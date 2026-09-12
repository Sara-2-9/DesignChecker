"""Bridge locale plugin Figma <-> DesignChecker (D29).

Il plugin Figma gira in una sandbox: puo' fare rete solo dall'iframe UI
e solo verso domini in allowlist. Il bridge e' un server HTTP locale
(solo 127.0.0.1, stdlib pura) che espone il validatore Python e i dati
del progetto (catalogo, token, screen JSON importati).

Endpoint:
  GET  /health         -> {"ok": true, "version": ..., "ai": {configured, label, model}}
  GET  /catalog        -> catalogo componenti (dict tipo -> entry)
  GET  /tokens         -> {hex_to_token: {...}, spacing: [{path, value}]}
  POST /validate       -> body: screen JSON; ritorna {"findings": [...], "errors": n}
  POST /import         -> come /validate + salva in imports/<id>.screen.json
  GET  /screen/<id>    -> screen JSON da imports/ (per il render su canvas)
  POST /review         -> body: screen JSON; ritorna {"critique": "..."} (D31)
  POST /fix            -> body: screen JSON; patch AI gated dal validatore (D31)

Sicurezza: ascolta solo su loopback; nessuna scrittura fuori da imports/.
Le chiamate AI escono solo verso il provider scelto dall'utente in `dck ai`;
l'output del modello passa SEMPRE dal validatore prima di toccare il JSON.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .loader import load_catalog, load_rules, load_tokens
from .tokens import TokenStore, dimension_to_float
from .validator import validate

DEFAULT_PORT = 7357


class Bridge:
    """Logica degli endpoint, separata dal server (testabile senza rete)."""

    def __init__(self, root: Path):
        self.root = root
        self.rules = load_rules(root / "rules")
        self.catalog = load_catalog(root / "components.catalog.yaml")
        self.tokens = TokenStore(load_tokens(root / "examples" / "tokens.json"))

    def _ai_config(self) -> dict:
        path = Path.home() / ".designchecker" / "config.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _ai_provider(self):
        """(Provider, model) dalla config, o (None, None)."""
        from . import ai as _ai
        config = self._ai_config()
        ai_cfg = config.get("ai") or {}
        pid, model = ai_cfg.get("provider"), ai_cfg.get("model")
        tmpl = next((p for p in _ai.PROVIDERS if p.pid == pid), None)
        if tmpl is None or not model:
            return None, None, config
        p = _ai.Provider(tmpl.pid, tmpl.label, tmpl.group, tmpl.style,
                         ai_cfg.get("base_url") or tmpl.base_url, tmpl.env_key,
                         [model], True, "", tmpl.alt_env,
                         temperature=tmpl.temperature)
        return p, model, config

    def health(self) -> dict:
        p, model, _ = self._ai_provider()
        return {"ok": True, "version": __version__, "bridge": "designchecker",
                "ai": {"configured": p is not None,
                       "label": p.label if p else None, "model": model}}

    def ai_review(self, screen: dict) -> dict:
        """Valutazione qualitativa consultiva (D31)."""
        from . import ai as _ai
        from . import patcher
        p, model, config = self._ai_provider()
        if p is None:
            return {"error": "Provider AI non configurato: lancia `dck ai`"}
        findings = validate(screen, self.rules, self.tokens, self.catalog)
        messages = patcher.build_review_prompt(screen, findings)
        try:
            return {"critique": _ai.chat(p, model, messages, config).strip()}
        except Exception as e:
            return {"error": f"Il provider non risponde: {e}"}

    def ai_fix(self, screen: dict) -> dict:
        """Patch AI gated dal validatore (D31). Se accettata, salva in imports/."""
        from . import ai as _ai
        from . import patcher
        p, model, config = self._ai_provider()
        if p is None:
            return {"error": "Provider AI non configurato: lancia `dck ai`"}
        findings = validate(screen, self.rules, self.tokens, self.catalog)

        def validate_fn(scr):
            fs = validate(scr, self.rules, self.tokens, self.catalog)
            return [f for f in fs if f.severity == "error"], \
                   [f for f in fs if f.severity == "warning"]

        def chat_fn(messages):
            return _ai.chat(p, model, messages, config)

        try:
            result = patcher.fix_loop(screen, findings, validate_fn, chat_fn,
                                      token_paths=list(self.tokens.flat))
        except Exception as e:
            return {"error": f"Il provider non risponde: {e}"}
        if result["applied"]:
            out_dir = self.root / "imports"
            out_dir.mkdir(exist_ok=True)
            screen_id = result["screen"].get("meta", {}).get("id", "screen")
            out_path = out_dir / f"{screen_id}.screen.json"
            out_path.write_text(json.dumps(result["screen"], indent=2,
                                           ensure_ascii=False), encoding="utf-8")
            result["path"] = str(out_path)
        return result


    def catalog_payload(self) -> dict:
        return self.catalog

    def tokens_payload(self) -> dict:
        hex_to_token: dict[str, str] = {}
        spacing: list[dict] = []
        flat: dict[str, object] = {}
        for path in self.tokens.flat:
            value = self.tokens.resolve_path(path)
            flat[path] = value
            if isinstance(value, str) and value.startswith("#"):
                hex_to_token[value.upper()] = path
            if path.startswith("spacing."):
                num = dimension_to_float(value)
                if num is not None:
                    spacing.append({"path": path, "value": num})
        return {"hex_to_token": hex_to_token, "spacing": spacing, "flat": flat}

    def validate_screen(self, screen: dict) -> dict:
        findings = validate(screen, self.rules, self.tokens, self.catalog)
        return {
            "findings": [
                {"severity": f.severity, "rule_id": f.rule_id, "node_id": f.node_id,
                 "message": f.message, "suggestion": f.suggestion,
                 "source": f.source, "source_url": f.source_url}
                for f in findings
            ],
            "errors": len([f for f in findings if f.severity == "error"]),
            "exceptions": screen.get("meta", {}).get("exceptions_applied", []),
        }

    @staticmethod
    def _sha(text: str) -> str:
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def import_screen(self, screen: dict) -> dict:
        result = self.validate_screen(screen)
        out_dir = self.root / "imports"
        out_dir.mkdir(exist_ok=True)
        screen_id = screen.get("meta", {}).get("id", "screen")
        out_path = out_dir / f"{screen_id}.screen.json"
        sidecar = out_dir / f".{screen_id}.export.sha256"
        new_content = json.dumps(screen, indent=2, ensure_ascii=False)

        # Anti-perdita: se il file su disco e' stato modificato FUORI dal
        # canale export (es. un fix AI) rispetto all'ultimo export noto,
        # salvalo prima di sovrascriverlo e avvisa il plugin (D29/D31).
        if out_path.exists() and sidecar.exists():
            disk = out_path.read_text(encoding="utf-8")
            last_export_sha = sidecar.read_text(encoding="utf-8").strip()
            if self._sha(disk) != last_export_sha and self._sha(disk) != self._sha(new_content):
                bak = out_path.with_suffix(out_path.suffix + ".preexport.bak")
                bak.write_text(disk, encoding="utf-8")
                result["notice"] = (
                    f"Il file era stato modificato fuori dal canvas (es. fix AI): "
                    f"la versione modificata e' salva in {bak.name}. Attenzione: "
                    "il frame esportato e' piu' vecchio del fix — aggiorna il "
                    "frame renderizzato, non quello originale.")

        out_path.write_text(new_content, encoding="utf-8")
        sidecar.write_text(self._sha(new_content), encoding="utf-8")
        result["path"] = str(out_path)
        return result

    def get_screen(self, screen_id: str) -> dict | None:
        from .codegen import kebab
        # normalizza: "Home2" -> "home2" (l'id dei file e' sempre kebab-case)
        safe = kebab(screen_id)
        safe = "".join(c for c in safe if c.isalnum() or c in "-_")  # anti path traversal
        path = self.root / "imports" / f"{safe}.screen.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_screens(self) -> list[str]:
        """Id degli screen importati (per l'autocompletamento nel plugin)."""
        imports = self.root / "imports"
        if not imports.is_dir():
            return []
        return sorted(p.name[: -len(".screen.json")] for p in imports.glob("*.screen.json"))


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict | None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_OPTIONS(self):  # preflight CORS dal plugin
            self._send(204, None)

        def do_GET(self):
            if self.path == "/health":
                self._send(200, bridge.health())
            elif self.path == "/catalog":
                self._send(200, bridge.catalog_payload())
            elif self.path == "/tokens":
                self._send(200, bridge.tokens_payload())
            elif self.path == "/screens":
                self._send(200, {"screens": bridge.list_screens()})
            elif self.path.startswith("/screen/"):
                screen = bridge.get_screen(self.path[len("/screen/"):])
                self._send(200, screen) if screen else self._send(404, {"error": "non trovato"})
            else:
                self._send(404, {"error": "endpoint sconosciuto"})

        def do_POST(self):
            try:
                payload = self._body()
            except json.JSONDecodeError:
                self._send(400, {"error": "JSON non valido"})
                return
            screen = payload.get("screen", payload)
            if self.path == "/validate":
                self._send(200, bridge.validate_screen(screen))
            elif self.path == "/import":
                self._send(200, bridge.import_screen(screen))
            elif self.path == "/review":
                self._send(200, bridge.ai_review(screen))
            elif self.path == "/fix":
                self._send(200, bridge.ai_fix(screen))
            else:
                self._send(404, {"error": "endpoint sconosciuto"})

        def log_message(self, fmt, *args):  # silenzia il log per richiesta
            pass

    return Handler


def serve(root: Path, port: int = DEFAULT_PORT) -> None:
    import socket
    import threading

    bridge = Bridge(root)
    handler = make_handler(bridge)

    servers: list[ThreadingHTTPServer] = []

    class V6Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    # localhost puo' risolversi in 127.0.0.1 O ::1 (Chromium sceglie):
    # ascoltiamo su entrambe le famiglie, ::1 best-effort (D29).
    servers.append(ThreadingHTTPServer(("127.0.0.1", port), handler))
    try:
        servers.append(V6Server(("::1", port), handler))
    except OSError:
        pass  # IPv6 disabilitato su questa macchina: va bene lo stesso

    for server in servers[1:]:
        threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"DesignChecker bridge attivo su http://localhost:{port}")
    print("Il plugin Figma ora parla con questo processo. Ctrl+C per fermare.")
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        print("\nBridge fermato.")
        for server in servers:
            server.shutdown()

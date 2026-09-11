"""Bridge locale plugin Figma <-> DesignChecker (D29).

Il plugin Figma gira in una sandbox: puo' fare rete solo dall'iframe UI
e solo verso domini in allowlist. Il bridge e' un server HTTP locale
(solo 127.0.0.1, stdlib pura) che espone il validatore Python e i dati
del progetto (catalogo, token, screen JSON importati).

Endpoint:
  GET  /health         -> {"ok": true, "version": ...}
  GET  /catalog        -> catalogo componenti (dict tipo -> entry)
  GET  /tokens         -> {hex_to_token: {...}, spacing: [{path, value}]}
  POST /validate       -> body: screen JSON; ritorna {"findings": [...], "errors": n}
  POST /import         -> come /validate + salva in imports/<id>.screen.json
  GET  /screen/<id>    -> screen JSON da imports/ (per il render su canvas)

Sicurezza: ascolta solo su loopback; nessuna scrittura fuori da imports/.
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

    def health(self) -> dict:
        return {"ok": True, "version": __version__, "bridge": "designchecker"}

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
        }

    def import_screen(self, screen: dict) -> dict:
        out_dir = self.root / "imports"
        out_dir.mkdir(exist_ok=True)
        screen_id = screen.get("meta", {}).get("id", "screen")
        out_path = out_dir / f"{screen_id}.screen.json"
        out_path.write_text(json.dumps(screen, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        result = self.validate_screen(screen)
        result["path"] = str(out_path)
        return result

    def get_screen(self, screen_id: str) -> dict | None:
        safe = "".join(c for c in screen_id if c.isalnum() or c in "-_")  # anti path traversal
        path = self.root / "imports" / f"{safe}.screen.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


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

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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .loader import load_catalog, load_rules, load_tokens
from .tokens import (TokenStore, dimension_to_float, hex_to_token_map,
                     is_themed, THEME_KEYS)
from .validator import resolve_theme, rules_for_platform, validate

DEFAULT_PORT = 7357


class Bridge:
    """Logica degli endpoint, separata dal server (testabile senza rete)."""

    def __init__(self, root: Path, autogen: Path | None = None,
                 log: bool = True, verbose_ai: bool = False):
        self.root = root
        self.autogen = Path(autogen).expanduser() if autogen else None
        self.log_enabled = log
        self.verbose_ai = verbose_ai
        self.rules = load_rules(root / "rules")
        self.catalog = load_catalog(root / "components.catalog.yaml")
        self.tokens = TokenStore(load_tokens(root / "examples" / "tokens.json"))

    # ---------------------------------------------------------- log attivita'

    def _log(self, msg: str) -> None:
        """Log live del bridge (D37): ogni azione visibile nel terminale."""
        if self.log_enabled:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def client_log(self, message: str) -> dict:
        """D43: eventi che accadono DENTRO Figma (es. selezione di un frame)
        inoltrati dal plugin al log del terminale — il bridge altrimenti non
        potrebbe mai vederli. Troncato per sicurezza, nessuna scrittura."""
        message = str(message).strip()[:200]
        if message:
            self._log(f"🖥 plugin: {message}")
        return {"ok": True}

    def _log_block(self, title: str, text: str) -> None:
        """Blocco multi-riga nel log (D38): prompt e risposte AI completi.
        Attivo solo con --verbose: il traffico AI e' lungo, il default
        resta leggibile a colpo d'occhio."""
        if not (self.log_enabled and self.verbose_ai):
            return
        lines = text.splitlines() or [""]
        self._log(f"  ┌─ {title} ({len(text)} caratteri, {len(lines)} righe)")
        for ln in lines:
            print(f"  │ {ln}", flush=True)
        print("  └─", flush=True)

    @staticmethod
    def _count_nodes(node: dict) -> int:
        return 1 + sum(Bridge._count_nodes(c)
                       for c in node.get("children", []) or [])

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
                       "label": p.label if p else None, "model": model},
                "autogen": str(self.autogen) if self.autogen else None,
                "metro": self._metro_running()}

    # ---------------------------------------------------------- autogen (D36)

    @staticmethod
    def _metro_running(port: int = 8081) -> bool:
        """Metro risponde su /status quando e' attivo: se gira, l'app nel
        simulatore si aggiorna da sola dopo ogni autogen (Fast Refresh)."""
        import urllib.request
        try:
            urllib.request.urlopen(f"http://localhost:{port}/status", timeout=0.6)
            return True
        except Exception:
            return False

    def _autogen_app(self, screen: dict) -> dict | None:
        """Rigenera il progetto Expo dopo ogni import/fix (D36): l'utente non
        tocca piu' il terminale. La cartella e' protetta da un marker: se
        esiste, e' piena e NON e' stata creata da noi, ci rifiutiamo di
        sovrascrivere (mai distruggere lavoro altrui)."""
        if not self.autogen:
            return None
        marker = self.autogen / ".designchecker-autogen"
        try:
            if self.autogen.exists() and any(self.autogen.iterdir()) \
                    and not marker.exists():
                return {"ok": False, "path": str(self.autogen),
                        "error": "cartella non vuota e non gestita da "
                                 "DesignChecker: scegline un'altra con "
                                 "--autogen <path>"}
            from .codegen import Codegen
            screen_id = screen.get("meta", {}).get("id", "screen")
            codegen = Codegen(screen, self.tokens, self.catalog,
                              assets_dir=self.root / "imports" / "assets" / screen_id)
            files = codegen.generate(self.autogen)
            marker.write_text("Cartella generata da `dck serve --autogen`: "
                              "non modificarla a mano.\n", encoding="utf-8")
            return {"ok": True, "path": str(self.autogen), "files": len(files),
                    "metro": self._metro_running()}
        except Exception as e:
            return {"ok": False, "path": str(self.autogen),
                    "error": str(e)[:200]}

    def ai_review(self, screen: dict, context: str | None = None,
                  platform: str | None = None,
                  theme: str | None = None) -> dict:
        """Valutazione qualitativa consultiva (D31), con contesto opzionale (D35)
        e piattaforma dichiarata (D39)."""
        from . import ai as _ai
        from . import patcher
        p, model, config = self._ai_provider()
        if p is None:
            return {"error": "Provider AI non configurato: lancia `dck ai`"}
        platform = self._resolve_platform(screen, platform)
        theme = resolve_theme(screen, self.tokens, theme)
        applicable = rules_for_platform(self.rules, platform)
        findings = validate(screen, self.rules, self.tokens, self.catalog,
                            platform=platform, theme=theme)
        messages = patcher.build_review_prompt(screen, findings, context=context,
                                               rules=applicable, platform=platform,
                                               theme=theme)
        self._log(f"→ /review [{platform}]: {p.label} · {model} — mando screen JSON, "
                  f"{len(findings)} finding, regolamento {platform}"
                  f"{' + contesto utente' if context else ''}")
        for m in messages:
            self._log_block(f"PROMPT → AI [{m['role']}]", m["content"])
        t0 = time.monotonic()
        try:
            critique = _ai.chat(p, model, messages, config).strip()
            self._log_block("RISPOSTA ← AI (parere)", critique)
            self._log(f"  ✓ parere ricevuto in {time.monotonic() - t0:.1f}s "
                      f"({len(critique)} caratteri) — nessuna scrittura, e' consultivo")
            return {"critique": critique}
        except Exception as e:
            self._log(f"  ✗ provider irraggiungibile: {e}")
            return {"error": f"Il provider non risponde: {e}"}

    def ai_fix(self, screen: dict, context: str | None = None,
               platform: str | None = None,
               theme: str | None = None) -> dict:
        """Patch AI gated dal validatore (D31/D35), con piattaforma (D39).
        Se accettata, salva in imports/ e rigenera il progetto Expo (D36)."""
        from . import ai as _ai
        from . import patcher
        p, model, config = self._ai_provider()
        if p is None:
            return {"error": "Provider AI non configurato: lancia `dck ai`"}
        platform = self._resolve_platform(screen, platform)
        theme = resolve_theme(screen, self.tokens, theme)
        applicable = rules_for_platform(self.rules, platform)
        findings = validate(screen, self.rules, self.tokens, self.catalog,
                            platform=platform, theme=theme)
        # catalogo path -> valore NEL TEMA ATTIVO: il modello vede i colori
        # veri (dark su design dark) e non puo' vandalizzare l'identita' (D42)
        token_values = {path: self.tokens.resolve_path(path, theme)
                        for path in self.tokens.flat}

        def validate_fn(scr):
            fs = validate(scr, self.rules, self.tokens, self.catalog,
                          platform=platform, theme=theme)
            return [f for f in fs if f.severity == "error"], \
                   [f for f in fs if f.severity == "warning"]

        logged_count = [0]  # messaggi gia' stampati (la conversazione cresce a ogni tentativo)

        def chat_fn(messages):
            if self.verbose_ai:
                for m in messages[logged_count[0]:]:
                    self._log_block(f"PROMPT → AI [{m['role']}]", m["content"])
                logged_count[0] = len(messages)
            raw = _ai.chat(p, model, messages, config)
            self._log_block("RISPOSTA ← AI (patch grezza)", raw)
            return raw

        self._log(f"→ /fix [{platform}]: {p.label} · {model} — il validatore fara' da "
                  f"gatekeeper sulla patch"
                  f"{' (contesto utente attivo)' if context else ''}")
        t0 = time.monotonic()
        try:
            result = patcher.fix_loop(screen, findings, validate_fn, chat_fn,
                                      token_paths=list(self.tokens.flat),
                                      token_values=token_values,
                                      context=context, rules=applicable,
                                      platform=platform, theme=theme)
        except Exception as e:
            self._log(f"  ✗ provider irraggiungibile: {e}")
            return {"error": f"Il provider non risponde: {e}"}
        for line in result.get("log", []):
            self._log(f"  {line}")
        self._log(f"  fix terminato in {time.monotonic() - t0:.1f}s — "
                  f"{'APPLICATO' if result['applied'] else 'NESSUNA PATCH ACCETTATA'}")
        if result["applied"]:
            out_dir = self.root / "imports"
            out_dir.mkdir(exist_ok=True)
            screen_id = result["screen"].get("meta", {}).get("id", "screen")
            out_path = out_dir / f"{screen_id}.screen.json"
            out_path.write_text(json.dumps(result["screen"], indent=2,
                                           ensure_ascii=False), encoding="utf-8")
            result["path"] = str(out_path)
            self._log(f"  scritto imports/{screen_id}.screen.json "
                      f"(versione corretta)")
            app = self._autogen_app(result["screen"])
            if app:
                result["app"] = app
                if app["ok"]:
                    self._log(f"  autogen: {app['files']} file rigenerati in "
                              f"{app['path']} · Metro: "
                              f"{'attivo' if app['metro'] else 'non attivo'}")
                else:
                    self._log(f"  autogen FERMO: {app['error']}")
        return result


    def catalog_payload(self) -> dict:
        return self.catalog

    def tokens_payload(self) -> dict:
        # hex -> token con tutte le varianti di tema (D42)
        hex_to_token = hex_to_token_map(self.tokens)
        spacing: list[dict] = []
        flat: dict[str, object] = {}
        for path in self.tokens.flat:
            raw = self.tokens.flat[path]
            if is_themed(raw):
                flat[path] = {t: self.tokens.resolve_path(path, t)
                              for t in THEME_KEYS}
            else:
                flat[path] = self.tokens.resolve_path(path)
            if path.startswith("spacing."):
                num = dimension_to_float(self.tokens.resolve_path(path))
                if num is not None:
                    spacing.append({"path": path, "value": num})
        return {"hex_to_token": hex_to_token, "spacing": spacing, "flat": flat}

    def validate_screen(self, screen: dict, platform: str | None = None,
                        theme: str | None = None) -> dict:
        platform = self._resolve_platform(screen, platform)
        theme = resolve_theme(screen, self.tokens, theme)
        findings = validate(screen, self.rules, self.tokens, self.catalog,
                            platform=platform, theme=theme)
        return {
            "findings": [
                {"severity": f.severity, "rule_id": f.rule_id, "node_id": f.node_id,
                 "message": f.message, "suggestion": f.suggestion,
                 "source": f.source, "source_url": f.source_url}
                for f in findings
            ],
            "errors": len([f for f in findings if f.severity == "error"]),
            "exceptions": screen.get("meta", {}).get("exceptions_applied", []),
            "platform": platform,
            "theme": theme,
        }

    @staticmethod
    def _resolve_platform(screen: dict, platform: str | None) -> str:
        """Priorita': scelta esplicita (plugin/CLI) > meta.platform salvata
        > 'both' (comportamento storico)."""
        from .validator import PLATFORMS
        for candidate in (platform,
                          (screen.get("meta", {}) or {}).get("platform")):
            if candidate in PLATFORMS:
                return candidate
        return "both"

    @staticmethod
    def _sha(text: str) -> str:
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def import_screen(self, screen: dict, assets: list | None = None,
                      platform: str | None = None,
                      theme: str | None = None) -> dict:
        # D39/D40: piattaforma e tema scelti nel plugin diventano parte del
        # contratto (meta) — review/fix/trace/codegen li ereditano da qui.
        platform = self._resolve_platform(screen, platform)
        screen.setdefault("meta", {})["platform"] = platform
        # theme "auto" (o assente) -> rilevamento deterministico dalla
        # luminanza dello sfondo radice
        theme = resolve_theme(screen, self.tokens, theme)
        screen["meta"]["theme"] = theme
        result = self.validate_screen(screen, platform, theme)
        out_dir = self.root / "imports"
        out_dir.mkdir(exist_ok=True)
        screen_id = screen.get("meta", {}).get("id", "screen")
        out_path = out_dir / f"{screen_id}.screen.json"
        sidecar = out_dir / f".{screen_id}.export.sha256"
        new_content = json.dumps(screen, indent=2, ensure_ascii=False)
        self._log(f"→ /import dal plugin: screen '{screen_id}' "
                  f"({self._count_nodes(screen.get('root', {}))} nodi, "
                  f"{len(assets or [])} asset in arrivo) — "
                  f"piattaforma: {platform}, tema: {theme} — "
                  f"validatore: {result['errors']} errori, "
                  f"{len(result['findings']) - result['errors']} warning")

        # Asset (D34): PNG esportati dal plugin (immagini/icone reali).
        # Path sanitizzato (solo basename) — mai scrivere fuori da imports/assets/.
        saved_assets = 0
        if assets:
            import base64
            assets_dir = out_dir / "assets" / screen_id
            assets_dir.mkdir(parents=True, exist_ok=True)
            for item in assets:
                if not isinstance(item, dict):
                    continue
                name = Path(str(item.get("path", ""))).name
                data = item.get("data_base64")
                if not name or not data:
                    continue
                try:
                    (assets_dir / name).write_bytes(base64.b64decode(data))
                    saved_assets += 1
                except Exception:
                    continue
            if saved_assets:
                result["assets_saved"] = saved_assets
                size_kb = sum(f.stat().st_size for f in assets_dir.iterdir()
                              if f.is_file()) // 1024
                self._log(f"  asset: {saved_assets} PNG salvati in "
                          f"imports/assets/{screen_id}/ ({size_kb} KB totali)")

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
                self._log(f"  sync guard: il file era modificato fuori dal "
                          f"canvas — backup in {bak.name}")

        out_path.write_text(new_content, encoding="utf-8")
        sidecar.write_text(self._sha(new_content), encoding="utf-8")
        result["path"] = str(out_path)
        self._log(f"  scritto imports/{screen_id}.screen.json (+ sidecar sha256)")

        # Autogen (D36): rigenera il progetto Expo ad ogni export dal canvas.
        app = self._autogen_app(screen)
        if app:
            result["app"] = app
            if app["ok"]:
                self._log(f"  autogen: {app['files']} file rigenerati in "
                          f"{app['path']} · Metro: "
                          f"{'attivo, l app si aggiorna da sola' if app['metro'] else 'non attivo (avvialo una volta)'}")
            else:
                self._log(f"  autogen FERMO: {app['error']}")
        return result

    # ---------------------------------------------------------- propose (padre+figli)

    def _save_preview(self, screen_id: str, preview_base64: str | None) -> dict | None:
        """Salva il PNG del frame in imports/previews/<id>.png (vision padre).
        Ritorna {"path", "kb"} o None. Base64 invalido -> None, mai eccezioni."""
        if not preview_base64:
            return None
        import base64 as _b64
        safe = "".join(c for c in screen_id if c.isalnum() or c in "-_") or "screen"
        try:
            raw = _b64.b64decode(preview_base64)
        except Exception:
            self._log("  preview PNG non decodificabile: proseguo senza vision")
            return None
        if len(raw) > 8 * 1024 * 1024:
            self._log("  preview PNG >8MB: scartata, proseguo senza vision")
            return None
        out_dir = self.root / "imports" / "previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{safe}.png"
        path.write_bytes(raw)
        info = {"path": str(path), "kb": max(len(raw) // 1024, 1)}
        self._log(f"  preview: PNG del frame salvato ({info['kb']} KB)")
        return info

    def _save_propose_input(self, screen_id: str, screen: dict) -> None:
        """Snapshot nascosto dell'input di /propose per riproducibilita'.

        imports/.<id>.propose-input.json (nascosto come i sidecar: non appare
        in /screens). Senza input salvato il test Pay-Frame non era
        riproducibile: restavano solo preview ed eval."""
        try:
            safe = "".join(c for c in screen_id if c.isalnum() or c in "-_") or "screen"
            out_dir = self.root / "imports"
            out_dir.mkdir(exist_ok=True)
            (out_dir / f".{safe}.propose-input.json").write_text(
                json.dumps(screen, indent=2, ensure_ascii=False), encoding="utf-8")
            self._log(f"  input salvato: imports/.{safe}.propose-input.json")
        except Exception:
            pass

    def _log_eval(self, screen_id: str, entry: dict) -> None:
        """Audit del perche' (D17): ruolo, fonti, divergenze, esito gate."""
        import json as _json
        out_dir = self.root / "imports"
        out_dir.mkdir(exist_ok=True)
        line = _json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "screen": screen_id, **entry}, ensure_ascii=False)
        with (out_dir / f"{screen_id}.eval.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def evaluate_role(self, screen: dict, context: str | None = None,
                      preview_base64: str | None = None) -> dict:
        """Solo diagnosi ruolo/scopo, niente scrittura (per `dck evaluate`)."""
        from .evaluator.classify import classify, heuristic_role
        p, model, config = self._ai_provider()
        if p is None:
            return {"error": "Provider AI non configurato: lancia `dck ai`"}
        from . import ai as _ai

        def chat_fn(messages):
            return _ai.chat(p, model, messages, config)

        self._log(f"→ /evaluate: {p.label} · {model} — classify ruolo")
        try:
            role = classify(screen, chat_fn, context, preview_base64)
        except Exception as e:
            role = heuristic_role(screen)
            role["_fallback"] = str(e)[:120]
        return {"role": role}

    def propose_screen(self, screen: dict, preview_base64: str | None = None,
                       context: str | None = None, platform: str | None = None,
                       theme: str | None = None, baseline: bool = True,
                       search_fn=None, emit=None) -> dict:
        """Giro completo Proponi nuovo design: padre+figli -> gate validatore.

        emit(text) chiamato a ogni fase (streaming plugin + log console).
        Salva preview PNG, proposal JSON e eval.jsonl. Il frame originale
        non viene mai sovrascritto: la proposta va in <id>.ai-proposal.screen.json.
        """
        from . import ai as _ai
        from . import patcher
        from .evaluator.orchestrator import run_propose
        from .evaluator.websearch import duckduckgo_search
        p, model, config = self._ai_provider()
        if p is None:
            return {"error": "Provider AI non configurato: lancia `dck ai`"}
        platform = self._resolve_platform(screen, platform)
        theme = resolve_theme(screen, self.tokens, theme)
        screen_id = screen.get("meta", {}).get("id", "screen")
        if search_fn is None:
            search_fn = duckduckgo_search  # ricerca reale, stdlib, mai eccezioni

        def _emit(t: str) -> None:
            self._log(f"  {t}")
            if emit is not None:
                try:
                    emit(t)
                except Exception:
                    pass

        self._log(f"→ /propose dal plugin: screen '{screen_id}' [{platform} · tema {theme}]"
                  f"{' + contesto' if context else ''}"
                  f"{' (baseline OFF: solo JSON+PNG+ricerca)' if not baseline else ''}")
        self._save_propose_input(screen_id, screen)
        preview = self._save_preview(screen_id, preview_base64)
        if preview_base64 and not preview:
            _emit("vision non disponibile: valuto dal solo JSON")
        elif preview and not _ai.supports_vision(p, model):
            _emit("modello senza vision dichiarata: il PNG resta agli atti, valuto dal JSON")

        base = self.validate_screen(screen, platform, theme)
        _emit(f"baseline deterministica: {base['errors']} errori, "
              f"{len(base['findings']) - base['errors']} warning (parere, non verita')")

        token_values = {path: self.tokens.resolve_path(path, theme)
                        for path in self.tokens.flat}

        def chat_fn(messages):
            # --verbose: prompt e risposte completi anche per /propose,
            # come gia' avviene per /review e /fix (D38)
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, list):
                    text = "\n".join(p.get("text", "") for p in content
                                     if isinstance(p, dict) and p.get("type") == "text")
                    if any(isinstance(p, dict) and p.get("type") == "image_url"
                           for p in content):
                        text += "\n[+ PNG del frame allegato]"
                    content = text
                self._log_block(f"PROMPT → AI [{m.get('role')}]", str(content))
            raw = _ai.chat(p, model, messages, config)
            self._log_block("RISPOSTA ← AI (grezza)", raw)
            return raw

        t0 = time.monotonic()
        def base_findings():
            from .validator import validate as _v
            return _v(screen, self.rules, self.tokens, self.catalog,
                      platform=platform, theme=theme)
        try:
            prop = run_propose(screen, base_findings(), chat_fn, search_fn,
                               token_paths=list(self.tokens.flat),
                               token_values=token_values, context=context,
                               platform=platform, theme=theme,
                               preview_base64=preview_base64 if preview else None,
                               baseline=baseline,
                               cache_dir=self.root / ".designchecker" / "research",
                               emit=_emit)
        except Exception as e:
            self._log(f"  ✗ orchestratore fallito: {e}")
            return {"error": f"Orchestratore fallito: {e}"}

        # gate finale: l'unico che decide (il padre propone, mai valida)
        def validate_fn(scr):
            from .validator import validate as _v
            fs = _v(scr, self.rules, self.tokens, self.catalog,
                    platform=platform, theme=theme)
            return [f for f in fs if f.severity == "error"], \
                   [f for f in fs if f.severity == "warning"]

        gate = patcher.gate_propose(screen, prop["ops"], validate_fn)
        dur = time.monotonic() - t0
        before, after = gate["before"], gate["after"]
        _emit(f"gate validatore: {before[0]}→{after[0]} errori, {before[1]}→{after[1]} warning "
              f"in {dur:.1f}s — {'ACCETTATA' if gate['applied'] else 'RIFIUTATA: ' + gate['detail'][:120]}")

        result: dict = {
            "role": prop["role"], "sources": prop["sources"],
            "blind": prop["blind"], "applied": gate["applied"],
            "before": list(before), "after": list(after),
            "ops": [{"op": o.get("op"), "path": o.get("path")} for o in gate["ops"]],
            "log": prop["log"], "platform": platform, "theme": theme,
            "baseline": baseline,
        }
        self._log_eval(screen_id, {"role": prop["role"], "platform": platform,
                                   "theme": theme, "before": list(before),
                                   "after": list(after), "applied": gate["applied"],
                                   "sources": [s["url"] for s in prop["sources"]],
                                   "ops": len(gate["ops"])})
        if gate["applied"]:
            out_dir = self.root / "imports"
            out_dir.mkdir(exist_ok=True)
            proposal = gate["screen"]
            proposal.setdefault("meta", {})["platform"] = platform
            proposal["meta"]["theme"] = theme
            proposal["meta"]["proposal_of"] = screen_id
            out_path = out_dir / f"{screen_id}.ai-proposal.screen.json"
            bak = out_dir / f"{screen_id}.ai-proposal.screen.json.bak"
            if out_path.exists() and not bak.exists():
                bak.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
            out_path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            result["path"] = str(out_path)
            result["screen"] = proposal
            self._log(f"  proposta salvata: imports/{screen_id}.ai-proposal.screen.json "
                      f"(originale intatto)")
            app = self._autogen_app(proposal)
            if app:
                result["app"] = app
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
                sid = self.path[len("/screen/"):]
                screen = bridge.get_screen(sid)
                bridge._log(f"→ /screen/{sid}: il plugin chiede lo screen "
                            f"(render su canvas) — {'trovato' if screen else 'NON trovato'}")
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
            platform = payload.get("platform")
            theme = payload.get("theme")
            if self.path == "/validate":
                result = bridge.validate_screen(screen, platform, theme)
                bridge._log(f"→ /validate [{result['platform']}]: {result['errors']} errori, "
                            f"{len(result['findings']) - result['errors']} warning "
                            f"(nessuna scrittura)")
                self._send(200, result)
            elif self.path == "/import":
                self._send(200, bridge.import_screen(screen, assets=payload.get("assets"),
                                                     platform=platform, theme=theme))
            elif self.path == "/review":
                self._send(200, bridge.ai_review(screen, context=payload.get("context"),
                                                 platform=platform, theme=theme))
            elif self.path == "/fix":
                self._send(200, bridge.ai_fix(screen, context=payload.get("context"),
                                              platform=platform, theme=theme))
            elif self.path == "/client-log":
                # eventi lato Figma (selezione frame, D43): solo log, nessuna scrittura
                self._send(200, bridge.client_log(payload.get("message", "")))
            elif self.path == "/evaluate":
                self._send(200, bridge.evaluate_role(
                    screen, context=payload.get("context"),
                    preview_base64=payload.get("preview_base64")))
            elif self.path.startswith("/propose"):
                stream = "stream=1" in (self.path.split("?", 1)[1] if "?" in self.path else "")
                baseline = payload.get("baseline", True)
                if baseline in ("false", "0", False):
                    baseline = False
                else:
                    baseline = True if baseline is None else bool(baseline)
                if not stream:
                    self._send(200, bridge.propose_screen(
                        screen, preview_base64=payload.get("preview_base64"),
                        context=payload.get("context"), platform=platform,
                        theme=theme, baseline=baseline))
                else:
                    self._send_propose_stream(bridge, screen, payload, platform, theme, baseline)
            else:
                self._send(404, {"error": "endpoint sconosciuto"})

        def _send_propose_stream(self, bridge, screen, payload, platform, theme, baseline):
            """Streaming NDJSON riga per fase per il plugin (fasi live in Figma).
            Ogni riga: {"phase": "..."}; ultima riga: {"done": true, "result": {...}}."""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            phases: list[str] = []

            def emit(text: str) -> None:
                phases.append(text)
                try:
                    self.wfile.write((json.dumps({"phase": text},
                                                 ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass

            result = bridge.propose_screen(
                screen, preview_base64=payload.get("preview_base64"),
                context=payload.get("context"), platform=platform,
                theme=theme, baseline=baseline, emit=emit)
            try:
                self.wfile.write((json.dumps({"done": True, "result": result},
                                             ensure_ascii=False) + "\n").encode("utf-8"))
            except Exception:
                pass

        def log_message(self, fmt, *args):  # silenzia il log per richiesta
            pass

    return Handler


def serve(root: Path, port: int = DEFAULT_PORT, autogen: Path | None = None,
          log: bool = True, verbose_ai: bool = False) -> None:
    import socket
    import threading

    bridge = Bridge(root, autogen=autogen, log=log, verbose_ai=verbose_ai)
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
    if log:
        print("Log attivita' attivo: qui vedi ogni richiesta del plugin, "
              "cosa valida, cosa scrive, cosa manda all'AI (--quiet per spegnerlo)")
    if verbose_ai:
        print("Verbose AI attivo: vedrai il PROMPT completo inviato al modello "
              "e la RISPOSTA grezza che torna, per ogni /review, /fix e /propose")
    elif log:
        print("  (vuoi vedere anche prompt e risposte AI completi? "
              "riavvia con --verbose)")
    if autogen:
        print(f"Autogen attivo: ogni export/fix rigenera l'app in {bridge.autogen}")
        print("  (Metro attivo? l'app nel simulatore si aggiorna da sola. "
              "Altrimenti, solo la prima volta: cd <cartella> && npm install && npx expo start)")
    print("Il plugin Figma ora parla con questo processo. Ctrl+C per fermare.")
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        print("\nBridge fermato.")
        for server in servers:
            server.shutdown()

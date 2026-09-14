"""Test del bridge locale plugin Figma <-> CLI (D29)."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from designchecker.loader import load_screen
from designchecker.serve import Bridge, make_handler

ROOT = Path(__file__).resolve().parent.parent


class TestBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge(ROOT)

    def test_health(self):
        self.assertTrue(self.bridge.health()["ok"])

    def test_tokens_payload(self):
        payload = self.bridge.tokens_payload()
        self.assertIn("#FFFFFF", {k.upper() for k in payload["hex_to_token"]})
        self.assertTrue(payload["spacing"])
        self.assertIn("color.brand.primary", payload["flat"])

    def test_validate_schermata_conforme(self):
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        result = self.bridge.validate_screen(screen)
        self.assertEqual(result["errors"], 0)

    def test_validate_schermata_con_violazioni(self):
        screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
        result = self.bridge.validate_screen(screen)
        self.assertGreater(result["errors"], 0)
        f0 = result["findings"][0]
        for key in ("severity", "rule_id", "node_id", "message", "suggestion"):
            self.assertIn(key, f0)

    def test_import_e_get_screen(self):
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        result = self.bridge.import_screen(screen)
        self.assertTrue(Path(result["path"]).is_file())
        loaded = self.bridge.get_screen(screen["meta"]["id"])
        self.assertEqual(loaded["meta"]["id"], screen["meta"]["id"])

    def test_get_screen_anti_traversal(self):
        self.assertIsNone(self.bridge.get_screen("../../etc/passwd"))
        self.assertIsNone(self.bridge.get_screen("non-esiste"))

    def test_get_screen_normalizza_maiuscole(self):
        """'Home' deve trovare home.screen.json (id kebab-case)."""
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        self.bridge.import_screen(screen)
        self.assertIsNotNone(self.bridge.get_screen("Home"))

    def test_list_screens(self):
        self.assertIn("home", self.bridge.list_screens())


class TestBridgeHTTP(unittest.TestCase):
    """Roundtrip reale via HTTP su porta effimera."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Bridge(ROOT)))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as res:
            return json.loads(res.read().decode("utf-8"))

    def test_health_http(self):
        self.assertTrue(self._get("/health")["ok"])

    def test_validate_http(self):
        screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/validate",
            data=json.dumps({"screen": screen}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode("utf-8"))
        self.assertGreater(data["errors"], 0)

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/niente")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()


class TestEccezioniEGradienti(unittest.TestCase):
    """D30: eccezioni giustificate + sfondi da gradiente."""

    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge(ROOT)

    def test_eccezione_giustificata_rimuove_finding(self):
        import copy
        from designchecker.validator import validate
        from designchecker.loader import load_rules
        screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
        rules = load_rules(ROOT / "rules")
        base = validate(copy.deepcopy(screen), rules, self.bridge.tokens, self.bridge.catalog)
        self.assertTrue(base)
        # copro TUTTE le regole trovate con eccezioni motivate sul root
        mod = copy.deepcopy(screen)
        rule_ids = sorted({f.rule_id.split(".")[0] for f in base})
        # eccezione a livello di prefisso regola sul nodo radice e sui figli
        def add_exc(node):
            node.setdefault("meta", {})["exceptions"] = [
                {"rule": r, "reason": "test"} for r in rule_ids]
            for c in node.get("children", []) or []:
                add_exc(c)
        add_exc(mod["root"])
        after = validate(mod, rules, self.bridge.tokens, self.bridge.catalog)
        self.assertEqual(after, [])
        self.assertTrue(mod["meta"]["exceptions_applied"])

    def test_eccezione_senza_motivo_non_vale(self):
        import copy
        from designchecker.validator import validate
        from designchecker.loader import load_rules
        screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
        rules = load_rules(ROOT / "rules")
        mod = copy.deepcopy(screen)

        def add_exc(node):
            node.setdefault("meta", {})["exceptions"] = [{"rule": "wcag", "reason": ""}]
            for c in node.get("children", []) or []:
                add_exc(c)
        add_exc(mod["root"])
        base = validate(copy.deepcopy(screen), rules, self.bridge.tokens, self.bridge.catalog)
        after = validate(mod, rules, self.bridge.tokens, self.bridge.catalog)
        self.assertEqual(len(after), len(base))  # senza reason: nessuna eccezione

    def test_gradiente_media_e_visual_bg(self):
        from designchecker.importer_figma import _fill_hex
        fills = [{"type": "GRADIENT_LINEAR", "visible": True, "gradientStops": [
            {"color": {"r": 1, "g": 1, "b": 1, "a": 1}},
            {"color": {"r": 0, "g": 0, "b": 0, "a": 1}}]}]
        hex_value, visual = _fill_hex(fills)
        self.assertEqual(hex_value, "#808080")
        self.assertEqual(visual, "gradient")
        img, visual_img = _fill_hex([{"type": "IMAGE", "visible": True}])
        self.assertIsNone(img)
        self.assertEqual(visual_img, "image")

    def test_visual_bg_esenta_hardcoded(self):
        """Un background approssimato da gradiente non e' un hex hard-coded."""
        import copy
        from designchecker.validator import validate
        from designchecker.loader import load_rules
        rules = load_rules(ROOT / "rules")
        screen = {
            "schema_version": "0.1.0",
            "meta": {"id": "t", "name": "t"},
            "root": {"id": "t", "type": "Screen",
                     "layout": {"safe_area": True},
                     "style": {"background": "#808080"},
                     "meta": {"visual_bg": "gradient"},
                     "children": []},
        }
        findings = validate(screen, rules, self.bridge.tokens, self.bridge.catalog)
        self.assertNotIn("ds.no-hardcoded-value", {f.rule_id for f in findings})


class TestImportSyncGuard(unittest.TestCase):
    """Anti-perdita: un export non deve mai cancellare modifiche esterne
    (es. fix AI) senza backup e avviso."""

    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge(ROOT)
        cls.imports = ROOT / "imports"
        cls.victim = cls.imports / "test-sync-guard.screen.json"
        cls.sidecar = cls.imports / ".test-sync-guard.export.sha256"
        cls.bak = cls.imports / "test-sync-guard.screen.json.preexport.bak"

    @classmethod
    def tearDownClass(cls):
        for p in (cls.victim, cls.sidecar, cls.bak):
            p.unlink(missing_ok=True)

    def _screen(self, text):
        return {"schema_version": "0.1",
                "meta": {"id": "test-sync-guard", "name": "T"},
                "root": {"id": "r", "type": "Screen",
                         "children": [{"id": "t1", "type": "Text",
                                       "props": {"content": text}}]}}

    def test_export_poi_modifica_esterna_poi_export(self):
        # 1. export dal canvas: scrive file + sidecar
        r1 = self.bridge.import_screen(self._screen("v1"))
        self.assertNotIn("notice", r1)
        self.assertTrue(self.sidecar.exists())

        # 2. modifica esterna (simula `dck fix`)
        import json as _json
        fixed = self._screen("v2-corretto-dal-fix")
        self.victim.write_text(_json.dumps(fixed, indent=2), encoding="utf-8")

        # 3. nuovo export dal canvas (contenuto vecchio): backup + notice
        r3 = self.bridge.import_screen(self._screen("v3-dal-canvas"))
        self.assertIn("notice", r3)
        self.assertTrue(self.bak.exists())
        self.assertIn("v2-corretto-dal-fix",
                      _json.loads(self.bak.read_text())["root"]["children"][0]
                      ["props"]["content"])

        # 4. export identico al disco: nessun falso positivo
        r4 = self.bridge.import_screen(self._screen("v3-dal-canvas"))
        self.assertNotIn("notice", r4)

    def test_export_normale_senza_sidecar_non_avvisa(self):
        # file preesistente senza sidecar (era pre-D31): primo export silenzioso
        self.sidecar.unlink(missing_ok=True)
        self.victim.write_text('{"meta": {"id": "test-sync-guard"}}',
                               encoding="utf-8")
        r = self.bridge.import_screen(self._screen("v1"))
        self.assertNotIn("notice", r)


class TestBridgeAssets(unittest.TestCase):
    """D34: gli asset PNG esportati dal plugin arrivano in base64 e vengono
    salvati in imports/assets/<screen_id>/ (path sanitizzato al basename)."""

    PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge(ROOT)
        cls.imports = ROOT / "imports"
        cls.screen_file = cls.imports / "test-assets.screen.json"
        cls.sidecar = cls.imports / ".test-assets.export.sha256"
        cls.assets_dir = cls.imports / "assets" / "test-assets"

    @classmethod
    def tearDownClass(cls):
        import shutil
        cls.screen_file.unlink(missing_ok=True)
        cls.sidecar.unlink(missing_ok=True)
        shutil.rmtree(cls.assets_dir, ignore_errors=True)

    def _screen(self):
        return {"schema_version": "0.1",
                "meta": {"id": "test-assets", "name": "T"},
                "root": {"id": "r", "type": "Screen",
                         "children": [{"id": "img", "type": "Image",
                                       "props": {"asset": "assets/test-assets/f.png"}}]}}

    def test_asset_salvato_e_sanitizzato(self):
        result = self.bridge.import_screen(self._screen(), assets=[
            {"path": "f.png", "data_base64": self.PNG_B64},
            {"path": "../../etc/evil.png", "data_base64": self.PNG_B64},
            {"path": "", "data_base64": self.PNG_B64},
            {"path": "rotto.png", "data_base64": "!!!non-base64!!!"},
        ])
        self.assertEqual(result.get("assets_saved"), 2)
        self.assertTrue((self.assets_dir / "f.png").is_file())
        self.assertTrue((self.assets_dir / "evil.png").is_file())
        self.assertFalse((self.imports / "evil.png").exists())
        self.assertFalse((self.assets_dir / "rotto.png").exists())

    def test_senza_assets_niente_directory(self):
        import shutil
        shutil.rmtree(self.assets_dir, ignore_errors=True)
        result = self.bridge.import_screen(self._screen())
        self.assertNotIn("assets_saved", result)
        self.assertFalse(self.assets_dir.exists())


class TestBridgeAutogen(unittest.TestCase):
    """D36: con --autogen il bridge rigenera il progetto Expo a ogni
    import/fix. La cartella e' protetta da marker: mai sovrascrivere
    una cartella non creata da DesignChecker."""

    @classmethod
    def tearDownClass(cls):
        imports = ROOT / "imports"
        (imports / "auto-app.screen.json").unlink(missing_ok=True)
        (imports / ".auto-app.export.sha256").unlink(missing_ok=True)

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="dc-autogen-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _screen(self):
        return {"schema_version": "0.1",
                "meta": {"id": "auto-app", "name": "Auto", "route": "/"},
                "root": {"id": "r", "type": "Screen",
                         "children": [{"id": "t", "type": "Text",
                                       "props": {"content": "ciao"}}]}}

    def test_import_genera_progetto_expo(self):
        out = self.tmp / "app"
        bridge = Bridge(ROOT, autogen=out)
        result = bridge.import_screen(self._screen())
        self.assertTrue(result["app"]["ok"])
        self.assertTrue((out / "src" / "screens" / "auto-app" / "index.tsx").is_file())
        self.assertTrue((out / "package.json").is_file())
        self.assertTrue((out / ".designchecker-autogen").is_file())

    def test_rifiuta_cartella_non_creata_da_noi(self):
        out = self.tmp / "app"
        out.mkdir()
        (out / "mio-file.txt").write_text("non toccare", encoding="utf-8")
        bridge = Bridge(ROOT, autogen=out)
        result = bridge.import_screen(self._screen())
        self.assertFalse(result["app"]["ok"])
        self.assertFalse((out / "package.json").exists())
        self.assertEqual((out / "mio-file.txt").read_text(encoding="utf-8"),
                         "non toccare")

    def test_senza_autogen_nessuna_chiave_app(self):
        bridge = Bridge(ROOT)
        result = bridge.import_screen(self._screen())
        self.assertNotIn("app", result)


class TestBridgeLog(unittest.TestCase):
    """D37: log live del bridge — ogni azione visibile, --quiet la spegne."""

    @classmethod
    def tearDownClass(cls):
        imports = ROOT / "imports"
        (imports / "test-log.screen.json").unlink(missing_ok=True)
        (imports / ".test-log.export.sha256").unlink(missing_ok=True)

    def _screen(self):
        return {"schema_version": "0.1",
                "meta": {"id": "test-log", "name": "T"},
                "root": {"id": "r", "type": "Screen",
                         "children": [{"id": "t", "type": "Text",
                                       "props": {"content": "ciao"}}]}}

    def test_log_visibile_di_default(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            Bridge(ROOT).import_screen(self._screen())
        out = buf.getvalue()
        self.assertIn("/import", out)
        self.assertIn("test-log", out)
        self.assertIn("scritto imports/test-log.screen.json", out)

    def test_log_silenziato(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            Bridge(ROOT, log=False).import_screen(self._screen())
        self.assertEqual(buf.getvalue(), "")


class TestTraceCommand(unittest.TestCase):
    """D37: `dck trace` stampa la mappa completa della pipeline."""

    def test_trace_stampa_tutte_le_fasi(self):
        import io
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        from designchecker.cli import _trace_command
        from designchecker.loader import load_rules

        args = SimpleNamespace(screen=ROOT / "examples" / "home.screen.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            _trace_command(args, ROOT, load_rules(ROOT / "rules"))
        out = buf.getvalue()
        for sezione in ("1. LETTURA", "2. VALIDAZIONE", "3. BRIDGE",
                        "4. AI", "5. CODEGEN", "6. APP"):
            self.assertIn(sezione, out)
        self.assertIn("src/screens/home/index.tsx", out)
        self.assertIn("home.screen.json", out)


class TestBridgeAI(unittest.TestCase):
    """Endpoint AI del bridge (D31) con provider finto: niente rete."""

    @classmethod
    def setUpClass(cls):
        cls.bridge = Bridge(ROOT)

    def _fake_provider(self):
        from designchecker import ai
        return ai.Provider("ollama", "Ollama", "A", "openai",
                           "http://localhost:11434/v1"), "qwen3:8b"

    def test_review_e_fix_richiedono_config(self):
        import designchecker.serve as serve_mod
        orig = Bridge._ai_provider
        Bridge._ai_provider = lambda self: (None, None, {})
        try:
            screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
            self.assertIn("error", self.bridge.ai_review(screen))
            self.assertIn("error", self.bridge.ai_fix(screen))
        finally:
            Bridge._ai_provider = orig

    def test_fix_applica_patch_e_salva(self):
        import designchecker.ai as ai_mod
        p, model = self._fake_provider()
        patch = [{"op": "replace", "path": "/root/style/background",
                  "value": "token:color.bg.primary"}]
        orig_provider = Bridge._ai_provider
        orig_chat = ai_mod.chat
        Bridge._ai_provider = lambda self: (p, model, {})
        ai_mod.chat = lambda *a, **k: json.dumps(patch)
        try:
            screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
            before_errors = self.bridge.validate_screen(screen)["errors"]
            result = self.bridge.ai_fix(screen)
            self.assertTrue(result.get("applied"), result.get("log"))
            self.assertEqual(result["ops"], patch)
            self.assertEqual(result["screen"]["root"]["style"]["background"],
                             "token:color.bg.primary")
            after_errors = self.bridge.validate_screen(result["screen"])["errors"]
            self.assertLess(after_errors, before_errors)
        finally:
            Bridge._ai_provider = orig_provider
            ai_mod.chat = orig_chat

    def test_review_ritorna_testo(self):
        import designchecker.ai as ai_mod
        p, model = self._fake_provider()
        orig_provider = Bridge._ai_provider
        orig_chat = ai_mod.chat
        Bridge._ai_provider = lambda self: (p, model, {})
        ai_mod.chat = lambda *a, **k: "Gerarchia ok, aumenta il respiro sotto il titolo."
        try:
            screen = load_screen(ROOT / "examples" / "home.screen.json")
            result = self.bridge.ai_review(screen)
            self.assertIn("Gerarchia", result.get("critique", ""))
        finally:
            Bridge._ai_provider = orig_provider
            ai_mod.chat = orig_chat

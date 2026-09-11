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

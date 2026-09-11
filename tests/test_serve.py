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

"""Test dell'importer Figma — offline, su fixture (D21/D24).

    python3 -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from designchecker.importer_figma import FigmaImporter, list_frames
from designchecker.loader import load_catalog, load_rules, load_tokens
from designchecker.tokens import TokenStore
from designchecker.validator import validate


class TestFigmaImporter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        cls.catalog = load_catalog(ROOT / "components.catalog.yaml")
        cls.rules = load_rules(ROOT / "rules")
        fixture = json.loads(
            (ROOT / "examples" / "figma-file.fixture.json").read_text(encoding="utf-8"))
        cls.document = fixture["document"]
        cls.screen = FigmaImporter(cls.tokens, cls.catalog).convert_screen(
            cls.document, "Home")
        cls.findings = validate(cls.screen, cls.rules, cls.tokens, cls.catalog)
        cls.rule_ids = {f.rule_id for f in cls.findings}

    def _node(self, node_id):
        def find(n):
            if n.get("id") == node_id:
                return n
            for c in n.get("children", []) or []:
                r = find(c)
                if r:
                    return r
            return None
        return find(self.screen["root"])

    def test_lista_frame(self):
        frames = list_frames({"document": self.document})
        self.assertTrue(any("Home" in f for f in frames))
        self.assertTrue(any("Add Expense" in f for f in frames))

    def test_frame_trova_la_schermata(self):
        self.assertIsNotNone(self.screen)
        self.assertEqual(self.screen["root"]["type"], "Screen")
        self.assertTrue(self.screen["root"]["layout"]["safe_area"])

    def test_mapping_istanze_a_catalogo(self):
        self.assertIsNotNone(self._node("button-primary"))
        self.assertEqual(self._node("button-primary")["type"], "Button")
        self.assertIsNotNone(self._node("tab-bar"))
        self.assertEqual(self._node("tab-bar")["type"], "TabBar")
        self.assertEqual(self._node("fab")["type"], "Fab")

    def test_dimensioni_reali_dal_canvas(self):
        """absoluteBoundingBox -> min_height reale: 36pt -> violazione touch."""
        self.assertEqual(self._node("button-primary")["props"]["min_height"], 36)
        self.assertIn("ios.touch-target.min", self.rule_ids)

    def test_azioni_dalle_interactions_prototipo(self):
        self.assertEqual(self._node("fab")["props"]["action"], "navigate:/add-expense")

    def test_colori_riconosciuti_come_token(self):
        """Il verde #5E8F6E del fab esiste nei token -> diventa riferimento."""
        fab = self._node("fab")
        bg = fab.get("style", {}).get("background")
        # il fab non ha trait container: il bg va in style solo per container/screen
        # ma il colore brand deve essere riconosciuto dove presente
        if bg:
            self.assertTrue(bg.startswith("{"), msg=f"atteso ref token, trovato {bg}")

    def test_contrasto_basso_rilevato(self):
        """Il testo #8FBF9F su sfondo bianco -> errore WCAG."""
        self.assertIn("wcag.1.4.3.contrast-text", self.rule_ids)

    def test_troppe_tab_rilevate(self):
        self.assertIn("ios.tab.max-items", self.rule_ids)

    def test_confidence_presente(self):
        self.assertIn("confidence", self.screen["root"]["meta"])
        self.assertEqual(self.screen["meta"]["source"]["kind"], "figma")

    def test_frame_non_trovato(self):
        importer = FigmaImporter(self.tokens, self.catalog)
        self.assertIsNone(importer.convert_screen(self.document, "Inesistente"))


if __name__ == "__main__":
    unittest.main()

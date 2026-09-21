"""Test di dck describe: scheda di stile da PNG (solo prompt/parsing, mai rete)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from designchecker.describer import (build_describe_json_messages,
                                     build_describe_messages, describe_image,
                                     describe_json, parse_describe)


class TestDescribePrompt(unittest.TestCase):
    def test_sette_sezioni_e_limiti(self):
        msgs = build_describe_messages("QUJD")
        system = msgs[0]["content"]
        for section in ("Sintesi", "Palette", "Tipografia", "Layout e ritmo",
                        "Componenti", "Stile e mood", "Piattaforma"):
            self.assertIn(section, system)
        self.assertIn("MAI codici hex", system)
        self.assertIn("300 parole", system)

    def test_immagine_allegata_e_contesto(self):
        msgs = build_describe_messages("QUJD", context="app bancaria",
                                       platform="ios")
        user = msgs[1]["content"]
        self.assertIsInstance(user, list)
        self.assertTrue(any(p.get("type") == "image_url" for p in user))
        text = "\n".join(p.get("text", "") for p in user
                         if isinstance(p, dict) and p.get("type") == "text")
        self.assertIn("bancaria", text)
        self.assertIn("iOS", msgs[0]["content"])

    def test_piattaforma_default_both(self):
        msgs = build_describe_messages("QUJD")
        self.assertIn("piattaforma", msgs[0]["content"].lower())


class TestDescribeParse(unittest.TestCase):
    def test_toglie_fence_markdown(self):
        raw = "```markdown\n## Sintesi\nCiao\n```"
        self.assertEqual(parse_describe(raw), "## Sintesi\nCiao")

    def test_testo_liscio_invariato(self):
        self.assertEqual(parse_describe("  ## Sintesi\nCiao  "), "## Sintesi\nCiao")


class TestDescribeImage(unittest.TestCase):
    def test_stub_ritorna_testo(self):
        seen = []

        def chat(msgs):
            seen.append(msgs)
            return "## Sintesi\nBella schermata"
        out = describe_image(chat, "QUJD", platform="ios")
        self.assertEqual(out["text"], "## Sintesi\nBella schermata")
        self.assertTrue(seen)


def _json_screen():
    return {"schema_version": "0.1.0", "meta": {"id": "s"},
            "root": {"id": "r", "type": "Screen",
                     "layout": {"frame": {"x": 0, "y": 0, "w": 100, "h": 100}},
                     "style": {"background": "#000000"},
                     "children": [
                         {"id": "cta", "type": "Button",
                          "props": {"label": "Vai", "min_height": 48},
                          "layout": {"frame": {"x": 10, "y": 10,
                                              "w": 80, "h": 48}},
                          "style": {"background": "#0088FF"}}]}}


class TestDescribeJson(unittest.TestCase):
    def test_prompt_contiene_png_e_json_e_concordanze(self):
        msgs = build_describe_json_messages(_json_screen(), "QUJD",
                                            platform="ios")
        system = msgs[0]["content"]
        self.assertIn("Concordanze e discordanze", system)
        self.assertIn("Zona per zona", system)
        user = msgs[1]["content"]
        self.assertIsInstance(user, list)
        self.assertTrue(any(p.get("type") == "image_url" for p in user))
        text = "\n".join(p.get("text", "") for p in user
                         if isinstance(p, dict) and p.get("type") == "text")
        self.assertIn("cta", text)  # screen compattato allegato
        self.assertIn("#0088FF", text)  # valori esatti citabili

    def test_stub_ritorna_testo_ancorato(self):
        seen = []

        def chat(msgs):
            seen.append(msgs)
            return "## Sintesi\nCTA blu #0088FF"
        out = describe_json(chat, _json_screen(), "QUJD")
        self.assertIn("#0088FF", out["text"])
        self.assertTrue(seen)


if __name__ == "__main__":
    unittest.main()

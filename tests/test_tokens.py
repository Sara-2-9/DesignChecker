"""Test dei token multi-tema (D42): $value {"light": ..., "dark": ...}."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from designchecker.loader import load_tokens
from designchecker.tokens import (TokenStore, effective_token_values,
                                  hex_saturation, hex_to_token_map, is_themed,
                                  screen_brand, themed_variants)


class TestMultiThemeTokens(unittest.TestCase):
    """Un path unico, due valori: il tema decide la risoluzione."""

    @classmethod
    def setUpClass(cls):
        cls.tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))

    def test_varianti_light_e_dark(self):
        t = self.tokens
        self.assertEqual(t.resolve_path("color.surface", "light"), "#F7F7F5")
        self.assertEqual(t.resolve_path("color.surface", "dark"), "#121212")
        self.assertEqual(t.resolve_path("color.text-primary", "dark"), "#F2F2F2")

    def test_alias_attraverso_la_variante(self):
        # surface-raised dark e' un alias: {color.neutral.800} -> #1C1C1E
        self.assertEqual(self.tokens.resolve_path("color.surface-raised", "dark"),
                         "#1C1C1E")

    def test_default_senza_tema_e_light(self):
        self.assertEqual(self.tokens.resolve_path("color.surface"), "#F7F7F5")
        self.assertEqual(self.tokens.resolve_value("{color.surface}"), "#F7F7F5")

    def test_token_non_tematizzato_invariato(self):
        # il brand e' identita': stesso valore in entrambi i temi
        for theme in ("light", "dark", None):
            self.assertEqual(self.tokens.resolve_path("color.brand.primary", theme),
                             "#5E8F6E")

    def test_helper_is_themed(self):
        self.assertTrue(is_themed(self.tokens.flat["color.surface"]))
        self.assertFalse(is_themed(self.tokens.flat["color.brand.primary"]))
        self.assertEqual(sorted(themed_variants({"light": "A", "dark": "B"})),
                         ["A", "B"])
        self.assertEqual(themed_variants("#123456"), ["#123456"])

    def test_hex_to_token_copre_entrambe_le_varianti(self):
        m = hex_to_token_map(self.tokens)
        # lo stesso path semantico risponde per il chiaro E per lo scuro
        self.assertEqual(m.get("#F7F7F5"), "color.surface")
        self.assertEqual(m.get("#121212"), "color.surface")
        self.assertEqual(m.get("#1C1C1E"), "color.surface-raised")
        # il primitivo resta raggiungibile per il suo hex specifico
        self.assertEqual(m.get("#3A3A3C"), "color.neutral.700")


class TestScreenBrand(unittest.TestCase):
    """D49: brand per-screen letto dal frame, default da tokens.json."""

    def test_screen_brand_valido(self):
        scr = {"meta": {"brand": {"color.brand.primary": "#0088FF"}}}
        self.assertEqual(screen_brand(scr), {"color.brand.primary": "#0088FF"})

    def test_screen_brand_scartati_non_validi(self):
        self.assertEqual(screen_brand({"meta": {}}), {})
        self.assertEqual(screen_brand({"meta": {"brand": "blu"}}), {})
        self.assertEqual(screen_brand(
            {"meta": {"brand": {"color.brand.primary": "non-hex"}}}), {})

    def test_valori_effettivi_usano_brand(self):
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        scr = {"meta": {"brand": {"color.brand.primary": "#0088FF"}}}
        vals = effective_token_values(tokens, "dark", scr)
        self.assertEqual(vals["color.brand.primary"], "#0088FF")
        self.assertEqual(vals["color.surface"], "#121212")  # resto dal tema
        plain = effective_token_values(tokens, "dark", {"meta": {}})
        self.assertEqual(plain["color.brand.primary"], "#5E8F6E")

    def test_saturazione(self):
        self.assertGreater(hex_saturation("#0088FF"), 0.5)
        self.assertEqual(hex_saturation("#6E6E6E"), 0)
        self.assertIsNone(hex_saturation("non-hex"))


if __name__ == "__main__":
    unittest.main()

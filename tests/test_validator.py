"""Test del validatore — unittest (stdlib, zero dipendenze extra).

Esecuzione dalla radice del progetto:
    python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from designchecker.loader import (load_catalog, load_rules, load_screen,
                                  load_tokens)
from designchecker.tokens import TokenStore, contrast_ratio
from designchecker.validator import validate


def _setup():
    rules = load_rules(ROOT / "rules")
    catalog = load_catalog(ROOT / "components.catalog.yaml")
    tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
    return rules, catalog, tokens


class TestTokens(unittest.TestCase):
    def test_contrast_black_white(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#FFFFFF"), 21.0, places=1)

    def test_alias_resolution(self):
        _, _, tokens = _setup()
        # color.surface e' un alias di color.neutral.50
        self.assertEqual(tokens.resolve_path("color.surface"), "#F7F7F5")

    def test_dimension_parsing(self):
        _, _, tokens = _setup()
        self.assertEqual(tokens.resolve_path("spacing.4"), "16")


class TestValidatorGoodScreen(unittest.TestCase):
    def test_home_conforme_zero_errori(self):
        rules, catalog, tokens = _setup()
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        findings = validate(screen, rules, tokens, catalog, platform="both")
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [],
                         msg=f"Errori inattesi: {[(f.rule_id, f.node_id) for f in errors]}")


class TestValidatorImportedScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules, catalog, tokens = _setup()
        screen = load_screen(ROOT / "examples" / "imported-home.screen.json")
        cls.findings = validate(screen, rules, tokens, catalog, platform="both")
        cls.rule_ids = {f.rule_id for f in cls.findings}

    def test_trova_touch_target_piccolo(self):
        self.assertIn("ios.touch-target.min", self.rule_ids)

    def test_trova_contrasto_insufficiente(self):
        self.assertIn("wcag.1.4.3.contrast-text", self.rule_ids)

    def test_trova_valori_hardcoded(self):
        self.assertIn("ds.no-hardcoded-value", self.rule_ids)

    def test_trova_token_rotto(self):
        self.assertIn("ds.token-resolvable", self.rule_ids)

    def test_trova_troppe_tab(self):
        self.assertIn("ios.tab.max-items", self.rule_ids)

    def test_trova_tab_senza_label(self):
        self.assertIn("ios.tab.icon-label", self.rule_ids)

    def test_trova_doppia_primaria(self):
        self.assertIn("ios.one-primary-action", self.rule_ids)

    def test_trova_safe_area_mancante(self):
        self.assertIn("expo.safe-area", self.rule_ids)

    def test_trova_label_accessibile_mancante(self):
        self.assertIn("ios.a11y.label", self.rule_ids)

    def test_trova_spacing_insufficiente(self):
        self.assertIn("m3.target-spacing", self.rule_ids)

    def test_trova_troppe_scelte_hick(self):
        self.assertIn("ux.hick.too-many-choices", self.rule_ids)

    def test_trova_primaria_fuori_zona_pollice(self):
        self.assertIn("ux.fitts.primary-low", self.rule_ids)

    def test_trova_destructive_senza_conferma(self):
        self.assertIn("ios.destructive-confirm", self.rule_ids)

    def test_trova_empty_state_mancante(self):
        self.assertIn("ios.empty-state-action", self.rule_ids)

    def test_trova_id_non_kebab(self):
        self.assertIn("expo.kebab-case-ids", self.rule_ids)

    def test_ha_errori_e_warning(self):
        severities = {f.severity for f in self.findings}
        self.assertEqual(severities, {"error", "warning"})


if __name__ == "__main__":
    unittest.main()

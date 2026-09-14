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


class TestPlatformCustom(unittest.TestCase):
    """D39: selezione piattaforma — ios/android filtrano, custom fonde."""

    def test_ios_esclude_regole_android(self):
        from designchecker.validator import rules_for_platform
        rules, _, _ = _setup()
        ids = {r["id"] for r in rules_for_platform(rules, "ios")}
        self.assertIn("ios.touch-target.min", ids)
        self.assertFalse(any(i.startswith("m3.") for i in ids))
        self.assertIn("wcag.1.4.3.contrast-text", ids)  # le 'both' restano

    def test_android_esclude_regole_ios(self):
        from designchecker.validator import rules_for_platform
        rules, _, _ = _setup()
        ids = {r["id"] for r in rules_for_platform(rules, "android")}
        # le regole SOLO iOS spariscono (alcune ios.* sono dichiarate
        # platform: both perche' universali, es. accessibilita')
        self.assertNotIn("ios.touch-target.min", ids)
        self.assertNotIn("ios.tab.max-items", ids)
        self.assertIn("m3.touch-target.min", ids)

    def test_custom_fonde_touch_target_al_piu_stretto(self):
        from designchecker.validator import rules_for_platform
        rules, _, _ = _setup()
        custom = rules_for_platform(rules, "custom")
        merged = next(r for r in custom if r["id"] == "custom.touch_target_min")
        self.assertEqual(merged["params"]["min"], 48)  # max(44 iOS, 48 Android)
        self.assertIn("custom", merged["message"])
        # le versioni originali non compaiono piu'
        ids = {r["id"] for r in custom}
        self.assertNotIn("ios.touch-target.min", ids)
        self.assertNotIn("m3.touch-target.min", ids)

    def test_custom_retorce_convenzioni_singola_piattaforma_a_warning(self):
        from designchecker.validator import rules_for_platform
        rules, _, _ = _setup()
        custom = {r["id"]: r for r in rules_for_platform(rules, "custom")}
        tab_rule = custom["ios.tab.max-items"]  # esiste solo su iOS
        self.assertEqual(tab_rule["severity"], "warning")
        self.assertIn("adattabile", tab_rule["message"])

    def test_custom_touch_45_passa_ios_ma_non_custom(self):
        """45pt: ok per iOS (>=44), ko per la quadra custom (<48)."""
        rules, catalog, tokens = _setup()
        screen = {"schema_version": "0.1", "meta": {"id": "t45"},
                  "root": {"id": "r", "type": "Screen", "children": [
                      {"id": "btn", "type": "Button",
                       "props": {"height": 45}}]}}
        ios_ids = {f.rule_id for f in validate(screen, rules, tokens, catalog,
                                               platform="ios")}
        custom_ids = {f.rule_id for f in validate(screen, rules, tokens, catalog,
                                                  platform="custom")}
        self.assertNotIn("ios.touch-target.min", ios_ids)
        self.assertIn("custom.touch_target_min", custom_ids)


class TestThemeDetection(unittest.TestCase):
    """D40: tema dark/light — rilevamento deterministico + regole tema-aware."""

    def _screen(self, bg):
        return {"schema_version": "0.1", "meta": {"id": "tema"},
                "root": {"id": "r", "type": "Screen",
                         "style": {"background": bg}, "children": []}}

    def test_rilevamento_da_hex(self):
        from designchecker.validator import detect_theme
        _, _, tokens = _setup()
        self.assertEqual(detect_theme(self._screen("#121212"), tokens), "dark")
        self.assertEqual(detect_theme(self._screen("#FFFFFF"), tokens), "light")

    def test_rilevamento_da_token_e_legacy(self):
        from designchecker.validator import detect_theme
        _, _, tokens = _setup()
        # ref DTCG a un token chiaro
        self.assertEqual(detect_theme(self._screen("{color.surface}"), tokens),
                         "light")
        # forma legacy "token:..."
        self.assertEqual(detect_theme(self._screen("token:color.surface"),
                                      tokens), "light")

    def test_esplicito_e_meta_battono_rilevamento(self):
        from designchecker.validator import resolve_theme
        _, _, tokens = _setup()
        screen = self._screen("#FFFFFF")
        self.assertEqual(resolve_theme(screen, tokens, "dark"), "dark")
        screen["meta"]["theme"] = "dark"
        self.assertEqual(resolve_theme(screen, tokens), "dark")

    def test_nero_puro_segnalato_solo_in_dark(self):
        rules, catalog, tokens = _setup()
        screen = self._screen("#000000")
        ids_dark = {f.rule_id for f in validate(screen, rules, tokens, catalog,
                                                theme="dark")}
        ids_light = {f.rule_id for f in validate(screen, rules, tokens, catalog,
                                                 theme="light")}
        self.assertIn("ux.dark.pure-black", ids_dark)
        self.assertNotIn("ux.dark.pure-black", ids_light)

"""Test dell'importer codice -> screen JSON (D23, D24).

Fixture:
- examples/generated-app/... (l'app generata da dc generate: roundtrip)
- examples/legacy-screen.fixture.tsx (violazioni tipiche di codice legacy)

Richiedono Node.js + tools/node_modules (@babel/parser): vengono saltati
con messaggio chiaro se l'ambiente non li ha.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from designchecker.importer_code import (
    CodeImporter, CodeImportError, parse_tsx,
)
from designchecker.loader import load_catalog, load_rules, load_tokens
from designchecker.tokens import TokenStore
from designchecker.validator import validate

ROOT = Path(__file__).resolve().parent.parent
APP_SCREEN = ROOT / "examples" / "generated-app" / "src" / "screens" / "home" / "index.tsx"
LEGACY_FIXTURE = ROOT / "examples" / "legacy-screen.fixture.tsx"


def _import(path: Path):
    tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
    catalog = load_catalog(ROOT / "components.catalog.yaml")
    parsed = parse_tsx(path, ROOT / "tools")
    screen = CodeImporter(tokens, catalog, tools_dir=ROOT / "tools") \
        .convert_screen(parsed, str(path))
    return screen, tokens, catalog


def _find(node: dict, node_id: str) -> dict | None:
    if node.get("id") == node_id:
        return node
    for child in node.get("children", []) or []:
        found = _find(child, node_id)
        if found:
            return found
    return None


def setUpModule():
    try:
        parse_tsx(APP_SCREEN, ROOT / "tools")
    except (CodeImportError, FileNotFoundError) as e:
        raise unittest.SkipTest(f"parser Node non disponibile: {e}")


class TestRoundtripGeneratedApp(unittest.TestCase):
    """L'app generata da dc generate deve re-importarsi quasi pulita."""

    @classmethod
    def setUpClass(cls):
        cls.screen, cls.tokens, cls.catalog = _import(APP_SCREEN)

    def test_root_is_screen(self):
        self.assertEqual(self.screen["root"]["type"], "Screen")
        self.assertTrue(self.screen["root"]["layout"]["safe_area"])

    def test_theme_refs_diventano_token(self):
        self.assertEqual(self.screen["root"]["style"]["background"], "{color.surface}")
        card = _find(self.screen["root"], "balance-card")
        self.assertIsNotNone(card)
        self.assertEqual(card["style"]["background"], "{color.surface-raised}")
        self.assertEqual(card["style"]["radius"], "{radius.lg}")

    def test_componente_custom_seguito_via_import(self):
        row = _find(self.screen["root"], "expense-row")
        self.assertIsNotNone(row)
        self.assertEqual(row["type"], "ListRow")
        self.assertEqual(row["meta"].get("via_import"), "ExpenseRow")
        # minHeight: 48 letto dal file del componente
        self.assertEqual(row["props"]["min_height"], 48)

    def test_props_sito_uso_unite(self):
        empty = _find(self.screen["root"], "empty-state")
        self.assertIsNotNone(empty)
        self.assertEqual(empty["type"], "EmptyState")
        self.assertEqual(empty["props"]["message"], "Nessuna spesa ancora")
        self.assertEqual(empty["props"]["action"], "navigate:/add-expense")

    def test_fab_rilevato_con_azione(self):
        fab = _find(self.screen["root"], "add-expense-fab")
        self.assertIsNotNone(fab)
        self.assertEqual(fab["type"], "Fab")
        self.assertEqual(fab["props"]["min_height"], 56)
        self.assertEqual(fab["props"]["action"], "navigate:/add-expense")

    def test_text_variant_da_typography(self):
        title = _find(self.screen["root"], "header-title")
        self.assertEqual(title["props"]["variant"], "title")
        self.assertEqual(title["props"]["content"], "Ciao Sara")

    def test_audit_quasi_pulito(self):
        rules = load_rules(ROOT / "rules")
        findings = validate(self.screen, rules, self.tokens, self.catalog)
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [])


class TestLegacyFixture(unittest.TestCase):
    """Il codice legacy deve produrre violazioni reali, non un ok falso."""

    @classmethod
    def setUpClass(cls):
        cls.screen, cls.tokens, cls.catalog = _import(LEGACY_FIXTURE)
        rules = load_rules(ROOT / "rules")
        cls.findings = validate(cls.screen, rules, cls.tokens, cls.catalog)

    def test_hex_hardcoded_segnalato(self):
        self.assertEqual(self.screen["root"]["style"]["background"], "#FF0000")
        rules_id = {f.rule_id for f in self.findings}
        self.assertIn("ds.no-hardcoded-value", rules_id)

    def test_touch_target_piccolo_rilevato(self):
        button = _find(self.screen["root"], "small-button")
        self.assertIsNotNone(button)
        self.assertEqual(button["props"]["min_height"], 32)
        target = [f for f in self.findings if f.node_id == "small-button"
                  and "touch" in f.rule_id]
        self.assertTrue(target)

    def test_errori_bloccanti_presenti(self):
        errors = [f for f in self.findings if f.severity == "error"]
        self.assertGreaterEqual(len(errors), 3)  # hex, touch, label/role…

    def test_font_troppo_piccolo(self):
        tiny = _find(self.screen["root"], "tiny")
        self.assertEqual(tiny["props"]["variant"], "caption")


if __name__ == "__main__":
    unittest.main()

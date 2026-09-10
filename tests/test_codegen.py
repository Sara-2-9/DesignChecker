"""Test del codegen v0.2 — unittest (stdlib).

Esecuzione dalla radice del progetto:
    python3 -m unittest discover -s tests -v
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from designchecker.codegen import Codegen
from designchecker.loader import load_catalog, load_screen, load_tokens
from designchecker.tokens import TokenStore


class TestCodegen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="dc-codegen-"))
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        cls.files = Codegen(screen, tokens, catalog).generate(cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def _read(self, rel: str) -> str:
        return (self.out / rel).read_text(encoding="utf-8")

    def test_struttura_convenzioni_expo(self):
        """Struttura ufficiale: /src, src/app, src/screens, src/components."""
        for rel in ("src/app/_layout.tsx", "src/app/index.tsx",
                    "src/screens/home/index.tsx", "src/components/button.tsx",
                    "src/components/empty-state.tsx", "src/theme.ts",
                    "src/data/mock/expenses.ts", "src/data/use-expenses.ts",
                    "package.json", "app.json", "tsconfig.json"):
            self.assertTrue((self.out / rel).exists(), msg=f"manca {rel}")

    def test_theme_contiene_valori_token_risolti(self):
        theme = self._read("src/theme.ts")
        self.assertIn("#5E8F6E", theme)   # color.brand.primary
        self.assertIn("#F7F7F5", theme)   # alias color.surface -> neutral.50 risolto
        self.assertIn('"16"', theme.replace("16", '"16"', 1))  # spacing.4

    def test_screen_usa_safe_area(self):
        screen = self._read("src/screens/home/index.tsx")
        self.assertIn("SafeAreaView", screen)
        self.assertIn("react-native-safe-area-context", screen)

    def test_screen_usa_flatlist_non_map(self):
        screen = self._read("src/screens/home/index.tsx")
        self.assertIn("FlatList", screen)
        self.assertNotIn(".map(", screen)

    def test_stili_in_fondo_al_file(self):
        screen = self._read("src/screens/home/index.tsx")
        self.assertLess(screen.index("export function"),
                        screen.index("StyleSheet.create"))

    def test_button_conforme(self):
        button = self._read("src/components/button.tsx")
        self.assertIn("Pressable", button)
        self.assertIn("minHeight: 48", button)
        self.assertIn("accessibilityRole", button)

    def test_layout_native_tabs_compound(self):
        layout = self._read("src/app/_layout.tsx")
        self.assertIn("NativeTabs.Trigger", layout)
        self.assertIn('sf="house"', layout)      # SF Symbol iOS
        self.assertIn('md="home"', layout)       # Material Symbol Android

    def test_route_snella(self):
        route = self._read("src/app/index.tsx")
        self.assertIn("return <Home />", route)

    def test_filename_kebab_case(self):
        for path in self.files:
            base = path.name.split(".")[0]
            if base.startswith("_"):
                base = base[1:]  # _layout: convenzione ufficiale Expo Router
            self.assertRegex(base, r"^[a-z0-9]+(-[a-z0-9]+)*$",
                             msg=f"nome non kebab-case: {path.name}")

    def test_nessun_hex_hardcoded_nei_componenti(self):
        """Gli stili devono passare da theme.*, mai hex nudi (regola ds.no-hardcoded)."""
        for rel in ("src/components/button.tsx", "src/components/empty-state.tsx"):
            content = self._read(rel)
            self.assertNotRegex(content, r"#[0-9a-fA-F]{6}", msg=rel)


if __name__ == "__main__":
    unittest.main()

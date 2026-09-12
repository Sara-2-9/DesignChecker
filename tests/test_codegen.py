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


class TestGenerateIntoExistingProject(unittest.TestCase):
    """D28: generazione dentro un progetto Expo esistente, senza scaffold."""

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="dc-into-"))
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        self.codegen = Codegen(screen, tokens, catalog)

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_project_files_senza_scaffold(self):
        files = self.codegen.project_files()
        self.assertIn("src/screens/home/index.tsx", files)
        self.assertIn("src/app/index.tsx", files)
        for scaffold in ("package.json", "app.json", "tsconfig.json", "src/app/_layout.tsx"):
            self.assertNotIn(scaffold, files, msg=f"non deve toccare {scaffold}")

    def test_generate_into_non_sovrascrive_senza_consenso(self):
        written1, skipped1 = self.codegen.generate_into(self.out)
        self.assertTrue(written1)
        self.assertEqual(skipped1, [])
        # marca un file esistente: non deve essere toccato
        marker = self.out / "src" / "theme.ts"
        marker.write_text("// mio tema custom", encoding="utf-8")
        written2, skipped2 = self.codegen.generate_into(self.out)
        self.assertEqual(written2, [])
        self.assertTrue(skipped2)
        self.assertEqual(marker.read_text(encoding="utf-8"), "// mio tema custom")
        # con overwrite=True invece sovrascrive
        written3, _ = self.codegen.generate_into(self.out, overwrite=True)
        self.assertTrue(written3)
        self.assertNotEqual(marker.read_text(encoding="utf-8"), "// mio tema custom")


class TestProjectDetection(unittest.TestCase):
    def test_is_expo_project(self):
        from designchecker.project import is_expo_project
        tmp = Path(tempfile.mkdtemp(prefix="dc-proj-"))
        try:
            self.assertFalse(is_expo_project(tmp))
            (tmp / "package.json").write_text('{"dependencies": {"react-native": "*"}}')
            self.assertFalse(is_expo_project(tmp))
            (tmp / "package.json").write_text('{"dependencies": {"expo": "^57.0.0"}}')
            self.assertTrue(is_expo_project(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class TestCodegenGeometry(unittest.TestCase):
    """D32: con layout.frame il codegen usa posizionamento assoluto."""

    def _screen_with_geo(self):
        return {
            "schema_version": "0.1",
            "meta": {"id": "geo", "name": "Geo", "route": "/geo"},
            "root": {
                "id": "main", "type": "Screen",
                "layout": {"safe_area": True,
                           "frame": {"x": 0, "y": 0, "w": 402, "h": 874}},
                "style": {"background": "{color.surface}"},
                "children": [
                    {"id": "title", "type": "Text",
                     "props": {"content": "Ciao", "variant": "heading"},
                     "layout": {"frame": {"x": 24, "y": 120, "w": 200, "h": 40}},
                     "style": {"color": "{color.text-primary}"}},
                    {"id": "badge", "type": "Stack",
                     "layout": {"frame": {"x": 300, "y": 700, "w": 64, "h": 64}},
                     "style": {"background": "{color.brand.primary}"},
                     "children": []},
                ],
            },
        }

    def test_posizionamento_assoluto(self):
        out = Path(tempfile.mkdtemp(prefix="dc-geo-"))
        try:
            tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
            catalog = load_catalog(ROOT / "components.catalog.yaml")
            Codegen(self._screen_with_geo(), tokens, catalog).generate(out)
            tsx = (out / "src/screens/geo/index.tsx").read_text()
            self.assertIn("position: 'absolute'", tsx)
            self.assertIn("left: 24,", tsx)
            self.assertIn("top: 700,", tsx)
            self.assertIn("width: 64,", tsx)
            # il root con geometria non usa SafeAreaView (le coordinate
            # partono da 0,0 del device, sotto la status bar)
            self.assertNotIn("SafeAreaView", tsx)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_senza_geometria_restano_fill_e_safe_area(self):
        out = Path(tempfile.mkdtemp(prefix="dc-nogeo-"))
        try:
            screen = load_screen(ROOT / "examples" / "home.screen.json")
            tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
            catalog = load_catalog(ROOT / "components.catalog.yaml")
            Codegen(screen, tokens, catalog).generate(out)
            tsx = (out / "src/screens/home/index.tsx").read_text()
            # senza geometria: niente coordinate assolute dal frame
            # (il Fab usa comunque position:absolute con bottom/right,
            # ma non left/top da layout.frame)
            self.assertNotIn("left:", tsx)
            self.assertNotIn("top:", tsx)
            self.assertIn("SafeAreaView", tsx)
        finally:
            shutil.rmtree(out, ignore_errors=True)

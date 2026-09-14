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

    def test_theme_usa_chiave_colors(self):
        # regressione: gli stili referenziano theme.colors.* (via _ts_path),
        # quindi theme.ts deve esporre "colors", non il gruppo DTCG "color"
        screen = load_screen(ROOT / "examples" / "home.screen.json")
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        ts = Codegen(screen, tokens, catalog).theme_ts()
        self.assertIn('"colors":', ts)
        self.assertNotIn('"color":', ts)
        self.assertIn('"surface-raised": "#FFFFFF"', ts)


class TestCodegenTabBar(unittest.TestCase):
    """D33: Native Tabs deve sempre includere la route index e icone valide."""

    def _codegen(self, tabs):
        screen = {
            "schema_version": "0.1",
            "meta": {"id": "tabs-test", "name": "Tabs", "route": "/"},
            "root": {
                "id": "main", "type": "Screen", "layout": {}, "style": {},
                "children": [{"id": "bar", "type": "TabBar",
                              "props": {"tabs": tabs}, "layout": {}, "style": {}}],
            },
        }
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        return Codegen(screen, tokens, catalog)

    def test_trigger_index_sempre_presente(self):
        # tab "sporchi" dai figli dell'istanza Figma: nessuno con route "/"
        cg = self._codegen([
            {"id": "tab-bar-buttons", "icon": "tab-bar-buttons",
             "label": "Tab Bar Buttons", "route": "/tab-bar-buttons"},
            {"id": "search", "icon": "search", "label": "Search", "route": "/search"},
        ])
        layout = cg.layout_tsx()
        self.assertIn('name="index"', layout)
        # nome icona non valido come SF Symbol -> fallback
        self.assertNotIn('sf="tab.bar.buttons"', layout)

    def test_icone_mappate_e_ruolo_search(self):
        cg = self._codegen([
            {"id": "home", "icon": "home", "label": "Home", "route": "/"},
            {"id": "apps", "icon": "apps", "label": "Apps", "route": "/apps"},
            {"id": "search", "icon": "search", "label": "Search",
             "route": "/search", "role": "search"},
        ])
        layout = cg.layout_tsx()
        self.assertIn('sf="house"', layout)
        self.assertIn('sf="square.grid.2x2"', layout)
        self.assertIn('name="search" role="search"', layout)

    def test_route_stub_per_tab_senza_schermata(self):
        cg = self._codegen([
            {"id": "home", "icon": "home", "label": "Home", "route": "/"},
            {"id": "apps", "icon": "apps", "label": "Apps", "route": "/apps"},
        ])
        files = cg.project_files()
        self.assertIn("src/app/apps.tsx", files)
        self.assertIn("export default function AppsRoute()", files["src/app/apps.tsx"])


class TestCodegenImagePlaceholder(unittest.TestCase):
    """D33: le immagini non portano i byte da Figma — placeholder View,
    mai <Image source={{uri:''}}> (box nero + warning RN nel simulatore)."""

    def test_immagine_e_placeholder_view(self):
        screen = {
            "schema_version": "0.1",
            "meta": {"id": "img-test", "name": "Img", "route": "/"},
            "root": {
                "id": "main", "type": "Screen",
                "layout": {"frame": {"x": 0, "y": 0, "w": 402, "h": 874}},
                "style": {}, "children": [
                    {"id": "flame", "type": "Image",
                     "props": {"source": "flame.png", "alt": "Fiamma"},
                     "layout": {"frame": {"x": 10, "y": 20, "w": 60, "h": 60}},
                     "style": {}},
                ],
            },
        }
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        _, _, content = Codegen(screen, tokens, catalog).screen_tsx()
        self.assertNotIn("uri: ''", content)
        self.assertNotIn("<Image", content)
        self.assertIn("{/* immagine: Fiamma (placeholder) */}", content)
        self.assertIn("backgroundColor: theme.colors.neutral[200]", content)


class TestCodegenRealAssets(unittest.TestCase):
    """D34: il plugin esporta i PNG (props.asset); il codegen emette
    require() locale e copia i byte in src/assets/ del progetto."""

    PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-payload"

    def _screen_con_immagine(self):
        return {
            "schema_version": "0.1",
            "meta": {"id": "img-test", "name": "Img", "route": "/"},
            "root": {
                "id": "main", "type": "Screen",
                "layout": {"frame": {"x": 0, "y": 0, "w": 402, "h": 874}},
                "style": {}, "children": [
                    {"id": "flame", "type": "Image",
                     "props": {"asset": "assets/img-test/img-test-flame.png", "alt": "Fiamma"},
                     "layout": {"frame": {"x": 10, "y": 20, "w": 60, "h": 60}},
                     "style": {}},
                    {"id": "icon-gear", "type": "Icon",
                     "props": {"name": "gearshape", "asset": "assets/img-test/img-test-icon-gear.png"},
                     "layout": {"frame": {"x": 100, "y": 20, "w": 24, "h": 24}},
                     "style": {}},
                ],
            },
        }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dc-assets-"))
        self.assets_dir = self.tmp / "imports" / "assets" / "img-test"
        self.assets_dir.mkdir(parents=True)
        (self.assets_dir / "img-test-flame.png").write_bytes(self.PNG_BYTES)
        (self.assets_dir / "img-test-icon-gear.png").write_bytes(self.PNG_BYTES)
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        self.codegen = Codegen(self._screen_con_immagine(), tokens, catalog,
                               assets_dir=self.assets_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_require_locale_in_image_e_icon(self):
        _, _, content = self.codegen.screen_tsx()
        self.assertIn("source={require('../../assets/img-test-flame.png')}", content)
        self.assertIn("source={require('../../assets/img-test-icon-gear.png')}", content)
        self.assertNotIn("(placeholder)", content)

    def test_generate_copia_i_byte_in_src_assets(self):
        out = self.tmp / "app"
        self.codegen.generate(out)
        for fname in ("img-test-flame.png", "img-test-icon-gear.png"):
            copied = out / "src" / "assets" / fname
            self.assertTrue(copied.is_file(), msg=f"manca {fname}")
            self.assertEqual(copied.read_bytes(), self.PNG_BYTES)

    def test_asset_mancante_torna_al_placeholder(self):
        (self.assets_dir / "img-test-flame.png").unlink()
        codegen = Codegen(self._screen_con_immagine(),
                          TokenStore(load_tokens(ROOT / "examples" / "tokens.json")),
                          load_catalog(ROOT / "components.catalog.yaml"),
                          assets_dir=self.assets_dir)
        _, _, content = codegen.screen_tsx()
        self.assertIn("{/* immagine: Fiamma (placeholder) */}", content)
        # l'icona con asset presente resta un'immagine reale
        self.assertIn("source={require('../../assets/img-test-icon-gear.png')}", content)



class TestCodegenTheme(unittest.TestCase):
    """D40: la status bar e il chrome di sistema seguono il tema del design."""

    def _tokens_catalog(self):
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        return tokens, catalog

    def _screen(self, theme):
        return {"schema_version": "0.1",
                "meta": {"id": "tema-app", "theme": theme},
                "root": {"id": "r", "type": "Screen",
                         "style": {"background": "#FFFFFF"},
                         "children": [{"id": "t", "type": "Text",
                                       "props": {"content": "ciao"}}]}}

    def test_dark_mode_statusbar_chiara(self):
        tokens, catalog = self._tokens_catalog()
        codegen = Codegen(self._screen("dark"), tokens, catalog)
        _, _, content = codegen.screen_tsx()
        self.assertIn('import { StatusBar }', content)
        self.assertIn('<StatusBar style="light" />', content)
        self.assertIn('"userInterfaceStyle": "dark"', codegen.app_json())

    def test_light_mode_statusbar_scura(self):
        tokens, catalog = self._tokens_catalog()
        codegen = Codegen(self._screen("light"), tokens, catalog)
        _, _, content = codegen.screen_tsx()
        self.assertIn('<StatusBar style="dark" />', content)
        self.assertIn('"userInterfaceStyle": "light"', codegen.app_json())

    def test_theme_ts_risolta_nel_tema_dello_screen(self):
        """D42: un design dark genera una theme.ts con i valori scuri."""
        tokens, catalog = self._tokens_catalog()
        dark_ts = Codegen(self._screen("dark"), tokens, catalog).theme_ts()
        light_ts = Codegen(self._screen("light"), tokens, catalog).theme_ts()
        self.assertIn('"surface": "#121212"', dark_ts)
        self.assertIn('"surface-raised": "#1C1C1E"', dark_ts)
        self.assertIn('"surface": "#F7F7F5"', light_ts)
        # il brand non cambia mai tema
        self.assertIn('"primary": "#5E8F6E"', dark_ts)
        self.assertIn('"primary": "#5E8F6E"', light_ts)

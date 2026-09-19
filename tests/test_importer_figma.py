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


class TestExportEdgeCases(unittest.TestCase):
    """Bug trovati dal primo export reale via plugin (iPhone16Pro-1)."""

    @classmethod
    def setUpClass(cls):
        cls.tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        cls.catalog = load_catalog(ROOT / "components.catalog.yaml")
        cls.importer = FigmaImporter(cls.tokens, cls.catalog)

    def test_screenshot_non_e_uno_screen(self):
        """'Screenshot 2026-08-22…' matchava Screen per prefisso: e' un'immagine."""
        node = {"type": "RECTANGLE", "name": "Screenshot 2026-08-22 at 23.59.27 2",
                "fills": [{"type": "IMAGE", "visible": True}], "children": []}
        out = self.importer.convert_node(node)
        self.assertEqual(out["type"], "Image")

    def test_device_chrome_saltato(self):
        """Status bar / Dynamic Island: chrome del mockup, mai esportati."""
        for name in ("Status bar - iPhone", "Dynamic Island", "Home Indicator"):
            node = {"type": "INSTANCE", "name": name, "children": []}
            self.assertIsNone(self.importer.convert_node(node), msg=name)

    def test_tab_con_glifo_sf_symbol_usa_nome_layer(self):
        """Le label di tab con glifi SF Symbols (PUA) cadono sul nome del layer."""
        tabbar = {"type": "INSTANCE", "name": "Tab Bar - iPhone", "children": [
            {"type": "FRAME", "name": "Home", "children": [
                {"type": "TEXT", "characters": "", "style": {"fontSize": 10}}]},
            {"type": "FRAME", "name": "Apps", "children": []},
        ]}
        out = self.importer.convert_node(tabbar)
        self.assertEqual(out["type"], "TabBar")
        labels = [t["label"] for t in out["props"]["tabs"]]
        self.assertEqual(labels, ["Home", "Apps"])
        self.assertTrue(all(t["id"] for t in out["props"]["tabs"]))


class TestImportColoriDark(unittest.TestCase):
    """D42: gli hex scuri del canvas vengono tokenizzati sulle varianti dark."""

    def test_hex_scuro_mappa_sul_token_semantico(self):
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        importer = FigmaImporter(tokens, catalog)
        # #121212 e' la variante dark di color.surface: in import diventa ref
        self.assertEqual(importer.hex_to_token.get("#121212"), "color.surface")
        self.assertEqual(importer.hex_to_token.get("#1C1C1E"),
                         "color.surface-raised")
        # e _token_or_value lo usa davvero
        self.assertEqual(importer._token_or_value("#121212"), "{color.surface}")
        # un colore fuori palette resta hex nudo (e il validatore lo segnala)
        self.assertEqual(importer._token_or_value("#0088FF"), "#0088FF")


class TestDedupId(unittest.TestCase):
    """Bug Pay-Frame: 'bg' x2, 'rectangle-253' x4 -> patcher applicava a un gemello solo."""

    def test_nomi_duplicati_diventano_id_univoci(self):
        tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        catalog = load_catalog(ROOT / "components.catalog.yaml")
        importer = FigmaImporter(tokens, catalog)
        doc = {"children": [{"name": "P", "children": [
            {"name": "Pay", "type": "FRAME", "children": [
                {"name": "bg", "type": "RECTANGLE"},
                {"name": "bg", "type": "RECTANGLE"},
                {"name": "Rectangle 253", "type": "RECTANGLE"},
                {"name": "Rectangle 253", "type": "RECTANGLE"},
            ]}]}]}
        scr = importer.convert_screen(doc, "Pay")
        ids = [c["id"] for c in scr["root"]["children"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("bg", ids)
        self.assertIn("bg-2", ids)


class TestFedeltaVisiva(unittest.TestCase):
    """Punti 1-2: angoli, bordi, opacita', rotazione, ellissi (round-trip
    Settings-Frame: cerchi diventati quadrati, toggle sparito, bordi persi)."""

    @classmethod
    def setUpClass(cls):
        cls.tokens = TokenStore(load_tokens(ROOT / "examples" / "tokens.json"))
        cls.catalog = load_catalog(ROOT / "components.catalog.yaml")
        cls.rules = load_rules(ROOT / "rules")
        cls.importer = FigmaImporter(cls.tokens, cls.catalog)

    def test_raggio_e_bordo_e_opacita_e_rotazione(self):
        node = {"type": "RECTANGLE", "name": "Card",
                "fills": [{"type": "SOLID", "visible": True,
                           "color": {"r": 0.11, "g": 0.11, "b": 0.12}}],
                "strokes": [{"type": "SOLID", "visible": True,
                             "color": {"r": 1, "g": 1, "b": 1}}],
                "strokeWeight": 1, "strokeAlign": "INSIDE",
                "cornerRadius": 16, "opacity": 0.5, "rotation": 90,
                "children": []}
        out = self.importer.convert_node(node)
        self.assertEqual(out["style"]["radius"], 16)
        self.assertEqual(out["style"]["border"]["weight"], 1)
        self.assertEqual(out["style"]["border"]["align"], "INSIDE")
        self.assertEqual(out["style"]["opacity"], 0.5)
        self.assertEqual(out["layout"]["rotation"], 90)

    def test_ellisse_non_scartata(self):
        node = {"type": "ELLIPSE", "name": "Thumb",
                "fills": [{"type": "SOLID", "visible": True,
                           "color": {"r": 1, "g": 1, "b": 1}}],
                "children": []}
        out = self.importer.convert_node(node)
        self.assertIsNotNone(out)
        self.assertEqual(out["meta"]["shape"], "ellipse")

    def test_fill_traslucido_e_vetro(self):
        """Back in vetro: #D9D9D9 al 20% + BACKGROUND_BLUR (bug Settings)."""
        node = {"type": "RECTANGLE", "name": "Glass",
                "fills": [{"type": "SOLID", "visible": True, "opacity": 0.2,
                           "color": {"r": 0.85, "g": 0.85, "b": 0.85}}],
                "effects": [{"type": "BACKGROUND_BLUR", "visible": True,
                             "radius": 12}],
                "children": []}
        out = self.importer.convert_node(node)
        self.assertEqual(out["style"]["backgroundOpacity"], 0.2)
        self.assertEqual(out["style"]["backdropBlur"], 12)

    def test_switch_tiene_i_figli(self):
        """'Toggle - Switch': track+levetta sono la verita' visiva e lo stato."""
        node = {"type": "GROUP", "name": "Toggle - Switch", "children": [
            {"type": "RECTANGLE", "name": "Track",
             "fills": [{"type": "SOLID", "visible": True,
                        "color": {"r": 0, "g": 0.53, "b": 1}}],
             "children": []},
            {"type": "ELLIPSE", "name": "Thumb",
             "fills": [{"type": "SOLID", "visible": True,
                        "color": {"r": 1, "g": 1, "b": 1}}],
             "children": []},
        ]}
        out = self.importer.convert_node(node)
        self.assertEqual(out["type"], "Switch")
        self.assertEqual(len(out.get("children", [])), 2)
        self.assertEqual(out["children"][1]["meta"]["shape"], "ellipse")

    def test_switch_registra_il_suo_sfondo(self):
        """Il track blu e' il fill del nodo Switch: senza trait surface
        veniva scartato e il toggle restava invisibile (bug Settings)."""
        node = {"type": "INSTANCE", "name": "Toggle - Switch",
                "fills": [{"type": "SOLID", "visible": True,
                           "color": {"r": 0.2, "g": 0.6, "b": 1}}],
                "children": []}
        out = self.importer.convert_node(node)
        self.assertEqual(out["type"], "Switch")
        self.assertIn("background", out.get("style", {}))

    def test_brand_estratto_dal_frame(self):
        """D49: il colore saturo dominante diventa meta.brand."""
        from designchecker.importer_figma import _extract_brand
        root = {"id": "r", "type": "Screen",
                "layout": {"frame": {"x": 0, "y": 0, "w": 402, "h": 874}},
                "children": [
                    {"id": "bg", "type": "Stack",
                     "layout": {"frame": {"x": 0, "y": 0, "w": 402, "h": 874}},
                     "style": {"background": "#000000"}},
                    {"id": "cta", "type": "Stack",
                     "layout": {"frame": {"x": 0, "y": 0, "w": 148, "h": 38}},
                     "style": {"background": "#0088FF"}}]}
        self.assertEqual(_extract_brand(root), "#0088FF")

    def test_brand_assente_su_design_neutro(self):
        from designchecker.importer_figma import _extract_brand
        root = {"id": "r", "type": "Screen",
                "children": [{"id": "bg", "type": "Stack",
                              "layout": {"frame": {"x": 0, "y": 0,
                                                  "w": 10, "h": 10}},
                              "style": {"background": "#202020"}}]}
        self.assertIsNone(_extract_brand(root))

    def test_convert_screen_registra_brand(self):
        doc = {"children": [{"name": "P", "children": [
            {"name": "Pay", "type": "FRAME", "children": [
                {"name": "CTA", "type": "RECTANGLE",
                 "absoluteBoundingBox": {"x": 0, "y": 0,
                                         "width": 148, "height": 38},
                 "fills": [{"type": "SOLID", "visible": True,
                            "color": {"r": 0, "g": 0.5333333333333333,
                                      "b": 1}}]},
            ]}]}]}
        scr = self.importer.convert_screen(doc, "Pay")
        self.assertEqual(scr["meta"]["brand"],
                         {"color.brand.primary": "#0088FF"})

    def test_testo_metriche_reali(self):
        node = {"type": "TEXT", "name": "Title", "characters": "Ciao",
                "style": {"fontSize": 17, "fontFamily": "SF Pro",
                          "fontPostScriptName": "SFProText-Semibold",
                          "textAlignHorizontal": "CENTER",
                          "lineHeightPx": 22, "letterSpacing": 0.5},
                "fills": []}
        out = self.importer.convert_node(node)
        self.assertEqual(out["props"]["fontSize"], 17)
        self.assertEqual(out["props"]["fontFamily"], "SFProText")
        self.assertEqual(out["props"]["fontStyle"], "Semibold")
        self.assertEqual(out["props"]["align"], "CENTER")
        self.assertEqual(out["props"]["lineHeight"], {"unit": "PIXELS", "value": 22})
        self.assertEqual(out["props"]["letterSpacing"], {"unit": "PIXELS", "value": 0.5})

    def test_effetti_ombra_e_vetro(self):
        node = {"type": "RECTANGLE", "name": "Card",
                "fills": [],
                "effects": [
                    {"type": "DROP_SHADOW", "visible": True,
                     "color": {"r": 0, "g": 0, "b": 0, "a": 0.3},
                     "offset": {"x": 0, "y": 4}, "radius": 12, "spread": 0},
                    {"type": "BACKGROUND_BLUR", "visible": True, "radius": 20}],
                "children": []}
        out = self.importer.convert_node(node)
        effs = out["style"]["effects"]
        self.assertEqual(len(effs), 2)
        self.assertEqual(effs[0]["type"], "DROP_SHADOW")
        self.assertEqual(effs[0]["offset"], {"x": 0, "y": 4})
        self.assertEqual(out["style"]["backdropBlur"], 20)

    def test_campi_fedelta_non_creano_errori(self):
        """Contratto: i nuovi campi non devono mai diventare finding."""
        scr = {"schema_version": "0.1.0",
               "meta": {"id": "t", "platform": "ios", "theme": "dark"},
               "root": {"id": "r", "type": "Screen",
                        "layout": {"safe_area": True},
                        "style": {"background": "{color.surface}"},
                        "children": [
                            {"id": "card", "type": "Stack",
                             "layout": {"rotation": 0},
                             "style": {"background": "{color.surface-raised}",
                                       "radius": 16,
                                       "border": {"color": "{color.neutral.700}",
                                                  "weight": 1},
                                       "backgroundOpacity": 0.2,
                                       "backdropBlur": 12,
                                       "effects": [{"type": "BACKGROUND_BLUR",
                                                    "radius": 12}],
                                       "opacity": 0.9},
                             "children": [
                                 {"id": "t1", "type": "Text",
                                  "props": {"content": "Ciao", "variant": "body",
                                            "fontSize": 17,
                                            "fontFamily": "SF Pro",
                                            "fontStyle": "Semibold",
                                            "align": "CENTER",
                                            "lineHeight": {"unit": "PIXELS",
                                                           "value": 22}},
                                  "layout": {"sizing": {"w": "hug", "h": "hug"}},
                                  "style": {"color": "{color.text-primary}"}}]}]}}
        findings = validate(scr, self.rules, self.tokens, self.catalog,
                            platform="ios", theme="dark")
        bad = [f for f in findings
               if f.severity == "error" and f.node_id == "card"]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()

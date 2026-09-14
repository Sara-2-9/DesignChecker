"""Importer Figma -> screen JSON (D21, D24).

Mappatura in cascata (priorita' decrescente):
1. INSTANCE il cui nome matcha il catalogo ("Button / Primary" -> Button)
2. Convenzione di naming sui frame ("Card", "Tab Bar", "fab"...)
3. Fallback strutturale: FRAME->Stack, TEXT->Text, GROUP->Stack (bassa confidenza)

Ogni nodo importato porta meta.confidence e meta.source.
La geometria arriva da absoluteBoundingBox: misure REALI -> touch target
verificabili al pixel. Le azioni arrivano dalle interactions di prototyping.
"""
from __future__ import annotations

import re

from .codegen import kebab
from .tokens import TokenStore, dimension_to_float, hex_to_token_map

ALIASES = {
    "tabbar": "TabBar", "navbar": "TabBar", "navigationbar": "TabBar",
    "bottombar": "TabBar", "bottomnavigation": "TabBar",
    "header": "AppHeader", "appbar": "AppHeader", "topbar": "AppHeader",
    "fab": "Fab", "floatingactionbutton": "Fab",
    "card": "Card", "list": "List", "flatlist": "List",
    "button": "Button", "textfield": "TextField", "input": "TextField",
    "switch": "Switch", "row": "ListRow", "listrow": "ListRow",
    "listitem": "ListRow", "image": "Image", "icon": "Icon",
}

# chrome di dispositivo nei mockup (Status bar, Dynamic Island…):
# non e' contenuto dell'app -> mai esportato/validato
DEVICE_CHROME = re.compile(r"^(status[\s-]?bar|dynamic[\s-]?island|home[\s-]?indicator|notch)",
                           re.IGNORECASE)

# glifi SF Symbols / private use area: non sono label leggibili
PUA = re.compile("[\\uE000-\\uF8FF\\U000F0000-\\U000FFFFD\\U00100000-\\U0010FFFD]")


def readable_label(raw: str | None, fallback: str | None) -> str:
    text = (raw or "").strip()
    if not text or PUA.search(text):
        return (fallback or "tab").strip()
    return text


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _rgb_hex(c: dict) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        round(c.get("r", 0) * 255),
        round(c.get("g", 0) * 255),
        round(c.get("b", 0) * 255))


def _solid_hex(fills) -> str | None:
    for fill in fills or []:
        if fill.get("type") == "SOLID" and fill.get("visible", True):
            return _rgb_hex(fill["color"])
    return None


def _fill_hex(fills) -> tuple[str | None, str | None]:
    """Sfondo di un nodo: (hex, visual_bg).

    Gradiente -> media pesata (alpha) degli stop, con visual_bg='gradient':
    approssimazione dichiarata per i controlli di contrasto (D30).
    Immagine -> (None, 'image'): nessun colore estraibile.
    """
    for fill in fills or []:
        if not fill.get("visible", True):
            continue
        ftype = fill.get("type", "")
        if ftype == "SOLID":
            return _rgb_hex(fill["color"]), None
        if ftype.startswith("GRADIENT"):
            stops = fill.get("gradientStops", []) or []
            if stops:
                total_a = sum(s["color"].get("a", 1) for s in stops) or 1
                avg = {ch: sum(s["color"].get(ch, 0) * s["color"].get("a", 1)
                               for s in stops) / total_a
                       for ch in ("r", "g", "b")}
                return _rgb_hex(avg), "gradient"
        if ftype == "IMAGE":
            return None, "image"
    return None, None


def _has_image_fill(fills) -> bool:
    return any(f.get("type") == "IMAGE" and f.get("visible", True) for f in fills or [])


class FigmaImporter:
    def __init__(self, tokens: TokenStore, catalog: dict):
        self.tokens = tokens
        self.catalog = catalog
        self.id_to_name: dict[str, str] = {}
        # mappa inversa: hex -> path token, tutte le varianti di tema (D42)
        # (per riconoscere i colori gia' tokenizzabili, light E dark)
        self.hex_to_token: dict[str, str] = hex_to_token_map(tokens)

    # ------------------------------------------------------------ utilities

    def _index_names(self, node: dict) -> None:
        if isinstance(node, dict):
            if "id" in node and "name" in node:
                self.id_to_name[node["id"]] = node["name"]
            for child in node.get("children", []) or []:
                self._index_names(child)

    def _token_or_value(self, hex_color: str, kind: str = "color") -> str:
        """Se l'hex corrisponde a un token del progetto, ritorna il riferimento."""
        path = self.hex_to_token.get(hex_color.upper())
        return f"{{{path}}}" if path else hex_color

    def _spacing_token(self, px) -> str | float:
        value = dimension_to_float(px) or 0
        for path in self.tokens.flat:
            if not path.startswith("spacing."):
                continue
            token_value = dimension_to_float(self.tokens.resolve_path(path))
            if token_value is not None and abs(token_value - value) <= 1:
                return f"{{{path}}}"
        return value  # numero nudo: il validatore lo segnalera' (ds.spacing-tokenized)

    def _catalog_match(self, name: str) -> tuple[str | None, float]:
        norm = _norm(name)
        if norm in ALIASES:
            return ALIASES[norm], 0.9
        for type_name in self.catalog:
            tnorm = _norm(type_name)
            if norm == tnorm:
                return type_name, 0.95
            # prefisso: MAI per Screen ("screenshot…" non e' una schermata)
            if type_name != "Screen" and norm.startswith(tnorm):
                return type_name, 0.85
        for alias, type_name in ALIASES.items():
            if norm.startswith(alias):
                return type_name, 0.75
        return None, 0.0

    def _text_variant(self, font_size: float) -> str:
        if font_size >= 24:
            return "title"
        if font_size >= 18:
            return "heading"
        if font_size >= 14:
            return "body"
        return "caption"

    def _first_text(self, node: dict) -> str | None:
        for child in node.get("children", []) or []:
            if child.get("type") == "TEXT":
                return child.get("characters")
            found = self._first_text(child)
            if found:
                return found
        return None

    def _action_from_interactions(self, node: dict) -> str | None:
        for interaction in node.get("interactions", []) or []:
            for action in interaction.get("actions", []) or []:
                if action.get("type") == "NODE" and action.get("destinationId"):
                    dest = self.id_to_name.get(action["destinationId"], "screen")
                    return f"navigate:/{kebab(dest)}"
        return None

    # ------------------------------------------------------------ conversione

    def convert_node(self, node: dict, top_level: bool = False) -> dict | None:
        ntype = node.get("type")
        name = node.get("name", "node")
        bounds = node.get("absoluteBoundingBox") or {}

        # chrome di dispositivo (Status bar, Dynamic Island…): mai validato
        if not top_level and DEVICE_CHROME.match(name):
            return None

        if ntype == "VECTOR":
            return {"id": kebab(name), "type": "Icon",
                    "props": {"name": _norm(name) or "icon"},
                    "layout": {}, "style": {},
                    "meta": {"source": "figma", "confidence": 0.9}}

        if ntype == "TEXT":
            font_size = (node.get("style") or {}).get("fontSize", 16)
            out = {
                "id": kebab(name) or "text",
                "type": "Text",
                "props": {"content": node.get("characters", ""),
                          "variant": self._text_variant(float(font_size))},
                "layout": {"sizing": {"w": "hug", "h": "hug"}},
                "style": {},
                "meta": {"source": "figma", "confidence": 1.0},
            }
            color = _solid_hex(node.get("fills"))
            if color:
                out["style"]["color"] = self._token_or_value(color)
            return out

        if ntype not in ("FRAME", "INSTANCE", "GROUP", "RECTANGLE", "COMPONENT"):
            return None

        # tipo: match catalogo o fallback strutturale
        if top_level:
            dc_type, confidence = "Screen", 1.0
        else:
            dc_type, confidence = self._catalog_match(name)
            if dc_type is None:
                if _has_image_fill(node.get("fills")):
                    dc_type, confidence = "Image", 0.7
                else:
                    dc_type, confidence = ("Stack", 0.6) if ntype == "GROUP" else ("Stack", 0.5)

        entry = self.catalog.get(dc_type, {})
        traits = set(entry.get("traits", []))

        out: dict = {
            "id": kebab(name) or "node",
            "type": dc_type,
            "props": {},
            "layout": {},
            "style": {},
            "meta": {"source": "figma", "confidence": confidence,
                     "figma_name": name, "figma_type": ntype},
        }

        # layout da auto-layout Figma
        layout_mode = node.get("layoutMode")
        if layout_mode in ("VERTICAL", "HORIZONTAL"):
            out["layout"]["direction"] = "column" if layout_mode == "VERTICAL" else "row"
        if node.get("itemSpacing"):
            out["layout"]["gap"] = self._spacing_token(node["itemSpacing"])
        pad = {}
        pl, pr = node.get("paddingLeft", 0), node.get("paddingRight", 0)
        pt, pb = node.get("paddingTop", 0), node.get("paddingBottom", 0)
        if pl and pl == pr:
            pad["horizontal"] = self._spacing_token(pl)
        if pt and pt == pb:
            pad["vertical"] = self._spacing_token(pt)
        if pad:
            out["layout"]["padding"] = pad
        if top_level:
            out["layout"]["safe_area"] = True
            out["layout"]["sizing"] = {"w": "fill", "h": "fill"}

        # colore di sfondo / superficie (gradienti -> media, dichiarata in meta)
        bg, visual_bg = _fill_hex(node.get("fills"))
        if bg and "container" in traits or (bg and top_level):
            out["style"]["background"] = self._token_or_value(bg)
        if visual_bg:
            out["meta"]["visual_bg"] = visual_bg

        # touch target: dimensioni REALI dal canvas
        if "interactive" in traits and bounds:
            out["props"]["min_height"] = round(min(bounds.get("height", 0),
                                                   bounds.get("width", 0)))

        # props specifiche
        if dc_type == "Button":
            label = self._first_text(node)
            if label:
                out["props"]["label"] = label
        if dc_type == "TabBar":
            tabs = []
            for child in node.get("children", []) or []:
                tab_label = readable_label(self._first_text(child), child.get("name"))
                tab_name = tab_label.split("/")[-1].strip()
                tabs.append({"id": kebab(tab_name), "icon": kebab(tab_name),
                             "label": tab_name, "route": "/" + kebab(tab_name)})
            out["props"]["tabs"] = tabs
            out["semantics"] = {"navigation_role": "root_tabs"}

        # azioni dal prototyping Figma
        action = self._action_from_interactions(node)
        if action and "interactive" in traits:
            out["props"]["action"] = action

        # a11y di base per gli interattivi
        if "interactive" in traits:
            out["a11y"] = {"role": "button",
                           "label": out["props"].get("label", name)}

        children = [c for c in (self.convert_node(ch) for ch in node.get("children", []) or [])
                    if c is not None]
        # i componenti mappati (Button ecc.) non esportano i figli: sono primitivi
        if children and dc_type in ("Screen", "Stack", "Card", "List"):
            out["children"] = children
        return out

    def convert_screen(self, document: dict, frame_name: str) -> dict | None:
        """Cerca il frame top-level per nome e lo converte in screen JSON."""
        self._index_names(document)
        for page in document.get("children", []) or []:
            for frame in page.get("children", []) or []:
                if frame.get("name", "").lower() == frame_name.lower():
                    root = self.convert_node(frame, top_level=True)
                    return {
                        "schema_version": "0.1.0",
                        "meta": {"id": kebab(frame_name), "name": f"{frame_name} (import Figma)",
                                 "route": "/" + kebab(frame_name), "status": "draft",
                                 "source": {"kind": "figma", "confidence": root["meta"]["confidence"]}},
                        "root": root,
                    }
        return None


def list_frames(file_tree: dict) -> list[str]:
    """Nomi dei frame top-level (le 'schermate') per `dck screens`."""
    frames = []
    for page in (file_tree.get("document", {}) or {}).get("children", []) or []:
        for frame in page.get("children", []) or []:
            if frame.get("type") in ("FRAME", "COMPONENT"):
                frames.append(f'{frame["name"]}  (pagina: {page.get("name", "?")})')
    return frames

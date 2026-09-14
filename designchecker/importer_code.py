"""Importer codice -> screen JSON (D23, D24).

Legge un file .tsx/.jsx di una schermata React Native/Expo e lo converte
in screen JSON con la STESSA interfaccia dell'importer Figma:
ogni nodo porta meta.confidence e meta.source, e il risultato va al
validatore per l'audit immediato.

Il parsing e' statico (AST, via tools/tsx2json.cjs + @babel/parser):
il codice non viene MAI eseguito.

Mappatura in cascata (priorita' decrescente):
1. Componente RN nativo noto (Pressable -> Button, FlatList -> List...)
2. Componente custom il cui nome matcha il catalogo ("EmptyState" -> EmptyState)
3. Fallback strutturale -> Stack (bassa confidenza)

Il codice da' la SEMANTICA (azioni onPress, accessibilityLabel, ruoli)
che Figma non ha; la geometria dai valori di style (width/height reali).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .codegen import kebab
from .tokens import TokenStore, hex_to_token_map

RN_MAP = {
    "View": ("Stack", 0.9),
    "ScrollView": ("Stack", 0.9),
    "KeyboardAvoidingView": ("Stack", 0.85),
    "SafeAreaView": ("Screen", 1.0),
    "Text": ("Text", 1.0),
    "Pressable": ("Button", 0.9),
    "TouchableOpacity": ("Button", 0.9),
    "TouchableHighlight": ("Button", 0.85),
    "Button": ("Button", 0.95),
    "FlatList": ("List", 1.0),
    "SectionList": ("List", 1.0),
    "TextInput": ("TextField", 1.0),
    "Switch": ("Switch", 1.0),
    "Image": ("Image", 0.95),
    "ImageBackground": ("Image", 0.85),
    "Fragment": ("Stack", 0.7),
}

# alias custom -> catalogo (come importer_figma, lato codice)
ALIASES = {
    "tabbar": "TabBar", "navbar": "TabBar", "header": "AppHeader",
    "appheader": "AppHeader", "appbar": "AppHeader", "fab": "Fab",
    "card": "Card", "button": "Button", "input": "TextField",
    "textfield": "TextField", "switch": "Switch", "image": "Image",
    "icon": "Icon", "list": "List", "row": "ListRow", "listrow": "ListRow",
    "emptystate": "EmptyState", "errorstate": "ErrorState",
    "skeleton": "SkeletonList", "skeletonlist": "SkeletonList",
}

TYPOGRAPHY_VARIANTS = {"title", "heading", "body", "caption"}


class CodeImportError(Exception):
    """Errore di parsing/import dal codice (messaggio utente-friendly)."""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def parse_tsx(path: Path, tools_dir: Path) -> dict:
    """Esegue il parser Node e ritorna {file, styles, tree}."""
    node = shutil.which("node")
    if not node:
        raise CodeImportError(
            "Node.js non trovato nel PATH: serve per il parsing statico del TSX "
            "(lo stesso Node che usi per Expo).")
    script = tools_dir / "tsx2json.cjs"
    if not script.exists():
        raise CodeImportError(f"Parser non trovato: {script}")
    if not (tools_dir / "node_modules" / "@babel" / "parser").is_dir():
        raise CodeImportError(
            "Dipendenza mancante: esegui una volta\n"
            f"  cd {tools_dir} && npm install\n"
            "(su questa macchina: npm install --no-bin-links se il disco non "
            "supporta i symlink)")
    result = subprocess.run(
        [node, str(script), str(path)],
        capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise CodeImportError(
            f"Parsing fallito per {path}:\n{result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout)


class CodeImporter:
    def __init__(self, tokens: TokenStore, catalog: dict,
                 tools_dir: Path | None = None):
        self.tokens = tokens
        self.catalog = catalog
        self.tools_dir = tools_dir
        self.styles: dict[str, dict] = {}
        self.imports: dict[str, str] = {}
        self.base_dir: Path | None = None
        self.counter = 0
        self._components: dict[str, dict | None] = {}  # cache file componenti
        self._loading: set[str] = set()                # guardia anti-cicli
        # mappa inversa hex -> token, tutte le varianti di tema (D42)
        self.hex_to_token: dict[str, str] = hex_to_token_map(tokens)

    # ---------------------------------------------------- import tra file

    def _load_component(self, tag: str) -> dict | None:
        """Segue l'import relativo di un componente custom e lo parsa (cache + anti-cicli)."""
        source = self.imports.get(tag)
        if not source or self.base_dir is None or self.tools_dir is None:
            return None
        if source in self._components:
            return self._components[source]
        if source in self._loading:
            return None
        self._loading.add(source)
        parsed = None
        base = (self.base_dir / source).resolve()
        for candidate in (base.with_suffix(".tsx"), base.with_suffix(".jsx"),
                          base.with_suffix(".ts"), base / "index.tsx"):
            if candidate.is_file():
                try:
                    parsed = parse_tsx(candidate, self.tools_dir)
                except (CodeImportError, json.JSONDecodeError):
                    parsed = None
                break
        self._loading.discard(source)
        self._components[source] = parsed
        return parsed

    # ------------------------------------------------------------ utilities

    def _catalog_match(self, name: str) -> tuple[str | None, float]:
        norm = _norm(name)
        for type_name in self.catalog:
            if norm == _norm(type_name):
                return type_name, 0.85
        if norm in ALIASES:
            return ALIASES[norm], 0.8
        for alias, type_name in ALIASES.items():
            if norm.endswith(alias):  # "ExpenseRow" -> ListRow, "UserCard" -> Card
                return type_name, 0.7
        return None, 0.0

    def _theme_ref_to_token(self, path: str) -> str | None:
        """theme.colors.brand.primary -> {color.brand.primary} se il token esiste."""
        if not path.startswith("theme."):
            return None
        rest = path[len("theme."):]
        # theme.colors.* -> color.*, il resto (spacing/radius/typography) resta uguale
        candidate = re.sub(r"^colors\.", "color.", rest)
        if candidate in self.tokens.flat:
            return "{" + candidate + "}"
        return None

    def _color_value(self, style_prop: dict) -> str | None:
        """Valore colore da una prop di stile: token, hex grezzo, o None."""
        if style_prop.get("kind") == "ref":
            return self._theme_ref_to_token(style_prop.get("path", ""))
        if style_prop.get("kind") == "string":
            value = style_prop["value"]
            if value.startswith("#"):
                token = self.hex_to_token.get(value.upper())
                return "{" + token + "}" if token else value  # hex grezzo: il validatore lo segnala
        return None

    def _spacing_value(self, style_prop: dict):
        """Spacing: token se riconosciuto, altrimenti numero grezzo (lo segnala ds.spacing-tokenized)."""
        if style_prop.get("kind") == "ref":
            token = self._theme_ref_to_token(style_prop.get("path", ""))
            if token:
                return token
        if style_prop.get("kind") == "number":
            return style_prop["value"]
        return None

    def _style_of(self, element: dict) -> dict:
        """Style risolto di un elemento (segue il riferimento styles.xxx)."""
        prop = element.get("props", {}).get("style")
        if not isinstance(prop, dict):
            return {}
        if prop.get("kind") == "style_ref":
            resolved = dict(self.styles.get(prop.get("name", ""), {}))
            for extra in prop.get("extra", []) or []:
                resolved.update(self.styles.get(extra, {}))
            return resolved
        return {}

    def _text_variant(self, style: dict) -> str:
        font = style.get("fontSize")
        if isinstance(font, dict):
            if font.get("kind") == "ref":
                path = font.get("path", "")
                # theme.typography.title -> "title"
                last = path.split(".")[-1]
                if last in TYPOGRAPHY_VARIANTS:
                    return last
            if font.get("kind") == "number":
                size = font["value"]
                if size >= 24:
                    return "title"
                if size >= 18:
                    return "heading"
                if size >= 14:
                    return "body"
                return "caption"
        return "body"

    def _action(self, element: dict) -> str | None:
        for prop_name in ("onPress", "onAction", "onLongPress"):
            prop = element.get("props", {}).get(prop_name)
            if isinstance(prop, dict) and prop.get("kind") == "action":
                if prop.get("verb") == "navigate" and prop.get("target"):
                    return f"navigate:{prop['target']}"
                if prop.get("verb") == "back":
                    return "back"
                return None  # call/custom: logica app, non ricostruibile -> audit action-wired
        return None

    # ------------------------------------------------------------ conversione

    def convert_element(self, element: dict, top_level: bool = False,
                        inside_list: bool = False) -> dict | None:
        tag = element.get("tag", "")
        if tag in ("Fragment",):
            return None  # i frammenti li gestisce il chiamante (figli risaliti)

        style = self._style_of(element)
        entry: dict | None = None

        if tag in RN_MAP:
            dc_type, confidence = RN_MAP[tag]
            if dc_type == "Screen" and not top_level:
                dc_type, confidence = "Stack", 0.8
        else:
            dc_type, confidence = self._catalog_match(tag)
            if dc_type is None:
                dc_type, confidence = ("Stack", 0.4)

        # Pressable dentro una lista -> ListRow; absolute + quadrato ~56 -> Fab
        if tag in ("Pressable", "TouchableOpacity", "TouchableHighlight"):
            if inside_list:
                dc_type, confidence = "ListRow", max(confidence, 0.85)
            elif (style.get("position", {}).get("value") == "absolute"
                  and style.get("width", {}).get("kind") == "number"
                  and 44 <= style["width"]["value"] <= 72):
                dc_type, confidence = "Fab", 0.85

        # View il cui nome di stile richiama un tipo del catalogo
        # ("balanceCard" -> Card, "appHeader" -> AppHeader): il nome e' semantica
        if tag in ("View", "ScrollView"):
            style_prop0 = element.get("props", {}).get("style")
            style_name = style_prop0.get("name", "") if isinstance(style_prop0, dict) else ""
            named_type, named_conf = self._catalog_match(style_name)
            if named_type and named_type in ("Card", "AppHeader", "TabBar"):
                dc_type, confidence = named_type, min(named_conf, 0.75)

        # componente custom importato da un file relativo: lo seguo e ne leggo
        # l'interno (semantica reale: touch size, a11y, azioni) invece di indovinare
        if tag not in RN_MAP and not top_level:
            sub = self._load_component(tag)
            if sub is not None:
                saved_styles, saved_imports, saved_base = self.styles, self.imports, self.base_dir
                self.styles = sub.get("styles", {})
                self.imports = sub.get("imports", {})
                sub_file = sub.get("file")
                if sub_file:
                    self.base_dir = Path(sub_file).resolve().parent
                inner = self.convert_element(sub["tree"], inside_list=inside_list)
                self.styles, self.imports, self.base_dir = saved_styles, saved_imports, saved_base
                if inner is not None:
                    # il tipo matchato dal nome (ExpenseRow -> ListRow) vince su quello interno
                    named_type, _ = self._catalog_match(tag)
                    if named_type and named_type != inner["type"]:
                        inner["type"] = named_type
                    inner["id"] = kebab(tag) or inner["id"]
                    # le props passate al sito d'uso sono parte della semantica:
                    # <EmptyState message="..." actionLabel="..." onAction={...} />
                    for key, prop in element.get("props", {}).items():
                        if key == "style" or not isinstance(prop, dict):
                            continue
                        if prop.get("kind") == "string":
                            inner["props"].setdefault(
                                "action_label" if key == "actionLabel" else kebab(key),
                                prop["value"])
                    outer_action = self._action(element)
                    if outer_action:
                        inner["props"]["action"] = outer_action
                    inner["meta"]["via_import"] = tag
                    inner["meta"]["confidence"] = max(inner["meta"]["confidence"], 0.85)
                    return inner

        traits = set(self.catalog.get(dc_type, {}).get("traits", []))
        fallback_id = f"{kebab(tag)}-{self.counter}"
        self.counter += 1

        out: dict = {
            "id": fallback_id,
            "type": dc_type,
            "props": {},
            "layout": {},
            "style": {},
            "meta": {"source": "code", "confidence": confidence, "rn_tag": tag},
        }

        # id parlante dallo style ref ("addExpenseFab" -> "add-expense-fab")
        style_prop = element.get("props", {}).get("style")
        if isinstance(style_prop, dict) and style_prop.get("kind") == "style_ref":
            named = kebab(style_prop.get("name", ""))
            if named:
                out["id"] = named

        # ---- colori e superficie
        bg = self._color_value(style.get("backgroundColor", {}))
        if bg and ("container" in traits or "surface" in traits or top_level):
            out["style"]["background"] = bg
        color = self._color_value(style.get("color", {}))
        if color and ("text" in traits or dc_type == "Text"):
            out["style"]["color"] = color
        radius = style.get("borderRadius")
        if isinstance(radius, dict) and radius.get("kind") == "ref":
            token = self._theme_ref_to_token(radius.get("path", ""))
            if token:
                out["style"]["radius"] = token

        # ---- layout
        pad: dict = {}
        for key, style_key in (("all", "padding"), ("horizontal", "paddingHorizontal"),
                               ("vertical", "paddingVertical")):
            value = self._spacing_value(style.get(style_key, {}))
            if value is not None:
                pad[key] = value
        if pad:
            out["layout"]["padding"] = pad
        gap = self._spacing_value(style.get("gap", {}))
        if gap is not None:
            out["layout"]["gap"] = gap
        if top_level:
            out["layout"]["safe_area"] = tag in ("SafeAreaView", "View")
            out["layout"]["sizing"] = {"w": "fill", "h": "fill"}

        # ---- touch target: dimensioni REALI dai valori di style
        width = style.get("width", {})
        height = style.get("height", {})
        if "interactive" in traits:
            dims = [d["value"] for key in ("width", "height", "minWidth", "minHeight")
                    if isinstance((d := style.get(key)), dict) and d.get("kind") == "number"]
            if dims:
                out["props"]["min_height"] = round(min(dims))

        # ---- props specifiche per tipo
        props = element.get("props", {})
        if dc_type == "Text":
            content = element.get("text", "").strip()
            out["props"]["content"] = content or "…"
            out["props"]["variant"] = self._text_variant(style)
        elif dc_type in ("Button", "Fab"):
            label = element.get("text", "").strip()
            if not label:  # label nel primo figlio Text
                for child in element.get("children", []):
                    if child.get("tag") == "Text" and child.get("text", "").strip():
                        label = child["text"].strip()
                        break
            if label:
                out["props"]["label"] = label
            a11y_label = props.get("accessibilityLabel", {})
            if isinstance(a11y_label, dict) and a11y_label.get("kind") == "string" \
                    and "destructiv" in _norm(a11y_label["value"]):
                out["props"]["variant"] = "destructive"
        elif dc_type == "TextField":
            ph = props.get("placeholder", {})
            if isinstance(ph, dict) and ph.get("kind") == "string":
                out["props"]["placeholder"] = ph["value"]
        elif dc_type == "List":
            row = props.get("renderItem")
            if isinstance(row, dict) and row.get("kind") == "jsx":
                child = self.convert_element(row["element"], inside_list=True)
                if child:
                    out.setdefault("children", []).append(child)
            empty = props.get("ListEmptyComponent")
            if isinstance(empty, dict) and empty.get("kind") == "jsx":
                child = self.convert_element(empty["element"])
                if child:
                    out.setdefault("children", []).append(child)
        elif dc_type == "EmptyState":
            for key in ("message", "actionLabel"):
                prop = props.get(key)
                if isinstance(prop, dict) and prop.get("kind") == "string":
                    out["props"][kebab(key) if key != "actionLabel" else "action_label"] = prop["value"]

        # ---- azioni e accessibilita'
        action = self._action(element)
        if action and ("interactive" in traits or dc_type == "EmptyState"):
            out["props"]["action"] = action

        a11y: dict = {}
        role = props.get("accessibilityRole")
        if isinstance(role, dict) and role.get("kind") == "string":
            a11y["role"] = role["value"]
        label_prop = props.get("accessibilityLabel")
        if isinstance(label_prop, dict) and label_prop.get("kind") == "string":
            a11y["label"] = label_prop["value"]
        elif isinstance(label_prop, dict) and label_prop.get("kind") == "expr":
            # es. `${item.title} — ${item.amount}`: c'e', ma dipende dai dati
            a11y["label"] = "(dinamica: dai dati della riga)"
            out["meta"]["a11y_dynamic"] = True
        if a11y:
            out["a11y"] = a11y
        elif "interactive" in traits and out["props"].get("label"):
            out["a11y"] = {"role": "button", "label": out["props"]["label"]}

        # ---- figli (i primitivi interattivi non esportano i figli testuali)
        children = [c for c in (self.convert_element(ch) for ch in element.get("children", []))
                    if c is not None]
        # frammenti: risalgo i nipoti
        for ch in element.get("children", []):
            if ch.get("tag") == "Fragment":
                children.extend(c for c in (self.convert_element(g) for g in ch.get("children", []))
                                if c is not None)
        if children and dc_type in ("Screen", "Stack", "Card", "List", "AppHeader"):
            out.setdefault("children", []).extend(children)
        return out

    def convert_screen(self, parsed: dict, source_path: str) -> dict:
        """Albero JSX -> screen JSON completo."""
        self.styles = parsed.get("styles", {})
        self.imports = parsed.get("imports", {})
        self.base_dir = Path(source_path).resolve().parent
        self.counter = 0
        root = self.convert_element(parsed["tree"], top_level=True)
        if root is None:
            raise CodeImportError("La radice JSX non e' convertibile.")
        if root["type"] != "Screen":
            root["meta"]["note"] = "radice non SafeAreaView: interpretata come Screen"
            root["type"] = "Screen"
        stem = Path(source_path).stem
        name = Path(source_path).parent.name if stem == "index" else stem
        return {
            "schema_version": "0.1.0",
            "meta": {"id": kebab(name), "name": f"{name} (import codice)",
                     "route": "/" + kebab(name), "status": "draft",
                     "source": {"kind": "code", "path": source_path,
                                "confidence": root["meta"]["confidence"]}},
            "root": root,
        }

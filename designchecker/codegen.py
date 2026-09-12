"""Codegen v0.2 — dallo screen JSON a un progetto Expo reale.

Genera codice secondo le convenzioni ufficiali Expo (blog struttura cartelle,
aggiornato gen 2026 + changelog SDK 55/56/57):
- /src con src/app (routing) snello, schermate in src/screens/
- filename kebab-case, un named export per componente
- StyleSheet.create in fondo al file
- theme.ts generato dai token DTCG
- Native Tabs (compound API SDK 55+) per la tab bar
- Pressable per gli interattivi, FlatList per le liste
- data layer isolato in src/data/ (mock + hook, decisione D14)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .tokens import TokenStore, dimension_to_float

ICON_MD_MAP = {
    "house": "home", "person": "person", "person.2": "group",
    "chart": "bar_chart", "wallet": "account_balance_wallet",
    "people": "group", "plus": "add", "gear": "settings",
}


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in kebab(name).split("-") if part)


def camel(name: str) -> str:
    p = pascal(name)
    return p[:1].lower() + p[1:]


def kebab(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).replace("_", "-")
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", s)   # spazi, slash ("Button / Primary")
    return s.strip("-").lower()


class Codegen:
    def __init__(self, screen: dict, tokens: TokenStore, catalog: dict,
                 app_name: str = "spesecondivise"):
        self.screen = screen
        self.tokens = tokens
        self.catalog = catalog
        self.app_name = app_name
        self.styles: dict[str, dict] = {}
        self.needs_router = False
        self.needs_safe_area = False
        self.list_bindings: list[dict] = []

    # ---------------------------------------------------------- theme.ts

    def _theme_tree(self) -> dict:
        """Token DTCG -> albero con valori risolti (alias compresi)."""
        out: dict = {}
        for path in self.tokens.flat:
            value = self.tokens.resolve_path(path)
            parts = path.split(".")
            node = out
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            num = dimension_to_float(value)
            node[parts[-1]] = num if num is not None and not str(value).startswith("#") else value
        return out

    def theme_ts(self) -> str:
        tree = self._theme_tree()
        body = json.dumps(tree, indent=2, ensure_ascii=False)
        return (
            "// Generato da DesignChecker da tokens.json (DTCG) — non modificare a mano.\n"
            "export const theme = " + body + " as const;\n"
        )

    # ---------------------------------------------------------- stili

    _IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

    def _ts_path(self, path: str) -> str:
        """'color.brand.primary' -> theme.colors.brand.primary (con notazione
        sicura per chiavi numeriche o con trattini: theme.spacing['4'])."""
        if path.startswith("color."):
            path = "colors." + path[len("color."):]
        parts = path.split(".")
        out = "theme"
        for part in parts:
            out += f".{part}" if self._IDENT_RE.match(part) else f"['{part}']"
        return out

    def _ts_value(self, value, kind: str) -> str:
        """Riferimento token -> espressione theme.*; numero nudo -> numero."""
        path = TokenStore.ref_path(value) if isinstance(value, str) else None
        if path:
            return self._ts_path(path)
        num = dimension_to_float(value)
        return str(int(num)) if num is not None else json.dumps(value)

    def _register_style(self, node: dict, extra: dict | None = None) -> str:
        name = camel(node.get("id", "node"))
        layout = node.get("layout", {}) or {}
        style = node.get("style", {}) or {}
        st: dict = {}

        if style.get("background"):
            st["backgroundColor"] = self._ts_value(style["background"], "color")
        # 'color' e' valido solo sui componenti testuali (ViewStyle RN non lo prevede)
        traits = set(self.catalog.get(node.get("type"), {}).get("traits", []))
        if style.get("color") and "text" in traits:
            st["color"] = self._ts_value(style["color"], "color")
        if style.get("radius"):
            st["borderRadius"] = self._ts_value(style["radius"], "radius")

        padding = layout.get("padding", {}) or {}
        pad_map = {"all": "padding", "horizontal": "paddingHorizontal",
                   "vertical": "paddingVertical", "top": "paddingTop",
                   "bottom": "paddingBottom", "left": "paddingLeft",
                   "right": "paddingRight"}
        for key, prop in pad_map.items():
            if key in padding:
                st[prop] = self._ts_value(padding[key], "spacing")

        if layout.get("gap"):
            st["gap"] = self._ts_value(layout["gap"], "spacing")

        # Geometria reale (D32): con layout.frame il nodo va in posizionamento
        # assoluto — anteprima pixel-fedele nel simulatore. Senza frame resta
        # il flexbox semantico. Il root Screen resta flex:1 (riempie il device).
        frame = layout.get("frame")
        if frame and node.get("type") != "Screen":
            st["position"] = "'absolute'"
            st["left"] = str(int(frame.get("x", 0) or 0))
            st["top"] = str(int(frame.get("y", 0) or 0))
            st["width"] = str(int(frame.get("w", 0) or 0))
            st["height"] = str(int(frame.get("h", 0) or 0))

        sizing = layout.get("sizing", {}) or {}
        if not frame:
            if sizing.get("w") == "fill" and node.get("type") != "Screen":
                st["alignSelf"] = "'stretch'"
            if sizing.get("h") == "fill":
                st["flex"] = "1"

        if extra:
            st.update(extra)
        if st:
            self.styles[name] = st
        return name

    def _style_obj_ts(self, st: dict) -> str:
        lines = []
        for key, val in st.items():
            lines.append(f"    {key}: {val},")
        return "{\n" + "\n".join(lines) + "\n  }"

    # ---------------------------------------------------------- azioni

    def _action_ts(self, action) -> str:
        if action is None:
            return "undefined"
        if isinstance(action, str):
            if action.startswith("navigate:"):
                self.needs_router = True
                return f"() => router.push('{action.split(':', 1)[1]}')"
            if action == "back":
                self.needs_router = True
                return "() => router.back()"
            if action.startswith("reload:"):
                return "() => { /* TODO: reload dati */ }"
            return "undefined"
        if isinstance(action, dict):
            kind = action.get("type")
            if kind == "navigate":
                self.needs_router = True
                return f"() => router.push('{action.get('route', '/')}')"
            if kind == "back":
                self.needs_router = True
                return "() => router.back()"
        return "undefined"

    def _a11y_ts(self, node: dict) -> str:
        a11y = node.get("a11y", {}) or {}
        parts = []
        if a11y.get("role"):
            parts.append(f'accessibilityRole="{a11y["role"]}"')
        if a11y.get("label"):
            parts.append(f'accessibilityLabel={json.dumps(a11y["label"], ensure_ascii=False)}')
        return (" " + " ".join(parts)) if parts else ""

    # ---------------------------------------------------------- emitter per tipo

    def emit(self, node: dict, depth: int) -> str:
        handler = getattr(self, f"_emit_{node.get('type', '').lower()}", self._emit_generic)
        return handler(node, depth)

    def _indent(self, depth: int) -> str:
        return "  " * depth

    def _emit_children(self, node: dict, depth: int) -> str:
        return "\n".join(self.emit(c, depth) for c in node.get("children", []) or [])

    def _emit_screen(self, node: dict, depth: int) -> str:
        self._register_style(node, extra={"flex": "1"})
        layout = node.get("layout", {}) or {}
        # Con geometria (D32) le coordinate partono da 0,0 del device:
        # niente SafeAreaView (sposterebbe tutto sotto la status bar).
        wrapper = "View" if layout.get("frame") else (
            "SafeAreaView" if layout.get("safe_area") else "View")
        if wrapper == "SafeAreaView":
            self.needs_safe_area = True
        children = self._emit_children(node, depth + 1)
        i = self._indent(depth)
        return (f"{i}<{wrapper} style={{styles.{camel(node.get('id', 'screen'))}}}>\n"
                f"{children}\n{i}</{wrapper}>")

    def _emit_appheader(self, node: dict, depth: int) -> str:
        name = self._register_style(node)
        props = node.get("props", {}) or {}
        i = self._indent(depth)
        title = json.dumps(props.get("title", ""), ensure_ascii=False)
        subtitle = props.get("subtitle")
        sub_tsx = (f"\n{i}  <Text style={{styles.{name}Subtitle}}>{subtitle}</Text>" if subtitle else "")
        if subtitle:
            self.styles[f"{name}Subtitle"] = {
                "fontSize": "theme.typography.body",
                "color": "theme.colors['text-secondary']",
            }
        self.styles[f"{name}Title"] = {
            "fontSize": "theme.typography.title",
            "fontWeight": "'700'",
            "color": "theme.colors['text-primary']",
        }
        return (f"{i}<View style={{styles.{name}}}{self._a11y_ts(node)}>\n"
                f"{i}  <Text style={{styles.{name}Title}}>{props.get('title','')}</Text>"
                f"{sub_tsx}\n{i}</View>")

    def _emit_card(self, node: dict, depth: int) -> str:
        name = self._register_style(node)
        children = self._emit_children(node, depth + 1)
        i = self._indent(depth)
        return f"{i}<View style={{styles.{name}}}>\n{children}\n{i}</View>"

    def _emit_stack(self, node: dict, depth: int) -> str:
        return self._emit_card(node, depth)

    def _emit_text(self, node: dict, depth: int) -> str:
        props = node.get("props", {}) or {}
        variant = props.get("variant", "body")
        extra = {"fontSize": f"theme.typography.{variant}"}
        if variant in ("title", "heading"):
            extra["fontWeight"] = "'700'"
        name = self._register_style(node, extra=extra)
        content = props.get("content", "")
        i = self._indent(depth)
        return f"{i}<Text style={{styles.{name}}}{self._a11y_ts(node)}>{content}</Text>"

    def _emit_button(self, node: dict, depth: int) -> str:
        props = node.get("props", {}) or {}
        i = self._indent(depth)
        variant = props.get("variant", "primary")
        on_press = self._action_ts(props.get("action"))
        label = json.dumps(props.get("label", ""), ensure_ascii=False)
        a11y_label = (node.get("a11y", {}) or {}).get("label")
        a11y_prop = (f" accessibilityLabel={json.dumps(a11y_label, ensure_ascii=False)}"
                     if a11y_label else "")
        # Geometria/stile dal JSON (D33): il componente Button accetta style.
        name = self._register_style(node)
        style_prop = f" style={{styles.{name}}}" if name in self.styles else ""
        return (f"{i}<Button label={label} variant=\"{variant}\" "
                f"onPress={{{on_press}}}{a11y_prop}{style_prop} />")

    def _emit_fab(self, node: dict, depth: int) -> str:
        props = node.get("props", {}) or {}
        layout = node.get("layout", {}) or {}
        # dimensione dal catalogo (default M3: 56) — conforme per costruzione
        size = int(dimension_to_float(props.get("size")
                                      or self.catalog.get("Fab", {}).get("defaults", {}).get("size", 56)))
        frame = layout.get("frame")
        if frame:
            # Con geometria reale (D33) posizione e dimensioni arrivano dal frame:
            # niente anchor bottom/right, evitiamo vincoli in conflitto.
            extra = {"borderRadius": str(int(frame.get("h", size) or size) // 2),
                     "alignItems": "'center'", "justifyContent": "'center'"}
        else:
            extra = {"position": "'absolute'", "width": str(size), "height": str(size),
                     "borderRadius": str(size // 2), "alignItems": "'center'",
                     "justifyContent": "'center'"}
        offset = layout.get("offset", {}) or {}
        position = str(layout.get("position", "bottom-trailing"))
        if not frame:
            if "bottom" in position:
                extra["bottom"] = self._ts_value(offset.get("y", "{spacing.4}"), "spacing")
            if "top" in position:
                extra["top"] = self._ts_value(offset.get("y", "{spacing.4}"), "spacing")
            if "trailing" in position or "right" in position:
                extra["right"] = self._ts_value(offset.get("x", "{spacing.4}"), "spacing")
            if "leading" in position or "left" in position:
                extra["left"] = self._ts_value(offset.get("x", "{spacing.4}"), "spacing")
        name = self._register_style(node, extra=extra)
        on_press = self._action_ts(props.get("action"))
        a11y = node.get("a11y", {}) or {}
        i = self._indent(depth)
        label = props.get("label")
        inner = (f'<Text style={{styles.{name}Label}}>{label}</Text>' if label
                 else f'<Text style={{styles.{name}Label}}>+</Text>')
        self.styles[f"{name}Label"] = {
            "color": self._ts_value((node.get("style", {}) or {}).get("foreground",
                                                                     "{color.brand.on-primary}"), "color"),
            "fontSize": "theme.typography.body", "fontWeight": "'600'",
        }
        bg = self._ts_value((node.get("style", {}) or {}).get("background",
                                                             "{color.brand.primary}"), "color")
        self.styles.setdefault(name, {})
        return (f"{i}<Pressable onPress={{{on_press}}} accessibilityRole=\"button\""
                f" accessibilityLabel={json.dumps(a11y.get('label', label or 'Azione'), ensure_ascii=False)}"
                f" style={{({{ pressed }}) => [styles.{name}, {{ backgroundColor: {bg} }},"
                f" pressed && {{ opacity: 0.85 }}]}}>\n"
                f"{i}  {inner}\n{i}</Pressable>")

    def _emit_list(self, node: dict, depth: int) -> str:
        props = node.get("props", {}) or {}
        name = self._register_style(node, extra={"flex": "1"})
        binding = props.get("data_source", "items")
        row = props.get("row_component", "Row")
        row_kebab = kebab(row)
        hook_name = "use" + pascal(binding.split(".")[0])
        state_name = binding.split(".")[0]
        self.list_bindings.append({"binding": binding, "hook": hook_name,
                                   "state": state_name, "row": row,
                                   "row_kebab": row_kebab})
        states = node.get("states", {}) or {}
        empty = states.get("empty", {}) or {}
        empty_props = empty.get("props", {}) or {}
        empty_msg = empty_props.get("message", "Nessun elemento")
        empty_action = empty_props.get("action", {}) or {}
        empty_action_label = empty_action.get("label", "")
        empty_on_press = self._action_ts(empty_action.get("action"))
        i = self._indent(depth)
        return (
            f"{i}<FlatList\n"
            f"{i}  data={{{state_name}}}\n"
            f"{i}  keyExtractor={{(item) => item.id}}\n"
            f"{i}  renderItem={{({{ item }}) => <{pascal(row)} item={{item}} />}}\n"
            f"{i}  contentContainerStyle={{styles.{name}}}\n"
            f"{i}  ListEmptyComponent={{<EmptyState message={json.dumps(empty_msg, ensure_ascii=False)}"
            f" actionLabel={json.dumps(empty_action_label, ensure_ascii=False)}"
            f" onAction={{{empty_on_press}}} />}}\n"
            f"{i}/>"
        )

    def _emit_tabbar(self, node: dict, depth: int) -> str:
        return (self._indent(depth)
                + "{/* TabBar: renderizzata da src/app/_layout.tsx (Native Tabs) */}")

    def _emit_textfield(self, node: dict, depth: int) -> str:
        props = node.get("props", {}) or {}
        name = self._register_style(node, extra={
            "minHeight": "48",
            "borderRadius": "theme.radius.sm",
            "backgroundColor": "theme.colors['surface-raised']",
            "paddingHorizontal": "theme.spacing[4]",
        })
        i = self._indent(depth)
        a11y = node.get("a11y", {}) or {}
        return (f"{i}<TextInput style={{styles.{name}}} "
                f"placeholder={json.dumps(props.get('placeholder', ''), ensure_ascii=False)}"
                f" accessibilityLabel={json.dumps(a11y.get('label', props.get('placeholder', 'campo')), ensure_ascii=False)} />")

    def _emit_switch(self, node: dict, depth: int) -> str:
        i = self._indent(depth)
        node_id = camel(node.get("id", "switch"))
        return (f"{i}<Switch value={{{node_id}Value}} onValueChange={{set{pascal(node_id)}Value}} />")

    def _emit_icon(self, node: dict, depth: int) -> str:
        name = node.get("props", {}).get("name", "?")
        return self._indent(depth) + "{/* icona: " + str(name) + " */}"

    def _emit_image(self, node: dict, depth: int) -> str:
        name = self._register_style(node)
        return f"{self._indent(depth)}<Image style={{styles.{name}}} source={{{{ uri: '' }}}} />"

    def _emit_generic(self, node: dict, depth: int) -> str:
        name = self._register_style(node)
        children = self._emit_children(node, depth + 1)
        i = self._indent(depth)
        style_attr = f" style={{styles.{name}}}" if name in self.styles else ""
        return f"{i}<View{style_attr}>\n{children}\n{i}</View>"

    # ---------------------------------------------------------- file di progetto

    def screen_tsx(self) -> tuple[str, str]:
        """Ritorna (nome_componente, contenuto src/screens/<id>/index.tsx)."""
        root = self.screen.get("root", {})
        screen_id = kebab(self.screen.get("meta", {}).get("id", "screen"))
        component = pascal(screen_id)

        body = self.emit(root, 1)

        imports = {"react-native": {"View", "Text", "StyleSheet"}}
        if "Pressable" in body:
            imports["react-native"].add("Pressable")
        if "TextInput" in body:
            imports["react-native"].add("TextInput")
        if "Switch" in body:
            imports["react-native"].add("Switch")
        if "FlatList" in body:
            imports["react-native"].add("FlatList")
        if "<Image" in body:
            imports["react-native"].add("Image")

        lines = []
        if self.needs_safe_area:
            lines.append("import { SafeAreaView } from 'react-native-safe-area-context';")
        if self.needs_router:
            lines.append("import { useRouter } from 'expo-router';")
        lines.append(f"import {{ {', '.join(sorted(imports['react-native']))} }} from 'react-native';")
        lines.append("import { theme } from '../../theme';")
        if "<Button" in body:
            lines.append("import { Button } from '../../components/button';")
        if "EmptyState" in body:
            lines.append("import { EmptyState } from '../../components/empty-state';")
        for binding in self.list_bindings:
            lines.append(f"import {{ {pascal(binding['row'])} }} from './components/{binding['row_kebab']}';")
            lines.append(f"import {{ {binding['hook']} }} from '../../data/use-{kebab(binding['state'])}';")

        router_line = "  const router = useRouter();" if self.needs_router else ""
        hooks = "\n".join(f"  const {{ {b['state']} }} = {b['hook']}();" for b in self.list_bindings)

        styles_entries = ",\n".join(
            f"  {name}: {self._style_obj_ts(st)}" for name, st in self.styles.items()
        )

        content = f"""{chr(10).join(lines)}

export function {component}() {{
{router_line}
{hooks}
  return (
{body}
  );
}}

const styles = StyleSheet.create({{
{styles_entries}
}});
"""
        return screen_id, component, content

    def layout_tsx(self) -> str:
        """src/app/_layout.tsx — Native Tabs se c'e' un TabBar, altrimenti Stack."""
        tabbar = self._find_type(self.screen.get("root", {}), "TabBar")
        if not tabbar:
            return ("import { Stack } from 'expo-router';\n\n"
                    "export default function RootLayout() {\n  return <Stack />;\n}\n")
        tabs = (tabbar.get("props", {}) or {}).get("tabs", [])
        triggers = []
        for tab in tabs:
            route = tab.get("route", "/")
            name = "index" if route == "/" else route.strip("/")
            icon = str(tab.get("icon", "circle"))
            sf = icon.replace("-", ".")
            md = ICON_MD_MAP.get(sf, "circle")
            label = tab.get("label", name)
            triggers.append(
                f'      <NativeTabs.Trigger name="{name}">\n'
                f'        <NativeTabs.Trigger.Icon sf="{sf}" md="{md}" />\n'
                f'        <NativeTabs.Trigger.Label>{label}</NativeTabs.Trigger.Label>\n'
                f'      </NativeTabs.Trigger>'
            )
        triggers_tsx = "\n".join(triggers)
        return f"""import {{ NativeTabs }} from 'expo-router/unstable-native-tabs';

// Native Tabs (SDK 55+): tab bar di sistema — Liquid Glass su iOS 26+,
// safe area gestita automaticamente (regole expo.native-tabs, ios.liquid-glass).
export default function TabLayout() {{
  return (
    <NativeTabs>
{triggers_tsx}
    </NativeTabs>
  );
}}
"""

    def _find_type(self, node: dict, type_name: str):
        if node.get("type") == type_name:
            return node
        for child in node.get("children", []) or []:
            found = self._find_type(child, type_name)
            if found:
                return found
        return None

    def route_tsx(self, component: str, screen_id: str) -> str:
        return (f"import {{ {component} }} from '../screens/{screen_id}';\n\n"
                f"export default function {component}Route() {{\n  return <{component} />;\n}}\n")

    # ---------------------------------------------------------- componenti riusabili

    def button_tsx(self) -> str:
        return """import { Pressable, Text, StyleSheet, StyleProp, ViewStyle } from 'react-native';
import { theme } from '../theme';

// Componente dalla component library DesignChecker (catalogo: Button).
// Conforme per costruzione: minHeight 48 (M3), Pressable, label sempre presente.
// `style` permette al codegen di applicare geometria/override dal JSON (D33).
type Props = {
  label: string;
  onPress?: () => void;
  variant?: 'primary' | 'secondary' | 'destructive';
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
};

export function Button({ label, onPress, variant = 'primary', accessibilityLabel, style }: Props) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      style={({ pressed }) => [styles.base, styles[variant], style, pressed && styles.pressed]}
    >
      <Text style={[styles.label, variant === 'secondary' && styles.labelOnSecondary]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 48,
    borderRadius: theme.radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: theme.spacing[4],
  },
  primary: { backgroundColor: theme.colors.brand.primary },
  secondary: { backgroundColor: theme.colors.neutral[200] },
  destructive: { backgroundColor: theme.colors.error },
  pressed: { opacity: 0.85 },
  label: {
    color: theme.colors.brand['on-primary'],
    fontSize: theme.typography.body,
    fontWeight: '600',
  },
  labelOnSecondary: { color: theme.colors['text-primary'] },
});
"""

    def empty_state_tsx(self) -> str:
        return """import { View, Text, StyleSheet } from 'react-native';
import { Button } from './button';
import { theme } from '../theme';

// HIG empty state: mai schermate vuote, sempre messaggio + azione (ios.empty-state-action).
type Props = {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
};

export function EmptyState({ message, actionLabel, onAction }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.message}>{message}</Text>
      {actionLabel ? <Button label={actionLabel} onPress={onAction} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: theme.spacing[6],
    gap: theme.spacing[4],
  },
  message: {
    fontSize: theme.typography.body,
    color: theme.colors['text-secondary'],
    textAlign: 'center',
  },
});
"""

    def row_tsx(self, row_name: str, state: str) -> str:
        comp = pascal(row_name)
        return f"""import {{ Pressable, Text, StyleSheet }} from 'react-native';
import {{ theme }} from '../../../theme';
import type {{ {pascal(state[:-1] if state.endswith('s') else state)} }} from '../../../data/mock/{kebab(state)}';

// Riga di lista — altezza minima 44pt (iOS) / 48dp (Android).
type Props = {{ item: {pascal(state[:-1] if state.endswith('s') else state)} }};

export function {comp}({{ item }}: Props) {{
  return (
    <Pressable style={{styles.row}} accessibilityRole="button"
      accessibilityLabel={{`${{item.title}} — ${{item.amount}}`}}>
      <View>
        <Text style={{styles.title}}>{{item.title}}</Text>
        <Text style={{styles.subtitle}}>{{item.date}} · {{item.payer}}</Text>
      </View>
      <Text style={{styles.amount}}>{{item.amount}}</Text>
    </Pressable>
  );
}}

const styles = StyleSheet.create({{
  row: {{
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: theme.spacing[4],
    paddingVertical: theme.spacing[2],
    backgroundColor: theme.colors['surface-raised'],
    borderRadius: theme.radius.sm,
  }},
  title: {{ fontSize: theme.typography.body, color: theme.colors['text-primary'] }},
  subtitle: {{ fontSize: theme.typography.caption, color: theme.colors['text-secondary'] }},
  amount: {{ fontSize: theme.typography.body, fontWeight: '600', color: theme.colors['text-primary'] }},
}});
"""

    def data_files(self) -> dict[str, str]:
        """src/data/mock/<state>.ts + src/data/use-<state>.ts (decisione D14)."""
        files = {}
        for binding in self.list_bindings:
            state = binding["state"]
            entity = pascal(state[:-1] if state.endswith("s") else state)
            files[f"src/data/mock/{kebab(state)}.ts"] = f"""// Mock di esempio — UNICO punto dati del prototipo (regola expo.no-mock-inline).
// Quando arriva il DB vero: si sostituisce solo src/data/, la UI non cambia.
export type {entity} = {{
  id: string;
  title: string;
  amount: string;
  payer: string;
  date: string;
}};

export const recent: {entity}[] = [
  {{ id: '1', title: 'Spesa supermercato', amount: '42,30 €', payer: 'Sara', date: '9 set' }},
  {{ id: '2', title: 'Bolletta luce', amount: '58,10 €', payer: 'Marco', date: '7 set' }},
  {{ id: '3', title: 'Pizza condivisa', amount: '27,00 €', payer: 'Giulia', date: '5 set' }},
];
"""
            files[f"src/data/use-{kebab(state)}.ts"] = f"""import {{ useState }} from 'react';
import {{ recent }} from './mock/{kebab(state)}';

// Hook di accesso ai dati: la UI parla solo con questo (decisione D14).
export function use{pascal(state)}() {{
  const [{state}] = useState(recent);
  return {{ {state} }};
}}
"""
        return files

    def package_json(self) -> str:
        return json.dumps({
            "name": f"{self.app_name}-preview",
            "version": "0.1.0",
            "main": "expo-router/entry",
            "scripts": {"start": "expo start", "ios": "expo start --ios",
                        "android": "expo start --android"},
            "dependencies": {
                "expo": "~57.0.0",
                "expo-router": "~57.0.0",
                "expo-status-bar": "*",
                "react": "19.2.3",
                "react-dom": "19.2.3",
                "react-native": "0.86.3",
                "react-native-safe-area-context": "~5.7.0",
                "react-native-screens": "~4.26.0"
            },
            "devDependencies": {
                "@types/react": "~19.2.0",
                "typescript": "~6.0.3"
            },
            "note": "Versioni allineate a Expo SDK 57 (react/react-dom/RN esatte, come i template ufficiali: il caret trascina minor non supportate). react-dom e' fissato perche' i pacchetti Radix di expo-router altrimenti risolvono la 19.3.0 (peer react ^19.3.0) e npm fallisce negli install successivi. typescript in devDeps evita l'install interattivo al primo `expo start`."
        }, indent=2)

    def app_json(self) -> str:
        return json.dumps({"expo": {
            "name": f"{self.app_name} (preview DesignChecker)",
            "slug": f"{self.app_name}-preview",
            "scheme": self.app_name,
            "newArchEnabled": True
        }}, indent=2)

    def tsconfig_json(self) -> str:
        return json.dumps({"extends": "expo/tsconfig.base", "compilerOptions": {"strict": True}},
                          indent=2)

    # ---------------------------------------------------------- entry point

    def project_files(self) -> dict[str, str]:
        """File della schermata per un progetto Expo ESISTENTE (D28):
        niente scaffold (package.json/app.json/tsconfig restano quelli del progetto)."""
        screen_id, component, screen_content = self.screen_tsx()
        route = (self.screen.get("meta", {}).get("route") or f"/{screen_id}").strip("/")
        route_rel = "src/app/index.tsx" if not route else f"src/app/{kebab(route)}.tsx"
        files: dict[str, str] = {
            route_rel: self.route_tsx(component, screen_id),
            f"src/screens/{screen_id}/index.tsx": screen_content,
            "src/components/button.tsx": self.button_tsx(),
            "src/components/empty-state.tsx": self.empty_state_tsx(),
            "src/theme.ts": self.theme_ts(),
        }
        files.update(self.data_files())
        for binding in self.list_bindings:
            files[f"src/screens/{screen_id}/components/{binding['row_kebab']}.tsx"] = \
                self.row_tsx(binding["row"], binding["state"])
        return files

    def generate_into(self, project_dir: Path, overwrite: bool = False) -> tuple[list[Path], list[Path]]:
        """Scrive la schermata in un progetto esistente.
        Ritorna (scritti, saltati): i file gia' presenti non vengono toccati
        senza overwrite=True."""
        written, skipped = [], []
        for rel, content in self.project_files().items():
            path = project_dir / rel
            if path.exists() and not overwrite:
                skipped.append(path)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
        return written, skipped

    def generate(self, out_dir: Path) -> list[Path]:
        screen_id, component, screen_content = self.screen_tsx()
        files: dict[str, str] = {
            "package.json": self.package_json(),
            "app.json": self.app_json(),
            "tsconfig.json": self.tsconfig_json(),
            "src/theme.ts": self.theme_ts(),
            "src/app/_layout.tsx": self.layout_tsx(),
            "src/app/index.tsx": self.route_tsx(component, screen_id),
            f"src/screens/{screen_id}/index.tsx": screen_content,
            "src/components/button.tsx": self.button_tsx(),
            "src/components/empty-state.tsx": self.empty_state_tsx(),
        }
        files.update(self.data_files())
        for binding in self.list_bindings:
            files[f"src/screens/{screen_id}/components/{binding['row_kebab']}.tsx"] = \
                self.row_tsx(binding["row"], binding["state"])

        written = []
        for rel, content in files.items():
            path = out_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
        return written

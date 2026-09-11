"""Il validatore di DesignChecker.

Principi (vedi docs/02 e decisioni D1-D2):
- Le regole sono DATI (YAML); ogni regola dichiara un `check` che rimanda a una
  funzione di controllo qui sotto. Nuova regola con check esistente = solo YAML.
- Il validatore non controlla i TIPI di componente ma i TRAITS dichiarati nel
  catalogo (components.catalog.yaml): i componenti custom futuri vengono
  validati automaticamente.
- Due severita': `error` (regola ufficiale violata, bloccante) e
  `warning` (euristica / raccomandazione).
- Le regole con `phase: codegen` non girano sul JSON: documentano controlli
  che avverranno sul codice generato.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tokens import TokenStore, contrast_ratio, dimension_to_float, HEX_RE

LARGE_TEXT_VARIANTS = {"title", "heading"}  # WCAG: testo grande


@dataclass
class Finding:
    rule_id: str
    severity: str            # error | warning
    node_id: str
    message: str
    suggestion: str = ""
    source: str = ""
    source_url: str = ""


@dataclass
class Context:
    tokens: TokenStore
    catalog: dict            # type -> entry del catalogo
    platform: str            # ios | android | both
    screen: dict             # root dello screen JSON
    parents: dict = field(default_factory=dict)  # id(node) -> parent node

    def entry(self, node: dict) -> dict:
        return self.catalog.get(node.get("type"), {})

    def traits(self, node: dict) -> set:
        return set(self.entry(node).get("traits", []))


# ---------------------------------------------------------------- utilita'

def walk(node: dict, parent: dict | None, ctx: Context):
    """Visita l'albero registrando i genitori (servono per sfondi e fratelli)."""
    ctx.parents[id(node)] = parent
    yield node, parent
    for child in node.get("children", []) or []:
        yield from walk(child, node, ctx)


def node_size(node: dict, ctx: Context) -> float | None:
    """Dimensione rilevante ai fini touch: props esplicite, poi default del catalogo."""
    props = node.get("props", {}) or {}
    for key in ("size", "min_height", "height"):
        if key in props:
            val = dimension_to_float(ctx.tokens.resolve_value(props[key]))
            if val is not None:
                return val
    defaults = ctx.entry(node).get("defaults", {}) or {}
    for key in ("size", "min_height", "height"):
        if key in defaults:
            val = dimension_to_float(defaults[key])
            if val is not None:
                return val
    return None


def nearest_background(node: dict, ctx: Context) -> str | None:
    """Risale l'albero cercando il primo style.background risolvibile in hex."""
    current = node
    while current is not None:
        bg = (current.get("style", {}) or {}).get("background")
        if bg:
            return ctx.tokens.resolve_value(bg)
        current = ctx.parents.get(id(current))
    return None


def interpolate(template: str, **values) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        return template


def make_finding(rule: dict, node_id: str, **values) -> Finding:
    return Finding(
        rule_id=rule["id"],
        severity=rule.get("severity", "warning"),
        node_id=node_id,
        message=interpolate(rule.get("message", rule["id"]), node=node_id, **values),
        suggestion=interpolate(rule.get("suggestion", ""), node=node_id, **values),
        source=rule.get("source", ""),
        source_url=rule.get("source_url", ""),
    )


def all_nodes(ctx: Context):
    return [n for n, _ in walk(ctx.screen.get("root", {}), None, ctx)]


# ---------------------------------------------------------------- check ---

def check_touch_target_min(node, rule, ctx):
    if "interactive" not in ctx.traits(node):
        return None
    size = node_size(node, ctx)
    if size is None:
        return None  # non verificabile: nessuna dimensione dichiarata
    minimum = float(rule["params"]["min"])
    if size < minimum:
        return [make_finding(rule, node.get("id", "?"),
                             actual=int(size), min=int(minimum),
                             unit=rule["params"].get("unit", "pt"))]
    return None


def check_max_items(node, rule, ctx):
    if node.get("type") != rule["params"].get("target"):
        return None
    items = (node.get("props", {}) or {}).get("tabs", []) or []
    maximum = int(rule["params"]["max"])
    if len(items) > maximum:
        return [make_finding(rule, node.get("id", "?"), count=len(items), max=maximum)]
    return None


def check_tabs_complete(node, rule, ctx):
    if node.get("type") != "TabBar":
        return None
    findings = []
    for tab in (node.get("props", {}) or {}).get("tabs", []) or []:
        if not tab.get("icon") or not tab.get("label"):
            findings.append(make_finding(rule, f"{node.get('id','?')}/{tab.get('id','?')}"))
    return findings


def check_single_primary_action(node, rule, ctx):
    # scope: screen — gira una sola volta (vedi run_rules)
    primaries = [n for n in all_nodes(ctx)
                 if (n.get("semantics", {}) or {}).get("primary_action") is True]
    if len(primaries) > 1:
        ids = ", ".join(n.get("id", "?") for n in primaries)
        return [make_finding(rule, "(schermata)", value=ids, count=len(primaries))]
    return None


def check_max_instances(node, rule, ctx):
    target = rule["params"]["type"]
    instances = [n for n in all_nodes(ctx) if n.get("type") == target]
    maximum = int(rule["params"]["max"])
    if len(instances) > maximum:
        ids = ", ".join(n.get("id", "?") for n in instances)
        return [make_finding(rule, "(schermata)", value=ids, count=len(instances), max=maximum)]
    return None


def check_a11y_label_required(node, rule, ctx):
    if "interactive" not in ctx.traits(node):
        return None
    if not (node.get("a11y", {}) or {}).get("label"):
        return [make_finding(rule, node.get("id", "?"))]
    return None


def check_a11y_role_required(node, rule, ctx):
    if "interactive" not in ctx.traits(node):
        return None
    if not (node.get("a11y", {}) or {}).get("role"):
        return [make_finding(rule, node.get("id", "?"))]
    return None


def check_role_expected(node, rule, ctx):
    if node.get("type") != rule["params"].get("type"):
        return None
    expected = rule["params"]["role"]
    if (node.get("a11y", {}) or {}).get("role") != expected:
        return [make_finding(rule, node.get("id", "?"), expected=expected)]
    return None


def check_safe_area_required(node, rule, ctx):
    if "top_level" not in ctx.traits(node):
        return None
    if not (node.get("layout", {}) or {}).get("safe_area"):
        return [make_finding(rule, node.get("id", "?"))]
    return None


def check_empty_state_action(node, rule, ctx):
    states = node.get("states", {}) or {}
    empty = states.get("empty")
    if empty is None:
        # l'empty state puo' anche essere un figlio EmptyState (import da codice)
        for child in node.get("children", []) or []:
            if child.get("type") == "EmptyState":
                empty = child
                break
    if empty is None:
        if node.get("type") == "List":
            return [make_finding(rule, node.get("id", "?"), value="stato empty mancante")]
        return None
    action = (empty.get("props", {}) or {}).get("action")
    if not action:
        return [make_finding(rule, node.get("id", "?"), value="empty senza azione")]
    return None


def check_contrast_min(node, rule, ctx):
    traits = ctx.traits(node)
    params = rule["params"]
    is_text = "text" in traits
    is_ui = "interactive" in traits
    if params.get("target") == "text" and not is_text:
        return None
    if params.get("target") == "ui" and not is_ui:
        return None
    # testo grande ha soglia diversa: la regola dichiara large:true/false
    variant = (node.get("props", {}) or {}).get("variant", "body")
    large = variant in LARGE_TEXT_VARIANTS
    if "large" in params and bool(params["large"]) != large:
        return None
    style = node.get("style", {}) or {}
    fg_raw = style.get("color") or style.get("foreground")
    if not fg_raw:
        return None
    fg = ctx.tokens.resolve_value(fg_raw)
    bg = nearest_background(node, ctx)
    ratio = contrast_ratio(fg, bg) if fg and bg else None
    if ratio is None:
        return None
    minimum = float(params["min"])
    if ratio < minimum:
        return [make_finding(rule, node.get("id", "?"),
                             actual=f"{ratio:.1f}:1", min=f"{minimum}:1")]
    return None


def check_color_only_meaning(node, rule, ctx):
    style = node.get("style", {}) or {}
    color = style.get("color") or style.get("background")
    if not color or not TokenStore.is_ref(color):
        return None
    path = TokenStore.ref_path(color) or ""
    semantic = any(k in path for k in ("success", "error", "warning", "danger"))
    has_cue = (node.get("props", {}) or {}).get("icon") or (node.get("a11y", {}) or {}).get("label")
    if semantic and not has_cue:
        return [make_finding(rule, node.get("id", "?"), value=path)]
    return None


def check_token_resolvable(node, rule, ctx):
    findings = []
    for key, value in (node.get("style", {}) or {}).items():
        if TokenStore.is_ref(value) and not ctx.tokens.has(TokenStore.ref_path(value)):
            findings.append(make_finding(rule, node.get("id", "?"),
                                         value=value, path=key))
    return findings


def check_no_hardcoded_value(node, rule, ctx):
    findings = []
    # sfondi approssimati da gradiente/immagine (meta.visual_bg, D30):
    # non sono una decisione "hard-coded", sono una lettura del canvas
    if (node.get("meta", {}) or {}).get("visual_bg"):
        return None
    for key, value in (node.get("style", {}) or {}).items():
        if isinstance(value, str) and HEX_RE.match(value.strip()):
            findings.append(make_finding(rule, node.get("id", "?"),
                                         value=value, path=key))
    return findings


def check_action_wired(node, rule, ctx):
    if "interactive" not in ctx.traits(node):
        return None
    action = (node.get("props", {}) or {}).get("action")
    if action in (None, ""):
        return [make_finding(rule, node.get("id", "?"))]
    return None


def check_gap_min(node, rule, ctx):
    children = node.get("children", []) or []
    interactive_children = [c for c in children if "interactive" in ctx.traits(c)]
    if len(interactive_children) < 2:
        return None
    gap = (node.get("layout", {}) or {}).get("gap")
    if gap is None:
        return None
    value = dimension_to_float(ctx.tokens.resolve_value(gap))
    minimum = float(rule["params"]["min"])
    if value is not None and value < minimum:
        return [make_finding(rule, node.get("id", "?"),
                             actual=int(value), min=int(minimum))]
    return None


def check_component_size(node, rule, ctx):
    if node.get("type") != rule["params"].get("type"):
        return None
    size = node_size(node, ctx)
    expected = float(rule["params"]["size"])
    if size is not None and size != expected:
        return [make_finding(rule, node.get("id", "?"),
                             actual=int(size), expected=int(expected))]
    return None


def check_component_height_range(node, rule, ctx):
    if node.get("type") != rule["params"].get("type"):
        return None
    size = node_size(node, ctx)
    if size is None:
        return None
    lo, hi = float(rule["params"]["min"]), float(rule["params"]["max"])
    if not lo <= size <= hi:
        return [make_finding(rule, node.get("id", "?"),
                             actual=int(size), min=int(lo), max=int(hi))]
    return None


def check_text_min_size(node, rule, ctx):
    if "text" not in ctx.traits(node):
        return None
    variant = (node.get("props", {}) or {}).get("variant")
    if not variant:
        return None
    size = ctx.tokens.resolve_path(f"typography.{variant}")
    size = dimension_to_float(size)
    minimum = float(rule["params"]["min"])
    if size is not None and size < minimum:
        return [make_finding(rule, node.get("id", "?"),
                             actual=int(size), min=int(minimum), value=variant)]
    return None


def check_destructive_requires_confirm(node, rule, ctx):
    if not (node.get("semantics", {}) or {}).get("destructive"):
        return None
    if not (node.get("props", {}) or {}).get("confirm"):
        return [make_finding(rule, node.get("id", "?"))]
    return None


def check_icon_only_critical(node, rule, ctx):
    if "interactive" not in ctx.traits(node):
        return None
    props = node.get("props", {}) or {}
    critical = (node.get("semantics", {}) or {}).get("primary_action") is True
    if critical and props.get("icon") and not props.get("label"):
        return [make_finding(rule, node.get("id", "?"))]
    return None


def check_primary_position_low(node, rule, ctx):
    if not (node.get("semantics", {}) or {}).get("primary_action"):
        return None
    position = (node.get("layout", {}) or {}).get("position")
    if position and "bottom" not in str(position):
        return [make_finding(rule, node.get("id", "?"), value=position)]
    return None


def check_too_many_choices(node, rule, ctx):
    children = node.get("children", []) or []
    interactive_children = [c for c in children if "interactive" in ctx.traits(c)]
    maximum = int(rule["params"]["max"])
    if len(interactive_children) > maximum:
        return [make_finding(rule, node.get("id", "?"),
                             count=len(interactive_children), max=maximum)]
    return None


def check_nav_pattern_present(node, rule, ctx):
    # scope: screen
    if not any("navigation_chrome" in ctx.traits(n) for n in all_nodes(ctx)):
        return [make_finding(rule, "(schermata)")]
    return None


def check_token_group_exists(node, rule, ctx):
    # scope: screen (controlla i token del progetto)
    group = rule["params"]["group"]
    if not ctx.tokens.has_group(group):
        return [make_finding(rule, "(progetto)", value=group)]
    return None


def check_gap_tokenized(node, rule, ctx):
    gap = (node.get("layout", {}) or {}).get("gap")
    if gap is None:
        return None
    if TokenStore.is_ref(gap):
        return None
    value = dimension_to_float(gap)
    if value is not None:
        return [make_finding(rule, node.get("id", "?"), actual=int(value))]
    return None


def check_kebab_case_ids(node, rule, ctx):
    import re
    node_id = node.get("id", "")
    if node_id and not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", node_id):
        return [make_finding(rule, node_id, value=node_id)]
    return None


CHECKS = {
    "touch_target_min": check_touch_target_min,
    "max_items": check_max_items,
    "tabs_complete": check_tabs_complete,
    "single_primary_action": check_single_primary_action,
    "max_instances": check_max_instances,
    "a11y_label_required": check_a11y_label_required,
    "a11y_role_required": check_a11y_role_required,
    "role_expected": check_role_expected,
    "safe_area_required": check_safe_area_required,
    "empty_state_action": check_empty_state_action,
    "contrast_min": check_contrast_min,
    "color_only_meaning": check_color_only_meaning,
    "token_resolvable": check_token_resolvable,
    "no_hardcoded_value": check_no_hardcoded_value,
    "action_wired": check_action_wired,
    "gap_min": check_gap_min,
    "component_size": check_component_size,
    "component_height_range": check_component_height_range,
    "text_min_size": check_text_min_size,
    "destructive_requires_confirm": check_destructive_requires_confirm,
    "icon_only_critical": check_icon_only_critical,
    "primary_position_low": check_primary_position_low,
    "too_many_choices": check_too_many_choices,
    "nav_pattern_present": check_nav_pattern_present,
    "token_group_exists": check_token_group_exists,
    "gap_tokenized": check_gap_tokenized,
    "kebab_case_ids": check_kebab_case_ids,
}

SCREEN_SCOPE_CHECKS = {"single_primary_action", "max_instances",
                       "nav_pattern_present", "token_group_exists"}


def validate(screen: dict, rules: list[dict], tokens: TokenStore,
             catalog: dict, platform: str = "both") -> list[Finding]:
    """Esegue tutte le regole applicabili sullo screen JSON.

    Eccezioni consapevoli (D30): un nodo puo' dichiarare
    meta.exceptions: [{rule: "<id o prefisso>", reason: "..."}] —
    i finding coperti vengono rimossi e conteggiati in
    screen["meta"]["exceptions_applied"] (visibile nel report).
    """
    ctx = Context(tokens=tokens, catalog=catalog, platform=platform, screen=screen)
    # costruisce la mappa dei genitori una sola volta
    list(walk(screen.get("root", {}), None, ctx))

    findings: list[Finding] = []
    for rule in rules:
        if rule.get("phase", "validate") != "validate":
            continue  # regole di codegen: documentate, non eseguite sul JSON
        rule_platform = rule.get("platform", "both")
        if platform != "both" and rule_platform not in ("both", platform):
            continue
        check_fn = CHECKS.get(rule.get("check", ""))
        if check_fn is None:
            continue
        if rule.get("scope") == "screen" or rule.get("check") in SCREEN_SCOPE_CHECKS:
            result = check_fn(screen.get("root", {}), rule, ctx)
            if result:
                findings.extend(result)
        else:
            applies_traits = set(rule.get("applies_to", []) or [])
            for node, _parent in walk(screen.get("root", {}), None, ctx):
                if applies_traits and not applies_traits & ctx.traits(node):
                    continue
                result = check_fn(node, rule, ctx)
                if result:
                    findings.extend(result)

    # ---- eccezioni giustificate (D30)
    by_id: dict[str, dict] = {}
    for node, _p in walk(screen.get("root", {}), None, ctx):
        by_id.setdefault(node.get("id", ""), node)
    kept: list[Finding] = []
    applied: list[str] = []
    for f in findings:
        # id composti ("main-tabs/profile") -> primo segmento; "(schermata)" -> root
        node = by_id.get(f.node_id) or by_id.get(f.node_id.split("/")[0])
        if node is None and f.node_id == "(schermata)":
            node = screen.get("root", {})
        if node is None:
            node = {}
        exceptions = (node.get("meta", {}) or {}).get("exceptions", []) or []
        match = next((e for e in exceptions
                      if e.get("reason", "").strip()
                      and f.rule_id.startswith(e.get("rule", ""))), None)
        if match:
            applied.append(f"{f.rule_id} su '{f.node_id}' — {match['reason']}")
        else:
            kept.append(f)
    if applied:
        screen.setdefault("meta", {})["exceptions_applied"] = applied
    return kept

"""Risoluzione dei design token (formato W3C DTCG 2025.10) e utilita' colore/contrasto.

I token vivono in tokens.json con la struttura DTCG:
    { "color": { "brand": { "primary": { "$type": "color", "$value": "#5E8F6E" } } } }

Nei nodi dello screen JSON si referenziano come "{color.brand.primary}".
Gli alias (un token il cui $value e' a sua volta "{altro.token}") vengono risolti.
"""
from __future__ import annotations

import re

ALIAS_RE = re.compile(r"^\{\s*([A-Za-z0-9_.-]+)\s*\}$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
DIM_RE = re.compile(r"^(-?\d+(?:\.\d+)?)")


def flatten(data: dict, prefix: str = "", out: dict | None = None) -> dict:
    """Appiattisce l'albero DTCG in { 'color.brand.primary': '#5E8F6E', ... }."""
    if out is None:
        out = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if "$value" in value:
                out[path] = value["$value"]
            else:
                flatten(value, path, out)
    return out


class TokenStore:
    """Accesso ai token con risoluzione degli alias e cache."""

    def __init__(self, data: dict):
        self.flat = flatten(data)
        self._resolved: dict = {}

    def has(self, path: str) -> bool:
        return path in self.flat

    def has_group(self, prefix: str) -> bool:
        return any(p == prefix or p.startswith(prefix + ".") for p in self.flat)

    def resolve_path(self, path: str):
        """Risolve un path token seguendo gli alias. None se inesistente."""
        if path in self._resolved:
            return self._resolved[path]
        if path not in self.flat:
            return None
        value = self.flat[path]
        m = ALIAS_RE.match(str(value))
        if m:
            value = self.resolve_path(m.group(1))
        self._resolved[path] = value
        return value

    @staticmethod
    def is_ref(value) -> bool:
        return isinstance(value, str) and bool(ALIAS_RE.match(value))

    @staticmethod
    def ref_path(value: str) -> str | None:
        m = ALIAS_RE.match(value) if isinstance(value, str) else None
        return m.group(1) if m else None

    def resolve_value(self, value):
        """Se value e' un riferimento "{a.b}" ritorna il valore risolto, altrimenti value stesso."""
        path = self.ref_path(value) if isinstance(value, str) else None
        return self.resolve_path(path) if path else value


def dimension_to_float(value) -> float | None:
    """'16', '16pt', 16 -> 16.0"""
    if isinstance(value, (int, float)):
        return float(value)
    m = DIM_RE.match(str(value).strip())
    return float(m.group(1)) if m else None


def hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not HEX_RE.match(value.strip()):
        return None
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Luminanza relativa secondo WCAG 2.x."""
    def channel(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float | None:
    """Rapporto di contrasto WCAG tra due colori hex. None se non parsabili."""
    f, b = hex_to_rgb(fg), hex_to_rgb(bg)
    if f is None or b is None:
        return None
    l1, l2 = relative_luminance(f), relative_luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)

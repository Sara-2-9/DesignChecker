"""Caricamento di regole, catalogo, token e screen JSON dal filesystem."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

RULE_FILES = [
    "ios-hig.yaml",
    "material3.yaml",
    "wcag.yaml",
    "design-system.yaml",
    "expo-rn.yaml",
    "ux-heuristics.yaml",
]


def load_rules(rules_dir: Path) -> list[dict]:
    """Carica tutte le regole dai file YAML della cartella rules/."""
    rules: list[dict] = []
    for name in RULE_FILES:
        path = rules_dir / name
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for rule in data.get("rules", []):
            rule["_file"] = name
            rules.append(rule)
    return rules


def load_catalog(path: Path) -> dict:
    """components.catalog.yaml -> { 'Button': {...}, 'Fab': {...}, ... }"""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {entry["type"]: entry for entry in data.get("components", [])}


def load_tokens(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_screen(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

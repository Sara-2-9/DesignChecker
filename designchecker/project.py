"""Gestione del progetto Expo di destinazione (D28).

Il flusso e': import (figma|code) -> audit -> "dove genero il codice?"
- progetto NUOVO: scaffold completo (come dc generate)
- progetto ESISTENTE: solo i file della schermata, senza mai
  sovrascrivere senza consenso

Il progetto scelto viene ricordato in ~/.designchecker/config.json
(chiave "project"), cosi' gli import successivi non ri-chiedono.
"""
from __future__ import annotations

import json
from pathlib import Path


def is_expo_project(path: Path) -> bool:
    """Vero se la cartella sembra un progetto Expo (package.json con dipendenza expo)."""
    pkg = path / "package.json"
    if not pkg.is_file():
        return False
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    return "expo" in deps


def has_router_structure(path: Path) -> bool:
    """Vero se il progetto usa gia' Expo Router con struttura src/ (SDK 52+)."""
    return (path / "src" / "app").is_dir()

"""Formattazione del report di validazione per il terminale."""
from __future__ import annotations

import sys

from .validator import Finding

_USE_COLOR = sys.stdout.isatty()
_RED, _YELLOW, _GREEN, _DIM, _RESET = "\033[31m", "\033[33m", "\033[32m", "\033[2m", "\033[0m"


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _USE_COLOR else text


def print_report(findings: list[Finding], screen_name: str, rules_count: int) -> None:
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    print()
    print(_c(f"DesignChecker — report di validazione", _DIM))
    print(f"Schermata: {screen_name}   Regole caricate: {rules_count}")
    print("─" * 64)

    if not findings:
        print(_c("✓ Nessuna violazione: la schermata rispetta tutte le regole caricate.", _GREEN))
        return

    for f in errors + warnings:
        if f.severity == "error":
            print(_c(f"✗ ERROR   [{f.rule_id}]", _RED))
        else:
            print(_c(f"⚠ WARNING [{f.rule_id}]", _YELLOW))
        print(f"  Nodo: {f.node_id}")
        print(f"  {f.message}")
        if f.suggestion:
            print(_c(f"  → {f.suggestion}", _DIM))
        if f.source:
            src = f"  Fonte: {f.source}"
            print(_c(src + (f" — {f.source_url}" if f.source_url else ""), _DIM))
        print()

    print("─" * 64)
    summary = f"{len(errors)} errori, {len(warnings)} warning"
    print(_c(summary, _RED if errors else _YELLOW))
    if errors:
        print("Gli errori sono bloccanti: correggili prima di confermare la schermata.")

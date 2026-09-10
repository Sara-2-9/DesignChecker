"""Interfaccia a riga di comando di DesignChecker (MVP).

Uso:
    python3 -m designchecker validate examples/imported-home.screen.json
    python3 -m designchecker rules
    python3 -m designchecker version

Per default cerca rules/, components.catalog.yaml ed examples/tokens.json
nella directory corrente (la radice del progetto DesignChecker).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .loader import load_catalog, load_rules, load_screen, load_tokens
from .report import print_report
from .tokens import TokenStore
from .validator import validate


def _find_project_root() -> Path:
    """Risale dalla cwd cercando la radice del progetto (quella con rules/)."""
    current = Path.cwd()
    for candidate in (current, *current.parents):
        if (candidate / "rules").is_dir():
            return candidate
    return current


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dc",
        description="DesignChecker — valida schermate contro le regole ufficiali UI/UX.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="Valida uno screen JSON")
    p_validate.add_argument("screen", type=Path, help="Percorso dello screen JSON")
    p_validate.add_argument("--tokens", type=Path, default=None,
                            help="tokens.json (default: examples/tokens.json)")
    p_validate.add_argument("--catalog", type=Path, default=None,
                            help="components.catalog.yaml (default: radice progetto)")
    p_validate.add_argument("--rules", type=Path, default=None,
                            help="Cartella delle regole (default: rules/ del progetto)")
    p_validate.add_argument("--platform", choices=["ios", "android", "both"],
                            default="both", help="Piattaforma target")

    p_generate = sub.add_parser("generate",
                                help="Genera un progetto Expo dallo screen JSON (v0.2)")
    p_generate.add_argument("screen", type=Path, help="Percorso dello screen JSON")
    p_generate.add_argument("--out", type=Path, required=True,
                            help="Cartella di output del progetto Expo")
    p_generate.add_argument("--tokens", type=Path, default=None)
    p_generate.add_argument("--catalog", type=Path, default=None)
    p_generate.add_argument("--app-name", default="spesecondivise")

    sub.add_parser("rules", help="Elenca le regole caricate")
    sub.add_parser("version", help="Mostra la versione")

    args = parser.parse_args(argv)
    root = _find_project_root()

    if args.command == "version":
        print(f"DesignChecker {__version__}")
        return

    rules_dir = getattr(args, "rules", None) or (root / "rules")
    catalog_path = getattr(args, "catalog", None) or (root / "components.catalog.yaml")
    tokens_path = getattr(args, "tokens", None) or (root / "examples" / "tokens.json")

    rules = load_rules(rules_dir)

    if args.command == "rules":
        by_file: dict[str, list[dict]] = {}
        for r in rules:
            by_file.setdefault(r.get("_file", "?"), []).append(r)
        print(f"\nRegole caricate da {rules_dir}: {len(rules)}\n")
        for fname, file_rules in by_file.items():
            print(f"{fname} ({len(file_rules)})")
            for r in file_rules:
                phase = r.get("phase", "validate")
                tag = "codegen" if phase == "codegen" else r.get("severity", "?")
                print(f"   [{tag:7}] {r['id']}")
            print()
        return

    if args.command == "validate":
        if not args.screen.exists():
            print(f"File non trovato: {args.screen}", file=sys.stderr)
            sys.exit(2)
        screen = load_screen(args.screen)
        tokens = TokenStore(load_tokens(tokens_path))
        catalog = load_catalog(catalog_path)
        findings = validate(screen, rules, tokens, catalog, platform=args.platform)
        print_report(findings, screen.get("meta", {}).get("name", str(args.screen)),
                     len([r for r in rules if r.get("phase", "validate") == "validate"]))
        sys.exit(1 if any(f.severity == "error" for f in findings) else 0)

    if args.command == "generate":
        from .codegen import Codegen
        if not args.screen.exists():
            print(f"File non trovato: {args.screen}", file=sys.stderr)
            sys.exit(2)
        screen = load_screen(args.screen)
        tokens = TokenStore(load_tokens(tokens_path))
        catalog = load_catalog(catalog_path)
        codegen = Codegen(screen, tokens, catalog, app_name=args.app_name)
        written = codegen.generate(args.out)
        print(f"\n✓ Progetto Expo generato in {args.out} ({len(written)} file)\n")
        print("Per provarlo:")
        print(f"  cd {args.out}")
        print("  npm install && npx expo install --fix")
        print("  npx expo start")
        print("\nNota: Expo Go SDK 56+ non e' sugli store — su iOS usa una dev build")
        print("(`npx expo run:ios` con Xcode, o `eas go`), su Android Expo Go via CLI.")

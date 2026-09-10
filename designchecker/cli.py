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
    """Trova la radice del progetto (quella con rules/): prima dalla cwd,
    poi dalla posizione del pacchetto (per il wrapper globale in ~/.local/bin)."""
    candidates = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parent.parent]
    for candidate in candidates:
        if (candidate / "rules").is_dir():
            return candidate
    return Path.cwd()


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

    p_link = sub.add_parser("link", help="Collega un file Figma (D21)")
    p_link.add_argument("source", choices=["figma"])
    p_link.add_argument("url", help="URL del file Figma")

    sub.add_parser("screens", help="Elenca le schermate del file Figma collegato")

    p_import = sub.add_parser("import", help="Importa una schermata → screen JSON + audit")
    p_import.add_argument("source", choices=["figma"], help="Sorgente (code/shot: v0.3+)")
    p_import.add_argument("frame", help="Nome del frame/schermata da importare")
    p_import.add_argument("--tokens", type=Path, default=None)
    p_import.add_argument("--catalog", type=Path, default=None)
    p_import.add_argument("--platform", choices=["ios", "android", "both"], default="both")
    p_import.add_argument("--fixture", type=Path, default=None,
                          help="Usa un file JSON locale invece della API (per test)")

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

    # ---------------------------------------------------------- figma link/import

    if args.command in ("link", "screens", "import"):
        _figma_commands(args, root)


def _config_path() -> Path:
    return Path.home() / ".designchecker" / "config.json"


def _load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    import json as _json
    return _json.loads(path.read_text(encoding="utf-8"))


def _save_config(config: dict) -> None:
    import json as _json
    import os
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(config, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)  # il token non deve essere leggibile da altri


def _figma_commands(args, root: Path) -> None:
    from .figma_api import FigmaClient, FigmaAPIError, parse_file_key
    from .importer_figma import FigmaImporter, list_frames

    if args.command == "link":
        file_key = parse_file_key(args.url)
        if not file_key:
            print("URL non valido. Atteso: https://www.figma.com/design/<key>/...",
                  file=sys.stderr)
            sys.exit(2)
        import getpass
        token = getpass.getpass("Personal Access Token Figma "
                                "(figma.com/settings, scope file_content:read): ")
        try:
            me = FigmaClient(token).me()
        except FigmaAPIError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        config = _load_config()
        config["figma"] = {"file_key": file_key, "file_url": args.url, "token": token}
        _save_config(config)
        print(f"\n✓ Collegato come {me.get('handle', '?')} ({me.get('email', '?')})")
        print(f"  File: {file_key} — config in ~/.designchecker/config.json (mai nel repo)")
        print("  Nota: il PAT scade entro 90 giorni; 'dc screens' ti avvisera'.")
        print("\nProssimo passo: python3 -m designchecker screens")
        return

    config = _load_config()
    figma_cfg = config.get("figma")
    if not figma_cfg and not getattr(args, "fixture", None):
        print("Nessun file Figma collegato. Prima: python3 -m designchecker link figma <url>",
              file=sys.stderr)
        sys.exit(2)

    if getattr(args, "fixture", None):
        import json as _json
        tree = _json.loads(args.fixture.read_text(encoding="utf-8"))
    else:
        try:
            tree = FigmaClient(figma_cfg["token"]).file_tree(figma_cfg["file_key"], depth=2)
        except FigmaAPIError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    if args.command == "screens":
        frames = list_frames(tree)
        print(f"\nSchermate nel file collegato ({len(frames)}):\n")
        for f in frames:
            print(f"  • {f}")
        print("\nImporta con: python3 -m designchecker import figma \"<nome>\"")
        return

    if args.command == "import":
        tokens = TokenStore(load_tokens(args.tokens or (root / "examples" / "tokens.json")))
        catalog = load_catalog(args.catalog or (root / "components.catalog.yaml"))
        importer = FigmaImporter(tokens, catalog)
        screen = importer.convert_screen(tree.get("document", {}), args.frame)
        if screen is None:
            print(f"Frame '{args.frame}' non trovato. Usa 'dc screens' per l'elenco.",
                  file=sys.stderr)
            sys.exit(2)
        out_dir = root / "imports"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{screen['meta']['id']}.screen.json"
        import json as _json
        out_path.write_text(_json.dumps(screen, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"✓ Importata: {out_path}")

        # audit immediato (D24: tutti gli importer sfociano nel validatore)
        rules = load_rules(root / "rules")
        findings = validate(screen, rules, tokens, catalog, platform=args.platform)
        print_report(findings, screen["meta"]["name"],
                     len([r for r in rules if r.get("phase", "validate") == "validate"]))
        sys.exit(1 if any(f.severity == "error" for f in findings) else 0)

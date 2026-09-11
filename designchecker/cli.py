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
import re
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
    p_import.add_argument("source", choices=["figma", "code"],
                          help="Sorgente: figma (file collegato) o code (file .tsx/.jsx)")
    p_import.add_argument("frame",
                          help="figma: nome del frame/schermata · code: percorso del file .tsx")
    p_import.add_argument("--tokens", type=Path, default=None)
    p_import.add_argument("--catalog", type=Path, default=None)
    p_import.add_argument("--platform", choices=["ios", "android", "both"], default="both")
    p_import.add_argument("--fixture", type=Path, default=None,
                          help="Usa un file JSON locale invece della API (per test)")

    p_project = sub.add_parser("project", help="Mostra/collega il progetto Expo di destinazione")
    p_project.add_argument("path", nargs="?", default=None,
                           help="Percorso del progetto da collegare")
    p_project.add_argument("--forget", action="store_true", help="Scollega il progetto")

    sub.add_parser("rules", help="Elenca le regole caricate")
    sub.add_parser("version", help="Mostra la versione")

    p_serve = sub.add_parser("serve", help="Bridge locale per il plugin Figma (D29)")
    p_serve.add_argument("--port", type=int, default=7357)

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
                     len([r for r in rules if r.get("phase", "validate") == "validate"]),
                     exceptions=screen.get("meta", {}).get("exceptions_applied"))
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

    if args.command == "project":
        _project_command(args)
        return

    if args.command == "serve":
        from .serve import serve
        serve(root, port=args.port)
        return

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


def _offer_codegen(root: Path, screen: dict, tokens, catalog, has_errors: bool) -> None:
    """Dopo un import: chiede dove generare il codice Expo (D28).
    Nuovo progetto su Desktop, progetto esistente, o quello gia' collegato."""
    from .codegen import Codegen
    from .project import has_router_structure, is_expo_project

    if not sys.stdin.isatty():
        print("\nPer generare il codice: designchecker generate <screen.json> --out <dir>")
        return

    config = _load_config()
    linked_path = (config.get("project") or {}).get("path")

    print("\n── Codice Expo ─────────────────────────────────────────")
    if has_errors:
        print("⚠ Ci sono errori bloccanti: il codice rispecchiera' il design cosi' com'e'.")
    print("Vuoi generare il codice di questa schermata in un progetto Expo?")
    if linked_path:
        print(f"  [i] Nel progetto collegato: {linked_path}   (default: Invio)")
    print("  [n] Nuovo progetto (creato sul Desktop)")
    print("  [e] Un altro progetto esistente")
    print("  [s] No, mi basta l'import")
    default = "i" if linked_path else "s"
    choice = (input(f"Scelta [{'/'.join(c for c in ('i' if linked_path else '', 'n', 'e', 's') if c)}]: ")
              .strip().lower() or default)

    if choice == "s" or choice not in ("i", "n", "e"):
        return

    codegen = Codegen(screen, tokens, catalog,
                      app_name=kebab_app_name(screen))

    if choice == "n":
        proposed = codegen.app_name
        name = input(f"Nome del progetto [{proposed}]: ").strip() or proposed
        target = Path.home() / "Desktop" / name
        if target.exists() and any(target.iterdir()):
            print(f"La cartella {target} esiste gia': la tratto come progetto esistente.")
            choice = "i"
            linked_path = str(target)
        else:
            written = codegen.generate(target)
            _save_linked_project(config, target)
            print(f"\n✓ Progetto creato: {target} ({len(written)} file)")
            _print_next_steps(target)
            return

    # ---- progetto esistente (collegato o scelto ora)
    if choice == "e" or not linked_path:
        raw = input("Percorso della cartella del progetto: ").strip()
        if not raw:
            print("Nessun percorso: annullato.")
            return
        linked_path = raw
    project_dir = Path(linked_path).expanduser()
    if not project_dir.is_dir():
        print(f"Cartella non trovata: {project_dir}")
        return
    if not is_expo_project(project_dir):
        print(f"⚠ {project_dir} non sembra un progetto Expo (manca la dipendenza 'expo').")
        if input("Continuare comunque? [s/N]: ").strip().lower() != "s":
            return
    elif not has_router_structure(project_dir):
        print("⚠ Il progetto non usa ancora Expo Router con src/app/: creo la struttura.")
    _save_linked_project(config, project_dir)

    files = codegen.project_files()
    conflicts = [project_dir / rel for rel in files if (project_dir / rel).exists()]
    overwrite = False
    if conflicts:
        print("\nQuesti file esistono gia':")
        for path in conflicts:
            print(f"  • {path.relative_to(project_dir)}")
        overwrite = input("Sovrascriverli? [s/N]: ").strip().lower() == "s"
    written, skipped = codegen.generate_into(project_dir, overwrite=overwrite)
    print(f"\n✓ Scritti {len(written)} file in {project_dir}")
    for path in written:
        print(f"  + {path.relative_to(project_dir)}")
    if skipped:
        print(f"  Saltati (gia' esistenti): {len(skipped)}")
    _print_next_steps(project_dir, existing=True)


def kebab_app_name(screen: dict) -> str:
    from .codegen import kebab
    name = screen.get("meta", {}).get("name", "mia-app")
    name = re.sub(r"\s*\(import[^)]*\)", "", name)  # "home (import Figma)" -> "home"
    return kebab(name) or "mia-app"


def _save_linked_project(config: dict, path: Path) -> None:
    config["project"] = {"path": str(path)}
    _save_config(config)
    print(f"  Progetto collegato salvato (cambialo con: designchecker project <path>)")


def _print_next_steps(project_dir: Path, existing: bool = False) -> None:
    print("\nPer vederla sul simulatore:")
    print(f"  cd {project_dir}")
    if not existing:
        print("  npm install && npx expo install --fix")
    print("  npx expo start   (poi 'i' per iOS / 'a' per Android)")


def _project_command(args) -> None:
    """`dc project` mostra il progetto collegato; `dc project <path>` lo cambia."""
    from .project import is_expo_project
    config = _load_config()
    if getattr(args, "forget", False):
        config.pop("project", None)
        _save_config(config)
        print("✓ Progetto scollegato.")
        return
    if args.path:
        path = Path(args.path).expanduser()
        if not path.is_dir():
            print(f"Cartella non trovata: {path}", file=sys.stderr)
            sys.exit(2)
        if not is_expo_project(path):
            print(f"⚠ {path} non sembra un progetto Expo (manca la dipendenza 'expo').")
        _save_linked_project(config, path)
        print(f"✓ Progetto collegato: {path}")
        return
    current = (config.get("project") or {}).get("path")
    if current:
        print(f"Progetto collegato: {current}")
        print("Cambia: designchecker project <path> · Scollega: designchecker project --forget")
    else:
        print("Nessun progetto collegato. Ti verra' chiesto al prossimo import,")
        print("oppure: designchecker project <path>")


def _code_import(args, root: Path) -> None:
    """`dc import code <file.tsx>`: parsing statico + conversione + audit (D23/D24)."""
    from .codegen import kebab
    from .importer_code import CodeImporter, CodeImportError, parse_tsx
    import json as _json

    source_path = Path(args.frame).expanduser()
    if not source_path.is_file():
        print(f"File non trovato: {source_path}", file=sys.stderr)
        sys.exit(2)
    try:
        parsed = parse_tsx(source_path, root / "tools")
    except CodeImportError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    tokens = TokenStore(load_tokens(args.tokens or (root / "examples" / "tokens.json")))
    catalog = load_catalog(args.catalog or (root / "components.catalog.yaml"))
    importer = CodeImporter(tokens, catalog, tools_dir=root / "tools")
    screen = importer.convert_screen(parsed, str(source_path))

    out_dir = root / "imports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{screen['meta']['id']}.screen.json"
    out_path.write_text(_json.dumps(screen, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"✓ Importata dal codice: {out_path}")

    rules = load_rules(root / "rules")
    findings = validate(screen, rules, tokens, catalog, platform=args.platform)
    print_report(findings, screen["meta"]["name"],
                 len([r for r in rules if r.get("phase", "validate") == "validate"]),
                 exceptions=screen.get("meta", {}).get("exceptions_applied"))
    has_errors = any(f.severity == "error" for f in findings)
    _offer_codegen(root, screen, tokens, catalog, has_errors)
    sys.exit(1 if has_errors else 0)


def _figma_commands(args, root: Path) -> None:
    from .figma_api import FigmaClient, FigmaAPIError, parse_file_key
    from .importer_figma import FigmaImporter, list_frames

    if args.command == "import" and args.source == "code":
        _code_import(args, root)
        return

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
                     len([r for r in rules if r.get("phase", "validate") == "validate"]),
                     exceptions=screen.get("meta", {}).get("exceptions_applied"))
        has_errors = any(f.severity == "error" for f in findings)
        _offer_codegen(root, screen, tokens, catalog, has_errors)
        sys.exit(1 if has_errors else 0)

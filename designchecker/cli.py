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

    p_trace = sub.add_parser("trace",
                             help="Mappa completa della pipeline di uno screen: "
                                  "file letti/scritti, cosa parte verso l'AI (D37)")
    p_trace.add_argument("screen", type=Path, help="Percorso dello screen JSON")

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
    p_serve.add_argument("--quiet", action="store_true",
                         help="Niente log delle attivita' (default: log visibile, D37)")
    p_serve.add_argument("--verbose", action="store_true",
                         help="Mostra nel log anche il PROMPT completo inviato "
                              "all'AI e la RISPOSTA grezza, per ogni /review e /fix (D38)")
    p_serve.add_argument("--autogen", nargs="?", const="~/Desktop/dck-preview",
                         default=None, metavar="PATH",
                         help="Rigenera il progetto Expo a ogni export/fix (D36). "
                              "Senza PATH usa ~/Desktop/dck-preview")

    p_ai = sub.add_parser("ai", help="Configura il provider AI: rileva, menu, probe (D31)")
    p_ai.add_argument("--probe", action="store_true",
                      help="Ri-testa il provider salvato senza riconfigurare")

    p_fix = sub.add_parser("fix", help="L'AI propone una patch, il validatore la approva (D31)")
    p_fix.add_argument("screen", type=Path, help="Percorso dello screen JSON")
    p_fix.add_argument("--tokens", type=Path, default=None)
    p_fix.add_argument("--catalog", type=Path, default=None)
    p_fix.add_argument("--platform", choices=["ios", "android", "both"], default="both")
    p_fix.add_argument("--context", default=None,
                       help="Contesto opzionale sull'app per calibrare l'AI (D35)")

    p_review = sub.add_parser("review", help="Valutazione qualitativa AI del design (D31)")
    p_review.add_argument("screen", type=Path, help="Percorso dello screen JSON")
    p_review.add_argument("--tokens", type=Path, default=None)
    p_review.add_argument("--catalog", type=Path, default=None)
    p_review.add_argument("--platform", choices=["ios", "android", "both"], default="both")
    p_review.add_argument("--context", default=None,
                          help="Contesto opzionale sull'app per calibrare l'AI (D35)")

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
        codegen = Codegen(screen, tokens, catalog, app_name=args.app_name,
                          assets_dir=args.screen.parent / "assets" / screen.get("meta", {}).get("id", ""))
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
        serve(root, port=args.port, autogen=args.autogen, log=not args.quiet,
              verbose_ai=args.verbose)
        return

    if args.command == "trace":
        _trace_command(args, root, rules)
        return

    if args.command == "ai":
        _ai_command(args)
        return

    if args.command in ("fix", "review"):
        _ai_screen_command(args, root, rules)
        return

    if args.command in ("link", "screens", "import"):
        _figma_commands(args, root)


def _config_path() -> Path:
    return Path.home() / ".designchecker" / "config.json"


def _trace_command(args, root: Path, rules) -> None:
    """D37: mappa completa della pipeline di uno screen — cosa viene letto,
    cosa viene scritto, cosa parte verso l'AI e cosa resta deterministico."""
    from .codegen import Codegen

    if not args.screen.exists():
        print(f"File non trovato: {args.screen}", file=sys.stderr)
        sys.exit(2)
    screen = load_screen(args.screen)
    tokens = TokenStore(load_tokens(root / "examples" / "tokens.json"))
    catalog = load_catalog(root / "components.catalog.yaml")
    sid = screen.get("meta", {}).get("id", "screen")

    def count(node: dict) -> int:
        return 1 + sum(count(c) for c in node.get("children", []) or [])

    print(f"\n═══ TRACCIA PIPELINE: {args.screen} ═══\n")

    print("1. LETTURA (input del sistema)")
    kb = max(args.screen.stat().st_size // 1024, 1)
    print(f"   screen JSON : {args.screen} ({kb} KB, id '{sid}', "
          f"{count(screen.get('root', {}))} nodi)")
    by_file: dict[str, list] = {}
    for r in rules:
        by_file.setdefault(r.get("_file", "?"), []).append(r)
    print(f"   regole      : {len(rules)} da rules/ — "
          + ", ".join(f"{f} ({len(rs)})" for f, rs in by_file.items()))
    print(f"   token       : examples/tokens.json ({len(tokens.flat)} token)")
    print(f"   catalogo    : components.catalog.yaml ({len(catalog)} componenti)")

    findings = validate(screen, rules, tokens, catalog)
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    print("\n2. VALIDAZIONE (Python deterministico, zero AI — l'arbitro)")
    print(f"   → {len(errors)} errori, {len(warnings)} warning")
    for f in findings[:6]:
        print(f"     [{f.severity}] {f.rule_id} su '{f.node_id}'")
    if len(findings) > 6:
        print(f"     … e altri {len(findings) - 6}")

    imports = root / "imports"
    assets_dir = imports / "assets" / sid
    pngs = list(assets_dir.glob("*.png")) if assets_dir.is_dir() else []
    print("\n3. BRIDGE (dck serve, solo localhost:7357) — all'export dal plugin:")
    print(f"   scrive    : imports/{sid}.screen.json + sidecar .{sid}.export.sha256")
    print(f"   asset     : imports/assets/{sid}/ ({len(pngs)} PNG, "
          f"{sum(p.stat().st_size for p in pngs) // 1024} KB)")
    print("   protezioni: backup .preexport.bak se il file cambia fuori dal canvas;")
    print("               path asset sanitizzati; scritture solo dentro imports/")

    config = _load_config()
    ai_cfg = config.get("ai") or {}
    print("\n4. AI (SOLO su tua richiesta: review / fix)")
    if ai_cfg.get("provider"):
        print(f"   provider : {ai_cfg.get('provider')} · modello {ai_cfg.get('model')}")
    else:
        print("   provider : non configurato (dck ai)")
    print("   review → manda: screen JSON + finding + regolamento + contesto;")
    print("            riceve: solo testo (parere consultivo, nessuna scrittura)")
    print("   fix    → manda: lo stesso + lista dei token reali;")
    print("            riceve: JSON Patch → il VALIDATORE la approva o rifiuta")
    print("   chiavi  : ~/.designchecker/config.json (chmod 600, mai nel repo);")
    print("             escono solo verso il provider che hai scelto")
    print("   ispeziona: `dck serve --verbose` mostra prompt e risposte completi (D38)")

    codegen = Codegen(screen, tokens, catalog, assets_dir=assets_dir)
    print("\n5. CODEGEN (Python deterministico, zero AI) — dck generate produce:")
    for rel in sorted(codegen.full_project_files()):
        print(f"     {rel}")
    print(f"   + i PNG di imports/assets/{sid}/ copiati in src/assets/ come require()")

    print("\n6. APP (toolchain Expo standard, non DesignChecker)")
    print("   prima volta : cd <cartella> && npm install && npx expo start")
    print("   poi         : Fast Refresh aggiorna l'app a ogni rigenerazione\n")


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
                      app_name=kebab_app_name(screen),
                      assets_dir=root / "imports" / "assets" / screen.get("meta", {}).get("id", ""))

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
    """`dck project` mostra il progetto collegato; `dc project <path>` lo cambia."""
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
    """`dck import code <file.tsx>`: parsing statico + conversione + audit (D23/D24)."""
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


# ---------------------------------------------------------- AI (D31)

def _resolve_provider(config: dict, task: str = "patch_fix"):
    """Provider+modello dalla config; None se non configurato."""
    from . import ai as _ai
    ai_cfg = config.get("ai") or {}
    pid, model = ai_cfg.get("provider"), ai_cfg.get("model")
    if not pid:
        return None, None
    tmpl = next((p for p in _ai.PROVIDERS if p.pid == pid), None)
    if tmpl is None:
        return None, None
    p = _ai.Provider(tmpl.pid, tmpl.label, tmpl.group, tmpl.style,
                     ai_cfg.get("base_url") or tmpl.base_url, tmpl.env_key,
                     list(tmpl.models), True, "", tmpl.alt_env,
                     temperature=tmpl.temperature)
    if not model:
        detected = {d.pid: d for d in _ai.detect_providers(config)}
        if detected.get(pid) and detected[pid].models:
            p.models = detected[pid].models
        model = _ai.pick_model(p, task)
    return p, model


def _ai_command(args) -> None:
    from . import ai as _ai

    config = _load_config()

    if args.probe:
        p, model = _resolve_provider(config)
        if p is None:
            print("Nessun provider configurato. Lancia: dck ai", file=sys.stderr)
            sys.exit(2)
        print(f"Probe: {p.label} · modello {model}…")
        ok, detail = _ai.probe(p, model, config)
        print(f"{'✓ Risponde' if ok else '✗ Non risponde'}: {detail}")
        sys.exit(0 if ok else 1)

    print("\n── Provider AI (D31) ───────────────────────────────────")
    providers = _ai.detect_providers(config)
    avail = [p for p in providers if p.detected]
    for group, title in (("A", "Locale"), ("B", "Cloud (API key)")):
        print(f"\nGruppo {group} — {title}:")
        for p in [x for x in providers if x.group == group]:
            mark = "●" if p.detected else "○"
            extra = f" — {p.note}" if p.note else " — non rilevato"
            print(f"  {mark} {p.label}{extra}")
    agents = _ai.cli_agents_present()
    if agents:
        print(f"\nℹ Rilevati CLI agent: {', '.join(agents)}. DesignChecker non li "
              "esegue: la stessa chiave del provider (es. Kimi Code) funziona anche qui.")

    # Opzioni: provider gia' pronti + provider cloud configurabili incollando la chiave
    options = [(p, "use") for p in avail]
    options += [(p, "key") for p in providers if p.group == "B" and not p.detected]

    if not sys.stdin.isatty():
        if not avail:
            print("\nNessun provider rilevato. Configura una API key in env o "
                  "nel config, oppure avvia Ollama/LM Studio.", file=sys.stderr)
            sys.exit(2)
        p = avail[0]
        model = _ai.pick_model(p)
        print(f"\n(non interattivo) Uso il primo disponibile: {p.label} · {model}")
    else:
        print()
        for i, (p, mode) in enumerate(options, 1):
            if mode == "use":
                print(f"  [{i}] {p.label} — pronto, modello: {_ai.pick_model(p) or '?'}")
            else:
                print(f"  [{i}] {p.label} — incolla la API key per attivarlo")
        choice = input("Scegli il provider (numero): ").strip()
        try:
            p, mode = options[int(choice) - 1]
        except (ValueError, IndexError):
            print("Scelta non valida.", file=sys.stderr)
            sys.exit(2)

        import getpass
        if p.pid == "custom":
            base_url = input("Base URL OpenAI-compatibile (es. https://host/v1): ").strip()
            if not base_url:
                print("Base URL obbligatoria.", file=sys.stderr)
                sys.exit(2)
            p.base_url = base_url
            config.setdefault("ai", {})["base_url"] = base_url
        if mode == "key":
            key = getpass.getpass(f"API key per {p.label} (nascosta, salvata "
                                  "in ~/.designchecker/config.json): ").strip()
            if not key:
                print("Nessuna chiave inserita.", file=sys.stderr)
                sys.exit(2)
            # la chiave si salva SUBITO: un probe fallito non la perde
            config.setdefault("ai", {}).setdefault("keys", {})[p.pid] = key
            _save_config(config)
            p.detected = True
            # modelli live dall'endpoint; fallback ai default noti
            p.models = _ai.fetch_models(p, config)
        model = _ai.pick_model(p)
        if len(p.models) > 1 or not model:
            if len(p.models) > 1:
                print("  Modelli disponibili: " + ", ".join(p.models[:8]))
            alt = input(f"Modello [{model or 'da specificare'}]: ").strip()
            if alt:
                model = alt

    print(f"\nProbe: {p.label} · {model}…")
    ok, detail = _ai.probe(p, model, config)
    if not ok:
        print(f"✗ Il provider non risponde: {detail}", file=sys.stderr)
        if p.pid == "kimicode":
            print("  Suggerimento: la chiave Kimi Code si genera dalla console "
                  "Kimi Code (kimi.com/code), NON da platform.kimi.ai — "
                  "le chiavi non sono intercambiabili (errore 401).")
        sys.exit(1)
    print(f"✓ Risponde: {detail}")
    config.setdefault("ai", {})["provider"] = p.pid
    config["ai"]["model"] = model
    _save_config(config)
    print(f"✓ Salvato in ~/.designchecker/config.json: {p.pid} · {model}")


def _ai_screen_command(args, root: Path, rules) -> None:
    from . import ai as _ai
    from . import patcher

    if not args.screen.exists():
        print(f"File non trovato: {args.screen}", file=sys.stderr)
        sys.exit(2)
    config = _load_config()
    task = "review" if args.command == "review" else "patch_fix"
    p, model = _resolve_provider(config, task)
    if p is None or not model:
        print("Nessun provider AI configurato. Lancia prima: dck ai", file=sys.stderr)
        sys.exit(2)

    screen = load_screen(args.screen)
    tokens = TokenStore(load_tokens(args.tokens or (root / "examples" / "tokens.json")))
    catalog = load_catalog(args.catalog or (root / "components.catalog.yaml"))
    findings = validate(screen, rules, tokens, catalog, platform=args.platform)

    def chat_fn(messages):
        return _ai.chat(p, model, messages, config)

    name = screen.get("meta", {}).get("name", str(args.screen))

    if args.command == "review":
        print(f"── Valutazione AI ({p.label} · {model}) di '{name}' ──\n")
        messages = patcher.build_review_prompt(screen, findings,
                                               context=args.context, rules=rules)
        try:
            print(chat_fn(messages).strip())
        except Exception as e:
            print(f"✗ Il provider non risponde: {e}", file=sys.stderr)
            sys.exit(1)
        print("\n(parere consultivo: il validatore deterministico resta l'arbitro)")
        return

    # fix
    print(f"── Fix AI ({p.label} · {model}) su '{name}' ──")

    def validate_fn(scr):
        fs = validate(scr, rules, tokens, catalog, platform=args.platform)
        return [f for f in fs if f.severity == "error"], \
               [f for f in fs if f.severity == "warning"]

    result = patcher.fix_loop(screen, findings, validate_fn, chat_fn,
                              token_paths=list(tokens.flat),
                              context=args.context, rules=rules)
    for line in result["log"]:
        print(f"  {line}")
    if result["applied"]:
        import json as _json
        bak = args.screen.with_suffix(args.screen.suffix + ".bak")
        if not bak.exists():
            bak.write_text(args.screen.read_text(encoding="utf-8"), encoding="utf-8")
        args.screen.write_text(_json.dumps(result["screen"], indent=2,
                                           ensure_ascii=False), encoding="utf-8")
        print(f"\n✓ Patch applicata ({len(result['ops'])} operazioni):")
        for op in result["ops"]:
            print(f"    {op['op']:7} {op['path']}")
        print(f"  File aggiornato: {args.screen} (backup: {bak.name})")
        print("  Su Figma: dal plugin, Render per vedere la versione corretta.")
        print("  Nota: il frame ORIGINALE su Figma e' ancora la versione vecchia —")
        print("  riesportandolo sovrascrivi il fix (verra' salvato un backup")
        print("  .preexport.bak). Continua a lavorare sul frame renderizzato.")
    else:
        print("\n✗ Nessuna correzione applicata: il file resta invariato.")
        print("  Puoi correggere a mano o riprovare con un altro modello (dck ai).")
    sys.exit(0 if result["applied"] or result["before"][0] == 0 else 1)

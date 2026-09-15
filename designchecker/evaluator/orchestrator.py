"""Orchestratore padre — valuta, smista, unisce. Mai valida.

Fasi: diagnosi cieca (JSON+PNG, senza findings) -> ricerca per ruolo ->
riconciliazione con findings fallibili -> fan-out 6 figli in parallelo ->
merge con risoluzione conflitti + check coerenza scopo -> patch unica
per node-id -> gate del validatore (fuori da qui) decide.
"""
from __future__ import annotations

import json

from .classify import classify, heuristic_role
from .research_agentic import agentic_research, queries_for_role, research_block, verify_sources
from .subagents import SUBAGENTS, build_sub_messages, parse_sub_fixes
from .vision import vision_note

BLIND_SYSTEM = """Sei il padre valutatore di DesignChecker (flusso Proponi nuovo design).
Fai una diagnosi cieca: NON hai ancora visto i findings del validatore.
Dallo screen JSON (+ PNG se presente) e dal ruolo, elenca i 5 problemi peggiori
per obiettivo/gerarchia/carico/affordance/fiducia, con id nodo.
Rispondi SOLO con array JSON [{"node": "...", "issue": "..."}]."""


def _nodes_index(screen: dict) -> dict:
    idx = {}

    def walk(n):
        if not isinstance(n, dict):
            return
        if n.get("id"):
            idx[n["id"]] = n
        for c in n.get("children", []) or []:
            walk(c)
    if isinstance(screen.get("root"), dict):
        walk(screen["root"])
    return idx


def _phase(log: list, emit, text: str) -> None:
    log.append(text)
    if emit is not None:
        try:
            emit(text)
        except Exception:
            pass


def run_propose(screen: dict, findings: list | None = None,
                chat_fn=None, search_fn=None,
                token_paths: list | None = None,
                token_values: dict | None = None,
                context: str | None = None,
                platform: str | None = None, theme: str | None = None,
                preview_base64: str | None = None,
                baseline: bool = True,
                cache_dir=None,
                emit=None) -> dict:
    """Esegue l'intero giro padre+figli. Ritorna dict con role, sources,
    blind, fixes, ops, log. La validazione finale (gate) resta fuori."""
    from ..patcher import normalize_ops
    log: list[str] = []
    findings = findings or []

    sid = (screen.get("meta", {}) or {}).get("id", "screen")

    # 1. classify ruolo/scopo
    _phase(log, emit, "call ai-padre · classify ruolo/scopo")
    try:
        role_info = classify(screen, chat_fn, context, preview_base64)
    except Exception:
        role_info = heuristic_role(screen)
        log.append("classify LLM non riuscita: fallback euristiche")
    role, goal = role_info["role"], role_info["user_goal"]
    _phase(log, emit, f"ruolo rilevato: {role} — {goal}")

    # 2. diagnosi cieca (senza findings -> anti-ancoraggio)
    _phase(log, emit, "call ai-padre · diagnosi cieca (senza validatore)")
    blind: list = []
    try:
        from ..patcher import extract_json
        from .vision import user_content_with_image
        raw = chat_fn([
            {"role": "system", "content": BLIND_SYSTEM + "\n" + vision_note(bool(preview_base64))},
            {"role": "user", "content": user_content_with_image(
                f"RUOLO: {role} — {goal}\nSCREEN:\n{json.dumps(screen, ensure_ascii=False)}",
                preview_base64)},
        ])
        blind = extract_json(raw)
        if not isinstance(blind, list):
            blind = []
    except Exception as e:
        log.append(f"diagnosi cieca non riuscita ({str(e)[:80]}), proseguo")
        blind = []

    # 3. ricerca per ruolo (agentica se possibile, fallback codice)
    _phase(log, emit, f"research per ruolo '{role}'")
    sources: list = []
    dropped: list = []
    if search_fn is not None and chat_fn is not None:
        try:
            res = agentic_research(role, chat_fn, search_fn, platform,
                                   cache_dir, log)
            sources, dropped = res["sources"], res["dropped"]
        except Exception as e:
            log.append(f"research agentica fallita ({str(e)[:80]}): fallback query codice")
    if not sources and search_fn is not None:
        seen: set[str] = set()
        for q in queries_for_role(role, platform):
            try:
                valid, drop = verify_sources(search_fn(q), seen)
                sources.extend(valid)
                dropped.extend(drop)
            except Exception:
                continue
            if len(sources) >= 8:
                break
        log.append(f"research fallback: {len(sources)} fonti")
    research_txt = research_block(sources)

    # 4. riconciliazione con findings (solo se baseline attiva)
    if baseline and findings:
        flist = "; ".join(f"{f.rule_id} su '{f.node_id}'" for f in findings[:12])
        _phase(log, emit, f"riconciliazione con validatore: {len(findings)} findings come parere fallibile")
    else:
        flist = "(baseline disattivata: nessuna influenza del validatore)"
        _phase(log, emit, "baseline disattivata: il padre lavora solo da JSON+PNG+ricerca")

    # 5. fan-out figli
    idx = _nodes_index(screen)
    token_block = ("TOKEN (path → valore nel tema; unici validi):\n"
                   + ("\n".join(f"- {p} → {(token_values or {}).get(p, p)}"
                                for p in (token_paths or [])[:60])
                      if token_paths else "(nessun catalogo token)"))
    all_fixes: list = []
    for spec in SUBAGENTS:
        _phase(log, emit, f"call sub-agent {spec['id']} ({spec['title']})")
        # sottoinsieme nodi: tutti per MVP (i figli filtrano da soli la porzione)
        msgs = build_sub_messages(spec["id"], screen, idx, token_block,
                                  research_txt + f"\nFINDINGS (parere, non verita'): {flist}",
                                  role, goal, platform, theme)
        try:
            fixes = parse_sub_fixes(chat_fn(msgs))
        except Exception as e:
            log.append(f"sub-agent {spec['id']} fallito ({str(e)[:80]})")
            continue
        _phase(log, emit, f"sub-agent {spec['id']} done: {len(fixes)} fix")
        for fx in fixes:
            fx["_from"] = spec["id"]
        all_fixes.extend(fixes)

    # 6. merge: deduplica per (node, key), ultimo vince, max 80 per propose
    _phase(log, emit, f"padre merge {len(all_fixes)} fix → patch unica + check coerenza scopo")
    merged: dict[tuple, dict] = {}
    for fx in all_fixes:
        key = (str(fx.get("node", "")), str(fx.get("key", fx.get("path", ""))))
        merged[key] = fx
    fixes = list(merged.values())[:80]
    try:
        ops = normalize_ops(screen, fixes)
    except Exception as e:
        log.append(f"merge: patch non normalizzabile ({e})")
        ops = []

    return {"role": role_info, "sources": sources, "dropped": dropped,
            "blind": blind[:5] if isinstance(blind, list) else [],
            "fixes": fixes, "ops": ops, "log": log, "screen_id": sid}

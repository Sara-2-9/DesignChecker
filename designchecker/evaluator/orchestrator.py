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


def _token_block(token_paths: list | None, token_values: dict | None,
                 screen: dict) -> str:
    """Catalogo token ordinato per rilevanza: prima i token gia' usati dallo
    screen (quelli che il figlio deve riusare per fix cromatici), poi
    color/spacing/radius/typography, poi il resto. Il vecchio taglio ai primi
    60 path poteva escludere proprio il token giusto (bug Pay-Frame: i fix su
    `bg` non avevano alternativa visibile)."""
    if not token_paths:
        return "(nessun catalogo token)"
    used: set[str] = set()

    def walk(n):
        if not isinstance(n, dict):
            return
        for section in ("style", "layout"):
            for v in (n.get(section, {}) or {}).values():
                vals = v.values() if isinstance(v, dict) else [v]
                for item in vals:
                    if isinstance(item, str) and item.startswith("{") and item.endswith("}"):
                        used.add(item[1:-1])
        for c in n.get("children", []) or []:
            walk(c)
    walk(screen.get("root", {}) or {})

    def rank(p: str) -> tuple:
        group = p.split(".")[0] if "." in p else p
        return (0 if p in used else 1,
                {"color": 0, "spacing": 1, "radius": 2, "typography": 3}.get(group, 4),
                p)

    ordered = sorted(dict.fromkeys(token_paths), key=rank)[:120]
    lines = "\n".join(f"- {p} → {(token_values or {}).get(p, p)}" for p in ordered)
    return f"TOKEN (path → valore nel tema; unici validi):\n{lines}"


def _design_dna(screen: dict, token_values: dict | None = None) -> str:
    """DNA visivo estratto dal frame reale: il padre (che ha visto il PNG)
    lo distilla in testo per i figli bendati. Senza, ogni figlio inventa
    un grigio diverso e il merge diventa patchwork (bug Pay-Frame)."""
    bgs: dict[str, int] = {}
    txts: dict[str, int] = {}
    radii: dict[str, int] = {}
    variants: dict[str, int] = {}

    def walk(n):
        if not isinstance(n, dict):
            return
        st, pr = n.get("style", {}) or {}, n.get("props", {}) or {}
        for k, d in (("background", bgs), ("color", txts), ("radius", radii)):
            v = st.get(k)
            if isinstance(v, str):
                d[v] = d.get(v, 0) + 1
        if isinstance(pr.get("variant"), str):
            variants[pr["variant"]] = variants.get(pr["variant"], 0) + 1
        for c in n.get("children", []) or []:
            walk(c)
    walk(screen.get("root", {}) or {})

    def top(d: dict, n: int = 3) -> str:
        items = sorted(d.items(), key=lambda kv: -kv[1])[:n]
        return ", ".join(f"{k}×{v}" for k, v in items) or "—"

    def val(ref: str) -> str:
        if token_values and ref.startswith("{") and ref.endswith("}"):
            return str(token_values.get(ref[1:-1], ref))
        return ref
    bg_show = ", ".join(
        f"{k}({val(k)})×{v}" for k, v in sorted(bgs.items(), key=lambda kv: -kv[1])[:3]
    ) or "—"
    return ("DNA VISIVO (preserva: evolvi dentro questi, non aggiungere nuove "
            "superfici/colori salvo brand):\n"
            f"- superfici: {bg_show}\n"
            f"- testi: {top(txts)}\n"
            f"- radius: {top(radii)}\n"
            f"- varianti tipo: {top(variants)}")


def _platform_dialect(platform: str | None) -> str:
    if platform == "ios":
        return ("DIALETTO iOS 26 Liquid Glass: superfici scure (#000 sfondo, "
                "card secondarie), corner continui 16-22, task circoscritto in "
                "sheet con grabber+scrim (mai overlay fullscreen nero), CTA filled "
                "unica, gerarchia con colore+spazio non ombre.")
    if platform == "android":
        return ("DIALETTO Material 3 expressive: superfici tonal, corner 12-28, "
                "FAB singolo, CTA filled/tonal unica, stati pressed/disabled visibili.")
    return ("DIALETTO custom: vincoli piu' stretti delle due piattaforme, "
            "convenzioni singole adattabili.")


def _coherence_polish(screen: dict, fixes: list) -> tuple[list, list[str]]:
    """Polish di coerenza del padre: scarta i fix che sporcano il DNA.

    - doppio background contenitore+figlio identico (es. add-money Stack e
      rectangle-5432 entrambi primary): tiene il figlio, scarta il padre;
    - tetto superfici/testi distinti: oltre 4 bg o 3 colori testo, scarta gli
      ultimi arrivati. Ritorna (fixes_tenuti, note_log)."""
    notes: list[str] = []
    parent_of: dict[str, str | None] = {}
    by_id: dict[str, dict] = {}

    def walk(n, parent):
        if not isinstance(n, dict):
            return
        if n.get("id"):
            by_id[n["id"]] = n
            parent_of[n["id"]] = parent.get("id") if isinstance(parent, dict) else None
        for c in n.get("children", []) or []:
            walk(c, n)
    walk(screen.get("root", {}) or {}, None)

    bg_fix: dict[str, str] = {}
    for fx in fixes:
        if isinstance(fx, dict) and fx.get("key") == "style/background":
            bg_fix[str(fx.get("node"))] = str(fx.get("value"))
    drop: set[int] = set()
    for i, fx in enumerate(fixes):
        if not isinstance(fx, dict) or fx.get("key") != "style/background":
            continue
        nid, val = str(fx.get("node")), str(fx.get("value"))
        node = by_id.get(nid, {})
        for c in (node.get("children", []) or []):
            cid = c.get("id") if isinstance(c, dict) else None
            if cid and bg_fix.get(cid) == val:
                drop.add(i)
                notes.append(f"coerenza: bg ridondante su contenitore '{nid}' (tiene figlio)")
                break
    kept = [fx for i, fx in enumerate(fixes) if i not in drop]
    bgs: set[str] = set()
    txts: set[str] = set()

    def collect(n):
        st = n.get("style", {}) or {} if isinstance(n, dict) else {}
        if isinstance(st.get("background"), str):
            bgs.add(st["background"])
        if isinstance(st.get("color"), str):
            txts.add(st["color"])
        for c in (n.get("children", []) or []):
            collect(c)
    collect(screen.get("root", {}) or {})
    for fx in kept:
        if isinstance(fx, dict) and fx.get("key") == "style/background":
            bgs.add(str(fx.get("value")))
        if isinstance(fx, dict) and fx.get("key") == "style/color":
            txts.add(str(fx.get("value")))
    if len(bgs) > 4 or len(txts) > 3:
        notes.append(f"coerenza: superfici {len(bgs)}, testi {len(txts)} — oltre il tetto (4/3)")
    return kept, notes


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
    if not sources:
        if search_fn is None:
            log.append("research: nessuno search_fn (offline/test) — i figli lavorano da regolamento")
        else:
            log.append("research: 0 fonti (rete fallita o query vuote) — i figli lavorano da regolamento")
    research_txt = research_block(sources)

    # 4. riconciliazione con findings (solo se baseline attiva)
    if baseline and findings:
        flist = "; ".join(f"{f.rule_id} su '{f.node_id}'" for f in findings[:12])
        _phase(log, emit, f"riconciliazione con validatore: {len(findings)} findings come parere fallibile")
    else:
        flist = "(baseline disattivata: nessuna influenza del validatore)"
        _phase(log, emit, "baseline disattivata: il padre lavora solo da JSON+PNG+ricerca")

    # 4b. direzione estetica: DNA + dialetto + diagnosi cieca riusata.
    # La blind era calcolata e mai usata (token buttati); ora guida i figli.
    # D49: il brand letto dal frame entra nella direzione (intoccabile).
    from ..tokens import screen_brand as _screen_brand
    _brand = _screen_brand(screen)
    brand_line = ("BRAND DELLO SCREEN (identita' letta dal frame, intoccabile — "
                  "mai mapparli su altri token, mai hex nuovi):\n" +
                  "\n".join(f"- {p} → {v}" for p, v in _brand.items())) \
        if _brand else ("BRAND DELLO SCREEN: nessun brand registrato — "
                        "usa i token della lista.")
    style_block = (_design_dna(screen, token_values) + "\n"
                   + _platform_dialect(platform) + "\n" + brand_line)
    if isinstance(blind, list) and blind:
        issues = "; ".join(
            f"{b.get('node')}: {b.get('issue')}" for b in blind[:5]
            if isinstance(b, dict) and b.get("node"))
        blind_txt = f"DIAGNOSI CIECA DEL PADRE (dal PNG reale, priorita'): {issues}" if issues else ""
    else:
        blind_txt = ""

    # 5. fan-out figli in parallelo (thread): il tempo totale diventa il
    # max dei figli invece della somma (~9 min -> ~2 min nel test Pay-Frame).
    # L'ordine di merge resta quello di SUBAGENTS per determinismo.
    idx = _nodes_index(screen)
    token_block = _token_block(token_paths, token_values, screen)
    _phase(log, emit, f"fan-out parallelo: {len(SUBAGENTS)} sub-agent insieme")
    all_fixes: list = []
    import concurrent.futures as _fut
    import time as _time

    def _run_one(spec: dict) -> tuple[str, list, float, str]:
        msgs = build_sub_messages(spec["id"], screen, idx, token_block,
                                  research_txt + f"\nFINDINGS (parere, non verita'): {flist}",
                                  role, goal, platform, theme,
                                  style_block=style_block, blind_txt=blind_txt)
        t0 = _time.monotonic()
        try:
            fixes = parse_sub_fixes(chat_fn(msgs))
            return spec["id"], fixes, _time.monotonic() - t0, ""
        except Exception as e:
            return spec["id"], [], _time.monotonic() - t0, str(e)[:80]

    with _fut.ThreadPoolExecutor(max_workers=len(SUBAGENTS)) as pool:
        future_of = {pool.submit(_run_one, spec): spec for spec in SUBAGENTS}
        pending = set(future_of)
        for spec in SUBAGENTS:
            # ritira nell'ordine di SUBAGENTS (deterministico) man mano che finiscono
            fut = next(f for f in future_of if future_of[f]["id"] == spec["id"])
            pending.discard(fut)
            _phase(log, emit, f"call sub-agent {spec['id']} ({spec['title']})")
            sid, fixes, dur, err = fut.result()
            if err:
                log.append(f"sub-agent {sid} fallito ({err})")
                continue
            _phase(log, emit, f"sub-agent {sid} done: {len(fixes)} fix in {dur:.0f}s")
            for fx in fixes:
                fx["_from"] = sid
            all_fixes.extend(fixes)

    # 6. merge: deduplica per (node, key), ultimo vince, max 80 per propose.
    # Normalizzazione TOLLERANTE: un fix allucinato viene scartato da solo,
    # gli altri passano (mai piu' 72 fix -> 0 ops come nel test Pay-Frame).
    # Polish di coerenza: via i bg ridondanti contenitore+figlio prima di
    # normalizzare, cosi' non doppiamo il verde della CTA.
    _phase(log, emit, f"padre merge {len(all_fixes)} fix → patch unica + check coerenza scopo")
    merged: dict[tuple, dict] = {}
    for fx in all_fixes:
        key = (str(fx.get("node", "")), str(fx.get("key", fx.get("path", ""))))
        merged[key] = fx
    fixes = list(merged.values())[:80]
    fixes, polish_notes = _coherence_polish(screen, fixes)
    for note in polish_notes:
        log.append(note)
        if emit is not None:
            try:
                emit(note)
            except Exception:
                pass
    from ..patcher import normalize_ops_tolerant
    ops, dropped = normalize_ops_tolerant(screen, fixes)
    if dropped:
        log.append(f"merge: {len(dropped)} fix scartati (nodo inesistente o key invalida)")
        for node, why in dropped[:5]:
            log.append(f"  scartato '{node}': {why}")
        if emit is not None:
            try:
                emit(f"merge: {len(dropped)} fix scartati, {len(ops)} ops valide")
            except Exception:
                pass

    return {"role": role_info, "sources": sources, "dropped": dropped,
            "blind": blind[:5] if isinstance(blind, list) else [],
            "fixes": fixes, "ops": ops, "log": log, "screen_id": sid}

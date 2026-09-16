"""Ricerca agentica per ruolo — l'iniziativa e' dell'AI, l'esecuzione e' nostra.

Il padre puo' chiedere fino a MAX_ROUNDS giri di web_search(query).
Il bridge esegue la ricerca (funzione iniettabile search_fn per i test),
verifica gli URL e li inietta nei prompt dei figli. Ritorna sempre anche
la sezione FONTI USATE con link reali: mai bibliografia allucinata.

search_fn(query) -> list[{title, url, snippet}]: da implementare con il
provider web reale o con stub nei test. Qui forniamo il protocollo +
validazione + cache + formattazione.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

MAX_ROUNDS = 3
MAX_SOURCES = 8
CACHE_TTL_S = 7 * 24 * 3600

URL_RE = re.compile(r"^https?://[^\s<>\"]+$")


def is_valid_url(url: str) -> bool:
    return isinstance(url, str) and bool(URL_RE.match(url.strip()))


def queries_for_role(role: str, platform: str | None = None) -> list[str]:
    """Query di fallback via codice (usate se il modello non chiama il tool
    o per il primo giro). Mirate per ruolo + piattaforma + linguaggio visuale."""
    base = role.replace("-", " ")
    plat = f" {platform}" if platform in ("ios", "android") else " mobile app"
    out = [
        f"{base} screen UX best practices 2026{plat}",
        f"{base} mobile UI empty loading error states 2026",
        f"{base} accessibility trust UX writing 2026",
    ]
    if platform == "ios":
        out.append(f"iOS 26 Liquid Glass {base} design HIG 2026")
    elif platform == "android":
        out.append(f"Material 3 expressive {base} design 2026")
    return out


def _cache_path(cache_dir: Path | None, role: str) -> Path | None:
    if cache_dir is None:
        return None
    safe = re.sub(r"[^a-z0-9-]+", "-", role.lower()).strip("-") or "role"
    return Path(cache_dir) / f"{safe}.research.json"


def load_cache(cache_dir: Path | None, role: str):
    import json as _json
    path = _cache_path(cache_dir, role)
    if path is None or not path.is_file():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) < CACHE_TTL_S:
            return data.get("sources", [])
    except Exception:
        return None
    return None


def save_cache(cache_dir: Path | None, role: str, sources: list) -> None:
    import json as _json
    path = _cache_path(cache_dir, role)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"ts": time.time(), "sources": sources},
                                    ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:
        pass


def verify_sources(raw: list, seen: set[str] | None = None) -> tuple[list, list]:
    """Filtra URL inventati/duplicati.     Ritorna (valide, scartate)."""
    if seen is None:
        seen = set()
    valid, dropped = [], []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "") or url)[:140]
        snippet = str(item.get("snippet", ""))[:500]
        if not is_valid_url(url) or url in seen:
            dropped.append(url or title)
            continue
        seen.add(url)
        valid.append({"title": title, "url": url, "snippet": snippet})
        if len(valid) >= MAX_SOURCES:
            break
    return valid, dropped


def research_block(sources: list) -> str:
    """Blocco prompt con le fonti: i figli devono citarle, non inventarle."""
    if not sources:
        return "RICERCA PER RUOLO: nessuna fonte esterna disponibile."
    lines = ["RICERCA PER RUOLO (fonti verificate dal bridge — cita SOLO questi URL, mai inventarne):"]
    for s in sources:
        lines.append(f"- [{s['title']}]({s['url']}) — {s['snippet']}")
    return "\n".join(lines)


def sources_markdown(sources: list) -> str:
    """Sezione FONTI USATE per la risposta finale al designer."""
    if not sources:
        return "Fonti: solo regolamento interno (nessuna fonte esterna)."
    return "\n".join(f"- [{s['title']}]({s['url']})" for s in sources)


def agentic_research(role: str, chat_fn, search_fn,
                     platform: str | None = None,
                     cache_dir: Path | None = None,
                     log: list | None = None) -> dict:
    """Giro agentic: il modello chiede query, noi eseguiamo e verifichiamo.

    chat_fn(messages) -> str (deve rispondere JSON {"queries": [...]});
    search_fn(query) -> list[{title, url, snippet}].
    Ritorna {"sources": [...], "dropped": [...], "rounds": n, "cached": bool}.
    """
    if log is None:
        log = []
    cached = load_cache(cache_dir, role)
    if cached:
        log.append(f"research '{role}': {len(cached)} fonti da cache")
        return {"sources": cached, "dropped": [], "rounds": 0, "cached": True}

    import json as _json
    seen: set[str] = set()
    all_valid: list = []
    all_dropped: list = []
    rounds = 0
    for rnd in range(1, MAX_ROUNDS + 1):
        rounds = rnd
        try:
            raw = chat_fn([
                {"role": "system",
                 "content": ("Sei il ricercatore UX di DesignChecker. Rispondi SOLO "
                             "con JSON {\"queries\": [\"...\", ...]}: max 3 query web "
                             "mirate per progettare al meglio questo ruolo screen. Niente testo fuori.")},
                {"role": "user",
                 "content": f"Ruolo screen: {role} (piattaforma: {platform or 'tutte'}). "
                            f"Fonti gia' raccolte: {len(all_valid)}. Proponi le prossime query."},
            ])
            from ..patcher import extract_json
            queries = extract_json(raw).get("queries", []) or []
        except Exception:
            queries = queries_for_role(role, platform) if rnd == 1 else []
        queries = [str(q)[:160] for q in queries if str(q).strip()][:3]
        if not queries:
            break
        log.append(f"research giro {rnd}: {len(queries)} query ({queries[0][:60]}…)")
        for q in queries:
            try:
                found = search_fn(q) or []
            except Exception as e:
                log.append(f"research: search fallita ({str(e)[:80]})")
                continue
            valid, dropped = verify_sources(found, seen)
            all_valid.extend(valid)
            all_dropped.extend(dropped)
            if len(all_valid) >= MAX_SOURCES:
                break
        if len(all_valid) >= MAX_SOURCES:
            break
    save_cache(cache_dir, role, all_valid)
    log.append(f"research '{role}': {len(all_valid)} fonti verificate, {len(all_dropped)} scartate")
    return {"sources": all_valid, "dropped": all_dropped,
            "rounds": rounds, "cached": False}

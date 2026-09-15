"""Ricerca web reale senza API key (stdlib only) per il bridge.

Usa l'endpoint HTML di DuckDuckGo: niente chiavi, niente dipendenze.
Pensata per l'orchestratore padre: search_fn(query) -> [{title, url, snippet}].
Mai eccezioni verso il chiamante: in caso di rete assente, blocco o
parsing fallito ritorna [] e il giro prosegue con le regole interne.
Timeout corto: la ricerca non deve mai bloccare la proposta.
"""
from __future__ import annotations

import html as _html
import re
import urllib.parse
import urllib.request

TIMEOUT = 8
MAX_RESULTS = 6
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DesignChecker/0.1"


def _fetch(query: str) -> str:
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "errors")


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_duckduckgo(page: str, max_results: int = MAX_RESULTS) -> list:
    """Estrae [{title, url, snippet}] dalla pagina HTML di DuckDuckGo.

    Gli href dei risultati passano dal redirect //duckduckgo.com/l/?uddg=<url>.
    Funzione pura e testabile senza rete."""
    out: list = []
    seen: set[str] = set()
    blocks = re.split(r'class="result__body"', page)[1:]
    for block in blocks:
        m = re.search(r'href="([^"]+)"', block)
        title_m = re.search(r'class="result__a"[^>]*>(.*?)</a>', block, re.S)
        snip_m = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.S)
        if not m or not title_m:
            continue
        href = _html.unescape(m.group(1))
        uddg = re.search(r"[?&]uddg=([^&]+)", href)
        url = urllib.parse.unquote(uddg.group(1)) if uddg else href
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append({
            "title": _clean(title_m.group(1))[:140] or url,
            "url": url[:500],
            "snippet": _clean(snip_m.group(1))[:500] if snip_m else "",
        })
        if len(out) >= max_results:
            break
    return out


def duckduckgo_search(query: str, max_results: int = MAX_RESULTS) -> list:
    """search_fn pronta per l'orchestratore. Mai eccezioni."""
    try:
        if not (query or "").strip():
            return []
        return parse_duckduckgo(_fetch(query.strip()[:160]), max_results)
    except Exception:
        return []

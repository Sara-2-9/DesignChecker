"""Client REST per la Figma API (D21) — solo lettura, stdlib urllib.

Note operative verificate (settembre 2026):
- PAT con scadenza massima 90 giorni (il CLI avvisa su 401/403).
- Scope consigliato: file_content:read.
- Rate limit severi su piano Starter: caching del tree e messaggi chiari su 429.
- La scrittura sul canvas NON passa da qui: solo plugin (D21/D22).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API_BASE = "https://api.figma.com/v1"


class FigmaAPIError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        hints = {
            401: "Token non valido. Rigenera il Personal Access Token su figma.com/settings",
            403: "Accesso negato o token scaduto (i PAT durano max 90 giorni). Rigenera il token.",
            404: "File non trovato: controlla l'URL del file Figma.",
            429: "Rate limit Figma raggiunto (piani Starter: ~10 req/min). Attendi un minuto e riprova.",
        }
        hint = hints.get(status, "")
        super().__init__(f"Figma API {status}: {detail}" + (f" — {hint}" if hint else ""))


class FigmaClient:
    def __init__(self, token: str):
        self.token = token

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(
            API_BASE + path,
            headers={"X-Figma-Token": self.token, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise FigmaAPIError(e.code, e.reason) from e
        except urllib.error.URLError as e:
            raise FigmaAPIError(0, f"Errore di rete: {e.reason}") from e

    def me(self) -> dict:
        """Verifica il token (usata da `dc link figma`)."""
        return self._get("/me")

    def file_tree(self, file_key: str, depth: int = 2) -> dict:
        """Albero del file. depth=2 basta per elencare pagine e frame top-level."""
        return self._get(f"/files/{file_key}?depth={depth}")

    def node(self, file_key: str, node_id: str) -> dict:
        """Un frame specifico con tutto il sotto-albero."""
        return self._get(f"/files/{file_key}/nodes?ids={node_id}")


def parse_file_key(url: str) -> str | None:
    """Estrae la file key da un URL Figma (/design/ o /file/)."""
    import re
    m = re.search(r"figma\.com/(?:design|file)/([A-Za-z0-9]+)", url)
    return m.group(1) if m else None

"""Classify ruolo/scopo dello screen — il padre capisce COSA sta guardando.

Niente financial-trust.yaml statico: il ruolo (profilo, wallet-home,
checkout, lista, form, onboarding...) e lo scopo si inferiscono da
meta + albero + contesto app. Output JSON strict per testabilita'.
"""
from __future__ import annotations

import json

from .vision import has_vision, user_content_with_image

CLASSIFY_SYSTEM = """Sei il classificatore di ruolo di DesignChecker.
Ricevi uno screen JSON (struttura) ed eventualmente il PNG reale del frame.
Rispondi SOLO con un oggetto JSON, niente testo fuori:
{"role": "<kebab-case, es. wallet-home, profile-screen, checkout-review, expense-list, login-form, onboarding-welcome>",
 "user_goal": "<cosa l'utente deve riuscire a fare in UNA frase>",
 "confidence": <0.0-1.0>,
 "signals": ["<max 4 segnali che motivano il ruolo: id/tipo/contenuto visti>"]}
Regole: ruolo generico 'generic-screen' solo se davvero ambiguo. Non inventare id."""


def build_classify_messages(screen: dict, context: str | None = None,
                            preview_base64: str | None = None) -> list:
    user_text = (
        "SCREEN JSON:\n" + json.dumps(screen, ensure_ascii=False) + "\n"
        + ("CONTESTO APP: " + context.strip() + "\n" if (context or "").strip() else "")
    )
    return [
        {"role": "system", "content": CLASSIFY_SYSTEM},
        {"role": "user",
         "content": user_content_with_image(user_text, preview_base64)},
    ]


def parse_classify(raw: str, fallback_id: str = "screen") -> dict:
    """Parsing tollerante: estrae il primo oggetto JSON, fallback generico."""
    from ..patcher import extract_json
    try:
        obj = extract_json(raw)
        if isinstance(obj, dict) and obj.get("role"):
            return {
                "role": str(obj["role"])[:64],
                "user_goal": str(obj.get("user_goal", ""))[:280],
                "confidence": float(obj.get("confidence", 0.5) or 0.5),
                "signals": list(obj.get("signals", []) or [])[:4],
            }
    except Exception:
        pass
    return {"role": "generic-screen",
            "user_goal": f"Completare il compito della schermata {fallback_id}",
            "confidence": 0.3, "signals": []}


def classify(screen: dict, chat_fn, context: str | None = None,
             preview_base64: str | None = None) -> dict:
    """Esegue la classify via LLM. chat_fn(messages) -> str."""
    messages = build_classify_messages(screen, context, preview_base64)
    raw = chat_fn(messages)
    sid = (screen.get("meta", {}) or {}).get("id", "screen")
    out = parse_classify(raw, sid)
    out["_raw_chars"] = len(raw)
    return out


def heuristic_role(screen: dict) -> dict:
    """Fallback deterministico senza LLM: euristiche su id/tipi/contenuto.
    Usato nei test e quando il provider non risponde."""
    root = screen.get("root", {}) or {}
    texts: list[str] = []

    def walk(n):
        if not isinstance(n, dict):
            return
        p = n.get("props", {}) or {}
        for k in ("content", "label", "title", "placeholder", "message"):
            v = p.get(k)
            if isinstance(v, str) and v.strip():
                texts.append(v.lower())
        for c in n.get("children", []) or []:
            walk(c)
    walk(root)
    blob = " ".join(texts)
    sid = str((screen.get("meta", {}) or {}).get("id", "")).lower()
    types: set[str] = set()

    def walk_t(n):
        if not isinstance(n, dict):
            return
        if n.get("type"):
            types.add(n["type"])
        for c in n.get("children", []) or []:
            walk_t(c)
    walk_t(root)

    def has(*words):
        return any(w in blob or w in sid for w in words)

    if has("profil", "avatar", "follower", "post miei", "mie foto"):
        role, goal = "profile-screen", "Mostrare foto profilo, info di base e contenuti propri"
    elif has("sald", "balance", "wallet", "fond", "ricaric", "pagament", "carta"):
        role, goal = "wallet-home", "Mostrare il saldo e permettere di aggiungere fondi"
    elif has("carrell", "checkout", "ordina", "paga ora", "spedizione"):
        role, goal = "checkout-review", "Rivedere l'ordine e confermare il pagamento"
    elif "List" in types and has("cerca", "search", "filtr"):
        role, goal = "search-list", "Cercare e selezionare un elemento dalla lista"
    elif "List" in types:
        role, goal = "expense-list", "Consultare la lista e agire su un elemento"
    elif "TextField" in types and has("accedi", "login", "password", "registr"):
        role, goal = "login-form", "Accedere all'account"
    elif "TextField" in types:
        role, goal = "input-form", "Compilare il modulo e inviarlo"
    else:
        role, goal = "generic-screen", "Completare il compito della schermata"
    return {"role": role, "user_goal": goal, "confidence": 0.6,
            "signals": sorted(types)[:4]}


__all__ = ["has_vision", "build_classify_messages", "parse_classify",
           "classify", "heuristic_role"]

"""Supporto vision PNG per il padre valutatore.

Il plugin esporta il frame come PNG 2x (come gia' fa per gli asset D34)
e lo allega a POST /propose come preview_base64. Qui si prepara il
contenuto multimodale per i provider che supportano image_url, con
fallback automatico a solo JSON.
"""
from __future__ import annotations


def has_vision(provider, model: str) -> bool:
    """Euristica: quasi tutti i cloud 2026 hanno vision; per i locali
    dipende dal modello caricato. Lista conservativa: in dubbio True
    per i cloud noti, False solo per modelli notoriamente text-only."""
    pid = getattr(provider, "pid", "")
    if pid in ("openai", "anthropic", "kimicode", "kimi", "huggingface"):
        return True
    if pid in ("ollama", "lmstudio", "custom"):
        name = (model or "").lower()
        text_only = ("embed", "whisper", "tts", "coder-v1", "llama2-7b-chat-q2")
        if any(t in name for t in text_only):
            return False
        # euristica: i modelli vision locali dichiarano vl/vision/llava/mistral-large
        return True
    return False


def user_content_with_image(text: str, preview_base64: str | None,
                            mime: str = "image/png"):
    """Contenuto user OpenAI-compatibile: testo + immagine se disponibile.
    Senza preview ritorna la stringa semplice (compatibile con tutti)."""
    if not preview_base64:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url",
         "image_url": {"url": f"data:{mime};base64,{preview_base64}"}},
    ]


def vision_note(has_png: bool) -> str:
    if has_png:
        return ("VERITA' VISIVA: hai anche il PNG reale del frame. "
                "Il JSON e' la struttura vera, il PNG e' cio' che l'utente "
                "vede davvero (ritmo, affollamento, pesi). Se discordano "
                "(es. bounds sballati), fidati del PNG e segnalalo.")
    return ("Nessuna preview PNG disponibile (modello senza vision o export "
            "non riuscito): valuta dal solo JSON + geometria layout.frame.")

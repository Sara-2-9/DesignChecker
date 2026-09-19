"""dck describe — scheda di stile da un PNG del frame.

Un vision-model descrive a parole lo stile del design: palette, tipografia,
ritmo, componenti, mood. La scheda e' un artefatto leggibile (brief per un
designer, documentazione del design system, DNA leggibile da allegare alle
proposte) — non tocca mai il JSON e non valida niente.

Limiti onesti (dichiarati anche nel prompt): i colori sono descritti a parole
("blu elettrico"), mai hex esatti; le misure sono qualitative ("CTA piccola,
tanto vuoto sotto"), mai pixel; i testi sotto i ~12px possono essere
fraintesi; stati e interazioni non si vedono da un fermo immagine.
"""
from __future__ import annotations

DESCRIBE_SYSTEM = """Sei un design critic che descrive interfacce mobile da un fermo immagine.
Scrivi in italiano, in Markdown, seguendo ESATTAMENTE queste sezioni:

## Sintesi
Due righe: che schermata sembra e che stile generale ha.

## Palette
Colori che vedi, descritti a parole con il loro ruolo (sfondo, superfici,
testi, accento/brand, stati). MAI codici hex: non puoi misurarli dal PNG,
descrivi ("nero", "grigio scuro caldo", "blu elettrico").

## Tipografia
Gerarchia che percepisci (titolo, corpo, caption), pesi apparenti, ritmo.
Se un testo e' troppo piccolo per leggerlo, scrivi "illeggibile" invece di
inventarlo.

## Layout e ritmo
Struttura (header/contenuto/CTA...), spaziature, respiro o affollamento,
allineamento, cosa guida l'occhio per primo.

## Componenti
Elementi riconoscibili (bottoni, stepper, toggle, card, liste, tab...)
e il loro stato apparente (attivo, selezionato, disabilitato...).

## Stile e mood
Tema (dark/light), linguaggio visivo (minimal, giocoso, istituzionale...),
angoli (vivi/arrotondati), materiali/ombre percepite, sensazione generale.

## Piattaforma
{platform_line}

Regole: concreto e specifico su QUESTO screen, niente frasi generiche da
manuale. Niente testo fuori dalle sezioni. Massimo 300 parole."""

PLATFORM_LINES = {
    "ios": "Valuta quanto il design parla il dialetto iOS (materiali, corner continui, sheet, SF Symbols, safe-area).",
    "android": "Valuta quanto il design parla Material 3 expressive (superfici tonali, FAB, forme, stati).",
    "custom": "Valuta la coerenza del linguaggio proprio, segnalando dove eredita da iOS o Android.",
    "both": "Segnala a quale piattaforma assomiglia di piu' e dove.",
}


def build_describe_messages(preview_base64: str, context: str | None = None,
                            platform: str | None = None,
                            mime: str = "image/png") -> list:
    """Messaggi per la scheda di stile. L'immagine e' obbligatoria:
    senza PNG non c'e' niente da descrivere."""
    from .evaluator.vision import user_content_with_image
    system = DESCRIBE_SYSTEM.format(
        platform_line=PLATFORM_LINES.get(platform or "", PLATFORM_LINES["both"]))
    user_text = ""
    if (context or "").strip():
        user_text += ("CONTESTO DELL'APP (descrizione dell'utente, usala per "
                      "capire le scelte):\n\"\"\"" + context.strip() + "\"\"\"\n\n")
    user_text += ("Descrivi questa schermata seguendo le sezioni richieste. "
                  "Se un dettaglio non si vede, scrivilo invece di inventarlo.")
    return [
        {"role": "system", "content": system},
        {"role": "user",
         "content": user_content_with_image(user_text, preview_base64, mime)},
    ]


def parse_describe(raw: str) -> str:
    """Pulisce la risposta: via fence markdown, via spazi bianchi."""
    import re as _re
    m = _re.search(r"```(?:markdown|md)?\s*(.*?)```", raw, _re.S)
    return (m.group(1) if m else raw).strip()


def describe_image(chat_fn, preview_base64: str,
                   context: str | None = None,
                   platform: str | None = None,
                   mime: str = "image/png") -> dict:
    """Esegue la descrizione. chat_fn(messages) -> str.
    Ritorna {"text": ...}. Non scrive mai file: quello lo fa la CLI."""
    messages = build_describe_messages(preview_base64, context, platform, mime)
    return {"text": parse_describe(chat_fn(messages))}

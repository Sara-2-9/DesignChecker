"""I 6 sottoagenti — ognuno una porzione fissa, output JSON strict.

Mappati sulla checklist UX/UI in 39 punti: gerarchia/carico cognitivo,
touch-affordance, feedback/stati, piattaforma nativa, psicologia/trust/
writing, accessibilita' robusta. Il contrasto numerico e i touch minimi
restano al validatore: i figli giudicano cio' che non e' misurabile.
"""
from __future__ import annotations

import json

SUBAGENTS = [
    {
        "id": "hierarchy-cognitive",
        "title": "Gerarchia e carico cognitivo",
        "brief": ("Test 2-3 secondi: cosa deve fare l'utente? Una sola primary "
                  "evidente? Recognition vs recall: deve ricordare, interpretare "
                  "icone, fare calcoli, capire cosa e' cliccabile e cosa succede dopo?"),
    },
    {
        "id": "touch-affordance",
        "title": "Touch, spacing, affordance",
        "brief": ("Area interattiva reale + distanza anti tap-accidentali, "
                  "prossimita' Gestalt dei gruppi, allineamento, affordance: "
                  "il bottone sembra premibile? il campo sembra editabile?"),
    },
    {
        "id": "feedback-states",
        "title": "Feedback, stati, errori",
        "brief": ("pressed/loading/success sempre visibili; empty con spiegazione "
                  "+ CTA; errori che spiegano cosa e' successo + soluzione; "
                  "prevenzione prima del messaggio; progressive disclosure."),
    },
    {
        "id": "platform-native",
        "title": "Piattaforma nativa",
        "brief": ("iOS: tab bottom max 5 per sezioni, sheet per task circoscritto, "
                  "SF Symbols, safe-area/Dynamic Island. Android: nav bar 3-5 su "
                  "compact, rail su large, FAB singolo, top app bar, gesture insets. "
                  "Custom: quadra col vincolo piu' stretto."),
    },
    {
        "id": "psych-trust-writing",
        "title": "Psicologia, trust, writing",
        "brief": ("Peak-End finale soddisfacente, Goal-Gradient solo su flussi reali, "
                  "Von Restorff un solo isolato per la CTA, Don't surprise me su "
                  "azioni economiche (review prima di pagare), Undo sempre possibile, "
                  "microcopy breve concreta orientata all'azione. Per denaro/dati: "
                  "costi e conseguenze espliciti, conferma irreversibili, stati "
                  "pending/success/failed, nessun dark pattern."),
    },
    {
        "id": "a11y-robustness",
        "title": "Accessibilita' e robustezza",
        "brief": ("Oltre i numeri del validatore: layout robusto a font grandi "
                  "(Dynamic Type/scaling 2x senza tagli), label VoiceOver/TalkBack "
                  "che descrivono l'azione, ordine di lettura, information scent "
                  "delle label, motion solo se spiega qualcosa."),
    },
]

SUB_SYSTEM = """Sei il sottoagente {sid} ({title}) di DesignChecker per il flusso Proponi nuovo design.
Ruolo screen: {role} — scopo: {goal}.
Valuta SOLO la tua porzione (brief sotto), mantenendo lo scopo che il designer vuole costruire.
BRIEF: {brief}
Rispondi SOLO con un array JSON di fix, niente testo fuori, max 12 fix:
[{{"node": "<id-nodo-visto>", "key": "style/color|style/background|props/label|layout/gap|a11y/label|...",
   "op": "replace|remove", "value": "...", "why": "<una riga>", "source_url": "<URL dalle fonti o regola id>"}}]
Usa SOLO token dalla lista TOKEN se cambi colori/spazi (mai inventare path). Identita' cromatica inviolabile: dark resta dark."""


def build_sub_messages(sid: str, screen: dict, involved: dict,
                       token_block: str, research_txt: str,
                       role: str, goal: str,
                       platform: str | None = None,
                       theme: str | None = None) -> list:
    spec = next(s for s in SUBAGENTS if s["id"] == sid)
    system = SUB_SYSTEM.format(sid=sid, title=spec["title"], role=role,
                               goal=goal, brief=spec["brief"])
    if platform:
        system += f"\nPIATTAFORMA: {platform}."
    if theme:
        system += f"\nTEMA: {theme}."
    user = (
        f"{research_txt}\n\n{token_block}\n\n"
        f"NODI (sottoinsieme rilevante):\n{json.dumps(involved, ensure_ascii=False, indent=1)}\n\n"
        f"SCREEN COMPLETO:\n{json.dumps(screen, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_sub_fixes(raw: str) -> list:
    """Parsing tollerante dei fix dei figli: lista di dict con node+key."""
    from ..patcher import extract_json
    try:
        obj = extract_json(raw)
    except Exception:
        return []
    if isinstance(obj, dict):
        obj = obj.get("fixes", obj.get("ops", []))
    if not isinstance(obj, list):
        return []
    out = []
    for op in obj:
        if not isinstance(op, dict):
            continue
        if "node" not in op or ("key" not in op and "path" not in op):
            continue
        op.setdefault("op", "replace")
        out.append(op)
        if len(out) >= 12:
            break
    return out

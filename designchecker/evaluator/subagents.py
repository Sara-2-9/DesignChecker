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
        "brief": ("iOS 26 Liquid Glass: materiali system (thin/regular/thick), "
                  "corner continui 16-22, chrome content-aware (Native Tabs/toolbar), "
                  "sheet con detent+grabber+scrim per task circoscritti (mai fullscreen "
                  "nero), SF Symbols gerarchici, safe-area/Dynamic Island. Android: "
                  "Material 3 expressive, nav bar 3-5 su compact, rail su large, FAB "
                  "singolo, top app bar, gesture insets. Evolvi il frame esistente "
                  "nel dialetto di piattaforma, non ridisegnare da zero."),
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
Valuta SOLO la tua porzione (brief sotto), mantenendo scopo E stile del designer.
BRIEF: {brief}
EVOLVI, NON RIDISENGNARE: conserva scheletro, brand hue e scala tipo; max 1 cambio
di materiale/superficie per proposta; se cambi un colore riusa un token gia' presente
nel DNA salvo brand; se allunghi un testo includi il co-fix layout/frame.
{style_block}
Rispondi SOLO con un array JSON di fix, niente testo fuori, max 5 fix MIRATI
(qualita' sopra quantita': niente riempitivi, solo problemi veri con id nodo visto):
[{{"node": "<id-nodo-visto>", "key": "style/color|style/background|props/label|layout/gap|a11y/label|...",
   "op": "replace|remove", "value": "...", "why": "<una riga>", "source_url": "<URL dalle fonti o regola id>"}}]
Usa SOLO token dalla lista TOKEN se cambi colori/spazi (mai inventare path). Identita' di brand: i colori in BRAND DELLO SCREEN restano come sono (mai mapparli su altri token, mai nuovi hex). Per gli altri colori, se nessun token va bene per un nodo, salta il nodo (niente fix e' meglio di un fix che peggiora). Identita' cromatica: dark resta dark."""


def _slim_node(n: dict) -> dict:
    """Versione compatta per i prompt: via meta rumorose (confidence, figma ids),
    asset lunghi e sotto-oggetti vuoti. Riduce ~40% i caratteri senza perdere id,
    tipi, testi, layout, stili e a11y che servono ai fix."""
    if not isinstance(n, dict):
        return n
    out: dict = {"id": n.get("id"), "type": n.get("type")}
    for k in ("props", "layout", "style", "a11y", "semantics"):
        v = n.get(k)
        if v:
            if k == "props" and isinstance(v, dict):
                v = {kk: vv for kk, vv in v.items()
                     if kk != "asset" or (isinstance(vv, str) and len(vv) < 120)}
            out[k] = v
    kids = n.get("children") or []
    if kids:
        out["children"] = [_slim_node(c) for c in kids]
    return out


def build_sub_messages(sid: str, screen: dict, involved: dict,
                       token_block: str, research_txt: str,
                       role: str, goal: str,
                       platform: str | None = None,
                       theme: str | None = None,
                       style_block: str | None = None,
                       blind_txt: str | None = None) -> list:
    spec = next(s for s in SUBAGENTS if s["id"] == sid)
    system = SUB_SYSTEM.format(sid=sid, title=spec["title"], role=role,
                               goal=goal, brief=spec["brief"],
                               style_block=style_block or "")
    if platform:
        system += f"\nPIATTAFORMA: {platform}."
    if theme:
        system += f"\nTEMA: {theme}."
    slim = _slim_node(screen.get("root", {}) or {})
    parts = [research_txt, token_block]
    if blind_txt:
        parts.append(blind_txt)
    parts.append("SCREEN (compatto: id/tipi/testi/layout/stili, meta rumorose rimosse):\n"
                 + json.dumps(slim, ensure_ascii=False))
    user = "\n\n".join(p for p in parts if p)
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
        if len(out) >= 6:  # prompt ne chiede 5, margine 1 per tolleranza
            break
    return out

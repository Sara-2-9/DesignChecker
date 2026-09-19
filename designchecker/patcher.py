"""Patch JSON indirizzate per id di nodo + gate del validatore (D44).

L'LLM propone operazioni {op, node, key, value}; qui vengono tradotte in
JSON Pointer reali (D41) e il validatore deterministico decide (safety +
qualita' da conteggio o copertura blind).

Invariante di sicurezza: l'output del modello NON tocca mai il JSON senza
passare dal validatore.

L'applicatore RFC 6902 qui implementato copre add/remove/replace con
JSON Pointer (RFC 6901), inclusi ~0/~1 e "-" per appendere agli array.
"""
from __future__ import annotations

import copy
import json
import re

MAX_OPS = 40
MAX_OPS_PROPOSE = 80  # redesign (padre+figli): piu' operazioni, stesso gate


class PatchError(Exception):
    pass


# ── JSON Pointer (RFC 6901) ──────────────────────────────────────────

def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _split(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise PatchError(f"path non valido (deve iniziare con '/'): {pointer!r}")
    return [_unescape(t) for t in pointer.split("/")[1:]]


def _parent_of(doc, tokens: list, create: bool = False):
    node = doc
    for t in tokens[:-1]:
        if isinstance(node, list):
            if not t.isdigit() or int(t) >= len(node):
                raise PatchError(f"indice array non valido: {t!r}")
            node = node[int(t)]
        elif isinstance(node, dict):
            if t not in node:
                # upsert (D41): 'add' crea i dizionari intermedi mancanti
                # (es. style/background su un nodo senza 'style')
                if create:
                    node[t] = {}
                else:
                    raise PatchError(f"chiave mancante: {t!r}")
            node = node[t]
        else:
            raise PatchError(f"il path attraversa un valore scalare: {t!r}")
    return node, tokens[-1]


def apply_patch(doc: dict, ops: list, max_ops: int = MAX_OPS) -> dict:
    """Applica ops (add/remove/replace) a una COPIA di doc. Ritorna il nuovo doc."""
    out = copy.deepcopy(doc)
    if not isinstance(ops, list):
        raise PatchError("la patch deve essere un array JSON")
    if len(ops) > max_ops:
        raise PatchError(f"troppe operazioni ({len(ops)} > {max_ops})")
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op or "path" not in op:
            raise PatchError(f"operazione {i} malformata: {op!r}")
        kind, path = op["op"], op["path"]
        tokens = _split(path)
        parent, last = _parent_of(out, tokens, create=(kind == "add"))
        if kind == "remove":
            if isinstance(parent, list):
                if not last.isdigit() or int(last) >= len(parent):
                    raise PatchError(f"remove: indice non valido {path}")
                parent.pop(int(last))
            elif isinstance(parent, dict) and last in parent:
                del parent[last]
            else:
                raise PatchError(f"remove: path inesistente {path}")
        elif kind in ("add", "replace"):
            if "value" not in op:
                raise PatchError(f"{kind}: manca 'value' in {path}")
            if isinstance(parent, list):
                if last == "-":
                    if kind == "replace":
                        raise PatchError("replace su '-' non valido")
                    parent.append(op["value"])
                elif last.isdigit() and int(last) < len(parent):
                    if kind == "add":
                        parent.insert(int(last), op["value"])
                    else:
                        parent[int(last)] = op["value"]
                elif kind == "add" and last.isdigit() and int(last) == len(parent):
                    parent.append(op["value"])
                else:
                    raise PatchError(f"{kind}: indice non valido {path}")
            elif isinstance(parent, dict):
                if kind == "replace" and last not in parent:
                    raise PatchError(f"replace: chiave inesistente {path}")
                parent[last] = op["value"]
            else:
                raise PatchError(f"{kind}: il parent non e' un contenitore {path}")
        else:
            raise PatchError(f"operazione non supportata: {kind!r} (solo add/remove/replace)")
    return out


# ── Patch indirizzata per id di nodo (D41) ───────────────────────────

def _node_paths(screen: dict) -> dict[str, list[str]]:
    """Mappa id nodo -> lista di JSON Pointer reali nell'albero.

    Gli export storici (pre-dedup) possono contenere ID duplicati
    ('bg' x2, 'rectangle-253' x4): un fix per node-id viene espanso a
    TUTTI i gemelli, altrimenti meta' degli errori resta aperta."""
    paths: dict[str, list[str]] = {}

    def walk(node, path):
        if not isinstance(node, dict):
            return
        if node.get("id"):
            paths.setdefault(node["id"], []).append(path)
        for i, ch in enumerate(node.get("children", []) or []):
            walk(ch, f"{path}/children/{i}")

    root = screen.get("root")
    if isinstance(root, dict):
        walk(root, "/root")
    return paths


def _coerce_value(key: str, value):
    """Normalizza i tipi: min_height/height/size numerici come int.

    Il modello risponde spesso "50" (stringa): il validatore/codegen
    leggono numeri, la stringa rendeva il fix inefficace ma valido."""
    last = str(key or "").strip("/").split("/")[-1]
    if last in ("min_height", "height", "size") and isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (ValueError, AttributeError):
            return value
    return value


def normalize_ops(screen: dict, ops) -> list:
    """Traduce la patch semplificata del modello in JSON Pointer reali (D41).

    Il modello indirizza per ID di nodo, non per indici numerici (che
    sbagliava regolarmente: 'chiave inesistente /root/children/0/...'):
      {"op": "replace", "node": "balance-value", "key": "style/color",
       "value": "{color.text-primary}"}

    Regole:
    - "node" + "key" -> path reale calcolato QUI (deterministico);
    - replace/add su chiave di nodo diventano upsert (RFC 'add': crea la
      chiave se manca — sparisce la classe d'errore 'chiave inesistente');
    - ID duplicati (export storici) -> espansi a tutti i gemelli;
    - le operazioni con "path" (RFC 6902 classico) passano invariate.
    """
    if not isinstance(ops, list):
        return ops
    paths: dict[str, list[str]] | None = None
    out: list[dict] = []
    for i, op in enumerate(ops):
        if isinstance(op, dict) and "node" in op and "path" not in op:
            if paths is None:
                paths = _node_paths(screen)
            node_id = str(op.get("node", ""))
            bases = paths.get(node_id)
            if not bases:
                raise PatchError(
                    f"operazione {i}: nodo '{node_id}' non trovato nello screen "
                    f"(usa gli id dei NODI COINVOLTI)")
            key = str(op.get("key", "")).strip("/")
            if not key:
                raise PatchError(f"operazione {i}: 'key' mancante")
            suffix = "/".join(
                t.replace("~", "~0").replace("/", "~1") for t in key.split("/"))
            kind = op.get("op", "replace")
            value = _coerce_value(key, op.get("value"))
            for base in bases:
                translated = {"op": "remove" if kind == "remove" else "add",
                              "path": base + "/" + suffix}
                if kind != "remove":
                    translated["value"] = value
                out.append(translated)
        else:
            out.append(op)
    return out


# ── Estrazione JSON dalla risposta del modello ───────────────────────

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str):
    """Estrae il primo valore JSON dalla risposta (tollera fence markdown
    e testo attorno). Solleva PatchError se non trova JSON valido."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)] or [text]
    for cand in candidates:
        cand = cand.strip()
        for start in (i for i, ch in enumerate(cand) if ch in "[{"):
            try:
                obj, _ = json.JSONDecoder().raw_decode(cand[start:])
                return obj
            except json.JSONDecodeError:
                continue
    raise PatchError("nessun JSON valido nella risposta del modello")


# ── Propose gate (flusso padre+figli): safety + qualita' ──

# Chiavi scrivibili dai fix AI (schema screen JSON v0.1). Tutto il resto
# viene scartato con log invece di avvelenare la patch (bug Pay-Frame #2:
# layout/height, style/background-pressed, props/enabled... inventate dal
# modello e mai lette da validatore/codegen).
# layout/frame ammesso: senza, un copy piu' lungo (CTA) tronca di sicuro
# perche' nessuna op puo' allargare il bottone (bug Pay-Frame "Add $15 to wal").
_ALLOWED_KEYS = {
    "style": {"color", "background", "radius", "foreground"},
    "props": {"label", "action", "min_height", "height", "size",
              "placeholder", "content", "variant", "confirm", "tabs",
              "asset", "route", "name", "message", "action_label"},
    "layout": {"direction", "gap", "padding", "sizing", "align",
               "safe_area", "position", "offset", "frame"},
    "a11y": {"label", "role"},
    "semantics": {"primary_action", "destructive", "navigation_role"},
    "meta": {"exceptions"},
}


def _key_allowed(key: str) -> bool:
    parts = str(key or "").strip("/").split("/")
    return (len(parts) >= 2 and parts[0] in _ALLOWED_KEYS
            and parts[1] in _ALLOWED_KEYS[parts[0]])

def _expand_frame_for_longer_copy(screen: dict, fixes: list) -> list:
    """Co-fix automatico: se un fix allunga il testo, allarga il frame.

    Bug Pay-Frame: 'Add 15 $' -> 'Add $15 to wallet' con frame w:70 fisso
    = 'Add $15 to wal' troncato. Il modello dimentica il co-fix; lo facciamo
    noi in modo deterministico (stima 8px/char + 16px padding)."""
    idx: dict[str, dict] = {}

    def walk(n):
        if not isinstance(n, dict):
            return
        if n.get("id"):
            idx.setdefault(n["id"], n)
        for c in n.get("children", []) or []:
            walk(c)
    walk(screen.get("root", {}) or {})
    extra: list = []
    for op in fixes:
        if not isinstance(op, dict) or op.get("key") not in (
                "props/content", "props/label"):
            continue
        node = idx.get(str(op.get("node", "")))
        new_text = str(op.get("value", ""))
        if not node or not new_text:
            continue
        old_text = str((node.get("props", {}) or {}).get(
            "content" if op["key"] == "props/content" else "label", ""))
        if len(new_text) <= len(old_text):
            continue
        frame = (node.get("layout", {}) or {}).get("frame") or {}
        w = frame.get("w")
        if not isinstance(w, (int, float)) or w <= 0:
            continue
        need = len(new_text) * 8 + 16
        if need > w:
            nf = dict(frame)
            nf["w"] = int(need)
            extra.append({"op": "replace", "node": node["id"],
                          "key": "layout/frame", "value": nf})
    return extra


def normalize_ops_tolerant(screen: dict, ops) -> tuple[list, list]:
    """Normalizza un fix alla volta. Ritorna (ops_validi, scartati).

    Un singolo fix allucinato (nodo inesistente, key vuota) non uccide piu'
    gli altri: bug Pay-Frame dove 72 fix diventavano 0 ops. Ogni scarto e'
    motivato come (nodo, motivo) per il log."""
    if not isinstance(ops, list):
        return [], [("?", "la patch non e' un array JSON")]
    good: list = []
    bad: list[tuple[str, str]] = []
    # co-fix copy+frame prima della normalizzazione (chiavi node-based)
    try:
        ops = list(ops) + _expand_frame_for_longer_copy(screen, ops)
    except Exception:
        pass
    for op in ops:
        if isinstance(op, dict) and "node" in op and "path" not in op:
            key = str(op.get("key", ""))
            if not _key_allowed(key):
                bad.append((str(op.get("node", "?")),
                            f"key fuori schema (ignorata da validatore/codegen): {key}"))
                continue
        try:
            good.extend(normalize_ops(screen, [op]))
        except PatchError as e:
            node = "?"
            if isinstance(op, dict):
                node = str(op.get("node", op.get("path", "?")))
            bad.append((node, str(e)))
    return good, bad


def apply_patch_tolerant(doc: dict, ops: list,
                         max_ops: int = MAX_OPS_PROPOSE) -> tuple[dict, list, list]:
    """Applica le ops una alla volta. Ritorna (patched, applicate, scartate).

    Una op che fallisce (es. remove su path inesistente) viene scartata da
    sola con motivo, le altre passano. Bug Pay-Frame #2: un remove su
    props/enabled inesistente bocciava l'intera patch da 25 ops."""
    out = copy.deepcopy(doc)
    applied: list = []
    dropped: list = []
    for op in ops:
        try:
            out = apply_patch(out, [op], max_ops=max_ops)
            applied.append(op)
        except PatchError as e:
            msg = str(e)
            if (isinstance(op, dict) and op.get("op") == "remove"
                    and ("inesistente" in msg or "mancante" in msg)):
                dropped.append({"op": op, "reason": "noop: chiave gia' assente"})
            else:
                dropped.append({"op": op, "reason": msg})
    return out, applied, dropped

BLIND_COVER_MIN = 2  # priorita' della diagnosi coperte per la qualita' "padre"


def _blind_coverage(screen: dict, applied: list, blind) -> tuple[int, list, list]:
    """Quante priorita' della diagnosi cieca toccano le ops applicate.

    Il padre ha visto il PNG, il contatore no: la copertura delle sue
    priorita' e' la base qualita' alternativa al conteggio (D44).
    Match per sottoalbero: un fix su un discendente o antenato del nodo
    cieco conta (es. cieco 'custom' coperto da fix su 'plus-button').
    Ritorna (n_coperte, [nodi coperti], [nodi ciechi])."""
    ids = [b.get("node") for b in (blind or [])
           if isinstance(b, dict) and b.get("node")][:5]
    ids = [i for i in ids if isinstance(i, str)]
    if not ids or not applied:
        return 0, [], ids
    children_of: dict[str, list] = {}
    parent_of: dict[str, str] = {}

    def walk(n, parent):
        if not isinstance(n, dict):
            return
        nid = n.get("id")
        if nid:
            children_of.setdefault(nid, [])
            if isinstance(parent, dict) and parent.get("id"):
                parent_of[nid] = parent["id"]
                children_of.setdefault(parent["id"], []).append(nid)
        for c in n.get("children", []) or []:
            walk(c, n)
    walk(screen.get("root", {}) or {}, None)

    def descendants(nid: str) -> set:
        out, stack = set(), [nid]
        while stack:
            cur = stack.pop()
            if cur in out:
                continue
            out.add(cur)
            stack.extend(children_of.get(cur, []))
        return out

    def ancestors(nid: str) -> set:
        out = set()
        cur = parent_of.get(nid)
        while cur and cur not in out:
            out.add(cur)
            cur = parent_of.get(cur)
        return out

    path_to_id: dict[str, str] = {}
    for nid, ps in _node_paths(screen).items():
        for p in ps:
            path_to_id[p] = nid

    def op_node(op_path: str):
        best = None
        for p, nid in path_to_id.items():
            if op_path == p or op_path.startswith(p + "/"):
                if best is None or len(p) > len(best[0]):
                    best = (p, nid)
        return best[1] if best else None

    covered = []
    for b in ids:
        related = descendants(b) | ancestors(b)
        for op in applied:
            if not isinstance(op, dict):
                continue
            nid = op_node(str(op.get("path", "")))
            if nid is not None and (nid == b or nid in related
                                    or b in descendants(nid)):
                covered.append(b)
                break
    return len(covered), covered, ids


def _culprit_ops(screen: dict, applied: list, before_keys: set,
                 validate_fn) -> tuple[list, list]:
    """Trova le ops che da sole introducono nuovi errori.

    Il validatore e' deterministico e veloce (ms): testare ogni op da sola
    sullo screen originale costa poco e individua il colpevole preciso
    (es. hex hard-coded scritto su un nodo che aveva gia' un token).
    Le ops non attribuibili da sole restano tenute: la rete finale resta
    il controllo sui new_keys dell'insieme."""
    culprits: list = []
    kept: list = []
    for op in applied:
        try:
            single = apply_patch(screen, [op])
        except PatchError:
            kept.append(op)
            continue
        try:
            errs, _ = validate_fn(single)
        except Exception:
            kept.append(op)
            continue
        if {(f.rule_id, f.node_id) for f in errs} - before_keys:
            culprits.append(op)
        else:
            kept.append(op)
    return culprits, kept


def gate_propose(screen: dict, ops: list, validate_fn, blind=None) -> dict:
    """Applica ops (gia' normalizzate per node-id) e decide col validatore.

    Due giudizi separati (D44):
    - SAFETY deterministica e bloccante: la patch si applica, non introduce
      NUOVI errori (coppie rule/node mai viste prima), non aumenta warning,
      non peggiora il conteggio. Il conteggio da solo premiava patch che
      fissano 4 hardcoded e ne rompono 1 di contrasto.
    - QUALITY: basta UNA delle due basi —
      (a) conteggio: errori ridotti di almeno MIN_FIXES, oppure
      (b) padre: le ops coprono almeno 2 delle 5 priorita' della diagnosi
      cieca (il padre ha visto il PNG, il contatore no). La copertura e'
      per sottoalbero: un fix su un discendente/antenato del nodo cieco conta.
    Le ops colpevoli di regressione vengono scartate da sole (gate
    tollerante): 2 hex cattivi non uccidono piu' 10 fix buoni.
    Usa MAX_OPS_PROPOSE (redesign) invece di MAX_OPS (fix puntuale).
    Ritorna {"applied", "screen", "ops", "before", "after", "detail",
             "quality", "coverage"}.
    """
    errors, warnings = validate_fn(screen)
    before = (len(errors), len(warnings))
    before_keys = {(f.rule_id, f.node_id) for f in errors}
    if not isinstance(ops, list):
        return {"applied": False, "screen": screen, "ops": [],
                "before": before, "after": before, "dropped": [],
                "detail": "la patch non e' un array JSON",
                "quality": "", "coverage": []}
    if len(ops) > MAX_OPS_PROPOSE:
        return {"applied": False, "screen": screen, "ops": [],
                "before": before, "after": before, "dropped": [],
                "detail": f"troppe operazioni ({len(ops)} > {MAX_OPS_PROPOSE})",
                "quality": "", "coverage": []}
    patched, applied, dropped = apply_patch_tolerant(screen, ops)
    n_errors, n_warnings = validate_fn(patched)
    after = (len(n_errors), len(n_warnings))
    after_keys = {(f.rule_id, f.node_id) for f in n_errors}
    new_keys = sorted(after_keys - before_keys)
    if new_keys:
        # Gate tollerante (stessa filosofia di normalize/apply): invece di
        # buttare l'intera patch per 1-2 ops cattive, scarta solo le colpevoli
        # e rivaluta il resto. Pay-Frame: 2 hex su nodi gia' tokenizzati
        # uccidevano 10+ fix buoni (23->22 RIFIUTATA invece di ~23->20).
        culprits, kept = _culprit_ops(screen, applied, before_keys, validate_fn)
        if culprits and kept:
            for c in culprits:
                dropped.append({"op": c,
                                "reason": "gate: introduce nuovi errori, scartata"})
            patched, applied, dropped2 = apply_patch_tolerant(screen, kept)
            dropped.extend(dropped2)
            n_errors, n_warnings = validate_fn(patched)
            after = (len(n_errors), len(n_warnings))
            after_keys = {(f.rule_id, f.node_id) for f in n_errors}
            new_keys = sorted(after_keys - before_keys)
    if new_keys:
        detail = "regressione: " + "; ".join(f"{r} su '{n}'" for r, n in new_keys[:5])
        return {"applied": False, "screen": screen, "ops": [],
                "before": before, "after": after, "dropped": dropped,
                "detail": detail, "quality": "", "coverage": []}
    # safety: mai peggiorare (il confronto per chiavi non copre il caso di
    # due finding stessa rule/node su path diversi)
    if after[0] > before[0] or after[1] > before[1]:
        detail = ("peggiorata: "
                  + "; ".join(f"{f.rule_id} su '{f.node_id}'" for f in n_errors[:5]))
        return {"applied": False, "screen": screen, "ops": [],
                "before": before, "after": after, "dropped": dropped,
                "detail": detail, "quality": "", "coverage": []}
    fixed = before[0] - after[0]
    min_fixes = 2 if before[0] >= 10 else 1
    count_ok = after[0] < before[0] and fixed >= min_fixes
    cov_n, covered, blind_ids = _blind_coverage(screen, applied, blind)
    blind_ok = bool(blind_ids) and cov_n >= min(BLIND_COVER_MIN, len(blind_ids))
    if count_ok:
        return {"applied": True, "screen": patched, "ops": applied,
                "before": before, "after": after, "dropped": dropped,
                "detail": "", "quality": f"conteggio ({fixed} fix)",
                "coverage": covered}
    if blind_ok:
        return {"applied": True, "screen": patched, "ops": applied,
                "before": before, "after": after, "dropped": dropped,
                "detail": "",
                "quality": (f"padre ({cov_n}/{len(blind_ids)} priorita': "
                            f"{', '.join(covered)})"),
                "coverage": covered}
    detail = "; ".join(f"{f.rule_id} su '{f.node_id}'" for f in n_errors[:5])
    if blind_ids:
        detail += f" — copertura padre {cov_n}/{len(blind_ids)} (< {min(BLIND_COVER_MIN, len(blind_ids))})"
    elif fixed < min_fixes and after[0] < before[0]:
        detail = f"miglioramento insufficiente ({fixed} < {min_fixes} min): {detail}"
    return {"applied": False, "screen": screen, "ops": [],
            "before": before, "after": after, "dropped": dropped,
            "detail": detail, "quality": "", "coverage": covered}

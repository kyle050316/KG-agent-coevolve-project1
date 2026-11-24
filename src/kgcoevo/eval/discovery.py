"""Scoring of gap reports (Exp 1 Mode B) against the defect log.

Every claimed gap is put into exactly one category:

* ``hit``          matches an injected defect (key and true G* value)
* ``located_only`` names the key of an injected defect but the value is wrong
* ``false_gap``    the claimed fact is already in Gw
* ``natural``      not injected, but the cited passage states the claimed value -> a real
                   gap/conflict of the original KB (excluded from precision; human-audited)
* ``unsupported``  none of the above (hallucinated or unverifiable claim)

Precision = hit / (hit + located_only + false_gap + unsupported).
Recall (end-to-end) = detected defects / all defects of the processed entities.
Recall (exposed) = detected / defects whose gold passage was shown to the model.
Strict (FEVER-style) = detected with the correct label and a cited gold passage.
"""

from __future__ import annotations

import difflib

from kgcoevo.docs.passages import Passage
from kgcoevo.eval.compare import answers_equal, mentions
from kgcoevo.kb.store import KBStore
from kgcoevo.kb.values import surface_forms

PRECISION_CATS = ("hit", "located_only", "false_gap", "unsupported")


class KeyResolver:
    def __init__(self, store: KBStore):
        self.rel_keys = {f.key for f in store.facts.values() if f.kind == "rel"}
        self.all_keys = sorted({f.key for f in store.facts.values()})
        self.lower = {k.lower(): k for k in self.all_keys}

    def __call__(self, key: str | None) -> str | None:
        if not key:
            return None
        k = key.strip().lower()
        if k in self.lower:
            return self.lower[k]
        m = difflib.get_close_matches(k, list(self.lower), n=1, cutoff=0.85)
        return self.lower[m[0]] if m else None


def resolve_entities(store: KBStore, name: str | None) -> list[str]:
    if not name:
        return []
    ids = store.name_to_ids.get(name.strip(), [])
    if ids:
        return list(ids)
    low = name.strip().lower()
    return [e for n, es in store.name_to_ids.items() if n.lower() == low for e in es]


def _value_matches(store: KBStore, kind: str, claimed: str, true_vstr: str) -> bool:
    if kind == "rel":
        return true_vstr in resolve_entities(store, claimed)
    return answers_equal(claimed, true_vstr)


def _passage_states(p: Passage | None, claimed: str, store: KBStore, is_rel: bool) -> bool:
    if p is None or not claimed:
        return False
    if is_rel:
        return mentions(p.text, claimed) or any(store.name(q) == claimed for _, _, q in p.anchors if q in store.entities)
    forms = [claimed]
    try:
        forms += surface_forms({"type": "date", "value": claimed})
    except Exception:  # noqa: BLE001 - not a date
        pass
    return any(mentions(p.text, f) for f in forms)


def score_report(gs: KBStore, gw: KBStore, resolver: KeyResolver, entity: str, gaps: list[dict],
                 defects: list[dict], shown_pids: set[str], passages: dict[str, Passage]) -> dict:
    """Score one entity's gap report. ``defects`` are defect dicts whose subject is ``entity``."""
    claims = []
    detected: dict[str, dict] = {}
    for g in gaps if isinstance(gaps, list) else []:
        if not isinstance(g, dict):
            continue
        key = resolver(str(g.get("key", "")))
        claimed = str(g.get("claimed_value", "") or "").strip()
        label = str(g.get("label", "")).strip().lower()
        cited = str(g.get("evidence_id", "") or "")
        rec = {"key_raw": g.get("key"), "key": key, "claimed_value": claimed, "label": label, "evidence_id": cited}
        if key is None or not claimed:
            claims.append({**rec, "category": "unsupported", "reason": "unresolved key or empty value"})
            continue
        is_rel = key in resolver.rel_keys
        kind = "rel" if is_rel else "attr"
        hit = None
        located = False
        for d in defects:
            if d["key"] != key:
                continue
            located = True
            dkind = "rel" if d["kind"] == "rel" else "attr"
            if _value_matches(gs, dkind, claimed, d["before"]):
                hit = d
                break
        if hit is not None:
            want = {"missing"} if hit["op"] == "delete" else ({"conflict"} if hit["functional"] else {"conflict", "missing"})
            label_ok = label in want
            strict = label_ok and cited in set(hit.get("passage_ids", []))
            prev = detected.get(hit["defect_id"])
            if prev is None or (strict and not prev["strict"]):
                detected[hit["defect_id"]] = {"label_ok": label_ok, "strict": strict}
            claims.append({**rec, "category": "hit", "defect_id": hit["defect_id"], "label_ok": label_ok, "strict": strict})
            continue
        if located:
            claims.append({**rec, "category": "located_only"})
            continue
        in_gw = any(_value_matches(gw, kind, claimed, f.vstr) for f in gw.facts_of(entity, (kind,)) if f.key == key)
        if in_gw:
            claims.append({**rec, "category": "false_gap"})
        elif cited in shown_pids and _passage_states(passages.get(cited), claimed, gs, is_rel):
            claims.append({**rec, "category": "natural"})
        else:
            claims.append({**rec, "category": "unsupported"})
    per_defect = []
    for d in defects:
        det = detected.get(d["defect_id"])
        per_defect.append({
            "defect_id": d["defect_id"], "op": d["op"], "subtype": d["subtype"], "hardness": d["hardness"],
            "functional": d["functional"], "exposed": bool(set(d.get("passage_ids", [])) & shown_pids),
            "detected": det is not None, "label_ok": bool(det and det["label_ok"]), "strict": bool(det and det["strict"]),
        })
    return {"entity": entity, "claims": claims, "defects": per_defect}

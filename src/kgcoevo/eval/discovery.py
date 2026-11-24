"""Scoring of gap reports (Exp 1 Mode B) against the defect log.

Every claimed gap is either correct or an error:

* ``hit``           matches an injected defect: same key and the true (G*) value
* ``located_only``  an error that names the key of an injected defect but gives a wrong value that is
                    not already stored in Gw (found the place, misread the value)
* ``other``         every other error: the fact is already in Gw, is not in G*, cannot be resolved,
                    or is a real gap of the original KB (counted as an error: no human audit)

Precision = hit / all claims.
Recall = detected defects / all defects of the processed entities.
Label accuracy = detected defects with the right label (missing / conflict) / detected defects.
"""

from __future__ import annotations

import difflib

from kgcoevo.eval.compare import answers_equal
from kgcoevo.kb.store import KBStore

CATEGORIES = ("hit", "located_only", "other")


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


def score_report(gs: KBStore, gw: KBStore, resolver: KeyResolver, entity: str, gaps: list[dict],
                 defects: list[dict]) -> dict:
    """Score one entity's gap report. ``defects`` are defect dicts whose subject is ``entity``."""
    claims = []
    detected: dict[str, bool] = {}  # defect_id -> label ok (True if any hit had the right label)
    for g in gaps if isinstance(gaps, list) else []:
        if not isinstance(g, dict):
            continue
        key = resolver(str(g.get("key", "")))
        claimed = str(g.get("claimed_value", "") or "").strip()
        label = str(g.get("label", "")).strip().lower()
        rec = {"key_raw": g.get("key"), "key": key, "claimed_value": claimed, "label": label,
               "evidence_id": str(g.get("evidence_id", "") or "")}
        if key is None or not claimed:
            claims.append({**rec, "category": "other"})
            continue
        hit, located = None, False
        for d in defects:
            if d["key"] != key:
                continue
            located = True
            if _value_matches(gs, "rel" if d["kind"] == "rel" else "attr", claimed, d["before"]):
                hit = d
                break
        if hit is None:
            kind = "rel" if key in resolver.rel_keys else "attr"
            in_gw = any(_value_matches(gw, kind, claimed, f.vstr) for f in gw.facts_of(entity, (kind,)) if f.key == key)
            claims.append({**rec, "category": "located_only" if located and not in_gw else "other"})
            continue
        want = {"missing"} if hit["op"] == "delete" else ({"conflict"} if hit["functional"] else {"conflict", "missing"})
        label_ok = label in want
        detected[hit["defect_id"]] = detected.get(hit["defect_id"], False) or label_ok
        claims.append({**rec, "category": "hit", "defect_id": hit["defect_id"], "label_ok": label_ok})
    per_defect = [{"defect_id": d["defect_id"], "op": d["op"], "subtype": d["subtype"], "hardness": d["hardness"],
                   "functional": d["functional"], "detected": d["defect_id"] in detected,
                   "label_ok": detected.get(d["defect_id"], False)} for d in defects]
    return {"entity": entity, "claims": claims, "defects": per_defect}

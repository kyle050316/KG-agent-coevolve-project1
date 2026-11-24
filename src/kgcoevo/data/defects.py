"""Controlled defect injection: G* (reference) -> Gw (working KG) + defect log.

Protocol (following KG error-detection practice, e.g. CKRL/CAGED, and IKGQA in Generate-on-Graph):
* defects are sampled from S (document-supported facts) within a scope of entities, at a given
  rate;
* deletions and corruptions are split 1:1 by default;
* corruptions are either "similar" (type-consistent, plausible: same-concept entity that already
  appears as an object of the same relation; nearby dates/years; quantities within +-10-30%;
  another observed value of the same key) or "random" (any entity of the same concept / any
  value) -- CCA (Liu et al., AAAI 2024) shows detectors fail mostly on the former;
* every edit keeps the forward and backward copies of a relation consistent;
* a self-check verifies on the engine that each defect is visible in Gw and absent in G*.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

from kgcoevo.kb.executor import Executor
from kgcoevo.kb.store import Edit, Fact, KBStore, apply_edits, content_id, qual_json
from kgcoevo.kb.values import parse_time, value_kind, value_str


@dataclass
class Defect:
    defect_id: str
    op: str  # delete | corrupt
    subtype: str  # attr_date | attr_year | attr_quantity | attr_string | rel_object | qual_<kind>
    hardness: str  # similar | random | n/a
    fid: str
    cid_before: str
    cid_after: str
    kind: str
    subject: str
    key: str
    before: str
    after: str
    functional: bool
    in_support: bool
    passage_ids: list[str] = field(default_factory=list)
    edit: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=4)
def _pools(store: KBStore) -> dict:
    """Value pools for corruption, computed once per KB (store objects hash by identity)."""
    rel_objects: dict[str, set] = defaultdict(set)
    attr_values: dict[str, set] = defaultdict(set)
    strings: set = set()
    by_concept: dict[str, set] = defaultdict(set)
    for g in store.facts.values():
        if g.kind == "rel":
            rel_objects[g.key].add(g.value)
        elif g.kind == "attr" and value_kind(g.value) == "string":
            attr_values[g.key].add(value_str(g.value))
            strings.add(value_str(g.value))
    for e in store.entities:
        for c in store.direct_concepts(e):
            by_concept[c].add(e)
    return {"rel_objects": rel_objects, "attr_values": attr_values, "strings": strings, "by_concept": by_concept}


def _shift_year(y: int, rng: random.Random) -> int:
    return y + rng.choice([d for d in range(-5, 6) if d != 0])


def corrupt_value(store: KBStore, f: Fact, rng: random.Random, hardness: str) -> Any | None:
    """New value for ``f`` (value dict, or entity id for relations); None if impossible."""
    if f.kind == "rel":
        pools = _pools(store)
        concepts = set(store.direct_concepts(f.value))
        same_concept = set().union(*[pools["by_concept"][c] for c in concepts]) if concepts else set()
        existing = {g.value for g in store.rel_out(f.subject, f.key)} | {f.subject}
        if hardness == "similar":
            pool = pools["rel_objects"][f.key] & same_concept
        else:
            pool = same_concept
        pool = sorted(pool - existing)
        return rng.choice(pool) if pool else None
    v = f.value
    kind = value_kind(v)
    if kind == "date":
        d = parse_time(v["value"])[1]
        if hardness == "similar":
            y = _shift_year(d.year, rng)
            day = min(d.day, 28) if d.month == 2 else d.day
            return {"type": "date", "value": date(max(y, 1), d.month, day).isoformat()}
        return {"type": "date", "value": date(rng.randint(1800, 2015), rng.randint(1, 12), rng.randint(1, 28)).isoformat()}
    if kind == "year":
        y = parse_time(v["value"])[1]
        new = _shift_year(y, rng) if hardness == "similar" else rng.randint(1000, 2015)
        return {"type": v["type"], "value": new if v["type"] == "year" else str(new)} if new != y else None
    if kind == "quantity":
        x = float(v["value"])
        if x == 0:
            return None
        factor = rng.choice([rng.uniform(0.7, 0.9), rng.uniform(1.1, 1.3)]) if hardness == "similar" else rng.uniform(0.1, 10)
        new = x * factor
        new = round(new) if abs(x - round(x)) < 1e-9 else round(new, 3)
        return {"type": "quantity", "value": new, "unit": v.get("unit", "1")} if new != x else None
    # string
    pools = _pools(store)
    pool = pools["attr_values"][f.key] if hardness == "similar" else pools["strings"]
    pool = sorted(pool - {value_str(v)})
    return {"type": "string", "value": rng.choice(pool)} if pool else None


def _subtype(f: Fact) -> str:
    if f.kind == "rel":
        return "rel_object"
    return f"{'attr' if f.kind == 'attr' else 'qual'}_{value_kind(f.value)}"


def _after_cid(store: KBStore, f: Fact, new: Any) -> str:
    if f.kind == "rel":
        return content_id("rel", f.subject, f.key, new, qual_json(f.qualifiers))
    if f.kind == "attr":
        return content_id("attr", f.subject, f.key, value_str(new), qual_json(f.qualifiers))
    return content_id("qual", f.subject, f.key, value_str(new), "", store.cid(f.parent))


def make_defect(store: KBStore, f: Fact, op: str, rng: random.Random, hardness: str, functional: dict,
                support: dict, defect_id: str) -> Defect | None:
    if op == "delete":
        edit, after, cid_after, hard = Edit.delete(store, f), "", "", "n/a"
    else:
        new = corrupt_value(store, f, rng, hardness)
        if new is None:
            return None
        edit, hard = Edit.update(store, f, new), hardness
        after = new if f.kind == "rel" else value_str(new)
        cid_after = _after_cid(store, f, new)
    rec = support.get(f.fid, {})
    return Defect(defect_id, op, _subtype(f), hard, f.fid, store.cid(f.fid), cid_after, f.kind, f.subject, f.key,
                  f.vstr, after, bool(functional.get(f.key if f.kind != "qual" else store.facts[f.parent].key, False)),
                  bool(rec.get("supported", False)), list(rec.get("passage_ids", [])), edit.to_json())


def inject_defects(store: KBStore, support_records: list[dict], *, rate: float, seed: int, scope: list[str],
                   delete_frac: float = 0.5, similar_frac: float = 0.5, n_unsupported: int = 0,
                   prefix: str = "d") -> list[Defect]:
    """Sample defects from supported facts of ``scope`` (and optionally unsupported controls)."""
    rng = random.Random(seed)
    support = {r["fid"]: r for r in support_records}
    functional = store.functional_keys()
    scope_set = set(scope)
    eligible = sorted(r["fid"] for r in support_records if r["supported"] and r["subject"] in scope_set)
    rng.shuffle(eligible)
    n = round(rate * len(eligible))
    n_del = round(n * delete_frac)
    chosen: list[Defect] = []
    used: set[str] = set()

    def blocked(f: Fact) -> bool:  # never touch a fact and its qualifier / parent at the same time
        return f.fid in used or (f.parent in used) or any(q in used for q in store.quals_of.get(f.fid, []))

    def take(cands: list[str], op: str, k: int, in_s: bool) -> None:
        for fid in cands:
            if k <= 0:
                return
            f = store.facts[fid]
            if blocked(f):
                continue
            hard = "similar" if rng.random() < similar_frac else "random"
            d = make_defect(store, f, op, rng, hard, functional, support, f"{prefix}{len(chosen):05d}")
            if d is None:
                continue
            d.in_support = in_s
            chosen.append(d)
            used.add(fid)
            k -= 1

    take(eligible, "delete", n_del, True)
    take(eligible, "corrupt", n - n_del, True)
    if n_unsupported:
        unsup = sorted(r["fid"] for r in support_records if not r["supported"] and r["subject"] in scope_set)
        rng.shuffle(unsup)
        take(unsup, "delete", n_unsupported // 2, False)
        take(unsup, "corrupt", n_unsupported - n_unsupported // 2, False)
    return chosen


def build_gw(store: KBStore, defects: list[Defect]) -> dict:
    return apply_edits(store.kb, [Edit.from_json(d.edit) for d in defects], store.has_mirrors)


def self_check(gstar: KBStore, gw: KBStore, gw_exec: Executor, defects: list[Defect]) -> dict:
    """Verify every defect in Gw: removed/changed content and consistent mirrors."""
    gw_cids = set(gw.cid_to_fid)
    failures = []
    dup: Counter | None = None
    for d in defects:
        ok = d.cid_before not in gw_cids
        if not ok:  # G* may contain the same content twice; then one copy legitimately survives
            dup = dup or Counter(gstar.cid(fid) for fid in gstar.facts)
            ok = dup[d.cid_before] > 1
        if d.op == "corrupt":
            ok = ok and d.cid_after in gw_cids
        if d.kind == "rel":
            eng = gw_exec.engine
            fwd = set(eng.Relate(([d.subject], None), d.key, "forward")[0])
            ok = ok and d.before not in fwd
            if gstar.has_mirrors:
                back_old = set(eng.Relate(([d.before], None), d.key, "backward")[0])
                ok = ok and d.subject not in back_old
                if d.op == "corrupt":
                    ok = ok and d.after in fwd and d.subject in set(eng.Relate(([d.after], None), d.key, "backward")[0])
        if not ok:
            failures.append(d.defect_id)
    return {"n_defects": len(defects), "n_failed": len(failures), "failed": failures[:50]}

"""In-memory view of a KQA Pro knowledge base with stable fact ids and pure edit operations.

Conventions
-----------
* The raw kb.json may use ``predicate`` or ``relation`` for relation names and ``instanceOf`` or
  ``subclassOf`` for concept parents. :func:`normalize_kb` converts it to the format the official
  KoPL engine expects (``relation`` / ``subclassOf``).
* A relational fact (s, r, o) is canonical in the forward direction. KQA Pro may additionally
  store a *mirror* entry at ``o`` with ``direction == "backward"``; edits always keep both sides
  consistent, otherwise a deleted fact would still be reachable through the inverse edge.
* Fact ids are content hashes, so every fact that an edit does not touch keeps its id in the
  edited KB. This lets G* and Gw share ids and makes defect logs joinable with any trace.
* Relations whose object is a concept (not an entity) are excluded from the fact inventory.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from kgcoevo.kb.values import value_str


class EditError(ValueError):
    """Raised when an edit cannot be applied to a KB."""


def normalize_kb(kb: dict) -> dict:
    """Deep-copy ``kb`` into the field names used by the official KoPL engine."""
    kb = copy.deepcopy(kb)
    for c in kb.get("concepts", {}).values():
        if "subclassOf" not in c:
            c["subclassOf"] = c.pop("instanceOf", [])
    for e in kb["entities"].values():
        e.setdefault("instanceOf", [])
        e.setdefault("attributes", [])
        e.setdefault("relations", [])
        for a in e["attributes"]:
            a.setdefault("qualifiers", {})
        for r in e["relations"]:
            if "relation" not in r:
                r["relation"] = r.pop("predicate")
            r.setdefault("qualifiers", {})
    return kb


def qual_json(quals: dict) -> str:
    """Order-independent canonical string for a qualifier dict."""
    return json.dumps({k: sorted(value_str(v) for v in vs) for k, vs in quals.items() if vs}, sort_keys=True)


def _hash(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def content_id(kind: str, subject: str, key: str, vstr: str, qj: str = "", parent_cid: str = "") -> str:
    """Occurrence-free content id; identical facts in G* and an edited KB share it."""
    return _hash("c", kind, subject, key, vstr, qj, parent_cid)


@dataclass
class Fact:
    """A single KB fact. ``value`` is a value dict for attr/qual facts and an entity id for rel facts."""

    fid: str
    kind: str  # "attr" | "rel" | "qual"
    subject: str
    key: str
    value: Any
    qualifiers: dict = field(default_factory=dict)
    parent: str | None = None  # parent fid for qualifier facts

    @property
    def vstr(self) -> str:
        return self.value if self.kind == "rel" else value_str(self.value)

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Edit:
    """A KB edit. For qualifier edits, ``parent_*`` identifies the attribute/relation that carries it."""

    op: str  # "delete" | "update" | "add"
    kind: str  # "attr" | "rel" | "qual"
    subject: str
    key: str
    value: Any = None  # old value dict (attr/qual) or old object id (rel); None for "add"
    new_value: Any = None  # new value dict (attr/qual) or new object id (rel)
    qualifiers: dict = field(default_factory=dict)  # qualifiers of the attr/rel entry itself
    parent_kind: str | None = None
    parent_key: str | None = None
    parent_value: Any = None
    parent_qualifiers: dict = field(default_factory=dict)
    target_fid: str | None = None

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "Edit":
        return Edit(**d)

    # -- constructors -------------------------------------------------------------------------
    @staticmethod
    def delete(store: "KBStore", fact: Fact) -> "Edit":
        return Edit._for_fact(store, fact, "delete", None)

    @staticmethod
    def update(store: "KBStore", fact: Fact, new_value: Any) -> "Edit":
        return Edit._for_fact(store, fact, "update", new_value)

    @staticmethod
    def add_attr(subject: str, key: str, value: dict, qualifiers: dict | None = None) -> "Edit":
        return Edit("add", "attr", subject, key, None, value, qualifiers or {})

    @staticmethod
    def add_rel(subject: str, relation: str, obj: str, qualifiers: dict | None = None) -> "Edit":
        return Edit("add", "rel", subject, relation, None, obj, qualifiers or {})

    @staticmethod
    def _for_fact(store: "KBStore", fact: Fact, op: str, new_value: Any) -> "Edit":
        if fact.kind in ("attr", "rel"):
            return Edit(op, fact.kind, fact.subject, fact.key, fact.value, new_value,
                        copy.deepcopy(fact.qualifiers), target_fid=fact.fid)
        parent = store.facts[fact.parent]
        return Edit(op, "qual", fact.subject, fact.key, fact.value, new_value, {},
                    parent.kind, parent.key, parent.value, copy.deepcopy(parent.qualifiers), target_fid=fact.fid)


class KBStore:
    """Read-only index over a (normalized) KQA Pro KB dict."""

    def __init__(self, kb: dict, normalized: bool = False):
        self.kb = kb if normalized else normalize_kb(kb)
        self.entities: dict = self.kb["entities"]
        self.concepts: dict = self.kb.get("concepts", {})
        self._build()

    # -- construction ---------------------------------------------------------------------------
    def _build(self) -> None:
        self.name_to_ids: dict[str, list[str]] = defaultdict(list)
        for eid in sorted(self.entities):
            self.name_to_ids[self.entities[eid]["name"]].append(eid)
        self.concept_name_to_ids: dict[str, list[str]] = defaultdict(list)
        for cid, c in self.concepts.items():
            self.concept_name_to_ids[c["name"]].append(cid)

        self.facts: dict[str, Fact] = {}
        self.by_subject: dict[str, list[str]] = defaultdict(list)
        self.by_object: dict[str, list[str]] = defaultdict(list)
        self.quals_of: dict[str, list[str]] = defaultdict(list)

        # attributes
        for eid in sorted(self.entities):
            occ: Counter = Counter()
            for a in self.entities[eid]["attributes"]:
                qj = qual_json(a["qualifiers"])
                k = (a["key"], value_str(a["value"]), qj)
                fid = _hash("attr", eid, *k, occ[k])
                occ[k] += 1
                self._add(Fact(fid, "attr", eid, a["key"], a["value"], a["qualifiers"]))

        # relations: count forward entries and backward mirrors per canonical key
        fwd: dict[tuple, list[dict]] = defaultdict(list)
        bwd: dict[tuple, list[dict]] = defaultdict(list)
        for eid in sorted(self.entities):
            for r in self.entities[eid]["relations"]:
                other = r["object"]
                if other in self.concepts or other not in self.entities:
                    continue
                if r["direction"] == "forward":
                    fwd[(eid, r["relation"], other, qual_json(r["qualifiers"]))].append(r)
                else:
                    bwd[(other, r["relation"], eid, qual_json(r["qualifiers"]))].append(r)
        n_mirrored = n_rel = 0
        for key in sorted(set(fwd) | set(bwd)):
            s, rel, o, qj = key
            entries = fwd.get(key) or bwd.get(key)
            n = max(len(fwd.get(key, [])), len(bwd.get(key, [])))
            for i in range(n):
                n_rel += 1
                n_mirrored += int(i < len(fwd.get(key, [])) and i < len(bwd.get(key, [])))
                fid = _hash("rel", s, rel, o, qj, i)
                self._add(Fact(fid, "rel", s, rel, o, entries[min(i, len(entries) - 1)]["qualifiers"]))
        self.has_mirrors = n_rel > 0 and n_mirrored / n_rel >= 0.5

    def _add(self, f: Fact) -> None:
        self.facts[f.fid] = f
        self.by_subject[f.subject].append(f.fid)
        if f.kind == "rel":
            self.by_object[f.value].append(f.fid)
        occ: Counter = Counter()
        for qk, qvs in f.qualifiers.items():
            for qv in qvs:
                k = (qk, value_str(qv))
                qid = _hash("qual", f.fid, *k, occ[k])
                occ[k] += 1
                q = Fact(qid, "qual", f.subject, qk, qv, {}, f.fid)
                self.facts[qid] = q
                self.quals_of[f.fid].append(qid)
                self.by_subject[f.subject].append(qid)

    # -- lookups --------------------------------------------------------------------------------
    def name(self, eid: str) -> str:
        if eid in self.entities:
            return self.entities[eid]["name"]
        return self.concepts[eid]["name"]

    def direct_concepts(self, eid: str) -> list[str]:
        return [c for c in self.entities[eid].get("instanceOf", []) if c in self.concepts]

    @lru_cache(maxsize=None)
    def all_concepts(self, eid: str) -> tuple[str, ...]:
        """Direct and ancestor concepts (BFS over subclassOf), as in kopl.data.KB.get_all_concepts."""
        seen: list[str] = []
        q = deque(self.direct_concepts(eid))
        while q:
            c = q.popleft()
            if c in self.concepts and c not in seen:
                seen.append(c)
                q.extend(self.concepts[c].get("subclassOf", []))
        return tuple(seen)

    def concept_names(self, eid: str) -> list[str]:
        return [self.concepts[c]["name"] for c in self.direct_concepts(eid)]

    def describe(self, eid: str) -> str:
        cs = self.concept_names(eid)
        return f"{self.name(eid)} ({', '.join(cs)})" if cs else self.name(eid)

    def facts_of(self, eid: str, kinds: Iterable[str] = ("attr", "rel", "qual")) -> list[Fact]:
        kinds = set(kinds)
        return [self.facts[f] for f in self.by_subject.get(eid, []) if self.facts[f].kind in kinds]

    def attr_facts(self, eid: str, key: str | None = None) -> list[Fact]:
        return [f for f in self.facts_of(eid, ("attr",)) if key is None or f.key == key]

    def rel_out(self, eid: str, rel: str | None = None) -> list[Fact]:
        return [f for f in self.facts_of(eid, ("rel",)) if rel is None or f.key == rel]

    def rel_in(self, eid: str, rel: str | None = None) -> list[Fact]:
        return [self.facts[f] for f in self.by_object.get(eid, []) if rel is None or self.facts[f].key == rel]

    def rel_step(self, eid: str, rel: str, direction: str) -> list[tuple[str, Fact]]:
        """(neighbor, fact) pairs reached from ``eid`` by Relate(rel, direction)."""
        if direction == "forward":
            return [(f.value, f) for f in self.rel_out(eid, rel)]
        return [(f.subject, f) for f in self.rel_in(eid, rel)]

    def quals(self, fid: str, qkey: str | None = None) -> list[Fact]:
        return [self.facts[q] for q in self.quals_of.get(fid, []) if qkey is None or self.facts[q].key == qkey]

    def neighbors(self, eid: str) -> set[str]:
        return {f.value for f in self.rel_out(eid)} | {f.subject for f in self.rel_in(eid)}

    def entities_with_concept(self, concept_name: str) -> list[str]:
        cids = set(self.concept_name_to_ids.get(concept_name, []))
        return [e for e in sorted(self.entities) if cids & set(self.all_concepts(e))]

    def fact_text(self, f: Fact, show_quals: bool = True) -> str:
        """Human-readable rendering used in prompts and audit sheets."""
        if f.kind == "qual":
            p = self.facts.get(f.parent)
            ptxt = self.fact_text(p, show_quals=False) if p else "?"
            return f"[{ptxt}] qualifier {f.key}: {value_str(f.value)}"
        if f.kind == "rel":
            txt = f"{self.name(f.subject)} --{f.key}--> {self.name(f.value)}"
        else:
            txt = f"{self.name(f.subject)} | {f.key}: {value_str(f.value)}"
        if show_quals and f.qualifiers:
            qs = "; ".join(f"{k}: {', '.join(value_str(v) for v in vs)}" for k, vs in f.qualifiers.items())
            txt += f" ({qs})"
        return txt

    def functional_keys(self, threshold: float = 0.95, min_subjects: int = 5) -> dict[str, bool]:
        """A key is functional if >= ``threshold`` of its subjects have exactly one value."""
        per: dict[str, Counter] = defaultdict(Counter)
        for f in self.facts.values():
            if f.kind in ("attr", "rel"):
                per[f.key][f.subject] += 1
        out = {}
        for key, cnt in per.items():
            n = len(cnt)
            out[key] = n >= min_subjects and sum(1 for c in cnt.values() if c == 1) / n >= threshold
        return out

    def cid(self, fid: str) -> str:
        """Content id of a fact (see :func:`content_id`)."""
        f = self.facts[fid]
        if f.kind == "qual":
            return content_id("qual", f.subject, f.key, f.vstr, "", self.cid(f.parent))
        return content_id(f.kind, f.subject, f.key, f.vstr, qual_json(f.qualifiers))

    @property
    def cid_to_fid(self) -> dict[str, str]:
        if not hasattr(self, "_cid_to_fid"):
            self._cid_to_fid = {}
            for fid in self.facts:
                self._cid_to_fid.setdefault(self.cid(fid), fid)
        return self._cid_to_fid

    def find_fact(self, kind: str, subject: str, key: str, vstr: str) -> Fact | None:
        for f in self.facts_of(subject, (kind,)):
            if f.key == key and f.vstr == vstr:
                return f
        return None


# --------------------------------------------------------------------------------------------
# Pure edit application on KB dicts
# --------------------------------------------------------------------------------------------

def _match_attr(entry: dict, key: str, value: dict, quals: dict | None) -> bool:
    return (entry["key"] == key and value_str(entry["value"]) == value_str(value)
            and (quals is None or qual_json(entry["qualifiers"]) == qual_json(quals)))


def _match_rel(entry: dict, rel: str, direction: str, obj: str, quals: dict | None) -> bool:
    return (entry["relation"] == rel and entry["direction"] == direction and entry["object"] == obj
            and (quals is None or qual_json(entry["qualifiers"]) == qual_json(quals)))


def _find(lst: list[dict], pred) -> int:
    for i, x in enumerate(lst):
        if pred(x):
            return i
    return -1


def _rel_entries(kb: dict, s: str, rel: str, o: str, quals: dict) -> list[dict]:
    """Forward entry at s and backward mirror at o (whichever exist)."""
    out = []
    i = _find(kb["entities"][s]["relations"], lambda x: _match_rel(x, rel, "forward", o, quals))
    if i >= 0:
        out.append(kb["entities"][s]["relations"][i])
    if o in kb["entities"]:
        j = _find(kb["entities"][o]["relations"], lambda x: _match_rel(x, rel, "backward", s, quals))
        if j >= 0:
            out.append(kb["entities"][o]["relations"][j])
    return out


def apply_edits(kb: dict, edits: list[Edit], has_mirrors: bool) -> dict:
    """Return a new normalized KB dict with ``edits`` applied in order (input is not modified)."""
    kb = copy.deepcopy(kb)
    for e in edits:
        _apply_one(kb, e, has_mirrors)
    return kb


def _apply_one(kb: dict, e: Edit, has_mirrors: bool) -> None:
    ents = kb["entities"]
    if e.subject not in ents:
        raise EditError(f"unknown subject {e.subject}")
    if e.kind == "attr":
        attrs = ents[e.subject]["attributes"]
        if e.op == "add":
            attrs.append({"key": e.key, "value": copy.deepcopy(e.new_value), "qualifiers": copy.deepcopy(e.qualifiers)})
            return
        i = _find(attrs, lambda x: _match_attr(x, e.key, e.value, e.qualifiers))
        if i < 0:
            raise EditError(f"attr not found: {e.subject} {e.key} {value_str(e.value)}")
        if e.op == "delete":
            attrs.pop(i)
        else:
            attrs[i]["value"] = copy.deepcopy(e.new_value)
        return

    if e.kind == "rel":
        if e.op in ("delete", "update"):
            removed = False
            rels = ents[e.subject]["relations"]
            i = _find(rels, lambda x: _match_rel(x, e.key, "forward", e.value, e.qualifiers))
            if i >= 0:
                rels.pop(i)
                removed = True
            if e.value in ents:
                mrels = ents[e.value]["relations"]
                j = _find(mrels, lambda x: _match_rel(x, e.key, "backward", e.subject, e.qualifiers))
                if j >= 0:
                    mrels.pop(j)
                    removed = True
            if not removed:
                raise EditError(f"rel not found: {e.subject} {e.key} {e.value}")
            if e.op == "delete":
                return
        obj = e.new_value
        if obj not in ents:
            raise EditError(f"unknown object {obj}")
        ents[e.subject]["relations"].append(
            {"relation": e.key, "direction": "forward", "object": obj, "qualifiers": copy.deepcopy(e.qualifiers)})
        if has_mirrors:
            ents[obj]["relations"].append(
                {"relation": e.key, "direction": "backward", "object": e.subject, "qualifiers": copy.deepcopy(e.qualifiers)})
        return

    # qualifier edits: apply on the parent entry (and its mirror for relations)
    if e.parent_kind == "attr":
        attrs = ents[e.subject]["attributes"]
        i = _find(attrs, lambda x: _match_attr(x, e.parent_key, e.parent_value, e.parent_qualifiers))
        parents = [attrs[i]] if i >= 0 else []
    else:
        parents = _rel_entries(kb, e.subject, e.parent_key, e.parent_value, e.parent_qualifiers)
    if not parents:
        raise EditError(f"qualifier parent not found for {e.subject} {e.parent_key}")
    for p in parents:
        qs = p["qualifiers"]
        if e.op == "add":
            qs.setdefault(e.key, []).append(copy.deepcopy(e.new_value))
            continue
        vals = qs.get(e.key, [])
        k = _find(vals, lambda v: value_str(v) == value_str(e.value))
        if k < 0:
            raise EditError(f"qualifier not found: {e.key} {value_str(e.value)}")
        if e.op == "delete":
            vals.pop(k)
            if not vals:
                qs.pop(e.key)
        else:
            vals[k] = copy.deepcopy(e.new_value)

"""Path sampling on a (possibly defective) KG and deterministic compilation to KoPL.

A *path* is a short reasoning chain rooted at an anchor entity. Paths are sampled from the KG the
Challenger actually has (Gw), compiled to KoPL by a fixed compiler (so program-writing errors of
the LLM cannot contaminate the measurement of KG-induced errors), and verified to have a unique
answer on Gw with the official engine. All conditions of Exp 1 Mode A receive the same paths.

Path types (hops): attr (1), rel (1), attr_qual (1), rel_qual (1), rel_attr (2), rel_rel (2),
rel_relqual (2).

``DirectedSampler`` draws the Exp 1 paths in two groups of fixed size: *defective* paths that use a
corrupted fact and *clean* paths whose first-hop fact is an unchanged, text-supported fact (S).
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Callable

from kgcoevo.eval.compare import answers_equal
from kgcoevo.kb.executor import Executor
from kgcoevo.kb.store import Fact, KBStore
from kgcoevo.kb.values import kopl_input

HOPS = {"attr": 1, "rel": 1, "attr_qual": 1, "rel_qual": 1, "rel_attr": 2, "rel_rel": 2, "rel_relqual": 2}


@dataclass
class Path:
    path_id: str
    ptype: str
    hops: int
    anchor: str
    entities: list[str]
    mention: list[str]  # entity ids the question must name
    hidden: list[str]  # bridge entity ids the question must not name
    fact_cids: list[str]
    facts_text: list[str]
    program: list[dict]
    description: str
    answer_gw: str
    template_question: str
    meta: dict = field(default_factory=dict)
    group: str = ""  # "defective" | "clean" (DirectedSampler) or "" (PathSampler)
    defect_ids: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def step(fn: str, *inputs: str) -> dict:
    return {"function": fn, "inputs": list(inputs)}


def find_prefix(store: KBStore, eid: str) -> list[dict] | None:
    """Find(name) [+ FilterConcept] that selects exactly ``eid``; None if impossible."""
    name = store.name(eid)
    ids = store.name_to_ids.get(name, [])
    if ids == [eid]:
        return [step("Find", name)]
    for cid in store.all_concepts(eid):
        cname = store.concepts[cid]["name"]
        cids = set(store.concept_name_to_ids[cname])
        if [i for i in ids if cids & set(store.all_concepts(i))] == [eid]:
            return [step("Find", name), step("FilterConcept", cname)]
    return None


def relate_steps(store: KBStore, src: str, rel: str, direction: str, dst: str) -> list[dict] | None:
    """Relate(rel, direction) [+ FilterConcept] that reaches exactly ``dst`` from ``src``."""
    targets = {n for n, _ in store.rel_step(src, rel, direction)}
    if dst not in targets:
        return None
    if targets == {dst}:
        return [step("Relate", rel, direction)]
    for cid in store.all_concepts(dst):
        cname = store.concepts[cid]["name"]
        cids = set(store.concept_name_to_ids[cname])
        if {t for t in targets if cids & set(store.all_concepts(t))} == {dst}:
            return [step("Relate", rel, direction), step("FilterConcept", cname)]
    return None


def _single(facts: list[Fact], key: str) -> Fact | None:
    same = [f for f in facts if f.key == key]
    return same[0] if len(same) == 1 else None


class PathSampler:
    def __init__(self, store: KBStore, executor: Executor, seed: int = 0, single_target: bool = False):
        """``single_target``: every Relate step must reach exactly one entity, so no FilterConcept is
        needed to pick one of several values (a question cannot express that filter and would be
        ambiguous, e.g. "where was X educated?" for someone with two schools)."""
        self.store = store
        self.ex = executor
        self.rng = random.Random(seed)
        self.single_target = single_target
        self._steps: dict[tuple, tuple[set, Counter]] = {}

    def _relate(self, src: str, rel: str, direction: str, dst: str) -> list[dict] | None:
        """Same result as :func:`relate_steps`, memoised per (src, rel, direction).

        Hub entities (countries, big cities, parties) have thousands of neighbours; recomputing the
        target set for every destination would make enumeration quadratic."""
        key = (src, rel, direction)
        if key not in self._steps:
            s = self.store
            targets = {n for n, _ in s.rel_step(src, rel, direction)}
            names: Counter = Counter()
            for t in targets:
                names.update({s.concepts[c]["name"] for c in s.all_concepts(t)})
            self._steps[key] = (targets, names)
        targets, names = self._steps[key]
        if dst not in targets:
            return None
        if len(targets) == 1:
            return [step("Relate", rel, direction)]
        if self.single_target:
            return None
        for cid in self.store.all_concepts(dst):
            cname = self.store.concepts[cid]["name"]
            if names[cname] == 1:
                return [step("Relate", rel, direction), step("FilterConcept", cname)]
        return None

    # -- candidate enumeration -------------------------------------------------------------------
    def _rel_moves(self, eid: str) -> list[tuple[str, str, str, Fact]]:
        moves = [(f.key, "forward", f.value, f) for f in self.store.rel_out(eid)]
        moves += [(f.key, "backward", f.subject, f) for f in self.store.rel_in(eid)]
        return [m for m in moves if m[2] != eid]

    def candidates(self, a: str, ptype: str, first_ok: Callable[[Fact], bool] | None = None) -> list[dict]:
        """All candidate paths of ``ptype`` from anchor ``a``; ``first_ok`` filters the first-hop fact."""
        s = self.store
        pre = find_prefix(s, a)
        if pre is None:
            return []
        ok = first_ok or (lambda f: True)
        out: list[dict] = []
        attrs = s.attr_facts(a)
        if ptype == "attr":
            for key in sorted({f.key for f in attrs}):
                f = _single(attrs, key)
                if f and ok(f):
                    out.append(dict(program=pre + [step("QueryAttr", key)], facts=[f], ents=[a], hidden=[],
                                    mention=[a], words=[("attr", key)]))
        elif ptype == "attr_qual":
            for f in attrs:
                if not ok(f):
                    continue
                for q in s.quals(f.fid):
                    if len(s.quals(f.fid, q.key)) == 1:
                        out.append(dict(program=pre + [step("QueryAttrQualifier", f.key, kopl_input(f.value), q.key)],
                                        facts=[f, q], ents=[a], hidden=[], mention=[a],
                                        words=[("attr_value", f.key, kopl_input(f.value)), ("qual", q.key)]))
        elif ptype in ("rel", "rel_attr", "rel_rel", "rel_relqual"):
            for rel, d, b, f in self._rel_moves(a):
                if not ok(f):
                    continue
                rs = self._relate(a, rel, d, b)
                if rs is None:
                    continue
                base = pre + rs
                if ptype == "rel":
                    out.append(dict(program=base + [step("QueryName")], facts=[f], ents=[a, b], hidden=[],
                                    mention=[a], words=[("rel", rel, d), ("name",)]))
                elif ptype == "rel_attr":
                    battrs = s.attr_facts(b)
                    for key in sorted({g.key for g in battrs}):
                        g = _single(battrs, key)
                        if g:
                            out.append(dict(program=base + [step("QueryAttr", key)], facts=[f, g], ents=[a, b],
                                            hidden=[b], mention=[a], words=[("rel", rel, d), ("attr", key)]))
                elif ptype == "rel_rel":
                    for rel2, d2, c, g in self._rel_moves(b):
                        if c == a:
                            continue
                        rs2 = self._relate(b, rel2, d2, c)
                        if rs2:
                            out.append(dict(program=base + rs2 + [step("QueryName")], facts=[f, g], ents=[a, b, c],
                                            hidden=[b], mention=[a], words=[("rel", rel, d), ("rel", rel2, d2), ("name",)]))
                else:  # rel_relqual: a -> b, then (b, rel2, c) forward with a qualifier
                    for g in s.rel_out(b):
                        c = g.value
                        if c == a:
                            continue
                        cpre = find_prefix(s, c)
                        if cpre is None:
                            continue
                        for q in s.quals(g.fid):
                            if len(s.quals(g.fid, q.key)) == 1:
                                out.append(dict(
                                    program=base + cpre + [step("QueryRelationQualifier", g.key, q.key)],
                                    facts=[f, g, q], ents=[a, b, c], hidden=[b], mention=[a, c],
                                    words=[("rel", rel, d), ("relqual", g.key, c, q.key)]))
        elif ptype == "rel_qual":
            for f in s.rel_out(a) + s.rel_in(a):
                subj, obj = f.subject, f.value
                if subj == obj or not ok(f):
                    continue
                p1, p2 = find_prefix(s, subj), find_prefix(s, obj)
                if p1 is None or p2 is None:
                    continue
                for q in s.quals(f.fid):
                    if len(s.quals(f.fid, q.key)) == 1:
                        out.append(dict(program=p1 + p2 + [step("QueryRelationQualifier", f.key, q.key)],
                                        facts=[f, q], ents=[subj, obj], hidden=[], mention=[subj, obj],
                                        words=[("relqual2", subj, f.key, obj, q.key)]))
        return out

    # -- sampling ----------------------------------------------------------------------------------
    def sample(self, anchors: list[str], n: int, type_weights: dict[str, float], max_tries: int = 50) -> list[Path]:
        """Sample ``n`` verified paths, cycling over anchors so each anchor contributes evenly."""
        types = [t for t in type_weights if type_weights[t] > 0]
        weights = [type_weights[t] for t in types]
        anchors = list(anchors)
        self.rng.shuffle(anchors)
        paths: list[Path] = []
        seen: set[str] = set()
        tries = 0
        i = 0
        while len(paths) < n and tries < n * max_tries and anchors:
            tries += 1
            a = anchors[i % len(anchors)]
            i += 1
            t = self.rng.choices(types, weights)[0]
            cands = self.candidates(a, t)
            if not cands:
                continue
            c = self.rng.choice(cands)
            pid = hashlib.sha1(repr(c["program"]).encode()).hexdigest()[:12]
            if pid in seen:
                continue
            res = self.ex.run(c["program"])
            if not res.unique:
                continue
            seen.add(pid)
            paths.append(self._make(pid, t, a, c, res.answers[0]))
        return paths

    def _make(self, pid: str, t: str, a: str, c: dict, answer: str) -> Path:
        s = self.store
        desc = describe_program(s, c["program"])
        return Path(
            path_id=pid, ptype=t, hops=HOPS[t], anchor=a, entities=c["ents"], mention=c["mention"],
            hidden=c["hidden"], fact_cids=[s.cid(f.fid) for f in c["facts"]],
            facts_text=[s.fact_text(f) for f in c["facts"]], program=c["program"], description=desc,
            answer_gw=answer, template_question=template_question(s, a, c["words"]),
        )


def _pid(program: list[dict]) -> str:
    return hashlib.sha1(repr(program).encode()).hexdigest()[:12]


def _weighted_order(rng: random.Random, items: list[str], weights: list[float]) -> list[str]:
    """``items`` in random order, drawn without replacement with probability proportional to weight."""
    pool = [(i, w) for i, w in zip(items, weights) if w > 0]
    out = []
    while pool:
        k = rng.choices(range(len(pool)), [w for _, w in pool])[0]
        out.append(pool.pop(k)[0])
    return out


def _allocate(counts: dict[str, float], n: int) -> Counter:
    """Split ``n`` over the keys of ``counts`` in proportion to the values (largest remainder)."""
    total = sum(counts.values())
    if total <= 0 or n <= 0:
        return Counter()
    raw = {k: n * v / total for k, v in counts.items()}
    out = Counter({k: int(x) for k, x in raw.items()})
    for k in sorted(raw, key=lambda k: (-(raw[k] - int(raw[k])), k))[: n - sum(out.values())]:
        out[k] += 1
    return out


class DirectedSampler:
    """Exp 1 Mode A paths in two groups of fixed size, shared by all conditions.

    defective  the path uses a corrupted fact, anchored at the defect's subject (the corrupted fact,
               or the fact it qualifies, is the first hop), and the defect changes a well-defined
               answer: the program has a unique answer on G* that differs from the Gw answer.
    clean      no path fact is changed, the first-hop fact is in S (stated in the documents), and the
               program has the same unique answer on Gw and G*.
    Every Relate step reaches a single entity (no FilterConcept among several values), so the
    natural-language question has one answer.

    Both groups have a unique G* answer and a text-supported first hop, so detection on defective
    paths and false alarms on clean paths are measured on comparable facts. Clean paths follow the
    path-type mix of the defective group. Each corrupted fact gets at most ``max_per_defect`` paths.
    Deleted facts cannot lie on a path sampled from Gw; they are measured in Mode B.
    """

    def __init__(self, gw: KBStore, gw_exec: Executor, gs_exec: Executor, gs_cids: set[str], s_cids: set[str],
                 seed: int = 0):
        self.gw = gw
        self.ps = PathSampler(gw, gw_exec, seed=seed, single_target=True)
        self.gwx, self.gsx = gw_exec, gs_exec
        self.gs_cids, self.s_cids = gs_cids, s_cids
        self.rng = random.Random(seed)
        self.seen: set[str] = set()
        self._clean_cands: dict[tuple[str, str], list[dict]] = {}

    def _run(self, c: dict):
        r = self.gwx.run(c["program"])
        return (r.answers[0], self.gsx.run(c["program"])) if r.unique else None

    def _defective(self, d: dict, types: list[str], weights: list[float], max_tries: int) -> Path | None:
        gw = self.gw
        fid = gw.cid_to_fid.get(d["cid_after"])
        if fid is None:
            return None
        f = gw.facts[fid]
        first_cid = gw.cid(f.parent) if f.kind == "qual" else d["cid_after"]
        tries = 0
        for t in _weighted_order(self.rng, types, weights):
            cands = [c for c in self.ps.candidates(d["subject"], t, lambda g: gw.cid(g.fid) == first_cid)
                     if d["cid_after"] in {gw.cid(x.fid) for x in c["facts"]}]
            self.rng.shuffle(cands)
            for c in cands:
                pid = _pid(c["program"])
                if pid in self.seen:
                    continue
                if tries >= max_tries:
                    return None
                tries += 1
                res = self._run(c)
                if res and res[1].unique and not answers_equal(res[1].answer, res[0]):
                    self.seen.add(pid)
                    p = self.ps._make(pid, t, d["subject"], c, res[0])
                    p.group = "defective"
                    return p
        return None

    def _clean(self, anchors: list[str], t: str, need: int, max_tries: int) -> list[Path]:
        out: list[Path] = []
        order = list(anchors)
        self.rng.shuffle(order)
        tries = i = 0
        while len(out) < need and tries < need * max_tries and order:
            a = order[i % len(order)]
            i += 1
            tries += 1
            if (a, t) not in self._clean_cands:
                self._clean_cands[(a, t)] = self.ps.candidates(a, t, lambda g: self.gw.cid(g.fid) in self.s_cids)
            cands = self._clean_cands[(a, t)]
            if not cands:
                continue
            c = self.rng.choice(cands)
            pid = _pid(c["program"])
            if pid in self.seen or any(self.gw.cid(x.fid) not in self.gs_cids for x in c["facts"]):
                continue
            res = self._run(c)
            if res and res[1].unique and answers_equal(res[1].answer, res[0]):
                self.seen.add(pid)
                p = self.ps._make(pid, t, a, c, res[0])
                p.group = "clean"
                out.append(p)
        return out

    def sample(self, anchors: list[str], defects: list[dict], n_defective: int, n_clean: int,
               type_weights: dict[str, float], max_per_defect: int = 2, max_tries: int = 50) -> tuple[list[Path], dict]:
        types = [t for t in type_weights if type_weights[t] > 0]
        weights = [type_weights[t] for t in types]
        scope = set(anchors)
        corrupt = sorted((d for d in defects if d["op"] == "corrupt" and d["subject"] in scope), key=lambda d: d["defect_id"])
        self.rng.shuffle(corrupt)
        defective: list[Path] = []
        used: Counter = Counter()
        for _ in range(max_per_defect):
            for d in corrupt:
                if len(defective) >= n_defective:
                    break
                p = self._defective(d, types, weights, max_tries)
                if p:
                    defective.append(p)
                    used[d["defect_id"]] += 1
        by_cid = {d["cid_after"]: d["defect_id"] for d in defects if d.get("cid_after")}
        for p in defective:
            p.defect_ids = sorted({by_cid[c] for c in p.fact_cids if c in by_cid})
        mix = Counter(p.ptype for p in defective) if defective else dict(zip(types, weights))
        quota = _allocate(mix, n_clean)
        clean: list[Path] = []
        for t in sorted(quota):
            clean += self._clean(anchors, t, quota[t], max_tries)
        for t in _weighted_order(self.rng, types, weights):  # top up from the overall mix if a type ran short
            if len(clean) >= n_clean:
                break
            clean += self._clean(anchors, t, n_clean - len(clean), max_tries)
        stats = {"corrupt_defects_in_scope": len(corrupt), "defects_with_a_path": len(used),
                 "defective": dict(Counter(p.ptype for p in defective)), "clean": dict(Counter(p.ptype for p in clean)),
                 "n_defective": len(defective), "n_clean": len(clean)}
        return defective + clean, stats


def describe_program(store: KBStore, program: list[dict]) -> str:
    """Numbered natural-language rendering of a KoPL program (for prompts and judges)."""
    lines = []
    for i, st in enumerate(program, 1):
        fn = st["function"]
        raw = st.get("inputs", [])
        inp = [str(x) for x in raw] + ["?"] * 3  # LLM programs may use numbers or omit inputs
        if fn == "Find":
            lines.append(f"{i}. Find the entity named '{inp[0]}'.")
        elif fn == "FilterConcept":
            lines.append(f"{i}. Keep only entities that are a '{inp[0]}'.")
        elif fn == "Relate":
            arrow = "outgoing" if inp[1] == "forward" else "incoming"
            lines.append(f"{i}. Follow the {arrow} relation '{inp[0]}'.")
        elif fn == "QueryName":
            lines.append(f"{i}. Return the name of the resulting entity.")
        elif fn == "QueryAttr":
            lines.append(f"{i}. Return its attribute '{inp[0]}'.")
        elif fn == "QueryAttrQualifier":
            lines.append(f"{i}. For its attribute '{inp[0]}' = '{inp[1]}', return the qualifier '{inp[2]}'.")
        elif fn == "QueryRelationQualifier":
            lines.append(f"{i}. For the relation '{inp[0]}' between the two entities above, return the qualifier '{inp[1]}'.")
        else:
            lines.append(f"{i}. {fn}({', '.join(str(x) for x in raw)})")
    return "\n".join(lines)


def template_question(store: KBStore, a: str, words: list[tuple]) -> str:
    """Deterministic question used by the B0 (no-LLM) generator."""
    an = store.name(a)
    w = words
    kind = w[0][0]
    if kind == "attr":
        return f"What is the {w[0][1]} of {an}?"
    if kind == "attr_value":
        return f"What is the {w[1][1]} of the {w[0][1]} ({w[0][2]}) of {an}?"
    if kind == "relqual2":
        _, subj, rel, obj, qk = w[0]
        return f"What is the {qk} of the '{rel}' relation from {store.name(subj)} to {store.name(obj)}?"
    rel, d = w[0][1], w[0][2]
    phrase = f"the {rel} of {an}" if d == "forward" else f"the entity whose {rel} is {an}"
    nxt = w[1]
    if nxt[0] == "name":
        return f"What is {phrase}?"
    if nxt[0] == "attr":
        return f"What is the {nxt[1]} of {phrase}?"
    if nxt[0] == "rel":
        rel2, d2 = nxt[1], nxt[2]
        if d2 == "forward":
            return f"What is the {rel2} of {phrase}?"
        return f"Which entity has {phrase} as its {rel2}?"
    if nxt[0] == "relqual":
        _, rel2, c, qk = nxt
        return f"What is the {qk} of the '{rel2}' relation from {phrase} to {store.name(c)}?"
    raise ValueError(words)

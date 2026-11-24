"""Path sampling on a (possibly defective) KG and deterministic compilation to KoPL.

A *path* is a short reasoning chain rooted at an anchor entity. Paths are sampled from the KG the
Challenger actually has (Gw), compiled to KoPL by a fixed compiler (so program-writing errors of
the LLM cannot contaminate the measurement of KG-induced errors), and verified to have a unique
answer on Gw with the official engine. All conditions of Exp 1 Mode A receive the same paths.

Path types (hops): attr (1), rel (1), attr_qual (1), rel_qual (1), rel_attr (2), rel_rel (2),
rel_relqual (2).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass, field

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
    def __init__(self, store: KBStore, executor: Executor, seed: int = 0):
        self.store = store
        self.ex = executor
        self.rng = random.Random(seed)

    # -- candidate enumeration -------------------------------------------------------------------
    def _rel_moves(self, eid: str) -> list[tuple[str, str, str, Fact]]:
        moves = [(f.key, "forward", f.value, f) for f in self.store.rel_out(eid)]
        moves += [(f.key, "backward", f.subject, f) for f in self.store.rel_in(eid)]
        return [m for m in moves if m[2] != eid]

    def candidates(self, a: str, ptype: str) -> list[dict]:
        s = self.store
        pre = find_prefix(s, a)
        if pre is None:
            return []
        out: list[dict] = []
        attrs = s.attr_facts(a)
        if ptype == "attr":
            for key in sorted({f.key for f in attrs}):
                f = _single(attrs, key)
                if f:
                    out.append(dict(program=pre + [step("QueryAttr", key)], facts=[f], ents=[a], hidden=[],
                                    mention=[a], words=[("attr", key)]))
        elif ptype == "attr_qual":
            for f in attrs:
                for q in s.quals(f.fid):
                    if len(s.quals(f.fid, q.key)) == 1:
                        out.append(dict(program=pre + [step("QueryAttrQualifier", f.key, kopl_input(f.value), q.key)],
                                        facts=[f, q], ents=[a], hidden=[], mention=[a],
                                        words=[("attr_value", f.key, kopl_input(f.value)), ("qual", q.key)]))
        elif ptype in ("rel", "rel_attr", "rel_rel", "rel_relqual"):
            for rel, d, b, f in self._rel_moves(a):
                rs = relate_steps(s, a, rel, d, b)
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
                        rs2 = relate_steps(s, b, rel2, d2, c)
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
                if subj == obj:
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


def describe_program(store: KBStore, program: list[dict]) -> str:
    """Numbered natural-language rendering of a KoPL program (for prompts and judges)."""
    lines = []
    for i, st in enumerate(program, 1):
        fn, inp = st["function"], st.get("inputs", [])
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
            lines.append(f"{i}. {fn}({', '.join(inp)})")
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

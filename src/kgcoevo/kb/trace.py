"""Provenance tracing for KoPL programs: which KB facts does an answer rest on?

The tracer re-executes a program on the *engine's* KB indexes (so sandbox edits apply) and
propagates, for every intermediate entity/value, the set of facts used to reach it. It supports
the chain subset of KoPL used by KQA Pro "path" questions; programs with set operations,
filters or aggregation are reported as untraceable (and excluded from Exp 2, by design).

The final answer always comes from the official engine; the tracer only adds provenance and
refuses to trace if its own values disagree with the engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from kgcoevo.kb.executor import Executor, _eng_qual_json, validate_program
from kgcoevo.kb.store import Edit, content_id

TRACEABLE = frozenset({
    "Find", "FilterConcept", "Relate", "QueryName", "What", "QueryAttr", "QueryAttrQualifier",
    "QueryRelationQualifier", "QueryRelation", "VerifyStr", "VerifyNum", "VerifyYear", "VerifyDate",
})
TWO_BRANCH = frozenset({"And", "Or", "SelectBetween", "QueryRelation", "QueryRelationQualifier"})


@dataclass
class TraceResult:
    ok: bool
    reason: str = ""
    answers: list[str] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)  # facts supporting the final answer
    entities: list[str] = field(default_factory=list)  # entities on the supporting path(s)

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def cids(self) -> list[str]:
        return [f["cid"] for f in self.facts]


def dependencies(funcs: list[str]) -> list[list[int]]:
    """Dependency inference identical to KoPLEngine.forward (indices into the program)."""
    deps, stack = [], []
    for i, f in enumerate(funcs):
        if f in ("Find", "FindAll"):
            deps.append([])
            stack.append(i - 1)
        elif f in TWO_BRANCH:
            j = stack.pop() if stack else -1
            if j < 0:
                raise ValueError("malformed program: missing second branch")
            deps.append([j, i - 1])
        else:
            deps.append([i - 1] if i > 0 else [])
    return deps


def trace(executor: Executor, program: list[dict], edits: list[Edit] | None = None) -> TraceResult:
    err = validate_program(program)
    if err:
        return TraceResult(False, err)
    funcs = [("QueryName" if s["function"] == "What" else s["function"]) for s in program]
    bad = [f for f in funcs if f not in TRACEABLE]
    if bad:
        return TraceResult(False, f"untraceable functions: {sorted(set(bad))}")
    with executor.patched(edits):
        res = executor.run(program)
        if not res.ok:
            return TraceResult(False, f"execution error: {res.error}")
        try:
            return _trace(executor, funcs, [[str(x) for x in s.get("inputs", [])] for s in program], res.answers)
        except Exception as e:  # noqa: BLE001 - tracing failures are reported, not raised
            return TraceResult(False, f"trace error: {type(e).__name__}: {e}", res.answers)


def _trace(ex: Executor, funcs: list[str], inputs: list[list[str]], answers: list[str]) -> TraceResult:
    from kopl.util import comp

    kb = ex.kb
    registry: dict[str, dict] = {}

    def reg(d: dict) -> str:
        registry.setdefault(d["cid"], d)
        return d["cid"]

    def rel_fact(s: str, rel: str, o: str, quals: dict) -> str:
        qj = _eng_qual_json(quals)
        return reg({"cid": content_id("rel", s, rel, o, qj), "kind": "rel", "subject": s, "key": rel,
                    "value": o, "qualifiers_json": qj, "parent_cid": ""})

    def attr_fact(s: str, key: str, value, quals: dict) -> str:
        qj = _eng_qual_json(quals)
        return reg({"cid": content_id("attr", s, key, str(value), qj), "kind": "attr", "subject": s, "key": key,
                    "value": str(value), "qualifiers_json": qj, "parent_cid": ""})

    def qual_fact(s: str, qk: str, qv, parent_cid: str) -> str:
        return reg({"cid": content_id("qual", s, qk, str(qv), "", parent_cid), "kind": "qual", "subject": s,
                    "key": qk, "value": str(qv), "qualifiers_json": "", "parent_cid": parent_cid})

    mem: list[tuple[str, object]] = []
    deps = dependencies(funcs)
    for f, dep, inp in zip(funcs, deps, inputs):
        args = [mem[d][1] for d in dep]
        if f == "Find":
            out = ("ents", {e: frozenset() for e in kb.name_to_id.get(inp[0], [])})
        elif f == "FilterConcept":
            members: set[str] = set()
            for cid in kb.name_to_id.get(inp[0], []):
                members.update(kb.concept_to_entity.get(cid, []))
            out = ("ents", {e: p for e, p in args[0].items() if e in members})
        elif f == "Relate":
            rel, direction = inp[0], inp[1]
            nxt: dict[str, frozenset] = {}
            for e, p in args[0].items():
                for idx in kb.relation_inv_index.get((rel, direction), {}).get(e, []):
                    r = kb.entities[e]["relations"][idx]
                    o = r["object"]
                    s_, o_ = (e, o) if direction == "forward" else (o, e)
                    c = rel_fact(s_, rel, o_, r["qualifiers"])
                    nxt[o] = nxt.get(o, frozenset()) | p | {c}
            out = ("ents", nxt)
        elif f == "QueryName":
            out = ("vals", [(kb.entities[e]["name"], p) for e, p in args[0].items()])
        elif f == "QueryAttr":
            key = inp[0]
            vals = []
            for e, p in args[0].items():
                for idx in kb.attribute_inv_index.get(key, {}).get(e, []):
                    a = kb.entities[e]["attributes"][idx]
                    vals.append((str(a["value"]), p | {attr_fact(e, key, a["value"], a["qualifiers"])}))
            out = ("vals", vals)
        elif f == "QueryAttrQualifier":
            key, value, qkey = inp
            target = ex.engine._parse_key_value(key, value)
            vals = []
            for e, p in args[0].items():
                for idx in kb.attribute_inv_index.get(key, {}).get(e, []):
                    a = kb.entities[e]["attributes"][idx]
                    if a["value"].can_compare(target) and comp(a["value"], target, "="):
                        pc = attr_fact(e, key, a["value"], a["qualifiers"])
                        for qv in a["qualifiers"].get(qkey, []):
                            vals.append((str(qv), p | {pc, qual_fact(e, qkey, qv, pc)}))
            out = ("vals", vals)
        elif f in ("QueryRelationQualifier", "QueryRelation"):
            left, right = args
            vals = []
            for s, ps in left.items():
                for o, po in right.items():
                    for idx in kb.forward_relation_index.get((s, o), []):
                        r = kb.entities[s]["relations"][idx]
                        if f == "QueryRelation":
                            vals.append((r["relation"], ps | po | {rel_fact(s, r["relation"], o, r["qualifiers"])}))
                        elif r["relation"] == inp[0]:
                            pc = rel_fact(s, inp[0], o, r["qualifiers"])
                            for qv in r["qualifiers"].get(inp[1], []):
                                vals.append((str(qv), ps | po | {pc, qual_fact(s, inp[1], qv, pc)}))
            out = ("vals", vals)
        elif f.startswith("Verify"):
            prov = frozenset().union(*[p for _, p in args[0]]) if args[0] else frozenset()
            out = ("verify", prov)
        else:  # pragma: no cover - guarded by TRACEABLE
            raise ValueError(f)
        mem.append(out)

    kind, last = mem[-1]
    if kind == "ents":
        return TraceResult(False, "program ends with an entity set", answers)
    if kind == "verify":
        prov = last
    else:
        traced = {v for v, _ in last}
        if traced != set(answers):
            return TraceResult(False, f"tracer/engine disagreement: {sorted(traced)} vs {answers}", answers)
        prov = frozenset().union(*[p for _, p in last]) if last else frozenset()
    facts = [registry[c] for c in sorted(prov)]
    ents = sorted({x for d in facts for x in ([d["subject"], d["value"]] if d["kind"] == "rel" else [d["subject"]])})
    return TraceResult(True, "", answers, facts, ents)

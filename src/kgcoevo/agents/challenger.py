"""Challenger: Mode A (path -> task, or reject), Mode B (entity -> gap report), verbalisation."""

from __future__ import annotations

import random

from kgcoevo.agents.evidence import EvidenceBuilder
from kgcoevo.eval.discovery import KeyResolver, resolve_entities
from kgcoevo.kb.paths import describe_program, find_prefix, relate_steps, step
from kgcoevo.kb.store import KBStore
from kgcoevo.llm.parsing import extract_json
from kgcoevo.llm.prompts import messages

DECISIONS = ("accept", "correct", "reject")


def _names(store: KBStore, ids: list[str]) -> str:
    return ", ".join(f"'{store.name(e)}'" for e in ids) or "(none)"


async def mode_a(llm, path: dict, cond: str, evb: EvidenceBuilder | None, gw: KBStore, seed: int | None = None) -> dict:
    """Return the Challenger's decision for one path under one condition."""
    base = {"path_id": path["path_id"], "condition": cond, "llm_seed": seed}
    if cond == "B0":
        return {**base, "decision": "accept", "question": path["template_question"], "answer": path["answer_gw"],
                "suspect_facts": [], "raw": None, "shown_pids": []}
    ev = evb.path(path, cond)
    msgs = messages("challenger_mode_a", description=path["description"], path_facts=ev["path_facts"],
                    evidence=ev["text"], condition_note=ev["note"], mention_names=_names(gw, path["mention"]),
                    hidden_names=_names(gw, path["hidden"]))
    raw = await llm.chat(msgs, seed=seed)
    js = extract_json(raw) or {}
    decision = str(js.get("decision", "")).strip().lower()
    return {**base, "decision": decision if decision in DECISIONS else "invalid",
            "question": str(js.get("question", "") or ""), "answer": str(js.get("answer", "") or ""),
            "suspect_facts": js.get("suspect_facts", []) if isinstance(js.get("suspect_facts"), list) else [],
            "parse_ok": bool(js), "raw": raw, "shown_pids": ev["shown_pids"]}


async def mode_b(llm, eid: str, cond: str, evb: EvidenceBuilder, gw: KBStore, seed: int | None = None) -> dict:
    ev = evb.entity(eid, cond)
    msgs = messages("challenger_mode_b", entity=gw.describe(eid), kg_facts=ev["kg_facts"], evidence=ev["text"],
                    allowed_keys=ev["allowed_keys"], cite_note=ev["cite_note"])
    raw = await llm.chat(msgs, seed=seed)
    js = extract_json(raw) or {}
    gaps = js.get("gaps", [])
    return {"entity": eid, "condition": cond, "llm_seed": seed, "gaps": gaps if isinstance(gaps, list) else [],
            "parse_ok": bool(js), "raw": raw, "shown_pids": ev["shown_pids"]}


def gap_task_specs(gw: KBStore, gs: KBStore, resolver: KeyResolver, eid: str, gaps: list[dict],
                   max_tasks: int = 2, seed: int = 0) -> list[dict]:
    """Deterministically compile reported gaps into 2-hop tasks (1-hop if no bridge exists).

    The answer key is the value claimed by the Challenger; the program is executed on G* by the
    checks (it may not run on Gw when the fact is missing there)."""
    rng = random.Random(seed)
    bridges = []
    for f in sorted(gw.rel_in(eid), key=lambda f: (f.subject, f.key)):
        pre = find_prefix(gw, f.subject)
        rs = relate_steps(gw, f.subject, f.key, "forward", eid) if pre else None
        if pre and rs and f.subject != eid:
            bridges.append((f.subject, pre + rs))
    rng.shuffle(bridges)
    specs = []
    for g in gaps:
        if len(specs) >= max_tasks or not isinstance(g, dict):
            break
        key = resolver(str(g.get("key", "")))
        claimed = str(g.get("claimed_value", "") or "").strip()
        if not key or not claimed:
            continue
        tail = ([step("Relate", key, "forward"), step("QueryName")] if key in resolver.rel_keys
                else [step("QueryAttr", key)])
        if bridges:
            x, prefix = bridges[len(specs) % len(bridges)]
            program, mention, hidden = prefix + tail, [x], [eid]
        else:
            pre = find_prefix(gw, eid)
            if pre is None:
                continue
            program, mention, hidden = pre + tail, [eid], []
        claimed_ok = key not in resolver.rel_keys or bool(resolve_entities(gs, claimed))
        specs.append({"program": program, "answer": claimed, "mention": mention, "hidden": hidden,
                      "description": describe_program(gw, program), "gap": g, "key": key,
                      "claimed_resolvable": claimed_ok})
    return specs


async def verbalize(llm, spec: dict, gw: KBStore, seed: int | None = None) -> str:
    msgs = messages("verbalize", description=spec["description"], mention_names=_names(gw, spec["mention"]),
                    hidden_names=_names(gw, spec["hidden"]))
    js = extract_json(await llm.chat(msgs, seed=seed)) or {}
    return str(js.get("question", "") or "")

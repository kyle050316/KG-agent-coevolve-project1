"""Exp 2 Curator runs (prompt-based, counterfactual re-run as a tool) and Solver-level locality.

Every case flagged by T1 or T2 is given to the Curator once per ablation:
  full     diagnose + edit -> sandbox re-run returned to the model -> commit / revise / withdraw
  no_tool  diagnose + edit only (the first answer is final)
  no_docs  as full, without evidence passages (does the Curator edit from memory?)
Ablations other than 'full' run on a stratified subset of ``ablation_n`` cases.

Source gate (proposal): an edit is admitted only if it cites an evidence item that was shown and an
independent verifier confirms that the item states the new fact. Deletions are never admitted.

Usage:  python -m experiments.exp2.run --config configs/main.yaml --stages curator locality
"""

from __future__ import annotations

import asyncio
import json
import random
from collections import defaultdict

from experiments.common import parse_args, selected, setup
from experiments.exp2.build_cases import case_executor, make_solver
from kgcoevo.agents import curator as C
from kgcoevo.agents.judge import verify_entailment
from kgcoevo.agents.solver import EntityLinker
from kgcoevo.context import Context
from kgcoevo.eval.compare import match_any
from kgcoevo.kb.store import Edit
from kgcoevo.kb.trace import trace
from kgcoevo.kb.values import value_str
from kgcoevo.runner import read_jsonl, run_jsonl

STAGES = ["curator", "locality"]
TRIGGER_TEXT = {
    "t1": "the Solver's final answer does not match the answer key.",
    "t2": ("the Solver's final answer matches the answer key, but its knowledge-graph execution did not return "
           "it (the Solver answered from memory or text, not from the KG)."),
}


def X(ctx: Context) -> dict:
    return ctx.cfg["exp2"]


def out(ctx: Context, name: str):
    return ctx.work / "exp2" / f"{name}.jsonl"


def plan(ctx: Context, cases: list[dict]) -> list[dict]:
    conf = X(ctx)
    flagged = [c for c in cases if (c["t1"] or c["t2"]) and c.get("traj")]
    rng = random.Random(ctx.cfg["seed"])
    by = defaultdict(list)
    for c in flagged:
        by[c["cls"]].append(c)
    subset = []
    per = max(1, conf["ablation_n"] // max(1, len(by)))
    for cls, cs in sorted(by.items()):
        cs = cs[:]
        rng.shuffle(cs)
        subset += cs[:per]
    sub_ids = {c["case_id"] for c in subset}
    items = []
    for c in flagged:
        for a in conf["ablations"]:
            if a != "full" and c["case_id"] not in sub_ids:
                continue
            items += [{"case": c, "ablation": a, "j": j} for j in range(conf["samples"] if a == "full" else 1)]
    return items


def program_keys(traj: dict) -> set[str]:
    """Relation / attribute keys used by any of the Solver's programs (listed first among the KG facts)."""
    keys = set()
    for a in traj.get("attempts", []):
        for s in a.get("program") or []:
            if isinstance(s, dict) and s.get("function") in ("Relate", "QueryAttr", "QueryRelation", "FilterStr", "FilterNum",
                                                              "FilterYear", "FilterDate", "QueryAttrQualifier",
                                                              "QueryRelationQualifier", "SelectBetween", "SelectAmong"):
                ins = s.get("inputs") or []
                if ins:
                    keys.add(str(ins[0]))
    return keys


def claim_text(ctx: Context, edit: Edit) -> str:
    if edit.kind == "rel":
        return f"{ctx.gs.name(edit.subject)} has {edit.key}: {ctx.gs.name(edit.new_value)}."
    return f"The {edit.key} of {ctx.gs.name(edit.subject)} is {value_str(edit.new_value)}."


def tool_text(rr: dict | None, err: str = "") -> str:
    if rr is None:
        return f"The edit could not be applied to the KG: {err}"
    ex = rr["exec"] or {}
    res = ex.get("answers") if ex.get("ok") else f"ERROR {ex.get('error')}"
    return (f"After applying your edit, the Solver's program returns: {json.dumps(res, ensure_ascii=False)}.\n"
            f"The Solver's new final answer: {rr['answer']!r} (matches the answer key: {'yes' if rr['success'] else 'no'}).")


async def stage_curator(ctx: Context) -> None:
    conf = X(ctx)
    cases = read_jsonl(out(ctx, "cases"))
    llm, judge = ctx.llm("curator"), ctx.llm("judge")
    solver = make_solver(ctx)
    linker = EntityLinker(ctx.gs)
    names = {e: ctx.gs.name(e) for e in ctx.gs.entities}

    async def sandbox(case: dict, edits: list[Edit], edit: Edit, ex, seed: int) -> dict:
        rr = await solver.rerun(case["question"], case["traj"].get("program"), ex, edits + [edit], seed=seed)
        return {"exec": rr["exec"], "answer": rr["answer"], "success": match_any(rr["answer"], [case["key"]])}

    async def work(it: dict) -> dict:
        case, abl, j = it["case"], it["ablation"], it["j"]
        seed = ctx.cfg["seed"] + 31 * j
        ex, edits = case_executor(ctx, case)
        traj = case["traj"]
        ents = list(dict.fromkeys(linker(case["question"])))
        if traj.get("program"):
            tr = trace(ex, traj["program"], edits)
            if tr.ok:
                ents += [e for e in tr.entities if e not in ents]
        ents = [e for e in ents if e in ctx.gs.entities][:8]
        shown: list[str] = []
        if abl == "no_docs":
            evidence = "(none)"
        else:
            nbrs = C.live_neighbors(ex, edits, ents)  # case KG, so a deleted link is not followed
            ps = ctx.index.search(f"{case['question']} {case['key']}", conf["evidence_k"], qids=sorted(nbrs))
            shown = [p.pid for p in ps]
            evidence = "\n".join(f"[{p.pid}] {p.text}" for p in ps) or "(no passages found)"
        first = await C.diagnose(llm, question=case["question"], answer_key=case["key"],
                                 trigger=TRIGGER_TEXT["t1" if case["t1"] else "t2"],
                                 trajectory=C.render_trajectory(traj, ctx.gs),
                                 kg_facts=C.live_facts_text(ex, edits, ents, names, focus_keys=program_keys(traj)),
                                 evidence=evidence, seed=seed)
        rec = {"case_id": case["case_id"], "cls": case["cls"], "subtype": case["subtype"], "t1": case["t1"], "t2": case["t2"],
               "ablation": abl, "j": j, "shown": shown,
               "first": {k: first[k] for k in ("diagnosis", "located_fact", "edit", "confidence", "rationale", "parse_ok")},
               "tool": None, "second": None}
        proposed = first["diagnosis"] in C.DIAGNOSES[:2] and bool(first["edit"])
        edit, err = (C.build_edit(ex, ctx.gs.name_to_ids, edits, first["edit"], prefer=ents) if proposed
                     else (None, "no edit proposed"))
        rec["proposed"] = proposed
        rec["first_edit_built"], rec["first_edit_error"] = (edit.to_json() if edit else None), err
        final_js, final_edit, diagnosis = first["edit"], edit, first["diagnosis"]
        if proposed and abl != "no_tool":
            rr = None
            if edit is not None:
                try:
                    rr = await sandbox(case, edits, edit, ex, seed)
                except Exception as e:  # noqa: BLE001 - reported to the model as a failed application
                    err = f"{type(e).__name__}: {e}"
            rec["tool"] = rr if rr else {"error": err}
            second = await C.decide(llm, first, tool_text(rr, err), seed=seed)
            rec["second"] = {k: second[k] for k in ("decision", "diagnosis", "edit", "rationale", "parse_ok")}
            diagnosis = second["diagnosis"]
            if second["decision"] == "withdraw" or diagnosis not in C.DIAGNOSES[:2]:
                final_js, final_edit = None, None
            elif second["decision"] == "revise" and second["edit"]:
                final_js = second["edit"]
                final_edit, err = C.build_edit(ex, ctx.gs.name_to_ids, edits, final_js, prefer=ents)
                rec["revised_edit_error"] = err
        rec["diagnosis"] = diagnosis
        rec["final_edit"] = final_edit.to_json() if final_edit else None
        # source gate
        cited = str((final_js or {}).get("evidence_id", "") or "")
        rec["cited_ok"] = bool(final_edit) and cited in shown
        rec["verified"] = None
        if final_edit is not None and final_edit.op != "delete" and rec["cited_ok"]:
            p = ctx.index.by_id.get(cited)
            rec["verified"] = (await verify_entailment(judge, p.text, claim_text(ctx, final_edit)))["entails"] if p else False
        rec["admitted"] = bool(final_edit is not None and final_edit.op != "delete" and rec["cited_ok"] and rec["verified"])
        return rec

    await run_jsonl(plan(ctx, cases), work, out(ctx, "curator"),
                    key=lambda it: f"{it['case']['case_id']}|{it['ablation']}|{it['j']}",
                    concurrency=llm.cfg.concurrency, desc="curator")


def neighbour_questions(ctx: Context, edit: Edit, n: int) -> list[dict]:
    """KQA Pro questions whose program starts from the edited subject or object (by name)."""
    names = {ctx.gs.name(edit.subject)}
    if edit.kind == "rel" and edit.new_value in ctx.gs.entities:
        names.add(ctx.gs.name(edit.new_value))
    out_q = []
    for split in ("val", "train"):
        for i, q in enumerate(ctx.questions(split)):
            if any(s["function"] == "Find" and s["inputs"][0] in names for s in q.get("program", [])):
                out_q.append({"qid": f"{split}:{i}", **q})
                if len(out_q) >= n:
                    return out_q
    return out_q


async def stage_locality(ctx: Context) -> None:
    """Solver-level regression test of admitted edits (program-level locality is exact, in analyze)."""
    conf = X(ctx)
    if conf["solver_locality_edits"] <= 0:
        return
    cases = {c["case_id"]: c for c in read_jsonl(out(ctx, "cases"))}
    admitted = [r for r in read_jsonl(out(ctx, "curator")) if r.get("admitted") and r["ablation"] == "full" and r["j"] == 0]
    solver = make_solver(ctx)
    items = []
    for r in admitted[: conf["solver_locality_edits"]]:
        for q in neighbour_questions(ctx, Edit.from_json(r["final_edit"]), conf["solver_locality_questions"]):
            for side in ("before", "after"):
                items.append({"case_id": r["case_id"], "edit": r["final_edit"], "q": q, "side": side})

    async def work(it: dict) -> dict:
        ex, edits = case_executor(ctx, cases[it["case_id"]])
        if it["side"] == "after":
            edits = edits + [Edit.from_json(it["edit"])]
        res = await solver.solve(it["q"]["question"], ex, edits, seed=ctx.cfg["seed"])
        return {"case_id": it["case_id"], "qid": it["q"]["qid"], "side": it["side"],
                "correct": match_any(res["answer"], [it["q"]["answer"]])}

    await run_jsonl(items, work, out(ctx, "locality_solver"), key=lambda it: f"{it['case_id']}|{it['q']['qid']}|{it['side']}",
                    concurrency=ctx.llm("solver").cfg.concurrency, desc="locality")


async def run_stages(ctx: Context, args) -> None:
    for st in STAGES:
        if selected(args, st, STAGES):
            await globals()[f"stage_{st}"](ctx)


def main(llms: dict | None = None, argv_args=None) -> None:
    args = argv_args or parse_args(__doc__, STAGES)
    ctx = setup(args, "exp2.run", llms)
    asyncio.run(run_stages(ctx, args))


if __name__ == "__main__":
    main()

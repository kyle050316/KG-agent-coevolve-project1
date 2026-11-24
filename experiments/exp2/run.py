"""Exp 2 Curator runs and Solver-level locality.

Stages
  curator    every case x variant (answer key shown: gold | pipeline) x ablation
             (full | no_traj | no_sandbox | no_docs | oracle); 'full' with the gold key is
             repeated with ``samples`` seeds, the other ablations run on a stratified subset
  locality   Solver-level regression test of committed edits (program-level locality is computed
             exactly, without the LLM, in the analysis)

Commit rule (three-way gate): an edit is committed only if it cites an evidence item that was
shown, an independent verifier (judge model) says the item entails the edited fact, and the
sandbox re-run of the Solver now returns the answer key. Deletions are never committed
automatically: they are referred (text rarely states that a fact does not hold).

Usage:  python -m experiments.exp2.run --config configs/small.yaml --stages curator
"""

from __future__ import annotations

import asyncio
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


def X(ctx: Context) -> dict:
    return ctx.cfg["exp2"]


def out(ctx: Context, name: str):
    return ctx.work / "exp2" / f"{name}.jsonl"


def plan(ctx: Context, cases: list[dict]) -> list[dict]:
    conf = X(ctx)
    rng = random.Random(ctx.cfg["seed"])
    by = defaultdict(list)
    for c in cases:
        by[c["cls"]].append(c)
    subset: list[dict] = []
    per = max(1, conf["ablation_n"] // max(1, len(by)))
    for cls, cs in sorted(by.items()):
        cs = cs[:]
        rng.shuffle(cs)
        subset += cs[:per]
    sub_ids = {c["case_id"] for c in subset}
    items = []
    for c in cases:
        for v in conf["variants"]:
            for a in conf["ablations"]:
                if a != "full" and c["case_id"] not in sub_ids:
                    continue
                n = conf["samples"] if (a == "full" and v == "gold") else 1
                items += [{"case": c, "variant": v, "ablation": a, "j": j} for j in range(n)]
    return items


def claim_text(ctx: Context, edit: Edit) -> str:
    if edit.kind == "rel":
        return f"{ctx.gs.name(edit.subject)} has {edit.key}: {ctx.gs.name(edit.new_value)}."
    return f"The {edit.key} of {ctx.gs.name(edit.subject)} is {value_str(edit.new_value)}."


async def stage_curator(ctx: Context) -> None:
    conf = X(ctx)
    cases = read_jsonl(out(ctx, "cases"))
    llm, judge = ctx.llm("curator"), ctx.llm("judge")
    solver = make_solver(ctx)
    linker = EntityLinker(ctx.gs)
    names = {e: ctx.gs.name(e) for e in ctx.gs.entities}

    async def work(it: dict) -> dict:
        case, variant, abl, j = it["case"], it["variant"], it["ablation"], it["j"]
        ex, edits = case_executor(ctx, case)
        key = case["key_gold"] if variant == "gold" else case["key_pipeline"]
        traj = case["failing_traj"]
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
            nbrs = set(ents)
            for e in ents:
                nbrs |= ctx.gs.neighbors(e)
            ps = ctx.index.search(f"{case['question']} {key}", conf["evidence_k"], qids=sorted(nbrs))
            shown = [p.pid for p in ps]
            evidence = "\n".join(f"[{p.pid}] {p.text}" for p in ps) or "(no passages found)"
        if abl == "oracle":
            ref = [f"REF: {ctx.gs.fact_text(f)}" for e in ents for f in ctx.gs.facts_of(e, ("attr", "rel"))][:80]
            evidence += "\n\nReference KG facts (authoritative; cite as REF):\n" + "\n".join(ref)
            shown.append("REF")
        diag = await C.diagnose(llm, question=case["question"], answer_key=key,
                                trajectory=C.render_trajectory(traj, ctx.gs) if abl != "no_traj" else "(not available)",
                                kg_facts=C.live_facts_text(ex, edits, ents, names), evidence=evidence,
                                seed=ctx.cfg["seed"] + 31 * j)
        rec = {"case_id": case["case_id"], "cls": case["cls"], "variant": variant, "ablation": abl, "j": j,
               **{k: diag[k] for k in ("diagnosis", "located_fact", "edit", "confidence", "rationale", "parse_ok")},
               "shown": shown, "edit_built": None, "edit_error": "", "cited_ok": False, "verified": None,
               "sandbox": None, "commit": False}
        if diag["diagnosis"] not in ("missing_fact", "wrong_fact") or not isinstance(diag["edit"], dict):
            return rec
        edit, err = C.build_edit(ex, ctx.gs.name_to_ids, edits, diag["edit"], prefer=ents)
        rec["edit_built"], rec["edit_error"] = (edit.to_json() if edit else None), err
        if edit is None:
            return rec
        cited = str(diag["edit"].get("evidence_id", "") or "")
        rec["cited_ok"] = cited in shown
        if edit.op != "delete" and rec["cited_ok"]:
            if cited == "REF":
                rec["verified"] = True
            else:
                p = ctx.index.by_id.get(cited)
                rec["verified"] = (await verify_entailment(judge, p.text, claim_text(ctx, edit)))["entails"] if p else False
        if abl != "no_sandbox":
            try:
                rr = await solver.rerun(case["question"], traj.get("program"), ex, edits + [edit],
                                        seed=ctx.cfg["seed"] + 31 * j)
                rec["sandbox"] = {"answer": rr["answer"], "exec": rr["exec"], "success": match_any(rr["answer"], [key])}
            except Exception as e:  # noqa: BLE001 - an edit that cannot be applied fails the sandbox
                rec["sandbox"] = {"answer": "", "exec": None, "success": False, "error": str(e)}
        sandbox_ok = abl == "no_sandbox" or bool(rec["sandbox"] and rec["sandbox"]["success"])
        rec["commit"] = bool(edit.op != "delete" and rec["cited_ok"] and rec["verified"] and sandbox_ok)
        rec["reward_hacking_candidate"] = bool(rec["sandbox"] and rec["sandbox"]["success"]
                                               and not (rec["cited_ok"] and rec["verified"]))
        return rec

    await run_jsonl(plan(ctx, cases), work, out(ctx, "curator"),
                    key=lambda it: f"{it['case']['case_id']}|{it['variant']}|{it['ablation']}|{it['j']}",
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
    conf = X(ctx)
    cases = {c["case_id"]: c for c in read_jsonl(out(ctx, "cases"))}
    commits = [r for r in read_jsonl(out(ctx, "curator")) if r.get("commit") and r["variant"] == "gold"
               and r["ablation"] == "full" and r["j"] == 0]
    commits = commits[: conf["solver_locality_edits"]]
    solver = make_solver(ctx)
    items = []
    for r in commits:
        edit = Edit.from_json(r["edit_built"])
        for q in neighbour_questions(ctx, edit, conf.get("solver_locality_questions", 30)):
            for side in ("before", "after"):
                items.append({"case_id": r["case_id"], "edit": r["edit_built"], "q": q, "side": side})

    async def work(it: dict) -> dict:
        case = cases[it["case_id"]]
        ex, edits = case_executor(ctx, case)
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

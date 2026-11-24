"""Exp 1 runs (LLM stages need the vLLM server; 'checks' is CPU only).

Stages (run in this order; every stage is resumable):
  probe      C0: closed-book probe of every supported fact of region A (k samples)
  mode_a     Challenger on the shared paths (defective + clean) under B0/C1/C1know/C2/C3
  mode_b     Challenger gap reports per entity under C1/C1know/C2/C3
  gap_tasks  compile reported gaps into tasks and verbalise them
  checks     E0-E5 for every task (official KoPL engine on Gw and G*)
  judge      LLM-judge faithfulness (E3) on every rule-valid task
  solver     Solver on Gw / G* / closed-book, k samples, for a sample of valid tasks per condition and source

Usage:  python -m experiments.exp1.run --config configs/main.yaml --stages mode_a mode_b
"""

from __future__ import annotations

import asyncio
import random

from experiments.common import parse_args, selected, setup
from kgcoevo.agents import challenger
from kgcoevo.agents.evidence import EvidenceBuilder
from kgcoevo.agents.judge import judge_faithfulness
from kgcoevo.agents.solver import FewShotPool, Solver
from kgcoevo.context import Context
from kgcoevo.eval.checks import check_task
from kgcoevo.eval.discovery import KeyResolver
from kgcoevo.llm.parsing import extract_json
from kgcoevo.llm.prompts import messages
from kgcoevo.runner import read_jsonl, run_jsonl, write_jsonl

STAGES = ["probe", "mode_a", "mode_b", "gap_tasks", "checks", "judge", "solver"]


def E(ctx: Context) -> dict:
    return ctx.cfg["exp1"]


def out(ctx: Context, name: str):
    return ctx.work / "exp1" / f"{name}.jsonl"


def main_rate(ctx: Context) -> float:
    return ctx.cfg["defects"]["rate"]


def seeds(ctx: Context) -> list[int]:
    return ctx.cfg["defects"]["seeds"]


def builder(ctx: Context, seed: int) -> EvidenceBuilder:
    ev = E(ctx)["evidence"]
    return EvidenceBuilder(ctx.gs, ctx.gw(main_rate(ctx), seed), ctx.index, support=ctx.support,
                           defects=ctx.defects(main_rate(ctx), seed), k_per_fact=ev["k_per_fact"],
                           mode_b_distractors=ev["mode_b_distractors"], vocab_entities=ctx.region["A"])


async def stage_probe(ctx: Context) -> None:
    if not E(ctx)["probe"].get("enabled", True):
        print("[probe] C0 closed-book probe disabled (exp1.probe.enabled=false)")
        return
    llm = ctx.llm("challenger")
    k = E(ctx)["probe"]["k"]
    items = [{**it, "j": j} for it in read_jsonl(ctx.data / "probe_items.jsonl") for j in range(k)]

    async def work(it: dict) -> dict:
        msgs = messages("probe", entity=ctx.gs.describe(it["entity"]), key=it["key"], qualifier_note=it["qualifier_note"])
        raw = await llm.chat(msgs, seed=ctx.cfg["seed"] + it["j"])
        js = extract_json(raw) or {}
        return {"item_id": it["item_id"], "j": it["j"], "answer": str(js.get("answer", "")), "raw": raw}

    await run_jsonl(items, work, out(ctx, "probe"), key=lambda it: f"{it['item_id']}|{it['j']}",
                    concurrency=llm.cfg.concurrency, desc="probe")


async def stage_mode_a(ctx: Context) -> None:
    llm = ctx.llm("challenger")
    conf = E(ctx)["mode_a"]
    for seed in seeds(ctx):
        gw = ctx.gw(main_rate(ctx), seed)
        evb = builder(ctx, seed)
        paths = ctx.paths(main_rate(ctx), seed)
        items = [{"cond": c, "seed": seed, "path": p, "j": j} for c in conf["conditions"] for p in paths
                 for j in range(conf.get("samples", 1))]

        async def work(it: dict) -> dict:
            s = ctx.cfg["seed"] + 7919 * it["j"] + it["seed"]
            return await challenger.mode_a(llm, it["path"], it["cond"], evb, gw, seed=s) | {"j": it["j"], "seed": it["seed"]}

        await run_jsonl(items, work, out(ctx, "mode_a"), key=lambda it: f"{it['cond']}|{it['seed']}|{it['path']['path_id']}|{it['j']}",
                        concurrency=llm.cfg.concurrency, desc=f"mode_a seed{seed}")


def mode_b_entities(ctx: Context) -> list[str]:
    ents = list(ctx.region["A"])
    random.Random(ctx.cfg["seed"]).shuffle(ents)
    return sorted(ents[: E(ctx)["mode_b"]["n_entities"]])


async def stage_mode_b(ctx: Context) -> None:
    llm = ctx.llm("challenger")
    conf = E(ctx)["mode_b"]
    for seed in seeds(ctx):
        gw = ctx.gw(main_rate(ctx), seed)
        evb = builder(ctx, seed)
        items = [{"cond": c, "seed": seed, "eid": e, "j": j} for c in conf["conditions"] for e in mode_b_entities(ctx)
                 for j in range(conf.get("samples", 1))]

        async def work(it: dict) -> dict:
            s = ctx.cfg["seed"] + 7919 * it["j"] + it["seed"]
            return await challenger.mode_b(llm, it["eid"], it["cond"], evb, gw, seed=s) | {"j": it["j"], "seed": it["seed"]}

        await run_jsonl(items, work, out(ctx, "mode_b"), key=lambda it: f"{it['cond']}|{it['seed']}|{it['eid']}|{it['j']}",
                        concurrency=llm.cfg.concurrency, desc=f"mode_b seed{seed}")


async def stage_gap_tasks(ctx: Context) -> None:
    llm = ctx.llm("challenger")
    resolver = KeyResolver(ctx.gs)
    items = []
    for r in read_jsonl(out(ctx, "mode_b")):
        if "error" in r:
            continue
        gw = ctx.gw(main_rate(ctx), r["seed"])
        specs = challenger.gap_task_specs(gw, ctx.gs, resolver, r["entity"], r["gaps"],
                                          E(ctx)["gap_tasks"]["max_per_entity"], seed=ctx.cfg["seed"])
        for k, sp in enumerate(specs):
            items.append({"task_id": f"gap|{r['condition']}|{r['seed']}|{r['entity']}|{r['j']}|{k}", "condition": r["condition"],
                          "seed": r["seed"], "entity": r["entity"], "spec": sp})

    async def work(it: dict) -> dict:
        gw = ctx.gw(main_rate(ctx), it["seed"])
        q = await challenger.verbalize(llm, it["spec"], gw, seed=ctx.cfg["seed"])
        return {**it, "question": q}

    await run_jsonl(items, work, out(ctx, "gap_tasks"), key=lambda it: it["task_id"], concurrency=llm.cfg.concurrency,
                    desc="gap_tasks")


def stage_checks(ctx: Context) -> None:
    rows = []
    paths = {(s, p["path_id"]): p for s in seeds(ctx) for p in ctx.paths(main_rate(ctx), s)}
    for r in read_jsonl(out(ctx, "mode_a")):
        if "error" in r or r["decision"] not in ("accept", "correct"):
            continue
        p = paths[(r["seed"], r["path_id"])]
        gw = ctx.gw(main_rate(ctx), r["seed"])
        rows.append({"task_id": f"A|{r['condition']}|{r['seed']}|{r['path_id']}|{r['j']}", "source": "mode_a",
                     "condition": r["condition"], "seed": r["seed"], "path_id": r["path_id"], "cluster": p["anchor"],
                     "decision": r["decision"], "question": r["question"], "program": p["program"],
                     "answer": r["answer"], "kg_e1": "gw", "e2_applicable": r["decision"] == "accept",
                     "mention_names": [gw.name(e) for e in p["mention"]], "hidden_names": [gw.name(e) for e in p["hidden"]],
                     "description": p["description"], "exposed": p["exposed"], "path_answer_affecting": p["answer_affecting"],
                     "group": p.get("group", ""), "hops": p["hops"], "ptype": p["ptype"]})
    for r in read_jsonl(out(ctx, "gap_tasks")):
        if "error" in r:
            continue
        sp = r["spec"]
        gw = ctx.gw(main_rate(ctx), r["seed"])
        rows.append({"task_id": r["task_id"], "source": "gap", "condition": r["condition"], "seed": r["seed"],
                     "cluster": r["entity"], "decision": "gap", "question": r["question"], "program": sp["program"],
                     "answer": sp["answer"], "kg_e1": "gstar", "e2_applicable": False,
                     "mention_names": [gw.name(e) for e in sp["mention"]], "hidden_names": [gw.name(e) for e in sp["hidden"]],
                     "description": sp["description"], "hops": len([s for s in sp["program"] if s["function"] == "Relate"]) + 1})
    out_rows = []
    for t in rows:
        chk = check_task(t, ctx.gw_exec(main_rate(ctx), t["seed"]), ctx.gs_exec)
        out_rows.append({**t, **chk})
    write_jsonl(out_rows, out(ctx, "tasks"))
    n_valid = sum(r["valid"] for r in out_rows)
    print(f"[checks] {len(out_rows)} tasks, {n_valid} valid by E0-E4 + E3 rules")


async def stage_judge(ctx: Context) -> None:
    llm = ctx.llm("judge")
    tasks = [t for t in read_jsonl(out(ctx, "tasks")) if t.get("e0") and t.get("e1") and t.get("e2") is not False]
    rng = random.Random(ctx.cfg["seed"])
    rng.shuffle(tasks)
    tasks = tasks[: E(ctx)["judge"].get("max_tasks")]  # None = judge every task

    async def work(t: dict) -> dict:
        res = await judge_faithfulness(llm, t["description"], t["question"], t["answer"])
        return {"task_id": t["task_id"], **res}

    await run_jsonl(tasks, work, out(ctx, "judge"), key=lambda t: t["task_id"], concurrency=llm.cfg.concurrency, desc="judge")


async def stage_solver(ctx: Context) -> None:
    conf = E(ctx)["solver"]
    llm = ctx.llm("solver")
    train = ctx.questions("train")
    random.Random(0).shuffle(train)
    solver = Solver(llm, ctx.gs, FewShotPool(train[: conf["fewshot_pool"]]), max_attempts=conf["max_attempts"])
    judged = {r["task_id"]: r for r in read_jsonl(out(ctx, "judge"))}
    valid = [t for t in read_jsonl(out(ctx, "tasks")) if t["valid"] and judged.get(t["task_id"], {}).get("faithful") is not False]
    rng = random.Random(ctx.cfg["seed"])
    picked = []  # n_per_group tasks for each (condition, source): Mode A tasks and gap tasks separately
    for cond, src in sorted({(t["condition"], t["source"]) for t in valid}):
        group = [t for t in valid if t["condition"] == cond and t["source"] == src]
        rng.shuffle(group)
        picked += group[: conf["n_per_group"]]
    items = [{"task": t, "setting": s, "j": j} for t in picked for s in conf["settings"] for j in range(conf["k"])]

    async def work(it: dict) -> dict:
        t, s, j = it["task"], it["setting"], it["j"]
        seed = ctx.cfg["seed"] + 104729 * j
        if s == "closed":
            res = await solver.closed_book(t["question"], seed=seed)
        else:
            ex = ctx.gw_exec(main_rate(ctx), t["seed"]) if s == "gw" else ctx.gs_exec
            res = await solver.solve(t["question"], ex, seed=seed)
        return {"task_id": t["task_id"], "condition": t["condition"], "setting": s, "j": j, **res}

    await run_jsonl(items, work, out(ctx, "solver"), key=lambda it: f"{it['task']['task_id']}|{it['setting']}|{it['j']}",
                    concurrency=llm.cfg.concurrency, desc="solver")


async def run_stages(ctx: Context, args) -> None:
    for st in STAGES:
        if selected(args, st, STAGES):
            res = globals()[f"stage_{st}"](ctx)
            if asyncio.iscoroutine(res):
                await res  # one event loop for all stages (clients are loop-bound)


def main(llms: dict | None = None, argv_args=None) -> None:
    args = argv_args or parse_args(__doc__, STAGES)
    ctx = setup(args, "exp1.run", llms)
    asyncio.run(run_stages(ctx, args))
    write_jsonl([{"usage": ctx.usage()}], ctx.work / "exp1" / "usage_last_run.jsonl")


if __name__ == "__main__":
    main()

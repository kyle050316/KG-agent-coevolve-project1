"""Exp 2 case construction (needs the Solver LLM).

Protocol (IKGQA-style defect injection on gold paths, Generate-on-Graph; stable labels by
repeated sampling):
  pool    KQA Pro train/val questions anchored on region-B entities whose official program is
          traceable on G* and whose engine answer equals the gold answer; the Solver answers each
          k times on G* -> stably correct (>= stable_hi) / stably wrong (<= stable_lo)
  cases   six classes; KG classes are kept only if the injected defect makes the Solver fail
          stably (<= stable_lo on the defective KG):
            missing_fact     supported gold-path fact deleted
            wrong_fact       supported gold-path fact corrupted (type-consistent)
            refer            unsupported gold-path fact deleted/corrupted (no evidence settles it)
            non_kg           stably wrong on intact G*, matched to KG cases on program features
            non_kg_offpath   stably wrong question + a defect on the same entities but off the path
            invalid_task     Exp 1 tasks with a contaminated answer key that the Solver contradicts

Usage:  python -m experiments.exp2.build_cases --config configs/small.yaml --stages pool cases
"""

from __future__ import annotations

import asyncio
import math
import random
from collections import Counter, defaultdict

from experiments.common import parse_args, selected, setup
from kgcoevo.agents.solver import FewShotPool, Solver
from kgcoevo.context import Context
from kgcoevo.data.defects import make_defect
from kgcoevo.eval.compare import answers_equal, match_any
from kgcoevo.kb.store import Edit
from kgcoevo.kb.trace import trace
from kgcoevo.runner import read_jsonl, run_jsonl, write_jsonl

STAGES = ["pool", "cases"]
KG_CLASSES = ("missing_fact", "wrong_fact", "refer")


def X(ctx: Context) -> dict:
    return ctx.cfg["exp2"]


def out(ctx: Context, name: str):
    return ctx.work / "exp2" / f"{name}.jsonl"


def make_solver(ctx: Context) -> Solver:
    train = ctx.questions("train")
    random.Random(0).shuffle(train)
    conf = ctx.cfg["exp1"]["solver"]
    return Solver(ctx.llm("solver"), ctx.gs, FewShotPool(train[: conf["fewshot_pool"]]), max_attempts=conf["max_attempts"])


def features(program: list[dict]) -> dict:
    funcs = [s["function"] for s in program]
    return {"program_len": len(program), "hops": funcs.count("Relate"), "funcs": "-".join(sorted(set(funcs)))}


def candidate_questions(ctx: Context) -> list[dict]:
    B = set(ctx.region["B"])
    out_rows = []
    for split in ("train", "val"):
        for i, q in enumerate(ctx.questions(split)):
            prog = q.get("program")
            if not prog:
                continue
            anchors = [e for s in prog if s["function"] == "Find" for e in ctx.gs.name_to_ids.get(s["inputs"][0], []) if e in B]
            if not anchors:
                continue
            tr = trace(ctx.gs_exec, prog)
            if not tr.ok or len(tr.answers) != 1 or not tr.facts or not answers_equal(tr.answers[0], q["answer"]):
                continue
            prog = [{"function": s["function"], "inputs": s.get("inputs", [])} for s in prog]
            out_rows.append({"qid": f"{split}:{i}", "question": q["question"], "answer": q["answer"], "program": prog,
                             "path": tr.facts, "path_entities": tr.entities, "anchor": anchors[0], **features(prog)})
    rng = random.Random(ctx.cfg["seed"])
    rng.shuffle(out_rows)
    return out_rows[: X(ctx)["pool_size"]]


async def stage_pool(ctx: Context) -> None:
    pool = candidate_questions(ctx)
    write_jsonl(pool, out(ctx, "pool"))
    solver = make_solver(ctx)
    k = X(ctx)["k"]
    items = [{"q": q, "j": j} for q in pool for j in range(k)]

    async def work(it: dict) -> dict:
        res = await solver.solve(it["q"]["question"], ctx.gs_exec, seed=ctx.cfg["seed"] + 104729 * it["j"])
        return {"qid": it["q"]["qid"], "j": it["j"], "correct": match_any(res["answer"], [it["q"]["answer"]]), "traj": res}

    await run_jsonl(items, work, out(ctx, "pool_solver"), key=lambda it: f"{it['q']['qid']}|{it['j']}",
                    concurrency=ctx.llm("solver").cfg.concurrency, desc="exp2 pool")


def _acc(rows: list[dict]) -> dict[str, float]:
    by = defaultdict(list)
    for r in rows:
        if "error" not in r:
            by[r["qid"]].append(int(r["correct"]))
    return {q: sum(v) / len(v) for q, v in by.items()}


def _kg_candidates(ctx: Context, stable_correct: list[dict], rng: random.Random) -> list[dict]:
    """Assign stably-correct questions to KG classes round-robin and inject one defect each."""
    conf = X(ctx)
    support = {r["fid"]: r for r in ctx.support}
    functional = ctx.gs.functional_keys()
    quota = {c: math.ceil(conf["targets"][c] * conf.get("oversample", 2.0)) for c in KG_CLASSES}
    cands = []
    order = list(KG_CLASSES)
    for q in stable_correct:
        fids = [ctx.gs.cid_to_fid.get(f["cid"]) for f in q["path"]]
        fids = [f for f in fids if f]
        sup = [f for f in fids if support.get(f, {}).get("supported")]
        uns = [f for f in fids if f in support and not support[f]["supported"]]
        for cls in order:
            if quota[cls] <= 0:
                continue
            pool = uns if cls == "refer" else sup
            if not pool:
                continue
            fid = rng.choice(pool)
            op = "delete" if cls == "missing_fact" else "corrupt" if cls == "wrong_fact" else rng.choice(["delete", "corrupt"])
            d = make_defect(ctx.gs, ctx.gs.facts[fid], op, rng, "similar", functional, support, f"x{len(cands):05d}")
            if d is None:
                continue
            quota[cls] -= 1
            cands.append({"cand_id": f"{cls}|{q['qid']}", "cls": cls, "q": q, "defect": d.to_json(), "edits": [d.edit],
                          "kg": {"type": "gstar"}, "key_gold": q["answer"], "key_pipeline": q["answer"]})
            order = order[1:] + order[:1]  # rotate so classes share questions fairly
            break
    return cands


def _offpath_candidates(ctx: Context, wrong: list[dict], n: int, rng: random.Random) -> list[dict]:
    support = {r["fid"]: r for r in ctx.support}
    functional = ctx.gs.functional_keys()
    cands = []
    for q in wrong:
        if len(cands) >= n:
            break
        on_path = {f["cid"] for f in q["path"]}
        pool = [r["fid"] for r in ctx.support if r["supported"] and r["subject"] in set(q["path_entities"])
                and r["cid"] not in on_path and ctx.gs.facts[r["fid"]].kind != "qual"]
        if not pool:
            continue
        fid = rng.choice(pool)
        d = make_defect(ctx.gs, ctx.gs.facts[fid], rng.choice(["delete", "corrupt"]), rng, "similar", functional, support,
                        f"o{len(cands):05d}")
        if d:
            cands.append({"cand_id": f"non_kg_offpath|{q['qid']}", "cls": "non_kg_offpath", "q": q, "defect": d.to_json(),
                          "edits": [d.edit], "kg": {"type": "gstar"}, "key_gold": q["answer"], "key_pipeline": q["answer"]})
    return cands


def _invalid_candidates(ctx: Context, n: int, rng: random.Random) -> list[dict]:
    """Exp 1 tasks whose (valid) answer key is contaminated by a KG defect."""
    p = ctx.work / "exp1" / "tasks.jsonl"
    rows = [t for t in read_jsonl(p) if t.get("valid") and t.get("contaminated") and t.get("gs_answers")]
    rng.shuffle(rows)
    cands = []
    for t in rows[: n * 2]:
        q = {"qid": t["task_id"], "question": t["question"], "answer": t["gs_answers"][0], "program": t["program"],
             "path": [], "path_entities": [], **features(t["program"])}
        cands.append({"cand_id": f"invalid_task|{t['task_id']}", "cls": "invalid_task", "q": q, "defect": None, "edits": [],
                      "kg": {"type": "gw", "rate": ctx.cfg["defects"]["main_rate"], "seed": t["seed"]},
                      "key_gold": t["gs_answers"][0], "key_pipeline": t["answer"]})
    return cands


def case_executor(ctx: Context, case: dict):
    kg = case["kg"]
    ex = ctx.gs_exec if kg["type"] == "gstar" else ctx.gw_exec(kg["rate"], kg["seed"])
    return ex, [Edit.from_json(e) for e in case["edits"]]


def _match(source: list[dict], targets: list[tuple], n: int) -> list[dict]:
    """Greedy matching of non-KG questions to KG cases on (function set, hops); fill by program length."""
    want = Counter(targets)
    chosen, rest = [], []
    for q in source:
        k = (q["funcs"], q["hops"])
        if want[k] > 0 and len(chosen) < n:
            chosen.append(q)
            want[k] -= 1
        else:
            rest.append(q)
    rest.sort(key=lambda q: q["program_len"])
    return chosen + rest[: max(0, n - len(chosen))]


async def stage_cases(ctx: Context) -> None:
    conf = X(ctx)
    rng = random.Random(ctx.cfg["seed"])
    pool = {q["qid"]: q for q in read_jsonl(out(ctx, "pool"))}
    pool_runs = read_jsonl(out(ctx, "pool_solver"))
    acc = _acc(pool_runs)
    stable_correct = [pool[q] for q, a in acc.items() if a >= conf["stable_hi"]]
    stable_wrong = [pool[q] for q, a in acc.items() if a <= conf["stable_lo"]]
    rng.shuffle(stable_correct)
    rng.shuffle(stable_wrong)
    fail_traj = {}
    for r in pool_runs:
        if "error" not in r and not r["correct"]:
            fail_traj.setdefault(r["qid"], r["traj"])

    kg_cands = _kg_candidates(ctx, stable_correct, rng)
    n_off = math.ceil(conf["targets"]["non_kg_offpath"] * conf.get("oversample", 2.0))
    half = len(stable_wrong) // 2
    off_cands = _offpath_candidates(ctx, stable_wrong[half:], n_off, rng)
    inv_cands = _invalid_candidates(ctx, conf["targets"]["invalid_task"], rng)
    cands = kg_cands + off_cands + inv_cands
    solver = make_solver(ctx)
    k = conf["k"]
    items = [{"c": c, "j": j} for c in cands for j in range(k)]

    async def work(it: dict) -> dict:
        c = it["c"]
        ex, edits = case_executor(ctx, c)
        res = await solver.solve(c["q"]["question"], ex, edits, seed=ctx.cfg["seed"] + 7 + 104729 * it["j"])
        key = c["key_pipeline"]
        return {"cand_id": c["cand_id"], "j": it["j"], "correct_vs_key": match_any(res["answer"], [key]), "traj": res}

    runs = await run_jsonl(items, work, out(ctx, "case_validation"), key=lambda it: f"{it['c']['cand_id']}|{it['j']}",
                           concurrency=ctx.llm("solver").cfg.concurrency, desc="exp2 cases")
    by = defaultdict(list)
    for r in runs:
        if "error" not in r:
            by[r["cand_id"]].append(r)

    cases, taken = [], Counter()
    for c in cands:
        rs = by.get(c["cand_id"], [])
        if not rs:
            continue
        a = sum(r["correct_vs_key"] for r in rs) / len(rs)
        if a > conf["stable_lo"] or taken[c["cls"]] >= conf["targets"][c["cls"]]:
            continue
        failing = next(r["traj"] for r in rs if not r["correct_vs_key"])
        cases.append(_case(c, failing, a))
        taken[c["cls"]] += 1
    # non-KG cases, matched on program features to the KG cases
    kg_cases = [c for c in cases if c["cls"] in KG_CLASSES]
    feats = [(c["features"]["funcs"], c["features"]["hops"]) for c in kg_cases]
    for q in _match(stable_wrong[:half], feats, conf["targets"]["non_kg"]):
        if q["qid"] in fail_traj:
            c = {"cand_id": f"non_kg|{q['qid']}", "cls": "non_kg", "q": q, "defect": None, "edits": [], "kg": {"type": "gstar"},
                 "key_gold": q["answer"], "key_pipeline": q["answer"]}
            cases.append(_case(c, fail_traj[q["qid"]], acc[q["qid"]]))
            taken["non_kg"] += 1
    write_jsonl(cases, out(ctx, "cases"))
    print("[cases]", dict(taken), "targets:", conf["targets"])


def _case(c: dict, failing: dict, acc_case: float) -> dict:
    q = c["q"]
    return {"case_id": c["cand_id"], "cls": c["cls"], "question": q["question"], "gold_answer": q["answer"],
            "program_gold": q["program"], "gold_path": q["path"], "path_entities": q["path_entities"],
            "key_gold": c["key_gold"], "key_pipeline": c["key_pipeline"], "kg": c["kg"], "edits": c["edits"],
            "defect": c["defect"], "failing_traj": failing, "solver_acc_case": acc_case,
            "features": {"program_len": q["program_len"], "hops": q["hops"], "funcs": q["funcs"]}}


async def run_stages(ctx: Context, args) -> None:
    for st in STAGES:
        if selected(args, st, STAGES):
            await globals()[f"stage_{st}"](ctx)


def main(llms: dict | None = None, argv_args=None) -> None:
    args = argv_args or parse_args(__doc__, STAGES)
    ctx = setup(args, "exp2.build_cases", llms)
    asyncio.run(run_stages(ctx, args))


if __name__ == "__main__":
    main()

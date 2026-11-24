"""Exp 2 case construction (needs the Solver LLM).

Three classes, one sandboxed defect per KG case (IKGQA protocol: delete/corrupt a gold-path triple,
Generate-on-Graph). Only attr/rel facts that the documents state (in S) and that a single-fact edit
can restore are used:

  missing_fact  a gold-path fact stated by the documents (in S) is deleted
  wrong_fact    such a fact is corrupted with a plausible value (type-consistent)
  non_kg        the KG is intact; subtype "wrong": the Solver is stably wrong on G*;
                subtype "ungrounded": the Solver is stably right but its KG execution does not
                return the answer (it answered from memory with a wrong program)

KG cases are kept whether or not the Solver still answers correctly. Each case records two triggers
(computed from k Solver samples on the case KG):
  T1  answer-based: the final answer is stably wrong (<= stable_lo), as in the original design
  T2  grounding-based: the KG execution stably does not return the answer key (<= stable_lo)
"visible" KG cases are caught by T1; "silent" ones (the Solver answers from memory) only by T2.

Stages
  pool   KQA Pro train/val questions anchored on region B, traceable chain programs whose engine
         answer equals the gold answer; the Solver answers each k times on G*
  cases  build the three classes and run the Solver k times on every KG case

Usage:  python -m experiments.exp2.build_cases --config configs/main.yaml --stages pool cases
"""

from __future__ import annotations

import asyncio
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
KG_CLASSES = ("missing_fact", "wrong_fact")
QUAL_FUNCS = {"QFilterStr", "QFilterNum", "QFilterYear", "QFilterDate", "QueryAttrQualifier", "QueryRelationQualifier"}


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


def grounded(traj: dict, key: str) -> bool:
    """Does the Solver's KG execution return the answer key?"""
    ex = traj.get("exec") or {}
    return bool(ex.get("ok")) and match_any(key, ex.get("answers", []))


def candidate_questions(ctx: Context) -> list[dict]:
    B = set(ctx.region["B"])
    rows = []
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
            rows.append({"qid": f"{split}:{i}", "question": q["question"], "answer": q["answer"], "program": prog,
                         "path": tr.facts, "path_entities": tr.entities, "anchor": anchors[0], **features(prog)})
    random.Random(ctx.cfg["seed"]).shuffle(rows)
    return rows[: X(ctx)["pool_size"]]


async def stage_pool(ctx: Context) -> None:
    pool = candidate_questions(ctx)
    write_jsonl(pool, out(ctx, "pool"))
    print(f"[pool] {len(pool)} traceable questions on region B")
    solver = make_solver(ctx)
    items = [{"q": q, "j": j} for q in pool for j in range(X(ctx)["k"])]

    async def work(it: dict) -> dict:
        res = await solver.solve(it["q"]["question"], ctx.gs_exec, seed=ctx.cfg["seed"] + 104729 * it["j"])
        return {"qid": it["q"]["qid"], "j": it["j"], "correct": match_any(res["answer"], [it["q"]["answer"]]),
                "grounded": grounded(res, it["q"]["answer"]), "traj": res}

    await run_jsonl(items, work, out(ctx, "pool_solver"), key=lambda it: f"{it['q']['qid']}|{it['j']}",
                    concurrency=ctx.llm("solver").cfg.concurrency, desc="exp2 pool")


def _rates(rows: list[dict]) -> dict[str, tuple[float, float]]:
    by = defaultdict(list)
    for r in rows:
        if "error" not in r:
            by[r["qid"]].append((int(r["correct"]), int(r["grounded"])))
    return {q: (sum(a for a, _ in v) / len(v), sum(g for _, g in v) / len(v)) for q, v in by.items()}


def repairable(ctx: Context, fid: str, program: list[dict]) -> bool:
    """The Curator edits single attr/rel facts without qualifiers, so the defect must be repairable that way:
    no qualifier facts, and no facts whose qualifiers the gold program reads."""
    f = ctx.gs.facts[fid]
    if f.kind not in ("attr", "rel"):
        return False
    return not (f.qualifiers and any(s["function"] in QUAL_FUNCS for s in program))


def _kg_candidates(ctx: Context, base: list[dict], rng: random.Random) -> list[dict]:
    """One defect per question, alternating missing/wrong, on a supported, repairable gold-path fact."""
    conf = X(ctx)
    support = {r["fid"]: r for r in ctx.support}
    functional = ctx.gs.functional_keys()
    quota = {c: conf["targets"][c] for c in KG_CLASSES}
    order = list(KG_CLASSES)
    cands = []
    for q in base:
        if all(v <= 0 for v in quota.values()):
            break
        fids = [ctx.gs.cid_to_fid.get(f["cid"]) for f in q["path"]]
        sup = [f for f in fids if f and support.get(f, {}).get("supported") and repairable(ctx, f, q["program"])]
        if not sup:
            continue
        for cls in order:
            if quota[cls] <= 0:
                continue
            op = "delete" if cls == "missing_fact" else "corrupt"
            d = make_defect(ctx.gs, ctx.gs.facts[rng.choice(sup)], op, rng, "similar", functional, support,
                            f"x{len(cands):05d}")
            if d is None:
                continue
            quota[cls] -= 1
            cands.append({"case_id": f"{cls}|{q['qid']}", "cls": cls, "q": q, "defect": d.to_json(), "edits": [d.edit]})
            order = order[1:] + order[:1]
            break
    return cands


def case_executor(ctx: Context, case: dict):
    return ctx.gs_exec, [Edit.from_json(e) for e in case["edits"]]


def _pick_traj(samples: list[dict], t1: bool) -> dict | None:
    """Trajectory shown to the Curator: a wrong answer for T1 cases, otherwise an ungrounded one."""
    if t1:
        pref = [s for s in samples if not s["correct"] and not s["grounded"]] or [s for s in samples if not s["correct"]]
    else:
        pref = [s for s in samples if s["correct"] and not s["grounded"]] or [s for s in samples if not s["grounded"]]
    return pref[0]["traj"] if pref else None


def _case(c: dict, samples: list[dict], conf: dict, subtype: str | None = None) -> dict:
    q = c["q"]
    acc = sum(s["correct"] for s in samples) / len(samples)
    gr = sum(s["grounded"] for s in samples) / len(samples)
    t1, t2 = acc <= conf["stable_lo"], gr <= conf["stable_lo"]
    if subtype is None:
        subtype = "visible" if acc <= conf["stable_lo"] else "silent" if acc >= conf["stable_hi"] else "mixed"
    return {"case_id": c["case_id"], "cls": c["cls"], "subtype": subtype, "t1": t1, "t2": t2,
            "solver_acc": acc, "solver_grounded": gr, "question": q["question"], "gold_answer": q["answer"],
            "key": q["answer"], "program_gold": q["program"], "gold_path": q["path"], "path_entities": q["path_entities"],
            "edits": c.get("edits", []), "defect": c.get("defect"), "traj": _pick_traj(samples, t1) if (t1 or t2) else None,
            "features": {"program_len": q["program_len"], "hops": q["hops"], "funcs": q["funcs"]}}


def _match(source: list[dict], targets: list[tuple], n: int) -> list[dict]:
    """Greedy matching on (function set, hops), then fill by program length."""
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
    pool_runs = [r for r in read_jsonl(out(ctx, "pool_solver")) if "error" not in r]
    rates = _rates(pool_runs)
    hi, lo = conf["stable_hi"], conf["stable_lo"]
    base = [pool[q] for q, (a, g) in rates.items() if a >= hi and g >= hi]  # stably right AND grounded on G*
    wrong = [pool[q] for q, (a, g) in rates.items() if a <= lo]
    ungrounded = [pool[q] for q, (a, g) in rates.items() if a >= hi and g <= lo]
    for lst in (base, wrong, ungrounded):
        rng.shuffle(lst)

    cands = _kg_candidates(ctx, base, rng)
    solver = make_solver(ctx)
    k = conf["k"]
    items = [{"c": c, "j": j} for c in cands for j in range(k)]

    async def work(it: dict) -> dict:
        c = it["c"]
        ex, edits = case_executor(ctx, c)
        res = await solver.solve(c["q"]["question"], ex, edits, seed=ctx.cfg["seed"] + 7 + 104729 * it["j"])
        key = c["q"]["answer"]
        return {"case_id": c["case_id"], "j": it["j"], "correct": match_any(res["answer"], [key]),
                "grounded": grounded(res, key), "traj": res}

    runs = await run_jsonl(items, work, out(ctx, "case_solver"), key=lambda it: f"{it['c']['case_id']}|{it['j']}",
                           concurrency=ctx.llm("solver").cfg.concurrency, desc="exp2 cases")
    by = defaultdict(list)
    for r in runs:
        if "error" not in r:
            by[r["case_id"]].append(r)
    cases = [_case(c, by[c["case_id"]], conf) for c in cands if by.get(c["case_id"])]

    # non-KG: half "ungrounded" (T2 false alarms on an intact KG), the rest "wrong", matched to KG cases
    n_nk = conf["targets"]["non_kg"]
    feats = [(c["features"]["funcs"], c["features"]["hops"]) for c in cases]
    runs_by_q = defaultdict(list)
    for r in pool_runs:
        runs_by_q[r["qid"]].append(r)
    n_ung = min(len(ungrounded), n_nk // 2)
    picks = [(q, "ungrounded") for q in _match(ungrounded, feats, n_ung)]
    picks += [(q, "wrong") for q in _match(wrong, feats, n_nk - n_ung)]
    for q, sub in picks:
        c = {"case_id": f"non_kg|{q['qid']}", "cls": "non_kg", "q": q}
        cases.append(_case(c, runs_by_q[q["qid"]], conf, subtype=sub))
    write_jsonl(cases, out(ctx, "cases"))
    cnt = Counter((c["cls"], c["subtype"]) for c in cases)
    print("[cases]", {f"{a}/{b}": v for (a, b), v in sorted(cnt.items())},
          "| T1:", sum(c["t1"] for c in cases), "T2:", sum(c["t2"] for c in cases))


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

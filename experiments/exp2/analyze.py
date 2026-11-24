"""Exp 2 analysis: attribution, localisation, repair, gate behaviour, locality/portability, baselines.

Gold action per class
  missing_fact -> missing_fact (+ add the deleted fact)      wrong_fact -> wrong_fact (+ restore value)
  non_kg, non_kg_offpath -> non_kg (no edit)                  invalid_task -> invalid_task (no edit)
  refer -> refer (no commit)

Usage:  python -m experiments.exp2.analyze --config configs/small.yaml
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from experiments.common import parse_args, setup
from experiments.exp2.build_cases import case_executor
from kgcoevo.context import Context
from kgcoevo.eval.compare import answers_equal, match_any
from kgcoevo.eval.discovery import KeyResolver
from kgcoevo.eval.stats import fmt_ci, wilson
from kgcoevo.kb.store import Edit
from kgcoevo.kb.trace import trace
from kgcoevo.kb.values import value_str
from kgcoevo.runner import read_jsonl, write_json

GOLD = {"missing_fact": "missing_fact", "wrong_fact": "wrong_fact", "non_kg": "non_kg", "non_kg_offpath": "non_kg",
        "invalid_task": "invalid_task", "refer": "refer"}
CORE = ("missing_fact", "wrong_fact", "non_kg")
KG = ("missing_fact", "wrong_fact")
NO_EDIT = ("non_kg", "non_kg_offpath", "invalid_task")


def _md(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
                     + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def _w(k, n):
    return f"{fmt_ci(*wilson(k, n))} (n={n})" if n else "n/a"


def _boot_f1(y, p, labels, n_boot=2000, seed=0):
    y, p = np.asarray(y), np.asarray(p)
    if len(y) == 0:
        return "n/a"
    rng = np.random.default_rng(seed)
    base = f1_score(y, p, labels=list(labels), average="macro", zero_division=0)
    bs = [f1_score(y[i], p[i], labels=list(labels), average="macro", zero_division=0)
          for i in (rng.integers(0, len(y), len(y)) for _ in range(n_boot))]
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return f"{100 * base:.1f} [{100 * lo:.1f}, {100 * hi:.1f}]"


def located_ok(ctx: Context, resolver: KeyResolver, r: dict, d: dict) -> bool:
    lf = r.get("located_fact")
    if not isinstance(lf, dict) or not d:
        return False
    subj_ok = d["subject"] in ctx.gs.name_to_ids.get(str(lf.get("subject", "")).strip(), [])
    key = resolver(str(lf.get("key", "")))
    return subj_ok and key == d["key"]


def exact_repair(ctx: Context, e: dict | None, d: dict | None) -> bool:
    """The edit restores the G* fact that the defect removed/changed."""
    if not e or not d or e["subject"] != d["subject"] or e["key"] != d["key"]:
        return False
    if d["op"] == "delete" and e["op"] != "add":
        return False
    if d["op"] == "corrupt" and e["op"] not in ("update", "add"):
        return False
    new = e["new_value"] if e["kind"] == "rel" else value_str(e["new_value"])
    return new == d["before"] if e["kind"] == "rel" else answers_equal(new, d["before"])


def consistent_with_gstar(ctx: Context, e: dict | None) -> bool:
    if not e:
        return False
    if e["op"] == "delete":
        old = e["value"] if e["kind"] == "rel" else value_str(e["value"])
        return ctx.gs.find_fact(e["kind"], e["subject"], e["key"], old) is None
    if e["kind"] == "rel":
        return ctx.gs.find_fact("rel", e["subject"], e["key"], e["new_value"]) is not None
    return any(answers_equal(f.vstr, value_str(e["new_value"])) for f in ctx.gs.attr_facts(e["subject"], e["key"]))


class QuestionIndex:
    def __init__(self, ctx: Context):
        self.by_name = defaultdict(list)
        for split in ("val", "train"):
            for i, q in enumerate(ctx.questions(split)):
                for s in q.get("program", []):
                    if s["function"] == "Find":
                        self.by_name[s["inputs"][0]].append({"qid": f"{split}:{i}", **q})

    def near(self, names: set[str], n: int) -> list[dict]:
        out, seen = [], set()
        for nm in sorted(names):
            for q in self.by_name.get(nm, []):
                if q["qid"] not in seen:
                    seen.add(q["qid"])
                    out.append(q)
        return out[:n]


def program_locality(ctx: Context, cases: dict, commits: list[dict], n: int) -> dict:
    """Exact, LLM-free locality/portability with gold KQA Pro programs (before vs. after the edit)."""
    qi = QuestionIndex(ctx)
    reg_n = reg_k = port_n = port_k = 0
    for r in commits:
        case = cases[r["case_id"]]
        ex, edits = case_executor(ctx, case)
        e = Edit.from_json(r["edit_built"])
        names = {ctx.gs.name(e.subject)} | ({ctx.gs.name(e.new_value)} if e.kind == "rel" and e.new_value in ctx.gs.entities else set())
        dcid = (case.get("defect") or {}).get("cid_before")
        for q in qi.near(names, n):
            prog = [{"function": s["function"], "inputs": s.get("inputs", [])} for s in q["program"]]
            before = ex.run(prog, edits)
            after = ex.run(prog, edits + [e])
            ok_b = before.ok and match_any(q["answer"], before.answers) and len(before.answers) == 1
            ok_a = after.ok and match_any(q["answer"], after.answers) and len(after.answers) == 1
            if ok_b:
                reg_n += 1
                reg_k += int(not ok_a)
            if dcid:
                tr = trace(ctx.gs_exec, prog)
                if tr.ok and dcid in tr.cids and not ok_b:
                    port_n += 1
                    port_k += int(ok_a)
    return {"regression": (reg_k, reg_n), "portability": (port_k, port_n)}


def surface_baseline(cases: list[dict]) -> dict:
    """Can program/trajectory surface features alone separate KG from non-KG failures? (shortcut check)"""
    rows = [c for c in cases if c["cls"] in CORE]
    if len({c["cls"] in KG for c in rows}) < 2 or len(rows) < 20:
        return {"auc": float("nan"), "n": len(rows)}
    funcs = sorted({f for c in rows for f in c["features"]["funcs"].split("-")})
    X, y = [], []
    for c in rows:
        t = c["failing_traj"]
        ex = t.get("exec") or {}
        X.append([c["features"]["program_len"], c["features"]["hops"], len(t.get("attempts", [])), int(not ex.get("ok", False)),
                  int(ex.get("ok", False) and not ex.get("answers")), int(t.get("source") == "memory")]
                 + [int(f in c["features"]["funcs"].split("-")) for f in funcs])
        y.append(int(c["cls"] in KG))
    X, y = np.asarray(X, float), np.asarray(y)
    cv = StratifiedKFold(n_splits=min(5, int(min(y.sum(), len(y) - y.sum()))), shuffle=True, random_state=0)
    prob = cross_val_predict(LogisticRegression(max_iter=1000), X, y, cv=cv, method="predict_proba")[:, 1]
    return {"auc": float(roc_auc_score(y, prob)), "n": len(rows)}


def exec_signal_baseline(case: dict) -> str:
    ex = case["failing_traj"].get("exec") or {}
    return "missing_fact" if (not ex.get("ok", False) or not ex.get("answers")) else "non_kg"


def main() -> None:
    args = parse_args(__doc__, ["all"])
    ctx = setup(args, "exp2.analyze")
    (ctx.work / "results").mkdir(parents=True, exist_ok=True)
    cases = {c["case_id"]: c for c in read_jsonl(ctx.work / "exp2" / "cases.jsonl")}
    runs = [r for r in read_jsonl(ctx.work / "exp2" / "curator.jsonl") if "error" not in r and r["case_id"] in cases]
    resolver = KeyResolver(ctx.gs)
    S: dict = {"cases": dict(Counter(c["cls"] for c in cases.values()))}
    parts = ["# Exp 2 report", "## Cases", _md(["class", "n"], sorted(S["cases"].items()))]

    groups = defaultdict(list)
    for r in runs:
        groups[(r["variant"], r["ablation"])].append(r)
    main_rows, gate_rows, conf_txt = [], [], []
    for (v, a), rs in sorted(groups.items()):
        core = [r for r in rs if r["cls"] in CORE]
        y = [GOLD[r["cls"]] for r in core]
        p = [r["diagnosis"] if r["diagnosis"] in CORE else "other" for r in core]
        acc3 = sum(int(a_ == b_) for a_, b_ in zip(y, p))
        tp = sum(1 for r in core if r["cls"] in KG and r["diagnosis"] in KG)
        pp = sum(1 for r in core if r["diagnosis"] in KG)
        pos = sum(1 for r in core if r["cls"] in KG)
        kgr = [r for r in rs if r["cls"] in KG]
        loc = sum(located_ok(ctx, resolver, r, cases[r["case_id"]]["defect"]) for r in kgr)
        prop_exact = sum(exact_repair(ctx, r["edit_built"], cases[r["case_id"]]["defect"]) for r in kgr)
        by_op = {op: [r for r in kgr if cases[r["case_id"]]["defect"]["op"] == op] for op in ("delete", "corrupt")}
        main_rows.append([v, a, len(rs), _w(acc3, len(core)), _boot_f1(y, p, CORE), _w(tp, pp), _w(tp, pos), _w(loc, len(kgr)),
                          _w(sum(r["commit"] and exact_repair(ctx, r["edit_built"], cases[r["case_id"]]["defect"]) for r in by_op["delete"]), len(by_op["delete"])),
                          _w(sum(r["commit"] and exact_repair(ctx, r["edit_built"], cases[r["case_id"]]["defect"]) for r in by_op["corrupt"]), len(by_op["corrupt"])),
                          _w(prop_exact, len(kgr))])
        commits = [r for r in rs if r["commit"]]
        ne = [r for r in rs if r["cls"] in NO_EDIT]
        inv = [r for r in rs if r["cls"] == "invalid_task"]
        ref = [r for r in rs if r["cls"] == "refer"]
        others = [r for r in rs if r["cls"] != "refer"]
        gate_rows.append([v, a, _w(sum(consistent_with_gstar(ctx, r["edit_built"]) for r in commits), len(commits)),
                          _w(sum(r["commit"] for r in ne), len(ne)), _w(sum(r["commit"] for r in inv), len(inv)),
                          _w(sum(r["diagnosis"] == "invalid_task" for r in inv), len(inv)),
                          _w(sum(r["diagnosis"] == "refer" for r in ref), len(ref)), _w(sum(r["commit"] for r in ref), len(ref)),
                          _w(sum(r["diagnosis"] == "refer" for r in others), len(others)),
                          sum(bool(r.get("reward_hacking_candidate")) for r in rs)])
        if (v, a) == ("gold", "full"):
            labels = list(CORE) + ["invalid_task", "refer", "invalid"]
            cm = Counter((GOLD[r["cls"]] if r["cls"] != "non_kg_offpath" else "non_kg(offpath)", r["diagnosis"]) for r in rs)
            rows_lab = ["missing_fact", "wrong_fact", "non_kg", "non_kg(offpath)", "invalid_task", "refer"]
            conf_txt = [_md(["gold \\ predicted"] + labels, [[g] + [cm[(g, l)] for l in labels] for g in rows_lab])]
    parts += ["## Attribution and repair (core classes for 3-way metrics)",
              "KG-vs-non-KG precision/recall count missing_fact or wrong_fact as positive; repair = committed exact restoration of the G* fact.",
              _md(["key shown", "ablation", "runs", "3-way acc %", "macro-F1 %", "KG precision %", "KG recall %",
                   "localisation %", "exact repair (deletions) %", "exact repair (corruptions) %", "proposed edit exact %"], main_rows),
              "## Gate behaviour",
              _md(["key shown", "ablation", "committed edits consistent with G* %", "commits on no-edit classes %",
                   "KG poisoning (commits on invalid_task) %", "invalid_task recognised %", "refer on refer class %",
                   "commits on refer class %", "false refer on other classes %", "reward-hacking candidates"], gate_rows),
              "## Confusion matrix (gold key, full)"] + conf_txt
    S["main"], S["gate"] = main_rows, gate_rows

    # locality / portability (program level, exact)
    commits = [r for r in groups.get(("gold", "full"), []) if r["commit"] and r["j"] == 0]
    loc = program_locality(ctx, cases, commits, ctx.cfg["exp2"]["locality_n"])
    S["locality"] = loc
    parts += ["## Locality and portability of committed edits (gold KQA Pro programs, exact)",
              f"Regressions among previously correct neighbour questions: {_w(*loc['regression'])}.  ",
              f"Portability (questions that depend on the repaired fact and become correct): {_w(*loc['portability'])}."]
    ls = read_jsonl(ctx.work / "exp2" / "locality_solver.jsonl")
    if ls:
        pair = defaultdict(dict)
        for r in ls:
            pair[(r["case_id"], r["qid"])][r["side"]] = r["correct"]
        before_ok = [v for v in pair.values() if v.get("before")]
        parts.append(f"Solver-level regressions: {_w(sum(not v.get('after', False) for v in before_ok), len(before_ok))}.")

    # baselines
    core_cases = [c for c in cases.values() if c["cls"] in CORE]
    y = [GOLD[c["cls"]] for c in core_cases]
    p_exec = [exec_signal_baseline(c) for c in core_cases]
    sb = surface_baseline(list(cases.values()))
    S["baselines"] = {"exec_signal_macro_f1": _boot_f1(y, p_exec, CORE), "always_wrong_fact_macro_f1": _boot_f1(y, ["wrong_fact"] * len(y), CORE),
                      "surface_auc": sb}
    parts += ["## Baselines",
              _md(["baseline", "result"], [["execution-signal rule (empty/error -> missing_fact, else non_kg), macro-F1 %", S["baselines"]["exec_signal_macro_f1"]],
                                           ["always wrong_fact, macro-F1 %", S["baselines"]["always_wrong_fact_macro_f1"]],
                                           ["surface-feature logistic regression, KG vs non-KG AUC (shortcut check; should be near 0.5)",
                                            f"{sb['auc']:.3f} (n={sb['n']})"]])]
    with open(ctx.work / "results" / "exp2_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "cls", "variant", "ablation", "j", "diagnosis", "commit", "cited_ok", "verified", "sandbox_success"])
        for r in runs:
            w.writerow([r["case_id"], r["cls"], r["variant"], r["ablation"], r["j"], r["diagnosis"], r["commit"], r["cited_ok"],
                        r["verified"], (r.get("sandbox") or {}).get("success")])
    (ctx.work / "results" / "exp2_report.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    write_json(S, ctx.work / "results" / "exp2_summary.json")
    print(f"[analyze] wrote {ctx.work / 'results' / 'exp2_report.md'}")


if __name__ == "__main__":
    main()

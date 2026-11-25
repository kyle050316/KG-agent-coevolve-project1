"""Exp 2 analysis: trigger coverage, diagnosis, KG repair, tool effects, gate, locality, baselines.

The goal of Exp 2 is that the Curator finds KG defects and repairs them; the diagnosis label is an
intermediate output. Primary metric: admitted exact repair (the admitted edit restores the G* fact
that the defect removed or changed). Secondary: false edits on non-KG cases (the KG was intact) and
edit precision against G*. The main tables use the KQA Pro cases (trusted keys); cases from Exp 1
Challenger tasks (keys that can be wrong) have their own section: edits that write a wrong key into
the KG, bad_key detection, and the control whose key is right.

Views (which flagged cases reach the Curator)
  T1      answer-based trigger only (the original design)
  T1+T2   answer-based or grounding-based trigger (adds silent defects and ungrounded non-KG cases)

Usage:  python -m experiments.exp2.analyze --config configs/main.yaml
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from experiments.common import parse_args, setup
from experiments.exp2.build_cases import CHALLENGER_KINDS, KG_CLASSES, case_executor
from kgcoevo.agents.curator import DIAGNOSES
from kgcoevo.context import Context
from kgcoevo.eval.compare import answers_equal, match_any
from kgcoevo.eval.discovery import KeyResolver
from kgcoevo.eval.stats import fmt_ci, mcnemar_exact, wilson
from kgcoevo.kb.store import Edit
from kgcoevo.kb.trace import trace
from kgcoevo.kb.values import value_str
from kgcoevo.runner import read_jsonl, write_json

NON_KG = ("non_kg", "bad_key")
VIEWS = {"T1": lambda c: c["t1"], "T1+T2": lambda c: c["t1"] or c["t2"]}


def _md(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
                     + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def _w(k, n):
    return f"{fmt_ci(*wilson(k, n))} (n={n})" if n else "n/a"


def _boot_f1(y, p, labels=None, n_boot=2000, seed=0):
    """Macro-F1 over the gold classes present (a class absent from the gold labels would count as 0)."""
    if len(y) == 0:
        return "n/a"
    labels = labels or [d for d in DIAGNOSES if d in set(y)]
    y, p = np.asarray(y), np.asarray(p)
    rng = np.random.default_rng(seed)
    base = f1_score(y, p, labels=list(labels), average="macro", zero_division=0)
    bs = [f1_score(y[i], p[i], labels=list(labels), average="macro", zero_division=0)
          for i in (rng.integers(0, len(y), len(y)) for _ in range(n_boot))]
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return f"{100 * base:.1f} [{100 * lo:.1f}, {100 * hi:.1f}]"


# -- edit scoring (exact, no LLM) ----------------------------------------------------------------

def located_ok(ctx: Context, resolver: KeyResolver, lf, d: dict | None) -> bool:
    if not isinstance(lf, dict) or not d:
        return False
    subj_ok = d["subject"] in ctx.gs.name_to_ids.get(str(lf.get("subject", "")).strip(), [])
    return subj_ok and resolver(str(lf.get("key", ""))) == d["key"]


def _same_value(kind: str, v, target: str) -> bool:
    return v == target if kind == "rel" else answers_equal(value_str(v), target)


def exact_repair(e: dict | None, d: dict | None) -> bool:
    """The edit restores the G* fact: re-add a deleted fact, or update the corrupted value back."""
    if not e or not d or (e["kind"], e["subject"], e["key"]) != (d["kind"], d["subject"], d["key"]):
        return False
    if not _same_value(e["kind"], e["new_value"], d["before"]):
        return False
    if d["op"] == "delete":
        return e["op"] == "add"
    return e["op"] == "update" and _same_value(e["kind"], e["value"], d["after"])


def writes_key(ctx: Context, e: dict | None, key: str) -> bool:
    """The edit writes the task's answer key into the KG (harmful when the key is wrong)."""
    if not e or e["op"] == "delete":
        return False
    v = e["new_value"]
    return answers_equal(ctx.gs.name(v) if e["kind"] == "rel" and v in ctx.gs.entities else value_str(v), key)


def consistent_with_gstar(ctx: Context, e: dict | None) -> bool:
    """The edited fact is true in G* (and an update replaces a value that G* does not have)."""
    if not e or e["op"] == "delete":
        return False

    def in_gs(v) -> bool:
        if e["kind"] == "rel":
            return ctx.gs.find_fact("rel", e["subject"], e["key"], v) is not None
        return any(answers_equal(f.vstr, value_str(v)) for f in ctx.gs.attr_facts(e["subject"], e["key"]))

    return in_gs(e["new_value"]) and (e["op"] == "add" or not in_gs(e["value"]))


def restores(ctx: Context, case: dict, e: dict | None) -> bool:
    """With the edit applied, the gold KQA Pro program returns the gold answer again (program level)."""
    if not e:
        return False
    ex, edits = case_executor(ctx, case)
    try:
        res = ex.run(case["program_gold"], edits + [Edit.from_json(e)])
    except Exception:  # noqa: BLE001 - an edit that cannot be applied does not restore anything
        return False
    return res.ok and len(res.answers) == 1 and answers_equal(res.answers[0], case["gold_answer"])


# -- locality / portability (program level, exact) -------------------------------------------------

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


def program_locality(ctx: Context, cases: dict, admitted: list[dict], n: int) -> dict:
    """Regressions on neighbour questions and portability to questions that use the repaired fact."""
    qi = QuestionIndex(ctx)
    reg_n = reg_k = port_n = port_k = 0
    for r in admitted:
        case = cases[r["case_id"]]
        ex, edits = case_executor(ctx, case)
        e = Edit.from_json(r["final_edit"])
        names = {ctx.gs.name(e.subject)}
        if e.kind == "rel" and e.new_value in ctx.gs.entities:
            names.add(ctx.gs.name(e.new_value))
        dcid = (case.get("defect") or {}).get("cid_before")
        for q in qi.near(names, n):
            if q["question"] == case["question"]:
                continue
            prog = [{"function": s["function"], "inputs": s.get("inputs", [])} for s in q["program"]]
            before, after = ex.run(prog, edits), ex.run(prog, edits + [e])
            ok_b = before.ok and len(before.answers) == 1 and match_any(q["answer"], before.answers)
            ok_a = after.ok and len(after.answers) == 1 and match_any(q["answer"], after.answers)
            if ok_b:
                reg_n += 1
                reg_k += int(not ok_a)
            elif dcid:
                tr = trace(ctx.gs_exec, prog)
                if tr.ok and dcid in tr.cids:
                    port_n += 1
                    port_k += int(ok_a)
    return {"regression": (reg_k, reg_n), "portability": (port_k, port_n)}


# -- baselines -----------------------------------------------------------------------------------

def exec_rule(case: dict) -> str:
    """No-LLM rule on the Solver's execution: error/empty -> missing, other answer -> wrong, key -> non-KG."""
    ex = case["traj"].get("exec") or {}
    if not ex.get("ok") or not ex.get("answers"):
        return "missing_fact"
    return "non_kg" if match_any(case["key"], ex["answers"]) else "wrong_fact"


def surface_baseline(cases: list[dict]) -> dict:
    """Do trajectory/program surface features alone separate KG from non-KG cases? (shortcut check)"""
    if len({c["cls"] in KG_CLASSES for c in cases}) < 2 or len(cases) < 20:
        return {"auc": float("nan"), "n": len(cases)}
    funcs = sorted({f for c in cases for f in c["features"]["funcs"].split("-")})
    X, y = [], []
    for c in cases:
        t = c["traj"]
        ex = t.get("exec") or {}
        X.append([c["features"]["program_len"], c["features"]["hops"], len(t.get("attempts", [])), int(not ex.get("ok", False)),
                  int(ex.get("ok", False) and not ex.get("answers")), int(t.get("source") == "memory"), int(c["t1"]), int(c["t2"])]
                 + [int(f in c["features"]["funcs"].split("-")) for f in funcs])
        y.append(int(c["cls"] in KG_CLASSES))
    X, y = np.asarray(X, float), np.asarray(y)
    folds = int(min(5, y.sum(), len(y) - y.sum()))
    if folds < 2:
        return {"auc": float("nan"), "n": len(cases)}
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=0)
    prob = cross_val_predict(LogisticRegression(max_iter=1000), X, y, cv=cv, method="predict_proba")[:, 1]
    return {"auc": float(roc_auc_score(y, prob)), "n": len(cases)}


# -- report --------------------------------------------------------------------------------------

def metric_row(ctx, resolver, cases, rs):
    kg = [r for r in rs if r["cls"] in KG_CLASSES]
    nk = [r for r in rs if r["cls"] == "non_kg"]
    y = [r["cls"] for r in rs]
    p = [r["diagnosis"] if r["diagnosis"] in DIAGNOSES else "invalid" for r in rs]
    tp = sum(r["diagnosis"] in KG_CLASSES for r in kg)
    pp = sum(r["diagnosis"] in KG_CLASSES for r in rs)
    adm = [r for r in rs if r["admitted"]]
    by_op = {op: [r for r in kg if cases[r["case_id"]]["defect"]["op"] == op] for op in ("delete", "corrupt")}
    row = [len(rs), _w(sum(a == b for a, b in zip(y, p)), len(rs)), _boot_f1(y, p), _w(tp, pp), _w(tp, len(kg)),
           _w(sum(located_ok(ctx, resolver, r["first"]["located_fact"], cases[r["case_id"]]["defect"]) for r in kg), len(kg)),
           _w(sum(r["_exact_first"] for r in kg), len(kg)),
           _w(sum(r["_repaired"] for r in by_op["delete"]), len(by_op["delete"])),
           _w(sum(r["_repaired"] for r in by_op["corrupt"]), len(by_op["corrupt"])),
           _w(sum(r["admitted"] for r in nk), len(nk)),
           _w(sum(consistent_with_gstar(ctx, r["final_edit"]) for r in adm), len(adm))]
    return row


def main() -> None:
    args = parse_args(__doc__, ["all"])
    ctx = setup(args, "exp2.analyze")
    conf = ctx.cfg["exp2"]
    (ctx.work / "results").mkdir(parents=True, exist_ok=True)
    cases = {c["case_id"]: c for c in read_jsonl(ctx.work / "exp2" / "cases.jsonl")}
    runs = [r for r in read_jsonl(ctx.work / "exp2" / "curator.jsonl") if "error" not in r and r["case_id"] in cases]
    resolver = KeyResolver(ctx.gs)
    for r in runs:
        d = cases[r["case_id"]].get("defect")
        r["_exact_first"] = exact_repair(r["first_edit_built"], d)
        r["_repaired"] = bool(r["admitted"]) and exact_repair(r["final_edit"], d)
        r["_writes_key"] = bool(r["admitted"]) and writes_key(ctx, r["final_edit"], cases[r["case_id"]]["key"])
    kq = {cid for cid, c in cases.items() if c.get("source", "kqapro") == "kqapro"}  # trusted keys
    S: dict = {}
    parts = ["# Exp 2 report"]

    # 1. cases and trigger coverage (no Curator involved)
    rows = []
    groups = defaultdict(list)
    for c in cases.values():
        groups[(c["cls"], c["subtype"])].append(c)
    for (cls, sub), cs in sorted(groups.items()):
        rows.append([cls, sub, len(cs), _w(sum(c["t1"] for c in cs), len(cs)), _w(sum(c["t2"] for c in cs), len(cs)),
                     _w(sum(c["t1"] or c["t2"] for c in cs), len(cs)), f"{np.mean([c['solver_acc'] for c in cs]):.2f}",
                     f"{np.mean([c['solver_grounded'] for c in cs]):.2f}"])
    S["cases"] = {f"{a}/{b}": len(v) for (a, b), v in groups.items()}
    parts += ["## Cases and trigger coverage",
              "T1 = Solver answer stably wrong; T2 = Solver KG execution stably does not return the answer key. "
              "For KG classes the trigger rate is the recall of the trigger; for non_kg it is the load of false alarms. "
              "visible/silent: Solver stably wrong/right despite the defect.",
              _md(["class", "subtype", "n", "T1 %", "T2 %", "T1 or T2 %", "Solver acc", "Solver grounded"], rows)]

    n_kg = sum(c["cls"] in KG_CLASSES for cid, c in cases.items() if cid in kq)
    j0 = [r for r in runs if r["j"] == 0]
    by_abl = defaultdict(list)
    for r in j0:
        by_abl[r["ablation"]].append(r)

    # 2. main table: ablation x view
    head = ["ablation", "view", "runs", "diagnosis acc %", "macro-F1 %", "KG precision %", "KG recall %", "localisation %",
            "proposed edit exact %", "admitted exact repair, missing %", "admitted exact repair, wrong %",
            "false edits on non_kg %", "admitted edits true in G* %"]
    main_rows = []
    for abl in conf["ablations"]:
        for vname, vf in VIEWS.items():
            rs = [r for r in by_abl.get(abl, []) if r["case_id"] in kq and vf(cases[r["case_id"]])]
            main_rows.append([abl, vname] + metric_row(ctx, resolver, cases, rs))
    S["main"] = main_rows
    parts += ["## Diagnosis and repair (KQA Pro cases, seed 0)",
              "KQA Pro cases only (answer keys are right; Challenger cases have their own section). "
              "Ablations other than full run on a stratified subset, so compare them with the paired table below. "
              "Repair counts only admitted edits (source gate passed) that restore the G* fact exactly.",
              _md(head, main_rows)]

    # 3. end-to-end over all KG cases (full)
    full = by_abl.get("full", [])
    full_kq = [r for r in full if r["case_id"] in kq]
    e2e = []
    for vname, vf in VIEWS.items():
        rs = [r for r in full_kq if vf(cases[r["case_id"]]) and r["cls"] in KG_CLASSES]
        rest = [r for r in rs if r["_repaired"]]
        e2e.append([vname, _w(len(rs), n_kg), _w(len(rest), n_kg),
                    _w(sum(restores(ctx, cases[r["case_id"]], r["final_edit"]) for r in rs if r["admitted"]), n_kg)])
    S["end_to_end"] = e2e
    parts += ["## End-to-end repair over all KG cases (KQA Pro, full)",
              "Denominator: every KQA Pro KG case, including those no trigger flags. Program restore: with the admitted edit, "
              "the gold KQA Pro program returns the gold answer again.",
              _md(["view", "flagged %", "exact repair %", "program restore %"], e2e)]

    # 4. by subtype (full, T1+T2)
    sub_rows = []
    for (cls, sub), _ in sorted(groups.items()):
        rs = [r for r in full if r["cls"] == cls and r["subtype"] == sub]
        sub_rows.append([cls, sub, len(rs), _w(sum(r["diagnosis"] == cls for r in rs), len(rs)),
                         _w(sum(r["admitted"] for r in rs), len(rs)),
                         _w(sum(r["_repaired"] for r in rs), len(rs)) if cls in KG_CLASSES else "-"])
    parts += ["## By subtype (full, all flagged cases)",
              _md(["class", "subtype", "runs", "diagnosis correct %", "admitted edit %", "exact repair %"], sub_rows)]

    # 5. tool effects
    prop = [r for r in full if r["proposed"]]
    dec = Counter((r["second"] or {}).get("decision", "none") for r in prop)
    ex_first = [r for r in prop if r["_exact_first"]]
    bad_first = [r for r in prop if r["cls"] in KG_CLASSES and not r["_exact_first"]] + [r for r in prop if r["cls"] in NON_KG]
    tool_ok = [r for r in ex_first if isinstance(r.get("tool"), dict) and "success" in r["tool"]]
    tool_rows = [["first-turn edits proposed", len(prop)],
                 ["decisions (commit / revise / withdraw / invalid)",
                  " / ".join(str(dec.get(k, 0)) for k in ("commit", "revise", "withdraw", "invalid"))],
                 ["sandbox: Solver answer fixed after an exact edit %", _w(sum(r["tool"]["success"] for r in tool_ok), len(tool_ok))],
                 ["exact first edits withdrawn after the tool % (lower is better)",
                  _w(sum((r["second"] or {}).get("decision") == "withdraw" for r in ex_first), len(ex_first))],
                 ["exact first edits kept and admitted %", _w(sum(r["_repaired"] for r in ex_first), len(ex_first))],
                 ["wrong first edits withdrawn or revised to exact % (higher is better)",
                  _w(sum(r["final_edit"] is None or r["_repaired"] for r in bad_first), len(bad_first))]]
    paired = []
    sub_full = {r["case_id"]: r for r in full}
    for abl in conf["ablations"]:
        if abl == "full":
            continue
        pairs = [(sub_full[r["case_id"]], r) for r in by_abl.get(abl, []) if r["case_id"] in sub_full]
        kg_p = [(a, b) for a, b in pairs if a["cls"] in KG_CLASSES]
        nk_p = [(a, b) for a, b in pairs if a["cls"] in NON_KG]
        for name, ps, f in (("exact repair (KG cases)", kg_p, lambda r: int(r["_repaired"])),
                            ("false edit (non_kg / bad_key cases)", nk_p, lambda r: int(r["admitted"]))):
            if ps:
                m = mcnemar_exact([f(a) for a, _ in ps], [f(b) for _, b in ps])
                paired.append([f"full vs {abl}", name, len(ps), f"{100 * np.mean([f(a) for a, _ in ps]):.1f}",
                               f"{100 * np.mean([f(b) for _, b in ps]):.1f}", f"{m['b10']}/{m['b01']}", f"{m['p']:.3g}"])
    S["tool"], S["paired"] = tool_rows, paired
    parts += ["## Counterfactual tool (full)",
              "The sandbox re-run is information for the Curator, not a gate: a correct edit need not fix a wrong Solver program.",
              _md(["quantity", "value"], tool_rows),
              "## Paired ablations (same cases, exact McNemar)",
              _md(["comparison", "outcome", "pairs", "full %", "ablation %", "full-only / ablation-only", "p"], paired)
              if paired else "(no ablations run)"]

    # 6. gate
    fin = [r for r in full if r["final_edit"]]
    cited = [r for r in fin if r["cited_ok"]]
    gate_rows = [["final edits", len(fin)], ["cite a shown evidence item %", _w(len(cited), len(fin))],
                 ["verifier confirms the cited item %", _w(sum(bool(r["verified"]) for r in cited), len(cited))],
                 ["blocked: the shown evidence states the value the edit replaces %",
                  _w(sum(bool(r.get("kg_supported")) for r in cited if r["verified"]), sum(bool(r["verified"]) for r in cited))],
                 ["admitted %", _w(sum(r["admitted"] for r in fin), len(fin))],
                 ["gate rejected an exact repair %", _w(sum(exact_repair(r["final_edit"], cases[r["case_id"]].get("defect"))
                                                            and not r["admitted"] for r in fin), len(fin))]]
    S["gate"] = gate_rows
    parts += ["## Source gate (full)", _md(["quantity", "value"], gate_rows)]

    # 7. confusion matrix (full, all flagged)
    labels = list(DIAGNOSES) + ["invalid"]
    cm = Counter((r["cls"], r["diagnosis"] if r["diagnosis"] in DIAGNOSES else "invalid") for r in full)
    parts += ["## Confusion matrix (full, all flagged cases)",
              _md(["gold \\ predicted"] + labels, [[g] + [cm[(g, p)] for p in labels] for g in DIAGNOSES])]

    # 7b. cases from Exp 1 Challenger tasks: the answer key can be wrong
    ch_rows = []
    for cls, sub in CHALLENGER_KINDS:
        cs = [c for c in cases.values() if c.get("source") == "challenger" and (c["cls"], c["subtype"]) == (cls, sub)]
        rs = [r for r in full if (r["cls"], r["subtype"]) == (cls, sub)]
        ch_rows.append([cls, sub, len(cs), _w(sum(c["t1"] or c["t2"] for c in cs), len(cs)), len(rs),
                        _w(sum(r["diagnosis"] == cls for r in rs), len(rs)),
                        _w(sum(r["diagnosis"] == "bad_key" for r in rs), len(rs)),
                        _w(sum(r["admitted"] for r in rs), len(rs)),
                        _w(sum(r["_repaired"] for r in rs), len(rs)) if cls in KG_CLASSES else "-",
                        _w(sum(r["_writes_key"] for r in rs), len(rs)) if sub != "challenger_key_right" else "-",
                        _w(sum(bool(r.get("kg_supported")) for r in rs), len(rs))])
    S["challenger"] = ch_rows
    parts += ["## Cases from Exp 1 Challenger tasks (full)",
              "bad_key: the KG is right and the Challenger changed the key to a wrong value (correct: bad_key, no edit). "
              "challenger_key_wrong: the path has a defect and the key is another wrong value (correct: repair to the "
              "G* value, not to the key). challenger_key_right: control, the key was fixed to the G* value (correct: "
              "repair). 'writes the wrong key' = an admitted edit puts the task's wrong key into the KG; 'blocked' = the "
              "two-sided gate found the replaced value stated in the shown evidence.",
              _md(["class", "subtype", "cases", "flagged %", "runs", "diagnosis correct %", "diagnosed bad_key %",
                   "admitted edit %", "exact repair %", "admitted edit writes the wrong key %", "blocked by the gate %"],
                  ch_rows)]

    if conf["samples"] > 1:
        per_j = defaultdict(list)
        for r in runs:
            if r["ablation"] == "full" and r["cls"] in KG_CLASSES and r["case_id"] in kq:
                per_j[r["j"]].append(r["_repaired"])
        vals = [100 * np.mean(v) for _, v in sorted(per_j.items())]
        parts.append(f"Seed spread of exact repair over KG runs (full): {', '.join(f'{v:.1f}' for v in vals)} "
                     f"(sd {np.std(vals, ddof=1):.1f}).")

    # 8. locality / portability
    admitted = [r for r in full if r["admitted"]]
    loc = program_locality(ctx, cases, admitted, conf["locality_n"])
    S["locality"] = loc
    parts += ["## Locality and portability of admitted edits (gold KQA Pro programs, exact)",
              f"Regressions among previously correct neighbour questions: {_w(*loc['regression'])}.  ",
              f"Portability (questions that use the defective fact and become correct): {_w(*loc['portability'])}."]
    ls = read_jsonl(ctx.work / "exp2" / "locality_solver.jsonl")
    if ls:
        pair = defaultdict(dict)
        for r in ls:
            if "error" not in r:
                pair[(r["case_id"], r["qid"])][r["side"]] = r["correct"]
        before_ok = [v for v in pair.values() if v.get("before")]
        parts.append(f"Solver-level regressions: {_w(sum(not v.get('after', False) for v in before_ok), len(before_ok))}.")

    # 9. baselines on the flagged cases
    flagged = [c for cid, c in cases.items() if cid in kq and (c["t1"] or c["t2"]) and c.get("traj")]
    y = [c["cls"] for c in flagged]
    sb = surface_baseline(flagged)
    S["baselines"] = {"exec_rule_macro_f1": _boot_f1(y, [exec_rule(c) for c in flagged]),
                      "majority_macro_f1": _boot_f1(y, [Counter(y).most_common(1)[0][0]] * len(y)) if y else "n/a",
                      "surface_auc": sb}
    parts += ["## Baselines (flagged KQA Pro cases)",
              _md(["baseline", "result"],
                  [["execution rule (error/empty -> missing, other answer -> wrong, key returned -> non_kg), macro-F1 %",
                    S["baselines"]["exec_rule_macro_f1"]],
                   ["majority class, macro-F1 %", S["baselines"]["majority_macro_f1"]],
                   ["surface-feature logistic regression, KG vs non-KG AUC (shortcut check)", f"{sb['auc']:.3f} (n={sb['n']})"]])]

    with open(ctx.work / "results" / "exp2_runs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "source", "cls", "subtype", "t1", "t2", "ablation", "j", "first_diagnosis", "diagnosis",
                    "decision", "proposed_exact", "admitted", "exact_repair", "writes_key", "cited_ok", "verified",
                    "kg_supported", "sandbox_success"])
        for r in runs:
            w.writerow([r["case_id"], cases[r["case_id"]].get("source", "kqapro"), r["cls"], r["subtype"], r["t1"], r["t2"],
                        r["ablation"], r["j"], r["first"]["diagnosis"], r["diagnosis"], (r["second"] or {}).get("decision", ""),
                        r["_exact_first"], r["admitted"], r["_repaired"], r["_writes_key"], r["cited_ok"], r["verified"],
                        r.get("kg_supported"), (r.get("tool") or {}).get("success", "")])
    (ctx.work / "results" / "exp2_report.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    write_json(S, ctx.work / "results" / "exp2_summary.json")
    print(f"[analyze] wrote {ctx.work / 'results' / 'exp2_report.md'}")


if __name__ == "__main__":
    main()

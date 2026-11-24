"""Exp 1 analysis: tables with 95% CIs, paired comparisons, stratification.

Outputs (in <work_dir>/results/):
  exp1_report.md     markdown tables (data, Mode A funnel + contamination, comparisons, Mode B, task quality)
  exp1_summary.json  all numbers
  exp1_*.csv         per-item tables for further analysis

Usage:  python -m experiments.exp1.analyze --config configs/exp1_2day.yaml
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict

from experiments.common import parse_args, setup
from kgcoevo.context import Context, rate_tag
from kgcoevo.eval.checks import check_task
from kgcoevo.eval.compare import answers_equal, match_any
from kgcoevo.eval.discovery import PRECISION_CATS, KeyResolver, score_report
from kgcoevo.eval.stats import cluster_bootstrap, fmt_ci, holm, mcnemar_exact, paired_cluster_bootstrap, wilson
from kgcoevo.runner import read_json, read_jsonl, write_json

LLM_ORDER = ["B0", "C0", "C1", "C2", "C2link", "C3"]


def _md(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _ci(vals: list[float], clusters: list[str]) -> str:
    if not vals:
        return "n/a"
    return fmt_ci(*cluster_bootstrap(vals, clusters, n_boot=2000))


def _wil(k: int, n: int) -> str:
    return fmt_ci(*wilson(k, n)) + f" (n={n})" if n else "n/a"


# ---------------------------------------------------------------------------------------------------
def probe_known(ctx: Context) -> dict[str, bool]:
    """fid -> True if the majority of closed-book probe answers match G*."""
    items = {r["item_id"]: r for r in read_jsonl(ctx.data / "probe_items.jsonl")}
    votes: dict[str, list[bool]] = defaultdict(list)
    for r in read_jsonl(ctx.work / "exp1" / "probe.jsonl"):
        it = items.get(r.get("item_id"))
        if it:
            votes[it["fid"]].append(answers_equal(r.get("answer", ""), it["gold"]))
    return {fid: sum(v) * 2 > len(v) for fid, v in votes.items()}


def section_data(ctx: Context, S: dict) -> str:
    reg = ctx.region
    sup = read_json(ctx.data / "support_summary.json")
    rows = []
    d = ctx.cfg["defects"]
    for rate in d["rates"]:
        for seed in (d["seeds"] if rate == d["main_rate"] else d["seeds"][:1]):
            try:
                defs = ctx.defects(rate, seed)
                paths = ctx.paths(rate, seed)
            except FileNotFoundError:
                continue
            c = Counter((x["op"]) for x in defs)
            rows.append([rate_tag(rate, seed), len(defs), c["delete"], c["corrupt"],
                         sum(x["hardness"] == "similar" for x in defs), len(paths),
                         sum(p["exposed"] for p in paths), sum(p["answer_affecting"] for p in paths)])
    S["data"] = {"region_A": len(reg["A"]), "region_B": len(reg["B"]), "support": sup, "gw": rows}
    txt = [f"Region A: {len(reg['A'])} entities; region B: {len(reg['B'])}; candidate pool {reg['pool_size']}.",
           f"Facts of A and B: {sup['facts']}; supported (S): {sup['supported']}; needing LLM verification: {sup['needs_verification']}.",
           "", _md(["KG", "defects", "delete", "corrupt", "similar", "paths", "exposed", "answer-affecting"], rows)]
    return "\n".join(txt)


def b0_sweep(ctx: Context, S: dict) -> str:
    """B0 contamination at each defect rate (no LLM; exact by execution)."""
    d = ctx.cfg["defects"]
    rows = []
    for rate in d["rates"]:
        seed = d["seeds"][0]
        paths = ctx.paths(rate, seed)
        if not paths:
            continue
        gwx = ctx.gw_exec(rate, seed)
        gw = ctx.gw(rate, seed)
        flags, clus = [], []
        for p in paths:
            t = {"task_id": p["path_id"], "question": p["template_question"], "program": p["program"], "answer": p["answer_gw"],
                 "kg_e1": "gw", "e2_applicable": True, "mention_names": [gw.name(e) for e in p["mention"]],
                 "hidden_names": [gw.name(e) for e in p["hidden"]]}
            c = check_task(t, gwx, ctx.gs_exec)
            if c["valid"]:
                flags.append(int(c["contaminated"]))
                clus.append(p["anchor"])
        rows.append([f"{rate:.2f}", len(paths), len(flags), _ci(flags, clus)])
        ctx.release_gw()
    S["b0_sweep"] = rows
    return _md(["defect rate", "paths", "valid B0 tasks", "B0 contamination % [95% CI]"], rows)


# ---------------------------------------------------------------------------------------------------
def section_mode_a(ctx: Context, S: dict, known: dict[str, bool]) -> str:
    mode_a = [r for r in read_jsonl(ctx.work / "exp1" / "mode_a.jsonl") if "error" not in r]
    tasks = {t["task_id"]: t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl")}
    judged = {r["task_id"]: r for r in read_jsonl(ctx.work / "exp1" / "judge.jsonl")}
    seeds = ctx.cfg["defects"]["seeds"]
    rate = ctx.cfg["defects"]["main_rate"]
    paths = {(s, p["path_id"]): p for s in seeds for p in ctx.paths(rate, s)}
    defects = {s: {x["cid_after"]: x for x in ctx.defects(rate, s) if x["cid_after"]} for s in seeds}

    per_path: dict[str, dict] = defaultdict(dict)  # cond -> (seed,pid,j) -> record
    for r in mode_a:
        p = paths[(r["seed"], r["path_id"])]
        tid = f"A|{r['condition']}|{r['seed']}|{r['path_id']}|{r['j']}"
        t = tasks.get(tid)
        jd = judged.get(tid, {})
        judge_ok = jd.get("faithful") is not False
        valid = bool(t and t["valid"] and judge_ok)
        contaminated = bool(valid and t["contaminated"])
        corrected_ok = bool(r["decision"] == "correct" and t and t.get("gs_answers")
                            and match_any(r["answer"], t["gs_answers"]))
        k = [known.get(defects[r["seed"]][c]["fid"]) for c in p["fact_cids"] if c in defects[r["seed"]]]
        per_path[r["condition"]][(r["seed"], r["path_id"], r["j"])] = {
            "decision": r["decision"], "task": t, "valid": valid, "contaminated": contaminated,
            "judge": jd.get("faithful"), "corrected_ok": corrected_ok, "affecting": p["answer_affecting"],
            "exposed": p["exposed"], "cluster": p["anchor"], "hops": p["hops"],
            "known": (any(x for x in k if x is not None) if k else None)}

    conds = [c for c in LLM_ORDER if c in per_path]
    funnel, contam, rej = [], [], []
    for c in conds:
        recs = list(per_path[c].values())
        dec = Counter(x["decision"] for x in recs)
        ts = [x["task"] for x in recs if x["task"]]
        stage = Counter(t["stage"] for t in ts)
        judge_fail = sum(1 for x in recs if x["task"] and x["task"]["valid"] and x["judge"] is False)
        nvalid = sum(x["valid"] for x in recs)
        funnel.append([c, len(recs), dec["accept"], dec["correct"], dec["reject"], dec["invalid"], len(ts),
                       stage["E1"], stage["E2"], stage["E3"], judge_fail, stage["E4"], nvalid])
        v = [x for x in recs if x["valid"]]
        contam.append([c, _wil(sum(x["contaminated"] for x in v), len(v)),
                       _ci([int(x["contaminated"]) for x in v], [x["cluster"] for x in v]),
                       _ci([int(x["contaminated"]) for x in recs], [x["cluster"] for x in recs])])
        aff = [x for x in recs if x["affecting"]]
        rj = [x for x in recs if x["decision"] in ("reject", "correct")]
        rej.append([c, _wil(sum(x["affecting"] for x in rj), len(rj)),
                    _wil(sum(x["decision"] in ("reject", "correct") for x in aff), len(aff)),
                    _wil(sum(x["corrected_ok"] for x in recs), sum(x["decision"] == "correct" for x in recs))])

    # paired comparisons on the per-path indicator "accepted and contaminated" (same paths across conditions)
    pairs = [("C1", "B0"), ("C2", "C1"), ("C2link", "C2"), ("C3", "C2"), ("C3", "C1")]
    comp, pv = [], {}
    for a, b in pairs:
        if a in per_path and b in per_path:
            keys = sorted(set(per_path[a]) & set(per_path[b]))
            xa = [int(per_path[a][k]["contaminated"]) for k in keys]
            xb = [int(per_path[b][k]["contaminated"]) for k in keys]
            cl = [per_path[a][k]["cluster"] for k in keys]
            res = paired_cluster_bootstrap(xa, xb, cl, n_boot=5000)
            mc = mcnemar_exact(xa, xb)
            pv[f"{a}-{b}"] = mc["p"]
            comp.append([f"{a} - {b}", res["n"], f"{100 * res['diff']:.1f} [{100 * res['lo']:.1f}, {100 * res['hi']:.1f}]",
                         f"{mc['b10']}/{mc['b01']}", f"{mc['p']:.3g}"])
    adj = holm(pv)
    for row in comp:
        row.append(f"{adj[row[0].replace(' - ', '-')]:.3g}")

    # stratification of the conditional contamination rate
    strat = []
    for c in conds:
        for name, fn in [("1-hop", lambda x: x["hops"] == 1), ("2-hop", lambda x: x["hops"] == 2),
                         ("exposed", lambda x: x["exposed"]), ("not exposed", lambda x: not x["exposed"]),
                         ("defect known (closed-book)", lambda x: x["known"] is True),
                         ("defect unknown (closed-book)", lambda x: x["known"] is False)]:
            v = [x for x in per_path[c].values() if x["valid"] and fn(x)]
            strat.append([c, name, _wil(sum(x["contaminated"] for x in v), len(v))])

    S["mode_a"] = {"funnel": funnel, "contamination": contam, "reject": rej, "paired": comp, "strata": strat}
    with open(ctx.work / "results" / "exp1_mode_a_items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["condition", "seed", "path_id", "j", "decision", "valid", "contaminated", "affecting", "exposed", "hops", "known"])
        for c in conds:
            for (s, pid, j), x in per_path[c].items():
                w.writerow([c, s, pid, j, x["decision"], x["valid"], x["contaminated"], x["affecting"], x["exposed"], x["hops"], x["known"]])
    return "\n\n".join([
        "### Funnel (counts)",
        _md(["cond", "paths", "accept", "correct", "reject", "invalid", "tasks", "E1 fail", "E2 fail", "E3-rule fail",
             "E3-judge fail", "E4 fail", "valid"], funnel),
        "### Contamination (E5)",
        "Conditional = among valid tasks (Wilson CI, and cluster-bootstrap CI over anchors); per-path = accepted-and-contaminated over all paths (the paired outcome).",
        _md(["cond", "conditional % (Wilson)", "conditional % (cluster)", "per-path % (cluster)"], contam),
        "### Rejection and correction",
        _md(["cond", "precision: rejected/corrected paths that were answer-affecting", "recall: answer-affecting paths rejected/corrected",
             "correction accuracy"], rej),
        "### Paired differences of the per-path contamination indicator",
        "Cluster-bootstrap CI over anchors; exact McNemar (b10/b01 = discordant pairs); Holm-adjusted p.",
        _md(["contrast", "n paired", "diff (pp) [95% CI]", "b10/b01", "p (McNemar)", "p (Holm)"], comp),
        "### Strata (conditional contamination)",
        _md(["cond", "stratum", "% [95% CI]"], strat),
    ])


# ---------------------------------------------------------------------------------------------------
def section_mode_b(ctx: Context, S: dict, known: dict[str, bool]) -> str:
    recs = [r for r in read_jsonl(ctx.work / "exp1" / "mode_b.jsonl") if "error" not in r]
    if not recs:
        return "(no Mode B results)"
    rate = ctx.cfg["defects"]["main_rate"]
    resolver = KeyResolver(ctx.gs)
    pid2p = ctx.index.by_id
    strata = ctx.region["stratum"]
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        defs = [d for d in ctx.defects(rate, r["seed"]) if d["subject"] == r["entity"]]
        sc = score_report(ctx.gs, ctx.gw(rate, r["seed"]), resolver, r["entity"], r["gaps"], defs,
                          set(r["shown_pids"]), pid2p)
        for d in sc["defects"]:
            src = next(x for x in defs if x["defect_id"] == d["defect_id"])
            d["known"] = known.get(src["fid"])
            d["stratum"] = strata.get(r["entity"], "?")
        by_cond[r["condition"]].append({**sc, "seed": r["seed"]})

    rows, strat_rows = [], []
    for c in [x for x in LLM_ORDER if x in by_cond]:
        claims = [cl for sc in by_cond[c] for cl in sc["claims"]]
        cats = Counter(cl["category"] for cl in claims)
        den = sum(cats[k] for k in PRECISION_CATS)
        defs = [(d, sc["entity"]) for sc in by_cond[c] for d in sc["defects"]]
        det = [int(d["detected"]) for d, _ in defs]
        cl = [e for _, e in defs]
        exposed = [(d, e) for d, e in defs if d["exposed"]]
        rows.append([c, len(by_cond[c]), len(claims), cats["hit"], cats["located_only"], cats["false_gap"], cats["unsupported"],
                     cats["natural"], _wil(cats["hit"], den), _ci(det, cl),
                     _ci([int(d["detected"]) for d, _ in exposed], [e for _, e in exposed]) if exposed else "n/a",
                     _wil(sum(d["label_ok"] for d, _ in defs), sum(d["detected"] for d, _ in defs)),
                     _wil(sum(d["strict"] for d, _ in defs), len(defs))])
        for name, fn in [("delete", lambda d: d["op"] == "delete"), ("corrupt", lambda d: d["op"] == "corrupt"),
                         ("similar corruption", lambda d: d["hardness"] == "similar"),
                         ("random corruption", lambda d: d["hardness"] == "random"),
                         ("head entities", lambda d: d["stratum"] == "head"), ("tail entities", lambda d: d["stratum"] == "tail"),
                         ("known (closed-book)", lambda d: d["known"] is True), ("unknown (closed-book)", lambda d: d["known"] is False)]:
            sub = [d for d, _ in defs if fn(d)]
            strat_rows.append([c, name, _wil(sum(d["detected"] for d in sub), len(sub))])
    # C0 from the closed-book probe: corrupted facts whose true value the model recalls
    c0 = []
    ents = {r["entity"] for r in recs}
    for s in ctx.cfg["defects"]["seeds"]:
        for d in ctx.defects(rate, s):
            if d["subject"] in ents and d["fid"] in known:
                c0.append((d, known[d["fid"]]))
    if c0:
        cor = [k for d, k in c0 if d["op"] == "corrupt"]
        dele = [k for d, k in c0 if d["op"] == "delete"]
        strat_rows.append(["C0", "corruptions whose true value is recalled", _wil(sum(cor), len(cor))])
        strat_rows.append(["C0", "deletions whose value is recalled", _wil(sum(dele), len(dele))])
    S["mode_b"] = {"table": rows, "strata": strat_rows}
    return "\n\n".join([
        _md(["cond", "entities", "claims", "hit", "located-only", "false gap", "unsupported", "natural (excluded)",
             "precision %", "recall e2e %", "recall exposed %", "label acc %", "strict (FEVER-style) %"], rows),
        "### Recall by stratum (C0 = closed-book probe)", _md(["cond", "stratum", "recall % [95% CI]"], strat_rows)])


# ---------------------------------------------------------------------------------------------------
def section_quality(ctx: Context, S: dict) -> str:
    sol = [r for r in read_jsonl(ctx.work / "exp1" / "solver.jsonl") if "error" not in r]
    if not sol:
        return "(no Solver results)"
    tasks = {t["task_id"]: t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl")}
    k = ctx.cfg["exp1"]["solver"]["k"]
    acc: dict[tuple, list[int]] = defaultdict(list)
    for r in sol:
        t = tasks[r["task_id"]]
        acc[(r["task_id"], r["setting"])].append(int(match_any(r.get("answer", ""), t["gs_answers"])))
    hi, lo = math.ceil(0.75 * k), math.floor(0.25 * k)
    settings = set(ctx.cfg["exp1"]["solver"]["settings"])
    rows = []
    for c in [x for x in LLM_ORDER if any(t["condition"] == x for t in tasks.values())]:
        ids = sorted({tid for tid, _ in acc if tasks[tid]["condition"] == c})
        if not ids:
            continue
        cl = [tasks[i]["cluster"] for i in ids]
        g = {s: [sum(acc.get((i, s), [])) for i in ids] for s in ("gw", "gstar", "closed")}

        def ci(vals: list, *need: str) -> str:  # n/a when a required setting was not run
            return _ci(vals, cl) if all(n in settings for n in need) else "n/a"
        rows.append([c, len(ids), ci([x / k for x in g["gstar"]], "gstar"), ci([x / k for x in g["gw"]], "gw"),
                     ci([x / k for x in g["closed"]], "closed"),
                     ci([int(gs >= hi and gw <= lo) for gs, gw in zip(g["gstar"], g["gw"])], "gw", "gstar"),
                     ci([int(x >= hi) for x in g["closed"]], "closed"),
                     ci([int(lo < x < hi) if k > 1 else 0 for x in g["gstar"]], "gstar"),
                     ci([int(x == 0) for x in g["gstar"]], "gstar")])
    S["quality"] = rows
    return _md(["cond", "tasks", "Solver acc on G*", "acc on Gw", "closed-book acc", "gap-dependent", "closed-book leak",
                "frontier (25-75%)", "fails even on G*"], rows)


def section_judge(ctx: Context, S: dict) -> str:
    jd = read_jsonl(ctx.work / "exp1" / "judge.jsonl")
    if not jd:
        return "(no judge results)"
    tasks = {t["task_id"]: t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl")}
    by = defaultdict(list)
    for r in jd:
        if r.get("faithful") is not None and r["task_id"] in tasks:
            t = tasks[r["task_id"]]
            by[(t["condition"], t["source"])].append(int(r["faithful"]))
    rows = [[c, src, _wil(sum(v), len(v))] for (c, src), v in sorted(by.items())]
    out = _md(["cond", "task source", "judge: faithful % [95% CI]"], rows)
    labels = ctx.work / "audit" / "e3_audit_labels.csv"
    if labels.exists():
        from experiments.exp1.export_audit import judge_agreement
        ag = judge_agreement(ctx)
        S["judge_agreement"] = ag
        out += f"\n\nHuman audit: n={ag['n']}, judge accuracy vs. human majority {ag['judge_acc']:.3f}, " \
               f"Cohen's kappa between annotators {ag['kappa_humans']:.3f}, judge-vs-human kappa {ag['kappa_judge']:.3f}."
    S["judge"] = rows
    return out


def main() -> None:
    args = parse_args(__doc__, ["all"])
    ctx = setup(args, "exp1.analyze")
    (ctx.work / "results").mkdir(parents=True, exist_ok=True)
    S: dict = {}
    known = probe_known(ctx)
    parts = ["# Exp 1 report", "## Data", section_data(ctx, S), "## B0 dose-response (exact, no LLM)", b0_sweep(ctx, S),
             "## Mode A: task generation from paths", section_mode_a(ctx, S, known),
             "## E3 judge", section_judge(ctx, S),
             "## Mode B: gap discovery", section_mode_b(ctx, S, known),
             "## Task quality (Solver)", section_quality(ctx, S)]
    (ctx.work / "results" / "exp1_report.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    write_json(S, ctx.work / "results" / "exp1_summary.json")
    print(f"[analyze] wrote {ctx.work / 'results' / 'exp1_report.md'}")


if __name__ == "__main__":
    main()

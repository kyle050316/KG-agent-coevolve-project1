"""Exp 1 analysis: count tables (statistical tests are left for later).

Outputs (in <work_dir>/results/):
  exp1_report.md         markdown tables
  exp1_summary.json      all numbers
  exp1_mode_a_items.csv  one row per (condition, path)

Sections
  Data        regions, S, defects, sampled paths per group and type
  Mode A      decisions on defective and clean paths (independent of the question wording),
              E0-E4 funnel of the emitted tasks, wrong keys by cause, catch / false-alarm strata
  Mode B      precision, recall, label accuracy (+ located-only count), recall strata
  Gap tasks   answer-key status of the tasks compiled from gap reports
  E3 judge    faithful rate per condition and source (+ human agreement if labels exist)
  Solver      pass rates over k samples on Gw / G* / closed-book, against the task key and against
              G*; difficulty bins (target: 30-70%, i.e. 3-5 of 8) on tasks with a correct key

Usage:  python -m experiments.exp1.analyze --config configs/main.yaml
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict

from experiments.common import parse_args, setup
from kgcoevo.context import Context, rate_tag
from kgcoevo.eval.checks import answer_forms
from kgcoevo.eval.compare import answers_equal, match_any, mentions
from kgcoevo.eval.discovery import KeyResolver, score_report
from kgcoevo.runner import read_json, read_jsonl, write_json

COND_ORDER = ["B0", "C0", "C1", "C1know", "C2", "C3"]
TARGET = (0.3, 0.7)  # Solver pass rate that counts as "challenging" (3-5 of 8)


def _md(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _pc(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "0/0"


def _conds(present) -> list[str]:
    return [c for c in COND_ORDER if c in present] + sorted(set(present) - set(COND_ORDER))


def _in_text(value: str, text: str) -> bool:
    return bool(value and text) and any(mentions(text, f) for f in answer_forms(value))


def rate(ctx: Context) -> float:
    return ctx.cfg["defects"]["rate"]


# ---------------------------------------------------------------------------------------------------
def probe_known(ctx: Context) -> dict[str, bool]:
    """fid -> True if the majority of closed-book probe answers match G* (empty if C0 was not run)."""
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
    drows, prows = [], []
    for seed in ctx.cfg["defects"]["seeds"]:
        defs = ctx.defects(rate(ctx), seed)
        paths = ctx.paths(rate(ctx), seed)
        c = Counter(x["op"] for x in defs)
        drows.append([rate_tag(rate(ctx), seed), len(defs), c["delete"], c["corrupt"],
                      sum(x["hardness"] == "similar" for x in defs), sum(x["hardness"] == "random" for x in defs)])
        by = Counter((p.get("group", ""), p["ptype"]) for p in paths)
        for t in sorted({t for _, t in by}):
            prows.append([rate_tag(rate(ctx), seed), t, by[("defective", t)], by[("clean", t)]])
        prows.append([rate_tag(rate(ctx), seed), "all", sum(v for (g, _), v in by.items() if g == "defective"),
                      sum(v for (g, _), v in by.items() if g == "clean")])
    S["data"] = {"region_A": len(reg["A"]), "region_B": len(reg["B"]), "support": sup, "defects": drows, "paths": prows}
    return "\n\n".join([
        f"Region A: {len(reg['A'])} entities; region B: {len(reg['B'])}; candidate pool {reg['pool_size']}. "
        f"Facts of A and B: {sup['facts']}; supported (S): {sup['supported']}.",
        _md(["KG", "defects", "deleted", "corrupted", "similar corruptions", "random corruptions"], drows),
        "Mode A paths. Defective: the path uses a corrupted fact and its G* answer differs from the Gw answer. "
        "Clean: no fact changed, first hop in S, same answer on Gw and G*. Deleted facts cannot lie on a Gw path "
        "and are measured in Mode B.",
        _md(["KG", "path type", "defective", "clean"], prows)])


# ---------------------------------------------------------------------------------------------------
def mode_a_records(ctx: Context, known: dict[str, bool]) -> dict[str, list[dict]]:
    """cond -> one record per Challenger decision, joined with its path, task checks and judge label."""
    seeds = ctx.cfg["defects"]["seeds"]
    paths = {(s, p["path_id"]): p for s in seeds for p in ctx.paths(rate(ctx), s)}
    defects = {s: {d["defect_id"]: d for d in ctx.defects(rate(ctx), s)} for s in seeds}
    tasks = {t["task_id"]: t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl")}
    judged = {r["task_id"]: r.get("faithful") for r in read_jsonl(ctx.work / "exp1" / "judge.jsonl")}
    strata = ctx.region.get("stratum", {})
    out: dict[str, list[dict]] = defaultdict(list)
    for r in read_jsonl(ctx.work / "exp1" / "mode_a.jsonl"):
        if "error" in r:
            continue
        p = paths[(r["seed"], r["path_id"])]
        tid = f"A|{r['condition']}|{r['seed']}|{r['path_id']}|{r['j']}"
        dec = r["decision"]
        emitted = dec in ("accept", "correct")
        key_ok = bool(emitted and len(p["gs_answers"]) == 1 and match_any(r["answer"], p["gs_answers"]))
        # what counts is the emitted key: "correct" with the Gw answer unchanged is in effect an accept
        changed = bool(emitted and not answers_equal(r["answer"], p["answer_gw"]))
        eff = {"accept": "keep", "correct": "fix" if changed else "keep"}.get(dec, dec)  # keep|fix|reject|invalid
        group = p.get("group") or ("defective" if p["answer_affecting"] else "clean")
        if not emitted or key_ok:
            cause = ""
        elif group == "defective":
            cause = "defect passed" if not changed else "failed fix"
        else:
            cause = "introduced"
        ds = [defects[r["seed"]][i] for i in p.get("defect_ids", []) if i in defects[r["seed"]]]
        t = tasks.get(tid)
        out[r["condition"]].append({
            "seed": r["seed"], "path_id": r["path_id"], "j": r["j"], "group": group, "ptype": p["ptype"],
            "hops": p["hops"], "anchor": p["anchor"], "stratum": strata.get(p["anchor"], "?"), "decision": dec,
            "eff": eff, "flagged_kept": dec == "correct" and not changed,
            "emitted": emitted, "key_ok": key_ok, "cause": cause,
            "grounded": bool(eff == "fix" and _in_text(r["answer"], r.get("evidence_text", ""))),
            "task": t, "judge": judged.get(tid),
            "valid": bool(t and t["valid"] and judged.get(tid) is not False),
            "hardness": ds[0]["hardness"] if ds else "", "subtype": ds[0]["subtype"] if ds else "",
            "known": (any(known.get(d["fid"]) for d in ds) if ds and any(d["fid"] in known for d in ds) else None)})
    return out


def section_mode_a(ctx: Context, S: dict, known: dict[str, bool]) -> str:
    recs = mode_a_records(ctx, known)
    conds = _conds(recs)
    dfc, cln, emit, funnel, strat = [], [], [], [], []
    for c in conds:
        d = [x for x in recs[c] if x["group"] == "defective"]
        k = [x for x in recs[c] if x["group"] == "clean"]
        dd, kd = Counter(x["eff"] for x in d), Counter(x["eff"] for x in k)
        dfc.append([c, len(d), _pc(dd["keep"], len(d)), _pc(sum(x["flagged_kept"] for x in d), len(d)),
                    _pc(sum(x["eff"] == "fix" and x["key_ok"] for x in d), len(d)),
                    _pc(sum(x["eff"] == "fix" and not x["key_ok"] for x in d), len(d)),
                    _pc(dd["reject"], len(d)), _pc(dd["invalid"], len(d)), _pc(dd["reject"] + dd["fix"], len(d))])
        cln.append([c, len(k), _pc(kd["keep"], len(k)), _pc(sum(x["flagged_kept"] for x in k), len(k)),
                    _pc(kd["fix"], len(k)), _pc(kd["reject"], len(k)), _pc(kd["invalid"], len(k))])
        e = [x for x in recs[c] if x["emitted"]]
        cause = Counter(x["cause"] for x in e)
        corr = [x for x in recs[c] if x["eff"] == "fix"]
        emit.append([c, len(e), _pc(sum(not x["key_ok"] for x in e), len(e)), cause["defect passed"],
                     cause["failed fix"], cause["introduced"], len(corr), _pc(sum(x["grounded"] for x in corr), len(corr))])
        ts = [x for x in e if x["task"]]
        st = Counter(x["task"]["stage"] for x in ts)
        v = [x for x in ts if x["valid"]]
        vc = Counter(x["cause"] for x in v)
        funnel.append([c, len(e), st["E0"], st["E1"], st["E2"], st["E3"],
                       sum(1 for x in ts if x["task"]["valid"] and x["judge"] is False), st["E4"], len(v),
                       sum(not x["key_ok"] for x in v), vc["defect passed"], vc["failed fix"], vc["introduced"]])
        caught = lambda xs: _pc(sum(x["eff"] in ("reject", "fix") for x in xs), len(xs))  # noqa: E731
        for name, fn in [("1-hop", lambda x: x["hops"] == 1), ("2-hop", lambda x: x["hops"] == 2),
                         ("head entity", lambda x: x["stratum"] == "head"), ("torso entity", lambda x: x["stratum"] == "torso"),
                         ("tail entity", lambda x: x["stratum"] == "tail")]:
            strat.append([c, name, caught([x for x in d if fn(x)]), caught([x for x in k if fn(x)])])
        for name, fn in [("similar corruption", lambda x: x["hardness"] == "similar"),
                         ("random corruption", lambda x: x["hardness"] == "random")] + \
                [(f"subtype {s}", (lambda s: lambda x: x["subtype"] == s)(s)) for s in sorted({x["subtype"] for x in d})] + \
                ([("defect known (closed-book)", lambda x: x["known"] is True),
                  ("defect unknown (closed-book)", lambda x: x["known"] is False)] if known else []):
            strat.append([c, name, caught([x for x in d if fn(x)]), "–"])
    S["mode_a"] = {"defective": dfc, "clean": cln, "emitted": emit, "funnel": funnel, "strata": strat}
    with open(ctx.work / "results" / "exp1_mode_a_items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["condition", "seed", "path_id", "j", "group", "ptype", "hops", "stratum", "decision", "effective", "emitted",
                    "key_ok", "cause", "grounded", "valid", "hardness", "subtype", "known"])
        for c in conds:
            for x in recs[c]:
                w.writerow([c, x["seed"], x["path_id"], x["j"], x["group"], x["ptype"], x["hops"], x["stratum"], x["decision"], x["eff"],
                            x["emitted"], x["key_ok"], x["cause"], x["grounded"], x["valid"], x["hardness"], x["subtype"], x["known"]])
    return "\n\n".join([
        "Decision-level counts on the shared paths (do not depend on how the question is worded). What counts is the "
        "emitted key: a \"correct\" decision that keeps the Gw answer is counted as *kept* (the model flagged a fact but "
        "did not change the key; shown separately as \"flagged, key kept\"); *fixed* = the key was changed.",
        "### Defective paths",
        "kept = the defect passes into the task; fixed right = the new key equals G*; caught = rejected or key changed.",
        _md(["cond", "paths", "kept (defect passed)", "of which flagged, key kept", "fixed, right value", "fixed, wrong value",
             "reject", "invalid", "caught"], dfc),
        "### Clean paths",
        _md(["cond", "paths", "kept", "of which flagged, key kept", "false fix (key changed)", "false reject", "invalid"], cln),
        "### Emitted tasks (accept + correct) with a wrong answer key, by cause",
        "defect passed = accepted defective path; failed fix = corrected a defective path to a wrong value; "
        "introduced = changed the key of a clean path. Corrections = key changes; grounded = the new key appears in the "
        "evidence shown.",
        _md(["cond", "emitted", "wrong key", "defect passed", "failed fix", "introduced", "corrections", "grounded corrections"],
            emit),
        "### Funnel of emitted tasks (E0-E5)",
        "E5 = valid tasks (E0-E4, E3 rules and judge) whose key differs from G*.",
        _md(["cond", "emitted", "E0 fail", "E1 fail", "E2 fail", "E3-rule fail", "E3-judge fail", "E4 fail", "valid",
             "E5 wrong key", "E5: defect passed", "E5: failed fix", "E5: introduced"], funnel),
        "### Strata",
        "caught = rejected or key changed (on defective paths); false alarm = rejected or key changed (on clean paths).",
        _md(["cond", "stratum", "defective: caught", "clean: false alarm"], strat),
    ])


# ---------------------------------------------------------------------------------------------------
def section_mode_b(ctx: Context, S: dict, known: dict[str, bool]) -> str:
    recs = [r for r in read_jsonl(ctx.work / "exp1" / "mode_b.jsonl") if "error" not in r]
    if not recs:
        return "(no Mode B results)"
    resolver = KeyResolver(ctx.gs)
    strata = ctx.region.get("stratum", {})
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        defs = [d for d in ctx.defects(rate(ctx), r["seed"]) if d["subject"] == r["entity"]]
        sc = score_report(ctx.gs, ctx.gw(rate(ctx), r["seed"]), resolver, r["entity"], r["gaps"], defs)
        for d in sc["defects"]:
            src = next(x for x in defs if x["defect_id"] == d["defect_id"])
            d["known"] = known.get(src["fid"])
            d["stratum"] = strata.get(r["entity"], "?")
        by_cond[r["condition"]].append(sc)
    rows, strat_rows = [], []
    for c in _conds(by_cond):
        claims = [cl for sc in by_cond[c] for cl in sc["claims"]]
        cats = Counter(cl["category"] for cl in claims)
        defs = [d for sc in by_cond[c] for d in sc["defects"]]
        det = [d for d in defs if d["detected"]]
        rows.append([c, len(by_cond[c]), len(claims), cats["hit"], cats["located_only"], cats["other"],
                     _pc(cats["hit"], len(claims)), len(defs), _pc(len(det), len(defs)),
                     _pc(sum(d["label_ok"] for d in det), len(det))])
        for name, fn in [("deleted", lambda d: d["op"] == "delete"), ("corrupted", lambda d: d["op"] == "corrupt"),
                         ("similar corruption", lambda d: d["hardness"] == "similar"),
                         ("random corruption", lambda d: d["hardness"] == "random"),
                         ("head entity", lambda d: d["stratum"] == "head"), ("torso entity", lambda d: d["stratum"] == "torso"),
                         ("tail entity", lambda d: d["stratum"] == "tail")] + \
                ([("known (closed-book)", lambda d: d["known"] is True),
                  ("unknown (closed-book)", lambda d: d["known"] is False)] if known else []):
            sub = [d for d in defs if fn(d)]
            strat_rows.append([c, name, _pc(sum(d["detected"] for d in sub), len(sub))])
    if known:  # C0: what the closed-book probe recalls for the same defects
        ents = {r["entity"] for r in recs}
        c0 = [(d, known[d["fid"]]) for s in ctx.cfg["defects"]["seeds"] for d in ctx.defects(rate(ctx), s)
              if d["subject"] in ents and d["fid"] in known]
        for op, name in [("corrupt", "corruptions whose true value is recalled"), ("delete", "deletions whose value is recalled")]:
            v = [k for d, k in c0 if d["op"] == op]
            strat_rows.append(["C0", name, _pc(sum(v), len(v))])
    S["mode_b"] = {"table": rows, "strata": strat_rows}
    return "\n\n".join([
        "Each claim is a hit (key and true value of an injected defect) or an error. Located-only = an error on the key of "
        "a defect with a wrong value; other = every other error (already in Gw, not in G*, unresolvable, or a real gap of "
        "the original KB, which is counted as an error because there is no human audit).",
        _md(["cond", "entities", "claims", "hits", "located-only", "other errors", "precision", "defects", "recall",
             "label accuracy"], rows),
        "### Recall by stratum", _md(["cond", "stratum", "detected"], strat_rows)])


def section_gap_tasks(ctx: Context, S: dict) -> str:
    tasks = [t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl") if t["source"] == "gap"]
    if not tasks:
        return "(no gap tasks)"
    judged = {r["task_id"]: r.get("faithful") for r in read_jsonl(ctx.work / "exp1" / "judge.jsonl")}
    by = defaultdict(list)
    for t in tasks:
        by[t["condition"]].append(t)
    rows = []
    for c in _conds(by):
        ts = by[c]
        ok = [t for t in ts if t.get("e0")]
        rows.append([c, len(ts), len(ts) - len(ok), sum(t.get("e3_rules") is False for t in ok),
                     sum(judged.get(t["task_id"]) is False for t in ok),
                     _pc(sum(t.get("key_ok", False) for t in ok), len(ok)),
                     sum(bool(t.get("gs_empty")) for t in ok),
                     sum(len(t.get("gs_answers", [])) > 1 for t in ok),
                     sum(len(t.get("gs_answers", [])) == 1 and not t.get("key_ok") for t in ok)])
    S["gap_tasks"] = rows
    return "\n\n".join([
        "One task per entity from its first resolvable claim; the key is the claimed value and is checked on G*. "
        "A wrong key here is the Challenger's error (a wrong gap claim), not a KG error.",
        _md(["cond", "tasks", "E0 fail", "E3-rule fail", "E3-judge fail", "key correct", "key wrong: fact not in G*",
             "ambiguous: several values in G*", "key wrong: other value"], rows)])


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
    rows = [[c, src, _pc(sum(v), len(v))] for (c, src), v in sorted(by.items(), key=lambda x: (COND_ORDER.index(x[0][0])
                                                                                            if x[0][0] in COND_ORDER else 99, x[0][1]))]
    out = "The judge is the same model as the Challenger (one model is available), so it may favour its own questions.\n\n"
    out += _md(["cond", "task source", "judged faithful"], rows)
    labels = ctx.work / "audit" / "e3_audit_labels.csv"
    if labels.exists():
        from experiments.exp1.export_audit import judge_agreement
        ag = judge_agreement(ctx)
        S["judge_agreement"] = ag
        out += f"\n\nHuman audit: n={ag['n']}, judge accuracy vs. human majority {ag['judge_acc']:.3f}, " \
               f"Cohen's kappa between annotators {ag['kappa_humans']:.3f}, judge-vs-human kappa {ag['kappa_judge']:.3f}."
    S["judge"] = rows
    return out


# ---------------------------------------------------------------------------------------------------
def _bins(k: int) -> list[tuple[str, callable]]:
    lo, hi = math.ceil(TARGET[0] * k), math.floor(TARGET[1] * k)

    def rng(a: int, b: int) -> str:
        return "–" if a > b else (f"{a}/{k}" if a == b else f"{a}-{b}/{k}")
    return [(f"0/{k}", lambda c: c == 0), (rng(1, lo - 1), lambda c: 0 < c < lo),
            (f"{rng(lo, hi)} (target)", lambda c: lo <= c <= hi and 0 < c < k), (rng(hi + 1, k - 1), lambda c: hi < c < k),
            (f"{k}/{k}", lambda c: c == k)]


def section_solver(ctx: Context, S: dict) -> str:
    sol = [r for r in read_jsonl(ctx.work / "exp1" / "solver.jsonl") if "error" not in r]
    if not sol:
        return "(no Solver results)"
    tasks = {t["task_id"]: t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl")}
    conf = ctx.cfg["exp1"]["solver"]
    k, settings = conf["k"], [s for s in ("gw", "gstar", "closed") if s in conf["settings"]]
    hi, lo = math.ceil(0.75 * k), math.floor(0.25 * k)
    vs_key: dict[tuple, int] = Counter()
    vs_gs: dict[tuple, int] = Counter()
    for r in sol:
        t = tasks[r["task_id"]]
        a = r.get("answer", "")
        vs_key[(r["task_id"], r["setting"])] += int(answers_equal(a, t["answer"]))
        vs_gs[(r["task_id"], r["setting"])] += int(bool(t.get("gs_answers")) and match_any(a, t["gs_answers"]))
    groups: dict[tuple, list[str]] = defaultdict(list)
    for tid in sorted({tid for tid, _ in vs_key}):
        t = tasks[tid]  # Mode A tasks are split by path group: corrected defective tasks are unanswerable on Gw
        groups[(t["condition"], t["source"] + (f"/{t['group']}" if t.get("group") else ""))].append(tid)
    order = sorted(groups, key=lambda g: (g[1].split("/")[0] != "mode_a", g[1], COND_ORDER.index(g[0]) if g[0] in COND_ORDER else 99))
    bins = _bins(k)
    rates, diff, wrong = [], [], []
    for g in order:
        ids = groups[g]
        good = [i for i in ids if tasks[i].get("key_ok", not tasks[i].get("contaminated"))]
        bad = [i for i in ids if i not in set(good)]
        row = [g[0], g[1], len(ids), len(good)]
        for s in settings:
            row += [f"{100 * sum(vs_key[(i, s)] for i in ids) / (k * len(ids)):.0f}%",
                    f"{100 * sum(vs_gs[(i, s)] for i in ids) / (k * len(ids)):.0f}%"]
        rates.append(row)
        if "gw" in settings:
            drow = [g[0], g[1], len(good)] + [_pc(sum(fn(vs_gs[(i, "gw")]) for i in good), len(good)) for _, fn in bins]
            if "gstar" in settings:
                drow.append(_pc(sum(vs_gs[(i, "gstar")] >= hi and vs_gs[(i, "gw")] <= lo for i in good), len(good)))
            if "closed" in settings:
                drow.append(_pc(sum(vs_gs[(i, "closed")] >= hi for i in good), len(good)))
            diff.append(drow)
            wrong.append([g[0], g[1], len(bad), _pc(sum(vs_key[(i, "gw")] >= hi for i in bad), len(bad)),
                          _pc(sum(vs_gs[(i, "gw")] >= hi for i in bad), len(bad))])
    S["solver"] = {"rates": rates, "difficulty": diff, "wrong_key": wrong}
    hdr = ["cond", "source", "tasks", "key correct"]
    for s in settings:
        hdr += [f"{s}: pass vs key", f"{s}: pass vs G*"]
    parts = [f"k = {k} Solver samples per task and setting; pass rate = share of the k answers that match.",
             "### Pass rates", _md(hdr, rates)]
    if diff:
        dh = ["cond", "source", "tasks with correct key"] + [b for b, _ in bins]
        dh += (["gap-dependent (G* >= %d, Gw <= %d)" % (hi, lo)] if "gstar" in settings else [])
        dh += (["closed-book leak (closed >= %d)" % hi] if "closed" in settings else [])
        parts += ["### Difficulty on Gw (tasks with a correct key; correct = matches G*)",
                  f"Target: {int(TARGET[0] * 100)}-{int(TARGET[1] * 100)}% of the {k} answers correct.", _md(dh, diff),
                  "### Tasks with a wrong key on Gw",
                  f"agrees with key = the Solver on Gw returns the wrong key in >= {hi}/{k} samples: the reward would "
                  "confirm the wrong fact and the error stays hidden.",
                  _md(["cond", "source", "tasks with wrong key", "Solver agrees with key", "Solver matches G*"], wrong)]
    return "\n\n".join(parts)


def main() -> None:
    args = parse_args(__doc__, ["all"])
    ctx = setup(args, "exp1.analyze")
    (ctx.work / "results").mkdir(parents=True, exist_ok=True)
    S: dict = {}
    known = probe_known(ctx)
    parts = ["# Exp 1 report", "Counts only; statistical tests are to be added later.",
             "## Data", section_data(ctx, S),
             "## Mode A: task generation from paths", section_mode_a(ctx, S, known),
             "## Mode B: gap discovery", section_mode_b(ctx, S, known),
             "## Gap tasks", section_gap_tasks(ctx, S),
             "## E3 judge", section_judge(ctx, S),
             "## Task quality (Solver)", section_solver(ctx, S)]
    (ctx.work / "results" / "exp1_report.md").write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    write_json(S, ctx.work / "results" / "exp1_summary.json")
    print(f"[analyze] wrote {ctx.work / 'results' / 'exp1_report.md'}")


if __name__ == "__main__":
    main()

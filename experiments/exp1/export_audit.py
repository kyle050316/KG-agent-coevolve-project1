"""Human-audit sheets for Exp 1 (blinded and shuffled) and agreement statistics.

  e3_audit.csv            question / program / answer key, two annotator columns (faithful 1/0)
  e3_audit_key.json       audit_id -> task_id (do not show to annotators)
  natural_gaps_audit.csv  claims scored "natural": is the passage really stating a KG gap? (1/0)

After labelling, save the filled sheet as audit/e3_audit_labels.csv; `analyze` then reports
inter-annotator kappa and the judge's accuracy against the human majority.

Usage:  python -m experiments.exp1.export_audit --config configs/exp1_2day.yaml
"""

from __future__ import annotations

import csv
import random

from experiments.common import parse_args, setup
from kgcoevo.context import Context
from kgcoevo.eval.discovery import KeyResolver, score_report
from kgcoevo.eval.stats import cohen_kappa
from kgcoevo.runner import read_json, read_jsonl, write_json


def export(ctx: Context) -> None:
    n = ctx.cfg["exp1"]["audit"]["e3_n"]
    rng = random.Random(ctx.cfg["seed"])
    tasks = [t for t in read_jsonl(ctx.work / "exp1" / "tasks.jsonl") if t.get("e0") and t.get("e1")]
    by: dict[str, list] = {}
    for t in tasks:
        by.setdefault(t["condition"], []).append(t)
    picked = []
    per = max(1, n // max(1, len(by)))
    for c, ts in sorted(by.items()):
        rng.shuffle(ts)
        picked += ts[:per]
    rng.shuffle(picked)
    audit_dir = ctx.work / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    key = {}
    with (audit_dir / "e3_audit.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["audit_id", "question", "program", "answer_key", "annotator_1 (faithful 1/0)", "annotator_2 (faithful 1/0)"])
        for i, t in enumerate(picked):
            aid = f"q{i:04d}"
            key[aid] = t["task_id"]
            w.writerow([aid, t["question"], t["description"], t["answer"], "", ""])
    write_json(key, audit_dir / "e3_audit_key.json")

    # natural-gap claims
    rate = ctx.cfg["defects"]["main_rate"]
    resolver = KeyResolver(ctx.gs)
    rows = []
    for r in read_jsonl(ctx.work / "exp1" / "mode_b.jsonl"):
        if "error" in r:
            continue
        defs = [d for d in ctx.defects(rate, r["seed"]) if d["subject"] == r["entity"]]
        sc = score_report(ctx.gs, ctx.gw(rate, r["seed"]), resolver, r["entity"], r["gaps"], defs, set(r["shown_pids"]),
                          ctx.index.by_id)
        for cl in sc["claims"]:
            if cl["category"] == "natural":
                p = ctx.index.by_id.get(cl["evidence_id"])
                rows.append([r["condition"], ctx.gs.name(r["entity"]), cl["key"], cl["claimed_value"], cl["label"],
                             p.text if p else "", ""])
    rng.shuffle(rows)
    with (audit_dir / "natural_gaps_audit.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["condition", "entity", "key", "claimed_value", "label", "passage", "true KG gap? (1/0)"])
        w.writerows(rows[: ctx.cfg["exp1"]["audit"]["natural_n"]])
    print(f"[audit] {len(picked)} E3 items, {min(len(rows), ctx.cfg['exp1']['audit']['natural_n'])} natural-gap items")


def judge_agreement(ctx: Context) -> dict:
    audit_dir = ctx.work / "audit"
    key = read_json(audit_dir / "e3_audit_key.json")
    judged = {r["task_id"]: r.get("faithful") for r in read_jsonl(ctx.work / "exp1" / "judge.jsonl")}
    h1, h2, maj, jg = [], [], [], []
    with (audit_dir / "e3_audit_labels.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            a = row.get("annotator_1 (faithful 1/0)", "").strip()
            b = row.get("annotator_2 (faithful 1/0)", "").strip()
            if a not in ("0", "1") or b not in ("0", "1"):
                continue
            h1.append(int(a))
            h2.append(int(b))
            m = int(a) if a == b else int(a)  # ties resolved by annotator 1 (adjudicate before final reporting)
            j = judged.get(key.get(row["audit_id"]))
            if j is not None:
                maj.append(m)
                jg.append(int(bool(j)))
    return {"n": len(h1), "kappa_humans": cohen_kappa(h1, h2),
            "judge_acc": (sum(int(a == b) for a, b in zip(maj, jg)) / len(jg)) if jg else float("nan"),
            "kappa_judge": cohen_kappa(maj, jg) if jg else float("nan")}


def main() -> None:
    args = parse_args(__doc__, ["all"])
    export(setup(args, "exp1.export_audit"))


if __name__ == "__main__":
    main()

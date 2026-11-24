"""Exp 1 data preparation (CPU only).

Stages
  kilt      stream KILT once and keep the pages of KB entities
  region    choose anchor entities, split into region A (Exp 1) and region B (Exp 2)
  passages  chunk pages of region entities and their neighbours into passages (with gold links)
  support   build S (document-supported facts) + an audit sample for the human check
  defects   inject defects into S (region A) for every seed; build Gw; self-check
  paths     sample Mode A paths on Gw in two groups (defective / clean), annotate G* answers
  probe     closed-book probe items (C0) for every supported fact of region A

Usage:  python -m experiments.exp1.prepare --config configs/main.yaml [--stages ...]
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from experiments.common import parse_args, selected, setup
from kgcoevo.context import Context, rate_tag
from kgcoevo.data.defects import build_gw, inject_defects, self_check
from kgcoevo.data.region import select_regions
from kgcoevo.data.support import build_support, pages_index, summarize_support
from kgcoevo.docs.kilt import extract_kb_pages, page_words
from kgcoevo.docs.passages import build_passages, save_passages
from kgcoevo.eval.compare import answers_equal
from kgcoevo.kb.executor import Executor
from kgcoevo.kb.paths import DirectedSampler
from kgcoevo.kb.store import KBStore
from kgcoevo.runner import write_json, write_jsonl

STAGES = ["kilt", "region", "passages", "support", "defects", "paths", "probe"]


def stage_kilt(ctx: Context) -> None:
    out = Path(ctx.cfg["paths"]["kilt_pages"])
    if out.exists() and not ctx.cfg.get("force", False):
        print(f"[kilt] {out} exists, skipping")
        return
    stats = extract_kb_pages(ctx.cfg["paths"]["kilt_source"], set(ctx.gs.entities), out,
                             limit=ctx.cfg.get("kilt_limit"))
    print("[kilt]", stats)


def stage_region(ctx: Context) -> None:
    c = ctx.cfg["region"]
    words = {q: page_words(p) for q, p in ctx.pages.items()}
    qs = ctx.questions("train") + ctx.questions("val")
    region = select_regions(ctx.gs, words, concept=c["concept"], n_a=c["n_a"], n_b=c["n_b"], min_facts=c["min_facts"],
                            min_page_words=c["min_page_words"], seed=ctx.cfg["seed"], questions=qs,
                            min_questions_b=c.get("min_questions_b", 3))
    write_json(region, ctx.data / "region.json")
    print(f"[region] pool={region['pool_size']} A={len(region['A'])} B={len(region['B'])}")


def stage_passages(ctx: Context) -> None:
    reg = ctx.region
    ents = set(reg["A"]) | set(reg["B"])
    qids = set(ents)
    for e in ents:
        qids |= ctx.gs.neighbors(e)
    qids &= set(ctx.pages)
    ps = build_passages(ctx.pages, qids, max_words=ctx.cfg["docs"]["max_words"])
    save_passages(ps, ctx.data / "passages.jsonl")
    print(f"[passages] pages={len(qids)} passages={len(ps)}")


def stage_support(ctx: Context) -> None:
    reg = ctx.region
    recs = build_support(ctx.gs, pages_index(ctx.passages), reg["A"] + reg["B"])
    write_jsonl(recs, ctx.data / "support.jsonl")
    summary = summarize_support(recs)
    write_json(summary, ctx.data / "support_summary.json")
    # audit sample: supported facts, stratified by method, for a precision check by a human
    rng = random.Random(ctx.cfg["seed"])
    sup = [r for r in recs if r["supported"]]
    rng.shuffle(sup)
    n = ctx.cfg["support"]["audit_n"]
    audit_dir = ctx.work / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / "support_audit.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fid", "method", "fact", "sentence", "supported_by_sentence (1/0)"])
        for r in sup[:n]:
            w.writerow([r["fid"], r["method"], r["text"], r["sentence"], ""])
    print(f"[support] facts={summary['facts']} supported={summary['supported']} -> audit {min(n, len(sup))} rows")


def stage_defects(ctx: Context) -> None:
    d = ctx.cfg["defects"]
    reg = ctx.region
    rate = d["rate"]
    for seed in d["seeds"]:
        out = ctx.gw_dir(rate, seed)
        defects = inject_defects(ctx.gs, ctx.support, rate=rate, seed=seed * 1000, scope=reg["A"],
                                 delete_frac=d["delete_frac"], similar_frac=d["similar_frac"])
        kb = build_gw(ctx.gs, defects)
        write_json(kb, out / "kb.json")
        write_jsonl([x.to_json() for x in defects], out / "defects.jsonl")
        gw = KBStore(kb, normalized=True)
        check = self_check(ctx.gs, gw, Executor.from_store(gw), defects)
        write_json(check, out / "selfcheck.json")
        print(f"[defects] {rate_tag(rate, seed)}: {len(defects)} defects, self-check failures={check['n_failed']}")
        if check["n_failed"]:
            raise SystemExit("self-check failed: see selfcheck.json")


def annotate_path(ctx: Context, p: dict) -> dict:
    res = ctx.gs_exec.run(p["program"])
    gs_cids = ctx.gs.cid_to_fid
    p["gs_answers"], p["gs_error"] = res.answers, res.error
    p["exposed"] = any(c not in gs_cids for c in p["fact_cids"])
    p["answer_affecting"] = not (res.unique and answers_equal(res.answers[0], p["answer_gw"]))
    return p


def stage_paths(ctx: Context) -> None:
    """Directed sampling: ``n_defective`` paths through corrupted facts and ``n_clean`` paths whose
    first hop is an unchanged S fact (see kgcoevo.kb.paths.DirectedSampler)."""
    c = ctx.cfg["paths_sampling"]
    rate = ctx.cfg["defects"]["rate"]
    s_cids = {r["cid"] for r in ctx.support if r["supported"]}
    gs_cids = set(ctx.gs.cid_to_fid)
    for seed in ctx.cfg["defects"]["seeds"]:
        gw, gwx = ctx.gw(rate, seed), ctx.gw_exec(rate, seed)
        sampler = DirectedSampler(gw, gwx, ctx.gs_exec, gs_cids, s_cids, seed=seed)
        paths, stats = sampler.sample(ctx.region["A"], ctx.defects(rate, seed), c["n_defective"], c["n_clean"],
                                      c["type_weights"], max_per_defect=c.get("max_per_defect", 2))
        rows = [annotate_path(ctx, p.to_json()) for p in paths]
        tag = rate_tag(rate, seed)
        write_jsonl(rows, ctx.data / "paths" / f"{tag}.jsonl")
        write_json(stats, ctx.data / "paths" / f"{tag}_stats.json")
        print(f"[paths] {tag}: defective={stats['n_defective']} (from {stats['defects_with_a_path']} of "
              f"{stats['corrupt_defects_in_scope']} corrupted facts), clean={stats['n_clean']}")
        if stats["n_defective"] < c["n_defective"]:
            print(f"[paths] WARNING: only {stats['n_defective']} defective paths (wanted {c['n_defective']}); "
                  "raise paths_sampling.max_per_defect or the defect rate, or lower n_defective")
        ctx.release_gw()


def stage_probe(ctx: Context) -> None:
    if not ctx.cfg["exp1"]["probe"].get("enabled", True):
        print("[probe] C0 closed-book probe disabled (exp1.probe.enabled=false)")
        return
    items = []
    A = set(ctx.region["A"])
    for r in ctx.support:
        if not r["supported"] or r["subject"] not in A:
            continue
        f = ctx.gs.facts[r["fid"]]
        if f.kind == "qual":
            parent = ctx.gs.facts[f.parent]
            note = f" (qualifier of the fact: {ctx.gs.fact_text(parent, show_quals=False)})"
            key, gold = f.key, f.vstr
        else:
            note = ""
            key = f.key
            gold = ctx.gs.name(f.value) if f.kind == "rel" else f.vstr
        items.append({"item_id": f.fid, "fid": f.fid, "cid": r["cid"], "entity": f.subject, "kind": f.kind,
                      "key": key, "gold": gold, "qualifier_note": note})
    write_jsonl(items, ctx.data / "probe_items.jsonl")
    print(f"[probe] {len(items)} probe items")


def main() -> None:
    args = parse_args(__doc__, STAGES)
    ctx = setup(args, "exp1.prepare")
    for st in STAGES:
        if selected(args, st, STAGES):
            globals()[f"stage_{st}"](ctx)


if __name__ == "__main__":
    main()

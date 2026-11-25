"""Select the anchor entities of the experiment and split them into disjoint regions.

* Region A: Exp 1 (task generation / gap discovery); later the Exp 3 training region.
* Region B: Exp 2 (Curator cases) and held-out evaluation; chosen among entities that KQA Pro
  questions actually talk about, so Exp 2 has enough gold-program cases.

Popularity is stratified with the Wikipedia article length as a proxy (PopQA, Mallen et al. 2023,
show that LLM memorisation depends strongly on entity popularity).
"""

from __future__ import annotations

import random
from collections import Counter

import numpy as np

from kgcoevo.kb.paths import find_prefix
from kgcoevo.kb.store import KBStore


def popularity_strata(words: dict[str, int], qids: list[str]) -> dict[str, str]:
    vals = np.array([words.get(q, 0) for q in qids], dtype=float)
    if len(vals) == 0:
        return {}
    lo, hi = np.quantile(vals, [1 / 3, 2 / 3])
    return {q: ("tail" if words.get(q, 0) <= lo else "head" if words.get(q, 0) > hi else "torso") for q in qids}


def question_coverage(store: KBStore, questions: list[dict]) -> Counter:
    """How many KQA Pro questions start from each entity (Find inputs resolved by name)."""
    cov: Counter = Counter()
    for q in questions:
        for st in q.get("program", []):
            if st["function"] == "Find":
                for eid in store.name_to_ids.get(st["inputs"][0], []):
                    cov[eid] += 1
    return cov


def select_regions(store: KBStore, page_words: dict[str, int], *, concept: str = "human", n_a: int = 200,
                   n_b: int = 200, min_facts: int = 8, min_page_words: int = 150, seed: int = 0,
                   questions: list[dict] | None = None, min_questions_b: int = 3, n_b_extra: int = 0) -> dict:
    """``n_b_extra`` adds more region-B entities after A and the first ``n_b`` B entities are chosen,
    so A and the core of B are the same as with ``n_b_extra=0`` (Exp 1 data stay valid)."""
    rng = random.Random(seed)
    pool = []
    for eid in store.entities_with_concept(concept):
        if page_words.get(eid, 0) < min_page_words:
            continue
        if len(store.facts_of(eid, ("attr", "rel"))) + len(store.rel_in(eid)) < min_facts:
            continue
        if find_prefix(store, eid) is None:
            continue
        pool.append(eid)
    strata = popularity_strata(page_words, pool)
    cov = question_coverage(store, questions) if questions else Counter()

    def stratified(cands: list[str], n: int) -> list[str]:
        by: dict[str, list[str]] = {"head": [], "torso": [], "tail": []}
        for q in cands:
            by[strata[q]].append(q)
        for v in by.values():
            rng.shuffle(v)
        out: list[str] = []
        while len(out) < n and any(by.values()):
            for k in ("head", "torso", "tail"):
                if by[k] and len(out) < n:
                    out.append(by[k].pop())
        return out

    b_cands = [q for q in pool if cov[q] >= min_questions_b] if questions else list(pool)
    region_b = stratified(b_cands, n_b)
    rest = [q for q in pool if q not in set(region_b)]
    region_a = stratified(rest, n_a)
    core_b = sorted(region_b)
    if n_b_extra > 0:
        taken = set(region_a) | set(region_b)
        region_b = region_b + stratified([q for q in b_cands if q not in taken], n_b_extra)
    return {
        "concept": concept, "A": sorted(region_a), "B": sorted(region_b), "B_core": core_b,
        "b_candidates": len(b_cands),
        "stratum": {q: strata[q] for q in region_a + region_b},
        "page_words": {q: page_words.get(q, 0) for q in region_a + region_b},
        "question_coverage": {q: cov[q] for q in region_b},
        "pool_size": len(pool),
    }

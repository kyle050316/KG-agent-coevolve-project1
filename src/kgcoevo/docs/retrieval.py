"""BM25 retrieval over passages (Robertson & Zaragoza, 2009), fixed across all conditions."""

from __future__ import annotations

import re
from collections import defaultdict

from rank_bm25 import BM25Okapi

from kgcoevo.docs.passages import Passage

_TOK = re.compile(r"[a-z0-9]+")
STOP = frozenset("the a an of in on at to for and or is was were be by with as from that this it its his her their".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOK.findall(text.lower()) if t not in STOP]


class BM25Index:
    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self.by_id = {p.pid: p for p in passages}
        self.by_qid: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(passages):
            self.by_qid[p.qid].append(i)
        self.bm25 = BM25Okapi([tokenize(p.text) or ["_"] for p in passages]) if passages else None

    def search(self, query: str, k: int = 5, qids: list[str] | None = None) -> list[Passage]:
        """Top-k passages; if ``qids`` is given, only passages from those entities' pages."""
        if not self.bm25:
            return []
        q = tokenize(query)
        if qids is not None:
            ids = sorted({i for qid in qids for i in self.by_qid.get(qid, [])})
            if not ids:
                return []
            scores = self.bm25.get_batch_scores(q, ids)
            ranked = sorted(zip(ids, scores), key=lambda x: (-x[1], x[0]))
        else:
            scores = self.bm25.get_scores(q)
            ranked = sorted(enumerate(scores), key=lambda x: (-x[1], x[0]))
        return [self.passages[i] for i, _ in ranked[:k]]

    def page(self, qid: str, max_passages: int | None = None) -> list[Passage]:
        ids = self.by_qid.get(qid, [])
        return [self.passages[i] for i in (ids[:max_passages] if max_passages else ids)]

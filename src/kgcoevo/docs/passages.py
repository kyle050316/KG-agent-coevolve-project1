"""Split KILT pages into short passages that keep gold entity links (anchors -> KB QIDs)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass
class Passage:
    pid: str
    qid: str  # entity whose page this passage comes from
    title: str
    text: str
    anchors: list[list] = field(default_factory=list)  # [start, end, qid] relative to text

    def to_json(self) -> dict:
        return asdict(self)

    def linked_text(self) -> str:
        """Text with gold entity ids inlined after each linked mention (C2-link condition)."""
        out, last = [], 0
        for s, e, q in sorted(self.anchors):
            if s < last:
                continue
            out.append(self.text[last:e])
            out.append(f" [{q}]")
            last = e
        out.append(self.text[last:])
        return "".join(out)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _clean(par: str) -> tuple[str | None, int | None]:
    """Cleaned paragraph and the offset to map raw anchor offsets (None if offsets are unusable)."""
    if par.startswith("Section::::"):
        return None, None
    if "BULLET::::" in par:
        par = par.replace("BULLET::::- ", "").replace("BULLET::::", "").strip()
        return (par or None), None
    stripped = par.strip()
    return (stripped or None), len(par) - len(par.lstrip())


def build_passages(pages: dict[str, dict], qids: set[str], max_words: int = 100) -> list[Passage]:
    """Chunk the pages of ``qids`` into <= ``max_words`` passages at sentence boundaries."""
    wid2qid = {p["wikipedia_id"]: q for q, p in pages.items()}
    out: list[Passage] = []
    for qid in sorted(qids):
        page = pages.get(qid)
        if not page:
            continue
        anchors_by_par: dict[int, list] = {}
        for a in page["anchors"]:
            tq = wid2qid.get(a["wikipedia_id"])
            if tq:
                anchors_by_par.setdefault(a["paragraph_id"], []).append((a["start"], a["end"], tq))
        for pi, raw in enumerate(page["paragraphs"]):
            if pi == 0:
                continue  # KILT stores the title as paragraph 0
            par, offset = _clean(raw)
            if par is None:
                continue
            par_anchors = [] if offset is None else [
                (a - offset, b - offset, q) for a, b, q in anchors_by_par.get(pi, [])]
            chunk: list[tuple[int, int]] = []
            words = 0
            ci = 0

            def flush() -> None:
                nonlocal chunk, words, ci
                if not chunk:
                    return
                s, e = chunk[0][0], chunk[-1][1]
                anchors = [[a - s, b - s, q] for a, b, q in par_anchors if a >= s and b <= e]
                out.append(Passage(f"{qid}:{pi}:{ci}", qid, page["title"], par[s:e], anchors))
                ci += 1
                chunk, words = [], 0

            for s, e in sentence_spans(par):
                n = len(par[s:e].split())
                if chunk and words + n > max_words:
                    flush()
                chunk.append((s, e))
                words += n
            flush()
    return out


def save_passages(passages: list[Passage], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in passages:
            f.write(json.dumps(p.to_json(), ensure_ascii=False) + "\n")


def load_passages(path: str | Path) -> list[Passage]:
    with open(path, encoding="utf-8") as f:
        return [Passage(**json.loads(line)) for line in f if line.strip()]

"""Streaming access to the KILT Wikipedia knowledge source (2019-08-01 snapshot).

KILT (Petroni et al., NAACL 2021) distributes one JSON object per Wikipedia page with paragraphs,
hyperlink anchors (target Wikipedia id) and the page's Wikidata id. KQA Pro entities are Wikidata
QIDs, so pages can be joined to the KB directly, and anchors give gold entity links.

The full file is ~35 GB; :func:`extract_kb_pages` makes a single streaming pass and keeps only the
pages of KB entities, so nothing else needs to be stored.
"""

from __future__ import annotations

import gzip
import io
import json
import re
from pathlib import Path
from typing import Iterator

_QID = re.compile(rb'"wikidata_id"\s*:\s*"(Q\d+)"')

KILT_URL = "http://dl.fbaipublicfiles.com/KILT/kilt_knowledgesource.json"


def iter_raw_lines(source: str) -> Iterator[bytes]:
    """Yield raw JSON lines (bytes) from a local path (optionally .gz) or an http(s) URL."""
    if source.startswith(("http://", "https://")):
        import requests

        with requests.get(source, stream=True, timeout=120) as r:
            r.raise_for_status()
            for line in r.iter_lines(chunk_size=1 << 20):
                if line:
                    yield line
        return
    opener = gzip.open if source.endswith(".gz") else open
    with opener(source, "rb") as f:  # type: ignore[arg-type]
        for line in f:
            line = line.strip()
            if line:
                yield line


def iter_kilt(source: str) -> Iterator[dict]:
    """Yield parsed page records."""
    for line in iter_raw_lines(source):
        yield json.loads(line)


def extract_kb_pages(source: str, qids: set[str], out_path: str | Path, limit: int | None = None) -> dict:
    """Keep pages whose Wikidata id is in ``qids``; write a compact JSONL file. Returns stats."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_seen = n_kept = 0
    with out_path.open("w", encoding="utf-8") as out:
        for line in iter_raw_lines(source):
            n_seen += 1
            m = _QID.search(line)  # cheap pre-filter: only parse pages of KB entities
            qid = m.group(1).decode() if m else None
            if qid in qids:
                page = json.loads(line)
                rec = {
                    "qid": qid,
                    "wikipedia_id": str(page.get("wikipedia_id")),
                    "title": page.get("wikipedia_title", ""),
                    "paragraphs": [p.rstrip("\n") for p in page.get("text", [])],
                    "anchors": [
                        {"paragraph_id": a["paragraph_id"], "start": a["start"], "end": a["end"],
                         "text": a.get("text", ""), "wikipedia_id": str(a.get("wikipedia_id", ""))}
                        for a in page.get("anchors", []) if a.get("wikipedia_id")
                    ],
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_kept += 1
            if limit and n_seen >= limit:
                break
    return {"pages_seen": n_seen, "pages_kept": n_kept, "out": str(out_path)}


def load_pages(path: str | Path) -> dict[str, dict]:
    pages = {}
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            pages.setdefault(rec["qid"], rec)
    return pages


def page_words(page: dict) -> int:
    return sum(len(p.split()) for p in page["paragraphs"][1:])

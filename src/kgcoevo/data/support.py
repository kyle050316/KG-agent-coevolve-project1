"""Build S: the KB facts that the document collection D explicitly states.

Defects are only injected into S (so every injected defect is discoverable from text in
principle); a small number of defects outside S serve as "unverifiable" controls.

Alignment follows the distant-supervision recipe of T-REx (Elsahar et al., LREC 2018): a fact
is a candidate if a sentence of the subject's page mentions the value (normalised surface forms)
or links/mentions the object entity. Candidates are then accepted by a high-precision rule
(exact full dates, numbers, strings; years or co-mentions only together with a relation cue
word) or, optionally, by an LLM entailment check (``needs_verification`` records).
Kang et al. (2026) show that most correct KG facts have no supporting passage, so S is a biased
subset; its size and relation distribution are reported by ``summarize_support``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from kgcoevo.docs.passages import Passage, sentence_spans
from kgcoevo.kb.store import Fact, KBStore
from kgcoevo.kb.values import surface_forms, value_kind, value_str

CUES: dict[str, list[str]] = {
    "date of birth": ["born", "birth"],
    "date of death": ["died", "death"],
    "place of birth": ["born", "native of", "birthplace"],
    "place of death": ["died"],
    "spouse": ["married", "wife", "husband", "spouse", "wed"],
    "child": ["son", "daughter", "child", "children"],
    "father": ["father", "son of", "daughter of"],
    "mother": ["mother", "son of", "daughter of"],
    "sibling": ["brother", "sister", "sibling"],
    "educated at": ["graduated", "attended", "studied", "educated", "alumn", "degree", "school"],
    "award received": ["award", "prize", "won", "received", "honor", "honour", "medal"],
    "nominated for": ["nominat"],
    "member of political party": ["party", "member"],
    "employer": ["worked", "employed", "joined", "professor", "career"],
    "member of sports team": ["played", "signed", "joined", "team", "transfer"],
    "position held": ["served", "elected", "appointed", "position"],
    "occupation": ["is a", "was a", "career", "worked as"],
    "inception": ["founded", "established", "formed", "created", "incorporated", "opened"],
    "publication date": ["released", "published", "premiered", "aired"],
    "population": ["population", "inhabitants", "residents", "people"],
    "start time": ["married", "began", "started", "since", "from"],
    "point in time": ["in", "awarded", "won", "received"],
}
STRONG_KINDS = ("date", "quantity", "string")


def _contains(sentence: str, form: str) -> bool:
    if not form:
        return False
    if form[0].isalnum() and form[-1].isalnum():
        return re.search(rf"(?<![\w]){re.escape(form)}(?![\w])", sentence, flags=re.IGNORECASE) is not None
    return form.lower() in sentence.lower()


def _has_cue(sentence: str, key: str) -> bool:
    s = sentence.lower()
    return any(c in s for c in CUES.get(key, []))


def _sentences(passages: list[Passage]):
    for p in passages:
        for s, e in sentence_spans(p.text):
            yield p, s, e, p.text[s:e]


def _mentions(store: KBStore, p: Passage, s: int, e: int, sent: str, eid: str) -> bool:
    if any(q == eid and a >= s and b <= e for a, b, q in p.anchors):
        return True
    return len(store.name(eid)) >= 4 and _contains(sent, store.name(eid))


def align_fact(store: KBStore, f: Fact, passages: list[Passage]) -> dict:
    """Return the best alignment record for one fact."""
    best: dict = {"supported": False, "method": "none", "passage_ids": [], "sentence": "", "needs_verification": False}
    if f.kind == "qual":
        return best  # qualifiers are aligned with their parent in build_support
    for p, s, e, sent in _sentences(passages):
        if f.kind == "attr":
            kind = value_kind(f.value)
            if kind == "string" and len(value_str(f.value)) < 4:
                continue
            if not any(_contains(sent, form) for form in surface_forms(f.value)):
                continue
            if kind in STRONG_KINDS:
                if kind == "quantity" and abs(float(f.value["value"])) < 1000 and not _has_cue(sent, f.key):
                    continue  # small numbers are too ambiguous without a cue
                return {"supported": True, "method": f"exact_{kind}", "passage_ids": [p.pid], "sentence": sent,
                        "needs_verification": False}
            if _has_cue(sent, f.key):  # year values need a cue word
                return {"supported": True, "method": "year_cue", "passage_ids": [p.pid], "sentence": sent,
                        "needs_verification": False}
            if not best["needs_verification"]:
                best = {"supported": False, "method": "year_only", "passage_ids": [p.pid], "sentence": sent,
                        "needs_verification": True}
        else:  # relation: the other endpoint must be linked or named in the sentence
            other = f.value if p.qid == f.subject else f.subject
            if not _mentions(store, p, s, e, sent, other):
                continue
            if _has_cue(sent, f.key):
                return {"supported": True, "method": "comention_cue", "passage_ids": [p.pid], "sentence": sent,
                        "needs_verification": False}
            if not best["needs_verification"]:
                best = {"supported": False, "method": "comention_only", "passage_ids": [p.pid], "sentence": sent,
                        "needs_verification": True}
    return best


def build_support(store: KBStore, pages_index: dict[str, list[Passage]], entities: list[str]) -> list[dict]:
    """Alignment records for every attr/rel fact whose subject is in ``entities`` (+ qualifiers)."""
    records: list[dict] = []
    for eid in entities:
        own = pages_index.get(eid, [])
        for f in store.facts_of(eid, ("attr", "rel")):
            psg = own + (pages_index.get(f.value, []) if f.kind == "rel" else [])
            rec = align_fact(store, f, psg)
            records.append(_record(store, f, rec))
            for q in store.quals(f.fid):
                qrec = {"supported": False, "method": "none", "passage_ids": [], "sentence": "", "needs_verification": False}
                if rec["supported"] and any(_contains(rec["sentence"], form) for form in surface_forms(q.value)):
                    qrec = {"supported": True, "method": "qual_same_sentence", "passage_ids": rec["passage_ids"],
                            "sentence": rec["sentence"], "needs_verification": False}
                records.append(_record(store, q, qrec))
    return records


def _record(store: KBStore, f: Fact, rec: dict) -> dict:
    return {"fid": f.fid, "cid": store.cid(f.fid), "kind": f.kind, "subject": f.subject, "key": f.key,
            "value": f.vstr, "parent": f.parent, "text": store.fact_text(f), **rec}


def summarize_support(records: list[dict]) -> dict:
    by_kind = Counter((r["kind"], r["supported"]) for r in records)
    by_method = Counter(r["method"] for r in records if r["supported"])
    by_key = Counter(r["key"] for r in records if r["supported"])
    return {
        "facts": len(records), "supported": sum(r["supported"] for r in records),
        "needs_verification": sum(r["needs_verification"] for r in records),
        "by_kind": {f"{k}/{'S' if s else 'notS'}": v for (k, s), v in sorted(by_kind.items())},
        "by_method": dict(by_method.most_common()), "top_keys": dict(by_key.most_common(25)),
    }


def pages_index(passages: list[Passage]) -> dict[str, list[Passage]]:
    idx: dict[str, list[Passage]] = defaultdict(list)
    for p in passages:
        idx[p.qid].append(p)
    return idx

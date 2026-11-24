"""Condition-specific evidence for the Challenger (single-turn, pre-retrieved).

Conditions (Exp 1):
  C1      working KG only
  C2      working KG + BM25 passages (k per path fact / page passages for Mode B)
  C2link  as C2, with gold entity ids inlined after linked mentions (removes entity linking)
  C3      working KG + the reference KG G* (oracle upper bound)
B0 (no LLM) and C0 (closed-book probe) do not use this module.

Evidence is retrieved by a fixed procedure, identical across conditions, so differences between
conditions are caused by the information shown, not by retrieval behaviour of the model.
"""

from __future__ import annotations

from collections import Counter

from kgcoevo.docs.passages import Passage
from kgcoevo.docs.retrieval import BM25Index
from kgcoevo.kb.store import Fact, KBStore

CONDITION_NOTES = {
    "C1": "You only have the working KG. Flag a fact only if it is inconsistent with other KG facts shown.",
    "C2": "Passages are labelled with ids in square brackets; cite these ids as evidence_id.",
    "C2link": ("Passages are labelled with ids in square brackets; each linked entity mention is followed by "
               "its KG id, e.g. 'Barack Obama [Q76]'. Cite passage ids as evidence_id."),
    "C3": "Facts marked REF come from the authoritative reference KG; cite them as evidence_id \"REF\".",
}
CITE_NOTES = {
    "C1": "use \"KG\" when the gap follows from an inconsistency among the KG facts",
    "C2": "the passage id in square brackets",
    "C2link": "the passage id in square brackets",
    "C3": "use \"REF\" for reference-KG facts",
}
LLM_CONDITIONS = ("C1", "C2", "C2link", "C3")


def render_passages(ps: list[Passage], linked: bool) -> str:
    return "\n".join(f"[{p.pid}] {p.linked_text() if linked else p.text}" for p in ps)


def numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in enumerate(lines))


class EvidenceBuilder:
    def __init__(self, gs: KBStore, gw: KBStore, index: BM25Index | None, *, k_per_fact: int = 3,
                 max_page_passages: int = 12, max_kg_facts: int = 120, max_context_facts: int = 20,
                 vocab_entities: list[str] | None = None):
        self.gs, self.gw, self.index = gs, gw, index
        self.k = k_per_fact
        self.max_page = max_page_passages
        self.max_kg = max_kg_facts
        self.max_ctx = max_context_facts
        vocab: Counter = Counter()
        for e in vocab_entities or []:
            vocab.update({f.key for f in gw.facts_of(e, ("attr", "rel"))})
        self.common_keys = [k for k, _ in vocab.most_common(40)]

    # -- helpers --------------------------------------------------------------------------------
    def _gw_fact(self, cid: str) -> Fact | None:
        fid = self.gw.cid_to_fid.get(cid)
        return self.gw.facts[fid] if fid else None

    def _ref_lines(self, f: Fact) -> list[str]:
        """G* facts with the same subject and key as a working-KG fact (oracle condition)."""
        if f.kind == "qual":
            parent = self.gw.facts[f.parent]
            out = []
            for g in self.gs.facts_of(parent.subject, (parent.kind,)):
                if g.key == parent.key:
                    out += [self.gs.fact_text(q) for q in self.gs.quals(g.fid, f.key)]
            return out
        return [self.gs.fact_text(g) for g in self.gs.facts_of(f.subject, (f.kind,)) if g.key == f.key]

    # -- Mode A: one path -----------------------------------------------------------------------------
    def path(self, path: dict, cond: str) -> dict:
        facts = [f for f in (self._gw_fact(c) for c in path["fact_cids"]) if f is not None]
        parts: list[str] = []
        shown: list[str] = []
        keys = {f.key for f in facts}
        cids = set(path["fact_cids"])
        ctx = []
        for e in path["entities"]:
            for g in self.gw.facts_of(e, ("attr", "rel")):
                if g.key in keys and self.gw.cid(g.fid) not in cids:
                    ctx.append(self.gw.fact_text(g))
        if ctx:
            parts.append("Other working-KG facts about the same entities:\n" + "\n".join(ctx[: self.max_ctx]))
        if cond in ("C2", "C2link") and self.index is not None:
            ps: list[Passage] = []
            for f in facts:
                if f.kind == "qual":
                    f = self.gw.facts[f.parent]
                qids = [f.subject] + ([f.value] if f.kind == "rel" else [])
                for p in self.index.search(f"{self.gw.name(f.subject)} {f.key}", self.k, qids=qids):
                    if p.pid not in shown:
                        shown.append(p.pid)
                        ps.append(p)
            parts.append("Passages:\n" + (render_passages(ps, cond == "C2link") or "(no passages found)"))
        if cond == "C3":
            ref = []
            for f in facts:
                ref += [f"REF: {t}" for t in self._ref_lines(f)] or [f"REF: (no fact with key '{f.key}')"]
            parts.append("Reference KG facts:\n" + "\n".join(dict.fromkeys(ref)))
        if cond == "C1" and not ctx:
            parts.append("(only the working-KG path facts above are available)")
        return {"text": "\n\n".join(parts), "shown_pids": shown, "note": CONDITION_NOTES[cond],
                "path_facts": numbered(path["facts_text"])}

    # -- Mode B: one entity --------------------------------------------------------------------------
    def entity(self, eid: str, cond: str) -> dict:
        kg = [self.gw.fact_text(f) for f in self.gw.facts_of(eid, ("attr", "rel"))][: self.max_kg]
        shown: list[str] = []
        if cond in ("C2", "C2link") and self.index is not None:
            ps = self.index.page(eid, self.max_page)
            shown = [p.pid for p in ps]
            ev = "Passages from the entity's Wikipedia page:\n" + (render_passages(ps, cond == "C2link") or "(none)")
        elif cond == "C3":
            ev = "Reference KG facts:\n" + "\n".join(f"REF: {self.gs.fact_text(f)}" for f in self.gs.facts_of(eid, ("attr", "rel")))
        else:
            ev = "(none: only the working-KG facts above are available)"
        own = sorted({f.key for f in self.gw.facts_of(eid, ("attr", "rel"))})
        allowed = list(dict.fromkeys(own + self.common_keys))
        return {"text": ev, "shown_pids": shown, "kg_facts": numbered(kg) or "(no facts)",
                "allowed_keys": ", ".join(allowed), "cite_note": CITE_NOTES[cond], "note": CONDITION_NOTES[cond]}

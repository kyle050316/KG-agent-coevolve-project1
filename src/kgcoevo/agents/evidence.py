"""Condition-specific evidence for the Challenger (single-turn, pre-retrieved).

Conditions (Exp 1):
  C1      working KG only
  C1know  working KG only; the Challenger may also use its own background knowledge
  C2      working KG + documents. Mode A: for every path fact, the passage(s) of S that state the
          fact ("gold", from the support alignment) are always shown, mixed with BM25 distractor
          passages from the same pages (``k_per_fact`` passages per fact in total; facts outside S
          get ``k_per_fact`` BM25 passages). Mode B: all S passages of the entity plus
          ``mode_b_distractors`` other passages of its page.
  C3      working KG + the reference KG G* (oracle upper bound)
B0 (no LLM) and C0 (closed-book probe) do not use this module.

Every condition sees the same working-KG context: all facts of the entities on the path (Mode A)
or of the entity (Mode B). Gold passages are looked up in the same way for defective and clean
facts (a corrupted fact gets the passage of the fact it replaced), so which passages appear does
not reveal where the defects are. Passages are listed in page order, not gold first.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from kgcoevo.docs.passages import Passage
from kgcoevo.docs.retrieval import BM25Index
from kgcoevo.kb.store import Fact, KBStore

CONDITION_NOTES = {
    "C1": "You only have the working KG. Flag a fact only if it is inconsistent with other KG facts shown.",
    "C1know": ("You have the working KG and your own background knowledge about these entities. Flag a fact if it "
               "is inconsistent with other KG facts shown or with what you know; cite \"MEMORY\" as evidence_id "
               "when you rely on your own knowledge."),
    "C2": ("Passages are labelled with ids in square brackets; cite these ids as evidence_id. "
           "Not every passage is relevant."),
    "C3": "Facts marked REF come from the authoritative reference KG; cite them as evidence_id \"REF\".",
}
CITE_NOTES = {
    "C1": "use \"KG\" when the gap follows from an inconsistency among the KG facts",
    "C1know": "use \"MEMORY\" for facts from your own knowledge, \"KG\" for inconsistencies among the KG facts",
    "C2": "the passage id in square brackets",
    "C3": "use \"REF\" for reference-KG facts",
}
# Mode A instruction 4 / Mode B rules: only C1know may use background knowledge.
KNOWLEDGE_RULE_A = {"C1know": "Base the decision on the evidence shown and on your own background knowledge about these entities."}
KNOWLEDGE_RULE_B = {"C1know": "Do not report anything you are not confident about."}
SOURCE_PHRASE_B = {"C1know": "the evidence states explicitly or that you know with confidence"}
DEFAULT_RULE_A = "Base the decision only on the evidence shown, not on your background knowledge."
DEFAULT_RULE_B = "Do not report anything the evidence does not state; do not use background knowledge."
DEFAULT_SOURCE_B = "the evidence states explicitly"
LLM_CONDITIONS = ("C1", "C1know", "C2", "C3")


def _page_order(pid: str) -> tuple:
    parts = pid.split(":")
    try:
        return (parts[0], int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return (pid, 0, 0)


def render_passages(ps: list[Passage]) -> str:
    return "\n".join(f"[{p.pid}] {p.text}" for p in ps)


def numbered(lines: list[str]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in enumerate(lines))


class EvidenceBuilder:
    def __init__(self, gs: KBStore, gw: KBStore, index: BM25Index | None, *, support: list[dict] | None = None,
                 defects: list[dict] | None = None, k_per_fact: int = 3, mode_b_distractors: int = 4,
                 max_kg_facts: int = 120, max_context_facts: int = 30, vocab_entities: list[str] | None = None):
        self.gs, self.gw, self.index = gs, gw, index
        self.k = k_per_fact
        self.n_dis_b = mode_b_distractors
        self.max_kg = max_kg_facts
        self.max_ctx = max_context_facts
        # gold passages: Gw content id -> S passages; a corrupted fact inherits those of the fact it replaced
        self.gold_by_cid: dict[str, list[str]] = {}
        self.gold_by_subject: dict[str, list[str]] = defaultdict(list)
        for r in support or []:
            if r["supported"]:
                self.gold_by_cid[r["cid"]] = list(r["passage_ids"])
                for pid in r["passage_ids"]:
                    if pid not in self.gold_by_subject[r["subject"]]:
                        self.gold_by_subject[r["subject"]].append(pid)
        for d in defects or []:
            if d.get("cid_after") and d.get("passage_ids"):
                self.gold_by_cid[d["cid_after"]] = list(d["passage_ids"])
        vocab: Counter = Counter()
        for e in vocab_entities or []:
            vocab.update({f.key for f in gw.facts_of(e, ("attr", "rel"))})
        self.common_keys = [k for k, _ in vocab.most_common(40)]

    # -- helpers --------------------------------------------------------------------------------
    def _gw_fact(self, cid: str) -> Fact | None:
        fid = self.gw.cid_to_fid.get(cid)
        return self.gw.facts[fid] if fid else None

    def _gold(self, f: Fact) -> list[str]:
        pids = self.gold_by_cid.get(self.gw.cid(f.fid)) or []
        if not pids and f.kind == "qual":
            pids = self.gold_by_cid.get(self.gw.cid(f.parent)) or []
        by_id = self.index.by_id if self.index else {}
        return [p for p in pids if p in by_id]

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

    def _context(self, entities: list[str], exclude: set[str]) -> list[str]:
        """All working-KG facts of the path entities (attributes first), at most ``max_ctx`` per entity."""
        lines = []
        for e in entities:
            fs = [g for g in self.gw.facts_of(e, ("attr", "rel")) if self.gw.cid(g.fid) not in exclude]
            fs.sort(key=lambda g: g.kind != "attr")
            lines += [self.gw.fact_text(g) for g in fs[: self.max_ctx]]
        return list(dict.fromkeys(lines))

    # -- Mode A: one path -----------------------------------------------------------------------------
    def path(self, path: dict, cond: str) -> dict:
        facts = [f for f in (self._gw_fact(c) for c in path["fact_cids"]) if f is not None]
        parts: list[str] = []
        shown: list[str] = []
        gold_shown: list[str] = []
        ctx = self._context(path["entities"], set(path["fact_cids"]))
        if ctx:
            parts.append("Other working-KG facts about the entities on the path:\n" + "\n".join(ctx))
        if cond == "C2" and self.index is not None:
            for f in facts:
                base = self.gw.facts[f.parent] if f.kind == "qual" else f
                gold = [p for p in self._gold(f) if p not in shown]
                qids = [base.subject] + ([base.value] if base.kind == "rel" else [])
                n_dis = max(self.k - len(gold), 0)
                pool = self.index.search(f"{self.gw.name(base.subject)} {base.key}", n_dis + len(gold) + len(shown) + 3,
                                         qids=qids)
                dis = [p.pid for p in pool if p.pid not in gold and p.pid not in shown][:n_dis]
                gold_shown += gold
                shown += gold + dis
            ps = sorted((self.index.by_id[p] for p in dict.fromkeys(shown)), key=lambda p: _page_order(p.pid))
            parts.append("Passages:\n" + (render_passages(ps) or "(no passages found)"))
        if cond == "C3":
            ref = []
            for f in facts:
                ref += [f"REF: {t}" for t in self._ref_lines(f)] or [f"REF: (no fact with key '{f.key}')"]
            parts.append("Reference KG facts:\n" + "\n".join(dict.fromkeys(ref)))
        if cond in ("C1", "C1know") and not ctx:
            parts.append("(only the working-KG path facts above are available)")
        return {"text": "\n\n".join(parts), "shown_pids": list(dict.fromkeys(shown)), "gold_pids": gold_shown,
                "note": CONDITION_NOTES[cond], "knowledge_rule": KNOWLEDGE_RULE_A.get(cond, DEFAULT_RULE_A),
                "path_facts": numbered(path["facts_text"])}

    # -- Mode B: one entity --------------------------------------------------------------------------
    def entity(self, eid: str, cond: str) -> dict:
        kg = [self.gw.fact_text(f) for f in self.gw.facts_of(eid, ("attr", "rel"))][: self.max_kg]
        shown: list[str] = []
        gold: list[str] = []
        if cond == "C2" and self.index is not None:
            gold = [p for p in self.gold_by_subject.get(eid, []) if p in self.index.by_id]
            dis = [p.pid for p in self.index.page(eid) if p.pid not in gold][: self.n_dis_b]
            ps = sorted((self.index.by_id[p] for p in dict.fromkeys(gold + dis)), key=lambda p: _page_order(p.pid))
            shown = [p.pid for p in ps]
            ev = "Passages about the entity:\n" + (render_passages(ps) or "(none)")
        elif cond == "C3":
            ev = "Reference KG facts:\n" + "\n".join(f"REF: {self.gs.fact_text(f)}" for f in self.gs.facts_of(eid, ("attr", "rel")))
        else:
            ev = "(none: only the working-KG facts above are available)"
        own = sorted({f.key for f in self.gw.facts_of(eid, ("attr", "rel"))})
        allowed = list(dict.fromkeys(own + self.common_keys))
        return {"text": ev, "shown_pids": shown, "gold_pids": gold, "kg_facts": numbered(kg) or "(no facts)",
                "allowed_keys": ", ".join(allowed), "cite_note": CITE_NOTES[cond], "note": CONDITION_NOTES[cond],
                "knowledge_rule": KNOWLEDGE_RULE_B.get(cond, DEFAULT_RULE_B),
                "source_phrase": SOURCE_PHRASE_B.get(cond, DEFAULT_SOURCE_B)}

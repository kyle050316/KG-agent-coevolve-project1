"""Solver: KoPL semantic parsing with execution feedback, then an answer step.

This follows the official KQA Pro setting (question -> KoPL program -> official engine) with
in-context examples retrieved from the KQA Pro training set (dynamic few-shot, as in KB-BINDER /
Interactive-KBQA style prompting) and one round of error feedback. The trajectory (programs,
execution results, final answer and its source) is what the Curator sees in Exp 2.

Modes: ``kg`` (execute on a given KG, optionally with sandbox edits and passages in context) and
``closed`` (no tools; used to detect questions answerable from parametric memory).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from kgcoevo.docs.passages import Passage
from kgcoevo.docs.retrieval import tokenize
from kgcoevo.kb.executor import ExecResult, Executor
from kgcoevo.kb.paths import describe_program
from kgcoevo.kb.store import Edit, KBStore
from kgcoevo.llm.parsing import extract_json
from kgcoevo.llm.prompts import messages


class EntityLinker:
    """Exact (case-insensitive) n-gram match of KB entity names in the question."""

    def __init__(self, store: KBStore, max_ngram: int = 8):
        self.store = store
        self.max_ngram = max_ngram
        self.lower: dict[str, list[str]] = defaultdict(list)
        for name, ids in store.name_to_ids.items():
            self.lower[name.lower()].extend(ids)

    def __call__(self, question: str, k: int = 6) -> list[str]:
        toks = re.findall(r"[\w'.&-]+|[^\w\s]", question)
        found: list[tuple[int, int, list[str]]] = []
        for n in range(min(self.max_ngram, len(toks)), 0, -1):
            for i in range(len(toks) - n + 1):
                cand = " ".join(toks[i:i + n]).lower()
                ids = self.lower.get(cand) or self.lower.get(re.sub(r"('s|')$", "", cand.rstrip(".")))
                if ids and not any(s < i + n and i < e for s, e, _ in found):
                    if n == 1 and len(cand) < 4:
                        continue
                    found.append((i, i + n, ids))
        out: list[str] = []
        for _, _, ids in sorted(found):
            for e in ids:
                if e not in out:
                    out.append(e)
        return out[:k]


class FewShotPool:
    def __init__(self, examples: list[dict], max_program_len: int = 10):
        self.examples = [e for e in examples if e.get("program") and len(e["program"]) <= max_program_len]
        from rank_bm25 import BM25Okapi

        self.bm25 = BM25Okapi([tokenize(e["question"]) or ["_"] for e in self.examples]) if self.examples else None

    def top(self, question: str, k: int = 4, exclude: str | None = None) -> list[dict]:
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(tokenize(question))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        out = []
        for i in order:
            if self.examples[i]["question"] != exclude:
                out.append(self.examples[i])
            if len(out) == k:
                break
        return out

    @staticmethod
    def render(examples: list[dict]) -> str:
        lines = []
        for e in examples:
            prog = [{"function": s["function"], "inputs": s.get("inputs", [])} for s in e["program"]]
            lines.append(f"Question: {e['question']}\nProgram: {json.dumps({'program': prog}, ensure_ascii=False)}")
        return "\n\n".join(lines) or "(none)"


def schema_hints(executor: Executor, eids: list[str], edits: list[Edit] | None, max_keys: int = 40) -> str:
    """Live relation/attribute keys around the linked entities (respects sandbox edits)."""
    kb = executor.kb
    lines = []
    with executor.patched(edits):
        for e in eids:
            if e not in kb.entities:
                continue
            ent = kb.entities[e]
            attrs = sorted({a["key"] for i, a in enumerate(ent["attributes"])
                            if i in kb.attribute_inv_index.get(a["key"], {}).get(e, [])})
            rels = sorted({f"{r['relation']} ({r['direction']})" for i, r in enumerate(ent["relations"])
                           if i in kb.relation_inv_index.get((r["relation"], r["direction"]), {}).get(e, [])})
            lines.append(f"- {ent['name']}: attributes [{', '.join(attrs[:max_keys])}]; relations [{', '.join(rels[:max_keys])}]")
    return "\n".join(lines) or "(no entity found in the question)"


def _result_text(res: ExecResult, limit: int = 20) -> str:
    if not res.ok:
        return f"ERROR: {res.error}"
    if res.empty:
        return "[] (empty result)"
    more = f" ... (+{len(res.answers) - limit} more)" if len(res.answers) > limit else ""
    return json.dumps(res.answers[:limit], ensure_ascii=False) + more


class Solver:
    def __init__(self, llm, store: KBStore, fewshot: FewShotPool, *, max_attempts: int = 2, n_examples: int = 4):
        self.llm = llm
        self.store = store  # names/concepts for entity hints (names are never edited)
        self.linker = EntityLinker(store)
        self.fewshot = fewshot
        self.max_attempts = max_attempts
        self.n_examples = n_examples

    async def closed_book(self, question: str, seed: int | None = None) -> dict:
        raw = await self.llm.chat(messages("closed_book_qa", question=question), seed=seed)
        js = extract_json(raw) or {}
        return {"mode": "closed", "answer": str(js.get("answer", "") or ""), "source": "memory", "raw": raw}

    async def solve(self, question: str, executor: Executor, edits: list[Edit] | None = None,
                    passages: list[Passage] | None = None, seed: int | None = None) -> dict:
        eids = self.linker(question)
        ents = "\n".join(f"- {self.store.describe(e)}" for e in eids) or "(none found)"
        schema = schema_hints(executor, eids, edits)
        examples = FewShotPool.render(self.fewshot.top(question, self.n_examples, exclude=question))
        attempts: list[dict] = []
        feedback = ""
        program: list[dict] | None = None
        res = ExecResult(False, [], "no program")
        for _ in range(self.max_attempts):
            raw = await self.llm.chat(messages("solver_parse", entities=ents, schema=schema, examples=examples,
                                               feedback=feedback, question=question), seed=seed)
            js = extract_json(raw) or {}
            program = js.get("program") if isinstance(js.get("program"), list) else None
            res = executor.run(program, edits) if program else ExecResult(False, [], "could not parse a program")
            attempts.append({"program": program, "exec": res.to_json()})
            if res.ok and not res.empty:
                break
            feedback = (f"\n## Previous attempt\nProgram: {json.dumps(program, ensure_ascii=False)}\n"
                        f"Result: {_result_text(res)}\nFix the program.\n")
        out = await self.answer(question, program, res, passages, seed)
        return {"mode": "kg", "entities": eids, "attempts": attempts, "program": program, "exec": res.to_json(), **out}

    async def answer(self, question: str, program: list[dict] | None, res: ExecResult,
                     passages: list[Passage] | None = None, seed: int | None = None) -> dict:
        prog_txt = describe_program(self.store, program) if program else "(no valid program)"
        psg = ""
        if passages:
            psg = "\nPassages:\n" + "\n".join(f"[{p.pid}] {p.text}" for p in passages) + "\n"
        raw = await self.llm.chat(messages("solver_answer", question=question, program=prog_txt,
                                           result=_result_text(res), passages=psg), seed=seed)
        js = extract_json(raw) or {}
        return {"answer": str(js.get("answer", "") or ""), "source": str(js.get("source", "") or ""), "raw_answer": raw}

    async def rerun(self, question: str, program: list[dict] | None, executor: Executor, edits: list[Edit],
                    passages: list[Passage] | None = None, seed: int | None = None) -> dict:
        """Sandbox re-run: same program on the edited KG, then the answer step (Curator test)."""
        res = executor.run(program, edits) if program else ExecResult(False, [], "no program")
        out = await self.answer(question, program, res, passages, seed)
        return {"exec": res.to_json(), **out}

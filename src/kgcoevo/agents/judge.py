"""LLM judge calls (use a different model family than the 9B under test when possible)."""

from __future__ import annotations

from kgcoevo.llm.parsing import extract_json
from kgcoevo.llm.prompts import messages


async def judge_faithfulness(llm, description: str, question: str, answer: str) -> dict:
    raw = await llm.chat(messages("judge_faithfulness", description=description, question=question, answer=answer),
                         temperature=0.0)
    js = extract_json(raw) or {}
    faithful = js.get("faithful")
    return {"faithful": bool(faithful) if isinstance(faithful, bool) else None,
            "violations": js.get("violations", []), "note": js.get("note", ""), "raw": raw}


async def verify_entailment(llm, passage: str, claim: str) -> dict:
    raw = await llm.chat(messages("verify_entailment", passage=passage, claim=claim), temperature=0.0)
    js = extract_json(raw) or {}
    return {"entails": js.get("entails") is True, "quote": js.get("quote", ""), "raw": raw}

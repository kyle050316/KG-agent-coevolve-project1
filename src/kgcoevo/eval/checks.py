"""Layered validity checks for generated tasks (E0-E5).

E0 format      the task parses and the program is well formed
E1 executable  the program runs and returns a non-empty answer (on Gw, or on G* for tasks built
               from facts missing in Gw)
E2 bookkeeping the answer key equals the program's output on Gw (only for accepted Mode A tasks)
E3 faithful    rule part here (answer/bridge leakage, anchors named, length); the LLM-judge part
               and the human audit are merged in the analysis
E4 unique      the program has exactly one answer on G*
E5 contaminated  passes E0-E4 (+E3) but the answer key differs from the answer on G*

Only E5 measures "wrong answer keys caused by KG defects"; everything else is reported
separately so that model errors are not mistaken for KG errors.
"""

from __future__ import annotations

from kgcoevo.eval.compare import answers_equal, canon, mentions, match_any
from kgcoevo.kb.executor import Executor, validate_program
from kgcoevo.kb.values import surface_forms


def _answer_forms(answer: str) -> list[str]:
    c = canon(answer)
    if c.startswith("date:"):
        return surface_forms({"type": "date", "value": c[5:]})
    return [answer]


def rule_checks(question: str, answer: str, mention_names: list[str], hidden_names: list[str]) -> dict:
    words = len(question.split())
    leak = (answer.strip().lower() not in {"yes", "no"} and len(answer.strip()) >= 3
            and any(mentions(question, f) for f in _answer_forms(answer)))
    out = {
        "answer_leak": leak,
        "bridge_leak": any(mentions(question, n) for n in hidden_names),
        "anchor_missing": not all(mentions(question, n) for n in mention_names),
        "length_ok": 4 <= words <= 60,
    }
    out["e3_rules"] = not out["answer_leak"] and not out["bridge_leak"] and not out["anchor_missing"] and out["length_ok"]
    return out


def check_task(task: dict, gw: Executor, gs: Executor) -> dict:
    """``task`` needs: question, program, answer, kg_e1 ('gw'|'gstar'), e2_applicable,
    mention_names, hidden_names."""
    out: dict = {"task_id": task["task_id"]}
    q, prog, key = task.get("question"), task.get("program"), task.get("answer")
    out["e0"] = bool(isinstance(q, str) and q.strip() and key not in (None, "") and validate_program(prog) is None)
    if not out["e0"]:
        return {**out, "stage": "E0", "valid": False, "contaminated": False}
    key = str(key)
    r1 = (gw if task.get("kg_e1", "gw") == "gw" else gs).run(prog)
    out["e1"] = r1.ok and not r1.empty
    rgw = r1 if task.get("kg_e1", "gw") == "gw" else gw.run(prog)
    rgs = gs.run(prog)
    out.update({"gw_answers": rgw.answers, "gw_error": rgw.error, "gs_answers": rgs.answers, "gs_error": rgs.error})
    out["answer_affecting"] = not (rgw.unique and rgs.unique and answers_equal(rgw.answer, rgs.answer))
    if task.get("e2_applicable", True):
        out["e2"] = bool(r1.ok and match_any(key, r1.answers))
    else:
        out["e2"] = None
    out.update(rule_checks(q, key, task.get("mention_names", []), task.get("hidden_names", [])))
    out["e4"] = rgs.unique
    stage = ("E1" if not out["e1"] else "E2" if out["e2"] is False else "E3" if not out["e3_rules"]
             else "E4" if not out["e4"] else "")
    out["stage"] = stage
    out["valid"] = stage == ""
    out["contaminated"] = bool(out["valid"] and not answers_equal(key, rgs.answer))
    return out

"""Curator: failure attribution and KG repair (Exp 2), prompt-based with a counterfactual tool.

Flow per flagged case:
1. ``diagnose`` (prompt): missing_fact | wrong_fact | non_kg | bad_key, the located fact, and a
   single-fact edit. The model sees both the KG's answer to the task program and the answer key, and is
   told that the key can be wrong (tasks come from a Challenger whose keys are not always right);
2. tool (optional, ablation ``no_tool`` skips it): the edit is applied to a sandbox copy of the KG,
   the Solver's program is re-executed and the Solver re-answers; the result goes back to the model
   without saying whether it matches the answer key (agreement with the key is not evidence);
3. ``decide`` (prompt): commit, revise or withdraw. The re-run is information, not a gate, because a
   correct edit does not fix a wrong Solver program;
4. source gate (two-sided): an edit is admitted only if it cites an evidence item that was shown, an
   independent verifier confirms that the item states the new fact, and no shown item states the value
   that the edit replaces (then the documents support the current KG).
"""

from __future__ import annotations

import json
import re

from kgcoevo.kb.executor import Executor
from kgcoevo.kb.store import Edit
from kgcoevo.llm.parsing import extract_json
from kgcoevo.llm.prompts import messages, render

DIAGNOSES = ("missing_fact", "wrong_fact", "non_kg", "bad_key")  # the first two come with an edit
EDIT_DIAGNOSES = DIAGNOSES[:2]


def vc_to_raw(vc) -> dict:
    """KoPL ValueClass -> KB value dict."""
    if vc.type == "string":
        return {"type": "string", "value": vc.value}
    if vc.type == "quantity":
        v = vc.value
        return {"type": "quantity", "value": int(v) if float(v).is_integer() else v, "unit": vc.unit}
    if vc.type == "year":
        return {"type": "year", "value": int(vc.value)}
    return {"type": "date", "value": vc.value.isoformat()}


def live_entries(executor: Executor, edits: list[Edit] | None, eid: str, key: str) -> list[dict]:
    """Current (patched) facts of ``eid`` with ``key``: attrs and forward relations."""
    kb = executor.kb
    out = []
    with executor.patched(edits):
        ent = kb.entities.get(eid)
        if not ent:
            return []
        for i in kb.attribute_inv_index.get(key, {}).get(eid, []):
            a = ent["attributes"][i]
            out.append({"kind": "attr", "value": vc_to_raw(a["value"]), "vstr": str(a["value"]),
                        "qualifiers": {k: [vc_to_raw(v) for v in vs] for k, vs in a["qualifiers"].items()}})
        for i in kb.relation_inv_index.get((key, "forward"), {}).get(eid, []):
            r = ent["relations"][i]
            out.append({"kind": "rel", "value": r["object"], "vstr": r["object"],
                        "qualifiers": {k: [vc_to_raw(v) for v in vs] for k, vs in r["qualifiers"].items()}})
    return out


def resolve_name(name_to_ids: dict[str, list[str]], name: str, prefer: list[str] | None = None) -> str | None:
    """Entity id for a name (KB names are never edited, so the G* name index is used)."""
    ids = list(name_to_ids.get(name.strip(), []))
    if not ids:
        low = name.strip().lower()
        ids = [i for n, es in name_to_ids.items() if n.lower() == low for i in es]
    for p in prefer or []:
        if p in ids:
            return p
    return ids[0] if ids else None


def parse_value(executor: Executor, key: str, text: str) -> dict:
    """Value dict for ``text`` using the KB's type of ``key`` (falls back to heuristics)."""
    t = executor.kb.key_type.get(key)
    s = str(text).strip()
    if t in ("date", None) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return {"type": "date", "value": s}
    if t in ("date", None) and re.fullmatch(r"-?\d{1,4}", s):
        return {"type": "year", "value": int(s)}
    if t in ("quantity", None):
        m = re.fullmatch(r"([-+]?[\d,]*\.?\d+)\s*(.*)", s)
        if m:
            num = float(m.group(1).replace(",", ""))
            return {"type": "quantity", "value": int(num) if num.is_integer() else num, "unit": m.group(2).strip() or "1"}
    return {"type": "string", "value": s}


def build_edit(executor: Executor, name_to_ids: dict, edits: list[Edit] | None, js_edit: dict,
               prefer: list[str]) -> tuple[Edit | None, str]:
    """Turn the Curator's JSON edit into an Edit applicable on the current KG."""
    if not isinstance(js_edit, dict):
        return None, "no edit"
    op = str(js_edit.get("op", "")).lower()
    key = str(js_edit.get("key", "")).strip()
    subj = resolve_name(name_to_ids, str(js_edit.get("subject", "")), prefer)
    if op not in ("add", "update", "delete") or not key or subj is None:
        return None, "unresolvable edit (op/key/subject)"
    is_rel = (key, "forward") in executor.kb.relation_inv_index or (key, "backward") in executor.kb.relation_inv_index
    current = live_entries(executor, edits, subj, key)
    new_txt = str(js_edit.get("new_value", "") or "")
    old_txt = str(js_edit.get("old_value", "") or "")
    if op == "add":
        if is_rel:
            obj = resolve_name(name_to_ids, new_txt, prefer)
            return (Edit.add_rel(subj, key, obj), "") if obj else (None, "unresolvable new object")
        return Edit.add_attr(subj, key, parse_value(executor, key, new_txt)), ""
    # update/delete need the current entry
    target = None
    if old_txt:
        old_id = resolve_name(name_to_ids, old_txt, prefer) if is_rel else None
        for c in current:
            if (is_rel and c["value"] == old_id) or (not is_rel and _same(c["vstr"], old_txt)):
                target = c
                break
    elif len(current) == 1:
        target = current[0]
    if target is None:
        return None, "old fact not found in the current KG"
    kind = target["kind"]
    if op == "delete":
        return Edit("delete", kind, subj, key, target["value"], None, target["qualifiers"]), ""
    if kind == "rel":
        obj = resolve_name(name_to_ids, new_txt, prefer)
        return (Edit("update", "rel", subj, key, target["value"], obj, target["qualifiers"]), "") if obj else (None, "unresolvable new object")
    return Edit("update", "attr", subj, key, target["value"], parse_value(executor, key, new_txt), target["qualifiers"]), ""


def _same(a: str, b: str) -> bool:
    from kgcoevo.eval.compare import answers_equal
    return answers_equal(a, b)


def resolve_citation(cited: str, shown) -> str:
    """Evidence id as shown: exact, without brackets, or the one shown passage of a cited entity id
    (the model sometimes cites "Q123" for "Q123:4:0")."""
    c = str(cited or "").strip().strip("[]").strip()
    if c in shown:
        return c
    hits = [pid for pid in shown if pid.startswith(c + ":")] if c else []
    return hits[0] if len(hits) == 1 else c


def render_trajectory(traj: dict | None, store) -> str:
    if not traj:
        return "(not available)"
    lines = []
    for i, a in enumerate(traj.get("attempts", []), 1):
        lines.append(f"Attempt {i} program: {json.dumps(a.get('program'), ensure_ascii=False)}")
        ex = a.get("exec", {})
        lines.append(f"Attempt {i} result: {ex.get('answers') if ex.get('ok') else 'ERROR ' + str(ex.get('error'))}")
    lines.append(f"Final answer: {traj.get('answer')} (source: {traj.get('source')})")
    return "\n".join(lines)


async def diagnose(llm, *, question: str, answer_key: str, kg_answer: str, trigger: str, trajectory: str,
                   kg_facts: str, evidence: str, seed: int | None = None) -> dict:
    msgs = messages("curator", question=question, answer_key=answer_key, kg_answer=kg_answer, trigger=trigger,
                    trajectory=trajectory, kg_facts=kg_facts, evidence=evidence)
    raw = await llm.chat(msgs, seed=seed)
    js = extract_json(raw) or {}
    d = str(js.get("diagnosis", "")).strip().lower()
    return {"diagnosis": d if d in DIAGNOSES else "invalid", "located_fact": js.get("located_fact"),
            "evidence_id": str(js.get("evidence_id", "") or ""),
            "edit": js.get("edit") if isinstance(js.get("edit"), dict) else None, "confidence": js.get("confidence"),
            "rationale": js.get("rationale", ""), "parse_ok": bool(js), "raw": raw, "_messages": msgs}


async def decide(llm, first: dict, tool_result: str, seed: int | None = None) -> dict:
    """Second turn: the model sees the sandbox result of its own edit and commits, revises or withdraws."""
    msgs = first["_messages"] + [{"role": "assistant", "content": first["raw"]},
                                 {"role": "user", "content": render("curator_decide", tool_result=tool_result)}]
    raw = await llm.chat(msgs, seed=seed)
    js = extract_json(raw) or {}
    dec = str(js.get("decision", "")).strip().lower()
    d = str(js.get("diagnosis", "")).strip().lower()
    return {"decision": dec if dec in ("commit", "revise", "withdraw") else "invalid",
            "diagnosis": d if d in DIAGNOSES else first["diagnosis"],
            "edit": js.get("edit") if isinstance(js.get("edit"), dict) else None,
            "rationale": js.get("rationale", ""), "parse_ok": bool(js), "raw": raw}


def live_neighbors(executor: Executor, edits: list[Edit] | None, eids: list[str]) -> set[str]:
    """``eids`` and their neighbours on the current (patched) KG, so retrieval never follows a deleted link."""
    kb = executor.kb
    out = set(eids)
    with executor.patched(edits):
        for e in eids:
            ent = kb.entities.get(e)
            if not ent:
                continue
            for i, r in enumerate(ent["relations"]):
                if r["object"] in kb.entities and i in kb.relation_inv_index.get((r["relation"], r["direction"]), {}).get(e, []):
                    out.add(r["object"])
    return out


def live_facts_text(executor: Executor, edits: list[Edit] | None, eids: list[str], names: dict[str, str],
                    per_entity: int = 40, focus_keys: set[str] | None = None) -> str:
    """Current facts (attrs + outgoing relations, with qualifiers) of ``eids`` on the patched KG.

    Facts whose key appears in ``focus_keys`` (keys used by the Solver's program) are listed first, so
    the per-entity cap never hides them.
    """
    kb = executor.kb
    focus = focus_keys or set()
    lines = []
    with executor.patched(edits):
        for e in eids:
            ent = kb.entities.get(e)
            if not ent:
                continue
            rows = []
            for i, a in enumerate(ent["attributes"]):
                if i in kb.attribute_inv_index.get(a["key"], {}).get(e, []):
                    q = "; ".join(f"{k}: {', '.join(str(v) for v in vs)}" for k, vs in a["qualifiers"].items())
                    rows.append((a["key"], f"{ent['name']} | {a['key']}: {a['value']}" + (f" ({q})" if q else "")))
            for i, r in enumerate(ent["relations"]):
                if r["direction"] == "forward" and i in kb.relation_inv_index.get((r["relation"], "forward"), {}).get(e, []):
                    q = "; ".join(f"{k}: {', '.join(str(v) for v in vs)}" for k, vs in r["qualifiers"].items())
                    rows.append((r["relation"], f"{ent['name']} --{r['relation']}--> {names.get(r['object'], r['object'])}"
                                 + (f" ({q})" if q else "")))
            rows.sort(key=lambda x: x[0] not in focus)  # stable: original order within each group
            lines += [t for _, t in rows[:per_entity]]
    return "\n".join(lines) or "(no facts)"

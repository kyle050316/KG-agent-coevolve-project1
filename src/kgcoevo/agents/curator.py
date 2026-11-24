"""Curator: failure attribution and KG repair (Exp 2).

Flow per case (Fig. "Solver failure -> compare path facts with documents -> ..."):
1. diagnose: missing_fact | wrong_fact | non_kg | invalid_task | refer, with the located fact;
2. for KG diagnoses, turn the proposed edit into an :class:`Edit` on the current KG;
3. commit only if (a) the edit cites an evidence item that was shown, (b) an independent verifier
   says that item entails the edited fact, and (c) the Solver succeeds in the sandbox re-run.
   "Re-run succeeds but unsupported" edits are counted as reward-hacking candidates.
"""

from __future__ import annotations

import json
import re

from kgcoevo.kb.executor import Executor
from kgcoevo.kb.store import Edit
from kgcoevo.llm.parsing import extract_json
from kgcoevo.llm.prompts import messages

DIAGNOSES = ("missing_fact", "wrong_fact", "non_kg", "invalid_task", "refer")


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


async def diagnose(llm, *, question: str, answer_key: str, trajectory: str, kg_facts: str, evidence: str,
                   seed: int | None = None) -> dict:
    raw = await llm.chat(messages("curator", question=question, answer_key=answer_key, trajectory=trajectory,
                                  kg_facts=kg_facts, evidence=evidence), seed=seed)
    js = extract_json(raw) or {}
    d = str(js.get("diagnosis", "")).strip().lower()
    return {"diagnosis": d if d in DIAGNOSES else "invalid", "located_fact": js.get("located_fact"),
            "edit": js.get("edit"), "confidence": js.get("confidence"), "rationale": js.get("rationale", ""),
            "parse_ok": bool(js), "raw": raw}


def live_facts_text(executor: Executor, edits: list[Edit] | None, eids: list[str], names: dict[str, str],
                    per_entity: int = 25) -> str:
    """Current facts (attrs + outgoing relations, with qualifiers) of ``eids`` on the patched KG."""
    kb = executor.kb
    lines = []
    with executor.patched(edits):
        for e in eids:
            ent = kb.entities.get(e)
            if not ent:
                continue
            n = 0
            for i, a in enumerate(ent["attributes"]):
                if n < per_entity and i in kb.attribute_inv_index.get(a["key"], {}).get(e, []):
                    q = "; ".join(f"{k}: {', '.join(str(v) for v in vs)}" for k, vs in a["qualifiers"].items())
                    lines.append(f"{ent['name']} | {a['key']}: {a['value']}" + (f" ({q})" if q else ""))
                    n += 1
            for i, r in enumerate(ent["relations"]):
                if (n < per_entity and r["direction"] == "forward"
                        and i in kb.relation_inv_index.get((r["relation"], "forward"), {}).get(e, [])):
                    q = "; ".join(f"{k}: {', '.join(str(v) for v in vs)}" for k, vs in r["qualifiers"].items())
                    lines.append(f"{ent['name']} --{r['relation']}--> {names.get(r['object'], r['object'])}"
                                 + (f" ({q})" if q else ""))
                    n += 1
    return "\n".join(lines) or "(no facts)"

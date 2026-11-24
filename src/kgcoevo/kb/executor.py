"""Program execution with the official KoPL engine, plus reversible in-place edits ("sandbox").

The official engine (``pip install KoPL``; THU-KEG) is the reference executor for every answer
key, check and score in this repository. Building an engine for the full KQA Pro KB takes a while,
so edits that must be tested many times (Curator sandbox, Exp 2 per-case defects, locality
checks) are applied *in place* on the engine's indexes and undone afterwards. Tests verify that a
patched engine answers exactly like an engine rebuilt from the edited KB dict.

Never ``await`` inside :meth:`Executor.patched`: the engine is shared by all coroutines.
"""

from __future__ import annotations

import contextlib
import copy
import io
import threading
from dataclasses import asdict, dataclass
from typing import Callable, Iterator

from kgcoevo.kb.store import Edit, EditError, KBStore, qual_json
from kgcoevo.kb.values import value_str

KOPL_FUNCTIONS = frozenset({
    "FindAll", "Find", "FilterConcept", "FilterStr", "FilterNum", "FilterYear", "FilterDate",
    "QFilterStr", "QFilterNum", "QFilterYear", "QFilterDate", "Relate", "And", "Or", "QueryName",
    "Count", "SelectBetween", "SelectAmong", "QueryAttr", "QueryAttrUnderCondition", "VerifyStr",
    "VerifyNum", "VerifyYear", "VerifyDate", "QueryRelation", "QueryAttrQualifier",
    "QueryRelationQualifier", "What",
})


@contextlib.contextmanager
def quiet() -> Iterator[None]:
    """Silence the engine's prints and tqdm bars."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


@dataclass
class ExecResult:
    ok: bool
    answers: list[str]
    error: str | None = None

    @property
    def unique(self) -> bool:
        return self.ok and len(self.answers) == 1

    @property
    def empty(self) -> bool:
        return self.ok and len(self.answers) == 0

    @property
    def answer(self) -> str | None:
        return self.answers[0] if self.unique else None

    def to_json(self) -> dict:
        return asdict(self)


def validate_program(program: object) -> str | None:
    """Return an error message if ``program`` is not a well-formed KoPL program, else None."""
    if not isinstance(program, list) or not program:
        return "program must be a non-empty list of steps"
    for i, step in enumerate(program):
        if not isinstance(step, dict) or "function" not in step:
            return f"step {i} must be an object with a 'function' field"
        if step["function"] not in KOPL_FUNCTIONS:
            return f"step {i}: unknown function {step['function']!r}"
        inputs = step.get("inputs", [])
        if not isinstance(inputs, list) or not all(isinstance(x, (str, int, float)) for x in inputs):
            return f"step {i}: 'inputs' must be a list of strings"
    return None


class Executor:
    """Thin wrapper around ``kopl.kopl.KoPLEngine`` with sandboxed edits."""

    def __init__(self, kb_normalized: dict, has_mirrors: bool):
        from kopl.kopl import KoPLEngine  # imported lazily: heavy

        with quiet():
            self.engine = KoPLEngine(copy.deepcopy(kb_normalized))
        self.kb = self.engine.kb
        self.has_mirrors = has_mirrors
        self._lock = threading.RLock()

    @classmethod
    def from_store(cls, store: KBStore) -> "Executor":
        return cls(store.kb, store.has_mirrors)

    # -- execution ------------------------------------------------------------------------------
    def run(self, program: list[dict], edits: list[Edit] | None = None) -> ExecResult:
        err = validate_program(program)
        if err:
            return ExecResult(False, [], err)
        funcs = [s["function"] for s in program]
        inputs = [[str(x) for x in s.get("inputs", [])] for s in program]
        with self._lock:
            ctx = self.patched(edits) if edits else contextlib.nullcontext()
            try:
                with ctx, quiet():
                    out = self.engine.forward(funcs, inputs, ignore_error=False)
            except EditError:
                raise
            except Exception as e:  # engine errors are part of the measurement (E1)
                return ExecResult(False, [], f"{type(e).__name__}: {e}")
        if out is None:
            return ExecResult(False, [], "engine returned None")
        answers = sorted(set(out)) if isinstance(out, list) else [str(out)]
        return ExecResult(True, answers)

    # -- sandbox edits ------------------------------------------------------------------------------
    @contextlib.contextmanager
    def patched(self, edits: list[Edit] | None) -> Iterator[None]:
        """Apply ``edits`` in place and undo them on exit (LIFO)."""
        undo: list[Callable[[], None]] = []
        with self._lock:
            try:
                for e in edits or []:
                    undo.extend(self._apply(e))
                yield
            finally:
                for fn in reversed(undo):
                    fn()

    # internal helpers -------------------------------------------------------------------------
    def _parse(self, v: dict):
        return self.kb._parse_value(copy.deepcopy(v))

    def _attr_idx(self, eid: str, key: str, vstr: str, qj: str | None) -> int:
        for idx in list(self.kb.attribute_inv_index.get(key, {}).get(eid, [])):
            a = self.kb.entities[eid]["attributes"][idx]
            if str(a["value"]) == vstr and (qj is None or _eng_qual_json(a["qualifiers"]) == qj):
                return idx
        return -1

    def _rel_idx(self, eid: str, rel: str, direction: str, obj: str, qj: str | None) -> int:
        for idx in list(self.kb.relation_inv_index.get((rel, direction), {}).get(eid, [])):
            r = self.kb.entities[eid]["relations"][idx]
            if r["object"] == obj and (qj is None or _eng_qual_json(r["qualifiers"]) == qj):
                return idx
        return -1

    def _unindex(self, lst: list[int], idx: int) -> Callable[[], None]:
        lst.remove(idx)

        def undo() -> None:
            lst.append(idx)
            lst.sort()
        return undo

    def _del_rel(self, s: str, rel: str, o: str, qj: str) -> list[Callable[[], None]]:
        undo = []
        i = self._rel_idx(s, rel, "forward", o, qj)
        if i >= 0:
            undo.append(self._unindex(self.kb.relation_inv_index[(rel, "forward")][s], i))
            undo.append(self._unindex(self.kb.forward_relation_index[(s, o)], i))
        if o in self.kb.entities:
            j = self._rel_idx(o, rel, "backward", s, qj)
            if j >= 0:
                undo.append(self._unindex(self.kb.relation_inv_index[(rel, "backward")][o], j))
        if not undo:
            raise EditError(f"rel not found in engine: {s} {rel} {o}")
        return undo

    def _add_rel(self, s: str, rel: str, o: str, quals: dict) -> list[Callable[[], None]]:
        if o not in self.kb.entities:
            raise EditError(f"unknown object {o}")
        undo = []
        parsed = {k: [self._parse(v) for v in vs] for k, vs in quals.items()}
        sides = [(s, "forward", o)] + ([(o, "backward", s)] if self.has_mirrors else [])
        for eid, direction, other in sides:
            rels = self.kb.entities[eid]["relations"]
            rels.append({"relation": rel, "direction": direction, "object": other, "qualifiers": parsed})
            idx = len(rels) - 1
            inv = self.kb.relation_inv_index[(rel, direction)][eid]
            inv.append(idx)
            fwd = self.kb.forward_relation_index[(eid, other)] if direction == "forward" else None
            if fwd is not None:
                fwd.append(idx)

            def undo_one(rels=rels, inv=inv, fwd=fwd, idx=idx) -> None:
                inv.remove(idx)
                if fwd is not None:
                    fwd.remove(idx)
                rels.pop(idx)
            undo.append(undo_one)
        return undo

    def _apply(self, e: Edit) -> list[Callable[[], None]]:
        kb = self.kb
        if e.subject not in kb.entities:
            raise EditError(f"unknown subject {e.subject}")
        if e.kind == "attr":
            if e.op == "add":
                attrs = kb.entities[e.subject]["attributes"]
                attrs.append({"key": e.key, "value": self._parse(e.new_value),
                              "qualifiers": {k: [self._parse(v) for v in vs] for k, vs in e.qualifiers.items()}})
                idx = len(attrs) - 1
                lst = kb.attribute_inv_index[e.key][e.subject]
                lst.append(idx)
                added_type = e.key not in kb.key_type
                if added_type:
                    kb.key_type[e.key] = "date" if e.new_value["type"] == "year" else e.new_value["type"]

                def undo_add() -> None:
                    lst.remove(idx)
                    attrs.pop(idx)
                    if added_type:
                        kb.key_type.pop(e.key, None)
                return [undo_add]
            idx = self._attr_idx(e.subject, e.key, value_str(e.value), qual_json(e.qualifiers))
            if idx < 0:
                raise EditError(f"attr not found in engine: {e.subject} {e.key} {value_str(e.value)}")
            if e.op == "delete":
                return [self._unindex(kb.attribute_inv_index[e.key][e.subject], idx)]
            entry = kb.entities[e.subject]["attributes"][idx]
            old = entry["value"]
            entry["value"] = self._parse(e.new_value)

            def undo_upd() -> None:
                entry["value"] = old
            return [undo_upd]

        if e.kind == "rel":
            undo: list[Callable[[], None]] = []
            if e.op in ("delete", "update"):
                undo += self._del_rel(e.subject, e.key, e.value, qual_json(e.qualifiers))
            if e.op in ("add", "update"):
                undo += self._add_rel(e.subject, e.key, e.new_value, e.qualifiers)
            return undo

        # qualifier edits on the parent entry (and its mirror)
        entries = []
        if e.parent_kind == "attr":
            i = self._attr_idx(e.subject, e.parent_key, value_str(e.parent_value), qual_json(e.parent_qualifiers))
            if i >= 0:
                entries.append(kb.entities[e.subject]["attributes"][i])
        else:
            pq = qual_json(e.parent_qualifiers)
            i = self._rel_idx(e.subject, e.parent_key, "forward", e.parent_value, pq)
            if i >= 0:
                entries.append(kb.entities[e.subject]["relations"][i])
            if e.parent_value in kb.entities:
                j = self._rel_idx(e.parent_value, e.parent_key, "backward", e.subject, pq)
                if j >= 0:
                    entries.append(kb.entities[e.parent_value]["relations"][j])
        if not entries:
            raise EditError(f"qualifier parent not found in engine: {e.subject} {e.parent_key}")
        undo = []
        for entry in entries:
            old_quals = entry["qualifiers"]
            new_quals = {k: list(vs) for k, vs in old_quals.items()}
            if e.op == "add":
                new_quals.setdefault(e.key, []).append(self._parse(e.new_value))
            else:
                vals = new_quals.get(e.key, [])
                k = next((i for i, v in enumerate(vals) if str(v) == value_str(e.value)), -1)
                if k < 0:
                    raise EditError(f"qualifier not found in engine: {e.key} {value_str(e.value)}")
                if e.op == "delete":
                    vals.pop(k)
                    if not vals:
                        new_quals.pop(e.key)
                else:
                    vals[k] = self._parse(e.new_value)
            entry["qualifiers"] = new_quals

            def undo_q(entry=entry, old_quals=old_quals) -> None:
                entry["qualifiers"] = old_quals
            undo.append(undo_q)
        return undo


def _eng_qual_json(quals: dict) -> str:
    """qual_json for engine entries whose qualifier values are parsed ValueClass objects."""
    import json
    return json.dumps({k: sorted(str(v) for v in vs) for k, vs in quals.items() if vs}, sort_keys=True)

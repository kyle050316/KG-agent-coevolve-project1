import pytest

from kgcoevo.kb.executor import Executor
from kgcoevo.kb.paths import PathSampler
from kgcoevo.kb.store import Edit, EditError, KBStore, apply_edits
from kgcoevo.kb.trace import trace
from kgcoevo.kb.values import surface_forms, value_str
from tests.fixtures.mini import QUESTIONS, make_kb


def test_values_mirror_kopl():
    assert value_str({"type": "quantity", "value": 206, "unit": "centimetre"}) == "206 centimetre"
    assert value_str({"type": "quantity", "value": 345064, "unit": "1"}) == "345064"
    assert value_str({"type": "date", "value": "1961-08-04"}) == "1961-08-04"
    assert value_str({"type": "year", "value": 2009}) == "2009"
    assert "August 4, 1961" in surface_forms({"type": "date", "value": "1961-08-04"})
    assert "345,064" in surface_forms({"type": "quantity", "value": 345064, "unit": "1"})


def test_store_inventory(store):
    assert store.has_mirrors
    assert not KBStore(make_kb(mirrors=False)).has_mirrors
    rels = [f for f in store.facts.values() if f.kind == "rel"]
    assert len(rels) == 26  # one canonical fact per forward entry, mirrors are not double counted
    assert store.find_fact("rel", "Q76", "spouse", "Q13133") is not None
    assert len(store.quals(store.find_fact("rel", "Q76", "award received", "Q35637").fid)) == 1
    assert store.functional_keys(min_subjects=2)["date of birth"]


def test_engine_answers_fixture_questions(executor):
    for q in QUESTIONS:
        res = executor.run(q["program"])
        assert res.ok, (q["question"], res.error)
        assert res.answers == [q["answer"]], q["question"]


def test_program_whitelist(executor):
    assert not executor.run([{"function": "__init__", "inputs": []}]).ok
    assert not executor.run([{"function": "_parse_key_value", "inputs": ["a", "b"]}]).ok


def _probe_programs(store):
    progs = [q["program"] for q in QUESTIONS]
    for eid in store.entities:
        name = store.name(eid)
        for rel in sorted({f.key for f in store.facts.values() if f.kind == "rel"}):
            for d in ("forward", "backward"):
                progs.append([{"function": "Find", "inputs": [name]}, {"function": "Relate", "inputs": [rel, d]},
                              {"function": "QueryName", "inputs": []}])
        for key in sorted({f.key for f in store.facts.values() if f.kind == "attr"}):
            progs.append([{"function": "Find", "inputs": [name]}, {"function": "QueryAttr", "inputs": [key]}])
    return progs


def _edits(store):
    f = store.find_fact
    dob = f("attr", "Q76", "date of birth", "1961-08-04")
    spouse = f("rel", "Q76", "spouse", "Q13133")
    award = f("rel", "Q76", "award received", "Q35637")
    pop = f("attr", "Q18094", "population", "345064")
    return [
        Edit.delete(store, dob),
        Edit.update(store, dob, {"type": "date", "value": "1963-08-04"}),
        Edit.delete(store, spouse),
        Edit.update(store, spouse, "Q432473"),
        Edit.delete(store, store.quals(award.fid)[0]),
        Edit.update(store, store.quals(award.fid)[0], {"type": "year", "value": 2010}),
        Edit.update(store, store.quals(pop.fid)[0], {"type": "year", "value": 2000}),
        Edit.add_attr("Q6279", "sex or gender", {"type": "string", "value": "male"}),
        Edit.add_rel("Q6279", "spouse", "Q432473"),
    ]


@pytest.mark.parametrize("i", range(9))
def test_patched_engine_equals_rebuilt_engine(store, executor, i):
    edit = _edits(store)[i]
    rebuilt = Executor(apply_edits(store.kb, [edit], store.has_mirrors), store.has_mirrors)
    progs = _probe_programs(store)
    before = [executor.run(p).to_json() for p in progs]
    with executor.patched([edit]):
        patched = [executor.run(p).to_json() for p in progs]
    after = [executor.run(p).to_json() for p in progs]
    assert patched == [rebuilt.run(p).to_json() for p in progs]
    assert after == before  # undo restores the engine exactly
    assert patched != before  # the edit is visible


def test_untouched_fact_ids_are_stable(store):
    edit = _edits(store)[3]
    gw = KBStore(apply_edits(store.kb, [edit], store.has_mirrors))
    lost = set(store.facts) - set(gw.facts)
    assert edit.target_fid in lost
    # only the edited fact and its qualifier facts change id
    assert len(lost) == 1 + len(store.quals(edit.target_fid))
    assert gw.find_fact("rel", "Q76", "spouse", "Q432473") is not None


def test_missing_fact_raises(store):
    bad = Edit("delete", "attr", "Q76", "height", {"type": "quantity", "value": 1, "unit": "1"})
    with pytest.raises(EditError):
        apply_edits(store.kb, [bad], True)


def test_trace_provenance(store, executor):
    t = trace(executor, QUESTIONS[2]["program"])
    assert t.ok and t.answers == ["1961-08-04"]
    kinds = sorted((d["kind"], d["key"]) for d in t.facts)
    assert kinds == [("attr", "date of birth"), ("rel", "spouse")]
    spouse = store.find_fact("rel", "Q13133", "spouse", "Q76")
    assert store.cid(spouse.fid) in t.cids
    t = trace(executor, QUESTIONS[3]["program"])
    assert t.ok and {d["kind"] for d in t.facts} == {"rel", "qual"}
    assert not trace(executor, QUESTIONS[-1]["program"]).ok  # Count is not traceable
    assert trace(executor, QUESTIONS[-2]["program"]).ok  # Verify keeps provenance


def test_trace_under_edit(store, executor):
    edit = _edits(store)[1]  # corrupt Obama's date of birth
    t = trace(executor, QUESTIONS[2]["program"], [edit])
    assert t.answers == ["1963-08-04"]
    assert any(d["value"] == "1963-08-04" for d in t.facts)


def test_path_sampler(store, executor):
    weights = {"attr": 1, "rel": 1, "rel_attr": 1, "rel_rel": 1, "rel_qual": 1, "rel_relqual": 1, "attr_qual": 1}
    paths = PathSampler(store, executor, seed=1).sample(["Q76", "Q13133", "Q22686", "Q15070044"], 25, weights)
    assert len(paths) >= 15
    for p in paths:
        assert executor.run(p.program).answers == [p.answer_gw]
        assert store.name(p.anchor) in p.template_question
        for h in p.hidden:
            assert store.name(h) not in p.template_question
    assert {p.hops for p in paths} == {1, 2}

import math

from kgcoevo.data.defects import inject_defects
from kgcoevo.data.support import build_support, pages_index
from kgcoevo.docs.kilt import page_words
from kgcoevo.docs.passages import build_passages, sentence_spans
from kgcoevo.eval.checks import rule_checks
from kgcoevo.eval.compare import answers_equal, canon
from kgcoevo.eval.discovery import KeyResolver, score_report
from kgcoevo.eval.stats import cluster_bootstrap, cohen_kappa, holm, mcnemar_exact, wilson
from kgcoevo.kb.store import KBStore
from kgcoevo.llm.parsing import extract_json
from tests.fixtures.mini import make_kilt_pages


def _pages():
    out = {}
    for p in make_kilt_pages():
        out[p["wikidata_info"]["wikidata_id"]] = {
            "qid": p["wikidata_info"]["wikidata_id"], "wikipedia_id": p["wikipedia_id"], "title": p["wikipedia_title"],
            "paragraphs": [t.rstrip("\n") for t in p["text"]],
            "anchors": [{k: a[k] for k in ("paragraph_id", "start", "end", "text", "wikipedia_id")} for a in p["anchors"]]}
    return out


def test_compare():
    assert answers_equal("August 4, 1961", "1961-08-04")
    assert answers_equal("345,064", "345064")
    assert answers_equal("206", "206 centimetre")
    assert not answers_equal("206 metre", "206 centimetre")
    assert answers_equal("The Democratic Party", "Democratic Party")
    assert canon("2009") == "num:2009" and not answers_equal("2009", "2010")


def test_stats():
    p, lo, hi = wilson(5, 10)
    assert math.isclose(p, 0.5) and lo < 0.5 < hi
    m, lo, hi = cluster_bootstrap([1, 0, 1, 1], ["a", "a", "b", "c"], n_boot=500)
    assert lo <= m <= hi
    assert mcnemar_exact([1, 1, 0, 0], [0, 0, 0, 0])["b10"] == 2
    adj = holm({"x": 0.01, "y": 0.04})
    assert adj["x"] == 0.02 and adj["y"] == 0.04
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0


def test_extract_json():
    assert extract_json('blah ```json\n{"a": 1}\n``` tail') == {"a": 1}
    assert extract_json('Answer: {"b": [1, 2]} trailing') == {"b": [1, 2]}
    assert extract_json("no json") is None


def test_passages_keep_gold_links():
    pages = _pages()
    ps = build_passages(pages, {"Q76"}, max_words=25)
    linked = [p for p in ps if any(q == "Q18094" for _, _, q in p.anchors)]
    assert linked
    p = linked[0]
    s, e, _ = next(a for a in p.anchors if a[2] == "Q18094")
    assert p.text[s:e] == "Honolulu"
    assert "Honolulu [Q18094]" in p.linked_text()
    assert len(sentence_spans("A b. C d. E f.")) == 3
    assert page_words(pages["Q76"]) > 20


def test_support_and_defects(store):
    ps = build_passages(_pages(), set(_pages()), max_words=100)
    recs = build_support(store, pages_index(ps), ["Q76", "Q13133", "Q22686"])
    sup = {(r["subject"], r["key"], r["value"]): r for r in recs if r["supported"]}
    assert ("Q76", "date of birth", "1961-08-04") in sup  # exact date
    assert ("Q76", "spouse", "Q13133") in sup  # anchor co-mention + cue ("married")
    assert ("Q76", "award received", "Q35637") in sup
    assert not any(k == ("Q76", "sex or gender", "male") for k in sup)  # value not stated in text
    award = next(r for r in recs if r["kind"] == "qual" and r["key"] == "point in time" and r["subject"] == "Q76")
    assert award["supported"]  # "2009" in the same sentence as the award
    d1 = inject_defects(store, recs, rate=0.5, seed=1, scope=["Q76", "Q13133"])
    d2 = inject_defects(store, recs, rate=0.5, seed=1, scope=["Q76", "Q13133"])
    assert [x.to_json() for x in d1] == [x.to_json() for x in d2]  # deterministic
    assert {x.op for x in d1} == {"delete", "corrupt"}
    assert all(x.in_support for x in d1)
    fids = [x.fid for x in d1]
    assert len(fids) == len(set(fids))
    assert all(x.kind in ("attr", "rel") for x in d1)  # no qualifier defects


def test_defects_skip_duplicates_and_pass_self_check():
    from kgcoevo.data.defects import build_gw, editable, self_check
    from kgcoevo.kb.executor import Executor
    from tests.fixtures.mini import make_kb
    kb = make_kb()
    # a second "educated at Harvard" with another qualifier: deleting either copy would change no answer
    kb["entities"]["Q76"]["relations"].append({"relation": "educated at", "direction": "forward", "object": "Q13371",
                                               "qualifiers": {"academic degree": [{"type": "string", "value": "JD"}]}})
    store = KBStore(kb)
    dup = [f for f in store.rel_out("Q76", "educated at") if f.value == "Q13371"]
    assert len(dup) == 2 and not any(editable(store, f) for f in dup)
    recs = [{"fid": f.fid, "subject": f.subject, "supported": True} for f in store.facts.values()
            if f.subject in ("Q76", "Q13133")]
    defects = inject_defects(store, recs, rate=1.0, seed=0, scope=["Q76", "Q13133"])
    assert defects and not any(d.fid in {f.fid for f in dup} for d in defects)
    gw = KBStore(build_gw(store, defects), normalized=True)
    assert self_check(store, gw, Executor.from_store(gw), defects)["n_failed"] == 0


def test_rule_checks():
    r = rule_checks("When was the spouse of Michelle Obama born?", "1961-08-04", ["Michelle Obama"], ["Barack Obama"])
    assert r["e3_rules"]
    assert rule_checks("When was Barack Obama, spouse of Michelle Obama, born?", "1961-08-04", ["Michelle Obama"],
                       ["Barack Obama"])["bridge_leak"]
    assert rule_checks("Was Obama born on August 4, 1961?", "1961-08-04", [], [])["answer_leak"]


def test_discovery_categories(store):
    gw = KBStore(store.kb, normalized=True)
    defects = [{"defect_id": "d1", "op": "delete", "subtype": "attr_date", "hardness": "n/a", "kind": "attr",
                "subject": "Q76", "key": "date of birth", "before": "1961-08-04", "functional": True,
                "passage_ids": ["Q76:1:0"]}]
    gaps = [{"key": "Date of Birth", "claimed_value": "August 4, 1961", "label": "missing", "evidence_id": "Q76:1:0"},
            {"key": "spouse", "claimed_value": "Michelle Obama", "label": "missing", "evidence_id": "Q76:2:0"},
            {"key": "unknown key", "claimed_value": "x", "label": "missing", "evidence_id": "Q76:1:0"},
            {"key": "date of birth", "claimed_value": "1962-01-01", "label": "missing", "evidence_id": "Q76:1:0"},
            {"key": "date of birth", "claimed_value": "1961-08-04", "label": "conflict", "evidence_id": "Q76:1:0"}]
    sc = score_report(store, gw, KeyResolver(store), "Q76", gaps, defects)
    cats = [c["category"] for c in sc["claims"]]
    # already in Gw / unresolvable key -> other; right key, wrong value -> located_only; second hit with a wrong label
    assert cats == ["hit", "other", "other", "located_only", "hit"]
    assert sc["defects"][0]["detected"] and sc["defects"][0]["label_ok"]


def test_region_b_extra_keeps_a_and_core_b(monkeypatch):
    """Extra region-B entities are added after A and the first n_b B entities, so Exp 1 data stay valid."""
    from kgcoevo.data import region as R

    class Stub:
        name_to_ids = {f"N{i}": [f"E{i}"] for i in range(40)}

        def entities_with_concept(self, concept):
            return [f"E{i}" for i in range(40)]

        def facts_of(self, eid, kinds):
            return list(range(10))

        def rel_in(self, eid):
            return []

    monkeypatch.setattr(R, "find_prefix", lambda store, eid: [])
    words = {f"E{i}": 200 + 37 * i for i in range(40)}
    qs = [{"program": [{"function": "Find", "inputs": [f"N{i}"]}]} for i in range(40) for _ in range(3) if i % 4]
    kw = dict(n_a=5, n_b=5, min_facts=8, min_page_words=150, seed=0, questions=qs, min_questions_b=3)
    base = R.select_regions(Stub(), words, **kw)
    ext = R.select_regions(Stub(), words, n_b_extra=8, **kw)
    assert ext["A"] == base["A"] and ext["B_core"] == base["B"]
    assert set(base["B"]) < set(ext["B"]) and len(ext["B"]) == 13 and not set(ext["A"]) & set(ext["B"])
    assert all(int(e[1:]) % 4 for e in ext["B"])  # every B entity has KQA Pro questions


def test_two_sided_gate_blocks_an_edit_to_a_wrong_key(store, executor):
    """An edit that the cited item supports is still blocked when a shown item states the replaced value."""
    import asyncio
    import json
    import re
    from types import SimpleNamespace

    from experiments.exp2.run import source_gate
    from kgcoevo.agents.curator import build_edit
    from kgcoevo.eval.checks import answer_forms
    from kgcoevo.eval.compare import mentions
    from kgcoevo.llm.client import MockLLM

    def judge(msgs, seed):
        text = msgs[-1]["content"]
        passage = text.split('"""')[1]
        value = re.split(r" is |: ", text.split("Claim: ")[1].split("\n")[0])[-1].rstrip(".")
        return json.dumps({"entails": any(mentions(passage, f) for f in answer_forms(value))})

    js = {"op": "update", "subject": "Barack Obama", "key": "date of birth", "old_value": "1961-08-04",
          "new_value": "1900-01-01", "evidence_id": "p1"}
    edit, err = build_edit(executor, store.name_to_ids, [], js, prefer=[])
    assert edit is not None, err
    p1 = "A tabloid claimed that he was born on 1 January 1900."
    p2 = "Obama was born on August 4, 1961, in Honolulu."

    def gate(shown, js_edit=js):
        return asyncio.run(source_gate(SimpleNamespace(gs=store), MockLLM(judge), executor, [], edit, js_edit, shown, {}))

    blocked = gate({"p1": p1, "p2": p2})
    assert blocked["verified"] and blocked["kg_supported"] and not blocked["admitted"]
    assert gate({"p1": p1})["admitted"]  # nothing shown states the replaced value
    assert not gate({"p2": p2}, {**js, "evidence_id": "p3"})["admitted"]  # cites an item that was not shown


def test_resolve_citation():
    from kgcoevo.agents.curator import resolve_citation
    shown = ["Q1:4:0", "Q2:1:0", "Q2:3:0"]
    assert resolve_citation("Q1:4:0", shown) == "Q1:4:0"
    assert resolve_citation("[Q1:4:0]", shown) == "Q1:4:0"
    assert resolve_citation("Q1", shown) == "Q1:4:0"   # the one shown passage of that entity
    assert resolve_citation("Q2", shown) == "Q2"       # ambiguous: stays unresolved
    assert resolve_citation("", shown) == ""


def test_program_steps_and_path_entities(store, executor):
    from kgcoevo.agents.curator import path_entity_ids, program_steps_text
    from kgcoevo.kb.store import Edit

    prog = [{"function": "Find", "inputs": ["Michelle Obama"]}, {"function": "Relate", "inputs": ["spouse", "forward"]},
            {"function": "QueryAttr", "inputs": ["date of birth"]}]
    steps = program_steps_text(executor, prog, [], store).split("\n")
    assert steps[1].endswith("-> Barack Obama") and steps[2].endswith("-> 1961-08-04")
    assert path_entity_ids(executor, prog, []) == ["Q13133", "Q76"]
    f = store.find_fact("rel", "Q13133", "spouse", "Q76")
    cut = [Edit.delete(store, f)]
    steps = program_steps_text(executor, prog, cut, store).split("\n")
    assert steps[1].endswith("-> nothing") and steps[2].endswith("-> nothing")  # the missing edge shows where it breaks
    assert path_entity_ids(executor, prog, cut) == ["Q13133"]


def test_aggregate_samples():
    from experiments.exp2.analyze import aggregate

    e1 = {"op": "update", "kind": "attr", "subject": "Q1", "key": "date of birth", "new_value": {"type": "date", "value": "1961-08-04"}}
    e2 = {**e1, "new_value": {"type": "date", "value": "1900-01-01"}}
    s = [{"j": 0, "diagnosis": "bad_key", "final_edit": None, "admitted": False},
         {"j": 1, "diagnosis": "wrong_fact", "final_edit": e1, "admitted": True},
         {"j": 2, "diagnosis": "wrong_fact", "final_edit": e1, "admitted": False},
         {"j": 3, "diagnosis": "wrong_fact", "final_edit": e2, "admitted": True}]
    assert aggregate(s, "single") == {"diagnosis": "bad_key", "edit": None}
    assert aggregate(s, "majority") == {"diagnosis": "wrong_fact", "edit": e1}   # e1 proposed twice, admitted once
    assert aggregate(s, "any")["edit"] == e1
    assert aggregate(s, "consensus", m=2)["edit"] == e1
    assert aggregate(s, "consensus", m=3)["edit"] is None

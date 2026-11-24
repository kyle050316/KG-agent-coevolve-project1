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

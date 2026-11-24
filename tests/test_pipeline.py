"""End-to-end run of every Exp 1 / Exp 2 stage on the fixture KB with a scripted LLM.

The mock is not meant to be smart; it exercises every code path (accept/correct/reject, gap
reports, verbalisation, solver parsing and answering, judge, curator edits and the gate).
"""

import argparse
import json
import re

import pytest
import yaml

from kgcoevo.llm.client import MockLLM
from kgcoevo.llm.prompts import task_of
from kgcoevo.runner import read_jsonl
from tests.fixtures.mini import QUESTIONS, make_kb, make_kilt_pages


class Script:
    def __init__(self):
        self.paths = {}  # description -> path record
        self.programs = {q["question"]: q["program"] for q in QUESTIONS}

    def __call__(self, msgs, seed):
        text = msgs[-1]["content"]
        t = task_of(msgs)
        if t == "probe":
            return json.dumps({"answer": "1961-08-04" if "Barack Obama" in text else "unknown", "confidence": 0.5})
        if t == "challenger_mode_a":
            desc = text.split("## Reasoning path (fixed program that will be executed)\n")[1].split("\n\n## ")[0].strip()
            p = self.paths[desc]
            names = re.search(r"The question must name: (.*)", text).group(1)
            q = f"[{p['path_id']}] Following the path from {names.replace(chr(39), '')}, what is the result?"
            if "Passages:" in text or "Reference KG facts" in text:
                if p["answer_affecting"]:
                    if p["gs_answers"]:
                        return json.dumps({"decision": "correct", "question": q, "answer": p["gs_answers"][0], "suspect_facts": []})
                    return json.dumps({"decision": "reject", "question": "", "answer": "", "suspect_facts": []})
            return json.dumps({"decision": "accept", "question": q, "answer": p["answer_gw"], "suspect_facts": []})
        if t == "challenger_mode_b":
            pids = re.findall(r"\[(Q\d+:\d+:\d+)\]", text)
            if pids or "REF:" in text:
                ev = pids[0] if pids else "REF"
                return json.dumps({"gaps": [
                    {"key": "date of birth", "kg_value": "", "claimed_value": "1961-08-04", "label": "missing", "evidence_id": ev},
                    {"key": "spouse", "kg_value": "", "claimed_value": "Michelle Obama", "label": "conflict", "evidence_id": ev},
                    {"key": "favourite food", "kg_value": "", "claimed_value": "pizza", "label": "missing", "evidence_id": "x"}]})
            return json.dumps({"gaps": []})
        if t == "verbalize":
            names = re.search(r"The question must name: (.*)", text).group(1).replace("'", "")
            return json.dumps({"question": f"What does the program starting from {names} return?"})
        if t == "judge_faithfulness":
            return json.dumps({"faithful": "starting from" not in text})
        if t == "solver_parse":
            q = text.split("## Question\n")[1].split("\n")[0].strip()
            m = re.match(r"\[(\w+)\]", q)
            if m:
                for p in self.paths.values():
                    if p["path_id"] == m.group(1):
                        return json.dumps({"program": p["program"]})
            return json.dumps({"program": self.programs.get(q, [{"function": "Find", "inputs": ["Nobody"]}, {"function": "QueryName", "inputs": []}])})
        if t == "solver_answer":
            res = text.split("Execution result: ")[1].split("\n")[0]
            try:
                vals = json.loads(res)
                return json.dumps({"answer": vals[0] if vals else "unknown", "source": "kg"})
            except json.JSONDecodeError:
                return json.dumps({"answer": "unknown", "source": "unknown"})
        if t == "closed_book_qa":
            return json.dumps({"answer": "unknown"})
        if t == "curator":
            pids = re.findall(r"\[(Q\d+:\d+:\d+)\]", text)
            ev = pids[0] if pids else "REF"
            if "Melania" in text:
                return json.dumps({"diagnosis": "non_kg", "located_fact": None, "edit": None})
            return json.dumps({"diagnosis": "missing_fact", "located_fact": {"subject": "Barack Obama", "key": "date of birth"},
                               "edit": {"op": "add", "subject": "Barack Obama", "key": "date of birth", "old_value": "",
                                        "new_value": "1961-08-04", "evidence_id": ev}, "confidence": 0.8})
        if t == "verify_entailment":
            return json.dumps({"entails": True})
        raise AssertionError(f"unexpected task {t}")


def _make_run(d, mutate=None):
    kq = d / "kqapro"
    kq.mkdir()
    (kq / "kb.json").write_text(json.dumps(make_kb()))
    (kq / "train.json").write_text(json.dumps(QUESTIONS[:9]))
    (kq / "val.json").write_text(json.dumps(QUESTIONS[9:]))
    src = d / "kilt.jsonl"
    src.write_text("\n".join(json.dumps(p) for p in make_kilt_pages()))
    cfg = yaml.safe_load(open("configs/base.yaml"))
    cfg["paths"] = {"kqapro_dir": str(kq), "kilt_source": str(src), "kilt_pages": str(d / "pages.jsonl"), "work_dir": str(d / "run")}
    cfg["region"].update({"n_a": 2, "n_b": 2, "min_facts": 3, "min_page_words": 5, "min_questions_b": 1})
    cfg["defects"].update({"rates": [0.3, 0.6], "main_rate": 0.6, "seeds": [0]})
    cfg["paths_sampling"].update({"n": 12, "n_sweep": 6})
    cfg["exp1"]["mode_a"]["conditions"] = ["B0", "C1", "C2", "C2link", "C3"]
    cfg["exp1"]["mode_b"].update({"conditions": ["C1", "C2", "C3"], "n_entities": 2})
    cfg["exp1"]["solver"].update({"n_per_condition": 5, "k": 2, "fewshot_pool": 100})
    cfg["exp1"]["audit"] = {"e3_n": 6, "natural_n": 5}
    cfg["exp2"].update({"pool_size": 50, "k": 2, "ablation_n": 6, "samples": 1, "locality_n": 10, "solver_locality_edits": 2,
                        "targets": {"missing_fact": 3, "wrong_fact": 3, "non_kg": 2, "invalid_task": 2, "non_kg_offpath": 2, "refer": 2}})
    if mutate:
        mutate(cfg)
    (d / "cfg.yaml").write_text(yaml.safe_dump(cfg))
    return d


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    return _make_run(tmp_path_factory.mktemp("e2e"))


def _args(d, stages):
    return argparse.Namespace(config=str(d / "cfg.yaml"), set=[], stages=stages)


def test_end_to_end(run_dir, capsys):
    from experiments.exp1 import analyze as a1, export_audit, prepare, run as r1
    from experiments.exp2 import analyze as a2, build_cases, run as r2
    from kgcoevo.config import load_config
    from kgcoevo.context import Context

    script = Script()
    llms = {r: MockLLM(script, r) for r in ("challenger", "solver", "curator", "judge")}

    import sys
    sys.argv = ["prepare", "--config", str(run_dir / "cfg.yaml")]
    prepare.main()
    ctx = Context(load_config(run_dir / "cfg.yaml"))
    for s in ctx.cfg["defects"]["seeds"]:
        for p in ctx.paths(0.6, s):
            script.paths[p["description"]] = p
    assert ctx.paths(0.6, 0), "paths were sampled"
    assert ctx.defects(0.6, 0), "defects were injected"
    assert json.loads((ctx.gw_dir(0.6, 0) / "selfcheck.json").read_text())["n_failed"] == 0

    r1.main(llms, _args(run_dir, ["all"]))
    tasks = read_jsonl(run_dir / "run" / "exp1" / "tasks.jsonl")
    assert tasks and any(t["condition"] == "B0" for t in tasks)
    assert any(t["source"] == "gap" for t in tasks)
    b0 = [t for t in tasks if t["condition"] == "B0"]
    # B0 accepts every path with its Gw answer: contamination == answer-affecting among valid tasks
    assert all(t["contaminated"] == t["path_answer_affecting"] for t in b0 if t["valid"])
    assert read_jsonl(run_dir / "run" / "exp1" / "solver.jsonl")

    sys.argv = ["x", "--config", str(run_dir / "cfg.yaml")]
    export_audit.main()
    a1.main()
    report = (run_dir / "run" / "results" / "exp1_report.md").read_text()
    for section in ("Funnel", "Contamination", "Paired differences", "Mode B", "Task quality"):
        assert section in report

    build_cases.main(llms, _args(run_dir, ["all"]))
    cases = read_jsonl(run_dir / "run" / "exp2" / "cases.jsonl")
    assert cases and {c["cls"] for c in cases} & {"missing_fact", "wrong_fact"}
    r2.main(llms, _args(run_dir, ["all"]))
    cur = read_jsonl(run_dir / "run" / "exp2" / "curator.jsonl")
    assert cur and all("error" not in r for r in cur), [r.get("error") for r in cur if "error" in r][:3]
    a2.main()
    rep2 = (run_dir / "run" / "results" / "exp2_report.md").read_text()
    assert "Gate behaviour" in rep2 and "Locality" in rep2


def test_exp1_minimal_config(tmp_path):
    """configs/exp1_min.yaml shape: one rate, B0/C1/C2/C3, no C0 probe, no closed-book Solver setting."""
    import sys

    from experiments.exp1 import analyze as a1, prepare, run as r1
    from kgcoevo.config import load_config
    from kgcoevo.context import Context

    def mutate(cfg):
        cfg["defects"].update({"rates": [0.6], "main_rate": 0.6})
        cfg["exp1"]["mode_a"]["conditions"] = ["B0", "C1", "C2", "C3"]
        cfg["exp1"]["solver"]["settings"] = ["gw", "gstar"]

    d = _make_run(tmp_path, mutate)
    sys.argv = ["prepare", "--config", str(d / "cfg.yaml"), "--stages", "kilt", "region", "passages", "support",
                "defects", "paths"]
    prepare.main()
    script = Script()
    for p in Context(load_config(d / "cfg.yaml")).paths(0.6, 0):
        script.paths[p["description"]] = p
    llms = {r: MockLLM(script, r) for r in ("challenger", "solver", "curator", "judge")}
    r1.main(llms, _args(d, ["mode_a", "mode_b", "gap_tasks", "checks", "judge", "solver"]))
    assert not (d / "run" / "exp1" / "probe.jsonl").exists()
    sys.argv = ["x", "--config", str(d / "cfg.yaml")]
    a1.main()
    rep = (d / "run" / "results" / "exp1_report.md").read_text()
    assert "| C3 |" in rep and "C2link" not in rep
    quality = rep.split("## Task quality (Solver)")[1]
    assert "n/a" in quality  # closed-book columns are reported as not run

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


# Mock Solver behaviour that produces every Exp 2 case type on the fixture:
# MEMORY      answered from memory when the KG execution fails (silent KG cases / ungrounded non-KG cases)
# UNGROUNDED  the mock parses a wrong program (non_kg/ungrounded: right answer, KG not used)
# WRONG       the mock gives a wrong final answer (non_kg/wrong)
MEMORY = {"When was Barack Obama born?": "1961-08-04", "When was the spouse of Michelle Obama born?": "1961-08-04",
          "Is Barack Obama male?": "yes"}
UNGROUNDED = {"Is Barack Obama male?"}
WRONG = {"Where was Michelle Obama born?": "Honolulu"}


class Script:
    def __init__(self):
        self.paths = {}  # description -> path record
        self.programs = {q["question"]: q["program"] for q in QUESTIONS}
        self.know_prompts = 0  # Challenger prompts that allow background knowledge (C1know)

    def __call__(self, msgs, seed):
        text = msgs[-1]["content"]
        t = task_of(msgs)
        if t.startswith("challenger") and "own background knowledge" in text:
            self.know_prompts += 1
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
            wrong = [{"function": "Find", "inputs": ["Nobody"]}, {"function": "QueryName", "inputs": []}]
            return json.dumps({"program": wrong if q in UNGROUNDED else self.programs.get(q, wrong)})
        if t == "solver_answer":
            q = text.split("Question: ")[1].split("\n")[0].strip()
            res = text.split("Execution result: ")[1].split("\n")[0]
            try:
                vals = json.loads(res)
            except json.JSONDecodeError:
                vals = []
            if q in WRONG:
                return json.dumps({"answer": WRONG[q], "source": "kg"})
            if vals:
                return json.dumps({"answer": vals[0], "source": "kg"})
            if q in MEMORY:
                return json.dumps({"answer": MEMORY[q], "source": "memory"})
            return json.dumps({"answer": "unknown", "source": "unknown"})
        if t == "closed_book_qa":
            return json.dumps({"answer": "unknown"})
        if t == "curator":
            pids = re.findall(r"\[(Q\d+:\d+:\d+)\]", text)
            ev = pids[0] if pids else "REF"
            if "Melania" in text:
                return json.dumps({"diagnosis": "non_kg", "located_fact": None, "edit": None})
            cur = re.search(r"Barack Obama \| date of birth: (\S+)", text)
            edit = {"op": "update" if cur else "add", "subject": "Barack Obama", "key": "date of birth",
                    "old_value": cur.group(1) if cur else "", "new_value": "1961-08-04", "evidence_id": ev}
            return json.dumps({"diagnosis": "wrong_fact" if cur else "missing_fact",
                               "located_fact": {"subject": "Barack Obama", "key": "date of birth"}, "edit": edit, "confidence": 0.8})
        if t == "curator_decide":
            first = json.loads(msgs[-2]["content"])
            if "matches the answer key: yes" in text:
                return json.dumps({"decision": "commit", "diagnosis": first["diagnosis"], "edit": None})
            if "could not be applied" in text:
                return json.dumps({"decision": "withdraw", "diagnosis": "non_kg", "edit": None})
            return json.dumps({"decision": "revise", "diagnosis": first["diagnosis"], "edit": first["edit"]})
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
    cfg["defects"].update({"rate": 0.6, "seeds": [0]})
    cfg["paths_sampling"].update({"n_defective": 6, "n_clean": 6})
    cfg["exp1"]["mode_b"]["n_entities"] = 2
    cfg["exp1"]["solver"].update({"n_per_group": 5, "k": 2, "fewshot_pool": 100})
    cfg["exp1"]["audit"] = {"e3_n": 6}
    cfg["exp1"]["probe"]["enabled"] = True
    cfg["exp2"].update({"pool_size": 50, "k": 2, "ablation_n": 6, "samples": 2, "locality_n": 10, "solver_locality_edits": 2,
                        "ablations": ["full", "no_tool", "no_docs"], "targets": {"missing_fact": 3, "wrong_fact": 3, "non_kg": 2}})
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
    paths = ctx.paths(0.6, 0)
    assert ctx.defects(0.6, 0), "defects were injected"
    assert {p["group"] for p in paths} == {"defective", "clean"}, "both path groups were sampled"
    assert all(p["answer_affecting"] and p["defect_ids"] for p in paths if p["group"] == "defective")
    assert not any(p["answer_affecting"] for p in paths if p["group"] == "clean")
    assert json.loads((ctx.gw_dir(0.6, 0) / "selfcheck.json").read_text())["n_failed"] == 0

    r1.main(llms, _args(run_dir, ["all"]))
    assert script.know_prompts > 0, "C1know prompts allow background knowledge"
    mode_a = read_jsonl(run_dir / "run" / "exp1" / "mode_a.jsonl")
    assert {r["condition"] for r in mode_a} == {"B0", "C1", "C1know", "C2", "C3"}
    groups = {p["path_id"]: p["group"] for p in paths}
    c2 = [r for r in mode_a if r["condition"] == "C2" and groups[r["path_id"]] == "defective"]
    assert c2 and all(r["gold_pids"] and set(r["gold_pids"]) <= set(r["shown_pids"]) for r in c2), "C2 always shows gold"
    mode_b = read_jsonl(run_dir / "run" / "exp1" / "mode_b.jsonl")
    assert all(set(r["gold_pids"]) <= set(r["shown_pids"]) for r in mode_b if r["condition"] == "C2")
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
    for section in ("Defective paths", "Clean paths", "by cause", "Funnel", "Mode B", "Gap tasks", "Task quality",
                    "Difficulty on Gw", "wrong key on Gw"):
        assert section in report, section
    assert "Paired" not in report and "McNemar" not in report  # counts only

    build_cases.main(llms, _args(run_dir, ["all"]))
    cases = read_jsonl(run_dir / "run" / "exp2" / "cases.jsonl")
    assert cases and {c["cls"] for c in cases} & {"missing_fact", "wrong_fact"}
    assert {c["cls"] for c in cases} <= {"missing_fact", "wrong_fact", "non_kg"}
    assert all(c["traj"] for c in cases if c["t1"] or c["t2"])
    kinds = {(c["cls"], c["subtype"]) for c in cases}
    assert ("non_kg", "wrong") in kinds and ("non_kg", "ungrounded") in kinds, kinds
    assert any(c["t2"] and not c["t1"] for c in cases if c["cls"] != "non_kg"), "a silent KG case (T2 only)"
    r2.main(llms, _args(run_dir, ["all"]))
    cur = read_jsonl(run_dir / "run" / "exp2" / "curator.jsonl")
    assert cur and all("error" not in r for r in cur), [r.get("error") for r in cur if "error" in r][:3]
    assert {r["ablation"] for r in cur} == {"full", "no_tool", "no_docs"}
    assert all(r["tool"] is None and r["second"] is None for r in cur if r["ablation"] == "no_tool")
    assert any(r["second"] for r in cur if r["ablation"] == "full"), "the tool turn ran"
    assert not any(r["admitted"] for r in cur if r["ablation"] == "no_docs"), "no evidence -> nothing admitted"
    assert any(r["admitted"] for r in cur)
    a2.main()
    rep2 = (run_dir / "run" / "results" / "exp2_report.md").read_text()
    for section in ("Cases and trigger coverage", "Diagnosis and repair", "End-to-end", "Counterfactual tool",
                    "Paired ablations", "Source gate", "Locality", "Baselines"):
        assert section in rep2, section


def test_exp1_main_config(tmp_path):
    """Main-config conditions (B0/C1/C1know/C2/C3), no C0 probe; a Solver setting that was not run is left out."""
    import sys

    from experiments.exp1 import analyze as a1, prepare, run as r1
    from kgcoevo.config import load_config
    from kgcoevo.context import Context

    def mutate(cfg):
        cfg["exp1"]["solver"]["settings"] = ["gw", "gstar"]
        cfg["exp1"]["probe"]["enabled"] = False

    d = _make_run(tmp_path, mutate)
    sys.argv = ["prepare", "--config", str(d / "cfg.yaml"), "--stages", "kilt", "region", "passages", "support",
                "defects", "paths"]
    prepare.main()
    script = Script()
    for p in Context(load_config(d / "cfg.yaml")).paths(0.6, 0):
        script.paths[p["description"]] = p
    llms = {r: MockLLM(script, r) for r in ("challenger", "solver", "curator", "judge")}
    r1.main(llms, _args(d, ["probe", "mode_a", "mode_b", "gap_tasks", "checks", "judge", "solver"]))
    assert not (d / "run" / "exp1" / "probe.jsonl").exists()
    sys.argv = ["x", "--config", str(d / "cfg.yaml")]
    a1.main()
    rep = (d / "run" / "results" / "exp1_report.md").read_text()
    assert "| C3 |" in rep and "| C1know |" in rep and "C2link" not in rep
    quality = rep.split("## Task quality (Solver)")[1]
    assert "gstar: pass vs G*" in quality and "closed" not in quality

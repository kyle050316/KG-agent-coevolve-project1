# KG–Agent Co-evolution, Project 1: Experiments 1 and 2

Code for the first two experiments of Project 1 ("Joint evolution of a KG and a clinical agent"),
run in a controlled sandbox built on the **KQA Pro** knowledge base. The KQA Pro KB plays the role of
the scoring KG, Wikipedia (KILT snapshot) plays the role of the literature, and the backbone model is
**Qwen3.5-9B** served with vLLM.

* **Exp 1 (Challenger).** When the KG has defects, how many KG-generated tasks have wrong answer
  keys? Can documents help the Challenger find the defects?
* **Exp 2 (Curator).** When a Solver task is flagged, can the Curator find the KG defect behind it
  (missing or wrong fact, or no KG fault) and repair the KG from documents without damaging it?

Every answer key, check and score is computed by executing KoPL programs with the **official KoPL
engine** on the hidden reference KB G\* and the defective working KB Gw. LLM judgments are used only
where execution cannot decide, such as whether a question faithfully expresses a program. Those are
audited by humans.

```
 G* (KQA Pro KB) --inject defects into S--> Gw (working KG) ----+
 D  (KILT Wikipedia passages, gold entity links) ---------------+--> Challenger --tasks--> Solver --failures--> Curator
                                                                        Exp 1                                   Exp 2
```

---

## 1. Design

### 1.1 Shared setup

| Component | Implementation | Why |
|---|---|---|
| Reference KB G\* | Official KQA Pro `kb.json` (16,960 entities), loaded by the official KoPL engine | Exact, executable ground truth |
| Documents D | KILT Wikipedia snapshot (2019-08-01), cut into ≤100-word passages that keep hyperlink anchors → Wikidata QIDs | Closer in time to the KB than today's Wikipedia; anchors give gold entity links |
| Regions | 400 "human" entities, stratified by page length (head/torso/tail). **A** (200) for Exp 1; **B** (200, entities that KQA Pro questions are about) for Exp 2 | Popularity strongly affects memorisation (PopQA); disjoint regions keep Exp 2/3 held-out |
| S (document-supported facts) | T-REx-style alignment: exact dates, numbers and strings; years and relations only together with a relation cue word; human audit of 50 facts | Every injected defect is discoverable from text in principle |
| Defects → Gw | Sampled from S at 30% (10/20% added in `extended.yaml` for a dose-response), deletions:corruptions = 1:1; corruptions are *similar* (type-consistent) or *random* (50/50); both copies of a relation (forward and backward) edited together; self-check on the engine | KG error-detection protocol (CKRL/CAGED); CCA shows similar noise is the hard case |
| Paths | Sampled on Gw, compiled to KoPL by a deterministic compiler, unique answer on Gw verified by execution; 1-hop and 2-hop, attributes, relations and qualifiers | LLM program-writing errors cannot be mistaken for KG-induced errors |

### 1.2 Exp 1: conditions and modes

The main design compares three information conditions; B0 is a free no-LLM reference line.

| Condition | The Challenger sees | Mode A (path → task) | Mode B (entity → gap report) |
|---|---|---|---|
| **B0** | nothing (no LLM; template question, Gw answer) | ✓ exact contamination baseline | – |
| **C1** | Gw (KG only) | ✓ | ✓ |
| **C2** | Gw + BM25 passages (KG + documents) | ✓ (main) | ✓ (main) |
| **C3** | Gw + G\* (KG + reference KG, oracle) | ✓ upper bound | ✓ upper bound |
| C0 *(extended)* | entity name only (closed-book probe of every S fact) | – | ✓ what memory alone recovers |
| C2link *(extended)* | as C2, with gold KG ids after linked mentions | ✓ | ✓ |

All conditions receive the **same paths and entities** (paired design). Evidence is pre-retrieved by a
fixed procedure, so conditions differ only in the information they show.

**Mode A.** The Challenger checks the path facts and either accepts the path (writing a question), corrects
the answer from evidence, or rejects the path. Each task then goes through the checks below.

| Check | Decided by | Meaning |
|---|---|---|
| E0 format | program | JSON parses, KoPL program well formed |
| E1 executable | KoPL engine | runs on Gw (on G\* for tasks built from facts missing in Gw), non-empty answer |
| E2 bookkeeping | KoPL engine | the answer key equals the program output on Gw (accepted tasks) |
| E3 faithful | rules + LLM judge + human audit | anchor named, no bridge entity or answer leaked; question expresses the program |
| E4 unique | KoPL engine | exactly one answer on G\* |
| **E5 contaminated** | KoPL engine | passes E0–E4 but the key differs from the G\* answer, i.e. caused by a KG defect |

**Mode B.** Each claimed gap is scored against the defect log as *hit / located-only / false gap /
unsupported / natural*. Natural gaps are real gaps in the original KB; they are excluded from precision and
human-audited. The analysis reports precision, end-to-end recall, recall on defects whose gold passage was
shown, label accuracy and a FEVER-style strict score. Reported gaps are then compiled into 2-hop tasks that
go through the same checks.

**Task quality.** The Solver answers a sample of valid tasks on Gw, on G\* and closed-book. The analysis
reports gap dependence (fails on Gw, succeeds on G\*), closed-book leakage, frontier rate (25–75% pass
rate) and tasks that fail even on G\*.

**Hypotheses** (fix them before the main run):

* H1: C1 ≈ B0: the LLM alone does not lower contamination.
* H2: C2 < C1 on per-path contamination (paired).
* H3: Mode B recall C2 > C1, with precision above a preset threshold; C3 bounds both.
* H4: recall is lower for similar corruptions and tail entities.
* (extended) B0 contamination rises with the defect rate; C2link closes most of the C2–C3 gap.

### 1.3 Exp 2: cases, triggers and Curator

The goal is that the Curator **finds KG defects and repairs the KG**; the cause label is an intermediate
output. Each KG case has one sandboxed defect on a fact of the gold path (IKGQA protocol, Generate-on-Graph).

| Class | Construction | Correct behaviour |
|---|---|---|
| missing_fact | a document-supported attr/rel fact on the gold path is deleted | re-add the fact from text |
| wrong_fact | such a fact is corrupted with a type-consistent value | update the value back |
| non_kg | intact KG. *wrong*: Solver stably wrong on G\*; *ungrounded*: Solver stably right, but its KG execution does not return the answer | no edit |

* **Pool.** KQA Pro train/val questions anchored on region B whose official program is traceable on G\*
  and returns the gold answer. Base questions for KG cases are stably correct **and grounded** on G\*
  (k=4 Solver samples; stable = ≥3/4, stably wrong = ≤1/4). Only facts a single-fact edit can restore are
  used (no qualifier facts, no qualifiers that the gold program reads).
* **KG cases are kept whether or not the Solver still answers correctly.** *Visible*: stably wrong;
  *silent*: stably right from memory although the KG is broken; *mixed*: in between.
* **Triggers** (from k Solver samples on the case KG):
  * **T1** (answer-based): the final answer is stably wrong.
  * **T2** (grounding-based): the KG execution stably does not return the answer key. Only T2 catches
    silent defects; on an intact KG it also flags *ungrounded* non-KG cases (the cost of T2).
* **Curator** (prompt-based, same 9B model). The counterfactual re-run is a **tool**, not a gate, because a
  correct edit does not fix a wrong Solver program:
  1. Turn 1: question, answer key, why the task was flagged, Solver trajectory, current KG facts around the
     path, and BM25 passages from the linked entities and their neighbours on the case KG. Output: diagnosis
     (missing_fact / wrong_fact / non_kg), located fact, and one add/update edit citing an evidence id.
  2. Tool: the edit is applied to a sandbox copy, the Solver's program is re-executed and the Solver
     re-answers; the result goes back to the model as text.
  3. Turn 2: commit, revise or withdraw.
  4. Source gate (proposal): the edit is admitted only if it cites a passage that was shown and an
     independent verifier says the passage states the new fact. Deletions are never admitted.
* **Ablations** (paired, on a stratified subset): `no_tool` (turn 1 is final); `no_docs` (extended).
* **Metrics** (all edit scoring is exact, against the defect log and G\*):
  * **Primary:** admitted exact repair, separately for missing and wrong facts and for visible and silent cases.
  * **False edits** on non_kg cases (the KG was intact) and **edit precision**: admitted edits that are true in G\*.
  * **End-to-end repair** over all KG cases (trigger recall × Curator), for the T1 and T1+T2 views;
    program restore (the gold program returns the gold answer again).
  * Diagnosis: 3-way accuracy and macro-F1 (bootstrap), KG vs non-KG precision/recall, confusion matrix;
    localisation (step-level, as in Who&When).
  * Tool effects: decisions, how often an exact edit fixes the Solver (why the tool cannot be a gate),
    exact edits withdrawn, wrong edits withdrawn or corrected; full vs no_tool with exact McNemar.
  * **Locality** (regressions among previously correct neighbour questions) and **portability** (questions that
    use the repaired fact become correct), exact with gold KQA Pro programs; Solver-level locality on a subset.
  * Baselines: execution rule (error/empty → missing, other answer → wrong, key returned → non_kg),
    majority class, and a surface-feature logistic regression as a shortcut check (AUC near 0.5 is good).
* **Hypotheses:** H5: T1+T2 repairs more KG cases end-to-end than T1 alone, mostly silent ones, with a
  bounded false-edit rate on ungrounded non-KG cases. H6: the tool lowers false edits without withdrawing
  correct ones (full vs no_tool, paired).

### 1.4 Statistics and reporting

* Proportions are reported with Wilson 95% CIs.
* Means use cluster bootstrap over anchor entities (Miller 2024, *Adding Error Bars to Evals*).
* Conditions are compared on paired items: paired cluster bootstrap plus exact McNemar, Holm-corrected over the pre-registered hypotheses.
* Human audits use two annotators and report Cohen's κ; the LLM judge's accuracy is measured against the human majority.
* Every run writes `config.resolved.yaml` and `manifest.jsonl` (package versions, git commit). Commit and tag the
  resolved config before the main run; it is the pre-registration.

---

## 2. Quick start

```bash
git clone https://github.com/kyle050316/KG-agent-coevolve-project1.git
cd KG-agent-coevolve-project1
pip install -e ".[dev]"
pytest -q          # 28 tests, incl. an end-to-end run of every stage on a tiny KB with a scripted LLM
```

### Colab, one A100 (80 GB recommended) or H100

```bash
pip install -e . && pip install vllm                    # a vLLM release that supports Qwen3.5
bash scripts/download_data.sh data                     # official KQA Pro release -> data/kqapro
nohup bash scripts/serve_vllm.sh > vllm.log 2>&1 &     # A100 40GB: MAX_SEQS=32 bash scripts/serve_vllm.sh
bash scripts/wait_for_server.sh

D=/content/drive/MyDrive/kgcoevo                       # keep everything on Drive: a disconnect loses nothing
SET="paths.kqapro_dir=data/kqapro paths.kilt_pages=$D/kilt/kb_pages.jsonl"

# 1) pilot on real data (about 30-45 min): every stage with small numbers, in its own work dir
CFG=configs/pilot.yaml bash scripts/run.sh all $SET paths.work_dir=$D/pilot

# 2) main run
W="paths.work_dir=$D/main"
bash scripts/run.sh prepare $SET $W                    # CPU part (KILT streaming ~30-60 min the first time)
bash scripts/run.sh exp1 $SET $W &                     # Exp 1
bash scripts/run.sh pool $SET $W; wait                 # Exp 2 pool runs in parallel on the same server
bash scripts/run.sh exp2 $SET $W                       # cases, Curator, locality, report
```

`scripts/run.sh` steps: `prepare | exp1 | pool | exp2 | all`; the config comes from `CFG` (default
`configs/main.yaml`) and any `key=value` after the step overrides it. Each stage can also be run on its own:

```bash
python -m experiments.exp1.run --config configs/main.yaml --stages mode_a
python -m experiments.exp2.run --config configs/main.yaml --stages curator
```

All stages are resumable: re-running a command skips items that are already in its JSONL output.
After the pilot, check the parse rates and the case counts printed by `build_cases` (how many KG cases are
visible vs silent) before starting the main run.

**Judge model.** By default `llm.judge` uses the same endpoint at temperature 0. A different model family
avoids self-preference. To use one, point `llm.judge.base_url/model/api_key` at it and set
`llm.judge.vllm_extras=false` for hosted APIs.

**Colab notes.**

* The official FAQ caps free notebooks at 12 h and Pro+ at 24 h of continuous execution. Runtimes can end
  earlier when idle or when compute units run out, and files on the VM are lost. Keep `work_dir` on Drive;
  every stage resumes where it stopped.
* A GPU runtime consumes compute units from the moment it is connected. Stop it as soon as the run finishes.

### Configs

| File | Use |
|---|---|
| `configs/base.yaml` | all defaults with comments = the simplified main design |
| `configs/main.yaml` | main run (work dir `runs/main`) |
| `configs/pilot.yaml` | smoke test on real data with small numbers |
| `configs/extended.yaml` | optional: B0 dose-response (10/20/30%), C0 probe, C2link, more paths, Solver k=4, no_docs ablation, 2 Curator seeds |

Override anything from the command line with `key.sub=value` after the step (or `--set key.sub=value`).

---

## 3. Outputs

```
<work_dir>/
  config.resolved.yaml, manifest.jsonl
  data/   region.json, passages.jsonl, support.jsonl, support_summary.json, probe_items.jsonl
          gw/rate30_seed0/{kb.json, defects.jsonl, selfcheck.json}    paths/rate30_seed0.jsonl
  exp1/   probe, mode_a, mode_b, gap_tasks, tasks (with E0-E5), judge, solver  (.jsonl)
  exp2/   pool, pool_solver, case_solver, cases, curator, locality_solver  (.jsonl)
  audit/  support_audit.csv, e3_audit.csv (+ key), natural_gaps_audit.csv
  results/ exp1_report.md, exp1_summary.json, exp1_mode_a_items.csv,
           exp2_report.md, exp2_summary.json, exp2_runs.csv
```

**Human steps.**

1. Fill in `audit/support_audit.csv` and check that S precision is ≥ 95% before the main run.
2. After Exp 1, two annotators fill in `audit/e3_audit.csv`. Save the filled sheet as `audit/e3_audit_labels.csv`;
   `experiments.exp1.analyze` then reports κ and the judge's accuracy.

---

## 4. Compute (rough estimates for `configs/main.yaml`)

These are planning numbers, not measurements. They assume 32–64 concurrent requests on vLLM with prefix
caching on one A100 80GB, and per-call token counts guessed before the pilot. Re-estimate from
`usage_last_run.jsonl` after the pilot; an H100 is roughly 1.5–2× faster.

| Stage | Calls (approx.) | A100 80GB hours |
|---|---|---|
| Exp 1 Mode A (B0 + C1/C2/C3 × 200 paths), Mode B (100 entities × 3), gap tasks, judge | ~2k | ~0.5 |
| Exp 1 Solver evaluation (Gw / G\* / closed-book) | ~1k | ~0.7 |
| Exp 2 pool (1,000 questions × 4 Solver samples) | ~4k solves | ~1–3 |
| Exp 2 KG cases (200 × 4 Solver samples) | ~800 solves | ~0.3–0.6 |
| Exp 2 Curator (2 turns + sandbox answer + verifier; no_tool on 100 cases) | ~1.5k | ~0.5–1 |
| Exp 2 Solver-level locality (20 edits × 30 questions × 2) | ~1.2k solves | ~0.5–0.9 |
| **Total** | | **~4–7** |

Exp 3 (GRPO on the 9B Solver) is not part of this repository and needs a multi-GPU node.

---

## 5. Repository layout

```
src/kgcoevo/
  kb/       store.py (facts, stable ids, pure edits), executor.py (official KoPL engine + sandbox patches),
            trace.py (provenance of answers), paths.py (path sampling, KoPL compiler), values.py
  docs/     kilt.py (streaming KILT), passages.py (chunks with gold links), retrieval.py (BM25)
  data/     region.py, support.py (S), defects.py (injection, Gw, self-check)
  agents/   evidence.py, challenger.py, solver.py, curator.py, judge.py
  eval/     checks.py (E0-E5), discovery.py (gap scoring), compare.py, stats.py
  llm/      client.py (OpenAI-compatible async client, mock), prompts.py, parsing.py
  prompts/  *.txt (all prompts, English)
  runner.py (resumable JSONL runner), config.py, context.py
experiments/exp1/  prepare.py, run.py, analyze.py, export_audit.py
experiments/exp2/  build_cases.py, run.py, analyze.py
tests/             unit tests + end-to-end pipeline test on a fixture KB
```

---

## 6. Known simplifications

* **Single-turn Challenger.** The Challenger receives pre-retrieved evidence instead of calling tools in a
  multi-turn loop. This removes the 9B model's tool-calling reliability as a confound. A multi-turn agent
  version is a natural follow-up.
* **Restricted traceability.** Exp 2 uses the traceable KoPL subset (chain programs). Questions with set
  operations, filters or aggregation are excluded because their gold path is not well defined.
* **Single-fact edits without qualifiers.** The Curator adds or updates one attr/rel fact; defects are drawn
  only from facts that such an edit can restore.
* **Biased S.** S only contains facts that Wikipedia states explicitly, so it is a biased subset of the KB
  (Kang et al. 2026). `support_summary.json` reports its composition; conclusions apply to text-supported facts.
* **Unverified KQA Pro snapshot date.** The KQA Pro paper does not state its Wikidata snapshot date; the
  2019 KILT snapshot is the closest standard corpus. Real disagreements surface as "natural" gaps and are audited.

---

## 7. References

* Cao et al. KQA Pro. ACL 2022. Official KoPL engine: `pip install KoPL`.
* Petroni et al. KILT. NAACL 2021.
* Elsahar et al. T-REx. LREC 2018.
* Xu et al. Generate-on-Graph (IKGQA). EMNLP 2024.
* Kang, Fu, Zhao. When Correct Edges Cannot Be Verified. arXiv:2606.15833, 2026.
* Zhang et al. CAGED. CIKM 2022.
* Liu et al. CCA. AAAI 2024.
* Mallen et al. PopQA. ACL 2023.
* Thorne et al. FEVER. NAACL 2018.
* Cohen et al. RippleEdits. TACL 2024.
* Zhang et al. Who&When. ICML 2025.
* Huang et al. R-Zero. ICLR 2026.
* Liu et al. SPICE. 2025.
* Miller. Adding Error Bars to Evals. 2024.
* Qwen3.5-9B model card. 2026.

---

# KG–Agent Co-evolution, Project 1: Experiments 1 and 2

Code for the first two experiments of Project 1 ("Joint evolution of a KG and a clinical agent"),
run in a controlled sandbox built on the **KQA Pro** knowledge base. The KQA Pro KB plays the role of
the scoring KG, Wikipedia (KILT snapshot) plays the role of the literature, and the backbone model is
**Qwen3.5-9B** served with vLLM.

* **Exp 1 (Challenger).** When the KG has defects, how many KG-generated tasks have wrong answer
  keys? Can documents help the Challenger find the defects?
* **Exp 2 (Curator).** After a Solver failure, can the Curator tell a missing fact, a wrong fact and
  a non-KG error apart, and repair the KG from documents without poisoning it?

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
| Defects → Gw | Sampled from S at rates 10/20/30% (dose-response), deletions:corruptions = 1:1; corruptions are *similar* (type-consistent) or *random* (50/50); both copies of a relation (forward and backward) edited together; self-check on the engine | KG error-detection protocol (CKRL/CAGED); CCA shows similar noise is the hard case |
| Paths | Sampled on Gw, compiled to KoPL by a deterministic compiler, unique answer on Gw verified by execution; 1-hop and 2-hop, attributes, relations and qualifiers | LLM program-writing errors cannot be mistaken for KG-induced errors |

### 1.2 Exp 1: conditions and modes

| Condition | The Challenger sees | Mode A (path → task) | Mode B (entity → gap report) |
|---|---|---|---|
| **B0** | nothing (no LLM; template question, Gw answer) | ✓ exact contamination baseline | – |
| **C0** | entity name only (closed-book probe of every S fact) | – | ✓ what memory alone recovers |
| **C1** | Gw | ✓ | ✓ |
| **C2** | Gw + BM25 passages | ✓ (main) | ✓ (main) |
| **C2link** | as C2, with gold KG ids after linked mentions | ✓ (full config) | ✓ (full config) |
| **C3** | Gw + G\* (oracle) | ✓ upper bound | ✓ upper bound |

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

* H1: C1 ≈ B0, and B0 contamination rises with the defect rate.
* H2: C2 < C1 on per-path contamination (paired).
* H3: Mode B recall C2 > C1/C0, with precision above a preset threshold.
* H4: C2link closes most of the C2–C3 gap.
* H5: recall is lower for similar corruptions and tail entities.

### 1.3 Exp 2: cases, flow and gate

| Class | Construction (one defect per case) | Correct behaviour |
|---|---|---|
| missing_fact | supported gold-path fact deleted | locate, re-add from text |
| wrong_fact | supported gold-path fact corrupted (similar) | locate, restore the value |
| non_kg | Solver stably wrong on intact G\*, matched to KG cases on program features | no edit |
| non_kg_offpath | stably wrong question + a defect on the same entities but off the path | no edit |
| invalid_task | Exp 1 task whose (valid) key is contaminated and that the Solver contradicts | flag the task, never edit the KG to fit the key |
| refer | unsupported gold-path fact deleted/corrupted (no text settles it) | refer to a human, no commit |

* **Pool.** KQA Pro train/val questions anchored on region B whose official program is traceable on G\* and
  whose engine answer equals the gold answer.
* **Stable labels.** Labels come from k=4 Solver samples: stably correct means ≥3/4, stably wrong means
  ≤1/4. A KG case is kept only if the defect makes the Solver fail stably.
* **Curator.** Input: question, answer key (gold, or the Challenger's key for the pipeline variant), Solver
  trajectory, live KG facts and BM25 passages. Output: diagnosis, located fact and a single-fact edit.
* **Gate (three-way).** An edit is committed only if all three hold: it cites an evidence item that was shown;
  an independent verifier says that item entails the new fact; the Solver succeeds in a sandbox re-run on the
  patched KG. Deletions are referred, not committed. Edits that pass the re-run but lack support are counted
  as reward-hacking candidates.
* **Metrics.**
  * Diagnosis: 3-way accuracy and macro-F1 (case-level bootstrap), KG vs non-KG precision and recall.
  * Localisation accuracy (step-level, as in Who&When).
  * Exact repair rate, separately for deletions and corruptions.
  * Committed edits consistent with G\*.
  * Commits on no-edit classes; KG poisoning on invalid_task; refer behaviour.
  * **Locality** (regressions among previously correct neighbour questions) and **portability** (questions that
    depend on the repaired fact become correct), computed exactly with gold KQA Pro programs; Solver-level
    locality on a subset.
* **Ablations:** no trajectory, no sandbox, no documents, oracle (G\* facts).
* **Baselines:** execution-signal rule, always wrong_fact, and a surface-feature logistic regression. The
  regression is a shortcut check: an AUC far above 0.5 means the case set leaks the label.

### 1.4 Statistics and reporting

* Proportions are reported with Wilson 95% CIs.
* Means use cluster bootstrap over anchor entities (Miller 2024, *Adding Error Bars to Evals*).
* Conditions are compared on paired items: paired cluster bootstrap plus exact McNemar, Holm-corrected over H1–H5.
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

### Colab, one A100 (80 GB recommended)

```bash
pip install -e . && pip install vllm                    # a vLLM release that supports Qwen3.5
bash scripts/download_data.sh data                     # official KQA Pro release -> data/kqapro
nohup bash scripts/serve_vllm.sh > vllm.log 2>&1 &     # A100 40GB: MAX_SEQS=32 bash scripts/serve_vllm.sh
bash scripts/wait_for_server.sh

# pilot (about 20 min): small numbers, separate work dir
bash scripts/run_small.sh paths.work_dir=runs/pilot paths_sampling.n=20 exp1.mode_b.n_entities=10 \
     exp1.solver.n_per_condition=10 exp2.pool_size=100

# main 2-day run; keep results on Drive so a disconnect loses nothing
bash scripts/run_small.sh paths.work_dir=/content/drive/MyDrive/kgcoevo/runs/small
```

Each stage can also be run on its own, for example:

```bash
python -m experiments.exp1.run --config configs/small.yaml --stages mode_a
```

All stages are resumable: re-running a command skips items that are already in its JSONL output.

**Judge model.** By default `llm.judge` uses the same endpoint at temperature 0. A different model family
avoids self-preference. To use one, point `llm.judge.base_url/model/api_key` at it and set
`llm.judge.vllm_extras=false` for hosted APIs.

### Minimal Exp 1 only (`configs/exp1_min.yaml`)

Runs C1 (KG), C2 (KG + documents) and C3 (KG + reference KG), plus B0, which needs no GPU, at one
defect rate, one seed, 200 paths and 100 entities. Exp 2 and the closed-book probe are not run.
Estimated LLM time is about 1.2 h on an A100 80GB; plan for about 3 h including model loading and the pilot.

```bash
# Step 1: data preparation, CPU only. A CPU runtime is enough, so no GPU compute units are used.
#         Streams KILT once, takes about 30-60 min. Write to Drive so step 2 can reuse it.
bash scripts/run_exp1_min.sh prepare paths.work_dir=/content/drive/MyDrive/kgcoevo/exp1_min \
     paths.kilt_pages=/content/drive/MyDrive/kgcoevo/kilt/kb_pages.jsonl \
     paths.kqapro_dir=/content/drive/MyDrive/kgcoevo/kqapro
# Step 2: switch to an A100 runtime, start vLLM, then
bash scripts/run_exp1_min.sh run paths.work_dir=/content/drive/MyDrive/kgcoevo/exp1_min \
     paths.kilt_pages=/content/drive/MyDrive/kgcoevo/kilt/kb_pages.jsonl \
     paths.kqapro_dir=/content/drive/MyDrive/kgcoevo/kqapro
```

**Colab notes.**

* The official FAQ caps free notebooks at 12 h and Pro+ at 24 h of continuous execution. Runtimes can end
  earlier when idle or when compute units run out, and files on the VM are lost. Keep `work_dir` on Drive;
  every stage resumes where it stopped.
* An A100 runtime consumes compute units from the moment it is connected. Run `prepare` on a CPU runtime and
  stop the GPU runtime as soon as the run finishes.

### Two-day plan (`configs/two_day.yaml`): minimal Exp 1 + reduced Exp 2

Both experiments share one work dir, because Exp 2 uses Exp 1 tasks for its invalid_task cases.
Exp 2's pool does not depend on Exp 1, so it runs at the same time against the same vLLM server.

```bash
W="paths.work_dir=/content/drive/MyDrive/kgcoevo/two_day"
bash scripts/run_two_day.sh prepare $W                 # CPU, ~30-60 min (KILT streaming)
bash scripts/run_two_day.sh exp1 $W &                  # ~1.2 GPU-h
bash scripts/run_two_day.sh pool $W; wait              # ~3 GPU-h, in parallel with exp1
bash scripts/run_two_day.sh exp2 $W                    # ~4.5 GPU-h: cases, Curator, locality, analysis
```

### Configs

| File | Use |
|---|---|
| `configs/two_day.yaml` | minimal Exp 1 + reduced Exp 2 (targets 100/100/100/50/50/50, ablations full/no_sandbox/no_docs) |
| `configs/exp1_min.yaml` | Exp 1 only, C1/C2/C3 (+ free B0), one rate and seed, about 1.2 GPU-h |
| `configs/small.yaml` | 2-day plan: 1 defect seed, B0/C1/C2/C3, Solver k=2, smaller Exp 2 |
| `configs/full.yaml` | full design: 3 seeds, + C2link, Solver k=4, larger audits |
| `configs/base.yaml` | all defaults with comments |

Override anything from the command line with `--set key.sub=value`.

---

## 3. Outputs

```
<work_dir>/
  config.resolved.yaml, manifest.jsonl
  data/   region.json, passages.jsonl, support.jsonl, support_summary.json, probe_items.jsonl
          gw/rate30_seed0/{kb.json, defects.jsonl, selfcheck.json}    paths/rate30_seed0.jsonl
  exp1/   probe, mode_a, mode_b, gap_tasks, tasks (with E0-E5), judge, solver  (.jsonl)
  exp2/   pool, pool_solver, case_validation, cases, curator, locality_solver  (.jsonl)
  audit/  support_audit.csv, e3_audit.csv (+ key), natural_gaps_audit.csv
  results/ exp1_report.md, exp1_summary.json, exp1_mode_a_items.csv,
           exp2_report.md, exp2_summary.json, exp2_runs.csv
```

**Human steps.**

1. Fill in `audit/support_audit.csv` and check that S precision is ≥ 95% before the main run.
2. After Exp 1, two annotators fill in `audit/e3_audit.csv`. Save the filled sheet as `audit/e3_audit_labels.csv`;
   `experiments.exp1.analyze` then reports κ and the judge's accuracy.

---

## 4. Compute (rough estimates for `configs/small.yaml`)

These are planning numbers, not measurements. They assume 32–64 concurrent requests on vLLM, about 1,800
output tokens/s aggregate on an A100 80GB (about 1,000 on 40GB), and per-call token counts guessed before
the pilot. Re-estimate from `usage_last_run.jsonl` after the pilot.

| Stage | Calls (approx.) | A100 80GB hours |
|---|---|---|
| Exp 1 probe + Mode A + Mode B + gap tasks + judge | ~10k short/medium calls | ~1.7 |
| Exp 1 Solver evaluation | ~1.6k KG solves + 0.8k closed-book | ~1.3 |
| Exp 2 pool (1,000 questions × 4) | ~4k solves | ~2.9 |
| Exp 2 case validation | ~2.8k solves | ~2.0 |
| Exp 2 Curator (+ verifier + sandbox) | ~1.3k cases | ~1.7 |
| Exp 2 Solver-level locality | ~1.2k solves | ~0.9 |
| **Total** | | **~10 (≈18 on 40GB)** |

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

## 中文简介

本仓库实现 Project 1 的实验 1（Challenger：KG 有缺陷时出题的答案键污染率，以及能否借助文档发现缺陷）
和实验 2（Curator：失败归因与基于文档的 KG 修复，含三向 gate、locality 和 portability）。

* 答案、检查和评分全部通过官方 KoPL 引擎在 G\* 和 Gw 上执行程序得到。只有题干忠实性这类执行无法判断的
  部分，才用 LLM 裁判，并配合人工审核。
* 两天方案用 `configs/small.yaml`，先跑 pilot，再跑主实验。
* 所有阶段都可续跑，适合在 Colab 上使用。

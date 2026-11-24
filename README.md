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
where execution cannot decide, such as whether a question faithfully expresses a program. Human audit
sheets for those are exported but optional.

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
| S (document-supported facts) | T-REx-style alignment: exact dates, numbers and strings; years and relations only together with a relation cue word; optional human audit of 50 facts | Every injected defect is discoverable from text in principle |
| Defects → Gw | A copy of G\* with 30% of the S facts of region A deleted or corrupted (1:1); corruptions are *similar* (type-consistent) or *random* (50/50); both copies of a relation (forward and backward) edited together; self-check on the engine. The defect log (`defects.jsonl`) records each edit and is the ground truth | KG error-detection protocol (CKRL/CAGED); CCA shows similar noise is the hard case |
| Paths | Directed sampling on Gw, compiled to KoPL by a deterministic compiler: 100 *defective* paths (use a corrupted fact; the G\* answer differs from the Gw answer) and 100 *clean* paths (no fact changed, first hop in S, same answer on Gw and G\*), with the same path-type mix; 1-hop and 2-hop, attributes, relations and qualifiers | Fixed counts in both groups; LLM program-writing errors cannot be mistaken for KG-induced errors |

### 1.2 Exp 1: conditions and modes

The question: when Gw has errors, can the Challenger find them from Gw plus documents, and how many
generated tasks carry a wrong answer key? B0 is a free no-LLM reference line.

| Condition | The Challenger sees | Mode A (path → task) | Mode B (entity → gap report) |
|---|---|---|---|
| **B0** | nothing (no LLM; template question, Gw answer) | ✓ | – |
| **C1** | Gw (KG only) | ✓ | ✓ |
| **C1know** | Gw, and it may use its own background knowledge | ✓ | ✓ |
| **C2** | Gw + documents: the S passage that states each fact (gold) is always shown, mixed with distractors | ✓ (main) | ✓ (main) |
| **C3** | Gw + G\* (oracle) | ✓ upper bound | ✓ upper bound |
| C0 *(optional)* | entity name only (closed-book probe of every S fact) | – | ✓ what memory alone recovers |

* **Input.** One prompt per path or entity, no tools: evidence is pre-retrieved by a fixed procedure. Every
  condition sees the same working-KG context (all facts of the entities on the path, or of the entity). Only
  C1know may use background knowledge; the other prompts forbid it.
* **C2 documents.** Mode A: per path fact, the gold passage(s) plus BM25 distractors from the same pages,
  3 passages per fact (facts outside S get 3 BM25 passages). Mode B: all S passages of the entity plus 4 other
  passages of its page. Gold passages are looked up in the same way for defective and clean facts (a corrupted
  fact gets the passage of the fact it replaced) and passages are listed in page order, so which passages
  appear does not reveal where the defects are.
* **Why S.** Defects are injected only into facts that the documents state. A miss is then the Challenger's
  failure, not missing document coverage, and clean and defective paths are both text-supported, so false
  alarms are not caused by facts the documents never mention.
* **Decoding.** The Challenger decodes greedily (temperature 0), one decision per path or entity.

**Mode A.** All conditions get the same 200 paths. For each path the Challenger *accepts* it (writes a question;
the key is the Gw answer), *corrects* it (a path fact contradicts the evidence; the key is the corrected value),
or *rejects* it. Reported as counts, at the decision level (independent of the question wording):

* Defective paths: accepted (defect passed into the task), corrected to the right / a wrong value, rejected; caught = reject + correct.
* Clean paths: kept, falsely corrected, falsely rejected.
* Emitted tasks (accept + correct) with a wrong key, by cause: *defect passed*, *failed fix*, *introduced*
  (the key of a clean path was changed); corrections whose value appears in the evidence shown (grounded).
* Strata of the catch rate: hops, similar vs random corruption, subtype, entity popularity (head/torso/tail),
  and known/unknown to the closed-book probe if C0 was run.

Each emitted task also goes through the checks:

| Check | Decided by | Meaning |
|---|---|---|
| E0 format | program | JSON parses, KoPL program well formed |
| E1 executable | KoPL engine | runs on Gw (on G\* for gap tasks) and, for Mode A, returns an answer |
| E2 bookkeeping | KoPL engine | accepted tasks: the key equals the program output on Gw (no copy error) |
| E3 faithful | rules + LLM judge | anchor named, no bridge entity or answer leaked; the judge checks that the question expresses the program |
| E4 unique | KoPL engine | exactly one answer on G\* (gap tasks: also none) |
| **E5 wrong key** | KoPL engine | passes E0–E4 but the key differs from G\*; split by cause as above |

**Mode B.** For 100 entities the Challenger reports gaps (missing or conflicting facts). Each claim is scored
against the defect log: a *hit* (key and true value of an injected defect) or an error; errors on the key of a
defect with a wrong value are counted separately as *located-only*. Precision = hits / claims, recall =
detected defects / defects, label accuracy = detected defects with the right label (missing for deletions,
conflict for corruptions) / detected defects. Real gaps of the original KB count as errors (no human audit).
Recall is broken down by deleted vs corrupted, similar vs random and entity popularity.

**Gap tasks.** The first resolvable claim of each entity is compiled into a 2-hop task whose key is the claimed
value. A claim whose fact does not exist in G\* is counted as a wrong key (the Challenger's error), not dropped.

**Task quality.** The Solver answers 40 valid tasks per condition and source (Mode A / gap) 8 times each, on Gw,
on G\* and closed-book. The report gives pass rates against the task key and against G\*, the difficulty of tasks
with a correct key (target: 3–5 of 8 correct on Gw), gap dependence (fails on Gw, succeeds on G\*), closed-book
leakage, and tasks with a wrong key on which the Solver on Gw agrees with the key: there the reward would
confirm the wrong fact and the error stays hidden.

**Expected outcomes** (stated before the main run; counts only, statistical tests to be added later):

* B0 and C1 pass most defects; C2 catches more defects than C1 with few false alarms on clean paths; C3 bounds both.
* C1know shows what the model's own knowledge adds without documents, mostly for popular (head) entities.
* Mode B: C2 recall > C1 recall at useful precision; similar corruptions and tail entities are harder.

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

* **Exp 1 reports counts only** (k/n and %); confidence intervals and paired tests are to be added later.
* Exp 2: proportions are reported with Wilson 95% CIs.
* Means use cluster bootstrap over anchor entities (Miller 2024, *Adding Error Bars to Evals*).
* Conditions are compared on paired items: paired cluster bootstrap plus exact McNemar, Holm-corrected over the pre-registered hypotheses.
* Human audits are optional (two annotators, Cohen's κ, the judge's accuracy against the human majority).
* Every run writes `config.resolved.yaml` and `manifest.jsonl` (package versions, git commit). Commit and tag the
  resolved config before the main run; it is the pre-registration.

---

## 2. Quick start

```bash
git clone https://github.com/kyle050316/KG-agent-coevolve-project1.git
cd KG-agent-coevolve-project1
pip install -e ".[dev]"
pytest -q          # 30 tests, incl. an end-to-end run of every stage on a tiny KB with a scripted LLM
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
After the pilot, check the parse rates, the path counts printed by `prepare` (`[paths] defective=… clean=…`;
if there are fewer defective paths than requested, raise `paths_sampling.max_per_defect` or the defect rate)
and the case counts printed by `build_cases` (how many KG cases are visible vs silent) before the main run.

**Judge model.** `llm.judge` uses the same endpoint (the same 9B model) at temperature 0 and judges every
task, so it may favour its own questions. If a second model becomes available, point
`llm.judge.base_url/model/api_key` at it (`llm.judge.vllm_extras=false` for hosted APIs).

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
| `configs/extended.yaml` | optional: C0 probe, more paths and Mode B entities, no_docs ablation, 2 Curator seeds |

Override anything from the command line with `key.sub=value` after the step (or `--set key.sub=value`).

---

## 3. Outputs

```
<work_dir>/
  config.resolved.yaml, manifest.jsonl
  data/   region.json, passages.jsonl, support.jsonl, support_summary.json, probe_items.jsonl
          gw/rate30_seed0/{kb.json, defects.jsonl, selfcheck.json}    paths/rate30_seed0{.jsonl, _stats.json}
  exp1/   probe, mode_a, mode_b, gap_tasks, tasks (with E0-E5), judge, solver  (.jsonl)
  exp2/   pool, pool_solver, case_solver, cases, curator, locality_solver  (.jsonl)
  audit/  support_audit.csv, e3_audit.csv (+ key)            (optional human audits)
  results/ exp1_report.md, exp1_summary.json, exp1_mode_a_items.csv,
           exp2_report.md, exp2_summary.json, exp2_runs.csv
```

**Optional human steps.** Nothing in the pipeline requires them; without them S precision and the judge are unaudited.

1. Fill in `audit/support_audit.csv` to check S precision (target ≥ 95%).
2. Two annotators fill in `audit/e3_audit.csv`. Save the filled sheet as `audit/e3_audit_labels.csv`;
   `experiments.exp1.analyze` then reports κ and the judge's accuracy.

---

## 4. Compute (rough estimates for `configs/main.yaml`)

These are planning numbers, not measurements. They assume 32–64 concurrent requests on vLLM with prefix
caching on one A100 80GB, and per-call token counts guessed before the pilot. Re-estimate from
`usage_last_run.jsonl` after the pilot; an H100 is roughly 1.5–2× faster.

| Stage | Calls (approx.) | A100 80GB hours |
|---|---|---|
| Exp 1 Mode A (C1/C1know/C2/C3 × 200 paths), Mode B (100 entities × 4), gap tasks, judge (all tasks) | ~3k | ~0.5–1 |
| Exp 1 Solver evaluation (9 groups × 40 tasks × 8 samples × Gw / G\* / closed-book) | ~8.6k solves | ~2–5 |
| Exp 2 pool (1,000 questions × 4 Solver samples) | ~4k solves | ~1–3 |
| Exp 2 KG cases (200 × 4 Solver samples) | ~800 solves | ~0.3–0.6 |
| Exp 2 Curator (2 turns + sandbox answer + verifier; no_tool on 100 cases) | ~1.5k | ~0.5–1 |
| Exp 2 Solver-level locality (20 edits × 30 questions × 2) | ~1.2k solves | ~0.5–0.9 |
| **Total** | | **~6–12** |

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
* **Oracle retrieval in C2.** The gold passage is always shown (with distractors), so C2 measures reading and
  judgement, not retrieval. A retrieval-only variant can be added back later.
* **Same-model judge, no human audit.** E3 is judged by the same 9B model, and S precision and the judge are
  not audited by humans unless the optional sheets are filled in.
* **Mode A covers corruptions only.** A deleted fact cannot lie on a path sampled from Gw; deletions are
  measured in Mode B.
* **Restricted traceability.** Exp 2 uses the traceable KoPL subset (chain programs). Questions with set
  operations, filters or aggregation are excluded because their gold path is not well defined.
* **Single-fact edits without qualifiers.** The Curator adds or updates one attr/rel fact; defects are drawn
  only from facts that such an edit can restore.
* **Biased S.** S only contains facts that Wikipedia states explicitly, so it is a biased subset of the KB
  (Kang et al. 2026). `support_summary.json` reports its composition; conclusions apply to text-supported facts.
* **Unverified KQA Pro snapshot date.** The KQA Pro paper does not state its Wikidata snapshot date; the
  2019 KILT snapshot is the closest standard corpus. Real disagreements between the two show up as gap claims that are not injected defects; they are counted as errors.

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

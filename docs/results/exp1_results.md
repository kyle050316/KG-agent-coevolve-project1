# Exp 1 results (2026-11-24)

Full generated reports: [seed 0](exp1_report_seed0.md) (main run, with the C0 probe) and
[seed 1](exp1_report_seed1.md) (replication with a second defect sample). Counts only; statistical
tests are to be added later.

## What was run

* **Compute.** One Colab A100-SXM4-40GB (driven with the `colab` CLI), vLLM 0.34.0 serving
  Qwen3.5-9B (bf16, thinking off). The whole Exp 1 run (prepare + every LLM stage) takes about 25 min;
  the session used about 13 compute units in total, including setup, two pilots and the replication.
* **Data.** KQA Pro KB (16,960 entities; the Tsinghua link is dead, the files come from the Hugging Face
  mirror `drt/kqa_pro`), KILT 2019 pages for 16,748 KB entities. 3,735 humans qualify; region A = 200,
  region B = 200. Facts of A and B: 9,307; text-supported (S): 2,195.
* **Defects.** 30% of the eligible S facts of region A: 233 defects (116 deletions, 117 corruptions:
  66 similar, 51 random), 0 self-check failures, for each of the two seeds.
* **Mode A.** 100 defective paths (a corrupted fact, G\* answer differs from Gw) and 100 clean paths
  (no changed fact, first hop in S, same answer), same type mix: 54 attr, 11 rel, 27 rel→attr, 8 rel→rel.
* **Mode B.** 100 entities (127 defects for seed 0, 124 for seed 1). **Solver.** 40 valid tasks per
  condition and source, 8 samples each on Gw, G\* and closed-book (about 13.8k Solver calls).
* Code: branch `exp1-directed-design` (commit `ce848db` for the analysis).

## Fixes found on real data (all in the branch)

| Problem | Effect | Fix |
|---|---|---|
| Duplicate relations (same subject/key/object, different qualifiers) and qualifier edits | 15/70 pilot defects invisible in Gw; main run crashed (`qualifier parent not found`) | defects only on attr/rel facts that one edit makes visible |
| Paths that pick one of several values with FilterConcept ("educated at" two schools) | ambiguous questions; most false fixes on clean paths | every Relate step must reach one entity |
| Long `rationale` field ran into max_tokens | 4 truncated Mode A replies → invalid | rationale removed; top-level fields recovered from cut JSON |
| Numeric / missing inputs in Solver programs | crash in `describe_program` | handled |
| "correct" decisions that keep the Gw answer (model flags a fact but keeps the key) | caught rate inflated | analysis counts by the emitted key: kept / fixed / rejected |

## Mode A: can the Challenger stop defects from becoming wrong answer keys?

Decision level, 100 defective + 100 clean paths, seed 0 (seed 1 in brackets).
*Caught* = rejected or key changed; *false alarm* = rejected or key changed on a clean path.

| | B0 | C1 (KG) | C1know (KG + memory) | C2 (KG + docs) | C3 (KG + G\*) |
|---|---|---|---|---|---|
| defective: caught | 0 (0) | 63 (61) | 62 (61) | **93 (92)** | 82 (73) |
| defective: fixed to the right value | 0 (0) | 14 (13) | 20 (18) | **62 (54)** | 66 (66) |
| defective: flagged but key kept | 0 (0) | 22 (27) | 34 (36) | 7 (8) | 18 (27) |
| clean: false alarm | 0 (0) | 35 (44) | 27 (25) | 14 (20) | 3 (5) |
| emitted tasks with a wrong key | 50% (50%) | 48% (55%) | 51% (52%) | **22% (26%)** | 20% (20%) |

Fixed to the right value, seed 0, by stratum:

| | C1 | C1know | C2 | C3 |
|---|---|---|---|---|
| 1-hop (65) | 12 | 18 | **56** | 65 |
| 2-hop (35) | 2 | 2 | 6 | 1 |
| head / torso / tail entity (42 / 31 / 27) | 11 / 3 / 0 | 14 / 5 / 1 | 25 / 18 / 19 | 27 / 18 / 21 |
| similar / random corruption (53 / 47) | 9 / 5 | 12 / 8 | 33 / 29 | 37 / 29 |

Caught on defective paths by whether the model knows the true value closed-book (C0 probe, seed 0):
C1know 21/24 known vs 41/76 unknown; C2 22/24 vs 71/76.

## Mode B: can the Challenger find the defects of an entity?

| | C1 | C1know | C2 | C3 |
|---|---|---|---|---|
| recall, seed 0 (seed 1) | 1% (4%) | 10% (12%) | **38% (41%)** | 73% (87%) |
| precision | 4% (12%) | 8% (7%) | 16% (14%) | 89% (96%) |
| label accuracy (missing / conflict) | 1/1 | 92% | 98% | 96% |
| C2 recall: deleted / corrupted | | | 24% / 52% (34% / 48%) | |

Precision counts every claim that is not an injected defect as an error, including real gaps of the
original KB (there is no human audit), so it is a lower bound; C2 makes 3-4 claims per entity.
The closed-book probe recalls the true value of 16% of the corrupted and 30% of the deleted facts.

## Task quality (Solver, 8 samples per task)

* **Hidden contamination.** On Mode A tasks with a wrong key, the Solver on Gw returns that same wrong
  key in ≥ 6/8 samples for 16/22 B0 tasks (seed 1: 9/16): a training reward would confirm the wrong fact.
* **Difficulty is bimodal.** Tasks from clean paths are mostly solved 8/8 on Gw (62-85% of tasks);
  C2/C3 tasks from corrected defective paths (right key) and gap tasks are mostly 0/8 on Gw (71-90%),
  because Gw still holds the wrong or missing fact (gap-dependent: G\* ≥ 6/8, Gw ≤ 2/8). The 3-5/8
  target band holds ≤ 11% of the tasks in every group with at least 10 tasks.
* The closed-book pass rate on clean tasks is 15-33%.

## Findings

1. Without outside evidence, defects pass into tasks: B0 emits a wrong key for every defective path,
   and C1/C1know still emit wrong keys for about half of the tasks. C1 catches random corruptions from
   inconsistencies in the KG context more often than similar ones (74% vs 51-53%, both seeds), but it
   cannot recover the right value (13-14%) and raises the most false alarms on clean paths (35-44%).
2. Documents work for 1-hop facts: C2 fixes 86% of them and halves the share of wrong keys (22-26% vs
   about 50%). Unlike the model's own knowledge, it does not depend on popularity (tail entities: C2 19/27,
   C1know 1/27; C1know catches 88% of defects it knows closed-book but 54% of the rest).
3. 2-hop defects are found but not repaired: when the bridge entity is wrong, the evidence does not give
   the final value, and the model keeps the key instead of rejecting (C3: 18/35 flagged but kept). These
   are most of C2's and C3's remaining wrong keys.
4. Gap discovery from documents (Mode B) is the harder problem: C2 recall 38-41%, deletions harder than
   corruptions; even with the reference KG (C3) recall is 73-87%.
5. Path-based tasks are either easy or impossible for a KG Solver; corrected tasks become solvable only
   after the KG is repaired (the link to Exp 2).

## Limitations

* One model (Qwen3.5-9B) as Challenger, judge and Solver; no human audit of S or of the judge.
* C2 always shows the gold passage (oracle retrieval): it measures reading, not retrieval.
* Defects only on attr/rel facts that one edit changes; Mode A covers corruptions only.
* Counts from 100 + 100 paths and two defect seeds; no confidence intervals yet.

## Reproduce

```bash
CFG=configs/pilot.yaml bash scripts/run.sh all paths.kqapro_dir=... paths.kilt_pages=...   # pilot
bash scripts/run.sh prepare ... && bash scripts/run.sh exp1 ...                             # main (seed 0)
bash scripts/run.sh exp1 ... defects.seeds=[1] paths.work_dir=runs/main_s1                 # replication
```
or `notebooks/colab_exp1.ipynb` on Colab.

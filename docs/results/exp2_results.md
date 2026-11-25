# Exp 2 results (2026-11-24)

Full generated report: [exp2_report.md](exp2_report.md) (Wilson 95% CIs in brackets there; counts here).
Code: branch `exp1-directed-design`, commits `df02f7d`, `5094fb3`, `268c580`, `6496adb` (analysis section
"Repair funnel" added after the run and re-run locally on the downloaded outputs).

## What was run

* **Compute.** One Colab A100-SXM4-40GB, vLLM serving Qwen3.5-9B (bf16, thinking off) as Solver, Curator
  (greedy) and verifier. About 52 min on the GPU (setup, three pilot passes, main run), 6.9 compute units.
* **Data.** Region B enlarged to 1,000 entities (`configs/exp2.yaml`; region A and the first 200 B entities
  as in Exp 1). Passages: 581,141 from 6,227 pages; S: 6,619 of 29,254 facts. 3,524 traceable KQA Pro
  questions on B, 524 of them can carry a defect; the pool holds those 524 plus 976 random ones (k=4 Solver
  samples each on G\*).
* **Cases (385).**

  | source | class / subtype | n |
  |---|---|---|
  | KQA Pro | missing_fact: visible / silent / mixed | 69 / 28 / 3 |
  | KQA Pro | wrong_fact: visible / silent | 70 / 30 |
  | KQA Pro | non_kg: wrong / ungrounded | 50 / 50 |
  | Exp 1 Challenger tasks | bad_key (KG right, key changed to a wrong value) | 25 |
  | Exp 1 Challenger tasks | wrong_fact, key also wrong / key right (control) | 30 / 30 |

* **Curator** (full: diagnose → sandbox re-run → commit/revise/withdraw → two-sided source gate) on every
  flagged case; `no_tool` on a stratified subset of 100.

## Pilot fixes (three passes on 51 cases)

| Problem | Fix |
|---|---|
| Citations given as an entity id (`Q123` for `Q123:4:0`) counted as uncited | a citation that matches exactly one shown passage is resolved to it |
| bad_key chosen when the KG had no answer, when the KG answer equalled the key, and without any passage (from memory) | the prompt says whether the KG answer matches the key; bad_key needs a differing KG value and a cited passage that states it |

bad_key on non-bad_key cases: 8 → 8 → 3 of 34 pilot runs; admitted edits on non-KG / bad_key cases: 0 in all passes.

## Safety: does the Curator damage the KG?

| | result |
|---|---|
| admitted edits on intact-KG cases (non_kg 100 + bad_key 25) | **0 / 125** |
| admitted KQA Pro edits that are true in G\* | 42 / 44 |
| neighbour questions broken by admitted edits (gold programs, exact) | 0 / 692 |
| Solver-level regressions on neighbour questions | 6 / 160 (program level is 0, so these are Solver sampling noise) |
| admitted edits that write the Challenger's wrong key into the KG | 1 / 51 flagged runs with a wrong key (25 bad_key + 26 key-wrong) |

The one key-writing edit is *Handel, name in native language*: the key "Georg Friedrich Händel" is what the
documents say; the G\* value "George Frideric Handel" is the odd one out (a KQA Pro quirk), so this is not a
real failure. On bad_key cases, 15/25 runs are diagnosed bad_key (all citing a shown passage), 8 as
wrong_fact; of their 5 final edits none passed the gate (2 blocked by the second side: the shown evidence
stated the KG value).

## Repair: how many defects are fixed?

KQA Pro cases, full ablation (T1+T2 view, 251 flagged runs):

| | result |
|---|---|
| diagnosis accuracy (4 labels) / macro-F1 | 72.1% / 71.0 (execution-rule baseline 38.8) |
| KG fault: precision / recall | 114/117 / 114/151 |
| admitted exact repair: missing / wrong | 19/79 (24%) / 11/72 (15%) |
| **end-to-end exact repair over all 200 KG cases** | **30/200 (15%)**, same for T1 and T1+T2; program restore 42/200 (21%) |

Where repairs are lost (KQA Pro, 151 flagged KG runs):

| step | count |
|---|---|
| gold passage (states the defect fact) among the 6 shown | 61 |
| diagnosed a KG fault | 114 |
| final edit | 85 |
| final edit exact | 52 |
| exact and confirmed by the verifier = admitted | 30 |
| repaired when the gold passage is shown / not shown | 23/61 (38%) / 7/90 (8%) |

The verifier rejected 22 of the 52 exact edits, 15 of them relation edits (claim text "X has place of
birth: Y"); dates pass most often.

Challenger KG cases repair less: 5/56 flagged runs (gold passage shown in 26), control 2/30, key-wrong 3/26.

## Triggers and the tool

* **T2 adds flagged cases but no repairs.** T1 flags 139/200 KG cases, T1+T2 151/200; the 12 extra (silent or mixed)
  cases are never repaired. Most silent wrong_fact cases are not on the Solver's path at all (Solver
  grounded 0.93: its program reaches the key another way), so the defect is invisible to any trigger. The
  cost of T2 (50 ungrounded non-KG cases flagged) produced no false edits.
* **The sandbox tool barely matters.** Decisions after the tool: 72 commit, 95 revise, 5 withdraw. Exact first
  edits withdrawn: 2/65; wrong first edits withdrawn or revised to exact: 58/107. Paired full vs no_tool on 50
  KG cases: exact repair 16% vs 14% (1 vs 0 discordant); false edits 0 vs 0.
* **bad_key costs some repairs.** 15 runs on other cases are diagnosed bad_key (13 wrong_fact, 2 non_kg);
  these defects are left in place (no damage, but no repair).

## Findings

1. With the four-label diagnosis, both values side by side and the two-sided gate, the Curator keeps wrong
   Challenger keys out of the KG: no admitted edit on 125 intact-KG cases, one key-writing edit out of 51
   flagged runs with a wrong key (and that key is arguably right). H7 holds on these counts.
2. Repair is low: 15% of all KQA Pro KG defects end-to-end. The main loss is retrieval (the gold passage is
   among the shown evidence in 40% of flagged cases; 38% repaired when it is, 8% when not), then the
   verifier (rejects 42% of exact repairs, mostly relations).
3. H5 is not supported: the grounding trigger T2 finds 12 more defective cases but repairs none; silent
   defects are mostly off the Solver's path.
4. H6 is not supported in this run: the tool changes few outcomes (16% vs 14% repair, no false edits either way).

## Limitations

* One model (Qwen3.5-9B) as Solver, Curator and verifier; one greedy Curator run; no human audit.
* G\* (KQA Pro KB) is treated as ground truth, but some of its values disagree with Wikipedia (e.g. Handel's
  native name); edits towards the documents then count as errors.
* Challenger cases are few (25-30 per kind); ablations use a subset of 100 cases.
* The surface-feature check (AUC 0.88) includes the trigger flags as features, which separate the KQA Pro
  subtypes by construction; it is not a clean shortcut test.

## Next steps (not run)

* Retrieval: query with the located subject and key, and always include the subject's own page.
* Verifier: natural-language claims for relations ("X was born in Y") and entity aliases.
* Check bad_key citations with the verifier, as for edits.

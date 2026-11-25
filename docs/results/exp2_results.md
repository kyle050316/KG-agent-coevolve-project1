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

---

# Curator v2 (2026-11-24, same cases)

Report: [exp2_v2_report.md](exp2_v2_report.md). Config `configs/exp2_v2.yaml`, commit `343d79a`. Same 385
cases and Solver runs as above; only the Curator, locality and analysis stages were re-run (A100, about
22 min, 2.5 compute units).

Changes: the task program is shown step by step on the case KG; single-valued keys are marked (the model
chooses add or update, its output is not rewritten); evidence also comes from the pages of the entities
the task program reaches, queried with the path keys and both candidate values (k = 10); relation claims
for the verifier read "The <key> of <subject> is <object>."; 5 sampled runs per case (temperature 0.7).
The `no_tool` ablation was not re-run. The changes were made together, so their effects are not separated,
except where a funnel step shows them.

## v1 vs v2 (KQA Pro cases, sample 0, T1+T2)

| | v1 (greedy) | v2 (sample 0) |
|---|---|---|
| **end-to-end exact repair (of 200 KG cases)** | 30 (15%) | **66 (33%)** |
| T1 only | 30 | 62 |
| program restore | 42 | 76 |
| gold passage among the shown evidence (of 151 flagged) | 61 | 110 |
| diagnosed a KG fault / final edit / final edit exact | 114 / 85 / 52 | 137 / 109 / 76 |
| repaired when the gold passage is shown / not shown | 38% / 8% | 59% / 2% |
| verifier confirms the cited item / gate rejected an exact repair | 48% / 25% | 75% / 9% |
| exact repair: missing visible / wrong visible / missing silent | 19/69 / 11/70 / 0/8 | 37/69 / 25/70 / 4/8 |
| diagnosis accuracy / KG recall / localisation | 72% / 76% / 74% | 79% / 91% / 87% |
| admitted edits on intact KG (non_kg 100 + bad_key 25) | 0 | 2 (both non_kg) |
| admitted KQA Pro edits true in G\* | 42/44 | 77/87 |
| neighbour questions broken (gold programs) | 0/692 | 3/1815 (from the 2 false edits) |
| admitted edits writing the Challenger's wrong key (of 51) | 1 | 2 |
| bad_key detected (of 25) / bad_key on other cases (of 307) | 15 / 15 | 11 / 12 |
| Challenger KG cases repaired: key wrong (26) / control (30) | 3 / 2 | 6 / 5 |

## Sampling (5 runs per case, aggregated offline)

| aggregation | exact repair (of 200) | edits on intact KG (of 125) | KQA Pro edits true in G\* |
|---|---|---|---|
| sample 0 | 66 | 2 | 77/87 |
| majority of 3 / of 5 | 71 / 72 | 2 / 2 | 84/93 / 86/93 |
| best-of-5 through the gate | 72 | 3 | 87/97 |
| consensus >= 3 of 5 | 66 | 1 | 78/84 |

Exact repair over the KG runs varies little between samples (40.4-43.7%, sd 1.4).

## What the admitted edits that are not true in G\* are (v2, sample 0, 13 edits)

| kind | cases |
|---|---|
| key copied with the arrow of the KG listing (`--spouse--`), so a junk attribute was added (bug) | Heather Locklear, Penelope Wilton |
| right name, wrong entity of that name (Aberdeen, Birmingham, Tehran) | Annie Lennox, Steve Winwood, Abbas Kiarostami |
| year written for a date key | Delmer Daves, Michael Schur |
| wrong key (`member of` for `member of political party`) or wrong value (native name) | Nancy Pelosi, Spike Jonze, Fred Quimby |
| G\* disagrees with the documents | Handel (native name); the two non_kg edits (Debi Mazar's birthplace, USC student count) |

Both "wrong key" writes are not real key-following: Handel's native name (as above), and Glen A. Larson,
where the Challenger's question asks for the city but the program returns its area, so writing "Santa
Monica" restores the G\* fact. Right value but add instead of update: 17 edits (v1: 19), so marking
single-valued keys barely helped.

## Findings (v2)

1. End-to-end repair more than doubles (15% → 33%; 36% with a majority of 5 samples). Most of the gain
   follows the evidence: the gold passage is shown in 110/151 flagged cases (v1: 61), and repair given it
   rises from 38% to 59% (the verifier now confirms 75% of cited items instead of 48%).
2. Safety stays high but is no longer perfect: 2 false edits on 100 non-KG cases (both where G\* and the
   documents disagree), 77/87 admitted edits true in G\*; no wrong Challenger key reached the KG in a way
   that contradicts G\*.
3. Sampling helps a little: +6 repairs with a majority of 5, at no extra false edit; best-of-5 adds one
   false edit; 3-of-5 consensus removes one false edit but also the gain.
4. T2 now adds 4 repairs (silent missing facts 4/8), so H5 holds weakly.
5. The remaining losses: no gold passage (41 cases, 1 repaired), add instead of update (17), entity
   disambiguation and key parsing (5 admitted wrong edits), bad_key under-detected (11/25).

## Next fixes (not run)

* Strip the listing arrows from keys (`--spouse-->` → `spouse`) and parenthesised qualifiers from objects.
* Resolve objects with the hyperlink anchors of the cited passage (gold entity links) instead of the
  first entity of that name.
* Ask for the full value of date keys (YYYY-MM-DD).

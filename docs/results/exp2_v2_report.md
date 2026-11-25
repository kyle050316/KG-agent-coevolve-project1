# Exp 2 report

## Cases and trigger coverage

T1 = Solver answer stably wrong; T2 = Solver KG execution stably does not return the answer key. For KG classes the trigger rate is the recall of the trigger; for non_kg it is the load of false alarms. visible/silent: Solver stably wrong/right despite the defect.

| class | subtype | n | T1 % | T2 % | T1 or T2 % | Solver acc | Solver grounded |
|---|---|---|---|---|---|---|---|
| bad_key | challenger | 25 | 84.0 [65.3, 93.6] (n=25) | 100.0 [86.7, 100.0] (n=25) | 100.0 [86.7, 100.0] (n=25) | 0.15 | 0.00 |
| missing_fact | mixed | 3 | 0.0 [0.0, 56.1] (n=3) | 66.7 [20.8, 93.9] (n=3) | 66.7 [20.8, 93.9] (n=3) | 0.50 | 0.17 |
| missing_fact | silent | 28 | 0.0 [0.0, 12.1] (n=28) | 28.6 [15.3, 47.1] (n=28) | 28.6 [15.3, 47.1] (n=28) | 0.97 | 0.67 |
| missing_fact | visible | 69 | 100.0 [94.7, 100.0] (n=69) | 100.0 [94.7, 100.0] (n=69) | 100.0 [94.7, 100.0] (n=69) | 0.01 | 0.00 |
| non_kg | ungrounded | 50 | 0.0 [0.0, 7.1] (n=50) | 100.0 [92.9, 100.0] (n=50) | 100.0 [92.9, 100.0] (n=50) | 0.95 | 0.05 |
| non_kg | wrong | 50 | 100.0 [92.9, 100.0] (n=50) | 84.0 [71.5, 91.7] (n=50) | 100.0 [92.9, 100.0] (n=50) | 0.05 | 0.17 |
| wrong_fact | challenger_key_right | 30 | 86.7 [70.3, 94.7] (n=30) | 100.0 [88.6, 100.0] (n=30) | 100.0 [88.6, 100.0] (n=30) | 0.12 | 0.00 |
| wrong_fact | challenger_key_wrong | 30 | 80.0 [62.7, 90.5] (n=30) | 86.7 [70.3, 94.7] (n=30) | 86.7 [70.3, 94.7] (n=30) | 0.22 | 0.13 |
| wrong_fact | silent | 30 | 0.0 [0.0, 11.4] (n=30) | 6.7 [1.8, 21.3] (n=30) | 6.7 [1.8, 21.3] (n=30) | 0.98 | 0.93 |
| wrong_fact | visible | 70 | 100.0 [94.8, 100.0] (n=70) | 98.6 [92.3, 99.7] (n=70) | 100.0 [94.8, 100.0] (n=70) | 0.00 | 0.01 |

## Diagnosis and repair (KQA Pro cases, seed 0)

KQA Pro cases only (answer keys are right; Challenger cases have their own section). Ablations other than full run on a stratified subset, so compare them with the paired table below. Repair counts only admitted edits (source gate passed) that restore the G* fact exactly.

| ablation | view | runs | diagnosis acc % | macro-F1 % | KG precision % | KG recall % | localisation % | proposed edit exact % | admitted exact repair, missing % | admitted exact repair, wrong % | false edits on non_kg % | admitted edits true in G* % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full | T1 | 189 | 72.5 [65.7, 78.4] (n=189) | 74.4 [68.0, 80.7] | 95.5 [90.4, 97.9] (n=132) | 90.6 [84.7, 94.5] (n=139) | 88.5 [82.1, 92.8] (n=139) | 55.4 [47.1, 63.4] (n=139) | 53.6 [42.0, 64.9] (n=69) | 35.7 [25.5, 47.4] (n=70) | 4.0 [1.1, 13.5] (n=50) | 90.1 [81.7, 94.9] (n=81) |
| full | T1+T2 | 251 | 78.5 [73.0, 83.1] (n=251) | 78.9 [73.3, 83.7] | 95.8 [91.1, 98.1] (n=143) | 90.7 [85.0, 94.4] (n=151) | 87.4 [81.2, 91.8] (n=151) | 53.6 [45.7, 61.4] (n=151) | 51.9 [41.1, 62.6] (n=79) | 34.7 [24.8, 46.2] (n=72) | 2.0 [0.6, 7.0] (n=100) | 88.5 [80.1, 93.6] (n=87) |

## End-to-end repair over all KG cases (KQA Pro, full)

Denominator: every KQA Pro KG case, including those no trigger flags. Program restore: with the admitted edit, the gold KQA Pro program returns the gold answer again.

| view | flagged % | exact repair % | program restore % |
|---|---|---|---|
| T1 | 69.5 [62.8, 75.5] (n=200) | 31.0 [25.0, 37.7] (n=200) | 36.5 [30.1, 43.4] (n=200) |
| T1+T2 | 75.5 [69.1, 80.9] (n=200) | 33.0 [26.9, 39.8] (n=200) | 38.0 [31.6, 44.9] (n=200) |

## Repair funnel and retrieval (full, KG cases)

Gold passage = a passage that states the defect fact in S. Retrieval is BM25 over the linked entities and their neighbours on the case KG (not oracle, unlike Exp 1 C2).

| source | step | count |
|---|---|---|
| kqapro | flagged runs | 151/151 |
| kqapro | gold passage among the shown evidence | 110/151 |
| kqapro | diagnosed a KG fault | 137/151 |
| kqapro | final edit | 109/151 |
| kqapro | final edit exact | 76/151 |
| kqapro | exact and verified | 66/151 |
| kqapro | exact and admitted | 66/151 |
| kqapro | repaired when the gold passage is shown | 59.1 [49.7, 67.8] (n=110) |
| kqapro | repaired when the gold passage is not shown | 2.4 [0.4, 12.6] (n=41) |
| challenger | flagged runs | 56/56 |
| challenger | gold passage among the shown evidence | 43/56 |
| challenger | diagnosed a KG fault | 52/56 |
| challenger | final edit | 26/56 |
| challenger | final edit exact | 14/56 |
| challenger | exact and verified | 11/56 |
| challenger | exact and admitted | 11/56 |
| challenger | repaired when the gold passage is shown | 23.3 [13.2, 37.7] (n=43) |
| challenger | repaired when the gold passage is not shown | 7.7 [1.4, 33.3] (n=13) |

## By subtype (full, all flagged cases)

| class | subtype | runs | diagnosis correct % | admitted edit % | exact repair % |
|---|---|---|---|---|---|
| bad_key | challenger | 25 | 44.0 [26.7, 62.9] (n=25) | 0.0 [0.0, 13.3] (n=25) | - |
| missing_fact | mixed | 2 | 100.0 [34.2, 100.0] (n=2) | 50.0 [9.5, 90.5] (n=2) | 0.0 [0.0, 65.8] (n=2) |
| missing_fact | silent | 8 | 100.0 [67.6, 100.0] (n=8) | 62.5 [30.6, 86.3] (n=8) | 50.0 [21.5, 78.5] (n=8) |
| missing_fact | visible | 69 | 89.9 [80.5, 95.0] (n=69) | 58.0 [46.2, 68.9] (n=69) | 53.6 [42.0, 64.9] (n=69) |
| non_kg | ungrounded | 50 | 100.0 [92.9, 100.0] (n=50) | 0.0 [0.0, 7.1] (n=50) | - |
| non_kg | wrong | 50 | 70.0 [56.2, 80.9] (n=50) | 4.0 [1.1, 13.5] (n=50) | - |
| wrong_fact | challenger_key_right | 30 | 93.3 [78.7, 98.2] (n=30) | 30.0 [16.7, 47.9] (n=30) | 16.7 [7.3, 33.6] (n=30) |
| wrong_fact | challenger_key_wrong | 26 | 80.8 [62.1, 91.5] (n=26) | 30.8 [16.5, 50.0] (n=26) | 23.1 [11.0, 42.1] (n=26) |
| wrong_fact | silent | 2 | 0.0 [0.0, 65.8] (n=2) | 0.0 [0.0, 65.8] (n=2) | 0.0 [0.0, 65.8] (n=2) |
| wrong_fact | visible | 70 | 57.1 [45.5, 68.1] (n=70) | 55.7 [44.1, 66.8] (n=70) | 35.7 [25.5, 47.4] (n=70) |

## Counterfactual tool (full)

The sandbox re-run is information for the Curator, not a gate: a correct edit need not fix a wrong Solver program.

| quantity | value |
|---|---|
| first-turn edits proposed | 210 |
| decisions (commit / revise / withdraw / invalid) | 107 / 89 / 14 / 0 |
| sandbox: Solver answer fixed after an exact edit % | 68.0 [58.2, 76.5] (n=97) |
| exact first edits withdrawn after the tool % (lower is better) | 2.1 [0.6, 7.2] (n=97) |
| exact first edits kept and admitted % | 79.4 [70.3, 86.2] (n=97) |
| wrong first edits withdrawn or revised to exact % (higher is better) | 54.9 [45.7, 63.7] (n=113) |

## Paired ablations (same cases, exact McNemar)

(no ablations run)

## Source gate (full)

| quantity | value |
|---|---|
| final edits | 142 |
| cite a shown evidence item % | 99.3 [96.1, 99.9] (n=142) |
| verifier confirms the cited item % | 75.2 [67.4, 81.6] (n=141) |
| blocked: the shown evidence states the value the edit replaces % | 1.9 [0.5, 6.6] (n=106) |
| admitted % | 73.2 [65.4, 79.8] (n=142) |
| gate rejected an exact repair % | 9.2 [5.4, 15.0] (n=142) |

## Confusion matrix (full, all flagged cases)

| gold \ predicted | missing_fact | wrong_fact | non_kg | bad_key | invalid |
|---|---|---|---|---|---|
| missing_fact | 72 | 2 | 4 | 0 | 1 |
| wrong_fact | 26 | 89 | 8 | 3 | 2 |
| non_kg | 0 | 6 | 85 | 9 | 0 |
| bad_key | 1 | 11 | 1 | 11 | 1 |

## Cases from Exp 1 Challenger tasks (full)

bad_key: the KG is right and the Challenger changed the key to a wrong value (correct: bad_key, no edit). challenger_key_wrong: the path has a defect and the key is another wrong value (correct: repair to the G* value, not to the key). challenger_key_right: control, the key was fixed to the G* value (correct: repair). 'writes the wrong key' = an admitted edit puts the task's wrong key into the KG; 'blocked' = the two-sided gate found the replaced value stated in the shown evidence.

| class | subtype | cases | flagged % | runs | diagnosis correct % | diagnosed bad_key % | admitted edit % | exact repair % | admitted edit writes the wrong key % | blocked by the gate % |
|---|---|---|---|---|---|---|---|---|---|---|
| bad_key | challenger | 25 | 100.0 [86.7, 100.0] (n=25) | 25 | 44.0 [26.7, 62.9] (n=25) | 44.0 [26.7, 62.9] (n=25) | 0.0 [0.0, 13.3] (n=25) | - | 0.0 [0.0, 13.3] (n=25) | 8.0 [2.2, 25.0] (n=25) |
| wrong_fact | challenger_key_wrong | 30 | 86.7 [70.3, 94.7] (n=30) | 26 | 80.8 [62.1, 91.5] (n=26) | 3.8 [0.7, 18.9] (n=26) | 30.8 [16.5, 50.0] (n=26) | 23.1 [11.0, 42.1] (n=26) | 7.7 [2.1, 24.1] (n=26) | 0.0 [0.0, 12.9] (n=26) |
| wrong_fact | challenger_key_right | 30 | 100.0 [88.6, 100.0] (n=30) | 30 | 93.3 [78.7, 98.2] (n=30) | 0.0 [0.0, 11.4] (n=30) | 30.0 [16.7, 47.9] (n=30) | 16.7 [7.3, 33.6] (n=30) | - | 0.0 [0.0, 11.4] (n=30) |

Seed spread of exact repair over KG runs (full): 43.7, 43.0, 43.7, 41.7, 40.4 (sd 1.4).

## Sampling and aggregation (full, 5 samples per case)

The other tables use sample 0. Here each flagged case gets one decision from its first n samples (see aggregate()). Exact repair is over all KQA Pro KG cases (unflagged ones count as not repaired).

| n | aggregation | exact repair (KQA Pro KG) | admitted edits on intact KG (non_kg + bad_key) | admitted KQA Pro edits true in G* | writes a wrong Challenger key | control repaired | bad_key detected | bad_key on other cases | diagnosis correct (KQA Pro) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | single | 66/200 | 2/125 | 77/87 | 2/51 | 5/30 | 11/25 | 12/307 | 197/251 |
| 3 | single | 66/200 | 2/125 | 77/87 | 2/51 | 5/30 | 11/25 | 12/307 | 197/251 |
| 3 | majority | 71/200 | 2/125 | 84/93 | 2/51 | 9/30 | 10/25 | 13/307 | 197/251 |
| 3 | any | 71/200 | 2/125 | 84/95 | 2/51 | 9/30 | 10/25 | 13/307 | 197/251 |
| 3 | consensus (>= 2/3) | 68/200 | 1/125 | 79/86 | 2/51 | 8/30 | 10/25 | 13/307 | 197/251 |
| 5 | single | 66/200 | 2/125 | 77/87 | 2/51 | 5/30 | 11/25 | 12/307 | 197/251 |
| 5 | majority | 72/200 | 2/125 | 86/93 | 3/51 | 9/30 | 11/25 | 13/307 | 198/251 |
| 5 | any | 72/200 | 3/125 | 87/97 | 3/51 | 9/30 | 11/25 | 13/307 | 198/251 |
| 5 | consensus (>= 3/5) | 66/200 | 1/125 | 78/84 | 2/51 | 8/30 | 11/25 | 13/307 | 198/251 |

## Locality and portability of admitted edits (gold KQA Pro programs, exact)

Regressions among previously correct neighbour questions: 0.2 [0.1, 0.5] (n=1815).  

Portability (questions that use the defective fact and become correct): 41.7 [19.3, 68.0] (n=12).

Solver-level regressions: 2.6 [1.0, 6.4] (n=156).

## Baselines (flagged KQA Pro cases)

| baseline | result |
|---|---|
| execution rule (error/empty -> missing, other answer -> wrong, key returned -> non_kg), macro-F1 % | 38.8 [33.4, 44.2] |
| majority class, macro-F1 % | 19.0 [16.9, 20.9] |
| surface-feature logistic regression, KG vs non-KG AUC (shortcut check) | 0.878 (n=251) |

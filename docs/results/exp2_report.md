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
| full | T1 | 189 | 67.2 [60.2, 73.5] (n=189) | 69.2 [62.2, 75.6] | 97.3 [92.4, 99.1] (n=111) | 77.7 [70.1, 83.8] (n=139) | 77.7 [70.1, 83.8] (n=139) | 38.1 [30.5, 46.4] (n=139) | 27.5 [18.4, 39.0] (n=69) | 15.7 [9.0, 26.0] (n=70) | 0.0 [0.0, 7.1] (n=50) | 95.5 [84.9, 98.7] (n=44) |
| full | T1+T2 | 251 | 72.1 [66.3, 77.3] (n=251) | 71.0 [64.8, 76.5] | 97.4 [92.7, 99.1] (n=117) | 75.5 [68.1, 81.7] (n=151) | 74.2 [66.7, 80.5] (n=151) | 35.8 [28.6, 43.7] (n=151) | 24.1 [16.0, 34.5] (n=79) | 15.3 [8.8, 25.3] (n=72) | 0.0 [0.0, 3.7] (n=100) | 95.5 [84.9, 98.7] (n=44) |
| no_tool | T1 | 47 | 76.6 [62.8, 86.4] (n=47) | 76.7 [61.4, 88.1] | 96.3 [81.7, 99.3] (n=27) | 81.2 [64.7, 91.1] (n=32) | 81.2 [64.7, 91.1] (n=32) | 43.8 [28.2, 60.7] (n=32) | 20.0 [8.1, 41.6] (n=20) | 8.3 [1.5, 35.4] (n=12) | 0.0 [0.0, 20.4] (n=15) | 100.0 [61.0, 100.0] (n=6) |
| no_tool | T1+T2 | 63 | 76.2 [64.4, 85.0] (n=63) | 75.2 [61.6, 86.3] | 96.7 [83.3, 99.4] (n=30) | 76.3 [60.8, 87.0] (n=38) | 73.7 [58.0, 85.0] (n=38) | 39.5 [25.6, 55.3] (n=38) | 16.0 [6.4, 34.7] (n=25) | 7.7 [1.4, 33.3] (n=13) | 0.0 [0.0, 13.3] (n=25) | 100.0 [61.0, 100.0] (n=6) |

## End-to-end repair over all KG cases (KQA Pro, full)

Denominator: every KQA Pro KG case, including those no trigger flags. Program restore: with the admitted edit, the gold KQA Pro program returns the gold answer again.

| view | flagged % | exact repair % | program restore % |
|---|---|---|---|
| T1 | 69.5 [62.8, 75.5] (n=200) | 15.0 [10.7, 20.6] (n=200) | 21.0 [15.9, 27.2] (n=200) |
| T1+T2 | 75.5 [69.1, 80.9] (n=200) | 15.0 [10.7, 20.6] (n=200) | 21.0 [15.9, 27.2] (n=200) |

## Repair funnel and retrieval (full, KG cases)

Gold passage = a passage that states the defect fact in S. Retrieval is BM25 over the linked entities and their neighbours on the case KG (not oracle, unlike Exp 1 C2).

| source | step | count |
|---|---|---|
| kqapro | flagged runs | 151/151 |
| kqapro | gold passage among the shown evidence | 61/151 |
| kqapro | diagnosed a KG fault | 114/151 |
| kqapro | final edit | 85/151 |
| kqapro | final edit exact | 52/151 |
| kqapro | exact and verified | 30/151 |
| kqapro | exact and admitted | 30/151 |
| kqapro | repaired when the gold passage is shown | 37.7 [26.6, 50.3] (n=61) |
| kqapro | repaired when the gold passage is not shown | 7.8 [3.8, 15.2] (n=90) |
| challenger | flagged runs | 56/56 |
| challenger | gold passage among the shown evidence | 26/56 |
| challenger | diagnosed a KG fault | 45/56 |
| challenger | final edit | 21/56 |
| challenger | final edit exact | 11/56 |
| challenger | exact and verified | 5/56 |
| challenger | exact and admitted | 5/56 |
| challenger | repaired when the gold passage is shown | 19.2 [8.5, 37.9] (n=26) |
| challenger | repaired when the gold passage is not shown | 0.0 [0.0, 11.4] (n=30) |

## By subtype (full, all flagged cases)

| class | subtype | runs | diagnosis correct % | admitted edit % | exact repair % |
|---|---|---|---|---|---|
| bad_key | challenger | 25 | 60.0 [40.7, 76.6] (n=25) | 0.0 [0.0, 13.3] (n=25) | - |
| missing_fact | mixed | 2 | 50.0 [9.5, 90.5] (n=2) | 0.0 [0.0, 65.8] (n=2) | 0.0 [0.0, 65.8] (n=2) |
| missing_fact | silent | 8 | 37.5 [13.7, 69.4] (n=8) | 0.0 [0.0, 32.4] (n=8) | 0.0 [0.0, 32.4] (n=8) |
| missing_fact | visible | 69 | 69.6 [57.9, 79.2] (n=69) | 30.4 [20.8, 42.1] (n=69) | 27.5 [18.4, 39.0] (n=69) |
| non_kg | ungrounded | 50 | 100.0 [92.9, 100.0] (n=50) | 0.0 [0.0, 7.1] (n=50) | - |
| non_kg | wrong | 50 | 90.0 [78.6, 95.7] (n=50) | 0.0 [0.0, 7.1] (n=50) | - |
| wrong_fact | challenger_key_right | 30 | 80.0 [62.7, 90.5] (n=30) | 13.3 [5.3, 29.7] (n=30) | 6.7 [1.8, 21.3] (n=30) |
| wrong_fact | challenger_key_wrong | 26 | 76.9 [57.9, 89.0] (n=26) | 15.4 [6.2, 33.5] (n=26) | 11.5 [4.0, 29.0] (n=26) |
| wrong_fact | silent | 2 | 0.0 [0.0, 65.8] (n=2) | 0.0 [0.0, 65.8] (n=2) | 0.0 [0.0, 65.8] (n=2) |
| wrong_fact | visible | 70 | 48.6 [37.2, 60.0] (n=70) | 32.9 [23.0, 44.5] (n=70) | 15.7 [9.0, 26.0] (n=70) |

## Counterfactual tool (full)

The sandbox re-run is information for the Curator, not a gate: a correct edit need not fix a wrong Solver program.

| quantity | value |
|---|---|
| first-turn edits proposed | 172 |
| decisions (commit / revise / withdraw / invalid) | 72 / 95 / 5 / 0 |
| sandbox: Solver answer fixed after an exact edit % | 72.3 [60.4, 81.7] (n=65) |
| exact first edits withdrawn after the tool % (lower is better) | 3.1 [0.8, 10.5] (n=65) |
| exact first edits kept and admitted % | 50.8 [38.9, 62.5] (n=65) |
| wrong first edits withdrawn or revised to exact % (higher is better) | 54.2 [44.8, 63.3] (n=107) |

## Paired ablations (same cases, exact McNemar)

| comparison | outcome | pairs | full % | ablation % | full-only / ablation-only | p |
|---|---|---|---|---|---|---|
| full vs no_tool | exact repair (KG cases) | 50 | 16.0 | 14.0 | 1/0 | 1 |
| full vs no_tool | false edit (non_kg / bad_key cases) | 50 | 0.0 | 0.0 | 0/0 | 1 |

## Source gate (full)

| quantity | value |
|---|---|
| final edits | 112 |
| cite a shown evidence item % | 100.0 [96.7, 100.0] (n=112) |
| verifier confirms the cited item % | 48.2 [39.2, 57.4] (n=112) |
| blocked: the shown evidence states the value the edit replaces % | 3.7 [1.0, 12.5] (n=54) |
| admitted % | 46.4 [37.5, 55.6] (n=112) |
| gate rejected an exact repair % | 25.0 [17.9, 33.8] (n=112) |

## Confusion matrix (full, all flagged cases)

| gold \ predicted | missing_fact | wrong_fact | non_kg | bad_key | invalid |
|---|---|---|---|---|---|
| missing_fact | 52 | 2 | 24 | 0 | 1 |
| wrong_fact | 27 | 78 | 9 | 13 | 1 |
| non_kg | 2 | 1 | 95 | 2 | 0 |
| bad_key | 1 | 8 | 1 | 15 | 0 |

## Cases from Exp 1 Challenger tasks (full)

bad_key: the KG is right and the Challenger changed the key to a wrong value (correct: bad_key, no edit). challenger_key_wrong: the path has a defect and the key is another wrong value (correct: repair to the G* value, not to the key). challenger_key_right: control, the key was fixed to the G* value (correct: repair). 'writes the wrong key' = an admitted edit puts the task's wrong key into the KG; 'blocked' = the two-sided gate found the replaced value stated in the shown evidence.

| class | subtype | cases | flagged % | runs | diagnosis correct % | diagnosed bad_key % | admitted edit % | exact repair % | admitted edit writes the wrong key % | blocked by the gate % |
|---|---|---|---|---|---|---|---|---|---|---|
| bad_key | challenger | 25 | 100.0 [86.7, 100.0] (n=25) | 25 | 60.0 [40.7, 76.6] (n=25) | 60.0 [40.7, 76.6] (n=25) | 0.0 [0.0, 13.3] (n=25) | - | 0.0 [0.0, 13.3] (n=25) | 8.0 [2.2, 25.0] (n=25) |
| wrong_fact | challenger_key_wrong | 30 | 86.7 [70.3, 94.7] (n=30) | 26 | 76.9 [57.9, 89.0] (n=26) | 15.4 [6.2, 33.5] (n=26) | 15.4 [6.2, 33.5] (n=26) | 11.5 [4.0, 29.0] (n=26) | 3.8 [0.7, 18.9] (n=26) | 0.0 [0.0, 12.9] (n=26) |
| wrong_fact | challenger_key_right | 30 | 100.0 [88.6, 100.0] (n=30) | 30 | 80.0 [62.7, 90.5] (n=30) | 6.7 [1.8, 21.3] (n=30) | 13.3 [5.3, 29.7] (n=30) | 6.7 [1.8, 21.3] (n=30) | - | 0.0 [0.0, 11.4] (n=30) |

## Locality and portability of admitted edits (gold KQA Pro programs, exact)

Regressions among previously correct neighbour questions: 0.0 [0.0, 0.6] (n=692).  

Portability (questions that use the defective fact and become correct): 40.0 [16.8, 68.7] (n=10).

Solver-level regressions: 3.8 [1.7, 7.9] (n=160).

## Baselines (flagged KQA Pro cases)

| baseline | result |
|---|---|
| execution rule (error/empty -> missing, other answer -> wrong, key returned -> non_kg), macro-F1 % | 38.8 [33.4, 44.2] |
| majority class, macro-F1 % | 19.0 [16.9, 20.9] |
| surface-feature logistic regression, KG vs non-KG AUC (shortcut check) | 0.878 (n=251) |

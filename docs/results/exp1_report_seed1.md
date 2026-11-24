# Exp 1 report

Counts only; statistical tests are to be added later.

## Data

Region A: 200 entities; region B: 200; candidate pool 3735. Facts of A and B: 9307; supported (S): 2195.

| KG | defects | deleted | corrupted | similar corruptions | random corruptions |
|---|---|---|---|---|---|
| rate30_seed1 | 233 | 116 | 117 | 62 | 55 |

Mode A paths. Defective: the path uses a corrupted fact and its G* answer differs from the Gw answer. Clean: no fact changed, first hop in S, same answer on Gw and G*. Deleted facts cannot lie on a Gw path and are measured in Mode B.

| KG | path type | defective | clean |
|---|---|---|---|
| rate30_seed1 | attr | 51 | 51 |
| rate30_seed1 | rel | 13 | 13 |
| rate30_seed1 | rel_attr | 23 | 23 |
| rate30_seed1 | rel_rel | 13 | 13 |
| rate30_seed1 | all | 100 | 100 |

## Mode A: task generation from paths

Decision-level counts on the shared paths (do not depend on how the question is worded). What counts is the emitted key: a "correct" decision that keeps the Gw answer is counted as *kept* (the model flagged a fact but did not change the key; shown separately as "flagged, key kept"); *fixed* = the key was changed.

### Defective paths

kept = the defect passes into the task; fixed right = the new key equals G*; caught = rejected or key changed.

| cond | paths | kept (defect passed) | of which flagged, key kept | fixed, right value | fixed, wrong value | reject | invalid | caught |
|---|---|---|---|---|---|---|---|---|
| B0 | 100 | 100/100 (100%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) |
| C1 | 100 | 39/100 (39%) | 27/100 (27%) | 13/100 (13%) | 30/100 (30%) | 18/100 (18%) | 0/100 (0%) | 61/100 (61%) |
| C1know | 100 | 39/100 (39%) | 36/100 (36%) | 18/100 (18%) | 38/100 (38%) | 5/100 (5%) | 0/100 (0%) | 61/100 (61%) |
| C2 | 100 | 8/100 (8%) | 8/100 (8%) | 54/100 (54%) | 26/100 (26%) | 12/100 (12%) | 0/100 (0%) | 92/100 (92%) |
| C3 | 100 | 27/100 (27%) | 27/100 (27%) | 66/100 (66%) | 7/100 (7%) | 0/100 (0%) | 0/100 (0%) | 73/100 (73%) |

### Clean paths

| cond | paths | kept | of which flagged, key kept | false fix (key changed) | false reject | invalid |
|---|---|---|---|---|---|---|
| B0 | 100 | 100/100 (100%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) |
| C1 | 100 | 56/100 (56%) | 21/100 (21%) | 14/100 (14%) | 30/100 (30%) | 0/100 (0%) |
| C1know | 100 | 75/100 (75%) | 57/100 (57%) | 23/100 (23%) | 2/100 (2%) | 0/100 (0%) |
| C2 | 100 | 80/100 (80%) | 35/100 (35%) | 14/100 (14%) | 6/100 (6%) | 0/100 (0%) |
| C3 | 100 | 95/100 (95%) | 6/100 (6%) | 3/100 (3%) | 2/100 (2%) | 0/100 (0%) |

### Emitted tasks (accept + correct) with a wrong answer key, by cause

defect passed = accepted defective path; failed fix = corrected a defective path to a wrong value; introduced = changed the key of a clean path. Corrections = key changes; grounded = the new key appears in the evidence shown.

| cond | emitted | wrong key | defect passed | failed fix | introduced | corrections | grounded corrections |
|---|---|---|---|---|---|---|---|
| B0 | 200 | 100/200 (50%) | 100 | 0 | 0 | 0 | 0/0 |
| C1 | 152 | 83/152 (55%) | 39 | 30 | 14 | 57 | 33/57 (58%) |
| C1know | 193 | 100/193 (52%) | 39 | 38 | 23 | 79 | 33/79 (42%) |
| C2 | 182 | 48/182 (26%) | 8 | 26 | 14 | 94 | 89/94 (95%) |
| C3 | 198 | 39/198 (20%) | 27 | 7 | 5 | 76 | 75/76 (99%) |

### Funnel of emitted tasks (E0-E5)

E5 = valid tasks (E0-E4, E3 rules and judge) whose key differs from G*.

| cond | emitted | E0 fail | E1 fail | E2 fail | E3-rule fail | E3-judge fail | E4 fail | valid | E5 wrong key | E5: defect passed | E5: failed fix | E5: introduced |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | 200 | 0 | 0 | 0 | 4 | 36 | 0 | 160 | 72 | 72 | 0 | 0 |
| C1 | 152 | 1 | 0 | 0 | 11 | 12 | 0 | 128 | 67 | 33 | 22 | 12 |
| C1know | 193 | 0 | 0 | 0 | 14 | 13 | 0 | 166 | 89 | 33 | 34 | 22 |
| C2 | 182 | 0 | 0 | 0 | 7 | 15 | 0 | 160 | 40 | 6 | 22 | 12 |
| C3 | 198 | 0 | 0 | 2 | 18 | 15 | 0 | 163 | 26 | 17 | 6 | 3 |

### Strata

caught = rejected or key changed (on defective paths); false alarm = rejected or key changed (on clean paths).

| cond | stratum | defective: caught | clean: false alarm |
|---|---|---|---|
| B0 | 1-hop | 0/64 (0%) | 0/64 (0%) |
| B0 | 2-hop | 0/36 (0%) | 0/36 (0%) |
| B0 | head entity | 0/52 (0%) | 0/42 (0%) |
| B0 | torso entity | 0/32 (0%) | 0/35 (0%) |
| B0 | tail entity | 0/16 (0%) | 0/23 (0%) |
| B0 | similar corruption | 0/57 (0%) | – |
| B0 | random corruption | 0/43 (0%) | – |
| B0 | subtype attr_date | 0/29 (0%) | – |
| B0 | subtype attr_string | 0/22 (0%) | – |
| B0 | subtype rel_object | 0/49 (0%) | – |
| C1 | 1-hop | 45/64 (70%) | 19/64 (30%) |
| C1 | 2-hop | 16/36 (44%) | 25/36 (69%) |
| C1 | head entity | 33/52 (63%) | 16/42 (38%) |
| C1 | torso entity | 18/32 (56%) | 17/35 (49%) |
| C1 | tail entity | 10/16 (62%) | 11/23 (48%) |
| C1 | similar corruption | 29/57 (51%) | – |
| C1 | random corruption | 32/43 (74%) | – |
| C1 | subtype attr_date | 19/29 (66%) | – |
| C1 | subtype attr_string | 19/22 (86%) | – |
| C1 | subtype rel_object | 23/49 (47%) | – |
| C1know | 1-hop | 49/64 (77%) | 13/64 (20%) |
| C1know | 2-hop | 12/36 (33%) | 12/36 (33%) |
| C1know | head entity | 36/52 (69%) | 11/42 (26%) |
| C1know | torso entity | 19/32 (59%) | 7/35 (20%) |
| C1know | tail entity | 6/16 (38%) | 7/23 (30%) |
| C1know | similar corruption | 30/57 (53%) | – |
| C1know | random corruption | 31/43 (72%) | – |
| C1know | subtype attr_date | 24/29 (83%) | – |
| C1know | subtype attr_string | 20/22 (91%) | – |
| C1know | subtype rel_object | 17/49 (35%) | – |
| C2 | 1-hop | 63/64 (98%) | 3/64 (5%) |
| C2 | 2-hop | 29/36 (81%) | 17/36 (47%) |
| C2 | head entity | 46/52 (88%) | 9/42 (21%) |
| C2 | torso entity | 31/32 (97%) | 7/35 (20%) |
| C2 | tail entity | 15/16 (94%) | 4/23 (17%) |
| C2 | similar corruption | 52/57 (91%) | – |
| C2 | random corruption | 40/43 (93%) | – |
| C2 | subtype attr_date | 29/29 (100%) | – |
| C2 | subtype attr_string | 21/22 (95%) | – |
| C2 | subtype rel_object | 42/49 (86%) | – |
| C3 | 1-hop | 64/64 (100%) | 0/64 (0%) |
| C3 | 2-hop | 9/36 (25%) | 5/36 (14%) |
| C3 | head entity | 37/52 (71%) | 3/42 (7%) |
| C3 | torso entity | 27/32 (84%) | 1/35 (3%) |
| C3 | tail entity | 9/16 (56%) | 1/23 (4%) |
| C3 | similar corruption | 39/57 (68%) | – |
| C3 | random corruption | 34/43 (79%) | – |
| C3 | subtype attr_date | 29/29 (100%) | – |
| C3 | subtype attr_string | 22/22 (100%) | – |
| C3 | subtype rel_object | 22/49 (45%) | – |

## Mode B: gap discovery

Each claim is a hit (key and true value of an injected defect) or an error. Located-only = an error on the key of a defect with a wrong value; other = every other error (already in Gw, not in G*, unresolvable, or a real gap of the original KB, which is counted as an error because there is no human audit).

| cond | entities | claims | hits | located-only | other errors | precision | defects | recall | label accuracy |
|---|---|---|---|---|---|---|---|---|---|
| C1 | 100 | 43 | 5 | 6 | 32 | 5/43 (12%) | 124 | 5/124 (4%) | 4/5 (80%) |
| C1know | 100 | 230 | 15 | 29 | 186 | 15/230 (7%) | 124 | 15/124 (12%) | 14/15 (93%) |
| C2 | 100 | 384 | 53 | 33 | 298 | 53/384 (14%) | 124 | 51/124 (41%) | 50/51 (98%) |
| C3 | 100 | 113 | 108 | 3 | 2 | 108/113 (96%) | 124 | 108/124 (87%) | 103/108 (95%) |

### Recall by stratum

| cond | stratum | detected |
|---|---|---|
| C1 | deleted | 1/62 (2%) |
| C1 | corrupted | 4/62 (6%) |
| C1 | similar corruption | 0/30 (0%) |
| C1 | random corruption | 4/32 (12%) |
| C1 | head entity | 5/61 (8%) |
| C1 | torso entity | 0/41 (0%) |
| C1 | tail entity | 0/22 (0%) |
| C1know | deleted | 3/62 (5%) |
| C1know | corrupted | 12/62 (19%) |
| C1know | similar corruption | 4/30 (13%) |
| C1know | random corruption | 8/32 (25%) |
| C1know | head entity | 12/61 (20%) |
| C1know | torso entity | 3/41 (7%) |
| C1know | tail entity | 0/22 (0%) |
| C2 | deleted | 21/62 (34%) |
| C2 | corrupted | 30/62 (48%) |
| C2 | similar corruption | 16/30 (53%) |
| C2 | random corruption | 14/32 (44%) |
| C2 | head entity | 23/61 (38%) |
| C2 | torso entity | 16/41 (39%) |
| C2 | tail entity | 12/22 (55%) |
| C3 | deleted | 50/62 (81%) |
| C3 | corrupted | 58/62 (94%) |
| C3 | similar corruption | 28/30 (93%) |
| C3 | random corruption | 30/32 (94%) |
| C3 | head entity | 51/61 (84%) |
| C3 | torso entity | 36/41 (88%) |
| C3 | tail entity | 21/22 (95%) |

## Gap tasks

One task per entity from its first resolvable claim; the key is the claimed value and is checked on G*. A wrong key here is the Challenger's error (a wrong gap claim), not a KG error.

| cond | tasks | E0 fail | E3-rule fail | E3-judge fail | key correct | key wrong: fact not in G* | ambiguous: several values in G* | key wrong: other value |
|---|---|---|---|---|---|---|---|---|
| C1 | 14 | 0 | 1 | 2 | 2/14 (14%) | 0 | 5 | 7 |
| C1know | 51 | 0 | 1 | 5 | 15/51 (29%) | 0 | 13 | 23 |
| C2 | 82 | 0 | 0 | 5 | 29/82 (35%) | 6 | 14 | 33 |
| C3 | 64 | 0 | 4 | 4 | 52/64 (81%) | 0 | 12 | 0 |

## E3 judge

The judge is the same model as the Challenger (one model is available), so it may favour its own questions.

| cond | task source | judged faithful |
|---|---|---|
| B0 | mode_a | 158/194 (81%) |
| C1 | gap | 12/14 (86%) |
| C1 | mode_a | 133/149 (89%) |
| C1know | gap | 46/51 (90%) |
| C1know | mode_a | 171/188 (91%) |
| C2 | gap | 73/78 (94%) |
| C2 | mode_a | 161/179 (90%) |
| C3 | gap | 55/59 (93%) |
| C3 | mode_a | 172/192 (90%) |

## Task quality (Solver)

k = 8 Solver samples per task and setting; pass rate = share of the k answers that match.

### Pass rates

| cond | source | tasks | key correct | gw: pass vs key | gw: pass vs G* | gstar: pass vs key | gstar: pass vs G* | closed: pass vs key | closed: pass vs G* |
|---|---|---|---|---|---|---|---|---|---|
| B0 | mode_a/clean | 24 | 24 | 68% | 68% | 67% | 67% | 24% | 24% |
| C1 | mode_a/clean | 26 | 20 | 76% | 76% | 76% | 76% | 29% | 36% |
| C1know | mode_a/clean | 21 | 13 | 63% | 54% | 63% | 54% | 33% | 32% |
| C2 | mode_a/clean | 23 | 20 | 79% | 78% | 82% | 78% | 16% | 18% |
| C3 | mode_a/clean | 22 | 21 | 77% | 77% | 77% | 77% | 18% | 18% |
| B0 | mode_a/defective | 16 | 0 | 59% | 7% | 0% | 66% | 0% | 22% |
| C1 | mode_a/defective | 14 | 1 | 36% | 23% | 7% | 73% | 7% | 43% |
| C1know | mode_a/defective | 19 | 3 | 19% | 10% | 11% | 57% | 13% | 14% |
| C2 | mode_a/defective | 17 | 10 | 12% | 13% | 42% | 60% | 12% | 20% |
| C3 | mode_a/defective | 18 | 12 | 25% | 17% | 64% | 67% | 24% | 22% |
| C1 | gap | 6 | 1 | 6% | 6% | 17% | 56% | 25% | 31% |
| C1know | gap | 32 | 12 | 9% | 19% | 23% | 58% | 13% | 17% |
| C2 | gap | 40 | 18 | 6% | 19% | 40% | 56% | 9% | 12% |
| C3 | gap | 40 | 40 | 10% | 10% | 62% | 62% | 18% | 18% |

### Difficulty on Gw (tasks with a correct key; correct = matches G*)

Target: 30-70% of the 8 answers correct.

| cond | source | tasks with correct key | 0/8 | 1-2/8 | 3-5/8 (target) | 6-7/8 | 8/8 | gap-dependent (G* >= 6, Gw <= 2) | closed-book leak (closed >= 6) |
|---|---|---|---|---|---|---|---|---|---|
| B0 | mode_a/clean | 24 | 6/24 (25%) | 1/24 (4%) | 1/24 (4%) | 1/24 (4%) | 15/24 (62%) | 0/24 (0%) | 6/24 (25%) |
| C1 | mode_a/clean | 20 | 2/20 (10%) | 0/20 (0%) | 0/20 (0%) | 1/20 (5%) | 17/20 (85%) | 0/20 (0%) | 7/20 (35%) |
| C1know | mode_a/clean | 13 | 3/13 (23%) | 0/13 (0%) | 1/13 (8%) | 0/13 (0%) | 9/13 (69%) | 0/13 (0%) | 4/13 (31%) |
| C2 | mode_a/clean | 20 | 3/20 (15%) | 0/20 (0%) | 0/20 (0%) | 0/20 (0%) | 17/20 (85%) | 0/20 (0%) | 3/20 (15%) |
| C3 | mode_a/clean | 21 | 3/21 (14%) | 1/21 (5%) | 0/21 (0%) | 2/21 (10%) | 15/21 (71%) | 0/21 (0%) | 4/21 (19%) |
| B0 | mode_a/defective | 0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| C1 | mode_a/defective | 1 | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |
| C1know | mode_a/defective | 3 | 2/3 (67%) | 0/3 (0%) | 1/3 (33%) | 0/3 (0%) | 0/3 (0%) | 1/3 (33%) | 2/3 (67%) |
| C2 | mode_a/defective | 10 | 9/10 (90%) | 0/10 (0%) | 0/10 (0%) | 0/10 (0%) | 1/10 (10%) | 6/10 (60%) | 2/10 (20%) |
| C3 | mode_a/defective | 12 | 9/12 (75%) | 0/12 (0%) | 0/12 (0%) | 1/12 (8%) | 2/12 (17%) | 8/12 (67%) | 4/12 (33%) |
| C1 | gap | 1 | 1/1 (100%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) | 1/1 (100%) |
| C1know | gap | 12 | 9/12 (75%) | 2/12 (17%) | 0/12 (0%) | 0/12 (0%) | 1/12 (8%) | 5/12 (42%) | 2/12 (17%) |
| C2 | gap | 18 | 16/18 (89%) | 1/18 (6%) | 0/18 (0%) | 0/18 (0%) | 1/18 (6%) | 14/18 (78%) | 2/18 (11%) |
| C3 | gap | 40 | 34/40 (85%) | 1/40 (2%) | 1/40 (2%) | 2/40 (5%) | 2/40 (5%) | 19/40 (48%) | 7/40 (18%) |

### Tasks with a wrong key on Gw

agrees with key = the Solver on Gw returns the wrong key in >= 6/8 samples: the reward would confirm the wrong fact and the error stays hidden.

| cond | source | tasks with wrong key | Solver agrees with key | Solver matches G* |
|---|---|---|---|---|
| B0 | mode_a/clean | 0 | 0/0 | 0/0 |
| C1 | mode_a/clean | 6 | 2/6 (33%) | 2/6 (33%) |
| C1know | mode_a/clean | 8 | 4/8 (50%) | 2/8 (25%) |
| C2 | mode_a/clean | 3 | 1/3 (33%) | 1/3 (33%) |
| C3 | mode_a/clean | 1 | 0/1 (0%) | 0/1 (0%) |
| B0 | mode_a/defective | 16 | 9/16 (56%) | 1/16 (6%) |
| C1 | mode_a/defective | 13 | 4/13 (31%) | 2/13 (15%) |
| C1know | mode_a/defective | 16 | 2/16 (12%) | 1/16 (6%) |
| C2 | mode_a/defective | 7 | 1/7 (14%) | 1/7 (14%) |
| C3 | mode_a/defective | 6 | 2/6 (33%) | 0/6 (0%) |
| C1 | gap | 5 | 0/5 (0%) | 0/5 (0%) |
| C1know | gap | 20 | 1/20 (5%) | 4/20 (20%) |
| C2 | gap | 22 | 1/22 (5%) | 5/22 (23%) |
| C3 | gap | 0 | 0/0 | 0/0 |

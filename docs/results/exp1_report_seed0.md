# Exp 1 report

Counts only; statistical tests are to be added later.

## Data

Region A: 200 entities; region B: 200; candidate pool 3735. Facts of A and B: 9307; supported (S): 2195.

| KG | defects | deleted | corrupted | similar corruptions | random corruptions |
|---|---|---|---|---|---|
| rate30_seed0 | 233 | 116 | 117 | 66 | 51 |

Mode A paths. Defective: the path uses a corrupted fact and its G* answer differs from the Gw answer. Clean: no fact changed, first hop in S, same answer on Gw and G*. Deleted facts cannot lie on a Gw path and are measured in Mode B.

| KG | path type | defective | clean |
|---|---|---|---|
| rate30_seed0 | attr | 54 | 54 |
| rate30_seed0 | rel | 11 | 11 |
| rate30_seed0 | rel_attr | 27 | 27 |
| rate30_seed0 | rel_rel | 8 | 8 |
| rate30_seed0 | all | 100 | 100 |

## Mode A: task generation from paths

Decision-level counts on the shared paths (do not depend on how the question is worded). What counts is the emitted key: a "correct" decision that keeps the Gw answer is counted as *kept* (the model flagged a fact but did not change the key; shown separately as "flagged, key kept"); *fixed* = the key was changed.

### Defective paths

kept = the defect passes into the task; fixed right = the new key equals G*; caught = rejected or key changed.

| cond | paths | kept (defect passed) | of which flagged, key kept | fixed, right value | fixed, wrong value | reject | invalid | caught |
|---|---|---|---|---|---|---|---|---|
| B0 | 100 | 100/100 (100%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) |
| C1 | 100 | 37/100 (37%) | 22/100 (22%) | 14/100 (14%) | 30/100 (30%) | 19/100 (19%) | 0/100 (0%) | 63/100 (63%) |
| C1know | 100 | 38/100 (38%) | 34/100 (34%) | 20/100 (20%) | 39/100 (39%) | 3/100 (3%) | 0/100 (0%) | 62/100 (62%) |
| C2 | 100 | 7/100 (7%) | 7/100 (7%) | 62/100 (62%) | 27/100 (27%) | 4/100 (4%) | 0/100 (0%) | 93/100 (93%) |
| C3 | 100 | 18/100 (18%) | 18/100 (18%) | 66/100 (66%) | 16/100 (16%) | 0/100 (0%) | 0/100 (0%) | 82/100 (82%) |

### Clean paths

| cond | paths | kept | of which flagged, key kept | false fix (key changed) | false reject | invalid |
|---|---|---|---|---|---|---|
| B0 | 100 | 100/100 (100%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) | 0/100 (0%) |
| C1 | 100 | 65/100 (65%) | 24/100 (24%) | 6/100 (6%) | 29/100 (29%) | 0/100 (0%) |
| C1know | 100 | 73/100 (73%) | 51/100 (51%) | 20/100 (20%) | 7/100 (7%) | 0/100 (0%) |
| C2 | 100 | 86/100 (86%) | 34/100 (34%) | 8/100 (8%) | 6/100 (6%) | 0/100 (0%) |
| C3 | 100 | 97/100 (97%) | 3/100 (3%) | 1/100 (1%) | 2/100 (2%) | 0/100 (0%) |

### Emitted tasks (accept + correct) with a wrong answer key, by cause

defect passed = accepted defective path; failed fix = corrected a defective path to a wrong value; introduced = changed the key of a clean path. Corrections = key changes; grounded = the new key appears in the evidence shown.

| cond | emitted | wrong key | defect passed | failed fix | introduced | corrections | grounded corrections |
|---|---|---|---|---|---|---|---|
| B0 | 200 | 100/200 (50%) | 100 | 0 | 0 | 0 | 0/0 |
| C1 | 152 | 73/152 (48%) | 37 | 30 | 6 | 50 | 22/50 (44%) |
| C1know | 190 | 97/190 (51%) | 38 | 39 | 20 | 79 | 24/79 (30%) |
| C2 | 190 | 42/190 (22%) | 7 | 27 | 8 | 97 | 85/97 (88%) |
| C3 | 198 | 39/198 (20%) | 18 | 16 | 5 | 83 | 79/83 (95%) |

### Funnel of emitted tasks (E0-E5)

E5 = valid tasks (E0-E4, E3 rules and judge) whose key differs from G*.

| cond | emitted | E0 fail | E1 fail | E2 fail | E3-rule fail | E3-judge fail | E4 fail | valid | E5 wrong key | E5: defect passed | E5: failed fix | E5: introduced |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | 200 | 0 | 0 | 0 | 5 | 30 | 0 | 165 | 80 | 80 | 0 | 0 |
| C1 | 152 | 1 | 0 | 0 | 11 | 9 | 0 | 131 | 63 | 35 | 24 | 4 |
| C1know | 190 | 1 | 0 | 0 | 14 | 14 | 0 | 161 | 80 | 30 | 34 | 16 |
| C2 | 190 | 1 | 0 | 0 | 7 | 14 | 0 | 168 | 35 | 5 | 24 | 6 |
| C3 | 198 | 1 | 0 | 4 | 12 | 15 | 0 | 166 | 26 | 13 | 12 | 1 |

### Strata

caught = rejected or key changed (on defective paths); false alarm = rejected or key changed (on clean paths).

| cond | stratum | defective: caught | clean: false alarm |
|---|---|---|---|
| B0 | 1-hop | 0/65 (0%) | 0/65 (0%) |
| B0 | 2-hop | 0/35 (0%) | 0/35 (0%) |
| B0 | head entity | 0/42 (0%) | 0/39 (0%) |
| B0 | torso entity | 0/31 (0%) | 0/28 (0%) |
| B0 | tail entity | 0/27 (0%) | 0/33 (0%) |
| B0 | similar corruption | 0/53 (0%) | – |
| B0 | random corruption | 0/47 (0%) | – |
| B0 | subtype attr_date | 0/41 (0%) | – |
| B0 | subtype attr_string | 0/13 (0%) | – |
| B0 | subtype rel_object | 0/46 (0%) | – |
| B0 | defect known (closed-book) | 0/24 (0%) | – |
| B0 | defect unknown (closed-book) | 0/76 (0%) | – |
| C1 | 1-hop | 45/65 (69%) | 16/65 (25%) |
| C1 | 2-hop | 18/35 (51%) | 19/35 (54%) |
| C1 | head entity | 31/42 (74%) | 10/39 (26%) |
| C1 | torso entity | 16/31 (52%) | 7/28 (25%) |
| C1 | tail entity | 16/27 (59%) | 18/33 (55%) |
| C1 | similar corruption | 28/53 (53%) | – |
| C1 | random corruption | 35/47 (74%) | – |
| C1 | subtype attr_date | 23/41 (56%) | – |
| C1 | subtype attr_string | 13/13 (100%) | – |
| C1 | subtype rel_object | 27/46 (59%) | – |
| C1 | defect known (closed-book) | 18/24 (75%) | – |
| C1 | defect unknown (closed-book) | 45/76 (59%) | – |
| C1know | 1-hop | 46/65 (71%) | 11/65 (17%) |
| C1know | 2-hop | 16/35 (46%) | 16/35 (46%) |
| C1know | head entity | 30/42 (71%) | 6/39 (15%) |
| C1know | torso entity | 15/31 (48%) | 9/28 (32%) |
| C1know | tail entity | 17/27 (63%) | 12/33 (36%) |
| C1know | similar corruption | 29/53 (55%) | – |
| C1know | random corruption | 33/47 (70%) | – |
| C1know | subtype attr_date | 27/41 (66%) | – |
| C1know | subtype attr_string | 12/13 (92%) | – |
| C1know | subtype rel_object | 23/46 (50%) | – |
| C1know | defect known (closed-book) | 21/24 (88%) | – |
| C1know | defect unknown (closed-book) | 41/76 (54%) | – |
| C2 | 1-hop | 65/65 (100%) | 2/65 (3%) |
| C2 | 2-hop | 28/35 (80%) | 12/35 (34%) |
| C2 | head entity | 41/42 (98%) | 4/39 (10%) |
| C2 | torso entity | 27/31 (87%) | 5/28 (18%) |
| C2 | tail entity | 25/27 (93%) | 5/33 (15%) |
| C2 | similar corruption | 49/53 (92%) | – |
| C2 | random corruption | 44/47 (94%) | – |
| C2 | subtype attr_date | 41/41 (100%) | – |
| C2 | subtype attr_string | 13/13 (100%) | – |
| C2 | subtype rel_object | 39/46 (85%) | – |
| C2 | defect known (closed-book) | 22/24 (92%) | – |
| C2 | defect unknown (closed-book) | 71/76 (93%) | – |
| C3 | 1-hop | 65/65 (100%) | 1/65 (2%) |
| C3 | 2-hop | 17/35 (49%) | 2/35 (6%) |
| C3 | head entity | 35/42 (83%) | 2/39 (5%) |
| C3 | torso entity | 24/31 (77%) | 0/28 (0%) |
| C3 | tail entity | 23/27 (85%) | 1/33 (3%) |
| C3 | similar corruption | 46/53 (87%) | – |
| C3 | random corruption | 36/47 (77%) | – |
| C3 | subtype attr_date | 41/41 (100%) | – |
| C3 | subtype attr_string | 13/13 (100%) | – |
| C3 | subtype rel_object | 28/46 (61%) | – |
| C3 | defect known (closed-book) | 21/24 (88%) | – |
| C3 | defect unknown (closed-book) | 61/76 (80%) | – |

## Mode B: gap discovery

Each claim is a hit (key and true value of an injected defect) or an error. Located-only = an error on the key of a defect with a wrong value; other = every other error (already in Gw, not in G*, unresolvable, or a real gap of the original KB, which is counted as an error because there is no human audit).

| cond | entities | claims | hits | located-only | other errors | precision | defects | recall | label accuracy |
|---|---|---|---|---|---|---|---|---|---|
| C1 | 100 | 27 | 1 | 4 | 22 | 1/27 (4%) | 127 | 1/127 (1%) | 1/1 (100%) |
| C1know | 100 | 159 | 13 | 19 | 127 | 13/159 (8%) | 127 | 13/127 (10%) | 12/13 (92%) |
| C2 | 100 | 332 | 53 | 27 | 252 | 53/332 (16%) | 127 | 48/127 (38%) | 47/48 (98%) |
| C3 | 100 | 105 | 93 | 8 | 4 | 93/105 (89%) | 127 | 93/127 (73%) | 89/93 (96%) |

### Recall by stratum

| cond | stratum | detected |
|---|---|---|
| C1 | deleted | 0/66 (0%) |
| C1 | corrupted | 1/61 (2%) |
| C1 | similar corruption | 1/33 (3%) |
| C1 | random corruption | 0/28 (0%) |
| C1 | head entity | 0/65 (0%) |
| C1 | torso entity | 1/40 (2%) |
| C1 | tail entity | 0/22 (0%) |
| C1 | known (closed-book) | 1/30 (3%) |
| C1 | unknown (closed-book) | 0/97 (0%) |
| C1know | deleted | 2/66 (3%) |
| C1know | corrupted | 11/61 (18%) |
| C1know | similar corruption | 7/33 (21%) |
| C1know | random corruption | 4/28 (14%) |
| C1know | head entity | 9/65 (14%) |
| C1know | torso entity | 3/40 (8%) |
| C1know | tail entity | 1/22 (5%) |
| C1know | known (closed-book) | 6/30 (20%) |
| C1know | unknown (closed-book) | 7/97 (7%) |
| C2 | deleted | 16/66 (24%) |
| C2 | corrupted | 32/61 (52%) |
| C2 | similar corruption | 18/33 (55%) |
| C2 | random corruption | 14/28 (50%) |
| C2 | head entity | 26/65 (40%) |
| C2 | torso entity | 11/40 (28%) |
| C2 | tail entity | 11/22 (50%) |
| C2 | known (closed-book) | 15/30 (50%) |
| C2 | unknown (closed-book) | 33/97 (34%) |
| C3 | deleted | 41/66 (62%) |
| C3 | corrupted | 52/61 (85%) |
| C3 | similar corruption | 28/33 (85%) |
| C3 | random corruption | 24/28 (86%) |
| C3 | head entity | 44/65 (68%) |
| C3 | torso entity | 31/40 (78%) |
| C3 | tail entity | 18/22 (82%) |
| C3 | known (closed-book) | 21/30 (70%) |
| C3 | unknown (closed-book) | 72/97 (74%) |
| C0 | corruptions whose true value is recalled | 10/61 (16%) |
| C0 | deletions whose value is recalled | 20/66 (30%) |

## Gap tasks

One task per entity from its first resolvable claim; the key is the claimed value and is checked on G*. A wrong key here is the Challenger's error (a wrong gap claim), not a KG error.

| cond | tasks | E0 fail | E3-rule fail | E3-judge fail | key correct | key wrong: fact not in G* | ambiguous: several values in G* | key wrong: other value |
|---|---|---|---|---|---|---|---|---|
| C1 | 11 | 0 | 0 | 2 | 1/11 (9%) | 0 | 5 | 5 |
| C1know | 47 | 0 | 3 | 6 | 8/47 (17%) | 0 | 16 | 23 |
| C2 | 84 | 0 | 0 | 8 | 35/84 (42%) | 4 | 18 | 27 |
| C3 | 62 | 0 | 2 | 4 | 48/62 (77%) | 0 | 12 | 2 |

## E3 judge

The judge is the same model as the Challenger (one model is available), so it may favour its own questions.

| cond | task source | judged faithful |
|---|---|---|
| B0 | mode_a | 164/194 (85%) |
| C1 | gap | 8/10 (80%) |
| C1 | mode_a | 139/149 (93%) |
| C1know | gap | 40/46 (87%) |
| C1know | mode_a | 168/187 (90%) |
| C2 | gap | 73/81 (90%) |
| C2 | mode_a | 172/187 (92%) |
| C3 | gap | 57/61 (93%) |
| C3 | mode_a | 172/189 (91%) |

## Task quality (Solver)

k = 8 Solver samples per task and setting; pass rate = share of the k answers that match.

### Pass rates

| cond | source | tasks | key correct | gw: pass vs key | gw: pass vs G* | gstar: pass vs key | gstar: pass vs G* | closed: pass vs key | closed: pass vs G* |
|---|---|---|---|---|---|---|---|---|---|
| B0 | mode_a/clean | 18 | 18 | 78% | 78% | 80% | 80% | 21% | 21% |
| C1 | mode_a/clean | 25 | 23 | 84% | 84% | 84% | 84% | 30% | 30% |
| C1know | mode_a/clean | 18 | 14 | 55% | 66% | 56% | 67% | 15% | 15% |
| C2 | mode_a/clean | 21 | 21 | 76% | 76% | 76% | 76% | 24% | 24% |
| C3 | mode_a/clean | 14 | 13 | 88% | 80% | 88% | 81% | 33% | 33% |
| B0 | mode_a/defective | 22 | 0 | 76% | 12% | 0% | 90% | 0% | 28% |
| C1 | mode_a/defective | 15 | 1 | 46% | 8% | 13% | 73% | 10% | 15% |
| C1know | mode_a/defective | 22 | 5 | 41% | 4% | 34% | 78% | 27% | 23% |
| C2 | mode_a/defective | 19 | 12 | 14% | 8% | 66% | 59% | 21% | 25% |
| C3 | mode_a/defective | 26 | 16 | 29% | 10% | 64% | 80% | 23% | 28% |
| C1 | gap | 4 | 1 | 0% | 0% | 3% | 12% | 0% | 0% |
| C1know | gap | 22 | 4 | 12% | 18% | 15% | 41% | 11% | 7% |
| C2 | gap | 40 | 21 | 13% | 18% | 43% | 49% | 16% | 14% |
| C3 | gap | 40 | 38 | 13% | 12% | 61% | 59% | 21% | 20% |

### Difficulty on Gw (tasks with a correct key; correct = matches G*)

Target: 30-70% of the 8 answers correct.

| cond | source | tasks with correct key | 0/8 | 1-2/8 | 3-5/8 (target) | 6-7/8 | 8/8 | gap-dependent (G* >= 6, Gw <= 2) | closed-book leak (closed >= 6) |
|---|---|---|---|---|---|---|---|---|---|
| B0 | mode_a/clean | 18 | 3/18 (17%) | 0/18 (0%) | 2/18 (11%) | 1/18 (6%) | 12/18 (67%) | 0/18 (0%) | 3/18 (17%) |
| C1 | mode_a/clean | 23 | 1/23 (4%) | 1/23 (4%) | 2/23 (9%) | 1/23 (4%) | 18/23 (78%) | 0/23 (0%) | 7/23 (30%) |
| C1know | mode_a/clean | 14 | 3/14 (21%) | 1/14 (7%) | 0/14 (0%) | 1/14 (7%) | 9/14 (64%) | 0/14 (0%) | 2/14 (14%) |
| C2 | mode_a/clean | 21 | 5/21 (24%) | 0/21 (0%) | 0/21 (0%) | 0/21 (0%) | 16/21 (76%) | 0/21 (0%) | 5/21 (24%) |
| C3 | mode_a/clean | 13 | 1/13 (8%) | 0/13 (0%) | 1/13 (8%) | 1/13 (8%) | 10/13 (77%) | 0/13 (0%) | 4/13 (31%) |
| B0 | mode_a/defective | 0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| C1 | mode_a/defective | 1 | 1/1 (100%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 1/1 (100%) | 1/1 (100%) |
| C1know | mode_a/defective | 5 | 3/5 (60%) | 1/5 (20%) | 1/5 (20%) | 0/5 (0%) | 0/5 (0%) | 4/5 (80%) | 4/5 (80%) |
| C2 | mode_a/defective | 12 | 10/12 (83%) | 1/12 (8%) | 1/12 (8%) | 0/12 (0%) | 0/12 (0%) | 9/12 (75%) | 3/12 (25%) |
| C3 | mode_a/defective | 16 | 12/16 (75%) | 2/16 (12%) | 0/16 (0%) | 1/16 (6%) | 1/16 (6%) | 14/16 (88%) | 6/16 (38%) |
| C1 | gap | 1 | 1/1 (100%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) |
| C1know | gap | 4 | 3/4 (75%) | 1/4 (25%) | 0/4 (0%) | 0/4 (0%) | 0/4 (0%) | 1/4 (25%) | 1/4 (25%) |
| C2 | gap | 21 | 15/21 (71%) | 3/21 (14%) | 0/21 (0%) | 0/21 (0%) | 3/21 (14%) | 12/21 (57%) | 4/21 (19%) |
| C3 | gap | 38 | 30/38 (79%) | 4/38 (11%) | 0/38 (0%) | 1/38 (3%) | 3/38 (8%) | 19/38 (50%) | 6/38 (16%) |

### Tasks with a wrong key on Gw

agrees with key = the Solver on Gw returns the wrong key in >= 6/8 samples: the reward would confirm the wrong fact and the error stays hidden.

| cond | source | tasks with wrong key | Solver agrees with key | Solver matches G* |
|---|---|---|---|---|
| B0 | mode_a/clean | 0 | 0/0 | 0/0 |
| C1 | mode_a/clean | 2 | 1/2 (50%) | 1/2 (50%) |
| C1know | mode_a/clean | 4 | 0/4 (0%) | 2/4 (50%) |
| C2 | mode_a/clean | 0 | 0/0 | 0/0 |
| C3 | mode_a/clean | 1 | 1/1 (100%) | 0/1 (0%) |
| B0 | mode_a/defective | 22 | 16/22 (73%) | 2/22 (9%) |
| C1 | mode_a/defective | 14 | 7/14 (50%) | 1/14 (7%) |
| C1know | mode_a/defective | 17 | 7/17 (41%) | 0/17 (0%) |
| C2 | mode_a/defective | 7 | 2/7 (29%) | 1/7 (14%) |
| C3 | mode_a/defective | 10 | 5/10 (50%) | 0/10 (0%) |
| C1 | gap | 3 | 0/3 (0%) | 0/3 (0%) |
| C1know | gap | 18 | 0/18 (0%) | 3/18 (17%) |
| C2 | gap | 19 | 2/19 (11%) | 3/19 (16%) |
| C3 | gap | 2 | 0/2 (0%) | 0/2 (0%) |

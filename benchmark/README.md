# Planted-defect benchmark: 10 short mathematics papers

This folder holds a small benchmark for tools that read and formalize mathematics papers. It has ten short papers (2–3 pages each). Each paper contains **planted defects**: false lemmas, missing hypotheses, vacuous statements, misquoted citations, slips in proofs and similar errors. Each paper also contains one **decoy**, a passage that looks wrong but is correct. **Hidden answer keys** list every planted defect and the decoy, with a concrete witness for each.

All ten papers have fictional authors and affiliations. Their e-mail addresses use made-up or `example` domains. The bibliographies cite real classical sources (Hardy–Wright, Erdős–Gallai, Zsigmondy, Jacobson, Lang and others); only the planted misquotations of those sources are wrong.

## Contents

```
papers/benchN/paper.tex, paper.pdf    the ten papers (N = 1..10); this is all a tool may see
keys/benchN-key.md                    answer key for each paper (never give it to the tool)
keys/KEY-CHECK-bench1-5.md            independent check of the bench1–5 keys
keys/KEY-CHECK-bench6-10.md           independent check of the bench6–10 keys
keys/KEY-SPOTCHECK.md                 hand check of 12 key entries by X. Tang
keys/bench7-verify.py                 the bench7 writer's verification script (cited in its key)
writing/WRITER-BRIEF.md               the brief given to the bench6–10 writer agents
scores/                               scores of past runs of formalize-paper (see Results)
```

| Paper | Topic | Goal theorem | Defects | Pages |
|---|---|---|---|---|
| bench1 | Polite numbers (sums of consecutive integers) | Thm 2.6: n ≥ 1 is polite ⇔ n is not a power of 2 | 6 | 3 |
| bench2 | Degrees in finite simple graphs | Thm 2.6: n ≥ 2 vertices ⇒ two vertices have equal degree | 6 | 3 |
| bench3 | Sum–reciprocal / Cauchy–Schwarz inequalities | Thm 2.6: (Σxᵢ)(Σ1/xᵢ) ≥ n² for positive reals | 7 | 3 |
| bench4 | gcd of 2ⁿ − 1 | Thm 2.6: gcd(2ᵐ−1, 2ⁿ−1) = 2^gcd(m,n) − 1 for all m, n ∈ ℕ | 6 | 2 |
| bench5 | Divisibility in subsets of {1..2n} | Thm 2.5: A ⊆ [2n], \|A\| ≥ n+1 ⇒ distinct a, b ∈ A with a \| b | 6 | 2 |
| bench6 | Quadratic residues mod an odd prime | Thm 2.8: −1 is a QR mod p iff p ≡ 1 (mod 4) | 6 | 3 |
| bench7 | Nilpotent and idempotent real matrices | Thm 2.5: a nilpotent n×n matrix has Aⁿ = 0 | 6 | 3 |
| bench8 | The iteration x_{n+1} = √(2 + x_n) | Thm 2.8: x_n(a) → 2 for every a ≥ −2 | 6 | 3 |
| bench9 | Involutions in finite groups | Thm 2.8: a group of even order has an odd number of elements of order 2 | 6 | 3 |
| bench10 | Integer polynomials | Thm 2.9: rational roots of a monic integer polynomial are integers dividing P(0) | 6 | 3 |

In total there are 61 planted defects and 10 decoys. Every goal theorem is true as stated. No planted defect makes a goal false. Some defects sit on the goal's proof path, but in each case the goal still follows from the corrected version.

### Defects by type

| Type | bench1–5 | bench6–10 |
|---|---|---|
| Numbered lemma false as printed (intended version recoverable) | 3 | 2 |
| Missing hypothesis at an edge case (n = 0/1, x < 0, g = e …) | 3 | 3 |
| Vacuous statement (hypotheses cannot hold together) | 3 | 3 |
| Unused / unneeded hypothesis | 4 | 5 |
| Cited classical result stated more strongly than its source | 5 | 5 |
| Typo in a statement (bound, modulus, exponent, direction) | 4 | 3 |
| Slip inside a proof only (statement correct) | 5 | 5 |
| Definition clashing with its later use | 2 | 0 |
| ℕ starting at 0 vs 1 / off-by-one in a range | 2 | 4 |
| **Total** | **31** | **30** |

Each key lists, for every planted defect, an id, its location (result number and tex line), its type, what is wrong, a concrete witness, the intended version, and whether it affects the goal. It also gives the decoy with the reason it is correct, plus a few "not a defect" notes. Ids are `B1-1` … `B5-6` and `B7-k`, `B10-k`; the bench6, bench8 and bench9 keys use `BN-k`, so read those ids together with the paper number.

## How it was made

- **Writers.** AI agents wrote all ten papers and all ten keys. bench1–5 were written by one isolated agent (2026-10-24). bench6–10 were written by five isolated agents, one per paper (2026-10-28), from the brief in `writing/WRITER-BRIEF.md`. No writer had access to the formalization tool under test, its prompts or its audit records. The bench6–10 writers also had no access to bench1–5 or their keys. Each writer verified its defects, decoy and goal computationally (Python; exhaustive on small cases where possible).
- **Independent key check.** For each half of the benchmark, a separate checker agent read every paper and key and re-verified every key entry with its own scripts (the bench6–10 checker formed its own view of each paper before opening its key). Result: 61/61 defects confirmed, 10/10 decoys correct, 10/10 goals true, and no unplanted defects of substance (`keys/KEY-CHECK-bench1-5.md`, `keys/KEY-CHECK-bench6-10.md`). One wording fix suggested by the checker was applied to the bench8 key (BN-3: the proof is valid; only the hypotheses are unsatisfiable).
- **Hand check.** X. Tang checked 12 key entries by hand (10 defects across all ten papers and 2 decoys): 12 of 12 OK (`keys/KEY-SPOTCHECK.md`).

## How to use it

1. Give the tool **only** `papers/benchN/paper.tex` and/or `papers/benchN/paper.pdf`. Never give it the keys, the key checks, the writer brief or the scores, and do not run it in a directory that contains them.
2. Let the tool finish and deliver its report.
3. Only then open `keys/benchN-key.md` and score the delivered report against it, item by item, using the rules below.

## Scoring rules

Score each key item by what reaches the delivered report.

| Code | Meaning |
|---|---|
| **FOUND** | Recorded as a defect, proof slip or vacuity, with a witness or argument, matching the key's item. |
| **NOTED** | The same fact appears in the delivered report, but the tool filed it as "not a defect", a reading choice or a citation note. |
| **LATE** | Found only in the closing summary, never in the tool's defect record. |
| **MISSED** | Nothing in the delivered report. |
| **FALSE ALARM** | A defect reported that the key and the key check say is not one. |

- **Decoys.** A decoy *passes* if the tool does not report it as a defect. Reporting it is a FALSE ALARM.
- **Vacuous statements** (B2-3, B3-5, B4-4, B7-3, bench8 BN-3, B10-5) are true statements, mostly with valid proofs. Count a hit only if the report says the hypotheses cannot all hold, not if it calls the item false.
- **Unneeded hypotheses** (B1-5, B3-2, B4-2, B5-1, bench6 BN-1, B7-5, bench8 BN-6, bench9 BN-2, B10-2) make true statements that are weaker than they could be. They are not errors. The scorings below therefore also give a count that leaves them out of the denominator ("key-check rule").
- **Proof-only slips** do not change any statement, so a tool that checks only statements cannot see them. They show up only through a careful reading of the proof text.

Some score files in `scores/` use an older code set: **CAUGHT / PARTIAL / MISSED**, with a "strict variant". There, CAUGHT means the right fact reached the delivered documents; in the strict variant a defect reported with the right facts but labelled "not a defect" or "reading choice" counts as PARTIAL. So strict CAUGHT corresponds to FOUND, strict PARTIAL to NOTED, and normal CAUGHT to FOUND + NOTED.

## Results

All runs below used formalize-paper in hands-off mode, where the agent takes the decisions and no human reviews the Lean statements. In every run, every decoy passed and there were no false alarms. Full evidence for each verdict is in the score file.

| Paper | formalize-paper version | Result | Score file |
|---|---|---|---|
| bench1 | 0.3.0-dev (5fcd619) | 5 caught, 1 missed (B1-1); strict 4 / 1 / 1 | `scores/bench1-SCORE.md` |
| bench1 | 0.3.0 (92bd3d4) | 6 caught; strict 5 / 1 / 0 | `scores/bench1-SCORE-0.3.0.md` |
| bench1 | **0.3.0 public release (9f2c1d3)** | 5 caught, 1 missed (B1-5, found during the run but not delivered); strict 5 / 0 / 1 | `scores/bench1-SCORE-b1v.md` |
| bench2 | 0.3.0-dev (5fcd619) | 6 caught; strict 6 / 0 / 0 | `scores/bench2-SCORE.md` |
| bench2 | **0.3.0 public release (9f2c1d3)** | 5 caught, 1 missed (B2-2, proof slip); strict 5 / 0 / 1 | `scores/bench2-SCORE-b2v.md` |
| bench3 | 0.3.0 | 5 FOUND, 2 NOTED (B3-2, B3-7) | `scores/bench3-10-scoring-combined.md` (X. Tang); also `scores/bench3-5-SCORE-0.3.0.md` |
| bench3 | **0.3.0 public release (9f2c1d3)** | 7 caught; strict 4 / 3 / 0 | `scores/bench3-SCORE-b3v.md` |
| bench4 | 0.3.0 | 4 FOUND, 2 NOTED (B4-2, B4-6); the run did not deliver | `scores/bench3-10-scoring-combined.md`; also `scores/bench3-5-SCORE-0.3.0.md` |
| bench4 | 0.3.0 public release (9f2c1d3) | in progress | — |
| bench5 | 0.3.0 | 3 FOUND, 3 NOTED (B5-1, B5-4, B5-6) | `scores/bench3-10-scoring-combined.md`; also `scores/bench3-5-SCORE-0.3.0.md` |
| bench5 | 0.3.0 public release (9f2c1d3) | in progress | — |
| bench6 | main branch (c0670f3) | 5 FOUND, 1 NOTED (BN-1) | `scores/bench3-10-scoring-combined.md` |
| bench7 | main branch (c0670f3) | 4 FOUND, 1 NOTED (B7-5), 1 MISSED (B7-1, proof slip) | `scores/bench3-10-scoring-combined.md` |
| bench8 | main branch (c0670f3) | 3 FOUND, 2 NOTED (BN-4, BN-6), 1 MISSED (BN-2, proof slip) | `scores/bench3-10-scoring-combined.md` |
| bench9 | main branch (c0670f3) | 5 FOUND, 1 NOTED (BN-2) | `scores/bench3-10-scoring-combined.md` |
| bench10 | main branch (c0670f3) | 5 FOUND, 1 NOTED (B10-2) | `scores/bench3-10-scoring-combined.md` |

"Strict a / b / c" means a CAUGHT, b PARTIAL, c MISSED under the strict variant. Bold rows are runs on the current public release.

**X. Tang's scoring of bench3–10** (eight runs, 49 planted defects): 34 FOUND, 13 NOTED, 0 LATE, 2 MISSED, 0 FALSE ALARM; 8/8 decoys passed. That is 34/49 strict and 47/49 documented (FOUND + NOTED). Under the key-check rule (the 8 unneeded-hypothesis items left out) it is 34/41 FOUND and 39/41 documented. Both misses are slips inside the proof of a true lemma that the Lean proof established by a different route.

The bench3–5 runs on 0.3.0 were also scored independently in `scores/bench3-5-SCORE-0.3.0.md` (19 caught, strict 13 / 6 / 0). The two scorings differ on one item, B4-6, which that file counts as caught and X. Tang's files as NOTED.

The earlier score files are included because the current-release score files compare against them. Each score file also records run details (stops, wall-clock time, how each defect was found); paths in them such as `D/SUMMARY.md` and `A/PAPER_DEFECTS.md` refer to the run's own deliverables and audit records, which are not published here.

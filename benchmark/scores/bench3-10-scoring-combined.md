# Benchmark scoring, bench3–10 (combined)

Three scoring files concatenated for review (revised 2026-10-29 evening: unified labelling rule, B4-6/B5-4/B5-6 relabelled NOTED, replay module counts added). Verdict codes: FOUND / NOTED / LATE / MISSED / FALSE ALARM. Overall totals for all eight runs are at the end.

---

# bench3–5: tool findings scored against the answer keys

Scorer: X. Tang (first pass drafted 2026-10-29 from the scorer's own findings notes, the delivered REPORT.md / PAPER_DEFECTS.md / VACUOUS.md of each run, and `keys/bench{3,4,5}-key.md` with `keys/KEY-CHECK-bench1-5.md`). Keys were opened only after all three runs had finished, on a separate machine, never on the run machines.

Verdict codes
- **FOUND**: recorded as a defect, proof slip or vacuity with a Lean witness or argument, matching the key's item.
- **NOTED**: the same fact appears in the delivered report, but filed as "not a defect" (the tool's rule: a superfluous hypothesis is not a defect) or as a reading choice.
- **LATE**: found only in the closing summary, never recorded in PAPER_DEFECTS.md.
- **MISSED**: nothing in the records.
- **FALSE ALARM**: a defect reported that the key and KEY-CHECK say is not one.

## bench3 — "A sum–reciprocal inequality and two applications"

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| B3-1 | Lem 2.3: x ≠ 0 should be x > 0 | PAPER_DEFECTS row: false as printed, witness x = −1, repair x > 0 | FOUND |
| B3-2 | Lem 2.5: hypothesis x_i ≥ 0 unneeded | REPORT.md l.117, l.122: "not needed mathematically … a property of the statements, not a defect"; kept as printed, docstring says unused | NOTED |
| B3-3 | Proof of Lem 2.5: b_i = x_i should be b_i = 1 | PAPER_DEFECTS slip; Lean proof uses b_i = 1 (DEVIATIONS row 2) | FOUND |
| B3-4 | Def 2.1 "harmonic mean" is the mean of reciprocals; Cor 2.7 false literally | PAPER_DEFECTS row: Cor 2.7 false as printed, witness n = 1, x = 1/2, cause traced to Def 2.1 | FOUND |
| B3-5 | Cor 2.8 vacuous | VACUOUS.md row 1, `cor_2_8_hyps_unsat` proved | FOUND |
| B3-6 | Bernoulli quoted for all real x; needs x ≥ −1 | PAPER_DEFECTS slip, witness n = 3, x = −4 (recorded although the text is unnumbered) | FOUND |
| B3-7 | Prop 3.1 at n = 0 (1/n undefined); needs n ≥ 1 | REPORT.md l.120, l.131, l.142: refuted in Lean at n = 0, Lean states n ≥ 1, report suggests the paper add "n ≥ 1" | NOTED (reading choice, repaired) |
| decoy | Nesbitt proof (Prop 2.9) | proved, nothing flagged | passed |

Extra tool items not in the key: Lemmas 2.2 and 2.4 are one-step Mathlib facts (observation); n ≥ 1 unused in Lemmas 2.4, 2.5 (key: harmless). No false alarm.

## bench4 — "Greatest common divisors of the numbers 2ⁿ − 1"

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| B4-1 | Lem 2.3: a_0 = 0 is even; needs n ≥ 1 | PAPER_DEFECTS row: false as printed, repair n ≥ 1 (this repair is what the delivery gate refused as RED[adj-record]) | FOUND |
| B4-2 | Lem 2.4: m ≤ n (and m ≥ 1) redundant | PAPER_DEFECTS l.31: "1 ≤ m ≤ n … not used by the proofs … a superfluous hypothesis is not a defect" | NOTED |
| B4-3 | Proof of Lem 2.5: 2^m should be 2^n | PAPER_DEFECTS slip | FOUND |
| B4-4 | Prop 2.8 vacuous | VACUOUS.md row, argument via Thm 2.6 | FOUND |
| B4-5 | Prop 3.2: mod 4p should be mod 2p | PAPER_DEFECTS row, witness p = 3, q = 7 (KEY-CHECK calls this the simpler witness) | FOUND |
| B4-6 | Remark: Zsigmondy without the n = 6 exception | SUMMARY.md l.34 ("an error in an unformalized remark", a₆ = 63 = 3²·7), REPORT.md l.119 and CITATIONS.md C1 (found by the citation check against Zsigmondy 1892); PAPER_DEFECTS l.36 files the remark as out of scope, "not a defect" | NOTED |
| decoy | Cor 2.7 at m = n = 0 | proved, nothing flagged | passed |

Extra tool items: proof of Lem 2.5 uses "a_n odd" at n = 0 (a consequence of B4-1; the key's B4-1 note says the same, so not a false alarm); Prop 3.1 already in Mathlib; Conj 3.3 stated as an unasserted Prop; m, n ≥ 1 unused in Prop 2.8. No false alarm.

## bench5 — "Divisibility and coprimality in large subsets of {1,…,2n}"

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| B5-1 | Lem 2.2: k ≥ 1 unneeded | REPORT.md l.111: "an unneeded hypothesis is not a defect"; six decisions keep it as printed | NOTED |
| B5-2 | Prop 2.3: |A| ≥ n should be ≥ n + 1 | PAPER_DEFECTS row 1, witnesses n = 1, A = {2} and {2, 4, …, 2n}; repair n + 1 | FOUND |
| B5-3 | Proof of Thm 2.5: b | a should be a | b | PAPER_DEFECTS slip | FOUND |
| B5-4 | Def 2.1 antichain without "distinct"; Prop 3.1 false literally | recorded as a reading choice with a deviation: literal reading makes no nonempty antichain and Prop 3.1 false; Lean takes "distinct" | NOTED (reading choice) |
| B5-5 | Lem 3.3 "every element even" false; "maximality" unstated | PAPER_DEFECTS row 2, witnesses n = 1, {1} and n = 3, {3, 6}; Lean drops the clause | FOUND |
| B5-6 | Remark: Erdős–Szekeres with n² instead of n² + 1 | citation note in the report (CITATIONS C1, with the block counterexample); SUMMARY files it under "not a defect" | NOTED |
| decoy | Prop 3.2 at n = 1 | proved, nothing flagged | passed |

Extra tool items: n ≥ 1 hypotheses unneeded (key: harmless). No false alarm.

## Totals

| | planted | FOUND | NOTED | LATE | MISSED | FALSE ALARM | decoy passed |
|---|---|---|---|---|---|---|---|
| bench3 | 7 | 5 | 2 (B3-2, B3-7) | 0 | 0 | 0 | 1/1 |
| bench4 | 6 | 4 | 2 (B4-2, B4-6) | 0 | 0 | 0 | 1/1 |
| bench5 | 6 | 3 | 3 (B5-1, B5-4, B5-6) | 0 | 0 | 0 | 1/1 |
| all | 19 | 12 | 7 | 0 | 0 | 0 | 3/3 |

Labelling rule (unified on 2026-10-29 after cross-checking the second scorer's independent score): whatever the tool filed as "not a defect", a reading choice or a citation note is NOTED, even when the fact and witness are complete. Three ways to count:
1. **Strict** (only FOUND counts): 12/19.
2. **Lenient** (FOUND + NOTED, the fact is in the delivered text): 19/19.
3. **KEY-CHECK's rule** (its closing remark: the unneeded-hypothesis items B3-2, B4-2, B5-1 "are not errors, so a tool that does not flag them is not missing anything false"; drop them from the denominator): 16/16 documented, of which 12 FOUND and 4 NOTED (B3-7, B4-6, B5-4, B5-6). The second scorer's own score of these three runs (`bench3-5-SCORE-0.3.0.md`) is 19 caught, strict 13/6/0; the one-item difference is B4-6, which he counts as caught and this table files as NOTED because the run itself said "not counted as a defect".

Two boundary observations worth a sentence in the report:
- The tool's rule "a superfluous hypothesis is not a defect" is applied consistently in all three runs, and in each case the fact itself is still printed in the report with the hypothesis marked unused. So the three NOTED hypothesis items are a classification choice, not a detection failure.
- B4-6 (an unnumbered remark, outside the Checkpoint A scope) was still found, by the citation check, and reported in the summary, report and citation notes; only the defect record leaves it out, by the scope rule.

---

# bench6–7: tool findings scored against the answer keys

Scorer: X. Tang, 2026-10-29. Sources: each run's delivered REPORT.md and audits PAPER_DEFECTS.md / VACUOUS.md (formalize-paper main c0670f3, hands-off, light budget), against `keys/bench{6,7}-key.md`. Keys were opened only after both runs had delivered. Verdict codes as in bench3-5-scoring.md: FOUND / NOTED (same fact in the report, filed as "not a defect") / LATE / MISSED / FALSE ALARM.

Kernel replay: bench6 3/3 modules OK, bench7 3/3 modules OK (a kernel-replay log in each run's project). No stop after Checkpoint A in either run.

## bench6 — "A short self-contained route to the first supplementary law" (first-supplementary)

Goal Theorem 2.8 proved as printed.

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| BN-1 | Lem 2.2: hypothesis p ∤ x unused | REPORT.md row for Lemma 2.2: "its hypotheses p ≠ 2 and p ∤ x are not used by the proof"; PAPER_DEFECTS "Not defects": "a stronger true statement is not a defect" | NOTED |
| BN-2 | Prop 2.3: range (p+1)/2 should be (p−1)/2 | PAPER_DEFECTS row 1, false, typo, witness p = 3, `not_prop_2_3_as_printed` | FOUND |
| BN-3 | Cor 2.4 fails at p = 3 | PAPER_DEFECTS row 2, false, add hypothesis p ≠ 3, witness p = 3 | FOUND |
| BN-4 | Lem 2.6: exponent (p+1)/2 should be (p−1)/2 | PAPER_DEFECTS row 3, false, typo, witness p = 5, a = 2 | FOUND |
| BN-5 | Proof of Prop 3.2: sign (−1)^((p+1)/2) and parity claim | PAPER_DEFECTS "Slips": exactly this, with the p = 5 check | FOUND |
| BN-6 | Thm 3.3: uniqueness claimed for composite n | PAPER_DEFECTS row 4, false, witness n = 65 = 1² + 8² = 4² + 7²; repaired to n prime, with a question to the author on the intended statement | FOUND |
| decoy | Thm 2.7 (Euler's criterion for every integer a) | proved as printed, nothing flagged | passed |

Extras not in the key (none a false alarm): p ≠ 2 unused in Lemmas 2.2, 2.5 and Theorem 3.1; n > 1 unused in the corrected Theorem 3.3; the repair of Theorem 3.3 to "n prime" noted as weaker than possible (prime squares also qualify).

## bench7 — "A short note on nilpotent and idempotent real matrices" (nilpotent-idempotent)

Goal Theorem 2.5 proved as printed.

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| B7-1 | Proof of Lem 2.3: "A^k(Ax) = 0 hence A^k x = 0" (should be A^{k+1}x = 0) | Lemma 2.3 "proved as printed"; PAPER_DEFECTS "Slips in the proofs: None found"; no mention in REPORT, DECISIONS or JUDGEMENT | MISSED |
| B7-2 | Lem 2.4: range k ≤ ν should be k < ν | PAPER_DEFECTS row 1, false, witness A = 0 ∈ M_1, repaired to k < ν(A) | FOUND |
| B7-3 | Prop 2.6 vacuous (N^ν x ≠ 0 impossible) | PAPER_DEFECTS row 4 and VACUOUS.md row 1, with the N^{ν−1} x ≠ 0 guess as a question to the author | FOUND |
| B7-4 | Lem 2.7: ν(A+B) ≤ max is false; bound ν(A)+ν(B)−1 | PAPER_DEFECTS row 2, false, witness E⊗I, I⊗E in M_4, repaired to ν(A)+ν(B)−1 | FOUND |
| B7-5 | Prop 2.8: symmetry hypothesis unneeded | PAPER_DEFECTS "Not defects": "Pᵀ = P is not needed … a superfluous hypothesis is not a defect" | NOTED |
| B7-6 | Thm 3.1 (Jacobson): "in fact C² = 0" not in the source and false | PAPER_DEFECTS row 3, false, witness J₃ and diag(0,1,2); `JacobsonHyp` drops the clause | FOUND |
| decoy | Cor 3.2 | proved assuming JacobsonHyp (the true part of Jacobson's lemma), nothing flagged | passed |

Extras not in the key: the standing n ≥ 1 unused in several results (not a false alarm). The slip in the proof of Lemma 2.7 (tex l.134) is subsumed in defect row 2, as the key also does.

## Totals

| | planted | FOUND | NOTED | LATE | MISSED | FALSE ALARM | decoy passed |
|---|---|---|---|---|---|---|---|
| bench6 | 6 | 5 | 1 (BN-1) | 0 | 0 | 0 | 1/1 |
| bench7 | 6 | 4 | 1 (B7-5) | 0 | 1 (B7-1) | 0 | 1/1 |
| both | 12 | 9 | 2 | 0 | 1 | 0 | 2/2 |

Counts: strict 9/12; lenient 11/12; KEY-CHECK's rule (unneeded-hypothesis items out of the denominator) 9/10, with B7-1 the one genuine miss.

Note on the miss: B7-1 is a slip inside the proof of a true lemma, in a step the Lean proof does not follow (the Lean proves Lemma 2.3 by its own route). The tool reports proof slips only when a lane reads the paper's proof text closely; here none did. This is the first planted item missed outright across bench3–7 (31 planted items).

---

# bench8–10: tool findings scored against the answer keys

Scorer: X. Tang, 2026-10-29. Sources: each run's delivered REPORT.md and audits PAPER_DEFECTS.md / VACUOUS.md (formalize-paper main c0670f3, hands-off, light budget), against `keys/bench{8,9,10}-key.md`. Keys were opened only after the runs had delivered. Verdict codes as before: FOUND / NOTED (same fact in the report, filed as "not a defect" or a reading choice) / LATE / MISSED / FALSE ALARM.

Kernel replay: 0 FAILED in all three (a kernel-replay log in each run's project). No stop after Checkpoint A in any of the three runs.

## bench8 — "A note on the nested radical iteration" (oduya-nested-radical)

Goal Theorem 2.8 proved as printed.

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| BN-1 | Lem 2.3: constant 1/4 should be 1/2 | PAPER_DEFECTS row 1, false, typo, witness x = −2; Lean proves the 1/2 version | FOUND |
| BN-2 | Proof of Lem 2.4: squaring step wrong for x < 0 | Lemma 2.4 "proved as printed (both parts)"; "Slips in the proofs: None found"; no mention anywhere | MISSED |
| BN-3 | Lem 2.7 vacuous | PAPER_DEFECTS row 3 and VACUOUS.md row 1 | FOUND |
| BN-4 | Def 3.1: sum of N+1 terms called the mean of N terms | PAPER_DEFECTS "Not defects": prose and formula disagree, recorded as reading choice (a), "a definition is neither true nor false"; every dependent result has the same truth value under both readings | NOTED |
| BN-5 | Thm 3.2: "if and only if" where Cauchy gives one direction | PAPER_DEFECTS row 2, false, witness (−1)^n; forward direction proved | FOUND |
| BN-6 | Cor 3.3: 0 ≤ a ≤ 2 unneeded | PAPER_DEFECTS "Not defects": "more than its proof needs … not wrong" | NOTED |
| decoy | Lem 2.2 (fixed point) | proved as printed, nothing flagged | passed |

No false alarm. Extra tool items: Cor 2.5(2)'s redundant hypothesis; the Lean's total sqrt and σ_0 = 0 conventions (formalization notes).

## bench9 — "Involutions in groups of even order" (oyelaran-involutions)

Goal Theorem 2.8 proved as printed.

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| BN-1 | Lem 2.2: divisibility reversed | PAPER_DEFECTS row 1, false, typo, witness trivial group, m = 2 | FOUND |
| BN-2 | Lem 2.3: "abelian" unneeded | PAPER_DEFECTS "Not defects": "a superfluous hypothesis is not a defect"; the Lean keeps CommGroup, proof does not use it | NOTED |
| BN-3 | Lem 2.5 fails at g = e | PAPER_DEFECTS row 2, false, add hypothesis g ≠ e | FOUND |
| BN-4 | Proof of Lem 2.6: |X| = |Fix σ| + m should be + 2m | PAPER_DEFECTS "Slips": exactly this | FOUND |
| BN-5 | Cor 2.7: "at least two fixed points" false | PAPER_DEFECTS row 3, false, witness the swap on {a, b} | FOUND |
| BN-6 | Thm 3.3 (Frobenius) without n ∣ |G| | PAPER_DEFECTS row 4, false, witness trivial group, n = 2 | FOUND |
| decoy | Prop 3.2 (exponent 2 ⇒ abelian, 2-power) | proved as printed, nothing flagged | passed |

No false alarm. Extra tool items: finiteness idle in Lemma 2.4 (formalization note).

## bench10 — "Divisibility and rational roots of integer polynomials" (rational-roots)

Goal Theorem 2.9 proved as printed.

| Key id | Key item | Tool record | Verdict |
|---|---|---|---|
| B10-1 | Proof of Lem 2.2: exponents sum to k | PAPER_DEFECTS "Slips": exactly this, with the k = 1 check | FOUND |
| B10-2 | Cor 2.3: "monic" unneeded | PAPER_DEFECTS "Not defects": "redundant, not wrong" | NOTED |
| B10-3 | Lem 2.4: residue 0 omitted | PAPER_DEFECTS row 1, false, add hypothesis, witness P = x, m = 2; a second slip recorded in the proof of Cor 3.3 as a consequence | FOUND |
| B10-4 | Lem 2.6: |r| ≤ |a₀| fails at a₀ = 0 | PAPER_DEFECTS row 2, false, witness x² − 5x, r = 5 | FOUND |
| B10-5 | Prop 2.7 vacuous (no 3-cycle) | PAPER_DEFECTS row 4 and VACUOUS.md row 1, `prop_2_7_hyps_unsat` proved | FOUND |
| B10-6 | Thm 3.1 (Eisenstein) concluding in ℤ[x] | PAPER_DEFECTS row 3, false, witness 2x + 6, p = 3 | FOUND |
| decoy | Lem 2.5 (no a ≠ b hypothesis) | proved as printed, nothing flagged | passed |

No false alarm. Extra tool items: the standing P ≠ 0 and m ≥ 1, n ≥ 1 hypotheses unused in places (formalization notes).

## Totals, bench8–10

| | planted | FOUND | NOTED | LATE | MISSED | FALSE ALARM | decoy passed |
|---|---|---|---|---|---|---|---|
| bench8 | 6 | 3 | 2 (BN-4, BN-6) | 0 | 1 (BN-2) | 0 | 1/1 |
| bench9 | 6 | 5 | 1 (BN-2) | 0 | 0 | 0 | 1/1 |
| bench10 | 6 | 5 | 1 (B10-2) | 0 | 0 | 0 | 1/1 |
| all | 18 | 13 | 4 | 0 | 1 | 0 | 3/3 |

Counts: strict 13/18; lenient 17/18; KEY-CHECK's rule (the three unneeded-hypothesis items BN-6, BN-2 of bench9, B10-2 out of the denominator; bench8's Def 3.1 item stays in as NOTED) 13/15 with one NOTED and one MISSED.

## Totals, bench3–10 (eight runs, all on 0.3.0 or main c0670f3, hands-off)

| | planted | FOUND | NOTED | LATE | MISSED | FALSE ALARM | decoys passed |
|---|---|---|---|---|---|---|---|
| bench3–5 | 19 | 12 | 7 | 0 | 0 | 0 | 3/3 |
| bench6–7 | 12 | 9 | 2 | 0 | 1 | 0 | 2/2 |
| bench8–10 | 18 | 13 | 4 | 0 | 1 | 0 | 3/3 |
| all | 49 | 34 | 13 | 0 | 2 | 0 | 8/8 |

Labelling rule (unified 2026-10-29): whatever the tool filed as "not a defect", a reading choice or a citation note is NOTED, even when the fact and witness are complete. Of the 13 NOTED items, 8 are unneeded hypotheses (the tool's rule "a superfluous hypothesis is not a defect", applied in every run, with the fact itself always printed in the report), 2 are reading choices (bench3 Prop 3.1 at n = 0, repaired in Lean; bench5 Def 2.1 "distinct"), 1 is a definition whose prose and formula disagree (bench8 Def 3.1), and 2 are citation notes on unnumbered remarks (bench4 Zsigmondy at n = 6, bench5 Erdős–Szekeres), both reported in the summary and citation notes but kept out of the defect record by the scope rule. The 2 MISSED items are both slips inside the proof of a true lemma that the Lean proved by another route (bench7 Lemma 2.3, bench8 Lemma 2.4). No false alarm in 49 items, and all 8 decoys passed.

Counting rules over all 49: strict 34/49 (69%); documented (FOUND + NOTED) 47/49 (96%); KEY-CHECK's rule, dropping the 8 unneeded-hypothesis items: 34/41 FOUND (83%), 39/41 documented (95.1%), 2/41 missed.

Kernel replay, module by module, all OK: bench3 5, bench4 3, bench5 6, bench6 3, bench7 3, bench8 5, bench9 3, bench10 6. Cross-check: the second scorer's independent score of bench6 and bench7 (not included here) agrees row by row: 11/12, B7-1 missed, BN-1 and B7-5 partial, no false alarm.
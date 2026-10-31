I scored the three runs bench3, bench4 and bench5 (formalize-paper 0.3.0, hands-off, release mode) against `keys/bench{3,4,5}-key.md` and `keys/KEY-CHECK-bench1-5.md`, using the rules in `scores/bench1-SCORE-0.3.0.md`. That includes its strict variant: a defect reported with the right facts but labelled "not a defect" or "reading choice" counts as mislabelled, so PARTIAL. I modified nothing. I did not rebuild the Lean or replay it in the kernel. I only grepped the sources: there is no `sorry`, `native_decide` or `axiom`, and I read the goal statements by hand. The runs' own Phase 0 reports standard axioms only.

**Headline:** across the 19 planted defects of papers 3–5, the result is 19 caught / 0 partial / 0 missed (strict: 13 / 6 / 0). There were 0 false alarms on the decoys and 0 false positives. All three goal theorems are proved. bench3 and bench5 delivered; bench4 did not.

**A pause in all three runs.** All three runs show the same ~14.5 h break in their commits, from about 09:15 to about 23:50 on 2026-10-27. Its cause is not in the records I read. "Active" below is the wall clock minus that gap.

## bench3 — "A sum–reciprocal inequality" (`audits/instance-sumrecip/`)

| Id | Verdict | Evidence |
|---|---|---|
| B3-1: x+1/x ≥ 2 for x ≠ 0 (Lem 2.3) | CAUGHT | PAPER_DEFECTS row 1: false, repaired with x > 0, x = −1 refuted in Lean (`not_lem_2_3_as_printed`). |
| B3-2: unneeded x_i ≥ 0 (Lem 2.5) | CAUGHT (strict PARTIAL) | Right fact, but placed under "Not defects" (an unneeded hypothesis is "not a defect"). Also listed as an unused hypothesis in SUMMARY. |
| B3-3: b_i = x_i slip (proof of Lem 2.5) | CAUGHT | Proof slip 1, should read b_i = 1. DEVIATIONS row 2. |
| B3-4: Def 2.1 "harmonic mean" vs Cor 2.7 | CAUGHT | Row 2: Cor 2.7 false as printed (n = 1, x = 1/2), refuted in Lean. Notes that the defect could equally be placed in Def 2.1. |
| B3-5: vacuous Cor 2.8 | CAUGHT | Row 3 and VACUOUS 1. Witness lemma `cor_2_8_hyps_unsat`. |
| B3-6: Bernoulli for all real x | CAUGHT | Proof slip 2 (x = −4, n = 3). Also in CITATIONS item 2 (the HLP book could not be accessed). |
| B3-7: ℕ ∋ 0 in Prop 3.1 | CAUGHT (strict PARTIAL) | Treated as a reading choice (DEVIATIONS row 4, proved for n ≥ 1). The early Lean refutation at n = 0 was relabelled "encoding error, not a defect". "Sending to authors" still asks for an "n ≥ 1" clarification and notes that the paper uses 0 ∈ ℕ. |
| Decoy: Nesbitt proof | correctly not reported | Prop 2.9 is listed as faithful. |
| Other false positives | none | CITATIONS also says the Nesbitt reference seems to be the 1903 reprint volume, first posed in 1902. This is advisory and bibliographic, not a mathematical claim; the key check could not verify the reference, and neither could I. Not counted. |
| Goal Thm 2.6 | proved, faithful | `SumRecip.thm_2_6` (Section2.lean:74) matches the paper. |

- **Delivered:** yes, at 2026-10-28 07:56.
- **Stop S1 (tool bug, self-cured):** `result_status.py` did not recognise the answers to reviewer questions on Lemmas 2.2 and 2.4, because the readings were numbered ("reading 1") rather than lettered. Tool patch TP1 was applied on attempt 16, after 15 rejected reviews, and one more full round followed. No human wait.
- **Wall clock:** 2026-10-27 05:01 to 2026-10-28 07:56, so 26 h 55. Active about 12 h 10.

## bench4 — "gcd of 2ⁿ − 1" (`audits/specimen-gcd/`; there is no `deliverables/` folder)

| Id | Verdict | Evidence |
|---|---|---|
| B4-1: a_n odd for n ∈ ℕ (Lem 2.3) | CAUGHT | Row 1: false at n = 0, repaired with n ≥ 1, refuted in Lean. Proof slip 2 (the use in Lemma 2.5 at n = 0). |
| B4-2: redundant 1 ≤ m ≤ n (Lem 2.4) | CAUGHT (strict PARTIAL) | Under "Not defects": "m ∣ n alone gives a_m ∣ a_n". The hypotheses are kept. |
| B4-3: 2^m vs 2^n slip (proof of Lem 2.5) | CAUGHT | Proof slip 1, exact. |
| B4-4: vacuous Prop 2.8 | CAUGHT | Row 3, plus Lean probes showing the hypotheses cannot hold together. |
| B4-5: mod 4p (Prop 3.2) | CAUGHT | Row 2: typo for 2p, counterexample p = 3, q = 7, refuted in Lean. |
| B4-6: Zsigmondy without n = 6 | CAUGHT | SUMMARY "an error in an unformalized remark" (a_6 = 63), REPORT §5 and CITATIONS C1 (checked against the 1892 source). |
| Decoy: Cor 2.7 at m = n = 0 | correctly not reported | Cor 2.7 is listed as faithful. |
| Other false positives | none | SUMMARY adds that the proof of Prop 3.2 also uses Lemma 2.3 ("a_p is odd", tex l.135). That is correct. |
| Goal Thm 2.6 | proved, "faithful under a reading choice" | `theorem_2_6` (Main.lean:80) is exact and is proved by the paper's induction. |

- **Delivered: NO.** `project.py --deliver` was refused at 2026-10-28 13:34 (RED[adj-record], RED[deliver]). SUMMARY says "Not delivered … these documents are given to you as they stand." Two reader gates did not pass (report and decisions).
- **Stop S1 (tool bug, waited for a human):** `result_status.py` treats the documented repair hypothesis `lemma_2_3:hn` as an unsettled assumption. TP1 was rejected 8 times. The stop opened 2026-10-27 23:55 and was closed 2026-10-28 08:52 by the human's ruling: do not patch, disclose, deliver what exists. Most of that span, about 5 h 30 (03:20 to 08:52), was spent waiting for the ruling.
- **Wall clock:** 2026-10-27 05:12 to 2026-10-28 13:34, so 32 h 22. Active about 17 h 50. That includes about 5 h 30 of waiting for the human, and a further 4 h 02 commit gap after the ruling (08:52 to 12:54) whose cause I did not establish.

## bench5 — "Divisibility in subsets of [2n]" (`audits/divisibility2n/`)

| Id | Verdict | Evidence |
|---|---|---|
| B5-1: unneeded k ≥ 1 (Lem 2.2) | CAUGHT (strict PARTIAL) | "Not a defect 2: k ≥ 1 is not needed (gcd(0,1) = 1)". |
| B5-2: \|A\| ≥ n (Prop 2.3) | CAUGHT | Row 1: false, typo for n + 1, counterexamples n = 1, A = {2} and {2, 4, …, 2n}. |
| B5-3: "b ∣ a" slip (proof of Thm 2.5) | CAUGHT | Proof slip 1, exact. |
| B5-4: antichain definition without a ≠ b | CAUGHT (strict PARTIAL) | Handled as a reading choice ("distinct"). The literal definition is in the Lean, with `not_isDivAntichain_literal` proving Prop 3.1 false under it. SUMMARY explains how to reverse the choice. Listed as "not a defect 4". |
| B5-5: Lemma 3.3 "all even" | CAUGHT | Row 2: false (n = 1, {1}; n = 3, {3, 6}). The Lean keeps only \|A\| ≤ n. |
| B5-6: Erdős–Szekeres with n² | CAUGHT (strict PARTIAL) | CITATIONS C1 compares with the 1935 source and gives the block counterexample. In SUMMARY it appears under "not a defect 3" ("authors should check it"). |
| Decoy: Prop 3.2 at n = 1 | correctly not reported | Listed as "faithful under a reading choice"; its status comes from the Def 2.1 reading, not from any defect. |
| Other false positives | none | |
| Goal Thm 2.5 | proved, "faithful under a reading choice" | `theorem_2_5` (Section2.lean:94) matches the paper. The reading label comes only from Def 2.1 being treated as one unit; the goal does not use the antichain notion. |

- **Delivered:** yes, at 2026-10-28 02:51.
- **Stop S1 (tool bug, self-cured):** the same family of `result_status.py` bug. Lettered versus numbered readings again, and an answered question on a definition was not carried over to the results that use it. TP1 was approved on attempt 2, after 1 rejection.
- **Wall clock:** 2026-10-27 05:23 to 2026-10-28 02:51, so 21 h 28. Active about 7 h 06.
- **Minor inconsistency:** SUMMARY's "Stops" section does not list S1. The correction is mentioned only at the top of SUMMARY and in RUN_RECORD.

## Combined (papers 3–5 of the 31-defect benchmark: 19 planted defects, 3 decoys)

| Paper | Caught | Partial | Missed | Strict (C/P/M) | Decoy false alarm | Other false positives | Goal | Delivered | Stops |
|---|---|---|---|---|---|---|---|---|---|
| bench3 | 7 | 0 | 0 | 5/2/0 | no | 0 | proved | yes | 1 (tool bug, self-cured) |
| bench4 | 6 | 0 | 0 | 5/1/0 | no | 0 | proved | **no** | 1 (tool bug, waited for a human, ~5.5 h) |
| bench5 | 6 | 0 | 0 | 3/3/0 | no | 0 | proved | yes | 1 (tool bug, self-cured) |
| **Total** | **19** | **0** | **0** | **13/6/0** | **0/3** | **0** | 3/3 | 2/3 | 3, all tool bugs |

## Notes
- **Planted defects:** every one was found with correct facts and witnesses. The six strict PARTIALs are all labelling: unneeded hypotheses (B3-2, B4-2, B5-1), reading choices (B3-7, B5-4) and a citation issue outside the formalized scope (B5-6).
- **Proof slips:** all three planted slips (B3-3, B4-3, B5-3) were caught. Each had a paper-faithfulness lane's out-of-lane note and/or the author's notes as its source. The bench1 caveat still applies: no pass is dedicated to reading proofs.
- **Tooling:** all three stops come from the same pinned checker, `result_status.py` and how it parses which reading was kept. That checker is the main cost to wall clock and to delivery. It is also the reason bench4 was not delivered.
## Note on the ~14.5 h gap (confirmed 2026-10-29 by the person who ran these runs)
The common break on 2026-10-27, about 09:15 to 23:50, was a usage stop: the $200 API credit ran out in the morning, and the runs resumed only when the weekly subscription limit reset that night. It is account waiting, not tool or protocol time; report wall-clock both with and without it.

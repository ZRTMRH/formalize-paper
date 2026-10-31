# bench1 score, re-run on formalize-paper 0.3.0: "Polite numbers and odd divisors"

Run: bench1r. Hands-off, release mode, formalize-paper 0.3.0 (release 92bd3d4 per the run notes; the audits branch's install commit cf84ff0 is titled "install formalize-paper 0.3.0-dev"). Delivered 2026-10-27 06:49 with 0 stops.
Snapshot: a frozen copy of the run's repository (not published). Scored 2026-10-27 by an independent scorer against `keys/bench1-key.md` and `keys/KEY-CHECK-bench1-5.md`, using the same method as `scores/bench1-SCORE.md` (the older run, 5fcd619). The snapshot was not modified. The rebuild and kernel replay were done in a fresh clone.

**Score: 6 of 6 planted defects CAUGHT, 0 PARTIAL, 0 MISSED. The decoy was correctly not reported. 0 false positives.**
(Strict variant, as in the old score: if a defect reported with the right facts but labelled "not a defect" counts as mislabelled, B1-5 becomes PARTIAL and the score is 5 CAUGHT + 1 PARTIAL + 0 MISSED.)

Paths below are relative to the snapshot. `D/` = `deliverables/`; `A/` = `audits/polite-numbers/`.

## Comparison with the old score

| Id | Planted defect | Old (5fcd619, 0.3.0-dev) | New (bench1r, 0.3.0) | Change |
|---|---|---|---|---|
| B1-1 | Proof slip in Lemma 2.3 (2a+2k+1 should be 2a+2k−1) | MISSED | **CAUGHT** (proof slip 2) | gained |
| B1-2 | Prop 2.5 d ≥ 1 should be d > 1 (false) | CAUGHT | **CAUGHT** (defect 1, Lean refutation) | same |
| B1-3 | Cor 3.2 R* = d_odd should be d_odd − 1 (false) | CAUGHT | **CAUGHT** (defect 2, Lean refutation) | same |
| B1-4 | Lem 3.4 k ≥ 1 should be k ≥ 2 (false) | CAUGHT | **CAUGHT** (defect 3, Lean refutation) | same |
| B1-5 | Prop 3.5 p ≥ 5 stronger than needed | CAUGHT (strict: PARTIAL), under "Not defects" | **CAUGHT** (strict: PARTIAL), under "Not defects" | same |
| B1-6 | Bertrand quoted for n ≥ 1, n<p<2n (false at n=1) | CAUGHT, PAPER_DEFECTS row "misprint (true as intended)" | **CAUGHT**, as "proof slip 1", plus CITATIONS C1 | same verdict, different category (see note) |
| Decoy | Cor 3.3 R(2^j)=1 incl. j=0 | correctly not reported | correctly not reported | same |
| False positives | | 0 | 0 | same |
| **Total** | | **5 C / 0 P / 1 M** (strict 4/1/1) | **6 C / 0 P / 0 M** (strict 5/1/0) | +1 |
| Stops | | 3 (S1 false alarm, S2 tool bug, S3 self-cured); hand delivery | 0 stops, 0 self-cures, 0 disclosed faults, 0 tool patches | better |
| Wall clock | | 7 h 09 (≈ 2 h human waiting on tool stops) | 6 h 01 (00:48 → 06:49) | −1 h 08 |

## Per defect

| Id | Verdict | Where it reaches the reader | Nature as reported | Mechanism |
|---|---|---|---|---|
| B1-1 | **CAUGHT** | `D/SUMMARY.md:23` ("proof slip 2 — tex l.75 (the proof of Lemma 2.3) …"); `D/REPORT.md` §5, "Slips in the proofs", 2nd bullet (l.107); `A/PAPER_DEFECTS.md:27`; `D/DECISIONS.md:21`; REPORT "Sending these to the authors" gives the one-line repair. | Exact: "the text says … = 2a + 2k + 1 … The sum is 2a + 2k − 1 … still odd … the lemma's argument stands." Matches the key's fact, intended text and impact. | Not by a proof-reading pass. A substantiveness **re-vote** lane on `lemma_2_3`'s idle hypothesis `hk` noted it out of lane (`A/2026-10-27-full-ddacb20deda/revote/substantiveness--PoliteNumbers.lemma_2_3.json:24`). The adjudicator passed it on as a lead (`A/2026-10-27-full-ddacb20deda/ADOPTED.md:55`), and the adjudicator of round `2026-10-27-368241b2e8c` checked the arithmetic. This catch was **incidental**: the re-vote happened because the hypothesis `hk` is idle, which made the reviewer read the proof text of Lemma 2.3. Nothing in the protocol systematically reads proofs (REPORT §6 still says "nothing checks that a Lean proof follows the paper's argument"). |
| B1-2 | **CAUGHT** | `D/SUMMARY.md:19` (defect 1); `D/REPORT.md` §5 row 1; `A/PAPER_DEFECTS.md:21` | false, repair "typo". Counterexample n = d = 1 (and every power of 2). Notes that the proof uses d ≥ 3 (tex l.99) and that Thm 2.6 is unaffected. | Operator while writing statements (`A/AUTHOR_NOTES.md` suspicion 1, Lean commit ae9a449 "refutations of Prop 2.5, Cor 3.2, Lemma 3.4 as printed"). Lean refutation `not_prop_2_5_as_printed` (PoliteNumbers/Main.lean:138); F10/F12 in paper-faithfulness of round `2026-10-27-full-2e342474b02`; adjudicator confirmed. Repair `prop_2_5` (1 < d). |
| B1-3 | **CAUGHT** | `D/SUMMARY.md:20` (defect 2); REPORT §5 row 2; `A/PAPER_DEFECTS.md:22` | false, repair "local". Counterexample n = 1, and notes it fails for every n (n = 9 example). Notes the paper's own proof gives −1. | Same path as B1-2. Refutation `not_cor_3_2_as_printed` (Main.lean:291). Repair `cor_3_2`: R*(n)+1 = d_odd(n) (Main.lean:307). |
| B1-4 | **CAUGHT** | `D/SUMMARY.md:21` (defect 3); REPORT §5 row 3; `A/PAPER_DEFECTS.md:23` | false, repair "typo" (old run said "add hypothesis"; either is acceptable). Counterexample k = 1. | Same path. Refutation `not_lemma_3_4_as_printed` (Main.lean:346). Repair `lemma_3_4` (2 ≤ k, Main.lean:354). |
| B1-5 | **CAUGHT** (strict: PARTIAL) | `D/SUMMARY.md:24` ("not a defect … 1 (Proposition 3.5)"); REPORT §5 "Not defects" 1st bullet; `A/PAPER_DEFECTS.md:30` | States exactly the fact: "assumes p ≥ 5, but its conclusion also holds for p = 3 (R(3) = 2, with representations (3, 1) and (1, 2))", then classes it as "a hypothesis stronger than necessary is not an error". The Lean keeps p ≥ 5 (faithful). | Substantiveness lane of the proof round (`A/DECISIONS.md:287`: "h5 is stronger than mathematically required (p = 3 also satisfies the conclusion …)"); the adjudicator rejected weakening the Lean and recorded the fact under "Not defects". Same handling and same label as the old run. |
| B1-6 | **CAUGHT** | `D/SUMMARY.md:22` ("proof slip 1 — tex l.173-174 (the form of Bertrand's postulate quoted for the proof of Corollary 4.1)"); REPORT §5 "Slips in the proofs" 1st bullet (l.106); `A/PAPER_DEFECTS.md:26`; REPORT §6 route row 2; `D/CITATIONS.md:9-13` (C1) | Fact exact: false at n = 1; should say n ≥ 2 or n < p ≤ 2n; Cor 4.1 (n ≥ 2) unaffected. Evidence "by argument" (no Lean witness, as in the old run). CITATIONS C1 compares against Chebyshev's 1852 memoir (Numdam scan: a > 3, a < p < 2a − 2) and says the paper's form is "a wider range than the source gives". That is exactly the key's nature (quote stronger than the source). | Operator at stating (`A/AUTHOR_NOTES.md` suspicion 4); paper-faithfulness lane of `2026-10-27-full-2e342474b02` noted it out of lane; adjudicator wrote it. Citation review (C1) found it independently, within this run this time. Lean `cor_4_1` uses Mathlib `Nat.exists_prime_lt_and_le_two_mul`. |

**Note on B1-6's category.** The old run put it in the defects table as `misprint (true as intended)`. This run lists it under "Slips in the proofs (no witness needed)", that is, as an error inside the proof of Cor 4.1. The facts, the repair and the impact are all right, and the citation note gives the source comparison. So it scores as CAUGHT. But the label is slightly off: the sentence is a quoted statement of a cited theorem, not a proof step.

**Decoy (Cor 3.3, R(2^j) = 1 including j = 0): correctly NOT reported.** SUMMARY lists Corollary 3.3 as faithful (`D/SUMMARY.md:11`). `cor_3_3 (j : ℕ) : R (2 ^ j) = 1` is proved for all j (Main.lean:327; SIGNOFF.md:228-236, "OK").

## False positives
None. The defect table has 3 rows (B1-2, B1-3, B1-4), and there are 2 proof slips (B1-6, B1-1). The "Not defects" list gives:
- p ≥ 5 (B1-5, correct fact);
- the out-of-scope items: the unnumbered Remark, the inline Bertrand statement, and the intro example 9 = 4+5 = 2+3+4;
- "every numbered result in scope is proved; Conj 4.2 stated only";
- the idle hypotheses n > 0 (Lem 2.2) and k > 0 (Lem 2.3).

None of these is wrongly called a defect. Mason (1912) was treated as a historical attribution, not a cited result, and was not flagged (`D/CITATIONS.md:3`). That is correct.

**Minor inconsistencies (not false positives).**
- The "Not defects" bullet 2 (`A/PAPER_DEFECTS.md:31`) calls the inline Bertrand statement out of scope and "not a defect in the paper". The slip list two items above (`A/PAPER_DEFECTS.md:26`) says the same sentence is wrong. So the same item is called both wrong and not a defect, which could confuse a reader.
- The SUMMARY's "not a defect 3" is labelled "(At commit 368241b2e8c every numbered result in scope)". That is a truncated sentence used as the label.

## (1) Mathematics
- **Builds clean.** Built in a fresh clone of branch `formalize/polite-numbers` (HEAD 368241b) with `lake exe cache get` and `lake build PoliteNumbers` (Lean v4.35.0, Mathlib v4.35.0). Build OK (1:27). Kernel replay with the toolchain's `leanchecker` passed: `lake env leanchecker -v PoliteNumbers` (all 4 modules, 38 s) and `lake env leanchecker --fresh -v PoliteNumbers` (whole import closure, 21 min), both exit 0.
- **No risky constructs in the sources.** There is no `sorry`, `native_decide`, `axiom`, `set_option`, `implemented_by`/`extern`, `unsafe`, or custom elab/macro in `PoliteNumbers/` or the lakefile. Phase 0 in SUMMARY reports standard axioms only.
- **Faithfulness (read by hand against paper.tex).**
  - Def 2.1 (`IsRep`, `Polite`, `R`/`Rstar` via `Set.ncard`, `dOdd` via `divisors.filter Odd`) is correct.
  - Goal `theorem_2_6 : 1 ≤ n → (Polite n ↔ ∀ j, n ≠ 2 ^ j)` is exact.
  - The three false statements are stated as printed (as `def … : Prop`) and refuted; the minimal repairs are proved.
  - Prop 3.5 keeps p ≥ 5 and proves the set equality plus R(p) = 2.
  - Cor 4.1 is as printed.
  - Conj 4.2 is a Prop and is not asserted.
- **Complete.** Every numbered environment is formalized. Only the unnumbered Remark, the inline Bertrand statement and the intro example are out of scope, and this is disclosed.
- The old run's cosmetic slip (the `oddPart` docstring) is not present in this form: `oddPart` (Main.lean:211) has no overstated docstring.

## (2) Deliverables vs records
- **Defects agree across documents.** SUMMARY, REPORT §5, PAPER_DEFECTS and DECISIONS agree on the defects and slips. VACUOUS is "None recorded" (REPORT §7).
- **Clean run record.** `D/RUN_RECORD.md` §1–§9 records:
  - no tool patches, no stops, no self-cures, no set-asides, no re-pins, no disclosed faults and no known-fault notices;
  - one mechanical failure (a correspondence lane child returned empty after 9 s and was re-spawned once);
  - a count correction (104 verdicts, not 103).
- **Reader gates passed.** Unlike the old run, all reader gates passed: summary after 7 passes, report after 2, decisions after 2 (`A/RUN_LOG.md`, "Fresh readers"). The SUMMARY took 15 hand edits (HE1–HE15).
- **Delivery.** The first `--deliver` was refused at 06:09 (RED[deliver]); after more reader passes it delivered at 06:49. This was not a hand delivery.
- **Statement approval.** Approval was by the agent under hands-off, marked "NOT a human" (`D/SUMMARY.md:5`).
- **Prior-art lane.** It was not chosen at intake, and this is disclosed.
- **Stale line number in the sign-off sheet.** `SIGNOFF.md` gives line numbers of the statements commit (e.g. `cor_3_3` at Main.lean:140), while REPORT gives those of the final commit (Main.lean:327). This is expected, because the sheet is of the approval round, but it may confuse a reader.

## (3) Time: 00:48 → 06:49 (6 h 01 min), from the audits git log and RUN_LOG

| Span | Duration | What |
|---|---|---|
| 00:48–02:20 | 1 h 32 | install (cf84ff0), intake, Checkpoint A, setup and pin. Whether this includes human waiting time at intake/Checkpoint A is not established from the records read. |
| 02:20–02:24 | 4 min | Lean scaffold; statements with refutations (ae9a449); author notes |
| 02:24–03:19 | 55 min | statement round `full-2e342474b02`, adjudication, agent approval (03:19) |
| 03:19–03:20 | 1 min | proofs of every result (ddacb20) |
| 03:20–04:14 | 54 min | full proof round `full-ddacb20deda`, re-vote, adjudication, implement (368241b) |
| 04:14–05:16 | ≈ 1 h | diff round `368241b2e8c` and Stage 5 full round `full-368241b2e8c` |
| 05:16–06:49 | ≈ 1 h 33 | prepare delivery, citation review (05:24), fresh readers (7 passes on SUMMARY), PDFs, refused `--deliver` (06:09), deliver (06:49) |

- **No time lost to stops.** The old run lost about 2 h 50 to tool-caused stops and a futile cure round.
- **Delivery is now the largest block.** It took about 1.5 h, mostly SUMMARY reader passes.

## Notes
- **What improved.** B1-1, the old run's only miss, is now caught, and the run had no stops at all.
- **The B1-1 catch was luck of routing, not a structural fix.** It came out of lane, from a re-vote that was triggered by Lemma 2.3's idle hypothesis. The protocol still has no proof-text reading pass (REPORT §6), so a proof slip in a lemma with no idle hypothesis could still be missed. This should be kept in mind when the result is reported as a benchmark gain.
- **Planted citation defect.** B1-6 was caught by both the statement work and the in-run citation review, which compared it against the 1852 source.

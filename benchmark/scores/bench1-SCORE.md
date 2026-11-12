# bench1 score: "Polite numbers and odd divisors"

Run: hands-off, release 5fcd619 (formalize-paper 0.3.0-dev), Claude Code with Opus 5.5 at medium effort. Delivered by hand after stop S2.
Snapshot: a frozen copy of the run's repository (not published). Scored 2026-10-24 by an independent scorer against `keys/bench1-key.md` and `keys/KEY-CHECK-bench1-5.md`. The snapshot was not modified. The rebuild was done in a scratch copy.

**Score: 5 of 6 planted defects CAUGHT, 0 PARTIAL, 1 MISSED. The decoy was correctly not reported. 0 false positives.**
(Strict variant: if a defect reported with the right facts but labelled "not a defect" counts as mislabelled, B1-5 becomes PARTIAL and the score is 4 CAUGHT + 1 PARTIAL + 1 MISSED.)

## Per defect

| Id | Planted defect | Verdict | Where it reaches the reader | Nature as reported | Mechanism |
|---|---|---|---|---|---|
| B1-1 | Proof slip in Lemma 2.3: "k+(2a+k−1)=2a+2k+1" should be 2a+2k−1 | **MISSED** | Nowhere. PAPER_DEFECTS "Slips in the proofs: None found". No record mentions the sum. | — | None. The lanes compare statements, not proof text, and the REPORT says "Proof routes: NOT CERTIFIED … proofs are not checked line by line". The Lean proof of `lem_2_3` is a direct parity argument (omega), so nothing forced the slip into view. |
| B1-2 | Prop 2.5 "d ≥ 1" should be d > 1 (false as printed) | **CAUGHT** | PAPER_DEFECTS row 1; REPORT §5; SUMMARY (defect 1, on its own line) | false, repair "typo". Counterexample n=d=1; notes that the proof uses d ≥ 3 and that Thm 2.6 is unaffected. | Operator while stating, before any review (AUTHOR_NOTES defect 1, commit 4e061ae "refutations of three printed statements"). Lean refutation `not_prop_2_5_as_printed`; paper-faithfulness F10/F12 Pass; adjudicator of e4477a9 confirmed. Repair `prop_2_5` (1 < d). |
| B1-3 | Cor 3.2 R*(n)=d_odd(n) should be d_odd(n)−1 (false) | **CAUGHT** | PAPER_DEFECTS row 2; REPORT §5; SUMMARY (counted, pointer to REPORT §5) | false, repair "local". Counterexample n=1; notes that the paper's own proof gives −1. | Same path: operator at Stage 2, Lean refutation `not_cor_3_2_as_printed`, F10/F12, adjudicator. Repair `cor_3_2`: R*(n)+1 = d_odd(n). |
| B1-4 | Lem 3.4 k ≥ 1 should be k ≥ 2 (fails at T_1=1) | **CAUGHT** | PAPER_DEFECTS row 3; REPORT §5; SUMMARY (counted) | false, repair "add hypothesis". Counterexample k=1. | Same path: operator at Stage 2, Lean refutation `not_lem_3_4_as_printed`, F10/F12, adjudicator. Repair `lem_3_4` (2 ≤ k). |
| B1-5 | Prop 3.5 p ≥ 5 stronger than needed (p=3 works) | **CAUGHT** (see note) | PAPER_DEFECTS "Not defects"; REPORT §5; SUMMARY "not a defect … 3 (Proposition 3.5)" | States exactly the fact: "assumes p ≥ 5, although its conclusion also holds for p = 3 ((3,1),(1,2))", then classes it as "a hypothesis stronger than needed is not a defect". | Substantiveness lane (round a0644f7, weakening probe `hyp_needed_counterexamples.lean`). The adjudicator REJECTed weakening the Lean and recorded the fact under "Not defects". The Lean keeps p ≥ 5, which is faithful. The label agrees with KEY-CHECK's remark that unneeded-hypothesis items are true statements, not errors. |
| B1-6 | Bertrand quoted "n ≥ 1, n<p<2n" (false at n=1) | **CAUGHT** | PAPER_DEFECTS row 4; REPORT §5; SUMMARY (counted); DEVIATIONS row 1 | "misprint (true as intended)", repair "typo". Fails at n=1; the intended form is the cited Chebyshev theorem (n ≥ 2, or p ≤ 2n); Cor 4.1 is unaffected. This matches the key's nature (quote stronger than the source). No Lean witness: "confirmed by argument". | Operator at intake/stating (AUTHOR_NOTES defect 4); out-of-lane notes from paper-faithfulness and non-vacuity in e4477a9; adjudicator wrote the row. Lean `cor_4_1` uses Mathlib `Nat.exists_prime_lt_and_le_two_mul` and excludes p=2n. (The separate citation-review test, which is not part of this run, also flagged B1-6 as C1.) |

**Decoy (Cor 3.3, R(2^j)=1 including j=0): correctly NOT reported.** It is listed as faithful, and `cor_3_3` is proved for all j ≥ 0.

## False positives
None. The four PAPER_DEFECTS rows are B1-2, B1-3, B1-4 and B1-6. The "Not defects" list gives:
- the idle hypotheses n>0 (Lem 2.2) and k>0 (Lem 2.3);
- p ≥ 5;
- the scope of the unnumbered Remark;
- the Mathlib form of Bertrand;
- Def 2.1 on all of ℕ;
- Conj 4.2.

All of these are correctly classed as non-defects. Mason (1912) was not flagged.

## (1) Mathematics
- **Builds clean.** Rebuilt in a scratch copy with `lake exe cache get` and `lake build PoliteNumbers` (Lean v4.35.0, Mathlib v4.35.0): success, with only style-linter warnings.
  - The default target `Bench1Formalization` does not include the PoliteNumbers lib. It must be built explicitly.
- **Axioms and sorry.** `#print axioms` on all 14 results and refutations (thm_2_6, prop_2_5, prop_3_1, cor_3_2, cor_3_3, lem_3_4, prop_3_5, cor_4_1, lem_2_2/2_3/2_4 and the three `not_*_as_printed`) gives only propext, Classical.choice and Quot.sound. There is no sorry, admit, native_decide or `axiom` in the sources.
- **Faithfulness (read by hand against paper.tex).**
  - Def 2.1 (IsRep/Polite/reps/R/Rstar/dOdd with ncard; finite sets) is correct.
  - Goal `thm_2_6`: `1 ≤ n → (Polite n ↔ ∀ j, n ≠ 2^j)` is exact.
  - Lem 2.2/2.3/2.4, Prop 3.1, Cor 3.3, Prop 3.5 (with the reps set) and Cor 4.1 are as printed.
  - The three false statements are stated as printed (as `def … : Prop`) and refuted. Minimal repairs are proved.
  - Conj 4.2 is a Prop, not asserted.
- **Complete.** Every numbered environment is formalized. Only the unnumbered Remark is out of scope (disclosed; it is true).
- **One cosmetic slip.** The adopted docstring fix for `oddPart`, which overstates its value at (0,0), was not implemented. This is disclosed. It is a helper only.

## (2) Deliverables vs records
- **Defects and decisions agree.** SUMMARY, REPORT, PAPER_DEFECTS, DEVIATIONS and DECISIONS agree on the defects and decisions. VACUOUS.md is absent and correctly reported as none.
- **Stale documents, disclosed.** The delivered SUMMARY, REPORT and DECISIONS were prepared at 18:26, before S2 and the cure round f167852. As a result:
  - SUMMARY lists only stop S1.
  - SUMMARY marks **Lemma 2.4 "not established: an assumption is not settled"**, although it is proved and every lane passed it. This is an artefact of the S2 tool bug (`result_status.py:491`).
  - Both points are disclosed in README §D and KNOWN_FAULTS-run (§1–2), but a reader of SUMMARY alone is misled about Lemma 2.4.
- **S1 labelled "tamper".** SUMMARY and REPORT §11 give S1 the cause class "tamper". That is the tool's class, while the record shows a false alarm (a prompt re-render diff), and the human's answer quoted beside it says so.
- **Reader gates failed but delivered.** None of the reader gates passed (23/22/2 open findings answered unfixable). They are quoted in the KNOWN_FAULTS notices. The delivery is honest, but its polish is weak.
- **Hand delivery disclosed.** README §D gives sha256 for each copied file.
- **Second tool fault disclosed.** `scope.py` produced 4 phantom F10 items in the cure round; this is disclosed.
- **Statement approval.** Approval was by the agent under hands-off, marked "NOT BY A HUMAN" throughout.

## (3) Time: 13:12 → 20:21 (7 h 09 min)

| Span | Duration | What |
|---|---|---|
| 13:12–13:33 | 21 min | install, intake, Checkpoint A |
| 13:33–14:56 | 1 h 23 | statements and refutations (13:36–13:42); statement round e4477a9 (non-vacuity lane slowest, 14:19); adjudication 14:32; agent approval 14:56 |
| 14:56–15:06 | 10 min | proofs (a0644f7 at 14:58: all proofs landed fast) |
| 15:06–15:44 | 38 min | full round a0644f7 + re-vote on lem_2_3's idle hypothesis |
| **15:44–17:13** | **1 h 29** | **stop S1 (false alarm): waiting for the human** |
| 17:13–17:55 | 42 min | implement, Stage 5 full round 488be9e, Checkpoint C (delegated) |
| 18:05–18:39 | 34 min | prepare delivery + 3 reader passes + 2 fix rounds (all failed) |
| 18:39–18:53 | 14 min | PDF render/verify (all verified round 1) |
| **18:59–19:48** | **49 min** | **stop S2 (tool bug): cure attempt = a whole extra full round f167852 that could not help** |
| **19:48–20:19** | **31 min** | **S2 waiting for the human** |
| 20:19–20:21 | 2 min | hand delivery, S3 (notice committed under wrong subject) self-cured by revert |

- **Breakdown.** About 2 h was human waiting on two tool-caused stops, and about 50 min was a futile cure round. The real formalization and audit work took about 4 h, of which the mathematics (statements + proofs) was under 1 h.
- **Without the tool faults** (S1, S2, S3) the run would plausibly have finished around 18:55 (≈ 5 h 40), or ≈ 4 h with no stops.

## Notes
- **What worked.** The operator found all three false statements and the Bertrand misquote while writing the statements. Lean refutations then made B1-2/3/4 airtight. The lanes and the adjudicator confirmed them and did not add noise.
- **The miss.** B1-1 is a proof-text slip in a lemma whose statement is true. Nothing in the protocol reads proofs line by line, and REPORT says so. Catching such slips would need a proof-reading pass, separate from the statement lanes.
- **Planted citation defect.** B1-6 was caught both in the run and by the separate citation-review test.

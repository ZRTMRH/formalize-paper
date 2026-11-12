# bench2 score: "Repeated degrees in finite simple graphs"

Run: hands-off, release 5fcd619 (formalize-paper 0.3.0-dev), Claude Code with Opus 5.5 at medium effort. One self-cured stop (S1), a memory-pressure pause, and a hand delivery after `--deliver` refused.
Snapshot: a frozen copy of the run's repository (not published). Scored 2026-10-24 by an independent scorer against `keys/bench2-key.md` and `keys/KEY-CHECK-bench1-5.md`. The snapshot was not modified. The rebuild was done in a scratch copy.

**Score: 6 of 6 planted defects CAUGHT, 0 PARTIAL, 0 MISSED. The decoy was correctly not reported. 0 false positives.**
All four "false as printed" rows are genuine, and each has a Lean refutation of a faithful as-printed statement.

Two caveats on how robust this is:
- B2-2 (the proof slip) was caught by the adjudicator reading the proof on its own initiative ("my own finding, not a lane's"). No lane is required to do that, and bench1's analogous slip was missed.
- B2-6 was missed by the operator. At Checkpoint A the operator declared the printed (false) Erdős–Gallai as the literature hypothesis, and the human typed "OK". The first statement round's lanes caught it.

## Per defect

| Id | Planted defect | Verdict | Where it reaches the reader | Nature as reported | Mechanism |
|---|---|---|---|---|---|
| B2-1 | Lemma 2.5 false for n = 1 | **CAUGHT** | PAPER_DEFECTS row 1; REPORT §5; SUMMARY defect 1 | false, repair "add hypothesis". Witness: the one-vertex graph. Notes that the proof's "u ≠ w" step needs n ≥ 2 and that Thm 2.6 survives. | Operator while stating (AUTHOR_NOTES at dc2fc5a, 13:41; refutation in Lean 7f44ea5). Lean `not_lemma_2_5_as_printed`; paper-faithfulness F10/F12; adjudicator d4df182. Repair `lemma_2_5` (2 ≤ n). |
| B2-2 | Proof slip "at most n−2 values" in Thm 2.6 | **CAUGHT** | PAPER_DEFECTS "Slips in the proofs"; DEVIATIONS row 3 ("paper step fails"); REPORT §5/§6; SUMMARY "proof slip 1" | Should be n−1. Witness: P_3. Pigeonhole still works. Exactly the key. | Adjudicator of the first statement round (d4df182, 14:18), on its own reading, checked in scratch `thm26_slip.lean`. The operator's Lean route (case split, n−1 values) independently records it as a route deviation. Not a protocol-guaranteed path. |
| B2-3 | Prop 2.7 vacuous | **CAUGHT** | PAPER_DEFECTS row 4 (vacuous, intent unknown); VACUOUS row 1; SUMMARY "vacuous 1"; docstring "True only vacuously" | Hypotheses contradict Thm 2.6; a question for the authors. | Operator noted it at Checkpoint A. The non-vacuity lane flagged it in every round, with a Lean unsat probe (`prop_2_7_unsat.lean`, later two lines from `theorem_2_6`). The Lean proof is by contradiction from `theorem_2_6`. |
| B2-4 | Prop 3.1 bound (n−2)/2 should be (n−1)/2 | **CAUGHT** | PAPER_DEFECTS row 2; REPORT §5; SUMMARY defect 2 | false, repair "typo". Witness: 2K_2 on 4 vertices (the key's second witness). Notes that the proof uses (n−1)/2. | Operator at Checkpoint A ("n = 4 counterexamples"). Lean `not_proposition_3_1_as_printed`; F10/F12; adjudicator. Repair `proposition_3_1` ((n−1)/2). |
| B2-5 | Prop 3.2 ≥ C(n−1,2) should be > | **CAUGHT** | PAPER_DEFECTS row 3; REPORT §5; SUMMARY defect 3 | false, repair "typo". Witness: K_3 + K_1 (the key's general witness). Notes that the proof proves the strict form. | Operator at Checkpoint A. Lean `not_proposition_3_2_as_printed`; F10/F12; adjudicator. Repair `proposition_3_2` (strict). Proved by a different route (DEVIATIONS row 5). |
| B2-6 | Erdős–Gallai missing min(d_i, k) | **CAUGHT** | PAPER_DEFECTS row 5; REPORT §5 and "sending to authors"; SUMMARY "defect (+2): 4; 5" (pointer only); SIGNOFF; DECISIONS | false, repair "local". Witness: (4,2,2,2), a valid variant of the key's (4,2,2,2,0). Notes that only "if" fails and that the Remark is unaffected. A brute-force check with n ≤ 6 shows the min form equals graphicity. | **Missed by the operator**: commit 7f44ea5 stated `ErdosGallaiCondition` without the min, as the Checkpoint A literature hypothesis. Caught in the first statement round by paper-faithfulness (F10 FAIL, witness (4,2,2,2)), correspondence (FAIL) and non-vacuity (FAIL). Adjudicator adopted; Lean 50f59a5 restated the hypothesis with min and refuted the printed form (`not_ErdosGallai_as_printed`). The separate citation-review test also flagged it (item 1, witness (4,2,2,2,0)). |

**Decoy (n ≥ 2 in Theorem 2.6): correctly NOT reported.** `theorem_2_6` was approved "exactly as printed". Also not flagged (correctly): Cor 2.3 for edgeless graphs, and Prop 3.1 at n = 1. The idle `n ≥ 1` of Prop 3.1 is recorded as the paper's own hypothesis, kept, and not called a defect.

## False positives
None. All five PAPER_DEFECTS rows and the one slip are planted defects. I checked each of the four "false as printed" findings:
- **Lemma 2.5:** K_1 has degree 0 = n−1. Genuine.
- **Prop 3.1:** in 2K_2 every degree is 1 ≥ (4−2)/2, and the graph is disconnected. Genuine.
- **Prop 3.2:** K_3 + K_1 has 3 = C(3,2) edges and is disconnected. Genuine.
- **Thm 4.1:** (4,2,2,2) has even sum, and its k = 1..4 checks are 4 ≤ 6, 6 ≤ 6, 8 ≤ 8 and 10 ≤ 12. It is not graphic, since 4 > n−1. Genuine.
- In each case I read the Lean `_as_printed` definition against the tex, found it faithful, and the refutation builds.

The "Not defects" list is all correctly classed:
- Lemma 2.2 and Cor 2.3 are already in Mathlib.
- "Connected" holds for the empty graph.
- The Remark is out of scope; its arithmetic is correct.
- Thm 4.1 is not proved (a scope limitation).

## (1) Mathematics
- **Builds clean.** Rebuilt in a scratch copy: `lake exe cache get` and `lake build RepeatedDegrees` (Lean/Mathlib v4.35.0) succeed, with only style-linter warnings. As in bench1, the default target `Bench2Formalization` does not include the lib.
- **Axioms and sorry.** `#print axioms` on all 13 theorems gives only propext, Classical.choice and Quot.sound. The theorems are lemma_2_2, corollary_2_3, lemma_2_4, lemma_2_5, theorem_2_6, proposition_2_7, proposition_3_1, proposition_3_2, the four `not_*_as_printed` refutations and the alias. There is no sorry, admit, native_decide or `axiom` (the one grep hit is a docstring).
- **Faithfulness (read by hand against paper.tex).**
  - Definitions: Def 2.1 is a Mathlib `SimpleGraph` on a `Fintype`. IsIsolated, IsDominating and IsConnected (= Preconnected, so it matches the paper on the empty graph) are correct.
  - Goal: `theorem_2_6` (2 ≤ card V → ∃ u ≠ w, equal degree) is exact.
  - Stated exactly as printed: Lem 2.2, Cor 2.3, Lem 2.4 and Prop 2.7.
  - The four false statements are stated as printed (as `def … : Prop`) and refuted. Their minimal repairs are proved, except Thm 4.1 (below).
  - Nits: Cor 2.3 carries an idle `[DecidableEq V]` (disclosed in its docstring). `IsDegreeSequence` puts degree d i at vertex i of Fin n, which is fine up to relabelling (stated in its docstring).
- **Complete, with one limitation.** Every numbered environment is formalized. Thm 4.1 (a cited result with no proof in the paper) is only a `def ErdosGallai : Prop` named hypothesis, used by nothing. Only its as-printed refutation is a theorem. This is the right call and is disclosed in REPORT. The Remark is checked as an `example`.

## (2) Deliverables vs records
- **Records agree.** PAPER_DEFECTS, VACUOUS, DEVIATIONS, REPORT §5 and DECISIONS agree with each other and with the Lean.
- **SUMMARY "Theorem 4.1 … proved as repaired": CONFIRMED wrong.**
  - The Lean has no proof of the repaired Erdős–Gallai. `ErdosGallai` is a `def … : Prop`, stated and never proved. Only `not_ErdosGallai_as_printed` is proved.
  - The cause is a generator bug: `result_status.py` reads a `def … : Prop` as proved. The fresh reader caught it as BLOCKING, but both reader-fix rounds had already been spent on the first (pre-S1) delivery attempt at 17:21–17:27, so it shipped unfixed.
  - It is disclosed in KNOWN_FAULTS-summary and README §D, both of which give the correct reading.
  - Judgement: a real overclaim on the headline page. Its impact is limited because Thm 4.1 is off the goal path and REPORT §5 is correct. Still, a reader of SUMMARY alone would believe a classical theorem was formalized. It should be a status of its own ("cited, hypothesis only; printed form refuted").
- **SUMMARY "not established: Lemma 2.2; Corollary 2.3": wrong in the other direction.**
  - Both are proved exactly as printed, with clean axioms. The status reflects non-vacuity "Ambiguous" verdicts (closed by a Mathlib lemma) that adjudicators answered with QUESTION, which `result_status.py` never counts as settled.
  - This was also the actual cause of the `--deliver` refusal.
  - Disclosed in KNOWN_FAULTS-summary. It is the same class of artefact as bench1's Lemma 2.4.
- **SUMMARY gives defects 4 and 5 only as "defect (+2): 4; 5".** They are named only in REPORT (reader finding, disclosed).
- **S1 labelled "tamper".** SUMMARY labels S1 "tamper", but its record says it was a pinned `scope.py` fault: the diff-round F10 filter reads the round's own sealed verdict. The bench1 mislabel recurs.
- **Hand delivery is honest and precise.**
  - README §D quotes the exact `--deliver` refusal lines and gives sha256 values.
  - It **correctly contradicts an earlier outside attribution**, which said the refusal came from the scope.py fault. The record shows `adj-record` QUESTION items on Lem 2.2 and Cor 2.3, and the operator says so.
  - It says the delivery gate was not re-run at copying.
- **Two cured failures not in REPORT (reader finding, disclosed):** the tree-baseline FAIL from skipping Phase 0 after empty commits, and the index-row drift from the alias.
- **Statement approval.** Approval was by the agent under hands-off, marked "NOT a human" throughout.

## (3) Time: 13:12 → 22:23 (9 h 11 min by the commit record; the operator's 13:22 start gives about 9 h 01)

| Span | Duration | What |
|---|---|---|
| 13:12–13:41 | 29 min | install, intake, Checkpoint A, statements + 3 refutations |
| 13:41–14:25 | 44 min | statement round 1 (7f44ea5): lanes catch Erdős–Gallai; adjudicator finds the slip |
| 14:25–15:18 | 53 min | statement round 2 (50f59a5), adjudication, delegated approval |
| 15:18–15:27 | 9 min | proofs (drafted during Stage 2; all land at 502b191) |
| 15:27–16:24 | 57 min | full round 502b191, adjudication, docstring fixes |
| 16:24–17:04 | 40 min | Stage 5 full round 3984355, adjudication, DECISIONS, delegated Checkpoint C |
| 17:13–17:51 | 38 min | delivery attempt 1: 3 readers, **both reader-fix rounds spent**, PDFs rendered |
| 17:54–18:03 | 9 min | diff round to settle pending items before delivery → S1 |
| **18:03–19:01** | **58 min** | **S1 (scope.py fault): set-aside, redo diff round 8788bdc hits the same mismatch; memory-pressure kill of scope.py --verify and wait for the human; diagnosis** |
| **19:01–20:31** | **1 h 30** | **S1 cure: full redo round ced696a (+ tree-baseline failure), alias theorem, drift and restore** |
| **20:47–21:13** | **26 min** | **diff redo round 297a872, adjudication, S1 closed** |
| 21:21–21:50 | 29 min | delivery attempt 2: readers (no fix budget left), re-renders |
| **21:50–22:23** | **33 min** | **`--deliver` refused (RED[adj-record] on Lem 2.2/Cor 2.3); waiting for the human; hand delivery** |

- **Breakdown.** About 3 h 10 (18:03–21:13), plus a second delivery preparation (~30 min), was caused by the pinned `scope.py` fault. That includes an unmeasured memory-pressure pause within 18:13–19:01. The final 33 min came from the second tool fault: QUESTION-answered Ambiguous verdicts never settle.
- **Mathematics took about 1 h 20.** Statements, refutations and proofs ran from 13:12 to 13:41 plus about 15:18–15:27. The rest of the time went to the statement rounds (~1 h 40) and audit rounds.
- **Without S1** the run would plausibly have ended around 18:00 (≈ 4 h 50). It would still have been refused at `--deliver` for the Lemma 2.2/Cor 2.3 items.

## Notes
- **What worked.**
  - The operator found 4 of 6 defects (B2-1, B2-3, B2-4, B2-5) before any review.
  - The paper-faithfulness lane caught the citation misstatement the operator had written into a Checkpoint-A hypothesis.
  - The adjudicator caught the proof slip.
  - Every false claim has a machine-checked refutation, with no false positives and no noise.
- **Weak points.**
  1. The proof slip was caught by chance, not by design.
  2. A false literature hypothesis passed Checkpoint A; the lanes saved it.
  3. The SUMMARY status table is wrong in both directions: Thm 4.1 is overclaimed, Lem 2.2/Cor 2.3 underclaimed. Both come from `result_status.py`.
  4. The reader-fix budget was spent on a delivery that was then superseded.
  5. A tool fault cost ~3.5 h.

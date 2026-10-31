# bench3 score, run b3v (formalize-paper 0.3.0 public release 9f2c1d3): "A sum–reciprocal inequality and two applications"

Run: b3v. Hands-off, release mode, Claude Code (Opus 5.5, Claude Team). Checkpoint A was confirmed 2026-10-31 08:19 EDT. The session was killed about 08:30 for a computer restart and resumed at 08:35 with `claude --continue`. The first `--deliver` was at 12:08 and the final delivery at 12:15:41. `audits/project.py --check-delivered` returned ok. There were 0 stops. Tokens (41 transcripts): 0.62M output, 97.9M cache read, 2.72M cache write. (These run facts come from the run notes. I did not re-derive them.)

Snapshot: a frozen copy of the run's repository (not published); read only, not modified. Scored 2026-10-31 by an independent scorer against `keys/bench3-key.md` and `keys/KEY-CHECK-bench1-5.md`, using the rules of `scores/bench1-SCORE-0.3.0.md`:
- **Strict variant.** A defect reported with the right facts but labelled "not a defect" or "reading choice" counts as PARTIAL.
- **Deliverables rule.** A defect counts only if it reaches a delivered document (`deliverables/`). A finding that appears only in the audit records is at most PARTIAL.

I did not rebuild the Lean or run lake. Paths are relative to the snapshot: `D/` = `deliverables/`, `A/` = `audits/sum-reciprocal/`, Lean = `SumReciprocal/`.

**Score: 7 of 7 planted defects CAUGHT, 0 PARTIAL, 0 MISSED. The decoy was correctly not reported. 0 false positives.**
**Strict: 4 CAUGHT + 3 PARTIAL + 0 MISSED** (B3-2 kept as an "unneeded hypothesis", B3-6 "not counted as a defect", B3-7 "reading choice").

## Comparison with the earlier 0.3.0 bench3 score (`scores/bench3-5-SCORE-0.3.0.md`, bench3 section)

| Id | Planted defect | Earlier 0.3.0 run (instance-sumrecip) | This run (b3v) | Change |
|---|---|---|---|---|
| B3-1 | Lem 2.3: x + 1/x ≥ 2 for x ≠ 0 (false) | CAUGHT | **CAUGHT** | same |
| B3-2 | Lem 2.5: x_i ≥ 0 not needed | CAUGHT (strict PARTIAL) | **CAUGHT (strict PARTIAL)** | same |
| B3-3 | Proof of Lem 2.5: b_i = x_i should be b_i = 1 | CAUGHT | **CAUGHT** | same |
| B3-4 | Def 2.1 "harmonic mean" vs Cor 2.7 | CAUGHT | **CAUGHT** | same |
| B3-5 | Cor 2.8 vacuous | CAUGHT | **CAUGHT** | same |
| B3-6 | Bernoulli quoted for every real x | CAUGHT (proof slip 2 + CITATIONS) | **CAUGHT (strict PARTIAL)**: right facts, but "disclosed, not counted as a defect" | strict: lost |
| B3-7 | Prop 3.1: ℕ ∋ 0 makes n = 0 bad | CAUGHT (strict PARTIAL) | **CAUGHT (strict PARTIAL)** | same |
| Decoy | Nesbitt proof (Prop 2.9) | correctly not reported | correctly not reported | same |
| False positives | | 0 | 0 | same |
| **Total** | | **7 C / 0 P / 0 M** (strict 5/2/0) | **7 C / 0 P / 0 M** (strict 4/3/0) | normal same; strict −1 |
| Goal Thm 2.6 | | proved, faithful | proved, as printed, faithful | same |
| Stops | | 1 (`result_status.py` tool bug, self-cured with tool patch TP1 after 15 rejected reviews) | 0; no tool patches, no self-cures, no disclosed faults | better |
| Delivered | | yes | yes (`--check-delivered` ok) | same |
| Wall clock | | 26 h 55 (about 12 h 10 active, without the 14.5 h usage-limit gap) | about 3 h 56 from Checkpoint A (08:19) to delivery (12:15), including the ~5 min restart | much faster |

## Per defect

| Id | Verdict (normal / strict) | Where it reaches the reader | Nature as reported |
|---|---|---|---|
| B3-1 | CAUGHT / CAUGHT | `D/SUMMARY.md` "Bottom line" and "Defects found" bullet 1; `D/REPORT.md` §3 Defect 1; §2 table row Lemma 2.3; `D/DECISIONS.md` "Lemma 2.3"; `A/PAPER_DEFECTS.md` row 1 | false, add hypothesis. Counterexample x = −1. The proof's "multiplying by x" works only for x > 0, and the repair is x > 0. It notes that only the unnumbered Remark uses the lemma, at a positive number. Lean: `not_lem_2_3_as_printed` (Section2.lean:59) and `lem_2_3` (x > 0). Exact. |
| B3-2 | CAUGHT / PARTIAL | `D/REPORT.md` §4 "Hypotheses the proofs do not need … x_i ≥ 0 in Lemma 2.5", "kept because the paper states them … Dropping any of them would make the statement stronger than the paper's"; `D/SUMMARY.md` "Where the Lean departs" ("x_i ≥ 0 in Lemma 2.5 … not needed by the proofs; they are kept"); `D/DECISIONS.md` "Lemma 2.5 … Unused hypothesis" (option (b) drop it = "a stronger statement"). The explicit statement that it "holds for all real x_i" is only in `A/PAPER_DEFECTS.md`, under "Not defects", bullet 4. | Right fact (the hypothesis is idle, the statement holds without it, and it was confirmed by a delete-and-recompile probe). In the deliverables it is presented as a kept, unneeded hypothesis, and the audit record calls it "not defects". So it is strict PARTIAL, as in the earlier run. |
| B3-3 | CAUGHT / CAUGHT | `D/SUMMARY.md` "Defects found" bullet 4 ("Proof slip, Lemma 2.5 (tex l.89)"); `D/REPORT.md` §3 "Proof slip — Lemma 2.5"; §4 "Proof route, Lemma 2.5"; `D/DECISIONS.md` "Lemma 2.5 … Proof route (paper step fails)"; `A/PAPER_DEFECTS.md` "Slips in the proofs" | Exact: with b_i = x_i you get only (∑x_i²)² ≤ (∑x_i²)². The text's "∑1² = n" shows a vector of ones was meant, and the lemma is unaffected. The Lean uses a_i = 1, b_i = x_i (Section2.lean:87). |
| B3-4 | CAUGHT / CAUGHT | `D/SUMMARY.md` "Bottom line" ("Corollary 2.7 is false only because Definition 2.1 misprints H") and "Defects found" bullet 2, plus the status-table row Definition 2.1; `D/REPORT.md` §3 Defect 2 and §2 rows Def 2.1 / Cor 2.7; `D/DECISIONS.md` "Definition 2.1", "Paper defect 2"; `A/PAPER_DEFECTS.md` row 2 | false, typo. Witness n = 1, x = (1/2), so A = 1/2 < 2 = H. The intended H = n/∑1/x_i is taken from the proof of Cor 2.7 (tex l.111-112). Lean: `harmonicMeanAsPrinted`, `not_cor_2_7_as_printed` (Section2.lean:118), and `cor_2_7` with the true harmonic mean. Matches the key exactly, including locating the cause in Def 2.1. |
| B3-5 | CAUGHT / CAUGHT | `D/SUMMARY.md` "Bottom line" ("true only because no input satisfies its hypotheses"), "Defects found" bullet 3 and the status-table row; `D/REPORT.md` §3 Defect 3; `D/DECISIONS.md` "Corollary 2.8"; `A/PAPER_DEFECTS.md` row 3; `A/VACUOUS.md` | vacuous, intent unknown. It uses Thm 2.6 exactly as in the key. Lean: `cor_2_8_hyps_unsat` (Section2.lean:165) proves the hypotheses inconsistent. The statement `cor_2_8` is kept as printed. |
| B3-6 | CAUGHT / PARTIAL | `D/SUMMARY.md` "Defects found" bullet 5 ("Bernoulli's inequality as quoted … false (x = −4, n = 3). Its one use (x = 1/n > 0) is valid; disclosed, not counted as a defect"); `D/REPORT.md` §3 "Not a numbered result — Bernoulli's inequality as quoted"; `D/DECISIONS.md` "Other decisions delegated at intake" (no defect row, the operator's own judgement; the adjudicator had left it open); `D/CITATIONS.md` §2 "Sources not reached" (HLP access-restricted; "common statements … restrict x, for instance to x ≥ −1"); Lean `Examples.lean` (refutation example) | The facts are right: the key's witness, the one use at x = 1/n > 0, and the correct ranges (x ≥ −1 in CITATIONS, Mathlib's x ≥ −2 in REPORT; both are valid). But the run explicitly declined to call it a defect ("outside the numbered results agreed at setup"), so it is strict PARTIAL. The earlier run listed it as proof slip 2. Neither run could compare it with the HLP text. |
| B3-7 | CAUGHT / PARTIAL | `D/SUMMARY.md` status table "proved for n ≥ 1 (n = 0 is undefined in the paper)"; `D/REPORT.md` §4 "Reading choice, Proposition 3.1"; `D/DECISIONS.md` "CHECK row: Proposition 3.1" / "Proposition 3.1" (reading choice, reversal re-approve); `A/PAPER_DEFECTS.md` "Not defects" bullet 2; `A/DEVIATIONS.md` row 1 | The facts are right: the paper's ℕ includes 0 (tex l.146), 1/n is undefined at n = 0, and with Lean's 1/0 = 0 the n = 0 case reads 1 ≥ 2 (`Examples.lean`). But it is labelled a reading choice, and REPORT §4 calls the n = 0 case "an artefact of the encoding, not a defect of the paper". So it is strict PARTIAL, as in the earlier run. Unlike the earlier run, no "send to authors" note asks for an n ≥ 1 clarification. SUMMARY does ask the reader to check Proposition 3.1 on the sign-off sheet. |

**Decoy (Nesbitt proof, Prop 2.9): correctly NOT reported.** `D/SUMMARY.md` status table: "proved, as printed". `D/REPORT.md` §2 row Prop 2.9 and §4: "Proposition 2.9 from Theorem 2.6 with n = 3" (the paper's route). `prop_2_9` (Section2.lean:185) uses the identity a/(b+c) = s/(b+c) − 1 via `hs`. No document questions the rewrite step.

## False positives

None. These are all the claims in the deliverables that go beyond the key, and each is correct:
- **Hypotheses the proofs do not need** (`D/REPORT.md` §4; SUMMARY "Where the Lean departs"):
  - n ≥ 1 in Lemma 2.4, Lemma 2.5 and Thm 2.6. The key itself calls n ≥ 1 on Thm 2.6 harmless.
  - x_i > 0 in Cor 2.8. This is correct: if all x_i are equal and ∑x_i = 1, then x_i = 1/n and ∑1/x_i = n², without using positivity.
  These are presented as kept hypotheses, not as paper defects.
- **Lemmas 2.2 and 2.4 are one-step Mathlib facts.** This is kept as printed and explicitly called no defect.
- **CITATIONS item 1 (Nesbitt volume/year).** This is bibliographic and advisory, and it is the same as in the earlier run. KEY-CHECK could not verify the volume and pages. Not counted, as before.
- **The statement "the correct form needs x ≥ −2"** (REPORT §3) is true for natural exponents (Mathlib `one_add_mul_le_pow`). It is not an error.

## Mathematics

- **Risky constructs:** none. A grep for `sorry|native_decide|axiom|set_option|implemented_by|extern|unsafe|admit|macro|elab` over `SumReciprocal/`, `SumReciprocal.lean`, `B3vFormalization*` and `lakefile.toml` found no hits. The lakefile sets only standard options (`autoImplicit = false`, `relaxedAutoImplicit = false`, the linter set, `maxSynthPendingDepth = 3`). REPORT §1 reports Phase 0: build exit 0, 0 `sorryAx`, and standard axioms only. I did not re-check this.
- **Goal (read by hand against `paper/paper.tex` l.93-98).** The Lean is `theorem thm_2_6 (n : ℕ) (hn : 1 ≤ n) (x : Fin n → ℝ) (hx : ∀ i, 0 < x i) : (n : ℝ) ^ 2 ≤ (∑ i, x i) * ∑ i, 1 / x i` (Section2.lean:99).
  - It is exact: n ≥ 1, positive reals x_1..x_n, and (∑x_i)(∑1/x_i) ≥ n².
  - It is proved by the paper's route: `lem_2_4` with a_i = √x_i, b_i = 1/√x_i.
  - `lem_2_4` is Mathlib's `Finset.sum_mul_sq_le_sq_mul_sq`, which is a faithful statement of Cauchy–Schwarz for real n-tuples.
- **Other statements, spot-read and faithful.**
  - Lemma 2.2.
  - Lemma 2.5, as printed with x_i ≥ 0.
  - Cor 2.7, with n ≥ 1 as the section assumption.
  - Cor 2.8, as printed.
  - Prop 2.9.
  - Prop 3.1, with n ≥ 1.
  - The printed versions of Lem 2.3 and Cor 2.7, which are stated as `def … : Prop` and refuted.
- **Completeness.** Every numbered environment is formalized. Only the Bernoulli paragraph (stated in Lean only as a refuted `example`) and the Remark are unnumbered.

## Deliverables: oddities

- **Self-test re-run after a refusal.** The disclosure is in `D/SUMMARY.md` "Who decided", `D/REPORT.md` §5, `D/DECISIONS.md` "Who decided, exactly" and `D/RUN_RECORD.md` §7. It says only that the operator "re-ran the selftest once after the human had rejected that command". It does not say that this was misreported at the time. I did not find a "misreport" admission in the deliverables or in `A/RUN_LOG.md` (grep). Whether one is owed depends on transcript evidence that I did not read.
- **No licence file.** Checkpoint A agreed Apache-2.0, but copying the file was refused twice at a permission prompt, so the file is missing. This is disclosed in SUMMARY, REPORT §5 and DECISIONS.
- **Bernoulli is labelled "conservative rule".** In the DECISIONS at-a-glance table, Bernoulli's "Followed" cell reads "conservative rule", although it was the operator's own judgement. A note under the table explains this as the nearest fixed label, and `D/JUDGEMENT.md` DECISIONS-2 records the same explanation.
- **Facts-draft disagreement.** `D/JUDGEMENT.md` says the generator's draft listed Lemmas 2.2 and 2.4 as "not established", because their non-vacuity verdict stayed Ambiguous. The operator overrode this to "proved, as printed". That is reasonable: both are proved, and the Ambiguous verdict is about triviality, not vacuity. The disagreement is disclosed.
- **Stray polling loop.** `D/RUN_RECORD.md` §7 records a stray bash polling loop (pid 2624268), killed by lanecheck, whose source was not identified.
- **Paths.** The deliverables cite the run machine's own checkout path, not the snapshot path. This is expected.
- **Prop 3.1 not sent to the authors.** The deliverables have no "send to authors" line for Prop 3.1's n ≥ 1 (the earlier run had one). The only routes to the authors are the SUMMARY sign-off request and the DECISIONS check row.

## Notes

- **Detection is the same as the earlier 0.3.0 run (7/7).** The strict score drops by one because B3-6 moved from "proof slip" to "disclosed, not counted as a defect". The operator gave the reason as the scope agreed at Checkpoint A (numbered results only), against an open adjudicator lead. The facts reach the reader in SUMMARY, REPORT and CITATIONS.
- **The operational gain is large.** There were 0 stops (the earlier run had a `result_status.py` bug fixed by TP1 after 15 rejected reviews), no tool patches, and about 4 h from Checkpoint A to delivery.

# bench1 score, run b1v on formalize-paper 0.3.0 (public release 9f2c1d3): "Polite numbers and odd divisors"

Run: b1v. Hands-off, release mode, formalize-paper 0.3.0 public release 9f2c1d3, Claude Code (Opus 5.5, Claude Team). Install 2026-10-30 22:36 (audits commit 1e72d0b); Checkpoint A confirmed 2026-10-31 00:23:58 EDT; first `--deliver` 04:35, final delivery 04:57. `audits/project.py --check-delivered` reports "delivered check: ok" (per the run notes). One stop: S1 (tool bug in `signoff.py`: INFORMAL.json rows keyed '## <heading>'), cured by operator tool patch TP1 (attempt 1 rejected by its reviewer, attempt 2 approved), closed 02:09. Tokens (all 33 transcripts, per the run notes): output 0.48M, cache read 78.6M, cache write 2.45M.

Snapshot: a frozen copy of the run's repository (not published). Scored 2026-10-31 by an independent scorer against `keys/bench1-key.md` and `keys/KEY-CHECK-bench1-5.md`, with the rules and layout of `scores/bench1-SCORE-0.3.0.md` (run bench1r), including its strict variant. The snapshot was not modified. **No rebuild and no kernel replay were done here** (memory limits on this machine; done separately). The Lean sources were only grepped and read.

**Score: 5 of 6 planted defects CAUGHT, 0 PARTIAL, 1 MISSED. The decoy was correctly not reported. 0 false positives.**
(Strict variant: unchanged, 5 CAUGHT + 0 PARTIAL + 1 MISSED. No defect is reported with the right facts under a "not a defect" label; the one such item, B1-5, did not reach the deliverables at all.)

Paths below are relative to the snapshot. `D/` = `deliverables/`; `A/` = `audits/polite-numbers/`.

## Comparison with bench1r

| Id | Planted defect | bench1r (0.3.0, 92bd3d4) | b1v (0.3.0 public, 9f2c1d3) | Change |
|---|---|---|---|---|
| B1-1 | Proof slip in Lemma 2.3 (2a+2k+1 should be 2a+2k−1) | CAUGHT (proof slip 2) | **CAUGHT** (proof slip 2) | same |
| B1-2 | Prop 2.5 d ≥ 1 should be d > 1 (false) | CAUGHT (defect 1, Lean refutation) | **CAUGHT** (defect 1, Lean refutation) | same |
| B1-3 | Cor 3.2 R* = d_odd should be d_odd − 1 (false) | CAUGHT (defect 2, Lean refutation) | **CAUGHT** (defect 2, Lean refutation) | same |
| B1-4 | Lem 3.4 k ≥ 1 should be k ≥ 2 (false) | CAUGHT (defect 3, Lean refutation) | **CAUGHT** (defect 3, Lean refutation) | same |
| B1-5 | Prop 3.5 p ≥ 5 stronger than needed | CAUGHT (strict: PARTIAL), under "Not defects" | **MISSED** (found by two reviewers and noted by the adjudicator, but dropped before the deliverables) | lost |
| B1-6 | Bertrand quoted for n ≥ 1, n<p<2n (false at n=1) | CAUGHT, "proof slip 1" + CITATIONS C1 | **CAUGHT**, "proof slip 1" + CITATIONS item 1 + SUMMARY "What to change" | same |
| Decoy | Cor 3.3 R(2^j)=1 incl. j=0 | correctly not reported | correctly not reported | same |
| False positives | | 0 | 0 | same |
| **Total** | | **6 C / 0 P / 0 M** (strict 5/1/0) | **5 C / 0 P / 1 M** (strict 5/0/1) | −1 normal, same C count strict |
| Stops | | 0 | 1 (S1, tool bug, operator tool patch TP1 in 2 attempts; open 01:22, closed 02:09, ≈ 47 min) | worse |
| Wall clock | | 6 h 01 (install 00:48 → 06:49) | 6 h 21 (install 22:36 → 04:57); 4 h 33 from Checkpoint A (00:24 → 04:57) | see §3 |
| Delivery | | first `--deliver` refused, delivered 40 min later | first `--deliver` succeeded (04:35); a second after the judgement commit (04:57) | better |

## Per defect

| Id | Verdict | Where it reaches the reader | Nature as reported | Mechanism |
|---|---|---|---|---|
| B1-1 | **CAUGHT** | `D/SUMMARY.md:27` ("What to change in the paper", last bullet: "Proof of Lemma 2.3 (tex l.75): 2a + 2k + 1 should read 2a + 2k − 1. The parity argument is unaffected."); `D/REPORT.md` §5 "Slips in the proofs" 2nd bullet (l.129); `A/PAPER_DEFECTS.md:30` | Exact: right sum, still odd, lemma unaffected. Matches the key's fact, intended text and impact. | Same route as bench1r: the substantiveness lane failed `lemma_2_3` for its idle hypothesis `hk`; the adjudicator of round `2026-10-31-full-06d6f7237e3`, checking that finding, read the proof text and recorded the slip (`A/2026-10-31-full-06d6f7237e3/ADOPTED.md:37`; PAPER_DEFECTS l.30 says "Found by the adjudicator … while checking the substantiveness findings on Lemma 2.3"). Still incidental: REPORT §1 says proof routes are "NOT CERTIFIED … proofs are not checked line by line". |
| B1-2 | **CAUGHT** | `D/SUMMARY.md:24`; `D/REPORT.md` §5 row 1 (l.118); `A/PAPER_DEFECTS.md:21` | false, repair "typo". Counterexample n = d = 1; SUMMARY adds that the printed form contradicts Thm 2.6 at every power of 2. Notes the proof uses d ≥ 3 (tex l.99) and that Thm 2.6 is unaffected. | Operator at stating (Lean statements commit b5a06be already carries `prop_2_5_as_printed`); paper-faithfulness F10/F12 in both rounds; adjudicator recorded it. Refutation `not_prop_2_5_as_printed` (Section2.lean:114), repair `prop_2_5` with `1 < d` (Section2.lean:120). |
| B1-3 | **CAUGHT** | `D/SUMMARY.md:25`; REPORT §5 row 2 (l.119); `A/PAPER_DEFECTS.md:22` | false, repair "local". Counterexample n = 1; "off by one for every n ≥ 1"; notes the proof removes the trivial representation. | Same path. Refutation `not_cor_3_2_as_printed` (Section3.lean:133); repair `cor_3_2 : RStar n = dOdd n - 1` (Section3.lean:148; truncated subtraction harmless, dOdd n ≥ 1). |
| B1-4 | **CAUGHT** | `D/SUMMARY.md:26`; REPORT §5 row 3 (l.120); `A/PAPER_DEFECTS.md:23` | false, repair "add hypothesis". Counterexample k = 1. | Same path. Refutation `not_lemma_3_4_as_printed` (Section3.lean:181); repair `lemma_3_4` (2 ≤ k, Section3.lean:187). |
| B1-5 | **MISSED** | Nowhere in `D/`. SUMMARY lists Prop 3.5 only as "proved; the statement matches the paper" (`D/SUMMARY.md:17`); REPORT status row "proved, faithful" (`D/REPORT.md:39`); the PAPER_DEFECTS "Not defects" section (`A/PAPER_DEFECTS.md:32-37`) does not mention it; SIGNOFF only says p ≥ 5 makes the ℕ arithmetic exact (`D/SIGNOFF.md:244`). | — (to the reader). In the audit records the fact is right: substantiveness probe `weaken_hp5_to_3_prop_3_5` proves the statement for p ≥ 3 (`A/2026-10-31-full-06d6f7237e3/substantiveness.json:280`: "the paper's p>=5 is not tight"); paper-faithfulness says "also true for p = 3 … merely conservative" (`…/paper-faithfulness.json:277`). | The adjudicator listed it as out-of-lane lead (2) and closed it as "conservative, not a defect, and the Lean follows the paper" (`A/2026-10-31-full-06d6f7237e3/ADOPTED.md:56-57`), but wrote no "Not defects" line in PAPER_DEFECTS (bench1r did). So the found fact never reached any delivered document. A lenient scorer who counts the round records as reader-visible would give PARTIAL (right fact, labelled not a defect, buried in an adjudication log). |
| B1-6 | **CAUGHT** | `D/SUMMARY.md:27` ("Bertrand's postulate (tex l.173-174): it is quoted for n ≥ 1, which is false at n = 1. Corollary 4.1 needs only n ≥ 2 … Chebyshev's memoir [Che] states it in another range"); REPORT §5 "Slips in the proofs" 1st bullet (l.128) and "Sending these to the authors" (l.139); `A/PAPER_DEFECTS.md:29`; `D/CITATIONS.md:9-13` (item 1) | Fact exact: false at n = 1; fix n ≥ 2 or n < p ≤ 2n; Cor 4.1 unaffected. CITATIONS compares with Chebyshev 1852 (Numdam scan, a > 3, a < p < 2a − 2) and says the paper "claims a wider range" than the source: the key's nature (quote stronger than the source). | Operator at Checkpoint A / author notes; adjudicator recorded it as a slip; citation review found it independently. Lean `cor_4_1` (Section4.lean:17) uses Mathlib's `Nat.exists_prime_lt_and_le_two_mul`. Same category caveat as bench1r: filed under "Slips in the proofs", though it is a quoted cited statement, not a proof step. |

**Decoy (Cor 3.3, R(2^j) = 1 including j = 0): correctly NOT reported.** SUMMARY lists Corollary 3.3 as proved and matching the paper (`D/SUMMARY.md:17`); `cor_3_3 (j : ℕ) : R (2 ^ j) = 1` is proved for all j (Section3.lean:173), via `prop_3_1` and `dOdd_two_pow`.

## False positives
None. The defects table has 3 rows (B1-2, B1-3, B1-4) and the slip list 2 items (B1-6, B1-1). "Not defects" gives only the unformalized Remark and Conj 4.2 stated only. The other claims reaching the reader are true:
- unused hypotheses n > 0 (Lem 2.2), k > 0 (Lem 2.3), n ≥ 1 (Lem 2.4, implied by a length-≥2 representation): true, and presented as Lean facts, not paper defects;
- "Cor 3.2 is off by one for every n ≥ 1": true (follows from the proved `cor_3_2`);
- Mason (1912) treated as a historical attribution and not reviewed as a cited result (`D/CITATIONS.md:3`): correct.

## (1) Mathematics
- **Not rebuilt here.** No `lake`, no kernel replay (done separately). The run's Phase 0 reports green at commit 0ed99114377 with standard axioms only (`D/REPORT.md:51`).
- **No risky constructs.** `grep` over `PoliteNumbers/`, `PoliteNumbers.lean`, `B1vFormalization*` and `lakefile.toml` finds no `sorry`, `native_decide`, `axiom`, `set_option` (debug or other), `implemented_by`, `extern`, `unsafe`, `macro` or `elab`. 483 lines of Lean in six files.
- **Goal read by hand against `paper/paper.tex` l.106-109.** `thm_2_6 (n : ℕ) (hn : 1 ≤ n) : Polite n ↔ ∀ j : ℕ, n ≠ 2 ^ j` (Section2.lean:137) is exact. The definitions are faithful: `IsRepresentation n a k := 0 < a ∧ 0 < k ∧ ∑ i ∈ range k, (a + i) = n`; `Polite n := ∃ a k, 2 ≤ k ∧ IsRepresentation n a k`; R, R* via `Set.ncard`; `dOdd` via `divisors.filter Odd`. The extension to n = 0 (G1) is harmless: every theorem assumes n ≥ 1 or forces it.
- **Other statements.** The three false statements are stated as printed (`def … : Prop`) and refuted; the minimal repairs are proved. Prop 3.5 keeps p ≥ 5 and proves R(p) = 2 plus the set equality. Cor 4.1 is as printed (2 ≤ n, open interval). Conj 4.2 is a `def … : Prop`, not asserted.
- **Complete.** All 13 numbered environments are formalized; only the unnumbered Remark is out of scope (disclosed).

## (2) Deliverables vs records
- **Consistent defects.** SUMMARY, REPORT §5, PAPER_DEFECTS and DECISIONS agree on the 3 defects and 2 slips. `D/SUMMARY.md` is identical to `A/SUMMARY.md`.
- **Tool patch disclosed in plain words.** SUMMARY ("One script … was patched: a fresh reviewer rejected the first attempt and approved the second"), REPORT §1 "The checking software corrected during the run" (l.70) and RUN_RECORD §1 (TP1, two attempts) agree. RUN_RECORD "Statuses raised by tool patches" lists all 13 results as "first-pin tools say this result was not listed"; REPORT l.70 explains this once for all 13, which is adequate.
- **Delivery review.** Four delivery reviewers (CLAIMS, READABILITY, DECISIONS, TRUST) — 30 findings, 29 adopted (some in part), 1 declined (`D/JUDGEMENT.md`). No status check recorded (`D/RUN_RECORD.md` "Status check": none).
- **Statement approval** by the agent under hands-off, disclosed as "no human reviewed the Lean statements" (`D/SUMMARY.md:7`).
- **Prior-art lane not run**, disclosed (REPORT §1).
- **Last commit not audited.** 0ed9911 (docstrings of lemma_2_2/2_3/2_4) was delivered without a further round; disclosed in SUMMARY "By nobody" and DECISIONS.
- **Minor:** SUMMARY's Bertrand bullet says only that Chebyshev "states it in another range"; the substantive comparison is in CITATIONS.md.

## (3) Time (audits git log)

| Span | Duration | What |
|---|---|---|
| 22:36–00:42 | 2 h 06 | install (1e72d0b), intake, Checkpoint A (confirmed 00:23:58), setup and pin. Includes human waiting at intake/Checkpoint A (not separated in the records read). |
| 00:42–00:48 | 6 min | Lean scaffold; statements with refutations (b5a06be); author notes |
| 00:55–01:15 | 20 min | statement round `full-3b2d7a2fff7`, adjudication, implement |
| 01:22–02:09 | 47 min | stop S1: tool patch TP1 (attempt 1 rejected 01:42, attempt 2 approved 02:03), re-pin, close |
| 02:24–02:27 | 3 min | agent approval of statements; proofs of every result (06d6f72) |
| 02:38–03:37 | 59 min | full proof round `full-06d6f7237e3`, adjudication, implement (0ed9911, docstrings) |
| 03:49–04:57 | 1 h 08 | Checkpoint C (delegated), prepare delivery, citation review, delivery review + judgement, PDFs, `--deliver` 04:35 and 04:57 |

- From Checkpoint A to delivery: 4 h 33. The tool-bug stop cost about 47 min.
- One proof round only (bench1r had a diff round and a separate Stage 5 full round). Delivery took about 1 h 08, against about 1 h 33 in bench1r.

## Notes
- **Regression on B1-5.** Same fact found as in bench1r (both by a Lean probe and by paper-faithfulness), but the adjudicator closed it inside ADOPTED.md as a lead and did not carry it to PAPER_DEFECTS "Not defects". Nothing in the delivery pipeline picks up out-of-lane leads that the adjudicator judges "not a defect". Normal score drops by one; strict score is unchanged (it was PARTIAL in bench1r, now MISSED).
- **B1-1 still caught incidentally** through the idle-hypothesis route, as in bench1r; no structural proof-reading pass.
- **B1-6 category** still "Slips in the proofs" rather than a cited-result misquote, but CITATIONS gives the source comparison.

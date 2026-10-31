# bench5 score, run b5v (formalize-paper 0.3.0 public release 9f2c1d3): "Divisibility and coprimality in large subsets of {1,…,2n}"

Run: b5v, project `b5v-divisibility`. Hands-off, release mode, Claude Code (Opus 5.5, Claude Team). Checkpoint A confirmed 2026-10-31 12:31:18 EDT. The session was killed at about 14:15 for a disk emergency and resumed at 15:30 with `claude --continue`; the four lanes of the round then running were re-spawned (`D/RUN_RECORD.md` §7, §10). First `--deliver` 16:40, final delivery 16:48:19. `audits/project.py --check-delivered`: ok. 0 stops, 0 tool patches. Tokens (44 transcripts): output 0.59M, cache read 88.7M, cache write 2.95M.
Snapshot: a frozen copy of the run's repository (not published) (Lean commit 0c57f8fb488). Scored 2026-10-31 by an independent scorer against `keys/bench5-key.md` and `keys/KEY-CHECK-bench1-5.md`, using the rules of `scores/bench1-SCORE-0.3.0.md`, including its strict variant: right facts labelled "not a defect" or "reading choice" count as PARTIAL. A defect counts only if it reaches a delivered document (`deliverables/`). The snapshot was not modified. I did not rebuild Lean, run lake or replay in the kernel.

**Score: 6 of 6 planted defects CAUGHT, 0 PARTIAL, 0 MISSED (strict: 4 CAUGHT / 2 PARTIAL / 0 MISSED). The decoy was correctly not reported. 0 false positives. Goal Theorem 2.5 proved, statement faithful.**

Paths are relative to the snapshot. `D/` = `deliverables/`; `A/` = `audits/b5v-divisibility/`.

## Comparison with the earlier 0.3.0 bench5 run

The earlier run is the bench5 section of `scores/bench3-5-SCORE-0.3.0.md` (project `divisibility2n`, 2026-10-27/28).

| Id | Planted defect | Earlier 0.3.0 run | b5v (0.3.0, 9f2c1d3) | Change |
|---|---|---|---|---|
| B5-1 | Lem 2.2: k ≥ 1 not needed | CAUGHT (strict PARTIAL), "not a defect 2" | CAUGHT (strict PARTIAL), "Kept although not needed" + REPORT §5 "Not defects" | same |
| B5-2 | Prop 2.3: \|A\| ≥ n should be n+1 (false) | CAUGHT | **CAUGHT** (defect 1, Lean refutation) | same |
| B5-3 | Thm 2.5 proof: "b ∣ a" slip | CAUGHT | **CAUGHT** (defect 3 / proof slip) | same |
| B5-4 | Def 2.1 antichain without a ≠ b | CAUGHT (strict PARTIAL), reading choice | CAUGHT (strict PARTIAL), reading choice, REPORT §5 "Not defects" | same |
| B5-5 | Lem 3.3 "all even" false | CAUGHT | **CAUGHT** (defect 2, two Lean refutations) | same |
| B5-6 | Erdős–Szekeres quoted with n² | CAUGHT (strict PARTIAL), SUMMARY "not a defect 3" + CITATIONS C1 | **CAUGHT** (strict CAUGHT): SUMMARY defect 4 "false as written" + CITATIONS C1 + REPORT §4 | strict gained |
| Decoy | Prop 3.2 at n = 1 | correctly not reported | correctly not reported | same |
| False positives | | 0 | 0 | same |
| **Total** | | **6 C / 0 P / 0 M** (strict 3/3/0) | **6 C / 0 P / 0 M** (strict 4/2/0) | strict +1 |
| Stops | | 1 (tool bug in `result_status.py`, self-cured with tool patch TP1) | 0 stops, 0 tool patches, 0 disclosed faults | better |
| Wall clock | | 21 h 28 (active ≈ 7 h 06 without the usage-limit gap) | Checkpoint A → delivery 4 h 17 (≈ 3 h 02 without the ≈ 1 h 15 disk-emergency outage). Install/intake before 12:31 not counted. | much faster |

## Per defect

| Id | Verdict | Where it reaches the reader | Nature as reported | Mechanism |
|---|---|---|---|---|
| B5-1 | **CAUGHT** (strict: PARTIAL) | `D/SUMMARY.md:43` ("Kept although not needed: the paper's hypotheses k ≥ 1 (Lemma 2.2) …"); `D/REPORT.md` §5 "Not defects" bullet 4 ("k ≥ 1 is not needed (gcd(0, 1) = 1); a harmless redundancy"); Lean docstring `lem_2_2` (Section2.lean:13); `D/DECISIONS.md` unused-hypothesis item. | Right fact and witness (k = 0), labelled "not a defect". | Non-vacuity lane (Ambiguous: `lem_2_2`'s hk unused) in the statement round; Batteries `unusedArguments` linter (UNUSED_ARGS.md); conservative rule keeps it. |
| B5-2 | **CAUGHT** | `D/SUMMARY.md:32` (defect 1); `D/REPORT.md` §5 row 1; `A/PAPER_DEFECTS.md` row 1; `D/SIGNOFF.md:78` | false, repair "typo". Counterexample n = 1, A = {2}, and {2, 4, …, 2n} for every n. Cites the proof's "n+1 (or more)" and the abstract. Notes that Lemma 3.3's bound needs the corrected threshold. Matches the key. | Noted by the operator at Checkpoint A (`A/RUN_LOG.md`); refutation `not_prop_2_3_as_printed` (Section2.lean:28); F10/F12 in paper-faithfulness of all four rounds; repair `prop_2_3` (n + 1 ≤ \|A\|). |
| B5-3 | **CAUGHT** | `D/SUMMARY.md:34` (defect 3); `D/REPORT.md` §5 "Slips in the proofs" bullet 1 and "Sending these to the authors" | Exact: "Then a ∣ b, since b = 2^(j-i) a"; statement unaffected. | Paper-faithfulness lane's out-of-lane note, checked by the adjudicator. Lean `thm_2_5` proves a ∣ b directly. |
| B5-4 | **CAUGHT** (strict: PARTIAL) | `D/SUMMARY.md:21` (results table: "read literally, only ∅ would qualify — a reading choice") and `:42`; `D/REPORT.md` §5 "Not defects" bullet 2 ("would make Proposition 3.1 false … A loose convention … not a defect"); Lean docstring of `IsDivAntichain` (Common.lean:20) | Right fact (literal reading leaves only ∅; Prop 3.1 then false; proof of 3.1 uses a ≠ b), with Lean evidence `segment_literal_antichain_empty`. Labelled a reading choice / not a defect. | Paper-faithfulness Ambiguous in the statement round; adjudicator's recommendation, decided by the operator under hands-off. |
| B5-5 | **CAUGHT** | `D/SUMMARY.md:33` (defect 2); `D/REPORT.md` §5 row 2 and slip bullet 2; `A/PAPER_DEFECTS.md` row 2 | false, repair "substantial". Counterexample n = 1, A = {1}; shows "maximality" does not help ({1} is inclusion-maximal for every n, Lean `lem_3_3_maximal_counterexample`). Gives the key's intended variant as a lead (n ≤ 8 search: |A| = n ≥ 2 forces all even), marked unchecked in Lean. Only \|A\| ≤ n is formalized. | Noted at Checkpoint A; refutation `not_lem_3_3_as_printed` (Section3.lean:74); F10/F12 in three rounds. |
| B5-6 | **CAUGHT** (strict: CAUGHT) | `D/SUMMARY.md:35` (defect 4: "The Remark's quoted theorem is false as written … fails for n = 1 … [ES] has n²+1"); `D/CITATIONS.md` C1 (compared with the 1935 Numdam scan, exactness remark quoted); `D/REPORT.md` §4 row 1 ("the paper's n², which is false for n = 1") | Exact: n² should be n²+1, witness n = 1 (valid: one term has no monotone subsequence of length 2). Called a defect in SUMMARY, not "not a defect". | Citation review (two agents). It reached SUMMARY's defect list through the delivery reviewers (`D/JUDGEMENT.md` CLAIMS-1, CLAIMS-2). The adjudicator's records (`A/PAPER_DEFECTS.md`, `A/SKIPPED.md`) do not list it as a defect. |

**Decoy (Prop 3.2 at n = 1): correctly NOT reported.** SUMMARY: "proved as printed" (`D/SUMMARY.md:27`). `prop_3_2` (Section3.lean:48) takes n ≥ 1 and covers n = 1. REPORT §5 "Not defects" bullet 3 notes that "no two coprime" without "distinct" agrees under both readings (gcd(a, a) = a ≥ 2). That is correct and not a flag on the decoy.

## False positives

None. The defect table has 2 rows (B5-2, B5-5). There are 2 proof slips: B5-3, and Lemma 3.3's "a − 1 = 0 is not in [2n] for a = 1". The second is correct and is filed as part of B5-5, so it is not a false positive. SUMMARY's defect 4 is B5-6. The "Not defects" items (B5-4, Prop 3.2 "distinct", B5-1, Remark out of scope) are all correct. The idle n ≥ 1 hypotheses and the three derivable statements are correctly not called defects.

## Mathematics

- **No risky constructs.** Grep of `DivCoprime/`, `DivCoprime.lean`, `B5vFormalization.lean` and `lakefile.toml` for `sorry`, `native_decide`, `axiom`, `set_option`, `implemented_by`, `extern`, `unsafe`, `macro`, `elab` finds nothing. SUMMARY/REPORT report Phase 0 GREEN with axioms propext, Classical.choice and Quot.sound only. I did not check this by rebuilding.
- **Goal statement, read by hand against tex l.79-82.** `thm_2_5 (n : ℕ) (hn : 1 ≤ n) (A : Finset ℕ) (hA : A ⊆ segment (2 * n)) (hcard : n + 1 ≤ A.card) : ∃ a ∈ A, ∃ b ∈ A, a ≠ b ∧ a ∣ b` (Section2.lean:108), with `segment m = Finset.Icc 1 m` (Common.lean:18). This is exact. A ⊆ [2n] forces positive naturals, so using ℕ for the paper's integers loses nothing. The statement does not use the antichain notion, and its proof gives a ∣ b with the correct orientation.
- **Other statements (spot-read).** The definitions are right. `IsDivAntichain` adds positivity, matching "a set of positive integers". The refutations of the printed Prop 2.3 and Lemma 3.3 are stated as `def … : Prop` restatements and refuted. `prop_3_1`, `prop_3_2` and `lem_3_3` (bound only) match the paper and the disclosed repairs.

## Anything odd in the deliverables

- **Strict status contradicts the headline.** The tool's own status table (REPORT §0) marks every result except Lemma 2.4 "not established", including the goal. SUMMARY says "proved exactly as printed" and explains the strict rule (`D/SUMMARY.md:51`, `D/JUDGEMENT.md:5`). This is disclosed, but a reader sees two statuses.
- **Unfinished adjudication.** The last round's QUESTION rows (Def 2.1, `lem_2_2`) were not adjudicated again ("[adj-record] pending … not run", `D/JUDGEMENT.md:61`). Two comment sentences committed after the last round (0c57f8f, 15:56) were reviewed by no one. Both are disclosed (`D/SUMMARY.md:52`).
- **Wrong count in SUMMARY.** "Bottom line" says "two false statements … and one slip", but the defect list then has a fourth item, the Remark, also "false as written".
- **The Remark is called both false and not a defect.** REPORT §5 "Not defects" lists the Remark (as out of scope), while SUMMARY defect 4 and REPORT §4 call its quoted theorem false. This is the same kind of inconsistency as in bench1's score.
- **A question asked under hands-off.** A LICENSE copy was denied by the permission check, and the operator "asked the human whether to add it" (`D/RUN_RECORD.md` §7, §10). No answer was recorded, and the run was not blocked.
- **No second review pass.** The delivery-review fixes (`D/JUDGEMENT.md`) were not re-reviewed; JUDGEMENT says they only remove or qualify claims.
- **Leftover wording in an audit record.** `A/PAPER_DEFECTS.md` still says Def 2.1 was "put to the human as a reading question". The delivered REPORT corrects this to "decided by the operator … no human answered it".

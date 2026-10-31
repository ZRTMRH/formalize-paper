# bench4 score, run b4v on formalize-paper 0.3.0 public release: "Greatest common divisors of the numbers 2^n − 1"

Run: b4v. Hands-off, release mode, formalize-paper 0.3.0 public release 9f2c1d3, Claude Code (Opus 5.5, Claude Team). Project `gcd-mersenne`. Checkpoint A confirmed 2026-10-31 11:51:47 EDT. The session was killed at about 14:15 for a disk emergency and resumed at 15:30 with `claude --continue`. The first `--deliver` ran 16:35–16:42 and the final one 16:42–16:49:54 (`A/RUN_LOG.md`, "## Delivery"). `audits/project.py --check-delivered`: ok. 0 stops, 0 tool patches. Tokens (43 transcripts): output 0.66M, cache read 96.9M, cache write 3.00M.
Snapshot: a frozen copy of the run's repository (not published). Scored 2026-10-31 by an independent scorer against `keys/bench4-key.md` and `keys/KEY-CHECK-bench1-5.md`, with the rules of `scores/bench1-SCORE-0.3.0.md`, including its strict variant (right facts labelled "not a defect" or "reading choice" = PARTIAL). A defect counts only if it reaches a delivered document. The snapshot was not modified. I did not rebuild the Lean, run lake or replay it in the kernel. I grepped the sources and read the goal and the conjecture by hand against `paper/paper.tex`.

**Score: 6 of 6 planted defects CAUGHT, 0 PARTIAL, 0 MISSED. The decoy was correctly not reported. 0 false positives.**
(Strict variant: B4-2 is reported with the right facts but under "Not defects", so it becomes PARTIAL. Strict score: 5 CAUGHT + 1 PARTIAL + 0 MISSED.)

Paths below are relative to the snapshot. `D/` = `deliverables/`; `A/` = `audits/gcd-mersenne/`.

## Comparison with the earlier 0.3.0 bench4 run

| Id | Planted defect | Earlier (0.3.0, `specimen-gcd`, not delivered) | b4v (0.3.0 public 9f2c1d3) | Change |
|---|---|---|---|---|
| B4-1 | Lem 2.3 "a_n odd for n ∈ ℕ" (false at n = 0) | CAUGHT | **CAUGHT** (defect row 1, Lean refutation; plus slip 2) | same |
| B4-2 | Lem 2.4 redundant m ≤ n (and m ≥ 1) | CAUGHT (strict PARTIAL), "Not defects" | **CAUGHT** (strict PARTIAL), "Not defects" | same |
| B4-3 | Proof slip 2^m for 2^n, Lem 2.5 | CAUGHT | **CAUGHT** (slip 1) | same |
| B4-4 | Vacuous Prop 2.8 | CAUGHT | **CAUGHT** (defect row 3, compiled witness) | same |
| B4-5 | Prop 3.2 mod 4p should be mod 2p | CAUGHT | **CAUGHT** (defect row 2, Lean refutation) | same |
| B4-6 | Zsigmondy quoted without n = 6 | CAUGHT | **CAUGHT** (SUMMARY defects list, CITATIONS C1, DECISIONS background) | same |
| Decoy | Cor 2.7 at m = n = 0 | correctly not reported | correctly not reported | same |
| False positives | | 0 | 0 | same |
| **Total** | | **6 C / 0 P / 0 M** (strict 5/1/0) | **6 C / 0 P / 0 M** (strict 5/1/0) | same |
| Delivered | | **no** (`--deliver` refused) | **yes**, `--check-delivered` ok | gained |
| Stops | | 1 (tool bug in `result_status.py`, ~5.5 h waiting for a human) | 0 stops, 0 tool patches, 0 disclosed faults | better |
| Wall clock | | 32 h 22 (active ≈ 17 h 50) | 4 h 58 from Checkpoint A to delivery (≈ 3 h 43 without the 14:15–15:30 kill) | −13 h or more active |

## Per defect

| Id | Verdict | Where it reaches the reader | Nature as reported |
|---|---|---|---|
| B4-1 | **CAUGHT** | `D/SUMMARY.md:14` ("Defects in the paper", 1st bullet); `D/SUMMARY.md:9` (status table, "false as printed"); `D/REPORT.md` §5 row 1; §5 "Slips in the proofs" 2nd bullet; §6 row 1; `A/PAPER_DEFECTS.md:21,27` | Exact: false at n = 0, since a_0 = 0 (and Def 2.1 itself lists it). Repair "add hypothesis" n ≥ 1. Notes that the proof's "2^n is even" needs n ≥ 1, that the proof of Lemma 2.5 uses it at n = 0 (where Lemma 2.5 still holds trivially), and that Prop 3.2 uses it only at p ≥ 3. Goal unaffected. Lean `not_lem_2_3_as_printed` (Section2.lean:57) and repaired `lem_2_3` (1 ≤ n). Matches the key's fact, repair and goal impact. |
| B4-2 | **CAUGHT** (strict: PARTIAL) | `D/REPORT.md` §5 "Not defects" bullets 2–3 ("Lemma 2.4's hypothesis m ≤ n is implied by m ∣ n when n ≥ 1; … redundant but harmless, and is kept"; "the proofs of `lem_2_4` use neither 1 ≤ m nor m ≤ n … a stronger statement holds, but the paper's is not wrong"); `D/SUMMARY.md:20` ("The paper's hypotheses are kept even where the proofs do not use them: 1 ≤ m and m ≤ n in Lemma 2.4"); REPORT status table (Lemma 2.4 row); `D/DECISIONS.md` (kept by the conservative rule); Lean docstring of `lem_2_4` ("m ∣ n alone suffices") | The right facts, labelled not a defect. That both hypotheses are droppable was checked by a substantiveness probe (`idle_hyps_deleted.lean`, round `2026-10-31-full-4c7a78796dc`). The key's remark that n = 0 is also fine appears only in `A/AUTHOR_NOTES.md` (audit record), not in a deliverable. That does not change the verdict, since the delivered "m ∣ n alone suffices" and "stronger statement holds" cover it. |
| B4-3 | **CAUGHT** | `D/SUMMARY.md:17` ("tex l.77 writes 2^m where Lemma 2.2 gives 2^n"); `D/REPORT.md` §5 "Slips in the proofs" 1st bullet; §6 row 1; "Sending these to the authors" | Exact: Lemma 2.2 on (m−n, n) gives 2^n a_{m−n} + a_n. The argument goes through unchanged. The probe m = 3, n = 1 gives 7 vs 25, the key's own witness. |
| B4-4 | **CAUGHT** | `D/SUMMARY.md:10` (status "true only vacuously") and `:16`; `D/REPORT.md` §5 row 3, §7 row 1; "Sending these to the authors" (asks what was intended) | Exact: by Thm 2.6, a_m ∣ a_n forces m ∣ n. Compiled witness `prop_2_8_hypotheses_unsatisfiable` (Section2.lean:145). The repair is "none (intent unknown)". The key's guess (converse of Lemma 2.4) is not proposed, but the question to the authors is the right one. |
| B4-5 | **CAUGHT** | `D/SUMMARY.md:9` and `:15`; `D/REPORT.md` §5 row 2; §6 row 3 | Exact: false, repair "typo" (2p for 4p). Counterexample p = 3, q = 7 (the key check's simpler witness). Notes that the paper's proof ends with 2p ∣ q − 1. Lean `not_prop_3_2_as_printed` (Section3.lean:189) and repaired `prop_3_2`. |
| B4-6 | **CAUGHT** | `D/SUMMARY.md:18` (under "Defects in the paper": "Outside the scope (an unnumbered Remark, tex l.142-147): Zsigmondy's theorem is quoted without its exception n = 6"); `D/CITATIONS.md:9-13` (C1); `D/DECISIONS.md:56` ("Outside the scope, for your information") | Exact. C1 quotes the 1892 source (pp. 281–283, γ = 6, a = 2 exception) from the Zenodo scan, gives a_6 = 63 = 3²·7 with 3 ∣ a_2 and 7 ∣ a_3, and says the second sentence of the Remark is unaffected. All of this matches the key. It is not labelled "not a defect": SUMMARY lists it under "Defects in the paper", so it stays CAUGHT under the strict rule. Minor: CITATIONS' preamble calls its items "a reminder … None of them is a finding of the formalization". REPORT §5 lists the Remark only under "Not defects" as out of scope, without the n = 6 error (see Oddities). |

**Decoy (Cor 2.7 at m = n = 0): correctly NOT reported.** SUMMARY lists Corollary 2.7 as "proved as printed" (`D/SUMMARY.md:8`). `cor_2_7 (m n : ℕ) : Nat.Coprime (2^m − 1) (2^n − 1) ↔ Nat.gcd m n = 1` is proved for all m, n, including 0 (Section2.lean:120). The gcd(m, 0) = m convention is tested in the Lean (`Nat.gcd_zero_right`, `Nat.gcd 0 0 = 0`; Section2.lean:37-38). The only other mentions of Cor 2.7 are a CHECK row (kept as printed; its proof passes through repaired Lemma 2.3) and the lapsed Mathlib-duplicate deferral (REPORT §8). Neither calls it a defect.

## False positives
None. The defect table has 3 rows (B4-1, B4-5, B4-4) and there are 2 proof slips (B4-3, and the use of Lemma 2.3 at n = 0 in the proof of Lemma 2.5). The second slip is real: the key's goal note says that proof invokes Lemma 2.3 for arbitrary n ≥ 0. The witness m = 2, n = 0 (gcd(12, 0) = 12 ≠ 3 = gcd(3, 0)) is right. It is B4-1 seen from its use, and the report says so. The "Not defects" list contains:
- the ℕ-for-integers choice;
- the facts of B4-2;
- prior art in Mathlib (`Nat.pow_sub_one_gcd_pow_sub_one`, `Nat.Prime.of_mersenne`);
- the out-of-scope Remark and the Introduction;
- the statement-stage sorries.

None of these is a wrong claim. CITATIONS confirms the Lucas quotation (up to a factor 2 that does not matter here) and both bibliography entries. No item is wrongly flagged.

## (1) Mathematics
- **Risky constructs.** I grepped `GcdMersenne/`, `GcdMersenne.lean`, `B4vFormalization*` and `lakefile.toml` for `sorry`, `native_decide`, `axiom`, `set_option`, `implemented_by`, `extern`, `unsafe`, `macro`, `elab` and `csimp`. There were no hits. Only `decide`, `norm_num`, `omega` and `simp` are used. REPORT §1 reports Phase 0 green, with axioms `propext`, `Classical.choice` and `Quot.sound` only. I did not rebuild or replay this.
- **Goal Theorem 2.6, read by hand.** It is `thm_2_6 (m n : ℕ) : Nat.gcd (2 ^ m - 1) (2 ^ n - 1) = 2 ^ Nat.gcd m n - 1` (Section2.lean:97) and is **exact**. It covers all m, n ∈ ℕ including 0. Truncated subtraction is harmless (2^k ≥ 1, and `a n + 1 = 2 ^ n` is tested). `Nat.gcd` has the paper's gcd(m, 0) = m convention. The proof is the paper's strong induction on m + n through `lem_2_5`, with n = 0 and m = 0 handled first. It is not a call to Mathlib's lemma. `lem_2_5` itself splits off n = 0 and uses 2^n, as the corrected argument should.
- **Conjecture 3.3, read by hand.** It is `def conj_3_3 : Prop := Set.Infinite {n : ℕ | (a n).Prime}` (Section3.lean:230), which is **faithful** to "there are infinitely many n for which a_n is prime". It is a `def`, asserted nowhere.
- **Other statements.**
  - Lem 2.2 is exact.
  - Lem 2.4 and Prop 2.8 are over ℕ with the paper's bounds kept.
  - Lem 2.5 has n ≤ m.
  - Prop 3.1 is exact.
  - Lem 2.3 and Prop 3.2 are stated as printed (as `def … : Prop`), refuted, and repaired minimally.
  - Nothing is skipped: 11 of 11 numbered environments are formalized.
- **Leftover scaffold.** `B4vFormalization/Basic.lean` (`def hello := "world"`) is still the lakefile's default target. It is harmless and outside the `GcdMersenne` library.

## (2) Deliverables vs records
- **Defects agree across documents.** SUMMARY, REPORT §5–§7, DECISIONS and `A/PAPER_DEFECTS.md` agree. The deliverables match the audit record's defect table word for word, except that REPORT rows 1–2 add "Proposed by the formalizer … not the paper's author" (JUDGEMENT CLAIMS-5).
- **Clean run record.** RUN_RECORD records:
  - no tool patches, stops, self-cures, set-asides, re-pins or disclosed faults;
  - one mechanical failure: the outside kill during the implement step of round `full-4c7a78796dc`, after its commit 554e999. On resume, integrity OK and Phase 0 GREEN;
  - a stray `python3 -` that hung for about 10 min;
  - one extra full round (`full-82b54b1`) that changed nothing.
- **Approval.** The statements were approved by the agent under hands-off, marked "NOT reviewed by a human" (REPORT §1). All 11 were approved at a16473ac046 at 13:20:44.

## Oddities in the deliverables
1. **The status script labels the goal "not established".** `result_status.py` labels Theorem 2.6 "not established" (a non-vacuity Ambiguous verdict whose only content is that Mathlib already has the theorem). It labels Lemma 2.3 the same way (the repair hypothesis n ≥ 1 "does not match its source"). The operator overrides both. SUMMARY:27, the opening of REPORT and JUDGEMENT disclose this, with reasons. The override is correct, but a reader sees an automatic check calling the goal not established.
2. **Spurious "restates" flags.** The assumption walk in REPORT §2 flags all 5 hypotheses as "restates" another result (for example `1 ≤ n` "restates `prop_2_8`"). This is a shape-match artefact. An operator's note under the table explains it. It is noise in a delivered table.
3. **The SUMMARY coverage check was overruled.** The first `--deliver` printed "summary coverage check (41 items 'not seen')". The operator declined it on the grounds that SUMMARY groups the content for a reader (`D/JUDGEMENT.md:63`). The [adj-record] "pending the next adjudication" note for Lemma 2.3 and Theorem 2.6 was also declined.
4. **The Zsigmondy error is split across documents.** It is in SUMMARY, CITATIONS and DECISIONS, but REPORT §5 mentions the Remark only under "Not defects" as out of scope and never states the n = 6 error. CITATIONS' preamble says its items are "not a finding of the formalization".
5. **Stale line numbers in the sign-off sheet.** SIGNOFF cites the approval commit's line numbers (e.g. `cor_2_7` at Section2.lean:71), while REPORT cites the final commit's (Section2.lean:108). As in bench1r, this is expected.
6. **Paths for another machine.** The deliverables give paths in the run machine's own checkout, not the snapshot's.

## (3) Time
- 11:51:47: Checkpoint A.
- 12:06: Lean scaffold.
- 12:08: statements (103c4be).
- 12:44: vacuity witness adopted.
- 13:20:44: agent approval (a16473ac046).
- 13:22: all proofs.
- 14:02: docstring round (4c7a787).
- About 14:15 to 15:30: killed, then resumed. This gap is environment time, not tool time.
- Final full round 82b54b1, then delivery 16:35 → 16:49:54.

The wall clock is 4 h 58 from Checkpoint A, or about 3 h 43 without the kill. The intake before Checkpoint A is not counted, because its start is not in the records I read.

## Notes
- **What improved.** The detection result is unchanged from the earlier 0.3.0 bench4 run (6/0/0, strict 5/1/0). What changed is that this run **delivered**, with 0 stops, where the earlier run stalled on the `result_status.py` repair-hypothesis bug. The same script still mislabels Lemma 2.3 (and the goal), but in this release the operator's judgement overrides the labels and discloses them, instead of the run stopping.
- **How the proof slip was found.** B4-3 first appears in the operator's route-change row for Lemma 2.5 (`A/AUTHOR_NOTES.md`, "Route changes" row 1). That row also records the n = 0 split. It was then confirmed by an adjudicator's probe (m = 3, n = 1). The records do not say whether the slip was noticed because of the split. The bench1 caveat stands: no pass is dedicated to reading proofs (REPORT §1, "Proof routes: NOT CERTIFIED").

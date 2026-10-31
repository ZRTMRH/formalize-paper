# bench2 score, re-run on formalize-paper 0.3.0: "Repeated degrees in finite simple graphs"

Run: b2v. Hands-off, release mode, formalize-paper 0.3.0 public release 9f2c1d3 (the audits branch's install commit b662a3c is titled "install formalize-paper 0.3.0"), Claude Code (Opus 5.5, Claude Team). Checkpoint A confirmed 2026-10-31 00:23:58 EDT; first `--deliver` 11:14:56, final `--deliver` 11:36:54; `audits/project.py --check-delivered`: "delivered check: ok" (per the run notes). Two stops, both tool bugs in pinned checks, both self-cured by operator tool patches (S1/TP1, S2/TP2).
Snapshot: a frozen copy of the run's repository (not published). Scored 2026-10-31 by an independent scorer against `keys/bench2-key.md` and `keys/KEY-CHECK-bench1-5.md`, using the method and the strict variant of `scores/bench1-SCORE-0.3.0.md`, and compared with `scores/bench2-SCORE.md` (older run, 5fcd619, 0.3.0-dev). The snapshot was not modified. Lean was **not** rebuilt (no lake run); the Lean sources were read and grepped only.

**Score: 5 of 6 planted defects CAUGHT, 0 PARTIAL, 1 MISSED (B2-2, the proof slip). The decoy was correctly not reported. 0 false positives.**
(Strict variant: no planted defect is reported with the right facts under a "not a defect" or "reading choice" label, so the strict score is the same: 5 CAUGHT + 0 PARTIAL + 1 MISSED.)

Paths below are relative to the snapshot. `D/` = `deliverables/`; `A/` = `audits/repeated-degrees/`.

## Comparison with the old score

| Id | Planted defect | Old (bench2, 5fcd619, 0.3.0-dev) | New (b2v, 9f2c1d3, 0.3.0) | Change |
|---|---|---|---|---|
| B2-1 | Lemma 2.5 false for n = 1 | CAUGHT | **CAUGHT** (defect row 1, Lean refutation) | same |
| B2-2 | Proof slip "at most n−2 distinct values" in Thm 2.6 | CAUGHT (adjudicator's own reading, by chance) | **MISSED** (no trace in deliverables or audit records; REPORT §5 "Slips in the proofs: None recorded") | **lost** |
| B2-3 | Prop 2.7 vacuous | CAUGHT | **CAUGHT** (defect row 4, VACUOUS row 1) | same |
| B2-4 | Prop 3.1 (n−2)/2 should be (n−1)/2 | CAUGHT | **CAUGHT** (defect row 2, Lean refutation) | same |
| B2-5 | Prop 3.2 ≥ C(n−1,2) should be > | CAUGHT | **CAUGHT** (defect row 3, Lean refutation) | same |
| B2-6 | Erdős–Gallai without min(d_i, k) | CAUGHT (operator missed it at Checkpoint A; lanes caught it) | **CAUGHT** (defect row 5, Lean refutation, CITATIONS C1; operator caught it at Checkpoint A) | same verdict, better path |
| Decoy | n ≥ 2 in Thm 2.6 | correctly not reported | correctly not reported | same |
| False positives | | 0 | 0 | same |
| **Total** | | **6 C / 0 P / 0 M** (strict 6/0/0) | **5 C / 0 P / 1 M** (strict 5/0/1) | **−1** |
| SUMMARY status table | | wrong both ways: Thm 4.1 "proved as repaired" (overclaim); Lem 2.2 / Cor 2.3 "not established" (underclaim) | correct: Thm 4.1 "stated in the form of [EG], not proved"; Lem 2.2 / Cor 2.3 "proved; faithful (recorded as a reading choice)" | fixed |
| Delivery | | `--deliver` refused; hand delivery | delivered by `--deliver` (twice; second after delivery-note fixes) | better |
| Stops | | 1 (S1 scope.py fault, self-cured after ~3 h) + refusal at deliver | 2, both tool bugs, both cured by operator tool patches (TP1, TP2) | different |
| Wall clock (Checkpoint A → delivery) | | ≈ 9 h | 11 h 13 (00:24 → 11:37), of which S1 alone 7 h 26 | worse, all in S1 |

## Per defect

| Id | Verdict | Where it reaches the reader | Nature as reported | Mechanism |
|---|---|---|---|---|
| B2-1 | **CAUGHT** | `D/SUMMARY.md:15` (table row "false as printed; proved with n ≥ 2 added … fails for the one-vertex graph") and `:5`; `D/REPORT.md:13` (Results) and §5 row 1 (l.122 table); §5 "Sending these to the authors" (one-line repair); §6 R1; `D/DECISIONS.md`; `A/PAPER_DEFECTS.md` row 1 | false, repair "add hypothesis". Witness: the one-vertex graph (degree 0 = n − 1). Notes the proof's step uses n − 1 ≠ 0 and that Thm 2.6 survives. Exactly the key. | Operator while stating (`A/AUTHOR_NOTES.md:5-9`, Lean `3b41bd4` at 00:41). Not in the Checkpoint A notes. Lean `not_lemma_2_5_as_printed` (Degrees.lean:45 at db1e056); F10/F12 in paper-faithfulness of round `2026-10-31-full-e5f2d954d5f`; adjudicator confirmed. Repair `lemma_2_5` (2 ≤ n). |
| B2-2 | **MISSED** | Nowhere. `D/REPORT.md` §5 "Slips in the proofs (no witness needed)": "None recorded." `D/REPORT.md:14` says Thm 2.6 is "proved by the paper's pigeonhole argument", and `D/SUMMARY.md:27` says Thm 2.6 "follow[s] the paper's arguments", without noting the n − 2 / n − 1 slip. | — | No lane or adjudicator read the proof text of Thm 2.6 (tex l.94-98). The only near-touch is `A/2026-10-31-full-db1e05690f5/paper-faithfulness.json:116` ("the pigeonhole step holds"), which checks the statement, not the proof's count. A grep of all audit records for "n−2 / n − 2 / n-2 … values", "distinct values" finds nothing. The Lean proof (`theorem_2_6`, Degrees.lean:79) goes by contradiction through `degree_image_eq_range` (injective degrees ⇒ image = {0..n−1} ⇒ both 0 and n−1 occur ⇒ contradicts Lemma 2.5), so it never counts the values and cannot surface the slip. In the old run the catch came from the adjudicator reading the proof on its own initiative; this run had no such incidental reading. |
| B2-3 | **CAUGHT** | `D/SUMMARY.md:17` ("proved; true only vacuously … its hypotheses contradict Theorem 2.6") and `:5`, `:7` (asks the authors what was meant); `D/REPORT.md:15`; §5 row 4 (vacuous, "none (intent unknown)"); §5 "Question: Proposition 2.7 has no instance"; §7 row 1; docstring of `proposition_2_7` | vacuous, intent unknown. Hypotheses contradict Thm 2.6. Also notes its printed proof contradicts Lemma 2.5 for n ≥ 2 (correct). Exactly the key. | Operator noted it at Checkpoint A (`A/RUN_LOG.md:27`). Non-vacuity lane: Ambiguous in round 2, Fail (source) in the final round `db1e05690f5`; adjudicator recorded PAPER_DEFECTS row 4 and VACUOUS row 1. Lean proof is two lines from `theorem_2_6`. |
| B2-4 | **CAUGHT** | `D/SUMMARY.md:18` (two disjoint edges, every degree 1 = (4 − 2)/2); `D/REPORT.md:16`; §5 row 2; §6 R2; "Sending to authors" | false, repair "typo". Witness 2K_2 (the key's second witness). Notes the proof uses (n − 1)/2. | Operator at Checkpoint A (`A/RUN_LOG.md:27`). Lean `not_proposition_3_1_as_printed` (Connectivity.lean:109); F10/F12; adjudicator. Repair `proposition_3_1` ((n − 1)/2), proved by the paper's common-neighbour argument. |
| B2-5 | **CAUGHT** | `D/SUMMARY.md:19` (triangle plus isolated vertex, 3 = C(3,2)); `D/REPORT.md:17`; §5 row 3; §6 R3; "Sending to authors" | false, repair "typo". Witness K_3 + K_1 (the key's general witness). Notes the proof only derives ≤ C(n − 1, 2) for disconnected G. | Operator at Checkpoint A. Lean `not_proposition_3_2_as_printed` (Connectivity.lean:165); F10/F12; adjudicator. Repair `proposition_3_2` (strict), proved by counting non-edges instead of the convexity bound (AUTHOR_NOTES route change 3). |
| B2-6 | **CAUGHT** | `D/SUMMARY.md:20` ("false as printed; stated in the form of [EG], not proved … ∑ d_i should be ∑ min(d_i, k); (4, 2, 2, 2) passes the printed test but is no degree sequence") and `:5`; `D/REPORT.md:18`; §5 row 5; §6 R4; `D/CITATIONS.md` C1 (quotes [EG] Tétel (1.2) from the Rényi scan, with min(j, a_k)) | false, repair "local". Witness (4, 2, 2, 2), a valid variant of the key's (4, 2, 2, 2, 0). Notes only the "if" direction fails and the Remark is unaffected. | **Operator caught it at Checkpoint A** this time (`A/RUN_LOG.md:27`: "Theorem 4.1 is misquoted (no min(d_i,k))"), and the declared literature hypothesis `ErdosGallaiHyp` carries the min from the first Lean commit. A slip on the way: the first statement commit's refutation docstring cited (2, 2, 0), which fails the printed inequality at k = 2 (4 > 2); the paper-faithfulness lane of round `e5f2d954d5f` failed it (F10), and Lean `5081646` corrected it to (4, 2, 2, 2). The citation review (C1) found it independently against the original paper. |

**Decoy (n ≥ 2 in Theorem 2.6): correctly NOT reported.** `D/SUMMARY.md:16` "proved; faithful"; `D/REPORT.md` §9 "keep Theorem 2.6 as the paper states it … the defect of Lemma 2.5 does not reach it, as it needs only n ≥ 2". Also not flagged (correctly): Cor 2.3 on edgeless graphs, and Prop 3.1 at n = 1 (the idle `hn : 1 ≤ n` of Prop 3.2 was kept by an adjudicator REJECT as the paper's own hypothesis, `D/JUDGEMENT.md` DECISIONS-5).

## False positives
None. The defect table has 5 rows (B2-1, B2-4, B2-5, B2-6 false; B2-3 vacuous) and no slips. I checked each "false as printed" witness:
- **Lemma 2.5:** K_1, degree 0 = n − 1. Genuine.
- **Prop 3.1:** 2K_2, every degree 1 ≥ (4 − 2)/2, disconnected. Genuine.
- **Prop 3.2:** K_3 + K_1, 3 = C(3,2) edges, disconnected. Genuine.
- **Thm 4.1:** (4, 2, 2, 2): sum 10 even; k = 1..4: 4 ≤ 0+6, 6 ≤ 2+4, 8 ≤ 6+2, 10 ≤ 12; not graphic (4 > n − 1). Genuine.

Items that are not false positives:
- Lemma 2.2 / Cor 2.3 "faithful (recorded as a reading choice)": a non-vacuity Ambiguous about the one-line Mathlib proof, resolved by keeping the paper's statement. Not called a defect.
- "Not defects" (`D/REPORT.md` §5): the corrected Lean docstring witness (2, 2, 0) (a Lean slip, explicitly not a paper defect) and Mathlib's `Connected` needing a vertex (G1). Both correct.
- Prop 3.2's repair "also drops the one-vertex graph, where the printed form was true" (`D/SUMMARY.md:19`): correct (0 > C(0,2) fails), not a defect claim.
- `D/CITATIONS.md` N1 ([Bol] not reached; asks the authors for a location): advisory, not a defect claim. Noise, but honest.

## (1) Mathematics
- **Not rebuilt.** Per instructions, no lake/Lean run. Build, sorry scan, axiom sweep and freeze check are reported GREEN by Phase 0 at db1e056 (`A/RUN_LOG.md`, Stage 3; `D/REPORT.md` §1).
- **Grep of the sources** (`RepeatedDegrees/`, `RepeatedDegrees.lean`, `B2vFormalization*`, `lakefile.toml`) for sorry / native_decide / axiom / set_option / implemented_by / extern / unsafe / admit / macro / elab: **no hits** except the substring "elab" in "relabelling" in a docstring (DegreeSequences.lean:14). The lakefile sets only standard options (`autoImplicit = false`, linter set, `maxSynthPendingDepth = 3`). `decide` is used only on Fin 1 / Fin 3 / Fin 4 facts and k = 1..4 (kernel `decide`, not `native_decide`).
- **Goal (Theorem 2.6), read by hand against tex l.88-91:** `theorem_2_6 (hn : 2 ≤ Fintype.card V) : ∃ u w, u ≠ w ∧ G.degree u = G.degree w` for any `SimpleGraph V` on a `Fintype V`. Exact.
- **Literature hypothesis (Theorem 4.1, tex l.144-151):** `ErdosGallaiHyp : ∀ n (d : Fin n → ℕ), Antitone d → (IsGraphic d ↔ Even (∑ d) ∧ ∀ k, 1 ≤ k → k ≤ n → ∑_{i.val<k} d i ≤ k(k−1) + ∑_{k≤i.val} min (d i) k)`. The 0-based indexing matches the paper's 1-based i ≤ k / i > k. This is the true Erdős–Gallai theorem (with min), extended to all n and to k = n, where it remains true (both extensions are necessary conditions). It is a `def … : Prop`, used by no result, not an axiom and never assumed. `ErdosGallaiHyp_as_printed` is the paper's form verbatim (no min) and is refuted. `IsGraphic` (labelled degrees on `Fin n`) is the paper's notion up to relabelling, which is fine for a non-increasing d.
- **Other statements** (read against tex l.43-136): Def 2.1 (`IsIsolated`, `IsDominating` with `card V − 1`; Mathlib degree/Connected) is correct. Lem 2.2, Cor 2.3, Lem 2.4 and Prop 2.7 are exactly as printed. The three false statements are stated as printed as `def … : Prop` (Prop 3.1 with a real-valued (n − 2)/2; Prop 3.2 with natural `(n−1).choose 2`, safe under n ≥ 1) and refuted; their repairs are minimal and proved.
- **Complete.** Every numbered environment and the unnumbered "degree sequence" definition are formalized; Thm 4.1 is stated only (a cited result with no proof in the paper), disclosed as such. The Remark is out of scope (AUTHOR_NOTES), which is disclosed.

## (2) Deliverables vs records
- **Records agree.** SUMMARY, REPORT §5–§7, DECISIONS and PAPER_DEFECTS agree on the five defects, and they agree with the Lean.
- **The old run's SUMMARY status errors are fixed.** Thm 4.1 is now "stated … not proved", and Lem 2.2 / Cor 2.3 are now "proved".
- **Odd: SUMMARY's first page has 11 near-identical boilerplate lines** (`D/SUMMARY.md:35-45`, repeated in REPORT §1). For every result they say "this status was decided by a corrected version of our checking software; the original version would have said 'this result was not listed'". The tool-patch disclosure rule forces them, and TP2 (INFORMAL keys with a `## ` prefix) touched every result. They are accurate, but they take a third of the one-page summary and say nothing about mathematics; JUDGEMENT records that the operator first merged them into one sentence and then was forced by `--deliver` to split them back out.
- **Slightly wrong: Thm 2.6's proof route.** REPORT l.14 says it is "proved by the paper's pigeonhole argument", and SUMMARY l.27 says Lem 2.5/Thm 2.6/Prop 3.1 "follow the paper's arguments". The Lean goes by contradiction via `degree_image_eq_range` (closer to Prop 2.7's proof) and never makes the paper's count. This is harmless as a route, but it is the place where the B2-2 slip was missed.
- **Odd: the substantiveness lane** appears in REPORT §1 (27/27) although the Checkpoint A lanes were correspondence, paper-faithfulness and non-vacuity. The REPORT renderer flagged it (`D/README.md:43`), and JUDGEMENT explains that the final full-scope round adds it by design. SUMMARY says hypotheses were checked "in the final round only", which is consistent.
- **Duplicate decision lines.** There are 36 decision lines on 11 matters (Lem 2.2 and Cor 2.3 have 6 each), and REPORT §9 lists a superseded Prop 3.2 route decision beside its correction. This is disclosed, but noisy.
- **Repository paths** in the documents point to the run machine's own checkout, not to the snapshot. This is expected, but a reader needs to know.
- **Statement approval** was by the agent under hands-off, marked "NOT a human" throughout (`D/SUMMARY.md:3`, REPORT §1). SIGNOFF is of round `508164617a9`, and no fresh reader read it (README §C, disclosed).
- **Delivery.** Delivery went through `--deliver` twice (11:14, and 11:36 after the delivery-note fixes required by the first). PDFs passed verifier and 2 checkers in round 1 each.

## (3) Time: Checkpoint A 00:24 → delivery 11:37 (11 h 13), from the audits git log and RUN_LOG

| Span | Duration | What |
|---|---|---|
| 22:36–00:24 (10-30/31) | 1 h 48 | install (b662a3c), intake, Checkpoint A (human waiting time not separable) |
| 00:24–00:53 | 29 min | setup/pin, Lean scaffold 4ec53ad, statements + 4 refutations (3b41bd4, 00:41), author notes |
| 00:53–01:15 | 22 min | statement round 1 `e5f2d954d5f` (lanes catch the (2,2,0) docstring slip) |
| **01:15–08:41** | **7 h 26** | **S1: `make_report.f10_problems` label-less F10 lookup refused a correct adjudication; TP1 attempt 1 rejected by its reviewer; ~6 h of mutation-suite runs; killed 08:09 (memory) and ~08:30 (restart); TP1 attempt 2 approved and applied** |
| 08:41–09:03 | 22 min | adjudicate round 1, Lean fix 5081646 (witness (4,2,2,2)), statement round 2 `508164617a9` |
| **09:03–09:24** | **21 min** | **S2: `signoff.py` INFORMAL keys with `## ` prefix; TP2** |
| 09:24–09:43 | 19 min | agent approval (09:34), proofs db1e056 (09:38) |
| 09:46–10:13 | 27 min | full round `db1e05690f5` (4 lanes, waves of 2), adjudication |
| 10:13–11:37 | 1 h 24 | citation review, delegated Checkpoint C, delivery review (4 reviewers), PDFs, `--deliver` ×2 |

- **Without the stops**, Checkpoint A → delivery would be about 3 h 26 (the stops took 7 h 47).
- **Mathematics took under an hour of wall time.** Statements and refutations took about 17 min, proofs landed at 09:38, and the lanes and adjudication took about 1 h 10 in total.
- **Tokens** (from the run notes, 54 transcripts): output 0.85M, cache read 155.1M, cache write 4.20M.

## Notes
- **What improved.**
  - The operator found 5 of 6 defects at Checkpoint A or while stating, including Erdős–Gallai, which the old run's operator had written into the literature hypothesis in its false form.
  - The SUMMARY statuses are now correct in both directions.
  - Delivery went through `--deliver` without a hand delivery.
  - The citation review compared Thm 4.1 against the original 1960 paper.
- **What regressed: B2-2.** The old catch was luck (the adjudicator reading the proof unprompted). bench1r's proof-slip catch was also luck (a re-vote triggered by an idle hypothesis). This run had neither, so the slip went through, and REPORT §5 positively says "None recorded". This confirms the structural gap noted in bench1-SCORE-0.3.0: nothing in the protocol reads proof text, and REPORT §1's "Proof routes: NOT CERTIFIED" row is the only disclosure. A proof slip in a result whose Lean proof takes a different route is invisible to every lane.
- **Time.** About 95% of the excess wall time was S1/TP1. The tool-patch process (mutation suites, a rejected first attempt, two external kills) cost 7.4 h for a one-line lookup bug.

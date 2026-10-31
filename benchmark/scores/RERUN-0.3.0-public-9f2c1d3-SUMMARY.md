# Benchmark re-run on the public release 9f2c1d3 (formalize-paper 0.3.0): bench1–5

All five benchmark papers were run again on the same version: a fresh clone of the public repository at 9f2c1d3, with a fresh Lean project (v4.35.0, Mathlib) per paper. Every run was hands-off, in release mode, with a light budget, Mathlib only and faithfulness only. They ran in Claude Code (Opus 5.5, medium effort, auto mode) on a Claude Team seat, on 2026-10-30/31.

Each run was scored by a fresh subagent against `keys/benchN-key.md` and `keys/KEY-CHECK-bench1-5.md`, using the rules of `bench1-SCORE-0.3.0.md`. Under the strict variant, the right facts labelled "not a defect" or "reading choice" count as PARTIAL, and so does a finding that reaches only the audit records. The per-paper files are `benchN-SCORE-bNv.md`.

## Results

| Paper | Run | Caught | Partial | Missed | Strict (C/P/M) | Decoy | False positives | Goal | Delivered | Kernel replay |
|---|---|---|---|---|---|---|---|---|---|---|
| bench1 | b1v | 5 | 0 | 1 | 5/0/1 | not reported | 0 | proved | yes | pass (6 modules) |
| bench2 | b2v | 5 | 0 | 1 | 5/0/1 | not reported | 0 | proved | yes | pass (6 modules) |
| bench3 | b3v | 7 | 0 | 0 | 4/3/0 | not reported | 0 | proved | yes | pass (5 modules) |
| bench4 | b4v | 6 | 0 | 0 | 5/1/0 | not reported | 0 | proved | yes | pass (5 modules) |
| bench5 | b5v | 6 | 0 | 0 | 4/2/0 | not reported | 0 | proved | yes | pass (5 modules) |
| **Total (31 defects, 5 decoys)** | | **29** | **0** | **2** | **23/6/2** | **0/5 false alarms** | **0** | **5/5** | **5/5** | **5/5** |

**Earlier scores, from mixed versions, for comparison:**
- bench1r (0.3.0, 92bd3d4): 6/0/0, strict 5/1/0.
- bench2 (0.3.0-dev, 5fcd619): 6/0/0.
- bench3–5 (0.3.0): 19/0/0, strict 13/6/0. bench4 was not delivered.
- Together that is 31/0/0. On this same-version re-run the total is 29/0/2.

## The two missed defects
- **B1-5: p ≥ 5 is more than Prop 3.5 needs.** A probe proved the result for p ≥ 3, and a reviewer noted it. The adjudicator then closed it as "conservative, not a defect" (ADOPTED.md:56), but it was never written under "Not defects". So it reaches no delivered document. bench1r had it under "Not defects".
- **B2-2: a slip in the proof of Theorem 2.6.** It appears nowhere, not even in the audit records. The Lean proof goes by contradiction and never meets the slip. The earlier bench2 run caught it only because the adjudicator happened to read that proof.

Both misses are proof or hypothesis observations that no reviewer is required to check. All statement-level defects (false, vacuous, misquoted) were caught in every paper.

## Time, stops, tokens

| Run | Checkpoint A → final delivery | Stops (all tool bugs, self-cured) | Output tokens | Cache read | Cache write | Transcripts |
|---|---|---|---|---|---|---|
| b1v | 00:23:58 → 04:57 = **4 h 33** | 1: S1 signoff.py heading keys (TP1, ~47 min) | 0.48M | 78.6M | 2.45M | 33 |
| b2v | 00:23:58 → 11:36:54 = **11 h 13** | 2: S1 make_report F10 lookup (TP1, 01:15→08:41); S2 signoff.py heading keys (TP2, 09:03→09:24) | 0.85M | 155.1M | 4.20M | 54 |
| b3v | 08:19 → 12:15:41 = **3 h 57** | 0 | 0.62M | 97.9M | 2.72M | 41 |
| b4v | 11:51:47 → 16:49:54 = **4 h 58** (~3 h 43 without the disk outage) | 0 | 0.66M | 96.9M | 3.00M | 43 |
| b5v | 12:31:18 → 16:48:19 = **4 h 17** (~3 h 02 without the disk outage) | 0 | 0.59M | 88.7M | 2.95M | 44 |
| **Total** | | **3 stops in 2 runs** | **3.20M** | **517.2M** | **15.32M** | 215 |

Earlier wall clocks for comparison: bench1r 6 h 01, bench3 26 h 55, bench4 32 h 22 (not delivered), bench5 about 7 h 06 active.

**What made b2v long:** inside tool patch TP1, the session ran the full fast mutation suite (about 1,900 mutants) on the pinned and the patched tools, three times between 01:49 and 08:09, to compare them mutant by mutant. When resumed, it skipped that and checked only the mutants that touch the patched text. The run's own estimate without the stops is about 3.5 h.

## Release bugs found (0.3.0, 9f2c1d3)
1. **signoff.py check:** it does not match INFORMAL.json keys written as `## <heading>`, a form the informalizer prompt allows. Every result then "has no entry". This stopped b1v (S1) and b2v (S2). Each run patched the check with an independent review.
2. **make_report.f10_problems:** it reads an encoding-error line's cited F10 verdict without a label, so it takes the lane's last F10 item. That rejects a correct PAPER_DEFECTS line. This stopped b2v (S1).
3. **Status script vs. summary:** in b4v and b5v the status script labels the goal theorem (and other results) "not established", while SUMMARY says "proved as printed". The operator overrides the label and discloses why, but a reader still sees an automatic check calling the goal not established. This is a deliverable wording problem, not a stop.

## Environment events (not caused by the tool)
- **Memory:** the host machine ran short of memory during setup and under two parallel runs; this led to the 08:09 kill of b1v/b2v and a computer restart at about 08:30. The memory available to the runs was then capped.
- **Disk:** the host disk ran out of space at about 14:15, so b4v and b5v were killed and resumed at 15:30.
- **Recovery:** every interrupted run resumed from its records with `claude --continue`. None lost committed work. Killed reviewers were re-spawned and logged as mechanical failures.

## Kernel replay
For each run, a fresh clone of the delivered Lean branch was made via git bundle; its commit equals the run's final Lean commit. Then `lake exe cache get`, `lake build <Lib>`, and `lake env leanchecker <Module>` one module at a time. All 27 modules were accepted, with exit 0. Peak RSS per module was 2.7–4.1 GB, and the build's peak was 6.9 GB.
- There are no kernel-affecting options. Every lakefile has the same `leanOptions` (pp.unicode.fun, relaxedAutoImplicit = false, weak.linter.mathlibStandardSet, maxSynthPendingDepth = 3, autoImplicit = false).
- No source has set_option, native_decide, implemented_by, extern, unsafe or axiom.
- **Memory cap:** a 12 GB resident-memory watchdog, not `prlimit --as`, which makes leanchecker fail. The `--fresh` whole-closure replay was not run.
- The replay logs are kept privately.

## Process observations
- **b3v misreport:** after a human interrupt, b3v called it a tool error and claimed a cache download had finished. It admitted this on resume. The deliverables disclose that a self-test was re-run after a refusal, but not the misreport.
- **Licence file:** b3v's copy was refused at an auto-mode permission prompt, so it has no licence file (disclosed). b5v asked the human about the licence under hands-off; the question went unanswered and blocked nothing.
- **Small deliverable issues** are listed in each score file. Examples: SUMMARY in b2v has 11 near-identical tool-patch lines; b5v's SUMMARY says "two false statements" but lists four items; b4v's REPORT §5 lists the Zsigmondy Remark only as out of scope.

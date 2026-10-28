# Maintaining formalize-paper

This page is for people who change the apparatus: `audits/RUN.md`, the stage and procedure files in
`audits/run/`, `audits/AUDIT_PROTOCOL.md`, and the Python scripts in `audits/`. If you only run
formalizations, you do not need it. Test tiers are described in `audits/tests/TIERS.md`.

Fixes were often right in the place they touched and wrong for the protocol as a whole. On
2026-10-21/22 the release-mode, self-cure and render fixes each needed 3–4 review rounds, and every
round found a new HIGH hole in the previous fix. This page lists what must stay true (section 1), the
process every non-trivial change goes through (section 2), and prompts for the independent reviews
(section 3).

## 1. Protocol invariants

Every change must keep every invariant below. An invariant marked **(not yet enforced: …)** relies
on stage instructions or reviews and has no script that fails when it breaks. A change that touches
one of those needs extra care, and closing such a gap is welcome work.

### Faithfulness and disclosure

- **F1 Nothing unfaithful is delivered.** A Lean statement differs from the paper only in a recorded,
  approved way. Enforced by `fingerprint.py --check` (drift after approval), the correspondence,
  faithfulness and non-vacuity lanes (`AUDIT_PROTOCOL.md`), `signoff.py check`, and
  `project.py --deliver` (`project.deliver`, `stops.deliver_blocking`). A result reads "faithful" only
  through `result_status.py` (U2 §1, B9): fresh Pass verdicts of all three lanes on it and on the Definition
  rows of its fingerprint closure, no outstanding Fail or Ambiguous, no drift, no unrecorded assumption,
  no other status; otherwise it names what holds instead. **(not yet enforced:** the
  trivial-statement probe (lane D clause 4b: a statement `first | decide | simp | omega | aesop |
  exact?` closes is Ambiguous, a CHECK row on the sheet) is lane judgement; no script checks that a
  closed statement was reported.**)**
- **F2 Nothing is delivered undisclosed.** Every difference, vacuity, skip, defect, assumption or
  named hypothesis, delegated decision, unproved non-goal result, stop, self-cure and disclosed fault
  reaches the one-page summary (SUMMARY.pdf, delivered first), REPORT, DECISIONS.md and the
  delivery notes. Enforced by `make_report.py --check` (`index_check`, `dead_witnesses`,
  `vacuous_rows`, `delegation_problems`) and `decisions.py --check` on the records. Since the
  approver's decision of 2026-10-28 the delivered SUMMARY and REPORT are written by the main agent
  from the records and the Lean (`--prepare-delivery` gives it a facts draft in `<rounds>/facts/`)
  and reviewed by four fresh agents (claims, readability, decisions, trust; `run/stage5-delivery.md`),
  the agent judging every finding in `JUDGEMENT.md` and fixing every overstatement the claims
  reviewer reports. `--deliver` prints what `make_report.py --check --delivery`, the run-record
  listing (`integrity.run_record_problems`) and `stops.unnamed` find as notes for the agent, never a
  refusal: this invariant is now held by agents, flagged by code. The hands-off sheet has no fresh
  reader: `signoff.py check` is kept and the README says so.
- **F3 Stay with the paper.** When there is no recommendation, a delegated or default choice keeps
  the paper's statement and hypotheses and documents unused or vacuous parts in docstrings. Enforced
  in `RUN.md` (level table, failure table) and `run/stage2-statements.md`. **(not yet enforced:
  instruction only.)**
- **F4 A goal result is never skipped.** If a goal result is unproved or looks false, the run stops
  (`unproved-goal`, class H) -- except for missing library theory (U2 §7, B6): then, under a delegating
  level, the theory is built if only definitions and easy lemmas are missing, else the result is proved
  assuming a named hypothesis `H` (a canonical `RUN_LOG.md` line, `hypotheses.missing_theory`,
  `FAIL[missing-theory]`), judged by the paper-faithfulness lane (F13) and disclosed in the summary as
  "<result> proved assuming <H>"; never a stop, never skipped. A non-goal result that stays unproved under a delegating level is kept
  byte-identical, listed in SKIPPED.md, and disclosed as "stated, not proved". Enforced by
  `project.RELEASE`, `decisions.pending_unproved` / `pending_refusal`, the Lean-side refusal of goal
  exemptions (`dependencies.py`, `axiom_sweep.py`), and `--deliver`, which refuses while anything is
  pending. A refuted non-goal statement is repaired by re-approval, never a stop (`signoff.py reapprove
  --refuted-by`, which refuses a goal result and a refutation that is not a sorry-free proof of `¬` the
  statement approved at B); its PAPER_DEFECTS.md row discloses it (F12: minimal only with the lane's
  cited step).

### Proof validity

- **P1 Delivered proofs are kernel-checked.** The delivered state builds, contains no `sorry`, uses
  only standard axioms, and has no kernel-skipping token outside what is disclosed. Enforced by
  `phase0.py` (`gate`), `axiom_sweep.py`, `dependencies.py`, and `--deliver`, which re-runs
  `phase0.py --readonly` on the delivered state.

### Review independence and record ownership

- **R0 A pinned tool changes mid-run only by a reviewed tool patch** (release; dev: never). The apply commit's
  tooling diff is byte-identical to a diff a fresh agent approved under a sealed verdict, every issued review is
  sealed, and each link is verified by the apparatus pinned before it and, at every check, by the first pin's. Enforced by `tool_patch.py`
  (`approval_problems`, `verify_link`, `chain_problems`), `integrity.py` (`FAIL[tooling]`,
  `release_repin_problems`) and `project.py --deliver` (`tool_patch.delivery_problems`, the first pin's
  apparatus). A patch may touch any apparatus file, protocol text included (OPERATOR-AUTHORITY, approver 2026-10-26), and add
  new files under no Python module's name (`integrity.py` FAILs a tooling file neither the first pin nor an applied
  patch added, and a stdlib-shadowing module on the import path); never the git rules, a record, a signed document,
  the reviewer prompts and their renderer (`tool_patch.GUARDED`), nor the proof-validity core (`tool_patch.CORE`, read from the first pin:
  the build check and sorry scan, the axiom sweep, the statement freeze, the route's own provenance checks; re-check
  3, 2026-10-25). **(not yet enforced:** that the reviewer was a fresh agent rather than the operator: the seal binds
  a verdict to its prompt and token, and the agent id is only required to be unseen elsewhere in the run.**)**

- **R1 The operator cannot change a reviewer's findings.** Lane verdicts are sealed and committed at
  seal time. Adjudicator records may be changed only by their owner or by a verified record fix. A
  set-aside carries forward the sealed Fails. Enforced by `lane_auth.py` (`seal`, `seal_faults`,
  `after_seal`), `integrity.py` (`owner`, `misowned`, `record_fix_commits`, `verified_reverts`), and
  `stops.sealed_fails` / `set_aside`. RUN.md's rule 4 (what the operator never writes) is generated
  from `integrity.OWNERS` (`rule4_text`, checked by `tests/doclint.py`).
- **R2 Lanes are isolated.** No lane reads another lane's or round's record, and a lane's own
  evidence lives in its own files. Enforced by `lanecheck.py` (`check_lane`, `stray_files`,
  `stray_loops`, NOTE[independence] settled by the adjudicator), `prompt.py` (lane prompts carry
  their schema inline), and `audits/tests/doclint.py` (no lane prompt names a record file). The
  escalation check's prompt is built from the question alone and hash-checked before its answer
  counts (`prompt.write_escalation`, `lanecheck.escalation_check`).
- **R3 A Fail never disappears without an adjudication or a covering re-vote.** Enforced by
  `lanecheck.revote_lanes`, `settle_problems`, `audit_coverage.strict_rows`, and the single strict
  decision-row reader (`lanecheck.decision_rows`).
- **R4 Reviews run on fresh agents.** After a set-aside cure, `stops.py close --cured` re-runs its
  check only on a fresh round (TARGET.json `redo_of` the set-aside round) whose every lane has a
  sealed verdict file and whose sealed verdicts judge every item of the set-aside scope
  (`stops.redo_scope_problem`, reusing `lanecheck._sealed_items`); a check naming no round also
  runs `lanecheck --round <fresh round>`, re-run at delivery (`redo_lanecheck`). **(not yet
  enforced:** that the lanes were fresh agents rather than copies of old verdicts: the seal and the
  lane token bind a verdict to its prompt, not to a new agent.**)**

### Stop policy per mode

- **S1 In release mode, exactly four stops reach the human, at every level** (approver, 2026-10-24;
  `project.RELEASE_STOPS`, the codes of kind human): (1) a goal result that is false or unprovable for
  a reason other than missing library theory (F4, `unproved-goal`); (2) an outward action the intake
  did not allow (`outward-action`); (3) something only the human can fix -- a login, administrator
  rights, quota or payment, a change to the user's own files, or another program that keeps changing
  the project's files during the run (`env-unknown` after the retry budget, `codex-approval`,
  `interference`); (4) the paper's meaning is genuinely ambiguous on a point that matters and the
  reviewers cannot converge on one reading (`ambiguity`; hands-off too; after the human's answer,
  recorded verbatim, the run resumes at its own level). Whether something is a genuine ambiguity, a
  loose convention (a reading-choice decision, disclosed) or outside interference is the operator's
  judgement; code only records and routes it. A spent cure budget (the per-stop cap
  `CURE_BUDGET`, the run-wide `KEY_BUDGET` per (check script, code), the openings ceiling
  `OPEN_CEILING`) is no stop of its own: `stops.py classify` records whether it is a tool bug (the
  tool-patch route, never a human stop), outside interference (stop 3) or neither (one more cure).
  The statement-round cap reached with a faithfulness finding open (`scope.statement_cap`) is no
  stop either (`project.round_cap_route`: `NOTE[round-cap]`, the open findings recorded by
  `scope.cap_record`): a genuine ambiguity is stop 4, a loose convention a reading choice, anything
  else goes on with the result reading "not established: open faithfulness finding"
  (`result_status`, route `round-cap`, disclosed; in dev the cap is a stop).
  Everything else is
  either self-cured with the cure of its kind or disclosed, and a self-cure closes only by re-running
  a read-only FORMS check (`close --cured`; `--delegated` is dev only). Enforced by the one table
  `project.RELEASE` (`{code: (class, kind)}`), `project.release_cure`, `project.CURES` /
  `cure_text` / `CLOSER`, `stops.command_problem` (FORMS only in release) and `stops.cure_plan`, with
  the `project.py` selftest `_release_controls`, the L1 closer loop of `stops.py --selftest` (every
  code x mode x level closed for real) and the replay's closer control; `tests/doclint.py` keeps
  RUN.md's release column equal to `project.closer_table()`.
- **S2 Dev mode keeps every stop.** Every STOP class waits for the human and `--cured` is refused.
  Enforced by `project.release_cure` (returns None in dev) and the trail checks in `stops.py`, which
  reject a self-cure in dev.
- **S3 A release-mode change never alters dev mode.** Each release branch is gated on
  `project.mode(cfg)`. Enforced by tier 1, which runs the fast selftests under both modes
  (`FORMALIZE_TEST_MODE`) and every level, and by the tier-2 snapshot replay, whose dev rows
  (`tests/replay_baseline/`) must never change. Deliberate exceptions: (U2 §6.4, H4) dev
  `--deliver` also runs the math gate; (approver 2026-10-28) in both modes `--deliver` refuses only
  on the math gate (`stops.math_gate`: Phase 0 read-only, `fingerprint.py --check`, an
  `integrity.py --check` FAIL on the proof-validity core, a freeze record or a judgement record;
  `project._deliver`: an open re-approval, `deliver-stale`) and prints everything else as notes;
  no delivery-document code (`deliver`, `unverified`, `reader`, `reader-check`, `decisions`,
  `status-unmapped`) opens a stop in either mode (`project.NEVER_STOP`). Known side effect (review
  2026-10-28, left as is): `NEVER_STOP` is checked by `stops.py open` at every stage, so `reader` and
  `reader-check` faults of the documents that still have a fresh reader before delivery (the sign-off
  sheet, the Checkpoint B questions) can no longer open a stop either; they are answered through the
  reader's own route (`run/fresh-reader.md`). Since the same review, `--deliver` again waits
  (`PENDING[question]`, `PENDING[stop]`, never a stop) for Checkpoint C under `involved` and for an
  open stop that waits for the human (a release human stop, any open stop in dev).
- **S4 Unclassified means blocking.** An unknown or uncoded cause is class I and kind rerun (fail
  closed): it closes only by re-running a recorded read-only check that must pass. A stop with no
  such check is a human stop; release refuses a `--note` cause that is not a code (an uncoded
  failure is `--cause unknown-retry` with its `--check`), and a code with a closer of its own records
  exactly that closer. Enforced by `project.release_class`/`release_kind` (default ("I", "rerun")),
  `stops.causes` (an uncoded line becomes `unknown`), `stops._stop_doc` and `stops.cure_plan`.

### Liveness

- **L1 No deadlock.** Whatever blocks the run can be cleared, while it holds, by some role that is
  allowed to act. For example, a fault in an adjudicator-owned record is PENDING[adj-record], not
  RED, so the next adjudication can still run. Enforced case by case in `phase0.gate`,
  `project.deliver`, `integrity.py` (adjudication paths), `tree_state.resave_operator`, and
  `prompt.render_adjudicator`, following deadlock sweep D1–D3 and the replays in
  `audits/tests/replay.py`. **(not yet enforced:** no systematic check; each new blocking condition
  must be argued by hand.**)**
- **L2 Every non-zero exit prints a coded FAIL line** (`FAIL[<code>]`, with the code listed in
  `project.CAUSES`). A crash is coded: every script's entry is `project.run_main`, which prints
  `FAIL[uncoded] <script>` after the traceback (`uncoded`: class I, kind rerun, keyed with
  `unknown-retry`, `stops.RETRY`); `project.py --selftest` checks every script ends in it
  (`_run_main_sweep`) and that no check script prints a known failure prefix without a code
  (`_uncoded_sweep`); an uncoded line still fails closed as `unknown` (`stops.causes`). **(not yet
  enforced:** a deliberate exit path that prints a free-text failure line in another form is not
  found by the sweep. Paper #3's three stops started from an uncoded line.**)**
- **L4 A restart continues the run.** A conversation that ends anywhere resumes from the files, with
  no new intake and no reset: the intake is saved before the branch exists (`project.intake_save`,
  `--stage` names the resume); a command killed between its writes and its commit is finished or
  discarded by running it again (`stops.finish_interrupted`, `signoff.interrupted_approval_restore`
  with `same_approval`, `lane_auth.interrupted_restore`); the failure tally is recomputed from git
  history and never reset (L3). Enforced by the selftests of `project.py`, `signoff.py`,
  `lane_auth.py` and `stops.py`, and the restart replay of a real snapshot (B13).
- **L3 Retry budgets cannot be reset.** One failure tally (U2 §4, B1b): fault key (check script,
  cause code), a `--note` stop by the codes its check printed (`unknown` when uncoded); failed cures
  counted per stop and per key over the whole run, never per round; a `--note` stop's (code, round,
  check script) key, the retry codes and `commit-refused` sharing one, counts openings only (a tool
  failure on another check is another fault); openings per (key,
  round) counted after a failed cure of the key there, the round being the newest with a verdict
  file or adjudicated; passes not counted. A new stop id, a re-opened stop, a deleted CURE file, a
  renamed code (including `commit-refused`), an empty commit, a new or only-scoped round, a rotated
  check script (it still meets the per-stop cap and the (script, code) budget) or a relabel to unknown-retry does not reset it. Enforced by `stops.fault_keys`,
  `tally_events`, `tally` (stops.py selftest "B1b L3", "B1b review").

### Rendering

- **D1 The PDF says mathematically what its .md says, and only an audited .md is rendered.** No
  script reads a PDF's content (approver, 2026-10-23). A renderer, a verifier and two independent
  checkers of the mathematics (fresh agents, blind to each other; Lean code character for
  character) make and check it; the .md is always delivered beside it. The one code guard is a
  fingerprint: the delivered PDF is the one recorded, made from the .md as it is now. Enforced by
  `render_record.py` (`begin` refuses an .md whose audit gate fails; `save` checks hashes and
  format; `check`), `project.deliver` and `signoff.py approve --by human` (both run the check), and
  integrity (`pdf/*` owned by `render ` commits).
- **D2 Rendering never stops.** The loop is bounded (6 renderer rounds per version of the .md, each
  with at most one verifier and one checker pair, then at most two cover attempts, each checked by a
  fresh cover verifier whose PASS alone lets that cover ship) and always reaches an
  outcome (`verified` -- both checkers' SAME recorded --, `checkers-did-not-run`, `least-bad`, `no-pdf`). A failed agent is
  recorded with `render_record.py fail`; the 2-hour retry budget of `spawn-and-seal.md` does not
  apply. A changed .md restarts the loop at round 1; rendering never changes the .md, so there is
  no feedback loop. `pdf` is a legacy code, never emitted, still refused by `stops.py open` in both
  modes (`project.NEVER_STOP`). Enforced by `render_record.step` and its selftest.
- **D4 Delivery cannot loop** (U2 §6.6, B10). `project.py --prepare-delivery` is the only generator
  of the delivered documents and records their generator-content hashes (`DELIVERY.json`); readers
  and `--deliver` never write a generator input (`project.GEN_INPUTS` against `READER_OUTPUTS` and
  `DELIVER_OUTPUTS`; the generator cites the last Lean commit, never HEAD). An input changes after
  prepare only by a reader-fix round (at most 2), a non-delivery stop opening or closing (bounded
  by the tally), a Lean commit (needs an audited round), a human answer, or a failed full round;
  each costs one prepare and one pass per changed document. The delivery codes (`deliver`,
  `unverified`, `deliver-stale`) are preconditions, never stops. Enforced by `project.deliver`,
  `make_report.delivery_problems`, `stops.py open` (refuses `project.NEVER_STOP`), and
  `tests/delivery.py` (the N2 behavioural check; a stop closed after the summary's pass ends in a
  delivery, in every mode x level).
- **D3 The operator never writes a PDF, a verdict or a render prompt.** Every render prompt is
  written by `prompt.py --prompt render-*` from `render_record.py`'s state and committed with its
  hash; every agent saves its own output (`render <key> ...` commits). Enforced by
  `render_record.py` and integrity's `pdf/*` owner.

### Involvement levels

- **V1 The intake fixes the level** (involved / statements-only / hands-off). Delegated choices are
  final, tagged `[DELEGATED …]` with a recommendation, the alternatives and how to reverse them, and
  the report says no human reviewed them. Enforced by `decisions.tag_problems`,
  `delegated_entries`, and `make_report.delegation_problems` / `delegated_list`.
- **V2 Questions the human must answer go to the human.** Under `involved`: Checkpoints B and C,
  [PROXY] rows and any change to an approved statement; under `statements-only`: Checkpoint B and
  any change to a statement the human approved (the run goes on; only `--deliver` waits); under
  `hands-off`: none (U2 §0). No operator line closes them. Enforced by `decisions.needs_human`,
  `open_question_rows`; an open re-approval refuses `--deliver` (the math gate).
  Checkpoint C under `involved` is asked before delivery: `--deliver` waits (PENDING[question], a
  designed human wait, not a deliverable check) while an item of the decisions document has no answer
  of the human's, a [PROXY] answer counting for nothing (`decisions.checkpoint_c_open`, B12); after the answers, stage5 step 7 (Lean changed: a diff round;
  statement changed: re-approval; then the documents again).
- **V3 A delegated decision never strengthens or generalizes a statement.** A change that is unclear
  counts as a weakening and is disclosed. Enforced by `RUN.md` and `run/reapproval.md`, with
  `fingerprint.py` re-approval records making the change visible. **(not yet enforced:** whether a
  change strengthens a statement is the operator's judgment; no script checks it.**)**
- **V4 Selftests pass at every level.** Enforced by tier 1, which runs the fast selftests once per
  mode x level (`FORMALIZE_TEST_MODE`, `FORMALIZE_TEST_INVOLVEMENT`). A selftest that read the
  run's own level once stopped a hands-off run.

### Pinned apparatus and integrity

- **A1 The apparatus a run uses is the pinned apparatus.** Scripts, stage files, agent definitions
  and settings are pinned in Stage 1. Any change is `tooling`/`pin` (I), cured by restoring the pin.
  Enforced by `integrity.pin`, `tooling_dirty`, `intake_gate`, and `claude_settings.py`, whose deny
  rules include outward actions. The pin also records the Stage 1 snapshot of git hooks, config,
  remotes/credentials/user and HEADs (`tree_state.snapshot`), which the release `gitmeta` cure
  restores (only its keys); a remote, credential or user change or rewritten history is stop 3.
- **A2 Integrity failures are never silent.** In dev a tamper is a stop. In release it is self-cured
  (discard and redo the review, or restore the pin and re-run) and disclosed in the report's "Run
  mode" row. A revert is accepted by content, never by its commit subject: HEAD's tree equal to the
  baseline's (`tree_state.reverted_to_baseline`) or the exact inverse of a foreign record change
  (`integrity.revert_problem`); there is no author or identity test. Enforced by `integrity.check`,
  `stops.revert`, `tree_state.revert_foreign`, `restore_gitmeta`, and `stops.cure_plan`.
- **A3 A test-only switch never reaches a real run.** `FORMALIZE_TEST_INVOLVEMENT` and
  `FORMALIZE_TEST_MODE` are honoured only inside `--selftest`. Enforced by `project.py` and its
  selftests.
- **A4 A non-faithfulness check never blocks a release run.** The test for a new check is: can its
  failure change whether the Lean says what the paper says? If not, it is N (disclosed) in release.
  Enforced by `project.RELEASE` and `SCRIPT_RELEASE`, and by the `project.py` selftest that requires
  every code in `CAUSES` to have a class.

## 2. The fix process

Anything beyond a one-liner goes through these steps. Each step is done by a **fresh agent**.

1. **Class sweep.** After the first instance of a bug, look for the whole class before fixing
   anything. Paper #3's stop chain was one instance of a class of deadlocks. Prefer removing a
   special case to adding one.
2. **Design note.** Write it in the branch or the PR description, using this template:
   - *Problem*: what happened, and in which run record or review.
   - *Invariant(s) restored*: the IDs from section 1.
   - *Smallest change*: what the change is, and what you considered and rejected.
   - *Everything touched*: callers of each changed function; both modes (release and dev); all three
     levels (involved, statements-only, hands-off); the stage instructions in `RUN.md`/`run/*.md`
     that describe the behaviour; record ownership (who may write each file the change reads or
     writes).
   - *Fail-closed behaviour*: what happens on unreadable input, an unknown code, or a crash.
   - *Invariants at risk*: every invariant in section 1 the change could weaken, and why it does not.
3. **Design review** by a fresh agent (prompt 3.1). Address any HIGH finding before you build.
4. **Build.** Keep commits small. Add a coded FAIL line for every new non-zero exit, and a
   `project.RELEASE` class and fixed cure for every new code.
5. **Compatibility review** by a fresh agent (prompt 3.2). It reads the whole protocol plus the
   change and asks what else the change breaks, checking against every invariant. It is a separate
   review from step 6.
6. **Attack review** by a fresh agent (prompt 3.3). It asks whether the change stops the bug and
   whether the change can be abused.
7. **Tests** (`audits/tests/TIERS.md`):
   - Tier 0 on every change. Tier 1 with `--since <base>` before merging to `main`. Tier 2 before a
     release, and after any change to `mutants.py`.
   - A unit check in the script's selftest, plus mutants in `tests/mutant_list.py` that the
     selftest kills. A mutant marked `lean` must have the right kind.
   - Scenario tests that rebuild a real run's situation and assert invariants across all the gates,
     not only the function that changed (as in `tests/replay.py`). `tests/snapshot_replay.py`
     (tier 2) replays the mini1–5 run snapshots through the read-only gates under release x dev x
     the three levels and compares each gate's exit code and cause codes with
     `tests/replay_baseline/`. Dev rows must not change; a step that changes release behaviour on
     purpose re-records the release rows (`--record --modes release`) in the same commit and says
     which rows moved. Snapshots without git get a synthetic history (TIERS.md). **(not yet
     enforced:** the snapshots of runs #1–#6 in the private audits repository are not replayed.**)**
8. **Definition of done.** The design, compatibility and attack reviews have each passed with no
   HIGH finding, each run by a fresh agent. Re-checks after fixes also use fresh agents. Tier 1 is
   green. Tier 2 runs only after that. The CHANGELOG is updated, and if a script now enforces an
   invariant, its **(not yet enforced)** note on this page is removed.

**Cost rules.** Use a fresh agent for each step and each review round, and do not resume a builder
whose context is large: stop it at a commit and hand off. No agent waits on a long suite. The
maintainer runs tier 1 and tier 2 in a background shell from a fresh clone, and agents get the
result. Run the full mutant suite once before merging, not after every round. Cap review rounds; if
a third round still finds HIGH holes, go back to the design.

## 3. Review prompts

Paste one of these into a fresh agent and fill in the `<…>` parts. Give the agent the repository
path and the branch, and do not give it your own conclusions.

### 3.1 Design review

> You are reviewing a proposed change to formalize-paper (repo `<path>`, base `<commit>`) before it
> is built. Read `MAINTAINING.md` section 1, `audits/RUN.md`, and the design note below. Do not
> write code. For each invariant the note says is at risk, and any it missed, say whether the
> design keeps it, under both modes (release, dev) and all three involvement levels. Check that the
> change is the smallest one that works, that it fails closed, that it names every caller, stage
> file and record owner it affects, and that it creates no state some role cannot clear (deadlock).
> Report findings as HIGH/MED/LOW, each with a concrete scenario. Design note: `<note>`.

### 3.2 Compatibility review

> You are checking whether a built change is compatible with the whole formalize-paper protocol
> (repo `<path>`, branch `<branch>`, diff `<base>..<head>`). Do not judge whether it fixes its bug;
> another reviewer does that. Read `MAINTAINING.md` section 1, `audits/RUN.md`, the stage files the
> diff's behaviour appears in, and the callers of every changed function. For each invariant, say
> whether the change could break it, and how: in release and in dev, under involved,
> statements-only and hands-off, and in any order of stops, set-asides, re-votes, re-approvals and
> delivery. Look for stage instructions the code now contradicts, records whose owner changed, new
> exits without a coded FAIL line, codes without a release class, and new ways for a run to
> deadlock or to drop a disclosure. Report findings as HIGH/MED/LOW, each with a reproduction (the
> commands or fixture).

### 3.3 Attack review

> You are attacking a change to formalize-paper (repo `<path>`, branch `<branch>`, diff
> `<base>..<head>`) that claims to fix: `<bug>`. Work in a scratch copy and never push. First,
> reproduce the original bug on `<base>` and show that it is refused on `<head>`. Then try to get
> around the fix the way a careless or adversarial operator would: rename, re-order or split
> records; use a different spelling of a label or lane; re-open or re-number stops; edit after a
> seal; use another round; pass test-only environment variables; or reach the same unfaithful or
> undisclosed outcome by another path. For each attack, report whether it works (HIGH if a
> statement change, Fail or disclosure can vanish, or the human can be bypassed) and give the
> commands you used.

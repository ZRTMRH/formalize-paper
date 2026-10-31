# Known limitations

These are known problems with this version of formalize-paper (see `VERSION`), found in real runs
and reviews, with the change we expect to make for each. None is known to have produced a wrong
result in the runs so far; most cost time or attention. The protocol's own list of what it cannot
check is in `audits/AUDIT_PROTOCOL.md`, section "What this protocol does not cover".

Words used below: the *operator* is the main agent (the Claude session that writes the Lean and runs
the protocol), never you; a *lane* is one reviewer agent with one criterion; a *round* is one pass
of the lanes plus the adjudicator's decisions; to *seal* a lane's verdict is to commit it with a
check that the lane itself returned it; *pinned* means frozen for the rest of the run; *Phase 0* is
the mechanical check run before every round. The first part ("Tooling", "Protocol") is mostly for
maintainers; the numbered items T1–T35 say what each limitation means for you as a reader.

## Tooling

- **Linux only.** The checks read Linux's `/proc` (the scan for reviewer processes in
  `lanecheck.py` and `stops.py`), and the install steps use `apt`. Supported: Debian or Ubuntu, or
  Ubuntu under WSL2 on Windows. On macOS (this branch) the same facts come from `libproc`, without
  `/proc`; macOS is less tested (two runs on one Intel Mac). Two cases there are skipped rather than
  refused: one of your own processes that cannot be read at that moment, and a process whose parent cannot
  be read. The worst outcome is a leftover agent loop that goes unreported; proofs are unaffected (they are
  checked by Lean's kernel).
- **Codex capacity failures stop the parent turn, and only a person can resume it.** Automatic
  resume is deferred: keystroke injection into a live TUI cannot be made safe (an adversarial
  test found 22 failing scenarios: approval overlays, drafts, re-wrapped screens, misread logs).
  `codex/watchdog.py` (optional, run from the clone) only notifies the person, from the pinned session log; a future
  version may resume through Codex's app-server API.
- **Document-generator limitations can remain after reader checks.** A fresh reader's finding
  against a generator's own text is answered `unfixable` (naming the generator change) and
  its notice is delivered in `RUN_RECORD.md` (no separate KNOWN_FAULTS file is delivered); fix the
  generators in a new tooling version, never by
  modifying a pinned run.
- **Lane authentication protects final verdict bytes, not every transient write.** The original
  same-round sibling-overwrite gap is now covered by spawn-token commitments and owner-returned
  completion digests/seals, with a passing four-case parallel live gate. Tokens are not secret:
  they become visible in verdicts, and a sibling could read them from the parent's transcript;
  only the originating child's returned digest may establish its seal. A pre-planted seal makes
  the round STOP loudly (a denial of service, not a forgery). A write
  restored before observation remains undetectable, and probe contents are not covered by the
  verdict's SHA-256. Deliberate forgery is a disclosed residual risk (below, "The record proves
  consistency, not provenance").
  `codex/README.md` describes the Codex path and summarises its tests (the test logs are not
  public: they contain machine-specific details).
- **Under a delegating level the operator decides set-asides and non-STOP stops alone.** There
  is no independent agent: `stops.py` refuses what could be tampering (a STOP class, or any
  uncoded cause), carries every Fail of a set-aside forward into the next adjudication and the
  final report, and records each decision with a script-computed inventory; but the reason for
  a set-aside is the operator's text. `close --human`, `set-aside --stop` and the summary-page
  waiver cannot tell the human's words from the operator's (as with `signoff.py approve --by
  human`). A waiver covers only a commit that added records no check reads as control data (in
  practice a report record such as PAPER_DEFECTS.md swept into the wrong commit); any other
  ownership FAIL stays a FAIL in the report. A refused seal is a STOP-class cause only once it is recorded as a stop: the
  instructions say to record it, no check does it for them. The resolver-less design is tested
  by replays of the four live stops and a hands-off smoke fixture, not yet by a live run.
  A re-vote lane the operator sets aside (never spawned, crashed, unsealed) leaves its item open
  for the human, never decided: an operator who cannot complete a re-vote cannot reject the Fail.
  A `--note` stop's text and cause code are the operator's (an interrupted one is completed with
  them, as written); every other interrupted record command recomputes its record before it
  commits the file it finds, and refuses a file that differs.
- **An unsealed lane's verdict is not in git until its seal.** The seal commits the verdict and its
  probe files with the seal itself, so the window is the minutes between the lane's return and its
  seal. A lane reissued after its spawn line was lost (at most once per lane and generation) moves
  the verdict it wrote to `.reissued/` and the report lists the reissue; a verdict deleted before
  the reissue leaves no trace beyond the reissue itself ("earlier verdict: NONE").
- **An unadjudicated round can be set aside even if all its lanes finished.** No check refuses it,
  but every Fail and Ambiguous item of its lanes (sealed or not) is carried forward: the next
  adjudication and the final report refuse until each has a row of its own lane that decides the
  carried verdict (ADOPT, DEFER or QUESTION of that Fail, or a re-vote), not a row about a fresh
  lane's Pass. The set-aside and its carried items stay listed in the delivered `RUN_RECORD.md`.
- **The dependency walk (`dependencies.py`) shows reachability in the kernel's terms, not necessity.**
  It lists formalized results the goal results do not use. A result whose content is re-proved
  inline under another name is reported unused; a result referenced only by a dummy binding
  (`have _ := lemma`, which the unused-variables linter does not flag) is counted as used.
  `DEPENDENCIES.json` is checked against the Lean files at its commit (Phase 0, every run) and against the
  walk itself by the adjudicator's read-only Phase 0; Phase 0 rewrites it before every report.
- **`scope.py` recognises a declaration only by its keyword at the start of a line.** A
  declaration written on the same line as its docstring (`/-- B -/ theorem b …`) is not seen as a
  declaration of its own; write the keyword on its own line (Mathlib style).
- **The project's history check is skipped across a branch change.** `tree_state.py` treats a
  different branch as a new run and does not require the recorded project HEAD to be an ancestor
  (the audit record's history is always checked). A branch switch between two rounds of one run
  therefore escapes that part of the check; inside a round, the check at step 4 still flags a
  moved HEAD.
- **Lane spawn lines live only in the conversation that issued them.** After a usage limit or a
  crash ends that conversation, an unsealed lane is re-issued with `lane_auth.py reissue`
  (logged, refused once sealed; `audits/run/spawn-and-seal.md`, "Resuming a half-finished round"). A reissue is the
  operator's act: it is recorded in the commit message and RUN_LOG.md, and an earlier verdict of
  that lane is kept as evidence but never used.
- **Seals do not survive a rewrite of the audit repository's history.** Integrity checks that
  seal files were committed under `seal …` messages and never changed, not that the commits
  themselves are the original ones. `lane_auth.py seal` prints each seal's commit hash for
  RUN_LOG.md and the conversation transcript; nothing yet verifies those hashes against later
  history automatically.
- **Polling-loop attribution is heuristic.** A loop counts as a lane's when its cwd is in the
  repository or its parent chain reaches a lane process (only the `codex_spawn.py` fallback runs
  lanes as processes of their own; built-in subagents do not). A loop a built-in lane starts
  after `cd /tmp` is not attributed, and a loop that copies the operator's
  `FORMALIZE_PAPER_OPERATOR=1` tag is spared: detection, not prevention. Other projects' loops
  (cwd outside the repository, not started by a lane process) are never flagged or killed.
- **Codex sandbox git approvals.** The project's `.git` is protected in workspace-write mode,
  so branch changes and commits ask for approval unless the session starts with
  `--add-dir <project>/.git` (tested on 0.163.0; printed by `install.sh --codex`). With it,
  reviewers (who inherit the sandbox) can also write the project's git metadata, including
  `.git/hooks` and `.git/config`, and a planted hook would run outside the sandbox at the next git
  command. `tree_state.py` records hooks and the repository config (local, worktree, included
  files) at Phase 0 and flags any change (and a moved `HEAD`) as an integrity failure; that is
  detection, not prevention, and it covers the project's and the audit record's repositories only,
  not other nested ones such as `.lake/packages/*/.git`. A project `.codex/config.toml` setting is not
  loaded until the project is trusted, so the installer does not rely on one.
- **Nested Codex fallback sandbox failure.** On 0.163.0, a reviewer launched with
  `codex exec` inside a sandbox can fail before reading its task (app-server socket directory).
  Fallback detection now fails closed for known startup errors and absent/empty final messages,
  but does not make nested execution work. Do not silently rerun reviewers outside the sandbox.
- **Codex CLI support is experimental.** See `codex/README.md` for what has been checked and what
  has not. The protocol is tuned for Claude Code.
- **Adjudicator-owned records go stale and nobody may refresh them.** `SKIPPED.md`,
  `PAPER_DEFECTS.md` and `VACUOUS.md` keep the statuses and line numbers of their last
  adjudication. *Planned:* a final "record refresh" adjudication in Stage 5, before the report. The
  report already lists stale `File.lean:N` citations together with the current line.
- **Full audit rounds are memory-hungry.** Many reviewer lanes probing Lean at once can exhaust
  memory on a 16–32 GB machine. The agent spawns lanes in waves of at most 8
  (`audits/run/spawn-and-seal.md`); ask for smaller waves on less memory. *Planned:* a project
  setting `max_parallel_lanes`, so that `prompt.py` prints the spawn order in waves; a shared Lean
  server for the lanes.
- **Diff rounds never clear some UNCOVERED rows.** If a verdict was recorded on a helper that has
  since been deleted, or on an auto-generated syntax declaration from a `macro` or `syntax`, the
  row stays UNCOVERED. *Planned:* `audit_coverage.py` retires a pass on a deleted declaration as
  "deleted at <commit>", and `scope.py` skips auto-generated syntax declarations.
- **An agent can miss a garbled formula in a PDF.** The PDFs are made and checked by agents (a
  renderer, a verifier, two independent checkers of the mathematics); no script reads them. A
  difference all three miss (a lost minus sign, a superscript printed flat, swapped operands) can
  reach the reader. The markdown is always delivered beside its PDF and is the authoritative text;
  a PDF that never passed its checks says so on its first page. *Workaround:* compare a doubtful
  formula with the markdown.
- **The report can miss a removed helper's name.** It fails on a cited name of the project's own
  form (`thm_1_2`, `lemma_3_4`, …) that no longer exists. A free-form helper name cited without its
  namespace can slip through. *Planned:* check every backticked identifier in every section.
- **Phase 0 regenerates the report on every run.** Counters such as "re-pinned N times" change the
  report's text, which then needs another fresh-reader pass. *Planned:* regenerate the report only
  in Stage 5.
- **Line numbers drift.** Each docstring edit shifts the `File.lean:N` citations in hand-written
  documents. The report locates every cited Lean name at its current line (section "Where the Lean
  names are"). *Planned:* records cite names only, and the generator inserts the lines.
- **Paper line citations drift too.** A `tex l.N` citation paired with a quote can be off by a few
  lines. *Planned:* check that the quote appears within ±1 line of N.

## Protocol

- **A fault in a proof-validity check can be closed only with a fresh reviewer's approval.** In release
  mode a check of the proof-validity core (the build and sorry scan, the axiom sweep, the freeze, the
  integrity and tool-patch checks) is never patched; when it cannot run and no Lean-side workaround
  exists, `stops.py core-fault` asks a fresh reviewer whether every failure line is the tool's fault.
  There is no cap on requests and no automatic exit after rejections: a rejection means the reviewer
  saw a real problem (a sorry, an axiom, a changed statement, tampering) or a workaround, which has its
  own cure. A run whose reviewers keep rejecting does not deliver by this route until that problem is
  fixed. `RUN_RECORD.md` lists every request with its verdict.

- **The record proves consistency, not provenance.** The checks verify that the run's records agree
  with each other and with the Lean, and that each was committed under its owner's commit message.
  They cannot tell a record written by its owner from one written by the operator under the owner's
  name, and they cannot detect a rewrite of the git history that is consistent throughout. An
  operator that deliberately forges could deliver a report that passes every check. Examples:
  writing a reviewer's verdict itself and sealing it with an invented agent id (`lane_auth.py seal`
  checks only that the id is not blank), committing an edit as "adjudicate R", logging an answer you
  never gave, or rewriting the history of the run. Commit authors are not checked at all (the human
  and the agent commit as the same identity); the commit subject carries the authority. The gates
  are built against a well-meaning agent's mistakes, not a deliberate forger (the threat model of
  this release). The cheap partial defences: no row of PAPER_DEFECTS, SKIPPED, VACUOUS or DEVIATIONS is ever
  removed and a cited row must exist; a refutation proved in the Lean needs its `false` defect row;
  the involvement level, mode and ownership version are the first committed pin's; a `by`-less
  approval counts as the human's only in a run pinned before the field existed; and the summary
  lists every answer and approval recorded as yours, each with the audit commit that recorded it
  ("Answers recorded as yours"), so you can refute one and keep the hashes as a receipt. Under
  hands-off nothing in the delivered report rules a forgery out. If the result matters, have a
  separate session run a fresh full audit round on the delivered commit. *Not done:* printing audit
  and project hashes in every checkpoint message to the human (receipts taken before delivery),
  pushing the audit branch to a protected remote at each checkpoint, and cross-checking each seal's
  agent id against the harness's subagent transcripts.

- **That the intake was sent unchanged is not checked by a script.** `prompt.py --intake` prints
  it and the first pin needs its hash in `RUN_LOG.md`, which shows the message was printed, not
  that the operator sent it without paraphrase or omission; the human sees the labels 1a … 7 and
  can say when one is missing.
- **`lanecheck.py --kill` is not the default.** Every operator command in the stage files and step
  blocks passes it; the adjudicator's run does not.
- **Docstring-only changes trigger a large round.** A lighter round (only the correspondence lane,
  on the changed declarations, when every fingerprint is unchanged) is not planned for now: it
  reduces audit coverage. In this release a comment- or docstring-only change at the end of a run
  needs no round at all (T1 below).
- **The faithfulness lanes' detection rate is not measured.** A planted-fault benchmark is planned.
  Version 0.3.0 itself was run end to end, hands-off, on the exact release code: on a short
  synthetic test paper with planted errors it delivered in about 4 h 15 min with no human input
  after setup (2026-10-26), and a second hands-off run on a benchmark paper delivered with no stops
  (2026-10-27). Two runs do not measure a detection rate.
- **The `statements-only` level has not run end to end.** No fixture covers its stops before and
  after Checkpoint B.
- **Later fresh-reader passes re-report known generator gaps.** A finding already answered
  `unfixable` blocks again when re-found.
- **Pushing is not tried at intake.** A token without push rights shows only at delivery, as a
  remaining stop.
- **The same idle-hypothesis question is raised many times.** *Planned:* one grouped QUESTION
  with a member list, which later rounds cite instead of reopening.
- **Some definitions cannot be checked for non-vacuity before their proofs exist.** This needs a
  standing defer. *Planned:* a defer whose revisit condition is mechanically checkable (for
  example "this theorem has no `sorry`") is re-tested automatically.
- **Several projects sharing one audit record can diverge.** *Recommended:* one Lean project, or
  at least one branch of the audit record, per paper. `install.sh` gives each Lean project its
  own copy of the scripts, so a pinned run never has to merge another project's tooling.
- **A push can fail only at the end.** In a Mathlib clone, pushing a branch that contains
  `.github/workflows` needs a token with the `workflow` scope. *Recommended:* test the push with
  `git push --dry-run` at intake, while the human is present.
- **Checkpoint messages can be very long.** Quoting every known-fault notice verbatim can run to
  tens of kilobytes. *Planned:* quote the notices' summary items and point to the files.
- **The involvement levels are enforced partly by text.** Under `statements-only` and `hands-off`,
  what the operator may decide alone is set by RUN.md; the scripts check the record it leaves
  (tags, the decisions document, the report's disclosure, the approval), not every rule. For
  example, that a "conservative rule" decision really is the conservative option is not checked
  mechanically. (That a statement change was begun before the Lean edit is checked:
  `signoff.py reapprove --begin`.)
- **Under a delegating level the operator may leave a hard non-goal result unproved.** A
  `[DELEGATED …; reversal: re-prove] leave <decl> unproved` line exempts that declaration's
  `sorry`, so an operator could give up on a result it could have proved with more effort. Whether
  the attempt was serious is judgement only. The trade-off is accepted: it is always disclosed
  (`SKIPPED.md`, the summary, the report's coverage section, `DECISIONS.md`), every result whose
  proof uses it must be listed too (the axiom sweep), a goal result is never exempt, and the
  reversal is to prove it.
- **A delegated re-approval may strengthen a listed statement unnoticed by the scripts.** Under
  `hands-off`, `signoff.py reapprove --begin` proves the begin came before the edit, but the freeze
  check reports any change to a listed declaration as `NOTE[reapproval]`, whether it weakens or
  strengthens the statement. "Never strengthen or generalize" stays an instruction; the re-rendered
  sheet marks the result CHANGED and the report lists the approval and every re-approval (the
  report check fails while one is open). Whether a change weakens or strengthens is judgement only. The record's ownership rests on
  its commit subject (`approve …`), as for the approval itself; the report check re-runs the approve
  gate on every commit of the full history that changed the approval, so a forged subject passes only
  where `signoff.py approve` itself would have (what it cannot see: who typed a logged human answer).
- **"Approve the statements" assumes the approver is a mathematician.** If the approver lets the
  agent approve (option (c) at Checkpoint B), every judgement that a statement is faithful rests on
  the AI reviewers. *Recommended:* at intake, ask whether a mathematician will review a short list
  of the riskiest statements.
- **A docstring-only answer at the final checkpoint can start more work.** The diff round that
  follows can adopt new fixes and raise new questions. *Planned:* treat docstring-only answers as
  "implement, Phase 0, correspondence check only".
- **A reader's summary is not its record.** Responses must quote the committed reader record,
  never the summary the reader returned in conversation. *Planned:* `readers.py` prints each
  blocking finding's quotable start.

## Trade-offs and open items (0.3.0)

Collected from the design's known risks and the audits of the test runs (short papers, mostly
hands-off). Each item says what it is, what it means for you as the reader of a run's report, and
whether the run's report discloses it. The numbers T1 … T35 (T28 and T34 fixed) match the
maintainers' table in `TRADEOFFS.md`, which says why each was accepted and how it will be tested.

### What the reviewers check

- **T1 An adopted docstring fix is not re-read.** A change to comments or docstrings only never
  starts a review round, so a docstring an adjudicator adopted in the last
  round reaches you without any reviewer reading the new text. *For you:* a misleading docstring
  could slip through; statements and proofs are unaffected. *In the report:* yes, REPORT "Changes
  after the last audit round" and the matching decisions item.
- **T2 Cited results are only partly checked.** Every run ends with an advisory citation review: where
  the cited work is openly available, agents check that it states the cited result in the form used
  and that the bibliography entries are right (`CITATIONS.md`; it reached 74% of cited results across
  seven real papers). It never stops a run, it is not proved in Lean, a citation whose source is not
  openly available is not checked, and it does not yet run under Codex. The prior-art reviewer runs
  only when the intake asks for a library contribution. *For you:* a wrong citation may go
  unremarked when its source is not openly available, and always under Codex. *In the report:* yes,
  `CITATIONS.md` gives each cited result's finding (as stated, a stronger form, not reachable); trust row "AI reviewer: prior-art: NOT RUN" when
  that reviewer did not run.
- **T3 Encoded hypotheses can escape the hypothesis walk.** The walk is syntactic: a hypothesis
  passed as a `Bool` or as data is not recognised as an assumption. *For you:* an extra assumption
  could be missing from the assumptions list; the faithfulness reviewers remain the backstop. *In
  the report:* yes, REPORT section 2 says the walk is syntactic.
- **T4 The reviewers' detection rate is measured on one benchmark only.** The planted-fault benchmark
  has been run: 10 agent-made papers with planted errors; the scores are in the accompanying report. It says
  nothing about faults of other kinds or in real papers. *For you:* "no Fail" is not a guarantee.
  *In the report:* in general terms ("the lanes are judgments, not checks").
- **T5 Slips in the paper's proofs have no owner.** No reviewer is assigned to read the paper's
  cross-references; slips are recorded only when someone notices (in one test run a slip was
  found only because an adjudicator happened to check). *For you:* the absence of a listed slip says little. *In the report:* yes,
  proofs are said not to be checked line by line against the paper.
- **T6 Several judgements rest on reviewers alone.** Whether a repair is minimal, whether missing
  library theory was small enough to build, which reading is weaker, whether a passage opens a
  contradiction, and whether a trivial statement was reported are not checked by any script.
  *For you:* these are as good as the reviewers. *In the report:* in general terms.
- **T7 A matter can be asked again.** Under `involved`, a wording change no longer re-asks (fixed
  for Checkpoint B → C), but a new record entry still can: in one test run a defect entry written
  after B re-opened an item the human had decided at B (one thin item at C). A question on a
  helper declaration is re-raised by each full round's fresh reviewers; some record entries are
  still identified by their wording. *For you:* an extra question, or extra delegated lines under hands-off;
  no wrong result. *In the report:* the Checkpoint C document says so; the report does not.

### Records and trust

- **T8 Forgery and self-sealed verdicts are not detected.** A deliberately rewritten history,
  a reviewer verdict written and sealed by the operator, commit authorship (never checked) and record
  ownership by commit subject alone are residual risks; see "The record proves consistency, not provenance" above. *For you:* under
  hands-off nothing in the report rules a forgery out. *In the report:* yes, trust row "Record
  provenance: NOT CHECKED".
- **T9 Hand-written RUN_LOG lines are checked only later.** A malformed line (e.g. a bare
  `[DELEGATED]` at a decision position) is caught by the next check, not when written; in one test
  run this cost an adjudicator restart (~10 min). *For you:* time only. *In the report:* no.
- **T10 A disclosed fault is never closed.** A fault disclosed in release mode is not re-checked at
  delivery. In one test run a fault was cured 18 minutes later, yet the delivered README §D and the
  run's known-faults notice still presented it as current, and REPORT §1 said no fault was disclosed. *For you:* a listed
  fault may already be gone; the three places can disagree. *In the report:* the stale lines are
  themselves the report's.
- **T11 PDFs are verified by agents only.** The renderer, verifier, checkers and cover verifier are
  trusted as agents; render checkers leave no notes beyond the verdict. *For you:* compare a
  doubtful formula with the markdown, which is authoritative. *In the report:* yes, README §D says
  what ran for each PDF.
- **T12 Some local changes are not watched.** Global git settings such as `http.proxy`,
  `http.sslVerify=false` and `remote.*.receivepack` are not compared, and files a reviewer writes
  under ignored directories (e.g. `.lake` build files) are not tracked. *For you:* in principle a
  stale build file could be used by a check; no case has been seen. *In the report:* no.

### The delivered documents

- **T13 The one-page SUMMARY under-reports the human's answers** (seen in a test run): "Answers recorded as
  yours" lists anchors and dates, not the answers; "Decisions: 0 matter(s)" although the human
  decided four at C; unused-hypothesis lines still read "(keep or drop: DECISIONS.md)" after
  "keep". *For you:* read REPORT §9 and DECISIONS.md for what was chosen. *In the report:* yes,
  the summary's known-faults notice lists them.
- **T14 REPORT §9 and §11 presentation** (seen in a test run): C answers print as bare doubled quotes
  (`""1: (1)"`), Q1/Q2 appear three times, and §11 lists answered QUESTIONs as stops. *For you:*
  cosmetic; the answers are complete in RUN_LOG.md and DECISIONS.md. *In the report:* no.
- **T15 Refreshed line ranges can be malformed** (seen in a test run): a correct `Lemmas.lean:50-52` became
  `53-52` in REPORT §5 and DECISIONS. *For you:* the name is right, the range is not; the report's
  "Where the Lean names are" gives the current line. *In the report:* no.
- **T16 Paper-level and Lean-level "uses" are not linked** (seen in two test runs): REPORT §5 can say a
  theorem uses a lemma while §13 says the Lean proof does not. *For you:* both are true at their
  level. *In the report:* no.
- **T17 The SUMMARY page can only count some items.** Near its 62-line budget, items are counted by
  name with "full text in REPORT §N". *In the report:* yes, the pointer is printed.
- **T18 Delivered DECISIONS.md after Checkpoint C** shows answered items only as "Previously
  answered" lines; the full pre-C document stays in the audit record. *In the report:* no.
- **T19 Smaller items from one test run, not confirmed fixed:** the paper-faithfulness lane cited
  Main.lean lines about 12 too high; a superseded known-faults notice was delivered as current; REPORT cited
  an audit commit as the approval commit. *In the report:* no.
- **T20 A paper's global convention may not be raised** (seen in two test runs): no
  GLOBAL item on the sheet. *For you:* check the convention yourself. *In the report:* no.

### Scale, cost and caps

- **T21 Agent PDF rendering is untested beyond about 14 pages.** The cost
  estimate for a 50-page REPORT is 3–4 M tokens and several hours in the worst case.
- **T22 Adjudication of about 300 findings is untested;** the test runs produced far fewer.
- **T23 No run of this version on a long real paper.** The test runs of this version's design used
  short test papers; the long real papers ran on earlier versions.
- **T24 A run takes hours even for a short paper**: about 4–6 h for a 3-page test paper (three test
  runs: 5 h 40 m, 5 h 52 m and about 5 h 20 m; a hands-off run about 4 h), and 1–2 days for a
  30-page paper. Parallel runs share one subscription's usage limits.
- **T25 Ceilings and caps are guesses.** Statement rounds 4 (re-approval 2), diff rounds by budget
  2/4/6, delivery rounds 2, renderer rounds 6, failed cures 2 per stop and 3 per check, openings 3
  per round, reader-fix rounds 2, SUMMARY 62 lines. *For you:* when a cap is reached the
  conservative default holds and is disclosed. *In the report:* yes, when reached.
- **T26 Proof-phase rounds are bounded only by progress,** and a fault that recurs each round but is
  cured at the first try is not counted against any cap. *For you:* time and tokens only.

### Test coverage of this release

- **T27 Twelve mutants tested by the `stops.py` selftest were not re-run since the last change**
  (that selftest exceeds the 10-minute foreground limit).
- **T28 (fixed after the release)** Selftests that failed now and then under load (`hypotheses.py`, `scope.py`,
  `stops.py`): their fixtures ordered rounds by a wall clock that stepped back; the tests now use fixed dates.
- **T29 An interrupted `--prepare`** (between writing and committing) is refused at delivery until
  re-run, but this was never tested by killing the process.
- **T30 Claude Code deny patterns with a mid-pattern `*`** follow the documented syntax but were not
  tried in a live session.
- **T31 `readers.py --check` in release mode** prints a stale report or decisions pass as DISCLOSED
  (exit 0); only `--deliver` requires the pass.
- **T32 Release self-cure of a stop** was shown in replays and fixtures at every mode × level, but
  not exercised on a planted live run.
- **T33 A stage check may pass although the failed step was never redone.** No test run showed it.
- **T35 `scope.py --verify` after an upgrade.** A round's scope is re-checked with the installed scope code, so a
  round scoped before an upgrade of formalize-paper and re-checked after it may be flagged as changed. Upgrades
  happen only between runs, so a run never meets this; *for you:* none.

None of T1–T35 is known to have produced a wrong mathematical result in the test runs.

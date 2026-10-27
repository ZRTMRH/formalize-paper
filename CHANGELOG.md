# Changelog

## 0.3.0 (release date: the date of the v0.3.0 tag)

### In short

- **Release and dev installations.** By default (release), a run stops for you only for four
  reasons: a goal result that looks false or unprovable, an outward action you did not allow, something
  only you can fix, and a genuine ambiguity in the paper's meaning. Faults in the run's own
  bookkeeping are fixed by the agent and disclosed in `RUN_RECORD.md`. `install.sh --dev` keeps
  every stop, for people changing the scripts.
- **A one-page `SUMMARY.pdf`**, delivered first, with the status of every numbered result. The other
  documents are its appendices.
- **The PDFs are rendered and checked by AI agents** from the audited markdown, which is always
  delivered beside them and is the authoritative text.
- **`RUN_RECORD.md`**: how the run went (stops, fixes, disclosed tool problems), apart from the
  report.
- **`DECISIONS.md` has one section per matter**, and an answered matter is not asked again.
- **Advisory notes**: a review of the paper's citations (`CITATIONS.md`) and a check of the
  summary's statuses by a fresh agent. Neither ever stops a run.
- **Reviewed tool patches (release mode).** When one of the run's own checks crashes or misjudges a
  case, the agent may patch it, with a regression test and an independent agent's review, and the
  patch is disclosed.
- **Codex (experimental):** generated roles for the tool-patch reviewer and the summary check. Not
  tested end to end on this version.

The entries below are the maintainers' detailed build log. They refer to internal test runs
("trial #n", "mini", "bench", "conf") and design notes ("U2", "B1"…"B13", "G", "F") that are not
published.

0.3.0 was tested end to end on the exact release code (Claude Code): a hands-off run on a short
synthetic test paper with planted errors delivered in about 4 h 15 min with no human input after
setup (2026-10-26), and a second hands-off run on a benchmark paper delivered with no stops
(2026-10-27). The changes below follow a live hands-off run of a 0.3.0-dev build (2026-10-19), the
independent audit of that run and a whole-repository simplification audit. The
principle is to remove the causes of stops instead of adding machinery to cure them. Every
decision, clearance, set-aside and waiver is still disclosed in the report. A stall-resolver agent
was added during 0.3.0-dev and removed again before release (see "Removed").

### Codex end-to-end fixes: stated-only conjectures, reproducible tool-patch facts (2026-10-26)
- Lane D (non-vacuity) rule 5b: on a stated-only conjecture (a `def : Prop` no theorem asserts) Pass means the
  sets/predicates it quantifies over are witnessed and the 4b probes close neither it nor its negation; never
  NotDoneYet for want of a proof of it. A Codex lane had returned NotDoneYet every full round, and delivery's
  RED[unverified] asked for a round that could not answer it. Statuses and delivery checks are unchanged.
- `tool_patch.py`: the facts a reviewer re-derives (regression and selftest tails, blast-radius lines) record the
  random scratch directories as `<scratch>`, other temporary names as `<tmp>` and object addresses as `0x…`, so an
  honest patch's FACTS.json re-derives identically.

### Codex port brought up to the redesign (codex-u2 2026-10-24, ported onto combined-fixes 2026-10-25 as codex-port; experimental; one hands-off end-to-end run on a synthetic paper, before the release rebase)
- Every subagent the Claude Code path spawns has a generated Codex role: new `formalize_citations` (citation agents
  1 and 2, step 5a; it replaces "a default agent") and `formalize_helper` (author-side helpers), eleven roles in all with the
  tool-patch reviewer and the status check.
  No role sets the network, the sandbox or tools; each child inherits the parent's sandbox (network off) and gets
  its network rule from its generated task (intake 1c). Every printed spawn line names its Codex role
  (`prompt.spawn_kind`). `run/codex.md` maps each Claude spawn to its role and lists every other difference: no
  network (prior-art and citation notes degrade, `--search` optional for a public paper only), steps that would
  leave the sandbox (fetch, push, copying deliverables elsewhere) handed to the person as commands, never an
  approval; seeing PDFs; waits and long commands. Claude Code behaviour unchanged (only the text before "with:"
  of a spawn line: the status check's and a reissued lane's now name their roles; the core-fault reviewer
  is `formalize_tool_patch_reviewer`). `codex_agents.py --selftest`
  checks the whole map from the sources: every spawn line a script prints names a generated role (or prints one
  through `spawn_kind`), every `formalize_*` role an instruction file names is generated, and every generated role
  is spawned somewhere; the history-fault acknowledgment reviewer (`integrity.py --ack-request`) is
  `formalize_tool_patch_reviewer` too. Mutants cu-1..13.
- `tests/snapshot_replay.py` selftest: its scratch directories fall back to the system temporary directory when
  `~/.cache/formalize-paper` cannot be written. Inside Codex's workspace-write sandbox ~/.cache is read-only, and
  `selftest_all.py --fast` FAILED there ("Read-only file system"), which made the Codex test run ask to re-run it
  outside the sandbox (CODEX-PORT test). Checked inside `codex sandbox`.
- integrity.py `pin`: a re-pin made without the project (`tool_patch.py apply`) keeps the first pin's Codex roles
  (`codex_agents`). It dropped them, so under Codex every applied tool patch was followed by `FAIL[codex-roles]`
  (stop S3 of the CODEX-PORT test run, self-cured there by a plain re-pin). Mutant cu-11.
- Codex roles: every generated role ends with a Codex-only sandbox rule (`codex_agents.SANDBOX_RULE`): a command the
  sandbox blocks is a failure the child records ("not reachable" for a source), never an approval it asks for. In
  the CODEX-PORT test run the citation child asked the person to approve downloading two cited PDFs. Mutant cu-12.

### Reviewed in-run tool patches; the deferral fallback reverted (post-release, approver 2026-10-24)
- Release mode: when a pinned check crashes or misjudges a case (bench1 S2, bench2 S1, bench1 S1 each ended at
  the person although the operator had diagnosed it exactly), the operator acts as maintainer:
  `tool_patch.py begin --stop S<n>`, a diagnosis and a minimal diff with a NEW regression test, `prepare`
  (mechanical facts: the regression test fails on the pinned and passes on the patched tools, every selftest
  passes, the blast radius over every round's read-only checks, the first pin's FLOOR of canary mutants),
  `review` (a fresh independent agent, prompt rendered from AUDIT_PROTOCOL.md, verdict sealed like a lane's;
  every earlier attempt and finding shown), `apply` (two commits: `tool-patch TP<k> apply` and `pin (tool-patch
  TP<k>)`), then `stops.py close --cured "tool-patch TP<k>"`. A reject is revised until approved (no cap, no
  stop); `withdraw` returns to the printed cure. A floor hit needs two approvals. Dev mode refuses all of it.
- integrity.py (ownership 4): every tool-patch link is verified by the apparatus pinned just before it; any
  other tooling change is `FAIL[tooling]`; a plain release re-pin may not change the tooling (`FAIL[pin]`;
  the gitmeta re-pin still passes); new code `tool-patch` (restore). `--deliver`: the first pin's apparatus
  checks that RUN_RECORD.md lists every applied patch and re-runs the floor; a patch that may have changed an
  earlier review's inputs forces a full round. Codex: the role `formalize_tool_patch_reviewer` (nine roles).
- Reverted: 378cf65's `stops.py close --deferred-to-full-round` and everything around it (its scope.py and
  `--deliver` hooks now serve the forced full round of a tool patch); kept: its T34 fix (`stops.recorded_plan`).
- Rejections are run-wide (re-check 2026-10-25): a diff rejected, or reviewed and never sealed, anywhere in the
  run is refused at prepare and apply on every later stop, a revision answers every earlier rejection of the run,
  and the reviewer's history lists the attempts of every stop (a diff rejected on S2 was accepted on S3, its
  reviewer shown "(none)").
- The "never resubmitted" rule compares diffs up to whitespace and line numbers (`tool_patch.diff_key`; re-check
  2026-10-25: a rejected diff with one blank line added had another sha256 and was accepted).
- A patch's selftests are the FIRST pin's (its project.py, plus any the patch adds), never the patched project.py's
  list, and a floor mutant counts as killed only when its selftest passes on the patched tools unmutated (re-check
  2026-10-25: TP-a moved lane_auth out of the pure tier, TP-b then disabled its prompt check, LA8 "killed" by a
  selftest that already failed).
- A tool patch only MODIFIES files of the first pin's apparatus: its one new file is its regression test, under no
  stdlib or apparatus module name; integrity.py FAILs a tooling file the first pin lacks and any stdlib-shadowing
  module in audits/, tests/ or tests/regressions/ (re-check 3, 2026-10-25: a new audits/re.py shadowed `re` and
  blinded phase0's sorry scan, with one approval).
- The proof-validity core is immutable to tool patches (`tool_patch.CORE`, read from the first pin): phase0.py, the
  axiom sweep (axiom_sweep.py/.sh, axiom_sweep_tail.lean), the freeze (fingerprint.py, fingerprint_tail.lean,
  olean_parts.lean), tool_patch.py and integrity.py; refused at prepare, apply and every link check (re-check 3: an
  edit of axiom_sweep_tail.lean accepting project-namespace axioms needed one approval and no guard fired).

### Release has exactly four human stops (post-release, approver 2026-10-24)
- At every involvement level a release run stops for the person only for: (1) a goal result that looks false
  or unprovable for a reason other than missing library theory; (2) an outward action the intake did not
  allow; (3) something only the user can fix -- a login, administrator rights, quota or payment, a change to
  their own files, or another program that keeps changing the project's files (`interference`); (4) NEW: the
  paper's meaning is genuinely ambiguous on a point that matters and the reviewers cannot converge on one
  reading (`--cause ambiguity`): the operator shows the passage, the readings and what each would mean for the
  formalization and asks; this holds under hands-off too, the answer is recorded verbatim and the run resumes
  at its own level. The old fourth stop, "a cure that keeps failing", is gone: a spent cure budget is
  classified (`stops.py classify`: a tool bug goes to the tool-patch route, outside interference is stop 3).
  A loose convention (ℕ from 0 or 1) is a reading-choice decision, never a stop. The statement-round cap with
  a faithfulness finding open is no stop in release: the operator judges it -- ambiguity (stop 4), convention
  (a reading choice) or anything else (the result reads "not established: open faithfulness finding";
  `round-caps/<round>.json`, owned by `round-cap <round>` commits). Dev mode keeps all its stops.
- RUN.md, the stage files, the intake paragraph, MAINTAINING S1, README, INSTALL and the Codex notes say the
  same; `tests/doclint.py` refuses the old fourth-stop wording in release text and checks the four stops
  appear consistently. Scenario selftests: the ambiguity stop at every level (hands-off resumes), the
  classification of a spent budget (a tool bug never reaches a human stop), and the three round-cap outcomes.

### RUN_RECORD.md: the process record, apart from the report (post-release, approver 2026-10-24)
- A separate deliverable `RUN_RECORD.md` (markdown only: never rendered, no reader; `audits/run_record.py`, written
  by `project.py --prepare-delivery` and hashed with the other prepared documents) holds how the run went: tool
  patches, every stop and who closed it, self-cures, set-asides and lane clearances, re-pins and reissues, faults
  disclosed instead of a stop, RUN_LOG's mechanical failures, and the fresh readers' known-fault notices (folded
  in at `--deliver`; no `KNOWN_FAULTS-*` file is delivered any more, and no `superseded/` directory).
- REPORT.md keeps eleven fixed sections (trust, assumptions, coverage, not formalized, defects, differences,
  vacuous, open questions, decisions, proof routes, Lean names; the reader notes end section 1, the notation
  section 11). Removed: "Stops cleared without you", "Every stop of the run", "Set-asides and clearances", the
  apparatus, reissue and set-aside trust rows and the disclosed/self-cured lists of the Run mode row. One trust
  line, "Checks weakened", says only "delivered by hand: the final delivery checks did not run" and/or "the audit
  tools were patched during this run; see RUN_RECORD.md". SUMMARY.md and the DECISIONS box drop self-cured stops
  and disclosed faults; the human's answers and the delegated closes stay.
- `integrity.py --check-run-record` (run by `--deliver` on the delivered copy and by the delivery gate on the
  prepared one): RUN_RECORD.md lists every applied tool patch (from TOOLING_PIN.json's re-pins and the
  `tool-patch TP<k> apply` commits), every stop the operator closed and every set-aside -- provenance only.
  README D points to RUN_RECORD.md and fingerprints it; `--check-delivered` compares it.
- Status check (advisory, approver 2026-10-24: "let agents guard code, not just code guard agents"): after the
  first prepare, a fresh agent (`prompt.py --prompt status-check --write`; Codex role `formalize_status_check`)
  reads SUMMARY.md beside REPORT.md and the records and lists each result whose summary status the records do
  not support (`status-check/FINDINGS.md`). The operator corrects each through the route that owns the status
  and writes `status-check/ACTIONS.md`; both are quoted in the delivered RUN_RECORD.md. Never blocks, never a
  stop; no script checks their content.

### F10/F12 items only for declared refutations (post-release, 2026-10-24)
- Benchmark run bench2: a reviewer's probe file `not_<X>_as_printed` (with no such declaration in
  the project) gave every round an F10 item no reviewer could judge (UNCOVERED,
  QUESTIONs, a standing defer, then an alias theorem that tripped RED[drift]). `scope.py` now schedules F10/F12
  items only for refutations `not_<X>_as_printed` that are declarations of the project at the round's commit;
  a name only lane text or a file name carries schedules nothing, and `scope.py` prints a note naming it
  (`lane_only_refutations`). The F10 rule is unchanged. Scheduling on the mini2/5/6/10/11 and bench1 snapshots is
  unchanged. A scenario selftest replays bench2's second fault (set-aside, empty commit, fresh diff round whose own
  lane decides the item, then `--verify`); it passes since 4dd9a08 (verify against frozen inputs).

### Deferral fallback: an impossible cure is not a human stop (post-release, 2026-10-24)
- Release mode: an integrity fault of an adjudicated round's review (a class-I `redo` code such as `prompt-changed`,
  or `tool-bug`) has no cure (`set-aside` refuses an adjudicated round), and the benchmark run bench1 (S1) went to
  the human for it. `stops.py close --stop S<n> --deferred-to-full-round "<text>"` now closes it: the round's
  verdicts are superseded (result_status drops them, so a tampered verdict never becomes a status), `scope.py`
  never skips the full round while a deferral is uncovered, and `--deliver` refuses until a later full round
  (scoped after the deferral, adjudicated, judging every item of its scope) has run. A fault in the final full
  round gets one more full round; a second is stop 4. Refused in dev mode, for faithfulness, proof, restore-kind
  or unknown codes, a statement round, and a round not adjudicated. The trail checks every deferral record.
  Review fixes: a deferred round's `## Hypotheses` rows and any cite of its verdicts support nothing; only a check of
  the round's own review (lanecheck, prompt, scope --verify, on that round) is deferred; the report names records the
  superseded adjudication wrote elsewhere; the trail re-checks a Stage-5 deferral as late from the committed log.
- TRADEOFFS T34: the stop trail judges an earlier self-cure by the apparatus pinned at its close (its scripts at that
  pin, in a subprocess), not by today's tables: a re-pin no longer turns a correct cure into "a human stop"; a forged
  cure is still caught.

### Live L-infinity run: bundle step (post-release, 2026-10-24)
- `signoff.py bundle` with a PROBLEM writes no `STATEMENTS_BUNDLE.md` (a failed commit restores the file as it was).
  The live run's bundle was left uncommitted, the round's set-aside committed it, and integrity stopped the next
  adjudicator on `FAIL[ownership]` (only a `scope` commit owns it; stop S1). `stops.py set-aside` now refuses an
  uncommitted bundle with the recovery (rm it), as it does the other files another step owns. The PROBLEM itself was
  a tool bug: a field of a Type-valued structure (a projection, no source text of its own) was reported as a
  definition whose source is missing; it is now shown by signature with a note naming its structure, whose
  definition the bundle shows. Scenario `tests/round3.py` t_bundle; mutants lsw-S1a..c.

### Advisory citation notes (citations, 2026-10-24)
- Stage 5 step 5a: after the final audit round, a fresh agent reviews every cited result the paper uses (as stated,
  a stronger form, not reachable) and its bibliography, and a second fresh agent verifies each item's evidence and
  writes `CITATIONS.md`: reminders for the authors to check, each with quotes and links. Prompts
  `prompt.py --prompt citations-draft|citations-review --write` (AUDIT_PROTOCOL.md); a confidential paper's agents
  only search for the cited works by title and authors. No check reads it; it never stops, blocks or changes the
  run. The summary gets one line ("Citation notes: N items — see CITATIONS.md", or "not produced: <reason>" from a
  RUN_LOG line); `--deliver` copies it and README D lists it. A run without it delivers exactly as before.

### Trial #11 audit fixes (protocol-u2-pdf, 2026-10-24)
- A decided defect row no longer reads "left to the human". Trial #11's PAPER_DEFECTS row 2 kept its statement-round
  decision cell ("whether to add a companion ... is left to the human") after the operator's [DELEGATED] decision
  under hands-off; the reader-fix may not touch a decision cell, so the operator ran a whole full round (50 min) for an
  adjudicator to rewrite it, which it did not. The generator now shows the decision instead, as it already did for an
  "open" VACUOUS row: a `defect:<anchor>: [DELEGATED …]` line (the anchor's version may be left out, as the decisions
  check accepts it) makes REPORT section 5 quote each sentence of the cell that leaves the matter to a person as what
  the row said when written, followed by the decision, and the summary's defect line say "decided since"
  (`make_report.decided_since(kind="defect")`, `settled_cell`; shown only, the record checks read the cells as
  written). stage5 step 1 lists it among the things that are never a reason for another round. Mutants t11b-1..6.
- A change to comments and docstrings only never needs a review round, at any stage. Trial #11 ran a Stage 5 full
  round (R3, 53 min) on R2's docstring-only fix (Stage 4's first full round had ADOPT rows, so Stage 5 "opened with its
  own full round") and then a diff round (R4, 31 min) on R3's docstring-only fixes ("a docstring fix of an ADOPT row
  is a fix like any other"; 347977f skipped such a diff round only in Stage 4). In Stage 5, `scope.py` now exits 3
  with `NEXT[no-round]` (`scope.no_round_line`) when the Lean is unchanged since the last proof-examining round, or
  changed only in comments and docstrings as `--deliver` decides it (the Lean comparison of
  `project.changes_after_last_audit`, so the delivery never asks for the round skipped), committed, with no item
  pending the next adjudication, no `deliver-stale` or `unverified` precondition and no set-aside redo due: a diff
  round then has nothing to audit, and a full round is already done when that last round is a full-scope proof
  round, adjudicated, every REVOTE NEEDED row decided and no unexpected UNCOVERED row (Stage 4's first full round is
  then Stage 5's full-scope round). Phase 0 still runs on the commit (the freeze check: approved statements
  unchanged); the report and the decisions document list the commits as comment-only, not re-read by a lane. This
  reverses fix-mini2 M2's rule that an ADOPT row's docstring fix is re-read by a lane (doclint and mutant rv-M2
  replaced; t11b-22). stage4 step 2/7 and stage5 step 1/7. Mutants t11b-15..22.
- The one-page summary's generator lines say something, and README C says what the sheet shows. Trial #11's
  SUMMARY printed "not a defect 2 — (full text in REPORT §5)" (a first sentence over the length limit left nothing:
  `_short` now falls back to its leading clauses ending at a comma), "not a defect (+2): 4; 5" (a counted item's ident
  now names the result it mentions; a proof route's names its result), the "Not defects" preamble as an item (a bullet
  that only points below or above and names no result, tex line, Lean name or number is not an item), and "proof
  route 1 — Theorem 2.1: paper step fails" (now the paper's tex line and the first clause of why the route differs).
  A `false` defect's line gives its counterexample when short, and the page ends with a "Terms" line for the terms it
  uses and does not explain (a round, a stop's class). README C said the sheet shows "the proofs as they stood then
  and line numbers of that commit" (the approval commit); it now says the sheet shows the statements, not the proofs,
  with the line numbers of the commit its own "Commit" line names, and the approval commit beside it when they
  differ (`project.sheet_commit`). Mutants t11b-7..14; mini2-3b and os-15 re-pointed.

### Trial #11 fix: a mentioned tag is no decision (protocol-u2-pdf, 2026-10-24)
- Live trial #11 (release, hands-off) looped on self-cures: a run-log line "QUESTION 1 decided [DELEGATED]" failed
  the report check's tag lint (S1); the cure text quoting the bare tag was copied by `stops.py` into `## Stops` and
  failed it again (S2). The lint (`decisions.tag_problems`, review B2: a decision in a variant spelling must not slip
  past the canonical pattern unseen) now reads a BARE `[DELEGATED]` as a decision only where one stands (opening an
  entry, or after its anchor or label); mid-sentence, in a code span or in a `stops.py` `## Stops` line it is a
  mention (`decisions.mentions_masked`, also used for the [PROXY]-under-a-delegating-level check, for code spans and
  stop lines only). A tag with anything inside it is linted wherever it stands (a dated one is counted as a
  decision). `stops.py close --cured/--delegated` refuses, before writing anything, a text the lint would refuse.
  Mutants t11-1..7.

### PDFs rendered and verified by agents (protocol-u2-pdf, PDF-AGENTS, 2026-10-23)
- Approver: the PDFs a human reads are made and checked by fresh agents, never by a script. The generators write
  markdown only (REPORT.md, SUMMARY.md, SIGNOFF.md, the sheet's paper statements as LaTeX source). Once a markdown is
  audited at its current hash (its fresh-reader gate; the hands-off sheet: `signoff.py check`),
  `render_record.py` runs the loop: a renderer (A, faithful and readable: it may rephrase or re-lay out for
  readability, never change the mathematics; Lean code character for character), a verifier (B), and on B's PASS
  two fresh checkers that judge only mathematical faithfulness; a checker's DIFFERENT goes back to A as a normal
  round, then B, then a fresh pair, within 6 renderer rounds. Spent: the least bad round ships with every
  remaining objection on a cover page. The markdown is always delivered beside its PDF. No round produced a PDF:
  the markdown ships alone (`no-pdf`), disclosed. Nothing in the loop is a stop; a crashed agent is `fail`ed and
  counts; a restart resumes from `pdf/<key>/RENDER.json` (every round's PDF and source committed).
- The one code guard is a fingerprint (`render_record.py check`): `project.py --deliver` and `signoff.py approve
  --by human` refuse unless the PDF is the one recorded for the markdown as it is now (`RED[deliver]`, render
  again). A human approval records the PDF's sha256 and the render outcome it was shown.
- Prompts: renderer, verifier, cover and checker blocks in AUDIT_PROTOCOL.md (`prompt.py --prompt
  render-a|render-b|render-cover|render-check`); the Codex role `formalize_renderer`; TeX engines allowed only with
  `-no-shell-escape` (LuaTeX `--safer`), pandoc only `--sandbox`, filters and `-shell-escape` denied.
- Removed: `render_fix.py` (the pdftotext comparison, the .tex edit allowlist, `--render-fix`, the render-check
  lane, the plain renderer), the LaTeX output of make_report and signoff, `project.py --pdf-check`, the PDF FAULT
  notes, `signoff.py glyphs` and `uni_math_extra.json`, the no-PDF test mode, the `pdf` mutant kind and its
  mutants, Phase 0's release PDF-only baseline exception. `pdf` stays a legacy cause code (never emitted; an older
  run's DISCLOSED[pdf] records still parse and stay in README D). `integrity.py`: `pdf/*` owned by `render `
  commits; the old `render/*` and `uni_math_extra.json` owners kept read-only.
- Migration: the reader hash is md-only; a pass recorded on md + .tex stands while the md is unchanged (a
  one-version shim in `readers.py`, to be dropped). An approval made on an old PDF stands; the approved sheet is
  rendered at delivery. Run `install.sh --upgrade <project>` (or `claude_settings.py`) for the new permissions.

### PDF-AGENTS review fixes (2026-10-24)
- `save` and `fail` refuse a step whose prompt was not issued (`prompt.py --write`), as lanes and readers do.
- The cover of a least bad PDF is checked by a fresh cover verifier (`--prompt render-cover-check`, `--role
  cover-check`), whose verdict is recorded: it compares the cover's objections with the record's, verbatim, and
  the pages behind it with the round's. A cover it does not pass never ships; after two attempts the round ships
  without a cover, disclosed. `finish` refuses a cover whose objection list is not the record's.
- `verified` needs both checkers' recorded SAME verdicts. A checker that did not run is never a pass: the
  outcome `verified-checkers-disclosed` is now `checkers-did-not-run`, and README D's line opens "NOT
  INDEPENDENTLY CHECKED" and says the checkers did not run.
- README D lists each delivered PDF's sha256; `project.py --check-delivered` (also run at the end of
  `--deliver`) refuses a PDF in `deliverables/` swapped after delivery, added without a fingerprint, or whose
  fingerprint is not its render record's.
- `render_record.py shown --doc SIGNOFF --round R`, run right before the human is asked, records the PDF shown;
  `approve --by human` refuses unless that is the PDF the record ships now, and stores it (not the PDF current at
  approval) in the approval.
- `install.sh --upgrade <project>` updates an existing project's `audits/` between runs (records, history and run
  mode kept; one `upgrade formalize-paper <version>` commit). INSTALL.md's old path ("move audits/ aside and run
  install.sh again") failed on the existing `AUDIT_PROTOCOL.md` link. Tested by `tests/upgrade.py` (tier 0).
- The subagent common rule 4 defers to the working directory a task names (the render prompts' `<DIR>`); `begin`'s
  refusal names the reader pass to run.

### Trial #8 (involved) fixes: the human is not asked twice (protocol-u2-int, 2026-10-24)
- Under `involved`, Checkpoint C no longer asks what the human decided at Checkpoint B: the approval, the approved
  sheet's global differences, CHECK rows and results not formalized, and the defect and vacuity rows the record held
  at the approval on a CHECK result. DECISIONS.md lists them once, under "Already decided by you at Checkpoint B
  (<date>)", with the B answer verbatim; delivery does not wait on them. One comes back only when its substance
  changes, saying it was decided at B. Trial #8's C asked 12 items, 9 of them B's; the same state now asks 3.
- A defect or vacuity item is keyed on its substance (location, printed statement, status, repair), never its prose:
  a reader-fix glossary sentence re-asked trial #8's two answered defects (C'). Answers logged under the old
  prose-hashing anchors still count (read from the record's history).
- Every answer in DECISIONS.md "Previously answered" names its checkpoint (trial #8 showed the C answer as the B
  approval's); a stop's answer is listed as the stop's, not as a stray anchor.
- REPORT section 9 and SUMMARY "Answers recorded as yours" show the human's own Checkpoint B and C answers, each
  with its checkpoint and audit commit; an answered open question (a reading choice) is no longer called a stop.

### Trial #10 audit fixes (protocol-u2-int, 2026-10-24)
- The sign-off sheet locates each Lean name of a row written in code spans (`` `N.x` ``, `` `N.d` (uses `N.y`) ``):
  trial #10's sheet showed doubled backticks and no `File.lean:N` at all.
- The report's trust table no longer says, for every self-cure, that a review's independence was compromised; each
  cured stop's line says what was done (52a863e).
- Stage 4: a diff round whose Lean differs from the last audited round only in comments and docstrings is skipped:
  `scope.py` exits 3 with `NEXT[stage5]`, and Stage 5's full round audits that commit with every lane (trial #10:
  a 16-minute diff round, then the full round on the same commit). Stage 5 keeps its diff rounds.
- AUDIT_PROTOCOL B.4: rejecting the removal of an idle hypothesis the paper states needs no re-vote (the rule keeps
  the paper's hypothesis; trial #10 spent about 25 minutes re-voting an idle hypothesis and kept it).
- One count of decision matters: the report groups the [DELEGATED] lines by DECISIONS.md's sections, as the summary
  counts them (trial #10: 23 decisions on 10 matters in the report, 7 sections elsewhere).
- Every qualified Lean name SUMMARY, REPORT, DECISIONS.md and the sheet cite must exist, resolved in Lean against the
  build (`signoff.py check`, `make_report.py --check --delivery`): trial #10 delivered a Mathlib
  name with the wrong namespace, written by the operator at Checkpoint A and copied by the sheet writer.

### SUMMARY is one page (protocol-u2-int, 2026-10-23)
- Approver: "one-page summary first". Trial #9's SUMMARY.pdf was 6 pages, left out items of three kinds
  (among them stop S2), and listed 20 decision lines for 6 matters. SUMMARY.md is now one page: the goal result's
  status; the results grouped by B9's status in plain words (equal statuses on one row); one short line per defect,
  proof slip, vacuous row, "not a defect" entry, assumption, idle hypothesis (UNUSED_ARGS.md), stop, hand delivery
  and other disclosure; the answers recorded as yours with their audit commit; one line with the number of matters
  in DECISIONS.md. When the page is full, a kind's items are counted by name with the REPORT section holding them
  (never dropped); a long text gives its first sentence and the place of the full text.
- `build_summary` and `make_report.py --check --delivery` refuse a SUMMARY.pdf of more than one page (code `pdf`:
  the render fix, never a stop); the plain renderer typesets SUMMARY compact so it fits too. The coverage check
  re-enumerates every item (listed whole or counted by name; nothing dropped, changed, invented or miscounted) and
  counts defects, slips, vacuous rows and stops from the raw records.

### Trial #10 fix: one refutation name (protocol-u2-int, 2026-10-23)
- A refutation of a printed statement has ONE name, `not_<decl>_as_printed` (`make_report.AS_PRINTED`), read by the
  F10/F12 checks, scope.py's F10 scheduling, prompt.py and `signoff.py reapprove --refuted-by` (its own regex
  removed). A theorem `make_report.lean_refutations` recognises under another name (trial #10:
  a theorem named `<decl>_as_printed_false`, which got no F10 item, so the adjudicator could not record its row and a statement
  round was lost) is refused before any round: Phase 0's index check (`FAIL[index]`, statement rounds too) and
  `scope.py` print the exact rename (`make_report.refutation_rename`); the F10 problem and `--refuted-by` name it too.
- The rule reaches whoever writes the Lean: stage2's "A result false as printed" bullet, and a new
  `prompt.py --prompt formalizer` brief for author-side helpers (stage2/stage3 spawn them with it); the
  paper-faithfulness lane names the missing `not_<decl>_as_printed` in its next_step (in trial #9 a result false as
  printed shipped with no refutation scheduled).

### Trial #7 and #9 audit fixes (protocol-u2-int, 2026-10-23)
- The freeze check (`fingerprint.py --check`, every Phase 0) also compares the approval round's statements bundle
  with a fresh build: a layout-only change to an approved statement (a space lost in a docstring edit) is
  RED[drift] in the round that made it, not first at delivery (trial #7: found 5 h later).
- A self-cure is described by what its cure did (`stops.cure_done`); only a redo says a review's independence
  was compromised.
- SIGNOFF.md carries the Lean statements of the round's bundle, the no-definitions sentence and the approving
  paragraph exactly as the .tex prints them, so the plain-renderer fallback keeps the Lean (trials #4, #6, #7, #9);
  its `File.lean:N` are the lines of the sheet's own commit (`make_report.locate_names(at=)`), as it claims.
- The DECISIONS box quotes the printed statement, then '; ' and the counterexample (`decisions.why_summary`), never
  the 'why' cell's first sentence (trial #9: a sentence restating a definition).
- A QUESTION on a declaration no index row names and the delegated lines answering it each round are one
  DECISIONS.md section (trial #7: 13 of 29 decisions re-asked on four worked examples).
- REPORT: "Where the Lean names are" lists every name cited above it; the terms define F10, F12 and probe; the
  decisions section is named by title. Stage 4 goes to Stage 5 without a diff round when the only ADOPT rows are
  comment or docstring fixes.

### Trial #9 delivery fixes (protocol-u2-int, 2026-10-23)
- A reader-fix round that changes no record cell is a valid outcome: `integrity.py --commit-reader-fix` records it
  as an empty `reader-fix R n` commit (body `no change`, `rounds: <dir>`), counted toward the budget of two, so the
  remaining `[content]` findings close as unfixable (disclosed) instead of a stop (trial #9, S2).
- Generated text a reader reads is never clipped (`project.full`): the "decided since" decision on a VACUOUS row, a
  stop's note and answer, Checkpoint A, the records quoted in DECISIONS.md, the escalation question, a long first
  sentence; the box quotes the printed statement in full (it read "the paper says Let …" and stopped). Only labels whose
  full text follows may be cut; `make_report.clipped_lines` tests it.
- The proof slips of PAPER_DEFECTS.md reach the summary ("proof slip") and both boxes. The summary's appendix map
  gives SIGNOFF.pdf's path and says README.md is written at delivery; the approval names its commit as the Lean's.

### Integrated review fixes (protocol-u2-int, 2026-10-23)
- The delivery phase is bounded (`project.DELIVERY_ROUND_CAP` = 2): after the newest full round a Lean commit asks
  for a diff round (`RED[deliver-stale]`) only while fewer than two ran; past that it ships, disclosed as not
  re-audited with the cap named (report, summary, decisions item). Stage 5 said "start no further round" while
  `--deliver` asked for one per change, and each round could adopt more.
- An empty diff scope while an item awaits the next adjudication (a `leave <decl> unproved` line logged after the
  final round, a route change recorded since the last adjudication, an unsettled Fail) routes to a full round
  (`NEXT[full-round]`), never back to Stage 5 (`make_report.pending_adjudication`).
- A route change recorded in AUTHOR_NOTES.md after the last adjudication is `RED[adj-record]` at delivery until a
  round's adjudicator has seen it (ownership 3).
- A statement round given up at `signoff.py bundle` is set aside (counted by no cap); a restart at the same Lean HEAD
  is refused with the prescribed empty commit, which `tree_state` now accepts for full/statement round names.
- `stops.py open/close/list` work before the config exists (Stage 1 steps 0-1): a human stop P<n> kept beside the
  saved intake, moved under `## Stops` by `--intake-move` (which refuses while one is open).
- Dev: `RED[status-unmapped]` has a cure (a stop; Phase 0 or the index cell; what remains is accepted as shown when
  the stop closes). A Checkpoint C answer citing an escalation, an adjudicator's record or the conservative rule is
  never the human's. At the statement-round cap a QUESTION the agent decides is not an open finding. An open
  re-approval prints as "decision open", never "faithful". B9's per-result verdicts are in `LANE_ITEM_PATHS`.
  `--prepare-delivery` names make_report's failure lines and routes a PDF fault to the render fix.

### Integration of B9 and B10 (protocol-u2-int, 2026-10-23)
- The summary's result statuses are `result_status.py`'s (the B10 stub "no finding recorded" is gone); matching a
  record to a result is part-aware (`Lemma 2.4 (c)` no longer names `(a)`); `--check --delivery` adds B9's routes
  (a missing or stale verdict: `unverified`; an outstanding Fail/Ambiguous or unrecorded assumption: `adj-record`;
  `status-unmapped`: disclosed in release, refused in dev); the summary prints the status legend.
- The summary's assumption part is B5's `hypotheses.report` (it crashed on B5's dict): the count line, or NOT
  COMPUTED with its reason (as the report says, never "none"), B6's missing-theory rows, each hypothesis with its
  Lean binder/type, record state and plain English. The summary lists the human's waivers.
- An empty diff scope while a Lean commit is unaudited (mini5: a theorem turned into an `example`) prints
  `NEXT[full-round]`: run a full round, not Stage 5 (the loop between Stage 5's deliver-stale and an empty diff round).
- DEVIATIONS.md is the adjudicator's from ownership 3 (`integrity.OWNED_SINCE`): the operator proposes route changes
  under "Route changes" in AUTHOR_NOTES.md. In a run pinned before 3 its `reading choice`/`differs` rows change only
  in an adjudication (FAIL[ownership]; `--check --delivery` RED[ownership]). An operator commit making a row a
  reading choice made the summary say "faithful under reading N", unchecked.
- The plain renderer's text check reads pdftotext's `-raw` text too (its default reading drops the hyphen of a line
  ending in "-": mini4's report failed the check at every level and was called an environment fault); a plain
  renderer failure while xelatex works is `FAIL[tool-fault]` (disclosable: `TOOL_FAULT_SCRIPTS`), never the
  environment's.
- A PDF fault never opens a stop, in any mix: `stops.py open` records the other faults only (`left_out`), the
  delivery gate routes a PDF-only failure to `--render-fix`.
- Compatibility: rule 4 labels B10's owned files; GEN_INPUTS names `escalations/*` and `waivers/*`; no text sends
  the reader to "page 1 of the report"; `result_status.py` enters through `run_main` (L2).

### B9: one status per result (U2 §1: F1, F7-F9)
- `result_status.py` combines what the records say about each numbered result into the statuses of U2 §1, every
  one that applies, in order: excluded at Checkpoint B, not formalized, decision open, stated only (a conjecture:
  "stated as a proposition, asserted nowhere"), defect (B3's status and repair in plain words: "false as printed;
  proved as repaired", "vacuous as printed; intent unknown"), differs, vacuous, not established: <reason>, proved
  assuming `H` ("(source not checked)", "also proved unconditionally"), faithful under reading X, faithful.
- "faithful" (F1) only when the latest correspondence, paper-faithfulness and non-vacuity verdicts on the result,
  and correspondence and paper-faithfulness on every Definition row of its fingerprint closure, are Pass and no
  older than the result's (or the definition's) last fingerprint change; a non-Pass verdict counts as settled only
  when the adjudicator REJECTed it, or decided it and an adjudicator-owned record names the result (an operator's
  DEVIATIONS row never clears a verdict); no drift from the approved statement; every assumption classified and
  recorded (F7, F9). A NotDoneYet is no verdict.
- Routing of "not established": a missing or stale verdict -> `unverified`; an outstanding Fail/Ambiguous or an
  unclassified/unrecorded assumption -> `adj-record` (the adjudicator); drift -> `drift`; anything else -> the new
  code `status-unmapped` (disclosed in release, a stop in dev). An open question is "decision open".
- `scope.py` records each declaration's project-local deps in the round's FINGERPRINTS.json (`deps`): the closure is
  read from the record. A round without it requires every Definition row (conservative).
- DEVIATIONS.md gains the kind `differs` (U2 §3, F10).
- The interface B10's summary calls: `result_status.result_status(cfg, row, inp)`; `result_status.py [--json]
  [--check] [--live]` prints every result's status and route.

### Fix: no pinned path gave a lane the F10 item, so a false lemma deadlocked the run (2026-10-23)
- Trial #7 (release, hands-off) stopped: the adjudicator could not commit, because the
  lane refutation `not_<X>_as_printed` needed a `false` row citing a Pass F10 item that no script
  ever put into a lane's scope (and `--revote` refuses items outside it).
- `scope.py` now gives the paper-faithfulness lane "F10: the counterexample of <result>" and "F12: the
  repair of <result>" for every refutation `not_<X>_as_printed` (a declaration at the round's commit, or
  one an earlier round's lane named; a diff round only while no lane has decided it, or when it is in
  scope), and in a full round an F10 item for every `false` row, refutation-less ones included
  (`_meta.f10` records each item's source; `--verify` accepts rounds scoped before this). `prompt.py`
  lists them under REFUTATIONS TO JUDGE, naming the Lean refutation or quoting the row's counterexample;
  `--revote` takes them as items of the scope.
- `make_report`: a lane refutation is due once a paper-faithfulness lane has decided (Pass or Fail) its
  scheduled F10 item (before that the next round schedules it again), so the stuck round commits and the
  next round records the row. An F10 citation reads the item naming the row's result when the record
  judges several.
- `prompt.py --selftest` checks the invariant: every `<NAME>_ITEM` constant of a gate, and the F15 and
  B7 lane requirements, have a pinned path into a lane prompt (LANE_ITEM_PATHS), each exercised by
  rendering a fixture's prompt and passing the check with a Pass for the rendered item.

### B11: the decisions document, one decision per matter (2026-10-23)
- `decisions.py --write` gives one section per matter (U2 §6.1, D3 §4; the mini2 audit counted 23 items
  for about 8 matters): a QUESTION row on a paper result ("Lemma 1.2") and a delegated line answering
  it (`QUESTION row on <item>, round R`, or logged as `- <anchor>: [DELEGATED …]`) join that result's
  section; items on no paper result are grouped by kind (global differences, standing rules,
  delegated lines, …). Under `involved` each question, [PROXY], open question and re-vote stays its
  own section. Fix: the writer's field prompt "re-approval?" made any delegated line naming the
  approved round part of the statement approval (mini6).
- Under a delegating level an item the operator decided and logged under `## Answered` with that
  level's `[DELEGATED]` tag keeps its section, its Decision taken filled from the log, instead of
  moving to "Previously answered" (mini2, mini4 and mini6 rewrote those decisions by hand in an
  appendix of about 3,000 words). Answered items are listed once per matter. Dev too.
- The "At a glance" table has one row per section (a matter's row lists its items' sources and
  costs, `;`-separated); each item keeps its own tagged Decision taken line. The fields' writing
  prompts are HTML comments, so the delivered document shows only the field names.
- Review fixes (mini6 hands-off review): `--check` requires each decision logged in `RUN_LOG.md` to stand
  word for word in its item's Decision taken (M2: a prefilled line was rewritten as "dropped …"), and
  exactly one tagged line per item, each naming one item (M3: one line named all five anchors).
- `--check` (delegating levels) also refuses a [DELEGATED] decision that a committed `RUN_LOG.md`
  recorded and the log no longer holds (M4: a delegated record was removed and its decision rewritten).
  A decision is changed by logging a new line beside it; a line the tag check refuses may be corrected.
- Readability (the reader is a mathematician): a decided delegated line is shown once, in its Decision
  taken (it was also the item's heading and a run-log quote); a merged section's decision lines open with
  the item's plain label ("CHECK row: Lemma 1.2"), the anchor id small at the end; section headings read
  "Lemma 1.2 (5 items: …)".
- A standing rule is one matter: a QUESTION row or a delegated line naming a configured or proposed
  standing rule is decided in that rule's section, and the paper result it sits on points there ("See
  also"); the report groups the same way (mini6: the standing-defer decision stood in two sections).

### B12, B13: Checkpoint C before delivery; restarts, caps, run_main (2026-10-23)
- `involved`: Checkpoint C is asked on the checked documents BEFORE delivery; `project.py --deliver` waits
  (`PENDING[question]`, never a stop) while an item of the decisions document has no answer of the human's
  (`decisions.checkpoint_c_open`; a [PROXY] or [DELEGATED] answer counts for nothing). Stage 5 step 7, at
  every level after C's answers or a reversal: carry out; Lean changed -> Phase 0 and a diff round;
  statement changed -> re-approval; DECISIONS.md written again; documents, readers, deliver. Dev too.
- Restarts: Stage 0 saves the intake before anything else (`project.py --intake-save`; Stage 1 moves it
  into RUN_LOG.md, `--intake-move`); `project.py --stage` then says "resume, no new intake", and Stage 1
  uses `git switch` on an existing branch. `signoff.py approve` killed before its commit: run again, it
  commits the approval only when equal to the one it recomputes, else discards it
  (`FAIL[uncommitted-record]`) and the approver is asked again. `lane_auth.py reissue` finishes an issue
  or reissue killed before its commit (an issue never committed is issued afresh). Dev too.
- Caps: 4 statement rounds before the first approval, 2 per re-approval (`scope.py --statements`):
  `NOTE[round-cap]` with no faithfulness finding open (no stop: the last round's sheet, its
  statement-changing ADOPT rows recorded as decisions), `PROBLEM[round-cap]` with one (stop 4,
  `--cause round-cap`, class H). The diff-round cap is never a stop in release (a [PROXY] default under
  `involved`, put to the human at C); `thorough` is capped at 6 diff rounds under a delegating level.
- L2: every script's entry is `project.run_main`: a crash prints `FAIL[uncoded] <script>` (code
  `uncoded`, class I, kind rerun, the unknown-retry key); the project selftest checks every script uses it.
- Codex: a missing spawn tool or role, or the operator's own usage limit past the time budget, is
  `env-unknown` (a human stop). RUN.md's "Stops that remain" says which stops are `dev` only.

### Fix: the report's PDF check failed in an installed, PDF-on selftest (2026-10-23)
- The report is set ragged right (`make_report.PREAMBLE`). Justified, a line holding a long record path
  (a defect row's `F10:`/`F12:` lane paths) stretched its spaces so far that pdftotext read it as
  separate columns; the render check then failed the PDF ("does not say what REPORT.md says"), and in
  `make_report.py --selftest` that fault failed eight later B3 and SKIPPED checks. Only the PDF-on
  selftest (the operator's `selftest_all.py --fast`) showed it; every builder's tier 0 ran without PDF.
  A new check fails on the PDF fault itself; mutant pdf-on-1 removes the fix.
- Tier 0 also runs `make_report.py --selftest` and `signoff.py --selftest` with the PDF compiled
  (`tier.py --selftest` checks the plan); TIERS.md says to run it from an installed project.

### B6: missing theory (2026-10-23)
- Under a delegating level, a result needing theory no configured library has is never a stop (a goal
  result included; RUN.md's goal stop now reads "false, or unprovable for a reason other than missing
  library theory"): the operator searches every configured library, estimates, builds the theory if
  only definitions and easy lemmas are missing, else assumes the missing result as a named hypothesis
  `H` (a project Prop definition taken as a binder of the result). Never "do not formalize".
- The decision is one canonical `RUN_LOG.md` line (`[DELEGATED …] missing theory: assume `<H>` for
  `<R>` — searched: …; estimate: …; paper: "<the passage>"`, or `… build <what> for `<R>` …`; under
  `involved` the human form `- missing theory (human <date>): …`). The report check refuses, as
  `FAIL[missing-theory]` (new code: document; release F/rerun, closed by `make_report.py --check`), a
  bare or non-canonical line, one without the quote or a configured library's search, the wrong
  level's form, and an `H` that is not in its result's assumption list; a corrected line clears it.
- F13: the paper-faithfulness lane, not the operator's line, judges `H` (quote not the paper's, the
  paper derives the result, `H` stronger than the invocation: Fail); non-vacuity flags `H` that is the
  goal's main step. Section 2 classifies `H` as missing theory with its result and quote; page 1 says
  "<result> proved assuming <H>" (and every goal result whose statement takes `H` too) and how far it
  was checked.
- Review fixes: an `H` the walk flags as restating a result the project states (mini5: a
  hypothesis restating a proposition the project itself proves) is `FAIL[missing-theory]`
  ("prove it instead"), its row may only say `no`, and the F13 lane Fails a hypothesis a library or the
  project already proves; an `H` that is a goal's conclusion or restates a goal is `FAIL[unproved-goal]`
  (stop 1); a human line needs the human's committed answer naming the result on its date; option (3)
  has the human form `- missing theory (human <date>): do not formalize `<R>` — …` (refused as
  [DELEGATED]); a `build` line is refused while the hypothesis it replaces is still a binder.
- F13 item (with trial #7's LANE_ITEM_PATHS): each missing-theory hypothesis of `RUN_LOG.md` gets the
  item "F13: the missing theory <H>" (`hypotheses.F13_ITEM`) in every round's paper-faithfulness
  scope (`scope.py`, `_meta.f13`, kept as recorded by `--verify`), listed under MISSING THEORY TO
  JUDGE (`prompt.py`, `--revote` takes it); its `yes` or `source unavailable` row needs a Pass on
  that item. Mutants f13s-1..5.

### B10: delivery, landed together (2026-10-23)
- `project.py --prepare-delivery` is the only generator of what is delivered: SUMMARY and REPORT
  (make_report.py), the DECISIONS box, the approved sheet's stamp, README sections A-C; it records each
  document's generator-content hash and the Lean commit in `DELIVERY.json` and commits all of it ("prepare
  delivery"). It runs while a stop is open (listed OPEN AT PREPARATION).
- `project.py --deliver` only checks, in both modes: `make_report.py --check --delivery` (each prepared
  document recomputed in memory and equal to its record and its file; each reader gate; the summary's
  coverage and result-status check; `unverified`, `deliver-stale`, pending items), no stop or QUESTION
  open, `deliver_blocking`, the render recompute of SUMMARY.pdf, REPORT.pdf and SIGNOFF.pdf; then the copy,
  with README = A-C as prepared + section D (known faults, delivery-phase records, reader outcomes), D
  only in the copy (ADDENDUM N6).
- One-page summary (`SUMMARY.md`/`.pdf`, delivered first; REPORT's section 0 points to it): every result
  with every status that applies, every defect, reading choice, assumption, decision taken on the
  reader's behalf, stop, self-cure and disclosed fault, one generated line each, never clipped. Until B9
  a result with no recorded finding reads "no finding recorded", never "faithful".
- Delivery codes `deliver`, `unverified`, `deliver-stale` are preconditions of `--deliver`, never a stop
  (ADDENDUM N1); `pdf` is never a stop either (approver: once the documents exist the run does not stop;
  the render fix ends at worst in the plain renderer). `stops.py open` refuses them in both modes.
- Readers: `--doc summary` (gated at every level); REPORT and DECISIONS get exactly one pass per version
  once the delivery flow runs; findings are labelled `[content]` or `[presentation]`; a content finding
  goes to the adjudicator's reader-fix round (`prompt.py 4 --reader-fix`, `integrity.py
  --commit-reader-fix`, at most 2 per run, its prompt hash checked by lanecheck; ADDENDUM N4). The
  hands-off sheet has no reader (`signoff.py check` kept; disclosed in the README); `deliver_checks` no
  longer gates it (with stage2-statements.md, L4). Dev: a missing pass, or a blocking finding left
  unfixable past the budget, is a stop.
- Generated documents cite the last Lean commit, never HEAD (ADDENDUM N2); a delivery-phase record (a
  reader's, the PDF's or the rendering's disclosure) is listed in README D, never in the documents.
- Dev-reaching (U2 §10): the reader modes and fix route, the summary, prepare/deliver.

### B4: refuted-statement repair (2026-10-22)
- `signoff.py reapprove --begin --refuted-by <ns>.not_<X>_as_printed` (U2 §3, F11, ADDENDUM N3): checked
  in Lean -- the theorem's type is `¬ <X>_as_printed`, its axioms are standard (no `sorryAx`; the
  refuted statement's own `sorry` may stay), `<X>_as_printed` is defeq to the statement approved at B,
  or after a failed correction the same `_as_printed` the first repair checked. A goal result is
  refused (stop 1). The begin records the refutation (`REAPPROVAL.json` `refuted`). Dev too.
- F12: a `false` defect row with a minimal repair (typo, add hypothesis, local) cites the
  paper-faithfulness lane's F12 item (Pass, naming the step of the paper's proof that uses the added
  hypothesis), else `PENDING[adj-record]` (the repair is `substantial`); a `--refuted-by` refutation
  needs its `false` row or encoding-error line, like a lane's. Lane C and the adjudicator prompt say so.
- M5: the delivered sheet (the latest approval's) keeps its CHANGED marks when rendered again after
  its approval (compared with the approval before it; approvals ordered as made, not by commit hash);
  a hands-off re-approval sheet says "Statements unchanged since the latest approval; K re-approved by
  the agent, marked CHANGED."; `approve --by human` on a re-approval refuses until the sheet's
  fresh-reader check passes.

### B2: questions, the pending state, the stop policy (2026-10-22)
- Level-reserved decisions are QUESTIONs, never stops: under `involved` and `statements-only` a change
  to a statement the human approved is a question (`reapproval.md`); the run goes on and only
  `project.py --deliver` waits (`PENDING[question]`, no failure line). Under `statements-only` a
  QUESTION row on that statement is the human's (`decisions.needs_human`).
- `signoff.py approve --by agent` closes an open re-approval only under `hands-off`, or when the
  intake's 5d chose the agent (the first logged answer), and only when the approval it replaces
  was the agent's; otherwise it refuses with `PENDING[question]`. An unreadable 5d means the human.
- Pending state (H3): while that question is open, Phase 0 (author and read-only) prints the
  statement's `sorry` as `NOTE[reapproval]`, the report check prints `PENDING[question]` instead of
  refusing the open re-approval, `decisions.pending_unproved` leaves the statement to the question,
  and the axiom sweep accepts sorryAx reaching a result only through it (a walk that stops at the
  pending declarations; a goal result is never pending).
- `drift`: the release cure is always restoring the approved statement; an intended change is a
  re-approval begun before the edit, never inside the open stop.
- `project.stop_policy_text(mode, level)` generates the intake paragraph (the four stops; the
  questions each level asks; a dev installation sends its own) and the Checkpoint A line
  (`prompt.py --show intake`; without a config, the installation's mode). `tests/doclint.py`
  checks `stage0-intake.md` carries it. The intake no longer says tampering stops a release run.

### B7, B8: smaller items, rule 4 (2026-10-22)
- A literature hypothesis later proved is never retired and never re-pinned: its proof lands as a pure
  addition `<decl>_unconditional`, audited by the next round like any new declaration (U2 §7a).
- Non-vacuity lane: a step of the paper's proof by contradiction needs the paper's quoted passage and
  the negating lemma (`CONTRADICTION STEP: negated by ...; paper (tex l.N): "..."`); a docstring alone
  is Ambiguous, and a Pass claiming the step without that form is a lane fault (re-voted). A passed
  step needs its VACUOUS.md row (`PENDING[adj-record]` until the adjudicator writes it) (§7b).
- Non-vacuity lane: each goal and main theorem is tried with `first | decide | simp | omega | aesop |
  exact?` under short heartbeats, with and without its hypotheses; a closure is Ambiguous (a QUESTION
  row, the sheet's CHECK), never a Pass (§7c; a lane judgement, not enforced by a script).
- Reading choices: never formalize both readings; the adjudicator's QUESTION row recommends the weaker
  one, or, when neither implies the other, the one the paper's proof proves; RUN.md "How you decide"
  takes it under a delegating level (§7d).
- The report's "Proof routes" row adds "slips are recorded when found; proofs are not checked line by
  line against the paper" (§7e).
- Escalation check (§7f): `prompt.py --prompt escalate --question ... [--decl] [--passage "tex l.N-M"]
  --write` builds the prompt (question, declaration with `File.lean:N`, paper passage quoted from the
  source), writes it once and commits it as `escalate E<n>` with its sha256 and inputs;
  `lanecheck.py --escalation E<n>` refuses an answer whose prompt changed, was committed otherwise, or
  is not what prompt.py renders for the recorded inputs, and commits the answer. A new owned record
  (`escalations/`, `escalate`). Dev too.
- RUN.md rule 4 is generated from `integrity.OWNERS` (`integrity.rule4_text`; doclint checks it), and
  names the reader responses and notices the operator writes (it used to forbid them) (U2 §5, §8).
  `reapproval.md`: a delegated re-approval may also repair a refuted statement.

### B7 re-check fixes (2026-10-23)
- `lanecheck.py --escalation E<n> --returned-file <file>`: the subagent's final message, saved verbatim
  with a quoted heredoc (`cat > <file> <<'RETURNED'`), so the backticks and `$` the escalation prompt
  invites survive (a `--returned "..."` call lost them and the honest answer was refused). The answer
  file must still be the message's last line. The protocol text and prompt.py's printed line show it.
- A contradiction step's quote is compared with the .tex with all whitespace, `$`, ties, spacing
  macros and simple formatting wrappers (`\emph`, `\textit`, `\textbf`, `\text`, `\mathrm`, ...: their
  argument kept) dropped, and `{x}` read as `x`: `$x_{n + 1}$`, `\pmod{m}` or a dropped `\emph` no
  longer make an honest quote a lane fault.
- An escalation names its declaration (`prompt.py --prompt escalate ... --decl`, now required), and the
  matter it is about is keyed on the declarations it names (`--decl` and declared Lean names in the
  question), never on its wording: a later escalation on a declaration whose earlier escalation was
  answered NEEDS-HUMAN or has no accepted answer is its re-ask (under `involved` citing it is
  refused). A rephrase ("Is ℤ the intended domain ...") used to pass.

### B7 review fixes (2026-10-23)
- Escalations: an answer counts only when `lanecheck.py --escalation E<n> --agent-id <id> --returned
  "<final message>"` commits it from the subagent's own returned line (id and sha256 in the commit).
  The report's "Decisions after the intake" lists every escalation with its answer (both renderings);
  a later one on the same matter as an earlier NEEDS-HUMAN is marked as its re-ask. A cited
  "escalation E<n>" must exist and be accepted (report check, `decisions.py --check`); under `involved`
  citing a re-ask is refused (the human's question). A DECISIONS.md section citing one shows its answer
  and a re-ask's earlier NEEDS-HUMAN; an accepted ANSWERABLE counts as a Recommendation's source.
- Contradiction steps: the quote must occur in the paper's .tex (whitespace aside) and the negating
  lemma must be declared, else a lane fault; the VACUOUS.md row must name the step or lemma exactly in
  its statement cell, status open or repaired. A Pass the adjudication overturned (REVOTE NEEDED,
  QUESTION, a Fail/Ambiguous verdict cell) demands no row (it was PENDING forever). The marker is read in
  any case as a label.

### B1c review fixes (2026-10-22)
- `--restore-gitmeta` writes and deletes only in `<gitdir>/hooks`, and only when that is also the
  snapshot's resolved hooks directory. The snapshot records the resolved hooks directory and
  `core.hooksPath` in every scope; either one changed is `FAIL[env-unknown]` (stop 3), nothing
  restored (attack H: a global `core.hooksPath` made the cure delete another directory's files).
- The revert test compares HEAD's tree with the tree hash `--save` recorded (a baseline without
  one accepts nothing), never asks git for the baseline commit's tree again; `tree_state` and
  `integrity` run git with `GIT_NO_REPLACE_OBJECTS=1`. A `refs/replace/*` ref or `info/grafts` is
  `FAIL[gitmeta]` (and `--save` refuses); one not in the Stage 1 snapshot is `FAIL[env-unknown]`
  (attack R: a replace ref made a tampered tree pass as "reverted to the baseline").
- `--revert-foreign` refuses (`FAIL[gitmeta]`) while the git hooks or config differ from the
  baseline or the Stage 1 snapshot, and commits each revert with `-c core.hooksPath=/dev/null`,
  `--no-verify`, `--no-gpg-sign`: no hook runs (attack K: a planted post-commit hook ran).
- Destination settings are stop 3 like a remote's url, in every scope: `url.*.insteadOf` /
  `pushInsteadOf`, `http.*.extraHeader`, `branch.*.pushRemote` / `branch.*.remote`,
  `remote.pushDefault`, `core.sshCommand` (attack U: they were restored, or not seen, as gitmeta).
- `integrity.revert_problem`: the record files a revert changes must be exactly the foreign
  commit's misowned ones (a superset, undoing records that commit owned, is no verified revert);
  its other files must be exact inverses; a verified revert excuses only its misowned files that
  are the foreign commit's. Content only, no stop binding. Mutant b1c-r5a ("accept a superset")
  replaces the retired scr-5b (compat H1).
- The Stage 1 snapshot comparison and the stop-3 identity, destination and history checks of
  `tree_state --check` apply in release only; dev is as before B1c (every gitmeta change, rewritten
  history included, is `FAIL[gitmeta]`, the human's) (compat M1).
- A pin without a Stage 1 snapshot: `--restore-gitmeta` is `FAIL[env-unknown]` (stop 3); a re-pin
  adds the snapshot when the pin has none (compat L1). `user.*` / `credential.*` count for stop 3
  only in the repository's own (local, worktree) config; a remote's url, the destination keys and
  `core.hooksPath` in every scope (compat L2; the rule is stated in RUN.md).

### Reverts by tree equality, gitmeta snapshot (U2 B1c, 2026-10-22)
- `head-moved` is a restore in release: `tree_state.py --revert-foreign` runs `git revert --no-edit`
  over the whole foreign range (`-m 1` for a merge); `tree_state --check` accepts a range that changed
  files only when HEAD's tree equals the baseline's (NOTE[reverted]; dev unchanged). A commit titled
  as a revert is never accepted by its subject.
- `integrity.verified_reverts` pairs a revert with the earlier commit whose foreign record change it
  exactly inverts, by content; `stops.py revert`'s and `git revert`'s commits both qualify, and the
  stop-record binding is dropped.
- The pin records a Stage 1 snapshot (`tree_state.snapshot`: hooks with content, risky config,
  remote url/credential/user, HEADs); `tree_state --check` compares against it; `--restore-gitmeta`
  restores only its hooks and keys. A changed remote, credential or user setting, or pinned history
  no longer an ancestor, prints `FAIL[env-unknown]` too: stop 3. No author or identity test.

### Failure tally and redo lineage (U2 B1b, 2026-10-22)
- Release self-cures are bounded by one failure tally (`stops.fault_keys`, `tally_events`, `tally`):
  fault key (check script, cause code); a `--note` stop keyed by (its code, round), the retry codes
  (`unknown-retry`, `tool-call`, `git-error`, `tool-bug`, uncoded) sharing one key, plus the coded
  faults its check printed. Failed cures counted over the whole run (`CURE_BUDGET` 2), openings per
  key and round (`OPEN_CEILING` 3, new); passes are no longer counted. Replaces `cure_key`,
  `cure_history`, `same_cure`.
- Review fixes: per-stop cap (a stop with 2 failed cures of its own is stop 4, whatever codes); the
  failed-cure budget is whole-run per (check script, code), `(script, unknown)` included, and
  `commit-refused` joins the retry codes (a `--note` key now counts openings only); openings count
  only after a failed cure of that key in the round, bucketed by the newest round with a verdict
  file or adjudicated; a child's capacity error or usage limit waited out is logged, no stop; a
  redo's fresh round must have sealed verdicts on every item of the set-aside scope, and a redo
  whose check names no round also runs `lanecheck --round <fresh round>`.
- Re-check H3: a `--note` stop's openings key carries its check script, ("--note", code, round,
  script): tool failures on different checks after one failed cure are different faults.
- Re-check H1: the run-wide budget per (check script, code) is its own constant, `KEY_BUDGET` 3
  (the per-stop cap stays `CURE_BUDGET` 2): a flaky check failing one cure in each of two far-apart
  rounds is not stop 4, a third failure is. A cure attempt is numbered per stop.
- Redo lineage: `scope.py` records `_meta.redo_of` (the open stop's set-aside round) in TARGET.json;
  `--verify` ignores it; a redo closes only on such a round, covering the set-aside scope with its
  lanes run; another code Y on the fresh round charges Y; unreadable lineage is the human's.
- STOP.json records `mode`; an operator close of a stop opened in release is a trail fault.
  A closer's `--project` is dropped only when it names this project.

### One cure table and real closers (U2 B1a, 2026-10-22)
- **Release:** `project.RELEASE` is one table `{code: (class, kind)}`; the kinds are rerun, restore,
  redo, reprove, human and disclose, and `open` prints `CURES[kind]` plus the code's own text
  (`_CURE_OF` and the special cases of `cure_plan` and `close --cured` are gone). RUN.md's failure
  table has a generated release column, checked by `tests/doclint.py`.
- **Release:** a stop's check is a read-only FORMS command (a build command is refused; Phase 0
  read-only checks the build); `open --note` needs `--check <the read-only check of the step that
  failed>` except for a human code; a `--note` cause that is no cause code is refused (an uncoded
  failure is `--cause unknown-retry`, now self-cured with its `--check`); `close --delegated` is
  dev-only. `tool-call`, `git-error` and `lane-output` are self-cured reruns instead of human stops.
  The cure kinds were renamed in new CLOSED.json records (`set-aside` -> `redo`, `restore-pin` and
  `revert` -> `restore`; `revert` now needs a stop of kind restore).
- **Both modes (dev-reaching):** `project.py --deliver` re-runs `deliver_blocking` in dev too
  (integrity, fingerprint once something is approved, Phase 0 read-only, each self-cured stop's
  check) and refuses on any failure. Dev is otherwise unchanged: no self-cure, `--delegated` kept,
  every class waits.
- Tests: an L1 selftest closes a stop of every code x mode x level (real integrity check with the
  stop open), and the snapshot replay re-runs each passing closer gate with a stop open.

### B1a review fixes (2026-10-22)

- Release: a `--note` stop of a code with a closer of its own records exactly that closer (H-1);
  `--deliver` also re-runs those closers. A redo stop whose round its self-cure set aside closes on
  the fresh round (`redo_round`; addendum N5). `--delegated` records the mode; a release-mode
  operator close is a trail fault. `--cause tool-bug` without `--check` is a human stop (a pinned
  writer that keeps crashing). `lanecheck --kill` is no longer a check form. Docs: release retry
  route mode-qualified; interim closer rows marked; MAINTAINING S3/S4.

### Test harness for the U2 build (B0, 2026-10-22)
- Tier 1 runs the fast selftests under both run modes x the three levels; the new test switch
  `FORMALIZE_TEST_MODE` is honoured only by `--selftest` processes (a real run keeps its
  config's mode). Tier 2 adds `tests/snapshot_replay.py`, which replays the mini1–5 run snapshots
  through the read-only gates in every mode x level against `tests/replay_baseline/`. No change to
  what a run does.
- The snapshot replay prefers the full snapshots (both git repositories): the runs' real history is
  replayed, and the recorded project path (under the test machine's home directory) resolves to the copy through
  a private mount namespace (no byte of the record rewritten; any other path still fails). The
  baselines were re-recorded (all rows: the lanecheck `PROBLEM[auth-metadata]` and
  `RED[dependencies]` artefacts of the synthetic history are gone).

### Run mode: release and dev (2026-10-21)
- **One codebase, two modes (`mode` in the config, set at install).** `release` is the default. It
  stops a run only for faithfulness, proof validity, integrity and the human stops. A finding of
  presentation or bookkeeping prints `DISCLOSED[<code>]` and does not fail its check. That covers
  report rendering, PDF, line citations, reader-gate findings, record formats, part labels,
  docstrings and the log's round list. It also covers a self-test failure or crash of a script
  that serves only those. `stops.py disclose` records it. The report's "Run mode" row and stop
  list, DECISIONS.md's box and `deliverables/KNOWN_FAULTS-run.md` list every one.
  `install.sh --dev` keeps every stop.
- The classifier is `project.RELEASE`. CLASSIFICATION.md gives a class to every place that can
  stop a run. The three stops of the first small-paper run (S1-S3) would have been disclosed
  under `release`. Mutants RM-1..RM-25 check that no F/P/I/H check becomes non-blocking.

### Guarantee changes approved by the approver (2026-10-20)
- **A lane's mention of a record file is a note, not a stop (A1).** lanecheck prints
  `NOTE[independence]`, and the adjudication commit refuses until each note is settled in
  ADOPTED.md. A mention is settled by a `CLEARED <lane file>: <reason>` line or by a whole-lane
  re-vote. A path into another round, or into another lane's verdict or probes, needs a whole-lane
  re-vote and cannot be cleared. Such a path is now caught; a lane citing a sibling's probe
  directory used to pass. Clearances have their own report section.
- **Lane mistakes are re-voted, not stops (A2/A3).** These cases are sealed, recorded in the seal
  and reported as `NOTE[lane-fault]`, and the adjudicator orders a re-vote: a cited probe that does
  not exist, a probe directory that differs from the lane's manifest, or no manifest. Only a change
  after the seal commit counts as tampering (`PROBLEM[evidence-after-seal]`). If a re-vote lane
  itself makes a mistake, its row is left open for the person.
- **A human waiver for an ownership failure (A5b).** `integrity.py --acknowledge <commit> --stop
  S<n>` is allowed only for a commit that added files, and only on a stop the person closed. The
  report's first page lists every waiver.
- **A failure with no cause code is retried, then classified (approved 2026-10-20).** It is no
  longer a stop as such. The operator records it (`--cause unknown-retry`) and re-runs it within the
  retry budget. If it persists, a traceback from a pinned script in `audits/` is `tool-bug`, a STOP
  class; anything else is `env-unknown`, fixed as an environment fault and closable with
  `--delegated`. The scripts still treat an unrecorded code as a stop.
- **The stall resolver is replaced by recorded stops and one `set-aside` command (A7).** See
  "Stops and set-asides" below.
- **Cached bytecode in `audits/` is a note (A10a).** It used to be an integrity failure; now
  `project.py --env-check` removes it. A sourceless or unchecked-hash `.pyc` still fails.

- **A non-goal result the operator cannot prove is left unproved and disclosed, not a stop (Q1 (b),
  2026-10-20).** Under a delegating level the operator keeps the statement byte-identical and
  unproved and logs `[DELEGATED <date>, operator under <level> (intake); reversal: re-prove] leave
  <decl> unproved — <reason>`. Phase 0 reads that line from the committed `RUN_LOG.md`: a `sorry`
  inside a declaration it names is `NOTE[unproved]`, any other stays `RED[sorry]`, and a goal
  result named there is refused (`RED[unproved-goal]`, a stop). The axiom sweep allows `sorryAx`
  for exactly those declarations, so every result whose proof uses one needs its own line. The
  adjudicator records each in `SKIPPED.md` ("Hard" stays no reason otherwise); `make_report.py
  --check` requires a "not formalized" index cell and that row, with the tag as "decided by",
  once a round has been adjudicated since the line. The report (coverage section and page-1 box)
  and `DECISIONS.md` disclose it as "stated, not proved". A goal result that stays unproved is
  still a stop; under `involved` nothing changes.
  After review: index names are resolved as the dependency walk resolves them (as written, then
  namespace ++ name), so a goal the index cites unqualified is still refused, and the sweep itself
  refuses a goal named in a leave line; the sweep's allowance under an exempt `X` covers only
  compiler-generated names (`eq_<n>`, `eq_def`, `eq_unfold`, `proof_<n>`, `induct`,
  `mutual_induct`) with no source range; "pending" is keyed on the declaration, and
  `project.py --deliver` refuses a result still pending (a line logged after the final diff round
  needs one more diff round); only a top-level line of `## Open questions`, `## Checkpoint C` or
  `## Answered` that begins with the tag counts; Phase 0 reads `set_option … in` / `open … in`
  declaration lines.
  After re-check: `decisions.py --check` (run before the completion message) refuses a result still
  pending, as `--deliver` does; the report lists every auxiliary the sweep accepted under an exempt
  name, with its parent (recorded in `DEPENDENCIES.json` by the walk, same rule); while a leave line
  is active a project `elab`/`macro`/elaborator attribute or `addDecl`/`addAndCompile` is
  `RED[unproved-meta]`; a leave line's anchor must be a real decisions anchor (`considered:` is not).

### Stops and set-asides
- `stops.py` records every stop with the raw output of the failing check and a cause code per
  failure line. `close --delegated` is refused under the involved level, for a STOP-class cause,
  and while the check still fails. The report lists every stop and who closed it.
- `stops.py set-aside` replaces abandoning a round or a re-vote lane. It commits every remaining
  file of the round or lane, by name, with an inventory computed by the script; nothing is deleted.
  Every Fail or Ambiguous item of the set-aside lanes is carried forward, and the next adjudication
  and the final report refuse until each has a row. Under a delegating level it refuses a round
  with a STOP-class cause unless the person closed that stop.
- **Structured cause codes (A9).** Every failure line starts with `KIND[code]`, and `project.CAUSES`
  gives each code its class. An unknown code, or a failure line without a code, counts as a stop
  (it fails closed). Normal states, such as nothing approved during a re-approval, are not stops.
- Smaller causes removed (A10). The tree_state git-config allow list takes exact keys and values
  only (submodule and git-lfs defaults). A project's extra glyph mappings are its own disclosed
  record (`signoff.py glyphs --add`), not an apparatus edit. The round name must match the full
  HEAD hash. `project.select` refuses a config with a hard error.
- `audits/tests/replay.py` replays the four live stops on the current design.

### Records
- **Commit at seal (A4).** `lane_auth.py seal` commits the lane's verdict and its probe files in
  one commit, by name. Sealing again is safe: it completes an interrupted seal, and a lane already
  sealed gets its existing seal commit back. A lane has one seal, ever.
- **Every record is committed by name (A5); no instruction uses `git add -A`.** The adjudicator
  commits with `integrity.py --commit-adjudication`. The commands of `signoff.py` and `scope.py`
  commit what they write. Ownership rules carry a version: a run pinned earlier keeps the rules it
  started with.
- **Re-approval begins before the edit (A11).** `signoff.py reapprove --begin` records the Lean
  HEAD and the approved fingerprints before any statement is edited. The freeze check then reports
  a change to a listed declaration as `NOTE[reapproval]`, and any other change as a drift.

### Round-3 audit fixes (scripts)
- **An open re-approval fails the report check.** `make_report.py --check`, and so Phase 0's
  report step, fails while `REAPPROVAL.json` is open. The report lists every re-approval of the run
  (begun, declarations, reason, which `approve` closed it) in the trust table and under
  "Re-approvals during the run", and the trust row no longer says that no statement changed.
- **A REVOTE NEEDED row is not a re-vote.** A decision (ADOPT, REJECT, DEFER) that follows a
  REVOTE NEEDED row counts only once the re-vote lane for that item (or the whole lane) is sealed
  or set aside, and only in an "adjudicate R revotes" commit after that seal. A carried Fail whose
  last row is a REJECT needs the same. A lane fault is settled by a REVOTE NEEDED row for each item
  whose verdict cites the faulty probe, not by a row for another item of the lane.
  `tests/round3.py` keeps the round-3 attacks as self-tests.
- **A re-vote lane is held to more than a first-pass lane.** It runs while its round's ADOPTED.md
  holds the adjudicator's reasons, so a path into its own round (other than its own files) is
  `NOTE[independence-path]`, and none of its notes can be cleared: its row is left open for the
  person.
- **The settle check runs on the committed record too.** `integrity.py --check`
  (`FAIL[unsettled]`) and `make_report.py --check` check every adjudicated round's NOTEs, lane
  faults and re-vote decisions, so an ADOPTED.md committed by hand as "adjudicate R" does not
  bypass the check of `--commit-adjudication`.
- **One parser for decision cells** (`project.decision_of`). The carry check, the settle check, the
  re-vote list and the report read a decision cell alike: backticks, italics and bold are
  formatting, struck-through text is dropped, and a cell that does not open with a decision is
  refused at adjudication.
- **A waiver is bound to its stop.** `integrity.py --acknowledge C --stop S` needs a stop recorded
  with `--cmd` on the integrity check while it printed `FAIL[ownership]` for commit C (the message
  now names the commit), closed by the person; one waiver per stop. A commit that adds a record
  another check reads (a set-aside marker, a seal, ADOPTED.md, a stop or waiver, an approval, a
  reader's report, ...), or lane evidence its lane's seal did not record, is never waived.
- **`set-aside --lane` refuses a sealed re-vote lane with no fault of its own**: it is settled by
  "adjudicate R revotes", not set aside.
- **`lane_auth.py reissue` rolls back a failed commit** (a stale `index.lock`): the verdict, its
  probes and the token commitment are restored, so the reissue runs again after `stops.py
  repair-lock` instead of leaving a tamper-class state.
- **Interrupted record commands can be re-run.** `stops.py open` and `close` first commit a stop
  file left uncommitted by a kill; `set-aside` completes a marker whose inventory still matches,
  or starts again when the marker was cut short; `integrity.py --acknowledge` writes an
  uncommitted waiver again.
- A lane naming another round by its commit hash ("round 0b23c87") is `NOTE[independence]` again
  (the simplification had dropped it).
- **A carried Fail is settled only by a row about it**: a row of the carried lane whose verdict
  cell is the carried verdict (ADOPT, DEFER, QUESTION), a REVOTE NEEDED row, or a decision after
  the re-vote ran. A fresh lane's Pass, or another lane's row, does not settle it.
- `stops.py repair-lock` is recorded in the stop record (`stops/repairs/R<n>.json`, committed as
  "stop repair R<n>"), and the report lists it with the stops.

### Round-3 audit fixes (instructions, docs, axiom sweep)
- The instructions describe the round-3 rules where the operator meets them: an open re-approval
  must be closed before delivery (RUN.md, `reapproval.md`, Stage 5); a REVOTE NEEDED row settles
  its item only through the re-vote adjudication after the re-vote lane's seal, and the settle
  check also runs in `integrity.py --check` and `make_report.py --check` (Stage 4, adjudicator
  prompt); a re-vote lane's NOTE is LEFT OPEN, never CLEARED; decision cells open with the bold
  decision; a waiver needs a stop recorded with `--cmd` on the integrity check, one per stop,
  report records only; `set-aside --lane` refuses a re-vote that can still be settled; a reissue
  runs again after `repair-lock`; interrupted stop, set-aside and waiver commands are re-run.
- A result you cannot prove is never removed or weakened under a delegating level, except missing
  theory as a named hypothesis (failure table, Stage 3). A statement change at Stage 5 under
  `statements-only` is a stop. RUN.md rule 2 names the escalation prompt as its one exception;
  rules 4 and 5 list every owned record and commit prefix. The document-check exception is
  recorded as a stop and closed delegated. Smaller wording fixes (`approve` commits itself,
  Checkpoint A under `hands-off`, the Checkpoint B question verbatim under Codex, literature
  hypotheses under `statements-only`, committing by name at delivery, INSTALL's denied edits).
- Test-run mentions are generic everywhere (code comments, fixtures, mutant names). `NOTICE`
  lists every adapted source `AUDIT_PROTOCOL.md` names.
- `axiom_sweep.py --selftest` matches the sweep's messages as whole lines (a miscount such as
  "11" for "1" is caught), exercises the module rule on an imported temp module with a root-level
  `sorry` (mutants X14, X15), and labels the fallback check by what failed.

### Round-3 re-check fixes (R3c)
- **A re-vote lane that was set aside never counts as the re-vote having run** (never spawned,
  crashed, unsealed or `--unsealable`): no ADOPT, REJECT or DEFER of its item after the REVOTE
  NEEDED row is accepted; the item stays open for the human (an unsettled re-vote in DECISIONS.md
  and the report), and the Fails the set-aside lane carried are settled by that open row.
- **An interrupted set-aside is never committed as found**: running `set-aside` again recomputes the
  marker after every refusal (an adjudicated round, an unsealed lane, a STOP-class cause under a
  delegating level, ...) and commits the uncommitted marker only when it equals the recomputed one;
  otherwise it refuses, leaves the file, and prints the recovery (remove it, run again). A
  whole-round set-aside refuses an uncommitted re-vote lane marker in the round.
- **An interrupted stop is never committed as found**: `open` and `close` recompute an uncommitted
  STOP.json (a `--cmd` stop: the check re-run, its exit, output and causes; refused if it passes
  now) or CLOSED.json (the re-run and every `--delegated` refusal) and commit it only when equal;
  a `--note` stop keeps the operator's note and cause code. `integrity.py --acknowledge` refuses a
  stop whose STOP.json or CLOSED.json is not committed.
- RUN.md lists "a result that stays unproved and is not missing theory" among the stops that
  remain at every level (the current behaviour).
- Self-tests from the re-check attacks (tests/round3.py, N1-N3) and mutants R3c-1a..3c.
- **R3d (final check F1-F3): a re-vote settles an item only when it is THE re-vote of that item**:
  its sealed verdict has an entry for the item (a whole-lane `--ALL.k` of another batch part never
  judged it); when more than one sealed re-vote judged the item, none is chosen (no sort order) and
  the item stays open for the human; an item whose re-vote was set aside stays open for the human
  even after a later item or whole-lane re-vote. Self-tests t_r3d (attacks3 V9, V7, V6, with
  controls) and mutants R3d-1..3.
- **R3e (narrow review H1, M1, M2, L1-L3): one strict reader of ADOPTED.md decision rows**
  (`lanecheck.decision_rows`), used by the settle check, the re-vote rules, the carried-item check,
  and the open re-vote, question and UNCOVERED lists: the lane cell must be exactly one lane name of
  the round and the item cell exactly one scope item (only surrounding spaces, emphasis and
  backticks ignored); any other row is refused by the adjudication commit, `integrity.py --check`
  and `make_report.py --check`. Open re-votes are keyed by (lane, item) and settled only by a row the
  re-vote rules accept; a re-vote entry counts only with a Pass/Fail/Ambiguous verdict and one entry
  for the item; an unsealed re-vote covering the item blocks its decision; a `(whole lane)` row is
  settled once its whole-lane re-vote settled the lane's items; `--ALL.k` covers only its part's
  items; a set-aside `--ALL*` marks its row abandoned. Self-tests t_r3e, mutants R3e-1a..7.
- **R3f: an UNCOVERED row may name any declared item of the project.** The strict reader's item
  names are the round's TARGET.json items, carried items, `(whole lane)` and every declared item of
  the project (`lanecheck.project_items`: the index file's row labels, the declarations' full names,
  and every name a round's FINGERPRINTS.json keys), so an UNCOVERED row for a NotDoneYet index
  entry or a STALE PASS is accepted; matching stays exact. `audit_coverage.read_adopted` reads a
  record pinned under ownership 2 or later through `lanecheck.decision_rows`, and keeps its
  best-effort reading only for older records (no pin, or ownership 1). Self-test t_r3f, mutants
  R3f-1a..2b.
- **R3g (narrow X4, junk entries): lanecheck validates every lane verdict file's schema.** The file
  must be one JSON object, its `verdicts` a list, and every entry an object with a non-empty
  `item` and a `verdict` of Pass, Fail, Ambiguous or NotDoneYet. A violation is
  `NOTE[lane-fault]` for that lane and covers all its items: an original lane needs a REVOTE
  NEEDED row for every item it names (a whole-lane row when an entry names none). A re-vote lane's
  violation means it validly judged nothing: its row stays open for the human (LEFT OPEN), and no
  decision can follow it. Before this change, a sealed re-vote with one valid entry beside
  non-object entries licensed the REJECT. Self-test t_r3g, mutants R3g-1..3.

### Deferred (round-2 proposal, group G)
- G1 (planted-fault benchmark for the faithfulness lanes) and G2 (hands-off smoke test without a
  resolver) are later test material: they run on the planned small test paper, after this release.
- G4 (a reader's re-found `unfixable` finding counts as answered): deferred; it changes what blocks
  a document and needs its own review that it cannot hide a new finding.
- G5 (one standing question per hypothesis and declaration): deferred; it needs a stable key (the
  declaration fingerprint) in the adjudicator's template and in `audit_coverage.py`.
- G6 (statements-only fixtures, a stop before and after Checkpoint B): deferred; the level has not
  run yet, and the small-paper test is the first source for realistic fixtures.
- G7 (records cite Lean names, generators render the lines): deferred; it changes the format of
  every adjudicator-owned record and of the generators.
- G9 (`git push --dry-run` at intake): deferred; a blocked push is already a remaining stop.
- G8 (a lighter round for docstring-only diffs after Checkpoint C): not now; it reduces audit
  coverage, an approver decision.

### Instructions
- **RUN.md is an always-read core of about 2.8k words** (it was 14.8k). The rest moved to one file
  per stage, plus procedure files, under `audits/run/`. `project.py --stage` names the file to
  read, and also does so on resume. The operator no longer reads AUDIT_PROTOCOL.md, and neither do
  lanes or readers: the verdict schema is inline in their prompts.
- **One failure table**, keyed by cause class. A `sorry` is the author's work in progress, not a
  stop. A mechanical retry gets a time budget (up to 2 hours) instead of "once more". Usage limits
  and capacity errors are waited out.
- **A script prints the intake** (`prompt.py --intake`). The operator sends it unchanged, as one
  message, and the first pin checks its hash.
- The adjudicator's prompt is self-contained, and re-votes have their own prompt. Under Codex the
  escalation check runs as the role `formalize_escalation`, the sixth role. The by-hand mode is
  dropped.

### Report, sign-off sheet and decisions (from a test run's audit)
- The report states verifiable facts about the order of work: when the statements were committed,
  when they were approved, and that they are unchanged since. It never claims that the statements
  came "before any proof was written". Proofs may be drafted aside once the statements are
  committed.
- New report sections: the decisions taken after the intake, every `[DELEGATED]` decision in full,
  every stop of the run, set-asides and clearances, and the proof routes. The proof-routes section
  includes the results the goals do not use, from a new dependency walk (`dependencies.py`, checked
  in Phase 0). Global differences are defined in the report, and unsettled re-votes are listed with
  the open questions.
- The sign-off sheet has a background section, a legend, the paper's `tex l.N` for each result and
  `File.lean:N` for each Lean name.

### Scripts and tests
- Rounds are ordered by Lean ancestry, in one place (`project.order_rounds`). Shared helpers have
  one home (`project.py`): the Lean runner, LaTeX, the index file and the table-row splitter. One
  script registry (`project.SCRIPTS`) feeds selftest_all, the allow list, the mutants and the
  watchdog.
- `check_index.py` is merged into `make_report.py --check --index-only`. The DEPENDENCIES.json check
  moved to Phase 0. The watchdog moved to `codex/`. Dead options were removed.
- Three test tiers (`audits/tests/tier.py 0|1|2`; see `audits/tests/TIERS.md`). Self-tests have a
  no-PDF mode, which a real run refuses. Mutants have a kind (plain, pdf, lean, codex). The doc-lint
  has its own script (`audits/tests/doclint.py`).
- `axiom_sweep.py --selftest` asks each negative control and main() for the sweep's own error message, not just a non-zero exit; its synthetic target lives in the system temp dir; the fallback shows the project's own sweep errors (mutants X7-X13).

### Documentation and release
- README, INSTALL and the other docs name the version only through `VERSION`. README says what to
  read: README, then INSTALL, then a run. It credits Trellis and states the licence of the parts
  adapted from it (new `NOTICE`; `CITATION.cff` lists both licences). The track record is updated.
- The deliverables of the test run on a public paper were removed from `examples/`. The raw Codex
  test evidence, the live Codex test harnesses and the Codex test report (`codex/SUBAGENTS_REPORT.md`)
  left the tree; they are kept privately. `codex/README.md` (History) summarizes the reference run.
- KNOWN_LIMITATIONS loses the items fixed since 0.2.0.
- The agent spawns lanes in waves of at most 8, fewer on less memory or on request, and waits
  for `signoff.py approve`, which can take many minutes.

### Removed
- The stall resolver (`resolve.py`, its prompt, the Codex role `formalize_resolver`,
  `codex_spawn.py --kind resolver`), lane supersede and seal generations, and the resolver caps.
  It was added and removed within 0.3.0-dev and never released.
- `check_index.py`, `prompt.py --missing`, `fingerprint.py --snapshot` and `--approve`.

## 0.2.0 (release date: the date of the v0.2.0 tag)

Two features, the fixes found by testing them, and the fixes from three independent pre-merge
reviews (protocol, code with adversarial tests, newcomer documentation).

- **Involvement levels.** An intake question (5c) chooses `involved` (the default), `statements-only`
  or `hands-off`. Delegated decisions are final and tagged `[DELEGATED …; reversal: …]` in
  `RUN_LOG.md`. They follow the adjudicator's recommendation, or else the most conservative choice
  that stays with the paper. The decisions document ("Decisions taken on your behalf"), the report
  and the sign-off sheet disclose the level, quote the intake answer and list every delegated
  decision. Some stops remain at every level.
- **Codex built-in reviewer subagents** (experimental). Reviewers run as fresh built-in Codex agents
  from roles that `audits/codex_agents.py` generates from the same reviewer body Claude uses.
  `codex_spawn.py` stays as a fallback that fails closed.
- **Lane attribution, Claude and Codex.** Each lane gets a spawn-only token, and the owning reviewer
  returns the digest of its verdict, which `lane_auth.py seal` commits. lanecheck and the
  adjudicator check tokens and seals.
- **Unattended runs in Claude Code.** The installer adds exact allow rules, edit rules for what the
  run writes, deny rules for the pinned apparatus, and `PYTHONDONTWRITEBYTECODE=1`. The protocol's
  own steps then ask for no permission. Helper drafts, scratch directories, the source compile and
  the delivery copy go through `project.py`, inside the project.
- `tree_state.py` records git hooks and command-running git config and flags any change. The
  installer refuses before writing anything. The optional Codex watchdog only notifies.
- Fixes: a docstring belongs to the declaration below it (a docstring-only change used to scope a
  neighbour). The report's open questions are cumulative across rounds. A question asked again
  after a delegated decision returns. Every xelatex call runs with `-no-shell-escape`.

## 0.1.0 (2026-10-18)

First public release. The protocol and scripts had been used on five papers before this release
(see README, "Track record").

- `install.sh` installs into any Lean project that requires Mathlib, or into a clone of Mathlib.
  `examples/sparse-note/` is a ready-to-build fixture.
- `readers.py --save` saves a fresh reader's record through the script, which checks and commits it.
- The project setting `work_dir` gives the proof helpers a persistent directory (never `/tmp`).
- The report gained sections for open questions and standing defers, an optional notation
  glossary, and the location of every cited Lean name.
- `selftest_all.py` works before the first project exists. `tests/mutants.py` checks that each
  self-test passes on the unmutated code before it judges the mutants. The axiom sweep's self-test
  runs a positive control first.
- Experimental Codex CLI support (`install.sh --codex`, `codex exec` per subagent).

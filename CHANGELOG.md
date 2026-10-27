# Changelog

## 0.2.0 (release date: the date of the v0.2.0 tag)

Two features merged (involvement levels; Codex built-in reviewers with lane attribution), the
fixes found by testing them, and the fixes from three independent pre-merge reviews (protocol,
code with adversarial tests, newcomer documentation).

### Pre-merge review fixes
- Every lane spawn is sealed where it happens: the `prompt.py 3` block, RUN.md Stage 2 step 3 and
  Stage 4 step 3 say to seal each lane from its own `LANE_COMPLETION` result, then run lanecheck.
- Adjudicators never spawn lanes; re-votes are the operator's (`--write`, token, seal), and
  `lane_auth.py` now accepts re-vote verdict paths at all.
- `lane_auth.py reissue`: a logged, refused-once-sealed reissue for a lane whose spawn line was
  lost with its conversation. Seal commits are serialised across processes and cleaned up on a
  failed commit.
- `watchdog.py` is NOTIFY-ONLY: it never types into the session (an adversarial test showed
  keystroke injection into a live TUI cannot be made safe; auto-resume is deferred). It pins one
  session log at startup (refusing none, several, a stale or a foreign one), decodes Codex's
  multi-chunk and truncated JSON tool output, reports "stalled" only for a service error with
  nothing else in the turn, and "needs a human: <reason>" for STOP/FAIL/RED, checker exits, usage
  or rate limits (429), approvals, errors and normal turn ends; terminal line, bell, log, and an
  optional `--notify-cmd` (no shell). Real reference-run events are fixtures; mutants WD1–WD25.
- `tree_state.py` records git hooks and command-running git config, for the project and the audit
  record, and flags any change as an integrity failure (a hook planted through a writable `.git`
  runs outside the sandbox).
- `install.sh` refuses before writing anything (no partial installs), adds a curated
  `permissions.allow` list for Claude Code's normal permission mode, and hardens the settings
  merge (symlinks, backups, read-only files, duplicate keys, NaN, comments). The Codex config edit
  refuses profile allowlists that drop the variable, keeps comments, writes atomically.
- A question asked again after a `[DELEGATED]` decision returns to the report. A `-- comment`
  between a docstring and its declaration no longer detaches it. `lanecheck.py` spares monitors
  tagged `FORMALIZE_PAPER_OPERATOR=1` and attributes loops started by lane processes.
- Documentation: Codex install and login, an "experimental in practice" box, permissions, a
  sample intake answer, an uninstall table of every path touched, and the overclaims the newcomer
  review found.

- Unattended hands-off runs in Claude Code: the protocol's own steps ask for no permission
  (copying deliverables outside the project, `rm` of a stray file and improvised commands still ask).
  The installer adds exact command rules, `Edit(…)` rules for exactly what the run writes, and
  deny rules for the pinned apparatus; the helpers' `work_dir` defaults to
  `.formalization-work/<name>` inside the project (git-excluded); Stage 1's checks, the source
  compile (shell escape off), the work_dir commits, subagents' scratch directories
  (`project.py --scratch`, inside the project) and the delivery copy (`--deliver`, into
  `deliverables/`) go through `project.py`. Readers run their scripts by relative path and git
  without `-C`. Every xelatex call runs with `-no-shell-escape`.
- tree_state fails closed when git cannot report config scopes; the watchdog strips control
  characters; a delegation on the day of a re-ask answers it.

### Integration notes (merging hands-off-mode and codex-subagents into 0.2.0)
- The hands-off merge had no conflicts. The codex-subagents merge conflicted in two places:
  `make_report.py`'s front matter (kept the level-dependent Checkpoint C sentence; the "answers
  recorded verbatim in RUN_LOG.md under ## Answered" clause applies only where the human decides)
  and `tests/mutant_list.py` (both appended blocks kept; ids unique, every pattern present once).
  Everything else merged textually, then RUN.md was reconciled: mechanical child failures are
  rule-7 re-runs, token/seal/lanecheck failures integrity stops at every level; seals apply at every
  level; Codex approval prompts are not checkpoints and delegated runs must not wait at them.
- Watchdog mutants were renamed WD* (W1 already named a project.py mutant).

### Features and earlier fixes

- **Involvement levels.** A new intake question (RUN.md, 5c) asks how involved the person wants to
  be after the intake: `involved` (the default, as before), `statements-only` (the person approves
  the statements at Checkpoint B; the agent decides everything after that) or `hands-off` (the
  agent also decides at Checkpoint B and finishes the run without asking). The answer is kept in
  the project configuration (`involvement`, validated, frozen at the pin like the other scope
  keys; `involvement_answer`, verbatim) and shown by `prompt.py --show` and at Checkpoint A.
- Delegated decisions are final, not provisional: they are tagged
  `[DELEGATED <date>, operator under <level> (intake); reversal: none | re-prove | re-approve | new round]`
  in `RUN_LOG.md` (any other spelling is refused), follow an adjudicator's written recommendation
  (never one the operator wrote itself) or else the most conservative choice that stays with the paper, and are
  not put to the person again. `[PROXY]` is unchanged for the involved level. RUN.md lists the
  stops that remain at every level (anything outward-facing not authorized at intake, integrity
  failures, a goal result that looks false as stated, an environment fault only the person can
  fix) and one narrow exception for clerical
  document-check failures the operator's own text caused.
- `decisions.py`: `[DELEGATED]` decisions are items to show, already decided. Under a delegating
  level the document is headed "Decisions taken on your behalf", quotes the intake answer, says who
  reviewed nothing, and every decision section has a sixth field, **Decision taken**, that must show
  its `[DELEGATED` tag; `--check` enforces this. Documents for the involved level are unchanged.
- `make_report.py`: the trust section and the page-1 box name the level, quote the intake answer,
  say that no human reviewed the statements (hands-off) or the later decisions, and count and list
  the delegated decisions. `[DELEGATED]` decisions under the involved level, or an unknown level,
  fail the report check.
- Review fixes: the canonical tag states the reversal cost and every other spelling is linted;
  a delegated `DECISIONS.md` opens with an "At a glance" table, its Recommendation names the
  adjudicator's recommendation or the conservative rule, and "Not applicable" is accepted only for
  what the human decided at Checkpoint B; delegated decisions are counted per anchor; `[PROXY]`
  under a delegating level and both tags on one line are refused; under `statements-only` an
  agent approval fails the report check; under `hands-off` `SIGNOFF.pdf` opens with "Approved by
  the formalizing agent; no person reviewed these statements (hands-off chosen at intake)."; a run
  pinned before the involvement keys accepts their explicit defaults. RUN.md: the involvement
  question comes before the approver question, names what still stops the run and that the choice
  cannot change; statements-only keeps every change to a human-approved statement as a stop;
  delegated re-approval never strengthens or generalizes; environment faults are first fixed by
  the agent and stop the run only when the fix needs the human.
- New self-tests and mutants (D109–D140, M97–M109, P61–P65, I27–I29, G53) for each of these checks.
- **Codex built-in reviewer subagents** (experimental): reviewers run as fresh built-in Codex
  agents (`fork_turns="none"`) from five roles generated by `audits/codex_agents.py` out of the
  same canonical reviewer body Claude uses; `integrity.py` pins the role files. `codex_spawn.py`
  stays as an explicit fallback and now fails closed on missing/stale finals and startup errors.
- **Lane attribution, Claude and Codex.** Each lane gets a random spawn-only token whose hash is
  committed (`.lane-auth/`); the owning reviewer returns the digest of its intended verdict bytes,
  and `lane_auth.py seal` commits that seal (`seal <R> <lane>`). `lanecheck.py` and the
  adjudicator's step 4 check tokens and seals. These apply at every involvement level.
- `lanecheck.py` flags or kills stray polling loops only when their cwd is inside the reviewed
  repository. Codex shells get `PYTHONDONTWRITEBYTECODE=1` from the installer.
- Integration: under Codex, sandbox command-approval prompts are not checkpoints and delegating
  levels must not wait at them; a mechanical child failure (crash, service/capacity error, no
  file) is a rule-7 re-run, while a token/seal/lanecheck failure is an integrity stop at every
  level; the parent waits for children with a long blocking `wait_agent` instead of short polls.
- `install.sh` sets `"env": {"PYTHONDONTWRITEBYTECODE": "1"}` in the project's
  `.claude/settings.json` (new `audits/claude_settings.py`: creates or merges, keeps every other
  key, backs up, refuses unparsable JSON before installing anything), so no command Claude Code
  runs in the project leaves bytecode in the apparatus. RUN.md Stage 1 checks the variable.
- `scope.py`: a docstring belongs to the declaration below it. A declaration's text used to run
  to the next declaration's header, so it swallowed the next docstring, and a docstring-only change
  scoped the neighbour above (sparse-note Codex run: Theorems 2.7/2.10 instead of Corollary 2.8 and
  Lemma 2.11). Regression self-tests; mutants S24, S25 (S21 re-pointed).
- `make_report.py`: the open-questions section is cumulative: every QUESTION row of every round
  whose item has no final answer, each with its round (it listed only the newest round's rows, so an
  earlier unanswered question could drop out). Questions answered under `## Answered` or decided
  as [DELEGATED] stay out; a [PROXY] answer keeps the row, marked provisional; a question asked
  again after its answer comes back. Shared logic in `decisions.open_question_rows`. Mutants
  M112–M116 (D43, RA2 re-pointed).
- `audits/watchdog.py` (Codex, optional): see above (notify-only).
- Codex git approvals (F9): starting the session with `--add-dir <project>/.git` lets the author
  commit without an approval prompt (tested on 0.163.0; a project config is not loaded while the
  project is untrusted). `install.sh --codex` prints the command; `codex/README.md` says what it
  allows.

## 0.1.0 (2026-10-18)

First public release. The protocol and scripts had been used on five papers before this release
(see README, "Track record"). New in the release:

- `install.sh` installs into any Lean project that requires Mathlib, or into a clone of Mathlib,
  with no hard-coded paths. `examples/sparse-note/` is a ready-to-build fixture with `setup.sh`.
- `readers.py --save`: a fresh reader saves its record through the script, from stdin. The script
  checks the record's format and its sha256 line, commits that one file, and checks that the commit
  matches the input byte for byte. Readers no longer need a file-writing tool.
- Project setting `work_dir`: a persistent directory for the proof helpers' drafts. A path under
  `/tmp` or the system's temporary directory is a hard configuration error.
- The report renders the free text recorded below each record's table. It has new sections for open
  QUESTION rows and standing defers, for an optional notation glossary (`glossary` in the project
  configuration), and for the location of every cited Lean name. Its PDF entries are numbered like
  their rows.
- `selftest_all.py` works before the first project exists, and reports the tests it skipped.
  `tests/mutants.py` takes `--project`, refuses unknown options, and fails when no mutant ran. It
  also checks that each self-test passes on the unmutated code before judging its mutants.
- The axiom sweep's self-test runs a positive control first. On a project whose proofs are still
  `sorry` (the statement phase) its negative controls run on a small synthetic clean target; before
  this, every control went red whatever the sweep did, and four mutants of the sweep survived.
- Experimental Codex CLI support: `install.sh --codex` and `audits/codex_spawn.py`, which runs
  each subagent as a separate `codex exec` process.

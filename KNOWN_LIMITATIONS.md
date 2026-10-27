# Known limitations

These are known problems with formalize-paper 0.2.0, found in real runs and reviews, with the
change we expect to make for each. None is known to have produced a wrong result in the runs so
far; most cost the operator time or attention. The
protocol's own list of what it cannot check is in `audits/AUDIT_PROTOCOL.md`, section "What this
protocol does not cover".

## Tooling

- **Codex capacity failures stop the parent turn, and only a person can resume it.** Automatic
  resume is deferred: keystroke injection into a live TUI cannot be made safe (an adversarial
  test found 22 failing scenarios: approval overlays, drafts, re-wrapped screens, misread logs).
  `audits/watchdog.py` (optional) only notifies the person, from the pinned session log; a future
  version may resume through Codex's app-server API.
- **Document-generator limitations remain after reader checks.** The signoff sheet lacks
  per-row source/Lean locations, a self-contained workflow glossary, and neighboring compile
  evidence. The report PDF can drop the empty skipped-results status sentence. The full test
  delivered explicit KNOWN_FAULTS notices under the reader-fix budget. Fix the generators in a
  new tooling version; do not modify a pinned run to hide the limitations.
- **Lane authentication protects final verdict bytes, not every transient write.** The original
  same-round sibling-overwrite gap is now covered by spawn-token commitments and owner-returned
  completion digests/seals, with a passing four-case parallel live gate. Tokens are not secret:
  they become visible in verdicts, and a sibling could read them from the parent's transcript;
  only the originating child's returned digest may establish its seal. A pre-planted seal makes
  the round STOP loudly (a denial of service, not a forgery). A write
  restored before observation remains undetectable, and probe contents are not covered by the
  verdict's SHA-256. A hostile process that forges history is outside the existing threat model.
  The Codex test evidence is kept privately.
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
  (logged, refused once sealed; RUN.md, "Resuming a half-finished round"). A reissue is the
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
- **Codex sandbox git approvals (F9).** The project's `.git` is protected in workspace-write mode,
  so branch changes and commits ask for approval unless the session starts with
  `--add-dir <project>/.git` (tested on 0.163.0; printed by `install.sh --codex`). With it,
  reviewers (who inherit the sandbox) can also write the project's git metadata, including
  `.git/hooks` and `.git/config`, and a planted hook would run outside the sandbox at the next git
  command. `tree_state.py` records hooks and the repository config (local, worktree, included
  files) at Phase 0 and flags any change (and a moved `HEAD`) as an integrity failure; that is
  detection, not prevention, and it covers the project's and the audit record's repositories only,
  not other nested ones such as `.lake/packages/*/.git`. A project `.codex/config.toml` setting is not
  loaded until the project is trusted, so the installer does not rely on one.
- **Nested Codex fallback sandbox failure (F3/F4).** On 0.163.0, a reviewer launched with
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
  memory on a 16–32 GB machine. *Workaround:* spawn lanes in waves of 6–8. *Planned:* a project
  setting `max_parallel_lanes`, so that `prompt.py` prints the spawn order in waves; a shared Lean
  server for the lanes.
- **Diff rounds never clear some UNCOVERED rows.** If a verdict was recorded on a helper that has
  since been deleted, or on an auto-generated syntax declaration from a `macro` or `syntax`, the
  row stays UNCOVERED. *Planned:* `audit_coverage.py` retires a pass on a deleted declaration as
  "deleted at <commit>", and `scope.py` skips auto-generated syntax declarations.
- **Formulas can render badly in the PDF report.** Subscripts, superscripts, `|…|` and raw LaTeX
  that are written as plain text in a record can reach the PDF as literal characters.
  *Workaround:* write formulas as `$…$` in the records.
- **The report can miss a removed helper's name.** It fails on a cited name of the project's own
  form (`thm_1_2`, `lemma_3_4`, …) that no longer exists. A free-form helper name cited without its
  namespace can slip through. *Planned:* check every backticked identifier in every section.
- **Phase 0 regenerates the report on every run.** Counters such as "re-pinned N times" change the
  report's text, which then needs another fresh-reader pass. *Planned:* regenerate the report only
  in Stage 5.
- **Hand-typed round names are accepted.** `scope.py --round` accepts a name whose commit hash
  does not resolve to HEAD, and later scripts then cannot find the round's commit.
  *Workaround:* use the name `prompt.py 3` prints. *Planned:* refuse a mismatching name.
- **Line numbers drift.** Each docstring edit shifts the `File.lean:N` citations in hand-written
  documents. The report locates every cited Lean name at its current line (section "Where the Lean
  names are"). *Planned:* records cite names only, and the generator inserts the lines.
- **Paper line citations drift too.** A `tex l.N` citation paired with a quote can be off by a few
  lines. *Planned:* check that the quote appears within ±1 line of N.

## Protocol

- **The adjudicator's commit can pick up the operator's uncommitted files.** *Planned:* each step
  commits only the paths it owns.
- **Answers given outside `DECISIONS.md` come back as open questions.** *Workaround:* record every
  checkpoint answer in the `## Answered` format.
- **Docstring-only changes trigger a large round.** *Planned:* when every fingerprint is unchanged,
  send only the correspondence lane, on the changed declarations.
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
- **The decisions document is long.** *Planned:* a one-page "what you are deciding" summary at the
  top.
- **The involvement levels are enforced partly by text.** Under `statements-only` and `hands-off`,
  what the operator may decide alone is set by RUN.md; the scripts check the record it leaves
  (tags, the decisions document, the report's disclosure, the approval), not every rule. For
  example, that a delegated statement change was logged before the Lean edit, or that a
  "conservative rule" decision really is the conservative option, is not checked mechanically.
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

# Stage 3 — proofs

Read this after the approval commit. It ends when nothing in scope is `sorry` (except a non-goal
result left unproved by a logged [DELEGATED] decision, below) and Phase 0 is GREEN;
then run `python3 audits/project.py --stage "Stage 4 — audit rounds"` and read `stage4-rounds.md`.

Drafts made in `work_dir` during Stage 2 may be merged now; what you may claim about the order of
work is in `stage2-statements.md`, step 3.

Prove the results. Habits that pay:

- **State, refute, then prove.** Try to refute a statement before proving it.
- **Decompose, then check the assembly before proving the parts:** state the pieces as hypotheses
  and derive the target; if that derivation carries no hole of its own, invest in the pieces.
- **Justify every hypothesis you add.** If you cannot say what breaks without it, delete it and see
  whether the proof still compiles. Instantiate every new definition at a concrete witness before
  building on it.
- **Commit before writing any prose that cites the commit.**
- **Route changes.** Whenever a Lean proof does not follow the paper's argument (a different lemma
  or case split, a weaker intermediate step, a paper step that fails and had to be repaired), record
  it *when you make the change*, under "Route changes" in `AUTHOR_NOTES.md`, as a row `# | result |
  the paper's route | the Lean route | why different | kind`, kind one of `same strength` / `paper
  step fails` / `Lean intermediate weaker`. The next adjudicator checks it against the Lean and
  writes the `DEVIATIONS.md` row (that file is the adjudicator's, `integrity.py` OWNERS); only the
  adjudicator writes a `reading choice` row (it settles an Ambiguous verdict) or a `differs` row (after
  an F10 finding), since those set a result's status in the summary. A line you add under "Route
  changes" after the last adjudication (a Stage 5 fix, say) must reach one before delivery:
  `--deliver` refuses it (`RED[adj-record]`, pending the next adjudication) until a round's
  adjudicator has seen it -- a diff round, or a full round when `scope.py` exits 3 with
  `NEXT[full-round]`. In a run pinned before
  ownership 3 (`TOOLING_PIN.json` `"ownership"` 1 or 2) you write the `DEVIATIONS.md` row yourself, as
  before, but never a `reading choice` or `differs` row. The lanes compare statements, not proofs: a
  route change nobody recorded is invisible.
- **Suspicions and skips.** Your suspicions about the paper, results you propose not to
  formalize and why, and route changes you think matter go in `AUTHOR_NOTES.md` under those three
  headings. The adjudicator verifies them; you never write `PAPER_DEFECTS.md` or `SKIPPED.md`. A
  result that needs theory no configured library has is not yours to skip, narrow or hypothesise
  away: follow RUN.md's missing-theory rule (involved: stop and ask, as in `stage2-statements.md`
  step 6).
- **No standing `sorry` for a skipped result.** Delete the statement (which needs re-approval if
  it was approved), or take the result as a named hypothesis. Under a delegating level you never
  delete or weaken a result yourself, except missing theory as a named hypothesis (RUN.md,
  "Missing theory": built if only definitions and easy lemmas are missing, else assumed as a named
  hypothesis with its canonical line; a goal result too, never a stop).
- **A non-goal result you cannot prove, under a delegating level.** After a serious attempt (and
  the escalation check below), leave it unproved: its statement stays byte-identical, ending in
  `sorry`. Log `[DELEGATED <date>, operator under <level> (intake); reversal: re-prove] leave
  <decl> unproved — <reason>` with the full Lean name, as a line of its own under `## Open
  questions` (`project.py --log "Open questions"`; only a top-level line of Open questions,
  Checkpoint C or Answered that begins with the tag, after at most its anchor, counts: a quote
  elsewhere is not a decision), once for it and once for every result whose
  proof uses it (the axiom sweep stays RED until each has its line); propose each in
  `AUTHOR_NOTES.md` under results not to formalize; make each index cell "`<decl>` (stated, not
  proved: not formalized)"; commit, then run Phase 0, which reads the committed `RUN_LOG.md` and
  reports that `sorry` as `NOTE[unproved]`. While any such line is active, a project metaprogram (`elab`, `macro`, an
  elaborator attribute, `addDecl`/`addAndCompile`) is `RED[unproved-meta]`: remove it. The next round adjudicated after the commit that
  first logged the declaration (an `ADOPTED.md` in that same commit does not count; rewording the
  line changes nothing) records each in `SKIPPED.md`; the report and `DECISIONS.md` disclose it as "stated, not proved". Never a goal
  result (a stop: Phase 0 refuses it as `RED[unproved-goal]`), never missing theory. Under
  `involved` the human decides.
- **Approved statements are frozen.** A change follows RUN.md, "Statement changes after
  approval", and `reapproval.md`, begun before the edit.

**Helpers.** For a long paper you may spawn author-side helper subagents (general-purpose; Codex: `formalize_helper`) to write
proofs in parallel, on separate files. They work FOR the author and are bound by every rule exactly
as you are; they are never used as reviewers, and nothing they write is a review.

**Proof helpers (how this was done for a 55-result paper).** One author-side helper per statement
file, working on a COPY of that file in the run's `work_dir` (never under `/tmp`: a reboot once
wiped a dozen files of proofs kept there). `work_dir` is a git repository of its own; each helper
commits its file as soon as it compiles, and at least every hour, with
`python3 audits/project.py --work-commit "<message>" <file>` (one commit at a time across helpers;
a plain `git -C <work_dir> commit` would ask for permission). The copy imports the BUILT modules, so it compiles
on its own (`lake env lean <copy>`) without touching the repository or running `lake build`, and
merging back is replacing the file. Give every helper the brief `python3 audits/prompt.py --prompt
formalizer` prints (a refutation's name among its rules), then the same written assignment: statements and
definitions frozen (only `sorry` bodies change), auxiliary lemmas in a sub-namespace per file, no
`native_decide`/`admit`/`axiom`, route changes as rows for `AUTHOR_NOTES.md` "Route changes" (columns
and kinds as above), a BLOCKED file for statements that look false (never weaken one), and a short
PROGRESS file kept current (the only way to see a long helper's progress). Before merging, check
that the diff removes only `sorry`s, then run the freeze check.

**Shared lemmas, sweeps and witnesses.**
- `<Name>/Common.lean` and `<Name>/Examples.lean` exist since Stage 1. `Common.lean` holds facts
  more than one file needs (basic facts about a shared definition, order embeddings, ...).
- `Common.lean` is the one file a helper may ADD to (never edit): each helper appends its shared
  lemmas to its scratch copy of it, and at merge you concatenate the additions, then check that
  the diff removes only `sorry`s plus pure additions to `Common.lean`. Nothing a statement's
  meaning uses goes there; definitions stay before the statements that use them.
- After each merge and after each implementation step, run `python3 audits/unused_args.py
  --write` (Phase 0 also does) and check its header names the current commit. Then, for each
  HELPER it lists: drop the argument (updating callers) or the dead lemma, then run
  `phase0.py --statements`; if the freeze check reports drift, the "helper" was a definition an
  approved statement uses: revert, and leave it to the adjudicator. Never act on the "Approved
  statements" section. Idle `[NeZero k]` arguments were reported in every round of a test run until
  this was done.
- Whoever implements adopted rows lists, in the commit message, every change beyond those rows,
  and backs every "this hypothesis can be dropped" claim with a compiled probe (a file that
  builds without it), cited by path. (This is checked by judgement, not by a script.)
- Keep a few named witnesses in the library (`<Name>/Examples.lean`): a concrete object for each
  central definition, one per interesting case (the paper's figures are good candidates). Lanes
  otherwise rebuild the same examples every round.

**File order and size.**
- Every definition and context `structure` must come before the first statement whose PROOF uses
  it, not only its statement. Otherwise helpers copy definitions to get at them, and those copies
  are duplicate declarations. In a test run they copied 18 definitions and re-declared a
  hypothesis structure.
- Keep each Lean file under about 2,000 lines. Put long proof developments in their own modules,
  imported by the statement file. A single file of 8,000 lines took 6–9 minutes and several GB to
  elaborate, and on an 11 GB machine the verification build was killed for low memory. If a
  build runs out of memory, split the file first (a pure move: the freeze check confirms that no
  statement changed), then retry.
- Machine: 16 GB RAM is the minimum for a paper of this size (run at most three Lean processes
  at once); 32 GB is comfortable.

**Ask the human mid-stage only when blocked** (a QUESTION, never a wait: the run goes on with the rest of the
work; in `release` only the four stops of RUN.md's "Stops that remain at every level" stop the run):

- a frozen statement must change;
- a goal result looks unprovable after a serious attempt;
- the work needs something the intake ruled out.

Under a delegating level, work the intake ruled out is not done (the conservative choice), logged
[DELEGATED]. A frozen statement that must change: RUN.md, "Statement changes after approval". A
goal result that looks false or unprovable as stated is a stop at every level.

First spawn the escalation check (general-purpose; under Codex the role `formalize_escalation`):
`python3 audits/prompt.py --prompt escalate --question "<the question, no argument for either
answer>" --decl <the declaration> [--passage "tex l.N-M"] --write` writes and commits its prompt
(`escalations/E<n>.prompt.txt`) and prints the line to spawn it with; nothing else reaches it. When
it returns, save its final message verbatim with a quoted heredoc (the quotes around `RETURNED` stop
the shell expanding the backticks and `$` the message holds; never pass it as `--returned "..."`):

```
cat > .escalation-E<n>.returned <<'RETURNED'
<its final message, pasted exactly as returned>
RETURNED
python3 audits/lanecheck.py --escalation E<n> --agent-id <its id> --returned-file .escalation-E<n>.returned
```

(Codex: the child's thread id is the agent id.) It checks the prompt against its recorded hash and
the answer file against the line the child returned, and commits the answer. Never write or commit
an answer yourself, and never re-ask a NEEDS-HUMAN question in other words: the report lists every
escalation, and under `involved` a later escalation on a declaration whose earlier one was answered
NEEDS-HUMAN or has no accepted answer is a re-ask, whatever its wording, and is refused (the question
stays the human's). A refused escalation is no stop and its answer counts for
nothing: write a new one. Ask the human only if the accepted answer is NEEDS-HUMAN; an accepted
ANSWERABLE is a written recommendation (cite it as "escalation E<n>").
Collect everything else under "Open questions" in `RUN_LOG.md`.

Commit at milestones. When nothing in scope is `sorry` (results left unproved as above aside), commit, then run `python3 audits/phase0.py`;
it must say GREEN, freeze check included. A RED row is handled as RUN.md's failure table says (your
own build, sorry or index rows are work; freeze, tree and integrity rows are stops: in `dev` the
human's, in `release` self-cures, `open`, the printed cure, `close --cured`).

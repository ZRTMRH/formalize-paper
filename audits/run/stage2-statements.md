# Stage 2 — statements first, then Checkpoint B

Read this after the pin (Stage 1 step 5). It ends with the approval commit (`approve <R>`); then run
`python3 audits/project.py --stage "Stage 3 — proofs"` and read `stage3-proofs.md`. Read
`spawn-and-seal.md` before the first spawn (step 3) and `fresh-reader.md` before step 7.

1. **Write the statements.** Formalize every in-scope definition and the **statement** of every
   in-scope result, each proof `sorry`.
   - Author-side helper subagents may draft statements in parallel, on separate files; they are
     bound by every rule as you are and are never reviewers. Spawn each (general-purpose; Codex: `agent_type`
     `formalize_helper`, `fork_turns` none) with the
     brief `python3 audits/prompt.py --prompt formalizer` prints, followed by its assignment. Put every shared definition in one
     base file before drafting in parallel, and when merging drafts check that two definitions of
     the same notion are equivalent before keeping one.
   - Literature hypotheses are named `Prop`s or `structure`s taken as explicit arguments, never
     `axiom`s. Before assuming one, spend a few minutes on "can we just prove it?": a lane once
     proved a cited result in 141 lines. A literature hypothesis that is later proved stays an
     argument of the approved statement (the set is fixed at Checkpoint A; it is never retired,
     and you never re-pin for it). Land the proof as a pure addition, at every level and without a
     question: a theorem `<decl>_unconditional` stating `<decl>`'s conclusion without that
     hypothesis, proved by applying `<decl>` to the proof of the hypothesis, its docstring saying
     so, listed in `<decl>`'s index cell beside it. The next round audits it like any new
     declaration (correspondence included).
   - **Test every definition before the statement round,** against the paper's own examples and
     against degenerate cases: empty matrix or set, zero rows or columns, the smallest lengths and
     sizes, `k = 0`, `sInf ∅`, truncated `ℕ` subtraction. Keep each test as an `example`. Most
     statement defects are definitional, and they show up exactly there.
   - **Reading choices and paper defects need evidence in the library.** When a definition departs
     from the paper's literal text because the literal text is wrong, commit the counterexample
     as a named `theorem`/`example` and cite it in the docstring and in `AUTHOR_NOTES.md`. Scratch
     files are invisible to auditors, and the adjudicator will not record a paper defect whose
     witness is not in the library.
   - **A result false as printed:** its refutation is named `not_<decl>_as_printed`, `<decl>` the
     declaration of the result (the corrected statement): `theorem not_<decl>_as_printed : ¬ <the
     statement as printed>`, or `¬ <decl>_as_printed` over a `def <decl>_as_printed : Prop` (the
     form `signoff.py reapprove --refuted-by` needs). It is the only name the checks read: the
     round schedules the lane's F10 item by it, and the defect row is recorded by it. Any other name
     for a theorem refuting a printed statement (`<decl>_as_printed_false`, `<decl>_false`,
     `..._counterexample`) is refused by Phase 0's index check and by `scope.py`, with the rename.
   - **Restatements** (a result printed again with a new number): every printed number gets its
     own index row; the restatement's row names the original declaration, "(restatement of …)".
     Do not add wrapper declarations.
   - **Standing hypotheses of a section** ("for the rest of this section fix …"): bundle them in
     one `structure` and take it as a hypothesis of each statement. If the section is a **proof by
     contradiction** (it fixes an object that a later lemma says cannot exist), say so in the
     section docstring, name the lemma it refutes, and keep the paper's numbered lemmas as they
     are; their hypotheses are unsatisfiable by design, and the non-vacuity lane is told to check
     the bundle minus the refuted field.
   - **Claims outside numbered environments** (figures, introduction, conclusion, unnumbered
     claims that a proof relies on) are out of scope unless the intake said otherwise; list them
     in `AUTHOR_NOTES.md` "proposed as out of scope" so the adjudicator records the exclusion.
   - When merging helpers' drafts, re-read every docstring afterwards: text written against a
     local definition that no longer exists goes stale silently.
   - Fill the index.
   - State each result, then try to refute it before going on: a wrong statement killed by a
     five-line check costs minutes; found three days into a proof, it costs the three days.

   Commit, then run `python3 audits/phase0.py --statements`. It must say GREEN; the sorry scan and
   the axiom sweep are waived. The assumption walk is not: Phase 0 writes `DEPENDENCIES.json` (what
   each result's statement assumes) in statement rounds too, and a hypothesis it lists is
   `PENDING[adj-record]` until the round's adjudicator writes its `## Hypotheses` row. A hypothesis it
   lists that nothing classifies -- a project definition used in a statement's hypothesis with no index
   `Definition` row (a notation of the paper's, such as 𝒢(n) in `hx : x ∈ G n`), not a declared literature
   hypothesis, with no missing-theory line -- refuses the statement round (`scope.py --statements`,
   `FAIL[index]`) and the approval: otherwise those results end "not established: unclassified
   assumption" and the cure changes the approved sheet. `scope.py --statements` judges this on a walk of
   the Lean at HEAD only: a missing or stale `DEPENDENCIES.json` refuses the round (`FAIL[index]`) until
   Phase 0 has rewritten it. Take the route that is right: a notion of the
   paper gets its index row `| Definition (<what>, tex l.<N>) | `<name>` |` (commit, Phase 0 again; the
   round's lanes review it); a missing-theory hypothesis gets its line (step 6, asked now); a hypothesis
   the paper does not make is removed. The approval
   (step 8) records the walk's binders from that file when it is current, so the report can list the
   hypotheses added since the approval.
2. **Scope.** Run `python3 audits/prompt.py 3 --statements`: its block names the round `<R>`
   (`<DATE>-full-<HASH>`) and scopes it with `scope.py --statements`; this step and step 3 carry
   out that block. Run:
   ```
   python3 audits/scope.py --statements --round <R>
   python3 audits/signoff.py bundle --round <R>
   ```
   Each commits exactly the files it wrote, by name (`scope <R>`, `scope <R> (statements bundle)`).
   If `bundle` reports a PROBLEM (an index name that does not resolve, a definition whose source
   is missing), it writes no bundle, and this round is given up before its review: set it aside, `python3 audits/stops.py
   set-aside <R> --reason "bundle PROBLEM: <what it said>"` (a set-aside round counts toward no
   round cap). Fix the index (commit it), or add the missing file to `lean_files` (an entry is only
   ever added: `integrity.py` refuses one removed after the pin), then start this step again with
   the new round `prompt.py 3 --statements` names. A fix to the config alone leaves the Lean HEAD,
   and so the round's name, unchanged: `scope.py` then refuses the taken name and prints the
   empty Lean commit that gives a new one (`stops-and-set-asides.md`, item 4).
3. **Review.** Write the prompts: `python3 audits/prompt.py --lanes --round <R> --batch 60 --write`
   and `python3 audits/prompt.py --prompt informalizer --round <R> --write`. In ONE message, spawn
   every lane (type `auditor`) and the informalizer (general-purpose), each with exactly its printed
   line (for a lane: everything after "with:", its lane token included; `spawn-and-seal.md`).
   **As each lane returns,
   seal it** from that child's own result (`python3 audits/lane_auth.py seal --verdict <verdict>
   --sha256 <sha256> --agent-id <agentId>`, values from its `LANE_COMPLETION` line and its result;
   it commits `seal <R> <lane>`). When all lanes are sealed, run `python3 audits/lanecheck.py
   --round <R> --kill`; its lines are handled as RUN.md's failure table says. When the informalizer
   returns, commit its file: `python3 audits/signoff.py save-informal --round <R>` (`signoff <R>`).
   Then write and spawn the sign-off writer the same way (`--prompt signoff-writer --round <R>
   --write`), and when it returns commit its file: `python3 audits/signoff.py save-signoff --round <R>`.

   **While these run you may draft proofs** in `work_dir` (Stage 3 says how). Merge nothing into
   the project until the approval is committed (step 8). What the record can show is limited to
   fingerprints: the approved statements are the committed, reviewed ones, unchanged since the
   approval's commit (the freeze check), and the report lists every statement that changed between
   the first statement round and the approval -- it cannot show that a revision made after
   drafting began was not shaped by a draft. So never write in any document that the statements
   were approved "before any proof was written": write what the record shows (the statements'
   commit and time, the approval's commit and time, and that the freeze check shows them unchanged
   since); `decisions.py --check` refuses the unverifiable sentence.
4. **Adjudicate.** `python3 audits/prompt.py 4 --round <R> --write`, and spawn the adjudicator
   (general-purpose) with the printed sentence. Its block runs `phase0.py --readonly --statements`.
   A later `FAIL[dead-witness]` or `FAIL[record-cite]` in its records is cured by a record
   correction, not a new round (RUN.md failure table, record-fix).
5. **Implement.** Run `python3 audits/prompt.py 5 --round <R>` and do what it says, using
   `phase0.py --statements`. A declaration a new `VACUOUS.md` row names gets a docstring sentence
   saying it is true only vacuously and why (Phase 0 checks the word "vacuous"; a docstring is not a
   statement change). Decide the round's QUESTION rows that shape statements first (ask the
   human; record the answers in `RUN_LOG.md` "Open questions"; under `hands-off`, decide them
   yourself as delegated decisions, one line per QUESTION row naming its item and round:
   `- [DELEGATED …] <decision> (QUESTION row on <item>, round <R>) — <reason>`; the line starts
   with the canonical tag, `<item>` is the row's item exactly and `<R>` the round's full name: only
   this form under "Open questions" counts as the answer, and under `involved` or `statements-only`
   no line of yours answers a Checkpoint B question), so the next statement round sees them implemented. **If any statement or definition changed,** the sheet no longer
   describes the Lean: commit, and go back to step 2 with a new round. At most 4 statement rounds
   run before the first approval (2 for each re-approval): `scope.py --statements` refuses one more.
   One exception, never a stop: when `signoff.py approve` refuses the last round at the cap for a
   mechanical reason (a statement blocker, or a stale bundle while the Lean is unchanged since the
   round: the printer changed), it records a grace round (`round-caps/grace/<R>.json`, "round-cap <R>
   grace", listed in `RUN_RECORD.md`), and one more statement round is allowed. A stale bundle because
   you changed a statement after the round is no grace: restore the round's Lean (the refusal prints
   the command) and approve that sheet.
   `NOTE[round-cap]` (no faithfulness finding open in the last round): no stop; prepare the last
   round's sheet as it stands, implement no ADOPT row that would change a statement, and record each
   such row as a decision taken at the cap, as the message says. A correspondence or
   paper-faithfulness finding still open at the cap: in `dev` mode `PROBLEM[round-cap]`, a stop at
   every level (`stops.py open --note "<what>" --cause round-cap`, and the human decides). In
   `release` mode it is no stop of its own: `scope.py` prints `NOTE[round-cap]` and records the open
   findings (`round-caps/<round>.json`, committed "round-cap <round>"), and you judge each
   finding's cause, taking exactly one route: (a) the paper's meaning is genuinely ambiguous on a
   point that matters and the reviewers cannot converge on one reading -- stop 4, at every level,
   `hands-off` included: `stops.py open --note "<the passage; the possible readings; what each
   would mean for the formalization>" --cause ambiguity`, show the human exactly that, `close
   --human "<their answer, verbatim>"`, and go on at the run's own level; (b) a loose or
   inconsistent convention that is no real misunderstanding (say, ℕ from 0 or from 1): take the
   intended reading, record it as a reading choice ("Route changes" in `AUTHOR_NOTES.md`, and a
   `[DELEGATED …]` -- under `involved` a `[PROXY …]` -- line under "Open questions"), and go on;
   (c) anything else: go on with the last round's sheet as it stands; each result the finding
   concerns reads "not established: open faithfulness finding" on the summary's first page, and the
   report says why.
6. **Missing theory.** Never decide a library gap yourself -- not by skipping, not by **narrowing**
   (stating the result for fewer objects than the paper does: graphs only where the paper says
   graphs or graphons), not by weakening, not by a named hypothesis, not as a "reading choice".
   Before Checkpoint B, list every result whose formalization needs
   definitions or theorems that none of the configured libraries (`libraries`; Mathlib, and Tau
   Ceti by default) provides. Search each library by name and by content (`grep -rn` over a
   checkout; record the commands). Name what is really missing: not only the definitions but the
   theorems the proof needs beyond them (for a graphon version of a graph statement, the theorem
   that graphs approximate graphons in homomorphism density). These results are **the human's
   decision, never yours or an adjudicator's.** Put each in the Checkpoint B message itself, not
   only in the sheet:

   > **<result>** needs <what is missing>. Searched: <libraries and how>. To build and test it
   > here: about <size> of new Lean, <agent time>, <usage>, plus one extra audit round.
   > **(1)** build it from scratch; **(2)** take <the missing theorem> as a named hypothesis;
   > **(3)** do not formalize this result (it is listed as not formalized, with this reason).

   Record the answer verbatim in `RUN_LOG.md`, under `## Checkpoint B` (or `## Answered`), as
   `- human answer (<date>; `<result>`): "<their words>"`, and commit it. If such a gap appears later (Stage 3 or an audit
   round), stop and ask the same question before going on (under a delegating level: below). A skip of this kind never enters
   `SKIPPED.md` without the human's recorded answer, and its "how this was checked" cell names
   every library searched. This step comes before the sign-off sheet (step 7): if the human chooses
   to build the theory, the statements change and a new sheet and round follow, so ask as soon as
   the list is ready, or at the latest in the Checkpoint B message. A hypothesis `H` already in a
   statement is asked before its statement round: `scope.py --statements` refuses the round while
   nothing classifies `H` (step 1).

   **Under a delegating level** follow RUN.md's missing-theory rule ("Involvement levels"): search
   and estimate as above, build the theory (option (1)) if only definitions and easy lemmas are
   missing, else take option **(2)**: `H` a project Prop definition saying exactly what the paper
   invokes, a binder of the result's statement; log the canonical line (`[DELEGATED …] missing
   theory: assume `<H>` for `<result>` — searched: …; estimate: …; paper: "<the passage>"`, or
   `… missing theory: build <what> for `<result>` — searched: …; estimate: …`). Never (3), never a
   stop. Under `involved` (and `statements-only` before the Checkpoint B answer), after the human's
   recorded answer, record what was done as `- missing theory (human <date>): …` with the same fields
   and the answer's date; for option (3): `- missing theory (human <date>): do not formalize
   `<result>` — searched: …; estimate: …` (`FAIL[missing-theory]` checks the line and its answer).
   `H` never restates a result the project states or a library proves: prove that instead.
7. **Prepare the sheet.** Run `python3 audits/signoff.py check --round <R>`. It must report 0
   problems (among them: every qualified Lean name the sheet's text cites exists, resolved in Lean);
   if not, rerun the sign-off writer (a mechanical failure), never edit its JSON. Then
   run `python3 audits/signoff.py render --round <R>`, which writes `SIGNOFF.md` (the paper's
   statements as their LaTeX source; its PDF is made later by agents). Literal LaTeX in a free-text
   field is cured by an `AUTHOR_NOTES.md` line telling the writer to put the formula in Unicode
   (⌊x⌋, ≡, ≤) or `$…$`, then a writer rerun. Then run the **fresh-reader check** on the sheet (`fresh-reader.md`;
   `prompt.py --prompt fresh-reader --doc signoff --round <R> --write`). Never edit the sheet. Fix a
   blocking finding
   in one of these ways:
   - through `AUTHOR_NOTES.md`, which the sign-off writer reads; then rerun the writer;
   - through the generator `signoff.py`: in `release` a tool patch (RUN.md "Tool patches": diagnosed,
     reviewed by a fresh agent, applied and re-pinned by `tool_patch.py`), in `dev` a stop for the
     maintainer; then render again;
   - if the Lean must change, commit it and go back to step 2 with a new round (it is a new sheet).

   A writer rerun is committed by `signoff.py save-signoff --round <R> --reason "<why>"` (subject
   `signoff <R> (sheet re-written: <why>)`), and logged under "Mechanical failures" with its reason. Then run the gate:
   `python3 audits/readers.py --doc signoff --round <R> --check`. It must pass before the sheet is
   rendered. Then **render the sheet** (`render-pdf.md`): `python3 audits/render_record.py next
   --doc SIGNOFF --round <R>`, and follow it to the end. A renderer makes the PDF, a verifier checks
   it, and two independent checkers judge whether it says mathematically the same thing as
   `SIGNOFF.md`, in at most 6 rounds; the run never stops on it. Only then ask the Checkpoint B
   question. If the sheet changes after this (a writer rerun, a new round), render it again and ask
   again: `approve --by human` refuses a PDF that is not the one rendered from the sheet as it is now.
8. **Checkpoint B.** (Under `hands-off`, do not ask: see "Under `hands-off`" at the end of this
   step.) Ask the approver, in the terminal, exactly this question (fill in the
   counts and the path), and wait for the answer:

   > The Lean statements are ready for your sign-off: `<path to SIGNOFF.pdf>` (its markdown,
   > `SIGNOFF.md`, is beside it and is the authoritative text). It has <N> results:
   > <o> match the paper; <g> differ from it only through a convention stated once at the top of the
   > sheet (G1, G2, …); <c> are marked CHECK because they differ in a way you should look at. There are
   > also <q> open questions only you can decide, listed below. How do you want to approve?
   > **(a)** I will read the sheet and approve all of it.
   > **(b)** I will read the sheet and list the results (or conventions G1, G2, …) I reject. A
   > rejected result is not approved: the report lists it as excluded, and its statement can be
   > revised and put to you again.
   > **(c)** Let the agent approve everything on the sheet without my reading it. The report will
   > then say that no human reviewed the statements.

   Under the question, list every QUESTION row from `ADOPTED.md`, each with enough context to
   decide (read only the section "Documents a human reads" of AUDIT_PROTOCOL.md). Write that list to
   `<rounds dir>/QUESTIONS-B-<R>.md` first, run the fresh-reader check on it (`--doc questions
   --round <R>`), and gate it, before asking. Right before asking, run `python3 audits/render_record.py
   shown --doc SIGNOFF --round <R>`: it records the PDF you show (`approve --by human` refuses any
   other) and prints the sheet's render outcome lines; print them verbatim above the question (a least bad PDF's
   remaining objections, every checker finding, the renderer's NOTE lines), any
   `KNOWN_FAULTS-signoff-<R>.md` and `KNOWN_FAULTS-questions-<R>.md` notice, every
   `fixed:`/`dismissed:`/`unfixable:` line of the reader responses for both documents, and every
   NOTE the gate printed.
   - Record the answer verbatim in `RUN_LOG.md`.
   - **(a) or (b) counts only if the approver personally typed it in this conversation.** An answer
     you give on their behalf -- because they are away, or told you earlier to "just proceed" -- is
     (c), recorded as a [PROXY] decision. Never record `--by human` for an answer you made.
   - Then run, choosing the flags from the answer:

     | answer | command |
     |---|---|
     | (a) | `signoff.py approve --round <R> --by human --how blanket` |
     | (b) | `signoff.py approve --round <R> --by human --how blanket --exclude "Theorem 2.7,…"`; use `--how individual` only if the approver really answered every result |
     | (c) | `signoff.py approve --round <R> --by agent --how blanket` (no `--exclude`: (c) approves everything) |

     Prefix each with `python3 audits/`. It checks every approved declaration with Lean and can
     take many minutes: give it a long timeout or run it in the background, and wait for it to
     finish before going on. Add `--note "<one sentence>"` when the record needs it,
     e.g. results the approver approved personally inside a (c) approval. It commits the approval
     itself (`approve <R>`): make no commit of your own for it. If the conversation ended while it ran
     (its files written, not committed), run the same command again: it commits the approval only when
     it equals what it computes now; otherwise it discards the interrupted files
     (`FAIL[uncommitted-record]`) and you ask the approver again.
   - Global differences at the head of the sheet are approved once each; under (b) a global left
     unticked excludes every result whose row cites it (the sheet lists them under "Used by").
   - QUESTION rows under (c): approve the sheet; for each QUESTION row the approver did not answer,
     you may make a provisional choice so the work can continue. Log it as a [PROXY] decision in
     `RUN_LOG.md`, keep it under "Open questions", and put it to the human at Checkpoint C.

   **Under `hands-off`, do not ask.** The sheet is still prepared, checked (`signoff.py check`) and
   written (step 7), since it is delivered, but skip step 7's fresh-reader check, its gate and its
   rendering: no human approves on its strength, and the delivery README says no reader read it.
   Its PDF is rendered at Stage 5. Then approve it
   yourself:
   `python3 audits/signoff.py approve --round <R> --by agent --how blanket --note "hands-off chosen at intake: <verbatim answer>"`
   (slow: wait for it as above); it commits `approve <R>` itself. The approval record names the agent and the note; the report and the
   sheet itself (its first line) say that no human reviewed the statements. Record the approval in
   `RUN_LOG.md` (Stage 2) as a tagged line, so it is counted:
   `- [DELEGATED <date>, operator under hands-off (intake); reversal: re-approve] approved the sheet of round <R> (commit <approval commit>) — hands-off chosen at intake`.
   Decide each QUESTION row as in "How you decide", recording each as [DELEGATED] under "Open
   questions". Write no `QUESTIONS-B-<R>.md` (nobody reads it); the rows reach the reader through
   `DECISIONS.md`.

   **Under `statements-only`,** ask as above, without option (c): the human chose at intake to
   approve the statements themselves. The answer must be typed by the approver in this
   conversation; never a [PROXY]. If they are away, stop and wait. Whatever their answer leaves
   undecided (a QUESTION row they did not answer) is decided by you as [DELEGATED], and is not put
   to them again.

   It refuses if anything changed since the sheet was made. From now on the approved statements
   are frozen: Phase 0's freeze check turns red if one changes, even through a definition it
   uses.

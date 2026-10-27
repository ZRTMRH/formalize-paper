# Stage 5 — final round, report, Checkpoint C

Read this when a Stage 4 exit check says "go to Stage 5". The run ends with the delivery: under
`involved` after Checkpoint C, which is asked on the documents before they are delivered (step 6),
and its answers carried out (step 7); under a delegating level with the completion message. Read `fresh-reader.md` before the first fresh-reader
check of this stage, `render-pdf.md` before the first PDF, and `reapproval.md` if a fix would change an
approved statement.

1. **Full-scope round.** Run Stage 4 with `prompt.py 3 --full` (its block scopes with
   `scope.py --full`). This round runs every correctness lane and re-examines everything,
   including passes made stale by a changed definition. If `scope.py --full` exits 3 with
   `NEXT[no-round]`, the last round was a full-scope proof round, adjudicated and settled, and
   the Lean changed since only in comments and docstrings (or not at all): that round is this
   step's full-scope round; run none and go to step 2. If it adopts anything, implement it and
   run one diff round on the result -- unless the fixes change only comments and docstrings:
   then `scope.py` prints `NEXT[no-round]` for the diff round and none runs. Resolve its REVOTE NEEDED rows as in Stage 4 step 5. If it
   adopts anything:
   - if a fix would change an approved statement or a definition one uses, follow RUN.md,
     "Statement changes after approval", and `reapproval.md`;
   - otherwise implement the fixes and run Phase 0. Every Lean change of this stage from here on
     (these fixes, step 4's delegated decisions, step 7's answers) gets **one** more diff round,
     together: run it once they are all in, before delivering (`--deliver` asks for it as
     `RED[deliver-stale]`). That is the cap: after the full-scope round at most two rounds
     (`project.DELIVERY_ROUND_CAP`). A Lean change after the second is implemented, committed and
     checked by Phase 0, and never re-audited: start no further round for it (`--deliver` no
     longer asks). The report and the summary list those commits under "Changes after the last
     audit round" (not re-audited, the cap reached), and the decisions document asks the human to
     confirm them. Its UNCOVERED rows are listed there for the human too.

   Three things are never a reason for another round (each cost a run a whole round):
   - **a change to comments and docstrings only**, at any stage: one that implements an ADOPT row
     of a round (trial #11: R3, a full round, and R4, a diff round, about 84 minutes, for docstring
     fixes) and one that implements none (e.g. a docstring note decided at Checkpoint C). Commit it
     and run Phase 0 (it still checks that the approved statements are unchanged); `scope.py`
     prints `NEXT[no-round]` for the round, and `--deliver` does not ask for one. No lane re-reads
     the new text: the report and the decisions document say so.
     `python3 audits/project.py --comment-only` checks it mechanically, with Lean (exit 0: each
     changed file, compiled before and after, gives the same declarations, with the same
     statements, proofs and definition bodies, and the same attributes and notation; only
     docstrings and source positions differ; nothing else changed). It builds the changed modules
     and compiles each changed file twice, so it takes about as long as that. The report and the
     decisions document then say so. Any other change, however small, fails the check and is
     handled as above;
   - **a stale `File.lean:N` in an adjudicator record** (`SKIPPED.md`, `PAPER_DEFECTS.md`,
     `VACUOUS.md`, a QUESTION row, a clearance): the report and the decisions document show a cited
     declaration at the line where it is declared now, resolved from its name;
   - **a decision cell of `PAPER_DEFECTS.md` or a status of `VACUOUS.md` written before your
     `[DELEGATED …]` decision on that row** ("is left to the human", "open"): the report and the
     summary show the decision beside it, from the log line anchored to the row (`defect:…`,
     `vacuous:…`), and quote a sentence that left the matter to a person as what the row said when
     it was written (trial #11: a 50-minute full round run so an adjudicator would rewrite such a
     cell, which it left unchanged). A reader finding on it is answered `dismissed`, citing the
     log line.
2. **Check and report.**
   - Run `python3 audits/integrity.py --check` (no round). It must report OK.
   - Commit, then run `python3 audits/phase0.py`. When GREEN it regenerates `REPORT.md` and the
     one-page summary `SUMMARY.md` (delivered first; `REPORT.md` section 0 points to it). The
     generators write markdown only; the PDFs are made from the audited markdown by agents (step 5,
     `render-pdf.md`). Never read a PDF yourself (RUN.md, rule 13). A fault in the markdown is fixed
     in the report's sources or in the generator, then regenerated -- or, after the final prepare, by a
     recorded hand edit (step 5, "A fault in a generated document"); never by an unrecorded edit of the
     output. Only a fault that nothing can fix (about the paper itself) goes into the notice
     `KNOWN_FAULTS-<key>.md` yourself, in the notice's form (`fresh-reader.md`, step 3), committed as
     `reader <key> notice`.
   - The fresh readers run after `--prepare-delivery` (step 5), on the prepared documents.
3. **Decisions document.**
   - If a `DECISIONS.md` from an earlier checkpoint exists, first move it to `DECISIONS.<date>.md`.
     Then run `python3 audits/decisions.py --write` (it uses the newest round). It writes
     `DECISIONS.md` in the rounds directory as a skeleton, with one anchored item for everything
     the human must see (the approval, every global difference and CHECK row, every result not
     formalized, paper defect, open vacuous statement, QUESTION row, [PROXY] decision, open
     question, standing defer, idle hypothesis of an approved statement (`UNUSED_ARGS.md`), the
     last round's UNCOVERED rows, every change after the last audit round), the detailed entries, and the pre-listed "Read this first" box.
     Items on one paper result are already one section (one decision per matter: its CHECK row,
     QUESTION rows, defect, vacuous row, unused hypothesis and the delegated lines on it); items on
     no paper result are grouped by kind (global differences, standing rules, …; a QUESTION row or a
     delegated line naming a standing rule is decided in that rule's section, and its result's
     section points there; under `involved`
     each question and [PROXY] stays its own section). Items already answered
     (`## Answered` in `RUN_LOG.md`) are listed as "Previously answered", once per matter, unless a later round asks
     them again or their content changed (a defect or vacuity row: its substance -- location, printed statement,
     status, repair -- never its wording); under a delegating level an item you decided and logged
     with this level's `[DELEGATED …]` tag keeps its section instead, its Decision taken filled from
     the log. **Under `involved`, what the human decided at Checkpoint B is not asked again**: the approval,
     the approved sheet's global differences, CHECK rows and results not formalized, and the defect and
     vacuity rows on a CHECK result as the record held them at the approval are listed once, under
     "Already decided by you at Checkpoint B (<date>)" with the B answer, not as sections; one comes back
     (a section saying it was decided at B) only when its substance changes, never its wording. An
     approval by the agent decided nothing for the human: then every item is asked. `--write --out PATH` / `--check --file PATH` write or
     check a draft elsewhere; an answer line naming no current item is listed as stray: fix its
     anchor.
   - **Under a delegating level** (`statements-only`, `hands-off`) the skeleton is headed
     "Decisions taken on your behalf" and gives every decision section a sixth field, **Decision
     taken**. Take each decision now, as in RUN.md "How you decide": the field states what was done,
     quotes its `[DELEGATED …]` tag, and says how the reader reverses it and what a reversal
     triggers. Its Recommendation field names the adjudicator's recommendation it follows, or the
     conservative rule's option; never your own. "Not applicable: <why>" only for an item the human
     decided at Checkpoint B. `[DELEGATED]` items already in `RUN_LOG.md` are listed as decided,
     their logged line prefilled: keep it word for word in its section (`--check` compares it with
     the log; a decision is changed by logging a new one, never by editing the document). A section
     holding several items (one paper result) gives each item exactly one Decision taken line, naming
     that item only (its plain label first, its anchor id small at the end, as prefilled), with its
     own tag and reversal cost. A decided line is shown once, in its Decision taken.
     Fill the "At a glance" table: one row per section, what was done, what it followed, and the
     reversal cost (a section of several items lists each source and cost once, separated by `;`).
   - State only what the record shows about the order of work (`stage2-statements.md`, step 3).
   - Fill it in. Read the section "Documents a human reads" of AUDIT_PROTOCOL.md (only that
     section) and follow it; the model is a document that opens with background (what was done,
     how the protocol works, where every file is, terms, the paper's notation), then gives
     decisions ordered by importance, each with paper / Lean / evidence / options and what each
     changes / recommendation, and ends with how to answer and what each answer triggers. Group
     items that are one decision; keep every anchor.
   - `python3 audits/decisions.py --check` must pass; it names each placeholder, anchor, box entry,
     field or tag it refuses. Fixing what it names is filling the document, at every level.
     It also refuses while a result left unproved awaits its adjudication, as `project.py --deliver` does.
   - Its fresh reader runs after `--prepare-delivery` (step 5).
4. **Delegated decisions** (`statements-only`, `hands-off`; under `involved` go to step 5 to
   prepare and read the documents, then to step 6: Checkpoint C comes before delivery). Do not wait
   for answers: the decisions were taken in step 3.
   - Record them in `RUN_LOG.md`: under `## Checkpoint C (<date>, delegated)` one line per
     decision, `- <anchor>: [DELEGATED <date>, operator under <level> (intake); reversal: <cost>]
     <decision> — <reason>`, and the same decision under `## Answered` as
     `- answered <anchor> (<date>, <round DECISIONS.md was written for>): [DELEGATED …] <decision> — <reason>`,
     word for word (the report counts the two as one), and `[DELEGATED …] <decision> — <reason>`
     copied word for word from the item's Decision taken line in `DECISIONS.md` (`--check` then
     requires it to stand there). A logged decision is never removed or reworded (`--check`
     compares the log with its committed history): to change one, log the new decision on a new
     line beside it. A decision already tagged earlier in the
     log (at Checkpoint B or between) is not re-recorded here: its section already shows it (if it
     is, the count still takes the two as one).
   - Carry each out as `DECISIONS.md` says it triggers. A change to the Lean is committed, then
     Phase 0; it gets the one diff round of step 1 if the cap leaves one (`--deliver` says
     `RED[deliver-stale]` while it does), else it ships disclosed; a statement change goes through `reapproval.md`: under `hands-off` approved by you;
     under `statements-only` it is a QUESTION approved by the human (the run goes on; delivery
     waits for the answer). If
     `decisions.py --check` then names a new item (for example the new commits), move the document
     to `DECISIONS.<date>.md`, write it again (the decided items keep their sections, their Decision
     taken filled from the log: copy their other fields from `DECISIONS.<date>.md`, re-checked at the
     new commit, never as a separate appendix), and take the new item the same way.
   - Commit, then run `phase0.py`: it regenerates the report and the summary, which now list the
     decisions taken on the reader's behalf.
5. **Prepare, read, deliver.** Under `involved` you come here twice: from step 4, to prepare and
   read the documents (then ask Checkpoint C, step 6, and deliver nothing yet), and from step 7 once
   Checkpoint C is answered, to prepare again, read the changed documents and deliver.
   `project.py --deliver` waits (`PENDING[question]`, never a stop) while an item of the decisions
   document has no answer of the human's logged (`decisions.checkpoint_c_open`; an empty answer
   answers nothing, and an answer carrying a [PROXY] or [DELEGATED] tag anywhere, quoted or not, or
   citing a source you decide by -- an escalation ("escalation E<n>"), an adjudicator's record (a
   round name, `ADOPTED.md`) or the conservative rule -- is yours and answers nothing: log the
   human's own words). After the delivery the `involved` run is
   complete: tell the human where the delivered files are, with the notices, reader responses and
   gate NOTEs as in step 6.
   - **Citation notes (step 5a; advisory, once per run, before the first prepare).** Start it once
     step 1's rounds are over; it runs while you do steps 2-4. Review of the paper's citations for
     its authors, in two fresh agents:
     ```
     python3 audits/prompt.py --prompt citations-draft  --write   # agent 1: <rounds dir>/citations/DRAFT.md
     python3 audits/prompt.py --prompt citations-review --write   # agent 2, after agent 1: <rounds dir>/CITATIONS.md
     ```
     Each writes its prompt under `<rounds dir>/citations/` and prints the spawn line: spawn one
     fresh general-purpose agent with it (Codex: `agent_type` `formalize_citations`, `fork_turns` none), the second only
     once the first has written `citations/DRAFT.md`, and never the same agent twice. Agent 1 checks
     every cited result the paper uses against its source (as stated, a stronger form, not
     reachable) and the bibliography; agent 2 verifies each item's evidence and writes the final
     file. The prompts carry intake 1c: for a confidential paper the agents only search for the
     cited works by title and authors and never send the paper's text anywhere. Commit
     `citations/` and `CITATIONS.md` by name (`citations: notes`). You do not edit the file or act
     on it: it never changes the Lean, a record, a decision or a round, and is never a reason for a
     question, a stop or a round. A usage limit or capacity error of either agent is waited out as
     `spawn-and-seal.md` says; any other failure (a crash, an agent that ends without its file) or no
     network: no retry; delete a partial `CITATIONS.md`, log the reason (`echo "- citation notes
     not produced: <reason>" | python3 audits/project.py --log "Citation notes"`), and go on. The
     run then ships without it. `CITATIONS.md` is an
     input of the summary ("Citation notes: N items — see CITATIONS.md", or "not produced:
     <reason>"): never write or change it after the first prepare. `--deliver` copies it into
     `deliverables/` (no check of it) and README D lists it.
   Once the documents are generated the run does not stop for them: every
   refusal below is a precondition with a fixed way out, never a stop (`stops.py open` refuses
   `deliver`, `unverified`, `deliver-stale` and an older run's `pdf`).
   - **Prepare.** `python3 audits/project.py --prepare-delivery` is the only generator of what is
     delivered: it regenerates `SUMMARY` and `REPORT` (make_report.py), adds to `DECISIONS.md`'s box
     every stop or disclosure recorded since you wrote it (your text is kept), re-renders the approved
     sheet if it still says "will be approved", writes the README sections A-C, records each
     document's generator-content hash in `DELIVERY.json`, and commits all of it as `prepare
     delivery`. It runs even while a stop is open: the summary then lists the stop as OPEN AT
     PREPARATION; close the stop, then prepare again. Never edit a generated document (SUMMARY,
     REPORT, the sheet, README A-C) except by a recorded hand edit of SUMMARY or REPORT after the
     final prepare (below): `--deliver` recomputes each and refuses one that differs by anything
     else.
   - **Readers** (`fresh-reader.md`), after prepare, on the prepared versions:
     ```
     python3 audits/prompt.py --prompt fresh-reader --doc summary   --round <newest round> --write   # gated, every level
     python3 audits/prompt.py --prompt fresh-reader --doc report    --round <newest round> --write   # one pass
     python3 audits/prompt.py --prompt fresh-reader --doc decisions --round <newest round> --write   # one pass
     ```
     The summary is gated: its newest pass reads its current version and every blocking finding is
     answered. The report and the decisions document get exactly one pass per version (a second pass
     on the same version is refused); their findings are answered like any other. The sheet keeps its
     approval-time pass while its hash is unchanged (`readers.py --doc signoff --round approved
     --check`); under `hands-off` it has no reader at all (`signoff.py check` only; the README says
     so). Each finding is labelled `[content]` or `[presentation]`:
     - a **content** finding (the record gives a line wrongly, or not at all) goes to the adjudicator:
       `python3 audits/prompt.py 4 --round <newest round> --reader-fix --write` writes and commits the
       reader-fix prompt; spawn a fresh adjudicator with the printed line; it commits with
       `integrity.py --commit-reader-fix`. Then prepare again and give each changed document one new
       pass. A reader fix that changes nothing is recorded as "no change" by the same command and
       counts as a round (no new pass: nothing changed). At most two reader-fix rounds per run; past that, answer what remains `unfixable` ("fix
       budget reached") and quote it in the notice. In dev a blocking finding left unfixable past the
       budget is a stop;
     - a **presentation** finding (how a right line is said), or a content finding the generator gets
       wrong although the record is right, is a fault in a generated document: never `unfixable`.
   - **A fault in a generated document** (approver 2026-10-25), found by a fresh reader, the status
     check or a PDF agent: choose one of three, each recorded (`fresh-reader.md` step 3 gives the
     commands and answer lines):
     1. **reject** it with a reason (not a real problem, or trivial: it affects neither faithfulness nor
        readability): the reader answer `dismissed`;
     2. **fix the generator** (release): `stops.py open --cause tool-bug`, the tool-patch route
        (`tool_patch.py`, a fresh reviewer), close the stop, prepare again, read the regenerated
        documents; in dev the maintainer's (a stop);
     3. **hand-edit** the document when a generator patch would be dangerous (it touches logic many
        documents share, or the core): after the final prepare, edit `SUMMARY.md` or `REPORT.md`, then
        `python3 audits/readers.py --doc summary|report --hand-edit --finding "<record>: <quote>"` (one
        commit, `hand-edit HE<k> <doc>`, with `hand-edits/HE<k>.json` and its diff). Then one fresh-reader
        pass on the edited version, the status check again (it judges each edit), and render the PDF
        again. A later prepare erases every hand edit (it prints which): redo what still holds.
     "Unfixable: generator fault" is not an answer for a real problem: `readers.py --check` refuses it on
     the summary and the report. A status-check mismatch or a PDF agent's finding on the markdown is
     answered the same way, in `status-check/ACTIONS.md` (`- M<n>: rejected — <reason>`, `tool patch
     TP<k>`, `hand edit HE<k>`) or, for a PDF agent, a line under `## Document faults` in `RUN_LOG.md`.
   - **Status check (advisory; after the first prepare, beside the readers, before the render).** One
     fresh agent reads `SUMMARY.md` next to `REPORT.md` and the records they cite, and checks that the
     status the summary gives each result is what the report and the records say (an assumed
     hypothesis shown "proved", a settled ambiguity shown "not established", a defect the summary
     does not show):
     ```
     python3 audits/prompt.py --prompt status-check --write   # <rounds dir>/status-check/status-check.txt
     ```
     Spawn one fresh general-purpose agent with the printed line (Codex: `agent_type`
     `formalize_status_check`, `fork_turns` "none"); it writes `status-check/FINDINGS.md`. If Claude Code
     refused that write ("Subagents should return findings as text"), the agent returns the file's text
     between a line `BEGIN RETURNED FILE <path> <delimiter>` and a line `END RETURNED FILE`: save exactly
     that text, unedited, as `FINDINGS.md` with a quoted heredoc ending at the delimiter that line names
     (`RETURNED_` and 12 hex digits, unique to the run: `cat > <rounds dir>/status-check/FINDINGS.md
     <<'<delimiter>'`, the text, `<delimiter>`; the quotes stop the shell expanding backticks and `$`), and go
     on as if the agent had written it (a sealed run: seal it from its returned line, below). For each
     mismatch you agree with, correct it through the route that owns the status (and reject the others with a
     reason): a status that comes
     from a record goes to the adjudicator (the reader-fix route above, after `status-check/` is committed:
     `python3 audits/prompt.py 4 --round <newest round> --reader-fix --status-findings M<n>[,M<m>] --write`
     carries those mismatches of the committed `FINDINGS.md` into its prompt as findings); one the
     summary's script computes wrongly is a fault in a generated document: the tool-patch route (release,
     RUN.md "Tool patches"), or a hand edit when a patch would be dangerous (above). Then prepare again
     and give each changed document its reader pass. Write `status-check/ACTIONS.md`, one line per
     mismatch: `- M<n>: <what you did>` (fixed by ..., or not fixed: <why>), and commit `status-check/`
     by name (`status-check: findings`; commit `FINDINGS.md` so before a reader fix names its
     mismatches, `ACTIONS.md` once you have acted). Never a stop, never a question and never a reason to hold
     the delivery: if the agent fails or ends with neither its file nor its returned text, do not retry; write in `ACTIONS.md`
     `- not produced: <reason>` and go on -- except after a **hand edit**: then the check is the judge
     of the edit, and `--deliver` refuses (`RED[deliver]`, never a stop) until a status-check run
     issued after the newest hand edit says `- HE<k>: OK` for each under `## Hand edits`. Such a run is
     authenticated like a lane: `--write` prints a spawn line carrying the run's token (the agent writes
     `run-token: <token>` into `FINDINGS.md`) and the agent ends with
     `STATUS_CHECK_COMPLETION <path> <sha256>`; seal it from that line,
     `python3 audits/run_record.py --seal-status-check --sha256 <sha256> --agent-id <the agent's id>`
     (it commits `FINDINGS.md` with `SEAL-<n>.json`; a returned `FINDINGS.md` saved as above is sealed only
     if its sha256 is the one the agent returned, so save it byte for byte). Never write or change a verdict line yourself:
     `--deliver` refuses a `FINDINGS.md` that is not the sealed agent's file. If that agent fails, ends
     with neither `FINDINGS.md` nor its returned text, writes no `OK`/`MISMATCH` line for an edit, or returns no completion line,
     the run failed: a mechanical failure, recorded in `RUNS.json` and the run record, never a
     judgement. Run it again with the same command (a fresh agent), whatever the cap. The same holds for
     the **trust lines** (approver 2026-10-26): each plain sentence the generator writes on SUMMARY page 1
     and in REPORT for an event RUN_RECORD.md records (a check that could not be run, ...) is judged by the
     run under `## Trust lines`; `--deliver` refuses until each is `OK`, and a `MISMATCH` is fixed through
     the generator (a tool patch) or a hand edit, then judged again. A `FINDINGS.md`
     that carries the run's token and a verdict line for every live edit is a judgement, sealed or not
     (and also once deleted, if a version of it was committed): seal it; it is never run again. A `MISMATCH` (the
     edit changes a status, a statement, a defect verdict or a human answer away from the records)
     is undone by preparing again, which erases every hand edit; re-apply each edit judged `OK` as a
     new hand edit (`patch -p1 -d <rounds dir> < <rounds dir>/hand-edits/HE<k>.diff`, or make it again,
     then `readers.py --hand-edit`), answer its findings anew, read, and run the check again. A hand
     edit restoring the text does not undo a `MISMATCH`: the check judges each edit's own diff.
     `--deliver` quotes `FINDINGS.md` and `ACTIONS.md` in the
     delivered `RUN_RECORD.md` (never in the report); nothing checks their content. The check must
     read the summary that is delivered: `--write` records which `SUMMARY.md` each run reads
     (`status-check/RUNS.json`), and when a later prepare changed it (a reader fix, a fix the check
     itself asked for), `--deliver` refuses (`RED[deliver]`, never a stop) until you run it again
     with the same command: it writes `status-check-<n>.txt`, keeps the earlier findings as
     `FINDINGS-<n-1>.md` and `ACTIONS-<n-1>.md`, and the new agent writes `FINDINGS.md`. A hand edit the last
     run did not see always gets a run (to judge it), whatever the cap. Otherwise at most 3
     runs; past that the delivered run record says the check read an earlier summary.
   - **Render the PDFs** (`render-pdf.md`), once the reader gates pass on the prepared versions
     (`render_record.py begin` refuses a markdown not audited at its current hash). Render
     `SUMMARY` and `REPORT` in parallel, and the approved sheet (`--doc SIGNOFF --round approved`)
     if its markdown changed since it was rendered (the approval stamp) or it was never rendered
     (`hands-off`). Only a document whose markdown changed is rendered again; `render_record.py
     next --doc D` says which step each is at. A renderer makes each PDF, a verifier checks it, and
     two independent checkers judge whether it says mathematically the same thing as the markdown;
     a checker's difference goes back to the renderer; after at most 6 rounds the least bad PDF
     ships with every remaining objection on its first page (a cover a fresh verifier passed; without
     one, the PDF ships with no cover, disclosed). The markdown is always delivered
     beside its PDF. Never a stop: a failed agent is recorded with `render_record.py fail`.
   - **Deliver.** `python3 audits/project.py --deliver` only checks, in both modes, and copies:
     1. `make_report.py --check --delivery`: every prepared document is what the generator writes now
        (an input changed since prepare -- a closed stop, a record, an answer, a Lean commit -- makes it
        stale: `RED[deliver]`, prepare again and read the changed documents once more), changed since
        only by recorded hand edits, each its own commit, chained to the file and judged `OK` by the
        status check; each reader
        gate as above; the summary's coverage (every disclosure listed, or counted by name with the
        report section that holds it) and its result-status check; every qualified Lean
        name SUMMARY, REPORT, DECISIONS and the sheet cite exists (resolved in Lean against the build;
        a wrong one: correct the text that says it, then prepare again); no `unverified` (no full-scope round since the approval, or a result whose
        verdict is missing or out of date, `result_status.py`: run a full round) and no `deliver-stale`
        (a Lean commit after the last audited round: run a diff round on it; if `scope.py` exits 3 with
        `NEXT[full-round]`, the commit changed no reviewed declaration: a full round; once two rounds
        ran after the full-scope round, step 1's cap, it is no longer asked: the commit ships
        disclosed); nothing pending
        (`RED[adj-record]`, e.g. a Fail or Ambiguous no adjudication settled, an assumption without its
        record, a route change recorded in `AUTHOR_NOTES.md` after the last adjudication: one more round). A status `result_status.py` cannot route (`status-unmapped`) is
        disclosed in release (the summary says it); in dev it is a stop, cured as RUN.md's failure table
        says (Phase 0, the index cell; what remains is accepted as shown when the stop closes).
     2. No stop and no QUESTION open (`PENDING[stop]`, `PENDING[question]`: close the stop, or wait for
        the human's answer; never a [PROXY] answer).
     3. The delivery gate (`deliver_blocking`, both modes): integrity, the freeze, Phase 0 read-only and
        every self-cured stop's check; in release also every disclosure recorded and named.
     4. The render guard (`render_record.py check`): each PDF is the one the rendering agents shipped
        for its markdown as it is now -- a fingerprint, never a reading (`RED[deliver]`: render again;
        never a stop).

     It then copies SUMMARY, REPORT and the approved sheet, each as its PDF with its markdown beside
     it (the markdown alone when no round produced a PDF), `DECISIONS.md` and `RUN_RECORD.md` (the
     run record as prepared, then its delivery-phase notes: the `KNOWN_FAULTS-<key>.md` notices of the
     delivered documents folded in, the delivery-phase disclosures; no `KNOWN_FAULTS` file is
     delivered; markdown only: it is never rendered and has no reader) into `deliverables/`, with
     `README.md`: sections A-C as prepared, then section D (written only there: the pointer to
     RUN_RECORD.md, each document's reader outcome, how each PDF was made and checked, every remaining
     objection and checker finding quoted, and the sha256 of each delivered PDF and of RUN_RECORD.md).
     It refuses a RUN_RECORD.md that omits an applied tool patch, a stop the operator closed or a
     set-aside (`integrity.py --check-run-record`). Each attempt logs one line under `## Delivery` of
     `RUN_LOG.md` (when it started and ended; delivered, or the codes that refused it), and a delivery
     sets `## Current stage` to "Stage 5 — delivered <time>"; it commits `RUN_LOG.md` itself, and the
     delivered `RUN_RECORD.md` gives the delivery's start and end. Do not log the delivery by hand. If the intake named another destination, copy them there as
     well (`cp`, which asks for permission), or tell the human where they are. Right before the
     completion message (or Checkpoint C's delivery), run `python3 audits/project.py --check-delivered`:
     every PDF in `deliverables/` and RUN_RECORD.md must be the one delivered (README D's sha256, and its render
     record's). `RED[deliver]`: deliver again; never a stop.
   - A re-approval still open (`REAPPROVAL.json`, begun and not closed by `signoff.py approve`) is
     never delivered. When it is the human's question (`involved`, `statements-only`) the report check
     prints `PENDING[question]` (not RED) and `project.py --deliver` refuses with `PENDING[question]`:
     wait for the human (never a stop, never a [PROXY] answer); when they answer, log it and approve as
     in `reapproval.md` step 4 (a rejected change: restore the approved statement first, "A rejected
     change" there), then prepare again, read, and deliver. One the agent may close itself keeps
     `make_report.py --check` RED: close it (`signoff.py approve`) before delivering.
   - A `leave <decl> unproved` line logged after the final diff round (e.g. at delegated Checkpoint C)
     needs one more round, so its adjudicator checks it: `--deliver` refuses (`RED[adj-record]`)
     any such result still pending. Run a diff round; when nothing changed for it to scope, `scope.py`
     exits 3 with `NEXT[full-round]` (anything awaiting the next adjudication goes to a full round,
     `prompt.py 3 --full`, never back to Stage 5), and that round's adjudicator settles it.
   - Commit the audits repo: your own files that changed (`RUN_LOG.md`, `AUTHOR_NOTES.md`,
     `DECISIONS.md`, `OUTCOMES.md`, `READER_NOTES.md`) by name, never `git add -A`
     (RUN.md rule 5); every other record was committed by its script.
   - Push only if the intake said yes.
6. **Checkpoint C, or the completion message.** Under `involved`, Checkpoint C is asked on the
   documents prepared in step 5 once their fresh-reader checks pass, before anything is delivered
   (U2 §6.7). Send the human a short message:
   where `SUMMARY.pdf` (read it first), `DECISIONS.md`, `REPORT.pdf` and `SIGNOFF.pdf` are, each with its
   markdown beside it (in the rounds directory: nothing is delivered yet); the number of decisions; whether the statements were approved by a human or by
   the agent; the outcome lines `render_record.py next` printed for each PDF (`DONE[render]`: every
   remaining objection, every checker finding, and the renderer's NOTE lines), verbatim; every hand
   edit of a generated document (`HE<k>`, the finding it fixed); every
   `KNOWN_FAULTS-*.md` notice of the delivered documents, verbatim (they are delivered folded into
   `RUN_RECORD.md`); every
   `fixed:`/`dismissed:`/`unfixable:` reader response; every NOTE the gate printed; and the
   fresh-reader pass counts. The decisions themselves
   are in `DECISIONS.md`, not in the message; it asks only what the human has not decided (step 3:
   never a Checkpoint B decision again, unless its substance changed). Record the human's answers verbatim in `RUN_LOG.md`
   under `## Checkpoint C (<date>)`, add one line per answered item under `## Answered`
   (`- answered <anchor> (<date>, <round DECISIONS.md was written for>): <answer>`), and go to step 7.
   Wait for the answer (it is a QUESTION, not a stop: nothing else of the run is left to do); never
   answer an item yourself, and never deliver before it.

   **Under a delegating level** do not ask; send a short completion message instead: what was
   produced and where (`SUMMARY.pdf` first, then `REPORT.pdf`, `SIGNOFF.pdf`, `DECISIONS.md`, and
   `CITATIONS.md` if it was produced, with paths;
   each PDF with its markdown beside it, and its render outcome lines verbatim); that the involvement level
   delegated the decisions, how many were taken on their behalf, and where to review and reverse
   them (`DECISIONS.md`, and the report's section 1); whether a human approved the statements;
   and, as above, every notice, reader response, hand edit, gate NOTE and pass count. End it with these
   reversal instructions, filled in: "To reverse a decision, open Claude Code in
   `<project path>` and say: *Read audits/RUN.md; reverse `<anchor>` in DECISIONS.md.* The table
   at the top of `<path to DECISIONS.md>` gives each decision's anchor and what reversing it
   costs (none, re-prove, re-approve or new round); its section says what will be rerun." The
   run is then complete. A later reversal the human asks for is new work: record their words
   verbatim and carry it out by step 7.

   Only now may you save a memory note about the run (under `involved`: after step 7's delivery).
7. **After Checkpoint C's answers, or any later reversal** (every level; U2 §6.7). In this order:
   1. Carry out each answer as `DECISIONS.md` says it triggers (a change to an approved statement
      begins its re-approval before the edit, `reapproval.md` step 1).
   2. If the Lean changed: commit, run Phase 0, and run one diff round on it if step 1's cap leaves
      one (`--deliver` asks for it as `RED[deliver-stale]` while it does; Stage 4; implement its ADOPT
      rows as in step 1 above, with no further round). A change to comments and docstrings only needs
      none (step 1). An answer that changes no Lean needs no round.
   3. If an approved statement changed: finish its re-approval (`reapproval.md` steps 3-4; under
      `involved` and `statements-only` the human approves it).
   4. Rewrite the decisions document: move `DECISIONS.md` to `DECISIONS.<date>.md`, run
      `decisions.py --write` again (the answered items are listed as previously answered; an item a
      later round asked again, or a new one, is an item again), fill and check it as in step 3.
      Under `involved` a new or re-asked item goes back to the human (step 6, for those items only).
   5. Regenerate and check the documents (step 2), then step 5: prepare again, run the fresh reader
      on every document that changed, render again only the documents whose markdown changed, and
      deliver.

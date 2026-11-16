# Stage 5 — final round, report, Checkpoint C

Read this when a Stage 4 exit check says "go to Stage 5". The run ends with the delivery: under
`involved` after Checkpoint C, which is asked on the documents before they are delivered (step 6),
and its answers carried out (step 7); under a delegating level with the completion message. Read
`render-pdf.md` before the first PDF, and `reapproval.md` if a fix would change an approved statement.
After the mathematics is verified, delivery never stops and is never refused except by the math gate
(step 5; approver, 2026-10-28).

1. **Full-scope round.** Run Stage 4 with `prompt.py 3 --full` (its block scopes with
   `scope.py --full`). This round runs every correctness lane and re-examines everything,
   including passes made stale by a changed definition. If `scope.py --full` exits 3 with
   `NEXT[no-round]`, the last round was a full-scope proof round, adjudicated and settled, and
   the Lean changed since only in comments and docstrings (or not at all): that round is this
   step's full-scope round; run none and go to step 2. If it adopts anything, implement it and
   run one diff round on the result -- unless the fixes change only comments and docstrings:
   then `scope.py` prints `NEXT[no-round]` for the diff round and none runs, except when such a fix
   implements an ADOPTed Fail on an index row's declaration (a docstring finding on a Definition):
   the diff round then runs and re-reads it (it counts toward the cap). Resolve its REVOTE NEEDED rows as in Stage 4 step 5. If it
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

   Four things are never a reason for another round (each cost a run a whole round):
   - **a change to comments and docstrings only**, at any stage: one that implements an ADOPT row
     of a round (trial #11: R3, a full round, and R4, a diff round, about 84 minutes, for docstring
     fixes) and one that implements none (e.g. a docstring note decided at Checkpoint C). Commit it
     and run Phase 0 (it still checks that the approved statements are unchanged); `scope.py`
     prints `NEXT[no-round]` for the round, and `--deliver` does not ask for one. No lane re-reads
     the new text: the report and the decisions document say so. The one exception: a docstring fix
     that implements an ADOPTed Fail on an index row's declaration is re-read by the next diff round
     (`scope.py` runs it instead of printing `NEXT[no-round]`), so the result does not stay "not
     established" for ever.
     `python3 audits/project.py --comment-only` checks it mechanically, with Lean (exit 0: each
     changed file, compiled before and after, gives the same declarations, with the same
     statements, proofs and definition bodies, and the same attributes and notation; only
     docstrings and source positions differ; nothing else changed). When the compiled files differ
     only in their bytes (every declaration, type, value and attribute the same) and each changed
     file, with comments and docstrings removed, reads exactly as before, it is accepted too: its
     `ok:` line says "checked on the source", and so do the report, the decisions document and
     `RUN_RECORD.md` (DESIGN-M7). It builds the changed modules
     and compiles each changed file twice, so it takes about as long as that. The report and the
     decisions document then say so. Any other change, however small, fails the check and is
     handled as above;
   - **a row already decided**: an ADOPT implemented in comments and docstrings, an ADOPT you declined
     (OUTCOMES.md "not implemented — disagree", or any outcome not starting "implemented", or no OUTCOMES.md
     row; it is a `declined:` item of the decisions document, asked at Checkpoint C under `involved` and, under a
     delegating level, disclosed by that item, whose "Decision taken" field carries the [DELEGATED] tag), a DEFER, a QUESTION answered by the human or by a [DELEGATED] line.
     A new round sees the same Lean and writes the same decision. Its result keeps its "not established …
     decision: X" status, which the summary explains; `scope.py` prints `NEXT[no-round]` (MAINTAINING L5);
   - **a stale `File.lean:N` in an adjudicator record** (`SKIPPED.md`, `PAPER_DEFECTS.md`,
     `VACUOUS.md`, a QUESTION row, a clearance): the report and the decisions document show a cited
     declaration at the line where it is declared now, resolved from its name;
   - **a decision cell of `PAPER_DEFECTS.md` or a status of `VACUOUS.md` written before your
     `[DELEGATED …]` decision on that row** ("is left to the human", "open"): the report and the
     summary show the decision beside it, from the log line anchored to the row (`defect:…`,
     `vacuous:…`), and quote a sentence that left the matter to a person as what the row said when
     it was written (trial #11: a 50-minute full round run so an adjudicator would rewrite such a
     cell, which it left unchanged). A delivery reviewer's finding on it is declined in
     `JUDGEMENT.md`, citing the log line.
2. **Check and report.**
   - Run `python3 audits/integrity.py --check` (no round). No FAIL may concern the proof-validity
     core, a freeze record or a judgement record (the math gate, step 5); any other FAIL is a note
     `--deliver` prints for you to judge.
   - Commit, then run `python3 audits/phase0.py`. When GREEN it regenerates `REPORT.md` and the
     one-page summary `SUMMARY.md` from the records as a draft in `<rounds dir>/facts/` (the
     rounds-directory copies are yours: seeded from the draft only while missing or untouched). The delivered `SUMMARY.md` and
     `REPORT.md` are yours, written in step 5 from the records and the Lean. The PDFs are made from
     the markdown by agents (step 5, `render-pdf.md`). Never read a PDF yourself (RUN.md, rule 13).
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
   - `python3 audits/decisions.py --check` is advisory (`--deliver` never refuses on it); it names each placeholder, anchor, box entry,
     field or tag it refuses. Fixing what it names is filling the document, at every level.
     It also refuses while a result left unproved awaits its adjudication (`project.py --deliver` notes it).
   - Its review is the DECISIONS reviewer's, with the other delivery reviewers (step 5).
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
   - Commit, then run `phase0.py`: it regenerates the draft report and summary, which now list the
     decisions taken on the reader's behalf.
5. **Prepare, write, review, deliver** (approver, 2026-10-28, binding). After the mathematics is
   verified, **delivery never stops and is never refused except by the math gate** (below). You write
   the deliverables yourself; fresh reviewers advise; you judge. Nothing about the documents is a stop
   (`stops.py open` refuses `deliver`, `unverified`, `deliver-stale`, `reader`, `reader-check`,
   `decisions`, `status-unmapped` and an older run's `pdf`), and nothing about them is a question to the
   human. Under `involved` you come here twice: from step 4, to prepare, write and review the documents
   (then ask Checkpoint C, step 6, and deliver nothing yet), and from step 7 once Checkpoint C is
   answered, to revise and deliver. Two designed human waits remain (a wait, never a stop):
   `--deliver` prints `PENDING[question]` while Checkpoint C is unanswered under `involved`
   (`decisions.checkpoint_c_open`; an answer carrying a [PROXY] or [DELEGATED] tag is yours and answers
   nothing; an answer is the human's words, logged verbatim; one that points to an option you offered or
   a record (ADOPTED.md, escalation E<n>, the conservative rule) adopts it as the human's answer, and
   README shows it so), and `PENDING[stop]` while
   a stop that waits for the human is open (a release human stop; any open stop in dev). Another open
   stop is a note. After the delivery the
   `involved` run is complete: tell the human where the delivered files are, as in step 6.
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
   - **The math gate** -- the only things `project.py --deliver` refuses on (`RED[...]`), in both modes:
     Phase 0 read-only GREEN (the build; no `sorry` but one a logged `leave <decl> unproved` line
     discloses as stated only; standard axioms only), the freeze (`fingerprint.py --check`; no
     re-approval open), the integrity of the proof-validity core (an `integrity.py --check`
     FAIL on a core file, a record of the freeze, or a record that carries a judgement: a lane's verdict,
     an adjudication, an approval, a round's files; any other integrity FAIL is a note), and no Lean
     commit after the last audited round (`RED[deliver-stale]`: run a diff round on it; if `scope.py`
     exits 3 with `NEXT[full-round]`, a full round; once two rounds ran after the full-scope round, step
     1's cap, it is no longer asked: the commit ships disclosed). Fix what it names, then deliver again.
   - **Facts draft.** `python3 audits/project.py --prepare-delivery` writes the generator's draft of
     `SUMMARY.md`, `REPORT.md` and `RUN_RECORD.md` to `<rounds dir>/facts/` (statuses, goal results,
     defects, assumptions, decisions, trust lines, stops, tool patches), adds to `DECISIONS.md`'s box every
     stop or disclosure recorded since you wrote it (your text is kept), re-renders the approved sheet if
     it still says "will be approved", writes README sections A-C and `DELIVERY.json`, and commits it as
     `prepare delivery`. The draft is **data for you, not the deliverable**. It never overwrites your
     `SUMMARY.md`, `REPORT.md` or `RUN_RECORD.md` in the rounds directory (a missing one is seeded from
     the draft, for you to rewrite). Run it again whenever a record changed; then check that your
     documents still say what the records say. (Phase 0 in author mode writes its drafts to `facts/`
     too: it never overwrites or deletes your documents.)
   - **Write** `SUMMARY.md` and `REPORT.md` in the rounds directory yourself, from the records and the
     Lean (the draft helps you find everything; it may be stale or wrong), for a research mathematician
     who knows the paper but neither Lean nor this tool:
     - every result's status exactly as the Lean has it: check each one against the Lean source (is it
       proved with no `sorry`? which hypotheses does its statement carry, and which unproved results do
       they stand for?) and against the records (`ADOPTED.md`, `PAPER_DEFECTS.md`, `SKIPPED.md`,
       `VACUOUS.md`, `DEVIATIONS.md`, `UNUSED_ARGS.md`, `DEPENDENCIES.json`, `RUN_LOG.md`);
     - understate rather than overstate: "proved, assuming X", "stated, not proved", "the Lean proves the
       printed statement false" (not "fails for every n" unless the Lean says so); when in doubt, the
       weaker claim;
     - plain words: define once every term the reader cannot know (`sorry`, the goal results, the
       involvement level, "approved", "no outside assumptions"); the paper's printed numbering and pages,
       never TeX labels;
     - SUMMARY first page: what was done, the bottom line, the status table, defects found, what was
       assumed and how each assumption was checked, where the proofs depart from the paper's, every
       decision taken on the reader's behalf (who decided -- the person who ran the tool, the agent, on
       whose recommendation -- and what reversing it costs), what was machine-checked, what reviewers
       checked and what nobody checked, and one line "What we ask of you"; each reading choice whose
       QUESTION no person answered (`DECISIONS.md` says who decided) is its one line phrased as a
       short question to the authors ("<result>: we read '<phrase>' as <the Lean's reading>; did you
       mean <the other>?", the weaker reading marked as such), counted by name with REPORT's section
       when the page is full;
     - on SUMMARY's first page, one line: "What the checking code found -- each result's status as the
       code computes it, the answers recorded as yours, and anything the checks noticed -- is in
       README.md." Keep the draft's "Answers recorded as yours" with their audit commits, or leave them
       to that README section, which always lists them (a missing pointer line is a note, never a
       refusal);
     - for each result that the facts draft does not rate *faithful* and whose status your summary words
       differently, add one line to `JUDGEMENT.md` under `## Status wording`:
       `- <label>: <why, in plain words for the author>`. The delivered README shows it next to the
       result. `--deliver` lists any you missed in a `[status-wording]` note: add those lines and
       deliver again;
     - if the human or the intake supplied known issues (CONDITIONS.md kind `known-issue`, an answer key,
       errata), say for each how the run handled it (a PAPER_DEFECTS row, a route change, why it is not a
       defect); never write "no defect" alone;
     - when the run had no network (`confidential`, or citation notes not produced for lack of network),
       the SUMMARY's trust lines say that cited results were compared only with the copies supplied to the
       run (SOURCES.md) and that their numbering in the published versions was not checked;
     - the K standard (next batch D1; approver 2026-11-16, option A): the code writes no K content (no count,
       no table, no list of items); you write it, labelled "the formalizing agent's judgement". In REPORT's
       section 12 "K certificate" (keep the title; the facts draft holds only the definition and a place
       for your text): for each result, K1–K4 yes or no, each with the reason and file:line evidence (the
       paper, the Lean, the records); how many results reach K; and the open K gaps (an unproved change of
       representation, a reading or generalization of a statement, an assumption, an open `CONDITIONS.md`
       item), each with the results it actually affects (an item on a helper lemma affects only the
       results whose proofs use it: check the Lean and `DEPENDENCIES.json`). The open items are the
       `CONDITIONS.md` items and ADOPTED `## Conditions` rows whose latest status is not `met` or `not
       applicable`: read them there; `--deliver`'s conditions-checklist notes add only record problems and
       the inferred items, for you to judge. In SUMMARY, one K line
       with the count and the reason in a few words, labelled the same way. The mechanical facts (the
       build, the `sorry` scan, `#print axioms`, the kernel replay) stay where they already are, as plain
       facts. Define K once in SUMMARY ("K: the Lean statement says exactly what
       the paper says, the proof is checked by Lean's kernel, every change of representation is proved,
       nothing is assumed");
     - a question to the authors is never about something outside a `scope` item of `CONDITIONS.md`;
       such a lead stays a note in REPORT;
     - REPORT: the same, in full, per result and per decision, with the Lean names and files;
     - process mechanics (stops, tool patches, reviewers, rounds, seals, scripts) only in
       `RUN_RECORD.md`; correct `RUN_RECORD.md` and `DECISIONS.md` where the draft is stale or wrong (a
       logged `[DELEGATED …]` line is changed only by logging a new one: step 4).
     When the facts disagree (e.g. `result_status.py` says "not established" for a result the
     adjudicator settled), judge from the records and the Lean, write what you find, and note the
     disagreement in `JUDGEMENT.md` (below); it never blocks. Commit your files by name
     (`deliverables: write`).
   - **Review.** Spawn four fresh general-purpose agents in parallel (at most 3 at once on a
     machine of 16 GB or less: RUN.md, "Cost"; Codex: `agent_type`
     `formalize_reader`, `fork_turns` "none"), one per perspective -- CLAIMS, READABILITY, DECISIONS,
     TRUST -- each with the prompt under "Delivery reviewer prompt" below, filled in. Their findings come
     back as their final message: subagent file writes are often refused ("Subagents should return
     findings as text"), so the prompt asks for text; save each returned text verbatim as
     `<rounds dir>/delivery-review/<PERSPECTIVE>.md` and commit `delivery-review/` by name
     (`delivery review`). No seal, no token. A reviewer that fails or returns nothing: spawn one fresh
     replacement once; if that fails too, write so in `JUDGEMENT.md` and go on.
   - **Judge and revise.** Judge every finding and write `<rounds dir>/JUDGEMENT.md`, one line per
     finding: `<perspective>-<n> · adopted|adopted in part|declined. <what you changed, or why not>`.
     You **must** fix every overstatement the claims reviewer reports (it is never declined); an
     understatement, a readability, decisions or trust finding you may decline with a reason. Revise
     the documents once, commit them with `JUDGEMENT.md` by name. A second review pass (fresh agents,
     only the perspectives concerned) only if you judge the revision needs it. Never a stop, never a
     question to the human.
   - **Render the PDFs** (`render-pdf.md`): `SUMMARY` and `REPORT` in parallel (`python3
     audits/render_record.py next --doc SUMMARY|REPORT`), and the approved sheet (`--doc SIGNOFF --round
     approved`) if its markdown changed since it was rendered (the approval stamp) or it was never
     rendered (`hands-off`). Render after the revision; a document changed later is rendered again. A
     renderer makes each PDF, a verifier checks it, and two independent checkers judge whether it says
     mathematically the same thing as the markdown; after at most 6 rounds the least bad PDF ships with
     every remaining objection on its first page. The markdown is always delivered beside its PDF. Never
     a stop: a failed agent is recorded with `render_record.py fail`.
   - **Deliver.** `python3 audits/project.py --deliver` runs the math gate; if it passes it copies into
     `deliverables/` your SUMMARY and REPORT (each with its PDF when one was shipped, the markdown
     always), the approved sheet, `DECISIONS.md`, `RUN_RECORD.md` (yours, then its delivery-phase notes),
     `JUDGEMENT.md`, `CITATIONS.md` when produced, and `README.md`: sections A-C as prepared, with the
     section "What the checking code found" inserted before A -- written by the checking program, not
     by you: each result's status as computed from the review records (a † where your summary words a
     status differently, with your `## Status wording` reason), the proof checks, the run settings
     fixed at the start, whether the checking software changed since the first pin, the answers
     recorded as the human's, the reviews on record, and every note below counted by kind -- then
     section D: who wrote and reviewed the documents, how each PDF was made, and the sha256 of every
     delivered file but README.md (README.md's own sha256 goes in the `## Delivery` line of
     `RUN_LOG.md`). Every note is also in the delivered `RUN_RECORD.md` under "Notes at delivery",
     word for word. Then it prints **notes for the main agent (not blocking)**: a stale facts
     draft, a document check (coverage, a Lean name a document cites that does not resolve), `unverified`
     (no full-scope round since the approval, a verdict out of date), a result whose status no route
     covers, an item pending the next adjudication, an integrity FAIL outside the core, a PDF that is not
     the one rendered from the markdown as it is now (left out: the markdown ships alone), an open stop
     that waits for no human, a SUMMARY or REPORT still identical to its facts draft, what
     `RUN_RECORD.md` omits (a tool patch, a stop the operator closed, a set-aside), a self-cured stop's
     check that fails now, the tool-patch delivery check. Judge each: fix what you agree with (revise a
     document, correct `RUN_RECORD.md`, render again, run a round) and deliver again, or leave it and say
     why in `JUDGEMENT.md`. None refuses the delivery. Every note has an id (`(id n3fa2c1)` after it; in
     the delivered `RUN_RECORD.md`, `- [n3fa2c1] <note> -- judged: <who>`), and the code reads who judged it
     from the records. **The NOTES reviewer** (once per run): after the first `--deliver`, if any note is
     not judged by a reviewer, spawn one more fresh delivery reviewer, perspective NOTES (Codex:
     `formalize_reader`, `fork_turns` "none"), with the prompt under "Delivery reviewer prompt"; save its
     returned text verbatim as `<rounds dir>/delivery-review/NOTES.md` and commit it by name in a commit of
     its own whose subject starts `delivery review` (the code counts its verdicts as the reviewer's only
     then; under any other subject, or after a later commit of the file under another subject, they read as
     yours); act on each note, write one line per note under `## Delivery notes` in `JUDGEMENT.md`
     (`- <id>: <what you did and why>`, or `- <id>: see delivery-review/NOTES.md -- <what you did>`), and
     deliver again. A reviewer that fails: one fresh replacement; then deliver anyway. README.md names
     every note no independent reviewer judged, every note nobody judged, every note the reviewer called a
     real problem and every note it marked `cannot tell` (with your line), and says that you saved NOTES.md; notes new at the final delivery are listed as not judged.
     Never a stop, never a question to the human. Each attempt logs one line under `## Delivery` of
     `RUN_LOG.md`, and a delivery sets `## Current stage`; it commits `RUN_LOG.md` itself. A copy to
     another destination the intake named comes after the push (below).
     `python3 audits/project.py --check-delivered` says whether each delivered file, README.md included
     (only stage5's `Pushed to …` lines, exactly as printed, may follow it), is still the one delivered
     (deliver again if not, unless it names a `RUN_LOG.md` delivery line edited or removed after
     delivery, which a new delivery cannot clear; a README no delivery line fingerprints is "not
     verified").
   - A re-approval still open (`REAPPROVAL.json`, begun and not closed by `signoff.py approve`) is never
     delivered (`PENDING[question]`: the freeze, part of the math gate; never a failure line, never a
     stop). When it is the human's question (`involved`, `statements-only`), wait for the human (never
     a stop, never a [PROXY] answer); when they answer, log it and approve as in
     `reapproval.md` step 4 (a rejected change: restore the approved statement first, "A rejected
     change" there), then prepare again, revise, and deliver. One the agent may close itself: close it
     (`signoff.py approve`) before delivering.
   - A `leave <decl> unproved` line logged after the final diff round (e.g. at delegated Checkpoint C)
     has no adjudication yet: `--deliver` notes it (`[adj-record]`). Run a diff round so its
     adjudicator checks it (when nothing changed for it to scope, `scope.py` exits 3 with
     `NEXT[full-round]`: a full round, `prompt.py 3 --full`), unless you judge otherwise and say why in
     `JUDGEMENT.md`.
   - A RUN_LOG.md line the missing-theory check suspects (`PENDING[adjudication]`, "may record a missing-theory
     decision outside the canonical form"), e.g. a delegated Checkpoint C line logged after the last adjudication:
     `--deliver` notes it (`[adj-record]`, "not judged by an independent agent"). If any such line is pending at
     delivery, run one full round before delivering (`scope.py` exits 3 with `NEXT[full-round]`: `prompt.py 3
     --full`); its adjudicator rules it (`MT RULED`); then run Phase 0, prepare again
     (`project.py --prepare-delivery`, the readers of the regenerated documents) and deliver. JUDGEMENT.md does not
     settle it: you wrote the line. The same holds for a line you dissented from (`MT DISSENT`) that no later
     round has re-ruled ("disputed by the operator; not re-ruled" in the documents): run one full round before
     delivering, so its adjudicator rules it again. A
     decision's reason need not describe the check: cite the decision by its anchor (a real missing-theory decision
     is still logged in its canonical form).
   - Commit the audits repo: your own files that changed (`RUN_LOG.md`, `AUTHOR_NOTES.md`,
     `DECISIONS.md`, `OUTCOMES.md`, `READER_NOTES.md`, `SUMMARY.md`, `REPORT.md`, `RUN_RECORD.md`,
     `JUDGEMENT.md`, `delivery-review/`) by name, never `git add -A` (RUN.md rule 5); every other record
     was committed by its script.
   - Push only if the intake said yes, after the last `--deliver` of the run (under `involved`, step
     7's). Unless 6c asked for the full history, push one clean commit, in ONE command (a shell
     variable does not survive between calls, and an empty hash would delete the remote branch). Each
     command starts at the project's top level, from any directory, and appends its `Pushed to …` line
     to `deliverables/README.md` once (a re-run adds no second copy).
     - The paper may be redistributed. `<parent>` is `<base_commit>` for the first push, else the
       clean commit pushed last:
       ```
       cd "$(git rev-parse --show-toplevel)" && H=$(git rev-parse HEAD) && T=$(git rev-parse "$H^{tree}") && C=$(git commit-tree "$T" -p <parent> -m "Formalization of <title> (<source id>). Tree of commit $H.") && test -n "$C" && git push <remote> "$C:refs/heads/<branch>" && L=$(printf 'Pushed to %s, branch %s, as commit `%s`: the tree of Lean HEAD `%s`.' '<remote>' '<branch>' "$C" "$H") && printf '%s\n' "$L" && { grep -qxF -- "$L" deliverables/README.md || printf '\n%s\n' "$L" >> deliverables/README.md; }
       ```
     - It may not (intake, Stage 0): the tree is built without the paper's files. `<paper paths>` are
       the paper's files or directories in the Lean repository (`paper/`, or wherever 1a put them).
       A path with a space or a shell character such as `( ) ~ '` is quoted in `git rm` and `git rev-list`;
       in the `printf` argument, already in single quotes, a `'` is written `'\''`. The `Pushed to` line
       quotes the paths in backticks.
       `P=` names the parent: empty for the first push, which has no parent (the base commit may
       already hold the paper) and goes to a new branch (onto an existing one it is refused as not a
       fast-forward); for a later push, `P=<the clean commit pushed last>`:
       ```
       cd "$(git rev-parse --show-toplevel)" && P= && H=$(git rev-parse HEAD) && I="$(git rev-parse --absolute-git-dir)/formalize-push.index" && rm -f "$I" && GIT_INDEX_FILE="$I" git read-tree "$H" && GIT_INDEX_FILE="$I" git rm -r -q --cached -- <paper paths> && T=$(GIT_INDEX_FILE="$I" git write-tree) && test -n "$T" && test "$T" != "$(git rev-parse "$H^{tree}")" && test -z "$(git diff --name-only "$H" "$T" -- '*.lean' 'lakefile*' lean-toolchain lake-manifest.json)" && { test -z "$P" || test -z "$(git rev-list -1 "$P" -- <paper paths>)"; } && C=$(git commit-tree "$T" ${P:+-p "$P"} -m "Formalization of <title> (<source id>). Tree of commit $H without <paper paths> (the paper is not redistributed).") && test -n "$C" && git push <remote> "$C:refs/heads/<branch>" && L=$(printf 'Pushed to %s, branch %s, as commit `%s`: the tree of Lean HEAD `%s`, without `%s`.' '<remote>' '<branch>' "$C" "$H" '<paper paths>') && printf '%s\n' "$L" && { grep -qxF -- "$L" deliverables/README.md || printf '\n%s\n' "$L" >> deliverables/README.md; }
       ```
       Nothing is pushed when: a path is mistyped (`git rm` fails); the tree still equals HEAD's; it
       lacks a Lean or build file HEAD has (a path such as `.` or the Lean directory); or the parent's
       history holds the paper (a wrong `P`, such as the base commit). Find the paper's tracked paths
       with `git ls-files`, which also shows a second copy of it elsewhere; if none is the paper's, the
       first command is the one. If 6c asked for the full history, push this clean commit instead, and
       say so in the completion message, with the command for the history push if the person still
       wants it. This covers the Lean repository only: its docstrings quote the paper's statements,
       and the audit record (6d) quotes passages of it; say so in the completion message when 6d
       allows a push.
     Every step is `&&`-chained: a failed step pushes nothing. Copy the printed `Pushed to …` line into
     `RUN_LOG.md` and the completion message. The documents cite the Lean commit (README's "Delivered
     from Lean HEAD"; SUMMARY and REPORT the last commit that changed a Lean or build file, whose Lean
     files the pushed tree holds); the line the command appends to `deliverables/README.md` maps it to
     the pushed commit. If you run `--deliver` again later (it rewrites README.md), append that line
     again, copied from `RUN_LOG.md` (never retyped). Push again only if the Lean changed. Anyone can
     check the push: `git diff --name-only <pushed> <the Lean HEAD named in the line>` prints nothing,
     or only the paper's files. A later push's parent that git no longer finds (no local branch keeps
     it): `git fetch <remote> <branch>` brings it back. The local branch keeps every commit. Never
     force a push: if the remote refuses, say so in the completion message with the command to run.
     If a permission prompt or the auto-mode classifier denies the push command, that is not a stop:
     put the exact command, filled in, in the completion message for the person to run from the
     project, as under Codex (`codex.md`).
   - If the intake named another destination, copy the files there after the push, so that the copy
     carries the push line (`cp`), or tell the human where they are.
6. **Checkpoint C, or the completion message.** Under `involved`, Checkpoint C is asked on the
   documents written and reviewed in step 5, before anything is delivered
   (U2 §6.7). Send the human a short message:
   where `SUMMARY.pdf` (read it first), `DECISIONS.md`, `REPORT.pdf` and `SIGNOFF.pdf` are, each with its
   markdown beside it (in the rounds directory: nothing is delivered yet); the number of decisions; whether the statements were approved by a human or by
   the agent; the outcome lines `render_record.py next` printed for each PDF (`DONE[render]`: every
   remaining objection, every checker finding, and the renderer's NOTE lines), verbatim; and the
   delivery reviewers' findings you declined, with your reason (`JUDGEMENT.md`). The decisions themselves
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
   and, as above, the reviewers' findings you declined, and every note `--deliver` printed that you left
   as it is, with your reason. End it with these
   reversal instructions, filled in: "To reverse a decision, open Claude Code in
   `<project path>` and say: *Read audits/RUN.md; reverse `<anchor>` in DECISIONS.md.* The table
   at the top of `<path to DECISIONS.md>` gives each decision's anchor and what reversing it
   costs (none, re-prove, re-approve or new round); its section says what will be rerun." Add the
   K line (next batch D1), filled in from your SUMMARY's K line: "In the formalizing agent's judgement,
   K is reached for X of N results (<the reason in a few words>). The open K gaps are listed
   in REPORT, section "K certificate" (not repeated here). Reply **K** to go through them one at a
   time; otherwise this delivery stands." The run is then complete. A later reversal the human asks
   for is new work: record their words verbatim and carry it out by step 7. (Under `involved` there is
   no K reply: the open K items that remain are listed in the Checkpoint C message and answered there
   like any other item.)

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
   5. Check the documents (step 2), then step 5: prepare again, revise your documents from the new
      facts, review what changed as you judge it needs, render again only the documents whose markdown
      changed, and deliver.

8. **The K stage** (`statements-only` and `hands-off`, on the human's reply `K` after the completion
   message; next batch D1). It is a later reversal, generalised, and bounded:
   1. `python3 audits/project.py --k-stage` (it logs `- K stage begun <date> after round <R>: human
      reply "K"` under `## K stage`, sets the stage "Stage 5 — K stage" and commits RUN_LOG.md).
   2. Ask the open K items **one at a time**, in REPORT order, in plain words (what it is, the options,
      what each costs); record each answer verbatim under `## Answered` as `- answered C<n> (<date>, K
      stage): "<words>"`. An item the human declines stays open; "stop" ends the K stage (the delivery
      stands).
   3. Carry out each answer: a bridge → prove it (a pure addition) or accept it as open; a reading →
      formalize the human's reading (a statement change: re-approval; or a pure-addition theorem for
      the other reading); a source-def or finding → as answered (a change of an approved statement:
      re-approval, `reapproval.md`). Under `statements-only` the human approves (`--by human`). Under
      `hands-off`, `approve --by human` is refused unless an earlier approval was the human's, so record
      the human's K answer verbatim under `## Answered` and `## Re-approvals` and close the re-approval
      with `signoff.py approve --by agent` (the replaced approval was the agent's); the documents say the
      change was made on the human's K answer and approved by the agent.
   4. Re-prove and re-review only what changed: Phase 0, then diff round(s) on the changes (a
      re-approved statement: its statement round(s) and the existing full round after a re-approval).
      The K stage's rounds have their own cap of two diff rounds after the round its `K stage begun`
      line names (`project.delivery_rounds`).
   5. Re-deliver as in step 7.5, the K certificate updated, and send the completion message again with
      the new X of N.
   The run is already delivered, so a wait for an answer blocks nothing; the delivery stands if the
   human never replies.

## Delivery reviewer prompt

Spawn four fresh general-purpose agents (step 5, "Review"), one per perspective, each with this text, the
placeholders filled in (`<PERSPECTIVE>` is one of CLAIMS, READABILITY, DECISIONS, TRUST; paths absolute), and,
after the first `--deliver`, the NOTES reviewer (step 5, "Deliver") with `<PERSPECTIVE>` NOTES.
Never give a reviewer your own notes, `JUDGEMENT.md`, the facts draft or another reviewer's findings (the
code-written notes in the delivered `RUN_RECORD.md` are the checking program's, not yours).

```
You are ONE independent reviewer of the documents a formalization run delivers to a paper's authors. You
advise; the main agent decides. Nothing you say stops the run.

Context: a run of formalize-paper (Lean 4 + Mathlib) on the paper <PAPER (authors, title, arXiv id)> has
finished the mathematics: the statements are approved and frozen, and the proofs are machine-checked (the
build passes, no `sorry` in a result called proved, standard axioms only). The main agent wrote SUMMARY.md
and REPORT.md for the authors -- research mathematicians who know the paper but neither Lean nor the tool --
and corrected RUN_RECORD.md and DECISIONS.md.

Read the deliverables: <ROUNDS>/SUMMARY.md and <ROUNDS>/REPORT.md (and <ROUNDS>/DECISIONS.md,
<ROUNDS>/RUN_RECORD.md as your perspective needs). As needed, read the run's records under <ROUNDS>
(ADOPTED.md of each round, PAPER_DEFECTS.md, SKIPPED.md, VACUOUS.md, DEVIATIONS.md, UNUSED_ARGS.md,
DEPENDENCIES.json, RUN_LOG.md, the stops/ and tool-patches/ directories), the paper (<PAPER PATH>) and the
Lean source (<LEAN FILES>), read-only. Do not read <ROUNDS>/JUDGEMENT.md, <REPO>/deliverables/JUDGEMENT.md,
<ROUNDS>/facts/ or <ROUNDS>/delivery-review/: judge independently. Change nothing.

Your perspective is <PERSPECTIVE>:
- CLAIMS: does any sentence say more than the records and the Lean support? Check every result's status
  against the Lean (is it really proved without `sorry`? is every assumption it rests on stated?) and the
  records (the adjudicators' decisions in ADOPTED.md, RUN_LOG decisions, PAPER_DEFECTS/SKIPPED/DEVIATIONS).
  An overstatement is must-fix. Also report understatement (minor). If <ROUNDS>/CONDITIONS.md lists
  known issues (kind `known-issue`), does the summary say how each was handled (never "no defect" alone)?
  Check REPORT's section "K certificate" and SUMMARY's K line, both written by the formalizing agent and
  labelled as its judgement: is each result's K1–K4 mark right, with a reason and file:line evidence that
  hold against the paper, the Lean and the records? Is the count right? Is every open K gap listed (an
  open bridge, reading, source-def, finding or condition item in <ROUNDS>/CONDITIONS.md or an
  adjudicator's `## Conditions` row; an unproved change of representation; a generalization), each with
  the results it actually affects (an item on a helper lemma affects only the results whose proofs use
  it; check the Lean and DEPENDENCIES.json)? A K mark or count that says more than the evidence is
  must-fix.
- READABILITY: you are a research mathematician who has never heard of the tool or of Lean. Is SUMMARY clear
  on first reading? What would confuse, bore or mislead you? What would you want first? Is any jargon
  unexplained?
- DECISIONS: is every decision taken on the authors' behalf listed, accurately described (who decided, on
  whose recommendation), with a correct reversal cost? Is every reading choice whose QUESTION no person
  answered also asked of the authors as a short question in SUMMARY? Is any question to the authors
  outside a `scope` item of <ROUNDS>/CONDITIONS.md? Check against RUN_LOG.md, DECISIONS.md and the
  adjudicators' records.
- TRUST: do the statements about what was machine-checked, reviewer-checked and unchecked match what the
  records show? Is anything claimed checked that was not, or a blind spot omitted? If the run had no
  network, do the trust lines say that cited results were compared only with the copies in SOURCES.md and
  that their published numbering was not checked?
- NOTES: read the code-written notes in <REPO>/deliverables/RUN_RECORD.md, section "Notes at delivery" (written
  by the checking program, not by the main agent). For EVERY note return one line `- <id>: real problem | no
  problem | cannot tell -- <why, citing the record, the Lean or the delivered document>; <what should be done>`
  (the id as the note's `[n…]` gives it), and nothing else. This overrides the format below: no numbered
  list, no severity, no overall verdict, any length.

Return your findings as your final message, as text (do not write files: a subagent's file write is often
refused). Unless your perspective is NOTES: a numbered list, each finding: severity (must-fix / should-fix /
minor), the exact sentence quoted, why (cite the Lean file:line or the record), and a suggested fix. Then one
line: overall verdict. Keep it under about 800 words.
```

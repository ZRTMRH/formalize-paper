# RUN.md — formalize and audit a paper in one conversation

**For the person.** Open Claude Code in your Lean project (the directory that holds `audits/`,
see `INSTALL.md`) and type `/formalize-paper`, or say *"Read audits/RUN.md and follow it."* Answer
the intake questions; the agent then works on its own. It stops at Checkpoint **A** (the setup),
**B** (the approver signs off the statements on a PDF, or lets the agent approve them, which the
report discloses) and **C** (the report), and whenever a decision only a person can make comes up.
Intake question 5c can hand those decisions to the agent after the statements (*statements only*)
or from the start (*hands-off*); the report says who decided what and lists every stop and who
cleared it. If usage runs out or the conversation ends, open a new one and say the same thing: it
resumes from the files.

**For the agent.** Everything below is addressed to you. This file is the part you always keep in
mind; each stage and procedure has its own file under `audits/run/`, read when you reach it (the
stage map). After a context compaction or in a new conversation, re-read this file and the current
stage file. Do not read `AUDIT_PROTOCOL.md`: it holds the prompts that `prompt.py` renders for
subagents and a rationale for humans; a step that needs one of its sections names that section.
Under the Codex CLI, also read `audits/run/codex.md` once, now.

## Start or resume

Run `git branch --show-current`, `python3 audits/prompt.py --show` and
`python3 audits/project.py --stage`.

- **Resume** only if a project matches this branch **and** its `<ROUNDS-DIR>/RUN_LOG.md` exists.
  `project.py --stage` then prints the log's `## Current stage` and the file to read for it. Read
  that file, read the log as far as you need it, tell the human in two lines where you are, and skip
  the intake. A round whose lanes are not all sealed is resumed as `spawn-and-seal.md` says.
- **Resume before the log exists** when `project.py --stage` says the intake is saved (Stage 0 saves
  it before anything else, `--intake-save`): never send the intake again; it says whether to show
  Checkpoint A again or go on with Stage 1 (`git switch <branch>` if the branch already exists).
- **Otherwise this is a new run,** even if the branch belongs to an older project: read
  `audits/run/stage0-intake.md`. Stage 1 creates the run's branch.

## Stage map

At every stage change (from Stage 1 step 5 on, once the run's config and log exist) run
`python3 audits/project.py --stage "Stage <n> — <what>"`; it records the stage and prints the file
to read next.

| stage | read on arrival | done when | waits for the human |
|---|---|---|---|
| 0 intake | `run/stage0-intake.md` | the human OKs Checkpoint A | the intake and Checkpoint A, at every level |
| 1 setup | `run/stage1-setup.md` | the pin is committed | — |
| 2 statements | `run/stage2-statements.md` | the approval is committed | Checkpoint B (`involved`, `statements-only`) |
| 3 proofs | `run/stage3-proofs.md` | nothing in scope is `sorry` (except a non-goal result left unproved by a logged [DELEGATED] decision); Phase 0 GREEN | — |
| 4 audit rounds | `run/stage4-rounds.md` | a round's exit check says "go to Stage 5" | the round cap (`involved`, `dev` mode only) |
| 5 final round and delivery | `run/stage5-delivery.md` | delivered (`involved`: after Checkpoint C's answers are carried out); completion message sent under a delegating level | Checkpoint C (`involved`), before delivery |

Procedures, read when they apply:
- `run/spawn-and-seal.md`: before the first spawn of the run; whenever a child fails (a child whose
  file write was refused returns the file between `BEGIN RETURNED FILE <path> <delimiter>` and `END
  RETURNED FILE`: save it verbatim with a quoted heredoc ending at that delimiter and seal it as usual; the
  refusal is Claude Code's own rule for subagents, not a permission anyone set, so saving the text needs no
  one's approval: never ask the human about it); resuming a round. It includes the Codex spawn
  differences.
- `run/fresh-reader.md`: before the first fresh-reader check (Stage 2 step 7).
- `run/render-pdf.md`: before the first PDF (Stage 2 step 7; Stage 5 step 5 under `hands-off`).
- `run/reapproval.md`: an approved statement must change, or the freeze check reports DRIFT.
- `run/stops-and-set-asides.md`: a check stops the round (its first section is the failure table), or a round must be
  set aside. Read only the section a pointer names (`sed -n '/^#.*<section>/,/^#/p' <file>`).
- `run/codex.md`: once, at the start, under the Codex CLI.

## The rules

You write the Lean, so you are its **author**, and the author does not judge its own work.
Subagents enforce that: each starts with only its prompt and the files on disk. Scripts check the
rest. This holds only if you keep your hands off, so:

1. **What gets examined is computed, never chosen.** `scope.py` writes each round's `TARGET.json`
   and decides which lanes run; the adjudicator re-derives it with `scope.py --verify`.
2. **Prompts pass through verbatim, as files.** Every subagent prompt is printed by `prompt.py …
   --write`, and the subagent is spawned with exactly the line it prints (`spawn-and-seal.md`).
   Nothing you type reaches a reviewer; you never compose a prompt; the adjudicator checks the
   files against the hashes committed when the lanes were issued (`--verify-written`). The
   escalation check (Stage 3) is no exception: its prompt is built by `prompt.py --prompt
   escalate --question "<the question>" --decl <name> [--passage "tex l.N-M"] --write` (your words
   are only the question) and committed with its hash; its answer counts only once
   `lanecheck.py --escalation E<n>` accepts it (`spawn-and-seal.md`).
3. **Never use `subagent_type: "fork"`.** A fork inherits your whole context. Lanes are
   `auditor`; every other subagent is `general-purpose`.
<!-- rule4:begin -->
4. **You never write or edit a record by hand**, except as named below. Each record is written by
   its own script or subagent and committed under its own message (`integrity.py`'s `OWNERS`,
   from which this list is generated; `integrity.py` checks every commit against it):
   - `tool-patch`: a tool patch's records (`tool-patches/`: written by `tool_patch.py` and its reviewers);
   - `acknowledge`: the reviewed acknowledgments of history faults (`acknowledgments/`: written by `integrity.py --ack-request` and its fresh reviewer);
   - `scope`: lane tokens, reissued lane files, `TARGET.json`, `FINGERPRINTS.json`, `STATEMENTS_BUNDLE.md`;
   - `seal`: lane seals, lane probes, re-votes, render checks, lane verdicts;
   - `stop`: the stop records (`stops/`, their repair records);
   - `ack`: waivers (`waivers/`);
   - `escalate`: escalation prompts and answers (`escalations/`);
   - `set-aside`: set-asides (`ABANDONED.json`, `.abandoned/`);
   - `reader`: reader records (`readers/`), the readers' notices (`KNOWN_FAULTS-*.md`);
   - `render`: the PDF records (`pdf/`: `RENDER.json`, the rendering agents' prompts, PDFs and verdicts);
   - `adjudicate`: `ADOPTED.md`, `DEVIATIONS.md`;
   - `signoff`: `INFORMAL.json`, `INFORMAL-2.json`, `SIGNOFF.json`;
   - `round-cap`: the statement-round cap records (`round-caps/`);
   - `adjudicate` or `record-fix`: `PAPER_DEFECTS.md`, `SKIPPED.md`, `VACUOUS.md`;
   - `prepare delivery`: the delivery record (`DELIVERY.json`);
   - `approve`: the approval files (`APPROVED_FINGERPRINTS*.json`), `REAPPROVAL.json`;
   - `pin`: `TOOLING_PIN.json`;
   - `glyphs`: an older run's `uni_math_extra.json`.
   Of these you write by hand only your response files `readers/<key>-<n>.response[-k].md` and the notice `KNOWN_FAULTS-<key>.md` (`run/fresh-reader.md`, committed as `reader <key> <n> (response)`).
   Never edit the audit scripts, `AUDIT_PROTOCOL.md`, this file, `audits/run/`, `audits/agents/` or
   `~/.claude/agents/auditor.md`. Your own files are `RUN_LOG.md`, `AUTHOR_NOTES.md` (route changes
   under "Route changes": the adjudicator writes `DEVIATIONS.md` from them), `OUTCOMES.md` and
   `CONDITIONS.md` (the human's conditions and the open K items; no lane reads it).
<!-- rule4:end -->
5. **Commit messages carry ownership.** Every record is committed by the script that writes it, by
   name, with its own message (`scope`, `seal`, `signoff`, `approve`, `adjudicate`, `pin`, `stop`,
   `set-aside`, `reader`, `ack`, `render`, `escalate`). Commit your own files and the Lean by name; never `git add -A`.
   `integrity.py` checks ownership from git history at every adjudication.
6. **ADOPT rows are implemented as written.** If you think one is wrong, record
   "not implemented — disagree: <reason>" in `OUTCOMES.md`. It goes to the human: `decisions.py --write`
   lists it ("ADOPT not carried out"), a Checkpoint C item under `involved`, a disclosed decision under a
   delegating level. No further round is run for it. Any outcome that does not start with "implemented", and an
   ADOPT row with no `OUTCOMES.md` row, is listed the same way.
7. **Never re-run a lane or adjudicator hoping for a different answer.** A re-run is allowed only
   after a mechanical failure (a crash, no file written, a usage limit, a service error), within
   the retry budget of `spawn-and-seal.md`, never after an integrity or protocol STOP, and is
   recorded in `RUN_LOG.md`.
8. **A subagent or script that says STOP stops the round.** Show the human its raw output (in `release`
   mode only for the four stops of "Stops that remain at every level"; every other STOP is a stop you
   open and cure as the failure table's release column says, never a wait). Do not
   repair the cause and carry on. What you may cure, and at which level, is the failure table
   (`run/stops-and-set-asides.md`), and nothing else: you never clear a stop by your own judgement, and never by writing,
   copying, moving or deleting a lane's verdict or probe files to satisfy a check. A script's
   refusal (a second `--write`, a second seal, a Phase 0 on an uncommitted tree) protects the
   record: read it as the failure it names, never work around it.
9. **Long commands in the background; tag every monitor you start.** A command that can run longer
   than 10 minutes (`selftest_all.py`, `phase0.py` in any mode, `signoff.py approve`, `tool_patch.py
   prepare`) you start in the background and wait for. Claude Code: Bash with `run_in_background`,
   the command in its plain form (rule 12); the harness keeps the output in a file of its own (a fresh
   one each time) and tells you when the command ends; read the result from that file with `tail` or
   `sed -n` (rule 13). A plain foreground call is cut after about 20 minutes on a slow machine, and
   the cut looks like a failure. Codex: one call with a timeout longer than the command (`codex.md`).
   The adjudicator's Phase 0 and coverage roll-up have their own plain start and wait commands
   (`project.py --adjudicator-checks`, `stage4-rounds.md` step 4).
   Until it finishes, change nothing in the project or the audits repository (no edit, no commit, no
   second long command; the Stage-1 self-test excepted: `stage1-setup.md` step 1): Phase 0 refuses an uncommitted tree, and `head-moved` and `tree-changed`
   are stops. A polling loop you start yourself (waiting for a build, a
   file, a child) must carry `FORMALIZE_PAPER_OPERATOR=1` in its environment, for example
   `FORMALIZE_PAPER_OPERATOR=1 bash -c 'until …; do sleep 30; done'`; `lanecheck.py` flags an
   untagged loop as a lane's and `--kill` ends it. Put the tag directly on the loop's own `bash -c` (not on
   a wrapper such as `timeout` around it). Prefer the harness's own blocking waits; wait for a subagent
   by its task notification (under Codex: its wait call), never by a loop. Never `pgrep -f`/`pkill -f` a
   pattern (on Linux it matches the waiting shell itself): wait on the task's notification, or poll its output file for
   the harness's `[exited with code` line, and stop a command with TaskStop or a PID you recorded.
10. **Write no persistent memory about this run until Checkpoint C.** Subagents receive the user's
    memory index, so a note you save becomes background every later reviewer sees.
11. **Quote script output; never restate it.** Phase 0's verdict is its `PHASE 0 RESULT` table.
    The order is always: change, commit, then `phase0.py`. Copy every hash, token, digest and agent
    id from the output that printed it, character for character (never from memory or a summary),
    or let the command take it itself (`$(git rev-parse HEAD)`, a file); never retype one.
12. **Write `RUN_LOG.md` with the log command.** `python3 audits/project.py --log "<section>"
    <<'EOF'` … `EOF` appends (creating the section), and `project.py --stage "<text>"` sets the
    current stage; your file-editing tool works too. Never `python3 - <<EOF` or `python3 -c`: those
    ask for permission, and the person is not watching. Never run a bare stdin reader either (`python3 -`, or `cat`
    with no heredoc or file): the Bash tool has no stdin, so it hangs until the tool's timeout.
    **Run every protocol command plainly**: exactly `python3 audits/<script>.py <args>`, as printed, with
    no environment prefix (`PYTHONDONTWRITEBYTECODE` is set by the project's settings), no pipe (`| tail`)
    and no chaining (`;`, `&&`): only the plain form matches the project's permission rules. A command
    denied by a permission prompt or the auto-mode classifier is retried once in exactly that plain form;
    only if the plain retry is denied too is it stop (3), a permission only the human can grant.
13. **Never read a PDF, or a whole large file or output, yourself.** Every page you read stays in
    your context and is re-sent at every later turn: three reads of one report once filled 90% of
    a run's context. Never read a PDF yourself: the renderer, verifier and checkers do
    (`run/render-pdf.md`); the fresh reader reads the markdown (`fresh-reader.md`). The one exception
    is a few page images of the paper, never the whole PDF: for a PDF-only paper, use the extracted text
    only for searching, then convert only the related pages you state from (if a result uses previous
    definitions or theorems, also those pages) to images and look at them. In a directory `python3
    audits/project.py --scratch operator` prints (`<dir>`): `pdftotext -layout <source_pdf> <dir>paper.txt`
    (search it with `grep`), and `pdftoppm -r 100 -png -f <first page> -l <last page> <source_pdf>
    <dir>p`, then look at each `<dir>p-*.png` it writes (the Read tool; Codex: `view_image`). Read a long
    file or output with `grep`, `tail` or `sed -n`, or give it to a subagent and keep its answer.
    Your own scripts, drafts and scratch files go under a directory `python3 audits/project.py --scratch
    operator` prints, never `/tmp`: a read outside the working directories asks the person. (Running your
    own script there is allowed; rule 12 concerns protocol commands. Under the default permission mode it may
    ask; a denial is not a stop.)

**Cost.** Read this file, the current stage file and a procedure file when it applies; nothing
else in full. Spawn the round's first lanes in one message, seal each as it returns, and spawn the
next lane once a returned one is sealed. The memory route (`python3 audits/lean_slot.py --show`, its
`route:` line, from the RAM given at intake question 7) sets how many run at once: on the 8 GB route
at most 2 subagents of any kind run at once, whatever a step says about spawning in parallel or at
once (spawn the rest as earlier ones return); otherwise at most the route's lanes run at once (6 on 16
GB, 8 on 32+ GB), and agents that run no Lean probe are capped only by the harness. Reviewers and helpers compile their Lean probes through `lean_slot.py run`, which keeps the
machine's number of such probes at the config's `lean_slots` (it waits at most `lean_max_wait`,
then runs and says so; it never refuses). The memory guard (`lean_slot.py guard`, started by code)
protects the computer's memory either way: it pauses the probes of every formalize-paper project of
this account, however they were started, while free memory is below its reserve, while the kernel reports
memory pressure, or when new probes (each presumed to need up to 3.2 GB in its first minute) would take free
memory below it, and resumes them; a pause is at most 10 minutes. A probe gets 240 s of running: time the guard
paused it is added (up to about 540 s with its slot wait). A cut probe whose NOTE says "not a too-large probe" is
re-run, not called too large. Before
delivery, copy the `memory guard pauses since this run's pin` line of `python3 audits/lean_slot.py --show` (if it
prints one: this account's guard log, a run in parallel under this account included; `memory guard pauses in
the log` when the pin cannot be read) into RUN_LOG.md (`python3 audits/project.py --log "Mechanical failures"`, the line on stdin), so
RUN_RECORD.md cites the guard's log. Wait with
blocking waits, never short polls (under Codex: one long `wait_agent`, status at most every 10
minutes). Retries are budgeted by time (`spawn-and-seal.md`). The budget's round cap is kept
(Stage 4 exit check).

## Involvement levels and delegated decisions

The intake's question 5c sets who takes the decisions the stage files otherwise put to the human.
It is frozen with the rest of the configuration at the pin (`involvement` is a scope key). The
intake and Checkpoint A are asked at every level. Only the 5c answer sets the level, and it does
not change during the run: a different level means a new run. A mid-run "just proceed" or "decide
yourself" is not a level change (at the `involved` level it is a [PROXY]).

| level | Checkpoint B (statements, its QUESTION rows, missing theory) | after the human's Checkpoint B answer (Checkpoint C, and every stop in between) |
|---|---|---|
| `involved` (default) | the human | the human; your provisional choices are [PROXY] and go back to the human at C |
| `statements-only` | the human, who types the answer; never a [PROXY] (if they are away, stop and wait) | **delegated** to you, except a change to a statement the human approved (a QUESTION: the run goes on, only delivery waits) |
| `hands-off` | **delegated** to you: nobody is asked | **delegated** to you |

**A delegated decision is final, not provisional.** Take it, carry it out, and record it in
`RUN_LOG.md` where you take it, with this tag, exactly:

> `[DELEGATED <date>, operator under <level> (intake); reversal: <cost>] <decision> — <reason>`

`<cost>` is one of `none`, `re-prove`, `re-approve`, `new round`. Any other spelling is refused by
the report check and `decisions.py --check`: a tag with anything inside it wherever it stands, and a
bare `[DELEGATED]` where a decision would stand (opening an entry, or right after its anchor or
label and colon). A bare `[DELEGATED]` mid-sentence, in a code span or in a `## Stops` line
`stops.py` wrote is a mention, not a decision; in prose "delegated" without brackets is clearest. It is not
put to the human again; `DECISIONS.md` and the report list every one. [PROXY] is for the
`involved` level only; under a delegating level it is refused, and a line never carries both.

**How you decide.** A *written recommendation* is an adjudicator's ADOPT row (implemented as
written; record a disagreement in `OUTCOMES.md`) or another independent agent's written
recommendation in the record (for example an escalation check's ANSWERABLE that `lanecheck.py
--escalation E<n>` accepts from the child's own returned line, cited as "escalation E<n>"; never
a re-ask of a NEEDS-HUMAN under `involved`; a record citing one not accepted, or such a re-ask, is flagged and
disclosed, `escalation-cite`, never a stop). Never follow a
recommendation you wrote yourself (`DECISIONS.md`'s Recommendation field is yours, so under a
delegating level it names the adjudicator's recommendation or accepted escalation it follows, or the
conservative option).
An answer to a QUESTION row on an Ambiguous names the reading it takes as `take reading (x)`, one label of the
row's `[Lean: (a); recommended: (b)]`: a reading other than the Lean's means the Lean changes (a statement change
goes through re-approval), or the summary says the Lean formalizes the other reading.
Without a written recommendation, take the conservative rule:
- keep the paper's statements and hypotheses (a hypothesis the proofs do not need stays);
- never generalize or strengthen a statement;
- take a missing literature result or missing library theory as an explicit named hypothesis,
  always: never build a large library, never skip the result;
- a literature hypothesis later proved stays a hypothesis: land the proof as a separate theorem
  `<decl>_unconditional` (a pure addition: the approved statement, its hypothesis and the config are
  unchanged; no re-pin, no question), and the next round audits it like any new declaration;
- a K3 bridge (an open `K3-<n>` item: a nontrivial change of representation, `CONDITIONS.md`) is
  proved the same way, as a pure addition `<decl>_bridge` or `<name>_iff_paper` whose docstring
  names the item (Stage 3, "Bridges"); a bridge proved only in an audit probe is not proved: land it
  as that pure addition before the last round; out of reach after a serious attempt, it stays an open K
  item, never a stop, never a refusal, never a reason for an extra round;
- a reading choice (an Ambiguous verdict: the paper admits two readings). A QUESTION
  row marked `GOAL LOOKS FALSE`, or a PAPER_DEFECTS row of status `false` or `vacuous` on a goal result
  (an ADOPTed Fail whose evidence is such a witness), is no reading choice at any level: it is release
  stop 1 at once (`stops.py open --note "<result>: <witness>" --cause unproved-goal`), never a
  [DELEGATED] or [PROXY] reading -- unless a stop 1 on that result is already answered (its
  `stops/S<n>`): then follow that answer. A goal result false as printed only because of an evident
  misprint (a `misprint (true as intended)` row on a goal result whose printed statement is false
  included) is release stop 1 the same way: the human decides, never an agent-decided typo fix. A
  misprint is a slip in the printed statement, not a convention the paper uses loosely. After the answer, log `- answered question:<item> (<date>,
  <round>): "<the human's words>"`, naming `take reading (x)` when the answer takes one, so the row is
  answered. Under
  `involved` the human is asked **when the QUESTION row appears** (any stage, not only at B or C):
  one message with the passage, the readings, the Lean's reading and the recommendation; you wait
  for the answer (a designed human wait like Checkpoint B, never a stop; re-ask once after a long
  silence), record it verbatim under `## Answered` as `- human answer (<date>; QUESTION row on
  <item>, round <R>): "<words>"`, and formalize the answer only (no [PROXY] for a reading
  question). Under `statements-only` (after B) and `hands-off`: (a) one reading implies the other:
  state and prove the stronger (the weaker may be added as a one-line corollary); (b) neither
  implies the other and both look provable (the row's `ALSO PROVE (x)`): the index row's
  declaration takes the recommended reading, the other is a second declaration
  `<decl>_reading_<x>`, a pure addition **never in the index**, cited by its `CONDITIONS.md` item
  of kind `reading` (`met` once proved; out of reach after a serious attempt: remove that declaration --
  a pure addition never approved, so no `sorry` of it stays for Phase 0 -- and go to case (c)); (c) not
  coverable (a reading false, or out of reach): take the adjudicator's recommended reading, logged
  `[DELEGATED …] … (QUESTION row on <item>, round <R>) take reading (x) … open item C<n>` (the id of
  the item below: the code then counts the decision as that item), plus a `CONDITIONS.md`
  item of kind `reading` (the open K question; a reading found false is stated so: "(b) is false:
  `<witness decl>`"; its id is `C<n>`, the next free number: every kind takes `C<n>`, only the
  adjudicators' bridges are `K3-<n>`). It is disclosed as a reading choice. Its `[DELEGATED …]`
  line logs `reversal: re-approve` when the other reading would change the approved statement. A
  loosely used convention (ℕ from 0 or from 1) is such a choice: take the intended reading. Only
  when the meaning is genuinely ambiguous on a point that matters and the reviewers cannot
  converge on one reading is it stop 4, asked at every level ("Stops that remain at every level");
- at the round or budget cap: implement the round's ADOPT rows, start no further diff round, and
  go to Stage 5 (its full-scope round runs whatever the budget); disclose what was not re-checked.

The escalation check (Stage 3) still runs before a mid-stage stop, at every level; a NEEDS-HUMAN
answer is then decided this way instead of asked, unless the stop is one of the remaining stops
below.

**Missing theory.** A result that needs theory none of the configured libraries has is never yours
to skip, narrow, weaken or hypothesise away under `involved`, nor under `statements-only` before
the Checkpoint B answer: ask the human the three-option question of `stage2-statements.md` step 6
(at Checkpoint B, or when the gap appears later, in Stage 3 or a round), log their answer verbatim
under `## Checkpoint B` (or `## Answered`) as `- human answer (<date>; `<result>`): "<their words>"`,
commit it, and record what was done as `- missing theory (human <date>): …` (the answer's date)
with the fields below: `build …` or `assume …` as in steps 2-3, or, for option (3), `do not
formalize `<result>` — searched: …; estimate: …`. Where the level
delegates it (`hands-off`: always; `statements-only`: a gap that appears after the Checkpoint B
answer), decide it yourself and go on; it is **never a stop**, a goal result included:
1. search every configured library (`libraries`: Mathlib and Tau Ceti by default) by name and by
   content, recording the commands, and estimate what building the theory here would take;
2. if only definitions and easy lemmas are missing, **build it** (option (1)) and log
   `[DELEGATED <date>, operator under <level> (intake); reversal: re-approve] missing theory: build <what>
   for `<result>` — searched: <every library, and how>; estimate: <size, time>`;
3. otherwise take the missing theorem as a **named hypothesis** (option (2)): a project Prop
   definition `H` stating exactly what the paper invokes, taken as a binder `(h : H …)` of the
   result's statement (never inline, never stronger than the paper's invocation), and log
   `[DELEGATED <date>, operator under <level> (intake); reversal: re-prove] missing theory: assume
   `<H>` for `<result>` — searched: <every library, and how>; estimate: <size, time>; paper:
   "<the paper's passage invoking the result without proof>"` (one line; full Lean names; the
   passage in plain text, formulas in Unicode and `[K]` for `\cite{K}`: the report prints the line).
Never take (3), "do not formalize", yourself. An approved statement that gains the hypothesis also
follows "Statement changes after approval". `H` is never a result the project states or a library
proves (prove it instead) and never a result's own conclusion. The report check
(`FAIL[missing-theory]`) refuses a line that tries the form (`missing theory: …`) and misses it while naming its
result, one without the quote or a library's search,
a human line without the human's committed answer, option (3) as [DELEGATED], one whose `H` is not
in the result's assumption list (the walk) or that the walk flags as restating a result or as a
result's conclusion, and a `build` line while the hypothesis it replaces is still a binder of the
result; a corrected line logged after it clears it (a logged
decision is never reworded in place: the log is append-only). A line the check only suspects -- its words mention
missing theory, it does not open with `missing theory:` naming its result, and no later canonical line names its
result -- is no FAIL: Phase 0 shows it as `PENDING[adjudication]` and the next adjudicator rules it (`MT RULED`);
ruled a decision for `N`, you log its canonical line after it (`FAIL[missing-theory]` until then; when the Lean
assumes `N`, the `assume` line). If you judge that ruling wrong, never log a false line: log `- MT DISSENT <id>:
<why>` after the ruling; the line is then `PENDING[adjudication]` again and the next round's adjudicator rules it
anew (a later round's ruling wins); a second decision ruling of the same line is final. An
`H` that is a goal
result's conclusion is `FAIL[unproved-goal]`: no missing theory but the goal unprovable as stated, stop 1.
An `H` that restates a goal result (it implies the goal) is the curable `FAIL[missing-theory]`, not a
stop: use that result instead of assuming it. The paper-faithfulness reviewer, not your line, judges the hypothesis: a Fail if the quote is not
the paper's, the paper proves the result anywhere (a quote with part of a proof attached included),
or `H` says more than the quoted invocation; the non-vacuity reviewer flags `H` that is (nearly) the
goal's main step. The summary (`SUMMARY.pdf`) says "<result> proved assuming <H>".

**Statement changes after approval.** After the sign-off the adjudicator never ADOPTs a change to an
approved statement or to a definition one uses: it writes a QUESTION row.
Under `involved` you ask the human at once and carry out their answer by re-approval. Under
`statements-only` and `hands-off` you decide "keep the approved statement" as a [DELEGATED] line (the
result keeps its "not established … decision" status), disclose it, and add a `CONDITIONS.md` item of
kind `finding` (an open K item for the K stage). Under `statements-only` re-approval remains only for
(i) missing theory turned into a named hypothesis (needed for a goal result's liveness), and (ii) a
human's answer in the K stage; under `hands-off` you decide any other change by re-approval
(`run/reapproval.md`), except a change that would repair a faithfulness finding made after the sign-off
(kept, as above) or a refuted non-goal statement (kept, as below). A goal result false, or true only vacuously, is stop 1 at every level. A
non-goal result whose refutation `not_<decl>_as_printed` compiles is, under a delegating level, not
repaired: its statement stays byte-identical and is left unproved (`leave <decl> unproved`, "stated, not
proved"), the PAPER_DEFECTS `false` row records it, and a `finding` item offers the repair in the K
stage (`involved`: asked). A goal whose proof (following the paper) needs such a refuted lemma may be
proved from a corrected helper lemma that is a pure addition (never in the index), disclosed with the
PAPER_DEFECTS row; stop 1 only when no such route exists. A vacuous non-goal result: its VACUOUS.md row
and docstring, and a `finding` item. Under `involved` (and, for missing theory turned into a named hypothesis, under `statements-only`)
a change to a statement the human approved is a QUESTION, never a stop.
**Adding a row to the index after the approval** changes the sign-off sheet: begin a re-approval
first (`run/reapproval.md` step 1), then add the row. A pure addition that needs no row (`<decl>_unconditional`, a
K3 bridge, a second reading `<decl>_reading_<x>`) is never added to the index: it is cited by its
`CONDITIONS.md` item or its docstring. Otherwise: begin the re-approval as below, ask them
(`reapproval.md`), and go on with the run. While it is open the **pending state** holds
(`reapproval.md`); only `project.py --deliver` refuses (`PENDING[question]`, not a failure line: open no
stop on it). Who may close it (`signoff.py approve --by agent` or `--by human`) is `reapproval.md` step 4. Under `hands-off` you
re-approve, but a delegated re-approval never strengthens or generalizes a statement beyond a reading
the paper's text admits (choosing the stronger of two readings the adjudicator found the paper admits
is not a strengthening), and weakens one only to turn missing theory into a named hypothesis (a refuted
statement is no longer repaired by you: above; `reapprove --begin --refuted-by` stays for `involved`
and the K stage). **Log before the edit:** before the Lean
edit, run `python3 audits/signoff.py reapprove --begin --decls <a,b> --reason "<reason>"` (list
every approved result stated in terms of a definition you will change, too). It refuses once a
listed declaration has already changed, commits the owned record `REAPPROVAL.json` (the Lean HEAD
and the approved fingerprints) and writes the `RUN_LOG.md` line `[DELEGATED …; reversal:
re-approve] change <declarations> — <reason>`. The freeze check then reports a change to a listed
declaration as `NOTE[reapproval]` (not a stop) until `signoff.py approve` closes the re-approval.
Any other DRIFT stays a freeze stop (its cure: `reapproval.md`, "A DRIFT"). While a re-approval the agent may close is open the report check (`make_report.py --check`,
also in Phase 0) is RED, so close it before delivery; the report lists every re-approval of the run.

**Stops that remain at every level.** Whatever the level, stop and tell the human, and wait, for
each of the following in `dev` mode; in `release` mode only for the four stops of the next paragraph, every other one being self-cured:
- anything outward-facing that the intake did not authorize: pushing, sending anything to the
  authors, publishing (`stops.py open --note "<what>" --cause outward-action`);
- (`dev`; self-cured in `release`) an integrity failure: a failure line of a STOP class (failure table) -- approved statements
  changed (DRIFT not begun as above), audit records tampered with or a record-ownership violation,
  tooling changed from the pin, a lane token, completion seal or prompt hash that does not match,
  git hooks, config or history changed (GITMETA: only the human clears it, by deleting
  `audits/.tree-baseline.json` after checking; you never delete it), an axiom beyond the standard
  three or a kernel-skipping token;
- (`dev`; never a stop in `release`) a tool bug: a failure with no cause code that persists after a
  re-run and comes from a pinned script, or a check that misjudges the case in front of it (`--cause
  tool-bug`; failure table). In `dev` only a maintainer fixes a pinned script. In `release` it is
  never a wait for a maintainer: a fault in the proof-validity core is a Lean-side workaround or
  `stops.py core-fault` and `close --core-fault` after a fresh reviewer's approval; any other is the
  tool-patch route (`tool_patch.py`; `run/stops-and-set-asides.md`, "Tool patches" and "Recording and
  closing a stop" item 1, also for a pinned writer that keeps crashing while every read-only check
  passes), never a human stop and never routed through `env-unknown`. The scripts treat a failure
  line with an unknown or missing code as a stop; it is you who re-runs and classifies it;
- a goal result (the intake's `goal_results`) that looks false, true only vacuously, unprovable as
  stated for a reason other than missing library theory (that is "Missing theory" above: never a
  stop), or stays unproved: it is never left unproved by a [DELEGATED] decision (Phase 0 refuses one,
  `RED[unproved-goal]`). Another result that stays unproved is not a stop under a delegating
  level: it is left unproved and disclosed (failure table, "your own work");
- the paper's meaning is genuinely ambiguous on a point that matters, and the reviewers cannot
  converge on one reading (`stops.py open --note "<the passage; the possible readings; what each
  would mean for the formalization>" --cause ambiguity`). This is your judgement; the code only
  records it. Show the human the passage, the possible readings and what each would mean for the
  formalization, and ask which is meant -- under every level, `hands-off` included. Close it with
  `close --human "<their answer, verbatim>"`; the run then resumes at its own level (a `hands-off`
  run stays hands-off: nothing else is asked). A loosely used or inconsistent convention (say,
  whether the natural numbers start at 0 or 1) is not this stop when it is no real
  misunderstanding: take the intended reading, go on, and record it as a reading choice (a
  `[DELEGATED …]` or, under `involved`, `[PROXY …]` line under "Open questions", and the
  `reading choice` row of the next adjudication); it is disclosed in `DECISIONS.md` and the report;
- something only the human can fix: a login or credential, administrator rights (a permission denial
  only after the plain retry of rule 12 is denied too), more quota or
  payment, a change to the user's own files, or another program that keeps changing the project's
  files during the run (`--cause interference`: a fault that recurs however it is cured -- name the
  recurring events). Say what is needed and why. Try first,
  within the retry budget (`spawn-and-seal.md`), logging each attempt under "Mechanical failures"
  (`release` mode: each attempt is a stop `open --note "<what failed>" --cause unknown-retry --check
  "<the read-only check of the failed step>"` closed `--cured`; `--cause env-unknown`, a human stop,
  is opened only once that budget is spent; `--delegated` is dev mode only).
  **A child's capacity error or usage limit opens no stop.** Waiting it out within the 2-hour time
  budget of `spawn-and-seal.md` is logged under "Mechanical failures" only, in both modes; it becomes
  a stop (as above) only when that budget is spent with the failure unchanged.
  **Your own usage limit or API error** ends your turn mid-step: in your next message (or, if you
  cannot write one, as the run's standing note) tell the human to type "continue" once the limit
  resets; the run then resumes where it stopped (`RUN.md`, "Start or resume").

**In `release` mode exactly four of these stop the run, at every level** (`project.RELEASE_STOPS`): **(1)** a goal result that looks false, true only
vacuously (a VACUOUS.md row or a confirmed non-vacuity finding on it),
unprovable for a reason other than missing library theory, or stays unproved (`unproved-goal`: `stops.py open --note
"<what>" --cause unproved-goal`); **(2)** an outward action the intake
did not allow (`outward-action`); **(3)** something only the human can fix: a login, administrator
rights, quota or payment, a change to the user's own files, or another program that keeps changing
the project's files during the run (`env-unknown` after the retry budget, `codex-approval`,
`interference`) -- but first remove the cause yourself: a plain retry, or a tool patch (a protocol-text
patch included: e.g. a subagent whose file write Claude Code refuses is told by the patched text to
return its text instead); stop 3 only for a login, a quota or usage limit, payment, OS or administrator
rights, a change to the user's own files, or another program changing the project's files. A protocol step you are told to do is never put
to the human as a permission question: stop 3 is only for what the human alone can grant (a login, a quota
or usage limit, payment, OS or administrator rights, a change to the user's own files, another program
changing files); **(4)** the paper's meaning is genuinely ambiguous on a point that matters and the
reviewers cannot converge on one reading (`ambiguity`; `hands-off` too; the run resumes at its own
level after the answer). When you ask, name it `stop S<n> (release stop <k> (<short label>))`, the label as the documents print it. A tool bug is never a
release stop: it is the tool-patch route. The statement-round cap reached while a faithfulness finding is open is no stop of its own in
`release` (`scope.py` prints `NOTE[round-cap]` and records the open findings in
`round-caps/<round>.json`): route it as `stage2-statements.md` step 5 says -- (a) a genuine
ambiguity: stop 4; (b) a loose convention: a reading choice; (c) anything else: a **Checkpoint B
question** (under `hands-off` a [DELEGATED] keep of the last round's statement with a `CONDITIONS.md`
`finding` item; every result it concerns reads "not established: open faithfulness finding"); `dev`:
a stop, `--cause round-cap`. Every other stop -- the integrity and tool-bug bullets, every other STOP
class, and every mechanical or document failure -- is **self-cured**, at every level: `stops.py open`
prints the cure of each code's kind (`project.CURES`; the failure table's release column,
`run/stops-and-set-asides.md`), you apply it, then `python3 audits/stops.py close --stop S<n> --cured "<what was done>"`.
The close re-runs the read-only check the stop recorded at open, which must pass. Before your first
`stops.py open` or `close` in this conversation, read only the section "Recording and closing a stop" of
`run/stops-and-set-asides.md` for this (`sed -n '/^#.*Recording and closing a stop/,/^#/p'
audits/run/stops-and-set-asides.md`), not the whole file: which check to record, the failure tally
and cure budget, `stops.py classify`, `close --withdrawn`, a redo stop's fresh round, and what
`--deliver` re-runs. A withdrawal never re-labels: a fault of the four stops is opened with its own
code. In `dev` mode every bullet above stays a stop.

One narrow exception, under a delegating level only: a RED from a **document check**
(`make_report.py --check` inside Phase 0, or `decisions.py --check`) whose cause is text **you**
wrote in `AUTHOR_NOTES.md`, `READER_NOTES.md` or `DECISIONS.md` is recorded as
a stop (`stops.py open`) that you cure yourself instead of waiting for the human, then close with
`stops.py close --delegated` (`release`: `close --cured`). The cure is a meaning-preserving edit of that text only (spelling, identifiers,
markup; never deleting an entry or a row). Log the diff as a [DELEGATED] decision. An edit to
`AUTHOR_NOTES.md` (or that `DEVIATIONS.md`) after the last audit round is disclosed in `DECISIONS.md` as
a change after the last audit round. It never covers a STOP class, a Lean file, a record owned by
another step, or a RED you did not cause. (Filling `DECISIONS.md` with what `decisions.py --check`
names, in Stage 5, is the step itself, at every level; the check advises and never blocks.)

## Run mode

The install sets the run mode (config `mode`, copied from `project_template.json`, frozen at the pin;
no key means `dev`); `prompt.py --show` prints it, and Checkpoint A states it. Under **`dev`** every
row of the failure table applies. Under **`release`** faithfulness, proof validity and integrity
findings (classes F, P, I of `project.RELEASE`) still fail their checks, but you cure them yourself
(`open`, the printed cure, `close --cured`: the failure table's release column); only the
stops that remain at every level reach the human. A finding of class N --
presentation or bookkeeping (report rendering, line citations, reader-gate findings, record
formats, part labels, docstrings, the log's round list), or a self-test failure or crash of a script
that serves only those -- prints as `DISCLOSED[<code>]` and does not fail its check. Fix it if the
text is yours; otherwise record it and go on: `python3 audits/stops.py disclose --cmd "<the check
that printed it>"` (a crash of `tests/doclint.py` that persists after a re-run within
the retry budget: `disclose --note "<what failed>" --cause tool-fault --script tests/doclint`). Never open a
stop for it (`open` refuses). The run record `RUN_RECORD.md` lists every one (with every stop,
self-cure, set-aside, tool patch, re-pin and mechanical failure: how the run went, which the reader of
the report does not need to judge faithfulness; markdown only, no PDF, no reader): `project.py --deliver` names in
notes a live `DISCLOSED` line with no record, a record RUN_RECORD.md does not name, and an applied tool patch, a
stop the operator closed or a set-aside it omits (`integrity.py --check-run-record`, from the raw records); you
correct RUN_RECORD.md from the facts draft (`project.py --prepare-delivery` after the last `disclose` writes it). REPORT.md and SUMMARY.md carry none of it: the report's
"How far to trust this" says only, in one line, that the tools were patched or the delivery was made by hand. A
fault of a delivered document's own presentation (`reader`, `render`, and an older run's `pdf`) is in the delivered
RUN_RECORD.md's delivery-phase notes instead, never in the documents: a reader's disclosure never makes a document stale. A tool bug in any
other script is the tool-patch route in `release` (a stop in `dev`).
**The delivered documents**: after the mathematics is verified, delivery never stops and is
never refused except by the math gate. `SUMMARY.md` and `REPORT.md` are yours, written from the records and the Lean
(`project.py --prepare-delivery` gives a facts draft, data, not the deliverable); four fresh reviewers advise and you
judge every finding (`JUDGEMENT.md`; its `## Status wording` gives, per result whose status your summary words
differently from the code's, your reason); `RUN_RECORD.md` and `DECISIONS.md` you correct where the draft is wrong.
The delivered README's section "What the checking code found" is the checking program's, never yours. No
generator fix, hand edit, fresh reader or stop is involved, and nothing about the documents is a
question to the human: `run/stage5-delivery.md` step 5.
The PDFs are never a stop and never a disclosure, in either mode. Fresh agents render each audited
markdown and check the PDF (`run/render-pdf.md`): a renderer, a verifier, and two independent
checkers of its mathematics, in a loop of at most 6 rounds that always finishes. The markdown is
always delivered beside its PDF. The one code guard is a fingerprint: `signoff.py approve --by human` refuses
(ask again), and `project.py --deliver` prints a note, unless the PDF is the one
`render_record.py` recorded for the markdown as it is now; `approve --by human` also needs it to be
the PDF recorded as shown when the human was asked (`render_record.py shown`). The cure is always to
render again (and ask again).

## When something fails

Every failure line carries `KIND[code]`; the class, never the wording, decides. Look up its row (a failed check, a failed child or agent) in **the failure table**
(`run/stops-and-set-asides.md`, first section): the row-specific cure, the release column and the tool-patch
route are there. `close --delegated` is dev mode only.

## Logging

`RUN_LOG.md` is your record of the run and what a resumed conversation reads. Its sections, in
order: Intake, Checkpoint A, Stage 2, Rounds, Mechanical failures, Stops, Set-asides, Open
questions, Checkpoint C, Answered, Fresh readers, Current stage. What each holds is in
`run/stage1-setup.md` ("RUN_LOG.md sections"), which creates the log; `project.py --log` creates a
missing section. A [PROXY] decision is logged as "[PROXY <date>, operator for <who>; reversible]
…", a delegated one with the [DELEGATED …] tag above; an answered open question is marked
"(answered <date>: <answer>)", never deleted.

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
- `run/stops-and-set-asides.md`: a check stops the round (failure table below), or a round must be
  set aside.
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
   - `scope`: lane tokens, reissued and superseded lane files, `TARGET.json`, `FINGERPRINTS.json`, `STATEMENTS_BUNDLE.md`;
   - `seal`: lane seals, lane probes, re-votes, render checks, lane verdicts;
   - `resolve`: an older run's stall resolutions (`resolutions/`);
   - `stop`: the stop records (`stops/`, their repair records);
   - `ack`: waivers (`waivers/`);
   - `escalate`: escalation prompts and answers (`escalations/`);
   - `set-aside`: set-asides (`ABANDONED.json`, `.abandoned/`);
   - `reader`: reader records (`readers/`), the readers' notices (`KNOWN_FAULTS-*.md`);
   - `hand-edit`: the hand-edit records (`hand-edits/`: written by `readers.py --hand-edit`);
   - `render`: the PDF records (`pdf/`: `RENDER.json`, the rendering agents' prompts, PDFs and verdicts);
   - `adjudicate` or `reader-fix`: `ADOPTED.md`, `DEVIATIONS.md` (a run pinned before ownership 3: you write its rows, never a `reading choice` or `differs` row);
   - `signoff`: `INFORMAL.json`, `SIGNOFF.json`;
   - `round-cap`: the statement-round cap records (`round-caps/`);
   - `adjudicate` or `record-fix` or `reader-fix`: `PAPER_DEFECTS.md`, `SKIPPED.md`, `VACUOUS.md`;
   - `reader-fix-prompt`: the reader-fix prompt (`prompts/adjudicator-readerfix-<n>.txt`);
   - `prepare delivery`: the delivery record (`DELIVERY.json`);
   - `approve`: the approval files (`APPROVED_FINGERPRINTS*.json`), `REAPPROVAL.json`;
   - `pin`: `TOOLING_PIN.json`;
   - `glyphs`: an older run's `uni_math_extra.json`.
   Of these you write by hand only your response files `readers/<key>-<n>.response[-k].md` and the notice `KNOWN_FAULTS-<key>.md` (`run/fresh-reader.md`, committed as `reader <key> <n> (response)`).
   Never edit the audit scripts, `AUDIT_PROTOCOL.md`, this file, `audits/run/`, `audits/agents/` or
   `~/.claude/agents/auditor.md`. Your own files are `RUN_LOG.md`, `AUTHOR_NOTES.md` (route changes
   under "Route changes": the adjudicator writes `DEVIATIONS.md` from them) and `OUTCOMES.md`.
<!-- rule4:end -->
5. **Commit messages carry ownership.** Every record is committed by the script that writes it, by
   name, with its own message (`scope`, `seal`, `signoff`, `approve`, `adjudicate`, `pin`, `stop`,
   `set-aside`, `reader`, `ack`, `render`, `escalate`). Commit your own files and the Lean by name; never `git add -A`.
   `integrity.py` checks ownership from git history at every adjudication.
6. **ADOPT rows are implemented as written.** If you think one is wrong, record
   "not implemented — disagree: <reason>" in `OUTCOMES.md`. It goes to the human.
7. **Never re-run a lane or adjudicator hoping for a different answer.** A re-run is allowed only
   after a mechanical failure (a crash, no file written, a usage limit, a service error), within
   the retry budget of `spawn-and-seal.md`, never after an integrity or protocol STOP, and is
   recorded in `RUN_LOG.md`.
8. **A subagent or script that says STOP stops the round.** Show the human its raw output (in `release`
   mode only for the four stops of "Stops that remain at every level"; every other STOP is a stop you
   open and cure as the failure table's release column says, never a wait). Do not
   repair the cause and carry on. What you may cure, and at which level, is the failure table
   below, and nothing else: you never clear a stop by your own judgement, and never by writing,
   copying, moving or deleting a lane's verdict or probe files to satisfy a check. A script's
   refusal (a second `--write`, a second seal, a Phase 0 on an uncommitted tree) protects the
   record: read it as the failure it names, never work around it.
9. **Tag every monitor you start.** A polling loop you start yourself (waiting for a build, a
   file, a child) must carry `FORMALIZE_PAPER_OPERATOR=1` in its environment, for example
   `FORMALIZE_PAPER_OPERATOR=1 bash -c 'until …; do sleep 30; done'`; `lanecheck.py` flags an
   untagged loop as a lane's and `--kill` ends it. Prefer the harness's own blocking waits.
10. **Write no persistent memory about this run until Checkpoint C.** Subagents receive the user's
    memory index, so a note you save becomes background every later reviewer sees.
11. **Quote script output; never restate it.** Phase 0's verdict is its `PHASE 0 RESULT` table.
    The order is always: change, commit, then `phase0.py`.
12. **Write `RUN_LOG.md` with the log command.** `python3 audits/project.py --log "<section>"
    <<'EOF'` … `EOF` appends (creating the section), and `project.py --stage "<text>"` sets the
    current stage; your file-editing tool works too. Never `python3 - <<EOF` or `python3 -c`: those
    ask for permission, and the person is not watching.
    **Run every protocol command plainly**: exactly `python3 audits/<script>.py <args>`, as printed, with
    no environment prefix (`PYTHONDONTWRITEBYTECODE` is set by the project's settings), no pipe (`| tail`)
    and no chaining (`;`, `&&`): only the plain form matches the project's permission rules. A command
    denied by a permission prompt or the auto-mode classifier is retried once in exactly that plain form;
    only if the plain retry is denied too is it stop (3), a permission only the human can grant.
13. **Never read a PDF, or a whole large file or output, yourself.** Every page you read stays in
    your context and is re-sent at every later turn: three reads of one report once filled 90% of
    a run's context. Never read a PDF yourself: the renderer, verifier and checkers do
    (`run/render-pdf.md`); the fresh reader reads the markdown (`fresh-reader.md`). Read a long
    file or output with `grep`, `tail` or `sed -n`, or give it to a subagent and keep its answer.

**Cost.** Read this file, the current stage file and a procedure file when it applies; nothing
else in full. Spawn the lanes of a wave in one message and seal each as it returns. If the human
said at intake (question 7) that the machine has 16 GB of RAM or less, at most 3 subagents run at
once, whatever a step says about spawning in parallel or at once: spawn the rest as earlier ones
return. Wait with
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
Without a written recommendation, take the conservative rule:
- keep the paper's statements and hypotheses (a hypothesis the proofs do not need stays);
- never generalize or strengthen a statement;
- take a missing literature result or missing library theory as an explicit named hypothesis,
  always: never build a large library, never skip the result;
- a literature hypothesis later proved stays a hypothesis: land the proof as a separate theorem
  `<decl>_unconditional` (a pure addition: the approved statement, its hypothesis and the config are
  unchanged; no re-pin, no question), and the next round audits it like any new declaration;
- a reading choice (an Ambiguous verdict: the paper admits two readings): never formalize both;
  take the reading the adjudicator's QUESTION row recommends, else the weaker one; when neither
  implies the other, the one the paper's own proof proves; it is disclosed as a reading choice. A
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
   `[DELEGATED <date>, operator under <level> (intake); reversal: none] missing theory: build <what>
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
(`FAIL[missing-theory]`) refuses a line in another form, one without the quote or a library's search,
a human line without the human's committed answer, option (3) as [DELEGATED], one whose `H` is not
in the result's assumption list (the walk) or that the walk flags as restating a result or as a
result's conclusion, and a `build` line while the hypothesis it replaces is still a binder of the
result; a corrected line logged after it, or the line reworded, clears it. An `H` that is a goal
result's conclusion or restates a goal result (it implies the goal) is `FAIL[unproved-goal]`: no
missing theory but the goal unprovable as stated, stop 1. The paper-faithfulness reviewer, not your line, judges the hypothesis: a Fail if the quote is not
the paper's, the paper proves the result anywhere (a quote with part of a proof attached included),
or `H` says more than the quoted invocation; the non-vacuity reviewer flags `H` that is (nearly) the
goal's main step. The summary (`SUMMARY.pdf`) says "<result> proved assuming <H>".

**Statement changes after approval.** Under `involved` and `statements-only` any change to a
statement the human approved is a QUESTION, never a stop (U2 §0, §5): begin the re-approval as
below, ask them (`reapproval.md`), and go on with the run. While it is open the **pending state**
holds: rounds, Phase 0 (`--readonly` too), `decisions.pending_unproved` and the axiom sweep accept
`sorry` in that statement's proof and sorryAx reaching other results only through it (Phase 0 prints
`NOTE[reapproval]`, the report check `PENDING[question]`); only `project.py --deliver` refuses
(`PENDING[question]`, not a failure line: open no stop on it). `signoff.py approve --by agent` closes a
re-approval only under `hands-off`, or under `involved` when the intake's 5d is logged as exactly
`- 5d: agent` (never under `statements-only`: there the human approves), and only when the
approval it replaces was the agent's; otherwise it refuses with `PENDING[question]` and the human
approves (`--by human`, which refuses until their verbatim answer is committed under `## Re-approvals`
as `- human answer (round <R>; <declarations>): "<words>"`: evidenced, still trust-based); an
unreadable 5d means the human. Under `hands-off` you
re-approve, but a delegated re-approval never strengthens or generalizes a statement, and weakens
one only to turn missing theory into a named hypothesis, or to repair a refuted statement (`reapprove
--begin --refuted-by`, `reapproval.md`: repaired and disclosed, never a stop). **Log before the edit:** before the Lean
edit, run `python3 audits/signoff.py reapprove --begin --decls <a,b> --reason "<reason>"` (list
every approved result stated in terms of a definition you will change, too). It refuses once a
listed declaration has already changed, commits the owned record `REAPPROVAL.json` (the Lean HEAD
and the approved fingerprints) and writes the `RUN_LOG.md` line `[DELEGATED …; reversal:
re-approve] change <declarations> — <reason>`. The freeze check then reports a change to a listed
declaration as `NOTE[reapproval]` (not a stop) until `signoff.py approve` closes the re-approval.
Any other DRIFT stays a freeze stop; in `release` its cure is always to restore the approved
statement (an intended change goes through re-approval, begun before the edit, never inside the open
stop). While a re-approval the agent may close is open the report check (`make_report.py --check`,
also in Phase 0) is RED, so close it before delivery; the report lists every re-approval of the run.

**Stops that remain at every level.** Whatever the level, stop and tell the human, and wait, for
each of the following in `dev` mode; in `release` mode only for the four stops of the next paragraph
(U2 §0; approver, 2026-10-24), every other one being self-cured:
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
  `stops.py core-fault` and `close --core-fault` after a fresh reviewer's approval ("Tool patches"), any
  other is
  the tool-patch route (`project.CURES["patch"]`, `tool_patch.py`): a tool bug that a read-only
  check shows (`open --note ... --cause tool-bug --check "<it, failing now>"`) is cured like any
  rerun, or by a tool patch; a pinned writer (`prompt.py`, `signoff.py approve`, ...) that keeps
  crashing while every read-only check passes is `open --note "<what crashed>" --cause tool-bug`
  with no `--check`, cured only by a tool patch (`close --cured "tool-patch TP<k>"`), never a human
  stop and never routed through `env-unknown`. A failure
  is no longer a stop merely because no code covers it: the scripts still treat a failure line with
  an unknown or missing code as a stop, and it is you who re-runs and classifies it;
- a goal result (the intake's `goal_results`) that appears false, or unprovable as stated for a
  reason other than missing library theory (that is "Missing theory" above: never a stop), or that
  stays unproved: it is never left unproved by a [DELEGATED] decision (Phase 0 refuses one,
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
  a stop (as above) only when that budget is spent with the failure unchanged. Fixes to try first:
  retry failed downloads (`lake exe cache get` again; it can partly fail), re-run the build, check
  that the Mathlib and toolchain pins match, clear and rebuild the project's own build outputs
  (never the user's files), wait out a usage limit and resume, and free space only in the run's
  own scratch and build directories.
  **Your own usage limit or API error** ends your turn mid-step: in your next message (or, if you
  cannot write one, as the run's standing note) tell the human to type "continue" once the limit
  resets; the run then resumes where it stopped (`RUN.md`, "Start or resume").

**In `release` mode exactly four of these stop the run, at every level** (approver, 2026-10-21 and
2026-10-24; `project.RELEASE_STOPS`): **(1)** a goal result that looks false, or unprovable for a
reason other than missing library theory (`unproved-goal`); **(2)** an outward action the intake
did not allow (`outward-action`); **(3)** something only the human can fix: a login, administrator
rights, quota or payment, a change to the user's own files, or another program that keeps changing
the project's files during the run (`env-unknown` after the retry budget, `codex-approval`,
`interference`) -- but first remove the cause yourself: a plain retry, or a tool patch (a protocol-text
patch included: e.g. a subagent whose file write Claude Code refuses is told by the patched text to
return its text instead); stop 3 only for a login, a quota or usage limit, payment, OS or administrator
rights, or another program changing the project's files. A protocol step you are told to do is never put
to the human as a permission question: stop 3 is only for what the human alone can grant (a login, a quota
or usage limit, payment, OS or administrator rights, another program changing files); **(4)** the paper's meaning is genuinely ambiguous on a point that matters and the
reviewers cannot converge on one reading (`ambiguity`; `hands-off` too; the run resumes at its own
level after the answer). A tool bug is never a release stop: it is the tool-patch route. The
statement-round cap reached while a faithfulness finding is open is no stop of its own in
`release` (`scope.py` prints `NOTE[round-cap]` and records the open findings in
`round-caps/<round>.json`): you judge its cause -- (a) a genuine ambiguity: stop 4; (b) a loose
convention: decide the intended reading, record it as a reading choice and go on; (c) anything
else: go on with the last round's sheet, and every result an open finding concerns reads "not
established: open faithfulness finding" on the summary's first page (`stage2-statements.md` step 5;
`dev`: a stop, `--cause round-cap`). Every other stop -- the integrity and tool-bug bullets, every other STOP
class, and every mechanical or document failure -- is **self-cured**, at every level: `stops.py open`
prints the cure of each code's kind (`project.CURES`; the release column under "When something
fails"), you apply it, then `python3 audits/stops.py close --stop S<n> --cured "<what was done>"`.
It re-runs exactly the read-only check the stop recorded at open, which must pass; a failing attempt
is recorded (`S<n>/CURE<k>.json`). That check is always one of the protocol's read-only check
commands, never a writer and never the failed tool command itself: a `--cmd` stop's check, or for a
`--note` stop the read-only check of the step that failed, given at open (`open --note ... --cause
<code> --check "<it>"`: `integrity.py --check` for setup, `lanecheck.py --round <R>` for a round,
`phase0.py --readonly` for the build); it must fail then. A code with a closer of its own (the
release column's "closes with") records exactly that closer, on the stop's `--round` for a
round-bound one (leave `--check` out and `open` records it), never another check that happens to
fail now; `--deliver` re-runs those closers too. A failure no code covers is `--cause
unknown-retry` with such a `--check`. `close --delegated` is dev mode only; a code that is
disclosed in release never opens a stop. The failure tally (U2 §4), counted from git history over the whole run and never
reset, under any stop id: a fault is keyed by (check script, cause code) -- a `--cmd` stop by its
command's codes, a `--note` stop by the codes its `--check` printed at open (an uncoded failure:
`unknown`), whatever code you gave it. A `--note` stop also has the key (its code, the round: the
newest round with a verdict file or adjudicated when it opened, its check script), `unknown-retry`, `tool-call`,
`git-error`, `tool-bug`, `commit-refused` and uncoded sharing one; it counts openings only. The
cure budget is spent by a stop with `project.CURE_BUDGET` (2) failed `--cured` re-runs of its own,
whatever codes they showed; a (script, code) with `project.KEY_BUDGET` (3) failed re-runs anywhere in
the run (a flaky check failing one cure in each of two far-apart rounds does not spend it); or a key
opened more than `project.OPEN_CEILING` (3) times in one round after a failed cure of it there. A
passing cure is not counted, so a fault that recurs but is cured at the first try never spends it.
A spent budget is no stop of its own: no further `--cured` is accepted until you classify the fault
(your judgement, recorded): `python3 audits/stops.py classify --stop S<n> --as
tool-bug|interference|other --evidence "<why>"` -- `tool-bug`: the check or tool is wrong, the
tool-patch route; `interference`: another program keeps changing the project's files, stop 3 (show
the human the recurring events, `close --human`); `other`: neither, name the different cure you
will try and `close --cured` once more. A stop round that is not a real round of the run is the
human's. The run record `RUN_RECORD.md` names every self-cure ("Stops cleared without you", with
what was redone and where the independence of a review was compromised; the report and the summary
do not; `project.py --deliver` names an omission in a note, and you correct RUN_RECORD.md). In both modes
`--deliver` re-runs on the state delivered the math gate -- Phase 0 read-only (build, sorry scan, axiom sweep,
freeze), `fingerprint.py --check` (once something is approved) and `integrity.py --check` (refusing only on a fault
of the proof-validity core, a freeze record or a judgement record; any other integrity FAIL is a note) -- and
refuses on its failure; every self-cured stop's own check is re-run too, a failure printed as a note for you to
judge (approver 2026-10-28). A refusal is cleared only by fixing what the check reports (and re-running
`--deliver`); closing a stop does not clear it, since the check itself is re-run. A
self-cure whose check names a round since set aside or superseded is not
re-run (it held for that round only): its committed passing record is verified instead. A redo
stop whose round its own self-cure set aside (`set-aside <R> --stop S<n>`) is closed on the fresh
round that redoes it: the set-aside round keeps its faulty files as record, so its check would fail
for ever; `close --cured` re-runs the recorded check with `--round` the fresh round: scoped after the
set-aside while the stop is open (`scope.py` records `redo_of` in its TARGET.json), covering the
set-aside round's scope with sealed verdicts on every item of it (a diff round cannot cover a
full or statements round: scope it `--full`), recorded as `redo_round`; it refuses, spending no
attempt, until that round exists, and refuses for the human when the lineage cannot be read. When
the recorded check names no round (`tree_state.py --check`, say), the cure also runs `lanecheck.py
--round <the fresh round>` (and `--deliver` re-runs it). A fresh round that fails with other codes
only charges the failed cure to those codes. In `dev`
mode every bullet above stays a stop.

One narrow exception, under a delegating level only: a RED from a **document check**
(`make_report.py --check` inside Phase 0, or `decisions.py --check`) whose cause is text **you**
wrote in `AUTHOR_NOTES.md`, `READER_NOTES.md` or `DECISIONS.md` (or `DEVIATIONS.md` in a run pinned before
ownership 3) is recorded as
a stop (`stops.py open`) that you cure yourself instead of waiting for the human, then close with
`stops.py close --delegated`. The cure is a meaning-preserving edit of that text only (spelling, identifiers,
markup; never deleting an entry or a row). Log the diff as a [DELEGATED] decision. An edit to
`AUTHOR_NOTES.md` (or that `DEVIATIONS.md`) after the last audit round is disclosed in `DECISIONS.md` as
a change after the last audit round. It never covers a STOP class, a Lean file, a record owned by
another step, or a RED you did not cause. (Filling `DECISIONS.md` until `decisions.py --check`
passes, in Stage 5, is the step itself, at every level.)

## Run mode

The install sets the run mode (config `mode`, copied from `project_template.json`, frozen at the pin;
no key means `dev`); `prompt.py --show` prints it, and Checkpoint A states it. Under **`dev`** every
row of the failure table applies. Under **`release`** faithfulness, proof validity and integrity
findings (classes F, P, I of `project.RELEASE`) still fail their checks, but you cure them yourself
(`open`, the printed cure, `close --cured`: the release column below the failure table); only the
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
**The delivered documents** (approver 2026-10-28): after the mathematics is verified, delivery never stops and is
never refused except by the math gate. `SUMMARY.md` and `REPORT.md` are yours, written from the records and the Lean
(`project.py --prepare-delivery` gives a facts draft, data, not the deliverable); four fresh reviewers advise and you
judge every finding (`JUDGEMENT.md`); `RUN_RECORD.md` and `DECISIONS.md` you correct where the draft is wrong. No
generator fix, hand edit, fresh reader, status check or stop is involved, and nothing about the documents is a
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

Each failure line carries a cause code, `KIND[code]` (`project.CAUSES` gives each code a class);
the class, never the wording, decides. A "stop" is recorded and handled with
`run/stops-and-set-asides.md`. Every cure is logged under "Mechanical failures".

The two right-hand columns are `dev` mode's. In `release` mode a stop closes only as the release
column below the table says: `close --cured` (re-running its read-only check) or, a human stop,
`close --human`; `close --delegated` is dev mode only.

| what failed | class (codes) | `involved` | `statements-only` (after B), `hands-off` |
|---|---|---|---|
| a `DISCLOSED[…]` line (`release` mode only) | presentation (`render`, `record-format`, `pdf`, `reader`, `label`, `selftest`, `tool-fault`); `docstring`, `run-log` | not a stop: fix your own text, or `stops.py disclose` ("Run mode") | same |
| a PDF: `signoff.py approve --by human` refuses, or `project.py --deliver` notes, that a PDF is missing, swapped, or was made from an older markdown (`render_record.py check`); a rendering agent crashed or never saved; an older run's `[pdf]` line | presentation (`pdf`, legacy) | never a stop, in either mode (`stops.py open` refuses `pdf`): render again (`render_record.py next --doc D`, `run/render-pdf.md`); a failed agent is recorded with `render_record.py fail` and the loop goes on; under approve, show the human the new PDF and ask again | same |
| a citation-review agent (Stage 5 step 5a: the advisory `CITATIONS.md`): crash, no file, the network unavailable | none: advisory, no check reads it | never a stop, never a retry beyond waiting out a usage limit or capacity error (`spawn-and-seal.md`): log `- citation notes not produced: <reason>` and go on; the run ships without it and the summary says so in one line | same |
| `RED[deliver-stale]` (`project.py --deliver`, the math gate): a Lean commit after the last audited round; a note `[deliver]` or `[unverified]` (`project.py --deliver`, after delivering): a facts draft stale or missing, a check of a delivered document, no full-scope round since the approval, or a result whose verdict is missing or out of date (`result_status.py`) | precondition (`deliver`, `unverified`, `deliver-stale`) | never a stop, in either mode (`stops.py open` refuses them): for `deliver-stale` a diff round (a full round when `scope.py` exits 3 with `NEXT[full-round]`: the commit changed no reviewed declaration; `run/stage5-delivery.md`), asked only until two rounds ran after the final full round (`project.DELIVERY_ROUND_CAP`, stage 5 step 1): past that the commit ships, disclosed as not re-audited, and no round is run for it; `deliver` and `unverified` never refuse: judge each note (approver 2026-10-28) | same |
| a note `[status-unmapped]` (`project.py --deliver`): a result reads "not established" for a reason no route of `result_status.py` covers (no assumption walk, the walk did not reach it, an index cell naming no declaration with a fingerprint, a record it cannot read) | presentation (`status-unmapped`) | never a stop (approver 2026-10-28): re-run Phase 0 (not `--readonly`: it rewrites `DEPENDENCIES.json`, the walk) or correct an index cell that names no declaration, commit; what remains you judge from the records and the Lean, and SUMMARY and REPORT state the status you find | same |
| a `NOTE[…]` line | info, settle (`independence`, `independence-path`), lane-fault | nothing to do, never act on it; the adjudicator settles each lane NOTE by a clearance or a re-vote | same |
| a child: crash, service or capacity error, usage limit, no verdict file, no `LANE_COMPLETION`; a failed tool call or download | mechanical (`lane-output`, `tool-call`) | retry within the time budget (`spawn-and-seal.md`; a capacity error or usage limit waited out there is logged under "Mechanical failures", no stop); then an environment fault (a stop) | same |
| your own work: Phase 0 (author mode) `RED[build]`, `RED[branch]`, `RED[baseline]`, `RED[sorry]`, `RED[unproved-meta]`, `RED[hard-token-own]`, `RED[axiom-own]` (a `native_decide` or other kernel-skipping token, an extra axiom: rewrite that proof without it); `RED[index]`, `RED[unlisted]`, `RED[docstring]`, `RED[run-log]`, `RED[unused-args]`, `RED[dependencies]` | mechanical, proof-wip, document | fix it in a new commit and re-run Phase 0; a `sorry` you cannot prove follows Stage 3 (a goal result: a stop; otherwise ask: removing, narrowing or hypothesising away a result is the human's decision) | fix it in a new commit and re-run Phase 0; a `sorry` you cannot prove: a goal result is a stop; missing theory becomes a named hypothesis ("Missing theory"; an approved statement also follows "Statement changes after approval"); any other result that stays unproved after a serious attempt is left unproved, never deleted or weakened: keep its statement byte-identical, log `[DELEGATED <date>, operator under <level> (intake); reversal: re-prove] leave <decl> unproved — <reason>` as a line of its own under `## Open questions` (`project.py --log "Open questions"`; full Lean name; every result whose proof uses it needs its own line: the axiom sweep is RED until it has one), propose it in `AUTHOR_NOTES.md` under results not to formalize, make its index cell "`<decl>` (stated, not proved: not formalized)", commit, re-run Phase 0 (its `sorry` is then `NOTE[unproved]`); the next round's adjudicator records it in `SKIPPED.md`, and the report and `DECISIONS.md` disclose it as "stated, not proved" |
| a `project.py --deliver` note `[adj-record]`: a result left unproved that no round has adjudicated since (its line logged after the final diff round) | document | (cannot occur: no line exempts under `involved`) | run one more round, so its adjudicator checks it and records it in `SKIPPED.md` (a diff round; `scope.py` exits 3 with `NEXT[full-round]` when it has nothing to scope: a full round); then Phase 0, prepare, and deliver |
| Phase 0 `RED[dependencies]` from the walk: `DEPENDENCIES.json` missing, without the assumption walk, stale (the Lean changed), or a goal result with no walk entry; or the walk did not run because the project does not build | document | re-run Phase 0 (not `--readonly`): it rewrites the file; a goal result with no entry: fix its index cell. `RED[tool-bug]` from the walk (an error inside the walk's own code): a pinned script's bug, the `tool-bug` key | same |
| `FAIL[missing-theory]` (`make_report.py --check`, also inside Phase 0): your missing-theory line in `RUN_LOG.md` is not in the canonical form ("Missing theory"), lacks the paper's quote or a configured library's search, comes from the wrong level (a [DELEGATED] line under `involved`, a human one under `hands-off`), is a human line without the human's committed answer naming the result, takes option (3) as [DELEGATED], names a hypothesis that is not in its result's assumption list or that the walk flags as restating a result (or as a result's conclusion), or says `build` while the replaced hypothesis is still a binder. (`FAIL[unproved-goal]` from the same check: `H` is a goal result's conclusion or restates one: stop 1, below.) | document | the human's choice is recorded in the wrong form: log their answer and correct the line (reword it, or log the corrected line after it), commit, re-run the check; ask if the Lean must change | correct the line (reword it, or log the corrected line after it), take `H` as a binder of the result's statement, or prove a restated result instead of assuming it ("Missing theory"; an approved statement follows "Statement changes after approval"), commit, re-run Phase 0 (`release`: a self-cure, closed by `make_report.py --check`) |
| lanecheck `PROBLEM[unsealed]`, `[stray-loop]`, `[stray-file]`, `[no-baseline]` | mechanical | seal (or reissue) the lane; `--kill`; restore the tree and tell the adjudicator; run Phase 0 | same |
| a record of the adjudicator's (PAPER_DEFECTS, SKIPPED, VACUOUS.md) cites what does not exist: `FAIL[dead-witness]` (a witness cell naming `sorry` or a probe's lemma), `FAIL[record-cite]` | record-fix | `stops.py open`; record correction: `prompt.py 4 --round <R> --record-fix --write` (R the last adjudicated round), spawn a fresh adjudicator with the printed line; it edits only the faulty cells and commits `record-fix <R>` (`integrity.py --commit-record-fix`, which refuses anything more); re-run the check, `close --delegated` (`release`: `close --cured`). It needs no GREEN Phase 0, no Lean commit and no new round (Phase 0 is RED on the very fault). It returns NEEDS A ROUND, or the fault is in a verdict, decision or status cell: a new round (Phase 0 shows the fault as `PENDING[adjudication]`, so the round runs; its adjudicator clears it). Disclosed in the report's stop list | same (never the human; `release`: `close --cured`, never `--delegated`) |
| a `PENDING[adjudication]` line (Phase 0), or `FAIL[adj-record]` / `RED[adj-record]` (`make_report.py --check`; a note of `project.py --deliver`): any other fault of an adjudicator's record (a cell count: a literal `\|` in a cell; a missing-theory "decided by" cell not bound to a RUN_LOG.md decision naming the result -- with none recorded, the adjudicator writes a QUESTION row and "QUESTION (<round>)", and the question reaches the human at Checkpoint C (under a delegating level, you decide it with a [DELEGATED] line); a defect only in prose; "formalized AND skipped" -- once an adjudication ADOPTs fixing the index for it, it is your `report` fault: make the index cell "not formalized"; a result left unproved without its SKIPPED.md row; a carried item without its ADOPTED.md row) | adjudication (`adj-record`) | not RED in Phase 0: run the round; its adjudicator's prompt lists the faults and `--commit-adjudication` refuses until it clears them. Before delivery: one more round (`prompt.py 3 --full` if no Lean changed); a stop on it is closed `--delegated` (`release`: `--cured`) | same (never the human; `release`: `close --cured`) |
| tree_state `FAIL[head-moved-operator]`: HEAD moved since the baseline only by your own prescribed empty commits (each empty, the baseline's author, subject `fresh round after the set-aside of <R>`, listed in RUN_LOG.md or a stop record: its full hash, or 12+ characters, on one line with that subject) | mechanical | list it when you make it: `echo "- <full hash> fresh round after the set-aside of <R>" \| python3 audits/project.py --log "Mechanical failures"` (works while another stop is open; `stops.py open` does not); `python3 audits/tree_state.py --resave-operator --reason "<which commit, why>"` (logged, recorded in the baseline; no GREEN Phase 0 needed); a stop opened on it: `close --delegated` (`release`: `close --cured`). `release` also: HEAD moved only by your own commits up to exactly the commit a round was cut from (its directory committed; Phase 0 did not save the baseline after them) is the same row, the same cure (`--resave-operator` logs it). Any other commit (another subject, unlisted, a change and its revert, a commit past the round's) is `FAIL[head-moved]` (next row) | same |
| tree_state `FAIL[head-moved]`: a commit since the baseline changed files, is a merge, or has another author | tamper | a stop for the human at every level (a lane may have committed); `release`: a self-cure (restore): `tree_state.py --revert-foreign` reverts the whole foreign range, accepted only when HEAD's tree equals the baseline's, then `close --cured` | same |
| a document check (`report`) RED from text you wrote in `AUTHOR_NOTES.md`, `READER_NOTES.md` (`DEVIATIONS.md` in a run pinned before ownership 3) | document | a stop: ask | the narrow exception above, then `stops.py close --delegated` |
| any other failure line of a check (integrity, tree_state, lanecheck, lane_auth, stops), class mechanical or document: e.g. `uncommitted-record`, `tree-changed`, `git-error`, `unsettled` | mechanical, document | a stop: `stops.py open`, ask, `close --human` | `stops.py open`, cure as the code says, `close --delegated` |
| a failure with no cause code: a script crashing (`FAIL[uncoded] <script> crashed (...)`, printed by `project.run_main` after the traceback, which goes to stderr), an error message no code covers, git or Lean/lake failing unwrapped | mechanical (`unknown-retry`, `uncoded`, `env-unknown`), tool-bug (`tool-bug`) | `stops.py open --note "<what failed>" --cause unknown-retry`, re-run the command within the retry budget (`spawn-and-seal.md`), ask, `close --human` | same open and re-run; it passes: `close --delegated`; it persists: close it naming the next stop and classify it (`run/stops-and-set-asides.md`): a traceback whose innermost project frame is in `audits/` is `--cause tool-bug`, a stop (you never edit a pinned script); otherwise `--cause env-unknown`, fixed as an environment fault (the last bullet of "Stops that remain at every level"), then `close --delegated`, a stop only after the retry budget. `release` mode, both columns: `open --note "<what failed>" --cause unknown-retry --check "<the read-only check of the failed step>"` (a FORMS check, failing now), cure, `close --cured`; after the retry budget `--cause env-unknown` (stop 3, a human stop) or, a pinned script, `--cause tool-bug` (the tool-patch route, never a human stop); never `--delegated` |
| a STOP class | tamper, apparatus, freeze (`drift`), gitmeta, proof (`axiom`, `hard-token`: read-only Phase 0 or another check; `unproved-goal`), tool-bug (`tool-bug`), unknown (a failure line with no code) | a stop: `stops.py open`, ask, `close --human`. `release` mode: a self-cure, except `unproved-goal` ("Stops that remain at every level": `open`, apply the printed cure, `close --cured`; past the budget, `stops.py classify`: stop 3 only for outside interference, a tool bug the tool-patch route) | same |
| the four release stops: (1) a goal result looks false, or unprovable for a reason other than missing library theory, or stays unproved; (2) an outward action the intake did not allow; (3) something only the human can fix (an environment fault, a Codex approval prompt under a delegating level, another program that keeps changing the project's files); (4) a genuine ambiguity of the paper's meaning the reviewers cannot settle | `unproved-goal` (Phase 0 prints it for one left unproved, the report check for a goal assumed as "missing theory"; one that looks false: `open --note ... --cause unproved-goal`), `outward-action`, `env-unknown` (after the retry budget), `codex-approval`, `interference` (after `stops.py classify --as interference`), `ambiguity`: human (H) | a stop: `stops.py open --note "<what>" --cause <that code>`, ask, `close --human` | same, in `release` mode too (never a self-cure; `release` refuses a `--note` cause that is not a cause code) |
| an approved statement must change | (decision) | a QUESTION (`reapproval.md`; the pending state holds, only `--deliver` waits) | `statements-only`: a QUESTION as under `involved` (the run goes on); `hands-off`: delegated within "Statement changes after approval" |
| missing theory; a QUESTION row; the round cap | (decision) | ask at the checkpoint; the round cap: the conservative default as a [PROXY] decision (`release`; `dev`: ask) | decide as in "How you decide" and "Missing theory" |
| the statement-round cap (`scope.py --statements`: 4 before the first approval, 2 per re-approval) | `NOTE[round-cap]`; with a faithfulness finding open: `dev`, `PROBLEM[round-cap]` (`round-cap`, a stop); `release`, `NOTE[round-cap]` naming the three routes, the open findings recorded in `round-caps/<round>.json` (`round-cap`, disclosed) | no finding open: no stop, the last round's sheet, its statement-changing ADOPT rows recorded as decisions ([PROXY]). A finding open: `dev`, a stop, `stops.py open --note "<what>" --cause round-cap`, ask, `close --human`; `release`, judge its cause: (a) a genuine ambiguity, stop 4 (`--cause ambiguity`, ask, `close --human`); (b) a loose convention, a reading-choice decision ([PROXY]), go on; (c) anything else, go on: each result it concerns reads "not established: open faithfulness finding" on the summary's first page | same ([DELEGATED] decisions; (a) is asked under `hands-off` too, and the run resumes hands-off) |

**Release column** (generated from `project.RELEASE`, `project.CURES` and `project.CLOSER`; `tests/doclint.py` checks it is current). Each cause code has a kind; `open` prints the kind's cure followed by the code's own text:

<!-- release-column:begin -->
| kind | codes | cure (`project.CURES`) | closes with |
|---|---|---|---|
| rerun | `adj-record`, `baseline`, `branch`, `commit-refused`, `dead-witness`, `dependencies`, `git-error`, `head-moved-operator`, `index`, `lane-output`, `missing-theory`, `no-baseline`, `no-round`, `record-cite`, `report`, `signoff-check`, `stray-file`, `stray-loop`, `tool-call`, `uncoded`, `unknown-retry`, `unsealed`, `unused-args` | fix the mechanical problem the code names, then re-run the check (close --cured re-runs it); a crash that persists: re-run the review by another route (a fresh round), never skip it | `close --cured`, re-running the `--check` recorded at open, `lanecheck.py --round <R>`, `make_report.py --check`, `phase0.py --readonly`, `signoff.py check --round <R>`, `tree_state.py --check` |
| restore | `agent`, `codex-roles`, `config`, `gitmeta`, `head-moved`, `no-pin`, `ownership`, `pin`, `pyc`, `reapproval-record`, `record-changed`, `record-fix-diff`, `resolution-trail`, `set-aside-changed`, `stop-trail`, `tool-patch`, `tooling`, `tree-changed`, `uncommitted-record`, `waiver` | go back to the last trusted version -- the pinned apparatus (git -C audits checkout <pin commit> -- <the files the FAIL names>), a committed record change (python3 audits/stops.py revert --stop S<n> --commit <the commit the FAIL names>: it restores the records that commit changed, committed as "revert <commit> (stop S<n>)", which integrity.py accepts once verified), an uncommitted one (git checkout <file>) -- then re-run the check; a FAIL in the committed history that no restore or revert clears (a past re-pin, a mistyped pin subject, a record its owner re-committed after a hand edit, an unverifiable tool-patch link, a damaged stop trail): the reviewed acknowledgment (python3 audits/integrity.py --ack-request --diagnosis "<what happened, why nothing it judges changed>"; a fresh reviewer judges it; then close --cured "acknowledgment AK<k>") | `close --cured`, re-running `integrity.py --check`, `tree_state.py --check` |
| redo | `auth-metadata`, `evidence-after-seal`, `independence`, `independence-path`, `lane-fault`, `owner-redo`, `prompt-changed`, `quote-unmatched`, `scope-changed`, `seal-mismatch`, `unauthenticated`, `unsettled` | restore the changed record if needed (git checkout <file>), set the affected round aside (stops.py set-aside <R> --reason "release self-cure of S<n>" --stop S<n>) and re-run its review in a fresh round (prompt.py 3; fresh lanes and adjudicator): its independence was compromised. An ADJUDICATED round is never set aside: restore what changed after its seal or commit (git checkout <the sealed or committed version> -- <file>) and re-run the check; a lane that cannot be restored is re-voted (the adjudicator's REVOTE NEEDED row, a fresh re-vote lane, "adjudicate R revotes"); an unsettled NOTE or carried item is settled by the round's adjudicator (its ADOPTED.md rows, integrity.py --commit-adjudication) | `close --cured`, re-running `integrity.py --check`, `lanecheck.py --round <R>`, `lanecheck.py --round <R> --settled`, `scope.py --verify --round <R>` |
| reprove | `axiom`, `axiom-own`, `build`, `drift`, `hard-token`, `hard-token-own`, `sorry`, `unlisted`, `unproved-meta` | change the Lean (rewrite the proof without the token or axiom, or restore the approved statement), commit, then run Phase 0 and the build | `close --cured`, re-running `fingerprint.py --check`, `phase0.py --readonly` |
| patch | `tool-bug` | if a read-only check fails because of a mechanical problem, fix it and re-run the check (close --cured re-runs it); if the pinned tool itself is wrong (it crashes, or misjudges this case): diagnose it and patch it through python3 audits/tool_patch.py begin --stop S<n> (RUN.md, "Tool patches": a fresh reviewer approves the patch; then close --cured "tool-patch TP<k>"); a fault in the proof-validity core (no patch may touch it): a Lean-side workaround, else stops.py core-fault (a fresh reviewer judges it), then close --core-fault <file> (what the check guarantees reads "not verified", never waited on); never edit a pinned script by hand | `close --cured`, re-running the `--check` recorded at open (a stop with none: `close --cured "tool-patch TP<k>"`, re-running the patch's regression test) |
| human | `ambiguity`, `codex-approval`, `env-unknown`, `interference`, `outward-action`, `unproved-goal` | a human stop: show the human the raw output and wait; close it with --human "<their answer, verbatim>" | `close --human` |
| disclose | `acknowledged`, `acknowledged-fault`, `before-pin`, `config-grew`, `docstring`, `escalation-cite`, `label`, `not-approved`, `pdf`, `pyc-cache`, `reader`, `reapproval`, `record-format`, `reissued`, `render`, `repinned`, `reverted`, `round-cap`, `run-log`, `selftest`, `status-unmapped`, `superseded`, `tool-fault`, `uncommitted-file`, `unproved` | not a stop in release mode: it is disclosed (stops.py disclose) | no stop: `stops.py disclose` |
| precondition | `decisions`, `deliver`, `deliver-stale`, `reader-check`, `unverified` | not a stop, in either mode: deliver-stale refuses project.py --deliver (a diff round); the others are notes it prints for you to judge, or document checks you fix (approver 2026-10-28) | no stop: `project.py --deliver` refuses on `deliver-stale` only; the others are notes |
<!-- release-column:end -->

### Tool patches (`release` mode only)

When a pinned check is itself wrong -- it crashes, or it misjudges this case (bench1: `result_status.py`
routed a correctly recorded inline hypothesis to the adjudicator; bench2: a diff round's scope check
read the round's own sealed verdict) -- you act as the maintainer. Decide first: **is the check
right?** If it is, apply the printed cure; real tamper, ownership, freeze, gitmeta and proof faults are
never patched. If it misjudged, go straight to a tool patch (never burn a cure that cannot work). A
human stop (the codes of kind `human`) is never a tool patch's subject. `dev` mode refuses all of this:
a tool fault stops the run and a maintainer fixes the tool.

1. `python3 audits/tool_patch.py begin --stop S<n>` (the stop stays open throughout, so nothing runs on
   the buggy tool). Diagnose it from the code and write `<rounds dir>/tool-patches/TP<k>/A1/DIAGNOSIS.md`
   (sections: the check; the failing case; the cause, `file:line`; the correct behaviour; why no
   faithfulness result depends on the change; whether the old behaviour is right elsewhere; then the
   lines `affects-review-inputs: yes|no` and `regression: tests/regressions/<name>.py`) and
   `A1/patch.diff`: `git -C audits diff --relative` of a minimal fix made in a scratch worktree, never in
   `audits/`. It may touch any file of the apparatus -- scripts, tests, Lean tails, and the protocol
   text (`AUDIT_PROTOCOL.md`, `RUN.md`, `run/`, `agents/`, `skills/`): a wrong instruction is patched
   like a wrong script (approver, 2026-10-26). It never touches the proof-validity core (below), the
   reviewer prompts that judge patches, core faults and acknowledgments or the code rendering them
   (`tool_patch.GUARDED`; this includes the common rules for subagents, which the reviewer receives),
   the git rules, anything outside `audits/` (the project's Lean), a round record, or what the author
   signed (`SIGNOFF*`, `APPROVED_FINGERPRINTS*`, `REAPPROVAL*` as `.json`/`.md`/`.pdf`/`.tex`; `signoff.py` and
   `run/reapproval.md` are tooling). It adds the NEW regression test,
   which takes `--apparatus DIR` and fails with the pinned apparatus, passes with the patched one (for
   a text patch: it reads the patched text). It may add other new files, under no Python module's
   name; it deletes and renames none. Prompts issued before the patch stay verified against what was
   issued (their committed hashes; a tool-patch review against the apparatus pinned at its issue);
   prompts after it are rendered from the patched text. A patch to `agents/auditor.md` or the common
   rules reinstalls the reviewer agent and the Codex roles at apply.
2. `python3 audits/tool_patch.py prepare --tp TP<k>` records the mechanical facts (`FACTS.json`): the
   regression test, every pure selftest of the first pin (and any the patch adds) on the patched tools,
   the blast radius (every read-only check of every round, pinned vs patched; a PASS->FAIL forces
   `affects-review-inputs: yes`), and the floor (the canaries of the first pin's `FLOOR`, each killed
   only by a selftest that passes on the patched tools unmutated: a hit needs two approvals). It refuses before review a
   failing fact (a) or (b), a file it may not touch (above), a new file with a module's name, a change to a
   guarded block, and a diff already rejected.
3. `python3 audits/tool_patch.py review --tp TP<k>` prints the spawn line of a FRESH reviewer (a
   general-purpose agent; Codex: `agent_type` `formalize_tool_patch_reviewer`, `fork_turns` "none"):
   never yourself, a lane or an adjudicator of the run. Seal its verdict exactly like a lane's
   (`lane_auth.py seal --verdict ... --sha256 ... --agent-id ...`). It approves or rejects.
4. **Rejected:** revise with its findings, write `A<n+1>/` (its `DIAGNOSIS.md` adds a section `## Earlier
   findings answered` naming each rejecting review of the run, on any stop, `TP<k> review-<n>-<m>.json`, with
   your answer; a review issued and never sealed counts as a rejection, and a diff once rejected anywhere in the
   run is never resubmitted, even with only whitespace or line numbers changed),
   prepare and review again (a new fresh reviewer sees every earlier attempt and finding). There is no cap
   and no stop. **The check was right
   after all, or a reviewer never returned:** `python3 audits/tool_patch.py withdraw --tp TP<k> --reason
   "<why>"`, then the printed cure (or a new tool patch). **Approved:** `python3 audits/tool_patch.py
   apply --tp TP<k>` commits the diff (`tool-patch TP<k> apply`) and re-pins (`pin (tool-patch TP<k>)`);
   then `python3 audits/stops.py close --stop S<n> --cured "tool-patch TP<k>"`, which re-runs the
   stop's check on the patched tools (a stop with no check: the regression test). If that still fails,
   the diagnosis was wrong: re-diagnose (a new tool patch, or the printed cure); never a stop.

`integrity.py --check` verifies every tool-patch link with the scripts pinned just before it, and again with
the first pin's scripts. A patch may never touch the proof-validity core -- `phase0.py` (the build and the
sorry scan), the axiom sweep (`axiom_sweep.*`, `axiom_sweep_tail.lean`), the freeze (`fingerprint.py`,
`fingerprint_tail.lean`, `olean_parts.lean`), `tool_patch.py` and `integrity.py`: refused at prepare and
apply whatever the reviewers say. A fault there is never patched, and in `release` never waited on: in `dev` it is
a maintainer's; in `release` withdraw the patch, then first try a Lean-side workaround (a pure refactor of the Lean
that the freeze check confirms, closed `--cured`); if none exists, the stop is closed as not established, in
two steps. (1) `python3 audits/stops.py core-fault --stop S<n> --core-fault <core file> --diagnosis "<the fault,
file:line; why no Lean-side workaround works>"`: the stop must be a tool bug whose check is the one that runs that
file (`phase0.py --readonly` for phase0.py and the sweep, `fingerprint.py --check` for the freeze, `integrity.py
--check` for integrity.py and tool_patch.py) and fails now, and every failure of the blocking checks must be that
file's own (a sorry beside a crashed sweep, a drift, an ownership FAIL keep their own cures); it records the
failure lines and prints the spawn line of a FRESH reviewer (as a tool patch's: never yourself, a lane or the
adjudicator), whose verdict you seal like a lane's. (2) After an approval, `python3 audits/stops.py close --stop
S<n> --core-fault <core file>`: it needs the sealed approval and the same failure lines. A rejection: revise and
request again, or take the ordinary cure; no cap, never a stop. A rejection means the reviewer saw a real problem
(a real sorry, axiom, changed statement or tampering) or a workaround: repeated rejections mean fix that problem,
whose own cure applies; `RUN_RECORD.md` lists every request with its verdict. A run whose reviewers never approve
does not deliver by this route (KNOWN_LIMITATIONS.md). After the close the run delivers with the consequence in
plain words on SUMMARY page 1 and in the REPORT ("Not verified: the check that every proof is complete could not
be run ...", per guarantee), each affected result marked "not verified: ...", and the check, the file, the
diagnosis, the failure lines and the verdict in `RUN_RECORD.md` only; it never claims that check passed, and
`--deliver` accepts no failure line but those the reviewer judged. Any other
tooling change is `FAIL[tooling]`, and a plain `pin (repin: ...)` in `release` may not change the tooling
(`FAIL[pin]`; the gitmeta re-pin changes none). If a patch may have changed what an earlier review was
shown (`affects-review-inputs: yes`), `scope.py` runs a full round scoped after it, and `--deliver` names it in
a note until one has been adjudicated. Tool patches are recorded only in `RUN_RECORD.md` (diagnosis, diffs, every reviewer
verdict, seals, commits, and the command a maintainer runs to re-check every link with the first
pin's scripts); the report names them only by its one "Checks weakened" line (details in
`RUN_RECORD.md`), and the summary, the sheet and `DECISIONS.md` not at all -- except that a result whose
status a patch made stronger than the run's first-pin tools make it is marked on SUMMARY page 1 and in REPORT
in plain words, for a reader who knows nothing of the mechanism ("<result>: this status was decided by a corrected
version of our checking software; the original version would have said <old>. ..."; which patch and the first
pin's status are in `RUN_RECORD.md`): `--deliver` recomputes it with the
first pin's `tool_patch.py` and `result_status.py` and names in a note a document without the line (or a REPORT
without the "Checks weakened" row): you write the line in plain words and the claims reviewer checks it.

An apply killed between its two commits leaves `FAIL[tool-patch] ... has no pin`: run `tool_patch.py apply --tp
TP<k>` again; it resumes (the approval and the byte-identical diff checked again, then the pin).

### History faults no cure clears (`release` mode only)

Some integrity FAILs live in the committed history, and no restore or revert can clear them: a past plain
re-pin that changed the tooling (once the tooling in force is a trusted pin's again), a pin committed under a
mistyped subject, an unverified `Revert ...`, a tool-patch link no verifier can run (never one that touched the
proof-validity core), a damaged stop trail, a bookkeeping record (a stop, reader, PDF or tool-patch record) committed
by the wrong step whose revert was tried and failed. They are never a human stop. A record that carries a judgement
(a lane's verdict or probe, `ADOPTED.md`, `PAPER_DEFECTS.md`, `SKIPPED.md`, `VACUOUS.md`, `DEVIATIONS.md`,
`INFORMAL.json`, `SIGNOFF.json`, `TARGET.json`, `STATEMENTS_BUNDLE.md`, an approval, an answer) is never acknowledged:
it keeps its real cure, `stops.py revert --stop S<n> --commit <C>` (also for an owner's own commit that a
check refuses: a record fix beyond its faulty cells, a touch of a set-aside round). It undoes C's change onto the
current content when that applies cleanly (later work stays); otherwise, when every later change was the owner's, it
puts back the content before C, and `integrity.py --check` then prints `FAIL[owner-redo]` for that record until a
fresh FULL round scoped after the revert is adjudicated and its `ADOPTED.md` rules every line the restore removed
(its adjudicator's prompt lists them): `REDO RULED <record> | <the line> | keep: <why>` or `drop: <why>`, each kept
line written back in the record. Code checks only that every line has a ruling and every kept one stands. Nothing is dropped silently, and none of it is a human stop. Open the stop on `integrity.py --check` as usual, then:
(1) `python3 audits/integrity.py --ack-request --diagnosis "<what each commit did, why no cure clears it, why no
statement, proof, verdict, adjudication, approval or check changed>"` records every current FAIL line it may cover,
each naming its commit, with the full diff of each named commit and the files of each named tool patch
(`acknowledgments/AK<k>/`), and prints a FRESH reviewer's spawn line (as a tool patch's: never yourself, a lane or the
adjudicator; Codex `agent_type` `formalize_tool_patch_reviewer`); seal its verdict like a lane's. Any `[pin]` line is
accepted, and stays acknowledged, only while the tooling in force is a trusted pin's (the first pin's, or a verified
tool patch's): restore it and re-pin first (`integrity.py --pin --repin` in release refuses a re-pin over changed
tooling). (2) Approved: `integrity.py --check` prints exactly those lines as `NOTE[acknowledged-fault]` (any other or
later line stays FAIL and needs its own request); close the stop `--cured "acknowledgment AK<k>"`. Rejected: revise
and request again (the next reviewer sees the rejection), or take another cure; no cap, never a stop.
`RUN_RECORD.md` lists each acknowledgment, and only it: none changes what the summary and the report say about the
results. `integrity.py --acknowledge` (the human's waiver) is dev mode only.

Interim rows (held back for later steps of this build, so they will change): `resolution-trail` (to be
removed) and `drift`
(its cure text to become "restore the approved statement"). `head-moved` and `gitmeta` are restores
(B1c): `tree_state.py --revert-foreign` reverts the whole foreign range and the check accepts it only
when HEAD's tree equals the baseline's (never by a commit subject); `tree_state.py --restore-gitmeta`
restores only the hooks and config keys of the Stage 1 snapshot in the pin, and writes only in
`<gitdir>/hooks`; `--revert-foreign` is refused while `gitmeta` fails and runs no hook. In release,
`env-unknown` (stop 3) is: a `user.*` or `credential.*` setting changed in the repository's own
(local or worktree) config -- the human's `~/.gitconfig` is not checked for these; in any scope
(local, worktree, global, system), a changed resolved hooks directory or `core.hooksPath`, or a
destination setting (a remote's url or pushurl, `url.*.insteadOf`/`pushInsteadOf`,
`http.*.extraHeader`, `branch.*.remote`/`pushRemote`, `remote.pushDefault`, `core.sshCommand`); a
`refs/replace/*` ref or `info/grafts` not in the snapshot; pinned history no longer an ancestor of
HEAD; a pin with no snapshot when the cure needs one (a re-pin adds it). In dev none of this is
checked against the snapshot: every git meta change is `FAIL[gitmeta]`, the human's.

## Logging

`RUN_LOG.md` is your record of the run and what a resumed conversation reads. Its sections, in
order: Intake, Checkpoint A, Stage 2, Rounds, Mechanical failures, Stops, Set-asides, Open
questions, Checkpoint C, Answered, Fresh readers, Current stage. What each holds is in
`run/stage1-setup.md` ("RUN_LOG.md sections"), which creates the log; `project.py --log` creates a
missing section. A [PROXY] decision is logged as "[PROXY <date>, operator for <who>; reversible]
…", a delegated one with the [DELEGATED …] tag above; an answered open question is marked
"(answered <date>: <answer>)", never deleted.

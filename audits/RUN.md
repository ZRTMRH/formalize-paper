# RUN.md — formalize and audit a paper in one conversation

**For the person.** Open Claude Code in your Lean project (the directory that holds `audits/`,
see `INSTALL.md`) and type `/formalize-paper`, or say *"Read audits/RUN.md and follow it."* Answer the intake questions.
After that the agent works on its own. It stops at three checkpoints:

- **A** confirms the setup.
- **B** asks the approver to sign off the statements, on a PDF with a box per result (or to let the
  agent approve them, which the report then discloses).
- **C** hands over the report.

It also stops if it needs a decision only a person can make. One intake question (5c) lets you
hand those decisions to the agent: after the statements (*statements only*), or from the start
(*hands-off*, which then needs you only at the intake and at A). The report says who decided
what. If it runs out of usage or the conversation ends, open a new one and say the same thing; it
resumes from the files.

**For the agent.** Everything below is addressed to you.

- `AUDIT_PROTOCOL.md` (same directory) holds the rules, the prompts and the reasons for them.
  Read it in full before Stage 1.
- This file decides **who launches what, in what order, and when to stop for the human**.
- Every prompt you hand a subagent is printed by `prompt.py`. You never compose one.

---

## The rules that replace opening new conversations

**Helpers.** For a long paper you may spawn author-side helper subagents to draft statements or
write proofs, in parallel, on separate files. They work FOR the author and are bound by everything
below exactly as you are; they are never used as reviewers, and nothing they write is a review.
Put every shared definition in one base file before drafting in parallel, and when merging drafts
check that two definitions of the same notion are equivalent before keeping one.

You will write the Lean, so you are its **author**, and the author does not judge its own work.
Subagents enforce that: each starts with only its prompt and the files on disk. Scripts check the
rest. This holds only if you keep your hands off, so:

1. **What gets examined is computed, never chosen.** `scope.py` writes each round's `TARGET.json`
   and decides which lanes run. The adjudicator re-derives it with `scope.py --verify`.
2. **Prompts pass through verbatim, as files.** Every subagent prompt is written to a file by
   `prompt.py … --write`, and the subagent is spawned with the one fixed sentence it prints ("Read
   the file … and carry out the task it describes, exactly"). Nothing you type reaches a reviewer;
   the adjudicator re-renders the files and checks them (`--verify-written`). Lane spawn messages
   additionally contain only the machine-generated authentication envelope: a random lane token
   from `prompt.py --lanes --write`, with only its hash committed under `.lane-auth/`. Never
   save that envelope to a prompt file or hand-compose it. The other exception is
   the escalation check, which gets the question and its evidence appended.
   **Lane completion, both Claude and Codex.** Spawn lanes in parallel with exactly their printed
   authenticated messages. As EACH finishes, inspect that child's actual completion result
   (not messages from siblings), require its expected verdict file and `LANE_COMPLETION` line,
   and run `python3 audits/lane_auth.py seal --verdict <path> --sha256 <owner-returned digest>
   --agent-id <originating child id>`. The owner computes this digest from its intended JSON
   bytes in memory before writing, so a token-preserving replacement before completion cannot
   be sealed. Never substitute a digest computed from the current disk file or from a sibling's
   message. The script validates the token/bytes and commits that one seal as `seal <R> <lane>`.
   A child that failed mechanically (a crash, a service or capacity error, no verdict file, no
   `LANE_COMPLETION` line) is a mechanical failure: re-run only that lane under rule 7, as below.
   A seal failure, a token or prompt-hash mismatch, or a failed lanecheck is an integrity failure:
   it stops the round, and it is a remaining stop at every involvement level (rule 8).
   Token commitments, seals and lanecheck apply at every involvement level, under Claude Code and
   Codex alike: they are mechanical steps, not decisions, and nobody is asked about them.
   Run the seal commands one at a time; never serialize the lanes themselves.
   Do not wait for the entire wave before sealing completed lanes. Parent exit 0 is not a
   child-success signal. Run lanecheck after all children; the adjudicator runs it again in its
   block (step 4, part A). It validates all
   expected commitments and immutable seals. A transcript containing spawn tokens is not a
   prompt file; siblings are forbidden to read parent/sibling transcripts. The verdict necessarily
   publishes its own token. Tokens are provenance challenges, not lasting on-disk secrets.
   For a verified mechanical failure, reuse that lane's original machine-generated envelope
   from the parent context, record the retry and new child id, and ensure the old child stopped.
   Never silently rekey an issued lane or overwrite a sealed verdict; a new audited version
   needs a new round. Do not rerun --write for lanes whose envelopes were already issued.
3. **Never use `subagent_type: "fork"`.** A fork inherits your whole context. Lanes are
   `auditor`; every other subagent is `general-purpose`.
4. **You never write or edit:**
   - lane verdicts, `ADOPTED.md`, `PAPER_DEFECTS.md`, `SKIPPED.md`;
   - `TARGET.json`, `FINGERPRINTS.json`, `INFORMAL.json`, `SIGNOFF.json`;
   - the approval file (only `signoff.py approve` writes it);
   - the audit scripts, `AUDIT_PROTOCOL.md`, this file, `audits/agents/`,
     `~/.claude/agents/auditor.md`.

   Your files are `RUN_LOG.md`, `AUTHOR_NOTES.md`, `DEVIATIONS.md` and `OUTCOMES.md`.
   `integrity.py` checks ownership from git history at every adjudication.
5. **Commit messages carry ownership.** Use exactly the messages the blocks give:
   `scope <R>`, `adjudicate <R>`, `approve <R>`, `pin`; the completion script alone commits
   seals as `seal <R> <lane>`. Integrity fails a protected record
   committed under any other message.
6. **ADOPT rows are implemented as written.** If you think one is wrong, record
   "not implemented — disagree: <reason>" in `OUTCOMES.md`. It goes to the human.
7. **Never re-run a lane or adjudicator hoping for a different answer.** A re-run is allowed only
   after a mechanical failure: a crash, no file written, a usage limit, or a service error (for
   example Codex's "Selected model is at capacity"); never after an integrity or protocol STOP. Record it in
   `RUN_LOG.md`.
8. **A subagent or script that says STOP stops the round.** Show the human its raw output. Do not
   repair the cause and carry on. This holds at every involvement level; the one narrow exception
   is in "Stops that remain at every level" (a clerical RED your own edit caused).
9. **Write no persistent memory about this run until Checkpoint C.** Subagents receive the user's
   memory index, so a note you save becomes background every later reviewer sees.
10. **Quote script output; never restate it.** Phase 0's verdict is its `PHASE 0 RESULT` table.
11. **Run Phase 0 in author mode only on a committed tree.** It refuses to save the baseline
    otherwise. The order is always: change, commit, then `phase0.py`.
12. **Tag every monitor you start.** A polling loop you start yourself (waiting for a build, a
    file, a child) must carry `FORMALIZE_PAPER_OPERATOR=1` in its environment, for example
    `FORMALIZE_PAPER_OPERATOR=1 bash -c 'until …; do sleep 30; done'`. `lanecheck.py` treats an
    untagged polling loop started after the round's scope, with its cwd in the project or started
    by a lane process, as a lane's: it flags it, and `--kill` ends it. Prefer the harness's own
    blocking waits to loops at all.

---

## Running under the Codex CLI (experimental)

This file is written for Claude Code. Under the Codex CLI everything is the same except the
following, which applies wherever this file says to spawn a subagent or to ask a question:

- **Python environment (required).** Install before starting Codex. Every spawned command must
  receive `PYTHONDONTWRITEBYTECODE=1` through `[shell_environment_policy.set]` in Codex config.
  `codex/install-codex.sh` adds it to the user and project configs, preserving other settings;
  any environment include allowlist must retain this variable. Check with
  `python3 audits/project.py --env-check` in the session.
  This prevents pre-run helper imports from leaving unpinned bytecode in the apparatus. Keep
  script-level `sys.dont_write_bytecode = True` guards as well. Never edit config/tools or
  delete unexpected bytecode to bypass an integrity failure during a pinned run.
- **Spawning.** Claude Code: Agent tool, `auditor` for lanes, `general-purpose` otherwise.
  Codex: the built-in spawn tool, with `agent_type` set to `formalize_auditor`,
  `formalize_adjudicator`, `formalize_informalizer`, `formalize_reader`, or `formalize_writer`
  as appropriate. Always request fresh context: `fork_turns="none"` on the current backend,
  or `fork_context=false` on the v1 surface. Never omit that flag, reuse a reviewer, or fork
  the author conversation. Use exactly the printed message (including its lane authentication
  envelope), with no author commentary. Spawn lanes in one wave; seal each as it completes.
  The generated roles set model and medium reasoning. Validate roles with
  `python3 audits/codex_agents.py --check .codex/agents` before spawning; integrity pins them.
  If the built-in tool/role is unavailable, STOP rather than doing its review yourself.
  `python3 audits/codex_spawn.py --kind auditor "<message>" … [--jobs N]` (or `--kind general`)
  remains an explicitly selected fallback, not an automatic retry after a child failure.
- **The escalation check** runs as a general-purpose subagent with a question appended to its
  sentence; Codex has no built-in general-purpose reviewer role (only the five generated roles),
  so there is nothing to run it as. Under Codex, record the escalation in `RUN_LOG.md` and ask the
  human instead (under a delegating level, decide as in "How you decide" unless it is a remaining
  stop).
- **Questions to the human.** Claude Code: the question tool where there are options. Codex: ask
  in plain text, numbering the options. This applies only to what the involvement level still
  puts to the human (under `hands-off`: the intake, Checkpoint A and the remaining stops).
- **Command approval prompts are not checkpoints.** Codex may ask the person to approve a command
  the sandbox blocks (by default any write to the project's `.git`: branch, staging, commit; F9).
  Such an approval is the harness's, not the protocol's: it is never a decision, never the human's
  answer to a question, and never a substitute for a checkpoint. A delegating level
  must not wait at them, so such a run is started with the project's `.git` writable
  (`--add-dir <project>/.git`, `codex/README.md`, "Git commits without approval prompts"). That is
  the ONLY sanctioned sandbox change. Never use `--dangerously-bypass-approvals-and-sandbox`,
  `danger-full-access`, an approval policy of `never` or wider writable roots; never request an
  approval to get past a STOP, to run a reviewer, or to retry a failed child outside the sandbox;
  never ask the person to approve a command just so a delegated run can continue. If an approval
  is requested anyway under a delegating level, it is an environment fault: log it under
  "Mechanical failures" and wait for the person; it is not a decision you may answer or record as
  delegated.
- **No network in the sandbox.** Codex's workspace-write sandbox has the network off, so
  `lake exe cache get` (Stage 1) cannot run inside the session. Fetch the cache and build once
  BEFORE starting Codex (INSTALL.md); if the cache is missing inside the run, that is an
  environment fault for the person (a remaining stop), never a reason to turn the network on.
- **Sandbox failures and logs.** Never treat a child exit code or final summary as proof that
  its record exists: require the expected files and run the prescribed checks. Do not retry a
  sandbox failure outside the sandbox automatically. Record the actual `--log-dir` path (or
  the default printed final-message path) in `RUN_LOG.md`; it overrides the cache location.
- **Protection and child results.** Reviewer restrictions are protocol restrictions enforced
  by detection, the same design as Claude Code, **not per-agent filesystem isolation**.
  Built-in agents inherit the parent's sandbox. The orchestrator must inspect every child's
  result and expected output files and run the prescribed checks: the parent's exit code can
  remain 0 after a child fails. A child error or missing output is a mechanical failure (rule 7);
  a failed seal or check is an integrity failure (a remaining stop at every level).
- **Service errors.** A turn of yours, or a child's, that ends on a service error ("Selected model
  is at capacity", overloaded, 5xx) is a mechanical failure (rule 7). The person resumes you
  (`audits/watchdog.py`, which they may run next to the session, only notifies them; it never types
  into the session). When you are resumed after one, keep every completed judgment: collect finished children's results and
  seal them, and retry only what failed, with its original message. A resume message never
  answers a question, approves anything or lifts a STOP.
- **Waiting for children.** Wait with the blocking `wait_agent` tool and a long `timeout_ms`
  (minutes: 600000, or the largest value it accepts), which returns as soon as a child finishes.
  Never poll with short waits (the reference run made 74 `wait_agent` calls at 10 s, plus `sleep`
  and `list_agents` calls): every poll is a new model turn that re-sends the whole context, which
  costs tokens and time. Check status without waiting (`list_agents`) at most once every 10
  minutes. Seal each lane as its wait returns.
- **Parallel attribution.** The four live negative controls passed after token commitments
  and owner-returned completion seals were added. Treat unsealed, unauthenticated or changed
  verdicts as failures; never recompute a seal to make an altered verdict pass. See the shared
  lane-completion rule above. Built-in agents execute within inherited sandbox permissions,
  without launching a nested CLI. They do not have Claude's per-role tool allowlist.
- **Reviewer definition.** The Codex auditor TOML is generated from the body of the same
  `audits/agents/auditor.md` installed at `~/.claude/agents/auditor.md`. Other role instructions
  derive from the common subagent block in AUDIT_PROTOCOL.md; their full tasks remain the same
  generated prompt files Claude uses. `integrity.py` checks their canonical derivation and
  pins the actual TOML hashes. Never edit role files during a pinned run.


## Stage 0 — resume or intake

Run `git branch --show-current` and `python3 audits/prompt.py --show`.

- **Resume** only if a project matches this branch **and** its `<ROUNDS-DIR>/RUN_LOG.md` exists.
  Then read the log, resume at `## Current stage`, tell the human in two lines where you are, and
  skip the intake.
- **Otherwise this is a new run,** even if the branch belongs to an older project. Do the intake;
  Stage 1 creates the run's branch (from the project's main branch, or from upstream master in a
  clone of Mathlib).

**The intake: ask these in ONE message.** Use the question tool where there are options; take
free text where there are none. Derive everything else yourself.

1. **Source.**
   - Where is the paper? `.tex` is preferred. It must be inside the project (for example
     `paper/`): a file outside it makes every reviewer's read ask for permission, and the config
     check refuses it.
   - Is it the authors' own text, and which version?
   - Is it unpublished or confidential? If so, `confidential: true`: no subagent uses the network,
     and nothing is pushed except to private remotes, and only if question 6 allows it.
2. **Range.**
   - The whole paper, or which results?
   - Which result(s) are **the goal**? (This fills `goal_results`.)
   - Which environments count as results: Theorems, Lemmas, Propositions, Corollaries,
     Definitions, and also Claims inside proofs, Facts, Constructions, Remarks? Default: every
     numbered environment.
3. **Literature results the paper cites.** Formalize each, or take it as an explicit named
   hypothesis? Default: hypothesis, unless a configured library has it. (This fills
   `literature_hypotheses`.)
   Which Lean libraries besides Mathlib may the formalization use? Default: Tau Ceti
   (`TauCetiProject/TauCeti`; it has, for example, graphons and dense graph limits). Every listed
   library is searched before a result is skipped for missing theory; one is added to the
   project as a Lake dependency only if something from it is actually used. (This fills
   `libraries`. A library other than Mathlib is less vetted: its definitions are checked before
   use, see "Missing theory".)
4. **Library work.**
   - Faithfulness only. This is the default: `goal: faithfulness`, prior-art lane off.
   - Or also check Mathlib for duplicates and list Mathlib-PR candidates:
     `goal: library-contribution`, prior-art lane on.
5. **Budget and checkpoints.** Ask 5c before 5d, and 5d only if the answer to 5c is (a) or (b).
   - 5a. Budget: `light`, `standard` (default) or `thorough` (table below).
   - 5b. Which subscription pays?
   - 5c. **Involvement.** Ask exactly this:

     > How involved do you want to be after the intake and Checkpoint A (where you confirm the
     > setup, right after this message)? After Checkpoint A the run normally waits for you twice
     > more:
     > - Checkpoint B (after the Lean statements are written, before any proof): approve that
     >   each Lean statement says what the paper says, and answer open questions (for example:
     >   Mathlib lacks a theory the paper uses — build it, assume it as a named hypothesis, or
     >   skip that result?).
     > - Checkpoint C (at the end): decisions such as keeping or dropping hypotheses the proofs
     >   do not need, claims that hold only vacuously (true only because nothing satisfies their
     >   hypotheses), results not formalized, and limits of the review (what the reviewers could
     >   not check).
     >
     > Where the agent decides for you, it follows the recommendation of the adjudicator (a
     > separate agent that did not write the code) if there is one. Otherwise it keeps the paper's
     > statements and hypotheses, never generalizes a statement, and takes missing theory as a
     > named hypothesis: it never builds a large library or skips a result on its own.
     >
     > **(a) Involved** (default): you decide at B and C. You keep every decision; the run waits
     > for you twice.
     > **(b) Statements only:** you approve the statements at B; the agent decides everything
     > after that. If a statement you approved must change later, the run stops and asks you. You
     > keep the statement sign-off; you give up the end-of-run decisions.
     > **(c) Hands-off:** the agent decides at B, at C and at every later stop, and finishes the
     > run without asking you. When it has no written recommendation it keeps the paper's
     > statements and hypotheses and assumes missing theory as a named hypothesis. The report
     > states that no human checked that the Lean statements say what the paper says, nor any
     > later decision. Each decision is explained, and can be reversed later, but a reversal may
     > need new proofs and new audit rounds. You keep the setup (Checkpoint A); you give up the
     > statement sign-off and every later decision.
     >
     > Whatever you choose, the run still stops and waits for you if: a goal result looks false or
     > unprovable as stated (you will be shown why and asked how to proceed); something would be
     > pushed or sent to the authors that you did not allow here; the audit records fail an
     > integrity check; or the computer needs something only you can provide (a login,
     > administrator rights, more quota or payment, or deleting your own files). You cannot change
     > this choice once the run starts, short of starting a new run.

     This fills `involvement` (`involved`, `statements-only` or `hands-off`) and
     `involvement_answer` (the answer, verbatim). What each level hands to you, the agent, is in
     "Involvement levels and delegated decisions" below.
   - 5d. (Only under (a) or (b).) Who approves the statements at Checkpoint B? It should be
     someone who knows the mathematics. (Under (a) only, they may still choose at Checkpoint B to
     let the agent approve; the report then says the statements were not reviewed by a human.
     Under (b) the approver approves the statements themselves.)
6. **Deliverables.**
   - Who reads the report?
   - Where should the report PDF and the sign-off PDF be copied? Default: `deliverables/` in the
     project (git-excluded); a copy anywhere else asks for permission, or the person makes it.
   - May the branch be pushed, and to which remote (for a confidential paper, a private one only)?
     May the audit record (`audits/`, its own git repository) be pushed, and where?
   - Will defects be sent to the authors?
7. **Anything else I should know?** For example: known errors or doubts, conventions, deadlines.

**Checkpoint A.** Show the derived setup on one screen:

- title, authors and version, from the source;
- the project name and branch;
- the namespace and `lean_lib` name;
- the goal results;
- the indexed environments;
- the literature hypotheses;
- the libraries besides Mathlib (`libraries`), and any result already known to need theory none
  of them has, asked as in "Missing theory" (Stage 2);
- `confidential`;
- the lanes, budget and round cap;
- the approver (none under `hands-off`);
- the involvement level, with the human's answer to 5c verbatim, and in one line what it means
  (who decides at B, at C and in between);
- the report destination;
- push yes or no.

Proceed only on the human's OK.

| budget | lanes in diff rounds (`lanes` in the config) | diff-round cap |
|---|---|---|
| light | correspondence, paper-faithfulness, non-vacuity | 2 |
| standard | + substantiveness | 4 |
| thorough | + substantiveness | until a round adopts nothing |

Prior-art is added only if question 4 said so. The statement round and the final full round run
fixed lane sets whatever the budget (`scope.py` decides). When the cap is reached and ADOPT rows
are still coming, stop and ask (under a delegating level: decide, see below).

## Involvement levels and delegated decisions

The intake's question 5c sets who takes the decisions this file otherwise puts to the human. It
is frozen with the rest of the configuration at the pin (`involvement` is a scope key). The
intake and Checkpoint A are asked at every level. Only the 5c answer sets the level, and it does
not change during the run: a different level means a new run. A mid-run "just proceed" or
"decide yourself" is not a level change (at the `involved` level it is a [PROXY], as before).

| level | Checkpoint B (statements, its QUESTION rows, missing theory) | after the human's Checkpoint B answer (Checkpoint C, and every stop in between) |
|---|---|---|
| `involved` (default) | the human | the human; your provisional choices are [PROXY] and go back to the human at C |
| `statements-only` | the human, who types the answer; never a [PROXY] (if they are away, stop and wait) | **delegated** to you, except a change to a statement the human approved (a remaining stop) |
| `hands-off` | **delegated** to you: nobody is asked | **delegated** to you |

**A delegated decision is final, not provisional.** Take it, carry it out, and record it in
`RUN_LOG.md` where you take it, with this tag, exactly:

> `[DELEGATED <date>, operator under <level> (intake); reversal: <cost>] <decision> — <reason>`

`<cost>` is what reversing it would take, one of: `none` (nothing to redo), `re-prove` (proofs
change), `re-approve` (a statement changes, so a new sign-off), `new round` (a new audit round).
Any other spelling (`[Delegated …]`, `reversible`, a bare `[DELEGATED]`) is refused by the report
check and by `decisions.py --check`; in prose write "delegated" without brackets. It is not put
to the human again. `decisions.py` lists every one in `DECISIONS.md` (as decided, not as a
question), and the report counts and lists them. [PROXY] is for the `involved` level only,
exactly as before; under a delegating level a [PROXY] tag is refused, and a line never carries
both.

**How you decide.** A *written recommendation* is an adjudicator's ADOPT row (implemented as
written; record a disagreement in `OUTCOMES.md` as a note) or another independent agent's
written recommendation in the record (for example an escalation check's ANSWERABLE). Never
follow a recommendation you wrote yourself: `DECISIONS.md`'s Recommendation field is yours, so
under a delegating level it names either the adjudicator's recommendation it follows or the
conservative option below. Where there is no written recommendation, take the conservative rule:
- keep the paper's statements and hypotheses (a hypothesis the proofs do not need stays);
- never generalize or strengthen a statement;
- take a missing literature result or missing library theory as an explicit named hypothesis,
  always: never build a large library, never skip the result;
- a literature hypothesis later proved stays a hypothesis (it is not retired; you never re-pin);
- at the round or budget cap: implement the round's ADOPT rows, start no further diff round, and
  go to Stage 5 (its full-scope round runs whatever the budget); disclose what was not
  re-checked.

The escalation check (Stage 3) still runs before a mid-stage stop; a NEEDS-HUMAN answer is then
decided this way instead of asked, unless the stop is one of the remaining stops below. Where the
escalation check is not available (under the Codex CLI), the question is decided this way too.

**Statement changes after approval.** Under `statements-only` any change to a statement the human
approved is a remaining stop: ask them ("Re-approval"). Under `hands-off` you re-approve, but a
delegated re-approval never strengthens or generalizes a statement, and weakens one only to turn
missing theory into a named hypothesis. Before the Lean edit, commit a `RUN_LOG.md` line
`[DELEGATED …; reversal: re-approve] change <declaration> — <reason>`; the freeze check's DRIFT
for that declaration, after that commit, is the change you logged. Any other DRIFT is an
integrity failure.

**Stops that remain at every level.** Whatever the level, stop and tell the human, and wait:
- anything outward-facing that the intake did not authorize: pushing, sending anything to the
  authors, publishing;
- an integrity failure: approved statements changed (the freeze check reports DRIFT not logged
  beforehand as above), audit records tampered with or a record-ownership violation, tooling
  changed from the pin, a lane writing where it may not, a lane token, completion seal or prompt
  hash that does not match -- anything `integrity.py`, `tree_state.py`, `lanecheck.py`,
  `lane_auth.py` or the freeze check flags. Rule 8 holds for these unchanged:
  show the raw output, do not repair the cause and carry on. A `tree_state.py` failure about git
  hooks, git config or rewritten history ("GITMETA" lines) is cleared only by the human, after
  they have checked the hook, the config entry or the history: they delete
  `audits/.tree-baseline.json`, and the next Phase 0 records a new baseline. You never delete it;
- a goal result (the intake's `goal_results`) that appears false or unprovable as stated;
- an environment fault whose fix needs the human: a login or credential, administrator rights,
  more quota or payment, or deleting the user's own files. Say what is needed and why. Try first,
  logging each attempt in `RUN_LOG.md` under "Mechanical failures": retry failed downloads
  (`lake exe cache get` again; it can partly fail), re-run the build, check that the Mathlib and
  toolchain pins match, clear and rebuild the project's own build outputs (never the user's
  files), wait out a usage limit and resume, and free space only in the run's own scratch and
  build directories.

One narrow exception, under a delegating level only: a RED from a **document check**
(`make_report.py --check` inside Phase 0, or `decisions.py --check`) whose cause is text **you**
wrote in `AUTHOR_NOTES.md`, `DEVIATIONS.md`, `READER_NOTES.md` or `DECISIONS.md` -- for example an
undefined identifier in a report source -- may be repaired instead of stopping, by a
meaning-preserving edit of that text only (spelling, identifiers, markup; never deleting an entry
or a row). Log the diff as a [DELEGATED] decision. An edit to `DEVIATIONS.md` or `AUTHOR_NOTES.md`
after the last audit round is disclosed in `DECISIONS.md` as a change after the last audit round.
The exception never covers the integrity failures above, Phase 0's build, sorry, axiom or freeze
checks, a record owned by another step, a Lean file, or a RED you did not cause.

## Stage 1 — setup

0. **No bytecode.** Run `python3 audits/project.py --env-check` (it must print `ok`).
   Every command of the run must have `PYTHONDONTWRITEBYTECODE=1`: bytecode a helper leaves in
   `audits/` is unpinned code, and `integrity.py` stops the round on it. Under Claude Code,
   `install.sh` puts `"env": {"PYTHONDONTWRITEBYTECODE": "1"}` in the project's
   `.claude/settings.json`, which Claude Code reads when the session starts; under Codex,
   `install-codex.sh` sets it in `[shell_environment_policy.set]` (see the Codex section). If the
   check fails, this is an environment fault for the human (at every level): ask them to add the
   setting (`python3 audits/claude_settings.py .claude/settings.json`) and restart the session in
   the project. Never delete bytecode to get past an integrity failure.
   **Permissions.** The run uses Claude Code's normal permission mode; `install.sh` allowed exactly
   the commands this file runs (INSTALL.md, "Permissions"). Never ask the human to switch to
   `bypassPermissions` or `--dangerously-skip-permissions`, and never suggest it to save prompts.
1. **Branch.** Create the run's branch from the current commit: `git switch -c <branch>`. Then
   run `lake exe cache get`, which downloads prebuilt Mathlib in minutes.
   - *In a standalone Lake project* (one that requires Mathlib, the usual setup), branch from its
     main branch.
   - *In a clone of Mathlib itself,* branch from a fresh upstream master instead:
     `git fetch upstream && git switch -c <branch> upstream/master` (`upstream` is the
     leanprover-community/mathlib4 remote; if the clone only has `origin` pointing there, use
     `origin`). Never branch from a stale local `master` blindly: if its toolchain differs from
     the built tree, Mathlib recompiles from source, which takes hours.

   If Mathlib starts compiling from source anyway, fix the cache first, at every level: check that
   the toolchain and the Mathlib pin match the cache, and run `lake exe cache get` again (it can
   partly fail). Stop and tell the human only if the cache still cannot be obtained ("Stops that
   remain at every level", environment faults).
2. **Lean files.**
   - Add a `lean_lib <Name>` of its own to the lakefile. Never make it a default target of a
     Mathlib clone, so that a plain `lake build` of Mathlib never touches it.
     - `lakefile.toml`:
       ```
       [[lean_lib]]
       name = "<Name>"
       leanOptions = { autoImplicit = false }
       ```
     - `lakefile.lean` (in a Mathlib clone, after the `lean_lib Counterexamples` entry):
       ```
       /-- Formalization of <source citation>. Not part of Mathlib. -/
       lean_lib <Name> where
         leanOptions := #[⟨`autoImplicit, false⟩, ⟨`pp.unicode.fun, true⟩]
       ```
   - Create `<Name>.lean`, which imports every project file.
   - Create `<Name>/Main.lean`, holding the index table: `| Theorem 1.1 | \`thm_1_1\` |`.
     **Backticks are for Lean names only; write mathematics as `$…$`.** `index_strict` enforces
     this.
   - If the source is `.tex`, compile it once: `python3 audits/project.py --compile-source <file.tex>`
     (xelatex twice, shell escape off, into `.formalization-work/source-build/`). Take result
     numbers from its `.aux`, never by counting.
3. **Config.** Write `audits/projects/<name>.json` with every field of `audits/project_template.json`,
   plus `index_strict: true`, `goal_results`, `literature_hypotheses`
   (`[{"lean": "<Name>.ErdosHyp", "paper": "[5, Thm 2]"}]`) and `confidential`.
   - `source_pdf` may be the `.tex`.
   - `source_id` and `source_cite`: for an unpublished paper, use authors, title and the file's
     date.
   - `base_commit` is the commit the branch was created from.
   - `sweep` is `{"mode": "import", "module": "<Name>", "min_decls": 10}`.
   - `lanes` follows the budget.
   - `involvement` and `involvement_answer` from question 5c (`involved` and `"default"` if the
     human took the default).
   - `calibration` is `"none recorded yet"` for each lane.
   - `work_dir` is a persistent directory for the helpers' drafts, by default
     `.formalization-work/<name>` (relative to the project root: inside the project, excluded from
     its git history, and covered by the project's permission rules). Create it with
     `python3 audits/project.py --init-work-dir`. A path under `/tmp` or the system's temporary
     directory is refused (`prompt.py --show` reports it).
   - Rewrite `blind_spots` for this source.
   - `standing_defers` gets one entry per literature hypothesis (id, item naming the hypothesis,
     reason "literature result taken as a hypothesis; non-vacuity cannot exhibit a witness",
     revisit_when "never"). Without these, every round reports it UNCOVERED and the loop never
     exits.
   - **No value may contain `<<`.**
4. **Checks.** `python3 audits/prompt.py --show` lists no unfilled blank, and
   `python3 audits/selftest_all.py --project <name> --fast` passes.
5. **Commit and pin.**
   - Create `<ROUNDS-DIR>/RUN_LOG.md` (format at the end). Record the intake answers and the
     Checkpoint A approval.
   - Commit the Lean scaffold.
   - Commit the audits repo: `git -C audits add -A && git -C audits commit -m "setup <name>"`.
   - Run `python3 audits/integrity.py --pin`, then commit **only** that file, with the message
     it prints (`pin`).

   From here on the apparatus and the scope-defining configuration are frozen for this run.

## Stage 2 — statements first, then Checkpoint B

1. **Write the statements.** Formalize every in-scope definition and the **statement** of every
   in-scope result, each proof `sorry`.
   - Literature hypotheses are named `Prop`s or `structure`s taken as explicit arguments, never
     `axiom`s. Before assuming one, spend a few minutes on "can we just prove it?": a lane once
     proved a cited result in 141 lines. A literature hypothesis that is later proved stays an
     argument (the set is fixed at Checkpoint A); land the proof as a theorem that discharges it,
     and ask the human at Checkpoint B whether to retire it. Retiring it changes a frozen config
     key, so it is done only with the human's OK, as a stated re-pin
     (`integrity.py --pin --repin "retire literature hypothesis <name> (approved <date>)"`).
     Under a delegating level it is not retired: it stays an argument, and you never re-pin.
   - **Test every definition before the statement round,** against the paper's own examples and
     against degenerate cases: empty matrix or set, zero rows or columns, the smallest lengths and
     sizes, `k = 0`, `sInf ∅`, truncated `ℕ` subtraction. Keep each test as an `example`. Most
     statement defects are definitional, and they show up exactly there.
   - **Reading choices and paper defects need evidence in the library.** When a definition departs
     from the paper's literal text because the literal text is wrong, commit the counterexample
     as a named `theorem`/`example` and cite it in the docstring and in `AUTHOR_NOTES.md`. Scratch
     files are invisible to auditors, and the adjudicator will not record a paper defect whose
     witness is not in the library.
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
   - Follow Phase 1's habits.

   Commit, then run `python3 audits/phase0.py --statements`. It must say GREEN; the sorry scan and
   the axiom sweep are waived.
2. **Scope.** Run `python3 audits/prompt.py 3 --full` and note the round name `<R>`
   (`<DATE>-full-<HASH>`). Then:
   ```
   python3 audits/scope.py --statements --round <R>
   python3 audits/signoff.py bundle --round <R>
   git -C audits add -A <ROUNDS-DIR-IN-AUDITS>/<R> && git -C audits commit -m "scope <R>"
   ```
   If `bundle` reports a PROBLEM (an index name that does not resolve, a definition whose source
   is missing), fix the index or `lean_files`, commit, and start this step again.
3. **Review.** Write the prompts: `python3 audits/prompt.py --lanes --round <R> --batch 60 --write`
   and `python3 audits/prompt.py --prompt informalizer --round <R> --write`. In ONE message, spawn
   every lane (type `auditor`) and the informalizer (general-purpose), each with exactly its printed
   line (for a lane: everything after "with:", its lane token included). **As each lane returns,
   seal it** from that child's own result: `python3 audits/lane_auth.py seal --verdict <verdict>
   --sha256 <sha256> --agent-id <agentId>`, with `verdict` and `sha256` from the
   `LANE_COMPLETION {…}` line of that child's result and `agentId` from that result (Codex: the
   child's thread id); it commits `seal <R> <lane>`. When all lanes are sealed, run
   `python3 audits/lanecheck.py --round <R>`. A seal or lanecheck failure is an integrity failure
   (a remaining stop at every level). When `INFORMAL.json` exists, write and spawn the sign-off
   writer the same way (`--prompt signoff-writer --round <R> --write`).
4. **Adjudicate.** `python3 audits/prompt.py 4 --round <R> --write`, and spawn the adjudicator
   (general-purpose) with the printed sentence. Its block runs `phase0.py --readonly --statements`.
5. **Implement.** Run `python3 audits/prompt.py 5 --round <R>` and do what it says, using
   `phase0.py --statements`. Decide the round's QUESTION rows that shape statements first (ask the
   human; record the answers in `RUN_LOG.md` "Open questions"; under `hands-off`, decide them
   yourself as delegated decisions), so the next statement round sees them implemented. **If any statement or definition changed,** the sheet no longer
   describes the Lean: commit, and go back to step 2 with a new round.
6. **Prepare the sheet.** Run `python3 audits/signoff.py check --round <R>`. It must report 0
   problems; if not, rerun the sign-off writer (a mechanical failure), never edit its JSON. Then
   run `python3 audits/signoff.py render --round <R>`, which writes `SIGNOFF.pdf` and fails if a
   character would be dropped. Then run the **fresh-reader check** on the sheet (see "Fresh-reader
   check" below; `prompt.py --prompt fresh-reader --doc signoff --round <R> --write`). It includes
   the checks formerly called the pre-approval check. Never edit the sheet. Fix a blocking finding
   in one of these ways:
   - through `AUTHOR_NOTES.md`, which the sign-off writer reads; then rerun the writer;
   - through the generator `signoff.py`, with a stated re-pin; then render again;
   - if the Lean must change, commit it and go back to step 2 with a new round (it is a new sheet).

   A writer rerun is committed as `adjudicate <R> (sheet re-written: <why>)`, since `SIGNOFF.json`
   belongs to that step, and logged under "Mechanical failures" with its reason. Then run the gate:
   `python3 audits/readers.py --doc signoff --round <R> --check`. It must pass before you ask the
   Checkpoint B question.
7. **Missing theory.** Never decide a library gap yourself -- not by skipping, not by **narrowing**
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

   Record the answer verbatim in `RUN_LOG.md`. If such a gap appears later (Stage 3 or an audit
   round), stop and ask the same question before going on. A skip of this kind never enters
   `SKIPPED.md` without the human's recorded answer, and its "how this was checked" cell names
   every library searched. Ideally this step runs before the sign-off sheet (step 6): if the human
   chooses to build the theory, the statements change and a new sheet and round follow.

   **Under a delegating level** these are not asked when the level delegates them (`hands-off`:
   always; `statements-only`: a gap that appears after the Checkpoint B answer). Take option
   **(2)**, the missing theorem as a named hypothesis, record it as a [DELEGATED] decision with
   the search you made, and go on; never take (1) or (3) on your own.
8. **Checkpoint B.** (Under `hands-off`, do not ask: see "Under `hands-off`" at the end of this
   step.) Ask the approver, in the terminal, exactly this question (fill in the
   counts and the path), and wait for the answer:

   > The Lean statements are ready for your sign-off: `<path to SIGNOFF.pdf>`. It has <N> results:
   > <o> match the paper; <g> differ from it only through a convention stated once at the top of the
   > sheet (G1, G2, …); <c> are marked CHECK because they differ in a way you should look at. There are
   > also <q> open questions only you can decide, listed below. How do you want to approve?
   > **(a)** I will read SIGNOFF.pdf and approve all of it.
   > **(b)** I will read SIGNOFF.pdf and list the results (or conventions G1, G2, …) I reject. A
   > rejected result is not approved: the report lists it as excluded, and its statement can be
   > revised and put to you again.
   > **(c)** Let the agent approve everything on the sheet without my reading it. The report will
   > then say that no human reviewed the statements.

   Under the question, list every QUESTION row from `ADOPTED.md`, each with enough context to
   decide (AUDIT_PROTOCOL.md, "Documents a human reads"). Write that list to
   `<rounds dir>/QUESTIONS-B-<R>.md` first, run the fresh-reader check on it (`--doc questions
   --round <R>`), and gate it, before asking. Above the question, print verbatim any
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

     Prefix each with `python3 audits/`. Add `--note "<one sentence>"` when the record needs it,
     e.g. results the approver approved personally inside a (c) approval. Commit with the message
     it prints (`approve <R>`).
   - Global differences at the head of the sheet are approved once each; under (b) a global left
     unticked excludes every result whose row cites it (the sheet lists them under "Used by").
   - QUESTION rows under (c): approve the sheet; for each QUESTION row the approver did not answer,
     you may make a provisional choice so the work can continue. Log it as a [PROXY] decision in
     `RUN_LOG.md`, keep it under "Open questions", and put it to the human at Checkpoint C.

   **Under `hands-off`, do not ask.** The sheet is still prepared and gated (step 6), since it is
   delivered. Then approve it yourself:
   `python3 audits/signoff.py approve --round <R> --by agent --how blanket --note "hands-off chosen at intake: <verbatim answer>"`,
   commit `approve <R>`. The approval record names the agent and the note; the report and the
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

## Stage 3 — proofs

Prove the results, following Phase 1's rules. Four matter most here:

- **Route changes.** Record each in `DEVIATIONS.md` *when you make it*, with its `kind`.
- **Suspicions and skips.** Your suspicions about the paper, and results you propose not to
  formalize, go in `AUTHOR_NOTES.md`. The adjudicator verifies them. A result that needs theory
  no configured library has is not yours to skip, narrow or hypothesise away: stop and ask
  (Stage 2, "Missing theory").
- **No standing `sorry` for a skipped result.** Delete the statement (which needs re-approval if
  it was approved), or take the result as a named hypothesis.
- **Approved statements are frozen.** See "Re-approval".

**Proof helpers (how this was done for a 55-result paper).** One author-side helper per statement
file, working on a COPY of that file in the run's `work_dir` (never under `/tmp`: a reboot once
wiped a dozen files of proofs kept there). `work_dir` is a git repository of its own; each helper
commits its file as soon as it compiles, and at least every hour, with
`python3 audits/project.py --work-commit "<message>" <file>` (one commit at a time across helpers;
a plain `git -C <work_dir> commit` would ask for permission). The copy imports the BUILT modules, so it compiles
on its own (`lake env lean <copy>`) without touching the repository or running `lake build`, and
merging back is replacing the file. Give every helper the same written brief: statements and
definitions frozen (only `sorry` bodies change), auxiliary lemmas in a sub-namespace per file, no
`native_decide`/`admit`/`axiom`, route changes as `DEVIATIONS.md` rows (columns and kinds as in
Phase 1), a BLOCKED file for statements that look false (never weaken one), and a short
PROGRESS file kept current (the only way to see a long helper's progress). Before merging, check
that the diff removes only `sorry`s, then run the freeze check.

**Shared lemmas, sweeps and witnesses.**
- Create `<Name>/Common.lean` and `<Name>/Examples.lean` in Stage 1 (stubs are fine), inside the
  project namespace, add both to `lean_files` and import them from `<Name>.lean` (Phase 0 fails on
  an unlisted project file). `Common.lean` is imported by every statement file and holds facts
  more than one file needs (permutation-matrix membership, order embeddings, ...);
  `Examples.lean` imports the statement files. In a test run 35 duplicate helpers came
  from section helpers that could not see each other's work.
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

**Ask the human mid-stage only when blocked:**

- a frozen statement must change;
- a goal result looks unprovable after a serious attempt;
- the work needs something the intake ruled out.

Under a delegating level, work the intake ruled out is not done (the conservative choice), logged
[DELEGATED]. A frozen statement that must change: under `statements-only` ask the human
("Re-approval"; a remaining stop); under `hands-off` follow "Statement changes after approval". A goal result that looks false or unprovable as stated is a stop at every
level ("Stops that remain at every level").

First spawn the escalation check: the prompt from `python3 audits/prompt.py --prompt escalate`,
followed by only the question and the evidence. Ask the human only if it answers NEEDS-HUMAN.
Collect everything else under "Open questions" in `RUN_LOG.md`.

Commit at milestones. When nothing in scope is `sorry`, commit, then run `python3 audits/phase0.py`;
it must say GREEN, freeze check included.

## Stage 4 — audit rounds

Each round, in order:

1. **Phase 0.** Commit, then run `python3 audits/phase0.py`. It must be GREEN; it also saves the
   tree baseline.
2. **Scope and lanes.** Run `python3 audits/prompt.py 3` and do exactly what its block says: scope,
   commit `scope <R>`, spawn the lanes it prints.
   - If `scope.py` exits 3 (nothing changed), go to Stage 5.
3. **Seal and check the lanes.** As each lane returns, seal it from that child's own result, as
   step 3 of the `prompt.py 3` block says (`lane_auth.py seal --verdict … --sha256 … --agent-id …`,
   values from the child's `LANE_COMPLETION` line and its agentId or Codex thread id; one seal
   command at a time). When every lane has returned and is sealed, run
   `python3 audits/lanecheck.py --round <R> --kill`. A token, digest or seal mismatch is an
   integrity failure (a remaining stop at every level); the rest below are mechanical. It flags a verdict file citing another round
   or the audit record, a cited probe that does not exist, stray files in the Lean repository, and
   leftover polling loops (killed with `--kill`). Clear each before adjudicating: re-run a lane
   that read the record or cites a missing probe, delete stray files. Log each under "Mechanical
   failures". A lane that only *mentions* a record file (for example, saying it saw the name and
   did not open it) may stay; say so in the log.
4. **Adjudicate.** `python3 audits/prompt.py 4 --round <R> --write`, then spawn one new
   general-purpose subagent with the printed sentence. Wait for it. It commits `adjudicate <R>`.
5. **Re-votes.** If `ADOPTED.md` has **REVOTE NEEDED** rows (adjudicators never spawn lanes; the
   re-votes are yours):
   - For each row, spawn the lane printed by
     `python3 audits/prompt.py --lanes --round <R> --revote LANE:ITEM --write` with its whole printed
     line (token included), and seal it from its own result exactly as in step 3; then run
     `python3 audits/lanecheck.py --round <R>`.
   - Then spawn a fresh adjudicator with the `prompt.py 4 --round <R>` prompt followed by exactly
     this line: *"Resolve only the REVOTE NEEDED rows, using the files under revote/; append your
     decisions as a new table at the end of ADOPTED.md and commit 'adjudicate <R> revotes'."*
6. **Implement.** Run `python3 audits/prompt.py 5 --round <R>` and do exactly what it says.
7. **Exit check.** Read `ADOPTED.md`.
   - **Go to Stage 5** if it has no **ADOPT**, no **REVOTE NEEDED**, and no **UNCOVERED** row
     except those marked "(expected: …)".
   - **Stop and ask** if the round cap is reached. Under a delegating level, do not ask: implement
     the round's ADOPT rows, log "round cap reached; no further diff round" as [DELEGATED], and go
     to Stage 5 (its full-scope round runs whatever the budget; what it does not re-check is
     disclosed there).
   - **Otherwise** go to the next round.
   - **QUESTION** rows wait for Checkpoint C.
   - **In Stage 5** the round after the full round is the last one: follow Stage 5 step 1 instead
     of this exit check.

**Resuming a half-finished round.** If `TARGET.json` exists but some lanes are not sealed, run
`--verify-written` first, then for each unsealed lane:
- **its spawn line is still in this conversation** (a mechanical failure): spawn it again with
  that same line;
- **its spawn line is lost** (a new conversation after a usage limit or a crash: the line, with
  its token, lived only in the old conversation): re-issue it, logged,
  `python3 audits/lane_auth.py reissue --round <R> --lane <lane> --reason "<why>"` (`<lane>` is
  the verdict file's name without `.json`, e.g. `correspondence@2`). It refuses a lane that has a
  seal, moves any verdict the lane already wrote to `<R>/.reissued/` (evidence, never used),
  commits the new commitment as `scope <R> (reissue <lane>: <why>)` and prints a new spawn line;
  only the newest commitment counts. Spawn ONE fresh lane with that line, seal it, and log the
  reissue under "Mechanical failures".

A sealed lane is never re-run or re-issued. Never re-scope a round, and never run `--write` again
for a round whose tokens were issued.

Log each round in `RUN_LOG.md`: commit; lanes; P/F/A/N counts;
ADOPT/REJECT/DEFER/QUESTION/UNCOVERED; wall-clock time.

## Stage 5 — final round, report, Checkpoint C

1. **Full-scope round.** Run Stage 4 with `prompt.py 3 --full`, and use `scope.py --full` where
   its block says `scope.py`. This round runs every correctness lane and re-examines everything,
   including passes made stale by a changed definition. If it adopts anything, implement it and
   run one diff round on the result. That diff round is the last. Resolve its REVOTE NEEDED rows as
   in Stage 4 step 5. If it adopts anything:
   - if a fix would change an approved statement or a definition one uses, stop and follow
     "Re-approval" (below; under `hands-off` without stopping, within "Statement changes after
     approval");
   - otherwise implement the fixes and run Phase 0, but start no further round. The report lists
     those commits under "Changes after the last audit round" (not re-audited), and the decisions
     document asks the human to confirm them. Its UNCOVERED rows are listed there for the human
     too.
2. **Check and report.**
   - Run `python3 audits/integrity.py --check` (no round). It must report OK.
   - Commit, then run `python3 audits/phase0.py`. When GREEN it regenerates `REPORT.pdf`.
   - **Read every page of the PDF** and the markdown in full (AUDIT_PROTOCOL.md, "Read the rendered
     PDF" and "Documents a human reads"). A fault is fixed in the report's sources or in the
     generator, then regenerated -- never by editing the output. A fault you find that nothing open
     in this run can fix goes into the notice `KNOWN_FAULTS-<key>.md` yourself, in the notice's form
     ("Fresh-reader check", step 3), committed as `reader <key> notice`.
   - Run the **fresh-reader check** (below) on `REPORT.pdf`.
3. **Decisions document.**
   - `python3 audits/decisions.py --write` (it uses the newest round). It writes `DECISIONS.md` in
     the rounds directory as a skeleton, with one anchored item for everything the human must see:
     - the approval: who made it, exclusions, notes, earlier approvals;
     - every global difference and CHECK row of the approved sign-off sheet;
     - every result not formalized, every paper defect, and every open vacuous statement
       (`VACUOUS.md`);
     - every QUESTION row of every round;
     - every [PROXY] decision and every open question in `RUN_LOG.md`;
     - every configured standing defer, and every one adjudicators invoked but nobody configured;
     - the last round's UNCOVERED rows;
     - every change after the last audit round;
     - the detailed entry for every box line: each paper defect, skip, route change and open
       vacuous statement.

     It also pre-lists the "Read this first" box: paper defects, results not formalized, route
     changes of any kind other than "same strength" and "reading choice", and open vacuous
     statements. An answered item comes back if a later round asks it again, or if its content
     changed; the earlier answer is shown with it. "Changed" means, per record: a new approval;
     new sheet text for a global difference or a not-formalized note; for a paper defect its
     location, severity, printed text, why it is wrong and its consequence; for a vacuous
     statement its parameters, reason, decision and status; for a skip its subject and reason;
     for a route change its result, the paper's route, the reason and the kind; for a standing
     defer any field; new commits after the last round. Line and commit citations are ignored.
     `--write --out PATH` / `--check --file PATH` write or check a draft elsewhere. An answer line
     naming no current item is listed under "Previously answered" as stray: fix its anchor. If a
     `DECISIONS.md` from an earlier checkpoint exists, first move it to `DECISIONS.<date>.md`. Items
     the human already answered are listed as "Previously answered" if `RUN_LOG.md` records them under
     `## Answered`.
   - **Under a delegating level** (`statements-only`, `hands-off`) the skeleton is headed
     "Decisions taken on your behalf", quotes the intake answer, says who reviewed nothing, and
     gives every decision section a sixth field, **Decision taken**. Take each decision now, as
     in "How you decide": the field states what was done, quotes its
     `[DELEGATED <date>, operator under <level> (intake); reversal: <cost>]` tag, and says how the
     reader reverses it and what a reversal triggers. Its Recommendation field names the
     adjudicator's recommendation it follows, or the conservative rule's option; never your own.
     "Not applicable: <why>" only for an item the human decided at Checkpoint B (under
     `statements-only`, approved by the human: the approval, global differences, CHECK rows).
     `[DELEGATED]` items already in `RUN_LOG.md` (decided at Checkpoint B or between) are listed as
     decided; keep them, and their tag, in their sections. The skeleton opens with a summary table,
     "At a glance": one row per decision section, saying what was done, what it followed
     (adjudicator's recommendation, conservative rule, or human at Checkpoint B) and the reversal
     cost (none, re-prove, re-approve, new round).
   - Fill it in. Follow AUDIT_PROTOCOL.md, "Documents a human reads"; the model is a document that
     opens with background (what was done, how the protocol works, where every file is, terms, the
     paper's notation), then gives decisions ordered by importance, each with paper / Lean /
     evidence / options and what each changes / recommendation, and ends with how to answer and
     what each answer triggers. Group items that are one decision; keep every anchor.
   - `python3 audits/decisions.py --check` must pass. It refuses a document with any of these:
     - an unfilled placeholder, or TODO/TBD/FIXME outside code;
     - a dropped or stale anchor;
     - a box that is missing, placed after the background or the decisions, or has lost an entry
       (every pre-listed entry must stay inside the box);
     - a `VACUOUS.md` status that is neither "open" nor "repaired in <commit>";
     - a decision section without its five fields filled with real content (Paper, Lean, Evidence,
       Options, Recommendation; "Not applicable: <why>" only for the first three);
     - a section that never names what its anchors cover (the result, the convention, or the
       question's item), or a [PROXY] section that does not show "[PROXY" (a [DELEGATED] one:
       "[DELEGATED");
     - under a delegating level: no "Decisions taken on your behalf" heading, no verbatim intake
       answer, no sentence saying who reviewed nothing, or a section whose **Decision taken**
       field is missing, empty, or (unless "Not applicable: <why>") does not show "[DELEGATED".
   - Run the **fresh-reader check** on `DECISIONS.md`.
4. **Deliver.**
   - Run the gate for each document, and deliver only if every one passes:
     ```
     python3 audits/readers.py --doc report    --check
     python3 audits/readers.py --doc decisions --check
     python3 audits/readers.py --doc signoff   --round approved --check   # the approval record names the round
     python3 audits/readers.py --doc other:<absolute path> --check   # each other document you deliver
     ```
   - Copy `REPORT.pdf`, the approved `SIGNOFF.pdf` and `DECISIONS.md`, with any `KNOWN_FAULTS-*.md`
     notice, with `python3 audits/project.py --deliver` (into `deliverables/`). If the intake named
     another destination, copy them there as well (`cp`, which asks for permission), or tell the
     human where they are.
   - Commit the audits repo.
   - Push only if the intake said yes.
5. **Checkpoint C.** Send the human a short message: where `DECISIONS.md`, `REPORT.pdf` and
   `SIGNOFF.pdf` are; the number of decisions; whether the statements were approved by a human or by
   the agent; every `KNOWN_FAULTS-*.md` notice of the delivered documents, verbatim; every
   `fixed:`/`dismissed:`/`unfixable:` reader response; every NOTE the gate printed; and the
   fresh-reader pass counts. The decisions themselves
   are in `DECISIONS.md`, not in the message. Record the human's answers verbatim in `RUN_LOG.md`
   under `## Checkpoint C (<date>)`, add one line per answered item under `## Answered`
   (`- answered <anchor> (<date>, <round DECISIONS.md was written for>): <answer>`), and carry them
   out as `DECISIONS.md` says each answer
   triggers.

   **Under a delegating level, do not wait for answers.** The decisions were taken in step 3.
   Before delivering (so step 4 comes after this):
   - Record them in `RUN_LOG.md`: under `## Checkpoint C (<date>, delegated)` one line per
     decision, `- <anchor>: [DELEGATED <date>, operator under <level> (intake); reversal: <cost>]
     <decision> — <reason>`, and the same decision under `## Answered` as
     `- answered <anchor> (<date>, <round DECISIONS.md was written for>): [DELEGATED …] <decision> — <reason>`,
     word for word (the report counts the two as one). A decision already tagged earlier in the
     log (at Checkpoint B or between) is not re-recorded here: its section already shows it (if it
     is, the count still takes the two as one).
   - Carry each out as `DECISIONS.md` says it triggers. A change to the Lean is committed, then
     Phase 0; a statement change goes through "Re-approval", approved by you. If
     `decisions.py --check` then names a new item (for example the new commits), move the document
     to `DECISIONS.<date>.md`, write it again (the answered items are listed as previously
     answered), and take the new item the same way.
   - Commit, then run `phase0.py`: it regenerates the report, whose page-1 box now counts the
     decisions taken on the reader's behalf and says where they are. Read every page.
   - Run the fresh-reader check and the gate on every delivered document as usual, then deliver
     (step 4).
   - Finish with a short completion message to the human: what was produced and where
     (`REPORT.pdf`, `SIGNOFF.pdf`, `DECISIONS.md`, with paths); that the involvement level
     delegated the decisions, how many were taken on their behalf, and where to review and reverse
     them (`DECISIONS.md`, and the report's section 1); whether a human approved the statements;
     and, as above, every notice, reader response, gate NOTE and pass count. End it with these
     reversal instructions, filled in: "To reverse a decision, open Claude Code in
     `<project path>` and say: *Read audits/RUN.md; reverse `<anchor>` in DECISIONS.md.* The table
     at the top of `<path to DECISIONS.md>` gives each decision's anchor and what reversing it
     costs (none, re-prove, re-approve or new round); its section says what will be rerun." The
     run is then complete. A later reversal the human asks for is new work: record their words
     verbatim and carry it out as `DECISIONS.md` says.

   Only now may you save a memory note about the run.

### Fresh-reader check

Run this before any of these documents reaches the human:
- the sign-off sheet (Stage 2 step 6), and the list of QUESTION rows for Checkpoint B (step 8);
- `REPORT.pdf` and `DECISIONS.md` (Stage 5);
- any other summary you write for them, with `--doc other:<absolute path>`.

The Checkpoint C message only points to checked documents. It needs no pass, but it must be true
(AUDIT_PROTOCOL.md, "Documents a human reads", rule 4).

**What the gate enforces.** `readers.py` checks two things:
- the newest well-formed pass read exactly the version you deliver;
- **every** `- BLOCKING:` finding that any reader ever raised about this document is answered.

So re-running a reader gains nothing: the findings it would wash away must still be answered.

1. **Mechanical check first.** Fix what it finds before any reader sees the document:
   - sheet: `signoff.py check --round <R>`, then render it;
   - report: commit, then `phase0.py` (it regenerates the report), then read every page;
   - decisions document: `decisions.py --check`.
2. **Spawn a reader.**
   ```
   python3 audits/prompt.py --prompt fresh-reader --doc signoff|questions|report|decisions|other:<path> --round <R> --write
   ```
   `<R>` is the sheet's round for `signoff` and `questions`, and the newest round otherwise. An
   `other:` document must lie inside the rounds directory. Spawn **one new**
   general-purpose agent with the printed sentence and nothing else. The script fills everything;
   you add no words.

   The reader saves its record itself by piping it into `readers.py --save` (the prompt gives
   the command), which checks it, writes `<rounds dir>/readers/<key>-<n>.md` and commits it
   alone as `reader <key> <n>`, so no record can vanish before it is on record. If the reader
   could not run commands and returned the report as text, pipe that text into the same command
   yourself, unedited: never retype or summarize it. The key names the document and its cycle: `signoff-<R>`, `questions-<R>`, `report-<newest round>`,
   `decisions-<newest round>`, or `other-<name>-<id>` (an `other:` document's history is tied to its
   path: never copy it to a new name to check it again). If the reader returned without committing,
   commit the file exactly as it is. Never edit, rename or delete a record: the gate reads every
   record as it was first committed, so an edit changes nothing except that the checkpoint message
   must report it (`readers.py --check` prints it as a NOTE). Never rewrite the history of the
   audits repository (`reset`, `--amend`, `rebase`): that is the one way to remove a record, and it
   is forbidden. If `--write` refuses because the prompt for that pass number exists, spawn that
   prompt; if it was never spawned, or HEAD moved since it was written, delete it and write it
   again.
3. **Answer every blocking finding.** For pass n, write `readers/<key>-<n>.response.md` with one line
   per `- BLOCKING:` finding. Each line copies the **start** of the finding (at least 15
   characters, or all of a shorter finding; enough that it matches no other finding of that pass,
   or the whole finding when it is the start of another), then a spaced em dash ` — ` and the
   answer. The quote may itself contain ` — `. There are three answers:
   - `- fixed: <quote> — <what you changed>`. Fix the sheet and the report through their sources or
     the generator, never by editing the output (AUDIT_PROTOCOL.md, "Fixing a generated
     document"). Then rerun step 1 and spawn a new reader. The gate accepts `fixed` only once a
     later pass has read a changed version of the document.
   - `- dismissed: <quote> — <evidence that the finding is wrong>`, with file:line and what it
     says. The next reader is not told. If it raises the point again, answer it again; the human
     sees every dismissal (Stage 2 step 8, Stage 5 step 5).
   - `- unfixable: <quote> — <why nothing open in this run fixes it, and what will>`, for a correct
     finding with no fix available now. Examples: a known generator gap (AUDIT_PROTOCOL.md, "Today's
     generators do not yet meet every rule"), or a record whose owner step is closed. Quote the
     finding also in the notice `<rounds dir>/KNOWN_FAULTS-<key>.md`.

   Commit the response file, and the notice if any, as `reader <key> <n> (response)`. Response
   files are records too: to correct a committed one, add `readers/<key>-<n>.response-2.md` (then
   `-3`, …); the gate reads them all, and the last answer to a finding counts. The gate names any
   response line it could not parse.
4. **A malformed report is a mechanical failure.** That means:
   - a missing or malformed first line, coverage line or verdict line;
   - a verdict whose count differs from its `- BLOCKING:` lines;
   - COULD NOT CHECK entries caused by a wrong path in the prompt.

   Commit it anyway and answer its `- BLOCKING:` lines like any others. Then spawn a new reader on the
   same document, and log the failure under "Mechanical failures".
5. **When to stop fixing.** After 3 passes that still report blocking problems, stop fixing: mark
   what remains `unfixable` with the reason "fix budget reached" (this counts as nothing open in
   this run), and deliver with the notice. The
   notice is never written into the document itself, since that would change what the reader
   read. It is delivered next to the document and quoted verbatim at the top of the checkpoint
   message.
   The checkpoint message says the fix budget was reached. Expect this for a long hand-written
   document; it is not a failure of the run.
6. **The gate.** Run it for each document before Checkpoint B (the sheet and the QUESTION list) and
   before delivering at Stage 5:
   ```
   python3 audits/readers.py --doc signoff|questions --round <R> --check   # Stage 5: --doc signoff --round approved
   python3 audits/readers.py --doc report|decisions|other:<path> --check
   ```
   It refuses in any of these cases:
   - there is no well-formed pass, or the newest record is malformed;
   - the newest well-formed pass read another version of the document;
   - a blocking finding in any pass has no answer. That includes malformed passes, where any line
     saying BLOCKING counts, however it is marked;
   - a quote matches several findings of its pass (it then answers none);
   - a finding is answered `fixed`, but the delivered version is the one it was raised on (or that
     pass recorded no version);
   - an `unfixable` finding is not quoted in the notice;
   - `DECISIONS.md` is not tagged for the newest round;
   - a record or notice of this document is uncommitted;
   - git fails (the check fails closed).

   Records edited or deleted after their commit do not refuse the gate (it reads them as first
   committed); it prints them as NOTE lines, and the checkpoint message repeats them.
7. **Log** each pass in `RUN_LOG.md` under `## Fresh readers`: document key · sha256 · commit ·
   pass n · verdict line · reader file.

### Re-approval

The freeze check reports DRIFT, or a statement must change. Stop, then:

1. Make the change and commit it.
2. Move the approval aside: `git -C audits mv <…>/APPROVED_FINGERPRINTS.json
   <…>/APPROVED_FINGERPRINTS.<date>.json`, then commit `approve <R> (moved aside for re-approval)`.
3. Run Stage 2 steps 2–7 on the new commit. The rendered sheet marks every result **CHANGED since
   the approval of <date>**.
4. Ask the approver the Checkpoint B question again for the new sheet, pointing them at those
   results in particular: does the change strengthen or weaken the statement? A change that is
   partly both, or unclear, counts as a weakening. If they choose (c), that judgment is yours and
   is logged as a [PROXY] decision; the report lists every earlier approval and who made it.
   Under `statements-only` this question is a remaining stop: ask the approver, who types the
   answer (never a [PROXY]); if they are away, stop and wait. Under `hands-off`, do not ask:
   approve the new sheet as in Stage 2 step 8 (`--by agent`, with a `--note` saying the
   re-approval was delegated at intake). The change must be one "Statement changes after approval"
   allows (never a strengthening or generalization; a weakening only to turn missing theory into a
   named hypothesis), logged as [DELEGATED] with `reversal: re-approve` in a commit made before the
   Lean edit.

---

## RUN_LOG.md format

```markdown
# Run log — <PROJECT>
## Intake (date)            one line per sub-question (1a–1c, 2a–2c, 3, 4, 5a–5d, 6a–6d, 7),
                            verbatim or close to it; "default" where the human took it
## Checkpoint A (date)      approved configuration; pin commit
## Stage 2                  statement commit, round, counts; Checkpoint B answer verbatim (date, commit)
## Rounds                   one line per round: commit · lanes · P/F/A/N · ADOPT/REJECT/DEFER/Q/U · time
## Mechanical failures      re-runs and why
## Open questions           for the human; mark each "(answered <date>: <answer>)"; never delete
                            (a [PROXY] decision: "[PROXY <date>, operator for <who>; reversible] …";
                            a delegated one: "[DELEGATED <date>, operator under <level> (intake); reversal: <cost>] … — <reason>")
## Checkpoint C (date)      the human's answers to DECISIONS.md, verbatim
                            (delegated: "## Checkpoint C (<date>, delegated)", one [DELEGATED] line per decision)
## Answered                 one line per answered item: - answered <anchor> (<date>, <round>): <answer>
## Fresh readers            one line per pass: document · sha256 · commit · pass n · verdict line · reader file
## Current stage            one line, updated whenever the stage changes (this is what resume reads)
```

## Running this without Claude Code

The protocol, scripts and files do not depend on which agent runs them. Two parts are specific to
Claude Code: the `auditor` subagent type (`audits/agents/auditor.md`) and the `/formalize-paper`
skill (`audits/skills/`). To run under another agent CLI that has subagents:

1. Define an equivalent read-only auditor agent.
2. Point the skill's instruction at this file.
3. Keep every rule above.

This is untested. Running one lane on a second model family is the cheapest way to vary the
method (AUDIT_PROTOCOL.md, "What this protocol does not cover").

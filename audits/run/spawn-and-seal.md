# Spawning subagents, sealing lanes, re-running a failed child

Read this before the first spawn of the run (Stage 2 step 3) and whenever a child fails. It is the
one home of these rules; the stage files point here.

## Spawning

- Every prompt is written to a file by `prompt.py … --write`, which prints the line to spawn it
  with. Spawn each subagent with exactly that line and nothing else: no framing, hint, summary or
  opinion of yours. The escalation check (Stage 3) too: `prompt.py --prompt escalate --question
  "<the question>" --decl <name> [--passage "tex l.N-M"] --write` puts the question, the
  declaration and the quoted paper passage into its prompt file and commits it with its hash; then
  `lanecheck.py --escalation E<n> --agent-id <agentId> --returned-file <file>`, the file holding its
  final message verbatim, saved with a quoted heredoc (`cat > <file> <<'RETURNED'`, the message,
  `RETURNED`: the shell expands backticks and `$` inside `"..."`), checks the file against that hash and the answer against the child's returned line, and commits the answer.
- **A child whose file write was refused** (Claude Code may refuse a subagent's report file:
  "Subagents should return findings as text, not write report files"). The status check and the
  reviewers of a tool patch, a core-fault request and an acknowledgment then return the file instead:
  its text between a line `BEGIN RETURNED FILE <path> <delimiter>` and a line `END RETURNED FILE`,
  followed by their completion line. The delimiter is `RETURNED_` and the first 12 hex digits of the
  child's token, so no line of the text ends the heredoc early. Save exactly that text, unedited, to
  the path it names with a quoted heredoc ending at that delimiter (`cat > <path> <<'<delimiter>'`,
  the text, `<delimiter>`), then seal as usual: the seal accepts the file
  only if its sha256 is the digest the child returned and it carries the child's token, so a file
  not saved byte for byte is refused (re-run the child). Never retype, reformat or summarize it.
  That refusal is Claude Code's own rule for subagents, not a permission the user or anyone set:
  saving the returned text as described is a normal protocol step and needs no one's approval.
  Never ask the human about it.
- **Lanes** (subagent type `auditor`): everything after "with:" in the printed line, the lane
  token included, is the lane's whole prompt. That machine-generated envelope is never saved to a
  prompt file, re-typed or hand-composed. Spawn every lane of a wave in ONE message, in parallel;
  never serialize the lanes themselves.
- **A wave is at most 8 lanes**, fewer when the machine has less than 32 GB of RAM or the human
  asked for smaller waves (more lanes probing Lean at once ran out of memory). When the human says
  at intake (question 7) that the machine has 16 GB of RAM or less, at most 3 subagents of any
  kind run at once (RUN.md, "Cost"): a wave is then at most 3 lanes. Spawn the next wave
  when the lanes of the previous one have returned and been sealed.
- **Every other subagent** (adjudicator, informalizer, sign-off writer, fresh reader, escalation
  check) is `general-purpose`. Never `subagent_type: "fork"`: a fork inherits your whole context.
- Wait for children with the harness's blocking wait, not by polling. A polling loop
  you start yourself must carry `FORMALIZE_PAPER_OPERATOR=1` (RUN.md, rule 9).

## Sealing each lane as it returns

**Lane completion, both Claude and Codex.** As EACH lane finishes, inspect that child's actual
completion result (not messages from siblings), require its expected verdict file and its
`LANE_COMPLETION {"verdict": …, "sha256": …}` line, and run:

```
python3 audits/lane_auth.py seal --verdict <verdict> --sha256 <sha256> --agent-id <agentId>
```

with `verdict` and `sha256` from that child's `LANE_COMPLETION` line and `agentId` from that
child's result (Codex: the child's thread id). The lane computed the digest from its intended JSON
bytes before writing, so a token-preserving replacement before completion cannot be sealed: never
substitute a digest computed from the file on disk or taken from a sibling's message. The script
validates the token and the bytes and commits that lane's seal, verdict and probes as
`seal <R> <lane>`. Do not wait for the whole wave before sealing; the script takes a lock, so seal
commands never collide. A parent's exit 0 is not a child's success.

Token commitments, seals and lanecheck apply at every involvement level, under Claude Code and
Codex alike: they are mechanical steps, not decisions, and nobody is asked about them. A
transcript containing spawn tokens is not a prompt file; lanes are forbidden to read parent or
sibling transcripts. Tokens are provenance challenges, not lasting secrets: the verdict publishes
its own.

When every lane of the wave has returned and is sealed, run `python3 audits/lanecheck.py --round
<R> --kill`. The adjudicator runs it again. What its lines mean and what you
do about each is RUN.md's failure table: PROBLEM lines of a STOP class (a token, digest or seal
mismatch; a verdict or probe changed after its seal) are stops at every level; an unsealed lane is
sealed (or reissued, below); stray files are restored; leftover loops are killed (`--kill`); NOTE
lines are never yours to act on (the adjudicator settles each by a clearance or a re-vote). Never
write, copy, move or delete a lane's verdict or probe files to make a check pass. Log each PROBLEM
you cleared under "Mechanical failures".

`prompt.py --lanes --write` issues the round's tokens once and refuses a second run, and `seal`
refuses a second seal: a refusal there means the step already happened, never a reason to re-scope
or to write the prompts again under another round name. A SEALED lane is never re-run or
re-issued: any doubt about it is a re-vote the adjudicator orders. A new audited version needs a
new round.

## A child that failed mechanically

A crash, a service or capacity error ("Selected model is at capacity", overloaded, 5xx), a usage
limit, no verdict file, or no `LANE_COMPLETION` line is a mechanical failure, never a verdict.
Re-run only that child, with its original printed line (for a lane: the same envelope from this
conversation), after making sure the old child has stopped; record the retry and the new child id
under "Mechanical failures". Keep every completed judgment: seal the children that finished and
retry only what failed. A resume message from the person never answers a question, approves
anything or lifts a STOP.

**Retry budget (time, not count).** Retry with backoff: wait about 1, 2, 4, 8, … minutes between
attempts (at most 30 minutes between two), for up to 2 hours of trying per failure; a usage limit
or a capacity error is waited out until it lifts (its reset time, or the backoff), and never
becomes a human stop by itself. **A child's capacity error or usage limit opens no stop.** Each wait and retry of a child is logged under
"Mechanical failures" only, in both modes (no `stops.py open`, so nothing reaches the failure
tally); only a failure unchanged after the 2 hours is a stop (RUN.md, "Stops that remain at every
level"). Wait with the harness's blocking wait or a tagged monitor, never
with short polls. Only when the budget is spent with the failure unchanged, or the fix needs
something only the person has (RUN.md, "Stops that remain at every level"), is it an environment
fault for the human.

## Resuming a half-finished round

If `TARGET.json` exists but some lanes are not sealed (for example after a crash or a usage
limit), run `python3 audits/prompt.py --lanes --round <R> --verify-written` first, then for each
unsealed lane:

- **its spawn line is still in this conversation**: spawn it again with that same line;
- **its spawn line is lost** (a new conversation: the line, with its token, lived only in the old
  one): re-issue it, `python3 audits/lane_auth.py reissue --round <R> --lane <lane> --reason
  "<why>"` (`<lane>` is the verdict file's name without `.json`, e.g. `correspondence@2`). It
  refuses a lane that has a seal or that returned a verdict under its current token (that is a
  real stop, not a lost line), moves any verdict the lane already wrote to `<R>/.reissued/`
  (evidence, never used), commits the new commitment as `scope <R> (reissue <lane>: <why>)` and
  prints a new spawn line; only the newest commitment counts. Spawn ONE fresh lane with that line,
  seal it, and log the reissue under "Mechanical failures". If its commit fails (for example a
  stale `index.lock`), the reissue is undone (the old commitment and verdict are restored): clear
  the lock with `stops.py repair-lock` (`stops-and-set-asides.md`) and run the same reissue again.
  If the conversation ended in the middle of an issue or a reissue (a restart: its files written,
  not committed), run the same reissue again: it puts back what the interrupted command left
  uncommitted and finishes it (an issue that was never committed is issued afresh; no reissue is
  spent). Never delete or edit those files yourself.

A round you give up before its adjudication is never deleted or left uncommitted: set it aside
(`stops-and-set-asides.md`) and start a fresh round.

## Under Codex

- **Spawning.** Use the built-in spawn tool with `agent_type` set to `formalize_auditor` (lanes),
  `formalize_adjudicator`, `formalize_informalizer`, `formalize_reader`, `formalize_writer` or
  `formalize_escalation` (the escalation check), `formalize_renderer` (the PDF renderer, verifier and checkers,
  `render-pdf.md`), `formalize_tool_patch_reviewer` (a tool patch's fresh reviewer, a core-fault request's,
  `stops.py core-fault`, and a history-fault acknowledgment's, `integrity.py --ack-request`; release mode: RUN.md "Tool patches"; its verdict is sealed like a lane's), `formalize_status_check` (the advisory status check at
  delivery, `stage5-delivery.md`), `formalize_citations` (citation agents 1 and 2, Stage 5 step 5a) or `formalize_helper`
  (author-side helpers) as appropriate; every printed spawn line names its role (`codex.md`, "Roles"). Always request fresh context: `fork_turns="none"` on the current backend, or
  `fork_context=false` on the v1 surface. Never omit that flag, reuse a reviewer, or fork the
  author conversation. Validate the roles with `python3 audits/codex_agents.py --check
  .codex/agents` before spawning; integrity pins them. If the built-in tool or role is
  unavailable, STOP rather than doing its review yourself: an environment fault only the person can
  fix (`stops.py open --note "<what is missing>" --cause env-unknown`, a human stop in every mode;
  U2 §8). So is your own usage limit as the operator, once it outlasts the time budget above (a
  child's usage limit is waited out first, as above). `python3 audits/codex_spawn.py --kind
  auditor "<message>" … [--jobs N]` (or `--kind general`) is an explicitly selected fallback,
  never an automatic retry after a child failure.
- **Child results.** Never treat a child's exit code or final summary as proof that its record
  exists: require the expected files and run the prescribed checks. The parent's exit code can be
  0 after a child failed.
- **Waiting for children.** Wait with the blocking `wait_agent` tool and a long `timeout_ms`
  (minutes: 600000, or the largest value it accepts), which returns as soon as a child finishes.
  Never poll with short waits (the reference run made 74 `wait_agent` calls at 10 s): every poll
  is a new model turn that re-sends the whole context. Check status without waiting
  (`list_agents`) at most once every 10 minutes. Seal each lane as its wait returns.
- **Service errors.** A turn of yours or a child's that ends on a service error is a mechanical
  failure (above). The person resumes you (`codex/watchdog.py` in the clone, which they may run next to the
  session, only notifies them; it never types into the session).

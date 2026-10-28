# Running under the Codex CLI (experimental)

Read this once, at the start of a run under Codex (RUN.md sends you here). Everything in RUN.md and
the stage files holds under Codex too, except what follows. How to spawn and wait for children
under Codex is in `spawn-and-seal.md` ("Under Codex"), since spawns happen in Stages 2, 4 and 5.

- **Python environment (required).** Install before starting Codex. Every spawned command must
  receive `PYTHONDONTWRITEBYTECODE=1` through `[shell_environment_policy.set]` in Codex config.
  `codex/install-codex.sh` adds it to the user and project configs, preserving other settings;
  any environment include allowlist must retain this variable. Check with
  `python3 audits/project.py --env-check` in the session (Stage 1 step 0). Never edit config or
  tools, or delete unexpected bytecode, to get past an integrity failure during a pinned run.
- **Roles.** Every subagent the Claude Code path spawns has a generated Codex role
  (`audits/codex_agents.py`; `install.sh --codex` installs them in `.codex/agents/`, integrity pins
  their bytes). Spawn each with the built-in spawn tool, `agent_type` the role, fresh context
  (`fork_turns` "none"), and exactly the line the prompt script printed; every printed spawn line
  names its role after "Codex:".

  | Claude Code spawns | Codex `agent_type` | spawned with |
  |---|---|---|
  | lane (`auditor`) | `formalize_auditor` | `prompt.py --lanes ... --write`, re-vote lanes (Stages 2, 4), a reissued lane (`lane_auth.py reissue`) |
  | adjudicator, re-vote, reader-fix and record-fix adjudicator (general-purpose) | `formalize_adjudicator` | `prompt.py 4 ... --write` |
  | blind informalizer | `formalize_informalizer` | `prompt.py --prompt informalizer --write` (Stage 2) |
  | sign-off writer | `formalize_writer` | `prompt.py --prompt signoff-writer --write` (Stage 2) |
  | fresh reader | `formalize_reader` | `prompt.py --prompt fresh-reader ... --write` (`fresh-reader.md`) |
  | escalation check | `formalize_escalation` | `prompt.py --prompt escalate ... --write` (Stage 3); its thread id is the `--agent-id` of `lanecheck.py --escalation` |
  | PDF renderer A, verifier B, cover, cover verifier, both checkers | `formalize_renderer` | `prompt.py --prompt render-a\|render-b\|render-cover\|render-cover-check\|render-check ... --write` (`render-pdf.md`); each saves with `render_record.py save`, a child that ends without saving is `render_record.py fail`, never a stop |
  | citation agents 1 and 2 | `formalize_citations` | `prompt.py --prompt citations-draft\|citations-review --write` (Stage 5 step 5a), two different children |
  | author-side helpers (statements, proofs) | `formalize_helper` | the brief `prompt.py --prompt formalizer` prints, then the assignment (Stages 2, 3) |
  | delivery reviewers (CLAIMS, READABILITY, DECISIONS, TRUST; advisory) | `formalize_reader` | the "Delivery reviewer prompt" of `stage5-delivery.md`, filled in (step 5, "Review"); four different children; each returns its findings as its final message |
  | tool-patch reviewer, core-fault reviewer, acknowledgment reviewer (release mode) | `formalize_tool_patch_reviewer` | `tool_patch.py review --tp TP<k>`, `stops.py core-fault --stop S<n> ...`, `integrity.py --ack-request ...` (RUN.md "Tool patches"); sealed with `lane_auth.py seal` |

  The roles carry no network, sandbox or tool setting of their own: each child inherits the
  parent's sandbox, and its network rule is the one in its generated task (intake 1c). Every role also
  tells its child that a command the sandbox blocks is a failure it records, never an approval to
  ask for (`codex_agents.SANDBOX_RULE`). If a child asks anyway (`Thread: Agent ...` on the approval
  prompt), it is declined: under a delegating level never approve it. Declining aborts that child's
  turn (Codex 0.163/0.164): it never completes, and `wait_agent` keeps reporting "No agents completed
  yet". So a child that has not returned after a long wait is checked once with `list_agents`; one
  whose turn was aborted or that the person reports declined is a failed child (a mechanical failure,
  never a stop): handle it as its stage says for a child that ends without its file.
- **The delivery reviewers** (advisory, at delivery; `stage5-delivery.md` step 5) run as `formalize_reader`
  (`fork_turns` "none"), one child per perspective, each given the "Delivery reviewer prompt" filled in. Save
  each child's final message verbatim as `delivery-review/<PERSPECTIVE>.md`; no seal. A child that fails is
  replaced once by a fresh one, then noted in `JUDGEMENT.md`; never a stop. (The status check role
  `formalize_status_check` is no longer used at delivery: approver, 2026-10-28.)
- **A tool patch's reviewer** (release mode; RUN.md "Tool patches") runs as the generated role
  `formalize_tool_patch_reviewer` (`fork_turns` "none"), spawned with the line `tool_patch.py review
  --tp TP<k>` prints (the same role reviews a history-fault acknowledgment, `integrity.py --ack-request`); seal its verdict with `lane_auth.py seal` and the child's thread id as
  `--agent-id`. A run whose first pin has no such role (installed before it existed) cannot patch its
  tools: `tool_patch.py` refuses, and the fault follows its printed cure. `codex_spawn.py --kind
  general` with the same line is the process-per-subagent alternative.
- **Questions to the human.** The intake is always one plain-text message (Stage 0). After it,
  Claude Code uses the question tool where there are options; Codex uses plain text, numbering the
  options. This applies only to what the involvement level still puts to the human. A question a
  stage file gives verbatim (the Checkpoint B question) is sent as that text, in the terminal,
  under both.
- **Command approval prompts are not checkpoints.** Codex may ask the person to approve a command
  the sandbox blocks (by default any write to the project's `.git`: branch, staging, commit; F9).
  Such an approval is the harness's, not the protocol's: it is never a decision, never the human's
  answer to a question, and never a substitute for a checkpoint. A delegating level must not wait at them, so such a run is started with the project's `.git` writable
  (`--add-dir <project>/.git`, `codex/README.md`, "Git commits without approval prompts"). That is
  the ONLY sanctioned sandbox change. Never use `--dangerously-bypass-approvals-and-sandbox`,
  `danger-full-access`, an approval policy of `never` or wider writable roots; never request an
  approval to get past a STOP, to run a reviewer, or to retry a failed child outside the sandbox;
  never ask the person to approve a command just so a delegated run can continue. If an approval
  is requested anyway under a delegating level, it is an environment fault: log it under
  "Mechanical failures", record the stop (`stops.py open --note "<the command>" --cause
  codex-approval`, a human stop in every mode: release stop 3, something only the person can fix) and wait for the person; it is not a decision you may
  answer or record as delegated.
- **No network in the sandbox.** Codex's workspace-write sandbox has the network off, so
  `lake exe cache get` (Stage 1) cannot run inside the session. Fetch the cache and build once
  BEFORE starting Codex (INSTALL.md); if the cache is missing inside the run, that is an
  environment fault for the person (stop 3), never a reason to turn the network on.
  The children inherit this: under Codex no agent fetches anything, which is stricter than intake
  1c asks of a public paper and exactly what it asks of a confidential one. What degrades:
  - the prior-art lane and Loogle lookups work from the local Mathlib and files only (a lookup that
    needs the network fails inside the sandbox; the lane goes on without it);
  - the citation agents (step 5a) cannot read the cited works. If the person started the session
    with `--search` (Codex's own web-search tool for the model; it is not a sandbox change and
    opens no shell network), they search with it under the rule their prompt carries (that children
    get the tool is untested). Without it,
    agent 1 records the items it could not reach as "not reachable", or, when it reaches nothing,
    you log `citation notes not produced: no network` (`stage5-delivery.md`, step 5a) and go on.
    Either way it is never a question, a stop or a round. Start with `--search` only for a public
    paper; for a confidential one (intake 1c) leave it off (if it is on anyway, the prompts' rule
    binds every agent, exactly as under Claude Code, whose agents always have web access).
- **Steps that would leave the sandbox are left to the person, never approved.** Three operator
  steps need the network or a write outside the project: Stage 1's `git fetch upstream` in a
  Mathlib clone (the person fetches before starting, with the cache), Stage 5's push when the
  intake allowed one (6c, 6d), and Stage 5's copy of the deliverables to a destination outside the
  project (6b). Do not run them (each would ask for an approval, which a delegating level must not
  wait at): the deliverables stay in `deliverables/`, and the completion message (or Checkpoint C)
  gives the person the exact `cp` and `git push` commands to run themselves. That is not a stop and
  not a question.
- **Seeing a PDF.** The PDF agents look at pages as `pdftoppm` images (Codex's image viewer,
  `view_image`) or as `pdftotext -layout` text; both are in their prompts. LaTeX runs in the
  sandbox: it writes only inside the project and the temporary directory, so an engine that needs a
  writable cache elsewhere (LuaLaTeX's font cache) can fail; the renderer then uses another engine.
  Any rendering failure is `render_record.py fail`, never a stop (`render-pdf.md`).
- **Thread limit.** Codex caps how many child threads are open at once, and a finished child still
  counts until it is closed. Close each child once its result is taken (sealed, saved or recorded).
  A spawn refused for the limit created no child: close finished children, then spawn the same
  printed line again; it is a mechanical failure (log it), not a retry of that child.
- **Waiting and long commands.** Children: one blocking `wait_agent` (`spawn-and-seal.md`). A
  backoff wait before a retry, or a long Lean command (`signoff.py approve`, `phase0.py`, a build):
  one shell call with a timeout longer than the command (Codex's per-call timeout), never a loop of
  short calls; Codex has no Monitor tool (do not rely on background tasks), and any polling loop you start
  carries `FORMALIZE_PAPER_OPERATOR=1` (RUN.md, rule 9).
- **Sandbox failures and logs.** Do not retry a sandbox failure outside the sandbox. Record the
  actual `--log-dir` path (or the default printed final-message path) in `RUN_LOG.md`; it
  overrides the cache location.
- **Start and settings.** The skill is `$formalize-paper` (Claude Code: `/formalize-paper`); Codex
  does not read `.claude/settings.json`: its settings come from `install-codex.sh` (user and project
  `.codex/config.toml`) and the launch command it prints. After a context compaction, re-read RUN.md
  and the current stage file, as under Claude Code.
- **Protection.** Reviewer restrictions are protocol restrictions enforced by detection, the same
  design as Claude Code, **not per-agent filesystem isolation**. Built-in agents inherit the
  parent's sandbox and do not have Claude's per-role tool allowlist.
- **Reviewer definitions.** The Codex auditor TOML is generated from the body of
  `audits/agents/auditor.md`; the other roles derive from the common subagent block in
  AUDIT_PROTOCOL.md, and their tasks are the same generated prompt files Claude uses.
  `integrity.py` pins the TOML hashes. Never edit role files during a pinned run.

## Other agent CLIs

The protocol, scripts and files do not depend on which agent runs them. Two parts are specific to
Claude Code: the `auditor` subagent type (`audits/agents/auditor.md`) and the `/formalize-paper`
skill (`audits/skills/`). Under another agent CLI that has subagents: define an equivalent
read-only auditor agent, point the skill's instruction at RUN.md, and keep every rule. This is
untested.

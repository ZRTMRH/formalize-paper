# Codex CLI support (experimental)

Codex support is experimental. Under Codex CLI 0.163.0 two hands-off runs have delivered on the
current version, on Linux: the example note and a real 5-page paper (about 4 h, the same outcome as
under Claude Code). The citation check does not yet run under Codex (planned). Codex on macOS: one run (the example note) delivered on the `macos` branch.

> **What "experimental" means in practice (tested with Codex CLI 0.163.0)**
> - Earlier versions ran end to end on the one-page example note (0.2.0) and a small synthetic paper
>   (a pre-release of 0.3.0). On the current version it has delivered on the example note and on a real
>   5-page paper (Linux, about 4 h, the same outcome as under Claude Code), and on the example note on macOS.
> - A run can stall: a "Selected model is at capacity" error stops the session until someone
>   types "resume". The optional watchdog only notifies you; it never resumes.
> - Without `--add-dir <project>/.git` every git commit of the agent waits for your approval.
>   With it, every sandboxed agent can also write the project's git metadata, including hooks
>   that later run outside the sandbox (detected by `tree_state.py`, not prevented).
> - Reviewers are not sandboxed from each other: they share the parent's sandbox, and their
>   independence rests on instructions plus after-the-fact checks (tokens, seals, lanecheck,
>   tree_state), as under Claude Code.
> - The test runs took 9 h 34 min (sparse-note, 0.2.0) and 12 h 26 min (the synthetic paper, a
>   pre-release of 0.3.0, on a shared machine), including stalls.

The shared Claude/Codex protocol is `audits/RUN.md` (`audits/run/codex.md` lists every difference, and
`audits/run/spawn-and-seal.md` how children are spawned and waited for).
Reviewers run as Codex built-in subagents, not as separate `codex exec` processes.

## Install and start

Installing and logging in to the Codex CLI, and the full sequence, are in INSTALL.md, "Codex CLI".
In short, from your home directory:

```bash
~/formalize-paper/install.sh --codex ~/my-formalization
cd ~/my-formalization && codex --sandbox workspace-write --add-dir ~/my-formalization/.git
```

(`install.sh --codex` prints this command with the project's actual git directory.) Install
before starting the session, so that its role catalog includes all eleven generated agents. When
Codex first opens the project it asks whether you trust the folder: answer yes; the project's
`.codex/config.toml` and roles are loaded only for a trusted folder. Do not turn the sandbox off to
load roles. If a startup warning (`F2`) still says project-local config is disabled after you trusted
the folder, restart Codex's background server (`/daemon`, "Restart background server") before you
go on (seen with 0.163.0). Then type `$formalize-paper`.

The installer requires Python 3.11+ (or Python 3.10 with `tomli`) for safe TOML edits. It adds
the following required setting to `${CODEX_HOME:-~/.codex}/config.toml` (which applies to every
Codex session on the machine) and to the project's `.codex/config.toml`, preserving unrelated
settings and comments and backing up a changed file once as `config.toml.before-formalize-paper`:

```toml
[shell_environment_policy.set]
PYTHONDONTWRITEBYTECODE = "1"
```

This applies to spawned commands, including built-in reviewer commands. Environment include
allowlists, including a profile's, must retain the variable; the installer refuses an
incompatible allowlist (before installing anything) rather than install an ineffective setting.
Unusual existing TOML layouts can require a manual edit. Verify the effective environment inside
the session: type `!python3 -c 'import os; assert os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"'`
(a line starting with `!` runs as a shell command), or ask the agent to run it. Do not update a
pinned run's configuration or tools mid-run. See the
[official shell environment documentation](https://learn.chatgpt.com/docs/config-file/config-advanced#shell-environment-policy).
How to undo every change: INSTALL.md, "Uninstall".

## Roles and source of truth

| Role | Canonical instructions and full task |
|---|---|
| `formalize_auditor` | Body of audits/agents/auditor.md, also installed/pinned for Claude; generated lane prompt |
| `formalize_adjudicator` | Common subagent rules in AUDIT_PROTOCOL.md; generated step-4 prompt |
| `formalize_informalizer` | Same common rules; generated blind informalizer prompt |
| `formalize_reader` | Same common rules; generated fresh-reader prompt |
| `formalize_writer` | Same common rules; generated sign-off writer prompt |
| `formalize_escalation` | Same common rules; the escalation-check prompt plus the question |
| `formalize_renderer` | Same common rules; the generated PDF prompts (renderer, verifier, cover, checkers; `run/render-pdf.md`) |
| `formalize_tool_patch_reviewer` | Same common rules; the generated tool-patch reviewer prompt (release mode: `tool_patch.py review`, RUN.md "Tool patches") |
| `formalize_status_check` | Same common rules; the generated status-check prompt (no longer used at delivery since 2026-10-28: the delivery reviewers run as `formalize_reader`, run/stage5-delivery.md step 5) |
| `formalize_citations` | Same common rules; the citation prompts (agents 1 and 2, Stage 5 step 5a), each with intake 1c's network rule |
| `formalize_helper` | Same common rules; the author-side helper brief (`--prompt formalizer`) plus its assignment |

`audits/run/codex.md` maps every subagent the Claude Code path spawns to its role, and lists every
other Claude/Codex difference (network, PDF viewing, waits). No role sets the network, the sandbox
or tools: each child inherits the parent's sandbox (network off), so under Codex the citation
agents reach the cited works only when the session was started with `--search`, which is untested
for children; use it only for a public paper (intake 1c). Without it the citation notes degrade
(items "not reachable", or "not produced: no network"), never a stop.

Each role's instructions end with one Codex-only sandbox rule (`codex_agents.SANDBOX_RULE`): a command
the sandbox blocks is recorded as a failure, never escalated to an approval.

Not yet covered by a generated role in this version: the advisory citation agents (Stage 5 step
5a) and the author-side helpers; `audits/run/codex.md` does not map them to a role yet. A Codex
run may therefore skip or improvise these steps (the citation notes are advisory).

`audits/codex_agents.py` generates project `.codex/agents/*.toml`; all roles select
`gpt-6.1-sol` with `model_reasoning_effort="medium"`. `integrity.py` checks deterministic
canonical derivation and pins actual role-file hashes, so a changed model, instruction or missing
role invalidates the run. There is no separately maintained Codex reviewer instruction body.

Always use fresh context (`fork_turns="none"`, or v1 `fork_context=false`), never author-history
forks or reused reviewer threads. Wait for children with one blocking `wait_agent` call with a
long `timeout_ms` (minutes), not with repeated short waits, `sleep` or `list_agents` polls: each
poll is a model turn that re-sends the whole context (`audits/run/spawn-and-seal.md`, "Under Codex"). The installed backend accepts `agent_type` plus the role name.
Spawn lanes in parallel; seal individual completions as they arrive. A fresh agent still receives
normal system, environment and skill context; it must not inherit author conversation or other
lanes' judgments. These boundaries were tested by independent canary tests, with retained logs.

## Protocol restrictions and attribution

Reviewer restrictions are **protocol restrictions enforced by detection**, the same as Claude
Code, **not per-agent filesystem isolation**. Codex agents inherit the parent's sandbox and
approval policy. Unlike Claude, Codex 0.163.0 does not provide its per-role tool allowlist.

Every lane receives a random token only in its generated spawn envelope. Its commitment file
contains only SHA-256 of the token (plus prompt identity). Do not redirect spawn envelopes into
prompt files, scripts or operator logs. The verdict must contain its lane_token, which necessarily
makes that token readable after publication. Model-client session logs can also retain messages;
protocol rules forbid siblings from reading those logs. Tokens are not lasting secrets.

A token alone does not authenticate contents once published. The owning agent computes SHA-256
from its intended serialized verdict bytes **in memory before writing** and returns that digest
in its own LANE_COMPLETION result. The orchestrator uses only that originating child's result
for `lane_auth.py seal`, which validates token and bytes and commits the expected digest. Never
seal the bytes found on disk merely because the child completed. Commitments and seals are
checked against their first committed versions, and lanecheck rechecks every verdict against
its commitment and seal, both after lanes and in step 4. A token-preserving replacement before
completion is refused at sealing; a later replacement violates the stored seal.

This detects persistent replacements. A write later restored to the exact legitimate bytes
leaves no snapshot evidence. A determined agent with access to all checks and repositories can
still forge history; the existing threat model is accidental/over-helpful behavior, not a hostile
same-user process. Probe contents are still governed by the existing evidence/integrity checks;
verdict tokens/seals do not cryptographically bind every probe byte.

The orchestrator checks **every child's result and expected files**, even when the parent exits
0. A child error, a missing output or a missing completion digest is a mechanical failure: that
child alone is re-run with its original message, within a time budget (`audits/run/spawn-and-seal.md`).
What a failed seal, token or lanecheck line does is RUN.md's failure table: a token, digest or seal
mismatch is an integrity fault -- in the default release installation the agent redoes the review
and the report discloses it (the run stops for you only at the four release stops), in a dev
installation it stops the run for you at every involvement level; a lane's own mistake is a NOTE the
adjudicator settles.
The actual per-child status matters; a parent process can exit 0 after reporting a child's error.
Never retry a failed reviewer outside the sandbox automatically.

## Watchdog: notification when a run stops (optional, notify-only)

A Codex turn can end on a service error instead of a result: in the reference run the parent
stopped on "Selected model is at capacity. Please try a different model." and sat idle until a
person noticed. `codex/watchdog.py` (in the formalize-paper clone) notices for you. **It never types into the session**: an
adversarial test of an auto-resume version showed that injecting keystrokes into a live TUI cannot
be made safe (an approval overlay, a draft, a resized screen or a misread log turn the keys into
answers nobody gave), so automatic resume is deferred (a future version may use Codex's app-server
API). You resume yourself; the watchdog prints a suggested resume line.

```bash
cd ~/my-formalization && python3 ~/formalize-paper/codex/watchdog.py --once    # check: it names the session it pinned
python3 ~/formalize-paper/codex/watchdog.py --notify-cmd "notify-send formalize-paper"   # then leave it running
```

- **What it reads.** One session log, pinned at startup: `--session-log FILE`, or the single
  interactive (`source: cli`) session of the project written in the last `--max-age-h` hours
  (default 12). It refuses to start if there is none, more than one (name the right one), or the
  file is not a cli session of the project. It never reads the terminal; children's sessions are
  ignored.
- **What it reports, once per turn.** *stalled*: the turn ended on a service error and nothing in
  it needs you. *needs a human: <reason>*: a STOP, FAIL, FAILED, FAIL(s), RED or "PHASE 0: RED" in
  a checker's output or in the agent's or a child's messages, a checker exiting non-zero, a usage
  or rate limit (429, too many requests), an approval request, any other error, or a normal turn
  end (a checkpoint, a question, the end of the run). It never says *stalled* when any of these is
  present. Command output that Codex stores as JSON inside strings (several objects per string,
  "Warning: truncated output" headers, objects cut off) is decoded first.
- **How it tells you.** A line and the terminal bell in its own terminal, a JSON line in
  `~/.cache/formalize-paper/watchdog/<start>.log` (`--log`; outside the project so that it cannot
  look like a lane write to `tree_state.py`), and `--notify-cmd`, if given, run with the
  notification text as one extra argument (split once with shlex at startup; never a shell string
  built from log text).
- **Why Python, why `codex/`.** A shell `until/while … sleep` loop started in the project would
  match `lanecheck.py`'s stray-loop scan. It is not part of the protocol (the agent never runs it,
  and it only notifies), so it lives in the clone's `codex/`, outside the pinned apparatus; it reads
  the clone's `audits/project.py` for the script registry. Its tests run from the clone:
  `python3 -B codex/watchdog.py --selftest` and the mutation suite's codex kind (WD1–WD26,
  `python3 -B audits/tests/mutants.py --kind codex`).
- **Tested** with the reference run's real events as fixtures (`codex/watchdog_fixtures.json`: its
  capacity stop, a child's integrity FAIL in a JSON tool result, a JSON-wrapped FAIL command output,
  two real truncated multi-chunk outputs) and the adversarial scenarios that concern detection, and
  replayed over the whole real parent log (its capacity stop is the one *stalled*; its FAILs are
  each *needs a human*). Experimental.

## Fallback and logs

`audits/codex_spawn.py` remains an explicitly selected fallback for environments without built-in
agents. It runs separate CLI processes, uses medium reasoning, rejects missing/empty/stale
finals and known sandbox startup errors, and validates authenticated owner completion seals.
Nested sandbox failures remain possible; do not silently switch to this fallback or escalate.

Its `--log-dir PATH` overrides `~/.cache/formalize-paper/codex/<timestamp>/`. Record actual log
locations. For built-in agents retain child thread ids and session-log locations, effective
models/efforts, and each completion/seal. Inspect executed reads, not mere filename mentions in
prompts. Sensitive spawn tokens should be redacted in exported evidence.

## Git commits without approval prompts

The default workspace-write sandbox keeps the project's top-level `.git` read-only, so every
`git switch`, `git add` and `git commit` of the author asks the person for approval (12
approvals in the reference run, each a stall until someone answered). Under a delegating
involvement level the run must not wait at them (`audits/run/codex.md`). Tested on Codex 0.163.0
in a scratch repository with `codex exec --sandbox workspace-write -c approval_policy="never"`
(`approval_policy="never"` only so that the scratch test could not prompt; never use it for a
run):

| setting | `git add` + `git commit` in the repository |
|---|---|
| default | fails: `.git/index.lock: Read-only file system` |
| `-c 'sandbox_workspace_write.writable_roots=["<repo>/.git"]'` | succeeds |
| `--add-dir <repo>/.git` | succeeds |
| the same `writable_roots` in the project's `.codex/config.toml`, project not trusted | fails (the project config is not loaded) |

So start the session with `--add-dir <project>/.git` (the installer prints the exact command).
It applies to that session only and to nothing outside the git directory; network stays off and
approvals for anything else stay as they were. A nested repository's `.git` -- the audit record
`audits/.git` -- was already writable under the default sandbox in the same test.

What it allows: built-in reviewers inherit the parent's sandbox, so every sandboxed child can
also write the project's git metadata for the whole session (they could already write the
working tree and `audits/.git`). **That includes `.git/hooks/` and `.git/config`: a hook or a
config entry (`core.hooksPath`, an alias, an include, a filter) planted there runs later, when
the operator or you run git, outside the sandbox.** This is a route out of the sandbox. Detection:
`tree_state.py` records every hook file (content and mode) and the repository config (local and
worktree scope, included files read; only user, branch and remote URL/fetch keys left out) of the
project's and the audit record's repositories at Phase 0, and any change, at the adjudicator's
check or at the next Phase 0, is an integrity failure (release: the agent restores the snapshot
and discloses it, and a changed remote, credential or user setting, or a change that keeps
recurring, is stop 3, yours; dev: the run stops for you). It detects; it does
not prevent a hook or a config entry that runs before the check, and it does not cover other
nested repositories (for example Lake's packages under `.lake/packages/`). The
protection stays the same as under Claude Code: detection, not isolation. A reviewer commit moves
`HEAD`, which `tree_state.py` records and checks at step 4, and the freeze and integrity checks
compare approved statements and records with their pins. If you prefer approval prompts for the
author's commits, leave out `--add-dir`; the run then needs someone to answer them (involved level
recommended). No writable login-directory or network override is needed to start built-in
reviewers.

## Tests

The capability tests established fresh context, canonical instructions, medium effort, artifact
return and explicit failure delivery. A live attribution test passed a clean parallel round plus project writes, pinned-definition edits, and
token-preserving sibling replacements before and after owner completion. Self-tests and mutants
cover the checks. `codex/watchdog.py --selftest` and the `codex` mutant kind test the watchdog.
The test logs are not public (they contain machine-specific details); the results are summarised
here. These tests ran on 0.2.0 and earlier, not on this version.

## History

An earlier Codex path ran each reviewer as a separate `codex exec` process: its full test run on
the example (0.1.0) took 2 h 21 min with 26 approvals, reviewers outside the parent sandbox and at
reasoning effort none. The built-in-subagent run (0.2.0) took 9 h 34 min including service and driver
pauses, with 12 author-only approvals, no reviewer approvals or escapes, at medium effort; all ten
proofs and delivery gates passed, with document limitations disclosed. That is not a speed
improvement. Official sources:
[OpenAI subagents documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and [version-pinned implementation](https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/core/src/agent).

# Installing formalize-paper

This takes about 30 minutes the first time, most of it downloading Mathlib. Every command runs in
a terminal on Debian or Ubuntu, or Ubuntu under WSL2, with `sudo` for the packages.

**System**: Debian or Ubuntu, or Ubuntu under WSL2 on Windows. On a Mac, use the separate `macos`
branch of this repository.

## 1. Requirements (once)

On Debian or Ubuntu (including Ubuntu under WSL2):

```bash
sudo apt update
sudo apt install -y git python3 curl \
  texlive-xetex texlive-latex-extra texlive-fonts-recommended \
  fonts-dejavu fonts-freefont-ttf poppler-utils python3-fonttools
```

- The PDFs are made by agents (a renderer, a verifier and two checkers) from the markdown the
  scripts write. The renderer needs a PDF engine: the TeX packages above (or pandoc with a LaTeX
  engine). `poppler-utils` (`pdftoppm`, `pdftotext`) lets the agents look at the pages; the fonts
  give them the symbols. `python3-fonttools` is not needed. Without any engine the run still
  finishes and delivers the markdown, disclosed. The project's permissions allow the engines only
  with shell escape off (`-no-shell-escape`; pandoc with `--sandbox`).
- **Disk.** About 7 GB per Lean project, mostly the prebuilt Mathlib, plus about 3 GB for the TeX
  packages.
- **Memory.** 16 GB is enough, one paper at a time: say so at intake question 7, and the run keeps at most 3 agents at a time, each compiling its Lean files one at a time. 8 GB works, more slowly: ask at question 7 for one agent at a time. 32 GB is comfortable.
- **Lean.** If `lean --version` does not work, install elan (it provides `lean` and `lake`), then
  open a new terminal:
  `curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh`
- **Claude Code.** Install it with `curl -fsSL https://claude.ai/install.sh | bash` (other methods:
  <https://code.claude.com/docs/en/setup>), open a new terminal, and log in: run `claude`, then
  follow the login prompt. Claude Code needs a paid plan; a run spawns dozens of subagents, so a
  Claude Max plan is recommended. Parallel runs share the subscription's usage limits:
  check that enough of the weekly limit is left before starting, and expect more 5-hour pauses
  when several papers run at once.
- **Git identity**, if it is not set: `git config --global user.name "Your Name"` and
  `git config --global user.email "you@example.com"`.
- **Python** must be 3.10 or newer (`python3 --version`); 3.11 or newer (or 3.10 with `tomli`) for
  `install.sh --codex`.

## 2. A Lean project

formalize-paper works inside a Lean project that requires Mathlib. If you have one, use it: it
must be a git repository with at least one commit, and `lake build` must work in it.

Otherwise, create one in your home directory. This release was tested with Lean and Mathlib
v4.35.0; the `math` template pins the Mathlib release that matches the Lean version you give it,
so the two always agree (a newer version should work but has not been tested):

```bash
cd ~
lake +leanprover/lean4:v4.35.0 new my-formalization math   # a Lake project that requires Mathlib
cd my-formalization
lake exe cache get        # prebuilt Mathlib: minutes, not hours (`lake new … math` may already have done it)
git add -A && git commit -m "new project"    # `lake new` created the git repository; this is its first commit
```

A clone of Mathlib itself also works; `audits/run/stage1-setup.md` covers both setups.

If `lake` ever starts compiling Mathlib file by file (thousands of `Building Mathlib…` lines), stop
it. The cache did not apply, and compiling Mathlib from source takes hours. Run
`lake exe cache get` again. If it reports failed downloads, repeat it until the downloads
succeed before running self-tests; a successful project build alone does not establish that
every self-test dependency is cached.

## 3. Install

```bash
git clone https://github.com/ZRTMRH/formalize-paper ~/formalize-paper
~/formalize-paper/install.sh ~/my-formalization
```

**Install before you open Claude Code (or Codex) in the project**: both read their settings when a
session starts. For Codex, run `install.sh --codex` (section "Codex CLI" below) INSTEAD of this
command; a second install refuses because `audits/` exists.

**Run mode.** The default install is `release`: a run stops only for the four stops that remain at
every level (a goal result that looks false or unprovable; an outward action you did not allow;
something only you can fix, another program that keeps changing the project's files included; a
genuine ambiguity in the paper's meaning). A faithfulness, proof or integrity fault is cured by the
agent with a fixed, logged step, and a fault of presentation or bookkeeping (a
report's rendering, a record's format, a crash of a tool that serves only those) is disclosed in the
run record `deliverables/RUN_RECORD.md` (how the run went: stops, self-cures, set-asides, tool patches;
markdown only) instead of stopping the run.
`install.sh --dev` keeps every stop (for people changing the apparatus). The mode is fixed per
installation (`audits/RUN.md`, "Run mode").

`install.sh` itself does four things, and nothing else; it never uses the network (`--codex` adds
the Codex steps listed in "Codex CLI" below):

1. It copies the apparatus into `~/my-formalization/audits/` and makes that directory a git
   repository of its own. That repository is the *audit record*.
2. It links `AUDIT_PROTOCOL.md` into the project root, and adds `audits/`, `AUDIT_PROTOCOL.md`,
   `.formalization-work/` and `deliverables/` to the project's `.git/info/exclude`. The record
   therefore never enters the project's own history.
3. It installs the reviewer agent and the skill for your user: `~/.claude/agents/auditor.md` and
   `~/.claude/skills/formalize-paper/`. A different existing copy is backed up first.
4. It sets `"env": {"PYTHONDONTWRITEBYTECODE": "1"}` and the protocol's permission list (below) in
   the **project's** `~/my-formalization/.claude/settings.json`. Claude Code runs every command of a session in that
   project with this environment, so no Python helper leaves `__pycache__` bytecode next to the
   pinned scripts (unpinned bytecode in the apparatus fails the integrity check and stops a
   round). Only this project is affected; your own `~/.claude/settings.json` is not touched. An
   existing project file is merged: every other key and variable is kept, and the old file is
   saved as `settings.json.before-formalize-paper`. A file the installer creates is added to the
   project's `.git/info/exclude`; if the file is tracked in the project and changed, commit it
   before the run (Phase 0 runs on a committed tree). Install before opening Claude Code: it reads
   settings when the session starts.

It refuses, before writing anything, if the directory is not the root of a git repository with a
lakefile, if `audits/` already exists, if `.claude/settings.json` exists but is not valid JSON
(comments are not allowed in it) or cannot be written, if anything it would write is not
writable, or if a project-level `.claude/agents/auditor.md` exists (it would override the pinned
reviewer; a project `.claude/settings.json` does not, and is kept).

### Permissions

A run works in Claude Code's **default permission mode** or in **auto mode**; auto mode is the
realistic setting for a hands-off run. The protocol's own steps ask for no permission in either,
so a hands-off run needs no one at the keyboard as long as it stays within them (what still asks
is listed at the end of this section).

- **Which mode you are in** is shown on the bottom line of the Claude Code screen (nothing extra
  for the default mode; a marker such as "auto mode on" otherwise). **Shift+Tab** cycles through
  the modes; stop on the one you want before you type `/formalize-paper`.
- **Default mode:** every action outside the allow list below asks you.
- **Auto mode:** an action outside the allow list does not ask you; it goes to Claude Code's
  safety classifier, which lets it run or blocks it. The allow list below still applies first,
  and its deny rules still win. The protocol's integrity checks do not depend on the mode: they
  detect after the fact what a prompt would have asked about.
- **Never `bypassPermissions`** (or `--dangerously-skip-permissions`): it runs every action
  unchecked, and the protocol never needs it.
- **Claude Code may update itself in the background** and show "Update installed · Restart to
  update". You do not need to restart mid-run; the update takes effect the next time you start
  Claude Code (a run resumes from its files).

The installer adds to the project's
`.claude/settings.json` exactly what the run does (checked against `audits/RUN.md`, `audits/run/`,
`AUDIT_PROTOCOL.md` and the skill). Claude Code applies a project's allow rules only after you
accept its workspace-trust dialog, so the first time you open Claude Code in the project, read the
listed rules and accept. What Claude Code does with them, from its documentation
(<https://code.claude.com/docs/en/permissions>):

- in the default mode, every shell command and every file edit asks unless an allow rule matches;
  a built-in set of read-only commands never asks (`ls`, `cat`, `grep`, `find`, `diff`, read-only
  `git` such as `git status`, `git diff`, `git log`, `git show`, `git grep`);
- `Bash(x *)` matches `x` and `x …`; a rule without `*` matches one exact command; in a compound
  command (`a && b`, `a | b`) every part must match;
- `Edit(…)` rules cover every file-writing tool (Write included) and use gitignore patterns; in
  project settings `/path` means a path from the project root; deny rules win over allow rules.

The rules added:

- **Commands:** `lake build …`, `lake env lean …`, `lake exe cache get`; each audit script by name,
  `python3 audits/<script>.py …` (the scripts the registry `project.SCRIPTS` marks agent-run:
  prompt, phase0, project, scope, integrity, lanecheck, lane_auth, tree_state, signoff, readers,
  decisions, audit_coverage, axiom_sweep, unused_args, dependencies, stops, selftest_all); `git status`, `git rev-parse`, `git branch --show-current`, `git switch -c`,
  `git add`, `git commit`, `git fetch upstream` (exactly), `git -C audits status|add|commit|mv`,
  `git -C audits checkout -- …`, the read-only `git -C audits log|show` (the adjudicator reads the
  audit record's history), and Stage 1's copy of the default license text to `LICENSE` (exactly). The run's other needs go through these scripts: the
  environment check (`project.py --env-check`), compiling a `.tex` source with shell escape off
  (`project.py --compile-source`), creating and committing the helpers' work directory
  (`project.py --init-work-dir`, `--work-commit`), a fresh scratch directory for each subagent
  inside the project (`project.py --scratch <name>`), and the delivery copy into `deliverables/`
  (`project.py --prepare-delivery`, then `project.py --deliver`), and the run log (`project.py --log <section>`, `--stage [<text>]`).
  Readers run their scripts by relative path, and git without `-C`.
- **File edits:** Lean files anywhere in the project (`Edit(/**/*.lean)`), the lakefile, `LICENSE`, the
  helpers' work directory `.formalization-work/` (inside the project, excluded from its git
  history), the project configuration `audits/projects/*.json`, the main agent's (the *operator's*)
  and the adjudicator's records in `audits/<project>/` (`RUN_LOG.md`, `AUTHOR_NOTES.md`, `DEVIATIONS.md`, `OUTCOMES.md`,
  `READER_NOTES.md`, `DECISIONS.md`, `PAPER_DEFECTS.md`, `SKIPPED.md`, `VACUOUS.md`,
  `KNOWN_FAULTS-*.md`, `QUESTIONS-B-*.md`, the reader responses `readers/*.response*.md`), and each
  round's verdicts, probes, re-votes, `ADOPTED.md` and `OUTCOMES.md`. Scratch files live under
  `.formalization-work/scratch/`.
- **Denied edits:** the pinned apparatus (`audits/*.py`, `audits/*.lean`, `audits/*.md`,
  `audits/*.json`, `audits/*.sh`, `audits/agents/`, `audits/run/`, `audits/skills/`, `audits/tests/`) and Lake's packages
  (`.lake/`), whatever else would allow them.

**These rules let the agent and every reviewer run arbitrary code without asking: a Lean file can
run programs through `lake env lean`/`lake build`, and `python3 audits/…` runs any script under
that path. The permission list saves prompts; it is not a sandbox. Run formalizations under a
dedicated user account or a dedicated machine/VM with no credentials (SSH keys, cloud tokens,
other projects) you are not willing to expose, and do not keep other work in that account.**
(Scripts are allowed one by one, so the rule cannot reach a file outside `audits/`, and the
scripts themselves cannot be edited without a prompt.) The same holds for git and edits: a
reviewer's `git add` or `git commit`, including `git commit --amend`, and a reviewer's edit of a
Lean file or of another role's record, no longer trigger a prompt; such writes are caught only
afterwards, by the integrity checks (`tree_state.py` flags a moved `HEAD`, any rewrite of
recorded history and any file a lane wrote; `integrity.py` checks record ownership).

What still asks: copying the deliverables anywhere outside the project (they are delivered to
`<project>/deliverables/` by `project.py --deliver`; a copy elsewhere is a `cp`, or yours), deleting
a stray file a lane left (`rm`, rare), a paper source outside the project (keep it inside, for
example in `paper/`: the run refuses a `source_pdf` outside the project, because every reviewer's
read of it would ask), and anything else not above (a command the agent improvises, an edit
outside these paths, network access, `git push`). In the default mode, answer it, or tell the
agent to use the protocol's form; in auto mode the classifier decides it instead of asking you.
Never run a formalization with `--dangerously-skip-permissions` or
`"defaultMode": "bypassPermissions"`: the protocol does not need them, and they would let any
command run unasked. The installer warns if the project's settings already say
`bypassPermissions`, and never sets it. Your own rules in the file are kept.

## 4. Check the installation (about 5 minutes)

```bash
cd ~/my-formalization
python3 -B audits/selftest_all.py --fast
```

The last line must be `ALL SELFTESTS: ok`. Every checking script tests itself against
fixtures, including cases that must fail. (Without `--fast`, the Lean-backed self-tests are
reported as skipped until a project exists: they need a built project, which the run sets up.)

## 5. A first run

Put the paper where the run can read it, for example `~/my-formalization/paper/`. A `.tex` source
is much better than a PDF: results are cited by line number, and the run compiles the source once
to read the true numbering. The paper does not need to be committed: the run reads it from disk.
For a confidential paper, keep it out of git (add `paper/` to `.git/info/exclude`) so that a push
of the branch cannot carry it. Then:

```bash
cd ~/my-formalization
claude
```

In Claude Code, type `/formalize-paper`. The agent reads `audits/RUN.md` and sends the intake
questions as one message, printed by `audits/prompt.py --intake` and labelled 1a to 7:

| Question | What to decide |
|---|---|
| 1 Source | the `.tex` path; whether it is the authors' own text, and which version; whether it is confidential (if so, no subagent uses the network and nothing is pushed; the paper is still sent to the model provider, as everything in a Claude Code or Codex session is) |
| 2 Range | the whole paper or some results; which result(s) are the goal |
| 3 Literature and libraries | which cited results to take as named hypotheses (3a); which Lean libraries besides Mathlib may be used (3b) |
| 4 Library work | faithfulness only (the default), or also search Mathlib for duplicates |
| 5 Budget, involvement, approver | the budget and who pays (5a, 5b); how involved you want to be after the intake (5c, below); who approves the statements (5d) |
| 6 Deliverables | who reads the report; where to copy the PDFs; whether the Lean branch (6c) and the audit record (6d) may be pushed, and where; whether defects go to the authors (6e) |
| 7 Anything else | known doubts, conventions, deadlines |

A sample answer (adapt it; the agent asks follow-ups if something is unclear):

```
1a: paper/note.tex  1b: the authors' own text, arXiv v2  1c: not confidential
2a: the whole paper  2b: Theorem 1.1  2c: default
3a: default  3b: default
4: faithfulness only
5a: standard  5b: my Claude Max subscription  5c: (a)  5d: Jane Doe (me)
6a: me  6b: ~/Documents/reports  6c: no  6d: no  6e: no
7: nothing else
```

The *budget* (question 5) sets how much reviewing is done: `light` runs 3 review lanes and at most 2
diff rounds (rounds that re-examine only what changed); `standard` 4 lanes and at most 4;
`thorough` 4 lanes until a round adopts nothing. (A *lane* is one reviewer criterion; a *round* is
one pass of the reviewers plus the adjudicator's decisions.) The usage a run consumes depends on the
paper. For planning: about 4–5 hours for a short paper (a few pages, about ten results), and 1–2
days for a paper like the 30-page L∞ paper (67 results), plus the time you take at the checkpoints.

After the intake, the agent creates the run's git branch (its name is shown at Checkpoint A), and works
on its own. It stops three times:

- **Checkpoint A**, after the intake: the setup on one screen. Approve it or correct it.
- **Checkpoint B**, when the statements are written and before any proof is merged: `SIGNOFF.pdf`, one entry
  per result. You can read it and approve everything, read it and list what you reject, or let
  the agent approve everything without reading it; in the last case the report says that no
  person reviewed the statements.
- **Checkpoint C**, at the end: `SUMMARY.pdf` (read first), `REPORT.pdf` and `DECISIONS.md`. Answer in the conversation.

**Only an answer you type yourself in the Claude Code session counts as yours.** An answer relayed
by another AI agent (a second Claude session, a script, an assistant acting for you), or an
instruction such as "approve whatever the reviewers accept", is recorded as the agent's approval,
and the summary and report say that no person reviewed the statements.

The *involvement* answer (question 5c) can remove the waits at B and C (the README, "How a run
goes", has a table of the three levels). **Involved** (the default)
is what is described above. **Statements only**: you answer at Checkpoint B, and the agent takes
every later decision itself. **Hands-off**: the agent also approves the statements and answers
Checkpoint B's questions, so after Checkpoint A the run finishes without asking you. A decision
the agent takes this way is final, and its record says what reversing it would cost (nothing,
new proofs, a new statement sign-off, or a new audit round): it follows the adjudicator's
recommendation, or else the most conservative choice that stays with the paper, and the report and `DECISIONS.md`
("Decisions taken on your behalf") list each one and say that no person reviewed it. The run
still stops for you (in the default release installation, for exactly these four) if a goal
result looks false or unprovable as stated; on anything outward-facing the intake did not allow
(pushing, contacting the authors); if something needs what only you can provide (a login, more
quota, administrator rights, a change to your own files, or stopping another program that keeps
changing the project's files); and if the paper's meaning is genuinely ambiguous on a point that
matters and the reviewers cannot settle it: you are shown the passage, the possible readings and
what each would mean for the formalization, and asked which is meant, after which the run goes on
at your level. A loosely used convention (whether the natural numbers start at 0 or at 1, say) is
not such a stop: the agent takes the intended reading and the report records it.
Under *statements only*, a change to a statement you approved also stops the run. Under a delegating
level, a stop caused only by a check's bookkeeping (a lane mistake, a reviewer's record left uncommitted) is cleared
by the agent with a fixed, logged command, never one whose cause could be tampering, and no check
is waived; the report lists every stop and who cleared it. The choice
cannot be changed once the run starts. Under both delegating levels the run delivers `SUMMARY.pdf`, `REPORT.pdf`
and `DECISIONS.md` at the end and does not wait at Checkpoint C. Hands-off removes the
checkpoints, not the need for someone to type `continue` after a usage limit (below); the protocol's
own steps ask for no permission (above), but copying the deliverables outside the project,
deleting a stray file and a command the agent improvises outside the list do. And without a person at Checkpoint B,
every judgement that a Lean statement says what the paper says rests on the AI reviewers
(KNOWN_LIMITATIONS.md): if you can, keep (a) or (b), or have a mathematician read at least the
riskiest statements on `SIGNOFF.pdf`.

Everything is recorded under `audits/<project>/`; `RUN_LOG.md` is the running log.

**If Claude stops mid-run** (a usage-limit message, or an API error such as "overloaded" or a
network error that ends its turn): leave the session open. Once the limit resets (the message says
when), or after a minute for an API error, type `continue`. The run picks up where it stopped.

**If the session ends** (a closed terminal, a crash): open `claude` in the project
again and type `/formalize-paper`. Stage 0 reads `RUN_LOG.md` and resumes. Before Checkpoint A
nothing is recorded yet, so the intake simply starts again. It finds the run by the
checked-out git branch, so if you switched branches, switch back first.

**Memory.** On a 32 GB machine, 6–8 reviewer subagents per wave and three Lean builds at once are
fine. On less memory, ask the agent to spawn smaller waves.

## Independent check of the proofs

After delivery you can re-check every proof with `leanchecker`, which ships with each Lean
toolchain since v4.28.0. It re-adds every compiled declaration to a kernel environment, so each is
type-checked again by Lean's own kernel; it does not check what the statements mean (that is the
sign-off sheet's job). Work in a fresh clone of the run's branch, and name the library (`<Lib>`,
the project's Lean library; with no name, `leanchecker` guesses the wrong module):

```bash
git clone --branch formalize/<project> <run-repository> check && cd check
grep -nE 'leanOptions|moreLeanArgs|weakLeanArgs|debug\.|skipKernel' lakefile.*   # kernel-affecting options?
lake exe cache get && lake build <Lib>
lake env leanchecker -v <Lib>          # each project module; exit 0 = all accepted (about 40 s)
lake env leanchecker --fresh -v <Lib>  # optional: the whole import closure (about 20 min, ~9 GB)
```

The first replay needs about 12 GB of free memory. On a tested run's Lean the two replays took
38 s and 21 min.

## Trying it on the example

`examples/sparse-note/` is a synthetic one-page note, already set up as a Lean project with its
statements written:

```bash
~/formalize-paper/examples/sparse-note/setup.sh ~/sparse-note-try
cd ~/sparse-note-try && lake exe cache get && lake build SparseNote
python3 -B audits/selftest_all.py        # the full self-test, Lean-backed checks included (slower than --fast)
claude                                   # then /formalize-paper
```

`setup.sh` writes the example's project configuration, but there is no `RUN_LOG.md` yet, so
Stage 0 starts a new run: it asks the full intake and works on a new branch it creates.
For Codex, run `setup.sh --codex ~/sparse-note-try` instead (and `--dev` for a dev installation): the
flags are passed to `install.sh`, which cannot add them to an existing installation later.

## Codex CLI (experimental)

Use this **instead of section 3**. Codex support is experimental (see the box at the top of
[`codex/README.md`](codex/README.md)); for a real paper, use Claude Code.

1. **Install and log in to the Codex CLI.** Tested with version 0.163.0:

   ```bash
   npm install -g --prefix ~/.local @openai/codex@0.163.0   # ~/.local/bin must be on your PATH
   codex --version                                          # codex-cli 0.163.0
   codex login                                              # follow the browser login
   ```

   You need a ChatGPT plan with Codex access that offers the model the generated reviewer roles
   use (`gpt-6.1-sol`; codex/README.md, "Roles"). Keep the version fixed for the whole run: the run
   is pinned to its tools, so update Codex only between runs (if your installation updates itself,
   turn that off for the run).
2. **Build first, with the network on:** `lake exe cache get && lake build` in the project (section
   2). Inside the Codex sandbox there is no network. In a clone of Mathlib itself, also run
   `git fetch upstream` now. The agent will not push or copy files outside the project under
   Codex: it gives you the commands at the end.
3. **Install:**

   ```bash
   ~/formalize-paper/install.sh --codex ~/my-formalization
   ```

   This does everything section 3 describes, and also installs the skill where Codex reads it
   (`~/.agents/skills/formalize-paper/`), eleven generated subagent roles in the project
   (`.codex/agents/`), and `PYTHONDONTWRITEBYTECODE = "1"` under `[shell_environment_policy.set]` in
   your user Codex config (`~/.codex/config.toml`, which affects **every** Codex session on this
   machine) and in the project's `.codex/config.toml`, keeping your other settings and backing up
   each changed file once as `config.toml.before-formalize-paper`. It needs Python 3.11+ (or 3.10
   with `tomli`), and refuses (before writing anything) a config whose environment include
   allowlist, or a profile's, would drop the variable.
4. **Start Codex** with the command the installer prints:

   ```bash
   cd ~/my-formalization && codex --sandbox workspace-write --add-dir ~/my-formalization/.git
   ```

   `--add-dir …/.git` lets the agent commit without an approval prompt per commit (needed for a
   hands-off run). It also lets every sandboxed agent write the project's git metadata, including
   hooks that later run outside the sandbox (`tree_state.py` detects a change; it does not prevent
   it): codex/README.md, "Git commits without approval prompts". When Codex first opens the project it asks whether you trust the folder: answer yes
   (the project's `.codex/config.toml` and the generated roles are loaded only for a trusted
   folder). Codex 0.163.0 keeps a background server that may still hold the settings from before
   you trusted the folder: if the screen shows a warning (`F2` to view) that project-local config
   is disabled, type `/daemon`, choose "Restart background server", then "Restart"; the warning
   must be gone before you go on. Inside the sandbox no agent has the network, so the advisory citation notes cannot
   read the cited works; for a **public** paper you may add `--search` (Codex's web-search tool,
   not a sandbox change; untested for subagents) so that they can. Never add it for a confidential
   paper. Without it the run is the same, with fewer citation notes (`audits/run/codex.md`).
5. **Check the environment** in the session: type `!python3 -c 'import os; assert
   os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"; print("ok")'` (a line starting with `!` runs
   as a shell command), or ask the agent to run that command and show its output. It must print `ok`.
6. Type `$formalize-paper`.

Optionally run `python3 <clone>/codex/watchdog.py` (the clone you installed from) in a second
terminal in the project: it tells you
(terminal line and bell, and an optional `--notify-cmd`) when the run stalls on a service error
such as "Selected model is at capacity" or needs you for any other reason. It is notify-only:
you resume the session yourself (codex/README.md, "Watchdog"; experimental). Never upgrade configuration or
pinned tools during a run.

## Upgrading

A run in progress is pinned to the tooling it started with (`integrity.py`), so never upgrade in
the middle of a run. Between runs, from the new clone:

```
./install.sh --upgrade <lean-project-dir>      # add --codex as at install
cd <lean-project-dir> && python3 -B audits/selftest_all.py --fast
```

`--upgrade` replaces the apparatus in `audits/` with this version (every file outside
`audits/projects/` and each project's rounds directory; a file this version no longer has is
removed), keeps those records, their history and the run mode (`--dev` changes it), and commits the
change in the audit record as `upgrade formalize-paper <version>`. It then reinstalls the agent,
the skill and the settings as an install does. It refuses an audit record with uncommitted
changes (an untracked file inside a rounds directory, such as a round's `prompts/`, is left alone
and never committed). A project pinned to the old tooling keeps its record, but a run continued on it would fail
integrity's tooling check: start the next run afresh. Running `install.sh` without `--upgrade` on
a project that has `audits/` refuses and names `--upgrade`. (`audits/tests/upgrade.py --selftest`
tests this from the clone; tier 0 runs it.)

## Uninstall: what the installer changed

Every path `install.sh` writes, and how to undo it:

| path | what | undo |
|---|---|---|
| `<project>/audits/` | the apparatus and the audit record (its own git repository) | keep it if you want the record; otherwise move it away |
| `<project>/AUDIT_PROTOCOL.md` | a symlink to `audits/AUDIT_PROTOCOL.md` | delete the link |
| `<project>/.git/info/exclude` | lines `audits/`, `AUDIT_PROTOCOL.md`, `.formalization-work/`, `deliverables/`, and `.claude/settings.json` if the installer created it (`.codex/` with `--codex`) | delete those lines |
| `<project>/.claude/settings.json` | `env.PYTHONDONTWRITEBYTECODE`, and the `permissions.allow` and `permissions.deny` entries listed under "Permissions" | restore `settings.json.before-formalize-paper` next to it, or delete the file if the installer created it |
| `<project>/.claude/settings.json.before-formalize-paper` | the backup of your earlier project settings (only if there were any) | delete it after restoring, or keep it |
| `<project>/.claude/` | created if it did not exist | delete it if it is now empty |
| `~/.claude/agents/auditor.md` | the reviewer agent | delete it; a different earlier copy was saved as `auditor.md.bak.<timestamp>` |
| `~/.claude/skills/formalize-paper/` | the skill | delete the directory; an earlier `SKILL.md` was saved as `SKILL.md.bak.<timestamp>` |

With `--codex`, also:

| path | what | undo |
|---|---|---|
| `~/.agents/skills/formalize-paper/SKILL.md` | the skill for Codex (overwritten, no backup) | delete the directory |
| `${CODEX_HOME:-~/.codex}/config.toml` | `[shell_environment_policy.set] PYTHONDONTWRITEBYTECODE = "1"`: applies to every Codex session | restore `config.toml.before-formalize-paper`, or delete that one line |
| `<project>/.codex/config.toml` | the same setting for this project | restore its `.before-formalize-paper` copy, or delete the file |
| `<project>/.codex/agents/*.toml` | the eleven generated subagent roles (pinned by a run) | delete them after the run |

A run itself writes `<project>/.formalization-work/` (the helpers' drafts, `work_dir`, and the
compiled paper source; excluded from the project's history), the run's
branch in the project, and logs under `~/.cache/formalize-paper/` (`codex/`, `watchdog/`). Nothing
is installed system-wide, and nothing is pushed.

## If something fails

- **`ALL SELFTESTS` is not ok.** Read the FAIL line. The usual cause is a missing tool from step 1
  (`git`, `python3`, `lake`). No selftest compiles a PDF.
- **`lake` errors about the toolchain.** Run `lake exe cache get` again in the project.
- **`/formalize-paper` says the apparatus is not installed.** Step 3 was skipped, or Claude Code was
  started outside the project root.

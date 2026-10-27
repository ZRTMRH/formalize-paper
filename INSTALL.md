# Installing formalize-paper

This takes about 30 minutes the first time, most of it downloading Mathlib. Every command runs in
a terminal on Debian or Ubuntu, or Ubuntu under WSL2, with `sudo` for the packages. Other Linux
distributions and macOS are untested.

## 1. Requirements (once)

On Debian or Ubuntu (including Ubuntu under WSL2):

```bash
sudo apt update
sudo apt install -y git python3 curl \
  texlive-xetex texlive-latex-extra texlive-fonts-recommended \
  fonts-dejavu fonts-freefont-ttf poppler-utils python3-fonttools
```

- The TeX packages, the two font packages and `poppler-utils` (for `pdftotext`) build and check
  the PDF report and the sign-off sheet. `python3-fonttools` is optional: without it, the report
  cannot check that every symbol has a glyph.
- **Disk.** About 8 GB per Lean project, mostly the prebuilt Mathlib, plus about 3 GB for the TeX
  packages.
- **Memory.** 16 GB at least (then ask the agent for smaller reviewer waves); 32 GB recommended.
- **Lean.** If `lean --version` does not work, install elan (it provides `lean` and `lake`), then
  open a new terminal:
  `curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh`
- **Claude Code.** Install it with `curl -fsSL https://claude.ai/install.sh | bash` (other methods:
  <https://code.claude.com/docs/en/setup>), open a new terminal, and log in: run `claude`, then
  follow the login prompt. Claude Code needs a paid plan; a run spawns many subagents, so a Max
  subscription is the practical minimum.
- **Git identity**, if it is not set: `git config --global user.name "Your Name"` and
  `git config --global user.email "you@example.com"`.
- **Python** must be 3.10 or newer (`python3 --version`).

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
git init && git add -A && git commit -m "new project"
lake exe cache get        # prebuilt Mathlib: minutes, not hours (`lake new … math` may already have done it)
```

A clone of Mathlib itself also works; `audits/RUN.md` (Stage 1) covers both setups.

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

`install.sh` itself does four things, and nothing else; it never uses the network:

1. It copies the apparatus into `~/my-formalization/audits/` and makes that directory a git
   repository of its own. That repository is the *audit record*.
2. It links `AUDIT_PROTOCOL.md` into the project root, and adds both `audits/` and
   `AUDIT_PROTOCOL.md` to the project's `.git/info/exclude`. The record therefore never enters the
   project's own history.
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

A run uses Claude Code's **normal (default) permission mode**. The protocol's own steps ask for no
permission, so a hands-off run needs no one at the keyboard as long as it stays within them (what
still asks is listed at the end of this section). The installer adds to the project's
`.claude/settings.json` exactly what the run does (checked against `audits/RUN.md`,
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
  `python3 audits/<script>.py …` (prompt, phase0, project, scope, integrity, lanecheck, lane_auth,
  tree_state, signoff, readers, decisions, audit_coverage, axiom_sweep, unused_args,
  selftest_all); `git status`, `git rev-parse`, `git branch --show-current`, `git switch -c`,
  `git add`, `git commit`, `git fetch upstream` (exactly), and `git -C audits status|add|commit|mv`
  and `git -C audits checkout -- …`. The run's other needs go through these scripts: the
  environment check (`project.py --env-check`), compiling a `.tex` source with shell escape off
  (`project.py --compile-source`), creating and committing the helpers' work directory
  (`project.py --init-work-dir`, `--work-commit`), a fresh scratch directory for each subagent
  inside the project (`project.py --scratch <name>`), and the delivery copy into `deliverables/`
  (`project.py --deliver`). Readers run their scripts by relative path, and git without `-C`.
- **File edits:** Lean files anywhere in the project (`Edit(/**/*.lean)`), the lakefile, the
  helpers' work directory `.formalization-work/` (inside the project, excluded from its git
  history), the project configuration `audits/projects/*.json`, the operator's and adjudicator's
  records in `audits/<project>/` (`RUN_LOG.md`, `AUTHOR_NOTES.md`, `DEVIATIONS.md`, `OUTCOMES.md`,
  `READER_NOTES.md`, `DECISIONS.md`, `PAPER_DEFECTS.md`, `SKIPPED.md`, `VACUOUS.md`,
  `KNOWN_FAULTS-*.md`, `QUESTIONS-B-*.md`, the reader responses `readers/*.response*.md`), and each
  round's verdicts, probes, re-votes, `ADOPTED.md` and `OUTCOMES.md`. Scratch files live under
  `.formalization-work/scratch/`.
- **Denied edits:** the pinned apparatus (`audits/*.py`, `audits/*.lean`, `audits/*.md`,
  `audits/*.json`, `audits/*.sh`, `audits/agents/`, `audits/skills/`, `audits/tests/`) and Lake's packages
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
outside these paths, network access, `git push`). Answer it, or tell the agent to use the
protocol's form. Never run a formalization with `--dangerously-skip-permissions` or
`"defaultMode": "bypassPermissions"`: the protocol does not need them, and they would let any
command run unasked. The installer warns if the project's settings already say
`bypassPermissions`, and never sets it. Your own rules in the file are kept.

## 4. Check the installation (about 5 minutes)

```bash
cd ~/my-formalization
python3 -B audits/selftest_all.py --fast
```

The last line must start with `ALL SELFTESTS: ok`. Every checking script tests itself against
fixtures, including cases that must fail. Before the first run, the line is exactly

```
ALL SELFTESTS: ok (2 skipped until a project exists: make_report.py, check_index.py)
```

which is a pass: those two self-tests need a project configuration, which the run writes at
intake.

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

In Claude Code, type `/formalize-paper`. The agent reads `audits/RUN.md` and asks the intake
questions in one message:

| Question | What to decide |
|---|---|
| 1 Source | the `.tex` path; whether it is the authors' own text, and which version; whether it is confidential (if so, no subagent uses the network and nothing is pushed; the paper is still sent to the model provider, as everything in a Claude Code or Codex session is) |
| 2 Range | the whole paper or some results; which result(s) are the goal |
| 3 Literature results | which cited results to take as named hypotheses |
| 4 Library work | faithfulness only (the default), or also search Mathlib for duplicates |
| 5 Budget, approver, involvement | the budget; who approves the statements; how involved you want to be after the intake (below) |
| 6 Deliverables | who reads the report; where to copy the PDFs; whether anything may be pushed, and where |
| 7 Anything else | known doubts, conventions, deadlines |

A sample answer (adapt it; the agent asks follow-ups if something is unclear):

```
1. paper/note.tex; the authors' own text, arXiv v2; not confidential.
2. The whole paper; the goal is Theorem 1.1; every numbered environment.
3. Take every cited literature result as a named hypothesis.
4. Faithfulness only.
5. Budget standard; my Claude Max subscription; involvement (a) involved;
   approver: Jane Doe (me).
6. I read the report; copy the PDFs to ~/Documents/reports; do not push; do not contact the authors.
7. Nothing else.
```

The *budget* (question 5) sets how much reviewing is done: `light` runs 3 review lanes and at most 2
diff rounds (rounds that re-examine only what changed); `standard` 4 lanes and at most 4;
`thorough` 4 lanes until a round adopts nothing. The usage a run consumes depends on the paper.
One measured run (67 results, 30 pages, Claude Opus 5.5) took about
16 h of model activity over two days, hit one session usage limit, and used 7,639 model calls;
the README has the details. It is a data point, not an estimate for your paper.

After the intake, the agent creates the run's git branch (its name is shown at Checkpoint A), and works
on its own. It stops three times:

- **Checkpoint A**, after the intake: the setup on one screen. Approve it or correct it.
- **Checkpoint B**, when the statements are written and before any proof: `SIGNOFF.pdf`, one entry
  per result. You can (a) read it and approve everything, (b) read it and list what you reject, or
  (c) let the agent approve everything without reading it. With (c), the report says that no person
  reviewed the statements.
- **Checkpoint C**, at the end: `REPORT.pdf` and `DECISIONS.md`. Answer in the conversation.

The *involvement* answer (question 5) can remove the waits at B and C. **Involved** (the default)
is what is described above. **Statements only**: you answer at Checkpoint B, and the agent takes
every later decision itself. **Hands-off**: the agent also approves the statements and answers
Checkpoint B's questions, so after Checkpoint A the run finishes without asking you. A decision
the agent takes this way is final, and its record says what reversing it would cost (nothing,
new proofs, a new statement sign-off, or a new audit round): it follows the adjudicator's
recommendation, or else the most conservative choice that stays with the paper, and the report and `DECISIONS.md`
("Decisions taken on your behalf") list each one and say that no person reviewed it. The run
still stops for you on anything outward-facing the intake did not allow (pushing, contacting the
authors), on an integrity failure, if a goal result looks false or unprovable as stated, and if
the machine needs something only you can provide (a login, more quota, administrator rights).
Under *statements only*, a change to a statement you approved also stops the run. The choice
cannot be changed once the run starts. Under both delegating levels the run delivers `REPORT.pdf`
and `DECISIONS.md` at the end and does not wait at Checkpoint C. Hands-off removes the
checkpoints, not the need for someone to restart the session after a usage limit; the protocol's
own steps ask for no permission (above), but copying the deliverables outside the project,
deleting a stray file and a command the agent improvises outside the list do. And without a person at Checkpoint B,
every judgement that a Lean statement says what the paper says rests on the AI reviewers
(KNOWN_LIMITATIONS.md): if you can, keep (a) or (b), or have a mathematician read at least the
riskiest statements on `SIGNOFF.pdf`.

Everything is recorded under `audits/<project>/`; `RUN_LOG.md` is the running log.

**If the session ends** (a usage limit, a closed terminal, a crash): open `claude` in the project
again and type `/formalize-paper`. Stage 0 reads `RUN_LOG.md` and resumes. Before Checkpoint A
nothing is recorded yet, so the intake simply starts again. It finds the run by the
checked-out git branch, so if you switched branches, switch back first.

**Memory.** On a 32 GB machine, 6–8 reviewer subagents per wave and three Lean builds at once are
fine. On less memory, ask the agent to spawn smaller waves.

## Trying it on the example

`examples/sparse-note/` is a synthetic one-page note, already set up as a Lean project with its
statements written:

```bash
~/formalize-paper/examples/sparse-note/setup.sh ~/sparse-note-try
cd ~/sparse-note-try && lake exe cache get && lake build SparseNote
python3 -B audits/selftest_all.py        # the full self-test, Lean-backed checks included
claude                                   # then /formalize-paper
```

The example's configuration is already in place, so Stage 0 finds the project on the
`sparse-note` branch. Because there is no `RUN_LOG.md` yet, it starts a new run with the intake.

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
   2). Inside the Codex sandbox there is no network.
3. **Install:**

   ```bash
   ~/formalize-paper/install.sh --codex ~/my-formalization
   ```

   This does everything section 3 describes, and also installs the skill where Codex reads it
   (`~/.agents/skills/formalize-paper/`), five generated reviewer roles in the project
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
   folder).
5. **Check the environment** in the session: type `!python3 -c 'import os; assert
   os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"; print("ok")'` (a line starting with `!` runs
   as a shell command), or ask the agent to run that command and show its output. It must print `ok`.
6. Type `$formalize-paper`.

Optionally run `python3 audits/watchdog.py` in a second terminal in the project: it tells you
(terminal line and bell, and an optional `--notify-cmd`) when the run stalls on a service error
such as "Selected model is at capacity" or needs you for any other reason. It is notify-only:
you resume the session yourself (codex/README.md, "Watchdog"; experimental). Never upgrade configuration or
pinned tools during a run.

## Upgrading

A run in progress is pinned to the tooling it started with (`integrity.py`), so never upgrade in
the middle of a run. Between runs, move `audits/` aside and run `install.sh` again; then copy your
earlier projects' records (`audits/projects/*.json` and `audits/<project>/`) back if you want to
keep them in the same record.

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
| `<project>/.codex/agents/*.toml` | the five generated reviewer roles (pinned by a run) | delete them after the run |

A run itself writes `<project>/.formalization-work/` (the helpers' drafts, `work_dir`, and the
compiled paper source; excluded from the project's history), the run's
branch in the project, and logs under `~/.cache/formalize-paper/` (`codex/`, `watchdog/`). Nothing
is installed system-wide, and nothing is pushed.

## If something fails

- **`ALL SELFTESTS` is not ok.** Read the FAIL line. The usual cause is a missing tool from step 1
  (`xelatex`, `pdftotext`) or a missing font: `fc-list | grep -E "DejaVu|FreeMono"` must list both.
- **`lake` errors about the toolchain.** Run `lake exe cache get` again in the project.
- **`/formalize-paper` says the apparatus is not installed.** Step 3 was skipped, or Claude Code was
  started outside the project root.

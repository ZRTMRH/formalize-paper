# Stage 1 — setup

Read this after the human's OK at Checkpoint A. It ends with the pin commit; then run
`python3 audits/project.py --stage "Stage 2 — statements"` and read `stage2-statements.md`.

0. **No bytecode.** Run `python3 audits/project.py --env-check` (it must print `ok`).
   Every command of the run must have `PYTHONDONTWRITEBYTECODE=1`. Cached bytecode a helper
   leaves in `audits/` is a NOTE, and `--env-check` removes it; a `.pyc` that can run without its
   source (outside `__pycache__`, or unchecked-hash) is unpinned code, and `integrity.py` stops the
   round on it. Under Claude Code,
   `install.sh` puts `"env": {"PYTHONDONTWRITEBYTECODE": "1"}` in the project's
   `.claude/settings.json`, which Claude Code reads when the session starts; under Codex,
   `install-codex.sh` sets it in `[shell_environment_policy.set]` (see `codex.md`). If the
   check fails, this is an environment fault for the human (at every level): ask them to add the
   setting (`python3 audits/claude_settings.py .claude/settings.json`) and restart the session in
   the project. Never delete bytecode to get past an integrity failure.
   **A stop before the config exists** (this step, step 1's cache): record it with `python3
   audits/stops.py open --note "<what failed>" --cause env-unknown`. With no config yet it is kept
   beside the saved intake as `P<n>` (one at a time, a human stop only); close it with the human's
   answer, `stops.py close --stop P<n> --human "<their answer, verbatim>"`. Step 5's
   `project.py --intake-move` moves it under `RUN_LOG.md`'s `## Stops` (it refuses while one is
   open).
   **Permissions.** The run uses Claude Code's normal permission mode; `install.sh` allowed exactly
   the commands this file runs (INSTALL.md, "Permissions"). Never ask the human to switch to
   `bypassPermissions` or `--dangerously-skip-permissions`, and never suggest it to save prompts.
1. **Branch.** Create the run's branch from the current commit: `git switch -c <branch>` (a resumed
   run whose branch already exists: `git switch <branch>`; never a second `-c`, never a new intake). Then
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
   partly fail). Stop and tell the human only if the cache still cannot be obtained (RUN.md, "Stops
   that remain at every level", environment faults), recorded as in step 0 ("A stop before the config
   exists").
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
   - A project made with `lake new <name> math` also has the template library (for example
     `MyFormalization`, holding `def hello := "world"`) as a default build target. Leave it alone:
     it is the user's, the run builds only its own `lean_lib` (`build_cmds`), and nothing of the
     run uses it. Name it at Checkpoint A ("other libraries in the lakefile") so the user can remove
     it, and do not list it in `lean_files`.
   - Create `<Name>/Common.lean` and `<Name>/Examples.lean` (stubs are fine), inside the project
     namespace, add both to `lean_files` and import them from `<Name>.lean` (Phase 0 fails on an
     unlisted project file). `Common.lean` is imported by every statement file and holds facts more
     than one file needs; `Examples.lean` imports the statement files and holds named witnesses
     (Stage 3 says how both are used). In a test run 35 duplicate helpers came from section
     helpers that could not see each other's work.
   - Create `<Name>/Main.lean`, holding the index table: `| Theorem 1.1 | \`thm_1_1\` |`.
     **Backticks are for Lean names only; write mathematics as `$…$`** (`index_strict` enforces
     it).
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
   - `mode` as `project_template.json` has it (set at install; the config check refuses another).
   - `calibration` is `"none recorded yet"` for each lane.
   - `work_dir` is a persistent directory for the helpers' drafts, by default
     `.formalization-work/<name>` (relative to the project root: inside the project, excluded from
     its git history, and covered by the project's permission rules). Create it with
     `python3 audits/project.py --init-work-dir` (it refuses a temporary directory: a reboot wipes
     it).
   - Rewrite `blind_spots` for this source.
   - `standing_defers` gets one entry per literature hypothesis (id, item naming the hypothesis,
     reason "literature result taken as a hypothesis; non-vacuity cannot exhibit a witness",
     revisit_when "never"). Without these, every round reports it UNCOVERED and the loop never
     exits.
   - **No value may contain `<<`.**
4. **Checks.** `python3 audits/prompt.py --show` lists no unfilled blank, and
   `python3 audits/selftest_all.py --project <name> --fast` passes (in `release` mode a
   `DISCLOSED[selftest]` line does not fail it: record it with `stops.py disclose --cmd "python3
   audits/selftest_all.py --fast"` once step 5 has created the log).
5. **Commit and pin.**
   - Create `<ROUNDS-DIR>/RUN_LOG.md` (sections below, "RUN_LOG.md sections"): `python3 audits/project.py
     --intake-move` puts the intake saved in Stage 0 (with the line `python3 audits/prompt.py --intake
     --hash` prints; the pin refuses without it) under `## Intake (<date>)` and removes the saved copy.
     Record the Checkpoint A approval, and set the stage with `project.py --stage`.
   - Commit the Lean scaffold.
   - Commit the audits repo, naming what you set up: `git -C audits add projects/<name>.json
     <ROUNDS-DIR-IN-AUDITS>/RUN_LOG.md && git -C audits commit -m "setup <name>"` (by name; never
     `git add -A`, here or anywhere in a run).
   - Run `python3 audits/integrity.py --pin`, then commit **only** that file, with the message
     it prints (`pin`). The pin also records the Stage 1 snapshot of the git hooks and config
     (`tree_state.py --restore-gitmeta` restores it in release).

   From here on the apparatus and the scope-defining configuration are frozen for this run.

## RUN_LOG.md sections

`project.py --log` creates a missing section before `## Current stage`.

```markdown
# Run log — <PROJECT>
## Intake (date)            the line `intake-message sha256 <hex>` (prompt.py --intake --hash); one line
                            per label (1a–1c, 2a–2c, 3a–3b, 4, 5a–5d, 6a–6e, 7), verbatim or close
                            to it; "default" where the human took it (5d only in the fixed form
                            `prompt.py --intake --5d <who>` prints: `- 5d: agent` or `- 5d: human
                            <name>`; anything else reads as the human)
## Checkpoint A (date)      approved configuration; pin commit
## Stage 2                  statement commit, round, counts; Checkpoint B answer verbatim (date, commit)
## Rounds                   one line per round: commit · lanes · P/F/A/N · ADOPT/REJECT/DEFER/Q/U · time
## Mechanical failures      re-runs, retries and cures, and why
## Stops                    written by stops.py close, disclose and repair-lock only
## Set-asides               written by stops.py set-aside only
## Open questions           for the human; mark each "(answered <date>: <answer>)"; never delete
                            (a [PROXY] decision: "[PROXY <date>, operator for <who>; reversible] …";
                            a delegated one: the [DELEGATED …] tag of RUN.md)
## Checkpoint C (date)      the human's answers to DECISIONS.md, verbatim
                            (delegated: "## Checkpoint C (<date>, delegated)", one [DELEGATED] line per decision)
## Answered                 one line per answered item: - answered <anchor> (<date>, <round>): <answer>
## Fresh readers            one line per pass: document · sha256 · commit · pass n · verdict line · reader file
## Current stage            one line, set with project.py --stage (this is what resume reads)
```

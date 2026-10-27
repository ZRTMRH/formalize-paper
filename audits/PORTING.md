# Moving a run to another machine

A run lives in two git repositories:
- the Lean project, on the run's branch;
- the audit record, `audits/` inside the project, which is a repository of its own.

Moving a run means moving both. A run is pinned to its tooling (`integrity.py`), so the new
machine must use the run's own `audits/` scripts, never a newer install.

## On the old machine

Commit everything first: a run resumes from what is committed. Then, from the Lean project root:

```bash
git -C audits bundle create ~/audits-<project>.bundle --all
git bundle create ~/lean-<project>.bundle <the run's branch>
```

Copy both files to the new machine. Alternatively, push both repositories to remotes you control,
but only if the intake allowed pushing (for a confidential paper, private remotes only).

## On the new machine

1. **Lean.** Install the requirements and Lean as in `INSTALL.md`, steps 1–2. Get the Lean project
   there (a clone of it), then fetch the run's branch:
   ```bash
   git fetch ~/lean-<project>.bundle <branch>:<branch> && git switch <branch>
   lake exe cache get
   ```
2. **The audit record.** Restore it **instead of** a fresh install: do not run `install.sh` in this
   project. Clone the bundle as `audits/`, and do by hand what the installer would do:
   ```bash
   git clone ~/audits-<project>.bundle audits
   ln -s audits/AUDIT_PROTOCOL.md AUDIT_PROTOCOL.md
   printf 'audits/\nAUDIT_PROTOCOL.md\n' >> .git/info/exclude
   mkdir -p ~/.claude/agents ~/.claude/skills/formalize-paper
   cp audits/agents/auditor.md ~/.claude/agents/auditor.md
   cp audits/skills/formalize-paper/SKILL.md ~/.claude/skills/formalize-paper/
   ```
3. **Check.** Both of these must pass:
   - `python3 -B audits/selftest_all.py` ends with `ALL SELFTESTS: ok`;
   - `python3 audits/integrity.py --check`.
4. **Work directory.** Make sure the run's `work_dir` (in `audits/projects/<project>.json`) exists
   on this machine. If the helpers have drafts that are not yet merged, move them there too.
5. **Resume.** Open Claude Code in the project and type `/formalize-paper`. Stage 0 reads
   `RUN_LOG.md` and resumes.

## Bringing the results back

Do the same in reverse: bundle the audit record (`--all`) and the run's branch. Then, on the first
machine:
- `git -C audits pull ~/audits-<project>.bundle <branch of the record>`
- `git fetch ~/lean-<project>.bundle <branch>:<branch>`

# Test tiers (maintainers)

This page is for people changing the apparatus (the scripts under `audits/`, `RUN.md`, the stage
files, `AUDIT_PROTOCOL.md`). An operator running a formalization never needs it: RUN.md's Stage 1
runs `selftest_all.py --fast`, and that is all a run needs.

Run every command from a project (a Lean project with `audits/` installed, e.g. the sparse-note
example), because the Lean-backed tests use it. The `codex` mutants are the exception: they run
from the clone (below).

| tier | when | command | time (sparse-note, 12 cores) |
|---|---|---|---|
| 0 | every change | `python3 -B audits/tests/tier.py 0` | ~15 s |
| 1 | before a merge to `main` | `python3 -B audits/tests/tier.py 1 --since <base>` | ~7 min plus the Lean mutants of touched files |
| 2 | release | `python3 -B audits/tests/tier.py 2 --compare-serial` | ~1-2 h |

- **Tier 0**: `selftest_all.py --fast`: every pure selftest, as an operator's Stage 1 runs it. No
  selftest compiles a PDF (the PDFs are rendered by agents, `render_record.py`). Run tier 0 from an
  installed project (install.sh), not only from the clone. From the clone it also runs, alongside,
  `tests/fresh_install.py --selftest` (install.sh into a scratch project that has the user's own
  README.md, then `selftest_all.py --fast --dev` there: a selftest that read the clone's README as
  formalize-paper's failed in every install, tier 1 2026-10-25), and then
  `tests/upgrade.py --selftest` (install.sh --upgrade end to end in a scratch project).
- **Tier 1**: tier 0; then, from a project, the fast selftests once per run mode x involvement
  level (`FORMALIZE_TEST_MODE=<release|dev>` and `FORMALIZE_TEST_INVOLVEMENT=<level>`, honoured
  only by a `--selftest` process: they set the project config's mode and level as the selftests
  read them), because a selftest that read the run's own level once stopped a hands-off run
  (small-paper run, stop S1), and a release-mode change must never alter dev mode (MAINTAINING
  S3); `tier.py --selftest` checks that the plan covers all six; then
  `mutants.py --kind plain --jobs N`: every plain mutant, N at a time. With `--since <base>` (the
  commit your branch started from) it also runs, serially, the `lean` mutants whose mutated file
  you changed: a change to a Lean-backed script is tested by its Lean mutants before the merge, not
  only at release (RULINGS, group D/E).
- **Tier 2**: the full `selftest_all.py` (Lean), the snapshot replay (below) and every mutant,
  Lean serial.
  `--compare-serial` also runs the whole mutant list with `--jobs 1` and fails if any mutant's
  result differs between the two runs. Do this at least once on each new machine and after any
  change to `mutants.py`, before trusting `--jobs` (ADVERSARIAL E2: the parallel kill set must
  equal the serial one).

## Test switches

`FORMALIZE_TEST_MODE` and `FORMALIZE_TEST_INVOLVEMENT` (`project._test_level`) change the mode
and level of the project config only in a process whose own argv has `--selftest`; a real command
with them set keeps its config's mode and level, and `project.problems` still refuses a mode
other than the installation's (MAINTAINING A3). `project.py --selftest` checks both, also from a
separate process, and mutants TM1-TM3 make the mode switch leak.

## Snapshot replay (tier 2)

`python3 -B audits/tests/snapshot_replay.py [--only mini1,...] [--modes dev] [--record]` copies
each run snapshot into `~/.cache/formalize-paper/replay/` (never /tmp), preferring the FULL
snapshots (`<parent>/full-snapshots/mini{1..5}/<project>`, `<parent>` by default
`~/formalization-work/release-test`, with the project's `.git` and
`audits/.git`), else the old ones (`<parent>/mini{1..5}-snapshot/<project>`, no git). The
snapshots are the maintainers' test runs and are not distributed: without them the replay
prints SKIP; `--snapshots` / `FORMALIZE_REPLAY_SNAPSHOTS` names the parent. It installs this checkout's
apparatus, sets the config's mode and level, and runs the read-only gates (integrity --check,
lanecheck per round, phase0 --readonly with the Lean steps skipped, make_report --check,
decisions --check, readers --check, stops list) under release x dev x the three levels. Each
gate's exit code and `KIND[code]` tags are compared with `tests/replay_baseline/mini<n>.json`.
Without snapshots it prints SKIP and exits 0. It takes about two and a half minutes.

- **Closer control** (U2 §4, L1; not recorded, never a baseline). In each release row, every gate
  that passes and is the release closer of some cause code (`project.CLOSER`: integrity, lanecheck
  of the newest round, phase0, make_report, decisions, readers report) is run once more for one code
  per kind and class with a stop of that code open (committed as `stops.py open` commits it, then
  taken out); it must still pass. A failure fails the replay. The in-process L1 of `stops.py
  --selftest` runs every code x mode x level (real integrity check, stand-ins for the rest). It
  takes the replay from about one minute to about two and a half.
- **Dev rows never change** (S3). A step that changes release behaviour on purpose re-records
  only the release rows, `--record --modes release`, in the same commit, and says in the commit
  message which rows moved and why.
- **Full snapshots** keep the run's real history (ownership, stop trail, pin); today's apparatus
  and the flipped config enter as one commit plus a re-pin (every row: `NOTE[repinned]`).
- **Path remap** (full snapshots only). The record names `/home/fp-claude/<project dir>/...`
  (lane metadata, prompts, verdicts). Nothing in the copy is rewritten (the lane metadata is
  committed; editing it would be tampering): each gate runs in a user+mount namespace where an
  empty tmpfs hides `/home/fp-claude` and only `/home/fp-claude/<project dir>` is a bind mount of
  the copy. Any other recorded path still fails; the selftest's remap control (a metadata path
  under a sibling project, the home itself, or a look-alike parent stays `PROBLEM[auth-metadata]`)
  guards it, and the selftest also refuses a baseline holding `PROBLEM[auth-metadata]`. Without
  `unshare` or `/home/fp-claude`, full snapshots are SKIPped.
- Old snapshots: the history is synthetic (record before a "pin" commit, then the stop record
  with stops.py's subjects); cited commits do not resolve.

## Mutant kinds

Each mutant in `tests/mutant_list.py` is `(id, file, old, new, selftest, extra args, kind)`:

- `plain`: its selftest is pure Python. (The `pdf` kind went with the PDF compilation, PDF-AGENTS.)
- `lean`: its selftest builds a Lean fixture (fingerprint, axiom_sweep, dependencies,
  `signoff --lean`; the registry `project.SCRIPTS` says which). `mutants.py` refuses a list whose
  `lean` field disagrees with the selftest.
- `codex`: a Codex-only tool in the clone's `codex/` (today `codex/watchdog.py`, notify-only and
  outside the pinned apparatus). File and selftest are paths from the clone root; these run only
  from a clone (`python3 -B audits/tests/mutants.py --kind codex`, with
  `python3 -B codex/watchdog.py --selftest`), and an installed project reports them as not run.
  Run them when you change `codex/watchdog.py` or the registry.

`mutants.py` options: `--kind K[,K]`, `--fast` (every kind but `lean`), `--jobs N` (plain
mutants only; Lean stays serial because every Lean-backed selftest runs `lake env lean` in the one
project, sharing its build, and each Lean process is heavy), `--project NAME`, and id prefixes. Output is in list order for any
`--jobs`; the last line is `mutants: K killed, S SURVIVED or CRASHED, M pattern missing`.

## Where a mutant is killed

A mutant names the selftest that must kill it. Prefer the selftest of the script that owns the
mutated code: it is cheaper and fails for the right reason. Cross-file mutants are kept where they
prove that a sub-check's failure reaches the report: one END-TO-END mutant per report data path
stays through `make_report.py` (marked in the list: M22 changes after the last audit, M31 the
index's cell splitting, M113 open questions); the other mutants of those functions run the owning
script's own selftest.

`tests/doclint.py` holds the checks on the operator's instructions (RUN.md, `audits/run/*.md`, the
intake message) and the lane prompts' record-file rule. A mutant of those documents runs it.

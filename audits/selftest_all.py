#!/usr/bin/env python3
"""Run every negative control in the audit apparatus. Exit 0 iff all pass.

Each script's --selftest builds fixtures with a known answer, including cases that MUST go red.
Run this after changing any script, and once on a new machine before trusting a round. The ones
that call Lean (fingerprint, axiom_sweep, signoff --lean) need a built project and take about a minute.

  python3 audits/selftest_all.py [--project NAME] [--fast] [--dev] [--only a,b] [--jobs N]   (--fast: no Lean)
  python3 audits/selftest_all.py --tooling-id      the id of the committed tooling (git), as ALL SELFTESTS prints it

`--jobs N` (C3b) runs the scripts in a pool of N, the longest first, lean_slot, tests/tier and the Lean-backed ones
alone after it; each line is printed as its script finishes, then the summary in registry order. A script that fails
in the pool is run once more alone; both lines are printed and the second decides. Default: 2 on the 8 GB route
(lean_slot.py --show) or with at most 8 CPUs, else 4; `--jobs 1` is the serial run.

`--only a,b` runs only those scripts (registry names, e.g. `project,tests/delivery`), so a run cut by a harness's
background limit can finish the rest in groups (next batch B10, stage1-setup.md step 4); the union of `ok` lines on
one commit is the check.

In release mode (the project's `mode`, else the installation's; project.RELEASE) a failure confined
to a non-blocking job (project.SCRIPT_RELEASE: the fresh-reader gate and prompt, the doc lint) is
printed as DISCLOSED[selftest] and does not fail the run's pre-pin check: record it with
`stops.py disclose --cmd "python3 audits/selftest_all.py --fast"`. Any other failure, or a crash of a
blocking script, fails. `--dev` makes every failure fail (maintainers: tests/tier.py passes it).
"""
import argparse, hashlib, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project  # noqa: E402  (the script registry, project.SCRIPTS)
PURE = [n + ".py" for n in project.scripts(selftest="pure")]
LEAN = [n + (".py --lean" if "pure" in project.SCRIPTS[n][0] else ".py") for n in project.scripts(selftest="lean")]
# the Lean-backed selftests build against a real project; signoff --lean builds its own
NEEDS_PROJECT = {n + ".py" for n in project.scripts(selftest="lean") if project.SCRIPTS[n][0] == "lean"}
# C3b: the pool's order, longest first (MEASURE-C032 §1); the rest follow in registry order. ALONE run after the pool,
# one at a time: lean_slot and tests/tier time sleeps and fake probes, a Lean-backed one runs Lean
LONGEST = ("tool_patch", "stops", "tests/delivery", "tests/doclint", "integrity", "project", "hypotheses",
           "tests/round3", "signoff", "make_report")
ALONE = ("lean_slot", "tests/tier")


def tooling_id():
    """The committed tooling's id: sha256 of the `git ls-tree -r HEAD` lines of audits/ that are tooling
    (integrity.is_tooling), 12 hex, with "+uncommitted" when the tooling differs from HEAD. The pin (stage1-setup.md
    step 5) needs the id the self-test printed: the tooling did not change while it ran."""
    import integrity
    r = subprocess.run(["git", "-C", HERE, "ls-tree", "-r", "HEAD", "."], capture_output=True, text=True)
    if r.returncode:
        return "unknown (not a git checkout)"
    keep = "".join(l + "\n" for l in r.stdout.splitlines() if integrity.is_tooling(l.split("\t", 1)[-1]))
    return hashlib.sha256(keep.encode()).hexdigest()[:12] + ("+uncommitted" if integrity.tooling_dirty(HERE) else "")


def default_jobs(cfg):
    try:
        import lean_slot
        sz = lean_slot.sizing(lean_slot.total_mb(), cfg)
        small = sz is None or sz["S"] == 1
    except Exception:       # noqa: BLE001 -- unknown memory: the small route
        small = True
    return 2 if small or (os.cpu_count() or 1) <= 8 else 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--dev", action="store_true", help="every failure fails, whatever the run mode")
    ap.add_argument("--only", help="comma-separated registry names to run (the others are not run)")
    ap.add_argument("--jobs", type=int, default=None, help="scripts run at once (default: by the route)")
    ap.add_argument("--tooling-id", action="store_true", help="print the committed tooling's id and exit")
    a = ap.parse_args()
    if a.tooling_id:
        print(f"tooling {tooling_id()}")
        return 0
    tid = tooling_id()
    only = {x.strip() for x in a.only.split(",") if x.strip()} if a.only else None
    if only is not None and not only <= set(project.SCRIPTS):
        print(f"FAIL[tool-call] selftest_all: --only names no script: {', '.join(sorted(only - set(project.SCRIPTS)))} "
              f"(registry names: {', '.join(n for n in project.SCRIPTS if project.SCRIPTS[n][0])})")
        return 2
    bad, skipped, disc = [], [], []
    # The scripts in NEEDS_PROJECT test against a real project. Without --project, use the one the
    # checked-out branch selects. A fresh install has no project until the first intake: those
    # tests are then reported as SKIPPED -- never as passed -- and the summary says so.
    proj = a.project
    if proj is None:
        if project.all_projects():
            try:
                proj = project.select()[0]["name"]
            except project.SelectionError as e:
                if not a.fast:      # --fast runs no Lean-backed script: go on without a project (Stage 1 step 1)
                    print(f"selftest_all: {e}")
                    return 2
    cfg = None
    if proj is not None:
        try:
            cfg = project.select(proj)[0]
        except project.SelectionError:
            cfg = None
    run_cfg = {"mode": "dev"} if a.dev else (cfg if cfg is not None else {"mode": project.installed_mode()})
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")     # C3b: no index.lock taken under the agent's commits
    todo = []       # (script, command, alone)
    for s in PURE + ([] if a.fast else LEAN):
        if only is not None and s.split()[0][:-len(".py")] not in only:
            continue
        lean = s in LEAN
        s, *extra = s.split()
        cmd = [sys.executable, os.path.join(HERE, s), "--selftest", *extra]
        if s in NEEDS_PROJECT:
            if proj is None:
                print(f"  SKIP  {s:20} needs a project config (none yet: run the intake first)")
                skipped.append(s)
                continue
            cmd += ["--project", proj]
        todo.append((s, cmd, lean or s[:-len(".py")] in ALONE))

    def run(i):
        s, cmd, _ = todo[i]
        r = subprocess.run(cmd, cwd=os.path.dirname(HERE), capture_output=True, text=True, env=env)
        out = (r.stdout + r.stderr).strip().splitlines()
        last = next((l for l in reversed(out) if l.strip().lower().startswith("selftest")), out[-1] if out else "")
        nb = project.selftest_release(s[:-len(".py")], "\n".join(out), r.returncode)
        return r.returncode == 0, project.split(run_cfg, nb)[1] if nb else [], last.strip(), out

    def tag(i):
        return "ok  " if res[i][0] else "disc" if res[i][1] else "FAIL"

    def report(i, how=""):
        _ok, _nb, last, out = res[i]
        print(f"  {tag(i)}  {todo[i][0]:20} {last}{how}", flush=True)
        if tag(i) == "FAIL":
            for l in out:
                if "FAIL" in l or "CRASH" in l:
                    print(f"          {l.strip()}")
            print("          Last output lines:")
            for l in out[-12:]:
                print(f"          {l}")

    jobs = max(1, a.jobs if a.jobs is not None else default_jobs(cfg))
    res = {}
    pool = [] if jobs == 1 else sorted((i for i, x in enumerate(todo) if not x[2]),
                                       key=lambda i: LONGEST.index(todo[i][0][:-3]) if todo[i][0][:-3] in LONGEST
                                       else len(LONGEST) + i)
    with ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(run, i): i for i in pool}
        for f in as_completed(futs):
            res[futs[f]] = f.result()
            report(futs[f], "" if res[futs[f]][0] else f"  (in a pool of {jobs}: run again alone below)")
    for i in range(len(todo)):
        again = i in res and not res[i][0]
        if i not in res or again:
            res[i] = run(i)
            report(i, "  (run again alone)" if again else "")
    if len(pool) > 1:
        print(f"summary (registry order; {jobs} at a time, then one at a time):")
    for i, (s, _c, _a) in enumerate(todo):
        if len(pool) > 1:
            print(f"  {tag(i)}  {s:20} {res[i][2]}")
        disc += res[i][1] if tag(i) == "disc" else []
        bad += [s] if tag(i) == "FAIL" else []
    note = f" ({len(skipped)} skipped until a project exists: {', '.join(skipped)})" if skipped else ""
    for p in disc:
        print(project.disclosed_line(p))
    if disc:
        note += f" ({len(disc)} disclosed, release mode: record them with stops.py disclose)"
    if only is not None:
        note += f" (only: {', '.join(sorted(only))})"
    print("ALL SELFTESTS:", ("ok" + note) if not bad else f"FAILED ({', '.join(bad)})", f"[tooling {tid}]")
    return 1 if bad else 0


if __name__ == "__main__":
    import project
    os.environ["FORMALIZE_PAPER_NO_GUARD"] = "1"     # DESIGN-RAM: no test starts a memory guard
    sys.exit(project.run_main(main))

#!/usr/bin/env python3
"""The three test tiers, one command each (maintainer docs: audits/tests/TIERS.md).

  python3 -B audits/tests/tier.py 0                    every change: selftest_all --fast (as an operator
                                                       runs it; nothing compiles a PDF: agents render them);
                                                       from the clone also in a fresh install, alongside
  python3 -B audits/tests/tier.py 1 [--since REF]      before a merge, ~6 min: tier 0, the fast selftests
                                                       again under each run mode x involvement level
                                                       (from a project), then every plain mutant in
                                                       parallel; with --since REF also the Lean-backed
                                                       mutants of every file changed since REF (serial)
  python3 -B audits/tests/tier.py 2 [--compare-serial] release, ~1 h: the full selftest_all (Lean) and
                                                       every mutant, Lean serial;
                                                       --compare-serial also runs the mutants with
                                                       --jobs 1 and fails if any id's result differs;
                                                       also the snapshot replay (snapshot_replay.py)
  python3 -B audits/tests/tier.py --selftest           the tier plan covers both modes x three levels
Common options: --jobs N (default: the number of CPUs), --project NAME (passed through).
Exit 0 iff every step passed. Run it from the project (as selftest_all.py and mutants.py are).
"""
import argparse, os, re, subprocess, sys, threading, time
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS = os.path.dirname(HERE)
def step(name, cmd, env_extra=None, keep=None, quiet=False):
    """Run one command; print its tail and time. (ok, stdout); with quiet, (ok, stdout, the text it would print)."""
    lines = []
    say = lines.append if quiet else (lambda l: print(l, flush=True))
    t = time.time()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("FORMALIZE_TEST_INVOLVEMENT", None)
    env.pop("FORMALIZE_TEST_MODE", None)
    env.update(env_extra or {})
    say(f"== {name}: {' '.join(cmd[2:])}" + "".join(f" ({k}={v})" for k, v in (env_extra or {}).items()))
    r = subprocess.run(cmd, cwd=os.path.dirname(AUDITS), capture_output=True, text=True, env=env)
    out = (r.stdout + r.stderr).rstrip().splitlines()
    bad = [l for l in out if re.match(r"\s*(FAIL|SURVIVED|CRASHED|PATTERN MISSING|BASELINE FAILS)", l)]
    for l in (bad[:40] + out[-2:]) if r.returncode else out[-2:]:
        say("   " + l)
    say(f"   -> {'ok' if r.returncode == 0 else 'FAILED'} in {time.time() - t:.0f} s")
    if quiet:
        return r.returncode == 0, r.stdout, "".join(l + "\n" for l in lines)
    return r.returncode == 0, r.stdout


def lean_mutants_since(ref):
    """Ids of the lean-kind mutants whose mutated file changed since REF (audits/ repo)."""
    r = subprocess.run(["git", "-C", AUDITS, "diff", "--name-only", ref, "--", "."],
                       capture_output=True, text=True)
    if r.returncode:     # e.g. an installed audits/ repo that does not have REF
        print(f"== --since {ref}: git diff in audits/ failed ({r.stderr.strip()[:120]}); run the lean "
              f"mutants by id instead (mutants.py --kind lean ID ...)")
        return None
    top = subprocess.run(["git", "-C", AUDITS, "rev-parse", "--show-prefix"],
                         capture_output=True, text=True).stdout.strip()
    changed = {p[len(top):] if top and p.startswith(top) else p for p in r.stdout.split()}
    os.environ.setdefault("MUTANT_PROJECT", "")
    sys.path.insert(0, HERE)
    from mutant_list import MUTANTS
    return [m[0] for m in MUTANTS if m[6] == "lean" and m[1] in changed]


def config_runs():
    """[(name, env)]: tier 1's extra selftest runs, one per run mode x involvement level. The
    switches are honoured only by --selftest processes (project._test_level; MAINTAINING A3)."""
    sys.path.insert(0, AUDITS)
    import project
    return [(f"mode {m}, involvement {lvl}", {project.TEST_MODE_ENV: m, project.TEST_LEVEL_ENV: lvl})
            for m in project.MODES for lvl in project.INVOLVEMENT_LEVELS]


def selftest():
    sys.path.insert(0, AUDITS)
    import project
    runs = config_runs()
    pairs = {(e[project.TEST_MODE_ENV], e[project.TEST_LEVEL_ENV]) for _, e in runs}
    checks = [
        ("tier 1 runs the selftests under every run mode x involvement level (S3, V4)",
         pairs == {(m, l) for m in project.MODES for l in project.INVOLVEMENT_LEVELS} and len(runs) == len(pairs)),
        ("both modes are among them, dev included (S3: a release change never alters dev)",
         {m for m, _ in pairs} == {"release", "dev"}),
        ("each run sets only the two test switches",
         all(set(e) == {project.TEST_MODE_ENV, project.TEST_LEVEL_ENV} for _, e in runs)),
        ("step() clears both switches from the inherited environment before a run",
         _step_clears()),
    ]
    for name, c in checks:
        print(f"  {'ok  ' if c else 'FAIL'}  {name}")
    ok = all(c for _, c in checks)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def _step_clears(env=None):
    import contextlib, io
    sys.path.insert(0, AUDITS)
    import project
    env = env or {project.TEST_MODE_ENV: "release", project.TEST_LEVEL_ENV: "hands-off"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        code = "import os; print(%s)" % ", ".join("os.environ.get(%r)" % k for k in env)
        with contextlib.redirect_stdout(io.StringIO()):
            _, out = step("probe", [sys.executable, "-B", "-c", code])
        return out.split() == ["None"] * len(env)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def main():
    if sys.argv[1:] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="the test tiers (audits/tests/TIERS.md)")
    ap.add_argument("tier", type=int, choices=[0, 1, 2])
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--project")
    ap.add_argument("--since", help="tier 1: also the Lean-backed mutants of files changed since REF")
    ap.add_argument("--compare-serial", action="store_true",
                    help="tier 2: also run the mutants serially and compare the results id by id")
    a = ap.parse_args()
    py = [sys.executable, "-B"]
    proj = ["--project", a.project] if a.project else []
    st_all, mut = os.path.join(AUDITS, "selftest_all.py"), os.path.join(HERE, "mutants.py")
    t0, ok = time.time(), True
    if a.tier in (0, 1):
        clone = os.path.isfile(os.path.join(os.path.dirname(AUDITS), "install.sh"))
        # the clone: also selftest_all --fast in a FRESH install beside a user's own README.md (tests/fresh_install.py;
        # tier 1, 2026-10-25: doclint passed in the clone and failed in every install). It runs alongside.
        fresh_res = []
        fresh = (threading.Thread(target=lambda: fresh_res.append(step(
            "selftests (fast) in a fresh install", py + [os.path.join(HERE, "fresh_install.py"), "--selftest"],
            quiet=True))) if clone else None)
        if fresh:
            fresh.start()
        ok &= step("selftests (fast)", py + [st_all, "--fast", "--dev", *proj])[0]
        if fresh:
            fresh.join()
            ok &= fresh_res[0][0]
            print(fresh_res[0][2], end="", flush=True)
        if clone:
            # the clone: install.sh --upgrade end to end in a scratch project (INSTALL.md, "Upgrading")
            ok &= step("install.sh --upgrade", py + [os.path.join(HERE, "upgrade.py"), "--selftest"])[0]
        if not any(os.path.exists(os.path.join(os.path.dirname(AUDITS), f)) for f in ("lakefile.lean", "lakefile.toml")):
            print("== tier 0 ran outside an installed project: run it from a project (install.sh) too, as an "
                  "operator does")
    if a.tier == 1:
        # the selftests once per run mode x involvement level of the project's config (TIERS.md): a
        # selftest that read the run's own level stopped a hands-off run (small-paper run, stop S1),
        # and a release-mode change must never alter dev mode (MAINTAINING S3)
        sys.path.insert(0, AUDITS)
        import project
        if project.all_projects():
            for name, env in config_runs():
                ok &= step(f"selftests (fast) under {name}", py + [st_all, "--fast", "--dev", *proj], env)[0]
        else:
            print("== modes and involvement levels: no project config here, so nothing reads one; run tier 1 "
                  "from a project to test the selftests under each mode and level")
        ok &= step("plain mutants", py + [mut, "--kind", "plain", "--jobs", str(a.jobs), *proj])[0]
        if a.since:
            ids = lean_mutants_since(a.since)
            if ids is None:
                ok = False
            elif ids:
                ok &= step(f"lean mutants of files changed since {a.since}", py + [mut, "--kind", "lean", *proj, *ids])[0]
            else:
                print(f"== no Lean-backed mutant mutates a file changed since {a.since}")
        else:
            print("== lean mutants: not run (pass --since REF to run those of the files you changed)")
    if a.tier == 2:
        ok &= step("selftests (all, Lean)", py + [st_all, "--dev", *proj])[0]
        # the scenario replay of the run snapshots (tests/snapshot_replay.py; SKIP without them)
        ok &= step("snapshot replay (every mode x level)", py + [os.path.join(HERE, "snapshot_replay.py"),
                                                                 "--jobs", str(min(a.jobs, 6))])[0]
        okp, outp = step("every mutant", py + [mut, "--jobs", str(a.jobs), *proj])
        ok &= okp
        if a.compare_serial:
            _, outs = step("every mutant, serial (--compare-serial)", py + [mut, "--jobs", "1", *proj])
            res = lambda out: {m.group(2).strip(): m.group(1) for m in
                               re.finditer(r"^(killed|SURVIVED|CRASHED|PATTERN MISSING \(\d+x\)) +(\S+)", out, re.M)}
            p_, s_ = res(outp), res(outs)
            diff = sorted(i for i in set(p_) | set(s_) if p_.get(i) != s_.get(i))
            print(f"== serial vs --jobs {a.jobs}: {len(diff)} id(s) differ" + (f": {' '.join(diff)}" if diff else ""))
            ok &= not diff
    print(f"tier {a.tier}: {'ok' if ok else 'FAILED'} in {time.time() - t0:.0f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run every negative control in the audit apparatus. Exit 0 iff all pass.

Each script's --selftest builds fixtures with a known answer, including cases that MUST go red.
Run this after changing any script, and once on a new machine before trusting a round. The ones
that call Lean (fingerprint, axiom_sweep, signoff --lean) need a built project and take about a minute.

  python3 audits/selftest_all.py [--project NAME] [--fast] [--dev]   (--fast skips the Lean-backed ones)

In release mode (the project's `mode`, else the installation's; project.RELEASE) a failure confined
to a non-blocking job (project.SCRIPT_RELEASE: the fresh-reader gate and prompt, the doc lint) is
printed as DISCLOSED[selftest] and does not fail the run's pre-pin check: record it with
`stops.py disclose --cmd "python3 audits/selftest_all.py --fast"`. Any other failure, or a crash of a
blocking script, fails. `--dev` makes every failure fail (maintainers: tests/tier.py passes it).
"""
import argparse, os, subprocess, sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project  # noqa: E402  (the script registry, project.SCRIPTS)
PURE = [n + ".py" for n in project.scripts(selftest="pure")]
LEAN = [n + (".py --lean" if "pure" in project.SCRIPTS[n][0] else ".py") for n in project.scripts(selftest="lean")]
# the Lean-backed selftests build against a real project; signoff --lean builds its own
NEEDS_PROJECT = {n + ".py" for n in project.scripts(selftest="lean") if project.SCRIPTS[n][0] == "lean"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--dev", action="store_true", help="every failure fails, whatever the run mode")
    a = ap.parse_args()
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
                print(f"selftest_all: {e}")
                return 2
    cfg = None
    if proj is not None:
        try:
            cfg = project.select(proj)[0]
        except project.SelectionError:
            cfg = None
    run_cfg = {"mode": "dev"} if a.dev else (cfg if cfg is not None else {"mode": project.installed_mode()})
    for s in PURE + ([] if a.fast else LEAN):
        s, *extra = s.split()
        cmd = [sys.executable, os.path.join(HERE, s), "--selftest", *extra]
        if s in NEEDS_PROJECT:
            if proj is None:
                print(f"  SKIP  {s:20} needs a project config (none yet: run the intake first)")
                skipped.append(s)
                continue
            cmd += ["--project", proj]
        r = subprocess.run(cmd, cwd=os.path.dirname(HERE), capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        last = next((l for l in reversed(out) if l.strip().lower().startswith("selftest")), out[-1] if out else "")
        ok = r.returncode == 0
        nb = project.selftest_release(s[:-len(".py")], "\n".join(out), r.returncode)
        nb = project.split(run_cfg, nb or [])[1] if nb else []
        if not ok and nb:
            print(f"  disc  {s:20} {last.strip()}")
            disc += nb
            continue
        print(f"  {'ok  ' if ok else 'FAIL'}  {s:20} {last.strip()}")
        if not ok:
            bad.append(s)
            for l in out:
                if "FAIL" in l or "CRASH" in l:
                    print(f"          {l.strip()}")
            print("          Last output lines:")
            for l in out[-12:]:
                print(f"          {l}")
    note = f" ({len(skipped)} skipped until a project exists: {', '.join(skipped)})" if skipped else ""
    for p in disc:
        print(project.disclosed_line(p))
    if disc:
        note += f" ({len(disc)} disclosed, release mode: record them with stops.py disclose)"
    print("ALL SELFTESTS:", ("ok" + note) if not bad else f"FAILED ({', '.join(bad)})")
    return 1 if bad else 0


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

#!/usr/bin/env python3
"""Run every negative control in the audit apparatus. Exit 0 iff all pass.

Each script's --selftest builds fixtures with a known answer, including cases that MUST go red.
Run this after changing any script, and once on a new machine before trusting a round. The ones
that call Lean (fingerprint, axiom_sweep, signoff --lean) need a built project and take about a minute.

  python3 audits/selftest_all.py [--project NAME] [--fast]   (--fast skips the Lean-backed ones)
"""
import argparse, os, subprocess, sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

HERE = os.path.dirname(os.path.abspath(__file__))
PURE = ["project.py", "prompt.py", "scope.py", "audit_coverage.py", "phase0.py", "integrity.py", "signoff.py",
        "tree_state.py", "make_report.py", "check_index.py", "decisions.py", "readers.py", "lanecheck.py", "unused_args.py",
        "codex_spawn.py", "lane_auth.py", "codex_agents.py", "claude_settings.py", "watchdog.py"]
LEAN = ["fingerprint.py", "axiom_sweep.py", "signoff.py --lean"]
NEEDS_PROJECT = {"make_report.py", "check_index.py", "fingerprint.py", "axiom_sweep.py"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    bad, skipped = [], []
    # The scripts in NEEDS_PROJECT test against a real project. Without --project, use the one the
    # checked-out branch selects. A fresh install has no project until the first intake: those
    # tests are then reported as SKIPPED -- never as passed -- and the summary says so.
    proj = a.project
    if proj is None:
        sys.path.insert(0, HERE)
        import project
        if project.all_projects():
            try:
                proj = project.select()[0]["name"]
            except project.SelectionError as e:
                print(f"selftest_all: {e}")
                return 2
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
    print("ALL SELFTESTS:", ("ok" + note) if not bad else f"FAILED ({', '.join(bad)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

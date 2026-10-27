#!/usr/bin/env python3
"""A fresh install's `selftest_all.py --fast`, end to end (tier 1, 2026-10-25: doclint read the installed project's
own README.md as formalize-paper's and failed for every user; the clone's selftests could not see it).

It installs this clone into a scratch Lean project that has the user's own files beside audits/ (a README.md
that is not formalize-paper's, a lakefile, a source file), with HOME stood in so the user's ~/.claude is
untouched, and runs `selftest_all.py --fast --dev` there, as Stage 1 runs it (--dev: every failure fails), with a
tool patch's apply commit in the audit record (as --deliver runs it after the tool-patch route, DOC-FIX review #1). The
scratch directory is under ~/.cache/formalize-paper/ (never /tmp: snapshot_replay's selftest refuses a scratch
default under /tmp, and HOME is the stand-in). It needs the clone (install.sh beside audits/); from an installed
project it reports itself not run.

  python3 audits/tests/fresh_install.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import os, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS = os.path.dirname(HERE)
CLONE = os.path.dirname(AUDITS)
INSTALL = os.path.join(CLONE, "install.sh")
PARENT = os.path.join(os.path.expanduser("~"), ".cache", "formalize-paper")
USER_README = "# My Lean project\n\nSome results about segments. Build with `lake build`.\n"


def run(cmd, env, cwd=None, timeout=None):
    r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def selftest():
    if not os.path.isfile(INSTALL):
        print("  note  install.sh is not beside audits/ (an installed project): not run")
        print("selftest: ok (not run)")
        return 0
    res = []

    def say(name, ok):
        res.append(bool(ok))
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    os.makedirs(PARENT, exist_ok=True)
    t = tempfile.mkdtemp(prefix="fresh-install-", dir=PARENT)
    try:
        home, proj = os.path.join(t, "home"), os.path.join(t, "proj")
        os.makedirs(home)
        os.makedirs(os.path.join(proj, "Proj"))
        env = dict(os.environ, HOME=home, PYTHONDONTWRITEBYTECODE="1")
        # elan's lake shim reads ~/.elan: keep the real toolchain reachable under the stand-in HOME
        env.setdefault("ELAN_HOME", os.path.join(os.path.expanduser("~"), ".elan"))
        for k in ("FORMALIZE_TEST_MODE", "FORMALIZE_TEST_INVOLVEMENT"):
            env.pop(k, None)
        open(os.path.join(proj, "README.md"), "w").write(USER_README)
        open(os.path.join(proj, "lakefile.toml"), "w").write('name = "proj"\n\n[[lean_lib]]\nname = "Proj"\n')
        open(os.path.join(proj, "Proj", "Basic.lean"), "w").write("theorem t : 1 + 1 = 2 := rfl\n")
        # the user's identity for the setup commit only: tree_state's selftest tells authors apart, so the
        # selftests must not run with one author forced on every commit
        open(os.path.join(home, ".gitconfig"), "w").write("[user]\n\tname = t\n\temail = t@t\n")
        for c in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "the user's project"]):
            run(["git", "-C", proj, *c], env)
        rc, out = run(["bash", INSTALL, proj], env)
        say("install.sh installs into a fresh project", rc == 0 and "installed in" in out)
        if rc:
            print("\n".join("        " + l for l in out.splitlines()[-10:]))
        else:
            # DOC-FIX review #1: a run that took the tool-patch route has a `tool-patch TP<k> apply` commit in its
            # audit record; project.py's and make_report.py's fixtures read it through project.AUDITS and failed, so
            # --deliver's `selftest_all.py --fast` refused every such run. The selftests must not see the run's state
            run(["git", "-C", os.path.join(proj, "audits"), "commit", "-q", "--allow-empty", "-m",
                 "tool-patch TP1 apply"], env)
            rc, out = run([sys.executable, "-B", os.path.join(proj, "audits", "selftest_all.py"), "--fast", "--dev"],
                          env, cwd=proj, timeout=1800)
            lines = out.rstrip().splitlines()
            for l in [l for l in lines if l.startswith(("  FAIL", "  disc", "  CRASH")) or l.startswith("ALL")][:40]:
                print("        " + l)
            say("selftest_all.py --fast --dev passes in the fresh install (the user's README.md beside audits/), after "
                "a tool patch was applied (its `tool-patch TP1 apply` commit in the audit record)",
                rc == 0 and lines and lines[-1].startswith("ALL SELFTESTS: ok"))
            say("the user's README.md is untouched", open(os.path.join(proj, "README.md")).read() == USER_README)
    finally:
        shutil.rmtree(t, ignore_errors=True)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)

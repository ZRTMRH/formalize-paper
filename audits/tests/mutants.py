#!/usr/bin/env python3
"""Standing mutation suite for the audit scripts: every mutant must be KILLED by a selftest.

WHY THIS EXISTS.  The scripts' own selftests were written by the same hand as the scripts, and
on 2026-10-11 an independent auditor applied 45 mutants of its own: 41 survived. The author's
earlier "mutation checks" had only tried the cases the author thought of. A green selftest says
nothing about the property it does not exercise, so this file lists, per claimed property, a
mutation that breaks it -- and the suite fails unless the selftests notice every one.

A mutant is (id, file, old text, new text, selftest script, extra args). Exit codes of a selftest:
0 green, 1 a check failed (the mutant is KILLED), 3 a fixture could not run (CRASHED, like a
traceback: it says nothing about the property); 2 with a usage message means the selftest never
ran (wrong arguments in the mutant list) and is CRASHED too. Exit 3 means this only for `--selftest` runs. `old` must occur exactly
once; if a refactor moves it, the suite reports PATTERN MISSING, which is a failure: re-point the
mutant at the new code rather than deleting it.

  python3 audits/tests/mutants.py                 every mutant (the Lean-backed ones take minutes)
  python3 audits/tests/mutants.py --fast          skip mutants whose selftest needs Lean
  python3 audits/tests/mutants.py S1 P3           only these ids (prefix match)

The Lean-backed mutants build against the clone's CHECKED-OUT branch, so a long run blocks branch
switches in that clone (and a switch mid-run changes what they test). Run them when no other work
needs the clone, or from a separate worktree.
"""
import os, re, shutil, subprocess, sys, tempfile
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS = os.path.dirname(HERE)
REPO = os.path.dirname(AUDITS)
LEAN_BACKED = {"fingerprint.py", "axiom_sweep.py"}


def parse_args(argv):
    """--fast, --project NAME, and mutant id prefixes. Anything else starting with -- is an error:
    an unknown flag used to be taken as an id prefix, matched nothing, and the run passed with
    0 mutants (2026-10-18)."""
    fast, proj, only, i = False, None, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--fast":
            fast = True
        elif a == "--project":
            if i + 1 >= len(argv):
                sys.exit("mutants.py: --project needs a NAME")
            proj, i = argv[i + 1], i + 1
        elif a.startswith("-"):
            sys.exit(f"mutants.py: unknown option {a!r} (known: --fast, --project NAME)")
        else:
            only.append(a)
        i += 1
    return fast, proj, only


FAST, PROJECT, ONLY = parse_args(sys.argv[1:]) if __name__ == "__main__" else (False, None, [])
if PROJECT is None:
    # the project the Lean-backed mutants build against: as for every script, the one the
    # checked-out branch selects
    sys.path.insert(0, AUDITS)
    import project as _project
    try:
        PROJECT = _project.select()[0]["name"]
    except _project.SelectionError:
        PROJECT = None
os.environ["MUTANT_PROJECT"] = PROJECT or ""

sys.path.insert(0, HERE)
from mutant_list import MUTANTS  # noqa: E402


def copy_apparatus(dst):
    """A runnable copy of audits/ whose project.py still points at the real clone."""
    for f in os.listdir(AUDITS):
        p = os.path.join(AUDITS, f)
        # .json: data the scripts load at import time (uni_math_extra.json); without it every
        # make_report mutant would fail a glyph check and count as "killed" for the wrong reason
        if f.endswith((".py", ".lean", ".md", ".json")) and os.path.isfile(p):
            shutil.copy(p, dst)
    shutil.copytree(os.path.join(AUDITS, "projects"), os.path.join(dst, "projects"))
    shutil.copytree(os.path.join(AUDITS, "agents"), os.path.join(dst, "agents"))
    src = open(os.path.join(dst, "project.py"), encoding="utf-8").read()
    src = src.replace("AUDITS = os.path.dirname(os.path.abspath(__file__))",
                      f"AUDITS = {dst!r}", 1).replace(
                      "REPO = os.path.dirname(AUDITS)", f"REPO = {REPO!r}", 1)
    open(os.path.join(dst, "project.py"), "w", encoding="utf-8").write(src)


def main():
    fast, only = FAST, ONLY
    survived, missing, killed, selected = [], [], 0, 0
    baseline = {}
    if only:
        unknown = [o for o in only if not any(m[0].startswith(o) for m in MUTANTS)]
        if unknown:
            print(f"mutants.py: no mutant id starts with {', '.join(unknown)}")
            return 2
    for mid, f, old, new, st, extra in MUTANTS:
        if only and not any(mid.startswith(o) for o in only):
            continue
        if fast and (st in LEAN_BACKED or f.endswith(".lean") or "--lean" in extra):
            continue
        if "--project" in extra and not PROJECT:
            print(f"mutants.py: mutant {mid} needs a project; pass --project NAME "
                  f"(none is selected by the checked-out branch)")
            return 2
        selected += 1
        # A mutant is "killed" when its selftest fails -- which proves nothing if the selftest
        # already fails on the unmutated code (a release run once counted every prompt.py mutant
        # as killed while prompt.py's own selftest was broken). Run each selftest once unmutated.
        key = (st, tuple(extra))
        if key not in baseline:
            bd = tempfile.mkdtemp(prefix="mut-base-")
            try:
                copy_apparatus(bd)
                rb = subprocess.run([sys.executable, "-B", os.path.join(bd, st), "--selftest", *extra],
                                    cwd=REPO, capture_output=True, text=True,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                baseline[key] = rb.returncode == 0
            finally:
                shutil.rmtree(bd, ignore_errors=True)
            if not baseline[key]:
                print(f"BASELINE FAILS  {st} {' '.join(extra)}: its selftest fails on the unmutated "
                      f"code, so no mutant of it can be judged; fix that first")
        if not baseline[key]:
            survived.append(mid)
            continue
        d = tempfile.mkdtemp(prefix="mut-")
        try:
            copy_apparatus(d)
            p = os.path.join(d, f)
            src = open(p, encoding="utf-8").read()
            n = src.count(old)
            if n != 1:
                print(f"PATTERN MISSING ({n}x)  {mid}")
                missing.append(mid)
                continue
            open(p, "w", encoding="utf-8").write(src.replace(old, new))
            r = subprocess.run([sys.executable, "-B", os.path.join(d, st), "--selftest", *extra],
                               cwd=REPO, capture_output=True, text=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            out = r.stdout + r.stderr
            if r.returncode != 0 and ("Traceback (most recent call last)" in out
                                      or "SyntaxError" in out or "IndentationError" in out
                                      or "TabError" in out or r.returncode == 3
                                      or (r.returncode == 2 and "usage:" in out)
                                      or not any(l.strip().lower().startswith("selftest")
                                                 for l in out.splitlines())):
                # no "selftest: ..." summary line: the selftest stopped before finishing (an
                # uncaught SystemExit in a CLI check did exactly this, and counted as a kill)
                # exit 2 + "usage:": argparse refused the command line -- the selftest never ran
                # exit 3: a Lean-backed selftest's fixture did not run (e.g. project not built)
                # A crash is not a kill: it shows the mutant broke the code, not that a test
                # noticed the property was gone. Rewrite the mutant so it runs.
                print(f"CRASHED   {mid}   [{out.strip().splitlines()[-1][:90]}]")
                survived.append(mid)
            elif r.returncode != 0:
                killed += 1
                # a selftest's own check line is "  FAIL  <name>"; prefer it over fixture output
                # such as "FAIL: 1 problem(s)" that a script under test prints along the way
                lines = out.splitlines()
                first = next((l.strip() for l in lines if re.match(r"\s*FAIL\s{2}", l)),
                             next((l.strip() for l in lines if l.strip().startswith("FAIL")), ""))
                print(f"killed    {mid}   [{first[:90]}]")
            else:
                print(f"SURVIVED  {mid}")
                survived.append(mid)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print(f"\nmutants: {killed} killed, {len(survived)} SURVIVED or CRASHED, {len(missing)} pattern missing")
    if selected == 0:
        print("mutants.py: no mutant was run -- a run that tests nothing is not a pass")
        return 1
    return 1 if survived or missing else 0


if __name__ == "__main__":
    sys.exit(main())

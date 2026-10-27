#!/usr/bin/env python3
"""Standing mutation suite for the audit scripts: every mutant must be KILLED by a selftest.

WHY THIS EXISTS.  The scripts' own selftests were written by the same hand as the scripts, and
on 2026-10-11 an independent auditor applied 45 mutants of its own: 41 survived. The author's
earlier "mutation checks" had only tried the cases the author thought of. A green selftest says
nothing about the property it does not exercise, so this file lists, per claimed property, a
mutation that breaks it -- and the suite fails unless the selftests notice every one.

A mutant is (id, file, old text, new text, selftest script, extra args, kind). Kind is "plain" (a
pure selftest; the "pdf" kind went with the PDF compilation, PDF-AGENTS), "lean"
(its selftest builds a Lean fixture) or "codex" (a Codex-only tool in the clone's codex/, outside
the installed apparatus: file and selftest are paths from the clone root, and these run only from
a clone, `python3 -B audits/tests/mutants.py --kind codex`; elsewhere they are reported as not run). Exit codes of a selftest:
0 green, 1 a check failed (the mutant is KILLED), 3 a fixture could not run (CRASHED, like a
traceback: it says nothing about the property); 2 with a usage message means the selftest never
ran (wrong arguments in the mutant list) and is CRASHED too. Exit 3 means this only for `--selftest` runs. `old` must occur exactly
once; if a refactor moves it, the suite reports PATTERN MISSING, which is a failure: re-point the
mutant at the new code rather than deleting it.

  python3 audits/tests/mutants.py                 every mutant (the Lean-backed ones take minutes)
  python3 audits/tests/mutants.py --fast          skip the lean kind
  python3 audits/tests/mutants.py --kind plain    only these kinds (comma-separated)
  python3 audits/tests/mutants.py --jobs 8        run the plain mutants 8 at a time (each is an
                                                  isolated temp copy); lean ones stay serial
  python3 audits/tests/mutants.py S1 P3           only these ids (prefix match)
The test tiers that combine these are `audits/tests/tier.py 0|1|2` (audits/tests/TIERS.md).

The Lean-backed mutants build against the clone's CHECKED-OUT branch, so a long run blocks branch
switches in that clone (and a switch mid-run changes what they test). Run them when no other work
needs the clone, or from a separate worktree.
"""
import itertools, os, re, shutil, subprocess, sys, tempfile
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS = os.path.dirname(HERE)
REPO = os.path.dirname(AUDITS)
sys.path.insert(0, AUDITS)
import project as _project  # noqa: E402  (the script registry)
LEAN_BACKED = {n + ".py" for n, (st, _) in _project.SCRIPTS.items() if st == "lean"}
KINDS = ("plain", "lean", "codex")
CODEX = os.path.join(REPO, "codex")     # present in a clone, not in an installed project


def parse_args(argv):
    """--fast, --kind K[,K], --jobs N, --project NAME, and mutant id prefixes. Anything
    else starting with -- is an error: an unknown flag used to be taken as an id prefix, matched
    nothing, and the run passed with 0 mutants (2026-10-18)."""
    o = dict(kinds=set(KINDS), jobs=1, project=None, only=[])
    i = 0

    def value(flag):
        if i + 1 >= len(argv):
            sys.exit(f"mutants.py: {flag} needs a value")
        return argv[i + 1]
    while i < len(argv):
        a = argv[i]
        if a == "--fast":
            o["kinds"] -= {"lean"}
        elif a == "--kind":
            ks = set(value(a).split(","))
            if not ks <= set(KINDS):
                sys.exit(f"mutants.py: --kind takes {', '.join(KINDS)} (comma-separated), not {value(a)!r}")
            o["kinds"] &= ks
            i += 1
        elif a == "--jobs":
            try:
                o["jobs"] = max(1, int(value(a)))
            except ValueError:
                sys.exit(f"mutants.py: --jobs takes a number, not {value(a)!r}")
            i += 1
        elif a == "--project":
            o["project"] = value(a)
            i += 1
        elif a.startswith("-"):
            sys.exit(f"mutants.py: unknown option {a!r} (known: --fast, --kind K, --jobs N, --project NAME)")
        else:
            o["only"].append(a)
        i += 1
    return o


OPTS = parse_args(sys.argv[1:] if __name__ == "__main__" else [])
PROJECT = OPTS["project"]
if PROJECT is None:
    # the project the Lean-backed mutants build against: as for every script, the one the
    # checked-out branch selects
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
        # .json: data a script may load at import time
        if f.endswith((".py", ".lean", ".md", ".json")) and os.path.isfile(p):
            shutil.copy(p, dst)
    if os.path.isdir(os.path.join(AUDITS, "projects")):     # a clone has none
        shutil.copytree(os.path.join(AUDITS, "projects"), os.path.join(dst, "projects"))
    shutil.copytree(os.path.join(AUDITS, "agents"), os.path.join(dst, "agents"))
    shutil.copytree(os.path.join(AUDITS, "run"), os.path.join(dst, "run"))     # RUN.md's stage files
    shutil.copytree(os.path.join(AUDITS, "tests"), os.path.join(dst, "tests"),
                    ignore=shutil.ignore_patterns("__pycache__"))     # tests/replay.py is a selftest
    src = open(os.path.join(dst, "project.py"), encoding="utf-8").read()
    src = src.replace("AUDITS = os.path.dirname(os.path.abspath(__file__))",
                      f"AUDITS = {dst!r}", 1).replace(
                      "REPO = os.path.dirname(AUDITS)", f"REPO = {REPO!r}", 1)
    open(os.path.join(dst, "project.py"), "w", encoding="utf-8").write(src)


def prepare(st):
    """A temp copy to mutate and run selftest `st` in: (the copy, the directory that the mutant's
    file and selftest paths are relative to; the same here). A codex/ selftest gets the clone's
    layout: <tmp>/audits (the apparatus) beside <tmp>/codex."""
    d = tempfile.mkdtemp(prefix="mut-")
    if not st.startswith("codex/"):
        copy_apparatus(d)
        return d
    os.makedirs(os.path.join(d, "audits")); os.makedirs(os.path.join(d, "codex"))
    copy_apparatus(os.path.join(d, "audits"))
    for f in os.listdir(CODEX):
        if f.endswith((".py", ".json")) and os.path.isfile(os.path.join(CODEX, f)):
            shutil.copy(os.path.join(CODEX, f), os.path.join(d, "codex"))
    return d


def kind_problem(m):
    """None, or why mutant m's kind field is wrong. The lean kind is checked against the selftest
    it runs (it used to be inferred from that name alone)."""
    mid, f, old, new, st, extra, kind = m
    if kind not in KINDS:
        return f"{mid}: kind {kind!r} is not one of {', '.join(KINDS)}"
    lean = st in LEAN_BACKED or f.endswith(".lean") or "--lean" in extra
    if lean != (kind == "lean"):
        return f"{mid}: kind {kind!r}, but its selftest {'is' if lean else 'is not'} Lean-backed"
    if (kind == "codex") != (f.startswith("codex/") and st.startswith("codex/")):
        return f"{mid}: kind {kind!r}, but its file and selftest {'are not both' if kind == 'codex' else 'are'} under codex/"
    return None


def run_selftest(d, st, extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", os.path.join(d, st), "--selftest", *extra],
                          cwd=REPO, capture_output=True, text=True, env=env)


def baseline(key):
    """Does the selftest pass on the unmutated code? A mutant is "killed" when its selftest fails --
    which proves nothing if the selftest already fails (a release run once counted every prompt.py
    mutant as killed while prompt.py's own selftest was broken)."""
    st, extra = key
    bd = prepare(st)
    try:
        return run_selftest(bd, st, list(extra)).returncode == 0
    finally:
        shutil.rmtree(bd, ignore_errors=True)


def run_mutant(m):
    """(status, line): status is killed / survived / missing."""
    mid, f, old, new, st, extra, kind = m
    d = prepare(st)
    try:
        p = os.path.join(d, f)
        src = open(p, encoding="utf-8").read()
        n = src.count(old)
        if n != 1:
            return "missing", f"PATTERN MISSING ({n}x)  {mid}"
        open(p, "w", encoding="utf-8").write(src.replace(old, new))
        r = run_selftest(d, st, extra)
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
            return "survived", f"CRASHED   {mid}   [{out.strip().splitlines()[-1][:90]}]"
        if r.returncode != 0:
            # every selftest prints its checks as "  ok    <name>" / "  FAIL  <name>" and ends with
            # "selftest: ok|FAILED" (one format since chunk 3; claude_settings and the watchdog used one
            # space): prefer that line over fixture output such as "FAIL: 1 problem(s)" a script prints
            lines = out.splitlines()
            first = next((l.strip() for l in lines if re.match(r"\s*FAIL\s{2}", l)),
                         next((l.strip() for l in lines if l.strip().startswith("FAIL")), ""))
            return "killed", f"killed    {mid}   [{first[:90]}]"
        return "survived", f"SURVIVED  {mid}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    o = OPTS
    only = o["only"]
    if only:
        unknown = [p for p in only if not any(m[0].startswith(p) for m in MUTANTS)]
        if unknown:
            print(f"mutants.py: no mutant id starts with {', '.join(unknown)}")
            return 2
    bad = [k for k in map(kind_problem, MUTANTS) if k]
    if bad:
        print("mutants.py: wrong kind field:\n  " + "\n  ".join(bad))
        return 2
    sel = [m for m in MUTANTS if m[6] in o["kinds"]
           and (not only or any(m[0].startswith(p) for p in only))]
    if not os.path.isdir(CODEX) and any(m[6] == "codex" for m in sel):
        print(f"mutants.py: {sum(m[6] == 'codex' for m in sel)} codex mutants not run: no codex/ beside "
              f"audits/ (run them from the clone: --kind codex)")
        sel = [m for m in sel if m[6] != "codex"]
    for m in sel:
        if "--project" in m[5] and not PROJECT:
            print(f"mutants.py: mutant {m[0]} needs a project; pass --project NAME "
                  f"(none is selected by the checked-out branch)")
            return 2
    key = lambda m: (m[4], tuple(m[5]))
    # plain mutants are isolated temp copies and run --jobs at a time; the Lean-backed
    # ones stay serial (each runs `lake env lean` in the one project: they share its build, and a Lean
    # process with the project imported is heavy)
    par = [m for m in sel if m[6] != "lean"]
    ser = [m for m in sel if m[6] == "lean"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=o["jobs"]) as ex:
        keys = list(dict.fromkeys(key(m) for m in par))
        base = dict(zip(keys, ex.map(baseline, keys)))
        for k in dict.fromkeys(key(m) for m in ser):
            base[k] = baseline(k)
        for k, ok in base.items():
            if not ok:
                print(f"BASELINE FAILS  {k[0]} {' '.join(k[1])}: its "
                      f"selftest fails on the unmutated code, so no mutant of it can be judged; fix that first")
        run = lambda m: (("survived", None) if not base[key(m)] else run_mutant(m))
        survived, missing, killed = [], [], 0
        # ex.map yields in list order, so the output is the same for any --jobs
        for m, (status, line) in itertools.chain(zip(par, ex.map(run, par)), ((m, run(m)) for m in ser)):
            if line:
                print(line, flush=True)
            if status == "killed":
                killed += 1
            elif status == "missing":
                missing.append(m[0])
            else:
                survived.append(m[0])
    print(f"\nmutants: {killed} killed, {len(survived)} SURVIVED or CRASHED, {len(missing)} pattern missing")
    if not sel:
        print("mutants.py: no mutant was run -- a run that tests nothing is not a pass")
        return 1
    return 1 if survived or missing else 0


if __name__ == "__main__":
    sys.exit(main())

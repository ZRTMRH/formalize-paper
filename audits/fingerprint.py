#!/usr/bin/env python3
"""Content fingerprints of a project's declarations: what each one MEANS, hashed.

WHY THIS EXISTS.  Two gaps, one cause: verdicts and approvals were keyed by declaration NAME.
  * A `Pass` on a theorem survived a later change to a definition its statement is written in
    terms of. The theorem's name and text were unchanged; what it says was not.
  * Checkpoint B (RUN.md) freezes the statements the human approved, and the freeze was a rule
    in prose: nothing noticed if an approved statement, or a definition under it, changed.
A fingerprint keyed to content closes both, mechanically.

WHAT IS HASHED (fingerprint_tail.lean computes the per-declaration part, in Lean):
  own(n)  = theorem: its statement (type) -- never its proof
            def/opaque: type and value; inductive: type and constructor types; other: type
            (metadata erased; binder names are not part of Lean's expression hash)
  deps(n) = the project-local constants occurring in own(n). Mathlib is trusted, not followed.
  fp(n)   = sha256 of own(n) and of own(m) for every m in the transitive closure of deps(n).
So changing a definition changes the fingerprint of every statement written in terms of it,
directly or through other definitions; changing a proof changes nothing.

  fingerprint.py                       print {name: fp} for the checked-out project
  fingerprint.py --snapshot DIR        write DIR/FINGERPRINTS.json (scope.py does this per round)
  fingerprint.py --approve             freeze: write <ROUNDS-DIR>/APPROVED_FINGERPRINTS.json
  fingerprint.py --check               exit 1 if anything approved has changed or vanished;
                                       exit 4 if nothing has been approved yet; 2 on any error
  fingerprint.py --selftest            controls that must go red (and some that must stay green)

Requires a built project (Phase 0 builds first): the fingerprints are read from the compiled
environment, through `import <sweep.module>` or the append mode the axiom sweep uses.
"""
import argparse, hashlib, json, os, subprocess, sys, tempfile, datetime
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

TAIL = os.path.join(project.AUDITS, "fingerprint_tail.lean")
APPROVED = "APPROVED_FINGERPRINTS.json"
# Auto-generated companions (equation lemmas, recursors, noConfusion, congr lemmas, matchers) are
# fingerprinted -- they are part of a definition's closure -- but never listed as approvable items.
# WHICH declarations are auto-generated is decided in Lean (no source position = nobody wrote it),
# not guessed from the name: a name-pattern rule excluded a real theorem called `eq_zero_of_G`.
_AUTO = set()


def is_autogen(name):
    """True iff the last fingerprint run reported `name` as auto-generated."""
    return name in _AUTO


def module_root(cfg):
    sw = cfg.get("sweep", {})
    return sw.get("module", "").split(".")[0] if sw.get("mode") == "import" else ""


def lean_source(cfg, body=None):
    tail = (open(TAIL, encoding="utf-8").read().replace("__NAMESPACE__", cfg["namespace"])
            .replace("`__MODULE_ROOT__", "`" + module_root(cfg) if module_root(cfg) else "Name.anonymous"))
    if body is not None:
        return body + "\n" + tail
    sw = cfg["sweep"]
    if sw["mode"] == "append":
        return open(os.path.join(project.REPO, sw["file"]), encoding="utf-8").read() + "\n" + tail
    if sw["mode"] == "import":
        return f"import {sw['module']}\n" + tail
    raise SystemExit(f"FAIL: unknown sweep.mode {sw['mode']!r}")


def run_lean(src):
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        r = subprocess.run(["lake", "env", "lean", path], cwd=project.REPO,
                           capture_output=True, text=True)
    finally:
        os.unlink(path)
    return r.returncode, r.stdout + r.stderr


def parse(out):
    """{key: (kind, own, [deps])}, or raise if the Lean side did not run to completion or two
    declarations produced the same key. Records which keys are auto-generated in _AUTO."""
    table, count, auto, dup = {}, None, set(), []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == "FP" and len(parts) == 6:
            if parts[1] in table:
                dup.append(parts[1])
            table[parts[1]] = (parts[2], parts[4], [d for d in parts[5].split(",") if d])
            if parts[3] == "auto":
                auto.add(parts[1])
        elif parts[0] == "FPCOUNT":
            count = int(parts[1])
    if dup:
        raise RuntimeError(f"two declarations share a fingerprint key: {sorted(set(dup))[:5]}")
    if count is None or count != len(table):
        raise RuntimeError("fingerprint run did not complete (no or mismatched FPCOUNT):\n" + out[-3000:])
    _AUTO.clear(); _AUTO.update(auto)
    return table


def closure_fps(table):
    """{name: fp} -- own hash plus own hashes of the transitive project-local closure."""
    fps = {}
    for n in table:
        seen, stack = set(), [n]
        while stack:
            m = stack.pop()
            if m in seen or m not in table:
                continue
            seen.add(m)
            stack.extend(table[m][2])
        h = hashlib.sha256()
        for m in sorted(seen):
            h.update(f"{m}\t{table[m][0]}\t{table[m][1]}\n".encode())
        fps[n] = h.hexdigest()[:16]
    return fps


def compute(cfg, body=None):
    rc, out = run_lean(lean_source(cfg, body))
    if rc != 0:
        raise RuntimeError(f"lake env lean exited {rc}:\n" + out[-3000:])
    return closure_fps(parse(out))


def head(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--short=11", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def check(approved, current):
    """[(name, problem)] for every approved item that changed or vanished."""
    bad = []
    for n, fp in sorted(approved.items()):
        cur = current.get(n)
        if cur is None:
            bad.append((n, "vanished (renamed or deleted)"))
        elif cur != fp:
            bad.append((n, "changed: its statement, or a definition it is stated in terms of"))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--snapshot", metavar="DIR")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    if a.selftest:
        return selftest(cfg)
    try:
        fps = compute(cfg)
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    rounds_dir = os.path.join(project.REPO, cfg["rounds_dir"])
    items = {n: fp for n, fp in fps.items() if not is_autogen(n)}
    print(f"# project {cfg['name']} ({why}): {len(fps)} declarations fingerprinted, "
          f"{len(items)} approvable", file=sys.stderr)

    if a.snapshot:
        os.makedirs(a.snapshot, exist_ok=True)
        p = os.path.join(a.snapshot, "FINGERPRINTS.json")
        json.dump({"commit": head(project.REPO), "fingerprints": fps}, open(p, "w"), indent=0)
        print(f"wrote {os.path.relpath(p, project.REPO)}")
        return 0
    if a.approve:
        # One path to approval, and it checks the sheet: signoff.py approve.
        print("FAIL: approve through `signoff.py approve --round R --by human|agent --how ...`, "
              "which ties the approval to the sheet that was shown", file=sys.stderr)
        return 2
    if a.check:
        p = os.path.join(rounds_dir, APPROVED)
        if not os.path.exists(p):
            print(f"NOT APPLICABLE: no {APPROVED}: nothing has been approved yet, so nothing "
                  f"can be checked. (Expected before Checkpoint B; a failure after it.)",
                  file=sys.stderr)
            return 4
        appr = json.load(open(p))
        bad = check(appr["fingerprints"], fps)
        for n, why_ in bad:
            print(f"DRIFT  {n}: {why_}")
        print(f"freeze check: {len(appr['fingerprints'])} approved at {appr['commit']}, "
              f"{len(bad)} drifted")
        return 1 if bad else 0
    json.dump(fps, sys.stdout, indent=0)
    print()
    return 0


# ---------------------------------------------------------------------------------------------
BASE = """import Mathlib.Order.Basic
def helperK : ℕ := 3
namespace FpT
/-- doc -/
def thing (n : ℕ) : ℕ := n + 1
def other : ℕ := 3
def wrap (n : ℕ) : ℕ := thing n
theorem st (n : ℕ) : thing n > n := by simp [thing]
theorem via_wrap (n : ℕ) : wrap n > n := by simp [wrap, thing]
theorem pf (n : ℕ) : n < n + 1 := by have := thing n; omega
theorem un : other = 3 := rfl
private def hidden (n : ℕ) : ℕ := 2 * n
theorem uses_hidden (n : ℕ) : hidden n = n + n := by unfold hidden; omega
theorem eq_zero_of_x (x : ℕ) (h : x = 0) : x = 0 := h
theorem uses_helper : helperK ≤ 10 := by decide
def U.{u} (α : Sort u) : Sort u := α
inductive Col | red | blue
theorem md (n : ℕ) : thing n > n := by simp [thing]
end FpT
"""

# (label, transformation of BASE, {name: must_change(True)/must_not_change(False)})
VARIANTS = [
    ("identical source twice (determinism)", lambda s: s,
     {"FpT.thing": False, "FpT.st": False, "FpT.pf": False}),
    ("bound variable renamed in a statement", lambda s: s.replace(
        "theorem st (n : ℕ) : thing n > n", "theorem st (m : ℕ) : thing m > m"),
     {"FpT.st": False}),
    ("universe parameter renamed", lambda s: s.replace(
        "def U.{u} (α : Sort u) : Sort u := α", "def U.{w} (α : Sort w) : Sort w := α"),
     {"FpT.U": False}),
    ("mdata in a statement (no_index) is not meaning", lambda s: s.replace(
        "theorem md (n : ℕ) : thing n > n", "theorem md (n : ℕ) : no_index (thing n) > n"),
     {"FpT.md": False}),
    ("docstring edited", lambda s: s.replace("/-- doc -/", "/-- a different doc -/"),
     {"FpT.thing": False}),
    ("only a proof changed", lambda s: s.replace(
        "by have := thing n; omega", "by omega"), {"FpT.pf": False, "FpT.st": False}),
    ("definition body changed", lambda s: s.replace("n + 1\n", "n + 2\n", 1),
     {"FpT.thing": True, "FpT.st": True, "FpT.via_wrap": True, "FpT.wrap": True,
      "FpT.pf": False, "FpT.un": False, "FpT.other": False}),
    ("statement strictness changed (> to ≥)", lambda s: s.replace(
        "thing n > n := by simp [thing]\ntheorem via", "thing n ≥ n := by simp [thing]\ntheorem via"),
     {"FpT.st": True, "FpT.thing": False, "FpT.via_wrap": False}),
    ("private definition changed", lambda s: s.replace(
        "private def hidden (n : ℕ) : ℕ := 2 * n", "private def hidden (n : ℕ) : ℕ := n + n").replace(
        "by unfold hidden; omega", "by unfold hidden; rfl"),
     {"FpT.hidden": True, "FpT.uses_hidden": True, "FpT.st": False}),
    ("root-level helper OUTSIDE the namespace changed", lambda s: s.replace(
        "def helperK : ℕ := 3", "def helperK : ℕ := 5"),
     {"FpT.uses_helper": True, "FpT.st": False}),
    ("constructor added to an inductive", lambda s: s.replace(
        "inductive Col | red | blue", "inductive Col | red | blue | green"),
     {"FpT.Col": True, "FpT.st": False}),
    ("unrelated definition changed", lambda s: s.replace(
        "def other : ℕ := 3", "def other : ℕ := 4").replace("theorem un : other = 3 := rfl",
                                                         "theorem un : other = 4 := rfl"),
     {"FpT.st": False, "FpT.thing": False, "FpT.other": True, "FpT.un": True}),
]


def _key(table, short):
    """The table key for a declaration, private or not."""
    return next((k for k in table if k == short or k.startswith(short + " (private in ")), None)


def selftest(cfg):
    cfg = dict(cfg, namespace="FpT", sweep={"mode": "append", "file": "-"})
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    try:
        base = compute(cfg, BASE)
    except RuntimeError as e:
        print(f"FAIL: base fixture did not run: {e}"); return 1
    base_auto = set(_AUTO)
    K = lambda t, n: t.get(_key(t, n))
    say("base fixture fingerprints every declaration",
        all(_key(base, n) for n in ("FpT.thing", "FpT.other", "FpT.wrap", "FpT.st", "FpT.via_wrap",
                                     "FpT.pf", "FpT.un", "FpT.hidden", "FpT.uses_hidden",
                                     "FpT.eq_zero_of_x", "FpT.uses_helper", "FpT.U", "FpT.Col")))
    say("a private declaration's key names it as private",
        _key(base, "FpT.hidden") and "(private in" in _key(base, "FpT.hidden"))
    say("a root-level declaration of the project is fingerprinted", "helperK" in base)
    say("equation lemmas are auto-generated (decided by Lean)",
        any(k.startswith("FpT.thing.eq") for k in base_auto))
    say("a user theorem NAMED eq_... is not auto-generated", "FpT.eq_zero_of_x" not in base_auto)
    say("recursor, casesOn, noConfusion, constructors, sizeOf_spec are auto-generated",
        {"FpT.Col.rec", "FpT.Col.casesOn", "FpT.Col.noConfusion", "FpT.Col.red",
         "FpT.Col.red.sizeOf_spec"} <= base_auto)
    say("user declarations are not auto-generated", "FpT.st" not in base_auto and "FpT.Col" not in base_auto)
    say("the helpers of the fingerprint program itself are excluded",
        not any(k.startswith("auditFp") for k in base))
    for label, f, expect in VARIANTS:
        try:
            var = compute(cfg, f(BASE))
        except RuntimeError as e:
            say(f"{label}: variant compiles", False); print(e); continue
        for n, must_change in expect.items():
            changed = K(base, n) != K(var, n) or K(base, n) is None
            say(f"{label}: {n} {'changes' if must_change else 'unchanged'}",
                changed == must_change)
    # parse(): completeness and uniqueness
    try:
        parse("FP\ta\ttheorem\tuser\t1\t\nFPCOUNT\t2\n"); r1 = False
    except RuntimeError:
        r1 = True
    say("parse: a truncated run (FPCOUNT mismatch) is an error", r1)
    try:
        parse("FP\ta\ttheorem\tuser\t1\t\nFP\ta\tdef\tuser\t2\t\nFPCOUNT\t2\n"); r2 = False
    except RuntimeError as e:
        r2 = "share a fingerprint key" in str(e)   # the specific guard, not the count backstop
    say("parse: two declarations with one key is an error", r2)
    # the freeze check itself
    appr = {n: fp for n, fp in base.items() if n not in base_auto}
    say("check: identical state reports no drift", check(appr, base) == [])
    say("check: a vanished item is reported AS vanished",
        any(n == "FpT.st" and "vanished" in w
            for n, w in check(appr, {k: v for k, v in base.items() if k != "FpT.st"})))
    mutated = dict(base, **{"FpT.wrap": "0" * 16})
    say("check: a changed item is reported", [n for n, _ in check(appr, mutated)] == ["FpT.wrap"])
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

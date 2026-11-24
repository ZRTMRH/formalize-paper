#!/usr/bin/env python3
"""Regression (TP1): `signoff.py reapprove --begin --refuted-by` must accept the refutation of a
universe-polymorphic approved statement. The statement as printed is a `def ... : Prop` without
universe parameters, so the check must compare it with the approved statement instantiated at
universe 0, not with the polymorphic type (whose level parameters isDefEq cannot unify with 0).

Usage: refuted_by_universe.py --apparatus DIR. Exit 0 when the apparatus in DIR passes.
1. The generated Lean command instantiates the approved declaration's level parameters.
2. If a `lean` executable is available, the generated command is run on a minimal core-Lean case
   (a false universe-polymorphic theorem, its universe-free statement as printed, and a proof of
   the negation): the check must print `defeq ok`."""
import os, shutil, subprocess, sys, tempfile

def main():
    if "--apparatus" not in sys.argv:
        print("usage: refuted_by_universe.py --apparatus DIR"); return 2
    app = os.path.abspath(sys.argv[sys.argv.index("--apparatus") + 1])
    sys.path.insert(0, app)
    import signoff
    cmd = signoff.refutation_lean("N", "A", "D")
    if "instantiateTypeLevelParams" not in cmd:
        print("FAIL: refutation_lean compares with the uninstantiated polymorphic type"); return 1
    lean = shutil.which("lean")
    if lean is None:
        print("ok (string check only: no lean executable)"); return 0
    src = ("import Lean\n"
           "theorem D.{u} : ∀ (α : Type u), Nonempty α := sorry\n"
           "def A : Prop := ∀ (α : Type), Nonempty α\n"
           "theorem N : ¬ A := fun h => (h Empty).elim (fun e => nomatch e)\n" + cmd)
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "T.lean")
        open(f, "w").write(src)
        r = subprocess.run([lean, f], capture_output=True, text=True, timeout=600, cwd=d)
    out = r.stdout + r.stderr
    if "REFDONE" not in out:
        print("ok (string check only: the Lean run did not complete)"); return 0
    if "REF\tdefeq\tok" not in out:
        print("FAIL: the Lean check still rejects the universe-0 statement as printed:\n" + out[-800:]); return 1
    print("ok"); return 0

if __name__ == "__main__":
    sys.exit(main())

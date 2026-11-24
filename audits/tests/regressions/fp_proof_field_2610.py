#!/usr/bin/env python3
"""Regression (DESIGN-FP; live e2e 2610.13707, stop S1): filling the `sorry` of a proof field of an approved
instance drifted every approved declaration stated over it (14 of 33). Lean abstracts an instance's proof fields
into aux theorems `<decl>._proof_<k>` and reuses an identical one from an earlier declaration, so the instance's
value named different constants after the fill, and other edits above it moved them again.

The fixture is Lean written for this test (no text of the paper or of the run): a class with data and a proof field,
an instance whose proof field is `by have …; sorry`, a declaration above it with the same proof (aux-proof reuse),
and statements over the instance. Checked, with the project's real fingerprint program:
  1. the fill (the proof field proved, citing a new project lemma; an edit above the instance) changes no
     fingerprint, and the new lemma is no dependency of the instance;
  2. control: with the proof erasure switched off (the tail's marker line replaced by `.continue`, mutant FP-M1)
     the same fill changes the instance's fingerprint and every statement's over it (the test is sensitive);
  3. a change of the instance's data (the bracket) still changes them.

  python3 audits/tests/regressions/fp_proof_field_2610.py --apparatus audits [--project NAME]
needs a project with Mathlib built (as `fingerprint.py --selftest`); one `lean` process at a time.
"""
import argparse, os, sys, tempfile
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser()
ap.add_argument("--apparatus", required=True)
ap.add_argument("--project")
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.apparatus))
import project, fingerprint  # noqa: E402

BEFORE = """import Mathlib.Order.Basic
namespace FpR
class Br (α : Type) where
  br : α → α → α
  anti : ∀ a b : α, br a b = br b a
  jac : ∀ a b c : α, br a (br b c) = br (br a b) c
abbrev V : Type := ℕ
def early : Br ℕ where
  br a b := a + b
  anti a b := Nat.add_comm a b
  jac a b c := by have h := a; sorry
instance instBrV : Br V where
  br a b := a + b
  anti a b := Nat.add_comm a b
  jac a b c := by have h := a; sorry
def tau (x : V) : V := Br.br x x
theorem tau_spec (x : V) : tau x = Br.br x x := rfl
theorem main : ∀ x : V, tau x = tau x := fun _ => rfl
end FpR
"""
FILL = (BEFORE.replace("abbrev V : Type := ℕ", "abbrev V : Type := ℕ\ntheorem jac' (a b c : ℕ) : a + (b + c) = a + b + c := "
                       "(Nat.add_assoc a b c).symm")
        .replace("instance instBrV : Br V where\n  br a b := a + b\n  anti a b := Nat.add_comm a b\n"
                 "  jac a b c := by have h := a; sorry",
                 "instance instBrV : Br V where\n  br a b := a + b\n  anti a b := Nat.add_comm a b\n"
                 "  jac a b c := jac' a b c"))
DATA = BEFORE.replace("br a b := a + b", "br a b := a + b + 0")
NAMES = ("FpR.instBrV", "FpR.tau", "FpR.tau_spec", "FpR.main")
MARK = '      return .done (.lit (.strVal "auditFpProof"))'

cfg, _ = project.select(a.project)
cfg = dict(cfg, namespace="FpR", sweep={"mode": "append", "file": "-"})
bad = []


def run(src, tail=None):
    keep = fingerprint.TAIL
    try:
        if tail:
            fingerprint.TAIL = tail
        return fingerprint.compute(cfg, src), dict(fingerprint.compute.table)
    finally:
        fingerprint.TAIL = keep


def say(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        bad.append(name)


b, _ = run(BEFORE)
f, ft = run(FILL)
d, _ = run(DATA)
say("1. the proof field filled (citing a new lemma, a lemma added above): no fingerprint changes",
    all(b[n] == f[n] for n in NAMES))
say("1. the lemma cited in the proof field is no dependency of the instance", "FpR.jac'" not in ft["FpR.instBrV"][2])
say("3. the instance's data changed: the instance and every statement over it change", all(b[n] != d[n] for n in NAMES))
src = open(fingerprint.TAIL, encoding="utf-8").read()
say("2. control: the tail has the erasure marker line exactly once", src.count(MARK) == 1)
with tempfile.TemporaryDirectory() as td:
    off = os.path.join(td, "tail_off.lean")
    open(off, "w", encoding="utf-8").write(src.replace(MARK, "      return .continue"))
    b0, _ = run(BEFORE, off)
    f0, _ = run(FILL, off)
say("2. control: without the erasure the same fill changes all of them (stop S1 reproduced)",
    all(b0[n] != f0[n] for n in NAMES))
print("fp_proof_field_2610:", "ok" if not bad else f"FAILED ({len(bad)})")
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""Phase 0 axiom sweep for one project: every declaration in the project's namespace, checked for
axioms outside propext / Classical.choice / Quot.sound, and for sorryAx.

  axiom_sweep.py                 project chosen by the current git branch
  axiom_sweep.py --project NAME
  axiom_sweep.py --selftest      negative controls: the sweep must go red on each, with its own message

Modes (config key `sweep.mode`):
  append  -- the project is not a lean_lib, so it cannot be imported; the sweep is appended to a
             temporary copy of `sweep.file`. (This is why the protocol's original recipe,
             `import <Name>.Theorem`, could not work.)
  import  -- `import <sweep.module>` then the sweep; use once the project is a lean_lib.

The raw `lake env lean` output is passed through unchanged and its exit code is this script's
exit code. Nothing in the repository is written; the temporary file lives in the system temp dir.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

TAIL = os.path.join(project.AUDITS, "axiom_sweep_tail.lean")

NEGATIVE = {
    "explicit-sorry": "theorem negctl_sorry : 1 = 2 := sorry",
    "unsolved-goal": "theorem negctl_unsolved : 1 = 2 := by\n  skip",
    # A private declaration's real name is `_private.<module>.0.<ns>.<name>`, which is "internal";
    # an earlier version of the sweep skipped every one of them.
    "private-sorry": "private theorem negctl_private : 1 = 2 := sorry",
    # outside the project's namespace, in a project file: still the project's
    "root-level-sorry": None,
    "custom-axiom": None,  # needs an axiom outside the namespace, see below
}


# Controls of the exemption for declarations left unproved by a logged decision: (injected Lean,
# the exempt list relative to the namespace, the goal results as the index cites them, the sweep's
# errors -- all required -- or None for a pass). "{ns}" is the namespace.
GOAL_REFUSED = "goal result {} is named in a 'leave <decl> unproved' line: refused (a goal result left unproved is a stop)"
EXEMPT = {
    "exempt-sorry": ("theorem negctl_sorry : 1 = 2 := sorry", ["negctl_sorry"], [], None),
    # its dependents are holes, also one named under it: listed (logged) or RED
    "exempt-dependent": ("theorem negctl_sorry : 1 = 2 := sorry\ntheorem negctl_dep : 1 = 2 := negctl_sorry\n"
                         "theorem negctl_sorry.mono : 1 = 2 := negctl_sorry", ["negctl_sorry"], [],
                         ["2 declarations reach sorryAx"]),
    # written by the operator under an exempt name: a hole, even with a compiler-like name
    # (`proof_1`: it has a source range); a declaration added with no range but not a generated
    # name (`eq_raw`, by a meta-program) is a hole too
    "exempt-written-aux": ("theorem negctl_sorry : 1 = 2 := sorry\ntheorem negctl_sorry.eq_dep : 1 = 2 := negctl_sorry\n"
                           "theorem negctl_sorry.eq_add (a b : Nat) (h : b ≤ a) : b + (a - b) = a := by\n"
                           "  exact absurd negctl_sorry (by decide)\n"
                           "theorem negctl_sorry.proof_1 : 1 = 2 := negctl_sorry\n"
                           "open Lean in\nrun_cmd Elab.Command.liftCoreM do\n"
                           "  let c ← getConstInfo `{ns}.negctl_sorry\n"
                           "  addDecl (.thmDecl {{ name := `{ns}.negctl_sorry.eq_raw, levelParams := [], type := c.type, "
                           "value := .const `{ns}.negctl_sorry [] }})",
                           ["negctl_sorry"], [], ["4 declarations reach sorryAx"]),
    # compiler-generated equation lemmas and functional induction of exempt definitions (no source
    # range) pass; the theorems that realize them are exempt themselves
    "exempt-generated": ("def negctl_f (n : Nat) : Nat := match n with | 0 => sorry | k+1 => k\n"
                         "theorem negctl_t : negctl_f 0 = negctl_f 0 := by rw [negctl_f.eq_1]\n"
                         "def negctl_w (n : Nat) : Nat := if h : n = 0 then 0 else negctl_w (n / 2)\n"
                         "decreasing_by sorry\n"
                         "theorem negctl_u (n : Nat) : negctl_w n = negctl_w n := by\n"
                         "  induction n using negctl_w.induct <;> rfl",
                         ["negctl_f", "negctl_t", "negctl_w", "negctl_u"], [], None),
    # a goal result is never exempt: cited by its short name (resolved namespace ++ name), the
    # sweep refuses its line and counts it as a hole
    "exempt-goal": ("theorem negctl_sorry : 1 = 2 := sorry", ["negctl_sorry"], ["negctl_sorry"],
                    [GOAL_REFUSED.format("{ns}.negctl_sorry"), "1 declarations reach sorryAx"]),
    # a goal the index cites as `X.proof_main` under an exempt X: a hole
    "exempt-goal-aux-name": ("theorem negctl_sorry : 1 = 2 := sorry\ntheorem negctl_sorry.proof_main : 1 = 2 := negctl_sorry",
                             ["negctl_sorry"], ["negctl_sorry.proof_main"], ["1 declarations reach sorryAx"]),
    "exempt-other": ("theorem negctl_sorry : 1 = 2 := sorry", ["negctl_other"], [], ["1 declarations reach sorryAx"]),
}


# Controls of the pending state (B2, U2 §3 H3): (injected Lean, the pending list relative to the namespace,
# the sweep's errors or None for a pass). A dependent that reaches sorryAx only through a pending
# declaration passes; one with a sorry of its own, or a sorry outside every pending one, is a hole. (A
# proof that unfolds a pending definition so that sorryAx appears in its own term is a hole too: the walk
# is syntactic, and fails closed.)
PENDING_CTL = {
    "pending-dependent": ("theorem negctl_sorry : 1 = 2 := sorry\ntheorem negctl_dep : 1 = 2 := negctl_sorry\n"
                          "theorem negctl_dep2 : 2 = 1 := negctl_dep.symm", ["negctl_sorry"], None),
    "pending-own-sorry": ("theorem negctl_sorry : 1 = 2 := sorry\ntheorem negctl_dep : 1 = 2 := negctl_sorry\n"
                          "theorem negctl_own : 1 = 2 := by\n  have _h := negctl_sorry\n  exact sorry",
                          ["negctl_sorry"], ["1 declarations reach sorryAx"]),
    "pending-other": ("theorem negctl_sorry : 1 = 2 := sorry", ["negctl_other"], ["1 declarations reach sorryAx"]),
}


# The last name component of a compiler-generated auxiliary (an equation lemma, an unfolding lemma,
# a functional induction principle, an auxiliary proof), as a Lean `String → Bool`. Filled into
# this sweep's tail and into the dependency walk's (dependencies.py), which lists every auxiliary
# the sweep accepts under an exempt name so the report discloses it: one rule, two users.
GENERATED_LEAN = ('fun (s : String) => s == "eq_def" || s == "eq_unfold" || s == "induct" || s == "mutual_induct"'
                  ' || (s.startsWith "eq_" && !(s.toList.drop 3).isEmpty && (s.toList.drop 3).all Char.isDigit)'
                  ' || (s.startsWith "proof_" && !(s.toList.drop 6).isEmpty && (s.toList.drop 6).all Char.isDigit)')


def project_unproved(cfg):
    """The declarations a logged [DELEGATED] decision left unproved (committed RUN_LOG.md)."""
    import decisions
    return sorted(decisions.unproved(cfg)["decls"])


def project_goals(cfg):
    """The goal results' Lean names, resolved (decisions.goal_decls): never exempt."""
    import decisions
    return sorted(decisions.goal_decls(cfg))


def lean_list(xs):
    return "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in xs) + "]"


def project_pending(cfg):
    """The declarations of a re-approval QUESTION the human has not answered (the pending state, U2 §3 H3)."""
    import decisions
    return sorted(decisions.pending_reapproval(cfg))


def build_source(cfg, inject=None, namespace=None, module_root=None, unproved=None, goals=None, pending=None):
    unproved = project_unproved(cfg) if unproved is None else unproved
    goals = project_goals(cfg) if goals is None else goals
    pending = project_pending(cfg) if pending is None else pending
    tail = project.lean_tail(dict(cfg, namespace=namespace or cfg["namespace"]), TAIL,
                             [("__MIN_DECLS__", str(cfg["sweep"].get("min_decls", 10))),
                              ("__UNPROVED__", lean_list(unproved)), ("__GOALS__", lean_list(goals)),
                              ("__PENDING__", lean_list(pending)),
                              ("__GENERATED__", GENERATED_LEAN)],
                             root=module_root)
    body = project.lean_body(cfg)
    extra = ""
    if inject == "root-level-sorry":
        extra = "\ntheorem negctlRootLevel : 1 = 2 := sorry\n"
    elif inject == "custom-axiom":
        extra = (f"\naxiom negctlAx : False\nnamespace {cfg['namespace']}\n"
                 f"theorem negctl_axiom : 1 = 2 := negctlAx.elim\nend {cfg['namespace']}\n")
    elif inject in EXEMPT or inject in PENDING_CTL:
        lean_ = (EXEMPT.get(inject) or PENDING_CTL[inject])[0]
        extra = f"\nnamespace {cfg['namespace']}\n{lean_.format(ns=cfg['namespace'])}\nend {cfg['namespace']}\n"
    elif inject:
        extra = f"\nnamespace {cfg['namespace']}\n{NEGATIVE[inject]}\nend {cfg['namespace']}\n"
    return body + extra + tail


def run(cfg, **kw):
    return project.run_lean(build_source(cfg, **kw))


# The sweep's own error messages (axiom_sweep_tail.lean's logError lines). The selftest asks for
# these, not just a non-zero exit: an unsolved goal or an unknown module is a Lean error by itself,
# so a control that failed only that way would prove nothing about the sweep.
SWEEP_ERROR = re.compile(r"error: (\d+ declarations reach sorryAx|\S+ carries \[|swept only \d+ declarations"
                         r"|goal result \S+ is named in a 'leave)")


def sweep_errors(out):
    """The sweep's own error lines in Lean output `out`, from "error: " on (no temp file path)."""
    return [l[l.index("error: "):] for l in out.splitlines() if SWEEP_ERROR.search(l)]


SWEPT_ONLY = "swept only "   # the min_decls message: its count varies, so it is matched as a prefix


def says(errs, msg):
    """Some sweep error line is exactly "error: <msg>" (the whole line, so "1 declarations" never
    matches "11 declarations"); SWEPT_ONLY is a prefix."""
    return any(l.startswith("error: " + msg) if msg == SWEPT_ONLY else l.rstrip() == "error: " + msg
               for l in errs)


CLEAN_DECLS = ("namespace NegCtlClean\n" + "".join(f"theorem clean_{i} : True := trivial\n" for i in range(12))
               + "end NegCtlClean\n")


def synthetic_target():
    """A small clean target in the system temp dir (never in the repository): its path."""
    fd, path = tempfile.mkstemp(suffix=".lean", prefix="negctl_target_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("import Lean.Elab.Command\n" + CLEAN_DECLS)
    return path


def module_control():
    """The module rule's `| some i =>` branch: a root-level `sorry` in an IMPORTED project module,
    outside the namespace. A module NegCtlMod is compiled into a fresh temp dir (never the
    repository) and imported with module root NegCtlMod; the sweep must report its sorry.
    (exit code, Lean output)."""
    d = tempfile.mkdtemp(prefix="negctl_mod_")
    try:
        mod = os.path.join(d, "NegCtlMod.lean")
        with open(mod, "w", encoding="utf-8") as fh:
            fh.write("theorem negctlModRoot : 1 = 2 := sorry\n")
        r = subprocess.run(["lake", "env", "lean", "--root=" + d, "-o", os.path.join(d, "NegCtlMod.olean"), mod],
                           cwd=project.REPO, capture_output=True, text=True)
        if r.returncode != 0:
            return r.returncode, "error (building the temp module NegCtlMod): " + (r.stdout + r.stderr)
        cfg = {"namespace": "NegCtlClean", "sweep": {"min_decls": 10}}
        tail = project.lean_tail(cfg, TAIL, [("__MIN_DECLS__", "10"), ("__UNPROVED__", "[]"), ("__GOALS__", "[]"),
                                             ("__PENDING__", "[]"),
                                                   ("__GENERATED__", GENERATED_LEAN)], root="NegCtlMod")
        return project.run_lean("import NegCtlMod\nimport Lean.Elab.Command\n" + CLEAN_DECLS + tail, lean_path=d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def synthetic_cfg(cfg, path):
    return dict(cfg, namespace="NegCtlClean", lean_files=[path],
                sweep={"mode": "append", "file": path, "min_decls": 10})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--inject", help=argparse.SUPPRESS)   # selftest: run main() on a negative control
    ap.add_argument("--synthetic-target", help=argparse.SUPPRESS)   # selftest: ... on its clean target
    a = ap.parse_args()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    print(f"# project {cfg['name']} (selected by {why}); namespace {cfg['namespace']}",
          file=sys.stderr)

    if not a.selftest:
        kw = {}
        if a.synthetic_target:
            cfg, kw = synthetic_cfg(cfg, a.synthetic_target), {"module_root": ""}
        rc, out = run(cfg, inject=a.inject, **kw)
        sys.stdout.write(out)
        print(f"axiom sweep exit={rc}")
        return rc

    # Negative controls: each must make the sweep fail with its own error message. A checker that has never failed
    # may be passing vacuously, and a green run cannot tell you which. They prove something only if
    # the target is clean to begin with: on a project still in its statement phase (every proof
    # `sorry`) each control went red whatever the sweep did, and four mutants of the sweep survived
    # (release 0.1.0). So: a positive control first; if the project is not clean, the controls run
    # on a small synthetic target that is.
    rc0, out0 = run(cfg)
    synth_path, own = None, None
    if rc0 != 0:
        # the project's own sweep errors, shown so a reader sees why the fallback happened (and
        # checked against main() below); Lean's other errors if the sweep never reported
        own = sweep_errors(out0)
        shown = own or [l for l in out0.splitlines() if "error" in l][:5]
        synth_path = synthetic_target()
        print("  note  the project is not clean (e.g. statements with `sorry`): the controls run on a "
              "synthetic clean target; the project's sweep says:\n" + "\n".join("          " + l for l in shown))
        cfg = synthetic_cfg(cfg, synth_path)
    try:
        return _controls(cfg, synth_path, own)
    finally:
        if synth_path:
            os.unlink(synth_path)


def _controls(cfg, synth_path, own):
    synthetic = synth_path is not None
    ok = True
    if synthetic:
        tmp, repo = os.path.realpath(tempfile.gettempdir()), os.path.realpath(project.REPO)
        d = os.path.dirname(os.path.realpath(synth_path))
        hit = d == tmp and os.path.commonpath([d, repo]) != repo
        ok &= hit
        print(f"  {'ok  ' if hit else 'FAIL'}  the synthetic target is in the system temp dir, not the "
              f"repository: {synth_path}")
    rcp, outp = run(cfg, module_root="" if synthetic else None)
    hit = rcp == 0
    ok &= hit
    print(f"  {'ok  ' if hit else 'FAIL'}  positive control: the clean target passes: exit={rcp}"
          + ("" if hit else "  " + " | ".join(outp.splitlines()[-2:])))
    mr = {"module_root": ""} if synthetic else {}
    sorry = "1 declarations reach sorryAx"
    want = {"explicit-sorry": sorry, "unsolved-goal": sorry, "private-sorry": sorry,
            "root-level-sorry": sorry, "custom-axiom": f"{cfg['namespace']}.negctl_axiom carries [negctlAx]"}
    # each control must fail with the sweep's own message (want), not merely exit non-zero
    cases = [(k, want[k], dict(inject=k, **mr)) for k in NEGATIVE]
    # A config that points the sweep at nothing (namespace AND module root wrong) must not pass:
    # the min_decls guard. A wrong namespace alone is now harmless -- the module rule still finds
    # every project declaration -- which is the point of the module rule.
    if synthetic:
        # every declaration of an appended file is swept whatever the namespace, so test the guard
        # itself: a sweep that finds fewer than min_decls declarations must not pass
        cases.append(("too-few-declarations (min_decls guard)", SWEPT_ONLY,
                      dict(module_root="", _cfg=dict(cfg, sweep=dict(cfg["sweep"], min_decls=1000)))))
    else:
        cases.append(("wrong-namespace-and-module", SWEPT_ONLY,
                      dict(namespace=cfg["namespace"] + "NegCtlTypo", module_root="NegCtlTypoRoot")))
    for label, msg, kw in cases:
        rc, out = run(kw.pop("_cfg", cfg), **kw)
        errs = sweep_errors(out)
        hit = rc != 0 and says(errs, msg)
        ok &= hit
        why = " | ".join(errs[-2:]) if hit else (f"wanted the sweep's error {msg!r}; Lean said: "
                                                  + " | ".join([l for l in out.splitlines() if "error" in l][:2]))
        print(f"  {'ok  ' if hit else 'FAIL'}  {label}: exit={rc}  {why}")
    # a declaration left unproved by a logged [DELEGATED] decision: its sorryAx alone passes; a
    # dependent (also one named under it), or a sorry elsewhere, is still a hole
    for label, (_, names, goals, msgs) in EXEMPT.items():
        rc, out = run(cfg, inject=label, unproved=[f"{cfg['namespace']}.{n}" for n in names], goals=goals, **mr)
        errs = sweep_errors(out)
        msgs = [m_.format(ns=cfg["namespace"]) for m_ in msgs] if msgs else None
        msg = " + ".join(msgs) if msgs else None
        hit = rc == 0 and not errs if msgs is None else rc != 0 and all(says(errs, m_) for m_ in msgs)
        ok &= hit
        print(f"  {'ok  ' if hit else 'FAIL'}  {label} (exempt: {', '.join(names)}): exit={rc}  "
              + (" | ".join(errs) or "passes") + ("" if hit else f"  wanted {msg or 'a pass'!r}; Lean said: "
                                                  + " | ".join([l for l in out.splitlines() if "error" in l][:2])))
    # B2 (U2 §3 H3): the pending state -- sorryAx reaching a result only through a pending declaration passes
    for label, (_, names, msgs) in PENDING_CTL.items():
        rc, out = run(cfg, inject=label, unproved=[], goals=[], pending=[f"{cfg['namespace']}.{n}" for n in names], **mr)
        errs = sweep_errors(out)
        hit = (rc == 0 and not errs) if msgs is None else (rc != 0 and all(says(errs, m_) for m_ in msgs))
        ok &= hit
        print(f"  {'ok  ' if hit else 'FAIL'}  {label} (pending: {', '.join(names)}): exit={rc}  "
              + (" | ".join(errs) or "passes") + ("" if hit else f"  wanted {msgs or 'a pass'!r}; Lean said: "
                                                  + " | ".join([l for l in out.splitlines() if "error" in l][:2])))
    # a root-level sorry in an imported project module (not the appended file) is swept
    rc, out = module_control()
    errs = sweep_errors(out)
    hit = rc != 0 and says(errs, sorry)
    ok &= hit
    print(f"  {'ok  ' if hit else 'FAIL'}  root-level-sorry in an imported project module: exit={rc}  "
          + (" | ".join(errs) if hit else f"wanted the sweep's error {sorry!r}; Lean said: "
             + " | ".join([l for l in out.splitlines() if "error" in l][:2])))
    # main()'s exit code is what phase0 reads; test it end to end, not only run(): with a sorry
    # injected into the clean target, main() must exit non-zero AND print the sweep's report
    import subprocess as _sp

    def main_run(*args):
        r = _sp.run([sys.executable, os.path.abspath(__file__), "--project", cfg["name"], *args],
                    cwd=project.REPO, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr
    rc, out = main_run("--inject", "explicit-sorry",
                       *(["--synthetic-target", synth_path] if synthetic else []))
    errs = sweep_errors(out)
    hit = rc != 0 and says(errs, sorry) and f"axiom sweep exit={rc}" in out
    ok &= hit
    print(f"  {'ok  ' if hit else 'FAIL'}  main() on a sorry: exit={rc} with the sweep's report  "
          + (" | ".join(errs) or " | ".join(out.strip().splitlines()[-2:])))
    if synthetic:
        # the fallback note showed the project's own sweep errors: they are what main() reports
        rc, out = main_run()
        errs = sweep_errors(out)
        hit = rc != 0 and bool(errs) and errs == own
        ok &= hit
        what = ("the same sweep errors as the note above" if hit else
                "the project's sweep failed without a sweep message (Lean errors in the note above, e.g. a "
                "stale or unbuildable import)" if not own else "not the sweep errors the note above showed")
        print(f"  {'ok  ' if hit else 'FAIL'}  main() on the project as it stands: exit={rc}, {what}  "
              + (" | ".join(errs) or " | ".join(out.strip().splitlines()[-2:])))
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1

if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

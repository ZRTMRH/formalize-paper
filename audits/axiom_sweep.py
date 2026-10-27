#!/usr/bin/env python3
"""Phase 0 axiom sweep for one project: every declaration in the project's namespace, checked for
axioms outside propext / Classical.choice / Quot.sound, and for sorryAx.

  axiom_sweep.py                 project chosen by the current git branch
  axiom_sweep.py --project NAME
  axiom_sweep.py --selftest      negative controls: the sweep must go red on each of them

Modes (config key `sweep.mode`):
  append  -- the project is not a lean_lib, so it cannot be imported; the sweep is appended to a
             temporary copy of `sweep.file`. (This is why the protocol's original recipe,
             `import <Name>.Theorem`, could not work.)
  import  -- `import <sweep.module>` then the sweep; use once the project is a lean_lib.

The raw `lake env lean` output is passed through unchanged and its exit code is this script's
exit code. Nothing in the repository is written; the temporary file lives in the system temp dir.
"""
import argparse, os, subprocess, sys, tempfile
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


def build_source(cfg, inject=None, namespace=None, module_root=None):
    sw = cfg["sweep"]
    ns = namespace or cfg["namespace"]
    tail = open(TAIL, encoding="utf-8").read()
    tail = tail.replace("__NAMESPACE__", ns).replace("__MIN_DECLS__", str(sw.get("min_decls", 10)))
    import fingerprint
    root = fingerprint.module_root(cfg) if module_root is None else module_root
    tail = tail.replace("`__MODULE_ROOT__", ("`" + root) if root else "Name.anonymous")
    if sw["mode"] == "append":
        body = open(os.path.join(project.REPO, sw["file"]), encoding="utf-8").read()
    elif sw["mode"] == "import":
        body = f"import {sw['module']}\n"
    else:
        raise SystemExit(f"FAIL: unknown sweep.mode {sw['mode']!r}")
    extra = ""
    if inject == "root-level-sorry":
        extra = "\ntheorem negctlRootLevel : 1 = 2 := sorry\n"
    elif inject == "custom-axiom":
        extra = (f"\naxiom negctlAx : False\nnamespace {cfg['namespace']}\n"
                 f"theorem negctl_axiom : 1 = 2 := negctlAx.elim\nend {cfg['namespace']}\n")
    elif inject:
        extra = f"\nnamespace {cfg['namespace']}\n{NEGATIVE[inject]}\nend {cfg['namespace']}\n"
    return body + extra + tail


def run(cfg, **kw):
    src = build_source(cfg, **kw)
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        r = subprocess.run(["lake", "env", "lean", path], cwd=project.REPO,
                           capture_output=True, text=True)
    finally:
        os.unlink(path)
    return r.returncode, r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--inject", help=argparse.SUPPRESS)   # selftest: run main() on a negative control
    a = ap.parse_args()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    print(f"# project {cfg['name']} (selected by {why}); namespace {cfg['namespace']}",
          file=sys.stderr)

    if not a.selftest:
        rc, out = run(cfg, inject=a.inject)
        sys.stdout.write(out)
        print(f"axiom sweep exit={rc}")
        return rc

    # Negative controls: each must make the sweep exit non-zero. A checker that has never failed
    # may be passing vacuously, and a green run cannot tell you which. They prove something only if
    # the target is clean to begin with: on a project still in its statement phase (every proof
    # `sorry`) each control went red whatever the sweep did, and four mutants of the sweep survived
    # (release 0.1.0). So: a positive control first; if the project is not clean, the controls run
    # on a small synthetic target that is.
    rc0, _ = run(cfg)
    synth_path = None
    if rc0 != 0:
        fd, synth_path = tempfile.mkstemp(suffix=".lean", prefix="negctl_target_", dir=project.REPO)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("import Lean.Elab.Command\nnamespace NegCtlClean\n"
                     + "".join(f"theorem clean_{i} : True := trivial\n" for i in range(12))
                     + "end NegCtlClean\n")
        cfg = dict(cfg, namespace="NegCtlClean", lean_files=[os.path.relpath(synth_path, project.REPO)],
                   sweep={"mode": "append", "file": synth_path, "min_decls": 10})
        print("  note  the project is not clean (e.g. statements with `sorry`): the controls run on a "
              "synthetic clean target")
    try:
        return _controls(cfg, synthetic=synth_path is not None)
    finally:
        if synth_path:
            os.unlink(synth_path)


def _controls(cfg, synthetic):
    rcp, outp = run(cfg, module_root="" if synthetic else None)
    ok = rcp == 0
    print(f"  {'ok  ' if ok else 'FAIL'}  positive control: the clean target passes: exit={rcp}"
          + ("" if ok else "  " + " | ".join(outp.splitlines()[-2:])))
    mr = {"module_root": ""} if synthetic else {}
    cases = [(k, dict(inject=k, **mr)) for k in NEGATIVE]
    # A config that points the sweep at nothing (namespace AND module root wrong) must not pass:
    # the min_decls guard. A wrong namespace alone is now harmless -- the module rule still finds
    # every project declaration -- which is the point of the module rule.
    if synthetic:
        # every declaration of an appended file is swept whatever the namespace, so test the guard
        # itself: a sweep that finds fewer than min_decls declarations must not pass
        cases.append(("too-few-declarations (min_decls guard)",
                      dict(module_root="", _cfg=dict(cfg, sweep=dict(cfg["sweep"], min_decls=1000)))))
    else:
        cases.append(("wrong-namespace-and-module", dict(namespace=cfg["namespace"] + "NegCtlTypo",
                                                         module_root="NegCtlTypoRoot")))
    for label, kw in cases:
        rc, out = run(kw.pop("_cfg", cfg), **kw)
        hit = rc != 0
        ok &= hit
        last = [l for l in out.splitlines() if "axiom sweep" in l or "swept only" in l
                or "reach sorryAx" in l or "carries" in l]
        print(f"  {'ok  ' if hit else 'FAIL'}  {label}: exit={rc}  {' | '.join(last[-2:])}")
    # main()'s exit code is what phase0 reads; test it end to end, not only run()
    import subprocess as _sp
    # On a project that is not clean, main() on the project as it stands must already exit
    # non-zero; on a clean one, with a sorry injected.
    r = _sp.run([sys.executable, os.path.abspath(__file__), "--project", cfg["name"]]
                + ([] if synthetic else ["--inject", "explicit-sorry"]),
                cwd=project.REPO, capture_output=True, text=True)
    hit = r.returncode != 0
    ok &= hit
    print(f"  {'ok  ' if hit else 'FAIL'}  main() exits non-zero on a sorry: exit={r.returncode}")
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

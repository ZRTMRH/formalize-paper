#!/usr/bin/env python3
"""Regression (TP1, sparse-note-2): prompt.py's cross-paper leak control compared the first two configured
projects whatever their sources, so a re-run beside an older project on the same paper failed the selftest
("project A's lanes do not name B's PDF") although nothing leaked. The control must pick two projects on
different papers, and skip when there is none.

  python3 tests/regressions/shared_source_leak_control.py --apparatus DIR   (exit 0 iff the fix is present)
"""
import argparse, os, sys
sys.dont_write_bytecode = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apparatus", required=True)
    a = ap.parse_args()
    sys.path.insert(0, os.path.abspath(a.apparatus))
    import prompt
    pick = getattr(prompt, "leak_control_pair", None)
    if pick is None:
        print("FAIL  prompt.py has no leak_control_pair: the leak control still pairs the first two projects")
        return 1
    same = {"a-2": {"source_pdf": "paper/note.tex"}, "a": {"source_pdf": "./paper/note.tex"}}
    mixed = {"a-2": {"source_pdf": "paper/note.tex"}, "a": {"source_pdf": "paper/note.tex"},
             "b": {"source_pdf": "paper/other.tex"}}
    checks = [
        ("two projects on one paper give no pair (nothing to control)", pick(same) is None),
        ("a project on another paper is paired, never a same-paper one",
         (lambda p: p is not None and {p[0][0], p[1][0]} == {"a-2", "b"})(pick(mixed))),
        ("fewer than two projects give no pair", pick({"x": {"source_pdf": "p.tex"}}) is None and pick({}) is None),
    ]
    ok = True
    for name, passed in checks:
        print(f"  {'ok  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

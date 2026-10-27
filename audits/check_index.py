#!/usr/bin/env python3
"""Check the paper->Lean index table against the Lean source.

WHY.  The source is a PDF, so there is no .aux and no label->number map, so the coverage check
that a LaTeX-backed project gets for free cannot be built.  The whole of that job is done by a
hand-written index table in the project's Main.lean, and until now it was read by nobody but
Lane C, once a round, by eye.

Half of that job IS mechanical, and this is it:

  1. Every Lean name the index cites must exist.  A rename, a deletion, or a typo in the index
     leaves a row pointing at nothing, and nothing else in Phase 0 would notice -- the build is
     green either way, because the index is a comment.
  2. Every row must cite at least one name that exists, or say in words that it is not
     formalized.  A row whose names have all vanished is a paper result the project has silently
     stopped covering.
  3. Numbering gaps, as a warning.  Results are numbered sequentially within a section, so a
     jump from 4.3 to 4.5 means either the paper has no 4.4 or the index forgot it.  This is a
     heuristic, not a proof, and is reported as a warning for a human to settle.

WHAT IT STILL DOES NOT DO.  It cannot tell you the index is COMPLETE, because it has no
machine-readable list of the paper's results to compare against -- only the index itself.  A
result the paper states and the index never mentions is invisible here, as it is to every other
check in this repository.  That remains Lane C's job, and a Lane C `NotDoneYet` on coverage is
therefore a real gap rather than a formality.  Do not read a green run here as "the paper is
covered"; read it as "the index is internally honest".

Usage:
  check_index.py --project sparse-note
  check_index.py --project sparse-note --selftest
Exit 1 on a dangling name or an empty row; 0 otherwise (warnings do not gate).
"""
import argparse, json, os, re, sys, glob
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402  (RESULT_KINDS lives there, once)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# A backticked token is a candidate declaration only if it could be a Lean identifier: no spaces,
# no operators, no parentheses.  The index also backticks mathematical notation (`v(G) ≥ 2`, `H₁`)
# and that must not be mistaken for a missing declaration.
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_'!?₀-₉ₐ-ₜ]*(?:\.[A-Za-z_][A-Za-z0-9_'!?₀-₉ₐ-ₜ]*)*$")
# Names matching the project's own convention are unambiguously ours: a dangling one is an error,
# not something that might live in Mathlib.
OURS = re.compile(r"^(lemma|thm|theorem|cor|prop|def|example|claim|remark|fact|construction)_\d", re.I)
DECL = r"(?:theorem|lemma|def|abbrev|structure|inductive|class|instance|noncomputable def)"
NOT_FORMALIZED = re.compile(r"not formalized|no new statement|deferred|out of scope", re.I)
ROW = re.compile(rf"^\|\s*((?:{project.RESULT_KINDS_RE})\s[^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
NUM = re.compile(r"(\d+)\.(\d+)")


def load_project(name):
    p = os.path.join(HERE, "projects", f"{name}.json")
    if not os.path.exists(p):
        print(f"FAIL: no project config at {p}", file=sys.stderr); sys.exit(2)
    return json.load(open(p, encoding="utf-8"))


def declared_names(repo, lean_files):
    """Every name declared in the project's Lean files, as written AND fully qualified, so an
    index may cite `thm_1_1` or `N.thm_1_1`. Read by scope.py's parser, which ignores comments --
    a declaration inside `/- … -/` used to count as existing."""
    import scope
    names = set()
    for rel in lean_files:
        f = os.path.join(repo, rel)
        if not os.path.exists(f):
            print(f"warning: listed Lean file missing: {rel}", file=sys.stderr); continue
        for qual in scope.parse_decls(open(f, encoding="utf-8").read()):
            if qual != "_unnamed":
                names |= scope.short_names(qual)
    return names


def parse_index(text):
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            rows.append((m.group(1).strip(), m.group(2).strip()))
    return rows


def run(cfg, repo, quiet=False):
    lean_files = cfg["lean_files"]
    index_file = cfg.get("index_file") or next(
        (f for f in lean_files if f.endswith("Main.lean")), lean_files[0])
    path = os.path.join(repo, index_file)
    if not os.path.exists(path):
        print(f"FAIL: index file not found: {index_file}", file=sys.stderr); return 2
    rows = parse_index(open(path, encoding="utf-8").read())
    if not rows:
        # Refuse to pass vacuously: no rows parsed means the table moved or its shape changed.
        print(f"FAIL: parsed 0 index rows from {index_file} — the table is missing or its "
              f"format changed. This check cannot pass by finding nothing.", file=sys.stderr)
        return 2

    declared = declared_names(repo, lean_files)
    dangling, empty, warnings = [], [], []

    strict = bool(cfg.get("index_strict"))
    for paper, lean in rows:
        spans = re.findall(r"`([^`]+)`", lean)
        cited = [t for t in spans if IDENT.match(t)]
        exists = [t for t in cited if t in declared]
        if strict:
            # Strict (every new project): backticks are for Lean names only, math goes in $…$.
            # Then every span must be a declaration, so a misspelt name beside a valid one in the
            # same row fails instead of passing with a warning.
            missing_ours = [t for t in spans if t not in declared]
            unknown = []
        else:
            missing_ours = [t for t in cited if t not in declared and OURS.match(t)]
            unknown = [t for t in cited if t not in declared and not OURS.match(t)]
        for t in missing_ours:
            dangling.append((paper, t))
        if unknown and not quiet:
            warnings.append(f"  {paper}: cited but not declared here — Mathlib, or notation? "
                            f"{', '.join(unknown)}")
        if not exists and not NOT_FORMALIZED.search(lean):
            empty.append((paper, lean[:70]))

    # numbering continuity, per section
    seen = {}
    for paper, _ in rows:
        m = NUM.search(paper)
        if m:
            seen.setdefault(int(m.group(1)), set()).add(int(m.group(2)))
    gaps = []
    for sec in sorted(seen):
        nums = sorted(seen[sec])
        for k in range(1, max(nums) + 1):
            if k not in nums:
                gaps.append(f"{sec}.{k}")

    print(f"index: {index_file}, {len(rows)} rows, {len(declared)} declarations in the project\n")
    print(f"DANGLING NAMES ({len(dangling)}) — the index cites a project declaration that does not exist")
    for paper, t in dangling:
        print(f"  {paper}: `{t}`")
    if not dangling:
        print("  none")

    print(f"\nEMPTY ROWS ({len(empty)}) — no existing declaration, and not marked unformalized")
    for paper, lean in empty:
        print(f"  {paper}: {lean}")
    if not empty:
        print("  none")

    print(f"\nNUMBERING GAPS ({len(gaps)}) — warning only; the paper may simply have no such result")
    print("  " + (", ".join(gaps) if gaps else "none"))

    if warnings:
        print(f"\nNOT DECLARED HERE ({len(warnings)} row(s)) — expected for Mathlib names and notation")
        for w in warnings:
            print(w)

    # --- PAPER_DEFECTS.md witnesses ---------------------------------------------------------
    # A defect row names a Lean witness. If that name no longer exists the row is a claim about
    # someone else's paper that nobody here can back up -- the worst kind of stale reference,
    # since it is the kind that gets sent outside the project.
    defects = os.path.join(repo, cfg.get("rounds_dir", "audits"), "PAPER_DEFECTS.md")
    dead_witness = []
    if os.path.exists(defects):
        rows = 0
        for line in open(defects, encoding="utf-8"):
            st = line.strip()
            if not st.startswith("|") or set(st) <= set("|-: "):
                continue
            cells = [c.strip() for c in st.strip("|").split("|")]
            if len(cells) < 6 or cells[0] in ("#", "") or not cells[0].rstrip(".").isdigit():
                continue
            rows += 1
            for t in re.findall(r"`([^`]+)`", cells[5]):
                t = t.split("(")[0].strip()
                if IDENT.match(t) and t not in declared:
                    dead_witness.append((cells[0], t))
        print(f"\nPAPER_DEFECTS witnesses ({rows} defect row(s)) — named declarations must exist")
        for n, t in dead_witness:
            print(f"  defect {n}: `{t}` is not declared in this project")
        if not dead_witness:
            print("  all present")
    else:
        print("\nPAPER_DEFECTS.md: absent (none recorded yet)")

    bad = len(dangling) + len(empty) + len(dead_witness)
    print(f"\n{'FAIL' if bad else 'ok'}: {len(dangling)} dangling, {len(empty)} empty, "
          f"{len(dead_witness)} dead defect witness(es), {len(gaps)} numbering gap(s) [warning]")
    print("NOTE: a green run means the index is internally honest, NOT that the paper is covered.")
    return 1 if bad else 0


def selftest(cfg, repo):
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "P"))
        open(os.path.join(tmp, "P", "Src.lean"), "w").write(
            "theorem lemma_1_1 : True := trivial\ndef helper : Nat := 0\n")
        def write_index(rows):
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(
                "/-!\n| Paper | Lean |\n|---|---|\n" + "\n".join(rows) + "\n-/\n")
        c = {"lean_files": ["P/Src.lean", "P/Main.lean"], "index_file": "P/Main.lean"}

        checks = []
        write_index(["| Lemma 1.1 | `lemma_1_1` |"])
        checks.append(("a good index passes", run(c, tmp, quiet=True) == 0))
        write_index(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.2 | `lemma_1_2` |"])
        checks.append(("a dangling project name fails", run(c, tmp, quiet=True) == 1))
        write_index(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.2 | `HasPathCover` |"])
        checks.append(("a row citing ONLY a non-project name is an empty row (fails)",
                       run(c, tmp, quiet=True) == 1))
        write_index(["| Lemma 1.1 | `lemma_1_1` `HasPathCover` |"])
        checks.append(("legacy mode: a non-project name beside a real one only warns",
                       run(c, tmp, quiet=True) == 0))
        cs = dict(c, index_strict=True)
        checks.append(("strict mode: a misspelt name beside a real one fails", run(cs, tmp, quiet=True) == 1))
        write_index(["| Lemma 1.1 | `lemma_1_1` (needs $n \\ge 2$) |"])
        checks.append(("strict mode: math in $…$ beside a real name passes", run(cs, tmp, quiet=True) == 0))
        write_index(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.2 | `hidden_in_comment` |"])
        open(os.path.join(tmp, "P", "Src.lean"), "a").write("/-\ntheorem hidden_in_comment : True := trivial\n-/\n")
        checks.append(("a declaration inside a comment does not count as declared",
                       run(c, tmp, quiet=True) == 1))
        write_index(["| Lemma 1.1 | `lemma_1_1` |"])
        os.makedirs(os.path.join(tmp, "R"))
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(
            "| # | where | sev | says | why | witness | consequence | found |\n|---|---|---|---|---|---|---|---|\n"
            "| 1 | L1.1 | S1 | x | y | `gone_witness` | z | r1 |\n")
        checks.append(("a PAPER_DEFECTS witness that no longer exists fails",
                       run(dict(c, rounds_dir="R"), tmp, quiet=True) == 1))
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(
            "| # | where | sev | says | why | witness | consequence | found |\n|---|---|---|---|---|---|---|---|\n"
            "| 1 | L1.1 | S1 | x | y | `lemma_1_1` | z | r1 |\n")
        checks.append(("an existing witness passes", run(dict(c, rounds_dir="R"), tmp, quiet=True) == 0))
        write_index(["| Lemma 1.1 | `lemma_1_1` |", "| Remark 1.2 | not formalized |"])
        checks.append(("'not formalized' is not an empty row", run(c, tmp, quiet=True) == 0))
        write_index(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.3 | `helper` |"])
        checks.append(("a numbering gap warns but does not fail", run(c, tmp, quiet=True) == 0))
        open(os.path.join(tmp, "P", "Main.lean"), "w").write("/-! no table here -/\n")
        checks.append(("an unparseable table refuses to pass", run(c, tmp, quiet=True) == 2))

        print("\n" + "=" * 60)
        for n, p in checks:
            print(f"  {'ok  ' if p else 'FAIL'}  {n}")
        ok = all(p for _, p in checks)
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    cfg = load_project(a.project)
    if a.selftest:
        return selftest(cfg, a.repo)
    return run(cfg, a.repo)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Phase 0, the mechanical gate, as one command. Raw output through; the verdict table is the
script's, not an agent's.

WHY THIS EXISTS.  Phase 0 used to be eight commands an agent ran by hand, with the instruction to
"paste the raw output, never a summary". That instruction is the weak point: an agent that runs
seven of eight, or reads `lake build X | tail`'s exit code as the build's, or writes "all green",
has put prose between the reader and the ground truth. Here the commands are fixed, each one's
output is passed through unchanged, and the final table of exit codes is computed, not written.

  phase0.py                  author mode: every check, then regenerate the report and save the
                             tree baseline (the next round's "did a lane write?" reference)
  phase0.py --readonly       adjudicator mode: every check, writes NOTHING
  phase0.py --statements     statement round: proofs are `sorry` by design, so the sorry scan and
                             the axiom sweep are reported but do not fail the gate
  phase0.py --selftest

Exit 0 iff every check that is not waived passed.

Checks, in order: on the project's branch; every project .lean file is listed in `lean_files`;
the build; the token scan; the axiom sweep; the index check; the freeze check; the report; and
(author mode, everything else green, and nothing uncommitted) the tree baseline.
"""
import argparse, glob, os, re, subprocess, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

PY = f"{sys.executable} -B"

# Token scan. HARD tokens fail the gate: each either leaves a proof unchecked by the kernel, makes
# the file stop being elaborated, or lets the file run arbitrary code at elaboration time. REVIEW
# tokens are legitimate in places and are listed for the adjudicator, without failing.
MODS = r"(?:(?:private|protected|noncomputable|unsafe|partial|nonrec|scoped|local)\s+)*"
ATTRS = r"(?:@\[[^\]]*\]\s*)*"
HARD = {
    "sorry": r"\bsorry\b", "admit": r"\badmit\b",
    "sorryAx": r"\bsorryAx\b",
    "native_decide / decide +native": r"\bnative_decide\b|\bdecide\s*\+\s*native\b",
    "axiom declaration": rf"^\s*{ATTRS}{MODS}axiom\s",
    "debug option": r"set_option\s+debug\.",
    "implemented_by": r"\bimplemented_by\b",
    "extern": r"\bextern\b",
    "unsafe": r"\bunsafe\b",
    "run_cmd/run_elab/run_meta": r"\brun_(?:cmd|elab|meta)\b",
    "#eval / #exit": r"^\s*#(?:eval|exit)\b",
    "initialize": r"^\s*(?:builtin_)?initialize\b",
    "Lean.ofReduceBool": r"\bofReduceBool\b",
}
REVIEW = {
    "macro/elab/syntax (non-local)": rf"^\s*{ATTRS}(?:macro|elab|syntax|macro_rules|elab_rules|notation)\b",
    "partial def": r"\bpartial\s+def\b",
    "opaque": rf"^\s*{ATTRS}{MODS}opaque\s",
    "set_option maxHeartbeats 0": r"maxHeartbeats\s+0\b",
}
SORRY_LIKE = ("sorry", "admit", "sorryAx")


def strip_comments(text):
    """Remove `--` line comments and (nested) `/- -/` block comments, keeping line numbers.

    String and character literals are skipped as literals: a string containing "/-" used to open a
    block comment that never closed, hiding the rest of the file -- a `sorry` after it scanned
    clean. Literal CONTENT is blanked too, so "sorry" inside a string is not a hit.
    """
    out, i, depth, n = [], 0, 0, len(text)

    def keep(c):
        out.append(c if c == "\n" else " ")

    while i < n:
        if depth == 0:
            if text.startswith("--", i):
                j = text.find("\n", i)
                j = n if j == -1 else j
                out.append(" " * (j - i)); i = j; continue
            if text[i] == '"':
                out.append('"'); i += 1
                while i < n and text[i] != '"':
                    if text[i] == "\\" and i + 1 < n:
                        keep(text[i]); keep(text[i + 1]); i += 2; continue
                    keep(text[i]); i += 1
                if i < n:
                    out.append('"'); i += 1
                continue
            # a char literal: 'x' or '\n', not a prime in an identifier (x', h₁')
            m = re.match(r"'(\\.|[^\\'\n])'", text[i:i + 4])
            if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_'!?")):
                out.append("'" + " " * (len(m.group(0)) - 2) + "'"); i += len(m.group(0)); continue
        if text.startswith("/-", i):
            depth += 1; out.append("  "); i += 2; continue
        if depth and text.startswith("-/", i):
            depth -= 1; out.append("  "); i += 2; continue
        c = text[i]
        out.append(c if depth == 0 or c == "\n" else " ")
        i += 1
    return "".join(out)


def scan(files, repo):
    """{label: [(file, line, text)]} for HARD and REVIEW hits, comments and literals ignored."""
    hits = {k: [] for k in list(HARD) + list(REVIEW)}
    for f in files:
        p = os.path.join(repo, f)
        if not os.path.exists(p):
            hits.setdefault("MISSING FILE", []).append((f, 0, "listed in config, not on disk"))
            continue
        raw = open(p, encoding="utf-8").read()
        code = strip_comments(raw).splitlines()
        rawl = raw.splitlines()
        for n, line in enumerate(code, 1):
            for label, pat in {**HARD, **REVIEW}.items():
                if re.search(pat, line):
                    hits[label].append((f, n, rawl[n - 1].strip()[:120]))
    return hits


DOC_RE = re.compile(r"/-[-!](.*?)-/", re.S)
PLACEHOLDER_RE = re.compile(r"\b(?:Theorem|Lemma|Corollary|Observation|Proposition|Definition|Remark|Claim|Fact)\s+"
                            r"\d*(?:\.\d+)*\.?\?|\?\?|\bTODO\b|\bFIXME\b|\bTBD\b|<<[^>]*>>")
DOC_TEX_RE = re.compile(r"\btex (?:ll?\.\s*~?|lines? )?(\d+)((?:\s*(?:[–-]|,)\s*\d+)*)|\bl\.\s*~?(\d+)\b"
                        r"|\.tex:\s*(\d+)")


def docstring_problems(cfg, repo):
    """[(file:line, problem)] in docstrings and module docs: unfilled placeholders
    ("Observation 1.?", "??", TODO) and tex line citations past the end of the source. In a
    test run both reached the final round (a "?" reference; a line citation two lines off
    after the source shifted) and lanes reported them by hand, round after round."""
    src = cfg.get("source_pdf", "")
    n_src = (open(src, encoding="utf-8", errors="replace").read().count("\n") + 1
             if src.endswith(".tex") and os.path.exists(src) else None)
    out = []
    for rel in cfg["lean_files"]:
        f = os.path.join(repo, rel)
        if not os.path.exists(f):
            continue
        txt = open(f, encoding="utf-8").read()
        for m in DOC_RE.finditer(txt):
            body, line = m.group(1), txt.count("\n", 0, m.start()) + 1
            for p in PLACEHOLDER_RE.finditer(body):
                out.append((f"{rel}:{line + body.count(chr(10), 0, p.start())}", f"placeholder {p.group(0)!r}"))
            if n_src:
                for t in DOC_TEX_RE.finditer(body):
                    nums = [int(x) for x in re.findall(r"\d+", t.group(0))]
                    if nums and max(nums) > n_src:
                        out.append((f"{rel}:{line + body.count(chr(10), 0, t.start())}",
                                    f"{t.group(0)!r} is past the end of the source ({n_src} lines)"))
    return out


def run_log_problems(cfg, repo):
    """Every adjudicated round (it has ADOPTED.md) must appear in RUN_LOG.md: the log is what a
    resumed run reads, and in a test run it fell a round behind (F-I12)."""
    rd = os.path.join(repo, cfg["rounds_dir"])
    log_p = os.path.join(rd, "RUN_LOG.md")
    if not os.path.exists(log_p):
        return []
    log = open(log_p, encoding="utf-8").read()
    return [f"RUN_LOG.md does not mention adjudicated round {os.path.basename(d)}"
            for d in project.rounds(cfg) if os.path.exists(os.path.join(d, "ADOPTED.md"))
            and os.path.basename(d) not in log and os.path.basename(d).rsplit("-", 1)[-1] not in log]


def unlisted_lean_files(cfg, repo):
    """Project .lean files on disk that are not in `lean_files`. A file nobody listed is invisible
    to the token scan, the scope computation, the report and the sign-off bundle."""
    root = (cfg.get("sweep") or {}).get("module", "").split(".")[0]
    if not root:
        return []
    on_disk = set(glob.glob(os.path.join(repo, root, "**", "*.lean"), recursive=True))
    if os.path.exists(os.path.join(repo, root + ".lean")):
        on_disk.add(os.path.join(repo, root + ".lean"))
    listed = {os.path.join(repo, f) for f in cfg["lean_files"]}
    return sorted(os.path.relpath(p, repo) for p in on_disk - listed)


def ever_approved(cfg):
    """Has an approval EVER been committed for this project? Decided from git history, not from
    whether the file is there now: moving the file aside (as re-approval does) must not turn the
    freeze check into "not applicable"."""
    rel = os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json"),
                          project.AUDITS)
    r = subprocess.run(["git", "-C", project.AUDITS, "log", "--all", "--format=%h", "--", rel],
                       capture_output=True, text=True)
    return bool(r.stdout.strip()) or os.path.exists(os.path.join(project.AUDITS, rel))


def uncommitted(cfg):
    """Tracked changes in the Lean repository that a commit would change. Saving the tree baseline
    over them makes the next check fail with 'HEAD moved' once they are committed."""
    r = subprocess.run(["git", "-C", project.REPO, "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.strip()]


def run(name, cmd, results, waived=False, runner=None):
    print(f"\n{'=' * 78}\n$ {cmd}\n{'-' * 78}", flush=True)
    if runner is not None:
        rc, out = runner(cmd)
    else:
        r = subprocess.run(cmd, shell=True, cwd=project.REPO, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        rc, out = r.returncode, r.stdout
    sys.stdout.write(out)
    print(f"[exit {rc}]", flush=True)
    results.append((name, rc, waived))
    return rc


def gate(cfg, readonly, statements, branch, runner=None, hits=None, approved_ever=None,
         doc_hits=None, log_hits=None,
         dirty=None, unlisted=None):
    """The gate itself: [(name, exit code, waived)]. Every environment-dependent input can be
    supplied, so the selftest can drive each branch with stub commands."""
    P = cfg["name"]
    results = []
    print(f"\n$ git branch --show-current\n{branch}")
    results.append(("on the project's branch", 0 if branch == cfg["branch"] else 1, False))

    unlisted = unlisted_lean_files(cfg, project.REPO) if unlisted is None else unlisted
    for f in unlisted:
        print(f"UNLISTED {f}: a project file missing from lean_files")
    results.append(("every project .lean file is in lean_files", 1 if unlisted else 0, False))

    for i, c in enumerate(cfg["build_cmds"]):
        # never piped: `lake build X | tail` reports tail's exit code
        run(f"build {i + 1}: {c}", c, results, runner=runner)

    print(f"\n{'=' * 78}\n$ token scan over {len(cfg['lean_files'])} Lean files "
          f"(comments and literals ignored)\n{'-' * 78}")
    hits = scan(cfg["lean_files"], project.REPO) if hits is None else hits
    for label, hs in hits.items():
        kind = "HARD" if label in HARD or label == "MISSING FILE" else "review"
        for f, n, t in hs:
            print(f"{kind:6} {label}: {f}:{n}: {t}")
    sorry_like = sum(len(hits.get(k, [])) for k in SORRY_LIKE)
    other_hard = sum(len(v) for k, v in hits.items()
                     if (k in HARD or k == "MISSING FILE") and k not in SORRY_LIKE)
    print(f"[sorry/admit/sorryAx: {sorry_like}; other hard: {other_hard}; review: "
          f"{sum(len(hits.get(k, [])) for k in REVIEW)}]")
    results.append(("token scan: sorry/admit/sorryAx", 1 if sorry_like else 0, statements))
    results.append(("token scan: other hard tokens", 1 if other_hard else 0, False))
    docs = docstring_problems(cfg, project.REPO) if doc_hits is None else doc_hits
    for loc, msg in docs:
        print(f"  docstring  {loc}  {msg}")
    results.append(("docstrings: no placeholders, tex lines within the source", 1 if docs else 0, False))
    logp = run_log_problems(cfg, project.REPO) if log_hits is None else log_hits
    for msg in logp:
        print(f"  run log  {msg}")
    results.append(("RUN_LOG.md mentions every adjudicated round", 1 if logp else 0, False))

    run("axiom sweep", f"{PY} audits/axiom_sweep.py --project {P}", results, waived=statements,
        runner=runner)
    run("index check", f"{PY} audits/check_index.py --project {P}", results, runner=runner)
    # review only: arguments no proof uses (Batteries linter), listed for the adjudicator in
    # <ROUNDS-DIR>/UNUSED_ARGS.md; never fails the gate (an approved statement may keep the
    # paper's own idle hypothesis)
    run("unused arguments (review; written to UNUSED_ARGS.md)",
        f"{PY} audits/unused_args.py --project {P}" + ("" if readonly else " --write"), results,
        waived=True, runner=runner)
    rc = run("freeze check (approved statements unchanged)",
             f"{PY} audits/fingerprint.py --project {P} --check", results, runner=runner)
    if rc == 4:
        # exit 4 = no approval file. Before Checkpoint B that is the truth; after it -- decided from
        # git history, not from the file's presence -- it is a failure. Exit 2 is an error: RED.
        ever = ever_approved(cfg) if approved_ever is None else approved_ever
        results[-1] = (results[-1][0] + (" — MISSING: an approval existed and is gone" if ever
                                         else " — NOT APPLICABLE: nothing approved yet"), 4, not ever)
    green_so_far = all(r == 0 or w for _, r, w in results)
    if readonly or not green_so_far or statements:
        # The report's trust section says "Phase 0 green at commit X". It is only regenerated when
        # that is true. A statement round is not green in that sense (proofs are sorry).
        # In a statement round the report check is reported but waived: an index row the author
        # proposes to skip has no SKIPPED.md row yet, because that round's adjudicator is the one
        # who decides skips (and writes SKIPPED.md). A calibration run hit exactly this.
        run("report (check only)", f"{PY} audits/make_report.py --project {P} --check", results,
            waived=statements, runner=runner)
        if not readonly:
            print("\n(report NOT regenerated: " + ("statement round" if statements and green_so_far
                                                    else "the gate is red") + ")")
    else:
        run("report (regenerate)", f"{PY} audits/make_report.py --project {P}", results,
            runner=runner)
    if not readonly:
        dirty = uncommitted(cfg) if dirty is None else dirty
        if not all(r == 0 or w for _, r, w in results):
            print("\n(tree baseline NOT saved: the gate is red)")
        elif dirty:
            # Saving now, then committing, would make the adjudicator's tree check fail with
            # "HEAD moved". Commit first, then run Phase 0 again.
            print("\n(tree baseline NOT saved: uncommitted changes -- commit, then run phase0.py again)")
            for l in dirty[:10]:
                print("   ", l)
            results.append(("tree baseline saved (needs a committed tree)", 1, False))
        else:
            run("tree baseline saved", f"{PY} audits/tree_state.py --save", results, runner=runner)
    return results


def verdict(results):
    print(f"\n{'=' * 78}\nPHASE 0 RESULT (computed by phase0.py from the exit codes above)")
    red = 0
    for name, rc, waived in results:
        status = "ok" if rc == 0 else ("waived" if waived else "RED")
        red += status == "RED"
        print(f"  {status:7} {name}  [exit {rc}]")
    print(f"PHASE 0: {'GREEN' if red == 0 else f'RED ({red} check(s))'}")
    return 0 if red == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--readonly", action="store_true")
    ap.add_argument("--statements", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    print(f"# Phase 0 for project {cfg['name']} ({why}); mode: "
          f"{'read-only' if a.readonly else 'author'}{', statement round' if a.statements else ''}")
    br = subprocess.run(["git", "-C", project.REPO, "branch", "--show-current"],
                        capture_output=True, text=True).stdout.strip()
    return verdict(gate(cfg, a.readonly, a.statements, br))


# ---------------------------------------------------------------------------------------------
def selftest():
    import tempfile, shutil, io, contextlib
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    # --- the token scan: every HARD key must have a fixture line that hits it -------------------
    d = tempfile.mkdtemp()
    try:
        lines = {
            "sorry": "theorem u : 1 = 2 := by sorry",
            "admit": "theorem u2 : 1 = 2 := by admit",
            "sorryAx": "theorem u3 : 1 = 2 := sorryAx _ false",
            "native_decide / decide +native": "theorem v : True := by decide +native",
            "axiom declaration": "@[simp] noncomputable axiom bad : False",
            "debug option": "set_option debug.skipKernelTC true in",
            "implemented_by": "@[simp, implemented_by foo] def f : Nat := 0",
            "extern": "attribute [extern \"c_f\"] f",
            "unsafe": "unsafe def g : Nat := 0",
            "run_cmd/run_elab/run_meta": "run_cmd pure ()",
            "#eval / #exit": "#exit",
            "initialize": "initialize registerFoo",
            "Lean.ofReduceBool": "theorem w : True := Lean.ofReduceBool _ _ rfl",
        }
        say("every HARD token has a fixture line, and every fixture line a HARD token",
            set(lines) == set(HARD))
        lines = {k: v for k, v in lines.items() if k in HARD}
        prelude = ("-- a comment mentioning sorry and axiom foo is not code\n"
                   "/- block: native_decide, run_cmd\n   /- nested -/ sorry still inside the outer comment -/\n"
                   'def s : String := "/- not a comment opener, and sorry is not code"\n'
                   "def c : Char := '\"'\n"
                   "theorem h' (x' : Nat) : x' = x' := rfl\n"
                   "theorem sorry_free_name_sorryish : True := trivial\n"
                   "partial def loop : Nat → Nat := loop\n"
                   "macro \"x\" : term => `(1)\n")
        body = prelude + "\n".join(lines[k] for k in HARD) + "\n"
        open(os.path.join(d, "A.lean"), "w").write(body)
        h = scan(["A.lean", "Missing.lean"], d)
        for k in HARD:
            say(f"HARD token '{k}' is found", len(h[k]) >= 1)
        say("no fixture line goes unflagged (a token dropped from HARD is noticed)",
            all(any(t.startswith(lines[k][:20]) or lines[k][:20] in t for kk in HARD for _, _, t in h[kk])
                for k in lines))
        say("comments (line, block, nested) are ignored",
            all(n > 3 for k in ("sorry", "native_decide / decide +native", "run_cmd/run_elab/run_meta",
                                "axiom declaration") for _, n, _ in h[k]))
        say("a string containing '/-' does not hide the rest of the file (sorry after it found)",
            any(t.startswith("theorem u :") for _, _, t in h["sorry"]))
        say("'sorry' inside a string literal is not a hit",
            not any("not a comment opener" in t for _, _, t in h["sorry"]))
        say("a char literal '\"' does not open a string", len(h["sorry"]) == 1)
        say("a primed identifier is not a char literal", not any("h'" in t for _, _, t in h["sorry"]))
        say("an identifier containing 'sorry' is not a sorry",
            not any("sorryish" in t for _, _, t in h["sorry"]))
        say("partial def is review, not hard", len(h["partial def"]) == 1 and "partial def" in REVIEW)
        say("macro is review", len(h["macro/elab/syntax (non-local)"]) == 1)
        say("a missing Lean file is reported", bool(h.get("MISSING FILE")))
        say("strip_comments keeps line numbers", strip_comments("a\n/- x\ny -/\nb").count("\n") == 3)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # --- unlisted project files -----------------------------------------------------------------
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "T", "Sub"))
        for f in ("T.lean", "T/A.lean", "T/Sub/B.lean", "Other.lean"):
            open(os.path.join(d, f), "w").write("")
        c2 = {"sweep": {"mode": "import", "module": "T"}, "lean_files": ["T.lean", "T/A.lean"]}
        say("a project file missing from lean_files is found (nested too)",
            unlisted_lean_files(c2, d) == ["T/Sub/B.lean"])
        say("files outside the project root are not the project's",
            "Other.lean" not in unlisted_lean_files(c2, d))
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # --- the gate: stub every command and drive each branch ------------------------------------
    cfg = {"name": "T", "branch": "b", "build_cmds": ["BUILD"], "lean_files": [], "rounds_dir": "x"}
    none = {k: [] for k in list(HARD) + list(REVIEW)}

    def G(codes=None, readonly=False, statements=False, branch="b", hits=None, ever=False,
          dirty=(), unlisted=(), docs=(), logp=()):
        codes = codes or {}
        ran = []

        def runner(cmd):
            ran.append(cmd)
            for key, rc in codes.items():
                if key in cmd:
                    return rc, ""
            return 0, ""
        with contextlib.redirect_stdout(io.StringIO()):
            res = gate(cfg, readonly, statements, branch, runner=runner,
                       hits=hits if hits is not None else none, approved_ever=ever,
                       doc_hits=list(docs), log_hits=list(logp),
                       dirty=list(dirty), unlisted=list(unlisted))
            rc = verdict(res)
        return rc, res, ran

    rc, res, ran = G()
    say("all green -> exit 0, report regenerated, baseline saved",
        rc == 0 and any("make_report" in c and "--check" not in c for c in ran)
        and any("tree_state.py --save" in c for c in ran))
    say("build failing -> RED", G({"BUILD": 1})[0] == 1)
    say("wrong branch -> RED", G(branch="other")[0] == 1)
    say("an unlisted project file -> RED", G(unlisted=["T/New.lean"])[0] == 1)
    say("axiom sweep failing -> RED", G({"axiom_sweep": 1})[0] == 1)
    say("a docstring placeholder or stale tex line -> RED", G(docs=[("A.lean:3", "placeholder")])[0] == 1)
    say("a round missing from RUN_LOG.md -> RED", G(logp=["RUN_LOG.md does not mention R"])[0] == 1)
    import tempfile as _tf, shutil as _sh
    _d = _tf.mkdtemp()
    try:
        open(os.path.join(_d, "p.tex"), "w").write("x\n" * 100)
        open(os.path.join(_d, "A.lean"), "w").write(
            "/-- Observation 1.? says so; see tex l.50 and tex 99--101 and l.~140, tex lines 10-150, p.tex:160. -/\n"
            "theorem t : True := trivial\n"
            "/-! TODO fill -/\n-- ?? in a line comment is not a docstring\n/-- clean, tex l.12 -/\ndef d := 0\n")
        dp = docstring_problems({"lean_files": ["A.lean"], "source_pdf": os.path.join(_d, "p.tex")}, _d)
        say("docstring check: placeholders and tex lines past the source are found, valid lines are not",
            any("1.?" in m for _, m in dp) and any("TODO" in m for _, m in dp)
            and any("l.~140" in m for _, m in dp) and any("101" in m for _, m in dp)
            and any("lines 10-150" in m for _, m in dp) and any(".tex:160" in m for _, m in dp)
            and not any("l.50" in m or "l.12" in m for _, m in dp) and not any("??" in m for _, m in dp))
        os.makedirs(os.path.join(_d, "rr", "2026-01-01-aaaaaaa")); os.makedirs(os.path.join(_d, "rr", "2026-01-02-bbbbbbb"))
        for _n in ("2026-01-01-aaaaaaa", "2026-01-02-bbbbbbb"):
            open(os.path.join(_d, "rr", _n, "ADOPTED.md"), "w").write("x")
        open(os.path.join(_d, "rr", "RUN_LOG.md"), "w").write("## Rounds\n- 2026-01-01-aaaaaaa: done\n")
        _saved = project.REPO; project.REPO = _d
        try:
            lp = run_log_problems({"rounds_dir": "rr"}, _d)
        finally:
            project.REPO = _saved
        say("a round with ADOPTED.md that RUN_LOG.md never mentions is found", lp and "bbbbbbb" in lp[0] and len(lp) == 1)
    finally:
        _sh.rmtree(_d, ignore_errors=True)
    say("the unused-argument list runs and never fails the gate",
        G({"unused_args": 1})[0] == 0 and any("unused_args.py" in c for c in G()[2]))
    say("axiom sweep failing in a statement round -> waived", G({"axiom_sweep": 1}, statements=True)[0] == 0)
    sh = dict(none, sorry=[("A", 1, "sorry")])
    say("a sorry -> RED", G(hits=sh)[0] == 1)
    say("a sorry in a statement round -> waived", G(hits=sh, statements=True)[0] == 0)
    oh = dict(none, **{"extern": [("A", 1, "extern")]})
    say("another hard token in a statement round is NOT waived", G(hits=oh, statements=True)[0] == 1)
    say("index check failing -> RED", G({"check_index": 1})[0] == 1)
    say("freeze drift (exit 1) -> RED", G({"fingerprint": 1})[0] == 1)
    say("freeze check error (exit 2) -> RED, never 'not applicable'", G({"fingerprint": 2})[0] == 1)
    say("no approval yet (exit 4), never approved -> waived", G({"fingerprint": 4})[0] == 0)
    say("approval file gone (exit 4) after an approval existed -> RED",
        G({"fingerprint": 4}, ever=True)[0] == 1)
    say("report check failing -> RED", G({"make_report": 1})[0] == 1)
    say("report check failing in a statement round -> waived (skips are decided by that round)",
        G({"make_report": 1}, statements=True)[0] == 0)
    rc, res, ran = G({"BUILD": 1})
    say("red gate -> report only checked, baseline NOT saved",
        any("make_report" in c and "--check" in c for c in ran)
        and not any("tree_state.py --save" in c for c in ran))
    rc, res, ran = G(readonly=True)
    say("read-only -> no report regeneration, no baseline, nothing written",
        rc == 0 and not any(("make_report" in c and "--check" not in c) or "tree_state" in c for c in ran))
    rc, res, ran = G(statements=True)
    say("statement round -> report only checked", not any("make_report" in c and "--check" not in c for c in ran))
    rc, res, ran = G(dirty=["M T/A.lean"])
    say("uncommitted changes -> baseline NOT saved and the gate is RED",
        rc == 1 and not any("tree_state.py --save" in c for c in ran))
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

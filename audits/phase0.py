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
# While a `leave <decl> unproved` line is active (decisions.unproved), the axiom sweep accepts the
# sorryAx of a compiler-generated auxiliary (`X.eq_1`, `X.proof_2`, …: no source range) of an exempt
# X. A project metaprogram could manufacture a rangeless declaration under such a name, so these are
# RED then (author and read-only); with no leave line they are what they always were.
META = {
    "elab/macro definition": rf"^\s*{ATTRS}{MODS}(?:elab|elab_rules|macro|macro_rules)\b",
    "elaborator attribute": r"@\[[^\]]*\b(?:command_elab|term_elab|tactic|macro)\b",
    "addDecl/addAndCompile": r"\b(?:addDecl|addAndCompile)\b",
}
META_RED = ("a metaprogram in the project's Lean while a 'leave <decl> unproved' line is active: it could "
            "manufacture a declaration with no source range under a compiler-generated name, which the "
            "axiom sweep would accept as an exempt result's auxiliary; remove it (or prove the results and "
            "drop their leave lines)")


def strip_comments(text, literals=False):
    """Remove `--` line comments and (nested) `/- -/` block comments, keeping line numbers.

    String and character literals are skipped as literals: a string containing "/-" used to open a
    block comment that never closed, hiding the rest of the file -- a `sorry` after it scanned
    clean. Literal CONTENT is blanked too, so "sorry" inside a string is not a hit (`literals`: kept).
    """
    out, i, depth, n = [], 0, 0, len(text)

    def keep(c):
        out.append(c if c == "\n" or literals else " ")

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
                out.append(m.group(0) if literals else "'" + " " * (len(m.group(0)) - 2) + "'")
                i += len(m.group(0)); continue
        if text.startswith("/-", i):
            depth += 1; out.append("  "); i += 2; continue
        if depth and text.startswith("-/", i):
            depth -= 1; out.append("  "); i += 2; continue
        c = text[i]
        out.append(c if depth == 0 or c == "\n" else " ")
        i += 1
    return "".join(out)


def scan(files, repo, pats=None):
    """{label: [(file, line, text)]} for HARD and REVIEW hits (or those of `pats`), comments and
    literals ignored."""
    pats = {**HARD, **REVIEW} if pats is None else pats
    hits = {k: [] for k in pats}
    for f in files:
        p = os.path.join(repo, f)
        if not os.path.exists(p):
            hits.setdefault("MISSING FILE", []).append((f, 0, "listed in config, not on disk"))
            continue
        raw = open(p, encoding="utf-8").read()
        code = strip_comments(raw).splitlines()
        rawl = raw.splitlines()
        for n, line in enumerate(code, 1):
            for label, pat in pats.items():
                if re.search(pat, line):
                    hits[label].append((f, n, rawl[n - 1].strip()[:120]))
    return hits


DECL_KW = (r"theorem|lemma|def|abbrev|instance|example|structure|class|inductive|opaque|axiom")
# a declaration line may begin with `set_option <opt> <val> in` / `open <names> in` (any number)
IN_PREFIX = r"(?:(?:set_option\s+\S+\s+\S+|open\s+[^\n]*?)\s+in\s+)*"
DECL_RE = re.compile(rf"^\s*{IN_PREFIX}{ATTRS}{MODS}(?:{DECL_KW})\b\s*([^\s:({{\[]*)")
SCOPE_RE = re.compile(r"^\s*(?:noncomputable\s+)?(namespace|section|end|mutual)\b\s*([^\s]*)")


def decl_locator(files, repo):
    """f(file, line) -> the full name of the declaration whose text holds that line (None outside
    every named declaration). Read from the comment-free code: `namespace`/`section`/`end` scopes
    and declaration headers; an anonymous `instance`/`example` or a scope line ends the previous
    declaration. Used only to exempt a `sorry` inside a declaration left unproved by a logged
    decision; the axiom sweep, over the kernel's terms, is what catches any other one."""
    table = {}
    for f in files:
        p = os.path.join(repo, f)
        if not os.path.exists(p):
            continue
        ns, cur, at = [], None, {}
        for n, line in enumerate(strip_comments(open(p, encoding="utf-8").read()).splitlines(), 1):
            sc = SCOPE_RE.match(line)
            if sc:
                kw, arg = sc.groups()
                if kw == "namespace":
                    ns.append(arg.split("."))
                elif kw in ("section", "mutual"):
                    ns.append([])
                elif ns:
                    ns.pop()
                cur = None
            else:
                m = DECL_RE.match(line)
                if m:
                    name = m.group(1)
                    cur = (None if not name else name[len("_root_."):] if name.startswith("_root_.")
                           else ".".join([x for part in ns for x in part] + [name]))
            at[n] = cur
        table[f] = at
    return lambda f, n: table.get(f, {}).get(n)


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
    return out + vacuous_doc_problems(cfg, repo)


def _mr():
    import make_report
    return make_report


def vacuous_doc_problems(cfg, repo):
    """[(file:line, problem)]: a declaration that an open VACUOUS.md row records as true only
    vacuously (the first project declaration backticked in the row's statement cell) whose
    docstring does not say so with the word "vacuous". The reader of the Lean must see it there,
    not only in the record (two test audits: a vacuous lemma's docstring never said it). A
    docstring is not a statement change: the fingerprints, and so the approval, are unaffected."""
    if not cfg.get("rounds_dir"):
        return []
    vp = os.path.join(repo, cfg["rounds_dir"], "VACUOUS.md")
    if not os.path.exists(vp):
        return []
    import decisions
    texts = {}
    for rel in cfg.get("lean_files", []):
        f = os.path.join(repo, rel)
        if os.path.exists(f):
            texts[rel] = open(f, encoding="utf-8").read()
    out = []
    for header, cells in decisions.table_rows(open(vp, encoding="utf-8").read()):
        i = decisions._idx(header, "statement")
        if i is None or i >= len(cells):
            continue
        if "status" in header and decisions.is_repaired(cells[header.index("status")]):
            continue
        for nm in re.findall(r"`([A-Za-z_][\w'.]*)`", cells[i]):
            short = nm.rsplit(".", 1)[-1]
            # review of fix-mini2 L5: comment-masked text (a commented-out copy is no declaration),
            # every file's declaration of the name (no first-file pick), and the docstring
            # immediately before it (an earlier declaration's docstring behind a plain comment is not)
            hits = [(rel, line) for rel, t in texts.items() for line in _mr().decl_hits(nm, t)]
            if not hits:
                continue
            for rel, line in hits:
                pre = "\n".join(texts[rel].splitlines()[:line - 1])
                pre = re.sub(r"(?:\n[ \t]*@\[[^\]\n]*\][ \t]*)+\s*$", "", pre).rstrip()
                doc = re.search(r"/--((?:(?!/-|-/).)*)-/$", pre, re.S)
                if not (doc and re.search(r"vacuous", doc.group(1), re.I)):
                    out.append((f"{rel}:{line}",
                                f"`{short}` is recorded in VACUOUS.md (row {cells[0]}) as true only vacuously, but its "
                                f"docstring does not say so: add a sentence with the word \"vacuous\" and why (e.g. "
                                f"\"True only vacuously: its hypothesis never holds, see ...\"); a docstring is not a "
                                f"statement change"))
            break
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


SEEN_DISCLOSED = []   # DISCLOSED[...] lines the gate's steps printed (release mode), listed by verdict()
STEP_CODES = {}       # {step name: the one cause code its failure lines carry}, read by code_of()


def run(name, cmd, results, waived=False, runner=None):
    print(f"\n{'=' * 78}\n$ {cmd}\n{'-' * 78}", flush=True)
    if runner is not None:
        rc, out = runner(cmd)
    else:
        r = subprocess.run(cmd, shell=True, cwd=project.REPO, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        rc, out = r.returncode, r.stdout
    sys.stdout.write(out)
    SEEN_DISCLOSED.extend(l.strip() for l in out.splitlines() if l.lstrip().startswith("DISCLOSED["))
    # a step whose every failure line carries one and the same cause code is RED under that code
    # (an index check failing only on a dead PAPER_DEFECTS witness is RED[dead-witness], not RED[index])
    import stops
    codes = {c["code"] for c in stops.causes(out)}
    if rc and len(codes) == 1 and codes <= set(project.CAUSES):
        STEP_CODES[name] = codes.pop()
    print(f"[exit {rc}]", flush=True)
    results.append((name, rc, waived))
    return rc


def gate(cfg, readonly, statements, branch, runner=None, hits=None, approved_ever=None,
         doc_hits=None, log_hits=None,
         dirty=None, unlisted=None, dep_hits=None, unproved=None, decl_at=None, meta_hits=None, pending=None):
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
    # a non-goal result left unproved by a [DELEGATED] decision in the COMMITTED RUN_LOG.md
    # (decisions.unproved; RUN.md failure table, "your own work"): a sorry/admit inside it is a
    # NOTE, any other stays RED; a goal result named there is refused (it stays a stop)
    import decisions
    left = decisions.unproved(cfg) if unproved is None else unproved
    # B2 (U2 §3 H3): the pending state -- a declaration of a re-approval QUESTION the human has not answered
    # yet (decisions.pending_reapproval): its sorry is a NOTE until the answer; only --deliver refuses
    pend = set(decisions.pending_reapproval(cfg) if pending is None else pending)
    exempt, waiting = [], []
    if left["decls"] or pend:
        where = decl_locator(cfg["lean_files"], project.REPO) if decl_at is None else decl_at
        hits = dict(hits)
        for k in ("sorry", "admit"):
            keep = []
            for h in hits.get(k, []):
                w_ = where(h[0], h[1])
                (exempt if w_ in left["decls"] else waiting if w_ in pend else keep).append(h)
            hits[k] = keep
    # sweep M1: in author mode the Lean is the operator's own work, so a kernel-skipping token or an extra
    # axiom there is its to rewrite (hard-token-own, axiom-own: proof-wip), never the human's; in read-only
    # mode (the adjudicator) it appeared after the author's GREEN Phase 0 and stays a stop
    own = not readonly
    for label, hs in hits.items():
        kind = "HARD" if label in HARD or label == "MISSING FILE" else "review"
        for f, n, t in hs:
            print(f"{kind:6} {label}: {f}:{n}: {t}" if kind != "HARD" else
                  f"HARD[{'sorry' if label in SORRY_LIKE else 'hard-token-own' if own else 'hard-token'}] "
                  f"{label}: {f}:{n}: {t}")
    for f, n, t in exempt:
        print(f"NOTE[unproved] {f}:{n}: {t}  (left unproved by a logged [DELEGATED] decision: "
              f"stated, not proved)")
    for f, n, t in waiting:
        print(f"NOTE[reapproval] {f}:{n}: {t}  (pending: the re-approval QUESTION on this statement awaits the "
              f"human; the run goes on, only --deliver refuses)")
    for msg in left["problems"]:
        print(f"  unproved  {msg}")
    sorry_like = sum(len(hits.get(k, [])) for k in SORRY_LIKE)
    other_hard = sum(len(v) for k, v in hits.items()
                     if (k in HARD or k == "MISSING FILE") and k not in SORRY_LIKE)
    print(f"[sorry/admit/sorryAx: {sorry_like}; other hard: {other_hard}; review: "
          f"{sum(len(hits.get(k, [])) for k in REVIEW)}]")
    results.append(("token scan: sorry/admit/sorryAx", 1 if sorry_like else 0, statements))
    results.append(("token scan: other hard tokens", 1 if other_hard else 0, False))
    if own and other_hard:
        STEP_CODES["token scan: other hard tokens"] = "hard-token-own"
    results.append(("left unproved by a [DELEGATED] line: no goal result", 1 if left["goal"] else 0, False))
    if left["decls"] or left["goal"] or pend:
        meta = scan(cfg["lean_files"], project.REPO, META) if meta_hits is None else meta_hits
        nmeta = 0
        for label, hs in meta.items():
            for f, n, t in hs:
                nmeta += 1
                print(f"RED[unproved-meta] {label}: {f}:{n}: {t}  ({META_RED})")
        results.append(("token scan: metaprogram while a leave line is active", 1 if nmeta else 0, False))
    # release mode: a docstring or run-log finding is disclosed, not RED (project.RELEASE; the third
    # field "disclosed" lets the gate go on like a waiver, and verdict() prints it as disclosed)
    docs = docstring_problems(cfg, project.REPO) if doc_hits is None else doc_hits
    dsc = project.disclosed(cfg, "docstring") and "disclosed"
    for loc, msg in docs:
        print(f"DISCLOSED[docstring] {loc}  {msg}" if dsc else f"  docstring  {loc}  {msg}")
        if dsc:
            SEEN_DISCLOSED.append(f"DISCLOSED[docstring] {loc}  {msg}")
    results.append(("docstrings: no placeholders, tex lines within the source", 1 if docs else 0, dsc))
    logp = run_log_problems(cfg, project.REPO) if log_hits is None else log_hits
    dsc = project.disclosed(cfg, "run-log") and "disclosed"
    for msg in logp:
        print(f"DISCLOSED[run-log] {msg}" if dsc else f"  run log  {msg}")
        if dsc:
            SEEN_DISCLOSED.append(f"DISCLOSED[run-log] {msg}")
    results.append(("RUN_LOG.md mentions every adjudicated round", 1 if logp else 0, dsc))

    if run("axiom sweep", f"{PY} audits/axiom_sweep.py --project {P}", results, waived=statements,
           runner=runner) and own and STEP_CODES.get("axiom sweep", "axiom") in ("axiom", "hard-token"):
        STEP_CODES["axiom sweep"] = "axiom-own"
    # the index check (make_report's index half): its own step, never waived, also in a statement round.
    # --pending here and in the report step: a fault of an adjudicator-owned record is a
    # PENDING[adjudication] NOTE, not RED -- only the next adjudication (or a record correction) clears
    # it, and a RED Phase 0 would keep that adjudication from ever running (deadlock sweep D1-D3); its
    # commit (integrity.py --commit-adjudication) and project.py --deliver refuse while one remains
    run("index check", f"{PY} audits/make_report.py --check --index-only --pending --project {P}", results, runner=runner)
    # review only: arguments no proof uses (Batteries linter), listed for the adjudicator in
    # <ROUNDS-DIR>/UNUSED_ARGS.md; never fails the gate (an approved statement may keep the
    # paper's own idle hypothesis)
    run("unused arguments (review; written to UNUSED_ARGS.md)",
        f"{PY} audits/unused_args.py --project {P}" + ("" if readonly else " --write"), results,
        waived=True, runner=runner)
    # the dependency and assumption walks over the kernel's terms (U2 §2), in every round -- the
    # assumption walk reads types only, so a statement round has it too: written to DEPENDENCIES.json
    # (what each result assumes, which results the goals do not use); in read-only mode (the
    # adjudicator) compared with that file, which must match (review round 3). Never waived: a goal
    # result with no walk entry fails closed. A crash inside the walk is RED[tool-bug] (L3), a project
    # that does not build or a missing file RED[dependencies] (rerun).
    if readonly:
        run("dependencies (DEPENDENCIES.json matches the walk)",
            f"{PY} audits/dependencies.py --project {P} --compare", results, runner=runner)
    else:
        run("dependencies (written to DEPENDENCIES.json)",
            f"{PY} audits/dependencies.py --project {P} --write", results, runner=runner)
    # DEPENDENCIES.json must be what dependencies.py wrote for the Lean at its recorded commit (a
    # generated file edited by hand). It was an integrity FAIL; it is a document RED (RULINGS D5).
    import dependencies
    depp = dependencies.problems(cfg) if dep_hits is None else dep_hits
    for msg in depp:
        print(f"  dependencies  {msg}")
    results.append(("dependencies: DEPENDENCIES.json is the walk's output at its commit", 1 if depp else 0, False))
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
        run("report (check only)", f"{PY} audits/make_report.py --project {P} --check --pending", results,
            waived=statements, runner=runner)
        if not readonly:
            print("\n(report NOT regenerated: " + ("statement round" if statements and green_so_far
                                                    else "the gate is red") + ")")
    else:
        run("report (regenerate)", f"{PY} audits/make_report.py --project {P} --pending", results,
            runner=runner)
    if not readonly:
        dirty = uncommitted(cfg) if dirty is None else dirty
        # (PDF-AGENTS: the report step builds no PDF, so the release exception for a step RED only on its PDF is gone)
        blocking = [n for n, r, w in results if not (r == 0 or w)]
        if blocking:
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


# the cause code of each gate check (project.CAUSES), printed as RED[<code>]
PHASE0_CODES = [("build", "build"), ("token scan: sorry", "sorry"),
                ("token scan: metaprogram", "unproved-meta"), ("token scan", "hard-token"),
                ("axiom sweep", "axiom"), ("on the project's branch", "branch"), ("every project .lean", "unlisted"),
                ("docstrings", "docstring"), ("left unproved", "unproved-goal"), ("RUN_LOG.md", "run-log"), ("index check", "index"),
                ("unused arguments", "unused-args"), ("dependencies", "dependencies"), ("report", "report"),
                ("freeze check", "drift"),     # sweep L1: fingerprint's error or mixed output, never "unknown"
                ("tree baseline", "baseline")]


def code_of(name):
    if name in STEP_CODES:
        return STEP_CODES[name]
    return next((c for pre, c in PHASE0_CODES if name.startswith(pre)), "unknown")


def verdict(results):
    print(f"\n{'=' * 78}\nPHASE 0 RESULT (computed by phase0.py from the exit codes above)")
    red = 0
    for name, rc, waived in results:
        status = "ok" if rc == 0 else ("disclosed" if waived == "disclosed" else "waived" if waived else "RED")
        red += status == "RED"
        print(f"  {status + (f'[{code_of(name)}]' if status in ('RED', 'disclosed') else ''):7} {name}  [exit {rc}]")
    seen = list(dict.fromkeys(SEEN_DISCLOSED))
    if seen:
        print(f"DISCLOSED, not failures (release mode; record them: python3 audits/stops.py disclose --cmd "
              f"\"<the check that printed them>\"):")
        for l in seen:
            print(f"  {l}")
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

    NO_LEFT = {"decls": {}, "lines": {}, "goal": [], "problems": []}

    def G(codes=None, readonly=False, statements=False, branch="b", hits=None, ever=False,
          dirty=(), unlisted=(), docs=(), logp=(), deps=(), left=NO_LEFT, where=None, out=None, meta=None,
          mode=None, pending=()):
        codes = codes or {}
        ran = []
        del SEEN_DISCLOSED[:]; STEP_CODES.clear()

        def runner(cmd):
            ran.append(cmd)
            for key, rc in codes.items():
                if key in cmd:
                    return (rc, "") if isinstance(rc, int) else rc     # (exit, output) when a test needs the output
            return 0, ""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = gate(dict(cfg, mode=mode) if mode else cfg, readonly, statements, branch, runner=runner,
                       hits=hits if hits is not None else none, approved_ever=ever,
                       doc_hits=list(docs), log_hits=list(logp),
                       dirty=list(dirty), unlisted=list(unlisted), dep_hits=list(deps),
                       unproved=left, decl_at=where, meta_hits=meta if meta is not None else {k: [] for k in META},
                       pending=list(pending))
            rc = verdict(res)
        if out is not None:
            out.append(buf.getvalue())
        return rc, res, ran

    # S1 (release trial): a step whose failure lines all carry one code is RED under that code
    del SEEN_DISCLOSED[:]; STEP_CODES.clear()
    _rs = []
    with contextlib.redirect_stdout(io.StringIO()) as _b1:
        run("index check", "x", _rs, runner=lambda c: (1, "FAIL[dead-witness] PAPER_DEFECTS.md row 2: `sorry`\n"))
        run("report", "y", _rs, runner=lambda c: (1, "FAIL[dead-witness] a\nFAIL[report] b\n"))
        verdict(_rs)
    STEP_CODES.clear()
    say("S1: an index check failing only on a dead witness is RED[dead-witness]; mixed codes keep the step's",
        "RED[dead-witness] index check" in _b1.getvalue() and "RED[report] report" in _b1.getvalue())
    say("a hand-edited DEPENDENCIES.json -> RED[dependencies], also in a statement round and read-only",
        all(G(deps=["x"], statements=s_, readonly=r_)[0] == 1 for s_, r_ in ((False, False), (True, False), (False, True))))
    _dd = tempfile.mkdtemp()
    try:
        import json
        json.dump({"commit": "abc", "lean_sha256": "0" * 64, "unused": []}, open(os.path.join(_dd, "DEPENDENCIES.json"), "w"))
        import dependencies as _deps
        say("review 2 N4: a DEPENDENCIES.json that does not match the Lean files at its commit is a problem",
            any("does not match" in p_ for p_ in _deps.problems(cfg, _dd)))
    finally:
        shutil.rmtree(_dd, ignore_errors=True)
    rc, res, ran = G()
    say("all green -> exit 0, report regenerated, baseline saved",
        rc == 0 and any("make_report" in c and "--check" not in c for c in ran)
        and any("tree_state.py --save" in c for c in ran))
    say("build failing -> RED", G({"BUILD": 1})[0] == 1)
    say("wrong branch -> RED", G(branch="other")[0] == 1)
    say("an unlisted project file -> RED", G(unlisted=["T/New.lean"])[0] == 1)
    say("axiom sweep failing -> RED", G({"axiom_sweep": 1})[0] == 1)
    say("a docstring placeholder or stale tex line -> RED", G(docs=[("A.lean:3", "placeholder")])[0] == 1)
    _o = []
    _r = G(docs=[("A.lean:3", "placeholder")], logp=["RUN_LOG.md does not mention adjudicated round R"],
           mode="release", out=_o)
    say("release mode: a docstring or run-log finding is disclosed, the gate GREEN and the report regenerated; "
        "dev keeps it RED",
        _r[0] == 0 and "disclosed[docstring]" in _o[0] and "disclosed[run-log]" in _o[0]
        and "DISCLOSED[docstring] A.lean:3" in _o[0].split("PHASE 0 RESULT")[1]
        and any("make_report.py --project" in c and "--check" not in c for c in _r[2])
        and G(logp=["x"], mode="dev")[0] == 1)
    say("release mode: a sorry, a build failure and the freeze check stay RED beside a disclosed docstring",
        G(docs=[("A.lean:3", "p")], hits=dict(none, sorry=[("A.lean", 3, "sorry")]), mode="release")[0] == 1
        and G(docs=[("A.lean:3", "p")], codes={"BUILD": 1}, mode="release")[0] == 1
        and G(docs=[("A.lean:3", "p")], codes={"fingerprint.py": 1}, mode="release")[0] == 1)
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
        # mini2 audit: a declaration VACUOUS.md records needs a docstring saying it is vacuous
        os.makedirs(os.path.join(_d, "vr"))
        open(os.path.join(_d, "vr", "VACUOUS.md"), "w").write(
            "| # | statement | for which parameters | why | decision | found | status |\n|---|---|---|---|---|---|---|\n"
            "| 1 | Lemma 2.4(b), `lemma_2_4_b` at `B.lean:2` | all | never holds | keep | r | open |\n"
            "| 2 | Lemma 4.1, `lemma_4_1` | all | x | repaired | r | repaired in abc1234 |\n")
        _vb = "theorem lemma_4_1 : True := trivial\n"
        open(os.path.join(_d, "B.lean"), "w").write("/-- Lemma 2.4(b). -/\ntheorem lemma_2_4_b : True := trivial\n" + _vb)
        _vc = {"lean_files": ["B.lean"], "rounds_dir": "vr"}
        _v1 = vacuous_doc_problems(_vc, _d)
        _vd = docstring_problems(dict(_vc, source_pdf=""), _d)
        open(os.path.join(_d, "B.lean"), "w").write(
            "/-- Lemma 2.4(b). True only vacuously: the hypothesis never holds. -/\n@[simp]\ntheorem lemma_2_4_b : True := trivial\n" + _vb)
        _v2 = vacuous_doc_problems(_vc, _d)
        say("mini2-5: a declaration an open VACUOUS.md row names needs 'vacuous' in its docstring (a repaired row "
            "does not); the docstring check reports it",
            len(_v1) == 1 and "lemma_2_4_b" in _v1[0][1] and _v1[0][0] == "B.lean:2" and _v2 == []
            and any("VACUOUS.md" in m for _, m in _vd))
        # review of fix-mini2 L5: an earlier declaration's "vacuous" docstring behind a plain comment,
        # a commented-out copy, or a second file's declaration of the name do not satisfy the rule
        open(os.path.join(_d, "B.lean"), "w").write(
            "/-- True only vacuously. -/\ntheorem other : True := trivial\n/- a plain comment -/\n"
            "theorem lemma_2_4_b : True := trivial\n" + _vb)
        _v3 = vacuous_doc_problems(_vc, _d)
        open(os.path.join(_d, "B.lean"), "w").write(
            "/- old:\n/-- vacuous -/\ntheorem lemma_2_4_b : True := trivial\n-/\ntheorem lemma_2_4_b : True := trivial\n" + _vb)
        _v4 = vacuous_doc_problems(_vc, _d)
        open(os.path.join(_d, "B.lean"), "w").write(
            "/-- Lemma 2.4(b). True only vacuously. -/\ntheorem lemma_2_4_b : True := trivial\n" + _vb)
        open(os.path.join(_d, "C.lean"), "w").write("namespace C\ntheorem lemma_2_4_b : True := trivial\nend C\n")
        _v5 = vacuous_doc_problems(dict(_vc, lean_files=["C.lean", "B.lean"]), _d)
        say("review of fix-mini2 L5: the docstring must be the one right before the declaration (not an earlier "
            "one behind a plain comment); a commented-out copy is no declaration; every file's declaration of "
            "the name is checked, not the first file's",
            len(_v3) == 1 and _v3[0][0] == "B.lean:4" and len(_v4) == 1 and _v4[0][0] == "B.lean:5"
            and [x for x, _ in _v5] == ["C.lean:2"])
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
    say("U2 §2: the dependency and assumption walk runs in every round (statement rounds too: it reads types), "
        "writes outside read-only mode, compares in read-only mode, and a failure is RED in each (fails closed)",
        G({"dependencies": 1})[0] == 1 and any("dependencies.py" in c and "--write" in c for c in G()[2])
        and any("dependencies.py" in c and "--compare" in c for c in G(readonly=True)[2])
        and G({"dependencies": 1}, readonly=True)[0] == 1
        and any("dependencies.py" in c and "--write" in c for c in G(statements=True)[2])
        and any("dependencies.py" in c and "--compare" in c for c in G(statements=True, readonly=True)[2])
        and G({"dependencies": 1}, statements=True)[0] == 1)
    del SEEN_DISCLOSED[:]; STEP_CODES.clear()
    _rt = []
    with contextlib.redirect_stdout(io.StringIO()) as _b2:
        run("dependencies (written to DEPENDENCIES.json)", "x", _rt,
            runner=lambda c: (1, "RED[tool-bug] dependencies: not computed: the dependency walk did not run\n"))
        run("dependencies (DEPENDENCIES.json matches the walk)", "y", _rt,
            runner=lambda c: (1, "RED[dependencies] dependencies: not computed: the project does not build\n"))
        verdict(_rt)
    STEP_CODES.clear()
    say("L3: a crash inside the walk is RED[tool-bug] (the tool-bug key); a project that does not build, "
        "RED[dependencies] (rerun)",
        "RED[tool-bug] dependencies (written" in _b2.getvalue()
        and "RED[dependencies] dependencies (DEPENDENCIES.json matches" in _b2.getvalue())
    say("axiom sweep failing in a statement round -> waived", G({"axiom_sweep": 1}, statements=True)[0] == 0)
    sh = dict(none, sorry=[("A", 1, "sorry")])
    say("a sorry -> RED", G(hits=sh)[0] == 1)
    say("a sorry in a statement round -> waived", G(hits=sh, statements=True)[0] == 0)
    oh = dict(none, **{"extern": [("A", 1, "extern")]})
    say("another hard token in a statement round is NOT waived", G(hits=oh, statements=True)[0] == 1)
    _m1 = [[], [], [], []]
    G(hits=oh, out=_m1[0]); G(hits=oh, readonly=True, out=_m1[1])
    G({"axiom_sweep": 1}, out=_m1[2]); G({"axiom_sweep": 1}, readonly=True, out=_m1[3])
    say("sweep M1: a kernel-skipping token or an extra axiom in author mode is the operator's own work "
        "(hard-token-own, axiom-own: proof-wip, rewrite the proof); read-only it stays a stop (hard-token, axiom)",
        "HARD[hard-token-own] extern" in _m1[0][0] and "RED[hard-token-own]" in _m1[0][0]
        and "HARD[hard-token] extern" in _m1[1][0] and "RED[hard-token]" in _m1[1][0]
        and "RED[axiom-own] axiom sweep" in _m1[2][0] and "RED[axiom] axiom sweep" in _m1[3][0]
        and project.cause_class("hard-token-own") == project.cause_class("axiom-own") == "proof-wip"
        and not project.is_stop_cause("axiom-own") and project.is_stop_cause("axiom")
        and project.release_class("axiom-own") == "P")
    say("index check failing -> RED, also in a statement round",
        G({"--index-only": 1})[0] == 1 and G({"--index-only": 1}, statements=True)[0] == 1)
    say("freeze drift (exit 1) -> RED", G({"fingerprint": 1})[0] == 1)
    say("freeze check error (exit 2) -> RED, never 'not applicable'", G({"fingerprint": 2})[0] == 1)
    say("no approval yet (exit 4), never approved -> waived", G({"fingerprint": 4})[0] == 0)
    say("approval file gone (exit 4) after an approval existed -> RED",
        G({"fingerprint": 4}, ever=True)[0] == 1)
    say("report check failing -> RED", G({"make_report.py --project": 1})[0] == 1)
    say("report check failing in a statement round -> waived (skips are decided by that round)",
        G({"make_report.py --project": 1}, statements=True)[0] == 0)
    rc, res, ran = G({"BUILD": 1})
    say("red gate -> report only checked, baseline NOT saved",
        any("make_report.py --project" in c and "--check" in c for c in ran)
        and not any("tree_state.py --save" in c for c in ran))
    rc, res, ran = G(readonly=True)
    say("read-only -> no report regeneration, no baseline, nothing written",
        rc == 0 and not any(("make_report" in c and "--check" not in c) or "tree_state" in c for c in ran))
    _pd = [[c for c in G(readonly=r_)[2] if "make_report" in c] for r_ in (False, True)] + [
        [c for c in G({"BUILD": 1})[2] if "make_report" in c]]
    say("sweep D1-D3: Phase 0 runs the index check and the report (check or regenerate) with --pending, in author "
        "and read-only mode, so an adjudicator-owned record fault never keeps the adjudication from running",
        all(len(x) == 2 and all("--pending" in c.split() for c in x) for x in _pd))
    rc, res, ran = G(statements=True)
    say("statement round -> report only checked", not any("make_report" in c and "--check" not in c for c in ran))
    rc, res, ran = G(dirty=["M T/A.lean"])
    say("uncommitted changes -> baseline NOT saved and the gate is RED",
        rc == 1 and not any("tree_state.py --save" in c for c in ran))
    # --- a non-goal result left unproved by a logged [DELEGATED] decision (decisions.unproved) ----
    _d = _tf.mkdtemp()
    try:
        open(os.path.join(_d, "A.lean"), "w").write(
            "namespace N\n/-- doc -/\ntheorem lem_a : 1 = 2 := by\n  sorry\n"
            "@[simp]\nprivate lemma lem_b : 1 = 2 := sorry\n"
            "section S\ntheorem _root_.top : 1 = 2 := sorry\nend S\n"
            "namespace Inner.Deep\ndef d : Nat := 0\ninstance : Inhabited Nat := sorry\nend Inner.Deep\n"
            "end N\ntheorem after : True := trivial\n"
            "set_option maxHeartbeats 400000 in theorem other : 1 = 2 := sorry\n"
            "open Classical in\n@[simp] theorem other2 : 1 = 2 := sorry\n"
            "open Classical Nat in private theorem other3 : 1 = 2 := sorry\n")
        at = decl_locator(["A.lean"], _d)
        say("decl_locator: the declaration holding each line, full name through namespaces, sections, "
            "_root_ and attributes; none after an anonymous instance or a scope end",
            at("A.lean", 4) == "N.lem_a" and at("A.lean", 6) == "N.lem_b" and at("A.lean", 8) == "top"
            and at("A.lean", 11) == "N.Inner.Deep.d" and at("A.lean", 12) is None
            and at("A.lean", 15) == "after" and at("A.lean", 13) is None)
        say("decl_locator: a `set_option … in` / `open … in` prefix on the declaration line starts that "
            "declaration (its sorry is not the one above's)",
            at("A.lean", 16) == "other" and at("A.lean", 18) == "other2" and at("A.lean", 19) == "other3")
    finally:
        _sh.rmtree(_d, ignore_errors=True)
    TAG = "[DELEGATED 2026-10-20, operator under hands-off (intake); reversal: re-prove]"
    left = {"decls": {"N.lem_a": TAG}, "lines": {}, "goal": [], "problems": []}
    two = dict(none, sorry=[("A.lean", 4, "sorry"), ("A.lean", 6, "lemma lem_b : 1 = 2 := sorry")])
    where = lambda f, n: {4: "N.lem_a", 6: "N.lem_b"}.get(n)
    out = []
    say("a sorry inside a declaration left unproved by a logged decision -> NOTE[unproved], not RED",
        G(hits=dict(none, sorry=[("A.lean", 4, "sorry")]), left=left, where=where, out=out)[0] == 0
        and "NOTE[unproved] A.lean:4" in out[0])
    rc, res, _ = G(hits=two, left=left, where=where)
    say("a sorry in a declaration no logged decision names stays RED[sorry]",
        rc == 1 and any(n_.startswith("token scan: sorry") and r_ == 1 for n_, r_, _w in res))
    say("an admit inside it is exempt too; sorryAx written out is not",
        G(hits=dict(none, admit=[("A.lean", 4, "admit")]), left=left, where=where)[0] == 0
        and G(hits=dict(none, sorryAx=[("A.lean", 4, "sorryAx")]), left=left, where=where)[0] == 1)
    # B2 (U2 §3 H3): the pending state -- a statements-only refuted statement whose re-approval QUESTION is
    # open does not hang the run: its sorry is a NOTE in author and read-only Phase 0 (the stops' closer)
    out = []
    one = dict(none, sorry=[("A.lean", 4, "sorry")])
    say("B2: a sorry inside a declaration of an open re-approval QUESTION -> NOTE[reapproval], not RED, also "
        "read-only; with no question it is RED[sorry]; a sorry elsewhere stays RED",
        G(hits=one, where=where, pending=["N.lem_a"], out=out)[0] == 0 and "NOTE[reapproval] A.lean:4" in out[0]
        and G(hits=one, where=where, pending=["N.lem_a"], readonly=True)[0] == 0
        and G(hits=one, where=where)[0] == 1 and G(hits=two, where=where, pending=["N.lem_a"])[0] == 1)
    goal = {"decls": {}, "lines": {}, "goal": ["N.goal"], "problems": ["N.goal is a goal result"]}
    rc, res, _ = G(left=goal)
    say("a goal result named in a 'leave <decl> unproved' line -> RED[unproved-goal] (a stop class), "
        "also in a statement round",
        rc == 1 and G(left=goal, statements=True)[0] == 1
        and any(code_of(n_) == "unproved-goal" and r_ == 1 for n_, r_, _w in res)
        and project.is_stop_cause("unproved-goal") and not project.is_stop_cause("unproved"))
    # re-check of Q1 (b), MED-A: a metaprogram could manufacture a rangeless "auxiliary" of an exempt
    # result (the review's `elab "gen_dep"` + addDecl of `X.eq_7`): RED while a leave line is active
    _d = _tf.mkdtemp()
    try:
        open(os.path.join(_d, "M.lean"), "w").write(
            "open Lean Elab Command in\nelab \"gen_dep\" : command => liftCoreM do\n"
            "  addDecl (.thmDecl { name := `N.lem_a.eq_7, levelParams := [], type := mkConst ``True, "
            "value := mkConst ``True.intro })\n"
            "@[command_elab gen] def genElab : CommandElab := fun _ => pure ()\n"
            "local macro \"m\" : term => `(1)\n"
            "def useIt : CoreM Unit := addAndCompile default\n"
            "-- addDecl in a comment\ntheorem t : True := trivial\nnotation \"⊤⊤\" => True\n")
        mh = scan(["M.lean"], _d, META)
    finally:
        _sh.rmtree(_d, ignore_errors=True)
    say("metaprogram scan: elab, an elaborator attribute, a local macro, addDecl and addAndCompile found; "
        "a comment, a theorem and a notation not",
        [n for _, n, _t in mh["elab/macro definition"]] == [2, 5]
        and [n for _, n, _t in mh["elaborator attribute"]] == [4]
        and [n for _, n, _t in mh["addDecl/addAndCompile"]] == [3, 6])
    rc, res, _ = G(left=left, meta=mh, out=out)
    say("a metaprogram while a leave line is active -> RED[unproved-meta], with the reason, also read-only",
        rc == 1 and G(left=left, meta=mh, readonly=True)[0] == 1
        and any(code_of(n_) == "unproved-meta" and r_ == 1 for n_, r_, _w in res)
        and "RED[unproved-meta] addDecl/addAndCompile" in out[-1] and "manufacture a declaration" in out[-1]
        and not project.is_stop_cause("unproved-meta"))
    say("... and with no leave line the same metaprogram changes nothing (not even checked)",
        G(meta=mh)[0] == 0 and not any(n_.startswith("token scan: metaprogram") for n_, _r, _w in G(meta=mh)[1]))
    say("... a leave line and no metaprogram -> green",
        G(left=left, meta={k: [] for k in META})[0] == 0)
    inv = {"decls": {}, "lines": {}, "goal": [], "problems": ["N.lem_a: ... the level is 'involved'"]}
    say("under the involved level a logged line exempts nothing: the sorry stays RED",
        G(hits=dict(none, sorry=[("A.lean", 4, "sorry")]), left=inv, where=where)[0] == 1)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

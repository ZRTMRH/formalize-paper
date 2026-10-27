#!/usr/bin/env python3
"""Write a round's TARGET.json mechanically: what each lane must examine.

WHY THIS EXISTS.  Step 3 used to tell the session launching the lanes to "derive the scope
yourself" from `git diff`, plus "every numbered result whose covering set they touch". In the
one-conversation mode (RUN.md) that session is the AUTHOR, and choosing what gets examined is
exactly the judgement the author must not make: an author that leaves its shakiest lemma out of
scope has audited nothing, and every lane will truthfully report full coverage of what it was
given. So the scope is now computed, and the author's only job is to pass it on verbatim.

WHAT IS IN SCOPE.
  diff round (default):
    1. every declaration whose text changed between <PREV> and HEAD, or that is new;
    2. every declaration whose MEANING depends on one in (1) or (2), transitively:
       - a theorem/lemma's meaning is its docstring + statement (the text before its top-level
         `:=`); its proof is not meaning, because changing a proof cannot change what is proved;
       - any other declaration's meaning (def, structure, instance, ...) is its whole text;
       - X depends on Y if Y's name occurs as a token in X's meaning.
       A changed definition therefore pulls in every statement written in terms of it, which is
       what keeps a Pass on such a statement from silently going stale.
    3. for the paper-faithfulness lane: every index row citing a declaration in (1)-(2), plus
       every index row whose text changed.
  full round (--full):  every declaration in the project's Lean files, and every index row.

Declaration lanes get fully qualified names; the paper-faithfulness lane gets index-row labels
("Theorem 1.1"). Unnamed declarations (`instance : Foo`, `example`) cannot be named in a verdict,
so they are listed on stderr instead and the round's lanes see them only through the file.

THE MATCHING IS TEXTUAL, and errs large on purpose: a short name like `foo` occurring in an
unrelated comment pulls a declaration in. A scope that is too big costs tokens; one that is too
small costs the audit. Declarations are recognised by keyword at column 0 (Mathlib style).

  python3 audits/scope.py --round 2026-10-11-abc1234def5            # writes TARGET.json there
  python3 audits/scope.py --round 2026-10-11-full-abc1234def5 --full
  python3 audits/scope.py --selftest
"""
import argparse, json, os, re, subprocess, sys, tempfile, shutil

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

KW = (r"theorem|lemma|def|abbrev|structure|inductive|class\s+inductive|class|instance|opaque|"
      r"axiom|example|irreducible_def")
MODS = r"(?:(?:private|protected|noncomputable|partial|unsafe|nonrec|scoped|local)\s+)*"
ATTRS = r"(?:@\[[^\]]*\]\s*)*"
HEADER = re.compile(rf"^{ATTRS}{MODS}({KW})\b", re.M)
SCOPE_CMD = re.compile(r"^(namespace|section|end|mutual)\b[ \t]*([^\s]*)", re.M)
IDENT = r"[^\W\d][\w'!?₀-₉ₐ-ₜ]*(?:\.[^\W\d][\w'!?₀-₉ₐ-ₜ]*)*"
TOKEN = re.compile(IDENT)
INDEX_ROW = re.compile(rf"^\|\s*((?:{project.RESULT_KINDS_RE})\s[^|]*?)\s*\|\s*(.*?)\s*\|\s*$", re.M)
STATEMENT_KINDS = {"theorem", "lemma"}

# Lane name -> what its scope unit is.
RESULT_LANES = {"paper-faithfulness", "literature-match"}
# Which lanes each kind of round runs. Fixed here, not chosen per call: a caller that could pass a
# lane list could quietly drop the lane that would have caught it.
CORRECTNESS = ["substantiveness", "correspondence", "paper-faithfulness", "non-vacuity"]
STATEMENT_LANES = ["correspondence", "paper-faithfulness", "non-vacuity"]


def lanes_for(kind, cfg):
    if kind == "statements":
        return list(STATEMENT_LANES)
    if kind == "full":
        return [l for l in CORRECTNESS + [x for x in cfg["lanes"] if x not in CORRECTNESS]
                if l in CORRECTNESS or l in cfg["lanes"]]
    return list(cfg["lanes"])


def _decl_name(kind, after):
    """The declared name from the text following the keyword, or "" if anonymous."""
    rest = after.lstrip()
    if kind == "instance":
        m = re.match(r"\(\s*priority\s*:=[^)]*\)\s*", rest)
        if m:
            rest = rest[m.end():]
    m = re.match(r"«[^»]+»|" + IDENT, rest)
    if not m or kind in ("example",):
        return ""
    return m.group(0)


def parse_decls(text):
    """{qualified name: (kind, short name, full text, meaning text)} for one Lean file.

    The STRUCTURE (keywords, namespaces, sections, mutual blocks) is read from the text with
    comments and literals blanked out -- a `namespace X` inside a doc comment used to open a
    namespace -- and the bodies are sliced from the raw text at the same positions (blanking is
    length-preserving). A declaration's text runs from the docstring directly above it to the next
    top-level item, so a changed docstring is a changed claim and the correspondence lane sees it.
    """
    from phase0 import strip_comments
    code = strip_comments(text)
    events = []
    for m in HEADER.finditer(code):
        kind = re.sub(r"\s+", " ", m.group(1))
        events.append((m.start(), "decl", (kind, _decl_name(kind, code[m.end():m.end() + 300]))))
    for m in SCOPE_CMD.finditer(code):
        events.append((m.start(), m.group(1), m.group(2)))
    events.sort(key=lambda e: e[0])
    # Where each event's text begins: a declaration begins at the docstring directly above its
    # header. The previous declaration ends THERE, not at the next header: otherwise a docstring
    # belonged to the declaration above it, and a docstring-only change was attributed to the
    # neighbour (2026-10-19, sparse-note: comments on Corollary 2.8 and Lemma 2.11 scoped
    # Theorems 2.7 and 2.10 instead).
    begins = [(_doc_start(text, code, pos, events[i - 1][0] + 1 if i else 0) if typ == "decl" else pos)
              for i, (pos, typ, _) in enumerate(events)]

    stack, out = [], {}
    prev_end = 0
    for i, (pos, typ, payload) in enumerate(events):
        if typ in ("namespace", "section", "mutual"):
            stack.append((typ, payload)); prev_end = text.find("\n", pos) + 1 or len(text)
        elif typ == "end":
            if stack:
                stack.pop()
            prev_end = text.find("\n", pos) + 1 or len(text)
        else:
            kind, short = payload
            nxt = begins[i + 1] if i + 1 < len(events) else len(text)
            start = max(begins[i], prev_end)
            body = text[start:nxt]
            prev_end = nxt
            if not short:
                out.setdefault("_unnamed", []).append((kind, (body.strip().splitlines() or [""])[0][:80]))
                continue
            short = short.strip("«»")
            if short.startswith("_root_."):
                qual = short[len("_root_."):]
            else:
                ns = ".".join(n for k, n in stack if k == "namespace" and n)
                qual = f"{ns}.{short}" if ns else short
            meaning = statement_part(body) if kind.split()[-1] in STATEMENT_KINDS else body
            # (kind, short name, normalised text, normalised meaning, raw text as written)
            out[qual] = (kind, short, normalise(body), normalise(meaning), body)
    return out


def _doc_start(text, code, pos, floor):
    """Start of the doc comment directly above the header at `pos` (only whitespace between them),
    or `pos` if there is none. `code` is `text` with comments blanked (same length); a span that
    is blank in `code` from `/--` to the header is a comment, not code."""
    j = pos
    while True:
        while j > floor and text[j - 1].isspace():
            j -= 1
        # a `-- line comment` between the docstring and the header does not detach the docstring
        ls = text.rfind("\n", floor, j) + 1
        if ls < j and text[max(ls, floor):j].lstrip().startswith("--") and ls > floor:
            j = ls
            continue
        break
    if not text.endswith("-/", floor, j):
        return pos
    k = text.rfind("/--", floor, j)
    if k == -1 or code[k:j].strip():
        return pos
    return k


def statement_part(body):
    """The text of a theorem before its top-level `:=` (or `|` match arms / `where`)."""
    from phase0 import strip_comments
    code = strip_comments(body)
    depth = 0
    for i, c in enumerate(code):
        if c in "([{⟨⦃":
            depth += 1
        elif c in ")]}⟩⦄":
            depth -= 1
        elif depth == 0 and code.startswith(":=", i):
            return body[:i]
        elif depth == 0 and c == "\n" and re.match(r"\n\s*(\||where\b)", code[i:]):
            return body[:i]
    return body


def normalise(s):
    return re.sub(r"\s+", " ", s).strip()


def git(repo, *a):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def decls_at(repo, rev, files):
    """All declarations in `files` at revision `rev` (None = the working tree)."""
    allds, unnamed = {}, []
    for f in files:
        if rev is None:
            p = os.path.join(repo, f)
            text = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        else:
            text = git(repo, "show", f"{rev}:{f}")
        if text is None:
            continue
        ds = parse_decls(text)
        unnamed += [(f,) + u for u in ds.pop("_unnamed", [])]
        allds.update(ds)
    return allds, unnamed


def short_names(qual):
    """Every suffix a declaration may be referred to by: A.B.c -> c, B.c, A.B.c."""
    parts = qual.split(".")
    return {".".join(parts[i:]) for i in range(len(parts))}


def token_names(text):
    """Every name a piece of text may refer to: each identifier and each of its dotted prefixes
    (`two.succ` may be a use of `two`)."""
    out = set()
    for t in TOKEN.findall(text):
        parts = t.split(".")
        out.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    return out


def dependents_closure(changed, decls):
    """`changed` plus everything whose meaning mentions something in the result, transitively."""
    tokens = {q: token_names(d[3]) for q, d in decls.items()}
    scope = set(changed)
    frontier = set(changed)
    while frontier:
        names = set().union(*(short_names(q) for q in frontier))
        frontier = {q for q in decls if q not in scope and tokens[q] & names}
        scope |= frontier
    return scope


def index_rows(text):
    """[(label, rest of the row)] from an index table."""
    return [(m.group(1).strip(), m.group(2)) for m in INDEX_ROW.finditer(text or "")]


def compute(repo, files, index_file, prev, full):
    head, unnamed = decls_at(repo, None, files)
    rows_head = index_rows(open(os.path.join(repo, index_file), encoding="utf-8").read()
                           if os.path.exists(os.path.join(repo, index_file)) else "")
    if full:
        return sorted(head), [r for r, _ in rows_head], unnamed, [], []
    old, _ = decls_at(repo, prev, files)
    changed = {q for q, d in head.items() if q not in old or old[q][2] != d[2]}
    removed = sorted(set(old) - set(head))
    scope = dependents_closure(changed, head)
    rows_old = dict(index_rows(git(repo, "show", f"{prev}:{index_file}") or ""))
    names = set().union(*(short_names(q) for q in scope)) if scope else set()
    rows = []
    for label, rest in rows_head:
        cited = set(re.findall(r"`([^`]+)`", rest))
        cited_tokens = set().union(*(token_names(c) for c in cited)) if cited else set()
        if cited_tokens & names or rows_old.get(label) != rest:
            rows.append(label)
    return sorted(scope), rows, unnamed, sorted(changed), removed


def fp_delta(prev, cur, auto=()):
    """Approvable declarations whose content fingerprint differs between two snapshots, or that
    are new. This is the semantic backstop for the textual matching above: it catches a change
    that reaches a statement through a path the token scan does not see (a notation, a coercion,
    an instance)."""
    return sorted(n for n, fp in cur.items() if n not in auto and prev.get(n) != fp)


def index_file_of(cfg):
    return cfg.get("index_file") or next(
        (f for f in cfg["lean_files"] if f.endswith("Main.lean")), cfg["lean_files"][0])


def previous_commit(cfg, repo, exclude=None):
    """The commit the last earlier round audited (by commit time), else the branch base."""
    rounds = [r for r in project.rounds(cfg) if os.path.basename(r) != exclude]
    if not rounds:
        return cfg["base_commit"]

    def ct(r):
        out = git(repo, "show", "-s", "--format=%ct", project.round_commit(r))
        return (int(out.strip()) if out and out.strip().isdigit() else 0, os.path.getmtime(r))
    return project.round_commit(sorted(rounds, key=ct)[-1])


def make_target(cfg, round_name, kind, repo, fps):
    """The TARGET.json document for a round: lanes and items, plus how it was made (`_meta`).
    `fps` is this commit's fingerprint table ({key: fp}, with `.auto`), or None to skip the
    fingerprint delta (selftests only)."""
    prev = None if kind in ("full", "statements") else previous_commit(cfg, repo, exclude=round_name)
    decls, rows, unnamed, changed, removed = compute(repo, cfg["lean_files"], index_file_of(cfg),
                                                     prev, kind != "diff")
    added = []
    if kind == "diff" and fps is not None:
        snap = None
        for r in project.rounds(cfg):
            f = os.path.join(r, "FINGERPRINTS.json")
            if project.round_commit(r) == prev and os.path.exists(f):
                snap = json.load(open(f))["fingerprints"]
        if snap is not None:
            added = sorted(set(fp_delta(snap, fps, getattr(fps, "auto", ()))) - set(decls))
            decls = sorted(set(decls) | set(added))
    lanes = lanes_for(kind, cfg)
    doc = {lane: (rows if lane in RESULT_LANES else decls) for lane in lanes}
    doc["_meta"] = {"kind": kind, "prev": prev, "commit": round_name and project.round_commit(round_name),
                    "fingerprint_added": added, "removed": removed}
    return doc, unnamed, changed


class FPs(dict):
    auto = ()


def lean_fps(cfg):
    import fingerprint
    fps = FPs(fingerprint.compute(cfg))
    fps.auto = set(fingerprint._AUTO)
    return fps


def target_items(doc):
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def preflight(cfg, repo, round_name, kind):
    """None, or why this round must not be scoped now."""
    if not round_name:
        return "--round is required (copy it from prompt.py 3's output)"
    if not project.ROUND_RE.match(round_name):
        return f"{round_name!r} is not a round directory name"
    if project.is_full_round(round_name) != (kind != "diff"):
        return "a round directory named ...-full-... is a full or statement round, and only it is"
    head = (git(repo, "rev-parse", "--short=11", "HEAD") or "").strip()
    rc_ = project.round_commit(round_name)
    if not head or not (head.startswith(rc_[:7]) or rc_.startswith(head[:7])):
        return f"round {round_name} is not cut from HEAD ({head})"
    dirty = git(repo, "status", "--porcelain", "--", *cfg["lean_files"])
    if dirty and dirty.strip():
        return ("uncommitted changes in the project's Lean files; the scope would describe a tree "
                "that is not the commit being audited:\n" + dirty)
    return None


def compare(recorded, doc):
    """[mismatch] between a recorded TARGET.json and a recomputed one."""
    bad = []
    if recorded.get("_meta", {}).get("prev") != doc["_meta"]["prev"]:
        bad.append(f"recorded base {recorded.get('_meta', {}).get('prev')} != recomputed {doc['_meta']['prev']}")
    rec, now = target_items(recorded), target_items(doc)
    if set(rec) != set(now):
        bad.append(f"lanes: recorded {sorted(rec)} != recomputed {sorted(now)}")
    for lane in set(rec) & set(now):
        miss = sorted(set(now[lane]) - set(rec[lane]))
        extra = sorted(set(rec[lane]) - set(now[lane]))
        if miss:
            bad.append(f"{lane}: {len(miss)} item(s) missing from TARGET.json, e.g. {miss[:3]}")
        if extra:
            bad.append(f"{lane}: {len(extra)} item(s) in TARGET.json not in the recomputed scope, e.g. {extra[:3]}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--round", required=False, help="round directory name, as printed by prompt.py 3")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="full-scope round")
    g.add_argument("--statements", action="store_true", help="statement round (full scope, 3 lanes)")
    ap.add_argument("--verify", action="store_true", help="recompute and compare with TARGET.json")
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    repo = project.REPO
    rd = os.path.join(repo, cfg["rounds_dir"], a.round or "")
    tp = os.path.join(rd, "TARGET.json")
    if a.verify:
        if not os.path.exists(tp):
            print(f"FAIL: no {tp}", file=sys.stderr); return 2
        kind = json.load(open(tp)).get("_meta", {}).get("kind")
    else:
        kind = "statements" if a.statements else "full" if a.full else "diff"
    why_not = preflight(cfg, repo, a.round, kind)
    if why_not:
        print(f"FAIL: {why_not}", file=sys.stderr); return 2
    head = (git(repo, "rev-parse", "--short=11", "HEAD") or "").strip()
    try:
        fps = lean_fps(cfg)
    except RuntimeError as e:
        print(f"FAIL: could not fingerprint the project (is it built? Phase 0 builds it):\n{e}",
              file=sys.stderr)
        return 2
    doc, unnamed, changed = make_target(cfg, a.round, kind, repo, fps)
    items = target_items(doc)
    meta = doc["_meta"]
    print(f"# project {cfg['name']} ({why}); {kind} round" + (f", diff {meta['prev']}..HEAD" if meta["prev"] else ""),
          file=sys.stderr)
    if kind == "diff":
        print(f"#   changed or new: {len(changed)}; added by fingerprint: {len(meta['fingerprint_added'])}; "
              f"removed: {len(meta['removed'])}", file=sys.stderr)
    for lane, its in items.items():
        print(f"#   {lane}: {len(its)} item(s)", file=sys.stderr)
    for f, k, line in unnamed:
        print(f"#   unnamed {k} in {f}, not nameable in a verdict: {line}", file=sys.stderr)

    if a.verify:
        bad = compare(json.load(open(tp)), doc)
        for x in bad:
            print(f"MISMATCH  {x}")
        print(f"scope verify: {'OK' if not bad else 'MISMATCH'}")
        return 1 if bad else 0
    if not any(items.values()):
        print("! empty scope: nothing changed since the last audited commit. Do not run lanes "
              "on it; an empty round reports full coverage of nothing.", file=sys.stderr)
        return 3
    if a.dry_run:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
        return 0
    if os.path.exists(tp):
        print(f"FAIL: {tp} already exists. A round's scope is written once.", file=sys.stderr)
        return 2
    os.makedirs(rd, exist_ok=True)
    json.dump(doc, open(tp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"commit": head, "fingerprints": dict(fps), "auto": sorted(fps.auto)},
              open(os.path.join(rd, "FINGERPRINTS.json"), "w"), indent=0)
    print(f"wrote {os.path.relpath(tp, repo)} and FINGERPRINTS.json")
    return 0


# ---------------------------------------------------------------------------------------------
def selftest():
    """Controls on throwaway git repos. Every case states what must happen."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    # --- the parser, on the constructs an independent audit showed it misread ------------------
    P = lambda t: {k for k in parse_decls(t) if k != "_unnamed"}
    check("_root_ inside a namespace is top-level",
          P("namespace N\ntheorem _root_.foo : True := trivial\nend N\n") == {"foo"})
    check("mutual ... end does not close the enclosing namespace",
          P("namespace N\nmutual\ndef a : Nat → Nat\n  | n => n\ndef b : Nat := 0\nend\n"
            "def after : Nat := 0\nend N\n") >= {"N.a", "N.b", "N.after"})
    check("instance (priority := …) name is read",
          "N.instFoo" in P("namespace N\ninstance (priority := 100) instFoo : Inhabited Nat := ⟨0⟩\nend N\n"))
    check("irreducible_def and scoped instance are declarations",
          P("namespace N\nirreducible_def k : Nat := 3\nscoped instance instBar : Inhabited Nat := ⟨1⟩\nend N\n")
          == {"N.k", "N.instBar"})
    check("a `namespace` inside a comment opens nothing",
          P("namespace N\n/-!\nnamespace X\n-/\ntheorem t : True := trivial\nend N\n") == {"N.t"})
    check("an anonymous instance is unnamed, not a declaration called `:`",
          parse_decls("instance : Inhabited Nat := ⟨0⟩\n").get("_unnamed"))
    uni = parse_decls("namespace N\ndef φ : Nat := 1\ntheorem uses : φ = 1 := rfl\nend N\n")
    check("unicode identifiers: φ is parsed, and a statement using φ depends on φ",
          "N.φ" in uni and "N.uses" in dependents_closure({"N.φ"}, uni))
    dot = parse_decls("namespace N\ndef two : Nat := 2\ntheorem three : two.succ = 3 := rfl\nend N\n")
    check("dotted use `two.succ` depends on `two`", "N.three" in dependents_closure({"N.two"}, dot))
    check("statement_part ignores := inside brackets (incl. ⦃⦄) and strings",
          statement_part('theorem t (h : ∀ x, (x := 1) = x) ⦃y := 2⦄ (s := ":= ") : True := by trivial')
          .rstrip().endswith(": True"))
    check("statement_part stops at a top-level `where`/`|`",
          "where" not in statement_part("def f : Nat → Nat\n  | 0 => 1\n  | n => n\n")
          and statement_part("def f : Nat → Nat\n  | 0 => 1\n").strip() == "def f : Nat → Nat")

    d = tempfile.mkdtemp(prefix="scope-selftest-")
    clock = [1_700_000_000]
    try:
        def run(*a):
            # every commit one hour after the previous, so commit-time order is never a tie
            clock[0] += 3600
            env = dict(os.environ, GIT_COMMITTER_DATE=f"{clock[0]} +0000",
                       GIT_AUTHOR_DATE=f"{clock[0]} +0000")
            subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, env=env)
        run("init", "-q"); run("config", "user.email", "t@t"); run("config", "user.name", "t")
        os.makedirs(os.path.join(d, "P"))
        v1 = {
            "P/Basic.lean": """namespace P

/-- A thing. -/
def thing (n : ℕ) : ℕ := n + 1

def other : ℕ := 3

theorem uses_thing_in_statement (n : ℕ) : thing n > n := by
  simp [thing]

theorem uses_thing_in_proof_only (n : ℕ) : n < n + 1 := by
  have := thing n
  omega

theorem unrelated : other = 3 := rfl

private theorem hidden_helper : other = 3 := rfl

namespace Inner
lemma deep (n : ℕ) : uses_thing_in_statement n = uses_thing_in_statement n := rfl
end Inner

end P
""",
            "P/Main.lean": """/-!
| Paper | Lean |
|---|---|
| Definition 1.1 | `P.thing` |
| Theorem 1.2 | `uses_thing_in_statement` |
| Theorem 1.3 | `P.unrelated` |
| Fact 1.4 | `P.Inner.deep` |
| Construction 1.5 | `P.other` |
-/
""",
        }
        for f, t in v1.items():
            open(os.path.join(d, f), "w").write(t)
        run("add", "."); run("commit", "-qm", "v1")
        base = git(d, "rev-parse", "HEAD").strip()
        files = list(v1)
        check("private declarations are parsed", "P.hidden_helper" in P(v1["P/Basic.lean"]))
        raw = parse_decls(v1["P/Basic.lean"])["P.thing"][4]
        check("raw text keeps the docstring and line breaks, and stops at the next declaration",
              raw.startswith("/-- A thing. -/\ndef thing") and "def other" not in raw)

        # regression (2026-10-19, sparse-note): a docstring belongs to the declaration BELOW it.
        # A docstring-only change of the second theorem used to change the first one's text.
        two = ("namespace Q\n\ntheorem first : 1 = 1 := by\n  rfl\n\n/-- Old words. -/\n"
               "theorem second : 2 = 2 := rfl\n\n/-- Third. -/\n@[simp] theorem third : 3 = 3 := rfl\n\nend Q\n")
        two_new = two.replace("/-- Old words. -/", "/-- New words,\nover two lines. -/")
        a0, a1 = parse_decls(two), parse_decls(two_new)
        check("a docstring is not part of the declaration above it",
              "Old words" not in a0["Q.first"][4] and a0["Q.second"][4].startswith("/-- Old words. -/")
              and a0["Q.third"][4].startswith("/-- Third. -/\n@[simp] theorem third"))
        cm = parse_decls("namespace Q\n\ntheorem first : 1 = 1 := rfl\n\n/-- Doc. -/\n-- a note\n"
                         "-- another\ntheorem second : 2 = 2 := rfl\n\nend Q\n")
        check("a `-- comment` between a docstring and its declaration does not detach it",
              cm["Q.second"][4].startswith("/-- Doc. -/") and "Doc." not in cm["Q.first"][4])
        check("a docstring-only change scopes the documented declaration, not its neighbour",
              sorted(q for q in a1 if a0.get(q, (0, 0, None))[2] != a1[q][2]) == ["Q.second"])

        decls, rows, *_ = compute(d, files, "P/Main.lean", base, False)
        check("unchanged tree gives an empty scope", decls == [] and rows == [])

        t = v1["P/Basic.lean"].replace("n + 1\n", "n + 2\n", 1)
        open(os.path.join(d, "P/Basic.lean"), "w").write(t)
        run("commit", "-qam", "v2")
        decls, rows, _, changed, _ = compute(d, files, "P/Main.lean", base, False)
        check("changed def is in scope", "P.thing" in decls)
        check("statement mentioning it is in scope", "P.uses_thing_in_statement" in decls)
        check("transitive dependent (nested namespace) is in scope", "P.Inner.deep" in decls)
        check("proof-only user is NOT in scope", "P.uses_thing_in_proof_only" not in decls)
        check("unrelated theorem is NOT in scope", "P.unrelated" not in decls)
        check("index rows citing scoped decls are in scope (incl. Fact)",
              {"Definition 1.1", "Theorem 1.2", "Fact 1.4"} <= set(rows))
        check("index row citing only unrelated decl is NOT in scope", "Theorem 1.3" not in rows)
        base2 = git(d, "rev-parse", "HEAD").strip()

        t2 = t.replace("  have := thing n\n  omega", "  omega")
        open(os.path.join(d, "P/Basic.lean"), "w").write(t2)
        run("commit", "-qam", "v3")
        decls, rows, *_ = compute(d, files, "P/Main.lean", base2, False)
        check("proof-only change: just that theorem", decls == ["P.uses_thing_in_proof_only"])
        base3 = git(d, "rev-parse", "HEAD").strip()

        t3 = t2.replace("/-- A thing. -/", "/-- A different thing. -/")
        open(os.path.join(d, "P/Basic.lean"), "w").write(t3)
        run("commit", "-qam", "v4")
        decls, *_ = compute(d, files, "P/Main.lean", base3, False)
        check("docstring change puts the declaration in scope", "P.thing" in decls)
        base4 = git(d, "rev-parse", "HEAD").strip()

        m = v1["P/Main.lean"].replace("`P.unrelated` |", "`P.unrelated` (corrected) |")
        open(os.path.join(d, "P/Main.lean"), "w").write(m)
        run("commit", "-qam", "v5")
        decls, rows, *_ = compute(d, files, "P/Main.lean", base4, False)
        check("edited index row is in scope", rows == ["Theorem 1.3"])

        open(os.path.join(d, "P/Basic.lean"), "a").write("\ntheorem brand_new : True := trivial\n")
        run("commit", "-qam", "v6")
        base5 = git(d, "rev-parse", "HEAD~1").strip()
        decls, *_ = compute(d, files, "P/Main.lean", base5, False)
        check("new declaration is in scope", "brand_new" in decls)

        decls, rows, *_ = compute(d, files, "P/Main.lean", git(d, "rev-parse", "HEAD").strip(), True)
        check("full scope: every named declaration",
              {"P.thing", "P.other", "P.uses_thing_in_statement", "P.uses_thing_in_proof_only",
               "P.unrelated", "P.Inner.deep", "P.hidden_helper"} <= set(decls))
        check("full scope: every index row, Construction included", len(rows) == 5)

        # --- the command-line paths: previous round, kinds, fingerprint delta, verify ----------
        head = git(d, "rev-parse", "--short=11", "HEAD").strip()
        h1 = git(d, "rev-parse", "--short=11", "HEAD~3").strip()   # older commit
        h2 = git(d, "rev-parse", "--short=11", "HEAD~1").strip()   # newer commit
        rdir = os.path.join(d, "rounds")
        # Adversarial names: by NAME the h1 round is newer (later date); by commit time h2 is.
        names = [f"2026-01-02-{h1}", f"2026-01-01-{h2}"]
        for n_ in names:
            os.makedirs(os.path.join(rdir, n_))
        cfg = {"name": "P", "lean_files": files, "rounds_dir": rdir, "base_commit": base,
               "lanes": ["correspondence", "paper-faithfulness", "prior-art"], "index_file": "P/Main.lean"}
        check("previous round = latest by COMMIT TIME, not by name", previous_commit(cfg, d) == h2)
        check("no rounds -> previous = the branch base",
              previous_commit(dict(cfg, rounds_dir=os.path.join(d, "none")), d) == base)
        check("kinds decide lanes: statements = the three statement lanes",
              lanes_for("statements", cfg) == STATEMENT_LANES)
        check("kinds decide lanes: full = every correctness lane plus the config's",
              set(lanes_for("full", cfg)) == set(CORRECTNESS) | {"prior-art"})
        check("kinds decide lanes: diff = the config's", lanes_for("diff", cfg) == cfg["lanes"])
        # fingerprint delta: snapshot in the previous round says P.other had another meaning
        json.dump({"fingerprints": {"P.other": "OLD", "P.thing": "T"}},
                  open(os.path.join(rdir, f"2026-01-01-{h2}", "FINGERPRINTS.json"), "w"))
        fps = FPs({"P.other": "NEW", "P.thing": "T", "P.thing.eq_1": "X"})
        fps.auto = {"P.thing.eq_1"}
        doc, _, _ = make_target(cfg, f"2026-01-02-{head}", "diff", d, fps)
        check("fingerprint delta adds a declaration the text scan did not change",
              "P.other" in doc["correspondence"] and doc["_meta"]["fingerprint_added"] == ["P.other"])
        check("auto-generated declarations are never added", "P.thing.eq_1" not in doc["correspondence"])
        check("TARGET records kind and base", doc["_meta"]["kind"] == "diff" and doc["_meta"]["prev"] == h2)
        check("result lane gets index rows, declaration lanes get declarations",
              all(" " in x for x in doc["paper-faithfulness"]) and "P.other" in doc["prior-art"])
        full, _, _ = make_target(cfg, f"2026-01-02-full-{head}", "full", d, None)
        check("full round: no base, every lane", full["_meta"]["prev"] is None
              and set(target_items(full)) == set(CORRECTNESS) | {"prior-art"})
        check("verify: identical documents agree", compare(doc, doc) == [])
        tampered = json.loads(json.dumps(doc))
        tampered["correspondence"] = tampered["correspondence"][1:]   # drop one item, any
        check("verify: an item removed from TARGET.json is a mismatch",
              any("missing" in x for x in compare(tampered, doc)))
        t2_ = json.loads(json.dumps(doc)); del t2_["prior-art"]
        check("verify: a lane removed from TARGET.json is a mismatch", any("lanes" in x for x in compare(t2_, doc)))
        t3_ = json.loads(json.dumps(doc)); t3_["_meta"]["prev"] = head
        check("verify: a different base is a mismatch", any("base" in x for x in compare(t3_, doc)))
        # preflight
        check("preflight: a round not cut from HEAD is refused",
              preflight(cfg, d, f"2026-01-02-{h1}", "diff") is not None)
        check("preflight: kind and round name must agree",
              preflight(cfg, d, f"2026-01-02-{head}", "full") is not None)
        check("preflight: a clean tree at HEAD is accepted", preflight(cfg, d, f"2026-01-02-{head}", "diff") is None)
        open(os.path.join(d, "P/Basic.lean"), "a").write("\n-- uncommitted\n")
        check("preflight: uncommitted Lean changes are refused",
              "uncommitted" in (preflight(cfg, d, f"2026-01-02-{head}", "diff") or ""))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

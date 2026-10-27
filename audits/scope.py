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
import argparse, glob, json, os, re, subprocess, sys, tempfile, shutil

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


def previous_commit(cfg, repo, exclude=None):
    """The commit the last earlier round audited (project.order_rounds: by Lean ancestry; a set-aside
    round is no round), else the branch base. Only a round scope.py scoped (its TARGET.json) is a
    base: an ADOPTED.md planted in a prompts directory must not make an unaudited commit the base
    (re-check of fix-mini1)."""
    rounds = [r for r in project.rounds(cfg, repo=repo) if os.path.basename(r) != exclude
              and os.path.exists(os.path.join(r, "TARGET.json"))]
    return project.round_commit(rounds[-1]) if rounds else cfg["base_commit"]


def make_target(cfg, round_name, kind, repo, fps):
    """The TARGET.json document for a round: lanes and items, plus how it was made (`_meta`).
    `fps` is this commit's fingerprint table ({key: fp}, with `.auto`), or None to skip the
    fingerprint delta (selftests only)."""
    prev = None if kind in ("full", "statements") else previous_commit(cfg, repo, exclude=round_name)
    decls, rows, unnamed, changed, removed = compute(repo, cfg["lean_files"], project.index_file(cfg),
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
    if "paper-faithfulness" in doc:
        f10 = refutation_scope(cfg, repo, round_name, kind, decls, rows)
        doc["paper-faithfulness"] = list(rows) + [i for i in f10 if i not in rows]
        doc["_meta"]["f10"] = {i: n for i, n in f10.items() if i.startswith("F10:")}
        # `row N`: a PAPER_DEFECTS.md `false` row's item, read off the record when the round was scoped (`--verify`
        # does not recompute it: the record grows after)
        # F13 (B6): every missing-theory hypothesis of RUN_LOG.md gets its item in every round (hypotheses.F13_ITEM:
        # a `yes` row needs a Pass on it); read off RUN_LOG.md when scoped, kept as recorded by `--verify`. B5: so
        # does every binder the walk flags as restating another result (hypotheses.FLAG_ITEM, its question)
        import hypotheses
        f13 = hypotheses.scheduled_items(cfg, os.path.join(repo, cfg["rounds_dir"]))
        doc["paper-faithfulness"] += [i for i in f13 if i not in doc["paper-faithfulness"]]
        doc["_meta"]["f13"] = f13
    return doc, unnamed, changed


def decl_refutations(decls):
    """{short name} of the refutations `not_<X>_as_printed` among the declarations `decls` ({qualified: ...})."""
    import make_report
    return {q.split(".")[-1] for q in decls if make_report.AS_PRINTED.fullmatch(q.split(".")[-1])}


def lane_only_refutations(cfg, repo, round_name):
    """{name: lane record} of each `not_<X>_as_printed` an earlier round's lane record names that is no declaration
    of the project at this commit (a probe file, a misspelling): no F10/F12 item is scheduled for it (bench2), the
    operator is told (a real refutation is added to the Lean under that name)."""
    import make_report
    head, _ = decls_at(repo, None, cfg["lean_files"])
    real = decl_refutations(head)
    earlier = [r for r in project.rounds(cfg, repo=repo)]
    here = [os.path.basename(r) for r in earlier]
    if round_name in here:
        earlier = earlier[:here.index(round_name)]
    out = {}
    for r in earlier:
        for p in sorted(glob.glob(os.path.join(r, "*.json")) + glob.glob(os.path.join(r, "revote", "*.json"))):
            try:
                d = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and "lane" in d and isinstance(d.get("verdicts"), list):
                for m in make_report.AS_PRINTED.finditer(json.dumps(d, ensure_ascii=False)):
                    if m.group(0) not in real:
                        out.setdefault(m.group(0), os.path.relpath(p, os.path.dirname(r)))
    return out


def refutation_scope(cfg, repo, round_name, kind, scope_decls, scope_rows):
    """{item: refutation} the paper-faithfulness lane judges besides the index rows (trial #7: no pinned path
    gave a lane the F10 item, so no `false` row could ever be recorded): for each refutation `not_<X>_as_printed`
    -- a DECLARATION of the project at this commit, never a name only lane text or a probe file carries (bench2:
    a probe `not_main_thm_as_printed` of the declaration `not_MainThm_as_printed` gave every round an
    item no reviewer could judge; lane_only_refutations lists such names for the operator) -- the item
    "F10: the counterexample of <result>" (make_report.F10_ITEM; its counterexample confirmed against the source)
    and "F12: the repair of <result>" (make_report.F12_ITEM; the corrected statement's repair). A full or
    statement round lists every refutation; a diff round those no lane has decided yet (make_report.f10_decided)
    and those whose refutation or result is in its scope. Earlier rounds only, so `--verify` recomputes it."""
    import make_report
    head, _ = decls_at(repo, None, cfg["lean_files"])
    names = decl_refutations(head)
    rdir = os.path.join(repo, cfg["rounds_dir"])
    text = open(os.path.join(repo, project.index_file(cfg)), encoding="utf-8").read() \
        if project.index_file(cfg) and os.path.exists(os.path.join(repo, project.index_file(cfg))) else ""
    short = {q.split(".")[-1] for q in scope_decls}
    out = {}
    for f10, f12, n in make_report.refutation_items(index_rows(text), names):
        lab = f10[len(make_report.F10_ITEM.format("")):]
        if kind == "diff" and n not in short and lab not in scope_rows \
                and make_report.f10_decided(rdir, n) is not None:
            continue
        out[f10] = n
        if f12:
            out[f12] = n
    if kind != "diff":
        # every `false` row of PAPER_DEFECTS.md (a refutation-less one too) has its counterexample judged afresh
        # in each full or statement round: a row once `false` changes status only citing a fresh F10 verdict
        pd = os.path.join(rdir, "PAPER_DEFECTS.md")
        head_, rows_, _, old_ = make_report.defects_table(pd) if os.path.exists(pd) else (None, [], [], True)
        i = make_report.defect_col(head_, "status") if head_ and not old_ else None
        for r in rows_ if i is not None else []:
            lab = make_report.defect_result(head_, r)
            if i < len(r) and make_report.defect_value(r[i]) == "false" and lab \
                    and make_report.F10_ITEM.format(lab) not in out:
                out[make_report.F10_ITEM.format(lab)] = f"row {r[0].strip('* ')}"
    return out


class FPs(dict):
    auto = ()
    deps = None


def fingerprint_record(head, fps):
    """The round's FINGERPRINTS.json: the commit, every fingerprint, the auto-generated keys and (B9) each
    declaration's project-local deps -- the closure result_status.py reads for F1."""
    rec = {"commit": head, "fingerprints": dict(fps), "auto": sorted(getattr(fps, "auto", ()))}
    if getattr(fps, "deps", None) is not None:
        rec["deps"] = fps.deps
    return rec


def lean_fps(cfg):
    import fingerprint
    fps = FPs(fingerprint.compute(cfg))
    fps.auto = set(fingerprint._AUTO)
    fps.deps = dict(fingerprint._DEPS)
    return fps


def target_items(doc):
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def preflight(cfg, repo, round_name, kind, verify=False):
    """None, or why this round must not be scoped now. `verify`: the round is already scoped
    (`--verify`): the first-proof-round rule is not applied again, so a diff round scoped before the
    rule (a run in flight) does not stall its adjudicator (review of fix-mini2, L2)."""
    if not round_name:
        return "--round is required (copy it from prompt.py 3's output)"
    if not project.ROUND_RE.match(round_name):
        return f"{round_name!r} is not a round directory name"
    if project.is_full_round(round_name) != (kind != "diff"):
        return "a round directory named ...-full-... is a full or statement round, and only it is"
    head = (git(repo, "rev-parse", "HEAD") or "").strip()
    rc_ = project.round_commit(round_name)
    # the round's commit is a prefix of the FULL hash: comparing 7 characters accepted
    # 0a1b2c3d4e5 against HEAD 0a1b2c3d4ef (RULINGS A10e)
    if not head or not head.startswith(rc_):
        return f"round {round_name} is not cut from HEAD ({head[:11]}): copy the round name prompt.py 3 prints"
    taken = taken_problem(cfg, repo, round_name) if not verify else None
    if taken:
        return taken
    dirty = git(repo, "status", "--porcelain", "--", *cfg["lean_files"])
    if dirty and dirty.strip():
        return ("uncommitted changes in the project's Lean files; the scope would describe a tree "
                "that is not the commit being audited:\n" + dirty)
    if not verify:
        # trial #10: a refutation under any name but `not_<decl>_as_printed` gets no F10 item, so no `false` row
        # can be recorded for it; refused here (and by Phase 0's index check), before the round is spent
        import make_report
        names = make_report.refutation_name_problems(cfg, repo)
        if names:
            return "FAIL[index] " + "\nFAIL[index] ".join(names)
    if kind == "diff" and not verify and not first_proof_round_ok(cfg, repo, round_name):
        return FIRST_PROOF_ROUND
    if kind == "statements" and not verify:
        # C2 audit: a hypothesis the walk lists that nothing classifies (a project definition of the paper's with no
        # index Definition row) blocks the statement round, before its lanes run: the sheet then carries the row
        import hypotheses
        # SWEEP-FIX D1 (G1): the blockers are judged on a FRESH walk here, never skipped on a stale or missing one --
        # else they surfaced first at approve, and at the cap no round was left to cure them (refuse-and-refresh)
        wp = hypotheses.walk_problem(cfg, os.path.join(repo, cfg["rounds_dir"]))
        if wp:
            return (f"FAIL[index] the assumption walk cannot be judged: {wp}. Refresh it -- `python3 audits/phase0.py "
                    f"--statements` (it rewrites it; or just `python3 audits/dependencies.py --write`) -- then scope "
                    f"again: a hypothesis nothing classifies must block the statement round here, before its lanes "
                    f"run, not first at approve")
        blk = hypotheses.statement_blockers(cfg, os.path.join(repo, cfg["rounds_dir"]))
        if blk:
            return "\n".join(hypotheses.statement_blocker_lines(blk))
        c = statement_cap(cfg, repo)
        if c:
            stop_ = c["open"] and project.round_cap_route(cfg) == "stop"
            return ("PROBLEM[round-cap] " if stop_ else "NOTE[round-cap] ") + cap_message(c, cfg)
    return None


def taken_problem(cfg, repo, round_name):
    """None, or why the round's name is taken: its directory was already scoped (TARGET.json). A round set aside
    before its review (stage2 step 2: `signoff.py bundle` reported a PROBLEM; a set-aside round counts toward no
    cap) keeps its name for ever, so a restart at the same Lean commit (a fix to the config only, e.g. a file added
    to `lean_files`) needs a new name: the operator's prescribed empty Lean commit (integrated review fix 3)."""
    rd = os.path.join(repo, cfg["rounds_dir"], round_name)
    if not os.path.exists(os.path.join(rd, "TARGET.json")):
        return None
    if project.is_abandoned(rd):
        return (f"round {round_name} was set aside, and a round's name is used once: make the empty Lean commit "
                f"`git commit --allow-empty -m \"fresh round after the set-aside of {round_name}\"` (exactly that "
                f"subject), list it in the run log (`echo \"- <its full hash> fresh round after the set-aside of "
                f"{round_name}\" | python3 audits/project.py --log \"Mechanical failures\"`), then run prompt.py 3 "
                f"again: it names the new round")
    return f"round {round_name} is already scoped (its TARGET.json exists): a round's scope is written once"


# B13 (U2 §8, caps): statement rounds are capped -- 4 before the first approval, 2 for each re-approval (its
# own cap, not counted toward the 4); proof-phase rounds are bounded by progress, not here. The numbers are
# guesses until replays of long runs tune them (U2 §14). A cap reached while the newest statement round leaves a
# faithfulness finding open: dev, a human stop; release, project.round_cap_route (the operator judges the cause;
# cap_record); otherwise the conservative default, disclosed.
STATEMENT_CAP = 4
REAPPROVAL_CAP = 2
FAITHFULNESS_LANES = ("correspondence", "paper-faithfulness")


def _first_commit(top, rel):
    r = subprocess.run(["git", "-C", top, "log", "--reverse", "--diff-filter=A", "--format=%H", "--", rel],
                       capture_output=True, text=True)
    return (r.stdout.split() or [None])[0]


def statement_cap(cfg, repo):
    """None while another statement round is allowed, else {"cap", "rounds", "what", "open"}: the statement
    rounds counted (set-aside rounds are not), "before the first approval" or "of the re-approval begun in
    <commit>", and the faithfulness findings the newest of them leaves open (lanes correspondence and
    paper-faithfulness, decided ADOPT or QUESTION: a fix the cap stops). A statement round after an approval
    with no re-approval open is not capped (none is expected there)."""
    import fingerprint, audit_coverage
    rdir = os.path.join(repo, cfg["rounds_dir"])
    stm = [r for r in project.rounds(cfg, repo=repo) if project.round_kind(r) == "statements"]
    reap, prob = fingerprint.open_reapproval(rdir, repo, cfg)
    if reap and not prob:
        top = subprocess.run(["git", "-C", rdir, "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True).stdout.strip()
        begin = subprocess.run(["git", "-C", top, "log", "-1", "--format=%H", "--", os.path.relpath(
            os.path.join(rdir, fingerprint.REAPPROVAL), top)], capture_output=True, text=True).stdout.strip()

        def after(r):
            c = _first_commit(top, os.path.relpath(os.path.join(r, "TARGET.json"), top))
            return bool(c and begin) and c != begin and subprocess.run(
                ["git", "-C", top, "merge-base", "--is-ancestor", begin, c], capture_output=True).returncode == 0
        counted, cap, what = [r for r in stm if after(r)], REAPPROVAL_CAP, f"of the re-approval begun in {begin[:11]}"
    elif fingerprint.approval_history(rdir, cfg)[0]:
        return None
    else:
        counted, cap, what = stm, STATEMENT_CAP, "before the first approval"
    # review M5(a): at most GRACE_CAP graces per cap -- a printer that keeps changing the sheet is a tool bug
    graces = [os.path.basename(r) for r in counted if grace_of(rdir, os.path.basename(r))][:GRACE_CAP]
    if len(counted) < cap + len(graces):
        return None
    rows = audit_coverage.read_adopted(os.path.join(counted[-1], "ADOPTED.md"))
    # integrated review fix 8: a QUESTION row the level lets the agent decide (decisions.needs_human: under hands-off
    # every one, under statements-only one after the approval that no open re-approval names) is a decision taken
    # at the cap like an ADOPT row's, not an open finding: it never makes the cap an open finding
    import decisions
    human = decisions.needs_human(cfg, project.rounds(cfg, repo=repo))
    last = os.path.basename(counted[-1])
    open_ = sorted(k for k, d in rows.items() if k.split(" :: ")[0] in FAITHFULNESS_LANES and (
        d == "ADOPT" or (d == "QUESTION" and human(last, k.split(" :: ", 1)[-1]))))
    return {"cap": cap, "rounds": [os.path.basename(r) for r in counted], "what": what, "open": open_,
            "graces": graces}


ROUND_CAPS = "round-caps"     # <rounds dir>/round-caps/<last round>.json, committed "round-cap <last round>"
# SWEEP-FIX D1 (G1, G2): <rounds dir>/round-caps/grace/<round>.json, committed "round-cap <round> grace" by
# signoff.py approve when it refuses, for a MECHANICAL reason, the last counted round of a reached cap. A
# subdirectory: result_status reads round-caps/*.json as the open-finding records, never these
GRACE = "grace"
GRACE_CAP = 3       # grace rounds per cap (review M5): past them a mechanical refusal is a tool bug (the tool-patch route)
GRACE_SPENT = "spent"


def grace_path(rdir, rnd):
    return os.path.join(rdir, ROUND_CAPS, GRACE, f"{rnd}.json")


def grace_of(rdir, rnd):
    """The grace record of round `rnd` (dict) when it is a committed-shaped record of that round, else None."""
    try:
        d = json.load(open(grace_path(rdir, rnd), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("round") == rnd and (d.get("rounds") or [None])[-1] == rnd else None


def grace_record(cfg, repo, rnd, reason):
    """Record one grace round (SWEEP-FIX D1): `signoff.py approve` refused round `rnd` for a mechanical reason
    (`reason`, verbatim) while `rnd` is the last statement round counted by a reached cap. The round needed only
    because of that refusal then never counts against the cap (statement_cap adds one per record; one per round).
    Returns the record's path, or None when the cap is not reached on `rnd` (another round is allowed anyway)."""
    c = statement_cap(cfg, repo)
    if not c or c["rounds"][-1] != rnd:
        return None
    rdir = os.path.join(repo, cfg["rounds_dir"])
    p = grace_path(rdir, rnd)
    if os.path.exists(p):
        return p
    if len(c.get("graces") or []) >= GRACE_CAP:
        return GRACE_SPENT
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"round": rnd, "rounds": c["rounds"], "cap": c["cap"], "what": c["what"],
               "reason": " ".join(str(reason).split())}, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        project.commit_only([p], f"round-cap {rnd} grace")
    except Exception:       # noqa: BLE001 -- an uncommitted record is no record
        os.remove(p)
        raise
    return p


def grace_rows(cfg, repo=None):
    """[(round, reason)] of every grace record of the run (for RUN_RECORD.md and the report: each is disclosed)."""
    rdir = os.path.join(repo or project.REPO, cfg["rounds_dir"])
    out = []
    for p in sorted(glob.glob(os.path.join(rdir, ROUND_CAPS, GRACE, "*.json"))):
        d = grace_of(rdir, os.path.basename(p)[:-len(".json")])
        if d:
            out.append((d["round"], d.get("reason", "")))
    return out


def cap_record(cfg, repo, c):
    """Release, round_cap_route "judge" (approver 2026-10-24): record the faithfulness findings the statement-round
    cap leaves open -- <rounds dir>/round-caps/<last round>.json, committed once as "round-cap <last round>" --
    so result_status marks every result one leaves unresolved "not established: open faithfulness finding". The
    record is written by this script, never by hand (integrity.OWNERS, ownership 4). Returns its path, or None
    (nothing open, or not this route)."""
    if not c or not c["open"] or project.round_cap_route(cfg) != "judge":
        return None
    last = c["rounds"][-1]
    p = os.path.join(repo, cfg["rounds_dir"], ROUND_CAPS, f"{last}.json")
    if os.path.exists(p):
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump({"round": last, "rounds": c["rounds"], "cap": c["cap"], "what": c["what"], "open": c["open"]},
              open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        project.commit_only([p], f"round-cap {last}")
    except Exception:       # noqa: BLE001 -- an uncommitted record is no record
        os.remove(p)
        raise
    return p


def cap_message(c, cfg=None):
    last = c["rounds"][-1]
    gr = c.get("graces") or []
    head = (f"the statement-round cap is reached: {len(c['rounds'])} statement round(s) {c['what']} (cap {c['cap']}"
            + (f", plus {len(gr)} grace round(s) after a mechanical approval refusal of {', '.join(gr)} -- "
               f"{ROUND_CAPS}/{GRACE}/, disclosed in RUN_RECORD.md" if gr else "")
            + f"; the last, {last}). No further statement round.")
    if c["open"] and project.round_cap_route(cfg or {}) == "judge":
        return (head + f" Round {last} leaves {len(c['open'])} faithfulness finding(s) open ({'; '.join(c['open'][:4])}"
                f"{'; ...' if len(c['open']) > 4 else ''}), recorded in {ROUND_CAPS}/{last}.json. Release mode: no stop "
                f"of its own -- judge each finding's cause (RUN.md \"Stops that remain\"): (a) the paper's meaning is "
                f"genuinely ambiguous on a point that matters and the reviewers cannot converge on one reading: stop 4, "
                f"`python3 audits/stops.py open --note \"<the passage and its readings>\" --cause ambiguity`, show the "
                f"user the passage, the possible readings and what each would mean for the formalization, wait, close "
                f"it with --human; (b) a loose or inconsistent convention that is no real misunderstanding: pick the "
                f"intended reading, record it as a reading choice (\"Route changes\" in AUTHOR_NOTES.md, and a "
                f"[DELEGATED …] or [PROXY …] line under \"Open questions\") and go on; (c) anything else: go on with "
                f"the sheet of round {last} as it stands -- every result it leaves open reads \"not established: open "
                f"faithfulness finding\" on the summary's first page")
    if c["open"]:
        return (head + f" Round {last} leaves {len(c['open'])} faithfulness finding(s) open ({'; '.join(c['open'][:4])}"
                f"{'; ...' if len(c['open']) > 4 else ''}): in dev mode this is a stop, at every level -- `python3 audits/stops.py "
                f"open --note \"statement-round cap reached with open faithfulness findings\" --cause round-cap`, "
                f"show the human the findings, wait, and close it with --human (RUN.md, \"Stops that remain\")")
    return (head + f" No faithfulness finding is open, so this is no stop: go on with the sheet of round {last} as that "
            f"round audited the statements (stage2-statements.md step 7). Implement no ADOPT row that would change a "
            f"statement; record each such row as a decision taken at the cap (`project.py --log \"Open questions\"`: "
            f"[DELEGATED …] under a delegating level, [PROXY …] under involved, which goes to the human at C), so the "
            f"decisions document and the report disclose it; a QUESTION row your level lets you decide (hands-off) is "
            f"decided as any other ([DELEGATED …], RUN.md \"How you decide\")")


FIRST_PROOF_ROUND = (
    "this would be the first round to examine proofs, and Stage 3 changed (nearly) every proof: a diff "
    "round here re-examines almost everything and is then followed by the full-scope round, often at "
    "the same commit (mini2 audit: 37 min spent twice). Run the full-scope round instead: `python3 "
    "audits/prompt.py 3 --full` (scope.py --full: every correctness lane, every declaration and index "
    "row -- more than a diff round, never less). Its exit check: no ADOPT, REVOTE NEEDED or unexpected "
    "UNCOVERED row -> it is Stage 5's full round (go to stage5-delivery.md step 2); otherwise implement "
    "and continue Stage 4 with diff rounds as usual, and Stage 5 still opens with its own full round")


def first_proof_round_ok(cfg, repo, round_name):
    """False when a diff round would be the first round to examine proofs (every earlier round is a
    statement round, or there is none): stage4-rounds.md then runs the full-scope round instead
    (FIRST_PROOF_ROUND). Only ever replaces a diff round by a full one, which examines more."""
    for r in project.rounds(cfg, repo=repo):
        if os.path.basename(r) != round_name and project.round_kind(r) in ("diff", "full"):
            return True
    return False


def compare(recorded, doc):
    """[mismatch] between a recorded TARGET.json and a recomputed one."""
    bad = []
    if recorded.get("_meta", {}).get("prev") != doc["_meta"]["prev"]:
        bad.append(f"recorded base {recorded.get('_meta', {}).get('prev')} != recomputed {doc['_meta']['prev']}")
    rec, now = target_items(recorded), target_items(doc)
    rows_ = lambda m: {i: n for i, n in (m.get("f10") or {}).items() if str(n).startswith("row ")}
    if "paper-faithfulness" in now:
        # PAPER_DEFECTS.md `false` rows' items: as recorded (the record grows after scoping); recomputed ones left out
        skip = set(rows_(doc["_meta"])) - set(rows_(recorded.get("_meta", {})))
        keep = set(rows_(recorded.get("_meta", {})))
        now = dict(now, **{"paper-faithfulness": [i for i in now["paper-faithfulness"] if i not in skip]
                           + [i for i in keep if i not in now["paper-faithfulness"]]})
        doc = dict(doc, _meta=dict(doc["_meta"], f10={**{i: n for i, n in (doc["_meta"].get("f10") or {}).items()
                                                         if i not in skip}, **rows_(recorded.get("_meta", {}))}))
    if "f10" not in recorded.get("_meta", {}) and "paper-faithfulness" in now:
        # a round scoped before F10 scheduling (no `_meta.f10`): its lane never had the items; not a change
        sched = set(doc["_meta"].get("f10") or {}) | {i for i in now["paper-faithfulness"] if i.startswith("F12: ")}
        now = dict(now, **{"paper-faithfulness": [i for i in now["paper-faithfulness"] if i not in sched]})
    elif (recorded.get("_meta", {}).get("f10") or {}) != (doc["_meta"].get("f10") or {}):
        bad.append(f"F10 items: recorded {recorded['_meta'].get('f10')} != recomputed {doc['_meta'].get('f10')}")
    if "paper-faithfulness" in now:
        # F13 items: as recorded (RUN_LOG.md grows after scoping; a round scoped before F13 scheduling has none)
        keep = list((recorded.get("_meta", {}).get("f13") or {}))
        now = dict(now, **{"paper-faithfulness": [i for i in now["paper-faithfulness"] if i not in
                                                  (doc["_meta"].get("f13") or {})] + keep})
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


def scope_commit(rdir, round_name):
    """(top, commit, text): the records repository holding `rdir`, the commit that first added
    <round>/TARGET.json there (scope.py's "scope R" commit) and the TARGET.json it committed; (top, None,
    None) when it was never committed, (None, None, None) outside a repository."""
    top, rel = project.rounds_rel(rdir, os.path.join(round_name, "TARGET.json"))
    if top is None:
        return None, None, None
    c = (git(top, "log", "--reverse", "--diff-filter=A", "--format=%H", "--", rel) or "").split()
    return (top, c[0], git(top, "show", f"{c[0]}:{rel}")) if c else (top, None, None)


def frozen_rounds_dir(top, commit, rdir):
    """(tmp, dir): the project's records as they stood when the round was scoped -- the tree of the records
    repository `top` at the parent of its scope commit `commit`, extracted under a fresh temporary directory
    `tmp` (the caller removes it). An empty directory when the records did not exist yet."""
    import io, tarfile
    tmp = tempfile.mkdtemp(prefix="scope-frozen-")
    rrel = os.path.relpath(os.path.realpath(rdir), top)
    dest = os.path.join(tmp, "records")
    os.makedirs(dest)
    parent = (git(top, "rev-parse", "-q", "--verify", f"{commit}^{{commit}}") or "").strip()
    if parent and git(top, "rev-parse", "-q", "--verify", f"{parent}:{'' if rrel == '.' else rrel}") is not None:
        p = subprocess.run(["git", "-C", top, "archive", "--format=tar", parent] + ([] if rrel == "." else ["--", rrel]),
                           capture_output=True)
        if p.returncode:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"git archive {parent[:11]}: {p.stderr.decode(errors='replace').strip()}")
        with tarfile.open(fileobj=io.BytesIO(p.stdout)) as t:
            t.extractall(dest, filter="data")
    fr = dest if rrel == "." else os.path.join(dest, rrel)
    os.makedirs(fr, exist_ok=True)
    return tmp, fr


def verify_round(cfg, repo, round_name, kind, fps):
    """([mismatch], (doc, unnamed, changed)) for `--verify`: the round's TARGET.json against the scope it was
    issued with. The scope is recomputed from the round's FROZEN inputs -- the Lean commit (HEAD, checked by
    preflight) and the records at the parent of its scope commit -- never from today's records: a record that
    legitimately changes after issue (the round's own lane deciding an F10 item, a later set-aside, a later
    re-vote) changed today's recomputation and raised a false MISMATCH[scope-changed] (bench2: the F10 item of
    `not_main_thm_as_printed`, decided by the round's own lane, "not in the recomputed scope"). Tampering is
    still caught: a TARGET.json changed after its scope commit differs from what that commit recorded, and one
    hand-written into the scope commit differs from the recomputation. Never committed (written, the commit
    failed): today's records are its inputs."""
    rdir = os.path.join(repo, cfg["rounds_dir"])
    recorded = json.load(open(os.path.join(rdir, round_name, "TARGET.json"), encoding="utf-8"))
    top, c, committed = scope_commit(rdir, round_name)
    if c is None:
        res = make_target(cfg, round_name, kind, repo, fps)
        return compare(recorded, res[0]), res
    bad = []
    try:
        if json.loads(committed or "") != recorded:
            bad.append(f"TARGET.json differs from the one its scope commit {c[:11]} recorded")
    except ValueError:
        bad.append(f"the TARGET.json its scope commit {c[:11]} recorded cannot be read")
    tmp, fr = frozen_rounds_dir(top, c, rdir)
    try:
        res = make_target(dict(cfg, rounds_dir=fr), round_name, kind, repo, fps)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return bad + compare(recorded, res[0]), res


def empty_scope_next(cfg):
    """(next, line) after an empty diff scope (exit 3): Stage 5, unless a Lean commit came after the last audited
    round all the same (make_report.stale_problems, the delivery's deliver-stale): a commit that changed no
    declaration a lane reviews (mini5: a theorem turned into an `example`). Going to Stage 5 there looped (its
    delivery check sent the run back to a diff round, whose scope is empty again): a full round audits that
    commit and ends the loop."""
    import make_report
    try:
        st = make_report.stale_problems(cfg)
    except Exception as e:      # noqa: BLE001 -- fail towards the round that audits more
        st = [f"the changes since the last audited round could not be read ({e})"]
    if st:
        return "full", ("NEXT[full-round] the diff scope is empty, but the delivery would refuse the Lean as unaudited "
                        "(deliver-stale: " + " ".join(st[0].split())[:240] + "): run a full round, python3 audits/"
                        "prompt.py 3 --full (Stage 4 step 2), not Stage 5")
    # integrated review fix 2: an item only the next adjudication clears (RED[adj-record] at --deliver: a `leave
    # <decl> unproved` line logged after the final round, a route change recorded since the last adjudication, an
    # unsettled Fail) with nothing for a diff round to scope: Stage 5 sent the run back here for ever
    try:
        pend = [t for c, t in make_report.pending_adjudication(cfg) if c == "adj-record"]
    except Exception as e:      # noqa: BLE001 -- fail towards the round that audits more
        pend = [f"what awaits the next adjudication could not be read ({e})"]
    if pend:
        return "full", ("NEXT[full-round] the diff scope is empty, but an item awaits the next adjudication (adj-record: "
                        + " ".join(pend[0].split())[:240] + "): run a full round, python3 audits/prompt.py 3 --full "
                        "(Stage 4 step 2), so its adjudicator settles it; not Stage 5")
    return "stage5", "NEXT[stage5] nothing changed since the last audited round: go to Stage 5 (stage5-delivery.md)"


def comment_only_since(repo, prev, files):
    """True when every Lean file in `files` differs between commit `prev` and the working tree only in comments
    and docstrings (the text with comments removed, literals kept, whitespace normalised, is the same) and the
    same files exist in both. Textual, so it errs towards False."""
    from phase0 import strip_comments
    same = lambda t: " ".join(strip_comments(t, literals=True).split())
    for f in files:
        p = os.path.join(repo, f)
        new = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        old = git(repo, "show", f"{prev}:{f}")
        if (new is None) != (old is None) or (new is not None and same(new) != same(old)):
            return False
    return True


def stage4_skip_line(cfg, repo, prev, stage):
    """The NEXT[stage5] line when a Stage 4 diff round would only re-read comments and docstrings (else None):
    Stage 5 opens with a full round on this same commit, which re-reads every docstring with every lane, so the
    diff round first only repeats part of it (trial #10: a 16-minute diff round, then the full round on the same
    commit; trial #7 the same). In Stage 5, no_round_line decides (no round for a docstring-only change)."""
    if project.stage_file(stage) != project.STAGE_FILES[4] or not prev:
        return None
    if not comment_only_since(repo, prev, cfg["lean_files"]):
        return None
    return (f"NEXT[stage5] only comments and docstrings changed since the last audited round ({str(prev)[:11]}): "
            "no diff round in Stage 4 -- go to Stage 5, whose full round audits this commit with every lane "
            "(stage4-rounds.md step 7)")


def _round_settled(rd):
    """None when round `rd` is adjudicated (ADOPTED.md), every REVOTE NEEDED row has a later decision row of the same
    lane and item, and no UNCOVERED row lacks its "(expected: …)" mark; else why not."""
    import lanecheck
    ap = os.path.join(rd, "ADOPTED.md")
    if not os.path.exists(ap):
        return f"round {os.path.basename(rd)} is not adjudicated"
    rows = lanecheck.decision_rows(rd)
    for i, r in enumerate(rows):
        if r.problem or r.lane is None or r.item is None:
            return f"a decision row names no lane or item of the round ({r.problem or '?'})"
        if r.decision == "REVOTE NEEDED" and not any(
                (q.lane, q.item) == (r.lane, r.item) and q.decision in ("ADOPT", "REJECT", "DEFER", "QUESTION")
                for q in rows[i + 1:]):
            return f"its REVOTE NEEDED row {r.lane} | {r.item} is not decided"
        if r.decision == "UNCOVERED" and "(expected" not in (r.reason or "") + (r.verdict or ""):
            return f"its UNCOVERED row {r.lane} | {r.item} is not marked expected"
    return None


def no_round_line(cfg, repo, kind, stage):
    """Stage 5 (trial #11: a full round and a diff round, about 84 minutes, for docstring-only fixes): the
    NEXT[no-round] line when the round would audit nothing new, else None. Both need the Lean unchanged since the
    last proof-examining round, or changed only in comments and docstrings as `project.py --deliver` decides it
    (project.changes_after_last_audit's Lean check, the one make_report.stale_problems uses, so the delivery never
    asks for the round skipped here), committed, nothing pending the next adjudication, and no `unverified`
    precondition. A diff round then has nothing to audit. A full round is already done when that last round IS a
    full-scope proof round, adjudicated and settled (Stage 4's first full round counts as Stage 5's full-scope round
    when its fixes were docstrings only). Phase 0 still runs on the commit (the freeze check: approved statements
    unchanged); the report and the decisions document list the commits as comment-only, read by no lane."""
    if project.stage_file(stage) != project.STAGE_FILES[5]:
        return None
    try:
        import make_report, stops
        if stops.redo_target(cfg):
            return None     # a set-aside's cure needs its fresh round (MAINTAINING R4)
        import tool_patch
        if tool_patch.forced_round_problems(cfg):
            return None     # a tool patch that may have changed a review's inputs needs a real full round (OPERATOR-PATCH §4)
        c = project.changes_after_last_audit(cfg, project.rounds(cfg))
        if c is None or c["problem"] or c["dirty"]:
            return None
        changed = bool(c["commits"])
        if kind == "diff" and not changed:
            return None     # nothing changed: the empty-scope route (empty_scope_next) says what follows
        if changed and not c.get("comment_only"):
            return None
        last = os.path.join(repo, cfg["rounds_dir"], c["round"])
        if kind == "full" and not (project.is_full_round(c["round"]) and project.round_kind(last) == "full"
                                   and _round_settled(last) is None):
            return None
        if make_report.stale_problems(cfg) or make_report.pending_adjudication(cfg) \
                or make_report.unverified_problems(cfg):
            return None
    except Exception:       # noqa: BLE001 -- fail towards the round that audits more
        return None
    what = (f"only comments and docstrings changed since round {c['round']} ({str(c['commit'])[:11]}), checked with "
            "Lean as --deliver checks it" if changed else f"nothing changed since round {c['round']}")
    if kind == "full":
        return (f"NEXT[no-round] {what}, and that round is a full-scope round, adjudicated and settled: it is Stage 5's "
                "full-scope round. Run no round: commit, run Phase 0 (it checks the approved statements are unchanged) "
                "and go on with stage5-delivery.md step 2")
    return (f"NEXT[no-round] {what}: no diff round (no lane re-reads a comment or docstring; the report and the "
            "decisions document say so). Commit, run Phase 0 (it checks the approved statements are unchanged) and "
            "go on with stage5-delivery.md step 2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--round", required=False, help="round directory name, as printed by prompt.py 3")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="full-scope round")
    g.add_argument("--statements", action="store_true", help="statement round (full scope, 3 lanes)")
    ap.add_argument("--verify", action="store_true",
                    help="recompute from the round's frozen inputs and compare with TARGET.json")
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
    why_not = preflight(cfg, repo, a.round, kind, verify=a.verify)
    if why_not:
        if why_not.startswith(("PROBLEM[round-cap]", "NOTE[round-cap]")):
            # B13: the cap is a refusal with its own route (dev: a human stop with an open faithfulness finding;
            # release: project.round_cap_route -- the operator judges, the open findings are recorded)
            if why_not.startswith("NOTE[round-cap]"):
                try:
                    cap_record(cfg, repo, statement_cap(cfg, repo))
                except Exception as e:      # noqa: BLE001 -- said; the route still holds
                    print(f"FAIL: the round-cap record could not be committed: {e}", file=sys.stderr)
                    return 2
            print(why_not)
            return 2 if why_not.startswith("PROBLEM") else 3
        print(why_not if why_not.startswith("FAIL[") else f"FAIL: {why_not}", file=sys.stderr); return 2
    nr = no_round_line(cfg, repo, kind, project.current_stage(cfg)) if kind in ("diff", "full") and not a.verify \
        else None
    if nr:
        print(nr)
        return 3
    head = (git(repo, "rev-parse", "--short=11", "HEAD") or "").strip()
    try:
        fps = lean_fps(cfg)
    except RuntimeError as e:
        print(f"FAIL: could not fingerprint the project (is it built? Phase 0 builds it):\n{e}",
              file=sys.stderr)
        return 2
    if a.verify:
        try:
            bad, (doc, unnamed, changed) = verify_round(cfg, repo, a.round, kind, fps)
        except (RuntimeError, OSError, ValueError) as e:
            print(f"FAIL: the round's scope inputs could not be read: {e}", file=sys.stderr)
            return 2
    else:
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
    if not a.verify and "paper-faithfulness" in items:
        for n, src in sorted(lane_only_refutations(cfg, repo, a.round).items()):
            print(f"#   note: `{n}` ({src}) is no declaration of the project: no F10/F12 item is scheduled for it "
                  f"(a refutation is judged only as a Lean declaration `not_<decl>_as_printed`)", file=sys.stderr)

    if a.verify:
        for x in bad:
            print(f"MISMATCH[scope-changed] {x}")
        print(f"scope verify: {'OK' if not bad else 'MISMATCH'}")
        return 1 if bad else 0
    if not any(items.values()):
        print("! empty scope: nothing changed since the last audited commit. Do not run lanes "
              "on it; an empty round reports full coverage of nothing.", file=sys.stderr)
        print(empty_scope_next(cfg)[1])
        return 3
    skip = (stage4_skip_line(cfg, repo, meta["prev"], project.current_stage(cfg))
            if kind == "diff" and not a.verify else None)
    if skip:
        print(skip)
        return 3
    import stops
    redo = stops.redo_target(cfg)
    if redo:
        # the fresh round of a redo (U2 §4 "Closing a redo"): the open stop set round <redo> aside; its
        # self-cure is checked on this round. --verify ignores it (compare reads only _meta.prev and the lanes)
        meta["redo_of"] = redo
        print(f"#   redoes round {redo} (set aside by the open stop)", file=sys.stderr)
    if a.dry_run:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
        return 0
    if os.path.exists(tp):
        print(f"FAIL: {tp} already exists. A round's scope is written once.", file=sys.stderr)
        return 2
    os.makedirs(rd, exist_ok=True)
    json.dump(doc, open(tp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(fingerprint_record(head, fps),
              open(os.path.join(rd, "FINGERPRINTS.json"), "w"), indent=0)
    print(f"wrote {os.path.relpath(tp, repo)} and FINGERPRINTS.json")
    try:
        # its own two files, by name: a round's scope commit never sweeps anything else in
        h = project.commit_only([tp, os.path.join(rd, "FINGERPRINTS.json")], f"scope {a.round}")
    except ValueError as e:
        print(f"FAIL: written but not committed ({e}); commit those two files, by name, as \"scope "
              f"{a.round}\"", file=sys.stderr)
        return 2
    print(f"committed them as \"scope {a.round}\" in {h[:11]}")
    return 0


_CLOCK = [1_700_000_000]


def _tick():
    """The environment of one git command in a selftest: commit dates one hour after the previous command's
    (polish 2026-10-24: these controls ordered rounds by the wall-clock second of their commits, so a tie or a clock
    step under load could reorder them; the main selftest's commits were already pinned this way)."""
    _CLOCK[0] += 3600
    return dict(os.environ, GIT_COMMITTER_DATE=f"{_CLOCK[0]} +0000", GIT_AUTHOR_DATE=f"{_CLOCK[0]} +0000")


def _bench2_redo_controls(check):
    """bench2's second fault, its exact sequence (RUN_LOG.md "Mechanical failures", 2026-10-24): a diff round
    schedules the F10 item of the refutation, its lane decides it and is sealed; the round is set aside (S1); an
    empty Lean commit; the fresh diff round schedules the item again (a set-aside round decides nothing), its own
    lane decides it and is sealed; its `--verify` then read that sealed verdict (make_report.f10_decided), dropped
    the item and failed. Verified against the frozen inputs (4dd9a08) it passes; the probe name a lane cited
    (`not_main_thm_as_printed`) is never an item."""
    ok = True

    def chk(name, cond):
        nonlocal ok
        check(name, cond)
        ok &= bool(cond)
    d = tempfile.mkdtemp(prefix="scope-bench2-selftest-")
    try:
        def run(top, *a):
            subprocess.run(["git", "-C", top, *a], check=True, capture_output=True, env=_tick())
        for top in (d, os.path.join(d, "audits")):
            os.makedirs(top, exist_ok=True)
            run(top, "init", "-q"); run(top, "config", "user.email", "t@t"); run(top, "config", "user.name", "t")
        os.makedirs(os.path.join(d, "ExamplePaper"))
        open(os.path.join(d, ".gitignore"), "w").write("audits/\n")
        open(os.path.join(d, "ExamplePaper/Basic.lean"), "w").write(
            "namespace ExamplePaper\n\ntheorem MainThm : True := trivial\n\n"
            "theorem not_MainThm_as_printed : ¬ False := id\n\nend ExamplePaper\n")
        open(os.path.join(d, "ExamplePaper/Main.lean"), "w").write(
            "/-!\n| Paper | Lean |\n|---|---|\n| Theorem 1.1 | `ExamplePaper.MainThm` |\n-/\n")
        run(d, "add", "."); run(d, "commit", "-qm", "v1")
        h0 = git(d, "rev-parse", "--short=11", "HEAD").strip()
        rec = os.path.join(d, "audits")
        rdir = os.path.join(rec, "proj")
        os.makedirs(rdir)
        open(os.path.join(rdir, "RUN_LOG.md"), "w").write("# run log\n")
        run(rec, "add", "."); run(rec, "commit", "-qm", "new project")
        cfg = {"name": "ExamplePaper", "lean_files": ["ExamplePaper/Basic.lean", "ExamplePaper/Main.lean"],
               "rounds_dir": rdir, "base_commit": h0, "index_file": "ExamplePaper/Main.lean",
               "lanes": ["correspondence", "paper-faithfulness", "non-vacuity"]}
        item = "F10: the counterexample of Theorem 1.1"

        def scope(rn, kind):
            doc = make_target(cfg, rn, kind, d, None)[0]
            os.makedirs(os.path.join(rdir, rn))
            json.dump(doc, open(os.path.join(rdir, rn, "TARGET.json"), "w"), indent=1)
            run(rec, "add", os.path.join("proj", rn)); run(rec, "commit", "-qm", f"scope {rn}")
            return doc

        def seal(rn, verdicts, lane="paper-faithfulness"):
            json.dump({"lane": lane, "verdicts": verdicts}, open(os.path.join(rdir, rn, f"{lane}.json"), "w"))
            run(rec, "add", "."); run(rec, "commit", "-qm", f"seal {rn} {lane}.json")
        r0 = f"2026-10-24-full-{h0}"
        scope(r0, "full")
        # a reviewer's probe file carries the lower-case name; the declaration is `not_MainThm_as_printed`
        seal(r0, [{"item": "ExamplePaper.MainThm", "verdict": "Pass",
                   "comment": "probe probes/not_main_thm_as_printed.lean compiles"}], lane="non-vacuity")
        run(d, "commit", "-q", "--allow-empty", "-m", "c1")
        h1 = git(d, "rev-parse", "--short=11", "HEAD").strip()
        rA = f"2026-10-24-{h1}"
        dA = scope(rA, "diff")
        seal(rA, [{"item": item, "verdict": "Fail", "comment": "the counterexample holds"}])
        json.dump({"by": "S1"}, open(os.path.join(rdir, rA, project.ABANDONED), "w"))
        run(rec, "add", "."); run(rec, "commit", "-qm", f"set-aside {rA}")
        run(d, "commit", "-q", "--allow-empty", "-m", f"fresh round after the set-aside of {rA}")
        h2 = git(d, "rev-parse", "--short=11", "HEAD").strip()
        rB = f"2026-10-24-{h2}"
        dB = scope(rB, "diff")
        seal(rB, [{"item": item, "verdict": "Fail", "comment": "the counterexample holds"}])
        today = compare(json.load(open(os.path.join(rdir, rB, "TARGET.json"))), make_target(cfg, rB, "diff", d, None)[0])
        vB, _ = verify_round(cfg, d, rB, "diff", None)
        chk("bench2 (second fault): the diff round scoped after a set-aside schedules the F10 item again, exactly "
            "once and only for the declaration (no probe-name item)",
            all(list(x["_meta"]["f10"].items()) == [(item, "not_MainThm_as_printed")]
                and not any("main_thm" in i for i in x["paper-faithfulness"]) for x in (dA, dB)))
        chk("bench2 (second fault): after its own lane decided the F10 item and was sealed, the round's --verify "
            "passes against its frozen inputs (the recomputation from today's records, the old check, fails)",
            vB == [] and any("F10 items" in x for x in today))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return ok


def _frozen_verify_controls(check):
    """bench2 (S1): `--verify` recomputed a round's scope from TODAY's records. The diff round scheduled the F10 item
    of an undecided refutation; its own lane then decided it, today's recomputation dropped it, and the honest round
    was flagged MISMATCH[scope-changed] and set aside. The scope is now recomputed from the records at the parent of
    the round's scope commit, in a records repository nested in the Lean one as a run has it."""
    ok = True

    def chk(name, cond):
        nonlocal ok
        check(name, cond)
        ok &= bool(cond)
    d = tempfile.mkdtemp(prefix="scope-frozen-selftest-")
    try:
        def run(top, *a):
            subprocess.run(["git", "-C", top, *a], check=True, capture_output=True, env=_tick())
        for top in (d, os.path.join(d, "audits")):
            os.makedirs(top, exist_ok=True)
            run(top, "init", "-q"); run(top, "config", "user.email", "t@t"); run(top, "config", "user.name", "t")
        os.makedirs(os.path.join(d, "P"))
        open(os.path.join(d, ".gitignore"), "w").write("audits/\n")
        open(os.path.join(d, "P/Basic.lean"), "w").write(
            "namespace P\n\ntheorem thm : True := trivial\n\ntheorem not_thm_as_printed : ¬ False := id\n\nend P\n")
        open(os.path.join(d, "P/Main.lean"), "w").write("/-!\n| Paper | Lean |\n|---|---|\n| Theorem 1.1 | `P.thm` |\n-/\n")
        run(d, "add", "."); run(d, "commit", "-qm", "v1")
        head = git(d, "rev-parse", "--short=11", "HEAD").strip()
        rec = os.path.join(d, "audits")
        rdir = os.path.join(rec, "proj")
        os.makedirs(rdir)
        open(os.path.join(rdir, "RUN_LOG.md"), "w").write("# run log\n")
        run(rec, "add", "."); run(rec, "commit", "-qm", "new project")
        cfg = {"name": "P", "lean_files": ["P/Basic.lean", "P/Main.lean"], "rounds_dir": rdir, "base_commit": head,
               "lanes": ["correspondence", "paper-faithfulness", "non-vacuity"], "index_file": "P/Main.lean"}
        item = "F10: the counterexample of Theorem 1.1"

        def scope(rn, kind, doc=None):
            doc = doc or make_target(cfg, rn, kind, d, None)[0]
            os.makedirs(os.path.join(rdir, rn))
            json.dump(doc, open(os.path.join(rdir, rn, "TARGET.json"), "w"), indent=1)
            run(rec, "add", os.path.join("proj", rn)); run(rec, "commit", "-qm", f"scope {rn}")
            return doc
        r0, r1, r2 = f"2026-01-01-full-{head}", f"2026-01-02-{head}", f"2026-01-03-{head}"
        scope(r0, "full")
        d1 = scope(r1, "diff")
        forged = json.loads(json.dumps(d1))
        forged["paper-faithfulness"] = [i for i in forged["paper-faithfulness"] if i != item]
        forged["_meta"]["f10"] = {}
        scope(r2, "diff", forged)          # hand-written into its scope commit: the F10 item left out
        # the round's own lane decides the F10 item, sealed; later the earlier full round is set aside
        json.dump({"lane": "paper-faithfulness", "verdicts": [{"item": item, "verdict": "Pass"}]},
                  open(os.path.join(rdir, r1, "paper-faithfulness.json"), "w"))
        run(rec, "add", "."); run(rec, "commit", "-qm", f"seal {r1} paper-faithfulness.json")
        today = compare(json.load(open(os.path.join(rdir, r1, "TARGET.json"))), make_target(cfg, r1, "diff", d, None)[0])
        v1, _ = verify_round(cfg, d, r1, "diff", None)
        chk("bench2: the diff round's F10 item scheduled at issue and decided later by its own lane is no mismatch "
            "(today's recomputation, the old check, flags it)",
            item in d1["paper-faithfulness"] and any("F10 items" in x for x in today) and v1 == [])
        json.dump({"by": "t"}, open(os.path.join(rdir, r0, project.ABANDONED), "w"))
        run(rec, "add", "."); run(rec, "commit", "-qm", f"set-aside {r0}")
        chk("a later set-aside of an earlier round (today's diff base changes) is no mismatch",
            verify_round(cfg, d, r1, "diff", None)[0] == [])
        v2, _ = verify_round(cfg, d, r2, "diff", None)
        chk("a TARGET.json hand-written into its scope commit (an F10 item left out) is still a mismatch",
            any("missing from TARGET.json" in x for x in v2) and any("F10 items" in x for x in v2))
        tp = os.path.join(rdir, r1, "TARGET.json")
        json.dump(forged, open(tp, "w"), indent=1)
        v3, _ = verify_round(cfg, d, r1, "diff", None)
        run(rec, "commit", "-q", "--allow-empty", "-am", "edit")
        v4, _ = verify_round(cfg, d, r1, "diff", None)
        chk("a TARGET.json edited after its scope commit is a mismatch, uncommitted or committed",
            all(any("differs from the one its scope commit" in x for x in v) and any("missing" in x for x in v)
                for v in (v3, v4)))
        meta = json.loads(json.dumps(d1)); meta["_meta"]["f13"] = {"F13: x": "x"}
        json.dump(meta, open(tp, "w"), indent=1)
        chk("an edit only compare() tolerates (an F13 item added as recorded) is still caught against the scope commit",
            any("differs from the one its scope commit" in x for x in verify_round(cfg, d, r1, "diff", None)[0]))
        os.makedirs(os.path.join(rdir, f"2026-01-04-{head}"))
        json.dump(d1, open(os.path.join(rdir, f"2026-01-04-{head}", "TARGET.json"), "w"))
        chk("a TARGET.json never committed is compared with today's recomputation, as before",
            any("F10 items" in x for x in verify_round(cfg, d, f"2026-01-04-{head}", "diff", None)[0]))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return ok


def _no_round_controls(check):
    """Trial #11: in Stage 5 a docstring-only change gets no round (no_round_line), and a round still runs whenever
    anything else holds. The record and Lean reads are stubbed; _round_settled runs on a real ADOPTED.md."""
    import make_report, stops
    ok = True

    def chk(name, cond):
        nonlocal ok
        check(name, cond)
        ok &= bool(cond)
    keep = (project.changes_after_last_audit, project.rounds, project.round_kind, make_report.stale_problems,
            make_report.pending_adjudication, make_report.unverified_problems, stops.redo_target,
            globals()["_round_settled"])
    st5, st4 = "Stage 5 — final round", "Stage 4 — audit rounds"
    state = {}

    def run(rkind, stage=st5, **kw):
        s_ = dict(dict(commits=["abc docstrings"], dirty=[], comment_only=True, problem=None,
                       round="2026-01-01-full-aaaaaaa", kind="full", settled=None, stale=[], pend=[], unver=[],
                       redo=None, boom=False), **kw)
        state.update(s_)
        return no_round_line({"rounds_dir": "R", "lean_files": []}, "/nonexistent", rkind, stage)

    def changes(cfg, rs):
        if state["boom"]:
            raise RuntimeError("unreadable")
        return {"round": state["round"], "commit": "aaaaaaa", "commits": state["commits"], "dirty": state["dirty"],
                "problem": state["problem"], "comment_only": state["comment_only"]}
    project.changes_after_last_audit = changes
    project.rounds = lambda cfg: []
    project.round_kind = lambda rd: state["kind"]
    make_report.stale_problems = lambda cfg: state["stale"]
    make_report.pending_adjudication = lambda cfg, inp=None: state["pend"]
    make_report.unverified_problems = lambda cfg, inp=None: state["unver"]
    stops.redo_target = lambda cfg: state["redo"]
    globals()["_round_settled"] = lambda rd: state["settled"]
    try:
        chk("trial #11: Stage 5, a diff round on a docstring-only change (as --deliver's Lean check finds it): "
            "NEXT[no-round]", (run("diff") or "").startswith("NEXT[no-round] only comments and docstrings"))
        chk("trial #11: Stage 5, a full round when the last round is a settled full-scope round and only docstrings "
            "changed since (or nothing): NEXT[no-round], it is Stage 5's full-scope round",
            "it is Stage 5's full-scope round" in (run("full") or "")
            and "nothing changed since" in (run("full", commits=[]) or ""))
        chk("trial #11: no skip in Stage 4 (its full round comes in Stage 5), for a code change, with nothing changed "
            "(diff: the empty-scope route), with uncommitted changes, or when the change cannot be read",
            run("diff", st4) is None and run("full", st4) is None and run("diff", comment_only=False) is None
            and run("full", comment_only=False) is None and run("diff", commits=[]) is None
            and run("diff", dirty=["P.lean"]) is None and run("diff", problem="git failed") is None
            and run("diff", boom=True) is None)
        chk("trial #11: a full round still runs when the last round was a diff round, a statement round, or is not "
            "settled (an undecided REVOTE NEEDED, an unexpected UNCOVERED)",
            run("full", round="2026-01-01-aaaaaaa", kind="diff") is None and run("full", kind="statements") is None
            and run("full", settled="its REVOTE NEEDED row x | y is not decided") is None)
        chk("trial #11: no skip while --deliver would ask for a round (deliver-stale, unverified), an item awaits the "
            "next adjudication, or a set-aside's redo round is due",
            run("diff", stale=["1 Lean commit(s)"]) is None and run("full", unver=["x: out of date"]) is None
            and run("diff", pend=[("adj-record", "x")]) is None and run("full", redo="2026-01-01-bbbbbbb") is None)
    finally:
        (project.changes_after_last_audit, project.rounds, project.round_kind, make_report.stale_problems,
         make_report.pending_adjudication, make_report.unverified_problems, stops.redo_target,
         globals()["_round_settled"]) = keep
    d = tempfile.mkdtemp(prefix="scope-settled-")
    try:
        rd = os.path.join(d, "R", "2026-01-01-full-aaaaaaa")
        os.makedirs(rd)
        json.dump({"_meta": {"kind": "full"}, "correspondence": ["N.a"], "substantiveness": ["N.b"]},
                  open(os.path.join(rd, "TARGET.json"), "w"))
        head = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        rv = "| substantiveness | N.b | Fail | **REVOTE NEEDED** | re-vote it |\n"

        def settled(text):
            open(os.path.join(rd, "ADOPTED.md"), "w").write(text)
            return _round_settled(rd)
        nothing = _round_settled(rd)
        chk("trial #11: a round is settled only when adjudicated, every REVOTE NEEDED row has a later decision of its "
            "lane and item, and every UNCOVERED row is expected",
            nothing and settled(head + "| correspondence | N.a | Pass | **ADOPT** | docstring |\n") is None
            and settled(head + rv) and settled(head + rv + "\n## Re-vote adjudication\n\n" + head
                                               + "| substantiveness | N.b | Fail | **ADOPT** | r |\n") is None
            and settled(head + rv + "| correspondence | N.a | Fail | **ADOPT** | another item |\n")
            and settled(head + "| correspondence | N.a | STALE | **UNCOVERED** | gone |\n")
            and settled(head + "| correspondence | N.a | STALE | **UNCOVERED** | gone (expected: x) |\n") is None
            and settled(head + "| nolane | N.a | Fail | **ADOPT** | r |\n"))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return ok


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
        # Adversarial names: by NAME the h1 round is newer (later date); by Lean ancestry (and commit time) h2 is.
        names = [f"2026-01-02-{h1}", f"2026-01-01-{h2}"]
        for n_ in names:
            os.makedirs(os.path.join(rdir, n_))
            open(os.path.join(rdir, n_, "TARGET.json"), "w").write("{}")   # a round (project.is_round)
        cfg = {"name": "P", "lean_files": files, "rounds_dir": rdir, "base_commit": base,
               "lanes": ["correspondence", "paper-faithfulness", "prior-art"], "index_file": "P/Main.lean"}
        check("previous round = latest by LEAN ANCESTRY, not by name", previous_commit(cfg, d) == h2)
        # review of fix-mini1 (M1): fresh-reader prompts written with --round <new> at a later commit
        # are no round: the next diff round's base stays the last audited commit, so the edit between
        # is scoped
        os.makedirs(os.path.join(rdir, f"2026-01-04-{head}", "prompts"))
        check("a directory with only prompts at a later commit is not the diff base", previous_commit(cfg, d) == h2)
        open(os.path.join(rdir, f"2026-01-04-{head}", "ADOPTED.md"), "w").write("planted\n")
        check("...nor with a planted ADOPTED.md: only a round with TARGET.json is a diff base",
              previous_commit(cfg, d) == h2)
        shutil.rmtree(os.path.join(rdir, f"2026-01-04-{head}"))
        # RULINGS D2: a set-aside round between the last adjudicated round and the new one is no diff base
        open(os.path.join(rdir, names[1], project.ABANDONED), "w").write("{}")
        os.makedirs(os.path.join(rdir, f"2026-01-03-{head}"))
        open(os.path.join(rdir, f"2026-01-03-{head}", "TARGET.json"), "w").write("{}")
        check("a set-aside round in between: the diff base is the last round before it",
              previous_commit(cfg, d, exclude=f"2026-01-03-{head}") == h1)
        os.remove(os.path.join(rdir, names[1], project.ABANDONED))
        shutil.rmtree(os.path.join(rdir, f"2026-01-03-{head}"))
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
        check("--verify ignores _meta.redo_of (B1b: the redo lineage scope.py records)",
              not compare(dict(doc, _meta=dict(doc["_meta"], redo_of="2026-01-01-full-abcdef1")), doc))
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
        # trial #7: every refutation `not_<X>_as_printed` (a declaration at this commit) gives the paper-faithfulness
        # lane its F10 and F12 items, named as make_report checks them
        _basic = open(os.path.join(d, "P/Basic.lean"), encoding="utf-8").read()
        open(os.path.join(d, "P/Basic.lean"), "w").write(
            _basic.replace("end P\n", "theorem not_unrelated_as_printed : ¬ other = 4 := by decide\n\n"
                                      "theorem not_other_as_printed : ¬ other = 4 := by decide\n\nend P\n"))
        _cl = os.path.join(rdir, names[1], "correspondence.json")
        json.dump({"lane": "correspondence", "verdicts": [{"item": "P.other", "verdict": "Fail",
                                                           "comment": "`P.not_other_as_printed` compiles"}]},
                  open(_cl, "w"))
        # bench1: an earlier lane cited its probe files `trivial/<decl>__as_printed.lean`; the
        # refutation recogniser read `not_lem_9_2_as_printed__as_printed` as a refutation of `lem_9_2_as_printed_`
        # and every full round scheduled F10 items for declarations that do not exist
        import make_report
        _nv = os.path.join(rdir, names[1], "non-vacuity.json")
        json.dump({"lane": "non-vacuity", "verdicts": [{"item": "P.other", "verdict": "Pass", "comment": "probes "
                   "non-vacuity.probes/trivial/not_lem_9_2_as_printed__as_printed.lean, "
                   "trivial/not_lem_9_4_as_printed__as_printed.lean, trivial/not_prop_9_5_as_printed__as_printed.lean "
                   "and trivial/not_thing_zero__as_printed.lean exit 1"}]}, open(_nv, "w"))
        _full, _, _ = make_target(cfg, f"2026-01-02-full-{head}", "full", d, None)
        check("bench1: probe paths `<decl>__as_printed` (a refutation's name re-suffixed, or a `not_` theorem's) "
              "an earlier lane cited schedule no F10/F12 item; only the real refutations are scheduled",
              set(_full["_meta"]["f10"].values()) == {"not_unrelated_as_printed", "not_other_as_printed"}
              and not any("__as_printed" in x for x in _full["paper-faithfulness"])
              and all(make_report.AS_PRINTED.fullmatch(x) is None for x in
                      ("not_lem_9_2_as_printed__as_printed", "not_thing_zero__as_printed",
                       "not_prop_9_5_as_printed_as_printed", "not__x_as_printed"))
              and make_report.AS_PRINTED.fullmatch("not_prop_9_5_as_printed").group(1) == "prop_9_5")
        # bench2: a lane's probe `not_main_thm_as_printed` (a file name, no declaration) of
        # the refutation `ExamplePaper.not_MainThm_as_printed` gave every round an F10 item no reviewer could
        # judge (UNCOVERED, a standing defer, an alias theorem that tripped RED[drift]); now only the declaration's
        json.dump({"lane": "non-vacuity", "verdicts": [{"item": "P.other", "verdict": "Pass", "comment": "probe "
                   "probes/not_main_thm_as_printed.lean: `ExamplePaper.not_MainThm_as_printed` compiles; "
                   "not_main_thm_as_printed exits 0"}]}, open(_nv, "w"))
        open(os.path.join(d, "P/Basic.lean"), "a").write(
            "namespace ExamplePaper\ntheorem not_MainThm_as_printed : ¬ P.other = 4 := by decide\n"
            "end ExamplePaper\n")
        _b2, _, _ = make_target(cfg, f"2026-01-02-full-{head}", "full", d, None)
        _b2_eg = [i for i, n in _b2["_meta"]["f10"].items() if "mainthm" in n.lower()]
        _b2_lo = lane_only_refutations(cfg, d, f"2026-01-02-full-{head}")
        check("bench2: a probe name `not_main_thm_as_printed` in lane text schedules nothing; the declaration "
              "`ExamplePaper.not_MainThm_as_printed` gets exactly one F10 item; the probe name is a note",
              _b2_eg == ["F10: the counterexample of `not_MainThm_as_printed`"]
              and not any("main_thm" in x for x in _b2["paper-faithfulness"])
              and "not_main_thm_as_printed" in _b2_lo and "not_MainThm_as_printed" not in _b2_lo
              and "not_other_as_printed" not in _b2_lo)
        open(os.path.join(d, "P/Basic.lean"), "w").write(_basic.replace(
            "end P\n", "theorem not_unrelated_as_printed : ¬ other = 4 := by decide\n\n"
                       "theorem not_other_as_printed : ¬ other = 4 := by decide\n\nend P\n"))
        os.remove(_nv)
        _pf = _full["paper-faithfulness"]
        check("trial #7: a full round's paper-faithfulness scope has the F10 and F12 items of each refutation (a "
              "declaration), labelled from the index, and `_meta.f10` maps them",
              {"F10: the counterexample of Theorem 1.3", "F12: the repair of Theorem 1.3",
               "F10: the counterexample of Construction 1.5", "F12: the repair of Construction 1.5"} <= set(_pf)
              and _full["_meta"]["f10"] == {"F10: the counterexample of Theorem 1.3": "not_unrelated_as_printed",
                                            "F10: the counterexample of Construction 1.5": "not_other_as_printed"}
              and "F10: the counterexample of Theorem 1.3" not in _full["correspondence"])
        _old = json.loads(json.dumps(_full)); del _old["_meta"]["f10"]
        _old["paper-faithfulness"] = [x for x in _old["paper-faithfulness"] if not x.startswith(("F10:", "F12:"))]
        _drop = json.loads(json.dumps(_full))
        _drop["paper-faithfulness"] = [x for x in _drop["paper-faithfulness"] if x != "F10: the counterexample of Theorem 1.3"]
        _drop["_meta"]["f10"] = {k: v for k, v in (_drop["_meta"].get("f10") or {}).items()
                                 if k != "F10: the counterexample of Theorem 1.3"}
        check("trial #7: --verify accepts a round scoped before F10 scheduling (no `_meta.f10`) and refuses a scheduled "
              "item dropped", compare(_full, _full) == [] and compare(_old, _full) == [] and compare(_drop, _full) != [])
        # a diff round re-lists a refutation only while no paper-faithfulness lane has decided its F10 item, or
        # when the refutation or its result is in the round's scope
        open(os.path.join(rdir, names[1], "TARGET.json"), "w").write(json.dumps(
            {"paper-faithfulness": ["F10: the counterexample of Construction 1.5"],
             "_meta": {"kind": "diff", "f10": {"F10: the counterexample of Construction 1.5": "not_other_as_printed"}}}))
        _pfj = os.path.join(rdir, names[1], "paper-faithfulness.json")
        json.dump({"lane": "paper-faithfulness", "verdicts": [{"item": "F10: the counterexample of Construction 1.5",
                                                                "verdict": "Ambiguous"}]}, open(_pfj, "w"))
        # both refutations are uncommitted declarations (in any diff scope): the filter is read with only
        # `not_unrelated_as_printed` in the round's scope
        _rs = lambda: {"paper-faithfulness": list(refutation_scope(cfg, d, f"2026-01-02-{head}", "diff",
                                                                   ["P.not_unrelated_as_printed"], []))}
        _d1 = _rs()
        json.dump({"lane": "paper-faithfulness", "verdicts": [{"item": "F10: the counterexample of Construction 1.5",
                                                                "verdict": "Pass"}]}, open(_pfj, "w"))
        _d2 = _rs()
        check("trial #7: a diff round lists an undecided refutation's F10 item, and drops it once a lane decided it "
              "(its refutation and result out of scope)",
              "F10: the counterexample of Construction 1.5" in _d1["paper-faithfulness"]
              and "F10: the counterexample of Construction 1.5" not in _d2["paper-faithfulness"]
              and "F10: the counterexample of Theorem 1.3" in _d2["paper-faithfulness"])
        os.remove(_pfj); os.remove(_cl)
        open(os.path.join(rdir, names[1], "TARGET.json"), "w").write("{}")
        open(os.path.join(d, "P/Basic.lean"), "w").write(_basic)
        # preflight
        check("preflight: a round not cut from HEAD is refused",
              preflight(cfg, d, f"2026-01-02-{h1}", "diff") is not None)
        check("preflight: kind and round name must agree",
              preflight(cfg, d, f"2026-01-02-{head}", "full") is not None)
        # mini2 audit (time): the first round to examine proofs is the full-scope round
        check("mini2-B(b): a diff round with no earlier proof round (only statement rounds, or rounds of unknown "
              "kind) is refused: run the full-scope round",
              preflight(cfg, d, f"2026-01-02-{head}", "diff") == FIRST_PROOF_ROUND
              and preflight(cfg, d, f"2026-01-02-full-{head}", "full") is None)
        open(os.path.join(rdir, names[1], "TARGET.json"), "w").write('{"_meta": {"kind": "statements"}}')
        _st_only = preflight(cfg, d, f"2026-01-02-{head}", "diff")
        _st_vf = preflight(cfg, d, f"2026-01-02-{head}", "diff", verify=True)
        open(os.path.join(rdir, names[1], "TARGET.json"), "w").write('{"_meta": {"kind": "diff"}}')
        check("mini2-B(b): ... after a statement round still refused; after a proof round a diff round is accepted",
              _st_only == FIRST_PROOF_ROUND and first_proof_round_ok(cfg, d, f"2026-01-02-{head}"))
        check("review of fix-mini2 L2: --verify of a diff round scoped with no earlier proof round is not refused",
              _st_only == FIRST_PROOF_ROUND and _st_vf is None)
        check("preflight: a clean tree at HEAD is accepted", preflight(cfg, d, f"2026-01-02-{head}", "diff") is None)
        _near = head[:7] + ("0" if head[7] != "0" else "1") + head[8:11]
        check("A10e: a round whose commit agrees with HEAD in 7 characters only is refused (full-hash prefix)",
              preflight(cfg, d, f"2026-01-02-{_near}", "diff") is not None)
        open(os.path.join(d, "P/Basic.lean"), "a").write("\n-- uncommitted\n")
        check("preflight: uncommitted Lean changes are refused",
              "uncommitted" in (preflight(cfg, d, f"2026-01-02-{head}", "diff") or ""))
        # trial #10: the operator named its refutation `lemma_9_1_as_printed_false`; no lane got its F10 item and
        # the adjudicator could not record the row (a wasted statement round). Now the statement round is refused
        # before it is scoped, with the exact rename, and scoped once renamed
        run("checkout", "--", "P/Basic.lean")
        _t10 = "theorem {} :\n    ¬ ∀ n : Nat, n = 0 := by\n  intro h\n  exact absurd (h 1) (by decide)\n\nend P\n"
        open(os.path.join(d, "P/Basic.lean"), "w").write(_basic.replace("end P\n", _t10.format("lemma_9_1_as_printed_false")))
        run("commit", "-qam", "t10")
        _bad10 = preflight(cfg, d, f"2026-01-05-full-{git(d, 'rev-parse', '--short=11', 'HEAD').strip()}", "statements")
        open(os.path.join(d, "P/Basic.lean"), "w").write(_basic.replace("end P\n", _t10.format("not_lemma_9_1_as_printed")))
        run("commit", "-qam", "t10 renamed")
        _keep10 = project.REPO
        try:
            project.REPO = d
            _miss10 = preflight(cfg, d, f"2026-01-05-full-{git(d, 'rev-parse', '--short=11', 'HEAD').strip()}", "statements")
            _fresh_walk(cfg, d)
            _ok10 = preflight(cfg, d, f"2026-01-05-full-{git(d, 'rev-parse', '--short=11', 'HEAD').strip()}", "statements")
        finally:
            project.REPO = _keep10
        check("SWEEP-FIX D1 (G1): a statement round is refused while the assumption walk is missing (FAIL[index], the "
              "refresh command named), so the blockers are judged at scope, never first at approve",
              (_miss10 or "").startswith("FAIL[index] the assumption walk cannot be judged") and "phase0.py --statements" in _miss10)
        _doc10, _, _ = make_target(cfg, f"2026-01-05-full-{git(d, 'rev-parse', '--short=11', 'HEAD').strip()}",
                                   "statements", d, None)
        check("trial #10: a statement round with a refutation not named `not_<decl>_as_printed` is refused before it "
              "is scoped, naming the exact rename; renamed, it is scoped and the lane gets the refutation's F10 item",
              (_bad10 or "").startswith("FAIL[index]") and "`lemma_9_1_as_printed_false`" in _bad10
              and "rename it `not_lemma_9_1_as_printed`" in _bad10 and _ok10 is None
              and "not_lemma_9_1_as_printed" in (_doc10["_meta"].get("f10") or {}).values())
        # trial #10 audit: a Stage 4 diff round on a docstring-only commit, then Stage 5's full round on the same
        # commit (16 minutes repeated). Stage 4 now goes to Stage 5 instead; Stage 5 keeps its diff round
        _h0 = git(d, "rev-parse", "HEAD").strip()
        _src = open(os.path.join(d, "P/Basic.lean")).read()
        _cfg4 = dict(cfg, lean_files=["P/Basic.lean"])
        open(os.path.join(d, "P/Basic.lean"), "w").write(
            "-- a new comment\n" + _src.replace("theorem not_lemma", "/-- A changed docstring. -/\ntheorem not_lemma", 1))
        _sk4 = stage4_skip_line(_cfg4, d, _h0, "Stage 4 — audit rounds")
        _sk5 = stage4_skip_line(_cfg4, d, _h0, "Stage 5 — final round")
        open(os.path.join(d, "P/Basic.lean"), "w").write(_src.replace("intro h", "intro h\n  have _x := \"s\"", 1))
        _skc = stage4_skip_line(_cfg4, d, _h0, "Stage 4 — audit rounds")
        open(os.path.join(d, "P/Basic.lean"), "w").write(_src.replace("\nend P", '\ndef lit : String := "a"\nend P', 1))
        run("commit", "-qam", "lit")
        _h1 = git(d, "rev-parse", "HEAD").strip()
        open(os.path.join(d, "P/Basic.lean"), "w").write(_src.replace("\nend P", '\ndef lit : String := "b"\nend P', 1))
        _skl = stage4_skip_line(_cfg4, d, _h1, "Stage 4 — audit rounds")
        run("checkout", "--", "P/Basic.lean")
        check("trial #10 audit: in Stage 4 a diff round on a comment/docstring-only change is skipped for Stage 5's "
              "full round (NEXT[stage5]); in Stage 5 it runs; a code or string-literal change runs it",
              (_sk4 or "").startswith("NEXT[stage5]") and _sk5 is None and _skc is None and _skl is None)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    ok &= _cap_controls(check)
    ok &= _no_round_controls(check)
    ok &= _frozen_verify_controls(check)
    ok &= _bench2_redo_controls(check)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def _fresh_walk(cfg, repo, assumes=None, stale=False):
    """Write DEPENDENCIES.json as the walk of the Lean at HEAD of `repo` (project.REPO must be `repo`), untracked."""
    import dependencies
    p = os.path.join(repo, cfg["rounds_dir"], dependencies.OUT)
    json.dump({"lean_sha256": "0" * 64 if stale else dependencies.lean_hash(cfg, "HEAD"), "binders": {},
               "assumes": assumes or {}}, open(p, "w"))
    return p


def _cap_controls(check):
    """B13 (U2 §8, caps): the 5th statement round before the first approval is refused, and so is a 3rd of one
    re-approval; dev: a human stop (PROBLEM[round-cap]) only while the newest statement round leaves a correspondence or
    paper-faithfulness finding open (release: NOTE[round-cap], the operator judges, cap_record), otherwise
    NOTE[round-cap] (no stop: the conservative default); set-aside
    rounds are not counted; a statement round after an approval with no re-approval open is not capped."""
    import fingerprint
    d = tempfile.mkdtemp(prefix="scope-cap-")
    G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, env=_tick()).stdout.strip()
    keep = (project.REPO, fingerprint.open_reapproval, fingerprint.approval_history)
    res = []

    def say(name, cond):
        check(name, cond); res.append(bool(cond))
    try:
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        os.makedirs(os.path.join(d, "P")); open(os.path.join(d, "P", "RUN_LOG.md"), "w").write("# Run log\n")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = d
        cfg = {"name": "P", "rounds_dir": "P", "lean_files": []}
        fingerprint.open_reapproval = lambda *a_, **k_: (None, None)
        fingerprint.approval_history = lambda *a_, **k_: (False, {})
        open(os.path.join(d, ".git", "info", "exclude"), "a").write("/P/DEPENDENCIES.json\n")   # untracked, as in a run
        _fresh_walk(cfg, d)
        head = "ADOPTED"
        n = [0]

        def stmt(rows="", aside=False):
            n[0] += 1
            r = os.path.join(d, "P", f"2026-01-{n[0]:02d}-full-{n[0]:07x}")
            os.makedirs(r)
            json.dump({"_meta": {"kind": "statements"}}, open(os.path.join(r, "TARGET.json"), "w"))
            open(os.path.join(r, "ADOPTED.md"), "w").write(
                "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n" + rows)
            if aside:
                open(os.path.join(r, project.ABANDONED), "w").write("{}")
            G("add", "-A"); G("commit", "-qm", f"scope {os.path.basename(r)}")
        caps = []
        for i in range(3):
            stmt(); caps.append(statement_cap(cfg, d))
        stmt(aside=True); caps.append(statement_cap(cfg, d))
        stmt("| non-vacuity | P.t | Fail | **ADOPT** | vacuous |\n")
        c4 = statement_cap(cfg, d)
        h = G("rev-parse", "HEAD")
        pf = preflight(cfg, d, f"2026-02-01-full-{h[:11]}", "statements")
        say("B13 cap: 4 statement rounds before the first approval are allowed (a set-aside one not counted); "
                    "the 5th is refused with NOTE[round-cap] -- no faithfulness finding open, so no stop: the sheet of "
                    "the 4th round, its statement-changing ADOPT rows recorded as decisions taken at the cap",
                    caps == [None] * 4 and c4 and c4["cap"] == 4 and len(c4["rounds"]) == 4 and c4["open"] == []
                    and (pf or "").startswith("NOTE[round-cap]") and "no stop" in pf and "Open questions" in pf)
        # C2 audit: a hypothesis the current walk lists unclassified (P the paper's notation, no Definition row)
        # refuses the statement round before the cap is even looked at; a stale walk does not
        import dependencies
        dp_ = os.path.join(d, "P", dependencies.OUT)
        walk_ = {"lean_sha256": dependencies.lean_hash(cfg, "HEAD"), "commit": h, "binders": {},
                 "assumes": {"P.t": [{"name": "P.Dom", "binder": "hx", "kind": "prop", "type_pp": "x ∈ P.Dom n",
                                      "embedded": False}]}}
        json.dump(walk_, open(dp_, "w"))
        pf_b = preflight(cfg, d, f"2026-02-01-full-{h[:11]}", "statements")
        json.dump(dict(walk_, lean_sha256="0" * 64), open(dp_, "w"))
        pf_s = preflight(cfg, d, f"2026-02-01-full-{h[:11]}", "statements")
        os.remove(dp_)
        pf_m = preflight(cfg, d, f"2026-02-01-full-{h[:11]}", "statements")
        _fresh_walk(cfg, d)
        say("C2 audit: a statement round is refused (FAIL[index], before any lane) while the walk of HEAD lists a "
            "hypothesis nothing classifies (a definition with no index Definition row); SWEEP-FIX D1 (G1): a stale or "
            "missing walk is refused too (refresh it), never passed silently -- else the blocker surfaced first at "
            "approve, past the cap",
            (pf_b or "").startswith("FAIL[index] `P.Dom` (in `P.t`)") and "Definition (" in pf_b
            and (pf_s or "").startswith("FAIL[index] the assumption walk cannot be judged") and "phase0.py --statements" in pf_s
            and (pf_m or "").startswith("FAIL[index] the assumption walk cannot be judged"))
        # SWEEP-FIX D1 (G1): at the reached cap, approve refuses the last round for a mechanical reason -> one grace
        # round, recorded and committed; a stale bundle because the statements changed records none (its cure printed)
        import signoff
        last4 = (c4 or {"rounds": ["none"]})["rounds"][-1]
        gb_ = signoff.cap_grace(cfg, last4, "STATEMENTS_BUNDLE.md is stale", "bundle")
        no_grace = not os.path.exists(grace_path(os.path.join(d, "P"), last4)) and statement_cap(cfg, d) is not None
        lr_ = os.path.join(d, "P", last4)
        os.makedirs(lr_, exist_ok=True)     # (only a mutant leaves no capped round here)
        open(os.path.join(lr_, "STATEMENTS_BUNDLE.md"), "w").write("same\n")
        json.dump({"fingerprints": {}}, open(os.path.join(lr_, "FINGERPRINTS.json"), "w"))
        G("add", "-A"); G("commit", "-qm", f"scope {last4} (statements bundle)")
        _fresh_walk(cfg, d, assumes=walk_["assumes"])
        sk_ = (signoff.build_bundle, signoff.check, project.select)
        signoff.build_bundle = lambda cfg_, table=None: ("same\n", [], [])
        signoff.check = lambda *a_, **k_: []
        project.select = lambda name=None: (cfg, "stub")
        import io, contextlib
        o_ = io.StringIO()
        try:
            with contextlib.redirect_stdout(o_), contextlib.redirect_stderr(o_):
                rc_ = signoff.main(["approve", "--round", last4, "--how", "blanket", "--by", "agent"])
        finally:
            signoff.build_bundle, signoff.check, project.select = sk_
        gr_ = grace_of(os.path.join(d, "P"), last4)
        c4g = statement_cap(cfg, d)
        _fresh_walk(cfg, d)
        pf_g = preflight(cfg, d, f"2026-02-01-full-{G('rev-parse', 'HEAD')[:11]}", "statements")
        say("SWEEP-FIX D1 (G1): at the reached cap, approve refused for a statement blocker records one grace round "
            "(round-caps/grace/<R>.json, \"round-cap <R> grace\") and scope allows one more statement round; a stale "
            "bundle with the statements changed records none and prints the restore",
            no_grace and "git checkout" in gb_ and rc_ == 1 and "approval REFUSED" in o_.getvalue()
            and "grace" in o_.getvalue() and gr_ and c4 and gr_.get("rounds") == c4["rounds"]
            and G("log", "-1", "--format=%s") == f"round-cap {last4} grace" and c4g is None and pf_g is None
            and grace_record(cfg, d, (c4 or {"rounds": ["none"]})["rounds"][0], "x") is None
            and grace_rows(cfg, d) == [(last4, gr_["reason"])] and gr_["reason"].startswith("FAIL[index] `P.Dom`"))
        stmt("| correspondence | P.t | Fail | **ADOPT** | wrong bound |\n| paper-faithfulness | Lemma 2 | Fail | **QUESTION** | x |\n")
        c5 = statement_cap(cfg, d)
        pf5 = preflight(cfg, d, f"2026-02-01-full-{G('rev-parse', 'HEAD')[:11]}", "statements")
        say("B13 cap, dev: with a faithfulness finding open in the newest statement round the cap is a human stop "
                    "(PROBLEM[round-cap], stops.py open --cause round-cap); the grace round is named in the message",
                    c5 and len(c5["open"]) == 2 and (pf5 or "").startswith("PROBLEM[round-cap]") and "--cause round-cap" in pf5
                    and c5.get("graces") == [last4] and "1 grace round(s)" in pf5 and len(c5["rounds"]) == 5
                    and project.is_stop_cause("round-cap") and project.round_cap_route(cfg) == "stop")
        # review M5(a): graces are bounded (GRACE_CAP per cap); past them the refusal names the tool-patch route
        g_ = globals()
        keep_m5 = (g_["STATEMENT_CAP"], g_["grace_of"], g_["grace_record"])
        try:
            g_["STATEMENT_CAP"], g_["grace_of"] = 1, (lambda rdir, rnd: {"round": rnd, "rounds": [rnd]})
            c_m5 = statement_cap(cfg, d)
            sp_m5 = keep_m5[2](cfg, d, (c_m5 or {"rounds": ["?"]})["rounds"][-1], "x")
        finally:
            g_["STATEMENT_CAP"], g_["grace_of"] = keep_m5[0], keep_m5[1]
        say("review M5(a): at most GRACE_CAP grace rounds count per cap; past them no grace is recorded (GRACE_SPENT)",
            c_m5 is not None and len(c_m5["graces"]) == GRACE_CAP and sp_m5 == GRACE_SPENT)
        # review M5(b): a fingerprint changed while the Lean is unchanged and a tool patch was applied since: a grace
        import signoff as _so, scope as _sc
        keep_m5b = (_so.lean_unchanged_since, _so.patched_since, _sc.grace_record)
        try:
            _sc.grace_record = lambda *a_, **k_: os.path.join(d, "P", ROUND_CAPS, GRACE, "x.json")
            _so.lean_unchanged_since, _so.patched_since = (lambda c_, r_: True), (lambda c_, r_: True)
            fpg = _so.cap_grace(cfg, c5["rounds"][-1], "P.t: changed since the sheet was generated", "fingerprint")
            _so.patched_since = lambda c_, r_: False
            fpn = _so.cap_grace(cfg, c5["rounds"][-1], "P.t: changed since the sheet was generated", "fingerprint")
        finally:
            _so.lean_unchanged_since, _so.patched_since, _sc.grace_record = keep_m5b
        say("review M5(b): at the cap, a fingerprint changed by a patched printer (Lean unchanged, a tool patch since) "
            "earns a grace round; without a patch since, none", "grace" in fpg and fpn == "")
        # approver 2026-10-24 (decision 3): release judges the cause -- no stop of its own; the three routes are
        # named; the open findings are recorded (round-caps/<round>.json, "round-cap <round>") for result_status
        rel = dict(cfg, mode="release")
        pr5 = preflight(rel, d, f"2026-02-01-full-{G('rev-parse', 'HEAD')[:11]}", "statements")
        rp = cap_record(rel, d, statement_cap(rel, d))
        rp2 = cap_record(rel, d, statement_cap(rel, d))
        rec = json.load(open(rp)) if rp else {}
        say("approver decision 3: in release the cap with a faithfulness finding open is NOTE[round-cap] (no stop): "
            "the operator judges -- a genuine ambiguity is stop 4 (--cause ambiguity), a loose convention a reading "
            "choice, anything else goes on with each result open reading 'not established: open faithfulness "
            "finding'; the open findings are recorded once, committed as \"round-cap <round>\"; dev unchanged",
            (pr5 or "").startswith("NOTE[round-cap]") and "--cause ambiguity" in pr5 and "reading choice" in pr5
            and "not established: open faithfulness finding" in pr5 and "--cause round-cap" not in pr5
            and project.RELEASE.get("round-cap") == ("N", "disclose") and rp and rp == rp2
            and rec.get("open") == c5["open"] and G("log", "-1", "--format=%s") == f"round-cap {c5['rounds'][-1]}"
            and cap_record(cfg, d, statement_cap(cfg, d)) is None)
        hoff, sonly = dict(cfg, involvement="hands-off"), dict(cfg, involvement="statements-only")
        c5h, c5s = statement_cap(hoff, d), statement_cap(sonly, d)
        stmt("| paper-faithfulness | Lemma 2 | Ambiguous | **QUESTION** | two readings; take the weaker |\n")
        c6, c6h = statement_cap(cfg, d), statement_cap(hoff, d)
        pf6h = preflight(hoff, d, f"2026-02-01-full-{G('rev-parse', 'HEAD')[:11]}", "statements")
        say("review fix 8: a QUESTION row the level lets the agent decide (hands-off) is not an open faithfulness "
            "finding at the cap: a reading-choice QUESTION alone is NOTE[round-cap] (no open finding) under hands-off; "
            "under involved and statements-only (a statement round's question is the human's) it stays open; an "
            "ADOPT row stays open at every level",
            c5h and [k.split(" :: ")[0] for k in c5h["open"]] == ["correspondence"] and len(c5s["open"]) == 2
            and c6 and len(c6["open"]) == 1 and c6h and c6h["open"] == [] and (pf6h or "").startswith("NOTE[round-cap]"))
        say("B13 cap: --verify of a capped statement round is never refused (the cap applies to scoping only)",
                    preflight(cfg, d, f"2026-02-01-full-{G('rev-parse', 'HEAD')[:11]}", "statements", verify=True) is None)
        fingerprint.approval_history = lambda *a_, **k_: (True, {"by": "human"})
        say("B13 cap: after an approval, with no re-approval open, statement rounds are not capped",
                    statement_cap(cfg, d) is None)
        open(os.path.join(d, "P", fingerprint.REAPPROVAL), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", fingerprint.REAPPROVAL_BEGIN + ": N.main)")
        fingerprint.open_reapproval = lambda *a_, **k_: ({"decls": ["N.main"]}, None)
        r0 = statement_cap(cfg, d)
        stmt(); r1 = statement_cap(cfg, d)
        stmt(); r2 = statement_cap(cfg, d)
        say("B13 cap: a re-approval has its own cap of 2 statement rounds (earlier rounds not counted): the 3rd "
                    "of it is refused",
                    r0 is None and r1 is None and r2 and r2["cap"] == 2 and len(r2["rounds"]) == 2
                    and "re-approval" in r2["what"] and r2["open"] == [])
        # SWEEP-FIX D1 (G2): the re-approval cap has the same grace (only for its own last round)
        r2l = (r2 or {"rounds": ["none"]})["rounds"][-1]
        rg = grace_record(cfg, d, r2l, "FAIL[index] x")
        r3 = statement_cap(cfg, d)
        stmt(); r4 = statement_cap(cfg, d)
        say("SWEEP-FIX D1 (G2): a mechanical refusal at the re-approval cap gives one grace round there too",
            rg and r3 is None and r4 and r4["graces"] == [r2l] and len(r4["rounds"]) == 3)
    finally:
        project.REPO, fingerprint.open_reapproval, fingerprint.approval_history = keep
        shutil.rmtree(d, ignore_errors=True)
    return all(res)


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

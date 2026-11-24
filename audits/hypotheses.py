#!/usr/bin/env python3
"""What the formalization assumes, and the adjudicator's record of each hypothesis (U2 §2).

The ASSUMPTION WALK (dependencies.py, dependencies_tail.lean) reads off the Lean, per index result,
every hypothesis that uses a project constant no Definition row covers: Prop binders, the Prop parts
of data binders (F2), the Prop fields of structure and class binders, a binder of any sort whose type
contains anywhere (or through a project definition it uses) a project structure or class with a Prop
field, directly or through its fields (under the structure's name), and project Prop
constants left in the body (F3). It is written to <ROUNDS-DIR>/DEPENDENCIES.json `assumes` ({result: [{name, binder,
kind, type_pp, embedded}]}). This module reads it and the HYPOTHESIS RECORDS:

  a `## Hypotheses` table in a round's ADOPTED.md (the adjudicator's; AUDIT_PROTOCOL.md step 4 G):
  | hypothesis | stands for (source) | matches source | consistency evidence | trivialization |
  | plain English | supporting verdict |
  keyed by the hypothesis's Lean name (as the walk prints it, or relative to the namespace).

  - `matches source` is `yes`, `no` or `source unavailable` (a word after it, `yes (…)`, is kept).
  - The latest row for a name (rounds in project.order_rounds order, rows in file order) must cite,
    in `supporting verdict`, the paper-faithfulness verdict behind its `matches source` value: a
    paper-faithfulness (or literature-match) lane JSON of that round (`paper-faithfulness.json`,
    `paper-faithfulness@2.json`, `revote/...`) or of a named round (`<round>/paper-faithfulness.json`)
    that exists and names the hypothesis (F15). An invalid latest row does not win: it is a record
    fault until a later row replaces it (ADOPTED.md is never edited after its commit).
  - `source unavailable` is valid only after paper-faithfulness CONFIRMED that H matches the paper's
    quoted invocation (F14): the cited verdict has a Pass entry naming H and no Fail or Ambiguous entry
    naming it; `yes` likewise needs such a Pass (review fix 2). Page 1 (trust section) counts the
    matching rows, these rows, and the ones whose source does not match.
  - A verdict given before H's content changed supports nothing: H's fingerprint (the result's, for an
    inline `<result>:<binder>`) in the cited verdict's round FINGERPRINTS.json must equal the newest
    round's (rounds without a FINGERPRINTS.json, or H in neither, are not compared).
  - An assumed name with no valid latest row is PENDING[adj-record] (`findings`), never RED: the next
    adjudicator writes it, in a diff round too; `integrity.py --commit-adjudication` and
    `project.py --deliver` refuse while one remains.
  - Plain English comes only from the adjudicator's cell; the report and the lanes' summary print it
    beside the Lean type, which the correspondence lane checks it against.

CLASSIFICATION of an assumed name: a paper notion (a Definition row; the walk never lists one, so
only an "added since approval" binder is one), a literature hypothesis (config
`literature_hypotheses`), a missing-theory hypothesis (missing_theory_names: the canonical
RUN_LOG.md line, B6 below), or UNCLASSIFIED (a project predicate taken as a hypothesis):
listed, never dropped. An unclassified name blocks the statement stage (statement_blockers: scope.py
--statements and signoff.py approve refuse, C2 audit), so the sheet a human approves already carries
its index Definition row or its classification; the code never judges which route is right.

  hypotheses.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import glob, json, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

COLS = ("hypothesis", "stands for", "matches source", "consistency evidence", "trivialization",
        "plain english", "supporting verdict")
TEMPLATE = ("| hypothesis | stands for (source) | matches source | consistency evidence | trivialization | "
            "plain English | supporting verdict |")
FAITH_LANES = ("paper-faithfulness", "literature-match")
CITE_RE = re.compile(r"((?:[\w.@-]+/)*[\w.@-]+\.json)")
_EDGE = re.compile(r"^[\s*_`]+|[\s*_`]+$")


def clean(c):
    return _EDGE.sub("", str(c))


rounds_dir = project.rounds_dir


def walk(cfg, rd=None):
    """(DEPENDENCIES.json as a dict, None) or (None, why not)."""
    import dependencies
    p = os.path.join(rd or rounds_dir(cfg), dependencies.OUT)
    if not os.path.exists(p):
        return None, f"no {dependencies.OUT} (Phase 0 writes it)"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except ValueError:
        return None, f"{dependencies.OUT} is malformed"
    if not isinstance(d, dict) or not isinstance(d.get("assumes"), dict):
        return None, f"{dependencies.OUT} has no assumption walk (written before it existed): rerun Phase 0"
    return d, None


def flags(doc, root, binder):
    """[why] the walk found binder `binder` of `root` suspect: it IS the conclusion (DEPS-GOAL), or it is
    (closed) the statement of another index result (DEPS-RESTATES) -- the benchmarks "H = goal" and
    "H restates a paper lemma"."""
    if not binder:
        return []
    out = [f"IS THE CONCLUSION of `{root}`"] if any(_same_binder(b, binder) for b in
                                                    ((doc or {}).get("goal") or {}).get(root, [])) else []
    return out + [f"restates `{x.get('result')}`" for x in ((doc or {}).get("restates") or {}).get(root, [])
                  if isinstance(x, dict) and _same_binder(x.get("binder"), binder)]


def _same_binder(a, b):
    """Binder `a` and `b` are one binder: equal, or one a field (`S.h1`) of the other (`S`) -- a
    structure binder's fields are checked one by one and as their conjunction (review fix 1)."""
    a, b = str(a or ""), str(b or "")
    return bool(a) and bool(b) and (a == b or a.startswith(b + ".") or b.startswith(a + "."))


def assumed(doc):
    """{hypothesis name: [(result, entry)]} from the walk. A binder the walk flags (`flags`) whose
    type uses no project constant (so no entry names it: `(h : ∀ n, n + 0 = n)`) is assumed too, under
    the name `<result>:<binder>` (kind `inline`): it needs a row like any hypothesis."""
    out = {}
    for root, ents in sorted((doc or {}).get("assumes", {}).items()):
        for e in ents or []:
            if isinstance(e, dict) and e.get("name"):
                out.setdefault(e["name"], []).append((root, e))
    named = {(r, e.get("binder")) for uses in out.values() for r, e in uses}
    for root in sorted(set(((doc or {}).get("goal") or {})) | set(((doc or {}).get("restates") or {}))):
        bs = list((doc.get("goal") or {}).get(root, [])) + [x.get("binder") for x in (doc.get("restates") or {}).get(root, [])
                                                             if isinstance(x, dict)]
        for b in sorted({b for b in bs if b}):
            if any(r == root and _same_binder(b, nb) for r, nb in named):
                continue
            ty = next((x.get("type_pp", "?") for x in (doc.get("binders") or {}).get(root, [])
                       if isinstance(x, dict) and x.get("binder") == b), "?")
            n = f"{root}:{b}"
            out.setdefault(n, []).append((root, {"name": n, "binder": b, "kind": "inline", "type_pp": ty,
                                                 "embedded": False}))
    return out


def name_flags(doc, uses):
    """The `flags` of every use of one assumed name."""
    return sorted({f for r, e in uses for f in flags(doc, r, e.get("binder"))})


def same_name(key, name, ns):
    """A row key names the walk's `name`: exactly, or relative to the project namespace."""
    k = clean(key)
    return bool(k) and (k == name or (bool(ns) and f"{ns}.{k}" == name))


# --- B6 (U2 §7, F13): missing theory -----------------------------------------------------------------
# A result whose proof needs theory no configured library has (RUN.md, "Missing theory"). Under a
# delegating level the operator searches every configured library, estimates the work, BUILDS the theory
# when only definitions and easy lemmas are missing, and otherwise takes the missing result as a NAMED
# HYPOTHESIS: a project Prop definition `H`, taken as a binder of the result's statement (so the walk
# lists it). Never a stop; never "do not formalize". The decision is one RUN_LOG.md line, a top-level list
# item (any section but `## Fresh readers`), in the canonical form
#   - [DELEGATED <date>, operator under <level> (intake); reversal: <cost>] missing theory: assume `<H>`
#     for `<R>` — searched: <every configured library, and how>; estimate: <size and time to build it>;
#     paper: "<the paper's passage invoking the result without proof>"
#   - [DELEGATED …] missing theory: build <what> for `<R>` — searched: <…>; estimate: <…>
# (one line each; `--` or `-` for the dash). Under `involved` (and `statements-only` before the
# Checkpoint B answer) the human chose at Checkpoint B (stage2-statements.md step 6) and the operator
# records what was done as `- missing theory (human <date>): assume `<H>` for `<R>` — …` (same fields).
# The scripts check the line's form, the quote's presence, the search of every configured library, and
# that `H` is in `R`'s assumption list (the walk); whether the paper really invokes the result without
# proving it, and whether `H` says no more than the quoted invocation, is the paper-faithfulness lane's
# judgement (F13), recorded in the hypothesis's `## Hypotheses` row like any other hypothesis. A line
# not in the canonical form is cleared by a later canonical line naming one of its backticked results or hypotheses
# (a logged line is never reworded in place, E2E-FIX2 L2; a reworded one is still read, so an older run is not
# refused; the latest line per hypothesis, or per result for `build`, counts). Otherwise the check only SUSPECTS it
# from its words (DESIGN-MT): whether it records a missing-theory decision at all is a meaning question, so it is
# no FAIL but an adj-record finding (PENDING[adjudication]) the next adjudicator rules once in ADOPTED.md's notes,
#   - MT RULED <line id> | not a missing-theory decision: <why>
#   - MT RULED <line id> | a missing-theory decision for `<Lean name>`: <why>
# bound to the line's text (mt_line_id). Ruled "not", it is cleared; ruled a decision for `N`, it is the
# operator's FAIL[missing-theory] until a canonical line for `N` is logged after it (which makes the F13 item).
MT_CODE = "missing-theory"
MT_TRIGGER = re.compile(r"missing[- ](?:library[- ])?theory", re.I)
_LEAN_ID = r"[A-Za-z_][\w'.₀-₉]*"
MT_BODY_RE = re.compile(
    r"\s*(?:(?:(?P<assume>assume)\s+`(?P<hyp>" + _LEAN_ID + r")`|(?P<build>build)\s+(?P<what>.+?))\s+for"
    r"|(?P<skip>do\s+not\s+formalize))\s+`(?P<result>" + _LEAN_ID + r")`\s*(?:—|–|--|-)\s*searched:\s*(?P<searched>.+?)\s*;\s*estimate:\s*(?P<estimate>.+?)\s*"
    r"(?:;\s*paper:\s*[\"“](?P<quote>.*)[\"”])?\s*\.?\s*$")
MT_HUMAN_RE = re.compile(r"[-*][ \t]+missing theory \(human (?P<date>\d{4}-\d{2}-\d{2})\):")
MT_HUMAN_LOOSE_RE = re.compile(r"[-*][ \t]+missing[- ]theory\s*\(\s*human\b", re.I)
# The paper-faithfulness lane's item for a missing-theory hypothesis (F13): scope.py schedules it in every round
# (TARGET.json, `_meta.f13`), prompt.py lists it under MISSING THEORY TO JUDGE, and a `## Hypotheses` row saying
# `yes` or `source unavailable` for the hypothesis needs a Pass on it (cite_problem; prompt.LANE_ITEM_PATHS)
F13_ITEM = "F13: the missing theory {}"
MT_QUOTE_MIN = 12          # characters of a quote, spaces aside: a word or two is no passage
MT_FORM = ("[DELEGATED <date>, operator under <level> (intake); reversal: <cost>] missing theory: assume `<H>` for "
           "`<R>` — searched: <every configured library, and how>; estimate: <size and time to build it>; paper: "
           "\"<the paper's passage invoking the result without proof, in plain text: formulas in Unicode>\"  (or: "
           "missing theory: build <what> for `<R>` "
           "— searched: …; estimate: …)")
# the adjudicator's ruling on a line the missing-theory check only suspects (DESIGN-MT; as QUOTE RULED)
MT_RULED_RE = re.compile(r"^\s*(?:[-*]\s*)?MT RULED\s+([0-9a-f]{12})\s*\|\s*"
                         r"(not a missing-theory decision\s*:\s*\S.*"
                         r"|a missing-theory decision for\s+`(" + _LEAN_ID + r")`\s*:\s*\S.*)$", re.M)
MT_RULED_LOOSE_RE = re.compile(r"^\s*(?:[-*]\s*)?MT RULED\b.*$", re.M)
MT_SUSPECT_HEAD = "may record a missing-theory decision outside the canonical form"


def mt_line_id(line):
    """12 hex of sha256: the binding of an MT RULED ruling. Of a decision line that OPENS with its [DELEGATED] tag
    (decisions.LEAVE_PREFIX_RE: `- [DELEGATED …`, `- <anchor>: [DELEGATED …`, `- answered <anchor> (…): [DELEGATED
    …`), its anchor (none for a plain line) and its text from the tag on, so a Checkpoint C line and its
    word-for-word `## Answered` copy share one ruling (review C2); of any other line (a human line that quotes a tag
    mid-text included, safety review F4), the whole line. Whitespace collapsed; any other change needs its own ruling."""
    import decisions, hashlib
    s = " ".join(str(line).split())
    p = decisions.LEAVE_PREFIX_RE.match(s)
    if p:
        a = decisions.DELEGATED_PRE_RE.match(s)
        s = (a.group(1) if a else "") + "\n" + s[p.end():]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


_MT_RULINGS = {}
MT_DISSENT_RE = re.compile(r"^\s*[-*]\s+MT DISSENT\s+([0-9a-f]{12})\s*:\s*\S.*$", re.M)


def _mt_ruled(text, rname, commit=None, prompt=None):
    """{line id: (round, "not" | "decision", name or None, commit)} of one ADOPTED.md text (a decision beats a "not"
    in one file); with `prompt` (the adjudicator prompt's text) only the ids it lists (safety review F1)."""
    out = {}
    for m in MT_RULED_RE.finditer(text or ""):
        if prompt is not None and f"MT RULED {m.group(1)}" not in prompt:
            continue        # an id this adjudicator was never shown is no ruling of its
        kind = "decision" if m.group(3) else "not"
        if kind == "not" and out.get(m.group(1), (None, None))[1] == "decision":
            continue
        out[m.group(1)] = (rname, kind, m.group(3), commit)
    return out


def _round_prompt(repo, rdir, name):
    """The text of a round's adjudicator prompt prompts/<name> (written once by `prompt.py 4 --write`): as
    committed when tracked, else on disk; None when there is none."""
    import lane_auth
    pp = os.path.join(rdir, "prompts", name)
    try:
        rel = os.path.relpath(pp, repo)
        if lane_auth.git(repo, "ls-files", "--", rel):
            return lane_auth.git(repo, "show", f"HEAD:{rel}")
    except lane_auth.AuthError:
        pass
    try:
        return open(pp, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return None


def _revote_lanes_in(repo, commit, rrel):
    """Does `commit`'s tree hold re-vote lane files of the round at `rrel` (<round>/revote/*.json)? A re-vote
    adjudication with none adjudicated no re-vote (review N1: `--commit-adjudication --revotes` alone is no ruling)."""
    import lane_auth
    try:
        names = lane_auth.git(repo, "ls-tree", "-r", "--name-only", commit, "--", f"{rrel}/revote/")
    except lane_auth.AuthError:
        return False
    return any(n.endswith(".json") and "/.lane-" not in n for n in names.splitlines())


def mt_ruling_history(cfg, rd=None, round_name=None):
    """{line id: [(round, "not" | "decision", name or None, commit or None), …]} in round order (set-aside rounds
    aside). A round's ruling is read from its ADOPTED.md AS OF its first `adjudicate R` commit (then its first
    `adjudicate R revotes` commit, which may re-rule only when that commit holds the round's re-vote lane files,
    review N1), never from a later re-commit (safety review F1), and counts
    only for an id its adjudicator prompt (prompts/adjudicator.txt, adjudicator-revotes.txt) lists. `round_name`'s
    ADOPTED.md counts as it is on disk (the adjudication about to be committed), against its prompt on disk. An MT
    RULED line anywhere else is never read. Any git error: {} (unruled, i.e. pending, never a hard fault). Memoized
    per process on HEAD and the files' state."""
    import lane_auth
    rd = os.path.abspath(rd or rounds_dir(cfg))
    try:
        dirs = [p for p in glob.glob(os.path.join(rd, "*")) if project.is_round(p) and not project.is_abandoned(p)]
        repo = str(lane_auth.audit_repo(lane_auth.Path(rd)))
        head = lane_auth.git(repo, "rev-parse", "HEAD")
    except (lane_auth.AuthError, OSError):
        return {}
    fs = [os.path.join(p, f) for p in sorted(dirs) for f in ("ADOPTED.md", "prompts/adjudicator.txt",
                                                             "prompts/adjudicator-revotes.txt")]
    key = (rd, round_name, head, tuple((f, os.stat(f).st_mtime_ns, os.stat(f).st_size) for f in fs if os.path.isfile(f)))
    if key in _MT_RULINGS:
        return _MT_RULINGS[key]
    out = {}
    try:
        for p in project.order_rounds(dirs, project.REPO):
            ap, rname = os.path.join(p, "ADOPTED.md"), os.path.basename(p)
            got = []
            if rname == round_name:
                if os.path.isfile(ap):
                    text = open(ap, encoding="utf-8").read()
                    pr = "\n".join(x for x in (_round_prompt(repo, p, "adjudicator.txt"),
                                               _round_prompt(repo, p, "adjudicator-revotes.txt")) if x)
                    got.append(_mt_ruled(text, rname, None, pr))
            else:
                rel = os.path.relpath(ap, repo)
                log = lane_auth.git(repo, "log", "--reverse", "--format=%H %s", "--", rel)
                for subj, pname in ((f"adjudicate {rname}", "adjudicator.txt"),
                                    (f"adjudicate {rname} revotes", "adjudicator-revotes.txt")):
                    c = next((l_.split(" ", 1)[0] for l_ in log.splitlines() if l_.split(" ", 1)[-1] == subj), None)
                    if c and subj.endswith(" revotes") and not _revote_lanes_in(repo, c, os.path.relpath(p, repo)):
                        c = None    # review N1: a re-vote adjudication rules only with the re-vote lanes it adjudicated
                    if c:
                        got.append(_mt_ruled(lane_auth.git(repo, "show", f"{c}:{rel}"), rname, c,
                                             _round_prompt(repo, p, pname) or ""))
            for g in got:
                for i_, r_ in g.items():
                    h_ = out.setdefault(i_, [])
                    if h_ and h_[-1][0] == rname:
                        h_[-1] = r_         # the re-vote adjudication re-rules within its round
                    else:
                        h_.append(r_)
    except (lane_auth.AuthError, OSError, UnicodeDecodeError):
        return {}
    _MT_RULINGS[key] = out
    return out


def _mt_dissents(cfg, log, rd, hist):
    """{line id: why} of the operator's `- MT DISSENT <id>: <why>` lines that stand AFTER the id's only "decision"
    ruling (absent from RUN_LOG.md as of that ruling's commit; review C-F2). A second "decision" ruling of the same
    id, or a ruling of the round being committed, admits no dissent."""
    import lane_auth
    out = {}
    for m in MT_DISSENT_RE.finditer(log or ""):
        h_ = hist.get(m.group(1)) or []
        if not h_ or h_[-1][1] != "decision" or sum(1 for x in h_ if x[1] == "decision") != 1 or not h_[-1][3]:
            continue
        try:
            repo = str(lane_auth.audit_repo(lane_auth.Path(rd)))
            then = lane_auth.git(repo, "show", f"{h_[-1][3]}:{os.path.relpath(os.path.join(rd, 'RUN_LOG.md'), repo)}")
        except lane_auth.AuthError:
            then = ""
        if m.group(0).strip() not in {l_.strip() for l_ in then.splitlines()}:
            out[m.group(1)] = m.group(0).split(":", 1)[1].strip()
    return out


def mt_ruling_problems(cfg, rd=None, round_name=None):
    """[Finding adj-record] of `round_name`'s ADOPTED.md only (never retroactive; None: []): an MT RULED line not
    in either form, and a "decision for `N`" whose `N` the project does not declare (the operator's canonical
    line must name a real declaration, so the follow-up stays curable)."""
    if not round_name:
        return []
    ap = os.path.join(rd or rounds_dir(cfg), round_name, "ADOPTED.md")
    try:
        text = open(ap, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    good = {m.start() for m in MT_RULED_RE.finditer(text)}
    for m in MT_RULED_LOOSE_RE.finditer(text):
        if m.start() not in good:
            out.append(f"{round_name}/ADOPTED.md: {m.group(0).strip()!r} is not an MT RULED ruling: write `- MT RULED "
                       f"<line id> | not a missing-theory decision: <why>` or `- MT RULED <line id> | a missing-theory "
                       f"decision for `<Lean name>`: <why>` (the id as the PENDING line gives it)")
    named = [m.group(3) for m in MT_RULED_RE.finditer(text) if m.group(3)]
    if named:
        import make_report
        declared = make_report.declared_names(cfg.get("lean_files") or [])
        ns = cfg.get("namespace", "")
        for n in named:
            if not ({n, f"{ns}.{n}" if ns else n} & declared):
                out.append(f"{round_name}/ADOPTED.md: MT RULED names `{n}`, which this project does not declare: name "
                           f"the Lean result (or hypothesis) the line decides missing theory for, as declared")
    return [project.Finding("! " + t, "adj-record") for t in out]


def _mt_attempt(rest):
    """Does the text after a [DELEGATED] tag decide missing theory? It opens with "missing theory", or
    names missing theory (not negated: "not missing theory"), or takes a hypothesis because a library lacks
    something (make_report.MISSING_THEORY_RE): a bare line in its own words is still one, and is refused.
    A re-approval's line (`change <decls> — <reason>`, signoff.py reapprove --begin) and a left-unproved
    line (`leave <decl> unproved — …`) are other decisions, whatever their reason says."""
    import make_report
    if re.match(r"\s*missing[- ](?:library[- ])?theory", rest, re.I):
        return True
    if re.match(r"\s*(?:change|leave)\b", rest, re.I):
        return False        # a re-approval's or a left-unproved line, whatever its reason says
    if any(not re.search(r"\b(?:not|no|never)\s+(?:an?\s+|for\s+|by\s+)?$", rest[:m.start()], re.I)
           for m in MT_TRIGGER.finditer(rest)):
        return True
    return bool(make_report.MISSING_THEORY_RE.search(rest) and re.search(r"\bhypothes", rest, re.I))


def _mt_log(cfg, log=None, rd=None):
    if log is not None:
        return log
    p = os.path.join(rd or rounds_dir(cfg), "RUN_LOG.md")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def missing_theory_lines(log):
    """[(kind, match of the body or None, the line, by)] for every missing-theory decision line of `log`, in
    order (`## Fresh readers` aside, which quotes). kind: "delegated" or "human"; by: the tag or "human
    <date>". A line that tries the form and misses it has match None."""
    import decisions
    out, sec = [], None
    for line in log.splitlines():
        if line.startswith("## "):
            sec = line[3:].strip()
            continue
        if sec is not None and sec.startswith("Fresh readers"):
            continue
        p = decisions.LEAVE_PREFIX_RE.match(line)
        if p:
            t = decisions.DELEGATED_TAG_RE.match(line, p.end())
            rest = line[t.end():] if t else line[p.end():]
            if not _mt_attempt(rest):
                continue
            m = re.match(r"\s*missing theory:", rest) if t else None
            out.append(("delegated", MT_BODY_RE.match(rest, m.end()) if m else None, line.strip(),
                        t.group(0) if t else None))
            continue
        h = MT_HUMAN_RE.match(line)
        if h:
            out.append(("human", MT_BODY_RE.match(line, h.end()), line.strip(), f"human {h.group('date')}"))
        elif MT_HUMAN_LOOSE_RE.match(line):
            out.append(("human", None, line.strip(), None))
    return out


def _short(n):
    return str(n or "").rsplit(".", 1)[-1]


def _names_in_line(line):
    return {_short(x) for x in re.findall(r"`(" + _LEAN_ID + r")`", line)}


def _root_of(doc, r, ns):
    """The walk's key for the result `r` named in a log line (keys are the index's names), or None."""
    keys = set(((doc or {}).get("assumes") or {})) | set((doc or {}).get("walked") or [])
    for k in sorted(keys):
        if k == r or (ns and (f"{ns}.{k}" == r or k == f"{ns}.{r}")):
            return k
    return None


def _mt_form_attempt(line):
    """Does the line try the canonical form: `missing theory:` right after its opening [DELEGATED] tag, or the
    human form's head `- missing theory (human <date>):`?"""
    import decisions
    p = decisions.LEAVE_PREFIX_RE.match(line)
    if p:
        t = decisions.DELEGATED_TAG_RE.match(line, p.end())
        return bool(t and re.match(r"\s*missing[- ]theory\s*:", line[t.end():], re.I))
    return bool(MT_HUMAN_RE.match(line))


# DESIGN-SW2 1.5 (C7, CH1's loose test, review R8's anchored backtick form): the body after a canonical-form head reads
# as a decision (assume / build / do not formalize / skip, or "`X` for `R`" opening it). Only such a line keeps the hard
# template FAIL (review C-F1: a sloppy real decision must not lose its searched/estimate obligations); any other body
# under the head ("none needed for `R`") is only suspected from its words: the DESIGN-MT route (MT RULED).
MT_DECISION_LIKE = re.compile(r"\s*(?:assum\w*|build\w*|do\s+not\s+formali[sz]e|skip\w*)\b|\s*`[^`]+`\s+for\s+`", re.I)


def _mt_head_end(line):
    """(end of the canonical-form head of `line`, whether it is the lower-case `missing theory:`), or (None, None)."""
    import decisions
    p = decisions.LEAVE_PREFIX_RE.match(line)
    if p:
        t = decisions.DELEGATED_TAG_RE.match(line, p.end())
        h = re.match(r"\s*missing[- ]theory\s*:", line[t.end():], re.I) if t else None
        return (t.end() + h.end(), "missing theory:" in h.group(0)) if h else (None, None)
    h = MT_HUMAN_RE.match(line)
    return (h.end(), True) if h else (None, None)


def _mt_decision_like(line):
    """Does the text after the canonical-form head (either case) read as a decision (MT_DECISION_LIKE)?"""
    e, _low = _mt_head_end(line)
    return e is not None and bool(MT_DECISION_LIKE.match(line, e))


def _mt_decision_problem(cfg, lines, i, r, doc, mt_names, ns):
    """Why the line lines[i], ruled a missing-theory decision for `N` (r), is not cured, or None. Cured by a
    canonical line logged after it naming N (U2 §7); with the walk (safety review F3): when N is a hypothesis the
    Lean assumes, only an `assume` line for N (it makes the F13 item); a `build` line for the result N only while
    no unclassified hypothesis of N is left in the Lean."""
    nm = _short(r[2])
    later = [m2 for _k2, m2, _l2, _b2 in lines[i + 1:]
             if m2 is not None and nm in {_short(m2.group("result")), _short(m2.group("hyp"))}]
    want = f"Log the canonical line for `{r[2]}` after it"
    if not later:
        return want
    if not doc:
        return None
    asm = assumed(doc)
    if any(same_name(r[2], n, ns) or same_name(n, r[2], ns) for n in asm):
        if not any(m2.group("assume") and nm == _short(m2.group("hyp")) for m2 in later):
            return (f"`{r[2]}` is a hypothesis the Lean assumes (the walk): only a canonical `assume` line for it cures "
                    f"this ({want})")
        return None
    root = _root_of(doc, r[2], ns)
    if root and any(m2.group("build") for m2 in later) and not any(m2.group("assume") for m2 in later):
        left = sorted(n for n, uses in asm.items() if any(u == root for u, _e in uses)
                      and classify(cfg, n, mt_names).startswith("unclassified"))
        if left:
            return (f"`build … for `{r[2]}`` while {', '.join(f'`{h}`' for h in left)} is still an unclassified "
                    f"hypothesis of it in the Lean (the walk): prove it and remove the binder, or log the `assume` "
                    f"line ({want})")
    return None


def missing_theory(cfg, log=None, doc=None, rd=None, round_name=None):
    """{"assume": {H: entry}, "build": {R: entry}, "skip": {R: entry}, "problems": [text], "goal": [text],
    "form": [(line id, line, line number)], "ruled": {line id: ruling}} from
    RUN_LOG.md (on disk, or `log`). An entry is {"result", "hyp" or "what", "searched", "estimate", "quote",
    "by", "line", "kind", "bound"}: the latest canonical line per hypothesis (per result for `build` and `do
    not formalize`; either supersedes an earlier `assume` line for the same result, and an `assume` or `build`
    line an earlier `do not formalize`). `form` (DESIGN-MT): a line the check suspects that is not in the
    canonical form, that no later canonical line naming its result or hypothesis cures, and that no adjudicator
    ruled (mt_ruling_history, `round_name` as there): the next adjudicator's to rule, never a problem. `problems`
    (FAIL[missing-theory] in the report check): such a line ruled a missing-theory decision for `N` with no
    canonical line for `N` after it; a delegated
    line under `involved` or a human one under `hands-off`; a human line with no committed human answer
    naming the result on its date (make_report.missing_theory_answers); `do not formalize` decided by the
    operator; and, of each latest line, a configured library not named as searched, a quote missing or too
    short, `H` not in `R`'s assumption list, `H` the walk flags as restating a result the project states or as
    a result's own conclusion, a `build` line while the hypothesis it replaces is still a binder of `R` (when
    the walk is there: without it Phase 0 is RED[dependencies] anyway). `goal` (FAIL[unproved-goal], stop 1):
    `H` that is a goal result's conclusion -- assuming it proves nothing (one that restates a goal result is a
    `problems` entry: use that result; DESIGN-SW2 1.8)."""
    log = _mt_log(cfg, log, rd)
    lvl = project.involvement(cfg)
    ns = cfg.get("namespace", "")
    lines = missing_theory_lines(log)
    out = {"assume": {}, "build": {}, "skip": {}, "problems": [], "goal": [], "form": [], "ruled": {}, "dissent": {}}
    same_r = lambda x, y: _short(x) == _short(y)
    hist, dissents, decided, nums = None, {}, [], {}
    for n_, l_ in enumerate(log.splitlines(), 1):
        nums.setdefault(l_.strip(), []).append(n_)
    for i, (kind, m, line, by) in enumerate(lines):
        n_ = nums[line].pop(0) if nums.get(line) else 0
        if m is None:
            names = _names_in_line(line)
            later = any(m2 is not None and (names & {_short(m2.group("result")), _short(m2.group("hyp"))} - {""})
                        for _k2, m2, _l2, _b2 in lines[i + 1:])
            if later:
                continue
            if names and _mt_form_attempt(line) and _mt_decision_like(line):
                # review C-F1: a line that tries the canonical form (`missing theory: …`), reads as a decision and names
                # its result keeps the template check hard; a corrected line naming it, logged after it, cures it
                low = _mt_head_end(line)[1]
                out["problems"].append(
                    f"RUN_LOG.md: a missing-theory decision not in the canonical form (U2 §7): {line[:110]!r}. Log a "
                    f"canonical line naming the same result after it (a logged decision is never reworded"
                    + ("" if low else "; the head is `missing theory:` in lower case") + f"): {MT_FORM}")
                continue
            # DESIGN-MT: only suspected from its words: the adjudicator rules whether it decides missing theory
            lid = mt_line_id(line)
            if hist is None:
                hist = mt_ruling_history(cfg, rd, round_name)
                dissents = _mt_dissents(cfg, log, rd or rounds_dir(cfg), hist) if hist else {}
            r = hist[lid][-1][:3] if hist.get(lid) else None
            if r is None:
                out["form"].append((lid, line, n_))
                continue
            out["ruled"][lid] = r
            if r[1] != "decision":
                continue
            if lid in dissents:
                # review C-F2: the operator dissents from the one "decision" ruling: the next adjudicator re-rules
                out["dissent"][lid] = (r[0], r[2], dissents[lid])
                out["form"].append((lid, line, n_))
                continue
            decided.append((i, lid, line, r))
            continue
        e = {"result": m.group("result"), "searched": m.group("searched"), "estimate": m.group("estimate"),
             "quote": (m.group("quote") or "").strip(), "by": by, "line": line, "kind": kind,
             "date": (by or "").rsplit(" ", 1)[-1] if kind == "human" else None}
        if m.group("assume"):
            e["hyp"] = m.group("hyp")
            out["assume"].pop(next((k for k in out["assume"] if _short(k) == _short(e["hyp"])), None), None)
            out["skip"].pop(next((k for k in out["skip"] if same_r(k, e["result"])), None), None)
            out["assume"][e["hyp"]] = e
        else:
            # a `build` or `do not formalize` line replaces the earlier `assume` lines for its result: their
            # hypotheses must be gone from the result's statement (review fix 3)
            e["replaces"] = [h for h, x in out["assume"].items() if same_r(x["result"], e["result"])]
            for h in e["replaces"]:
                out["assume"].pop(h)
            key = "build" if m.group("build") else "skip"
            if key == "build":
                e["what"] = m.group("what")
            for k2 in ("build", "skip"):
                out[k2].pop(next((k for k in out[k2] if same_r(k, e["result"])), None), None)
            out[key][e["result"]] = e
    if doc is None:
        doc, _ = walk(cfg, rd)
    for i, lid, line, r in decided:
        p_ = _mt_decision_problem(cfg, lines, i, r, doc, set(out["assume"]), ns)
        if p_:
            who = (" Under `involved` (and `statements-only` before the Checkpoint B answer) the human chooses: ask "
                   "the three-option question (stage2-statements.md step 6) and record `- missing theory (human "
                   "<date>): …`." if lvl != "hands-off" else "")
            dis = (" If you judge the ruling wrong, never log a false line: log `- MT DISSENT "
                   f"{lid}: <why>` after it; the line then waits for the next adjudicator's ruling (PENDING), which "
                   f"is final when it is again a decision." if sum(1 for x in (hist or {}).get(lid, []) if x[1] == "decision") == 1
                   else " A second decision ruling is final.")
            out["problems"].append(
                f"RUN_LOG.md: the adjudicator of round {r[0]} ruled this line a missing-theory decision for `{r[2]}` "
                f"(MT RULED {lid}): {line!r}. {p_} (a logged line is never reworded): {MT_FORM}.{who}{dis}")
    libs = project.libraries(cfg)
    answers = None
    for e in list(out["assume"].values()) + list(out["build"].values()) + list(out["skip"].values()):
        who = f"`{e.get('hyp') or e['result']}`"
        if e["kind"] == "delegated" and not project.delegates(cfg):
            out["problems"].append(f"RUN_LOG.md: missing theory for {who} is decided as [DELEGATED], but the level is "
                                   f"{lvl!r}: the human decides (stage2-statements.md step 6); record their choice as "
                                   f"`- missing theory (human <date>): …`")
        if e["kind"] == "human" and lvl == "hands-off":
            out["problems"].append(f"RUN_LOG.md: missing theory for {who} is recorded as the human's, but the level is "
                                   f"hands-off (nobody is asked): log it as a [DELEGATED] decision ({MT_FORM})")
        e["bound"] = e["kind"] != "human"
        if e["kind"] == "human" and lvl != "hands-off":
            # review fix 2: "decided by the human" is bound to the human's recorded, committed answer naming the
            # result on the line's date (sweep N1's rule for a missing-theory SKIPPED.md row)
            if answers is None:
                answers = _committed_answers_log(cfg, rd)
            e["bound"] = _human_bound(cfg, answers, e)
            if not e["bound"]:
                out["problems"].append(
                    f"RUN_LOG.md: missing theory for `{e['result']}` is recorded as the human's ({e['by']}), but the "
                    f"committed RUN_LOG.md holds no human answer naming `{e['result']}` dated {e['date']}: under "
                    f"`## Checkpoint B` (or `## Answered`) log the human's words verbatim as `- human answer "
                    f"({e['date']}; `{e['result']}`): \"<their words>\"` and commit it (an answer you write for them "
                    f"is no human decision); if nobody was asked, ask the three-option question first")
        norm = re.sub(r"\s+", "", e["searched"]).lower()
        miss = [l for l in libs if re.sub(r"\s+", "", l).lower() not in norm]
        if miss:
            out["problems"].append(f"RUN_LOG.md: missing theory for {who}: `searched:` does not name "
                                   f"{', '.join(miss)} (every configured library is searched before a result is "
                                   f"called missing theory): {e['line'][:90]!r}")
    for e in out["skip"].values():
        if e["kind"] == "delegated":
            out["problems"].append(
                f"RUN_LOG.md: `do not formalize `{e['result']}`` is option (3), the human's alone: under a delegating "
                f"level never take it yourself (RUN.md, \"Missing theory\"): build the theory or assume it as a named "
                f"hypothesis, and log that line after this one")
    goals = _goal_keys(cfg)
    for e in out["build"].values():
        left = _build_left(doc, e, ns)
        if left:
            out["problems"].append(
                f"RUN_LOG.md: `build … for `{e['result']}`` while {', '.join(f'`{h}`' for h in left)} is still a "
                f"hypothesis of `{e['result']}` in the Lean (the walk): a built theory leaves no hypothesis -- prove it "
                f"and remove the binder (commit, re-run Phase 0), or keep the `assume` line")
    for e in out["assume"].values():
        if len(re.sub(r"\s+", "", e["quote"])) < MT_QUOTE_MIN:
            out["problems"].append(f"RUN_LOG.md: missing theory `{e['hyp']}`: no quote of the paper's passage that invokes "
                                   f"the result without proof (`paper: \"<passage>\"`, at least {MT_QUOTE_MIN} "
                                   f"characters): {e['line'][:90]!r}")
        if doc:
            root = _root_of(doc, e["result"], ns)
            if root is None:
                out["problems"].append(f"RUN_LOG.md: missing theory `{e['hyp']}` is assumed for `{e['result']}`, which is "
                                       f"not a result the assumption walk reads (an index result, by its Lean name)")
            elif not any(same_name(e["hyp"], x.get("name", ""), ns) or same_name(x.get("name", ""), e["hyp"], ns)
                         for x in (doc.get("assumes") or {}).get(root, []) if isinstance(x, dict)):
                out["problems"].append(
                    f"RUN_LOG.md: missing theory `{e['hyp']}` is not in the assumption list of `{root}` (the walk, "
                    f"DEPENDENCIES.json): state it as a project Prop definition and take it as a binder `(h : "
                    f"{_short(e['hyp'])} …)` of `{root}`'s statement, commit and re-run Phase 0, or correct the line")
            # review fixes 1 and 4: a hypothesis the walk flags (in any result taking it) is no missing theory
            conc, rest = _mt_flags(doc, e["hyp"], ns)
            g_conc = sorted(r for r in conc if r in goals)
            # DESIGN-SW2 1.8 (C8): a hypothesis that only RESTATES a goal result is no stop 1 (the goal may well be
            # proved): it falls into the `rest` branch below, the operator's own curable FAIL ("use that result")
            if g_conc:
                what = f"the conclusion of the goal result {', '.join(f'`{g}`' for g in g_conc)}"
                out["goal"].append(
                    f"RUN_LOG.md: missing theory `{e['hyp']}` is {what} (the walk, DEPENDENCIES.json): assuming it "
                    f"proves nothing, so this is no missing theory. A goal result unprovable as stated is stop 1 (RUN.md, "
                    f"\"Stops\"): prove the goal, or stop for the human (`release`: `stops.py open --note \"<why>\" "
                    f"--cause unproved-goal`; `dev`: ask)")
            elif conc:
                out["problems"].append(
                    f"RUN_LOG.md: missing theory `{e['hyp']}` is the conclusion of {', '.join(f'`{r}`' for r in conc)} "
                    f"(the walk): assuming it proves nothing. Prove the result, or leave it unproved (`[DELEGATED …] "
                    f"leave <decl> unproved — <reason>`, the failure table, run/stops-and-set-asides.md); never assume a result's own conclusion")
            elif rest:
                out["problems"].append(
                    f"RUN_LOG.md: missing theory `{e['hyp']}` restates {', '.join(sorted({f'`{x}`' for _r, x in rest}))}, "
                    f"a result this project states (the walk, DEPENDENCIES.json): it is not missing theory. Prove it "
                    f"instead -- use that result (or the library's or the project's proof of it) in the proof and remove "
                    f"the binder, commit, re-run Phase 0 -- or correct the line")
    return out


def _mt_flags(doc, hyp, ns):
    """([results whose conclusion a binder of type `hyp` is], [(result, restated result)]): the walk's goal and
    restates flags of every binder through which a result takes the hypothesis `hyp`."""
    conc, rest = [], []
    for root, ents in sorted(((doc or {}).get("assumes") or {}).items()):
        for x in ents or []:
            if not (isinstance(x, dict) and (same_name(hyp, x.get("name", ""), ns) or same_name(x.get("name", ""), hyp, ns))):
                continue
            b = x.get("binder")
            if not b:
                continue
            if any(_same_binder(g, b) for g in ((doc.get("goal") or {}).get(root) or [])) and root not in conc:
                conc.append(root)
            rest += [(root, y.get("result")) for y in ((doc.get("restates") or {}).get(root) or [])
                     if isinstance(y, dict) and _same_binder(y.get("binder"), b) and (root, y.get("result")) not in rest]
    return conc, rest


def _goal_keys(cfg):
    """The goal results' Lean names (dependencies.goal_roots: the index cells of the intake's goal_results)."""
    try:
        import dependencies
        roots = set(dependencies.goal_roots(cfg))
    except Exception:          # noqa: BLE001 -- no index: no goal routing (the index check fails anyway)
        return set()
    ns = cfg.get("namespace", "")
    return roots | {f"{ns}.{g}" for g in roots if ns and not g.startswith(ns + ".")}


def _build_left(doc, e, ns):
    """The hypotheses a `build` line replaces (an earlier `assume` line for its result, or a name it gives in
    backticks) that its result still takes in the Lean (the walk)."""
    root = _root_of(doc, e["result"], ns) if doc else None
    if root is None:
        return []
    cand = set(e.get("replaces") or []) | set(re.findall(r"`(" + _LEAN_ID + r")`", e.get("what") or ""))
    names = [x.get("name", "") for x in ((doc.get("assumes") or {}).get(root) or []) if isinstance(x, dict)]
    return sorted({h for h in cand for n in names if same_name(h, n, ns) or same_name(n, h, ns)})


def _committed_answers_log(cfg, rd=None):
    """RUN_LOG.md as committed at HEAD (literal path, a regular file), or "" (outside git, or uncommitted)."""
    top, rel = project.rounds_rel(rd or rounds_dir(cfg), "RUN_LOG.md")
    return (project.committed_blob(top, "HEAD", rel) or "") if top else ""


def _human_bound(cfg, log, e):
    """Does the committed RUN_LOG.md text `log` record a human answer naming the result of the human missing-
    theory line `e` on its date (make_report.missing_theory_answers; the missing-theory lines themselves are
    the operator's record, not the answer)?"""
    import make_report
    try:
        import decisions
        labels = decisions.decl_results(cfg)
    except Exception:          # noqa: BLE001 -- the Lean names alone name it
        labels = {}
    ns = cfg.get("namespace", "")
    r = e["result"]
    full = r if (not ns or r.startswith(ns + ".")) else f"{ns}.{r}"
    names = {full.lower(), _short(r).lower()} | {str(l).lower() for l in (labels.get(full), labels.get(r)) if l}
    log = "\n".join(l for l in (log or "").splitlines() if not (MT_HUMAN_LOOSE_RE.match(l) or MT_HUMAN_RE.match(l)))
    return any(d == e["date"] for d, _l in make_report.missing_theory_answers(log, names)["human"])


def f13_items(cfg, rd=None):
    """{F13 item: hypothesis} for every missing-theory hypothesis of RUN_LOG.md (the latest canonical `assume` line
    per hypothesis, as written there): the paper-faithfulness lane's F13 items (scope.py schedules them)."""
    rd = rd or rounds_dir(cfg)
    names = missing_theory(cfg, log=_mt_log(cfg, None, rd), doc={}, rd=rd)["assume"]
    return {F13_ITEM.format(h): h for h in sorted(names)}


def mt_suspect_text(lid, line, n, dissent=None):
    """The adj-record finding of a suspected line (DESIGN-MT): the line in full, its id and anchor, both ruling forms;
    with `dissent` (round, name, why), the ruling the operator dissents from."""
    import decisions
    a = decisions.DELEGATED_PRE_RE.match(line)
    d = (f" The adjudicator of round {dissent[0]} ruled it a missing-theory decision for `{dissent[1]}`; the operator "
         f"dissents (MT DISSENT {lid}): {dissent[2]}. Rule it again: a second decision ruling is final."
         if dissent else "")
    return (f"RUN_LOG.md l.{n} (line id {lid}" + (f", anchor {a.group(1)}" if a else "") + f") {MT_SUSPECT_HEAD}.{d} "
            f"The check reads only its words; whether it is one "
            f"is the adjudicator's judgement: \"{line}\". Rule it once in ADOPTED.md's notes: `- MT RULED {lid} | not a "
            f"missing-theory decision: <why>` or `- MT RULED {lid} | a missing-theory decision for `<Lean name of the "
            f"result or hypothesis>`: <why>` (the operator then logs its canonical line). The id binds the exact text "
            f"(of a [DELEGATED] line: its anchor and the text from the tag on): a reworded line needs its own ruling.")


def missing_theory_findings(cfg, log=None, doc=None, rd=None, round_name=None):
    """[Finding missing-theory] of missing_theory (the report check; the operator's to clear), [Finding
    unproved-goal] of its goal problems (a goal result assumed away: stop 1, the human's), and [Finding adj-record]
    of its suspected lines no adjudicator ruled yet (DESIGN-MT: PENDING[adjudication], the next adjudicator's)."""
    mt = missing_theory(cfg, log, doc, rd, round_name)
    return ([project.Finding("! " + t, MT_CODE) for t in mt["problems"]]
            + [project.Finding("! " + t, "unproved-goal") for t in mt["goal"]]
            + [project.Finding("! " + mt_suspect_text(*x, dissent=mt["dissent"].get(x[0])), "adj-record")
               for x in mt["form"]])


def missing_theory_names(cfg, log=None):
    """The Lean names of missing-theory hypotheses: the canonical RUN_LOG.md lines (missing_theory)."""
    return set(missing_theory(cfg, log, doc={})["assume"])


def classify(cfg, name, mt_names=None):
    ns = cfg.get("namespace", "")
    if ":" in name:
        return "inline hypothesis (its type uses no project constant)"
    if any(same_name(h.get("lean", ""), name, ns) for h in cfg.get("literature_hypotheses") or []):
        return "literature hypothesis (declared at Checkpoint A)"
    if any(same_name(m, name, ns) for m in (missing_theory_names(cfg) if mt_names is None else mt_names)):
        return "missing-theory hypothesis"
    return "unclassified: a project predicate taken as a hypothesis"


def walk_problem(cfg, rd=None):
    """None when DEPENDENCIES.json is the assumption walk of the Lean files at HEAD, else why not (missing,
    malformed, or the walk of other Lean). SWEEP-FIX D1: scope.py --statements refuses on it, so statement_blockers
    is never evaluated on a stale walk at scope and then on a fresh one at approve (the cap deadlock, G1)."""
    import dependencies
    doc, why = walk(cfg, rd)
    if doc is None:
        return why
    if not doc.get("lean_sha256") or doc.get("lean_sha256") != dependencies.lean_hash(cfg, "HEAD"):
        return f"{dependencies.OUT} is not the walk of the Lean files at HEAD (it was written for other Lean)"
    return None


def statement_blockers(cfg, rd=None):
    """[(name, [result])] of the assumed names (the walk) that `classify` calls unclassified, computed only when
    DEPENDENCIES.json is the walk of the Lean files at HEAD ([] otherwise: Phase 0 reports a missing or stale walk).
    C2 audit: a project definition used in a hypothesis (`hx : x ∈ Good n`, Good a notation of the paper) with no
    index Definition row surfaced only at delivery, as "not established: unclassified assumption", and forced a
    re-approval after the human had approved the sheet. Each one is a mechanical blocker of the statement stage
    (scope.py --statements, signoff.py approve): the code flags it; which route is right is never the code's."""
    import dependencies
    doc, _why = walk(cfg, rd)
    if doc is None or not doc.get("lean_sha256") or doc.get("lean_sha256") != dependencies.lean_hash(cfg, "HEAD"):
        return []
    mt = missing_theory_names(cfg)
    return [(n, sorted({r for r, _e in uses})) for n, uses in sorted(assumed(doc).items())
            if classify(cfg, n, mt).startswith("unclassified")]


def statement_blocker_lines(blockers):
    """The FAIL[index] lines of statement_blockers, each with the routes (the choice is a judgement: the operator's,
    then the lanes' and the adjudicator's on the record it leads to)."""
    return [f"FAIL[index] `{n}` (in {', '.join(f'`{r}`' for r in rs)}) is a hypothesis no index Definition row "
            f"covers and no literature or missing-theory record classifies: after the approval those results would read "
            f"\"not established: unclassified assumption\", and the cure would change the approved sheet (a "
            f"re-approval). Before the sheet is approved, take the route that is right: a notion the paper defines or "
            f"introduces (a notation too) -> an index row `| Definition (<what>, tex l.<N>) | `{n}` |`, committed, "
            f"then phase0.py --statements and a statement round, whose lanes review the row; a missing-theory "
            f"hypothesis -> its canonical RUN_LOG.md line (stage2-statements.md step 6; under involved or "
            f"statements-only after the human's answer); a hypothesis the paper does not make -> change the statement"
            for n, rs in blockers]


def _round_dirs(rd):
    dirs = [os.path.dirname(f) for f in glob.glob(os.path.join(rd, "*", "ADOPTED.md"))]
    return project.order_rounds(dirs, project.REPO) if dirs else []


def table(text):
    """[(header, cells)] of every `## Hypotheses` table in an ADOPTED.md's text (a table whose first
    header cell is `hypothesis`)."""
    import decisions
    return [(h, c) for h, c in decisions.table_rows(text) if h and clean(h[0]).lower().startswith("hypothesis")]


def rows(cfg, rd=None):
    """[(round dir, row number, {column: cell}, shape problem or None)] oldest first."""
    rd = rd or rounds_dir(cfg)
    out = []
    for d in _round_dirs(rd):
        text = open(os.path.join(d, "ADOPTED.md"), encoding="utf-8").read()
        for i, (h, cells) in enumerate(table(text), 1):
            col = {}
            missing = [c for c in COLS if not any(clean(x).lower().startswith(c) for x in h)]
            for c in COLS:
                j = next((k for k, x in enumerate(h) if clean(x).lower().startswith(c)), None)
                col[c] = cells[j].strip() if j is not None and j < len(cells) else ""
            prob = None
            if missing:
                prob = f"its table has no {', '.join(missing)} column (the header is {TEMPLATE})"
            elif len(cells) != len(h):
                prob = f"{len(cells)} cells under a {len(h)}-column header (a literal `|` in a cell is written `\\|`)"
            out.append((d, i, col, prob))
    return out


def match_word(cell):
    c = clean(cell).lower()
    for w in ("source unavailable", "yes", "no"):
        if c == w or re.match(re.escape(w) + r"\b[\s(;:,.-]", c + " "):
            return w
    return None


def _mentions(text, name):
    short = name.rsplit(".", 1)[-1]
    return re.search(r"(?<![\w.'])(?:[\w.]*\.)?" + re.escape(short) + r"(?![\w'])", text) is not None


def _fp_key(name, ns, fps):
    """The FINGERPRINTS.json key of an assumed name: the constant itself; for an inline name
    `<result>:<binder>`, the result (its statement holds the binder)."""
    n = name.split(":", 1)[0]
    return n if n in fps or not ns else (f"{ns}.{n}" if f"{ns}.{n}" in fps else n)


def _fps(round_dir):
    try:
        d = json.load(open(os.path.join(round_dir, "FINGERPRINTS.json"), encoding="utf-8"))
        return d.get("fingerprints") if isinstance(d, dict) and isinstance(d.get("fingerprints"), dict) else None
    except (OSError, ValueError):
        return None


def latest_fps(rd):
    """{declaration: fingerprint} of the newest round (project.order_rounds) with a FINGERPRINTS.json,
    or None."""
    dirs = [os.path.dirname(f) for f in glob.glob(os.path.join(rd, "*", "FINGERPRINTS.json"))]
    for d in reversed(project.order_rounds(dirs, project.REPO) if dirs else []):
        f = _fps(d)
        if f is not None:
            return f
    return None


# B5 (approver's rule 2026-10-24, a benchmark run): the walk's restates flag (a binder whose type is an instance of
# another result's conclusion) is a QUESTION for the paper-faithfulness lane, never a verdict: is the binder the
# paper's own hypothesis of the result as printed ("if G is planar, then ..."), or an assumption the paper does not
# make (something it proves)? scope.py schedules this item for every such binder (TARGET.json `_meta.f13`, beside
# the F13 items); a `yes` or `source unavailable` row needs a Pass on it, a Fail on it is a Fail like any other. Python
# checks only that the item exists, names the binder, is answered (Pass) and current (the fingerprint check). One
# hard rule stays: a binder that IS the result's own conclusion is circular, `no` only (no judgement).
FLAG_ITEM = "F15: the flagged hypothesis {}"


def flag_question(doc, uses):
    """The question asked under the FLAG_ITEM of an assumed name (its `uses` from `assumed`), or None when the
    walk flags none of its binders only as restating (unflagged, or IS THE CONCLUSION somewhere)."""
    fl = [(r, e.get("binder"), flags(doc, r, e.get("binder"))) for r, e in uses]
    if not any(fs for _r, _b, fs in fl) or any(f.startswith("IS THE CONCLUSION") for _r, _b, fs in fl for f in fs):
        return None
    return "; ".join(f"hypothesis `{b}` of `{r}` looks like the conclusion of "
                     f"{', '.join(f[len('restates '):] for f in fs)}" for r, b, fs in fl if fs)


def flag_items(cfg, rd=None):
    """{FLAG_ITEM: hypothesis} for every assumed name the walk flags only as restating another result, a
    missing-theory hypothesis aside (its F13 path; one that restates a result is no missing theory)."""
    rd = rd or rounds_dir(cfg)
    doc, _ = walk(cfg, rd)
    if doc is None:
        return {}
    ns = cfg.get("namespace", "")
    mtn = set(missing_theory(cfg, log=_mt_log(cfg, None, rd), doc={}, rd=rd)["assume"])
    return {FLAG_ITEM.format(n): n for n, uses in sorted(assumed(doc).items())
            if flag_question(doc, uses) and not any(same_name(m, n, ns) for m in mtn)}


# next batch B17 (NW-1, stop S1 commit-refused): a plain literature hypothesis of the walk had no item, so no sealed
# paper-faithfulness verdict named it, `cite_problem` found no verdict to cite and the adjudication commit was refused
# with no valid row possible. Every assumed name without a valid latest `## Hypotheses` row gets this item (scheduling,
# not a new check); the item text contains the name, so `cite_problem`'s `_mentions` sees a verdict on it.
HYP_ITEM = "F15: the hypothesis {}"


def hyp_items(cfg, rd=None, skip=()):
    """{HYP_ITEM: hypothesis} for every assumed name with no valid latest `## Hypotheses` row (`latest`), the names
    in `skip` (those with an F13 or FLAG_ITEM item of their own) aside."""
    rd = rd or rounds_dir(cfg)
    doc, _ = walk(cfg, rd)
    if doc is None:
        return {}
    lat = latest(cfg, rd)
    return {HYP_ITEM.format(n): n for n in sorted(assumed(doc)) if n not in skip and (n not in lat or lat[n][3])}


def scheduled_items(cfg, rd=None):
    """The paper-faithfulness items scope.py schedules in every round for hypotheses: F13, FLAG_ITEM and HYP_ITEM."""
    own = {**f13_items(cfg, rd), **flag_items(cfg, rd)}
    return {**own, **hyp_items(cfg, rd, set(own.values()))}


def cite_problem(rd, row_round, col, name, flagged=(), ns="", now_fps=None, mt=False):
    """None if the row cites the paper-faithfulness verdict behind its `matches source` value (F15,
    and F14 for `source unavailable`), else why not. `flagged`: the walk's flags of the name (`flags`): one that
    IS a conclusion (circular) or a flagged missing-theory hypothesis may only be `no`; one flagged only as
    restating is the lane's question on its FLAG_ITEM.
    Review fix 2: `yes` too needs the cited verdict to CONFIRM it (a Pass naming H, no Fail or
    Ambiguous naming it); and a verdict given before H's content changed (H's fingerprint in the cited
    verdict's round differs from `now_fps`, the newest round's) supports nothing. `mt`: a missing-theory
    hypothesis, whose `yes` or `source unavailable` needs a Pass on its F13 item (F13_ITEM). B5: a hypothesis the
    walk flags only as restating (not the conclusion, not missing theory) needs a Pass on its FLAG_ITEM instead."""
    import lanecheck
    w = match_word(col["matches source"])
    if w is None:
        return f"`matches source` is {col['matches source']!r}: write yes, no or source unavailable"
    if flagged and w != "no" and (mt or any(f.startswith("IS THE CONCLUSION") for f in flagged)):
        return (f"`matches source` is {w!r}, but the walk finds it {'; '.join(flagged)}: "
                + ("assuming a result's own conclusion is circular" if not mt else
                   "a missing-theory hypothesis that restates a result is no missing theory (F13)")
                + " (write `no`; the paper-faithfulness lane Fails it)")
    for c in ("stands for", "consistency evidence", "trivialization", "plain english"):
        if clean(col[c]) in ("", "-", "?"):
            return f"its `{c}` cell is empty"
    cites = CITE_RE.findall(col["supporting verdict"])
    if not cites:
        return ("its `supporting verdict` cell cites no lane verdict: name the paper-faithfulness verdict file "
                "behind `matches source` (F15), e.g. `paper-faithfulness.json`")
    why = []
    for c in cites:
        first = c.split("/", 1)[0]
        cross = "/" in c and os.path.isdir(os.path.join(rd, first)) and first != "revote"
        p = os.path.join(rd, c) if cross else os.path.join(row_round, c)
        v_round = os.path.join(rd, first) if cross else row_round
        base = lanecheck.lane_base(os.path.basename(c)[:-len(".json")])
        if base not in FAITH_LANES:
            why.append(f"`{c}` is not a paper-faithfulness verdict")
            continue
        try:
            doc = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            why.append(f"`{c}` is not a readable lane verdict of {os.path.basename(row_round)}")
            continue
        ents = lanecheck.lane_entries(doc)
        if ents is None:
            why.append(f"`{c}` is not a lane verdict document (no `verdicts` list)")
            continue
        named = [e for e in ents if _mentions(json.dumps(e, ensure_ascii=False), name)]
        if not named:
            why.append(f"`{c}` does not name `{name.rsplit('.', 1)[-1]}`: it is not the verdict behind this row")
            continue
        # DESIGN-SW2 1.12 (C32): only a non-Pass on H's OWN item (the entry's `item` names H, a template field) blocks
        # `yes` / `source unavailable`; a Fail on another item that merely mentions H ("unlike `hP`") is the
        # adjudicator's to weigh when it writes the row (AUDIT_PROTOCOL step H), never a forced `no`
        own = [e for e in named if _mentions(str(e.get("item", "")), name)]
        if w == "source unavailable":
            # F14: valid only once paper-faithfulness CONFIRMED that H matches the paper's quoted invocation
            if any(e.get("verdict") != "Pass" for e in own) or not any(e.get("verdict") == "Pass" for e in named):
                why.append(f"`{c}` does not confirm it (F14: `source unavailable` needs a Pass naming the hypothesis "
                           f"-- H matches the paper's quoted invocation -- and no Fail or Ambiguous on its own item)")
                continue
        if w == "yes":
            # review fix 2: `yes` is the paper-faithfulness lane's finding, so the cited verdict must confirm it
            if any(e.get("verdict") != "Pass" for e in own) or not any(e.get("verdict") == "Pass" for e in named):
                why.append(f"`{c}` does not confirm it (`matches source: yes` needs a Pass naming the hypothesis and "
                           f"no Fail or Ambiguous on its own item; its verdicts on that item: "
                           f"{', '.join(sorted({str(e.get('verdict')) for e in own})) or 'none'})")
                continue
        if mt and w in ("yes", "source unavailable"):
            # the F13 item check (prompt.LANE_ITEM_PATHS): the lane judged H as missing theory, on its scheduled item
            want = {F13_ITEM.format(x) for x in (name, _short(name), name[len(ns) + 1:] if ns and name.startswith(ns + ".")
                                                  else name)}
            if not any(e.get("verdict") == "Pass" and " ".join(str(e.get("item", "")).split()) in want for e in named):
                why.append(f"`{c}` has no Pass on the item \"{F13_ITEM.format(name)}\" (F13: a missing-theory "
                           f"hypothesis is judged on its own item, which scope.py puts in every round's "
                           f"paper-faithfulness scope; the next round's lane judges it)")
                continue
        if flagged and not mt and w in ("yes", "source unavailable"):
            # B5: the walk's restates flag is a question the lane answers on the binder's own item:
            # the FLAG_ITEM check (prompt.LANE_ITEM_PATHS)
            want_f = {FLAG_ITEM.format(x) for x in (name, _short(name), name[len(ns) + 1:] if ns and name.startswith(ns + ".")
                                                   else name)}
            if not any(e.get("verdict") == "Pass" and " ".join(str(e.get("item", "")).split()) in want_f for e in named):
                why.append(f"`{c}` has no Pass on the item \"{FLAG_ITEM.format(name)}\" (the walk finds it "
                           f"{'; '.join(flagged)}: whether it is the paper's own hypothesis as printed is the "
                           f"paper-faithfulness lane's question on that item, which scope.py puts in every round's "
                           f"scope; the next round's lane answers it)")
                continue
        then = _fps(v_round)
        if then is not None and now_fps is not None:
            k = _fp_key(name, ns, now_fps)
            if k in then and k in now_fps and then[k] != now_fps[k]:
                why.append(f"`{c}` was given before `{k}` changed (its fingerprint in round {os.path.basename(v_round)} "
                           f"differs from the newest round's): a verdict on the old content supports nothing; the "
                           f"next paper-faithfulness lane judges it again")
                continue
        return None
    return "; ".join(why)


def latest(cfg, rd=None):
    """{assumed name: (round dir, row number, columns, problem or None)} -- the latest row naming it."""
    rd = rd or rounds_dir(cfg)
    doc, _ = walk(cfg, rd)
    ns = cfg.get("namespace", "")
    asm = assumed(doc)
    now = latest_fps(rd)
    mtn = set(missing_theory(cfg, doc={}, rd=rd)["assume"])
    out = {}
    for d, i, col, prob in rows(cfg, rd):
        for n, uses in sorted(asm.items()):
            if same_name(col["hypothesis"], n, ns):
                is_mt = any(same_name(m, n, ns) for m in mtn)
                out[n] = (d, i, col, prob or cite_problem(rd, d, col, n, rule_flags(doc, uses, n, mtn, ns), ns, now,
                                                          mt=is_mt))
    return out


def rule_flags(doc, uses, name, mt_names=(), ns=""):
    """The walk's flags that allow only `matches source: no` -- for a missing-theory hypothesis too (B6 review
    fix 1: one the walk flags as restating a result is no missing theory, FAIL[missing-theory], and page 1
    never calls it checked)."""
    return name_flags(doc, uses)


def findings(cfg, rd=None):
    """[Finding adj-record]: every assumed name without a valid latest row (PENDING in Phase 0 and
    make_report --pending; blocking --commit-adjudication, --check and --deliver)."""
    rd = rd or rounds_dir(cfg)
    doc, why = walk(cfg, rd)
    if doc is None:
        return []          # dependencies.problems says so (RED[dependencies] in Phase 0)
    lat = latest(cfg, rd)
    out = []
    for n, uses in sorted(assumed(doc).items()):
        where = "; ".join(sorted({f"{r}: ({e.get('binder') or 'body'} : {e.get('type_pp', '?')})" for r, e in uses}))[:300]
        if n not in lat:
            out.append(project.Finding(
                f"! hypothesis `{n}` ({where}) has no row in a `## Hypotheses` table of an ADOPTED.md: the next "
                f"adjudicator writes it ({TEMPLATE})", "adj-record"))
        elif lat[n][3]:
            d, i, _col, prob = lat[n]
            out.append(project.Finding(
                f"! hypothesis `{n}`: its latest row (round {os.path.basename(d)}, row {i}) {prob}; the next "
                f"adjudicator writes a new row (an ADOPTED.md is never edited after its commit)", "adj-record"))
    return out


def new_binders(cfg, doc=None, rd=None):
    """{result: [(binder, type)]} of the Prop binders added since the FIRST genuine approval, or None
    when that cannot be computed (no approval, or an approval that recorded no binders). Step 6 of the
    walk: a re-approved statement's new binder is listed even when it uses only Mathlib or Definition
    rows. The binders at the approval are the ones `signoff.py approve` recorded in it (review fix 4:
    DEPENDENCIES.json is not committed at approval in real runs), else the DEPENDENCIES.json committed in
    the approval's commit."""
    rd = rd or rounds_dir(cfg)
    if doc is None:
        doc, _ = walk(cfg, rd)
    if not doc:
        return None
    try:
        import fingerprint, dependencies
        g = fingerprint.genuine_approvals(rd, cfg)
        if not g:
            return None
        rec = g[0][1] if isinstance(g[0][1], dict) else {}
        if isinstance(rec.get("binders"), dict):
            return added_binders(rec["binders"], doc.get("binders") or {})
        top, rel = project.rounds_rel(rd, dependencies.OUT)
        if top is None:
            return None
        import subprocess
        r = subprocess.run(["git", "-C", top, "show", f"{g[0][0]}:{rel}"], capture_output=True, text=True)
        then = json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:       # noqa: BLE001 -- not computed, said so in the report
        return None
    if not isinstance(then, dict) or not isinstance(then.get("binders"), dict):
        return None
    return added_binders(then["binders"], doc.get("binders") or {})


def added_binders(then, now):
    """{result: [(binder, type)]}: binders of `now` (by type) beyond those `then` had, per result
    present in both."""
    import collections
    out = {}
    for root, bs in sorted(now.items()):
        if root not in then:
            continue
        old = collections.Counter(b.get("type_pp") for b in then[root] or [])
        for b in bs or []:
            if old[b.get("type_pp")]:
                old[b.get("type_pp")] -= 1
            else:
                out.setdefault(root, []).append((b.get("binder", ""), b.get("type_pp", "")))
    return out


def report(cfg, rd=None):
    """{"rows": [[assumed, kind, stands for / matches source, plain English, Lean]], "notes": [text],
    "why": reason when the walk is missing, "counts": {...}} for the report's section 2."""
    rd = rd or rounds_dir(cfg)
    doc, why = walk(cfg, rd)
    ns = cfg.get("namespace", "")
    rows_, notes = [], []
    counts = {"assumed": 0, "matching": 0, "unavailable": 0, "mismatch": 0, "pending": 0, "unclassified": 0,
              "flagged": 0}
    lits = cfg.get("literature_hypotheses") or []
    asm = assumed(doc) if doc else {}
    lat = latest(cfg, rd) if doc else {}
    mt = missing_theory(cfg, doc=doc or {}, rd=rd)
    missing = []
    for ax in sorted({a for v in ((doc or {}).get("axioms") or {}).values() for a in v}):
        users = sorted(r for r, v in doc["axioms"].items() if ax in v)
        rows_.append([f"`{ax}`", "axiom", "-", "-", ", ".join(f"`{u}`" for u in users)])
    for h in lits:
        if not any(same_name(h.get("lean", ""), n, ns) for n in asm):
            rows_.append([f"`{h.get('lean', '?')}`", "literature hypothesis (declared at Checkpoint A)",
                          str(h.get("paper", "?")), "-", "*not used by any result's statement*"])
    for n, uses in sorted(asm.items()):
        counts["assumed"] += 1
        kind = classify(cfg, n, set(mt["assume"]))
        counts["unclassified"] += kind.startswith("unclassified")
        mte = next((e for h, e in mt["assume"].items() if same_name(h, n, ns)), None)
        if mte:
            # B6 (F13): what the operator's line says the hypothesis stands for, for the lanes to judge (a
            # note under the table: a long quote in a narrow table cell does not typeset reliably)
            import make_report
            notes.append(f"Missing theory: `{n}` is assumed for `{mte['result']}`; the paper invokes it: "
                         f"\u201c{make_report.codeify_latex(mte['quote']) or 'NO QUOTE'}\u201d (searched: "
                         f"{make_report.codeify_latex(mte['searched'])}).")
        flags = name_flags(doc, uses)
        counts["flagged"] += bool(flags)
        if n in lat and not lat[n][3]:
            col = lat[n][2]
            w = match_word(col["matches source"])
            counts["unavailable"] += w == "source unavailable"
            counts["mismatch"] += w == "no"
            counts["matching"] += w == "yes"
            src = f"{clean(col['stands for'])}; matches source: {clean(col['matches source'])}"
            plain = clean(col["plain english"])
            state, triv = w, clean(col["trivialization"])
        else:
            counts["pending"] += 1
            src, plain = "PENDING: no valid hypothesis row yet (the next adjudication writes it)", "-"
            state, triv = None, ""
        if mte:
            # review fix 6: every result whose statement takes H (a goal using the lemma H is assumed for takes
            # it too), for page 1
            missing.append(dict(mte, name=n, state=state, trivialization=triv, flags=flags,
                                users=sorted({r for r, _e in uses})))
        lean = "; ".join(sorted({f"`{r}`: " + (f"({e['binder']} : {e.get('type_pp', '?')})" if e.get("binder")
                                                 else f"in the statement: {e.get('type_pp', '?')}")
                                 for r, e in uses}))
        rows_.append([f"`{n}`", kind + ("; " + "; ".join(flags) if flags else ""), src, plain, lean])
    if doc:
        nb = new_binders(cfg, doc, rd)
        if nb is None:
            notes.append("Hypotheses added since the approval: not computed (no approval yet, or the approval "
                         "recorded no binders: made before approvals recorded them, or without a current walk).")
        elif nb:
            notes.append("Hypotheses added since the approval: " + "; ".join(
                f"`{r}`: " + ", ".join(f"({b} : {t})" for b, t in bs) for r, bs in sorted(nb.items())) + ".")
        else:
            notes.append("Hypotheses added since the approval: none.")
        inst = doc.get("instances") or []
        if inst:
            notes.append("Project instances the results use that the index does not list (the correspondence "
                         "reviewer checks each against the paper): " + ", ".join(f"`{i}`" for i in inst) + ".")
        bare = doc.get("bare") or {}
        if bare:
            notes.append("For information, every project Prop definition taken bare as a hypothesis anywhere in "
                         "the Lean: " + "; ".join(f"`{h}` by " + ", ".join(f"`{u}`" for u in us)
                                                  for h, us in sorted(bare.items())) + ".")
    for h, e in sorted(mt["assume"].items()):
        if not any(m_["result"] == e["result"] and same_name(h, m_["name"], ns) for m_ in missing):
            # the line names a hypothesis the walk does not list for it (FAIL[missing-theory]): still on page 1
            missing.append(dict(e, name=h, state="unlisted" if doc else "no walk", trivialization="", flags=[]))
    built = [dict(e, left=_build_left(doc, e, ns)) for e in sorted(mt["build"].values(), key=lambda e: e["result"])]
    return {"rows": rows_, "notes": notes, "why": why or "", "counts": counts, "missing": missing,
            "built": built, "skipped": sorted(mt["skip"].values(), key=lambda e: e["result"]), "suspects": mt["form"],
            "dissented": mt["dissent"]}


def trust_rows(cfg, rd=None, r=None):
    """Page 1: the hypothesis count, with the rows whose source was not checked or does not match (`r`: a
    report() already computed, as the summary passes it)."""
    r = r if r is not None else report(cfg, rd)
    c = r["counts"]
    mt = missing_theory_rows(cfg, r)
    if r["why"]:
        return [("What the formalization assumes", "every hypothesis the results' statements take, read off the "
                 "Lean (section 2)", "NOT COMPUTED: " + r["why"])] + mt
    return mt + [("What the formalization assumes",
             "every hypothesis the results' statements take, read off the Lean (section 2)",
             f"{c['assumed']} hypothesis name(s) beyond the paper's definitions; {c['matching']} matching their "
             f"source (confirmed by a paper-faithfulness verdict); {c['unavailable']} with the source "
             f"unavailable (only the paper's quoted invocation was checked); {c['mismatch']} not matching their "
             f"source; {c['unclassified']} unclassified; {c['pending']} pending a record"
             + (f"; {c['flagged']} flagged by the walk as the conclusion itself or a restated result (section 2)"
                if c["flagged"] else ""))]


MT_STATE = {
    "yes": "checked: a paper-faithfulness verdict confirms it says no more than the paper's invocation",
    "source unavailable": ("source not checked: the cited work was not available; a paper-faithfulness verdict "
                           "confirms it says no more than the paper's quoted invocation"),
    "no": "it does NOT match the paper's invocation (section 2)",
    None: "PENDING: not yet checked against the paper (no valid hypothesis record)",
    "unlisted": "NOT a hypothesis of that result in the Lean: the log line and the statement disagree (report check)",
    "no walk": "NOT COMPUTED: no assumption walk, so not compared with the Lean",
}


def missing_theory_rows(cfg, r):
    """Page 1 (U2 §7): one row per result proved assuming a missing-theory hypothesis -- "<result> proved
    assuming <H>", naming every other result (a goal first) whose statement takes H -- per result whose missing
    theory was built here, and per result the human chose not to formalize; who decided, and how far the
    hypothesis was checked against the paper's invocation (F13)."""
    try:
        import decisions
        labels = decisions.decl_results(cfg)
    except Exception:          # noqa: BLE001 -- the Lean name stands in for the paper's label
        labels = {}
    ns = cfg.get("namespace", "")
    lab = lambda d: labels.get(d) or labels.get(f"{ns}.{d}") or f"`{d}`"

    def who(e):
        if e["kind"] == "delegated":
            return "decided by the operator (" + (e.get("by") or "[DELEGATED]") + "), not by a person"
        if e.get("bound"):
            return f"decided by the human ({e.get('by')})"
        return f"recorded as the human's ({e.get('by')}) but with NO recorded human answer (report check)"
    import make_report
    goals = _goal_keys(cfg)
    out = []
    for e in r.get("missing", []):
        import make_report      # LaTeX in a quote is set as code (it never prints raw on page 1)
        q = make_report.codeify_latex(e["quote"] if len(e["quote"]) <= 160 else e["quote"][:157] + "...")
        st = MT_STATE.get(e["state"], MT_STATE[None])
        if re.search(r"main step", e.get("trivialization", ""), re.I):
            st += "; the hypothesis is (nearly) the main step of the proof"
        if e.get("flags"):
            st += "; flagged by the walk: " + "; ".join(e["flags"])
        others = [u for u in e.get("users") or [] if not (same_name(u, e["result"], ns) or same_name(e["result"], u, ns)
                                                         or u == e["result"])]
        g_o = [u for u in others if u in goals]
        also = ""
        if g_o:
            also += (f"; so the goal result{'s' if len(g_o) > 1 else ''} {', '.join(lab(u) for u in g_o)} "
                     f"{'are' if len(g_o) > 1 else 'is'} proved assuming it too")
        if len(others) > len(g_o):
            also += "; also assumed by " + ", ".join(lab(u) for u in others if u not in g_o)
        out.append(("Missing theory",
                    f"{lab(e['result'])} proved assuming `{_short(e['name'])}`, a result the paper invokes without "
                    f"proof (\u201c{q or 'NO QUOTE'}\u201d) and no configured library has{also}; {who(e)}", st))
    for e in r.get("built", []):
        st = ("proved here and reviewed like every other proof" if not e.get("left") else
              "NOT built: " + ", ".join(f"`{_short(h)}`" for h in e["left"]) + " is still a hypothesis of that "
              "result in the Lean (report check)")
        out.append(("Missing theory", f"{lab(e['result'])}: the missing theory ({make_report.codeify_latex(e['what'])}) "
                    f"was built in this project; {who(e)}", st))
    import decisions
    place = lambda l_, n_: (lambda a: a.group(1) if a else f"RUN_LOG.md l.{n_}")(decisions.DELEGATED_PRE_RE.match(l_))
    dis = r.get("dissented") or {}
    never = [x for x in r.get("suspects") or [] if x[0] not in dis]
    if never:
        # DESIGN-MT fix round (safety review F2): said to the author in plain words, the lines by their anchor
        where = list(dict.fromkeys(place(l_, n_) for _i, l_, n_ in never))
        out.append(("Missing theory", f"run-log decision lines that mention missing theory ({', '.join(where)}): "
                    f"whether they decide a library gap is not yet judged by an independent agent",
                    "PENDING: not judged by an independent agent (the next full review round rules it)"))
    for i_, (rr, nm, _why) in sorted(dis.items()):
        # review N2: an independent ruling the operator disputed is never called "not judged"
        where = list(dict.fromkeys(place(l_, n_) for j_, l_, n_ in r.get("suspects") or [] if j_ == i_))
        out.append(("Missing theory", f"a run-log decision line ({', '.join(where)}) was ruled a missing-theory decision "
                    f"for `{_short(nm)}` by an independent reviewer (round {rr}); disputed by the operator; not re-ruled",
                    "DISPUTED: not acted on (no canonical line, no paper-faithfulness item) until a second review round re-rules it"))
    for e in r.get("skipped", []):
        out.append(("Missing theory", f"{lab(e['result'])}: not formalized, for theory no configured library has; "
                    f"{who(e)}", "not formalized (section 4)" if e["kind"] == "human" else
                    "REFUSED: option (3) is the human's alone (report check)"))
    return out


def summary_text(cfg, rd=None):
    """The ASSUMPTIONS block of a lane prompt: each hypothesis the walk lists, its Lean type and the
    adjudicator's plain-English cell side by side (the correspondence lane checks one against the
    other), its class and flags. Read off DEPENDENCIES.json; no record file is named."""
    r = report(cfg, rd)
    if r["why"]:
        return f"  (not computed: {r['why']})"
    if not r["rows"]:
        return "  (none: no result's statement takes a hypothesis beyond the paper's definitions and Mathlib)"
    out = []
    for name, kind, src, plain, lean in r["rows"]:
        out.append(f"  - {name} [{kind}]\n      Lean: {lean}\n      stands for: {src}\n      plain English: {plain}")
    return "\n".join(out + [f"  {n}" for n in r["notes"]])


def selftest():
    import collections, shutil, tempfile
    res = []

    def say(n, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    tmp = tempfile.mkdtemp()
    saved, saved_st = project.REPO, project._scope_time
    try:
        project.REPO = tmp
        # the two rounds are uncommitted, so project.order_rounds would order them by their directories' mtimes,
        # which every file created in them moves: under load a clock step (WSL) could put the older round last
        # (T28, polish 2026-10-24). Their order here is by name; ordering itself is project.py's selftest's.
        project._scope_time = lambda d_: {"2026-01-01-aaaaaaa": 1, "2026-01-02-bbbbbbb": 2}.get(
            os.path.basename(d_), None) or saved_st(d_)
        rd = os.path.join(tmp, "R")
        os.makedirs(os.path.join(rd, "2026-01-01-aaaaaaa"))
        os.makedirs(os.path.join(rd, "2026-01-02-bbbbbbb"))
        cfg = {"rounds_dir": "R", "namespace": "N", "literature_hypotheses": [{"lean": "N.Lit", "paper": "[3]"}]}
        dep = {"lean_sha256": "h", "commit": "c", "walked": ["thm"],
               "binders": {"thm": [{"binder": "hI", "type_pp": "∀ n, n + 0 = n"}]}, "goal": {"thm": ["hX"]},
               "restates": {"thm": [{"binder": "hI", "result": "lem"}]}, "axioms": {"thm": ["N.ax"]}, "instances": ["N.instX"], "bare": {"N.H": ["N.thm"]},
               "assumes": {"thm": [{"name": "N.H", "binder": "h", "kind": "prop", "type_pp": "N.H n", "embedded": False},
                                   {"name": "N.G", "binder": "hG", "kind": "prop", "type_pp": "N.G n", "embedded": False},
                                   {"name": "N.X", "binder": "hX", "kind": "prop", "type_pp": "N.X n", "embedded": False},
                                   {"name": "N.Lit", "binder": "hl", "kind": "prop", "type_pp": "N.Lit", "embedded": False},
                                   {"name": "N.E", "binder": "", "kind": "embedded", "type_pp": "P ∧ (N.E → Q)",
                                    "embedded": True}]}}
        json.dump(dep, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        r1, r2 = os.path.join(rd, "2026-01-01-aaaaaaa"), os.path.join(rd, "2026-01-02-bbbbbbb")
        pf = lambda ents: json.dump({"lane": "paper-faithfulness", "verdicts": ents}, open(os.path.join(r1, "paper-faithfulness.json"), "w"))
        pf([{"item": "Theorem 1", "verdict": "Pass", "checked": "H matches the paper's (H); Lit is [3, Thm 2]; E ok"},
            {"item": "Theorem 2", "verdict": "Fail", "checked": "G is the conclusion itself"}])
        json.dump({"lane": "correspondence", "verdicts": [{"item": "Theorem 1", "verdict": "Pass", "checked": "H"}]},
                  open(os.path.join(r1, "correspondence.json"), "w"))
        head = TEMPLATE + "\n|---|---|---|---|---|---|---|\n"
        row = lambda n, m, cite, plain="n is not 7": f"| `{n}` | the paper's (H) | {m} | witness n=0 | not trivial | {plain} | {cite} |\n"
        open(os.path.join(r1, "ADOPTED.md"), "w").write("| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n\n## Hypotheses\n\n" + head
                                                          + row("H", "yes", "paper-faithfulness.json"))
        f1 = findings(cfg)
        say("an assumed name with no row is PENDING[adj-record] (never RED); a row keyed relative to the namespace counts",
            all(f.code == "adj-record" for f in f1) and {re.search(r"`([^`]+)`", f).group(1) for f in f1} == {"N.G", "N.X", "N.Lit", "N.E", "thm:hI"})
        # C2 audit: the statement stage's blockers -- every assumed name classify calls unclassified (not the declared
        # literature hypothesis, not the inline binder), only on the walk of HEAD's Lean; a row or a classification
        # (here: N.H declared as literature) removes it
        import dependencies as _dep
        _keep_lh = _dep.lean_hash
        try:
            _dep.lean_hash = lambda c_, h_: "h"
            sb = statement_blockers(cfg)
            sb_lit = statement_blockers(dict(cfg, literature_hypotheses=cfg["literature_hypotheses"] + [{"lean": "N.H"}]))
            _dep.lean_hash = lambda c_, h_: "another"
            sb_stale = statement_blockers(cfg)
        finally:
            _dep.lean_hash = _keep_lh
        ln_ = statement_blocker_lines(sb)
        say("C2 audit: a hypothesis the walk lists that nothing classifies blocks the statement stage (FAIL[index], with "
            "the index-row route first); a literature or inline one does not; a stale walk blocks nothing",
            [n for n, _ in sb] == ["N.E", "N.G", "N.H", "N.X"] and all(rs == ["thm"] for _, rs in sb)
            and [n for n, _ in sb_lit] == ["N.E", "N.G", "N.X"] and sb_stale == [] and len(ln_) == 4
            and all(l_.startswith("FAIL[index] `N.") and "| Definition (<what>, tex l.<N>) |" in l_ for l_ in ln_))
        open(os.path.join(r2, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head + row("N.H", "yes", "correspondence.json"))
        f2 = findings(cfg)
        say("F15: the latest row wins only if it cites the paper-faithfulness verdict behind `matches source` "
            "(citing correspondence is a fault until a newer row; the older valid row is no excuse)",
            any("N.H" in f and "not a paper-faithfulness verdict" in f for f in f2))
        open(os.path.join(r2, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head + row("N.H", "yes", "2026-01-01-aaaaaaa/paper-faithfulness.json")
                                                          + row("N.G", "source unavailable", "2026-01-01-aaaaaaa/paper-faithfulness.json")
                                                          + row("N.Lit", "yes", "none")
                                                          + row("N.E", "yes", "2026-01-01-aaaaaaa/paper-faithfulness.json", plain=""))
        f3 = collections.defaultdict(str, {re.search(r"`([^`]+)`", f).group(1): f for f in findings(cfg)})
        say("a verdict of an earlier round, named by its round, supports a row", "N.H" not in f3)
        say("F14: `source unavailable` without a paper-faithfulness Pass naming H (here a Fail names it) is a fault",
            "N.G" in f3 and "F14" in f3["N.G"])
        say("a row citing no verdict file, or with an empty plain-English cell, is a fault",
            "cites no lane verdict" in f3.get("N.Lit", "") and "plain english" in f3.get("N.E", ""))
        pf([{"item": "Theorem 1", "verdict": "Pass", "checked": "H matches; G matches the quoted invocation; Lit; E; X; thm:hI"}])
        P1 = "2026-01-01-aaaaaaa/paper-faithfulness.json"
        rows_ok = (row("N.H", "yes", P1) + row("N.G", "source unavailable", P1) + row("N.Lit", "no (stronger than [3])", P1)
                   + row("N.E", "yes", P1))
        open(os.path.join(r2, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head + rows_ok + row("N.X", "yes", P1)
                                                          + row("thm:hI", "source unavailable", P1))
        f4 = collections.defaultdict(str, {re.search(r"`([^`]+)`", f).group(1): f for f in findings(cfg)})
        say("benchmarks: a hypothesis the walk finds IS the conclusion, or an inline binder restating another result "
            "(named `<result>:<binder>`), has no valid row saying `yes` or `source unavailable`, even with a Pass",
            set(f4) == {"N.X", "thm:hI"} and "IS THE CONCLUSION" in f4["N.X"] and "restates `lem`" in f4["thm:hI"])
        open(os.path.join(r2, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head + rows_ok + row("N.X", "no (it is the goal)", P1)
                                                          + row("thm:hI", "no (Lemma 2 restated)", P1))
        say("every name with a valid row: no finding", findings(cfg) == [])
        # B5 (a benchmark run): the restates flag is a question on the binder's own item; Python checks only
        # that the item exists, names the binder, is answered (Pass) and current -- no quote, no forced `no`
        yes_col = {"matches source": "yes", "stands for": "Theorem 1's hypothesis", "consistency evidence": "n=0",
                   "trivialization": "not trivial", "plain english": "n + 0 = n", "supporting verdict": "paper-faithfulness.json"}
        fit = FLAG_ITEM.format("thm:hI")
        def cp(ents, col=yes_col, fl=("restates `lem`",), mt=False):
            json.dump({"lane": "paper-faithfulness", "verdicts": ents}, open(os.path.join(r1, "paper-faithfulness.json"), "w"))
            return cite_problem(rd, r1, col, "thm:hI", list(fl), "N", None, mt=mt)
        good = [{"item": fit, "verdict": "Pass", "checked": "Theorem 1 prints it as its hypothesis"}]
        su = dict(yes_col, **{"matches source": "source unavailable"})
        say("B5: a restating binder recorded `yes` (or `source unavailable`) stands on a Pass of its flag item, "
            "whatever the entry's wording", cp(good) is None and cp(good, col=su) is None)
        say("B5: no flag item (a Pass on the result's own item naming it does not do), a Fail or Ambiguous on it, or "
            "the item of another binder: no valid `yes`",
            "has no Pass on the item" in (cp([{"item": "Theorem 1", "verdict": "Pass", "checked": "thm:hI printed"}]) or "")
            and "does not confirm it" in (cp([dict(good[0], verdict="Fail")]) or "")
            and "does not confirm it" in (cp(good + [dict(good[0], verdict="Ambiguous")]) or "")
            # DESIGN-SW2 C32: an Ambiguous on ANOTHER item that only mentions the binder is the adjudicator's to weigh
            and cp(good + [{"item": "Theorem 1", "verdict": "Ambiguous", "checked": "thm:hI?"}]) is None
            and "has no Pass on the item" in (cp([dict(good[0], item=FLAG_ITEM.format("thm:hJ"), checked="thm:hI")]) or ""))
        say("B5: `no` needs no flag item; IS THE CONCLUSION and a restating missing-theory hypothesis stay `no` only, "
            "a Pass on the item notwithstanding",
            cp([{"item": "Theorem 1", "verdict": "Fail", "checked": "thm:hI"}], col=dict(yes_col, **{"matches source": "no"})) is None
            and "circular" in (cp(good, fl=("IS THE CONCLUSION of `thm`", "restates `lem`")) or "")
            and "no missing theory" in (cp(good, mt=True) or ""))
        u_hi, u_hx = assumed(dep).get("thm:hI", []), [("thm", {"binder": "hX"})]
        q = flag_question(dep, u_hi)
        fi = flag_items(cfg)
        say("B5: the flag item and its question name the binder, its result and the restated result; none for a "
            "conclusion binder or an unflagged one; scheduled_items carries it",
            fi == {fit: "thm:hI"} and "`hI` of `thm`" in (q or "") and "`lem`" in (q or "") and flag_question(dep, u_hx) is None
            and flag_question(dep, assumed(dep)["N.H"]) is None and fit in scheduled_items(cfg))
        pf([{"item": "Theorem 1", "verdict": "Pass", "checked": "H matches; G matches the quoted invocation; Lit; E; X; thm:hI"}])
        rp = report(cfg)
        tr = trust_rows(cfg)[0][2]
        say("page 1 counts the `source unavailable` rows and the ones not matching their source",
            "1 with the source unavailable" in tr and "3 not matching" in tr and "6 hypothesis name(s)" in tr
            and "2 flagged by the walk as the conclusion itself or a restated result" in tr)
        by = collections.defaultdict(lambda: [""] * 5, {r_[0]: r_ for r_ in rp["rows"]})
        say("classification: a configured literature hypothesis; anything else unclassified (listed, never dropped)",
            by["`N.Lit`"][1].startswith("literature") and by["`N.H`"][1].startswith("unclassified")
            and by["`N.E`"][1].startswith("unclassified"))
        say("the report prints the adjudicator's plain English beside the Lean type, an axiom, a binder that IS the "
            "conclusion, the instances and the bare listing (F17)",
            by["`N.H`"][3] == "n is not 7" and "(h : N.H n)" in by["`N.H`"][4] and "`N.ax`" in by
            and "IS THE CONCLUSION" in by["`N.X`"][1] and "restates `lem`" in by["`thm:hI`"][1]
            and by["`thm:hI`"][1].startswith("inline") and "(hI : ∀ n, n + 0 = n)" in by["`thm:hI`"][4] and any("N.instX" in n_ for n_ in rp["notes"])
            and any("taken bare" in n_ and "`N.H` by `N.thm`" in n_ for n_ in rp["notes"]))
        st = summary_text(cfg)
        say("the lanes' summary prints the type and the plain English and names no record file",
            "Lean: `thm`: (h : N.H n)" in st and "plain English: n is not 7" in st and "ADOPTED" not in st)
        tr0 = trust_rows(cfg)[0][2]
        fpj = lambda d, m: json.dump({"commit": "c", "fingerprints": m}, open(os.path.join(d, "FINGERPRINTS.json"), "w"))
        fpj(r1, {"N.H": "a", "N.thm": "t1", "N.G": "g"}); fpj(r2, {"N.H": "a", "N.thm": "t1", "N.G": "g"})
        same_fp = findings(cfg)
        fpj(r2, {"N.H": "b", "N.thm": "t2", "N.G": "g"})
        f5 = collections.defaultdict(str, {re.search(r"`([^`]+)`", f).group(1): f for f in findings(cfg)})
        say("review fix 2: a row is invalid once H's fingerprint (or an inline binder's result's) changed since "
            "the round of the verdict it cites; unchanged, it stays valid",
            same_fp == [] and set(f5) == {"N.H", "thm:hI"} and "changed" in f5["N.H"] and "`N.thm` changed" in f5["thm:hI"])
        os.remove(os.path.join(r1, "FINGERPRINTS.json")); os.remove(os.path.join(r2, "FINGERPRINTS.json"))
        pf([{"item": "Theorem 1", "verdict": "Pass", "checked": "G matches the quoted invocation; Lit; E; X; thm:hI"},
            {"item": "Theorem 3", "verdict": "Fail", "checked": "H is stronger than the paper's (H)"}])
        f6 = collections.defaultdict(str, {re.search(r"`([^`]+)`", f).group(1): f for f in findings(cfg)})
        tr6 = trust_rows(cfg)[0][2]
        say("review fix 2: `matches source: yes` while the cited lane's only verdict naming H Fails is a finding, and "
            "page 1 does not count it as matching",
            set(f6) == {"N.H"} and "does not confirm" in f6["N.H"] and "2 matching their source" in tr0
            and "1 matching their source" in tr6 and "1 pending" in tr6)
        import fingerprint as fp_
        keep_ga = fp_.genuine_approvals
        try:
            fp_.genuine_approvals = lambda *a_, **k_: [("c0", {"by": "human", "binders": {"thm": []}})]
            nb_rec = new_binders(cfg)
            nt_rec = report(cfg)["notes"]
            fp_.genuine_approvals = lambda *a_, **k_: [("c0", {"by": "human", "binders_not_recorded": "x"})]
            nb_old = new_binders(cfg)
            nt_old = report(cfg)["notes"]
        finally:
            fp_.genuine_approvals = keep_ga
        say("review fix 4: the binders the approval recorded are what 'added since the approval' compares with "
            "(no DEPENDENCIES.json committed at approval); an approval without them is 'not computed', a note, "
            "never a finding",
            nb_rec == {"thm": [("hI", "∀ n, n + 0 = n")]}
            and any("added since the approval: `thm`: (hI : ∀ n, n + 0 = n)" in n_ for n_ in nt_rec)
            and nb_old is None and any("added since the approval: not computed" in n_ for n_ in nt_old))
        say("added since approval: a binder beyond the approval's, per result (by type)",
            added_binders({"t": [{"binder": "a", "type_pp": "1 ≤ n"}]},
                          {"t": [{"binder": "a", "type_pp": "1 ≤ n"}, {"binder": "b", "type_pp": "n ≠ 7"}],
                           "u": [{"binder": "c", "type_pp": "x"}]}) == {"t": [("b", "n ≠ 7")]})
        sdoc = {"assumes": {"c": [{"name": "N.MSet", "binder": "S", "kind": "struct", "type_pp": "N.MSet n",
                                   "embedded": False}]},
                "restates": {"c": [{"binder": "S.h1", "result": "lem2"}, {"binder": "inst", "result": "lem"}]},
                "binders": {"c": [{"binder": "S", "type_pp": "N.MSet n"}, {"binder": "inst", "type_pp": "Fact (∀ n, n = n)"}]}}
        sa = assumed(sdoc)
        say("review fix 1: a structure binder flagged through one of its fields (`S.h1`) carries the flag on the "
            "structure's name, with no second inline name; a flagged `Fact` binder naming nothing is inline",
            name_flags(sdoc, sa["N.MSet"]) == ["restates `lem2`"] and set(sa) == {"N.MSet", "c:inst"}
            and sa["c:inst"][0][1]["type_pp"] == "Fact (∀ n, n = n)")
        os.remove(os.path.join(rd, "DEPENDENCIES.json"))
        say("no walk: no hypothesis finding (Phase 0's RED[dependencies] says so), and page 1 says NOT COMPUTED",
            findings(cfg) == [] and trust_rows(cfg)[0][2].startswith("NOT COMPUTED"))
    finally:
        project.REPO, project._scope_time = saved, saved_st
        shutil.rmtree(tmp, ignore_errors=True)
    _mt_selftest(say)
    _mt_ruled_selftest(say)
    _c32_selftest(say)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


def _mt_selftest(say):
    """B6 (U2 §7, F13): the canonical missing-theory line, its checks, the classification and page 1."""
    import collections, shutil, tempfile
    tmp = tempfile.mkdtemp()
    saved = project.REPO
    try:
        project.REPO = tmp
        rd = os.path.join(tmp, "R")
        r1 = os.path.join(rd, "2026-01-01-aaaaaaa")
        os.makedirs(r1)
        dep = {"walked": ["thm", "lem"], "binders": {}, "goal": {}, "restates": {},
               "assumes": {"thm": [{"name": "N.LS", "binder": "hLS", "kind": "prop", "type_pp": "N.LS", "embedded": False}],
                           "lem": []}}
        json.dump(dep, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        cfg = {"rounds_dir": "R", "namespace": "N", "involvement": "hands-off"}
        T = "[DELEGATED 2026-01-02, operator under hands-off (intake); reversal: re-prove]"
        Q = 'paper: "by the theorem of Lovász and Szegedy [7], every graphon is a limit of finite graphs"'
        S = "searched: Mathlib (grep -rn graphon Mathlib/), TauCeti (grep -rn graphon TauCeti/)"
        E = "estimate: about 3000 lines and a week of agent time"
        good = f"- {T} missing theory: assume `N.LS` for `N.thm` — {S}; {E}; {Q}"
        logp = os.path.join(rd, "RUN_LOG.md")
        w = lambda *ls: open(logp, "w").write("# log\n## Stage 2\n" + "\n".join(ls) + "\n## Fresh readers\n"
                                              f"- {T} missing theory: graphons, a bare line quoted by a reader\n")
        probs = lambda c=cfg: missing_theory(c)["problems"]
        w(good)
        mt = missing_theory(cfg)
        say("B6: the canonical [DELEGATED] missing-theory line under hands-off, `H` in the result's assumption "
            "list: no problem; the hypothesis is classified missing theory (a line quoted under Fresh readers is "
            "not a decision)", probs() == [] and set(mt["assume"]) == {"N.LS"}
            and classify(cfg, "N.LS") == "missing-theory hypothesis" and mt["assume"]["N.LS"]["quote"].startswith("by the"))
        tr = trust_rows(cfg)
        mrow = [t for t in tr if t[0] == "Missing theory"]
        say("B6: page 1 says `<result> proved assuming <H>`, quotes the paper, says who decided and that it is not "
            "yet checked (no hypothesis row)", len(mrow) == 1 and "proved assuming `LS`" in mrow[0][1]
            and "Lovász" in mrow[0][1] and "[DELEGATED 2026-01-02" in mrow[0][1] and mrow[0][2].startswith("PENDING"))
        st = summary_text(cfg)
        say("B6: the lanes' listing shows the class, the result and the quoted passage (F13: the lane judges it)",
            "N.LS` [missing-theory hypothesis]" in st
            and "Missing theory: `N.LS` is assumed for `N.thm`; the paper invokes it: “by the theorem" in st)
        w(f"- {T} take the graphon approximation theorem `N.LS` as a named hypothesis (missing theory)")
        p1, f1 = probs(), missing_theory(cfg)["form"]
        w(f"- {T} assume `N.LS` for `N.thm`: Mathlib has no graphons, so a hypothesis")
        p1b, f1b = probs(), missing_theory(cfg)["form"]
        say("B6 (DESIGN-MT): a bare [DELEGATED] missing-theory decision (no canonical form; also one in its own words: "
            "a hypothesis because Mathlib lacks something) is no FAIL but a suspect for the adjudicator (adj-record), "
            "and its hypothesis is not classified missing theory",
            p1 == [] and len(f1) == 1 and p1b == [] and len(f1b) == 1
            and classify(cfg, "N.LS").startswith("unclassified")
            and [f.code for f in missing_theory_findings(cfg)] == ["adj-record"])
        w(f"- {T} take the graphon approximation theorem `N.LS` as a named hypothesis (missing theory)", good)
        p2, f2 = probs(), missing_theory(cfg)["form"]
        w(good, f"- {T} take the graphon approximation theorem `N.LS` as a named hypothesis (missing theory)")
        p2b, f2b = probs(), missing_theory(cfg)["form"]
        say("B6: a later canonical line naming the same hypothesis clears a bare one (rewording it in place does "
            "too); a bare line AFTER the canonical one is still a suspect (DESIGN-MT: for the adjudicator)",
            p2 == [] and f2 == [] and p2b == [] and len(f2b) == 1)
        w(f"- {T} missing theory: assume `N.LS` for `N.thm` — {S}; {E}")
        p3 = probs()
        w(f"- {T} missing theory: assume `N.LS` for `N.thm` — {S}; {E}; paper: \"see [7]\"")
        p3b = probs()
        say("B6: the quote is required (missing, or a word or two)",
            len(p3) == 1 and "no quote" in p3[0] and len(p3b) == 1 and "no quote" in p3b[0])
        w(f"- {T} missing theory: assume `N.LS` for `N.thm` — searched: Mathlib (grep graphon); {E}; {Q}")
        p4 = probs()
        say("B6: every configured library is searched (TauCeti missing from `searched:`)",
            len(p4) == 1 and "TauCeti" in p4[0])
        w(f"- {T} missing theory: assume `N.LS` for `N.lem` — {S}; {E}; {Q}",
          f"- {T} missing theory: assume `N.Other` for `N.nope` — {S}; {E}; {Q}")
        p5 = probs()
        say("B6: a hypothesis not in its result's assumption list (the walk) fails, and so does a result the walk "
            "does not read; page 1 says the line and the Lean disagree",
            len(p5) == 2 and any("not in the assumption list of `lem`" in p_ for p_ in p5)
            and any("not a result the assumption walk reads" in p_ for p_ in p5)
            and any("NOT a hypothesis of that result" in t[2] for t in trust_rows(cfg) if t[0] == "Missing theory"))
        w(good)
        inv = dict(cfg, involvement="involved")
        p6 = missing_theory(inv)["problems"]
        import subprocess
        git = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True)
        git("init", "-q")
        commit = lambda: (git("add", "-A"), git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "log"))
        hl = f"- missing theory (human 2026-01-02): assume `N.LS` for `N.thm` — {S}; {E}; {Q}"
        ans = '- human answer (2026-01-02; `N.thm`): "option (2): take Lovász–Szegedy as a hypothesis"'
        w(hl, ans)
        commit()
        p6b, p6c = missing_theory(inv)["problems"], probs()
        say("B6: a [DELEGATED] line under involved fails (the human decides); the human form with the human's "
            "committed answer passes under involved and fails under hands-off; page 1 says the human decided",
            len(p6) == 1 and "the human decides" in p6[0] and p6b == [] and len(p6c) == 1 and "hands-off" in p6c[0]
            and any("decided by the human (human 2026-01-02)" in t[1] for t in trust_rows(inv)))
        so = dict(cfg, involvement="statements-only")
        w(hl)
        commit()
        p6d, p6e = missing_theory(inv)["problems"], missing_theory(so)["problems"]
        tr6 = [t[1] for t in trust_rows(inv) if t[0] == "Missing theory"]
        w(hl, ans.replace("2026-01-02", "2026-01-05"))
        commit()
        p6f = missing_theory(inv)["problems"]
        w(hl, ans)
        p6g = missing_theory(inv)["problems"]
        commit()
        p6h = missing_theory(inv)["problems"]
        say("B6 review fix 2: under involved and statements-only a human missing-theory line needs the human's "
            "recorded answer naming the result on its date, COMMITTED (the line itself is no answer; another date, "
            "or an answer not yet committed, does not bind it); page 1 never says 'decided by the human' without it",
            len(p6d) == 1 and "no human answer naming `N.thm` dated 2026-01-02" in p6d[0] and len(p6e) == 1
            and len(tr6) == 1 and "decided by the human" not in tr6[0] and "NO recorded human answer" in tr6[0]
            and len(p6f) == 1 and len(p6g) == 1 and p6h == [])
        sk = f"- missing theory (human 2026-01-02): do not formalize `N.thm` — {S}; {E}"
        skd = f"- {T} missing theory: do not formalize `N.thm` — {S}; {E}"
        ans3 = '- human answer (2026-01-02; `N.thm`): "(3), do not formalize it"'
        res5 = {}
        for lvl_ in ("involved", "statements-only", "hands-off"):
            c_ = dict(cfg, involvement=lvl_)
            w(sk, ans3)
            commit()
            res5[lvl_, "human"] = (missing_theory(c_)["problems"],
                                   [t for t in trust_rows(c_) if t[0] == "Missing theory"])
            w(skd)
            commit()
            res5[lvl_, "delegated"] = (missing_theory(c_)["problems"], [])
        say("B6 review fix 5: the human's option (3) has a canonical form, `- missing theory (human <date>): do not "
            "formalize `<R>` — searched: …; estimate: …`: it passes under involved and statements-only (page 1: not "
            "formalized, decided by the human) and fails under hands-off; option (3) as [DELEGATED] fails at every "
            "level",
            all(res5[l_, "human"][0] == [] and len(res5[l_, "human"][1]) == 1 and "not formalized" in res5[l_, "human"][1][0][1]
                and "decided by the human" in res5[l_, "human"][1][0][1] for l_ in ("involved", "statements-only"))
            and len(res5["hands-off", "human"][0]) == 1 and "hands-off" in res5["hands-off", "human"][0][0]
            and all(any("option (3), the human's alone" in p_ for p_ in res5[l_, "delegated"][0])
                    for l_ in ("involved", "statements-only", "hands-off")))
        shutil.rmtree(os.path.join(tmp, ".git"))
        w(good, f"- {T.replace('re-prove', 're-approve')} change N.thm — missing theory",
          f"- {T} leave `N.lem` unproved — hard, not missing theory",
          f"- {T} keep the hypothesis hk of N.lem — not missing theory, an ordinary hypothesis")
        say("B6: a re-approval's line (`change … — missing theory`), a left-unproved line and a negated mention are "
            "not missing-theory decisions", probs() == [] and missing_theory(cfg)["form"] == [])
        w(f"- {T} missing theory: build the Ramsey number bound R(3,3) = 6 for `N.lem` — {S}; {E}")
        bt = [t for t in trust_rows(cfg) if t[0] == "Missing theory"]
        say("B6: a `build` line needs no quote; page 1 says the theory was built here",
            probs() == [] and len(bt) == 1 and "was built in this project" in bt[0][1])
        # benchmark: H strengthens the step the paper invokes; the lane Fails it (F13), the row cannot say `yes`
        w(good)
        head = TEMPLATE + "\n|---|---|---|---|---|---|---|\n"
        P = "paper-faithfulness.json"
        json.dump({"lane": "paper-faithfulness", "verdicts": [
            {"item": "Theorem 5.1", "verdict": "Fail", "checked": "N.LS is STRONGER than the quoted invocation "
             "(tex l.88 invokes convergence in cut distance; LS asserts a rate): an intermediate step strengthened"}]},
            open(os.path.join(r1, P), "w"))
        row = lambda m, triv="not trivial": (f"| `N.LS` | missing theory: Lovász–Szegedy, invoked at tex l.88 | {m} | "
                                             f"a graphon | {triv} | every graphon is a limit of graphs | {P} |\n")
        open(os.path.join(r1, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head + row("yes"))
        f7 = [x for x in findings(cfg) if "N.LS" in x]
        mt_st = lambda: next((t[2] for t in trust_rows(cfg) if t[0] == "Missing theory"), "")
        st7 = mt_st()
        open(os.path.join(r1, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head + row("no (stronger than tex l.88)"))
        st8 = mt_st()
        say("B6 benchmark (strengthened intermediate step): the paper-faithfulness Fail leaves no valid `yes` row "
            "(a finding, page 1 PENDING); the `no` row is page 1's 'does NOT match'",
            len(f7) == 1 and "does not confirm" in f7[0] and st7.startswith("PENDING") and "does NOT match" in st8)
        json.dump({"lane": "paper-faithfulness", "verdicts": [
            {"item": "Theorem 5.1", "verdict": "Pass", "checked": "N.LS says no more than tex l.88"}]},
            open(os.path.join(r1, P), "w"))
        open(os.path.join(r1, "ADOPTED.md"), "w").write("## Hypotheses\n\n" + head
                                                         + row("yes", "H is the main step of the proof (the paper too)"))
        f9a = findings(cfg)
        json.dump({"lane": "paper-faithfulness", "verdicts": [
            {"item": F13_ITEM.format("N.LS"), "verdict": "Pass", "checked": "N.LS says no more than tex l.88"}]},
            open(os.path.join(r1, P), "w"))
        st9 = mt_st()
        say("F13 item: a missing-theory hypothesis's `yes` needs a Pass on its own item \"F13: the missing theory "
            "<H>\" (a Pass on another item naming H does not do); f13_items lists the item for scope.py",
            len(f9a) == 1 and "has no Pass on the item" in f9a[0] and f13_items(cfg) == {F13_ITEM.format("N.LS"): "N.LS"})
        say("B6: a confirmed row reads 'checked' on page 1, with the non-vacuity flag that H is the goal's main step",
            findings(cfg) == [] and st9.startswith("checked") and "main step" in st9)
        json.dump(dict(dep, restates={"thm": [{"binder": "hLS", "result": "lem"}]}), open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        f10, p10, st10 = findings(cfg), probs(), mt_st()
        w(f"- {T} keep the hypothesis `N.LS`, an ordinary paper lemma")
        f10b = findings(cfg)
        w(good)
        json.dump(dict(dep, goal={"thm": ["hLS"]}), open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        f10c = findings(cfg)
        say("B6 review fix 1: a missing-theory hypothesis the walk flags as restating a result the project states "
            "(a test run: a cited proposition the project also proves) is FAIL[missing-theory] telling the operator "
            "to prove it; its row may only say `no` (with or without the line), and page 1 never says 'checked'",
            len(p10) == 1 and "restates `lem`" in p10[0] and "Prove it" in p10[0] and len(f10) == 1
            and "restates `lem`" in f10[0] and not st10.startswith("checked") and len(f10b) == 1
            and "restates `lem`" in f10b[0] and len(f10c) == 1 and "IS THE CONCLUSION" in f10c[0])
        import dependencies
        keep_gr = dependencies.goal_roots
        try:
            json.dump(dict(dep, goal={"thm": ["hLS"]}), open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
            dependencies.goal_roots = lambda c_: []
            p11 = missing_theory(cfg)
            dependencies.goal_roots = lambda c_: ["thm"]
            p11b = missing_theory(cfg)
            f11b = missing_theory_findings(cfg)
            json.dump(dict(dep, restates={"thm": [{"binder": "hLS", "result": "lem"}]}), open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
            dependencies.goal_roots = lambda c_: ["lem"]
            p11c = missing_theory(cfg)
        finally:
            dependencies.goal_roots = keep_gr
        say("B6 review fix 4: a missing-theory hypothesis that IS a goal result's conclusion is FAIL[unproved-goal] "
            "(stop 1, the human's), not a page-1 mismatch; a non-goal result's own conclusion is FAIL[missing-theory] "
            "(prove it or leave it unproved); DESIGN-SW2 C8: one that only restates a goal result is the operator's "
            "curable FAIL[missing-theory] (use that result), no stop 1",
            len(p11["problems"]) == 1 and "conclusion of `thm`" in p11["problems"][0] and p11["goal"] == []
            and p11b["problems"] == [] and len(p11b["goal"]) == 1 and "stop 1" in p11b["goal"][0]
            and [f.code for f in f11b] == ["unproved-goal"] and project.is_stop_cause("unproved-goal")
            and p11c["goal"] == [] and len(p11c["problems"]) == 1 and "restates `lem`" in p11c["problems"][0]
            and "Prove it" in p11c["problems"][0])
        dep2 = dict(dep, assumes=dict(dep["assumes"], main=[dict(dep["assumes"]["thm"][0], binder="h")]),
                    walked=["thm", "lem", "main"])
        json.dump(dep2, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        try:
            dependencies.goal_roots = lambda c_: ["main"]
            r12 = [t for t in trust_rows(cfg) if t[0] == "Missing theory"]
        finally:
            dependencies.goal_roots = keep_gr
        say("B6 review fix 6: H assumed for a lemma a goal depends on (the goal's statement takes it too, the walk): "
            "page 1 says the goal is proved assuming H",
            len(r12) == 1 and "so the goal result `main` is proved assuming it too" in r12[0][1])
        w(f"- {T} missing theory: assume `N.LS` for `N.thm` — {S}; {E}; {Q}",
          f"- {T.replace('re-prove', 'none')} missing theory: build graphon theory for `N.thm` — {S}; {E}")
        json.dump(dep, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        p13 = probs()
        b13 = [t for t in trust_rows(cfg) if t[0] == "Missing theory"]
        json.dump(dict(dep, assumes={"thm": [], "lem": []}), open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        p13b = probs()
        b13b = [t for t in trust_rows(cfg) if t[0] == "Missing theory"]
        say("B6 review fix 3: a `build` line while the hypothesis it replaces (an earlier `assume` line for the "
            "result) is still a binder of the result fails, and page 1 says NOT built; once the binder is gone the "
            "build line supersedes the assume line (no 'not in the assumption list' fault) and page 1 says built",
            len(p13) == 1 and "still a hypothesis of `N.thm`" in p13[0] and len(b13) == 1
            and "NOT built" in b13[0][2] and p13b == [] and len(b13b) == 1 and b13b[0][2].startswith("proved here"))
        json.dump(dep, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        w(good)
        os.remove(os.path.join(rd, "DEPENDENCIES.json"))
        say("B6: no walk: the assumption-list check waits for Phase 0 (RED[dependencies]); page 1 says not computed",
            probs() == [] and any("NOT COMPUTED" in t[2] for t in trust_rows(cfg) if t[0] == "Missing theory"))
        say("B6: FAIL[missing-theory] is a document fault, F/rerun in release, closed by make_report.py --check",
            project.cause_class(MT_CODE) == "document" and project.release_kind(MT_CODE) == "rerun"
            and project.release_class(MT_CODE) == "F" and project.CLOSER.get(MT_CODE) == "make_report.py --check")
    finally:
        project.REPO = saved
        shutil.rmtree(tmp, ignore_errors=True)


def _c32_selftest(say):
    """DESIGN-SW2 C32: only a non-Pass on H's own item blocks `yes` / `source unavailable`."""
    import shutil, tempfile
    d = tempfile.mkdtemp()
    try:
        r = os.path.join(d, "2026-01-01-full-abcdef12345"); os.makedirs(r)
        col = {"matches source": "yes", "stands for": "x", "consistency evidence": "y", "trivialization": "not trivial",
               "plain english": "z", "supporting verdict": "paper-faithfulness.json"}

        def run(ents, w="yes"):
            json.dump({"verdicts": ents}, open(os.path.join(r, "paper-faithfulness.json"), "w"))
            return cite_problem(d, r, dict(col, **{"matches source": w}), "N.hP", ns="N")
        ok_p = {"item": "F15: the hypothesis N.hP", "verdict": "Pass", "checked": "matches"}
        men = {"item": "Theorem 3", "verdict": "Fail", "checked": "the bound, unlike `hP`, is too weak"}
        mine = {"item": "hP", "verdict": "Fail", "checked": "no"}
        amb = {"item": "N.hP", "verdict": "Ambiguous", "checked": "unclear"}
        say("SW2-C32: a Fail on another item that only mentions H no longer forces `no` (yes / source unavailable "
            "accepted on H's own Pass); a Fail or Ambiguous on H's own item still blocks; no Pass naming H still blocks",
            run([ok_p, men]) is None and run([ok_p, men], "source unavailable") is None
            and run([ok_p, mine]) is not None and run([ok_p, amb], "source unavailable") is not None
            and run([men]) is not None)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _mt_ruled_selftest(say):
    """DESIGN-MT: a line the missing-theory check only suspects goes to the adjudicator (MT-u1..u10, the fix round's
    S-F1, S-F3, S-F4, C-F1, C-F2)."""
    import shutil, subprocess, tempfile
    import make_report
    tmp = tempfile.mkdtemp()
    saved = project.REPO, make_report.REPO
    try:
        project.REPO = make_report.REPO = tmp
        rd = os.path.join(tmp, "R")
        os.makedirs(rd)
        open(os.path.join(tmp, "N.lean"), "w").write("namespace N\ntheorem thm : True := trivial\n"
                                                     "def LS : Prop := True\nend N\n")
        dep = {"walked": ["thm"], "binders": {}, "goal": {}, "restates": {},
               "assumes": {"thm": [{"name": "N.LS", "binder": "hLS", "kind": "prop", "type_pp": "N.LS",
                                    "embedded": False}]}}
        setdep = lambda d_: json.dump(d_, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        setdep(dep)
        cfg = {"rounds_dir": "R", "namespace": "N", "involvement": "hands-off", "lean_files": ["N.lean"],
               "libraries": ["Mathlib"]}
        git = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True)
        git("init", "-q")
        commit = lambda msg="log": (git("add", "-A"), git("-c", "user.name=t", "-c", "user.email=t@t", "commit",
                                                          "-qm", msg))
        k = [0]

        def rnd(*ls, prompt_ids=None, do_commit=True):
            """A new round whose adjudicator prompt lists `prompt_ids` (default: every id its rulings name) and whose
            ADOPTED.md holds `ls`, committed as `adjudicate R` (its first)."""
            k[0] += 1
            r_ = f"2026-02-{k[0]:02d}-{k[0]:07x}"
            os.makedirs(os.path.join(rd, r_, "prompts"))
            json.dump({"_meta": {"kind": "full"}}, open(os.path.join(rd, r_, "TARGET.json"), "w"))
            ids = prompt_ids if prompt_ids is not None else re.findall(r"MT RULED ([0-9a-f]{12})", "\n".join(ls))
            open(os.path.join(rd, r_, "prompts", "adjudicator.txt"), "w").write(
                "PENDING ADJUDICATION FAULTS\n" + "".join(f"  - … `- MT RULED {i_} | not …`\n" for i_ in ids))
            open(os.path.join(rd, r_, "ADOPTED.md"), "w").write("# A\n\n## Notes\n" + "".join(l_ + "\n" for l_ in ls))
            if do_commit:
                commit(f"adjudicate {r_}")
            return r_
        T = "[DELEGATED 2026-11-15, operator under hands-off (intake); reversal: re-approve]"
        L72 = (f"- global:G2: {T} keep the minor and star-contraction definitions built for this run, with G/A read as a "
               "quotient graph (global difference G2) — conservative rule, as in the logged Stage 2 decision to build "
               "the missing theory, and the adjudicator of round 2026-11-14-full-f97ada758fe found the quotient to be "
               "the direct reading of tex l.141-144")
        A72 = L72.replace("- global:G2: ", "- answered global:G2 (2026-11-15, 2026-11-15-full-a5774234119): ")
        S = "searched: Mathlib (grep -rn graphon Mathlib/)"
        E = "estimate: about 3000 lines"
        Q = 'paper: "by the theorem of Lovász and Szegedy [7], every graphon is a limit"'
        TP = T.replace('re-approve', 're-prove')
        canon = f"- {TP} missing theory: assume `N.LS` for `N.thm` — {S}; {E}; {Q}"
        logp = os.path.join(rd, "RUN_LOG.md")
        w = lambda *ls: open(logp, "w").write("# log\n## Checkpoint C (2026-11-15, delegated)\n" + "\n".join(ls) + "\n")
        MT = lambda c_=cfg, **kw: missing_theory(c_, **kw)
        w("", L72)
        commit("setup")
        mt, fs, lid = MT(), missing_theory_findings(cfg), mt_line_id(L72)
        tr1 = [t for t in trust_rows(cfg) if t[0] == "Missing theory"]
        say("safety F2: page 1 (REPORT and SUMMARY) says in plain words that a decision line mentioning missing "
            "theory is not judged by an independent agent, naming it by its anchor",
            len(tr1) == 1 and "(global:G2)" in tr1[0][1] and "not judged by an independent agent" in tr1[0][2])
        say("MT-u1: the live run's l.72 (no backticked name, no ruling) is a suspect for the adjudicator, no problem: "
            "an adj-record finding with its id, anchor, line number, the full line and both ruling forms",
            mt["problems"] == [] and [(i_, n_) for i_, _l, n_ in mt["form"]] == [(lid, 4)]
            and [f.code for f in fs] == ["adj-record"] and f"line id {lid}, anchor global:G2" in fs[0] and "l.4 " in fs[0]
            and L72 in fs[0] and f"MT RULED {lid} | not a missing-theory decision" in fs[0]
            and f"MT RULED {lid} | a missing-theory decision for" in fs[0])
        hum = f"- missing theory (human 2026-11-15): assume hP for thm, Mathlib lacks graphons; {T} keep the definitions"
        say("review C2 / safety F4: a Checkpoint C line and its word-for-word `## Answered` copy share one id; the same "
            "text on another anchor, a one-character change, or a human line quoting the tag mid-text does not",
            mt_line_id(A72) == lid and mt_line_id(L72.replace("global:G2", "global:G3")) != lid
            and mt_line_id(L72 + ".") != lid and mt_line_id(L72.replace(" keep", "  keep")) == lid
            and mt_line_id(hum) != mt_line_id(f"- {T} keep the definitions"))
        r1 = rnd(f"- MT RULED {lid} | not a missing-theory decision: it keeps the G2 reading")
        mt2 = MT()
        w("", L72, A72)
        commit()
        mt2b = MT()
        say("MT-u2: a committed adjudication's `MT RULED <id> | not a missing-theory decision: …` clears it, and its "
            "`## Answered` copy too (C2)", mt2["form"] == [] and mt2["problems"] == [] and lid in mt2["ruled"]
            and mt2b["form"] == [] and mt2b["problems"] == [])
        w("", L72 + " (sic)")
        mt3 = MT()
        rnd("- MT RULED 0123456789ab | not a missing-theory decision: another line")
        mt3b = MT()
        say("MT-u3: a ruling binds its exact line: the line changed, or a ruling for another id, is pending again",
            len(mt3["form"]) == 1 and mt3["problems"] == [] and len(mt3b["form"]) == 1)
        # MT-u4: a "decision" ruling, at every level
        res4 = {}
        for lvl_ in ("involved", "statements-only", "hands-off"):
            c_ = dict(cfg, involvement=lvl_)
            bare = f"- {T} take the graphon theorem as a named hypothesis (missing theory, {lvl_})"
            bid = mt_line_id(bare)
            w("", canon, bare)
            rr = rnd(f"- MT RULED {bid} | a missing-theory decision for `N.LS`: it takes LS as a hypothesis")
            before = [p_ for p_ in MT(c_)["problems"] if f"MT RULED {bid}" in p_]
            w("", bare, canon)
            commit()
            after = [p_ for p_ in MT(c_)["problems"] if "MT RULED" in p_]
            res4[lvl_] = (before, after, rr)
        b_ = res4["hands-off"][0] or [""]
        say("MT-u4: a ruling `a missing-theory decision for `N``: the operator's hard problem naming N and the round, "
            "cleared by a canonical line for N logged AFTER it, not by one before it; under involved and "
            "statements-only the text gives the human route; under hands-off it does not",
            all(len(res4[l_][0]) == 1 and res4[l_][1] == [] for l_ in res4)
            and "for `N.LS`" in b_[0] and res4["hands-off"][2] in b_[0] and "the human chooses" not in b_[0]
            and all("the human chooses" in res4[l_][0][0] for l_ in ("involved", "statements-only")))
        # MT-u5 and safety F1: rulings that do not count
        L5 = f"- {T} keep the definitions, as in the decision to build the missing theory (u5)"
        i5 = mt_line_id(L5)
        w("", L5, f"- MT RULED {i5} | not a missing-theory decision: written by the operator into RUN_LOG.md")
        commit()
        u5a = len(MT()["form"]) == 1
        rp = rnd(f"- MT RULED {i5} | not a missing-theory decision: uncommitted", do_commit=False)
        u5b = len(MT()["form"]) == 1
        u5c = len(MT(round_name=rp)["form"]) == 0
        git("add", "-A")
        u5d = len(MT()["form"]) == 1          # staged, not committed: still none
        git("reset", "-q")
        json.dump({"why": "set aside"}, open(os.path.join(rd, rp, project.ABANDONED), "w"))
        commit(f"adjudicate {rp}")
        u5f = len(MT()["form"]) == 1          # set aside (it stays set aside)
        # safety F1: the operator re-commits an OLD round's ADOPTED.md with its own ruling, through the tool
        import integrity
        open(os.path.join(rd, r1, "ADOPTED.md"), "a").write(f"- MT RULED {i5} | not a missing-theory decision: mine\n")
        try:
            integrity.commit_adjudication(tmp, rd, "R", r1, cfg=cfg)
        except ValueError:
            commit(f"adjudicate {r1}")
        u5g = len(MT()["form"]) == 1 and git("log", "-1", "--format=%s").stdout.strip() == f"adjudicate {r1}"
        rnd(f"- MT RULED {i5} | not a missing-theory decision: not in this adjudicator's prompt", prompt_ids=[])
        u5h = len(MT()["form"]) == 1
        # the old round's prompt DID list the id, but its first adjudication did not rule it: a re-commit still rules nothing
        r6 = rnd("- a note", prompt_ids=[i5])
        open(os.path.join(rd, r6, "ADOPTED.md"), "a").write(f"- MT RULED {i5} | not a missing-theory decision: added later\n")
        commit(f"adjudicate {r6}")
        u5h = u5h and len(MT()["form"]) == 1
        # review N1: a `revotes` commit with no re-vote lane files rules nothing; with them (an honest re-vote) it does
        Ln1 = f"- {T} keep the definitions, as in the decision to build the missing theory (n1)"
        in1 = mt_line_id(Ln1)
        w("", Ln1)
        commit()
        rv = rnd("- a note", prompt_ids=[])
        open(os.path.join(rd, rv, "ADOPTED.md"), "a").write(f"- MT RULED {in1} | not a missing-theory decision: mine\n")
        open(os.path.join(rd, rv, "prompts", "adjudicator-revotes.txt"), "w").write(f"- MT RULED {in1} | not …\n")
        commit(f"adjudicate {rv} revotes")
        n1a = [x[0] for x in MT()["form"]] == [in1]
        rv2 = rnd("- a note", prompt_ids=[])
        open(os.path.join(rd, rv2, "ADOPTED.md"), "a").write(f"- MT RULED {in1} | not a missing-theory decision: re-voted\n")
        open(os.path.join(rd, rv2, "prompts", "adjudicator-revotes.txt"), "w").write(f"- MT RULED {in1} | not …\n")
        os.makedirs(os.path.join(rd, rv2, "revote"))
        json.dump({"lane": "correspondence", "verdicts": []}, open(os.path.join(rd, rv2, "revote", "correspondence--x.json"), "w"))
        commit(f"adjudicate {rv2} revotes")
        n1b = MT()["form"] == []
        say("review N1: an `adjudicate R revotes` commit holding no re-vote lane files of R rules nothing (the operator's "
            "`--commit-adjudication --revotes` on an old round); an honest re-vote adjudication's ruling counts",
            n1a and n1b)
        rnd(f"- MT RULED {i5} | not a missing-theory decision: listed")
        u5i = len(MT()["form"]) == 0
        # DESIGN-SW2 C19: a suspect logged after the round's adjudicator prompt was written is not refused at that
        # round's adjudication commit (it was never shown); it stays pending and the next prompt lists it
        L19 = f"- {T} keep the definitions, the missing theory being built later (c19)"
        i19 = mt_line_id(L19)
        w("", L19)
        commit()
        r19 = rnd("- MT RULED zzz | bogus", prompt_ids=[], do_commit=False)
        has19 = lambda fs_: any(f"line id {i19}" in str(f_) for f_ in fs_)
        f19c = make_report.adjudication_findings(cfg, r19, revotes=False)
        f19p = make_report.adjudication_findings(cfg, r19)
        pend19 = [t for _c, t in make_report.pending_adjudication(cfg)]
        commit(f"adjudicate {r19}")
        r19b = rnd("- a note", prompt_ids=[i19], do_commit=False)
        f19b = make_report.adjudication_findings(cfg, r19b, revotes=False)
        open(os.path.join(rd, r19b, "ADOPTED.md"), "a").write(f"- MT RULED {i19} | not a missing-theory decision: x\n")
        f19r = make_report.adjudication_findings(cfg, r19b, revotes=False)
        commit(f"adjudicate {r19b}")
        isrc = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "integrity.py"), encoding="utf-8").read()
        say("SW2-C19: an MT suspect the round's adjudicator prompt did not list is not refused at its adjudication "
            "commit (other findings are); unfiltered elsewhere (the prompt, pending_adjudication); the next round's "
            "prompt lists it, its commit refuses it until ruled, and a ruling clears it; integrity.py still passes "
            "`revotes=bool(revotes)` (the signal this filter keys on)",
            not has19(f19c) and any("is not an MT RULED ruling" in str(f_) for f_ in f19c) and has19(f19p)
            and any(f"line id {i19}" in t for t in pend19) and has19(f19b) and not has19(f19r)
            and "adjudication_findings(cfg, round_name, revotes=bool(revotes))" in isrc)
        say("MT-u5 / safety F1: a ruling counts only from a round's ADOPTED.md as of its FIRST `adjudicate R` commit, "
            "for an id its adjudicator prompt lists (or the round being committed, as on disk): one in RUN_LOG.md, "
            "uncommitted, staged, set aside, re-committed into an old round, or for an id the prompt did not list does not",
            all((u5a, u5b, u5c, u5d, u5f, u5g, u5h, u5i)))
        # MT-u6: cure 1 unchanged; review C-F1: a canonical-form attempt naming its result stays hard
        w("", f"- {T} take `N.LS` as a named hypothesis (missing theory)", canon)
        mt6 = MT()
        att = f"- {TP} missing theory: assume `N.LS` for `N.thm` — {S}; {Q}"
        w("", att)
        mt6b = MT()
        w("", att, canon)
        mt6c = MT()
        w("", f"- {TP} missing theory: keep the definitions as they are")
        mt6d = MT()
        say("MT-u6 / review C-F1: cure 1 is unchanged; a line that tries the canonical form (`missing theory:`) and "
            "names its result keeps the old hard FAIL (here: no `estimate:`), cured by a corrected canonical line "
            "after it; such a line naming no Lean name is a suspect",
            mt6["form"] == [] and mt6["problems"] == [] and "N.LS" in mt6["assume"]
            and mt6b["form"] == [] and len(mt6b["problems"]) == 1 and "not in the canonical form" in mt6b["problems"][0]
            and mt6c["problems"] == [] and len(mt6d["form"]) == 1 and mt6d["problems"] == [])
        # DESIGN-SW2 C7: under the canonical head, a body that does not read as a decision is a suspect (MT RULED); a
        # sloppy real decision (no searched:/estimate:) and a capital-M head with a decision body keep the hard FAIL
        w("", f"- {TP} missing theory: none needed for `N.thm`, the hypothesis is proved directly")
        c7a = MT()
        w("", f"- {TP} missing theory: assumed `N.LS` for `N.thm`")
        c7b = MT()
        w("", f"- {TP} Missing theory: assume `N.LS` for `N.thm` — {S}; {Q}")
        c7c = MT()
        w("", f"- {TP} missing theory: `N.LS` for `N.thm` — {S}")
        c7d = MT()
        say("SW2-C7: a canonical head over a non-decision body is a suspect for the adjudicator (no dead-end FAIL); "
            "'assumed `H` for `R`' and a capital-M head with a decision body stay hard (the latter says lower case)",
            len(c7a["form"]) == 1 and c7a["problems"] == []
            and len(c7b["problems"]) == 1 and c7b["form"] == []
            and len(c7c["problems"]) == 1 and "in lower case" in c7c["problems"][0] and c7c["form"] == []
            and len(c7d["problems"]) == 1 and "in lower case" not in c7d["problems"][0])
        # MT-u7: conflicts
        L7 = f"- {T} keep it, the missing theory being built (u7)"
        i7 = mt_line_id(L7)
        w("", L7)
        commit()
        rnd(f"- MT RULED {i7} | not a missing-theory decision: x", f"- MT RULED {i7} | a missing-theory decision for "
            f"`N.LS`: y", f"- MT RULED {i7} | not a missing-theory decision: z")
        u7a = (mt_ruling_history(cfg).get(i7) or [(None, None)])[-1][1] == "decision"
        rnd(f"- MT RULED {i7} | not a missing-theory decision: re-ruled")
        u7b = (mt_ruling_history(cfg).get(i7) or [(None, None, None)])[-1][1:3] == ("not", None) and MT()["problems"] == []
        say("MT-u7: a 'decision' and a 'not' ruling in one file: decision; a later round's 'not' overrides an earlier "
            "round's 'decision'", u7a and u7b)
        # review C-F2: the operator's dissent from a decision ruling
        L8 = f"- {T} keep the minors as defined — see the missing-theory decisions of Stage 2 (c-f2)"
        i8 = mt_line_id(L8)
        w("", L8)
        commit()
        DIS = f"- MT DISSENT {i8}: the line keeps a reading; it decides no library gap"
        w("", DIS, L8)
        commit()
        rnd(f"- MT RULED {i8} | a missing-theory decision for `N.LS`: z")
        f8a = MT()
        w("", DIS, L8, DIS.replace("it decides", "it decides, as before,"))
        commit()
        f8b = MT()
        fs8 = [f for f in missing_theory_findings(cfg) if i8 in f]
        tr8 = [t for t in trust_rows(cfg) if t[0] == "Missing theory"]
        pa8 = [t for _c, t in make_report.pending_adjudication(cfg) if i8 in t]
        rnd(f"- MT RULED {i8} | not a missing-theory decision: re-ruled after the dissent")
        f8c = MT()
        rnd(f"- MT RULED {i8} | a missing-theory decision for `N.LS`: z")
        f8d = MT()
        w("", DIS, L8, DIS.replace("it decides", "it decides, as before,"), DIS.replace("it decides", "it decides, again,"))
        commit()
        f8e = MT()
        say("review C-F2: `- MT DISSENT <id>: <why>` logged AFTER a decision ruling turns that one hard problem into a "
            "PENDING suspect quoting the ruling and the dissent (one logged before the ruling does nothing); a later "
            "'not' clears it; a second 'decision' ruling is final (hard) whatever the dissent",
            any(f"MT RULED {i8}" in p_ for p_ in f8a["problems"]) and f8b["problems"] == []
            and [x[0] for x in f8b["form"]] == [i8] and len(fs8) == 1 and fs8[0].code == "adj-record"
            and "the operator dissents" in fs8[0] and f8c["problems"] == [] and f8c["form"] == []
            and any(f"MT RULED {i8}" in p_ for p_ in f8d["problems"]) and f8d["form"] == []
            and any("A second decision ruling is final" in p_ for p_ in f8e["problems"] if f"MT RULED {i8}" in p_)
            and f8e["form"] == [])
        say("review N2: page 1 and the delivery note call a dissented line what it is -- ruled a missing-theory "
            "decision by an independent reviewer, disputed by the operator, not re-ruled -- never 'not judged'",
            len(tr8) == 1 and "ruled a missing-theory decision for `LS` by an independent reviewer" in tr8[0][1]
            and "disputed by the operator; not re-ruled" in tr8[0][1] and "not judged" not in tr8[0][1] + tr8[0][2]
            and len(pa8) == 1 and "disputed by the operator, not re-ruled" in pa8[0]
            and "not judged by an independent agent" not in pa8[0])
        L8b = f"- {T} keep it as it is, the missing theory aside (c-f2 alone)"
        w("", L8b, f"- MT DISSENT {mt_line_id(L8b)}: no ruling yet")
        commit()
        say("review C-F2: a dissent with no decision ruling clears and changes nothing (the line stays a suspect)",
            [x[0] for x in MT()["form"]] == [mt_line_id(L8b)] and MT()["problems"] == [])
        # safety F3: the cure of a decision ruling must fit the Lean
        L9 = f"- {T} take the graphon theorem as given (missing theory) (f3)"
        i9 = mt_line_id(L9)
        bh = f"- {TP} missing theory: build the graphon theory for `N.LS` — {S}; {E}"
        bt = f"- {TP} missing theory: build the graphon theory for `N.thm` — {S}; {E}"
        w("", L9, bh)
        commit()
        rnd(f"- MT RULED {i9} | a missing-theory decision for `N.LS`: it assumes LS")
        f9a = [p_ for p_ in MT()["problems"] if f"MT RULED {i9}" in p_]
        w("", L9, bt)
        L9b = L9.replace("(f3)", "(f3b)")
        i9b = mt_line_id(L9b)
        w("", L9b, bt)
        commit()
        rnd(f"- MT RULED {i9b} | a missing-theory decision for `N.thm`: it assumes LS for thm")
        f9b = [p_ for p_ in MT()["problems"] if f"MT RULED {i9b}" in p_]
        setdep(dict(dep, assumes={"thm": []}))
        f9c = [p_ for p_ in MT()["problems"] if f"MT RULED {i9b}" in p_]
        w("", L9, canon)
        setdep(dep)
        f9d = [p_ for p_ in MT()["problems"] if f"MT RULED {i9}" in p_]
        say("safety F3: a decision ruling for `N` is not cured by a `build` line when N is a hypothesis the Lean "
            "assumes, nor by `build … for <result>` while an unclassified hypothesis of it is left; with the binder "
            "gone the build line cures it, and the `assume` line cures the first",
            len(f9a) == 1 and "only a canonical `assume` line" in f9a[0] and len(f9b) == 1
            and "still an unclassified hypothesis" in f9b[0] and f9c == [] and f9d == [])
        # review N4: a decision ruling naming a declared definition (neither assumed nor a walk root) is cured by the
        # true `build` line for it (the definitions built), with no other missing-theory problem
        L4 = f"- {T} keep the definition of graphons built here (missing theory) (n4)"
        i4 = mt_line_id(L4)
        w("", L4)
        commit()
        rnd(f"- MT RULED {i4} | a missing-theory decision for `N.LS`: the definition LS was built")
        setdep(dict(dep, assumes={"thm": []}))
        n4a = [p_ for p_ in MT()["problems"] if f"MT RULED {i4}" in p_]
        w("", L4, f"- {TP} missing theory: build the definition of graphons for `N.LS` — {S}; {E}")
        n4b = MT()["problems"]
        setdep(dep)
        say("review N4: a decision ruling for a declared name that is neither assumed nor a walk root is cured by the "
            "true `build` line for it, with no other problem (no dead end)", len(n4a) == 1 and n4b == [])
        # MT-u8: D3 phrases go to the adjudicator, never a problem
        d3 = [f"- {T} keep hP, which isn't missing theory but an ordinary hypothesis",
              f"- {T} keep hP rather than missing theory",
              f"- {T} keep hP, unrelated to missing theory",
              f"- {T} keep hP: Mathlib has no version of it, so the hypothesis `hP` stays",
              f"- check:Lemma_2.5: {T} keep it — as in the decision to build the missing theory",
              "- missing theory (human 2026-11-15) keep it as the human said"]
        w("", *d3)
        mt8 = MT()
        say("MT-u8: D3 phrases (weak negations, 'Mathlib has no … hypothesis', a delegated Checkpoint C line, a loose "
            "human line) each give a suspect for the adjudicator, never a problem",
            mt8["problems"] == [] and len(mt8["form"]) == len(d3))
        # MT-u10: ruling problems of the round being committed only
        r10 = rnd("- MT RULED 0e0a | not a missing-theory decision: short id",
                  f"- MT RULED {i7} | a missing-theory decision for `N.Nope`: undeclared",
                  f"- MT RULED {i7} | a missing-theory decision for `LS`: declared (short)", do_commit=False)
        rp10 = mt_ruling_problems(cfg, rd, r10)
        say("MT-u10: a malformed MT RULED line and a decision ruling naming an undeclared name are adj-record "
            "findings of the round being committed only (None: none)",
            len(rp10) == 2 and all(f.code == "adj-record" for f in rp10) and any("N.Nope" in f for f in rp10)
            and any("is not an MT RULED ruling" in f for f in rp10) and mt_ruling_problems(cfg, rd, None) == []
            and mt_ruling_problems(cfg, rd, r1) == [])
        shutil.rmtree(os.path.join(rd, r10))
        # MT-m2, MT-p1, MT-i1: make_report wiring (adjudication_findings, the commit's list, the prompt)
        setdep(dict(dep, assumes={"thm": []}))
        Lm = f"- {T} keep the definitions, as in the decision to build the missing theory (m2)"
        lm_id = mt_line_id(Lm)
        w("", Lm)
        commit()
        rm = rnd("- a note", do_commit=False)
        af = make_report.adjudication_findings(cfg)
        af_r = make_report.adjudication_findings(cfg, rm)
        pa = make_report.pending_adjudication(cfg)
        import prompt
        proto = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "AUDIT_PROTOCOL.md"), encoding="utf-8").read()
        pcfg = dict(cfg, name="t", branch="b", base_commit="HEAD", source_pdf="s", source_id="i", source_cite="c",
                    build_cmds=[], calibration={})
        bodies = [prompt.render_adjudicator(proto, tmp, rm, pcfg, revotes=rv)[0] or "" for rv in (False, True)]
        # the round's real prompt is the rendered one (it lists the id)
        open(os.path.join(rd, rm, "prompts", "adjudicator.txt"), "w").write(bodies[0])

        def commit_adj(rv=False):
            try:
                return integrity.commit_adjudication(tmp, rd, "R", rm, revotes=rv, cfg=cfg)[0] and ""
            except ValueError as e_:
                return str(e_)
        i1a, i1r = commit_adj(), commit_adj(True)
        open(os.path.join(rd, rm, "ADOPTED.md"), "w").write(f"# A\n\n- a note\n- MT RULED {lm_id} | not a "
                                                            "missing-theory decision: keeps a reading\n")
        af_r2 = make_report.adjudication_findings(cfg, rm)
        i1b = commit_adj()
        last = git("log", "-1", "--format=%s").stdout.strip()
        say("MT-m2: adjudication_findings lists the suspect (so the adjudication commit refuses and the prompt lists "
            "it), and stops listing it once the round being committed rules it; --deliver's note says it was not "
            "judged by an independent agent (C4)",
            any(MT_SUSPECT_HEAD in f and f.code == "adj-record" for f in af)
            and any(MT_SUSPECT_HEAD in f for f in af_r) and not any(MT_SUSPECT_HEAD in f for f in af_r2)
            and any(c == "adj-record" and "not judged by an independent agent" in t for c, t in pa))
        say("MT-p1: the adjudicator prompt (with and without re-votes) lists the suspect in full with its MT RULED id, "
            "and step H says how to rule it",
            all(f"MT RULED {lm_id}" in " ".join(b.split()) and Lm in " ".join(b.split())
                and "Judge what the line decides, never the check's words" in " ".join(b.split()) for b in bodies))
        say("MT-i1: the adjudication commit refuses while the suspect is unruled (also `adjudicate R revotes`), "
            "listing it as Phase 0 shows it, and commits once the round's ADOPTED.md rules it; the ruling then counts",
            f"MT RULED {lm_id}" in i1a and "PENDING[adjudication] adj-record" in i1a and f"MT RULED {lm_id}" in i1r
            and i1b == "" and last == f"adjudicate {rm}" and MT()["form"] == [])
    finally:
        project.REPO, make_report.REPO = saved
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--selftest"]:
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(project.run_main(main))

#!/usr/bin/env python3
"""Content fingerprints of a project's declarations: what each one MEANS, hashed.

WHY THIS EXISTS.  Two gaps, one cause: verdicts and approvals were keyed by declaration NAME.
  * A `Pass` on a theorem survived a later change to a definition its statement is written in
    terms of. The theorem's name and text were unchanged; what it says was not.
  * Checkpoint B (RUN.md) freezes the statements the human approved, and the freeze was a rule
    in prose: nothing noticed if an approved statement, or a definition under it, changed.
A fingerprint keyed to content closes both, mechanically.

WHAT IS HASHED (fingerprint_tail.lean computes the per-declaration part, in Lean):
  own(n)  = theorem: its statement (type) -- never its proof
            def/opaque: type and value; inductive: type and constructor types; other: type
            (metadata erased; binder names are not part of Lean's expression hash)
  deps(n) = the project-local constants occurring in own(n). Mathlib is trusted, not followed.
  fp(n)   = sha256 of own(n) and of own(m) for every m in the transitive closure of deps(n).
So changing a definition changes the fingerprint of every statement written in terms of it,
directly or through other definitions; changing a proof changes nothing.

  fingerprint.py                       print {name: fp} for the checked-out project
  (scope.py writes each round's FINGERPRINTS.json; approval, which writes
  <ROUNDS-DIR>/APPROVED_FINGERPRINTS.json, is `signoff.py approve`, tied to the sheet shown)
  fingerprint.py --check               exit 1 if anything approved has changed or vanished;
                                       exit 4 if nothing has been approved yet; 2 on any error.
                                       A change to a declaration listed in the open re-approval
                                       (REAPPROVAL.json, `signoff.py reapprove --begin`) is a
                                       NOTE[reapproval], not a drift
  fingerprint.py --selftest            controls that must go red (and some that must stay green)

Requires a built project (Phase 0 builds first): the fingerprints are read from the compiled
environment, through `import <sweep.module>` or the append mode the axiom sweep uses.
"""
import argparse, hashlib, json, os, re, subprocess, sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402
# Run as a script this module is `__main__`, and the freeze check's `import signoff` (approved_text_problem) makes
# signoff's own `import fingerprint` load a SECOND copy of this file, whose _AUTO is empty: is_autogen() was then
# False for every declaration, an auto-generated matcher (`Fprev.match_1` of a definition by pattern matching)
# entered the rebuilt bundle and every Phase 0 reported a false DRIFT (live trial, stop S1, 2026-10-26). One module:
if __name__ == "__main__":
    sys.modules.setdefault("fingerprint", sys.modules[__name__])

TAIL = os.path.join(project.AUDITS, "fingerprint_tail.lean")
APPROVED = "APPROVED_FINGERPRINTS.json"
# The open re-approval (RULINGS A11): written only by `signoff.py reapprove --begin` (committed as
# "approve (reapproval begin: ...)"), closed by `signoff.py approve`. An owned record (integrity
# OWNERS); the freeze check trusts it only when open_reapproval() finds it committed by its owner.
REAPPROVAL = "REAPPROVAL.json"
REAPPROVAL_BEGIN = "approve (reapproval begin"
# Auto-generated companions (equation lemmas, recursors, noConfusion, congr lemmas, matchers) are
# fingerprinted -- they are part of a definition's closure -- but never listed as approvable items.
# WHICH declarations are auto-generated is decided in Lean (no source position = nobody wrote it),
# not guessed from the name: a name-pattern rule excluded a real theorem called `eq_zero_of_G`.
_AUTO = set()
# The project-local constants each declaration's own statement (or value) uses, from the last run: scope.py
# writes them into the round's FINGERPRINTS.json as `deps`, so a result's fingerprint closure (the
# Definition rows it is stated in terms of: result_status.py, F1) is read from the record, not recomputed.
_DEPS = {}


def is_autogen(name):
    """True iff the last fingerprint run reported `name` as auto-generated."""
    return name in _AUTO


def lean_source(cfg, body=None):
    return (project.lean_body(cfg) if body is None else body) + "\n" + project.lean_tail(cfg, TAIL)


def parse(out):
    """{key: (kind, own, [deps])}, or raise if the Lean side did not run to completion or two
    declarations produced the same key. Records which keys are auto-generated in _AUTO."""
    table, count, auto, dup = {}, None, set(), []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == "FP" and len(parts) == 6:
            if parts[1] in table:
                dup.append(parts[1])
            table[parts[1]] = (parts[2], parts[4], [d for d in parts[5].split(",") if d])
            if parts[3] == "auto":
                auto.add(parts[1])
        elif parts[0] == "FPCOUNT":
            count = int(parts[1])
    if dup:
        raise RuntimeError(f"two declarations share a fingerprint key: {sorted(set(dup))[:5]}")
    if count is None or count != len(table):
        raise RuntimeError("fingerprint run did not complete (no or mismatched FPCOUNT):\n" + out[-3000:])
    _AUTO.clear(); _AUTO.update(auto)
    _DEPS.clear(); _DEPS.update({k: sorted(set(v[2])) for k, v in table.items()})
    return table


def closure_fps(table):
    """{name: fp} -- own hash plus own hashes of the transitive project-local closure."""
    fps = {}
    for n in table:
        seen, stack = set(), [n]
        while stack:
            m = stack.pop()
            if m in seen or m not in table:
                continue
            seen.add(m)
            stack.extend(table[m][2])
        h = hashlib.sha256()
        for m in sorted(seen):
            h.update(f"{m}\t{table[m][0]}\t{table[m][1]}\n".encode())
        fps[n] = h.hexdigest()[:16]
    return fps


def compute(cfg, body=None):
    rc, out = project.run_lean(lean_source(cfg, body))
    if rc != 0:
        raise RuntimeError(f"lake env lean exited {rc}:\n" + out[-3000:])
    compute.table = parse(out)          # kept for approved_text_problem (signoff.build_bundle reads it)
    return closure_fps(compute.table)


compute.table = None


def freeze_check(cfg, rounds_dir, appr, fps, bundle=None):
    """`fingerprint.py --check` on the approval `appr` and the current fingerprints `fps`: prints the NOTE and
    DRIFT lines and the summary; 0, 1 (a drift, the approved statement text included, or a re-approval record
    to distrust) or 2 (the text could not be compared). `bundle`: the selftest's stand-in (approved_text_problem)."""
    bad = check(appr["fingerprints"], fps)
    reap, rprob = open_reapproval(rounds_dir, project.REPO)
    if rprob:
        print(f"FAIL[reapproval-record] {rprob}: it is ignored, so every change below is a drift")
    notes, drift = split_drift(appr["fingerprints"], bad, reap)
    for n, why_ in notes:
        print(f"NOTE[reapproval] {n}: {why_} -- listed in the re-approval begun at Lean "
              f"{reap['lean_head']}; `signoff.py approve` closes it")
    for n, why_ in drift:
        print(f"DRIFT[drift] {n}: {why_}")
    try:
        tp = approved_text_problem(cfg, rounds_dir, appr, reap, compute.table, bundle=bundle)
    except RuntimeError as e:
        print(f"FAIL: the approved statement text could not be compared: {e}", file=sys.stderr)
        return 2
    if tp:
        print(f"DRIFT[drift] {tp}")
        drift = drift + [("approved statement text", tp)]
    print(f"freeze check: {len(appr['fingerprints'])} approved at {appr.get('commit')}, "
          f"{len(drift)} drifted" + (f", {len(notes)} in the open re-approval" if notes else ""))
    return 1 if drift or rprob else 0


def approved_text_problem(cfg, rounds_dir, appr, reap, table=None, bundle=None):
    """A sentence when the statements bundle of the approval's round is no longer what a fresh build gives
    (signoff.bundle_problem), else None. The fingerprints ignore layout, so a statement whose source text
    changed (a lost space from a docstring edit, trial #7) passed every round's freeze check and was found
    only at delivery, 5 h later, by `signoff.py check`; the freeze check now runs the same comparison in
    every Phase 0. Not while a re-approval is open (its statements may change until `approve`), nor for an
    approval with no round (nothing to compare). `bundle`: the selftest's stand-in for signoff.build_bundle."""
    rn = appr.get("round")
    if reap or not rn:
        return None
    rd = os.path.join(rounds_dir, rn)
    if not os.path.isdir(rd):
        return f"the approval's round {rn} is missing, so the approved statement text cannot be compared"
    import signoff
    md = bundle(cfg) if bundle is not None else signoff.build_bundle(cfg, table)[0]
    bp = signoff.bundle_problem(rd, md)
    return (f"the approved statement text (round {rn}) changed: {bp.replace(' Start a new statement round.', '')} "
            f"Restore the approved text (or re-approve the change)") if bp else None


def head(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--short=11", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def check(approved, current):
    """[(name, problem)] for every approved item that changed or vanished."""
    bad = []
    for n, fp in sorted(approved.items()):
        cur = current.get(n)
        if cur is None:
            bad.append((n, "vanished (renamed or deleted)"))
        elif cur != fp:
            bad.append((n, "changed: its statement, or a definition it is stated in terms of"))
    return bad


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def open_reapproval(rounds_dir, lean_repo, cfg=None):
    """(record, problem) for the re-approval in progress (RULINGS A11).
    (None, None): there is none, or it is closed. (None, why): a record the freeze check must not
    trust, so every change stays a DRIFT. Trusted only when it is committed and unmodified, the last
    commit that touched it is a reapproval begin and every commit that touched it is an `approve`
    commit (its owner), it lists declarations with their begin-time fingerprints, and the Lean HEAD
    it recorded is in the Lean repository's history."""
    p = os.path.join(rounds_dir, REAPPROVAL)
    if not os.path.exists(p):
        return None, None
    try:
        doc = json.load(open(p))
    except (OSError, ValueError) as e:
        return None, f"{REAPPROVAL} is not readable JSON ({e})"
    if not isinstance(doc, dict):
        return None, f"{REAPPROVAL} is not a JSON object"
    if doc.get("closed"):
        return None, closed_problem(rounds_dir, doc, cfg)
    rc, top = _git(rounds_dir, "rev-parse", "--show-toplevel")
    if rc:
        return None, f"{REAPPROVAL} is not in a git repository"
    rel = os.path.relpath(os.path.realpath(p), os.path.realpath(top))
    if _git(top, "ls-files", "--error-unmatch", "--", rel)[0] or _git(top, "status", "--porcelain", "--", rel)[1]:
        return None, f"{REAPPROVAL} is not committed as it is (only `signoff.py reapprove --begin` writes it)"
    subjects = _git(top, "log", "--format=%s", "--", rel)[1].splitlines()
    if not subjects or not subjects[0].startswith(REAPPROVAL_BEGIN) \
            or not all(s.startswith("approve") for s in subjects):
        return None, (f"{REAPPROVAL} was committed by {subjects[:1]!r}, not by `signoff.py reapprove "
                      f"--begin` (\"{REAPPROVAL_BEGIN}: ...\")")
    decls, begin, lh = doc.get("decls"), doc.get("begin_fingerprints"), doc.get("lean_head")
    if not (isinstance(decls, list) and decls and isinstance(begin, dict)
            and all(isinstance(n, str) and isinstance(begin.get(n), str) for n in decls)):
        return None, f"{REAPPROVAL} does not list declarations with their begin-time fingerprints"
    if not isinstance(lh, str) or not lh or _git(lean_repo, "merge-base", "--is-ancestor", lh, "HEAD")[0]:
        return None, f"{REAPPROVAL}'s Lean HEAD {lh!r} is not in the Lean repository's history"
    return doc, None


# B2 review (byhuman) / re-check (c): the human's answer to a re-approval question, logged verbatim under
# RUN_LOG.md's "## Re-approvals" (or "## Answered") and committed AFTER the begin, BEFORE the close
HUMAN_ANSWER_RE = re.compile(r'^\s*[-*]\s+human answer \(round ([^;\s]+); ([^)]*)\):\s+"(.*\S.*)"\s*$')


def answer_lines(log, round_name, decls):
    """The lines of RUN_LOG.md text `log`, under "## Re-approvals" or "## Answered", recording the human's
    answer for `round_name` that name EVERY declaration of `decls` by its full name (re-check (c): a suffix
    such as `main` for `N.main` is not the declaration)."""
    out = set()
    for m in re.finditer(r"^## (?:Re-approvals|Answered)\b.*?$(.*?)(?=^## |\Z)", log or "", re.M | re.S):
        for ln in m.group(1).splitlines():
            mm = HUMAN_ANSWER_RE.match(ln)
            if not mm or mm.group(1) != round_name:
                continue
            named = {x.strip().strip("`") for x in mm.group(2).split(",")}
            if decls and all(d in named for d in decls):
                out.add(ln.strip())
    return out


def answered_after(top, h, begin_h, rel_log, round_name, decls):
    """Does RUN_LOG.md as committed in `h` hold a human-answer line (answer_lines) that the begin commit
    `begin_h` did not (re-check (c): an answer logged before the question was begun answers another one)?"""
    now = answer_lines(project.committed_blob(top, h, rel_log), round_name, decls)
    then = answer_lines(project.committed_blob(top, begin_h, rel_log), round_name, decls) if begin_h else set()
    return bool(now - then)


def _doc_at(top, h, rel):
    txt = project.committed_blob(top, h, rel) if h else None
    try:
        d = json.loads(txt) if txt is not None else None
    except ValueError:
        d = None
    return d if isinstance(d, dict) else None


def _cfg_for(rounds_dir, cfg=None):
    """The project config whose rounds dir is `rounds_dir` (for the level the approve gate reads); when
    none can be found, the strictest reading (statements-only: an agent never re-approves)."""
    if cfg:
        return cfg
    want = os.path.realpath(rounds_dir)
    same = lambda c: isinstance(c, dict) and c.get("rounds_dir") and \
        os.path.realpath(os.path.join(project.REPO, c["rounds_dir"])) == want
    try:
        c = project.select()[0]
        if same(c):
            return c
    except Exception:
        pass
    try:
        for c in project.all_projects().values():
            if same(c):
                return c
    except Exception:
        pass
    return {"rounds_dir": os.path.relpath(want, os.path.realpath(project.REPO)), "involvement": "statements-only"}


def _status(top, h, rel):
    return _git(top, "show", "--no-renames", "--name-status", "--format=", h, "--", rel)[1].split("\t", 1)[0]


def _blob_id(top, h, rel):
    rc, out = _git(top, "rev-parse", "-q", "--verify", f"{h}:{rel}")
    return None if rc else out


_WALK_CACHE = {}


def approval_walk(rounds_dir, cfg=None, upto=None):
    """(approvals, problems) -- B2 round 3, the ONE invariant of the approval records: every commit in the
    FULL history (git rev-list --full-history: merges included, never simplified away) that changes
    APPROVED_FINGERPRINTS.json must pass the approve gate as it applied at that commit (_gate_at); a merge
    commit whose records differ from its first parent's brought them from another branch. Each failure is a
    problem (make_report.record_problems: the report check fails on it), never silently skipped.
    `approvals`: [(commit, approval)] oldest first, the commits that passed, along the history of `upto`
    (HEAD): genuine_approvals, replaced_approval and reapprovals() all read this one walk."""
    top, rel_a = project.rounds_rel(rounds_dir, APPROVED)
    if top is None:
        return [], []
    rel_r = project.rounds_rel(rounds_dir, REAPPROVAL)[1]
    cfg = _cfg_for(rounds_dir, cfg)
    rc, tip = _git(top, "rev-parse", "-q", "--verify", f"{upto or 'HEAD'}^{{commit}}")
    if rc:
        return [], []
    key = (top, rel_a, tip, project.REPO, json.dumps(cfg, sort_keys=True, default=str))
    if key in _WALK_CACHE:
        a_, p_ = _WALK_CACHE[key]
        return list(a_), list(p_)
    out = _git(top, "rev-list", "--full-history", "--topo-order", "--reverse", "--parents", tip, "--",
               rel_a, rel_r)[1]
    state, problems, last = {}, [], ()
    for line in out.splitlines():
        h, *ps = line.split()
        base = state.get(ps[0], ()) if ps else ()
        real = _git(top, "rev-parse", f"{h}^@")[1].split()
        if len(real) > 1:
            if any(_blob_id(top, h, r) != _blob_id(top, real[0], r) for r in (rel_a, rel_r)):
                problems.append(f"merge commit {h[:11]} changes {APPROVED} or {REAPPROVAL} (brought from another "
                                f"branch): only `signoff.py approve` and `reapprove --begin` write them, on the "
                                f"run's own line; nothing it brought counts as approved")
        elif _status(top, h, rel_a):
            why = _gate_at(top, rounds_dir, h, base, state, cfg)
            if why:
                problems.append(f"{APPROVED} changed in commit {h[:11]} without passing the approve gate: {why}")
            else:
                base = base + ((h, _doc_at(top, h, rel_a)),)
        state[h] = last = base
    _WALK_CACHE[key] = (tuple(last), tuple(problems))
    return list(last), problems


def _gate_at(top, rounds_dir, h, prior, state, cfg):
    """None when commit `h` (writing APPROVED_FINGERPRINTS.json) passes `signoff.py approve`'s gate as it
    applied at `h` (the records as committed in its parent; `prior`: the approvals that passed before it on
    its line), else why not:
    - an "approve <R>" commit (not a begin) adding or modifying the file with a JSON object `by` human/agent;
    - a re-approval open at the parent (a record a begin wrote, not closed): `by: agent` needs
      project.agent_may_reapprove against the approval the begin replaced; `by: human` needs the human's
      answer line, naming the round and every listed declaration in full, in h's RUN_LOG.md and not in the
      begin's;
    - none open: only first approvals -- no declaration approved before with another fingerprint -- and
      `by: agent` over an earlier approval again needs agent_may_reapprove (B2 review "rmrecords")."""
    rel_a = project.rounds_rel(rounds_dir, APPROVED)[1]
    rel_r = project.rounds_rel(rounds_dir, REAPPROVAL)[1]
    subj = _git(top, "log", "-1", "--format=%s", h)[1]
    if not subj.startswith("approve ") or subj.startswith(REAPPROVAL_BEGIN):
        return f"commit {h[:11]} ({subj!r}) is not an \"approve <R>\" commit"
    if _status(top, h, rel_a) not in ("A", "M"):
        return f"commit {h[:11]} ({subj!r}) deletes or moves {APPROVED} instead of writing it"
    doc = _doc_at(top, h, rel_a)
    by = project.approval_by(doc, _git(top, "log", "-1", "--format=%cs", h)[1], rounds_dir=rounds_dir)[0]
    if by is None or not isinstance(doc.get("fingerprints", {}), dict):
        return f"{APPROVED} as committed in {h[:11]} is not an approval (a JSON object with `by` human or agent)"
    rec = _doc_at(top, f"{h}^", rel_r)
    w = _git(top, "log", "-1", "--format=%H", f"{h}^", "--", rel_r)[1] if rec is not None else ""
    if rec is not None and not rec.get("closed"):
        if not _git(top, "log", "-1", "--format=%s", w)[1].startswith(REAPPROVAL_BEGIN):
            return f"the open {REAPPROVAL} at its parent was not committed by `signoff.py reapprove --begin`"
        at_begin = state.get(w, prior)
        replaced = at_begin[-1][1] if at_begin else {}
        if by == "agent":
            ok_, why_ = project.agent_may_reapprove(cfg, replaced)
            return None if ok_ else f"the agent re-approves, which it may not: {why_}"
        decls = rec.get("decls") if isinstance(rec.get("decls"), list) else []
        rel_log = project.rounds_rel(rounds_dir, "RUN_LOG.md")[1]
        if not answered_after(top, h, w, rel_log, subj[len("approve "):], decls):
            return (f"the human re-approves, but its RUN_LOG.md has no human answer for round "
                    f"{subj[len('approve '):]} naming {', '.join(map(str, decls)) or '?'} logged after the begin")
        return None
    if rec is not None and (w not in {x for x, _ in prior}
                            or _git(top, "log", "-1", "--format=%s", w)[1] != rec.get("closed_by")):
        return (f"{REAPPROVAL} at its parent is marked closed by a commit that is not a genuine approve (the "
                f"re-approval is still open)")
    before = {}
    for _, a in prior:
        before.update(a.get("fingerprints") or {})
    changed = sorted(n for n, f in (doc.get("fingerprints") or {}).items() if n in before and before[n] != f)
    if changed:
        return (f"it re-approves {', '.join(changed)} (approved before with another fingerprint) with no "
                f"re-approval open (`signoff.py reapprove --begin` first)")
    if by == "agent" and prior:
        ok_, why_ = project.agent_may_reapprove(cfg, prior[-1][1])
        return None if ok_ else f"the agent approves over an earlier approval, which it may not: {why_}"
    return None


def approval_problems(rounds_dir, cfg=None):
    """approval_walk's problems: each commit that changed the approval records without the approve gate."""
    return approval_walk(rounds_dir, cfg)[1]


def genuine_approvals(rounds_dir, cfg=None, upto=None):
    """[(commit, approval)] oldest first: the approvals that passed the gate (approval_walk) on the history
    of `upto` (HEAD). A hand edit committed later (B2 re-check "amend") is not among them."""
    return approval_walk(rounds_dir, cfg, upto)[0]


def closed_problem(rounds_dir, doc, cfg=None):
    """None when the closed REAPPROVAL.json `doc` is committed unmodified by a genuine approve (approval_walk:
    a commit whose subject is its closed_by and which passed the gate); else why the close is not trusted
    (the re-approval then stays open: a FAIL[reapproval-record] for the freeze check, RED for the report)."""
    top, rel = project.rounds_rel(rounds_dir, REAPPROVAL)
    if top is None:
        return f"{REAPPROVAL} is not in a git repository"
    h = _git(top, "log", "-1", "--format=%H", "--", rel)[1]
    try:
        committed = json.loads(project.committed_blob(top, h, rel) or "null") if h else None
    except ValueError:
        committed = None
    if committed != doc or _git(top, "status", "--porcelain", "--", rel)[1]:
        return f"{REAPPROVAL} is marked closed but not committed as it is (only `signoff.py approve` closes it)"
    if not _closed_by_genuine(rounds_dir, top, h, doc, cfg):
        return (f"{REAPPROVAL} is marked closed by a commit that is not `signoff.py approve`'s own (an "
                f"\"approve <R>\" commit writing the new {APPROVED}, the approve gate holding): the "
                f"re-approval is still open")
    return None


def _closed_by_genuine(rounds_dir, top, h, rec, cfg):
    return bool(h) and _git(top, "log", "-1", "--format=%s", h)[1] == rec.get("closed_by") \
        and h in {x for x, _ in genuine_approvals(rounds_dir, cfg)}


def approval_history(rounds_dir, cfg=None):
    """(earlier, latest): whether an approval of this run passed the gate (approval_walk) and the newest one
    ({} when none). `approve --by agent` over an earlier approval is a re-approval whatever the records now
    say (B2 review "rmrecords": the walk keeps an approval moved aside, and flags the commit moving it)."""
    g = genuine_approvals(rounds_dir, cfg)
    return bool(g), (g[-1][1] if g else {})


def last_genuine_approval(rounds_dir, cfg=None, upto=None):
    """(commit, approval) of the newest genuine approval (in `upto`'s history), or (None, {})."""
    g = genuine_approvals(rounds_dir, cfg, upto)
    return g[-1] if g else (None, {})


def replaced_approval(rounds_dir, cfg=None):
    """The approval an open re-approval replaces: the newest genuine approval (approval_walk) in the history
    of the commit that last wrote REAPPROVAL.json -- a begin, which open_reapproval requires. Never a
    working-copy edit nor a hand edit committed over the approval (B2 review, re-check "amend"). {} when
    there is none (then nobody is recorded, and the human decides)."""
    top, rel = project.rounds_rel(rounds_dir, REAPPROVAL)
    if top is None:
        return {}
    h = _git(top, "log", "-1", "--format=%H", "--", rel)[1]
    return last_genuine_approval(rounds_dir, cfg, h)[1] if h else {}


def reapprovals(rounds_dir, cfg=None):
    """Every re-approval of the run, oldest first (the report discloses each, ROUND3 H1): the last
    state of each REAPPROVAL.json cycle (begin ... closing `approve`), read from the record's full git
    history, plus the working copy when it differs. A close counts only when the commit that wrote it is a
    genuine approve on HEAD's line (approval_walk), so every re-approval, the agent's or the human's, is
    either closed by the gate or listed OPEN. Each is the record itself: decls, begins ([{date, lean_head,
    decls, reason, involvement}]), closed, closed_by, closed_date."""
    p = os.path.join(rounds_dir, REAPPROVAL)
    versions = []      # (commit or None for the working copy, text)
    top, rel = project.rounds_rel(rounds_dir, REAPPROVAL)
    if top is not None:
        for h in _git(top, "rev-list", "--full-history", "--topo-order", "--reverse", "--no-merges", "HEAD",
                      "--", rel)[1].split():
            rc_, txt = _git(top, "show", f"{h}:{rel}")
            if not rc_:
                versions.append((h, txt))
    if os.path.exists(p):
        versions.append((None, open(p, encoding="utf-8").read()))
    cycles = []
    for h, txt in versions:
        try:
            v = json.loads(txt)
        except ValueError:
            v = {"decls": ["(unreadable REAPPROVAL.json)"], "closed": False}
        if not isinstance(v, dict):
            v = {"decls": ["(REAPPROVAL.json is not a JSON object)"], "closed": False}
        if v.get("closed"):
            ok_ = (_closed_by_genuine(rounds_dir, top, h, v, cfg) if h
                   else (closed_problem(rounds_dir, v, cfg) is None))
            if not ok_:
                v = dict(v, closed=False)
        if cycles and (v == cycles[-1] or not cycles[-1].get("closed")):
            cycles[-1] = v
        else:
            cycles.append(v)
    return cycles


def open_reapproval_problem(rounds_dir, cfg=None):
    """A sentence when a re-approval is open (begun, never closed by `signoff.py approve`), else
    None. The report check refuses while one is open (ROUND3 H1): the freeze check accepts changes
    to the listed declarations meanwhile, so nothing else proves they were approved."""
    cyc = reapprovals(rounds_dir, cfg)
    if not cyc or cyc[-1].get("closed"):
        return None
    c = cyc[-1]
    b = (c.get("begins") or [{}])[-1]
    return (f"a re-approval is OPEN ({REAPPROVAL}, begun {b.get('date', '?')} for "
            f"{', '.join(map(str, c.get('decls') or [])) or '?'}: {b.get('reason', '?')}): the listed "
            f"statements may have changed with nobody approving them; finish it (run/reapproval.md: "
            f"Stage 2 steps 2-7, then `signoff.py approve`, which closes it)")


def split_drift(approved, bad, reap):
    """([(name, why)] announced by the open re-approval, [(name, why)] real drift) (RULINGS A11).
    A change is announced only when its declaration is listed AND the fingerprint recorded at the
    begin equals the approved one: that proves the begin came before the edit (`reapprove --begin`
    refuses a listed declaration that has already changed)."""
    listed = set(reap["decls"]) if reap else set()
    begin = reap.get("begin_fingerprints", {}) if reap else {}
    notes, drift = [], []
    for n, why in bad:
        if n in listed and begin.get(n) is not None and begin.get(n) == approved.get(n):
            notes.append((n, why))
        else:
            drift.append((n, why))
    return notes, drift


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    if a.selftest:
        return selftest(cfg)
    try:
        fps = compute(cfg)
    except RuntimeError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    rounds_dir = os.path.join(project.REPO, cfg["rounds_dir"])
    items = {n: fp for n, fp in fps.items() if not is_autogen(n)}
    print(f"# project {cfg['name']} ({why}): {len(fps)} declarations fingerprinted, "
          f"{len(items)} approvable", file=sys.stderr)

    if a.check:
        p = os.path.join(rounds_dir, APPROVED)
        if not os.path.exists(p):
            print(f"NOTE[not-approved] no {APPROVED}: nothing has been approved yet, so nothing "
                  f"can be checked. (Expected before Checkpoint B; a failure after it.)",
                  file=sys.stderr)
            return 4
        appr = json.load(open(p))
        return freeze_check(cfg, rounds_dir, appr, fps)
    json.dump(fps, sys.stdout, indent=0)
    print()
    return 0


# ---------------------------------------------------------------------------------------------
BASE = """import Mathlib.Order.Basic
def helperK : ℕ := 3
namespace FpT
/-- doc -/
def thing (n : ℕ) : ℕ := n + 1
def other : ℕ := 3
def wrap (n : ℕ) : ℕ := thing n
theorem st (n : ℕ) : thing n > n := by simp [thing]
theorem via_wrap (n : ℕ) : wrap n > n := by simp [wrap, thing]
theorem pf (n : ℕ) : n < n + 1 := by have := thing n; omega
theorem un : other = 3 := rfl
private def hidden (n : ℕ) : ℕ := 2 * n
theorem uses_hidden (n : ℕ) : hidden n = n + n := by unfold hidden; omega
theorem eq_zero_of_x (x : ℕ) (h : x = 0) : x = 0 := h
theorem uses_helper : helperK ≤ 10 := by decide
def U.{u} (α : Sort u) : Sort u := α
inductive Col | red | blue
theorem md (n : ℕ) : thing n > n := by simp [thing]
def prev : ℕ → ℕ
  | 0 => 0
  | n + 1 => n
theorem uses_prev : prev 1 = 0 := rfl
end FpT
"""

# (label, transformation of BASE, {name: must_change(True)/must_not_change(False)})
VARIANTS = [
    ("identical source twice (determinism)", lambda s: s,
     {"FpT.thing": False, "FpT.st": False, "FpT.pf": False}),
    ("bound variable renamed in a statement", lambda s: s.replace(
        "theorem st (n : ℕ) : thing n > n", "theorem st (m : ℕ) : thing m > m"),
     {"FpT.st": False}),
    ("universe parameter renamed", lambda s: s.replace(
        "def U.{u} (α : Sort u) : Sort u := α", "def U.{w} (α : Sort w) : Sort w := α"),
     {"FpT.U": False}),
    ("mdata in a statement (no_index) is not meaning", lambda s: s.replace(
        "theorem md (n : ℕ) : thing n > n", "theorem md (n : ℕ) : no_index (thing n) > n"),
     {"FpT.md": False}),
    ("docstring edited", lambda s: s.replace("/-- doc -/", "/-- a different doc -/"),
     {"FpT.thing": False}),
    ("only a proof changed", lambda s: s.replace(
        "by have := thing n; omega", "by omega"), {"FpT.pf": False, "FpT.st": False}),
    ("definition body changed", lambda s: s.replace("n + 1\n", "n + 2\n", 1),
     {"FpT.thing": True, "FpT.st": True, "FpT.via_wrap": True, "FpT.wrap": True,
      "FpT.pf": False, "FpT.un": False, "FpT.other": False}),
    ("statement strictness changed (> to ≥)", lambda s: s.replace(
        "thing n > n := by simp [thing]\ntheorem via", "thing n ≥ n := by simp [thing]\ntheorem via"),
     {"FpT.st": True, "FpT.thing": False, "FpT.via_wrap": False}),
    ("private definition changed", lambda s: s.replace(
        "private def hidden (n : ℕ) : ℕ := 2 * n", "private def hidden (n : ℕ) : ℕ := n + n").replace(
        "by unfold hidden; omega", "by unfold hidden; rfl"),
     {"FpT.hidden": True, "FpT.uses_hidden": True, "FpT.st": False}),
    ("root-level helper OUTSIDE the namespace changed", lambda s: s.replace(
        "def helperK : ℕ := 3", "def helperK : ℕ := 5"),
     {"FpT.uses_helper": True, "FpT.st": False}),
    ("constructor added to an inductive", lambda s: s.replace(
        "inductive Col | red | blue", "inductive Col | red | blue | green"),
     {"FpT.Col": True, "FpT.st": False}),
    ("unrelated definition changed", lambda s: s.replace(
        "def other : ℕ := 3", "def other : ℕ := 4").replace("theorem un : other = 3 := rfl",
                                                         "theorem un : other = 4 := rfl"),
     {"FpT.st": False, "FpT.thing": False, "FpT.other": True, "FpT.un": True}),
]


def _key(table, short):
    """The table key for a declaration, private or not."""
    return next((k for k in table if k == short or k.startswith(short + " (private in ")), None)


def selftest(cfg):
    cfg = dict(cfg, namespace="FpT", sweep={"mode": "append", "file": "-"})
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    # the re-approval split (RULINGS A11); pure, so before the Lean fixture
    bad_ = [("A", "changed"), ("B", "changed"), ("C", "vanished")]
    appr_ = {"A": "1", "B": "2", "C": "3"}
    say("split_drift: with no re-approval every change is a drift", split_drift(appr_, bad_, None) == ([], bad_))
    n_, d_ = split_drift(appr_, bad_, {"decls": ["A", "C"], "begin_fingerprints": {"A": "1", "C": "9"}})
    say("split_drift: a listed change whose begin fingerprint is the approved one is announced", n_ == [bad_[0]])
    say("split_drift: unlisted, or begun after the change (begin fingerprint differs), stays a drift",
        d_ == [bad_[1], bad_[2]])
    # trial #7 audit: a layout-only change of an approved statement's text is caught by the freeze check
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        os.makedirs(os.path.join(td_, "R"))
        open(os.path.join(td_, "R", "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write("theorem t (m : N)\n")
        ap_ = {"round": "R"}
        same = approved_text_problem(cfg, td_, ap_, None, bundle=lambda c: "theorem t (m : N)\n")
        lost = approved_text_problem(cfg, td_, ap_, None, bundle=lambda c: "theorem t(m : N)\n")
        say("approved text: the approval round's bundle unchanged is no problem; a lost space is a drift, "
            "and names the line", same is None and lost and "approved statement text" in lost and "t(m" in lost)
        say("approved text: not compared while a re-approval is open, nor without an approval round; a missing "
            "round is a problem",
            approved_text_problem(cfg, td_, ap_, {"decls": ["t"]}, bundle=lambda c: "x\n") is None
            and approved_text_problem(cfg, td_, {}, None, bundle=lambda c: "x\n") is None
            and "missing" in (approved_text_problem(cfg, td_, {"round": "Q"}, None, bundle=lambda c: "x\n") or ""))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()) as o_:
            rc_same = freeze_check(cfg, td_, dict(ap_, fingerprints={"t": "1"}), {"t": "1"},
                                   bundle=lambda c: "theorem t (m : N)\n")
            rc_lost = freeze_check(cfg, td_, dict(ap_, fingerprints={"t": "1"}), {"t": "1"},
                                   bundle=lambda c: "theorem t(m : N)\n")
        say("approved text: the freeze check exits 0 on the approved text and 1 with DRIFT[drift] when only its "
            "layout changed (same fingerprints)",
            rc_same == 0 and rc_lost == 1 and "DRIFT[drift] the approved statement text" in o_.getvalue()
            and "1 drifted" in o_.getvalue())
    # stop S1 (2026-10-26): run as a script, the freeze check's bundle (signoff.build_bundle) must see the auto-
    # generated declarations this run's parse() found. A theorem stated with a definition by pattern matching
    # (its matcher `<def>.match_1` is auto-generated), and the round's stored bundle (built without it): no drift.
    import signoff
    say("one module: `import fingerprint` (as signoff does) is this module, also when run as a script",
        sys.modules.get("fingerprint") is sys.modules[__name__])

    def matcher_drift(tab, thm, matcher):
        """(approved_text_problem, defs of the rebuilt bundle) for a round whose stored bundle is the one built
        with `matcher` absent from the table (as `signoff.py bundle`, which filters it, wrote it)."""
        keep = (signoff.index_rows, signoff.signatures, signoff._raw_text)
        try:
            signoff.index_rows = lambda c: [("Theorem 1", f"`{thm}`")]
            signoff.signatures = lambda c, ns: {n: f"sig of {n}" for n in ns}
            signoff._raw_text = lambda q, c: f"theorem {q} : True := trivial" if q == thm else f"def {q} := 0"
            stored = signoff.build_bundle(cfg, {k: v for k, v in tab.items() if k != matcher})[0]
            with tempfile.TemporaryDirectory() as td:
                os.makedirs(os.path.join(td, "R"))
                open(os.path.join(td, "R", "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write(stored)
                return (approved_text_problem(cfg, td, {"round": "R"}, None, tab),
                        signoff.build_bundle(cfg, tab)[2])
        finally:
            signoff.index_rows, signoff.signatures, signoff._raw_text = keep

    keep_ = (set(_AUTO), dict(_DEPS))
    tp_, defs_ = matcher_drift(parse("FP\tP.t\ttheorem\tuser\t1\tP.f\nFP\tP.f\tdef\tuser\t2\tP.f.match_1\n"
                                     "FP\tP.f.match_1\tdef\tauto\t3\t\nFPCOUNT\t3\n"), "P.t", "P.f.match_1")
    _AUTO.clear(); _AUTO.update(keep_[0]); _DEPS.clear(); _DEPS.update(keep_[1])
    say("freeze check: an auto-generated matcher in a statement's closure is no drift of the approved statement "
        "text (stop S1: `## Fprev.match_1` entered the rebuilt bundle)", tp_ is None and defs_ == ["P.f"])
    try:
        base = compute(cfg, BASE)
    except RuntimeError as e:
        print(f"FAIL: base fixture did not run: {e}"); return 1
    base_auto = set(_AUTO)
    K = lambda t, n: t.get(_key(t, n))
    say("base fixture fingerprints every declaration",
        all(_key(base, n) for n in ("FpT.thing", "FpT.other", "FpT.wrap", "FpT.st", "FpT.via_wrap",
                                     "FpT.pf", "FpT.un", "FpT.hidden", "FpT.uses_hidden",
                                     "FpT.eq_zero_of_x", "FpT.uses_helper", "FpT.U", "FpT.Col")))
    say("a private declaration's key names it as private",
        _key(base, "FpT.hidden") and "(private in" in _key(base, "FpT.hidden"))
    say("a root-level declaration of the project is fingerprinted", "helperK" in base)
    say("equation lemmas are auto-generated (decided by Lean)",
        any(k.startswith("FpT.thing.eq") for k in base_auto))
    say("a user theorem NAMED eq_... is not auto-generated", "FpT.eq_zero_of_x" not in base_auto)
    say("recursor, casesOn, noConfusion, constructors, sizeOf_spec are auto-generated",
        {"FpT.Col.rec", "FpT.Col.casesOn", "FpT.Col.noConfusion", "FpT.Col.red",
         "FpT.Col.red.sizeOf_spec"} <= base_auto)
    say("user declarations are not auto-generated", "FpT.st" not in base_auto and "FpT.Col" not in base_auto)
    tp_, defs_ = matcher_drift(compute.table, _key(base, "FpT.uses_prev"), _key(base, "FpT.prev.match_1"))
    say("a definition by pattern matching: its matcher is auto-generated, in the theorem's closure, and the freeze "
        "check's rebuilt bundle leaves it out (stop S1)",
        "FpT.prev.match_1" in base_auto and "FpT.prev.match_1" in signoff.closure(["FpT.uses_prev"], compute.table)
        and tp_ is None and defs_ == ["FpT.prev"])
    say("the helpers of the fingerprint program itself are excluded",
        not any(k.startswith("auditFp") for k in base))
    for label, f, expect in VARIANTS:
        try:
            var = compute(cfg, f(BASE))
        except RuntimeError as e:
            say(f"{label}: variant compiles", False); print(e); continue
        for n, must_change in expect.items():
            changed = K(base, n) != K(var, n) or K(base, n) is None
            say(f"{label}: {n} {'changes' if must_change else 'unchanged'}",
                changed == must_change)
    # parse(): completeness and uniqueness
    try:
        parse("FP\ta\ttheorem\tuser\t1\t\nFPCOUNT\t2\n"); r1 = False
    except RuntimeError:
        r1 = True
    say("parse: a truncated run (FPCOUNT mismatch) is an error", r1)
    try:
        parse("FP\ta\ttheorem\tuser\t1\t\nFP\ta\tdef\tuser\t2\t\nFPCOUNT\t2\n"); r2 = False
    except RuntimeError as e:
        r2 = "share a fingerprint key" in str(e)   # the specific guard, not the count backstop
    say("parse: two declarations with one key is an error", r2)
    # the freeze check itself
    appr = {n: fp for n, fp in base.items() if n not in base_auto}
    say("check: identical state reports no drift", check(appr, base) == [])
    say("check: a vanished item is reported AS vanished",
        any(n == "FpT.st" and "vanished" in w
            for n, w in check(appr, {k: v for k, v in base.items() if k != "FpT.st"})))
    mutated = dict(base, **{"FpT.wrap": "0" * 16})
    say("check: a changed item is reported", [n for n, _ in check(appr, mutated)] == ["FpT.wrap"])
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

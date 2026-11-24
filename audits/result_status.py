#!/usr/bin/env python3
"""The status of each numbered result, as a mathematician reads it (U2 §1: F1, F7-F9; B9).

WHY THIS EXISTS.  The summary (SUMMARY.md, page 1) gives every result of the paper one line saying
what was established about it. Before B9 a result with no record against it read as if it were
fine; nothing checked that every review of it was positive and current. This module combines what
the other records say into the statuses of U2 §1, every one that applies, in this order:

   1. excluded at Checkpoint B             (the approval's row status)
   2. not formalized                       (SKIPPED.md)
   3. decision open                        (an unanswered QUESTION row; an open re-approval of its statement)
   4. stated only                          ('leave <decl> unproved' lines; a conjecture); "assumed, not proved"
                                           (its index row names a literature or missing-theory hypothesis: a cited
                                           result stated, never proved; with a defect: "assumed as a corrected
                                           hypothesis (not proved)")
   5. defect N: <status>; <repair> -- in plain words ("false as printed; proved as repaired"),
      with the Lean witness                (PAPER_DEFECTS.md, B3/B4)
   6. differs                              (a DEVIATIONS.md row of kind `differs`, F10)
   7. vacuous                              (VACUOUS.md, B7)
   8. not established: <reason>            (F1 below; F9)
   9. proved assuming `H`                  (a literature or missing-theory hypothesis WITH a valid
      hypothesis row, B5/B6; "(source not checked)" for `source unavailable`; "also proved
      unconditionally" when `<decl>_unconditional` exists and is reviewed, B7a)
  10. faithful under reading X (alternative Y)   (a DEVIATIONS.md row of kind `reading choice`, F8)
  11. faithful                             (only when every F1 condition holds and nothing above)

F1 -- a result is faithful only if (all from the records, never from the operator's words):
  * the latest correspondence, paper-faithfulness and non-vacuity verdicts on the result (its index
    row's Lean names; its label for paper-faithfulness) are Pass, each from a round whose fingerprint
    snapshot is at or after the last change of the result's fingerprint;
  * the same for correspondence and paper-faithfulness on every Definition row whose constants are in
    the fingerprint closure of the result (the closure scope.py records, `deps` of FINGERPRINTS.json;
    a round without it: every Definition row);
  * no Fail or Ambiguous among those latest verdicts is outstanding: a non-Pass verdict counts as
    answered only when the adjudicator REJECTed it, or decided it (ADOPT, or a QUESTION since
    answered) AND an adjudicator-owned record names the result (a PAPER_DEFECTS, VACUOUS or SKIPPED
    row, the approval's exclusion) -- or, for an Ambiguous, a reading-choice row, for a Fail a
    `differs` row (those rows are the operator's: they only ever add a status that claims less); an Ambiguous
    whose QUESTION a final answer settled by the reading the row says the Lean takes is answered too, and reads
    "faithful under reading (x) of the <lane> question ..." (reading_answer; a benchmark run);
  * the approved fingerprints of its declarations equal the newest audited ones (no drift);
  * every assumption the walk lists for it is classified and recorded (F7, F9);
  * no status 1-10 applies.
A NotDoneYet is not a verdict: the latest real verdict counts, if it is still fresh.

ROUTING of "not established" (U2 §1; `routes`): a missing or stale verdict -> `unverified`; an
outstanding Fail or Ambiguous with no decision row, or an unclassified/unrecorded assumption -> the adjudicator
(`adjudicator`, code `adj-record`: the next round's adjudicator decides it); one its round's adjudicator already
decided (ADOPT, DEFER, a QUESTION since answered; every item of the verdict, no re-vote open; a `## Hypotheses` row
saying `no`) -> `decided` (code `adj-record` too, but no round can clear it, so it never scopes one:
make_report.pending_adjudication; B1, MAINTAINING L5) -- except a finding the statement-round cap left open in a release run (scope.cap_record,
project.round_cap_route): "not established: open faithfulness finding: ..." -> `round-cap`, disclosed on the
summary's first page and never a delivery block (approver 2026-10-24); fingerprint drift -> `drift`; anything this module cannot map -> `status-unmapped`
(disclosed in release, a stop in dev). An open question is status 3 (the human; delivery waits).

INTERFACE (what B10's SUMMARY consumes): `result_status(cfg, row, inp=None)` -> [status], `row` an
index row [label, Lean cell] (make_report.table_rows of the index), `inp` any dict reused across rows
(the context is cached in it under CTX_KEY). The plain status is exactly FAITHFUL ("faithful"); every
other list names its reasons. `routes(cfg)` -> [Route]. `result_status.py [--project P] [--json]
[--check]` prints every result's status (and with --check exits 1 on any route but `question`).

  result_status.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import collections, contextlib, glob, io, json, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

FAITHFUL = "faithful"
CTX_KEY = "result_status"
F1_LANES = ("correspondence", "paper-faithfulness", "non-vacuity")
DEF_LANES = ("correspondence", "paper-faithfulness")      # on the Definition rows of the closure
DEF_KIND = re.compile(r"(?i)^\s*(definition|notation|construction)\b")
OPEN_KIND = re.compile(r"(?i)^\s*(conjecture|open problem|question)\b")
_LEAN = re.compile(r"^[A-Za-z_][\w'.!?₀-₉ₐ-ₜ]*$")
UNMAPPED_CODE = "status-unmapped"
# plain words for a defect row (B3's status/repair vocabulary): what the paper's statement is, and what
# the Lean does about it
STATUS_WORDS = {"false": "false as printed", "vacuous": "vacuous as printed",
                "unsupported": "the paper's argument does not establish it",
                "misprint": "a misprint; true as intended"}
REPAIRED = ("typo", "add hypothesis", "local", "substantial")
Route = collections.namedtuple("Route", "result reason route code")


# --- reading the records once (the context) --------------------------------------------------------------
def _quiet(f, *a, **k):
    """audit_coverage prints its warnings (CONFLICT, BARE PASS) to stderr: the statuses carry them."""
    with contextlib.redirect_stderr(io.StringIO()):
        return f(*a, **k)


def _json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def norm_label(label):
    """"Lemma 5.4 (c)" and "lemma 5.4(c)" -> "lemma 5.4(c)": the key a result row and a lane item share."""
    t = " ".join(str(label).replace("*", "").replace("`", "").split()).lower()
    return re.sub(r"\s+\(", "(", t).strip(" .:")


def label_core(key):
    """"lemma 5.4(c)" -> "lemma 5.4" (the kind and number)."""
    m = re.match(rf"((?:{project.RESULT_KINDS_RE.lower()}|open problem|question)\s+\d+(?:\.\d+)*)", key)
    return m.group(1) if m else key


def row_names(cell, ns, known=()):
    """The Lean names of an index row's Lean cell, fully qualified when the namespace makes them known."""
    out = []
    for t in re.findall(r"`([^`]+)`", str(cell)):
        n = t.split("(")[0].strip()
        if not _LEAN.match(n):
            continue
        if ns and not n.startswith(ns + ".") and (f"{ns}.{n}" in known or n not in known):
            n = f"{ns}.{n}"
        if n not in out:
            out.append(n)
    return out


def item_decl(item, ns, known=()):
    """A correspondence/non-vacuity lane item as a Lean name: `File.lean:12 thm`, `` `thm` (proof only) ``,
    `Ns.thm` -> `Ns.thm` (the namespace added when that names a known declaration, or the bare name none)."""
    t = re.sub(r"\s*\([^()]*\)\s*$", "", str(item).strip()).strip().strip("`").strip()
    t = t.split()[-1].strip("`") if t.split() else t
    if not ns or t.startswith(ns + ".") or t in known:
        return t
    return f"{ns}.{t}" if f"{ns}.{t}" in known or not known else t


def _rows_of(path, keycol):
    import make_report
    return make_report.record_table(path, keycol)


def _col(head, row, name):
    i = next((k for k, h in enumerate(head or []) if str(h).lower().startswith(name)), None)
    return row[i] if i is not None and i < len(row) else ""


def mentions(text, label, names):
    """Does a record's cell name this result: one of its Lean names (in full, or its last component in a
    code span or as a word of 4+ characters), or its label -- part-aware: the row "Lemma 5.4 (a)" is not
    named by "Lemma 5.4 (c)"; the row "Lemma 5.4" is named by "Lemma 5.4(c)" (it holds every part)."""
    t = " ".join(str(text).split())
    for n in names:
        last = n.rsplit(".", 1)[-1]
        if re.search(r"(?<![\w.'])" + re.escape(n) + r"(?![\w'])", t):
            return True
        if re.search(r"`(?:[\w']+\.)*" + re.escape(last) + r"(?![\w'])[^`]*`", t) or (
                len(last) >= 4 and re.search(r"(?<![\w.'])(?:[\w']+\.)*" + re.escape(last) + r"(?![\w'])", t)):
            return True
    key = norm_label(label)
    core = label_core(key)
    if not core:
        return False
    part = key[len(core):].strip()
    low = norm_label(t)
    for m in re.finditer(re.escape(core) + r"(?![\d]|\.\d)", low):
        if not part:
            return True
        after = low[m.end():].lstrip()
        if after.startswith(part) or after.startswith(part.strip("()") + ")"):
            return True
        # "Lemma 5.4 (b) and (c)": a list of parts after the number
        if re.match(r"(?:\([a-z0-9ivx]+\)\s*(?:,|and|&)?\s*)*" + re.escape(part), after):
            return True
    return False


def primary_subject(text, kind):
    """The part of a record's subject cell that names the result the row is ABOUT (next batch B6, AUDIT-P4 D1: a
    VACUOUS row on a helper that names the goal as context gave the goal "true only vacuously"; a SKIPPED row on
    Remark 5.2 that mentions "condition (ii) of Theorem C" gave Theorem C "not formalized"). `kind` "vacuous": the
    first backticked Lean name (AUDIT_PROTOCOL's VACUOUS template puts it first); "skipped": whichever comes first,
    a result label or a backticked name. The whole cell when it holds neither (as before). Only the status reads
    this; the same test decides whether the row is one of the result's records (rec_ok; fix round 1, attack 1)."""
    t = " ".join(str(text).split())
    code = re.search(r"`[^`]+`", t)
    if kind == "vacuous":
        return code.group(0) if code else t
    # a label is a kind word and a number-like token ("Remark 5.2", "Theorem C"), never "remark on" (gate 3a: P4)
    lab = re.search(rf"\b(?i:{project.RESULT_KINDS_RE})\s+(?:[A-Z]?\d[\w.]*\w|[A-Z]?\d|[A-Z](?![\w]))"
                    rf"(?:\s*\([a-z0-9ivx]+\))?", t)
    first = min((m for m in (code, lab) if m), key=lambda m: m.start(), default=None)
    return first.group(0) if first else t


def _snapshots(rd):
    """[(round name, {decl: fp}, deps or None)] oldest first, over the rounds that are not set aside."""
    dirs = [os.path.dirname(f) for f in glob.glob(os.path.join(rd, "*", "FINGERPRINTS.json"))
            if not project.is_abandoned(os.path.dirname(f))]
    out = []
    for d in project.order_rounds(dirs, project.REPO) if dirs else []:
        j = _json(os.path.join(d, "FINGERPRINTS.json"))
        if isinstance(j, dict) and isinstance(j.get("fingerprints"), dict):
            deps = j.get("deps") if isinstance(j.get("deps"), dict) else None
            out.append((os.path.basename(d), j["fingerprints"], deps))
    return out


def _history(rd, ns, known=()):
    """{(lane, key): [(round, verdict, raw item)]} oldest first, keys: a Lean name for the decl lanes, a
    normalized label for paper-faithfulness. NotDoneYet entries are dropped (not a verdict)."""
    import audit_coverage as ac
    lanes = [l for l in F1_LANES]
    rounds = _quiet(ac.load_rounds, rd, lanes)
    out = collections.defaultdict(list)
    for rnd, lane, verdicts in rounds:
        for item, v in verdicts.items():
            if v == "NotDoneYet":
                continue
            key = norm_label(item) if lane == "paper-faithfulness" else item_decl(item, ns, known)
            out[(lane, key)].append((rnd, v, item))
    return out


def _decisions(rd):
    """{round: {"<lane> :: <norm item>": decision}} (audit_coverage.read_adopted: THE reader)."""
    import audit_coverage as ac
    out = {}
    for p in glob.glob(os.path.join(rd, "*", "ADOPTED.md")):
        try:
            out[os.path.basename(os.path.dirname(p))] = _quiet(ac.read_adopted, p)
        except Exception:          # noqa: BLE001 -- an unreadable record decides nothing
            out[os.path.basename(os.path.dirname(p))] = {}
    return out


def _capped(rd):
    """{"<lane> :: <norm item>": round} of every faithfulness finding a statement-round cap left open (scope.py
    cap_record: <rounds dir>/round-caps/<round>.json, release, project.round_cap_route "judge")."""
    out = {}
    for p in sorted(glob.glob(os.path.join(rd, "round-caps", "*.json"))):
        d = _json(p)
        for k in (d or {}).get("open") or [] if isinstance(d, dict) else []:
            out[str(k)] = str(d.get("round") or os.path.basename(p)[:-len(".json")])
    return out


def context(cfg, live_fps=None):
    """Everything the statuses read, once. `live_fps`: fingerprints of HEAD (fingerprint.compute), else
    the newest round's snapshot stands for the current version."""
    import make_report, decisions, hypotheses
    rd = os.path.join(project.REPO, cfg["rounds_dir"])
    ns = str(cfg.get("namespace") or "")
    c = {"rd": rd, "ns": ns, "problems": []}
    c["snaps"] = _snapshots(rd)
    c["cur"] = dict(live_fps) if live_fps is not None else (dict(c["snaps"][-1][1]) if c["snaps"] else None)
    c["deps"] = next((s[2] for s in reversed(c["snaps"]) if s[2] is not None), None)
    # the newest snapshot's deps only: an older one may miss a constant added since
    if c["snaps"] and c["snaps"][-1][2] is None:
        c["deps"] = None
    known = set(c["cur"] or {})
    # E2E-FIX2 M1: the index's result rows as the freeze reads them, whatever their label word
    c["index"] = make_report.index_cells(os.path.join(project.REPO, project.index_file(cfg) or ""))
    c["known"] = known
    # every Definition, Notation or Construction row of the index (a Notation row is no numbered result)
    try:
        import signoff
        allrows = signoff.index_rows(cfg)
    except Exception:          # noqa: BLE001 -- the numbered rows, at least
        allrows = [(r[0], r[1] if len(r) > 1 else "") for r in c["index"]]
    c["defrows"] = [(" ".join(lab.split()), row_names(rest, ns, known)) for lab, rest in allrows if DEF_KIND.match(lab)]
    # C2-FIX 5b: a check of the proof-validity core that could not run (stops.py close --core-fault): every result
    # gets the plain status of the guarantee it gives (proof complete, standard axioms, statement as approved); a
    # provenance check gives none: the proofs and statements were checked; that the reviewers' records behind
    # "faithful" were not verified at delivery is said on page 1 and in the legend (make_report.RECORD_LEGEND)
    try:
        import stops
        c["core"] = list(dict.fromkeys(st for st in (stops.core_fault_status(x) for x in stops.core_fault_rows(cfg, rd))
                                       if st))
    except Exception:       # noqa: BLE001 -- fail closed: nothing is verified
        c["core"] = ["not verified (details for maintainers in RUN_RECORD.md)"]
    c["hist"] = _history(rd, ns, known)
    c["dec"] = _decisions(rd)
    c["capped"] = _capped(rd)
    # the QUESTION rows and RUN_LOG.md: an answered question that keeps the reading the Lean takes (reading_answer);
    # A5: both cells of each row (a row may write everything in its decision cell), never decisions.question_rows'
    # value (review M6: that feeds DECISIONS.md)
    try:
        c["qrows"] = question_texts(project.rounds(cfg))
    except Exception:          # noqa: BLE001 -- no question is then read as settled
        c["qrows"] = {}
    try:
        c["log"] = open(os.path.join(rd, "RUN_LOG.md"), encoding="utf-8").read()
    except OSError:
        c["log"] = ""
    c["approval"] = _json(os.path.join(rd, "APPROVED_FINGERPRINTS.json")) or {}
    try:
        import fingerprint
        rec, _why = fingerprint.open_reapproval(rd, project.REPO, cfg)
        c["reapproving"] = set((rec or {}).get("decls") or [])
    except Exception:          # noqa: BLE001
        c["reapproving"] = set()
    c["skipped"] = _rows_of(os.path.join(rd, "SKIPPED.md"), "what")
    c["deviations"] = _rows_of(os.path.join(rd, "DEVIATIONS.md"), "kind")
    c["vacuous"] = _rows_of(os.path.join(rd, "VACUOUS.md"), "statement")
    h, rows, _p, old = make_report.defects_table(os.path.join(rd, "PAPER_DEFECTS.md"))
    c["defects"] = ([x.lower() for x in h], rows, old)
    try:
        c["unproved"] = dict(decisions.unproved(cfg)["decls"])
    except Exception as e:     # noqa: BLE001 -- said, never dropped
        c["unproved"] = {}
        c["problems"].append(f"the 'leave unproved' lines could not be read ({e})")
    c["problems_q"] = False
    try:
        c["questions"] = make_report.open_questions(cfg)
    except Exception as e:     # noqa: BLE001
        c["questions"] = []
        c["problems"].append(f"the open questions could not be read ({e})")
        c["problems_q"] = True      # B1: no QUESTION is then read as answered, so none as decided
    # B1 (review M2): a REVOTE NEEDED row no later row of its round decides is no decision, whatever another row of
    # the same base lane and item says (read_adopted keys by base lane and skips REVOTE NEEDED rows)
    try:
        import audit_coverage as ac, lanecheck
        c["revotes"] = {(r, f"{lanecheck.lane_base(l)} :: {ac.norm_item(i)}")
                        for r, l, i, _w, _a in decisions.open_revotes(project.rounds(cfg))}
    except Exception:          # noqa: BLE001 -- fail towards the round: nothing reads as decided
        c["revotes"] = None
    doc, why = hypotheses.walk(cfg, rd)
    c["walk"], c["walk_why"] = doc, why
    c["assumed"] = hypotheses.assumed(doc) if doc else {}
    try:
        c["hyp_rows"] = hypotheses.latest(cfg, rd) if doc else {}
        c["mt"] = set(hypotheses.missing_theory(cfg, doc={}, rd=rd)["assume"])
    except Exception as e:     # noqa: BLE001
        c["hyp_rows"], c["mt"] = {}, set()
        c["problems"].append(f"the hypothesis records could not be read ({e})")
    return c


def ctx_of(cfg, inp=None):
    if isinstance(inp, dict):
        if CTX_KEY not in inp:
            inp[CTX_KEY] = context(cfg)
        return inp[CTX_KEY]
    return context(cfg)


# --- F1: verdicts, freshness, closure --------------------------------------------------------------------
def changed_at(c, decl):
    """Index into c["snaps"] of the first snapshot of the decl's current run of equal fingerprints (its last
    change), or None when the current version is unknown."""
    cur = (c["cur"] or {}).get(decl)
    if cur is None:
        return None
    k = len(c["snaps"])
    while k > 0 and c["snaps"][k - 1][1].get(decl) == cur:
        k -= 1
    return k


def _round_index(c, rnd):
    return next((i for i, s in enumerate(c["snaps"]) if s[0] == rnd), None)


def latest(c, lane, keys):
    """(round, worst verdict of that round, [raw items]) of the newest round with a verdict on any of `keys`,
    or None."""
    ent = [e for k in keys for e in c["hist"].get((lane, k), [])]
    if not ent:
        return None
    order = {s[0]: i for i, s in enumerate(c["snaps"])}
    # the history is in round order per key; across keys order by snapshot position (else by the history)
    rounds = []
    for k in keys:
        for e in c["hist"].get((lane, k), []):
            if e[0] not in rounds:
                rounds.append(e[0])
    newest = max(rounds, key=lambda r: (order.get(r, -1), rounds.index(r)))
    sev = ["Pass", "Ambiguous", "Fail"]
    vs = [e for e in ent if e[0] == newest]
    worst = max((e[1] for e in vs), key=lambda v: sev.index(v) if v in sev else 3)
    return newest, worst, [e[2] for e in vs if e[1] == worst]


def fresh(c, rnd, decls):
    """None if a verdict of round `rnd` is about the current version of every decl in `decls`, else why not."""
    if not c["snaps"]:
        return "no round recorded fingerprints (FINGERPRINTS.json)"
    i = _round_index(c, rnd)
    if i is None:
        return f"round {rnd} recorded no fingerprints"
    for d in decls:
        k = changed_at(c, d)
        if k is None:
            if (c["cur"] or {}) and d not in c["cur"]:
                continue        # not a declaration of the project (a library name cited in the index)
            return f"`{d}` has no current fingerprint"
        if i < k:
            return f"`{d}` changed after round {rnd}"
    return None


def decision(c, rnd, lane, item):
    import audit_coverage as ac
    return (c["dec"].get(rnd) or {}).get(f"{lane} :: {ac.norm_item(item)}")


def closure_defs(c, decls):
    """The Definition rows ([(label, names)]) whose constants are in the fingerprint closure of `decls`;
    every Definition row when the newest round recorded no closure."""
    if c["deps"] is None:
        return list(c["defrows"]), False
    seen, stack = set(), list(decls)
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(c["deps"].get(m) or [])
    return [(l, ns_) for l, ns_ in c["defrows"] if set(ns_) & seen], True


def _answered(c, label, names):
    return not any(mentions(item, label, names) for _r, _l, item, _why, _n in c["questions"])


DECIDED = ("ADOPT", "DEFER", "QUESTION")


def _nonpass_items(c, rnd, lane, keys):
    """The raw items of every non-Pass verdict of round `rnd` on any of `keys` (review MEDIUM-3: latest() returns only
    the worst verdict's items; an Ambiguous on (b) beside a Fail on (a) must be decided too)."""
    out = []
    for k in keys:
        for e in c["hist"].get((lane, k), []):
            if e[0] == rnd and e[1] != "Pass" and e[2] not in out:
                out.append(e[2])
    return out


def _part_decided(c, rnd, lane, item):
    """Review MEDIUM-3: decision() compares items by audit_coverage.norm_item, which drops a part ("Lemma 1.2 (a)" and
    "(b)" are one key), so a row on (a) would decide (b). A paper-faithfulness item with a part is decided only by a
    row of round `rnd` naming that part or the label without a part. Unreadable rows: not decided."""
    if lane != "paper-faithfulness" or "rd" not in c:
        return True
    k = norm_label(item)
    core = label_core(k)
    if k == core:
        return True
    cache = c.setdefault("_pf_rows", {})
    if rnd not in cache:
        import lanecheck
        try:
            # every row, as read_adopted (decision()'s reader) reads them; only the part is added here
            cache[rnd] = {norm_label(r.item) for r in lanecheck.decision_rows(os.path.join(c["rd"], rnd))
                          if r.base == "paper-faithfulness" and r.decision}
        except Exception:       # noqa: BLE001 -- fails towards `adjudicator` (a round)
            cache[rnd] = set()
    return k in cache[rnd] or core in cache[rnd]


def _route(c, rnd, lane, items, label, names, dec, keys=()):
    """B1 (MAINTAINING L5): the route of a non-Pass verdict of round `rnd` that no record settles. `question` while
    its QUESTION is unanswered (the human's; `dec` is the first item's decision, as the status text names it);
    `decided` when round `rnd`'s adjudicator decided EVERY item of it (ADOPT, DEFER, or a QUESTION since answered)
    and no re-vote of it is open: no round can clear it, and its status still says what holds ("not established:
    ... decision: X"), so it never scopes a round (make_report.pending_adjudication); else `adjudicator` (a verdict
    with no decision row: the next adjudicator decides it). Fails towards `adjudicator` (a round). `keys`: the verdict's
    keys; every non-Pass verdict of round `rnd` on them must be decided, not only the worst one's items (review
    MEDIUM-3)."""
    if dec == "QUESTION" and not _answered(c, label, names):
        return "question"
    import audit_coverage as ac
    items = list(dict.fromkeys(list(items) + _nonpass_items(c, rnd, lane, keys)))
    if not items or c.get("revotes") is None:
        return "adjudicator"
    for i in items:
        d = decision(c, rnd, lane, i)
        if d not in DECIDED or (rnd, f"{lane} :: {ac.norm_item(i)}") in c["revotes"]:
            return "adjudicator"
        if not _part_decided(c, rnd, lane, i):
            return "adjudicator"
        if d == "QUESTION" and (c.get("problems_q") or not _answered(c, label, names)):
            return "adjudicator"
    return "decided"


def question_texts(rounds):
    """{item: [(round name, lane, text)]} for every QUESTION row of any round's ADOPTED.md (THE reader,
    lanecheck.decision_rows), `text` the decision cell and the reason cell, `**` removed (A5)."""
    import lanecheck
    out = {}
    for d in rounds:
        for r in lanecheck.decision_rows(d):
            if r.decision.startswith("QUESTION"):
                # one cell per line: a bare label ending the decision cell still ends its clause (LBL_T's `$`)
                t = (str(r.text or "") + "\n" + str(r.reason or "")).replace("**", "")
                out.setdefault(r.item, []).append((os.path.basename(d), r.lane, t))
    return out


# A5: which reading of an Ambiguous the QUESTION row says the Lean takes, and which one the answer took.
# The prescribed token (AUDIT_PROTOCOL C): the row ends with `[Lean: (a); recommended: (b)]` -- read in either cell,
# any case, `;` or `,`, the labels with or without parentheses; when a row has one, only it is read.
_LAB = r"[A-Za-z]|[ivxIVX]+|\d+"
TOKEN = re.compile(r"(?i)\[\s*lean\s*:\s*\(?(" + _LAB + r")\)?\s*[;,]\s*recommended\s*:\s*\(?(" + _LAB + r")\)?\s*\]")
# The legacy wordings (records written before the token). A label is `(a)`, `(A)`, `(ii)`, `(1)`, or a bare capital
# or number; never a word ("takes a stronger ...") nor a section number ("reading A.5"). After "takes" without the
# word "reading" a bare label must end its clause (review H2: "takes A arbitrary", "takes 2 ≤ d", "takes K as a
# parameter" name objects, not readings).
LBL_R = r"(?:\((" + _LAB + r")\)|([A-Z]|\d+)(?!\w|\.\d))"
LBL_T = r"(?:\((" + _LAB + r")\)|([A-Z]|\d+)(?!\w|\.\d)(?=\s*(?:[.,;:)]|\(|$)))"
_LEAN_SUBJ = (r"(?<![\w-])(?:[Tt]he\s+)?Lean(?:'s)?(?:\s+(?:statement|type|declaration|definition|version))?"
              r"(?:\s*`[^`\n]*`)?(?:\s*\((?:[^()\n]|\([^()\n]*\))*\))?\s+takes\s+")
LEAN_TAKES = re.compile(_LEAN_SUBJ + r"(?:(?:[Rr]eading\s+)" + LBL_R + r"|" + LBL_T + r")", re.M)
READING = re.compile(r"(?<![\w-])[Rr]eading\s+" + LBL_R)
LEANS_READING = re.compile(r"(?i)\b(?:keep|keeps|kept|take)\s+the lean'?s reading\b(?!s)")
# Review HIGH-1, L2: a label in a negated or interrogative clause names no reading -- "do not keep the Lean's
# reading", "Keep the Lean's reading? No: ...", "not reading (a)", "Neither the paper nor the Lean takes (a)". A clause
# ends at ; ! ? [ ] a newline, a full stop or colon before a space, or a dash between spaces; code spans are not read.
# Fails towards "no reading named" (the status then reads "not established").
NEG = re.compile(r"(?i)\b(?:not|never|no|neither|nor|instead|rather\s+than|reject(?:s|ed)?|refuse[sd]?)\b|n['\u2019]t\b")
_CLAUSE_END = re.compile(r"[;!?\[\]\n]|[.:](?=\s|$)|\s(?:\u2014|\u2013|--)\s")


def _negated(text, m):
    """Is match `m` of `text` in a negated or interrogative clause (NEG, _CLAUSE_END)?"""
    t = re.sub(r"`[^`\n]*`", lambda x: " " * len(x.group(0)), str(text))
    start = max((e.end() for e in _CLAUSE_END.finditer(t, 0, m.start())), default=0)
    end_m = _CLAUSE_END.search(t, m.end())
    end = end_m.start() if end_m else len(t)
    return bool(NEG.search(t, start, end)) or bool(end_m and end_m.group(0) == "?")


def _labels(rx, text, guard=True):
    """The labels `rx` reads in `text`; `guard`: none from a negated or interrogative clause (_negated)."""
    t = str(text)
    return {next(g for g in m.groups() if g).lower() for m in rx.finditer(t) if not (guard and _negated(t, m))}


def _lean_takes(text):
    """The legacy reading of which label the Lean takes. A bare label after "takes" (no "reading" before it) counts
    only when the row names it as a reading ("Reading A: ..."; review L1: "takes 1, i.e.", "takes C," name objects)."""
    t = str(text).replace("**", "")
    named = _labels(READING, t, guard=False)
    out = set()
    for m in LEAN_TAKES.finditer(t):
        if _negated(t, m):
            continue
        lab = next(g for g in m.groups() if g).lower()
        if m.group(4) and lab not in named:
            continue
        out.add(lab)
    return out


def _tokens(text):
    return {(m.group(1).lower(), m.group(2).lower()) for m in TOKEN.finditer(str(text))}


def token_conflict(text):
    """Review MEDIUM-1: the row's token names one Lean label and its prose (the legacy wordings) another."""
    toks = _tokens(text)
    if len(toks) != 1:
        return False
    legacy = _lean_takes(text)
    return bool(legacy) and legacy != {next(iter(toks))[0]}


def lean_labels(text):
    """(set of labels the row says the Lean takes, the recommended label or None) of one QUESTION row's text: the
    token's when it has one (two different tokens, or a token its own prose contradicts: nothing), else the legacy
    wordings'."""
    toks = _tokens(text)
    if toks:
        if len(toks) != 1 or token_conflict(text):
            return set(), None
        return {next(iter(toks))[0]}, next(iter(toks))[1]
    return _lean_takes(text), None


def reading_answer(c, rnd, lane, item):
    """("kept", reading, who) when a final answer to the QUESTION row of round `rnd` on (lane, item) took the reading
    that row says the Lean takes (AUDIT_PROTOCOL C: the row names "the one the Lean takes"); ("other", taken, lean,
    who) when it took exactly one other reading; else None. The answer: the [DELEGATED] lines naming that round's
    QUESTION row on the item, else the latest `question:<item>` answer line; every reading it names counts ("keep
    the Lean's reading" names the row's). The caller has checked that no open question names the result."""
    import audit_coverage as ac, decisions
    key = ac.norm_item(item)
    takes, recs = set(), set()
    for it, asks in (c.get("qrows") or {}).items():
        if ac.norm_item(it) != key:
            continue
        for r, l, why in asks:
            if r == rnd and l == lane:
                if token_conflict(why):
                    # review MEDIUM-1: settles nothing, and a delivery note names the row (make_report.decided_notes)
                    c.setdefault("token_conflict", {})[(rnd, lane, key)] = (
                        f"the {lane} QUESTION row of round {rnd} on {it}: its [Lean: ...] token names reading "
                        f"({next(iter(_tokens(why)))[0]}) but its text says the Lean takes "
                        + ", ".join(f"({x})" for x in sorted(_lean_takes(why))) + ": the reading is not read from it "
                        "(its result reads not established); correct the row or say which holds in the summary")
                t_, rec = lean_labels(why)
                takes |= t_
                if t_ and rec:
                    recs.add(rec)
    if len(takes) != 1:
        return None
    anchor = re.compile(re.escape(decisions.anchor_id("question", str(item).strip().strip("`"))) + r"(?![\w.])", re.I)
    exact, anchored = [], []
    for ln in str(c.get("log") or "").splitlines():
        tag = decisions.DELEGATED_TAG_RE.search(ln)
        if not (tag or decisions.ANSWER_LINE_RE.match(ln)):
            continue
        q = decisions.QROW_RE.search(ln)
        if tag and q and q.group("round") == rnd and q.group("item") and \
                ac.norm_item(q.group("item").strip().strip("`")) == key:
            exact.append(ln)
        elif anchor.match(re.sub(r"^\s*[-*]\s*(?:answered\s+)?", "", ln, flags=re.I)):
            anchored.append(ln)
    lines = exact or anchored[-1:]
    if not lines:
        return None
    said = set()
    for ln in lines:
        ln_ = ln.replace("**", "")
        got = _labels(READING, ln_)
        if not got and any(not _negated(ln_, m) for m in LEANS_READING.finditer(ln_)):
            got = set(takes)
        said |= got
    who = ("a delegated decision of the operator" if all(decisions.DELEGATED_TAG_RE.search(ln) for ln in lines)
           else "the human's answer")
    if said == takes:
        return "kept", next(iter(takes)), who
    if len(said) == 1 and _same_scheme(next(iter(said)), next(iter(takes))):
        return "other", next(iter(said)), next(iter(takes)), who
    return None


def _same_scheme(a, b):
    """Two labels of one labelling scheme: digits, letters, roman numerals (a lone i, v or x may be either of the
    last two). Labels of different schemes are never compared ((b) and (ii) say nothing about each other)."""
    kinds = lambda x: {"digit"} if x.isdigit() else ({"letter", "roman"} if x in ("i", "v", "x") else
                                                     {"roman"} if re.fullmatch(r"[ivx]+", x) else {"letter"})
    return bool(kinds(a) & kinds(b))


def _capped_or(reason, c, lane, items):
    """`reason`, or -- when the statement-round cap left this (lane, item) open (c["capped"]) -- the open
    faithfulness finding it is (route round-cap: disclosed, never a delivery block). An unanswered QUESTION (route
    `question`) stays the human's, as a result's own does."""
    import audit_coverage as ac
    if reason[1] == "question":
        return reason
    cap = next((c.get("capped", {})[f"{lane} :: {ac.norm_item(i)}"] for i in items
                if f"{lane} :: {ac.norm_item(i)}" in c.get("capped", {})), None)
    if not cap:
        return reason
    return (f"open faithfulness finding: {reason[0]} (the statement-round cap was reached at round {cap} with it "
            f"open)", "round-cap")


def _def_route(c, lt, lane, dl, dn, keys=()):
    """B1: the route of a non-Pass verdict on a Definition row the result uses (R3: its status names it whatever the
    records say), by the same rule as a result's own verdict (_route), the question read for the definition's own
    label and names: `question` while its QUESTION is unanswered (the human's, as the definition's own row is),
    `decided` once decided, else `adjudicator`. Before B1 every one was `adjudicator`, so a round no adjudicator
    could clear it in was scoped for it."""
    r = _route(c, lt[0], lane, lt[2], dl, dn, decision(c, lt[0], lane, lt[2][0]) if lt[2] else None, keys)
    if r == "decided":
        _note_decided(c, lt[0], lane, list(dict.fromkeys(list(lt[2]) + _nonpass_items(c, lt[0], lane, keys))), dl, dn)
    return r


def _def_kept(c, lt, lane, dl, dn, subject, kept):
    """A5b: True when the verdict `lt` on a Definition row the result uses is an Ambiguous whose QUESTION a final
    answer settled by the reading the row says the Lean takes (reading_answer, read for the definition's own label
    and names, as for a result's own verdict); `kept` then gets its "faithful under reading" status (never the plain
    "faithful": the reading is disclosed)."""
    rnd, v, items = lt
    if v != "Ambiguous" or not items or decision(c, rnd, lane, items[0]) != "QUESTION" or not _answered(c, dl, dn):
        return False
    ks = [reading_answer(c, rnd, lane, i) for i in items]
    if not (ks and all(k and k[0] == "kept" for k in ks)):
        return False
    if kept is not None:
        kept.append(f"faithful under reading ({ks[0][1]}) of the {lane} question on {subject} (round {rnd}): the "
                    f"reading the Lean takes, kept by {ks[0][2]}")
    return True


def _note_decided(c, rnd, lane, items, label, names):
    """Remember a `decided` verdict for make_report.decided_notes (review M1: an ADOPT with no OUTCOMES.md row, or
    "implemented" with no Lean commit behind it, is a delivery note: the forced round that used to re-check it is
    gone). Keyed so that repeated analyses of one context record it once."""
    c.setdefault("decided_rows", {})[(rnd, lane, tuple(items))] = {
        "result": label, "names": list(names), "decs": [decision(c, rnd, lane, i) for i in items]}


def verdict_reasons(c, label, names, records, is_def, kept=None):
    """[(reason, route)] standing between the result and F1 (empty: F1's verdict conditions hold).
    `records`: which adjudicator-owned records name the result ({"defect", "vacuous", "skipped", "excluded",
    "reading", "differs"}). `kept`: a list that gets a "faithful under reading" status for every Ambiguous settled
    by an answered question keeping the Lean's reading (reading_answer)."""
    out = []
    decls = [n for n in names if not c["cur"] or n in c["cur"]]

    def judge(lane, keys, subject, about, record_ok):
        lt = latest(c, lane, keys)
        if lt is None:
            out.append((f"no {lane} verdict on {subject}", "unverified"))
            return
        rnd, v, items = lt
        why = fresh(c, rnd, about)
        if why:
            out.append((f"the {lane} verdict on {subject} (round {rnd}) is out of date: {why}", "unverified"))
            return
        if v == "Pass":
            return
        dec = decision(c, rnd, lane, items[0]) if items else None
        if dec == "REJECT":
            return
        if dec in ("ADOPT", "DEFER", "QUESTION") and record_ok(v):
            return
        other = None
        if dec == "QUESTION" and v == "Ambiguous" and _answered(c, label, names):
            ks = [reading_answer(c, rnd, lane, i) for i in items]
            if ks and all(k and k[0] == "kept" for k in ks):
                if kept is not None:
                    kept.append(f"faithful under reading ({ks[0][1]}) of the {lane} question on {subject} (round "
                                f"{rnd}): the reading the Lean takes, kept by {ks[0][2]}")
                return
            other = next((k for k in ks if k and k[0] == "other"), None)
        route = _route(c, rnd, lane, items, label, names, dec, keys)
        why_ = f"{lane} {v} on {subject} (round {rnd}; decision: {dec or 'none recorded'})"
        if other:
            # A5 (review M3): the answer took another reading than the Lean's: the Lean must change (re-approval) or
            # the answer be revised -- said in the status and as a delivery note (make_report.decided_notes)
            why_ = why_[:-1] + f"; the answer took reading ({other[1]}), the Lean takes ({other[2]}))"
            c.setdefault("reading_mismatch", {})[(rnd, lane, label)] = (
                f"{label}: the answer to the {lane} QUESTION of round {rnd} on {subject} ({other[3]}) took reading "
                f"({other[1]}), but the row says the Lean takes ({other[2]}): change the Lean (by re-approval) or "
                f"revise the answer (stage5-delivery.md step 7), and say which holds in the summary")
        if route == "decided":
            _note_decided(c, rnd, lane, list(dict.fromkeys(list(items) + _nonpass_items(c, rnd, lane, keys))), label,
                          decls)
        import audit_coverage as ac
        cap = next((c.get("capped", {})[f"{lane} :: {ac.norm_item(i)}"] for i in items
                    if f"{lane} :: {ac.norm_item(i)}" in c.get("capped", {})), None)
        if route in ("adjudicator", "decided") and cap:
            # approver 2026-10-24 (decision 3): the statement-round cap was reached with this finding open and the
            # run went on (project.round_cap_route): disclosed on the summary's first page, never a delivery block
            out.append((f"open faithfulness finding: {lane} {v} on {subject} (round {rnd}; the statement-round cap "
                        f"was reached at round {cap} with it open)", "round-cap"))
            return
        out.append((why_, route))

    def rec_ok(lane):
        def ok(v):
            base = records & {"defect", "skipped", "excluded"}
            if lane == "non-vacuity":
                return bool(base or "vacuous" in records)
            if v == "Ambiguous":
                return bool(base or records & {"vacuous", "reading"})
            return bool(base or records & {"vacuous", "differs"})
        return ok

    for lane in ("correspondence", "non-vacuity"):
        for d in decls:
            judge(lane, [d], f"`{d}`", [d], rec_ok(lane))
    lk = norm_label(label)
    core = label_core(lk)
    pf_keys = [lk]
    if lk == core:      # a row without a part: every part's item counts too
        pf_keys += sorted({k for (ln, k) in c["hist"] if ln == "paper-faithfulness" and label_core(k) == core
                           and k != lk and re.match(r"^\(", k[len(core):])})
    elif not any(c["hist"].get(("paper-faithfulness", lk), [])):
        pf_keys = [core]
    judge("paper-faithfulness", pf_keys, label, decls, rec_ok("paper-faithfulness"))
    if not decls and not out:
        out.append(("its index row names no Lean declaration with a fingerprint", "unmapped"))
    defs, recorded = closure_defs(c, decls)
    for dl, dn in defs:
        if norm_label(dl) == lk:
            continue
        dd = [n for n in dn if not c["cur"] or n in c["cur"]]
        sub = []
        for lane in DEF_LANES:
            if lane == "paper-faithfulness":
                lt = latest(c, lane, [norm_label(dl)])
                about = dd
            else:
                lt = None
            if lane == "correspondence":
                for d in dd:
                    lt_ = latest(c, lane, [d])
                    if lt_ is None:
                        sub.append((f"no correspondence verdict on `{d}` ({dl}, used by it)", "unverified"))
                    elif fresh(c, lt_[0], [d]):
                        sub.append((f"the correspondence verdict on `{d}` ({dl}, used by it) is out of date: "
                                    f"{fresh(c, lt_[0], [d])}", "unverified"))
                    elif lt_[1] != "Pass" and decision(c, lt_[0], lane, lt_[2][0]) != "REJECT":
                        if _def_kept(c, lt_, lane, dl, dn, f"`{d}` ({dl}, used by it)", kept):
                            continue
                        sub.append(_capped_or((f"correspondence {lt_[1]} on `{d}` ({dl}, used by it)",
                                               _def_route(c, lt_, lane, dl, dn, [d])), c, lane, lt_[2]))
                continue
            if lt is None:
                sub.append((f"no paper-faithfulness verdict on {dl} (used by it)", "unverified"))
            elif fresh(c, lt[0], about):
                sub.append((f"the paper-faithfulness verdict on {dl} (used by it) is out of date: "
                            f"{fresh(c, lt[0], about)}", "unverified"))
            elif lt[1] != "Pass" and decision(c, lt[0], lane, lt[2][0]) != "REJECT":
                if _def_kept(c, lt, lane, dl, dn, f"{dl} (used by it)", kept):
                    continue
                sub.append(_capped_or((f"paper-faithfulness {lt[1]} on {dl} (used by it)",
                                       _def_route(c, lt, lane, dl, dn, [norm_label(dl)])), c, lane, lt[2]))
        out += sub
    # drift: the approved version is not the audited one
    appr = (c["approval"] or {}).get("fingerprints") or {}
    for d in decls:
        if d in appr and c["cur"] and d in c["cur"] and appr[d] != c["cur"][d] and d not in c["reapproving"]:
            out.append((f"`{d}` differs from its approved statement (fingerprint drift)", "drift"))
    return out


# --- the statuses --------------------------------------------------------------------------------------
def _defect_words(st, rp, stated, assumed=False):
    """`assumed`: the result's Lean is a named hypothesis (literature or missing theory), stated and never proved."""
    s = STATUS_WORDS.get(st.split(" ")[0] if st else "", "")
    if not s:
        return ""
    if st.startswith("false") or st.startswith("vacuous"):
        if rp in REPAIRED:
            if assumed:
                return s + "; assumed as a corrected hypothesis (not proved)"
            return s + ("; the repaired statement is stated, not proved" if stated else "; proved as repaired")
        if rp.startswith("none"):
            return s + "; intent unknown, not repaired"
        if rp == "not repaired":
            return s + "; not repaired"
    if st.startswith("unsupported"):
        return s + ("" if stated or assumed else "; proved here")
    if st.startswith("misprint"):
        return s + ("" if stated or assumed else "; proved as intended")
    return s


def _assumption_statuses(c, names, stated, cfg):
    """[(status, route or None)] for the hypotheses the walk lists for the result's declarations."""
    import hypotheses
    out = []
    if c["walk"] is None:
        if names:
            out.append((f"not established: no assumption walk ({c['walk_why']})", "unmapped"))
        return out
    walked = set(c["walk"].get("walked") or [])
    ns = c["ns"]
    for n_, uses in sorted(c["assumed"].items()):
        mine = [(r, e) for r, e in uses if r in names]
        if not mine:
            continue
        short = n_.rsplit(".", 1)[-1] if ":" not in n_ else n_
        kind = hypotheses.classify(cfg, n_, c["mt"])
        emb = any(e.get("embedded") for _r, e in mine)
        # an inline `<result>:<binder>` (a walk-flagged binder whose type uses no project constant) is classified by
        # its `## Hypotheses` row, as a named hypothesis is (bench1: routing it here whatever its row said made
        # delivery unreachable); the B5 rule that a flagged binder's only valid value is `no` is hypotheses.latest's
        if emb or kind.startswith("unclassified"):
            out.append((f"not established: unclassified assumption `{short}`" + (" (embedded in the statement)"
                                                                                if emb else ""), "adjudicator"))
            continue
        row = c["hyp_rows"].get(n_)
        if not row or row[3]:
            out.append((f"not established: the hypothesis `{short}` has no valid record yet", "adjudicator"))
            continue
        w = hypotheses.match_word(row[2].get("matches source", ""))
        if w == "no":
            # B1: the adjudicator's `## Hypotheses` row says `no`: a decision, so no round can clear it (`decided`)
            out.append((f"not established: the hypothesis `{short}` does not match its source", "decided"))
            continue
        if kind.startswith("inline") and w == "yes":
            continue        # B5: a flagged binder confirmed as the paper's own printed hypothesis assumes nothing more
        verb = "stated assuming" if stated else "proved assuming"
        s = f"{verb} `{short}` ({kind})" + (" (source not checked)" if w == "source unavailable" else "")
        unc = [f"{r}_unconditional" for r, _e in mine if f"{r}_unconditional" in (c["cur"] or {})]
        for u in unc:
            lt = latest(c, "correspondence", [u])
            if lt and lt[1] == "Pass" and not fresh(c, lt[0], [u]):
                s += f"; also proved unconditionally (`{u.rsplit('.', 1)[-1]}`)"
            else:
                s += f"; an unconditional version (`{u.rsplit('.', 1)[-1]}`) is not yet reviewed"
        out.append((s, None))
    for ax, users in sorted(((a, [r for r, v in (c["walk"].get("axioms") or {}).items() if a in v])
                             for a in {a for v in (c["walk"].get("axioms") or {}).values() for a in v})):
        if set(users) & set(names):
            out.append((f"not established: uses the declared axiom `{ax}`", "unmapped"))
    if not (set(names) & walked) and any(n in (c["walk"].get("results") or []) for n in names):
        out.append(("not established: the assumption walk did not reach it", "unmapped"))
    return out


def analyse(cfg, row, c):
    """(statuses, [Route]) of one index row."""
    label = " ".join(str(row[0]).split())
    names = row_names(row[1] if len(row) > 1 else "", c["ns"], c["known"])
    is_def = bool(DEF_KIND.match(label))
    st, routes, records = [], [], set()
    appr_row = ((c["approval"] or {}).get("rows") or {}).get(label) or {}
    if appr_row.get("status") == "excluded":
        st.append("excluded at Checkpoint B")
        records.add("excluded")
    sh, srows = c["skipped"]
    for r in srows:
        # the row's subject (its `what` cell), never its reasons: a skip that cites a result is not about it
        what_ = _col(sh, r, "what") or (r[1] if len(r) > 1 else "")
        # fix round 1 (attack 1): the row answers a Fail (records) only for the result it is ABOUT, the one that also
        # gets its status; a context mention gives neither (else a Fail it does not answer read "faithful")
        if mentions(primary_subject(what_, "skipped"), label, names):
            st.append(f"not formalized (SKIPPED row {r[0]})")
            records.add("skipped")
    opn = [q for q in c["questions"] if mentions(q[2], label, names)]
    if opn:
        st.append("decision open: " + "; ".join(f"{q[1]} question of round {q[0]} on {q[2]}" for q in opn))
        routes.append(Route(label, "an open question", "question", "question"))
    # integrated review fix 9: while a re-approval of its statement is open the Lean may still be the old, approved
    # and audited version, so every review passes -- the result is not "faithful" then: its statement is in question
    short = {x.rsplit(".", 1)[-1] for x in c["reapproving"]}
    reap = [d for d in names if d in c["reapproving"] or d.rsplit(".", 1)[-1] in short]
    if reap:
        st.append("decision open: a change to its statement (" + ", ".join(f"`{d.rsplit('.', 1)[-1]}`" for d in reap)
                  + ") awaits re-approval (signoff.py reapprove --begin; closed by signoff.py approve)")
        routes.append(Route(label, "an open re-approval of its statement", "question", "question"))
    stated = [d for d in names if d in c["unproved"] or d.rsplit(".", 1)[-1] in
              {u.rsplit(".", 1)[-1] for u in c["unproved"]}]
    conj = bool(OPEN_KIND.match(label))
    # a result formalized as a named hypothesis (a cited result the paper does not prove) is
    # stated and assumed, never proved -- a benchmark run's defect read "proved as repaired"
    import hypotheses
    assumed = [(d, hypotheses.classify(cfg, d, c["mt"])) for d in names if d not in stated]
    assumed = [(d, k) for d, k in assumed if k.startswith(("literature", "missing-theory"))]
    reasons = verdict_reasons(c, label, names, set(), is_def)     # first pass: for "stated only"'s note
    dh, drows, old = c["defects"]
    dtexts = []
    for r in drows:
        # the row's `where` cell names its result; its witness only when `where` names no result at all (a
        # witness may be another result's lemma: `lemma_1_3_b` witnessing a defect of Lemma 1.2)
        where = _col(dh, r, "where")
        about = mentions(where, label, names) if re.search(rf"(?i)\b({project.RESULT_KINDS_RE})\s+\d", where) or \
            re.search(r"`[^`]+`", where) else mentions(_col(dh, r, "lean witness"), label, names)
        if about:
            wit = [t.split("(")[0].strip() for t in re.findall(r"`([^`]+)`", _col(dh, r, "lean witness"))]
            wit = list(dict.fromkeys(w for w in wit if _LEAN.match(w)))
            wtxt = (" (witness " + ", ".join(f"`{w}`" for w in wit) + ")") if wit else " (no Lean witness)"
            records.add("defect")
            if old:
                sev = _col(dh, r, "severity")
                sev = (re.search(r"\bS\d\b", sev) or [" ".join(sev.split()) or "?"])[0]
                dtexts.append(f"defect {r[0]}: severity {sev} (an old-format "
                              f"row: status and repair not yet recorded by the adjudicator){wtxt}")
                routes.append(Route(label, f"defect {r[0]} is in the old format", "adjudicator", "adj-record"))
                continue
            s_, r_ = " ".join(_col(dh, r, "status").strip("*` ").split()), " ".join(_col(dh, r, "repair").strip("*` ").split())
            words = _defect_words(s_.lower(), r_.lower(), bool(stated), bool(assumed))
            dtexts.append(f"defect {r[0]}: {s_ or 'status not recorded'}; {r_ or 'repair not recorded'}"
                          + (f" — {words}" if words else "") + wtxt)
    vh, vrows = c["vacuous"]
    vtexts = []
    for r in vrows:
        if mentions(primary_subject(_col(vh, r, "statement"), "vacuous"), label, names):
            records.add("vacuous")
            stv = " ".join(_col(vh, r, "status").split())
            vtexts.append(f"vacuous (VACUOUS row {r[0]}" + (f"; {stv}" if stv else "") + ")")
    deh, derows = c["deviations"]
    reading, differs = [], []
    for r in derows:
        k = _col(deh, r, "kind").strip("*` ").lower()
        if not mentions(_col(deh, r, "result") or r[0], label, names):
            continue
        if k == "reading choice":
            records.add("reading")
            reading.append(f"faithful under reading {r[0]}: {' '.join(_col(deh, r, 'the lean route').split())} "
                           f"(alternative: {' '.join(_col(deh, r, 'the paper').split())})")
        elif k.startswith("differs"):
            records.add("differs")
            differs.append(f"differs (DEVIATIONS row {r[0]}): {' '.join(_col(deh, r, 'why').split())}")
    kept = []
    reasons = verdict_reasons(c, label, names, records, is_def, kept)
    reading += kept
    if stated or conj:
        what = (", ".join(f"`{d.rsplit('.', 1)[-1]}`" for d in stated) + " left unproved") if stated else \
            "a conjecture: stated as a proposition, asserted nowhere"
        if not reasons:
            what += "; its statement checked faithful"
        st.append(f"stated only ({what})")
    if assumed and not any("assumed as a corrected hypothesis" in t for t in dtexts):
        st.append("assumed, not proved (" + ", ".join(f"`{d.rsplit('.', 1)[-1]}`: {k}" for d, k in assumed) + ")")
    st += dtexts + differs + vtexts
    asm = _assumption_statuses(c, names, bool(stated), cfg)
    for why, route in reasons:
        st.append(f"not established: {why}")
        routes.append(Route(label, why, route, _code(route)))
    for s, route in asm:
        if s.startswith("not established"):
            st.append(s)
            routes.append(Route(label, s[len("not established: "):], route, _code(route)))
    st += [s for s, route in asm if not s.startswith("not established")]
    st += [m for m in c.get("core") or [] if m not in st]
    for p in c["problems"]:
        st.append(f"not established: {p}")
        routes.append(Route(label, p, "unmapped", UNMAPPED_CODE))
    if reading:
        if any(s.startswith("not established") for s in st):
            st += [r_.replace("faithful under reading", "reading choice", 1) for r_ in reading]
        else:
            st += reading
    if not st:
        st = [FAITHFUL]
    return st, routes


def _code(route):
    return {"unverified": "unverified", "adjudicator": "adj-record", "decided": "adj-record", "drift": "drift",
            "question": "question",
            "unmapped": UNMAPPED_CODE, "round-cap": "round-cap"}.get(route, UNMAPPED_CODE)


def result_status(cfg, row, inp=None):
    """[status] of one index row (B10's SUMMARY and page 1 call this; see the module docstring)."""
    return analyse(cfg, row, ctx_of(cfg, inp))[0]


# ---- next batch G1 (approver D1, NW-5/NW-6/NW-11): the conditions checklist and the K certificate ---------------
# K1: the Lean statement says exactly what the paper says; K2: kernel-checked, no `sorry`, standard axioms; K3: every
# nontrivial representation proved equivalent in Lean (a bridge theorem); K4: no unproved assumption. These readers
# FLAG only: they never refuse, never stop (reviewers judge triviality and adequacy; code checks mechanics).
# K-REMOVE (approver 2026-11-16): no K verdict is computed here; the formalizing agent writes the K certificate.
CONDITIONS_MD = "CONDITIONS.md"
COND_KINDS = ("condition", "scope", "known-issue", "bridge", "reading", "source-def", "finding")
COND_CLOSED = ("met", "not applicable")
COND_ID = re.compile(r"^(?:C\??-?\d+|K3-\d+)$")     # C<n>, an adjudicator's C?-<n> (a condition missing from the list), K3-<n>
RAW_ID_WHY = "id not in C<n>/K3-<n> form"     # fix round K (AUDIT-P5 §3): such a row is kept under its raw id, open


_STATUS_RE = re.compile(r"^(met|open|out of reach|not applicable)(?:\s*(?:—|–|--|-|:)\s*(.*))?$")


def _cond_status(cell):
    """(status, tail) of a `## Conditions` status cell, read by EXACT word (fix round 1, attack 4): `met`, `open`, `out
    of reach` or `not applicable`, alone or followed by a dash or colon and a remark (`not applicable — now C4`).
    Anything else ("met only for part (a)", "Met?", "metric argument pending") reads `open`."""
    t = " ".join(str(cell).replace("*", "").replace("`", "").split()).lower().rstrip(".")
    m = _STATUS_RE.match(t)
    return (m.group(1), (m.group(2) or "").strip()) if m else ("open", t)


def _clean_id(cell):
    return str(cell).replace("*", "").replace("`", "").strip().rstrip(".:").strip()


def conditions(cfg, rd=None):
    """{id: item} of the run's conditions and open K items: every row of `<rounds>/CONDITIONS.md` (the operator's
    checklist: id | kind | results | text | source) and every id first seen in an adjudicator's `## Conditions` table
    (ADOPTED.md: id | status | evidence | reason; `K3-<n>` a bridge, `C?-<n>` a condition missing from the list).
    Each item carries its latest status row (rounds oldest first; a later row replaces an earlier one): `status` (no
    row: "no status row"), `evidence`, `reason`, `round`, and `why_open` when a closing status cannot be confirmed:
    `met` with no evidence, `not applicable — now C<k>` naming no listed C<k> (fix round 1, attack 4). An item is
    closed only when its status is met or not applicable AND that is confirmed. The key "_unparsed" holds the table
    rows whose id is not in the C<n>/C?-<n>/K3-<n> form (attack 3) -- fix round K (AUDIT-P5 §3): such a row is still
    kept under its raw id, its kind from its kind cell (unknown: K4), and it counts open (why_open RAW_ID_WHY: never
    met, never dropped); "_headers" the tables whose header does not start with `id` (fix
    round 2, M2): their rows are read by the first column and their items count open (never met)."""
    import decisions, hypotheses
    rd = rd or os.path.join(project.REPO, cfg["rounds_dir"])
    out, unparsed, headers = {}, [], []
    odd_why = "read from a table whose header does not start with `id`"
    try:
        txt = open(os.path.join(rd, CONDITIONS_MD), encoding="utf-8").read()
    except OSError:
        txt = ""
    for h, c in decisions.table_rows(txt):
        if not h or len(c) < 2:
            continue
        odd = h[0].strip("* ").lower() != "id"     # fix round 2 (M2): noted, read by its first column, open
        if odd and f"{CONDITIONS_MD}: {h[0]!r}" not in headers:
            headers.append(f"{CONDITIONS_MD}: {h[0]!r}")
        col = lambda n: c[h.index(n)].strip() if n in h and h.index(n) < len(c) else ""
        i = _clean_id(c[0] if odd else col("id"))
        if not COND_ID.match(i):
            if odd or not i:
                continue
            unparsed.append(f"{CONDITIONS_MD}: {col('id')!r}")     # fix round K: kept under its raw id, open
        out[i] = {"id": i, "kind": col("kind").strip("`* ").lower(), "results": col("results"), "text": col("text"),
                  "source": col("source"), "status": "no status row", "evidence": "", "reason": "", "round": None,
                  "listed": True, "odd": odd}
    rows = []
    for d in hypotheses._round_dirs(rd):
        try:
            a = open(os.path.join(d, "ADOPTED.md"), encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"^## Conditions\b.*?$(.*?)(?=^## |\Z)", a, re.M | re.S)
        if not m:
            continue
        for h, c in decisions.table_rows(m.group(1)):
            if not h or len(c) < 2:
                continue
            odd = h[0].strip("* ").lower() != "id"     # fix round 2 (M2)
            where = f"{os.path.basename(d)}/ADOPTED.md ## Conditions: {h[0]!r}"
            if odd and where not in headers:
                headers.append(where)
            col = lambda n: c[h.index(n)].strip() if n in h and h.index(n) < len(c) else ""
            i = _clean_id(c[0] if odd else col("id"))
            if not COND_ID.match(i):
                if odd or not i:
                    continue
                unparsed.append(f"{os.path.basename(d)}/ADOPTED.md: {col('id')!r}")     # fix round K: raw id, open
            rows.append((d, i, dict({n: col(n) for n in ("status", "evidence", "reason")}, odd=odd)))
    for d, i, cells in rows:
        col = cells.get
        it = out.setdefault(i, {"id": i, "kind": "bridge" if i.startswith("K3-") else "condition",
                                "results": "", "text": col("reason"), "source": f"{os.path.basename(d)}/ADOPTED.md",
                                "listed": False})
        st, tail = _cond_status(col("status"))
        it.update(status=st, evidence=col("evidence"), reason=col("reason"), round=os.path.basename(d), why_open="")
        if st == "met" and col("evidence").strip("`*- ") == "":
            it["why_open"] = "`met` without evidence"
        if cells.get("odd"):
            it["why_open"] = odd_why
        if st == "not applicable":
            now = re.search(r"\bnow\s+(C\d+)\b", tail + " " + col("reason"), re.I)
            if now and not (out.get(now.group(1).upper()) or {}).get("listed"):
                it["why_open"] = (f"`not applicable — now {now.group(1).upper()}`, but {now.group(1).upper()} is not in "
                                  f"{CONDITIONS_MD}")
    for i, it in out.items():
        it.setdefault("why_open", "")
        if it.pop("odd", False):
            it["why_open"] = odd_why
        if not COND_ID.match(i):        # fix round K (AUDIT-P5 §3): an id the code cannot read never closes
            it["why_open"] = RAW_ID_WHY
        it["open"] = it["status"] not in COND_CLOSED or bool(it["why_open"])
    if unparsed:
        out["_unparsed"] = unparsed
    if headers:
        out["_headers"] = headers
    return out


def _items(cfg, rd=None):
    """conditions() without its "_unparsed" and "_headers" keys."""
    return {k: v for k, v in conditions(cfg, rd).items() if not k.startswith("_")}


def _plural(kind):
    return kind[:-1] + "ies" if kind.endswith("y") else kind + "s"


# fix round P6 (AUDIT-P6 §2, fix 1): a list of labels in a `results` cell, "Theorems 1.3, 2.1, 2.2, 3.1", "Lemmas 2.4
# and 2.6", "Lemmas 2.4–2.6"; a bare number after a kind word takes that kind ("Theorem 2.1 and 2.2")
_LNUM = r"\d+(?:\.\d+)*(?:\s*\([a-z0-9ivx]{1,4}\))?"
_LSEP = r"\s*(?:,\s*and\b|,|;|&|\band\b)\s*"
_LRANGE = r"\s*(?:–|—|-|\bto\b)\s*"
_LIST_RE = re.compile(r"\b(" + "|".join(sorted({x for k in project.RESULT_KINDS if " " not in k
                                                  for x in (_plural(k), k)}, key=len, reverse=True))
                      + rf")\s+({_LNUM}(?:(?:{_LSEP}|{_LRANGE}){_LNUM})*)(?![\w.])", re.I)
_SINGULAR = {x.lower(): k for k in project.RESULT_KINDS if " " not in k for x in (_plural(k), k)}


def expand_labels(cell):
    """A results cell with each list of labels written out: "Theorems 1.3, 2.1 and 2.2" -> "Theorem 1.3, Theorem 2.1,
    Theorem 2.2"; a range "Lemmas 2.4–2.6" (same prefix, integer last part, at most 50 numbers) -> each number; a
    list with a range it cannot write out stays as written (its plural kind word matches no row: counted against every
    result)."""
    def rep(m):
        kind = _SINGULAR[m.group(1).lower()]
        body = m.group(2)
        nums = list(re.finditer(_LNUM, body))
        out, k = [], 0
        while k < len(nums):
            a = nums[k].group(0)
            if k + 1 < len(nums) and re.fullmatch(_LRANGE, body[nums[k].end():nums[k + 1].start()]):
                b = nums[k + 1].group(0)
                pa, _, la = a.rpartition(".")
                pb, _, lb = b.rpartition(".")
                if pa == pb and la.isdigit() and lb.isdigit() and 0 < int(lb) - int(la) <= 50:
                    out += [f"{kind} {pa + '.' if pa else ''}{x}" for x in range(int(la), int(lb) + 1)]
                else:
                    return m.group(0)       # as written (a plural kind word then matches no row: counted everywhere)
                k += 2
                continue
            out.append(f"{kind} {a}")
            k += 1
        return ", ".join(out)
    return _LIST_RE.sub(rep, " ".join(str(cell or "").split()))


def unmatched_entries(cell, idx):
    """[entry] of a `results` cell (split on `,`, `;`, `and`, `&`) that match no index row of idx = [(label, names)]
    (fix round 2, M1): such an item counts against every result. A bare part such as "(c)" after "Lemma 5.4 (b)"
    belongs to the entry before it and is not checked alone; `all` and an empty cell give []."""
    cell = " ".join(str(cell or "").split())
    if not cell or cell.lower() == "all":
        return []
    out = []
    for e in re.split(r"[,;&]|\band\b", expand_labels(cell)):     # fix round P6: plural lists written out
        e = e.strip(" .")
        if not e or re.fullmatch(r"\(?[a-z0-9ivx]{1,4}\)", e, re.I):
            continue
        if not any(mentions(e, label, names) for label, names in idx):
            out.append(e)
    return out


def index_names(cfg, inp=None):
    """[(label, names)] of every index row."""
    c = ctx_of(cfg, inp)
    return [(" ".join(str(r[0]).split()), row_names(r[1] if len(r) > 1 else "", c["ns"], c["known"])) for r in c["index"]]


# kinds that are context, never an item for the adjudicator to rule
_CONTEXT_KINDS = ("scope", "known-issue")


def inferred_items(cfg, rd, items, inp=None):
    """Open K items the record shows but no checklist row holds (fix round 1, attack 5; flags, never refusals):
    `R?-<n>` for a `[DELEGATED …] … take reading (x)` line on a QUESTION row whose item no `reading` item names, and
    `K3?-<n>` for a lane's `REPRESENTATION: … nontrivial` note in a round with no `K3-` row at all. Fix round K
    (AUDIT-P5 §4): one R? per decision -- the item is read from a leading `question:<decl>` anchor or the QUESTION-row
    words, `answered …` copies are skipped, and a `reading` item naming the index row of that decl (its label or a
    Lean name) counts as the item."""
    import decisions
    out = {}
    try:
        log = open(os.path.join(rd, "RUN_LOG.md"), encoding="utf-8").read()
    except OSError:
        log = ""
    readings = [it for it in items.values() if it["kind"] == "reading"]
    try:
        idx = index_names(cfg, inp)
    except Exception:       # noqa: BLE001 -- no index: only the literal match below
        idx = []
    try:        # fix round P6 (AUDIT-P6 §3): the current declaration set (empty: nothing is stale)
        c_ = ctx_of(cfg, inp)
        known = {str(k).split(" (private in ")[0] for k in (c_.get("known") or ())}
        # fix round P6b (REVIEW-FIXP6-NB M2): the fingerprints, current and recorded (content, not the name)
        cur_fp = {}
        for k_, v_ in (c_.get("cur") or {}).items():
            cur_fp.setdefault(v_, set()).add(str(k_).split(" (private in ")[0])
        snaps = list(c_.get("snaps") or [])
    except Exception:       # noqa: BLE001 -- unreadable: every inferred item stays counted open
        known, cur_fp, snaps = set(), {}, []
    ns = str(cfg.get("namespace") or "")

    def last_fp(name):
        """The declaration's fingerprint in the newest recorded snapshot that holds it, or None (unknown)."""
        for s_ in reversed(snaps):
            fps = s_[1] if len(s_) > 1 and isinstance(s_[1], dict) else {}
            for k_, v_ in fps.items():
                if str(k_).split(" (private in ")[0] == name and v_ is not None:
                    return v_
        return None

    def stale(name):
        """A project declaration (`<ns>.x`) no longer in the current declaration set AND whose last recorded
        fingerprint no current declaration carries (a deletion the code can confirm): its item is not counted.
        Fix round P6b (REVIEW-FIXP6-NB M2): an unknown old fingerprint, or one a current declaration carries (a
        rename or a move), keeps the item open."""
        name = str(name or "").strip().strip("`")
        if not (known and ns and name.startswith(ns + ".") and _LEAN.match(name) and name not in known):
            return False
        fp = last_fp(name)
        return fp is not None and fp not in cur_fp

    def renamed(name):
        """The one current declaration carrying the absent declaration's last fingerprint, or None."""
        name = str(name or "").strip().strip("`")
        if not name or name in known:
            return None
        fp = last_fp(name)
        to = sorted(cur_fp.get(fp) or ()) if fp is not None else []
        return to[0] if len(to) == 1 else None
    n, seen = 0, set()
    for ln in log.splitlines():
        if "[DELEGATED" not in ln or "take reading" not in ln:
            continue
        # fix round K (AUDIT-P5 §4): one item per decision -- the `answered question:` copies (B20) are skipped, the
        # item is read from a leading `question:<decl>` anchor too, and a reading item naming the row's label counts
        body = ln.strip().lstrip("-* ").strip()
        if re.match(r"(?i)answered\b", body):
            continue
        a = re.match(r"question:\s*([^\s:]+(?::[^\s:]+)*?):\s", body)
        q = decisions.QROW_RE.search(ln)
        lab = " ".join(((a.group(1) if a else "") or (q.group("item") if q else "") or "").split())
        rows_ = [(l_, ns_) for l_, ns_ in idx if lab and (lab == l_ or lab in ns_ or mentions(lab, l_, ns_))]
        # fix round P6 (AUDIT-P6 §2, fix 2): the line names the open `reading` item that carries this decision
        # ("open item C3"): no R? item. A referenced id that is not an open reading item keeps the R? item (open).
        # Fix round P6b (REVIEW-FIXP6-NB M1): the reference is honoured only for a decl on no index row (a helper,
        # whose R? item would count against every result). A decl on an index row goes to the RAMK row test below
        # alone: the item must name the decl or its row, so a reference to another result's item keeps it (open)
        refs = [x.upper() for x in re.findall(r"(?i)\bopen (?:K )?items? (C\??-?\d+|K3-\d+)\b", ln)]
        if not rows_ and refs and any(r_ in items and items[r_].get("open") and items[r_].get("kind") == "reading"
                                      for r_ in refs):
            continue
        key = lab or " ".join(body.split())
        if key in seen:
            continue
        seen.add(key)
        # fix round RAMK (REVIEW-RAMK-NB, K): a `reading` item that names only the decl's ROW (its label or another
        # Lean name of the row) counts as this decision's item only while it is open; a closed one may be another
        # decision's, so the R? item is kept (counted open, never hidden)
        if lab and any(lab in (it.get("results") or "") or lab in (it.get("text") or "")
                       or (it.get("open") and any(mentions(" ".join([str(it.get("results") or ""),
                                                                     str(it.get("text") or "")]), l_, ns_)
                                                  for l_, ns_ in rows_)) for it in readings):
            continue
        n += 1
        out[f"R?-{n}"] = {"id": f"R?-{n}", "kind": "reading", "results": lab, "text": f"a reading taken without a "
                          f"`reading` item in {CONDITIONS_MD}: {project.clip(ln.lstrip('- '), 160)}",
                          "source": "RUN_LOG.md", "status": "no status row", "open": True, "listed": False,
                          "why_open": "no checklist item"}
    # fix round P6 (AUDIT-P6 §2, fix 3): per round -- a round whose adjudicator wrote a `K3-<n>` row, or ruled
    # `| K3-0 | not applicable | - | <reason> |` (B'': no nontrivial REPRESENTATION note), gives no K3? item from its
    # own notes; every other round's notes are still read (before: one K3- row anywhere hid every round's)
    ruled = _k3_rounds(rd)
    k = 0
    for f in sorted(glob.glob(os.path.join(rd, "*", "correspondence*.json"))):
        if os.path.relpath(f, rd).split(os.sep)[0] in ruled:
            continue
        try:
            vs = json.load(open(f, encoding="utf-8")).get("verdicts") or []
        except (OSError, ValueError, AttributeError):
            continue
        for v in vs:
            t = " ".join(str(v.get(x, "")) for x in ("checked", "evidence")) if isinstance(v, dict) else ""
            if "REPRESENTATION:" in t and re.search(r"(?i)\bnontrivial\b", t):
                k += 1
                out[f"K3?-{k}"] = {"id": f"K3?-{k}", "kind": "bridge", "results": str(v.get("item", "")),
                                   "text": "a nontrivial change of representation a reviewer named, with no bridge "
                                           f"item: {project.clip(t[t.index('REPRESENTATION:'):], 160)}",
                                   "source": os.path.relpath(f, rd), "status": "no status row", "open": True,
                                   "listed": False, "why_open": "no K3 row"}
    # fix round P6 (AUDIT-P6 §3): an item naming a project declaration that is no longer in the Lean is listed
    # "stale, not counted" (never met, never open); an empty or unreadable declaration set keeps it open
    # Fix round P6b (REVIEW-FIXP6-NB M2, L1): K3? items only (a reading decision may still govern the paper's
    # result); a renamed or moved declaration (same fingerprint) keeps its item open, on the new name's rows
    for it in out.values():
        if it["kind"] != "bridge":
            continue
        if stale(it["results"]):
            it.update(open=False, stale=True, status=STALE_STATUS, why_open="")
        elif renamed(it["results"]):
            # on the new name's index row only when a row lists that exact name; else the old name stays (it
            # matches no row: counted against every result)
            to = renamed(it["results"])
            it["renamed_to"] = to
            if any(to in ns_ for _l, ns_ in idx):
                it.update(renamed_from=it["results"], results=to)
    return out


STALE_STATUS = "stale, not counted"


def _k3_rounds(rd):
    """{round name} whose ADOPTED.md `## Conditions` table has a `K3-<n>` row (n >= 1) or a `K3-0` row `not
    applicable` with a reason (fix round P6: B'' found no nontrivial REPRESENTATION note in that round)."""
    import decisions, hypotheses
    out = set()
    for d in hypotheses._round_dirs(rd):
        try:
            a = open(os.path.join(d, "ADOPTED.md"), encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"^## Conditions\b.*?$(.*?)(?=^## |\Z)", a, re.M | re.S)
        for h, c in decisions.table_rows(m.group(1)) if m else ():
            if not h or len(c) < 2 or h[0].strip("* ").lower() != "id":
                continue
            col = lambda n_: c[h.index(n_)].strip() if n_ in h and h.index(n_) < len(c) else ""
            i = _clean_id(col("id"))
            if not re.fullmatch(r"K3-\d+", i):
                continue
            if i != "K3-0" or (_cond_status(col("status"))[0] == "not applicable"
                               and str(col("reason")).strip("-` *")):
                out.add(os.path.basename(d))
    return out


def conditions_without_row(cfg, rd=None):
    """[id] of the checklist items of a kind the adjudicator rules (every kind but scope and known-issue, an unknown
    kind included) with no `## Conditions` status row yet (prompt.py 4 lists them; never a refusal)."""
    return [i for i, it in _items(cfg, rd).items()
            if it["status"] == "no status row" and it["kind"] not in _CONTEXT_KINDS]


def provenance_notes(cfg, rd=None):
    """[note] (code `deliver`, never a refusal): a `condition`, `scope` or `known-issue` item of CONDITIONS.md whose text
    is not found verbatim (whitespace-normalised) in RUN_LOG.md or the file its source names; every checklist item of
    a ruled kind with no status row; an unknown kind; an unparsed id; a closing status the code cannot confirm; a
    `not applicable` with no reason; every open item inferred from the record (inferred_items); and (fix round 2) a
    table whose header does not start with `id`, and a `results` entry that matches no index row."""
    rd = rd or os.path.join(project.REPO, cfg["rounds_dir"])
    norm = lambda t: " ".join(str(t).replace("“", '"').replace("”", '"').split()).strip('" ')
    try:
        log = open(os.path.join(rd, "RUN_LOG.md"), encoding="utf-8").read()
    except OSError:
        log = ""
    out = []
    allc = conditions(cfg, rd)
    for x in allc.get("_unparsed", []):     # fix round K (AUDIT-P5 §3): kept under its raw id, counted open
        out.append(f"{CONDITIONS_MD}: a row whose id is not in the C<n>/K3-<n> form ({x}): kept under that id and "
                   f"counted open (never met); write C<n>, C?-<n> or K3-<n>")
    for x in allc.get("_headers", []):      # fix round 2 (M2)
        out.append(f"a conditions table whose header does not start with `id` ({x}): its rows are read by the first "
                   f"column and its items count open (never met); write the header `| id | ...`")
    items = {k: v for k, v in allc.items() if not k.startswith("_")}
    for i, it in items.items():
        if it.get("listed") and it["kind"] in ("condition", "scope", "known-issue"):
            srcs = [log]
            for f in re.findall(r"[\w./-]+\.(?:md|txt|tex|json)", str(it.get("source") or "")):
                for base in (rd, project.REPO):
                    try:
                        srcs.append(open(os.path.join(base, f), encoding="utf-8").read())
                        break
                    except OSError:
                        continue
            t = norm(it["text"])
            if not t or not any(t in norm(x) for x in srcs):
                out.append(f"{CONDITIONS_MD} {i}: text not found in {it.get('source') or 'RUN_LOG.md'}")
        if it["kind"] not in COND_KINDS:
            out.append(f"{CONDITIONS_MD} {i}: unknown kind {it['kind']!r}")
        if it.get("why_open") and it["why_open"] != RAW_ID_WHY:     # a raw id: the note above names it
            out.append(f"{CONDITIONS_MD} {i}: counted open: {it['why_open']}")
        if it["status"] == "not applicable" and not str(it.get("reason") or "").strip("-` "):
            out.append(f"{CONDITIONS_MD} {i}: `not applicable` with no reason")
    miss = conditions_without_row(cfg, rd)
    if miss:
        out.append(f"{CONDITIONS_MD}: {len(miss)} item(s) with no `## Conditions` status row of an adjudicator yet: "
                   + ", ".join(miss))
    for i, it in inferred_items(cfg, rd, items).items():
        if it.get("stale"):     # fix round P6 (AUDIT-P6 §3)
            out.append(f"{i} names `{it['results']}`, no longer in the Lean (not in the current declaration set; "
                       f"from {it['source']}): {STALE_STATUS} (never met)")
            continue
        out.append(f"{i}: {it['text']}")
    try:        # fix round 2 (M1): an entry of a results cell that matches no index row
        idx = index_names(cfg)
    except Exception:       # noqa: BLE001 -- no index: the note is skipped
        idx = None
    for i, it in items.items() if idx is not None else ():
        if it["kind"] in _CONTEXT_KINDS:
            continue
        e = unmatched_entries(it.get("results"), idx)
        if e:
            out.append(f"{CONDITIONS_MD} {i}: results entry " + ", ".join(repr(x) for x in e) + " matches no result of "
                       "the index")
    return out


def statuses(cfg, inp=None):
    """[(label, [status])] of every index row."""
    c = ctx_of(cfg, inp)
    return [(" ".join(r[0].split()), analyse(cfg, r, c)[0]) for r in c["index"]]


def routes(cfg, inp=None):
    """[Route] of every "not established" (and open question), U2 §1's routing table."""
    c = ctx_of(cfg, inp)
    return [x for r in c["index"] for x in analyse(cfg, r, c)[1]]


def is_plain(st):
    return list(st) == [FAITHFUL]


# --- selftest --------------------------------------------------------------------------------------------
def selftest():
    import shutil, subprocess, tempfile, lanecheck
    fails = []

    def say(name, ok):
        print(("ok   " if ok else "FAIL ") + name)
        if not ok:
            fails.append(name)

    tmp = tempfile.mkdtemp(prefix="rstatus-")
    old_repo = project.REPO
    try:
        project.REPO = tmp
        import make_report
        mr_repo = make_report.REPO
        make_report.REPO = tmp
        rd = os.path.join(tmp, "audits", "P")
        os.makedirs(rd)
        cfg = {"name": "P", "namespace": "P", "rounds_dir": "audits/P", "lean_files": ["P/Main.lean"],
               "involvement": "hands-off", "mode": "release", "goal_results": ["Theorem 2.1"]}
        os.makedirs(os.path.join(tmp, "P"))
        INDEX = ("/-!\n| Paper | Lean |\n|---|---|\n| Definition 1.1 | `P.D` |\n| Lemma 1.2 | `P.lemma_1_2` |\n"
                 "| Lemma 1.3 (a) | `P.lemma_1_3_a` |\n| Lemma 1.3 (b) | `P.lemma_1_3_b` |\n"
                 "| Theorem 2.1 | `P.thm_2_1` |\n| Conjecture 3.1 | `P.conj_3_1` |\n-/\n")
        open(os.path.join(tmp, "P", "Main.lean"), "w").write(INDEX)
        subprocess.run(["git", "init", "-q", tmp]); subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "x"])
        decls = ["P.D", "P.lemma_1_2", "P.lemma_1_3_a", "P.lemma_1_3_b", "P.thm_2_1", "P.conj_3_1"]
        fp0 = {d: "a" + d for d in decls}
        deps = {"P.lemma_1_2": ["P.D"], "P.thm_2_1": ["P.D", "P.lemma_1_2"], "P.lemma_1_3_a": [], "P.lemma_1_3_b": [],
                "P.D": [], "P.conj_3_1": []}

        def mkround(name, fps, verdicts, adopted="", with_deps=True):
            d = os.path.join(rd, name)
            os.makedirs(d, exist_ok=True)
            j = {"commit": "c", "fingerprints": fps}
            if with_deps:
                j["deps"] = deps
            json.dump(j, open(os.path.join(d, "FINGERPRINTS.json"), "w"))
            json.dump({}, open(os.path.join(d, "TARGET.json"), "w"))
            for lane, vs in verdicts.items():
                json.dump({"lane": lane, "scope": [i for i, _ in vs],
                           "verdicts": [{"item": i, "verdict": v, "checked": "x"} for i, v in vs]},
                          open(os.path.join(d, lane + ".json"), "w"))
            lanecheck.fixture_rows(d, adopted)
            return d

        labels = ["Definition 1.1", "Lemma 1.2", "Lemma 1.3 (a)", "Lemma 1.3 (b)", "Theorem 2.1", "Conjecture 3.1"]

        def allpass(over=None):
            v = {"correspondence": [(d, "Pass") for d in decls], "non-vacuity": [(d, "Pass") for d in decls],
                 "paper-faithfulness": [(l, "Pass") for l in labels]}
            for lane, it, val in over or []:
                v[lane] = [(i, val if i == it else x) for i, x in v[lane]]
            return v

        def ST():
            return dict(statuses(cfg))

        # helpers: the order of rounds is by name here (no commits): project.order_rounds falls back
        def reset():
            for d in glob.glob(os.path.join(rd, "*")):
                shutil.rmtree(d) if os.path.isdir(d) else os.remove(d)

        import decisions
        dq_un, mq = decisions.unproved, make_report.open_questions
        decisions.unproved = lambda cfg_, *a, **k: {"decls": {}, "lines": {}, "goal": [], "problems": []}
        make_report.open_questions = lambda cfg_: []
        import hypotheses
        hw = hypotheses.walk
        WALK = {"assumes": {}, "walked": decls, "results": decls, "axioms": {}}
        hypotheses.walk = lambda cfg_, rd_=None: (WALK, None)
        hwp = hypotheses.walk_problem
        hypotheses.walk_problem = lambda cfg_, rd_=None: None
        try:
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            s = ST()
            say("F1 honest: every result with fresh Pass verdicts reads exactly 'faithful' (definitions included)",
                all(s[l] == [FAITHFUL] for l in labels[:5]))
            # next batch G1: the conditions checklist and the K certificate (flags only)
            open(os.path.join(rd, "RUN_LOG.md"), "w").write(
                '# log\n## Checkpoint B\n- human answer (2026-01-02): "(a) and keep the witnesses relative to the '
                'authorized inputs COND1QZ"\n')
            open(os.path.join(rd, CONDITIONS_MD), "w").write(
                "| id | kind | results | text | source |\n|---|---|---|---|---|\n"
                "| C1 | condition | Lemma 1.2 | keep the witnesses relative to the authorized inputs COND1QZ | RUN_LOG.md "
                "## Checkpoint B 2026-01-02 |\n"
                "| C2 | reading | Lemma 1.3 (a) | (b) is not covered | 2026-01-01-aaaaaaa/ADOPTED.md |\n"
                "| C3 | scope | all | only what the authors asked NOTVERBATIMQZ | RUN_LOG.md |\n")
            open(os.path.join(rd, "2026-01-01-aaaaaaa", "ADOPTED.md"), "a").write(
                "\n## Conditions\n\n| id | status | evidence | reason |\n|---|---|---|---|\n"
                "| C1 | open | - | not yet |\n| C1 | met | `P.lemma_1_2` | checked: relative inputs |\n"
                "| K3-1 | open | - | bridge: the quotient is the paper's metric identification; serves Lemma 1.2 |\n"
                "| C?-1 | open | - | not in CONDITIONS.md: \"use Theorem 2.1 as printed\"; RUN_LOG ## Answered |\n"
                "| C9 | bogus | - | unknown status reads open (Conjecture 3.1) |\n")
            cd_ = conditions(cfg)
            pn_ = provenance_notes(cfg)
            say("next batch G1: conditions() = CONDITIONS.md ∪ ids first seen in a `## Conditions` row (K3-<n>, C?-<n>); "
                "the latest row wins; an unknown status reads open; a listed item with no row is open",
                set(cd_) == {"C1", "C2", "C3", "K3-1", "C?-1", "C9"} and cd_["C1"]["status"] == "met"
                and not cd_["C1"]["open"] and cd_["C2"]["status"] == "no status row" and cd_["C2"]["open"]
                and cd_["K3-1"]["kind"] == "bridge" and cd_["C?-1"]["kind"] == "condition"
                and cd_["C9"]["status"] == "open" and cd_["C9"]["open"])
            say("next batch G1: a provenance NOTE names a condition/scope item whose text is not verbatim in RUN_LOG.md "
                "(never one that is), and the items with no status row",
                any(x.startswith("CONDITIONS.md C3: text not found") for x in pn_)
                and not any(x.startswith("CONDITIONS.md C1:") for x in pn_)
                and any("no `## Conditions` status row" in x and "C2" in x for x in pn_)
                and conditions_without_row(cfg) == ["C2"])
            # fix round 1 (attack review 2-6): what the code cannot match, parse or confirm counts as OPEN
            adp = os.path.join(rd, "2026-01-01-aaaaaaa", "ADOPTED.md")
            ad0 = open(adp).read()
            open(adp, "a").write("| K3-2 | open | - | bridge: `P.quot_equiv` (the quotient); serves Theorem 1 |\n"
                                 "| C1 | met only for part (a) | `P.lemma_1_2` | partly |\n"
                                 "| C?-1 | not applicable — now C8 | - | added as C8 |\n"
                                 "| **K3-3a** | open | - | malformed id |\n")
            open(os.path.join(rd, CONDITIONS_MD), "a").write("| C5 | requirement | Lemma 1.3 (b) | must be constructive | "
                                                             "RUN_LOG.md |\n| C6 | condition | Thm 9.9 | mistyped "
                                                             "results cell | RUN_LOG.md |\n")
            cd2 = conditions(cfg)
            pn3 = provenance_notes(cfg)
            say("fix round 1 (attack 2): an open item that attaches to no result (a bridge naming `Theorem 1`, a "
                "mistyped results cell) stays open, never dropped, and the mistyped cell is noted (K-REMOVE: the "
                "agent judges which results it affects)",
                cd2["K3-2"]["open"] and cd2["C6"]["open"]
                and any("C6: results entry 'Thm 9.9' matches no result" in x for x in pn3))
            say("fix round 1 (attack 3, 4): an unknown kind is noted; a malformed id is noted; a status "
                "read by exact word ('met only for part (a)' is open); 'not applicable — now C8' with no C8 stays open",
                any("unknown kind 'requirement'" in x for x in pn3)
                and any("not in the C<n>/K3-<n> form" in x and "K3-3a" in x and "counted open" in x for x in pn3)
                and (cd2.get("K3-3a") or {}).get("open") and (cd2.get("K3-3a") or {}).get("why_open") == RAW_ID_WHY
                and cd2["C1"]["status"] == "open" and cd2["C?-1"]["open"]
                and any("C8 is not in CONDITIONS.md" in x for x in pn3)
                and _cond_status("met — `P.x`") == ("met", "p.x") and _cond_status("metric pending")[0] == "open"
                and _cond_status("Met?")[0] == "open")
            open(adp, "w").write(ad0 + "| C1 | met | - | no evidence |\n")
            say("fix round 1 (attack 4): `met` with no evidence stays open, with a note",
                conditions(cfg)["C1"]["open"] and any("C1: counted open: `met` without evidence" in x
                                                      for x in provenance_notes(cfg)))
            open(adp, "w").write(ad0)
            open(os.path.join(rd, CONDITIONS_MD), "w").write("| id | kind | results | text | source |\n|---|---|---|---|---|\n")
            open(os.path.join(rd, "RUN_LOG.md"), "a").write(
                "## Open questions\n- [DELEGATED 2026-01-03, operator under hands-off (intake); reversal: re-approve] "
                "keep it (QUESTION row on Lemma 1.2, round 2026-01-01-aaaaaaa) take reading (a) — r\n")
            inf6 = inferred_items(cfg, rd, _items(cfg, rd))
            say("fix round 1 (attack 5): a delegated reading with no `reading` item is an inferred open item (R?-1), "
                "noted for the agent",
                list(inf6) == ["R?-1"] and inf6["R?-1"]["open"]
                and any(x.startswith("R?-1:") for x in provenance_notes(cfg)))
            # fix round 2 (REVIEW-FIX1-NB M1): a results cell with ANY entry matching no index row counts against
            # every result, with a note naming the entry
            cmd_ = os.path.join(rd, CONDITIONS_MD)
            hdr_ = "| id | kind | results | text | source |\n|---|---|---|---|---|\n"
            open(cmd_, "w").write(hdr_ + "| C7 | condition | Lemma 1.2, Thm 2.1 | partly mistyped | RUN_LOG.md |\n")
            pn7 = provenance_notes(cfg)
            open(cmd_, "w").write(hdr_ + "| C7 | condition | Lemma 1.2 and Theorem 2.1 | typed right | RUN_LOG.md |\n")
            pn7b = provenance_notes(cfg)
            say("fix round 2 (M1): a note names the entry 'Thm 2.1' of `Lemma 1.2, Thm 2.1` that matches no result; a "
                "cell whose entries all match gives no such note",
                any("C7: results entry 'Thm 2.1' matches no result" in x for x in pn7)
                and not any("C7: results entry" in x for x in pn7b)
                and unmatched_entries("Lemma 1.3 (a) and (b)", [("Lemma 1.3 (a)", []), ("Lemma 1.3 (b)", [])]) == []
                and unmatched_entries("all", []) == [])
            # fix round 2 (M2): a table whose header does not start with `id` is noted and its items count open
            open(cmd_, "w").write("| item | kind | results | text | source |\n|---|---|---|---|---|\n"
                                  "| C1 | condition | Lemma 1.3 (b) | a | RUN_LOG.md |\n")
            cd8, pn8 = conditions(cfg), provenance_notes(cfg)
            open(cmd_, "w").write(hdr_)
            open(adp, "w").write(ad0.replace("| id | status | evidence | reason |", "| item | status | evidence | reason |"))
            cd9, pn9 = conditions(cfg), provenance_notes(cfg)
            open(adp, "w").write(ad0)
            say("fix round 2 (M2): a CONDITIONS.md or `## Conditions` table headed `item` is noted, its rows are read "
                "by the first column and count open (a `met` row too)",
                cd8["C1"]["open"]
                and any("header does not start with `id`" in x and "CONDITIONS.md: 'item'" in x for x in pn8)
                and (cd9.get("K3-1") or {}).get("open") and (cd9.get("C1") or {}).get("open")
                and any("header does not start with `id`" in x and "ADOPTED.md ## Conditions" in x for x in pn9))
            os.remove(os.path.join(rd, CONDITIONS_MD)); os.remove(os.path.join(rd, "RUN_LOG.md"))
            say("a conjecture reads 'stated only', with its statement checked faithful, never plain faithful",
                s["Conjecture 3.1"] == ["stated only (a conjecture: stated as a proposition, asserted nowhere; its "
                                        "statement checked faithful)"])
            # E2E-FIX2 M1 (the e2e run's "Problem 6.4" row had no status at all): a Problem row gets a status from
            # its own verdicts, like any result -- faithful on fresh Passes, never by default
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(INDEX.replace("-/\n", "| Problem 6.4 | `P.conj_3_1` |\n-/\n"))
            _v = allpass()
            _v["paper-faithfulness"].append(("Problem 6.4", "Pass"))
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, _v)
            s_p = ST()
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            s_q = ST()
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(INDEX)
            say("E2E-FIX2 M1: a Problem row has a status: faithful on fresh Passes, not established with no "
                "paper-faithfulness verdict on it",
                s_p.get("Problem 6.4") == [FAITHFUL] and "Problem 6.4" in s_q
                and any("no paper-faithfulness verdict on Problem 6.4" in x for x in s_q["Problem 6.4"]))
            # mutant target: faithful by default -- no verdict at all
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, {"correspondence": [(d, "Pass") for d in decls]})
            s = ST()
            say("no paper-faithfulness / non-vacuity verdict -> not established (unverified), never faithful",
                any("no paper-faithfulness verdict on Lemma 1.2" in x for x in s["Lemma 1.2"])
                and any("no non-vacuity verdict" in x for x in s["Lemma 1.2"]) and FAITHFUL not in s["Lemma 1.2"])
            say("routes: a missing verdict goes to `unverified`",
                {r.code for r in routes(cfg) if r.result == "Lemma 1.2"} == {"unverified"})
            # Codex e2e (minipaper3, TP2): a stated-only conjecture's non-vacuity NotDoneYet, adjudicated UNCOVERED,
            # is no verdict -- its statement is not "checked faithful" and a full round is asked for (lane D rule 5b
            # says what that round's Pass is); the next round's Pass settles it
            reset()
            unc = "| non-vacuity | P.conj_3_1 | NotDoneYet | **UNCOVERED** | no witness of the proposition |\n"
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("non-vacuity", "P.conj_3_1", "NotDoneYet")]), unc)
            mkround("2026-01-02-bbbbbbb", fp0, allpass([("non-vacuity", "P.conj_3_1", "NotDoneYet")]), unc)
            s_c, r_c = ST()["Conjecture 3.1"], {r.code for r in routes(cfg) if r.result == "Conjecture 3.1"}
            mkround("2026-01-03-ccccccc", fp0, allpass())
            say("a conjecture's non-vacuity NotDoneYet (UNCOVERED) is no verdict: not established, `unverified`; a "
                "later Pass settles it",
                s_c == ["stated only (a conjecture: stated as a proposition, asserted nowhere)",
                        "not established: no non-vacuity verdict on `P.conj_3_1`"] and r_c == {"unverified"}
                and ST()["Conjecture 3.1"] == ["stated only (a conjecture: stated as a proposition, asserted nowhere; "
                                               "its statement checked faithful)"])
            # paper-faithfulness Fail + correspondence Pass != faithful (U §13 B9)
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Lemma 1.2", "Fail")]),
                    "| paper-faithfulness | Lemma 1.2 | Fail | **QUESTION** — which reading | x |\n")
            s = ST()
            say("paper-faithfulness Fail + correspondence Pass is not faithful (routed to the adjudicator)",
                s["Lemma 1.2"][0].startswith("not established: paper-faithfulness Fail on Lemma 1.2")
                and any(r.code == "adj-record" for r in routes(cfg) if r.result == "Lemma 1.2"))
            say("a Fail on a lemma stays with the lemma: the theorem using it (not a Definition row) is untouched",
                s["Theorem 2.1"] == [FAITHFUL] and s["Lemma 1.3 (a)"] == [FAITHFUL])
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Definition 1.1", "Fail")]))
            s = ST()
            say("closure: a Fail on Definition 1.1 reaches Lemma 1.2 and Theorem 2.1 (they use it), not Lemma 1.3",
                any("Definition 1.1 (used by it)" in x for x in s["Lemma 1.2"])
                and any("Definition 1.1 (used by it)" in x for x in s["Theorem 2.1"]) and s["Lemma 1.3 (b)"] == [FAITHFUL])
            # a REJECTed Fail is answered
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("correspondence", "P.lemma_1_2", "Fail")]),
                    "| correspondence | P.lemma_1_2 | Fail | **REJECT** — the lane misread | x |\n")
            say("a Fail the adjudicator REJECTed does not stand between the result and faithful",
                ST()["Lemma 1.2"] == [FAITHFUL])
            # stale verdict: the result changed after its last Pass (diff round leaving others unchanged)
            reset()
            fp1 = dict(fp0, **{"P.lemma_1_3_b": "changed"})
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            mkround("2026-01-02-bbbbbbb", fp1, {"correspondence": [("P.lemma_1_3_b", "Pass")]})
            s = ST()
            say("a Pass from before the result's last change is stale -> not established (out of date)",
                any("paper-faithfulness verdict on Lemma 1.3 (b) (round 2026-01-01-aaaaaaa) is out of date" in x
                    for x in s["Lemma 1.3 (b)"]))
            say("a diff round leaving other results unchanged keeps their earlier Passes current",
                s["Lemma 1.3 (a)"] == [FAITHFUL] and s["Theorem 2.1"] == [FAITHFUL])
            # A -> B -> A: the first A-round's Pass is not about the current version after a change in between
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            mkround("2026-01-02-bbbbbbb", fp1, {"correspondence": [("P.lemma_1_2", "Pass")]})
            mkround("2026-01-03-ccccccc", fp0, {"correspondence": [("P.lemma_1_3_b", "Pass")]})
            say("a fingerprint changed and changed back: the verdict before the change is stale",
                any("out of date" in x for x in ST()["Lemma 1.3 (b)"]))
            # NotDoneYet is not a verdict: the earlier fresh Pass stands
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            mkround("2026-01-02-bbbbbbb", fp0, {"paper-faithfulness": [("Lemma 1.2", "NotDoneYet")]})
            say("a NotDoneYet in a later round leaves the fresh Pass standing",
                ST()["Lemma 1.2"] == [FAITHFUL])
            # defect rows: false + typo, as repaired; unsupported
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Lemma 1.2", "Fail")]),
                    "| paper-faithfulness | Lemma 1.2 | Fail | **ADOPT** — paper defect | x |\n")
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
                "## Defects\n\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
                "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
                "| 1 | Lemma 1.2, tex l.3 | false | typo | x | counterexample: n = 2 | `P.not_lemma_1_2_as_printed` | none | fixed | r |\n"
                "| 2 | Lemma 1.3 (a) | unsupported | none (intent unknown) | x | y | `P.lemma_1_3_a` | z | d | r |\n")
            s = ST()
            say("a false row with a typo repair reads 'false as printed; proved as repaired' with its witness, the "
                "adopted Fail answered by the row",
                s["Lemma 1.2"] == ["defect 1: false; typo — false as printed; proved as repaired (witness "
                                   "`P.not_lemma_1_2_as_printed`)"])
            say("an unsupported defect reads its status (U §13: unsupported defect), never faithful",
                s["Lemma 1.3 (a)"][0].startswith("defect 2: unsupported; none (intent unknown) — the paper's argument "
                                                  "does not establish it; proved here") and FAITHFUL not in s["Lemma 1.3 (a)"])
            say("part-aware: the row of Lemma 1.3 (a) does not reach Lemma 1.3 (b)", s["Lemma 1.3 (b)"] == [FAITHFUL])
            # mutant target: a defect row yields faithful
            say("a defect row never yields plain faithful", not any(is_plain(v) for k, v in s.items()
                                                                    if k in ("Lemma 1.2", "Lemma 1.3 (a)")))
            # an ADOPTed Fail with no record naming the result stands
            os.remove(os.path.join(rd, "PAPER_DEFECTS.md"))
            say("an ADOPTed Fail with no record naming the result: not established (adjudicator)",
                ST()["Lemma 1.2"] == ["not established: paper-faithfulness Fail on Lemma 1.2 (round "
                                      "2026-01-01-aaaaaaa; decision: ADOPT)"])
            # approver 2026-10-24 (decision 3): the statement-round cap was reached with this finding open and the
            # run went on (scope.cap_record): it reads "not established: open faithfulness finding", route round-cap
            # (disclosed on the summary, no adj-record delivery block)
            os.makedirs(os.path.join(rd, "round-caps"))
            json.dump({"round": "2026-01-01-aaaaaaa", "open": ["paper-faithfulness :: lemma 1.2"]},
                      open(os.path.join(rd, "round-caps", "2026-01-01-aaaaaaa.json"), "w"))
            s_cap = ST()["Lemma 1.2"]
            r_cap = {r.code for r in routes(cfg) if r.result == "Lemma 1.2"}
            shutil.rmtree(os.path.join(rd, "round-caps"))
            say("a finding the statement-round cap left open reads 'not established: open faithfulness finding' "
                "(route round-cap, never adj-record); without the cap record it is the adjudicator's again",
                len(s_cap) == 1 and s_cap[0].startswith("not established: open faithfulness finding: paper-faithfulness "
                                                        "Fail on Lemma 1.2") and r_cap == {"round-cap"}
                and ST()["Lemma 1.2"][0].endswith("decision: ADOPT)"))
            # operator's DEVIATIONS rows never clear a Fail by themselves
            open(os.path.join(rd, "DEVIATIONS.md"), "w").write(
                "| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
                "| 1 | Lemma 1.2 | reading A | reading B | ambiguous | reading choice |\n")
            s = ST()["Lemma 1.2"]
            say("a reading-choice row (the operator's) does not clear a Fail: not established, the reading listed "
                "as a choice, never 'faithful under reading'",
                s[0].startswith("not established") and s[-1].startswith("reading choice 1:")
                and not any(x.startswith("faithful") for x in s))
            # approver 2026-10-24, round-cap outcome (b): a loose convention at the statement-round cap -- the operator
            # took the intended reading (its reading-choice row) and went on; the cap recorded the finding open. The
            # result says both, and nothing blocks delivery (route round-cap, never adj-record)
            os.makedirs(os.path.join(rd, "round-caps"))
            json.dump({"round": "2026-01-01-aaaaaaa", "open": ["paper-faithfulness :: lemma 1.2"]},
                      open(os.path.join(rd, "round-caps", "2026-01-01-aaaaaaa.json"), "w"))
            s_b = ST()["Lemma 1.2"]
            r_b = {r.code for r in routes(cfg) if r.result == "Lemma 1.2"}
            shutil.rmtree(os.path.join(rd, "round-caps"))
            say("round-cap outcome (b), a convention decided at the cap: 'not established: open faithfulness finding' "
                "and the reading choice listed, route round-cap only (disclosed, no delivery block), never faithful",
                s_b[0].startswith("not established: open faithfulness finding") and s_b[-1].startswith("reading choice 1:")
                and r_b == {"round-cap"} and not any(x.startswith("faithful") for x in s_b))
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Lemma 1.2", "Ambiguous")]),
                    "| paper-faithfulness | Lemma 1.2 | Ambiguous | **ADOPT** — reading B | x |\n")
            open(os.path.join(rd, "DEVIATIONS.md"), "w").write(
                "| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
                "| 1 | Lemma 1.2 | reading A | reading B | ambiguous | reading choice |\n")
            s = ST()["Lemma 1.2"]
            say("an adopted Ambiguous with its reading-choice row reads 'faithful under reading', never plain (F8)",
                s == ["faithful under reading 1: reading B (alternative: reading A)"])
            open(os.path.join(rd, "DEVIATIONS.md"), "w").write(
                "| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
                "| 1 | Lemma 1.2 | reading A | reading B | ambiguous | reading choice |\n"
                "| 2 | Lemma 1.3 (a) | x | y | ℕ subtraction cannot be avoided | differs |\n")
            s = ST()
            say("an accepted deviation (DEVIATIONS kind `differs`) reads 'differs', never faithful",
                s["Lemma 1.3 (a)"] == ["differs (DEVIATIONS row 2): ℕ subtraction cannot be avoided"])
            os.remove(os.path.join(rd, "DEVIATIONS.md"))
            # a benchmark run: a non-vacuity Ambiguous (closed by a library lemma) whose QUESTION row
            # says the Lean takes (a), answered "reading (a)" by a final [DELEGATED] decision: settled by the Lean as it
            # stands -- "faithful under reading (a)", no route; an answer taking the other reading, or none, settles nothing
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("non-vacuity", "P.lemma_1_2", "Ambiguous")]),
                    "| non-vacuity | P.lemma_1_2 | Ambiguous | **QUESTION** | Reading (a): acceptable, exactly the "
                    "paper's statement. Reading (b): a trivial stand-in. The Lean takes (a). Recommended: (a). |\n")

            def ans(words):
                open(os.path.join(rd, "RUN_LOG.md"), "w").write(
                    "# Run log\n\n## Open questions\n\n" + (f"- [DELEGATED 2026-01-01, operator under hands-off "
                    f"(intake); reversal: none] keep lemma_1_2 as stated ({words}) (QUESTION row on P.lemma_1_2, round "
                    "2026-01-01-aaaaaaa) -- follows the adjudicator's recommendation.\n" if words else ""))
                return ST()["Lemma 1.2"], {r.code for r in routes(cfg) if r.result == "Lemma 1.2"}
            s_a, r_a = ans("reading (a)")
            s_b, r_b = ans("reading (b)")
            s_n, r_n = ans("")
            say("B9: an Ambiguous whose answered QUESTION keeps the reading the Lean takes reads 'faithful under "
                "reading (a)', no route; answered with the other reading, or unanswered in the log, not established",
                s_a == ["faithful under reading (a) of the non-vacuity question on `P.lemma_1_2` (round 2026-01-01-aaaaaaa): "
                        "the reading the Lean takes, kept by a delegated decision of the operator"] and r_a == set()
                and s_b[0].startswith("not established: non-vacuity Ambiguous") and r_b == {"adj-record"}
                and s_n[0].startswith("not established: non-vacuity Ambiguous") and r_n == {"adj-record"})
            os.remove(os.path.join(rd, "RUN_LOG.md"))
            # B1 (MAINTAINING L5): a row its round's adjudicator decided never scopes a round (route `decided`, code
            # adj-record, the status text unchanged, nothing in make_report.pending_adjudication); a verdict with no
            # decision row, or one item of it undecided, or an open re-vote of it, stays the adjudicator's (pending)
            pf_, ar_, rc_ = decisions.pending_refusal, make_report.adjudication_findings, make_report.route_changes_pending
            decisions.pending_refusal = lambda cfg_: None
            make_report.adjudication_findings = lambda cfg_, *a, **k: []
            make_report.route_changes_pending = lambda cfg_: []
            orv = decisions.open_revotes
            try:
                def RT(label):
                    return sorted((r.route, r.code) for r in routes(cfg) if r.result == label)

                def PEND():
                    return [t for _c, t in make_report.pending_adjudication(cfg)]
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("correspondence", "P.lemma_1_2", "Fail")]),
                        "| correspondence | P.lemma_1_2 | Fail | **ADOPT** — fix the docstring | x |\n")
                s1, r1, p1 = ST()["Lemma 1.2"], RT("Lemma 1.2"), PEND()
                say("B1 u1: an ADOPTed Fail with no record: route `decided` (code adj-record), the status exactly as "
                    "before, and nothing pending the next adjudication",
                    s1 == ["not established: correspondence Fail on `P.lemma_1_2` (round 2026-01-01-aaaaaaa; decision: "
                           "ADOPT)"] and r1 == [("decided", "adj-record")] and p1 == [])
                # review M1/L4: decided ADOPTs are delivery notes (never refusals): one line naming the results, and
                # an ADOPT with no OUTCOMES row or "implemented" with no Lean commit behind it
                n_none = [t for _c, t in make_report.decided_notes(cfg)]
                open(os.path.join(tmp, "P", "Main.lean"), "a").write("namespace P\ntheorem lemma_1_2 : True := trivial\nend P\n")
                subprocess.run(["git", "-C", tmp, "add", "-A", "P"], capture_output=True)
                subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "decl"],
                               capture_output=True)
                h0 = subprocess.run(["git", "-C", tmp, "rev-parse", "--short=7", "HEAD"], capture_output=True,
                                    text=True).stdout.strip()
                reset()
                rn = f"2026-01-01-{h0}"
                mkround(rn, fp0, allpass([("correspondence", "P.lemma_1_2", "Fail")]),
                        "| correspondence | P.lemma_1_2 | Fail | **ADOPT** — fix the docstring | x |\n")
                open(os.path.join(rd, rn, "OUTCOMES.md"), "w").write(
                    "| lane | item | outcome | note |\n|---|---|---|---|\n"
                    "| correspondence@3 | `P.lemma_1_2` | implemented as described | docstring |\n")
                n_nocommit = [t for _c, t in make_report.decided_notes(cfg)]
                open(os.path.join(tmp, "P", "Main.lean"), "a").write("-- docstring fix\n")
                subprocess.run(["git", "-C", tmp, "add", "-A", "P"], capture_output=True)
                subprocess.run(["git", "-C", tmp, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "doc"],
                               capture_output=True)
                n_commit = [t for _c, t in make_report.decided_notes(cfg)]
                say("B1 (review M1, L4): a decided ADOPT gives notes only: the results line always; no OUTCOMES row -> "
                    "a note; 'implemented' with no Lean commit after its round -> a note; with one -> none",
                    any("no OUTCOMES.md row" in t for t in n_none) and any("only because of rows" in t and "Lemma 1.2" in t
                                                                           for t in n_none)
                    and any("no Lean commit after round" in t for t in n_nocommit)
                    and not any("no Lean commit" in t or "no OUTCOMES" in t for t in n_commit)
                    and any("only because of rows" in t for t in n_commit)
                    and all(c_ == "deliver" for c_, _t in make_report.decided_notes(cfg)))
                # review M9 3: a decided ADOPT, then a real statement change (a new snapshot, its fingerprint changed):
                # the verdict is out of date (`unverified`, never `decided`) -- delivery and scope see it as unreviewed
                mkround("2026-01-03-ccccccc", dict(fp0, **{"P.lemma_1_2": "changed"}), {})
                r_ch = RT("Lemma 1.2")
                say("B1 (review M9 3): a decided ADOPT followed by a statement change is `unverified`, not `decided`",
                    ("unverified", "unverified") in r_ch and not any(r_[0] == "decided" for r_ in r_ch))
                for dw in ("DEFER", "QUESTION"):
                    reset()
                    mkround("2026-01-01-aaaaaaa", fp0, allpass([("correspondence", "P.lemma_1_2", "Fail")]),
                            f"| correspondence | P.lemma_1_2 | Fail | **{dw}** — x | x |\n")
                    say(f"B1 u1: a {dw} row (answered) decides it too: route `decided`, nothing pending",
                        RT("Lemma 1.2") == [("decided", "adj-record")] and PEND() == [])
                    if dw == "QUESTION":
                        # attack review L4: an answered QUESTION with no Lean commit after its round is a note; the
                        # delivery check prints the decided rows' notes as NOTE lines, never "NOT deliverable"
                        # (compatibility review L3)
                        import io, contextlib
                        n_q = [t for _c, t in make_report.decided_notes(cfg)]
                        dp_ = make_report.delivery_problems
                        make_report.delivery_problems = lambda cfg_, inp_=None: make_report.decided_notes(cfg_, inp_)
                        buf = io.StringIO()
                        try:
                            with contextlib.redirect_stdout(buf):
                                rc_dc = make_report.delivery_check(cfg)
                        finally:
                            make_report.delivery_problems = dp_
                        say("B1 (attack review L4, compatibility review L3): an answered QUESTION with no Lean commit "
                            "after its round gives a note; the delivery check prints decided rows' notes as NOTE and "
                            "exits 0",
                            any("was answered, and no Lean commit after round" in t for t in n_q) and rc_dc == 0
                            and "NOT deliverable" not in buf.getvalue() and "NOTE[deliver]" in buf.getvalue()
                            and "RED[" not in buf.getvalue())
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("correspondence", "P.lemma_1_2", "Fail")]))
                say("B1 u2: a Fail with no decision row stays the adjudicator's, and pending_adjudication lists it",
                    RT("Lemma 1.2") == [("adjudicator", "adj-record")] and len(PEND()) == 1
                    and "decision: none recorded" in PEND()[0])
                # review MEDIUM-3: a decided Fail on part (a) does not hide an undecided Ambiguous on part (b) of the
                # same round: the adjudicator's (pending); with both decided, `decided`
                for rows_, want in (("| paper-faithfulness | Lemma 1.2 (a) | Fail | **ADOPT** — x | x |\n", "adjudicator"),
                                    ("| paper-faithfulness | Lemma 1.2 (a) | Fail | **ADOPT** — x | x |\n"
                                     "| paper-faithfulness | Lemma 1.2 (b) | Ambiguous | **DEFER** — x | x |\n", "decided")):
                    reset()
                    _v = allpass()
                    _v["paper-faithfulness"] = [x for x in _v["paper-faithfulness"] if x[0] != "Lemma 1.2"] + [
                        ("Lemma 1.2 (a)", "Fail"), ("Lemma 1.2 (b)", "Ambiguous")]
                    mkround("2026-01-01-aaaaaaa", fp0, _v, rows_)
                    r_p, p_p = RT("Lemma 1.2"), PEND()
                    say(f"B1 (review MEDIUM-3): Fail on (a) ADOPTed, Ambiguous on (b) "
                        f"{'undecided' if want == 'adjudicator' else 'DEFERred'}: route `{want}`",
                        r_p == [(want, "adj-record")] and (len(p_p) == 1) == (want == "adjudicator"))
                # M2: one item of the verdict undecided -> the adjudicator's (_route reads every item, not the first)
                c_ = {"dec": {"R": {"correspondence :: x": "ADOPT"}}, "revotes": set(), "questions": [],
                      "problems_q": False}
                r_one = _route(c_, "R", "correspondence", ["x", "y"], "Lemma 9.9", ["P.x"], "ADOPT")
                c_["dec"]["R"]["correspondence :: y"] = "DEFER"
                r_both = _route(c_, "R", "correspondence", ["x", "y"], "Lemma 9.9", ["P.x"], "ADOPT")
                say("B1 (review M2): a verdict with two items, one undecided, stays `adjudicator`; with both decided "
                    "it is `decided`", r_one == "adjudicator" and r_both == "decided")
                # M2: an open re-vote of the item (correspondence@2 REVOTE NEEDED beside correspondence@7 ADOPT)
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("correspondence", "P.lemma_1_2", "Fail")]),
                        "| correspondence | P.lemma_1_2 | Fail | **ADOPT** — x | x |\n")
                decisions.open_revotes = lambda rounds_: [("2026-01-01-aaaaaaa", "correspondence@2", "P.lemma_1_2",
                                                           "a second look", False)]
                r_rv, p_rv = RT("Lemma 1.2"), PEND()
                decisions.open_revotes = lambda rounds_: 1 / 0
                r_err = RT("Lemma 1.2")
                decisions.open_revotes = orv
                say("B1 (review M2): an open re-vote of the item keeps it the adjudicator's (pending), whatever the "
                    "other row says; the re-votes unreadable: the adjudicator's too",
                    r_rv == [("adjudicator", "adj-record")] and len(p_rv) == 1 and r_err == [("adjudicator", "adj-record")])
                # u3: an Ambiguous QUESTION: unanswered -> question; answered (a reading reading_answer cannot read) ->
                # decided; the open questions unreadable -> never decided
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Lemma 1.2", "Ambiguous")]),
                        "| paper-faithfulness | Lemma 1.2 | Ambiguous | **QUESTION** | which reading |\n")
                make_report.open_questions = lambda cfg_: [("2026-01-01-aaaaaaa", "paper-faithfulness", "Lemma 1.2",
                                                            "which reading", "")]
                r_open = {r.route for r in routes(cfg) if r.result == "Lemma 1.2"}
                make_report.open_questions = lambda cfg_: []
                r_ans, p_ans = RT("Lemma 1.2"), PEND()

                def boom(cfg_):
                    raise OSError("unreadable")
                make_report.open_questions = boom
                r_boom = {r.route for r in routes(cfg) if r.result == "Lemma 1.2"}
                make_report.open_questions = lambda cfg_: []
                say("B1 u3: an unanswered QUESTION is the human's (`question`), answered it is `decided` (nothing "
                    "pending); with the open questions unreadable it is never `decided` (the adjudicator's, plus "
                    "status-unmapped)", r_open == {"question"} and r_ans == [("decided", "adj-record")] and p_ans == []
                    and "decided" not in r_boom and "adjudicator" in r_boom and "unmapped" in r_boom)
                # u4: Definition rows the result uses follow the same rule; a REJECT still gives nothing
                for dw, want in (("ADOPT", "decided"), ("", "adjudicator"), ("REJECT", None)):
                    reset()
                    mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Definition 1.1", "Fail")]),
                            f"| paper-faithfulness | Definition 1.1 | Fail | **{dw}** — x | x |\n" if dw else "")
                    got_ = {r.route for r in routes(cfg) if r.result == "Theorem 2.1"}
                    say(f"B1 u4: a Definition row's Fail decided {dw or 'by no row'}: its users' route is {want}",
                        got_ == ({want} if want else set()))
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Definition 1.1", "Ambiguous")]),
                        "| paper-faithfulness | Definition 1.1 | Ambiguous | **QUESTION** | which reading |\n")
                make_report.open_questions = lambda cfg_: [("2026-01-01-aaaaaaa", "paper-faithfulness",
                                                            "Definition 1.1", "which reading", "")]
                r_dq = {r.route for r in routes(cfg) if r.result == "Theorem 2.1"}
                make_report.open_questions = lambda cfg_: []
                r_da = {r.route for r in routes(cfg) if r.result == "Theorem 2.1"}
                say("B1 u4: a Definition's QUESTION unanswered gives its users `question` (the human's, as the "
                    "definition's own row; no round); answered, `decided`", r_dq == {"question"} and r_da == {"decided"})
                # u6: a `## Hypotheses` row saying `no` is a decision; a missing row is the adjudicator's
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass())
                WALK["assumes"] = {"P.thm_2_1": [{"name": "P.H", "binder": "hH", "kind": "prop", "type_pp": "P.H n",
                                                  "embedded": False}]}
                cfg["literature_hypotheses"] = [{"lean": "P.H", "paper": "[K, Thm 1]"}]
                hl_ = hypotheses.latest
                try:
                    r_none = RT("Theorem 2.1")
                    hypotheses.latest = lambda cfg_, rd_=None: {"P.H": ("r", 1, {"matches source": "no"}, None)}
                    r_no, p_no = RT("Theorem 2.1"), PEND()
                finally:
                    hypotheses.latest = hl_
                    del cfg["literature_hypotheses"]
                    WALK["assumes"] = {}
                say("B1 u6: a hypothesis row saying `no` is `decided` (nothing pending); no valid row is the "
                    "adjudicator's", r_no == [("decided", "adj-record")] and p_no == []
                    and r_none == [("adjudicator", "adj-record")])
            finally:
                decisions.pending_refusal, make_report.adjudication_findings = pf_, ar_
                make_report.route_changes_pending, decisions.open_revotes = rc_, orv
                make_report.open_questions = lambda cfg_: []
            # A5: the reading decision, end to end. A row writing everything in its decision cell (a real run did), a
            # bare label after the Lean's code span and file range (a Mac run), the prescribed token, "keep the Lean's
            # reading", and an answer taking the other reading (a status reason and a delivery note, review M3)
            def a5(dcell, rcell, words):
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("non-vacuity", "P.lemma_1_2", "Ambiguous")]),
                        f"| non-vacuity | P.lemma_1_2 | Ambiguous | {dcell} | {rcell} |\n")
                open(os.path.join(rd, "RUN_LOG.md"), "w").write(
                    "# Run log\n\n## Open questions\n\n- [DELEGATED 2026-01-01, operator under hands-off (intake); "
                    f"reversal: none] keep lemma_1_2 as stated ({words}) (QUESTION row on P.lemma_1_2, round "
                    "2026-01-01-aaaaaaa) -- follows the adjudicator's recommendation.\n")
                st_ = ST()["Lemma 1.2"]
                notes_ = [t for _c, t in make_report.decided_notes(cfg)]
                os.remove(os.path.join(rd, "RUN_LOG.md"))
                return st_, notes_
            F = "faithful under reading ({}) of the non-vacuity question on `P.lemma_1_2` (round 2026-01-01-aaaaaaa)"
            s_dc, _n = a5("**QUESTION** — Source: either. The Lean (`lemma_1_2`, Main.lean:3, `sInf` for min) takes (a). "
                          "Recommended: (a).", "see the decision", "keep reading (a)")
            s_mac, _n = a5("**QUESTION**", "Reading A: sufficiency; reading B: necessity. The Lean `P.lemma_1_2` "
                           "(Main.lean:3-5) takes A", "reading A (sufficiency)")
            s_tok, _n = a5("**QUESTION**", "Reading (a) the paper's; (b) a stand-in. [Lean: (A), Recommended: (B)]",
                           "keep the Lean's reading")
            s_oth, n_oth = a5("**QUESTION**", "Two readings. [Lean: (a); recommended: (b)]", "take reading (b)")
            s_sch, _n = a5("**QUESTION**", "The Lean takes (b).", "keep reading (ii)")
            s_h2, _n = a5("**QUESTION**", "Readings: (a) A finite; (b) A arbitrary. The Lean takes A arbitrary, i.e. (b). "
                          "Recommended: (a).", "keep reading (a)")
            s_nl, _n = a5("**QUESTION**", "The Lean takes (a).", "keep it as stated")
            say("A5: the Lean's reading read from the decision cell, after a code span and file range, from the token "
                "(any case, a comma), and 'keep the Lean's reading' with a one-label row: 'faithful under reading'",
                s_dc == [F.format("a") + ": the reading the Lean takes, kept by a delegated decision of the operator"]
                and s_mac == [F.format("a") + ": the reading the Lean takes, kept by a delegated decision of the operator"]
                and s_tok == [F.format("a") + ": the reading the Lean takes, kept by a delegated decision of the operator"])
            say("A5 (review M3): an answer taking the other reading: 'not established ... the answer took reading (b), the "
                "Lean takes (a)' and a delivery note; labels of different schemes, or a bare label naming an object "
                "(review H2), settle nothing",
                s_oth == ["not established: non-vacuity Ambiguous on `P.lemma_1_2` (round 2026-01-01-aaaaaaa; decision: "
                          "QUESTION; the answer took reading (b), the Lean takes (a))"]
                and any("took reading (b), but the row says the Lean takes (a)" in t for t in n_oth)
                and s_sch == ["not established: non-vacuity Ambiguous on `P.lemma_1_2` (round 2026-01-01-aaaaaaa; "
                              "decision: QUESTION)"]
                and s_h2 == ["not established: non-vacuity Ambiguous on `P.lemma_1_2` (round 2026-01-01-aaaaaaa; "
                             "decision: QUESTION)"] and s_nl == s_h2)
            # review HIGH-1, L1, L2, MEDIUM-1: a negated or interrogative answer, a negated row, a bare label the row
            # does not name as a reading, a token its own prose contradicts: each settles nothing (not established);
            # the contradicting token is also a delivery note
            NE = s_h2
            ATT = [("Two readings: (a) the paper's, (b) a stand-in. The Lean takes (b). Recommended: (a).",
                    "do not keep the Lean's reading; take the paper's"),
                   ("The Lean takes (b). Recommended: (a).", "Keep the Lean's reading? No: use the paper's"),
                   ("The Lean takes (b). Recommended: (a).", "don't keep the Lean's reading"),
                   ("The Lean takes (b). Recommended: (a).", "do not take reading (b)"),
                   ("Neither the paper nor the Lean takes (a); both take (b).", "keep reading (a)"),
                   ("Readings (1) k=1 and (2) k=2. The Lean takes 1, i.e. one vertex, so reading 2.", "keep reading 1"),
                   ("The Lean takes C, the constant.", "keep reading C"),
                   ("The Lean takes (a).", "not reading (a)"),
                   ("The Lean takes (b), i.e. the stand-in. [Lean: (a); recommended: (b)]", "keep the Lean's reading"),
                   ("The Lean takes (b). [Lean: (a); recommended: (a)]", "take reading (a)")]
            att = [(r_, w_, a5("**QUESTION**", r_, w_)) for r_, w_ in ATT]
            bad_att = [(r_, w_, st_) for r_, w_, (st_, _n) in att if st_ != NE]
            say("A5 (review HIGH-1, L1, L2, MEDIUM-1): a negated or interrogative answer, a negated row, a bare label "
                "the row does not name as a reading, a token its prose contradicts: not established; the "
                "contradicting token is a delivery note naming the row",
                not bad_att and all(any("[Lean: ...] token names reading (a)" in t for t in n_) for _r, _w, (_s, n_)
                                    in att[-2:]))
            if bad_att:
                print("   A5 attack misses:", bad_att)
            s_ok, _n = a5("**QUESTION**", "The Lean takes (b). Recommended: (a).", "keep the Lean's reading, as stated")
            say("A5: 'keep the Lean's reading' without a negation still keeps it",
                s_ok == [F.format("b") + ": the reading the Lean takes, kept by a delegated decision of the operator"])
            # A5b: a kept reading of a Definition row the result uses reads "faithful under reading" for its users too;
            # an answer taking the other reading, or none, settles nothing
            def a5b(words):
                reset()
                mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Definition 1.1", "Ambiguous")]),
                        "| paper-faithfulness | Definition 1.1 | Ambiguous | **QUESTION** | Two readings. "
                        "[Lean: (a); recommended: (a)] |\n")
                open(os.path.join(rd, "RUN_LOG.md"), "w").write(
                    "# Run log\n\n## Open questions\n\n" + (f"- [DELEGATED 2026-01-01, operator under hands-off "
                    f"(intake); reversal: none] keep D ({words}) (QUESTION row on Definition 1.1, round "
                    "2026-01-01-aaaaaaa) -- follows the adjudicator's recommendation.\n" if words else ""))
                st_, rt_ = ST(), {r.route for r in routes(cfg) if r.result == "Theorem 2.1"}
                os.remove(os.path.join(rd, "RUN_LOG.md"))
                return st_["Theorem 2.1"], st_["Lemma 1.3 (a)"], rt_
            k_t, k_l, k_r = a5b("take reading (a)")
            o_t, _l, o_r = a5b("take reading (b)")
            say("A5b: a Definition's Ambiguous answered with the Lean's reading: its users read 'faithful under reading "
                "(a) ... (used by it)' (no route); another reading: not established; a result not using it: faithful",
                k_t == ["faithful under reading (a) of the paper-faithfulness question on Definition 1.1 (used by it) "
                        "(round 2026-01-01-aaaaaaa): the reading the Lean takes, kept by a delegated decision of the operator"]
                and k_r == set() and k_l == [FAITHFUL] and o_t[0].startswith("not established: paper-faithfulness "
                                                                            "Ambiguous on Definition 1.1 (used by it)")
                and o_r == {"decided"})
            LT = [("The Lean takes (a).", {"a"}), ("The Lean takes reading (i)", {"i"}), ("The Lean** takes reading (i)", {"i"}),
                  ("The Lean takes reading A", {"a"}), ("The Lean takes reading 2: the weak form", {"2"}),
                  ("Reading A: x. The Lean takes A.", {"a"}), ("Reading A: x. The Lean takes A, and the paper", {"a"}),
                  ("Reading B: y. The Lean takes B (x)", {"b"}), ("Reading A is x. The Lean `eq` (S.lean:167-173) takes A",
                                                                  {"a"}),
                  ("The Lean takes A.", set()), ("The Lean takes B (x)", set()), ("The Lean takes 1, i.e. one", set()),
                  ("The Lean takes C, the constant", set()), ("The Lean takes I (the identity)", set()),
                  ("The Lean takes X;", set()), ("Neither the paper nor the Lean takes (a); both take (b)", set()),
                  ("Which one? The Lean takes (a)?", set()), ("The Lean takes (a) as a hypothesis", {"a"}),
                  ("Lean (`p_A_5`, S.lean:3) takes reading 2", {"2"}),
                  ("The Lean (`l_2_3`, B.lean:31, `sInf` for min) takes (a). Recommended: (a).", {"a"}),
                  ("The Lean (E.lean:12) takes reading A", {"a"}), ("The Lean type takes reading 1", {"1"}),
                  ("reading A\nThe Lean takes A\nshort reason", {"a"}),
                  ("The Lean takes the stronger hypothesis", set()), ("The Lean takes `X` as a hypothesis", set()),
                  ("the lane takes (a)", set()), ("take reading (b); the rest of the docstring takes (a)", set()),
                  ("Readings: (a) A finite; (b) A arbitrary. The Lean takes A arbitrary, i.e. (b).", set()),
                  ("The Lean takes 2 ≤ d (a bound)", set()), ("The Lean takes K as a parameter", set()),
                  # review H2 with the label named as a reading elsewhere: only the clause end rules it out (A5-1)
                  ("Reading A: x finite. The Lean takes A arbitrary, i.e. the stand-in", set()),
                  ("Reading 2: d = 2. The Lean takes 2 ≤ d (a bound)", set()),
                  ("The Lean takes a stronger form", set()), ("The Lean takes reading A.5 of x", set()),
                  ("The Lean takes (a). The Lean takes (b).", {"a", "b"})]
            bad_lt = [t for t, w in LT if lean_labels(t)[0] != w]
            TK = [("[Lean: (a); recommended: (b)]", ({"a"}, "b")), ("[Lean: (A); recommended: (B)]", ({"a"}, "b")),
                  ("[lean: a, Recommended: b]", ({"a"}, "b")), ("The Lean takes (b). [Lean: (a); recommended: (a)]", (set(), None)),
                  ("The Lean takes (a). [Lean: (a); recommended: (b)]", ({"a"}, "b")),
                  ("[Lean: (a); recommended: (a)] [Lean: (b); recommended: (b)]", (set(), None))]
            bad_tk = [t for t, w in TK if lean_labels(t) != w]
            RD = [("keep reading (a)", {"a"}), ("reading A (sufficiency)", {"a"}), ("keep reading 1 (the weak one)", {"1"}),
                  ("keep reading B", {"b"}), ("keep reading 2 of Proposition A.5", {"2"}),
                  ("keep S7 with d ≥ 2 (reading A)", {"a"}), ("(reading 1)", {"1"}), ("after re-reading A, keep it", set()),
                  ("keep reading B and note that x uses reading A", {"a", "b"}), ("reading A.5", set()),
                  ("do not take reading (a)", set()), ("not reading (a)", set()), ("keep reading (a)? no", set()),
                  ("[DELEGATED x; reversal: not before y] keep reading (a) (QUESTION row on P.x, round r)", {"a"}),
                  ("keep reading 1 -- the paper's (not the stronger one)", {"1"}),
                  ("keep `not_x` (reading 2)", {"2"})]
            bad_rd = [t for t, w in RD if _labels(READING, t) != w]
            say("A5 unit table: the Lean's reading (legacy wordings, review H2 negatives, a bare label only when the row "
                "names it as a reading, no negated clause), the token (review M5: case, comma, A/B; two tokens, or prose "
                "naming another label, give nothing), the answer's readings (no 're-reading', no negated clause)",
                not bad_lt and not bad_tk and not bad_rd and _same_scheme("b", "a") and not _same_scheme("b", "ii")
                and _same_scheme("i", "ii") and not _same_scheme("1", "a"))
            if bad_lt or bad_tk or bad_rd:
                print("   A5 misses:", bad_lt, bad_tk, bad_rd)
            # B9 (a benchmark run): a cited result stated as the named literature hypothesis, with a false row and a
            # repair: "assumed as a corrected hypothesis (not proved)", never "proved as repaired"; without a defect
            # it reads "assumed, not proved", never faithful
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
                "## Defects\n\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
                "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
                "| 5 | Theorem 2.1, tex l.9 | false | local | x | counterexample: n = 3 | `P.not_thm_as_printed`, "
                "`P.not_thm_as_printed` | none | fixed | r |\n")
            cfg["literature_hypotheses"] = [{"lean": "P.thm_2_1", "paper": "[A]"}, {"lean": "P.lemma_1_3_a", "paper": "[B]"}]
            s = ST()
            del cfg["literature_hypotheses"]
            say("B9: a named literature hypothesis false as printed reads 'assumed as a corrected hypothesis (not "
                "proved)' (witness once); one with no defect reads 'assumed, not proved'; neither 'proved' nor faithful",
                s["Theorem 2.1"] == ["defect 5: false; local — false as printed; assumed as a corrected hypothesis (not "
                                     "proved) (witness `P.not_thm_as_printed`)"]
                and s["Lemma 1.3 (a)"] == ["assumed, not proved (`lemma_1_3_a`: literature hypothesis (declared at "
                                           "Checkpoint A))"])
            os.remove(os.path.join(rd, "PAPER_DEFECTS.md"))
            # vacuous
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("non-vacuity", "P.lemma_1_3_b", "Fail")]),
                    "| non-vacuity | P.lemma_1_3_b | Fail | **ADOPT** — VACUOUS row 1 | x |\n")
            open(os.path.join(rd, "VACUOUS.md"), "w").write(
                "| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
                "|---|---|---|---|---|---|---|\n| 1 | Lemma 1.3 (b), `P.lemma_1_3_b` | all | unsat | keep | r | open |\n")
            s = ST()
            say("a vacuous statement reads 'vacuous', its non-vacuity Fail answered by the VACUOUS row",
                s["Lemma 1.3 (b)"] == ["vacuous (VACUOUS row 1; open)"] and s["Lemma 1.3 (a)"] == [FAITHFUL])
            # next batch B6 (AUDIT-P4 D1): a VACUOUS row on a helper naming another result as context, and a SKIPPED
            # row whose subject mentions another result, give that other result no status
            open(os.path.join(rd, "VACUOUS.md"), "w").write(
                "| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
                "|---|---|---|---|---|---|---|\n| 1 | `P.lemma_1_3_b`, the helper used in the proof of Lemma 1.3 (a) "
                "(`P.lemma_1_3_a`) | all | unsat | keep | r | open |\n")
            open(os.path.join(rd, "SKIPPED.md"), "w").write(
                "| # | what | reason | what it would take | how this was checked | decided by |\n|---|---|---|---|---|---|\n"
                "| 1 | Conjecture 3.1, which needs condition (ii) of Theorem 2.1 | open problem | a proof | read | human |\n")
            s6 = ST()
            say("next batch B6: a context mention in a VACUOUS statement cell or a SKIPPED `what` cell gives the "
                "mentioned result no status; the row's own result keeps it",
                s6["Lemma 1.3 (b)"] == ["vacuous (VACUOUS row 1; open)"] and s6["Lemma 1.3 (a)"] == [FAITHFUL]
                and s6["Conjecture 3.1"][0] == "not formalized (SKIPPED row 1)"
                and not any(x.startswith("not formalized") for x in s6["Theorem 2.1"])
                and primary_subject("Proof of Conjecture 3.1", "skipped") == "Conjecture 3.1"
                and primary_subject("the bound in the remark on k = h², Remark 5.2", "skipped") == "Remark 5.2"
                and primary_subject("condition (ii) of Theorem C", "skipped") == "Theorem C"
                and primary_subject("`P.x` for Lemma 2", "vacuous") == "`P.x`"
                and primary_subject("no name here", "vacuous") == "no name here")
            # fix round 1 (attack 1, demonstrated): a VACUOUS row about `P.lemma_1_3_a` that names the helper
            # `P.lemma_1_3_b` (which has the non-vacuity Fail) as context: the helper's Fail is NOT answered by it
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("non-vacuity", "P.lemma_1_3_b", "Fail")]),
                    "| non-vacuity | P.lemma_1_3_b | Fail | **ADOPT** — VACUOUS row 1 | x |\n")
            open(os.path.join(rd, "VACUOUS.md"), "w").write(
                "| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
                "|---|---|---|---|---|---|---|\n| 1 | `P.lemma_1_3_a` is proved from the helper `P.lemma_1_3_b`, whose "
                "hypotheses are unsatisfiable | all | unsat | keep | r | open |\n")
            open(os.path.join(rd, "SKIPPED.md"), "w").write("| # | what | reason |\n|---|---|---|\n")
            s7 = ST()
            say("fix round 1 (attack 1): a VACUOUS row that names a result only as context neither gives it a status nor "
                "answers its Fail: it never reads plain 'faithful'",
                s7["Lemma 1.3 (b)"] != [FAITHFUL] and s7["Lemma 1.3 (a)"][0].startswith("vacuous"))
            os.remove(os.path.join(rd, "SKIPPED.md"))
            os.remove(os.path.join(rd, "VACUOUS.md"))
            # excluded at B; SKIPPED; open question (PROXY/open questions under involved)
            json.dump({"rows": {"Lemma 1.2": {"decls": ["P.lemma_1_2"], "status": "excluded"}}, "fingerprints": fp0},
                      open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
            open(os.path.join(rd, "SKIPPED.md"), "w").write(
                "| # | what | reason | what it would take | how this was checked | decided by |\n|---|---|---|---|---|---|\n"
                "| 1 | Proof of Conjecture 3.1 | open problem | a proof | read | human |\n")
            make_report.open_questions = lambda cfg_: [("2026-01-01-aaaaaaa", "paper-faithfulness", "Lemma 1.3 (a)",
                                                        "which reading", "")]
            s = ST()
            say("excluded at Checkpoint B comes first", s["Lemma 1.2"][0] == "excluded at Checkpoint B")
            say("a SKIPPED row: 'not formalized', before 'stated only'",
                s["Conjecture 3.1"][0] == "not formalized (SKIPPED row 1)" and s["Conjecture 3.1"][1].startswith("stated only"))
            say("an open question (involved: B, C, [PROXY], open QUESTION rows) reads 'decision open' and routes to "
                "the human", s["Lemma 1.3 (a)"][0].startswith("decision open: paper-faithfulness question")
                and any(r.code == "question" for r in routes(cfg) if r.result == "Lemma 1.3 (a)"))
            make_report.open_questions = lambda cfg_: []
            os.remove(os.path.join(rd, "SKIPPED.md"))
            # drift
            json.dump({"rows": {}, "fingerprints": dict(fp0, **{"P.lemma_1_3_a": "approved-other"})},
                      open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
            say("fingerprint drift from the approved statement: not established, routed to `drift`",
                any("fingerprint drift" in x for x in ST()["Lemma 1.3 (a)"])
                and any(r.code == "drift" for r in routes(cfg) if r.result == "Lemma 1.3 (a)"))
            os.remove(os.path.join(rd, "APPROVED_FINGERPRINTS.json"))
            # stated only (a leave line)
            decisions.unproved = lambda cfg_, *a, **k: {"decls": {"P.lemma_1_2": "[DELEGATED]"}, "lines": {},
                                                        "goal": [], "problems": []}
            say("a result left unproved reads 'stated only', never faithful",
                ST()["Lemma 1.2"] == ["stated only (`lemma_1_2` left unproved; its statement checked faithful)"])
            decisions.unproved = lambda cfg_, *a, **k: {"decls": {}, "lines": {}, "goal": [], "problems": []}
            # assumptions (F7, F9)
            WALK["assumes"] = {"P.thm_2_1": [{"name": "P.H", "binder": "hH", "kind": "prop", "type_pp": "P.H n",
                                              "embedded": False}],
                               "P.lemma_1_2": [{"name": "P.G", "binder": None, "kind": "prop", "type_pp": "P.G",
                                                "embedded": True}]}
            s = ST()
            say("an unclassified assumption: not established (adjudicator) (F9)",
                s["Theorem 2.1"] == ["not established: unclassified assumption `H`"])
            say("an embedded assumption: not established, said embedded (F9)",
                s["Lemma 1.2"] == ["not established: unclassified assumption `G` (embedded in the statement)"])
            cfg["literature_hypotheses"] = [{"lean": "P.H", "paper": "[K, Thm 1]"}]
            say("a literature hypothesis WITHOUT a valid row: not established (F7: no row, no 'proved assuming')",
                ST()["Theorem 2.1"] == ["not established: the hypothesis `H` has no valid record yet"])
            hl = hypotheses.latest
            hypotheses.latest = lambda cfg_, rd_=None: {"P.H": ("r", 1, {"matches source": "source unavailable"}, None)}
            say("a literature hypothesis with a 'source unavailable' row: proved assuming H (source not checked)",
                ST()["Theorem 2.1"] == ["proved assuming `H` (literature hypothesis (declared at Checkpoint A)) "
                                        "(source not checked)"])
            hypotheses.latest = lambda cfg_, rd_=None: {"P.H": ("r", 1, {"matches source": "no"}, None)}
            say("a hypothesis that does not match its source: not established",
                ST()["Theorem 2.1"] == ["not established: the hypothesis `H` does not match its source"])
            hypotheses.latest = lambda cfg_, rd_=None: {"P.H": ("r", 1, {"matches source": "yes"}, None)}
            fpu = dict(fp0, **{"P.thm_2_1_unconditional": "u"})
            reset()
            v = allpass()
            v["correspondence"].append(("P.thm_2_1_unconditional", "Pass"))
            mkround("2026-01-01-aaaaaaa", fpu, v)
            say("'also proved unconditionally' once the _unconditional declaration passed correspondence (B7a)",
                ST()["Theorem 2.1"] == ["proved assuming `H` (literature hypothesis (declared at Checkpoint A)); "
                                        "also proved unconditionally (`thm_2_1_unconditional`)"])
            # B5: an inline `<result>:<binder>` is classified by its row like a named one
            WALK["assumes"], WALK["restates"] = {}, {"P.thm_2_1": [{"binder": "hI", "result": "P.lemma_1_2"}]}
            hypotheses.latest = lambda cfg_, rd_=None: {}
            s_none = ST()["Theorem 2.1"]
            hypotheses.latest = lambda cfg_, rd_=None: {"P.thm_2_1:hI": ("r", 1, {"matches source": "no"}, None)}
            s_no = ST()["Theorem 2.1"]
            hypotheses.latest = lambda cfg_, rd_=None: {"P.thm_2_1:hI": ("r", 1, {"matches source": "yes"}, "bad cite")}
            s_bad = ST()["Theorem 2.1"]
            hypotheses.latest = lambda cfg_, rd_=None: {"P.thm_2_1:hI": ("r", 1, {"matches source": "yes"}, None)}
            s_yes = ST()["Theorem 2.1"]
            say("B5: an inline binder is classified by its Hypotheses row: none or an invalid one -> no valid record, "
                "`no` -> does not match its source (both adjudicator), a valid `yes` (the paper's printed hypothesis) "
                "-> faithful",
                s_none == s_bad == ["not established: the hypothesis `P.thm_2_1:hI` has no valid record yet"]
                and s_no == ["not established: the hypothesis `P.thm_2_1:hI` does not match its source"]
                and s_yes == [FAITHFUL] and any(r.code == "adj-record" for r in routes(cfg) if r.result == "Theorem 2.1") is False)
            WALK.pop("restates")
            hypotheses.latest = hl
            del cfg["literature_hypotheses"]
            WALK["assumes"] = {}
            # no closure recorded: every Definition row is required (conservative)
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass([("paper-faithfulness", "Definition 1.1", "Fail")]),
                    with_deps=False)
            say("no closure recorded: every Definition row is required (Lemma 1.3 too)",
                any("Definition 1.1 (used by it)" in x for x in ST()["Lemma 1.3 (a)"]))
            # precedence over every status
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, {"correspondence": [(d, "Pass") for d in decls]})
            json.dump({"rows": {"Lemma 1.2": {"status": "excluded"}}}, open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
            open(os.path.join(rd, "SKIPPED.md"), "w").write(
                "| # | what | reason | what it would take | how this was checked | decided by |\n|---|---|---|---|---|---|\n"
                "| 1 | Lemma 1.2 | x | y | z | h |\n")
            open(os.path.join(rd, "VACUOUS.md"), "w").write(
                "| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
                "|---|---|---|---|---|---|---|\n| 1 | Lemma 1.2 | all | unsat | keep | r | open |\n")
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
                "## Defects\n\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
                "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
                "| 1 | Lemma 1.2 | false | not repaired | x | y | `P.lemma_1_2` | z | d | r |\n")
            make_report.open_questions = lambda cfg_: [("R", "correspondence", "P.lemma_1_2", "why", "")]
            decisions.unproved = lambda cfg_, *a, **k: {"decls": {"P.lemma_1_2": "t"}, "lines": {}, "goal": [], "problems": []}
            s = ST()["Lemma 1.2"]
            order = ["excluded", "not formalized", "decision open", "stated only", "defect", "vacuous", "not established"]
            pos = [next((i for i, x in enumerate(s) if x.startswith(o)), -1) for o in order]
            say("precedence: every status shown, in U2 §1's order", -1 not in pos and pos == sorted(pos))
            # C2-FIX 5b (approver 2026-10-26): a check of the proofs that could not run marks every result "not
            # verified: <what>"; a provenance check marks none (the proofs and statements were checked)
            import stops as _st
            keep_cf = _st.core_fault_rows
            got = {}
            for cf_ in ("axiom_sweep.py", "integrity.py"):
                _st.core_fault_rows = (lambda f_: lambda *a_, **k_: [{"core_file": f_}])(cf_)
                try:
                    got[cf_] = ST()
                finally:
                    _st.core_fault_rows = keep_cf
            base = ST()
            say("C2-FIX 5b: with a check of the proofs that could not run every result reads 'not verified: standard "
                "axioms only' (none faithful); a provenance check that could not run changes no status",
                got["axiom_sweep.py"] and all("not verified: standard axioms only" in v and FAITHFUL not in v
                                              for v in got["axiom_sweep.py"].values())
                and got["integrity.py"] == base)
        finally:
            decisions.unproved, make_report.open_questions, hypotheses.walk = dq_un, mq, hw
            hypotheses.walk_problem = hwp
            make_report.REPO = mr_repo
    finally:
        project.REPO = old_repo
        shutil.rmtree(tmp, ignore_errors=True)
    # the closure comes from the record: fingerprint.parse keeps each declaration's own deps, scope.lean_fps
    # hands them to the FINGERPRINTS.json it writes
    import fingerprint, scope
    out_ = "FP\tP.thm\ttheorem\tuser\th1\tP.D,P.lemma\nFP\tP.D\tdef\tuser\th2\t\nFP\tP.lemma\ttheorem\tuser\th3\tP.D\nFPCOUNT\t3\n"
    fingerprint.parse(out_)
    say("fingerprint.parse records each declaration's project-local deps (FINGERPRINTS.json `deps`)",
        fingerprint._DEPS == {"P.thm": ["P.D", "P.lemma"], "P.D": [], "P.lemma": ["P.D"]})
    fc = fingerprint.compute
    try:
        fingerprint.compute = lambda cfg_, body=None: fingerprint.closure_fps(fingerprint.parse(out_))
        fps_ = scope.lean_fps({})
        say("scope.lean_fps carries the deps scope.py writes into FINGERPRINTS.json",
            fps_.deps == {"P.thm": ["P.D", "P.lemma"], "P.D": [], "P.lemma": ["P.D"]}
            and scope.fingerprint_record("h", fps_).get("deps") == fps_.deps)
    finally:
        fingerprint.compute = fc
    # the routing table names only codes the cure table knows (or the question route)
    say("every route code is a cause code of project.CAUSES (or the question route)",
        all(_code(r) in project.CAUSES or _code(r) in ("question", "unverified")
            for r in ("unverified", "adjudicator", "drift", "question", "unmapped", "?")))
    say("status-unmapped is disclosed in release (class N), never a release stop",
        project.release_class(UNMAPPED_CODE) == "N" and project.release_kind(UNMAPPED_CODE) == "disclose")
    say("defect words: a false row left unrepaired never reads 'proved as repaired'; a misprint reads 'as intended'",
        _defect_words("false", "not repaired", False) == "false as printed; not repaired"
        and _defect_words("false", "none (intent unknown)", False) == "false as printed; intent unknown, not repaired"
        and _defect_words("false", "substantial", True) == "false as printed; the repaired statement is stated, not proved"
        and _defect_words("misprint (true as intended)", "typo", False) == "a misprint; true as intended; proved as intended"
        and _defect_words("false", "local", False, True) == "false as printed; assumed as a corrected hypothesis (not proved)")
    say("mentions: part-aware labels", mentions("Lemma 5.4 (c), `X.lemma_5_4_c`", "Lemma 5.4 (c)", [])
        and not mentions("Lemma 5.4 (c), `X.lemma_5_4_c`", "Lemma 5.4 (a)", ["X.lemma_5_4_a"])
        and mentions("Lemma 5.4(c) is cited", "Lemma 5.4", []) and not mentions("Lemma 5.41", "Lemma 5.4", [])
        and mentions("Lemma 5.4 (b) and (c)", "Lemma 5.4 (c)", []))
    _selftest_p5(say)
    _selftest_p6(say)
    print("selftest: " + ("ok" if not fails else f"FAILED ({len(fails)})"))
    return 1 if fails else 0


def _selftest_p5(say):
    """Fix round K (AUDIT-P5): the conditions checklist and inferred items replayed on the e2e run's own K records (tests/lane_samples/k-p5-records.json,
    verbatim), each index row's status as the run's records gave it."""
    import shutil, subprocess, tempfile, hypotheses
    P = json.load(open(os.path.join(project.AUDITS, "tests", "lane_samples", "k-p5-records.json"), encoding="utf-8"))
    ns = P["namespace"]
    tmp = tempfile.mkdtemp(prefix="rstatus-p5-")
    saved = (project.REPO, globals()["context"], globals()["analyse"], hypotheses.walk, hypotheses.walk_problem)
    try:
        project.REPO = tmp
        subprocess.run(["git", "init", "-q", tmp]); subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "x"])
        rd = os.path.join(tmp, "audits", "P5")
        cfg = {"name": "P5", "namespace": ns, "rounds_dir": "audits/P5", "involvement": "hands-off", "mode": "release",
               "literature_hypotheses": P["literature_hypotheses"]}
        st = {lab: s for lab, _n, s in P["rows"]}
        ctx = {"rd": rd, "ns": ns, "known": set(), "problems": [],
               "index": [(lab, ", ".join(f"`{n}`" for n in names)) for lab, names, _s in P["rows"]]}
        globals()["context"] = lambda cfg_, live=None: ctx
        globals()["analyse"] = lambda cfg_, r, c: (st[" ".join(str(r[0]).split())],)
        DOC = {"assumes": P["assumes"], "bare": P["bare"]}
        hypotheses.walk = lambda cfg_, rd_=None: (DOC, None)
        hypotheses.walk_problem = lambda cfg_, rd_=None: None

        def write(conditions, adopted, log):
            shutil.rmtree(rd, ignore_errors=True)
            os.makedirs(rd)
            open(os.path.join(rd, CONDITIONS_MD), "w", encoding="utf-8").write(conditions)
            open(os.path.join(rd, "RUN_LOG.md"), "w", encoding="utf-8").write(log)
            for d, sec in adopted.items():
                os.makedirs(os.path.join(rd, d))
                open(os.path.join(rd, d, "ADOPTED.md"), "w", encoding="utf-8").write(
                    "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n\n" + sec)

        write(P["conditions"], P["adopted"], P["run_log"])
        cd, pn = conditions(cfg), provenance_notes(cfg)
        say("fix round K (AUDIT-P5 §3): ids `K1` and `K-2` are kept under their raw ids, open (K1's `met` rows update "
            "it but never close it), with a note saying they are counted open; never dropped",
            cd["K1"]["open"] and cd["K1"]["status"] == "met" and cd["K1"]["kind"] == "source-def"
            and cd["K1"]["why_open"] == RAW_ID_WHY and cd["K-2"]["open"] and cd["K-2"]["kind"] == "reading"
            and not any("not counted" in x for x in pn)
            and sum("not in the C<n>/K3-<n> form" in x and "counted open" in x for x in pn) == 4
            and "K-2" in conditions_without_row(cfg))
        say("fix round K (AUDIT-P5 §4): the three log copies of one Lemma 2.5 decision give no R? item when the "
            "`reading` item K-2 names its row by label",
            not any(x.startswith("R?-") for x in pn))
        lines = [l for l in P["run_log"].splitlines() if "take reading" in l]
        no_k2 = "\n".join(l for l in P["conditions"].splitlines() if not l.startswith("| K-2 |")) + "\n"
        rq = lambda log: sorted(i for i in inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx}))
        write(no_k2, P["adopted"], "\n".join(lines) + "\n")
        r_all = rq(None)
        write(no_k2, P["adopted"], lines[2] + "\n")
        r_ans = rq(None)
        write(P["conditions"], P["adopted"], lines[1] + "\n")
        r_anchor = rq(None)
        write(P["conditions"], P["adopted"], lines[0] + "\n")
        r_qrow = rq(None)
        say("fix round K (AUDIT-P5 §4): without K-2 the three copies give one R? item; an "
            "`answered` copy alone gives none; with K-2 neither the `question:` anchor line nor the QUESTION-row line "
            "gives one (K-2's label `Lemma 2.5` names the decl's row)",
            r_all == ["R?-1"] and r_ans == [] and r_anchor == [] and r_qrow == [])
        # fix round RAMK: the same reading item under a readable id and MET names only the row: it may be another
        # decision's item, so the R? item stays (counted open); naming the decl's Lean name, it is the item
        c9 = lambda s: s.replace("| K-2 |", "| C9 |")
        met = {d: sec.rstrip("\n") + "\n| C9 | met | VACUOUS.md row 1 | kept as printed, as the decision says |\n"
               for d, sec in P["adopted"].items()}
        write(c9(P["conditions"]), met, lines[1] + "\n")
        its9 = _items(cfg, rd)
        r_met = rq(None)
        lit = c9(P["conditions"]).replace("| C9 | reading | Lemma 2.5 |", "| C9 | reading | Lemma 2.5, `ColoringSmallKtMinorFree.lemma_2_5` |")
        write(lit, met, lines[1] + "\n")
        r_lit = rq(None)
        say("fix round RAMK: a CLOSED `reading` item naming only the decl's row (by label) no longer hides the delegated "
            "decision's R? item (counted open); one naming the decl itself still counts as its item",
            its9["C9"]["open"] is False and r_met == ["R?-1"] and r_lit == [])
    except Exception as e:      # noqa: BLE001 -- a crash of the fixture is a failure
        say(f"fix round K (AUDIT-P5): the replay of the run's K records ran ({type(e).__name__}: {e})", False)
    finally:
        project.REPO, globals()["context"], globals()["analyse"], hypotheses.walk, hypotheses.walk_problem = saved
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest_p6(say):
    """Fix round P6 (AUDIT-P6): the inferred items replayed on the final e2e run's own K records
    (tests/lane_samples/k-p6-records.json, verbatim): as recorded, three helper-level K3? items on notes the
    adjudicators ruled trivial in prose; none with the adjudicators' B'' ruling written as the `K3-0` row it asks for
    now (AUDIT-P6 §2). K-REMOVE: which results an item affects is the formalizing agent's judgement."""
    import shutil, subprocess, tempfile, hypotheses
    P = json.load(open(os.path.join(project.AUDITS, "tests", "lane_samples", "k-p6-records.json"), encoding="utf-8"))
    ns = P["namespace"]
    tmp = tempfile.mkdtemp(prefix="rstatus-p6-")
    saved = (project.REPO, globals()["context"], globals()["analyse"], hypotheses.walk, hypotheses.walk_problem)
    try:
        project.REPO = tmp
        subprocess.run(["git", "init", "-q", tmp]); subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "x"])
        rd = os.path.join(tmp, "audits", "P6")
        cfg = {"name": "P6", "namespace": ns, "rounds_dir": "audits/P6", "involvement": "hands-off", "mode": "release",
               "literature_hypotheses": P["literature_hypotheses"]}
        st = {lab: s_ for lab, _n, s_ in P["rows"]}
        # fix round P6b (REVIEW-FIXP6-NB M2): fingerprints by content -- an older round still held the deleted
        # `isMinor_of_iso` (a fingerprint no current declaration carries)
        cur = {n: f"fp:{n}" for n in P["known"]}
        old_snap = dict(cur, **{f"{ns}.isMinor_of_iso": "fp:isMinor_of_iso"})
        ctx = {"rd": rd, "ns": ns, "known": set(P["known"]), "problems": [], "cur": cur,
               "snaps": [("old", old_snap, None), ("new", dict(cur), None)],
               "index": [(lab, ", ".join(f"`{n}`" for n in names)) for lab, names, _s in P["rows"]]}
        globals()["context"] = lambda cfg_, live=None: ctx
        globals()["analyse"] = lambda cfg_, r, c: (st[" ".join(str(r[0]).split())],)
        DOC = {"assumes": P["assumes"], "bare": P["bare"]}
        hypotheses.walk = lambda cfg_, rd_=None: (DOC, None)
        hypotheses.walk_problem = lambda cfg_, rd_=None: None
        K30 = "| K3-0 | not applicable | - | no nontrivial REPRESENTATION note: each is immediate by unfolding |\n"

        def write(conditions=P["conditions"], adopted=P["adopted"], log=P["run_log"], k30=(), corr=P["correspondence"]):
            shutil.rmtree(rd, ignore_errors=True)
            os.makedirs(rd)
            open(os.path.join(rd, CONDITIONS_MD), "w", encoding="utf-8").write(conditions)
            open(os.path.join(rd, "RUN_LOG.md"), "w", encoding="utf-8").write(log)
            for d, sec in adopted.items():
                os.makedirs(os.path.join(rd, d), exist_ok=True)
                sec = sec.rstrip("\n") + "\n" + (K30 if d in k30 else "") + "\n"
                open(os.path.join(rd, d, "ADOPTED.md"), "w", encoding="utf-8").write(
                    "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n\n" + sec)
            for f, vs in corr.items():
                os.makedirs(os.path.join(rd, os.path.dirname(f)), exist_ok=True)
                json.dump({"verdicts": vs}, open(os.path.join(rd, f), "w", encoding="utf-8"))

        def run():
            return inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx}), provenance_notes(cfg)
        opn = lambda inf_: sorted(it["results"].rsplit(".", 1)[-1] for it in inf_.values() if it["open"])
        R = sorted(P["adopted"])
        D1 = "2026-11-14-full-d1d7d5ebd69"
        write()
        inf, pn = run()
        on_rows = {n_ for _l, ns_, _s in P["rows"] for n_ in ns_}
        say("fix round P6 (AUDIT-P6): as recorded, the open inferred items on helpers (on no index row) are the K3? "
            "items on `iterInv_step`, `isMinor_induce`, `isMinor_of_injective_hom`; no R? item (each delegated line "
            "names the open item C3)",
            not any(i.startswith("R?-") for i in inf)
            and sorted(it["results"].rsplit(".", 1)[-1] for it in inf.values() if it["open"]
                       and it["results"] not in on_rows) == ["isMinor_induce", "isMinor_of_injective_hom", "iterInv_step"])
        stale_ = [i for i, it in inf.items() if it.get("stale")]
        say("fix round P6 (AUDIT-P6 §3): the K3? item on the deleted `isMinor_of_iso` is listed 'stale, not counted' "
            "(never open, never met) with a note; no result counts it",
            len(stale_) == 1 and inf[stale_[0]]["results"].endswith(".isMinor_of_iso")
            and inf[stale_[0]]["status"] == STALE_STATUS and inf[stale_[0]]["open"] is False
            and any(x.startswith(stale_[0] + " names") and "stale, not counted" in x for x in pn))
        say("fix round P6 (AUDIT-P6 §2, fix 1): C1's 'Theorems 1.3, 2.1, 2.2, 3.1' names four index rows (no "
            "unmatched-entry note)", not any(x.startswith(f"{CONDITIONS_MD} C1: results entry") for x in pn)
            and unmatched_entries("Theorems 1.3, 2.1, 2.2, 3.1", index_names(cfg, {CTX_KEY: ctx})) == [])
        write(k30=R)
        inf, pn = run()
        say("fix round P6 (AUDIT-P6 §2): with each round's B'' ruling as the row `K3-0 | not applicable`, no open "
            "inferred item and no K3? note; C3 stays open",
            opn(inf) == [] and _items(cfg, rd)["C3"]["open"]
            and not any(x.startswith("K3?-") for x in pn))
        write(k30=[r for r in R if r != D1])
        inf_d, pn_d = run()
        noreason = dict(P["adopted"])
        write(k30=R)
        open(os.path.join(rd, D1, "ADOPTED.md"), "w", encoding="utf-8").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n\n" + P["adopted"][D1].rstrip("\n")
            + "\n| K3-0 | not applicable | - | - |\n\n")
        inf_nr = run()[0]
        bridge = {d: (sec.rstrip("\n") + "\n| K3-1 | met | `SmallKtMinorFree.IsMinor` | bridge: proved |\n\n"
                      if d == R[0] else sec) for d, sec in noreason.items()}
        write(adopted=bridge)
        inf_b = inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx})
        say("fix round P6 (AUDIT-P6 §2, fix 3): the ruling is per round -- without it in round full-d1d7d5ebd69 its "
            "helper notes are open items again (the deleted helper's stays stale); a `K3-0` "
            "row with no reason rules nothing; one round's `K3-1` row no longer hides the other rounds' notes",
            opn(inf_d) != [] and any("stale, not counted" in x for x in pn_d) and opn(inf_nr) != []
            and any(it["source"].startswith(D1) for it in inf_b.values())
            and not any(it["source"].startswith(R[0]) for it in inf_b.values()))
        c9 = P["run_log"].replace("open item C3", "open item C9")
        write(k30=R, log=c9)
        inf9 = run()[0]
        c1 = P["run_log"].replace("open item C3", "open item C1")
        write(k30=R, log=c1)
        inf1 = run()[0]
        c3m = {d: re.sub(r"(?m)^\| C3 \| open \|", "| C3 | met |", sec) for d, sec in P["adopted"].items()}
        write(k30=R, adopted=c3m)
        inf3 = inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx})
        say("fix round P6 (AUDIT-P6 §2, fix 2): a delegated line naming an item that does not exist (C9), or one that "
            "is closed (C1; C3 itself once met), keeps its R? item, open",
            any(i.startswith("R?-") and it["open"] for i, it in inf9.items())
            and any(i.startswith("R?-") and it["open"] for i, it in inf1.items()) and not _items(cfg, rd)["C3"]["open"]
            and sorted(it["results"].rsplit(".", 1)[-1] for it in inf3.values()) == ["iterInv_step", "lem_2_5_proof"]
            and sorted(it["results"].rsplit(".", 1)[-1] for it in inf9.values())
            == ["iterInv_step", "lem_2_5_proof"] and inf9["R?-1"]["open"])
        ctx["known"] = set()
        write(k30=[r for r in R if r != D1])
        ctx["known"] = set(P["known"])
        inf_e = [it for it in inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx}).values()
                 if it["results"].endswith(".isMinor_of_iso")]
        ctx["known"] = set()
        inf_e0 = [it for it in inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx}).values()
                  if it["results"].endswith(".isMinor_of_iso")]
        ctx["known"] = set(P["known"])
        say("fix round P6 (AUDIT-P6 §3): with no readable declaration set the deleted helper's item stays open",
            len(inf_e0) == 1 and inf_e0[0]["open"] is True
            and len(inf_e) == 1 and inf_e[0]["open"] is False)
        # fix round P6b (REVIEW-FIXP6-NB M2): a rename (same fingerprint, new name) is no deletion: the item stays
        # open, on the new name; an unknown old fingerprint keeps the deleted helper's item open too
        IMI, NEW = f"{ns}.isMinor_induce", f"{ns}.IsMinor.induce"
        ctx["known"] = set(P["known"]) - {IMI} | {NEW}
        ctx["cur"] = dict({k_: v_ for k_, v_ in cur.items() if k_ != IMI}, **{NEW: cur[IMI]})
        ctx["snaps"] = [("old", old_snap, None), ("new", dict(ctx["cur"]), None)]
        write(k30=[r for r in R if r != D1])
        inf_r = inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx})
        ren = [it for it in inf_r.values() if it.get("renamed_to") == NEW]
        gone = [it for it in inf_r.values() if it["results"].endswith(".isMinor_of_iso")]
        ctx["snaps"] = [("new", dict(ctx["cur"]), None)]
        inf_u = [it for it in inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx}).values()
                 if it["results"].endswith(".isMinor_of_iso")]
        ctx["known"], ctx["cur"] = set(P["known"]), cur
        ctx["snaps"] = [("old", old_snap, None), ("new", dict(cur), None)]
        say("fix round P6b (REVIEW-FIXP6-NB M2): renamed `isMinor_induce` -> `IsMinor.induce` (same fingerprint): its "
            "K3? item stays open; the deleted `isMinor_of_iso` is "
            "stale; with its old fingerprint unknown, it stays open",
            len(ren) == 1 and ren[0]["open"] is True and not ren[0].get("stale") and ren[0]["results"] == IMI
            and len(gone) == 1 and gone[0].get("stale") is True
            and len(inf_u) == 1 and inf_u[0]["open"] is True and not inf_u[0].get("stale"))
        # fix round P6b (REVIEW-FIXP6-NB L1): an R? item on a deleted declaration is never stale (a reading decision
        # may still govern the paper's result)
        LP = f"{ns}.lem_2_5_proof"
        ctx["known"] = set(P["known"]) - {LP}
        ctx["cur"] = {k_: v_ for k_, v_ in cur.items() if k_ != LP}
        write(k30=R, log=c9)
        inf_l = [it for it in inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx}).values() if it["results"] == LP]
        ctx["known"], ctx["cur"] = set(P["known"]), cur
        say("fix round P6b (REVIEW-FIXP6-NB L1): an R? item on a declaration no longer in the Lean stays open",
            len(inf_l) == 1 and inf_l[0]["id"].startswith("R?-") and inf_l[0]["open"] is True
            and not inf_l[0].get("stale"))
        # fix round P6b (REVIEW-FIXP6-NB M1): "open item C3" (C3 is about Lemma 2.5) on a line about Lemma 2.4's
        # own declaration hides nothing: the R? item stays open on Lemma 2.4
        L24 = f"{ns}.lem_2_4"
        ln24 = (f"- [DELEGATED 2026-11-14, operator under hands-off (intake); reversal: none] take reading (b) "
                f"(QUESTION row on {L24}, round 2026-11-14-cdcb74f8540) -- reading (b) of Lemma 2.4's hypothesis")
        for tail in ("; open item C3", ""):
            write(k30=R, log=P["run_log"].replace("## Checkpoint C", ln24 + tail + "\n## Checkpoint C"))
            inf24 = inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx})
            r24 = [i for i, it in inf24.items() if i.startswith("R?-") and it["results"] == L24]
            say(f"fix round P6b (REVIEW-FIXP6-NB M1): a delegated reading on `lem_2_4`{' citing C3 (about Lemma 2.5)' if tail else ''} "
                "keeps its R? item open",
                "## Checkpoint C" in P["run_log"] and len(r24) == 1 and inf24[r24[0]]["open"] is True)
        ln25 = ln24.replace(L24, f"{ns}.lem_2_5").replace("Lemma 2.4's", "Lemma 2.5's") + "; open item C3"
        write(k30=R, log=P["run_log"].replace("## Checkpoint C", ln25 + "\n## Checkpoint C"))
        inf25 = inferred_items(cfg, rd, _items(cfg, rd), {CTX_KEY: ctx})
        say("fix round P6b (REVIEW-FIXP6-NB M1): the same reference on Lemma 2.5's own declaration (C3 names Lemma 2.5) "
            "is honoured: no R? item", not any(i.startswith("R?-") for i in inf25) and opn(inf25) == [])
        say("fix round P6 (AUDIT-P6 §2, fix 1): plural lists and ranges are written out; a range it cannot write out "
            "stays as written (matching no row)",
            expand_labels("Theorems 1.3, 2.1, 2.2, 3.1") == "Theorem 1.3, Theorem 2.1, Theorem 2.2, Theorem 3.1"
            and expand_labels("Lemmas 2.4 and 2.6") == "Lemma 2.4, Lemma 2.6"
            and expand_labels("Lemmas 2.4–2.6") == "Lemma 2.4, Lemma 2.5, Lemma 2.6"
            and expand_labels("Corollaries 3 and 4") == "Corollary 3, Corollary 4"
            and expand_labels("Theorem 2.1 and 2.2") == "Theorem 2.1, Theorem 2.2"
            and expand_labels("Lemmas 2.4–3.1") == "Lemmas 2.4–3.1"
            and unmatched_entries("Lemmas 2.4–3.1", [("Lemma 2.4", [])]) == ["Lemmas 2.4–3.1"]
            and expand_labels("Lemma 5.4 (b) and (c)") == "Lemma 5.4 (b) and (c)")
    except Exception as e:      # noqa: BLE001 -- a crash of the fixture is a failure
        say(f"fix round P6 (AUDIT-P6): the replay of the run's K records ran ({type(e).__name__}: {e})", False)
    finally:
        project.REPO, globals()["context"], globals()["analyse"], hypotheses.walk, hypotheses.walk_problem = saved
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if any result is not established (a route other "
                                                         "than an open question)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    cfg, _ = project.select(a.project)
    inp = {CTX_KEY: context(cfg)}
    st = statuses(cfg, inp)
    rts = routes(cfg, inp)
    if a.json:
        print(json.dumps({"statuses": st, "routes": [r._asdict() for r in rts]}, indent=1, ensure_ascii=False))
    else:
        for lab, s in st:
            print(f"- {lab}: " + "; ".join(s))
        for r in rts:
            print(f"  route {r.code}: {r.result}: {r.reason}")
    return 1 if a.check and any(r.route != "question" for r in rts) else 0


if __name__ == "__main__":
    sys.exit(project.run_main(main))

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
    "faithful under reading (x) of the <lane> question ..." (kept_reading; a benchmark run);
  * the approved fingerprints of its declarations equal the newest audited ones (no drift);
  * every assumption the walk lists for it is classified and recorded (F7, F9);
  * no status 1-10 applies.
A NotDoneYet is not a verdict: the latest real verdict counts, if it is still fresh.

ROUTING of "not established" (U2 §1; `routes`): a missing or stale verdict -> `unverified`; an
outstanding Fail or Ambiguous, or an unclassified/unrecorded assumption -> the adjudicator
(`adj-record`) -- except a finding the statement-round cap left open in a release run (scope.cap_record,
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
STATUS_LEGEND = (
    "How to read a result's status: \"faithful\" means every review of the Lean statement against the paper "
    "(correspondence, paper-faithfulness, non-vacuity, on the result and on the definitions it uses) passed on "
    "its current version, nothing is assumed beyond the paper, and -- unless \"stated only\" is listed -- it is "
    "proved with the standard axioms only. Every other status names what holds instead: \"proved as repaired\" "
    "(the printed statement is false and the Lean proves the corrected one), \"assumed, not proved\" (the "
    "result is stated as a named hypothesis, as a cited result is, and never proved), \"proved assuming H\", \"stated "
    "only\", \"vacuous\", \"differs\", \"not established: <why>\" (a review is missing, out of date or not "
    "settled; nothing is claimed).")

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
    idx = make_report.table_rows(os.path.join(project.REPO, project.index_file(cfg) or ""))
    c["index"] = [r for r in idx if r and make_report.RESULT.match(r[0])]
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
    # the QUESTION rows and RUN_LOG.md: an answered question that keeps the reading the Lean takes (kept_reading)
    try:
        c["qrows"] = decisions.question_rows(project.rounds(cfg))
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
    try:
        c["questions"] = make_report.open_questions(cfg)
    except Exception as e:     # noqa: BLE001
        c["questions"] = []
        c["problems"].append(f"the open questions could not be read ({e})")
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


LEAN_TAKES = re.compile(r"(?i)\bthe lean takes (?:reading )?\(([a-z]|[ivx]+)\)")
READING = re.compile(r"(?i)\breading \(([a-z]|[ivx]+)\)")


def kept_reading(c, rnd, lane, item):
    """(reading, who) when a final answer to the QUESTION row of round `rnd` on (lane, item) took the reading that
    row says the Lean takes (AUDIT_PROTOCOL C: the row names "the one the Lean takes"); else None. The Ambiguous is
    then settled by the Lean as it stands (a benchmark run: a non-vacuity Ambiguous, answered "reading (a)", read
    "not established" though nothing was left to settle). The caller has checked that no open question names the
    result. The answer: the [DELEGATED] lines naming that round's QUESTION row on the item, else the latest
    `question:<item>` answer line; every reading it names must be the Lean's."""
    import audit_coverage as ac, decisions
    key = ac.norm_item(item)
    takes = {m.group(1).lower() for it, asks in (c.get("qrows") or {}).items() if ac.norm_item(it) == key
             for r, l, why in asks if r == rnd and l == lane for m in LEAN_TAKES.finditer(str(why))}
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
    said = {m.group(1).lower() for ln in lines for m in READING.finditer(ln)}
    if not lines or said != takes:
        return None
    who = ("a delegated decision of the operator" if all(decisions.DELEGATED_TAG_RE.search(ln) for ln in lines)
           else "the human's answer")
    return next(iter(takes)), who


def _capped_or(reason, c, lane, items):
    """`reason`, or -- when the statement-round cap left this (lane, item) open (c["capped"]) -- the open
    faithfulness finding it is (route round-cap: disclosed, never a delivery block)."""
    import audit_coverage as ac
    cap = next((c.get("capped", {})[f"{lane} :: {ac.norm_item(i)}"] for i in items
                if f"{lane} :: {ac.norm_item(i)}" in c.get("capped", {})), None)
    if not cap:
        return reason
    return (f"open faithfulness finding: {reason[0]} (the statement-round cap was reached at round {cap} with it "
            f"open)", "round-cap")


def verdict_reasons(c, label, names, records, is_def, kept=None):
    """[(reason, route)] standing between the result and F1 (empty: F1's verdict conditions hold).
    `records`: which adjudicator-owned records name the result ({"defect", "vacuous", "skipped", "excluded",
    "reading", "differs"}). `kept`: a list that gets a "faithful under reading" status for every Ambiguous settled
    by an answered question keeping the Lean's reading (kept_reading)."""
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
        if dec == "QUESTION" and v == "Ambiguous" and _answered(c, label, names):
            ks = [kept_reading(c, rnd, lane, i) for i in items]
            if ks and all(ks):
                if kept is not None:
                    kept.append(f"faithful under reading ({ks[0][0]}) of the {lane} question on {subject} (round "
                                f"{rnd}): the reading the Lean takes, kept by {ks[0][1]}")
                return
        route = "question" if dec == "QUESTION" and not _answered(c, label, names) else "adjudicator"
        import audit_coverage as ac
        cap = next((c.get("capped", {})[f"{lane} :: {ac.norm_item(i)}"] for i in items
                    if f"{lane} :: {ac.norm_item(i)}" in c.get("capped", {})), None)
        if route == "adjudicator" and cap:
            # approver 2026-10-24 (decision 3): the statement-round cap was reached with this finding open and the
            # run went on (project.round_cap_route): disclosed on the summary's first page, never a delivery block
            out.append((f"open faithfulness finding: {lane} {v} on {subject} (round {rnd}; the statement-round cap "
                        f"was reached at round {cap} with it open)", "round-cap"))
            return
        out.append((f"{lane} {v} on {subject} (round {rnd}; decision: {dec or 'none recorded'})", route))

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
                        sub.append(_capped_or((f"correspondence {lt_[1]} on `{d}` ({dl}, used by it)", "adjudicator"),
                                              c, lane, lt_[2]))
                continue
            if lt is None:
                sub.append((f"no paper-faithfulness verdict on {dl} (used by it)", "unverified"))
            elif fresh(c, lt[0], about):
                sub.append((f"the paper-faithfulness verdict on {dl} (used by it) is out of date: "
                            f"{fresh(c, lt[0], about)}", "unverified"))
            elif lt[1] != "Pass" and decision(c, lt[0], lane, lt[2][0]) != "REJECT":
                sub.append(_capped_or((f"paper-faithfulness {lt[1]} on {dl} (used by it)", "adjudicator"),
                                      c, lane, lt[2]))
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
            out.append((f"not established: the hypothesis `{short}` does not match its source", "adjudicator"))
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
        if mentions(_col(sh, r, "what") or (r[1] if len(r) > 1 else ""), label, names):
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
        if mentions(_col(vh, r, "statement"), label, names):
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
    return {"unverified": "unverified", "adjudicator": "adj-record", "drift": "drift", "question": "question",
            "unmapped": UNMAPPED_CODE, "round-cap": "round-cap"}.get(route, UNMAPPED_CODE)


def result_status(cfg, row, inp=None):
    """[status] of one index row (B10's SUMMARY and page 1 call this; see the module docstring)."""
    return analyse(cfg, row, ctx_of(cfg, inp))[0]


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
    import shutil, subprocess, tempfile
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
            open(os.path.join(d, "ADOPTED.md"), "w").write(
                "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n" + adopted)
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
        try:
            reset()
            mkround("2026-01-01-aaaaaaa", fp0, allpass())
            s = ST()
            say("F1 honest: every result with fresh Pass verdicts reads exactly 'faithful' (definitions included)",
                all(s[l] == [FAITHFUL] for l in labels[:5]))
            say("a conjecture reads 'stated only', with its statement checked faithful, never plain faithful",
                s["Conjecture 3.1"] == ["stated only (a conjecture: stated as a proposition, asserted nowhere; its "
                                        "statement checked faithful)"])
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
    print("selftest: " + ("ok" if not fails else f"FAILED ({len(fails)})"))
    return 1 if fails else 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if any result is not established (a route other "
                                                         "than an open question)")
    ap.add_argument("--live", action="store_true", help="compare with the fingerprints of HEAD (runs Lean)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    cfg, _ = project.select(a.project)
    live = None
    if a.live:
        import fingerprint
        live = fingerprint.compute(cfg)
    inp = {CTX_KEY: context(cfg, live)}
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

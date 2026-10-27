#!/usr/bin/env python3
"""Checkpoint C: the decisions document a human reads (RUN.md Stage 5, AUDIT_PROTOCOL.md
"Documents a human reads").

WHY THIS EXISTS.  The first Checkpoint C of a real test run (2026-10-13) was a ten-line
summary the human could not act on. Its replacement, written freehand from the record, needed four
independent reader passes, and every pass found decisions it had left out: the sheet's CHECK rows,
QUESTION rows from older rounds, [PROXY] choices made at intake, a stale standing defer, a standing
rule adjudicators proposed but nobody configured. The record is spread over SIGNOFF.json, one
ADOPTED.md per round, RUN_LOG.md, PAPER_DEFECTS.md, SKIPPED.md, the approval file, the project
config and git; a writer reading it by hand misses things. So the SKELETON is generated here: one
item per thing the human must see, each with a hidden anchor, grouped into one section per matter
(B11: a paper result, the approval, or for items on no result their kind). The writer fills in
context, options and a recommendation, may group items further, but may not drop an anchor, and every
decision section must carry real content; `--check` refuses the document otherwise.

Answered items: once the human has answered an item at a checkpoint, record it in RUN_LOG.md under
`## Answered` as a line `- answered <anchor> (<date>, <round>): <answer>`, where <round> is the
round DECISIONS.md was written for. The next skeleton lists it under "Previously answered" (once
per matter) instead of asking again -- under a delegating level an answer carrying that level's
[DELEGATED] tag is a decision taken on the reader's behalf and keeps its section, its Decision taken
filled from the log (B11) -- unless it was asked again since: a QUESTION or CHECK row in a LATER round
(rounds are ordered, not compared by date), or new content. Items whose content can change carry
a content hash in their anchor (`approval:<round>@<hash>`, `global:G1@<hash>`, ...), so a new
approval, new sheet text or new commits are a new item; the old answer is shown next to it. A defect or
vacuity record's hash covers its substance only (location, printed statement, status, repair), never its prose
(trial #8: a reworded reason re-asked two answered defects).

  python3 audits/decisions.py --write   [--round R --allow-older] [--out PATH]   # skeleton: <rounds_dir>/DECISIONS.md
  python3 audits/decisions.py --check   [--round R --allow-older] [--file PATH]  # completeness gate before delivery
  python3 audits/decisions.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import argparse, glob, hashlib, json, os, re, shutil, subprocess, tempfile

import project

FILL = "<<FILL"
ANCHOR_RE = re.compile(r"<!--\s*item:([\w.:/@+-]+)\s*-->")
ROUND_TAG_RE = re.compile(r"<!--\s*decisions-round:\s*(\S+)\s*-->")
# a [PROXY] decision: the dated tag, or the bare tag where a decision is recorded ("approver [PROXY]",
# at the start of an entry, or opening a quoted answer) -- not prose that merely mentions one
PROXY_RE = re.compile(r'\[PROXY \d{4}-\d{2}-\d{2}|(?:^|\bapprover |["“]|^- )\[PROXY\]', re.M)
# a [DELEGATED] decision: taken by the operator under the involvement level chosen at intake
# (RUN.md, intake question 5c), final rather than provisional. The dated tag only, so prose that
# merely talks about delegated decisions is not one.
DELEGATED_RE = re.compile(r"\[DELEGATED \d{4}-\d{2}-\d{2}")
# What reversing it would cost the reader: nothing; new proofs; a new sign-off of statements; a new
# audit round. The tag states it instead of a blanket "reversible".
REVERSAL_COSTS = ("none", "re-prove", "re-approve", "new round")
# the one canonical form (RUN.md, "Involvement levels and delegated decisions"):
#   [DELEGATED 2026-10-18, operator under hands-off (intake); reversal: re-prove]
DELEGATED_TAG_RE = re.compile(r"\[DELEGATED (\d{4}-\d{2}-\d{2}), operator under (statements-only|hands-off) "
                              r"\(intake\); reversal: (none|re-prove|re-approve|new round)\]")
# anything that looks like a [DELEGATED …] tag, in any case or spacing: linted, so a variant
# ("[Delegated …]", "[DELEGATED]", two spaces) cannot slip past the strict pattern unseen
DELEGATED_LOOSE_RE = re.compile(r"\[\s*delegated\b[^\]\n]*\]?", re.I)
# Trial #11: a BARE tag ("[DELEGATED]", nothing inside) is never counted as a decision (DELEGATED_RE
# wants the date), so it can only be a decision written in the wrong form where it stands as one:
# opening an entry, or after the entry's anchor or label ("- check:x: [DELEGATED] keep …", optionally
# opening a quote). There it is linted as every other variant; anywhere else -- mid-sentence prose
# ("QUESTION 1 decided [DELEGATED]"), a code span, or a line stops.py wrote under `## Stops` (its
# text is the operator's or the human's own words about a stop, never a decision) -- it is a
# mention. A tag with anything inside ("[DELEGATED 2026-…]", "[Delegated, operator]") is linted
# wherever it stands: a dated one IS counted as a decision (delegated_entries).
BARE_TAG_RE = re.compile(r"\[\s*(?:delegated|proxy)\s*\]", re.I)
DECISION_POS_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:[^\n]*:\s*)?[\"“'‘]?\s*$")
# the head of every `## Stops` line stops.py (and project.intake_move) writes
STOPS_LINE_RE = re.compile(r"^\s*[-*]\s+(?:\[[^\]\n]*\]\s+)?(?:stop [SP]\d+\b|[DP]\d+ \(|repair-lock )")
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")


def mentions_masked(log):
    """RUN_LOG.md with every bare [DELEGATED]/[PROXY] that is a MENTION, not a decision position,
    written without its brackets: one inside a code span, one in a stops.py line under `## Stops`,
    and a bare [DELEGATED] mid-sentence. A bare tag where a decision is recorded, and every tag with
    anything inside it, stays as written (so the tag checks still see it)."""
    out, sec = [], ""
    for line in (log or "").splitlines(keepends=True):
        if line.startswith("## "):
            sec = line[3:].strip()
        stop_line = sec.split(" (")[0] == "Stops" and STOPS_LINE_RE.match(line)
        spans = [m.span() for m in CODE_SPAN_RE.finditer(line)]

        def keep(m):
            if stop_line or any(a < m.start() < b for a, b in spans):
                return False
            # [PROXY] keeps PROXY_RE's own positions (it also reads "approver [PROXY]" and a quoted
            # answer opening with it mid-line as a decision)
            return "proxy" in m.group(0).lower() or bool(DECISION_POS_RE.match(line[:m.start()]))
        out.append(BARE_TAG_RE.sub(lambda m: m.group(0) if keep(m) else
                                   m.group(0).strip("[] \t").upper(), line))
    return "".join(out)


# what a delegated decision may follow (RUN.md, "How you decide"): an independent agent's written
# recommendation, or the conservative rule -- never a recommendation the operator wrote itself
FOLLOWED = ("adjudicator's recommendation", "conservative rule", "human at checkpoint b",
            # a stop the operator closed (stops.py close --delegated): its cause's row of the cause
            # table (project.CAUSES), cited by its record `stops/S<n>/`
            "cause table")
GLANCE_HEADING = "## At a glance: decisions taken on your behalf"
# RUN_LOG.md sections whose [DELEGATED] lines ANSWER items already in a decisions document (the
# delegated Checkpoint C): they are listed under "Previously answered", never new items
DELEGATED_SKIP_SECTIONS = ("Fresh readers", "Answered", "Checkpoint C")
# the sentence a delegated document must keep, per level (who did NOT review what)
DISCLOSURE = {
    "hands-off": "No human reviewed the Lean statements or any decision below.",
    "statements-only": "No human reviewed any decision below, except sections whose Decision taken "
                       "says Not applicable, which the human decided at Checkpoint B.",
}
LABELS = ("**Paper**", "**Lean**", "**Evidence**", "**Options", "**Recommendation")
PLACEHOLDER_WORDS = re.compile(r"\b(TODO|TBD|FIXME)\b")
# Claims the record cannot establish (test-run audit, caveat 1): drafts of proofs existed before the
# approval there, and the deliverables said the opposite. The fingerprints prove the statements did
# not change, not when proofs were written.
UNVERIFIABLE_ORDER = re.compile(r"before any proofs? (?:was|were|had been) (?:written|drafted|started)"
                                r"|then the proofs were (?:written|drafted)", re.I)
FIELD_LABEL_RE = re.compile(r"^\W*\*\*(Paper|Lean|Evidence|Options|Recommendation|Decision taken)\b[^*\n]*\*\*", re.M | re.I)
BOX_START = "> **READ THIS FIRST**"
# sections of RUN_LOG.md that RECORD answers or checks rather than decisions taken by proxy
# RUN_LOG.md sections that record CHECKS, not decisions (a dismissal there may quote "[PROXY]").
# [PROXY] answers recorded under `## Answered` or `## Checkpoint C` stay items: the human confirms them.
LOG_SKIP_SECTIONS = ("Fresh readers",)
NUM_RE = re.compile(r"\b\d+(?:\.\d+)+\b|\btex (?:l\.)?\d+\b")
STANDING_RE = re.compile(r"\(standing:\s*([A-Za-z0-9._-]+)\)")


def _read(p):
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def table_rows(text):
    """[(header cells, row cells)] for every markdown table in text (separator rows skipped)."""
    out, header = [], None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cells = project.split_row(line)
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = [c.lower().strip("* ") for c in cells]
            continue
        if project.superseded_row(cells):
            continue        # a row an adjudication superseded (forgery review H1): kept in the file, read by nobody
        out.append((header, cells))
    return out


def anchor_id(kind, text):
    """A stable, comment-safe anchor: `kind:<slug>` for short names, else `kind:<slug>-<hash>`."""
    t = text.strip()
    # word characters in any script: `α_two` stays `α_two` (an ASCII-only slug made it `__two-<hash>`,
    # mini2 audit)
    slug = re.sub(r"[^\w.:/@+-]+", "_", t)[:80]
    if t and len(t) <= 80 and slug == t.replace(" ", "_"):
        return f"{kind}:{slug}"
    return f"{kind}:{slug[:40]}-{hashlib.sha1(t.encode()).hexdigest()[:10]}"


# churn that must not re-ask an item: Lean line citations, tex line citations, commit hashes (hex
# runs with both a letter and a digit -- "effaced" or "1000000" are content)
LEAN_CITE_RE = re.compile(r"\b[\w/]+\.lean:\d+(?:\s*[,–-]\s*:?\d+)*"
                          r"|\btex (?:l\.\s*~?|lines? )?\d+(?:\s*(?:[–-]|,)\s*\d+)*"
                          r"|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")


def defect_rows(root):
    """[(header, cells)] of PAPER_DEFECTS.md's defects table as make_report.defects_table parses it (its whole
    `## Defects` section; B3 attack fixes): the box, the items and the report read the same rows."""
    import make_report as _mr
    head, rows, _, _ = _mr.defects_table(os.path.join(root, "PAPER_DEFECTS.md"))
    return [(head, r) for r in rows]


def is_defect_header(header):
    """A PAPER_DEFECTS.md defects table: `status` and `repair` (B3), or the old `severity` column (PENDING[adj-record]
    in make_report until the adjudicator rewrites it; its rows stay items meanwhile)."""
    return ("status" in header and "repair" in header) or "severity" in header


def defining(header, cells, cols):
    """The text that DEFINES a record row, for its anchor hash: only the named columns (matched by
    the start of the header), with File.lean:N citations and commit hashes removed -- refreshing a
    line number or a commit must not turn an answered item into a new one."""
    out = []
    for c in cols:
        i = next((k for k, h in enumerate(header) if h.startswith(c)), None)
        if i is not None and i < len(cells):
            out.append(LEAN_CITE_RE.sub("", cells[i]))
    return re.sub(r"\s+", " ", " | ".join(out)).strip().lower()


def unused_hypotheses(root, legacy=False):
    """[(declaration, [argument text])] from the approved-statements section of UNUSED_ARGS.md. unused_args.py
    writes a declaration's arguments on one line ("- `P.lemma_2_6`: argument 2: (hx : 0 < x); argument 4: (hy : y ≠
    0)"); conf1 (C1 audit): only the first "argument N:" was taken off, so the summary read "`(hx : 0 < x); argument
    4: (hy : y ≠ 0)`". Each argument is its own item now. `legacy`: the text as it was read before (the rest of the
    line after the first "argument N:"), which the keep/drop item's anchor hashes, so an answer logged under it
    still answers the item."""
    sec = re.split(r"^## ", _read(os.path.join(root, "UNUSED_ARGS.md")), flags=re.M)
    sec = next((x for x in sec if x.startswith("Approved statements")), "")
    out = {}
    for m in re.finditer(r"^- `([^`]+)`: argument \d+: (.+?)\s*$", sec, re.M):
        out.setdefault(m.group(1), []).extend(
            [m.group(2)] if legacy else [a for a in re.split(r";\s+argument \d+:\s+", m.group(2)) if a])
    return list(out.items())


def versioned(kind, ident, content):
    """`kind:<ident>@<hash>`: an anchor that changes when the content does, so an answer to an
    earlier version does not hide the new one."""
    base = anchor_id(kind, ident)
    return f"{base}@{hashlib.sha1(str(content).encode()).hexdigest()[:8]}"


# Trial #8 (involved): an answered matter is the same matter while its SUBSTANCE is -- what the human decides on:
# the location and printed statement, the status, the repair -- never because the record's prose changed. A
# reader-fix round added glossary sentences ("Terms used in this row: ...") to two defect rows' reasons; their
# anchors, which hashed every prose column, changed, and the human was asked them a third time. The anchors hash
# only these columns now; the old (prose-hashing) anchors are kept as LEGACY ones, so an answer logged under one
# still answers the row while its substance is unchanged (legacy_aliases, from the record's history).
DEFECT_SUBSTANCE = ("where", "status", "repair", "severity", "what")
DEFECT_LEGACY = ("where", "status", "repair", "severity", "what", "why", "consequence")
VACUOUS_SUBSTANCE = ("statement", "for which", "param", "status")
VACUOUS_LEGACY = ("statement", "for which", "param", "why", "decision", "status")


def defect_anchor(header, cells, legacy=False):
    """The decision item's anchor of a PAPER_DEFECTS.md defects row: identity = the row number (rows are never
    removed) plus the location without citations; hashed = its substance (DEFECT_SUBSTANCE; B3: an old-format
    `severity` row keeps its own columns). `legacy`: the anchor before trial #8, which also hashed the prose."""
    return versioned("defect", f"{cells[0]}-" + LEAN_CITE_RE.sub("", cells[1]).strip()[:60],
                     defining(header, cells, DEFECT_LEGACY if legacy else DEFECT_SUBSTANCE))


def vacuous_anchor(header, cells, legacy=False):
    """The decision item's anchor of a VACUOUS.md row (shared with make_report.decided_since): hashed = its
    substance (VACUOUS_SUBSTANCE); `legacy`: the anchor before trial #8 (also the reason and decision prose)."""
    st = cells[_idx(header, "statement")]
    # identity without line citations: a refreshed `File.lean:N` must not make the row a new item
    return versioned("vacuous", f"{cells[0]}-" + LEAN_CITE_RE.sub("", st).strip(),
                     defining(header, cells, VACUOUS_LEGACY if legacy else VACUOUS_SUBSTANCE))


def record_versions(root, name):
    """[(commit or None, text)] of the record `name` in the rounds dir `root`: every committed version, oldest first,
    then the working copy (commit None). [] when it never existed."""
    out = []
    top, rel = project.rounds_rel(root, name)
    if top:
        r = subprocess.run(["git", "-C", top, "log", "--reverse", "--format=%H", "--", rel], capture_output=True,
                           text=True)
        for h in (r.stdout.split() if r.returncode == 0 else []):
            t = subprocess.run(["git", "-C", top, "show", f"{h}:{rel}"], capture_output=True, text=True)
            if t.returncode == 0:
                out.append((h, t.stdout))
    p = os.path.join(root, name)
    if os.path.exists(p):
        out.append((None, _read(p)))
    return out


def record_rows_of(name, text):
    """[(anchor, legacy anchor, label)] of the decision rows of one version `text` of PAPER_DEFECTS.md or
    VACUOUS.md, as the skeleton reads them (defect_rows, table_rows); `label` names the row's paper result."""
    out = []
    if name == "PAPER_DEFECTS.md":
        d = tempfile.mkdtemp(prefix="decisions-rec-")
        try:
            open(os.path.join(d, name), "w", encoding="utf-8").write(text)
            for header, cells in defect_rows(d):
                if is_defect_header(header) and len(cells) >= len(header):
                    out.append((defect_anchor(header, cells), defect_anchor(header, cells, legacy=True),
                                LEAN_CITE_RE.sub("", cells[1])))
        finally:
            shutil.rmtree(d, ignore_errors=True)
    else:
        for header, cells in table_rows(text):
            if _idx(header, "statement") is not None and len(cells) >= len(header):
                if "status" in header and is_repaired(cells[header.index("status")]):
                    continue
                out.append((vacuous_anchor(header, cells), vacuous_anchor(header, cells, legacy=True),
                            LEAN_CITE_RE.sub("", cells[_idx(header, "statement")])))
    return out


RECORD_FILES = ("PAPER_DEFECTS.md", "VACUOUS.md")


def legacy_aliases(root):
    """{legacy anchor: substance anchor} over every version of the defect and vacuity records (record_versions):
    an answer logged under a row's pre-trial-#8 anchor answers the row while its substance is the same."""
    out = {}
    for name in RECORD_FILES:
        for _, text in record_versions(root, name):
            for a, la, _ in record_rows_of(name, text):
                if la != a:
                    out[la] = a
    return out


def is_repaired(status):
    """A VACUOUS.md row is repaired only when its status says so with a commit; a blank or
    misspelt status keeps it open (an edited cell must not hide a row from the human)."""
    return re.match(r"^\W*repaired in [0-9a-f]{7,}", status.strip(), re.I) is not None


def latest_signoff(rounds, appr):
    """(round dir, SIGNOFF.json): the APPROVED sheet's round if there is an approval, else the newest
    round with a sheet."""
    want = (appr or {}).get("round")
    for d in reversed(rounds):
        p = os.path.join(d, "SIGNOFF.json")
        if os.path.exists(p) and (not want or os.path.basename(d) == want):
            return d, json.load(open(p, encoding="utf-8"))
    for d in reversed(rounds):
        p = os.path.join(d, "SIGNOFF.json")
        if os.path.exists(p):
            return d, json.load(open(p, encoding="utf-8"))
    return None, {}


def question_rows(rounds):
    """{item: [(round name, lane, reason), …]} for every QUESTION decision in any round's ADOPTED.md.
    The decision is read from the table's `decision` column, not from anywhere in the line."""
    import lanecheck
    out = {}
    for d in rounds:
        # THE reader (lanecheck.decision_rows, R3e); every QUESTION row is listed, valid or not
        for r in lanecheck.decision_rows(d):
            if r.decision.startswith("QUESTION"):
                out.setdefault(r.item, []).append((os.path.basename(d), r.lane, r.reason))
    return out


def delegated_stops(cfg):
    """{S<n>} of every stop the operator closed under a delegating level (stops.py close --delegated)."""
    import stops
    return {r["stop"] for r in stops.stop_rows(cfg) if r["by"].startswith("the operator")}


def open_revotes(rounds):
    """[(round, lane, item, reason, abandoned)] for every REVOTE NEEDED row of any round's ADOPTED.md
    that no later row of the same file settles: a re-vote left unsettled. Rows are read by THE strict
    reader (lanecheck.decision_rows, R3e) and keyed by (lane, item): only a later row of the SAME lane
    and item settles it -- a QUESTION (the human decides), or an ADOPT, REJECT or DEFER the re-vote
    rules accept (lanecheck.revote_decision_problems). A `(whole lane)` row is settled once its
    whole-lane re-vote settled the lane's items (lanecheck.whole_lane_settled). A row naming no lane or
    item of the round exactly settles nothing (the settle check refuses it) and, if it asks for a
    re-vote, is listed. `abandoned` is True when a re-vote lane covering the item was set aside
    (stops.py set-aside --lane; a whole-lane --ALL* included). The human must see each (a test run left
    one out of the report)."""
    import lanecheck
    out = []
    for d in rounds:
        rows, pending = lanecheck.decision_rows(d), {}
        good = [r for r in rows if r.problem is None]
        for r in rows:
            key = (r.base, r.item) if r.problem is None else ("?", r.lane, r.item)
            if r.decision.startswith("REVOTE NEEDED"):
                pending.setdefault(key, r)
            elif r.problem is None and r.item != lanecheck.WHOLE_LANE and key in pending and (
                    r.decision.startswith("QUESTION") or (re.match(r"(ADOPT|REJECT|DEFER)\b", r.decision)
                                                         and not lanecheck.revote_decision_problems(d, only={key}))):
                pending.pop(key)
        for key, r in pending.items():
            if r.problem is None and r.item == lanecheck.WHOLE_LANE and \
                    lanecheck.whole_lane_settled(d, r.lane, good, good.index(r)):
                continue
            ab = r.problem is None and bool(lanecheck.set_aside_revote(d, r.lane, r.item))
            out.append((os.path.basename(d), r.lane, r.item, r.reason, ab))
    return out


def asked_after(order, asked_round, ans_round, ans_date):
    """Was an item asked again (in `asked_round`) after it was answered? Rounds are compared by
    their order; an answer without a round (older format) counts as answered before any same-day
    asking."""
    if not asked_round:
        return False
    if ans_round in order and asked_round in order:
        return order.index(asked_round) > order.index(ans_round)
    return not ans_date or round_date(asked_round) >= ans_date


# The stage2 step 5 form of a [DELEGATED] answer to a QUESTION row, logged under `## Open questions`
# with no anchor: "(QUESTION row on <item>, round <R>)" or "the QUESTION row on <item> of round <R>";
# "(QUESTION row, round <R>)" answers a round that asked exactly one question. The round token is
# exact (nothing may follow it but a non-name character).
QROW_RE = re.compile(r"QUESTION row(?: on (?P<item>[^\n]+?))?(?:,| of) round "
                     r"(?P<round>\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40})(?![\w-])")


def needs_human(cfg, rounds):
    """predicate(round name): is a QUESTION row of that round the human's to answer, so that no
    operator line ([DELEGATED] or not) closes it? RUN.md's level table: under `involved` every
    question; under `statements-only` a Checkpoint B question -- a statement round's, or any round's
    up to the approved one (all of them before an approval exists); under `hands-off` none."""
    lvl = project.involvement(cfg)
    if lvl == "hands-off":
        return lambda r, item=None: False
    if lvl != "statements-only":
        return lambda r, item=None: True
    order = [os.path.basename(d) for d in rounds]
    kinds = {os.path.basename(d): project.round_kind(d) for d in rounds}
    try:
        appr = (approval(cfg) or {}).get("round")
    except (OSError, ValueError):
        appr = None
    # B2 (U2 §0, decision 5): a change to a statement the human approved is the human's too -- a QUESTION
    # row on a declaration of the open re-approval question, whichever round asked it
    q = reapproval_question(cfg)
    qd = set((q or {}).get("decls") or [])
    qd |= {d.rsplit(".", 1)[-1] for d in qd}
    return lambda r, item=None: (kinds.get(r) == "statements" or appr not in order or r not in order
                                 or order.index(r) <= order.index(appr)
                                 or (item is not None and str(item).strip().strip("`") in qd))


def reapproval_question(cfg):
    """The open re-approval that is the human's QUESTION (U2 §3, §5), or None: {"decls", "reason", "date",
    "why"}. A re-approval is begun (signoff.py reapprove --begin) and not yet closed, and the agent may not
    approve it (project.agent_may_reapprove: involved or statements-only unless 5d chose the agent, or a
    replaced approval that was a human's). While it is open the PENDING STATE holds: rounds, Phase 0
    (read-only too), pending_unproved and the axiom sweep allow `sorry` in its declarations' proofs and
    sorryAx reaching other results only through them (pending_reapproval); only `project.py --deliver`
    refuses. A record the freeze check cannot trust is no question (it is FAIL[reapproval-record])."""
    import fingerprint
    rdir = os.path.join(project.REPO, cfg["rounds_dir"])
    try:
        doc, prob = fingerprint.open_reapproval(rdir, project.REPO, cfg)
    except Exception:      # noqa: BLE001 -- no trusted record, no pending state
        return None
    if not doc or prob:
        return None
    ok, why = project.agent_may_reapprove(cfg, fingerprint.replaced_approval(rdir, cfg))
    if ok:
        return None
    b = (doc.get("begins") or [{}])[-1]
    return {"decls": sorted(doc.get("decls") or []), "reason": b.get("reason", "?"), "date": b.get("date", "?"),
            "why": why}


def pending_reapproval(cfg, goals=None):
    """[decl] in the pending state (reapproval_question): its `sorry` and sorryAx reaching other results only
    through it pass every check but --deliver. A goal result is never pending (one found false is stop 1)."""
    q = reapproval_question(cfg)
    if not q:
        return []
    gd = goal_decls(cfg) if goals is None else set(goals)
    ns = cfg.get("namespace", "")
    return [d for d in q["decls"] if not ({d, f"{ns}.{d}"} & gd)]


def question_refusal(cfg):
    """The refusal of `project.py --deliver` while a level-reserved QUESTION is open (the re-approval the
    human must answer; under `involved`, Checkpoint C: checkpoint_c_refusal), or None. Not a stop: the run
    goes on; only the delivery waits."""
    q = reapproval_question(cfg)
    if not q:
        return checkpoint_c_refusal(cfg)
    return (f"a QUESTION is open: the change to {', '.join(q['decls'])} (re-approval begun {q['date']}: "
            f"{q['reason']}) awaits the human's approval ({q['why']}). Not a stop: the run goes on; deliver "
            f"after `signoff.py approve --by human` closes it (run/reapproval.md)")


def checkpoint_c_open(cfg):
    """B12 (U2 §0, §6.7): under `involved` Checkpoint C is the human's QUESTION, asked on the prepared
    documents BEFORE delivery. [anchor] of every item the decisions document asks now (decisions.py
    --write's items for the newest round: never answered, or asked again since) and of every current item
    whose only answer is the operator's (a [PROXY] or [DELEGATED] line under `## Answered`): delivery waits
    until the human's answers are logged (stage5-delivery.md step 6). [] under a delegating level (C is
    delegated there, stage5 step 4), and with no round."""
    if project.involvement(cfg) != "involved":
        return []
    rounds = project.rounds(cfg)
    if not rounds:
        return []
    _, anchors = skeleton(cfg, rounds, rounds[-1])
    byop = [a for a, line in getattr(skeleton, "answered_current", []) if not human_answer(line)]
    return list(dict.fromkeys(list(anchors) + byop))


def human_answer(line):
    """Is the `## Answered` line `line` (answered()'s text: `answered <anchor> (<date>, <round>): <answer>`)
    an answer of the human's for Checkpoint C? Not when the answer has no content (B12 review fix 1: an
    empty `answered <anchor> (...):` answers nothing), nor when it carries the operator's tag, a [PROXY]
    or [DELEGATED] anywhere in it, quoted or not (review fix 2: quote-stripping hid `"[DELEGATED …] keep"`).
    The human confirming a [PROXY] decision answers in their own words; the tag stays on the decision."""
    ans = ANSWER_PREFIX_RE.sub("", line, count=1)
    if not re.search(r"\w", ans):
        return False
    return not OPERATOR_TAG_RE.search(ans) and not OPERATOR_SOURCE_RE.search(ans)


OPERATOR_TAG_RE = re.compile(r"\[\s*(?:proxy|delegated)\b", re.I)
# integrated review fix 7: the sources the operator cites for a decision it takes (RUN.md "How you decide"): an
# escalation's answer ("escalation E<n>", accepted by lanecheck.py), an adjudicator's record (a round's ADOPTED.md, a
# round name) or the conservative rule. Under `involved` a Checkpoint C answer citing one is the operator's
# decision, never the human's: an escalation or adjudicator is not the human, and the human answers in their words
OPERATOR_SOURCE_RE = re.compile(r"\bescalation (?:check )?E[0-9]+\b|\bADOPTED\.md\b|\bconservative rule\b|"
                                r"\b\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40}\b", re.I)


def checkpoint_c_refusal(cfg):
    """The `--deliver` refusal while Checkpoint C is open under `involved` (checkpoint_c_open), or None.
    Fails closed: a record the decisions skeleton cannot read keeps the delivery waiting, with the reason."""
    try:
        open_ = checkpoint_c_open(cfg)
    except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
        return (f"Checkpoint C could not be computed ({type(e).__name__}: {e}); `decisions.py --check` names "
                f"the record it cannot read")
    if not open_:
        return None
    return (f"Checkpoint C is open: {len(open_)} item(s) of the decisions document await the human's answer "
            f"({', '.join(open_[:4])}{', ...' if len(open_) > 4 else ''}). Under `involved` C is asked on the "
            f"prepared documents before delivery (stage5-delivery.md step 6): log each answer under `## Answered` "
            f"(`- answered <anchor> (<date>, <round>): <their answer>`, in the human's own words; an empty answer, a [PROXY] or [DELEGATED] line, or one citing an escalation, an adjudicator's record or the conservative rule answers nothing), carry the "
            f"answers out (step 7), then deliver. Not a stop: only the delivery waits")


def open_question_rows(cfg, rounds):
    """[(round, lane, item, reason, note)] for every QUESTION row of EVERY round's ADOPTED.md whose
    item has no final answer -- cumulative, not just the newest round's (a question carried from an
    earlier round used to vanish from the report when a later round raised none; Codex sparse-note
    run, 2026-10-19). Final answers are kept out: a `## Answered` line for the item's
    `question:<item>` anchor (unless the item was asked again after it), or a [DELEGATED] decision
    on that anchor or in the stage2 form (QROW_RE); those are in DECISIONS.md and RUN_LOG.md. A
    [PROXY] answer is not final: the row stays, with a note. A [DELEGATED] decision counts only in
    the canonical tag of the configured, delegating level, and never for a question that needs the
    human (needs_human): that row stays, with a note. Rows are in round order."""
    root = os.path.join(project.REPO, cfg["rounds_dir"])
    log = _read(os.path.join(root, "RUN_LOG.md"))
    done = answered(log)
    lvl = project.involvement(cfg)
    delegating = lvl in ("hands-off", "statements-only")
    human = needs_human(cfg, rounds)
    deleg = {}
    for pre, tagged in delegated_entries(log):
        m = DELEGATED_TAG_RE.match(tagged)
        if m and delegating and m.group(2) == lvl:
            deleg[pre] = max(deleg.get(pre, ""), m.group(1))
    order = [os.path.basename(d) for d in rounds]
    qrows = question_rows(rounds)
    per_round = {}
    for item, asks in qrows.items():
        for r, _, _ in asks:
            per_round.setdefault(r, set()).add(item)
    # A [DELEGATED] line with no anchor decides a round's asking only in the strict form (the
    # small-paper run's three lines; review of fix-mini1, H1): a top-level line of `## Open questions`
    # that BEGINS with the canonical tag of the configured delegating level, in the stage2 form
    # (QROW_RE) naming exactly that round, dated no earlier than the round, naming the item exactly
    # (or no item, when the round asked one question). Rounds the line names in passing count for
    # nothing; so does a line anywhere else.
    free = []
    for ln in section(log, "Open questions").splitlines():
        m0 = re.match(r"(?:[-*][ \t]+)?" + DELEGATED_TAG_RE.pattern, ln)
        if not m0 or not delegating or m0.group(2) != lvl:
            continue
        q = QROW_RE.search(ln, m0.end())
        if q:
            it = (q.group("item") or "").strip().strip("`").strip().lower()
            free.append((m0.group(1), it or None, q.group("round")))

    def named(item, r):
        return any(rr == r and day >= round_date(r)
                   and ((it == item.lower()) if it else len(per_round[r]) == 1)
                   for day, it, rr in free)
    HUMAN = (f"an operator decision does not answer it: under the level '{lvl}' this question is the "
             "human's")
    out = []
    for item, asks in qrows.items():
        notes = {}
        for x in asks:
            if named(item, x[0]) and human(x[0], item):
                notes[x] = HUMAN
        asks = [x for x in asks if human(x[0], item) or not named(item, x[0])]
        if not asks:
            continue
        a = anchor_id("question", item)
        if a in done:
            line, when, ans_round = done[a]
            again = [x for x in asks if asked_after(order, x[0], ans_round, when)]
            # an operator's [DELEGATED] answer under `## Answered` answers no question that needs the human
            byop = DELEGATED_LOOSE_RE.search(line)
            keep_h = [x for x in asks if byop and human(x[0], item) and x not in again]
            for x in keep_h:
                notes[x] = HUMAN
            if again:
                for x in again:
                    notes.setdefault(x, f"answered earlier ({line[:120]}), asked again since")
                asks = again + keep_h
            elif PROXY_RE.search(line):
                for x in asks:
                    notes.setdefault(x, "provisional [PROXY] answer, awaiting the human's confirmation")
            elif keep_h:
                asks = keep_h
            else:
                continue
        elif a.lower() in deleg:
            # a delegated decision is final -- unless a later round asked the question again
            # a [DELEGATED] tag carries a date, not a round: it answered the askings dated before it,
            # or (if none) the first asking of that day; a later round -- even the same day -- asking
            # it again is a re-ask (round order, as for answers). It answers no asking that needs the human.
            dd = deleg[a.lower()]
            keep_h = [x for x in asks if human(x[0], item)]
            for x in keep_h:
                notes[x] = HUMAN
            mine = [x for x in asks if not human(x[0], item)]
            idx = lambda r: order.index(r) if r in order else -1
            before = [x for x in mine if round_date(x[0]) < dd]
            same = sorted((x for x in mine if round_date(x[0]) == dd), key=lambda x: idx(x[0]))
            upto = max((idx(x[0]) for x in before + same[:1]), default=10 ** 9)
            again = [x for x in mine if idx(x[0]) > upto]
            for x in again:
                notes.setdefault(x, f"decided as [DELEGATED] on {dd}, asked again since")
            asks = again + keep_h
            if not asks:
                continue
        out += [(r, l, item, why, notes.get((r, l, why), "")) for r, l, why in asks]
    return sorted(out, key=lambda t: (order.index(t[0]) if t[0] in order else -1, t[2]))


def proposed_standing(rounds, cfg):
    """{rule id: [round names]} for standing defers that ADOPTED.md rows invoke but the config lacks."""
    have = {s.get("id") for s in cfg.get("standing_defers", [])}
    out = {}
    for d in rounds:
        for m in STANDING_RE.finditer(_read(os.path.join(d, "ADOPTED.md"))):
            if m.group(1) not in have:
                out.setdefault(m.group(1), [])
                if os.path.basename(d) not in out[m.group(1)]:
                    out[m.group(1)].append(os.path.basename(d))
    return out


def log_entries(run_log):
    """Entries of RUN_LOG.md: each bullet with its continuation lines, or each paragraph."""
    blocks, cur = [], []
    for line in run_log.splitlines():
        starts = line.startswith("- ") or line.startswith("#") or not line.strip()
        if starts and cur:
            blocks.append("\n".join(cur)); cur = []
        if line.startswith("#") or not line.strip():
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def section(run_log, title):
    m = re.search(rf"^## {re.escape(title)}\b.*?$(.*?)(?=^## |\Z)", run_log, re.M | re.S)
    return m.group(1) if m else ""


ANSWER_LINE_RE = re.compile(r"^\s*[-*]\s+answered\s+(\S+?)(?=[\s(]|$)(?:\s*\((\d{4}-\d{2}-\d{2})(?:,\s*([^)\s]+))?\))?", re.I)
# the "answered <anchor> (<date>, <round>):" head of an answer line: shown once, not per entry (B11)
ANSWER_PREFIX_RE = re.compile(r"^\s*answered\s+\S+?(?=[\s(]|$)\s*(?:\([^)\n]*\))?\s*:?\s*", re.I)
QUOTED_RE = re.compile(r'"[^"\n]*"|“[^”\n]*”')
TAG_RE = re.compile(r"\[PROXY[^\]\n]*\]", re.I)


def answered_scan(log):
    """RUN_LOG.md with its `## Answered` sections rewritten for the [PROXY] scan.

    Under `## Answered` a quoted tag ("…[PROXY …]…") is a QUOTATION -- set aside -- only when its
    whole quoted text also stands unquoted elsewhere in the log (the decision it quotes, which is an item of
    its own). Otherwise the quotes are dropped and the tag stays: the record writes its own proxy
    answers as `Answer: "[PROXY 2026-10-13, operator …] …"`. Every remaining tag, dated or not, in
    any case and anywhere on a line, then starts an entry of its own, so the scan sees it."""
    sec_rx = r"^(## Answered\b.*?)$.*?(?=^## |\Z)"
    norm = lambda x: " ".join(x.lower().split())
    outside = norm(re.sub(sec_rx, "", log, flags=re.M | re.S))

    def quote(m):
        # a quotation only if its WHOLE text stands elsewhere -- a new decision reusing an old
        # tag header ("[PROXY 2026-10-12, operator for the approver …] brand new decision") is not one
        tags = TAG_RE.findall(m.group(0))
        if tags and norm(m.group(0)[1:-1]) in outside:
            return '""'
        return m.group(0)[1:-1] if tags else '""'

    def section_(m):
        t = QUOTED_RE.sub(quote, m.group(0))
        lines = []
        for line in t.splitlines():
            line = re.sub(r"\[proxy", "[PROXY", line, flags=re.I)
            i = line.find("[PROXY")
            if i > 0 and not re.match(r"^\s*-\s*\[PROXY", line):
                lines += [line[:i].rstrip(), "- " + line[i:]]
            else:
                lines.append(line)
        return "\n".join(lines)
    return re.sub(sec_rx, section_, log, flags=re.M | re.S)


def answered(run_log):
    """{anchor: (line, date or '', round or '')} from RUN_LOG.md `## Answered` (every such section);
    a later line for the same anchor wins."""
    out = {}
    for sec in re.findall(r"^## Answered\b.*?$(.*?)(?=^## |\Z)", run_log, re.M | re.S):
        for line in sec.splitlines():
            m = ANSWER_LINE_RE.match(line)
            if m:
                out[m.group(1)] = (line.strip()[2:].strip(), m.group(2) or "", m.group(3) or "")
    return out


CHECKPOINT_ANSWER_RE = re.compile(r"^\s*[-*]\s+human answer\b[^(\n]*\((\d{4}-\d{2}-\d{2})[^)\n]*\)\s*:\s*(.*?)\s*$", re.M)


def checkpoint_answers(log):
    """[(checkpoint "B" or "C", date, words)] of the human's own answers RUN_LOG.md logs under `## Checkpoint B` and
    `## Checkpoint C (<date>)` (`- human answer (<date>…): "<their words>"`, stage2 step 8, stage5 step 6), in log
    order. A delegated Checkpoint C section, an empty answer and an operator-tagged line are not the human's."""
    out = []
    for m in re.finditer(r"^## Checkpoint ([BC])\b([^\n]*)$(.*?)(?=^## |\Z)", log, re.M | re.S):
        if "delegated" in m.group(2).lower():
            continue
        for a in CHECKPOINT_ANSWER_RE.finditer(m.group(3)):
            words = a.group(2).strip()
            if re.search(r"\w", words) and not OPERATOR_TAG_RE.search(words):
                out.append((m.group(1), a.group(1), words))
    return out


def _unquote(t):
    t = " ".join(str(t).split())
    return t[1:-1] if len(t) > 1 and t[0] + t[-1] in ('""', "“”") else t


def answer_occasion(log, line):
    """The checkpoint an `## Answered` line `line` (answered()'s text) records, as ("Checkpoint B" or
    "Checkpoint C", <date>): the checkpoint whose logged answer (checkpoint_answers) the line quotes; None when it
    quotes none (a question answered between checkpoints, a stop). Trial #8: DECISIONS.md showed the Checkpoint C
    answer under the Checkpoint B approval with nothing saying it was given at C."""
    ans = _unquote(ANSWER_PREFIX_RE.sub("", line, count=1))
    for cp, date, words in reversed(checkpoint_answers(log)):
        w = _unquote(words)
        if ans and (ans == w or ans.startswith(w) or w.startswith(ans)):
            return f"Checkpoint {cp}", date
    return None


def when_answered(log, entry):
    """"(<checkpoint> (<date>))" or "(<date>, round <R>)" for an answered() entry (line, date, round)."""
    occ = answer_occasion(log, entry[0])
    if occ:
        return f"(at {occ[0]}, {occ[1]})"
    return "(" + ", ".join(x for x in (entry[1], f"round {entry[2]}" if entry[2] else "") if x) + ")" if (entry[1] or entry[2]) else ""


SHEET_KINDS = ("approval", "global", "check", "notformalized")
B_RECORD_KINDS = ("defect", "vacuous")


def approval_commit(root, rnd):
    """The newest audit commit named "approve <rnd>" (signoff.py approve commits the approval so), or None."""
    top, rel = project.rounds_rel(root, ".")
    if not top:
        return None
    r = subprocess.run(["git", "-C", top, "log", "--format=%H%x09%s"], capture_output=True, text=True)
    for ln in (r.stdout.splitlines() if r.returncode == 0 else []):
        h, _, subj = ln.partition("\t")
        if subj.strip() == f"approve {rnd}":
            return h
    return None


def decided_at_b(cfg, root, appr, sheet_round):
    """Trial #8 (involved): what the HUMAN decided at Checkpoint B, which Checkpoint C must not ask again -- or None
    (another level; no approval by a human, e.g. answer (c)). {"date", "round", "commit", "sheet": the approved
    sheet's items (approval, globals, CHECK rows, not formalized) count as decided (the skeleton reads the approved
    round's sheet: `sheet_round` must be it), "anchors": the defect and vacuity rows present, with the same
    substance (their anchors), in the record at an approval by the human and on a result the approved sheet marks
    CHECK (the human was shown it), "families": {row family: date} of those rows}. A row whose substance changed
    since is asked again; a reworded one is not (defect_anchor)."""
    if project.involvement(cfg) != "involved" or not appr:
        return None
    rd = os.path.join(project.REPO, cfg["rounds_dir"])
    if project.approval_by(appr, rounds_dir=rd)[0] != "human":
        return None
    files = sorted(glob.glob(os.path.join(rd, "APPROVED_FINGERPRINTS.*.json")), key=project.approval_order)
    files.append(os.path.join(rd, "APPROVED_FINGERPRINTS.json"))
    out = {"date": appr.get("date") or "", "round": appr.get("round") or "", "sheet": sheet_round == appr.get("round"),
           "anchors": set(), "families": {}, "commit": approval_commit(root, appr.get("round"))}
    top, _ = project.rounds_rel(root, ".")
    for f in files:
        try:
            doc = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if project.approval_file_by(f, doc)[0] != "human" or not doc.get("round"):
            continue
        c = approval_commit(root, doc["round"])
        sp = os.path.join(rd, doc["round"], "SIGNOFF.json")
        try:
            sheet = json.load(open(sp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        checked = {exact_label(str(r.get("result"))) for r in sheet.get("rows", [])
                   if str(r.get("flag", "")).upper().startswith("CHECK")} - {None}
        if not c or not top:
            continue
        for name in RECORD_FILES:
            _, rel = project.rounds_rel(root, name)
            t = subprocess.run(["git", "-C", top, "show", f"{c}:{rel}"], capture_output=True, text=True)
            if t.returncode:
                continue
            for a, _, label in record_rows_of(name, t.stdout):
                if exact_label(label) in checked:
                    out["anchors"].add(a)
                    out["families"][a.rsplit("@", 1)[0] + "@"] = doc.get("date") or ""
    return out


def round_date(name):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else ""


def approval(cfg):
    p = os.path.join(project.REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json")
    return json.load(open(p)) if os.path.exists(p) else None


def earlier_approvals(cfg):
    out = []
    for f in sorted(glob.glob(os.path.join(project.REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.*.json")),
                    key=project.approval_order):
        try:
            h = json.load(open(f))
            out.append(f"{h.get('date', '?')} by {h.get('by') or 'approver not recorded'}")
        except ValueError:
            pass
    return out


def changes_after(cfg, rounds):
    """[line] describing Lean changes after the last proof-examining round (project.py helper,
    shared with make_report.py so the report and the decisions document cannot disagree)."""
    c = project.changes_after_last_audit(cfg, rounds)
    if c is None:
        return []
    if c["problem"]:
        return [f"UNKNOWN: {c['problem']}"]
    tag = " (comments and docstrings only, verified mechanically)" if c.get("comment_only") else ""
    return [x + tag for x in c["commits"]] + [f"UNCOMMITTED: {p}" for p in c["dirty"]]


_real_changes_after = changes_after


ABBREV = ("e.g", "i.e", "resp", "cf", "al", "Obs", "Fig", "Thm", "Cor", "Lem", "Def", "Prop", "Eq",
          "Sec", "vs", "etc", "approx", "No")


def first_sentence(text, limit=240):
    """The first sentence: up to a full stop followed by a capital letter, but not after a common
    abbreviation ("e.g.", "resp.", "cf.", "Obs.") and never inside a `code span`. Never cut inside the
    sentence (trial #9: a long first sentence was clipped with "…"); `limit` is kept for callers and unused."""
    t = re.sub(r"\s+", " ", text).strip()
    in_code, i = False, 0
    while i < len(t):
        c = t[i]
        if c == "`":
            in_code = not in_code
        elif c == "." and not in_code and re.match(r"\.\s+[A-Z“\"]", t[i:]):
            word = re.search(r"([A-Za-z.]+)$", t[:i])
            if not (word and word.group(1).rstrip(".") in ABBREV):
                t = t[:i + 1]
                break
        i += 1
    return t


def sentences(text):
    """`text` split into its sentences (first_sentence, repeatedly)."""
    t, out = re.sub(r"\s+", " ", text or "").strip(), []
    while t:
        f = first_sentence(t)
        out.append(f)
        t = t[len(f):].strip()
    return out


def why_summary(why):
    """The reason a box line gives for a defect: from the first sentence naming a counterexample (with the
    sentence after it when that one is short, e.g. "Counterexample: x = 4." then the computation), else the
    first sentence. Trial #9 audit: the first sentence of the 'why' cell was a definition (\"X_n denotes the
    sequence ...\"), and the box never showed the counterexample."""
    ss = sentences(why)
    k = next((i for i, x in enumerate(ss) if re.search(r"counter-?example", x, re.I)), None)
    if k is None:
        return ss[0] if ss else ""
    return " ".join(ss[k:k + (2 if len(ss[k]) < 80 else 1)])


def _idx(header, prefix):
    """Index of the first column whose header starts with `prefix`, else None. Prefix, as in
    make_report.record_table: SKIPPED.md's key column is headed "what is not formalized", and an
    exact match on "what" once left every skip out of the page-1 box, silently."""
    return next((k for k, h in enumerate(header) if h.startswith(prefix)), None)


def _col(header, cells, prefix):
    i = _idx(header, prefix)
    return cells[i] if i is not None and i < len(cells) else ""


def witness_free(header, cells):
    """A defect row with no Lean witness: its witness cell names no declaration in backticks ("none:
    confirmed by argument (<where>)"). Such a defect is never dropped (re-check N3): the box and the
    report list it, saying it is confirmed by argument only. A header without a witness column: False."""
    i = next((k for k, h in enumerate(header) if "witness" in h.lower()), None)
    return i is not None and not re.search(r"`[^`]+`", cells[i] if i < len(cells) else "")


SLIPS_HEADING = "Slips in the proofs"


def slip_rows(root):
    """[text] of every entry of PAPER_DEFECTS.md's `## Slips in the proofs` section (a wrong step in a proof
    whose result still holds), in full; the template's parenthetical and a "none" entry are not entries.
    Trial #9: the summary and the box dropped this section, so a slip the record holds reached only the report."""
    sec = section(_read(os.path.join(root, "PAPER_DEFECTS.md")), SLIPS_HEADING)
    out = []
    for b in log_entries(sec):
        if not b.startswith("- "):
            continue
        t = project.full(b[2:])
        if t and t.strip(" .").lower() not in ("none", "none yet", "(none)"):
            out.append(t)
    return out


def box_lines(cfg):
    """The entries the 'Read this first' box must list, from the record, each with a one-sentence
    summary a reader who stops on page 1 can understand (rule 5):
      defect N: <where> (<status>; <repair>): the paper says <printed text>; <what is wrong>. Consequence: ...
      not formalized: <what>: <reason>
      proof route <R>: <result> (<kind>): <why different>
      proof slip: <the slip, in full>
      vacuous: <statement> (for <parameters>): <decision>"""
    root = os.path.join(project.REPO, cfg["rounds_dir"])
    out = []
    for header, cells in defect_rows(root):
        if is_defect_header(header) and len(cells) >= 3:
            said, why, cons = _col(header, cells, "what"), _col(header, cells, "why"), _col(header, cells, "consequence")
            parts = []
            if said:
                # the printed statement in full (trial #9: its first sentence alone read "the paper says
                # Let x be given.", the preamble without the claim), always in quotes, then '; ' and the reason
                # (trials #7, #9 audits: an unquoted or half-quoted statement ran into the reason)
                q_ = project.full(said)
                if not (re.match(r'["“]', q_) and q_.endswith(('"', '”'))):
                    q_ = f"\"{q_}\""
                parts.append("the paper says " + q_)
            if why:
                parts.append(why_summary(why))
            if said:
                summ = parts[0] + ("; " + parts[1].rstrip(".") + "." if len(parts) > 1 else "")
            else:
                summ = ". ".join(x.rstrip(".") for x in parts) + "." if parts else ""
            summ += f" Consequence: {first_sentence(cons)}" if cons else ""
            st_ = "; ".join(cells[header.index(c_)].strip("* ") for c_ in ("status", "repair", "severity")
                            if c_ in header and header.index(c_) < len(cells))
            out.append(f"defect {cells[0]}: {cells[1]} ({st_})"
                       + (f": {summ}" if summ else "")
                       + (" [NO LEAN WITNESS: confirmed by argument only]" if witness_free(header, cells) else ""))
    for t in slip_rows(root):
        out.append(f"proof slip: {t} (the result still holds)")
    for header, cells in table_rows(_read(os.path.join(root, "SKIPPED.md"))):
        if _idx(header, "what") is not None and len(cells) > _idx(header, "what"):
            reason = _col(header, cells, "reason")
            out.append(f"not formalized: {cells[_idx(header, 'what')]}"
                       + (f": {first_sentence(reason)}" if reason else ""))
    # results left unproved by a [DELEGATED] decision (unproved()): stated in Lean, not proved
    for d_, tag in unproved(cfg)["decls"].items():
        out.append(f"stated, not proved: `{d_}` is stated in the Lean but left unproved by the operator "
                   f"({tag}); every result whose proof uses it is listed here too")
    for header, cells in table_rows(_read(os.path.join(root, "DEVIATIONS.md"))):
        if _idx(header, "kind") is not None and len(cells) > _idx(header, "kind"):
            kind = cells[_idx(header, "kind")].strip("* ").lower()
            if kind and kind not in ("same strength", "reading choice"):
                res = cells[header.index("result")] if "result" in header else cells[0]
                why = _col(header, cells, "why")
                out.append(f"proof route {cells[0]}: {res} ({kind})" + (f": {first_sentence(why)}" if why else ""))
    for header, cells in table_rows(_read(os.path.join(root, "VACUOUS.md"))):
        if _idx(header, "statement") is not None and len(cells) > _idx(header, "statement"):
            if "status" in header and len(cells) > header.index("status") \
                    and is_repaired(cells[header.index("status")]):
                continue          # repaired: no longer true of the Lean (rule 4)
            params, dec = _col(header, cells, "for which") or _col(header, cells, "param"), _col(header, cells, "decision")
            out.append(f"vacuous: {cells[_idx(header, 'statement')]}" + (f" (for {params})" if params else "")
                       + (f": {first_sentence(dec)}" if dec else ""))
    # the stops that are decisions: answered by the human, or closed by the operator under a delegating level (a
    # [DELEGATED] decision). A release self-cure and a disclosed fault are the process record (RUN_RECORD.md,
    # approver 2026-10-24), not a decision
    import stops
    for r in stops.stop_rows(cfg, phase="run"):
        if r.get("cured") or r["by"] == "nobody yet" or r.get("core"):
            continue        # a not-verified close is no decision of the author's: RUN_RECORD.md's (approver 2026-10-26)
        # every other closed stop, a late one (closed at delivery) included (mini4/mini5 S1); in full, never clipped
        out.append(f"stop {r['stop']} ({', '.join(r['classes']) or 'no cause class'}; "
                   f"{'answered by the human' if r.get('human') else 'closed by the operator, delegated'}): "
                   f"{' '.join(str(r['what']).split())} -- {' '.join(str(r['by']).split())}")
    return out


def refresh_box(cfg, path=None):
    """Add to DECISIONS.md's 'Read this first' box every entry box_lines now requires that the box
    lacks (a stop or disclosure recorded after the document was written: --deliver calls this). The
    writer's text is kept; nothing is removed. Returns the lines added."""
    p = path or os.path.join(project.REPO, cfg["rounds_dir"], "DECISIONS.md")
    try:
        text = open(p, encoding="utf-8").read()
    except OSError:
        return []
    if BOX_START not in text:
        return []
    i = text.index(BOX_START)
    lines = text[i:].split("\n")
    end = next((k for k, l in enumerate(lines) if not l.startswith(">")), len(lines))
    box = "\n".join(lines[:end])
    add = [f"> - {bl}" for bl in box_lines(cfg) if bl not in box]
    if add:
        lines[end:end] = add
        open(p, "w", encoding="utf-8").write(text[:i] + "\n".join(lines))
    return add


# The writer's prompts are HTML comments: the reader of the filled document sees the field names, not
# five lines of instructions per section (B11: mini6's document was 6.6k words)
FIELDS = ("**Paper:** <!-- location in the source, quoted where wording matters --> " + FILL + " >>\n\n"
          "**Lean:** <!-- declaration and File.lean:N at the document's commit --> " + FILL + " >>\n\n"
          "**Evidence:** <!-- file paths, commands and exit status --> " + FILL + " >>\n\n"
          "**Options, and what each changes:** <!-- re-approval? new round? --> " + FILL + " >>\n\n"
          "**Recommendation:** " + FILL + " >>\n")
# the sixth field of every decision section when the involvement level delegates Checkpoint C
DECIDED_FIELD = ("\n**Decision taken:** <!-- what was done, quoting its tag from RUN_LOG.md, and how to reverse it; "
                 "'Not applicable: <why>' only where the human decided it at Checkpoint B --> " + FILL + " >>\n")
# a section holding several items: one line per item, each with its own tag and reversal cost, as
# their decisions may differ (review of fix-mini2, M1). decisions.py --check requires each line.
MULTI_DECIDED_FIELD = ("\n**Decision taken:** <!-- one line per item below, each naming its item, saying what was done, "
                       "quoting its own tag from RUN_LOG.md and how to reverse it -->\n")


def strip_sections(log, titles):
    """RUN_LOG.md without the `## <title>` sections named."""
    for sec in titles:
        log = re.sub(rf"^## {re.escape(sec)}\b.*?(?=^## |\Z)", "", log, flags=re.M | re.S)
    return log


def delegated_decisions(log):
    """[tagged text] of every [DELEGATED] decision in RUN_LOG.md (the tag and what follows it on
    its line), once each: a delegated Checkpoint C answer is written both under `## Checkpoint C`
    and under `## Answered`, and is one decision. Shared with make_report.py, so the report and
    the decisions document count the same decisions."""
    out, seen, by_text = [], set(), {}
    for pre, t in delegated_entries(log):
        tk = " ".join(t.lower().split())
        k = (pre, tk)
        # the same words under an anchor and under no anchor (logged at Checkpoint B, then
        # re-recorded at C as "- delegated:…: <same text>") are one decision; two ANCHORS decided
        # in the same words are two
        dup_text = tk in by_text and (not ANCHORISH_RE.match(pre) or not all(ANCHORISH_RE.match(p_) for p_ in by_text[tk]))
        if k not in seen and not dup_text:
            out.append(t)
        seen.add(k); by_text.setdefault(tk, set()).add(pre)
    return out


ANCHORISH_RE = re.compile(r"^[a-z-]+:\S+$")


def delegated_by_matter(cfg, log, texts=None):
    """[(matter or None, [tagged text])]: delegated_decisions grouped by the matter their anchor is
    about (matter_of), in the order of each matter's first decision. The report lists one matter
    once (mini2 audit: 23 decisions on about 8 matters, four pages of near-identical entries)."""
    idx, appr_round = decl_results(cfg), (approval(cfg) or {}).get("round")
    try:
        rules = [str(s_.get("id")) for s_ in cfg.get("standing_defers", [])] + list(proposed_standing(project.rounds(cfg), cfg))
    except (OSError, KeyError, ValueError):
        rules = []
    pre_of = {}
    for pre, t in delegated_entries(log):
        pre_of.setdefault(t, pre)
    sec = _delegated_sections(cfg, log)
    groups, order = {}, []
    for t in (delegated_decisions(log) if texts is None else texts):
        pre = pre_of.get(t, "")
        a = pre if ANCHORISH_RE.match(pre) else "delegated:" + pre
        q = QROW_RE.search(t) if a.startswith("delegated:") else None     # B11: as the skeleton groups it
        key = (sec(pre, t) or                                             # trial #10 audit: its DECISIONS.md section
               (rule_matter(rule_named(t, rules)) if rule_named(t, rules) else     # B11 review: as the skeleton
               matter_of(a, t, idx, appr_round, label=q.group("item") if q and q.group("item") else None)))
        k = key or ("\0" + t)
        if k not in groups:
            groups[k] = (key, [])
            order.append(k)
        groups[k][1].append(t)
    return [groups[k] for k in order]


def _delegated_sections(cfg, log):
    """f(anchor-ish prefix, tagged text) -> the matter name of the DECISIONS.md section (skeleton) holding that
    delegated line, else None (no round yet, or the skeleton cannot be built: the old grouping applies). One
    count of matters for the report, the summary and the decisions document (trial #10 audit: 23 decisions on
    10 matters in the report, 7 sections in DECISIONS.md)."""
    if getattr(_delegated_sections, "busy", False):
        return lambda pre, t: None
    _delegated_sections.busy = True
    saved = {k: getattr(skeleton, k) for k in ("sections", "logged", "names", "answered_current", "decided",
                                              "human_decided") if hasattr(skeleton, k)}
    try:
        rs = project.rounds(cfg)
        if not rs:
            return lambda pre, t: None
        skeleton(cfg, rs, rs[-1])
        secs, logged = dict(getattr(skeleton, "sections", {})), dict(getattr(skeleton, "logged", {}))
    except Exception:       # noqa: BLE001 -- the old grouping, never a crash of the report
        return lambda pre, t: None
    finally:
        for k, v in saved.items():
            setattr(skeleton, k, v)
        _delegated_sections.busy = False
    norm = lambda x: " ".join(str(x).split())
    by_anchor = {}
    for a_, kt in secs.items():
        by_anchor.setdefault(a_.split("@")[0].lower(), kt)
    name = lambda kt: (kt[0] if kt[0] and not kt[0].startswith(("\0", "\1"))
                       else re.sub(r" \(\d+ items: .*\)$", "", kt[1]))

    def find(pre, t):
        if ANCHORISH_RE.match(pre or "") and pre.split("@")[0] in by_anchor:
            return name(by_anchor[pre.split("@")[0]])
        hit = [kt for a_, kt in secs.items() if a_.startswith("delegated:") and norm(t) and norm(t) in norm(logged.get(a_, ""))]
        return name(hit[0]) if hit else None
    return find


def delegated_entries(log):
    """[(what the line is about, tagged text)] for every [DELEGATED] line of RUN_LOG.md (Fresh
    readers aside). "What it is about" is the anchor ("- check:x: …", "- answered check:x (date,
    round): …"), or whatever precedes the tag, lower-cased."""
    out = []
    for line in strip_sections(log, ("Fresh readers",)).splitlines():
        m = DELEGATED_RE.search(line)
        if m:
            pre = re.sub(r"^\s*[-*]\s*", "", line[:m.start()])
            pre = re.sub(r"^answered\s+", "", pre, flags=re.I)
            pre = re.sub(r"\(\d{4}-\d{2}-\d{2}[^)]*\)", "", pre)
            out.append((" ".join(pre.strip().rstrip(":—-").split()).lower(), line[m.start():].strip()))
    return out


def tag_problems(log, level=None):
    """[problem] for every [DELEGATED …]-like tag in RUN_LOG.md (Fresh readers aside, which quote)
    that is not in the canonical form, or names another level than the configured one. A bare tag
    that is a mention (mentions_masked) is none."""
    out = []
    for line in mentions_masked(strip_sections(log, ("Fresh readers",))).splitlines():
        for m in DELEGATED_LOOSE_RE.finditer(line):
            c = DELEGATED_TAG_RE.match(line, m.start())
            if not c:
                out.append(f"RUN_LOG.md: {m.group(0)[:70]!r} is not a canonical [DELEGATED] tag "
                           f"('[DELEGATED <date>, operator under <level> (intake); reversal: "
                           f"{' | '.join(REVERSAL_COSTS)}]'): {line.strip()[:80]!r}. A decision takes that "
                           f"form; to mention the tag instead, write it bare ('[DELEGATED]', nothing inside) "
                           f"mid-sentence or in a code span, or write 'delegated'")
            elif level and c.group(2) != level:
                out.append(f"RUN_LOG.md: a [DELEGATED] tag names the level {c.group(2)!r}, but the run's "
                           f"level is {level!r}: {line.strip()[:80]!r}")
            elif LEAVE_LOOSE_RE.match(line, c.end()) and c.group(3) != "re-prove":
                out.append(f"RUN_LOG.md: a result left unproved is reversed by proving it: its tag must say "
                           f"'reversal: re-prove': {line.strip()[:80]!r}")
        if PROXY_RE.search(line) and DELEGATED_LOOSE_RE.search(line):
            out.append(f"RUN_LOG.md: one line carries both a [PROXY] and a [DELEGATED] tag; a decision is "
                       f"one or the other: {line.strip()[:80]!r}")
    return out


# A non-goal result left unproved under a delegating level (RUN.md, failure table, "your own
# work"; approver's decision Q1 (b)). The operator logs, after a serious attempt,
#   [DELEGATED <date>, operator under <level> (intake); reversal: re-prove] leave <decl> unproved — <reason>
# with <decl> the full Lean name (backticks optional). The statement stays byte-identical and
# unproved: Phase 0 reports its `sorry` as NOTE[unproved], the axiom sweep allows sorryAx for
# exactly these declarations (any other declaration reaching sorryAx -- a result whose proof uses
# one -- must be logged too), the adjudicator records each in SKIPPED.md, and the report and the
# decisions document disclose it as "stated, not proved". Never a goal result (a stop), never
# under `involved` (the human decides). Read from the COMMITTED RUN_LOG.md only.
LEAVE_LOOSE_RE = re.compile(r"\s*leave\b[^\n]*?\bunproved\b", re.I)
LEAVE_UNPROVED_RE = re.compile(r"\s*leave\s+`?([A-Za-z_][\w'.₀-₉]*)`?\s+unproved\b")


def committed_log(cfg):
    """RUN_LOG.md as committed at HEAD of the audit record ("" when there is none)."""
    import subprocess
    rel = os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"], "RUN_LOG.md"), project.AUDITS)
    r = subprocess.run(["git", "-C", project.AUDITS, "show", f"HEAD:./{rel}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


# Which log lines are such decisions (and nothing else is): a top-level list item of a DECISION
# section of RUN_LOG.md -- `## Open questions`, `## Checkpoint C …`, `## Answered` -- whose text
# begins with the canonical tag, optionally after its anchor (`- <anchor>: [DELEGATED …] …`, the
# delegated Checkpoint C form) or its answered prefix (`- answered <anchor> (<date>, <round>): …`).
# A line in any other section (Rounds, Stops, Fresh readers, …), a blockquote, an indented line or
# a sentence that merely quotes the words ("considered `[DELEGATED …] leave X unproved` but
# rejected") is not a decision and exempts nothing.
LEAVE_SECTIONS_RE = re.compile(r"(?:Open questions|Checkpoint C|Answered)\b")
# The anchor a decision line may open with is a real decisions anchor (`<kind>:<id>`, a kind
# anchor_id/versioned use below): `considered:` or any other free word is not one.
ANCHOR_KINDS = ("approval", "global", "check", "notformalized", "question", "revote", "proxy", "delegated",
                "open", "defer", "proposed-defer", "defect", "vacuous", "skip", "route", "uncovered",
                "after-last-round", "unused")
_ANCHOR = rf"(?:{'|'.join(map(re.escape, ANCHOR_KINDS))}):[\w.:/@+\-]+"
# a delegated line logged under the anchor it decides: "- check:Lemma_3.1: [DELEGATED …"
DELEGATED_PRE_RE = re.compile(rf"^\s*[-*][ \t]+(?:answered[ \t]+)?({_ANCHOR})(?::[ \t]|[ \t]+\()[^\n]*?\[DELEGATED ")
LEAVE_PREFIX_RE = re.compile(rf"[-*][ \t]+(?:answered[ \t]+{_ANCHOR}[ \t]+\([^)\n]*\):[ \t]*|{_ANCHOR}:[ \t]+)?(?=\[DELEGATED )")


def leave_lines(log):
    """[(tag match, the line)] for every [DELEGATED] tag that opens a decision line of `log` (the
    rule above), in order."""
    out, sec = [], None
    for line in log.splitlines():
        if line.startswith("## "):
            sec = line[3:].strip()
            continue
        if sec is None or not LEAVE_SECTIONS_RE.match(sec):
            continue
        m = LEAVE_PREFIX_RE.match(line)
        c = DELEGATED_TAG_RE.match(line, m.end()) if m else None
        if c:
            out.append((c, line))
    return out


_FIRST_LOGGED = {}


def first_logged(cfg):
    """{decl: the first commit of the audit record whose RUN_LOG.md names it in a decision line
    `leave <decl> unproved`} -- keyed on the declaration, not the line's words, so rewording a
    line (RUN_LOG.md is not append-only) cannot make it new again."""
    import subprocess
    g = lambda *a: subprocess.run(["git", "-C", project.AUDITS, *a], capture_output=True, text=True)
    rel = os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"], "RUN_LOG.md"), project.AUDITS)
    head = g("rev-parse", "HEAD").stdout.strip()
    key = (project.AUDITS, rel, head)
    if key not in _FIRST_LOGGED:
        out = {}
        r = g("log", "--reverse", "--format=%H", "--", rel)
        for h in (r.stdout.split() if r.returncode == 0 else []):
            text = g("show", f"{h}:./{rel}").stdout
            for c, line in leave_lines(text):
                m = LEAVE_UNPROVED_RE.match(line, c.end())
                if m:
                    out.setdefault(m.group(1), h)
        _FIRST_LOGGED.clear()
        _FIRST_LOGGED[key] = out
    return _FIRST_LOGGED[key]


_LOGGED_HIST = {}


def dropped_delegated(cfg, log, level):
    """[(commit, tagged text)] of every canonical [DELEGATED] decision at `level` that some committed
    RUN_LOG.md recorded and `log` (the log as it stands) no longer holds, whitespace aside; a line
    later extended still holds it. A decision is never removed or reworded: a new one is logged
    beside it (B11 review, M4: a delegated record was removed from the log and its decision
    rewritten, and the document check passed). A line the tag check refuses (tag_problems) may be
    corrected. Git unreadable: nothing (the record has no history to compare)."""
    import subprocess
    g = lambda *a: subprocess.run(["git", "-C", project.AUDITS, *a], capture_output=True, text=True)
    rel = os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"], "RUN_LOG.md"), project.AUDITS)
    head = g("rev-parse", "HEAD").stdout.strip()
    key = (project.AUDITS, rel, head, level)
    norm = lambda x: " ".join(x.split())
    if key not in _LOGGED_HIST:
        hist = {}
        r = g("log", "--reverse", "--format=%H", "--", rel)
        for h in (r.stdout.split() if r.returncode == 0 else []):
            for _, t in delegated_entries(g("show", f"{h}:./{rel}").stdout):
                c = DELEGATED_TAG_RE.match(t)
                if c and c.group(2) == level and norm(t) not in hist and not tag_problems("- " + t, level):
                    hist[norm(t)] = (h, t)
        _LOGGED_HIST.clear()
        _LOGGED_HIST[key] = hist
    now = "\n".join(norm(t) for _, t in delegated_entries(log))
    return [v for k, v in _LOGGED_HIST[key].items() if k not in now]


def adjudicated_since(cfg, decl):
    """Has a round been adjudicated (an ADOPTED.md committed to the audit record) AFTER the commit
    that first logged `leave <decl> unproved` (first_logged)? Then that adjudicator saw the
    decision, and its SKIPPED.md row is due. An ADOPTED.md committed in that same commit does not
    count (the adjudicator worked before the line existed): the row stays pending until the next
    adjudication. True when git cannot tell (fail closed: the row is required)."""
    import subprocess
    first = first_logged(cfg).get(decl)
    if not first:
        return True
    rel = os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"]), project.AUDITS)
    r = subprocess.run(["git", "-C", project.AUDITS, "rev-list", f"{first}..HEAD", "--", f"{rel}/*/ADOPTED.md"],
                       capture_output=True, text=True)
    return r.returncode != 0 or bool(r.stdout.strip())


def pending_refusal(cfg):
    """The refusal while a result left unproved awaits its adjudication (pending_unproved), or None.
    `project.py --deliver` and `decisions.py --check` (run before the completion message) both
    refuse with it: no route out of the run delivers an exemption no adjudicator has checked."""
    pend = pending_unproved(cfg)
    if not pend:
        return None
    return ("left unproved by a [DELEGATED] line that no round has adjudicated since: "
            + ", ".join(f"`{d}`" for d in pend) + ". A line logged after the final diff round needs one "
            "more round, so its adjudicator checks it and records it in SKIPPED.md: a diff round, or a full round "
            "(prompt.py 3 --full) when no Lean changed with it (scope.py exits 3 with NEXT[full-round]); then deliver.")


def pending_unproved(cfg):
    """[decl] left unproved by a logged decision that no round has adjudicated since (its
    SKIPPED.md row and the adjudicator's check -- not a goal result, not missing theory -- are
    still to come). Pending is allowed during the run; at delivery it is RED (`project.py
    --deliver` refuses): a line logged after the final diff round needs one more round (pending_refusal)."""
    # B2 pending state: a declaration of the open re-approval question is the question's, not a leave line's
    pend = set(pending_reapproval(cfg))
    return [d for d in unproved(cfg)["decls"] if d not in pend and not adjudicated_since(cfg, d)]


def goal_decls(cfg):
    """The full Lean names of the configured goal results: the index's names resolved the way the
    dependency walk resolves them (dependencies.resolve_name: as written, then namespace ++ name);
    an unresolved one stands for both forms (fail closed)."""
    import dependencies
    return dependencies.resolve_all(dependencies.goal_roots(cfg), cfg.get("namespace", ""),
                                    dependencies.project_decls(cfg))


def unproved(cfg, log=None, goals=None):
    """{"decls": {decl: its [DELEGATED] tag}, "lines": {decl: its log line}, "goal": [goal results
    named], "problems": [...]} for the `leave <decl> unproved` lines of the committed RUN_LOG.md
    (or of `log`). Only valid lines count: the run's own delegating level, reversal re-prove, not
    a goal result; a refused line is a problem, and its declaration's `sorry` stays RED."""
    log = committed_log(cfg) if log is None else log
    out = {"decls": {}, "lines": {}, "goal": [], "problems": []}
    lvl = project.involvement(cfg)
    gd, ns = None, cfg.get("namespace", "")
    for c, line in leave_lines(log):
        m = LEAVE_UNPROVED_RE.match(line, c.end())
        if not m:
            if LEAVE_LOOSE_RE.match(line, c.end()):
                out["problems"].append(f"not a full Lean name in a 'leave <decl> unproved' line: "
                                       f"{line.strip()[:90]!r}")
            continue
        d = m.group(1)
        if not project.delegates(cfg):
            out["problems"].append(f"{d}: left unproved by a [DELEGATED] line, but the level is {lvl!r}: "
                                   f"the human decides (Checkpoint C); its sorry stays RED")
        elif c.group(2) != lvl:
            out["problems"].append(f"{d}: the [DELEGATED] tag names the level {c.group(2)!r}, the run's is {lvl!r}")
        elif c.group(3) != "re-prove":
            out["problems"].append(f"{d}: a result left unproved is reversed by proving it ('reversal: re-prove')")
        else:
            gd = (goal_decls(cfg) if goals is None else set(goals)) if gd is None else gd
            # the log names the full Lean name; a short one is checked as namespace ++ name too
            if {d, f"{ns}.{d}"} & gd:
                out["goal"].append(d)
                out["problems"].append(f"{d} is a goal result: one that stays unproved is a stop at every "
                                       f"level (RUN.md, \"Stops that remain at every level\")")
            elif d not in out["decls"]:
                out["decls"][d] = c.group(0)
                out["lines"][d] = line.strip()
    return out


def intake_disclosure(cfg):
    """The opening paragraph of a delegated decisions document: the level, the human's verbatim
    intake answer, and who reviewed nothing (DISCLOSURE)."""
    lvl = project.involvement(cfg)
    ans = str(cfg.get("involvement_answer") or "NOT RECORDED").strip()
    asked = ("so you were asked only at Checkpoint B" if lvl == "statements-only" else "so nobody was asked")
    return (f"This is the protocol's final checkpoint, **Checkpoint C**. At the intake you chose the "
            f"involvement level **{lvl}** (your answer, verbatim: \"{ans}\"), {asked}: "
            f"the operator (the AI agent running the protocol) took each decision below itself, "
            f"following an adjudicator's written recommendation where there was one (never one it "
            f"wrote itself) and otherwise the conservative rule (keep the paper's statements and "
            f"hypotheses; build missing theory when only definitions and easy lemmas were missing, else assume it "
            f"as a named hypothesis), and recorded it in "
            f"`RUN_LOG.md` with a dated tag. {DISCLOSURE.get(lvl, '')} Each decision is final unless "
            f"you reverse it: the table below says what reversing it costs, and its **Decision taken** "
            f"field says what was done and how to reverse it.\n")


def question_mention(item):
    """What a section answering this QUESTION item must show. A Lean name (`Ns.S4.l410b`): its last
    component. A paper result ("Theorem 1.5"): its number, matched as a number. Free text: the
    words before its first colon."""
    if re.fullmatch(r"[A-Za-z_][\w'.₀-₉]*", item) and "." in item and not NUM_RE.search(item):
        return item.rsplit(".", 1)[-1]
    m = NUM_RE.search(item)
    if m:
        return item
    return item.split(":")[0].strip()[:40]


RESULT_RE = re.compile(r"\b(definition|lemma|theorem|proposition|corollary|conjecture|claim|remark|example|fact|"
                       r"observation)s?[\s_]+(\d+(?:\.\d+)*)", re.I)
DECL_KINDS = ("question", "unused", "revote")


def result_of(text):
    """'Lemma 3.2' for any text naming Lemma 3.2 or a part of it ('Lemma_3.2', 'Lemma 3.2(c)'), else None."""
    m = RESULT_RE.search(str(text))
    return f"{m.group(1).capitalize()} {m.group(2)}" if m else None


# a paper-result label in a labelled field: kind word, blank, dotted number, and nothing that
# continues the number (`Lemma 3a`, `Lemma 3_2`); a plural ("Lemmas 3.2 and 3.3") names several
LABEL_RE = re.compile(r"(?<![\w])(definition|lemma|theorem|proposition|corollary|conjecture|claim|remark|example|"
                      r"fact|observation)(s?)[ \t~]+(\d+(?:\.\d+)*)(?![\w]|\.\d)", re.I)


def exact_label(field):
    """The one paper result ('Lemma 3.2') a labelled field names, or None: no label, a plural, or
    two different results (review of fix-mini2, H2: when in doubt, do not merge). Code spans
    (`lemma_3_2_c`) are dropped first: a Lean name is never read as a label."""
    t = re.sub(r"`[^`]*`", " ", str(field or ""))
    found = set()
    for m in LABEL_RE.finditer(t):
        if m.group(2):
            return None
        found.add(f"{m.group(1).capitalize()} {m.group(3)}")
    return found.pop() if len(found) == 1 else None


def decl_results(cfg):
    """{declaration name: result label} from the index (Main.lean): each name as the index writes
    it, and also under the project namespace when written without it. A name in two rows with
    different results is left out (review of fix-mini2, L6: keyed by the unqualified name,
    `Foo.lemma_3_3` joined Lemma 3.3)."""
    import signoff
    out, bad = {}, set()
    try:
        rows = signoff.index_rows(cfg)
    except (OSError, ValueError, KeyError, SystemExit):
        return out
    ns = str(cfg.get("namespace") or "")
    for lab, rest in rows:
        r = exact_label(lab)
        if not r:
            continue
        for n in re.findall(r"`([^`]+)`", rest):
            for k in {n} | ({f"{ns}.{n}"} if ns and not n.startswith(ns + ".") else set()):
                if out.get(k, r) != r:
                    bad.add(k)
                out[k] = r
    return {k: v for k, v in out.items() if k not in bad}


def decl_matter(decl, idx):
    """The result of declaration `decl` in the index `idx` (decl_results): a full-name match (case
    aside);
    an unqualified `decl` also matches when exactly one index name ends in `.decl` and all such
    agree. Else None (do not merge)."""
    d = decl.lower()        # RUN_LOG.md anchors are read lower-cased (delegated_entries)
    hits = {v for k, v in idx.items() if k.lower() == d}
    if not hits and "." not in d:
        hits = {v for k, v in idx.items() if k.lower().endswith("." + d)}
    return hits.pop() if len(hits) == 1 else None


RECORD_KINDS = ("check", "notformalized", "defect", "vacuous", "skip", "route")


def matter_of(anchor, text, idx, appr_round=None, label=None):
    """The matter an item or a delegated decision is about, or None (it stands alone). Items on one
    matter are ONE decision section listing every anchor (mini2 audit: 23 decisions for about 8
    matters -- a CHECK row, a QUESTION row, an unused hypothesis and a paper defect on one lemma).
    The matter is an exact paper-result label, never read from a Lean name (review of fix-mini2,
    H2: `lemma_2_1_c` read as "Lemma 2" merged three lemmas): a declaration's result from the index
    (decl_matter); a record's from its labelled field (`label`, from exact_label), or, for a CHECK
    or not-formalized anchor, which is the sheet's result field itself, from the anchor when it is
    exactly a label ("Lemma_3.2(a)"). A QUESTION row's item, or the item a delegated line names
    (`label`: its anchor's or its "QUESTION row on <item>"), is a declaration or exactly one label
    (B11: a run's QUESTION on "Lemma 2.2" stood apart from Lemma 2.2). The approval and a delegated
    line recording the same approval (its own text names the approved round; `text` is the item's
    title and record, never the writer's field prompts) are one matter. When in doubt: None."""
    kind, _, ident = str(anchor).partition(":")
    kind = kind.lower()
    if kind == "approval" or (kind == "delegated" and appr_round and appr_round.lower() in str(text).lower()
                              and "approv" in str(text).lower()):
        return "Statement approval"
    if kind in DECL_KINDS or (kind == "delegated" and label is not None):
        hit = decl_matter(ident.split("@")[0], idx) if kind in DECL_KINDS else None
        if hit is None and label is not None and kind in ("question", "delegated"):
            lab = str(label).strip().strip("`")
            hit = decl_matter(lab, idx) if re.fullmatch(r"[^\s`]+", lab) else None
            hit = hit or exact_label(label)
        return hit
    if kind in RECORD_KINDS:
        if label is not None:
            return exact_label(label)
        if kind in ("check", "notformalized"):
            m = re.fullmatch(r"([A-Za-z]+)_(\d+(?:\.\d+)*)(\([^()]*\))?", ident.split("@")[0])
            return exact_label(f"{m.group(1)} {m.group(2)}") if m else None
    return None


# B11 (U2 §6.1 "one decision per matter", D3 §4): items on no paper result are grouped by their anchor's
# kind, one section per kind, each item keeping its record and its own Decision taken line. Under
# `involved` a question, [PROXY], open question or re-vote is the human's own answer and stays a section
# of its own (each needs its own options and recommendation).
KIND_TITLES = {"global": "Global differences (conventions stated once on the sheet)",
               "check": "CHECK rows on no single paper result", "notformalized": "Not formalized (sheet)",
               "skip": "Not formalized or not proved (SKIPPED.md)", "defect": "Paper defects on no single result",
               "vacuous": "True only vacuously, on no single result", "route": "Proof routes on no single result",
               "unused": "Unused hypotheses", "question": "Questions on no single paper result",
               "revote": "Unsettled re-votes", "proxy": "Decisions taken for you as a [PROXY]",
               "delegated": "Other decisions delegated at intake", "open": "Open questions",
               "defer": "Standing rules in the audit configuration",
               "proposed-defer": "Proposed standing rules (not configured)"}
HUMAN_KINDS = ("question", "proxy", "open", "revote")


def kind_group(anchor, deleg):
    """The kind-group key of an item on no paper result (KIND_TITLES), or None (it stands alone)."""
    kind = str(anchor).partition(":")[0].lower()
    if kind not in KIND_TITLES or (not deleg and kind in HUMAN_KINDS):
        return None
    return "\1" + kind


def strip_fields(body, fields):
    """An item's body without the writer's fields (its title and record only)."""
    return body[:-len(fields)].rstrip() if body.endswith(fields) else body.rstrip()


# B11 review: a standing rule is one matter. A QUESTION row or a delegated line that names a standing
# rule (configured or proposed) is decided in that rule's section, whatever result the row sits on
# (a test run: the standing-defer decision stood under a lemma and again under its proposed rule); the
# result's own section points there (see also). A matter starting with FORCED wins over matter_of.
FORCED = "\2"


def rule_named(text, rules):
    """The one standing rule id of `rules` that `text` names as a whole word, or None."""
    hits = {r for r in rules if r and re.search(rf"(?<![\w-]){re.escape(r)}(?![\w-])", str(text))}
    return hits.pop() if len(hits) == 1 else None


def rule_matter(rule):
    return f"Standing rule `{rule}`"


def matter_key(it, idx, appr_round, fields):
    """The group key of a skeleton item (anchor, title, body, mention[, matter[, label]]): a FORCED
    matter (a standing rule), else its matter (matter_of, read from the title and record only), else
    the shared matter the skeleton gave it, else its anchor kind's group (kind_group), else the anchor
    itself (alone)."""
    if len(it) > 4 and isinstance(it[4], str) and it[4].startswith(FORCED):
        return it[4][1:]
    return (matter_of(it[0], it[1] + "\n" + strip_fields(it[2], fields), idx, appr_round,
                      it[5] if len(it) > 5 else None)
            or (it[4] if len(it) > 4 else None) or kind_group(it[0], DECIDED_FIELD in fields) or ("\0" + it[0]))


def group_title(key, g):
    """The heading of a section holding the items `g` [(anchor, title, …)] under group key `key`."""
    if len(g) == 1:
        return g[0][1]
    if key.startswith("\1"):
        return f"{KIND_TITLES[key[1:]]}: {len(g)} items"
    kinds = list(dict.fromkeys(re.split(r"[:(]", t, maxsplit=1)[0].strip().replace(
        "Decision delegated at intake", "logged decision") for _, t, *_ in g))
    return f"{key} ({len(g)} items: {', '.join(kinds)})"


def decided_line(anchor, answer):
    """The Decision taken text of an item the operator already decided and logged under `## Answered`
    (B11): the logged answer verbatim (its [DELEGATED] tag included) and how to reverse it."""
    return f"{answer} (logged; to reverse: last section)"


def item_label(title):
    """The plain label of one item in a merged section's Decision taken (B11 review: the reader saw
    opaque anchor ids first): its title, short; a delegated line's decision follows it in full."""
    if str(title).startswith("Decision delegated at intake"):
        return "Decision logged during the run"
    return short_label(title, 60)


def group_items(items, idx, appr_round, fields, decided=None, see_also=None):
    """[(anchors, title, body, mentions)] from [(anchor, title, body, mention[, matter[, label]])]:
    items on one matter (matter_key) merged into one, in the order of the first; each body keeps its
    record text, the fields once. `decided`: {anchor: logged answer} of items already decided under a
    delegating level, whose Decision taken line is filled from the log (decided_line). `see_also`:
    {group key: note} placed before the fields of that group's section."""
    decided, see_also = decided or {}, see_also or {}
    groups, order = {}, []
    keys = [matter_key(it, idx, appr_round, fields) for it in items]
    # trial #7 audit: a QUESTION on a declaration the index gives no result (a worked example, a witness lemma)
    # and the delegated lines answering it, round after round, sat in two kind groups ("Questions on no single
    # paper result", "Other decisions delegated at intake": 4 + 16 items); such a declaration with its
    # question and at least one line answering it is one section
    def _decl(it, key):
        if key == "\1question":
            return str(it[0]).partition(":")[2].split("@")[0]
        if key == "\1delegated" and len(it) > 5 and it[5]:
            n_ = str(it[5]).strip().strip("`")
            return n_ if re.fullmatch(r"[A-Za-z_][\w.'!?]*\.[\w.'!?]+", n_) else None
        return None
    decls = [_decl(it, k) for it, k in zip(items, keys)]
    asked = {d for d, k in zip(decls, keys) if d and k == "\1question"}
    answering = {d for d, k in zip(decls, keys) if d and k == "\1delegated"}
    keys = [f"Declaration `{d}`" if d and d in asked and d in answering else k for d, k in zip(decls, keys)]
    for it, key in zip(items, keys):
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(it[:4])
    out = []
    group_items.order = list(order)     # the group key of each section returned, in order (skeleton.sections)
    for key in order:
        g = groups[key]
        note = see_also.get(key, "")
        if len(g) == 1:
            a, t, b, m = g[0]
            if note and b.endswith(fields):
                b = b[:-len(fields)] + note + fields
            if a in decided and b.endswith(fields) and DECIDED_FIELD in fields:
                b = b[:-len(fields)] + fields.replace(DECIDED_FIELD, DECIDED_FIELD.replace(
                    FILL + " >>", decided_line(a, decided[a])))
            out.append(([a], t, b, [m]))
            continue
        f_ = fields
        if DECIDED_FIELD in fields:
            # each item keeps its own decision and reversal cost (review of fix-mini2, M1); B11 review: the
            # reader sees the item's plain label first, its anchor id small at the end of the line
            f_ = fields.replace(DECIDED_FIELD, MULTI_DECIDED_FIELD + "".join(
                f"- *{item_label(t)}:* {decided_line(a, decided[a]) if a in decided else FILL + ' >>'} "
                f"<sub>`{a.split('@')[0]}`</sub>\n" for a, t, _, _ in g))
        # (italic, not bold: a bold label opening a line reads as a field, "**Paper defect 1**" as **Paper**)
        # an item's own heading is its short label; an item whose record is empty (a decided delegated
        # line, quoted once in its Decision taken line) has no paragraph of its own
        body = "\n\n".join(f"**{short_label(t, 90)}.** {strip_fields(b, fields)}" for _, t, b, _ in g
                           if strip_fields(b, fields)) + "\n\n" + note + f_
        out.append(([a for a, _, _, _ in g], group_title(key, g), body, [m for _, _, _, m in g]))
    return out


def n_sections(text):
    """The number of decision sections (headings carrying an item anchor) of a decisions document."""
    return len(re.findall(r"^### [^\n]*\n<!-- item:", text, re.M))


def delegated_title(first):
    """The title of a decision delegated at intake: its run-log line, cut only at a word (mini5 audit:
    a cut at 110 characters, tag included, left the label 'approved the sheet of round 20')."""
    return f"Decision delegated at intake: {project.clip(first, 240)}"


def short_label(text, limit=90):
    """A table label: the [DELEGATED …]/[PROXY …] tag dropped (it is in the section), cut at a word
    with an ellipsis, never mid-tag (mini2 audit: two rows read '…(intake); re')."""
    t = re.sub(r"\[(?:DELEGATED|PROXY)[^\]]*\]\s*", "", str(text)).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return (cut if len(cut) > limit // 2 else t[:limit]).rstrip(" ,;:") + " …"


def skeleton(cfg, rounds, last_round):
    """(markdown, [anchor ids in order]). Every anchor is collected here, not re-parsed."""
    deleg = project.delegates(cfg)
    FIELDS = globals()["FIELDS"] + (DECIDED_FIELD if deleg else "")
    appr = approval(cfg)
    sd, so = latest_signoff(rounds, appr)
    newest_sheet = latest_signoff(rounds, None)[0]
    root = os.path.join(project.REPO, cfg["rounds_dir"])
    log = _read(os.path.join(root, "RUN_LOG.md"))
    done = answered(log)
    order = [os.path.basename(d) for d in rounds]
    # trial #8: an answer logged under a record row's pre-trial-#8 (prose-hashing) anchor is an answer to the row's
    # substance anchor; the later answer wins when both are logged
    alias = legacy_aliases(root)
    for k in [k for k in done if k in alias]:
        a, v = alias[k], done.pop(k)
        if a not in done or (order.index(v[2]) if v[2] in order else -1, v[1]) > \
                (order.index(done[a][2]) if done[a][2] in order else -1, done[a][1]):
            done[a] = v
    anchors, items, prev = [], [], []
    bdec = decided_at_b(cfg, root, appr, os.path.basename(sd) if sd else None)
    b_items = []            # trial #8: (item, later answer line or None) of the matters the human decided at B
    glance_labels = []      # one at-a-glance row per section: per matter (B11; was per item, review M1)
    names = {}

    def later(asked_round, ans_round, ans_date):
        return asked_after(order, asked_round, ans_round, ans_date)

    pending = []
    b_lines = []           # trial #8: the "Already decided by you at Checkpoint B" list
    answered_now = []      # (anchor, answer line) of the current items answered and not asked again (B12)

    def add(anchor, title, body, mention=None, asked=(), matter=None, label=None):
        """`mention`: text a section carrying this anchor must show (None: no requirement);
        `asked`: the rounds that asked it, so an older answer does not hide a newer asking;
        `matter`: the matter it shares with other items when matter_of cannot tell (group_items);
        `label`: a record's labelled field naming its paper result (matter_of reads only that).
        Items are settled in finish(), once every current anchor is known."""
        pending.append((anchor, title, body, mention, asked, matter, label))

    idx, appr_round = decl_results(cfg), (appr or {}).get("round")
    level = project.involvement(cfg)
    logged = {}     # anchor of a delegated item: its tagged run-log line

    def finish():
        current = {p_[0] for p_ in pending}
        live, decided, prev_items = [], {}, []
        for anchor, title, body, mention, asked, matter, label in pending:
            kind_ = anchor.split(":", 1)[0]
            if bdec and ((kind_ in SHEET_KINDS and bdec["sheet"]) or anchor in bdec["anchors"]):
                # trial #8: decided by the human at Checkpoint B and unchanged in substance: listed, never asked
                # again (an answer logged since -- an older apparatus re-asked it -- is shown with its checkpoint)
                b_items.append(((anchor, title, body, mention, matter, label), done[anchor][0] if anchor in done else None))
                continue
            if bdec and kind_ in B_RECORD_KINDS and anchor not in done and anchor.rsplit("@", 1)[0] + "@" in bdec["families"]:
                body = (f"You decided this matter at Checkpoint B ({bdec['families'][anchor.rsplit('@', 1)[0] + '@'] or 'undated'}); "
                        "what it decides (its location, printed statement, status or repair) has changed since, so it is "
                        "asked again.\n\n" + body)
            tg = DELEGATED_TAG_RE.search(logged.get(anchor, ""))
            if deleg and tg and tg.group(2) == level and anchor not in done:
                decided[anchor] = logged[anchor]     # B11: a delegated line IS its decision: quoted, not retyped
            if anchor in done:
                line, when, ans_round = done[anchor]
                if not any(later(a, ans_round, when) for a in asked):
                    tg = DELEGATED_TAG_RE.search(line)
                    if deleg and tg and tg.group(2) == level:
                        # B11: under a delegating level an answer logged with this level's [DELEGATED] tag is a
                        # decision taken on the reader's behalf: it keeps its section in its matter, its
                        # Decision taken filled from the log (mini2/4/6 wrote it again by hand in an appendix)
                        decided[anchor] = ANSWER_PREFIX_RE.sub("", line, count=1).strip()
                    else:
                        prev_items.append((anchor, title, body, mention, matter, label))
                        answered_now.append((anchor, line))
                        continue
                else:
                    body = f"Previously answered ({line}); asked again since.\n\n" + body
            elif "@" in anchor:
                # an answer to an earlier version of this item (its anchor is no longer current)
                fam = anchor.rsplit("@", 1)[0] + "@"
                old = [v for k, v in done.items() if k.startswith(fam) and k not in current]
                # only when the family is one current item: two items sharing a family must not
                # show each other's answers
                n_cur = sum(a_.startswith(fam) for a_ in current)
                if old and n_cur > 1:
                    # several current items share the family: the old answer belongs to one of them,
                    # which one is unknown -- show it on each, saying so
                    last = max(old, key=lambda v: (order.index(v[2]) if v[2] in order else -1, v[1]))
                    body = (f"An earlier version of one of {n_cur} items about the same subject was "
                            f"answered ({last[0]}); the content has changed since.\n\n" + body)
                elif old and n_cur == 1:
                    last = max(old, key=lambda v: (order.index(v[2]) if v[2] in order else -1, v[1]))
                    body = (f"Previously answered for an earlier version ({last[0]}); the content has "
                            f"changed since.\n\n" + body)
            live.append((anchor, title, body, mention, matter, label))
        skeleton.decided = dict(decided)
        # an item moved to a standing rule's section: its paper result's section points there
        see = {}
        for anchor, title, body, mention, matter, label in live:
            if isinstance(matter, str) and matter.startswith(FORCED):
                home = matter_of(anchor, title + "\n" + strip_fields(body, FIELDS), idx, appr_round, label)
                if home:
                    see.setdefault(home, {}).setdefault(matter[1:], []).append(item_label(title))
        see = {h_: "".join(f"*See also* the section \u201c{rk}\u201d: it decides {' and '.join(ls)}.\n\n"
                           for rk, ls in v.items()) for h_, v in see.items()}
        grouped = group_items(live, idx, appr_round, FIELDS, decided, see)
        # trial #10 audit: the report counted the delegated lines by its own grouping (10 matters) against these
        # sections (7): delegated_by_matter now reads each line's section from here
        skeleton.sections = {a_: (k_, g_[1]) for g_, k_ in zip(grouped, group_items.order) for a_ in g_[0]}
        for ans, title, body, ments in grouped:
            for anchor, mention in zip(ans, ments):
                anchors.append(anchor)
                if mention:
                    names[anchor] = mention
            items.append(f"### {title}\n" + "".join(f"<!-- item:{a} -->\n" for a in ans) + f"\n{body}\n")
            # B11: one at-a-glance row per section (matter), not per item
            glance_labels.append(title)
        # answered items, one entry per matter (B11; mini2 listed 21 lines, each repeating its anchor)
        pg, porder = {}, []
        for it in prev_items:
            k = matter_key(it, idx, appr_round, FIELDS)
            if k not in pg:
                pg[k] = []
                porder.append(k)
            pg[k].append(it)
        for k in porder:
            g = pg[k]
            # trial #8: each answer with the checkpoint it was given at (the C answer read as the B approval's)
            lines_ = [f"{short_label(it[1], 60)}: "
                      + ANSWER_PREFIX_RE.sub("", done[it[0]][0], count=1).strip() + " " + when_answered(log, done[it[0]])
                      + f" <sub>`{it[0].split('@')[0]}`</sub>" for it in g]
            if len(g) == 1:
                prev.append(f"- {lines_[0]}")
            else:
                prev.append(f"- **{group_title(k, g)}**")
                prev.extend(f"  - {l_}" for l_ in lines_)
        # trial #8: the matters the human decided at Checkpoint B, one line per matter, never a question
        bg, border = {}, []
        for it, later_ in b_items:
            k = matter_key(it, idx, appr_round, FIELDS)
            if k not in bg:
                bg[k] = []
                border.append(k)
            bg[k].append((it, later_))
        again, again_order = {}, []      # (when, answer) -> [item labels]: an answer logged since, once per answer
        for k in border:
            g = bg[k]
            title_ = group_title(k, [it for it, _ in g])
            b_lines.append(f"- {title_} <sub>" + ", ".join(f"`{it[0].split('@')[0]}`" for it, _ in g) + "</sub>")
            for it, later_ in g:
                if later_:
                    occ = answer_occasion(log, later_)
                    key_ = (f"at {occ[0]} ({occ[1]})" if occ else f"on {done[it[0]][1] or 'an unrecorded date'}",
                            ANSWER_PREFIX_RE.sub("", later_, count=1).strip())
                    if key_ not in again:
                        again[key_] = []
                        again_order.append(key_)
                    again[key_].append(short_label(it[1], 60))
        for when_, ans_ in again_order:
            b_lines.append(f"- Answered again {when_} ({'; '.join(again[(when_, ans_)])}): {ans_}")
        # an answer line naming no current item and no family: probably a mistyped anchor
        fams = {a.rsplit("@", 1)[0] + "@" for a in current if "@" in a}
        # C2 audit (fault (f)): an answer keyed by the family without its `@hash` (`unused:P.lemma_2_6`) is the
        # family's, not stray
        stray = [k for k in done if k not in current and not any(k.startswith(f) or k + "@" == f for f in fams)]
        # a stop's answer (`stop:S<n>`, stage file "Stops") is no decisions item: listed as the stop's, not as stray
        for k in [k for k in stray if re.fullmatch(r"stop:S\d+", k)
                  and os.path.isdir(os.path.join(root, "stops", k.split(":", 1)[1]))]:
            stray.remove(k)
            prev.append(f"- Stop {k.split(':', 1)[1]}: " + ANSWER_PREFIX_RE.sub("", done[k][0], count=1).strip()
                        + " " + when_answered(log, done[k]) + f" <sub>`{k}`</sub>")
        for k in stray:
            prev.append(f"- `{k}` — matches no current item (mistyped anchor, or the item is gone): "
                        f"{done[k][0]}")

    name = cfg.get("title") or cfg["name"]
    head = [f"# Decisions taken on your behalf — {name}\n" if deleg else f"# Decisions needed from you — {name}\n",
            f"<!-- decisions-round: {os.path.basename(last_round)} -->",
            "<!-- Generated by audits/decisions.py. Fill every " + FILL + " >> placeholder; group items "
            "that are one decision under one heading, keeping every `item:` anchor; each decision "
            "section keeps the " + ("six" if deleg else "five") + " labelled fields with real content. `decisions.py --check` refuses "
            "the document otherwise. Rules: AUDIT_PROTOCOL.md, 'Documents a human reads'. -->\n",
            intake_disclosure(cfg) if deleg else
            "This is the protocol's final checkpoint, **Checkpoint C**. Every decision that belongs "
            "to you is below, with enough context to decide it. How to answer is at the end.\n",
            "## Read this first: defects in the paper, vacuous statements, results not formalized\n",
            FILL + ": complete each entry below (location, one-sentence summary, which decision covers "
            "it); keep every entry inside the box; keep the box a blockquote. >>\n",
            BOX_START]
    for bl in box_lines(cfg):
        head.append(f"> - {bl}")
    if deleg:
        head += ["", GLANCE_HEADING + "\n",
                 "<!-- one row per decision section below (one per matter); 'Followed' is "
                 "adjudicator's recommendation, conservative rule, cause table, or human at Checkpoint B; 'Reversal "
                 "cost' is " + ", ".join(REVERSAL_COSTS) + " (not applicable for the human's); a section holding "
                 "several items lists each of its items' sources and costs once, separated by ';' -->\n",
                 "| Decision | What was done | Followed | Reversal cost |", "|---|---|---|---|",
                 "@@GLANCE@@"]
    head += ["", "## Background (read first)\n",
             FILL + ": what was formalized, what is proved, under which assumptions; how the protocol "
             "works in a few lines; where every file is (deliverables with absolute paths, the paper "
             "source and how its locations are cited, the Lean branch and commit, the audit records); "
             "terms; the paper's notation the items use, each with its location. >>\n",
             f"**Rounds, in order** (directories under `{cfg['rounds_dir']}/`):\n",
             "| Directory | Kind |", "|---|---|"]
    for d in rounds:
        head.append(f"| `{os.path.basename(d)}` | {project.round_kind(d) or 'unknown'} |")
    head.append("")

    # 1. approval
    by, legacy_by = (project.approval_by(appr, rounds_dir=os.path.join(project.REPO, cfg["rounds_dir"])) if appr
                     else (None, False))
    who = {"human": "approved by a human" + (f" ({project.LEGACY_BY_NOTE})" if legacy_by else ""), "agent": "approved by the AGENT, not by a human"}.get(
        by, "approver NOT RECORDED" if appr else "NOT APPROVED")
    excl = [l for l, r in (appr or {}).get("rows", {}).items() if r.get("status") == "excluded"]
    hist = earlier_approvals(cfg)
    body = (f"Sheet: `{os.path.relpath(os.path.join(sd, 'SIGNOFF.md'), project.REPO) if sd else '?'}` (and its PDF, "
            f"when the rendering agents made one: delivery README, section D)."
            + (f" Approved round: `{appr.get('round')}`, {appr.get('date', '?')}, commit {appr.get('commit', '?')}." if appr else "")
            + (f" Excluded: {', '.join(excl)}." if excl else "")
            + (f" Note: {appr['note']}." if appr and appr.get("note") else "")
            + (f" Earlier approvals: {'; '.join(hist)}." if hist else "")
            + (f" WARNING: the newest sheet is in `{os.path.basename(newest_sheet)}`, not the approved round."
               if appr and newest_sheet and newest_sheet != sd else "")
            + "\n\n" + FIELDS)
    add(versioned("approval", (appr or {}).get("round") or "none", json.dumps(appr, sort_keys=True)),
        f"Statement approval (Checkpoint B): {who}", body)
    # 2. the sheet: global differences, CHECK rows, results not formalized
    for g in so.get("global", []):
        add(versioned("global", str(g.get("id")), str(g.get("title", "")) + "\n" + str(g.get("text", ""))),
            f"Global difference {g.get('id')}: {g.get('title', '')}",
            f"Sheet text: {g.get('text', '')}\n\n" + FIELDS, mention=str(g.get("id")))
    for r in so.get("rows", []):
        if str(r.get("flag", "")).upper().startswith("CHECK"):
            add(anchor_id("check", str(r.get("result"))), f"CHECK row: {r.get('result')}",
                f"Sheet's reason: {r.get('check_reason', '')}\n\n" + FIELDS, mention=str(r.get("result")),
                asked=(os.path.basename(sd),) if sd else (), label=str(r.get("result")))
    for nf in so.get("not_formalized", []):
        add(versioned("notformalized", str(nf.get("result")), nf.get("note", "")), f"Not formalized: {nf.get('result')}",
            f"Record: {nf.get('note', '')}\n\n" + FIELDS, mention=str(nf.get("result")), label=str(nf.get("result")))
    # 3. QUESTION rows of every round, grouped by identical reason for the writer's convenience
    qs = question_rows(rounds)
    rules = [str(s_.get("id")) for s_ in cfg.get("standing_defers", [])] + list(proposed_standing(rounds, cfg))
    by_reason = {}
    for it_, asks in qs.items():
        by_reason.setdefault(asks[-1][2][:300], []).append(it_)
    for reason, its in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        for it_ in sorted(its):
            asks = "\n".join(f"- round {r}, {l}: " + (why if len(why) <= 600 else
                                                         why[:600] + f" … (full text in {r}/ADOPTED.md)")
                              for r, l, why in qs[it_])
            add(anchor_id("question", it_),
                f"QUESTION: {it_}" + (f" (one of {len(its)} with the same reason)" if len(its) > 1 else ""),
                f"Asked:\n{asks}\n\n" + FIELDS, mention=question_mention(it_),
                asked=tuple(r for r, _, _ in qs[it_]), label=it_,
                # one question asked of several declarations (e.g. every named witness) is one matter;
                # one about a standing rule is that rule's matter
                matter=(FORCED + rule_matter(rule_named(asks, rules)) if rule_named(asks, rules) else
                        f"The same question on several declarations ({sorted(its)[0]}, …)" if len(its) > 1 else None))
    # 3b. re-votes left unsettled (REVOTE NEEDED with no later decision), abandoned or not
    for rnd, lane, it_, reason, ab in open_revotes(rounds):
        add(anchor_id("revote", f"{rnd}-{it_}"),
            f"Unsettled re-vote: {it_}" + (" (its re-vote lane was abandoned)" if ab else ""),
            f"Round {rnd}, lane {lane}: the adjudicator would have rejected a Fail and asked for a second "
            f"look (REVOTE NEEDED); no later row decides it"
            + (" -- its re-vote lane was set aside, so no second look exists" if ab else "")
            + f". The adjudicator's reason: {reason}\n\n" + FIELDS,
            mention=question_mention(it_), asked=(rnd,))
    # 4. every [PROXY] decision and every open question in RUN_LOG.md
    # under `## Answered`, an answer that merely QUOTES a [PROXY] tag is not a new proxy decision;
    # only an answer that is itself one ("[PROXY ...] ...") is
    # `## Answered` sections: text QUOTED there ("…", “…”) is the human's words quoting a tag, not a
    # decision; everything else stays, so a [PROXY] tag outside quotes -- any line format,
    # continuation lines included -- is still a decision the human must confirm
    scan = answered_scan(log)
    for sec in LOG_SKIP_SECTIONS:
        scan = re.sub(rf"^## {re.escape(sec)}\b.*?(?=^## |\Z)", "", scan, flags=re.M | re.S)
    for b in log_entries(scan):
        if PROXY_RE.search(b) and "(answered" not in b:
            tagged = [l for l in b.splitlines() if PROXY_RE.search(l)]
            key = "\n".join(l.strip() for l in tagged)   # stable when lines are appended later
            first = tagged[0][tagged[0].index("[PROXY"):] if "[PROXY" in tagged[0] else tagged[0]
            add(anchor_id("proxy", key), f"Decision taken on your behalf: {first.strip()[:110]}",
                "Run log:\n\n" + "\n".join("> " + l for l in b.splitlines()) + "\n\n" + escalation_note(cfg, b) + FIELDS,
                mention="[PROXY")
    # every [DELEGATED] decision: an item the reader must SEE, already decided (not a question);
    # those recorded as answers to a decisions document (Checkpoint C, Answered) are not new items
    for b in log_entries(strip_sections(log, DELEGATED_SKIP_SECTIONS)):
        if DELEGATED_RE.search(b) and "(answered" not in b:
            tagged = [l for l in b.splitlines() if DELEGATED_RE.search(l)]
            key = "\n".join(l.strip() for l in tagged)
            first = tagged[0][DELEGATED_RE.search(tagged[0]).start():]
            # B11: the matter of the item it decides -- the anchor it is logged under ("- check:x: [DELEGATED…"),
            # or the QUESTION row it answers ("QUESTION row on <item>, round R")
            pre = DELEGATED_PRE_RE.match(tagged[0])
            qrow = QROW_RE.search(" ".join(tagged))
            logged[anchor_id("delegated", key)] = first.strip()
            tg_ = DELEGATED_TAG_RE.search(first)
            if deleg and tg_ and tg_.group(2) == level and anchor_id("delegated", key) not in done:
                # B11 review: decided -- its line is quoted once, in its Decision taken (finish), not
                # also in its heading and record; only the entry's other lines stay here
                rest_ = [l for l in b.splitlines() if l != tagged[0]]
                title_, rec_ = (f"Decision delegated at intake: {short_label(first, 70)}",
                                "".join(f"Run log, continued:\n\n" + "\n".join("> " + l for l in rest_) + "\n\n" if rest_ else ""))
            else:
                title_, rec_ = delegated_title(first), "Run log:\n\n" + "\n".join("> " + l for l in b.splitlines()) + "\n\n"
            add(anchor_id("delegated", key), title_, rec_ + escalation_note(cfg, b) + FIELDS,
                mention="[DELEGATED", matter=(FORCED + rule_matter(rule_named(b, rules)) if rule_named(b, rules) else
                                              matter_of(pre.group(1), "", idx, appr_round) if pre else None),
                label=qrow.group("item") if qrow and qrow.group("item") else None)
    for b in log_entries(section(log, "Open questions")):
        if not PROXY_RE.search(b) and not DELEGATED_RE.search(b) and "(answered" not in b:
            add(anchor_id("open", b), f"Open question: {project.clip(b.splitlines()[0].lstrip('- '), 100)}",
                "Run log:\n\n" + "\n".join("> " + l for l in b.splitlines()) + "\n\n" + escalation_note(cfg, b)
                + FIELDS)
    # 5. standing defers: configured ones (is the reason still true?) and proposed ones
    for sdf in cfg.get("standing_defers", []):
        add(versioned("defer", str(sdf.get("id")), json.dumps(sdf, sort_keys=True)), f"Standing rule `{sdf.get('id')}` in the audit configuration",
            f"Item: {sdf.get('item')}. Reason recorded: \"{sdf.get('reason')}\". "
            f"Revisit: {sdf.get('revisit_when')}. Is the reason still true?\n\n" + FIELDS, mention=str(sdf.get("id")),
            matter=FORCED + rule_matter(str(sdf.get("id"))))
    for rule, rs in sorted(proposed_standing(rounds, cfg).items()):
        add(anchor_id("proposed-defer", rule), f"Proposed standing rule `{rule}` (used by adjudicators, not configured)",
            f"Invoked in rounds: {', '.join(rs)}. Add it to the project config, or have the deferred "
            f"items fixed now?\n\n" + FIELDS, mention=rule, matter=FORCED + rule_matter(rule))
    # the records' `name` at File.lean:N quoted at the declaration's current line, as the report shows
    # them (make_report.refresh_lines): a moved line is no reason for another round (mini2 audit)
    import make_report as _mr

    def cur(text):
        try:
            return _mr.refresh_lines(text, cfg, _files={
                rel: open(os.path.join(project.REPO, rel), encoding="utf-8").read()
                for rel in cfg.get("lean_files", []) if os.path.exists(os.path.join(project.REPO, rel))})
        except (OSError, ValueError):
            return text
    # paper defects and vacuous statements: each gets its detailed entry (rule 5)
    for header, cells in defect_rows(root):
        if is_defect_header(header) and len(cells) >= len(header):
            # defect_anchor: hashed = where, status, repair (B3; an old-format row, PENDING[adj-record] until
            # rewritten, keeps where, severity), the printed text -- the substance, never the prose (trial #8)
            add(defect_anchor(header, cells),
                f"Paper defect {cells[0]}: {project.clip(cells[1], 90)}",
                f"Record (PAPER_DEFECTS.md row {cells[0]}): " + project.full(cur(" | ".join(cells[1:]))) + "\n\n" + FIELDS,
                mention=(NUM_RE.search(cells[1]).group(0) if NUM_RE.search(cells[1]) else cells[1][:30]),
                label=LEAN_CITE_RE.sub("", cells[1]))
    for header, cells in table_rows(_read(os.path.join(root, "VACUOUS.md"))):
        if _idx(header, "statement") is not None and len(cells) >= len(header):
            if "status" in header and is_repaired(cells[header.index("status")]):
                continue
            st = cells[_idx(header, "statement")]
            add(vacuous_anchor(header, cells),
                f"True only vacuously: {project.clip(st, 90)}",
                "Record (VACUOUS.md): " + project.full(cur(" | ".join(cells))) + "\n\n" + FIELDS,
                mention=(NUM_RE.search(st).group(0) if NUM_RE.search(st) else st[:30]), label=LEAN_CITE_RE.sub("", st))
    # skips and route changes listed in the box: each gets its detailed entry too (rule 5)
    left_unproved = unproved(cfg)["decls"]
    for header, cells in table_rows(_read(os.path.join(root, "SKIPPED.md"))):
        if _idx(header, "what") is not None and len(cells) > _idx(header, "what"):
            what = cells[_idx(header, "what")]
            label = re.sub(r"\*\*", "", what).split("(")[0].strip()[:60]
            stated = any(f"`{d_}`" in " ".join(cells) for d_ in left_unproved)
            add(versioned("skip", f"{cells[0]}-{label}", defining(header, cells, ("what", "reason"))),
                ("Stated in Lean, not proved (reversal: re-prove): " if stated else "Not formalized: ")
                + project.clip(re.sub(r"\*\*", "", what).split("(")[0], 60),     # never cut mid-word (mini5)
                "Record (SKIPPED.md): " + project.full(cur(" | ".join(cells))) + "\n\n" + FIELDS,
                mention=(NUM_RE.search(label).group(0) if NUM_RE.search(label) else label[:30]), label=what)
    for header, cells in table_rows(_read(os.path.join(root, "DEVIATIONS.md"))):
        if _idx(header, "kind") is not None and len(cells) > _idx(header, "kind"):
            kind = cells[_idx(header, "kind")].strip("* ").lower()
            if kind and kind not in ("same strength", "reading choice"):
                res = cells[header.index("result")] if "result" in header else cells[0]
                add(versioned("route", f"{cells[0]}-{res}", defining(header, cells, ("result", "the paper", "the lean", "why", "kind"))),
                    f"Proof route: {res} ({kind})",
                    "Record (DEVIATIONS.md): " + project.full(" | ".join(cells)) + "\n\n" + FIELDS,
                    mention=(NUM_RE.search(res).group(0) if NUM_RE.search(res) else res[:30]), label=res)
    # 6. the last round's UNCOVERED rows (RUN.md Stage 5 step 1 lists them for the human)
    import lanecheck
    unc = [(r.lane, r.item) for r in lanecheck.decision_rows(last_round) if r.decision.startswith("UNCOVERED")]
    if unc:
        add(anchor_id("uncovered", os.path.basename(last_round)),
            f"Items no audit lane examined in the last round ({len(unc)} UNCOVERED rows)",
            "Rows (lane, item):\n\n" + "\n".join(f"- {c[0]}: {c[1]}" for c in unc[:200])
            + ("\n- …" if len(unc) > 200 else "") + "\n\n" + FIELDS)
    # 6b. idle hypotheses of approved statements (UNUSED_ARGS.md): keep the paper's, or drop one --
    # a keep/drop decision with its reversal, not only a line of evidence (a test run)
    legacy_args = dict(unused_hypotheses(root, legacy=True))
    for decl, args in unused_hypotheses(root):
        # the anchor hashes the text as it was read before the arguments were split (an answer logged stays valid)
        add(versioned("unused", decl, "; ".join(legacy_args.get(decl, args))), f"Unused hypothesis: `{decl}`",
            f"UNUSED_ARGS.md (Batteries' `unusedArguments` linter, regenerated by Phase 0): no proof term "
            f"uses " + "; ".join(f"`{a}`" for a in args) + f" of the approved statement `{decl}`. Options: keep it "
            "(the paper's statement, with an idle hypothesis), or drop it (a stronger statement: a "
            "re-approval and one more round).\n\n" + FIELDS, mention=decl)
    # 7. changes after the last audit round
    late = changes_after(cfg, rounds)
    if late:
        # hashed on the commits' first 7 hex digits: git's abbreviation grows with the repository
        key_late = "\n".join(re.sub(r"^([0-9a-f]{7})[0-9a-f]*", r"\1", c) for c in late)
        add(versioned("after-last-round", "commits", key_late),
            "Changes made after the last audit round (not re-audited)",
            "Commits / files:\n\n" + "\n".join(f"- `{c}`" for c in late) + "\n\n" + FIELDS)
    finish()
    tail = (["## How to reverse a decision, and what happens next\n",
             FILL + ": how to ask for a decision to be reversed, and for each kind of reversal what it "
             "triggers (helpers/config only: change, Phase 0, diff round; an approved statement "
             "changed or added: new sign-off, then proofs, diff round, Phase 0). >>\n"] if deleg else
            ["## How to answer, and what happens next\n",
            FILL + ": the reply format, and for each kind of answer what it triggers (helpers/config "
            "only: change, Phase 0, diff round; an approved statement changed or added: new sign-off, "
            "then proofs, diff round, Phase 0). >>\n"])
    if prev:
        tail += ["## Previously answered (from RUN_LOG.md `## Answered`)\n", *prev, ""]
    skeleton.names = names
    skeleton.logged = dict(logged)
    skeleton.answered_current = answered_now
    # items the HUMAN decided at Checkpoint B (statements-only, approved by a human): the only
    # sections whose Decision taken may say "Not applicable"
    human_b = set()
    if project.involvement(cfg) == "statements-only" and project.approval_by(appr, rounds_dir=os.path.join(project.REPO, cfg["rounds_dir"]))[0] == "human":
        # ... except what RUN_LOG.md records as delegated (an anchor decided at Checkpoint C)
        deleg_anchors = {p_ for p_, _ in delegated_entries(log)}
        human_b = {a for a in anchors if a.split(":", 1)[0] in ("approval", "global", "check")
                   and a.lower() not in deleg_anchors and a.rsplit("@", 1)[0].lower() not in deleg_anchors}
    skeleton.human_decided = human_b
    if deleg:
        glance = [f"| {short_label(re.sub(r'[|]', '/', t), 90)} | {FILL} >> | {FILL} >> | {FILL} >> |"
                  for t in glance_labels]
        head = [h if h != "@@GLANCE@@" else "\n".join(glance) for h in head]
    bsec = []
    if b_lines:
        b_ans = [w for cp, _, w in checkpoint_answers(log) if cp == "B"]
        bsec = [f"## Already decided by you at Checkpoint B ({bdec['date'] or 'undated'})\n",
                f"Not asked again: you decided these when you approved the statements of round `{bdec['round']}`"
                + (f" (audit commit {bdec['commit'][:11]})" if bdec.get("commit") else "") + ". "
                + ("Your answer, as RUN_LOG.md `## Checkpoint B` records it: " + "; ".join(b_ans) + ". " if b_ans else
                   "RUN_LOG.md `## Checkpoint B` records no answer in your words; the approval file records the "
                   "approval as yours. ")
                + "One comes back only if what it decides changes (its statement, status, repair or options), "
                "never for a change of wording.\n", *b_lines, ""]
    skeleton.decided_at_b = [it[0] for it, _ in b_items]
    return "\n".join(head + bsec + ["## Decisions\n"] + items + tail), anchors


def sections_of(text):
    """[(heading line, body)] split at ### / ## headings; lines inside code fences are marked."""
    out, cur_h, cur, fence = [], None, [], False
    for line in text.splitlines():
        if line.strip().startswith(("```", "~~~")):
            fence = not fence
            cur.append("\x00" + line)
            continue
        if not fence and re.match(r"^#{2,3} ", line):
            if cur_h is not None:
                out.append((cur_h, "\n".join(cur)))
            cur_h, cur = line, []
        else:
            cur.append(("\x00" if fence else "") + line)
    if cur_h is not None:
        out.append((cur_h, "\n".join(cur)))
    return out


def fields_of(body):
    """{label (lower case): content} for the five labelled fields of a decision section. A field
    runs from its bold label to the next field label (bold option paragraphs inside it are fine)."""
    ms = list(FIELD_LABEL_RE.finditer(body))
    out = {}
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(body)
        content = body[m.end():end]
        content = re.sub(r"^\s*(\([^)\n]*\)\s*:)?\s*:?", "", content)
        out.setdefault(m.group(1).lower(), "")
        out[m.group(1).lower()] += content
    return out


def field_ok(content, allow_na=True):
    t = re.sub(r"[`*_\s>]", "", content)
    if re.match(r"^\W*not applicable\b", content.strip(), re.I):
        return allow_na and re.match(r"^\W*not applicable:\s*\S.{9,}", content.strip(), re.I) is not None
    return len(t) >= 20


def mentions(need, shown):
    """Does the visible text show `need`? A result name is matched by its number with word
    boundaries ("Lemma 4.20" is shown by "Lemmas 4.16, 4.20"); anything else literally."""
    m = NUM_RE.search(need)
    if m and need != "[PROXY":
        return re.search(rf"(?<![\d.]){re.escape(m.group(0).lower())}(?![\d])", shown) is not None
    return need.lower() in shown


def check(text, required, round_name=None, box_lines=(), names=None, level="involved", answer=None,
          human_decided=(), stops=None, escalations=(), decided=None):
    """Problems of a filled decisions document. `level` is the involvement level chosen at intake;
    a delegating one (statements-only, hands-off) also requires the "Decisions taken on your behalf"
    framing, the verbatim intake `answer`, the DISCLOSURE sentence, and in every decision section a
    filled **Decision taken** field that shows "[DELEGATED" (unless it says why it does not apply).
    `decided`: {anchor: its decision line logged in RUN_LOG.md} (skeleton.decided): that line must stand
    word for word in its item's Decision taken, one tagged line per item (B11 review: M2/M3/M4)."""
    probs = []
    decided = decided or {}
    norm_ = lambda x: " ".join(str(x).split())
    deleg = level in DISCLOSURE
    if deleg:
        h1 = re.search(r"^# (.*)$", text, re.M)
        if not h1 or not h1.group(1).startswith("Decisions taken on your behalf"):
            probs.append(f"under the {level} level the document must be headed '# Decisions taken on "
                         f"your behalf — …' (nobody was asked)")
        flat = " ".join(re.sub(r"<!--.*?-->", "", text, flags=re.S).split())
        if not str(answer or "").strip():
            probs.append(f"the human's intake answer choosing {level} is not recorded "
                         f"(config involvement_answer), so the document cannot quote it")
        elif f'verbatim: "{" ".join(str(answer).split())}"' not in flat:
            probs.append(f"the human's intake answer choosing {level} is not quoted verbatim "
                         f"(as `verbatim: \"<answer>\"`): {answer!r}")
        gl = text.find(GLANCE_HEADING)
        dec_at = re.search(r"^## Decisions\b", text, re.M)
        if gl < 0 or (dec_at and gl > dec_at.start()):
            probs.append(f"no summary table {GLANCE_HEADING!r} before the decisions")
        else:
            body_gl = text[gl:dec_at.start() if dec_at else len(text)]
            rows_gl = [c for hd, c in table_rows(body_gl) if hd and hd[0].startswith("decision")]
            n_sec = len({k for k in range(len(sections_of(text)))
                         if ANCHOR_RE.search(sections_of(text)[k][1])})
            if len(rows_gl) < n_sec:
                probs.append(f"the summary table has {len(rows_gl)} row(s) for {n_sec} decision section(s): one row "
                             f"per section (per matter), listing the reversal cost of each of its items")
            for c in rows_gl:
                # B11: a matter's row may list several items' sources and costs ("re-approve; none")
                bare = lambda i: re.sub(r"\([^()]*\)", "", c[i] if len(c) > i else "")
                fols = [x.strip("* ").lower() for x in bare(2).split(";") if x.strip("* ")]
                costs = [x.strip("* ").lower() for x in re.split(r"[;,]", bare(3)) if x.strip("* ")]
                if not fols or not all(any(f_.startswith(x) for x in FOLLOWED) for f_ in fols):
                    probs.append(f"summary row {c[0][:40]!r}: 'Followed' must be one of {', '.join(FOLLOWED)} "
                                 f"(several separated by ';')")
                elif not costs or not all(x in REVERSAL_COSTS or (x == "not applicable" and any(
                        f_.startswith("human") for f_ in fols)) for x in costs):
                    probs.append(f"summary row {c[0][:40]!r}: 'Reversal cost' must be one of {', '.join(REVERSAL_COSTS)} "
                                 f"(several separated by ';')")
        if DISCLOSURE[level] not in flat:
            probs.append(f"the disclosure sentence for the {level} level is missing: {DISCLOSURE[level]!r}")
    tag = ROUND_TAG_RE.search(text)
    if round_name and (not tag or tag.group(1) != round_name):
        probs.append(f"document was written for round {tag.group(1) if tag else '?'}, not {round_name}")
    if FILL in text:
        probs.append(f"{text.count(FILL)} placeholder(s) still unfilled ({FILL} ... >>)")
    prose = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    prose = re.sub(r"^\s*(```|~~~).*?^\s*(```|~~~)", "", prose, flags=re.S | re.M)
    prose = re.sub(r"`[^`\n]*`", "", prose)
    m = PLACEHOLDER_WORDS.search(prose)
    if m:
        probs.append(f"placeholder text left in the document: {m.group(0)!r}")
    m = UNVERIFIABLE_ORDER.search(prose)
    if m:
        probs.append(f"an unverifiable claim about the order of work: {m.group(0)!r}. State only what the record "
                     f"shows: the statements' commit and time, the approval's commit and time, and that the freeze "
                     f"check shows them unchanged since (drafts of proofs may predate the approval)")
    if BOX_START not in text:
        probs.append(f"no 'Read this first' box: the document must open with a blockquote starting "
                     f"{BOX_START!r}")
    box = ""
    if BOX_START in text:
        i = text.index(BOX_START)
        first_anchor = ANCHOR_RE.search(text)
        bg = re.search(r"^## Background", text, re.M)
        if first_anchor and i > first_anchor.start():
            probs.append("the 'Read this first' box must come before the decisions")
        if bg and i > bg.start():
            probs.append("the 'Read this first' box must come before the background")
        lines = text[i:].splitlines()
        box = "\n".join(l for l in lines[:next((k for k, l in enumerate(lines) if not l.startswith(">")), len(lines))])
    for bl in box_lines:
        if bl not in box:
            probs.append(f"the 'Read this first' box lost a recorded entry (it must stay inside the box): "
                         f"{bl[:80]!r}")
    placed, secs = {}, []
    for h, b in sections_of(text):
        visible = "\n".join(l for l in b.splitlines() if not l.startswith("\x00"))
        anchors_here = ANCHOR_RE.findall(visible)
        # what the reader sees: no HTML comments (an empty field filled with a comment is empty)
        seen = re.sub(r"<!--.*?-->", "", visible, flags=re.S)
        secs.append((h, seen))
        for a in anchors_here:
            placed.setdefault(a, len(secs) - 1)
    for a in required:
        if a not in placed:
            probs.append(f"item dropped: {a}  (keep its anchor `<!-- item:{a} -->` under the decision that covers it)")
    for a in sorted(set(placed) - set(required)):
        probs.append(f"anchor {a} is no longer an item of the record (renamed or answered?): remove it")
    for k in sorted(set(placed.values())):
        h, b = secs[k]
        f = fields_of(b)
        for lab in ("paper", "lean", "evidence", "options", "recommendation"):
            if lab not in f or not field_ok(f[lab], allow_na=lab in ("paper", "lean", "evidence")):
                probs.append(f"section {h.strip()!r}: field {lab.capitalize()} missing or empty "
                             + ("(write 'Not applicable: <why>' where it does not apply)"
                                if lab in ("paper", "lean", "evidence") else "(it always applies)"))
        if deleg:
            dt = f.get("decision taken")
            here = [a for a, kk in placed.items() if kk == k]
            na = dt is not None and re.match(r"^\W*not applicable\b", dt.strip(), re.I)
            if dt is None or not field_ok(dt):
                probs.append(f"section {h.strip()!r}: field Decision taken missing or empty (under the "
                             f"{level} level every decision says what was done and how to reverse it; "
                             f"'Not applicable: <why>' only where the human decided it at Checkpoint B)")
            elif na:
                if not here or not all(a in human_decided for a in here):
                    probs.append(f"section {h.strip()!r}: 'Not applicable' in Decision taken is allowed only "
                                 f"for an item the human decided at Checkpoint B (statements-only); this "
                                 f"one was decided on the reader's behalf")
            else:
                tg = DELEGATED_TAG_RE.search(dt or "")
                rest = DELEGATED_TAG_RE.sub("", dt or "")
                if not tg or tg.group(2) != level:
                    probs.append(f"section {h.strip()!r}: its Decision taken field must quote the canonical "
                                 f"[DELEGATED <date>, operator under {level} (intake); reversal: <cost>] tag "
                                 f"(who decided, and what reversing costs, must show)")
                if not re.search(r"revers", rest, re.I):
                    probs.append(f"section {h.strip()!r}: its Decision taken field must say how to reverse it")
                n_tags = len(DELEGATED_TAG_RE.findall(dt or ""))
                if n_tags > max(1, len(here)):
                    # B11 review (M3): one decision line per item, never one line for several
                    probs.append(f"section {h.strip()!r}: its Decision taken field carries {n_tags} [DELEGATED] "
                                 f"tags for {len(here)} item(s): exactly one tagged decision line per item")
                if len(here) > 1:
                    # several items: each its own line with its own tag (review of fix-mini2, M1); a line
                    # names exactly one item (B11 review, M3: one tagged line named all five anchors)
                    bind = lambda l_: [a for a in here if re.search(
                        rf"(?<![\w.:/@+-]){re.escape(a.split('@')[0])}(?![\w.:/@+-])", l_)]
                    for l_ in (dt or "").splitlines():
                        if len(bind(l_)) > 1:
                            probs.append(f"section {h.strip()!r}: one Decision taken line names "
                                         f"{len(bind(l_))} items ({', '.join(a.split('@')[0] for a in bind(l_))}): "
                                         f"each item gets its own line with its own tag")
                    for a in here:
                        lines_a = [l for l in (dt or "").splitlines() if bind(l) == [a]]
                        if len(lines_a) != 1 or not ((t_ := DELEGATED_TAG_RE.search(lines_a[0])) and t_.group(2) == level):
                            probs.append(f"section {h.strip()!r} holds {len(here)} items: its Decision taken "
                                         f"field needs exactly one line for `{a.split('@')[0]}` with that item's own "
                                         f"[DELEGATED …; reversal: <cost>] tag")
                        elif a in decided and norm_(decided[a]) not in norm_(lines_a[0]):
                            probs.append(f"section {h.strip()!r}: the line for `{a.split('@')[0]}` must quote its "
                                         f"decision as logged in RUN_LOG.md, word for word: {decided[a][:100]!r} "
                                         f"(a decision is changed by logging a new one, not by editing the document)")
                else:
                    for a in here:
                        if a in decided and norm_(decided[a]) not in norm_(dt or ""):
                            probs.append(f"section {h.strip()!r}: its Decision taken must quote the decision as "
                                         f"logged in RUN_LOG.md, word for word: {decided[a][:100]!r} (a decision is "
                                         f"changed by logging a new one, not by editing the document)")
                rec = f.get("recommendation", "")
                cited = re.search(r"stops/(S\d+)/", rec)
                # the stop must exist, be closed by the operator, and be this item's stop (its
                # [DELEGATED] line quoted in the section names it)
                stop_ok = bool(re.search(r"cause table", rec, re.I) and cited and cited.group(1) in (stops or ())
                               and f"stop {cited.group(1)} closed" in b)
                # review 1: an accepted ANSWERABLE escalation is a written recommendation (RUN.md)
                esc_ok = any(e["name"] == m_.group(1).upper() and (e["answer"] or "").startswith("ANSWERABLE")
                             for m_ in ESC_CITE.finditer(rec) for e in escalations)
                if not re.search(r"conservative rule", rec, re.I) and not (
                        re.search(r"adjudicator", rec, re.I) and re.search(r"\d{4}-\d{2}-\d{2}-", rec)
                        and "ADOPTED" in rec) and not stop_ok and not esc_ok:
                    probs.append(f"section {h.strip()!r}: under the {level} level the Recommendation cites "
                                 f"its source: the adjudicator's row (round and ADOPTED.md) it follows, the "
                                 f"cause table and the stop's record (stops/S<n>/), an accepted ANSWERABLE "
                                 f"escalation (\"escalation E<n>\"), or the words 'conservative "
                                 f"rule' (never a recommendation the operator wrote)")
    # review 1: a section citing an escalation shows its answer, and for a re-ask the earlier NEEDS-HUMAN
    by_e = {e["name"]: e for e in escalations}
    for h, b in secs:
        for n_ in sorted({m_.group(1).upper() for m_ in ESC_CITE.finditer(h + b)}):
            e = by_e.get(n_)
            if not e or not e["answer"]:
                continue        # escalation_citations reports it
            flat_b = " ".join(b.split())
            if " ".join(e["answer"].split()) not in flat_b:
                probs.append(f"section {h.strip()!r} cites escalation {n_} but does not show its answer "
                             f"({e['answer'][:80]!r})")
            prev = by_e.get(e["reask_of"]) if e["reask_of"] else None
            if prev and not (re.search(rf"\bescalation {prev['name']}\b", flat_b, re.I)
                             and " ".join((prev["answer"] or "").split()) in flat_b):
                probs.append(f"section {h.strip()!r} cites escalation {n_}, a re-ask of escalation {prev['name']} "
                             f"({(prev['answer'] or 'no accepted answer')[:60]!r}), without showing escalation "
                             f"{prev['name']} and its answer")
    for a, k in placed.items():
        h, b = secs[k]
        need = (names or {}).get(a)
        shown = (h + b).lower()
        if need and not mentions(need, shown):
            probs.append(f"section {h.strip()!r} carries anchor {a} but never mentions {need!r}")
    return probs


ESC_CITE = re.compile(r"\bescalation (?:check )?(E[0-9]+)\b", re.I)     # lanecheck.ESC_CITE_RE


def escalation_note(cfg, text, recs=None):
    """The skeleton's note for an item whose record cites escalations (review 1): each cited one with its
    answer (lanecheck.escalation_line), and the earlier NEEDS-HUMAN a re-ask repeats. "" when none."""
    cited = sorted({m_.group(1).upper() for m_ in ESC_CITE.finditer(text or "")}, key=lambda x: int(x[1:]))
    if not cited:
        return ""
    import lanecheck
    recs = lanecheck.escalations(cfg) if recs is None else recs
    by = {e["name"]: e for e in recs}
    show = []
    for n_ in cited:
        e = by.get(n_)
        if e and e["reask_of"] and e["reask_of"] not in show:
            show.append(e["reask_of"])
        if n_ not in show:
            show.append(n_)
    return ("Escalations cited (every escalation is listed in the report with its answer; keep these lines):\n\n"
            + "".join(f"- {lanecheck.escalation_line(by[n_], by)}\n" if n_ in by else
                      f"- escalation {n_}: never written\n" for n_ in show) + "\n")


def record_problems(cfg):
    """Record faults that would hide or blur an item: a VACUOUS.md status that is neither open nor
    'repaired in <commit>'; a [PROXY] tag under `## Answered` that is neither the start of the
    answer nor quoted (is it a proxy decision, or a quotation of one?); and a result left unproved
    that no round has adjudicated since its line (pending_refusal: refused here as at --deliver)."""
    out = []
    log = _read(os.path.join(project.REPO, cfg["rounds_dir"], "RUN_LOG.md"))
    for sec in re.findall(r"^## Answered\b.*?$(.*?)(?=^## |\Z)", log, re.M | re.S):
        for line in sec.splitlines():
            if re.match(r"^\s*[-*]\s+\S", line) and not ANSWER_LINE_RE.match(line) and "[proxy" not in line.lower():
                out.append(f"RUN_LOG.md `## Answered`: {line.strip()[:80]!r} is not an answer line "
                           f"(`- answered <anchor> (<date>, <round>): <answer>`), so it answers nothing")
            bare = QUOTED_RE.sub("", line)
            if "[PROXY" in bare and not re.match(r'^\s*-\s*(?:answered \S+\s*(?:\([^)\n]*\))?\s*[:—-]?\s*)?\[PROXY', bare, re.I):
                out.append(f"RUN_LOG.md `## Answered`: {line.strip()[:80]!r} has a [PROXY] tag mid-answer: "
                           f"quote it if it is a quotation; start the answer with it if it is a proxy decision")
    out += tag_problems(log, project.involvement(cfg) if project.delegates(cfg) else None)
    import lanecheck     # review 1: a cited escalation exists and was accepted; involved: no re-ask of a NEEDS-HUMAN
    out += ["RUN_LOG.md " + t for t in lanecheck.escalation_citations(cfg, log)]
    pend = pending_refusal(cfg)
    if pend:
        out.append(pend)
    if project.delegates(cfg):
        for h, t in dropped_delegated(cfg, log, project.involvement(cfg)):
            out.append(f"RUN_LOG.md: the [DELEGATED] decision committed in {h[:10]} is no longer in the log: "
                       f"{t[:100]!r}. A decision is never removed or reworded: restore its line; to change "
                       f"the decision, log the new one on a new line beside it")
        for line in mentions_masked(strip_sections(log, ("Fresh readers",))).splitlines():
            if PROXY_RE.search(line):
                out.append(f"RUN_LOG.md records a [PROXY] decision under the {project.involvement(cfg)} "
                           f"level, where nothing is provisional: a decision the level delegates is "
                           f"tagged DELEGATED; the human's own Checkpoint B answer is untagged: {line.strip()[:80]!r}")
    if not project.delegates(cfg):
        for t in delegated_decisions(log)[:5]:
            out.append(f"RUN_LOG.md records a [DELEGATED] decision, but the involvement level is "
                       f"{project.involvement(cfg)!r}, which delegates nothing: {t[:80]!r} (a decision "
                       f"taken for the human there is a [PROXY], put to them at Checkpoint C)")
    for header, cells in table_rows(_read(os.path.join(project.REPO, cfg["rounds_dir"], "VACUOUS.md"))):
        if "status" in header and len(cells) > header.index("status"):
            st = cells[header.index("status")].strip()
            if not is_repaired(st) and not re.match(r"^\W*open\b", st, re.I):
                out.append(project.Finding(f"VACUOUS.md: status {st!r} is neither 'open' nor 'repaired in "
                                           f"<commit>' (the row is treated as open)", "record-format"))
    return out


def resolve_round(cfg, wanted, allow_older):
    rounds = project.rounds(cfg)
    if not rounds:
        return None, None, "no rounds"
    last = rounds[-1]
    if wanted and os.path.basename(last) != wanted:
        hit = [d for d in rounds if os.path.basename(d) == wanted]
        if not hit:
            return None, None, f"no round {wanted}"
        if not allow_older:
            return None, None, (f"{wanted} is not the newest round ({os.path.basename(last)}); an older "
                                f"round drops newer items -- pass --allow-older only on purpose")
        last = hit[0]
    return rounds[:rounds.index(last) + 1], last, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--round")
    ap.add_argument("--allow-older", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", help="with --write: write the skeleton here instead")
    ap.add_argument("--file", help="with --check: check this file instead")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.write == a.check:
        ap.error("give exactly one of --write / --check")
    if a.write and a.file:
        ap.error("--file goes with --check; to write elsewhere use --out")
    if a.check and a.out:
        ap.error("--out goes with --write; to check another file use --file")
    try:
        cfg, _ = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    if project.involvement(cfg) not in project.INVOLVEMENT_LEVELS:
        print(f"FAIL: project config: involvement is {project.involvement(cfg)!r}, not one of "
              f"{', '.join(project.INVOLVEMENT_LEVELS)}", file=sys.stderr)
        return 2
    rounds, last, err = resolve_round(cfg, a.round, a.allow_older)
    if err:
        print(f"FAIL: {err}", file=sys.stderr); return 2
    text, anchors = skeleton(cfg, rounds, last)
    target = os.path.join(project.REPO, cfg["rounds_dir"], "DECISIONS.md")
    if a.write and a.out:
        target = os.path.abspath(a.out)
    if a.check and a.file:
        target = os.path.abspath(a.file)
    if a.write:
        if os.path.exists(target):
            print(f"FAIL: {target} exists; it may hold the writer's work. Move it aside first "
                  f"(DECISIONS.<date>.md).", file=sys.stderr)
            return 2
        open(target, "w", encoding="utf-8").write(text)
        print(f"wrote {os.path.relpath(target, project.REPO)}: {len(anchors)} item(s) to fill")
        return 0
    if not os.path.exists(target):
        print(f"FAIL: {target} missing; run --write first", file=sys.stderr); return 1
    # The required set is recomputed from the record now, so an item that appeared after --write
    # (a new QUESTION row, a new [PROXY]) is also demanded.
    import lanecheck
    esc = lanecheck.escalations(cfg)
    probs = check(open(target, encoding="utf-8").read(), anchors, os.path.basename(last),
                  [f"> - {bl}" for bl in box_lines(cfg)], skeleton.names, project.involvement(cfg),
                  cfg.get("involvement_answer") if project.delegates(cfg) else None,
                  skeleton.human_decided, stops=delegated_stops(cfg), escalations=esc,
                  decided=skeleton.decided) + record_problems(cfg)
    # review 1: what DECISIONS.md cites is checked like the log (exists, accepted; involved: no re-ask)
    probs += ["DECISIONS.md " + t for t in lanecheck.escalation_citations(cfg, open(target, encoding="utf-8").read(), esc)]
    probs, disc = project.split(cfg, probs)
    for p in probs:
        print(project.problem_line(p, "decisions"))
    for p in disc:
        print(project.disclosed_line(p))
    print(f"decisions check: {len(anchors)} required item(s), {len(probs)} problem(s)"
          + (f", {len(disc)} disclosed (release mode: stops.py disclose records them)" if disc else ""))
    return 1 if probs else 0


def _unproved_controls(say):
    """A result left unproved by a [DELEGATED] decision (unproved()): only a valid line exempts."""
    T = "- [DELEGATED 2026-10-20, operator under {} (intake); reversal: {}] leave {} unproved \u2014 no proof found\n"
    OQ = "## Open questions\n"
    ho = {"involvement": "hands-off", "rounds_dir": "x"}
    u = unproved(ho, OQ + T.format("hands-off", "re-prove", "`N.lem_a`")
                 + T.format("hands-off", "re-prove", "N.lem_b"), goals=())
    say("unproved: a canonical 'leave <decl> unproved' line (backticks optional) exempts exactly its declarations",
        set(u["decls"]) == {"N.lem_a", "N.lem_b"} and u["decls"]["N.lem_a"].startswith("[DELEGATED 2026-10-20")
        and not u["problems"])
    for what, cfg_, line in (
            ("under the involved level (the human decides)", dict(ho, involvement="involved"),
             T.format("hands-off", "re-prove", "N.lem_a")),
            ("with a reversal other than re-prove", ho, T.format("hands-off", "none", "N.lem_a")),
            ("naming another level than the run's", ho, T.format("statements-only", "re-prove", "N.lem_a")),
            ("naming a paper result instead of a Lean name", ho, T.format("hands-off", "re-prove", "Lemma 2.3"))):
        u = unproved(cfg_, OQ + line, goals=())
        say(f"unproved: a line {what} exempts nothing and is a problem", not u["decls"] and u["problems"])
    u = unproved(ho, OQ + T.format("hands-off", "re-prove", "N.goal"), goals={"N.goal"})
    say("unproved: a goal result is refused (it stays a stop)", not u["decls"] and u["goal"] == ["N.goal"])
    # HIGH 1 (review of Q1): the index cites the goal unqualified; resolved as the dependency walk
    # resolves it (as written, then namespace ++ name) it is still the goal
    import dependencies
    keep = dependencies.goal_roots, dependencies.project_decls
    try:
        dependencies.goal_roots = lambda c_: ["thm_2_7", "N.cor_2_8", "ghost"]
        dependencies.project_decls = lambda c_: {"N.thm_2_7", "N.cor_2_8", "N.lem_a"}
        hn = dict(ho, namespace="N")
        gd = goal_decls(hn)
        u = unproved(hn, OQ + T.format("hands-off", "re-prove", "N.thm_2_7"))
        say("unproved: a goal the index cites by its short name is resolved (namespace ++ name) and refused; "
            "an unresolved one stands for both forms",
            gd == {"N.thm_2_7", "N.cor_2_8", "ghost", "N.ghost"} and not u["decls"] and u["goal"] == ["N.thm_2_7"]
            and set(unproved(hn, OQ + T.format("hands-off", "re-prove", "N.lem_a"))["decls"]) == {"N.lem_a"})
    finally:
        dependencies.goal_roots, dependencies.project_decls = keep
    say("dependencies.resolve_name: as written, then namespace ++ name, else None",
        dependencies.resolve_name("N.a", "N", {"N.a"}) == "N.a" and dependencies.resolve_name("a", "N", {"N.a"}) == "N.a"
        and dependencies.resolve_name("a", "N", {"a", "N.a"}) == "a" and dependencies.resolve_name("b", "N", {"N.a"}) is None)
    u = unproved(ho, "## Fresh readers\n" + T.format("hands-off", "re-prove", "N.lem_a"), goals=())
    say("unproved: a line quoted under Fresh readers is not a decision", not u["decls"])
    # LOW 5: only a decision line of a decision section counts
    L = T.format("hands-off", "re-prove", "N.lem_a")
    for what, log in (("in another section (Rounds)", "## Rounds\n" + L),
                      ("before any section", L),
                      ("in a blockquote", OQ + "> " + L),
                      ("indented (a nested quote)", OQ + "  " + L),
                      ("inside a sentence ('considered … but rejected')",
                       OQ + "- considered " + L[2:].rstrip() + " but rejected it\n")):
        say(f"unproved: a leave line {what} is not a decision (exempts nothing)",
            not unproved(ho, log, goals=())["decls"])
    tag = L[2:].split("]")[0] + "]"
    u = unproved(ho, "## Checkpoint C (2026-10-20, delegated)\n- skip:lemma-2-3: " + tag + " leave N.lem_c unproved \u2014 x\n"
                 "## Answered\n- answered skip:lemma-2-3 (2026-10-20, 2026-10-20-full-abc): " + tag
                 + " leave N.lem_c unproved \u2014 x\n", goals=())
    say("unproved: the anchored Checkpoint C form and the answered form are decision lines",
        set(u["decls"]) == {"N.lem_c"})
    # re-check of Q1 (b), LOW: the anchor must be a real decisions anchor; a free word is not one
    for pre in ("considered: ", "rejected: ", "answered considered (2026-10-20, r): "):
        say(f"unproved: a leave line opening with {pre.strip()!r} (not a decisions anchor) exempts nothing",
            not unproved(ho, OQ + "- " + pre + L[2:], goals=())["decls"])
    import inspect
    used = set(re.findall(r'(?:anchor_id|versioned)\("([a-z-]+)"', inspect.getsource(sys.modules[__name__])))
    say("unproved: every anchor kind decisions.py writes is a kind a leave line may open with",
        used and used <= set(ANCHOR_KINDS))
    say("unproved: the tag lint refuses a leave-unproved line whose reversal is not re-prove",
        any("re-prove" in p_ for p_ in tag_problems(T.format("hands-off", "none", "N.lem_a"), "hands-off"))
        and not tag_problems(T.format("hands-off", "re-prove", "N.lem_a"), "hands-off"))
    d = tempfile.mkdtemp(prefix="decisions-unproved-")
    saved = globals()["committed_log"], globals()["goal_decls"]
    try:
        globals()["committed_log"] = lambda cfg_: OQ + T.format("hands-off", "re-prove", "N.lem_a")
        globals()["goal_decls"] = lambda cfg_: set()
        bl = box_lines(dict(ho, rounds_dir=d))
        say("unproved: the box lists each result left unproved as 'stated, not proved', with its tag",
            any(b.startswith("stated, not proved: `N.lem_a`") and "reversal: re-prove" in b for b in bl))
        # re-check of Q1 (b), MED-B: --check (run before the completion message) refuses while an
        # exemption is pending, with the --deliver refusal; nothing pending, no such problem
        keep_p = globals()["pending_unproved"]
        try:
            globals()["pending_unproved"] = lambda c_: ["N.lem_a"]
            rp_pend = record_problems(dict(ho, rounds_dir=d))
            globals()["pending_unproved"] = lambda c_: []
            rp_none = record_problems(dict(ho, rounds_dir=d))
        finally:
            globals()["pending_unproved"] = keep_p
        say("unproved: decisions.py --check refuses while a result left unproved awaits its adjudication "
            "(the --deliver refusal); nothing pending, no such problem",
            any("no round has adjudicated since: `N.lem_a`" in p_ for p_ in rp_pend)
            and not any("adjudicated since" in p_ for p_ in rp_none))
    finally:
        globals()["committed_log"], globals()["goal_decls"] = saved
        shutil.rmtree(d, ignore_errors=True)
    # the SKIPPED.md row is due once a round has been adjudicated since the line was committed;
    # keyed on the declaration (MED 3), so rewording the line does not make it pending again
    import subprocess
    d = tempfile.mkdtemp(prefix="decisions-adj-")
    keep = project.REPO, project.AUDITS
    try:
        project.REPO = project.AUDITS = d
        G = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      capture_output=True, text=True)
        G("init", "-q")
        os.makedirs(os.path.join(d, "rr", "r1"))
        os.makedirs(os.path.join(d, "rr", "r2"))
        lp = os.path.join(d, "rr", "RUN_LOG.md")
        open(lp, "w").write("# log\n" + OQ + T.format("hands-off", "re-prove", "N.lem_a"))
        G("add", "-A"); G("commit", "-qm", "log")
        c_ = {"rounds_dir": "rr", "involvement": "hands-off"}
        before = adjudicated_since(c_, "N.lem_a")
        pend_before = pending_unproved(c_)
        open(os.path.join(d, "rr", "r1", "ADOPTED.md"), "w").write("x")
        G("add", "-A"); G("commit", "-qm", "adjudication")
        after = adjudicated_since(c_, "N.lem_a")
        # reword the line (RUN_LOG.md is not append-only): still adjudicated
        open(lp, "w").write("# log\n" + OQ + T.format("hands-off", "re-prove", "N.lem_a").replace("no proof found", "reworded"))
        G("add", "-A"); G("commit", "-qm", "reword")
        reworded = adjudicated_since(c_, "N.lem_a")
        # LOW 6: a line committed in the same commit as an ADOPTED.md is pending until the next one
        open(lp, "a").write(T.format("hands-off", "re-prove", "N.lem_d"))
        open(os.path.join(d, "rr", "r2", "ADOPTED.md"), "w").write("x")
        G("add", "-A"); G("commit", "-qm", "log + adjudication")
        same = adjudicated_since(c_, "N.lem_d")
        open(lp, "a").write(T.format("hands-off", "re-prove", "N.lem_c"))
        say("unproved: its SKIPPED.md row is pending until a round is adjudicated after the log line, then due; "
            "the committed log is what counts (an uncommitted line exempts nothing)",
            before is False and pend_before == ["N.lem_a"] and after is True
            and adjudicated_since(c_, "N.never_logged") is True
            and "leave N.lem_a unproved" in committed_log(c_) and "N.lem_c" not in committed_log(c_))
        say("unproved: pending is keyed on the declaration: rewording its line does not make it pending again",
            reworded is True)
        say("unproved: a line committed together with an ADOPTED.md stays pending until the next adjudication",
            same is False and pending_unproved(c_) == ["N.lem_d"])
        # B11 review (M4): a committed [DELEGATED] decision removed (or reworded) is a record problem
        DQ = "- check:Lemma_2.1: [DELEGATED 2026-01-05, operator under hands-off (intake); reversal: none] keep DROPQZ — rule\n"
        open(lp, "a").write(DQ)
        G("add", "-A"); G("commit", "-qm", "decide")
        cur_ = open(lp).read()
        dr = lambda t_: [p_ for p_ in record_problems(dict(c_, name="T")) if "no longer in the log" in p_ and t_ in p_]
        kept = dr("DROPQZ")
        open(lp, "w").write(cur_.replace(DQ, ""))
        removed = dr("DROPQZ")
        open(lp, "w").write(cur_.replace("keep DROPQZ", "dropped DROPQZ"))
        rewr = dr("DROPQZ")
        open(lp, "w").write(cur_.replace(DQ, "## Answered\n" + DQ.replace("- check:Lemma_2.1:", "- answered check:Lemma_2.1 (2026-01-05, r2):")
                                         .replace("— rule", "— rule, see stop S1")))
        moved = dr("DROPQZ")
        open(lp, "w").write(cur_.replace(DQ, ""))
        inv = [p_ for p_ in record_problems(dict(c_, involvement="involved")) if "no longer in the log" in p_]
        # a line the tag check refuses (a leave line whose reversal is not re-prove) may be corrected
        BADQ = "- [DELEGATED 2026-01-05, operator under hands-off (intake); reversal: none] leave N.lem_q unproved — TAGFIXQZ\n"
        open(lp, "w").write(cur_ + BADQ)
        G("add", "-A"); G("commit", "-qm", "bad tag")
        open(lp, "w").write(cur_ + BADQ.replace("reversal: none", "reversal: re-prove"))
        tagfix = dr("N.lem_q")
        open(lp, "w").write(cur_)
        tagdrop = dr("N.lem_q")
        say("B11 review (M4): correcting a line the tag check refuses is not a removal", not tagfix and not tagdrop)
        say("B11 review (M4): a committed [DELEGATED] decision removed from RUN_LOG.md, or reworded, is a record "
            "problem (decisions --check fails); kept, moved to another section or extended, it is not",
            not kept and removed and rewr and not moved and not inv)
    finally:
        project.REPO, project.AUDITS = keep
        shutil.rmtree(d, ignore_errors=True)


def selftest():
    results = []
    def say(name, ok):
        results.append(ok); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    tmp = tempfile.mkdtemp(prefix="decisions-")
    try:
        _selftest(tmp, say)
        _open_question_controls(tmp, say)
        _open_question_strict(tmp, say)
        _unproved_controls(say)
        _matter_controls(say)
        _per_matter_controls(tmp, say)
        _question_level_controls(tmp, say)
        _checkpoint_c_controls(tmp, say)
        _checkpoint_b_decided_controls(tmp, say)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "ok" if all(results) else "FAILED")
    return 0 if all(results) else 1


def _per_matter_controls(tmp, say):
    """B11 (U2 §6.1, D3 §4): one decision section per matter. A QUESTION on a paper result and a delegated line
    answering it join that result's section; items on no result are grouped by kind (the human's own questions
    stay apart under `involved`); the writer's field prompts never make an item "about the approval"; an item the
    operator already decided under a delegating level keeps its section with its logged decision; answered items
    are listed once per matter; the at-a-glance table has one row per section."""
    rd = os.path.join(tmp, "b11")
    r1 = os.path.join(rd, "2026-02-01-full-aaaaaaa")
    os.makedirs(r1)
    json.dump({"_meta": {"kind": "statements"}}, open(os.path.join(r1, "TARGET.json"), "w"))
    json.dump({"global": [{"id": "G1", "title": "naturals", "text": "GONEQZ"}, {"id": "G2", "title": "casts", "text": "GTWOQZ"}],
               "rows": [{"result": "Lemma 2.2", "flag": "CHECK", "check_reason": "CHECKQZ"}]},
              open(os.path.join(r1, "SIGNOFF.json"), "w"))
    open(os.path.join(r1, "ADOPTED.md"), "w").write(
        "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        "| pf | Lemma 2.2 | Fail | **QUESTION** | add the standing defer? |\n"
        "| subst | Paper.helper_a | Fail | **QUESTION** | duplicate witness A |\n"
        "| subst | Paper.helper_b | Fail | **QUESTION** | duplicate witness B |\n")
    open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
        "| # | where | status | repair | what |\n|---|---|---|---|---|\n"
        "| 1 | Lemma 2.2, tex l.40 | false | add hypothesis | DEFQZ |\n")
    json.dump({"round": os.path.basename(r1), "by": "agent", "date": "2026-02-01", "commit": "c"},
              open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
    R = os.path.basename(r1)
    TG = "[DELEGATED 2026-02-02, operator under hands-off (intake); reversal: {}] "
    base_log = ("# Run log\n## Rounds\n- " + TG.format("re-approve") + f"approved the sheet of round {R}\n"
                "- " + TG.format("none") + f"do not add the standing defer QROWQZ (QUESTION row on Lemma 2.2, round {R})\n"
                "- check:Lemma_2.2: " + TG.format("none") + "PREQZ keep the CHECK row's reading\n")
    cfg = {"name": "T", "rounds_dir": "b11", "lean_files": []}
    hcfg = dict(cfg, involvement="hands-off", involvement_answer="(c) hands-off")
    g = globals(); saved = (project.REPO, g["changes_after"])
    project.REPO = tmp
    g["changes_after"] = lambda c, r: []

    def gen(c, log):
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(log)
        t_, a_ = skeleton(c, [r1], r1)
        return t_, a_, {h_.strip()[4:]: ANCHOR_RE.findall(b_) for h_, b_ in sections_of(t_) if ANCHOR_RE.search(b_)}
    try:
        th, ah, sh = gen(hcfg, base_log)
        l33 = next((v for k, v in sh.items() if k.startswith("Lemma 2.2 (")), [])
        say("B11: the CHECK row, the QUESTION on 'Lemma 2.2', the defect and the delegated lines answering it "
            "('QUESTION row on Lemma 2.2', '- check:Lemma_2.2: [DELEGATED') are ONE section",
            "check:Lemma_2.2" in l33 and "question:Lemma_2.2" in l33 and any(a.startswith("defect:") for a in l33)
            and sum(a.startswith("delegated:") for a in l33) == 2)
        appr = next((v for k, v in sh.items() if k.startswith("Statement approval")), [])
        say("B11: a delegated line naming the approved round joins the approval only by its own words (the field "
            "prompt 're-approval?' made QROWQZ 'about the approval')",
            len(appr) == 2 and not any("QROWQZ" in b_ for h_, b_ in sections_of(th) if h_.startswith("### Statement approval")))
        dt33 = next((b_ for h_, b_ in sections_of(th) if h_.startswith("### Lemma 2.2 (")), "").split("**Decision taken:**")[-1]
        say("B11: a delegated line's Decision taken line is the logged line itself (a run retyped it twice)",
            re.search(r"^- \*Decision logged during the run:\* \[DELEGATED [^\n]*QROWQZ[^\n]*\(logged;[^\n]*<sub>`delegated:", dt33, re.M) is not None
            and re.search(r"^- \*Decision logged during the run:\* \[DELEGATED [^\n]*PREQZ[^\n]*\(logged;[^\n]*<sub>`delegated:", dt33, re.M) is not None)
        dec_h = th.split("## Decisions", 1)[1]
        say("B11 review: a decided delegated line is shown once (in its Decision taken line), not also in its "
            "heading and a run-log quote", dec_h.count("QROWQZ") == 1 and dec_h.count("PREQZ") == 1)
        lines33 = [l_ for l_ in dt33.splitlines() if l_.startswith("- ")]
        say("B11 review: a merged section's Decision taken lines open with the item's plain label; its anchor id "
            "is small, at the end", len(lines33) == len(l33)
            and all(re.fullmatch(r"- \*[^`\n]+:\* .*<sub>`[^`]+`</sub>", l_) for l_ in lines33)
            and any(l_.startswith("- *CHECK row: Lemma 2.2:* ") for l_ in lines33)
            and not any(h_.startswith("### ") and "one matter" in h_ for h_, _ in sections_of(th)))
        say("B11: the global differences are one section; under hands-off the questions on no paper result too",
            any(k.startswith("Global differences") and len(v) == 2 for k, v in sh.items())
            and any(k.startswith("Questions on no single paper result: 2 items") for k in sh) and len(sh) == 4)
        # trial #7 audit: a question on a declaration with no paper result, and the delegated lines answering it
        # each round, are one section; another such question stays in the kind group
        _rl = base_log + "".join("- " + TG.format("none") + f"keep reading 1 HAQZ{i_} (QUESTION row on Paper.helper_a, "
                                 f"round {R})\n" for i_ in (1, 2))
        _, _, s7 = gen(hcfg, _rl)
        ha_ = next((v for k, v in s7.items() if k.startswith("Declaration `Paper.helper_a` (3 items")), [])
        say("trial #7: a QUESTION on a declaration no index row names and the delegated lines answering it are ONE "
            "section; the other such question stays with the questions on no paper result",
            "question:Paper.helper_a" in ha_ and sum(a.startswith("delegated:") for a in ha_) == 2
            and any(k.startswith("QUESTION: Paper.helper_b") or k.startswith("Questions on no single") for k in s7)
            and not any("helper_a" in a for k, v in s7.items() if not k.startswith("Declaration") for a in v))
        ti, ai, si = gen(cfg, base_log.replace("[DELEGATED", "[NOTED"))
        say("B11: under involved each question on no paper result stays its own section (the human answers each)",
            sum(k.startswith("QUESTION: Paper.helper_") for k in si) == 2)
        gl = (th.split(GLANCE_HEADING, 1) + [""])[1].split("## Background", 1)[0]
        say("B11: the at-a-glance table has one row per section, not per item",
            sum(l_.startswith("| ") and FILL in l_ for l_ in gl.splitlines()) == len(sh) == n_sections(th) < len(ah))
        # the operator decides and logs (stage 5 step 4): the items keep their sections
        ans = "".join(f"- answered {a} (2026-02-03, {R}): " + TG.format("none") + f"DECIDEDQZ {k_}\n" for k_, a in enumerate(ah))
        th2, ah2, sh2 = gen(hcfg, base_log + "## Answered\n" + ans)
        dec2, names2 = dict(skeleton.decided), dict(skeleton.names)
        dec = th2.split("## Decisions", 1)[1].split("## How to reverse", 1)[0]
        say("B11: under hands-off an item decided and logged under `## Answered` keeps its section, its Decision taken "
            "filled from the log (no hand-written appendix of 'previously answered' decisions)",
            sorted(ah2) == sorted(ah) and sh2 == sh and "## Previously answered" not in th2
            and all(f"DECIDEDQZ {k_} (logged;" in dec for k_ in range(len(ah))))
        _, ah3, _ = gen(dict(hcfg, involvement="statements-only"), base_log + "## Answered\n" + ans)
        say("B11: only an answer tagged with the run's own level is a decision kept in its section (a hands-off tag "
            "under statements-only is listed as answered)", "check:Lemma_2.2" not in ah3 and "global:G1" not in " ".join(ah3))
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(base_log)
        bym = dict((m_, ts) for m_, ts in delegated_by_matter(hcfg, base_log) if m_)
        # the grouping used where no DECISIONS.md section holds a line (trial #10 audit) agrees too
        _ds, g["_delegated_sections"] = g["_delegated_sections"], lambda c_, l_: (lambda p_, t_: None)
        try:
            bym_fb = dict((m_, ts) for m_, ts in delegated_by_matter(hcfg, base_log) if m_)
        finally:
            g["_delegated_sections"] = _ds
        say("B11: the report's matters agree: the delegated line answering 'QUESTION row on Lemma 2.2' and the one "
            "logged under check:Lemma_2.2 are one matter", all(any("QROWQZ" in t for t in b_.get("Lemma 2.2", []))
                                                             and any("PREQZ" in t for t in b_.get("Lemma 2.2", []))
                                                             for b_ in (bym, bym_fb)))
        # trial #10 audit: a delegated line logged under the defect's anchor was a matter of its own in the report
        # (23 decisions on 10 matters there, 7 sections in DECISIONS.md)
        _da = next((a_ for a_ in l33 if a_.startswith("defect:")), "defect:x").split("@")[0]
        _dlog = base_log + f"- {_da}: " + TG.format("none") + "DEFQZ record the defect\n"
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(_dlog)
        _bym_d = delegated_by_matter(hcfg, _dlog)
        _th_d = skeleton(hcfg, [r1], r1)[0]
        _secs_d = {k_ for k_, _ in _bym_d if k_} | {None for k_, _ in _bym_d if not k_}
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(base_log)
        say("trial #10 audit: the report groups the delegated lines by DECISIONS.md's sections: the line logged under "
            "the defect's anchor is in Lemma 2.2's matter, and no more matters than sections",
            any("DEFQZ" in t for k_, ts in _bym_d if k_ == "Lemma 2.2" for t in ts)
            and sum(1 if k_ else len(ts) for k_, ts in _bym_d) <= n_sections(_th_d) and None not in _secs_d)
        fill2 = re.sub(re.escape(FILL) + r".*?>>", "kept, as the conservative rule says (reversal: see below)", th2, flags=re.S)
        fill2 = fill2.replace("| kept, as the conservative rule says (reversal: see below) | kept, as the conservative rule says "
                              "(reversal: see below) | kept, as the conservative rule says (reversal: see below) |",
                              "| kept | conservative rule; adjudicator's recommendation | re-approve; none |")
        hc = lambda d: check(d, ah2, R, [f"> - {b_}" for b_ in box_lines(hcfg)], names2, "hands-off", "(c) hands-off",
                             decided=dec2)
        p2 = hc(fill2)
        say("B11: the honest path -- the regenerated document, filled, passes the check (a matter's glance row "
            "listing several sources and costs)", p2 == [] or print(p2))
        say("B11 review: every decided item's logged line is known to the check (skeleton.decided)",
            set(dec2) == set(ah2) and all(f"DECIDEDQZ {k_}" in dec2.get(a, "") for k_, a in enumerate(ah)))
        # M2: a prefilled decision line edited in the document ("dropped …; reversal: none")
        k33 = ah.index("check:Lemma_2.2") if "check:Lemma_2.2" in ah else -1
        m2 = fill2.replace(f"DECIDEDQZ {k33} (logged;", f"dropped it instead (logged;", 1)
        say("B11 review (M2): a prefilled Decision taken line edited in the document fails (the logged line must "
            "stand word for word)", m2 != fill2 and any("word for word" in p_ and "check:Lemma_2.2" in p_ for p_ in hc(m2)))
        kg = next((k_ for k_, a in enumerate(ah) if a.startswith("approval:")), -1)
        m2s = fill2.replace(f"DECIDEDQZ {kg} (logged;", f"DECIDEDQZ X{kg} (logged;", 1)
        say("B11 review (M2): ... also on the approval's line",
            m2s != fill2 and any("word for word" in p_ for p_ in hc(m2s)))
        # M3: one tagged line naming all the section's anchors (the per-item lines folded into one)
        sec33 = next((b_ for h_, b_ in sections_of(fill2) if h_.startswith("### Lemma 2.2")), "")
        dt_ = (sec33.split("**Decision taken:**", 1) + ["\n- x"])[1]
        ids_ = [a.split("@")[0] for a in ANCHOR_RE.findall(sec33)]
        one = f"\n- {', '.join(ids_)}: " + TG.format("none") + "kept all of them; to reverse it, see below\n"
        m3 = fill2.replace(dt_, one, 1)
        say("B11 review (M3): one tagged line naming every item of a section fails",
            any("names" in p_ and "items" in p_ for p_ in hc(m3)) and any("exactly one line" in p_ for p_ in hc(m3)))
        ln = [l_ for l_ in dt_.splitlines() if l_.startswith("- ")] or ["- x"]
        m3b = fill2.replace(dt_, dt_.replace(ln[0], ln[0] + " " + TG.format("none") + "and also kept the rest", 1), 1)
        say("B11 review (M3): a second tagged decision on one item's line fails (one tagged line per item)",
            any("tags for" in p_ for p_ in hc(m3b)))
        say("B11: a glance row with an unknown cost among several fails",
            any("'Reversal cost'" in p_ for p_ in hc(fill2.replace("| re-approve; none |", "| re-approve; maybe |", 1))))
        # involved: the human's answers are listed once per matter, each line without its "answered <anchor>" head
        hum = (f"- answered check:Lemma_2.2 (2026-02-03, {R}): keep CHKANSQZ\n"
               f"- answered question:Lemma_2.2 (2026-02-03, {R}): no defer QANSQZ\n")
        ti2, ai2, _ = gen(cfg, base_log.replace("[DELEGATED", "[NOTED") + "## Answered\n" + hum)
        prev_ = ti2.split("## Previously answered", 1)[1] if "## Previously answered" in ti2 else ""
        say("B11: answered items are listed once per matter, nested, without repeating 'answered <anchor>'",
            "- **Lemma 2.2 (2 items" in prev_ and f"  - CHECK row: Lemma 2.2: keep CHKANSQZ (2026-02-03, round {R}) <sub>`check:Lemma_2.2`</sub>" in prev_
            and "answered check:" not in prev_ and "check:Lemma_2.2" not in ai2 and "question:Lemma_2.2" not in ai2)
        # B11 review: a standing rule is one matter (a test run: the standing-defer decision stood under Lemma 2.2 and
        # again under its proposed rule); the question and delegated line naming it move there, Lemma 2.2 points there
        ad_ = open(os.path.join(r1, "ADOPTED.md")).read()
        open(os.path.join(r1, "ADOPTED.md"), "w").write(
            ad_.replace("add the standing defer? |", "add the standing defer QROWQZ? |")
            + "| pf | Lemma 2.5 | Fail | **DEFER** (standing: QROWQZ) | recorded |\n")
        try:
            tr, ar, sr_ = gen(hcfg, base_log)
            open(os.path.join(rd, "RUN_LOG.md"), "w").write(base_log)
            bym_r = dict((m_, ts) for m_, ts in delegated_by_matter(hcfg, base_log) if m_)
            _ds, g["_delegated_sections"] = g["_delegated_sections"], lambda c_, l_: (lambda p_, t_: None)
            try:
                bym_rfb = dict((m_, ts) for m_, ts in delegated_by_matter(hcfg, base_log) if m_)
            finally:
                g["_delegated_sections"] = _ds
        finally:
            open(os.path.join(r1, "ADOPTED.md"), "w").write(ad_)
        rule_s = next((v for k, v in sr_.items() if k.startswith("Standing rule `QROWQZ` (")), [])
        l33r = next((b_ for h_, b_ in sections_of(tr) if h_.startswith("### Lemma 2.2 (")), "")
        say("B11 review: the QUESTION and the delegated line naming a standing rule, and the rule itself, are one "
            "section; the rule's decision appears in that one place",
            "question:Lemma_2.2" in rule_s and any(a.startswith("proposed-defer:") for a in rule_s)
            and sum(a.startswith("delegated:") for a in rule_s) == 1 and "QROWQZ" not in l33r.replace(
                "Standing rule `QROWQZ`", ""))
        say("B11 review: ... and the paper result's section points to it (see also)",
            "*See also* the section \u201cStanding rule `QROWQZ`\u201d: it decides QUESTION: Lemma 2.2 and Decision logged "
            "during the run." in l33r)
        say("B11 review: the report's matters agree (the delegated line naming the rule is the rule's matter)",
            all(any("QROWQZ" in t for t in b_.get("Standing rule `QROWQZ`", []))
                and not any("QROWQZ" in t for t in b_.get("Lemma 2.2", [])) for b_ in (bym_r, bym_rfb)))
    finally:
        project.REPO, g["changes_after"] = saved


def _question_level_controls(tmp, say):
    """B2 (U2 §0, decision 5): under statements-only a QUESTION row on a statement of the open re-approval
    question is the human's, in a round after the approval too; another post-approval row stays delegated."""
    rd = os.path.join(tmp, "qlvl")
    for r_, kind in (("2026-01-01-aaaaaaa", "statements"), ("2026-01-02-bbbbbbb", "diff")):
        os.makedirs(os.path.join(rd, r_))
        json.dump({"_meta": {"kind": kind}}, open(os.path.join(rd, r_, "TARGET.json"), "w"))
    json.dump({"round": "2026-01-01-aaaaaaa", "by": "human"}, open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
    rounds = [os.path.join(rd, r_) for r_ in sorted(os.listdir(rd)) if r_.startswith("2026")]
    keep_r, keep_q = project.REPO, globals()["reapproval_question"]
    project.REPO = tmp
    try:
        cfg = {"rounds_dir": "qlvl", "involvement": "statements-only"}
        globals()["reapproval_question"] = lambda c_: {"decls": ["N.lem"]}
        h = needs_human(cfg, rounds)
        late = "2026-01-02-bbbbbbb"
        say("B2: statements-only, re-approval question open: a QUESTION row on its statement after the approval is "
            "the human's (full or short name); another one is delegated",
            h(late, "N.lem") and h(late, "`lem`") and not h(late, "N.other") and not h(late))
        globals()["reapproval_question"] = lambda c_: None
        say("B2: with no question open the post-approval row on it is delegated as before",
            not needs_human(cfg, rounds)(late, "N.lem"))
    finally:
        project.REPO, globals()["reapproval_question"] = keep_r, keep_q


def _checkpoint_c_controls(tmp, say):
    """B12 (U2 §6.7): under `involved` Checkpoint C is a QUESTION asked before delivery: --deliver waits
    (question_refusal) until every item the decisions document asks has the human's answer; a [PROXY] or
    [DELEGATED] answer is the operator's and answers nothing; an item asked again after its answer is open
    again; the delegating levels never wait on C."""
    rd = os.path.join(tmp, "ckc")
    r1, r2 = os.path.join(rd, "2026-01-01-aaaaaaa"), os.path.join(rd, "2026-01-02-bbbbbbb")
    for d in (r1, r2):
        os.makedirs(d); json.dump({"_meta": {"kind": "diff"}}, open(os.path.join(d, "TARGET.json"), "w"))
    head = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
    open(os.path.join(r1, "ADOPTED.md"), "w").write(head + "| subst | Paper.q1 | Fail | **QUESTION** | keep h? |\n")
    open(os.path.join(r2, "ADOPTED.md"), "w").write(head + "| subst | Paper.q2 | Fail | **QUESTION** | reading? |\n")
    logp = os.path.join(rd, "RUN_LOG.md")
    a1, a2 = anchor_id("question", "Paper.q1"), anchor_id("question", "Paper.q2")
    g = globals()
    keep = (project.REPO, g["changes_after"], g["reapproval_question"])
    project.REPO = tmp
    g["changes_after"] = lambda c, r: []
    g["reapproval_question"] = lambda c_: None
    try:
        cfg = {"name": "C", "rounds_dir": "ckc", "lean_files": [], "involvement": "involved"}

        def with_log(answers):
            open(logp, "w").write("# Run log\n## Open questions\n## Answered\n" + answers)
            return checkpoint_c_open(cfg), question_refusal(cfg)
        o, q = with_log("")
        ap = [x for x in o if x.startswith("approval:")]
        say("B12: involved, nothing answered: Checkpoint C is open on every item (the approval and both QUESTION "
            "rows) and --deliver waits (PENDING, never a stop)",
            len(ap) == 1 and set(o) == {a1, a2, ap[0]} and q and "Checkpoint C is open" in q and "Not a stop" in q)
        apl = f"- answered {ap[0]} (2026-01-03, 2026-01-02-bbbbbbb): approved, as at B\n" if ap else ""
        o, q = with_log(apl + f"- answered {a1} (2026-01-03, 2026-01-02-bbbbbbb): keep it\n")
        say("B12: items answered by the human: only the unanswered one keeps C open", o == [a2] and q)
        o, q = with_log(apl + f"- answered {a1} (2026-01-03, 2026-01-02-bbbbbbb): keep it\n"
                        f"- answered {a2} (2026-01-03, 2026-01-02-bbbbbbb): the weaker reading\n")
        say("B12: every item answered by the human: C is closed, --deliver does not wait on it", o == [] and q is None)
        o, q = with_log(apl + f"- answered {a1} (2026-01-03, 2026-01-02-bbbbbbb): [PROXY 2026-01-03, operator for the "
                        f"approver] keep it\n- answered {a2} (2026-01-03, 2026-01-02-bbbbbbb): the weaker reading\n")
        say("B12: a [PROXY] answer is the operator's: that item keeps C open", a1 in o and a2 not in o and q)
        pl = "- [PROXY 2026-01-03, operator for the approver] keep h (QUESTION row on Paper.q1, round 2026-01-01-aaaaaaa)"
        open(logp, "w").write(f"# Run log\n## Open questions\n{pl}\n## Answered\n" + apl
                              + f"- answered {a2} (2026-01-03, 2026-01-02-bbbbbbb): weaker\n")
        o = checkpoint_c_open(cfg)
        px = [x for x in o if x.startswith("proxy:")]
        # the proxy decision stays in Open questions; the human confirms it by quoting it
        open(logp, "w").write(f"# Run log\n## Open questions\n{pl}\n## Answered\n" + apl
                              + f"- answered {a2} (2026-01-03, 2026-01-02-bbbbbbb): weaker\n" + "".join(
            f"- answered {x} (2026-01-04, 2026-01-02-bbbbbbb): confirmed\n" for x in px)
            + f"- answered {a1} (2026-01-04, 2026-01-02-bbbbbbb): yes, keep h as the proxy decision did\n")
        o3, q3 = checkpoint_c_open(cfg), question_refusal(cfg)
        say("B12: a [PROXY] decision is the human's item until confirmed; the human confirming it in their words "
            "closes C (no false alarm)", len(px) == 1 and a1 in o and o3 == [] and q3 is None)
        # review fix 1: an answer with no content answers nothing; review fix 2: a tag anywhere in the answer,
        # quoted or not, is the operator's line (quote-stripping hid a quoted [DELEGATED])
        dl = "[DELEGATED 2026-01-03, operator under hands-off for the approver] keep"
        for what, ans in (("an empty answer", ""), ("an answer of punctuation only", ' "" -'),
                          ("a quoted [DELEGATED] answer", f' "{dl}"'),
                          ("a human-looking answer quoting [DELEGATED]", f' yes, "{dl}"'),
                          ("a quoted [PROXY] answer", ' "[PROXY 2026-01-03, operator for the approver] keep"'),
                          ("a lower-case [ delegated ] tag", " keep [ delegated by the operator ]"),
                          ("a quoted [PROXY] confirming the logged decision", f' yes, "{pl[2:]}"')):
            o4, q4 = with_log(apl + f"- answered {a1} (2026-01-03, 2026-01-02-bbbbbbb):{ans}\n"
                              f"- answered {a2} (2026-01-03, 2026-01-02-bbbbbbb): weaker\n")
            say(f"B12 review: {what} is not the human's answer: that item keeps C open and --deliver waits",
                a1 in o4 and a2 not in o4 and bool(q4) and "the human's own words" in q4)
        o, q = with_log(apl + f"- answered {a1} (2026-01-03, 2026-01-01-aaaaaaa): keep it\n"
                        f"- answered {a2} (2026-01-03, 2026-01-02-bbbbbbb): weaker\n")
        r3 = os.path.join(rd, "2026-01-04-ccccccc"); os.makedirs(r3)
        json.dump({"_meta": {"kind": "diff"}}, open(os.path.join(r3, "TARGET.json"), "w"))
        open(os.path.join(r3, "ADOPTED.md"), "w").write(head + "| subst | Paper.q1 | Fail | **QUESTION** | again |\n")
        # the rounds' order (project.order_rounds) falls back to their directories' times here (no git): pin them,
        # oldest first, so a loaded machine's clock never decides which round asked last (tier 1 flake, release x
        # statements-only); and the level is this test's own (involved), whatever FORMALIZE_TEST_INVOLVEMENT says
        for k_, d_ in enumerate((r1, r2, r3)):
            os.utime(d_, (1_700_000_000 + 3600 * k_, 1_700_000_000 + 3600 * k_))
        cfg["involvement"] = "involved"
        o2 = checkpoint_c_open(cfg)
        say("B12: an item asked again by a later round (step 7's diff round) re-opens C on that item only", o2 == [a1])
        for lvl in ("statements-only", "hands-off"):
            cfg["involvement"] = lvl
            open(logp, "w").write("# Run log\n## Answered\n")
            say(f"B12: under {lvl} Checkpoint C is delegated: --deliver never waits on it",
                checkpoint_c_open(cfg) == [] and question_refusal(cfg) is None)
        cfg["involvement"] = "involved"
        g["skeleton"], keep_sk = (lambda *a: (_ for _ in ()).throw(ValueError("unreadable record"))), g["skeleton"]
        try:
            q = checkpoint_c_refusal(cfg)
        finally:
            g["skeleton"] = keep_sk
        say("B12: a record the skeleton cannot read keeps the delivery waiting, with the reason (fail closed)",
            bool(q) and "unreadable record" in q)
    finally:
        project.REPO, g["changes_after"], g["reapproval_question"] = keep


def _checkpoint_b_decided_controls(tmp, say):
    """Trial #8 (involved): Checkpoint C does not ask again what the human decided at Checkpoint B -- the approval,
    the approved sheet's CHECK rows, and the defect and vacuity rows the record held at the approval on a CHECK
    result -- while their substance is unchanged; it lists them once, with the B answer; a changed substance asks
    again, saying so. An approval by the agent, and the delegating levels, are unchanged."""
    import subprocess as _sp
    rd = os.path.join(tmp, "ckb")
    R = "2026-01-02-full-bbbbbbb"
    rr = os.path.join(rd, R)
    os.makedirs(rr)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    G = lambda *a: _sp.run(["git", "-C", rd, *a], capture_output=True, text=True, env=env)
    json.dump({"_meta": {"kind": "full"}}, open(os.path.join(rr, "TARGET.json"), "w"))
    json.dump({"rows": [{"result": "Lemma 2.2", "flag": "CHECK", "check_reason": "repaired"},
                        {"result": "Lemma 2.5", "flag": "OK"}]}, open(os.path.join(rr, "SIGNOFF.json"), "w"))
    pdp = os.path.join(rd, "PAPER_DEFECTS.md")
    hdr = ("## Defects\n| # | where | status | repair | what the paper says | why it is wrong | lean witness | consequence |\n"
           "|---|---|---|---|---|---|---|---|\n")
    row1 = "| 1 | Lemma 2.2, tex 40 | false | add hypothesis | r divides Q | r = 3 | `w` | 2.6 survives |\n"
    row2 = "| 2 | Lemma 2.5, tex 52 | misprint (true as intended) | typo | q + 3 blocks | q + 2 | `v` | none |\n"
    open(pdp, "w").write(hdr + row1 + row2)
    appr = {"round": R, "by": "human", "how": "blanket", "date": "2026-01-02", "commit": "bbbbbbb", "rows": {},
            "fingerprints": {}}
    ap = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
    json.dump(appr, open(ap, "w"))
    logp = os.path.join(rd, "RUN_LOG.md")
    log = ('# Run log\n## Checkpoint B\n- human answer (2026-01-02): "(a) I approve all of it BANSWERQZ"\n'
           "## Answered\n")
    open(logp, "w").write(log)
    G("init", "-q"); G("add", "-A"); G("commit", "-qm", f"approve {R}")
    # after the approval: a reader-fix rewords defect 1's reason (a glossary sentence), committed
    open(pdp, "w").write(hdr + row1.replace("| r = 3 |", "| r = 3. Terms used in this row: F10 is a check. |") + row2)
    G("add", "-A"); G("commit", "-qm", "reader-fix")
    g = globals()
    keep = (project.REPO, g["changes_after"], g["reapproval_question"])
    project.REPO = tmp
    g["changes_after"] = lambda c, r: []
    g["reapproval_question"] = lambda c_: None
    try:
        cfg = {"name": "B", "rounds_dir": "ckb", "lean_files": [], "involvement": "involved"}
        rounds = [rr]
        t, a = skeleton(cfg, rounds, rr)
        bsec = t.split("## Already decided by you at Checkpoint B", 1)[-1].split("## Decisions", 1)[0]
        d1 = [x for x in skeleton.decided_at_b if x.startswith("defect:1-")]
        say("trial #8: under involved, C does not ask the approval, the approved sheet's CHECK row or the defect on it "
            "that the human decided at B (a reworded reason since changes nothing) ...",
            not any(x.startswith(("approval:", "check:Lemma_2.2", "defect:1-")) for x in a) and d1
            and {x.split(":")[0] for x in skeleton.decided_at_b} == {"approval", "check", "defect"})
        say("... it lists them once, under 'Already decided by you at Checkpoint B (<date>)', with the B answer verbatim",
            "## Already decided by you at Checkpoint B (2026-01-02)" in t and "BANSWERQZ" in bsec
            and "`check:Lemma_2.2`" in bsec and "`defect:1-" in bsec and "### " not in bsec)
        say("... a defect on a result the sheet did not mark CHECK (the human was not shown it) is still asked",
            any(x.startswith("defect:2-") for x in a))
        open(logp, "w").write(log)
        say("... and checkpoint_c_open (what delivery waits for) does not wait on the B decisions",
            not any(x.startswith(("approval:", "check:", "defect:1-")) for x in checkpoint_c_open(cfg)))
        cur = open(pdp).read()
        open(pdp, "w").write(cur.replace("| add hypothesis |", "| substantial |"))
        t2, a2 = skeleton(cfg, rounds, rr)
        open(pdp, "w").write(cur)
        say("trial #8: a B-decided defect whose substance (its repair) changed since is asked again, saying it was decided "
            "at B", any(x.startswith("defect:1-") for x in a2) and "You decided this matter at Checkpoint B (2026-01-02)" in t2
            and "check:Lemma_2.2" not in a2)
        open(logp, "w").write(log + f"- answered check:Lemma_2.2 (2026-01-05, {R}): \"keep it CANSWERQZ\"\n"
                              + log.split("## Answered", 1)[0].replace("# Run log\n", "").replace("## Checkpoint B", "## Checkpoint C (2026-01-05)")
                              .replace("(2026-01-02)", "(2026-01-05)").replace("(a) I approve all of it BANSWERQZ", "keep it CANSWERQZ"))
        t3, a3 = skeleton(cfg, rounds, rr)
        bsec3 = t3.split("## Already decided by you at Checkpoint B", 1)[-1].split("## Decisions", 1)[0]
        prev3 = t3.split("## Previously answered", 1)[-1] if "## Previously answered" in t3 else ""
        say("trial #8: an answer logged at C to a B-decided item (an older apparatus asked it) stays with C: listed "
            "'Answered again at Checkpoint C (<date>)', never as the B answer",
            "Answered again at Checkpoint C (2026-01-05)" in bsec3 and "CANSWERQZ" in bsec3 and "CANSWERQZ" not in prev3
            and "check:Lemma_2.2" not in a3)
        open(logp, "w").write(log)
        json.dump(dict(appr, by="agent"), open(ap, "w"))
        t4, a4 = skeleton(cfg, rounds, rr)
        apa = next((x for x in a4 if x.startswith("approval:")), "approval:none")
        os.makedirs(os.path.join(rd, "stops", "S1"), exist_ok=True)
        open(logp, "w").write(log.replace("## Answered\n", "") + '## Checkpoint C (2026-01-05)\n- human answer (2026-01-05): '
                              '"All as recommended CANSWERQZ"\n## Answered\n'
                              f'- answered {apa} (2026-01-05, {R}): "All as recommended CANSWERQZ"\n'
                              f'- answered stop:S1 (2026-01-03, {R}): "re-baseline SANSWERQZ"\n')
        t6, _ = skeleton(cfg, rounds, rr)
        prev6 = t6.split("## Previously answered", 1)[-1]
        json.dump(appr, open(ap, "w")); open(logp, "w").write(log)
        say("trial #8: a previously answered item names the checkpoint its answer was given at (the C answer is never "
            "shown as if it were the approval's B answer)",
            re.search(r"Statement approval[^\n]*CANSWERQZ[^\n]*\(at Checkpoint C, 2026-01-05\)", prev6) is not None)
        say("trial #8: a stop's answer is listed as the stop's, not as a stray anchor",
            re.search(r"^- Stop S1: [^\n]*SANSWERQZ", prev6, re.M) is not None and "matches no current item" not in prev6)
        fx_ = next((x for x in a4 if "@" in x), None)
        if fx_:
            open(logp, "w").write(log + f'- answered {fx_.rsplit("@", 1)[0]} (2026-01-05, {R}): "keep it FAMQZ"\n')
            t7, _ = skeleton(cfg, rounds, rr)
            open(logp, "w").write(log)
        say("C2 audit: an answer keyed by an item's family without its @hash is not listed as matching no current item",
            fx_ is not None and "FAMQZ" not in "".join(l_ for l_ in t7.splitlines() if "matches no current item" in l_))
        say("trial #8: an approval by the agent ((c), or a [PROXY]) decided nothing for the human: C asks every item",
            any(x.startswith("approval:") for x in a4) and "check:Lemma_2.2" in a4
            and any(x.startswith("defect:1-") for x in a4) and "Already decided by you" not in t4)
        for lvl in ("statements-only", "hands-off"):
            cfg["involvement"] = lvl
            t5, a5 = skeleton(cfg, rounds, rr)
            say(f"trial #8: under {lvl} nothing moves to a Checkpoint B list (its items keep their sections)",
                "Already decided by you" not in t5 and any(x.startswith("approval:") for x in a5)
                and "check:Lemma_2.2" in a5 and any(x.startswith("defect:1-") for x in a5))
        cfg["involvement"] = "involved"
    finally:
        project.REPO, g["changes_after"], g["reapproval_question"] = keep


def _matter_controls(say):
    """mini2 audit: one matter recorded under several anchors is one decision section; no truncated
    labels; no mangled anchors."""
    F = "FIELDS\n"
    idx = {"Paper.lemma_2_4": "Lemma 2.4", "Paper.lemma_2_1_c": "Lemma 2.1",
           "Paper.lemma_2_1_c_hyp_unsat": "Lemma 2.1"}
    items = [("approval:R1@aa", "Statement approval (Checkpoint B)", "b0\n\n" + F, None),
             ("delegated:x-1", "Decision delegated at intake: [DELEGATED …] approved the sheet of round R1",
              "Run log: approved the sheet of round R1\n\n" + F, "[DELEGATED"),
             ("check:Lemma_2.4", "CHECK row: Lemma 2.4", "b1\n\n" + F, "Lemma 2.4"),
             ("question:Paper.lemma_2_4", "QUESTION: Paper.lemma_2_4", "b2\n\n" + F, "lemma_2_4"),
             ("unused:Paper.lemma_2_4@11", "Unused hypothesis: `Paper.lemma_2_4`", "b3\n\n" + F, "x"),
             ("defect:1-Lemma_2.4_-0a@22", "Paper defect 1: Lemma 2.4 (tex l.50)", "b4\n\n" + F, "2.4", None,
              "Lemma 2.4 (tex l.50)"),
             ("check:Lemma_2.1", "CHECK row: Lemma 2.1", "c1\n\n" + F, "Lemma 2.1"),
             ("question:Paper.lemma_2_1_c", "QUESTION: Paper.lemma_2_1_c", "c2\n\n" + F, None),
             ("vacuous:1-Lemma_2.1_c_tex-0b@33", "True only vacuously: Lemma 2.1(c) (tex l.30)", "c3\n\n" + F, None, None,
              "`lemma_2_1_c` (Lemma 2.1(c), tex l.30)"),
             ("question:Paper.pair_ok", "QUESTION: pair_ok", "w1\n\n" + F, None, "same-q"),
             ("question:Paper.α_two", "QUESTION: α_two", "w2\n\n" + F, None, "same-q"),
             ("global:G1@44", "Global difference G1", "g\n\n" + F, None)]
    gs = group_items(items, idx, "R1", F)
    by = {re.split(r"[:(]", g[1])[0].strip(): g for g in gs}
    say("mini2-2: a CHECK row, a QUESTION, an unused hypothesis and a paper defect on Lemma 2.4 are ONE item "
        "listing all four anchors, with each record and the fields once",
        len(by.get("Lemma 2.4", ((),))[0]) == 4 and by["Lemma 2.4"][2].count(F) == 1
        and all(x in by["Lemma 2.4"][2] for x in ("b1", "b2", "b3", "b4")))
    say("mini2-2: the vacuous part, its QUESTION and the CHECK row of Lemma 2.1 are one item; the approval and "
        "the delegated line recording it are one item; one question on several declarations is one item; "
        "an unrelated item stands alone (12 items, 5 sections)",
        len(by.get("Lemma 2.1", ((),))[0]) == 3 and len(by.get("Statement approval", ((),))[0]) == 2
        and len(gs) == 5 and sum(len(g[0]) for g in gs) == 12)
    # review of fix-mini2 H2: a Lean name is never read as a label; distinct results stay apart
    h2 = [(versioned("vacuous", "1-`lemma_2_1_c` (Lemma 2.1(c)): if x > y ...", "v1"),
           "True only vacuously: `lemma_2_1_c` (Lemma 2.1(c))", "V1\n\n" + F, None, None,
           "`lemma_2_1_c` (Lemma 2.1(c)): if x > y"),
          (versioned("defect", "2-`lemma_2_4` (Lemma 2.4) missing hypothesis", "v2"),
           "Paper defect 2: `lemma_2_4` (Lemma 2.4)", "D2\n\n" + F, None, None, "`lemma_2_4` (Lemma 2.4)"),
          (versioned("vacuous", "3-`lemma_3_1` (Lemma 3.1) for n = 5", "v3"),
           "True only vacuously: `lemma_3_1` (Lemma 3.1)", "V3\n\n" + F, None, None, "`lemma_3_1` for n = 5"),
          (versioned("skip", "4-lemma_3_4", "v4"), "Not formalized: lemma_3_4", "S4\n\n" + F, None, None,
           "lemma_3_4 and `theorem_3`"),
          (versioned("defect", "5-Lemmas 3.5 and 3.6", "v5"), "Paper defect 5", "D5\n\n" + F, None, None,
           "Lemmas 3.5 and 3.6"),
          (versioned("defect", "6-Lemma 3.5", "v6"), "Paper defect 6", "D6\n\n" + F, None, None,
           "Lemma 3.5 (tex l.40)")]
    gh = group_items(h2, {"Paper.lemma_2_4": "Lemma 2.4"}, "R1", F)
    say("review of fix-mini2 H2: a vacuous row on Lemma 2.1(c), a defect on Lemma 2.4 and rows naming Lean "
        "names, a plural or two results are separate sections (a Lean name such as `lemma_2_1_c` is never "
        "read as 'Lemma 3'; when in doubt, no merge)",
        len(gh) == 6 and all(len(g[0]) == 1 for g in gh)
        and matter_of(h2[0][0], "", {}, label=h2[0][5]) == "Lemma 2.1"
        and matter_of(h2[2][0], "", {}, label=h2[2][5]) is None
        and matter_of(h2[0][0], h2[0][1] + "\nLemma 2.4", {}) is None
        and exact_label("Lemma 3.5, used in Theorem 1.1") is None and exact_label("Lemma 3a") is None
        and matter_of("check:lemma_2_1_c", "", {}) is None and matter_of("check:Lemma_2.1(c)", "", {}) == "Lemma 2.1")
    say("review of fix-mini2 L6: a declaration matches the index by its full name: a helper `Foo.lemma_2_4` "
        "does not join Lemma 2.4; an unqualified name matches one namespaced entry",
        matter_of("question:Foo.lemma_2_4", "", idx) is None
        and matter_of("question:Paper.lemma_2_4", "", idx) == "Lemma 2.4"
        and matter_of("unused:lemma_2_4@1", "", idx) == "Lemma 2.4"
        and decl_matter("x", {"A.x": "Lemma 1.1", "B.x": "Lemma 1.2"}) is None)
    g1 = group_items([("check:Lemma_9.9", "CHECK row: Lemma 9.9", "b9\n\n" + F, "Lemma 9.9")], {}, "R1", F,
                     see_also={"Lemma 9.9": "SEEQZ\n\n"})
    say("B11 review: a single item's section carries its see-also note before the fields",
        len(g1) == 1 and g1[0][2].endswith("SEEQZ\n\n" + F) and "b9" in g1[0][2])
    # review of fix-mini2 M1: a merged section keeps one decision line per item, each with its tag
    gm = group_items(items, idx, "R1", F + DECIDED_FIELD)
    l33 = next((g for g in gm if g[1].startswith("Lemma 2.4")), ((), "", ""))
    say("review of fix-mini2 M1: a merged section asks for one Decision taken line per item (its own tag "
        "and reversal cost), not one for all",
        len(l33[0]) > 1 and l33[2].count("**Decision taken:**") == 1 and MULTI_DECIDED_FIELD in l33[2]
        and all(f"{FILL} >> <sub>`{a.split('@')[0]}`</sub>" in l33[2] for a in l33[0]))
    a_ = anchor_id("question", "Paper.α_two")
    say("mini2-2: an anchor keeps a non-ASCII name (α_two, not __two-<hash>) and the item pattern reads it",
        a_ == "question:Paper.α_two" and ANCHOR_RE.search(f"<!-- item:{a_} -->").group(1) == a_)
    lab = short_label("Decision delegated at intake: [DELEGATED 2026-10-21, operator under hands-off (intake); "
                      "reversal: re-approve] approved the sheet of round 2026-10-21-full-e8c34bd008c (commit 2a0f9ffc594) "
                      "— hands-off chosen at intake", 90)
    say("mini2-2: an at-a-glance label drops the tag and is cut at a word with an ellipsis",
        "[DELEGATED" not in lab and "approved the sheet" in lab and lab.endswith(" …") and len(lab) <= 92)
    line5 = ("[DELEGATED 2026-10-21, operator under hands-off (intake); reversal: re-approve] approved the sheet of "
             "round 2026-10-21-full-e8c34bd008c (commit 2a0f9ffc594)")
    lab5 = short_label(delegated_title(line5), 90)
    words5 = set(("Decision delegated at intake: " + line5).split())
    say("mini5 audit: a delegated decision's at-a-glance label is never cut mid-word (it read 'approved the sheet of "
        "round 20')", "2026-10-21-full-e8c34bd008c" in lab5 and all(w in words5 for w in lab5.split() if w != "…")
        and all(w in words5 for w in project.clip("x " * 3 + "lemma_2_4_witness_long_name is unproved", 20).split()
                if w != "…" and w != "x"))


def _open_question_strict(tmp, say):
    """The review of fix-mini1 (H1): an operator line closes a QUESTION row only in the strict form,
    and never one that needs the human. One scenario per attack of the review (attack_oq.py)."""
    hdr = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
    tag = "[DELEGATED 2026-04-02, operator under {lvl} (intake); reversal: none]"
    R1, R2 = "2026-04-01-aaa1111aaa1", "2026-04-03-full-bbb2222bbb2"

    def still(name, rounds, log, lvl="hands-off", kinds=None, appr=None):
        base = os.path.join(tmp, "oqs", name.split(":")[0].replace(" ", "_"))
        rr = os.path.join(base, "R")
        for rn, rows in rounds.items():
            os.makedirs(os.path.join(rr, rn))
            open(os.path.join(rr, rn, "ADOPTED.md"), "w").write(
                hdr + "".join(f"| {l} | {i} | Ambiguous | **QUESTION** | {w} |\n" for l, i, w in rows))
            if (kinds or {}).get(rn):
                json.dump({"_meta": {"kind": kinds[rn]}}, open(os.path.join(rr, rn, "TARGET.json"), "w"))
        if appr:
            json.dump({"round": appr, "rows": {}}, open(os.path.join(rr, "APPROVED_FINGERPRINTS.json"), "w"))
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log.replace("{lvl}", lvl))
        saved = project.REPO
        project.REPO = base
        try:
            oq = open_question_rows({"rounds_dir": "R", "involvement": lvl}, [os.path.join(rr, r) for r in rounds])
        finally:
            project.REPO = saved
        return {(r, i): n for r, _, i, _, n in oq}

    one = {R1: [("paper-faithfulness", "Theorem 4.1", "goal result: n or n+1?")]}
    ok_line = "## Open questions\n" + tag + f" keep it (QUESTION row on Theorem 4.1, round {R1}) — r\n"
    say("strict open questions: the stage2 form under the level's canonical tag closes the asking (control)",
        still("ctl", one, ok_line) == {})
    for lvl in ("hands-off", "statements-only", "involved"):
        say(f"strict open questions ({lvl}): an unrelated line naming the round and 'no question' closes nothing",
            (R1, "Theorem 4.1") in still(f"A {lvl}", one, "## Open questions\n- " + tag + f" keep K.lemma_2 as "
                                         f"stated (round {R1}); no question about K.lemma_2 arises — r\n", lvl))
    say("strict open questions: a line in the stage2 form under ## Rounds closes nothing",
        (R1, "Theorem 4.1") in still("B", one, "## Rounds\n" + tag + f" keep (QUESTION row on Theorem 4.1, "
                                     f"round {R1}) — r\n## Open questions\n"))
    two = {R1: [("non-vacuity", "K.lemma_3_2_c", "keep hn?"), ("non-vacuity", "K.lemma_3_2_cx", "other?")]}
    o = still("C", two, "## Open questions\n- " + tag + f" declare K.lemma_3_2_cx (QUESTION row on K.lemma_3_2_cx, "
              f"round {R1}) — r\n")
    say("strict open questions: a line on K.lemma_3_2_cx does not close K.lemma_3_2_c (item exact)",
        (R1, "K.lemma_3_2_c") in o and (R1, "K.lemma_3_2_cx") not in o)
    two2 = {R1: [("paper-faithfulness", "Lemma 3", "which?"), ("paper-faithfulness", "Lemma 3.1", "x?")]}
    say("strict open questions: a line on 'Lemma 3.1' does not close 'Lemma 3'",
        (R1, "Lemma 3") in still("C2", two2, "## Open questions\n- " + tag + f" keep (QUESTION row on Lemma 3.1, "
                                 f"round {R1}) — r\n"))
    say("strict open questions: a line naming round R1 + '0' does not close round R1 (round token exact)",
        (R1, "Theorem 4.1") in still("D", one, "## Open questions\n- " + tag + f" keep it (QUESTION row, round {R1}0) — r\n"))
    say("strict open questions: a line naming round R1 + 'x' (a name, not that round) does not close round R1",
        (R1, "Theorem 4.1") in still("D2", one, "## Open questions\n- " + tag + f" keep it (QUESTION row, round {R1}x) — r\n"))
    er = {R1: [("paper-faithfulness", "Theorem 4.1", "n or n+1?")], R2: [("paper-faithfulness", "Lemma 2", "keep h?")]}
    o = still("E", er, "## Open questions\n- " + tag.replace("04-02", "04-03") + f" keep Lemma 2 (QUESTION row on "
              f"Lemma 2, round {R2}); unlike round {R1} nothing needs the human — r\n")
    say("strict open questions: a line answering R2's question does not close R1's, which it names in passing",
        (R1, "Theorem 4.1") in o and (R2, "Lemma 2") not in o)
    say("strict open questions: a non-canonical [DELEGATED <date>] tag closes nothing",
        (R1, "Theorem 4.1") in still("F", one, "## Open questions\n- [DELEGATED 2026-04-02] the QUESTION row on "
                                     f"Theorem 4.1, round {R1} is moot\n"))
    for lvl in ("hands-off", "statements-only"):
        say(f"strict open questions ({lvl}): a line saying the question is left open for the human closes nothing",
            (R1, "Theorem 4.1") in still(f"G {lvl}", one, "## Open questions\n- " + tag + f" the QUESTION row on "
                                         f"Theorem 4.1 (round {R1}) is a goal result: left open for the human — r\n", lvl))
    say("strict open questions: a line dated before the round closes nothing",
        (R1, "Theorem 4.1") in still("H", one, "## Open questions\n" + tag.replace("04-02", "03-31")
                                     + f" keep (QUESTION row, round {R1}) — r\n"))
    say("strict open questions: a line under ## Checkpoint C naming the round's question closes nothing",
        (R1, "Theorem 4.1") in still("I", one, "## Checkpoint C (delegated)\n- check:Lemma_2: " + tag
                                     + f" keep; see the QUESTION row on Theorem 4.1, round {R1} — r\n## Open questions\n"))
    say("strict open questions: a tag naming another level than the configured one closes nothing",
        (R1, "Theorem 4.1") in still("lvl", one, ok_line.replace("{lvl}", "statements-only"), "hands-off"))
    # statements-only: a Checkpoint B question (a statement round's, or any round up to the approved one,
    # or any round before an approval exists) is the human's, by either path; a later one is delegated
    sb = {R1: one[R1], R2: [("paper-faithfulness", "Lemma 2", "keep h?")]}
    both = ("## Open questions\n" + tag + f" keep (QUESTION row on Theorem 4.1, round {R1}) — r\n"
            + tag.replace("04-02", "04-03") + f" keep (QUESTION row on Lemma 2, round {R2}) — r\n")
    o = still("SB1", sb, both, "statements-only", kinds={R1: "statements", R2: "diff"}, appr=R1)
    say("strict open questions (statements-only): an operator line never closes a Checkpoint B question "
        "(noted); one after the approval it closes", (R1, "Theorem 4.1") in o and (R2, "Lemma 2") not in o
        and "human's" in o[(R1, "Theorem 4.1")])
    o = still("SB2", sb, both, "statements-only", kinds={R1: "diff", R2: "diff"})
    say("strict open questions (statements-only): before any approval every question is the human's",
        (R1, "Theorem 4.1") in o and (R2, "Lemma 2") in o)
    anch = ("## Checkpoint C\n- question:Theorem_4.1: " + tag + " keep — r\n## Answered\n- answered "
            f"question:Lemma_2 (2026-04-03, {R2}): " + tag.replace("04-02", "04-03") + " keep — r\n")
    o = still("SB3", sb, anch, "statements-only", kinds={R1: "statements", R2: "statements"}, appr=R2)
    say("strict open questions (statements-only): an anchored or answered [DELEGATED] line never closes a "
        "Checkpoint B question either", (R1, "Theorem 4.1") in o and (R2, "Lemma 2") in o)
    say("strict open questions (hands-off): the same anchored and answered lines close both (control)",
        still("SB4", sb, anch, "hands-off", kinds={R1: "statements", R2: "statements"}, appr=R2) == {})
    o = still("INV", sb, both + anch.replace("## Checkpoint C", "## Checkpoint C2"), "involved")
    say("strict open questions (involved): no operator line closes any question",
        (R1, "Theorem 4.1") in o and (R2, "Lemma 2") in o)


def _open_question_controls(tmp, say):
    """open_question_rows directly (make_report's selftest checks one path of it through the
    report: an answered question stays out of REPORT.md)."""
    rr = os.path.join(tmp, "oq", "R")
    hdr = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
    rows = {
        "2025-12-30-def5678": [("non-vacuity", "old_open", "QUESTION", "OLDQ still unanswered?"),
                               ("correspondence", "old_done", "QUESTION", "OLDA answered by the human?"),
                               ("correspondence", "old_proxy", "QUESTION", "OLDP proxied only?"),
                               ("correspondence", "old_deleg", "QUESTION", "OLDD delegated?"),
                               ("correspondence", "re_q", "QUESTION", "REQ1 first asking"),
                               ("correspondence", "deleg_re", "QUESTION", "DRQ1 delegated, first asking")],
        "2025-12-31-fed8765": [("substantiveness", "re_q", "QUESTION", "REQ2 asked again after the answer?"),
                               ("substantiveness", "deleg_re", "QUESTION", "DRQ2 asked again after the delegation?"),
                               ("substantiveness", "mid_q", "ADOPT", "MIDADOPT not a question")],
        "2026-02-01-aaa1111": [("correspondence", "same_day", "QUESTION", "SDQ1 first asking")],
        "2026-02-01-full-bbb2222": [("correspondence", "same_day", "QUESTION", "SDQ2 asked again the same day")],
        "2026-03-01-ccc3333": [("correspondence", "x_then_y", "QUESTION", "XYQ1 day one")],
        "2026-03-02-ddd4444": [("correspondence", "x_then_y", "QUESTION", "XYQ2 day two")],
        "2026-04-01-eee5555": [("paper-faithfulness", "free_q", "QUESTION", "FRQ1 decided by an unanchored line")],
        "2026-04-01-full-fff6666": [("paper-faithfulness", "free_q", "QUESTION", "FRQ2 asked again, not decided"),
                                    ("non-vacuity", "two_b", "QUESTION", "TWOB named by the line"),
                                    ("non-vacuity", "two_c", "QUESTION", "TWOC not named by any line")],
    }
    for rn, rs in rows.items():
        os.makedirs(os.path.join(rr, rn))
        open(os.path.join(rr, rn, "ADOPTED.md"), "w").write(
            hdr + "".join(f"| {l} | {i} | Fail | **{d}** | {w} |\n" for l, i, d, w in rs))
    dl = lambda item, day: (f"- question:{item}: [DELEGATED {day}, operator under hands-off (intake); "
                            "reversal: none] keep \u2014 reason\n")
    open(os.path.join(rr, "RUN_LOG.md"), "w").write(
        "# Run log\n## Answered\n"
        "- answered question:old_done (2025-12-30, 2025-12-30-def5678): keep it\n"
        "- answered question:re_q (2025-12-30, 2025-12-30-def5678): keep it too\n"
        "- answered question:old_proxy (2025-12-30, 2025-12-30-def5678): [PROXY 2025-12-30] keep\n"
        + dl("old_deleg", "2025-12-30") + dl("deleg_re", "2025-12-30") + dl("same_day", "2026-02-01")
        + dl("x_then_y", "2026-03-02")
        + "## Open questions\n"
        "[DELEGATED 2026-04-02, operator under hands-off (intake); reversal: re-approve] keep K.free_q as "
        "stated (QUESTION row, round 2026-04-01-eee5555) \u2014 conservative rule\n"
        "[DELEGATED 2026-04-02, operator under hands-off (intake); reversal: none] the QUESTION row on "
        "two_b of round 2026-04-01-full-fff6666 is answered by keeping it \u2014 reason\n"
        "[DELEGATED 2026-04-02, operator under hands-off (intake); reversal: none] keep K.other as stated "
        "(round 2026-04-01-full-fff6666) \u2014 no question named\n")
    saved = project.REPO
    project.REPO = os.path.join(tmp, "oq")
    try:
        oq = open_question_rows({"rounds_dir": "R", "involvement": "hands-off"}, [os.path.join(rr, rn) for rn in rows])
    finally:
        project.REPO = saved
    by = {}
    for r, l, item, why, note in oq:
        by.setdefault(item, []).append((why.split()[0], note))
    say("open questions: every round's unanswered QUESTION rows; final answers and ADOPT rows stay out "
        f"{sorted(by)}", sorted(by) == ["deleg_re", "free_q", "old_open", "old_proxy", "re_q", "same_day", "two_c"])
    say("open questions: an unanchored [DELEGATED] line naming 'question' and a round decides that round's asking "
        "when it names the item or the round asked one question; a line naming no question decides nothing",
        [w for w, _ in by.get("free_q", [])] == ["FRQ2"] and "two_b" not in by and "two_c" in by)
    say("open questions: answered, then asked again -> only the later asking, noted",
        [w for w, _ in by.get("re_q", [])] == ["REQ2"] and "asked again since" in by["re_q"][0][1])
    say("open questions: [DELEGATED], then asked again -> only the later asking, noted",
        [w for w, _ in by.get("deleg_re", [])] == ["DRQ2"] and "decided as [DELEGATED]" in by["deleg_re"][0][1])
    say("open questions: a [PROXY] answer is not final (listed, with a note)",
        [n for _, n in by.get("old_proxy", [])] == ["provisional [PROXY] answer, awaiting the human's confirmation"])
    say("open questions: a same-day re-ask after a [DELEGATED] decision is listed (round order); "
        "asked on day 1 and day 2, delegated on day 2: not open",
        [w for w, _ in by.get("same_day", [])] == ["SDQ2"] and "x_then_y" not in by)


def _selftest(tmp, say):
    rr = os.path.join(tmp, "rr")
    r0 = os.path.join(rr, "2026-01-01-full-aaaaaaa"); r1 = os.path.join(rr, "2026-01-01-full-ccccccc")
    r2 = os.path.join(rr, "2026-01-02-bbbbbbb")
    for d, kind in ((r0, "statements"), (r1, "statements"), (r2, "diff")):
        os.makedirs(d); json.dump({"_meta": {"kind": kind}}, open(os.path.join(d, "TARGET.json"), "w"))
    json.dump({"global": [], "rows": [{"result": "Lemma 9.9", "flag": "CHECK", "check_reason": "OLD SHEET"}]},
              open(os.path.join(r0, "SIGNOFF.json"), "w"))
    json.dump({"global": [{"id": "G1", "title": "witness has a row", "text": "GLOBALTEXT"}],
               "rows": [{"result": "Lemma 1.6", "flag": "CHECK", "check_reason": "ZERO-ROW WITNESS"},
                        {"result": "Lemma 1.8", "flag": "CHECK", "check_reason": "SECOND-CHECK-REASON"},
                        {"result": "Lemma 1.7", "flag": "OK"}],
               "not_formalized": [{"result": "Theorem 1.5", "note": "cited, unused"}]},
              open(os.path.join(r1, "SIGNOFF.json"), "w"))
    open(os.path.join(r1, "ADOPTED.md"), "w").write(
        "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        "| nv | Paper.old_q | Fail | **QUESTION** | only the human |\n"
        "| subst | Paper.Osc | Fail | QUESTION (see G5) | is the defer reason still true |\n")
    open(os.path.join(r2, "ADOPTED.md"), "w").write(
        "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        "| subst | Paper.Osc | Fail | **QUESTION** | hV redundant |\n"
        "| subst | Paper.fixed | Fail | **ADOPT** | delete |\n"
        "| subst | Paper.dup | Fail | **DEFER** (standing: dup-quality) | duplicate |\n"
        "| subst | Paper.rej | Fail | **REJECT** | see the **QUESTION** row above |\n"
        "| subst | Paper.gt | Fail | **QUESTION** | reading m > 0 assumed |\n")
    open(os.path.join(rr, "PAPER_DEFECTS.md"), "w").write(
        "| # | where | status | repair | what |\n|---|---|---|---|---|\n| 1 | tex 654 | **misprint (true as intended)** | typo | `hd = \\|i\\|` swapped |\n")
    open(os.path.join(rr, "DEVIATIONS.md"), "w").write(
        "| # | result | why | kind |\n|---|---|---|---|\n| R1 | Lemma 1.14 | termination | paper step fails |\n"
        "| R2 | Lemma 2.1 | bookkeeping | same strength |\n")
    open(os.path.join(rr, "SKIPPED.md"), "w").write("| # | what is not formalized | reason |\n|---|---|---|\n| 1 | **Theorem 1.5** | cited |\n")
    log = ("# Run log\n## Intake\nbudget standard; approver [PROXY] operator\n"
           "## Rounds\n- round X [PROXY 2026-01-02, operator] implement and go on\n  continued line\n"
           "- report fault: the trust section presents the [PROXY] approval as human (prose only)\n"
           "- plain round line\n## Open questions\n- Should the author be told about defect 1?\n"
           "- Settled thing (answered 2026-01-03)\n## Answered\n- answered check:Lemma_1.6 (2026-01-03): keep\n")
    open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
    open(os.path.join(rr, "UNUSED_ARGS.md"), "w").write(
        "# Unused arguments\n\n## Helpers (1): each is a finding\n\n- `Paper.helper`: argument 1: (h : HELPERQZ)\n\n"
        "## Approved statements (1): hypotheses that may mirror the paper's\n\n"
        "- `Paper.lemma_2_2`: argument 2: (hn : 5 ≤ n); argument 3: (hk : IDLEQZ)\n")
    json.dump({"round": os.path.basename(r1), "by": "agent", "date": "2026-01-02", "commit": "c",
               "rows": {"Lemma 1.6": {"status": "approved"}, "Lemma 1.7": {"status": "excluded"}},
               "note": "NOTE-X"}, open(os.path.join(rr, "APPROVED_FINGERPRINTS.json"), "w"))
    json.dump({"date": "2025-12-01", "by": "human"}, open(os.path.join(rr, "APPROVED_FINGERPRINTS.2025-12-01.json"), "w"))
    rn = os.path.join(rr, "2026-01-03-full-ddddddd"); os.makedirs(rn)
    json.dump({"_meta": {"kind": "statements"}}, open(os.path.join(rn, "TARGET.json"), "w"))
    json.dump({"global": [], "rows": [{"result": "Lemma 7.7", "flag": "CHECK", "check_reason": "NEWER UNAPPROVED SHEET"}]},
              open(os.path.join(rn, "SIGNOFF.json"), "w"))
    cfg = {"name": "T", "rounds_dir": "rr", "lean_files": [],
           "standing_defers": [{"id": "lit-X", "item": "witness", "reason": "r", "revisit_when": "never"}]}
    g = globals(); saved = (project.REPO, g["changes_after"])
    project.REPO = tmp
    g["changes_after"] = lambda c, r: ["abc123 implement late rows"]
    try:
        # review of fix-mini1 (M1): a newer round-named directory holding only fresh-reader prompts
        # is not the last round (its UNCOVERED rows, none, replaced the real round's)
        rp = os.path.join(rr, "2026-01-04-eeeeeee")
        os.makedirs(os.path.join(rp, "prompts"))
        open(os.path.join(rp, "prompts", "fresh_reader_report-x_1.txt"), "w").write("x")
        os.utime(rp, (4_000_000_000, 4_000_000_000))
        say("resolve_round: a directory with only prompts is not the newest round",
            os.path.basename(resolve_round(cfg, None, False)[1] or "") == os.path.basename(rn))
        shutil.rmtree(rp)
        rounds = [r0, r1, r2]
        text, anchors = skeleton(cfg, rounds, r2)
        tN, _ = skeleton(cfg, rounds + [rn], rn)
        say("with a newer, unapproved sheet the APPROVED sheet is used, and the gap is flagged",
            "NEWER UNAPPROVED SHEET" not in tN and "ZERO-ROW" not in tN and "SECOND-CHECK-REASON" in tN
            and "WARNING: the newest sheet" in tN)
        A = set(anchors)
        qs = question_rows(rounds)
        say("QUESTION decisions are read from the decision column (bold or not), every round",
            set(qs) == {"Paper.old_q", "Paper.Osc", "Paper.gt"})
        say("a REJECT row that mentions **QUESTION** in its reason is not a question", "Paper.rej" not in qs)
        say("every round and lane that asked the same item is kept",
            [r for r, _, _ in qs["Paper.Osc"]] == [os.path.basename(r1), os.path.basename(r2)]
            and "defer reason" in text and "hV redundant" in text)
        say("anchors are comment-safe and all round-trip (an item with '>' is still required)",
            all(ANCHOR_RE.fullmatch(f"<!-- item:{a} -->") for a in anchors)
            and any(a.startswith("question:Paper.gt") for a in anchors))
        want = {"approval", "global:G1", "check:Lemma_1.8", "notformalized:Theorem_1.5", "defer:lit-X",
                "proposed-defer:dup-quality", "after-last-round"}
        say("one anchored item per thing the human must see",
            all(any(x == w or x.startswith(w + ":") or x.startswith(w + "@") for x in A) for w in want))
        say("an OK row is not an item", "check:Lemma_1.7" not in A)
        say("mini1: an approved statement's unused hypotheses (UNUSED_ARGS.md) are one keep/drop item; a "
            "helper's are not", sum(a.startswith("unused:Paper.lemma_2_2@") for a in A) == 1
            and "`(hn : 5 ≤ n)`; `(hk : IDLEQZ)`" in text and "HELPERQZ" not in text
            # conf1: the anchor hashes the line as read before its arguments were split (logged answers hold)
            and versioned("unused", "Paper.lemma_2_2", "(hn : 5 ≤ n); argument 3: (hk : IDLEQZ)") in A)
        # conf1 (C1 audit): unused_args.py writes a declaration's arguments on one line (the real UNUSED_ARGS.md)
        cu_ = tempfile.mkdtemp(prefix="cu-")
        open(os.path.join(cu_, "UNUSED_ARGS.md"), "w").write(
            "## Helpers (0): each is a finding -- drop the argument, or record why it must stay\n\n(none)\n\n"
            "## Approved statements (1): hypotheses that may mirror the paper's; report, do not delete\n\n"
            "- `Paper.lemma_2_6`: argument 2: (hx : 0 < x); argument 4: (hy : y ≠ 0)\n")
        say("conf1: an approved statement's unused arguments on one line are each read whole (\"argument 4:\" is "
            "not part of the first); the item's anchor hashes the text as read before",
            unused_hypotheses(cu_) == [("Paper.lemma_2_6", ["(hx : 0 < x)", "(hy : y ≠ 0)"])]
            and unused_hypotheses(cu_, legacy=True) == [("Paper.lemma_2_6", ["(hx : 0 < x); argument 4: (hy : y ≠ 0)"])])
        shutil.rmtree(cu_)
        say("an item answered in RUN_LOG `## Answered` is listed as previously answered, not asked",
            "check:Lemma_1.6" not in A and "Previously answered" in text)
        say("the sheet used is the APPROVED round's, not merely the newest", "OLD SHEET" not in text)
        proxies = [a for a in anchors if a.startswith("proxy:")] or ["proxy:none-a", "proxy:none-b"]
        say("[PROXY] decisions are found (intake + dated tag), prose mentions are not", len(proxies) == 2
            and "continued line" in text and "prose only" not in text)
        open_qs = [a for a in anchors if a.startswith("open:")]
        say("open questions in RUN_LOG are items; answered ones are not", len(open_qs) == 1 and "author be told" in text)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(
            log.replace("## Rounds\n", "## Rounds\n- r0 [PROXY 2026-01-01, operator] NEW EARLIER DECISION\n"))
        text2, anchors2 = skeleton(cfg, rounds, r2)
        def anchor_of(t, needle):
            k = t.find("implement and go on")
            m = ANCHOR_RE.search(t, k) if k >= 0 else None
            return m.group(1) if m else None
        say("[PROXY] anchors are content-stable: the same entry keeps its anchor when one is added before it",
            anchor_of(text, "") is not None and anchor_of(text, "") == anchor_of(text2, "")
            and len([a for a in anchors2 if a.startswith("proxy:")]) == 3)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("item text carries the record: global text, CHECK reason, exclusions, note, history, defects box",
            all(x in text for x in ("GLOBALTEXT", "SECOND-CHECK-REASON", "Excluded: Lemma 1.7", "NOTE-X",
                                    "2025-12-01 by human", "defect 1", "hd = |i|", "not formalized: **Theorem 1.5**",
                                    "proof route R1: Lemma 1.14 (paper step fails)"))
            and "Lemma 2.1 (same strength)" not in text)
        say("an agent approval is named as such", "AGENT, not by a human" in text)
        filled = re.sub(re.escape(FILL) + r".*?>>", "x" * 25, text, flags=re.S)
        say("the unfilled skeleton fails the check", any("still unfilled" in p for p in check(text, anchors)))
        say("a filled skeleton passes", check(filled, anchors, os.path.basename(r2)) == [])
        say("a document written for another round fails",
            any("written for round" in p for p in check(filled, anchors, "other")))
        dropped = filled.replace(f"<!-- item:{proxies[0]} -->", "")
        say("dropping an item's anchor fails", any(proxies[0] in p for p in check(dropped, anchors)))
        todo = re.sub(re.escape(FILL) + r".*?>>", "TODO: " + "y" * 25, text, flags=re.S)
        say("'TODO' left in otherwise long content fails", any("TODO" in p for p in check(todo, anchors)))
        thin = re.sub(re.escape(FILL) + r".*?>>", "ok", text, flags=re.S)
        say("labelled fields with almost no content fail", any("missing or empty" in p for p in check(thin, anchors)))
        footer = "# D\n\nNothing to decide.\n\n## All\n" + "\n".join(f"<!-- item:{a} -->" for a in anchors)
        say("anchors parked in a footer without the five fields fail",
            any("missing or empty" in p for p in check(footer, anchors)))
        fenced = filled.replace(f"<!-- item:{proxies[1]} -->", "```\n<!-- item:" + proxies[1] + " -->\n```")
        say("an anchor hidden in a code fence does not count", any(proxies[1] in p for p in check(fenced, anchors)))
        grouped = filled.replace(f"<!-- item:{proxies[1]} -->", "").replace(
            f"<!-- item:{proxies[0]} -->", f"<!-- item:{proxies[0]} --> <!-- item:{proxies[1]} -->")
        say("grouping two items under one decision (anchors kept) passes", check(grouped, anchors) == [])
        # the model document's style: labels with a period, no colon, bold option paragraphs, N/A
        sec = ("### D2. Remove the assumption\n<!-- item:global:G1 -->\nThis concerns G1.\n\n"
               "**Paper.** Lemma 1.10 at tex l.449 uses a cited result throughout.\n\n"
               "**Lean** `thm_1_1` (MainTheorem.lean:312) takes hV as an argument.\n\n"
               "**Evidence** Not applicable: this is a configuration decision.\n\n"
               "**Options.**\n**(a) Keep hV.** No code change; a reader still sees it.\n"
               "**(b) Add thm_1_1'.** Compiled; no approved statement changes.\n\n"
               "**Recommendation:** (b), because nothing approved changes and the theorem reads cleaner.\n")
        f = fields_of(sec)
        say("fields: labels with a period, without a colon, and bold option paragraphs are read whole",
            all(field_ok(f.get(k, "")) for k in ("paper", "lean", "evidence", "options", "recommendation"))
            and "(b) Add" in f["options"])
        say("'Not applicable: <why>' satisfies a field", field_ok("Not applicable: configuration decision"))
        say("placeholder words inside code are not flagged, in prose they are",
            not [p for p in check("> **READ THIS FIRST**\n`TODO x` and code:\n```\nTODO\n```\n", []) if "placeholder text" in p]
            and [p for p in check("> **READ THIS FIRST**\nTODO later\n", []) if "placeholder text" in p])
        say("a section carrying an anchor must mention what it covers",
            any("never mentions" in p for p in check(filled.replace("CHECK row: Lemma 1.8", "CHECK row: something"),
                                                      anchors, names=skeleton.names)))
        say("a result is mentioned by its number, also in a plural list ('Lemmas 1.6, 1.8')",
            mentions("Lemma 1.8", "lemmas 1.6, 1.8 differ") and not mentions("Lemma 1.8", "lemma 1.81"))
        say("a [PROXY] section must say who decided", mentions("[PROXY", "[proxy 2026] x")
            and not mentions("[PROXY", "decided by us"))
        say("an anchor that is no longer an item is reported",
            any("no longer an item" in p for p in check(filled + "\n### Old\n<!-- item:proxy:gone -->\n", anchors)))
        bl = [f"> - {x}" for x in box_lines(cfg)]
        say("the box pre-lists defects and skips; deleting an entry fails",
            bl and all(x in filled for x in bl)
            and any("lost a recorded entry" in p for p in check(filled.replace(bl[0], ""), anchors, None, bl)))
        log3 = log.replace("## Answered\n", "## Answered\n- answered proxy:x (2026-01-04): [PROXY 2026-01-04, operator] approve (a)\n")
        log3 = log3.replace("  continued line\n", "  continued line\n  Implemented Lean abc.\n")
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log3)
        t4, a4 = skeleton(cfg, rounds, r2)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        old_p = [x for x in anchors if x.startswith("proxy:")]
        new_p = [x for x in a4 if x.startswith("proxy:")]
        say("a [PROXY] answer under `## Answered` is an item to confirm; an appended line keeps old anchors",
            set(old_p) <= set(new_p) and len(new_p) == len(old_p) + 1)
        open(os.path.join(r2, "ADOPTED.md"), "a").write("| nv | Paper.gone | STALE PASS | **UNCOVERED** | no longer exists |\n")
        t5, a5 = skeleton(cfg, rounds, r2)
        say("the last round's UNCOVERED rows are one item", any(x.startswith("uncovered:") for x in a5) and "Paper.gone" in t5)
        na_opt = re.sub(r"(\*\*Options, and what each changes:\*\* <!-- re-approval\? new round\? --> )x+",
                        r"\1Not applicable: nothing to choose", filled, count=1)
        say("'Not applicable' in an Options field fails the check",
            any("Options missing or empty" in p for p in check(na_opt, anchors)))
        ka = filled.find(f"<!-- item:{proxies[0]} -->")
        k = filled.rfind("### ", 0, ka) if ka >= 0 else 0
        e = filled.find("### ", k + 4) if ka >= 0 else 0
        noproxy = filled[:k] + filled[k:e].replace("[PROXY", "[proxied") + filled[e:] if ka >= 0 else ""
        say("a [PROXY] decision's section that no longer says [PROXY] fails (who decided must show)",
            any("never mentions '[PROXY'" in p for p in check(noproxy, anchors, names=skeleton.names)))
        say("'Not applicable' is accepted for Paper/Lean/Evidence only",
            field_ok("Not applicable: process decision, no paper text") and
            not field_ok("Not applicable: nothing to choose here at all", allow_na=False))
        moved = filled.replace(BOX_START, "> moved").rstrip() + "\n\n" + BOX_START + "\n"
        say("the box must come before the decisions", any("before the decisions" in p for p in check(moved, anchors)))
        tilde = filled.replace(f"<!-- item:{proxies[1]} -->", "~~~\n<!-- item:" + proxies[1] + " -->\n~~~")
        say("an anchor inside a ~~~ fence does not count", any(proxies[1] in p for p in check(tilde, anchors)))
        open(os.path.join(r2, "ADOPTED.md"), "a").write("\n| decision | rows |\n|---|---|\n| **UNCOVERED** | 92 |\n")
        t6, _ = skeleton(cfg, rounds, r2)
        say("a summary table with an UNCOVERED cell is not counted as a row", "(1 UNCOVERED rows)" in t6)
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | parameters | why | decision | status |\n|---|---|---|---|---|---|\n"
            "| 1 | Lemma 4.10 | all | EmbSetting is empty (Lemma 4.9) | keep | open |\n"
            "| 2 | Lemma 9.1 | m=2 | gone | repaired | repaired in abc1234 |\n")
        t7, a7 = skeleton(cfg, rounds, r2)
        os.remove(os.path.join(rr, "VACUOUS.md"))
        say("open vacuous statements and paper defects are items; repaired ones are not",
            any((x.startswith("vacuous:") and "Lemma_4.10" in x) for x in a7) and not any("9.1" in x for x in a7)
            and any(x.startswith("defect:") for x in a7) and "vacuous: Lemma 4.10" in t7)
        log5 = log.replace("- answered check:Lemma_1.6 (2026-01-03): keep", "- answered question:Paper.Osc (2026-01-01): keep hV")
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log5)
        t8, a8 = skeleton(cfg, rounds, r2)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("an item asked again after it was answered comes back, noting the old answer",
            "question:Paper.Osc" in a8 and "asked again since" in t8)
        pdp_ = os.path.join(rr, "PAPER_DEFECTS.md"); pd_o = open(pdp_).read()
        open(pdp_, "w").write("| # | where | status | repair | what the paper says | why it is wrong | consequence |\n|---|---|---|---|---|---|---|\n"
                              "| 1 | tex 9 | false | substantial | PRINTED-TEXT | WHY-SUMMARY here. More. | MAIN RESULTS SURVIVE. Detail. |\n")
        open(pdp_, "a").write("")
        try:
            bl_ = box_lines(cfg)
        finally:
            open(pdp_, "w").write(pd_o)
        say("a defect's box line quotes the printed text and says what is wrong (one sentence each)",
            any("the paper says \"PRINTED-TEXT\"; WHY-SUMMARY here." in b and "More" not in b
                and "Consequence: MAIN RESULTS SURVIVE." in b and "Detail" not in b for b in bl_))
        # trials #4, #6, #7: a quoted printed statement is kept whole and closed, never spliced onto the reason
        open(pdp_, "w").write("| # | where | status | repair | what the paper says | why it is wrong | Lean witness |\n"
                              "|---|---|---|---|---|---|---|\n"
                              "| 2 | Lemma 2.4 | false | add hypothesis | \"Let r ≥ 2 and let s be prime. Then s ∤ Q_r(s).\" "
                              "| counterexample: r = 3, s = 5. Both hold. | `x` |\n")
        try:
            bq_ = box_lines(cfg)
        finally:
            open(pdp_, "w").write(pd_o)
        say("trial #7: the box quotes a printed statement whole, its quote closed, then '; ' and the reason (not '\". ')",
            any("the paper says \"Let r ≥ 2 and let s be prime. Then s ∤ Q_r(s).\"; counterexample: r = 3, s = 5." in b
                for b in bq_))
        # re-check N3: a defect confirmed by argument, with no Lean witness, stays in the box and says so
        open(pdp_, "w").write("| # | where | status | repair | what the paper says | why it is wrong | Lean witness |\n"
                              "|---|---|---|---|---|---|---|\n| 1 | tex 9 | false | substantial | P | W | `real_witness` |\n"
                              "| 2 | tex 12 | false | substantial | Q | V | none: confirmed by argument (ADOPTED.md, round r) |\n")
        try:
            bl_n3 = box_lines(cfg)
        finally:
            open(pdp_, "w").write(pd_o)
        say("N3: a witness-free defect is in the box, marked confirmed by argument only; a witnessed one is not marked",
            any(b.startswith("defect 2:") and "NO LEAN WITNESS" in b for b in bl_n3)
            and any(b.startswith("defect 1:") and "NO LEAN WITNESS" not in b for b in bl_n3))
        sk_ = os.path.join(rr, "SKIPPED.md"); sk_o = open(sk_).read()
        open(sk_, "w").write("| # | what | reason |\n|---|---|---|\n| 1 | **Theorem 1.5** | SKIP-REASON here. More. |\n")
        try:
            blk = box_lines(cfg)
        finally:
            open(sk_, "w").write(sk_o)
        say("a skip's box line gives its reason (first sentence)",
            any(b.startswith("not formalized: **Theorem 1.5**: SKIP-REASON here.") and "More" not in b for b in blk))
        say("sentences are not cut after common abbreviations or inside code",
            first_sentence("Cut, resp. R holds. Next.") == "Cut, resp. R holds."
            and first_sentence("See `a. B` here. Next.") == "See `a. B` here."
            and first_sentence("By Obs. 4.7 it fails. Next.") == "By Obs. 4.7 it fails.")
        say("the box summary of a defect is the first sentence of what is wrong (not cut at e.g., and a long "
            "sentence never cut inside: trial #9)",
            first_sentence("(i,j) is (row, column) (e.g. tex 1026) so rows swap. More here.")
            == "(i,j) is (row, column) (e.g. tex 1026) so rows swap." and first_sentence("x " * 300) == ("x " * 300).strip()
            and "…" not in first_sentence("x " * 300 + "end. Next."))
        open(pdp_, "w").write("| # | where | status | repair | what the paper says | why it is wrong | consequence |\n|---|---|---|---|---|---|---|\n"
                              "| 1 | tex 9 | false | none | Let x be given. Then P holds and Q holds. | WHY. |  |\n")
        try:
            bl9 = box_lines(cfg)
        finally:
            open(pdp_, "w").write(pd_o)
        say("trial #9: the box quotes the printed statement in full, not its first sentence (the preamble alone)",
            any("the paper says \"Let x be given. Then P holds and Q holds.\"; WHY." in b for b in bl9))
        # trial #9 audit: the reason given is the counterexample, not the 'why' cell's first sentence (a definition)
        open(pdp_, "w").write("| # | where | status | repair | what the paper says | why it is wrong | consequence |\n|---|---|---|---|---|---|---|\n"
                              "| 1 | tex 9 | false | typo | For x ≥ 3, X = Y. | X_x are DEFQZ values. Counterexample: x = 4. "
                              "At x = 4, X = 0 and Y = 1 CEQZ. The intent is clear. |  |\n")
        try:
            blc = box_lines(cfg)
        finally:
            open(pdp_, "w").write(pd_o)
        say("trial #9: a defect's box line gives the counterexample (and its computation), not a definition",
            any("the paper says \"For x ≥ 3, X = Y.\"; Counterexample: x = 4. At x = 4, X = 0 and Y = 1 CEQZ." in b
                and "DEFQZ" not in b and "intent" not in b for b in blc))
        _lw = " ".join(f"w{i}" for i in range(400)) + " ENDQZ."
        open(pdp_, "w").write("| # | where | status | repair | what the paper says | why it is wrong | consequence |\n|---|---|---|---|---|---|---|\n"
                              f"| 1 | tex 9 | false | substantial | P | {_lw} | C |\n")
        try:
            t9, _a9 = skeleton(cfg, rounds, r2)
        finally:
            open(pdp_, "w").write(pd_o)
        _rec9 = [l for l in t9.splitlines() if l.startswith("Record (PAPER_DEFECTS.md row 1)")]
        say("trial #9: a record quoted in the decisions document is quoted whole (it was cut at 900 characters)",
            _rec9 and all("ENDQZ" in l and "…" not in l for l in _rec9))
        say("split_row keeps an escaped bar inside a cell", project.split_row(r"| a | x = \|i\| | b |") == ["a", "x = |i|", "b"])
        g["approval"], saved_appr = (lambda c: None), g["approval"]
        try:
            t3, _ = skeleton(cfg, rounds, r2)
        finally:
            g["approval"] = saved_appr
        say("no approval at all is said as NOT APPROVED", "NOT APPROVED" in t3)
        # --- answers and later askings: rounds are ordered, contents are versioned ---
        def with_log(extra):
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + extra)
            try:
                return skeleton(cfg, rounds, r2)
            finally:
                open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        rb0, rb1 = os.path.basename(r0), os.path.basename(r1)
        _, aq = with_log(f"- answered question:Paper.old_q (2026-01-01, {rb0}): keep\n")
        say("a QUESTION asked in a later round on the SAME day as the answer comes back",
            "question:Paper.old_q" in aq)
        _, aq = with_log(f"- answered question:Paper.old_q (2026-01-01, {rb1}): keep\n")
        say("...and one answered at or after its last asking stays answered", "question:Paper.old_q" not in aq)
        appr_a = next((x for x in anchors if x.startswith("approval")), "approval:MISSING")
        later_a = next(x for x in anchors if x.startswith("after-last-round"))
        glob_a = next((x for x in anchors if x.startswith("global:G1")), "global:MISSING")
        say("an approval by the agent and its sheet's global difference are items (nothing was the human's at B)",
            "MISSING" not in appr_a + glob_a)
        tq, aq = with_log(f"- answered {appr_a} (2026-01-03, {os.path.basename(r2)}): ok\n"
                          f"- answered {later_a} (2026-01-03, {os.path.basename(r2)}): ok\n"
                          f"- answered {glob_a} (2026-01-03, {os.path.basename(r2)}): ok\n")
        say("answered approval, later changes and global difference are not asked again",
            not ({appr_a, later_a, glob_a} & set(aq)))
        ap_p = os.path.join(rr, "APPROVED_FINGERPRINTS.json")
        ap_old = open(ap_p).read()
        # by the agent: under involved a human's approval and its sheet are Checkpoint B decisions C lists, not asks
        # (trial #8; _checkpoint_b_decided_controls); this checks the anchors' versioning
        json.dump(dict(json.loads(ap_old), date="2026-01-09", by="agent"), open(ap_p, "w"))
        g["changes_after"] = lambda c, r: ["abc123 implement late rows", "def456 a NEW commit"]
        sheet = os.path.join(r1, "SIGNOFF.json"); sheet_old = open(sheet).read()
        open(sheet, "w").write(sheet_old.replace("GLOBALTEXT", "GLOBALTEXT, now different"))
        try:
            tq, aq = with_log(f"- answered {appr_a} (2026-01-03, {os.path.basename(r2)}): ok\n"
                              f"- answered {later_a} (2026-01-03, {os.path.basename(r2)}): ok\n"
                              f"- answered {glob_a} (2026-01-03, {os.path.basename(r2)}): ok\n")
        finally:
            open(ap_p, "w").write(ap_old); open(sheet, "w").write(sheet_old)
            g["changes_after"] = lambda c, r: ["abc123 implement late rows"]
        say("a NEW approval, a NEW commit and NEW sheet text are new items despite the old answers",
            sum(x.startswith(("approval", "after-last-round", "global:G1")) for x in aq) == 3
            and not ({appr_a, later_a, glob_a} & set(aq)))
        say("...each showing the answer to the earlier version", tq.count("answered for an earlier version") == 3)
        # --- round-4 audit: versioning, mentions, wording, scope ---
        _, aq = with_log(f"- answered check:Lemma_1.8 (2026-01-01, {os.path.basename(r0)}): keep\n")
        say("a CHECK row answered before the approved sheet's round is asked again", "check:Lemma_1.8" in aq)
        _, aq = with_log(f"- answered check:Lemma_1.8 (2026-01-01, {os.path.basename(r1)}): keep\n")
        say("...and not if answered at that round", "check:Lemma_1.8" not in aq)
        say("defining columns only: a refreshed File.lean:N or commit hash keeps the anchor",
            defining(["where", "status", "what the paper says", "lean witness"],
                     ["tex 1", "typo", "says X (Section4.lean:563, :565)", "w.lean:9"], ("where", "status", "what"))
            == defining(["where", "status", "what the paper says", "lean witness"],
                        ["tex 1", "typo", "says X (Section4.lean:12, :14)", "w.lean:10"], ("where", "status", "what"))
            and defining(["where", "status", "what the paper says"], ["tex 1", "typo", "says Y"], ("where", "status", "what"))
            != defining(["where", "status", "what the paper says"], ["tex 1", "typo", "says X"], ("where", "status", "what")))
        recs = {"PAPER_DEFECTS.md": ("| 1 | tex 654 | **misprint (true as intended)** | typo | `hd = \\|i\\|` swapped |", "| 1 | tex 654 | **misprint (true as intended)** | typo | `hd = \\|j\\|` swapped |"),
                "SKIPPED.md": ("| 1 | **Theorem 1.5** | cited |", "| 1 | **Theorem 1.5** | cited, and unused |"),
                "DEVIATIONS.md": ("| R1 | Lemma 1.14 | termination | paper step fails |", "| R1 | Lemma 1.14 | termination | lean intermediate weaker |")}
        for fname, (old_row, new_row) in recs.items():
            fp = os.path.join(rr, fname); orig = open(fp).read()
            assert old_row in orig, fname
            kind_ = {"PAPER_DEFECTS.md": "defect:", "SKIPPED.md": "skip:", "DEVIATIONS.md": "route:"}[fname]
            before = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith(kind_)}
            open(fp, "w").write(orig.replace(old_row, new_row))
            try:
                after = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith(kind_)}
            finally:
                open(fp, "w").write(orig)
            say(f"a changed {fname} row is a new item (versioned anchor)", before and after and before != after)
        # B3: the defect anchor hashes `status` and `repair`: a changed repair alone re-hashes it (a new item)
        fp = os.path.join(rr, "PAPER_DEFECTS.md"); orig = open(fp).read()
        before = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")}
        open(fp, "w").write(orig.replace("| typo | `hd = \\|i\\|`", "| local | `hd = \\|i\\|`"))
        try:
            after = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")}
        finally:
            open(fp, "w").write(orig)
        _oh = ["#", "where", "severity", "what the paper says", "why it is wrong", "consequence"]
        _oc = ["1", "tex 3", "S1", "x", "w", "c"]
        say("B3: an old-format (`severity`) defect row stays an item with its pre-B3 anchor text until rewritten",
            is_defect_header(_oh) and defining(_oh, _oc, ("where", "status", "repair", "severity", "what", "why",
                                                         "consequence"))
            == defining(_oh, _oc, ("where", "severity", "what", "why", "consequence")))
        say("B3: a defect row whose `repair` alone changes is a new item (status and repair are hashed in its anchor)",
            "| typo | `hd = \\|i\\|`" in orig and before and after and before != after)
        pdp = os.path.join(rr, "PAPER_DEFECTS.md"); pd_old = open(pdp).read()
        open(pdp, "w").write("| # | where | status | repair | what | lean witness |\n|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | misprint (true as intended) | typo | swapped | `w` (Basic.lean:240) |\n")
        try:
            w1 = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")}
            cur_pd = open(pdp).read()
            open(pdp, "w").write(cur_pd.replace("`w` (Basic.lean:240)", "`w2`, re-checked"))
            w2 = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")}
        finally:
            open(pdp, "w").write(pd_old)
        say("changing a non-defining column (the Lean witness) keeps the defect's anchor", w1 and w1 == w2)
        open(pdp, "w").write("| # | where | status | repair | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | misprint (true as intended) | typo | swapped | rows | `w` | main results survive |\n")
        try:
            c1 = [x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")]
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {c1[0] if c1 else 'none'} (2026-01-05, {os.path.basename(r2)}): ok\n")
            cur_pd = open(pdp).read()
            open(pdp, "w").write(cur_pd.replace("main results survive", "Theorem 1.1 fails"))
            tc2p, c2p = skeleton(cfg, rounds, r2)
            open(pdp, "w").write(cur_pd.replace("| swapped |", "| swapped twice |"))
            tc2, c2 = skeleton(cfg, rounds, r2)
            open(pdp, "w").write(cur_pd.replace("tex 654", "tex 656"))
            tc3, c3 = skeleton(cfg, rounds, r2)
        finally:
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        open(pdp, "w").write("| # | where | status | repair | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | misprint (true as intended) | typo | swapped | rows | `w` | main results survive |\n")
        try:
            v1 = next((x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")), "none")
            cur_pd = open(pdp).read()
            open(pdp, "w").write(cur_pd.replace("| swapped |", "| swapped v2 |"))
            v2 = next((x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")), "none")
            open(pdp, "w").write(cur_pd.replace("| swapped |", "| swapped v3 |"))
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(
                log + f"- answered {v2} (2026-01-02, {os.path.basename(r1)}): LATER-ANSWER\n"
                f"- answered {v1} (2026-01-01, {os.path.basename(r0)}): EARLIER-ANSWER\n")
            tv3, _ = skeleton(cfg, rounds, r2)
        finally:
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        open(pdp, "w").write("| # | where | status | repair | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | misprint (true as intended) | typo | a | b | `w` | c1 |\n| 2 | tex 1028 | misprint (true as intended) | typo | d | e | `w` | c2 |\n")
        try:
            dd = sorted(x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:"))
            cur_pd = open(pdp).read()
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {dd[0] if dd else 'x'} (2026-01-05, {os.path.basename(r2)}): DEFECT-ONE-ANSWER\n")
            open(pdp, "w").write(cur_pd.replace("| typo | a |", "| typo | a changed |"))
            tdd, _ = skeleton(cfg, rounds, r2)
        finally:
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        items_dd = tdd.split("## Decisions", 1)[1].split("## How to answer")[0]
        say("two defects located only by tex lines are distinct items; one's answer is not shown on the other",
            len(set(dd)) == 2 and items_dd.count("DEFECT-ONE-ANSWER") == 1)
        # trial #8: an answer logged under a row's pre-trial-#8 anchor (it hashed the prose) answers the row while its
        # substance is unchanged: the legacy anchor is read from the record's committed history
        import subprocess as _sp
        _G = lambda *a: _sp.run(["git", "-C", rr, *a], capture_output=True, text=True,
                                env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                         GIT_COMMITTER_EMAIL="t@t"))
        rowv1 = "| 1 | tex 654 | false | add hypothesis | says X | W1 | `w` | c1 |\n"
        hd8 = "| # | where | status | repair | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|---|\n"
        try:
            _G("init", "-q")
            open(pdp, "w").write(hd8 + rowv1)
            _G("add", "-A"); _G("commit", "-qm", "adjudicate v1")
            h8, c8 = hd8.splitlines()[0], rowv1
            leg = defect_anchor([x.strip().lower() for x in h8.strip("|").split("|")],
                                [x.strip() for x in c8.strip().strip("|").split("|")], legacy=True)
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {leg} (2026-01-05, {os.path.basename(r2)}): LEGACY-ANS\n")
            open(pdp, "w").write(hd8 + rowv1.replace("| W1 |", "| W1. Terms used in this row: a glossary. |"))
            _G("add", "-A"); _G("commit", "-qm", "reader-fix")
            tl8, al8 = skeleton(cfg, rounds, r2)
            open(pdp, "w").write(hd8 + rowv1.replace("| false |", "| false (as printed) |"))
            tl9, al9 = skeleton(cfg, rounds, r2)
        finally:
            shutil.rmtree(os.path.join(rr, ".git"), ignore_errors=True)
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("trial #8: an answer under a defect row's legacy (prose-hashing) anchor still answers it after a reworded "
            "reason, with no stray line", "@" in leg and not any(x.startswith("defect:") for x in al8)
            and "LEGACY-ANS" in tl8.split("## Previously answered", 1)[-1] and "matches no current item" not in tl8)
        say("...and a changed status asks it again, the legacy answer shown as an earlier version's",
            any(x.startswith("defect:") for x in al9) and "answered for an earlier version" in tl9 and "LEGACY-ANS" in tl9)
        say("tex citation forms (lists, 'tex line N') are stripped from identities and hashes",
            defining(["what"], ["see tex 654, 660 and tex line 12"], ("what",)) == defining(["what"], ["see tex 1, 2 and tex line 3"], ("what",)))
        vp_ = os.path.join(rr, "VACUOUS.md")
        hdr_v = "| # | statement | for which parameters | why | decision and reasoning | status |\n|---|---|---|---|---|---|\n"
        vset = []
        try:
            for row_ in ("| 1 | Lemma 4.10 | all | W1 | D1 | open |", "| 1 | Lemma 4.10 | m=3 | W1 | D1 | open |",
                         "| 1 | Lemma 4.10 | all | W1 | D1 | open (see 2) |", "| 1 | Lemma 4.10 | all | W2 | D2 | open |"):
                open(vp_, "w").write(hdr_v + row_ + "\n")
                vset.append({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("vacuous:")})
        finally:
            os.remove(vp_)
        try:
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all | W1 | D1 | open |\n")
            v_old = next(iter({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("vacuous:")}), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {v_old} (2026-01-05, {os.path.basename(r2)}): FAM2-ANSWER\n")
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all m | W1 | D9 | open |\n| 1 | Lemma 4.10 | m=2 | W1 | D9 | open |\n")
            tfam, _ = skeleton(cfg, rounds, r2)
        finally:
            os.remove(vp_); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        try:
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all | W1 | D1 | open |\n")
            v1_ = next(iter({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("vacuous:")}), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {v1_} (2026-01-05, {os.path.basename(r2)}): ROW1-ANS\n")
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all m | W1 | D9 | open |\n| 2 | Lemma 4.10 | m=2 | W1 | D1 | open |\n")
            tnum, _ = skeleton(cfg, rounds, r2)
        finally:
            os.remove(vp_); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("two vacuous rows about the same statement are separate families (row numbers in the identity)",
            "one of 2 items" not in tnum and "ROW1-ANS" in tnum)
        say("an earlier answer whose family now has several current items is shown on each, saying so",
            tfam.count("FAM2-ANSWER") >= 2 and "one of 2 items" in tfam)
        say("a vacuous row's parameters and status are hashed (each change is a new item); trial #8: its reason "
            "and decision prose are not", all(vset) and vset[0] != vset[1] and vset[0] != vset[2] and vset[0] == vset[3])
        dvp3 = os.path.join(rr, "DEVIATIONS.md"); dv3_old = open(dvp3).read()
        hdr3 = "| # | result | the paper's route | the lean route | why different | kind |\n|---|---|---|---|---|---|\n"
        rsets = []
        try:
            for row_ in ("| R1 | Lemma 1.14 | p | LEAN-A | w | paper step fails |", "| R1 | Lemma 1.14 | p | LEAN-B | w | paper step fails |",
                         "| R1 | Lemma 1.14 | p | LEAN-A | w2 | paper step fails |"):
                open(dvp3, "w").write(hdr3 + row_ + "\n")
                rsets.append({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("route:")})
            open(dvp3, "w").write(hdr3 + "| R1 | Lemma 1.14 | p | LEAN-A | w | paper step fails |\n")
            ra0 = next(iter(rsets[0]), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {ra0} (2026-01-05, {os.path.basename(r2)}): ROUTE-ANSWER-OK\n")
            open(dvp3, "w").write(hdr3 + "| R1 | Lemma 1.14 | p | LEAN-C | w | paper step fails |\n| R2 | Lemma 1.14 | q | x | y | lean intermediate weaker |\n")
            tfa, _ = skeleton(cfg, rounds, r2)
            open(dvp3, "w").write(hdr3 + "| R1 | Lemma 1.14 | p | LEAN-C | w | paper step fails |\n")
            tfb, _ = skeleton(cfg, rounds, r2)
        finally:
            open(dvp3, "w").write(dv3_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("a route's Lean route and reason are hashed (each change is a new item)",
            all(rsets) and rsets[0] != rsets[1] and rsets[0] != rsets[2])
        say("an answer to an earlier version is never lost: shown on the item (one current item) ...",
            "ROUTE-ANSWER-OK" in tfb.split("## Decisions", 1)[1].split("## How to answer")[0]
            and "matches no current item" not in tfb)
        say("... and with route IDs in the identity, a new route for the same result is its own family",
            "ROUTE-ANSWER-OK" in tfa.split("## Decisions", 1)[1].split("## How to answer")[0])
        g["changes_after"] = lambda c, r: ["abc1234 implement late rows"]
        la1 = [x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("after-last-round")]
        g["changes_after"] = lambda c, r: ["abc1234ff implement late rows"]
        la2 = [x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("after-last-round")]
        g["changes_after"] = lambda c, r: ["abc123 implement late rows"]
        say("after-last-round items are keyed on 7-hex commit prefixes (a longer abbreviation is the same item)",
            la1 and la1 == la2)
        pdx = os.path.join(rr, "PAPER_DEFECTS.md"); pdx_old = open(pdx).read()
        hdx = "| # | where | status | repair | what | why it is wrong | consequence |\n|---|---|---|---|---|---|---|\n"
        dsets = []
        try:
            for row_ in ("| 1 | tex 3 | false | substantial | x | W1 | c |", "| 1 | tex 3, Theorem 9 | false | substantial | x | W1 | c |", "| 1 | tex 3 | false | substantial | x | W2 | c |"):
                open(pdx, "w").write(hdx + row_ + "\n")
                dsets.append({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")})
            open(pdx, "w").write(hdx + "| 1 | tex 3 | false | substantial | x | W1 | c |\n")
            d0 = next(iter(dsets[0]), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(
                log + f"- answered {d0} (2026-01-02, {os.path.basename(r1)}): ANS-R1\n")
            open(pdx, "w").write(hdx + "| 1 | tex 3 | false | substantial | x | W9 | c |\n")
            ts_, _ = skeleton(cfg, rounds, r2)
        finally:
            open(pdx, "w").write(pdx_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("a defect's location is hashed; trial #8: its reason (prose) is not",
            all(dsets) and dsets[0] != dsets[1] and dsets[0] == dsets[2])
        say("an answer to an earlier version of a current item is not also listed as stray",
            "ANS-R1" in ts_ and "matches no current item" not in ts_)
        say("the first sentence is not cut at 'e.g.' followed by a capital",
            first_sentence("Wrong (e.g. Lemma 3 fails). Second.") == "Wrong (e.g. Lemma 3 fails).")
        say("hashing is case-insensitive", defining(["what"], ["ABC"], ("what",)) == defining(["what"], ["abc"], ("what",)))
        say("the earlier-version note shows the LATEST earlier answer (by round order)",
            "LATER-ANSWER" in tv3 and "EARLIER-ANSWER" not in tv3.split("## Decisions", 1)[1].split("## Previously")[0])
        say("trial #8: a defect whose consequence (prose) alone changes stays answered",
            not any(x.startswith("defect:") for x in c2p) and "matches no current item" not in tc2p)
        say("a defect whose printed statement changes is asked again, with the earlier answer shown",
            any(x.startswith("defect:") for x in c2) and "answered for an earlier version" in tc2)
        say("refreshing a tex line in a defect's location keeps it answered",
            not any(x.startswith("defect:") for x in c3) and "matches no current item" not in tc3)
        say("only real commit hashes are stripped: numbers and words stay",
            defining(["what"], ["n >= 1000000"], ("what",)) != defining(["what"], ["n >= 2000000"], ("what",))
            and "effaced" in defining(["what"], ["effaced"], ("what",))
            and defining(["what"], ["see abc1234f"], ("what",)) == defining(["what"], ["see 9de7ab01"], ("what",)))
        dvp = os.path.join(rr, "DEVIATIONS.md"); dv_old = open(dvp).read()
        open(dvp, "w").write(dv_old + "| R3 | Lemma 1.14 | other step | lean intermediate weaker |\n")
        try:
            rt = sorted(x for x in skeleton(cfg, rounds, r2)[1] if (x.startswith("route:") and "Lemma_1.14" in x))
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {rt[0] if rt else 'x'} (2026-01-05, {os.path.basename(r2)}): ok\n")
            tr, _ = skeleton(cfg, rounds, r2)
        finally:
            open(dvp, "w").write(dv_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("two current items of one family: the answer to one is not shown as an 'earlier version' of the other",
            len(set(rt)) == 2 and "answered for an earlier version" not in tr)
        cfg_d = dict(cfg, standing_defers=[dict(cfg["standing_defers"][0], reason="r2")])
        sd_a = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defer:")}
        sd_b = {x for x in skeleton(cfg_d, rounds, r2)[1] if x.startswith("defer:")}
        say("a changed standing defer is a new item", sd_a != sd_b)
        sheet = os.path.join(r1, "SIGNOFF.json"); sheet_old = open(sheet).read()
        nf_a = {x for x in anchors if x.startswith("notformalized:")}
        open(sheet, "w").write(sheet_old.replace("cited, unused", "cited, unused; now questioned"))
        try:
            nf_b = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("notformalized:")}
        finally:
            open(sheet, "w").write(sheet_old)
        say("a changed not-formalized note is a new item", nf_a != nf_b)
        skeleton(cfg, rounds, r2)
        nm = skeleton.names
        say("every item kind that names something carries a mention requirement",
            all(any(a.startswith(k) for a in nm) for k in
                ("global:", "check:", "notformalized:", "question:", "proxy:", "defer:", "proposed-defer:",
                 "defect:", "skip:", "route:")))
        say("'repaired' without a commit does not count as repaired", not is_repaired("repaired")
            and is_repaired("repaired in abc1234"))
        g["approval"], saved_appr = (lambda c: {"round": os.path.basename(r1), "date": "d", "rows": {}}), g["approval"]
        g["earlier_approvals"], saved_ea = (lambda c: ["2025-01-01 by approver not recorded"]), g["earlier_approvals"]
        try:
            tw, _ = skeleton(cfg, rounds, r2)
        finally:
            g["approval"], g["earlier_approvals"] = saved_appr, saved_ea
        say("an approval without a recorded approver says so", "approver NOT RECORDED" in tw)
        ea_p = os.path.join(rr, "APPROVED_FINGERPRINTS.2025-12-02.json")
        json.dump({"date": "2025-12-02"}, open(ea_p, "w"))
        try:
            ea = earlier_approvals(cfg)
        finally:
            os.remove(ea_p)
        say("an earlier approval without `by` is not shown as a human's", "2025-12-02 by approver not recorded" in ea)
        # B4 review fix 4: earlier approvals in the order made: unnumbered first, then .2, .3, ..., .10 (numerically)
        eo_ = [("APPROVED_FINGERPRINTS.2025-12-02.json", "first"), ("APPROVED_FINGERPRINTS.2025-12-02.2.json", "second"),
               ("APPROVED_FINGERPRINTS.2025-12-02.10.json", "tenth")]
        for n_, b_ in eo_:
            json.dump({"date": "2025-12-02", "by": b_}, open(os.path.join(rr, n_), "w"))
        try:
            ea = earlier_approvals(cfg)
        finally:
            for n_, _ in eo_:
                os.remove(os.path.join(rr, n_))
        say("B4 review fix 4: earlier approvals are listed in the order made (unnumbered, .2, .10)",
            [x for x in ea if x.startswith("2025-12-02 by ")] == ["2025-12-02 by first", "2025-12-02 by second",
                                                                  "2025-12-02 by tenth"])
        F = ("**Paper**: " + "p" * 25 + "\n\n**Lean**: " + "l" * 25 + "\n\n**Evidence**: " + "e" * 25
             + "\n\n**Options**: " + "o" * 25 + "\n\n**Recommendation:** " + "r" * 25 + "\n")
        doc3s = (f"{BOX_START}\n> - B\n\n## Background\nb\n## Decisions\n" + "".join(
            f"### D{k}: Lemma 1.{k}\n<!-- item:z{k} -->\n" + (F if k < 3 else F.replace("e" * 25, "")) + "\n" for k in (1, 2, 3)))
        say("fields are checked in every section, not only the first",
            any("D3" in p and "Evidence" in p for p in check(doc3s, ["z1", "z2", "z3"], box_lines=["> - B"])))
        say("'Not applicable' needs a reason", not field_ok("Not applicable") and field_ok("Not applicable: the item is a config rule"))
        say("a configured standing defer is not also 'proposed'",
            "dup-quality" in proposed_standing(rounds, cfg)
            and "dup-quality" not in proposed_standing(rounds, dict(cfg, standing_defers=[{"id": "dup-quality"}])))
        _, aq = with_log("- answered check:Lemma_1.8 (2026-01-01, x): old\n## Answered\n"
                         f"- answered check:Lemma_1.8 (2026-01-05, {os.path.basename(r2)}): newer\n")
        say("a later answer line, in a second `## Answered` section, wins", "check:Lemma_1.8" not in aq)
        tq, aq = with_log(f"- answered proxy:zz (2026-01-05, {os.path.basename(r2)}): confirms the \"[PROXY 2026-01-02, operator]\" choice\n")
        tb_, _ = with_log("")
        base_proxies = tb_.split("## Decisions", 1)[1].count("### Decision taken on your behalf")
        for variant in ('- answered proxy:zz (2026-01-05, R) the approver confirms the "[PROXY 2026-01-02, operator]" choice\n',
                        '- answered proxy:zz (2026-01-05, R) — confirms the “[PROXY 2026-01-02, operator]” choice\n',
                        '- answered proxy:zz (2026-01-05, R): confirms\n  the "[PROXY 2026-01-02, operator]" choice\n'):
            tv_, _ = with_log(variant)
            if tv_.split("## Decisions", 1)[1].count("### Decision taken on your behalf") != base_proxies:
                say(f"an answer quoting a [PROXY] tag in another format is not a new item: {variant[:50]!r}", False)
        say("an answer that quotes a [PROXY] tag is not a new proxy decision",
            not any("confirms_the" in x or "proxy:-_answered" in x for x in aq))
        say("an answer naming no current item is listed as stray", "matches no current item" in tq)
        for variant, label in (
                ("- [PROXY 2026-01-08, operator for D; reversible] drop hV after all\n", "a bare [PROXY] bullet"),
                ("- Answered proxy:yy (2026-01-08, R): [PROXY 2026-01-08, operator] keep\n", "a capitalised answer"),
                ("- answered proxy:yy (2026-01-08, R): keep (a) [PROXY 2026-01-08, operator]\n", "a trailing tag"),
                ("- answered proxy:yy (2026-01-08, R): keep\n  then [PROXY 2026-01-08, operator] chose b\n", "a continuation line")):
            tv_, _ = with_log(variant)
            say(f"a [PROXY] decision under `## Answered` written as {label} is still an item",
                "Decision taken on your behalf: [PROXY 2026-01-08" in tv_.split("## Decisions", 1)[1])
        tv_, _ = with_log('- answered proxy:zz (2026-01-08, R): "[PROXY 2026-01-02, operator]" keep -- confirmed, approver\n')
        say("a confirmation that quotes the tag first is not a new item",
            tv_.split("## Decisions", 1)[1].count("### Decision taken on your behalf") == base_proxies)
        def n_proxies(extra):
            t_, _ = with_log(extra)
            return t_.split("## Decisions", 1)[1].count("### Decision taken on your behalf")
        say("a whole proxy answer written in quotes (a tag not standing elsewhere) is an item",
            n_proxies('- answered question:X (2026-01-08, R): Answer: "[PROXY 2026-01-08, operator for D] skip it"\n') == base_proxies + 1
            and n_proxies('- answered question:X (2026-01-08, R): “[PROXY 2026-01-08, operator] skip it”\n') == base_proxies + 1)
        say("a quoted new decision reusing an existing tag header is still an item",
            n_proxies('- answered question:X (2026-01-08, R): Answer: "[PROXY 2026-01-02, operator] brand new decision Z"\n') == base_proxies + 1)
        say("an undated [PROXY] answer is an item",
            n_proxies("- answered question:X (2026-01-08, R): [PROXY] skip it\n") == base_proxies + 1
            and n_proxies("- answered question:X (2026-01-08, R): keep, [proxy] chose b\n") == base_proxies + 1)
        say("quotes outside `## Answered` are not set aside",
            "## Answered" in log and answered_scan('## Rounds\n- "[PROXY 2026-01-09, op] x"\n') == '## Rounds\n- "[PROXY 2026-01-09, op] x"\n')
        _, aqA = with_log(f"- Answered check:Lemma_1.8 (2026-01-05, {os.path.basename(r2)}): keep\n"
                          f"* answered question:Paper.gt (2026-01-05, {os.path.basename(r2)}): keep\n")
        say("capitalised and `*` answer lines are read", "check:Lemma_1.8" not in aqA and "question:Paper.gt" not in aqA)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + "- answered x (2026-01-05, R): keep (a) [PROXY 2026-01-05, op]\n"
                                                         "- answerd y (2026-01-05, R): typo\n"
                                                         '- answered z (2026-01-05, R): "quoted [PROXY 2026-01-05, op] only"\n')
        try:
            rp_ = record_problems(cfg)
        finally:
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("a [PROXY] tag mid-answer is reported; a quoted one is not; a line that answers nothing is reported",
            sum("mid-answer" in p for p in rp_) == 1 and any("answerd y" in p and "answers nothing" in p for p in rp_))
        # --- question mentions ---
        say("a QUESTION about a Lean name must mention its last component",
            question_mention("Paper.S4.l410b") == "l410b")
        say("a QUESTION about a paper result must mention its number, not a fragment of it",
            question_mention("Theorem 1.5") == "Theorem 1.5" and not mentions("Theorem 1.5", "round 2026-10-12-x5"))
        say("a free-text QUESTION must mention the words before its colon",
            question_mention("Reading choice 14: standing defer reason") == "Reading choice 14")
        # --- check(): sections, comments, the box ---
        F = ("**Paper**: " + "p" * 25 + "\n\n**Lean**: " + "l" * 25 + "\n\n**Evidence**: " + "e" * 25
             + "\n\n**Options**: " + "o" * 25 + "\n\n**Recommendation:** " + "r" * 25 + "\n")
        doc = (f"{BOX_START}\n> - BOXLINE\n\n## Background\nb\n## Decisions\n### D: Lemma 1.1\n<!-- item:a1 -->\n"
               + F.replace("r" * 25, "") + "\n### D: Lemma 1.1\n<!-- item:a2 -->\n" + F)
        say("two sections with the same heading are each checked",
            any("Recommendation missing" in p for p in check(doc, ["a1", "a2"], box_lines=["> - BOXLINE"])))
        doc2 = doc.replace("**Recommendation:** \n", "**Recommendation:** <!-- " + "x" * 30 + " -->\n")
        say("a field holding only an HTML comment is empty",
            any("Recommendation missing" in p for p in check(doc2, ["a1", "a2"], box_lines=["> - BOXLINE"])))
        doc3 = doc.replace("\n### D: Lemma 1.1\n<!-- item:a1 -->", "\n### D: something\n<!-- item:a1 --><!-- Lemma 1.1 -->")
        say("a mention inside an HTML comment does not count",
            any("never mentions" in p for p in check(doc3.replace(F.replace("r" * 25, ""), F), ["a1", "a2"],
                                                     box_lines=["> - BOXLINE"], names={"a1": "Lemma 1.1"})))
        doc4 = doc.replace("> - BOXLINE\n", "> - other\n") + "\n> - BOXLINE\n"
        say("a box entry moved out of the box is refused",
            any("lost a recorded entry" in p for p in check(doc4, ["a1", "a2"], box_lines=["> - BOXLINE"])))
        doc5 = "## Background\nb\n" + doc.replace("\n## Background\nb", "")
        say("the box must come before the background",
            any("before the background" in p for p in check(doc5, ["a1", "a2"], box_lines=["> - BOXLINE"])))
        say("TODO inside an indented code fence is not a placeholder",
            not any("placeholder text" in p for p in check(doc + "\n  ```\n  TODO\n  ```\n", ["a1", "a2"])))
        say("TODO inside an HTML comment is not a placeholder",
            not any("placeholder text" in p for p in check(doc + "\n<!-- TODO -->\n", ["a1", "a2"])))
        say("TODO in prose is a placeholder", any("placeholder text" in p for p in check(doc + "\nTODO\n", ["a1", "a2"])))
        # --- record faults, box filtering, truncation, proxy filters, changes_after failure ---
        vac = os.path.join(rr, "VACUOUS.md")
        open(vac, "w").write("| # | statement | why | status |\n|---|---|---|---|\n"
                             "| 1 | Lemma 4.10 | empty | |\n| 2 | Lemma 9.1 | gone | repaired in abc1234 |\n"
                             "| 3 | Lemma 9.2 | gone | fixed |\n")
        try:
            bl = box_lines(cfg); rp = record_problems(cfg)
            _, av = skeleton(cfg, rounds, r2)
        finally:
            os.remove(vac)
        say("a blank or misspelt VACUOUS status keeps the row open (box and item); only 'repaired in <commit>' hides it",
            "vacuous: Lemma 4.10" in bl and "vacuous: Lemma 9.2" in bl and "vacuous: Lemma 9.1" not in bl
            and any((x.startswith("vacuous:") and "Lemma_4.10" in x) for x in av) and not any("9.1" in x for x in av))
        say("...and a malformed status is reported", any("'fixed'" in p for p in rp) and not any("abc1234" in p for p in rp))
        say("release mode: a malformed VACUOUS status is disclosed (record-format), never in dev",
            {p.code for p in project.split({"mode": "release"}, rp)[1]} == {"record-format"}
            and project.split({"mode": "release"}, rp)[0] == []
            and project.split({"mode": "dev"}, rp)[1] == [])
        dd_ = os.path.join(rr, "stops", "disclosed")
        os.makedirs(dd_)
        json.dump({"fault": "D1", "date": "2026-10-21", "mode": "release", "command": "python3 audits/make_report.py --check",
                   "faults": [{"code": "record-format", "line": "VACUOUS.md row R1: status"}]}, open(os.path.join(dd_, "D1.json"), "w"))
        # B10: a fault of a delivered document's presentation (reader, pdf, render) is README D's, never the box's
        json.dump({"fault": "D2", "date": "2026-10-21", "mode": "release", "command": "python3 audits/make_report.py --check",
                   "faults": [{"code": "render", "line": "DEVIATIONS.md row R2: LaTeX"}]}, open(os.path.join(dd_, "D2.json"), "w"))
        sc_ = os.path.join(rr, "stops", "S1")
        os.makedirs(sc_)
        json.dump({"stop": "S1", "date": "2026-10-21", "command": "python3 audits/integrity.py --check", "exit": 1,
                   "causes": [{"code": "seal-mismatch", "class": "tamper", "line": "FAIL[seal-mismatch] x"}]},
                  open(os.path.join(sc_, "STOP.json"), "w"))
        json.dump({"stop": "S1", "by": "cure", "mode": "release", "attempt": 1, "budget": 2, "cures": ["set-aside"],
                   "text": "set the round aside; a fresh round re-ran it", "rerun": {"exit": 0, "passes": True}},
                  open(os.path.join(sc_, "CLOSED.json"), "w"))
        try:
            bl_d = box_lines(cfg)
        finally:
            shutil.rmtree(os.path.join(rr, "stops"))
        say("approver 2026-10-24: the 'Read this first' box lists no disclosed fault and no release self-cured stop "
            "(the process record, RUN_RECORD.md); they are not decisions",
            not any("D1" in x or "D2" in x for x in bl_d) and not any("S1" in x for x in bl_d))
        say("each box-listed skip and failing route gets a detailed item",
            any((x.startswith("skip:") and "Theorem_1.5" in x) for x in anchors) and any((x.startswith("route:") and "Lemma_1.14" in x) for x in anchors)
            and not any((x.startswith("route:") and "Lemma_2.1" in x) for x in anchors))
        long_r2 = open(os.path.join(r2, "ADOPTED.md")).read()
        open(os.path.join(r2, "ADOPTED.md"), "a").write(
            "\n| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            "| subst | Paper.long | Fail | **QUESTION** | " + "w" * 700 + " |\n"
            + "".join(f"| nv | Paper.u{i} | - | **UNCOVERED** | none |\n" for i in range(205)))
        try:
            tl, _ = skeleton(cfg, rounds, r2)
        finally:
            open(os.path.join(r2, "ADOPTED.md"), "w").write(long_r2)
        say("a long QUESTION reason is cut with a pointer to the full text", "(full text in" in tl and "w" * 700 not in tl)
        say("a long UNCOVERED list is cut with a marker", re.search(r"\((20[56]) UNCOVERED rows\)", tl) is not None and "\n- …" in tl)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(
            log.replace("## Open questions\n", "## Open questions\n- [PROXY 2026-01-07, operator] chose XQZ\n")
            + "## Mechanical failures\n- [PROXY 2026-01-04, operator] RERUNQZ (answered 2026-01-05: fine)\n"
              "## Fresh readers\n- [PROXY 2026-01-06, operator] DISMISSALQZ quoting a proxy\n")
        try:
            tp, ap_ = skeleton(cfg, rounds, r2)
        finally:
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        items_txt = tp.split("## Decisions", 1)[1]
        say("a [PROXY] entry already answered is not an item", "RERUNQZ" not in items_txt)
        say("a [PROXY] quoted under Fresh readers is not an item", "DISMISSALQZ" not in items_txt)
        say("an open question that is a [PROXY] decision is one proxy item, not also an open-question item",
            items_txt.count("### Decision taken on your behalf: [PROXY 2026-01-07") == 1
            and "### Open question: [PROXY 2026-01-07" not in items_txt)
        # --- involvement levels: [DELEGATED] decisions and the delegated Checkpoint C document ---
        say("the involved level keeps today's document: its heading and five fields, no 'Decision taken'",
            text.startswith("# Decisions needed from you") and "Decision taken**" not in text
            and "**Decision taken" not in text)
        TG = "[DELEGATED 2026-01-0{}, operator under hands-off (intake); reversal: {}] "
        dlog = (log.replace("## Rounds\n", "## Rounds\n- QUESTION Paper.gt " + TG.format(4, "re-approve")
                            + "keep m > 0 as in the paper — conservative DGQZ\n")
                .replace("## Open questions\n", "## Open questions\n- " + TG.format(4, "new round")
                         + "round cap reached: stop auditing — budget OPENDGQZ\n")
                + "## Checkpoint C (2026-01-06, delegated)\n- check:Lemma_1.8: " + TG.format(6, "none")
                + "keep CCDGQZ — recommendation\n"
                + "## Answered\n- answered check:Lemma_1.8 (2026-01-06, " + os.path.basename(r2) + "): "
                + TG.format(6, "none") + "keep CCDGQZ — recommendation\n")
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(dlog)
        hcfg = dict(cfg, involvement="hands-off", involvement_answer="(c) hands-off, ANSWERQZ")
        try:
            th, ah = skeleton(cfg, rounds, r2)
            namesh_inv = dict(skeleton.names)
            th, ah = skeleton(hcfg, rounds, r2)
            namesh = dict(skeleton.names)
            decided_h = dict(skeleton.decided)
            dd = delegated_decisions(dlog)
            rp_inv = record_problems(cfg); rp_h = record_problems(hcfg)
        finally:
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        items_h = th.split("## Decisions\n", 1)[1]
        dels = [a for a in ah if a.startswith("delegated:")]
        say("[DELEGATED] decisions in RUN_LOG are items (Open questions included), each must show the tag",
            len(dels) == 2 and "DGQZ" in items_h and "OPENDGQZ" in items_h
            and all(namesh.get(a) == "[DELEGATED" for a in dels))
        say("a [DELEGATED] decision is decided: not also an open question",
            "### Open question: [DELEGATED" not in items_h
            # B11: open questions are one kind section under hands-off; count the items, not headings
            and sum(a.startswith("open:") for a in ah) == 1)
        sec18 = next((b_ for h_, b_ in sections_of(items_h) if "<!-- item:check:Lemma_1.8 -->" in b_), "")
        say("[DELEGATED] answers under Checkpoint C / Answered are not new items; B11: under hands-off the answered "
            "item keeps its section, its Decision taken filled from the logged answer (not 'previously answered')",
            not any("CCDGQZ" in a for a in ah) and "check:Lemma_1.8" in ah
            and ("## Previously answered" not in th or "CCDGQZ" not in th.split("## Previously answered", 1)[1]))
        say("B11: ... and that Decision taken line quotes the logged tag and decision verbatim",
            "**Decision taken:**" in sec18 and TG.format(6, "none") + "keep CCDGQZ — recommendation (logged;" in sec18
            and FILL not in sec18.split("**Decision taken:**", 1)[1])
        say("delegated_decisions counts a Checkpoint C answer written twice once",
            len(dd) == 3 and sum("CCDGQZ" in t for t in dd) == 1)
        say("a [DELEGATED] decision under the involved level is a record problem; under hands-off it is not",
            any("[DELEGATED]" in p_ and "'involved'" in p_ for p_ in rp_inv)
            and not any("[DELEGATED]" in p_ for p_ in rp_h))
        say("a delegated skeleton is headed 'Decisions taken on your behalf', quotes the intake answer and "
            "the disclosure, and every section has a 'Decision taken' field",
            th.startswith("# Decisions taken on your behalf") and "ANSWERQZ" in th
            and DISCLOSURE["hands-off"] in th and th.count("\n**Decision taken:** <!--") == n_sections(th))
        DT = ("[DELEGATED 2026-01-06, operator under hands-off (intake); reversal: none] kept, as the "
              "conservative rule says; to reverse it, ask")
        GL_FILL = "| " + FILL + " >> | " + FILL + " >> | " + FILL + " >> |"
        hfill = re.sub(re.escape(FILL) + r".*?>>", DT, th.replace(GL_FILL, "| kept | conservative rule | none |"), flags=re.S)
        hc = lambda d, lvl="hands-off", ans="(c) hands-off, ANSWERQZ", hd=(): check(
            d, ah, os.path.basename(r2), (), namesh, lvl, ans, hd)
        say("a filled delegated document passes", hc(hfill) == [])
        hcd = lambda d: check(d, ah, os.path.basename(r2), (), namesh, "hands-off", "(c) hands-off, ANSWERQZ",
                              decided=decided_h)
        say("B11 review: ... also with the decided items' logged lines required word for word", hcd(hfill) == [])
        say("B11 review (M2): the prefilled decision of check:Lemma_1.8 rewritten in the document fails",
            "check:Lemma_1.8" in decided_h and any("word for word" in p_ for p_ in hcd(
                hfill.replace("keep CCDGQZ — recommendation (logged;", "dropped CCDGQZ — recommendation (logged;"))))
        k_ = hfill.find("\n**Decision taken:** <!--") + 1
        e_ = hfill.find("\n", k_) if k_ else 0
        no_dt = hfill[:k_] + hfill[e_:]
        say("a delegated document with a section lacking 'Decision taken' fails",
            any("Decision taken missing" in p_ for p_ in hc(no_dt)))
        empty_dt = hfill[:k_] + "**Decision taken**: x" + hfill[e_:]
        say("...and with an empty 'Decision taken' field fails", any("Decision taken missing" in p_ for p_ in hc(empty_dt)))
        # the approval section is first and is not a [DELEGATED] item: its tag comes only from the field
        k1 = max(hfill.find("### Statement approval"), 0)
        e1 = max(hfill.find("\n### ", k1 + 4), k1)
        sec1 = hfill[k1:e1]
        def set_dt(sec, val):
            # the whole field: one line, or (a section of several items) its lines up to the blank line
            return re.sub(r"(\*\*Decision taken:\*\* <!--.*?-->)[ \n].*?(?=\n\n|\Z)", lambda m: m.group(1) + " " + val,
                          sec, flags=re.S)
        untagged = hfill[:k1] + set_dt(sec1, "the operator kept everything, as the conservative rule says; to reverse, ask") + hfill[e1:]
        say("a delegated section whose 'Decision taken' does not show the canonical tag fails",
            any("canonical" in p_ for p_ in hc(untagged)))
        # adversarial (hands-off review, A1): the tag only in the quoted run log, not in the field
        dsec_k = hfill.find("### Other decisions delegated at intake")     # B11: the delegated lines' kind group
        dsec_e = hfill.find("\n### ", dsec_k + 4)
        a1 = hfill[:dsec_k] + set_dt(hfill[dsec_k:dsec_e], "the operator did something sensible here, trust it") + hfill[dsec_e:]
        say("a [DELEGATED] item whose field lacks the tag fails, though the run-log quote shows it",
            dsec_k > 0 and any("canonical" in p_ for p_ in hc(a1)))
        say("a Decision taken field that does not say how to reverse fails",
            any("how to reverse" in p_ for p_ in hc(hfill[:k1] + set_dt(sec1, DT.replace("; to reverse it, ask", ", done")) + hfill[e1:])))
        say("a tag naming another level fails",
            any("canonical" in p_ for p_ in hc(hfill.replace("under hands-off (intake); reversal: none] kept", "under statements-only (intake); reversal: none] kept"))))
        say("a non-canonical tag ('reversible') in the field fails",
            any("canonical" in p_ for p_ in hc(hfill.replace("reversal: none] kept", "reversible] kept"))))
        rec_bad = re.sub(r"(\*\*Recommendation:\*\* ).*", lambda m: m.group(1) + "keep it, which seems best to the operator here", hfill, count=1)
        say("under delegation a Recommendation naming neither the adjudicator nor the conservative rule fails",
            any("Recommendation cites" in p_ for p_ in hc(rec_bad)))
        rec_a7 = re.sub(r"(\*\*Recommendation:\*\* ).*", lambda m: m.group(1) + "I see no adjudicator; my own view: keep", hfill, count=1)
        rec_ok = re.sub(r"(\*\*Recommendation:\*\* ).*", lambda m: m.group(1) + "keep, as the adjudicator decided in 2026-01-02-bbbbbbb/ADOPTED.md", hfill, count=1)
        say("a Recommendation must cite its source: an adjudicator row (round + ADOPTED.md) or 'conservative rule' (review A7)",
            any("Recommendation cites" in p_ for p_ in hc(rec_a7)) and hc(rec_ok) == [])
        na = hfill[:k1] + set_dt(sec1, "Not applicable: the human approved at Checkpoint B") + hfill[e1:]
        appr_a = next((a for a in ah if a.startswith("approval:")), None)
        say("the delegated skeleton's approval item has a versioned approval: anchor", appr_a is not None)
        say("'Not applicable' in 'Decision taken' passes only for an item the human decided at Checkpoint B",
            hc(na, hd={appr_a}) == [] and any("Not applicable' in Decision taken" in p_ for p_ in hc(na)))
        # adversarial A2: "Not applicable" on a [DELEGATED] item
        a2 = hfill[:dsec_k] + set_dt(hfill[dsec_k:dsec_e], "Not applicable: a human decided this one at intake") + hfill[dsec_e:]
        say("'Not applicable' on a [DELEGATED] item fails", any("Not applicable' in Decision taken" in p_ for p_ in hc(a2, hd={appr_a})))
        say("the delegated skeleton opens with an at-a-glance table, one row per decision section (B11: per "
            "matter; it was per item, review of fix-mini2 M1)",
            GLANCE_HEADING in th and th.index(GLANCE_HEADING) < th.index("## Background")
            and th.count(GL_FILL) == n_sections(th) < len(ah))
        mm = re.search(r"^- \*[^\n]*?:\* \[DELEGATED[^\n]*<sub>`([^`]+)`</sub>$", hfill.split("## Decisions", 1)[1], re.M)
        one_dt = hfill.replace(mm.group(0), f"- *item:* kept, as above <sub>`{mm.group(1)}`</sub>") if mm else ""
        say("review of fix-mini2 M1: a merged section whose Decision taken lacks one item's own tagged line fails",
            bool(mm) and any(f"line for `{mm.group(1)}`" in p_ for p_ in hc(one_dt)))
        row_ok = "| kept | conservative rule | none |"
        say("a summary table with an unknown 'Followed' or cost, or missing rows, fails",
            any("'Followed'" in p_ for p_ in hc(hfill.replace(row_ok, "| kept | my judgement | none |", 1)))
            and any("'Reversal cost'" in p_ for p_ in hc(hfill.replace(row_ok, "| kept | conservative rule | reversible |", 1)))
            and any("row(s) for" in p_ for p_ in hc(re.sub(r"\n\|[^\n]*\| kept \| conservative rule \| none \|", "", hfill, count=1))))
        say("a delegated document without the at-a-glance table fails",
            any("no summary table" in p_ for p_ in hc(hfill.replace(GLANCE_HEADING, "## Summary"))))
        say("an unverifiable claim about the order of work ('before any proof was written') fails",
            any("order of work" in p_ for p_ in hc(hfill.replace("## Background", "## Background\n\nThe statements "
                                                                 "were approved before any proof was written.", 1))))
        # a stop the operator closed (stops.py): the cause table and the stop's record are a valid source
        slog = dlog + ("## Stops\n- " + TG.format(7, "none") + "stop S1 closed: STALLQZ killed the lane's stray loop\n")
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(slog)
        try:
            ts, as_ = skeleton(hcfg, rounds, r2)
            names_s = dict(skeleton.names)
        finally:
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("a delegated stop close in RUN_LOG.md is a decision item of the delegated document", "STALLQZ" in ts)
        RS_REC = "per the cause table (stray-loop: mechanical), stops/S1/ (closed by the operator)"
        sfill = re.sub(re.escape(FILL) + r".*?>>", DT, ts.replace(GL_FILL, "| killed | cause table | none |"), flags=re.S)
        sfill = re.sub(r"(\*\*Recommendation:\*\* ).*", lambda m: m.group(1) + "kept, as the conservative rule says", sfill)
        # (the at-a-glance label shows STALLQZ too: find its decision section, after "## Decisions")
        k_s = sfill.rfind("\n### ", 0, sfill.find("STALLQZ", sfill.find("\n## Decisions"))) if "STALLQZ" in sfill else len(sfill)
        e_s = sfill.find("\n### ", k_s + 4)
        e_s = len(sfill) if e_s < 0 else e_s
        sfill = sfill[:k_s] + re.sub(r"(\*\*Recommendation:\*\* ).*", lambda m: m.group(1) + RS_REC, sfill[k_s:e_s]) + sfill[e_s:]
        hs = lambda d, st=("S1",): check(d, as_, os.path.basename(r2), (), names_s, "hands-off",
                                         "(c) hands-off, ANSWERQZ", (), stops=set(st))
        say("decisions.py --check passes a delegated stop close: 'cause table' as Followed, the stop's record "
            "as the Recommendation's source", hs(sfill) == [])
        say("... but a Recommendation naming the cause table without the stop's record fails",
            any("Recommendation cites" in p_ for p_ in hs(sfill.replace(RS_REC, "per the cause table"))))
        say("the cited stop must exist, be closed by the operator, and be this item's own stop",
            any("Recommendation cites" in p_ for p_ in hs(sfill, ()))
            and any("Recommendation cites" in p_ for p_ in hs(sfill.replace("stops/S1/ (closed", "stops/S2/ (closed"), ("S1", "S2"))))
        # re-votes left unsettled, abandoned or not, are items (review M4 / test-run audit)
        rvd = os.path.join(tmp, "rv"); os.makedirs(os.path.join(rvd, "2026-02-01-aaaaaaa", ".abandoned"))
        open(os.path.join(rvd, "2026-02-01-aaaaaaa", "ADOPTED.md"), "w").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            "| substantiveness | `K.isProbDist_single` | Fail | **REVOTE NEEDED** | unused, test lemma |\n"
            "| substantiveness | `K.other` | Fail | **REVOTE NEEDED** | x |\n"
            "| correspondence | `K.thm` | Fail | **ADOPT** | y |\n\n## Re-votes\n\n"
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            "| substantiveness | `K.other` | Pass | **REJECT** | the re-vote passed |\n")
        open(os.path.join(rvd, "2026-02-01-aaaaaaa", ".abandoned", "revote__substantiveness--K.isProbDist_single.json"), "w").write("{}")
        json.dump({"substantiveness": ["K.isProbDist_single", "K.other"], "correspondence": ["K.thm"]},
                  open(os.path.join(rvd, "2026-02-01-aaaaaaa", "TARGET.json"), "w"))
        orv = open_revotes([os.path.join(rvd, "2026-02-01-aaaaaaa")])
        say("open_revotes lists a REVOTE NEEDED row no later row settles (a REJECT with no re-vote run does not), "
            "and marks an abandoned re-vote lane",
            orv == [("2026-02-01-aaaaaaa", "substantiveness", "K.isProbDist_single", "unused, test lemma", True),
                    ("2026-02-01-aaaaaaa", "substantiveness", "K.other", "x", False)])
        adp = os.path.join(r2, "ADOPTED.md"); adp_keep = open(adp).read()
        open(adp, "a").write("\n| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                             "| substantiveness | `Paper.rvq` | Fail | **REVOTE NEEDED** | RVQZ unused |\n")
        try:
            tr_, ar_ = skeleton(cfg, rounds, r2)
        finally:
            open(adp, "w").write(adp_keep)
        say("an unsettled re-vote is an item of the decisions document",
            any(a.startswith("revote:") for a in ar_) and "RVQZ" in tr_)
        apf = os.path.join(rr, "APPROVED_FINGERPRINTS.json")
        ap_keep = open(apf).read()
        json.dump(dict(json.loads(ap_keep), by="human"), open(apf, "w"))
        try:
            skeleton(dict(cfg, involvement="statements-only", involvement_answer="(b)"), rounds, r2)
            hd_s = set(skeleton.human_decided)
            skeleton(hcfg, rounds, r2)
            hd_h = set(skeleton.human_decided)
        finally:
            open(apf, "w").write(ap_keep)
        open(os.path.join(rr, "RUN_LOG.md"), "w").write(
            log + "## Checkpoint C (2026-01-06, delegated)\n- check:Lemma_1.8: " + TG.format(6, "none") + "keep — r\n")
        json.dump(dict(json.loads(ap_keep), by="human"), open(apf, "w"))
        try:
            skeleton(dict(cfg, involvement="statements-only", involvement_answer="(b)"), rounds, r2)
            hd_d = set(skeleton.human_decided)
        finally:
            open(apf, "w").write(ap_keep)
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("an item RUN_LOG records as delegated is never the human's, even under statements-only",
            "check:Lemma_1.8" in hd_s and "check:Lemma_1.8" not in hd_d)
        say("under statements-only with a human approval, the sheet's items are the human's (Not applicable allowed); "
            "under hands-off none are",
            any(a.startswith("approval:") for a in hd_s) and any(a.startswith("check:") for a in hd_s)
            and not any(a.startswith(("delegated:", "question:")) for a in hd_s) and hd_h == set())
        # adversarial A4/A5: a short answer matched anywhere; no answer recorded
        say("the intake answer must appear as the quoted verbatim answer, not anywhere",
            any("verbatim" in p_ for p_ in hc(hfill, ans="c")))
        say("a delegating level with no recorded intake answer fails", any("not recorded" in p_ for p_ in hc(hfill, ans=None)))
        # adversarial B1-B3: counting by anchor; variant tags; both tags on one line
        tg6 = TG.format(6, "none") + "keep as recommended — recommendation"
        b1 = (f"## Checkpoint C (2026-01-06, delegated)\n- check:L1: {tg6}\n- check:L2: {tg6}\n"
              f"## Answered\n- answered check:L1 (2026-01-06, r): {tg6}\n- answered check:L2 (2026-01-06, r): {tg6}\n")
        say("two anchors decided in the same words are two decisions (counted once each)", len(delegated_decisions(b1)) == 2)
        n2 = (f"## Open questions\n- {TG.format(4, 'none')}keep hX as in the paper — conservative\n"
              f"## Checkpoint C (2026-01-06, delegated)\n- delegated:abc: {TG.format(4, 'none')}keep hX as in the paper — conservative\n")
        say("a decision logged without an anchor and re-recorded at C under one is counted once (review N2)",
            len(delegated_decisions(n2)) == 1)
        variants = ["[Delegated 2026-01-04, operator] x", "[DELEGATED  2026-01-04] x", "[DELEGATED] x",
                    "[DELEGATED, 2026-01-04] x", "[delegated 2026-01-04] x",
                    "[DELEGATED 2026-01-04, operator under hands-off (intake); reversible] x"]
        say("every non-canonical [DELEGATED] variant is linted",
            all(tag_problems("## Open questions\n- " + v + "\n") for v in variants)
            and tag_problems("## Open questions\n- " + TG.format(4, "none") + "x\n", "hands-off") == []
            and tag_problems("## Fresh readers\n- quoting [delegated] x\n") == [])
        # trial #11: the run's exact lines. S1: a bare tag mid-sentence in a Rounds line; S2: the same
        # quoted in a Mechanical failures line and in the `## Stops` line stops.py wrote from the cure text
        t11 = ("## Rounds\n- 2026-10-24-7874c0b9ccb: adjudicated e37ca82 (ADOPT 1, REJECT 2, QUESTION 1 decided "
               "[DELEGATED]); reader-fix 1 (no change) 7d575a2eaab\n"
               "## Mechanical failures\n- 2026-10-24, round 2026-10-24-full-7874c0b9ccb: the adjudicator stopped at "
               "step A (Phase 0 RED[report]: a bare '[DELEGATED]' in my own Rounds line of RUN_LOG.md); stop S1 "
               "opened, line reworded, closed --cured\n- see `[DELEGATED]` in RUN.md\n"
               "- the cause, `FAIL[report] RUN_LOG.md: [DELEGATED] is not a canonical tag`, was mine\n"
               "## Stops\n- stop S1 self-cured (release mode, not a human stop; attempt 1 of 2; rerun; `python3 "
               "audits/make_report.py --project minipaper3 --check` passes): reworded my own RUN_LOG.md Rounds "
               "line: bare '[DELEGATED]' in prose changed to 'as delegated' (meaning unchanged; not a decision line)\n"
               "- stop S3 self-cured (release mode, not a human stop; attempt 1 of 2; rerun; `x` passes): "
               "[DELEGATED] and \"[PROXY]\" mentioned\n"
               "- stop S2 (2026-10-24, the human's answer, verbatim: \"[PROXY] fine\")\n")
        say("trial #11: a bare [DELEGATED] mentioned mid-sentence, quoted, in a code span or in a stops.py "
            "`## Stops` line is no tag problem (S1, S2)", tag_problems(t11, "hands-off") == [])
        forged = ["## Rounds\n- [DELEGATED] keep hX\n", "## Open questions\n- check:L1: [DELEGATED] keep hX\n",
                  "## Open questions\n- check:L1: '[Delegated] keep hX'\n",
                  "## Rounds\n- r1: kept hX [DELEGATED 2026-10-24] as recommended\n",
                  "## Rounds\n- r1: kept hX `[DELEGATED 2026-10-24, operator]`\n",
                  "## Stops\n- stop S1 self-cured (x; `y` passes): [DELEGATED 2026-10-24] keep hX\n",
                  "## Stops\n- [DELEGATED] keep hX\n"]
        say("trial #11: a structured (or dated, anywhere) non-canonical [DELEGATED] line is still linted",
            all(tag_problems(f) for f in forged))
        say("a canonical tag naming another level than the run's is linted",
            tag_problems("## Open questions\n- " + TG.format(4, "none") + "x\n", "statements-only") != [])
        both = "## Open questions\n- [PROXY 2026-01-04] " + TG.format(4, "none") + "x — y\n"
        say("both tags on one line are linted", any("both" in p_ for p_ in tag_problems(both, "hands-off")))
        say("a [PROXY] decision under a delegating level is a record problem",
            any("[PROXY] decision under the hands-off" in p_ for p_ in rp_h)
            and not any("[PROXY] decision under" in p_ for p_ in rp_inv))
        say("a delegated document without the 'Decisions taken on your behalf' heading fails",
            any("headed" in p_ for p_ in hc(hfill.replace("# Decisions taken on your behalf", "# Decisions needed from you", 1))))
        say("a delegated document that does not quote the intake answer fails",
            any("verbatim" in p_ for p_ in hc(hfill.replace("ANSWERQZ", "answer"))))
        say("a delegated document without the disclosure sentence fails",
            any("disclosure" in p_ for p_ in hc(hfill.replace(DISCLOSURE["hands-off"], "Some decisions follow."))))
        say("statements-only has its own disclosure; a hands-off document does not pass as statements-only",
            any("disclosure" in p_ for p_ in hc(hfill, "statements-only")))
        say("the involved level does not require 'Decision taken' (today's documents pass unchanged)",
            check(filled, anchors, os.path.basename(r2)) == []
            and check(filled, anchors, os.path.basename(r2), level="involved") == [])
        say("a [DELEGATED] item's section that loses its tag fails even under the involved level",
            mentions("[DELEGATED", "[delegated 2026] x") and not mentions("[DELEGATED", "delegated x")
            and bool(dels) and namesh_inv.get(dels[0]) == "[DELEGATED")
        cal = project.changes_after_last_audit
        project.changes_after_last_audit = lambda c, r: {"problem": "git failed", "commits": [], "dirty": [], "round": "x", "commit": "y"}
        try:
            ca_lines = _real_changes_after(cfg, rounds)
        finally:
            project.changes_after_last_audit = cal
        say("a git failure in changes_after is an UNKNOWN item, never silence", ca_lines == ["UNKNOWN: git failed"])
        # main(): --write / --check / refusal to overwrite / --round
        saved_sel = project.select
        project.select = lambda name=None: (cfg, "stub")
        saved_order = project.order_rounds
        project.order_rounds = lambda rs, repo: sorted(rs)
        try:
            import io, contextlib
            def run(*argv):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    try:
                        rc = main(list(argv))
                    except SystemExit as e:      # argparse refusals
                        rc = e.code
                return rc, buf.getvalue()
            rc, _ = run("--write")
            say("main --write writes the skeleton", rc == 0 and os.path.exists(os.path.join(rr, "DECISIONS.md")))
            rc, out = run("--write")
            say("main --write refuses to overwrite the writer's work", rc != 0 and "exists" in out)
            rc, _ = run("--check")
            say("main --check refuses the unfilled skeleton", rc == 1)
            dm = os.path.join(rr, "DECISIONS.md")
            filled_doc = re.sub(re.escape(FILL) + r".*?>>", "x" * 25, open(dm).read(), flags=re.S)
            open(dm, "w").write(filled_doc)
            rc, out = run("--check")
            say("main --check passes a filled document", rc == 0)
            dm2 = os.path.join(tmp, "elsewhere.md")
            rc, out = run("--write", "--out", dm2)
            say("--write --out writes a draft elsewhere", rc == 0 and os.path.exists(dm2))
            rc, out = run("--check", "--file", dm2)
            say("--check --file checks that draft (unfilled: refused)", rc == 1)
            good = open(dm).read()
            for what, bad in (
                    ("a wrong round tag", re.sub(r"decisions-round: \S+", "decisions-round: R-other", good)),
                    ("a deleted box line", good.replace("> - defect 1", "> - (removed)", 1)),
                    ("a section that lacks its mention", good.replace("SECOND", "S-E-C-O-N-D")
                     .replace("Lemma 1.8", "the lemma"))):
                open(dm, "w").write(bad)
                rc, out = run("--check")
                say(f"main --check refuses {what}", rc == 1)
            open(dm, "w").write(good)
            saved_dm = open(dm).read(); os.remove(dm)
            rc, out = run("--write", "--file", dm2)
            say("--file with --write is refused (it would write into the rounds dir)",
                rc == 2 and not os.path.exists(dm))
            open(dm, "w").write(saved_dm)
            rc, out = run("--check", "--out", dm2)
            say("--out with --check is refused", rc == 2)
            vac = os.path.join(rr, "VACUOUS.md")
            open(vac, "w").write("| # | statement | status |\n|---|---|---|\n| 1 | Lemma 4.10 | fixed |\n")
            try:
                rc, out = run("--check")
            finally:
                os.remove(vac)
            say("main --check reports a malformed VACUOUS status", rc == 1 and "neither 'open'" in out)
            rc, out = run("--check", "--round", os.path.basename(r1))
            say("an older --round is refused without --allow-older", rc != 0 and "not the newest" in out)
            project.select = lambda name=None: (dict(cfg, involvement="hands-free"), "stub")
            rc, out = run("--check")
            say("main refuses an invalid involvement level", rc == 2 and "involvement" in out)
            project.select = lambda name=None: (dict(cfg, involvement="hands-off", involvement_answer="ANS-CLI"), "stub")
            rc, out = run("--check")
            say("main --check under hands-off refuses an involved-style document", rc == 1 and "Decision taken" in out)
        finally:
            project.select, project.order_rounds = saved_sel, saved_order
    finally:
        project.REPO, g["changes_after"] = saved


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

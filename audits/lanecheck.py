#!/usr/bin/env python3
"""Check a round's lanes after they return and before adjudication (RUN.md Stage 4, step 3).

WHY THIS EXISTS.  In a test run, rules written into the lane prompts were broken anyway:
lanes read earlier rounds' records four times (one aborted itself on noticing), left `until !
pgrep -f ...` loops running five times (the pattern matches its own command line, so the loop
never exits), wrote files into the repository root, and cited probe files that were never
written. A rule in a prompt is advice; this script makes each of those visible before the
adjudicator reads the verdicts, and the adjudication commit refuses until each is settled.

  python3 audits/lanecheck.py --round R [--project NAME] [--kill]
  python3 audits/lanecheck.py --round R --settled     (the adjudication settles every flag?)
  python3 audits/lanecheck.py --selftest

Each line is KIND[code] (codes: project.CAUSES). Per lane verdict file `<round>/<lane>.json`,
`<lane>@<n>.json` and `revote/<lane>--<item>.json`:
  1. independence. A MENTION of a record file lanes may not read (ADOPTED.md, RUN_LOG.md,
     TARGET.json, SIGNOFF.*, REPORT.*, SKIPPED.md, ...), or of another round by its name (or "round <hash>"), is
     NOTE[independence]: a name in a finding's text ("record in ADOPTED.md that ...") is not
     necessarily a read (live run, 2026-10-19, S1). The adjudicator reads the context and either
     clears it in one line of ADOPTED.md ("CLEARED <lane file>: <reason>") or re-votes the whole
     lane. A PATH into another round ("<round>/ADOPTED.md") or into another lane's verdict or probe
     directory is NOTE[independence-path]: near-certain evidence of a read, so it forces a re-vote
     and no clearance settles it. A RE-VOTE lane runs while its own round's ADOPTED.md exists: a
     path into its own round (other than its own files) is NOTE[independence-path] too;
  2. lane faults, NOTE[lane-fault]: a cited probe that does not exist next to the verdict (a
     re-vote's under `revote/`), and what the seal recorded -- no probe manifest, a listed probe
     missing or changed before the seal, files the manifest does not list; and a verdict file that
     breaks the verdict schema lanes are given (not one JSON object, `verdicts` not a list, an entry
     not an object, with no item, or a verdict other than Pass/Fail/Ambiguous/NotDoneYet): it judged
     nothing, so every item it names (the whole lane when an entry names none) needs a re-vote, and a
     re-vote lane's row stays open for the human (R3g). The evidence they touch is void: the
     adjudicator re-votes, never rejects on it;
  3. sealed evidence: the verdict or a probe changed, removed or added after the seal commit is
     PROBLEM[evidence-after-seal] (tampering: a stop; in release a self-cure, the lane re-voted:
     project.RELEASE kind redo; in dev the human's);
  (a re-vote lane set aside by `stops.py set-aside --lane`, `<round>/.abandoned/`, is not checked;
and for the round as a whole:
  4. authentication: every issued lane validates against its token commitment and seal;
  5. stray files: untracked files in the Lean repository outside the audits directory;
  6. stray processes: this user's processes running a polling loop (`until`/`while` with `sleep`
     or `pgrep`); `--kill` ends them.
Exit 1 if anything is found that is not a NOTE. `--settled` exits 1 unless ADOPTED.md settles
every NOTE: a clearance or a whole-lane REVOTE NEEDED row per independence NOTE, a whole-lane
re-vote per independence-path NOTE, a REVOTE NEEDED row per item a lane fault touches; a re-vote
lane's own NOTE (an independence one included: no clearance) leaves its row open for the human
("LEFT OPEN <lane file>: <reason>"), never a second re-vote. A decision after a REVOTE NEEDED row
needs the re-vote itself: sealed, decided in an "adjudicate R revotes" commit; a re-vote lane set
aside never counts (its item stays open for the human).
"""
import sys
sys.dont_write_bytecode = True
import argparse, collections, glob, json, os, re, shutil, subprocess, tempfile, time

import project

NOTE = "NOTE["          # printed, never counted: the adjudicator settles it
ROUND_NAME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40}\b")
# another round named by its commit hash ("as decided in round 0b23c87"): a mention (hashes also
# name Lean commits a lane may legitimately cite), so NOTE[independence], clearable (ROUND3 CONS M1)
ROUND_HASH_RE = re.compile(r"\bround\s+([0-9a-f]{7,40})\b", re.I)
ROUND_PATH_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40})/")
RECORD_RE = re.compile(r"\b(ADOPTED\.md|RUN_LOG\.md|TARGET\.json|SIGNOFF\.(?:md|json|pdf|tex)|REPORT\.(?:md|pdf|tex)"
                       r"|SKIPPED\.md|DEVIATIONS\.md|PAPER_DEFECTS\.md|VACUOUS\.md|AUTHOR_NOTES\.md|OUTCOMES\.md"
                       r"|readers/|resolutions/|stops/)", re.I)
WHOLE_LANE = "(whole lane)"     # the item of a whole-lane re-vote row in ADOPTED.md
CLEARED_RE = re.compile(r"^\s*(?:[-*]\s*)?CLEARED\s+(\S+?)\s*:\s*(\S.*)$", re.M)
LEFT_OPEN_RE = re.compile(r"^\s*(?:[-*]\s*)?LEFT OPEN\s+(\S+?)\s*:\s*(\S.*)$", re.M)
# JUDGEMENT-SCAN item 1 (coordinator 2026-10-26): a contradiction-step quote the text matcher does not find in the .tex
# is a FLAG (NOTE[quote-unmatched]), never a decision: LaTeX macros and formatting the normaliser cannot undo hide real
# passages (the live L-infinity run: a re-vote's own quote tripped it again, six items left open). The adjudicator reads
# the paper and rules, once, in ADOPTED.md:
#   QUOTE RULED <lane file> | <item> | in the paper at tex l.<N>[: <note>]
#   QUOTE RULED <lane file> | <item> | not in the paper: <why>
# "in the paper" settles the flag (no re-vote, and the re-vote's quote is never matched again); "not in the paper" is
# then a REVOTE NEEDED row for the item (a re-vote lane: LEFT OPEN, never a second re-vote).
QUOTE_RULED_RE = re.compile(r"^\s*(?:[-*]\s*)?QUOTE RULED\s+(\S+?\.json)\s*\|\s*(.+?)\s*\|\s*"
                            r"(in the paper at tex l\.\s*\d+.*|not in the paper\s*:\s*\S.*)$", re.M)
QUOTE_FLAG_RE = re.compile(r"NOTE\[quote-unmatched\] \S+: (.+?) is passed as a CONTRADICTION STEP quoting")
# a probe path ends at its file extension (lanes sometimes run paths together without a space)
PROBE_RE = re.compile(r"([A-Za-z0-9_@.-]+\.probes/[^\s\"'`,;()]+?\.(?:lean|py|txt|out|log|json|sh|md)(?:\.(?:txt|log|out))?)(?!\w)(?!\.\w)")
# a shell running a polling loop -- the command line of `bash -c 'until ! pgrep -f X; do sleep 5; done'`
LOOP_RE = re.compile(r"^(?:\S*/)?(?:ba|z|da)?sh\b.*\b(?:until|while)\b.*\b(?:sleep|pgrep)\b")


def is_abandoned_lane(round_dir, rel):
    """A re-vote lane set aside (stops.py set-aside --lane): its files are record,
    its row stays open for the human, and no check reads it as a lane."""
    return os.path.exists(os.path.join(round_dir, ".abandoned", rel[:-len(".json")].replace("/", "__") + ".json"))


def lane_files(round_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(round_dir, "*.json")) + glob.glob(os.path.join(round_dir, "revote", "*.json"))):
        b = os.path.basename(p)
        if b in RECORD_JSON or b.startswith("APPROVED"):
            continue
        if is_abandoned_lane(round_dir, os.path.relpath(p, round_dir)):
            continue
        out.append(p)
    return out


SCHEMA_VERDICTS = ("Pass", "Fail", "Ambiguous", "NotDoneYet")     # AUDIT_PROTOCOL, the verdict schema
SCHEMA_FAULT = "does not follow the verdict schema"


def schema_faults(text):
    """[violation] of the verdict schema lanes are given (AUDIT_PROTOCOL, common rule 6) in a verdict
    file's text (R3g): the file is one JSON object, its `verdicts` (when present) a list, and every entry
    a dict with a non-empty string `item` and a `verdict` of Pass, Fail, Ambiguous or NotDoneYet. A file
    with a violation is a lane fault: none of its entries judged anything (narrow X4: one valid entry
    beside junk entries licensed a decision)."""
    try:
        doc = json.loads(text)
    except ValueError:
        return ["not JSON"]
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    v = doc.get("verdicts", [])
    if not isinstance(v, list):
        return ["`verdicts` is not a list"]
    out = []
    for i, e in enumerate(v):
        if not isinstance(e, dict):
            out.append(f"entry {i} is not an object ({json.dumps(e)[:40]})")
        elif not isinstance(e.get("item"), str) or not clean_cell(e["item"]):
            out.append(f"entry {i} has no item")
        elif e.get("verdict") not in SCHEMA_VERDICTS:
            out.append(f"entry {i} ({clean_cell(e['item'])}) has verdict {json.dumps(e.get('verdict'))[:40]}, none of "
                       + ", ".join(SCHEMA_VERDICTS))
    return out


def check_lane(path, round_dir):
    """[flag] for one lane verdict file, each "NOTE[<code>] <file>: <what>" (see the docstring)."""
    probs, rel = [], os.path.relpath(path, round_dir)
    own = os.path.basename(path)[:-len(".json")]
    text = open(path, encoding="utf-8", errors="replace").read()
    bad = schema_faults(text)
    if bad:
        probs.append(f"NOTE[lane-fault] {rel}: {SCHEMA_FAULT} ({'; '.join(bad[:3])}): none of its entries "
                     f"judged anything (the adjudicator re-votes every item of the lane; a re-vote lane's row is "
                     f"left open for the human)")
    this = os.path.basename(round_dir)
    paths = sorted({r for r in ROUND_PATH_RE.findall(text) if r != this})
    if paths:
        probs.append(f"NOTE[independence-path] {rel}: cites a path into another round ({', '.join(paths[:3])}/...): "
                     f"near-certain evidence that it read that round's record; the lane is re-voted (no clearance)")
    if rel.startswith("revote/"):
        # a re-vote runs while its own round's ADOPTED.md (the adjudicator's reasons) and the original
        # lane's files exist: a path into its own round, other than its own files, is anchoring
        # (ROUND3 H3/T4), not a harmless pointer
        mine = os.path.basename(path)[:-len(".json")]
        own_round = sorted({m for m in re.findall(rf"(?<![\w-]){re.escape(this)}/([^\s\"'`,;()]+)", text)
                            if not m.startswith(f"revote/{mine}")})
        if own_round:
            probs.append(f"NOTE[independence-path] {rel}: a re-vote lane cites a path into its own round's record "
                         f"({', '.join(own_round[:3])}): it may have read the adjudicator's reasons; its row is left "
                         f"open for the human (no clearance)")
    names = sorted({r for r in ROUND_NAME_RE.findall(text) if r != this} - set(paths))
    own_hash = this.rsplit("-", 1)[-1].lower()
    names += sorted({f"round {h}" for h in (x.lower() for x in ROUND_HASH_RE.findall(text))
                     if not (own_hash.startswith(h) or h.startswith(own_hash))})
    rec = sorted(set(RECORD_RE.findall(text)))
    if rec or names:
        probs.append(f"NOTE[independence] {rel}: mentions " + "; ".join(
            ([f"record files lanes may not read ({', '.join(rec[:4])})"] if rec else [])
            + ([f"other rounds ({', '.join(names[:3])})"] if names else []))
            + ": the adjudicator clears it in one line of ADOPTED.md or re-votes the lane")
    siblings = sorted({os.path.basename(p) for p in lane_files(round_dir)} - {os.path.basename(path)})
    cited = [b for b in siblings if re.search(rf"(?<![\w@.-]){re.escape(b)}(?!\w)", text)]
    base = os.path.dirname(path)    # a lane's probes sit next to its verdict (revote/ for a re-vote)
    for m in sorted(set(PROBE_RE.findall(text))):
        rel_p = m.rstrip(".:")      # PROBE_RE stops at the extension, so `file.lean:90-95` is just the file
        if rel_p.split(".probes/", 1)[0] != own:
            # another lane's probe directory (lanecheck globbed the whole round before, so this
            # passed: RULINGS A2/A3, condition 4)
            cited.append(rel_p.split("/", 1)[0])
            continue
        # a pattern (del_*.lean, del_<decl>.lean, a|b.lean) must match at least one file
        alts = []
        if "|" in rel_p:
            head, _, tail = rel_p.rpartition("/")
            stem = tail.split("|")
            ext = os.path.splitext(stem[-1])[1]
            prefix = stem[0].rsplit("_", 1)[0] + "_" if "_" in stem[0] else ""
            alts = [os.path.join(head, (x if i == 0 else (x if x.startswith(prefix) else prefix + x)).replace(ext, "") + ext)
                    for i, x in enumerate(stem)]
        pats = [re.sub(r"<[^>]*>", "*", x) for x in (alts or [rel_p])]
        if all(glob.glob(os.path.join(base, x)) for x in pats):
            continue
        probs.append(f"NOTE[lane-fault] {rel}: cites probe {rel_p}, which does not exist next to its verdict: the "
                     f"evidence it was cited for is void (the adjudicator re-votes, never rejects on it)")
    if cited:
        probs.append(f"NOTE[independence-path] {rel}: cites another lane's verdict or probe directory "
                     f"({', '.join(sorted(set(cited))[:3])}): the lane is re-voted (no clearance)")
    if not bad:
        probs += contradiction_faults(path)
    return probs


def counts(p):
    return not p.startswith(NOTE)


def lane_problems(rd, p):
    """Every flag of one lane file: its own (check_lane), the lane faults its seal recorded, and its
    sealed evidence changed after the seal (PROBLEM[evidence-after-seal])."""
    import lane_auth
    rel = os.path.relpath(p, rd)
    return (check_lane(p, rd)
            + [f"NOTE[lane-fault] {x.split('] ', 1)[1]}" for x in lane_auth.seal_faults(p)]
            + [f"PROBLEM[evidence-after-seal] {x.split('] ', 1)[1]}" for x in lane_auth.after_seal(p)])


def flag_code(flag):
    m = re.match(r"^[A-Z]+\[([a-z-]+)\]", flag)
    return m.group(1) if m else None


def flag_lane(flag):
    """The lane file (relative to the round) a flag is about."""
    m = re.match(r"^[A-Z]+\[[a-z-]+\] (\S+?):", flag)
    return m.group(1) if m else None


# --- THE reader of ADOPTED.md's decision rows (R3e) -----------------------------------------------
# Every consumer -- the settle check (adjudication commit, integrity --check, make_report --check),
# the re-vote rules, the carried-item check (stops.py), the open re-vote list and the question list
# (decisions.py), and audit_coverage.read_adopted for a current-format record (R3f) -- reads decision
# rows through `decision_rows` and nothing else. A row is read
# STRICTLY: its lane cell is exactly one lane name of the round and its item cell exactly one scope
# item of the round or declared item of the project (its index rows and declarations, R3f: an UNCOVERED
# row for a NotDoneYet entry or a STALE PASS), after stripping only surrounding whitespace, markdown
# emphasis and backticks.
# Any other row is refused by the settle check and never decides or settles anything: no case
# folding, no ".json" or "-lane" guessing (NARROW H1: a row of another lane, or a lane cell spelled
# differently, removed an open re-vote from the human's list while every settle check ignored it).

Row = collections.namedtuple("Row", "lane item decision verdict reason base problem")
OUTCOMES_LANE = "outcomes"      # AUDIT_PROTOCOL step 4 B': the outcome check's rows
RECORD_JSON = ("TARGET.json", "FINGERPRINTS.json", "SIGNOFF.json", "INFORMAL.json", "ABANDONED.json")
_EDGE_RE = re.compile(r"^[\s*_`]+|[\s*_`]+$")


def clean_cell(c):
    """A cell with only its surrounding whitespace, markdown emphasis (* _) and backticks removed."""
    return _EDGE_RE.sub("", str(c))


def _target(rd):
    try:
        d = json.load(open(os.path.join(rd, "TARGET.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: [str(x) for x in v] for k, v in d.items() if isinstance(v, list)} if isinstance(d, dict) else None


def round_names(rd):
    """(lanes, items, earlier items) a decision row of round `rd` may name. Lanes: TARGET.json's, every
    lane file of the round without .json (batch parts `<lane>@<k>`, re-vote lanes `revote/<lane>--<x>`,
    set-aside ones included), the lanes of carried-forward items, and `outcomes`. Items: TARGET.json's,
    the carried-forward items, `(whole lane)` and every declared item of the project (project_items:
    its index rows and declarations, R3f). Earlier items: every other round's TARGET.json items (an
    `outcomes` row checks an earlier round's ADOPT row)."""
    import stops
    lanes, items, earlier = set(), {WHOLE_LANE}, set()
    t = _target(rd) or {}
    for k, v in t.items():
        lanes.add(k); items.update(v)
    for p in glob.glob(os.path.join(rd, "*.json")) + glob.glob(os.path.join(rd, "revote", "*.json")):
        if os.path.basename(p) not in RECORD_JSON and not os.path.basename(p).startswith("APPROVED"):
            lanes.add(os.path.relpath(p, rd)[:-len(".json")])
    rds = os.path.dirname(rd)
    for m, _, _ in stops.markers(rds):
        for c in (stops.load(m) or {}).get("carried") or []:
            if c.get("lane"):
                lanes.add(re.sub(r"\.json$", "", os.path.basename(str(c["lane"]))).split("--")[0].split("@")[0])
            if c.get("item"):
                items.add(str(c["item"]))
    for o in glob.glob(os.path.join(rds, "*", "TARGET.json")):
        if os.path.dirname(o) != rd:
            for v in (_target(os.path.dirname(o)) or {}).values():
                earlier.update(v)
    lanes.add(OUTCOMES_LANE)
    return lanes, items | project_items(rds), earlier


def _project_configs(rds):
    """[(repo, config)] of every project whose rounds dir is `rds`: the configs under
    <ancestor>/audits/projects/ (project.PROJECTS of the apparatus beside the record) of the nearest
    ancestor of `rds` that has one naming it as its rounds_dir."""
    want, d = os.path.realpath(rds), os.path.dirname(os.path.realpath(rds))
    while True:
        hits = []
        for f in sorted(glob.glob(os.path.join(d, "audits", "projects", "*.json"))):
            try:
                cfg = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(cfg, dict) and isinstance(cfg.get("rounds_dir"), str) and \
                    os.path.realpath(os.path.join(d, cfg["rounds_dir"])) == want:
                hits.append((d, cfg))
        if hits or d == os.path.dirname(d):
            return hits
        d = os.path.dirname(d)


_PROJECT_ITEMS = {}


def project_items(rds):
    """Every declared item of the project whose rounds dir is `rds` (R3f): the labels of its index
    table (scope.index_rows of the config's index file: the rows make_report's index check reads and a
    paper-faithfulness lane is scoped by), the qualified names of its declarations (scope.parse_decls
    over lean_files: the names TARGET.json and fingerprint.py key), and every name a round's
    FINGERPRINTS.json keys (a STALE PASS may be about a declaration since renamed or deleted). A decision
    row may name these beyond its round's scope: an UNCOVERED row for a NotDoneYet entry of an earlier
    round, or for a STALE PASS (AUDIT_PROTOCOL step E). Still exact names; empty without a config."""
    import scope
    cfgs = _project_configs(rds)
    fps = sorted(glob.glob(os.path.join(rds, "*", "FINGERPRINTS.json")))
    srcs = sorted({os.path.join(repo, f) for repo, cfg in cfgs
                   for f in [project.index_file(cfg)] + list(cfg.get("lean_files") or []) if isinstance(f, str)})
    paths = srcs + fps
    key = tuple((p, os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in paths if os.path.exists(p))
    if key in _PROJECT_ITEMS:
        return _PROJECT_ITEMS[key]
    out = set()
    for repo, cfg in cfgs:
        ix = project.index_file(cfg)
        lfs = [f for f in cfg.get("lean_files") or [] if isinstance(f, str)]
        for f in ([ix] if isinstance(ix, str) else []) + lfs:
            try:
                text = open(os.path.join(repo, f), encoding="utf-8").read()
            except OSError:
                continue
            if f == ix:
                out.update(label for label, _ in scope.index_rows(text))
            if f in lfs:
                out.update(q for q in scope.parse_decls(text) if q != "_unnamed")
    for fp in fps:
        try:
            d = json.load(open(fp, encoding="utf-8")).get("fingerprints")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(d, dict):
            out.update(str(k) for k in d)
    _PROJECT_ITEMS[key] = frozenset(out)
    return _PROJECT_ITEMS[key]


def _name(cell, names):
    """(the one name `cell` is, or None; why not): exact, else equal after clean_cell on both sides."""
    if cell.strip() in names:
        return cell.strip(), None
    hits = sorted(n for n in names if clean_cell(n) == clean_cell(cell))
    if len(hits) == 1:
        return hits[0], None
    return None, ("it is more than one name (" + ", ".join(hits[:4]) + ")" if hits else "")


def decision_rows(rd, text=None):
    """[Row] of every row of every decision table (a header with `item` and `decision`) of round `rd`'s
    ADOPTED.md (or of `text`), in order: lane and item as the round names them, the decision
    (project.decision_of; "?<cell>" when the cell records none), the verdict and reason cells, the
    lane's base (lane_base) and `problem`: None, or why the row names no lane or no item of the round
    exactly (the settle check refuses it; no other check reads it as deciding anything)."""
    import decisions
    if text is None:
        ap = os.path.join(rd, "ADOPTED.md")
        text = open(ap, encoding="utf-8").read() if os.path.exists(ap) else ""
    names, out, R = None, [], os.path.basename(rd)
    for header, cells in decisions.table_rows(text):
        if "decision" not in header or "item" not in header:
            continue
        if names is None:
            names = round_names(rd)
        lanes, items, earlier = names
        cell = lambda h: cells[header.index(h)] if h in header and header.index(h) < len(cells) else ""
        raw_l, raw_i = cell("lane"), cell("item")
        dec = project.decision_of(cell("decision")) or "?" + cell("decision").strip()
        lane, why_l = _name(raw_l, lanes)
        item, why_i = _name(raw_i, items | (earlier if lane == OUTCOMES_LANE else set()))
        problem = None
        if len(cells) < len(header):
            problem = (f"the row {' | '.join(cells)[:80]!r} has {len(cells)} cells where its table has "
                       f"{len(header)}: every row of a decision table fills every column")
        elif "lane" not in header:
            problem = f"its decision table has no lane column: write | lane | item | verdict | decision | reason |"
        elif lane is None:
            problem = (f"the lane cell {raw_l!r} is not a lane of round {R}" + (f": {why_l}" if why_l else "")
                       + f"; write exactly one of {', '.join(sorted(lanes))} (no other spelling is read)")
        elif item is None:
            problem = (f"the item cell {raw_i!r} (lane {lane}) is not a scope item of round {R}"
                       + (f": {why_i}" if why_i else "") + "; copy the item exactly as TARGET.json, the "
                       f"lane's JSON or the project's index names it (no other spelling is read)")
        out.append(Row(lane or clean_cell(raw_l), item or clean_cell(raw_i), dec, clean_cell(cell("verdict")),
                       cells[-1], lane_base(lane or clean_cell(raw_l)), problem))
    return out


def valid_rows(rd, text=None):
    """decision_rows' rows that name a lane and an item of the round (the only rows that decide)."""
    return [r for r in decision_rows(rd, text) if r.problem is None]


DECIDED_RE = re.compile(r"(ADOPT|REJECT|DEFER)\b")


def lane_base(lane):
    """The reviewer lane a row or file names: `correspondence` for correspondence@2, revote/x--N.b, ..."""
    return os.path.basename(str(lane)).split("--")[0].split("@")[0]


def _slug(item):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", item)[:80]


VERDICTS = ("Pass", "Fail", "Ambiguous")


def lane_entries(doc):
    """[entry dict] of a lane verdict document (its `verdicts` list, the verdict schema), or None when
    `doc` is no verdict document (not a dict, or no `verdicts` list). The one reader of that key: every
    gate that reads lane entries goes through it (make_report's F10 check included)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("verdicts"), list):
        return None
    return [e for e in doc["verdicts"] if isinstance(e, dict)]


def judged_items(doc):
    """{item (clean_cell): verdict} a verdict document judged: an entry counts only when its verdict is
    exactly Pass, Fail or Ambiguous and its item has exactly one entry in the document (R3e M1: an entry
    with no verdict, an empty or unknown one, or two entries for one item never judged the item)."""
    ents = lane_entries(doc) or []
    n = collections.Counter(clean_cell(e.get("item", "")) for e in ents)
    return {clean_cell(e.get("item", "")): e.get("verdict") for e in ents
            if e.get("verdict") in VERDICTS and n[clean_cell(e.get("item", ""))] == 1}


def _sealed_items(c):
    """The items re-vote lane file `c`'s SEALED verdict judged (judged_items): the file's bytes must be
    the ones its seal's digest covers; None when they are not (not sealed, or changed after it)."""
    import lane_auth
    s_ = lane_auth.sealed_doc(c)
    try:
        data = open(c, "rb").read()
        if not s_ or lane_auth.sha(data) != s_.get("sha256"):
            return None
        doc = json.loads(data)
    except (OSError, ValueError):
        return None
    # R3g: a verdict that breaks the schema is a lane fault and judged nothing
    return {} if schema_faults(data.decode("utf-8", "replace")) else judged_items(doc)


def _part(c):
    """The batch part k of a whole-lane re-vote file revote/<lane>--ALL.k.json, "" for --ALL, None for an
    item re-vote."""
    tail = os.path.basename(c)[:-len(".json")].split("--", 1)[-1]
    return None if not tail.startswith("ALL") else tail[len("ALL."):] if tail.startswith("ALL.") else ""


def _covers(rd, c, item):
    """Does re-vote lane file `c` re-judge `item`? An item re-vote and --ALL do; --ALL.k does for the items
    of lane part `<lane>@k` (that part's verdict, or the re-vote's own), and when neither can be read
    (R3e L2: part 2's set-aside --ALL.2 is not part 1's re-vote)."""
    k = _part(c)
    if not k or item == WHOLE_LANE:
        return True
    seen, readable = set(), False
    for f in (os.path.join(rd, f"{lane_base(c)}@{k}.json"), c):
        try:
            doc = json.load(open(f, encoding="utf-8"))
            readable = True
            seen |= {clean_cell(e.get("item", "")) for e in lane_entries(doc) or []}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    return not readable or clean_cell(item) in seen


def _revote_files(rd, lane, item, markers=False):
    """The re-vote lane files (absolute) that would re-judge `item` of `lane`: its item re-vote and the
    lane's whole-lane re-votes (`--ALL`, `--ALL.k` for a part `<lane>@k` row: only `--ALL.k`), existing or
    (markers) set aside with no file."""
    base = lane_base(lane)
    k = os.path.basename(str(lane)).split("@")[1] if "@" in os.path.basename(str(lane)) else None
    alls = [os.path.join(rd, "revote", os.path.basename(f)) for f in
            glob.glob(os.path.join(rd, "revote", glob.escape(base) + "--ALL*.json"))]
    if markers:
        alls += [os.path.join(rd, "revote", os.path.basename(m)[len("revote__"):]) for m in
                 glob.glob(os.path.join(rd, ".abandoned", "revote__" + glob.escape(base) + "--ALL*.json"))]
    alls = sorted({a for a in alls if _part(a) is not None and (item != WHOLE_LANE or k is None or _part(a) == k)})
    own = [] if item == WHOLE_LANE else [os.path.join(rd, "revote", f"{base}--{_slug(item)}.json")]
    return own + [a for a in alls if _covers(rd, a, item)]


def revote_lanes(rd, lane, item):
    """[(lane file relative to the round, commit)] of every re-vote of `item` of `lane` in round `rd`
    that has run: revote/<lane>--<item slug>.json, or a whole-lane revote/<lane>--ALL[.k].json,
    SEALED (commit = its seal commit) and whose sealed verdict judged `item` (judged_items; R3d F1: a
    re-vote that never judged the item -- another batch part's --ALL.k -- is not its re-vote). A lane
    SET ASIDE (stops.py set-aside --lane) never counts (R3c N1)."""
    import lane_auth
    try:
        repo = lane_auth.audit_repo(lane_auth.Path(rd))
    except lane_auth.AuthError:
        return []
    out = []
    for c in _revote_files(rd, lane, item):
        rel = os.path.relpath(c, rd)
        try:
            if is_abandoned_lane(rd, rel) or not os.path.exists(c):
                continue        # set aside: not a re-vote (R3c N1)
            items = _sealed_items(c)
            if items is None or clean_cell(item) not in items:
                continue        # never judged the item (R3d F1, R3e M1)
            h = lane_auth.committed_at(repo, lane_auth.locations(c)[3])
            if h:
                out.append((rel, h))
        except (lane_auth.AuthError, ValueError):
            continue
    return out


def revote_lane(rd, lane, item):
    """(lane file, commit) of THE re-vote of `item` of `lane` (revote_lanes), or None when none ran
    -- or when more than one did: a second re-vote never settles an item, and the script never picks
    one (R3d F2, RULINGS A2.3); the item stays open for the human."""
    rv = revote_lanes(rd, lane, item)
    return rv[0] if len(rv) == 1 else None


def set_aside_revote(rd, lane, item):
    """The re-vote lane file (relative) that would re-judge `item` of `lane` (item re-vote, or a
    whole-lane one covering it) and was set aside, else None (R3c N1; R3e L2: --ALL.k only for its part)."""
    for c in _revote_files(rd, lane, item, markers=True):
        if is_abandoned_lane(rd, os.path.relpath(c, rd)):
            return os.path.relpath(c, rd)
    return None


def unsealed_revote(rd, lane, item):
    """A re-vote lane file (relative) that would re-judge `item` of `lane`, exists, is not set aside and is
    not sealed as it stands, else None (R3e M2: a decision never waits out a re-vote it does not like)."""
    for c in _revote_files(rd, lane, item):
        rel = os.path.relpath(c, rd)
        if os.path.exists(c) and not is_abandoned_lane(rd, rel) and _sealed_items(c) is None:
            return rel
    return None


def _revote_before(rows, j):
    """The REVOTE NEEDED row before row j for its item (or its lane, whole), else None. Rows are
    valid_rows (exact lane and item names), compared by lane base and item."""
    r = rows[j]
    for r2 in rows[:j]:
        if r2.decision.startswith("REVOTE NEEDED") and r2.base == r.base and r2.item in (r.item, WHOLE_LANE):
            return r2.lane, r2.item
    return None


def whole_lane_settled(rd, lane, rows, j, revotes=None):
    """Is the `(whole lane)` REVOTE NEEDED row rows[j] (valid_rows) settled (R3e L1)? Yes when the lane's
    whole-lane re-votes (--ALL, or --ALL.k for a part row) ran -- none set aside, none unsealed, at least
    one sealed -- and judged every item the lane (part) did not Pass, and every item either verdict does
    not Pass is decided (ADOPT, REJECT, DEFER, QUESTION) after row j by a row the re-vote rules accept."""
    if set_aside_revote(rd, lane, WHOLE_LANE) or unsealed_revote(rd, lane, WHOLE_LANE):
        return False
    files = [c for c in _revote_files(rd, lane, WHOLE_LANE) if os.path.exists(c)]
    judged = [_sealed_items(c) for c in files]
    if not files or any(x is None for x in judged):
        return False
    rv = {k: v for x in judged for k, v in x.items()}
    base, b = rows[j].base, os.path.basename(str(lane))
    own = {}
    for f in glob.glob(os.path.join(rd, glob.escape(b) + (".json" if "@" in b else "*.json"))):
        if lane_base(f[:-len(".json")]) == base and "--" not in os.path.basename(f):
            try:
                own.update(judged_items(json.load(open(f, encoding="utf-8"))))
            except (OSError, ValueError):
                return False
    need = {k for k, v in own.items() if v != "Pass"} | {k for k, v in rv.items() if v != "Pass"}
    if not rv or need - set(rv):
        return False
    for it in need:
        hit = [r for r in rows[j + 1:] if r.base == base and clean_cell(r.item) == it
               and re.match(r"(ADOPT|REJECT|DEFER|QUESTION)\b", r.decision)]
        if not hit or revote_decision_problems(rd, revotes, only={(base, hit[0].item)}):
            return False
    return True


def _versions(repo, ap):
    """[(commit, subject, rows)] of every committed version of ADOPTED.md, oldest first (valid_rows)."""
    import lane_auth
    rel = os.path.relpath(ap, repo)
    out = []
    for line in lane_auth.git(repo, "log", "--reverse", "--format=%H %s", "--", rel).splitlines():
        h, _, subj = line.partition(" ")
        try:
            txt = lane_auth.git(repo, "show", f"{h}:{rel}")
        except lane_auth.AuthError:
            txt = ""
        out.append((h, subj, valid_rows(os.path.dirname(ap), txt)))
    return out


def revote_decision_problems(rd, revotes=None, only=None):
    """[problem] for every decision (ADOPT, REJECT, DEFER) that follows a REVOTE NEEDED row of its
    item (or its whole lane) in the round's ADOPTED.md without the re-vote having run (ROUND3 H2):
    the re-vote lane must be sealed (revote_lane; a set-aside one never counts, an unsealed one blocks),
    and the row must have come in an "adjudicate R revotes" commit after that seal. A decision of the
    `(whole lane)` row itself needs whole_lane_settled. `revotes`: for the adjudication about to be
    committed, True when it is "adjudicate R revotes" (rows not yet committed are judged as part of
    it); None judges the record as committed. `only`: restrict to these (lane base, item) pairs."""
    import lane_auth
    ap = os.path.join(rd, "ADOPTED.md")
    if not os.path.exists(ap):
        return []
    rows = valid_rows(rd)
    R = os.path.basename(rd)
    out, versions, repo = [], None, None
    for j, row in enumerate(rows):
        l, it, d = row.lane, row.item, row.decision
        if not DECIDED_RE.match(d) or not _revote_before(rows, j):
            continue
        if only is not None and (row.base, it) not in only:
            continue
        if it == WHOLE_LANE:
            jw = next(k for k in range(j) if rows[k].decision.startswith("REVOTE NEEDED")
                      and rows[k].base == row.base and rows[k].item == WHOLE_LANE)
            if not whole_lane_settled(rd, rows[jw].lane, rows, jw, revotes):
                out.append(f"{l} {it}: decided ({d.split()[0]}) after its whole-lane REVOTE NEEDED row, but the "
                           f"whole-lane re-vote has not settled it: every --ALL re-vote of the lane sealed (none set "
                           f"aside or unsealed) and each item it judged decided after the row; until then leave the "
                           f"row undecided")
            continue
        sa = set_aside_revote(rd, l, it)
        if sa:
            # R3c N1; R3d F3: once a re-vote of the item was set aside, no later re-vote settles it
            out.append(f"{l} {it}: decided ({d.split()[0]}) after REVOTE NEEDED, but its re-vote lane "
                       f"{sa} was set aside: a set-aside re-vote never ran, so it never "
                       f"licenses a decision, and a later re-vote (item or whole lane) is a second re-vote; leave "
                       f"the REVOTE NEEDED row undecided -- the item stays open for the human (DECISIONS.md, the report)")
            continue
        un = unsealed_revote(rd, l, it)
        if un:
            out.append(f"{l} {it}: decided ({d.split()[0]}) after REVOTE NEEDED while its re-vote lane {un} exists "
                       f"unsealed: seal it (lane_auth.py seal) or set it aside (stops.py set-aside --lane) first; "
                       f"a re-vote that returned is never passed over for another")
            continue
        rvs = revote_lanes(rd, l, it)
        if len(rvs) > 1:
            out.append(f"{l} {it}: decided ({d.split()[0]}) after REVOTE NEEDED, but more than one sealed re-vote "
                       f"judged it ({', '.join(r_ for r_, _ in rvs)}): a second re-vote never settles an item and "
                       f"none is chosen; leave the REVOTE NEEDED row undecided -- the item stays open for the "
                       f"human (DECISIONS.md, the report)")
            continue
        rv = rvs[0] if rvs else None
        if not rv:
            out.append(f"{l} {it}: decided ({d.split()[0]}) after REVOTE NEEDED, but no re-vote lane "
                       f"revote/{row.base}--{_slug(it)}.json (or --ALL) is sealed with a verdict on {it}: run the "
                       f"re-vote first; a REVOTE NEEDED row is not a re-vote, nor is a re-vote that never judged the item")
            continue
        try:
            repo = repo or lane_auth.audit_repo(lane_auth.Path(rd))
            versions = _versions(repo, ap) if versions is None else versions
        except lane_auth.AuthError as e:
            out.append(f"{l} {it}: the adjudication history cannot be read ({e})")
            continue
        key = (l, it, d)
        first = next(((h, subj) for h, subj, vr in versions
                      if any((vr[k].lane, vr[k].item, vr[k].decision) == key and _revote_before(vr, k)
                             for k in range(len(vr)))), None)
        want = f"adjudicate {R} revotes"
        if first is None:
            if revotes is not True:
                out.append(f"{l} {it}: its decision after the re-vote must be committed as \"{want}\" "
                           f"(integrity.py --commit-adjudication --revotes)")
            continue
        h, subj = first
        after = h != rv[1] and not subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", rv[1], h],
                                                  capture_output=True).returncode
        if subj != want or not after:
            out.append(f"{l} {it}: decided after REVOTE NEEDED in commit {h[:11]} (\"{subj[:60]}\"), which is "
                       f"not an \"{want}\" commit after the re-vote's seal {rv[1][:11]} ({rv[0]})")
    return out


def fault_items(rd, lane, fault_flags):
    """The items of lane file `lane` whose verdict entries cite a probe a lane-fault flag names (ROUND3
    H2/T5: the fault is settled by re-voting THOSE items, not any item of the lane). None when the
    flags name no probe an entry cites (no manifest, unlisted files): any re-vote of the lane, as
    before."""
    if any(SCHEMA_FAULT in f for f in fault_flags):
        # R3g: a verdict breaking the schema judged nothing: every item it names, and the whole lane
        # when an entry names none
        try:
            doc = json.load(open(os.path.join(rd, lane), encoding="utf-8"))
            ents = doc.get("verdicts") if isinstance(doc, dict) else None
            ents = ents if isinstance(ents, list) else [None]
        except (OSError, ValueError):
            ents = [None]
        named = [clean_cell(e["item"]) if isinstance(e, dict) and isinstance(e.get("item"), str) else "" for e in ents]
        return {WHOLE_LANE} if "" in named else set(named)
    paths = set()
    for f in fault_flags:
        paths |= {m.rstrip(".:") for m in PROBE_RE.findall(f)}
        m = re.search(r"probe (\S+?\.probes/\S+?) is listed", f)
        if m:
            paths.add(m.group(1))
    if not paths:
        return None
    try:
        doc = json.load(open(os.path.join(rd, lane), encoding="utf-8"))
    except (OSError, ValueError):
        return None
    items = set()
    for e in lane_entries(doc) or []:
        if any(p_ in json.dumps(e, ensure_ascii=False) for p_ in paths):
            items.add(clean_cell(e.get("item", "")))
    return items or None


def settle_problems(rd, flags=None, revotes=None):
    """[problem] unless ADOPTED.md settles every NOTE lanecheck prints for the round (RULINGS A1, A2):
      independence       a "CLEARED <lane file>: <reason>" line, or a whole-lane REVOTE NEEDED row;
      independence-path  a whole-lane REVOTE NEEDED row (a clearance does not settle it);
      lane-fault         a REVOTE NEEDED row for that lane (whole lane or an item);
      quote-unmatched    a "QUOTE RULED <lane file> | <item> | in the paper at tex l.N" line (or "not in the paper:
                         <why>" with a REVOTE NEEDED row; a re-vote lane: LEFT OPEN) -- a flag, never a re-vote by itself;
    and, for a RE-VOTE lane, a fault of its own (any of these) leaves its row open for the human:
      a "LEFT OPEN <lane file>: <reason>" line, and no later decision of its item(s).
    Carried-forward items of set-aside rounds are checked by `carried_problems`."""
    ap = os.path.join(rd, "ADOPTED.md")
    text = open(ap, encoding="utf-8").read() if os.path.exists(ap) else ""
    if flags is None:
        flags = []
        for p in lane_files(rd):
            flags += lane_problems(rd, p)
    all_rows = decision_rows(rd, text)
    rows = [(r.lane, r.item, r.decision) for r in all_rows if r.problem is None]
    faults = {}
    for f in flags:
        if f.startswith(NOTE) and flag_code(f) == "lane-fault" and flag_lane(f):
            faults.setdefault(flag_lane(f), []).append(f)
    cleared = {m.group(1) for m in CLEARED_RE.finditer(text)}
    left = {m.group(1) for m in LEFT_OPEN_RE.finditer(text)}
    ruled = {(m.group(1), clean_cell(m.group(2))): m.group(3) for m in QUOTE_RULED_RE.finditer(text)}
    tex_lines = _paper_lines(os.path.dirname(os.path.abspath(rd))) if ruled else None
    out = []
    by_lane = {}
    for f in flags:
        if f.startswith(NOTE) and flag_lane(f) and flag_code(f) == "quote-unmatched":
            # JUDGEMENT-SCAN 1: the adjudicator's ruling settles the flag; "not in the paper" is the item's re-vote
            lane, mq = flag_lane(f), QUOTE_FLAG_RE.search(f)
            it = clean_cell(mq.group(1)) if mq else ""
            r_ = ruled.get((lane, it)) or ruled.get((os.path.basename(lane), it))
            stem_ = lane[:-len(".json")]
            ln_ = re.match(r"in the paper at tex l\.\s*(\d+)", r_ or "")
            if ln_ and tex_lines is not None and not 1 <= int(ln_.group(1)) <= tex_lines:
                # review L1: a fact, never a content match -- the line the ruling cites exists in the paper's .tex
                out.append(f"{lane}: {it}: the ruling cites tex l.{ln_.group(1)}, but the paper's .tex has {tex_lines} "
                           f"lines: correct the QUOTE RULED line")
                continue
            if r_ is None:
                out.append(f"{lane}: {it}: a contradiction-step quote the matcher did not find needs the adjudicator's "
                           f"ruling: \"QUOTE RULED {lane} | {it} | in the paper at tex l.<N>\" or \"... | not in the "
                           f"paper: <why>\"")
            elif r_.startswith("not in the paper"):
                if stem_.startswith("revote/"):
                    if left.isdisjoint({lane}):
                        out.append(f"{lane}: ruled not in the paper: the re-vote's row stays open for the human: "
                                   f"\"LEFT OPEN {lane}: <reason>\" (never a second re-vote)")
                elif not any(d.startswith("REVOTE NEEDED") and lane_base(l) == lane_base(stem_)
                             and (it_ == it or it_ == WHOLE_LANE) for l, it_, d in rows):
                    out.append(f"{lane}: {it}: ruled not in the paper: a REVOTE NEEDED row for the item")
            continue
        if f.startswith(NOTE) and flag_lane(f):
            by_lane.setdefault(flag_lane(f), set()).add(flag_code(f))
    for lane, codes in sorted(by_lane.items()):
        stem = lane[:-len(".json")]
        name = os.path.basename(stem).split("--")[0].split("@")[0]
        if stem.startswith("revote/"):
            items = {it for _, it, d in rows if d.startswith("REVOTE NEEDED")
                     and re.sub(r"[^A-Za-z0-9_.-]+", "_", it)[:80] == stem.split("--", 1)[1]}
            # never cleared: a re-vote that read the record anchors on the reasons it re-judges (ROUND3 H3)
            if lane not in left:
                out.append(f"{lane}: a re-vote lane with its own fault ({', '.join(sorted(codes))}) leaves its row open "
                           f"for the human: write \"LEFT OPEN {lane}: <reason>\" (never a second re-vote)")
            if lane in left:
                decided = [it for _, it, d in rows if it in items and re.match(r"(ADOPT|REJECT|DEFER)\b", d)]
                if decided:
                    out.append(f"{lane}: LEFT OPEN, but its item {decided[0]} is decided; the human decides it")
            continue
        whole = any(d.startswith("REVOTE NEEDED") and it == WHOLE_LANE and l in (stem, lane) for l, it, d in rows)
        any_rv = whole or any(d.startswith("REVOTE NEEDED") and l.split("@")[0] == name for l, it, d in rows)
        if "independence-path" in codes and not whole:
            out.append(f"{lane}: a path into another round's record or another lane's files forces a whole-lane "
                       f"re-vote: a row | {stem} | {WHOLE_LANE} | ... | **REVOTE NEEDED** | ... | (no clearance settles it)")
        if "independence" in codes and lane not in cleared and not whole:
            out.append(f"{lane}: an independence NOTE needs a clearance line \"CLEARED {lane}: <reason>\" or a "
                       f"whole-lane REVOTE NEEDED row | {stem} | {WHOLE_LANE} | ...")
        if "lane-fault" in codes:
            hit = fault_items(rd, lane, faults.get(lane, []))
            rv_items = {it for l, it, d in rows if d.startswith("REVOTE NEEDED") and lane_base(l) == name}
            missing = sorted(hit - rv_items) if hit is not None and not whole else []
            if not any_rv or missing:
                schema = any(SCHEMA_FAULT in f for f in faults.get(lane, []))
                what = (f"its whole lane, | {stem} | {WHOLE_LANE} | (an entry names no item)" if WHOLE_LANE in missing
                        else f"each item {'it names' if schema else 'citing the faulty probe'} ({', '.join(missing)})"
                        f" (or | {stem} | {WHOLE_LANE} |)" if missing else f"this lane (or | {stem} | {WHOLE_LANE} |)")
                out.append(f"{lane}: a lane fault voids the evidence it touches: a REVOTE NEEDED row for {what}")
    # one parser for every reader (ROUND3 M2, R3e): a row naming no lane or item of the round exactly, or
    # a decision cell no reader can read, is refused
    out += [f"ADOPTED.md: {r.problem}" for r in all_rows if r.problem]
    for l, it, d in rows:
        if d.startswith("?"):
            out.append(f"{l} {it}: the decision cell {d[1:]!r} is none of {', '.join(project.DECISIONS[:5])} "
                       f"(write it as **ADOPT**, **REJECT**, ...)")
    # a decision after a REVOTE NEEDED row needs the re-vote itself (ROUND3 H2)
    out += revote_decision_problems(rd, revotes)
    return out


def record_problems(rounds_dir):
    """["<round>: <problem>"] for every adjudicated round as committed (ADOPTED.md committed and
    unchanged; not set aside): its lane NOTEs, lane faults and re-vote decisions settled
    (settle_problems). Run by `integrity.py --check` and `make_report.py --check` (ROUND3 M1), so an
    ADOPTED.md committed by hand as "adjudicate R" does not bypass the adjudication command's check.
    Runs pinned before ownership 2 (no settle rules) are not checked."""
    import integrity, lane_auth
    if integrity.pinned_version(rounds_dir) < 2:
        return []
    out = []
    for ap in sorted(glob.glob(os.path.join(rounds_dir, "*", "ADOPTED.md"))):
        rd = os.path.dirname(ap)
        if os.path.exists(os.path.join(rd, project.ABANDONED)):
            continue
        try:
            repo = lane_auth.audit_repo(lane_auth.Path(rd))
            rel = os.path.relpath(ap, repo)
            if not lane_auth.git(repo, "log", "-1", "--format=%H", "--", rel) or \
                    lane_auth.git(repo, "status", "--porcelain", "--", rel):
                continue      # an adjudication in progress: its commit command checks it
        except lane_auth.AuthError:
            continue
        out += [f"{os.path.basename(rd)}: {p_}" for p_ in settle_problems(rd)]
    return out


# U2 §7b (B7): a non-vacuity Pass of a step of the paper's proof by contradiction carries the paper's
# quoted passage and the negating lemma in a fixed form (AUDIT_PROTOCOL Lane D, clause 5); a Pass that
# claims the step without them is a lane fault (re-voted, never accepted on a docstring), and a
# well-formed one stands only once VACUOUS.md lists the section (contradiction_problems, adj-record).
# the marker: the words in capitals anywhere, or in any case as a label ("Contradiction step:"); a
# Pass merely saying it is "not a contradiction step" in prose claims nothing (review 4)
CONTRA_MARK = re.compile(r"CONTRADICTION STEP\b|(?:^|[.;!?]\s+)\s*(?i:contradiction[\s_-]*step\s*:)")
CONTRA_FORM = re.compile(r"(?i:contradiction[\s_-]*step)\s*:\s*(?i:negated\s+by)\s*`([^`\s]+)`\s*;\s*paper\s*(?:\([^)]*\))?\s*:\s*"
                         r"[\"“]([^\"”]*\S[^\"”]*)[\"”]", re.S)


def is_nonvacuity(path):
    """A non-vacuity lane file: `non-vacuity[@k].json`, or a re-vote of that lane (revote/non-vacuity...)."""
    b = os.path.basename(path)
    return b.startswith("non-vacuity") and b.endswith(".json")


def contradiction_steps(doc):
    """[(item, lemma or None, quote or None)] for every Pass entry of a lane document that claims a
    CONTRADICTION STEP; lemma/quote None when the claim is not in the fixed form."""
    out = []
    for e in lane_entries(doc) or []:
        if not isinstance(e, dict) or e.get("verdict") != "Pass":
            continue
        txt = " ".join(str(e.get(k, "")) for k in ("checked", "comment"))
        if not any(CONTRA_MARK.search(str(e.get(k, ""))) for k in ("checked", "comment")):
            continue
        m = CONTRA_FORM.search(txt)
        out.append((clean_cell(str(e.get("item", ""))), m.group(1) if m else None,
                    " ".join(m.group(2).split()) if m else None))
    return out


_FMT_MACRO = re.compile(r"\\(?:emph|textit|textbf|textrm|textsf|texttt|textsl|textup|textnormal|text|mathrm|mathit|"
                        r"mathbf)\s*\{")


def _qnorm(text):
    """How a quote and the paper's .tex are compared (re-check 2): the simple formatting wrappers (\\emph,
    \\textit, \\textbf, \\text, \\mathrm, ...) replaced by their argument, a one-character group `{x}` by
    `x`, and every `$`, `\\(`, `\\)`, tie `~`, spacing macro (`\\,` `\\;` `\\!` `\\ `) and whitespace dropped.
    `$x_{n + 1}$` and `$x_{n+1}$`, `\\pmod 7` and `\\pmod{7}`, `\\emph{chain count}` and `chain count` compare equal."""
    t = str(text)
    while True:
        m = _FMT_MACRO.search(t)
        if not m:
            break
        i, depth = m.end(), 1
        while i < len(t) and depth:
            depth += {"{": 1, "}": -1}.get(t[i], 0) if t[i - 1] != "\\" else 0
            i += 1
        if depth:           # unbalanced: drop the macro name only
            t = t[:m.start()] + t[m.end() - 1:]
            break
        t = t[:m.start()] + t[m.end():i - 1] + t[i:]
    t = re.sub(r"\\[,;:! ]|\\[()]|[$~]", "", t)
    t = "".join(t.split())
    return re.sub(r"(?<!\\)\{(\w)\}", r"\1", t)


def _paper_lines(rds):
    """The number of lines of the project's paper .tex (the longest, if several configs share the rounds dir), or None
    when there is no readable .tex."""
    n = None
    for repo, cfg in _project_configs(rds):
        src = cfg.get("source_pdf")
        if isinstance(src, str) and src.endswith(".tex"):
            try:
                k = len(open(src if os.path.isabs(src) else os.path.join(repo, src), encoding="utf-8",
                             errors="replace").read().splitlines())
            except OSError:
                continue
            n = max(n or 0, k)
    return n


def _project_paper(rds):
    """(the paper's .tex, normalized (_qnorm), or None; every name a project declaration may be
    referred to by (scope.short_names), or None) of the project whose rounds dir is `rds`
    (_project_configs). None where there is no config, or the source is no readable .tex (a PDF):
    then that part is not checked."""
    import scope
    tex = names = None
    for repo, cfg in _project_configs(rds):
        src = cfg.get("source_pdf")
        if isinstance(src, str) and src.endswith(".tex"):
            sp = src if os.path.isabs(src) else os.path.join(repo, src)
            try:
                tex = (tex or "") + "\x00" + _qnorm(open(sp, encoding="utf-8", errors="replace").read())
            except OSError:
                pass
        for f in cfg.get("lean_files") or []:
            try:
                text = open(os.path.join(repo, f), encoding="utf-8").read()
            except (OSError, TypeError):
                continue
            names = names if names is not None else set()
            for q in scope.parse_decls(text):
                if q != "_unnamed":
                    names |= scope.short_names(q)
    return tex, names


def quote_in(quote, tex):
    """Does the lane's quote occur in the paper's source `tex` (_qnorm-normalized)? Verbatim but for
    whitespace, `$`, ties and simple formatting wrappers (_qnorm); an omission marked "..." or "…" splits
    it into parts that occur in order."""
    at = 0
    parts = [_qnorm(x) for x in re.split(r"\.\.\.|…", quote)]
    if not any(parts):
        return False
    for part in parts:
        if not part:
            continue
        i = tex.find(part, at)
        if i < 0:
            return False
        at = i + len(part)
    return True


def contradiction_faults(path):
    """["NOTE[lane-fault] ..."] for one lane file: a non-vacuity Pass claiming a CONTRADICTION STEP
    without the quoted paper passage and the negating lemma (docstring alone: Ambiguous, U2 §7b), or
    whose quote is not in the paper's .tex, or whose lemma the project does not declare (review 2)."""
    if not is_nonvacuity(path):
        return []
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return []           # schema_faults reports it
    steps = contradiction_steps(doc)
    if not steps:
        return []
    rd = os.path.dirname(os.path.abspath(path))
    rd = os.path.dirname(rd) if os.path.basename(rd) == "revote" else rd
    tex, names = _project_paper(os.path.dirname(rd))
    out, b = [], os.path.basename(path)
    for item, lemma, quote in steps:
        if not (lemma and quote):
            out.append(f"NOTE[lane-fault] {b}: {item} is passed as a CONTRADICTION STEP without "
                       f"the fixed form (CONTRADICTION STEP: negated by `<lemma>`; paper (tex l.N): \"<passage>\"): a "
                       f"step established by a docstring alone is Ambiguous, never a Pass; the adjudicator re-votes "
                       f"the item")
            continue
        if tex is not None and not quote_in(quote, tex):
            b_ = os.path.relpath(os.path.abspath(path), rd)     # revote/<lane>--<item>.json for a re-vote lane
            out.append(f"NOTE[quote-unmatched] {b_}: {item} is passed as a CONTRADICTION STEP quoting \"{quote[:80]}\", "
                       f"which the text matcher does not find in the paper's source (LaTeX macros or formatting can hide "
                       f"a real passage): a flag, not a finding -- the adjudicator reads the paper and rules once in "
                       f"ADOPTED.md: \"QUOTE RULED {b_} | {item} | in the paper at tex l.<N>\" settles it; \"QUOTE RULED "
                       f"{b_} | {item} | not in the paper: <why>\" needs a REVOTE NEEDED row for the item (a re-vote lane: "
                       f"LEFT OPEN)")
        if names is not None and lemma not in names:
            out.append(f"NOTE[lane-fault] {b}: {item} is passed as a CONTRADICTION STEP negated by `{lemma}`, which "
                       f"the project's Lean files do not declare: the adjudicator re-votes the item")
    return out


_LEAN_NAME = r"[A-Za-z_][\w'.]*[\w']|[A-Za-z_]"


def _step_names(item, lemma):
    """The Lean names a VACUOUS.md row may list a contradiction step by: the item's (backticked, its first
    word, or any dotted or underscored name in it) and the negating lemma's."""
    t = item or ""
    first = re.match(rf"\s*`?({_LEAN_NAME})", t)
    names = set(re.findall(r"`([^`\s]+)`", t)) | {n for n in re.findall(_LEAN_NAME, t) if "." in n or "_" in n}
    return {n.strip(".") for n in names | ({first.group(1)} if first else set()) | {lemma or ""} if n.strip(".")}


def _names_exactly(cell, names):
    """Does the statement cell name one of `names` exactly: a Lean name in it equal to one, or one
    qualified further or less (`TI.c450x` for `Ns.TI.c450x`), never a name sharing only a part?"""
    for t in set(re.findall(r"`([^`\s]+)`", cell)) | set(re.findall(_LEAN_NAME, cell)):
        t = t.strip(".")
        if t and any(t == n or n.endswith("." + t) or t.endswith("." + n) for n in names):
            return True
    return False


def vacuous_listing(rounds_dir):
    """[statement cell] of every VACUOUS.md row that lists something as vacuous: a row of its table
    (the `statement` column) whose status is open or repaired (decisions.is_repaired); a dismissed
    or misspelt status lists nothing here (the decisions check reports the status, record-format)."""
    import decisions
    vp = os.path.join(rounds_dir, "VACUOUS.md")
    out = []
    for header, cells in decisions.table_rows(decisions._read(vp)):
        si = next((i for i, h in enumerate(header) if h.startswith("statement")), None)
        if si is None or si >= len(cells):
            continue
        st = cells[header.index("status")].strip() if "status" in header and header.index("status") < len(cells) else "open"
        if re.match(r"^\W*open\b", st, re.I) or decisions.is_repaired(st):
            out.append(cells[si])
    return out


def overturned(rows, rel, item):
    """Did the adjudication (valid_rows `rows` of the round) overturn lane file `rel`'s Pass of `item`
    (review 3)? A lane's own Pass: a REVOTE NEEDED row for the item or the whole lane (the re-vote's
    verdict counts instead), a QUESTION row, or a row whose verdict cell is Fail or Ambiguous. A
    re-vote's Pass (revote/...): such a row after the REVOTE NEEDED row that ordered it (a QUESTION, or
    Fail / Ambiguous), never the REVOTE NEEDED row itself."""
    it, base, rev = clean_cell(item), lane_base(rel[:-len(".json")] if rel.endswith(".json") else rel), \
        rel.startswith("revote/")
    seen_rv = False
    for r in rows:
        if r.base != base or r.item not in (it, WHOLE_LANE):
            continue
        if r.decision.startswith("REVOTE NEEDED"):
            if not rev:
                return True
            seen_rv = True
            continue
        if r.item != it or (rev and not seen_rv):
            continue
        if r.decision.startswith("QUESTION") or re.match(r"^(Fail|Ambiguous)\b", r.verdict):
            return True
    return False


def contradiction_problems(rounds_dir):
    """["<round>/<lane file>: ..."] for every well-formed CONTRADICTION STEP Pass of a non-vacuity lane of
    an adjudicated round (ADOPTED.md present; not set aside) whose item, or the negating lemma it names,
    no row of VACUOUS.md lists, by name in its statement cell (review 2: exactly, the row open or
    repaired): the Pass stands only with the row (U2 §7b; adjudicator rule G)."""
    cells = vacuous_listing(rounds_dir)
    out = []
    for ap in sorted(glob.glob(os.path.join(rounds_dir, "*", "ADOPTED.md"))):
        rd = os.path.dirname(ap)
        if os.path.exists(os.path.join(rd, project.ABANDONED)):
            continue
        rows = None
        for p in lane_files(rd):
            if not is_nonvacuity(p):
                continue
            try:
                doc = json.load(open(p, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for item, lemma, quote in contradiction_steps(doc):
                if not (lemma and quote):
                    continue        # a lane fault (contradiction_faults): re-voted, never a Pass
                rows = valid_rows(rd) if rows is None else rows
                if overturned(rows, os.path.relpath(p, rd), item):
                    continue        # review 3: the adjudicated outcome is not this Pass
                if any(_names_exactly(c, _step_names(item, lemma)) for c in cells):
                    continue
                out.append(f"{os.path.basename(rd)}/{os.path.relpath(p, rd)}: {item} is passed as a step of the "
                           f"paper's proof by contradiction (negated by `{lemma}`), and no VACUOUS.md row names it "
                           f"or `{lemma}`: the adjudicator lists the section there")
    return out


# U2 §7f (B7): an escalation's answer counts only while its prompt is exactly what prompt.py wrote
# and committed for the recorded question (the hash and a fresh rendering of the recorded inputs).
ESC_ANSWER_RE = re.compile(r"^(NEEDS-HUMAN|ANSWERABLE):\s*\S")


def _commits_of(repo, rel):
    """[(hash, subject, body)] of every commit touching `rel`, newest first."""
    r = subprocess.run(["git", "-C", repo, "log", "--format=%H%x1f%s%x1f%b%x1e", "--", rel],
                       capture_output=True, text=True)
    out = []
    for rec in r.stdout.split("\x1e"):
        if rec.strip():
            h, s, b = (rec.strip("\n").split("\x1f") + ["", ""])[:3]
            out.append((h, s, b))
    return out


def _text_at(repo, commit, path):
    """The text of `path` (a file of the apparatus) as committed at `commit` of `repo`; the file on disk when git does
    not have it there (an apparatus outside that repository)."""
    import prompt as _pr
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo))
    if not rel.startswith(".."):
        r = subprocess.run(["git", "-C", repo, "show", f"{commit}:{rel}"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
    return _pr.load(path)


def escalation_check(cfg, name, commit=True, agent_id=None, returned=None):
    """(answer line or None, [problem]) for escalation `name` (E<n>). Problems: no prompt; a prompt not
    committed exactly once as "escalate E<n>", changed since, or not what prompt.py renders for the
    inputs that commit records (composed or edited by hand); no answer, or not one line NEEDS-HUMAN: /
    ANSWERABLE:; an answer committed other than as "escalate E<n> (answer)", without the escalation
    subagent's record (its id and the sha256 of the line it returned, review 1), or changed since. A
    valid, uncommitted answer is committed (`commit`) only with that record: `agent_id` (the child's
    id; Codex: its thread id) and `returned` (its final message), whose last line must be the
    answer file's line -- an answer the operator wrote is no subagent's. Without `commit`, an
    uncommitted answer is not accepted yet."""
    import prompt as _pr, lane_auth, hashlib
    if not _pr.ESC_NAME_RE.match(name or ""):
        return None, [f"{name!r} is not an escalation name (E1, E2, ...)"]
    p, ans = _pr.escalation_paths(cfg, name)
    if not os.path.isfile(p):
        return None, [f"no prompt {os.path.relpath(p, project.REPO)}: an escalation is written by prompt.py "
                      f"--prompt escalate --question ... --write"]
    try:
        repo = str(lane_auth.audit_repo(lane_auth.Path(p).resolve().parent))
    except lane_auth.AuthError as e:
        return None, [f"the escalation record is not in a git repository: {e}"]
    rel = os.path.relpath(os.path.realpath(p), repo)
    probs = []
    cs = _commits_of(repo, rel)
    content = open(p, encoding="utf-8").read()
    if not cs:
        return None, [f"{rel} was never committed: only prompt.py --write records an escalation"]
    if [s for _h, s, _b in cs] != [f"escalate {name}"]:
        probs.append(f"{rel} must be committed once, as \"escalate {name}\" (commits: "
                     + "; ".join(f"{h[:11]} \"{s}\"" for h, s, _b in cs) + ")")
    body = cs[-1][2]
    m = re.search(r"^prompt sha256: ([0-9a-f]{64})$", body, re.M)
    mi = re.search(r"^inputs: (.*)$", body, re.M)
    if not m or not mi:
        probs.append(f"the commit {cs[-1][0][:11]} records no prompt sha256 and inputs")
    elif hashlib.sha256(content.encode("utf-8")).hexdigest() != m.group(1):
        probs.append(f"{rel} does not match the sha256 recorded when it was written: the prompt was changed")
    else:
        try:
            inp = json.loads(mi.group(1))
            # OPERATOR-AUTHORITY: rendered with the protocol text in force when it was written (its commit's
            # AUDIT_PROTOCOL.md), so a reviewed tool patch to the protocol text later never fails it
            again, _n = _pr.render_escalation(_text_at(repo, cs[-1][0], _pr.DEFAULT), cfg, name, inp)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            again = None
            probs.append(f"the recorded inputs cannot be rendered again: {e}")
        if again is not None and again + "\n" != content:
            probs.append(f"{rel} is not the prompt prompt.py renders for its recorded question: composed or "
                         f"edited by hand (only the question, declaration and passage may be given)")
    if subprocess.run(["git", "-C", repo, "status", "--porcelain", "--", rel], capture_output=True,
                      text=True).stdout.strip():
        probs.append(f"{rel} has an uncommitted change")
    if not os.path.isfile(ans):
        return None, probs + [f"no answer yet ({os.path.relpath(ans, project.REPO)}): spawn the escalation check "
                              f"with the line prompt.py printed"]
    lines = [l for l in open(ans, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    verdict = lines[0].strip() if len(lines) == 1 and ESC_ANSWER_RE.match(lines[0].strip()) else None
    if verdict is None:
        probs.append(f"{os.path.relpath(ans, project.REPO)} is not one line \"NEEDS-HUMAN: ...\" or "
                     f"\"ANSWERABLE: ...\"")
    arel = os.path.relpath(os.path.realpath(ans), repo)
    acs = _commits_of(repo, arel)
    dirty = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--", arel], capture_output=True,
                           text=True).stdout.strip()
    if acs:
        if [s for _h, s, _b in acs] != [f"escalate {name} (answer)"]:
            probs.append(f"{arel} must be committed once, as \"escalate {name} (answer)\"")
        if dirty:
            probs.append(f"{arel} has an uncommitted change: the committed answer is the record")
        ab = acs[-1][2]
        ag = re.search(r"^agent: (\S.*)$", ab, re.M)
        rh = re.search(r"^returned sha256: ([0-9a-f]{64})$", ab, re.M)
        if not ag or not rh:
            probs.append(f"{arel} was committed without the escalation subagent's record (its agent id and the "
                         f"line it returned): only lanecheck.py --escalation {name} --agent-id ... --returned-file ... "
                         f"commits an answer")
        elif verdict and rh.group(1) != hashlib.sha256(verdict.encode("utf-8")).hexdigest():
            probs.append(f"{arel} is not the line the escalation subagent returned (sha256 recorded at its commit)")
    elif not commit:
        if not probs:
            probs.append(f"{arel} is not accepted yet: run lanecheck.py --escalation {name} with the subagent's "
                         f"--agent-id and --returned-file")
    elif not probs and verdict:
        back = [l.strip() for l in str(returned or "").splitlines() if l.strip()]
        if not str(agent_id or "").strip() or not back:
            probs.append(f"no subagent record: give the escalation check's --agent-id (Codex: its thread id) and "
                         f"--returned-file (its final message, saved verbatim): an answer is the subagent's, never "
                         f"the operator's")
        elif back[-1] != verdict:
            probs.append(f"{arel} is not the line the escalation subagent returned ({back[-1][:80]!r}): the answer "
                         f"file was not written by it")
        else:
            aid = " ".join(str(agent_id).split())
            project.commit_only([ans], f"escalate {name} (answer)\n\nagent: {aid}\nreturned sha256: "
                                + hashlib.sha256(verdict.encode("utf-8")).hexdigest(), repo=repo)
    return (verdict if not probs else None), probs


RETURNED_HEREDOC = ("cat > <file> <<'RETURNED'\n<the subagent's final message, pasted verbatim>\nRETURNED")


def escalation_cli(cfg, name, agent_id=None, returned=None, returned_file=None):
    """`lanecheck.py --escalation`: check escalation `name` and commit its answer with the subagent's record
    (escalation_check). The returned message comes verbatim from `returned_file` (re-check 1: a message
    passed as --returned "..." loses its backticks and $ to the shell) or from `returned`, never both."""
    if returned is not None and returned_file is not None:
        print(f"escalation {name} refused: give --returned-file or --returned, not both")
        return 2
    if returned_file is not None:
        try:
            returned = open(returned_file, encoding="utf-8").read()
        except OSError as e:
            print(f"escalation {name} refused: --returned-file {returned_file}: {e}")
            return 2
    # B7: a refusal is no stop: the answer is not a written recommendation
    ans, bad = escalation_check(cfg, name, agent_id=agent_id, returned=returned)
    for p in bad:
        print(f"escalation {name} refused: {p}")
    if bad:
        print(f"escalation {name}: NOT USABLE (no stop: its answer is no recommendation). If only the returned "
              f"message did not match, save it verbatim with a quoted heredoc and run this again with "
              f"--returned-file:\n  {RETURNED_HEREDOC.replace(chr(10), chr(10) + '  ')}\n"
              f"Otherwise write a new escalation (prompt.py --prompt escalate --question ... --decl ... --write); "
              f"under `involved` one on the same declaration re-asks this one and stays the human's question")
        return 1
    print(f"escalation {name}: {ans}")
    return 0


ESC_CITE_RE = re.compile(r"\bescalation (?:check )?(E[0-9]+)\b", re.I)
_ESC_NAME = re.compile(r"`([^`\s]+)`|\b([A-Za-z_][\w'.]*(?:[._0-9])[\w'.]*[\w'])")


def escalation_decls(cfg, inp):
    """The declarations escalation input `inp` names (re-check 3): its --decl, and every Lean name its
    question names (backticked, or written with a dot, underscore or digit) that the project declares.
    The matter an escalation is about is keyed on these, never on its wording."""
    out = {str(inp.get("decl") or "").strip(".")} - {""}
    cands = {(a or b).strip(".") for a, b in _ESC_NAME.findall(str(inp.get("question") or ""))} - {""}
    if cands:
        import make_report
        try:
            out |= set(make_report.locate_names(cfg, sorted(cands)))
        except (OSError, KeyError, TypeError):
            pass
    return out


def same_decl(a, b):
    """Do declaration-name sets `a` and `b` share a declaration: one name equal to another, or the same
    name qualified further (`TI.c450x`, `Ns.TI.c450x`), never two names sharing only a part?"""
    return any(x == y or x.endswith("." + y) or y.endswith("." + x) for x in a for y in b)


def escalations(cfg):
    """[dict] of every escalation written (prompt.escalation_names), in order: name, inputs (the question,
    declaration, passage its prompt commit records), decls (escalation_decls), answer (the accepted line,
    else None), problems (why it is not accepted), reask_of (an earlier escalation on the same matter
    still standing as the human's question -- answered NEEDS-HUMAN, or with no accepted answer -- else
    None: under `involved` that stays the human's question, review 1). The same matter is keyed on the
    declarations named (re-check 3: a rephrased question on the same declaration is a re-ask), the
    latest NEEDS-HUMAN preferred, else the latest unanswered."""
    import prompt as _pr
    out = []
    for name in _pr.escalation_names(cfg):
        p = _pr.escalation_paths(cfg, name)[0]
        inp = {}
        import lane_auth
        try:
            repo = str(lane_auth.audit_repo(lane_auth.Path(p).resolve().parent))
            cs = _commits_of(repo, os.path.relpath(os.path.realpath(p), repo))
            mi = re.search(r"^inputs: (.*)$", cs[-1][2], re.M) if cs else None
            inp = json.loads(mi.group(1)) if mi else {}
        except (lane_auth.AuthError, ValueError, OSError):
            inp = {}
        ans, probs = escalation_check(cfg, name, commit=False)
        inp = inp if isinstance(inp, dict) else {}
        out.append({"name": name, "inputs": inp, "decls": escalation_decls(cfg, inp), "answer": ans,
                    "problems": probs, "reask_of": None})
    for i, e in enumerate(out):
        open_ = [p for p in out[:i] if (p["answer"] is None or p["answer"].startswith("NEEDS-HUMAN"))
                 and same_decl(e["decls"], p["decls"])]
        nh = [p for p in open_ if p["answer"]]
        if open_:
            e["reask_of"] = (nh or open_)[-1]["name"]
    return out


def escalation_line(e, by_name=None):
    """One line of the report and DECISIONS.md for escalation record `e` (escalations): the question,
    declaration, the accepted answer or why there is none, and the earlier NEEDS-HUMAN it re-asks."""
    inp = e["inputs"]
    t = f"escalation {e['name']}: \"{project.full(inp.get('question', '?'))}\""
    if inp.get("decl"):
        t += f" (`{inp['decl']}`)"
    t += (f" -- answer: {e['answer']}" if e["answer"] else
          f" -- NOT ACCEPTED, its answer counts for nothing: {e['problems'][0] if e['problems'] else '?'}")
    if e["reask_of"]:
        prev = (by_name or {}).get(e["reask_of"])
        t += (f" -- RE-ASKS escalation {e['reask_of']}, " + reask_state(prev)
              + " (the same declaration: under `involved` it stays the human's question)")
    return t


def reask_state(prev):
    """How the earlier escalation a re-ask repeats stands: its NEEDS-HUMAN answer, or no accepted answer."""
    return f"answered {prev['answer']}" if prev and prev["answer"] else "which has no accepted answer"


def escalation_citations(cfg, text, recs=None):
    """[problem] for every "escalation E<n>" `text` cites (RUN_LOG.md, DECISIONS.md): one never written or
    not accepted, and, under `involved`, one that re-asks an earlier NEEDS-HUMAN or unanswered escalation
    on the same declaration (review 1, re-check 3, V2: that question goes to the human)."""
    recs = escalations(cfg) if recs is None else recs
    by = {e["name"]: e for e in recs}
    out = []
    for n in sorted(set(m.group(1).upper() for m in ESC_CITE_RE.finditer(text or "")), key=lambda x: int(x[1:])):
        e = by.get(n)
        if e is None:
            out.append(f"cites escalation {n}, which was never written (prompt.py --prompt escalate ... --write)")
        elif not e["answer"]:
            out.append(f"cites escalation {n}, whose answer is not accepted: "
                       + (e["problems"][0] if e["problems"] else "?"))
        elif e["reask_of"] and project.involvement(cfg) == "involved":
            out.append(f"cites escalation {n}, which re-asks escalation {e['reask_of']} ("
                       + reask_state(by.get(e["reask_of"])) + ") on the same declaration: under `involved` that "
                       f"stays the human's question -- ask the human")
    return out


def clearances(rd):
    """[(lane file, reason)] of every clearance line in the round's ADOPTED.md (the report lists them)."""
    ap = os.path.join(rd, "ADOPTED.md")
    text = open(ap, encoding="utf-8").read() if os.path.exists(ap) else ""
    return [(m.group(1), m.group(2).strip()) for m in CLEARED_RE.finditer(text)]


def stray_files(repo, audits_dir):
    """Files that appeared or changed in the Lean repository since Phase 0's baseline
    (tree_state.py): the user's own pre-existing untracked files are not lane writes."""
    r = subprocess.run([sys.executable, "-B", os.path.join(audits_dir, "tree_state.py"), "--check"],
                       cwd=repo, capture_output=True, text=True)
    out = [f"since Phase 0: {l.strip()}" for l in r.stdout.splitlines() if l.startswith(("APPEARED", "VANISHED"))]
    if r.returncode == 2:
        out.append("no Phase 0 tree baseline, so lane writes cannot be told from earlier files: run phase0.py "
                   "before the lanes")
    return out


def _ancestors():
    pids, pid = set(), os.getpid()
    while pid > 1:
        pids.add(pid)
        try:
            pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return pids


OPERATOR_TAG = b"FORMALIZE_PAPER_OPERATOR=1"


def _environ_has(pid, tag):
    try:
        return tag in open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    except OSError:
        return False


def _parent(pid):
    try:
        return int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def _lane_pids(prompt_dir):
    """Processes running a lane of this round as a process of their own (the codex_spawn.py
    fallback runs `codex exec … <round>/prompts/<lane>.txt`); built-in subagents (Claude Code,
    Codex) are not processes of their own and cannot be traced this way."""
    if not prompt_dir:
        return set()
    out = set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                cmd = open(f"/proc/{d}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if prompt_dir in cmd:
                out.add(int(d))
    return out


def stray_loops(kill=False, since=None, repo=None, prompt_dir=None):
    """This user's shells running a polling loop, started after `since` (epoch seconds; the
    round's scope time), never this process or its ancestors, and never a process started with
    FORMALIZE_PAPER_OPERATOR=1 in its environment (a monitor the operator started on purpose,
    RUN.md rule 9). A loop counts when its cwd is inside the repository, or when its parent chain
    reaches a lane process of this round (whatever its cwd). Listed always; ended only with --kill."""
    r = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid=,etimes=,args="], capture_output=True, text=True)
    mine, now, out = _ancestors(), time.time(), []
    lanes = _lane_pids(prompt_dir)
    for l in r.stdout.splitlines():
        parts = l.strip().split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        pid, age, args = int(parts[0]), int(parts[1]), parts[2]
        if pid in mine or not LOOP_RE.search(args):
            continue
        if since is not None and now - age < since - 60:
            continue                      # older than the round: not a lane's
        if _environ_has(pid, OPERATOR_TAG):
            continue                      # the operator's own monitor, tagged as RUN.md says
        chain, q = set(), _parent(pid)
        while q > 1 and q not in chain:
            chain.add(q); q = _parent(q)
        from_lane = bool(chain & lanes)
        if repo is not None and not from_lane:
            # A same-user process in another project is not this round's to inspect or kill.
            # cwd gives actual process ownership evidence; a word in a shell wrapper does not.
            try:
                cwd = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
                root = os.path.realpath(repo)
                if os.path.commonpath([cwd, root]) != root:
                    continue
            except (OSError, ValueError):
                continue
        if kill:
            subprocess.run(["kill", str(pid)], capture_output=True)
        out.append(f"stray polling loop (pid {pid}{', killed' if kill else ''}): {args[:100]}")
    return out


def check_round(cfg, round_name, kill=False, processes=True):
    rd = os.path.join(project.REPO, cfg["rounds_dir"], round_name)
    if not os.path.isdir(rd):
        return [f"PROBLEM[no-round] no round directory {rd}"]
    import lane_auth
    probs = [f"PROBLEM{p[:p.index(']') + 1]}{p[p.index(']') + 1:]}" if p.startswith("[") else f"PROBLEM[unauthenticated] {p}"
             for p in lane_auth.check_round(rd, lane_files(rd))]
    for p in lane_files(rd):
        probs += lane_problems(rd, p)
    # B10 (ADDENDUM N4, U2 §7f): a reader-fix round of this round ran on the prompt prompt.py committed
    import integrity
    probs += [f"PROBLEM[prompt-changed] {x}" for x in integrity.reader_fix_prompt_problems(
        project.AUDITS, os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"]), project.AUDITS), round_name)]
    probs += [f"PROBLEM[{'no-baseline' if 'no Phase 0 tree baseline' in x else 'stray-file'}] {x}"
              for x in stray_files(project.REPO, project.AUDITS)]
    if processes:
        tgt = os.path.join(rd, "TARGET.json")
        probs += [f"PROBLEM[stray-loop] {x}" for x in
                  stray_loops(kill, since=os.path.getmtime(tgt) if os.path.exists(tgt) else None, repo=project.REPO,
                              prompt_dir=os.path.join(rd, "prompts") + os.sep)]
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--round")
    ap.add_argument("--project")
    ap.add_argument("--kill", action="store_true")
    ap.add_argument("--settled", action="store_true",
                    help="exit 1 unless the round's ADOPTED.md settles every NOTE (clearance, re-vote, LEFT OPEN)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--escalation", metavar="E<n>",
                    help="check an escalation's prompt against its recorded hash and commit its answer (U2 §7f)")
    ap.add_argument("--agent-id", help="with --escalation: the escalation subagent's id (Codex: its thread id)")
    ap.add_argument("--returned", help="with --escalation: the escalation subagent's final message, verbatim "
                    "(prefer --returned-file: the shell expands backticks and $ inside double quotes)")
    ap.add_argument("--returned-file", metavar="PATH",
                    help="with --escalation: a file holding the subagent's final message verbatim, saved with a "
                         "quoted heredoc (cat > PATH <<'RETURNED' ... RETURNED)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.round and not a.escalation:
        ap.error("give --round (or --escalation E<n>)")
    try:
        cfg, _ = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    if a.escalation:
        return escalation_cli(cfg, a.escalation, a.agent_id, a.returned, a.returned_file)
    rd = os.path.join(project.REPO, cfg["rounds_dir"], a.round)
    if a.settled:
        bad = settle_problems(rd) + carried_problems(os.path.join(project.REPO, cfg["rounds_dir"]), a.round)
        for p in bad:
            print(f"PROBLEM[unsettled] {p}")
        print(f"settled {a.round}: {'OK' if not bad else f'{len(bad)} problem(s)'}")
        return 1 if bad else 0
    probs = check_round(cfg, a.round, a.kill)
    import lane_auth
    for h, lane, reason, files in lane_auth.reissues(rd):
        print(f"NOTE[reissued] reissued lane {lane} in commit {h[:11]}: {reason}; earlier verdict kept as "
              f"{', '.join(files) or 'NONE (no verdict file existed at the reissue)'} -- the adjudicator reads it")
    for p in probs:
        print(p)
    bad = [p for p in probs if counts(p)]
    print(f"lane check {a.round}: {'OK' if not bad else f'{len(bad)} problem(s)'}")
    return 1 if bad else 0


def carried_problems(rounds_dir, round_name, revotes=None):
    """[problem] for every Fail or Ambiguous item a set-aside carried forward (stops.py set-aside) that
    has no row in this round's ADOPTED.md or an adjudication after the set-aside (RULINGS A7.4)."""
    import stops
    return stops.carried_problems(rounds_dir, round_name, revotes=revotes)


def selftest():
    res = []
    def say(n, ok):
        res.append(ok); print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    d = tempfile.mkdtemp(prefix="lanecheck-")
    try:
        rd = os.path.join(d, "2026-01-02-bbbbbbb"); os.makedirs(os.path.join(rd, "correspondence.probes"))
        open(os.path.join(rd, "correspondence.probes", "ok.lean"), "w").write("x")
        def lane(name, text):
            p = os.path.join(rd, name); open(p, "w").write(text); return check_lane(p, rd)
        say("a clean lane passes", lane("correspondence.json",
            '{"checked": "probe correspondence.probes/ok.lean compiles; this round 2026-01-02-bbbbbbb"}') == [])
        say("A1: a lane naming another round is NOTE[independence] (it does not block)",
            [flag_code(p) for p in lane("substantiveness.json", '{"checked": "as in 2026-01-01-aaaaaaa"}')]
            == ["independence"] and not any(counts(p) for p in lane("substantiveness.json", '{"checked": "as in 2026-01-01-aaaaaaa"}')))
        say("A1 condition 3: a PATH into another round's record is NOTE[independence-path]",
            any(flag_code(p) == "independence-path" for p in lane("substantiveness.json",
                '{"checked": "audits/P/2026-01-01-aaaaaaa/ADOPTED.md row 3"}')))
        open(os.path.join(rd, "correspondence.probes", "run.out.txt"), "w").write("x")
        say("a double extension (run.out.txt) is one probe path",
            lane("correspondence.json", '{"checked": "correspondence.probes/run.out.txt"}') == [])
        say("A1: a lane mentioning ADOPTED.md is NOTE[independence]",
            any(flag_code(p) == "independence" and "record files" in p
                for p in lane("non-vacuity.json", '{"checked": "per ADOPTED.md row 3"}')))
        mf_ = lane("paper-faithfulness.json", '{"checked": "see paper-faithfulness.probes/missing.lean."}')
        say("A2/A3: a lane citing a probe that was never written is NOTE[lane-fault] (not 'evidence changed'): no block",
            any(flag_code(p) == "lane-fault" and "missing.lean" in p for p in mf_) and not any(counts(p) for p in mf_))
        say("A2/A3 condition 4: a lane citing a SIBLING lane's probe directory is NOTE[independence-path]",
            any(flag_code(p) == "independence-path" and "correspondence.probes" in p
                for p in lane("paper-faithfulness.json", '{"checked": "see correspondence.probes/ok.lean"}')))
        open(os.path.join(rd, "correspondence.probes", "del_a__h.lean"), "w").write("x")
        say("line suffixes, wildcards, <placeholders> and a|b alternatives resolve against real files",
            lane("correspondence.json", '{"checked": "correspondence.probes/ok.lean:90-95, correspondence.probes/del_*.lean, '
                 'correspondence.probes/del_<decl>__<hyp>.lean, correspondence.probes/del_a__h|h.lean, '
                 'correspondence.probes/ok.lean/audits/x/correspondence.probes/del_a__h.lean"}') == []
            and any("nope" in p for p in lane("correspondence.json", '{"checked": "correspondence.probes/nope_*.lean"}')))
        say("record files are not lane files", "TARGET.json" not in [os.path.basename(p) for p in
                                                                     (open(os.path.join(rd, "TARGET.json"), "w").write("{}") and lane_files(rd))])
        say("a bare commit hash is not another round (the diff base is in git log); record names in any case are",
            (os.makedirs(os.path.join(d, "2026-01-01-aaaaaaa")) or True)
            and lane("x1.json", '{"checked": "diff base aaaaaaa"}') == []
            and any("record files" in p for p in lane("x2.json", '{"checked": "per adopted.md and AUTHOR_NOTES.md"}')))
        os.makedirs(os.path.join(rd, "revote"))
        open(os.path.join(rd, "revote", "nv.json"), "w").write("{}")
        tr = os.path.join(d, "repo"); os.makedirs(os.path.join(tr, "audits"))
        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tree_state.py"), os.path.join(tr, "audits"))
        gt = lambda *x: subprocess.run(["git", "-C", tr, *x], capture_output=True, text=True)
        gt("init", "-q"); gt("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i")
        open(os.path.join(tr, "users_own.md"), "w").write("x")
        say("no Phase 0 baseline is reported, never passed", any("no Phase 0 tree baseline" in p
                                                                for p in stray_files(tr, os.path.join(tr, "audits"))))
        subprocess.run([sys.executable, "-B", os.path.join(tr, "audits", "tree_state.py"), "--save"], cwd=tr, capture_output=True)
        open(os.path.join(tr, "lane_wrote.lean"), "w").write("x")
        sf = stray_files(tr, os.path.join(tr, "audits"))
        say("a file written after Phase 0 is flagged; the user's earlier untracked file is not",
            any("lane_wrote.lean" in p for p in sf) and not any("users_own" in p for p in sf))
        say("re-vote lane files are checked too", any(p.endswith("revote/nv.json") for p in lane_files(rd)))
        # S3 (live run 2026-10-19): a re-vote's probes live next to its verdict, under revote/
        os.makedirs(os.path.join(rd, "revote", "substantiveness--K.isProb.probes"))
        open(os.path.join(rd, "revote", "substantiveness--K.isProb.probes", "drop_h.lean"), "w").write("x")
        rvp = os.path.join(rd, "revote", "substantiveness--K.isProb.json")
        open(rvp, "w").write('{"checked": "substantiveness--K.isProb.probes/drop_h.lean compiles"}')
        say("a re-vote's cited probe under revote/<lane>.probes/ is found", check_lane(rvp, rd) == [])
        open(rvp, "w").write('{"checked": "substantiveness--K.isProb.probes/gone.lean compiles"}')
        say("... and a re-vote's missing probe is still flagged, as a lane fault",
            any("gone.lean" in p and flag_code(p) == "lane-fault" for p in check_lane(rvp, rd)))
        # A1/A2 settlement: the adjudication commit refuses until ADOPTED.md settles every NOTE
        wrd = os.path.join(d, "2026-01-03-ccccccc"); os.makedirs(os.path.join(wrd, "revote"))
        vp = os.path.join(wrd, "non-vacuity.json")
        open(vp, "w").write('{"next_step": "record in ADOPTED.md that x"}')
        fp_ = os.path.join(wrd, "correspondence.json")
        open(fp_, "w").write('{"checked": "see correspondence.probes/never.lean"}')
        pp_ = os.path.join(wrd, "paper-faithfulness.json")
        open(pp_, "w").write('{"checked": "audits/P/2026-01-01-aaaaaaa/ADOPTED.md"}')
        rv_ = os.path.join(wrd, "revote", "correspondence--N.a.json")
        open(rv_, "w").write('{"checked": "per ADOPTED.md and correspondence--N.a.probes/gone.lean"}')
        AP_ = os.path.join(wrd, "ADOPTED.md")
        TG_ = os.path.join(wrd, "TARGET.json")
        json.dump({k_: ["N.a"] for k_ in ("correspondence", "non-vacuity", "paper-faithfulness")}, open(TG_, "w"))
        HDR = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        def settle(body):
            open(AP_, "w").write(body); return settle_problems(wrd)
        none_ = settle(HDR)
        say("A1: every NOTE unsettled by an empty ADOPTED.md is named (mention, lane fault, path, re-vote fault)",
            all(any(x in p for p in none_) for x in ("non-vacuity.json", "correspondence.json",
                                                     "paper-faithfulness.json", "revote/correspondence--N.a.json")))
        good = (HDR + "| correspondence | N.a | Fail | **REVOTE NEEDED** | its probe was never written |\n"
                "| paper-faithfulness | (whole lane) | - | **REVOTE NEEDED** | it read another round's record |\n"
                "\n- CLEARED non-vacuity.json: advice text only, it names ADOPTED.md as a place to record\n"
                "- LEFT OPEN revote/correspondence--N.a.json: the re-vote's own probe is missing\n")
        say("A1/A2: a clearance, a whole-lane re-vote, an item re-vote and LEFT OPEN settle them", settle(good) == [])
        say("A1 condition 3: a path into another round is never settled by a clearance",
            any("paper-faithfulness.json" in p for p in settle(good.replace(
                "| paper-faithfulness | (whole lane) | - | **REVOTE NEEDED** | it read another round's record |\n", "")
                + "- CLEARED paper-faithfulness.json: harmless\n")))
        say("A1: an independence NOTE is settled by a whole-lane re-vote instead of a clearance",
            settle(good.replace("- CLEARED non-vacuity.json: advice text only, it names ADOPTED.md as a place to record\n",
                                "").replace(HDR, HDR + "| non-vacuity | (whole lane) | - | **REVOTE NEEDED** | independence |\n"))
            == [])
        say("A2: a lane fault is not settled by a clearance (it needs a re-vote)",
            any("correspondence.json" in p for p in settle(good.replace(
                "| correspondence | N.a | Fail | **REVOTE NEEDED** | its probe was never written |\n", "")
                + "- CLEARED correspondence.json: fine\n")))
        say("A2 condition 3: a re-vote lane's own fault is never re-voted again: it is LEFT OPEN, and its item undecided",
            any("LEFT OPEN" in p for p in settle(good.replace(
                "- LEFT OPEN revote/correspondence--N.a.json: the re-vote's own probe is missing\n", "")))
            and any("is decided" in p for p in settle(good + "\n" + HDR + "| correspondence | N.a | Fail | **REJECT** | re-vote |\n")))
        say("the report reads the clearances", clearances(wrd) == [
            ("non-vacuity.json", "advice text only, it names ADOPTED.md as a place to record")])
        for f_ in (vp, fp_, pp_, rv_, AP_, TG_):
            os.remove(f_)
        import lane_auth
        eg = os.path.join(d, "egit"); er = os.path.join(eg, "2026-01-04-ddddddd"); os.makedirs(os.path.join(er, "prompts"))
        subprocess.run(["git", "init", "-q", eg]); subprocess.run(["git", "-C", eg, "-c", "user.email=t@t", "-c", "user.name=t",
                                                                 "commit", "-q", "--allow-empty", "-m", "i"])
        for k_, v_ in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", eg, "config", k_, v_])
        ev = os.path.join(er, "correspondence.json"); epf = os.path.join(er, "prompts", "c.txt")
        open(epf, "w").write(f"Write that JSON object, and nothing else, to {ev}\n")
        etok = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(epf)).group(1)
        os.makedirs(os.path.join(er, "correspondence.probes")); open(os.path.join(er, "correspondence.probes", "w.lean"), "w").write("x")
        open(os.path.join(er, "correspondence.probes", "helper.lean"), "w").write("uncited")
        open(ev, "w").write(json.dumps({"lane_token": etok, "checked": "correspondence.probes/w.lean",
                                        "probes": lane_auth.probe_manifest(ev)}))
        lane_auth.seal(ev, lane_auth.sha(open(ev, "rb").read()), "a")
        ok0 = lane_problems(er, ev) == []
        eu = os.path.join(er, "non-vacuity.json"); epu = os.path.join(er, "prompts", "nv.txt")
        open(epu, "w").write(f"Write that JSON object, and nothing else, to {eu}\n")
        utok = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(epu)).group(1)
        os.makedirs(os.path.join(er, "non-vacuity.probes")); open(os.path.join(er, "non-vacuity.probes", "x.lean"), "w").write("x")
        open(eu, "w").write(json.dumps({"lane_token": utok, "probes": {}}))
        lane_auth.seal(eu, lane_auth.sha(open(eu, "rb").read()), "b")
        say("A3: what the seal recorded (an unlisted probe file) is a NOTE[lane-fault] of lanecheck",
            [flag_code(p) for p in lane_problems(er, eu)] == ["lane-fault"])
        open(os.path.join(er, "correspondence.probes", "helper.lean"), "w").write("changed after the seal")
        say("A3: an uncited probe changed after the seal commit is PROBLEM[evidence-after-seal] (tampering)",
            ok0 and any(flag_code(p) == "evidence-after-seal" and "helper.lean" in p and counts(p)
                        for p in lane_problems(er, ev)))
        os.remove(os.path.join(er, "correspondence.probes", "w.lean"))
        say("A3: a probe deleted after the seal commit is tampering; its citation is also a lane fault",
            any(flag_code(p) == "evidence-after-seal" and "w.lean" in p for p in lane_problems(er, ev))
            and any(flag_code(p) == "lane-fault" and "does not exist" in p for p in lane_problems(er, ev)))
        say("resolutions/ (other stalls' records) is a record lanes may not read",
            any("record files" in p for p in lane("x3.json", '{"checked": "see resolutions/S1/STALL.json"}')))
        os.makedirs(os.path.join(wrd, ".abandoned"))
        open(os.path.join(wrd, "revote", "substantiveness--K.thm.json"), "w").write("{}")
        open(os.path.join(wrd, "revote", "substantiveness--L.thm.json"), "w").write("{}")
        open(os.path.join(wrd, ".abandoned", "revote__substantiveness--K.thm.json"), "w").write("{}")
        open(os.path.join(wrd, "ABANDONED.json"), "w").write("{}")
        say("X7: an abandoned round's ABANDONED.json is not a lane file",
            "ABANDONED.json" not in [os.path.basename(p) for p in lane_files(wrd)])
        say("a set-aside re-vote lane is not a lane file; another re-vote is",
            [os.path.basename(p) for p in lane_files(wrd) if "revote" in p] == ["substantiveness--L.thm.json"])
        old_repo, old_audits = project.REPO, project.AUDITS
        try:
            project.REPO, project.AUDITS = tr, os.path.join(tr, "audits")
            os.makedirs(os.path.join(tr, "audits", "P", "R"))
            auth_problems = check_round({"rounds_dir": "audits/P"}, "R", processes=False)
            say("round check rejects missing lane token commitments",
                any("no lane token commitments" in p for p in auth_problems))
        finally:
            project.REPO, project.AUDITS = old_repo, old_audits

        say("a shell polling loop is recognised; a grep mentioning the words is not",
            LOOP_RE.search("bash -c until ! pgrep -f lake; do sleep 5; done") is not None
            and LOOP_RE.search("lake build Foo") is None
            and LOOP_RE.search("grep -E until|while .* sleep") is None)
        loop = subprocess.Popen(["bash", "-c", "until false; do sleep 1; done"], cwd=d)
        unrelated_dir = tempfile.mkdtemp(prefix="unrelated-project-")
        unrelated = subprocess.Popen(["bash", "-c", "until false; do sleep 1; done"], cwd=unrelated_dir)
        # the operator's own monitor, tagged; and a fallback lane process whose child loops elsewhere
        operator = subprocess.Popen(["bash", "-c", "until false; do sleep 1; done"], cwd=d,
                                    env=dict(os.environ, FORMALIZE_PAPER_OPERATOR="1"))
        lane_prompts = os.path.join(d, "audits", "P", "R", "prompts") + os.sep
        lane_proc = subprocess.Popen(["bash", "-c", f"until false; do sleep 1; done & wait # {lane_prompts}correspondence.txt"],
                                     cwd=unrelated_dir)
        time.sleep(0.3)
        lane_child = [int(c) for c in open(f"/proc/{lane_proc.pid}/task/{lane_proc.pid}/children").read().split()]
        real_run = subprocess.run
        def fixture_processes(cmd, *args, **kwargs):
            result = real_run(cmd, *args, **kwargs)
            if isinstance(cmd, list) and cmd[:2] == ["ps", "-u"]:
                allowed = {str(loop.pid), str(unrelated.pid), str(operator.pid)} | {str(c) for c in lane_child}
                result.stdout = "\n".join(line for line in result.stdout.splitlines()
                                          if line.strip().split(None, 1)[0] in allowed)
            return result
        # Even a mutant removing process ownership must never kill other real projects.
        # Keep real processes/cwds/kill calls, but expose only this selftest's two fixtures.
        subprocess.run = fixture_processes
        try:
            say("a loop older than the round is not touched",
                not any(str(loop.pid) in p for p in stray_loops(kill=False, since=time.time() + 3600, repo=d)))
            found = stray_loops(kill=True, repo=d, prompt_dir=lane_prompts)
            try:
                ended = loop.wait(timeout=5) is not None
            except subprocess.TimeoutExpired:
                ended = False
            say("a running polling loop is found and killed", any(str(loop.pid) in p for p in found) and ended)
            say("another project's loop is neither flagged nor killed",
                unrelated.poll() is None and not any(str(unrelated.pid) in p for p in found))
            say("the operator's tagged monitor (FORMALIZE_PAPER_OPERATOR=1) is neither flagged nor killed",
                operator.poll() is None and not any(str(operator.pid) in p for p in found))
            say("a loop started by a lane process is flagged and killed, even with its cwd elsewhere",
                bool(lane_child) and any(str(c) in p for c in lane_child for p in found))
        finally:
            subprocess.run = real_run
            if loop.poll() is None:
                loop.kill()
            unrelated.terminate(); unrelated.wait(timeout=5)
            operator.terminate(); operator.wait(timeout=5)
            for c in lane_child:
                try:
                    os.kill(c, 9)
                except OSError:
                    pass
            lane_proc.kill(); lane_proc.wait(timeout=5)
            shutil.rmtree(unrelated_dir, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    res += selftest_b7()
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


def selftest_b7():
    """B7 (U2 §7b, §7f): proof-by-contradiction steps and escalation records."""
    res = []
    def say(n, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    d = tempfile.mkdtemp(prefix="lanecheck-b7-")
    good = ('CONTRADICTION STEP: negated by `Ns.lemma_4_40`; paper (tex l.88): "Suppose, for a contradiction, '
            'that a counterexample exists." Field hbig set aside; witness non-vacuity.probes/w.lean')
    def nv(entries):
        return json.dumps({"lane": "non-vacuity", "verdicts": entries})
    try:
        top = os.path.join(d, "P"); rd = os.path.join(top, "2026-01-02-bbbbbbb")
        os.makedirs(os.path.join(rd, "non-vacuity.probes"))
        # the project the rounds dir belongs to (_project_configs): its paper .tex and its Lean
        os.makedirs(os.path.join(d, "audits", "projects"))
        json.dump({"rounds_dir": "P", "source_pdf": "paper.tex", "lean_files": ["Main.lean"]},
                  open(os.path.join(d, "audits", "projects", "p.json"), "w"))
        open(os.path.join(d, "paper.tex"), "w").write("\\begin{proof}\nSuppose, for a contradiction,  that a\n"
                                                      "counterexample exists. Then $x$ is big.\n\\end{proof}\n")
        open(os.path.join(d, "Main.lean"), "w").write("namespace Ns\ntheorem lemma_4_40 : True := trivial\n"
                                                      "namespace TI\ntheorem c450x : True := trivial\nend TI\nend Ns\n")
        open(os.path.join(rd, "non-vacuity.probes", "w.lean"), "w").write("x")
        f = os.path.join(rd, "non-vacuity.json")
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good}]))
        say("b7: a CONTRADICTION STEP Pass quoting the paper and naming the negating lemma is no lane fault",
            not any("CONTRADICTION" in p_ for p_ in check_lane(f, rd)))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass",
                                "checked": "CONTRADICTION STEP: the docstring at TI.lean:4 marks it as a step of "
                                           "Lemma 4.40's proof by contradiction"}]))
        flt = check_lane(f, rd)
        say("b7 benchmark: a CONTRADICTION STEP Pass resting on the docstring alone is a lane fault (re-voted)",
            any(flag_code(p_) == "lane-fault" and "docstring alone" in p_ for p_ in flt))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass",
                                "checked": good.replace("; paper (tex l.88): \"Suppose, for a contradiction, that a "
                                                        "counterexample exists.\"", "")}]))
        say("b7: a CONTRADICTION STEP Pass without the quoted passage is a lane fault",
            any("CONTRADICTION STEP" in p_ for p_ in check_lane(f, rd)))
        for why, txt, code in (("quotes a passage the matcher does not find in the paper's source is FLAGGED for the "
                                "adjudicator's ruling (quote-unmatched), never a lane fault (JUDGEMENT-SCAN 1)",
                                good.replace("Suppose, for a contradiction,", "Assume, towards a contradiction,"),
                                "quote-unmatched"),
                               ("names a negating lemma that is not declared is a lane fault",
                                good.replace("Ns.lemma_4_40", "no_such_lemma"), "lane-fault")):
            open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": txt}]))
            fl_ = check_lane(f, rd)
            say(f"b7 review 2: a well-formed CONTRADICTION STEP Pass that {why}",
                any(flag_code(p_) == code and "CONTRADICTION STEP" in p_ for p_ in fl_)
                and (code == "lane-fault" or not any(flag_code(p_) == "lane-fault" for p_ in fl_)))
        # JUDGEMENT-SCAN 1 (coordinator 2026-10-26): a quote of a real passage behind a LaTeX macro the normaliser cannot
        # undo (\newcommand) is flagged; the adjudicator's one ruling settles it -- no re-vote, and a re-vote lane's own
        # flagged quote is settled the same way (no loop, no human stop)
        with open(os.path.join(d, "paper.tex"), "a") as fh:
            fh.write("\\newcommand{\\Linf}{L^\\infty}\nAssume the norm in $\\Linf$ is attained, for a contradiction.\n")
        mq = good.replace("Suppose, for a contradiction, that a counterexample exists.",
                          "Assume the norm in L^infinity is attained, for a contradiction.")
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": mq}]))
        fq = check_lane(f, rd)
        os.makedirs(os.path.join(rd, "revote"), exist_ok=True)
        fr = os.path.join(rd, "revote", "non-vacuity--Ns.TI.c450x.json")
        open(fr, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": mq}]))
        fqr = check_lane(fr, rd)
        rows_ = ("| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                 "| non-vacuity | Ns.TI.c450x | Pass | **ADOPT** | the step is the paper's |\n")
        ap_ = os.path.join(rd, "ADOPTED.md")
        open(ap_, "w").write(rows_)
        unruled = settle_problems(rd, flags=fq)
        _ln = next(i for i, l in enumerate(open(os.path.join(d, "paper.tex")).read().splitlines(), 1) if "Linf" in l)
        open(ap_, "w").write(rows_ + f"\nQUOTE RULED non-vacuity.json | Ns.TI.c450x | in the paper at tex l.{_ln}: "
                                     "\\Linf is L^\\infty\n")
        ruled_ok = settle_problems(rd, flags=fq)
        open(ap_, "w").write(rows_ + "\nQUOTE RULED non-vacuity.json | Ns.TI.c450x | not in the paper: no such line\n")
        ruled_no = settle_problems(rd, flags=fq)
        open(ap_, "w").write(rows_ + "\nQUOTE RULED revote/non-vacuity--Ns.TI.c450x.json | Ns.TI.c450x | in the paper "
                                     f"at tex l.{_ln}\n")
        ruled_rv = settle_problems(rd, flags=[p_ for p_ in fqr if flag_code(p_) == "quote-unmatched"])
        open(ap_, "w").write(rows_ + "\nQUOTE RULED non-vacuity.json | Ns.TI.c450x | in the paper at tex l.9999\n")
        ruled_far = settle_problems(rd, flags=fq)
        os.remove(ap_); os.remove(fr)
        say("JUDGEMENT-SCAN 1: a quote behind a LaTeX macro is flagged (quote-unmatched, no lane fault); unruled it is "
            "unsettled; the adjudicator's \"in the paper at tex l.N\" settles it with no re-vote; \"not in the paper\" "
            "needs the item's REVOTE NEEDED row; a re-vote lane's flagged quote is settled by the ruling, with no "
            "LEFT OPEN and no second re-vote",
            any(flag_code(p_) == "quote-unmatched" for p_ in fq) and not any(flag_code(p_) == "lane-fault" for p_ in fq)
            and any(flag_code(p_) == "quote-unmatched" for p_ in fqr)
            and any("needs the adjudicator's ruling" in x for x in unruled) and ruled_ok == []
            and any("REVOTE NEEDED row for the item" in x for x in ruled_no) and ruled_rv == [])
        say("review L1: a QUOTE RULED line citing a tex line the paper does not have is refused (a fact; no content match)",
            any("correct the QUOTE RULED line" in x for x in ruled_far))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good.replace(
            "that a counterexample exists.", "that a counterexample ... is big.")}]))
        say("b7 review 2: the quote is found across the source's line breaks and spacing, an omission marked \"...\"",
            not any("CONTRADICTION" in p_ for p_ in check_lane(f, rd)))
        # re-check 2: honest quotes of multi-line passages, written as a lane writes them: other spacing,
        # `$` dropped, \\emph dropped, \\pmod{7}
        with open(os.path.join(d, "paper.tex"), "a") as fh:
            fh.write(('\\item[(b)] If $x_n$ and $x_{n+1}$ are both positive, then $x_{n+2}$ is positive.\n'
                     '$h(-n)=\\max(u(n+1),u(n))=h(n)$; moreover $n\\equiv 1\\pmod 7$ exactly when\n'
                     '$2n+3\\equiv 5\\pmod 7$. Thus it suffices to treat $n\\ge 0$. By\n'
                     'For integers $r\\ge 1$ and $s\\ge 0$, the \\emph{chain count} $C_s(r)$ is the number of\n'
                     'the $s$-element chains in the grid of side $r$:\n'
                     '$b^s=(b^{q-1})^t\\equiv 1\\pmod q$ by Proposition~\\ref{prop:aux}. Hence each\n'
                     'of the $q+3$ blocks of $C_s(q)$ is congruent to $1$, and\n'
                     '$C_s(q)\\equiv q+3\\equiv 3\\pmod q$.\n'))
        honest = ["If $x_n$ and $x_{n + 1}$ are both positive, then $x_{n + 2}$ is positive.",
                  "moreover $n \\equiv 1 \\pmod 7$ exactly when $2n + 3 \\equiv 5 \\pmod{7}$. Thus it suffices "
                  "to treat $n \\ge 0$.",
                  "the chain count $C_s(r)$ is the number of the $s$-element chains in the grid of side r",
                  "Hence each of the $q + 3$ blocks of $C_s(q)$ is congruent to $1$, and $C_s(q) \\equiv q + 3 "
                  "\\equiv 3 \\pmod q$.",
                  "For integers $r \\ge 1$ ... the \\emph{chain count} ... of side $r$:"]
        bad_q = ["moreover $n \\equiv 2 \\pmod 7$ exactly when $2n + 3 \\equiv 5 \\pmod{7}$.",
                 "the chain count $C_s(r)$ is the number of the $s$-element chains in the grid of size $r$",
                 "Hence each of the $q + 4$ blocks of $C_s(q)$ is congruent to $1$"]
        def faults_for(q_):
            open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good.replace(
                "Suppose, for a contradiction, that a counterexample exists.", q_)}]))
            return [p_ for p_ in check_lane(f, rd) if "CONTRADICTION" in p_]
        hf = {q_: faults_for(q_) for q_ in honest}
        say("re-check 2: an honest quote of the paper differing only in spacing, `$`, \\pmod{7} braces or a dropped "
            "\\emph (multi-line, real passages) is no lane fault", not any(hf.values()))
        say("re-check 2: a quote that is not in the paper (a changed number or word) is still flagged (for the adjudicator's "
            "ruling, JUDGEMENT-SCAN 1)",
            all(any(flag_code(p_) == "quote-unmatched" for p_ in faults_for(q_)) for q_ in bad_q))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass",
                                "checked": "Contradiction step: the docstring at TI.lean:4 says so"}]))
        say("b7 review 4: the marker in another case (\"Contradiction step:\") is read as the marker (a lane fault "
            "without the form)", any("CONTRADICTION STEP" in p_ for p_ in check_lane(f, rd)))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": "Witness w.lean. It is not a "
                                "proof-by-contradiction step: no docstring or passage marks it."}]))
        say("b7 review 4: prose saying an item is \"not a proof-by-contradiction step:\" claims no step",
            not any("CONTRADICTION" in p_ for p_ in check_lane(f, rd)))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good.replace(
            '"Suppose, for a contradiction, that a counterexample exists."', "as the docstring at TI.lean:4 says")}]))
        say("b7: a CONTRADICTION STEP Pass naming the lemma but citing the docstring instead of quoting the paper is a "
            "lane fault", any("CONTRADICTION STEP" in p_ for p_ in check_lane(f, rd)))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Ambiguous", "question": "CONTRADICTION STEP?"},
                               {"item": "Ns.a", "verdict": "Pass", "checked": "witness non-vacuity.probes/w.lean; "
                                "not a proof-by-contradiction step"}]))
        say("b7: an Ambiguous entry, and a Pass that merely mentions a proof by contradiction, are no lane fault",
            not any("CONTRADICTION" in p_ for p_ in check_lane(f, rd)))
        g = os.path.join(rd, "correspondence.json")
        open(g, "w").write(nv([{"item": "x", "verdict": "Pass", "checked": "CONTRADICTION STEP: docstring"}]))
        say("b7: only non-vacuity lanes are read for contradiction steps", contradiction_faults(g) == [])
        os.remove(g)
        open(f, "w").write(nv([{"item": "Ns.TI.c450x (section TI)", "verdict": "Pass", "checked": good}]))
        say("b7: an unadjudicated round asks for no VACUOUS.md row yet", contradiction_problems(top) == [])
        open(os.path.join(rd, "ADOPTED.md"), "w").write("| # | lane | item | decision |\n|---|---|---|---|\n")
        cp = contradiction_problems(top)
        say("b7: an adjudicated round whose passed contradiction step has no VACUOUS.md row is a problem",
            len(cp) == 1 and "Ns.TI.c450x" in cp[0] and "lemma_4_40" in cp[0])
        vac = ("| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
               "|---|---|---|---|---|---|---|\n")
        open(os.path.join(top, "VACUOUS.md"), "w").write(vac + "| 1 | Lemma 4.40 section | all | x | x | r | open |\n")
        say("b7: a VACUOUS.md row naming neither the step nor its lemma (plain words only) does not count",
            len(contradiction_problems(top)) == 1)
        open(os.path.join(top, "VACUOUS.md"), "w").write(
            vac + "| 1 | proof-by-contradiction section of `Ns.lemma_4_40` | all | x | x | r | open |\n")
        say("b7: a VACUOUS.md row naming the negating lemma lists the section", contradiction_problems(top) == [])
        open(os.path.join(top, "VACUOUS.md"), "w").write(vac + "| 1 | `Ns.TI.c450x` (section TI) | all | x | x | r | open |\n")
        say("b7: a VACUOUS.md row naming the step lists it", contradiction_problems(top) == [])
        open(os.path.join(top, "VACUOUS.md"), "w").write(
            vac + "| 1 | Not vacuous | all | `Ns.TI.c450x` and `Ns.lemma_4_40` are fine | x | r | dismissed |\n")
        say("b7 review 2: a row naming the step outside its statement cell, or one dismissed, does not list it",
            len(contradiction_problems(top)) == 1)
        open(os.path.join(top, "VACUOUS.md"), "w").write(
            vac + "| 1 | `Ns.TI.c450x` (section TI) | all | x | x | r | dismissed |\n")
        say("b7 review 2: a row naming the step whose status is neither open nor repaired does not list it",
            len(contradiction_problems(top)) == 1)
        open(os.path.join(top, "VACUOUS.md"), "w").write(
            vac + "| 1 | Not vacuous | all | `Ns.TI.c450x` and `Ns.lemma_4_40` are fine | x | r | open |\n")
        say("b7 review 2: an open row naming the step only outside its statement cell does not list it",
            len(contradiction_problems(top)) == 1)
        open(os.path.join(top, "VACUOUS.md"), "w").write(vac + "| 1 | `c450x_aux`, `TI.c450x2`, `Other.c450x` | all | x | x | r | open |\n")
        say("b7 review 2: a row naming another declaration that shares a part of the step's name does not list it",
            len(contradiction_problems(top)) == 1)
        open(os.path.join(top, "VACUOUS.md"), "w").write(vac + "| 1 | section of `TI.c450x` | all | x | x | r | open |\n")
        say("b7 review 2: a row naming the step by a shorter qualified name lists it", contradiction_problems(top) == [])
        os.remove(os.path.join(top, "VACUOUS.md"))
        open(os.path.join(rd, project.ABANDONED), "w").write("{}")
        say("b7: a set-aside round is not read", contradiction_problems(top) == [])
        os.remove(os.path.join(rd, project.ABANDONED))
        # review 3: a Pass the adjudicator or a re-vote overturned demands no row (rule G)
        json.dump({"non-vacuity": ["Ns.TI.c450x"]}, open(os.path.join(rd, "TARGET.json"), "w"))
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good}]))
        hdr = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        def adopted(*rows_):
            open(os.path.join(rd, "ADOPTED.md"), "w").write(hdr + "".join(r_ + "\n" for r_ in rows_))
        adopted("| non-vacuity | Ns.TI.c450x | Pass | **ADOPT** list it in VACUOUS.md | x |")
        say("b7 review 3: an adopted contradiction-step Pass still needs its row", len(contradiction_problems(top)) == 1)
        rv_ = "| non-vacuity | Ns.TI.c450x | Pass | **REVOTE NEEDED** docstring only | x |"
        adopted(rv_)
        say("b7 review 3: a Pass put to a re-vote (REVOTE NEEDED) needs no row", contradiction_problems(top) == [])
        adopted("| non-vacuity | (whole lane) | - | **REVOTE NEEDED** lane fault | x |")
        say("b7 review 3: a Pass whose whole lane is re-voted needs no row", contradiction_problems(top) == [])
        adopted("| non-vacuity | Ns.TI.c450x | Pass | **QUESTION** a step on a docstring | x |")
        say("b7 review 3: a Pass the adjudicator made a QUESTION row needs no row", contradiction_problems(top) == [])
        os.makedirs(os.path.join(rd, "revote"), exist_ok=True)
        rvf = os.path.join(rd, "revote", "non-vacuity--Ns.TI.c450x.json")
        open(rvf, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good}]))
        adopted(rv_)
        cp = contradiction_problems(top)
        say("b7 review 3: the re-vote's own contradiction-step Pass needs the row",
            len(cp) == 1 and "revote/" in cp[0])
        adopted(rv_, "| revote/non-vacuity--Ns.TI.c450x | Ns.TI.c450x | Ambiguous | **QUESTION** still a docstring | x |")
        say("b7 review 3: a re-vote Pass the adjudicator then made a QUESTION row needs no row",
            contradiction_problems(top) == [])
        adopted(rv_, "| revote/non-vacuity--Ns.TI.c450x | Ns.TI.c450x | Fail | **ADOPT** no step | x |")
        say("b7 review 3: a re-vote Pass whose row records a Fail needs no row", contradiction_problems(top) == [])
        os.remove(rvf)
        open(os.path.join(rd, "ADOPTED.md"), "w").write("| # | lane | item | decision |\n|---|---|---|---|\n")
        import make_report as _mr
        open(f, "w").write(nv([{"item": "Ns.TI.c450x", "verdict": "Pass", "checked": good}]))
        rp = [x for x in _mr.record_problems(top) if "proof by contradiction" in x]
        say("b7: the report check holds it as adj-record (PENDING; the next adjudication clears it)",
            len(rp) == 1 and getattr(rp[0], "code", None) == "adj-record")
        res += _selftest_escalation(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


def _selftest_escalation(d):
    """U2 §7f: prompt.py builds, writes once and commits the escalation prompt with its hash; lanecheck accepts
    the answer only while the prompt is that file, and commits the answer."""
    import prompt as _pr, make_report as _mr
    res = []
    def say(n, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    tr = os.path.join(d, "esc"); au = os.path.join(tr, "audits"); os.makedirs(os.path.join(au, "P"))
    open(os.path.join(tr, "paper.tex"), "w").write("".join(f"line {i}\n" for i in range(1, 21)))
    open(os.path.join(tr, "Main.lean"), "w").write("theorem main_thm : True := trivial\ntheorem side_bound : True := "
                                                   "trivial\ntheorem deg_sum : True := trivial\n"
                                                   "theorem fresh_one : True := trivial\n"
                                                   "theorem main_thm_aux : True := trivial\n")
    for c in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", "-C", au] + c, capture_output=True)
    tmpl = json.load(open(os.path.join(project.AUDITS, "project_template.json"), encoding="utf-8"))
    cfg = dict(tmpl, name="p", title="t", source_pdf="paper.tex", source_id="x:1", source_cite="c", branch="b",
               base_commit="0", lean_files=["Main.lean"], build_cmds=["true"], namespace="Ns", rounds_dir="audits/P",
               work_dir=".w", blind_spots="none", goal_results=["Theorem 1"], involvement="involved",
               involvement_answer="default", calibration={}, _path=os.path.join(project.AUDITS, "project_template.json"))
    keep = (project.REPO, _mr.REPO)
    try:
        project.REPO = _mr.REPO = tr
        text = _pr.load(_pr.DEFAULT)
        try:
            _pr.escalation_inputs(cfg, "  ")
            empty = False
        except ValueError:
            empty = True
        say("b7 escalate: an empty question is refused", empty)
        bad = []
        for kw in ({"decl": "Ns.nope"}, {}, {"decl": "main_thm", "passage": "tex l.30"},
                   {"decl": "main_thm", "passage": "page 3"}, {"decl": "main_thm", "passage": "l.5-200"}):
            try:
                _pr.escalation_inputs(cfg, "q", **kw); bad.append(False)
            except ValueError:
                bad.append(True)
        say("b7 escalate: an undeclared --decl, no --decl (re-check 3), a passage beyond the source, not a line "
            "locator, or too long is refused",
            all(bad))
        inp = _pr.escalation_inputs(cfg, "May lemma <X> be stated over ℕ?", "main_thm", "tex l.3-4")
        say("b7 escalate: the inputs carry the declaration's File.lean:N and the quoted lines",
            inp.get("decl_at") == "Main.lean:1" and inp.get("passage_text") == "line 3\nline 4")
        name, p_, h_ = _pr.write_escalation(text, cfg, inp)
        body = open(p_, encoding="utf-8").read()
        log = subprocess.run(["git", "-C", au, "log", "-1", "--format=%s%n%b"], capture_output=True, text=True).stdout
        say("b7 escalate: the prompt is written once as E1, committed \"escalate E1\" with its sha256",
            name == "E1" and log.startswith("escalate E1\n") and f"prompt sha256: {h_}" in log
            and "COMMON RULES FOR EVERY SUBAGENT" in body and "May lemma <X> be stated" in body
            and "`main_thm` (Main.lean:1)" in body and "    line 3\n    line 4" in body
            and "audits/P/escalations/E1.answer.md" in body and "NEEDS-HUMAN" in body)
        v, pr_ = escalation_check(cfg, "E1")
        say("b7 escalate: no answer yet is refused", v is None and any("no answer yet" in x for x in pr_))
        ans = _pr.escalation_paths(cfg, "E1")[1]
        open(ans, "w").write("Let me think.\nANSWERABLE: yes, see tex l.3\n")
        v, pr_ = escalation_check(cfg, "E1", agent_id="a1", returned="Let me think.")
        say("b7 escalate: an answer that is not one NEEDS-HUMAN/ANSWERABLE line is refused",
            v is None and any("is not one line" in x for x in pr_))
        import integrity as _ig
        say("b7 escalate: prompt and answer are records of `escalate`; a new answer waits for lanecheck without an "
            "integrity failure, a changed committed one does not",
            _ig.owner("escalations/E1.answer.md") == ("escalate ",) == _ig.owner("escalations/E1.prompt.txt")
            and _ig.waiting_answer("?? audits/P/escalations/E1.answer.md", "escalations/E1.answer.md")
            and not _ig.waiting_answer(" M audits/P/escalations/E1.answer.md", "escalations/E1.answer.md")
            and not _ig.waiting_answer("?? audits/P/escalations/E1.prompt.txt", "escalations/E1.prompt.txt"))
        open(ans, "w").write("ANSWERABLE: yes, see tex l.3\n")
        head0 = subprocess.run(["git", "-C", au, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        v, pr_ = escalation_check(cfg, "E1")
        say("b7 review 1: an answer with no subagent record (no --agent-id / --returned) is refused, not committed",
            v is None and any("no subagent record" in x for x in pr_)
            and subprocess.run(["git", "-C", au, "rev-parse", "HEAD"], capture_output=True, text=True).stdout == head0)
        v, pr_ = escalation_check(cfg, "E1", returned="ANSWERABLE: yes, see tex l.3")
        say("b7 review 1: an answer with the returned line but no agent id is refused",
            v is None and any("no subagent record" in x for x in pr_))
        v, pr_ = escalation_check(cfg, "E1", agent_id="a1", returned="ANSWERABLE: no, see tex l.4")
        say("b7 review 1: an answer file that is not the line the subagent returned is refused",
            v is None and any("not the line the escalation subagent returned" in x for x in pr_))
        v, pr_ = escalation_check(cfg, "E1", commit=False)
        say("b7 review 1: an uncommitted answer is not accepted yet (the report's reading)",
            v is None and any("not accepted yet" in x for x in pr_))
        v, pr_ = escalation_check(cfg, "E1", agent_id="a1", returned="Checked.\nANSWERABLE: yes, see tex l.3")
        log = subprocess.run(["git", "-C", au, "log", "-1", "--format=%s%n%b"], capture_output=True, text=True).stdout
        say("b7 escalate: a valid answer to the recorded prompt is accepted and committed as its answer, with the "
            "subagent's id and the sha256 of its returned line",
            v == "ANSWERABLE: yes, see tex l.3" and pr_ == [] and log.startswith("escalate E1 (answer)\n")
            and "agent: a1" in log and "returned sha256: " in log)
        v2, pr2 = escalation_check(cfg, "E1")
        say("b7 escalate: checking it again changes nothing", v2 == v and pr2 == [])
        open(p_, "a").write("Hint: the answer is ANSWERABLE.\n")
        v, pr_ = escalation_check(cfg, "E1")
        say("b7 escalate: a prompt changed after its hash was recorded is refused (mismatched hash)",
            v is None and any("sha256" in x for x in pr_) and any("uncommitted" in x for x in pr_))
        subprocess.run(["git", "-C", au, "checkout", "-q", "--", os.path.relpath(p_, au)])
        # a hand-composed prompt committed with a matching hash of its own: the fresh rendering refuses it
        p2 = _pr.escalation_paths(cfg, "E2")[0]
        fake = body.replace("Interrupting the human is expensive.", "The human is waiting.")
        open(p2, "w").write(fake)
        import hashlib
        subprocess.run(["git", "-C", au, "add", os.path.relpath(p2, au)], capture_output=True)
        subprocess.run(["git", "-C", au, "commit", "-q", "-m", "escalate E2\n\nprompt sha256: "
                        + hashlib.sha256(fake.encode()).hexdigest() + "\ninputs: "
                        + json.dumps(dict(inp, decl="side_bound", decl_at="Main.lean:2"))], capture_output=True)
        open(_pr.escalation_paths(cfg, "E2")[1], "w").write("ANSWERABLE: x\n")
        v, pr_ = escalation_check(cfg, "E2")
        say("b7 escalate: a hand-composed prompt with a hash of its own is refused (not what prompt.py renders)",
            v is None and any("by hand" in x for x in pr_))
        name3, p3, _h3 = _pr.write_escalation(text, cfg, _pr.escalation_inputs(cfg, "Another?", "side_bound"))
        subprocess.run(["git", "-C", au, "add", os.path.relpath(p3, au)], capture_output=True)
        open(p3, "a").write("\n")
        subprocess.run(["git", "-C", au, "commit", "-q", "-am", "operator: tidy"], capture_output=True)
        open(_pr.escalation_paths(cfg, name3)[1], "w").write("NEEDS-HUMAN: only the human\n")
        v, pr_ = escalation_check(cfg, name3)
        say("b7 escalate: the next one is E3; a prompt recommitted under another message is refused",
            name3 == "E3" and v is None and any("committed once" in x for x in pr_))
        say("b7 escalate: a malformed name is refused", escalation_check(cfg, "E0")[0] is None
            and escalation_check(cfg, "x")[1])
        # review 1 repro: E4 NEEDS-HUMAN accepted; E5 a leading rephrase answered ANSWERABLE by hand
        def esc(q_, decl_=None):
            return _pr.write_escalation(text, cfg, _pr.escalation_inputs(cfg, q_, decl_))[0]
        n4 = esc("May `main_thm` drop its hypothesis that the graph is connected?", "main_thm")
        open(_pr.escalation_paths(cfg, n4)[1], "w").write("NEEDS-HUMAN: dropping it changes the theorem\n")
        escalation_check(cfg, n4, agent_id="a4", returned="NEEDS-HUMAN: dropping it changes the theorem")
        n5 = esc("Since the connectedness hypothesis of main_thm is unused, it is fine to drop it, right?", "main_thm")
        a5 = _pr.escalation_paths(cfg, n5)[1]
        open(a5, "w").write("ANSWERABLE: yes\n")
        subprocess.run(["git", "-C", au, "add", os.path.relpath(a5, au)], capture_output=True)
        subprocess.run(["git", "-C", au, "commit", "-q", "-m", f"escalate {n5} (answer)"], capture_output=True)
        recs = {e["name"]: e for e in escalations(cfg)}
        say("b7 review 1: an answer committed by hand (no subagent record) is not accepted",
            recs[n5]["answer"] is None and any("subagent's record" in x for x in recs[n5]["problems"]))
        n6 = esc("Is it fine to drop main_thm's connectedness hypothesis, which no proof uses?", "Ns.main_thm")
        open(_pr.escalation_paths(cfg, n6)[1], "w").write("ANSWERABLE: yes, unused\n")
        escalation_check(cfg, n6, agent_id="a6", returned="ANSWERABLE: yes, unused")
        n7 = esc("Which Mathlib lemma gives the bound on the degree sum?", "deg_sum")
        open(_pr.escalation_paths(cfg, n7)[1], "w").write("ANSWERABLE: Finset.sum_le_sum\n")
        escalation_check(cfg, n7, agent_id="a7", returned="ANSWERABLE: Finset.sum_le_sum")
        recs_l = escalations(cfg)
        recs = {e["name"]: e for e in recs_l}
        say("b7 review 1: every escalation is listed in order with its answer or why it has none",
            [e["name"] for e in recs_l] == [f"E{i}" for i in range(1, 8)]
            and recs["E1"]["answer"] == "ANSWERABLE: yes, see tex l.3" and recs["E2"]["answer"] is None
            and recs[n4]["answer"].startswith("NEEDS-HUMAN"))
        say("b7 review 1: a later escalation on the same matter as an earlier NEEDS-HUMAN is flagged as its re-ask "
            "(the same declaration, also qualified further); one on another declaration is not",
            recs[n6]["reask_of"] == n4 and recs[n5]["reask_of"] == n4 and recs[n7]["reask_of"] is None
            and recs["E1"]["reask_of"] is None and recs["E3"]["reask_of"] == "E2")
        ln = escalation_line(recs[n6], recs)
        say("b7 review 1: the report line of a re-ask shows the earlier NEEDS-HUMAN and its answer",
            f"RE-ASKS escalation {n4}" in ln and "dropping it changes the theorem" in ln and "ANSWERABLE: yes, unused" in ln)
        _lq = dict(recs[n6], inputs=dict(recs[n6]["inputs"], question="Q " + "word " * 80 + "ENDQZ?"))
        say("trial #9: the escalation's question is quoted whole in the report and the decisions document (never clipped)",
            "word ENDQZ?\"" in escalation_line(_lq, recs) and "…" not in escalation_line(_lq, recs))
        ci = escalation_citations(cfg, f"[DELEGATED ...] dropped it per escalation {n6}; see escalation E9 and "
                                       f"escalation {n5}; escalation {n7}", recs_l)
        say("b7 review 1: under involved, citing the re-ask is refused (the human's question); citing an escalation "
            "never written or not accepted is refused; an accepted unrelated one is not",
            len(ci) == 3 and any(n6 in x and "human" in x for x in ci) and any("E9" in x and "never written" in x for x in ci)
            and any(n5 in x and "not accepted" in x for x in ci) and not any(f"escalation {n7}," in x for x in ci))
        ci_h = escalation_citations(dict(cfg, involvement="hands-off"), f"per escalation {n6}", recs_l)
        say("b7 review 1: under a delegating level the re-ask is flagged in the record, not refused", ci_h == [])
        # the report lists every escalation; the report and decisions checks read the log's citations
        el = _mr.escalation_list(_mr.escalation_items(cfg))
        say("b7 review 1: the report lists every escalation with its answer, the re-asks marked",
            all(f"escalation E{i}:" in el for i in range(1, 8)) and el.count("RE-ASKS escalation") == 3
            and "NOT ACCEPTED" in el and "Finset.sum_le_sum" in el)
        import decisions as _dc
        open(os.path.join(au, "P", "RUN_LOG.md"), "w").write(
            f"# Run log\n## Open questions\n- dropped the hypothesis per escalation {n6}\n")
        dp = [x for x in _mr.delegation_problems(cfg) if "escalation" in x]
        rp_ = [x for x in _dc.record_problems(cfg) if "escalation" in x]
        say("b7 review 1: the report check and decisions --check refuse a log citing a re-ask under involved "
            "(report: code decisions)", len(dp) == 1 and getattr(dp[0], "code", None) == "decisions" and len(rp_) == 1)
        note = _dc.escalation_note(cfg, f"per escalation {n6}")
        say("b7 review 1: DECISIONS.md's skeleton shows a cited re-ask with the earlier NEEDS-HUMAN and both answers",
            f"escalation {n4}:" in note and f"escalation {n6}:" in note and note.index(f"escalation {n4}:")
            < note.index(f"escalation {n6}:") and _dc.escalation_note(cfg, "nothing cited") == "")
        sec = (f"## 1. Drop it\n<!-- item:x -->\nRun log: per escalation {n6}\n\n" + "{note}"
               + "**Paper:** Not applicable: x\n\n**Lean:** Not applicable: x\n\n**Evidence:** Not applicable: x\n\n"
               "**Options, and what each changes:** keep or drop\n\n**Recommendation:** per escalation " + n7 + "\n\n"
               "**Decision taken:** [DELEGATED 2026-01-01, operator under hands-off (intake); reversal: none] dropped; "
               "reverse it by restoring the hypothesis\n")
        note = _dc.escalation_note(cfg, f"per escalation {n6}; escalation {n7}")
        cut = [x for x in _dc.check(sec.format(note=""), ["x"], escalations=recs_l) if "escalation" in x]
        full = [x for x in _dc.check(sec.format(note=note), ["x"], escalations=recs_l) if "escalation" in x]
        # the E4 line dropped, and the re-ask mark of the E6 line
        part = re.sub(r" -- RE-ASKS [^\n]*", "", note.replace(note.split("\n")[2] + "\n", ""))
        half = [x for x in _dc.check(sec.format(note=part), ["x"], escalations=recs_l) if "escalation" in x]
        say("b7 review 1: a DECISIONS.md section citing an escalation must show its answer, and for a re-ask the "
            "earlier NEEDS-HUMAN with its answer", len(cut) >= 2 and full == [] and f"escalation {n4}:" not in part
            and len(half) == 1 and "re-ask" in half[0])
        rec_p = [x for x in _dc.check(sec.format(note=note), ["x"], level="hands-off", escalations=recs_l)
                 if "Recommendation cites its source" in x]
        rec_p2 = [x for x in _dc.check(sec.format(note=note).replace("per escalation " + n7 + "\n\n", "per escalation "
                                                                     + n4 + "\n\n"), ["x"], level="hands-off",
                                       escalations=recs_l) if "Recommendation cites its source" in x]
        say("b7 review 1: under a delegating level a Recommendation citing an accepted ANSWERABLE escalation cites its "
            "source; one citing a NEEDS-HUMAN does not", rec_p == [] and len(rec_p2) == 1)
        # re-check 1: the returned message, with backticks, $, quotes and newlines, saved by a quoted heredoc
        n8 = esc("Is `Main.lean:1` stated for every $n$?", "main_thm")
        a8 = "ANSWERABLE: yes, `main_thm` (Main.lean:1) holds for all `n : ℕ`; cost $5, \"as stated\" -- it's $(n)"
        open(_pr.escalation_paths(cfg, n8)[1], "w").write(a8 + "\n")
        msg = ("I read `Main.lean:1` and tex l.3.\nIt says $x_{n+1}$ and `$(whoami)` and 'single' \"double\"\n\n"
               + a8)
        rf = os.path.join(d, "returned-e8.txt")
        subprocess.run(["bash", "-c", f"cat > {rf} <<'RETURNED'\n{msg}\nRETURNED\n"], cwd=d)
        dq = subprocess.run(["bash", "-c", f'printf %s "{msg}"'], cwd=d, capture_output=True, text=True).stdout
        import contextlib, io
        def cli(*args_):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_ = escalation_cli(cfg, n8, *args_)
            return rc_, buf.getvalue()
        both = cli("a8", "x", rf)
        mangled = cli("a8", dq)
        open(rf + ".bad", "w").write(msg.replace("$5", "$6"))
        tampered = cli("a8", None, rf + ".bad")
        missing = cli("a8", None, rf + ".none")
        nofile_yet = escalation_check(cfg, n8, commit=False)[0]
        ok = cli("a8", None, rf)
        log = subprocess.run(["git", "-C", au, "log", "-1", "--format=%s%n%b"], capture_output=True, text=True).stdout
        say("re-check 1: --returned-file takes the returned message verbatim (backticks, $, quotes, newlines, saved "
            "by a quoted heredoc) and commits the answer; the same message as --returned \"...\" is mangled by the "
            "shell and refused, pointing at --returned-file and the quoted heredoc",
            open(rf, encoding="utf-8").read() == msg + "\n" and dq != msg and mangled[0] == 1
            and "--returned-file" in mangled[1] and "<<'RETURNED'" in mangled[1] and nofile_yet is None
            and ok[0] == 0 and a8 in ok[1] and log.startswith(f"escalate {n8} (answer)\n") and "agent: a8" in log
            and escalation_check(cfg, n8)[0] == a8)
        say("re-check 1: the answer file must still match the returned message: a file whose last line differs is "
            "refused; both --returned and --returned-file, or an unreadable file, are refused",
            tampered[0] == 1 and "not the line the escalation subagent returned" in tampered[1]
            and both[0] == 2 and missing[0] == 2)
        # re-check 3: the same matter is keyed on the declarations named, never on the wording
        n9 = esc("Is ℤ the intended domain here, rather than ℕ?", "main_thm")
        open(_pr.escalation_paths(cfg, n9)[1], "w").write("ANSWERABLE: yes, ℤ\n")
        escalation_check(cfg, n9, agent_id="a9", returned="ANSWERABLE: yes, ℤ")
        n10 = esc("Should `main_thm` and this lemma share the domain?", "deg_sum")
        n11 = esc("Is ℤ the intended domain here, rather than ℕ?", "fresh_one")
        n12 = esc("Can the bound be strict?", "fresh_one")
        open(_pr.escalation_paths(cfg, n12)[1], "w").write("ANSWERABLE: yes\n")
        escalation_check(cfg, n12, agent_id="a12", returned="ANSWERABLE: yes")
        n13 = esc("May the lemma deg_sum_aux hold for main_thm_x too?", "side_bound")
        n14 = esc("Is the bound tight?", "main_thm_aux")
        recs_l = escalations(cfg)
        recs = {e["name"]: e for e in recs_l}
        say("re-check 3: a rephrased re-ask with no shared wording, on the declaration of an earlier NEEDS-HUMAN, is "
            "its re-ask; so is one whose question names that declaration (backticked) under another --decl",
            recs[n9]["reask_of"] == n4 and recs[n10]["reask_of"] == n4
            and escalation_citations(cfg, f"per escalation {n9}", recs_l)
            and "RE-ASKS escalation " + n4 in escalation_line(recs[n9], recs))
        say("re-check 3: a later escalation on a declaration whose earlier escalation has no accepted answer is its "
            "re-ask (citing it under involved is refused); another declaration, or a name sharing only a part "
            "(`main_thm_x`, `main_thm_aux`), is no re-ask",
            recs[n11]["reask_of"] is None and recs[n12]["reask_of"] == n11
            and any("no accepted answer" in x and "human" in x for x in escalation_citations(cfg, f"per escalation "
                                                                                              f"{n12}", recs_l))
            and "which has no accepted answer" in escalation_line(recs[n12], recs)
            and recs[n13]["reask_of"] == "E3" and "main_thm" not in recs[n13]["decls"] and recs[n14]["reask_of"] is None)
    finally:
        project.REPO, _mr.REPO = keep
    return res


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

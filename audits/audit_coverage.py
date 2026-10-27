#!/usr/bin/env python3
"""Roll up the stored audit rounds and report what has never actually been examined.

WHY THIS EXISTS.  `AUDIT_PROTOCOL.md` gives each lane three verdicts -- Pass, Fail, NotDoneYet --
and the rule that an item omitted from `verdicts[]` counts as NotDoneYet.  That rule turns an
audit report from a list of complaints into a claim about coverage.  But the claim is only worth
something if somebody reads it back across rounds, and nobody re-reads a JSON file by hand.  So:

  - Which items has a given lane never returned `Pass` on?
  - Which items has a given lane never *seen*?
  - Which `Fail` verdicts are still outstanding (failed, and never passed since)?

Without this script, `NotDoneYet` is a politer way of saying nothing, and the protocol is a
document rather than a process.  This project's record on the difference is one-sided: every
countermeasure that held is one that ran on its own.

NEGATIVE CONTROL.  `--selftest` builds a synthetic set of rounds with a known answer and checks
the roll-up against it, then exits.  Run it after editing this file.  Two scripts here passed
vacuously for weeks because nobody had made them fail on purpose.

Usage:
  audit_coverage.py [audits_dir]        # default: ../audits relative to this script
  audit_coverage.py --lane correspondence
  audit_coverage.py --selftest
Exit 1 if any item carries an outstanding Fail; 0 otherwise (gaps are reported, not gated --
an unexamined item is a fact about the audit, not a defect in the library).
"""
import json, os, re, sys, glob, argparse
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402  (ROUND_RE lives there, once)
import lanecheck  # noqa: E402  (lane_entries: the one reader of a lane file's `verdicts`)
from collections import defaultdict

# The canonical lanes, in protocol order. This list is NOT the set that gets read -- lanes are
# DISCOVERED from the round directories, because a hardcoded list silently drops any lane it does
# not name.  It did exactly that: `prior-art` (lane 5, added for library work) was absent here, so
# the first real round's roll-up reported 36 outstanding fails where the files held 45, and the
# nine it dropped were invisible -- no warning, no error, a lower number that looked like progress.
# That is the same failure as a checker that does not read a file, in the checker written to catch
# checkers that do not read files.
_AUDITS_DIR = []
ROUND_DIR_RE = project.ROUND_RE


def _dirs(audits_dir):
    """The directories of a rounds dir, without abandoned rounds (stops.py set-aside): their
    verdicts were never adjudicated, so none of them counts as a pass, a fail or a decision."""
    return [d for d in glob.glob(os.path.join(audits_dir, "*")) if not project.is_abandoned(d)]
CANONICAL = ["substantiveness", "correspondence", "paper-faithfulness", "non-vacuity", "prior-art"]
VALID = {"Pass", "Fail", "NotDoneYet", "Ambiguous"}
SEVERITY = ["Pass", "NotDoneYet", "Ambiguous", "Fail"]   # later = worse


def _repo_of(audits_dir):
    """Walk up to the enclosing git repository, so round hashes can be resolved."""
    d = os.path.abspath(audits_dir)
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return None


def discover_lanes(audits_dir):
    """Lane names, found by CONTENT rather than filename.

    Globbing *.json and trusting the basename made TARGET.json a lane called "TARGET" with 639
    items, which then entered every cross-lane gap count -- most of the 1488 gaps one round
    reported were that one file. A lane report is identified by carrying a `verdicts` list;
    bookkeeping files do not.
    """
    found = set()
    for d in _dirs(audits_dir):
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, "*.json")):
            try:
                doc = json.load(open(f, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if lanecheck.lane_entries(doc) is not None:
                found.add(os.path.splitext(os.path.basename(f))[0].split("@")[0])
    ordered = [l for l in CANONICAL if l in found] + sorted(found - set(CANONICAL))
    return ordered, sorted(found - set(CANONICAL))



# --- ADOPTED.md, the other half of a round ---------------------------------------------------
# The lane JSONs say what was FOUND; ADOPTED.md says what was DECIDED, and nothing read it until
# now. A DEFER repeated in three consecutive rounds looked identical to one taken once, so
# "standing" was a convention held in prose, carried only by whoever happened to read the previous
# round. That is the NotDoneYet failure one level up: the item stays visible while quietly
# ceasing to be anyone's decision.
VERDICT_RE = re.compile(r"\*\*(ADOPT|REJECT|DEFER|QUESTION|UNCOVERED)\b", re.I)


def norm_item(item):
    """A key under which a lane's item and an ADOPTED.md row's item compare equal.

    Lanes and adjudicators write the same item differently: `Paper/Blowup.lean:119 sum_range_box`
    in a lane's JSON, `` `Blowup.lean:119 sum_range_box` `` in ADOPTED.md, `Ns.sum_range_box`
    from scope.py. Exact string matching made a report announce that 47 adjudicated findings had
    "no recorded decision". Paper results ("Theorem 2.6") are kept whole; anything else is reduced
    to its declaration name: the last whitespace-separated token, last dot-component."""
    t = re.sub(r"\s*\([^()]*\)\s*$", "", item.strip()).strip().strip("`").strip()
    if re.match(rf"^(?:{project.RESULT_KINDS_RE})\s", t, re.I):
        return re.sub(r"\s+", " ", t).lower()
    t = t.split()[-1].strip("`") if t.split() else t
    return t.rsplit(".", 1)[-1] if not t.endswith(".lean") else t


def strict_rows(rounds_dir):
    """Are the round's decision rows read strictly (lanecheck.decision_rows)? Yes when the run's pin
    (TOOLING_PIN.json) records ownership version 2 or later: the version (0.3.0) whose settle check
    refuses a row naming no lane or item of the round exactly (R3e). No pin, or a pin of version 1
    (0.2.0 and earlier records, written before strict rows), is read best-effort (read_adopted)."""
    import integrity
    return os.path.exists(os.path.join(rounds_dir, integrity.PIN)) and integrity.pinned_version(rounds_dir) >= 2


def read_adopted(path):
    """{"<lane> :: <item>": decision} from one round's ADOPTED.md. A current-format record (strict_rows)
    is read through THE reader, lanecheck.decision_rows (R3f): only the rows that name a lane and an item
    of the round exactly, by their decision cell (project.decision_of), the lane by its base. An older
    record keeps the best-effort reading below: the file is prose around a table."""
    out = {}
    if not os.path.exists(path):
        return out
    rd = os.path.dirname(os.path.abspath(path))
    if strict_rows(os.path.dirname(rd)):
        import lanecheck
        for r in lanecheck.valid_rows(rd):
            if r.decision.startswith("?") or r.decision == "REVOTE NEEDED":
                continue          # no decision recorded; a re-vote request is not a decision
            k = f"{r.base} :: {norm_item(r.item)}"
            # UNCOVERED is a coverage status: inside one file too, it never replaces a decision
            if r.decision != "UNCOVERED" or k not in out:
                out[k] = r.decision
        return out
    # Older records (no pin, or ownership 1): best effort.
    header = None
    for line in open(path, encoding="utf-8"):
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cells = project.split_row(line)
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = [c.lower().strip("* ") for c in cells]
            if "decision" in header and "item" in header:
                continue
        if len(cells) < 3:
            continue
        lane_cell, item = cells[0], cells[1]
        if not item or item.lower() in ("item", "---", ":--") or set(item) <= set("-: "):
            continue
        structured = "decision" in header and "item" in header and len(cells) >= len(header)
        if structured:
            # a table with a decision column: its cell, read by the one parser the carry and
            # settle checks use (ROUND3 M2); a re-vote request is not a decision
            lane_cell = cells[header.index("lane")] if "lane" in header else lane_cell
            item = cells[header.index("item")]
            dec = project.decision_of(cells[header.index("decision")])
            if dec in (None, "REVOTE NEEDED"):
                continue
        # Older records: the first bold ADOPT/REJECT/DEFER in the row, else the first such word
        # in upper case in a later cell (they did not bold it, nor always have a decision column).
        v = None if structured else VERDICT_RE.search(line)
        dec = dec if structured else (v.group(1).upper() if v else None)
        if dec is None:
            for c in cells[2:]:
                m = re.search(r"\b(ADOPT|REJECT|DEFER|QUESTION|UNCOVERED)\b", c)
                if m:
                    dec = m.group(1); break
        if dec is None:
            continue
        # one row may cover several lanes: "substantiveness + prior-art"
        for lane in re.split(r"\s*[+,/&]\s*", lane_cell.strip("`* ")):
            # a lane instance is named `<lane>@<n>` in rounds with several lanes per criterion
            lane = re.sub(r"@\d+$", "", lane)
            if lane:
                k = f"{lane} :: {norm_item(item)}"
                # UNCOVERED is a coverage status: inside one file too, it never replaces a decision
                if dec != "UNCOVERED" or k not in out:
                    out[k] = dec
    return out


NOTE_KEY_RE = re.compile(r"`([A-Za-z_][\w'.]*)`|\b([A-Z]\w*(?:\.[A-Za-z_]\w*)+)\b")
NOTE_FILE_RE = re.compile(r"\b([\w/]+\.lean):(\d+)")
NOTE_BARE_RE = re.compile(r"(?<![\w.`])([a-z]\w*(?:_\w+|\d\w*|'))(?![\w.`])")


def repeated_notes(audits_dir):
    """[(key, [rounds])] for a declaration named in lanes' `out_of_lane` notes in 2+ rounds that no
    ADOPTED.md row ever decided. Out-of-lane notes are read by nobody's criterion: in a
    test run one stale docstring was noted five times and never became a row (F-I13)."""
    rounds = project.order_rounds([d for d in _dirs(audits_dir)
                           if os.path.isdir(d) and project.ROUND_RE.match(os.path.basename(d))], _repo_of(audits_dir))
    seen, decided, examined = defaultdict(list), set(), set()
    # names some lane examined as an item: a bare word in a note counts only if it is one of these
    for d in rounds:
        for f in glob.glob(os.path.join(d, "*.json")):
            try:
                for v in lanecheck.lane_entries(json.load(open(f, encoding="utf-8"))) or []:
                    if v.get("item"):
                        examined.add(norm_item(str(v["item"])).lower())
            except (ValueError, AttributeError):
                continue
    for d in rounds:
        decided |= {k.split(" :: ", 1)[1].lower() for k in read_adopted(os.path.join(d, "ADOPTED.md"))}
        keys = set()
        for f in glob.glob(os.path.join(d, "*.json")):
            try:
                notes = json.load(open(f, encoding="utf-8")).get("out_of_lane") or []
            except (ValueError, AttributeError):
                continue
            for n in notes if isinstance(notes, list) else [notes]:
                n = str(n)
                for a, b in NOTE_KEY_RE.findall(n):
                    key = (a or b).rstrip(".")
                    if "." in key and not key.endswith((".lean", ".md", ".json", ".py", ".txt")):
                        keys.add(key)
                # a place: File.lean:N, bucketed by 20 lines (lines drift between rounds)
                for fl, ln in NOTE_FILE_RE.findall(n):
                    keys.add(f"{os.path.basename(fl)}:~{int(ln) // 20 * 20}")
                # a bare declaration name, if some lane examined it as an item
                for b in NOTE_BARE_RE.findall(n):
                    if b.lower() in examined:
                        keys.add(b)
        for k in keys:
            seen[k].append(os.path.basename(d))
    # a place (File.lean:~N) is listed from 3 rounds, a name from 2: places are noisier
    return sorted(((k, rs) for k, rs in seen.items()
                   if len(rs) >= (3 if ":~" in k else 2) and norm_item(k).lower() not in decided and k.lower() not in decided),
                  key=lambda t: (-len(t[1]), t[0]))


def decision_streaks(audits_dir):
    """[(item, verdict, [rounds])] for anything decided the same way in 2+ rounds."""
    from collections import defaultdict
    rounds = project.order_rounds([d for d in _dirs(audits_dir)
                           if os.path.isdir(d)], _repo_of(audits_dir))
    runs = defaultdict(list)
    for d in rounds:
        for item, v in read_adopted(os.path.join(d, "ADOPTED.md")).items():
            if v in ("ADOPT", "REJECT", "DEFER"):     # QUESTION/UNCOVERED are not repeated decisions
                runs[(item, v)].append(os.path.basename(d))
    return sorted(((i, v, r) for (i, v), r in runs.items() if len(r) >= 2),
                  key=lambda t: (-len(t[2]), t[0]))



# --- what was SENT, versus what came back ----------------------------------------------------
# The omission rule ("an item absent from verdicts[] counts as NotDoneYet") compares a lane's
# verdicts against the lane's OWN declared scope. That is circular: a lane that quietly drops ten
# items from its scope also drops them from verdicts, reports unlisted = 0, and looks complete.
# Across three real rounds every lane reported unlisted = 0, and one of them had silently ADDED
# five items -- caught by a human reading the diff in prose, by nothing mechanical.
#
# So step 3 writes the target it sent to TARGET.json, and this compares the two. A lane that
# narrows its own assignment is then as visible as one that skips an item, which is the thing the
# rule was for.

def parked_items(audits_dir):
    """Substrings from the project's standing_defers, used to mark a NotDoneYet as parked.

    Without this the roll-up lists an item every round after it has been deliberately parked, so
    the number never falls and stops meaning anything -- the boy-who-cried-wolf failure that
    makes a report get skimmed. A parked item is still shown, in its own bucket, because parked
    is not the same as examined.
    """
    for cand in (os.path.join(audits_dir, "..", "projects"),
                 os.path.join(audits_dir, "projects")):
        for f in glob.glob(os.path.join(cand, "*.json")):
            try:
                cfg = json.load(open(f, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if cfg.get("rounds_dir") and os.path.basename(audits_dir) in cfg["rounds_dir"]:
                out = []
                for sd in cfg.get("standing_defers", []):
                    out.append((sd.get("id", "?"), sd.get("item", "")))
                return out
    return []


def read_target(round_dir):
    """{lane: [items sent]} from TARGET.json, or {} when step 3 did not record it."""
    p = os.path.join(round_dir, "TARGET.json")
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"MALFORMED {p}: {e}", file=sys.stderr)
        return {}
    return {k: list(v) for k, v in d.items() if isinstance(v, (list, tuple))}


def lane_doc(d, lane):
    """One lane's verdict document in round directory `d`, or None.

    A lane with a large scope is split across several subagents (`prompt.py --batch`), each writing
    `<lane>@<k>.json`. They are one lane: scopes and verdicts are merged here, so every reader of a
    round sees the same thing whether or not it was batched."""
    files = sorted(glob.glob(os.path.join(d, glob.escape(lane) + ".json"))
                   + glob.glob(os.path.join(d, glob.escape(lane) + "@*.json")))
    if not files:
        return None
    merged = {"lane": lane, "scope": [], "verdicts": []}
    for f in files:
        doc = json.load(open(f, encoding="utf-8"))   # malformed JSON propagates to the caller
        merged["scope"] += doc.get("scope") or doc.get("request_summary", {}).get("items") or []
        merged["verdicts"] += lanecheck.lane_entries(doc) or []
    return merged


def scope_drift(audits_dir, lanes):
    """[(round, lane, dropped, added)] where sent and returned scopes disagree.

    Returns a third element `unrecorded` listing rounds with no TARGET.json, because a round that
    cannot be checked must not read the same as a round that passed.
    """
    out, unrecorded = [], []
    for d in project.order_rounds([x for x in _dirs(audits_dir)
                           if os.path.isdir(x)], _repo_of(audits_dir)):
        sent = read_target(d)
        if not sent:
            if any(glob.glob(os.path.join(d, glob.escape(l) + "*.json")) for l in lanes):
                unrecorded.append(os.path.basename(d))
            continue
        for lane in sorted(set(lanes) | set(sent)):
            if lane not in sent:
                continue
            try:
                doc = lane_doc(d, lane)
            except (OSError, json.JSONDecodeError):
                continue
            if doc is None:
                # a lane that was sent a scope and wrote nothing examined nothing
                out.append((os.path.basename(d), lane, sorted(sent[lane]), [], []))
                continue
            got = set(doc.get("scope", []))
            # Compare on a normalised key. A lane that annotates an item --
            # "cycle_interp" -> "cycle_interp (proof only; modified in <hash>)" -- has not
            # changed its scope, and reporting that as six drops and six adds buries a real
            # drift in noise. Renames are counted separately and do not gate.
            def _norm(x):
                # case is significant in Lean names (N.Foo and N.foo are different declarations)
                return re.sub(r"\s*\(.*$", "", str(x)).strip().rsplit(":", 1)[-1].strip()
            smap, gmap = {_norm(x): x for x in sent[lane]}, {_norm(x): x for x in got}
            dropped = sorted(smap[k] for k in smap.keys() - gmap.keys())
            added = sorted(gmap[k] for k in gmap.keys() - smap.keys())
            renamed = sorted((smap[k], gmap[k]) for k in smap.keys() & gmap.keys()
                             if smap[k] != gmap[k])
            if dropped or added or renamed:
                out.append((os.path.basename(d), lane, dropped, added, renamed))
    return out, unrecorded


def load_rounds(audits_dir, lanes):
    """Return [(round_name, lane, {item: verdict}, [declared_scope])], oldest first.

    A round directory is any subdirectory holding at least one <lane>.json.  Rounds sort by
    directory name, which the protocol fixes as <YYYY-MM-DD>-<commit>, so lexicographic order is
    chronological.
    """
    rounds = []
    for d in project.order_rounds([x for x in _dirs(audits_dir)
                           if os.path.isdir(x)], _repo_of(audits_dir)):
        if not os.path.isdir(d):
            continue
        rnd = os.path.basename(d)
        for lane in lanes:
            try:
                doc = lane_doc(d, lane)
            except (OSError, json.JSONDecodeError) as e:
                print(f"MALFORMED {rnd}/{lane}.json: {e}", file=sys.stderr)
                continue
            if doc is None:
                continue
            verdicts = {}
            # Rounds cut by scope.py carry FINGERPRINTS.json; they were run under the schema in
            # which a Pass must say what was `checked`. Older rounds predate that rule and are not
            # re-judged by it after the fact.
            proof_of_work = os.path.exists(os.path.join(d, "FINGERPRINTS.json"))
            for v in lanecheck.lane_entries(doc) or []:
                item, verd = v.get("item"), v.get("verdict")
                if not item:
                    continue
                if verd not in VALID:
                    print(f"BAD VERDICT {rnd}/{lane}: {item!r} -> {verd!r}", file=sys.stderr)
                    verd = "NotDoneYet"
                if verd == "Pass" and proof_of_work and not str(v.get("checked", "")).strip():
                    print(f"BARE PASS {rnd}/{lane}: {item!r} has no `checked`; counted as "
                          f"NotDoneYet", file=sys.stderr)
                    verd = "NotDoneYet"
                if item in verdicts and verdicts[item] != verd:
                    # two verdicts on one item (a repeated entry, or two batches that disagree):
                    # the WORSE one stands, never the later one
                    worse = max(verdicts[item], verd, key=SEVERITY.index)
                    print(f"CONFLICT {rnd}/{lane}: {item!r} has {verdicts[item]} and {verd}; "
                          f"counted as {worse}", file=sys.stderr)
                    verd = worse
                verdicts[item] = verd
            # The protocol's rule: anything in scope but absent from verdicts[] is NotDoneYet.
            # A lane may declare its scope explicitly; if it does, honour it.
            scope = doc.get("scope") or doc.get("request_summary", {}).get("items") or []
            for item in scope:
                verdicts.setdefault(item, "NotDoneYet")
            rounds.append((rnd, lane, verdicts))
    return rounds


def stale_passes(audits_dir, state):
    """[(lane, item, pass_round, why)] -- Passes whose subject has changed meaning since.

    A Pass is a verdict on what a declaration MEANT at that round's commit. Each round directory
    carries FINGERPRINTS.json (written by scope.py through fingerprint.py): a content hash of every
    declaration's statement, or of its value for a definition, closed under the project-local
    definitions it is stated in terms of. If the newest snapshot disagrees with the snapshot of
    the round that passed an item, the Pass is about something that no longer exists, and the item
    is back in the backlog. Before this, a Pass was keyed by NAME and survived any change to a
    definition underneath it.

    Items that are not declaration names (paper results like "Theorem 1.1") have no fingerprint
    and are not judged here; rounds with no FINGERPRINTS.json cannot be judged either, and are
    reported as such rather than counted as fresh.
    """
    snaps = {}
    for d in _dirs(audits_dir):
        f = os.path.join(d, "FINGERPRINTS.json")
        if os.path.isdir(d) and os.path.exists(f):
            try:
                snaps[os.path.basename(d)] = json.load(open(f, encoding="utf-8"))["fingerprints"]
            except (OSError, ValueError, KeyError) as e:
                print(f"MALFORMED {os.path.basename(d)}/FINGERPRINTS.json: {e}", file=sys.stderr)
    if not snaps:
        return [], None
    ordered = project.order_rounds([os.path.join(audits_dir, r) for r in snaps], _repo_of(audits_dir))
    newest = os.path.basename(ordered[-1])
    current = snaps[newest]
    out = []
    for (lane, item), st in sorted(state.items()):
        passes = [r for r, v in st["history"] if v == "Pass"]
        if not passes or st["last"] != "Pass":
            continue
        r = passes[-1]
        if r not in snaps:
            out.append((lane, item, r, "passed in a round with no fingerprint snapshot"))
        elif item in snaps[r]:
            if item not in current:
                out.append((lane, item, r, "no longer exists (renamed or deleted)"))
            elif current[item] != snaps[r][item]:
                out.append((lane, item, r, "its meaning changed since it passed"))
    return out, newest


def roll_up(rounds):
    """{(lane, item): {"last": verdict, "history": [(round, verdict)]}}"""
    state = defaultdict(lambda: {"last": None, "history": []})
    for rnd, lane, verdicts in rounds:
        for item, verd in verdicts.items():
            s = state[(lane, item)]
            s["history"].append((rnd, verd))
            s["last"] = verd
    return state


def report(state, lanes, only_lane=None, rounds_meta=()):
    outstanding, never_passed, never_seen_by, ambiguous = [], [], defaultdict(list), []
    items = {item for (_, item) in state}
    lanes = [only_lane] if only_lane else lanes

    for (lane, item), s in sorted(state.items()):
        if only_lane and lane != only_lane:
            continue
        verds = [v for _, v in s["history"]]
        last_fail = max((k for k, v in enumerate(verds) if v == "Fail"), default=-1)
        last_pass = max((k for k, v in enumerate(verds) if v == "Pass"), default=-1)
        if last_fail > last_pass:
            # "failed, and never passed since" -- a later round that omitted the item (NotDoneYet)
            # does not clear it; it used to, and the Fail vanished from the report
            outstanding.append((lane, item, s["history"][last_fail][0]))
        elif s["last"] == "Ambiguous":
            ambiguous.append((lane, item, s["history"][-1][0]))
        elif "Pass" not in verds:
            never_passed.append((lane, item, verds[-1]))

    # Lanes key items differently: paper-faithfulness by paper result ("Theorem 2.7"), the others
    # by declaration. Comparing across the two kinds reported every item as "never examined" by
    # the other kind (36 spurious gaps on a 12-result project), which hid the real ones.
    RESULT_LANES = {"paper-faithfulness", "literature-match"}
    for lane in lanes:
        kind = lane in RESULT_LANES
        same_kind = {i for (l, i) in state if (l in RESULT_LANES) == kind}
        for item in sorted(same_kind):
            if (lane, item) not in state:
                never_seen_by[lane].append(item)

    print("=" * 72)
    print(f"OUTSTANDING FAILS ({len(outstanding)}) — failed, and no Pass since the last Fail")
    for lane, item, rnd in outstanding:
        print(f"  [{lane}] {item}   (last seen {rnd})")
    if not outstanding:
        print("  none")

    print()
    print(f"AMBIGUOUS ({len(ambiguous)}) — a reading choice; each is a question for the human")
    for lane, item, rnd in ambiguous:
        print(f"  [{lane}] {item}   (last seen {rnd})")
    if not ambiguous:
        print("  none")

    print()
    print(f"NEVER PASSED ({len(never_passed)}) — seen, but no lane round ever returned Pass")
    for lane, item, last in never_passed:
        print(f"  [{lane}] {item}   (last verdict: {last})")
    if not never_passed:
        print("  none")

    print()
    print("NEVER EXAMINED — item is known to some lane, but this lane has never seen it")
    total_gaps = 0
    for lane in lanes:
        gaps = never_seen_by[lane]
        total_gaps += len(gaps)
        print(f"  {lane}: {len(gaps)}")
        for item in gaps[:20]:
            print(f"      {item}")
        if len(gaps) > 20:
            print(f"      … and {len(gaps) - 20} more")

    stale, newest = stale_passes(_AUDITS_DIR[0], state) if _AUDITS_DIR else ([], None)
    print()
    if newest is None:
        print("STALE PASSES — NOT CHECKABLE: no round has a FINGERPRINTS.json, so a Pass on a")
        print("  declaration whose definitions later changed cannot be told from a fresh one.")
    else:
        print(f"STALE PASSES ({len(stale)}) — passed earlier, but changed since (vs. {newest})")
        for lane, item, r, why in stale:
            print(f"  [{lane}] {item}   (passed in {r}: {why})")
        if not stale:
            print("  none")

    drift, unrecorded = scope_drift(_AUDITS_DIR[0], lanes) if _AUDITS_DIR else ([], [])
    print()
    print(f"SCOPE DRIFT ({len(drift)}) — lane's declared scope vs the target step 3 sent")
    for rnd, lane, dropped, added, renamed in drift:
        print(f"  {rnd} {lane}: -{len(dropped)} dropped, +{len(added)} added, {len(renamed)} renamed")
        for i in dropped[:5]:
            print(f"      DROPPED (counts as NotDoneYet) {i[:64]}")
        for i in added[:5]:
            print(f"      ADDED   (lane redefined its job) {i[:64]}")
        for a_, b_ in renamed[:3]:
            print(f"      renamed (cosmetic, not gated) {a_[:38]} -> {b_[:38]}")
    real = [x for x in drift if x[2] or x[3]]
    if not real and not unrecorded:
        print("  none")
    if unrecorded:
        print(f"  NOT CHECKABLE: {len(unrecorded)} round(s) have no TARGET.json, so their scope")
        print(f"  cannot be compared at all: {', '.join(unrecorded)}")
        print("  A round that cannot be checked is not a round that passed.")

    # NotDoneYet items nobody has looked at since. The verdict records that an item was not
    # examined; nothing routed it anywhere afterwards, so with diff-scoped rounds an item goes
    # NotDoneYet once and then falls out of scope forever. On one project 101 of 102 NotDoneYet
    # items were reported exactly once and never revisited -- which reads, from any single
    # round, exactly like being resolved.
    _ORDER = []
    for r, _, _ in rounds_meta:
        if r not in _ORDER:
            _ORDER.append(r)
    orphans = []
    for (lane, item), st in sorted(state.items()):
        verds = [v for _, v in st["history"]]
        if "NotDoneYet" in verds and st["last"] == "NotDoneYet":
            last_round = st["history"][-1][0]
            # Position in the ORDERED round list. Two earlier attempts got this wrong the same
            # way: one counted lane-rounds instead of rounds ("10 rounds ago" in a project with
            # four), the next compared round NAMES as strings -- which sorts by hash, the exact
            # bug already fixed twice elsewhere in this file. Round names are not ordered data;
            # only the ordered list is.
            later = (len(_ORDER) - 1 - _ORDER.index(last_round)) if last_round in _ORDER else 0
            orphans.append((lane, item, last_round, later))
    stale = [o for o in orphans if o[3] >= 1]
    # split parked from unaddressed: an item covered by a standing defer has been decided, and
    # listing it beside genuinely forgotten items makes both easier to ignore.
    parked_defs = parked_items(_AUDITS_DIR[0]) if _AUDITS_DIR else []
    def _parked(item):
        low = str(item).lower()
        for pid, text in parked_defs:
            toks = [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{4,}", text) if "_" in t or "." in t]
            if any(t.lower() in low for t in toks):
                return pid
        return None
    parked = [(l, i, r, n, _parked(i)) for l, i, r, n in orphans if _parked(i)]
    orphans = [o for o in orphans if not _parked(o[1])]
    stale = [o for o in orphans if o[3] >= 1]
    if parked:
        print()
        print(f"NotDoneYet, PARKED ({len(parked)}) — covered by a standing defer, decided not forgotten")
        seen_ids = defaultdict(int)
        for _, _, _, _, pid in parked:
            seen_ids[pid] += 1
        for pid, n in sorted(seen_ids.items()):
            print(f"  {pid}: {n} item(s)")
    if orphans:
        print()
        print(f"NotDoneYet, STILL ({len(orphans)}) — never examined since and not parked; "
              f"{len(stale)} have had a later round pass them by")
        by_lane = defaultdict(int)
        for lane, _, _, later in orphans:
            by_lane[lane] += 1
        for lane, n in sorted(by_lane.items(), key=lambda x: -x[1]):
            print(f"  {lane}: {n}")
        for lane, item, lr, later in stale[:6]:
            print(f"    last seen {lr}, {later} round(s) ago: [{lane}] {item[:52]}")
        if len(stale) > 6:
            print(f"    … and {len(stale) - 6} more")
        print("  Each belongs in exactly one of two places, and step 4 decides which: the scope")
        print("  of a future round, or the project's standing_defers with a revisit condition.")
        print("  Left here, it is an item that was honestly not examined and then forgotten.")

    # A lane that has never once said "I did not examine this" across hundreds of items is
    # either genuinely exhaustive or is treating NotDoneYet as an admission of failure, and the
    # difference matters: the verdict only protects coverage if lanes will actually use it.
    # Reported, not enforced -- a lane pressured into NotDoneYet would be worse than one that
    # never says it.
    per_lane = defaultdict(lambda: {"items": 0, "ndy": 0, "rounds": set()})
    for (lane, _item), st in state.items():
        for rnd, v in st["history"]:
            per_lane[lane]["rounds"].add(rnd)
            per_lane[lane]["items"] += 1
            if v == "NotDoneYet":
                per_lane[lane]["ndy"] += 1
    silent = [(l, d) for l, d in sorted(per_lane.items())
              if d["ndy"] == 0 and d["items"] >= 50 and len(d["rounds"]) >= 2]
    if silent:
        print()
        print(f"NEVER SAYS NotDoneYet ({len(silent)} lane(s)) — observation, not a failure")
        for l, d in silent:
            print(f"  {l}: {d['items']} items over {len(d['rounds'])} rounds, 0 NotDoneYet")
        print("  Either exhaustive, or treating the verdict as an admission. Worth one spot check")
        print("  of a Pass you did not expect: the coverage claim rests on lanes using it.")

    streaks = decision_streaks(_AUDITS_DIR[0]) if _AUDITS_DIR else []
    if streaks:
        print()
        print(f"REPEATED DECISIONS ({len(streaks)}) — same verdict in 2 or more rounds")
        for item, v, rs in streaks:
            flag = "   <-- standing: does it have a revisit condition?" if v == "DEFER" else ""
            print(f"  {v:<7} x{len(rs)}  {item[:64]}{flag}")
        print("  A DEFER repeated with no stated revisit condition is an abandonment nobody")
        print("  decided on. Record it under the project's `standing_defers`, with the condition.")

    notes = repeated_notes(_AUDITS_DIR[0]) if _AUDITS_DIR else []
    if notes:
        print()
        print(f"REPEATED OUT-OF-LANE NOTES ({len(notes)}) — named in lanes' notes in 2+ rounds, never decided")
        for k, rs in notes[:40]:
            print(f"  x{len(rs)}  {k[:64]}")
        if len(notes) > 40:
            print(f"  ... and {len(notes) - 40} more")
        print("  Each needs a row this round (ADOPT / REJECT / DEFER with a condition): a note no")
        print("  lane owns is otherwise repeated forever and decided never.")

    print()
    print(f"summary: {len(outstanding)} outstanding fail(s), {len(never_passed)} never passed, "
          f"{total_gaps} lane/item gap(s), {len(streaks)} repeated decision(s), "
          f"{len(real)} scope drift(s), {len(unrecorded)} unrecorded round(s), "
          f"{len(orphans)} NotDoneYet still unexamined")
    # Exit 1 when the record shows unresolved trouble: a Fail never passed since, or a lane that
    # did not examine what it was sent. Everything else is reported, not gated.
    return 1 if outstanding or real else 0


def selftest():
    """Synthetic rounds with a known answer."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        def write(rnd, lane, verdicts, scope=None):
            d = os.path.join(tmp, rnd)
            os.makedirs(d, exist_ok=True)
            doc = {"lane": lane, "decision": "PASS",
                   "verdicts": [{"item": i, "verdict": v} for i, v in verdicts],
                   "summary": ""}
            if scope:
                doc["scope"] = scope
            json.dump(doc, open(os.path.join(d, lane + ".json"), "w"))

        # round 1: A passes, B fails, C omitted although in scope -> NotDoneYet
        write("2026-01-01-aaaaaaa", "correspondence",
              [("A", "Pass"), ("B", "Fail")], scope=["A", "B", "C"])
        # round 2: B fixed, C still not examined, D newly passes
        write("2026-01-02-bbbbbbb", "correspondence",
              [("B", "Pass"), ("C", "NotDoneYet"), ("D", "Pass")])
        # substantiveness has only ever looked at A
        write("2026-01-02-bbbbbbb", "substantiveness", [("A", "Pass")])
        # a lane that is NOT in CANONICAL must still be counted: hardcoding the lane list once
        # dropped nine real Fail verdicts without a word, and this is the control for that.
        write("2026-01-02-bbbbbbb", "prior-art", [("E", "Fail")])
        write("2026-01-02-bbbbbbb", "invented-lane", [("F", "Fail")])

        # an abandoned round (stops.py set-aside): never adjudicated, so its Pass of C
        # must not retire C
        write("2026-01-02-full-bbbbbbb", "correspondence", [("C", "Pass")])
        open(os.path.join(tmp, "2026-01-02-full-bbbbbbb", project.ABANDONED), "w").write("{}")
        lanes, _ = discover_lanes(tmp)
        rounds = load_rounds(tmp, lanes)
        state = roll_up(rounds)

        checks = []
        checks.append(("C never passed (an abandoned round's Pass does not count)",
                       "Pass" not in [v for _, v in state[("correspondence", "C")]["history"]]))
        checks.append(("C was recorded despite omission in round 1",
                       state[("correspondence", "C")]["history"][0][1] == "NotDoneYet"))
        checks.append(("B no longer outstanding",
                       state[("correspondence", "B")]["last"] == "Pass"))
        checks.append(("substantiveness never saw B",
                       ("substantiveness", "B") not in state))
        checks.append(("D passed", state[("correspondence", "D")]["last"] == "Pass"))
        checks.append(("non-canonical lane 'prior-art' counted",
                       state.get(("prior-art", "E"), {}).get("last") == "Fail"))
        checks.append(("unknown lane 'invented-lane' counted, not dropped",
                       state.get(("invented-lane", "F"), {}).get("last") == "Fail"))
        # scope drift: the control for the circularity. A lane that narrows its own
        # assignment reports unlisted = 0 and must still be caught.
        import json as _j
        _d = os.path.join(tmp, "2026-01-03-ccccccc")
        os.makedirs(_d, exist_ok=True)
        _j.dump({"correspondence": ["A", "B", "C"]}, open(os.path.join(_d, "TARGET.json"), "w"))
        _j.dump({"lane": "correspondence", "scope": ["A", "Z"],
                 "verdicts": [{"item": "A", "verdict": "Pass"}, {"item": "Z", "verdict": "Pass"}],
                 "summary": ""}, open(os.path.join(_d, "correspondence.json"), "w"))
        _drift, _unrec = scope_drift(tmp, ["correspondence"])
        _hit = [x for x in _drift if x[0] == "2026-01-03-ccccccc"]
        checks.append(("a lane that drops scope items is caught",
                       bool(_hit) and _hit[0][2] == ["B", "C"]))
        checks.append(("a lane that adds scope items is caught",
                       bool(_hit) and _hit[0][3] == ["Z"]))
        checks.append(("rounds with no TARGET.json are reported as not checkable",
                       "2026-01-01-aaaaaaa" in _unrec))
        # Bare passes: under the new schema (round has FINGERPRINTS.json) a Pass with no
        # `checked` is NotDoneYet; in an older round it is left alone.
        _t4 = tempfile.mkdtemp()
        try:
            for _rn, _fp in (("2026-04-01-3333333", True), ("2026-04-02-4444444", False)):
                _d4 = os.path.join(_t4, _rn); os.makedirs(_d4)
                if _fp:
                    _j.dump({"fingerprints": {}}, open(os.path.join(_d4, "FINGERPRINTS.json"), "w"))
                _j.dump({"lane": "correspondence", "verdicts": [
                    {"item": f"bare{_rn[-1]}", "verdict": "Pass"},
                    {"item": f"worked{_rn[-1]}", "verdict": "Pass", "checked": "x.lean:3"},
                    {"item": f"amb{_rn[-1]}", "verdict": "Ambiguous", "question": "q"}]},
                    open(os.path.join(_d4, "correspondence.json"), "w"))
            import io as _io, contextlib as _cl
            with _cl.redirect_stderr(_io.StringIO()):
                _st4 = roll_up(load_rounds(_t4, ["correspondence"]))
            checks.append(("bare Pass in a new-schema round is NotDoneYet",
                           _st4[("correspondence", "bare3")]["last"] == "NotDoneYet"))
            checks.append(("Pass with `checked` stays Pass",
                           _st4[("correspondence", "worked3")]["last"] == "Pass"))
            checks.append(("bare Pass in an old round is not re-judged",
                           _st4[("correspondence", "bare4")]["last"] == "Pass"))
            checks.append(("Ambiguous is a valid verdict, not coerced",
                           _st4[("correspondence", "amb3")]["last"] == "Ambiguous"))
        finally:
            shutil.rmtree(_t4, ignore_errors=True)
        checks.append(("norm_item: lane path form == ADOPTED backtick form == qualified form",
                       norm_item("Paper/Blowup.lean:119 sum_range_box")
                       == norm_item("`Blowup.lean:119 sum_range_box`")
                       == norm_item("Paper.sum_range_box") == "sum_range_box"))
        checks.append(("norm_item: trailing parenthetical note ignored",
                       norm_item("Arxiv/X.lean:49 ceil_le (proof changed; import dropped)") == "ceil_le"))
        _ta = tempfile.mkdtemp()
        try:
            _ap = os.path.join(_ta, "ADOPTED.md")
            open(_ap, "w").write("| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                                 "| substantiveness + prior-art | `F.lean:30 avg_nonneg` | Fail x2 | DEFER | follows |\n"
                                 "| correspondence | `G.lean:1 foo` | Fail | **ADOPT** | ok, will not REJECT |\n"
                                 "| paper-faithfulness | Theorem 2.6 | Fail | not decided yet | adopt later |\n"
                                 "| substantiveness@3 | Ns.l410b | Fail (REJECT proposed) | **QUESTION** | nonExt idle |\n"
                                 "| correspondence | Ns.PL | STALE PASS | **UNCOVERED** | renamed |\n"
                                 "| substantiveness | Ns.bar\\|baz | Fail | **REJECT** | quoted |\n"
                                 "| non-vacuity | Ns.unb | Fail | QUESTION | older record, not bold |\n"
                                 "\nAn older table, without a decision column:\n\n| lane | item | found | outcome |\n|---|---|---|---|\n"
                                 "| non-vacuity | Ns.legb | Fail (REJECT proposed) | **QUESTION** to the human |\n"
                                 "| non-vacuity | Ns.legu | Fail | asked: QUESTION |\n")
            _ad = read_adopted(_ap)
            checks.append(("read_adopted: multi-lane row registers each lane, unbolded DEFER read",
                           _ad.get("substantiveness :: avg_nonneg") == "DEFER"
                           and _ad.get("prior-art :: avg_nonneg") == "DEFER"))
            checks.append(("read_adopted: bold decision wins over a word in the reason",
                           _ad.get("correspondence :: foo") == "ADOPT"))
            checks.append(("read_adopted: a lane instance `lane@3` counts for its lane; QUESTION and UNCOVERED are decisions",
                           _ad.get("substantiveness :: l410b") == "QUESTION"
                           and _ad.get("correspondence :: PL") == "UNCOVERED"))
            checks.append(("read_adopted: an unbolded QUESTION is read", _ad.get("non-vacuity :: unb") == "QUESTION"))
            checks.append(("read_adopted: in a table without a decision column, a bold and an unbolded QUESTION are read",
                           _ad.get("non-vacuity :: legb") == "QUESTION" and _ad.get("non-vacuity :: legu") == "QUESTION"))
            open(_ap, "a").write("| correspondence | Ns.S4.hd_le_Wc | Fail | **ADOPT** | fix |\n"
                                 "| correspondence | Ns.S4.Setting.hd_le_Wc | STALE | **UNCOVERED** | gone |\n")
            checks.append(("read_adopted: a later UNCOVERED row in the same file does not replace a decision",
                           read_adopted(_ap).get("correspondence :: hd_le_Wc") == "ADOPT"))
            checks.append(("read_adopted: an escaped bar in the reason does not shift the cells",
                           _ad.get("substantiveness :: " + norm_item("Ns.bar|baz")) == "REJECT"))
            checks.append(("read_adopted: lower-case 'adopt' in prose is not a decision",
                           "paper-faithfulness :: theorem 2.6" not in _ad))
        finally:
            shutil.rmtree(_ta, ignore_errors=True)
        checks.append(("norm_item: paper results kept whole",
                       norm_item("Theorem 2.6") == "theorem 2.6" != norm_item("Theorem 2.7")))
        # Batched lanes: <lane>@1.json + <lane>@2.json are ONE lane.
        _t5 = tempfile.mkdtemp()
        try:
            _d5 = os.path.join(_t5, "2026-05-01-5555555"); os.makedirs(_d5)
            _j.dump({"correspondence": ["P", "Q", "R"]}, open(os.path.join(_d5, "TARGET.json"), "w"))
            _j.dump({"lane": "correspondence", "scope": ["P", "Q"], "verdicts": [
                {"item": "P", "verdict": "Pass", "checked": "x"}, {"item": "Q", "verdict": "Fail"}]},
                open(os.path.join(_d5, "correspondence@1.json"), "w"))
            _j.dump({"lane": "correspondence", "scope": ["R"], "verdicts": []},
                    open(os.path.join(_d5, "correspondence@2.json"), "w"))
            _l5, _ = discover_lanes(_t5)
            checks.append(("batched: parts discovered as one lane", _l5 == ["correspondence"]))
            _s5 = roll_up(load_rounds(_t5, _l5))
            checks.append(("batched: verdicts merged; omitted item in part 2 is NotDoneYet",
                           _s5[("correspondence", "Q")]["last"] == "Fail"
                           and _s5[("correspondence", "R")]["last"] == "NotDoneYet"))
            _dr5, _ = scope_drift(_t5, _l5)
            checks.append(("batched: merged scope matches TARGET (no false drift)", _dr5 == []))
            os.remove(os.path.join(_d5, "correspondence@2.json"))
            _dr5, _ = scope_drift(_t5, _l5)
            checks.append(("batched: a missing part shows as dropped scope",
                           bool(_dr5) and _dr5[0][2] == ["R"]))
        finally:
            shutil.rmtree(_t5, ignore_errors=True)
        # --- report() semantics and exit code, on a fresh fixture ----------------------------
        import io as _io2, contextlib as _cl2
        _t6 = tempfile.mkdtemp()
        try:
            def _w(rnd, lane, vs, t, scope=None, target=None):
                dd = os.path.join(_t6, rnd); os.makedirs(dd, exist_ok=True)
                doc = {"lane": lane, "verdicts": [dict(item=i, verdict=v, checked="x") for i, v in vs]}
                if scope is not None:
                    doc["scope"] = scope
                _j.dump(doc, open(os.path.join(dd, lane + ".json"), "w"))
                if target is not None:
                    _j.dump(target, open(os.path.join(dd, "TARGET.json"), "w"))
                os.utime(dd, (t, t))
            # Adversarial names: by NAME round b is first; by time (the fallback for hashes git
            # cannot resolve) it is second. Ordering must follow time.
            _w("2026-06-02-aaaaaaa", "correspondence", [("F", "Fail"), ("G", "Pass")], 1_000_000)
            _w("2026-06-01-bbbbbbb", "correspondence", [("F", "NotDoneYet"), ("G", "Fail")], 2_000_000)
            _AUDITS_DIR.clear(); _AUDITS_DIR.append(_t6)
            _st6 = roll_up(load_rounds(_t6, ["correspondence"]))
            checks.append(("ordering by time, not name: G's last verdict is the later round's Fail",
                           _st6[("correspondence", "G")]["last"] == "Fail"))
            with _cl2.redirect_stdout(_io2.StringIO()) as _o6:
                _rc6 = report(_st6, ["correspondence"])
            checks.append(("a Fail followed only by NotDoneYet is still OUTSTANDING",
                           "[correspondence] F" in _o6.getvalue().split("NEVER PASSED")[0]))
            checks.append(("outstanding fails -> exit 1", _rc6 == 1))
            shutil.rmtree(_t6); os.makedirs(_t6)
            _w("2026-06-01-ccccccc", "correspondence", [("A", "Pass")], 1_000_000, scope=["A"],
               target={"correspondence": ["A"]})
            _st7 = roll_up(load_rounds(_t6, ["correspondence"]))
            with _cl2.redirect_stdout(_io2.StringIO()):
                checks.append(("clean record -> exit 0", report(_st7, ["correspondence"]) == 0))
            _j.dump({"correspondence": ["A"], "non-vacuity": ["A"]},
                    open(os.path.join(_t6, "2026-06-01-ccccccc", "TARGET.json"), "w"))
            _dr7, _ = scope_drift(_t6, ["correspondence"])
            checks.append(("a TARGET lane that wrote no file is a drift (all its scope dropped)",
                           any(x[1] == "non-vacuity" and x[2] == ["A"] for x in _dr7)))
            with _cl2.redirect_stdout(_io2.StringIO()):
                checks.append(("scope drift -> exit 1", report(_st7, ["correspondence"]) == 1))
            _j.dump({"correspondence": ["N.Foo"]}, open(os.path.join(_t6, "2026-06-01-ccccccc", "TARGET.json"), "w"))
            _j.dump({"lane": "correspondence", "scope": ["N.foo"], "verdicts": []},
                    open(os.path.join(_t6, "2026-06-01-ccccccc", "correspondence.json"), "w"))
            _dr8, _ = scope_drift(_t6, ["correspondence"])
            checks.append(("case matters: N.Foo sent, N.foo returned is a drift",
                           any(x[2] == ["N.Foo"] for x in _dr8)))
            # conflicting verdicts on one item: the worse stands
            shutil.rmtree(_t6); os.makedirs(_t6)
            _w("2026-06-01-ddddddd", "correspondence", [("X", "Fail"), ("X", "Pass")], 1_000_000)
            with _cl2.redirect_stderr(_io2.StringIO()) as _e9:
                _st9 = roll_up(load_rounds(_t6, ["correspondence"]))
            checks.append(("conflicting Fail/Pass on one item -> Fail, with a CONFLICT warning",
                           _st9[("correspondence", "X")]["last"] == "Fail" and "CONFLICT" in _e9.getvalue()))
            _w("2026-06-01-ddddddd", "correspondence", [("Y", "Maybe")], 1_000_000)
            with _cl2.redirect_stderr(_io2.StringIO()):
                _st10 = roll_up(load_rounds(_t6, ["correspondence"]))
            checks.append(("an invalid verdict counts as NotDoneYet, never Pass",
                           _st10[("correspondence", "Y")]["last"] == "NotDoneYet"))
            # repeated decisions
            shutil.rmtree(_t6); os.makedirs(_t6)
            for _k, (_rn, _t) in enumerate((("2026-07-01-eeeeeee", 1_000_000), ("2026-07-02-fffffff", 2_000_000))):
                os.makedirs(os.path.join(_t6, _rn))
                open(os.path.join(_t6, _rn, "ADOPTED.md"), "w").write(
                    "| correspondence | `Z.lean:1 zed` | Fail | **DEFER** | later |\n"
                    + "| correspondence | `Z.lean:3 unc` | STALE PASS | **UNCOVERED** | gone |\n"
                    + ("| correspondence | `Z.lean:2 once` | Fail | **REJECT** | no |\n" if _k == 0 else ""))
                os.utime(os.path.join(_t6, _rn), (_t, _t))
            _str = decision_streaks(_t6)
            for _k, _rn in enumerate(("2026-07-01-eeeeeee", "2026-07-02-fffffff")):
                _j.dump({"verdicts": [{"item": "Ns.lemma_x"}],
                         "out_of_lane": [f"`Ns.stale_doc` docstring is stale (round {_k})",
                                         "S1.decided_one looks duplicated",
                                         f"docstring at Section4Aux1.lean:{987 + _k} is stale",
                                         "lemma_x keeps an idle hypothesis", "the word some_thing is prose"]},
                        open(os.path.join(_t6, _rn, "substantiveness.json"), "w"))
            open(os.path.join(_t6, "2026-07-02-fffffff", "ADOPTED.md"), "a").write(
                "| substantiveness | S1.decided_one | Fail | **REJECT** | fine |\n")
            _r3 = os.path.join(_t6, "2026-07-03-ddddddd"); os.makedirs(_r3)
            _j.dump({"verdicts": [], "out_of_lane": ["docstring at Section4Aux1.lean:990 is still stale",
                                                     "Other.lean:500 noted once more"]},
                    open(os.path.join(_r3, "substantiveness.json"), "w"))
            os.utime(_r3, (3_000_000, 3_000_000))
            _rnotes = dict(repeated_notes(_t6))
            checks.append(("a declaration noted out-of-lane in 2 rounds and never decided is listed; a decided one is not",
                           "Ns.stale_doc" in _rnotes and "S1.decided_one" not in _rnotes))
            checks.append(("a File.lean:N place noted in 2 rounds (lines drifting) is listed; a bare name only if a lane examined it",
                           "Section4Aux1.lean:~980" in _rnotes and "lemma_x" in _rnotes and "some_thing" not in _rnotes
                           and "Other.lean:~500" not in _rnotes))
            checks.append(("a decision repeated in 2 rounds is a streak", any(i.endswith("zed") for i, _, _ in _str)))
            checks.append(("a decision made once is not a streak", not any(i.endswith("once") for i, _, _ in _str)))
            checks.append(("UNCOVERED in 2 rounds is not a repeated decision", not any(i.endswith("unc") for i, _, _ in _str)))
            # parking: an item covered by a standing defer is parked, not orphaned
            shutil.rmtree(_t6); os.makedirs(os.path.join(_t6, "projects")); os.makedirs(os.path.join(_t6, "PR"))
            _j.dump({"rounds_dir": "audits/PR", "standing_defers": [{"id": "lit-hyp", "item": "witness for Ns.erdos_hyp"}]},
                    open(os.path.join(_t6, "projects", "PR.json"), "w"))
            for _rn, _t in (("2026-08-01-1212121", 1_000_000), ("2026-08-02-3434343", 2_000_000)):
                dd = os.path.join(_t6, "PR", _rn); os.makedirs(dd)
                _j.dump({"lane": "non-vacuity", "verdicts": [{"item": "Ns.erdos_hyp", "verdict": "NotDoneYet"},
                                                            {"item": "Ns.other_thing", "verdict": "NotDoneYet"}]},
                        open(os.path.join(dd, "non-vacuity.json"), "w"))
                os.utime(dd, (_t, _t))
            _AUDITS_DIR.clear(); _AUDITS_DIR.append(os.path.join(_t6, "PR"))
            _st11 = roll_up(load_rounds(os.path.join(_t6, "PR"), ["non-vacuity"]))
            with _cl2.redirect_stdout(_io2.StringIO()) as _o11:
                report(_st11, ["non-vacuity"])
            _out11 = _o11.getvalue()
            checks.append(("a NotDoneYet covered by a standing defer is PARKED",
                           "PARKED (1)" in _out11 and "lit-hyp: 1" in _out11))
            checks.append(("an uncovered NotDoneYet is still listed as unexamined", "STILL (1)" in _out11))
        finally:
            shutil.rmtree(_t6, ignore_errors=True)
            _AUDITS_DIR.clear()
        # never-examined compares like with like
        _t8 = tempfile.mkdtemp()
        try:
            _d8 = os.path.join(_t8, "2026-09-01-abababa"); os.makedirs(_d8)
            for _ln, _it in (("correspondence", "N.foo"), ("paper-faithfulness", "Theorem 1.1"),
                             ("non-vacuity", "N.bar")):
                _j.dump({"lane": _ln, "verdicts": [{"item": _it, "verdict": "Pass", "checked": "x"}]},
                        open(os.path.join(_d8, _ln + ".json"), "w"))
            _AUDITS_DIR.clear(); _AUDITS_DIR.append(_t8)
            _l8, _ = discover_lanes(_t8)
            with _cl2.redirect_stdout(_io2.StringIO()) as _o8:
                report(roll_up(load_rounds(_t8, _l8)), _l8)
            _o8 = _o8.getvalue()
            checks.append(("never-examined: a declaration is not 'missing' from the result-keyed lane",
                           "paper-faithfulness: 0" in _o8))
            checks.append(("never-examined: real gaps among same-kind lanes are still reported",
                           "correspondence: 1" in _o8 and "non-vacuity: 1" in _o8))
        finally:
            shutil.rmtree(_t8, ignore_errors=True); _AUDITS_DIR.clear()
        # Stale passes: a Pass survives only while the item's fingerprint is unchanged.
        _t2 = tempfile.mkdtemp()
        try:
            def _snap(rnd, fps, lanes_verdicts, t):
                d = os.path.join(_t2, rnd); os.makedirs(d, exist_ok=True)
                _j.dump({"commit": rnd.split("-")[-1], "fingerprints": fps},
                        open(os.path.join(d, "FINGERPRINTS.json"), "w"))
                for lane, vs in lanes_verdicts.items():
                    _j.dump({"lane": lane, "verdicts": [{"item": i, "verdict": v, "checked": "f:1"}
                                                         for i, v in vs]},
                            open(os.path.join(d, lane + ".json"), "w"))
                os.utime(d, (t, t))
            _snap("2026-03-01-1111111", {"A": "a1", "B": "b1", "C": "c1"},
                  {"correspondence": [("A", "Pass"), ("B", "Pass"), ("C", "Pass"), ("D", "Pass")]},
                  1_000_000)
            _snap("2026-03-02-2222222", {"A": "a1", "B": "b2"}, {}, 2_000_000)
            _d0 = os.path.join(_t2, "2026-02-28-0000000"); os.makedirs(_d0)
            _j.dump({"lane": "correspondence", "verdicts": [{"item": "E", "verdict": "Pass"}]},
                    open(os.path.join(_d0, "correspondence.json"), "w"))
            os.utime(_d0, (500_000, 500_000))
            _st2 = roll_up(load_rounds(_t2, ["correspondence"]))
            _stale, _newest = stale_passes(_t2, _st2)
            _by = {i: w for _, i, _, w in _stale}
            checks.append(("stale: newest snapshot is the later round", _newest == "2026-03-02-2222222"))
            checks.append(("stale: unchanged item A is NOT stale", "A" not in _by))
            checks.append(("stale: item B whose fingerprint moved IS stale",
                           "meaning changed" in _by.get("B", "")))
            checks.append(("stale: item C that vanished IS stale", "no longer exists" in _by.get("C", "")))
            checks.append(("stale: non-declaration item D (no fingerprint) is not judged", "D" not in _by))
            checks.append(("stale: a Pass from a round with no snapshot is reported as unjudgeable",
                           "no fingerprint snapshot" in _by.get("E", "")))
            _t3 = tempfile.mkdtemp()
            checks.append(("stale: no snapshots at all is reported as not checkable",
                           stale_passes(_t3, _st2)[1] is None))
            shutil.rmtree(_t3, ignore_errors=True)
        finally:
            shutil.rmtree(_t2, ignore_errors=True)
        # the never-NotDoneYet report needs >=50 items and >=2 rounds; without a case that
        # reaches it, a NameError in that branch survived a fully green selftest.
        # a lane of its own: `correspondence` already has a NotDoneYet in this fixture, so
        # reusing it would exclude the lane from the report and the branch would never run --
        # which is exactly how the first version of this control passed while the code raised.
        for _r in ("2026-02-01-aaaaaaa", "2026-02-02-bbbbbbb"):
            write(_r, "non-vacuity", [(f"x{i}", "Pass") for i in range(40)])
        _lanes, _ = discover_lanes(tmp)
        _st = roll_up(load_rounds(tmp, _lanes))
        _prev = _AUDITS_DIR[:]
        _AUDITS_DIR.clear(); _AUDITS_DIR.append(tmp)
        try:
            import io, contextlib
            _buf = io.StringIO()
            with contextlib.redirect_stdout(_buf):
                report(_st, _lanes)
            checks.append(("the never-NotDoneYet branch runs without error",
                           "NEVER SAYS NotDoneYet" in _buf.getvalue()))
        except Exception as _e:
            checks.append((f"the never-NotDoneYet branch runs without error ({_e})", False))
        finally:
            _AUDITS_DIR.clear(); _AUDITS_DIR.extend(_prev)

        # missing canonical lanes are "by design" only while every round is a statement round
        _kd = tempfile.mkdtemp()
        try:
            _r1 = os.path.join(_kd, "2026-02-01-full-aaaaaaa"); os.makedirs(_r1)
            json.dump({"_meta": {"kind": "statements"}}, open(os.path.join(_r1, "TARGET.json"), "w"))
            _why = missing_lanes_reason(_kd, ["substantiveness", "prior-art"])
            checks.append(("missing lanes after statement rounds only: explained as by design",
                           "by design" in _why))
            checks.append(("a statement-round lane missing is NOT explained away",
                           missing_lanes_reason(_kd, ["substantiveness", "non-vacuity"]) == ""))
            _r0 = os.path.join(_kd, "2026-01-31-aaaaaaa"); os.makedirs(_r0)   # no TARGET.json
            checks.append(("a round of unknown kind is not taken for a statement round",
                           missing_lanes_reason(_kd, ["substantiveness"]) == ""))
            shutil.rmtree(_r0)
            _r2 = os.path.join(_kd, "2026-02-02-aaaaaaa"); os.makedirs(_r2)
            json.dump({"_meta": {"kind": "diff"}}, open(os.path.join(_r2, "TARGET.json"), "w"))
            checks.append(("after a proof round, missing substantiveness is NOT explained away",
                           missing_lanes_reason(_kd, ["substantiveness"]) == ""))
        finally:
            shutil.rmtree(_kd, ignore_errors=True)

        ok = True
        for name, passed in checks:
            print(f"  {'ok  ' if passed else 'FAIL'}  {name}")
            ok = ok and passed
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



from scope import STATEMENT_LANES  # noqa: E402  (one list: scope.py decides what a statement round runs)
STATEMENT_ROUND_LANES = set(STATEMENT_LANES)


def round_kinds(audits_dir):
    """{round name: kind} from each round's TARGET.json (`_meta.kind`); "unknown" if unreadable."""
    out = {}
    for d in _dirs(audits_dir):
        if os.path.isdir(d) and ROUND_DIR_RE.match(os.path.basename(d)):
            try:
                k = json.load(open(os.path.join(d, "TARGET.json"))).get("_meta", {}).get("kind")
            except (OSError, ValueError):
                k = None
            # a round whose kind cannot be read counts as "unknown", never as a statement round:
            # an unreadable kind must not explain a missing proof lane away
            out[os.path.basename(d)] = k or "unknown"
    return out


def missing_lanes_reason(audits_dir, missing):
    """Why canonical lanes have no data, when the answer is "by design": a statement round runs
    only the three statement lanes, so substantiveness (which needs proofs) and prior-art are
    absent until the first proof round. Without this note an adjudicator reads the gap as a lane
    that should have run (it did, in a test run)."""
    kinds = round_kinds(audits_dir)
    if kinds and set(kinds.values()) == {"statements"}:
        by_design = [l for l in missing if l not in STATEMENT_ROUND_LANES]
        if by_design == missing:
            return (" -- expected: every round so far is a statement round, which runs only "
                    + ", ".join(sorted(STATEMENT_ROUND_LANES)) + " (by design; not UNCOVERED)")
    return ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audits_dir", nargs="?",
                    default=os.path.join(os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__))), "audits"))
    ap.add_argument("--lane")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    a.explicit = a.audits_dir != ap.get_default("audits_dir")

    if a.selftest:
        return selftest()

    if not os.path.isdir(a.audits_dir):
        print(f"FAIL: no audits directory at {a.audits_dir}", file=sys.stderr)
        return 2
    # Refuse to guess between projects. With per-project rounds directories the no-argument
    # form silently reported on whichever project happened to keep its rounds at the top level,
    # which for months was one specific paper -- a roll-up confidently describing a project the
    # reader was not asking about.
    subs = [d for d in sorted(glob.glob(os.path.join(a.audits_dir, "*")))
            if os.path.isdir(d) and not ROUND_DIR_RE.match(os.path.basename(d))
            and any(ROUND_DIR_RE.match(os.path.basename(x))
                    for x in glob.glob(os.path.join(d, "*")) if os.path.isdir(x))]
    if subs and not a.explicit:
        print(f"FAIL: {a.audits_dir} holds per-project rounds directories. Name one:",
              file=sys.stderr)
        for d in subs:
            print(f"    {os.path.relpath(d)}", file=sys.stderr)
        return 2
    lanes, unknown = discover_lanes(a.audits_dir)
    if unknown:
        print(f"note: non-canonical lane(s) found and included: {', '.join(unknown)}")
    missing = [l for l in CANONICAL if l not in lanes]
    if missing:
        print(f"note: canonical lane(s) with no data in any round: {', '.join(missing)}"
              + missing_lanes_reason(a.audits_dir, missing))
    _AUDITS_DIR.append(a.audits_dir)
    rounds = load_rounds(a.audits_dir, lanes)
    if not rounds:
        # Refuse to pass vacuously: an empty roll-up must not read as "everything is covered".
        print(f"no audit rounds found in {a.audits_dir} — nothing has been examined yet")
        return 0
    print(f"rolled up {len(rounds)} lane-round(s) from {a.audits_dir}\n")
    return report(roll_up(rounds), lanes, a.lane, rounds)


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

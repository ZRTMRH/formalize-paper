#!/usr/bin/env python3
"""The fresh-reader gate: no document reaches the human unless a fresh reader passed THAT version
of it and no blocking finding any reader raised has silently disappeared (RUN.md, "Fresh-reader
check"; AUDIT_PROTOCOL.md, "Documents a human reads", rule 7).

WHY THIS EXISTS.  In a test run a hand-written decisions document passed its writer's own
reading; four successive fresh readers then found 20, 11, 12 and 10 problems. Without a gate the
check is advice: the report lives in the conversation, a document can change after its last pass,
and a reader can be re-run until one says "no blocking problems".

THE INVARIANT (what the gate enforces).  Two earlier designs counted passes and forbade re-reading
an unchanged document; an independent audit showed both could be gamed (a one-space edit, toggling
A→B→A, a malformed or empty record) and both deadlocked an honest operator (a finding that is true
but cannot be fixed in this run). The gate now checks only what matters:
  1. the newest well-formed pass read exactly the version being delivered;
  2. EVERY `- BLOCKING:` finding in ANY reader file of this document (well-formed or not) is
     answered in that pass's response files `<key>-<n>.response[-k].md`, by a line quoting its
     START (one finding per line; the last answer counts):
       - fixed: <quote> — <what changed>        (only once a later pass read a changed version; on a generated
                                                 document: "tool patch TP<k>" or "hand edit HE<k>", below)
       - dismissed: <quote> — <evidence that the finding is wrong, or "trivial: ..."> (the REJECT)
       - unfixable: <quote> — <why no path is open in this run, or "fix budget reached">
                                                          (must also be in the notice; never a fault of a
                                                          generated document's own text: DOC-FIX G4)
  3. every `unfixable` finding is quoted in `KNOWN_FAULTS-<key>.md`, the notice shown with the
     document and in the checkpoint message (never inside the hashed document).
Re-running a reader then gains nothing: the findings it would wash away must still be answered.
Passes beyond 3 are allowed but pointless; RUN.md tells the operator to stop fixing after 3 and
mark what remains `unfixable`.

WHAT IS HASHED.  The markdown, the audited content, never a PDF (the PDF is made afterwards from exactly this
text by fresh agents, render_record.py, and fingerprinted against it):
  signoff     <round>/SIGNOFF.md               (covers SIGNOFF.json, INFORMAL.json, the generator)
  questions   QUESTIONS-B-<round>.md             (the open questions put under the Checkpoint B question)
  report      REPORT.md, minus its "Generated <date>" header line
  decisions   DECISIONS.md
  other:PATH  the file itself
`readers.py --hash --doc …` prints it; the reader's prompt tells it to run exactly that.

WHERE RECORDS LIVE.  `<rounds_dir>/readers/<key>-<n>.md` (+ `.response.md`), where the key names
the document AND its cycle: `signoff-<round>`, `questions-<round>`, `report-<newest round>`, `decisions-<newest
round>` (computed, never read from the document), `other-<name>-<id>` (only inside the rounds
directory, keyed by its path there). Each record is committed alone as `reader <key> <n>` by the
reader; the operator commits the responses `<key>-<n>.response.md` (corrections in
`.response-2.md`, ...) and the notice as `reader <key> <n> (response)`. Every file is read AS FIRST
COMMITTED (record_texts), so a later edit, rename or deletion cannot wash a finding; such changes
are printed as NOTEs for the human rather than refusing the gate (a refusal there deadlocked the
whole project on one reformatted record).

LIMITS.  The gate cannot tell whether a fresh agent wrote a record: an operator could write one
by hand, or remove one by rewriting git history (RUN.md forbids both). A one-space edit
satisfies `fixed`, and so does a pass whose reader wrote a wrong sha; the human sees every
`fixed:` line, which is the only defence. A shallow clone, or a tracked record whose adding commit
git does not show, makes the gate fail closed.

  python3 audits/readers.py --doc signoff|questions --round R|approved --hash|--next|--check
  python3 audits/readers.py --doc report|decisions|other:<abs path> --hash|--next|--check
  python3 audits/readers.py --doc … --save < record.txt   (the reader saves and commits its record)
  python3 audits/readers.py --doc summary|report --hand-edit --finding "<record>: <quote>"   (DOC-FIX: your edit of a
                                                          generated document after the final prepare, committed)
  python3 audits/readers.py --selftest

SAVING A RECORD.  A reader agent should not need a file-writing tool: some harnesses refuse a
subagent's Write call ("subagents should return findings as text"), and the operator then had to
retype the record, which loses the guarantee that the reader wrote it. `--save` takes the record
on stdin, refuses a malformed one or one whose sha256 line is not the document's current hash,
writes `<key>-<n>.md`, commits that one file as `reader <key> <n>`, and checks that the committed
file is byte for byte the text it was given. A reader with only Bash runs it itself; otherwise the
operator pipes the reader's returned text in unedited.
"""
import sys
sys.dont_write_bytecode = True
import argparse, glob, hashlib, json, os, re, subprocess, tempfile, shutil

import project

VERDICT_RE = re.compile(r"^VERDICT: (NO BLOCKING PROBLEMS|BLOCKING PROBLEMS: ([1-9]\d*))$")
SHA_RE = re.compile(r"^sha256: ([0-9a-f]{64})$")
FINDING_RE = re.compile(r"^\s*-\s*(BLOCKING|NOT BLOCKING):\s*(.*)$")
LOOSE_BLOCKING_RE = re.compile(r"(?<!NOT )(?<!NOT-)(?<!NON-)(?<!NON )\bBLOCKING\b\s*:?\s*(.*)$", re.I)
RESPONSE_HEAD_RE = re.compile(r"^\s*-\s*(fixed|dismissed|unfixable):\s*(.*)$")
# the report's date stamp: markdown header line and the LaTeX one (make_report.py)
REPORT_STAMP_RES = [re.compile(r"^\*\*Generated \d{4}-\d{2}-\d{2} by `audits/make_report\.py`\. Do not edit this file\.\*\*$", re.M),
                    re.compile(r"\{\\small Generated \d{4}-\d{2}-\d{2} from the audit records\. Do not edit this file\.\}")]
DECISIONS_ROUND_RE = re.compile(r"<!--\s*decisions-round:\s*(\S+)\s*-->")


class DocError(Exception):
    pass


# B10 (U2 §6.3): each document's reader mode, fixed here (never chosen by the operator).
#   gated   the newest well-formed pass read the current version and every blocking finding is answered
#           (SUMMARY at every level; the Checkpoint B documents; other:PATH)
#   single  exactly one well-formed pass on the current version; a regenerated document gets one new pass
#           (REPORT, DECISIONS)
#   sheet   the approval-time pass stays valid while the sheet's hash is unchanged (gated); under hands-off the
#           delivered sheet has no reader at all (signoff.py check is kept; the README discloses it)
MODES = {"summary": "gated", "report": "single", "decisions": "single", "signoff": "gated",
         "questions": "gated", "other": "gated"}
# a reader labels each finding: content (what the document says is wrong or missing: the adjudicator's
# records are fixed in a reader-fix round, prompt.py 4 --reader-fix) or presentation (how it is said; a
# generator fault: disclosed in the notice). An unlabelled finding is content (the route that changes the
# records, never the one that only discloses)
LABEL_RE = re.compile(r"^\s*\[(content|presentation)\]\s*", re.I)
FIX_BUDGET = 2          # reader-fix rounds per run (U2 §6.3, ADDENDUM N4)
READER_FIX_SUBJECT = re.compile(r"^reader-fix (\S+) ([1-9]\d*)$")
DELIVERY_RECORD = "DELIVERY.json"   # project.py --prepare-delivery's record (the delivery flow, B10)


def mode_of(doc):
    return MODES["other" if str(doc).startswith("other:") else doc]


def label(finding):
    """"content" or "presentation" (unlabelled: content)."""
    m = LABEL_RE.match(finding or "")
    return m.group(1).lower() if m else "content"


def fix_rounds_used(cfg=None):
    """The reader-fix rounds of the run so far (commits "reader-fix R n" in the audit record's history; a git
    failure counts as the budget spent, so a content finding is never held for a round that cannot be
    counted)."""
    r = git("log", "--format=%s")
    if r.returncode != 0:
        return FIX_BUDGET
    return sum(1 for l in r.stdout.splitlines() if READER_FIX_SUBJECT.match(l.strip()))


def content_findings(cfg):
    """[(key, reader file, finding)] of the delivered documents' readers (summary, report, decisions of the newest
    round) whose BLOCKING finding is labelled content and is not answered fixed or dismissed: what a reader-fix
    round (prompt.py 4 --reader-fix) is given. Read as first committed (record_texts)."""
    out = []
    try:
        texts = record_texts(readers_dir(cfg))
    except DocError:
        texts = record_texts(readers_dir(cfg), use_git=False)
    newest = newest_round(cfg)
    for doc in ("summary", "report", "decisions"):
        key = f"{doc}-{newest}"
        files = reader_files(texts, key)
        flow = {nm for _, nm in files} if doc == "summary" else flow_passes(cfg, [nm for _, nm in files])
        for n, name in files:
            if name not in flow:
                continue        # recorded before the delivery flow: answered under the rules of its time
            r = parse(name, texts[name])
            uniq = list(dict.fromkeys(t for k, t in r["findings"] if k == "BLOCKING"))
            resp, _ = responses(texts, response_names(texts, key, n))
            answers = [(kind, answered_set(c, uniq)) for kind, c in resp]
            for i, f in enumerate(uniq):
                hit = [kind for kind, ids in answers if i in ids]
                if label(f) == "content" and (not hit or hit[-1] == "unfixable"):
                    out.append((key, name, f))
    return out


def flow_passes(cfg, names):
    """The reader files among `names` recorded under the delivery flow (B10): added at or after the first
    commit of DELIVERY.json (project.py --prepare-delivery). Without git (record_texts read from disk) every
    one counts once DELIVERY.json exists. A pass recorded before the flow began keeps the rules it was
    answered under (an older run's unfixable answers stay valid)."""
    if not os.path.exists(os.path.join(rounds_root(cfg), DELIVERY_RECORD)):
        return set()
    added = getattr(record_texts, "added", None)
    if added is None:
        return set(names)
    rel = os.path.relpath(os.path.join(rounds_root(cfg), DELIVERY_RECORD), project.AUDITS)
    lg = git("log", "--format=%H", "--diff-filter=A", "--", rel)
    first = lg.stdout.split()[-1] if lg.returncode == 0 and lg.stdout.split() else None
    if first is None:
        return set(names)       # not committed yet: fail closed (the new rules apply)
    out = set()
    for n in names:
        c = added.get(n)
        if c is None or git("merge-base", "--is-ancestor", first, c).returncode == 0:
            out.add(n)
    return out


def delivery_flow(cfg, doc):
    """True when the B10 delivery rules apply to `doc`: always for the summary; for the report and the
    decisions document once project.py --prepare-delivery has run (an older run's records keep their rules)."""
    return doc == "summary" or (doc in ("report", "decisions")
                                and os.path.exists(os.path.join(rounds_root(cfg), DELIVERY_RECORD)))


def rounds_root(cfg):
    return os.path.normpath(os.path.join(project.REPO, cfg["rounds_dir"]))


def resolve(cfg, doc, round_name=None):
    """(key, [source paths], display path) for a document; raises DocError."""
    root = rounds_root(cfg)
    if doc == "signoff":
        if round_name == "approved":
            # the delivered sheet is the APPROVED one, read from the approval record, never typed
            ap = os.path.join(root, "APPROVED_FINGERPRINTS.json")
            try:
                round_name = json.load(open(ap, encoding="utf-8")).get("round")
            except (OSError, ValueError):
                round_name = None
            if not round_name:
                raise DocError(f"--round approved: no round recorded in {ap}")
        if not round_name:
            raise DocError("--doc signoff needs --round (the sheet's round, or `approved`)")
        rd = os.path.join(root, round_name)
        srcs = [os.path.join(rd, "SIGNOFF.md")]
        key, shown = f"signoff-{round_name}", srcs[0]
    elif doc == "report":
        srcs = [os.path.join(root, "REPORT.md")]
        # one history per checkpoint cycle (the newest round), so a notice from an earlier
        # Checkpoint C is not carried into a later one
        newest = newest_round(cfg)
        if not newest:
            raise DocError("no audit round found: the report is checked for the newest round")
        key, shown = f"report-{newest}", srcs[0]
    elif doc == "summary":
        # B10: the one-page summary, generated by make_report.py (project.py --prepare-delivery); keyed by the
        # newest round, like the report
        newest = newest_round(cfg)
        if not newest:
            raise DocError("no audit round found: the summary is checked for the newest round")
        srcs, key, shown = [os.path.join(root, "SUMMARY.md")], f"summary-{newest}", os.path.join(root, "SUMMARY.md")
    elif doc == "decisions":
        p = os.path.join(root, "DECISIONS.md")
        if not os.path.exists(p):
            raise DocError(f"{p} does not exist")
        # The key is the NEWEST round, computed, never read from the document: a tag the operator
        # can edit would start a fresh history and wash away every earlier finding.
        newest = newest_round(cfg)
        if not newest:
            raise DocError("no audit round found: DECISIONS.md is written for the newest round")
        m = DECISIONS_ROUND_RE.search(open(p, encoding="utf-8").read())
        if not m or m.group(1) != newest:
            raise DocError(f"DECISIONS.md is tagged for round {m.group(1) if m else '(no tag)'}, but the "
                           f"newest round is {newest}: regenerate it (decisions.py --write)")
        key, srcs, shown = f"decisions-{newest}", [p], p
    elif doc == "questions":
        if not round_name:
            raise DocError("--doc questions needs --round (the sheet's round)")
        if not os.path.exists(os.path.join(root, round_name, "SIGNOFF.json")):
            raise DocError(f"--doc questions: round {round_name} has no sign-off sheet (SIGNOFF.json)")
        p = os.path.join(root, f"QUESTIONS-B-{round_name}.md")
        key, srcs, shown = f"questions-{round_name}", [p], p
    elif doc.startswith("other:"):
        p = doc.split(":", 1)[1]
        if not os.path.isabs(p):
            raise DocError("--doc other:PATH needs an absolute path")
        rel = os.path.relpath(os.path.realpath(p), os.path.realpath(root))
        if rel.startswith(".."):
            # keyed by its place in the record: a copy elsewhere must not start a fresh history
            raise DocError(f"--doc other:PATH must lie inside the rounds directory {root}")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(p)).strip("-")[:40]
        key = f"other-{slug}-{hashlib.sha1(rel.encode()).hexdigest()[:10]}"
        srcs, shown = [p], p
    else:
        raise DocError(f"--doc must be signoff, questions, report, decisions, summary or other:<abs path>, got {doc!r}")
    missing = [s for s in srcs if not os.path.exists(s)]
    if missing:
        raise DocError("source missing (render or write it first): " + ", ".join(missing))
    return key, srcs, shown


def newest_round(cfg):
    rs = project.rounds(cfg)
    return os.path.basename(rs[-1]) if rs else None


def content_hash(paths, doc):
    h = hashlib.sha256()
    for p in paths:
        data = open(p, "rb").read()
        if doc == "report":
            t = data.decode("utf-8", "replace")
            for rx in REPORT_STAMP_RES:
                t = rx.sub("", t, count=1)
            data = t.encode("utf-8")
        elif doc == "signoff":
            # the approval's wording ("will be approved" before, "approved" after: mini5 audit) is a stamp:
            # a re-render after the approval keeps the reader's pass
            import signoff
            data = signoff.unstamp(data.decode("utf-8", "replace")).encode("utf-8")
        h.update(os.path.basename(p).encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def legacy_hash(srcs, doc):
    """PDF-AGENTS migration shim (one version; drop it in the next minor version): a pass recorded before the hash
    became md-only read the md AND the generated .tex beside it (REPORT.tex, SIGNOFF.tex). The hash of the md as it
    is now with that .tex, still on disk and read by nothing else since, stands for the same version: an old pass
    stays valid while the md is unchanged. None when there is no such .tex."""
    if doc not in ("report", "signoff") or len(srcs) != 1 or not srcs[0].endswith(".md"):
        return None
    tex = srcs[0][:-3] + ".tex"
    return content_hash([srcs[0], tex], doc) if os.path.exists(tex) else None


def readers_dir(cfg):
    return os.path.join(rounds_root(cfg), "readers")


def record_texts(rdir, use_git=True):
    """{file name: text} of every reader record and response file. With git, each committed file is
    read FROM THE COMMIT THAT ADDED IT: a later edit, rename or deletion can neither wash a finding
    away nor block the project (records are append-only by rule; this makes the rule hold by
    construction). Files not yet committed are read from disk (and refused by the gate)."""
    out = {}
    record_texts.unseen = []
    record_texts.added = None       # {file name: the commit that added it}, with git
    if os.path.isdir(rdir):
        for p in glob.glob(os.path.join(rdir, "*.md")):
            out[os.path.basename(p)] = open(p, encoding="utf-8").read()
    if not use_git:
        return out
    rel = os.path.relpath(rdir, project.AUDITS)
    sh_ = git("rev-parse", "--is-shallow-repository")
    if sh_.returncode != 0 or sh_.stdout.strip() == "true":
        raise DocError("the audits repository is a shallow clone (or git failed): the reader records' "
                       "first commits cannot be seen; fetch the full history")
    # -z: paths are NUL-separated and never C-quoted (non-ASCII rounds directories);
    # --first-parent with --diff-merges=first-parent: the history of THIS line of work, where a
    # record brought in by a merge counts as added by that merge -- a side branch's own add (say a
    # backdated clean copy merged with `-s ours`) can never stand in for the record
    pf = git("rev-parse", "--show-prefix")
    if pf.returncode != 0:
        raise DocError(f"git rev-parse failed: {pf.stderr.strip()[:120]}")
    toprel = os.path.normpath(os.path.join(pf.stdout.strip(), rel))     # rel to the repository top
    lg = git("-c", "core.quotePath=false", "log", "--root", "--first-parent", "--no-renames",
             "--diff-merges=first-parent", "--diff-filter=A", "-z", "--format=%x01%H", "--name-only", "--", rel)
    if lg.returncode != 0:
        raise DocError(f"git log failed, so the reader records cannot be read: {lg.stderr.strip()[:120]}")
    added = {}
    for block in lg.stdout.split("\x01")[1:]:          # newest commit first
        parts = [x.strip("\n") for x in block.split("\x00") if x.strip("\n")]
        if not parts:
            continue
        commit, paths = parts[0].split("\n")[0], [parts[0].split("\n", 1)[1]] if "\n" in parts[0] else []
        paths += parts[1:]
        for path in paths:
            # records are files directly in the readers directory: a same-named file in a
            # subdirectory must not stand in for one
            if os.path.dirname(path) == toprel:
                added[path] = commit                    # ends at the OLDEST adding commit
    tracked = git("-c", "core.quotePath=false", "ls-files", "--full-name", "-z", "--", rel)
    if tracked.returncode != 0:
        raise DocError(f"git ls-files failed: {tracked.stderr.strip()[:120]}")
    # tracked (staged) but with no adding commit: read from disk, so not yet a record; check()
    # refuses the documents they belong to, and only those
    record_texts.unseen = [os.path.basename(p) for p in tracked.stdout.split("\x00")
                           if p and os.path.dirname(p) == toprel and p not in added]
    record_texts.added = {os.path.basename(p_): c_ for p_, c_ in added.items()}
    for path, c in added.items():
        sh = git("show", f"{c}:{path}")
        if sh.returncode != 0:
            raise DocError(f"git show {c[:10]}:{path} failed: {sh.stderr.strip()[:120]}")
        out[os.path.basename(path)] = sh.stdout
    return out


def key_file(key, name):
    """Is `name` a record or response file of exactly this key (not of a key that starts with it)?"""
    return re.match(rf"^{re.escape(key)}-\d+(?:\.response(?:-\d+)?)?\.md$", name) is not None


def reader_files(texts, key):
    """[(n, name)] of the key's reader records, by pass number."""
    out = []
    for name in texts:
        m = re.match(rf"^{re.escape(key)}-(\d+)\.md$", name)
        if m:
            out.append((int(m.group(1)), name))
    return sorted(out)


def parse(name, text):
    """dict(sha, verdict, blocking, findings [(kind, text)], problems)."""
    lines = text.splitlines()
    out = {"sha": None, "verdict": None, "blocking": None, "findings": [], "problems": []}
    m = SHA_RE.match(lines[0].strip()) if lines else None
    if m:
        out["sha"] = m.group(1)
    else:
        out["problems"].append(f"{name}: first line is not `sha256: <64 hex>`")
        # the version a malformed pass read, if it says so anywhere (an honest `fixed` needs it)
        any_sha = next((SHA_RE.match(l.strip()) for l in lines if SHA_RE.match(l.strip())), None)
        out["sha"] = any_sha.group(1) if any_sha else None
    last = next((l.strip() for l in reversed(lines) if l.strip()), "")
    v = VERDICT_RE.match(last)
    if v:
        out["verdict"] = v.group(0)
        out["blocking"] = int(v.group(2)) if v.group(2) else 0
    else:
        out["problems"].append(f"{name}: last line is not a well-formed VERDICT line")
    if not any(l.lower().startswith("coverage:") for l in lines):
        out["problems"].append(f"{name}: no `coverage:` line")
    # a finding is its marker line plus the indented lines that continue it; a marker with no
    # text on its line takes the next non-blank lines (up to a blank line or the next marker)
    for i, l in enumerate(lines):
        m = FINDING_RE.match(l)
        if not m:
            continue
        text = [m.group(2).strip()]
        rest = lines[i + 1:]
        if not text[0]:
            while rest and not rest[0].strip():
                rest = rest[1:]
            for c in rest:
                if not c.strip() or FINDING_RE.match(c) or VERDICT_RE.match(c.strip()):
                    break
                text.append(c.strip())
        else:
            for c in rest:
                if not c.strip() or not c[:1].isspace() or FINDING_RE.match(c):
                    break
                text.append(c.strip())
        t = " ".join(x for x in text if x)
        if not t:
            out["problems"].append(f"{name}: a `- {m.group(1)}:` line with no text")
            t = f"(empty finding, line {i + 1})"
        out["findings"].append((m.group(1), t))
    nb = sum(1 for k, _ in out["findings"] if k == "BLOCKING")
    if v and nb != out["blocking"]:
        out["problems"].append(f"{name}: the verdict says {out['blocking']} blocking, the report lists "
                               f"{nb} `- BLOCKING:` finding(s)")
    if out["problems"]:
        # In a malformed file a finding may carry a wrong marker (`- **BLOCKING:**`, `1. BLOCKING:`);
        # it must still be answered, or a malformed pass would silently drop it.
        have = {_norm(t) for k, t in out["findings"] if k == "BLOCKING"}
        for l in lines:
            plain = re.sub(r"[*_`]", "", l)
            if FINDING_RE.match(l) or re.match(r"^\W*VERDICT\b", plain):
                continue
            m = LOOSE_BLOCKING_RE.search(plain)
            if m and m.group(1).strip() and _norm(m.group(1)) not in have:
                have.add(_norm(m.group(1)))
                out["findings"].append(("BLOCKING", m.group(1).strip()))
    return out


def response_names(texts, key, n):
    """Pass n's response files: `<key>-<n>.response.md`, then corrections in
    `<key>-<n>.response-2.md`, `-3`, ... (a committed response with a typo is answered again in a
    new file, never edited); later files win."""
    out = []
    for name in texts:
        m = re.match(rf"^{re.escape(key)}-{n}\.response(?:-(\d+))?\.md$", name)
        if m:
            out.append((int(m.group(1) or 1), name))
    return [p for _, p in sorted(out)]


def responses(texts, names):
    """([(kind, [candidate quotes])], [unparsed list lines]). A finding may itself contain ` — `, so
    every split point of the line before its answer is a candidate quote. `responses.bodies` holds each answer
    line's text after its kind, parallel to the first list (the reason a quote is followed by)."""
    got, bad, bodies = [], [], []
    for name in names:
        for l in texts[name].splitlines():
            m = RESPONSE_HEAD_RE.match(l)
            body = m.group(2) if m else ""
            parts = body.split(" — ")
            cands = [" — ".join(parts[:k]).strip() for k in range(1, len(parts))
                     if " — ".join(parts[k:]).strip()]
            if m and cands:
                got.append((m.group(1), cands))
                bodies.append(body)
            elif l.lstrip().startswith(("-", "*")) and l.strip() not in ("-", "*"):
                bad.append(f"{name}: {l.strip()[:80]}")
    responses.bodies = bodies
    return got, bad


def reason_of(body, cands, finding):
    """The answer part of a response line (what follows the quote that answers `finding`)."""
    for q in sorted(cands, key=len, reverse=True):
        if _norm(q) == _norm(finding) or covers(q, finding):
            return body.strip()[len(q.strip()):].lstrip(" —")
    return body


def _norm(s):
    # a finding's label ([content] / [presentation], B10) is not part of what a response or a notice quotes
    return re.sub(r"\s+", " ", LABEL_RE.sub("", s, count=1)).strip().strip('"“”`').lower()


def covers(quote, finding):
    """Does `quote` reproduce the START of `finding`: at least 15 characters, or all of a
    shorter finding?"""
    q, f = _norm(quote), _norm(finding)
    return bool(q) and len(q) >= min(15, len(f)) and f.startswith(q)


def answered_set(cands, findings):
    """The findings (indices into the DISTINCT findings of a pass) one response line answers: the
    first candidate quote that covers exactly one finding, or equals one in full (a finding that
    is a prefix of another is answered by quoting it whole). Empty if ambiguous."""
    # longest first: a quote for "X — more" must not stop at "X" when X is itself a finding
    for q in reversed(cands):
        exact = [i for i, f in enumerate(findings) if _norm(q) == _norm(f)]
        if exact:
            return set(exact)
        hit = [i for i, f in enumerate(findings) if covers(q, f)]
        if len(hit) == 1:
            return set(hit)
    return set()


def next_number(cfg, key):
    """The next pass number: after every record on disk or ever committed."""
    rdir = readers_dir(cfg)
    try:
        texts = record_texts(rdir, use_git=True)
    except DocError:
        texts = record_texts(rdir, use_git=False)
    files = reader_files(texts, key)
    return (files[-1][0] + 1) if files else 1


def git(*a):
    return subprocess.run(["git", "-C", project.AUDITS, *a], capture_output=True, text=True)


def history_problems(rdir, key):
    """The key's records and its notice must be committed (an uncommitted record could vanish).
    Fails CLOSED: a git error is a problem. Edits and deletions after a commit are harmless --
    records are read from the commit that added them -- and are listed by history_notes."""
    rel = os.path.relpath(rdir, project.AUDITS)
    kf = os.path.join(os.path.dirname(rel), f"KNOWN_FAULTS-{key}.md")
    st = git("status", "--porcelain", "--untracked-files=all", "--", os.path.join(rel, f"{key}-*"), kf)
    if st.returncode != 0:
        return [f"git status failed, so the reader records cannot be checked: {st.stderr.strip()[:120]}"]
    return [f"reader record or notice not committed (or changed since): {l[3:]}"
            for l in st.stdout.splitlines()]


def history_notes(rdir, key):
    """Records of this key edited, renamed or deleted after their commit (shown to the human)."""
    rel = os.path.relpath(rdir, project.AUDITS)
    lg = git("-c", "core.quotePath=false", "log", "--root", "--full-history", "--diff-merges=first-parent",
             "--no-renames", "--diff-filter=DMR", "--name-status", "-z", "--format=", "--",
             os.path.join(rel, f"{key}-*"))
    if lg.returncode != 0:
        return [f"git log failed: {lg.stderr.strip()[:120]}"]
    parts = [x.strip("\n") for x in lg.stdout.split("\x00") if x.strip("\n")]
    return [f"{parts[i]} {parts[i + 1]}" for i in range(0, len(parts) - 1, 2)]


def outcome_text(key, n_unfixable, n_budget):
    """(clean, what happened) of a reader gate: 'passed' only when no blocking finding was left
    answered unfixable (mini4 audit: a run log and README said the gate 'passed' after 3 passes that
    ended at the fix budget with blocking findings)."""
    if not n_unfixable:
        return True, "passed (every blocking finding was fixed and re-read)"
    return False, (f"NOT passed: it ended with {n_unfixable} blocking finding(s) answered unfixable"
                   + (f" ({n_budget} at the fix budget)" if n_budget else "")
                   # conf1 (C1 audit): README D said "No separate KNOWN_FAULTS file is delivered" and then "quoted in
                   # KNOWN_FAULTS-<key>.md and delivered with the document"; the notice is folded into RUN_RECORD.md
                   + f", quoted in RUN_RECORD.md (from the notice KNOWN_FAULTS-{key}.md, folded in there; it is not "
                     f"delivered as a file)")


PASSED_RE = re.compile(r"\b(passed|pass(?:ing)? cleanly|clean pass)\b", re.I)


def log_claims(cfg, key, what):
    """RUN_LOG.md lines that say the fresh-reader check of this document passed when it did not
    (blocking findings left unfixable): each is a problem, so the log says what happened."""
    doc = key.split("-", 1)[0]
    try:
        log = open(os.path.join(rounds_root(cfg), "RUN_LOG.md"), encoding="utf-8").read()
    except OSError:
        return []
    out = []
    for l in log.splitlines():
        low = l.lower()
        if "reader" in low and PASSED_RE.search(l) and (key in l or re.search(rf"\b{doc}\b", low)) \
                and "not passed" not in low:
            out.append(f"RUN_LOG.md says the fresh-reader check of {key} passed ({' '.join(l.split())[:120]!r}), "
                       f"but it {what[0].lower() + what[1:]}: say what happened")
    return out


def outcome(cfg, doc, round_name=None):
    """What the fresh-reader gate of a document says happened (outcome_text), or why it is unknown."""
    try:
        check(cfg, doc, round_name)
    except Exception as e:      # noqa: BLE001 -- the README says it could not be read
        return f"could not be read ({e})"
    return check.outcome[1] if check.outcome else "no complete reader record"


def stale_finding(key, text):
    """A missing, malformed or stale pass: N ("reader") in release, except on the sign-off sheet and the summary
    (F: the summary's gate holds at every level, U2 §6.3)."""
    return text if key.startswith(("signoff", "summary")) else project.Finding(text, "reader")


def check(cfg, doc, round_name=None, check_git=True):
    """Problems preventing delivery (empty list = deliverable). Also sets `check.outcome`: what the
    gate's history says happened (outcome_text), for the summary line, the run-log check and the
    delivery README."""
    check.outcome = None
    try:
        key, srcs, _ = resolve(cfg, doc, round_name)
        rdir = readers_dir(cfg)
        texts = record_texts(rdir, use_git=check_git)
    except DocError as e:
        return [str(e)]
    # release mode (project.RELEASE "reader", review H2): only a missing, malformed or stale pass
    # on a document other than the sign-off sheet is N. Every finding about the sheet (its reader
    # is the pre-approval faithfulness check), an unanswered BLOCKING finding, a false `fixed` and an
    # unfixable finding the notice does not quote block in every mode: the answer path (`unfixable`
    # after 3 passes, quoted in the notice) means they never stall a run. Uncommitted records block.
    R = lambda p_: stale_finding(key, p_)
    files = reader_files(texts, key)
    if not files:
        return [R(f"no fresh-reader pass for {key}: run the fresh-reader check (audits/run/fresh-reader.md)")]
    probs = history_problems(rdir, key) if check_git else []
    probs += [f"reader file tracked but not committed (commit it): {u}"
              for u in getattr(record_texts, "unseen", []) if key_file(key, u)]
    parsed = [(n, name, parse(name, texts[name])) for n, name in files]
    good = [(n, p, r) for n, p, r in parsed if not r["problems"]]
    if not good:
        return probs + [R(f"no well-formed pass for {key} (malformed: "
                          + ", ".join(p for _, p, _ in parsed) + ")")]
    newest_n, newest_p, newest = good[-1]
    if parsed[-1][0] != newest_n:
        probs.append(R(f"the newest reader file ({parsed[-1][1]}) is malformed: spawn a new "
                     f"reader on the same document (its findings must still be answered)"))
    cur = content_hash(srcs, doc)
    old_ = legacy_hash(srcs, doc) if newest["sha"] != cur else None
    if old_ and newest["sha"] == old_:
        cur = old_          # the migration shim: a pass on the md and its old .tex, the md unchanged since
    if newest["sha"] != cur:
        probs.append(R(f"the document changed after its last well-formed pass ({newest_p} read "
                     f"{newest['sha'][:12]}…, the source is now {cur[:12]}…): run a new pass on this version"))
    new_flow = delivery_flow(cfg, doc.split(":")[0] if doc.startswith("other:") else doc)
    flow = (flow_passes(cfg, [p for _, p, _ in parsed]) if doc != "summary" else {p for _, p, _ in parsed}) \
        if new_flow else set()
    if new_flow and mode_of(doc) == "single":
        # U2 §6.3: exactly one pass on the current version; another pass on it gains nothing (its findings must
        # still be answered) and is refused, so no reader is re-run until one says nothing. Counted over the
        # passes of the delivery flow (an older run's passes on the same text are not the operator's choice now)
        on_cur = [p for _, p, r in good if r["sha"] == cur and p in flow]
        if len(on_cur) > 1:
            probs.append(f"{len(on_cur)} passes read the current version of {key} ({', '.join(on_cur)}): a "
                         f"single-pass document gets exactly one pass per version")
    used = fix_rounds_used(cfg) if new_flow else 0
    unfixable, budget = [], []
    for n, p, r in parsed:
        # identical findings in one pass are one finding
        blocking = list(dict.fromkeys(t for k, t in r["findings"] if k == "BLOCKING"))
        uniq, seen = [], set()
        for f in blocking:
            if _norm(f) not in seen:
                seen.add(_norm(f)); uniq.append(f)
        resp, bad = responses(texts, response_names(texts, key, n))
        bodies = responses.bodies
        answers = [(kind, answered_set(cands, uniq)) for kind, cands in resp]
        for i, f in enumerate(uniq):
            hit = [kind for kind, ids in answers if i in ids]
            last = max((j for j, (_k, ids) in enumerate(answers) if i in ids), default=None)
            why = reason_of(bodies[last], resp[last][1], f) if last is not None else ""
            if hit and hit[-1] == "fixed" and doc in HAND_EDIT_DOCS:
                # DOC-FIX G3: a fix by hand edit holds only while that edit is in the delivered document (a later
                # prepare regenerates it and erases the edit; the generator never re-applies one)
                live = {h["he"] for h in live_hand_edits(cfg, HAND_EDIT_DOCS[doc])}
                for he in HE_REF_RE.findall(why):
                    if he not in live:
                        probs.append(f"{p}: {f[:60]!r} is answered fixed by hand edit {he}, which is not in the "
                                     f"delivered {HAND_EDIT_DOCS[doc]} (a later prepare erased it, or it was never "
                                     f"recorded): re-apply its diff ({HE_DIR}/{he}.diff) and record it again "
                                     f"(readers.py --hand-edit), then answer the finding anew in a new response file")
            if hit and hit[-1] == "unfixable" and doc in HAND_EDIT_DOCS and p in flow \
                    and (label(f) == "presentation" or GENERATOR_BLAME_RE.search(why)):
                # DOC-FIX G4 (approver 2026-10-25): a fault of a generated document is never "unfixable: generator
                # fault". The operator rejects it with a reason, fixes the generator (a tool patch, then prepare
                # again), or hand-edits the document; `unfixable` stays for what nothing can fix (the paper itself)
                probs.append(f"{p}: {f[:60]!r} is answered unfixable, but it is a fault of the generated "
                             f"{HAND_EDIT_DOCS[doc]}: answer it `dismissed` (a reason: not a real problem, or trivial), "
                             f"fix the generator (release: the tool-patch route, then prepare again) and answer `fixed "
                             f"... — tool patch TP<k>`, or hand-edit the document (readers.py --hand-edit) and answer "
                             f"`fixed ... — hand edit HE<k>` (run/fresh-reader.md step 3)")
                continue
            if not hit:
                why = ""
                if any(any(covers(q, f) for q in cands) for _, cands in resp):
                    why = (" (a response quotes it, but its quote also matches another finding: quote "
                           "more, or quote the whole finding)")
                elif bad:
                    why = " (unparsed response lines: " + "; ".join(bad[:3]) + ")"
                probs.append(f"{p}: blocking finding not answered in {key}-{n}.response*.md: {f[:80]!r}{why}")
            elif hit[-1] == "fixed" and (r["sha"] is None or r["sha"] == cur):
                # `fixed` claims a change: the delivered version must differ from the one the
                # finding was raised on (A->B->A toggling, or a pass with no sha, does not count)
                probs.append(f"{p}: {f[:60]!r} is marked fixed, but the delivered version is the one it was "
                             f"raised on" + (" (or that pass recorded no version)" if r["sha"] is None else "")
                             + ": change the document, then run a new reader")
            elif hit[-1] == "unfixable":
                if p in flow and label(f) == "content" and used < FIX_BUDGET:
                    # ADDENDUM N4: a content finding goes to the adjudicator's reader-fix round while the run's
                    # budget lasts; only past it is it disclosed (the notice)
                    probs.append(f"{p}: the content finding {f[:60]!r} is answered unfixable, but {used} of the run's "
                                 f"{FIX_BUDGET} reader-fix rounds are used: send it to one (python3 audits/prompt.py "
                                 f"4 --round <newest round> --reader-fix), or answer it dismissed with evidence")
                    continue
                if p in flow and project.mode(cfg) != "release":
                    # U2 §6.3 (dev): a blocking finding past the fix budget is a stop, never disclosed
                    probs.append(f"{p}: dev mode: the blocking finding {f[:60]!r} is left unfixable (past the fix "
                                 f"budget): a stop for the human")
                unfixable.append(f)
                if any("fix budget" in texts[nm].lower() for nm in response_names(texts, key, n)) \
                        or (p in flow and used >= FIX_BUDGET):
                    budget.append(f)
    check.outcome = outcome_text(key, len(unfixable), len(budget))
    if unfixable and not check.outcome[0]:
        probs += log_claims(cfg, key, check.outcome[1])
    if unfixable:
        kf = os.path.join(rounds_root(cfg), f"KNOWN_FAULTS-{key}.md")
        notice = open(kf, encoding="utf-8").read() if os.path.exists(kf) else None
        if notice is None:
            probs.append(f"{len(unfixable)} finding(s) marked unfixable: write {os.path.basename(kf)}, the "
                         f"notice folded into the delivered RUN_RECORD.md, quoting each")
        else:
            for f in unfixable:
                if _norm(f)[:60] not in _norm(notice):
                    probs.append(f"{os.path.basename(kf)} does not quote the unfixable finding {f[:60]!r}")
    return probs


# --- hand edits of a generated document (DOC-FIX; approver 2026-10-25) ---------------------------------------
# When an agent (a fresh reader, the status check, a PDF agent) finds a fault in a GENERATED document, the operator
# answers it one of three ways, each recorded: (1) REJECT it with a reason (`dismissed`); (2) fix the GENERATOR
# through the tool-patch route (release), then prepare again; (3) when a generator patch would be dangerous, HAND-EDIT
# the document after the final prepare. "Code guards agents on provenance; agents guard code on meaning": a hand
# edit is a dedicated commit "hand-edit HE<k> <doc>" holding the document and its two records (hand-edits/HE<k>.json:
# the finding it answers, the prepare it follows, the hashes before and after; HE<k>.diff: the diff), and nothing
# else. --deliver accepts a prepared document that differs from what prepare recorded only when the live edits chain
# from the prepared hash to the file exactly (hand_edit_problems); the status check, a fresh agent, judges whether an
# edit changes a status, a statement, a defect verdict or a human answer away from the records (judgement_problems);
# a fresh reader reads the edited version (the gate above). A later prepare regenerates the document and so erases
# its edits: prepare names them, and a `fixed ... — hand edit HE<k>` answer then refuses the gate (G3).
HAND_EDIT_DOCS = {"summary": "SUMMARY.md", "report": "REPORT.md"}
HE_DIR = "hand-edits"
HE_ID_RE = re.compile(r"^HE([1-9]\d*)$")
HE_REF_RE = re.compile(r"\bhand[- ]edit (HE[1-9]\d*)\b", re.I)
HE_SUBJECT = "hand-edit {he} {doc}"
HE_SUBJECT_RE = re.compile(r"^hand-edit (HE[1-9]\d*) (SUMMARY\.md|REPORT\.md)$")
PREPARE_SUBJECT = "prepare delivery"
# an `unfixable` answer that blames a generator: DOC-FIX G4 (the answers are reject, tool patch or hand edit)
GENERATOR_BLAME_RE = re.compile(r"generator|make_report|generated\s+text", re.I)
# where an agent's finding on a generated document is recorded (the rounds directory): a reader's record, the
# status check's findings, a PDF agent's record
FINDING_SOURCES = ("readers/", "status-check/", "pdf/")
JUDGE_HEAD_RE = re.compile(r"(?ms)^##\s+Hand edits[ \t]*\n(.*?)(?=^##\s|\Z)")
JUDGE_LINE_RE = re.compile(r"^\s*-\s*(HE[1-9]\d*)\s*:\s*(OK|MISMATCH)\b", re.M)


def _rgit(rd, *a):
    return subprocess.run(["git", "-C", rd, *a], capture_output=True, text=True)


def newest_prepare_commit(rd):
    """The newest commit of the audit record whose subject is "prepare delivery" (project.py --prepare-delivery), or
    None. Read on the first-parent line of work."""
    r = _rgit(rd, "log", "--first-parent", "--format=%H%x00%s")
    if r.returncode:
        return None
    for l in r.stdout.splitlines():
        h, _, subj = l.partition("\x00")
        if subj.strip() == PREPARE_SUBJECT:
            return h
    return None


def all_hand_edits(rd):
    """[record dict] of every hand-edits/HE<k>.json on disk, by k (each with "he", "k", "path")."""
    out = []
    d = os.path.join(rd, HE_DIR)
    for p in glob.glob(os.path.join(d, "HE*.json")):
        m = HE_ID_RE.match(os.path.basename(p)[:-5])
        if not m:
            continue
        try:
            rec = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        if not isinstance(rec, dict):
            rec = {}
        out.append(dict(rec, he=f"HE{m.group(1)}", k=int(m.group(1)), path=p))
    return sorted(out, key=lambda r: r["k"])


def live_hand_edits_at(rd, name=None):
    """The hand edits made since the newest prepare (its commit recorded in the edit): the ones in the delivered
    documents. `name` (SUMMARY.md / REPORT.md) narrows to one document."""
    pc = newest_prepare_commit(rd)
    return [r for r in all_hand_edits(rd) if pc and r.get("prepare_commit") == pc
            and (name is None or r.get("doc") == name)]


def live_hand_edits(cfg, name=None):
    return live_hand_edits_at(rounds_root(cfg), name)


def erased_hand_edits(cfg):
    """The hand edits a later prepare erased (their prepare is not the newest)."""
    pc = newest_prepare_commit(rounds_root(cfg))
    return [r for r in all_hand_edits(rounds_root(cfg)) if r.get("prepare_commit") != pc]


def _he_commit(rd, he, name):
    r = _rgit(rd, "log", "--first-parent", "--format=%H%x00%s")
    hs = [l.split("\x00")[0] for l in r.stdout.splitlines() if l.partition("\x00")[2].strip()
          == HE_SUBJECT.format(he=he, doc=name)] if r.returncode == 0 else []
    return hs


def _changed(rd, commit):
    r = _rgit(rd, "-c", "core.quotePath=false", "diff-tree", "--no-commit-id", "--name-only", "-r", "-m",
              "--first-parent", "--relative", commit)
    return sorted(set(x for x in r.stdout.splitlines() if x)) if r.returncode == 0 else None


def doc_diff(rd, name, commit=None):
    """The unified diff of document `name` (relative to the rounds dir): in `commit`, or of the working tree
    against HEAD."""
    a = (["show", "--first-parent", "--format=", "--no-color", "--no-ext-diff", "--relative", commit, "--", name]
         if commit else ["diff", "--no-color", "--no-ext-diff", "--relative", "HEAD", "--", name])
    r = _rgit(rd, *a)
    return r.stdout if r.returncode == 0 else None


def hand_edit_problems_at(rd, name, base):
    """[problem] of document `name`'s live hand edits, given the hash prepare recorded (`base`): each edit is its
    own commit "hand-edit HE<k> <name>" touching only the document and its two records, its diff the recorded one,
    the edits chain base -> result in order to the file on disk, and nothing else changed the document since the
    prepare (provenance: no edit outside such a commit)."""
    import project as _p
    out = []
    live = live_hand_edits_at(rd, name)
    pc = newest_prepare_commit(rd)
    want = base
    seen = set()
    for r in live:
        he = r["he"]
        hs = _he_commit(rd, he, name)
        if len(hs) != 1:
            out.append(f"hand edit {he}: {len(hs)} commit(s) \"{HE_SUBJECT.format(he=he, doc=name)}\", not exactly one "
                       f"(readers.py --hand-edit commits it)")
            continue
        c = hs[0]
        seen.add(c)
        files = _changed(rd, c)
        allowed = {name, f"{HE_DIR}/{he}.json", f"{HE_DIR}/{he}.diff"}
        if files is None or set(files) != allowed:
            out.append(f"hand edit {he}: its commit {c[:11]} changes {files}, not exactly {sorted(allowed)}")
        if _rgit(rd, "merge-base", "--is-ancestor", pc or "x", c).returncode != 0 or c == pc:
            out.append(f"hand edit {he}: its commit {c[:11]} does not follow the newest prepare")
        if r.get("base_sha256") != want:
            out.append(f"hand edit {he}: it was made on {str(r.get('base_sha256'))[:12]}…, but the document before it "
                       f"was {str(want)[:12]}…")
        try:
            diff_rec = open(os.path.join(rd, HE_DIR, f"{he}.diff"), encoding="utf-8").read()
        except OSError:
            diff_rec = None
        if diff_rec is None or doc_diff(rd, name, c) != diff_rec:
            out.append(f"hand edit {he}: {HE_DIR}/{he}.diff is not the diff its commit {c[:11]} made to {name}")
        for f_ in (f"{HE_DIR}/{he}.json", f"{HE_DIR}/{he}.diff"):
            st = _rgit(rd, "diff", "--quiet", c, "--", f_)
            st2 = _rgit(rd, "status", "--porcelain", "--", f_)
            if st.returncode != 0 or st2.stdout.strip():
                out.append(f"hand edit {he}: {f_} changed after its commit {c[:11]}")
        shown = _rgit(rd, "show", f"{c}:./{name}")
        got = _p.doc_text_hash(name, shown.stdout) if shown.returncode == 0 else None
        if got != r.get("result_sha256"):
            out.append(f"hand edit {he}: {name} at its commit hashes to {str(got)[:12]}…, not the recorded "
                       f"{str(r.get('result_sha256'))[:12]}…")
        want = r.get("result_sha256")
    disk = _p.file_hash(name, os.path.join(rd, name))
    if disk != want:
        out.append(f"{name} on disk ({str(disk)[:12]}…) is not the document its last hand edit made "
                   f"({str(want)[:12]}…): a change outside a recorded hand edit (restore it: git checkout -- {name})")
    if pc:
        lg = _rgit(rd, "log", "--first-parent", "--format=%H%x00%s", f"{pc}..HEAD", "--", name)
        for l in lg.stdout.splitlines() if lg.returncode == 0 else []:
            h, _, subj = l.partition("\x00")
            if h not in seen:
                out.append(f"{name} was changed after the prepare by commit {h[:11]} \"{subj.strip()}\", which is no "
                           f"recorded hand edit: restore it, or prepare again")
    return out


def hand_edit_problems(cfg, name):
    import project as _p
    man = _p.manifest(cfg) or {}
    return hand_edit_problems_at(rounds_root(cfg), name, (man.get("hashes") or {}).get(name))


def judgement_problems(cfg):
    """[problem] (DOC-FIX G5): with live hand edits, the status check -- a fresh agent, the judge of meaning -- must
    have read them: status-check/FINDINGS.md committed after the newest hand edit, its "## Hand edits" section saying
    `- HE<k>: OK` for each (an edit that changes no status, statement, defect verdict or human answer, or changes one
    only to what the records say). The file must be the issued agent's (DOC-FIX review #3, provenance): the last
    status-check run was issued for exactly the live edits and its FINDINGS.md is sealed (run_record.py
    --seal-status-check: the run's token, the agent's own digest) and unchanged since, so a verdict line typed by
    the operator is refused. MISMATCH refuses: undo the edit by preparing again (it erases every hand edit; re-apply
    those judged OK as new hand edits). Never a stop."""
    rd = rounds_root(cfg)
    live = live_hand_edits_at(rd)
    if not live:
        return []
    fp = os.path.join(rd, "status-check", "FINDINGS.md")
    rel = os.path.relpath(fp, rd)
    newest = max((c for r in live for c in _he_commit(rd, r["he"], r.get("doc", ""))), default=None,
                 key=lambda c: int(_rgit(rd, "rev-list", "--count", c).stdout.strip() or 0))
    lg = _rgit(rd, "log", "-1", "--first-parent", "--format=%H", "--", rel)
    fc = lg.stdout.strip() if lg.returncode == 0 else ""
    dirty = _rgit(rd, "status", "--porcelain", "--", rel).stdout.strip()
    ids = ", ".join(r["he"] for r in live)
    rerun = ("run the status check again (python3 audits/prompt.py --prompt status-check --write, a fresh agent: it "
             "judges each hand edit), commit status-check/ by name, then deliver again: never a stop")
    if not fc or dirty or not newest or fc == newest \
            or _rgit(rd, "merge-base", "--is-ancestor", newest, fc).returncode != 0:
        return [f"the hand edit(s) {ids} were not judged by the status check (status-check/FINDINGS.md, committed after "
                f"the newest hand edit): {rerun}"]
    import run_record
    runs, ids_l = run_record.status_runs(cfg), [r["he"] for r in live]
    if not runs or list(runs[-1].get("hand_edits") or []) != ids_l:
        return [f"the last status-check run ({(runs[-1].get('prompt') if runs else None) or 'none'}) was not issued "
                f"for the live hand edit(s) {ids}: {rerun}"]
    failed = run_record.status_run_failure(cfg, ids_l, runs)
    if failed:
        return [f"the status check's last run gave no sealed verdict on the hand edit(s) {ids} ({failed}): if its agent "
                f"returned its {run_record.STATUS_COMPLETION} line, seal it (python3 audits/run_record.py "
                f"--seal-status-check --sha256 <hex> --agent-id <id>; {run_record.RETURNED_SAVE} first); otherwise "
                f"the run failed, a mechanical failure "
                f"and never a judgement: {rerun}"]
    text = open(fp, encoding="utf-8").read()
    m = JUDGE_HEAD_RE.search(text)
    said = {}
    for he, v in JUDGE_LINE_RE.findall(m.group(1) if m else ""):
        said.setdefault(he, set()).add(v)
    out = []
    for r in live:
        v = said.get(r["he"], set())
        if "MISMATCH" in v:
            out.append(f"the status check judged hand edit {r['he']} of {r.get('doc')} a MISMATCH (it changes a status, a "
                       f"statement, a defect verdict or a human answer away from the records): undo it by preparing again "
                       f"(python3 audits/project.py --prepare-delivery: it erases every hand edit), re-apply each edit "
                       f"judged OK as a new hand edit (patch -p1 -d <rounds dir> < <rounds dir>/{HE_DIR}/HE<k>.diff, then "
                       f"readers.py --hand-edit) and answer its findings anew, then read and check again: never a stop "
                       f"(a hand edit restoring the text does not undo it: the check judges each edit's own diff)")
        elif "OK" not in v:
            out.append(f"status-check/FINDINGS.md has no `- {r['he']}: OK` line under \"## Hand edits\": {rerun}")
    return out


def trust_problems(cfg):
    """[problem] (approver 2026-10-26, "make sure the agent guards those lines"): every plain trust line code wrote
    on SUMMARY page 1 and in REPORT (make_report.trust_line_events: a check that could not run, ...) was judged by
    the status check, a fresh agent: its last run was issued for exactly these events, its FINDINGS.md is sealed
    (the run's token, the agent's digest), says `- <TL-id>: OK` for each and has no `- extra: MISMATCH`. A MISMATCH
    (the line missing, untrue, incomplete, or a line with no event) goes back through the route of a fault in a
    generated document: the generator is fixed (a tool patch) or the document hand-edited, then the check judges
    again (a verdict of the agent's is not "rejected" by the operator). Never a stop."""
    import make_report, run_record
    events = make_report.trust_line_events(cfg)
    ids = [e.id for e in events]
    root = rounds_root(cfg)
    fix = ("fix it through the generator (stops.py open --cause tool-bug, the tool-patch route, then prepare again) or "
           "a hand edit (readers.py --hand-edit), then the status check judges again: never a stop")
    # review 3 (code flags, fail-safe): every plain trust sentence the documents carry stands for an event a provider
    # gives; one that does not means a provider is missing -- nothing would guard it
    lines = {e.line for e in events}
    out = []
    for doc in ("SUMMARY.md", "REPORT.md"):
        try:
            txt = open(os.path.join(root, doc), encoding="utf-8").read()
        except OSError:
            continue
        out += [f"{doc} carries the trust sentence \"{t}\" but no event of the record stands for it (a provider of "
                f"make_report.TRUST_LINE_PROVIDERS is missing: a fault of the generator, the tool-patch route)"
                for t in make_report.trust_sentences(txt) if t not in lines]
    runs = run_record.status_runs(cfg)
    if not ids:
        # an `extra` line the agent wrote is read even with no event (it has no token then: its file as it stands)
        # re-check R1: only from a run that judged the current SUMMARY.md (a fixed summary drops a stale line; the code
        # flag above still guards its text)
        try:
            said0 = run_record.item_verdicts(open(os.path.join(root, "status-check", "FINDINGS.md"),
                                                  encoding="utf-8").read()) if runs else {}
        except OSError:
            said0 = {}
        if said0.get("extra") == "MISMATCH" and runs[-1].get("summary_sha256") != run_record.summary_sha(cfg):
            # re-check of 0adf59c: a stale extra MISMATCH is not dropped silently: the fixed summary is judged again
            # (begin_status_run allows that run past the cap)
            out.append("the status check's `extra: MISMATCH` was judged on an earlier SUMMARY.md: run the status check "
                       "again (python3 audits/prompt.py --prompt status-check --write, a fresh agent), then deliver "
                       "again: never a stop")
        elif said0.get("extra") == "MISMATCH":
            out.append(f"the status check found a trust line on SUMMARY or REPORT with no event in the record (`- extra: "
                       f"MISMATCH`): {fix}")
        return out
    rerun = ("run the status check again (python3 audits/prompt.py --prompt status-check --write, a fresh agent: it "
             "judges each trust line), seal it, then deliver again: never a stop")
    if not runs or list(runs[-1].get("trust_lines") or []) != ids:
        return out + [f"the trust line(s) {', '.join(ids)} were not judged by the status check: {rerun}"]
    if runs[-1].get("summary_sha256") != run_record.summary_sha(cfg):
        # review 3: a verdict on a trust line is bound to the SUMMARY.md it judged
        return out + [f"the trust line(s) {', '.join(ids)} were judged on an earlier SUMMARY.md: {rerun}"]
    failed = run_record.status_run_failure(cfg, ids, runs)
    if failed:
        return out + [f"the status check's last run gave no sealed verdict on the trust line(s) {', '.join(ids)} ({failed}): "
                f"if its agent returned its {run_record.STATUS_COMPLETION} line, seal it (python3 audits/run_record.py "
                f"--seal-status-check --sha256 <hex> --agent-id <id>; {run_record.RETURNED_SAVE} first); otherwise "
                f"{rerun}"]
    said = run_record.item_verdicts(open(os.path.join(root, "status-check", "FINDINGS.md"),
                                         encoding="utf-8").read())
    out += [f"the status check judged trust line {i} a MISMATCH (status-check/FINDINGS.md, \"## Trust lines\"): {fix}"
           for i in ids if said.get(i) == "MISMATCH"]
    out += [f"status-check/FINDINGS.md has no `- {i}: OK` line under \"## Trust lines\": {rerun}" for i in ids
            if i not in said]
    if said.get("extra") == "MISMATCH":
        out.append(f"the status check found a trust line on SUMMARY or REPORT with no event in the record (`- extra: "
                   f"MISMATCH`): {fix}")
    return out


def hand_edit_summary(cfg):
    """[line] for HAND-EDITS in the status check's prompt: each live edit and its diff file, or "none"."""
    live = live_hand_edits(cfg)
    if not live:
        return "none"
    return "; ".join(f"{r['he']} ({r.get('doc')}): {cfg['rounds_dir']}/{HE_DIR}/{r['he']}.diff" for r in live)


def finding_problems(rd, finding):
    """[problem] with a --finding "<file under the rounds dir>: <quote>": the file is an agent's committed record
    (readers/, status-check/, pdf/) and the quote, at least 15 characters, stands in it as committed."""
    path, sep, quote = (finding or "").partition(": ")
    path, quote = path.strip(), quote.strip()
    if not sep or not path.startswith(FINDING_SOURCES) or ".." in path.split("/"):
        return [f"--finding must be \"<record>: <quote>\", the record a file under {', '.join(FINDING_SOURCES)} of the "
                f"rounds directory (a reader's record, status-check/FINDINGS.md, a PDF agent's record)"]
    if len(_norm(quote)) < 15:
        return ["--finding: quote at least 15 characters of the finding, as the agent wrote it"]
    shown = _rgit(rd, "show", f"HEAD:./{path}")
    dirty = _rgit(rd, "status", "--porcelain", "--", path).stdout.strip()
    if shown.returncode or dirty:
        return [f"--finding: {path} is not committed as it stands (the agent's record must be on record first)"]
    if _norm(quote) not in _norm(re.sub(r"\s+", " ", shown.stdout)):
        return [f"--finding: the quote does not stand in {path} as committed"]
    return []


def record_hand_edit(cfg, doc, finding):
    """readers.py --hand-edit: record and commit the operator's edit of a generated document, made in the working
    tree after the final prepare. Returns (HE id, [problem]); nothing is written when there is a problem."""
    import project as _p
    if doc not in HAND_EDIT_DOCS:
        return None, [f"--hand-edit: --doc must be {' or '.join(HAND_EDIT_DOCS)} (the sheet and README A-C: reject the "
                      f"finding, or fix their generator)"]
    name = HAND_EDIT_DOCS[doc]
    rd = rounds_root(cfg)
    pc = newest_prepare_commit(rd)
    man = _p.manifest(cfg) or {}
    if not pc or name not in (man.get("hashes") or {}):
        return None, ["--hand-edit: no prepare is recorded: a hand edit comes after the final prepare (python3 audits/"
                      "project.py --prepare-delivery)"]
    probs = finding_problems(rd, finding)
    live = live_hand_edits_at(rd, name)
    tip = live[-1].get("result_sha256") if live else man["hashes"][name]
    head = _rgit(rd, "show", f"HEAD:./{name}")
    if head.returncode or _p.doc_text_hash(name, head.stdout) != tip:
        probs.append(f"--hand-edit: the committed {name} is not the prepared one or its last hand edit: restore it "
                     f"(git checkout -- {name}) or prepare again")
    disk = _p.file_hash(name, os.path.join(rd, name))
    if disk == tip:
        probs.append(f"--hand-edit: {name} is unchanged: make the edit in the file first")
    prior = probs[:]
    if not prior:
        bad = hand_edit_problems_at(rd, name, man["hashes"][name])
        probs += [p_ for p_ in bad if "on disk" not in p_]
    if probs:
        return None, probs
    k = max([r["k"] for r in all_hand_edits(rd)] + [0]) + 1
    lg = _rgit(rd, "log", "--format=%s")
    for l in lg.stdout.splitlines() if lg.returncode == 0 else []:
        m = HE_SUBJECT_RE.match(l.strip())
        if m:
            k = max(k, int(m.group(1)[2:]) + 1)
    he = f"HE{k}"
    diff = doc_diff(rd, name)
    os.makedirs(os.path.join(rd, HE_DIR), exist_ok=True)
    jp, dp = os.path.join(rd, HE_DIR, f"{he}.json"), os.path.join(rd, HE_DIR, f"{he}.diff")
    open(dp, "w", encoding="utf-8", newline="").write(diff or "")
    import datetime
    json.dump({"doc": name, "finding": " ".join(finding.split()), "prepare_commit": pc, "base_sha256": tip,
               "result_sha256": disk, "diff_sha256": hashlib.sha256((diff or "").encode("utf-8")).hexdigest(),
               "date": datetime.date.today().isoformat()},
              open(jp, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        _p.commit_only([os.path.join(rd, name), jp, dp], HE_SUBJECT.format(he=he, doc=name), repo=project.AUDITS)
    except (ValueError, OSError) as e:
        return he, [f"written but not committed: {e}"]
    after = hand_edit_problems_at(rd, name, man["hashes"][name])
    return he, after


def save(cfg, doc, round_name, text, commit=True):
    """Write and commit a reader record given as text. Returns (path, problems); nothing is
    written if problems is non-empty."""
    key, srcs, _ = resolve(cfg, doc, round_name)
    if not text.endswith("\n"):
        text += "\n"
    rec = parse("(stdin)", text)
    probs = list(rec["problems"])
    want = content_hash(srcs, doc)
    if rec["sha"] and rec["sha"] != want:
        probs.append(f"the record read version {rec['sha'][:12]}…, but the document now hashes to "
                     f"{want[:12]}…: the reader read another version (re-run it on this one)")
    if probs:
        return None, probs
    rdir = readers_dir(cfg)
    os.makedirs(rdir, exist_ok=True)
    n = next_number(cfg, key)
    path = os.path.join(rdir, f"{key}-{n}.md")
    if os.path.exists(path):
        return None, [f"{path} already exists"]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    if commit:
        rel = os.path.relpath(path, project.AUDITS)
        r1 = subprocess.run(["git", "-C", project.AUDITS, "add", "--", rel], capture_output=True, text=True)
        r2 = subprocess.run(["git", "-C", project.AUDITS, "commit", "-q", "-m", f"reader {key} {n}",
                             "--", rel], capture_output=True, text=True)
        if r1.returncode or r2.returncode:
            return path, [f"written but not committed: {(r1.stderr + r2.stderr).strip()}"]
        shown = subprocess.run(["git", "-C", project.AUDITS, "show", f"HEAD:{rel}"],
                               capture_output=True)
        if shown.returncode or shown.stdout != text.encode("utf-8"):
            return path, ["the committed record differs from the text given on stdin"]
    return path, []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", help="signoff | questions | report | decisions | summary | other:<absolute path>")
    ap.add_argument("--round", help="with --doc signoff/questions: the sheet's round "
                    "(`approved` = the round of the approval record)")
    ap.add_argument("--project")
    ap.add_argument("--hash", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--save", action="store_true", help="read a reader record on stdin, save and commit it")
    ap.add_argument("--hand-edit", action="store_true",
                    help="with --doc summary|report and --finding: record and commit your edit of the generated "
                         "document (made after the final prepare) as hand-edit HE<k> (DOC-FIX)")
    ap.add_argument("--finding", help="with --hand-edit: \"<record under the rounds dir>: <quote of the finding>\"")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.doc or (a.hash + a.check + a.next + a.save + a.hand_edit) != 1:
        ap.error("give --doc and exactly one of --hash / --next / --check / --save / --hand-edit")
    if a.hand_edit and not a.finding:
        ap.error("--hand-edit needs --finding \"<record>: <quote>\"")
    try:
        cfg, _ = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    try:
        key, srcs, _ = resolve(cfg, a.doc, a.round)
    except DocError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    if a.hash:
        print(content_hash(srcs, a.doc))
        return 0
    if a.next:
        print(os.path.join(readers_dir(cfg), f"{key}-{next_number(cfg, key)}.md"))
        return 0
    if a.hand_edit:
        he, probs = record_hand_edit(cfg, a.doc, a.finding)
        for p in probs:
            print(project.problem_line(p, "reader-check"))
        if he is None or probs:
            print("hand edit NOT recorded" if he is None else f"hand edit {he} written, see above")
            return 1
        print(f"recorded and committed hand edit {he} of {HAND_EDIT_DOCS[a.doc]} ({HE_DIR}/{he}.json, {he}.diff). "
              f"Now: answer the finding `- fixed: <quote> — hand edit {he}` in a new response file; one fresh-reader "
              f"pass on the edited version; the status check again (it judges the edit); render the PDF again")
        return 0
    if a.save:
        path, probs = save(cfg, a.doc, a.round, sys.stdin.read())
        for p in probs:
            print(project.problem_line(p, "reader-check"))
        if probs:
            print("record NOT saved" if path is None else f"record written to {path}, see above")
            return 1
        print(f"saved and committed {path}")
        return 0
    probs, disc = project.split(cfg, check(cfg, a.doc, a.round))
    for p in probs:
        print(project.problem_line(p, "reader-check"))
    for p in disc:
        print(project.disclosed_line(p))
    for nt in history_notes(readers_dir(cfg), key):
        # harmless to the gate (records are read as first committed), but the human is told
        print(f"NOTE     reader record changed after its commit (shown to the human): {nt}")
    oc = getattr(check, "outcome", None)
    print(f"fresh-reader gate for {key}: {'OK' if not probs else 'REFUSED'}"
          + (f" -- {oc[1]}" if oc and not probs else "")
          + (f" ({len(disc)} disclosed, release mode: record them with stops.py disclose)" if disc else ""))
    return 1 if probs else 0


def selftest():
    res = []
    def say(name, ok):
        res.append(ok); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    d = tempfile.mkdtemp(prefix="readers-")
    saved = (project.REPO, project.AUDITS)
    try:
        project.REPO = project.AUDITS = d
        cfg = {"rounds_dir": "rr"}
        root = os.path.join(d, "rr"); rdir = os.path.join(root, "readers"); os.makedirs(rdir)
        RN = "2026-01-01-abc1234"
        os.makedirs(os.path.join(root, RN))
        open(os.path.join(root, RN, "TARGET.json"), "w").write("{}")   # a round (project.is_round)
        doc = os.path.join(root, "DECISIONS.md")
        def put(text, tag=RN):
            open(doc, "w").write((f"<!-- decisions-round: {tag} -->\n" if tag else "") + text)
            return content_hash([doc], "decisions")
        key = "decisions-" + RN
        def reader(n, sha, verdict, findings=(), cov=True):
            open(os.path.join(rdir, f"{key}-{n}.md"), "w").write(
                f"sha256: {sha}\n" + ("coverage: 40 of 40 references; COULD NOT CHECK: none\n" if cov else "")
                + "".join(f + "\n" for f in findings) + verdict + "\n")
        def respond(n, *lines):
            open(os.path.join(rdir, f"{key}-{n}.response.md"), "w").write("".join(l + "\n" for l in lines))
        C = lambda: check(cfg, "decisions", check_git=False)
        F1 = "- BLOCKING: the count of CHECK rows says 15 but the sheet has 16"
        F2 = "- BLOCKING: tex l.447 is quoted with the wrong bound on m"
        h1 = put("v1\n")
        say("no pass: refused", any("no fresh-reader" in p for p in C()))
        say("release mode: the gate's own findings are disclosed (reader); dev keeps them blocking",
            bool(C()) and project.split({"mode": "release"}, C()) == ([], C()) and C()[0].code == "reader"
            and project.split({"mode": "dev"}, C()) == (C(), []))
        reader(1, h1, "VERDICT: NO BLOCKING PROBLEMS", findings=("- NOT BLOCKING: style",))
        say("a clean pass on the delivered version: accepted", C() == [])
        put("v2\n")
        say("the document changed after its last pass: refused", any("changed after" in p for p in C()))
        h2 = put("v2\n")
        reader(2, h2, "VERDICT: BLOCKING PROBLEMS: 1", findings=(F1,))
        say("an unanswered blocking finding: refused", any("not answered" in p for p in C()))
        say("review H2: an unanswered BLOCKING finding blocks in release too",
            any("not answered" in p for p in project.split({"mode": "release"}, C())[0]))
        say("review H2: on the sign-off sheet (the pre-approval faithfulness check) even a missing or stale pass "
            "blocks in release; on another document it is disclosed",
            project.split({"mode": "release"}, [stale_finding("signoff-2026-01-01-abc1234", "x")])[0] == ["x"]
            and project.split({"mode": "release"}, [stale_finding("report-R", "x")])[1] == ["x"])
        respond(2, "- fixed: the count of CHECK rows says 15 — now says 16, matching SIGNOFF.json")
        say("'fixed' on the newest pass is not enough: a new pass must read the fix",
            any("marked fixed" in p for p in C()))
        h3 = put("v3 with 16\n")
        reader(3, h3, "VERDICT: NO BLOCKING PROBLEMS")
        say("fixed, then a clean pass on the fixed version: accepted", C() == [])
        os.remove(os.path.join(rdir, f"{key}-2.response.md"))
        say("a re-roll cannot wash away an earlier finding (pass 2's finding still needs an answer)",
            any("not answered" in p for p in C()))
        respond(2, "- fixed: the count of CHECK rows says 15 — now 16")
        hx = put("v3 with 16\n")
        reader(4, hx, "VERDICT: BLOCKING PROBLEMS: 1", findings=(F2,))
        respond(4, "- fixed: tex l.447 is quoted with the wrong bound — reworded")
        reader(5, hx, "VERDICT: NO BLOCKING PROBLEMS")
        say("'fixed' with no change to the document, then a clean re-roll: refused",
            any("the one it was raised on" in p for p in C()))
        for n in (4, 5):
            os.remove(os.path.join(rdir, f"{key}-{n}.md"))
        os.remove(os.path.join(rdir, f"{key}-4.response.md"))
        put("v3 with 16\n", tag="R-other")
        say("a DECISIONS.md whose round tag was edited: refused (the key is computed, not read)",
            any("tagged for round" in p for p in C()))
        put("v3 with 16\n", tag=None)
        say("...and one with the tag deleted: refused", any("tagged for round" in p for p in C()))
        h4 = put("v4\n")
        reader(4, h4, "VERDICT: BLOCKING PROBLEMS: 3", findings=(F2,))
        reader(5, h4, "VERDICT: NO BLOCKING PROBLEMS")
        say("a malformed report's blocking finding must still be answered",
            any("-4.md: blocking finding not answered" in p for p in C()))
        respond(4, "- dismissed: tex l.447 is quoted with the wrong bound — l.447 reads exactly as quoted (checked)")
        say("after answering it, a new pass on the same version is accepted", C() == [])
        reader(6, h4, "**VERDICT: NO BLOCKING PROBLEMS**")
        say("a malformed NEWEST report: refused (spawn a new reader)", any("is malformed" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-6.md"))
        reader(6, h4, "VERDICT: NO BLOCKING PROBLEMS", cov=False)
        say("a report without a coverage line does not count", any("is malformed" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-6.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: G3 is never defined in the document",))
        respond(6, "- dismissed: something unrelated entirely — ok")
        say("a dismissal that does not quote the finding: refused", any("not answered" in p for p in C()))
        respond(6, "- dismissed: G3 is never defined in the document — the glossary defines G3 at line 40")
        say("a dismissal quoting the finding, with evidence: accepted on the unchanged document", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        respond(6, "- dismissed: G3 is never defined in the document -- the glossary defines G3")
        say("a response line without the spaced em dash is reported as unparsed",
            any("unparsed response lines" in p for p in C()))
        open(os.path.join(rdir, f"{key}-6.response-2.md"), "w").write(
            "- dismissed: G3 is never defined in the document — the glossary defines G3 at line 40\n")
        say("a correction in a new response file answers it (records stay append-only)", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.response-2.md"))
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: typo p.3", "- BLOCKING:\n  the text is on the next line, indented"))
        respond(6, "- dismissed: typo p.3 — p.3 has no typo",
                "- dismissed: the text is on the next line — checked")
        say("a short finding, and one continued on an indented line, can be answered", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: G3 is not defined in the document", "- BLOCKING: G3 is not defined in the document, and G4 neither"))
        respond(6, "- dismissed: G3 is not defined in the document — glossary")
        say("a quote from the middle of a finding does not answer it",
            not covers("defined in the document", "G3 is not defined in the document"))
        say("a finding that is a prefix of another is answered by quoting it whole; the longer one is not",
            sum("not answered" in p for p in C()) == 1 and any("and G4 neither" in p and "quote more" in p for p in C()))
        respond(6, "- dismissed: G3 is not defined in the document — glossary",
                "- dismissed: G3 is not defined in the document, and G4 neither — glossary has both")
        say("...and both can be answered", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: G3 is not defined here at all", "- BLOCKING: G3 is not defined here, nor G4"))
        respond(6, "- dismissed: G3 is not defined here — glossary")
        say("one quote matching two findings (equal to neither) answers neither", sum("quote more" in p for p in C()) == 2)
        respond(6, "- dismissed: G3 — glossary", "- dismissed: G3 is not defined here at all — glossary",
                "- dismissed: G3 is not defined here, nor G4 — glossary")
        say("a short prefix of a long finding answers nothing (G3 alone)",
            not covers("G3", "G3 is not defined here at all") and C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: Decision 3 — recommends option B on a false premise",
                         "- BLOCKING: Decision 3 — recommends option B on a false premise"))
        respond(6, "- dismissed: Decision 3 — recommends option B — the premise is true (RUN_LOG l.40)")
        say("a finding containing ' — ' can be answered, and identical findings are one", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: Decision 3 — recommends option B on a false premise",
                         "- BLOCKING: decision 3 —  recommends option B on a false premise"))
        say("findings differing only in case or spacing are one", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: short\n  continued here, more text",))
        respond(6, "- dismissed: short continued here — checked")
        say("a quote may reach into the finding's indented continuation", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: Decision 3 — recommends option B on a false premise",
                         "- BLOCKING: Decision 3 — recommends option B on a false premise"))
        respond(6, "- dismissed: Decision 3 — recommends option B — the premise is true (RUN_LOG l.40)")
        os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        respond(6, "- dismissed: Decision 3 — recommends option B — the premise is true",
                "- fixed: Decision 3 — recommends option B — reworded")
        say("the last answer to a finding counts (here `fixed` on the unchanged version: refused)",
            any("the one it was raised on" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        respond(6, "- fixed: Decision 3 — recommends option B — reworded")
        open(os.path.join(rdir, f"{key}-6.response-2.md"), "w").write(
            "- dismissed: Decision 3 — recommends option B — wrongly marked fixed; the premise is true\n")
        say("a later correction file overrides the first response file", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.response-2.md"))
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING:\n\nthe text after a blank line",))
        respond(6, "- dismissed: the text after a blank line — checked")
        say("a marker followed by a blank line takes the next lines as its text", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- BLOCKING: typo p.3", "- BLOCKING: typo p.3 — also on p.4"))
        respond(6, "- dismissed: typo p.3 — no typo there", "- dismissed: typo p.3 — also on p.4 — p.4 is fine")
        say("a finding equal to the start of another (up to ' — ') does not capture the other's answer", C() == [])
        os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        respond(6, "- dismissed: typo p.3 — also on p.4 — p.4 is fine")
        say("...and the longer finding's answer does not answer the shorter one",
            any("'typo p.3'" in p for p in C()) and not any("also on p.4" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        open(os.path.join(rdir, f"{key}-6.md"), "w").write(
            f"preamble line\nsha256: {hx}\ncoverage: x\n- BLOCKING: the honest finding here\nVERDICT: BLOCKING PROBLEMS: 1\n")
        open(os.path.join(rdir, f"{key}-7.md"), "w").write(f"sha256: {h4}\ncoverage: x\nVERDICT: NO BLOCKING PROBLEMS\n")
        respond(6, "- fixed: the honest finding here — changed the document")
        say("a malformed pass that names its version elsewhere can be answered `fixed` honestly", C() == [])
        say("a malformed pass's version is its FIRST sha256 line",
            parse("x", f"preamble\nsha256: {'a' * 64}\nsha256: {'b' * 64}\n")["sha"] == "a" * 64)
        for f_ in (f"{key}-6.md", f"{key}-7.md", f"{key}-6.response.md"):
            os.remove(os.path.join(rdir, f_))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: G3 is never defined in the document",))
        respond(6, "- dismissed: G3 is never defined in the document — the glossary defines G3 at line 40")
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        open(os.path.join(rdir, f"{key}-6.md"), "w").write(
            "no sha line\ncoverage: x\n- **BLOCKING:** the per-decision verdict for Decision 3 hides option C\n"
            "Non-blocking: style nit here\nVERDICT: BLOCKING PROBLEMS: 1\n")
        open(os.path.join(rdir, f"{key}-7.md"), "w").write(f"sha256: {h4}\ncoverage: x\nVERDICT: NO BLOCKING PROBLEMS\n")
        msgs = C()
        say("in a malformed file a finding mentioning 'verdict' is still a finding; 'Non-blocking' is not",
            any("hides option C" in p for p in msgs) and not any("style nit" in p for p in msgs))
        respond(6, "- fixed: the per-decision verdict for Decision 3 — reworded")
        say("`fixed` on a pass that recorded no version: refused", any("recorded no version" in p for p in C()))
        for f_ in (f"{key}-6.md", f"{key}-7.md", f"{key}-6.response.md"):
            os.remove(os.path.join(rdir, f_))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: toggled back and forth",))
        respond(6, "- fixed: toggled back and forth — changed")
        hb = put("v4 changed\n"); reader(7, hb, "VERDICT: NO BLOCKING PROBLEMS")
        put("v4\n"); reader(8, h4, "VERDICT: NO BLOCKING PROBLEMS")
        say("`fixed` after toggling A->B->A (delivered = the version it was raised on): refused",
            any("the one it was raised on" in p for p in C()))
        for f_ in (f"{key}-6.md", f"{key}-7.md", f"{key}-8.md", f"{key}-6.response.md"):
            os.remove(os.path.join(rdir, f_))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: G3 is never defined in the document",))
        respond(6, "- dismissed: G3 is never defined in the document — the glossary defines G3 at line 40")
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 2",
               findings=("- **BLOCKING:** the box omits Lemma 4.25", "1. BLOCKING: the count is wrong"))
        reader(7, h4, "VERDICT: NO BLOCKING PROBLEMS")
        say("a malformed pass's wrongly marked findings must still be answered",
            sum("-6.md: blocking finding not answered" in p for p in C()) == 2)
        respond(6, "- dismissed: the box omits Lemma 4.25 — it is listed", "- dismissed: the count is wrong — it is 3")
        say("...and answering them clears it", C() == [])
        os.remove(os.path.join(rdir, f"{key}-7.md"))
        os.remove(os.path.join(rdir, f"{key}-6.md")); os.remove(os.path.join(rdir, f"{key}-6.response.md"))
        reader(6, h4, "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: G3 is never defined in the document",))
        respond(6, "- dismissed: G3 is never defined in the document — the glossary defines G3 at line 40")
        reader(7, h4, "VERDICT: BLOCKING PROBLEMS: 1",
               findings=("- BLOCKING: the report has no page-1 box listing paper defects",))
        respond(7, "- unfixable: the report has no page-1 box listing paper defects — generator gap, closed by H4")
        say("an unfixable finding without the notice: refused", any("write KNOWN_FAULTS" in p for p in C()))
        open(os.path.join(root, f"KNOWN_FAULTS-{key}.md"), "w").write("- other text\n")
        say("a notice that does not quote it: refused", any("does not quote" in p for p in C()))
        open(os.path.join(root, f"KNOWN_FAULTS-{key}.md"), "w").write(
            "- the report has no page-1 box listing paper defects (closed by H4)\n")
        say("an unfixable finding quoted in the notice: accepted at any pass count", C() == [])
        open(os.path.join(root, f"KNOWN_FAULTS-{key}.md"), "w").write(
            "- the report has no page-1 box\n    listing paper defects (closed by H4)\n")
        say("a notice copying the finding across a line break still quotes it", C() == [])
        oc1 = check.outcome
        open(os.path.join(rdir, f"{key}-7.response-2.md"), "w").write(
            "- unfixable: the report has no page-1 box listing paper defects — fix budget reached\n")
        C()
        oc2 = check.outcome
        open(os.path.join(root, "RUN_LOG.md"), "w").write(
            "# Run log\n## Fresh readers\n- the fresh-reader gate for the decisions passed after 3 passes\n")
        lc1 = C()
        open(os.path.join(root, "RUN_LOG.md"), "w").write(
            "# Run log\n## Fresh readers\n- decisions: 3 reader passes; NOT passed: 1 finding unfixable at the fix budget\n")
        lc2 = C()
        os.remove(os.path.join(root, "RUN_LOG.md"))
        os.remove(os.path.join(rdir, f"{key}-7.response-2.md"))
        say("mini4 audit: a gate that ends with a blocking finding answered unfixable says NOT passed (and the fix "
            "budget); a run-log line saying it passed is refused until it says what happened",
            oc1 and not oc1[0] and "NOT passed" in oc1[1] and "1 blocking finding(s) answered unfixable" in oc1[1]
            and "fix budget" not in oc1[1] and oc2 and "(1 at the fix budget)" in oc2[1]
            and any("RUN_LOG.md says the fresh-reader check" in p and "say what happened" in p for p in lc1)
            and lc2 == [] and outcome_text("k", 0, 0)[0])
        # conf1 (C1 audit): the README D line of the delivered summary, from the real gate's numbers
        oc_c1 = outcome_text("summary-2026-10-25-full-ecc11cecdd0", 8, 8)
        say("conf1: an unfixable finding is said to be quoted in RUN_RECORD.md, where the delivery folds its notice in, "
            "never \"delivered with the document\" (no KNOWN_FAULTS file is delivered)",
            not oc_c1[0] and oc_c1[1] == "NOT passed: it ended with 8 blocking finding(s) answered unfixable (8 at the fix "
            "budget), quoted in RUN_RECORD.md (from the notice KNOWN_FAULTS-summary-2026-10-25-full-ecc11cecdd0.md, "
            "folded in there; it is not delivered as a file)")
        open(os.path.join(root, f"KNOWN_FAULTS-{key}.md"), "w").write("- the report has no page-1\n")
        say("a notice quoting only the start of an unfixable finding is refused", any("does not quote" in p for p in C()))
        open(os.path.join(root, f"KNOWN_FAULTS-{key}.md"), "w").write(
            "- the report has no page-1 box\n    listing paper defects (closed by H4)\n")
        reader(8, h4, "VERDICT: BLOCKING PROBLEMS: 2", findings=(F1,))
        say("a verdict count above the listed findings is malformed (its finding still needs an answer)",
            any("-8.md: blocking finding not answered" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-8.md"))
        reader(8, h4, "VERDICT: BLOCKING PROBLEMS: 2", findings=("- BLOCKING: G3 is never defined in the document",))
        respond(8, "- dismissed: G3 is never defined in the document — the glossary defines it")
        say("a verdict counting more findings than it lists is malformed even if the listed one is answered",
            any("is malformed" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-8.md")); os.remove(os.path.join(rdir, f"{key}-8.response.md"))
        reader(8, h4, "VERDICT: BLOCKING PROBLEMS: 0")
        say("'BLOCKING PROBLEMS: 0' is malformed", any("is malformed" in p for p in C()))
        os.remove(os.path.join(rdir, f"{key}-8.md"))
        a = _w(d, "a/REPORT.md", "# R\n**Generated 2026-10-13 by `audits/make_report.py`. Do not edit this file.**\nbody\n")
        b = _w(d, "b/REPORT.md", "# R\n**Generated 2026-11-02 by `audits/make_report.py`. Do not edit this file.**\nbody\n")
        ta = _w(d, "a/REPORT.tex", "{\\small Generated 2026-10-13 from the audit records. Do not edit this file.}\nx\n")
        tb = _w(d, "b/REPORT.tex", "{\\small Generated 2026-11-02 from the audit records. Do not edit this file.}\nx\n")
        say("the report's real date stamps (md and tex) do not change its hash",
            content_hash([a, ta], "report") == content_hash([b, tb], "report"))
        say("...but a date line in a hand-written document does", content_hash([a], "decisions") != content_hash([b], "decisions"))
        _w(d, "rr/REPORT.md", "r"); _w(d, "rr/REPORT.tex", "t")
        say("PDF-AGENTS: the report resolves to its markdown only (a leftover .tex is read by nothing)",
            [os.path.basename(x) for x in resolve(cfg, "report")[1]] == ["REPORT.md"])
        say("PDF-AGENTS migration shim: the old md+tex hash of the unchanged md is recognised; a changed md is not",
            legacy_hash(resolve(cfg, "report")[1], "report") == content_hash(
                [os.path.join(d, "rr/REPORT.md"), os.path.join(d, "rr/REPORT.tex")], "report")
            and legacy_hash(resolve(cfg, "report")[1], "report") != content_hash(resolve(cfg, "report")[1], "report")
            and legacy_hash([os.path.join(d, "rr/DECISIONS.md")], "decisions") is None)
        _lr = os.path.join(d, "rr", "readers", f"report-{RN}-1.md")
        _lh = content_hash([os.path.join(d, "rr/REPORT.md"), os.path.join(d, "rr/REPORT.tex")], "report")
        _w(d, f"rr/readers/report-{RN}-1.md", f"sha256: {_lh}\ncoverage: all\nVERDICT: NO BLOCKING PROBLEMS\n")
        _ok_old = check(cfg, "report", check_git=False) == []
        _w(d, "rr/REPORT.md", "r changed")
        _ok_new = any("changed after" in str(p_) for p_ in check(cfg, "report", check_git=False))
        _w(d, "rr/REPORT.md", "r")
        os.remove(_lr)
        say("PDF-AGENTS migration shim, at the gate: a pass recorded on the md and its .tex stands while the md is "
            "unchanged, and goes stale once the md changes", _ok_old and _ok_new)
        say("the report's history is per cycle (keyed by the newest round)", resolve(cfg, "report")[0] == f"report-{RN}")
        k1, _, _ = resolve(cfg, "other:" + _w(d, "rr/x/SUM.md", "s"))
        k2, _, _ = resolve(cfg, "other:" + _w(d, "rr/y/SUM.md", "s"))
        say("other documents get distinct keys", k1 != k2)
        say("an other: document outside the rounds directory is refused (a copy must not reset its history)",
            _raises(lambda: resolve(cfg, "other:" + _w(d, "elsewhere/SUM.md", "s"))))
        say("the sheet needs its round", _raises(lambda: resolve(cfg, "signoff")))
        _w(d, f"rr/{RN}/SIGNOFF.md", "m")
        say("the sheet hashes its rendered md, not SIGNOFF.json (nor a PDF)",
            [os.path.basename(x) for x in (_try(lambda: resolve(cfg, "signoff", RN)) or ["", []])[1]]
            == ["SIGNOFF.md"])
        say("--round approved without an approval record: refused", _raises(lambda: resolve(cfg, "signoff", "approved")))
        _w(d, "rr/APPROVED_FINGERPRINTS.json", json.dumps({"round": RN}))
        say("--round approved reads the round from the approval record",
            (_try(lambda: resolve(cfg, "signoff", "approved")) or [None])[0] == f"signoff-{RN}")
        _w(d, f"rr/QUESTIONS-B-{RN}.md", "q")
        say("the question list of a round without a sheet is refused", _raises(lambda: resolve(cfg, "questions", RN)))
        _w(d, f"rr/{RN}/SIGNOFF.json", "{}")
        say("the Checkpoint B question list has its own fixed path and key",
            resolve(cfg, "questions", RN)[0] == f"questions-{RN}")
        two = ("**Generated 2026-10-13 by `audits/make_report.py`. Do not edit this file.**\n"
               "**Generated 2026-10-14 by `audits/make_report.py`. Do not edit this file.**\n")
        say("only the first date stamp is stripped (a second one in the body still counts)",
            content_hash([_w(d, "s1/REPORT.md", two)], "report")
            != content_hash([_w(d, "s2/REPORT.md", two.replace("14", "15"))], "report"))
        say("outside a git repository the history check fails closed", history_problems(rdir, key) != [])
        g = lambda *x: subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", d, *x], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        g("add", "-A"); g("commit", "-qm", f"reader {key} 1")
        say("committed records pass the history check", history_problems(rdir, key) == [])
        sel = project.select
        project.select = lambda name=None: (cfg, None)
        try:
            open(os.path.join(rdir, f"{key}-1.md"), "a").write("x\n")
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--doc", "decisions", "--check"])
            say("the CLI gate runs the history check (an uncommitted record edit is refused)",
                rc == 1 and "not committed" in buf.getvalue())
            project.select = lambda name=None: (dict(cfg, mode="release"), None)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--doc", "decisions", "--check"])
            say("release mode: an uncommitted reader record still refuses the gate (integrity)",
                rc == 1 and "PROBLEM[reader-check] reader record or notice not committed" in buf.getvalue())
            g("checkout", "--", os.path.relpath(os.path.join(rdir, f"{key}-1.md"), d))
        finally:
            project.select = sel
        _w(d, f"rr/KNOWN_FAULTS-{key}.md", "- an uncommitted notice\n")
        say("an uncommitted notice: refused", any("not committed" in p for p in history_problems(rdir, key)))
        g("add", "-A"); g("commit", "-qm", f"reader {key} notice")
        open(os.path.join(rdir, f"{key}-1.md"), "a").write("x\n")
        say("an uncommitted edit to a record: refused", any("not committed" in p for p in history_problems(rdir, key)))
        g("checkout", "--", os.path.relpath(os.path.join(rdir, f"{key}-1.md"), d))
        # a committed blocking record, later rewritten clean and deleted, still counts as first committed
        nb = next_number(cfg, key)
        reader(nb, put("v4\n"), "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: the WASHME finding stays",))
        g("add", "-A"); g("commit", "-qm", f"reader {key} {nb}")
        reader(nb, put("v4\n"), "VERDICT: NO BLOCKING PROBLEMS")
        g("commit", "-qam", f"reader {key} {nb} (reformatted)")
        Cg = lambda: check(cfg, "decisions", check_git=True)
        say("a record rewritten after its commit is read as first committed (no wash)",
            any("WASHME" in p for p in Cg()))
        os.remove(os.path.join(rdir, f"{key}-{nb}.md")); g("commit", "-qam", f"reader {key} {nb} (deleted)")
        say("...and so is a deleted one", any("WASHME" in p for p in Cg()))
        say("...and the edit is noted for the human", any(f"{key}-{nb}.md" in x for x in history_notes(rdir, key)))
        _w(d, "rr/readers/other-NOTES-md-abc-1.md", "sha256: x\n"); g("add", "-A"); g("commit", "-qm", "reader other 1")
        _w(d, "rr/readers/other-NOTES-md-abc-1.md", "sha256: y\n"); g("commit", "-qam", "reader other 1 (edit)")
        say("a changed record of ANOTHER document does not block this one",
            not any("other-" in p for p in history_problems(rdir, key)) and not any("other-" in p for p in Cg()))
        say("--next numbers after every record ever committed", next_number(cfg, key) == nb + 1)
        reader(nb, put("v4\n"), "VERDICT: NO BLOCKING PROBLEMS"); g("add", "-A"); g("commit", "-qm", f"reader {key} {nb} (re-added)")
        say("a record deleted and re-added clean is still read as FIRST committed (no wash)",
            any("WASHME" in p for p in Cg()))
        sel = project.select
        project.select = lambda name=None: (cfg, None)
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                main(["--doc", "decisions", "--check"])
            say("the CLI prints records changed after their commit as NOTEs", "NOTE" in buf.getvalue()
                and f"{key}-{nb}.md" in buf.getvalue())
        finally:
            project.select = sel
        nb2 = next_number(cfg, key)
        g("checkout", "-q", "-b", "side")
        reader(nb2, put("v4\n"), "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: MERGEDIN finding",))
        g("add", "-A"); g("commit", "-qm", f"reader {key} {nb2}")
        g("checkout", "-q", "-"); g("merge", "-q", "--no-ff", "-m", "merge side", "side")
        reader(nb2, put("v4\n"), "VERDICT: NO BLOCKING PROBLEMS"); g("commit", "-qam", f"reader {key} {nb2} (edit)")
        say("a record brought in by a merge is read as the merge added it (no wash)",
            any("MERGEDIN" in p for p in Cg()))
        nb3 = next_number(cfg, key)
        g("checkout", "-q", "-b", "side2"); _w(d, "other.txt", "x"); g("add", "-A"); g("commit", "-qm", "unrelated")
        g("checkout", "-q", "-"); g("merge", "-q", "--no-ff", "--no-commit", "side2")
        reader(nb3, put("v4\n"), "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: INMERGE finding",))
        g("add", "-A"); g("commit", "-qm", f"reader {key} {nb3} (in a merge)")
        reader(nb3, put("v4\n"), "VERDICT: NO BLOCKING PROBLEMS"); g("commit", "-qam", f"reader {key} {nb3} (edit)")
        say("a record added by the merge commit itself is read as the merge added it",
            any("INMERGE" in p for p in Cg()))
        g("checkout", "-q", "-b", "side3"); _w(d, "other3.txt", "x"); g("add", "-A"); g("commit", "-qm", "unrelated 3")
        g("checkout", "-q", "-"); g("merge", "-q", "--no-ff", "--no-commit", "side3")
        _w(d, f"rr/readers/{key}-{nb3}.md", "edited inside a merge\n"); g("add", "-A"); g("commit", "-qm", "merge side3")
        say("an edit made inside a merge commit is noted", sum(f"{key}-{nb3}.md" in x for x in history_notes(rdir, key)) >= 2)
        shallow = tempfile.mkdtemp(prefix="readers-sc-")
        nb5 = next_number(cfg, key)
        base_ = g("rev-parse", "HEAD").stdout.strip()
        reader(nb5, put("v4\n"), "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: BACKDATE finding",))
        g("add", "-A"); g("commit", "-qm", f"reader {key} {nb5}")
        g("checkout", "-q", "-b", "side4", base_)
        reader(nb5, put("v4\n"), "VERDICT: NO BLOCKING PROBLEMS"); g("add", "-A")
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", d, "commit", "-qm", "clean copy"],
                       env=dict(os.environ, GIT_COMMITTER_DATE="2020-01-01T00:00:00", GIT_AUTHOR_DATE="2020-01-01T00:00:00"),
                       capture_output=True)
        g("checkout", "-q", "-"); g("merge", "-q", "-s", "ours", "-m", "merge side4", "side4")
        say("a backdated clean copy on a side branch merged with -s ours does not replace the record",
            any("BACKDATE" in p for p in Cg()))
        _w(d, f"rr/readers/z/{key}-{nb5}.md", "sha256: x\ncoverage: x\nVERDICT: NO BLOCKING PROBLEMS\n")
        g("add", "-A"); g("commit", "-qm", f"reader {key} {nb5} (subdir)")
        g("rm", "-q", f"rr/readers/{key}-{nb5}.md"); g("commit", "-qm", "reader rm")
        reader(nb5, put("v4\n"), "VERDICT: BLOCKING PROBLEMS: 1", findings=("- BLOCKING: BACKDATE finding",))
        g("add", "-A"); g("commit", "-qm", f"reader {key} {nb5} (re-added)")
        say("a same-named file in a subdirectory never stands in for a record", any("BACKDATE" in p for p in Cg()))
        say("a deleted record is noted (D)", any(x.startswith("D ") and f"{key}-{nb5}.md" in x for x in history_notes(rdir, key)))
        say("records of a key that merely starts with this key are not this key's", not key_file(key, f"{key}-x-1.md")
            and key_file(key, f"{key}-3.md") and key_file(key, f"{key}-3.response-2.md"))
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + d, shallow], capture_output=True)
        saved_a = project.AUDITS; project.AUDITS = shallow
        try:
            say("a shallow clone fails closed", any("shallow" in p for p in
                check(cfg, "decisions", check_git=True)))
        finally:
            project.AUDITS = saved_a; shutil.rmtree(shallow, ignore_errors=True)
        nb4 = next_number(cfg, key)
        reader(nb4, put("v4\n"), "VERDICT: NO BLOCKING PROBLEMS"); g("add", "-A")
        say("a record staged but not committed refuses its own document",
            any("tracked but not committed" in p for p in Cg()))
        _w(d, "rr/readers/other-X-md-1-1.md", "s"); g("add", "-A")
        say("...and not another document's gate", not any("other-X" in p for p in Cg()))
        g("commit", "-qm", f"reader {key} {nb4}")
        g("mv", f"rr/readers/{key}-{nb}.md", f"rr/readers/{key}-{nb}.tmp")
        g("commit", "-qm", "reader move"); _w(d, f"rr/readers/{key}-{nb}.tmp", "edited\n")
        g("mv", "-f", f"rr/readers/{key}-{nb}.tmp", f"rr/readers/{key}-{nb}.md"); g("commit", "-qam", "reader move back")
        say("a record moved away, edited and moved back is still read as first committed",
            any("WASHME" in p for p in Cg()))
        say("...and the change is noted", any(f"{key}-{nb}.md" in x for x in history_notes(rdir, key)))
        big = tempfile.mkdtemp(prefix="readers-big-")
        gb = lambda *x: subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", big, *x], capture_output=True, text=True)
        gb("init", "-q"); gb("config", "user.email", "t@t"); gb("config", "user.name", "t")
        _w(big, "sub/rr/readers/k-1.md", "FIRST\n"); gb("add", "-A"); gb("commit", "-qm", "reader k 1")
        _w(big, "sub/rr/readers/k-1.md", "edited\n"); gb("commit", "-qam", "edit")
        saved_a = project.AUDITS; project.AUDITS = os.path.join(big, "sub")
        try:
            tb = _try(lambda: record_texts(os.path.join(big, "sub", "rr", "readers")))
            say("audits as a subdirectory of a larger repository: records read as first committed, none 'unseen'",
                tb is not None and tb.get("k-1.md") == "FIRST\n" and record_texts.unseen == [])
        finally:
            project.AUDITS = saved_a; shutil.rmtree(big, ignore_errors=True)
        uni = tempfile.mkdtemp(prefix="readers-uni-")
        gu = lambda *x: subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", uni, *x], capture_output=True, text=True)
        gu("init", "-q"); gu("config", "user.email", "t@t"); gu("config", "user.name", "t")
        _w(uni, "Gödel/readers/k-1.md", "FIRSTVERSION\n"); gu("add", "-A"); gu("commit", "-qm", "reader k 1")
        _w(uni, "Gödel/readers/k-1.md", "edited\n"); gu("commit", "-qam", "edit")
        saved_a = project.AUDITS; project.AUDITS = uni
        try:
            tx_ = _try(lambda: record_texts(os.path.join(uni, "Gödel", "readers")))
            say("a non-ASCII rounds directory works, and records are read as first committed",
                tx_ is not None and tx_.get("k-1.md") == "FIRSTVERSION\n")
        finally:
            project.AUDITS = saved_a; shutil.rmtree(uni, ignore_errors=True)
        # --save: the reader's text goes in on stdin and comes out committed, byte for byte
        sv = tempfile.mkdtemp(prefix="readers-save-")
        gs = lambda *x: subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", sv, *x], capture_output=True, text=True)
        gs("init", "-q"); gs("config", "user.email", "t@t"); gs("config", "user.name", "t")
        saved_ra = (project.REPO, project.AUDITS); project.REPO = project.AUDITS = sv
        try:
            os.makedirs(os.path.join(sv, "rr", RN))
            open(os.path.join(sv, "rr", RN, "TARGET.json"), "w").write("{}")
            dp = os.path.join(sv, "rr", "DECISIONS.md")
            open(dp, "w").write(f"<!-- decisions-round: {RN} -->\nthe document\n")
            gs("add", "-A"); gs("commit", "-qm", "setup")
            hs = content_hash([dp], "decisions")
            good = (f"sha256: {hs}\ncoverage: 3 of 3 references; COULD NOT CHECK: none\n"
                    "- BLOCKING: a finding with “quotes” and ü\nVERDICT: BLOCKING PROBLEMS: 1\n")
            p1, pr1 = save(cfg, "decisions", None, good)
            say("--save: a well-formed record is written as <key>-1.md and committed",
                pr1 == [] and p1 and p1.endswith(f"decisions-{RN}-1.md")
                and gs("log", "-1", "--format=%s").stdout.strip() == f"reader decisions-{RN} 1")
            say("--save: the committed file is byte for byte the text given",
                gs("show", f"HEAD:rr/readers/decisions-{RN}-1.md").stdout == good)
            say("--save: the commit holds that one file only",
                gs("show", "--name-only", "--format=", "HEAD").stdout.split() == [f"rr/readers/decisions-{RN}-1.md"])
            p2, pr2 = save(cfg, "decisions", None, good.replace(hs, "0" * 64))
            say("--save: a record of another version of the document is refused, nothing written",
                p2 is None and any("another version" in x for x in pr2)
                and not os.path.exists(os.path.join(sv, "rr", "readers", f"decisions-{RN}-2.md")))
            p3, pr3 = save(cfg, "decisions", None, good.replace("VERDICT: BLOCKING PROBLEMS: 1\n", ""))
            say("--save: a malformed record (no VERDICT line) is refused", p3 is None and pr3 != [])
            p4, pr4 = save(cfg, "decisions", None, f"sha256: {hs}\ncoverage: x\nVERDICT: NO BLOCKING PROBLEMS\n")
            say("--save: the next pass gets the next number", pr4 == [] and p4.endswith(f"decisions-{RN}-2.md"))
        finally:
            project.REPO, project.AUDITS = saved_ra; shutil.rmtree(sv, ignore_errors=True)
    finally:
        project.REPO, project.AUDITS = saved
        shutil.rmtree(d, ignore_errors=True)
    for name, ok in _b10_controls():
        say(name, ok)
    for name, ok in _docfix_controls():
        say(name, ok)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


def _b10_controls():
    """B10 (U2 §6.3, ADDENDUM N4): the summary document, the reader modes, finding labels and the fix budget."""
    out = []
    d = tempfile.mkdtemp(prefix="readers-b10-")
    saved = (project.REPO, project.AUDITS)
    G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    try:
        project.REPO = project.AUDITS = d
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        RN = "2026-01-01-abc1234"
        root = os.path.join(d, "rr")
        _w(root, f"{RN}/TARGET.json", "{}")
        smd = _w(root, "SUMMARY.md", "# Summary\n- result: Lemma 1 — faithful\n")
        rdir = os.path.join(root, "readers")
        os.makedirs(rdir)
        cfg = {"rounds_dir": "rr", "mode": "release"}
        key = f"summary-{RN}"
        out.append(("B10: --doc summary resolves to SUMMARY.md, keyed by the newest round; the reader reads the md",
                    resolve(cfg, "summary")[0] == key and resolve(cfg, "summary")[1] == [smd]
                    and resolve(cfg, "summary")[2].endswith("SUMMARY.md") and mode_of("summary") == "gated"
                    and mode_of("report") == mode_of("decisions") == "single" and mode_of("other:/x") == "gated"))
        miss = check(cfg, "summary", check_git=False)
        out.append(("B10: a missing summary pass blocks in release too (gated at every level; never disclosed)",
                    bool(miss) and project.split(cfg, miss)[1] == []))
        h = content_hash([smd], "summary")

        def rec(k, n, sha, findings=(), dkey=None):
            _w(rdir, f"{dkey or key}-{n}.md", f"sha256: {sha}\ncoverage: all\n" + "".join(f + "\n" for f in findings)
               + (f"VERDICT: BLOCKING PROBLEMS: {sum(1 for f in findings if f.startswith('- BLOCKING'))}"
                  if any(f.startswith("- BLOCKING") for f in findings) else "VERDICT: NO BLOCKING PROBLEMS") + "\n")
        CF = "- BLOCKING: [content] Lemma 1 reads faithful but PAPER_DEFECTS.md row 1 names it"
        PF = "- BLOCKING: [presentation] the line about Lemma 2 wraps in the middle of a name"
        rec(key, 1, h, (CF, PF))
        _w(rdir, f"{key}-1.response.md", "- unfixable: Lemma 1 reads faithful but PAPER_DEFECTS — no fix open\n"
           "- unfixable: the line about Lemma 2 wraps — a generator fault\n")
        _w(root, f"KNOWN_FAULTS-{key}.md", "Lemma 1 reads faithful but PAPER_DEFECTS.md row 1 names it\n"
           "the line about Lemma 2 wraps in the middle of a name\n")
        G("add", "-A"); G("commit", "-qm", "x")
        c0 = check(cfg, "summary", check_git=False)
        out.append(("N4: a [content] finding answered unfixable while the run's reader-fix budget is unspent is refused "
                    "(it goes to the adjudicator's reader-fix round); DOC-FIX G4: a [presentation] one answered "
                    "\"unfixable: a generator fault\" is refused (reject, tool patch or hand edit)",
                    any("content finding" in p and "reader-fix" in p for p in c0)
                    and any("wraps" in p and "fault of the generated" in p for p in c0)))
        # the operator rejects it with a reason (approver 2026-10-25, answer 1)
        _w(rdir, f"{key}-1.response-2.md", "- dismissed: the line about Lemma 2 wraps — trivial: the PDF sets the name "
           "on one line; neither faithfulness nor readability is affected\n")
        G("add", "-A"); G("commit", "-qm", "x2")
        cf0 = content_findings(cfg)
        out.append(("N4: content_findings lists the unanswered-or-unfixable [content] findings, never a [presentation] one",
                    [f for _k, _n, f in cf0] == [CF[len("- BLOCKING: "):]]))
        for k in (1, 2):
            G("commit", "-q", "--allow-empty", "-m", f"reader-fix {RN} {k}")
        out.append(("N4: once both reader-fix rounds are spent, the content finding may be left unfixable (in the notice; "
                    "release)", fix_rounds_used(cfg) == 2 and check(cfg, "summary", check_git=False) == []))
        out.append(("U2 §6.3 (dev): a blocking finding past the fix budget is a stop, never disclosed",
                    any("dev mode" in p for p in check(dict(cfg, mode="dev"), "summary", check_git=False))))
        _w(rdir, f"{key}-1.response-3.md", "- dismissed: Lemma 1 reads faithful but PAPER_DEFECTS — row 1 is about Lemma 3\n")
        out.append(("N4: a dismissed content finding is not sent to a reader fix",
                    content_findings(cfg) == []))
        # single mode: exactly one pass per version, once the delivery flow runs (DELIVERY.json)
        dmd = _w(root, "DECISIONS.md", f"<!-- decisions-round: {RN} -->\n# D\n")
        hd = content_hash([dmd], "decisions")
        rec(None, 1, hd, dkey=f"decisions-{RN}")
        rec(None, 2, hd, dkey=f"decisions-{RN}")
        two_old = check(cfg, "decisions", check_git=False)
        _w(root, DELIVERY_RECORD, "{}")
        two_new = check(cfg, "decisions", check_git=False)
        out.append(("U2 §6.3: a single-pass document (DECISIONS, REPORT) gets exactly one pass per version: a second "
                    "pass on the same version is refused once prepare has run (an older run's records keep their rules)",
                    two_old == [] and any("exactly one pass per version" in p for p in two_new)))
        os.remove(os.path.join(rdir, f"decisions-{RN}-2.md"))
        out.append(("U2 §6.3: one pass on the current version of a single-pass document is enough",
                    check(cfg, "decisions", check_git=False) == []))
        # with git: a pass recorded before the first prepare keeps its old rules (an older run's records)
        rmd = _w(root, "REPORT.md", "# R\n")
        os.remove(os.path.join(root, DELIVERY_RECORD))
        hr = content_hash([rmd], "report")
        rk = f"report-{RN}"
        UF = "- BLOCKING: an old finding in the run's own words"
        rec(None, 1, hr, (UF,), dkey=rk)
        _w(rdir, f"{rk}-1.response.md", "- unfixable: an old finding in the run's own words — fix budget reached\n")
        _w(root, f"KNOWN_FAULTS-{rk}.md", "an old finding in the run's own words\n")
        rec(None, 2, hr, dkey=rk)
        G("add", "-A"); G("commit", "-qm", "an older run's passes")
        _w(root, DELIVERY_RECORD, "{}")
        G("add", "-A"); G("commit", "-qm", "prepare delivery")
        old_ok = check(cfg, "report")
        rec(None, 3, hr, (CF,), dkey=rk)
        _w(rdir, f"{rk}-3.response.md", "- unfixable: Lemma 1 reads faithful but PAPER_DEFECTS — no fix open\n")
        G("add", "-A"); G("commit", "-qm", "a pass after prepare")
        G("reset", "-q", "--soft", "HEAD~0")
        out.append(("B10 honest path: a pass recorded before the first prepare keeps the rules it was answered under "
                    "(unlabelled unfixable, two passes on one text); a pass after it follows the delivery rules",
                    old_ok == [] and any("Lemma 1 reads faithful" in p for p in check(cfg, "report"))
                    and flow_passes(cfg, [f"{rk}-1.md", f"{rk}-3.md"]) == {f"{rk}-3.md"}))
    finally:
        project.REPO, project.AUDITS = saved
        shutil.rmtree(d, ignore_errors=True)
    return out


def _docfix_controls():
    """DOC-FIX (approver 2026-10-25): a fault an agent finds in a generated document is rejected, fixed in the
    generator, or hand-edited after the final prepare -- recorded, chained, judged by the status check."""
    out = []
    d = tempfile.mkdtemp(prefix="readers-docfix-")
    saved = (project.REPO, project.AUDITS)
    G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
    try:
        project.REPO = project.AUDITS = d
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        RN = "2026-01-01-abc1234"
        root = os.path.join(d, "rr")
        cfg = {"rounds_dir": "rr", "mode": "release"}
        _w(root, f"{RN}/TARGET.json", "{}")
        gen = "# Summary\n- defect 1 — Lemma 1.2: false; typo; decided since (REPORT §5)\n- result: Lemma 1 — faithful\n"
        smd = _w(root, "SUMMARY.md", gen)
        rdir = os.path.join(root, "readers")
        key = f"summary-{RN}"
        PF = "- BLOCKING: [presentation] the defect 1 line is cut short after decided since and says nothing"
        _w(rdir, f"{key}-1.md", f"sha256: {content_hash([smd], 'summary')}\ncoverage: all\n{PF}\n"
           "VERDICT: BLOCKING PROBLEMS: 1\n")
        G("add", "-A"); G("commit", "-qm", "records and a reader")
        F = f"readers/{key}-1.md: the defect 1 line is cut short after decided since"
        # before any prepare a hand edit is refused (it comes after the final prepare)
        open(smd, "a").write("x\n")
        he0, p0 = record_hand_edit(cfg, "summary", F)
        open(smd, "w").write(gen)
        json.dump({"hashes": {"SUMMARY.md": project.doc_text_hash("SUMMARY.md", gen)}},
                  open(os.path.join(root, DELIVERY_RECORD), "w"))
        G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
        un = record_hand_edit(cfg, "summary", F)
        sheet = record_hand_edit(cfg, "signoff", F)
        open(smd, "w").write(gen.replace("decided since (REPORT §5)",
                                         "decided by the operator under hands-off ([DELEGATED]), REPORT §5"))
        bad_src = record_hand_edit(cfg, "summary", "RUN_LOG.md: the defect 1 line is cut short after decided since")
        bad_q = record_hand_edit(cfg, "summary", f"readers/{key}-1.md: a quote the reader never wrote at all")
        out.append(("DOC-FIX: a hand edit is refused before the final prepare, on an unchanged document, on the sheet, "
                    "and for a finding that is not an agent's committed record (or not quoted from it); nothing is "
                    "written",
                    he0 is None and any("after the final prepare" in x for x in p0)
                    and un[0] is None and any("unchanged" in x for x in un[1])
                    and sheet[0] is None and any("sheet" in x for x in sheet[1])
                    and bad_src[0] is None and any("--finding must be" in x for x in bad_src[1])
                    and bad_q[0] is None and any("does not stand" in x for x in bad_q[1])
                    and not os.path.isdir(os.path.join(root, HE_DIR))))
        # a status check committed BEFORE the edit cannot have judged it
        _w(root, "status-check/FINDINGS.md", "# Status check\n\n## Hand edits\n\n- HE1: OK -- written early\n")
        G("add", "--", "rr/status-check"); G("commit", "-qm", "status-check: findings")
        he, ps = record_hand_edit(cfg, "summary", F)
        early = judgement_problems(cfg)
        subj = G("log", "-1", "--format=%s").stdout.strip()
        files = G("show", "--format=", "--name-only", "HEAD").stdout.split()
        rec_ = json.load(open(os.path.join(root, HE_DIR, "HE1.json")))
        out.append(("DOC-FIX: readers.py --hand-edit records HE1 (the finding, the prepare, the hashes before and "
                    "after, the diff) and commits it with the document alone as \"hand-edit HE1 SUMMARY.md\"; the "
                    "chain then holds",
                    he == "HE1" and ps == [] and subj == "hand-edit HE1 SUMMARY.md"
                    and sorted(files) == ["rr/SUMMARY.md", "rr/hand-edits/HE1.diff", "rr/hand-edits/HE1.json"]
                    and rec_["base_sha256"] == project.doc_text_hash("SUMMARY.md", gen)
                    and rec_["result_sha256"] == project.file_hash("SUMMARY.md", smd)
                    and "+- defect 1 — Lemma 1.2: false; typo; decided by the operator" in
                    open(os.path.join(root, HE_DIR, "HE1.diff")).read()
                    and hand_edit_problems(cfg, "SUMMARY.md") == []
                    and [r["he"] for r in live_hand_edits(cfg)] == ["HE1"]))
        # the answer: fixed by HE1, and a fresh reader's pass on the edited version
        _w(rdir, f"{key}-1.response.md", "- fixed: the defect 1 line is cut short — hand edit HE1\n")
        _w(rdir, f"{key}-2.md", f"sha256: {content_hash([smd], 'summary')}\ncoverage: all\n"
           "VERDICT: NO BLOCKING PROBLEMS\n")
        G("add", "-A"); G("commit", "-qm", f"reader {key} 2")
        ok_gate = check(cfg, "summary")
        # an unrecorded edit on top: refused by the chain (on disk, then committed in another commit)
        open(smd, "a").write("- stop S9 — gone\n")
        disk_bad = hand_edit_problems(cfg, "SUMMARY.md")
        G("add", "-A"); G("commit", "-qm", "tidy the summary")
        commit_bad = hand_edit_problems(cfg, "SUMMARY.md")
        G("reset", "-q", "--hard", "HEAD~1")
        # a hand edit whose diff record was altered after its commit
        open(os.path.join(root, HE_DIR, "HE1.diff"), "a").write("+ smuggled\n")
        diff_bad = hand_edit_problems(cfg, "SUMMARY.md")
        G("checkout", "-q", "--", "rr/hand-edits/HE1.diff")
        # a forged "hand-edit HE2" commit by hand whose diff record is not the diff it made
        open(smd, "a").write("- forged line\n")
        rec2 = dict(rec_, base_sha256=rec_["result_sha256"], result_sha256=project.file_hash("SUMMARY.md", smd))
        json.dump(rec2, open(os.path.join(root, HE_DIR, "HE2.json"), "w"))
        open(os.path.join(root, HE_DIR, "HE2.diff"), "w").write("diff --git a/SUMMARY.md b/SUMMARY.md\n+- another line\n")
        G("add", "-A"); G("commit", "-qm", "hand-edit HE2 SUMMARY.md")
        forged = hand_edit_problems(cfg, "SUMMARY.md")
        G("reset", "-q", "--hard", "HEAD~1")
        out.append(("DOC-FIX G1: an edit outside a recorded hand edit is refused, uncommitted or committed under "
                    "another subject, and so is a hand-edit record changed after its commit; the honest chain and "
                    "the reader gate pass",
                    ok_gate == [] and any("outside a recorded hand edit" in x for x in disk_bad)
                    and any("no recorded hand edit" in x for x in commit_bad)
                    and any("changed after its commit" in x or "is not the diff" in x for x in diff_bad)
                    and any("HE2.diff is not the diff" in x for x in forged)))
        # G5: the status check judges the edit; its FINDINGS.md must be the issued agent's, sealed (DOC-FIX review #3)
        import run_record as RR
        no_judge = judgement_problems(cfg)
        sc = os.path.join(root, "status-check", "FINDINGS.md")
        HEAD_ = "# Status check\n\n## Mismatches\n\n- none\n\n## Hand edits\n\n"

        def begin_():
            try:
                return RR.begin_status_run(cfg)
            except ValueError as e_:
                return "refused: " + str(e_)

        def agent_(body):
            """the issued agent: FINDINGS.md with its run's token; returns the digest of its completion line"""
            txt = HEAD_ + f"run-token: {RR.begin_status_run.token}\n" + body
            open(sc, "w").write(txt)
            return hashlib.sha256(txt.encode()).hexdigest()

        def seal_(dg, who="agent-1"):
            try:
                return RR.seal_status_run(cfg, dg, who)
            except ValueError as e_:
                return "refused: " + str(e_)
        # a mutant may break this fixture's sequence (a refusal where a run was expected): a failed check, never
        # a crash (mutants.py counts a crash as saying nothing)
        g5_ok = True
        try:
            n1 = begin_()
            # the operator types the verdict (the early file, re-committed after the edit): no token, no seal
            open(sc, "w").write(HEAD_ + "- HE1: OK -- typed by the operator\n")
            G("add", "-A"); G("commit", "-qm", "status-check: findings")
            typed = judgement_problems(cfg)
            typed_seal = seal_(hashlib.sha256(open(sc, "rb").read()).hexdigest())
            n2 = begin_()             # run 1 gave no sealed verdict: a failed run, run again (the same SUMMARY.md)
            failed1 = RR.status_runs(cfg)[0].get("failed", "")
            no_file = judgement_problems(cfg)       # run 2's agent wrote nothing
            n3 = begin_()
            failed2 = RR.status_runs(cfg)[1].get("failed", "")
            agent_("- HE1: fine\n")                # run 3's agent wrote no verdict line
            G("add", "-A"); G("commit", "-qm", "status-check: findings")
            no_line = judgement_problems(cfg)
            n4 = begin_()                           # past the cap of 3: a failed run is never counted as a judgement
            dg = agent_("- HE1: MISMATCH -- it says the operator decided; the records say so too, but it also drops "
                        "the defect\n")
            dirty = judgement_problems(cfg)
            # DOC-FIX re-check #3(a): the tokened, complete, unsealed MISMATCH is a judgement -- no new run on it, and
            # none either once it is deleted after a version of it was committed
            unsealed_shop = begin_()
            saved_ = open(sc).read()
            G("add", "--", sc); G("commit", "-qm", "status-check: findings", "--", sc)
            os.remove(sc)
            deleted_shop = begin_()
            G("reset", "-q", "--soft", "HEAD~1"); G("reset", "-q", "--", sc)
            open(sc, "w").write(saved_)
            bad_seal = seal_("0" * 64)
            sealed = seal_(dg)
            seal_subj = G("log", "-1", "--format=%s").stdout.strip()
            mism = judgement_problems(cfg)
            shop = begin_()                         # a sealed verdict is a judgement: no new run on the same edits
            typed_over = open(sc).read().replace("MISMATCH", "OK")
            open(sc, "w").write(typed_over)
            G("add", "-A"); G("commit", "-qm", "status-check: findings")
            over = judgement_problems(cfg)
            restore_msg = begin_()            # review 2: a sealed run's file replaced -> restore the sealed version
            G("reset", "-q", "--hard", "HEAD~1")
            rr_lines = "\n".join(RR.status_check_lines(cfg))
            out.append(("DOC-FIX review #2/#3: a status-check run that gave no sealed verdict on the live hand edits (a "
                        "verdict typed by the operator, no FINDINGS.md, no verdict line) failed: a mechanical failure, "
                        "recorded, never a judgement; it is run again whatever the SUMMARY.md and the cap. A verdict "
                        "line not in the issued agent's sealed file is refused, the seal refuses a file without the run's "
                        "token or with another digest; a sealed MISMATCH is a judgement (no re-run on the same edits)",
                        n1 == "status-check.txt" and any("no sealed verdict" in x and "not sealed" in x for x in typed)
                        and typed_seal.startswith("refused: ") and "token" in typed_seal
                        and n2 == "status-check-2.txt" and "not sealed" in failed1 and "HE1: OK" in failed1
                        and any("not judged" in x for x in no_file) and n3 == "status-check-3.txt"
                        and "wrote no FINDINGS.md" in failed2
                        and any("no `- <HE>: OK|MISMATCH` line" in x for x in no_line) and n4 == "status-check-4.txt"
                        and any("not judged" in x for x in dirty) and bad_seal.startswith("refused: ")
                        and "not the file the agent returned" in bad_seal and not sealed.startswith("refused")
                        and seal_subj == "status-check: seal run 4" and shop.startswith("refused: ")
                        and any("not the one its seal names" in x for x in over)
                        and "FAILED, a mechanical failure and not a judgement" in rr_lines
                        and "sealed (agent `agent-1`)" in rr_lines))
            out.append(("DOC-FIX re-check #3(a): an unsealed FINDINGS.md carrying the run's token and a verdict on every "
                        "live hand edit is a judgement: no new run (it must be sealed), also after it is deleted once a "
                        "version of it was committed",
                        "restore the sealed version" in restore_msg and "checkout" in restore_msg
                        and unsealed_shop.startswith("refused: ") and "it is a judgement" in unsealed_shop
                        and "HE1: MISMATCH" in unsealed_shop and deleted_shop.startswith("refused: ")
                        and "committed in" in deleted_shop))
            out.append(("DOC-FIX review #4: a MISMATCH is undone by preparing again and re-applying the edits judged OK; "
                        "the refusal never offers a hand edit restoring the text (the check judges each diff: it looped)",
                        any("MISMATCH" in x and "preparing again" in x and "does not undo it" in x for x in mism)
                        and not any("a hand edit restoring the generated text" in x for x in mism)))
            # a second edit (HE2): the next run judges both, sealed OK
            open(smd, "a").write("- result: Lemma 2 — faithful\n")
            he2, _p2 = record_hand_edit(cfg, "summary", F)
            n5 = begin_()
            seal_(agent_("- HE1: OK -- it names who decided, as RUN_LOG.md does; no status changes\n"
                         "- HE2: OK -- adds a row the records hold\n"))
            okj = judgement_problems(cfg)
            prompt_list = hand_edit_summary(cfg)
        except (IndexError, KeyError, AttributeError, OSError, TypeError, ValueError):
            g5_ok = False
            out.append(("DOC-FIX review #2/#3/#4: the status-check fixture ran to its end", False))
        out.append(("DOC-FIX G5: with a live hand edit --deliver needs the status check's judgement, committed after "
                    "the edit: none, one committed before the edit or uncommitted is refused, MISMATCH is refused (undo "
                    "it), OK passes; the prompt lists the edit's diff",
                    g5_ok and any("not judged by the status check" in x for x in no_judge)
                    and any("not judged by the status check" in x for x in early)
                    and any("MISMATCH" in x for x in mism) and he2 == "HE2" and n5 == "status-check-5.txt"
                    and okj == []
                    and prompt_list == "HE1 (SUMMARY.md): rr/hand-edits/HE1.diff; HE2 (SUMMARY.md): rr/hand-edits/HE2.diff"))
        # a later prepare erases the edit: the fixed answer naming it then refuses the gate (never silent)
        open(smd, "w").write(gen)
        G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
        _w(rdir, f"{key}-3.md", f"sha256: {content_hash([smd], 'summary')}\ncoverage: all\n"
           "VERDICT: NO BLOCKING PROBLEMS\n")
        G("add", "-A"); G("commit", "-qm", f"reader {key} 3")
        erased = check(cfg, "summary")
        out.append(("DOC-FIX G3: a later prepare erases the hand edit (no longer live; named as erased), and the "
                    "`fixed ... hand edit HE1` answer then refuses the gate although a reader passed the regenerated "
                    "version",
                    live_hand_edits(cfg) == [] and [r["he"] for r in erased_hand_edits(cfg)] == ["HE1", "HE2"]
                    and any("hand edit HE1" in x and "re-apply" in x for x in erased)
                    and judgement_problems(cfg) == []))
        # approver 2026-10-26 ("make sure the agent guards those lines"): a plain trust line the generator wrote (here
        # a stand-in event) is judged by the status check; the generator omitting or misstating it -> MISMATCH ->
        # delivery refused, through the generator or a hand edit; judged OK after the fix -> accepted
        import make_report as MR, inspect
        keep_tp = list(MR.TRUST_LINE_PROVIDERS)
        MR.TRUST_LINE_PROVIDERS[:] = [lambda c_: [MR.TrustEvent(
            "TL-not-verified-S9", "a check could not be run", "Not verified: the check X could not be run.",
            "RUN_RECORD.md: stop S9", "every result's status reads \"not verified: X\"")]]
        try:
            tl0 = trust_problems(cfg)
            nt = begin_()
            prompt_tl = MR.trust_line_summary(cfg)
            dgt = agent_("- none\n\n## Trust lines\n\n- TL-not-verified-S9: MISMATCH -- the summary's first lines omit "
                         "it; RUN_RECORD.md says \"stop S9\"\n")
            tl_unsealed = trust_problems(cfg)
            seal_t = seal_(dgt)
            tl1 = trust_problems(cfg)
            open(smd, "a").write("**Not verified: the check X could not be run.**\n")
            G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
            nt2 = begin_()
            dgt2 = agent_("- none\n\n## Trust lines\n\n- TL-not-verified-S9: OK -- on the first lines and true\n"
                          "- extra: MISMATCH -- \"Not verified: the record ...\" has no event\n")
            seal_(dgt2)
            tl_extra = trust_problems(cfg)
            open(smd, "a").write("\n")       # the generator fixed, the documents prepared again
            G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
            nt3 = begin_()
            dgt3 = agent_("- none\n\n## Trust lines\n\n- TL-not-verified-S9: OK -- on the first lines and true\n")
            seal_(dgt3)
            tl2 = trust_problems(cfg)
            # review 3: an OK is bound to the SUMMARY.md it judged -- a later prepare asks for a new run, past the cap
            open(smd, "a").write("- a later prepare\n")
            G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
            tl_stale = trust_problems(cfg)
            nt4 = begin_()
            seal_(agent_("- none\n\n## Trust lines\n\n- TL-not-verified-S9: OK -- still true\n"))
            tl3 = trust_problems(cfg)
            # review 3 (fail-safe): a trust sentence in SUMMARY.md that no provider stands for refuses delivery
            open(smd, "a").write("**Not verified: the check Y could not be run (details for maintainers in "
                                 "RUN_RECORD.md).**\n")
            G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
            tl_cov = trust_problems(cfg)
            # with no event at all, an `extra` line the agent wrote is still read
            MR.TRUST_LINE_PROVIDERS[:] = []
            rp_ = os.path.join(root, "status-check", RR.STATUS_RUNS)    # that run read this SUMMARY.md
            runs_ = json.load(open(rp_))
            runs_[-1]["summary_sha256"] = RR.summary_sha(cfg)
            json.dump(runs_, open(rp_, "w"))
            open(sc, "w").write(HEAD_ + "- none\n\n## Trust lines\n\n- extra: MISMATCH -- \"Not verified: Y\" has no "
                                "event\n")
            tl_zero = trust_problems(cfg)
            # re-check R1: the generator fixed (the stray sentence gone) and prepared again, past the cap: the extra
            # line no longer counts, and a new run may judge the fixed summary
            open(smd, "w").write(open(smd).read().replace("**Not verified: the check Y could not be run (details for "
                                                          "maintainers in RUN_RECORD.md).**\n", ""))
            G("add", "-A"); G("commit", "-qm", PREPARE_SUBJECT)
            tl_fixed = trust_problems(cfg)
            nt5 = begin_()
            open(sc, "w").write(HEAD_ + "- none\n\n## Trust lines\n\n- none\n")     # the new run finds no extra line
            tl_after = trust_problems(cfg)
        finally:
            MR.TRUST_LINE_PROVIDERS[:] = keep_tp
        out.append(("approver 2026-10-26: a plain trust line is judged by the status check (its prompt lists the event): "
                    "not judged, unsealed, a sealed MISMATCH (the generator omitted it) or an `extra` line refuse "
                    "delivery (the generator or a hand edit, then judged again); judged OK passes",
                    any("not judged by the status check" in x for x in tl0) and not nt.startswith("refused")
                    and "TL-not-verified-S9" in prompt_tl and tl_unsealed and not seal_t.startswith("refused")
                    and any("MISMATCH" in x and "hand edit" in x and "generator" in x for x in tl1)
                    and not nt2.startswith("refused") and any("extra" in x for x in tl_extra)
                    and not nt3.startswith("refused") and tl2 == [] and "what it weakens" in prompt_tl
                    and any("earlier SUMMARY.md" in x for x in tl_stale) and not nt4.startswith("refused") and tl3 == []
                    and any("no event of the record stands for it" in x and "check Y" in x for x in tl_cov)
                    and any("extra" in x for x in tl_zero) and any("no event of the record" in x for x in tl_zero)
                    and any("earlier SUMMARY.md" in x for x in tl_fixed) and not nt5.startswith("refused")
                    and tl_after == []
                    # approver (2026-10-28): the status check no longer runs at delivery; trust_problems stays for an
                    # older run's records and is no longer part of --deliver's checks
                    and "readers.trust_problems(cfg)" not in inspect.getsource(MR.delivery_problems)))
        # G4 on a content finding blaming the generator (after the reader-fix budget), and the report
        rmd = _w(root, "REPORT.md", "# R\n| 1 | md row 1; no corrected variant |\n")
        rk = f"report-{RN}"
        CF = "- BLOCKING: [content] Section 5 row 1 decision cell begins mid-sentence"
        _w(rdir, f"{rk}-1.md", f"sha256: {content_hash([rmd], 'report')}\ncoverage: all\n{CF}\n"
           "VERDICT: BLOCKING PROBLEMS: 1\n")
        _w(rdir, f"{rk}-1.response.md", "- unfixable: Section 5 row 1 decision cell — a fault of the pinned generator "
           "make_report.py; fix budget reached\n")
        _w(root, f"KNOWN_FAULTS-{rk}.md", "Section 5 row 1 decision cell begins mid-sentence\n")
        for k_ in (1, 2):
            G("commit", "-q", "--allow-empty", "-m", f"reader-fix {RN} {k_}")
        G("add", "-A"); G("commit", "-qm", f"reader {rk} 1")
        g4 = check(cfg, "report")
        g4_dev = check(dict(cfg, mode="dev"), "report")
        _w(rdir, f"{rk}-1.response-2.md", "- unfixable: Section 5 row 1 decision cell — the paper's own row is "
           "garbled at tex l.93; nothing can fix it\n")
        G("add", "-A"); G("commit", "-qm", f"reader {rk} 1 (response)")
        paper = check(cfg, "report")
        out.append(("DOC-FIX G4: \"unfixable\" blaming the generator is refused on the report even past the fix "
                    "budget, in release and dev; an unfixable finding about the paper itself stays allowed",
                    any("fault of the generated REPORT.md" in x for x in g4)
                    and any("fault of the generated REPORT.md" in x for x in g4_dev)
                    and not any("fault of the generated" in x for x in paper)
                    and not any("Section 5" in x for x in paper)))
    finally:
        project.REPO, project.AUDITS = saved
        shutil.rmtree(d, ignore_errors=True)
    return out


def _try(f):
    try:
        return f()
    except DocError:
        return None


def _raises(f):
    try:
        f()
    except DocError:
        return True
    return False


def _w(d, name, text):
    p = os.path.join(d, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)
    return p


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

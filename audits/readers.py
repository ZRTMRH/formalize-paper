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
       - fixed: <quote> — <what changed>        (only once a later pass read a changed version)
       - dismissed: <quote> — <evidence that the finding is wrong>
       - unfixable: <quote> — <why no path is open in this run, or "fix budget reached">
                                                          (must also be in the notice)
  3. every `unfixable` finding is quoted in `KNOWN_FAULTS-<key>.md`, the notice shown with the
     document and in the checkpoint message (never inside the hashed document).
Re-running a reader then gains nothing: the findings it would wash away must still be answered.
Passes beyond 3 are allowed but pointless; RUN.md tells the operator to stop fixing after 3 and
mark what remains `unfixable`.

WHAT IS HASHED.  The deterministic rendered text, never a PDF (xelatex embeds a creation date):
  signoff     <round>/SIGNOFF.md + SIGNOFF.tex   (covers SIGNOFF.json, INFORMAL.json, the generator)
  questions   QUESTIONS-B-<round>.md             (the open questions put under the Checkpoint B question)
  report      REPORT.md + REPORT.tex, minus their "Generated <date>" header lines
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
        srcs = [os.path.join(rd, "SIGNOFF.md"), os.path.join(rd, "SIGNOFF.tex")]
        key, shown = f"signoff-{round_name}", os.path.join(rd, "SIGNOFF.pdf")
    elif doc == "report":
        srcs = [os.path.join(root, "REPORT.md"), os.path.join(root, "REPORT.tex")]
        # one history per checkpoint cycle (the newest round), so a notice from an earlier
        # Checkpoint C is not carried into a later one
        newest = newest_round(cfg)
        if not newest:
            raise DocError("no audit round found: the report is checked for the newest round")
        key, shown = f"report-{newest}", os.path.join(root, "REPORT.pdf")
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
        raise DocError(f"--doc must be signoff, questions, report, decisions or other:<abs path>, got {doc!r}")
    missing = [s for s in srcs if not os.path.exists(s)]
    if missing:
        raise DocError("source missing (render or write it first): " + ", ".join(missing))
    return key, srcs, shown


def newest_round(cfg):
    import audit_coverage
    rs = audit_coverage.order_rounds(project.rounds(cfg), project.REPO)
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
        h.update(os.path.basename(p).encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def readers_dir(cfg):
    return os.path.join(rounds_root(cfg), "readers")


def record_texts(rdir, use_git=True):
    """{file name: text} of every reader record and response file. With git, each committed file is
    read FROM THE COMMIT THAT ADDED IT: a later edit, rename or deletion can neither wash a finding
    away nor block the project (records are append-only by rule; this makes the rule hold by
    construction). Files not yet committed are read from disk (and refused by the gate)."""
    out = {}
    record_texts.unseen = []
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
    every split point of the line before its answer is a candidate quote."""
    got, bad = [], []
    for name in names:
        for l in texts[name].splitlines():
            m = RESPONSE_HEAD_RE.match(l)
            body = m.group(2) if m else ""
            parts = body.split(" — ")
            cands = [" — ".join(parts[:k]).strip() for k in range(1, len(parts))
                     if " — ".join(parts[k:]).strip()]
            if m and cands:
                got.append((m.group(1), cands))
            elif l.lstrip().startswith(("-", "*")) and l.strip() not in ("-", "*"):
                bad.append(f"{name}: {l.strip()[:80]}")
    return got, bad


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().strip('"“”`').lower()


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


def check(cfg, doc, round_name=None, check_git=True):
    """Problems preventing delivery (empty list = deliverable)."""
    try:
        key, srcs, _ = resolve(cfg, doc, round_name)
        rdir = readers_dir(cfg)
        texts = record_texts(rdir, use_git=check_git)
    except DocError as e:
        return [str(e)]
    files = reader_files(texts, key)
    if not files:
        return [f"no fresh-reader pass for {key}: run RUN.md 'Fresh-reader check'"]
    probs = history_problems(rdir, key) if check_git else []
    probs += [f"reader file tracked but not committed (commit it): {u}"
              for u in getattr(record_texts, "unseen", []) if key_file(key, u)]
    parsed = [(n, name, parse(name, texts[name])) for n, name in files]
    good = [(n, p, r) for n, p, r in parsed if not r["problems"]]
    if not good:
        return probs + [f"no well-formed pass for {key} (malformed: "
                        + ", ".join(p for _, p, _ in parsed) + ")"]
    newest_n, newest_p, newest = good[-1]
    if parsed[-1][0] != newest_n:
        probs.append(f"the newest reader file ({parsed[-1][1]}) is malformed: spawn a new "
                     f"reader on the same document (its findings must still be answered)")
    cur = content_hash(srcs, doc)
    if newest["sha"] != cur:
        probs.append(f"the document changed after its last well-formed pass ({newest_p} read "
                     f"{newest['sha'][:12]}…, the source is now {cur[:12]}…): run a new pass on this version")
    unfixable = []
    for n, p, r in parsed:
        # identical findings in one pass are one finding
        blocking = list(dict.fromkeys(t for k, t in r["findings"] if k == "BLOCKING"))
        uniq, seen = [], set()
        for f in blocking:
            if _norm(f) not in seen:
                seen.add(_norm(f)); uniq.append(f)
        resp, bad = responses(texts, response_names(texts, key, n))
        answers = [(kind, answered_set(cands, uniq)) for kind, cands in resp]
        for i, f in enumerate(uniq):
            hit = [kind for kind, ids in answers if i in ids]
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
                unfixable.append(f)
    if unfixable:
        kf = os.path.join(rounds_root(cfg), f"KNOWN_FAULTS-{key}.md")
        notice = open(kf, encoding="utf-8").read() if os.path.exists(kf) else None
        if notice is None:
            probs.append(f"{len(unfixable)} finding(s) marked unfixable: write {os.path.basename(kf)}, the "
                         f"notice delivered with the document, quoting each")
        else:
            for f in unfixable:
                if _norm(f)[:60] not in _norm(notice):
                    probs.append(f"{os.path.basename(kf)} does not quote the unfixable finding {f[:60]!r}")
    return probs


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
    ap.add_argument("--doc", help="signoff | questions | report | decisions | other:<absolute path>")
    ap.add_argument("--round", help="with --doc signoff/questions: the sheet's round "
                    "(`approved` = the round of the approval record)")
    ap.add_argument("--project")
    ap.add_argument("--hash", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--next", action="store_true")
    ap.add_argument("--save", action="store_true", help="read a reader record on stdin, save and commit it")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.doc or (a.hash + a.check + a.next + a.save) != 1:
        ap.error("give --doc and exactly one of --hash / --next / --check / --save")
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
    if a.save:
        path, probs = save(cfg, a.doc, a.round, sys.stdin.read())
        for p in probs:
            print(f"PROBLEM  {p}")
        if probs:
            print("record NOT saved" if path is None else f"record written to {path}, see above")
            return 1
        print(f"saved and committed {path}")
        return 0
    probs = check(cfg, a.doc, a.round)
    for p in probs:
        print(f"PROBLEM  {p}")
    for nt in history_notes(readers_dir(cfg), key):
        # harmless to the gate (records are read as first committed), but the human is told
        print(f"NOTE     reader record changed after its commit (shown to the human): {nt}")
    print(f"fresh-reader gate for {key}: {'OK' if not probs else 'REFUSED'}")
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
        reader(1, h1, "VERDICT: NO BLOCKING PROBLEMS", findings=("- NOT BLOCKING: style",))
        say("a clean pass on the delivered version: accepted", C() == [])
        put("v2\n")
        say("the document changed after its last pass: refused", any("changed after" in p for p in C()))
        h2 = put("v2\n")
        reader(2, h2, "VERDICT: BLOCKING PROBLEMS: 1", findings=(F1,))
        say("an unanswered blocking finding: refused", any("not answered" in p for p in C()))
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
        tc = _w(d, "c/REPORT.tex", "{\\small Generated 2026-10-13 from the audit records. Do not edit this file.}\nY\n")
        say("a generator-only change (the .tex differs) changes the report's hash",
            content_hash([a, ta], "report") != content_hash([a, tc], "report"))
        _w(d, "rr/REPORT.md", "r"); _w(d, "rr/REPORT.tex", "t")
        say("the report resolves to both its markdown and its LaTeX (generator changes count)",
            [os.path.basename(x) for x in resolve(cfg, "report")[1]] == ["REPORT.md", "REPORT.tex"])
        say("the report's history is per cycle (keyed by the newest round)", resolve(cfg, "report")[0] == f"report-{RN}")
        k1, _, _ = resolve(cfg, "other:" + _w(d, "rr/x/SUM.md", "s"))
        k2, _, _ = resolve(cfg, "other:" + _w(d, "rr/y/SUM.md", "s"))
        say("other documents get distinct keys", k1 != k2)
        say("an other: document outside the rounds directory is refused (a copy must not reset its history)",
            _raises(lambda: resolve(cfg, "other:" + _w(d, "elsewhere/SUM.md", "s"))))
        say("the sheet needs its round", _raises(lambda: resolve(cfg, "signoff")))
        _w(d, f"rr/{RN}/SIGNOFF.md", "m"); _w(d, f"rr/{RN}/SIGNOFF.tex", "t")
        say("the sheet hashes its rendered md and tex, not SIGNOFF.json",
            [os.path.basename(x) for x in (_try(lambda: resolve(cfg, "signoff", RN)) or ["", []])[1]]
            == ["SIGNOFF.md", "SIGNOFF.tex"])
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
        _w(uni, "Erdős/readers/k-1.md", "FIRSTVERSION\n"); gu("add", "-A"); gu("commit", "-qm", "reader k 1")
        _w(uni, "Erdős/readers/k-1.md", "edited\n"); gu("commit", "-qam", "edit")
        saved_a = project.AUDITS; project.AUDITS = uni
        try:
            tx_ = _try(lambda: record_texts(os.path.join(uni, "Erdős", "readers")))
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
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


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
    sys.exit(main())

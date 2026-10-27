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
item per thing the human must see, each with a hidden anchor. The writer fills in context, options
and a recommendation, may group items under one decision, but may not drop an anchor, and every
decision section must carry real content; `--check` refuses the document otherwise.

Answered items: once the human has answered an item at a checkpoint, record it in RUN_LOG.md under
`## Answered` as a line `- answered <anchor> (<date>, <round>): <answer>`, where <round> is the
round DECISIONS.md was written for. The next skeleton lists it under "Previously answered" instead
of asking again -- unless it was asked again since: a QUESTION or CHECK row in a LATER round
(rounds are ordered, not compared by date), or new content. Items whose content can change carry
a content hash in their anchor (`approval:<round>@<hash>`, `global:G1@<hash>`, ...), so a new
approval, new sheet text or new commits are a new item; the old answer is shown next to it.

  python3 audits/decisions.py --write   [--round R --allow-older] [--out PATH]   # skeleton: <rounds_dir>/DECISIONS.md
  python3 audits/decisions.py --check   [--round R --allow-older] [--file PATH]  # completeness gate before delivery
  python3 audits/decisions.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import argparse, glob, hashlib, json, os, re, shutil, tempfile

import project

FILL = "<<FILL"
ANCHOR_RE = re.compile(r"<!--\s*item:([A-Za-z0-9._:/@+-]+)\s*-->")
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
# what a delegated decision may follow (RUN.md, "How you decide"): an independent agent's written
# recommendation, or the conservative rule -- never a recommendation the operator wrote itself
FOLLOWED = ("adjudicator's recommendation", "conservative rule", "human at checkpoint b")
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


def split_row(line):
    """Cells of a markdown table row; `\\|` inside a cell is a literal bar, not a separator."""
    cells, cur, i, s = [], "", 0, line.strip().strip("|")
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"; i += 2; continue
        if s[i] == "|":
            cells.append(cur.strip()); cur = ""
        else:
            cur += s[i]
        i += 1
    cells.append(cur.strip())
    return cells


def table_rows(text):
    """[(header cells, row cells)] for every markdown table in text (separator rows skipped)."""
    out, header = [], None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            header = None
            continue
        cells = split_row(line)
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = [c.lower().strip("* ") for c in cells]
            continue
        out.append((header, cells))
    return out


def anchor_id(kind, text):
    """A stable, comment-safe anchor: `kind:<slug>` for short names, else `kind:<slug>-<hash>`."""
    t = text.strip()
    slug = re.sub(r"[^A-Za-z0-9._:/@+-]+", "_", t)[:80]
    if t and len(t) <= 80 and slug == t.replace(" ", "_"):
        return f"{kind}:{slug}"
    return f"{kind}:{slug[:40]}-{hashlib.sha1(t.encode()).hexdigest()[:10]}"


# churn that must not re-ask an item: Lean line citations, tex line citations, commit hashes (hex
# runs with both a letter and a digit -- "effaced" or "1000000" are content)
LEAN_CITE_RE = re.compile(r"\b[\w/]+\.lean:\d+(?:\s*[,–-]\s*:?\d+)*"
                          r"|\btex (?:l\.\s*~?|lines? )?\d+(?:\s*(?:[–-]|,)\s*\d+)*"
                          r"|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")


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


def versioned(kind, ident, content):
    """`kind:<ident>@<hash>`: an anchor that changes when the content does, so an answer to an
    earlier version does not hide the new one."""
    base = anchor_id(kind, ident)
    return f"{base}@{hashlib.sha1(str(content).encode()).hexdigest()[:8]}"


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
    out = {}
    for d in rounds:
        for header, cells in table_rows(_read(os.path.join(d, "ADOPTED.md"))):
            if "decision" not in header or "item" not in header or len(cells) < len(header):
                continue
            dec = cells[header.index("decision")]
            if not re.match(r"^\**\s*QUESTION\b", dec):
                continue
            item = cells[header.index("item")].strip("`")
            lane = cells[header.index("lane")] if "lane" in header else "?"
            reason = cells[-1]
            out.setdefault(item, []).append((os.path.basename(d), lane, reason))
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


def open_question_rows(cfg, rounds):
    """[(round, lane, item, reason, note)] for every QUESTION row of EVERY round's ADOPTED.md whose
    item has no final answer -- cumulative, not just the newest round's (a question carried from an
    earlier round used to vanish from the report when a later round raised none; Codex sparse-note
    run, 2026-10-19). Final answers are kept out: a `## Answered` line for the item's
    `question:<item>` anchor (unless the item was asked again after it), or a [DELEGATED] decision
    on that anchor; those are in DECISIONS.md and RUN_LOG.md. A [PROXY] answer is not final: the
    row stays, with a note. Rows are in round order."""
    root = os.path.join(project.REPO, cfg["rounds_dir"])
    log = _read(os.path.join(root, "RUN_LOG.md"))
    done = answered(log)
    deleg = {}
    for pre, tagged in delegated_entries(log):
        m = DELEGATED_TAG_RE.search(tagged) or re.search(r"(\d{4}-\d{2}-\d{2})", tagged)
        deleg[pre] = max(deleg.get(pre, ""), m.group(1) if m else "")
    order = [os.path.basename(d) for d in rounds]
    out = []
    for item, asks in question_rows(rounds).items():
        a = anchor_id("question", item)
        note = ""
        if a in done:
            line, when, ans_round = done[a]
            again = [x for x in asks if asked_after(order, x[0], ans_round, when)]
            if again:
                note, asks = f"answered earlier ({line[:120]}), asked again since", again
            elif PROXY_RE.search(line):
                note = "provisional [PROXY] answer, awaiting the human's confirmation"
            else:
                continue
        elif a.lower() in deleg:
            # a delegated decision is final -- unless a later round asked the question again
            # a [DELEGATED] tag carries a date, not a round: it answered the askings dated before it,
            # or (if none) the first asking of that day; a later round -- even the same day -- asking
            # it again is a re-ask (round order, as for answers)
            dd = deleg[a.lower()]
            idx = lambda r: order.index(r) if r in order else -1
            before = [x for x in asks if round_date(x[0]) < dd]
            same = sorted((x for x in asks if round_date(x[0]) == dd), key=lambda x: idx(x[0]))
            upto = max((idx(x[0]) for x in before + same[:1]), default=10 ** 9)
            again = [x for x in asks if idx(x[0]) > upto]
            if not again:
                continue
            note, asks = f"decided as [DELEGATED] on {deleg[a.lower()]}, asked again since", again
        out += [(r, l, item, why, note) for r, l, why in asks]
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


def round_date(name):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else ""


def approval(cfg):
    p = os.path.join(project.REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json")
    return json.load(open(p)) if os.path.exists(p) else None


def earlier_approvals(cfg):
    out = []
    for f in sorted(glob.glob(os.path.join(project.REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.*.json"))):
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
    return c["commits"] + [f"UNCOMMITTED: {p}" for p in c["dirty"]]


_real_changes_after = changes_after


ABBREV = ("e.g", "i.e", "resp", "cf", "al", "Obs", "Fig", "Thm", "Cor", "Lem", "Def", "Prop", "Eq",
          "Sec", "vs", "etc", "approx", "No")


def first_sentence(text, limit=240):
    """The first sentence: up to a full stop followed by a capital letter, but not after a common
    abbreviation ("e.g.", "resp.", "cf.", "Obs.") and never inside a `code span`; at most `limit`
    characters."""
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
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + " …"


def _idx(header, prefix):
    """Index of the first column whose header starts with `prefix`, else None. Prefix, as in
    make_report.record_table: SKIPPED.md's key column is headed "what is not formalized", and an
    exact match on "what" once left every skip out of the page-1 box, silently."""
    return next((k for k, h in enumerate(header) if h.startswith(prefix)), None)


def _col(header, cells, prefix):
    i = _idx(header, prefix)
    return cells[i] if i is not None and i < len(cells) else ""


def box_lines(cfg):
    """The entries the 'Read this first' box must list, from the record, each with a one-sentence
    summary a reader who stops on page 1 can understand (rule 5):
      defect N: <where> (<severity>): the paper says <printed text>; <what is wrong>. Consequence: ...
      not formalized: <what>: <reason>
      proof route <R>: <result> (<kind>): <why different>
      vacuous: <statement> (for <parameters>): <decision>"""
    root = os.path.join(project.REPO, cfg["rounds_dir"])
    out = []
    for header, cells in table_rows(_read(os.path.join(root, "PAPER_DEFECTS.md"))):
        if "severity" in header and len(cells) >= 3:
            said, why, cons = _col(header, cells, "what"), _col(header, cells, "why"), _col(header, cells, "consequence")
            parts = []
            if said:
                parts.append("the paper says " + first_sentence(said, 140))
            if why:
                parts.append(first_sentence(why))
            summ = ". ".join(x.rstrip(".") for x in parts) + "." if parts else ""
            summ += f" Consequence: {first_sentence(cons)}" if cons else ""
            out.append(f"defect {cells[0]}: {cells[1]} ({cells[header.index('severity')].strip('*')})"
                       + (f": {summ}" if summ else ""))
    for header, cells in table_rows(_read(os.path.join(root, "SKIPPED.md"))):
        if _idx(header, "what") is not None and len(cells) > _idx(header, "what"):
            reason = _col(header, cells, "reason")
            out.append(f"not formalized: {cells[_idx(header, 'what')]}"
                       + (f": {first_sentence(reason)}" if reason else ""))
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
    return out


FIELDS = ("**Paper** (location in the source, quoted where wording matters): " + FILL + " >>\n\n"
          "**Lean** (declaration and File.lean:N at the document's commit): " + FILL + " >>\n\n"
          "**Evidence** (file paths, commands and exit status): " + FILL + " >>\n\n"
          "**Options, and what each changes** (re-approval? new round?): " + FILL + " >>\n\n"
          "**Recommendation:** " + FILL + " >>\n")
# the sixth field of every decision section when the involvement level delegates Checkpoint C
DECIDED_FIELD = ("\n**Decision taken** (what was done, quoting its tag from RUN_LOG.md, and how to reverse it; "
                 "'Not applicable: <why>' only where the human decided it at Checkpoint B): " + FILL + " >>\n")


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
    that is not in the canonical form, or names another level than the configured one."""
    out = []
    for line in strip_sections(log, ("Fresh readers",)).splitlines():
        for m in DELEGATED_LOOSE_RE.finditer(line):
            c = DELEGATED_TAG_RE.match(line, m.start())
            if not c:
                out.append(f"RUN_LOG.md: {m.group(0)[:70]!r} is not a canonical [DELEGATED] tag "
                           f"('[DELEGATED <date>, operator under <level> (intake); reversal: "
                           f"{' | '.join(REVERSAL_COSTS)}]'): {line.strip()[:80]!r}")
            elif level and c.group(2) != level:
                out.append(f"RUN_LOG.md: a [DELEGATED] tag names the level {c.group(2)!r}, but the run's "
                           f"level is {level!r}: {line.strip()[:80]!r}")
        if PROXY_RE.search(line) and DELEGATED_LOOSE_RE.search(line):
            out.append(f"RUN_LOG.md: one line carries both a [PROXY] and a [DELEGATED] tag; a decision is "
                       f"one or the other: {line.strip()[:80]!r}")
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
            f"hypotheses; assume missing theory as a named hypothesis), and recorded it in "
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
    anchors, items, prev = [], [], []
    names = {}
    order = [os.path.basename(d) for d in rounds]

    def later(asked_round, ans_round, ans_date):
        return asked_after(order, asked_round, ans_round, ans_date)

    pending = []

    def add(anchor, title, body, mention=None, asked=()):
        """`mention`: text a section carrying this anchor must show (None: no requirement);
        `asked`: the rounds that asked it, so an older answer does not hide a newer asking.
        Items are settled in finish(), once every current anchor is known."""
        pending.append((anchor, title, body, mention, asked))

    def finish():
        current = {p_[0] for p_ in pending}
        for anchor, title, body, mention, asked in pending:
            if anchor in done:
                line, when, ans_round = done[anchor]
                if not any(later(a, ans_round, when) for a in asked):
                    prev.append(f"- `{anchor}` — {title}: {line}")
                    continue
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
            anchors.append(anchor)
            if mention:
                names[anchor] = mention
            items.append(f"### {title}\n<!-- item:{anchor} -->\n\n{body}\n")
        # an answer line naming no current item and no family: probably a mistyped anchor
        fams = {a.rsplit("@", 1)[0] + "@" for a in current if "@" in a}
        stray = [k for k in done if k not in current and not any(k.startswith(f) for f in fams)]
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
                 FILL + ": one row per decision section below (keep a row for each); 'Followed' is "
                 "adjudicator's recommendation, conservative rule, or human at Checkpoint B; 'Reversal "
                 "cost' is " + ", ".join(REVERSAL_COSTS) + " (not applicable for the human's). >>\n",
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
    by = (appr or {}).get("by")
    who = {"human": "approved by a human", "agent": "approved by the AGENT, not by a human"}.get(
        by, "approver NOT RECORDED" if appr else "NOT APPROVED")
    excl = [l for l, r in (appr or {}).get("rows", {}).items() if r.get("status") == "excluded"]
    hist = earlier_approvals(cfg)
    body = (f"Sheet: `{os.path.relpath(os.path.join(sd, 'SIGNOFF.pdf'), project.REPO) if sd else '?'}`."
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
                asked=(os.path.basename(sd),) if sd else ())
    for nf in so.get("not_formalized", []):
        add(versioned("notformalized", str(nf.get("result")), nf.get("note", "")), f"Not formalized: {nf.get('result')}",
            f"Record: {nf.get('note', '')}\n\n" + FIELDS, mention=str(nf.get("result")))
    # 3. QUESTION rows of every round, grouped by identical reason for the writer's convenience
    qs = question_rows(rounds)
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
                asked=tuple(r for r, _, _ in qs[it_]))
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
                "Run log:\n\n" + "\n".join("> " + l for l in b.splitlines()) + "\n\n" + FIELDS,
                mention="[PROXY")
    # every [DELEGATED] decision: an item the reader must SEE, already decided (not a question);
    # those recorded as answers to a decisions document (Checkpoint C, Answered) are not new items
    for b in log_entries(strip_sections(log, DELEGATED_SKIP_SECTIONS)):
        if DELEGATED_RE.search(b) and "(answered" not in b:
            tagged = [l for l in b.splitlines() if DELEGATED_RE.search(l)]
            key = "\n".join(l.strip() for l in tagged)
            first = tagged[0][DELEGATED_RE.search(tagged[0]).start():]
            add(anchor_id("delegated", key), f"Decision delegated at intake: {first.strip()[:110]}",
                "Run log:\n\n" + "\n".join("> " + l for l in b.splitlines()) + "\n\n" + FIELDS,
                mention="[DELEGATED")
    for b in log_entries(section(log, "Open questions")):
        if not PROXY_RE.search(b) and not DELEGATED_RE.search(b) and "(answered" not in b:
            add(anchor_id("open", b), f"Open question: {b.splitlines()[0].lstrip('- ')[:100]}",
                "Run log:\n\n" + "\n".join("> " + l for l in b.splitlines()) + "\n\n" + FIELDS)
    # 5. standing defers: configured ones (is the reason still true?) and proposed ones
    for sdf in cfg.get("standing_defers", []):
        add(versioned("defer", str(sdf.get("id")), json.dumps(sdf, sort_keys=True)), f"Standing rule `{sdf.get('id')}` in the audit configuration",
            f"Item: {sdf.get('item')}. Reason recorded: \"{sdf.get('reason')}\". "
            f"Revisit: {sdf.get('revisit_when')}. Is the reason still true?\n\n" + FIELDS, mention=str(sdf.get("id")))
    for rule, rs in sorted(proposed_standing(rounds, cfg).items()):
        add(anchor_id("proposed-defer", rule), f"Proposed standing rule `{rule}` (used by adjudicators, not configured)",
            f"Invoked in rounds: {', '.join(rs)}. Add it to the project config, or have the deferred "
            f"items fixed now?\n\n" + FIELDS, mention=rule)
    # paper defects and vacuous statements: each gets its detailed entry (rule 5)
    for header, cells in table_rows(_read(os.path.join(root, "PAPER_DEFECTS.md"))):
        if "severity" in header and len(cells) >= len(header):
            # hashed: where, severity, the printed text, why it is wrong, and the consequence (what
            # the human decides on: "the main results survive" turning into "Theorem 1.1 fails")
            # identity: the row number (rows are never removed) plus the location without citations
            add(versioned("defect", f"{cells[0]}-" + LEAN_CITE_RE.sub("", cells[1]).strip()[:60],
                          defining(header, cells, ("where", "severity", "what", "why", "consequence"))),
                f"Paper defect {cells[0]}: {cells[1][:90]}",
                f"Record (PAPER_DEFECTS.md row {cells[0]}): " + " | ".join(cells[1:])[:900] + "\n\n" + FIELDS,
                mention=(NUM_RE.search(cells[1]).group(0) if NUM_RE.search(cells[1]) else cells[1][:30]))
    for header, cells in table_rows(_read(os.path.join(root, "VACUOUS.md"))):
        if _idx(header, "statement") is not None and len(cells) >= len(header):
            if "status" in header and is_repaired(cells[header.index("status")]):
                continue
            st = cells[_idx(header, "statement")]
            add(versioned("vacuous", f"{cells[0]}-{st}", defining(header, cells, ("statement", "for which", "param", "why",
                                                                   "decision", "status"))),
                f"True only vacuously: {st[:90]}",
                "Record (VACUOUS.md): " + " | ".join(cells)[:900] + "\n\n" + FIELDS,
                mention=(NUM_RE.search(st).group(0) if NUM_RE.search(st) else st[:30]))
    # skips and route changes listed in the box: each gets its detailed entry too (rule 5)
    for header, cells in table_rows(_read(os.path.join(root, "SKIPPED.md"))):
        if _idx(header, "what") is not None and len(cells) > _idx(header, "what"):
            what = cells[_idx(header, "what")]
            label = re.sub(r"\*\*", "", what).split("(")[0].strip()[:60]
            add(versioned("skip", f"{cells[0]}-{label}", defining(header, cells, ("what", "reason"))), f"Not formalized: {label}",
                "Record (SKIPPED.md): " + " | ".join(cells)[:900] + "\n\n" + FIELDS,
                mention=(NUM_RE.search(label).group(0) if NUM_RE.search(label) else label[:30]))
    for header, cells in table_rows(_read(os.path.join(root, "DEVIATIONS.md"))):
        if _idx(header, "kind") is not None and len(cells) > _idx(header, "kind"):
            kind = cells[_idx(header, "kind")].strip("* ").lower()
            if kind and kind not in ("same strength", "reading choice"):
                res = cells[header.index("result")] if "result" in header else cells[0]
                add(versioned("route", f"{cells[0]}-{res}", defining(header, cells, ("result", "the paper", "the lean", "why", "kind"))),
                    f"Proof route: {res} ({kind})",
                    "Record (DEVIATIONS.md): " + " | ".join(cells)[:900] + "\n\n" + FIELDS,
                    mention=(NUM_RE.search(res).group(0) if NUM_RE.search(res) else res[:30]))
    # 6. the last round's UNCOVERED rows (RUN.md Stage 5 step 1 lists them for the human)
    unc = [(cells[header.index("lane")] if "lane" in header else "?",
            cells[header.index("item")] if "item" in header else cells[0])
           for header, cells in table_rows(_read(os.path.join(last_round, "ADOPTED.md")))
           if "decision" in header and "item" in header and len(cells) >= len(header)
           and re.match(r"^\**\s*UNCOVERED\b", cells[header.index("decision")])]
    if unc:
        add(anchor_id("uncovered", os.path.basename(last_round)),
            f"Items no audit lane examined in the last round ({len(unc)} UNCOVERED rows)",
            "Rows (lane, item):\n\n" + "\n".join(f"- {c[0]}: {c[1]}" for c in unc[:200])
            + ("\n- …" if len(unc) > 200 else "") + "\n\n" + FIELDS)
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
    # items the HUMAN decided at Checkpoint B (statements-only, approved by a human): the only
    # sections whose Decision taken may say "Not applicable"
    human_b = set()
    if project.involvement(cfg) == "statements-only" and (appr or {}).get("by") == "human":
        # ... except what RUN_LOG.md records as delegated (an anchor decided at Checkpoint C)
        deleg_anchors = {p_ for p_, _ in delegated_entries(log)}
        human_b = {a for a in anchors if a.split(":", 1)[0] in ("approval", "global", "check")
                   and a.lower() not in deleg_anchors and a.rsplit("@", 1)[0].lower() not in deleg_anchors}
    skeleton.human_decided = human_b
    if deleg:
        glance = [f"| {re.sub(r'[|]', '/', t[4:].split(chr(10), 1)[0])[:90]} | {FILL} >> | {FILL} >> | {FILL} >> |"
                  for t in items]
        head = [h if h != "@@GLANCE@@" else "\n".join(glance) for h in head]
    return "\n".join(head + ["## Decisions\n"] + items + tail), anchors


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
          human_decided=()):
    """Problems of a filled decisions document. `level` is the involvement level chosen at intake;
    a delegating one (statements-only, hands-off) also requires the "Decisions taken on your behalf"
    framing, the verbatim intake `answer`, the DISCLOSURE sentence, and in every decision section a
    filled **Decision taken** field that shows "[DELEGATED" (unless it says why it does not apply)."""
    probs = []
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
                probs.append(f"the summary table has {len(rows_gl)} row(s) for {n_sec} decision section(s)")
            for c in rows_gl:
                fol = c[2].strip("* ").lower() if len(c) > 2 else ""
                cost = c[3].strip("* ").lower() if len(c) > 3 else ""
                if not any(fol.startswith(x) for x in FOLLOWED):
                    probs.append(f"summary row {c[0][:40]!r}: 'Followed' must be one of {', '.join(FOLLOWED)}")
                elif cost not in REVERSAL_COSTS and not (fol.startswith("human") and cost == "not applicable"):
                    probs.append(f"summary row {c[0][:40]!r}: 'Reversal cost' must be one of {', '.join(REVERSAL_COSTS)}")
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
                rec = f.get("recommendation", "")
                if not re.search(r"conservative rule", rec, re.I) and not (
                        re.search(r"adjudicator", rec, re.I) and re.search(r"\d{4}-\d{2}-\d{2}-", rec)
                        and "ADOPTED" in rec):
                    probs.append(f"section {h.strip()!r}: under the {level} level the Recommendation cites "
                                 f"its source: the adjudicator's row (round and ADOPTED.md) it follows, or "
                                 f"the words 'conservative rule' (never a recommendation the operator wrote)")
    for a, k in placed.items():
        h, b = secs[k]
        need = (names or {}).get(a)
        shown = (h + b).lower()
        if need and not mentions(need, shown):
            probs.append(f"section {h.strip()!r} carries anchor {a} but never mentions {need!r}")
    return probs


def record_problems(cfg):
    """Record faults that would hide or blur an item: a VACUOUS.md status that is neither open nor
    'repaired in <commit>'; a [PROXY] tag under `## Answered` that is neither the start of the
    answer nor quoted (is it a proxy decision, or a quotation of one?)."""
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
    if project.delegates(cfg):
        for line in strip_sections(log, ("Fresh readers",)).splitlines():
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
                out.append(f"VACUOUS.md: status {st!r} is neither 'open' nor 'repaired in <commit>' "
                           f"(the row is treated as open)")
    return out


def resolve_round(cfg, wanted, allow_older):
    import audit_coverage
    rounds = audit_coverage.order_rounds(project.rounds(cfg), project.REPO)
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
    probs = check(open(target, encoding="utf-8").read(), anchors, os.path.basename(last),
                  [f"> - {bl}" for bl in box_lines(cfg)], skeleton.names, project.involvement(cfg),
                  cfg.get("involvement_answer") if project.delegates(cfg) else None,
                  skeleton.human_decided) + record_problems(cfg)
    for p in probs:
        print(f"PROBLEM  {p}")
    print(f"decisions check: {len(anchors)} required item(s), {len(probs)} problem(s)")
    return 1 if probs else 0


def selftest():
    results = []
    def say(name, ok):
        results.append(ok); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    tmp = tempfile.mkdtemp(prefix="decisions-")
    try:
        _selftest(tmp, say)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "ok" if all(results) else "FAILED")
    return 0 if all(results) else 1


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
        "| # | where | severity | what |\n|---|---|---|---|\n| 1 | tex 654 | **S4** | `hd = \\|i\\|` swapped |\n")
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
        na_opt = re.sub(r"(\*\*Options, and what each changes\*\* \(re-approval\? new round\?\): )x+",
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
        open(pdp_, "w").write("| # | where | severity | what the paper says | why it is wrong | consequence |\n|---|---|---|---|---|---|\n"
                              "| 1 | tex 9 | S1 | PRINTED-TEXT | WHY-SUMMARY here. More. | MAIN RESULTS SURVIVE. Detail. |\n")
        open(pdp_, "a").write("")
        try:
            bl_ = box_lines(cfg)
        finally:
            open(pdp_, "w").write(pd_o)
        say("a defect's box line quotes the printed text and says what is wrong (one sentence each)",
            any("the paper says PRINTED-TEXT. WHY-SUMMARY here." in b and "More" not in b
                and "Consequence: MAIN RESULTS SURVIVE." in b and "Detail" not in b for b in bl_))
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
        say("the box summary of a defect is the first sentence of what is wrong (not cut at e.g.)",
            first_sentence("(i,j) is (row, column) (e.g. tex 1026) so rows swap. More here.")
            == "(i,j) is (row, column) (e.g. tex 1026) so rows swap." and len(first_sentence("x " * 300)) <= 242)
        say("split_row keeps an escaped bar inside a cell", split_row(r"| a | x = \|i\| | b |") == ["a", "x = |i|", "b"])
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
        appr_a = next(x for x in anchors if x.startswith("approval"))
        later_a = next(x for x in anchors if x.startswith("after-last-round"))
        glob_a = next(x for x in anchors if x.startswith("global:G1"))
        tq, aq = with_log(f"- answered {appr_a} (2026-01-03, {os.path.basename(r2)}): ok\n"
                          f"- answered {later_a} (2026-01-03, {os.path.basename(r2)}): ok\n"
                          f"- answered {glob_a} (2026-01-03, {os.path.basename(r2)}): ok\n")
        say("answered approval, later changes and global difference are not asked again",
            not ({appr_a, later_a, glob_a} & set(aq)))
        ap_p = os.path.join(rr, "APPROVED_FINGERPRINTS.json")
        ap_old = open(ap_p).read()
        json.dump(dict(json.loads(ap_old), date="2026-01-09", by="human"), open(ap_p, "w"))
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
            defining(["where", "severity", "what the paper says", "lean witness"],
                     ["tex 1", "S4", "says X (Section4.lean:563, :565)", "w.lean:9"], ("where", "severity", "what"))
            == defining(["where", "severity", "what the paper says", "lean witness"],
                        ["tex 1", "S4", "says X (Section4.lean:12, :14)", "w.lean:10"], ("where", "severity", "what"))
            and defining(["where", "severity", "what the paper says"], ["tex 1", "S4", "says Y"], ("where", "severity", "what"))
            != defining(["where", "severity", "what the paper says"], ["tex 1", "S4", "says X"], ("where", "severity", "what")))
        recs = {"PAPER_DEFECTS.md": ("| 1 | tex 654 | **S4** | `hd = \\|i\\|` swapped |", "| 1 | tex 654 | **S4** | `hd = \\|j\\|` swapped |"),
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
        pdp = os.path.join(rr, "PAPER_DEFECTS.md"); pd_old = open(pdp).read()
        open(pdp, "w").write("| # | where | severity | what | lean witness |\n|---|---|---|---|---|\n"
                             "| 1 | tex 654 | S4 | swapped | `w` (Basic.lean:240) |\n")
        try:
            w1 = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")}
            cur_pd = open(pdp).read()
            open(pdp, "w").write(cur_pd.replace("`w` (Basic.lean:240)", "`w2`, re-checked"))
            w2 = {x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")}
        finally:
            open(pdp, "w").write(pd_old)
        say("changing a non-defining column (the Lean witness) keeps the defect's anchor", w1 and w1 == w2)
        open(pdp, "w").write("| # | where | severity | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | S4 | swapped | rows | `w` | main results survive |\n")
        try:
            c1 = [x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")]
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {c1[0] if c1 else 'none'} (2026-01-05, {os.path.basename(r2)}): ok\n")
            cur_pd = open(pdp).read()
            open(pdp, "w").write(cur_pd.replace("main results survive", "Theorem 1.1 fails"))
            tc2, c2 = skeleton(cfg, rounds, r2)
            open(pdp, "w").write(cur_pd.replace("tex 654", "tex 656"))
            tc3, c3 = skeleton(cfg, rounds, r2)
        finally:
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        open(pdp, "w").write("| # | where | severity | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | S4 | swapped | rows | `w` | main results survive |\n")
        try:
            v1 = next((x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")), "none")
            cur_pd = open(pdp).read()
            open(pdp, "w").write(cur_pd.replace("main results survive", "v2"))
            v2 = next((x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")), "none")
            open(pdp, "w").write(cur_pd.replace("main results survive", "v3"))
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(
                log + f"- answered {v2} (2026-01-02, {os.path.basename(r1)}): LATER-ANSWER\n"
                f"- answered {v1} (2026-01-01, {os.path.basename(r0)}): EARLIER-ANSWER\n")
            tv3, _ = skeleton(cfg, rounds, r2)
        finally:
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        open(pdp, "w").write("| # | where | severity | what | why | lean witness | consequence |\n|---|---|---|---|---|---|---|\n"
                             "| 1 | tex 654 | S4 | a | b | `w` | c1 |\n| 2 | tex 1028 | S4 | d | e | `w` | c2 |\n")
        try:
            dd = sorted(x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:"))
            cur_pd = open(pdp).read()
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {dd[0] if dd else 'x'} (2026-01-05, {os.path.basename(r2)}): DEFECT-ONE-ANSWER\n")
            open(pdp, "w").write(cur_pd.replace("| c1 |", "| c1 changed |"))
            tdd, _ = skeleton(cfg, rounds, r2)
        finally:
            open(pdp, "w").write(pd_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        items_dd = tdd.split("## Decisions", 1)[1].split("## How to answer")[0]
        say("two defects located only by tex lines are distinct items; one's answer is not shown on the other",
            len(set(dd)) == 2 and items_dd.count("DEFECT-ONE-ANSWER") == 1)
        say("tex citation forms (lists, 'tex line N') are stripped from identities and hashes",
            defining(["what"], ["see tex 654, 660 and tex line 12"], ("what",)) == defining(["what"], ["see tex 1, 2 and tex line 3"], ("what",)))
        vp_ = os.path.join(rr, "VACUOUS.md")
        hdr_v = "| # | statement | for which parameters | why | decision and reasoning | status |\n|---|---|---|---|---|---|\n"
        vset = []
        try:
            for row_ in ("| 1 | Lemma 4.10 | all | W1 | D1 | open |", "| 1 | Lemma 4.10 | all | W2 | D1 | open |",
                         "| 1 | Lemma 4.10 | all | W1 | D2 | open |"):
                open(vp_, "w").write(hdr_v + row_ + "\n")
                vset.append({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("vacuous:")})
        finally:
            os.remove(vp_)
        try:
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all | W1 | D1 | open |\n")
            v_old = next(iter({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("vacuous:")}), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {v_old} (2026-01-05, {os.path.basename(r2)}): FAM2-ANSWER\n")
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all | W1 | D9 | open |\n| 1 | Lemma 4.10 | m=2 | W1 | D9 | open |\n")
            tfam, _ = skeleton(cfg, rounds, r2)
        finally:
            os.remove(vp_); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        try:
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all | W1 | D1 | open |\n")
            v1_ = next(iter({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("vacuous:")}), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(log + f"- answered {v1_} (2026-01-05, {os.path.basename(r2)}): ROW1-ANS\n")
            open(vp_, "w").write(hdr_v + "| 1 | Lemma 4.10 | all | W1 | D9 | open |\n| 2 | Lemma 4.10 | m=2 | W1 | D1 | open |\n")
            tnum, _ = skeleton(cfg, rounds, r2)
        finally:
            os.remove(vp_); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("two vacuous rows about the same statement are separate families (row numbers in the identity)",
            "one of 2 items" not in tnum and "ROW1-ANS" in tnum)
        say("an earlier answer whose family now has several current items is shown on each, saying so",
            tfam.count("FAM2-ANSWER") >= 2 and "one of 2 items" in tfam)
        say("a vacuous row's reason and decision are hashed (each change is a new item)",
            all(vset) and vset[0] != vset[1] and vset[0] != vset[2])
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
        hdx = "| # | where | severity | what | why it is wrong | consequence |\n|---|---|---|---|---|---|\n"
        dsets = []
        try:
            for row_ in ("| 1 | tex 3 | S1 | x | W1 | c |", "| 1 | tex 3, Theorem 9 | S1 | x | W1 | c |", "| 1 | tex 3 | S1 | x | W2 | c |"):
                open(pdx, "w").write(hdx + row_ + "\n")
                dsets.append({x for x in skeleton(cfg, rounds, r2)[1] if x.startswith("defect:")})
            open(pdx, "w").write(hdx + "| 1 | tex 3 | S1 | x | W1 | c |\n")
            d0 = next(iter(dsets[0]), "x")
            open(os.path.join(rr, "RUN_LOG.md"), "w").write(
                log + f"- answered {d0} (2026-01-02, {os.path.basename(r1)}): ANS-R1\n")
            open(pdx, "w").write(hdx + "| 1 | tex 3 | S1 | x | W9 | c |\n")
            ts_, _ = skeleton(cfg, rounds, r2)
        finally:
            open(pdx, "w").write(pdx_old); open(os.path.join(rr, "RUN_LOG.md"), "w").write(log)
        say("a defect's location and reason are hashed", all(dsets) and dsets[0] != dsets[1] and dsets[0] != dsets[2])
        say("an answer to an earlier version of a current item is not also listed as stray",
            "ANS-R1" in ts_ and "matches no current item" not in ts_)
        say("the first sentence is not cut at 'e.g.' followed by a capital",
            first_sentence("Wrong (e.g. Lemma 3 fails). Second.") == "Wrong (e.g. Lemma 3 fails).")
        say("hashing is case-insensitive", defining(["what"], ["ABC"], ("what",)) == defining(["what"], ["abc"], ("what",)))
        say("the earlier-version note shows the LATEST earlier answer (by round order)",
            "LATER-ANSWER" in tv3 and "EARLIER-ANSWER" not in tv3.split("## Decisions", 1)[1].split("## Previously")[0])
        say("a defect whose consequence changes is asked again, with the earlier answer shown",
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
            "### Open question: [DELEGATED" not in items_h)
        say("[DELEGATED] answers under Checkpoint C / Answered are not new items",
            "CCDGQZ" not in items_h.split("## Previously answered")[0] and "check:Lemma_1.8" not in ah)
        say("delegated_decisions counts a Checkpoint C answer written twice once",
            len(dd) == 3 and sum("CCDGQZ" in t for t in dd) == 1)
        say("a [DELEGATED] decision under the involved level is a record problem; under hands-off it is not",
            any("[DELEGATED]" in p_ and "'involved'" in p_ for p_ in rp_inv)
            and not any("[DELEGATED]" in p_ for p_ in rp_h))
        say("a delegated skeleton is headed 'Decisions taken on your behalf', quotes the intake answer and "
            "the disclosure, and every section has a 'Decision taken' field",
            th.startswith("# Decisions taken on your behalf") and "ANSWERQZ" in th
            and DISCLOSURE["hands-off"] in th and th.count("\n**Decision taken** (") == len(ah))
        DT = ("[DELEGATED 2026-01-06, operator under hands-off (intake); reversal: none] kept, as the "
              "conservative rule says; to reverse it, ask")
        GL_FILL = "| " + FILL + " >> | " + FILL + " >> | " + FILL + " >> |"
        hfill = re.sub(re.escape(FILL) + r".*?>>", DT, th.replace(GL_FILL, "| kept | conservative rule | none |"), flags=re.S)
        hc = lambda d, lvl="hands-off", ans="(c) hands-off, ANSWERQZ", hd=(): check(
            d, ah, os.path.basename(r2), (), namesh, lvl, ans, hd)
        say("a filled delegated document passes", hc(hfill) == [])
        k_ = hfill.find("\n**Decision taken** (") + 1
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
            return re.sub(r"(\*\*Decision taken\*\*.*?\): ).*", lambda m: m.group(1) + val, sec)
        untagged = hfill[:k1] + set_dt(sec1, "the operator kept everything, as the conservative rule says; to reverse, ask") + hfill[e1:]
        say("a delegated section whose 'Decision taken' does not show the canonical tag fails",
            any("canonical" in p_ for p_ in hc(untagged)))
        # adversarial (hands-off review, A1): the tag only in the quoted run log, not in the field
        dsec_k = hfill.find("### Decision delegated at intake")
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
        say("the delegated skeleton opens with an at-a-glance table, one row per decision section",
            GLANCE_HEADING in th and th.index(GLANCE_HEADING) < th.index("## Background")
            and th.count(GL_FILL) == len(ah))
        row_ok = "| kept | conservative rule | none |"
        say("a summary table with an unknown 'Followed' or cost, or missing rows, fails",
            any("'Followed'" in p_ for p_ in hc(hfill.replace(row_ok, "| kept | my judgement | none |", 1)))
            and any("'Reversal cost'" in p_ for p_ in hc(hfill.replace(row_ok, "| kept | conservative rule | reversible |", 1)))
            and any("row(s) for" in p_ for p_ in hc(re.sub(r"\n\|[^\n]*\| kept \| conservative rule \| none \|", "", hfill, count=1))))
        say("a delegated document without the at-a-glance table fails",
            any("no summary table" in p_ for p_ in hc(hfill.replace(GLANCE_HEADING, "## Summary"))))
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
        import audit_coverage
        saved_order = audit_coverage.order_rounds
        audit_coverage.order_rounds = lambda rs, repo: sorted(rs)
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
            project.select, audit_coverage.order_rounds = saved_sel, saved_order
    finally:
        project.REPO, g["changes_after"] = saved


if __name__ == "__main__":
    sys.exit(main())

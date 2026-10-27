#!/usr/bin/env python3
"""The PDFs a human reads, rendered and verified by fresh agents (approver, 2026-10-23; PDF-AGENTS).

WHAT THIS IS.  The generators write markdown only (SUMMARY.md and REPORT.md by make_report.py, SIGNOFF.md by
signoff.py render). Once a document's markdown is audited at its current hash (its fresh-reader gate passes;
for the hands-off sheet `signoff.py check`), fresh agents turn it into a PDF (approver, 2026-10-23):

  * A, the renderer, makes a PDF of the md by any engine, layout or method, faithful to the md and readable (it
    may rephrase or re-lay out for readability, never change the mathematics; Lean code character for character);
  * B, the verifier, reads the whole md and every page and says PASS or FAIL (BLOCKING findings);
  * when B passes a round, two fresh independent checkers judge only whether the PDF says mathematically the same
    thing as the md (SAME or DIFFERENT); a DIFFERENT sends its findings back to A as a normal round, then B, then
    a fresh checker pair;
  * all of it inside one budget of BUDGET renderer rounds per version of the md; once it is spent, the least bad
    round ships, A adding a first page that lists every remaining objection (B's and the checkers') verbatim, a
    fresh verifier checking that cover (its verdict recorded; an unverified cover never ships), and the md is
    delivered beside it as the authoritative text.

This script only keeps the books. It never opens, reads or parses a PDF: it copies files, hashes them, checks
the agents' output FORMAT, and commits each step alone (`render <key> ...`), as readers.py --save does. The one
guard (check) is a fingerprint: the delivered PDF is the recorded one, and it was made from the md as it is
now. It runs in project.py --deliver and in signoff.py approve --by human.

NEVER A STOP.  Nothing here opens a stop or asks a human, in any mode. The loop is bounded (BUDGET renderer rounds, each
with at most one verifier and one checker pair, then at most COVER_TRIES cover attempts, each a cover and its
verifier); an agent that crashes or ends without saving is recorded with `fail`, and its
step counts as done (a failed A round counts toward the budget; a missing B verdict leaves its round unverified;
a checker that did not run is disclosed as such, never looped on; when no cover passes its verifier, the least
bad PDF ships without one, disclosed). `next` always
reaches an outcome, `no-pdf` included (the md ships alone, disclosed). When the md changes (a new prepare, an
approval stamp), the loop starts again from round 1 for the new md, with a fresh budget: rendering never
changes the md (SUMMARY.md and REPORT.md carry one static sentence about the PDF; the outcome is never a stop or
a disclosure record), so there is no feedback loop.

RECORDS.  `<rounds dir>/pdf/<key>/RENDER.json` (key SUMMARY, REPORT or SIGNOFF-<round>), and per version v of
the md `pdf/<key>/v<v>/`: `r<k>/` (A's prompt, PDF and source; B's prompt and verdict; the round's checker pair's
prompts and verdicts `check-<n>.md`), `cover/t<t>/` (each cover attempt's prompt, PDF, and its verifier's prompt
and verdict `check.md`). Every file is committed (integrity: owned by `render ` commits), so a restart, or
least-bad, can always reach every round's PDF. The agents work in `.formalization-work/render/<key>/v<v>/...`
(git-excluded); `save` copies what they made into the record.

  python3 audits/render_record.py next   --doc SUMMARY|REPORT|SIGNOFF [--round R|approved]
  python3 audits/render_record.py begin  --doc ... [--round ...]
  python3 audits/render_record.py save   --doc ... [--round ...] --role A|B|cover|cover-check|checker [--n 1|2] < output
  python3 audits/render_record.py fail   --doc ... [--round ...] --role A|B|cover|cover-check|checker [--n 1|2] --why "..."
  python3 audits/render_record.py finish --doc ... [--round ...]
  python3 audits/render_record.py check  --doc ... [--round ...]
  python3 audits/render_record.py shown  --doc SIGNOFF --round R     (right before the human is asked)
  python3 audits/render_record.py status [--doc ...]
  python3 audits/render_record.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import argparse, datetime, hashlib, json, os, re, shutil, subprocess, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

DOCS = ("SUMMARY", "REPORT", "SIGNOFF")
BUDGET = 6              # A-B rounds per version of the md
RECORD = "RENDER.json"
PDF_DIR = "pdf"
OUTCOMES = ("verified", "checkers-did-not-run", "least-bad", "no-pdf")
DONE_RE = re.compile(r"^\s*RENDER_DONE\s+(\{.*\})\s*$")
SHA_LINE = {"md": re.compile(r"^md_sha256:\s*([0-9a-f]{64})\s*$"), "pdf": re.compile(r"^pdf_sha256:\s*([0-9a-f]{64})\s*$")}
PAGES_RE = re.compile(r"^pages:\s*read\s+(\d+)\s+of\s+(\d+)\s*$")
FIND_RE = re.compile(r"^\s*-\s*(BLOCKING|MINOR):\s*(.*)$")
B_VERDICT = re.compile(r"^VERDICT:\s*(PASS|FAIL \(([1-9]\d*)\))$")
C_VERDICT = re.compile(r"^VERDICT:\s*(SAME|DIFFERENT \(([1-9]\d*)\))$")
SOURCE_MAX = 4 * 1024 * 1024    # bytes of A's source kept in the record
COVER_TRIES = 2         # cover attempts (each: a fresh A makes it, a fresh verifier checks it) before shipping without


class Refused(Exception):
    pass


# --- where things are --------------------------------------------------------------------------------------
def root(cfg):
    return os.path.normpath(os.path.join(project.REPO, cfg["rounds_dir"]))


def approved_round(cfg):
    try:
        return json.load(open(os.path.join(root(cfg), "APPROVED_FINGERPRINTS.json"), encoding="utf-8")).get("round")
    except (OSError, ValueError, AttributeError):
        return None


def resolve(cfg, doc, round_name=None):
    """(DOC, round or None, key) for --doc/--round; raises Refused."""
    d = str(doc or "").upper()
    if d not in DOCS:
        raise Refused(f"--doc must be SUMMARY, REPORT or SIGNOFF, not {doc!r}"
                      + (" (RUN_RECORD.md is delivered as markdown only: never rendered)" if "RUN_RECORD" in d else ""))
    if d != "SIGNOFF":
        return d, None, d
    r = approved_round(cfg) if round_name == "approved" else round_name
    if not r:
        raise Refused("--doc SIGNOFF needs --round <the sheet's round> (or `approved`, the round of the approval)")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", r) or not os.path.isdir(os.path.join(root(cfg), r)):
        raise Refused(f"--round {r}: no such round directory")
    return d, r, f"SIGNOFF-{r}"


def md_path(cfg, doc, rnd=None):
    return os.path.join(root(cfg), rnd, "SIGNOFF.md") if doc == "SIGNOFF" else os.path.join(root(cfg), doc + ".md")


def pdf_path(cfg, doc, rnd=None):
    """Where the delivered PDF lives (the document's usual path): finish copies the shipped one there."""
    return md_path(cfg, doc, rnd)[:-3] + ".pdf"


def rec_dir(cfg, key):
    return os.path.join(root(cfg), PDF_DIR, key)


def rec_path(cfg, key):
    return os.path.join(rec_dir(cfg, key), RECORD)


def vdir(cfg, key, v):
    return os.path.join(rec_dir(cfg, key), f"v{v}")


def work_dir(cfg, key, v, step):
    """The agent's own working directory (git-excluded; created so that no mkdir asks permission)."""
    d = os.path.join(project.REPO, project.FW, "render", key, f"v{v}", step)
    os.makedirs(d, exist_ok=True)
    project._exclude(project.FW + "/")
    return d


def rel(p):
    return os.path.relpath(p, project.REPO)


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def md_sha(cfg, doc, rnd=None):
    p = md_path(cfg, doc, rnd)
    return sha_file(p) if os.path.exists(p) else None


def load(cfg, key):
    try:
        return json.load(open(rec_path(cfg, key), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(cfg, key, rec):
    os.makedirs(rec_dir(cfg, key), exist_ok=True)
    with open(rec_path(cfg, key), "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return rec_path(cfg, key)


# --- committing (each step alone; parallel documents retry on a busy index) ---------------------------------
def git(*a):
    return subprocess.run(["git", "-C", project.AUDITS, *a], capture_output=True, text=True)


def commit(paths, subject, tries=6):
    """project.commit_only, retried while another process holds git's index.lock (SUMMARY and REPORT render in
    parallel; review 3d). Raises ValueError when it cannot commit."""
    last = None
    for i in range(tries):
        try:
            return project.commit_only(paths, subject, repo=project.AUDITS)
        except ValueError as e:
            last = e
            if "index.lock" not in str(e) and "Unable to create" not in str(e):
                raise
            time.sleep(0.5 * (i + 1))
    raise ValueError(f"{last} (index.lock still held after {tries} tries: stops.py repair-lock, then run it again)")


def restore_interrupted(cfg, key):
    """B13 pattern: a command killed between writing its files and committing them leaves them uncommitted. Each
    mutating command first puts this document's record back to its committed state (untracked files removed,
    changed ones checked out, nothing staged), so a half-written step is never mistaken for a done one. Returns
    the paths it restored ([] when nothing was left over)."""
    d = rec_dir(cfg, key)
    if not os.path.isdir(d):
        return []
    r = git("status", "--porcelain", "--untracked-files=all", "-z", "--", os.path.relpath(d, project.AUDITS))
    if r.returncode != 0:
        raise Refused(f"git status failed on {rel(d)}: {r.stderr.strip()[:200]}")
    out = []
    for ent in [e for e in r.stdout.split("\x00") if e]:
        st, path = ent[:2], ent[3:]
        full = os.path.join(project.AUDITS, path)
        if st.strip() == "??":
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            elif os.path.exists(full):
                os.remove(full)
        else:
            git("reset", "-q", "--", path)
            if git("cat-file", "-e", f"HEAD:{path}").returncode == 0:
                git("checkout", "-q", "--", path)
            elif os.path.exists(full):
                os.remove(full)
        out.append(path)
    return out


# --- the state machine -----------------------------------------------------------------------------------
def rounds_of(rec):
    return list((rec or {}).get("rounds") or [])


def b_passed(r):
    return ((r or {}).get("b") or {}).get("verdict") == "PASS"


def checkers_of(r):
    return dict((r or {}).get("checkers") or {})


def checker_failed(r):
    """Did an independent checker of round r (its pair ran after B passed it) find a difference?"""
    return any(c.get("verdict") == "DIFFERENT" for c in checkers_of(r).values())


def good(r):
    """Round r ships as verified: B passed it and its checker pair is done with no DIFFERENT (a checker that did
    not run is disclosed, never looped on)."""
    ch = checkers_of(r)
    return b_passed(r) and all(str(n) in ch for n in (1, 2)) and not checker_failed(r)


def passed_round(rec):
    rs = rounds_of(rec)
    return rs[-1] if rs and good(rs[-1]) else None


def objections(r):
    """[remaining objection, verbatim] of round r: B's BLOCKING findings when B failed it; the checkers' when B
    passed it and a checker found a difference; a note when no verifier verdict exists."""
    b = (r or {}).get("b") or {}
    if b.get("status") != "saved":
        return ["No verifier verdict: the verifier did not run on this rendering."]
    if b.get("verdict") != "PASS":
        return list(b.get("findings") or [])
    return [f"checker {n}: {f}" for n, c in sorted(checkers_of(r).items()) for f in (c.get("findings") or [])]


def least_bad(rec):
    """The round to ship when the budget is spent: among rounds with a PDF, a round with a B verdict before any
    round without one (unverified ranks below every verified round); then the fewest remaining objections (B's,
    or the checkers' on a round B passed); then the later round. None when no round produced a PDF."""
    cands = [r for r in rounds_of(rec) if (r.get("a") or {}).get("status") == "saved"]
    if not cands:
        return None

    def rank(r):
        verified = ((r.get("b") or {}).get("status") == "saved")
        return (0 if verified else 1, len(objections(r)) if verified else 0, -r["k"])
    return min(cands, key=rank)


def covers_of(rec):
    """The cover attempts, in order: {"t", "round", "objections" (the list the cover was asked to show), "a" (the
    cover agent's PDF or failure), "check" (the cover verifier's verdict or failure)}."""
    return list((rec or {}).get("covers") or [])


def good_cover(rec):
    """The cover attempt that ships (review HIGH): a fresh verifier, whose verdict is recorded, passed it. None
    otherwise -- a cover nobody verified never ships."""
    cs = covers_of(rec)
    c = cs[-1] if cs else None
    if c and (c.get("a") or {}).get("status") == "saved" and (c.get("check") or {}).get("verdict") == "PASS":
        return c
    return None


def target(rec):
    """(round entry or None, the PDF that ships, relative to the rounds dir): the verified round's, else the least
    bad round's (with its cover only when a fresh verifier passed the cover)."""
    p = passed_round(rec)
    if p:
        return p, p["a"]["pdf"]
    lb = least_bad(rec)
    if lb is None:
        return None, None
    cov = good_cover(rec)
    return lb, (cov["a"]["pdf"] if cov else lb["a"]["pdf"])


def step(rec, cur_sha):
    """The one next step: ("begin",), ("A", k), ("B", k), ("checker", [n...]) on round k's PDF, ("cover", k),
    ("cover-check", k), ("finish",), ("done",). The loop (approver, 2026-10-23): A renders, B verifies; B FAIL -> A again with B's
    findings; B PASS -> a fresh checker pair; a checker DIFFERENT -> A again with the checkers' findings, then B,
    then a fresh pair; all inside one budget of BUDGET A rounds. Spent: the least bad round, its cover page of every
    remaining objection made by a fresh A and checked by a fresh verifier (review HIGH; at most COVER_TRIES
    attempts, then the round ships without a cover, disclosed), finish. Always ends."""
    if rec is None or rec.get("md_sha256") != cur_sha or cur_sha is None:
        return ("begin",)
    if rec.get("outcome"):
        return ("done",)
    rs = rounds_of(rec)
    if not rs:
        return ("A", 1)
    last = rs[-1]
    if (last.get("a") or {}).get("status") == "saved" and not last.get("b"):
        return ("B", last["k"])
    if b_passed(last):
        todo = [n for n in (1, 2) if str(n) not in checkers_of(last)]
        if todo:
            return ("checker", todo)
        if not checker_failed(last):
            return ("finish",)
    if last["k"] < rec.get("budget", BUDGET):
        return ("A", last["k"] + 1)
    lb = least_bad(rec)
    if lb is None:
        return ("finish",)
    cs = covers_of(rec)
    if cs:
        if (cs[-1].get("a") or {}).get("status") == "saved" and not cs[-1].get("check"):
            return ("cover-check", lb["k"])
        if good_cover(rec):
            return ("finish",)
    if len(cs) < COVER_TRIES:
        return ("cover", lb["k"])
    return ("finish",)


# --- begin ---------------------------------------------------------------------------------------------------
def _audit_gate(cfg, doc, rnd):
    """[problem]: is the md audited at its current hash? The fresh-reader gate of the document (readers.py
    --check: its newest pass read exactly this version, every blocking finding answered); for the hands-off
    sheet, which has no reader, `signoff.py check`."""
    if doc == "SIGNOFF" and project.involvement(cfg) == "hands-off":
        r = subprocess.run([sys.executable, "-B", os.path.join(project.AUDITS, "signoff.py"), "check", "--round", rnd]
                           + (["--project", cfg["name"]] if cfg.get("name") else []),
                           cwd=project.REPO, capture_output=True, text=True)
        return [] if r.returncode == 0 else [f"signoff.py check --round {rnd} fails: "
                                             + " | ".join((r.stdout + r.stderr).strip().splitlines()[-3:])[:400]]
    import readers
    try:
        return [str(p) for p in readers.check(cfg, doc.lower(), rnd)]
    except Exception as e:      # noqa: BLE001 -- fail closed
        return [f"the reader records could not be read: {e!r}"]


AUDIT_GATE = _audit_gate        # the selftest's stand-in


def reader_pass_cmd(cfg, doc, rnd):
    """Smoke test: the one command that runs the md's missing audit -- the fresh-reader pass to run (or, for the
    hands-off sheet, its check)."""
    if doc == "SIGNOFF" and cfg is not None and project.involvement(cfg) == "hands-off":
        return f"python3 audits/signoff.py check --round {rnd}"
    if doc == "SIGNOFF":
        return f"python3 audits/prompt.py --prompt fresh-reader --doc signoff --round {rnd} --write"
    return (f"python3 audits/prompt.py --prompt fresh-reader --doc {doc.lower()} --round <newest round> --write "
            f"(run/fresh-reader.md; run/stage5-delivery.md step 5)")


def gate_cmd(doc, rnd, cfg=None):
    if doc == "SIGNOFF" and cfg is not None and project.involvement(cfg) == "hands-off":
        return f"python3 audits/signoff.py check --round {rnd}"
    return f"python3 audits/readers.py --doc {doc.lower()}" + (f" --round {rnd}" if rnd else "") + " --check"


def begin(cfg, doc, rnd=None):
    """Start (or restart, for a changed md) the loop. Returns (rc, [lines])."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    fixed = restore_interrupted(cfg, key)
    out = [f"note: an interrupted render command left {', '.join(fixed)} uncommitted: restored to the committed "
           f"state"] if fixed else []
    cur = md_sha(cfg, doc, rnd)
    if cur is None:
        raise Refused(f"{rel(md_path(cfg, doc, rnd))} does not exist: generate it first")
    rec = load(cfg, key)
    if rec and rec.get("md_sha256") == cur:
        return 0, out + [f"render {key}: already begun for this md (version {rec.get('version')}): "
                         f"python3 audits/render_record.py next {_args(doc, rnd)}"]
    probs = AUDIT_GATE(cfg, doc, rnd)
    if probs:
        raise Refused(f"{rel(md_path(cfg, doc, rnd))} is not audited at its current hash ({gate_cmd(doc, rnd, cfg)}: "
                      + "; ".join(" ".join(p.split())[:200] for p in probs[:3])
                      + "): nothing is rendered from an unaudited md. "
                      + ("Run its check: " if doc == "SIGNOFF" and project.involvement(cfg) == "hands-off" else
                         f"Run its fresh-reader pass ({doc} reader): ")
                      + reader_pass_cmd(cfg, doc, rnd) + ", answer every blocking finding, check it ("
                      + gate_cmd(doc, rnd, cfg) + ") and begin again; never a stop")
    earlier = list((rec or {}).get("earlier") or [])
    if rec:
        earlier.append({"version": rec.get("version"), "md_sha256": rec.get("md_sha256"),
                        "outcome": rec.get("outcome") or "superseded (the md changed before it finished)",
                        "rounds": len(rounds_of(rec)), "shipped_pdf_sha256": rec.get("shipped_pdf_sha256")})
    v = (rec.get("version", 0) if rec else 0) + 1
    mc = git("log", "-1", "--format=%H", "--", os.path.relpath(md_path(cfg, doc, rnd), project.AUDITS))
    new = {"doc": doc, "round": rnd, "key": key, "version": v, "budget": BUDGET,
           "md_path": os.path.relpath(md_path(cfg, doc, rnd), root(cfg)), "md_sha256": cur,
           "md_commit": mc.stdout.strip() if mc.returncode == 0 else "",
           "audited_by": gate_cmd(doc, rnd, cfg), "started": datetime.date.today().isoformat(),
           "rounds": [], "covers": [], "outcome": None, "md_beside": True,
           "earlier": earlier}
    p = _write(cfg, key, new)
    commit([p], f"render {key} begin v{v}")
    out.append(f"render {key}: begun, version {v} (md sha256 {cur[:12]}…, audited: {gate_cmd(doc, rnd, cfg)})"
               + (f"; the md changed since version {v - 1}: the loop starts again at round 1" if rec else ""))
    return 0, out


def _args(doc, rnd):
    return f"--doc {doc}" + (f" --round {rnd}" if rnd else "")


# --- prompts (prompt.py --prompt render-a|render-b|render-cover|render-cover-check|render-check fills them) --
REF_RE = re.compile(r"\\(cref|Cref|ref|eqref|autoref)\{([^}]*)\}")


def paper_tex(cfg, doc, rnd):
    """The typesetting aid for the sheet, whose paper statements are LaTeX source: the paper's own macro
    definitions and what each cross-reference the sheet quotes prints as in the paper (from its .aux), so the
    renderer typesets them as the paper does, and the verifier and checkers know these are not changes. Empty for
    the other documents."""
    if doc != "SIGNOFF":
        return ""
    import signoff
    try:
        macros = signoff.source_macros(cfg)
        labels = signoff.paper_labels(cfg)
        md = open(md_path(cfg, doc, rnd), encoding="utf-8").read()
    except (OSError, ValueError):
        macros, labels, md = "", {}, ""
    refs = []
    for m in REF_RE.finditer(md):
        for key in m.group(2).split(","):
            kind, num = labels.get(key.strip(), ("", None))
            shown = ("[" + key.strip() + "]" if num is None else
                     (kind.capitalize() + " " + num if m.group(1) in ("cref", "Cref") and kind else num))
            line = f"  \\{m.group(1)}{{{key.strip()}}} prints as: {shown}"
            if line not in refs:
                refs.append(line)
    out = ["The paper's statements on this sheet (after **Paper.**) are LaTeX source: typeset them as mathematics, "
           "as the paper does. A theorem-environment wrapper (\\begin{lemma}...\\end{lemma}, restatable), a "
           "\\label and a \\qed are dropped (the sheet has its own heading per result): that is not a change."]
    out.append("The paper's macro definitions (use them; they are data):\n" + (macros or "  (none found)"))
    out.append("Its cross-references print as in the paper:\n" + ("\n".join(refs) or "  (none on this sheet)"))
    return "\n".join(out)


ROLE_PROMPT = {"A": "render-a", "B": "render-b", "cover": "render-cover", "cover-check": "render-cover-check",
               "checker": "render-check"}


def prompt_file(cfg, key, rec, st, n=None):
    """The prompt file of step st (as `step` returns it) in this version's record."""
    V = vdir(cfg, key, rec["version"])
    if st[0] == "A":
        return os.path.join(V, f"r{st[1]}", "prompt-A.txt")
    if st[0] == "B":
        return os.path.join(V, f"r{st[1]}", "prompt-B.txt")
    if st[0] == "cover":
        return os.path.join(V, "cover", f"t{len(covers_of(rec)) + 1}", "prompt-cover.txt")
    if st[0] == "cover-check":
        return os.path.join(V, "cover", f"t{len(covers_of(rec))}", "prompt-cover-check.txt")
    return os.path.join(V, f"r{rounds_of(rec)[-1]['k']}", f"prompt-check-{n}.txt")


def issued(p):
    """Was this prompt written and committed (prompt.py --prompt ... --write)? Only a committed prompt was issued."""
    return git("cat-file", "-e", f"HEAD:{os.path.relpath(p, project.AUDITS)}").returncode == 0


def _require_issued(cfg, key, rec, st, role, n, doc, rnd, what):
    """Review MED 1 (as lanes and readers): an output, or a failure, is recorded only for a step whose prompt was
    issued -- written and committed by prompt.py --write -- so an agent's verdict is always the answer to the prompt
    on record, and a step nobody was spawned for cannot be closed."""
    p = prompt_file(cfg, key, rec, st, n)
    if not issued(p):
        nn = f" --n {n}" if n else ""
        raise Refused(f"render {key}: no prompt was issued for {_step_text(st) if not n else f'checker {n}'} "
                      f"({rel(p)} is not committed): {what} is not recorded. Issue it (python3 audits/prompt.py "
                      f"--prompt {ROLE_PROMPT[role]} {_args(doc, rnd)}{nn} --write), spawn one new agent with the "
                      f"printed line, and let it save")


def prompt_target(cfg, doc, rnd, role, n=None):
    """(prompt file, placeholder map, record) for the step the record is at. Raises Refused when `role` is not
    the next step (the loop's control is here, never the operator's judgement)."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    fixed = restore_interrupted(cfg, key)
    rec = load(cfg, key)
    st = step(rec, md_sha(cfg, doc, rnd))
    want = {v_: k_ for k_, v_ in ROLE_PROMPT.items()}[role]
    if st[0] != want or (want == "checker" and n not in st[1]):
        raise Refused(f"render {key}: the next step is {_step_text(st)}, not {role}"
                      + (f" {n}" if n else "") + f" (python3 audits/render_record.py next {_args(doc, rnd)})"
                      + (f" [restored: {', '.join(fixed)}]" if fixed else ""))
    v = rec["version"]
    V = vdir(cfg, key, v)
    md = md_path(cfg, doc, rnd)
    save = f"python3 audits/render_record.py save {_args(doc, rnd)}"
    subs = {"<DOC>": doc, "<MD>": rel(md), "<MD-SHA>": rec["md_sha256"], "<PAPER-TEX>": paper_tex(cfg, doc, rnd),
            "<ONE-PAGE>": ("SUMMARY must fit on ONE page (a cover page of objections, if any, is not counted)."
                           if doc == "SUMMARY" else "There is no page limit.")}
    if want == "A":
        k = st[1]
        prev = [r for r in rounds_of(rec) if (r.get("a") or {}).get("status") == "saved"]
        last = rounds_of(rec)[-1] if rounds_of(rec) else None
        if not prev:
            prevtxt = "This is the first rendering of this version of the md: there is no earlier source."
        else:
            ps = prev[-1]
            src = os.path.join(root(cfg), ps["a"]["source"]) if ps["a"].get("source") else None
            b = (last or {}).get("b") or {}
            if b_passed(last) and checker_failed(last):
                fnd = (f"The verifier passed round {last['k']}, but an independent checker found a mathematical "
                       f"difference: " + "; ".join(rel(os.path.join(root(cfg), c["file"]))
                                                  for _n, c in sorted(checkers_of(last).items())
                                                  if c.get("verdict") == "DIFFERENT"))
            elif b.get("status") == "saved":
                fnd = f"The verifier's findings on round {last['k']}: {rel(os.path.join(root(cfg), b['file']))}"
            elif (last or {}).get("a", {}).get("status") == "failed":
                fnd = f"Round {last['k']} produced no PDF (the renderer ended without one); there are no new findings."
            else:
                fnd = f"The verifier did not run on round {last['k']}: there are no findings."
            prevtxt = (f"Round {ps['k']}'s source (yours to start from): "
                       + (rel(src) if src else "(not kept: start afresh)") + f"\n{fnd}\nFix every BLOCKING "
                       "finding; keep what was right.")
        p = prompt_file(cfg, key, rec, st)
        subs.update({"<ROUND>": str(k), "<BUDGET>": str(rec.get("budget", BUDGET)), "<PREVIOUS>": prevtxt,
                     "<DIR>": rel(work_dir(cfg, key, v, f"r{k}")) + os.sep,
                     "<SAVE-CMD>": f"{save} --role A"})
    elif want == "B":
        k = st[1]
        r = rounds_of(rec)[-1]
        p = prompt_file(cfg, key, rec, st)
        subs.update({"<ROUND>": str(k), "<PDF>": rel(os.path.join(root(cfg), r["a"]["pdf"])),
                     "<PDF-SHA>": r["a"]["pdf_sha256"], "<DIR>": rel(work_dir(cfg, key, v, f"r{k}-B")) + os.sep,
                     "<SAVE-CMD>": f"{save} --role B"})
    elif want == "cover":
        k = st[1]
        r = next(x for x in rounds_of(rec) if x["k"] == k)
        p = prompt_file(cfg, key, rec, st)
        objs = objections(r)
        cs = covers_of(rec)
        t = len(cs) + 1
        if not cs:
            prevtxt = ""
        else:
            ck = cs[-1].get("check") or {}
            prevtxt = ("An earlier cover attempt was rejected by its verifier: "
                       + rel(os.path.join(root(cfg), ck["file"])) + ". Fix every BLOCKING finding."
                       if ck.get("status") == "saved" else
                       "An earlier cover attempt produced no PDF." if (cs[-1].get("a") or {}).get("status") != "saved"
                       else "An earlier cover attempt was not verified (its verifier did not run).")
        subs.update({"<ROUND>": str(k), "<PDF>": rel(os.path.join(root(cfg), r["a"]["pdf"])),
                     "<PDF-SHA>": r["a"]["pdf_sha256"], "<PREVIOUS>": prevtxt,
                     "<OBJECTIONS>": "\n".join(f"- {o}" for o in objs) or "- (none recorded)",
                     "<DIR>": rel(work_dir(cfg, key, v, f"cover-t{t}")) + os.sep,
                     "<SAVE-CMD>": f"{save} --role cover"})
    elif want == "cover-check":
        k = st[1]
        r = next(x for x in rounds_of(rec) if x["k"] == k)
        c = covers_of(rec)[-1]
        p = prompt_file(cfg, key, rec, st)
        subs.update({"<ROUND>": str(k), "<PDF>": rel(os.path.join(root(cfg), c["a"]["pdf"])),
                     "<PDF-SHA>": c["a"]["pdf_sha256"],
                     "<ROUND-PDF>": rel(os.path.join(root(cfg), r["a"]["pdf"])), "<ROUND-PDF-SHA>": r["a"]["pdf_sha256"],
                     "<OBJECTIONS>": "\n".join(f"- {o}" for o in c["objections"]) or "- (none recorded)",
                     "<DIR>": rel(work_dir(cfg, key, v, f"cover-t{c['t']}-check")) + os.sep,
                     "<SAVE-CMD>": f"{save} --role cover-check"})
    else:
        r = rounds_of(rec)[-1]          # a fresh pair for each round B passes
        k = r["k"]
        p = prompt_file(cfg, key, rec, st, n)
        subs.update({"<N>": str(n), "<PDF>": rel(os.path.join(root(cfg), r["a"]["pdf"])),
                     "<PDF-SHA>": r["a"]["pdf_sha256"],
                     "<DIR>": rel(work_dir(cfg, key, v, f"r{k}-check-{n}")) + os.sep,
                     "<SAVE-CMD>": f"{save} --role checker --n {n}"})
    return p, subs, rec, key


def write_prompt(cfg, doc, rnd, role, body, n=None):
    """Write the filled prompt once and commit it alone (`render <key> prompt ...`). Re-issuable: the same
    prompt for the same step is not written again, its spawn line is printed again (a lost line, a restart, a
    mechanical retry). Returns (path, sha256, issued_now)."""
    p, _subs, rec, key = prompt_target(cfg, doc, rnd, role, n)
    data = body if body.endswith("\n") else body + "\n"
    if os.path.exists(p):
        old = open(p, encoding="utf-8").read()
        if old == data:
            return p, hashlib.sha256(data.encode()).hexdigest(), False
        raise Refused(f"{rel(p)} exists with other content (the step's inputs changed under it): python3 "
                      f"audits/render_record.py next {_args(rec['doc'], rec['round'])}")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(data)
    label = {"render-a": "A", "render-b": "B", "render-cover": "cover", "render-cover-check": "cover-check",
             "render-check": f"checker {n}"}[role]
    try:
        commit([p], f"render {key} prompt {label}")
    except ValueError:
        os.remove(p)
        raise
    return p, hashlib.sha256(data.encode()).hexdigest(), True


# --- save / fail ---------------------------------------------------------------------------------------------
def _parse_done(text):
    m = None
    for line in reversed((text or "").splitlines()):
        m = DONE_RE.match(line)
        if m:
            break
    if not m:
        raise Refused("no `RENDER_DONE {\"pdf\": ..., \"sha256\": ..., \"engine\": ..., \"notes\": ...}` line")
    try:
        d = json.loads(m.group(1))
    except ValueError as e:
        raise Refused(f"the RENDER_DONE line is not JSON ({e})")
    if not isinstance(d, dict) or not isinstance(d.get("pdf"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(d.get("sha256", ""))):
        raise Refused("RENDER_DONE needs \"pdf\" (its path) and \"sha256\" (64 lowercase hex)")
    return d


def _abs(p):
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.join(project.REPO, p)


def _parse_verdict(text, rx, want_md, want_pdf):
    """(verdict word, n blocking, [blocking findings], [problems]) of a B or checker output."""
    lines = [l.rstrip() for l in (text or "").splitlines()]
    body = [l for l in lines if l.strip()]
    probs = []
    got = {}
    for k_, r_ in SHA_LINE.items():
        m = next((r_.match(l.strip()) for l in body if r_.match(l.strip())), None)
        got[k_] = m.group(1) if m else None
    if got["md"] != want_md:
        probs.append(f"md_sha256 is {got['md'] or '(missing)'}, the md rendered is {want_md}: you read another "
                     f"version (read the md named in your prompt)")
    if got["pdf"] != want_pdf:
        probs.append(f"pdf_sha256 is {got['pdf'] or '(missing)'}, the PDF is {want_pdf}: check the PDF named in "
                     f"your prompt")
    pm = next((PAGES_RE.match(l.strip()) for l in body if PAGES_RE.match(l.strip())), None)
    if not pm:
        probs.append("no `pages: read N of N` line")
    elif pm.group(1) != pm.group(2) or pm.group(2) == "0":
        probs.append(f"pages: read {pm.group(1)} of {pm.group(2)}: read every page")
    v = rx.match(body[-1].strip()) if body else None
    if not v:
        probs.append("the last line is not a well-formed VERDICT line")
    blocking = []
    for i, l in enumerate(lines):
        m = FIND_RE.match(l)
        if m and m.group(1) == "BLOCKING":
            t = [m.group(2).strip()]
            for c in lines[i + 1:]:
                if not c.strip() or not c[:1].isspace() or FIND_RE.match(c):
                    break
                t.append(c.strip())
            blocking.append(" ".join(x for x in t if x))
    word = n = None
    if v:
        word = v.group(1).split(" ")[0]
        n = int(v.group(2)) if v.group(2) else 0
        if n != len(blocking):
            probs.append(f"the verdict says {n} BLOCKING, the output lists {len(blocking)} `- BLOCKING:` line(s)")
    return word, n, blocking, probs


def save(cfg, doc, rnd, role, text, n=None):
    """Record one agent's output. Returns [lines]; raises Refused (nothing recorded) on a malformed output, a
    stale md or PDF, or a role that is not the next step."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    fixed = restore_interrupted(cfg, key)
    pre = [f"note: an interrupted render command left {', '.join(fixed)} uncommitted: restored"] if fixed else []
    rec = load(cfg, key)
    cur = md_sha(cfg, doc, rnd)
    st = step(rec, cur)
    if st[0] == "begin":
        raise Refused(f"{rel(md_path(cfg, doc, rnd))} changed since this loop began (or none began): this output "
                      f"is of an older md and is not recorded; the loop starts again: python3 audits/render_record.py "
                      f"begin {_args(doc, rnd)}")
    want = role if role in ROLE_PROMPT else None
    if want is None or st[0] != want or (want == "checker" and n not in st[1]):
        raise Refused(f"render {key}: the next step is {_step_text(st)}, not {role}" + (f" {n}" if n else ""))
    _require_issued(cfg, key, rec, st, want, n, doc, rnd, "an output for which no prompt was issued")
    v, V = rec["version"], vdir(cfg, key, rec["version"])
    R = root(cfg)
    paths = []
    if want in ("A", "cover"):
        d = _parse_done(text)
        src_pdf = _abs(d["pdf"])
        if not os.path.isfile(src_pdf) or os.path.islink(src_pdf):
            raise Refused(f"{d['pdf']}: no such regular file")
        if sha_file(src_pdf) != d["sha256"]:
            raise Refused(f"{d['pdf']} hashes to {sha_file(src_pdf)}, not the sha256 given")
        sub = (os.path.join(V, f"r{st[1]}") if want == "A"
               else os.path.join(V, "cover", f"t{len(covers_of(rec)) + 1}"))
        os.makedirs(sub, exist_ok=True)
        dst = os.path.join(sub, f"{doc}.pdf")
        shutil.copyfile(src_pdf, dst)
        paths.append(dst)
        entry = {"status": "saved", "pdf": os.path.relpath(dst, R), "pdf_sha256": d["sha256"],
                 "engine": str(d.get("engine", ""))[:200], "notes": str(d.get("notes", ""))[:4000]}
        s = d.get("source")
        if isinstance(s, str) and s.strip():
            sp = _abs(s)
            if os.path.isfile(sp) and not os.path.islink(sp) and os.path.getsize(sp) <= SOURCE_MAX:
                sdst = os.path.join(sub, "source" + (os.path.splitext(sp)[1] or ".txt"))
                shutil.copyfile(sp, sdst)
                paths.append(sdst)
                entry["source"] = os.path.relpath(sdst, R)
            else:
                entry["source_note"] = f"{s}: not kept (missing, a link, or over {SOURCE_MAX} bytes)"
        if want == "A":
            rec["rounds"].append({"k": st[1], "a": entry})
            label = f"A {st[1]}"
        else:
            lb = next(x for x in rounds_of(rec) if x["k"] == st[1])
            rec.setdefault("covers", []).append({"t": len(covers_of(rec)) + 1, "round": st[1],
                                                 "objections": objections(lb), "a": entry})
            label = f"cover {rec['covers'][-1]['t']}"
    elif want == "cover-check":
        c = rec["covers"][-1]
        word, nb, blk, probs = _parse_verdict(text, B_VERDICT, rec["md_sha256"], c["a"]["pdf_sha256"])
        if probs:
            raise Refused("the output is not recorded: " + "; ".join(probs)
                          + ". Fix the format and save again (the whole output, on stdin)")
        f = os.path.join(V, "cover", f"t{c['t']}", "check.md")
        with open(f, "w", encoding="utf-8", newline="") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        paths.append(f)
        c["check"] = {"status": "saved", "verdict": word, "blocking": nb, "file": os.path.relpath(f, R),
                      "findings": blk, "pdf_sha256": c["a"]["pdf_sha256"]}
        label = f"cover-check {c['t']}"
    else:
        if want == "B":
            r = rec["rounds"][-1]
            pdf_sha = r["a"]["pdf_sha256"]
            word, nb, blk, probs = _parse_verdict(text, B_VERDICT, rec["md_sha256"], pdf_sha)
        else:
            r = rec["rounds"][-1]       # the checkers read the round B just passed
            pdf_sha = r["a"]["pdf_sha256"]
            word, nb, blk, probs = _parse_verdict(text, C_VERDICT, rec["md_sha256"], pdf_sha)
        if probs:
            raise Refused("the output is not recorded: " + "; ".join(probs)
                          + ". Fix the format and save again (the whole output, on stdin)")
        f = os.path.join(V, f"r{r['k']}", "B.md" if want == "B" else f"check-{n}.md")
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w", encoding="utf-8", newline="") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
        paths.append(f)
        entry = {"status": "saved", "verdict": word, "blocking": nb, "file": os.path.relpath(f, R),
                 "findings": blk, "pdf_sha256": pdf_sha}
        if want == "B":
            r["b"] = entry
            label = f"B {st[1]}"
        else:
            r.setdefault("checkers", {})[str(n)] = entry
            label = f"checker {n} {r['k']}"
    paths.append(_write(cfg, key, rec))
    try:
        commit(paths, f"render {key} {label}")
    except ValueError as e:
        restore_interrupted(cfg, key)
        raise Refused(f"not committed ({e}); nothing recorded: save again")
    return pre + [f"render {key}: {label} recorded" + _verdict_tail(rec, want, n),
                  "next: " + _step_text(step(rec, cur))]


def _verdict_tail(rec, want, n):
    if want == "B":
        b = rec["rounds"][-1]["b"]
        return f" ({b['verdict']}, {b['blocking']} blocking)"
    if want == "checker":
        c = checkers_of(rec["rounds"][-1])[str(n)]
        return f" ({c['verdict']}, {c['blocking']} finding(s))"
    if want == "cover-check":
        c = rec["covers"][-1]["check"]
        return f" ({c['verdict']}, {c['blocking']} blocking)"
    return ""


def fail(cfg, doc, rnd, role, why, n=None):
    """An agent that crashed, was refused, or ended without saving (also one lost to a restart): its step is
    done, unsuccessfully. Never a stop. Returns [lines]."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    restore_interrupted(cfg, key)
    rec = load(cfg, key)
    cur = md_sha(cfg, doc, rnd)
    st = step(rec, cur)
    if st[0] == "begin":
        raise Refused(f"no loop for this md: python3 audits/render_record.py begin {_args(doc, rnd)}")
    if st[0] != role or (role == "checker" and n not in st[1]):
        raise Refused(f"render {key}: the next step is {_step_text(st)}, not {role}" + (f" {n}" if n else ""))
    _require_issued(cfg, key, rec, st, role, n, doc, rnd, "a failure of an agent nobody was spawned for")
    why = " ".join(str(why or "").split())[:500] or "(no reason given)"
    entry = {"status": "failed", "why": why}
    if role == "A":
        rec["rounds"].append({"k": st[1], "a": entry})
        label = f"A {st[1]} failed"
    elif role == "B":
        rec["rounds"][-1]["b"] = entry
        label = f"B {st[1]} failed"
    elif role == "cover":
        lb = next(x for x in rounds_of(rec) if x["k"] == st[1])
        rec.setdefault("covers", []).append({"t": len(covers_of(rec)) + 1, "round": st[1],
                                             "objections": objections(lb), "a": entry})
        label = f"cover {rec['covers'][-1]['t']} failed"
    elif role == "cover-check":
        rec["covers"][-1]["check"] = entry
        label = f"cover-check {rec['covers'][-1]['t']} failed"
    else:
        rec["rounds"][-1].setdefault("checkers", {})[str(n)] = entry
        label = f"checker {n} {rec['rounds'][-1]['k']} failed"
    p = _write(cfg, key, rec)
    commit([p], f"render {key} {label}")
    return [f"render {key}: {label} ({why}); never a stop", "next: " + _step_text(step(rec, cur))]


# --- finish --------------------------------------------------------------------------------------------------
def finish(cfg, doc, rnd=None):
    doc, rnd, key = resolve(cfg, doc, rnd)
    restore_interrupted(cfg, key)
    rec = load(cfg, key)
    cur = md_sha(cfg, doc, rnd)
    st = step(rec, cur)
    if st[0] == "done":
        return [f"render {key}: finished already ({rec['outcome']})"]
    if st[0] != "finish":
        raise Refused(f"render {key}: the next step is {_step_text(st)}, not finish")
    R = root(cfg)
    usual = pdf_path(cfg, doc, rnd)
    passed = passed_round(rec)
    chosen, tp = target(rec)
    paths = []
    if chosen is None:
        rec.update(outcome="no-pdf", shipped_pdf_sha256=None, shipped_round=None, shipped_from=None,
                   remaining_objections=["no round produced a PDF: the md is delivered alone"])
        if os.path.exists(usual):
            os.remove(usual)      # an older PDF never ships for this md
            paths.append(usual)
    else:
        if passed:
            # review MED 2: `verified` needs both checkers' recorded SAME verdicts; a checker that did not run is
            # never a pass (never looped on either: the outcome says plainly that it did not run)
            ch = checkers_of(passed)
            same = all(ch.get(str(n_), {}).get("status") == "saved" and ch[str(n_)].get("verdict") == "SAME"
                       for n_ in (1, 2))
            rec["outcome"] = "verified" if same else "checkers-did-not-run"
            rec["remaining_objections"] = []
        else:
            rec["outcome"] = "least-bad"
            rec["remaining_objections"] = objections(chosen)
            cov = good_cover(rec)
            if cov and (cov["round"] != chosen["k"] or cov["objections"] != rec["remaining_objections"]):
                raise Refused(f"render {key}: the verified cover shows round {cov['round']}'s objections, the record's "
                              f"least bad round is {chosen['k']} with other objections: not finished")
            rec["shipped_cover"] = cov["t"] if cov else None
        shutil.copyfile(os.path.join(R, tp), usual)
        rec.update(shipped_pdf_sha256=sha_file(usual), shipped_round=chosen["k"], shipped_from=tp)
        paths.append(usual)
    rec["finished"] = datetime.date.today().isoformat()
    paths.append(_write(cfg, key, rec))
    commit(paths, f"render {key} finish")
    return [f"render {key}: {rec['outcome']}"] + [f"  {l}" for l in outcome_lines(rec)]


# --- the guard ------------------------------------------------------------------------------------------------
def check(cfg, doc, rnd=None):
    """[problem] (empty: the delivered PDF, or the md alone, is the one recorded for the md as it is now):
    RENDER.json exists and has an outcome; its md sha256 is the md on disk; the PDF at the document's usual path
    hashes to the recorded shipped PDF (a hash, never a reading). `no-pdf` passes with no PDF."""
    try:
        doc, rnd, key = resolve(cfg, doc, rnd)
    except Refused as e:
        return [str(e)]
    name = rel(md_path(cfg, doc, rnd))
    again = f"render it: python3 audits/render_record.py next {_args(doc, rnd)} (never a stop)"
    rec = load(cfg, key)
    if not rec:
        return [f"{name} has no rendering record ({rel(rec_path(cfg, key))}): {again}"]
    cur = md_sha(cfg, doc, rnd)
    if cur is None:
        return [f"{name} does not exist"]
    if rec.get("md_sha256") != cur:
        return [f"{name} changed since its PDF was rendered (render record {str(rec.get('md_sha256'))[:12]}…, the md "
                f"now {cur[:12]}…): {again}"]
    if rec.get("outcome") not in OUTCOMES:
        return [f"the rendering of {name} has not finished (next: {_step_text(step(rec, cur))}): {again}"]
    if rec["outcome"] == "no-pdf":
        return []
    usual = pdf_path(cfg, doc, rnd)
    if not os.path.exists(usual):
        return [f"{rel(usual)} is missing (render record {key} shipped {str(rec.get('shipped_pdf_sha256'))[:12]}…): "
                f"restore it from {rec.get('shipped_from')}, or {again}"]
    if sha_file(usual) != rec.get("shipped_pdf_sha256"):
        return [f"{rel(usual)} is not the PDF the render record shipped (sha256 {sha_file(usual)[:12]}…, recorded "
                f"{str(rec.get('shipped_pdf_sha256'))[:12]}…): {again}"]
    return []


def shown(cfg, doc, rnd=None):
    """Review LOW: record the PDF the human is shown, right before the question is asked (Checkpoint B; a
    re-approval): its sha256, outcome, render version and md sha256, appended to RENDER.json's `shown` and committed
    (`render <key> shown`). `approve --by human` requires the newest entry to be the PDF the record ships then.
    Returns [lines]: the record, then the outcome lines to quote above the question."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    restore_interrupted(cfg, key)
    probs = check(cfg, doc, rnd)
    if probs:
        raise Refused("; ".join(probs) + ": nothing shown is recorded; render it first")
    rec = load(cfg, key)
    entry = {"pdf_sha256": rec.get("shipped_pdf_sha256"), "outcome": rec.get("outcome"),
             "render_version": rec.get("version"), "md_sha256": rec.get("md_sha256"),
             "date": datetime.date.today().isoformat()}
    rec.setdefault("shown", []).append(entry)
    commit([_write(cfg, key, rec)], f"render {key} shown")
    return ([f"render {key}: shown recorded ({rel(pdf_path(cfg, doc, rnd)) if entry['pdf_sha256'] else rel(md_path(cfg, doc, rnd))}"
             f"{', sha256 ' + entry['pdf_sha256'] if entry['pdf_sha256'] else ', no PDF: the md'}); quote these "
             f"lines above the question:"] + [f"  {l}" for l in outcome_lines(rec)])


def shown_problem(cfg, doc, rnd=None):
    """(the newest `shown` entry, [problem]): it exists and is the PDF (sha256, render version, md) the record ships
    now -- the human approves the PDF they were shown, never one rendered after the question."""
    try:
        doc, rnd, key = resolve(cfg, doc, rnd)
    except Refused as e:
        return None, [str(e)]
    rec = load(cfg, key) or {}
    sh = list(rec.get("shown") or [])
    cmd = f"python3 audits/render_record.py shown {_args(doc, rnd)}"
    if not sh:
        return None, [f"no PDF of {rel(md_path(cfg, doc, rnd))} was recorded as shown to the human ({cmd}, right "
                      f"before asking)"]
    last = sh[-1]
    now = {"pdf_sha256": rec.get("shipped_pdf_sha256"), "render_version": rec.get("version"),
           "md_sha256": rec.get("md_sha256")}
    if any(last.get(k_) != v_ for k_, v_ in now.items()):
        return None, [f"the PDF the record ships now (sha256 {str(now['pdf_sha256'])[:12]}…, version "
                      f"{now['render_version']}) is not the one shown to the human (sha256 "
                      f"{str(last.get('pdf_sha256'))[:12]}…, version {last.get('render_version')}; {cmd})"]
    return last, []


def delivered(cfg, doc, rnd=None):
    """(outcome, pdf path or None) for --deliver, after check passed."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    rec = load(cfg, key) or {}
    if rec.get("outcome") in ("verified", "checkers-did-not-run", "least-bad"):
        return rec["outcome"], pdf_path(cfg, doc, rnd)
    return rec.get("outcome"), None


# --- what the human is told ----------------------------------------------------------------------------------
def _q(s, n=300):
    s = " ".join(str(s).split())
    return f"«{s[:n]}{'…' if len(s) > n else ''}»"


def outcome_lines(rec):
    """The lines README section D, the checkpoint messages and the completion message quote: the outcome, the
    rounds, every remaining objection, the checkers' verdicts with their findings, and A's notes (NOTE: nobody
    acts on them)."""
    if not rec:
        return ["not rendered"]
    doc = rec.get("doc", "?")
    out = []
    rs = rounds_of(rec)
    nb = sum(1 for r in rs if (r.get("b") or {}).get("status") == "saved")
    oc = rec.get("outcome")
    if oc == "no-pdf":
        out.append(f"no PDF: no rendering round produced one ({len(rs)} round(s)); `{doc}.md` is delivered alone")
    elif oc == "verified":
        out.append(f"verified: the verifier passed round {rec.get('shipped_round')} of {len(rs)} (budget "
                   f"{rec.get('budget', BUDGET)}) and both independent checkers found no mathematical difference")
    elif oc == "checkers-did-not-run":
        ch = checkers_of(next((r for r in rs if r["k"] == rec.get("shipped_round")), {}))
        miss = sum(1 for n_ in (1, 2) if ch.get(str(n_), {}).get("status") != "saved")
        out.append(f"NOT INDEPENDENTLY CHECKED: the verifier passed round {rec.get('shipped_round')} of {len(rs)}, but "
                   + ("the independent checkers did not run" if miss == 2 else
                      "only one of the two independent checkers ran (it found no mathematical difference); the other "
                      "did not run")
                   + f", so {'nobody' if miss == 2 else 'only one checker'} independently judged whether the PDF says "
                   f"mathematically the same thing as `{doc}.md`; `{doc}.md`, delivered beside it, is the "
                   f"authoritative text")
    elif oc == "least-bad":
        cs = covers_of(rec)
        out.append(f"NOT FULLY VERIFIED (least bad): no rendering passed the verifier and both independent checkers "
                   f"in {len(rs)} round(s) ({nb} verified); round {rec.get('shipped_round')} ships"
                   + (", its first page listing the remaining objections (a fresh verifier checked that cover page: "
                      "PASS)" if rec.get("shipped_cover") else
                      f" WITHOUT the cover page of objections (no cover passed its verifier in {len(cs)} attempt(s))")
                   + f"; `{doc}.md`, delivered beside it, is the authoritative text")
        for o in rec.get("remaining_objections") or []:
            out.append(f"remaining objection: {_q(o)}")
    else:
        out.append(f"in progress: {_step_text(step(rec, rec.get('md_sha256')))}")
    for r in rs:
        # every checker pair of the loop: a DIFFERENT sent the round back to the renderer; the shipped round's
        # findings are quoted (the least bad round's are its remaining objections, above)
        for n_, c in sorted(checkers_of(r).items()):
            if c.get("status") != "saved":
                out.append(f"round {r['k']}, checker {n_}: did not run ({c.get('why', '')})")
                continue
            out.append(f"round {r['k']}, checker {n_}: {c['verdict']}" + (f" ({c['blocking']})" if c.get("blocking") else "")
                       + (" -- back to the renderer" if c["verdict"] == "DIFFERENT" and r["k"] != rec.get("shipped_round")
                          else ""))
            if r["k"] == rec.get("shipped_round") and oc != "least-bad":
                out += [f"round {r['k']}, checker {n_} finding: {_q(f)}" for f in c.get("findings") or []]
    for r in rs:
        a = r.get("a") or {}
        if a.get("status") == "saved" and str(a.get("notes", "")).strip():
            out.append(f"NOTE (renderer, round {r['k']}; a suspected error in the md, nobody acts on it): {_q(a['notes'])}")
    for c in covers_of(rec):
        ck = c.get("check") or {}
        if c.get("t") != rec.get("shipped_cover") and oc == "least-bad":
            out.append(f"cover attempt {c.get('t')}: " + (
                "produced no PDF" if (c.get("a") or {}).get("status") != "saved" else
                f"rejected by its verifier ({ck.get('blocking')} blocking)" if ck.get("verdict") == "FAIL" else
                "not verified (its verifier did not run)") + ": not shipped")
        if (c.get("a") or {}).get("notes"):
            out.append(f"NOTE (cover {c.get('t')}): {_q(c['a']['notes'])}")
    return out


def readme_lines(cfg, doc, rnd=None):
    """README section D's lines for one document."""
    try:
        d, r, key = resolve(cfg, doc, rnd)
    except Refused as e:
        return [f"- `{doc}`: {e}"]
    rec = load(cfg, key)
    name = f"{d}.pdf" if d != "SIGNOFF" else f"{r}/SIGNOFF.pdf"
    if not rec:
        return [f"- `{name}`: not rendered"]
    ls = outcome_lines(rec)
    return [f"- `{name}`: {ls[0]}"] + [f"  - {l}" for l in ls[1:]]


def _step_text(st):
    k = st[0]
    if k == "begin":
        return "begin (the md is new or changed)"
    if k == "A":
        return f"the renderer, round {st[1]}"
    if k == "B":
        return f"the verifier, round {st[1]}"
    if k == "cover":
        return f"the cover page on round {st[1]} (least bad)"
    if k == "cover-check":
        return f"the cover page's verifier on round {st[1]} (least bad)"
    if k == "checker":
        return "checker " + " and ".join(str(n) for n in st[1])
    return {"finish": "finish", "done": "nothing (done)"}[k]


def next_text(cfg, doc, rnd=None):
    """(rc, [lines]): the one next step, as a command to run (NEXT[render]) or DONE[render]."""
    doc, rnd, key = resolve(cfg, doc, rnd)
    fixed = restore_interrupted(cfg, key)
    out = [f"note: an interrupted render command left {', '.join(fixed)} uncommitted: restored to the committed "
           f"state (if it was a save, pipe the agent's output again; else record the step failed)"] if fixed else []
    rec = load(cfg, key)
    cur = md_sha(cfg, doc, rnd)
    st = step(rec, cur)
    a = _args(doc, rnd)
    if st[0] == "done":
        return 0, out + [f"DONE[render] {key}: {rec['outcome']}"] + [f"  {l}" for l in outcome_lines(rec)]
    if st[0] == "begin":
        return 0, out + [f"NEXT[render] {key}: python3 audits/render_record.py begin {a}"
                         + (" (the md changed: the loop starts again at round 1, with a new budget)" if rec else "")]
    if st[0] == "finish":
        return 0, out + [f"NEXT[render] {key}: python3 audits/render_record.py finish {a}"]
    roles = {k_: v_ for k_, v_ in ROLE_PROMPT.items() if k_ != "checker"}
    items = [(roles[st[0]], None)] if st[0] != "checker" else [("render-check", n) for n in st[1]]
    for role, n in items:
        try:
            p, _s, _r, _k = prompt_target(cfg, doc, rnd, role, n)
        except Refused as e:
            return 2, out + [f"FAIL {e}"]
        nn = f" --n {n}" if n else ""
        if os.path.exists(p):
            out.append(f"NEXT[render] {key}: {_step_text(st) if not n else f'checker {n}'} was issued ({rel(p)}): wait "
                       f"for its save. If its agent ended without saving (a crash, a refusal, lost to a restart), "
                       f"respawn it once with the same line (python3 audits/prompt.py --prompt {role} {a}{nn} "
                       f"--write prints it again) or record the step failed: python3 audits/render_record.py fail "
                       f"{a} --role {_role_arg(role)}{nn} --why \"<what happened>\". A usage limit or a capacity "
                       f"error is not a failure: wait it out (spawn-and-seal.md, \"Retry budget\"), then spawn "
                       f"it again with the same line")
        else:
            out.append(f"NEXT[render] {key}: {_step_text(st) if not n else f'checker {n}'}: python3 audits/prompt.py "
                       f"--prompt {role} {a}{nn} --write, then spawn one new general-purpose agent with the printed "
                       f"line and nothing else")
    if len(items) > 1:
        out.append("  (spawn both checkers at once, in parallel)")
    return 0, out


def _role_arg(role):
    return {v_: k_ for k_, v_ in ROLE_PROMPT.items()}[role]


def status_lines(cfg):
    out = []
    docs = [("SUMMARY", None), ("REPORT", None)]
    rr = os.path.join(root(cfg), PDF_DIR)
    if os.path.isdir(rr):
        docs += [("SIGNOFF", k[len("SIGNOFF-"):]) for k in sorted(os.listdir(rr)) if k.startswith("SIGNOFF-")]
    for d, r in docs:
        try:
            _d, _r, key = resolve(cfg, d, r)
        except Refused:
            continue
        rec = load(cfg, key)
        cur = md_sha(cfg, d, r)
        out.append(f"{key}: " + ("not begun" if not rec else
                                  f"version {rec.get('version')}, next: {_step_text(step(rec, cur))}"
                                  + (f", outcome {rec['outcome']}" if rec.get("outcome") else "")))
    return out


# --- selftest -------------------------------------------------------------------------------------------------
def selftest():
    """Scenario tests in a scratch git repository (the audit gate stood in): the normal path (B passes, both
    checkers SAME: verified), a checker DIFFERENT looped back (a fresh pair after), the md changing mid-loop (the loop restarts at
    round 1 for the new md, the stale output refused), a restart mid-save (the half-written step restored, the
    same save then recorded once), an agent crash (a failed round counts; never a stop), six FAILs ending in
    least bad (cover with B's objections; a failed cover ships without it), no PDF at all (no-pdf), the
    fingerprint guard refusing a stale or swapped PDF and accepting no-pdf, and the format checks. The checker loop
    (approver, 2026-10-23): a checker's DIFFERENT goes back to the renderer inside the same budget, then a fresh
    pair; spent, least bad with every remaining objection on its cover."""
    res = []

    def say(name, ok):
        res.append(bool(ok))
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    def refused(fn, *a, **k):
        try:
            fn(*a, **k)
        except Refused as e:
            return str(e)
        return ""

    d = tempfile.mkdtemp(prefix="render-record-")
    saved = (project.REPO, project.AUDITS, AUDIT_GATE)
    try:
        globals()["AUDIT_GATE"] = lambda c_, d_, r_: []
        project.REPO = d
        project.AUDITS = os.path.join(d, "audits")
        os.makedirs(os.path.join(project.AUDITS, "rr", "2026-01-01-abc1234"))
        G = lambda *a: subprocess.run(["git", "-C", project.AUDITS, *a], capture_output=True, text=True)
        subprocess.run(["git", "init", "-q", d], capture_output=True)
        G("init", "-q")
        G("config", "user.email", "t@t"); G("config", "user.name", "t")
        cfg = {"rounds_dir": "audits/rr", "name": "t", "involvement": "involved"}
        R = root(cfg)
        md = os.path.join(R, "REPORT.md")
        open(md, "w").write("# Report\n\n$x^2$ and `lemma_3_1`\n")
        G("add", "-A"); G("commit", "-qm", "init")
        wd = os.path.join(d, "w"); os.makedirs(wd)

        def issue(doc, rnd, role, n=None):
            """The operator's prompt.py --write for the step (an output is recorded only for an issued prompt)."""
            k_ = resolve(cfg, doc, rnd)[2]
            rec_ = load(cfg, k_)
            st_ = step(rec_, md_sha(cfg, doc, rnd))
            if st_[0] == role and not os.path.exists(prompt_file(cfg, k_, rec_, st_, n)):
                write_prompt(cfg, doc, rnd, ROLE_PROMPT[role], f"PROMPT {role}", n)

        def sv(doc, rnd, role, text, n=None):
            issue(doc, rnd, role, n)
            return save(cfg, doc, rnd, role, text, n)

        def fl(doc, rnd, role, why, n=None):
            issue(doc, rnd, role, n)
            return fail(cfg, doc, rnd, role, why, n)

        def pdf(name, data):
            p = os.path.join(wd, name)
            open(p, "wb").write(b"%PDF-1.5\n" + data)
            return p

        def A(name, data, notes="", doc="REPORT", rnd=None, src=True):
            p = pdf(name, data)
            s_ = os.path.join(wd, name + ".tex")
            open(s_, "w").write("\\documentclass{article}" + data.decode())
            return sv(doc, rnd, "A", f"made it\nRENDER_DONE " + json.dumps(
                {"pdf": p, "sha256": sha_file(p), "engine": "pdflatex", "notes": notes,
                 **({"source": s_} if src else {})}))

        def Bout(rec, verdict, blocking=(), k=None, pages="read 3 of 3", md_s=None):
            r = rec["rounds"][-1] if k is None else rec["rounds"][k - 1]
            return (f"md_sha256: {md_s or rec['md_sha256']}\npdf_sha256: {r['a']['pdf_sha256']}\npages: {pages}\n"
                    + "".join(f"- BLOCKING: [content] p.1: {b} | md: x\n" for b in blocking)
                    + "- MINOR: spacing\n" + verdict + "\n")

        def Cout(rec, verdict, findings=()):
            r_ = rec["rounds"][-1]
            return (f"md_sha256: {rec['md_sha256']}\npdf_sha256: {r_['a']['pdf_sha256']}\npages: read 2 of 2\n"
                    + "".join(f"- BLOCKING: {f}\n" for f in findings) + verdict + "\n")

        L = lambda: load(cfg, "REPORT")
        S = lambda: step(L(), md_sha(cfg, "REPORT"))
        say("before begin: next says begin; the guard refuses (no record)",
            S() == ("begin",) and "no rendering record" in " ".join(check(cfg, "REPORT")))
        globals()["AUDIT_GATE"] = lambda c_, d_, r_: ["no fresh-reader pass for report-x"]
        _nb = refused(begin, cfg, "REPORT")
        say("begin refuses an md that is not audited at its current hash (never a stop), and names the reader pass "
            "to run (smoke test: it did not say which)",
            "not audited at its current hash" in _nb and L() is None
            and "python3 audits/prompt.py --prompt fresh-reader --doc report --round" in _nb
            and "readers.py --doc report --check" in _nb)
        globals()["AUDIT_GATE"] = lambda c_, d_, r_: []
        rc, ls = begin(cfg, "REPORT")
        say("begin records the md's sha256 and commits RENDER.json alone as `render REPORT begin v1`",
            rc == 0 and L()["md_sha256"] == sha_file(md) and L()["version"] == 1
            and G("log", "-1", "--format=%s").stdout.strip() == "render REPORT begin v1"
            and G("show", "--name-only", "--format=", "HEAD").stdout.split() == ["rr/pdf/REPORT/RENDER.json"])
        say("begin again on the same md is a no-op (idempotent)", begin(cfg, "REPORT")[1][-1].startswith(
            "render REPORT: already begun") and G("log", "-1", "--format=%s").stdout.strip() == "render REPORT begin v1")
        say("next: the renderer, round 1", S() == ("A", 1) and "--prompt render-a --doc REPORT" in " ".join(next_text(cfg, "REPORT")[1]))
        say("a step other than the next one is refused (B before A; the loop's control is here)",
            "not B" in refused(save, cfg, "REPORT", None, "B", "x"))
        p, h, now = write_prompt(cfg, "REPORT", None, "render-a", "PROMPT A1")
        p2, h2, now2 = write_prompt(cfg, "REPORT", None, "render-a", "PROMPT A1")
        say("the prompt is written once and committed; issuing it again re-prints the same (re-issuable), commits nothing",
            now and not now2 and p == p2 and G("log", "-1", "--format=%s").stdout.strip() == "render REPORT prompt A"
            and "was issued" in " ".join(next_text(cfg, "REPORT")[1]))
        say("compatibility review: an issued step's line says a usage limit or capacity error is waited out, never "
            "a failure (spawn-and-seal.md's retry budget), and the run-file says so too",
            "A usage limit or a capacity error is not a failure: wait it out" in " ".join(next_text(cfg, "REPORT")[1])
            and "A usage limit or a capacity error is not a failed round" in open(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "run", "render-pdf.md"), encoding="utf-8").read())
        say("a malformed renderer output is refused, nothing recorded",
            "RENDER_DONE" in refused(save, cfg, "REPORT", None, "A", "done") and S() == ("A", 1))
        pbad = pdf("bad.pdf", b"x")
        say("a sha256 that is not the file's is refused",
            "not the sha256" in refused(save, cfg, "REPORT", None, "A", "RENDER_DONE " + json.dumps(
                {"pdf": pbad, "sha256": "0" * 64})))
        A("r1.pdf", b"one", notes="the md says 2+2=5 in section 3")
        r1 = L()["rounds"][0]
        say("A's PDF and source are copied into the record and committed (restart-safe; least bad can reach them)",
            r1["a"]["pdf"] == "pdf/REPORT/v1/r1/REPORT.pdf" and r1["a"]["source"] == "pdf/REPORT/v1/r1/source.tex"
            and G("ls-files", "rr/pdf/REPORT/v1/r1/").stdout.split() == [
                "rr/pdf/REPORT/v1/r1/REPORT.pdf", "rr/pdf/REPORT/v1/r1/prompt-A.txt", "rr/pdf/REPORT/v1/r1/source.tex"]
            and G("log", "-1", "--format=%s").stdout.strip() == "render REPORT A 1" and S() == ("B", 1))
        _noprompt = refused(save, cfg, "REPORT", None, "B", Bout(L(), "VERDICT: PASS"))
        _nofail = refused(fail, cfg, "REPORT", None, "B", "never spawned")
        say("review MED 1: a verifier's output (or a failure) for which no prompt was issued is refused, nothing "
            "recorded (an output is the answer to the prompt on record, as for lanes and readers)",
            "no prompt was issued" in _noprompt and "prompt.py --prompt render-b --doc REPORT" in _noprompt
            and "no prompt was issued" in _nofail and S() == ("B", 1))
        issue("REPORT", None, "B")
        say("B's output: a wrong md sha, a wrong PDF sha, a partial read, or a count mismatch is refused",
            "md_sha256" in refused(save, cfg, "REPORT", None, "B", Bout(L(), "VERDICT: PASS", md_s="1" * 64))
            and "pdf_sha256" in refused(save, cfg, "REPORT", None, "B", Bout(L(), "VERDICT: PASS").replace(
                r1["a"]["pdf_sha256"], "2" * 64))
            and "read every page" in refused(save, cfg, "REPORT", None, "B", Bout(L(), "VERDICT: PASS", pages="read 2 of 3"))
            and "verdict says 2" in refused(save, cfg, "REPORT", None, "B", Bout(L(), "VERDICT: FAIL (2)", ["a"]))
            and "verdict says 0" in refused(save, cfg, "REPORT", None, "B", Bout(L(), "VERDICT: PASS", ["a"]))
            and S() == ("B", 1))
        sv("REPORT", None, "B", Bout(L(), "VERDICT: FAIL (1)", ["x^2 printed as x2"]))
        say("B FAIL in round 1: the renderer gets round 2 with B's findings and its previous source",
            S() == ("A", 2) and "pdf/REPORT/v1/r1/B.md" in prompt_target(cfg, "REPORT", None, "render-a")[1]["<PREVIOUS>"]
            and "pdf/REPORT/v1/r1/source.tex" in prompt_target(cfg, "REPORT", None, "render-a")[1]["<PREVIOUS>"])
        # a restart mid-save: the files written, the commit never made
        snap = L()
        open(os.path.join(rec_dir(cfg, "REPORT"), "v1", "r2-junk.pdf"), "w").write("half")
        _write(cfg, "REPORT", dict(snap, rounds=snap["rounds"] + [{"k": 2, "a": {"status": "saved", "pdf": "x",
                                                                                 "pdf_sha256": "0" * 64}}]))
        rc_n, nl = next_text(cfg, "REPORT")
        say("restart mid-save: the uncommitted half-step is restored (B13 pattern) and the loop resumes from "
            "RENDER.json at the same step",
            "interrupted" in nl[0] and S() == ("A", 2) and not os.path.exists(
                os.path.join(rec_dir(cfg, "REPORT"), "v1", "r2-junk.pdf")) and G("status", "--porcelain").stdout == "")
        fl("REPORT", None, "A", "the agent crashed")
        say("an agent crash: `fail` closes its step, the round counts toward the budget, never a stop",
            S() == ("A", 3) and L()["rounds"][1]["a"]["status"] == "failed"
            and G("log", "-1", "--format=%s").stdout.strip() == "render REPORT A 2 failed"
            and "produced no PDF" in prompt_target(cfg, "REPORT", None, "render-a")[1]["<PREVIOUS>"])
        A("r3.pdf", b"three")
        # the md changes mid-loop (a new prepare): the stale B output is refused, the loop starts again
        bstale = Bout(L(), "VERDICT: PASS")
        open(md, "w").write("# Report\n\n$x^2$ and `lemma_3_1` (regenerated)\n")
        G("add", "-A"); G("commit", "-qm", "prepare delivery")
        say("the md changes mid-loop: a verdict on the old md is refused, next says begin",
            "changed since this loop began" in refused(save, cfg, "REPORT", None, "B", bstale) and S() == ("begin",)
            and "starts again" in " ".join(next_text(cfg, "REPORT")[1]))
        say("the guard refuses while the md has no finished rendering", bool(check(cfg, "REPORT")))
        begin(cfg, "REPORT")
        say("begin on the changed md: version 2, round 1, a fresh budget; version 1 kept in `earlier`",
            L()["version"] == 2 and S() == ("A", 1) and L()["earlier"][0]["version"] == 1
            and "superseded" in L()["earlier"][0]["outcome"]
            and os.path.exists(os.path.join(R, "pdf/REPORT/v1/r3/REPORT.pdf")))
        A("v2r1.pdf", b"v2 one", notes="the md says 2+2=5 in section 3")
        sv("REPORT", None, "B", Bout(L(), "VERDICT: PASS"))
        say("B PASS: both checkers next, in parallel", S() == ("checker", [1, 2])
            and "in parallel" in " ".join(next_text(cfg, "REPORT")[1]))
        say("review MED 1: a checker's output for which no prompt was issued is refused",
            "no prompt was issued" in refused(save, cfg, "REPORT", None, "checker", Cout(L(), "VERDICT: SAME"), n=1))
        issue("REPORT", None, "checker", 1)
        say("a checker saying SAME with a finding is malformed",
            "verdict says 0" in refused(save, cfg, "REPORT", None, "checker", Cout(L(), "VERDICT: SAME", ["x"]), n=1))
        sv("REPORT", None, "checker", Cout(L(), "VERDICT: DIFFERENT (1)", ["p.2: n+1 printed as n-1 | md: n+1"]), n=1)
        _early = refused(finish, cfg, "REPORT")
        sv("REPORT", None, "checker", Cout(L(), "VERDICT: SAME"), n=2)
        say("approver (2026-10-23): a checker's DIFFERENT sends the round back to the renderer as a normal round "
            "inside the same budget, with the checker's findings; finish is refused meanwhile",
            "not finish" in _early and S() == ("A", 2)
            and "pdf/REPORT/v2/r1/check-1.md" in prompt_target(cfg, "REPORT", None, "render-a")[1]["<PREVIOUS>"]
            and "check-2" not in prompt_target(cfg, "REPORT", None, "render-a")[1]["<PREVIOUS>"])
        A("v2r2.pdf", b"v2 two")
        sv("REPORT", None, "B", Bout(L(), "VERDICT: PASS"))
        say("...then the verifier, then a FRESH checker pair on the new round (its own prompts)",
            S() == ("checker", [1, 2])
            and prompt_target(cfg, "REPORT", None, "render-check", 1)[0].endswith("v2/r2/prompt-check-1.txt")
            and prompt_target(cfg, "REPORT", None, "render-check", 1)[1]["<PDF>"].endswith("v2/r2/REPORT.pdf"))
        sv("REPORT", None, "checker", Cout(L(), "VERDICT: SAME"), n=1)
        sv("REPORT", None, "checker", Cout(L(), "VERDICT: SAME"), n=2)
        say("both checkers SAME: finish is next", S() == ("finish",))
        out = finish(cfg, "REPORT")
        say("verified: the PDF is copied to REPORT.pdf and committed with RENDER.json (`render REPORT finish`)",
            L()["outcome"] == "verified" and L()["shipped_round"] == 2 and sha_file(os.path.join(R, "REPORT.pdf")) == L()["shipped_pdf_sha256"]
            and G("log", "-1", "--format=%s").stdout.strip() == "render REPORT finish" and "verified" in out[0]
            and G("status", "--porcelain").stdout == "")
        say("the guard passes on the delivered PDF and the md as rendered", check(cfg, "REPORT") == [])
        say("A's notes reach the human as a NOTE line nobody acts on (never the md)", any(
            "NOTE (renderer, round 1" in l and "2+2=5" in l for l in outcome_lines(L())) and "2+2" not in open(md).read())
        open(os.path.join(R, "REPORT.pdf"), "ab").write(b"swapped")
        say("the guard refuses a swapped PDF (a hash, not a reading)", "not the PDF" in " ".join(check(cfg, "REPORT")))
        G("checkout", "-q", "--", "rr/REPORT.pdf")
        open(md, "a").write("one more line\n")
        say("the guard refuses a PDF built from an older md (stale): render again, never a stop",
            "changed since its PDF was rendered" in " ".join(check(cfg, "REPORT"))
            and "never a stop" in " ".join(check(cfg, "REPORT")))
        G("checkout", "-q", "--", "rr/REPORT.md")
        say("the guard passes again once the md is the rendered one", check(cfg, "REPORT") == [])
        # least bad: SUMMARY, six FAILs (one B crash), cover, checkers disclosed
        open(os.path.join(R, "SUMMARY.md"), "w").write("# Summary\n")
        G("add", "-A"); G("commit", "-qm", "summary")
        begin(cfg, "SUMMARY")
        LS = lambda: load(cfg, "SUMMARY")
        SS = lambda: step(LS(), md_sha(cfg, "SUMMARY"))
        # rounds: 1 FAIL(3), 2 FAIL(1), 3 the verifier crashed, 4 PASS and a checker DIFFERENT(2) (the other did
        # not run), 5 FAIL(1), 6 PASS and a checker DIFFERENT(1): the budget is spent
        plan = {1: 3, 2: 1, 3: None, 4: "c2", 5: 1, 6: "c1"}
        for k in range(1, 7):
            A(f"s{k}.pdf", f"s{k}".encode(), doc="SUMMARY")
            if plan[k] is None:
                fl("SUMMARY", None, "B", "the verifier crashed")
            elif isinstance(plan[k], int):
                sv("SUMMARY", None, "B", Bout(LS(), f"VERDICT: FAIL ({plan[k]})",
                                                     [f"objection {k}.{i}" for i in range(plan[k])]))
            else:
                sv("SUMMARY", None, "B", Bout(LS(), "VERDICT: PASS"))
                m_ = int(plan[k][1])
                sv("SUMMARY", None, "checker", Cout(LS(), f"VERDICT: DIFFERENT ({m_})",
                                                           [f"p.1: checker objection {k}.{i}" for i in range(m_)]), n=1)
                if k == 4:
                    fl("SUMMARY", None, "checker", "harness refused", n=2)
                else:
                    sv("SUMMARY", None, "checker", Cout(LS(), "VERDICT: SAME"), n=2)
        say("budget spent at round 6 (no round 7): the least bad round is next for its cover -- fewest remaining "
            "objections, B's or the checkers', the later round on a tie (round 6's one checker objection over rounds 2 "
            "and 5); an unverified round ranks below every verified one",
            SS() == ("cover", 6)
            and "checker 1: p.1: checker objection 6.0" in prompt_target(cfg, "SUMMARY", None, "render-cover")[1]["<OBJECTIONS>"])
        # review HIGH: a cover nobody verified never ships -- here the first attempt lists no objection and
        # carries another body; its verifier rejects it; the second attempt passes its verifier
        p_bad = pdf("cover-bad.pdf", b"a cover with no objections and another body")
        sv("SUMMARY", None, "cover", "RENDER_DONE " + json.dumps({"pdf": p_bad, "sha256": sha_file(p_bad)}))
        _cfin = refused(finish, cfg, "SUMMARY")
        _cchk = prompt_target(cfg, "SUMMARY", None, "render-cover-check")[1]

        def CV(verdict, findings=()):
            c_ = LS()["covers"][-1]
            return (f"md_sha256: {LS()['md_sha256']}\npdf_sha256: {c_['a']['pdf_sha256']}\npages: read 2 of 2\n"
                    + "".join(f"- BLOCKING: {f}\n" for f in findings) + verdict + "\n")
        say("review HIGH: a saved cover is not shipped until a fresh verifier checks it: next is the cover's verifier, "
            "finish is refused, and the verifier is given the record's objections and the round's PDF",
            SS() == ("cover-check", 6) and "not finish" in _cfin
            and "checker 1: p.1: checker objection 6.0" in _cchk["<OBJECTIONS>"]
            and _cchk["<ROUND-PDF>"].endswith("v1/r6/SUMMARY.pdf") and _cchk["<PDF>"].endswith("cover/t1/SUMMARY.pdf"))
        sv("SUMMARY", None, "cover-check", CV("VERDICT: FAIL (2)", ["p.1: no objection listed | expected: checker 1: "
                                                                       "p.1: checker objection 6.0",
                                                                       "p.2: another body | expected: round 6 p.1"]))
        say("review HIGH: the cover's verifier rejects it: a second cover attempt, given the rejection",
            SS() == ("cover", 6) and "cover/t1/check.md" in prompt_target(cfg, "SUMMARY", None, "render-cover")[1]["<PREVIOUS>"])
        p_ = pdf("cover.pdf", b"cover + s6")
        sv("SUMMARY", None, "cover", "RENDER_DONE " + json.dumps({"pdf": p_, "sha256": sha_file(p_)}))
        sv("SUMMARY", None, "cover-check", CV("VERDICT: PASS"))
        say("after a cover its verifier passed: finish (no further loop)", SS() == ("finish",))
        _good = LS()
        _write(cfg, "SUMMARY", dict(_good, covers=_good["covers"][:-1] + [dict(_good["covers"][-1], objections=[])]))
        G("commit", "-qam", "render SUMMARY tampered")
        _tamp = refused(finish, cfg, "SUMMARY")
        G("reset", "-q", "--hard", "HEAD~1")
        say("review HIGH: a cover whose objection list is not the record's is never shipped (the list shown is the one "
            "recorded)", "other objections" in _tamp and LS() == _good)
        finish(cfg, "SUMMARY")
        ol = outcome_lines(LS())
        say("least bad: shipped with the cover listing every remaining objection verbatim (here the checker's), the "
            "md beside it; the round sent back by a checker and a checker that did not run are disclosed",
            LS()["outcome"] == "least-bad" and LS()["shipped_round"] == 6 and LS()["remaining_objections"] ==
            ["checker 1: p.1: checker objection 6.0"] and LS()["md_beside"] is True
            and any("round 4, checker 1: DIFFERENT (2) -- back to the renderer" in l for l in ol)
            and any("round 4, checker 2: did not run" in l for l in ol)
            and "authoritative" in ol[0] and check(cfg, "SUMMARY") == [] and SS() == ("done",)
            and sha_file(os.path.join(R, "SUMMARY.pdf")) == sha_file(p_) and "a fresh verifier checked" in ol[0]
            and any("cover attempt 1: rejected by its verifier (2 blocking): not shipped" in l for l in ol))
        say("the run's worst case is fixed: 6 A + 6 B + 6 checker pairs + 2 covers with their verifiers, then done",
            len(LS()["rounds"]) == 6 and SS() == ("done",))
        # a crash where the loop forks: B passes, both checkers fail to run -> verified, disclosed (never looped)
        open(os.path.join(R, "SUMMARY.md"), "a").write("v2\n")
        begin(cfg, "SUMMARY")
        A("t1.pdf", b"t1", doc="SUMMARY")
        sv("SUMMARY", None, "B", Bout(LS(), "VERDICT: PASS"))
        fl("SUMMARY", None, "checker", "crashed", n=1)
        fl("SUMMARY", None, "checker", "crashed", n=2)
        finish(cfg, "SUMMARY")
        say("review MED 2: checkers that did not run never loop and are never a pass: the outcome is not "
            "`verified`, and its first line says plainly that the checkers did not run",
            LS()["outcome"] == "checkers-did-not-run" and LS()["shipped_round"] == 1
            and sum("did not run" in l for l in outcome_lines(LS())[1:]) == 2
            and outcome_lines(LS())[0].startswith("NOT INDEPENDENTLY CHECKED")
            and "the independent checkers did not run" in outcome_lines(LS())[0]
            and "verified" not in readme_lines(cfg, "SUMMARY")[0] and check(cfg, "SUMMARY") == [])
        open(os.path.join(R, "SUMMARY.md"), "a").write("v3\n")
        begin(cfg, "SUMMARY")
        A("t2.pdf", b"t2", doc="SUMMARY")
        sv("SUMMARY", None, "B", Bout(LS(), "VERDICT: PASS"))
        sv("SUMMARY", None, "checker", Cout(LS(), "VERDICT: SAME"), n=1)
        fl("SUMMARY", None, "checker", "not needed", n=2)
        finish(cfg, "SUMMARY")
        say("review MED 2: one checker SAME and one that did not run is not `verified` either (2 recorded verdicts "
            "are needed)", LS()["outcome"] == "checkers-did-not-run"
            and "only one of the two independent checkers ran" in outcome_lines(LS())[0])
        # a failed cover, and a run that produced no PDF at all (SIGNOFF of a round)
        RN = "2026-01-01-abc1234"
        open(os.path.join(R, RN, "SIGNOFF.md"), "w").write("# Sheet\n")
        G("add", "-A"); G("commit", "-qm", "sheet")
        begin(cfg, "SIGNOFF", RN)
        for k in range(1, 7):
            fl("SIGNOFF", RN, "A", "no TeX on the machine")
        say("six rounds without a PDF: next is finish, never the checkers", step(load(cfg, f"SIGNOFF-{RN}"),
                                                                                  md_sha(cfg, "SIGNOFF", RN)) == ("finish",))
        open(os.path.join(R, RN, "SIGNOFF.pdf"), "w").write("an old sheet PDF")
        G("add", "-A"); G("commit", "-qm", "old pdf")
        finish(cfg, "SIGNOFF", RN)
        say("no-pdf: an older PDF never ships (removed), the md ships alone, disclosed; the guard accepts it",
            load(cfg, f"SIGNOFF-{RN}")["outcome"] == "no-pdf" and not os.path.exists(os.path.join(R, RN, "SIGNOFF.pdf"))
            and check(cfg, "SIGNOFF", RN) == [] and delivered(cfg, "SIGNOFF", RN) == ("no-pdf", None)
            and "no PDF" in outcome_lines(load(cfg, f"SIGNOFF-{RN}"))[0])
        open(os.path.join(R, RN, "SIGNOFF.md"), "a").write("approved stamp\n")
        begin(cfg, "SIGNOFF", RN)
        A("g1.pdf", b"g1", doc="SIGNOFF", rnd=RN)
        for k in range(1, 7):
            if k > 1:
                fl("SIGNOFF", RN, "A", "crash")
            else:
                sv("SIGNOFF", RN, "B", Bout(load(cfg, f"SIGNOFF-{RN}"), "VERDICT: FAIL (1)", ["Lean code differs"]))
        fl("SIGNOFF", RN, "cover", "the renderer crashed")
        # review HIGH: the attack -- a cover saved and its verifier never run -- never ships that cover
        p_atk = pdf("cover-atk.pdf", b"any PDF, no objections, a different body")
        sv("SIGNOFF", RN, "cover", "RENDER_DONE " + json.dumps({"pdf": p_atk, "sha256": sha_file(p_atk)}))
        _atk_fin = refused(finish, cfg, "SIGNOFF", RN)
        fl("SIGNOFF", RN, "cover-check", "not needed")
        finish(cfg, "SIGNOFF", RN)
        gs = load(cfg, f"SIGNOFF-{RN}")
        say("a failed cover, then a cover whose verifier did not run: the least bad round's own PDF ships without a "
            "cover (never the unverified one), disclosed with its objections; the md changed (the approval stamp): "
            "version 2 rendered afresh",
            "not finish" in _atk_fin
            and gs["outcome"] == "least-bad" and gs["version"] == 2 and gs["shipped_round"] == 1
            and gs["shipped_pdf_sha256"] == gs["rounds"][0]["a"]["pdf_sha256"] != sha_file(p_atk)
            and "WITHOUT the cover" in outcome_lines(gs)[0] and check(cfg, "SIGNOFF", RN) == []
            and any("Lean code differs" in l for l in outcome_lines(gs))
            and any("cover attempt 2: not verified" in l for l in outcome_lines(gs)))
        _sh0 = shown_problem(cfg, "SIGNOFF", RN)
        shown(cfg, "SIGNOFF", RN)
        _sh1 = shown_problem(cfg, "SIGNOFF", RN)
        open(os.path.join(R, RN, "SIGNOFF.md"), "a").write("a writer rerun after the question\n")
        _shr = refused(shown, cfg, "SIGNOFF", RN)
        begin(cfg, "SIGNOFF", RN)
        A("g2.pdf", b"g2", doc="SIGNOFF", rnd=RN)
        for k in range(1, 7):
            if k > 1:
                fl("SIGNOFF", RN, "A", "crash")
            else:
                sv("SIGNOFF", RN, "B", Bout(load(cfg, f"SIGNOFF-{RN}"), "VERDICT: FAIL (1)", ["Lean code differs"]))
        fl("SIGNOFF", RN, "cover", "crash")
        fl("SIGNOFF", RN, "cover", "crash")
        finish(cfg, "SIGNOFF", RN)
        _sh2 = shown_problem(cfg, "SIGNOFF", RN)
        say("review LOW: what the human was shown is recorded when asked (`shown`, committed); approval's check passes "
            "on that PDF, and refuses once another PDF ships (rendered after the question: show it and ask again); "
            "nothing is recorded as shown before it is rendered",
            _sh0[0] is None and "was recorded as shown" in _sh0[1][0]
            and _sh1[1] == [] and _sh1[0]["pdf_sha256"] == gs["shipped_pdf_sha256"]
            and G("log", "-1", "--format=%s", "--", f"rr/pdf/SIGNOFF-{RN}/RENDER.json").stdout.strip()
            and "render it first" in _shr and check(cfg, "SIGNOFF", RN) == []
            and _sh2[0] is None and "was recorded as shown" in _sh2[1][0])
        say("--round approved resolves through the approval record",
            "needs --round" in refused(resolve, cfg, "SIGNOFF", "approved"))
        json.dump({"round": RN}, open(os.path.join(R, "APPROVED_FINGERPRINTS.json"), "w"))
        say("--round approved names the approved round's sheet", resolve(cfg, "SIGNOFF", "approved")[2] == f"SIGNOFF-{RN}")
        say("README lines: one per document, with the outcome first", readme_lines(cfg, "REPORT")[0].startswith(
            "- `REPORT.pdf`: verified"))
        _co, _calls = project.commit_only, []

        def busy_once(paths, subject, repo=None):
            _calls.append(subject)
            if len(_calls) == 1:
                raise ValueError("git failed: fatal: Unable to create '.git/index.lock': File exists.")
            return _co(paths, subject, repo=repo)
        project.commit_only = busy_once
        try:
            open(os.path.join(R, "REPORT.md"), "a").write("lock test\n")
            begin(cfg, "REPORT")
        finally:
            project.commit_only = _co
        say("a save racing the other document's save (index.lock) is retried, not lost (review 3d)",
            len(_calls) == 2 and L()["md_sha256"] == sha_file(md)
            and G("log", "-1", "--format=%s").stdout.strip().startswith("render REPORT begin"))
        say("every render commit touched only pdf/ and the delivered PDF (integrity: owned by `render ` commits)",
            all(f.startswith("rr/pdf/") or f in ("rr/REPORT.pdf", "rr/SUMMARY.pdf", f"rr/{RN}/SIGNOFF.pdf")
                for c in G("log", "--format=%H", "--grep=^render ").stdout.split()
                for f in G("show", "--name-only", "--format=", c).stdout.split()))
    except Exception as e:      # noqa: BLE001 -- a scenario cut short is a failed check (mutants.py: a kill)
        say(f"the scenarios ran to the end ({type(e).__name__}: {' '.join(str(e).split())[:200]})", False)
    finally:
        project.REPO, project.AUDITS = saved[0], saved[1]
        globals()["AUDIT_GATE"] = saved[2]
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="the PDF-by-agents bookkeeping (never reads a PDF)")
    ap.add_argument("cmd", nargs="?", choices=["next", "begin", "save", "fail", "finish", "check", "shown", "status"])
    ap.add_argument("--doc")
    ap.add_argument("--round")
    ap.add_argument("--role", choices=["A", "B", "cover", "cover-check", "checker"])
    ap.add_argument("--n", type=int, choices=[1, 2])
    ap.add_argument("--why", default="")
    ap.add_argument("--project")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.error("give a command")
    try:
        cfg, _ = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    if a.cmd == "status":
        for l in status_lines(cfg):
            print(l)
        return 0
    if not a.doc:
        ap.error("--doc SUMMARY|REPORT|SIGNOFF")
    if a.cmd in ("save", "fail") and (not a.role or (a.role == "checker") != bool(a.n)):
        ap.error("--role A|B|cover|cover-check, or --role checker --n 1|2")
    try:
        if a.cmd == "next":
            rc, ls = next_text(cfg, a.doc, a.round)
        elif a.cmd == "begin":
            rc, ls = begin(cfg, a.doc, a.round)
        elif a.cmd == "save":
            rc, ls = 0, save(cfg, a.doc, a.round, a.role, sys.stdin.read(), a.n)
        elif a.cmd == "fail":
            rc, ls = 0, fail(cfg, a.doc, a.round, a.role, a.why, a.n)
        elif a.cmd == "finish":
            rc, ls = 0, finish(cfg, a.doc, a.round)
        elif a.cmd == "shown":
            rc, ls = 0, shown(cfg, a.doc, a.round)
        else:
            ps = check(cfg, a.doc, a.round)
            for p in ps:
                print("RED[deliver] " + " ".join(p.split()))
            print(f"render check: {'ok' if not ps else 'NOT ok'}" + ("" if not ps else " (never a stop: render again)"))
            return 1 if ps else 0
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    for l in ls:
        print(l)
    return rc


if __name__ == "__main__":
    sys.exit(project.run_main(main))

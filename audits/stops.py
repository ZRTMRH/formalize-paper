#!/usr/bin/env python3
"""Every stop of the run, recorded; and the one command that sets a round (or one re-vote lane) aside.

WHY THIS EXISTS.  The report promises to list every stop of the run and who cleared it (RUN.md,
G4). A stall-resolver agent used to decide hands-off stops; the simplification (RULINGS, round 2,
A7/A8) removed the causes of those stops instead, and kept only the record and two guarded
commands:

  stops.py open --cmd "<the failing check, in its exact read-only form>" [--round R]
  stops.py open --note "<what failed>" --cause CODE [--round R] [--check "<the failing script's check>"]
  stops.py close --stop S<n> --human "<the human's answer, verbatim>"
  stops.py close --stop S<n> --delegated "<what was done>"   (delegating levels; never a STOP class)
  stops.py close --stop S<n> --cured "<what was done>"   (release mode: self-cure; re-runs the recorded check)
  stops.py classify --stop S<n> --as tool-bug|interference|other --evidence TEXT   (release mode: the cure
                                                          budget is spent; the operator's judgement, recorded)
  stops.py list
  stops.py revert --stop S<n> --commit C   (release self-cure: restore the records C changed; verified)
  stops.py set-aside R --reason TEXT [--lane revote/<lane>--<item>] [--unsealable L1,L2] [--stop S<n>]
  stops.py repair-lock audits|project --reason TEXT        (a stale git index.lock; logged)
  stops.py disclose --cmd "<the check, read-only form>"     (release mode: record its DISCLOSED lines)
  stops.py disclose --note "<what failed>" --cause tool-fault --script NAME   (release mode: a crash of
                                                          a script whose job is non-blocking)
  stops.py --selftest

DISCLOSE (release mode only; project.RELEASE): a fault of class N -- presentation, bookkeeping, or a
crash of a script that serves only those -- is not a stop. The check prints it as DISCLOSED[<code>]
and passes; `disclose --cmd` re-runs the check, refuses while it fails (a blocking line is a stop)
or prints nothing to disclose, and records the DISCLOSED lines in <rounds>/stops/disclosed/D<n>.json
("stop disclose D<n>"), logged under "## Stops". The report, the decisions document and the
delivered notice KNOWN_FAULTS-run.md list every one. `open` refuses a failure all of whose causes
are disclosed in release mode.

OPEN re-runs the check itself (so the operator never types the evidence), refuses one that passes,
and records its raw output with the cause codes of its failure lines (project.CAUSES; a line
without a known code is "unknown", a stop). CLOSE re-runs the recorded check and records whether
it passes now; `--delegated` is refused under the involved level, for a STOP-class cause, and
while the check still fails. One stop is open at a time. Records: <rounds>/stops/S<n>/STOP.json
("stop S<n> open") and CLOSED.json ("stop S<n> close"), committed once, never changed or deleted
(integrity.py runs trail_problems).

SET-ASIDE gives up a round that will never be adjudicated (or one re-vote lane, adjudicated round
or not) WITHOUT deleting anything (RULINGS A7): it commits every remaining file of the round (or
lane) by name with a script-computed inventory -- <round>/ABANDONED.json, or
<round>/.abandoned/<lane>.json -- as "set-aside R [lane]". It refuses an adjudicated round; refuses
while a returned lane is unsealed (seal it first) unless that lane is named in --unsealable;
under a delegating level it refuses when the round carries a STOP-class cause (a tampering-class
lane check, or a stop of that round not closed by the human), unless --stop names a stop of the
round the human closed. Every Fail or Ambiguous item of the set-aside lanes, sealed or not, is
CARRIED FORWARD: the next adjudication (integrity.py --commit-adjudication, lanecheck --settled)
and the final report (make_report --check) refuse until an ADOPTED.md committed after the
set-aside has a row for it, and a REJECT row counts only with a REVOTE NEEDED row for the item.
After the set-aside commit nothing may touch those files (integrity.py).

RELEASE SELF-CURE (project.release_cure, U2 §4): in release mode a stop with no cause of kind human
(project.RELEASE: unproved-goal, outward-action, env-unknown, codex-approval) is cured by the operator
with the cure of its codes' kinds (project.CURES; project.cure_text) and closed `--cured`: the read-only
check the stop recorded at open (its --cmd, or a --note stop's --check, failing at open; a FORMS
command, command_problem: never a writer, never a build command in release, never the failed tool
command) is re-run and must pass; no substitute. In release, --note needs --check (kind human
excepted) and a cause code (an uncoded failure is unknown-retry); --delegated is dev mode only; a
code of kind disclose never opens a stop. A failing attempt is recorded as S<n>/CURE<k>.json ("stop
S<n> cure <k>"). The failure tally (U2 §4; fault_keys, tally_events, tally) counts, from git history,
failed cures per stop and per (check script, code) over the whole run, and openings per key and round
after a failed cure there; at project.CURE_BUDGET per stop, project.KEY_BUDGET per key or past project.OPEN_CEILING
no further --cured is accepted (under any stop id) until the operator CLASSIFIES the fault (approver, 2026-10-24:
release has four human stops, project.RELEASE_STOPS; the old "stop 4, a cure that keeps failing" is gone):
`stops.py classify --stop S<n> --as tool-bug|interference|other --evidence TEXT` ("stop S<n> classify <j>"):
tool-bug -> the tool-patch route (tool_patch.py; close --cured "tool-patch TP<k>"), interference -> stop 3, the
human's (close --human), other -> one more cure attempt, logged. A redo closes on the fresh round whose
TARGET.json names its set-aside round as redo_of and whose sealed verdicts judge its whole scope. The report, its trust table and DECISIONS.md's box list every
self-cure. Dev mode: every stop waits for the human (--human, or --delegated as the level allows).

THREAT MODEL.  A careless or improvising operator, not a forger: `--human` cannot tell the human's
words from the operator's (the same limit as `signoff.py approve --by human`, KNOWN_LIMITATIONS.md).
"""
import sys
sys.dont_write_bytecode = True
import argparse, contextlib, datetime, glob, hashlib, json, os, re, subprocess, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

STOPS = "stops"
STOP_RE = re.compile(r"^S([1-9]\d*)$")
REPAIRS = "repairs"     # stops/repairs/R<n>.json: each `repair-lock`, in the stop record (ROUND3 L4)
REPAIR_RE = re.compile(r"^R([1-9]\d*)\.json$")
DISCLOSED = "disclosed"  # stops/disclosed/D<n>.json: a fault disclosed instead of a stop (release mode)
DISCLOSED_RE = re.compile(r"^D([1-9]\d*)\.json$")
DISCLOSED_LINE = re.compile(r"^\s*DISCLOSED\[([a-z0-9-]+)\]\s*(.*)$")
FILES = ("STOP.json", "CLOSED.json")
CURE_RE = re.compile(r"^CURE([1-9]\d*)\.json$")   # S<n>/CURE<k>.json: a failed release self-cure attempt
ROUND_PAT = r"\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40}"
SET_ASIDE_RE = re.compile(r"^set-aside (\S+)(?: (\S+))?$")
# a stall's command is one of the protocol's read-only check forms (required, optional), each a
# {flag or "@positional": None or a value pattern}; anything else is opened with --note
FORMS = {
    "integrity": ({"--check": None}, {"--round": ROUND_PAT}),
    "tree_state": ({"--check": None}, {}),
    "lanecheck": ({"--round": ROUND_PAT}, {"--settled": None}),     # --kill is an action, never a check
    "phase0": ({"--readonly": None}, {"--statements": None}),
    "scope": ({"--verify": None, "--round": ROUND_PAT}, {"--full": None, "--statements": None}),
    "prompt": ({"--lanes": None, "--round": ROUND_PAT, "--verify-written": None}, {"--batch": r"\d+"}),
    "fingerprint": ({"--check": None}, {}),
    "signoff": ({"@check": None, "--round": ROUND_PAT}, {}),
    "readers": ({"--doc": r"signoff|questions|report|decisions|summary|other:[\w@./-]+", "--check": None},
                {"--round": ROUND_PAT + "|approved"}),
    "decisions": ({"--check": None}, {"--round": ROUND_PAT}),
    "make_report": ({"--check": None}, {"--index-only": None, "--delivery": None}),
    "selftest_all": ({"--fast": None}, {}),
    "audit_coverage": ({"@PATH": None}, {}),
}
SAFE_TOKEN = re.compile(r"^[\w@./:=+-]+$")
FAIL_LINE = re.compile(r"^\s*(?:FAIL|PROBLEM|GITMETA|DRIFT|MISMATCH|RED|HARD|STOP|ERROR|MISSING)(?:\b|\[)|\berror:")
CODE_RE = re.compile(r"^\s*[A-Z]+\[([a-z0-9-]+)\]")
NEVER_SET_ASIDE = ("ADOPTED.md", "INFORMAL.json", "SIGNOFF.json", "TARGET.json", "FINGERPRINTS.json",
                   "STATEMENTS_BUNDLE.md")
RUNNER = None     # the selftest's fake command runner


class Refused(ValueError):
    pass


def today():
    return datetime.date.today().isoformat()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(repo, *a, check=True):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    if check and r.returncode:
        raise Refused(f"git {' '.join(a[:3])} failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def rounds_dir(cfg):
    return os.path.join(project.REPO, cfg["rounds_dir"])


def load(path):
    try:
        return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    except ValueError:
        return None


def stop_dir(cfg, s):
    if not STOP_RE.match(s or ""):
        raise Refused(f"a stop is named S<n>, not {s!r}")
    return os.path.join(rounds_dir(cfg), STOPS, s)


def stops(cfg, rd=None):
    d = os.path.join(rd or rounds_dir(cfg), STOPS)
    names = [x for x in os.listdir(d) if STOP_RE.match(x)] if os.path.isdir(d) else []
    return sorted(names, key=lambda x: int(x[1:]))


def open_name(cfg):
    return next((s for s in stops(cfg) if not os.path.exists(os.path.join(stop_dir(cfg, s), "CLOSED.json"))), None)


def commit(paths, subject):
    try:
        return project.commit_only(paths, subject)
    except (ValueError, OSError) as e:
        raise Refused(f"commit \"{subject}\" failed: {e}")


def causes(text):
    """[{code, class, line}] of every failure line of a check's output (a line with no code, or an
    unknown one, is class "unknown": a stop)."""
    out = []
    for l in (text or "").splitlines():
        if FAIL_LINE.search(l):
            m = CODE_RE.match(l)
            code = m.group(1) if m else "unknown"
            out.append({"code": code, "class": project.cause_class(code), "line": l.strip()[:300]})
    return out


def only_left_out(doc, out):
    """Does the re-run check fail only on the faults its stop left out (a PDF fault, a delivery precondition:
    project.NEVER_STOP; attack 8)? Then the stop's own faults are cured."""
    cs = causes(out)
    return bool(doc.get("left_out")) and bool(cs) and all(c["code"] in project.NEVER_STOP for c in cs)


def pdf_route(txt):
    """Where a PDF fault a check printed goes (attack 8): rendering it again by agents (render_record.py,
    PDF-AGENTS). An older run's `pdf` lines only: no script emits the code any more."""
    docs = [d for d in ("SUMMARY", "REPORT", "SIGNOFF") if re.search(rf"\b{d}\.(?:pdf|md|tex)\b", txt or "")]
    return " and ".join(f"python3 audits/render_record.py next --doc {d}" + (" --round <R>" if d == "SIGNOFF" else "")
                        for d in docs or ["SUMMARY|REPORT|SIGNOFF"])


def stop_class(doc):
    """The STOP classes among a stop's causes (sorted), empty when the operator may close it."""
    return sorted({c["class"] for c in doc.get("causes") or [] if c["class"] in project.STOP_CLASSES})


def command_problem(cmd, cfg):
    """None if `cmd` is one of the protocol's read-only check forms (FORMS) or, in dev mode only, a build
    command of the project, else why not. In release mode only a FORMS command is a stop's check: a
    release stop closes by re-running it (`close --cured`), and a writer is never a check (U2 §4, H1)."""
    if re.search(r"[|&;<>$`()\\\n'\"*?]", cmd or ""):
        return "a stop's command is one plain command: no shell metacharacters, quotes or redirections"
    argv = (cmd or "").split()
    if not argv:
        return "empty command"
    if " ".join(argv) in [" ".join(c.split()) for c in cfg.get("build_cmds") or []] \
            or argv == ["lake", "exe", "cache", "get"]:
        if project.mode(cfg) == "release":
            return ("release mode: a stop's check is one of the protocol's read-only check commands (python3 "
                    "audits/<check>.py ...); a build is checked by python3 audits/phase0.py --readonly")
        return None
    a = [x for x in argv if x != "-B"]
    if len(a) < 2 or a[0] not in ("python3", "python"):
        return ("only the protocol's read-only check commands (python3 audits/<check>.py …, the project's "
                "build commands, lake exe cache get) can be a stop's command; anything else is --note")
    m = re.fullmatch(r"(?:\./)?audits/([a-z_0-9]+)\.py", a[1])
    if not m or m.group(1) not in FORMS:
        return f"{a[1]} is not one of the check scripts a stop may name ({', '.join(sorted(FORMS))})"
    req, opt = FORMS[m.group(1)]
    toks, seen, i = a[2:], set(), 0
    while i < len(toks):
        t = toks[i]
        if not SAFE_TOKEN.match(t):
            return f"argument {t!r} is not allowed"
        if t == "--project" and i + 1 < len(toks) and re.fullmatch(r"[\w.-]+", toks[i + 1]):
            i += 2
            continue
        if t.startswith("--"):
            if t not in req and t not in opt:
                return f"{t} is not part of the read-only form of {m.group(1)}.py"
            spec = req.get(t, opt.get(t))
            if spec is not None:
                if i + 1 >= len(toks) or not re.fullmatch(spec, toks[i + 1]):
                    return f"{t} needs a value matching {spec}"
                i += 1
            seen.add(t)
        elif f"@{t}" in req:
            seen.add(f"@{t}")
        elif "@PATH" in req and "@PATH" not in seen:
            seen.add("@PATH")
        else:
            return f"{t!r} is not part of the read-only form of {m.group(1)}.py"
        i += 1
    missing = [k for k in req if k not in seen]
    if missing:
        return f"the read-only form of {m.group(1)}.py needs {', '.join(missing)}"
    return None


def run_cmd(argv, timeout=7200):
    if RUNNER:
        return RUNNER(argv)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(argv, cwd=project.REPO, capture_output=True, text=True, env=env, timeout=timeout)
        out, rc = (r.stdout + r.stderr), r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (str(e.stdout or "") + str(e.stderr or "") + f"\n(timed out after {timeout} s)"), 124
    except OSError as e:
        out, rc = str(e), 127
    return rc, out


def tag(cfg, reversal="none"):
    return (f"[DELEGATED {today()}, operator under {project.involvement(cfg)} (intake); reversal: {reversal}]")


# --- open / close / list ----------------------------------------------------------------------

def _valid_date(d):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d))) and str(d) <= today()


def finish_interrupted(cfg):
    """Complete a stop command killed between writing its file and committing it (ROUND3 L1; R3c N3).
    A file found on disk is never committed as found: the record is recomputed now (a `--cmd` stop:
    the recorded check re-run, its exit, output and causes, refused if it passes now; a `--note`
    stop: the operator's note and cause code, as `open` writes them; a close: the re-run and every
    `--delegated` refusal) and the uncommitted STOP.json ("stop S<n> open") or CLOSED.json ("stop S<n>
    close", with its RUN_LOG line) is committed only when it equals that record (its date may be any
    day up to today). Otherwise Refused, the file left in place, with the exact recovery. Returns
    [what was done]; run by `open` and `close` before anything else."""
    done = []
    audits = project.AUDITS
    for s in stops(cfg):
        sd = stop_dir(cfg, s)
        for f in cure_attempts(cfg, s):
            p = os.path.join(sd, f)
            if not committed(audits, p):
                raise Refused(f"an uncommitted {s}/{f} (an interrupted cure attempt) is never committed as found. "
                              f"Recover: rm {os.path.relpath(p, audits)}, then run the cure's close again")
        for f, step in (("STOP.json", "open"), ("CLOSED.json", "close")):
            p = os.path.join(sd, f)
            if not os.path.exists(p) or committed(audits, p):
                continue
            rel = os.path.relpath(p, audits)
            doc = load(p)
            if step == "open":
                redo = (f"python3 audits/stops.py open --cmd \"{doc.get('command')}\"" if isinstance(doc, dict) and doc.get("command")
                        else "python3 audits/stops.py open --note \"<what failed>\" --cause CODE") + \
                       (f" --round {doc.get('round')}" if isinstance(doc, dict) and doc.get("round") else "")
            else:
                sdoc_ = load(os.path.join(sd, "STOP.json")) or {}
                redo = (f"python3 audits/stops.py close --stop {s} --cured \"<what was done>\" (release: it re-runs the "
                        f"recorded check)" if cure_plan(cfg, sdoc_) else
                        f"python3 audits/stops.py close --stop {s} --human \"<the human's answer, verbatim>\""
                        + (" (or --delegated)" if project.mode(cfg) != "release" else ""))
            recover = f"Recover: rm {rel}" + (f" && rmdir {os.path.relpath(sd, audits)}" if step == "open" else "") + f", then {redo}"
            try:
                if not isinstance(doc, dict) or doc.get("stop") != s:
                    raise Refused("it is cut short or not a record of this stop")
                if step == "open":
                    cs = doc.get("causes") if isinstance(doc.get("causes"), list) else []
                    code = str(cs[0].get("code")) if len(cs) == 1 and isinstance(cs[0], dict) else ""
                    want = _stop_doc(cfg, doc.get("command"), None if doc.get("command") else (doc.get("note") or ""),
                                     code, doc.get("round"), check=doc.get("check"))
                    want["stop"] = s
                else:
                    sdoc = load(os.path.join(sd, "STOP.json")) or {}
                    by = doc.get("by")
                    if by not in ("human", "operator", "cure"):
                        raise Refused(f"its \"by\" is {by!r}")
                    want = _close_doc(cfg, s, sdoc, human=doc.get("text") if by == "human" else None,
                                      delegated=doc.get("text") if by == "operator" else None,
                                      cured=doc.get("text") if by == "cure" else None)
            except Refused as e:
                raise Refused(f"an uncommitted {s}/{f} (an interrupted `{step}`) is never committed as found, and "
                              f"it cannot be completed now: {e}. {recover}")
            if _valid_date(doc.get("date")):
                want["date"] = doc["date"]
            if doc != want:
                diff = sorted(k for k in set(doc) | set(want) if doc.get(k) != want.get(k))
                raise Refused(f"an uncommitted {s}/{f} (an interrupted `{step}`) differs from the record computed now "
                              f"({', '.join(diff)}): it is never committed as found. {recover}")
            commit([p], f"stop {s} {step}")
            if step == "close":
                project.log_append(cfg, "Stops", f"- stop {s} closed by {doc.get('by')}: {doc.get('text', '')} "
                                                 f"(an interrupted close, completed)")
            done.append(f"committed {s}/{f} as \"stop {s} {step}\" (an interrupted `{step}`, completed)")
    return done


def _stop_doc(cfg, cmd, note, cause, round_name, check=None):
    """The STOP.json record of `open` (without its number), computed now: the check re-run (--cmd), or
    the operator's note and cause code (--note), with the failing script's read-only check (--check)
    re-run now: it must fail, and it is the command a release self-cure re-runs (review H1). Refused
    as `open` refuses."""
    if cmd and check:
        raise Refused("--check is for a --note stop: a --cmd stop's check is its --cmd")
    if bool(cmd) == bool(note):
        raise Refused("give exactly one of --cmd (a failing check, in its read-only form, re-run here) or "
                      "--note (a failed tool call) with --cause")
    if round_name and not re.fullmatch(ROUND_PAT, str(round_name)):
        raise Refused(f"{round_name!r} is not a round name")
    doc = {"date": today(), "involvement": project.involvement(cfg), "mode": project.mode(cfg),
           "round": round_name or None}
    if cmd:
        why = command_problem(cmd, cfg)
        if why:
            raise Refused(why)
        rc, out = run_cmd(cmd.split())
        if rc == 0:
            raise Refused(f"`{cmd}` exits 0 now: there is no stop to record")
        normal = [m.group(1) for m in re.finditer(r"^\s*NOTE\[([a-z0-9-]+)\]", out, re.M)
                  if project.cause_class(m.group(1)) == "info"]
        if normal and not causes(out):
            # e.g. fingerprint --check exit 4 (nothing approved) during a re-approval (RULINGS A9)
            raise Refused(f"`{cmd}` reports a normal state ({', '.join(normal)}), not a failure: there is no stop to record")
        doc.update(command=" ".join(cmd.split()), exit=rc, output=out, causes=causes(out) or
                   [{"code": "unknown", "class": "unknown", "line": f"exit {rc} with no failure line"}])
    else:
        if not cause:
            raise Refused("--note needs --cause CODE (project.CAUSES; e.g. tool-call)")
        if cause in project.NEVER_STOP:
            # ADDENDUM N1 (both modes): a delivery code never opens a stop; nor does a PDF (agents render it again)
            raise Refused(f"{cause} is never a stop (a precondition of project.py --deliver, or a PDF the rendering "
                          f"agents make again: render_record.py): {project.CAUSES[cause][1]}")
        rel = project.mode(cfg) == "release"
        if rel and cause not in project.CAUSES:
            raise Refused(f"release mode: {cause!r} is not a cause code (project.CAUSES); a failure no code covers "
                          f"is --cause unknown-retry, with --check \"<the read-only check of the step that failed>\"")
        doc.update(command=None, exit=None, output="", note=" ".join(str(note).split()),
                   causes=[{"code": cause, "class": project.cause_class(cause), "line": "(operator's note)"}])
        if rel and check is None and _specific_closer(cause) and (doc["round"] or "{R}" not in project.CLOSER[cause]):
            check = project.closer(cause, doc["round"])     # the code's own closer is the check (review H-1)
        why = closer_problem(cfg, dict(doc, check=check))
        if why:
            raise Refused(f"release mode: {why}")
        if check:
            why = command_problem(check, cfg)
            if why:
                raise Refused(f"--check: {why}")
            rc, out = run_cmd(check.split())
            if rc == 0:
                raise Refused(f"--check `{check}` exits 0 now: it is not the failing step's check. Name the "
                              f"read-only check of the step that failed; if no check fails, there is no stop to "
                              f"record: re-run the tool (the unknown-retry route); a fault only the human can fix is "
                              f"--cause env-unknown (a human stop)")
            doc.update(check=" ".join(check.split()), exit=rc, output=out)
        elif rel and project.release_kind(cause) not in ("human", "disclose") and cause != "tool-bug":
            # tool-bug without --check (review MED-2): a pinned writer (prompt.py, signoff.py approve ...) that keeps
            # crashing while every read-only check passes has no check to re-run: the tool-patch route (OPERATOR-PATCH:
            # tool_patch.py; closed --cured "tool-patch TP<k>", re-running the patch's regression test), never
            # env-unknown
            raise Refused(f"release mode: a --note stop of {cause} is self-cured by re-running the read-only check of "
                          f"the step that failed, so open it with --check \"<that check, failing now>\" (integrity.py "
                          f"--check for setup, lanecheck.py --round <R> for a round, phase0.py --readonly for the "
                          f"build); the failed tool command itself is never the check")
    return doc


def _canon(cmd, name=None):
    """A check command as compared with its code's closer: -B dropped, and `--project NAME` when NAME is this
    project's `name` (a check naming another project is another check: re-check V6)."""
    a, out, i = (cmd or "").split(), [], 0
    while i < len(a):
        if a[i] == "-B":
            i += 1
        elif a[i] == "--project" and i + 1 < len(a) and name is not None and a[i + 1] == name:
            i += 2
        else:
            out.append(a[i])
            i += 1
    return " ".join(out)


def _specific_closer(code):
    """True when release closes a stop of `code` by a check of its own (project.CLOSER), not "@check"."""
    return project.closer(code) not in (None, "@check")


def closer_problem(cfg, doc):
    """None unless `doc` is a release `--note` stop record whose check is not exactly its codes' closer,
    then why (review H-1): a code with a closer of its own (project.CLOSER, not "@check") is closed by
    that check, its round the stop's own (`--round`, required for a round-bound closer), never by
    another check that happens to fail at open and pass later. A `--cmd` stop re-runs its own --cmd."""
    if project.mode(cfg) != "release" or doc.get("command"):
        return None
    for code in sorted({str(c.get("code")) for c in doc.get("causes") or []}):
        if not _specific_closer(code):
            continue
        if "{R}" in project.CLOSER[code] and not doc.get("round"):
            return (f"a stop of {code} is closed by `{project.closer(code)}`: give the round it concerns "
                    f"(--round <R>)")
        want = project.closer(code, doc.get("round") or "<R>")
        if _canon(doc.get("check"), cfg.get("name")) != want:
            return (f"a stop of {code} is closed by exactly `{want}` (its code's closer, project.CLOSER), so that "
                    f"is its --check (or leave --check out), not `{doc.get('check')}`")
    return None


def cure_cmd(doc):
    """The command a release self-cure of stop record `doc` re-runs: its --cmd, or the --check recorded
    at open (a --note stop). None: nothing to re-run (never a self-cure)."""
    return (doc or {}).get("command") or (doc or {}).get("check") or None


# --- the failure tally (U2 §4 M1, B1b) ----------------------------------------------------------------
# One rule. A fault is keyed by (check script, cause code), never by stop id or round: a --cmd stop by its
# command's codes, a --note stop by every code its --check printed at open ((script, "unknown") for an
# uncoded failure), whatever code the operator gave it (a renamed or relabelled code still meets the fault
# the check reports; review attack B). A --note stop also has the key ("--note", its code, the round, its
# check script), the retry codes and commit-refused sharing one ("--note", "retry", R, script; re-check V4): it
# counts openings only, never failed cures. It carries the check script (B1b re-check H3): unrelated tool-call
# stops on different checks after one failed cure are not one fault; a repeated fault on the same check is (a
# rotated check script still meets the per-stop cap and the (script, code) budget). The round
# of a --note key is the newest round scoped before the stop opened, from git, never the stop's own --round
# (re-check R1). From git history over the whole run, never reset: each failing --cured re-run is a failed
# cure, charged to the stop itself and to its keys -- or, when a redo's fresh round fails with other codes Y
# only, to (script, Y) (U2 §4 "Closing a redo" 3); each "stop S<n> open" commit is an opening of its keys in
# the newest round scoped before it ("pre-round" before any). Passes are not counted. The cure budget is spent
# (stops.py classify, never a stop of its own) by a stop with CURE_BUDGET failed cures of its own (the per-stop cap), a (script, code) key with KEY_BUDGET
# failed cures in the run, or a key opened more than OPEN_CEILING times in one round.
RETRY = frozenset({"unknown-retry", "tool-call", "git-error", "unknown", "uncoded", "tool-bug", "commit-refused"})
# a tool-patch close (OPERATOR-PATCH): `close --cured "tool-patch TP<k>"`, TP<k> applied for this stop (tool_patch.py)
TP_TEXT = re.compile(r"^tool-patch (TP[1-9]\d*)$")
CLASSIFY_RE = re.compile(r"^CLASSIFY([1-9]\d*)\.json$")   # S<n>/CLASSIFY<j>.json: a spent budget classified
CLASSES_AT_BUDGET = ("tool-bug", "interference", "other")
PRE_ROUND = "pre-round"


def _script(cmd):
    """The registry name of a check command's script (flags and -B dropped), else the command itself."""
    a = [x for x in (cmd or "").split() if x != "-B"]
    m = next((re.fullmatch(r"(?:\./)?audits/([a-z_0-9]+)\.py", x) for x in a if x.endswith(".py")), None)
    return m.group(1) if m else " ".join(a)


def fault_keys(doc, rnd=PRE_ROUND):
    """frozenset of the fault keys of stop record `doc` opened in round `rnd` (see above)."""
    doc = doc or {}
    scr = _script(cure_cmd(doc))
    cs = [str(c.get("code")) for c in doc.get("causes") or []]
    if doc.get("command"):
        return frozenset((scr, c) for c in cs)
    keys = {("--note", "retry" if c in RETRY else c, rnd, scr) for c in cs[:1]}
    if doc.get("check"):
        keys |= {(scr, y) for y in {c["code"] for c in causes(doc.get("output"))} or {"unknown"}}
    return frozenset(keys)


def charged_keys(doc, rec, rnd=PRE_ROUND):
    """The keys a failed cure attempt `rec` of stop record `doc` is charged to: the stop's own, or, when a redo's
    re-run (on the fresh round) fails with other codes only, (script, Y) for each such code Y."""
    own = fault_keys(doc, rnd)
    codes = {str(c.get("code")) for c in (doc or {}).get("causes") or []}
    if any(project.release_kind(c) == "redo" for c in codes):
        ys = {c["code"] for c in causes(((rec or {}).get("rerun") or {}).get("output_tail"))} - {"unknown"}
        if ys and not ys & codes:
            lc_out = str(((rec or {}).get("rerun") or {}).get("output_tail") or "").startswith("$ ")
            scr = _script((rec or {}).get("redo_lanecheck") if lc_out else (rec or {}).get("check") or cure_cmd(doc))
            return frozenset((scr, y) for y in ys)
    return own


def round_problem(doc, rd=None):
    """Refused when stop record `doc` names a round inconsistently (re-check R1): a round that is not a round of
    this run (a directory under `rd` with its TARGET.json), or a stop round its re-run command contradicts. Such
    a record's self-cure is the human's."""
    a = (cure_cmd(doc) or "").split()
    rr = a[a.index("--round") + 1] if "--round" in a and a.index("--round") + 1 < len(a) else None
    # RELEASE-SWEEP S4: checked at `open`, before STOP.json is committed (a mistyped --round is refused there, never
    # recorded); later, a round directory that lost its TARGET.json is restored (git checkout), never the human's. A
    # `no-round` stop names exactly the round it lacks: it is cured by scoping (or naming) the round
    lacks = "no-round" in {str(c.get("code")) for c in doc.get("causes") or []} \
        or "no-round" in {c["code"] for c in causes(doc.get("output"))}
    for r in (doc.get("round"), rr):
        if r and re.fullmatch(ROUND_PAT, str(r)) and not lacks \
                and not (rd and os.path.isfile(os.path.join(rd, str(r), "TARGET.json"))):
            raise Refused(f"stop {doc.get('stop') or '(new)'} names round {r}, which is not a round of this run (no "
                          f"{r}/TARGET.json): name a round of this run (a mistyped --round), or restore its "
                          f"TARGET.json (git checkout -- <rounds dir>/{r}/TARGET.json); never a human stop")
        if r and not re.fullmatch(ROUND_PAT + "|approved", str(r)):
            raise Refused(f"stop {doc.get('stop') or '(new)'} names {r!r} as its round: give a round name")
    if doc.get("round") and rr and rr != "approved" and doc["round"] != rr:
        raise Refused(f"stop {doc.get('stop') or '(new)'} is recorded for round {doc['round']} but re-runs "
                      f"`{' '.join(a)}` (round {rr}): give --round the round its check names")


def _show_json(audits, rev, rel):
    r = subprocess.run(["git", "-C", audits, "show", f"{rev}:{rel}"], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


STOP_SUBJ = re.compile(r"^stop (S[1-9]\d*) (open|close|cure ([1-9]\d*))$")


def tally_events(cfg, audits=None, rd=None):
    """[(event, stop, keys, round)] of the run, oldest first, read from the commits themselves (a deleted CURE
    file, a re-opened stop or a new stop id resets nothing): "open" (each "stop S<n> open" commit; round: the
    newest round scoped before it, PRE_ROUND before any), "fail" (a failed cure attempt; keys: charged_keys) and
    "pass" (a self-cure close). Refused when such a record cannot be read (fail closed: the human)."""
    audits = audits or project.AUDITS
    rd = rd or rounds_dir(cfg)
    rel = os.path.relpath(rd, audits)
    pre = "" if rel == "." else rel + "/"
    out, cur, at, order, active = [], None, {}, {}, set()
    unreadable = UNREADABLE_TALLY.setdefault(os.path.abspath(rd), [])
    del unreadable[:]
    newest = lambda: max(active, key=order.get) if active else PRE_ROUND
    commits = []
    for line in _log(audits, "--reverse", "--format=@%H %s", "--name-status", "--", pre + STOPS,
                     f":(glob){pre}*/*.json", f":(glob){pre}*/ADOPTED.md").splitlines():
        if line.startswith("@"):
            h, _, subj = line[1:].partition(" ")
            cur = [h, subj, []]
            commits.append(cur)
        elif cur and line.strip():
            st, _, p = line.partition("\t")
            cur[2].append((st.strip(), p.strip()))
    for h, subj, files in commits:
        for st, p in sorted(files, key=lambda f: not f[1].endswith("/TARGET.json")):
            r_ = os.path.basename(os.path.dirname(p))
            if not st.startswith("A") or not re.fullmatch(ROUND_PAT, r_):
                continue
            if os.path.basename(p) == "TARGET.json":
                order.setdefault(r_, len(order))
            elif r_ in order and _verdict_or_adjudication(os.path.basename(p)):
                active.add(r_)      # the bucket: the newest round with a verdict file or adjudicated (compat LOW)
        m = STOP_SUBJ.match(subj)
        if not m:
            continue
        s, what = m.group(1), m.group(2)
        srel = f"{pre}{STOPS}/{s}/"
        sdoc = _show_json(audits, h, srel + "STOP.json")
        rec = None if what == "open" else _show_json(audits, h, srel + (f"CURE{m.group(3)}.json" if m.group(3) else "CLOSED.json"))
        if what == "close" and (rec or {}).get("by") not in (None, "cure"):
            continue
        if sdoc is None or (what != "open" and (rec is None or rec.get("by") != "cure")):
            # RELEASE-SWEEP S4: an unreadable committed record never makes the stop the human's. It is counted the
            # conservative way -- an opening, or a FAILED cure of that stop (it spends budget, never frees any) --
            # and trail_problems flags the record itself ([stop-trail]: the reviewed acknowledgment, integrity.py
            # --ack-request, when no cure clears it)
            ks_ = fault_keys(sdoc, at.get(s, newest())) if sdoc else frozenset()
            if what == "open":
                at[s] = newest()    # (an unreadable record)
                out.append(("open", s, ks_, at[s]))
            else:
                out.append(("fail", s, ks_, at.get(s, newest())))
            unreadable.append(f"the stop record of commit {h[:11]} (\"{subj}\") cannot be read: counted as "
                              + ("an opening" if what == "open" else "a failed cure"))
            continue
        if what == "open":
            at[s] = newest()
            out.append(("open", s, fault_keys(sdoc, at[s]), at[s]))
        elif m.group(3) or not (rec.get("rerun") or {}).get("passes"):
            out.append(("fail", s, charged_keys(sdoc, rec, at.get(s, newest())), at.get(s, newest())))
        else:
            out.append(("pass", s, fault_keys(sdoc, at.get(s, newest())), at.get(s, newest())))
    return out


UNREADABLE_TALLY = {}     # {rounds dir: [why]} of the records the last tally_events could not read (trail_problems)


def _verdict_or_adjudication(base):
    """Is a file `base` added to a round directory a lane's verdict file or the round's adjudication (ADOPTED.md)?
    A round only scoped (its TARGET.json) is not yet a bucket of the openings ceiling."""
    import lanecheck
    return base == "ADOPTED.md" or (base.endswith(".json") and base not in lanecheck.RECORD_JSON
                                    and not base.startswith("APPROVED"))


def _label(k):
    return (f"--note {k[1]}" + (f" checked by {k[3]}" if len(k) > 3 else "") + f" in round {k[2]}"
            if k[0] == "--note" else f"{k[1]} from {k[0]}")


def tally(events, s, keys=()):
    """(failed, why) for stop `s` after `events`: the failed cures of `s` itself (its attempt count, within the
    per-stop cap), and [why the budget is spent] (empty: within the per-stop cap, the run-wide budget of each of its keys
    -- its own keys, `keys`, and every key its own failed attempts were charged to -- and the openings ceiling)."""
    failed, failed_r, opened, bucket, mine, own = {}, {}, {}, PRE_ROUND, set(keys), 0
    for ev, s_, ks, r in events:
        if ev == "open":
            for k in ks:    # counted only once the key has had a failed cure in that round (compat MED (b))
                if failed_r.get((k, r)):
                    opened[(k, r)] = opened.get((k, r), 0) + 1
            if s_ == s:
                bucket = r
                mine |= set(ks)
        elif ev == "fail":
            for k in ks:
                failed[k] = failed.get(k, 0) + 1
                failed_r[(k, r)] = failed_r.get((k, r), 0) + 1
            if s_ == s:
                own += 1
                mine |= set(ks)
    why = []
    if own >= project.CURE_BUDGET:      # the per-stop cap (review attack A): whatever codes its failures showed
        why.append(f"stop {s} had {own} failed self-cure(s) of its own, the per-stop cap ({project.CURE_BUDGET}), "
                   f"whatever codes they showed")
    for k in sorted(mine):
        if len(k) == 2 and failed.get(k, 0) >= project.KEY_BUDGET:     # a --note key counts openings only
            why.append(f"`{_label(k)}` had {failed[k]} failed self-cure(s) in this run, its retry budget "
                       f"({project.KEY_BUDGET}), counted across stops")
        if opened.get((k, bucket), 0) > project.OPEN_CEILING:
            why.append(f"`{_label(k)}` was opened {opened[(k, bucket)]} times in round {bucket} after a failed "
                       f"self-cure there, past the ceiling ({project.OPEN_CEILING} per round)")
    return own, why


def cures_spent(cfg, doc, audits=None, rd=None):
    """(failed, why) of stop record `doc` now (tally); Refused on an inconsistent record (round_problem),
    history or not, or an unreadable history."""
    round_problem(doc, rd or rounds_dir(cfg))
    ev = tally_events(cfg, audits, rd)
    rnd = next((e[3] for e in reversed(ev) if e[0] == "open" and e[1] == doc.get("stop")), None)
    return tally(ev, doc.get("stop"), fault_keys(doc, rnd or _newest(cfg, audits, rd)))


def _newest(cfg, audits=None, rd=None):
    """The newest round scoped that has a verdict file or is adjudicated (PRE_ROUND before any), as tally_events
    dates an opening now."""
    audits = audits or project.AUDITS
    rel = os.path.relpath(rd or rounds_dir(cfg), audits)
    pre = "" if rel == "." else rel + "/"
    order, active = {}, set()
    for line in _log(audits, "--reverse", "--diff-filter=A", "--format=", "--name-only", "--",
                     f":(glob){pre}*/*.json", f":(glob){pre}*/ADOPTED.md").splitlines():
        r_, b_ = os.path.basename(os.path.dirname(line.strip())), os.path.basename(line.strip())
        if not re.fullmatch(ROUND_PAT, r_):
            continue
        if b_ == "TARGET.json":
            order.setdefault(r_, len(order))
        elif r_ in order and _verdict_or_adjudication(b_):
            active.add(r_)
    return max(active, key=order.get) if active else PRE_ROUND


def _with_round(cmd, r):
    """`cmd` with the value of its --round replaced by `r` (unchanged when it has none)."""
    a = (cmd or "").split()
    if "--round" in a and a.index("--round") + 1 < len(a):
        a[a.index("--round") + 1] = r
    return " ".join(a)


def redo_round(cfg, s, doc):
    """The fresh round on which a release self-cure of redo stop `s` (record `doc`) re-runs its check, once its
    round was set aside by this stop (set-aside <R> --stop S<n>), else None (addendum U2.1 N5, review MED-3):
    a set-aside round keeps its faulty files as record, so `lanecheck --round <R>` (or `scope --verify`) on
    it fails for ever; the redo is checked on the round that redoes it (U2 §4 "Closing a redo"): the newest
    round scoped after the set-aside whose TARGET.json names it as `_meta.redo_of` (scope.py writes it from the
    open stop's set-aside round, redo_target) and that covers its scope and has run its lanes
    (redo_scope_problem). Refused while there is none (no cure attempt is spent); refused for the human when
    a TARGET.json of the lineage cannot be read."""
    r = doc.get("round")
    if not r or "redo" not in (cure_plan(cfg, doc) or []):
        return None
    mk = marker_path(os.path.join(rounds_dir(cfg), r))
    if not os.path.exists(mk) or (load(mk) or {}).get("stop") != s or not committed(project.AUDITS, mk):
        return None
    at = _last_commit(project.AUDITS, mk)
    first = lambda p: (git(project.AUDITS, "log", "--diff-filter=A", "--format=%H", "--", os.path.relpath(
        os.path.join(p, "TARGET.json"), project.AUDITS), check=False).split() or [None])[-1]
    fresh = []
    for p in project.rounds(cfg):
        if os.path.basename(p) == r or not _after(project.AUDITS, at, first(p)):
            continue
        ro = redo_of(p)
        if ro is False:
            # RELEASE-SWEEP S5: a round whose TARGET.json cannot be read is no fresh round of this redo (restore the
            # file with git checkout, or scope another fresh round); never a human stop
            continue
        if ro == r:
            fresh.append(os.path.basename(p))
    why = None
    for new in reversed(fresh):
        why = redo_scope_problem(cfg, r, new)
        if not why:
            return new
    raise Refused(f"round {r} is set aside by {s}'s self-cure: its check is re-run on the fresh round that redoes "
                  f"it (TARGET.json redo_of {r}), and there is none yet ({why or 'none is scoped'}; scope a new round "
                  f"while {s} is open, so scope.py records redo_of, and run its review: prompt.py 3), then close "
                  f"--cured again (no cure attempt was spent)")


def redo_of(round_dir):
    """The round a round redoes (its TARGET.json `_meta.redo_of`), None when it redoes none, False when its
    TARGET.json cannot be read (unreadable lineage)."""
    t = load(os.path.join(round_dir, "TARGET.json"))
    if not isinstance(t, dict) or not isinstance(t.get("_meta", {}), dict):
        return False
    ro = t.get("_meta", {}).get("redo_of")
    return ro if ro is None or (isinstance(ro, str) and re.fullmatch(ROUND_PAT, ro)) else False


def redo_target(cfg):
    """The round a round scoped now redoes, which scope.py records as TARGET.json `_meta.redo_of`: the round of
    the open stop, when that stop set it aside (its set-aside marker names the stop); else None."""
    s = open_name(cfg)
    r = (load(os.path.join(stop_dir(cfg, s), "STOP.json")) or {}).get("round") if s else None
    if not r or not re.fullmatch(ROUND_PAT, str(r)):
        return None
    return r if (load(marker_path(os.path.join(rounds_dir(cfg), r))) or {}).get("stop") == s else None


def redo_scope_problem(cfg, old, new, rd=None):
    """None when round `new` can be the fresh round redoing set-aside round `old`, else why (re-check N5; B1b
    review attacks C, C2): every lane of `new` has run and is sealed, and for every lane of `old`'s scope the
    sealed verdicts of `new` (lanecheck._sealed_items: the bytes the seal covers, schema-valid) judge every item
    of it -- a verdict file that judged nothing, or none of those items, has redone nothing."""
    import lanecheck
    rd = rd or rounds_dir(cfg)
    ld = lambda r: load(os.path.join(rd, str(r), "TARGET.json"))
    o, n = ld(old), ld(new)
    if not isinstance(o, dict) or not isinstance(n, dict):
        return f"the TARGET.json of round {old if not isinstance(o, dict) else new} cannot be read"
    items = lambda t: {k: v for k, v in t.items() if not str(k).startswith("_") and isinstance(v, list)}
    rn = os.path.join(rd, str(new))
    files = {}
    for f in lanecheck.lane_files(rn):
        if os.path.dirname(f) == rn:
            files.setdefault(lanecheck.lane_base(f[:-len(".json")]), []).append(f)
    nov = sorted(lane for lane in set(items(n)) | set(items(o)) if not files.get(lane))
    if nov:
        return f"round {new} has no verdicts of lane(s) {', '.join(nov)} yet"
    judged = {}
    for lane in sorted(set(items(n)) | set(items(o))):
        for f in files.get(lane, []):
            got = lanecheck._sealed_items(f)
            if got is None:
                return f"round {new}'s verdict file {os.path.basename(f)} is not sealed (or changed after its seal)"
            judged.setdefault(lane, set()).update(got)
    miss = sorted(f"{lane}: {x}" for lane, xs in items(o).items() for x in xs
                  if lanecheck.clean_cell(str(x)) not in judged.get(lane, set()))
    if miss:
        wide = (o.get("_meta") or {}).get("kind") in ("full", "statements") and (n.get("_meta") or {}).get("kind") != "full"
        return (f"round {new}'s sealed verdicts do not cover round {old}'s scope ({len(miss)} item(s) not judged, e.g. "
                f"{miss[0]})" + ("; a diff round cannot cover a full/statements round -- use --full" if wide else ""))
    return None


def redo_lanecheck(doc, rr):
    """The lanecheck a redo's cure also runs on its fresh round `rr` when the stop's own check names no round
    (a --cmd check without {R} printing a redo code), else None (B1b review C)."""
    return None if not rr or "--round" in (cure_cmd(doc) or "").split() else f"python3 audits/lanecheck.py --round {rr}"


def cured_check(doc, c):
    """The check a self-cure CLOSED.json `c` of stop record `doc` must have re-run: the recorded one, on its
    `redo_round` when it has one."""
    return _with_round(cure_cmd(doc), c["redo_round"]) if c.get("redo_round") else cure_cmd(doc)


def cure_plan(cfg, doc):
    """[kinds] (project.CURES) when stop record `doc` is the operator's to self-cure: release mode, no
    cause of kind human (project.release_cure), and a recorded check that is a read-only FORMS command
    (command_problem) to re-run. Else None: a human stop."""
    cmd = cure_cmd(doc)
    codes = [c.get("code") for c in (doc or {}).get("causes") or []]
    if not cmd and codes and set(codes) == {"tool-bug"} and project.mode(cfg) == "release":
        return ["patch"]        # a pinned writer that keeps crashing, no read-only check failing: a tool patch
    if not cmd or command_problem(cmd, cfg) or closer_problem(cfg, doc):
        return None
    return project.release_cure(cfg, codes)


def open_stop(cfg, cmd=None, note=None, cause=None, round_name=None, check=None):
    """Record a stop. Returns (S<n>, message). A PDF fault or delivery precondition among the causes is left out
    of the stop (attack 8) and the message says where it goes."""
    s, msg = _open_stop(cfg, cmd, note, cause, round_name, check)
    left = (load(os.path.join(stop_dir(cfg, s), "STOP.json")) or {}).get("left_out") or []
    if left:
        msg += (" -- left out of this stop, never a stop: " + "; ".join(c["line"][:120] for c in left[:3])
                + (f" ({pdf_route(' '.join(c['line'] for c in left))}: render it again)"
                   if any(c["code"] == "pdf" for c in left) else " (a precondition of project.py --deliver)"))
    return s, msg


def _open_stop(cfg, cmd=None, note=None, cause=None, round_name=None, check=None):
    if bool(cmd) == bool(note):
        raise Refused("give exactly one of --cmd (a failing check, in its read-only form, re-run here) or "
                      "--note (a failed tool call) with --cause")
    if round_name and not re.fullmatch(ROUND_PAT, round_name):
        raise Refused(f"{round_name!r} is not a round name")
    fixed = finish_interrupted(cfg)
    busy = open_name(cfg)
    if busy:
        raise Refused(f"stop {busy} is still open: one stop at a time (close it first)"
                      + (f" [{'; '.join(fixed)}]" if fixed else ""))
    if cause == "tool-fault":
        raise Refused("tool-fault is recorded with stops.py disclose (release mode); in dev mode a persistent "
                      "crash of a pinned script is --cause tool-bug (in release mode too: with no --check, the tool-patch route)")
    doc = _stop_doc(cfg, cmd, note, cause, round_name, check=check)
    # ADDENDUM N1 (both modes): deliver, unverified and deliver-stale are preconditions of --deliver; a PDF is
    # rendered again by agents (approver, 2026-10-23; `pdf` is an older run's code). Attack 8: in any mix
    # too -- the stop records the other faults only (left_out), and its cure is judged on them
    left_out = [c for c in doc.get("causes") or [] if c["code"] in project.NEVER_STOP]
    rest = [c for c in doc.get("causes") or [] if c["code"] not in project.NEVER_STOP]
    if left_out and all(project.disclosed(cfg, c["code"]) for c in rest):
        raise Refused("never a stop: every cause is a precondition of project.py --deliver or a PDF the rendering "
                      "agents make again (" + "; ".join(f"{c['code']}: {project.CAUSES[c['code']][1]}" for c in left_out) + ")")
    if left_out:
        doc["causes"], doc["left_out"] = rest, left_out
    if doc["causes"] and all(project.disclosed(cfg, c["code"]) for c in doc["causes"]):
        raise Refused("every cause is disclosed in release mode, not a stop: python3 audits/stops.py disclose "
                      + (f"--cmd \"{cmd}\"" if cmd else "--note ..."))
    if project.mode(cfg) == "release":
        round_problem(doc, rounds_dir(cfg))     # RELEASE-SWEEP S4: refused here, before anything is recorded
    existing = stops(cfg)
    s = f"S{int(existing[-1][1:]) + 1 if existing else 1}"
    doc["stop"] = s
    sd = stop_dir(cfg, s)
    os.makedirs(sd)
    p = os.path.join(sd, "STOP.json")
    try:
        json.dump(doc, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
        commit([p], f"stop {s} open")
    except (Refused, OSError):
        for f in (p,):
            if os.path.exists(f):
                os.remove(f)
        os.rmdir(sd)
        raise
    cure = cure_plan(cfg, doc)
    try:
        spent, why4 = cures_spent(cfg, doc) if cure else (0, [])
    except Refused as e:
        # RELEASE-SWEEP S4: a bookkeeping refusal of the tally is never a human stop
        return s, (f"opened {s} (release mode, not a human stop): {e}. Then cure it as its codes say ("
                   + "; ".join(f"{c['code']}: {project.cure_text(c['code'])}" for c in doc["causes"][:2])
                   + f") and close it with python3 audits/stops.py close --stop {s} --cured \"<what was done>\"")
    if cure == ["patch"] and not cure_cmd(doc):
        return s, (f"opened {s} (release mode: not a human stop): a pinned script keeps crashing and no read-only "
                   f"check fails. Cure it: {project.cure_text('tool-bug')}. Then: python3 audits/stops.py close --stop "
                   f"{s} --cured \"tool-patch TP<k>\" (it re-runs the patch's regression test)")
    if cure and not why4:
        return s, (f"opened {s} (release mode: a self-cure, not a human stop). Cure it: "
                   + " | ".join(f"{k}: {project.cure_text(c)}" for k, c in sorted(
                       {project.release_kind(c["code"]): c["code"] for c in doc["causes"]
                        if project.release_kind(c["code"]) != "disclose"}.items()))
                   + f". Then: python3 audits/stops.py close --stop {s} --cured \"<what was done>\" (it re-runs "
                   + f"`{cure_cmd(doc)}`; attempt {spent + 1} of {project.CURE_BUDGET} for this stop, "
                   + f"{project.KEY_BUDGET} failed cures for one fault in the run; then classify it)")
    if cure and why4:
        return s, (f"opened {s} (release mode, not a human stop): the cure budget is spent ({'; '.join(why4)}): "
                   + CLASSIFY_HINT.format(s=s))
    if project.mode(cfg) == "release":
        hum = sorted({c["code"] for c in doc["causes"] if project.release_kind(c["code"]) == "human"})
        return s, (f"opened {s}: a human stop in release mode -- "
                   + (spent if isinstance(spent, str) else
                      f"{', '.join(hum)} ({human_stop_name(hum)}): {project.CURES['human']}" if hum else
                      f"its recorded check `{cure_cmd(doc)}` is not a read-only check to re-run")
                   + f". Show the human; close it with python3 audits/stops.py close --stop {s} --human \"<their answer, verbatim>\"")
    cls = stop_class(doc)
    if cls or not (project.delegates(cfg) or record_fix_only(doc)):
        why = (f"its causes are of a STOP class ({', '.join(cls)})" if cls else "the involved level asks the human")
        return s, (f"opened {s}: {why}. Show the human the raw output and wait for their answer; record it with "
                   f"python3 audits/stops.py close --stop {s} --human \"<their answer, verbatim>\"")
    return s, (f"opened {s} (classes: {', '.join(sorted({c['class'] for c in doc['causes']}))}). Cure it as the "
               f"cause table says, then: python3 audits/stops.py close --stop {s} --delegated \"<what was done>\"")


CLASSIFY_HINT = ("classify it (your judgement): python3 audits/stops.py classify --stop {s} --as tool-bug|interference|"
                 "other --evidence \"<why>\" -- tool-bug: the check or tool is wrong, patch it (tool_patch.py begin "
                 "--stop {s}; then close --cured \"tool-patch TP<k>\"); interference: another program keeps "
                 "changing the project's files (name the recurring events): stop 3, show the human and close it "
                 "--human; other: neither -- name the different cure you will try, then close --cured once more")


def human_stop_name(codes):
    """Which of the four release stops (project.RELEASE_STOPS) these human codes are: "stop 1" ... "stop 4"."""
    ns = sorted({n for n, cs in project.RELEASE_STOPS.items() for c in codes if c in cs})
    return ", ".join(f"stop {n}" for n in ns) or "a human stop"


def classifications(cfg, s, rd=None):
    """[CLASSIFY<j>.json] of stop `s`, committed, in order."""
    sd = os.path.join(rd or rounds_dir(cfg), STOPS, s)
    fs = sorted((f for f in (os.listdir(sd) if os.path.isdir(sd) else []) if CLASSIFY_RE.match(f)),
                key=lambda f: int(CLASSIFY_RE.match(f).group(1)))
    return [load(os.path.join(sd, f)) or {} for f in fs]


def classify(cfg, s, as_, evidence):
    """Record the operator's classification of stop `s` whose cure budget is spent (release mode only)."""
    if project.mode(cfg) != "release":
        raise Refused("classify is release mode only; in dev mode every stop waits for the human (--human)")
    if as_ not in CLASSES_AT_BUDGET:
        raise Refused(f"--as is one of {', '.join(CLASSES_AT_BUDGET)}")
    ev = " ".join(str(evidence or "").split())
    if not ev:
        raise Refused("--evidence is required: why it is a tool bug, which events recur (interference), or which "
                      "different cure you will try")
    sd = stop_dir(cfg, s)
    doc = load(os.path.join(sd, "STOP.json"))
    if not doc:
        raise Refused(f"no stop {s}")
    if os.path.exists(os.path.join(sd, "CLOSED.json")):
        raise Refused(f"{s} is closed")
    if not cure_plan(cfg, doc):
        raise Refused(f"{s} is a human stop of release mode: nothing to classify; close it with --human")
    own, why = cures_spent(cfg, doc)
    if not why:
        raise Refused(f"{s}'s cure budget is not spent: cure it and close it --cured")
    if any(c.get("after_fail") == own for c in classifications(cfg, s)):
        raise Refused(f"{s} is already classified after its {own} failed cure(s): act on that classification")
    j = 1 + len(classifications(cfg, s))
    rec = {"stop": s, "as": as_, "evidence": ev, "date": today(), "mode": "release", "after_fail": own,
           "spent": why}
    p = os.path.join(sd, f"CLASSIFY{j}.json")
    json.dump(rec, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        commit([p], f"stop {s} classify {j}")
    except Refused:
        os.remove(p)
        raise
    what = {"tool-bug": f"a tool bug: python3 audits/tool_patch.py begin --stop {s} (RUN.md \"Tool patches\"), then "
                        f"close --cured \"tool-patch TP<k>\"",
            "interference": f"outside interference: stop 3, the human's -- show them the recurring events and close it "
                            f"with --human \"<their answer, verbatim>\"",
            "other": "neither: one more cure attempt (close --cured); if it fails, classify again"}[as_]
    project.log_append(cfg, "Stops", f"- stop {s} classified (release mode; cure budget spent): {as_}: {ev}")
    return rec, what


def budget_grant(cfg, s, own, cured_text):
    """None when a --cured attempt of stop `s` whose budget is spent (with `own` failed cures of its own) may be
    made now, else why not: the newest classification made after those failures allows it -- other, or tool-bug
    with a tool-patch close; never interference."""
    cls = [c for c in classifications(cfg, s) if c.get("after_fail") == own]
    if not cls:
        return "classify it first"
    a = cls[-1].get("as")
    if a == "interference":
        return "it is classified as outside interference: stop 3, the human's (close --human)"
    if a == "tool-bug" and not TP_TEXT.match(" ".join(str(cured_text or "").split())):
        return "it is classified as a tool bug: close it --cured \"tool-patch TP<k>\" once the patch is applied"
    return None


def record_fix_only(doc):
    """True when every cause of a stop is of class record-fix or adjudication (a fault of an adjudicator's
    record): the operator cures it by a record correction or the next adjudication at every level, the
    human's level included (RUN.md failure table), and closes it with --delegated."""
    cs = (doc or {}).get("causes") or []
    return bool(cs) and all(c.get("class") in ("record-fix", "adjudication") for c in cs)


def cure_attempts(cfg, s):
    """[CURE<k>.json] of stop `s`: its failed release self-cure attempts, in order."""
    sd = stop_dir(cfg, s)
    fs = [f for f in os.listdir(sd) if CURE_RE.match(f)] if os.path.isdir(sd) else []
    return sorted(fs, key=lambda f: int(CURE_RE.match(f).group(1)))


def _close_doc(cfg, s, doc, human=None, delegated=None, cured=None):
    """The CLOSED.json record of `close` for stop `s` (STOP.json `doc`), computed now: the recorded
    check re-run, and every `--delegated` / `--cured` refusal. Refused as `close` refuses. A `--cured`
    record whose re-run fails is returned as it is (the caller records it as a failed attempt)."""
    if sum(map(bool, (human, delegated, cured))) != 1:
        raise Refused("give exactly one of --human \"<the human's answer, verbatim>\", --delegated \"<what was "
                      "done>\" or (release mode) --cured \"<what was done>\"")
    rec = {"stop": s, "date": today(), "involvement": project.involvement(cfg)}
    if cured:
        if project.mode(cfg) != "release":
            raise Refused("--cured is release mode only; in dev mode a STOP class waits for the human (--human)")
        cmd = cure_cmd(doc)
        cure = cure_plan(cfg, doc)
        tpm = TP_TEXT.match(" ".join(str(cured).split()))
        if tpm:             # OPERATOR-PATCH: the patch applied for this stop (verified by tool_patch.py)
            try:
                import tool_patch
                info = tool_patch.applied_info(cfg, tpm.group(1))
            except (ImportError, ValueError) as e:
                raise Refused(f"{tpm.group(1)} is not an applied tool patch: {e}")
            if info.get("stop") != s:
                raise Refused(f"{tpm.group(1)} was made for stop {info.get('stop')}, not {s}")
            rec["tool_patch"] = tpm.group(1)
            if not cmd:
                cmd = info["regression_cmd"]
        elif cure == ["patch"] and not cmd:
            raise Refused(f"{s} has no read-only check to re-run: it is cured only by a tool patch (python3 audits/"
                          f"tool_patch.py begin --stop {s}), closed --cured \"tool-patch TP<k>\"")
        if not cure:
            why = ("a goal result, an outward action, or an environment fault only the human can fix"
                   if not project.release_cure(cfg, [c.get("code") for c in doc.get("causes") or []]) else
                   "it records no read-only check to re-run" if not cmd else
                   closer_problem(cfg, doc) or f"its check `{cmd}` is no read-only check: {command_problem(cmd, cfg)}")
            raise Refused(f"{s} is a human stop in release mode ({why}): close it with --human")
        try:
            k, why4 = cures_spent(cfg, doc)
            k += 1
        except Refused as e:
            # RELEASE-SWEEP S4: bookkeeping, never a human stop: fix what it names, then close --cured again
            raise Refused(f"{e}; no cure attempt of {s} was spent: fix that, then close --cured again")
        if why4:
            no = budget_grant(cfg, s, k - 1, cured)
            if no:
                raise Refused(f"the failure of {s} (`{cmd}`): the cure budget is spent ({'; '.join(why4)}): {no}. "
                              + CLASSIFY_HINT.format(s=s))
        rr_ = redo_round(cfg, s, doc)       # Refused (no attempt spent) while the fresh round is missing
        if rr_:
            cmd = _with_round(cmd, rr_)
            rec["redo_round"] = rr_
        rc, out = run_cmd(cmd.split())
        lc = redo_lanecheck(doc, rr_)
        if lc:      # the fresh round's own lanes must pass too: the stop's check does not look at them
            rec["redo_lanecheck"] = lc
            if rc == 0:
                rc, out = run_cmd(lc.split())
                out = f"$ {lc}\n{out}"
        rec.update(by="cure", mode="release", text=" ".join(str(cured).split()), attempt=k,
                   budget=project.CURE_BUDGET, cures=cure, codes=sorted({c.get("code") for c in doc["causes"]}),
                   check=" ".join(cmd.split()), rerun={"exit": rc, "output_tail": out[-2000:],
                                                       "passes": rc == 0 or only_left_out(doc, out)})
        return rec
    if doc.get("command"):
        rc, out = run_cmd(doc["command"].split())
        rec["rerun"] = {"exit": rc, "output_tail": out[-2000:], "passes": rc == 0 or only_left_out(doc, out)}
    if delegated:
        if project.mode(cfg) == "release":
            raise Refused("release mode: --delegated is dev mode only; a release stop closes with --cured (it re-runs "
                          "its read-only check) or, a human stop, with --human")
        if not project.delegates(cfg) and not record_fix_only(doc):
            raise Refused("under the involved level the human answers every stop: close it with --human")
        cls = stop_class(doc)
        if cls:
            raise Refused(f"{s}'s causes are of a STOP class ({', '.join(cls)}): only the human closes it (--human)")
        if rec.get("rerun") and not rec["rerun"]["passes"]:
            raise Refused(f"`{doc['command']}` still fails (exit {rec['rerun']['exit']}): the stop is not cured")
        rec.update(by="operator", mode=project.mode(cfg), text=" ".join(str(delegated).split()))
    else:
        rec.update(by="human", text=str(human).strip())
    return rec


# Approver (2026-10-25, C2-FIX 5b; redesigned after its attack review): a fault in the PROOF-VALIDITY CORE
# (tool_patch.CORE: the build and sorry scan, the axiom sweep, the freeze, tool_patch.py, integrity.py) is never
# patched by a tool patch, and in release the run never waits for a maintainer. The operator first tries a Lean-side
# workaround (a pure refactor the freeze check confirms, closed --cured); when none exists:
#   1. `stops.py core-fault --stop S<n> --core-fault <file> --diagnosis "..."` (core_fault_request) -- code, mechanical:
#      the file is in the first pin's core, the stop is a tool bug, its check is THE check that runs the file and fails
#      now, and every failure any standard blocking check prints is that file's own (core_attribution: a sorry when
#      the axiom sweep is named, a DRIFT, an ownership FAIL, the build are another fault's, which keeps its own cure);
#      the exact failure lines are recorded and a FRESH reviewer is issued (agents judge, code flags);
#   2. the reviewer judges that every recorded line is the tool's fault, not a real unfinished proof, axiom, changed
#      statement or tampering; its verdict is sealed like a lane's;
#   3. `close --core-fault <file>` (_core_fault_doc) needs that sealed, fresh approval of the newest request, and the
#      failure lines now exactly the recorded ones. The check is then "not established" -- never claimed passed --
#      every result reads so (result_status), the marker is on SUMMARY page 1, and --deliver accepts no other line.
CORE_CHECKS = (("phase0.py", "Phase 0 (the build, the sorry scan and every check it runs)"),
               ("axiom_sweep", "the axiom sweep"),
               ("fingerprint", "the freeze check (approved statements unchanged)"),
               ("olean_parts.lean", "the freeze check (approved statements unchanged)"),
               ("integrity.py", "the integrity check (record ownership, the pinned apparatus)"),
               ("tool_patch.py", "the tool-patch provenance check"))
# the read-only check that runs each core file, and the Phase 0 steps that are the file's own (a Phase 0 that crashed
# before its result is phase0.py's own fault)
PY = "python3 audits/"
CORE_CHECK_CMD = (("phase0.py", PY + "phase0.py --readonly"), ("axiom_sweep", PY + "phase0.py --readonly"),
                  ("fingerprint", PY + "fingerprint.py --check"), ("olean_parts.lean", PY + "fingerprint.py --check"),
                  ("integrity.py", PY + "integrity.py --check"), ("tool_patch.py", PY + "integrity.py --check"))
OWN_STEPS = (("phase0.py", ("token scan",)), ("axiom_sweep", ("axiom sweep",)), ("fingerprint", ("freeze check",)),
             ("olean_parts.lean", ("freeze check",)), ("integrity.py", ()), ("tool_patch.py", ()))
PHASE0_RED = re.compile(r"^\s*RED\[[\w-]+\]\s+(.+?)\s+\[exit -?\d+\]\s*$")
CORE_REQ_RE = re.compile(r"^CORE-REQUEST([1-9]\d*)\.json$")
CORE_FILE_RE = re.compile(r"^(?:CORE-REQUEST[1-9]\d*\.json|core-review-[1-9]\d*\.json|core-review-[1-9]\d*\.probes|"
                          r"\.lane-auth|\.lane-seals|prompts)$")


def _core_map(table, f):
    return next((v for p_, v in table if str(f).startswith(p_)), None)


def core_check_name(f):
    """The check a core file implements (CORE_CHECKS), never the operator's words."""
    return _core_map(CORE_CHECKS, f) or f"the check of {f}"


# Approver (2026-10-26): SUMMARY and REPORT are read by a paper author who knows nothing of the mechanism. They say
# only the plain consequence for the author's results, per guarantee the faulty check gives; the check, the file,
# the stop, the failure lines and the reviewer's verdict are RUN_RECORD.md's (core_fault_tech). Per guarantee: the
# sentence on page 1 and in the report, and the short status every result gets. None for the provenance checks: the
# proofs and statements were still checked by Lean (Phase 0 and the freeze, re-run at delivery), so "proved" and
# "statement as approved" hold; but the reviewers' verdicts are authenticated at delivery inside integrity.py --check,
# so "faithful" rests on records not verified then: page 1, the legend (make_report.RECORD_LEGEND) and every report
# row resting on the record say so (review 3)
CORE_GUARANTEES = (
    ("phase0.py", "proof", "the check that every proof is complete (and uses only Lean's standard axioms) could not be "
                           "run, so the proofs have not been confirmed complete", "not verified: proof complete"),
    ("axiom_sweep", "axioms", "the check that the proofs use only Lean's standard axioms could not be run, so that has "
                              "not been confirmed", "not verified: standard axioms only"),
    ("fingerprint", "statement", "the check that the statements are exactly the ones approved could not be run, so "
                                 "that has not been confirmed", "not verified: statement as approved"),
    ("olean_parts.lean", "statement", "the check that the statements are exactly the ones approved could not be run, "
                                      "so that has not been confirmed", "not verified: statement as approved"),
    ("integrity.py", "record", "the record of who reviewed and approved what could not be verified automatically", None),
    ("tool_patch.py", "record", "the record of who reviewed and approved what could not be verified automatically",
     None))


def core_guarantee(rec):
    """(guarantee, plain sentence, short status or None) of a core-fault record (CORE_GUARANTEES)."""
    f = str(rec.get("core_file") or "")
    return next(((g, t, st) for p_, g, t, st in CORE_GUARANTEES if f.startswith(p_)),
                ("proof", "a check of the proofs could not be run, so the proofs have not been confirmed", "not verified"))


def core_fault_marker(rec):
    """The plain sentence a core-fault close puts on SUMMARY page 1 and in the REPORT (no mechanism words)."""
    return f"Not verified: {core_guarantee(rec)[1]} (details for maintainers in RUN_RECORD.md)."


def core_fault_status(rec):
    """The short status every result gets from a core-fault close, or None (CORE_GUARANTEES)."""
    return core_guarantee(rec)[2]


def core_fault_tech(rec):
    """The maintainers' line of a core-fault close (RUN_LOG.md, RUN_RECORD.md only)."""
    return f"{rec.get('check_name')} could not run (tool fault in {rec.get('core_file')})"


# review 2 (C2-FIX): what differs between two runs of the same failing check and is not the failure: the temporary
# file Lean is run on (project.run_lean: "/tmp/tmp46h5xdbo.lean:41:2: error: ..."; a crash message quoting it, as
# fingerprint.py's RuntimeError does), a temporary directory, an object's address. Every other character is kept
# only a temporary file's or directory's own name (tempfile's tmp<random>), directly under a temporary root: a project
# that lives under /tmp keeps its file names (review 3: /tmp/proj/P/A.lean and B.lean must differ)
TMP_PATH_RE = re.compile(r"(?:%s|/tmp|/var/tmp|(?:/private)?/var/folders/[^\s/]+/[^\s/]+/T)/tmp[A-Za-z0-9_]{6,}"
                         r"(?:\.[A-Za-z]+)?(?![A-Za-z0-9_])" % re.escape(tempfile.gettempdir()))
ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{6,}\b")


def _run_free(line):
    return ADDR_RE.sub("0x<address>", TMP_PATH_RE.sub("<temporary file>", " ".join(str(line).split())))


def _fail_lines(txt):
    """The failure lines of a check's output, exactly but for what differs from run to run (_run_free: temporary
    files, addresses); no hash, declaration or line number dropped."""
    return sorted({_run_free(c["line"]) for c in causes(txt)})


def core_attribution(f, cmd, out):
    """(own lines, foreign lines) of the failure output `out` of standard check `cmd` for a fault in core file `f`:
    in Phase 0's output only the RED steps of `f` (OWN_STEPS) are its own (any other RED step makes every line
    foreign), a Phase 0 that crashed before its result is phase0.py's; fingerprint.py --check is the freeze files',
    integrity.py --check integrity.py's and tool_patch.py's. Mechanical only: whether those lines are really the
    tool's fault is the fresh reviewer's judgement."""
    lines = _fail_lines(out)
    script = os.path.basename(next((x for x in cmd.split() if x.endswith(".py")), ""))
    own_cmd = _core_map(CORE_CHECK_CMD, f) or ""
    if script == "phase0.py":
        if "PHASE 0 RESULT" not in out:
            return (lines, []) if f == "phase0.py" else ([], lines)
        steps = [m.group(1) for m in (PHASE0_RED.match(l) for l in out.split("PHASE 0 RESULT", 1)[1].splitlines()) if m]
        mine = _core_map(OWN_STEPS, f) or ()
        foreign = [st for st in steps if not st.startswith(mine)] if mine else steps
        return ([], lines) if foreign or not steps else (lines, [])
    own_script = os.path.basename(next((x for x in own_cmd.split() if x.endswith(".py")), "-"))
    return (lines, []) if script == own_script else ([], lines)


def _core_basics(cfg, s, doc, core_file):
    """(core file, its check command) after the mechanical refusals shared by the request and the close."""
    if project.mode(cfg) != "release":
        raise Refused("--core-fault is release mode only; in dev a fault in the proof-validity core is the "
                      "maintainer's (close --human)")
    import tool_patch
    try:
        core = tool_patch.core_files(project.AUDITS, rounds_dir(cfg))
    except Exception:       # noqa: BLE001 -- no first pin: this file's own CORE
        core = tool_patch.CORE
    f = str(core_file or "").strip()
    if f not in core:
        raise Refused(f"{f!r} is not in the proof-validity core ({', '.join(core)}): any other tool fault is the "
                      f"tool-patch route (tool_patch.py begin --stop {s})")
    if "tool-bug" not in {c.get("code") for c in doc.get("causes") or []} \
            and not any(x.get("as") == "tool-bug" for x in classifications(cfg, s)):
        raise Refused(f"{s} is not a tool bug (opened --cause tool-bug, or classified tool-bug): a check that is right "
                      f"is cured as its code says, never marked not established")
    want, name = _core_map(CORE_CHECK_CMD, f), cfg.get("name")
    if _canon(cure_cmd(doc), name) != _canon(want, name):
        raise Refused(f"{s}'s check is `{cure_cmd(doc)}`; a fault in {f} is shown by the check that runs it, `{want}`: "
                      f"open the stop with --check \"{want}\"")
    return f, want


def _core_failing(cfg, f, want):
    """{command: [failure line]} of every standard blocking check that fails now, all of them `f`'s own, the stop's
    check among them; Refused naming any other failure (it keeps its own cure or stop)."""
    failing, foreign = {}, []
    for c2 in standard_blocking(cfg):
        rc2, out2 = run_cmd(c2.split())
        if rc2:
            own, other = core_attribution(f, c2, out2)
            if other:
                foreign += [f"`{c2}`: {l}" for l in other[:4]] or [f"`{c2}` exits {rc2}"]
            else:
                failing[c2] = own
    empty = [c for c, ls in failing.items() if not ls]
    if empty:
        # review 2: a check that exits non-zero printing no failure line (a timeout, exit 124) can never be compared
        raise Refused(f"`{empty[0]}` fails but prints no failure line (a timeout or a kill): nothing a reviewer could "
                      f"judge or delivery compare -- re-run it within the retry budget, and if it persists classify "
                      f"the stop otherwise (stops.py classify; an environment fault is env-unknown)")
    if foreign:
        raise Refused(f"a failure that is not {f}'s own is open (it keeps its own cure or stop; fix it first): "
                      + "; ".join(foreign))
    if not any(_canon(c, cfg.get("name")) == _canon(want, cfg.get("name")) for c in failing):
        raise Refused(f"`{want}` passes now: nothing is left not established; close --cured")
    return failing


def _core_requests(sd):
    return sorted(int(CORE_REQ_RE.match(x).group(1)) for x in (os.listdir(sd) if os.path.isdir(sd) else [])
                  if CORE_REQ_RE.match(x))


CORE_REVIEW_PROMPT = """You are a FRESH reviewer of a release run of formalize-paper. You are not the operator, a review lane
or the adjudicator, and you have not seen this run. One question, about a check of the proof-validity core (the files
that check that proofs are valid: no tool patch may change them):

The operator says the check {check_name} could not run because of a fault in the tool file audits/{core_file}, and asks
to deliver the run with that check marked "not established" (never claimed passed). Every result of the run will read
"not established" because of it. Decide whether EVERY recorded failure line below is produced by the diagnosed fault of
the TOOL, and none is a real problem of the work: a real `sorry` or unfinished proof, a real axiom beyond propext,
Classical.choice and Quot.sound, a real change of an approved statement (a drift), tampering with a record, or a build
error of the Lean. Also decide whether a Lean-side workaround (a pure refactor of the Lean that the freeze check
confirms) would avoid the fault; if one would, reject.

The request (read it in full): {request} (sha256 {request_sha256}).
The core file: {core_path} (sha256 {core_sha256}). The project's Lean files are named in its config; you may run
read-only commands (git, grep, the check itself) and must change nothing.

The operator's diagnosis: {diagnosis}

The recorded failure lines, per check:
{lines}

Write this JSON object, and nothing else, to {verdict}:
{{"lane_token": "<your lane_token>", "verdict": "approve" or "reject", "request_sha256": "{request_sha256}",
 "reason": "<one paragraph: for each recorded line, why it is (or is not) the tool's fault; whether a Lean-side workaround
exists>"}}
Approve only if you are sure; when in doubt, reject: a rejection costs the run another request or the ordinary cure,
never a stop.
If your write of {verdict} is refused (some hosts refuse a subagent's file writes), do not look for another way to
write it: return it. Its delimiter is `RETURNED_` and the first 12 hex digits of your lane_token; check that no line of
the object equals it. Hash the object with `sha256sum <<'<delimiter>'`, the object, then a line `<delimiter>` (this
writes no file; the digest covers the object and one final newline), and end your final message with a line
`BEGIN RETURNED FILE {verdict} <delimiter>`, the same object, a line `END RETURNED FILE`, and then the LANE_COMPLETION line with
that sha256. The operator saves the object verbatim to {verdict}; it is sealed only if its sha256 is the one you
returned.
"""


def core_fault_request(cfg, s, core_file, diagnosis):
    """`stops.py core-fault`: the request of a core-fault close and its fresh reviewer (CORE_CHECKS above). Returns
    (request path, spawn line)."""
    import lane_auth, secrets
    sd = stop_dir(cfg, s)
    doc = load(os.path.join(sd, "STOP.json"))
    if not doc:
        raise Refused(f"no stop {s}")
    if os.path.exists(os.path.join(sd, "CLOSED.json")):
        raise Refused(f"{s} is closed")
    f, want = _core_basics(cfg, s, doc, core_file)
    diag = " ".join(str(diagnosis or "").split())
    if not diag:
        raise Refused("--diagnosis is required: the fault (file:line), what the check cannot do because of it, and "
                      "why no Lean-side workaround (a pure refactor the freeze check confirms) works")
    failing = _core_failing(cfg, f, want)
    k = 1 + max(_core_requests(sd) or [0])
    req = os.path.join(sd, f"CORE-REQUEST{k}.json")
    cp_ = os.path.join(project.AUDITS, f)
    rec = {"stop": s, "request": k, "date": today(), "core_file": f, "check_name": core_check_name(f), "check": want,
           "diagnosis": diag, "failing": [[c, ls] for c, ls in sorted(failing.items())],
           "core_sha256": lane_auth.sha(open(cp_, "rb").read()) if os.path.isfile(cp_) else None}
    json.dump(rec, open(req, "w", encoding="utf-8"), indent=1, sort_keys=True, ensure_ascii=False)
    name = f"core-review-{k}.json"
    pdir = os.path.join(sd, "prompts")
    os.makedirs(pdir, exist_ok=True)
    pp = os.path.join(pdir, f"core-review-{k}.txt")
    rs = lane_auth.sha(open(req, "rb").read())
    open(pp, "w", encoding="utf-8").write(CORE_REVIEW_PROMPT.format(
        check_name=rec["check_name"], core_file=f, request=os.path.abspath(req), request_sha256=rs,
        core_path=os.path.abspath(cp_), core_sha256=rec["core_sha256"], diagnosis=diag,
        lines="\n".join(f"- `{c}`:\n" + "\n".join(f"    {l}" for l in ls) for c, ls in rec["failing"]),
        verdict=os.path.abspath(os.path.join(sd, name))))
    cp = os.path.join(sd, ".lane-auth", name)
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    token = secrets.token_hex(32)
    json.dump({"verdict": name, "token_sha256": lane_auth.sha(token.encode()), "prompt": os.path.abspath(pp),
               "prompt_sha256": lane_auth.sha(open(pp, "rb").read())}, open(cp, "w", encoding="utf-8"),
              sort_keys=True, indent=2)
    open(cp, "a", encoding="utf-8").write("\n")
    try:
        commit([req, pp, cp], f"stop {s} core-fault request {k}")
    except Refused:
        for x in (req, pp, cp):
            if os.path.exists(x):
                os.remove(x)
        raise
    return req, lane_auth.spawn_line(os.path.abspath(pp), token)


def _core_review_problem(cfg, s, k, rd=None):
    """(None, verdict doc, seal doc) when review k of stop s is sealed, fresh and approves request k as it is, else
    (why not, ...)."""
    import lane_auth, tool_patch
    rd = rd or rounds_dir(cfg)
    sd = os.path.join(rd, STOPS, s)
    v = os.path.join(sd, f"core-review-{k}.json")
    probs = lane_auth.validate(v) if os.path.exists(os.path.join(sd, ".lane-auth", f"core-review-{k}.json")) \
        else [f"core-review-{k}.json was never issued"]
    if probs:
        return f"review core-review-{k}.json is not sealed or does not authenticate ({probs[0]})", None, None
    d = load(v) or {}
    sl = load(os.path.join(sd, ".lane-seals", f"core-review-{k}.json")) or {}
    rs = lane_auth.sha(open(os.path.join(sd, f"CORE-REQUEST{k}.json"), "rb").read())
    agent = str(sl.get("agent_id"))
    others = [x for x in tool_patch.all_agent_ids(rd).get(agent, [])
              if x != os.path.join(STOPS, s, ".lane-seals", f"core-review-{k}.json")] + other_agent_seals(rd, agent)
    if others:
        return f"the reviewer's agent id {agent} also sealed {others[0]}: the reviewer must be fresh", d, sl
    if d.get("request_sha256") != rs:
        return f"core-review-{k}.json judges another request (its request_sha256)", d, sl
    if d.get("verdict") != "approve":
        return (f"core-review-{k}.json REJECTS the request ({' '.join(str(d.get('reason', '')).split())[:300]}): revise "
                f"the diagnosis and request again (stops.py core-fault), or take the ordinary cure; never a stop"), d, sl
    return None, d, sl


def other_agent_seals(rd, agent):
    """[record] outside .lane-seals that names agent id `agent`: a status-check run's seal (status-check/SEAL-<n>.json).
    Fresh readers and PDF agents record no agent id, so they cannot be compared (review 3; the narrow model: agent ids
    are the operator's text, as for lanes)."""
    out = []
    for p_ in glob.glob(os.path.join(rd, "status-check", "SEAL-*.json")):
        d_ = load(p_)
        if isinstance(d_, dict) and str(d_.get("agent_id")) == agent:
            out.append(os.path.relpath(p_, rd))
    return out


def _core_fault_doc(cfg, s, doc, core_file):
    """The CLOSED.json record of `close --core-fault`, computed now; Refused when it does not apply."""
    f, want = _core_basics(cfg, s, doc, core_file)
    sd = stop_dir(cfg, s)
    ks = _core_requests(sd)
    if not ks:
        raise Refused(f"no core-fault request for {s}: python3 audits/stops.py core-fault --stop {s} --core-fault {f} "
                      f"--diagnosis \"...\" first (a fresh reviewer judges it)")
    k = ks[-1]
    req = load(os.path.join(sd, f"CORE-REQUEST{k}.json")) or {}
    if req.get("core_file") != f:
        raise Refused(f"the newest request (CORE-REQUEST{k}.json) names {req.get('core_file')}, not {f}")
    why, vd, sl = _core_review_problem(cfg, s, k)
    if why:
        raise Refused(why)
    failing = _core_failing(cfg, f, want)
    if {c: sorted(ls) for c, ls in failing.items()} != {c: sorted(ls) for c, ls in req.get("failing") or []}:
        raise Refused(f"the failure lines differ from those the reviewer judged (CORE-REQUEST{k}.json): request again")
    return {"stop": s, "date": today(), "involvement": project.involvement(cfg), "by": "core-fault",
            "mode": "release", "core_file": f, "check_name": core_check_name(f), "check": want,
            "text": req.get("diagnosis", ""), "failing": [[c, ls] for c, ls in sorted(failing.items())],
            "request": k, "review": f"core-review-{k}.json", "review_reason": " ".join(str(vd.get("reason", "")).split()),
            "reviewer": sl.get("agent_id"), "rerun": {"exit": 1, "passes": False}}


def core_request_lines(cfg, rd=None):
    """[line] for RUN_RECORD.md: every core-fault request of the run (stops.py core-fault) with its reviewer's verdict
    -- approved, REJECTED with its reason, or not sealed -- so a run of rejections is on the record (review 2)."""
    rd = rd or rounds_dir(cfg)
    out = []
    for s in stops(cfg, rd):
        sd = os.path.join(rd, STOPS, s)
        for k in _core_requests(sd):
            q = load(os.path.join(sd, f"CORE-REQUEST{k}.json")) or {}
            why, vd, _sl = _core_review_problem(cfg, s, k, rd)
            v = ("approved" if not why else
                 f"REJECTED: {' '.join(str((vd or {}).get('reason', '')).split())}" if (vd or {}).get("verdict") == "reject"
                 else f"not approved ({why})")
            out.append(f"- stop {s}, request {k} ({q.get('date', '?')}; {q.get('core_file')}, `{q.get('check')}`; "
                       f"diagnosis: {q.get('diagnosis', '')}): {v}")
    return out


def core_fault_rows(cfg, rd=None):
    """[CLOSED.json] of every stop closed --core-fault, in stop order."""
    rd = rd or rounds_dir(cfg)
    out = []
    for s in stops(cfg, rd):
        c = load(os.path.join(rd, STOPS, s, "CLOSED.json")) or {}
        if c.get("by") == "core-fault":
            out.append(c)
    return out


def core_covered(cfg, cmd, txt):
    """Is the failure of delivery check `cmd` (its output `txt`) the one a core-fault close recorded: the same
    command, every failure line now exactly one the reviewer judged? Anything else (a real sorry, a drift, another
    declaration) is never covered."""
    name = cfg.get("name")
    now = set(_fail_lines(txt))
    for c in core_fault_rows(cfg):
        for c_cmd, lines in c.get("failing") or []:
            if _canon(c_cmd, name) == _canon(cmd, name) and now and now <= set(lines):
                return True
    return False


def _close_line(cfg, s, rec):
    """The RUN_LOG.md `## Stops` line of a close record."""
    if rec.get("by") == "core-fault":
        return (f"- stop {s} closed, release, a fault in the proof-validity core (`{rec.get('check')}` still fails): "
                f"{core_fault_tech(rec)} -- {rec.get('text')}")
    if rec.get("by") == "cure":
        return (f"- stop {s} self-cured (release mode, not a human stop; attempt {rec.get('attempt')} of "
                f"{project.CURE_BUDGET}; {', '.join(rec.get('cures') or [])}; `{rec.get('check')}` passes): {rec.get('text')}")
    if rec.get("by") == "operator":
        return f"- {tag(cfg)} stop {s} closed: {rec.get('text')}"
    return f"- stop {s} ({rec.get('date')}, the human's answer, verbatim: \"{' '.join(str(rec.get('text')).split())}\")"


def import_log(cfg):
    p = os.path.join(rounds_dir(cfg), "RUN_LOG.md")
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return ""


def close_stop(cfg, s, human=None, delegated=None, cured=None, check=None, core_fault=None, diagnosis=None):
    if sum(map(bool, (human, delegated, cured, core_fault))) != 1:
        raise Refused("give exactly one of --human \"<the human's answer, verbatim>\", --delegated \"<what was "
                      "done>\" or (release mode) --cured \"<what was done>\" or --core-fault <core file> --diagnosis "
                      "\"<why>\"")
    if check:
        raise Refused("close takes no --check: a self-cure re-runs exactly the command the stop recorded at open "
                      "(--cmd, or open --note ... --check)")
    # trial #11: the text goes into RUN_LOG.md's ## Stops, where make_report --check (Phase 0) lints tags; a
    # text the lint would refuse is refused here, before anything is written, not after a round started
    import decisions
    words = " ".join(str(cured or delegated or diagnosis or "").split())
    bad = decisions.tag_problems(f"## Stops\n- stop {s} self-cured (text; `x` passes): {words}\n") if words else []
    if bad:
        raise Refused(f"the text would put a non-canonical tag into RUN_LOG.md ## Stops: {bad[0]}")
    fixed = finish_interrupted(cfg)
    sd = stop_dir(cfg, s)
    doc = load(os.path.join(sd, "STOP.json"))
    if not doc:
        raise Refused(f"no stop {s}")
    if os.path.exists(os.path.join(sd, "CLOSED.json")):
        # B13 (restarts): a close killed after its commit, before its RUN_LOG.md line, gets the line now
        if committed(project.AUDITS, os.path.join(sd, "CLOSED.json")) and not re.search(
                rf"^- (?:\[[^\]\n]*\] )?stop {s} ", import_log(cfg), re.M):
            project.log_append(cfg, "Stops", _close_line(cfg, s, load(os.path.join(sd, "CLOSED.json")) or {}))
            fixed = list(fixed) + [f"its RUN_LOG.md line, lost by an interrupted close, written now"]
        raise Refused(f"{s} is closed" + (f" [{'; '.join(fixed)}]" if fixed else ""))
    if core_fault and diagnosis:
        raise Refused("close --core-fault takes no --diagnosis: it is the request's (stops.py core-fault), which the "
                      "fresh reviewer judged")
    rec = (_core_fault_doc(cfg, s, doc, core_fault) if core_fault
           else _close_doc(cfg, s, doc, human, delegated, cured))
    if rec["by"] == "cure" and not rec["rerun"]["passes"]:
        j = 1 + sum(1 for ev, x, _k, _r in tally_events(cfg) if x == s and ev == "fail")
        p = os.path.join(sd, f"CURE{j}.json")
        json.dump(rec, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
        try:
            commit([p], f"stop {s} cure {j}")
        except Refused:
            os.remove(p)
            raise
        try:
            last = rec["attempt"] >= project.CURE_BUDGET or bool(cures_spent(cfg, doc)[1])
        except Refused:
            last = True
        project.log_append(cfg, "Stops", f"- stop {s}: release self-cure attempt {rec['attempt']} of "
                                         f"{project.CURE_BUDGET} failed (`{rec['check']}` exits {rec['rerun']['exit']}): "
                                         f"{rec['text']}" + ("; the budget is spent: classify it" if last else ""))
        raise Refused(f"`{rec['check']}` still fails (exit {rec['rerun']['exit']}): cure attempt {rec['attempt']} of "
                      f"{project.CURE_BUDGET} recorded"
                      + (f" (tool patch {rec['tool_patch']} applied: its diagnosis was wrong or incomplete -- re-diagnose: "
                         f"a new tool patch on {s} (tool_patch.py begin --stop {s}), or the printed cure; never a stop)"
                         if rec.get("tool_patch") else "")
                      + (". The cure budget is spent: " + CLASSIFY_HINT.format(s=s) if last else "; cure again"))
    line = _close_line(cfg, s, rec)
    p = os.path.join(sd, "CLOSED.json")
    json.dump(rec, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        commit([p], f"stop {s} close")
    except Refused:
        os.remove(p)
        raise
    project.log_append(cfg, "Stops", line)
    return rec


# U2 §6.4/§6.6 (B10): what the delivery phase records stays out of the generated documents (it is listed in
# README section D, written by --deliver into the delivery copy): a disclosed fault whose every code is a
# presentation fault of a delivered document (DELIVERY_PHASE_CODES: reader findings, the PDF -- an older run's code,
# kept so its D records stay in README D (PDF-AGENTS review 2) --, its rendering),
# and a stop whose every code is a delivery code (project.DELIVERY_CODES; such stops are refused since B10,
# an older run may hold one). Otherwise a reader's disclosure would make the report stale and loop (M2).
DELIVERY_PHASE_CODES = frozenset({"reader", "pdf", "render"})


def delivery_phase(codes, stop=False):
    """True when a record with these cause codes belongs to the delivery phase (README D), not to the run's
    generated documents: a D record (stop=False) whose codes are all DELIVERY_PHASE_CODES, a stop (stop=True)
    whose codes are all project.DELIVERY_CODES. No code: never."""
    codes = {str(c) for c in codes}
    return bool(codes) and codes <= (set(project.DELIVERY_CODES) if stop else DELIVERY_PHASE_CODES)


def _phase_ok(phase, is_delivery):
    return phase is None or (phase == "delivery") == is_delivery


# Trial #7 audit: what a self-cure did, by the cure kinds it recorded (project.CURES). Only a redo (a round set
# aside and its review re-run in a fresh round) says that independence was compromised; a sign-off text restored
# by a rerun said so too, which was false.
CURE_DONE = {
    "rerun": "the mechanical fault was fixed and the check re-run",
    "restore": "the changed file was restored to its last trusted version and the check re-run",
    "redo": ("the independence of a review was compromised: its round was set aside and the review redone in a "
             "fresh round"),
    "reprove": "the Lean was changed and the check re-run",
    "patch": "the audit tool was patched (an independent agent reviewed the patch) and the check re-run",
}
CURE_DONE["set-aside"] = CURE_DONE["redo"]          # older close records name the set-aside step


def cure_done(kinds):
    """The plain words for what a self-cure of these kinds did (CURE_DONE); an unknown kind: the check re-run."""
    out = [CURE_DONE[k] for k in dict.fromkeys(kinds or []) if k in CURE_DONE]
    return "; ".join(dict.fromkeys(out)) or "the check was re-run"


def stop_rows(cfg, rd=None, phase=None):
    """[dict] of EVERY stop, for the report and `list`: the stop, its classes, who closed it, how. `phase`
    "run": only the stops the generated documents list; "delivery": only those README D lists
    (delivery_phase); None: all."""
    rd = rd or rounds_dir(cfg)
    out = []
    for s in stops(cfg, rd):
        d = load(os.path.join(rd, STOPS, s, "STOP.json")) or {}
        if not _phase_ok(phase, delivery_phase([x.get("code") for x in d.get("causes") or []], stop=True)):
            continue
        c = load(os.path.join(rd, STOPS, s, "CLOSED.json"))
        first = next((x["line"] for x in d.get("causes") or []), "")
        what = (f"`{d.get('command')}` exited {d.get('exit')}: {project.full(first)}" if d.get("command")
                else f"a failed tool call (operator's note: {project.full(d.get('note', ''))})")
        if c:
            who = ("the human (answer, verbatim: \"" + c.get("text", "") + "\")" if c.get("by") == "human"
                   else (f"the operator (release, a fault in the proof-validity core, no Lean-side workaround; so "
                         f"{core_fault_tech(c)}, not verified; judged by a fresh reviewer, {c.get('review')}, approve: "
                         f"\"{c.get('review_reason', '')}\"; the failure lines it judged, the only ones delivery "
                         f"accepts: " + "; ".join(f"`{cc}`: " + " | ".join(ls) for cc, ls in c.get("failing") or [])
                         + "): " + c.get("text", "")) if c.get("by") == "core-fault"
                   else (f"the operator (release self-cure, attempt {c.get('attempt')} of {c.get('budget')}; "
                         f"{', '.join(c.get('cures') or [])}; {cure_done(c.get('cures'))}): "
                         + c.get("text", "")) if c.get("by") == "cure"
                   else "the operator (delegated): " + c.get("text", ""))
            rr = c.get("rerun")
            done = "closed" + (f"; the check {'passes' if rr.get('passes') else 'still fails'} at the close" if rr else "")
        else:
            who, done = "nobody yet", ("OPEN: the run waits for the human" if not cure_plan(cfg, d)
                                       else "OPEN: the operator is curing it")
        what_full = (f"`{d.get('command')}` exited {d.get('exit')}: {first}" if d.get("command")
                     else f"a failed tool call (operator's note: {d.get('note', '')})")
        out.append({"stop": s, "date": d.get("date"), "round": d.get("round"), "what": what, "what_full": what_full,
                    "classes": sorted({x["class"] for x in d.get("causes") or []}), "by": who, "done": done,
                    "human": bool(c and c.get("by") == "human"), "cured": bool(c and c.get("by") == "cure"),
                    "answer": c.get("text", "") if c and c.get("by") == "human" else "",
                    "core": core_fault_marker(c) if c and c.get("by") == "core-fault" else "",
                    "attempts": len(cure_attempts(cfg, s)) if rd == rounds_dir(cfg) else 0})
    return out


def do_list(cfg):
    for r in stop_rows(cfg):
        print(f"{r['stop']}  {r['date']}  [{', '.join(r['classes'])}]  {r['what'][:70]}  -> {r['by'][:60]}; {r['done']}")
    for r in set_aside_rows(cfg):
        print(f"set-aside {r['scope']}  {r['date']}  {r['summary'][:120]}")
    for r in disclosed_rows(cfg):
        print(f"{r['stop']}  {r['date']}  [{', '.join(r['codes'])}]  {r['what'][:110]}  (disclosed)")
    return 0


# --- set-aside ----------------------------------------------------------------------------------

def _status(audits, path):
    st = git(audits, "status", "--porcelain", "--untracked-files=all", "--", os.path.relpath(path, audits))
    return [l for l in st.splitlines() if l.strip()]


def committed(audits, path):
    return bool(git(audits, "log", "-1", "--format=%H", "--", os.path.relpath(path, audits), check=False))


def marker_path(rd_r, lane=None):
    return (os.path.join(rd_r, project.ABANDONED) if not lane
            else os.path.join(rd_r, ".abandoned", lane.replace("/", "__") + ".json"))


def lane_status(v):
    """sealed | unsealed (returned, token valid, not sealed) | not-returned | invalid:<code>."""
    import lane_auth
    if not os.path.exists(v):
        return "not-returned"
    p = lane_auth.validate(v)
    if not p:
        return "sealed"
    code = p[0][1:p[0].index("]")]
    if code == "unsealed" and not lane_auth.validate(v, require_seal=False):
        return "unsealed"
    return "invalid:" + code


def _fails(v, data=None):
    try:
        doc = json.loads(data) if data is not None else json.load(open(v, encoding="utf-8"))
    except (OSError, ValueError):
        return []
    import lanecheck
    return [(str(x.get("item")), x.get("verdict")) for x in lanecheck.lane_entries(doc) or []
            if x.get("verdict") in ("Fail", "Ambiguous")]


def sealed_fails(v):
    """[(item, verdict)] of the Fails of a lane's SEALED bytes when its file differs from its seal (self-cure
    review M1: a set-aside on a self-cure stop carries the sealed Fail, never the tampered verdict): the
    version in git whose SHA-256 is the seal's. [] when the lane is not sealed or its file is the sealed
    one; None when the sealed bytes are nowhere in git (they cannot be carried: the human's)."""
    import lane_auth
    sd = lane_auth.sealed_doc(v) if os.path.exists(v) else None
    want = (sd or {}).get("sha256")
    if not want:
        return []
    try:
        if sha(open(v, "rb").read()) == want:
            return []
    except OSError:
        pass
    audits = project.AUDITS
    rel = os.path.relpath(v, audits)
    for h in _log(audits, "--format=%H", "--", rel).split():
        b = subprocess.run(["git", "-C", audits, "show", f"{h}:{rel}"], capture_output=True).stdout
        if sha(b) == want:
            return _fails(v, b.decode("utf-8", "replace"))
    return None


def round_causes(cfg, rd_r, lanes):
    """[(code, line)] of the STOP-class causes the round carries: its lanes' authentication and
    after-seal checks, and any stop of the round the human has not closed."""
    import lane_auth, lanecheck
    out = []
    for v in lanes:
        if os.path.exists(v):
            for p in lane_auth.validate(v):
                code = p[1:p.index("]")]
                if project.is_stop_cause(code):
                    out.append((code, p))
            for f in lanecheck.lane_problems(rd_r, v):
                code = lanecheck.flag_code(f)
                if code and project.is_stop_cause(code):
                    out.append((code, f))
    for r in stop_rows(cfg):
        if r["round"] == os.path.basename(rd_r) and not r["human"]:
            d = load(os.path.join(rounds_dir(cfg), STOPS, r["stop"], "STOP.json")) or {}
            for c in stop_class(d):
                out.append((c, f"stop {r['stop']} ({c}) is not closed by the human"))
    return out


def _resume_set_aside(cfg, rd_r, rnd, lane, doc, files):
    """A set-aside killed between writing its marker and committing it (ROUND3 L1; R3c N2). The marker
    found on disk is never committed as found: `doc` and `files` are recomputed now, after every
    refusal of set_aside; the marker is committed (with those files) only when it equals `doc`
    (its date may be any day up to today). Otherwise refused, the file left for the human, with the
    exact recovery. Returns (doc on disk, commit), or None when there is no uncommitted marker."""
    marker = marker_path(rd_r, lane)
    if not os.path.exists(marker):
        return None
    what = lane or rnd
    found = load(marker)
    want = dict(doc)
    if isinstance(found, dict) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(found.get("date"))) \
            and str(found["date"]) <= want["date"]:
        want["date"] = found["date"]
    if found != want:
        diff = sorted(k for k in set(want) | set(found if isinstance(found, dict) else {})
                      if not isinstance(found, dict) or found.get(k) != want.get(k))
        cmd = (f"python3 audits/stops.py set-aside {rnd} --reason \"{doc['reason']}\""
               + (f" --lane {lane}" if lane else "") + (f" --unsealable {','.join(doc['unsealable'])}" if doc["unsealable"] else "")
               + (f" --stop {doc['stop']}" if doc["stop"] else ""))
        raise Refused(f"an uncommitted set-aside marker {os.path.relpath(marker, project.AUDITS)} of {what} differs from the "
                      f"one computed now ({', '.join(diff) or 'unreadable'}): it is never committed as found. Recover: "
                      f"rm {os.path.relpath(marker, project.AUDITS)} && {cmd}")
    h = commit(files + [marker], f"set-aside {rnd}" + (f" {lane}" if lane else ""))
    project.log_append(cfg, "Set-asides", f"- ({found.get('date')}) {'re-vote lane ' + lane + ' of ' if lane else ''}"
                       f"round {rnd} set aside (an interrupted set-aside, completed). Reason: {found.get('reason')}")
    return found, h


def _commit_of(audits, path, subject):
    """The one commit with `subject` that touched `path`, else None (none, or more than one)."""
    hs = [l.split(" ", 1)[0] for l in _log(audits, "--format=%H %s", "--", os.path.relpath(path, audits)).splitlines()
          if l.partition(" ")[2] == subject]
    return hs[0] if len(hs) == 1 else None


def _scope_commit(audits, round_dir):
    """The commit that first added the round's TARGET.json (its scope commit), or None."""
    return (git(audits, "log", "--diff-filter=A", "--format=%H", "--",
                os.path.relpath(os.path.join(round_dir, "TARGET.json"), audits), check=False).split() or [None])[-1]


# TRADEOFFS T34: an earlier self-cure is judged by the apparatus it was made under -- the pin in
# force at its close commit -- never by today's tables: an apparatus re-pin that changes project.RELEASE, CLOSER,
# FORMS or build_cmds would otherwise make the trail call a correct cure "a human stop" (the recompute-from-today
# class of false alarm of f22a92d and 4dd9a08). Same pin: today's code IS that apparatus. Another pin: its
# committed scripts are run in a subprocess on the stop record. Anything unreadable: today's (the old behaviour).
_PLAN_AT = {}


def _pin_commit(audits, rel_pin, rev=None):
    txt = git(audits, "show", f"{rev}:{rel_pin}", check=False) if rev else None
    try:
        doc = json.loads(txt) if rev else load(os.path.join(audits, rel_pin))
    except ValueError:
        return None, {}
    return (doc or {}).get("audits_commit"), (doc or {}).get("config") or {}


def _plan_with_apparatus(cfg, doc, commit, pinned_cfg):
    """cure_plan of stop record `doc` as the apparatus committed at `commit` (the audits repo) judges it; raises
    on anything it cannot do."""
    import shutil, tempfile
    key = (commit, json.dumps(doc, sort_keys=True), json.dumps(pinned_cfg, sort_keys=True, default=str))
    if key in _PLAN_AT:
        return _PLAN_AT[key]
    names = [n for n in git(project.AUDITS, "ls-tree", "--name-only", commit).split() if n.endswith(".py")]
    if "stops.py" not in names or "project.py" not in names:
        raise ValueError(f"no apparatus at {commit[:11]}")
    tmp = tempfile.mkdtemp(prefix="stops-pin-")
    try:
        for n in names:
            open(os.path.join(tmp, n), "w", encoding="utf-8").write(git(project.AUDITS, "show", f"{commit}:{n}") + "\n")
        code = ("import sys, json; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]); import project; "
                "project.AUDITS, project.REPO = sys.argv[2], sys.argv[3]; import stops; a = json.load(sys.stdin); "
                "print(json.dumps(stops.cure_plan(a['cfg'], a['doc'])))")
        r = subprocess.run([sys.executable, "-I", "-B", "-c", code, tmp, project.AUDITS, project.REPO],
                           input=json.dumps({"cfg": dict(cfg, **pinned_cfg), "doc": doc}, default=str),
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise ValueError(r.stderr.strip()[-300:])
        _PLAN_AT[key] = json.loads(r.stdout.strip().splitlines()[-1])
        return _PLAN_AT[key]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def recorded_plan(cfg, s, doc, rd=None, audits=None):
    """cure_plan of stop `s` (record `doc`) as the apparatus pinned at its close commit judged it (T34)."""
    import integrity
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    rel_pin = os.path.relpath(os.path.join(rd, integrity.PIN), audits)
    h = _commit_of(audits, os.path.join(rd, STOPS, s, "CLOSED.json"), f"stop {s} close")
    then, pinned = _pin_commit(audits, rel_pin, h) if h else (None, {})
    now, _c = _pin_commit(audits, rel_pin)
    if not then or then == now:
        return cure_plan(cfg, doc)
    try:
        return _plan_with_apparatus(cfg, doc, then, {k: v for k, v in pinned.items() if v is not None})
    except (ValueError, OSError, Refused, subprocess.SubprocessError):
        return cure_plan(cfg, doc)


def _cure_stop(cfg, stop, rnd):
    """True when `stop` is a stop of round `rnd` that release mode self-cures (open, or closed --cured):
    its set-aside is the cure's own step (project.CURES "redo")."""
    try:
        d = load(os.path.join(stop_dir(cfg, stop), "STOP.json")) or {}
        c = load(os.path.join(stop_dir(cfg, stop), "CLOSED.json"))
    except Refused:
        return False
    return (d.get("round") == rnd and (c is None or c.get("by") == "cure")
            and bool(cure_plan(cfg, d) if c is None else recorded_plan(cfg, stop, d)))


def set_aside(cfg, rnd, reason, lane=None, unsealable=(), stop=None):
    """Commit every remaining file of round `rnd` (or of its re-vote lane `lane`) with an inventory,
    as "set-aside R [lane]". Returns (marker doc, commit)."""
    import lane_auth, lanecheck
    if not rnd or not project.ROUND_RE.match(rnd):
        raise Refused(f"{rnd!r} is not a round name")
    if not str(reason or "").strip():
        raise Refused("--reason is required: why the round (or lane) will never be adjudicated")
    audits = project.AUDITS
    rd_r = os.path.join(rounds_dir(cfg), rnd)
    if not os.path.isdir(rd_r):
        raise Refused(f"no round {rnd}")
    if committed(audits, marker_path(rd_r, lane)):
        raise Refused(f"{lane or rnd} is already set aside")
    adopted = os.path.join(rd_r, "ADOPTED.md")
    if lane:
        if not re.fullmatch(r"revote/[a-z-]+--[A-Za-z0-9_.-]+", lane):
            raise Refused("--lane names a re-vote lane, revote/<lane>--<item> (a reviewer lane is never set "
                          "aside alone: set the round aside, or re-vote it)")
        if project.is_abandoned(rd_r):
            raise Refused(f"{rnd} is already set aside")
        marker = marker_path(rd_r, lane)
        v = os.path.join(rd_r, lane + ".json")
        if not os.path.exists(os.path.join(rd_r, ".lane-auth", lane + ".json")):
            raise Refused(f"{lane} of {rnd} was never issued")
        lanes = [v]
        probes = [p for p in glob.glob(os.path.join(rd_r, glob.escape(lane) + ".probes", "**"), recursive=True)
                  if os.path.isfile(p)]
        prompts = [p for p in glob.glob(os.path.join(rd_r, "prompts", "*.txt"))
                   if v in open(p, encoding="utf-8", errors="replace").read()]
        cand = [f for f in [v] + probes + prompts if os.path.exists(f)]
    else:
        marker = marker_path(rd_r)
        if os.path.exists(adopted) or committed(audits, adopted):
            raise Refused(f"{rnd} was adjudicated (it has ADOPTED.md): an adjudicated round is never set aside "
                          f"(an unsettled re-vote lane of it is: --lane revote/...)")
        lanes = sorted(set(lanecheck.lane_files(rd_r)) | {
            os.path.join(rd_r, os.path.relpath(p, os.path.join(rd_r, ".lane-auth")))
            for p in glob.glob(os.path.join(rd_r, ".lane-auth", "**", "*.json"), recursive=True)
            if not lanecheck.is_abandoned_lane(rd_r, os.path.relpath(p, os.path.join(rd_r, ".lane-auth")))})
        cand = [rd_r]
    lines = sorted({l for f in cand for l in _status(audits, f)})
    changed = [l for l in lines if not l.startswith("??")]
    if changed:
        raise Refused(f"a committed record of {rnd} changed ({changed[0].strip()}): restore it (git checkout); "
                      f"a set-aside never commits a change to a record")
    files = sorted(f for f in (os.path.join(audits, l[3:].strip().strip('"')) for l in lines)
                   if os.path.abspath(f) != os.path.abspath(marker))
    never = [f for f in files if os.path.basename(f) in NEVER_SET_ASIDE]
    if never:
        raise Refused(f"{os.path.relpath(never[0], rd_r)} is uncommitted: its own step commits it, never a set-aside"
                      + (" (a bundle `signoff.py bundle` did not commit is no record: rm it, then set the round aside)"
                         if os.path.basename(never[0]) == "STATEMENTS_BUNDLE.md" else ""))
    stray = [f for f in files if os.path.relpath(f, rd_r).startswith(".abandoned" + os.sep)]
    if stray:
        raise Refused(f"{os.path.relpath(stray[0], audits)} is an uncommitted re-vote lane set-aside marker: it is never "
                      f"committed as found. Recover: rm {os.path.relpath(stray[0], audits)}, then run that lane's "
                      f"set-aside again (stops.py set-aside {rnd} --lane ...) or this one")
    status = {os.path.relpath(v, rd_r): lane_status(v) for v in lanes}
    if lane and status.get(lane + ".json") == "sealed" and not lanecheck.lane_problems(rd_r, lanes[0]):
        # a sealed, clean re-vote is settled by "adjudicate R revotes": setting it aside would leave its
        # verdict unread and its item to any later row (ROUND3 M4/T10)
        raise Refused(f"{lane} is sealed and has no fault of its own: it is settled, not set aside -- write the "
                      f"decision of its item in ADOPTED.md and commit it with integrity.py --commit-adjudication "
                      f"--round {rnd} --revotes")
    names = {u.strip() if u.strip().endswith(".json") else u.strip() + ".json" for u in unsealable if u.strip()}
    for n in sorted(names):
        if status.get(n) not in ("unsealed",) and not str(status.get(n, "")).startswith("invalid:"):
            raise Refused(f"--unsealable {n}: not a returned, unsealed lane of this set-aside ({status.get(n, 'unknown')})")
    waiting = [n for n, st in status.items() if st == "unsealed" and n not in names]
    if waiting:
        raise Refused(f"{waiting[0]} returned and is not sealed: seal it first from its own LANE_COMPLETION line "
                      f"(lane_auth.py seal); if it cannot be sealed (its digest is lost, or the seal was refused), "
                      f"name it in --unsealable -- its Fails are carried forward either way")
    tamper = round_causes(cfg, rd_r, lanes)
    human_stop, cure_by = None, False
    if stop:
        d = load(os.path.join(stop_dir(cfg, stop), "STOP.json")) or {}
        c = load(os.path.join(stop_dir(cfg, stop), "CLOSED.json")) or {}
        if d.get("round") != rnd or (c.get("by") != "human" and not _cure_stop(cfg, stop, rnd)):
            raise Refused(f"--stop {stop} is not a stop of {rnd} closed by the human"
                          + (" or being self-cured (release mode)" if project.mode(cfg) == "release" else ""))
        human_stop, cure_by = stop, c.get("by") != "human"
    if tamper and project.delegates(cfg) and not human_stop:
        raise Refused(f"{rnd} carries a STOP-class cause ({tamper[0][1][:160]}): "
                      + (f"release mode: set it aside on the self-cure stop of the round -- open one (stops.py open "
                         f"--cmd \"<the failing check>\" --round {rnd}) and pass --stop S<n> while it is open (its cure)"
                         if project.mode(cfg) == "release" else
                         f"under a delegating level only the human sets it aside. Open a stop for the round (stops.py "
                         f"open ... --round {rnd}), ask the human, close it with --human, and pass --stop S<n>"))
    carried = [{"lane": n, "item": it, "verdict": vd, "status": status[n]}
               for n in sorted(status) for it, vd in _fails(os.path.join(rd_r, n))]
    if human_stop and _cure_stop(cfg, human_stop, rnd) and (load(os.path.join(stop_dir(cfg, human_stop), "CLOSED.json"))
                                                           or {}).get("by") != "human":
        # a self-cure's set-aside (release): a verdict changed after its seal is carried as SEALED (review M1)
        lost = []
        for n in sorted(status):
            sf = sealed_fails(os.path.join(rd_r, n))
            if sf is None:
                # RELEASE-SWEEP S6: the sealed bytes are nowhere in git, so its Fails cannot be read. Never a human
                # stop: every item the round scoped for that lane is carried forward as Ambiguous (conservative: the
                # next adjudication decides each one -- ADOPT, DEFER or REVOTE NEEDED), recorded as `sealed_lost`
                tgt = load(os.path.join(rd_r, "TARGET.json")) or {}
                base = lanecheck.lane_base(n[:-len(".json")] if n.endswith(".json") else n)
                sf = [(lanecheck.clean_cell(str(x)), "Ambiguous") for x in (tgt.get(base) or [])
                      if isinstance(tgt.get(base), list)]
                lost.append(n)
            have = {(c["lane"], c["item"], c["verdict"]) for c in carried}
            carried += [{"lane": n, "item": it, "verdict": vd, "status": status[n], "sealed": True}
                        for it, vd in sf if (n, it, vd) not in have]
    doc = {"round": rnd, "lane": lane, "date": today(), "involvement": project.involvement(cfg),
           "delegated": project.delegates(cfg), "reason": " ".join(str(reason).split()), "stop": human_stop,
           "stop_causes": [x[1] for x in tamper], "lanes": status, "unsealable": sorted(names), "carried": carried,
           "files": {os.path.relpath(f, rd_r): sha(open(f, "rb").read()) for f in files}}
    if cure_by:
        doc["stop_by"] = "cure"     # the operator's release self-cure, not the human's answer (review M2)
        if lost:
            doc["sealed_lost"] = lost   # lanes whose sealed verdict is lost: every scoped item carried as Ambiguous
    done = _resume_set_aside(cfg, rd_r, rnd, lane, doc, files)
    if done:
        return done
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    json.dump(doc, open(marker, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        h = commit(files + [marker], f"set-aside {rnd}" + (f" {lane}" if lane else ""))
    except Refused:
        os.remove(marker)
        raise
    summary = (f"{'re-vote lane ' + lane + ' of ' if lane else ''}round {rnd} set aside: {len(files)} file(s) "
               f"committed as record; lanes: " + (", ".join(f"{n} {st}" for n, st in sorted(status.items())) or "none")
               + f"; carried forward: " + ("; ".join(f"{c['item']} ({c['verdict']}, {c['lane']})" for c in carried) or "none"))
    project.log_append(cfg, "Set-asides", (f"- {tag(cfg, 'new round')} " if doc["delegated"] and not human_stop else
                                           f"- ({doc['date']}{(', by the operator: release self-cure of stop ' if cure_by else ', on the human answer of stop ') + human_stop if human_stop else ''}) ")
                       + f"{summary}. Reason: {doc['reason']}")
    return doc, h


def revert(cfg, s, commit_ref):
    """The release self-cure "restore" (project.CURES) of a committed ownership fault (self-cure review M3): restore every
    record file commit `commit_ref` changed without owning it to its content before it, by name, as "revert <C> (stop
    S<n>)", which integrity.py accepts as the exact inverse of that commit's foreign change (integrity.revert_problem:
    by content, never by subject). Only for an open
    self-cure stop that recorded the integrity FAIL naming that commit, and only when nothing changed
    those files since. Returns the revert commit."""
    import integrity
    if project.mode(cfg) != "release":
        raise Refused("revert is a release self-cure; in dev mode the human decides (close --human)")
    sd = stop_dir(cfg, s)
    doc = load(os.path.join(sd, "STOP.json"))
    if not doc or os.path.exists(os.path.join(sd, "CLOSED.json")):
        raise Refused(f"{s} is not an open stop")
    if "restore" not in (cure_plan(cfg, doc) or []):
        raise Refused(f"{s}'s cure is not a restore ({', '.join(cure_plan(cfg, doc) or ['a human stop'])})")
    audits = project.AUDITS
    c = git(audits, "rev-parse", "--verify", "-q", f"{commit_ref}^{{commit}}", check=False)
    if not c or "integrity.py" not in str(doc.get("command")) or c[:11] not in str(doc.get("output")):
        raise Refused(f"{s} did not record an integrity FAIL naming {commit_ref!r}: a revert undoes only the commit "
                      f"its stop's FAIL names")
    rr = os.path.relpath(rounds_dir(cfg), audits)
    files = sorted(integrity.misowned(audits, rr, rounds_dir(cfg), c))
    owned = False
    if not files and re.search(r"FAIL\[(?:record-fix-diff|set-aside-changed)\][^\n]*" + re.escape(c[:11]),
                               str(doc.get("output"))):
        # review R2: a commit of the records' own owner that a check refuses (a record fix beyond its cells, a touch
        # of a set-aside round): its record files are reverted too; a fresh full round then re-writes them
        files, owned = sorted(f for f in integrity.changed_files(audits, c) or () if f.startswith(rr + "/")), True
    if not files:
        raise Refused(f"{c[:11]} changed no record file it does not own")
    new, owner_redo = {}, []
    for f in files:
        if _status(audits, os.path.join(audits, f)):
            raise Refused(f"{f} has uncommitted changes: restore it (git checkout -- {f}), then revert")
        if integrity._blob(audits, "HEAD", f) == integrity._blob(audits, c, f):
            new[f] = integrity._blob_text(audits, c + "^", f)          # the exact inverse
            continue
        # review R1: changed since -- first undo c's change ONTO the current content (git revert semantics): the later
        # work stays; else, if every later change was the owner's, put back the content before c and let a fresh
        # round re-decide it (integrity prints FAIL[owner-redo] until its adjudication)
        merged = integrity._merge_revert(audits, c, f, "HEAD")
        if merged is not None:
            new[f] = merged
            continue
        if integrity.owner_only_since(audits, rr, rounds_dir(cfg), f, c) is not True:
            raise Refused(f"{f} changed since {c[:11]} by a commit that is not its owner's, and {c[:11]}'s change cannot "
                          f"be undone onto the current content: revert that later commit first (its own "
                          f"FAIL[ownership] line names it), then this one; never a human stop")
        new[f] = integrity._blob_text(audits, c + "^", f)
        owner_redo.append(os.path.relpath(f, rr))
    for f, txt in new.items():
        if txt is None:
            os.remove(os.path.join(audits, f))
        else:
            open(os.path.join(audits, f), "wb").write(txt)
    rest = sorted((integrity.changed_files(audits, c) or set()) - set(files))
    h = commit([os.path.join(audits, f) for f in files], f"revert {c} (stop {s})")
    redo = integrity.revert_redo(audits, rr, rounds_dir(cfg), h, c)
    project.log_append(cfg, "Stops", f"- stop {s}: release self-cure, revert {h[:11]} of {c[:11]} undid its change to "
                                     f"{', '.join(os.path.relpath(f, rr) for f in files)}"
                                     + (f"; its other changes ({', '.join(os.path.relpath(f, rr) for f in rest)}) are "
                                        f"not restored and integrity.py still checks them" if rest else "")
                                     + (f"; {', '.join(sorted(redo))} must be re-decided by a fresh "
                                        f"{'full ' if 'full' in redo.values() else ''}round's adjudication "
                                        f"(FAIL[owner-redo] until then)" if redo else ""))
    return h


def markers(rd):
    """[(marker path, round, lane or None)] of every set-aside marker under the rounds dir."""
    out = [(p, os.path.basename(os.path.dirname(p)), None) for p in glob.glob(os.path.join(rd, "*", project.ABANDONED))]
    for p in glob.glob(os.path.join(rd, "*", ".abandoned", "*.json")):
        d = load(p) or {}
        out.append((p, os.path.basename(os.path.dirname(os.path.dirname(p))), d.get("lane")))
    return sorted(out)


def _set_aside_by_cure(cfg, d):
    """True when set-aside marker `d` was the operator's release self-cure, not the human's answer: its
    record says so, or (a marker written before review M2) its stop was not closed by the human."""
    if d.get("stop_by") == "cure":
        return True
    try:
        return (load(os.path.join(stop_dir(cfg, str(d.get("stop"))), "CLOSED.json")) or {}).get("by") != "human"
    except Refused:
        return True


def set_aside_rows(cfg, rd=None):
    """[dict] of every set-aside, with its script-computed inventory, for the report."""
    out = []
    for p, rnd, lane in markers(rd or rounds_dir(cfg)):
        d = load(p) or {}
        lanes = d.get("lanes") or {}
        out.append({"scope": f"{rnd}" + (f" {lane}" if lane else ""), "date": d.get("date"), "reason": d.get("reason", ""),
                    "by": (f"the operator (release self-cure of stop {d['stop']})" if d.get("stop") and _set_aside_by_cure(cfg, d)
                           else "the human (stop " + d["stop"] + ")" if d.get("stop") else
                           "the operator (delegated)" if d.get("delegated") else "the operator, under the involved level"),
                    "summary": f"{len(d.get('files') or {})} file(s) committed; lanes: "
                               + (", ".join(f"{n} {s}" for n, s in sorted(lanes.items())) or "none")
                               + "; carried forward: " + ("; ".join(f"{c.get('item')} ({c.get('verdict')})"
                                                                     for c in d.get("carried") or []) or "none"),
                    "carried": d.get("carried") or [], "stop_causes": d.get("stop_causes") or []})
    return out


def _last_commit(audits, path):
    return git(audits, "log", "-1", "--format=%H", "--", os.path.relpath(path, audits), check=False)


def _after(audits, a, b):
    """True when commit b descends from commit a and is not a."""
    return bool(a and b and a != b and not subprocess.run(["git", "-C", audits, "merge-base", "--is-ancestor", a, b],
                                                          capture_output=True).returncode)


def carried_problems(rds, round_name=None, audits=None, revotes=None):
    """[problem] for every carried-forward item (set-aside) with no row in an ADOPTED.md committed after
    its set-aside -- or in `round_name`'s ADOPTED.md as it stands, for the adjudication about to be
    committed (`revotes`: it is an "adjudicate R revotes" commit). A REJECT row counts only after a
    REVOTE NEEDED row for the item whose re-vote lane ran (sealed; a set-aside one never ran) and was
    decided in an "adjudicate R revotes" commit after its seal (RULINGS A2.2, A7.4; ROUND3 H2). An item
    carried by a set-aside RE-VOTE lane is settled by leaving it open: its round's REVOTE NEEDED row
    still undecided (listed for the human) (R3c N1)."""
    import lanecheck, lane_auth
    ms = markers(rds)
    if not ms:
        return []
    try:
        audits = audits or str(lane_auth.audit_repo(lane_auth.Path(rds)))
    except lane_auth.AuthError as e:
        return [f"the set-aside record cannot be read from git ({e}): every carried item is unchecked"]
    adopted = []
    for ap in sorted(glob.glob(os.path.join(rds, "*", "ADOPTED.md"))):
        rnd = os.path.basename(os.path.dirname(ap))
        h = "WORKTREE" if rnd == round_name else _last_commit(audits, ap)
        if h:
            # the one strict reader (R3e): a row naming no lane or item of its round exactly is about nothing
            adopted.append((rnd, h, lanecheck.valid_rows(os.path.dirname(ap))))
    # the carried lane as the set-aside marker records it (a lane file name, written by this script)
    base_of = lambda l_: lanecheck.lane_base(re.sub(r"\.json$", "", str(l_)))
    def row_ok(rnd, h_, rows, j, carried_verdict):
        # the carried lane's LAST row of the item settles it when it is (ROUND3 H2, M6):
        #   REVOTE NEEDED (the re-vote is pending, listed for the human);
        #   a decision after a REVOTE NEEDED row whose re-vote ran and was decided after its seal;
        #   otherwise an explicit ADOPT, DEFER or QUESTION of the carried verdict itself (its verdict
        #   cell is the carried Fail or Ambiguous) -- never a decision on a fresh lane's Pass, never a
        #   REJECT without the re-vote
        it, d_ = rows[j].item, rows[j].decision
        if d_.startswith("REVOTE NEEDED"):
            return True
        if lanecheck._revote_before(rows, j):
            return not lanecheck.revote_decision_problems(os.path.join(rds, rnd), revotes if h_ == "WORKTREE" else None,
                                                          only={(rows[j].base, it)})
        if d_.startswith("REJECT"):
            return False
        return rows[j].verdict.lower() == str(carried_verdict).lower()
    out = []
    for p, rnd, lane in ms:
        d = load(p) or {}
        h = _last_commit(audits, p)
        if not h:
            continue          # a set-aside not committed is not a set-aside (integrity flags the file)
        later = [x for x in adopted if x[1] == "WORKTREE" or _after(audits, h, x[1])]
        own = next((x for x in adopted if x[0] == rnd), None) if lane else None
        for c in d.get("carried") or []:
            it, cl = c.get("item"), base_of(str(c.get("lane")))
            if own:
                # a set-aside RE-VOTE lane never ran (R3c N1): its item is settled by staying open -- its
                # round's last row of the item still REVOTE NEEDED, listed for the human
                # (or, for a set-aside whole-lane re-vote, the `(whole lane)` row whose re-vote it was)
                js = [j for j, r_ in enumerate(own[2]) if r_.base == cl and (r_.item == it or (
                    r_.item == lanecheck.WHOLE_LANE and lanecheck.set_aside_revote(os.path.join(rds, rnd), r_.lane, r_.item)))]
                if js and own[2][js[-1]].decision.startswith("REVOTE NEEDED"):
                    continue
            # the item's LAST row of the carried lane in each later adjudication decides: a REVOTE NEEDED
            # row followed by a REJECT is a REJECT (ROUND3 H2/T1); another lane's row is not about it (M6)
            mine = [[j for j, r_ in enumerate(rows) if r_.item == it and r_.base == cl]
                    for _, _, rows in later]
            dec = any(mine)
            ok = any(js and row_ok(r_, h_, rows, js[-1], c.get("verdict"))
                     for (r_, h_, rows), js in zip(later, mine))
            if not ok:
                out.append(f"{it} ({c.get('verdict')} in {c.get('lane')}, carried forward by the set-aside of "
                           f"{rnd}{' ' + lane if lane else ''}) has no row of its lane deciding it in an adjudication "
                           f"after the set-aside"
                           + (" (a REJECT needs a REVOTE NEEDED row, then the re-vote lane sealed, then the "
                              "decision in an \"adjudicate R revotes\" commit; an ADOPT or DEFER names the carried "
                              f"verdict, {c.get('verdict')}, in its verdict cell)" if dec else "")
                           + f": give it a row | {cl} | {it} | {c.get('verdict')} | **ADOPT**, **DEFER** or "
                             f"**REVOTE NEEDED** |")
    return out


# --- the trail, for integrity.py ----------------------------------------------------------------

def _log(audits, *a):
    return subprocess.run(["git", "-C", audits, "log", *a], capture_output=True, text=True).stdout


def trail_problems(cfg, audits=None, rd=None):
    """[problem] in the stop record: S1..Sn without gaps, each file committed once by its own step and
    never changed or deleted, one stop open at a time, no delegated close of a STOP class or under the
    involved level, and a delegated set-aside of a round with a STOP-class cause names a stop the
    human closed."""
    audits = audits or project.AUDITS
    rd = rd or rounds_dir(cfg)
    sdir = os.path.join(rd, STOPS)
    rel = os.path.relpath(sdir, audits)
    probs = []
    for d_ in sorted({l for l in _log(audits, "--diff-filter=D", "--format=", "--name-only", "--", rel).splitlines() if l.strip()})[:5]:
        probs.append(f"stop trail: {d_} was deleted; a stop record is never deleted")
    names = sorted(x for x in os.listdir(sdir) if x not in (REPAIRS, DISCLOSED)) if os.path.isdir(sdir) else []
    for f in sorted(glob.glob(os.path.join(sdir, DISCLOSED, "*"))):
        r_ = os.path.relpath(f, audits)
        want = f"stop disclose {os.path.basename(f)[:-len('.json')]}"
        subj = _log(audits, "--format=%s", "--", r_).splitlines()
        if not DISCLOSED_RE.match(os.path.basename(f)) or subj != [want]:
            probs.append(f"stop trail: {STOPS}/{DISCLOSED}/{os.path.basename(f)} must be a disclosure committed "
                         f"once, as \"{want}\" (found {subj[:3]})")
        d_ = load(f) or {}
        bad = [x.get("code") for x in d_.get("faults") or [{}] if project.release_class(x.get("code")) != "N"]
        if project.mode(cfg) != "release" or d_.get("mode") != "release" or bad:
            probs.append(f"stop trail: {STOPS}/{DISCLOSED}/{os.path.basename(f)} discloses "
                         + (f"blocking causes ({', '.join(map(str, bad))})" if bad else
                            f"a fault in a run whose mode is {project.mode(cfg)!r}") + ": only a release run "
                         "discloses, and only class N")
    for f in sorted(glob.glob(os.path.join(sdir, REPAIRS, "*"))):
        r_ = os.path.relpath(f, audits)
        want = f"stop repair {os.path.basename(f)[:-len('.json')]}"
        subj = _log(audits, "--format=%s", "--", r_).splitlines()
        if not REPAIR_RE.match(os.path.basename(f)) or subj != [want]:
            probs.append(f"stop trail: {STOPS}/{REPAIRS}/{os.path.basename(f)} must be a repair record committed "
                         f"once, as \"{want}\" (found {subj[:3]})")
    nums = sorted(int(x[1:]) for x in names if STOP_RE.match(x))
    if nums != list(range(1, len(nums) + 1)):
        probs.append(f"stop trail: the stops are not S1..S{len(nums)} without gaps ({', '.join(names)})")
    open_ = []
    for s in names:
        sd = os.path.join(sdir, s)
        if not STOP_RE.match(s) or not os.path.isdir(sd):
            probs.append(f"stop trail: {STOPS}/{s} is not a stop directory (S<n>)")
            continue
        for f in sorted(os.listdir(sd)):
            if f not in FILES and not CURE_RE.match(f) and not CLASSIFY_RE.match(f) and not CORE_FILE_RE.match(f):
                probs.append(f"stop trail: {STOPS}/{s}/{f} is not a stop record")
        cls_ = sorted((f for f in os.listdir(sd) if CLASSIFY_RE.match(f)), key=lambda f: int(CLASSIFY_RE.match(f).group(1)))
        for i, f in enumerate(cls_, 1):
            want = f"stop {s} classify {i}"
            subj = _log(audits, "--format=%s", "--", os.path.relpath(os.path.join(sd, f), audits)).splitlines()
            a_ = load(os.path.join(sd, f)) or {}
            if f != f"CLASSIFY{i}.json" or subj != [want] or a_.get("as") not in CLASSES_AT_BUDGET \
                    or a_.get("mode") != "release" or project.mode(cfg) != "release" or not a_.get("evidence"):
                probs.append(f"stop trail: {STOPS}/{s}/{f} must be classification {i} of a release run, committed once as "
                             f"\"{want}\" (tool-bug, interference or other, with its evidence)")
        tries = sorted((f for f in os.listdir(sd) if CURE_RE.match(f)), key=lambda f: int(CURE_RE.match(f).group(1)))
        for i, f in enumerate(tries, 1):
            want = f"stop {s} cure {i}"
            subj = _log(audits, "--format=%s", "--", os.path.relpath(os.path.join(sd, f), audits)).splitlines()
            a_ = load(os.path.join(sd, f)) or {}
            if f != f"CURE{i}.json" or subj != [want] or a_.get("by") != "cure" or (a_.get("rerun") or {}).get("passes"):
                probs.append(f"stop trail: {STOPS}/{s}/{f} must be failed cure attempt {i}, committed once as \"{want}\"")
        for f in FILES:
            p_ = os.path.join(sd, f)
            if not os.path.exists(p_):
                continue
            r_ = os.path.relpath(p_, audits)
            subj = _log(audits, "--format=%s", "--", r_).splitlines()
            dirty = bool(subprocess.run(["git", "-C", audits, "status", "--porcelain", "--", r_],
                                        capture_output=True, text=True).stdout.strip())
            want = f"stop {s} {'open' if f == 'STOP.json' else 'close'}"
            if dirty or subj != [want]:
                probs.append(f"stop trail: {STOPS}/{s}/{f} must be committed once, as \"{want}\", and never changed "
                             f"(found {subj[:3]}{', uncommitted changes' if dirty else ''})")
        d = load(os.path.join(sd, "STOP.json"))
        c = load(os.path.join(sd, "CLOSED.json"))
        if not d:
            probs.append(f"stop trail: {s} has no STOP.json")
            continue
        if not c:
            open_.append(s)
            continue
        if c.get("by") == "operator":
            # the mode of the close, or of the open (STOP.json records it since B1b): a forged close that leaves out
            # `mode` is still caught (re-check V5); a record with neither predates B1a and is not judged by it
            if "release" in (c.get("mode"), d.get("mode")):
                probs.append(f"stop trail: {s} was closed by the operator (--delegated) in release mode, where a stop "
                             f"closes only --cured or --human")
            if stop_class(d):
                probs.append(f"stop trail: {s} was closed by the operator although its cause is of a STOP class "
                             f"({', '.join(stop_class(d))})")
            if (d.get("involvement") == "involved" or not project.delegates(cfg)) and not record_fix_only(d):
                probs.append(f"stop trail: {s} was closed by the operator under the involved level")
        elif c.get("by") == "cure":
            if project.mode(cfg) != "release" or c.get("mode") != "release":
                probs.append(f"stop trail: {s} was self-cured in a run whose mode is {project.mode(cfg)!r}: only a "
                             f"release run self-cures")
            elif not recorded_plan(cfg, s, d, rd, audits):
                probs.append(f"stop trail: {s} was self-cured although it is a human stop of release mode")
            want_ = cured_check(d, c)
            if c.get("tool_patch"):     # OPERATOR-PATCH: closed by an applied tool patch made for this stop
                try:
                    import tool_patch
                    info_ = tool_patch.applied_info(cfg, c["tool_patch"], audits=audits, rd=rd)
                except (ImportError, ValueError) as e:
                    info_ = None
                    probs.append(f"stop trail: {s} was closed by tool patch {c['tool_patch']}, which is not applied ({e})")
                if info_ and info_.get("stop") != s:
                    probs.append(f"stop trail: {s} was closed by tool patch {c['tool_patch']}, made for stop "
                                 f"{info_.get('stop')}")
                if info_ and not cure_cmd(d):
                    want_ = info_.get("regression_cmd")
            elif not cure_cmd(d) and recorded_plan(cfg, s, d, rd, audits) == ["patch"]:
                probs.append(f"stop trail: {s} has no read-only check and was closed without a tool patch")
            if not (c.get("rerun") or {}).get("passes") or not isinstance(c.get("attempt"), int) \
                    or not 0 < c["attempt"] or c.get("check") != want_:
                probs.append(f"stop trail: {s}'s self-cure does not show its check passing")
            rr_ = c.get("redo_round")
            if rr_ and (rr_ == d.get("round") or not os.path.isfile(os.path.join(rd, str(rr_), "TARGET.json"))
                        or redo_of(os.path.join(rd, str(rr_))) != d.get("round")
                        or redo_scope_problem(cfg, d.get("round"), rr_, rd)
                        or (load(marker_path(os.path.join(rd, str(d.get("round"))))) or {}).get("stop") != s):
                probs.append(f"stop trail: {s}'s self-cure re-ran its check on round {rr_}, which is not a fresh round "
                             f"redoing round {d.get('round')} set aside by {s}")
            if c.get("redo_lanecheck") != redo_lanecheck(d, rr_):
                probs.append(f"stop trail: {s}'s self-cure on fresh round {rr_} does not record `{redo_lanecheck(d, rr_)}` "
                             f"passing (a redo whose check names no round also runs lanecheck on the fresh round)")
        elif c.get("by") == "core-fault":
            # C2-FIX 5b: the record's mechanical facts, as close --core-fault checked them
            try:
                import tool_patch
                core_ = tool_patch.core_files(audits, rd)
            except Exception:       # noqa: BLE001 -- no first pin: this apparatus's CORE
                import tool_patch
                core_ = tool_patch.CORE
            if project.mode(cfg) != "release" or c.get("mode") != "release":
                probs.append(f"stop trail: {s} was closed as a core fault in a run whose mode is {project.mode(cfg)!r}")
            if c.get("core_file") not in core_ or c.get("check_name") != core_check_name(c.get("core_file")):
                probs.append(f"stop trail: {s} was closed as a core fault of {c.get('core_file')!r}, not a file of the "
                             f"proof-validity core (or its check is misnamed)")
            if "tool-bug" not in {x.get("code") for x in d.get("causes") or []} \
                    and not any(x.get("as") == "tool-bug" for x in classifications(cfg, s, rd)):
                probs.append(f"stop trail: {s} was closed as a core fault but is no tool bug")
            if c.get("check") != cure_cmd(d) or (c.get("rerun") or {}).get("passes") is not False \
                    or not str(c.get("text") or "").strip():
                probs.append(f"stop trail: {s}'s core-fault close does not show its check failing, or has no diagnosis")
            # C2-FIX 5b review: the close stands on a fresh reviewer's sealed approval of the request it names
            req_ = load(os.path.join(sd, f"CORE-REQUEST{c.get('request')}.json")) or {}
            why_ = (_core_review_problem(cfg, s, c.get("request"), rd)[0] if req_ else
                    f"no CORE-REQUEST{c.get('request')}.json")
            if why_ or req_.get("core_file") != c.get("core_file") or \
                    sorted(map(tuple, map(lambda x: (x[0], tuple(x[1])), req_.get("failing") or []))) != \
                    sorted(map(tuple, map(lambda x: (x[0], tuple(x[1])), c.get("failing") or []))):
                probs.append(f"stop trail: {s}'s core-fault close does not stand on a fresh reviewer's sealed approval "
                             f"of its request ({why_ or 'the request names other lines or another file'})")
        elif c.get("by") == "human":
            if not str(c.get("text") or "").strip():
                probs.append(f"stop trail: {s} was closed for the human without their answer")
        else:
            probs.append(f"stop trail: {s} closed by {c.get('by')!r}, neither the human nor the operator")
    if len(open_) > 1:
        probs.append(f"stop trail: {len(open_)} stops are open at once ({', '.join(open_)}); one at a time")
    try:   # the failure tally (U2 §4): every self-cure attempt was made within both ceilings of its keys
        hist = tally_events(cfg, audits, rd)
        probs += [f"stop trail: {w}" for w in UNREADABLE_TALLY.get(os.path.abspath(rd), [])]
        for i, (ev, s, _k, _r) in enumerate(hist):
            if ev in ("fail", "pass"):
                own_, why = tally(hist[:i], s)
                # approver 2026-10-24: past the budget an attempt needs the operator's classification made after
                # those failures (other, or tool-bug with a tool-patch close; never interference)
                c_ = load(os.path.join(sdir, s, "CLOSED.json")) or {} if ev == "pass" else {}
                cl_ = [x for x in classifications(cfg, s, rd) if x.get("after_fail") == own_]
                ok_ = bool(cl_) and cl_[-1].get("as") != "interference" and (
                    cl_[-1].get("as") != "tool-bug" or ev == "fail" or bool(c_.get("tool_patch")))
                if why and not ok_:
                    probs.append(f"stop trail: {s} made a self-cure attempt past its ceilings ({'; '.join(why)}) "
                                 f"without a classification that allows it (stops.py classify: other, or tool-bug with "
                                 f"a tool-patch close); the budget is {project.CURE_BUDGET} failed cures per stop and "
                                 f"{project.KEY_BUDGET} per fault in the run, the openings ceiling "
                                 f"{project.OPEN_CEILING} per round")
    except Refused as e:
        probs.append(f"stop trail: {e}")
    for p, rnd, lane in markers(rd):
        d = load(p) or {}
        if d.get("stop_causes") and d.get("delegated") and not d.get("stop"):
            probs.append(f"stop trail: {os.path.relpath(p, rd)}: a delegated set-aside of a round with a STOP-class "
                         f"cause, without a stop the human closed")
        if d.get("stop"):
            c = load(os.path.join(sdir, str(d["stop"]), "CLOSED.json")) or {}
            if c.get("by") != "human" and not _cure_stop(cfg, str(d["stop"]), d.get("round")):
                probs.append(f"stop trail: {os.path.relpath(p, rd)} names stop {d['stop']}, which the human did not close")
    return probs


# --- repair-lock ---------------------------------------------------------------------------------

def repair_lock(cfg, which, reason):
    """Remove a stale git index.lock (no git process in the repository, older than a minute); logged."""
    if not str(reason or "").strip():
        raise Refused("--reason is required")
    repo = project.AUDITS if which == "audits" else project.REPO
    lock = git(repo, "rev-parse", "--git-path", "index.lock")
    lock = lock if os.path.isabs(lock) else os.path.join(repo, lock)
    if not os.path.exists(lock):
        raise Refused(f"no {lock}: nothing to repair")
    if time.time() - os.path.getmtime(lock) < 60:
        raise Refused("the lock is less than a minute old: a git command may still hold it; wait and retry")
    me, root = os.getuid(), os.path.realpath(repo)
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if os.stat(f"/proc/{d}").st_uid != me or open(f"/proc/{d}/comm").read().strip() != "git":
                    continue
                cwd = os.path.realpath(os.readlink(f"/proc/{d}/cwd"))
            except OSError:
                continue
            if os.path.commonpath([cwd, root]) == root:
                raise Refused(f"a git process (pid {d}) is running in {root}: the lock may be live")
    os.remove(lock)
    project.log_append(cfg, "Stops", f"- repair-lock {which} ({today()}): removed the stale {lock}; "
                                     f"{' '.join(reason.split())}")
    # in the stop record too, which the report lists (ROUND3 L4)
    rdir = os.path.join(rounds_dir(cfg), STOPS, REPAIRS)
    os.makedirs(rdir, exist_ok=True)
    n = 1 + max([int(REPAIR_RE.match(x).group(1)) for x in os.listdir(rdir) if REPAIR_RE.match(x)] or [0])
    p = os.path.join(rdir, f"R{n}.json")
    json.dump({"repair": f"R{n}", "date": today(), "repo": which, "lock": lock, "reason": " ".join(reason.split()),
               "involvement": project.involvement(cfg)}, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        commit([p], f"stop repair R{n}")
    except Refused:
        os.remove(p)
        raise
    return lock


def repair_rows(cfg, rd=None):
    """[dict] of every repair-lock, for the report's stop list (stop, date, what, by, done)."""
    d = os.path.join(rd or rounds_dir(cfg), STOPS, REPAIRS)
    out = []
    for f in sorted(glob.glob(os.path.join(d, "R*.json")), key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)) or 0)):
        r = load(f) or {}
        out.append({"stop": f"repair {r.get('repair', os.path.basename(f))}", "date": r.get("date"),
                    "what": f"stale git lock in the {r.get('repo')} repository removed (stops.py repair-lock): "
                            f"{r.get('reason', '')}", "classes": ["mechanical"], "by": "the operator", "done": "lock removed"})
    return out


# --- disclose (release mode) -------------------------------------------------------------------

def disclose(cfg, cmd=None, note=None, cause=None, script=None):
    """Record a fault disclosed instead of a stop (release mode; project.RELEASE class N). Returns D<n>."""
    if project.mode(cfg) != "release":
        raise Refused(f"the run mode is {project.mode(cfg)!r}: every failure is a stop (stops.py open)")
    if bool(cmd) == bool(note):
        raise Refused("give exactly one of --cmd (the check, read-only form, re-run here) or --note (a crash) "
                      "with --cause tool-fault --script NAME")
    doc = {"date": today(), "mode": "release", "involvement": project.involvement(cfg)}
    if cmd:
        why = command_problem(cmd, cfg)
        if why:
            raise Refused(why)
        rc, out = run_cmd(cmd.split())
        # the exit code alone decides (review L4): a GREEN gate's output quotes its steps' outputs,
        # whose FAIL-like tokens (MISSING, error:) are not failures of the gate
        if rc != 0:
            raise Refused(f"`{cmd}` fails (exit {rc}): a blocking failure is a stop, never a disclosure -- "
                          f"python3 audits/stops.py open --cmd \"{cmd}\"")
        seen = dict.fromkeys((m.group(1), m.group(2).strip()[:300])
                             for m in (DISCLOSED_LINE.match(l) for l in out.splitlines()) if m)
        faults = [{"code": c, "line": t} for c, t in seen]
        if not faults:
            raise Refused(f"`{cmd}` prints no DISCLOSED line: nothing to disclose")
        wrong = sorted({f["code"] for f in faults if project.release_class(f["code"]) != "N"})
        if wrong:
            raise Refused(f"DISCLOSED lines with blocking codes ({', '.join(wrong)}): a stop, not a disclosure")
        doc.update(command=" ".join(cmd.split()), exit=rc, faults=faults)
    else:
        if cause != "tool-fault":
            raise Refused("--note discloses only a crash: --cause tool-fault --script NAME (a check's own findings "
                          "are disclosed with --cmd)")
        if (script not in project.SCRIPT_RELEASE or project.SCRIPT_RELEASE[script] is not None) and \
                script not in project.TOOL_FAULT_SCRIPTS:
            raise Refused(f"--script {script!r}: only a script whose whole job is non-blocking "
                          f"({', '.join(k for k, v in project.SCRIPT_RELEASE.items() if v is None)}) may crash "
                          f"without a stop; any other is unknown-retry, then tool-bug (a stop)")
        doc.update(command=None, note=" ".join(str(note).split()), script=script,
                   faults=[{"code": cause, "line": f"{script}.py: (operator's note)"}])
    d = os.path.join(rounds_dir(cfg), STOPS, DISCLOSED)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        # written and never committed (an interrupted disclose): not a record; recomputed below
        if DISCLOSED_RE.match(f) and not committed(project.AUDITS, os.path.join(d, f)):
            os.remove(os.path.join(d, f))
    # the same fault is disclosed once (mini4 audit: D1-D3 for one name off the page edge, one per render):
    # a fault an earlier record holds (same code, same line up to hashes and page numbers) is not recorded
    # again, and when every fault is held, no record is made and the earlier one is named
    have = _covered(load(os.path.join(d, f)) or {} for f in sorted(
        (x for x in os.listdir(d) if DISCLOSED_RE.match(x)), key=lambda x: int(DISCLOSED_RE.match(x).group(1))))
    new = [x for x in doc["faults"] if _norm(x["code"], x["line"].strip()[:300]) not in have]
    if not new:
        return have[_norm(doc["faults"][0]["code"], doc["faults"][0]["line"].strip()[:300])]
    doc["faults"] = new
    n = 1 + max([int(DISCLOSED_RE.match(x).group(1)) for x in os.listdir(d) if DISCLOSED_RE.match(x)] or [0])
    doc["fault"] = f"D{n}"
    p = os.path.join(d, f"D{n}.json")
    json.dump(doc, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        commit([p], f"stop disclose D{n}")
    except Refused:
        os.remove(p)
        raise
    what = doc["command"] and f"`{doc['command']}`: " + "; ".join(
        f"[{f['code']}] {f['line']}" for f in doc["faults"]) or f"{script}.py: {doc['note']}"
    project.log_append(cfg, "Stops", f"- D{n} ({doc['date']}, release mode: disclosed, not a stop) "
                                     f"{project.clip(what, 600)}")
    return f"D{n}"


# --- the delivery gate (release mode, review H3) ------------------------------------------------
# Every check that can print a DISCLOSED line is re-run at delivery; each live line must be covered
# by a D record (same code, same text up to hashes -- and, for a reader line, digits: a stale pass
# keeps its D record when only the hashes and pass numbers move), and REPORT.md and DECISIONS.md
# must name every D record (the report is regenerated after the last disclose). Refusing instead
# of recording automatically keeps one writer of D records (`disclose`, which re-runs the check),
# and never stalls: each line comes from a check that exits 0 here, so its disclose goes through.
PHASE0_LINES = None   # the selftest's fake for phase0's in-process findings


def _norm(code, text):
    t = re.sub(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,64}\b", "#", " ".join(str(text).split()))
    # a page number moves when the document is rebuilt: the same fault on p.4 and on p.5 is one fault
    # (mini4 audit: one name off the page edge disclosed three times, D1-D3)
    t = re.sub(r"\bp\.\s?\d+", "p.#", t)
    return (code, re.sub(r"\d+", "#", t) if code == "reader" else t)


def _covered(rows):
    """{_norm key: the D<n> that first recorded it} over D record dicts, in D order."""
    out = {}
    for r in rows:
        for x in r.get("faults") or []:
            out.setdefault(_norm(x.get("code"), x.get("line", "")), r.get("fault"))
    return out


def deliver_checks(cfg):
    """The read-only check forms (FORMS) that can disclose, as delivery re-runs them."""
    py = "python3 audits/"
    cmds = [py + "make_report.py --check", py + "decisions.py --check", py + "readers.py --doc summary --check",
            py + "readers.py --doc report --check", py + "readers.py --doc decisions --check",
            py + "selftest_all.py --fast"]
    appr = load(os.path.join(rounds_dir(cfg), "APPROVED_FINGERPRINTS.json")) or {}
    if appr.get("round"):
        cmds.append(py + f"signoff.py check --round {appr['round']}")
        # B10 (U2 §6.3, L4; with stage2-statements.md, "Under hands-off"): the hands-off sheet has no reader;
        # signoff.py check is kept and the README discloses the missing reader
        if project.involvement(cfg) != "hands-off":
            cmds.append(py + "readers.py --doc signoff --round approved --check")
    return cmds


def standard_blocking(cfg):
    """The core checks delivery always re-runs: integrity, Phase 0 read-only, the freeze (when something is
    approved)."""
    py = "python3 audits/"
    cmds = [py + "integrity.py --check", py + "phase0.py --readonly"]
    if (load(os.path.join(rounds_dir(cfg), "APPROVED_FINGERPRINTS.json")) or {}).get("round"):
        cmds.append(py + "fingerprint.py --check")
    return cmds


def deliver_blocking(cfg):
    """The blocking checks delivery re-runs on the state delivered (self-cure review M4): integrity, the
    approval's fingerprints (when something is approved), Phase 0 read-only (the build, the axiom sweep,
    the freeze), and the recorded check of every self-cured stop: a self-cure counts only if its check
    still passes on what ships."""
    cmds = standard_blocking(cfg)
    for s in stops(cfg):
        c = load(os.path.join(stop_dir(cfg, s), "CLOSED.json")) or {}
        if c.get("by") == "cure":
            chk = " ".join(str(c.get("check") or "").split())
            d = load(os.path.join(stop_dir(cfg, s), "STOP.json")) or {}
            # defence in depth (review H-1): a --note stop's codes' own closers too, on the round the cure ran
            # on (a --cmd stop's codes are its own command's output: that command is their check)
            rr = c.get("redo_round") or d.get("round") or _round_of(chk)
            for want in dict.fromkeys([chk] + ([c["redo_lanecheck"]] if c.get("redo_lanecheck") else [])
                                      + [project.closer(str(x.get("code")), rr or "<R>")
                                               for x in d.get("causes") or []
                                               if not d.get("command") and _specific_closer(str(x.get("code")))]):
                if "<R>" in want:
                    cmds.append(f"(self-cured stop {s} names no round, so its closer `{want}` cannot be re-run)")
                    continue
                old = _old_round(cfg, want)
                if old:     # a check bound to a set-aside or superseded round: verified from its recorded pass
                    why = (recorded_pass_problem(cfg, s, c) if _canon(want, cfg.get("name")) in {
                        _canon(chk, cfg.get("name")), _canon(c.get("redo_lanecheck"), cfg.get("name"))} else
                           f"its closer `{want}` is not the check it recorded (`{chk}`)")
                    if why:
                        cmds.append(f"(the check of self-cured stop {s}, `{want}`, names round {old}, set aside or "
                                    f"superseded, so it is not re-run; its recorded pass does not hold: {why})")
                    continue
                cmds.append(want or f"(the check of self-cured stop {s}: none recorded)")
    return list(dict.fromkeys(cmds))


def _round_of(cmd):
    """The value of `cmd`'s --round, or None."""
    a = (cmd or "").split()
    return a[a.index("--round") + 1] if "--round" in a and a.index("--round") + 1 < len(a) else None


def _old_round(cfg, cmd):
    """The round `cmd`'s --round names when that round is no longer the run's current one (set aside, or
    not the newest round: project.rounds), else None. Such a check is valid only for the state it was
    run on: re-running it on the delivered state would stall a correct run (re-check M4)."""
    a = (cmd or "").split()
    r = a[a.index("--round") + 1] if "--round" in a and a.index("--round") + 1 < len(a) else None
    if not r or not re.fullmatch(ROUND_PAT, r):
        return None
    cur = [os.path.basename(p) for p in project.rounds(cfg)]
    return r if not cur or cur[-1] != r else None


def recorded_pass_problem(cfg, s, c):
    """None when the CLOSED.json `c` of self-cured stop `s` is, byte for byte as data, the record its
    "stop S<n> close" commit committed, by the cure, with its recorded check passing; else why not."""
    audits = project.AUDITS
    rel = os.path.relpath(os.path.join(stop_dir(cfg, s), "CLOSED.json"), audits)
    hs = [l.split(" ", 1)[0] for l in _log(audits, "--format=%H %s", "--", rel).splitlines()
          if l.partition(" ")[2] == f"stop {s} close"]
    if len(hs) != 1:
        return f"{len(hs)} \"stop {s} close\" commit(s) of its CLOSED.json, not one"
    at = _show_json(audits, hs[0], rel)
    if at != c:
        return f"its CLOSED.json differs from the one committed by {hs[0][:11]}"
    if at.get("by") != "cure" or not (at.get("rerun") or {}).get("passes") or not at.get("check"):
        return f"the record committed by {hs[0][:11]} does not show its check passing"
    return None


def phase0_lines(cfg):
    """phase0's own disclosures (docstring, run-log), computed in-process: the full gate builds."""
    if PHASE0_LINES is not None:
        return PHASE0_LINES(cfg)
    import phase0
    return ([("docstring", f"{loc}  {msg}") for loc, msg in phase0.docstring_problems(cfg, project.REPO)]
            + [("run-log", msg) for msg in phase0.run_log_problems(cfg, project.REPO)])


def tool_patch_checks(cfg):
    """{the regression command of an applied tool patch that cured a stop}: the check its close recorded
    (CLOSED.json "check", tool_patch.applied_info's regression_cmd), re-run by deliver_gate. It is no FORMS command
    (tests/regressions/ is the patch's own file), so command_problem would refuse it: the DOC-FIX replay of conf1 (a
    generator fault fixed by a tool patch, the stop opened with no --check) could never deliver."""
    out = set()
    for s in stops(cfg):
        c = load(os.path.join(stop_dir(cfg, s), "CLOSED.json")) or {}
        if c.get("by") != "cure" or not c.get("tool_patch"):
            continue
        try:
            import tool_patch
            reg = tool_patch.applied_info(cfg, c["tool_patch"]).get("regression_cmd")
        except Exception:       # noqa: BLE001 -- not applied: the check is judged as any other
            reg = None
        if reg and " ".join(str(c.get("check") or "").split()) == reg:
            out.add(reg)
    return out


# THE MATH GATE (approver, 2026-10-28, binding): after the mathematics is verified, delivery never stops and is never
# refused except by these checks: Phase 0 read-only GREEN (the build, no `sorry` beyond a logged leave line, standard
# axioms only), the freeze (fingerprint.py --check), and the integrity of the proof-validity core (an integrity.py
# FAIL that concerns a core file, a record of the statement freeze, or a record that carries a judgement: a lane's
# verdict, an adjudication, an approval, a round's files). Every other integrity FAIL (a reader, render or hand-edit
# record, a delivered document, a bookkeeping trail, a non-core tool) is a NOTE for the main agent, as is every
# other delivery-phase fault (project._deliver); none opens a stop. A Lean commit after the last audited round
# (deliver-stale) and an open re-approval are checked by project._deliver.
GATE_NOTE_CODES = ("tooling", "pin", "ownership", "tool-patch", "set-aside-changed", "stop-trail", "waiver",
                   "record-changed", "uncommitted-record", "gitmeta", "resolution-trail")
GATE_ROUND_FILE = re.compile(r"(?:^|[\s`'\"(/])\d{4}-\d{2}-\d{2}-[^/\s]+/")


def integrity_blocks(cfg, line):
    """Does the integrity.py --check failure line `line` (a `FAIL[<code>] text` line) concern the proof-validity core
    (the math gate: True), or only a delivery-side or bookkeeping record (a NOTE: False)? Fail closed: only a
    bookkeeping code (GATE_NOTE_CODES) whose faulty thing is no core file, no record of the statement freeze, no
    round's file and no record that carries a judgement (integrity.ackable's test) is a note."""
    import integrity
    m = re.match(r"^\s*FAIL\[([a-z0-9-]+)\]\s*(.*)$", line or "")
    if not m or m.group(1) not in GATE_NOTE_CODES:
        return True
    code, text = m.groups()
    head = integrity._fault_paths(f"[{code}] {text}")
    if integrity.NEVER_ACK_RE.search(" " + head) or GATE_ROUND_FILE.search(" " + head):
        return True
    if code in ("ownership", "set-aside-changed"):
        need = integrity.owner(head.strip(), integrity.pinned_version(rounds_dir(cfg))) or ()
        return bool(set(need) & set(integrity.JUDGEMENT_OWNERS))
    return False


def math_gate(cfg):
    """(block, notes): the math gate's refusals, and what the gate's checks found that does not refuse (NOTEs for the
    main agent). Runs standard_blocking (integrity, Phase 0 read-only, the freeze); in release a failure a core-fault
    close recorded is covered (C2-FIX 5b). Every self-cured stop's recorded check, the disclosures of release mode and
    what a prepared document does not name are run or computed for the notes only."""
    rel = project.mode(cfg) == "release"
    block, notes = [], []
    for cmd in standard_blocking(cfg):
        why = command_problem(cmd, cfg)
        rc, txt = (2, why) if why else run_cmd(cmd.split())
        if rc == 0 or (not why and rel and core_covered(cfg, cmd, txt)):
            continue
        if "integrity.py" in cmd and not why:
            fails = [l.strip() for l in txt.splitlines() if re.match(r"^\s*FAIL\b", l)]
            core_ = [l for l in fails if integrity_blocks(cfg, l)]
            notes += [f"integrity (not the proof-validity core): {l}" for l in fails if l not in core_]
            if fails and not core_:
                continue
            block.append(f"`{cmd}` fails (exit {rc}) on the proof-validity core: "
                         + ("; ".join(core_[:6]) if core_ else (txt.strip().splitlines() or ["no output"])[-1][:300]))
            continue
        tail = [l.strip() for l in (txt or "").splitlines() if FAIL_LINE.search(l)][:6] or \
               [((txt or "").strip().splitlines() or ["no output"])[-1][:300]]
        block.append(f"`{cmd}` fails (exit {rc}){': ' + why if why else ''}: " + "; ".join(tail))
    def noted(what, f):
        try:
            f()
        except Exception as e:      # noqa: BLE001 -- a note, never a refusal
            notes.append(f"{what} could not be computed: {type(e).__name__}: {e}")

    def self_cures():
        for cmd in deliver_blocking(cfg)[len(standard_blocking(cfg)):]:
            if cmd.startswith("(") and cmd.endswith(")"):
                notes.append(cmd[1:-1])
                continue
            why = None if cmd in tool_patch_checks(cfg) else command_problem(cmd, cfg)
            rc, _txt = (2, why) if why else run_cmd(cmd.split())
            if rc:
                notes.append(f"a self-cured stop's recorded check `{cmd}` fails now (exit {rc}){': ' + why if why else ''}")

    def disclosures():
        live = list(phase0_lines(cfg))
        rows = [load(f) or {} for f in glob.glob(os.path.join(rounds_dir(cfg), STOPS, DISCLOSED, "D*.json"))]
        have = {_norm(x.get("code"), x.get("line", "")) for r in rows for x in r.get("faults") or []}
        notes.extend(f"DISCLOSED[{c}] {' '.join(t.split())[:160]} (no D record)" for c, t in live
                     if _norm(c, t.strip()[:300]) not in have)

    def named():
        for doc, gone in unnamed(cfg).items():
            notes.append(f"{doc} does not name {'; '.join(sorted(gone))}")
    noted("the self-cured stops' checks", self_cures)
    if rel:
        noted("phase0's disclosures", disclosures)
    noted("what the prepared documents name", named)
    return block, notes


def deliver_gate(cfg):
    """[why delivery is refused]: the math gate's refusals (math_gate)."""
    return math_gate(cfg)[0]


def unnamed(cfg):
    """{"REPORT.md"|"DECISIONS.md"|"RUN_RECORD.md": [ids or problems]} of what a prepared document must name and
    does not ({} when all do). Approver (2026-10-24): the process record is RUN_RECORD.md -- every stop of the run,
    every stop the operator closed (a release self-cure, a delegated close), every disclosed fault (D<n>), every
    set-aside and every applied tool patch (run_record.listing_problems); REPORT.md names every stop the human
    answered (its "Decisions after the intake": "stop S<n> (" ...), DECISIONS.md's box every closed stop that is a
    decision ("> - stop S<n> (": the human's answer, or a delegated close). A stop closed late (at delivery: mini4
    and mini5 S1) is named too. Each is named by its generated line, not any mention (review L2)."""
    import run_record
    rd = rounds_dir(cfg)
    closed = [r for r in stop_rows(cfg, phase="run") if r["by"] != "nobody yet"]
    want = {"REPORT.md": [(r["stop"], rf"\bstop {re.escape(r['stop'])} \(") for r in closed if r.get("human")],
            "DECISIONS.md": [(r["stop"], rf"(?m)^> - stop {re.escape(r['stop'])} \(") for r in closed
                             if not r.get("cured") and not r.get("core")]}
    # C2-FIX 5b: a check not established by a core fault is said on SUMMARY page 1 and in the report (its marker), and
    # the diagnosis is in the run record
    for c in core_fault_rows(cfg, rd):
        # on SUMMARY's page 1 (its head, before the results), in the report; the record: diagnosis, lines, verdict
        want.setdefault("SUMMARY.md", []).append((f"{c.get('stop')} (marker)", r"\A(?:(?!\n## Results).)*"
                                                  + re.escape(core_fault_marker(c))))
        want.setdefault("REPORT.md", []).append((f"{c.get('stop')} (marker)", re.escape(core_fault_marker(c))))
        for what, t in [("diagnosis", c.get("text", "")), ("verdict", c.get("review_reason", ""))] + [
                ("failure line", l) for _cc, ls in c.get("failing") or [] for l in ls]:
            want.setdefault(run_record.RUN_RECORD_MD, []).append((f"{c.get('stop')} ({what})", re.escape(t)))
    out = {}
    for doc, pats in want.items():
        try:
            txt = open(os.path.join(rd, doc), encoding="utf-8").read()
        except OSError:
            continue        # not written yet: delivery reports it missing
        gone = [i for i, pat in pats if not re.search(pat, txt, re.S)]
        if gone:
            out[doc] = gone
    if os.path.exists(os.path.join(rd, run_record.RUN_RECORD_MD)):
        rr = run_record.listing_problems(cfg)
        if rr:
            out[run_record.RUN_RECORD_MD] = out.get(run_record.RUN_RECORD_MD, []) + rr
    return out


def disclosed_rows(cfg, rd=None, phase=None):
    """[dict] of every disclosed fault (release mode), for the report, DECISIONS.md and the notice. `phase`
    as stop_rows: "run" for the generated documents, "delivery" for README D, None for all."""
    d = os.path.join(rd or rounds_dir(cfg), STOPS, DISCLOSED)
    out, seen = [], {}
    for f in sorted(glob.glob(os.path.join(d, "D*.json")), key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)) or 0)):
        r = load(f) or {}
        fl = r.get("faults") or []
        if not _phase_ok(phase, delivery_phase([x.get("code") for x in fl])):
            continue
        rid = r.get("fault", os.path.basename(f)[:-5])
        keys = [_norm(x.get("code"), x.get("line", "")) for x in fl]
        first = {seen.get(k) for k in keys}
        if keys and len(first) == 1 and None not in first:
            # the same fault recorded again (before the dedupe in disclose): listed once, under its first
            # record, which names this one so every D<n> stays findable (mini4 audit, D1-D3)
            to = first.pop()
            row = next(o for o in out if o["id"] == to)
            row["also"].append(rid)
            row["fault"] = row["stop"] = f"{row['id']} (also recorded as {', '.join(row['also'])})"
            continue
        for k in keys:
            seen.setdefault(k, rid)
        what = (f"`{r.get('command')}` disclosed: " + "; ".join(f"[{x.get('code')}] {x.get('line')}" for x in fl)
                if r.get("command") else f"{r.get('script')}.py crashed or failed (operator's note: {r.get('note', '')})")
        out.append({"id": rid, "also": [], "stop": rid, "fault": rid,
                    "date": r.get("date"), "what": what, "codes": sorted({x.get("code", "?") for x in fl}),
                    "classes": ["disclosed (release mode)"], "by": "the operator (release mode: not a stop)",
                    "done": "disclosed; the run went on"})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", nargs="?", choices=["open", "close", "list", "set-aside", "repair-lock", "disclose", "revert", "classify",
                                                   "core-fault"])
    ap.add_argument("target", nargs="?", help="set-aside: the round; repair-lock: audits|project")
    ap.add_argument("--cmd"); ap.add_argument("--note"); ap.add_argument("--cause"); ap.add_argument("--round")
    ap.add_argument("--stop"); ap.add_argument("--human"); ap.add_argument("--delegated")
    ap.add_argument("--cured", help="close (release mode): the self-cure done"); ap.add_argument("--check")
    ap.add_argument("--core-fault", dest="core_fault", help="close (release mode): the proof-validity core file at fault")
    ap.add_argument("--diagnosis", help="core-fault: the fault, and why no Lean-side workaround works")
    ap.add_argument("--lane"); ap.add_argument("--reason"); ap.add_argument("--unsealable", default="")
    ap.add_argument("--project"); ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--script", help="disclose --note: the registry name of the script that crashed")
    ap.add_argument("--commit", help="revert (release self-cure): the commit the stop's integrity FAIL names")
    ap.add_argument("--as", dest="as_", choices=CLASSES_AT_BUDGET,
                    help="classify (release mode, the cure budget spent): tool-bug, interference or other")
    ap.add_argument("--evidence", help="classify: why (the tool's fault, the recurring events, the different cure)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.command:
        ap.error("give a command")
    try:
        try:
            cfg = project.select(a.project)[0]
        except project.SelectionError:
            # integrated review fix 4: Stage 1 before the config (steps 0-2) -- a human stop kept beside the intake
            if not a.project and project.pre_config_window() and a.command in ("open", "close", "list"):
                return pre_config_main(a)
            raise
        if a.command == "open":
            print(open_stop(cfg, a.cmd, a.note, a.cause, a.round, check=a.check)[1])
        elif a.command == "core-fault":
            req, line = core_fault_request(cfg, a.stop, a.core_fault, a.diagnosis)
            print(f"recorded {os.path.relpath(req, project.AUDITS)}. Spawn a FRESH reviewer (general-purpose; Codex: "
                  f"agent_type formalize_tool_patch_reviewer, fork_turns none; never a lane, the adjudicator or "
                  f"yourself) with: {line}\n  then seal its verdict from its own LANE_COMPLETION line: python3 "
                  f"audits/lane_auth.py seal --verdict <verdict path> --sha256 <sha256> --agent-id <agentId>; then "
                  f"python3 audits/stops.py close --stop {a.stop} --core-fault {a.core_fault} (a rejection: revise and "
                  f"request again, or the ordinary cure; never a stop)")
        elif a.command == "close":
            rec = close_stop(cfg, a.stop, a.human, a.delegated, a.cured, a.check, a.core_fault, a.diagnosis)
            rr = rec.get("rerun")
            print(f"closed {a.stop} ({rec['by']})" + (f"; the check exits {rr['exit']} now" if rr else ""))
        elif a.command == "list":
            return do_list(cfg)
        elif a.command == "set-aside":
            doc, h = set_aside(cfg, a.target, a.reason, a.lane, a.unsealable.split(","), a.stop)
            print(f"set aside {a.target}{' ' + a.lane if a.lane else ''} in commit {h[:11]}: {len(doc['files'])} "
                  f"file(s); carried forward: {len(doc['carried'])} item(s), which the next adjudication must give rows")
        elif a.command == "classify":
            rec, what = classify(cfg, a.stop, a.as_, a.evidence)
            print(f"classified {a.stop} as {rec['as']}: {what}")
        elif a.command == "revert":
            print(f"reverted {a.commit} for {a.stop} in commit {revert(cfg, a.stop, a.commit)[:11]}")
        elif a.command == "disclose":
            print(f"disclosed {disclose(cfg, a.cmd, a.note, a.cause, a.script)}: recorded, logged under ## Stops; "
                  f"the run goes on")
        elif a.command == "repair-lock":
            if a.target not in ("audits", "project"):
                ap.error("repair-lock audits|project")
            print(f"removed the stale {repair_lock(cfg, a.target, a.reason)}")
        return 0
    except project.SelectionError as e:
        print(f"FAIL: {e}"); return 2
    except (Refused, OSError, ValueError) as e:
        print(f"REFUSED: {e}"); return 1


def pre_config_main(a):
    """stops.py open|close|list while no config exists yet (project.pre_config_open; integrated review fix 4)."""
    try:
        if a.command == "open":
            if a.cmd or a.check or a.round:
                raise ValueError("before the config exists a stop is --note \"<what failed>\" --cause <code> only")
            sid = project.pre_config_open(a.note, a.cause)
            print(f"opened {sid} (before the config exists: a human stop, {a.cause}). Show the human what failed and "
                  f"wait; record their answer with python3 audits/stops.py close --stop {sid} --human \"<their answer, "
                  f"verbatim>\". Stage 1 step 5 (project.py --intake-move) moves it under RUN_LOG.md's ## Stops")
        elif a.command == "close":
            r = project.pre_config_close(a.stop, a.human)
            print(f"closed {r['stop']} (human)")
        else:
            for l in project.pre_config_lines() or ["no pre-config stop"]:
                print(l)
        return 0
    except ValueError as e:
        print(f"REFUSED: {e}")
        return 1


# --- self-test ---------------------------------------------------------------------------------

def selftest():
    # commit dates from the monotonic clock: a wall-clock step back under load reordered this fixture's rounds
    # ("release-cure M4", polish 2026-10-24; project.steady_git_clock)
    with project.steady_git_clock():
        return _selftest()


# every self-cure open message ends "...; then classify it)" (48917d2), so a spent budget is told by the classify
# instructions themselves (CLASSIFY_HINT), not the bare words: mutants b1b-r3b and scr-8a survived the bare check
SPENT = CLASSIFY_HINT.split(":")[0] + ":"


def _selftest_core_fault(cfg, cfg_r, d, rd, outs, refused, strail):
    """C2-FIX 5b and its attack review: a fault in the proof-validity core is closed as not established only for the
    named file's own failure lines, after a FRESH reviewer's sealed approval; any other failure keeps its own cure."""
    import lane_auth, shutil
    import make_report as _mr
    res = []

    def say(name, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    def p0(*steps, extra=""):
        return (extra + "".join(f"{x}\n" for x, _n in steps) + "\n" + "=" * 78 + "\nPHASE 0 RESULT (computed by phase0.py "
                "from the exit codes above)\n" + "".join(f"  RED[{c}] {n}  [exit 1]\n" for c, n in
                                                            [(x.split("]")[0].split("[")[1], n) for x, n in steps])
                + f"PHASE 0: RED ({len(steps)} check(s))\n")
    sweep = ("RED[axiom] axiom_sweep.py raised KeyError on `P.thm` (axiom_sweep.py:88)", "axiom sweep")

    def p0_real(tmpname):
        """Phase 0's output as phase0.run and phase0.verdict print it: the build passes, the sweep's Lean fails on
        its temporary file (project.run_lean)."""
        import io, phase0
        phase0.STEP_CODES.clear()
        res_, buf = [], io.StringIO()
        lean = os.path.join(tempfile.gettempdir(), tmpname)
        with contextlib.redirect_stdout(buf):
            phase0.run("build", "lake build P", res_, runner=lambda c_: (0, "Build completed successfully.\n"))
            phase0.run("axiom sweep", "python3 audits/axiom_sweep.py --project P", res_,
                       runner=lambda c_: (1, f"{lean}:41:2: error: unknown constant 'Lean.Elab.Command.liftTermElabM'\n"))
            phase0.verdict(res_)
        return buf.getvalue()
    sorry = ("HARD[sorry] P/Main.lean:40: `P.lem` contains sorry", "token scan: sorry")

    def review(s_, k_, verdict, agent, req_sha=None):
        sd = stop_dir(cfg_r, s_)
        line = None
        v = os.path.join(sd, f"core-review-{k_}.json")
        tok = getattr(review, "tokens", {}).get((s_, k_))
        json.dump({"lane_token": tok, "verdict": verdict, "reason": f"{verdict} REASONQZ",
                   "request_sha256": req_sha or lane_auth.sha(open(os.path.join(sd, f"CORE-REQUEST{k_}.json"), "rb")
                                                              .read())}, open(v, "w"))
        lane_auth.seal(v, lane_auth.sha(open(v, "rb").read()), agent)
        return line

    def request(s_, f_, diag="axiom_sweep.py:88 KeyError on a private name; no refactor avoids it DIAGQZ"):
        req_, line_ = core_fault_request(cfg_r, s_, f_, diag)
        k_ = int(CORE_REQ_RE.match(os.path.basename(req_)).group(1))
        review.tokens = dict(getattr(review, "tokens", {}))
        review.tokens[(s_, k_)] = re.search(r"lane_token is (\w+)", line_).group(1)
        return k_, line_
    keep_ = {k: outs.get(k) for k in ("phase0", "integrity", "fingerprint")}
    try:
        outs["integrity"] = (0, "integrity: OK\n")
        outs["phase0"] = (1, p0(sweep, sorry))
        sc_, _mc = open_stop(cfg_r, note="axiom_sweep.py raises KeyError on every run", cause="tool-bug",
                             check="python3 audits/phase0.py --readonly")
        # the attack review's scenario 1: the sweep really crashes AND a real sorry is in the Lean -> refused
        r_sorry = refused(core_fault_request, cfg_r, sc_, "axiom_sweep.py", "KeyError")
        outs["phase0"] = (1, p0(sweep))
        open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w").write('{"round": "R"}')
        outs["fingerprint"] = (1, "DRIFT P.thm_1_1: approved 1a2b3c4d, now 5e6f7a8b\n")
        r_drift = refused(core_fault_request, cfg_r, sc_, "axiom_sweep.py", "KeyError")     # scenario 2: a drift
        os.remove(os.path.join(rd, "APPROVED_FINGERPRINTS.json"))
        outs["integrity"] = (1, "FAIL[ownership] P/x was committed by \"y\"\n")
        r_own = refused(core_fault_request, cfg_r, sc_, "axiom_sweep.py", "KeyError")
        outs["integrity"] = (0, "integrity: OK\n")
        r_mode = [refused(core_fault_request, cfg, sc_, "axiom_sweep.py", "x"),
                  refused(core_fault_request, cfg_r, sc_, "lanecheck.py", "x"),
                  refused(core_fault_request, cfg_r, sc_, "fingerprint.py", "x"),
                  refused(core_fault_request, cfg_r, sc_, "axiom_sweep.py", " "),
                  refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")]
        outs["phase0"] = (0, "PHASE 0: GREEN\n")
        r_mode.append(refused(core_fault_request, cfg_r, sc_, "axiom_sweep.py", "KeyError"))
        outs["phase0"] = (1, p0(sweep))
        outs["phase0"] = (124, "(timed out after 7200 s)\n")
        r_empty = refused(core_fault_request, cfg_r, sc_, "axiom_sweep.py", "KeyError")
        outs["phase0"] = (1, p0(sweep))
        fpc = lambda t_: ("FAIL[uncoded] fingerprint.py crashed (RuntimeError: lake env lean exited 1: "
                          f"{os.path.join(tempfile.gettempdir(), t_)}:3:0: error: unknown identifier 'x' at 0x7f3a2b1c9d40)")
        say("C2-FIX 5b review 2: a run-specific temporary file or address is not part of a failure line (two runs of the "
            "same crash compare equal, another error does not); a check that fails printing no failure line (a "
            "timeout) is refused, never recorded as an empty set",
            _fail_lines(fpc("tmpaaaa1111.lean")) == _fail_lines(fpc("tmpbbbb2222.lean"))
            and _fail_lines(p0_real("tmpaaaa1111.lean")) == _fail_lines(p0_real("tmpbbbb2222.lean"))
            and _fail_lines(fpc("tmpaaaa1111.lean")) != _fail_lines(fpc("tmpaaaa1111.lean").replace("'x'", "'y'"))
            and _fail_lines("/tmp/proj/P/A.lean:41:2: error: X\n") != _fail_lines("/tmp/proj/P/B.lean:41:2: error: X\n")
            and "prints no failure line" in r_empty)
        say("C2-FIX 5b review: a core-fault request is refused while another failure is open -- a real sorry beside the "
            "crashed axiom sweep, a drift, an ownership FAIL (each keeps its own cure) -- and in dev, for a file "
            "outside the core, for a file whose check is not the stop's, without a diagnosis; no close without a "
            "request",
            "not axiom_sweep.py's own" in r_sorry and "HARD[sorry]" in r_sorry and "DRIFT" in r_drift
            and "FAIL[ownership]" in r_own and "release mode only" in r_mode[0]
            and "not in the proof-validity core" in r_mode[1] and "fingerprint.py --check" in r_mode[2]
            and "--diagnosis" in r_mode[3] and "no core-fault request" in r_mode[4] and "passes now" in r_mode[5])
        k1, line1 = request(sc_, "axiom_sweep.py")
        req1 = load(os.path.join(stop_dir(cfg_r, sc_), f"CORE-REQUEST{k1}.json")) or {}
        r_unsealed = refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")
        review(sc_, k1, "reject", "rev-1")
        r_rej = refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")
        rl_ = "\n".join(core_request_lines(cfg_r))
        say("C2-FIX 5b review: the request records exactly the sweep's own lines and issues a fresh reviewer; the close "
            "waits for its sealed verdict; a rejection refuses it (request again or the ordinary cure, never a stop)",
            [c_ for c_, _l in req1.get("failing") or []] == ["python3 audits/phase0.py --readonly"]
            and sweep[0] in req1["failing"][0][1] and not any("sorry" in l for l in req1["failing"][0][1])
            and "Your lane_token is" in line1 and "not sealed" in r_unsealed and "REJECTS" in r_rej
            and "never a stop" in r_rej and f"stop {sc_}, request {k1}" in rl_ and "REJECTED: reject REASONQZ" in rl_)
        os.makedirs(os.path.join(rd, "R0", ".lane-seals"), exist_ok=True)
        json.dump({"agent_id": "lane-x"}, open(os.path.join(rd, "R0", ".lane-seals", "x.json"), "w"))
        k2, _l2 = request(sc_, "axiom_sweep.py")
        review(sc_, k2, "approve", "lane-x")
        r_fresh = refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")
        os.makedirs(os.path.join(rd, "status-check"), exist_ok=True)       # review 2: a status-check agent's seal too
        json.dump({"agent_id": "sc-agent"}, open(os.path.join(rd, "status-check", "SEAL-1.json"), "w"))
        k2b, _l2b = request(sc_, "axiom_sweep.py")
        review(sc_, k2b, "approve", "sc-agent")
        r_fresh2 = refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")
        shutil.rmtree(os.path.join(rd, "status-check"))
        # review 2: the real shape of the most likely core fault -- axiom_sweep_tail.lean broken against the toolchain:
        # Phase 0's own output (phase0.run, phase0.verdict) with Lean's error on a fresh temporary file each run
        outs["phase0"] = (1, p0_real("tmpa1b2c3d4.lean"))
        k3, _l3 = request(sc_, "axiom_sweep.py")
        review(sc_, k3, "approve", "rev-3")
        outs["phase0"] = (1, p0(sweep, sorry))
        r_foreign = refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")
        outs["phase0"] = (1, p0(("RED[axiom] axiom_sweep.py raised KeyError on `P.other` (axiom_sweep.py:88)",
                                 "axiom sweep")))
        r_new = refused(close_stop, cfg_r, sc_, core_fault="axiom_sweep.py")
        outs["phase0"] = (1, p0_real("tmpz9y8x7w6.lean"))
        rc_ = close_stop(cfg_r, sc_, core_fault="axiom_sweep.py")
        row_ = next(r for r in stop_rows(cfg_r) if r["stop"] == sc_)
        mk_ = core_fault_marker({"core_file": "axiom_sweep.py"})
        cov_ = (core_covered(cfg_r, "python3 audits/phase0.py --readonly", p0_real("tmpq1w2e3r4.lean")),
                core_covered(cfg_r, "python3 audits/phase0.py --readonly", p0(sweep, sorry)),
                core_covered(cfg_r, "python3 audits/fingerprint.py --check", "DRIFT P.thm_1_1: approved 1a2b3c4d\n"),
                core_covered(cfg_r, "python3 audits/integrity.py --check", "FAIL[ownership] P/x\n"))
        say("C2-FIX 5b review: a reviewer that sealed anything else in the run is not fresh; a failure line the reviewer "
            "did not judge (a sorry since) refuses the close; the close stands on the approval; the trail accepts it; "
            "delivery accepts only the judged lines (a sorry, a drift, an ownership FAIL never)",
            "must be fresh" in r_fresh and "status-check/SEAL-1.json" in r_fresh2 and "differ from those the reviewer judged" in r_new
            and "not axiom_sweep.py's own" in r_foreign and rc_["by"] == "core-fault" and rc_["request"] == k3
            and "REASONQZ" in rc_["review_reason"] and not strail(cfg_r, sc_) and row_["core"] == mk_
            and "DIAGQZ" in row_["by"] and "REASONQZ" in row_["by"] and "<temporary file>:41:2: error: unknown "
            "constant" in row_["by"] and cov_ == (True, False, False, False)
            and _mr.page_stops([row_]) == [])
        sm_ = os.path.join(rd, "SUMMARY.md")
        open(sm_, "w").write(f"# Summary\nPhase 0: the Lean builds\n\n## Results\n\n**{mk_}**\n")
        un_ = unnamed(cfg_r)
        open(sm_, "w").write(f"# Summary\n**{mk_}**\n\n## Results\n")
        un2_ = unnamed(cfg_r)
        os.remove(sm_)
        say("C2-FIX 5b review: delivery requires the marker on SUMMARY's page 1 (its head, before the results), not "
            "anywhere in it",
            f"{sc_} (marker)" in un_.get("SUMMARY.md", []) and f"{sc_} (marker)" not in un2_.get("SUMMARY.md", []))
    finally:
        for k, v in keep_.items():
            if v is None:
                outs.pop(k, None)
            else:
                outs[k] = v
    return res


def _selftest():
    import shutil, tempfile
    import integrity, lane_auth
    res = []

    def say(name, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    def refused(f, *x, **k):
        try:
            f(*x, **k)
        except Refused as e:
            return str(e)
        return ""

    global RUNNER
    saved = (project.REPO, project.AUDITS, RUNNER)
    base = tempfile.mkdtemp(prefix="stops-")
    try:
      try:
        d = os.path.join(base, "rec")
        rd = os.path.join(d, "P")
        os.makedirs(rd)
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True).stdout.strip()
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        open(os.path.join(d, ".gitignore"), "w").write("__pycache__/\n")
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("# Run log\n")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = project.AUDITS = d
        cfg = {"name": "P", "rounds_dir": "P", "involvement": "hands-off", "build_cmds": ["lake build P"]}
        agent = os.path.join(base, "agent.md")
        open(agent, "w").write("auditor\n")
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd)
        G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin")
        integ = lambda rnd: [m for sv, m in integrity.check(d, cfg, rnd, agent_file=agent, rounds_dir=rd,
                                                             rounds_rel="P") if sv == "FAIL"]
        outs = {}
        RUNNER = lambda argv: outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, ""))
        # open / close
        say("open refuses a command outside the read-only forms",
            "not part of the read-only form" in refused(open_stop, cfg, cmd="python3 audits/integrity.py --pin"))
        say("lanecheck --kill (an action) is not a check form",
            "not part of the read-only form" in (command_problem("python3 audits/lanecheck.py --round "
                                                                 "2026-10-19-full-1a2b3c4 --kill", cfg) or ""))
        say("open refuses a check that passes", "exits 0 now" in refused(open_stop, cfg, cmd="python3 audits/integrity.py --check"))
        outs["integrity"] = (1, "FAIL P/x was committed by \"y\"\nFAIL[no-such-code] x\nintegrity: 2 FAIL(s)\n")
        s1, m = open_stop(cfg, cmd="python3 -B audits/integrity.py --check")
        doc = load(os.path.join(rd, STOPS, s1, "STOP.json"))
        say("open records the check's raw output and classes an uncoded or unknown cause as a stop",
            s1 == "S1" and doc["exit"] == 1 and stop_class(doc) == ["unknown"] and "--human" in m
            and G("log", "-1", "--format=%s") == "stop S1 open")
        say("one stop at a time", "still open" in refused(open_stop, cfg, note="x", cause="tool-call"))
        say("close --delegated is refused for a STOP class",
            "STOP class" in refused(close_stop, cfg, s1, delegated="fixed it"))
        close_stop(cfg, s1, human="set the round aside")
        say("close --human records the answer verbatim and re-runs the check",
            (load(os.path.join(rd, STOPS, s1, "CLOSED.json")) or {}).get("rerun", {}).get("exit") == 1
            and "the human's answer, verbatim: \"set the round aside\"" in open(os.path.join(rd, "RUN_LOG.md")).read())
        outs["lanecheck"] = (1, "PROBLEM[stray-loop] pid 7\n")
        s2, _ = open_stop(cfg, cmd="python3 audits/lanecheck.py --round 2026-10-19-full-1a2b3c4")
        say("close --delegated is refused while the check still fails",
            "still fails" in refused(close_stop, cfg, s2, delegated="killed it"))
        outs["lanecheck"] = (0, "lane check: OK\n")
        say("trial #11: a close whose text carries a non-canonical dated tag is refused before anything is written",
            "non-canonical" in refused(close_stop, cfg, s2, delegated="fixed the [DELEGATED 2026-10-24] line")
            and not os.path.exists(os.path.join(rd, STOPS, s2, "CLOSED.json")))
        close_stop(cfg, s2, delegated="killed the loop with --kill; bare '[DELEGATED]' and `[PROXY]` mentioned")
        import decisions as _dc
        say("trial #11: a bare tag mentioned in a close's text is accepted and its ## Stops line passes the tag lint",
            not _dc.tag_problems(open(os.path.join(rd, "RUN_LOG.md")).read(), project.involvement(cfg)))
        say("close --delegated of a mechanical cause: closed and logged as [DELEGATED]",
            "[DELEGATED" in open(os.path.join(rd, "RUN_LOG.md")).read() and not trail_problems(cfg, d, rd))
        cfg_i = dict(cfg, involvement="involved")
        s3, _ = open_stop(cfg_i, note="a tool call failed", cause="tool-call")
        say("under the involved level --delegated is refused", "involved" in refused(close_stop, cfg_i, s3, delegated="x"))
        close_stop(cfg_i, s3, human="retry")
        # S1 (release trial): a stop whose every cause is record-fix is the operator's at every level
        h_s1 = G("rev-parse", "HEAD")
        outs["make_report"] = (1, "FAIL[dead-witness] PAPER_DEFECTS.md row 2: `sorry`\nindex check: FAIL -- x\n")
        s4, m4 = open_stop(cfg_i, cmd="python3 audits/make_report.py --check --index-only")
        outs["make_report"] = (1, "FAIL[dead-witness] PAPER_DEFECTS.md row 2: `sorry`\nFAIL[index] 1 dangling\n")
        r4 = refused(close_stop, cfg_i, s4, delegated="x")
        outs["make_report"] = (0, "index check: ok\n")
        close_stop(cfg_i, s4, delegated="record-fix R: witness cell corrected")
        say("S1: a dead-witness stop is cured by the operator under the involved level too (record correction), "
            "only once the check passes, and the trail accepts it",
            "--delegated" in m4 and "still fails" in r4 and not trail_problems(cfg, d, rd))
        outs["make_report"] = (1, "FAIL[dead-witness] a\nFAIL[index] 1 dangling\n")
        s5, m5 = open_stop(cfg_i, cmd="python3 audits/make_report.py --check --index-only")
        say("S1: a stop mixing record-fix with another cause stays the human's under the involved level",
            "--human" in m5 and "involved" in refused(close_stop, cfg_i, s5, delegated="x"))
        close_stop(cfg_i, s5, human="ok")
        G("reset", "-q", "--hard", h_s1)
        # set-aside: a round with a sealed Fail lane and an unsealed (returned) lane
        R = "2026-10-19-full-1a2b3c40000"
        r = os.path.join(rd, R); os.makedirs(os.path.join(r, "prompts"))
        open(os.path.join(r, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {R}")

        def lane(name, verdicts, seal=True):
            v = os.path.join(r, name + ".json")
            os.makedirs(os.path.dirname(v), exist_ok=True)
            pf = os.path.join(r, "prompts", name.replace("/", "__") + ".txt")
            open(pf, "w").write(f"Write that JSON object, and nothing else, to {v}\n")
            tok = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(pf)).group(1)
            data = json.dumps({"lane_token": tok, "probes": lane_auth.probe_manifest(v),
                               "verdicts": [{"item": i, "verdict": x, "next_step": "-"} for i, x in verdicts]}).encode()
            open(v, "wb").write(data)
            if seal:
                lane_auth.seal(v, lane_auth.sha(data), "agent-" + name.replace("/", "-"))
            return v

        lane("correspondence", [("N.a", "Fail")])
        uv = lane("non-vacuity", [("N.b", "Ambiguous"), ("N.c", "Pass")], seal=False)
        say("set-aside refuses while a returned lane is unsealed (seal it first)",
            "not sealed" in refused(set_aside, cfg, R, "superseded"))
        say("set-aside refuses --unsealable for a sealed lane",
            "not a returned, unsealed lane" in refused(set_aside, cfg, R, "x", unsealable=["correspondence"]))
        open(os.path.join(r, "TARGET.json"), "w").write('{"x": 1}')
        say("set-aside refuses a round whose committed record changed (it never sweeps a change)",
            "committed record" in refused(set_aside, cfg, R, "x", unsealable=["non-vacuity"]))
        G("checkout", "--", f"P/{R}/TARGET.json")
        RA = "2026-10-18-full-0a0b0c00000"
        os.makedirs(os.path.join(rd, RA))
        open(os.path.join(rd, RA, "ADOPTED.md"), "w").write("x")
        say("set-aside refuses an adjudicated round", "adjudicated" in refused(set_aside, cfg, RA, "x"))
        shutil.rmtree(os.path.join(rd, RA))
        pf = os.path.join(r, "prompts", "non-vacuity.txt")
        open(pf, "a").write("edited\n")
        say("under a delegating level, a round with a tampering-class cause is set aside only by the human",
            "only the" in refused(set_aside, cfg, R, "superseded", unsealable=["non-vacuity"]))
        s4, _ = open_stop(cfg, note="prompt changed after issue", cause="prompt-changed", round_name=R)
        close_stop(cfg, s4, human="set it aside")
        doc, h = set_aside(cfg, R, "superseded by a full round", unsealable=["non-vacuity"], stop=s4)
        st = G("status", "--porcelain", "--untracked-files=all", "--", f"P/{R}")
        say("set-aside commits every remaining file with an inventory (no rm), and carries the Fails of sealed "
            "and unsealed lanes forward",
            not st and G("log", "-1", "--format=%s") == f"set-aside {R}" and os.path.exists(uv)
            and doc["lanes"] == {"correspondence.json": "sealed", "non-vacuity.json": "invalid:prompt-changed"}
            and [(c["item"], c["verdict"]) for c in doc["carried"]] == [("N.a", "Fail"), ("N.b", "Ambiguous")])
        say("...and the human's stop is recorded", doc["stop"] == s4 and not trail_problems(cfg, d, rd))
        say("an adjudicated or set-aside round is refused", "already set aside" in refused(set_aside, cfg, R, "again"))
        R2 = "2026-10-20-full-2b3c4d50000"
        os.makedirs(os.path.join(rd, R2))
        open(os.path.join(rd, R2, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {R2}")
        HDR = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        open(os.path.join(rd, R2, "ADOPTED.md"), "w").write(HDR + "| correspondence | N.a | Fail | REJECT | no |\n")
        cp = carried_problems(rd, R2, d)
        say("carry-forward: the next adjudication refuses without a row for each carried item, and a bare REJECT "
            "does not count", len(cp) == 2 and "REVOTE NEEDED row, then the re-vote lane sealed" in cp[0] and "N.b" in cp[1])
        open(os.path.join(rd, R2, "ADOPTED.md"), "w").write(
            HDR + "| correspondence | N.a | Fail | **REVOTE NEEDED** | check |\n| correspondence | N.a | Fail | **REJECT** | no |\n"
            "| non-vacuity | N.b | Ambiguous | DEFER | later |\n")
        say("H2 (attack T1): REVOTE NEEDED + REJECT with no re-vote lane does not settle a carried Fail",
            any("N.a" in x for x in carried_problems(rd, R2, d, revotes=True)))
        open(os.path.join(rd, R2, "ADOPTED.md"), "w").write(
            HDR + "| correspondence | N.a | Fail | **REVOTE NEEDED** | check |\n| non-vacuity | N.b | Ambiguous | DEFER | later |\n")
        say("...a row for each settles it", carried_problems(rd, R2, d) == [])
        say("...and the final report (no round under adjudication) still sees the uncommitted rows as missing",
            len(carried_problems(rd, None, d)) == 2)
        G("add", "--", f"P/{R2}/ADOPTED.md"); G("commit", "-qm", f"adjudicate {R2}")
        say("...until they are committed", carried_problems(rd, None, d) == [])
        say("integrity passes the stop record and the set-aside round's files (owned by the set-aside commit)",
            integ(R2) == [])
        open(uv, "a").write(" ")
        G("add", "--", f"P/{R}/non-vacuity.json"); G("commit", "-qm", f"adjudicate {R2}")
        say("a set-aside file touched by any later commit fails",
            any("touched after it was set aside" in m for m in integ(R2)))
        G("reset", "-q", "--hard", "HEAD~1")
        mk = os.path.join(rd, R, project.ABANDONED)
        open(mk, "a").write(" ")
        G("add", "--", f"P/{R}/{project.ABANDONED}"); G("commit", "-qm", f"implement {R2}")
        say("a set-aside marker is committed only by its set-aside", any(f"{R}/{project.ABANDONED}" in m for m in integ(R2)))
        G("reset", "-q", "--hard", "HEAD~1")
        # repair-lock
        lk = os.path.join(d, ".git", "index.lock")
        open(lk, "w").write("")
        say("repair-lock refuses a fresh lock", "less than a minute" in refused(repair_lock, cfg, "audits", "stale"))
        os.utime(lk, (time.time() - 120, time.time() - 120))
        repair_lock(cfg, "audits", "a killed commit left it")
        say("repair-lock removes a stale lock and logs it",
            not os.path.exists(lk) and "repair-lock audits" in open(os.path.join(rd, "RUN_LOG.md")).read())
        say("L4: ... and records it in the stop record (committed once), which the report lists",
            G("log", "-1", "--format=%s") == "stop repair R1" and repair_rows(cfg)[0]["stop"] == "repair R1"
            and "a killed commit left it" in repair_rows(cfg)[0]["what"] and not trail_problems(cfg, d, rd))
        # A9: every cause code a script prints is in project.CAUSES
        import phase0
        code_re = re.compile(r"\b(?:FAIL|PROBLEM|WARNING|NOTE|GITMETA|DRIFT|HARD|RED)\[([a-z0-9-]+)\]"
                             r"|\(\"(?:FAIL|note)\", f?\"\[([a-z0-9-]+)\]|AuthError\([^\n]*'([a-z-]+)'\)$")
        here = os.path.dirname(os.path.abspath(__file__))
        found = {}
        for f in sorted(glob.glob(os.path.join(here, "*.py"))):
            for m in code_re.finditer(open(f, encoding="utf-8").read()):
                c = next(g for g in m.groups() if g)
                found.setdefault(c, os.path.basename(f))
        found.update({c: "phase0.py" for _, c in phase0.PHASE0_CODES})
        missing = sorted(f"{c} ({f})" for c, f in found.items() if c not in project.CAUSES)
        say(f"every printed cause code is in project.CAUSES ({len(found)} found){': missing ' + ', '.join(missing) if missing else ''}",
            not missing and len(found) > 40)
        outs["fingerprint"] = (4, "NOTE[not-approved] no APPROVED_FINGERPRINTS.json: nothing has been approved yet\n")
        say("A9: fingerprint exit 4 (nothing approved) is not a stop",
            "normal state" in refused(open_stop, cfg, cmd="python3 audits/fingerprint.py --check"))
        # A5b: the human's waiver of an ownership FAIL, for a commit that only ADDED files
        h0 = G("rev-parse", "HEAD")
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write("swept\n")
        G("add", "--", "P/PAPER_DEFECTS.md"); G("commit", "-qm", "implement x")
        hx = G("rev-parse", "HEAD")
        def ack(stop_):
            try:
                integrity.acknowledge(d, rd, cfg, hx, stop_); return ""
            except ValueError as e:
                return str(e)
        say("A5b: a waiver needs a stop the human closed", "not closed by the human" in ack(s2))
        say("M3 (attack T6): a human-closed stop about something else does not back a waiver",
            "not about the ownership FAIL" in ack(s1))
        outs["integrity"] = (1, f"FAIL[ownership] P/PAPER_DEFECTS.md was committed by \"implement x\" ({hx[:11]}); "
                                f"only a \"adjudicate …\" commit may change it\nintegrity: 1 FAIL(s)\n")
        s5, _ = open_stop(cfg, cmd="python3 -B audits/integrity.py --check")
        close_stop(cfg, s5, human="waive it")
        say("A5b: ... and is recorded on the stop that showed that commit's ownership FAIL",
            ack(s5) == "" and G("log", "-1", "--format=%s") == f"ack {hx[:11]}")
        say("A5b: the waived commit's ownership FAIL becomes a NOTE, listed for the summary page",
            not any("PAPER_DEFECTS" in m for m in integ(R2)) and integrity.waiver_rows(cfg)[0][0] == hx[:11])
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "a").write("changed\n")
        G("add", "--", "P/PAPER_DEFECTS.md"); G("commit", "-qm", "implement y")
        hy = G("rev-parse", "HEAD")
        outs["integrity"] = (1, f"FAIL[ownership] P/PAPER_DEFECTS.md was committed by \"implement y\" ({hy[:11]}); x\n")
        s6, _ = open_stop(cfg, cmd="python3 -B audits/integrity.py --check")
        close_stop(cfg, s6, human="waive it")
        try:
            integrity.acknowledge(d, rd, cfg, hy, s6); modok = False
        except ValueError as e:
            modok = "only a commit that ADDED" in str(e)
        say("A5b: a commit that changed a record is never waived", modok and any("PAPER_DEFECTS" in m for m in integ(R2)))
        # a failure with no cause code: retried (unknown-retry), then a tool bug (a stop) or an
        # environment fault (cured by the operator)
        sr, _ = open_stop(cfg, note="phase0.py: unexpected git message", cause="unknown-retry")
        close_stop(cfg, sr, delegated="re-ran it once; it passed")
        say("unknown-retry: closed --delegated once the re-run passes", load(os.path.join(rd, STOPS, sr, "CLOSED.json")) is not None)
        # B13 (restarts): a close killed after its commit, before its RUN_LOG.md line: a later close writes the line
        _lp = os.path.join(rd, "RUN_LOG.md")
        _lg = open(_lp, encoding="utf-8").read()
        open(_lp, "w", encoding="utf-8").write("\n".join(l for l in _lg.splitlines() if f"stop {sr} closed" not in l) + "\n")
        _r13 = refused(close_stop, cfg, sr, delegated="again")
        _lg2 = open(_lp, encoding="utf-8").read()
        _r13b = refused(close_stop, cfg, sr, delegated="again")
        say("B13 restart: a close whose RUN_LOG.md line was lost (killed after its commit) gets it from a later close, once",
            f"{sr} is closed" in _r13 and "written now" in _r13 and f"stop {sr} closed: re-ran it once" in _lg2
            and "written now" not in _r13b and open(_lp, encoding="utf-8").read().count(f"stop {sr} closed") == 1)
        st, m = open_stop(cfg, note="Traceback ... File audits/lanecheck.py, KeyError", cause="tool-bug")
        say("tool-bug is a STOP class: --delegated is refused, the human closes it",
            "--human" in m and "STOP class (tool-bug)" in refused(close_stop, cfg, st, delegated="patched it"))
        close_stop(cfg, st, human="wait for the maintainer")
        se, m = open_stop(cfg, note="lake build: cannot open .olean (disk full)", cause="env-unknown")
        close_stop(cfg, se, delegated="freed the run's own build directory; the build passes")
        say("env-unknown: closable with --delegated after a fix", "--delegated" in m
            and load(os.path.join(rd, STOPS, se, "CLOSED.json")) is not None and not trail_problems(cfg, d, rd))
        G("reset", "-q", "--hard", h0)
        say("list prints every stop and set-aside", len(stop_rows(cfg)) == 4 and len(set_aside_rows(cfg)) == 1)
        # trail
        json.dump({"by": "operator", "text": "x"}, open(os.path.join(rd, STOPS, s1, "CLOSED.json"), "w"))
        G("add", "-A"); G("commit", "-qm", "edit")
        tp = trail_problems(cfg, d, rd)
        say("the trail fails a record changed by another commit, and an operator close of a STOP class",
            any("S1/CLOSED.json must be committed once" in p for p in tp) and any("S1 was closed by the operator" in p for p in tp))
        say("integrity runs the stop trail", any("stop trail" in m for m in integ(R2)))
        G("revert", "--no-edit", "HEAD")
        os.makedirs(os.path.join(rd, STOPS, "S7"))
        open(os.path.join(rd, STOPS, "S7", "STOP.json"), "w").write("{}")
        say("the trail fails a gap in the numbering",
            any("without gaps" in p for p in trail_problems(cfg, d, rd)))
        shutil.rmtree(os.path.join(rd, STOPS, "S7"))
        # release mode: disclose (project.RELEASE); S1/S3-like faults are recorded, never stops
        cfg_r = dict(cfg, mode="release")
        dtrail = lambda c_: [p for p in trail_problems(c_, d, rd) if f"/{DISCLOSED}/" in p]
        outs["make_report"] = (0, "DISCLOSED[render] DEVIATIONS.md row R1: LaTeX $x$ outside a code span\nok: 0 problem(s), 1 disclosed\n")
        say("dev mode: disclose is refused (every failure is a stop)",
            "every failure is a stop" in refused(disclose, cfg, cmd="python3 audits/make_report.py --check"))
        outs["make_report"] = (1, "  ! Lemma 1.3: not formalized by the index\nDISCLOSED[render] x\nFAIL: 1 problem(s)\n")
        say("release: disclose refuses a check that still fails (a blocking line is a stop)",
            "never a disclosure" in refused(disclose, cfg_r, cmd="python3 audits/make_report.py --check"))
        outs["make_report"] = (0, "DISCLOSED[drift] thm_1_1 changed\n")
        say("release: disclose refuses a DISCLOSED line with a blocking code",
            "blocking codes (drift)" in refused(disclose, cfg_r, cmd="python3 audits/make_report.py --check"))
        outs["make_report"] = (0, "ok: 0 problem(s)\n")
        say("release: disclose refuses a check that discloses nothing",
            "nothing to disclose" in refused(disclose, cfg_r, cmd="python3 audits/make_report.py --check"))
        outs["make_report"] = (0, "DISCLOSED[render] DEVIATIONS.md row R1: LaTeX $x$ outside a code span\n"
                                  "DISCLOSED[render] DEVIATIONS.md row R1: LaTeX $x$ outside a code span\nok\n")
        d1 = disclose(cfg_r, cmd="python3 audits/make_report.py --check")
        r1 = load(os.path.join(rd, STOPS, DISCLOSED, "D1.json")) or {}
        say("S3-like: disclose records the DISCLOSED lines once each, commits them, logs them; the trail accepts it",
            d1 == "D1" and len(r1.get("faults", [])) == 1 and r1["faults"][0]["code"] == "render"
            and G("log", "-1", "--format=%s") == "stop disclose D1"
            and "D1 (" in open(os.path.join(rd, "RUN_LOG.md")).read() and not dtrail(cfg_r))
        outs["make_report"] = (0, "DISCLOSED[render] DEVIATIONS.md row R1: LaTeX $x$ outside a code span\nok\n")
        d1b = disclose(cfg_r, cmd="python3 audits/make_report.py --check")
        # legacy duplicates (recorded before the dedupe): one name off the page edge, on p.4 then p.5
        dup_ = os.path.join(d, "dup-rd")
        os.makedirs(os.path.join(dup_, STOPS, DISCLOSED))
        for i_, pg_ in ((1, 4), (2, 5), (3, 5)):
            json.dump({"fault": f"D{i_}", "date": "2026-10-21", "command": "python3 audits/signoff.py check --round R",
                       "faults": [{"code": "pdf", "line": f"SIGNOFF.pdf page check: p.{pg_}: text off the right page "
                                                          "edge: `ExamplePaper.lemma_9_1_false`"}]},
                      open(os.path.join(dup_, STOPS, DISCLOSED, f"D{i_}.json"), "w"))
        dr_ = disclosed_rows(cfg_r, rd=dup_)
        shutil.rmtree(dup_)
        say("mini4 audit: the same fault is disclosed once -- disclose makes no new record for a fault an earlier "
            "record holds (it names that one), and earlier duplicates (page numbers moved) are listed once, naming "
            "every record",
            d1b == "D1" and not os.path.exists(os.path.join(rd, STOPS, DISCLOSED, "D2.json"))
            and len(dr_) == 1 and dr_[0]["fault"] == "D1 (also recorded as D2, D3)" and dr_[0]["stop"] == dr_[0]["fault"])
        outs["selftest_all"] = (0, "  disc  prompt.py\nDISCLOSED[selftest] prompt.py selftest: fresh-reader: baseline\n"
                                   "ALL SELFTESTS: ok (1 disclosed)\n")
        say("S1-like: a self-test failure of a non-blocking check is disclosed, not a stop",
            disclose(cfg_r, cmd="python3 audits/selftest_all.py --fast") == "D2")
        say("release: a crash of tests/doclint.py is disclosed as tool-fault; of fingerprint, prompt or readers "
            "(the sheet's faithfulness gate, review H2) it is refused",
            disclose(cfg_r, note="doclint.py: KeyError", cause="tool-fault", script="tests/doclint") == "D3"
            and "may crash without a stop" in refused(disclose, cfg_r, note="x", cause="tool-fault", script="readers")
            and "may crash without a stop" in refused(disclose, cfg_r, note="x", cause="tool-fault", script="fingerprint")
            and "may crash without a stop" in refused(disclose, cfg_r, note="x", cause="tool-fault", script="prompt")
            and "only a crash" in refused(disclose, cfg_r, note="x", cause="render"))
        say("open refuses tool-fault (in any mode), and in release a failure whose causes are all disclosed",
            "tool-fault is recorded with stops.py disclose" in refused(open_stop, cfg_r, note="x", cause="tool-fault")
            and "tool-fault is recorded" in refused(open_stop, cfg, note="x", cause="tool-fault"))
        outs["lanecheck"] = (1, "PROBLEM[label] x\n")
        say("release: open refuses a failure all of whose causes are disclosed", "disclosed in release mode, not a stop" in refused(
            open_stop, cfg_r, cmd="python3 audits/lanecheck.py --round 2026-10-19-full-1a2b3c4"))
        outs["lanecheck"] = (1, "PROBLEM[reader] x\nPROBLEM[stray-loop] pid 7\n")
        # RELEASE-SWEEP S4: a release stop naming a round that is not one of the run is refused at open, before
        # anything is recorded (before: recorded, then "every self-cure of it is the human's now")
        n_before = len(stops(cfg_r))
        s4_ref = refused(open_stop, cfg_r, cmd="python3 audits/lanecheck.py --round 2026-10-19-full-1a2b3c4")
        say("RELEASE-SWEEP S4: a release stop naming a round of no TARGET.json is refused at open (nothing recorded), "
            "never a human stop", "not a round of this run" in s4_ref and "never a human stop" in s4_ref
            and len(stops(cfg_r)) == n_before)
        _t4 = os.path.join(rd, "2026-10-19-full-1a2b3c4", "TARGET.json")
        os.makedirs(os.path.dirname(_t4), exist_ok=True); open(_t4, "w").write("{}")
        s_mix, m_mix = open_stop(cfg_r, cmd="python3 audits/lanecheck.py --round 2026-10-19-full-1a2b3c4")
        say("release: a failure with one blocking cause beside a disclosed one is still a stop", bool(s_mix))
        outs["lanecheck"] = (0, "lane check: OK\n")
        say("release: --delegated is dev mode only (U2 §4)", "dev mode only" in refused(
            close_stop, cfg_r, s_mix, delegated="killed the loop"))
        close_stop(cfg_r, s_mix, human="killed the loop")
        os.remove(_t4); os.rmdir(os.path.dirname(_t4))
        say("release: a stop's check is a FORMS command only: a build command (dev: accepted) is refused at open, "
            "and a record naming one, or a writer, has no cure plan (U2 §4, H1)",
            command_problem("lake build P", cfg) is None and "release mode" in str(command_problem("lake build P", cfg_r))
            and "release mode" in refused(open_stop, cfg_r, cmd="lake build P")
            and "release mode" in refused(open_stop, cfg_r, note="x", cause="tool-call", check="lake build P")
            and cure_plan(cfg_r, {"command": "lake build P", "causes": [{"code": "build"}]}) is None
            and cure_plan(cfg_r, {"command": None, "check": "python3 audits/integrity.py --pin",
                                  "causes": [{"code": "tool-call"}]}) is None
            and cure_plan(cfg_r, {"command": "python3 audits/phase0.py --readonly", "causes": [{"code": "build"}]})
            == ["reprove"])
        say("the report's stop list carries every disclosed fault",
            [r["stop"] for r in disclosed_rows(cfg_r)] == ["D1", "D2", "D3"])
        say("the trail fails a disclosure in a dev-mode run",
            any("whose mode is 'dev'" in p for p in dtrail(cfg)) and not dtrail(cfg_r))
        json.dump({"fault": "D4", "mode": "release", "faults": [{"code": "axiom", "line": "x"}]},
                  open(os.path.join(rd, STOPS, DISCLOSED, "D4.json"), "w"))
        G("add", "-A"); G("commit", "-qm", "stop disclose D4")
        say("the trail fails a disclosure of a blocking cause (written by hand)",
            any("D4.json discloses blocking causes (axiom)" in p for p in dtrail(cfg_r)))
        outs["phase0"] = (0, "$ python3 audits/x.py\nMISSING: something a step reports\n  error: quoted\n"
                             "DISCLOSED[docstring] A.lean:3  a placeholder\nPHASE 0: GREEN\n")
        say("release: disclose records a GREEN gate whose steps' output has FAIL-like tokens (exit code decides, "
            "review L4)", disclose(cfg_r, cmd="python3 audits/phase0.py --readonly") == "D5")
        # review H3: the delivery gate (release): every live DISCLOSED line has a D record, and REPORT.md
        # and DECISIONS.md name every D record
        global PHASE0_LINES
        PHASE0_LINES = lambda c_: [("docstring", "A.lean:3  a placeholder")]
        names = lambda ids: [open(os.path.join(rd, f_), "w").write(" ".join(ids) + "\n" + "".join(
            f"| {i} [tamper]: x -- the operator (release self-cure, attempt 1 of 2) |\nself-cured stop {i} (tamper)\n"
            for i in ids if i.startswith("S")) + "".join(       # every other closed stop: its row, its box entry
            f"| {r_['stop']} | x |\n> - stop {r_['stop']} (x\n" for r_ in stop_rows(cfg_r)
            if not r_["cured"] and r_["by"] != "nobody yet")) for f_ in ("REPORT.md", "DECISIONS.md")] + [
            # approver 2026-10-24: the process record names every stop, the operator's closes, the disclosed faults
            # and the set-asides (run_record.listing_problems, integrity.run_record_problems)
            open(os.path.join(rd, "RUN_RECORD.md"), "w").write(
                "## 1. Tool patches\n\nNone.\n\n## 2. Every stop of the run\n\n"
                + "".join(f"| {r_['stop']} | x |\n" for r_ in stop_rows(cfg_r, phase="run") if r_["stop"] in ids
                          or not r_["cured"])
                + "\n## 3. Stops cleared without you\n\n"
                + "".join(f"| {r_['stop']} | x |\n" for r_ in stop_rows(cfg_r, phase="run")
                          if r_["by"].startswith("the operator") and (r_["stop"] in ids or not r_["cured"]))
                + "\n## 4. Set-asides and clearances\n\n" + "".join(f"| {r_['scope']} | x |\n" for r_ in set_aside_rows(cfg_r))
                + "\n## 6. Faults disclosed instead of a stop\n\n" + "".join(f"- {i}\n" for i in ids if i.startswith("D")))]
        names(["D1", "D2", "D3", "D4", "D5"])
        stale = lambda n, h: (0, f"DISCLOSED[reader] the document changed after its last well-formed pass "
                                 f"(report-2026-10-2{n}-abc1234_{n}.md read {h}…, the source is now 0f0f0f0f0f0f…)\n")
        outs["readers"], outs["decisions"] = stale(1, "0123456789ab"), (0, "ok\n")
        outs["integrity"] = (0, "integrity: OK\n")
        g1, n1 = math_gate(cfg_r)
        PHASE0_LINES = lambda c_: [("docstring", "A.lean:3  a placeholder"), ("docstring", "B.lean:9  NEWQZ")]
        g1b, n1b = math_gate(cfg_r)
        PHASE0_LINES = lambda c_: [("docstring", "A.lean:3  a placeholder")]
        say("H3 (approver 2026-10-28): the delivery gate's disclosure bookkeeping is notes only: a recorded disclosure "
            "is no note, a live one with no D record is a note, never a refusal; dev has none; no disclosing check "
            "(readers, decisions, make_report, selftests) is run by the gate",
            g1 == [] and not any("no D record" in x for x in n1) and g1b == []
            and any("NEWQZ" in x and "no D record" in x for x in n1b)
            and not any("DISCLOSED" in x for x in math_gate(cfg)[1]) and deliver_gate(cfg) == [])
        dr = disclose(cfg_r, cmd="python3 audits/readers.py --doc report --check")
        outs["readers"] = stale(2, "ba9876543210")
        g2 = deliver_gate(cfg_r)
        say("H3 / B10: a stale pass whose hashes and pass number moved keeps its record; REPORT.md and DECISIONS.md "
            "need not name a reader disclosure (README D lists it: a reader pass never makes a document stale, U2 "
            "§6.6)", dr == "D6" and g2 == [] and "D6" not in unnamed(cfg_r).get("REPORT.md", [])
            and "D6" in [r_["fault"] for r_ in disclosed_rows(cfg_r, phase="delivery")]
            and "D6" not in [r_["fault"] for r_ in disclosed_rows(cfg_r, phase="run")])
        names(["D1", "D2", "D3", "D4", "D5", "D6"])
        g3 = deliver_gate(cfg_r)
        outs["decisions"] = (1, "FAIL: x\n")
        g4 = deliver_gate(cfg_r)
        outs["decisions"] = (0, "ok\n")
        say("H3 (approver 2026-10-28): the gate passes once every disclosure is recorded and named; a failing "
            "decisions.py --check (a document check) is not the gate's",
            g3 == [] and g4 == [])
        PHASE0_LINES = None
        # release self-cure (approver, 2026-10-21): only the four human stops stop a release run
        R_ = "2026-10-19-full-1a2b3c4"
        os.makedirs(os.path.join(rd, R_)); open(os.path.join(rd, R_, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {R_}")
        strail = lambda c_, s_: [p for p in trail_problems(c_, d, rd) if re.search(rf"\b{s_}\b", p)]
        outs["integrity"] = (1, "FAIL[seal-mismatch] a verdict differs from its seal\n")
        sc, mc = open_stop(cfg_r, cmd="python3 audits/integrity.py --check", round_name=R_)
        say("release-cure: a tamper stop (I) is the operator's self-cure, with the fixed cure printed",
            "self-cure" in mc and "set-aside" in mc and "--cured" in mc and "--human" not in mc
            and _cure_stop(cfg_r, sc, R_) and not _cure_stop(cfg, sc, R_))
        r1 = refused(close_stop, cfg_r, sc, cured="restored the verdict, set the round aside")
        outs["integrity"] = (0, "integrity: OK\n")
        close_stop(cfg_r, sc, cured="set the round aside; fresh round re-ran the review")
        row = next(r for r in stop_rows(cfg_r) if r["stop"] == sc)
        log_ = open(os.path.join(rd, "RUN_LOG.md")).read()
        say("release-cure: a failing attempt is recorded (CURE1) and counted; a passing one closes, disclosed",
            "attempt 1 of 2" in r1 and cure_attempts(cfg_r, sc) == ["CURE1.json"] and row["cured"]
            and "release self-cure, attempt 2 of 2" in row["by"] and "compromised" in row["by"]
            and f"stop {sc} self-cured" in log_ and not strail(cfg_r, sc))
        say("release-cure: a self-cure in a dev run is a trail fault",
            any("self-cured in a run whose mode is 'dev'" in p for p in strail(cfg, sc)))
        g5 = math_gate(cfg_r)[1]
        say("release-cure (approver 2026-10-24): RUN_RECORD.md must name each self-cured stop, in its stop list and "
            "under \"Stops cleared without you\" (REPORT.md and DECISIONS.md need not: the process record)",
            any(x.startswith("RUN_RECORD.md does not name") and re.search(rf"stop {sc} under", x)
                and "closed by the operator" in x for x in g5)
            and not any(x.startswith(("REPORT.md", "DECISIONS.md")) for x in g5))
        _rrk = open(os.path.join(rd, "RUN_RECORD.md")).read()
        open(os.path.join(rd, "RUN_RECORD.md"), "w").write(_rrk + f"\nStop {sc} mentioned in passing; | {sc} | inline\n")
        say("release-cure: a mention of a self-cured stop in passing is not its row in RUN_RECORD.md (review L2)",
            any(x.startswith("RUN_RECORD.md does not name") and re.search(rf"\b{sc}\b", x) for x in math_gate(cfg_r)[1]))
        names(["D1", "D2", "D3", "D4", "D5", "D6", sc])
        cp_ = os.path.join(rd, STOPS, sc, "CLOSED.json")
        c_ = load(cp_)
        json.dump(dict(c_, rerun=dict(c_["rerun"], passes=False)), open(cp_, "w"))
        bad_ = strail(cfg_r, sc)
        G("checkout", "--", os.path.relpath(cp_, d))
        say("release-cure: the trail refuses a self-cure record whose check did not pass",
            any("does not show its check passing" in p for p in bad_) and not strail(cfg_r, sc))
        outs["integrity"] = (1, "FAIL[seal-mismatch] a verdict differs from its seal\n")
        sd_, md_ = open_stop(cfg, cmd="python3 audits/integrity.py --check", round_name=R_)
        say("release-cure: dev is unchanged (a STOP class waits for the human; --cured refused)",
            "--human" in md_ and "release mode only" in refused(close_stop, cfg, sd_, cured="x"))
        close_stop(cfg, sd_, human="set it aside")
        outs["integrity"] = (1, "Traceback (most recent call last):\n  File audits/integrity.py\nKeyError: x\n")
        su, mu = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
        outs["integrity"] = (0, "integrity: OK\n")
        close_stop(cfg_r, su, cured="re-ran the check after the retry")
        ru_ = next(r for r in stop_rows(cfg_r) if r["stop"] == su)
        say("release-cure: a rerun self-cure says what was done, never that independence was compromised "
            "(trial #7 audit: a restored sign-off text was described as a compromised review)",
            ru_["cured"] and "compromised" not in ru_["by"] and "mechanical fault was fixed" in ru_["by"])
        nwb = "make_report.py crashed twice (traceback in audits/)"
        nb0 = refused(open_stop, cfg_r, note=nwb, cause="unknown-retry")   # (tool-bug without --check: MED-2 below)
        outs["make_report"] = (0, "ok\n")
        nb1 = refused(open_stop, cfg_r, note=nwb, cause="tool-bug", check="python3 audits/integrity.py --check")
        outs["make_report"] = (1, "Traceback (most recent call last):\n  File audits/make_report.py\nKeyError: x\n")
        sb, mb = open_stop(cfg_r, note=nwb, cause="tool-bug", check="python3 audits/make_report.py --check")
        nb = refused(close_stop, cfg_r, sb, cured="re-ran it", check="python3 audits/integrity.py --check")
        outs["make_report"] = (0, "ok\n")
        close_stop(cfg_r, sb, cured="re-ran the review in a fresh round")
        say("release-cure: an unknown failure and a tool-bug are self-cured; a --note stop records its failing "
            "check at open and the cure re-runs exactly that, never a substitute (review H1)",
            "self-cure" in mu and "self-cure" in mb and "open it with --check" in nb0 and "exits 0 now" in nb1
            and "close takes no --check" in nb
            and load(os.path.join(rd, STOPS, sb, "CLOSED.json"))["check"] == "python3 audits/make_report.py --check"
            and all(next(r for r in stop_rows(cfg_r) if r["stop"] == x)["cured"] for x in (su, sb))
            and not strail(cfg_r, su) and not strail(cfg_r, sb))
        sg, mg = open_stop(cfg_r, note="Theorem 1 looks false as stated", cause="unproved-goal")
        say("release-cure: a goal result (H) stays a human stop", "--human" in mg
            and "human stop in release" in refused(close_stop, cfg_r, sg, cured="x"))
        close_stop(cfg_r, sg, human="drop it")
        # review H2: the human stops no script detects have H codes; an unknown --note cause fails closed
        h2 = []
        outs["make_report"] = (1, "Traceback (most recent call last):\n  File audits/make_report.py\nKeyError: x\n")
        for cz in ("outward-action", "codex-approval"):
            sq, mq = open_stop(cfg_r, note=f"would push to the authors' repo ({cz})", cause=cz,
                               check="python3 audits/make_report.py --check")
            h2.append("a self-cure, not" not in mq and "human stop in release" in refused(close_stop, cfg_r, sq, cured="x")
                      and "--cured" not in mq)
            close_stop(cfg_r, sq, human="x")
        for cz in ("push-needed", "goal-false"):
            h2.append("not a cause code" in refused(open_stop, cfg_r, note="x", cause=cz,
                                                    check="python3 audits/make_report.py --check"))
        sq, mq = open_stop(cfg, note="push to the authors' repo", cause="outward-action")
        h2.append("--human" in mq)
        close_stop(cfg, sq, human="x")
        sq, mq = open_stop(cfg_r, note="phase0.py: unexpected git message", cause="unknown-retry",
                           check="python3 audits/make_report.py --check")
        h2.append("needs --check" not in mq and "self-cure" in mq and "dev mode only" in refused(
            close_stop, cfg_r, sq, delegated="re-ran it"))
        outs["make_report"] = (0, "ok\n")
        close_stop(cfg_r, sq, cured="re-ran it within the retry budget; it passes")
        h2.append(load(os.path.join(rd, STOPS, sq, "CLOSED.json"))["by"] == "cure"
                  and "open it with --check" in refused(open_stop, cfg_r, note="x", cause="unknown-retry")
                  and "open it with --check" in refused(open_stop, cfg_r, note="x", cause="tool-call"))
        say("release-cure: an outward action and a Codex approval prompt are never self-cured; outward-action is a "
            "human stop in dev too (review H2); a --note cause that is no cause code is refused in release; "
            "unknown-retry and tool-call need --check and close --cured (U2 §4: the uncoded route)",
            all(h2) and len(h2) == 7)
        se_, me_ = open_stop(cfg_r, note="lake: permission denied on the cache", cause="env-unknown")
        say("release-cure: an environment fault (H) is never self-cured",
            "self-cure" not in me_ and "human stop in release" in refused(close_stop, cfg_r, se_, cured="x"))
        close_stop(cfg_r, se_, human="fixed the permissions")
        # approver 2026-10-24, stop 4: a genuine ambiguity of the paper's meaning is a human stop at EVERY level,
        # hands-off included; the human's answer is recorded verbatim and the run resumes at its own level (the next
        # fault of the hands-off run is again the operator's self-cure, never a question)
        amb, amb_ans = [], "Read 'for all n' as n >= 1, as in Section 2."
        for lv_ in project.INVOLVEMENT_LEVELS:
            cl_ = dict(cfg_r, involvement=lv_)
            sa_, ma_ = open_stop(cl_, note="Lemma 1.2: 'for all n' -- n >= 0 or n >= 1? (readings; what each means)",
                                 cause="ambiguity")
            amb.append("stop 4" in ma_ and "--human" in ma_ and "a self-cure, not" not in ma_
                       and "human stop in release" in refused(close_stop, cl_, sa_, cured="picked one")
                       and "dev mode only" in refused(close_stop, cl_, sa_, delegated="picked one"))
            close_stop(cl_, sa_, human=amb_ans)
            ra_ = next(r for r in stop_rows(cl_) if r["stop"] == sa_)
            amb.append(ra_["human"] and ra_["answer"] == amb_ans and project.involvement(cl_) == lv_
                       and not strail(cl_, sa_))
        outs["make_report"] = (1, "Traceback (most recent call last):\n  File audits/make_report.py\nKeyError: x\n")
        sr_, mr_ = open_stop(cfg_r, note="phase0.py: unexpected git message", cause="unknown-retry",
                             check="python3 audits/make_report.py --check")
        outs["make_report"] = (0, "ok\n")
        close_stop(cfg_r, sr_, cured="re-ran it; it passes")
        amb.append(cfg_r["involvement"] == "hands-off" and "self-cure" in mr_ and "--human" not in mr_
                   and load(os.path.join(rd, STOPS, sr_, "CLOSED.json"))["by"] == "cure")
        sd4, md4 = open_stop(cfg, note="Lemma 1.2: two readings", cause="ambiguity")
        amb.append("--human" in md4 and "--delegated" not in md4.split("record it with")[0])
        close_stop(cfg, sd4, human=amb_ans)
        say("approver 2026-10-24, stop 4 (ambiguity): a human stop under involved, statements-only and hands-off "
            "alike (never --cured, never --delegated); the answer is recorded verbatim; the level is unchanged and "
            "the hands-off run resumes as before (its next fault is the operator's self-cure); dev: a stop too",
            all(amb) and len(amb) == 8)
        outs["fingerprint"] = (1, "DRIFT[drift] Thm 1 changed\n")
        sx, _ = open_stop(cfg_r, cmd="python3 audits/fingerprint.py --check")
        e1 = refused(close_stop, cfg_r, sx, cured="restored the statement")
        e2 = refused(close_stop, cfg_r, sx, cured="restored it again")
        e3 = refused(close_stop, cfg_r, sx, cured="third try")
        say("release-cure: a cure failing past its budget (2) spends it (no further --cured until it is classified)",
            "attempt 2 of 2" in e2 and "budget is spent" in e2 and "per-stop cap (2)" in e3
            and len(cure_attempts(cfg_r, sx)) == 2 and not strail(cfg_r, sx))
        close_stop(cfg_r, sx, human="re-approve the changed statement")
        # review H1: the budget is per failure (script, code) across stops: KEY_BUDGET (3) failed cures in the run
        sy, my = open_stop(cfg_r, cmd="python3 audits/fingerprint.py --check")
        ey = refused(close_stop, cfg_r, sy, cured="restored it")
        close_stop(cfg_r, sy, human="x")
        sw, mw = open_stop(cfg_r, cmd="python3 audits/fingerprint.py --check")
        cw_ = [refused(classify, cfg, sw, "interference", "x"), refused(classify, cfg_r, sw, "stop", "x"),
               refused(classify, cfg_r, sw, "interference", " ")]
        _rw, ww_ = classify(cfg_r, sw, "interference", "tree-changed recurs every few minutes: a sync client")
        cw_ += [ww_, refused(close_stop, cfg_r, sw, cured="re-ran it"), refused(classify, cfg_r, sw, "other", "y")]
        close_stop(cfg_r, sw, human="x")
        sz, mz = open_stop(cfg_r, note="fingerprint.py crashed", cause="tool-bug", check="python3 -B audits/fingerprint.py --check")
        _rz, wz_ = classify(cfg_r, sz, "tool-bug", "fingerprint.py raises KeyError on this input")
        cz_ = refused(close_stop, cfg_r, sz, cured="re-ran it")
        close_stop(cfg_r, sz, human="x")
        say("approver 2026-10-24: a spent cure budget is never 'stop 4' -- the operator classifies it (release only, "
            "with evidence, once per failure count): outside interference is stop 3, the human's (--cured refused); "
            "a tool bug (also a tool-bug fault's own spent budget) never routes to a human stop: the tool-patch route "
            "(tool_patch.py), a plain --cured refused",
            "release mode only" in cw_[0] and "--as is one of" in cw_[1] and "--evidence is required" in cw_[2]
            and "stop 3" in cw_[3] and "--human" in cw_[3] and "stop 3" in cw_[4] and "already classified" in cw_[5]
            and "not a human stop" in mz and "--human" not in mz.split("interference")[0]
            and "tool_patch.py begin" in wz_ and "--human" not in wz_ and "tool-patch TP<k>" in cz_
            and "classified as a tool bug" in cz_ and "stop 4" not in mz + wz_ + cz_)
        say("release-cure: a new stop id, or a --note stop under another code, of a failure whose run-wide budget "
            "(3 failed cures) is spent is no self-cure: classify it (review H1, re-check H1)", "a self-cure, not" in my
            and "budget is spent" in ey and "budget is spent" in mw and SPENT in mw and "retry budget (3)" in mw
            and "counted across stops" in mw and "budget is spent" in mz and "a self-cure, not" not in mz)
        res += _selftest_core_fault(cfg, cfg_r, d, rd, outs, refused, strail)
        # B1b (U2 §4): passes are not counted; a recurring fault is counted by its openings in a round once it has
        # had a failed cure there (review compat MED (b): recurrence cured at the first try is never spends the budget)
        crash = (1, "Traceback (most recent call last):\n  File audits/integrity.py\nKeyError: x\n")
        flap, flap2 = [], []
        for i in range(project.OPEN_CEILING + 3):
            outs["integrity"] = crash
            sf, mf = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
            flap.append(mf)
            outs["integrity"] = (0, "integrity: OK\n")
            close_stop(cfg_r, sf, cured="re-ran it") if "a self-cure, not" in mf else close_stop(cfg_r, sf, human="x")
        for i in range(project.OPEN_CEILING + 2):
            outs["integrity"] = crash
            sf, mf = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
            flap2.append(mf)
            if "a self-cure, not" not in mf:
                close_stop(cfg_r, sf, human="x")
                break
            if i == 0:
                refused(close_stop, cfg_r, sf, cured="re-ran it too soon")
            outs["integrity"] = (0, "integrity: OK\n")
            close_stop(cfg_r, sf, cured="re-ran it")
        Rf = "2026-10-21-full-0f1e2d3"
        os.makedirs(os.path.join(rd, Rf)); open(os.path.join(rd, Rf, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {Rf}")
        outs["integrity"] = crash
        sf, mf_s = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
        outs["integrity"] = (0, "integrity: OK\n")
        close_stop(cfg_r, sf, cured="re-ran it") if "a self-cure, not" in mf_s else close_stop(cfg_r, sf, human="x")
        open(os.path.join(rd, Rf, "correspondence.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"lanes {Rf}")
        outs["integrity"] = crash
        sf, mf = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
        outs["integrity"] = (0, "integrity: OK\n")
        close_stop(cfg_r, sf, cured="re-ran it")
        say("B1b: a flapping check cured each time at the first try is never spends the budget however often it recurs (passes "
            "not counted; compat MED (b)); once it has a failed cure in a round, the 4th opening after it there is "
            "the budget is spent; a round only scoped is no new bucket (compat LOW), one with a verdict file counts afresh",
            all("a self-cure, not" in m for m in flap) and all("a self-cure, not" in m for m in flap2[:-1])
            and len(flap2) == project.OPEN_CEILING + 2 and SPENT in flap2[-1] and "per round" in flap2[-1]
            and SPENT in mf_s and "a self-cure, not" in mf and not strail(cfg_r, sf))
        G("rm", "-q", "--", os.path.join("P", STOPS, sx, "CURE1.json"), os.path.join("P", STOPS, sx, "CURE2.json"))
        G("commit", "-qm", f"stop {sx} open")
        outs["fingerprint"] = (1, "DRIFT[drift] Thm 1 changed\n")
        sw, mw = open_stop(cfg_r, cmd="python3 audits/fingerprint.py --check")
        say("release-cure: deleting the CURE files does not reset the count (review H1, L1)",
            "budget is spent" in mw and "counted across stops" in refused(close_stop, cfg_r, sw, cured="x"))
        close_stop(cfg_r, sw, human="x")
        cp_ = os.path.join(rd, STOPS, sw, "CURE1.json")
        json.dump({"by": "cure", "rerun": {"passes": False}}, open(cp_, "w"))
        G("add", "--", cp_); G("commit", "-qm", f"stop {sw} cure 1")
        say("release-cure: the trail flags a self-cure attempt past the budget of its failure, across stops (review H1)",
            any("the budget is 2" in p for p in strail(cfg_r, sw)))
        # re-check R1: the stop's --round is not part of the budget key; a made-up or inconsistent round is the human's
        outs["fingerprint"] = (1, "DRIFT[drift] Thm 1 changed\n")
        r1 = []
        for rn in (R, R2):
            sr1, mr1 = open_stop(cfg_r, cmd="python3 audits/fingerprint.py --check", round_name=rn)
            r1.append("budget is spent" in mr1 and "retry budget" in mr1 and "a self-cure, not" not in mr1)
            close_stop(cfg_r, sr1, human="x")
        n_r1 = len(stops(cfg_r))
        for rn in ("2026-10-21-full-abcdef1", "2026-10-22-full-abcdef2"):
            outs["integrity"] = (1, "FAIL[seal-mismatch] x\n")
            # RELEASE-SWEEP S4: refused at open, nothing recorded (before: recorded as a human stop)
            mr1 = refused(open_stop, cfg_r, cmd="python3 audits/integrity.py --check", round_name=rn)
            r1.append("not a round of this run" in mr1 and "never a human stop" in mr1 and len(stops(cfg_r)) == n_r1)
        outs["lanecheck"] = (1, "FAIL[seal-mismatch] x\n")
        mr1 = refused(open_stop, cfg_r, cmd=f"python3 audits/lanecheck.py --round {R2}", round_name=R)
        r1.append("give --round the round its check names" in mr1 and len(stops(cfg_r)) == n_r1)
        outs["lanecheck"], outs["integrity"] = (0, "lane check: OK\n"), (0, "integrity: OK\n")
        e0 = os.path.join(base, "empty-run"); os.makedirs(e0)
        subprocess.run(["git", "init", "-q", e0], check=True)
        r1.append("not a round of this run" in refused(cures_spent, cfg_r, {
            "stop": "S1", "round": "2026-10-21-full-abcdef1", "command": "python3 audits/fingerprint.py --check",
            "causes": [{"code": "drift"}]}, e0, e0))
        say("release-cure: a stop's --round (real or made up) does not reset its failure's budget; a made-up round, "
            "or one its command contradicts, is refused at open, never recorded and never a human stop (re-check R1; "
            "RELEASE-SWEEP S4)", r1 == [True] * 6)
        # review M4: delivery re-runs integrity, Phase 0 and each self-cured stop's check on the state delivered
        outs["tree_state"] = (1, "FAIL[tree-changed] x\n")
        st_, _ = open_stop(cfg_r, cmd="python3 audits/tree_state.py --check")
        outs["tree_state"] = (0, "ok\n")
        close_stop(cfg_r, st_, cured="restored the tree")
        outs["tree_state"], outs["integrity"], outs["phase0"] = (1, "FAIL[tree-changed] y\n"), (1, "FAIL[seal-mismatch] y\n"), (1, "RED\n")
        g_m4, n_m4 = math_gate(cfg_r)
        outs["tree_state"], outs["integrity"], outs["phase0"] = (0, "ok\n"), (0, "ok\n"), (0, "PHASE 0: GREEN\n")
        say("release-cure: delivery refuses when integrity (a verdict's seal) or Phase 0 fails on the state delivered; a "
            "self-cured stop's own check that fails is re-run and noted (review M4; approver 2026-10-28)",
            all(any(f"`python3 audits/{x}` fails" in g for g in g_m4) for x in ("integrity.py --check", "phase0.py --readonly"))
            and any("tree_state.py --check` fails" in n for n in n_m4) and not any("tree_state" in g for g in g_m4)
            and not any("fails" in g for g in sum(math_gate(cfg_r), [])))
        # re-check M4: a self-cure whose check names a round since superseded or set aside is verified from its
        # recorded pass, not re-run on the delivered state (it would stall a correct release run)
        R5, R6 = "2026-10-22-full-5e6f7a8", "2026-10-23-full-6f7a8b9"
        os.makedirs(os.path.join(rd, R5)); open(os.path.join(rd, R5, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {R5}")
        outs["lanecheck"] = (1, "FAIL[seal-mismatch] x\n")
        s5_, _ = open_stop(cfg_r, cmd=f"python3 audits/lanecheck.py --round {R5}", round_name=R5)
        outs["lanecheck"] = (0, "lane check: OK\n")
        close_stop(cfg_r, s5_, cured="re-sealed the lane")
        outs["lanecheck"] = (1, "PROBLEM[stray-loop] pid 9\n")
        g_cur = math_gate(cfg_r)[1]          # R5 is still the current round: its check is re-run, and fails
        os.makedirs(os.path.join(rd, R6)); open(os.path.join(rd, R6, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {R6}")
        g_old = math_gate(cfg_r)[1]
        cp5 = os.path.join(rd, STOPS, s5_, "CLOSED.json")
        c5_ = load(cp5); json.dump(dict(c5_, text="edited"), open(cp5, "w"), indent=1, sort_keys=True)
        g_ed = math_gate(cfg_r)[1]
        json.dump(c5_, open(cp5, "w"), indent=1, sort_keys=True)
        outs["lanecheck"] = (0, "lane check: OK\n")
        say("release-cure: delivery verifies a self-cure whose check names a superseded round from its committed "
            "passing record instead of re-running it, so a correct release run delivers; an edited record "
            "refuses; a current round's check is re-run (re-check M4)",
            any(f"lanecheck.py --round {R5}` fails" in g for g in g_cur) and not any("lanecheck" in g for g in g_old)
            and any(g.startswith(f"the check of self-cured stop {s5_}") and "recorded pass does not hold" in g
                    and "differs" in g for g in g_ed)
            and not any("lanecheck" in g for g in math_gate(cfg_r)[1]))
        # review M1: a self-cure's set-aside carries the SEALED Fail of a verdict tampered after its seal
        R3 = "2026-10-20-full-3c4d5e6"
        r = os.path.join(rd, R3)
        os.makedirs(os.path.join(r, "prompts"))
        open(os.path.join(r, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"scope {R3}")
        v3 = lane("correspondence", [("T.1", "Fail")])
        t3 = json.load(open(v3)); t3["verdicts"][0]["verdict"] = "Pass"; json.dump(t3, open(v3, "w"))
        G("add", "-A"); G("commit", "-qm", f"implement {R3}")
        outs["integrity"] = (1, "FAIL[seal-mismatch] a verdict differs from its seal\n")
        sm, _ = open_stop(cfg_r, cmd=f"python3 audits/integrity.py --check --round {R3}", round_name=R3)
        doc3, _h = set_aside(cfg_r, R3, "release self-cure of " + sm, stop=sm)
        say("release-cure: a self-cure's set-aside carries the sealed Fail, not the verdict tampered after its seal "
            "(review M1)", ("T.1", "Fail") in [(c["item"], c["verdict"]) for c in doc3["carried"]])
        row3 = next(x for x in set_aside_rows(cfg_r) if x["scope"] == R3)
        log3 = [l for l in open(os.path.join(rd, "RUN_LOG.md")).read().splitlines() if R3 in l and "set aside" in l]
        outs["integrity"] = (0, "ok\n")
        # review M3: the revert cure of a committed ownership fault can pass (a verified revert)
        R4 = "2026-10-20-full-4d5e6f7"
        r = os.path.join(rd, R4)
        os.makedirs(os.path.join(r, "prompts"))
        rt4 = redo_target(cfg_r)          # what scope.py records as R4's redo_of (U2 §4 "Closing a redo")
        open(os.path.join(r, "TARGET.json"), "w").write(json.dumps({"_meta": {"redo_of": rt4}}))
        G("add", "-A"); G("commit", "-qm", f"scope {R4}")
        # (R4 is the fresh round that redoes R3: sm's check is re-run on it, addendum N5)
        say("B1b: scope.py's redo_of is the round the open stop set aside", rt4 == R3)
        close_stop(cfg_r, sm, cured="set the round aside; a fresh round re-runs its review")
        sc4 = G("rev-parse", "HEAD")
        v4 = lane("correspondence", [("T.2", "Fail")])
        G("add", "-A"); G("commit", "-qm", f"prompts {R4}")
        t4 = json.load(open(v4)); t4["verdicts"][0]["verdict"] = "Pass"; json.dump(t4, open(v4, "w"))
        G("add", "-A"); G("commit", "-qm", f"implement {R4}")
        c4 = G("rev-parse", "HEAD")
        own4 = lambda: [m for sv, m in integrity.check(d, cfg_r, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
                        if sv == "FAIL" and (R4 in m or "revert" in m)]
        before4 = own4()
        outs["integrity"] = (1, "\n".join("FAIL" + m for m in before4) + "\n")
        sr, mr = open_stop(cfg_r, cmd=f"python3 audits/integrity.py --check --round {R4}", round_name=R4)
        bad4 = refused(revert, cfg_r, sr, sc4)
        revert(cfg_r, sr, c4)
        after4 = own4()
        dev4 = [m for sv, m in integrity.check(d, cfg, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
                if sv == "FAIL" and R4 in m]
        say("release-cure: stops.py revert restores the records of the commit its stop's FAIL names, and integrity "
            "accepts the verified revert (review M3); dev does not",
            any("[ownership]" in m and c4[:11] in m for m in before4) and "did not record an integrity FAIL" in bad4
            and after4 == [] and lane_status(v4) == "sealed" and len(dev4) >= 2 and "revert" in mr)
        outs["integrity"] = (0, "ok\n")
        close_stop(cfg_r, sr, cured="reverted the tamper commit")
        rel4 = os.path.relpath(v4, d)
        t4 = json.load(open(v4)); t4["verdicts"][0]["verdict"] = "Pass"; json.dump(t4, open(v4, "w"))
        G("add", "-A"); G("commit", "-qm", f"implement {R4}")
        c5 = G("rev-parse", "HEAD")
        G("checkout", c5 + "^", "--", rel4); open(v4, "a").write(" ")
        G("add", "-A"); G("commit", "-qm", f"revert {c5} (stop {sr})")
        f1 = own4()
        G("reset", "-q", "--hard", "HEAD~1")
        G("checkout", c5 + "^", "--", rel4)
        G("add", "-A"); G("commit", "-qm", 'Revert "implement"')
        f2 = own4()
        n2 = [m for sv, m in integrity.check(d, cfg_r, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
              if sv == "note" and "[reverted]" in m and c5[:11] in m]
        G("reset", "-q", "--hard", "HEAD~1")
        G("checkout", c5 + "^", "--", rel4); open(v4, "a").write("  ")
        G("add", "-A"); G("commit", "-qm", 'Revert "implement"')
        f3 = own4()
        G("reset", "-q", "--hard", "HEAD~1")
        open(v4, "a").write("\n"); open(os.path.join(rd, R4, "TARGET.json"), "a").write("\n")
        G("add", "-A"); G("commit", "-qm", f"implement {R4}")
        c7 = G("rev-parse", "HEAD")
        G("checkout", c7 + "^", "--", rel4)
        G("add", "-A"); G("commit", "-qm", 'Revert "implement"')      # a partial revert: TARGET.json left
        f4 = own4()
        G("reset", "-q", "--hard", "HEAD~3")
        say("release-cure: a revert is judged by content, never by subject (B1c): a commit named as a revert that "
            "does not restore the content (stops.py's or git's subject) is no revert; the exact inverse is one whatever its "
            "subject (git revert's \"Revert ...\"); a partial inverse of a two-file foreign change is none",
            any("not the exact inverse" in m for m in f1) and any("not the exact inverse" in m for m in f3)
            and f2 == [] and n2 and any("not the exact inverse" in m for m in f4) and own4() == [])
        # review H1: a revert that also undoes records the foreign commit owned (a superset of its misowned files)
        # is no verified revert either: the record files a revert touches are exactly the misowned ones
        open(v4, "a").write("\n"); ad4 = os.path.join(rd, R4, "ADOPTED.md")
        open(ad4, "a").write("adopted\n")
        G("add", "-A"); G("commit", "-qm", f"adjudicate {R4}")
        c8 = G("rev-parse", "HEAD")
        G("revert", "--no-edit", c8)                                   # git's revert: v4 AND ADOPTED.md
        f5 = own4()
        G("reset", "-q", "--hard", "HEAD~2")
        say("release-cure (review H1): a revert restoring a superset of the foreign commit's misowned record files "
            "(also one it owned) is not a verified revert",
            any("not the exact inverse" in m for m in f5) and own4() == [])
        # re-check R2: a verified revert excuses only the files it restored; the rest of the commit is still checked
        h_r2 = G("rev-parse", "HEAD")
        rd4 = lambda: [m for sv, m in integrity.check(d, cfg_r, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
                       if sv == "FAIL" and (f"seal {R3}" in m or "revert" in m)]
        G("commit", "-q", "--allow-empty", "-m", f"seal {R3} correspondence.json")
        c_ok = G("rev-parse", "HEAD")      # a reviewer's commit: nothing misowned, so nothing to revert
        t3 = json.load(open(v3)); t3["verdicts"][0]["note"] = "flipped"; json.dump(t3, open(v3, "w"))
        open(os.path.join(rd, R4, "TARGET.json"), "w").write('{"x": 2}')
        G("add", "-A"); G("commit", "-qm", f"seal {R3} correspondence.json")
        c6 = G("rev-parse", "HEAD")
        before6 = rd4()
        outs["integrity"] = (1, "\n".join("FAIL" + m for m in before6) + f"\nFAIL[ownership] {c_ok[:11]}\n")
        s6, _ = open_stop(cfg_r, cmd=f"python3 audits/integrity.py --check --round {R4}", round_name=R4)
        bad6 = refused(revert, cfg_r, s6, c_ok)
        revert(cfg_r, s6, c6)
        after6 = rd4()
        notes6 = [m for sv, m in integrity.check(d, cfg_r, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
                  if sv == "note" and "[reverted]" in m and c6[:11] in m]
        log6 = next((l for l in open(os.path.join(rd, "RUN_LOG.md")).read().splitlines() if f"of {c6[:11]}" in l), "")
        r2_ok = (any("[set-aside-changed]" in m and R3 in m for m in before6)
                 and any("[ownership]" in m and f"{R4}/TARGET.json" in m for m in before6)
                 and "changed no record file it does not own" in bad6
                 and any("[set-aside-changed]" in m and f"seal {R3}" in m for m in after6)
                 and not any(f"{R4}/TARGET.json" in m for m in after6)
                 and notes6 and all(f"{R4}/TARGET.json" in m for m in notes6)
                 and f"{R4}/TARGET.json" in log6 and "correspondence.json" in log6 and "not restored" in log6)
        outs["integrity"] = (1, "\n".join("FAIL" + m for m in after6) + "\n")
        e6 = refused(close_stop, cfg_r, s6, cured="reverted the misowned commit")
        close_stop(cfg_r, s6, human="x")
        G("reset", "-q", "--hard", h_r2)
        say("release-cure: a verified revert excuses only the files it restored: the set-aside lane the same commit "
            "changed is still a FAIL, the revert is logged with what it restored, and a reviewer's commit cannot be "
            "reverted (re-check R2)", r2_ok and "still fails" in e6 and rd4() == [])
        say("release-cure: a self-cure's set-aside is reported and logged as the operator's, not the human's (review M2)",
            row3["by"] == f"the operator (release self-cure of stop {sm})" and doc3.get("stop_by") == "cure"
            and log3 and "by the operator: release self-cure of stop " + sm in log3[-1] and "human" not in log3[-1])
        # RELEASE-SWEEP S4/S5/S6/S9/S11, G4 (SWEEP-FIX D2): bookkeeping refusals that used to make a release stop
        # "the human's now" have a real cure; the history is reset afterwards
        global sealed_fails
        h_sw = G("rev-parse", "HEAD")
        RS = "2026-10-24-full-7a8b9c0"
        r = os.path.join(rd, RS)
        os.makedirs(os.path.join(r, "prompts"))
        open(os.path.join(r, "TARGET.json"), "w").write(json.dumps({"correspondence": ["T.7", "T.8"]}))
        G("add", "-A"); G("commit", "-qm", f"scope {RS}")
        vS = lane("correspondence", [("T.7", "Fail"), ("T.8", "Pass")])
        tS = json.load(open(vS)); tS["verdicts"][0]["verdict"] = "Pass"; json.dump(tS, open(vS, "w"))
        G("add", "-A"); G("commit", "-qm", f"implement {RS}")
        outs["integrity"] = (1, "FAIL[seal-mismatch] a verdict differs from its seal\n")
        sS, _ = open_stop(cfg_r, cmd=f"python3 audits/integrity.py --check --round {RS}", round_name=RS)
        rowS = next(x for x in stop_rows(cfg_r) if x["stop"] == sS)
        keep_sf, sealed_fails = sealed_fails, (lambda v: None)
        try:
            docS, _hS = set_aside(cfg_r, RS, "release self-cure of " + sS, stop=sS)
        finally:
            sealed_fails = keep_sf
        say("RELEASE-SWEEP S6: a self-cure's set-aside of a lane whose sealed bytes are nowhere in git is no human stop: "
            "every item the round scoped for that lane is carried forward as Ambiguous, recorded as sealed_lost",
            docS.get("sealed_lost") == ["correspondence.json"]
            and {("T.7", "Ambiguous"), ("T.8", "Ambiguous")} <= {(c["item"], c["verdict"]) for c in docS["carried"]})
        say("RELEASE-SWEEP S11: an open self-cure stop is listed as the operator's to cure, not as waiting for the human",
            rowS["done"] == "OPEN: the operator is curing it")
        RL = "2026-10-25-full-8b9c0d1"
        os.makedirs(os.path.join(rd, RL)); open(os.path.join(rd, RL, "TARGET.json"), "w").write("{not json")
        G("add", "-A"); G("commit", "-qm", f"scope {RL}")
        s5 = refused(redo_round, cfg_r, sS, load(os.path.join(rd, STOPS, sS, "STOP.json")))
        say("RELEASE-SWEEP S5: a redo lineage round whose TARGET.json cannot be read is no fresh round of the redo "
            "(scope another), never a human stop", "there is none yet" in s5 and "--human" not in s5)
        close_stop(cfg_r, sS, human="x")
        # an unreadable committed stop record: counted the conservative way, flagged by the trail, never the human's
        sU = f"S{int(stops(cfg_r)[-1][1:]) + 1}"
        os.makedirs(os.path.join(rd, STOPS, sU)); open(os.path.join(rd, STOPS, sU, "STOP.json"), "w").write("{cut")
        G("add", "-A"); G("commit", "-qm", f"stop {sU} open")
        try:
            evU, okU = tally_events(cfg_r), True
        except Refused:
            evU, okU = [], False
        say("RELEASE-SWEEP S4: an unreadable committed stop record no longer makes every self-cure the human's: the "
            "tally counts it the conservative way and the trail flags it ([stop-trail], acknowledgeable)",
            okU and ("open", sU, frozenset(), evU[-1][3]) == evU[-1]
            and any("cannot be read: counted as an opening" in p for p in trail_problems(cfg_r)))
        G("reset", "-q", "--hard", h_sw)
        # S9 / review H2: the owner re-committed the file after the foreign commit (the next adjudication adopted an
        # operator's hand edit): the revert still applies -- it undoes the owner's later change too, which the owner
        # commits again -- and integrity verifies it; a non-owner change since is refused (revert that one first)
        pdS = os.path.join(rd, "PAPER_DEFECTS.md")
        open(pdS, "a").write("| 9 | a hand edit |\n"); G("add", "-A"); G("commit", "-qm", "implement fix")
        hS = G("rev-parse", "HEAD")
        open(pdS, "a").write("| 10 | adjudicated |\n"); G("add", "-A"); G("commit", "-qm", f"adjudicate {R4}")
        outs["integrity"] = (1, f"FAIL[ownership] PAPER_DEFECTS.md was committed by \"implement fix\" ({hS[:11]})\n")
        sR, _ = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
        h9 = revert(cfg_r, sR, hS)
        all9 = [m for sv, m in integrity.check(d, cfg_r, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
                if sv == "FAIL" and (hS[:11] in m or h9[:11] in m)]
        own9 = [m for m in all9 if not m.startswith("[owner-redo]")]
        kept9 = os.path.exists(pdS) and "| 10 | adjudicated |" in open(pdS).read()
        log9 = open(os.path.join(rd, "RUN_LOG.md")).read()
        close_stop(cfg_r, sR, human="x")
        G("reset", "-q", "--hard", h_sw)
        open(pdS, "a").write("| 9 | a hand edit |\n"); G("add", "-A"); G("commit", "-qm", "implement fix")
        hS2 = G("rev-parse", "HEAD")
        open(pdS, "w").write(open(pdS).read().replace("| 9 | a hand edit |", "| 9 | a hand edit, edited again |"))
        G("add", "-A"); G("commit", "-qm", "implement more")
        outs["integrity"] = (1, f"FAIL[ownership] PAPER_DEFECTS.md was committed by \"implement fix\" ({hS2[:11]})\n")
        sR2, _ = open_stop(cfg_r, cmd="python3 audits/integrity.py --check")
        e9 = refused(revert, cfg_r, sR2, hS2)
        close_stop(cfg_r, sR2, human="x")
        G("reset", "-q", "--hard", h_sw)
        outs["integrity"] = (0, "ok\n")
        say("RELEASE-SWEEP S9 / review H2, R1: a revert of a hand edit its owner re-committed since is a verified cure "
            "(undone onto the current content, or the content restored with FAIL[owner-redo] until a fresh round "
            "re-decides); after a NON-owner change it cannot undo cleanly it is refused naming the route, never a human stop",
            h9 and own9 == [] and "not its owner's" in e9 and "human stop once" not in e9
            # review R1: either the hand edit was undone onto the current content (row 10 kept, nothing to redo) or the
            # restore undid row 10 too and FAIL[owner-redo] says so until a fresh round re-decides it -- never silent
            and ((kept9 and not all9) or (not kept9 and len(all9) == 1 and all9[0].startswith("[owner-redo]")
                                          and "re-decided by a fresh" in log9)))
        say("RELEASE-SWEEP G4: the `unsettled` closer checks settledness (lanecheck.py --round R --settled)",
            project.closer("unsettled", RS) == f"python3 audits/lanecheck.py --round {RS} --settled"
            and command_problem(project.closer("unsettled", RS), cfg_r) is None)
        # L1 (U2 §4): for every code x mode x level a closer exists AND works. A stop of the code is opened
        # (its check failing), the fixture made to pass, and the stop closed the way its mode and kind say:
        # release, a self-cure re-running the recorded check, which command_problem accepts and which passes
        # -- integrity.py --check is the REAL in-process integrity check, run with that stop open (its stop
        # trail included), the other read-only checks a stand-in; human and dev: --human; disclose: open
        # refuses in release. The history is reset after each case, so no case spends another's budget.
        # (a fresh record of its own: the stop trail of the long history above makes each case slow)
        d = os.path.join(base, "l1")
        rd = os.path.join(d, "P")
        os.makedirs(os.path.join(rd, R_))
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True).stdout.strip()
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        open(os.path.join(d, ".gitignore"), "w").write("__pycache__/\n")
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("# Run log\n")
        open(os.path.join(rd, R_, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = project.AUDITS = d
        h_l0, l1_bad = G("rev-parse", "HEAD"), []
        real_integ = lambda c_: (lambda fs: (1 if fs else 0, "".join(f"FAIL {m}\n" for m in fs) or "integrity: OK\n"))(
            [m for sv, m in integrity.check(d, c_, None, agent_file=agent, rounds_dir=rd, rounds_rel="P") if sv == "FAIL"])
        l1_clean = []
        for md in project.MODES:
            for lv in project.INVOLVEMENT_LEVELS:
                c_ = dict(cfg, mode=md, involvement=lv)
                G("reset", "-q", "--hard", h_l0)
                integrity.pin(d, c_, agent_file=agent, rounds_dir=rd)    # the run's mode and level are pinned
                G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin")
                h_l1 = G("rev-parse", "HEAD")
                l1_clean.append(real_integ(c_)[0] == 0)
                for code in sorted(project.RELEASE) + ["no-such-code"]:
                    kind, cl = project.release_kind(code), project.closer(code, R_)
                    chk = cl if cl not in (None, "@check") else "python3 audits/integrity.py --check"
                    scr = chk.split()[1].split("/")[-1][:-3]
                    case = f"{code}/{md}/{lv}"
                    try:
                        RUNNER = lambda argv: outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, ""))
                        outs[scr] = (1, ("Traceback (most recent call last):\nKeyError: x\n" if code == "no-such-code"
                                         else f"FAIL[{code}] x\n"))
                        note = cl in (None, "@check") and code != "no-such-code"
                        if code in project.NEVER_STOP:      # ADDENDUM N1, approver: never a stop, in either mode
                            why_ = refused(open_stop, c_, note=f"x ({code})", cause=code, check=chk)
                            if "never a stop" not in why_:
                                l1_bad.append(case + ": a delivery precondition opened a stop")
                            continue
                        # tool-fault: disclose only; escalation-cite: a flag in every mode (approver, 2026-10-27)
                        if (md == "release" and kind == "disclose") or code in ("tool-fault", "escalation-cite"):
                            why_ = refused(open_stop, c_, note=f"x ({code})", cause=code, check=chk)
                            if "disclosed in release mode" not in why_ and "recorded with stops.py disclose" not in why_:
                                l1_bad.append(case + ": a disclosed code opened a stop")
                            continue
                        s_, m_ = (open_stop(c_, note=f"x ({code})", cause=code, check=chk) if note
                                  else open_stop(c_, cmd=chk, round_name=R_ if "--round" in chk else None))
                        doc_ = load(os.path.join(rd, STOPS, s_, "STOP.json"))
                        outs[scr] = (0, "ok\n")
                        RUNNER = lambda argv: (real_integ(c_) if any(x.endswith("integrity.py") for x in argv)
                                               else outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, "")))
                        if md == "release" and kind != "human":
                            ok_ = (command_problem(cure_cmd(doc_), c_) is None and "--cured" in m_
                                   and "--delegated" not in m_ and project.CURES[kind] in m_
                                   and "dev mode only" in refused(close_stop, c_, s_, delegated="x"))
                            close_stop(c_, s_, cured="cured as printed")
                            cl_ = load(os.path.join(rd, STOPS, s_, "CLOSED.json")) or {}
                            ok_ = ok_ and cl_.get("by") == "cure" and cl_.get("check") == chk and cl_["rerun"]["passes"]
                        else:
                            ok_ = "--cured" not in m_ and bool(refused(close_stop, c_, s_, cured="x"))
                            close_stop(c_, s_, human="the human's answer")
                            ok_ = ok_ and (load(os.path.join(rd, STOPS, s_, "CLOSED.json")) or {}).get("by") == "human"
                        ok_ = ok_ and (scr == "integrity" or not trail_problems(c_, d, rd))
                        if not ok_:
                            l1_bad.append(case + ": " + m_[:160])
                    except Refused as e:
                        l1_bad.append(f"{case}: refused: {e} [{RUNNER(['audits/integrity.py'])[1][:300]}]")
                    finally:
                        outs.pop(scr, None)
                        G("reset", "-q", "--hard", h_l1)
        RUNNER = lambda argv: outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, ""))
        say("L1: the fixture passes the real integrity check under every mode and level", all(l1_clean))
        say(f"L1: every code x mode x level has a closer that works ({len(project.RELEASE) + 1} codes; "
            f"{len(l1_bad)} failing{': ' + '; '.join(l1_bad[:4]) if l1_bad else ''})", not l1_bad)
        # review H-1: a release --note stop of a code with a closer of its own (project.CLOSER) records
        # exactly that closer, on the stop's round; the cure plan and delivery hold to it too
        G("reset", "-q", "--hard", h_l0)
        c_ = dict(cfg, mode="release", involvement="hands-off")
        integrity.pin(d, c_, agent_file=agent, rounds_dir=rd)
        G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin")
        h_h1, lc_ = G("rev-parse", "HEAD"), f"python3 audits/lanecheck.py --round {R_}"
        outs.update(lanecheck=(1, "FAIL[independence] lane 2 read lane 1's verdict\n"), make_report=(1, "MISSING x\n"))
        h1a = refused(open_stop, c_, note="x", cause="independence", round_name=R_, check="python3 audits/make_report.py --check")
        h1b = refused(open_stop, c_, note="x", cause="unsettled", round_name=R_, check=f"python3 audits/integrity.py --check --round {R_}")
        h1c = refused(open_stop, c_, note="x", cause="independence", check=lc_)
        h1v3 = refused(open_stop, c_, note="x", cause="independence", round_name=R_,
                       check=f"python3 -B audits/lanecheck.py --project P --round {R_}")
        G("reset", "-q", "--hard", h_h1)
        h1v6 = refused(open_stop, c_, note="x", cause="independence", round_name=R_,
                       check=f"python3 audits/lanecheck.py --project Other --round {R_}")
        s_, _m = open_stop(c_, note="x", cause="independence", round_name=R_)
        say("H-1: release refuses a --note stop whose --check is not its code's closer (another FORMS check that "
            "fails now, the wrong script for the round) or lacks the round a round-bound closer needs; without "
            "--check it records the closer itself",
            "closed by exactly `" + lc_ in h1a and "closed by exactly `" in h1b and "--round <R>" in h1c
            and (load(os.path.join(rd, STOPS, s_, "STOP.json")) or {}).get("check") == lc_)
        say("re-check V3/V6: the closer may carry -B and --project <this project>, never --project <another one>",
            not h1v3 and "closed by exactly `" + lc_ in h1v6)
        G("reset", "-q", "--hard", h_h1)
        bad_ = {"command": None, "check": "python3 audits/make_report.py --check", "round": R_, "stop": "S1",
                "causes": [{"code": "independence", "class": "tamper", "line": "(operator's note)"}]}
        say("H-1: the cure plan (and so close --cured and the trail) refuses a recorded check that is not the code's closer",
            cure_plan(c_, bad_) is None and cure_plan(c_, dict(bad_, check=lc_)) == ["redo"]
            and "closed by exactly" in refused(_close_doc, c_, "S1", bad_, cured="x"))
        # a self-cure recorded before H-1 (another check than the closer): delivery re-runs the closer too
        os.makedirs(os.path.join(rd, STOPS, "S1"))
        json.dump(bad_, open(os.path.join(rd, STOPS, "S1", "STOP.json"), "w"))
        G("add", "-A"); G("commit", "-qm", "stop S1 open")
        json.dump({"stop": "S1", "by": "cure", "mode": "release", "attempt": 1, "check": bad_["check"],
                   "rerun": {"exit": 0, "passes": True}}, open(os.path.join(rd, STOPS, "S1", "CLOSED.json"), "w"))
        G("add", "-A"); G("commit", "-qm", "stop S1 close")
        db_ = deliver_blocking(c_)
        say("H-1: delivery re-runs each self-cured stop's code closer as well as its recorded check",
            lc_ in db_ and bad_["check"] in db_
            and any(lc_ in w for w in math_gate(c_)[1]) if not outs.update(lanecheck=(1, "FAIL[independence] x\n")) else False)
        G("reset", "-q", "--hard", h_h1)
        # review M-2: --delegated records the run mode; a release-mode operator close is a trail fault
        c_d = dict(cfg, mode="dev", involvement="hands-off")
        outs["lanecheck"] = (1, "PROBLEM[stray-loop] pid 7\n")
        s_, _m = open_stop(c_d, cmd=lc_)
        outs["lanecheck"] = (0, "ok\n")
        close_stop(c_d, s_, delegated="killed it")
        cp_ = os.path.join(rd, STOPS, s_, "CLOSED.json")
        m2_dev = (load(cp_) or {}).get("mode") == "dev" and not [p for p in trail_problems(c_d, d, rd) if s_ in p]
        json.dump(dict(load(cp_), mode="release"), open(cp_, "w"), indent=1, sort_keys=True)
        G("add", "-A"); G("commit", "--amend", "-qm", f"stop {s_} close")
        m2_rel = [p for p in trail_problems(c_, d, rd) if "(--delegated) in release mode" in p]
        c0_ = dict(load(cp_)); c0_.pop("mode")
        json.dump(c0_, open(cp_, "w"), indent=1, sort_keys=True)
        G("add", "-A"); G("commit", "--amend", "-qm", f"stop {s_} close")
        m2_old = [p for p in trail_problems(c_, d, rd) if "(--delegated) in release mode" in p]
        say("M-2: --delegated writes the run mode into CLOSED.json; the trail reports an operator close recorded in "
            "release mode, and leaves a record without a mode (before B1a) alone", m2_dev and m2_rel and not m2_old)
        G("reset", "-q", "--hard", h_h1)
        outs["lanecheck"] = (1, "PROBLEM[stray-loop] pid 7\n")
        s_, _m = open_stop(c_, cmd=lc_)
        v5_open = (load(os.path.join(rd, STOPS, s_, "STOP.json")) or {}).get("mode") == "release"
        json.dump({"stop": s_, "by": "operator", "text": "killed it"}, open(os.path.join(rd, STOPS, s_, "CLOSED.json"), "w"))
        G("add", "-A"); G("commit", "-qm", f"stop {s_} close")
        say("re-check V5: STOP.json records the mode at open; a forged operator close without a mode of a stop opened "
            "in release is still a trail fault", v5_open and m2_dev and
            [p for p in trail_problems(c_, d, rd) if s_ in p and "(--delegated) in release mode" in p])
        G("reset", "-q", "--hard", h_h1)
        outs.clear()
        # review MED-2 / OPERATOR-PATCH (approver 2026-10-24): a pinned writer that keeps crashing while every
        # read-only check passes: release opens tool-bug with no --check on the tool-patch route (never a human stop,
        # never env-unknown); a --cured that is no tool patch is refused
        mt_, mm_ = open_stop(c_, note="prompt.py 3 crashes (traceback in audits/prompt.py) on every retry", cause="tool-bug")
        say("MED-2 / OPERATOR-PATCH: release opens --cause tool-bug without --check on the tool-patch route (not a "
            "human stop); --cured without a tool patch is refused; unknown-retry still needs its --check",
            "not a human stop" in mm_ and "tool_patch.py begin" in mm_ and 'tool-patch TP<k>' in mm_
            and "only by a tool patch" in refused(close_stop, c_, mt_, cured="x")
            and "not an applied tool patch" in refused(close_stop, c_, mt_, cured="tool-patch TP1")
            and close_stop(c_, mt_, human="a maintainer will fix prompt.py")["by"] == "human"
            and not [p for p in trail_problems(c_, d, rd) if mt_ in p]
            and "--check" in refused(open_stop, c_, note="x", cause="unknown-retry"))
        G("reset", "-q", "--hard", h_h1)
        # addendum N5 / review MED-3: a REAL sealed round with a redo-class fault (seal-mismatch: a verdict changed
        # after its seal), set aside by its self-cure, then close --cured. lanecheck runs for real (only its tree
        # baseline and process scan, which need a Lean project, are left out): on the set-aside round it still
        # fails (the round keeps its files as record), so the cure re-runs it on the fresh round (redo_round)
        import lanecheck
        d = os.path.join(base, "n5")
        rd = os.path.join(d, "P")
        os.makedirs(rd)
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True).stdout.strip()
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        open(os.path.join(d, ".gitignore"), "w").write("__pycache__/\n")
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("# Run log\n")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = project.AUDITS = d
        integrity.pin(d, c_, agent_file=agent, rounds_dir=rd)
        G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin")

        def real_round(rnd, tamper=False, lanes=True, item="N.a", redo=None):
            r = os.path.join(rd, rnd)
            os.makedirs(os.path.join(r, "prompts"))
            open(os.path.join(r, "TARGET.json"), "w").write(json.dumps(
                {"correspondence": [item], "_meta": dict({"kind": "full" if "-full-" in rnd else "diff"},
                                                         **({"redo_of": redo} if redo else {}))}))
            G("add", "-A"); G("commit", "-qm", f"scope {rnd}")
            if not lanes:
                return
            v = os.path.join(r, "correspondence.json")
            pf = os.path.join(r, "prompts", "correspondence.txt")
            open(pf, "w").write(f"Write that JSON object, and nothing else, to {v}\n")
            tok = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(pf)).group(1)
            doc = {"lane_token": tok, "probes": lane_auth.probe_manifest(v),
                   "verdicts": [{"item": item, "verdict": "Fail", "next_step": "-"}]}
            data = json.dumps(doc).encode()
            open(v, "wb").write(data)
            lane_auth.seal(v, lane_auth.sha(data), "agent-correspondence")
            G("add", "-A"); G("commit", "-qm", f"lanes {rnd}")
            if tamper:
                doc["verdicts"][0]["verdict"] = "Pass"
                open(v, "w").write(json.dumps(doc))
                G("add", "-A"); G("commit", "-qm", f"edit {rnd}")

        def real_lc(argv):
            rnd = argv[argv.index("--round") + 1]
            ps = [p for p in lanecheck.check_round(c_, rnd, processes=False) if lanecheck.counts(p)]
            return (1 if ps else 0), "".join(p + "\n" for p in ps) + f"lane check {rnd}\n"
        saved_sf = lanecheck.stray_files
        lanecheck.stray_files = lambda *a: []
        try:
            RUNNER = lambda argv: (real_lc(argv) if any(x.endswith("lanecheck.py") for x in argv) else (0, "ok\n"))
            R5a, R5b = "2026-10-19-full-1a2b3c4", "2026-10-20-full-2b3c4d5"
            real_round(R5a, tamper=True)
            s5, m5 = open_stop(c_, cmd=f"python3 audits/lanecheck.py --round {R5a}", round_name=R5a)
            d5 = load(os.path.join(rd, STOPS, s5, "STOP.json"))
            set_aside(c_, R5a, f"release self-cure of {s5}", stop=s5)
            stale = real_lc(["lanecheck.py", "--round", R5a])
            early = refused(close_stop, c_, s5, cured="redone")
            h_n5 = G("rev-parse", "HEAD")
            real_round("2026-10-20-3c4d5e6", item="Other.decl", redo=R5a)   # a diff round that does not cover R5a
            n5_other = refused(close_stop, c_, s5, cured="redone")
            G("reset", "-q", "--hard", h_n5); G("clean", "-fdq")
            real_round(R5b, lanes=False, redo=R5a)                    # scoped, no lane has run yet
            n5_empty = refused(close_stop, c_, s5, cured="redone")
            G("reset", "-q", "--hard", h_n5); G("clean", "-fdq")
            real_round(R5b)                                           # covers R5a, lanes run, but no redo_of
            n5_nolin = refused(close_stop, c_, s5, cured="redone")
            G("reset", "-q", "--hard", h_n5); G("clean", "-fdq")
            say("B1b: a fresh round that is not in the redo lineage (no redo_of naming the set-aside round) is not "
                "the redo: refused, no cure attempt spent", "redo_of " + R5a in n5_nolin
                and "no cure attempt was spent" in n5_nolin and not cure_attempts(c_, s5)
                and redo_target(c_) == R5a)
            say("re-check N5 variants: a fresh round that does not cover the set-aside round's scope, or that is only "
                "scoped (no lane verdicts), is not the redo: close --cured is refused and no cure attempt is spent",
                "do not cover round" in n5_other and "no verdicts of lane(s) correspondence" in n5_empty
                and "no cure attempt was spent" in n5_other + n5_empty and not cure_attempts(c_, s5)
                and "cure 1" not in _log(d, "--format=%s"))
            real_round(R5b, redo=R5a)
            rec5 = close_stop(c_, s5, cured=f"redone in {R5b}")
            n5_ok = ("seal-mismatch" in {c["code"] for c in d5["causes"]} and "redo" in m5
                     and stale[0] == 1 and "seal-mismatch" in stale[1]
                     and "no cure attempt was spent" in early and not cure_attempts(c_, s5)
                     and rec5["redo_round"] == R5b and rec5["check"] == f"python3 audits/lanecheck.py --round {R5b}"
                     and rec5["rerun"]["passes"] and not [p for p in trail_problems(c_, d, rd) if s5 in p]
                     and f"python3 audits/lanecheck.py --round {R5b}" in deliver_blocking(c_)
                     and not any(R5a in x for x in deliver_blocking(c_)))
            say("N5/MED-3: on a real sealed round with a seal-mismatch, set aside by its self-cure, lanecheck --round "
                "<set-aside R> still fails (real), so close --cured waits for the fresh round (no attempt spent) and "
                "re-runs lanecheck on it (redo_round), which passes; trail and delivery accept it", n5_ok)
            cp5 = os.path.join(rd, STOPS, s5, "CLOSED.json")
            json.dump(dict(rec5, redo_round=R5a, check=f"python3 audits/lanecheck.py --round {R5a}"), open(cp5, "w"),
                      indent=1, sort_keys=True)
            G("add", "-A"); G("commit", "--amend", "-qm", f"stop {s5} close")
            say("N5/MED-3: the trail rejects a redo_round that is not a fresh round redoing the set-aside one",
                any("not a fresh round" in p for p in trail_problems(c_, d, rd)))
            R5c = "2026-10-21-full-3c4d5e6"
            real_round(R5c)                  # covers R5a, its lanes ran, but it names no redo_of
            json.dump(dict(rec5, redo_round=R5c, check=f"python3 audits/lanecheck.py --round {R5c}"), open(cp5, "w"),
                      indent=1, sort_keys=True)
            G("add", "-A"); G("commit", "--amend", "-qm", f"stop {s5} close")
            say("B1b: the trail rejects a redo_round outside the redo lineage (its TARGET.json has no redo_of naming "
                "the set-aside round)", any("not a fresh round" in p for p in trail_problems(c_, d, rd)))
        finally:
            lanecheck.stray_files = saved_sf
        # --- B1b: the failure tally (U2 §4 M1) and the redo lineage, in a fresh release fixture -------------
        d = os.path.join(base, "b1b")
        rd = os.path.join(d, "P")
        os.makedirs(rd)
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True).stdout.strip()
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        open(os.path.join(d, ".gitignore"), "w").write("__pycache__/\n")
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("# Run log\n")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = project.AUDITS = d
        integrity.pin(d, c_, agent_file=agent, rounds_dir=rd)
        G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin")
        outs = {}
        RUNNER = lambda argv: outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, ""))
        py = "python3 audits/"

        def scope_(rnd, target=None, verdicts=True):
            """scope round `rnd`; with `verdicts`, also commit a (dummy) verdict file: the round becomes the bucket
            of the openings ceiling (a round only scoped is not)."""
            os.makedirs(os.path.join(rd, rnd), exist_ok=True)
            open(os.path.join(rd, rnd, "TARGET.json"), "w").write(target if target is not None else "{}")
            G("add", "-A"); G("commit", "-qm", f"scope {rnd}")
            if verdicts:
                open(os.path.join(rd, rnd, "substantiveness.json"), "w").write("{}")
                G("add", "-A"); G("commit", "-qm", f"lanes {rnd}")

        def cycle(scr, fail, cmd=None, note=None, cause=None, check=None, round_name=None, cure_fails=0):
            """open a stop; cure it (`cure_fails` failing attempts first); returns (stop, open message, [close
            outcomes]); a human stop is closed --human."""
            outs[scr] = (1, fail)
            s, m = open_stop(c_, cmd=cmd, note=note, cause=cause, check=check, round_name=round_name)
            got = []
            if "a self-cure, not" in m:
                for i in range(cure_fails + 1):
                    outs[scr] = (1, fail) if i < cure_fails else (0, "ok\n")
                    e = refused(close_stop, c_, s, cured=f"try {i}")
                    got.append(e or "closed")
                    if e and "still fails" not in e:
                        break
            if not (load(os.path.join(rd, STOPS, s, "CLOSED.json")) or {}):
                close_stop(c_, s, human="x")
            outs[scr] = (0, "ok\n")
            return s, m, got
        self_ = lambda m: "a self-cure, not" in m
        # (1) relabels to the retry codes (re-check V4, A3) on one check: one key per round and check script, its
        # openings counted once a retry has failed a cure in the round; unrelated retries on other checks are not
        # that fault (B1b re-check H3: the --note key carries the check script)
        rot = [cycle("readers", "FAIL[reader-check] x\n", note="prompt.py 3 crashed", cause="unknown-retry",
                     check=py + "readers.py --doc report --check", cure_fails=1)[1]]
        h3 = [cycle(sc, out, note=f"tool call {sc} failed", cause="tool-call", check=py + f"{sc}.py " + fl)[1]
              for sc, fl, out in (("make_report", "--check", "FAIL[report] x\n"), ("decisions", "--check", "FAIL[decisions] x\n"),
                                  ("tree_state", "--check", "FAIL[tree-changed] x\n"),
                                  ("integrity", "--check", "FAIL[ownership] x\n"), ("phase0", "--readonly", "RED[build] x\n"))]
        rot += [cycle("readers", f"FAIL[{y}] x\n", note="prompt.py 3 crashed again", cause=cz,
                      check=py + "readers.py --doc report --check")[1]
                for y, cz in (("label", "unknown-retry"), ("render", "commit-refused"), ("record-format", "git-error"),
                              ("index", "tool-call"))]
        say("B1b L3 / re-check H3: after one failed retry cure, five tool-call stops on five different checks are no "
            "the budget is spent; relabelling to unknown-retry/commit-refused/git-error/tool-call (V4) on the same check does not "
            "reset the tally: the 4th opening of its --note retry key in the round after the failed cure spends the budget",
            all(map(self_, h3)) and all(map(self_, rot[:4])) and SPENT in rot[4]
            and "--note retry checked by readers" in rot[4])
        # (2) failed cures are counted over the whole run: a new round and an empty commit reset nothing
        R1_, R2_ = "2026-10-19-full-1a2b3c4", "2026-10-20-full-2b3c4d5"
        scope_(R1_)
        p0 = py + "phase0.py --readonly"
        _s, m1_, got1 = cycle("phase0", "RED[build] x\n", cmd=p0, cure_fails=2)
        G("commit", "-q", "--allow-empty", "-m", "an empty Lean commit")
        scope_(R2_)
        _s, m2a, g2a = cycle("phase0", "RED[build] x\n", cmd=p0, cure_fails=1)
        _s, m2_, _g = cycle("phase0", "RED[build] x\n", cmd=p0)
        _s, m2b, g2b = cycle("make_report", "FAIL x\n", note="lake crashed", cause="unknown-retry",
                             check=py + "make_report.py --check", cure_fails=2)
        G("commit", "-q", "--allow-empty", "-m", "an empty Lean commit")
        _s, m2e, g2e = cycle("make_report", "FAIL x\n", note="lake crashed", cause="git-error",
                             check=py + "make_report.py --check", cure_fails=1)
        _s, m2c, _g = cycle("make_report", "FAIL x\n", note="lake crashed", cause="tool-call", check=py + "make_report.py --check")
        say("B1b L3: KEY_BUDGET (3) failed cures of a key are its budget for the whole run (a --note stop: the codes "
            "its check printed, uncoded = unknown): a new round, an empty commit, a new stop id or another retry code "
            "do not reset it (the budget is spent)",
            self_(m1_) and "attempt 2 of 2" in got1[1] and "budget is spent" in got1[1] and self_(m2a)
            and "budget is spent" in g2a[0] and SPENT in m2_ and "retry budget (3)" in m2_ and self_(m2b)
            and "budget is spent" in g2b[1] and self_(m2e) and "budget is spent" in g2e[0] and SPENT in m2c
            and "unknown from make_report" in m2c)
        # (3) a renamed code meets the fault its check reports
        lc = py + f"lanecheck.py --round {R2_}"
        _s, m3_, got3 = cycle("lanecheck", "PROBLEM[stray-loop] pid 7\n", cmd=lc, round_name=R2_, cure_fails=2)
        _s, m3a, g3a = cycle("lanecheck", "PROBLEM[stray-loop] pid 7\n", cmd=lc, round_name=R2_, cure_fails=1)
        _s, m3b, _g = cycle("lanecheck", "PROBLEM[stray-loop] pid 7\n", note="a lane loop", cause="stray-file",
                            round_name=R2_)
        _s, m3c, _g = cycle("lanecheck", "PROBLEM[stray-loop] pid 7\n", note="lanecheck crashed", cause="tool-bug",
                            check=lc, round_name=R2_)
        say("B1b L3: a --note stop under another code (stray-file, tool-bug) whose check reports the spent fault "
            "(lanecheck, stray-loop) spends the budget", self_(m3_) and self_(m3a) and "budget is spent" in g3a[0] and SPENT in m3b and SPENT in m3c
            and "stray-loop from lanecheck" in m3b)
        # (4) a reopened stop counts as another opening; the trail sees the attempt past the ceiling
        tsc = py + "tree_state.py --check"
        s4_, m4_, _g = cycle("tree_state", "FAIL[tree-changed] x\n", cmd=tsc, cure_fails=1)
        reo = []
        for i in range(project.OPEN_CEILING + 1):
            G("rm", "-q", "--", f"P/{STOPS}/{s4_}/CLOSED.json"); G("commit", "-qm", f"stop {s4_} open")
            outs["tree_state"] = (0, "ok\n")
            reo.append(refused(close_stop, c_, s4_, cured=f"again {i}"))
        cl4 = os.path.join(rd, STOPS, s4_, "CLOSED.json")
        json.dump({"stop": s4_, "by": "cure", "mode": "release", "attempt": 1, "check": tsc,
                   "rerun": {"exit": 0, "passes": True}}, open(cl4, "w"))
        G("add", "-A"); G("commit", "-qm", f"stop {s4_} close")
        say("B1b L3: re-opening a stop (its CLOSED.json removed, \"stop S<n> open\" committed again) is counted as an "
            "opening: the 4th in a round after its failed cure is refused, and a forged close past it is a trail fault",
            self_(m4_) and reo[:3] == ["", "", ""] and "per round" in reo[3]
            and any("past its ceilings" in p for p in trail_problems(c_, d, rd)))
        G("reset", "-q", "--hard", "HEAD~1")
        close_stop(c_, s4_, human="x")
        # (5) openings are bucketed by the newest round scoped, not by the stop's free --round (re-check R1)
        fpc = py + "fingerprint.py --check"
        b5 = [cycle("fingerprint", "DRIFT[drift] x\n", cmd=fpc, round_name=(R1_, R2_)[i % 2], cure_fails=int(i == 0))[1]
              for i in range(5)]
        say("B1b: openings are counted per round (the newest with a verdict file), whatever --round a stop names",
            all(map(self_, b5[:4])) and SPENT in b5[4])
        # (6) the redo lineage: a different code Y on the fresh round charges Y, never the stop's own key; every
        # refused close charges some key; unreadable lineage is the human's
        R3_, R4_, R5_ = "2026-10-21-full-3c4d5e6", "2026-10-22-full-4d5e6f7", "2026-10-22-full-5e6f7a8"
        scope_(R3_, verdicts=False)
        outs["lanecheck"] = (1, "FAIL[seal-mismatch] x\n")
        s6, m6 = open_stop(c_, cmd=py + f"lanecheck.py --round {R3_}", round_name=R3_)
        set_aside(c_, R3_, f"release self-cure of {s6}", stop=s6)
        rt6 = redo_target(c_)
        h6 = G("rev-parse", "HEAD")
        scope_("2026-10-22-full-6f7a8b9", '{"_meta": {"redo_of": 7}}')
        bad6 = refused(close_stop, c_, s6, cured="x")
        G("reset", "-q", "--hard", h6); G("clean", "-fdq")
        scope_(R4_, json.dumps({"_meta": {"kind": "full", "redo_of": rt6}}))
        outs["lanecheck"] = (1, "FAIL[independence] lane 2 read lane 1\n")
        y1 = refused(close_stop, c_, s6, cured="redone")
        ev6 = tally_events(c_)
        scope_(R5_, json.dumps({"_meta": {"kind": "full", "redo_of": rt6}}))
        y2 = refused(close_stop, c_, s6, cured="redone again")
        y3 = refused(close_stop, c_, s6, cured="and again")
        fails6 = [e for e in tally_events(c_) if e[0] == "fail"]
        say("B1b: scope.py's redo_of names the open stop's set-aside round; an unreadable lineage round is no fresh round "
            "(RELEASE-SWEEP S5: never the human's); a "
            "fresh round failing with another code Y charges Y only, and the stop that keeps charging Y meets "
            "Y's budget (the budget is spent)",
            self_(m6) and rt6 == R3_ and "there is none yet" in bad6 and "--human" not in bad6 and "still fails" in y1
            and ev6[-1][2] == frozenset({("lanecheck", "independence")}) and "still fails" in y2
            and SPENT in y3 and "per-stop cap" in y3
            and "independence from lanecheck" in " ".join(tally(fails6 + [("fail", "Sq", ev6[-1][2], R5_)], "Sq",
                                                                 ev6[-1][2])[1])
            and not any(("lanecheck", "seal-mismatch") in e[2] for e in fails6))
        close_stop(c_, s6, human="x")
        outs.pop("lanecheck")
        # (7) mini3's chain under release: a record fault only the next adjudication clears, which cannot run
        # (Phase 0 RED): the operator retries each way the protocol lets it; the spent budget comes exactly once, and soon
        R6_ = "2026-10-23-full-6a7b8c9"
        chain, n4 = [], 0
        for i in range(8):
            rr = (R5_, R6_, "2026-10-24-full-7b8c9d0", "2026-10-25-full-8c9d0e1")[min(i, 3)]
            if not os.path.isfile(os.path.join(rd, rr, "TARGET.json")):
                scope_(rr)      # the "fix": another round (mini3's round 3)
            _s, mc, gc = cycle("make_report", "FAIL[dead-witness] PAPER_DEFECTS row 2 names sorry\n",
                               cmd=py + "make_report.py --check --index-only", cure_fails=3)
            chain.append(mc)
            n4 += (SPENT in mc) or any("budget is spent" in g or SPENT in g for g in gc)
            if n4:
                break
        say(f"B1b: mini3's deadlock chain spends the budget exactly once, after {len(chain)} stop(s)",
            n4 == 1 and len(chain) <= 2)
        # (8) a run-#3-length history, with the codes its checks print, each fault cured at the first try but a
        # flaky tool every 10 rounds whose first retry fails (a different fault each time), never spends the budget;
        # the same fault failing a cure again anywhere in the run does (the whole-run budget: failures recur)
        ev8, flakes = [], (("lanecheck", "lane-output"), ("prompt", "verify-written"), ("phase0", "build"),
                           ("make_report", "report"))
        for i in range(40):
            rnd = f"r{i}"
            for k8 in ({("lanecheck", "lane-fault")}, {("lanecheck", "stray-file")}, {("lanecheck", "stray-file")},
                       {("--note", "retry", rnd), ("lanecheck", "lane-output")}):
                n8 = f"S{len(ev8)}"
                ev8 += [("open", n8, frozenset(k8), rnd), ("pass", n8, frozenset(k8), rnd)]
            if i % 10 == 9:
                n8, k8 = f"S{len(ev8)}", frozenset({("--note", "retry", rnd), flakes[i // 10]})
                ev8 += [("open", n8, k8, rnd), ("fail", n8, k8, rnd), ("pass", n8, k8, rnd)]
        worst = [tally(ev8[:i], e[1], e[2])[1] for i, e in enumerate(ev8) if e[0] in ("fail", "pass")]
        k8b = frozenset({("--note", "retry", "r39"), ("lanecheck", "lane-output")})
        ev8b1 = ev8 + [("open", "Sy", k8b, "r39"), ("fail", "Sy", k8b, "r39"), ("pass", "Sy", k8b, "r39")]
        ev8b = ev8b1 + [("open", "Sy2", k8b, "r39"), ("fail", "Sy2", k8b, "r39")]
        k8d = frozenset({("--note", "retry", "r39"), ("integrity", "gitmeta")})    # another flake, same round
        k8e = frozenset({("--note", "retry", "r39"), ("phase0", "sorry")})    # and a third, same round
        ev8d = ev8 + [("open", "Sw", k8d, "r39"), ("fail", "Sw", k8d, "r39"), ("pass", "Sw", k8d, "r39"),
                      ("open", "Sw2", k8e, "r39"), ("fail", "Sw2", k8e, "r39")]
        ev8c = ev8 + [("open", f"Sz{i}", frozenset({("make_report", "report")}), "r39") for i in range(4)]
        say("B1b ceilings: 40 rounds with coded check output (2 stray-file, a lane-fault, a retry with "
            "FAIL[lane-output] per round, cured at the first try; a flaky tool failing its first retry once per 10 "
            "rounds, a different fault each time) never spend the budget; the lane-output flake failing a cure again 30 "
            "rounds later does not (re-check H1), a third time does, and so does a 4th opening in a round after a failed cure there; a 2nd and 3rd different flake "
            "failing in one round do not (a --note key counts openings only)",
            not any(worst) and not tally(ev8b1, "Sv", k8b)[1]
            and "lane-output from lanecheck" in " ".join(tally(ev8b, "Sv", k8b)[1])
            and "per round" in " ".join(tally(ev8c, "Sz3", {("make_report", "report")})[1])
            and not tally(ev8c[:-1], "Sz2", {("make_report", "report")})[1]
            and not tally(ev8d, "Sw2", k8e)[1])
        # b1b-2k: a stop opened on key X whose failed cure is charged to Y meets Y's run-wide budget (Y failed
        # twice under other stops before): its charged keys are its own
        kx_, ky_ = frozenset({("integrity", "gitmeta")}), frozenset({("lanecheck", "lane-output")})
        ev2k = [e for i, r_ in enumerate(("r1", "r2")) for e in
                (("open", f"Sk{i}", ky_, r_), ("fail", f"Sk{i}", ky_, r_), ("pass", f"Sk{i}", ky_, r_))]
        ev2k += [("open", "Sk", kx_, "r3"), ("fail", "Sk", ky_, "r3")]
        say("B1b: a stop opened on X whose failed self-cure is charged to Y meets Y's run-wide budget (its charged "
            "keys are its own), with only one failed cure of its own",
            "lane-output from lanecheck" in " ".join(tally(ev2k, "Sk", kx_)[1]) and tally(ev2k, "Sk", kx_)[0] == 1)
        # (9) the per-stop cap (review attack A): a redo whose fresh round fails with a different code Y on every
        # attempt charges a different key each time, but the stop itself has CURE_BUDGET failed cures: the budget is spent
        R7_, R8_ = "2026-10-26-full-9d0e1f2", "2026-10-27-full-0e1f2a3"
        scope_(R7_, verdicts=False)
        outs["lanecheck"] = (1, "FAIL[seal-mismatch] x\n")
        s9, m9 = open_stop(c_, cmd=py + f"lanecheck.py --round {R7_}", round_name=R7_)
        set_aside(c_, R7_, f"release self-cure of {s9}", stop=s9)
        scope_(R8_, json.dumps({"_meta": {"kind": "full", "redo_of": redo_target(c_)}}))
        a9 = []
        for y in ("unsealed", "no-baseline", "unsettled", "lane-fault", "lane-output", "evidence-after-seal", "no-round"):
            outs["lanecheck"] = (1, f"PROBLEM[{y}] x\n")
            a9.append(refused(close_stop, c_, s9, cured=f"fixed {y}"))
        outs["lanecheck"] = (0, "ok\n")
        a9.append(refused(close_stop, c_, s9, cured="finally"))
        cl9 = os.path.join(rd, STOPS, s9, "CLOSED.json")
        json.dump({"stop": s9, "by": "cure", "mode": "release", "attempt": 2, "redo_round": R8_,
                   "check": py + f"lanecheck.py --round {R8_}", "rerun": {"exit": 0, "passes": True}}, open(cl9, "w"))
        G("add", "-A"); G("commit", "-qm", f"stop {s9} close")
        t9 = trail_problems(c_, d, rd)
        G("reset", "-q", "--hard", "HEAD~1")
        say("B1b review (attack A): a stop with CURE_BUDGET failed cures of its own spends the budget whatever codes they "
            "showed (7 different Y codes: the 3rd attempt is refused, no CURE3), and a close past it is a trail fault",
            self_(m9) and "attempt 1 of 2" in a9[0] and "budget is spent" in a9[1]
            and all(SPENT in x and "per-stop cap" in x for x in a9[2:])
            and cure_attempts(c_, s9) == ["CURE1.json", "CURE2.json"]
            and any("past its ceilings" in p and "per-stop cap" in p for p in t9))
        close_stop(c_, s9, human="x")
        outs.pop("lanecheck")
        # (10) review attack B: an uncoded --note check, relabelled unknown-retry -> commit-refused -> --cmd, then
        # new rounds: one key (decisions, unknown) for the whole run, whatever the stop's code or round
        R9_, R10_ = "2026-10-28-full-1f2a3b4", "2026-10-29-full-2a3b4c5"
        scope_(R9_)
        dk, miss = py + "decisions.py --check", "MISSING DECISIONS.md\n"
        b10 = [cycle("decisions", miss, note="prompt.py 3 crashed", cause="unknown-retry", check=dk, cure_fails=1),
               cycle("decisions", miss, note="adjudication commit refused", cause="commit-refused", check=dk,
                     cure_fails=1),
               cycle("decisions", miss, cmd=dk, cure_fails=1)]
        scope_(R10_)
        b10.append(cycle("decisions", miss, note="prompt.py 3 crashed", cause="tool-call", check=dk, cure_fails=1))
        say("B1b review (attack B): an uncoded --note check is keyed (script, unknown) for the whole run, "
            "commit-refused is a retry code: the 3rd failed cure across relabels is the budget, then the budget is spent (a "
            "--cmd stop of the same check, a new round)",
            self_(b10[0][1]) and b10[0][2] == ["`" + dk + "` still fails (exit 1): cure attempt 1 of 2 recorded; cure "
                                              "again", "closed"]
            and self_(b10[1][1]) and "still fails" in b10[1][2][0] and b10[1][2][1] == "closed"
            and self_(b10[2][1]) and "budget is spent" in b10[2][2][0] and SPENT in b10[2][2][1]
            and "unknown from decisions" in b10[2][2][1]
            and all(SPENT in m and "unknown from decisions" in m for _s, m, _g in b10[3:]))
        # (11) review compat: tool-call stops whose check prints FAIL[lane-output] (a child at capacity left no
        # verdict). The rule: the budget is spent only for (a) a stop with 2 failed cures of its own, (b) a (script, code) with 3
        # failed cures in the run, or (c) a 4th opening in a round after a failed cure of that key there.
        # Recurrence cured at the first try is none of these; a 3rd failed cure of the same fault is (b).
        R11_, R12_ = "2026-10-30-full-3b4c5d6", "2026-10-31-full-4c5d6e7"
        lk, lo = (lambda r: py + f"lanecheck.py --round {r}"), "FAIL[lane-output] correspondence: no verdict file\n"
        scope_(R11_)
        c11 = [cycle("lanecheck", lo, note="child at capacity", cause="tool-call", check=lk(R11_), round_name=R11_)
               for _ in range(project.OPEN_CEILING + 2)]
        _s, m11a, g11a = cycle("lanecheck", lo, note="child crashed", cause="tool-call", check=lk(R11_),
                               round_name=R11_, cure_fails=1)
        scope_(R12_)
        _s, m11b, g11b = cycle("lanecheck", lo, note="child at capacity", cause="tool-call", check=lk(R12_),
                               round_name=R12_)
        s11c, m11c, g11c = cycle("lanecheck", lo, note="child crashed", cause="tool-call", check=lk(R12_),
                               round_name=R12_, cure_fails=1)
        _s, m11d, g11d = cycle("lanecheck", lo, note="child crashed", cause="tool-call", check=lk(R12_),
                               round_name=R12_, cure_fails=1)
        say("B1b review (compat): 5 tool-call stops with FAIL[lane-output] in one round, cured at the first try, are "
            "no spent budget; one failed cure in a round, then first-try cures in the next: none; the same fault failing a "
            "cure again in another round: none (re-check H1: a flaky check); a third failed cure: the budget is spent",
            all(self_(m) and g == ["closed"] for _s, m, g in c11) and self_(m11a) and "attempt 1 of 2" in g11a[0]
            and g11a[1] == "closed" and self_(m11b) and g11b == ["closed"] and self_(m11c)
            and "attempt 1 of 2 recorded; cure again" in g11c[0] and g11c[1] == "closed" and not strail(c_, s11c)
            and self_(m11d)
            and "budget is spent" in g11d[0] and SPENT in g11d[1] and "lane-output from lanecheck" in g11d[1])
        # (12) review attacks C, C2: the fresh round must have run sealed lanes judging every item of the set-aside
        # scope; a redo whose check names no round (tree_state, head-moved) also runs lanecheck on the fresh round
        def lanes_(rnd, item="N.a", verdicts=None):
            r_ = os.path.join(rd, rnd)
            os.makedirs(os.path.join(r_, "prompts"), exist_ok=True)
            v_, pf = os.path.join(r_, "correspondence.json"), os.path.join(r_, "prompts", "correspondence.txt")
            open(pf, "w").write(f"Write that JSON object, and nothing else, to {v_}\n")
            tok = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(pf)).group(1)
            doc_ = {"lane_token": tok, "probes": lane_auth.probe_manifest(v_), "verdicts": verdicts if verdicts is not None
                    else [{"item": item, "verdict": "Fail", "next_step": "-"}]}
            data = json.dumps(doc_).encode()
            open(v_, "wb").write(data)
            lane_auth.seal(v_, lane_auth.sha(data), "agent-correspondence")
            G("add", "-A"); G("commit", "-qm", f"lanes {rnd}")
        R13_, F1_, F2_, F3_, R14_ = ("2026-11-01-5d6e7f8", "2026-11-02-6e7f8a9", "2026-11-03-7f8a9b0",
                                     "2026-11-04-8a9b0c1", "2026-11-05-full-9b0c1d2")
        tgt = lambda **m: json.dumps({"correspondence": ["N.a"], "_meta": dict({"kind": "diff"}, **m)})
        scope_(R13_, tgt(), verdicts=False)
        lanes_(R13_)
        # (a check without {R} printing a redo code; head-moved was this example until B1c made it a restore)
        outs["integrity"] = (1, "FAIL[lane-fault] a lane's evidence was changed during the round\n")
        s12, m12 = open_stop(c_, cmd=py + "integrity.py --check", round_name=R13_)
        set_aside(c_, R13_, f"release self-cure of {s12}", stop=s12)
        outs["integrity"] = (0, "ok\n")
        scope_(F1_, tgt(redo_of=R13_), verdicts=False)
        open(os.path.join(rd, F1_, "correspondence.json"), "w").write("")     # attack C: an empty file
        G("add", "-A"); G("commit", "-qm", f"lanes {F1_}")
        c12 = refused(close_stop, c_, s12, cured="redone")
        scope_(F2_, tgt(redo_of=R13_), verdicts=False)
        lanes_(F2_, verdicts=[])                                              # attack C2: sealed, judged nothing
        c12b = refused(close_stop, c_, s12, cured="redone")
        why1, why2 = redo_scope_problem(c_, R13_, F1_), redo_scope_problem(c_, R13_, F2_)
        scope_(F3_, tgt(redo_of=R13_), verdicts=False)
        lanes_(F3_)
        outs["lanecheck"] = (1, "PROBLEM[unauthenticated] correspondence.json\n")
        c12c = refused(close_stop, c_, s12, cured="redone")
        outs["lanecheck"] = (0, "ok\n")
        c12d = close_stop(c_, s12, cured="redone, lanes clean")
        db12 = deliver_blocking(c_)
        cl12 = os.path.join(rd, STOPS, s12, "CLOSED.json")
        json.dump({k: v for k, v in c12d.items() if k != "redo_lanecheck"}, open(cl12, "w"), indent=1, sort_keys=True)
        t12 = strail(c_, s12)
        G("checkout", "-q", "--", cl12)
        scope_(R14_, json.dumps({"correspondence": ["N.a", "N.b"], "_meta": {"kind": "statements"}}), verdicts=False)
        why3 = redo_scope_problem(c_, R14_, F3_)
        say("B1b review (attacks C, C2): a fresh round with an empty verdict file, or sealed lanes that judged none of "
            "the set-aside scope, is no redo (refused, no attempt); a redo whose check has no {R} also runs lanecheck "
            "on the fresh round (its failure is a failed cure); delivery re-runs it; a diff round cannot cover a "
            "statements round",
            self_(m12) and "no cure attempt was spent" in c12 and "no cure attempt was spent" in c12b
            and "not sealed" in why1 and "not judged" in why2 and "N.a" in why2
            and "still fails" in c12c and "attempt 1 of 2" in c12c
            and c12d.get("redo_round") == F3_ and c12d.get("redo_lanecheck") == py + f"lanecheck.py --round {F3_}"
            and not strail(c_, s12) and any("redo_lanecheck" in p or "lanecheck on the fresh round" in p for p in t12) and py + f"lanecheck.py --round {F3_}" in db12
            and "use --full" in why3 and "N.b" in why3)
        outs.pop("lanecheck")
        # B10 (U2 §6.3, L4): the hands-off sheet has no reader; delivery never gates it, the summary's reader is gated
        ap_ = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
        ap_keep = open(ap_).read() if os.path.exists(ap_) else None
        if ap_keep is not None:
            os.remove(ap_)
        dc_ = {lv: deliver_checks(dict(c_, involvement=lv)) for lv in project.INVOLVEMENT_LEVELS}
        json.dump({"round": R_}, open(ap_, "w"))
        dca_ = {lv: deliver_checks(dict(c_, involvement=lv)) for lv in project.INVOLVEMENT_LEVELS}
        os.remove(ap_)
        if ap_keep is not None:
            open(ap_, "w").write(ap_keep)
        say("approver (2026-10-23): a PDF is never a stop, in dev too (an older run's `pdf` code stays refused; "
            "PDF-AGENTS review 2); nor a delivery code",
            all("never a stop" in refused(open_stop, dict(c_, mode=md_), note="x", cause=cd_, check=py + "integrity.py --check")
                for md_ in project.MODES for cd_ in ("pdf", "deliver", "unverified", "deliver-stale")))
        say("B10: deliver_checks re-runs the summary's reader gate at every level and the sheet's only outside "
            "hands-off (signoff.py check is kept)",
            all(py + "readers.py --doc summary --check" in v for v in dca_.values())
            and py + "readers.py --doc signoff --round approved --check" not in dca_["hands-off"]
            and all(py + "readers.py --doc signoff --round approved --check" in dca_[lv]
                    for lv in ("involved", "statements-only"))
            and all(py + f"signoff.py check --round {R_}" in v for v in dca_.values())
            and not any("signoff" in x for v in dc_.values() for x in v))
        # TRADEOFFS T34: an earlier self-cure is judged by the apparatus pinned at its close, not by today's tables
        d = os.path.join(base, "t34")
        rd = os.path.join(d, "P")
        os.makedirs(rd)
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True).stdout.strip()
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        open(os.path.join(d, ".gitignore"), "w").write("__pycache__/\n")
        here = os.path.dirname(os.path.abspath(__file__))
        for f_ in os.listdir(here):         # the apparatus the run pins (its scripts, at the audits root)
            if f_.endswith(".py"):
                shutil.copy(os.path.join(here, f_), d)
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("# Run log\n\n## Stops\n")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = project.AUDITS = d
        integrity.pin(d, c_, agent_file=agent, rounds_dir=rd)
        G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin")
        outs = {}
        RUNNER = lambda argv: outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, ""))
        tsc_ = py + "tree_state.py --check"
        outs["tree_state"] = (1, "FAIL[tree-changed] x\n")
        sA, mA = open_stop(c_, cmd=tsc_)
        outs["tree_state"] = (0, "ok\n")
        close_stop(c_, sA, cured="restored the file")
        outs["tree_state"] = (1, "FAIL[tree-changed] x\n")
        sB, mB = open_stop(c_, note="the build environment is gone", cause="env-unknown", check=tsc_)
        json.dump({"stop": sB, "by": "cure", "mode": "release", "attempt": 1, "check": tsc_, "date": "2026-10-24",
                   "rerun": {"exit": 0, "passes": True}}, open(os.path.join(rd, STOPS, sB, "CLOSED.json"), "w"))
        G("add", "-A"); G("commit", "-qm", f"stop {sB} close")         # a forged self-cure of a human stop
        outs["tree_state"] = (0, "ok\n")
        before = (strail(c_, sA), strail(c_, sB))
        G("commit", "-q", "--allow-empty", "-m", "apparatus fix")
        integrity.pin(d, c_, agent_file=agent, rounds_dir=rd, repin="a bug in a script")
        G("add", "--", "P/" + integrity.PIN); G("commit", "-qm", "pin (repin: a bug in a script)")
        keep_rel = dict(project.RELEASE)
        try:     # today's (re-pinned) tables: tree-changed is the human's, env-unknown a rerun
            project.RELEASE["tree-changed"] = ("H", "human")
            project.RELEASE["env-unknown"] = ("I", "rerun")
            today = (cure_plan(c_, load(os.path.join(rd, STOPS, sA, "STOP.json"))),
                     cure_plan(c_, load(os.path.join(rd, STOPS, sB, "STOP.json"))))
            after = (strail(c_, sA), strail(c_, sB))
        finally:
            project.RELEASE.clear(); project.RELEASE.update(keep_rel)
        say("T34: after a re-pin whose tables would judge differently, the trail judges each earlier self-cure by the "
            "apparatus pinned at its close: a correct cure stays correct (no false 'human stop'), and a forged cure of "
            "a stop that was the human's then is still caught",
            "a self-cure, not" in mA and "human stop" in mB and not before[0]
            and any("human stop" in p for p in before[1]) and today == (None, ["rerun"])
            and not after[0] and any("human stop" in p for p in after[1]))
      except Refused as e:
        say(f"no unexpected refusal ({e})", False)
    finally:
        project.REPO, project.AUDITS, RUNNER = saved
        shutil.rmtree(base, ignore_errors=True)
    _pre_config_controls(say)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


def _pre_config_controls(say):
    """Integrated review fix 4: Stage 1 steps 0-1 (env-check, the Mathlib cache) fail before any config exists;
    release requires `stops.py open`, which needed a config. In the pre-config window (an intake saved, no config)
    open/close/list record a human stop beside the intake; --intake-move refuses while it is open and moves it under
    RUN_LOG.md's ## Stops."""
    import contextlib, io, shutil, subprocess, tempfile
    d = tempfile.mkdtemp(prefix="stops-preconfig-")
    keep = (project.REPO, project.PROJECTS)
    out = []
    try:
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        os.makedirs(os.path.join(d, "audits", "projects"))
        project.REPO, project.PROJECTS = d, os.path.join(d, "audits", "projects")

        def run(*argv):
            o = io.StringIO()
            with contextlib.redirect_stdout(o):
                rc = main(list(argv))
            return rc, o.getvalue()
        no_window = run("open", "--note", "x", "--cause", "env-unknown")
        os.makedirs(os.path.join(d, project.FW))
        open(project.intake_draft_path(), "w").write("intake-message sha256 x\n- 1a: paper.tex\n")
        wrong = run("open", "--note", "x", "--cause", "tool-call")
        o1 = run("open", "--note", "lake exe cache get: 403 from the cache server", "--cause", "env-unknown")
        o2 = run("open", "--note", "y", "--cause", "env-unknown")
        lst = run("list")
        cfg = {"name": "t", "rounds_dir": "audits/R"}
        os.makedirs(os.path.join(d, "audits", "R"))
        try:
            project.intake_move(cfg); moved_open = "moved"
        except ValueError as e:
            moved_open = str(e)
        c1 = run("close", "--stop", "P1", "--human", "fixed the proxy; go on")
        try:
            msg = project.intake_move(cfg)
        except ValueError as e:     # a fault of the path under test fails the check, never crashes the selftest
            msg = f"refused: {e}"
        lp = os.path.join(d, "audits", "R", "RUN_LOG.md")
        log = open(lp, encoding="utf-8").read() if os.path.exists(lp) else ""
        say("review fix 4: before the config exists (an intake saved) stops.py opens a human stop "
                       "(env-unknown) P1, one at a time, never a non-human cause; --intake-move refuses while it is "
                       "open and, once the human's answer closed it, moves it under ## Stops; with no saved intake "
                       "stops.py still says it has no project",
                       no_window[0] == 2 and wrong[0] == 1 and "only a human stop" in wrong[1]
                       and o1[0] == 0 and "opened P1" in o1[1] and o2[0] == 1 and "still open" in o2[1]
                       and "OPEN" in lst[1] and "pre-config stop is open" in moved_open and c1[0] == 0
                       and "pre-config stop(s) moved" in msg and "## Stops" in log
                       and "P1 (" in log and "fixed the proxy; go on" in log
                       and not os.path.exists(project.pre_config_path()))
    finally:
        project.REPO, project.PROJECTS = keep
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

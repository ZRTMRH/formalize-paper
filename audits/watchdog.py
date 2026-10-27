#!/usr/bin/env python3
"""Tell the person when a Codex run stops, and why (optional, experimental; NOTIFY-ONLY).

WHY.  In the Codex reference run (2026-10-18) the parent turn ended with "Selected model is at
capacity. Please try a different model." (`codex_error_info: server_overloaded`), and the run sat
idle for about 1 h 45 min until a person noticed and typed "resume". This script notices for
you. It NEVER types anything into the session: a development version of 0.2.0 tried resuming by
sending keys into the Codex terminal, and an adversarial test showed that keystroke injection into a live TUI cannot
be made safe (an approval overlay, a person's draft, a resized screen or a misread log turn the
keys into answers nobody gave). A future version may resume through Codex's app-server API.

  python3 audits/watchdog.py [--project DIR] [--session-log FILE] [--max-age-h 12]
                             [--poll 60] [--notify-cmd "CMD ARGS"] [--log FILE] [--once]
  python3 audits/watchdog.py --selftest

Start it in a second terminal, in the project, after the Codex session has started. It is a
Python program on purpose: a shell `until/while … sleep` loop in the project would be flagged (and
killed) by lanecheck.py's stray-loop scan.

WHAT IT WATCHES.  Exactly one session log, pinned at startup: --session-log FILE, or else the one
interactive (`source: cli`) session under `$CODEX_HOME/sessions/` whose cwd is the project and
which was written in the last --max-age-h hours. It refuses to start (exit 2) if there is none, or
more than one (then name the right one with --session-log), or if the given file is not a cli
session of this project. Children (`subagent` sessions) are never watched. It never reads the
terminal.

WHAT IT REPORTS.  Once per turn of the parent:
  - "stalled": the turn ended on a SERVICE error (capacity, overloaded, unavailable, internal
    server error, bad gateway, a dropped stream), and nothing in that turn needs a person. You
    can then type the suggested resume line (RESUME_TEXT) into the session yourself.
  - "needs a human: <reason>": anything else that ends or blocks a turn -- a STOP, FAIL, FAILED,
    FAIL(s), RED or PHASE 0: RED in a checker's output or in the agent's or a child's messages, a
    checker that exited non-zero, a usage or rate limit (429, too many requests, a reached rate
    limit), an approval request, any other error, or a normal turn end (a checkpoint, a question,
    the end of the run). It never reports "stalled" when any of these is present.
Command output in Codex logs is JSON inside strings, sometimes several objects per string, behind
a "Warning: truncated output" header, or cut off: every JSON object in a string is decoded, and a
truncated one is scanned as text with its escapes undone.

HOW IT NOTIFIES.  A line on its own terminal, the terminal bell, a JSON line in its log
(--log; default ~/.cache/formalize-paper/watchdog/<start time>.log, outside the project, so that it
cannot look like a lane write to tree_state.py), and, if --notify-cmd is given, that command run
with the notification text as ONE extra argument (no shell: the command line is split once, by
shlex, when it starts; text from the log is never part of a shell string). Example:
`--notify-cmd "notify-send formalize-paper"`, or a script that sends a phone notification.
"""
import sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
import argparse, datetime, glob, json, os, re, shlex, subprocess, time

SERVICE_INFO = {"server_overloaded", "internal_server_error", "service_unavailable",
                "response_stream_disconnected", "response_stream_failed", "http_connection_failed"}
SERVICE_RE = re.compile(r"at capacity|overloaded|temporarily unavailable|service unavailable|"
                        r"internal server error|bad gateway|gateway time-?out|"
                        r"stream disconnected|error sending request", re.I)
USAGE_RE = re.compile(r"usage limit|rate limit|quota|purchase more credits|upgrade to|"
                      r"hit your (?:usage|weekly|daily|limit)|\b429\b|too many requests", re.I)
# STOP/FAIL/RED at the start of a line, after any indentation, box drawing, bullets or quotes
LEAD = r"[\s\"'`>*|•·●◦■□▪▶►✗✘×\-_─━│┃└┗├┣╰╭╮╯┌┐┘┏┓┛]*"
# RED only as phase0 prints it (a result column "RED   <check>"), not prose such as "RED: commit first"
FAILWORD = r"(?:STOP\b|FAIL(?:ED|S|\(s\))?\b|RED[ \t]{2,}\S|PHASE 0(?: RESULT)?: RED\b)"
STOP_LINE_RE = re.compile(r"(?m)^" + LEAD + FAILWORD)
# anywhere in a line: what a checker prints when it fails, even piped through tail
FAIL_ANY_RE = re.compile(r"\b\d+ FAIL(?:ED|S|\(s\))?\b|\bFAILED\b|\bPHASE 0(?: RESULT)?: RED\b|^\s*RED[ \t]{2,}\S", re.M)
# in the agent's or a child's own words (a lane's "Decision: FAIL" is normal protocol flow, not a stop)
MSG_STOP_RE = re.compile(r"\bSTOP\b|\b\d+ FAIL(?:ED|S|\(s\))?\b|\bPHASE 0(?: RESULT)?: RED\b|"
                         r"(?i:\b(?:must|have to|had to|will|should|i'll|we'll) stop\b|\bstopped\b|\bstopping\b)")
EXITED_RE = re.compile(r"Process exited with code (-?\d+)")
CHECKER_RE = re.compile(r"audits/(?:integrity|tree_state|lanecheck|lane_auth|phase0|scope|decisions|"
                        r"make_report|readers|signoff|prompt|audit_coverage|check_index|axiom_sweep|"
                        r"fingerprint|unused_args|codex_spawn|codex_agents|project)\.py")
# checkers whose normal output is protocol prose (prompt.py prints the blocks): exit code only
PROSE_CHECKER_RE = re.compile(r"audits/(?:prompt|project)\.py")
RESUME_TEXT = ("The previous turn ended with a service error, not with a protocol stop or a question. "
               "Resume the run from audits/RUN.md and RUN_LOG.md at the current stage: keep every completed "
               "judgment; do not re-run or re-spawn any reviewer, adjudicator, reader or writer whose result "
               "is complete; collect each finished child's result and expected file and seal completed lanes "
               "from their own results; retry only children that failed mechanically, with their original "
               "messages, and log each retry (rule 7). If any check or child says to stop, stop there and "
               "show its raw output (rule 8).")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog_fixtures.json")

_DEC = json.JSONDecoder()


def _decode_all(s):
    """Every JSON object or array that starts a line of `s` (several per string, after a header),
    plus, for one that is cut off, its text with the JSON escapes undone."""
    out, i, n = [], 0, len(s)
    while i < n:
        j = s.find("{", i)
        k = s.find("[", i)
        j = min(x for x in (j, k) if x >= 0) if (j >= 0 or k >= 0) else -1
        if j < 0:
            break
        if j > 0 and s[j - 1] not in "\n\r\t \x00:,":
            i = j + 1
            continue
        try:
            obj, end = _DEC.raw_decode(s, j)
            out.append(obj)
            i = end
        except ValueError:
            rest = s[j:]
            if '\\n' in rest or '\\"' in rest:
                out.append(rest.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\'))
            i = j + 1
            # one undecodable object: everything after it is already in `rest`
            break
    return out


def _nodes(obj, depth=0):
    """Every value inside a log payload, with JSON held in strings decoded."""
    if depth > 12:
        return
    if isinstance(obj, str):
        yield obj
        if "{" in obj or "[" in obj:
            for d in _decode_all(obj):
                yield from _nodes(d, depth + 1)
    elif isinstance(obj, dict):
        yield obj
        for k, v in obj.items():
            if k not in ("id", "call_id", "type", "encrypted_content"):
                yield from _nodes(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _nodes(v, depth + 1)


def _text(obj):
    return "\n".join(n for n in _nodes(obj) if isinstance(n, str))


def tool_output_reason(output, call_text=""):
    """Why a tool output needs a person, or None: a STOP/FAIL/RED line; a checker script that
    exited non-zero or printed FAIL/RED anywhere (e.g. piped through tail)."""
    text = _text(output)
    m = STOP_LINE_RE.search(text)
    if m:
        return "tool output: " + text[m.start():m.start() + 100].strip().splitlines()[0]
    if CHECKER_RE.search(call_text or ""):
        m = None if PROSE_CHECKER_RE.search(call_text or "") and not re.search(
            r"audits/(?!prompt|project)\w+\.py", call_text or "") else FAIL_ANY_RE.search(text)
        if m:
            line = text[text.rfind("\n", 0, m.start()) + 1:].splitlines()[0]
            return "checker output: " + line.strip()[:100]
        codes = [n["exit_code"] for n in _nodes(output) if isinstance(n, dict) and isinstance(n.get("exit_code"), int)]
        codes += [int(c) for c in EXITED_RE.findall(text)]
        if any(c != 0 for c in codes):
            return "a checker exited with code " + str(next(c for c in codes if c != 0))
    return None


def message_reason(content):
    text = _text(content)
    m = STOP_LINE_RE.search(text) or MSG_STOP_RE.search(text)
    if m:
        line = text[text.rfind("\n", 0, m.start()) + 1:].splitlines()[0]
        return "message: " + line.strip()[:100]
    return None


def error_info(err):
    info = err.get("codex_error_info")
    if isinstance(info, dict):   # e.g. {"response_stream_disconnected": {"http_status_code": 502}}
        return next(iter(info)) if len(info) == 1 else ""
    return str(info or "")


def is_service_error(err):
    """Is a task_complete `error` a service error (and not a usage limit)?"""
    if not isinstance(err, dict):
        return False
    msg, info = str(err.get("message") or ""), error_info(err)
    if USAGE_RE.search(msg) or USAGE_RE.search(json.dumps(err)) or "usage" in info or "limit" in info:
        return False
    return info in SERVICE_INFO or bool(SERVICE_RE.search(msg))


def _limit_reached(p):
    for n in _nodes(p):
        if isinstance(n, dict) and (n.get("rate_limit_reached_type")
                                    or (isinstance(n.get("used_percent"), (int, float)) and n["used_percent"] >= 100)):
            return True
    return False


def analyse_session(lines):
    """The parent's last turn: {"state": "running" | "ended" | "empty", "turn", "error",
    "service": bool, "reasons": [why a person is needed], "last_message"}"""
    st = {"state": "empty", "turn": None, "error": "", "service": False, "reasons": [], "last_message": ""}
    calls = {}
    for l in lines:
        try:
            d = json.loads(l)
        except (ValueError, TypeError):
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        typ, ptyp = d.get("type"), p.get("type")
        if ptyp == "task_started" or typ == "turn_context" or (ptyp == "message" and p.get("role") == "user"):
            tid = p.get("turn_id") or st["turn"]
            if st["state"] != "running" or tid != st["turn"]:
                st.update(state="running", turn=tid, error="", service=False, reasons=[], last_message="")
            continue
        r = None
        if ptyp == "task_complete":
            st["state"], st["turn"] = "ended", p.get("turn_id") or st["turn"]
            err = p.get("error")
            msg = str(p.get("last_agent_message") or "")
            st["last_message"] = msg
            if err:
                st["error"] = str(err.get("message") if isinstance(err, dict) else err)[:200]
                st["service"] = is_service_error(err)
                if USAGE_RE.search(json.dumps(err)):
                    r = "usage or rate limit: " + st["error"]
                elif not st["service"]:
                    r = "error: " + st["error"]
            else:
                r = message_reason(msg) or ("the agent's turn ended (a checkpoint, a question or the end): "
                                            + (msg.strip().splitlines() or [""])[0][:100])
        elif ptyp in ("function_call", "custom_tool_call"):
            calls[p.get("call_id")] = _text(p.get("input") or p.get("arguments") or "")
        elif ptyp in ("function_call_output", "custom_tool_call_output"):
            r = tool_output_reason(p.get("output"), calls.get(p.get("call_id"), ""))
        elif ptyp == "agent_message" or (ptyp == "message" and p.get("role") == "assistant"):
            r = message_reason(p.get("content"))
        elif ptyp and "approval" in ptyp:
            r = "an approval was requested"
        elif ptyp == "token_count" and _limit_reached(p):
            r = "usage or rate limit reached"
        if r is None and typ == "event_msg" and ptyp != "token_count" and USAGE_RE.search(json.dumps(p)[:4000]):
            r = "usage or rate limit"
        if r:
            st["reasons"].append(r)
    return st


def classify(st):
    """(kind, reason) for an ended turn: ("stalled", error) or ("needs a human", reason); None
    while the turn runs."""
    if st["state"] != "ended":
        if st["reasons"] and any(x.startswith(("an approval", "usage")) for x in st["reasons"]):
            return "needs a human", st["reasons"][0]
        return None
    if st["service"] and not st["reasons"]:
        return "stalled", st["error"]
    return "needs a human", (st["reasons"] or ["the turn ended"])[0]


def sessions(codex_home, project_dir, now=None, max_age_h=12):
    """[(path, id)] of interactive (source: cli) sessions of the project written in the last
    max_age_h hours, newest first."""
    now, out = now or time.time(), []
    for f in glob.glob(os.path.join(codex_home, "sessions", "**", "rollout-*.jsonl"), recursive=True):
        try:
            m = os.path.getmtime(f)
            if now - m > max_age_h * 3600:
                continue
            meta = session_meta(f)
        except (OSError, ValueError):
            continue
        if meta and meta.get("source") == "cli" and \
                os.path.realpath(str(meta.get("cwd") or "")) == os.path.realpath(project_dir):
            out.append((m, f, meta.get("id")))
    return [(f, i) for _, f, i in sorted(out, reverse=True)]


def session_meta(f):
    with open(f, encoding="utf-8") as fh:
        d = json.loads(fh.readline())
    return d.get("payload") if d.get("type") == "session_meta" else None


def pin_session(codex_home, project_dir, given=None, max_age_h=12):
    """(path, id) of the one session to watch, or raise SystemExit-worthy ValueError."""
    if given:
        meta = session_meta(given)
        if not meta or meta.get("source") != "cli" or \
                os.path.realpath(str(meta.get("cwd") or "")) != os.path.realpath(project_dir):
            raise ValueError(f"{given} is not an interactive Codex session of {project_dir}")
        return given, meta.get("id")
    found = sessions(codex_home, project_dir, max_age_h=max_age_h)
    if not found:
        raise ValueError(f"no interactive Codex session of {project_dir} written in the last {max_age_h} h: "
                         "start Codex first, or name the log with --session-log")
    if len(found) > 1:
        raise ValueError("more than one recent Codex session of this project; name the one to watch with "
                         "--session-log:\n  " + "\n  ".join(f for f, _ in found))
    return found[0]


class Watchdog:
    """The decision logic, with every side effect injected (session lines, notify, log)."""

    def __init__(self, read_session, notify, log):
        self.read_session, self.notify, self.log = read_session, notify, log
        self.told, self.last_key = set(), None

    def step(self, now=None):
        """One poll. Returns the (kind, reason) notified, or None."""
        lines = self.read_session()
        if lines is None:
            if ("missing", None) not in self.told:
                self.told.add(("missing", None))
                self.notify("needs a human", "the pinned session log is gone", None)
                return "needs a human", "the pinned session log is gone"
            return None
        st = analyse_session(lines)
        c = classify(st)
        key = (st["state"], st["turn"], c)
        if key != self.last_key:
            self.log("state", state=st["state"], turn=st["turn"], verdict=list(c) if c else None,
                     reasons=st["reasons"][:5], error=st["error"])
            self.last_key = key
        if c is None:
            return None
        if (st["turn"], c[0]) in self.told:
            return None
        self.told.add((st["turn"], c[0]))
        self.notify(c[0], c[1], st["turn"])
        return c


def make_logger(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def log(event, **kw):
        rec = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "event": event, **kw}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return log


CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(text):
    """Log text without C0/C1 control characters (an escape sequence in a session log, e.g. OSC 52,
    must not reach the person's terminal or the --notify-cmd argument)."""
    return CONTROL_RE.sub("?", str(text))


def make_notifier(log, cmd_argv=None, out=sys.stdout):
    def notify(kind, reason, turn):
        text = clean(f"formalize-paper watchdog: {kind}: {reason}")
        if kind == "stalled":
            text += " -- to resume, type into the session: " + RESUME_TEXT
        out.write("\a" + text + "\n"); out.flush()
        log("notify", kind=kind, reason=reason, turn=turn)
        if cmd_argv:
            try:
                r = subprocess.run(cmd_argv + [text], capture_output=True, text=True, timeout=30)
                log("notify-cmd", argv=cmd_argv, returncode=r.returncode, stderr=r.stderr[-300:])
            except (OSError, subprocess.SubprocessError) as e:
                log("notify-cmd-failed", argv=cmd_argv, error=f"{type(e).__name__}: {e}")
    return notify


def selftest():
    bad = []

    def say(name, ok):
        if callable(ok):
            try:
                ok = bool(ok())
            except Exception as e:  # noqa: BLE001
                name, ok = f"{name} ({type(e).__name__}: {e})", False
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            bad.append(name)

    def ev(typ, **p):
        return json.dumps({"type": typ, "payload": p})

    fx = json.load(open(FIXTURES, encoding="utf-8"))
    META = json.dumps({"type": "session_meta", "payload": {"source": "cli", "cwd": "/p"}})
    T1 = [ev("event_msg", type="task_started", turn_id="t1"), ev("turn_context", turn_id="t1"),
          ev("response_item", type="message", role="user", content=[{"type": "input_text", "text": "go"}])]
    CAP = ev("event_msg", type="task_complete", turn_id="t1", last_agent_message=None,
             error={"message": "Selected model is at capacity. Please try a different model.",
                    "codex_error_info": "server_overloaded"})

    def call(cid, cmd):
        return ev("response_item", type="custom_tool_call", call_id=cid, name="exec",
                  input='text(await tools.exec_command({cmd:%s}));' % json.dumps(cmd))

    def out(cid, *texts):
        return ev("response_item", type="custom_tool_call_output", call_id=cid,
                  output=[{"type": "input_text", "text": "Script completed\nWall time 0.2 seconds\nOutput:\n"}]
                  + [{"type": "input_text", "text": t} for t in texts])

    def chunk(o, rc=0):
        return json.dumps({"chunk_id": "a", "exit_code": rc, "output": o})

    def verdict(lines):
        return classify(analyse_session(lines))

    base = [META] + T1
    say("a clean capacity stop is 'stalled'", verdict(base + [CAP]) == ("stalled", fx and
        "Selected model is at capacity. Please try a different model."))
    say("real event: the reference run's capacity stop is 'stalled'",
        lambda: verdict(base + [fx["capacity_stop"]])[0] == "stalled")
    say("real event: a child's integrity FAIL in a list_agents result -> needs a human",
        lambda: verdict(base + [fx["child_fail_list_agents"], fx["capacity_stop"]])[0] == "needs a human")
    say("real event: a JSON-wrapped FAIL command output -> needs a human",
        lambda: verdict(base + [fx["call_decisions_write"], fx["out_fail_json"], fx["capacity_stop"]])[0] == "needs a human")
    say("real event: a truncated multi-chunk output decodes into both chunks",
        lambda: sum(1 for n in _nodes(json.loads(fx["truncated_multichunk_out"])["payload"]["output"])
                    if isinstance(n, dict) and "chunk_id" in n) >= 2)
    say("real event: a truncated multi-chunk output by itself does not hold a stall",
        lambda: verdict(base + [fx["truncated_multichunk_out"], CAP])[0] == "stalled")
    planted = fx["truncated_multichunk_out"].replace('\\"output\\":\\"lakefile.toml',
                                                      '\\"output\\":\\"FAIL  lane check R\\\\nlakefile.toml')
    say("real event, FAIL planted in its last chunk: seen -> needs a human",
        lambda: planted != fx["truncated_multichunk_out"] and verdict(base + [planted, CAP])[0] == "needs a human")
    say("real event: a nested status/value truncated output decodes",
        lambda: any(isinstance(n, dict) and "chunk_id" in n
                    for n in _nodes(json.loads(fx["truncated_nested_status_out"])["payload"]["output"])))
    cut = "Warning: truncated output (original token count: 13412)\nTotal output lines: 2\n\n" + \
        chunk("ok a\n" * 50 + "FAIL  lane check R: token mismatch\n" + "ok b\n…3412 tokens truncated…\nok", 1)[:-1]
    say("a FAIL inside a JSON object that is cut off is seen",
        verdict(base + [call("c2", "python3 audits/lanecheck.py --round R"), out("c2", cut), CAP])[0] == "needs a human")
    two = chunk("ok  x\nFAIL  compiled bytecode present\nintegrity: 1 FAIL(s)\n", 1) + "\n" + chunk(" M x\n")
    say("a FAIL in the first of two JSON chunks in one string is seen",
        verdict(base + [call("c1", "python3 audits/integrity.py --check; git status"), out("c1", two), CAP])[0] == "needs a human")
    say("'integrity: 1 FAIL(s)' piped through tail (exit 0) -> needs a human",
        verdict(base + [call("c3", "python3 audits/integrity.py --check --round R | tail -1"),
                        out("c3", chunk("integrity: 1 FAIL(s)\n")), CAP])[0] == "needs a human")
    say("'PHASE 0: RED' piped -> needs a human",
        verdict(base + [call("c4", "python3 audits/phase0.py 2>&1 | tail -8"),
                        out("c4", chunk("  RED     integrity  [exit 1]\nPHASE 0: RED (1 check(s))\n")), CAP])[0] == "needs a human")
    say("'FAILED:' at a line start -> needs a human",
        verdict(base + [call("c5", "cat x"), out("c5", chunk("FAILED: lane correspondence seal missing\n")), CAP])[0] == "needs a human")
    fcall = ev("response_item", type="function_call", call_id="c6", name="exec_command",
               arguments=json.dumps({"cmd": "python3 audits/integrity.py --check"}))
    fout = ev("response_item", type="function_call_output", call_id="c6",
              output="Chunk ID: a\nWall time: 0.1 seconds\nProcess exited with code 1\nOutput:\nintegrity: 1 problem\n")
    say("a checker's 'Process exited with code 1' (plain-text output) -> needs a human",
        verdict(base + [fcall, fout, CAP])[0] == "needs a human")
    other = fout.replace("audits/integrity.py --check", "grep -c x notes.txt")
    say("... another command's non-zero exit alone does not",
        verdict(base + [fcall.replace("audits/integrity.py --check", "grep -c x notes.txt"),
                        other.replace("integrity: 1 problem", "0"), CAP])[0] == "stalled")
    wres = json.dumps({"status": {"/root/adj": {"completed": "Stopped at the first gate.\n\n```text\nFAIL  compiled bytecode present\n```"}}})
    say("a FAIL inside a wait_agent result -> needs a human",
        verdict(base + [ev("response_item", type="function_call", call_id="c7", name="wait_agent", arguments="{}"),
                        ev("response_item", type="function_call_output", call_id="c7", output=wres), CAP])[0] == "needs a human")
    amsg = ev("response_item", type="agent_message", content=[{"type": "input_text",
              "text": "Message Type: FINAL_ANSWER\nPayload:\nStopped at the first required gate.\n```text\nFAIL  compiled bytecode present\n```"}])
    say("a child's FINAL_ANSWER with FAIL lines and no word STOP -> needs a human",
        verdict(base + [amsg, CAP])[0] == "needs a human")
    say("a child's STOP arriving after the stall -> needs a human",
        verdict(base + [CAP, amsg.replace("Stopped at the first required gate.", "STOP (rule 8): integrity failed.")])[0]
        == "needs a human")
    cm = ev("response_item", type="message", role="assistant",
            content=[{"type": "output_text", "text": "integrity reported 1 FAIL(s); per rule 8 I must stop here."}])
    say("the parent's own message reporting a FAIL / 'must stop' -> needs a human", verdict(base + [cm, CAP])[0] == "needs a human")
    ck = ev("event_msg", type="task_complete", turn_id="t1", last_agent_message="Checkpoint B is ready. Approve?")
    say("a checkpoint (normal turn end) -> needs a human, never 'stalled'",
        lambda: verdict(base + [ck])[0] == "needs a human" and verdict(base + [ck])[1].startswith("the agent's turn ended"))
    say("box drawing or bullets before FAIL/STOP still count as a line start",
        verdict(base + [call("cb", "cat x"), out("cb", chunk("  └ FAIL  lane check\n")), CAP])[0] == "needs a human"
        and verdict(base + [call("cc", "cat x"), out("cc", chunk("│ STOP: integrity\n")), CAP])[0] == "needs a human")
    later = base + [stop_early := out("cd", chunk("FAIL  something\n")), ck,
                    ev("event_msg", type="task_started", turn_id="t2"), CAP.replace('"t1"', '"t2"')]
    say("a FAIL in an EARLIER turn does not hold a later stall", verdict(later)[0] == "stalled")
    catcap = [call("c8", "cat RUN_LOG.md"), out("c8", chunk("- 21:18 Selected model is at capacity; retried\n")),
              ev("event_msg", type="task_complete", turn_id="t1", last_agent_message="Done; the model was at capacity once.")]
    say("capacity quoted in a cat output, normal turn end -> not 'stalled'", verdict(base + catcap)[0] != "stalled")
    usage = CAP.replace("Selected model is at capacity. Please try a different model.", "You've hit your usage limit.") \
        .replace("server_overloaded", "usage_limit_exceeded")
    say("a usage limit -> needs a human", verdict(base + [usage]) == ("needs a human", "usage or rate limit: You've hit your usage limit."))
    tmr = CAP.replace("Selected model is at capacity. Please try a different model.",
                      "stream disconnected before completion: 429 Too Many Requests").replace("server_overloaded", "response_stream_disconnected")
    say("'429 Too Many Requests' as a stream disconnect -> needs a human, not 'stalled'", verdict(base + [tmr])[0] == "needs a human")
    rl = ev("event_msg", type="token_count", rate_limits={"primary": {"used_percent": 100.0}, "rate_limit_reached_type": "primary"})
    say("a reached rate limit in token_count -> needs a human", verdict(base + [rl, CAP])[0] == "needs a human")
    obj = CAP.replace('"codex_error_info": "server_overloaded"',
                      '"codex_error_info": {"response_stream_disconnected": {"http_status_code": 502}}') \
        .replace("Selected model is at capacity. Please try a different model.", "stream closed")
    say("codex_error_info as a one-key object is read by its key -> 'stalled'", verdict(base + [obj])[0] == "stalled")
    obj2 = obj.replace('{"http_status_code": 502}}', '{"http_status_code": 502}, "x": 1}')
    say("a multi-key info object with a neutral message -> needs a human", verdict(base + [obj2])[0] == "needs a human")
    say("a bare number is not a service error", not is_service_error({"message": "lemma_5_3 has 502 lines"}))
    say("a usage limit is not a service error, even in words that sound like one",
        not is_service_error({"message": "Rate limit reached: the model is overloaded for your plan; "
                              "try again in 2 hours", "codex_error_info": "usage_limit_exceeded"}))
    appr = ev("event_msg", type="exec_approval_request", call_id="x", command=["git", "commit"])
    say("an approval request while the turn runs -> needs a human", verdict(base + [appr]) == ("needs a human", "an approval was requested"))
    say("a running turn reports nothing", verdict(base) is None)
    lane_fail = ev("response_item", type="agent_message", content=[{"type": "input_text",
                   "text": "Message Type: FINAL_ANSWER\nPayload:\nDecision: FAIL. Counts: 11 Pass, 1 Fail."}])
    say("a lane's ordinary 'Decision: FAIL' verdict does not hold a stall (seen in the reference run)",
        verdict(base + [lane_fail, CAP])[0] == "stalled")
    prose = out("c9", chunk("RED: commit first, then run Phase 0).\nSTOPPING once the wrong place produced something\n"))
    say("protocol prose read in the turn ('RED: commit first', 'STOPPING once') does not hold a stall",
        verdict(base + [call("c9", "sed -n 1,80p audits/RUN.md"), prose, CAP])[0] == "stalled")
    say("the RESUME_TEXT suggestion keeps judgments and stops on stops",
        all(w in RESUME_TEXT for w in ("keep every completed judgment", "rule 7", "rule 8")))

    # notify once per turn and kind; a new stall in a new turn is told again
    told = []
    sess = base + [CAP]
    wd = Watchdog(lambda: list(sess), lambda k, r, t: told.append((k, t)), lambda e, **k: None)
    for _ in range(5):
        wd.step()
    sess += [ev("event_msg", type="task_started", turn_id="t2"), CAP.replace('"t1"', '"t2"')]
    for _ in range(3):
        wd.step()
    say("one notification per stalled turn", told == [("stalled", "t1"), ("stalled", "t2")])
    gone = []
    wdg = Watchdog(lambda: None, lambda k, r, t: gone.append(r), lambda e, **k: None)
    wdg.step(); wdg.step()
    say("a vanished session log is told once", gone == ["the pinned session log is gone"])

    # notifying: terminal line with bell, log, and --notify-cmd with the text as one argument
    import io, tempfile, shutil
    d = tempfile.mkdtemp(prefix="watchdog-")
    try:
        logs, buf = [], io.StringIO()
        argfile = os.path.join(d, "args.txt")
        cmd = [sys.executable, "-c", "import sys; open(sys.argv[1], 'w').write(repr(sys.argv[2:]))", argfile]
        n = make_notifier(lambda e, **k: logs.append((e, k)), cmd, out=buf)
        n("needs a human", "tool output: FAIL  x; $(rm -rf ~) `boom`", "t1")
        got = open(argfile).read() if os.path.exists(argfile) else ""
        say("notification: a bell and a line on the terminal", buf.getvalue().startswith("\aformalize-paper watchdog: needs a human"))
        say("--notify-cmd gets the text as ONE argument, never through a shell",
            got.startswith("['formalize-paper watchdog: needs a human: tool output: FAIL  x; $(rm -rf ~) `boom`']"))
        buf2, args2 = io.StringIO(), os.path.join(d, "args2.txt")
        n3 = make_notifier(lambda e, **k: None, [sys.executable, "-c",
                           "import sys; open(sys.argv[1], 'w').write(repr(sys.argv[2:]))", args2], out=buf2)
        n3("needs a human", "FAIL \x1b]52;c;ZXZpbA==\x07 and \x9b31m", "t1")
        got2 = open(args2).read() if os.path.exists(args2) else "\x1b"
        say("control characters (OSC 52, C1) never reach the terminal or --notify-cmd",
            "\x1b" not in buf2.getvalue() and "\x9b" not in buf2.getvalue() and "\\x1b" not in got2
            and "\\x9b" not in got2 and buf2.getvalue().startswith("\a"))
        say("every notification is logged", any(e == "notify" for e, _ in logs) and any(e == "notify-cmd" for e, _ in logs))
        n2 = make_notifier(lambda e, **k: logs.append((e, k)), [os.path.join(d, "no-such-cmd")], out=io.StringIO())
        say("a failing --notify-cmd is logged, not fatal",
            lambda: (n2("stalled", "x", "t1"), any(e == "notify-cmd-failed" for e, _ in logs))[1])
        # pinning: exactly one recent cli session of the project, never a subagent's
        day = os.path.join(d, "sessions", "2026", "10", "18"); os.makedirs(day)
        def mk(name, source, cwd, age):
            f = os.path.join(day, f"rollout-{name}.jsonl")
            open(f, "w").write(json.dumps({"type": "session_meta", "payload": {"source": source, "cwd": cwd, "id": name}}) + "\n")
            os.utime(f, (time.time() - age, time.time() - age))
            return f
        proj = os.path.join(d, "proj"); os.makedirs(proj)
        parent = mk("parent", "cli", proj, 100)
        mk("child", {"subagent": {"thread_spawn": {"parent_thread_id": "x"}}}, proj, 10)
        mk("other", "cli", "/elsewhere", 5)
        mk("stale", "cli", proj, 30 * 3600)
        say("pinned: the one recent cli session of the project (children, other projects, stale ones ignored)",
            lambda: pin_session(d, proj) == (parent, "parent"))
        mk("second", "cli", proj, 50)
        def refused(**kw):
            try:
                pin_session(d, proj, **kw)
            except ValueError:
                return True
            return False
        say("two recent cli sessions of the project: refused (name one with --session-log)", refused())
        say("--session-log of another project's session: refused", refused(given=os.path.join(day, "rollout-other.jsonl")))
        say("--session-log of a child session: refused", refused(given=os.path.join(day, "rollout-child.jsonl")))
        say("no recent session: refused", lambda: (lambda: (os.utime(parent, (0, 0)), os.utime(os.path.join(day, "rollout-second.jsonl"), (0, 0)), refused())[2])())
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # it never sends anything into a terminal
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    say("no code path sends keys or text into a terminal",
        all(w not in src.replace("say(\"no code path", "") for w in ("send-" + "keys", "paste-" + "buffer", "load-" + "buffer")))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import lanecheck
        say("lanecheck's stray-loop scan does not match the watchdog",
            lanecheck.LOOP_RE.search("python3 audits/watchdog.py --poll 60") is None)
    except ImportError:
        say("lanecheck's stray-loop scan does not match the watchdog (lanecheck.py importable)", False)
    print("selftest:", "ok" if not bad else f"FAILED ({len(bad)})")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=os.getcwd(), help="the project directory (default: cwd)")
    ap.add_argument("--session-log", help="the parent's rollout-*.jsonl (default: the one recent cli session of the project)")
    ap.add_argument("--max-age-h", type=float, default=12, help="ignore session logs not written for this long")
    ap.add_argument("--poll", type=int, default=60, help="seconds between checks")
    ap.add_argument("--notify-cmd", help="a command to run on each notification, with the text as one extra argument")
    ap.add_argument("--log")
    ap.add_argument("--once", action="store_true", help="one check, then exit")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    try:
        path, sid = pin_session(codex_home, a.project, a.session_log, a.max_age_h)
    except (ValueError, OSError) as e:
        print(f"watchdog.py: {e}", file=sys.stderr)
        return 2
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = make_logger(a.log or os.path.expanduser(f"~/.cache/formalize-paper/watchdog/{stamp}.log"))
    notify = make_notifier(log, shlex.split(a.notify_cmd) if a.notify_cmd else None)
    log("start", project=os.path.abspath(a.project), session_log=path, session_id=sid, notify_cmd=a.notify_cmd)
    print(f"watchdog: watching session {sid} ({path}); notify-only, it never types into the session", flush=True)

    def read_session():
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()

    wd = Watchdog(read_session, notify, log)
    while True:
        wd.step()
        if a.once:
            return 0
        time.sleep(a.poll)


if __name__ == "__main__":
    sys.exit(main())

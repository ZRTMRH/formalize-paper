#!/usr/bin/env python3
"""Run protocol subagents under the Codex CLI (experimental): one `codex exec` process per subagent.

Under Claude Code the operator spawns each subagent with the Agent tool and the one fixed sentence
`prompt.py … --write` prints (RUN.md, "Prompts pass through verbatim"). Under Codex the operator
runs this script with the same sentences instead:

  python3 audits/codex_spawn.py --kind auditor "<sentence>" ["<sentence>" ...] [--jobs N]
  python3 audits/codex_spawn.py --kind general "<sentence>"
  python3 audits/codex_spawn.py --selftest

WHY SEPARATE PROCESSES.  The protocol's guarantee is that a reviewer starts with only its prompt and
the files on disk. Codex's documentation does not say what context an in-session subagent sees,
so each subagent here is its own `codex exec` run: a fresh process with no conversation history.
Independence matters more than speed; `--jobs` runs several at once, each still its own process.

WHAT AN AUDITOR IS TOLD.  `--kind auditor` prepends the body of the INSTALLED reviewer definition,
`~/.claude/agents/auditor.md` (the file `integrity.py` pins), so the pin covers exactly what the
Codex reviewers were told. `install.sh --codex` installs it. `--kind general` sends the sentence
alone (adjudicator, fresh readers, sign-off writer, ...).

Each run's final message is saved to `<log dir>/<n>-<kind>.md` (default
`~/.cache/formalize-paper/codex/<timestamp>/`, outside the audit record); the subagent writes its
own record files, exactly as under Claude Code. Exit status: 0 only if every run exited 0, wrote a nonempty final message, and had no known sandbox startup error.
"""
import sys
sys.dont_write_bytecode = True
import argparse, concurrent.futures, datetime, os, re, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
AGENT_FILE = os.path.expanduser("~/.claude/agents/auditor.md")
SENTENCE_RE = re.compile(r"^Read the file (\S+) and carry out the task it describes, exactly\.")


def agent_body(path=AGENT_FILE):
    """The reviewer instructions without the Claude Code front matter."""
    text = open(path, encoding="utf-8").read()
    m = re.match(r"\A---\n.*?\n---\n", text, re.S)
    return text[m.end():] if m else text


def build_input(kind, sentence, agent_path=AGENT_FILE):
    if kind == "auditor":
        return (agent_body(agent_path).strip() + "\n\n---\n\nYour task:\n" + sentence.strip() + "\n")
    return sentence.strip() + "\n"


def command(log_file, model=None, codex="codex"):
    cmd = [codex, "exec", "--sandbox", "workspace-write", "--cd", REPO, "--skip-git-repo-check",
           '--config', 'model_reasoning_effort="medium"',
           "--output-last-message", log_file]
    if model:
        cmd += ["--model", model]
    return cmd + ["-"]


def check_sentence(s):
    """The sentence must be one prompt.py printed, naming a prompt file that exists."""
    m = SENTENCE_RE.match(s.strip())
    if not m:
        return "not a sentence printed by prompt.py (\"Read the file … and carry out the task …\")"
    if not os.path.isfile(m.group(1)):
        return f"the prompt file it names does not exist: {m.group(1)}"
    return None


def run_one(i, kind, sentence, log_dir, model, codex):
    log = os.path.join(log_dir, f"{i}-{kind}.md")
    # A reused log directory must never let a stale final message certify a failed run.
    if os.path.exists(log):
        os.unlink(log)
    r = subprocess.run(command(log, model, codex), input=build_input(kind, sentence),
                       capture_output=True, text=True)
    with open(os.path.join(log_dir, f"{i}-{kind}.stderr.txt"), "w", encoding="utf-8") as fh:
        fh.write(r.stderr)
    final_ok = os.path.isfile(log) and bool(open(log, encoding="utf-8").read().strip())
    startup_error = any(error in r.stderr + r.stdout for error in (
        "error building bubblewrap command", "failed to initialize in-process app-server client"))
    code = r.returncode or (0 if final_ok and not startup_error else 1)
    if code == 0 and kind == "auditor" and "lane_token is " in sentence:
        import lane_auth
        try:
            completions = re.findall(r'LANE_COMPLETION (\{[^\n]+\})', open(log, encoding="utf-8").read())
            if len(completions) != 1:
                raise ValueError("missing or ambiguous owner completion")
            done = __import__("json").loads(completions[0])
            prompt_file = SENTENCE_RE.match(sentence).group(1)
            expected = re.search(r'Write that JSON object, and nothing else, to (\S+\.json)', open(prompt_file).read()).group(1)
            if os.path.realpath(done["verdict"]) != os.path.realpath(expected):
                raise ValueError("child returned a different verdict path")
            lane_auth.seal(expected, done["sha256"], f"fallback-{i}")
        except (OSError, ValueError, KeyError, AttributeError) as e:
            with open(os.path.join(log_dir, f"{i}-{kind}.stderr.txt"), "a") as fh:
                fh.write(f"\nSTOP: lane completion/seal failed: {e}\n")
            code = 1
    return i, code, log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sentences", nargs="*")
    ap.add_argument("--kind", choices=["auditor", "general"])
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--model")
    ap.add_argument("--log-dir")
    ap.add_argument("--codex", default="codex", help="the codex executable")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.kind or not a.sentences:
        ap.error("give --kind and at least one sentence")
    bad = [(s, check_sentence(s)) for s in a.sentences]
    bad = [(s, e) for s, e in bad if e]
    for s, e in bad:
        print(f"REFUSED  {s[:80]}…: {e}")
    if bad:
        return 2
    if a.kind == "auditor" and not os.path.isfile(AGENT_FILE):
        print(f"REFUSED  {AGENT_FILE} is not installed (install.sh installs it; integrity.py pins it)")
        return 2
    if shutil.which(a.codex) is None:
        print(f"REFUSED  the Codex CLI ({a.codex}) is not on PATH")
        return 2
    log_dir = a.log_dir or os.path.expanduser(
        "~/.cache/formalize-paper/codex/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(log_dir, exist_ok=True)
    rc = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = [ex.submit(run_one, i, a.kind, s, log_dir, a.model, a.codex)
                for i, s in enumerate(a.sentences, 1)]
        for f in concurrent.futures.as_completed(futs):
            i, code, log = f.result()
            print(f"{'ok  ' if code == 0 else 'FAIL'}  subagent {i} ({a.kind}): exit {code}; final message in {log}")
            rc = rc or code
    return 1 if rc else 0


def selftest():
    res = []
    def say(name, ok):
        res.append(ok); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    d = tempfile.mkdtemp(prefix="codex-spawn-")
    try:
        ag = os.path.join(d, "auditor.md")
        open(ag, "w").write("---\nname: auditor\ntools: Read\n---\n\nYou are one audit lane.\n")
        pf = os.path.join(d, "lane.txt"); open(pf, "w").write("task")
        sent = f"Read the file {pf} and carry out the task it describes, exactly. That file is your whole task."
        inp = build_input("auditor", sent, ag)
        say("auditor input: the reviewer instructions without front matter, then the sentence",
            inp.startswith("You are one audit lane.") and "tools: Read" not in inp and inp.rstrip().endswith("whole task."))
        say("general input: the sentence alone", build_input("general", sent, ag) == sent + "\n")
        say("a sentence naming an existing prompt file is accepted", check_sentence(sent) is None)
        say("free text is refused (nothing typed by the operator reaches a reviewer)",
            check_sentence("Please review thm_1_1 carefully") is not None)
        say("a sentence naming a missing file is refused",
            check_sentence(sent.replace(pf, pf + ".gone")) is not None)
        cmd = command("/x/log.md")
        say("each subagent is a separate non-interactive codex exec, prompt on stdin, final message saved",
            cmd[:2] == ["codex", "exec"] and cmd[-1] == "-" and "--output-last-message" in cmd
            and cmd[cmd.index("--cd") + 1] == REPO)
        say("reviewers explicitly use medium reasoning",
            'model_reasoning_effort="medium"' in cmd)
        # a fake codex: records its stdin, writes the final message
        fake = os.path.join(d, "codex")
        open(fake, "w").write("#!/bin/sh\nwhile [ $# -gt 1 ]; do [ \"$1\" = --output-last-message ] && out=$2; shift; done\n"
                              "cat > \"$out.stdin\"; echo done > \"$out\"\n")
        os.chmod(fake, 0o755)
        logs = os.path.join(d, "logs")
        import io, contextlib
        global AGENT_FILE
        keep = AGENT_FILE; AGENT_FILE = ag
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--kind", "auditor", "--codex", fake, "--log-dir", logs, "--jobs", "2", sent, sent])
        finally:
            AGENT_FILE = keep
        got = sorted(os.listdir(logs)) if os.path.isdir(logs) else []
        say("two sentences run as two processes, each with its own log",
            rc == 0 and "1-auditor.md" in got and "2-auditor.md" in got
            and open(os.path.join(logs, "1-auditor.md.stdin")).read().startswith("You are one audit lane."))
        # Reuse logs to prove stale messages cannot mask failures. Exit 0 alone is insufficient.
        for label, body in [
            ("missing final", "cat >/dev/null\n"),
            ("empty final", 'cat >/dev/null; : > "$out"\n'),
            ("sandbox error with final", 'cat >/dev/null; echo blocked > "$out"; echo "error building bubblewrap command: app-server socket directory must be a user-owned directory with mode 0700" >&2\n'),
            ("app-server error", 'cat >/dev/null; echo "failed to initialize in-process app-server client: Read-only file system" >&2\n'),
            ("nonzero exit with final", 'cat >/dev/null; echo partial > "$out"; exit 7\n'),
        ]:
            open(fake, "w").write('#!/bin/sh\nwhile [ $# -gt 1 ]; do [ "$1" = --output-last-message ] && out=$2; shift; done\n' + body)
            open(os.path.join(logs, "1-general.md"), "w").write("stale success")
            with contextlib.redirect_stdout(io.StringIO()):
                failed = main(["--kind", "general", "--codex", fake, "--log-dir", logs, sent])
            say(label + " is a failure", failed == 1)
        with contextlib.redirect_stdout(io.StringIO()):
            rc2 = main(["--kind", "general", "--codex", fake, "--log-dir", logs, "free text"])
        say("a run with a refused sentence starts nothing (exit 2)", rc2 == 2)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Add the protocol's settings to a project's Claude Code settings, without clobbering anything.

WHAT AND WHY.  Two entries go into the PROJECT's `.claude/settings.json` (never the user's own
`~/.claude/settings.json`), so they are scoped to the formalization project:

1. `"env": {"PYTHONDONTWRITEBYTECODE": "1"}`. Claude Code runs every command with the environment
   in "env". A Python helper imported once without `-B` leaves `__pycache__/*.pyc` next to the
   pinned scripts; `integrity.py` then sees unpinned bytecode in the apparatus and the round STOPs
   (this happened in the Codex reference run, 2026-10-18). This is the Claude Code counterpart of
   Codex's `[shell_environment_policy.set]` (codex/README.md).
2. `"permissions": {"allow": [...]}`, the curated list ALLOW below: exactly the commands the
   agent runs (Lake in the project, each audit script by name, git status/add/commit in the project
   and in audits/). With it a run in Claude Code's normal permission mode does not stop to ask
   about each of them. Anything else still asks. It saves prompts; it is NOT a sandbox (INSTALL.md,
   "Permissions"). The protocol never needs `bypassPermissions` or
   `--dangerously-skip-permissions`; do not use them.

  claude_settings.py PATH              merge both into PATH
  claude_settings.py --dry-run PATH    only check that PATH can be merged and written (exit 1 if not)
  claude_settings.py --selftest

Rules: a missing file is created; every other key, env variable and allow rule is kept as it was
(key order too; our rules are appended); an existing different value of the variable is replaced
and reported. REFUSED (exit 1, file unchanged, a message saying what to fix): unparsable JSON,
comments (not allowed in settings.json), duplicate keys, NaN/Infinity, a top level, "env" or
"permissions" that is not an object, an "allow" that is not a list of strings, a file that is not
UTF-8 text, a file or directory we may not write. A symlinked settings.json is followed: its
target is updated, the link kept. An existing file that changes is backed up once as
PATH.before-formalize-paper, created exclusively and never through a symlink.
"""
import sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
import argparse, json, os, re, shutil, tempfile

KEY, VALUE = "PYTHONDONTWRITEBYTECODE", "1"
# Claude Code permission rules, so that a run in the normal (default) permission mode asks for
# nothing in normal operation, and no more is allowed than the run needs. Semantics relied on
# (https://code.claude.com/docs/en/permissions, checked 2026-10-19): in the default mode Bash
# commands and file edits prompt unless an allow rule matches; a built-in set of read-only
# commands (ls, cat, grep, find, diff, read-only git, ...) never prompts; `Bash(x *)`/`Bash(x:*)`
# matches `x` and `x …`, a rule without `*` one exact command; a compound command must match
# per subcommand; `Edit(...)` rules cover every file-editing tool (Write too; `Write(...)` rules are
# never consulted) and use gitignore patterns, with `/path` anchored at the project root in
# project settings; deny rules win over allow rules; project allow rules apply only after the
# person accepts the workspace-trust dialog. Every rule below is something RUN.md,
# AUDIT_PROTOCOL.md or the skill has the agent or a subagent run or write (checked 2026-10-19).
SCRIPTS = ["audit_coverage", "axiom_sweep", "decisions", "integrity", "lane_auth", "lanecheck",
           "phase0", "project", "prompt", "readers", "scope", "selftest_all", "signoff",
           "tree_state", "unused_args"]
# The files the agent and its subagents write by hand: Lean (formalizer, helpers, probes), the
# lakefile, the helpers' work_dir, the project config, and the records each role owns.
RECORD_FILES = ["RUN_LOG.md", "AUTHOR_NOTES.md", "DEVIATIONS.md", "OUTCOMES.md", "READER_NOTES.md",
                "DECISIONS.md", "PAPER_DEFECTS.md", "SKIPPED.md", "VACUOUS.md", "KNOWN_FAULTS-*.md",
                "QUESTIONS-B-*.md", "readers/*.response*.md"]
EDITS = (["Edit(/**/*.lean)", "Edit(/lakefile.toml)", "Edit(/lakefile.lean)", "Edit(/.formalization-work/**)",
          "Edit(/audits/projects/*.json)"]
         + [f"Edit(/audits/*/{f})" for f in RECORD_FILES]
         + ["Edit(/audits/*/20*/*.json)", "Edit(/audits/*/20*/ADOPTED.md)", "Edit(/audits/*/20*/*.probes/**)",
            "Edit(/audits/*/20*/revote/*.json)", "Edit(/audits/*/20*/OUTCOMES.md)"])
ALLOW = (["Bash(lake build:*)", "Bash(lake env lean:*)", "Bash(lake exe cache get)"]
         + [f"Bash(python3 audits/{n}.py:*)" for n in SCRIPTS]
         + ["Bash(git status:*)", "Bash(git rev-parse:*)", "Bash(git branch --show-current)",
            "Bash(git switch -c:*)", "Bash(git add:*)", "Bash(git commit:*)", "Bash(git fetch upstream)",
            "Bash(git -C audits status:*)", "Bash(git -C audits add:*)", "Bash(git -C audits commit:*)",
            "Bash(git -C audits mv:*)", "Bash(git -C audits checkout -- *)"]
         + EDITS)
# What nobody in a run may edit (RUN.md rule 4: the pinned apparatus), whatever else allows it,
# and Lake's package checkouts.
DENY = ["Edit(/audits/*.py)", "Edit(/audits/*.lean)", "Edit(/audits/*.md)", "Edit(/audits/*.json)", "Edit(/audits/*.sh)",
        "Edit(/audits/agents/**)", "Edit(/audits/skills/**)", "Edit(/audits/tests/**)", "Edit(/.lake/**)"]


class Refused(ValueError):
    pass


def _strict_object(pairs):
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise Refused(f"duplicate key(s) {', '.join(map(repr, dup))}: JSON readers disagree on which one counts; "
                      f"keep one")
    return dict(pairs)


def _no_constant(name):
    raise Refused(f"{name} is not valid JSON; remove it")


def parse(text):
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text, object_pairs_hook=_strict_object, parse_constant=_no_constant)
    except json.JSONDecodeError as e:
        if re.search(r"(?m)^\s*(?://|/\*|#)", text) or re.search(r",\s*//", text):
            raise Refused("comments are not allowed in settings.json (it is strict JSON); remove them")
        raise Refused(f"not valid JSON ({e.msg}, line {e.lineno} column {e.colno}); fix or "
                      f"remove it, or add \"env\": {{\"{KEY}\": \"{VALUE}\"}} by hand")
    if not isinstance(data, dict):
        raise Refused("the top-level JSON value is not an object; Claude Code settings are an object")
    return data


def merged(text):
    """Return (new_text, notes). new_text is None when nothing needs to change."""
    data = parse(text)
    env = data.get("env", {})
    if not isinstance(env, dict):
        raise Refused("its \"env\" is not an object; Claude Code expects \"env\": {\"NAME\": \"value\"}")
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        raise Refused("its \"permissions\" is not an object")
    allow = perms.get("allow", [])
    if not isinstance(allow, list) or not all(isinstance(r, str) for r in allow):
        raise Refused("its \"permissions.allow\" is not a list of strings")
    deny = perms.get("deny", [])
    if not isinstance(deny, list) or not all(isinstance(r, str) for r in deny):
        raise Refused("its \"permissions.deny\" is not a list of strings")
    notes = []
    if env.get(KEY) != VALUE:
        notes.append(f"replaced {KEY}={env[KEY]!r} with {VALUE!r}" if KEY in env else f"added {KEY}={VALUE}")
    missing = [r for r in ALLOW if r not in allow]
    if missing:
        notes.append(f"allowed {len(missing)} protocol command(s)")
    missing_deny = [r for r in DENY if r not in deny]
    if missing_deny:
        notes.append(f"denied edits to the pinned apparatus ({len(missing_deny)} rule(s))")
    if perms.get("defaultMode") == "bypassPermissions":
        notes.append("WARNING: permissions.defaultMode is bypassPermissions; the protocol must not run "
                     "that way (INSTALL.md, 'Permissions'); left unchanged, change it yourself")
    if not missing and not missing_deny and env.get(KEY) == VALUE:
        return None, notes or ["already set"]
    env = dict(env)
    env[KEY] = VALUE
    perms = dict(perms)
    perms["allow"] = list(allow) + missing
    perms["deny"] = list(deny) + missing_deny
    data = dict(data)
    data["env"] = env
    data["permissions"] = perms
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", notes


def _read(path):
    if not os.path.exists(path):
        return None
    if not os.path.isfile(path):
        raise Refused("it exists but is not a regular file")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        raise Refused("it is not UTF-8 text")
    except OSError as e:
        raise Refused(f"it cannot be read ({e.strerror})")


def _writable(path):
    """Refuse before writing anything: the file (if it exists) and its directory (or the nearest
    existing ancestor that would hold it) must be writable."""
    if os.path.exists(path) and not os.access(path, os.W_OK):
        raise Refused("it is read-only; make it writable or add the entries by hand")
    d = os.path.dirname(path)
    while not os.path.exists(d):
        d = os.path.dirname(d)
    if not os.access(d, os.W_OK | os.X_OK):
        raise Refused(f"{d} is not writable, so the file cannot be written there")


def apply(path, dry_run=False):
    path = os.path.realpath(path)          # a symlinked settings.json: update its target, keep the link
    text = _read(path)
    new, notes = merged(text)
    _writable(path)
    if new is None or dry_run:
        return notes
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    if text is not None:
        bak = path + ".before-formalize-paper"
        if not os.path.lexists(bak):       # an existing backup, or a (dangling) symlink there: leave it
            fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings.", suffix=".tmp")
    # mkstemp creates 0600; keep the existing file's mode, or the umask default for a new one
    um = os.umask(0); os.umask(um)
    os.chmod(tmp, os.stat(path).st_mode & 0o7777 if text is not None else 0o666 & ~um)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return notes


def selftest():
    bad = []
    def say(name, ok):
        # `ok` may be a callable: an exception inside it is a FAIL of that check, not a crash
        if callable(ok):
            try:
                ok = bool(ok())
            except Exception as e:  # noqa: BLE001
                name, ok = f"{name} ({type(e).__name__}: {e})", False
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            bad.append(name)
    def env_of(t):
        return json.loads(t)["env"]
    def refused(t, why=""):
        try:
            merged(t)
        except Refused as e:
            return why in str(e)
        return False

    t, _ = merged(None)
    say("missing file: created with the variable", lambda: env_of(t) == {KEY: VALUE})
    say("missing file: created with the protocol's allow list",
        lambda: json.loads(t)["permissions"]["allow"] == ALLOW and json.loads(t)["permissions"]["deny"] == DENY)
    t, _ = merged("")
    say("empty file: treated as {}", lambda: env_of(t) == {KEY: VALUE})
    src = json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm:*)"]}, "model": "x",
                      "env": {"FOO": "bar"}, "hooks": {}})
    t, note = merged(src)
    d = json.loads(t)
    say("other top-level keys kept", lambda: d.get("model") == "x" and d.get("hooks") == {})
    say("other permission rules kept, ours appended",
        lambda: d["permissions"]["allow"] == ["Bash(ls:*)"] + ALLOW and d["permissions"]["deny"] == ["Bash(rm:*)"] + DENY)
    say("other env variables kept", lambda: d["env"] == {"FOO": "bar", KEY: VALUE})
    say("key order kept", lambda: list(d) == ["permissions", "model", "env", "hooks"])
    t2, _ = merged(json.dumps({"model": "x"}))
    say("env added when absent, other keys kept",
        lambda: json.loads(t2) == {"model": "x", "env": {KEY: VALUE}, "permissions": {"allow": ALLOW, "deny": DENY}})
    say("idempotent: a second merge changes nothing", lambda: merged(t)[0] is None)
    say("a different value is replaced and reported",
        lambda: (lambda r: env_of(r[0])[KEY] == VALUE and "replaced" in r[1][0])(merged(json.dumps({"env": {KEY: "0"}}))))
    say("a rule already present is not added twice",
        lambda: json.loads(merged(json.dumps({"permissions": {"allow": [ALLOW[0]]}}))[0])["permissions"]["allow"].count(ALLOW[0]) == 1)
    here = os.path.dirname(os.path.abspath(__file__))
    say("the allow list names only scripts that exist, one by one, and no broad or file-writing rule",
        all(os.path.exists(os.path.join(here, n + ".py")) for n in SCRIPTS)
        and not any(r in ALLOW for r in ("Bash(python3 audits/:*)", "Bash(python3 -B audits/:*)",
                                         "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
                                         "Bash(xelatex:*)", "Bash(mkdir -p:*)"))
        and not any(r.endswith("audits/:*)") for r in ALLOW)
        and not any(r.startswith("Write(") for r in ALLOW + DENY))
    def glob_re(pat):  # gitignore semantics for anchored patterns: * within a segment, ** across
        out, i = "", 0
        while i < len(pat):
            if pat.startswith("**/", i):
                out += "(?:.*/)?"; i += 3
            elif pat.startswith("**", i):
                out += ".*"; i += 2
            elif pat[i] == "*":
                out += "[^/]*"; i += 1
            else:
                out += re.escape(pat[i]); i += 1
        return re.compile(out + r"\Z")
    def edit_allowed(path):
        def m(rule):
            return glob_re(rule[len("Edit(/"):-1]).match(path) is not None
        return any(m(r) for r in ALLOW if r.startswith("Edit(")) and not any(m(r) for r in DENY)
    say("the agent's own files are editable without a prompt (Lean, lakefile, work_dir, records, verdicts)",
        all(edit_allowed(p) for p in ("Paper/Basic.lean", "Paper.lean", "lakefile.toml",
                                       ".formalization-work/paper/Basic.lean", ".formalization-work/paper/PROGRESS",
                                       ".formalization-work/paper/BLOCKED", "audits/projects/paper.json",
                                       "audits/paper/RUN_LOG.md", "audits/paper/2026-10-19-abc1234/correspondence.json",
                                       "audits/paper/2026-10-19-abc1234/correspondence.probes/p.lean",
                                       "audits/paper/2026-10-19-abc1234/ADOPTED.md",
                                       "audits/paper/2026-10-19-abc1234/OUTCOMES.md",
                                       "audits/paper/readers/signoff-2026-10-19-abc1234-1.response.md",
                                       "audits/paper/readers/report-2.response-2.md",
                                       "audits/paper/QUESTIONS-B-2026-10-19-abc1234.md",
                                       ".formalization-work/scratch/correspondence-20261019T120000-1/p.lean")))
    say("deny rules cover the pinned apparatus and Lake's packages on their own (whatever else allows)",
        all(any(glob_re(r[len("Edit(/"):-1]).match(p) for r in DENY)
            for p in ("audits/integrity.py", "audits/AUDIT_PROTOCOL.md", "audits/fingerprint_tail.lean",
                      "audits/uni_math_extra.json", "audits/axiom_sweep.sh", "audits/agents/auditor.md",
                      "audits/skills/formalize-paper/SKILL.md", "audits/tests/mutants.py", ".lake/packages/x/X.lean")))
    say("the pinned apparatus and Lake's packages are not",
        not any(edit_allowed(p) for p in ("audits/integrity.py", "audits/AUDIT_PROTOCOL.md", "audits/RUN.md",
                                           "audits/agents/auditor.md", "audits/fingerprint_tail.lean",
                                           "audits/skills/formalize-paper/SKILL.md", ".lake/packages/mathlib/Mathlib/X.lean")))
    say("bypassPermissions is warned about, never set",
        lambda: any("bypassPermissions" in n for n in merged(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))[1]))
    say("unparsable JSON refused", refused('{"env": {"A": "b",}}', "not valid JSON"))
    say("a deny that is not a list of strings refused", refused('{"permissions": {"deny": "x"}}', "deny"))
    say("JSON with comments refused, saying comments are not allowed", refused('// mine\n{"env": {}}', "comments are not allowed"))
    say("duplicate keys refused", refused('{"env": {}, "env": {"A": "1"}}', "duplicate"))
    say("NaN refused", refused('{"x": NaN}', "NaN"))
    say("top-level array refused", refused("[1, 2]"))
    say("env that is not an object refused", refused('{"env": ["PYTHONDONTWRITEBYTECODE=1"]}'))
    say("permissions that are not an object refused", refused('{"permissions": ["Bash"]}'))
    say("an allow that is not a list of strings refused", refused('{"permissions": {"allow": "Bash(*)"}}'))

    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, ".claude", "settings.json")
        apply(p)
        um = os.umask(0); os.umask(um)
        say("new file gets the umask default mode, not 0600", os.stat(p).st_mode & 0o777 == 0o666 & ~um)
        say("file created with its directory", lambda: env_of(open(p).read()) == {KEY: VALUE}
            and not os.path.exists(p + ".before-formalize-paper"))
        orig = '{"model": "x"}'
        open(p, "w").write(orig)
        apply(p, dry_run=True)
        say("--dry-run writes nothing", open(p).read() == orig)
        apply(p)
        say("existing file backed up before the change",
            lambda: open(p + ".before-formalize-paper").read() == orig)
        say("existing file merged", lambda: json.loads(open(p).read())["env"] == {KEY: VALUE})
        broken = '{"model": '
        open(p, "w").write(broken)
        try:
            apply(p)
            say("unparsable file refused by apply", False)
        except Refused:
            say("unparsable file refused by apply", True)
        say("refused file left unchanged", open(p).read() == broken)
        r = __import__("subprocess").run([sys.executable, os.path.abspath(__file__), p],
                                         capture_output=True, text=True)
        say("CLI exits 1 with a clear message on unparsable JSON",
            r.returncode == 1 and "not valid JSON" in r.stderr and "unchanged" in r.stderr
            and "Traceback" not in r.stderr)
        # a symlinked settings.json: the target is updated, the link stays a link
        real = os.path.join(tmp, "shared-settings.json"); open(real, "w").write('{"model": "y"}')
        lp = os.path.join(tmp, "l", ".claude", "settings.json"); os.makedirs(os.path.dirname(lp))
        os.symlink(real, lp)
        apply(lp)
        say("a symlinked settings.json: target updated, link kept",
            lambda: os.path.islink(lp) and env_of(open(real).read()) == {KEY: VALUE})
        # a dangling symlink where the backup goes must not be written through
        q = os.path.join(tmp, "q", ".claude", "settings.json"); os.makedirs(os.path.dirname(q))
        open(q, "w").write('{"model": "z"}')
        outside = os.path.join(tmp, "outside-target.txt")
        os.symlink(outside, q + ".before-formalize-paper")
        say("a (dangling) symlink at the backup path is not written through, and is no error",
            lambda: apply(q) is not None and not os.path.exists(outside))
        # read-only file, unwritable directory, non-UTF-8, a directory: clean refusals
        ro = os.path.join(tmp, "ro", ".claude", "settings.json"); os.makedirs(os.path.dirname(ro))
        open(ro, "w").write("{}"); os.chmod(ro, 0o444)
        def refuses(path, why):
            try:
                apply(path, dry_run=True)
            except Refused as e:
                return why in str(e)
            return False
        if os.geteuid() != 0:
            say("a read-only settings.json is refused (dry run)", refuses(ro, "read-only"))
            nd = os.path.join(tmp, "nd"); os.makedirs(nd); os.chmod(nd, 0o555)
            say("an unwritable project directory is refused (dry run)", refuses(os.path.join(nd, ".claude", "settings.json"), "not writable"))
            os.chmod(nd, 0o755)
        bin_ = os.path.join(tmp, "bin", "settings.json"); os.makedirs(os.path.dirname(bin_))
        open(bin_, "wb").write(b"\xff\xfe{}")
        say("non-UTF-8 refused cleanly", refuses(bin_, "UTF-8"))
        dd = os.path.join(tmp, "dd", "settings.json"); os.makedirs(dd)
        say("a directory in its place refused cleanly", refuses(dd, "not a regular file"))
        os.chmod(ro, 0o644)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest:", "ok" if not bad else f"FAILED ({len(bad)})")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.path:
        ap.error("PATH required")
    try:
        notes = apply(a.path, dry_run=a.dry_run)
    except Refused as e:
        print(f"claude_settings.py: refusing to edit {a.path}: {e}. The file is unchanged.",
              file=sys.stderr)
        return 1
    for n in notes:
        if n.startswith("WARNING"):
            print(f"  {n}", file=sys.stderr)
    if not a.dry_run:
        print(f"  Claude Code: {a.path}: {'; '.join(n for n in notes if not n.startswith('WARNING'))} "
              f"(every command in this project runs with {KEY}={VALUE}; the protocol's commands are allowed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

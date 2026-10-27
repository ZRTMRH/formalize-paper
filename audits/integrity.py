#!/usr/bin/env python3
"""Has anyone changed the audit apparatus, or a record they do not own, since the run began?

WHY THIS EXISTS.  In one-conversation mode (RUN.md) the author of the Lean also launches the lanes
and has write access to everything: the scripts that judge its work, the protocol text the lane
prompts are cut from, the reviewer agent's definition, the project config that says what is in
scope, and the audit record itself (decisions, defects, skips, approvals). `tree_state.py` watches
the Lean repository and is blind to all of these. An author that weakened a check, or edited a
decision against its own work -- even with good intentions -- would leave no trace a reader could
find. This makes such changes visible, and fails on them.

THREAT MODEL.  A careless or over-helpful author, not a malicious one. Everything here lives in a
repository the author can write, so a determined forger can defeat it (by faking commit messages,
for instance). What it guarantees is that nobody changes these things BY ACCIDENT or in passing.

OWNERSHIP.  Each record in the rounds directory has one owner, identified by the commit message
prefix of every commit that touches it:
  scope <R>      TARGET.json, FINGERPRINTS.json, STATEMENTS_BUNDLE.md   (the launcher, via scripts)
  adjudicate <R> lane verdicts, revote/, ADOPTED.md, PAPER_DEFECTS.md, SKIPPED.md,
                 INFORMAL.json, SIGNOFF.json                            (the adjudicator)
  approve        APPROVED_FINGERPRINTS*.json                            (after the Checkpoint B approval)
  pin            TOOLING_PIN.json -- exactly one such commit
  adjudicate <R> also <round>/<lane>.probes/* -- the probes a lane's verdicts cite
  reader <key> <n>  readers/<key>-<n>.md (by the reader), <key>-<n>.response[-k].md and
                 KNOWN_FAULTS-<key>.md (by the operator) -- fresh readers (readers.py)
  adjudicate <R> also VACUOUS.md -- statements true only vacuously
Author-maintained and generated files (RUN_LOG.md, AUTHOR_NOTES.md, DEVIATIONS.md, OUTCOMES.md,
REPORT.*, SIGNOFF.md/.pdf/.tex rendered from SIGNOFF.json, DECISIONS.md written from
the skeleton decisions.py generates) may change at any time, in any commit.

  integrity.py --pin                 Checkpoint A: record the apparatus (<ROUNDS-DIR>/TOOLING_PIN.json)
  integrity.py --check --round R     step 4, first thing. Exit 1 on any FAIL.
  integrity.py --selftest
"""
import argparse, fnmatch, glob, hashlib, json, os, re, subprocess, sys, tempfile, shutil, datetime

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

PIN = "TOOLING_PIN.json"
TOOLING_GLOBS = ["*.py", "*.lean", "*.sh", "AUDIT_PROTOCOL.md", "RUN.md", "agents", "skills",
                 "tests", ".gitignore", ".gitattributes"]   # rules that could hide or rewrite a tool
# The tooling is the TOP level of audits/ plus those directories. A plain git pathspec "*.lean"
# also matches files deep inside a rounds directory -- the lanes' probe files -- and every round
# with a probe then read as "tooling changed since the pin" (found by the independent audit of
# batch B). ":(glob)" makes "*" stop at "/".
TOOLING_PATHSPECS = [f":(glob){g}" for g in TOOLING_GLOBS]


def is_tooling(path):
    """Same semantics as TOOLING_PATHSPECS, for a path relative to audits/."""
    return any(("/" not in path and fnmatch.fnmatch(path, g)) or path == g
               or path.startswith(g + "/") for g in TOOLING_GLOBS)
AGENT_FILE = os.path.expanduser("~/.claude/agents/auditor.md")
# Changing one of these changes WHAT is audited or HOW, so any change mid-run fails.
SCOPE_KEYS = ["name", "source_pdf", "branch", "base_commit", "namespace", "sweep", "rounds_dir",
              "lanes", "calibration", "goal", "goal_results", "index_file", "build_cmds",
              "confidential", "literature_hypotheses", "index_strict",
              # who decides after the intake (RUN.md, question 5c): changing it mid-run would let
              # the operator hand itself decisions the human kept
              "involvement", "involvement_answer"]


def scope_value(c, k):
    """A scope key's value for comparison. The involvement keys compare by meaning: a run pinned
    before they existed (no key) and a config that later states the default explicitly
    ("involved", answer "default") are the same run."""
    if k == "involvement":
        return project.involvement(c)
    if k == "involvement_answer":
        return c.get(k) or "default"
    return c.get(k)


# Keys that may only grow (an entry removed is a fail, an entry added is a note).
GROW_ONLY = ["lean_files", "standing_defers"]

AUTHOR_FILES = ["RUN_LOG.md", "AUTHOR_NOTES.md", "DEVIATIONS.md", "OUTCOMES.md", "REPORT.md",
                "REPORT.tex", "REPORT.pdf", "DECISIONS.md"]
OWNERS = [  # (pattern relative to the rounds dir, required commit-message prefix)
    # a lane's probe files are evidence its verdicts cite: written by the lane in the round under
    # review, committed by the adjudicator, never changed afterwards (an "implement" commit that
    # rewrote a probe would change the evidence behind an adopted finding). Listed FIRST: fnmatch's
    # "*" crosses "/", so a probe named e.g. TARGET.json would otherwise get the scope owner.
    ("*/.lane-auth/*", "scope "),
    ("*/.lane-seals/*", "seal "),
    ("*/.reissued/*", "scope "),     # a reissued lane's old verdict: evidence, never used (lane_auth.py)
    ("*/*.probes/*", "adjudicate "),
    # a fresh reader's report on a document a human will read (readers.py): written by the reader,
    # committed as "reader <doc> <n>", never edited (it records which version of the document passed)
    ("readers/*", "reader "),
    ("KNOWN_FAULTS-*.md", "reader "),     # the notice for findings marked unfixable (readers.py)
    ("*/TARGET.json", "scope "), ("*/FINGERPRINTS.json", "scope "),
    ("*/STATEMENTS_BUNDLE.md", "scope "),
    ("*/ADOPTED.md", "adjudicate "), ("*/revote/*", "adjudicate "),
    ("*/INFORMAL.json", "adjudicate "), ("*/SIGNOFF.json", "adjudicate "),
    # SIGNOFF.md/.pdf/.tex are rendered from SIGNOFF.json by signoff.py: generated, not owned
    ("*/*.json", "adjudicate "),          # lane verdicts (after the two scope-owned json above)
    ("PAPER_DEFECTS.md", "adjudicate "), ("SKIPPED.md", "adjudicate "), ("VACUOUS.md", "adjudicate "),
    ("APPROVED_FINGERPRINTS*.json", "approve"), (PIN, "pin"),
]


def owner(rel):
    """The required commit prefix for a path relative to the rounds dir, or None (author file)."""
    # Author-maintained files (AUTHOR_FILES) match no pattern below, so they have no owner.
    for pat, pre in OWNERS:
        if fnmatch.fnmatch(rel, pat):
            return pre
    return None


def git(repo, *a):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    return r.returncode, r.stdout


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.exists(path) else None


def disk_differs(repo, base):
    """Tooling files whose bytes on disk differ from (or are missing compared with) commit `base`,
    read directly -- independent of git's index flags and ignore rules."""
    # ls-tree does not take ":(glob)" pathspecs; list everything and classify with is_tooling
    rc, files = git(repo, "ls-tree", "-r", "--name-only", base)
    if rc != 0:
        return {f"(cannot list the pinned commit {base})"}
    bad = set()
    for f in files.splitlines():
        if not f.strip() or not is_tooling(f):
            continue
        p = os.path.join(repo, f)
        r = subprocess.run(["git", "-C", repo, "show", f"{base}:{f}"], capture_output=True)
        if not os.path.exists(p) or r.returncode != 0 or open(p, "rb").read() != r.stdout:
            bad.add(f)
    return bad


def tooling_dirty(repo):
    rc, out = git(repo, "status", "--porcelain", "--untracked-files=all", "--", *TOOLING_PATHSPECS)
    return [l for l in out.splitlines() if l.strip()]


def pin(audits, cfg, agent_file=AGENT_FILE, rounds_dir=None, repin=None, repo=None):
    """Write the pin. A second pin (`repin`) is allowed only with a stated reason: a genuine bug
    in the apparatus found mid-run. It is committed as "pin (repin: <reason>)" and listed in the
    report's trust section, so the human sees that the apparatus changed under the run."""
    dirty = tooling_dirty(audits)
    if dirty:
        return None, "uncommitted tooling changes; commit them before pinning:\n  " + "\n  ".join(dirty)
    repo_agent = os.path.join(audits, "agents", "auditor.md")
    if os.path.exists(repo_agent) and sha(repo_agent) != sha(agent_file):
        return None, (f"the installed reviewer agent {agent_file} differs from "
                      f"audits/agents/auditor.md; install the versioned copy before pinning")
    rc, head = git(audits, "rev-parse", "HEAD")
    doc = {"audits_commit": head.strip(), "date": datetime.date.today().isoformat(),
           "agent_sha256": sha(agent_file),
           "config": {k: cfg.get(k) for k in SCOPE_KEYS + GROW_ONLY}}
    if repo:
        import codex_agents
        try:
            roles = codex_agents.state(os.path.join(repo, ".codex", "agents"))
        except (OSError, ValueError) as e:
            return None, str(e)
        if roles is not None:
            doc["codex_agents"] = roles
    p = os.path.join(rounds_dir, PIN)
    if os.path.exists(p) and not repin:
        return None, f"{p} exists; a pin is set once per run (a re-pin needs --repin REASON)"
    if repin and not os.path.exists(p):
        return None, "nothing to re-pin: there is no pin yet"
    if repin:
        old = json.load(open(p))
        doc["repins"] = old.get("repins", []) + [{"date": doc["date"], "reason": repin,
                                                  "previous_commit": old["audits_commit"]}]
    os.makedirs(rounds_dir, exist_ok=True)
    json.dump(doc, open(p, "w"), indent=1)
    return p, None


def history(audits, rounds_rel):
    """[(subject, [paths relative to the rounds dir])] for every commit touching the rounds dir."""
    rc, out = git(audits, "log", "--format=@@%s", "--name-only", "--", rounds_rel)
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            cur = (line[2:], []); commits.append(cur)
        elif line.strip() and cur is not None:
            rel = os.path.relpath(line.strip(), rounds_rel)
            if not rel.startswith(".."):
                cur[1].append(rel)
    return commits


def check(audits, cfg, round_name, agent_file=AGENT_FILE, rounds_dir=None, rounds_rel=None,
          repo=None):
    """[(severity, message)] with severity 'FAIL' or 'note'."""
    out = []
    p = os.path.join(rounds_dir, PIN)
    if not os.path.exists(p):
        return [("FAIL", f"no {PIN}: the apparatus was never pinned (RUN.md Stage 1), so "
                         f"nothing can be compared")]
    doc = json.load(open(p))
    base = doc["audits_commit"]
    # 1. tooling: committed or not, nothing differs from the pinned commit
    rc, diff = git(audits, "diff", "--name-only", base, "--", *TOOLING_PATHSPECS)
    if rc != 0:
        out.append(("FAIL", f"cannot diff against pinned commit {base}"))
    changed = set(diff.splitlines()) | {l[3:] for l in tooling_dirty(audits)}
    # git's own view can be told to look away (an entry in .git/info/exclude, `update-index
    # --assume-unchanged` / --skip-worktree): compare the bytes on disk with the pinned commit
    # directly, and list ignored untracked tooling files (found by the audit of batch D)
    changed |= disk_differs(audits, base)
    rc_i, ign = git(audits, "ls-files", "-o", "-i", "--exclude-standard", "--", *TOOLING_PATHSPECS)
    changed |= {f for f in ign.splitlines() if f.strip() and "__pycache__" not in f}
    for f in sorted(changed):
        if f.strip():
            out.append(("FAIL", f"tooling changed since the pin: {f.strip()}"))
    # stale bytecode would run code that is not in any tracked file
    # only where it could shadow a tool: a lane that runs a probe script in its probe directory
    # leaves a __pycache__ there, which is evidence, not apparatus (found in round 2)
    pyc = [p for p in glob.glob(os.path.join(audits, "**", "*.pyc"), recursive=True)
           if is_tooling(os.path.relpath(p, audits))
           or os.path.dirname(os.path.dirname(os.path.relpath(p, audits))) in ("", "tests")]
    if pyc:
        out.append(("FAIL", f"compiled bytecode present ({os.path.relpath(pyc[0], audits)} …): "
                            f"delete every __pycache__ under audits/; the scripts never write one"))
    # 2. the reviewer agent: unchanged, and not overridden by a project-level copy
    repo_agent = os.path.join(audits, "agents", "auditor.md")
    if os.path.exists(repo_agent) and sha(repo_agent) != sha(agent_file):
        out.append(("FAIL", f"the installed reviewer agent {agent_file} differs from the versioned "
                            f"copy audits/agents/auditor.md; reinstall it (cp) and re-pin"))
    if sha(agent_file) != doc.get("agent_sha256"):
        out.append(("FAIL", f"reviewer agent definition changed or missing since the pin: {agent_file}"))
    if repo and os.path.exists(os.path.join(repo, ".claude", "agents", "auditor.md")):
        out.append(("FAIL", "a project-level .claude/agents/auditor.md overrides the pinned reviewer"))
    # Generated Codex roles are the actual instructions supplied to built-in children.
    if repo:
        import codex_agents
        try:
            roles = codex_agents.state(os.path.join(repo, ".codex", "agents"))
            if roles != doc.get("codex_agents"):
                out.append(("FAIL", "Codex role definitions changed, added or missing since the pin"))
        except (OSError, ValueError) as e:
            out.append(("FAIL", str(e)))
    # 3. config
    for k in SCOPE_KEYS:
        if scope_value(cfg, k) != scope_value(doc["config"], k):
            out.append(("FAIL", f"config key `{k}` changed since the pin: "
                                f"{doc['config'].get(k)!r} -> {cfg.get(k)!r}"))
    for k in GROW_ONLY:
        old, new = doc["config"].get(k) or [], cfg.get(k) or []
        key = (lambda x: json.dumps(x, sort_keys=True))
        gone = [x for x in old if key(x) not in {key(y) for y in new}]
        if gone:
            out.append(("FAIL", f"config key `{k}` lost entries since the pin: {gone[:3]}"))
        elif len(new) != len(old):
            out.append(("note", f"config key `{k}` grew by {len(new) - len(old)} since the pin"))
    # 4. ownership of committed records
    pin_subjects = []
    hist = history(audits, rounds_rel)
    # the run begins at the first pin: commits before it (a project's records imported, or kept
    # under an older protocol, before this run adopted the protocol) are not this run's to judge
    first_pin = max((i for i, (_, files) in enumerate(hist) if PIN in files), default=None)
    if first_pin is not None and first_pin + 1 < len(hist):
        out.append(("note", f"{len(hist) - first_pin - 1} commit(s) to the record before the first pin "
                            f"not checked: the run began at the pin"))
        hist = hist[:first_pin + 1]
    for subject, files in hist:
        for rel in files:
            need = owner(rel)
            if need == "pin":
                pin_subjects.append(subject)
            if need and not subject.startswith(need):
                out.append(("FAIL", f"{rel} was committed by \"{subject[:50]}\"; only a "
                                    f"\"{need.strip()} …\" commit may change it"))
    pin_subjects.reverse()   # git log is newest first
    if not pin_subjects or pin_subjects[0] != "pin":
        out.append(("FAIL", f"{PIN}: the first pin commit must be exactly \"pin\" "
                            f"(found {pin_subjects[:1]})"))
    for sj in pin_subjects[1:]:
        if not re.match(r"^pin \(repin: .+\)$", sj):
            out.append(("FAIL", f"{PIN} re-committed as \"{sj[:50]}\"; a re-pin must be "
                                f"\"pin (repin: <reason>)\" via integrity.py --pin --repin"))
    if len(pin_subjects) > 1:
        out.append(("note", f"the apparatus was re-pinned {len(pin_subjects) - 1} time(s) during this run"))
    # 5. uncommitted writes: author files anywhere at the top; protected records only inside
    #    the round under review (that is where lanes and the sign-off agents write)
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all", "--", rounds_rel)
    for line in st.splitlines():
        rel = os.path.relpath(line[3:].strip().strip('"'), rounds_rel)
        if owner(rel) is None:
            continue
        if round_name and rel.startswith(round_name + "/") and owner(rel) == "adjudicate ":
            continue
        hint = (" -- a lane's probe evidence: restore it (git checkout) or delete it if new; "
                "never commit it outside an adjudication" if ".probes/" in rel else "")
        out.append(("FAIL", f"uncommitted change to a protected record outside the round under "
                            f"review: {line.strip()}{hint}"))
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all")
    for line in st.splitlines():
        path = line[3:].strip().strip('"')
        if not path.startswith(rounds_rel + "/") and not path.startswith("projects/"):
            if not is_tooling(path):
                out.append(("note", f"uncommitted file in audits/: {path}"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--round")
    ap.add_argument("--repin", metavar="REASON", help="with --pin: re-pin, stating why")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    rd = os.path.join(project.REPO, cfg["rounds_dir"])
    rel = os.path.relpath(rd, project.AUDITS)
    if a.pin:
        p, err = pin(project.AUDITS, cfg, rounds_dir=rd, repin=a.repin, repo=project.REPO)
        if err:
            print(f"FAIL: {err}", file=sys.stderr); return 2
        msg = f"pin (repin: {a.repin})" if a.repin else "pin"
        print(f"pinned the audit apparatus: {os.path.relpath(p, project.REPO)}\n"
              f"now commit it, alone, with exactly this message: "
              f"git -C audits add {rel}/{PIN} && git -C audits commit -m \"{msg}\"")
        return 0
    if a.check:
        res = check(project.AUDITS, cfg, a.round, rounds_dir=rd, rounds_rel=rel, repo=project.REPO)
        for sev, m in res:
            print(f"{sev:5} {m}")
        fails = sum(1 for s, _ in res if s == "FAIL")
        print(f"integrity: {'OK' if not fails else f'{fails} FAIL(s)'}")
        return 1 if fails else 0
    ap.print_help()
    return 2


def selftest():
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    d = tempfile.mkdtemp()
    repo = tempfile.mkdtemp()
    try:
        def g(*a):
            subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)

        def commit(msg):
            g("add", "-A"); g("commit", "-qm", msg)

        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        os.makedirs(os.path.join(d, "projects")); os.makedirs(os.path.join(d, "P", "R1"))
        for f, t in (("phase0.py", "print('gate')\n"), ("AUDIT_PROTOCOL.md", "rules\n"),
                     ("RUN.md", "run\n"), ("tail.lean", "-- lean\n")):
            open(os.path.join(d, f), "w").write(t)
        os.makedirs(os.path.join(d, "agents")); open(os.path.join(d, "agents", "auditor.md"), "w").write("auditor\n")
        agent = os.path.join(d, "installed-agent.md"); open(agent, "w").write("auditor\n")
        cfg = {"name": "P", "namespace": "N", "lanes": ["correspondence"], "lean_files": ["a"],
               "build_cmds": ["lake build N"], "standing_defers": [{"id": "x"}],
               "rounds_dir": "P", "_path": os.path.join(d, "projects", "P.json")}
        json.dump({k: v for k, v in cfg.items() if k != "_path"}, open(cfg["_path"], "w"))
        commit("setup")
        # a project adopted mid-life: its records were committed before this run's pin
        open(os.path.join(d, "P", "SKIPPED.md"), "w").write("| # | what |\n|---|---|\n| 1 | Lemma 1 |\n")
        commit("legacy import")
        rd = os.path.join(d, "P")
        C = lambda c=cfg, r="R1": check(d, c, r, agent_file=agent, rounds_dir=rd, rounds_rel="P", repo=repo)
        fails = lambda res: [m for s, m in res if s == "FAIL"]

        say("check without a pin fails", fails(C()) and "never pinned" in fails(C())[0])
        open(os.path.join(d, "phase0.py"), "a").write("# dirty\n")
        say("pin refuses a dirty tooling tree", pin(d, cfg, agent_file=agent, rounds_dir=rd)[0] is None)
        g("checkout", "--", "phase0.py")
        p, err = pin(d, cfg, agent_file=agent, rounds_dir=rd)
        say("pin succeeds on a clean tree", p and not err)
        commit("pin")
        say("clean state passes", fails(C()) == [])
        say("record commits before the first pin are not judged, and the report says so",
            fails(C()) == [] and any("before the first pin" in m for s_, m in C() if s_ == "note"))
        open(os.path.join(d, "P", "SKIPPED.md"), "a").write("| 2 | Lemma 2 |\n"); commit("hand edit")
        say("a record edited by a non-adjudicate commit AFTER the pin still fails",
            any("SKIPPED.md was committed by" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        say("second pin refuses", pin(d, cfg, agent_file=agent, rounds_dir=rd)[0] is None)

        # lanes write in the round under review; the scope was committed by "scope"
        open(os.path.join(rd, "R1", "TARGET.json"), "w").write("{}"); commit("scope R1")
        open(os.path.join(rd, "R1", "correspondence.json"), "w").write("{}")
        say("a lane writing its verdict file in the round passes", fails(C()) == [])
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("log")
        open(os.path.join(rd, "AUTHOR_NOTES.md"), "w").write("notes")
        say("author-maintained files may be uncommitted", fails(C()) == [])
        # a lane's probes, including .lean/.py/.json and a file named like a protected record
        pd = os.path.join(rd, "R1", "non-vacuity@1.probes"); os.makedirs(pd)
        for f in ("witness.lean", "search.py", "out.json", "TARGET.json"):
            open(os.path.join(pd, f), "w").write("x\n")
        say("uncommitted lane probes (.lean/.py/.json) in the round pass", fails(C()) == [])
        commit("adjudicate R1")
        say("the adjudicator's commit of the round passes", fails(C()) == [])
        say("COMMITTED lane probes are not tooling", fails(C()) == [])
        open(os.path.join(pd, "witness.lean"), "a").write("more\n")
        say("an uncommitted change to an ADJUDICATED round's probe fails, saying what to do",
            any("witness.lean" in m and "probe evidence" in m for m in fails(C(r="R2"))))
        commit("implement R1")
        say("a probe rewritten by a non-adjudicate commit fails (evidence is frozen)",
            any("witness.lean" in m for m in fails(C())))
        # ownership is judged over the whole history, so a revert would not clear it; this
        # throwaway repo drops the commit instead
        g("reset", "-q", "--hard", "HEAD~1")
        say("without that commit it passes again", fails(C()) == [])
        # a fresh reader's report: committed as "reader <doc> <n>", never under another message
        os.makedirs(os.path.join(rd, "readers"))
        open(os.path.join(rd, "readers", "decisions-1.md"), "w").write("sha256: x\n")
        commit("reader decisions 1")
        say("a reader report committed as 'reader <doc> <n>' passes", fails(C()) == [])
        open(os.path.join(rd, "readers", "decisions-1.md"), "a").write("VERDICT: NO BLOCKING PROBLEMS\n")
        commit("implement R1")
        say("a reader report edited in another commit fails (it records which version passed)",
            any("decisions-1.md" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        open(os.path.join(rd, "KNOWN_FAULTS-decisions.md"), "w").write("- unfixable: x\n")
        commit("implement R1")
        say("a KNOWN_FAULTS notice committed outside a `reader` commit fails",
            any("KNOWN_FAULTS-decisions.md" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")

        # each tooling class
        for f in ("phase0.py", "tail.lean", "AUDIT_PROTOCOL.md", "RUN.md", "agents/auditor.md"):
            open(os.path.join(d, f), "a").write("# weakened\n")
            say(f"uncommitted edit to {f} fails", any("tooling changed" in m for m in fails(C())))
            commit("weaken")
            say(f"COMMITTED edit to {f} still fails", any("tooling changed" in m for m in fails(C())))
            g("revert", "--no-edit", "HEAD")
        open(os.path.join(d, ".gitignore"), "a").write("evil.py\n")
        open(os.path.join(d, "evil.py"), "w").write("def lenient(): return True\n")
        say("an ignore rule cannot hide a new tool", any("evil.py" in m for m in fails(C())))
        say("the .gitignore edit itself is reported (it is tooling)",
            any(m.endswith(": .gitignore") for m in fails(C())))
        os.remove(os.path.join(d, "evil.py")); os.remove(os.path.join(d, ".gitignore"))
        # routes around git's view: unversioned exclude file, and index flags
        open(os.path.join(d, ".git", "info", "exclude"), "a").write("sneaky.py\n")
        open(os.path.join(d, "sneaky.py"), "w").write("def lenient(): return True\n")
        say("a tool hidden by .git/info/exclude fails", any("sneaky.py" in m for m in fails(C())))
        os.remove(os.path.join(d, "sneaky.py"))
        g("update-index", "--assume-unchanged", "phase0.py")
        open(os.path.join(d, "phase0.py"), "a").write("# weakened behind assume-unchanged\n")
        say("an edit hidden by --assume-unchanged fails", any("phase0.py" in m for m in fails(C())))
        g("update-index", "--no-assume-unchanged", "phase0.py"); g("checkout", "--", "phase0.py")
        say("restored, it passes", fails(C()) == [])
        open(os.path.join(d, "helper.py"), "w").write("def lenient(): return True\n")
        say("a NEW untracked tooling file fails", any("helper.py" in m for m in fails(C())))
        os.remove(os.path.join(d, "helper.py"))
        os.makedirs(os.path.join(d, "__pycache__")); open(os.path.join(d, "__pycache__", "x.pyc"), "w").write("")
        say("stale bytecode fails", any("bytecode" in m for m in fails(C())))
        shutil.rmtree(os.path.join(d, "__pycache__"))
        os.makedirs(os.path.join(d, "tests", "__pycache__"))
        open(os.path.join(d, "tests", "__pycache__", "m.pyc"), "w").write("")
        say("stale bytecode next to the test scripts fails", any("bytecode" in m for m in fails(C())))
        shutil.rmtree(os.path.join(d, "tests"))
        pc = os.path.join(rd, "R1", "non-vacuity@1.probes", "__pycache__"); os.makedirs(pc)
        open(os.path.join(pc, "search.cpython-312.pyc"), "w").write("")
        say("bytecode left by a lane's probe script is not apparatus",
            not any("bytecode" in m for m in fails(C())))
        shutil.rmtree(pc)

        open(agent, "a").write("relaxed\n")
        say("agent definition edit fails", any("agent definition" in m for m in fails(C())))
        say("an installed agent that differs from audits/agents/auditor.md fails",
            any("differs from the versioned" in m for m in fails(C())))
        say("pin refuses while the installed agent differs from the versioned copy",
            pin(d, dict(cfg), agent_file=agent, rounds_dir=rd, repin="x")[0] is None)
        os.remove(agent)
        say("agent definition deleted fails", any("agent definition" in m for m in fails(C())))
        open(agent, "w").write("auditor\n")
        os.makedirs(os.path.join(repo, ".claude", "agents"))
        open(os.path.join(repo, ".claude", "agents", "auditor.md"), "w").write("x")
        say("a project-level agent override fails", any("overrides" in m for m in fails(C())))
        shutil.rmtree(os.path.join(repo, ".claude"))

        for k, v in (("lanes", []), ("namespace", "M"), ("build_cmds", ["true"]), ("confidential", True),
                     ("involvement", "hands-off")):
            say(f"scope key `{k}` change fails", any(f"`{k}`" in m for m in fails(C(dict(cfg, **{k: v})))))
        say("a pin without the involvement keys accepts the explicit default (involved, 'default')",
            not any("involvement" in m for m in fails(C(dict(cfg, involvement="involved", involvement_answer="default")))))
        say("lean_files shrinking fails", any("lean_files" in m for m in fails(C(dict(cfg, lean_files=[])))))
        say("standing_defers losing an entry fails",
            any("standing_defers" in m for m in fails(C(dict(cfg, standing_defers=[])))))
        res = C(dict(cfg, lean_files=["a", "b"]))
        say("lean_files growing is a note, not a fail",
            not fails(res) and any("lean_files" in m for s, m in res if s == "note"))

        # ownership of committed records
        with open(os.path.join(rd, "R1", "ADOPTED.md"), "w") as f:
            f.write("| l | i | Fail | **REJECT** | x |")
        commit("implement R1")
        say("an ADOPTED.md committed by the author fails",
            any("ADOPTED.md" in m and "adjudicate" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        open(os.path.join(rd, "SKIPPED.md"), "w").write("x"); commit("tidy")
        say("a SKIPPED.md committed by the author fails", any("SKIPPED.md" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w").write("{}"); commit("approve")
        say("an approval committed as 'approve' passes", fails(C()) == [])
        open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w").write('{"x":1}'); commit("fix approval")
        say("an approval rewritten in another commit fails", any("APPROVED" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        doc = json.load(open(os.path.join(rd, PIN)))
        doc["audits_commit"] = "deadbeef"; json.dump(doc, open(os.path.join(rd, PIN), "w"))
        commit("pin")
        say("a second plain pin commit (forgery) fails", any("re-pin must be" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        open(os.path.join(d, "phase0.py"), "a").write("# genuine fix\n"); commit("tooling fix")
        say("a tooling fix after the pin fails until re-pinned", any("tooling changed" in m for m in fails(C())))
        p2, e2 = pin(d, cfg, agent_file=agent, rounds_dir=rd, repin="phase0 bug found mid-run")
        commit("pin (repin: phase0 bug found mid-run)")
        res = C()
        say("a stated re-pin passes, and is reported", p2 and not fails(res)
            and any("re-pinned 1" in m for s, m in res if s == "note"))
        say("the re-pin's reason is recorded in the pin file",
            json.load(open(os.path.join(rd, PIN)))["repins"][0]["reason"] == "phase0 bug found mid-run")
        say("re-pin without an existing pin is refused",
            pin(d, cfg, agent_file=agent, rounds_dir=os.path.join(d, "nopin"), repin="x")[0] is None)
        g("reset", "-q", "--hard", "HEAD~2")
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write("x")
        say("an uncommitted protected record outside the round fails",
            any("protected record" in m for m in fails(C())))
        os.remove(os.path.join(rd, "PAPER_DEFECTS.md"))
        os.makedirs(os.path.join(rd, "R0"))
        open(os.path.join(rd, "R0", "correspondence.json"), "w").write("{}")
        say("a lane file written into ANOTHER round fails", any("protected record" in m for m in fails(C())))
        shutil.rmtree(os.path.join(rd, "R0"))
        say("everything restored passes again", fails(C()) == [])
        # the first pin must be committed as exactly "pin"
        d2 = tempfile.mkdtemp()
        try:
            def g2(*a):
                subprocess.run(["git", "-C", d2, *a], check=True, capture_output=True)
            g2("init", "-q"); g2("config", "user.email", "t@t"); g2("config", "user.name", "t")
            os.makedirs(os.path.join(d2, "P")); open(os.path.join(d2, "x.py"), "w").write("")
            g2("add", "-A"); g2("commit", "-qm", "setup")
            pin(d2, cfg, agent_file=agent, rounds_dir=os.path.join(d2, "P"))
            g2("add", "-A"); g2("commit", "-qm", "pin and some other things")
            r2 = check(d2, cfg, None, agent_file=agent, rounds_dir=os.path.join(d2, "P"),
                       rounds_rel="P", repo=repo)
            say("a first pin committed under another message fails",
                any("first pin commit" in m for s_, m in r2 if s_ == "FAIL"))
        finally:
            shutil.rmtree(d2, ignore_errors=True)
        # Actual Codex role bytes must be pinned, even when a changed model is otherwise canonical.
        import codex_agents
        d3 = tempfile.mkdtemp()
        try:
            g3 = lambda *a: git(d3, *a)
            g3("init", "-q"); g3("config", "user.email", "t@t"); g3("config", "user.name", "t")
            open(os.path.join(d3, "x.py"), "w").write("# fixture")
            g3("add", "-A"); g3("commit", "-qm", "setup")
            roles = os.path.join(repo, ".codex", "agents")
            codex_agents.install(roles)
            rdir = os.path.join(d3, "P")
            pin(d3, cfg, agent_file=agent, rounds_dir=rdir, repo=repo)
            g3("add", "-A"); g3("commit", "-qm", "pin")
            C3 = lambda: check(d3, cfg, None, agent_file=agent, rounds_dir=rdir, rounds_rel="P", repo=repo)
            say("generated Codex roles pass with pinned actual bytes", not fails(C3()))
            for name, body in codex_agents.generated(model="another-model").items():
                open(os.path.join(roles, name), "w").write(body)
            say("canonical Codex model change violates the pin",
                any("Codex role definitions changed" in m for m in fails(C3())))
            shutil.rmtree(os.path.join(repo, ".codex"))
            say("missing Codex roles violate the pin", any("Codex role definitions changed" in m for m in fails(C3())))
        finally:
            shutil.rmtree(d3, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(repo, ignore_errors=True)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

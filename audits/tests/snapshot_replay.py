#!/usr/bin/env python3
"""Scenario replay of real run snapshots under every run mode and involvement level (tier 2).

WHY THIS EXISTS.  A change meant for release mode must never alter dev mode (MAINTAINING.md, S3),
and a change must not move the stops a real run met. The selftests check functions on fixtures;
this replays the final state of real runs (the mini1..mini5 snapshots) through the read-only gates
with today's code, once per mode x level, and compares what each gate says -- its exit code and
the cause codes of the lines it printed -- with a baseline committed under replay_baseline/. Every
build step after B0 runs it: the dev rows must stay equal; a release row may change only where the
step says so, and then its baseline is re-recorded in the same commit (--record --modes release).

WHAT ONE REPLAY DOES (in a fresh directory under --work, never /tmp):
  1. copy the snapshot's project, preferring a FULL snapshot
     (<snapshots>/full-snapshots/<mini>/<project>/, with the project's .git and audits/.git; .lake
     is not copied), else the old one without git (<snapshots>/<mini>-snapshot/<project>/);
  2. replace its apparatus with this checkout's (the TOOLING files of integrity.py, the template);
  3. set the config's `mode` and `involvement` (a delegating level gets an involvement_answer), and
     the template's mode (the mode is the installation's: project.problems);
  4. git. FULL snapshot: the run's real history is kept untouched (both repositories, the stop
     trail, the run's own pin) and its uncommitted final state stays uncommitted; today's apparatus
     and the flipped config come in as the protocol's mid-run apparatus change does -- one commit
     outside the rounds dir ("replay: today's apparatus (<mode>, <level>)") and a re-pin
     ("pin (repin: snapshot replay -- ...)"), so every row carries NOTE[repinned]. OLD snapshot
     (no .git, only `git log` text): the audit record becomes one commit of everything but the
     pin, then a "pin" commit, then the stop record one commit per file with stops.py's subjects
     -- so history-based checks see a run that began at the pin; the project repository is one
     commit on the config's branch and the commit hashes the record cites do not resolve;
  4b. PATH REMAP (full snapshots only; remap_cmd). The record names files by the run machine's
     absolute path: lane metadata (.lane-auth/*.json "prompt"), prompts, verdicts, deliverables
     say /home/fp-claude/<project dir>/... (RECORDED_PARENT). The lane metadata is committed and
     lane_auth checks it against its first commit, so editing it would itself be tampering. No byte
     is rewritten instead: each gate runs in a private user+mount namespace (unshare) where an
     empty tmpfs hides RECORDED_PARENT and exactly <RECORDED_PARENT>/<project dir> is a bind mount
     of the copy; the gates run from there, as in the run. EXACTLY that one prefix is remapped:
     any other path under RECORDED_PARENT (a sibling project, the home itself) or elsewhere does
     not resolve and fails as before -- the selftest's remap control (and mutants RM1-RM7) holds
     this, so a real PROBLEM[auth-metadata] cannot be masked. Without unshare or RECORDED_PARENT
     a full snapshot is SKIPped (exit 0);
  5. run, with HOME set to a scratch home holding the versioned reviewer agent:
       integrity.py --check --round <newest round>
       lanecheck.py --round R             for every round
       phase0 --readonly                  in-process, with the Lean steps (build, axiom sweep,
                                          dependencies, freeze check, unused arguments) skipped
       make_report.py --check, decisions.py --check, readers.py --check (report, decisions, and
                                          the sign-off sheet of every round with a SIGNOFF.json)
       stops.py list
     and record, per gate, the exit code and the multiset of KIND[code] tags it printed
     (FAIL, RED, NOTE, WARNING, PROBLEM, PENDING, DISCLOSED, ...; an uncoded FAIL line counts as
     FAIL[uncoded], a traceback as CRASH).

  python3 -B audits/tests/snapshot_replay.py [--only mini1,...] [--modes dev,release] [--jobs N]
          [--snapshots DIR] [--work DIR] [--record] [--keep]
  python3 -B audits/tests/snapshot_replay.py --selftest
Without snapshots (another machine) it prints SKIP and exits 0: the replay is a maintainer's tool,
its snapshots are private run records. Exit 1 iff a replayed sequence differs from its baseline
(or a baseline is missing); --record writes the baselines instead.
"""
import os, sys
sys.dont_write_bytecode = True
import argparse, collections, concurrent.futures, glob, json, re, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS = os.path.dirname(HERE)
BASELINE_DIR = os.path.join(HERE, "replay_baseline")
SNAPSHOTS_ENV = "FORMALIZE_REPLAY_SNAPSHOTS"
DEFAULT_SNAPSHOTS = os.path.expanduser("~/formalization-work/release-test")
FULL_DIR = "full-snapshots"       # <snapshots>/full-snapshots/<mini>/<project>/ (with both .git)
RECORDED_PARENT = "/home/fp-claude"   # the run machine's home: lane metadata name /home/fp-claude/<project>/...
DEFAULT_WORK = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                            "formalize-paper", "replay")
MINIS = [f"mini{i}" for i in range(1, 6)]

def scratch_base():
    """The parent of the selftest's scratch directories: DEFAULT_WORK's parent, or the system temporary
    directory when that cannot be written (CODEX-PORT: inside Codex's workspace-write sandbox ~/.cache is
    read-only, and the selftest failed with "Read-only file system" in the run's own pre-pin check)."""
    base = os.path.dirname(DEFAULT_WORK)
    try:
        os.makedirs(base, exist_ok=True)
        shutil.rmtree(tempfile.mkdtemp(prefix="probe-", dir=base))
        return base
    except OSError:
        return None



MODES = ("release", "dev")          # project.MODES
LEVELS = ("involved", "statements-only", "hands-off")   # project.INVOLVEMENT_LEVELS
# the apparatus a replay installs from this checkout (integrity.TOOLING_GLOBS, plus the template)
TOOLING_FILES = re.compile(r"^(.*\.(py|lean|sh)|AUDIT_PROTOCOL\.md|RUN\.md|\.gitignore|\.gitattributes|"
                           r"project_template\.json)$")
TOOLING_DIRS = ("run", "agents", "skills", "tests")
# phase0 steps that need Lean: the replay skips them (the snapshots keep no .lake build)
LEAN_STEP = re.compile(r"axiom_sweep\.py|dependencies\.py|fingerprint\.py|unused_args\.py|\blake\b")
TAG = re.compile(r"\b(FAIL|RED|NOTE|WARNING|PROBLEM|PENDING|DISCLOSED|STOP|SKIPPED)\[([A-Za-z0-9_.:-]+)\]")
STOP_LINE = re.compile(r"^S\d+  \S+  \[([^\]]*)\]  .*  -> (.*?); ")
DISCLOSED_LINE = re.compile(r"^D\d+\b.*?  \[([^\]]*)\]  .*\(disclosed\)\s*$")
GIT_ENV = {"GIT_AUTHOR_NAME": "replay", "GIT_AUTHOR_EMAIL": "replay@example.invalid",
           "GIT_COMMITTER_NAME": "replay", "GIT_COMMITTER_EMAIL": "replay@example.invalid",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"}


# ---- pure parts (selftested) -------------------------------------------------------------------
def tags(out):
    """{KIND[code]: count} of one gate's output. An uncoded FAIL line is FAIL[uncoded] (project.py's
    fail-closed reading, S4); a Python traceback is CRASH."""
    c = collections.Counter()
    for line in out.splitlines():
        found = TAG.findall(line)
        for kind, code in found:
            c[f"{kind}[{code}]"] += 1
        if not found and re.match(r"\s*FAIL\b(?!\[)", line):
            c["FAIL[uncoded]"] += 1
        if line.startswith("Traceback (most recent call last)"):
            c["CRASH"] += 1
        m = STOP_LINE.match(line)      # stops.py list (do_list): a stop by its classes and who closed it
        if m:
            c[f"stop[{m.group(1)}]:{m.group(2).split(' (')[0].strip()}"] += 1
        m = DISCLOSED_LINE.match(line)
        if m:
            c[f"disclosed[{m.group(1)}]"] += 1
        if line.startswith("set-aside "):
            c["set-aside"] += 1
    return dict(sorted(c.items()))


def result(gate, rc, out):
    return {"gate": gate, "rc": rc, "tags": tags(out)}


def compare(base, now):
    """Differences between two {"<mode>/<level>": [result, ...]} maps: [str], empty iff equal."""
    diffs = []
    for key in sorted(set(base) | set(now)):
        b, n = base.get(key), now.get(key)
        if b is None or n is None:
            diffs.append(f"{key}: {'no baseline' if b is None else 'not replayed'}")
            continue
        bg, ng = {r["gate"]: r for r in b}, {r["gate"]: r for r in n}
        if [r["gate"] for r in b] != [r["gate"] for r in n]:
            diffs.append(f"{key}: gate sequence {[r['gate'] for r in b]} -> {[r['gate'] for r in n]}")
        for g in sorted(set(bg) & set(ng)):
            if bg[g]["rc"] != ng[g]["rc"]:
                diffs.append(f"{key}: {g}: exit {bg[g]['rc']} -> {ng[g]['rc']}")
            if bg[g]["tags"] != ng[g]["tags"]:
                diffs.append(f"{key}: {g}: {bg[g]['tags']} -> {ng[g]['tags']}")
    return diffs


def flip(cfg, template, pin, mode, level):
    """The config, template and pin of one replay: mode and level set everywhere they are read."""
    cfg = dict(cfg, mode=mode, involvement=level)
    if level == "involved":
        cfg.pop("involvement_answer", None)
    else:
        cfg["involvement_answer"] = cfg.get("involvement_answer") or f"({level}, set by the snapshot replay)"
    template = dict(template, mode=mode)
    pin = dict(pin, config=dict(pin.get("config") or {}))
    for k in ("mode", "involvement", "involvement_answer"):
        pin["config"][k] = cfg.get(k)
    return cfg, template, pin


def snapshot_project(snapshots, mini):
    """(project directory of a snapshot, full) or (None, False). A FULL snapshot
    (<snapshots>/full-snapshots/<mini>/<project>/, with the project's .git and audits/.git) is
    preferred: its real history is replayed. Otherwise the old snapshot without git
    (<snapshots>/<mini>-snapshot/<project>/), whose history is synthesized."""
    for pat, full in ((os.path.join(snapshots, FULL_DIR, mini, "*"), True),
                      (os.path.join(snapshots, f"{mini}-snapshot", "*"), False)):
        for d in sorted(glob.glob(pat)):
            if not glob.glob(os.path.join(d, "audits", "projects", "*.json")):
                continue
            if not full or (os.path.isdir(os.path.join(d, ".git")) and os.path.isdir(os.path.join(d, "audits", ".git"))):
                return d, full
    return None, False


def recorded_root(src, parent=None):
    """The absolute project path the run recorded (lane metadata, prompts, verdicts): the run
    machine's <RECORDED_PARENT>/<project dir>. The ONLY path a full replay remaps."""
    return os.path.join(parent or RECORDED_PARENT, os.path.basename(os.path.normpath(src)))


def remap_cmd(parent, root, copy, cmd, cwd=None):
    """`cmd` run so that the recorded project root `root` (under `parent`, the run machine's home)
    resolves to `copy`, and nothing else does: in a private user+mount namespace, an empty tmpfs
    hides `parent`, and only `root` inside it is a bind mount of the copy. No byte of the copy is
    changed (the committed lane metadata keeps the run's path, so its git checks still hold); any
    other path the record names -- a sibling project, the run's home, a path outside the parent --
    still does not resolve, and fails as it would have (selftest: the control)."""
    if hides_live(parent):
        raise RemapUnavailable(f"mounting over {parent} would hide the running install ({AUDITS})")
    return ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", REMAP_SH, "sh",
            parent, root, copy, cwd or root, *cmd]


REMAP_SH = 'set -e; mount -t tmpfs -o mode=755 replay "$1"; mkdir "$2"; mount --bind "$3" "$2"; cd "$4"; shift 4; exec "$@"'


def hides_live(parent, live=None):
    """True when an empty tmpfs over `parent` would hide the running install (`live`: this audits/):
    `parent` is the current user's home, or `live` is `parent` or under it (e.g. a trial run as the
    user fp-claude, whose own projects live under RECORDED_PARENT). The remap then never mounts."""
    rp = os.path.realpath(parent)
    lv = os.path.realpath(live or AUDITS)
    return rp == os.path.realpath(os.path.expanduser("~")) or lv == rp or lv.startswith(rp.rstrip(os.sep) + os.sep)


def remap_available(parent=None):
    parent = parent or RECORDED_PARENT
    if not os.path.isdir(parent) or not shutil.which("unshare") or hides_live(parent):
        return False
    r = subprocess.run(["unshare", "--user", "--map-root-user", "--mount", "sh", "-c",
                        'mount -t tmpfs none "$1"', "sh", parent], capture_output=True)
    return r.returncode == 0


def stop_trail(sdir):
    """[(path under stops/, commit subject)] in the order stops.py commits them: per stop S<n> (by
    number) its opening, its failed cure attempts, its close; then the disclosures and the repairs
    (stops.trail_problems checks each subject). A file it does not know keeps no commit of its own."""
    if not os.path.isdir(sdir):
        return []
    num = lambda s_: int(re.sub(r"\D", "", s_) or 0)
    out = []
    for s_ in sorted((d for d in os.listdir(sdir) if re.fullmatch(r"S[1-9]\d*", d)), key=num):
        fs = os.listdir(os.path.join(sdir, s_))
        if "STOP.json" in fs:
            out.append((f"{s_}/STOP.json", f"stop {s_} open"))
        for f in sorted((f for f in fs if re.fullmatch(r"CURE[1-9]\d*\.json", f)), key=num):
            out.append((f"{s_}/{f}", f"stop {s_} cure {num(f)}"))
        if "CLOSED.json" in fs:
            out.append((f"{s_}/CLOSED.json", f"stop {s_} close"))
    for sub, verb in (("disclosed", "disclose"), ("repairs", "repair")):
        d = os.path.join(sdir, sub)
        for f in sorted((f for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith(".json")), key=num):
            out.append((f"{sub}/{f}", f"stop {verb} {f[:-len('.json')]}"))
    return out


def lean_skip(cmd):
    return bool(LEAN_STEP.search(cmd))


# ---- one replay --------------------------------------------------------------------------------
def _git(cwd, *a, env=None):
    r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(a)} in {cwd}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


REMAP_VALIDATE = r"""
import json, sys
sys.path.insert(0, sys.argv[1]); import lane_auth
print(json.dumps([lane_auth.validate(v, require_seal=False) for v in sys.argv[2:]]))
"""


def remap_control(parent=None):
    """The control for remap_cmd: a fixture audit repository at <work>/proj (and an identical
    sibling <work>/proj-other) whose committed lane metadata names its prompt under the recorded
    root, under a sibling of it, directly under the run's home, and under a look-alike parent. Only
    the first may authenticate, and only through the remap; no byte of the copy may change."""
    import hashlib
    sha = lambda b: hashlib.sha256(b).hexdigest()
    parent = parent or RECORDED_PARENT
    w = tempfile.mkdtemp(prefix="remap-control-", dir=scratch_base())
    try:
        env = dict(os.environ, **GIT_ENV, GIT_CONFIG_NOSYSTEM="1")
        name = "proj"
        root = recorded_root(os.path.join(w, name), parent)
        cases = {"recorded": root, "sibling": os.path.join(parent, name + "-other"), "home": parent,
                 "elsewhere": os.path.join(parent + "-other", name)}
        for proj in (name, name + "-other"):
            aud = os.path.join(w, proj, "audits")
            rd = os.path.join(aud, "rounds", "R")
            os.makedirs(os.path.join(rd, "prompts")); os.makedirs(os.path.join(rd, ".lane-auth"))
            _git(aud, "init", "-q", env=env)
            prompt = b"the lane prompt\n"
            open(os.path.join(rd, "prompts", "x.txt"), "wb").write(prompt)
            for lane, (case, r_) in zip(("correspondence", "non-vacuity", "substantiveness", "prior-art"), cases.items()):
                tok = lane + "-token"
                json.dump({"verdict": lane + ".json", "token_sha256": sha(tok.encode()),
                           "prompt": os.path.join(r_, "audits", "rounds", "R", "prompts", "x.txt"),
                           "prompt_sha256": sha(prompt)},
                          open(os.path.join(rd, ".lane-auth", lane + ".json"), "w"), sort_keys=True, indent=2)
                json.dump({"lane_token": tok}, open(os.path.join(rd, lane + ".json"), "w"))
            _git(aud, "add", "-A", env=env)
            _git(aud, "commit", "-q", "-m", "scope R (lane tokens)", env=env)
        lanes = ("correspondence", "non-vacuity", "substantiveness", "prior-art")
        digest = lambda: hashlib.sha256(b"".join(open(os.path.join(dp, f), "rb").read()
                                                 for dp, _, fs in sorted(os.walk(os.path.join(w, name)))
                                                 for f in sorted(fs))).hexdigest()
        before = digest()
        argv = [sys.executable, "-B", "-c", REMAP_VALIDATE, AUDITS]

        def run(cmd):
            r = subprocess.run(cmd, capture_output=True, text=True, env=env)
            return json.loads(r.stdout) if r.returncode == 0 else None
        inside = run(remap_cmd(parent, root, os.path.join(w, name),
                               argv + [os.path.join(root, "audits", "rounds", "R", l + ".json") for l in lanes]))
        outside = run(argv + [os.path.join(w, name, "audits", "rounds", "R", l + ".json") for l in lanes])
        code = lambda probs: [p_.split("]")[0] + "]" for p_ in probs]
        if os.environ.get("REPLAY_DEBUG"):
            print(inside, outside)
        return (inside is not None and outside is not None
                and inside[0] == [] and all(code(p_) == ["[auth-metadata]"] for p_ in inside[1:])
                and all(code(p_) == ["[auth-metadata]"] for p_ in outside)
                and digest() == before)
    finally:
        shutil.rmtree(w, ignore_errors=True)


REMAP_INSIDE = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1]); import snapshot_replay as s
s.RECORDED_PARENT = sys.argv[2]
try:
    s.remap_cmd(s.RECORDED_PARENT, s.recorded_root("/x/p", s.RECORDED_PARENT), "/x/p", ["true"])
    refused = False
except s.RemapUnavailable:
    refused = True
print(json.dumps([s.remap_available(), refused, s.remap_control(sys.argv[3])]))
"""


def remap_from_inside(scratch):
    """The remap run from an install located under the mounted prefix: a copy of this audits/ at
    <scratch>/home/proj/audits, whose RECORDED_PARENT is <scratch>/home (the user fp-claude running a
    project under /home/fp-claude). The replay's remap must refuse (it would hide that install), and the
    selftest's remap control, over another scratch parent, must still pass from there."""
    home = os.path.join(scratch, "home")
    inst = os.path.join(home, "proj", "audits")
    shutil.copytree(AUDITS, inst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    other = os.path.join(scratch, "other-parent")
    os.makedirs(other)
    r = subprocess.run([sys.executable, "-B", "-c", REMAP_INSIDE, os.path.join(inst, "tests"), home, other],
                       capture_output=True, text=True, cwd=os.path.join(home, "proj"))
    if os.environ.get("REPLAY_DEBUG"):
        print(r.stdout, r.stderr)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]) == [False, True, True]
    except (ValueError, IndexError):
        return False


def _install_tooling(dst_audits):
    for n in os.listdir(dst_audits):
        p = os.path.join(dst_audits, n)
        if (os.path.isfile(p) and TOOLING_FILES.match(n)) or (os.path.isdir(p) and n in TOOLING_DIRS + ("__pycache__",)):
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    for n in os.listdir(AUDITS):
        p = os.path.join(AUDITS, n)
        if os.path.isfile(p) and TOOLING_FILES.match(n):
            shutil.copy2(p, os.path.join(dst_audits, n))
        elif os.path.isdir(p) and n in TOOLING_DIRS:
            shutil.copytree(p, os.path.join(dst_audits, n), ignore=ign)


# Run inside the copy (its own audits/ on sys.path): write the pin, then the phase0 gate.
PIN_DRIVER = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1]); import integrity, project, codex_agents
p, cfg = sys.argv[2], json.load(open(sys.argv[3]))
doc = json.load(open(p))
doc["audits_commit"] = sys.argv[4]
doc["agent_sha256"] = integrity.sha(integrity.AGENT_FILE)
roles = codex_agents.state(os.path.join(project.REPO, ".codex", "agents"))
if roles is not None: doc["codex_agents"] = roles
else: doc.pop("codex_agents", None)
json.dump(doc, open(p, "w"), indent=1)
"""
# Forgery review M2: the run's mode and involvement level are its FIRST committed pin's (integrity: FAIL[pin] for
# any later change). A replay under another mode or level therefore replays the run as if it had been pinned so:
# every committed version of the pin gets the flipped terms (git filter-branch on a bare clone of the audits
# repository, fetched back; the working tree, with the snapshot's uncommitted final state, is kept), never a
# mid-run flip, which the check now refuses as the forgery it is.
PIN_REWRITE = r"""
import json, subprocess, sys
rel, terms = sys.argv[1], json.loads(sys.argv[2])
ls = subprocess.run(["git", "ls-files", "-s", "--", rel], capture_output=True, text=True).stdout.split()
if ls:
    doc = json.loads(subprocess.run(["git", "cat-file", "blob", ls[1]], capture_output=True, text=True).stdout)
    doc.setdefault("config", {}).update(terms)
    sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=json.dumps(doc, indent=1), capture_output=True,
                         text=True).stdout.strip()
    subprocess.run(["git", "update-index", "--cacheinfo", f"{ls[0]},{sha},{rel}"], check=True)
"""


def rewrite_pin_history(aud, pin_rel, terms, root, env):
    """Give every committed version of the pin at `pin_rel` the intake `terms` (mode, involvement, answer)."""
    bare = os.path.join(root, "pin-rewrite.git")
    script = os.path.join(root, "pin_rewrite.py")
    open(script, "w").write(PIN_REWRITE)
    _git(root, "clone", "-q", "--bare", aud, bare, env=env)
    cmd = f"{sys.executable} -B {script} {pin_rel} '{json.dumps(terms)}'"
    r = subprocess.run(["git", "-C", bare, "filter-branch", "-f", "--index-filter", cmd, "--", "--all"],
                       capture_output=True, text=True, env=dict(env, FILTER_BRANCH_SQUELCH_WARNING="1"))
    if r.returncode:
        raise RuntimeError(f"pin history rewrite: {(r.stdout + r.stderr)[-600:]}")
    _git(aud, "fetch", "-q", "--update-head-ok", bare, "+refs/heads/*:refs/heads/*", env=env)
    _git(aud, "reset", "-q", env=env)
    shutil.rmtree(bare, ignore_errors=True)


PHASE0_DRIVER = r"""
import re, subprocess, sys
sys.path.insert(0, sys.argv[1]); import phase0, project
cfg = project.select(sys.argv[2])[0]
LEAN = re.compile(sys.argv[3])
def runner(cmd):
    if LEAN.search(cmd):
        return 0, "SKIP (snapshot replay: Lean is not run)\n"
    r = subprocess.run(cmd, shell=True, cwd=project.REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode, r.stdout
br = subprocess.run(["git", "-C", project.REPO, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
sys.exit(phase0.verdict(phase0.gate(cfg, True, False, br, runner=runner)))
"""


def _tooling_names(aud):
    """Top-level names in audits/ that are apparatus (on disk or tracked): what an install replaces."""
    tracked = {l.split("/")[0] for l in _git(aud, "ls-files").splitlines() if l}
    return sorted(n for n in tracked | set(os.listdir(aud))
                  if TOOLING_FILES.match(n) or n in TOOLING_DIRS)


def closer_codes():
    """{gate name prefix: [cause codes]}: release codes whose closer (project.CLOSER) is a gate the replay
    runs, one per kind and class; "@check" codes (and an uncoded one) are closed with the integrity gate."""
    sys.path.insert(0, AUDITS)
    import project
    by = {"integrity.py --check": "integrity --check", "lanecheck.py --round {R}": "lanecheck",
          "phase0.py --readonly": "phase0 --readonly", "make_report.py --check": "make_report --check",
          "decisions.py --check": "decisions --check", "readers.py --doc report --check": "readers --check report",
          "@check": "integrity --check"}
    out, seen = collections.defaultdict(list), set()
    for c in sorted(project.RELEASE) + ["no-such-code"]:
        g = by.get(project.CLOSER.get(c, "@check"))
        # one code per (gate, kind, class): a check sees an open stop's record, not its code (the
        # in-process L1 of stops.py runs every code), and each takes a full gate run (~1 s)
        if project.release_kind(c) not in ("human", "disclose") and g and (g, project.RELEASE.get(c)) not in seen:
            seen.add((g, project.RELEASE.get(c)))
            out[g].append(c)
    return dict(out)


def replay_one(src, work, mode, level, keep=False, full=False, parent=None, closers=None):
    """... `closers` (a list, release rows): L1 closer control, appended to it as (row, code, gate, rc)."""
    """[result] for one snapshot project under one mode and level. `full`: the snapshot keeps both
    git repositories; its real history is kept and the gates run with the recorded project root
    remapped to the copy (remap_cmd)."""
    os.makedirs(work, exist_ok=True)
    root = tempfile.mkdtemp(prefix=f"{os.path.basename(src)}-{mode}-{level}-", dir=work)
    try:
        proj = os.path.join(root, "p")
        skip = (".lake", "__pycache__") + (() if full else (".git",))
        shutil.copytree(src, proj, symlinks=True, ignore=shutil.ignore_patterns(*skip))
        aud = os.path.join(proj, "audits")
        if full:
            tool_names = _tooling_names(aud)
        _install_tooling(aud)
        cfg_path = sorted(glob.glob(os.path.join(aud, "projects", "*.json")))[0]
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        rd = os.path.join(proj, cfg["rounds_dir"])
        pin_path = os.path.join(rd, "TOOLING_PIN.json")
        pin = json.load(open(pin_path)) if os.path.exists(pin_path) else {"config": {}, "ownership": 1}
        tpl_path = os.path.join(aud, "project_template.json")
        cfg, tpl, pin = flip(cfg, json.load(open(tpl_path)), pin, mode, level)
        json.dump(cfg, open(cfg_path, "w"), indent=1)
        json.dump(tpl, open(tpl_path, "w"), indent=1)
        home = os.path.join(root, "home")
        os.makedirs(os.path.join(home, ".claude", "agents"))
        shutil.copy2(os.path.join(aud, "agents", "auditor.md"), os.path.join(home, ".claude", "agents", "auditor.md"))
        gitcfg = os.path.join(root, "gitconfig")
        open(gitcfg, "w").write("[init]\n\tdefaultBranch = main\n[advice]\n\tdetachedHead = false\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("FORMALIZE_")}
        env.update(GIT_ENV, HOME=home, GIT_CONFIG_GLOBAL=gitcfg, GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")

        def write_pin(subject):
            json.dump(pin, open(pin_path, "w"), indent=1)
            r = subprocess.run([sys.executable, "-B", "-c", PIN_DRIVER, aud, pin_path, cfg_path,
                                _git(aud, "rev-parse", "HEAD", env=env)], capture_output=True, text=True, env=env)
            if r.returncode:
                raise RuntimeError(f"pin driver: {(r.stdout + r.stderr)[-600:]}")
            _git(aud, "add", "--", os.path.relpath(pin_path, aud), env=env)
            _git(aud, "commit", "-q", "-m", subject, env=env)

        if full:
            # the run's own history stays (but for the pin's intake terms, rewritten to the replayed mode and
            # level in every committed version: rewrite_pin_history); today's apparatus and the flipped config
            # come in as the protocol's mid-run apparatus change does: one commit outside the rounds dir, then a
            # re-pin. The snapshot's uncommitted files (the run's final state) stay uncommitted.
            rewrite_pin_history(aud, os.path.relpath(pin_path, aud),
                                {k: pin["config"].get(k) for k in ("mode", "involvement", "involvement_answer")},
                                root, env)
            _git(aud, "add", "-A", "--", *tool_names, *[n for n in os.listdir(aud) if TOOLING_FILES.match(n)
                                                        or n in TOOLING_DIRS], os.path.relpath(cfg_path, aud), env=env)
            _git(aud, "commit", "-q", "--allow-empty", "-m", f"replay: today's apparatus ({mode}, {level})", env=env)
            write_pin(f"pin (repin: snapshot replay -- today's apparatus, {mode}, {level})")
        else:
            if os.path.exists(pin_path):
                os.remove(pin_path)
            # the audit record: everything before the pin, then the pin
            _git(aud, "init", "-q", env=env)
            rd_rel = os.path.relpath(rd, aud)
            trail = stop_trail(os.path.join(rd, "stops"))
            _git(aud, "add", "-A", env=env)
            if trail:
                _git(aud, "reset", "-q", "--", os.path.join(rd_rel, "stops"), env=env)
            _git(aud, "commit", "-q", "--allow-empty", "-m", "replay: the snapshot's record (before the pin)", env=env)
            write_pin("pin")
            for rel, subject in trail:     # the stop record, one commit per file as stops.py makes them
                _git(aud, "add", "--", os.path.join(rd_rel, "stops", rel), env=env)
                _git(aud, "commit", "-q", "-m", subject, env=env)
            # the project repository, on the config's branch
            _git(proj, "init", "-q", env=env)
            with open(os.path.join(proj, ".git", "info", "exclude"), "a") as f:
                f.write("/audits/\n")
            _git(proj, "checkout", "-q", "-b", cfg.get("branch") or "main", env=env)
            _git(proj, "add", "-A", env=env)
            _git(proj, "commit", "-q", "--allow-empty", "-m", "replay: the snapshot's project", env=env)
        # where the gates see the project: the copy, or (full) the run's recorded root
        rroot = recorded_root(src, parent) if full else proj
        raud = os.path.join(rroot, "audits")

        name, py = cfg["name"], [sys.executable, "-B"]
        rounds = sorted(os.path.basename(os.path.dirname(t)) for t in glob.glob(os.path.join(rd, "*", "TARGET.json")))
        signoffs = sorted(os.path.basename(os.path.dirname(t)) for t in glob.glob(os.path.join(rd, "*", "SIGNOFF.json")))
        gates = []
        if rounds:
            gates.append(("integrity --check", ["integrity.py", "--check", "--round", rounds[-1]]))
        gates += [(f"lanecheck {r_}", ["lanecheck.py", "--round", r_]) for r_ in rounds]
        gates.append(("phase0 --readonly", None))
        gates += [("make_report --check", ["make_report.py", "--check"]),
                  ("decisions --check", ["decisions.py", "--check"]),
                  ("readers --check report", ["readers.py", "--doc", "report", "--check"]),
                  ("readers --check decisions", ["readers.py", "--doc", "decisions", "--check"])]
        gates += [(f"readers --check signoff {r_}", ["readers.py", "--doc", "signoff", "--round", r_, "--check"])
                  for r_ in signoffs]
        gates.append(("stops list", ["stops.py", "list"]))
        out = []
        for gate, argv in gates:
            if argv is None:
                cmd = py + ["-c", PHASE0_DRIVER, raud, name, LEAN_STEP.pattern]
            else:
                cmd = py + [os.path.join(raud, argv[0]), *argv[1:], "--project", name]
            if full:
                cmd = remap_cmd(os.path.dirname(rroot), rroot, proj, cmd)
            try:
                r = subprocess.run(cmd, cwd=proj, capture_output=True, text=True, env=env, timeout=1800)
                out.append(result(gate, r.returncode, r.stdout + r.stderr))
            except subprocess.TimeoutExpired:
                out.append({"gate": gate, "rc": "timeout", "tags": {}})
        if closers is not None and mode == "release":
            # L1 (U2 §4): a gate that passes here is the closer of its codes; it must still pass with a stop
            # of each such code open (no check may test whether a stop is open). The stop record is
            # committed as stops.py commits it, then taken out again (the run's own files untouched).
            sdir = os.path.join(rd, "stops")
            nums = [int(m.group(1)) for m in (re.fullmatch(r"S(\d+)", x) for x in
                                              (os.listdir(sdir) if os.path.isdir(sdir) else [])) if m]
            busy = any(not os.path.exists(os.path.join(sdir, f"S{n}", "CLOSED.json")) for n in nums)
            rcs = {g["gate"]: g["rc"] for g in out}
            newest = f"lanecheck {rounds[-1]}" if rounds else None
            for gname, codes in closer_codes().items():
                gate = newest if gname == "lanecheck" else gname
                if busy or rcs.get(gate) != 0:
                    continue
                argv = dict(gates)[gate]
                for code in codes:
                    s_ = f"S{max(nums, default=0) + 1}"
                    sp = os.path.join(sdir, s_, "STOP.json")
                    os.makedirs(os.path.dirname(sp))
                    chk = "python3 audits/" + " ".join(argv) if argv else "python3 audits/phase0.py --readonly"
                    json.dump({"stop": s_, "date": "2026-10-22", "involvement": level, "round": None,
                               "command": chk, "exit": 1, "output": f"FAIL[{code}] x\n",
                               "causes": [{"code": code, "class": "unknown", "line": f"FAIL[{code}] x"}]},
                              open(sp, "w"), indent=1, sort_keys=True)
                    _git(aud, "add", "--", os.path.relpath(sp, aud), env=env)
                    _git(aud, "commit", "-q", "-m", f"stop {s_} open", env=env)
                    cmd = (py + ["-c", PHASE0_DRIVER, raud, name, LEAN_STEP.pattern] if argv is None
                           else py + [os.path.join(raud, argv[0]), *argv[1:], "--project", name])
                    if full:
                        cmd = remap_cmd(os.path.dirname(rroot), rroot, proj, cmd)
                    r = subprocess.run(cmd, cwd=proj, capture_output=True, text=True, env=env, timeout=1800)
                    closers.append((f"{mode}/{level}", code, gate, r.returncode, (r.stdout + r.stderr)[-300:]))
                    _git(aud, "reset", "-q", "HEAD~1", env=env)
                    os.remove(sp); os.rmdir(os.path.dirname(sp))
        return out
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def replay_mini(snapshots, mini, work, modes, keep=False, jobs=1, closers=None):
    src, full = snapshot_project(snapshots, mini)
    if src is None:
        return None
    if full and not remap_available():
        raise RemapUnavailable(f"{mini}: a full snapshot needs a user+mount namespace (unshare) and {RECORDED_PARENT}, "
                               f"not holding this install or the current user's home")
    keys = [(m, l) for m in modes for l in LEVELS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = {k: ex.submit(replay_one, src, work, k[0], k[1], keep, full, None, closers) for k in keys}
        return {f"{m}/{l}": futs[(m, l)].result() for m, l in keys}


class RemapUnavailable(RuntimeError):
    pass


def baseline_path(mini):
    return os.path.join(BASELINE_DIR, f"{mini}.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated: mini1,...")
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--snapshots", default=os.environ.get(SNAPSHOTS_ENV) or DEFAULT_SNAPSHOTS)
    ap.add_argument("--work", default=DEFAULT_WORK, help="scratch parent for the copies (never /tmp)")
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 2))
    ap.add_argument("--record", action="store_true", help="write the baselines instead of comparing")
    ap.add_argument("--keep", action="store_true", help="keep the copies (debugging)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    modes = [m for m in a.modes.split(",") if m]
    if any(m not in MODES for m in modes):
        ap.error(f"--modes: one or more of {', '.join(MODES)}")
    minis = a.only.split(",") if a.only else MINIS
    if not os.path.isdir(a.snapshots):
        print(f"SKIP snapshot replay: no snapshots at {a.snapshots} (set {SNAPSHOTS_ENV} or --snapshots)")
        return 0
    bad = 0
    for mini in minis:
        cl = [] if not a.record else None
        try:
            got = replay_mini(a.snapshots, mini, a.work, modes, a.keep, a.jobs, cl)
        except RemapUnavailable as e:
            print(f"SKIP {e}")
            continue
        if got is None:
            print(f"SKIP {mini}: no snapshot project under {a.snapshots}/{FULL_DIR}/{mini}/ or {a.snapshots}/{mini}-snapshot/")
            continue
        p = baseline_path(mini)
        old = json.load(open(p)) if os.path.exists(p) else {}
        if a.record:
            os.makedirs(BASELINE_DIR, exist_ok=True)
            json.dump(dict(old, **got), open(p, "w"), indent=1, sort_keys=True)
            open(p, "a").write("\n")
            print(f"recorded {mini}: {', '.join(sorted(got))}")
            continue
        diffs = compare({k: v for k, v in old.items() if k.split("/")[0] in modes}, got)
        bad += bool(diffs)
        print(f"{'ok  ' if not diffs else 'DIFF'}  {mini} ({len(got)} replays)")
        for d in diffs[:40]:
            print(f"        {d}")
        cbad = [c for c in cl if c[3] != 0]
        bad += bool(cbad)
        print(f"{'ok  ' if not cbad else 'FAIL'}  {mini} closers: {len(cl)} release closer run(s) with their stop "
              f"open, on the gates that pass ({len({c[2] for c in cl})} gate(s)), {len(cbad)} failing")
        for c in cbad[:10]:
            print(f"        {c[0]} {c[1]}: `{c[2]}` exits {c[3]} with the stop open: {' '.join(c[4].split())[-200:]}")
    print("snapshot replay:", "ok" if not bad else f"FAILED ({bad} snapshot(s) differ from replay_baseline/)")
    return 1 if bad else 0


# ---- selftest ----------------------------------------------------------------------------------
def selftest():
    global DEFAULT_WORK     # the CODEX-PORT check below points it at an unwritable cache, then restores it
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    out = ("FAIL[tooling] x\n  RED[sorry] y\nDISCLOSED[docstring] z\nDISCLOSED[docstring] w\n"
           "NOTE[before-pin] n\nFAIL: no project\nTraceback (most recent call last):\n")
    t = tags(out)
    say("tags: every KIND[code] counted, DISCLOSED included; an uncoded FAIL and a traceback are kept",
        t == {"CRASH": 1, "DISCLOSED[docstring]": 2, "FAIL[tooling]": 1, "FAIL[uncoded]": 1,
              "NOTE[before-pin]": 1, "RED[sorry]": 1})
    t = tags("S1  2026-10-22  [mechanical]  a failed tool call (x)  -> the human (answer, verbatim: \"3; closed\n"
             "S2  2026-10-22  [tool-bug, tooling]  y  -> the operator; open\n"
             "D1 (also recorded as D2)  2026-10-21  [pdf]  `x` disclosed: [pdf] page  (disclosed)\nset-aside R  d  s\n")
    say("tags: stops.py list lines count by class and closer; disclosures and set-asides too",
        t == {"disclosed[pdf]": 1, "set-aside": 1, "stop[mechanical]:the human": 1,
              "stop[tool-bug, tooling]:the operator": 1})
    d = tempfile.mkdtemp(dir=scratch_base())
    try:
        for f in ("S2/STOP.json", "S1/CLOSED.json", "S1/STOP.json", "S1/CURE2.json", "S1/CURE1.json",
                  "S10/STOP.json", "disclosed/D1.json", "repairs/R1.json"):
            os.makedirs(os.path.dirname(os.path.join(d, f)), exist_ok=True)
            open(os.path.join(d, f), "w").write("{}")
        say("the stop record is committed in stops.py's order and subjects (stops.trail_problems)",
            stop_trail(d) == [("S1/STOP.json", "stop S1 open"), ("S1/CURE1.json", "stop S1 cure 1"),
                              ("S1/CURE2.json", "stop S1 cure 2"), ("S1/CLOSED.json", "stop S1 close"),
                              ("S2/STOP.json", "stop S2 open"), ("S10/STOP.json", "stop S10 open"),
                              ("disclosed/D1.json", "stop disclose D1"), ("repairs/R1.json", "stop repair R1")]
            and stop_trail(os.path.join(d, "none")) == [])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    base = {"dev/involved": [result("a", 1, "FAIL[x] 1"), result("b", 0, "")]}
    say("compare: equal sequences give no difference", compare(base, json.loads(json.dumps(base))) == [])
    say("compare: an exit code change is a difference",
        compare(base, {"dev/involved": [result("a", 0, "FAIL[x] 1"), result("b", 0, "")]}) != [])
    say("compare: a tag change is a difference (FAIL -> DISCLOSED)",
        compare(base, {"dev/involved": [result("a", 1, "DISCLOSED[x] 1"), result("b", 0, "")]}) != [])
    say("compare: a missing gate or a missing key is a difference",
        compare(base, {"dev/involved": [result("a", 1, "FAIL[x] 1")]}) != []
        and compare(base, {}) != [] and compare({}, base) != [])
    cfg, tpl, pin = flip({"name": "x", "involvement": "hands-off", "involvement_answer": "a", "mode": "release"},
                         {"mode": "release"}, {"config": {"mode": "release", "involvement": "hands-off"}}, "dev", "involved")
    say("flip: config, template and pin agree on the mode and level; involved drops the answer",
        cfg["mode"] == tpl["mode"] == pin["config"]["mode"] == "dev"
        and cfg["involvement"] == pin["config"]["involvement"] == "involved"
        and "involvement_answer" not in cfg and "involvement_answer" in pin["config"]
        and pin["config"]["involvement_answer"] is None)
    cfg, _, pin = flip({"name": "x"}, {}, {}, "release", "statements-only")
    say("flip: a delegating level gets an answer (project.problems requires one), pinned too",
        cfg["involvement_answer"] and pin["config"].get("involvement_answer") == cfg["involvement_answer"])
    say("the Lean steps of phase0 are skipped, the others run",
        all(lean_skip(c) for c in ("lake build X", "python3 -B audits/axiom_sweep.py --project p",
                                   "python3 -B audits/fingerprint.py --project p --check",
                                   "python3 -B audits/dependencies.py --project p --compare",
                                   "python3 -B audits/unused_args.py --project p"))
        and not any(lean_skip(c) for c in ("python3 -B audits/make_report.py --check --index-only --pending --project p",
                                           "python3 -B audits/tree_state.py --save")))
    d = tempfile.mkdtemp(dir=scratch_base())
    try:
        say("no snapshots: SKIP, exit 0 (another machine)",
            _quiet_rc(["--snapshots", os.path.join(d, "none")]) == 0)
        os.makedirs(os.path.join(d, "mini9-snapshot", "p", "audits", "projects"))
        open(os.path.join(d, "mini9-snapshot", "p", "audits", "projects", "x.json"), "w").write("{}")
        say("the snapshot's project is the directory holding audits/projects/",
            snapshot_project(d, "mini9") == (os.path.join(d, "mini9-snapshot", "p"), False)
            and snapshot_project(d, "mini8") == (None, False))
        say("--modes refuses an unknown mode", _quiet_rc(["--snapshots", d, "--modes", "prod"]) == 2)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    d = tempfile.mkdtemp(dir=scratch_base())
    try:
        for full in ("full-snapshots/mini9/proj", "mini9-snapshot/old", "full-snapshots/mini8/nogit"):
            os.makedirs(os.path.join(d, full, "audits", "projects"))
            open(os.path.join(d, full, "audits", "projects", "x.json"), "w").write("{}")
        for g in ("full-snapshots/mini9/proj/.git", "full-snapshots/mini9/proj/audits/.git",
                  "full-snapshots/mini8/nogit/.git"):          # mini8: audits/.git missing
            os.makedirs(os.path.join(d, g))
        os.makedirs(os.path.join(d, "mini8-snapshot", "old8", "audits", "projects"))
        open(os.path.join(d, "mini8-snapshot", "old8", "audits", "projects", "x.json"), "w").write("{}")
        say("a full snapshot (both .git) is preferred; one missing a .git falls back to the old snapshot",
            snapshot_project(d, "mini9") == (os.path.join(d, "full-snapshots/mini9/proj"), True)
            and snapshot_project(d, "mini8") == (os.path.join(d, "mini8-snapshot", "old8"), False)
            and snapshot_project(d, "mini7") == (None, False))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    say("the recorded root is the run machine's home + the project directory, nothing broader",
        recorded_root("/x/full-snapshots/mini2/mini2-formalization/") == RECORDED_PARENT + "/mini2-formalization")
    # the control mounts over a scratch parent it creates, never over RECORDED_PARENT: run as the user
    # fp-claude, a tmpfs over /home/fp-claude hid the live install and selftest --fast failed (trial #7)
    sp = tempfile.mkdtemp(prefix="remap-parent-", dir=scratch_base())
    try:
        if remap_available(sp):
            rc = remap_control(sp)
            say("remap control: the recorded root resolves to the copy (lane metadata authenticates, bytes unchanged); "
                "a metadata path NOT under the recorded root -- a sibling project, the run's home, a look-alike "
                "parent -- still fails PROBLEM[auth-metadata]; without the remap all fail", rc)
            say("the remap never mounts over the current user's home or a parent holding the running install",
                hides_live(os.path.expanduser("~")) and hides_live(os.path.dirname(AUDITS)) and not hides_live(sp)
                and not remap_available(os.path.dirname(os.path.dirname(AUDITS))))
            say("run from an install under the mounted prefix (a project under RECORDED_PARENT): the replay's remap "
                "refuses (the install stays visible) and the selftest's control still passes", remap_from_inside(sp))
        else:
            print("  SKIP  remap control: no user+mount namespace here")
    finally:
        shutil.rmtree(sp, ignore_errors=True)
    say("the default scratch directory is outside /tmp", not os.path.realpath(DEFAULT_WORK).startswith("/tmp"))
    _dw, ro = DEFAULT_WORK, tempfile.mkdtemp()
    try:
        os.chmod(ro, 0o555)
        DEFAULT_WORK = os.path.join(ro, "cache", "formalize-paper", "replay")
        fell_back = scratch_base() is None or os.geteuid() == 0     # root writes anyway: nothing to test
        DEFAULT_WORK = os.path.join(ro + "-w", "formalize-paper", "replay")
        kept = scratch_base() == os.path.dirname(DEFAULT_WORK)
    finally:
        DEFAULT_WORK = _dw
        os.chmod(ro, 0o755)
        shutil.rmtree(ro, ignore_errors=True)
        shutil.rmtree(ro + "-w", ignore_errors=True)
    say("an unwritable cache (Codex's sandbox: ~/.cache is read-only) falls back to the temporary directory; "
        "a writable one is used (CODEX-PORT)", fell_back and kept)
    bl = sorted(glob.glob(os.path.join(BASELINE_DIR, "*.json")))
    keys = {f"{m}/{l}" for m in MODES for l in LEVELS}
    say("the committed baselines cover mini1..mini5 x both modes x the three levels",
        [os.path.basename(p)[:-5] for p in bl] == MINIS
        and all(set(json.load(open(p))) == keys for p in bl))
    say("no baseline row carries PROBLEM[auth-metadata] (the remap's artefact before B0b; a real one would be a finding)",
        not any("auth-metadata" in t for p in bl for rows in json.load(open(p)).values() for r in rows for t in r["tags"]))
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def _quiet_rc(argv):
    import contextlib, io
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(argv)
    except SystemExit as e:
        return e.code


if __name__ == "__main__":
    sys.exit(main())

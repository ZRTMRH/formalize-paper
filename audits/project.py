"""Per-paper project configs for the audit protocol.

WHY THIS EXISTS.  AUDIT_PROTOCOL.md and audits/ are git-excluded, so ONE copy of them serves every
branch of this clone. Before this file, the protocol spelled out the first paper's PDF, Lean file and
namespace inline, so a second paper could only be audited by editing the protocol -- which would
silently re-point the first paper's still-open round at the wrong source. Now the protocol carries
placeholders (<SOURCE-PDF>, <NAMESPACE>, ...) and each paper's values live in
audits/projects/<name>.json. `prompt.py` and `axiom_sweep.py` fill them from here.

Selection: `--project NAME`, or else the project whose `branch` is the current git branch. If
neither determines exactly one project, callers refuse rather than guess -- a prompt that quietly
names the wrong paper is worse than no prompt.
"""
import sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
import glob, json, os, re, subprocess

AUDITS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(AUDITS)
PROJECTS = os.path.join(AUDITS, "projects")

REQUIRED = ["name", "source_pdf", "source_id", "source_cite", "branch", "base_commit",
            "lean_files", "build_cmds", "namespace", "sweep", "rounds_dir", "lanes",
            "calibration", "blind_spots"]
OPTIONAL = ["standing_defers", "index_file", "confidential", "goal", "goal_note", "notes",
            "lane_purpose", "title", "index_strict", "goal_results", "literature_hypotheses",
            "libraries", "work_dir", "glossary", "involvement", "involvement_answer"]
# The Lean libraries a missing definition or theorem must be searched in before a skip blames it
# on Mathlib (config `libraries`, set at intake). Tau Ceti has, e.g., dense graph limits.
DEFAULT_LIBRARIES = ["Mathlib", "TauCeti"]


def libraries(cfg):
    return cfg.get("libraries") or DEFAULT_LIBRARIES


# How involved the human chose to be after the intake (RUN.md, intake question 5c; config
# `involvement`, its verbatim answer in `involvement_answer`):
#   involved         the human decides at Checkpoints B and C (the default)
#   statements-only  the human approves the statements at B; the operator decides everything after
#   hands-off        the operator decides at B, at C and at every later stop
# A decision the level hands to the operator is final and tagged [DELEGATED ...] in RUN_LOG.md;
# the report and the decisions document disclose who decided what.
INVOLVEMENT_LEVELS = ("involved", "statements-only", "hands-off")


def involvement(cfg):
    """The configured involvement level; "involved" when the key is absent. An invalid value is
    returned as it is (problems() reports it; callers refuse it rather than guess)."""
    v = cfg.get("involvement")
    return "involved" if v is None else v


def delegates(cfg):
    """True when the level hands Checkpoint C (and every later stop) to the operator."""
    return involvement(cfg) in ("statements-only", "hands-off")
# A round directory is <YYYY-MM-DD>-<commit> (a diff round) or <YYYY-MM-DD>-full-<commit> (a
# full-scope round, `prompt.py 3 --full`). Anything else under a rounds dir (another project's
# rounds dir, `projects/`) is not a round -- matching on the name is what lets the legacy layout,
# with the first project's rounds directly under audits/, coexist with per-project subdirectories.
#
# The `full-` infix exists because a full round is often cut from the SAME commit as the diff
# round before it (the diff round adopted nothing, so nothing was committed). With one naming
# scheme both rounds got the same directory, and the full round's lanes and adjudicator would have
# overwritten the diff round's record. The commit is always the LAST dash-separated field.
#
# This regex, and RESULT_KINDS below, are imported by every script. They used to be copied into
# each one, and the copies drifted: one script accepted `Fact`/`Construction` index rows and
# another silently dropped them from the coverage count.
ROUND_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40}$")
BLANK = "<<"

# The environment names a paper's numbered results may carry, as they appear in the index table.
RESULT_KINDS = ["Definition", "Lemma", "Theorem", "Proposition", "Corollary", "Claim", "Remark",
                "Example", "Conjecture", "Fact", "Observation", "Construction"]
RESULT_KINDS_RE = "|".join(RESULT_KINDS)


def split_row(line):
    """Cells of a markdown table row. `\\|` inside a cell is a literal bar, not a separator (as in
    GitHub markdown). Records quote formulas like `\\|i - i'\\|`; splitting there shifted every
    later field of a report row."""
    cells, cur, i, s = [], "", 0, line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"; i += 2; continue
        if ch == "|":
            cells.append(cur.strip()); cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def round_commit(name):
    """The commit a round directory was cut from: always the last dash-separated field."""
    return os.path.basename(name).split("-")[-1]


def is_full_round(name):
    return "-full-" in os.path.basename(name)


def git(*args):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def all_projects():
    out = {}
    for path in sorted(glob.glob(os.path.join(PROJECTS, "*.json"))):
        cfg = json.load(open(path, encoding="utf-8"))
        cfg["_path"] = path
        out[cfg.get("name", os.path.basename(path)[:-5])] = cfg
    return out


class SelectionError(Exception):
    pass


def select(name=None):
    projects = all_projects()
    if not projects:
        raise SelectionError(f"no project configs in {PROJECTS}")
    if name:
        if name not in projects:
            raise SelectionError(f"no project {name!r}; known: {', '.join(projects)}")
        return projects[name], f"--project {name}"
    branch = git("branch", "--show-current")
    hits = [p for p in projects.values() if p.get("branch") == branch]
    if len(hits) == 1:
        return hits[0], f"current branch {branch!r}"
    known = ", ".join(f"{n} (branch {p.get('branch')})" for n, p in projects.items())
    raise SelectionError(f"current branch {branch!r} selects {len(hits)} projects; "
                         f"pass --project NAME. Known: {known}")


def rounds(cfg):
    """Round directories of this project, oldest first (names sort chronologically)."""
    d = os.path.join(REPO, cfg["rounds_dir"])
    return sorted(p for p in glob.glob(os.path.join(d, "*"))
                  if os.path.isdir(p) and ROUND_RE.match(os.path.basename(p)))


def is_temporary(path):
    """True if `path` lies in a directory the system may wipe (/tmp, /var/tmp, $TMPDIR)."""
    import tempfile
    p = os.path.realpath(os.path.expanduser(path))
    roots = {"/tmp", "/var/tmp", "/dev/shm", os.path.realpath(tempfile.gettempdir())}
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def problems(cfg):
    """Everything wrong or unfilled in a config. Strings starting with '!' are hard errors."""
    out = []
    for k in REQUIRED:
        if k not in cfg:
            out.append(f"! missing field {k!r}")

    def walk(v, path):
        if isinstance(v, str) and BLANK in v:
            out.append(f"  unfilled blank in {path}: {v}")
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    for k, v in cfg.items():
        if not k.startswith("_"):
            walk(v, k)
    if "source_pdf" in cfg and not os.path.exists(cfg["source_pdf"]):
        out.append(f"! source_pdf does not exist: {cfg['source_pdf']}")
    # Proof drafts must survive a reboot: a run once lost a dozen files of proofs kept under /tmp
    # when the machine restarted. RUN.md, Stage 1: `work_dir` is a persistent git repository.
    wd = cfg.get("work_dir")
    if wd is None:
        out.append("  no work_dir set: helpers' drafts need a persistent directory (RUN.md, Stage 1)")
    elif isinstance(wd, str) and BLANK not in wd and work_dir_problem(cfg):
        out.append("! " + work_dir_problem(cfg))
    elif isinstance(wd, str) and BLANK not in wd and is_temporary(work_dir_path(dict(cfg, work_dir=wd))):
        out.append(f"! work_dir is under a temporary directory, which a reboot may wipe: {wd}")
    src = cfg.get("source_pdf")
    if isinstance(src, str) and BLANK not in src:
        sp = os.path.realpath(os.path.join(REPO, os.path.expanduser(src)))
        if os.path.commonpath([sp, os.path.realpath(REPO)]) != os.path.realpath(REPO):
            out.append(f"! source_pdf must be inside the project (a file outside it makes every reviewer's "
                       f"read ask for permission): {src}")
    lvl = involvement(cfg)
    if lvl not in INVOLVEMENT_LEVELS:
        out.append(f"! involvement is {lvl!r}; it must be one of {', '.join(INVOLVEMENT_LEVELS)} "
                   f"(RUN.md, intake question 5c)")
    elif lvl != "involved" and not str(cfg.get("involvement_answer") or "").strip():
        out.append(f"! involvement is {lvl!r} but involvement_answer (the human's intake answer, "
                   f"verbatim) is empty: the report and the decisions document must quote it")
    for f in cfg.get("lean_files", []):
        if not os.path.exists(os.path.join(REPO, f)):
            out.append(f"  lean file not present on this checkout: {f}")
    branch = git("branch", "--show-current")
    if cfg.get("branch") and branch != cfg["branch"]:
        out.append(f"  current branch is {branch!r}, but this project lives on {cfg['branch']!r}")
    return out


FW = ".formalization-work"


def _fw_root():
    """<project>/.formalization-work, refusing a symlink there (a write would follow it out of the
    project)."""
    root = os.path.join(REPO, FW)
    if os.path.islink(root):
        raise ValueError(f"{root} is a symbolic link; it must be a directory inside the project")
    return root


def scratch(name):
    """A fresh scratch directory for one subagent: .formalization-work/scratch/<name>-<time>-<n>/,
    created here so that no mkdir has to ask for permission. Returns the path relative to the
    project root (the subagent's working directory)."""
    import datetime
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name or "") or ".." in name:
        raise ValueError("--scratch NAME: letters, digits, '.', '_' and '-' only")
    base = os.path.join(_fw_root(), "scratch")
    os.makedirs(base, exist_ok=True)
    _exclude(FW + "/")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    for n in range(1, 10000):
        d = os.path.join(base, f"{name}-{stamp}-{n}")
        try:
            os.mkdir(d)
            return os.path.relpath(d, REPO) + os.sep
        except FileExistsError:
            continue
    raise ValueError("no free scratch directory name")


def work_dir_problem(cfg):
    """Why the configured work_dir is not acceptable, or None. It must be a relative path under the
    project's .formalization-work/ (git-excluded, covered by the project's permission rules)."""
    wd = cfg.get("work_dir")
    if wd is None:
        return None
    wd = str(wd)
    if os.path.isabs(os.path.expanduser(wd)) or wd.startswith("~"):
        return f"work_dir must be a path inside the project (default {FW}/<name>), not {wd}"
    parts = os.path.normpath(wd).split(os.sep)
    if ".." in wd.split("/") or parts[0] != FW or len(parts) < 2:
        return f"work_dir must lie under {FW}/ inside the project (default {FW}/<name>), not {wd}"
    return None


def work_dir_path(cfg):
    """The helpers' work directory as an absolute path: `~` expanded, a relative path taken from the
    project root (the default, `.formalization-work/<name>`, lives inside the project, git-excluded,
    so that Claude Code's project permission rules cover it)."""
    wd = os.path.expanduser(str(cfg.get("work_dir") or os.path.join(FW, cfg.get("name", "work"))))
    return wd if os.path.isabs(wd) else os.path.join(REPO, wd)


def _exclude(path_in_repo):
    """Add a line to the project's .git/info/exclude (once)."""
    r = subprocess.run(["git", "-C", REPO, "rev-parse", "--git-path", "info/exclude"], capture_output=True, text=True)
    if r.returncode != 0:
        return
    ex = r.stdout.strip()
    ex = ex if os.path.isabs(ex) else os.path.join(REPO, ex)
    os.makedirs(os.path.dirname(ex), exist_ok=True)
    have = open(ex, encoding="utf-8").read().splitlines() if os.path.exists(ex) else []
    if path_in_repo not in have:
        with open(ex, "a", encoding="utf-8") as f:
            f.write(path_in_repo + "\n")


def env_check():
    """RUN.md Stage 1 step 0: every command must run with PYTHONDONTWRITEBYTECODE=1."""
    ok = os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    print("environment: PYTHONDONTWRITEBYTECODE=1 ok" if ok else
          "FAIL: PYTHONDONTWRITEBYTECODE is not 1 in this session's commands (RUN.md, Stage 1, step 0)")
    return 0 if ok else 1


def init_work_dir(cfg, _allow_temporary=False):
    """Create the work_dir as a git repository of its own (once), git-excluded from the project."""
    bad = work_dir_problem(cfg)
    if bad:
        print("FAIL: " + bad)
        return 1
    try:
        _fw_root()
    except ValueError as e:
        print(f"FAIL: {e}")
        return 1
    wd = work_dir_path(cfg)
    if is_temporary(wd) and not _allow_temporary:
        print(f"FAIL: work_dir {wd} is under a temporary directory, which a reboot may wipe")
        return 1
    os.makedirs(wd, exist_ok=True)
    if not os.path.isdir(os.path.join(wd, ".git")):
        subprocess.run(["git", "init", "-q", wd], check=True)
    _exclude(FW + "/")      # the whole .formalization-work/, never a component of the project's own tree
    print(f"work_dir ready: {wd}")
    return 0


def work_commit(cfg, message, paths=None):
    """Commit the helpers' drafts in work_dir (all changes, or the given paths), one commit at a
    time across parallel helpers."""
    import fcntl
    wd = work_dir_path(cfg)
    if not os.path.isdir(os.path.join(wd, ".git")):
        print(f"FAIL: {wd} is not a git repository: run project.py --init-work-dir first")
        return 1
    with open(os.path.join(wd, ".git", "formalize-paper-work.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        def g(*a):
            return subprocess.run(["git", "-C", wd, *a], capture_output=True, text=True)
        # paths may be given from the project root or from work_dir: each must be a file in work_dir
        rels, rwd = [], os.path.realpath(wd)
        for p_ in (paths or []):
            cand = [os.path.realpath(os.path.join(REPO, p_)), os.path.realpath(os.path.join(wd, p_))]
            hit = next((c for c in cand if os.path.commonpath([c, rwd]) == rwd and os.path.exists(c)), None)
            if hit is None:
                print(f"FAIL: {p_} is not a file in the work_dir {wd}")
                return 1
            rels.append(os.path.relpath(hit, rwd))
        a_ = g("add", "-A", "--", *(rels or ["."]))
        if a_.returncode != 0:
            print("FAIL: git add in work_dir failed: " + a_.stderr.strip())
            return 1
        if g("diff", "--cached", "--quiet").returncode == 0:
            print("work_dir: nothing to commit")
            return 0
        r = g("-c", "user.name=formalize-paper helper", "-c", "user.email=helper@localhost",
              "commit", "-q", "-m", message)
        print(r.stdout + r.stderr if r.returncode else f"work_dir: committed: {message}")
        return r.returncode


def deliver(cfg):
    """Copy the deliverables into <project>/deliverables/ (git-excluded): REPORT.pdf, DECISIONS.md,
    every KNOWN_FAULTS-*.md notice, and the APPROVED round's SIGNOFF.pdf. A copy elsewhere is the
    person's (or a plain `cp`, which asks for permission)."""
    import shutil
    rd = os.path.join(REPO, cfg["rounds_dir"])
    out = os.path.join(REPO, "deliverables")
    if os.path.islink(out):
        print(f"FAIL: {out} is a symbolic link"); return 1
    os.makedirs(out, exist_ok=True)
    _exclude("deliverables/")
    files = [os.path.join(rd, f) for f in ("REPORT.pdf", "DECISIONS.md")]
    files += sorted(glob.glob(os.path.join(rd, "KNOWN_FAULTS-*.md")))
    try:
        appr = json.load(open(os.path.join(rd, "APPROVED_FINGERPRINTS.json")))
        files.append(os.path.join(rd, appr["round"], "SIGNOFF.pdf"))
    except (OSError, ValueError, KeyError):
        print("note: no approval record (APPROVED_FINGERPRINTS.json): no SIGNOFF.pdf delivered")
    missing = [f for f in files if not os.path.exists(f)]
    for f in files:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(out, os.path.basename(f)))
    print(f"delivered {len(files) - len(missing)} file(s) to {out}"
          + (f"; MISSING: {', '.join(os.path.relpath(m, REPO) for m in missing)}" if missing else ""))
    return 1 if missing else 0


def compile_source(tex, out_dir):
    """Compile a .tex source twice with xelatex, shell escape OFF, in out_dir (RUN.md, Stage 1,
    step 2: result numbers come from the .aux)."""
    tex = os.path.abspath(tex)
    os.makedirs(out_dir, exist_ok=True)
    for _ in range(2):
        r = subprocess.run(["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                            f"-output-directory={out_dir}", tex], cwd=os.path.dirname(tex),
                           capture_output=True, text=True)
    aux = os.path.join(out_dir, os.path.splitext(os.path.basename(tex))[0] + ".aux")
    print(f"compiled {tex} -> {out_dir} (exit {r.returncode}); numbering in {aux}"
          + ("" if os.path.exists(aux) else " -- MISSING"))
    return 0 if os.path.exists(aux) else 1


# Files outside lean_files that still change what the Lean means: the toolchain, the build, and the
# dependency pins (a Mathlib bump can change a definition the project uses).
BUILD_FILES = ["lakefile.lean", "lakefile.toml", "lean-toolchain", "lake-manifest.json"]


def _env_check_without():
    old = os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
    try:
        return env_check() == 1
    finally:
        if old is not None:
            os.environ["PYTHONDONTWRITEBYTECODE"] = old


def _quiet(f):
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return f()


def selftest():
    """The config checks, as negative controls (prompt.py's self-test runs them too)."""
    global REPO
    fake = {"name": "negctl"}
    checks = [
        ("a config missing fields is a hard error", any(p.startswith("! missing") for p in problems(fake))),
        ("a work_dir under /tmp is a hard error",
         any(p.startswith("! work_dir") for p in problems(dict(fake, work_dir="/tmp/w")))),
        ("an unknown involvement level is a hard error; the three levels are not",
         any(p.startswith("! involvement") for p in problems(dict(fake, involvement="hands-free", involvement_answer="x")))
         and not any(p.startswith("! involvement") for lvl in INVOLVEMENT_LEVELS
                     for p in problems(dict(fake, involvement=lvl, involvement_answer="x")))),
        ("a delegating level without its intake answer is a hard error",
         any(p.startswith("! involvement") for p in problems(dict(fake, involvement="statements-only")))),
        ("a relative work_dir is taken from the project root; the default lives inside the project",
         work_dir_path({"name": "x", "work_dir": ".formalization-work/x"}) == os.path.join(REPO, ".formalization-work", "x")
         and work_dir_path({"name": "x"}) == os.path.join(REPO, ".formalization-work", "x")
         and work_dir_path({"work_dir": "~/w"}) == os.path.expanduser("~/w")),
        ("--env-check reports the variable", _quiet(lambda: (os.environ.get("PYTHONDONTWRITEBYTECODE") == "1") == (env_check() == 0))),
        ("--env-check fails when the variable is missing", _quiet(_env_check_without)),
        ("no key means involved, which delegates nothing",
         involvement(fake) == "involved" and not delegates(fake) and delegates(dict(fake, involvement="hands-off"))),
    ]
    # the work_dir and source-compile commands, in a scratch repository
    import tempfile, shutil, io, contextlib
    saved, tmp = REPO, tempfile.mkdtemp(prefix="project-selftest-")
    try:
        REPO = os.path.join(tmp, "proj"); os.makedirs(REPO)
        subprocess.run(["git", "init", "-q", REPO], check=True)
        cfgw = {"name": "x", "work_dir": ".formalization-work/x"}
        with contextlib.redirect_stdout(io.StringIO()):
            rc_t = init_work_dir(cfgw)          # the scratch repository is under /tmp: refused
            rc_i = init_work_dir(cfgw, _allow_temporary=True)
            open(os.path.join(REPO, ".formalization-work", "x", "Draft.lean"), "w").write("-- draft\n")
            rc_c = work_commit(cfgw, "draft compiles")
            log = subprocess.run(["git", "-C", work_dir_path(cfgw), "log", "--format=%s"], capture_output=True, text=True).stdout
            excl = open(os.path.join(REPO, ".git", "info", "exclude")).read()
        checks.append(("--init-work-dir refuses a work_dir under a temporary directory", rc_t == 1))
        checks.append(("--init-work-dir makes a git repository inside the project, excluded from its history",
                       rc_i == 0 and os.path.isdir(os.path.join(REPO, ".formalization-work", "x", ".git"))
                       and ".formalization-work/" in excl.splitlines()))
        checks.append(("--work-commit commits the drafts in work_dir", rc_c == 0 and "draft compiles" in log))
        with contextlib.redirect_stdout(io.StringIO()):
            open(os.path.join(REPO, ".formalization-work", "x", "Two.lean"), "w").write("-- two\n")
            rc_p = work_commit(cfgw, "by project path", [".formalization-work/x/Two.lean"])
            rc_bad = work_commit(cfgw, "outside", ["Elsewhere.lean"])
            log2 = subprocess.run(["git", "-C", work_dir_path(cfgw), "log", "--format=%s"], capture_output=True, text=True).stdout
        checks.append(("--work-commit takes a project-relative path, and refuses a path outside work_dir",
                       rc_p == 0 and "by project path" in log2 and rc_bad == 1))
        checks.append(("the exclude names .formalization-work/, never a component of the project's tree",
                       excl.splitlines().count(".formalization-work/") == 1
                       and work_dir_problem({"work_dir": "Paper/drafts"}) is not None))
        checks.append(("the config check names a work_dir outside .formalization-work/",
                       any("work_dir must" in x for x in problems({"name": "x", "work_dir": "~/w"}))
                       and any("work_dir must" in x for x in problems({"name": "x", "work_dir": "Paper/drafts"}))))
        checks.append(("an absolute, home or '..' work_dir is refused",
                       all(work_dir_problem({"work_dir": w}) for w in ("/srv/w", "~/w", ".formalization-work/../w"))
                       and work_dir_problem({"work_dir": ".formalization-work/x"}) is None))
        sd1, sd2 = scratch("correspondence"), scratch("correspondence")
        checks.append(("--scratch prints a fresh directory inside .formalization-work/scratch/ each time",
                       sd1 != sd2 and sd1.startswith(".formalization-work/scratch/correspondence-")
                       and os.path.isdir(os.path.join(REPO, sd1))))
        try:
            scratch("../x"); bad_name = False
        except ValueError:
            bad_name = True
        checks.append(("--scratch refuses a name with a path in it", bad_name))
        shutil.rmtree(os.path.join(REPO, ".formalization-work"))
        os.symlink(tmp, os.path.join(REPO, ".formalization-work"))
        try:
            scratch("lane"); sym_ok = False
        except ValueError:
            sym_ok = True
        with contextlib.redirect_stdout(io.StringIO()):
            sym_init = init_work_dir(cfgw, _allow_temporary=True)
        checks.append(("a symlinked .formalization-work is refused", sym_ok and sym_init == 1))
        os.remove(os.path.join(REPO, ".formalization-work"))
        os.makedirs(os.path.join(REPO, "paper")); open(os.path.join(REPO, "paper", "n.tex"), "w").write("x")
        inside = [x for x in problems({"name": "x", "source_pdf": "paper/n.tex"}) if "source_pdf must" in x]
        outside = [x for x in problems({"name": "x", "source_pdf": tmp}) if "source_pdf must" in x]
        checks.append(("source_pdf must be inside the project", not inside and bool(outside)))
        rdd = os.path.join(REPO, "audits", "x", "2026-01-01-abc1234"); os.makedirs(rdd)
        for f_ in ("REPORT.pdf", "DECISIONS.md", "KNOWN_FAULTS-report-x.md"):
            open(os.path.join(REPO, "audits", "x", f_), "w").write("x")
        open(os.path.join(rdd, "SIGNOFF.pdf"), "w").write("x")
        json.dump({"round": "2026-01-01-abc1234"}, open(os.path.join(REPO, "audits", "x", "APPROVED_FINGERPRINTS.json"), "w"))
        with contextlib.redirect_stdout(io.StringIO()):
            rc_d = deliver({"rounds_dir": "audits/x"})
        got = sorted(os.listdir(os.path.join(REPO, "deliverables")))
        excl2 = open(os.path.join(REPO, ".git", "info", "exclude")).read().splitlines()
        checks.append(("--deliver copies the report, decisions, notices and the approved sheet into deliverables/ (excluded)",
                       rc_d == 0 and got == ["DECISIONS.md", "KNOWN_FAULTS-report-x.md", "REPORT.pdf", "SIGNOFF.pdf"]
                       and "deliverables/" in excl2))
        st = subprocess.run(["git", "-C", REPO, "status", "--porcelain"], capture_output=True, text=True).stdout
        checks.append(("the project's tree does not see work_dir", ".formalization-work" not in st))
        if shutil.which("xelatex"):
            tex = os.path.join(tmp, "n.tex")
            open(tex, "w").write("\\documentclass{article}\\begin{document}\\immediate\\write18{touch "
                                 + os.path.join(tmp, "PWNED") + "}\\section{A}\\label{s}x\\end{document}\n")
            with contextlib.redirect_stdout(io.StringIO()):
                rc_x = compile_source(tex, os.path.join(tmp, "out"))
            checks.append(("--compile-source writes the .aux, with shell escape off",
                           rc_x == 0 and os.path.exists(os.path.join(tmp, "out", "n.aux"))
                           and not os.path.exists(os.path.join(tmp, "PWNED"))))
        else:
            print("  note  xelatex not installed: --compile-source not exercised")
    finally:
        REPO = saved
        shutil.rmtree(tmp, ignore_errors=True)
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    ok = all(c for _, c in checks)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def round_kind(round_dir):
    """'statements', 'diff' or 'full' from the round's TARGET.json (None if unreadable)."""
    try:
        return json.load(open(os.path.join(round_dir, "TARGET.json"))).get("_meta", {}).get("kind")
    except (OSError, ValueError):
        return None


def changes_after_last_audit(cfg, rounds):
    """What changed in the Lean since the last round that examined proofs (a diff or full round;
    a statement round examines statements only). `rounds` oldest first BY COMMIT TIME
    (audit_coverage.order_rounds). Returns None if there is no such round, else a dict:
      round, commit            the last proof-examining round and its commit
      commits                  [oneline] after it touching lean_files or BUILD_FILES
      dirty                    [path] uncommitted changes to those files
      problem                  a sentence when the answer cannot be trusted, else None
    One implementation, used by make_report.py and decisions.py, so the two cannot disagree."""
    audit = [d for d in rounds if round_kind(d) != "statements"]
    if not audit:
        return None
    rd = audit[-1]
    h = round_commit(os.path.basename(rd))
    paths = list(cfg.get("lean_files", [])) + BUILD_FILES
    out = {"round": os.path.basename(rd), "commit": h, "commits": [], "dirty": [], "problem": None}
    def run(*a):
        return subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)
    anc = run("merge-base", "--is-ancestor", h, "HEAD")
    if anc.returncode != 0:
        out["problem"] = (f"HEAD does not descend from the last audited commit {h} (round "
                          f"{out['round']}): the reported code may not be what was audited; check by hand")
        return out
    log = run("log", "--oneline", f"{h}..HEAD", "--", *paths)
    st = run("status", "--porcelain", "--", *paths)
    if log.returncode != 0 or st.returncode != 0:
        out["problem"] = f"git failed reading the history since {h}; check by hand"
        return out
    out["commits"] = [l.strip() for l in log.stdout.splitlines() if l.strip()]
    out["dirty"] = [l[3:].strip() for l in st.stdout.splitlines() if l.strip()]
    return out


USAGE = """usage:
  project.py --env-check                     PYTHONDONTWRITEBYTECODE=1 in this session? (RUN.md Stage 1)
  project.py --compile-source FILE.tex       xelatex twice, no shell escape, into .formalization-work/source-build/
  project.py --scratch NAME                  print a fresh scratch directory for one subagent
  project.py --deliver [--project NAME]      copy the deliverables into deliverables/ (git-excluded)
  project.py --init-work-dir [--project NAME]        create the helpers' work_dir (git, excluded)
  project.py --work-commit MESSAGE [--project NAME] [PATH ...]   commit drafts in work_dir
  project.py --selftest"""


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    if argv == ["--env-check"]:
        return env_check()
    name = None
    if "--project" in argv:
        i = argv.index("--project")
        name = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if argv[:1] == ["--scratch"] and len(argv) == 2:
        try:
            print(scratch(argv[1]))
            return 0
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
    if argv[:1] == ["--compile-source"] and len(argv) == 2:
        try:
            out = os.path.join(_fw_root(), "source-build")
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
        _exclude(FW + "/")
        return compile_source(argv[1], out)
    if argv[:1] in (["--init-work-dir"], ["--work-commit"], ["--deliver"]):
        try:
            cfg = select(name)[0]
        except SelectionError as e:
            print(f"FAIL: {e}")
            return 2
        if argv[0] == "--init-work-dir":
            return init_work_dir(cfg)
        if argv[0] == "--deliver":
            return deliver(cfg)
        if len(argv) < 2:
            print(USAGE); return 2
        return work_commit(cfg, argv[1], argv[2:] or None)
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

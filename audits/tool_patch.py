#!/usr/bin/env python3
"""Reviewed in-run patches to a buggy pinned check (release mode; OPERATOR-PATCH, approver 2026-10-24).

WHY THIS EXISTS.  In release mode a pinned check that misjudges a case (bench1 S2: result_status.py routed a
correctly recorded inline hypothesis to the adjudicator; bench2 S1: the diff-round F10 filter read the round's
own sealed verdict; bench1 S1: a false prompt-changed) used to end the run at the human, although the operator
had diagnosed it exactly and the maintainer's later fix was a small diff. Now the operator acts as maintainer:
it diagnoses the fault, writes a minimal patch with a regression test, this script records the MECHANICAL facts
about the patch, a FRESH independent reviewer (no lane, no adjudicator of the run, not the operator) tries to
refute it, and only a sealed approval of exactly that diff lets it be applied. Python checks facts and
provenance; agents judge. Dev mode refuses every step (a maintainer fixes tools there).

THE ROUTE (RUN.md "Tool patches"):
  tool_patch.py begin --stop S<n>                 open TP<k> for an open, non-human stop ("tool-patch TP<k> begin")
     (write <rounds>/tool-patches/TP<k>/A<n>/DIAGNOSIS.md and A<n>/patch.diff, the diff made in a scratch tree)
  tool_patch.py prepare --tp TP<k>                record FACTS.json; commits "tool-patch TP<k> diagnosis <n>"
                                                  (refused before review: a file a patch may not touch, a new
                                                  file with a module's name, a guarded block changed, no new regression test, the test not failing on the pinned tool and
                                                  passing on the patched one, a failing selftest suite, a diff
                                                  identical to one already rejected)
  tool_patch.py review --tp TP<k>                 issue a fresh reviewer's prompt with a lane token
                                                  ("tool-patch TP<k> token review-<n>-<m>.json"); seal its verdict
                                                  with lane_auth.py seal ("tool-patch TP<k> seal ...")
  tool_patch.py apply --tp TP<k>                  approved: commit the diff ("tool-patch TP<k> apply", tooling only)
                                                  and re-pin ("pin (tool-patch TP<k>)"); then stops.py close --stop
                                                  S<n> --cured "tool-patch TP<k>"
  tool_patch.py withdraw --tp TP<k> --reason T    the check was right after all (or a reviewer never returned):
                                                  back to the printed cure; never a dead end
  tool_patch.py facts --tp TP<k> --attempt N [--out F]   re-derive FACTS (the reviewer runs it)
  tool_patch.py status [--tp TP<k>]
  tool_patch.py verify-chain [--first-pin]        every link verified (the maintainer's standalone re-check)
  tool_patch.py --selftest

FACTS (mechanical, FACTS.json): (a) the patch's new regression test tests/regressions/<name>.py fails with the
pinned apparatus and passes with the patched one; (b) every pure selftest OF THE FIRST PIN (listed by its
project.py, never the patched one's; plus any the patch adds) passes on the patched apparatus; (c)
the blast radius: every read-only check of every round run with the pinned and the patched code on today's
records, every result that changes (a PASS->FAIL forces affects-review-inputs yes, R8); (d) the floor: every
mutant whose id is in FLOOR of tests/mutant_list.py AT THE RUN'S FIRST PIN must still find its pattern exactly
once and still be killed by the patched selftests -- killed meaning its selftest PASSES on the patched apparatus
unmutated and fails under the mutant (a selftest failing unmutated is a hit, never a kill: re-check 2026-10-25).
A floor hit does not refuse: it needs TWO independent
approvals (review §4b), and the reviewer is told.

APPROVAL (one rule, checked at apply and by every later integrity check): every reviewer prompt issued for the
TP is sealed (an unsealed reject cannot be hidden: withdraw the TP instead); the attempt applied has no reject;
its diff is none a review IN THE RUN (any stop: re-check 2026-10-25) rejected or never sealed (read from git: a
review issued and never sealed counts as a rejection, safety review 2026-10-25), and its DIAGNOSIS.md names and
answers each such review under "## Earlier findings answered";
it has `required` approvals (1, or 2 with a floor hit) whose verdicts name its patch_sha256, from distinct
agent ids seen nowhere else in the run; its prompts are exactly what the apparatus in force renders.

THE CHAIN (integrity.py --check, chain_problems): each "pin (tool-patch TP<k>)" link is verified by the
apparatus pinned JUST BEFORE it (its scripts extracted from git and run in a subprocess, T34's pattern): the
apply commit's tooling diff is byte-identical to the approved patch.diff, and the diff from the previous pin's
commit too; only allowed files; the pin records the link; the reviews and facts hold. No TP patches the verifier
itself: tool_patch.py and integrity.py are in the proof-validity CORE (below). `verify-chain --first-pin` re-checks every link with the
FIRST pin's apparatus: integrity.py --check runs it too (first_pin_recheck; a link it does not verify is
FAIL[tool-patch], safety review 2026-10-25: a patch that weakened approval_problems let the NEXT link through with
no review, its pinned-before verifier being the weakened one), and RUN_RECORD.md lists each link's result as
--prepare-delivery found it, with the command a maintainer runs by hand. The tool-patch machinery's own
selftests (TP4-TP8, TP10, TP12, TP22-TP26, TP30-TP35) are in the FLOOR, so a patch weakening their non-core call sites
(project.py's, prompt.py's) needs two approvals.

STRUCTURE (re-check 3, 2026-10-25; OPERATOR-AUTHORITY 2026-10-26; structure_problems, guard_problems,
manifest_problems): a patch may touch any file of the apparatus, the protocol text included, and add files under no
Python module's name; never a record, a signed document, the git rules, the GUARDED reviewer prompts and their
renderer, nor the PROOF-VALIDITY CORE (CORE, read from the first pin): the build check and sorry scan, the axiom sweep, the statement
freeze and the route's own provenance checks. Refused at prepare, apply and every link check; no approval counts.

THREAT MODEL.  As integrity.py: a careless or over-helpful operator, not a forger who rewrites git history.
"""
import sys
sys.dont_write_bytecode = True
import argparse, concurrent.futures, datetime, glob, hashlib, json, os, re, shutil, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

TP_DIR = "tool-patches"
TP_RE = re.compile(r"^TP([1-9]\d*)$")
ATTEMPT_RE = re.compile(r"^A([1-9]\d*)$")
REVIEW_RE = re.compile(r"^review-([1-9]\d*)-([1-9]\d*)\.json$")
OWNERSHIP_SINCE = 4         # integrity.OWNED_SINCE["tool-patches/*"]: a run pinned earlier cannot patch
REVIEWER_ROLE = "formalize_tool_patch_reviewer"     # the Codex role (codex_agents.ROLES); pinned at the first pin
PIN_SUBJ_RE = re.compile(r"^pin \(tool-patch (TP[1-9]\d*)\)$")
SUBJ_RE = re.compile(r"^tool-patch (TP[1-9]\d*) (begin|diagnosis [1-9]\d*|token review-[1-9]\d*-[1-9]\d*\.json|"
                     r"seal review-[1-9]\d*-[1-9]\d*\.json|withdraw|apply)$")
DIAG_HEADINGS = ("## The check", "## The failing case", "## The cause", "## The correct behaviour",
                 "## Why no faithfulness result depends on the change", "## Whether the old behaviour is right elsewhere")
AFFECTS_RE = re.compile(r"^affects-review-inputs:\s*(yes|no)\s*$", re.M)
REGRESSION_RE = re.compile(r"^regression:\s*(tests/regressions/[A-Za-z0-9_]+\.py)\s*$", re.M)
DIAG_TEMPLATE = "\n\n".join(h + "\n<...>" for h in DIAG_HEADINGS) + (
    "\n\naffects-review-inputs: yes|no   (could the bug have changed what an earlier review was shown or scoped?)"
    "\nregression: tests/regressions/<name>.py   (a NEW file of the patch: fails on the pinned tool, passes on the "
    "patched one; it takes --apparatus DIR and imports the scripts from DIR)\n"
    "(after a rejected or never-sealed review in the run, on any stop: a section \"## Earlier findings answered\" naming each, "
    "`TP<k> review-<n>-<m>.json`, with your answer to its findings)\n")
RUNNER = None           # the selftest's stand-in for the heavy fact runners: RUNNER(kind, *args) -> result or None
JOBS = max(1, min(8, os.cpu_count() or 1))


class Refused(ValueError):
    pass


# --- small helpers --------------------------------------------------------------------------------------------
def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def git(repo, *a, check=True, binary=False):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=not binary)
    if check and r.returncode:
        raise Refused(f"git {' '.join(a[:3])} failed: {(r.stderr or b'').strip() if not binary else r.stderr[:200]}")
    return r.stdout if binary else r.stdout.strip("\n")


def today():
    return datetime.date.today().isoformat()


def rounds_dir(cfg):
    return os.path.join(project.REPO, cfg["rounds_dir"])


def audit_top(audits):
    return git(audits, "rev-parse", "--show-toplevel")


def prefix(audits):
    """The audits directory's path inside its repository ("" in an installed project, "audits/" in a clone)."""
    return git(audits, "rev-parse", "--show-prefix")


def show(audits, rev, rel, binary=False):
    """The bytes/text of `rel` (relative to the audits dir) at `rev`, or None."""
    r = subprocess.run(["git", "-C", audits, "show", f"{rev}:./{rel}"], capture_output=True, text=not binary)
    return r.stdout if r.returncode == 0 else None


def load(p):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def tp_dir(rd, tp):
    return os.path.join(rd, TP_DIR, tp)


def tps(rd):
    """[TP<k>] in order."""
    d = os.path.join(rd, TP_DIR)
    ns = sorted(int(TP_RE.match(x).group(1)) for x in (os.listdir(d) if os.path.isdir(d) else [])
                if TP_RE.match(x) and os.path.isfile(os.path.join(d, x, "BEGIN.json")))     # begun, not a stray dir
    return [f"TP{n}" for n in ns]


def attempts(rd, tp):
    """[n] of the attempts whose FACTS.json is committed... and present on disk (A<n>/FACTS.json)."""
    d = tp_dir(rd, tp)
    return sorted(int(ATTEMPT_RE.match(x).group(1)) for x in (os.listdir(d) if os.path.isdir(d) else [])
                  if ATTEMPT_RE.match(x) and os.path.isfile(os.path.join(d, x, "FACTS.json")))


def reviews(rd, tp):
    """[(n, m, name)] of every review issued for TP (its token commitment exists), in order."""
    d = os.path.join(tp_dir(rd, tp), ".lane-auth")
    out = []
    for f in (os.listdir(d) if os.path.isdir(d) else []):
        m = REVIEW_RE.match(f)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), f))
    return sorted(out)


def committed(audits, path):
    return bool(git(audits, "log", "-1", "--format=%H", "--", os.path.relpath(path, audits), check=False))


def commit_paths(audits, paths, subject):
    """Commit exactly `paths` (relative or absolute) under `subject` (project.commit_only, the record lock)."""
    return project.commit_only([os.path.abspath(p) for p in paths], subject, repo=audits)


def first_pin(rd):
    return project.first_pin(rd) or {}


def first_pin_problem(rd):
    """None when this run may patch tools (release at its first pin, ownership >= 4), else why not."""
    fp = first_pin(rd)
    if not fp:
        return "the run has no committed pin"
    if project.mode(fp.get("config") or {}) != "release":
        return ("the run's mode at its first pin is not release: in dev mode a tool fault stops the run and a "
                "maintainer fixes the tool (dev refuses tool patches)")
    try:
        if int(fp.get("ownership", 1)) < OWNERSHIP_SINCE:
            return (f"the run was pinned under ownership {fp.get('ownership', 1)}, before tool patches existed "
                    f"(ownership {OWNERSHIP_SINCE}): its records have no owner for tool-patches/, so it cannot patch")
    except (TypeError, ValueError):
        return "the first pin's ownership version cannot be read"
    roles = fp.get("codex_agents")
    if roles is not None and f"{REVIEWER_ROLE}.toml" not in ((roles or {}).get("sha256") or {}):
        return (f"a Codex run whose first pin has no {REVIEWER_ROLE} role: its reviewer could not be spawned as a "
                f"pinned role")
    return None


def pin_doc(rd):
    return load(os.path.join(rd, "TOOLING_PIN.json")) or {}


def stop_doc(rd, s):
    return load(os.path.join(rd, "stops", s, "STOP.json"))


def stop_open(rd, s):
    return bool(stop_doc(rd, s)) and not os.path.exists(os.path.join(rd, "stops", s, "CLOSED.json"))


def tp_state(rd, tp, audits=None):
    """"applied", "withdrawn" or "open"."""
    audits = audits or project.AUDITS
    if apply_commit(audits, tp):
        return "applied"
    if os.path.exists(os.path.join(tp_dir(rd, tp), "WITHDRAWN.json")):
        return "withdrawn"
    return "open"


def apply_commit(audits, tp):
    """The commit "tool-patch TP<k> apply", or None."""
    hs = git(audits, "log", "--format=%H", f"--grep=^tool-patch {tp} apply$", check=False).split()
    return hs[-1] if hs else None


# --- the patch: files, allowed set ----------------------------------------------------------------------------
DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)


def patch_files(text):
    """[(path, kind)] of a git diff; kind "new", "modified" (Refused for deletes, renames, mode changes, binaries)."""
    out = []
    for blk in re.split(r"(?=^diff --git )", text, flags=re.M):
        if not blk.startswith("diff --git "):
            if blk.strip():
                raise Refused("patch.diff has text before its first `diff --git` header")
            continue
        m = DIFF_FILE.match(blk.splitlines()[0])
        if not m or m.group(1) != m.group(2):
            raise Refused(f"patch.diff: unreadable or renaming header {blk.splitlines()[0][:100]!r}")
        if re.search(r"^(deleted file mode|rename from|copy from|old mode|new mode|Binary files|GIT binary patch)",
                     blk, re.M):
            raise Refused(f"patch.diff: {m.group(1)}: a tool patch only adds or edits text files (no deletion, "
                          f"rename, mode change or binary)")
        out.append((m.group(1), "new" if re.search(r"^new file mode \d+$", blk, re.M) else "modified"))
    if not out:
        raise Refused("patch.diff changes nothing")
    return out


def diff_key(text):
    """The identity of a diff for the "never resubmitted" rule, whitespace-insensitive (re-check 2026-10-25, gap 3: a
    rejected diff with one blank line added had another sha256 and was accepted): per file (by path), its removed and
    added lines in order, each with ALL whitespace dropped, lines left empty dropped; hunk headers (line numbers),
    context lines and index lines ignored. Two diffs with the same key make the same change up to whitespace."""
    files, cur, hunk = {}, None, False
    for line in text.splitlines():
        m = DIFF_FILE.match(line)
        if m:
            cur, hunk = files.setdefault(m.group(2), []), False
            continue
        if line.startswith("@@"):
            hunk = True
            continue
        if cur is None or not hunk or line[:1] not in "+-":
            continue
        t = "".join(line[1:].split())
        if t:
            cur.append(line[0] + t)
    return sha_bytes(json.dumps(sorted((k, v) for k, v in files.items() if v)).encode("utf-8"))


SIGNED_RE = re.compile(r"(^|/)(SIGNOFF[^/]*|APPROVED_FINGERPRINTS[^/]*|REAPPROVAL[^/]*)$", re.I)
GIT_RULES = (".gitignore", ".gitattributes")


def allowed(path):
    """Is `path` (relative to audits/) a file a tool patch may touch (OPERATOR-AUTHORITY, approver 2026-10-26)? Any
    file of the apparatus -- the scripts, tests, Lean tails, and the protocol text: AUDIT_PROTOCOL.md, RUN.md, run/,
    agents/, skills/ -- except the git rules (they decide what git shows, the provenance's ground) and anything a
    signature covers (SIGNOFF*, APPROVED_FINGERPRINTS*, REAPPROVAL*). Never a path outside audits/ (the project's
    Lean), never a record (the rounds dir is no tooling path; structure_problems also refuses it by name). The
    proof-validity core is refused by structure_problems (CORE, read from the first pin)."""
    import integrity
    parts = path.split("/")
    if not path or path.startswith("/") or ".." in parts or "" in parts or parts[0] == ".git":
        return False
    if SIGNED_RE.search(path) or path in GIT_RULES:
        return False
    return integrity.is_tooling(path)


# --- what a patch may never do (re-check 3, 2026-10-25) --------------------------------------------------------------
# A. A tool patch modifies files of the apparatus (the first pin's, or one an applied patch added) and may add files
#    (OPERATOR-AUTHORITY, approver 2026-10-26; before: only its regression test), under no name Python could import in
#    place of another module (the re-check added audits/re.py, which shadowed the stdlib `re` for every script and
#    blinded phase0's sorry scan under an environment variable, with one approval). A fix that needs new code puts it
#    inside an existing file. integrity.py --check flags, in every check, a tooling file the first pin did not have
#    (manifest_problems).
# B. The PROOF-VALIDITY CORE is immutable to tool patches: the files that implement the Lean build check and the
#    no-sorry token scan (phase0.py), the axiom sweep (axiom_sweep.py/.sh and its Lean, axiom_sweep_tail.lean), the
#    approved-statement freeze (fingerprint.py, fingerprint_tail.lean, and olean_parts.lean, the Lean comparison of a
#    docstring-only edit), and the provenance checks of the route itself (tool_patch.py, integrity.py). The set is
#    read from the FIRST pin's tool_patch.py (core_files), so no patch can shrink it; a patch touching one is refused
#    at prepare, at apply and by every link check: no reviewer can approve it (the re-check edited
#    axiom_sweep_tail.lean to accept project-namespace axioms; the floor has no axiom canary, the sweep's selftest is
#    Lean-tier and the blast radius does not run it). Such a fault is a maintainer's in dev; in release a Lean-side
#    workaround, else stops.py core-fault and close --core-fault (the check marked not established).
CORE = ("phase0.py", "axiom_sweep.py", "axiom_sweep.sh", "axiom_sweep_tail.lean", "fingerprint.py",
        "fingerprint_tail.lean", "olean_parts.lean", "tool_patch.py", "integrity.py")
CORE_RE = re.compile(r"^CORE = (\([^)]*\))", re.M)
# C. THE GUARD STAYS FIXED (coordinator, 2026-10-26): a patch may touch the protocol text, but never the prompts of the
#    reviewers that judge a patch, a core fault or an acknowledgment, nor the code that renders them -- otherwise a
#    patch could weaken its own reviewer. integrity.ACK_PROMPT and tool_patch.py are in CORE; these blocks of
#    non-core files are compared, pinned vs patched, at prepare, at apply and by every link check (guard_problems):
#    any change inside one, or its removal, is refused whatever the reviewers say.
GUARDED = (("AUDIT_PROTOCOL.md", "### Tool-patch reviewer prompt\n", "\n### "),
           ("AUDIT_PROTOCOL.md", "### Common rules for every other subagent\n", "\n### "),   # the reviewer gets them
           ("prompt.py", "def render_tool_patch(", "\ndef "),
           ("prompt.py", "def blocks_after(", "\ndef "),
           ("prompt.py", "SUBAGENT_COMMON_HEADING = ", "\n"),
           ("prompt.py", "TOOL_PATCH_HEADING = ", "\n"),
           ("stops.py", "CORE_REVIEW_PROMPT = ", "\ndef other_agent_seals("))
SHADOWING = (frozenset(getattr(sys, "stdlib_module_names", ())) | frozenset(sys.builtin_module_names)
             | {"sitecustomize", "usercustomize", "__main__", "__init__"})
IMPORT_DIRS = ("", "tests", "tests/regressions")    # where a script of the apparatus (or a test) imports from
_TREES = {}


def module_name(name):
    """The module a directory entry would be imported as (`re.py`, `re/`, `re.cpython-314.so` -> `re`)."""
    return os.path.basename(name.rstrip("/")).split(".")[0]


def importable(p):
    """Would Python import the directory entry `p` as a module: a file with a module suffix (.py, .pyc, .so, ...) or
    a regular package (a directory with __init__); a plain directory is a namespace portion a module found later on
    the path wins over, and a rounds directory may carry any project name."""
    import importlib.machinery
    if os.path.isdir(p):
        return any(importable(os.path.join(p, "__init__" + x)) for x in importlib.machinery.all_suffixes())
    return os.path.isfile(p) and any(p.endswith(x) for x in importlib.machinery.all_suffixes())


def tooling_tree(audits, commit):
    """{path relative to audits/} of the tooling files at `commit` (None: it cannot be listed)."""
    import integrity
    key = (os.path.abspath(audits), commit)
    if key not in _TREES:
        pre = prefix(audits)
        r = subprocess.run(["git", "-C", audits, "ls-tree", "-r", "--name-only", "--full-tree", str(commit)],
                           capture_output=True, text=True)
        _TREES[key] = None if r.returncode or not commit else {
            n[len(pre):] for n in r.stdout.splitlines() if n.startswith(pre) and integrity.is_tooling(n[len(pre):])}
    return _TREES[key]


def core_files(audits, rd):
    """The proof-validity core as the run's FIRST pin defines it (its tool_patch.py's CORE), else this file's."""
    import ast
    txt = show(audits, first_pin(rd).get("audits_commit") or "", "tool_patch.py")
    m = CORE_RE.search(txt or "")
    try:
        got = ast.literal_eval(m.group(1)) if m else None
    except (ValueError, SyntaxError):
        got = None
    return tuple(got) if isinstance(got, tuple) and got else CORE


def guarded_block(text, start, end):
    """The text of a GUARDED block (from `start` to the next `end`), None when `text` lacks it."""
    i = (text or "").find(start)
    if i < 0:
        return None
    j = text.find(end, i + len(start))
    return text[i:j if j >= 0 else len(text)]


def guard_problems(audits, base, patch):
    """[why the patch changes a GUARDED block] (C above): each guarded file the patch touches, as committed at `base`
    and with the patch applied to it, must hold its block unchanged."""
    out = []
    try:
        touched = {p for p, _k in patch_files(patch)}
    except Refused:
        return out
    for rel, start, end in GUARDED:
        if rel not in touched:
            continue
        old = show(audits, base, rel)
        tmp = tempfile.mkdtemp(prefix="tp-guard-")
        try:
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)) or tmp, exist_ok=True)
            if old is not None:
                open(os.path.join(tmp, rel), "w", encoding="utf-8").write(old)
            open(os.path.join(tmp, "x.diff"), "w", encoding="utf-8").write(patch)
            r = subprocess.run(["git", "apply", f"--include={rel}", "x.diff"], cwd=tmp, capture_output=True, text=True)
            new = open(os.path.join(tmp, rel), encoding="utf-8").read() if not r.returncode and os.path.exists(
                os.path.join(tmp, rel)) else None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        ob = guarded_block(old, start, end)
        if ob is None:
            continue
        if new is None or guarded_block(new, start, end) != ob:
            out.append(f"{rel}: the patch changes the guarded block starting {start.strip()!r} (the prompt of a reviewer "
                       f"that judges patches, core faults or acknowledgments, or the code rendering it): the guard stays "
                       f"fixed, no reviewer can approve a change to it")
    return out


def shadow_problem(path, tree):
    """Why the new file `path` could be imported in place of another module (None: it cannot)."""
    if os.path.dirname(path) not in IMPORT_DIRS:
        return None
    mn = module_name(path)
    if mn in SHADOWING:
        return f"{path} shadows the Python standard-library module `{mn}`"
    mine = {module_name(x) for x in tree or () if os.path.dirname(x) in IMPORT_DIRS and x != path}
    if mn in mine:
        return f"{path} has the name of the apparatus module `{mn}`"
    return None


def patch_added(audits):
    """{path relative to audits/} of every file an applied tool patch ("tool-patch TP<k> apply") added."""
    added = set()
    for h in git(audits, "log", "--format=%H", "--grep=^tool-patch TP[1-9][0-9]* apply$", check=False).split():
        added |= set(git(audits, "diff", "--relative", "--name-only", "--diff-filter=A", f"{h}^", h,
                         check=False).splitlines())
    return added


def structure_problems(audits, rd, files, reg):
    """[why the patch's file list is not allowed] (A, B above): a path outside the apparatus (the project's Lean, a
    record, a signed document, the git rules), a core file, a new file with a shadowing name, a modified file the
    apparatus does not have."""
    out = []
    core = core_files(audits, rd)
    tree = tooling_tree(audits, first_pin(rd).get("audits_commit") or "")
    if tree is None:
        return ["the first pin's apparatus cannot be listed (its audits_commit is not in the audits history)"]
    rel_rd = os.path.relpath(rd, audits) if rd else None
    have = None
    for p, kind in files:
        if not allowed(p) or (rel_rd and rel_rd != "." and (p == rel_rd or p.startswith(rel_rd + "/"))):
            out.append(f"{p} is outside what a tool patch may touch: only the apparatus under audits/ (scripts, tests, "
                       f"the protocol text), never the project's Lean, a round record, a signed document (SIGNOFF*, "
                       f"APPROVED_FINGERPRINTS*, REAPPROVAL*) or the git rules")
        elif p in core:
            out.append(f"{p} is in the proof-validity core ({', '.join(core)}): immutable to tool patches, no reviewer "
                       f"can approve a change to it (release: withdraw, then a Lean-side workaround, else stops.py close "
                       f"--core-fault {p} after stops.py core-fault and a fresh reviewer's approval, RUN.md \"Tool patches\"; never a "
                       f"wait for a maintainer)")
        elif kind == "new" and shadow_problem(p, tree):
            out.append(f"{shadow_problem(p, tree)}: name the file otherwise")
        elif kind != "new" and p not in tree:
            have = patch_added(audits) if have is None else have
            if p not in have:
                out.append(f"{p} is not a file of the run's apparatus (the first pin's, or one an applied tool patch "
                           f"added): a tool patch modifies only those, or adds a new file")
    return out


def manifest_problems(audits, rd):
    """[(severity, "[tooling] ...")] for integrity.py --check (A above): a tooling file at the current pin that the
    first pin's apparatus did not have is FAIL (release; dev: a NOTE, a maintainer's re-pin may add files) unless an
    applied tool patch added it as its regression test; an entry of audits/, tests/ or tests/regressions/ on disk
    whose name shadows a standard-library module is FAIL in every mode."""
    out = []
    fp = first_pin(rd)
    fpc, cur = fp.get("audits_commit"), pin_doc(rd).get("audits_commit")
    try:
        owned = int(fp.get("ownership", 1)) >= OWNERSHIP_SINCE
    except (TypeError, ValueError):
        owned = True        # an unreadable ownership version is judged by the rule, never exempted
    # a run pinned before tool patches existed (ownership < 4) cannot patch tools (first_pin_problem), and its re-pins
    # are judged by the rules of its time, as integrity.release_repin_problems judges them: the files a later
    # apparatus added are no tool patch's (the snapshot replay of old runs read them as FAIL[tooling])
    if fpc and cur and fpc != cur and owned:
        first, now = tooling_tree(audits, fpc), tooling_tree(audits, cur)
        if first is None or now is None:
            out.append(("FAIL", f"[tooling] the first pin's or the current pin's apparatus cannot be listed "
                                f"({str(fpc)[:11]}, {str(cur)[:11]})"))
            first, now = first or set(), set()
        added = patch_added(audits)
        sev = "FAIL" if project.mode(fp.get("config") or {}) == "release" else "note"
        for p in sorted(now - first):
            if p in added and not shadow_problem(p, now):
                continue
            out.append((sev, f"[tooling] {p} is not a file of the first pin's apparatus ({fpc[:11]}) nor one an "
                             f"applied tool patch added: restore the tooling"))
    for d in IMPORT_DIRS:
        dd = os.path.join(audits, d)
        for e in sorted(os.listdir(dd)) if os.path.isdir(dd) else ():
            if module_name(e) in SHADOWING and importable(os.path.join(dd, e)):
                out.append(("FAIL", f"[tooling] audits/{os.path.join(d, e)} shadows the Python standard-library module "
                                    f"`{module_name(e)}` for every script that imports from audits/{d}: remove it, "
                                    f"after checking what wrote it"))
    return out


# --- extracting an apparatus (T34's pattern) --------------------------------------------------------------------
def extract(audits, commit, dest):
    """Write the tooling of the audits directory at `commit` into `dest` (a fresh directory); return dest."""
    import integrity
    pre = prefix(audits)
    names = [n[len(pre):] for n in git(audits, "ls-tree", "-r", "--name-only", "--full-tree", commit).splitlines()
             if n.startswith(pre)]
    os.makedirs(dest, exist_ok=True)
    for n in names:
        if not integrity.is_tooling(n) or n.split("/")[0] in ("projects",):
            continue
        b = show(audits, commit, n, binary=True)
        if b is None:
            continue
        p = os.path.join(dest, n)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b)
    tmpl = show(audits, commit, "project_template.json", binary=True)
    if tmpl is not None:
        open(os.path.join(dest, "project_template.json"), "wb").write(tmpl)
    return dest


def scratch_tree(audits, commit, patch=None):
    """(scratch root, apparatus dir): <root>/audits holds the tooling at `commit` (with `patch` applied), <root> a
    git repository with one empty commit (the selftests that read the clone's HEAD)."""
    root = tempfile.mkdtemp(prefix="tool-patch-")
    subprocess.run(["git", "init", "-q", root], check=True)
    for k, v in (("user.email", "tool-patch@localhost"), ("user.name", "tool-patch")):
        subprocess.run(["git", "-C", root, "config", k, v], check=True)
    subprocess.run(["git", "-C", root, "commit", "-q", "--allow-empty", "-m", "scratch"], check=True)
    d = extract(audits, commit, os.path.join(root, "audits"))
    if patch is not None:
        pf = os.path.join(root, "patch.diff")
        open(pf, "w", encoding="utf-8").write(patch)
        r = subprocess.run(["git", "apply", "--unsafe-paths", "--directory=audits", pf], cwd=root,
                           capture_output=True, text=True)
        if r.returncode:
            shutil.rmtree(root, ignore_errors=True)
            raise Refused(f"patch.diff does not apply to the pinned apparatus: {r.stderr.strip()[:300]}")
        os.remove(pf)
    return root, d


# a script of an apparatus directory D run on the LIVE project and records (project.AUDITS/REPO overridden)
LAUNCH = ("import os, sys, runpy; sys.dont_write_bytecode = True; d, a, r, s = sys.argv[1:5]; "
          "sys.argv = [os.path.join(d, s)] + sys.argv[5:]; sys.path.insert(0, d); import project; "
          "project.AUDITS, project.REPO, project.PROJECTS = a, r, os.path.join(a, 'projects'); "
          "runpy.run_path(os.path.join(d, s), run_name='__main__')")


def run_with(code_dir, script, args, timeout=3600):
    """(exit, output) of `script` of apparatus `code_dir` on the live records."""
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", LAUNCH, code_dir, project.AUDITS, project.REPO, script,
                            *args], cwd=project.REPO, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout} s)"


# --- FACTS ---------------------------------------------------------------------------------------------------------
CODED = re.compile(r"^\s*([A-Z]+\[[a-z0-9-]+\])\s*(.*)$")


# FACTS are re-derived by a fresh reviewer and compared with FACTS.json (facts_text): what they record must not carry
# what differs between two honest runs -- the random scratch directories (scratch_tree, mirror), other temporary
# names, object addresses (Codex e2e TP1: a regression's traceback tail kept /tmp/tool-patch-<random>/, and the
# reviewer had to reject an honest patch). Exit codes and every other character are recorded as they are.
SCRATCH = "<scratch>"
_ADDR = re.compile(r"\b0x[0-9a-fA-F]{6,}\b")


def scrub(text, roots=()):
    """`text` with each scratch root in `roots` (as given and resolved) -> <scratch>, any other name directly under
    the temporary directory -> <tmp>, and object addresses -> 0x…"""
    for r in sorted({v for r in roots if r for v in (r.rstrip("/"), os.path.realpath(r))}, key=len, reverse=True):
        text = text.replace(r, SCRATCH)
    for t in sorted({tempfile.gettempdir().rstrip("/"), os.path.realpath(tempfile.gettempdir())}, key=len, reverse=True):
        text = re.sub(re.escape(t) + r"/[^\s/'\"():,]+", "<tmp>", text)
    return _ADDR.sub("0x…", text)


def _outcome(rc, out, roots=()):
    out = scrub(out, roots)
    lines = sorted({" ".join(f"{m.group(1)} {m.group(2)}".split())[:300] for m in map(CODED.match, out.splitlines())
                    if m and not m.group(1).startswith(("NOTE[", "DISCLOSED["))})
    return {"exit": rc, "lines": lines}


def blast_checks(cfg, stop_check=None):
    """[[script, args]] of every read-only check of every round (and the run-wide ones), and the stop's own check
    (`stop_check`, the command its stop re-runs), which is always run (FORMALIZE_TP_NO_LEAN leaves out only the
    other Lean-backed scope checks)."""
    out = [["integrity.py", ["--check"]], ["make_report.py", ["--check"]], ["make_report.py", ["--check", "--delivery"]],
           ["decisions.py", ["--check"]], ["result_status.py", ["--check"]]]
    for p in project.rounds(cfg):
        r = os.path.basename(p)
        out += [["lanecheck.py", ["--round", r]], ["prompt.py", ["--lanes", "--round", r, "--verify-written"]]]
        if not os.environ.get("FORMALIZE_TP_NO_LEAN"):
            out.append(["scope.py", ["--verify", "--round", r]])
        if project.round_kind(p) == "statements":
            out.append(["signoff.py", ["check", "--round", r]])
    out = [[s, a + (["--project", cfg["name"]] if cfg.get("name") else [])] for s, a in out]
    m = re.match(r"^python3 (?:-B )?audits/([a-z_0-9]+\.py)((?: \S+)*)$", " ".join(str(stop_check or "").split()))
    if m:
        args = m.group(2).split()
        own = [m.group(1), args + (["--project", cfg["name"]] if cfg.get("name") and "--project" not in args else [])]
        if not any(c[0] == own[0] and sorted(c[1]) == sorted(own[1]) for c in out):
            out.insert(0, own)
    return out


def mirror(patch=None):
    """(scratch root, project dir): a copy of the project as it stands -- the Lean repository and the audits repository
    cloned (--shared: nothing is written into them) at their HEADs, the audits directory's uncommitted files copied
    over, the Lean build linked -- with `patch` applied to its tooling. Every check runs there exactly as in the
    project (`python3 audits/<script>`), so no module's own idea of the repository can see the scratch tree."""
    import integrity
    # never under /tmp: a project's work_dir under a temporary directory is a hard config error (project.problems)
    base = os.path.join(project.REPO, project.FW, "tool-patch")
    os.makedirs(base, exist_ok=True)
    try:
        project._exclude(project.FW + "/")
    except Exception:       # noqa: BLE001 -- the exclude is a convenience; the mirror is removed afterwards
        pass
    root = tempfile.mkdtemp(prefix="tp-mirror-", dir=base)
    proj = os.path.join(root, "proj")
    rtop, atop = git(project.REPO, "rev-parse", "--show-toplevel"), audit_top(project.AUDITS)
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", rtop, proj], check=True, capture_output=True)
    subprocess.run(["git", "-C", proj, "checkout", "-q", "--detach", git(rtop, "rev-parse", "HEAD")], check=True,
                   capture_output=True)
    rel_a = os.path.relpath(project.AUDITS, rtop)
    adir = os.path.join(proj, rel_a)
    if atop != rtop:
        shutil.rmtree(adir, ignore_errors=True)
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", atop, adir], check=True, capture_output=True)
        subprocess.run(["git", "-C", adir, "checkout", "-q", "--detach", git(atop, "rev-parse", "HEAD")], check=True,
                       capture_output=True)
    for line in git(project.AUDITS, "status", "--porcelain", "--untracked-files=all", "--", ".", check=False).splitlines():
        rel = line[3:].strip().strip('"')
        rel = os.path.relpath(os.path.join(git(project.AUDITS, "rev-parse", "--show-toplevel"), rel), project.AUDITS)
        src = os.path.join(project.AUDITS, rel)
        if integrity.is_tooling(rel) or not os.path.isfile(src) or "__pycache__" in rel:
            continue
        os.makedirs(os.path.dirname(os.path.join(adir, rel)), exist_ok=True)
        shutil.copy2(src, os.path.join(adir, rel))
    for extra in (".lake", "lake-packages"):
        if os.path.exists(os.path.join(rtop, extra)) and not os.path.exists(os.path.join(proj, extra)):
            os.symlink(os.path.join(rtop, extra), os.path.join(proj, extra))
    if patch is not None:
        pf = os.path.join(root, "patch.diff")
        open(pf, "w", encoding="utf-8").write(patch)
        pre = git(adir, "rev-parse", "--show-prefix")
        r = subprocess.run(["git", "-C", adir, "apply"] + ([f"--directory={pre.rstrip('/')}"] if pre else []) + [pf],
                           capture_output=True, text=True)
        if r.returncode:
            shutil.rmtree(root, ignore_errors=True)
            raise Refused(f"patch.diff does not apply to the project's tooling: {r.stderr.strip()[:300]}")
    return root, proj


def _run_in(proj, script, args, timeout=3600):
    try:
        r = subprocess.run([sys.executable, "-B", os.path.join("audits", script), *args], cwd=proj, capture_output=True,
                           text=True, timeout=timeout, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout} s)"


def _patched_outcome(o):
    """The patched mirror's tooling differs from its pin by the patch itself: its FAIL[tooling] lines say nothing
    about the records (and a check that failed only on them passed)."""
    lines = [l for l in o["lines"] if not l.startswith("FAIL[tooling]")]
    return {"exit": 0 if o["exit"] and not lines and o["lines"] else o["exit"], "lines": lines}


# a delivery precondition (make_report.py --check --delivery's RED[deliver]: a prepared document stale or changed, a
# reader gate on it, what a prepared document must name) is cured by preparing again and reading the regenerated
# documents; it is never what an earlier REVIEW was shown or scoped. DOC-FIX replay of conf1: a generator patch fixing
# cut-off text made the prepared documents stale, the blast radius called that PASS->FAIL, affects-review-inputs was
# forced and --deliver demanded a full round for a change to how a record cell is printed
DELIVERY_ONLY_RE = re.compile(r"^RED\[deliver\]")


def pass_to_fail(changed):
    """[check] of the changed rows that turned PASS->FAIL or gained a failure line -- except a row whose new lines
    are all delivery preconditions (DELIVERY_ONLY_RE): those are cured by the next prepare and its readers."""
    out = []
    for r in changed:
        new = set(r["after"]["lines"]) - set(r["before"]["lines"])
        if not ((r["before"]["exit"] == 0 and r["after"]["exit"] != 0) or new):
            continue
        if new and all(DELIVERY_ONLY_RE.match(l) for l in new):
            continue
        out.append(r["check"])
    return out


def blast_radius(cfg, pinned=None, patched=None, patch=None, stop_check=None):
    """FACTS (c): every read-only check of every round, run in a mirror of the project with the pinned tooling and
    in one with the patch applied; what changes; PASS->FAIL."""
    if RUNNER:
        got = RUNNER("blast", cfg, pinned, patched)
        if got is not None:
            return got
    checks = blast_checks(cfg, stop_check)
    r0, p0 = mirror()
    r1, p1 = None, None
    try:
        r1, p1 = mirror(patch)
        with concurrent.futures.ThreadPoolExecutor(max_workers=JOBS) as ex:
            before = list(ex.map(lambda c: _outcome(*_run_in(p0, c[0], c[1]), roots=(r0,)), checks))
            after = list(ex.map(lambda c: _patched_outcome(_outcome(*_run_in(p1, c[0], c[1]), roots=(r1,))), checks))
    finally:
        shutil.rmtree(r0, ignore_errors=True)
        if r1:
            shutil.rmtree(r1, ignore_errors=True)
    rows = [{"check": " ".join([c[0]] + c[1]), "before": b, "after": a} for c, b, a in zip(checks, before, after)]
    changed = [r for r in rows if r["before"] != r["after"]]
    p2f = pass_to_fail(changed)
    return {"checks": len(rows), "changed": changed, "pass_to_fail": p2f,
            "exits": [[r["check"], r["before"]["exit"], r["after"]["exit"]] for r in rows]}


def pure_selftests(code_dir):
    code = "import sys,json; sys.path.insert(0, sys.argv[1]); import project; print(json.dumps(project.scripts(selftest='pure')))"
    r = subprocess.run([sys.executable, "-I", "-B", "-c", code, code_dir], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise Refused(f"the patched apparatus cannot list its selftests: {r.stderr.strip()[-300:]}")
    return [n + ".py" for n in json.loads(r.stdout.strip().splitlines()[-1])]


def run_selftest(code_dir, script, extra=()):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for k in ("FORMALIZE_TEST_MODE", "FORMALIZE_TEST_INVOLVEMENT"):
        env.pop(k, None)
    try:
        r = subprocess.run([sys.executable, "-B", os.path.join(code_dir, script), "--selftest", *extra],
                           cwd=os.path.dirname(code_dir), capture_output=True, text=True, env=env, timeout=3600)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "(timed out)"


def first_pin_selftests(audits, rd):
    """The pure selftests of the run's FIRST pin, listed by ITS project.py (extracted from git): the set every patch
    must pass (re-check 2026-10-25, gap 2: TP-a moved lane_auth out of project.py's pure tier, so TP-b's facts never
    ran lane_auth's selftest, and TP-b disabled its prompt check with one approval)."""
    fpc = first_pin(rd).get("audits_commit")
    if not fpc:
        raise Refused("the run's first pin names no audits commit: its selftests cannot be listed")
    tmp = tempfile.mkdtemp(prefix="tp-first-")
    try:
        return pure_selftests(extract(audits, fpc, os.path.join(tmp, "audits")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def selftest_names(audits, rd, code_dir):
    """(names, first): the selftests fact (b) runs on the patched apparatus in `code_dir` -- every pure selftest of the
    first pin (`first`; a patch cannot remove one, gap 2), then any the patched project.py adds."""
    first = first_pin_selftests(audits, rd)
    return first + [n for n in pure_selftests(code_dir) if n not in first], first


def selftests(code_dir, names, first0=()):
    """FACTS (b): the selftests `names` (selftest_names) on the patched apparatus, in parallel; every one must pass."""
    if RUNNER:
        got = RUNNER("selftests", code_dir, names)
        if got is not None:
            return got
    return run_selftests(code_dir, names, first0)


def run_selftests(code_dir, names, first0=()):
    with concurrent.futures.ThreadPoolExecutor(max_workers=JOBS) as ex:
        res = list(ex.map(lambda n: run_selftest(code_dir, n), names))
    first = {n: r for n, r in zip(names, res) if r[0] != 0}
    # a selftest failing under the parallel load is run once more alone (bench1 replay: scope.py's selftest is
    # timing-sensitive); a pass then is recorded as such, never hidden
    again = {n: run_selftest(code_dir, n) for n in first}
    failed = [n for n, r in again.items() if r[0] != 0]
    return {"run": names, "first_pin": list(first0), "failed": failed, "passes": not failed,
            "passed_alone": sorted(set(first) - set(failed)), "tails": {n: scrub(again[n][1], (os.path.dirname(code_dir),)).strip().splitlines()[-3:]
                                                             for n in failed}}


def regression(pinned, patched, rel):
    """FACTS (a): the new regression test fails with the pinned apparatus and passes with the patched one."""
    if RUNNER:
        got = RUNNER("regression", pinned, patched, rel)
        if got is not None:
            return got
    test = os.path.join(patched, rel)

    def run(app):
        try:
            r = subprocess.run([sys.executable, "-I", "-B", test, "--apparatus", app], cwd=os.path.dirname(patched),
                               capture_output=True, text=True, timeout=1800, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            return {"exit": r.returncode, "tail": scrub(r.stdout + r.stderr, (os.path.dirname(pinned),
                                                                               os.path.dirname(patched))).strip().splitlines()[-12:]}
        except subprocess.TimeoutExpired:
            return {"exit": 124, "tail": ["(timed out)"]}
    a, b = run(pinned), run(patched)
    return {"test": rel, "pinned": a, "patched": b, "passes": a["exit"] not in (0, 124) and b["exit"] == 0}


def floor_mutants(audits, rd):
    """[(id, file, old, new, selftest, extra)] of the floor, read from tests/mutant_list.py AT THE FIRST PIN."""
    fp = first_pin(rd)
    src = show(audits, fp.get("audits_commit") or "", "tests/mutant_list.py") if fp else None
    if not src:
        raise Refused("the first pin's tests/mutant_list.py cannot be read: no floor")
    ns = {"__name__": "mutant_list_first_pin"}
    exec(compile(src, "mutant_list(first pin)", "exec"), ns)       # noqa: S102 -- the pinned list, trusted
    floor = set(ns.get("FLOOR") or ())
    if not floor:
        raise Refused("the first pin's tests/mutant_list.py has no FLOOR")
    ms = [m[:6] for m in ns.get("MUTANTS") or [] if m[0].split()[0] in floor]
    missing = sorted(floor - {m[0].split()[0] for m in ms})
    if missing:
        raise Refused(f"the first pin's FLOOR names mutants it does not define: {', '.join(missing)}")
    return ms


def floor_pattern_hits(ms, read):
    """[(id, why)] of floor mutants whose pattern is not found exactly once (`read(file)` -> text or None)."""
    out = []
    for mid, f, old, _new, _st, _x in ms:
        n = (read(f) or "").count(old)
        if n != 1:
            out.append((mid.split()[0], f"pattern found {n}x in {f}"))
    return out


def run_floor_mutant(code_dir, m, mutate=True):
    """"killed" / "survived" / "crashed" / "missing" of floor mutant `m` on the apparatus in `code_dir`; with
    mutate=False its selftest on the apparatus unmutated: "passes" or "fails" (the floor's baseline)."""
    mid, f, old, new, st, extra = m
    root = tempfile.mkdtemp(prefix="tp-floor-")
    try:
        subprocess.run(["git", "init", "-q", root], check=True)
        subprocess.run(["git", "-C", root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "scratch"], check=True)
        d = os.path.join(root, "audits")
        shutil.copytree(code_dir, d, ignore=shutil.ignore_patterns("__pycache__"))
        p = os.path.join(d, f or "")
        if not mutate:
            return "passes" if run_selftest(d, st, [x for x in extra if x != "--project" and x])[0] == 0 else "fails"
        src = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        if src.count(old) != 1:
            return "missing"
        open(p, "w", encoding="utf-8").write(src.replace(old, new))
        rc, out = run_selftest(d, st, [x for x in extra if x != "--project" and x])
        if rc and ("Traceback (most recent call last)" in out or "SyntaxError" in out or rc == 3
                   or not any(l.strip().lower().startswith("selftest") for l in out.splitlines())):
            return "crashed"
        return "killed" if rc else "survived"
    finally:
        shutil.rmtree(root, ignore_errors=True)


NESTED = "FORMALIZE_TP_SELFTEST"     # set by tool_patch.py --selftest for every process it starts


def floor(audits, rd, code_dir):
    """FACTS (d): the floor on the apparatus in `code_dir`: [(id, why)] hits (pattern missing, not killed, or its
    selftest failing unmutated). Inside a --selftest process (or one it started, NESTED) the floor mutants of the
    tool-patch machinery itself (selftest tool_patch.py) are judged by their pattern only: running tool_patch.py's
    selftest on each would run its own real floor again, a recursion (a real prepare runs them all)."""
    ms = floor_mutants(audits, rd)
    if RUNNER:
        got = RUNNER("floor", code_dir, ms)
        if got is not None:
            return got
    return floor_judge(code_dir, ms)


def floor_judge(code_dir, ms):
    """{"ids", "hits"} of floor mutants `ms` on the apparatus in `code_dir`. A kill counts only when the selftest
    PASSES on that apparatus unmutated (its baseline) and fails under the mutant: a selftest that fails unmutated
    "kills" every mutant, so each of its mutants is then a hit, never a kill (re-check 2026-10-25, gap 2: TP-b broke
    lane_auth's selftest, and LA8, the prompt check it disabled, counted as killed)."""
    own = "--selftest" in sys.argv or os.environ.get(NESTED) == "1"
    by_pattern = lambda m: own and m[4] == "tool_patch.py"
    key = lambda m: (m[4], tuple(x for x in m[5] if x != "--project" and x))
    groups = sorted({key(m) for m in ms if not by_pattern(m)})

    def judge(m):
        if by_pattern(m):
            p = os.path.join(code_dir, m[1])
            return "killed" if os.path.exists(p) and open(p, encoding="utf-8").read().count(m[2]) == 1 else "missing"
        if base.get(key(m)) != "passes":
            return f"baseline: {m[4]}'s selftest fails on the patched apparatus unmutated (a floor violation, never a kill)"
        return run_floor_mutant(code_dir, m)
    base_m = lambda g: run_floor_mutant(code_dir, (None, None, None, None, g[0], list(g[1])), mutate=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=JOBS) as ex:
        base = dict(zip(groups, ex.map(base_m, groups)))
    base.update({g: base_m(g) for g, r in list(base.items()) if r != "passes"})    # failing under load: once alone
    with concurrent.futures.ThreadPoolExecutor(max_workers=JOBS) as ex:
        res = list(ex.map(judge, ms))
    hits = [{"id": m[0].split()[0], "why": r} for m, r in zip(ms, res) if r != "killed"]
    return {"ids": [m[0].split()[0] for m in ms], "hits": hits}


def diagnosis_problems(text):
    out = [f"DIAGNOSIS.md lacks the section {h!r}" for h in DIAG_HEADINGS if not re.search(
        rf"^{re.escape(h)}\s*\n+(?!##)\S", text, re.M)]
    if not AFFECTS_RE.search(text):
        out.append("DIAGNOSIS.md lacks the line `affects-review-inputs: yes` or `no`")
    if not REGRESSION_RE.search(text):
        out.append("DIAGNOSIS.md lacks the line `regression: tests/regressions/<name>.py`")
    return out


def compute_facts(cfg, tp, n, diagnosis, patch, audits=None):
    """FACTS.json of attempt n (dict) and [refusal]: mechanical facts only (design §1.2, review R1/R2/R8)."""
    audits = audits or project.AUDITS
    rd = rounds_dir(cfg)
    pin = pin_doc(rd).get("audits_commit")
    refuse = diagnosis_problems(diagnosis)
    files = patch_files(patch)
    m = REGRESSION_RE.search(diagnosis)
    reg = m.group(1) if m else None
    if reg and (reg, "new") not in files:
        refuse.append(f"the regression test {reg} is not a NEW file of the patch")
    refuse += structure_problems(audits, rd, files, reg)
    refuse += guard_problems(audits, pin, patch)
    b_ = load(os.path.join(tp_dir(rd, tp), "BEGIN.json")) or {}
    sd_ = stop_doc(rd, b_.get("stop") or "") or {}
    stop_check = sd_.get("command") or sd_.get("check")
    facts = {"tp": tp, "attempt": n, "patch_sha256": sha_bytes(patch.encode("utf-8")), "pinned_commit": pin,
             "files": [p for p, _k in files], "regression_test": reg,
             "diagnosis_affects": (AFFECTS_RE.search(diagnosis) or [None, None])[1]}
    if refuse:
        return facts, refuse
    pr, pd = scratch_tree(audits, pin)
    qr, qd = None, None
    try:
        qr, qd = scratch_tree(audits, pin, patch)
        facts["regression"] = regression(pd, qd, reg)
        if not facts["regression"]["passes"]:
            refuse.append(f"fact (a): the regression test must fail with the pinned apparatus and pass with the patched "
                          f"one (pinned exit {facts['regression']['pinned']['exit']}, patched exit "
                          f"{facts['regression']['patched']['exit']}: {' | '.join(facts['regression']['patched']['tail'])})")
        # (b), (c) and (d) at once: each is slow (minutes), none depends on another. (b) runs every selftest of the
        # FIRST pin (never the list of the patched project.py: re-check 2026-10-25, gap 2)
        names, first = selftest_names(audits, rd, qd)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fb, fd, fc = (ex.submit(selftests, qd, names, first), ex.submit(floor, audits, rd, qd),
                          ex.submit(blast_radius, cfg, pd, qd, patch, stop_check))
            facts["selftests"], facts["floor"], facts["blast_radius"] = fb.result(), fd.result(), fc.result()
        if not facts["selftests"]["passes"]:
            refuse.append(f"fact (b): selftests fail on the patched apparatus: {', '.join(facts['selftests']['failed'])}")
    finally:
        shutil.rmtree(pr, ignore_errors=True)
        if qr:
            shutil.rmtree(qr, ignore_errors=True)
    forced = bool(facts["blast_radius"]["pass_to_fail"])
    facts["affects_review_inputs"] = "yes" if forced or facts["diagnosis_affects"] == "yes" else "no"
    facts["affects_forced"] = forced
    facts["required_approvals"] = 2 if facts["floor"]["hits"] else 1
    return facts, refuse


# --- the record -----------------------------------------------------------------------------------------------------
def _subjects(audits, tp):
    """[subject] of every "tool-patch <tp> ..." commit, oldest first (git: a deleted file cannot hide one)."""
    return git(audits, "log", "--reverse", "--format=%s", f"--grep=^tool-patch {tp} ", check=False).splitlines()


def rejections(rd, upto=None, audits=None):
    """[(tp, attempt, review name, "reject" | "never sealed", findings, diff_key)] of every review of every
    attempt IN THE RUN (every stop) before (tp, n) == upto that rejected its diff -- a sealed reject, or a review issued
    (its token commit) and never sealed (safety review 2026-10-25: a reject never sealed, its verdict deleted, the TP
    withdrawn and the identical diff begun again got a second reviewer's approval). Run-wide, not per stop (re-check
    2026-10-25: a diff rejected on S2 was accepted unchanged on S3, its reviewer shown no history). Read from git: the
    token, seal and diagnosis commits, and each attempt's patch.diff as its diagnosis commit recorded it."""
    audits = audits or project.AUDITS
    out = []
    for tp in tps(rd):
        subs = _subjects(audits, tp)
        tokens = [x.split(" token ", 1)[1] for x in subs if " token " in x]
        sealed = {x.split(" seal ", 1)[1] for x in subs if " seal " in x}
        for name in tokens:
            m = REVIEW_RE.match(name)
            if not m:
                continue
            n = int(m.group(1))
            if upto and (int(tp[2:]), n) >= (int(upto[0][2:]), upto[1]):
                continue
            v = load(os.path.join(tp_dir(rd, tp), name)) if name in sealed else None
            if v is not None and v.get("verdict") != "reject":
                continue
            dc = git(audits, "log", "-1", "--format=%H", f"--grep=^tool-patch {tp} diagnosis {n}$", check=False)
            rel = os.path.relpath(os.path.join(tp_dir(rd, tp), f"A{n}", "patch.diff"), audits)
            pt = show(audits, dc, rel) if dc else None
            if pt is None and os.path.isfile(os.path.join(audits, rel)):
                pt = open(os.path.join(audits, rel), encoding="utf-8").read()
            out.append((tp, n, name, "reject" if v is not None else "never sealed", list((v or {}).get("findings") or []),
                        diff_key(pt) if pt is not None else None))
    return out


def rejected_keys(rd, upto=None, audits=None):
    """{diff_key: [(tp, review name)]} of every diff a review in the run rejected or never sealed (rejections)."""
    out = {}
    for tp, _n, name, _k, _f, key in rejections(rd, upto, audits):
        if key:
            out.setdefault(key, []).append((tp, name))
    return out


ANSWERS_HEADING = "## Earlier findings answered"


def unanswered(diag, rejs):
    """[`TP<k> review-<n>-<m>.json`] of the rejecting reviews (rejections) the diagnosis's section "## Earlier findings
    answered" does not name: a revision answers each rejection's findings (or says what it does about a review that
    never returned); the reviewer judges the answers, this checks only that each is there."""
    m = re.search(rf"^{re.escape(ANSWERS_HEADING)}\s*\n(.*?)(?=^## |\Z)", diag, re.M | re.S)
    sec = m.group(1) if m else ""
    return [f"{tp} {name}" for tp, _n, name, _k, _f, _s in rejs if not re.search(rf"\b{tp} {re.escape(name)}", sec)]


def shopping_problems(rd, tp, n, diag, key, audits=None):
    """[why attempt n of TP is reviewer shopping]: its diff is one a review in the run (any stop) rejected or never
    sealed (identical up to whitespace, diff_key: refused; revise it), or its diagnosis does not answer every such
    rejection."""
    rejs = rejections(rd, (tp, n), audits)
    out = []
    same = [f"{t} {x} ({k})" for t, _n, x, k, _f, s in rejs if s == key]
    if same:
        out.append(f"this exact diff (up to whitespace and line numbers) was rejected before ({', '.join(same)}; a "
                   f"review never sealed counts as a rejection): revise it with the findings (no resubmission)")
    miss = unanswered(diag, rejs)
    if miss:
        out.append(f"DIAGNOSIS.md's section {ANSWERS_HEADING!r} does not answer {', '.join(miss)} (name each rejecting "
                   f"or never-sealed review of the run, on any stop, and answer its findings)")
    return out


def seal_doc(rd, tp, name):
    return load(os.path.join(tp_dir(rd, tp), ".lane-seals", name))


def all_agent_ids(rd):
    """{agent id: [seal path]} of every seal in the run (lanes, re-votes, reviewers)."""
    out = {}
    for p in glob.glob(os.path.join(rd, "**", ".lane-seals", "**", "*.json"), recursive=True):
        a = (load(p) or {}).get("agent_id")
        if a:
            out.setdefault(str(a), []).append(os.path.relpath(p, rd))
    return out


def approval_problems(cfg, tp, n, rd=None, audits=None, render=None):
    """[why attempt n of TP may not be applied] (empty: approved). `render(tp, n, m)` -> the prompt text the
    apparatus in force renders (verifying a link: the previous pin's)."""
    import lane_auth
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    out = []
    f = load(os.path.join(tp_dir(rd, tp), f"A{n}", "FACTS.json")) or {}
    patch = os.path.join(tp_dir(rd, tp), f"A{n}", "patch.diff")
    sha = sha_bytes(open(patch, "rb").read()) if os.path.exists(patch) else None
    if not f or f.get("patch_sha256") != sha:
        return [f"attempt {n}: FACTS.json is missing or names another patch_sha256"]
    need = int(f.get("required_approvals") or 1)
    dg = os.path.join(tp_dir(rd, tp), f"A{n}", "DIAGNOSIS.md")
    try:
        rg = REGRESSION_RE.search(open(dg, encoding="utf-8").read()) if os.path.isfile(dg) else None
        out += [f"attempt {n}: {x}" for x in structure_problems(
            audits, rd, patch_files(open(patch, encoding="utf-8").read()), rg.group(1) if rg else None)]
    except Refused as e:
        out.append(f"attempt {n}: {e}")
    base_ = (git(audits, "rev-parse", apply_commit(audits, tp) + "^") if apply_commit(audits, tp)
             else pin_doc(rd).get("audits_commit"))
    if os.path.exists(patch):
        out += [f"attempt {n}: {x}" for x in guard_problems(audits, base_, open(patch, encoding="utf-8").read())]
    out += [f"attempt {n}: {x}" for x in shopping_problems(
        rd, tp, n, open(dg, encoding="utf-8").read() if os.path.isfile(dg) else "",
        diff_key(open(patch, encoding="utf-8").read()), audits)]
    fh = floor_pattern_hits(floor_mutants(audits, rd), lambda fl: _patched_text(audits, rd, tp, n, fl))
    if fh:
        need = max(need, 2)        # the cheap half of the floor, recomputed (R1: FACTS are the operator's file)
        out_floor = f" (floor: {', '.join(i + ' ' + w for i, w in fh)})"
    else:
        out_floor = ""
    ids = all_agent_ids(rd)
    approvals = []
    for n_, m_, name in reviews(rd, tp):
        v = os.path.join(tp_dir(rd, tp), name)
        probs = lane_auth.validate(v)
        if probs:
            out.append(f"review {name}: {probs[0]} (every issued review is sealed before apply; a reviewer that never "
                       f"returned: withdraw the TP and begin a new one)")
            continue
        if render is not None:
            want = render(tp, n_, m_)
            have = open(os.path.join(tp_dir(rd, tp), "prompts", name[:-len('.json')] + ".txt"), encoding="utf-8").read()
            if want is None or want != have:
                out.append(f"review {name}: its prompt is not what the apparatus in force renders for it")
        d = load(v) or {}
        if n_ != n:
            continue
        if d.get("verdict") == "reject":
            out.append(f"attempt {n} was rejected by {name}: revise it (prepare attempt {n + 1})")
        elif d.get("verdict") == "approve" and d.get("patch_sha256") == sha:
            agent = str((seal_doc(rd, tp, name) or {}).get("agent_id"))
            others = [p for p in ids.get(agent, []) if p != os.path.join(TP_DIR, tp, ".lane-seals", name)]
            if others:
                out.append(f"review {name}: its agent id {agent} also sealed {others[0]}: a reviewer must be fresh")
            elif agent in {a for a, _x in approvals}:
                out.append(f"review {name}: agent {agent} approved twice")
            else:
                approvals.append((agent, name))
        else:
            out.append(f"review {name}: its verdict is neither a reject nor an approval of patch {str(sha)[:12]}")
    if len(approvals) < need:
        out.append(f"attempt {n} has {len(approvals)} approval(s) of patch {str(sha)[:12]}; it needs {need}"
                   + (f" (a floor hit: two independent approvals{out_floor})" if need > 1 else ""))
    return out


def _patched_text(audits, rd, tp, n, rel):
    """The text of tooling file `rel` with attempt n's patch applied to the current pin (None: no such file)."""
    key = (tp, n)
    if key not in _PATCHED:
        root, d = scratch_tree(audits, pin_doc(rd).get("audits_commit") if not apply_commit(audits, tp)
                               else git(audits, "rev-parse", apply_commit(audits, tp) + "^"),
                               open(os.path.join(tp_dir(rd, tp), f"A{n}", "patch.diff"), encoding="utf-8").read())
        _PATCHED[key] = (root, d)
    p = os.path.join(_PATCHED[key][1], rel)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else None


_PATCHED = {}


def _cleanup():
    for root, _d in list(_PATCHED.values()) + list(_RENDERERS.values()):
        shutil.rmtree(root, ignore_errors=True)
    _PATCHED.clear()
    _RENDERERS.clear()


# --- commands ---------------------------------------------------------------------------------------------------
def begin(cfg, stop):
    rd, audits = rounds_dir(cfg), project.AUDITS
    if project.mode(cfg) != "release":
        raise Refused("dev mode: a tool fault stops the run and a maintainer fixes the tool (no tool patches)")
    why = first_pin_problem(rd)
    if why:
        raise Refused(why)
    if not stop_open(rd, stop):
        raise Refused(f"{stop} is not an open stop: a tool patch cures the open stop of the check it fixes")
    codes = [c.get("code") for c in (stop_doc(rd, stop) or {}).get("causes") or []]
    hum = [c for c in codes if project.release_kind(c) == "human"]
    if hum:
        raise Refused(f"{stop} is a human stop ({', '.join(hum)}): never a tool-patch subject")
    act = [t for t in tps(rd) if tp_state(rd, t) == "open"]
    if act:
        raise Refused(f"{act[0]} is still open: apply or withdraw it first (one tool patch at a time)")
    tp = f"TP{len(tps(rd)) + 1}"
    d = tp_dir(rd, tp)
    os.makedirs(os.path.join(d, "A1"))
    p = os.path.join(d, "BEGIN.json")
    json.dump({"tp": tp, "stop": stop, "date": today(), "mode": "release",
               "pinned_commit": pin_doc(rd).get("audits_commit")}, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        commit_paths(audits, [p], f"tool-patch {tp} begin")
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return tp, (f"began {tp} for {stop}. Diagnose it from the code, then write {os.path.relpath(d, project.REPO)}/A1/"
                f"DIAGNOSIS.md (sections below) and A1/patch.diff (`git -C audits diff --relative` of a minimal fix made "
                f"in a scratch worktree, never in audits/, with a NEW regression test tests/regressions/<name>.py), "
                f"then python3 audits/tool_patch.py prepare --tp {tp}.\n" + DIAG_TEMPLATE)


def facts_text(cfg, tp, n):
    """(FACTS.json's text for attempt n, exactly as prepare writes it, [refusal]): `tool_patch.py facts`, the reviewer's
    re-derivation, compared with FACTS.json where any difference but timings rejects (safety review LOW 4: it once
    added a `refused` key no FACTS.json has; the refusals go to stderr and the exit code instead)."""
    ad = os.path.join(tp_dir(rounds_dir(cfg), tp), f"A{n}")
    f, refuse = compute_facts(cfg, tp, n, open(os.path.join(ad, "DIAGNOSIS.md"), encoding="utf-8").read(),
                              open(os.path.join(ad, "patch.diff"), encoding="utf-8").read())
    return json.dumps(f, indent=1, sort_keys=True), refuse


def prepare(cfg, tp):
    rd, audits = rounds_dir(cfg), project.AUDITS
    if project.mode(cfg) != "release" or first_pin_problem(rd):
        raise Refused(first_pin_problem(rd) or "dev mode refuses tool patches")
    if tp_state(rd, tp) != "open" or not os.path.isfile(os.path.join(tp_dir(rd, tp), "BEGIN.json")):
        raise Refused(f"{tp} is not an open tool patch")
    n = (attempts(rd, tp) or [0])[-1] + 1
    if n > 1 and not any(load(os.path.join(tp_dir(rd, tp), x)) and n_ == n - 1 and (load(os.path.join(tp_dir(rd, tp), x)) or {}).get("verdict") == "reject"
                         for n_, _m, x in reviews(rd, tp)):
        raise Refused(f"attempt {n - 1} of {tp} is prepared and not rejected: review it first (tool_patch.py review)")
    ad = os.path.join(tp_dir(rd, tp), f"A{n}")
    dp, pp = os.path.join(ad, "DIAGNOSIS.md"), os.path.join(ad, "patch.diff")
    if not (os.path.isfile(dp) and os.path.isfile(pp)):
        raise Refused(f"write {os.path.relpath(dp, project.REPO)} and {os.path.relpath(pp, project.REPO)} first\n"
                      + DIAG_TEMPLATE)
    diag, patch = open(dp, encoding="utf-8").read(), open(pp, encoding="utf-8").read()
    if diff_key(patch) in rejected_keys(rd):
        raise Refused("this exact diff (up to whitespace and line numbers) was rejected before, or its review was never "
                      "sealed: revise it with the reviewer's findings (no resubmission)")
    shop = shopping_problems(rd, tp, n, diag, diff_key(patch), audits)
    if shop:
        raise Refused(f"attempt {n} of {tp}: " + "; ".join(shop))
    facts, refuse = compute_facts(cfg, tp, n, diag, patch, audits)
    if refuse:
        raise Refused(f"attempt {n} of {tp} is refused before review (fix it and prepare again):\n  - "
                      + "\n  - ".join(refuse))
    fp = os.path.join(ad, "FACTS.json")
    json.dump(facts, open(fp, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        commit_paths(audits, [dp, pp, fp], f"tool-patch {tp} diagnosis {n}")
    except Exception:
        os.remove(fp)
        raise
    return facts


def render_prompt(cfg, tp, n, m, rd=None, pin_commit=None, text=None, at=None):
    import prompt as _pr
    rd = rd or rounds_dir(cfg)
    return _pr.render_tool_patch(text if text is not None else _pr.load(_pr.DEFAULT), cfg, rd, tp, n, m,
                                 pin_commit or pin_doc(rd).get("audits_commit"), at=at)


def rendered_at_issue(cfg, tp, n, m, rd, pin_commit, audits=None):
    """The prompt of review m of attempt n as the apparatus running now renders it from the records as they were
    when it was issued (the parent of its token commit); None when that cannot be read."""
    audits = audits or project.AUDITS
    rel = os.path.relpath(os.path.join(tp_dir(rd, tp), ".lane-auth", f"review-{n}-{m}.json"), audits)
    h = git(audits, "log", "--reverse", "--diff-filter=A", "--format=%H", "--", rel, check=False).split()
    if not h:
        return None
    at = git(audits, "rev-parse", h[0] + "^")
    if not pin_commit or _renders_as(audits, pin_commit):
        return render_prompt(cfg, tp, n, m, rd, pin_commit, at=at)
    # SWEEP-FIX D3 (RELEASE-SWEEP T3): the prompt was rendered by the apparatus pinned when it was issued (`pin_commit`,
    # whose own link is verified), not by the apparatus running this check -- a reviewed patch to the renderer
    # (prompt.render_tool_patch) must not make every later link fail the first pin's re-check. That pin's renderer
    # runs from its tooling extracted from git, in a subprocess (T34's pattern)
    return render_with(audits, pin_commit, cfg, rd, tp, n, m, pin_commit, at)


def render_with(audits, commit, cfg, rd, tp, n, m, pin_commit, at=None):
    """The review prompt as the renderer of the apparatus at `commit` (its tooling extracted from git) renders it, run in
    a subprocess; None when it cannot be rendered."""
    if commit not in _RENDERERS:
        tmp = tempfile.mkdtemp(prefix="tp-render-")
        _RENDERERS[commit] = (tmp, extract(audits, commit, os.path.join(tmp, "audits")))
    code_dir = _RENDERERS[commit][1]
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", RENDER_LAUNCH, code_dir, project.AUDITS, project.REPO,
                            json.dumps([cfg, rd, tp, n, m, pin_commit, at])], cwd=project.REPO, capture_output=True,
                           text=True, timeout=600, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, ValueError):
        return None


# the renderer of an apparatus directory D, run on the live records (project.AUDITS/REPO overridden as LAUNCH does);
# prints the rendered prompt as JSON (null when its records cannot be read)
RENDER_LAUNCH = ("import os, sys, json; sys.dont_write_bytecode = True; d, a, r, args = sys.argv[1:5]; "
                 "sys.path.insert(0, d); import project; "
                 "project.AUDITS, project.REPO, project.PROJECTS = a, r, os.path.join(a, 'projects'); import prompt; "
                 "c, rd, tp, n, m, pc, at = json.loads(args); "
                 "sys.stdout.write(json.dumps(prompt.render_tool_patch(prompt.load(prompt.DEFAULT), c, rd, tp, n, m, pc, "
                 "at=at)))")
_RENDERERS = {}


def _renders_as(audits, commit):
    """Does the renderer running in this process (its prompt.py and protocol text) equal the one pinned at `commit`?"""
    import prompt as _pr
    for f, here_ in (("prompt.py", _pr.__file__), ("AUDIT_PROTOCOL.md", _pr.DEFAULT)):
        pinned = show(audits, commit, f, binary=True)
        try:
            mine = open(here_, "rb").read()
        except OSError:
            return False
        if pinned is None or pinned != mine:
            return False
    return True


def review(cfg, tp):
    """Issue the next reviewer prompt of the newest attempt; returns (prompt path, spawn line)."""
    import lane_auth, secrets
    rd, audits = rounds_dir(cfg), project.AUDITS
    if project.mode(cfg) != "release" or first_pin_problem(rd):
        raise Refused(first_pin_problem(rd) or "dev mode refuses tool patches")
    if tp_state(rd, tp) != "open":
        raise Refused(f"{tp} is {tp_state(rd, tp)}")
    ns = attempts(rd, tp)
    if not ns or not committed(audits, os.path.join(tp_dir(rd, tp), f"A{ns[-1]}", "FACTS.json")):
        raise Refused(f"{tp} has no prepared attempt (tool_patch.py prepare --tp {tp})")
    n = ns[-1]
    for n_, _m, name in reviews(rd, tp):
        if lane_auth.validate(os.path.join(tp_dir(rd, tp), name)):
            raise Refused(f"review {name} was issued and is not sealed: seal it from its reviewer's LANE_COMPLETION line "
                          f"(lane_auth.py seal; if its write was refused and it returned the verdict between `BEGIN "
                          f"RETURNED FILE <path> <delimiter>` and `END RETURNED FILE`, first save that text verbatim to "
                          f"<path> with a quoted heredoc ending at that delimiter), or withdraw {tp} (a reviewer that "
                          f"never returned)")
        if n_ == n and (load(os.path.join(tp_dir(rd, tp), name)) or {}).get("verdict") == "reject":
            raise Refused(f"attempt {n} was rejected ({name}): revise it and prepare attempt {n + 1}")
    m = 1 + sum(1 for n_, _m, _x in reviews(rd, tp) if n_ == n)
    name = f"review-{n}-{m}.json"
    body = render_prompt(cfg, tp, n, m)
    pdir = os.path.join(tp_dir(rd, tp), "prompts")
    os.makedirs(pdir, exist_ok=True)
    pp = os.path.join(pdir, name[:-len(".json")] + ".txt")
    cp = os.path.join(tp_dir(rd, tp), ".lane-auth", name)
    if os.path.exists(pp) or os.path.exists(cp):
        raise Refused(f"{name} is already issued")
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    open(pp, "w", encoding="utf-8").write(body)
    token = secrets.token_hex(32)
    json.dump({"verdict": name, "token_sha256": lane_auth.sha(token.encode()), "prompt": os.path.abspath(pp),
               "prompt_sha256": lane_auth.sha(open(pp, "rb").read())}, open(cp, "w", encoding="utf-8"),
              sort_keys=True, indent=2)
    open(cp, "a", encoding="utf-8").write("\n")
    try:
        commit_paths(audits, [pp, cp], f"tool-patch {tp} token {name}")
    except Exception:
        for x in (pp, cp):
            if os.path.exists(x):
                os.remove(x)
        raise
    return pp, lane_auth.spawn_line(os.path.abspath(pp), token)


def apply(cfg, tp):
    """Apply the approved newest attempt: "tool-patch TP<k> apply" (tooling only), then "pin (tool-patch TP<k>)"."""
    import integrity
    rd, audits = rounds_dir(cfg), project.AUDITS
    if project.mode(cfg) != "release" or first_pin_problem(rd):
        raise Refused(first_pin_problem(rd) or "dev mode refuses tool patches")
    if tp_state(rd, tp) == "applied" and not any(x[1] == tp for x in links(audits, rd)):
        return _resume_apply(cfg, tp, rd, audits)
    if tp_state(rd, tp) != "open":
        raise Refused(f"{tp} is {tp_state(rd, tp)}")
    pin = pin_doc(rd)
    ns = attempts(rd, tp)
    if not ns:
        raise Refused(f"{tp} has no prepared attempt")
    n = ns[-1]
    try:
        probs = approval_problems(cfg, tp, n, rd, audits,
                                  render=lambda t, a, b: rendered_at_issue(cfg, t, a, b, rd, pin.get("audits_commit"), audits))
    finally:
        _cleanup()
    if probs:
        raise Refused(f"{tp} attempt {n} is not approved:\n  - " + "\n  - ".join(probs))
    if integrity.tooling_dirty(audits) or git(audits, "diff", "--name-only", pin.get("audits_commit"), "HEAD", "--",
                                              *integrity.TOOLING_PATHSPECS, check=False):
        raise Refused("the tooling differs from the pin already: restore it first (integrity.py --check)")
    pp = os.path.join(tp_dir(rd, tp), f"A{n}", "patch.diff")
    patch = open(pp, encoding="utf-8").read()
    top, pre = audit_top(audits), prefix(audits)
    r = subprocess.run(["git", "-C", top, "apply", "--index"] + ([f"--directory={pre.rstrip('/')}"] if pre else []) + [pp],
                       capture_output=True, text=True)
    if r.returncode:
        raise Refused(f"patch.diff does not apply: {r.stderr.strip()[:300]}")
    files = [os.path.join(audits, p) for p, _k in patch_files(patch)]
    head0 = git(audits, "rev-parse", "HEAD")
    try:
        commit_paths(audits, files, f"tool-patch {tp} apply")
        h = git(audits, "rev-parse", "HEAD")
        got = git(audits, "diff", "--relative", f"{h}^", h, "--", *integrity.TOOLING_PATHSPECS)
        if got.strip("\n") != patch.strip("\n"):
            raise Refused("the commit's tooling diff is not byte-identical to the approved patch.diff")
        _pin_applied(cfg, tp, n, rd, audits, patch)
    except Exception:
        subprocess.run(["git", "-C", audits, "reset", "-q", "--hard", head0], capture_output=True)
        raise
    return h


def _pin_applied(cfg, tp, n, rd, audits, patch):
    """The second half of apply: the re-pin "pin (tool-patch TP<k>)" recording the link."""
    import integrity
    stop = (load(os.path.join(tp_dir(rd, tp), "BEGIN.json")) or {}).get("stop")
    seals = [git(audits, "log", "-1", "--format=%H", "--", os.path.relpath(
        os.path.join(tp_dir(rd, tp), ".lane-seals", name), audits)) for n_, _m, name in reviews(rd, tp)
        if n_ == n and (load(os.path.join(tp_dir(rd, tp), name)) or {}).get("verdict") == "approve"]
    roles = sync_derived(audits, [f for f, _k in patch_files(patch)])
    p, why = integrity.pin(audits, cfg, rounds_dir=rd, repin=f"tool-patch {tp}",
                           tool_patch={"tool_patch": tp, "attempt": n, "patch_sha256": sha_bytes(patch.encode("utf-8")),
                                       "review_seals": seals, "stop": stop})
    if why:
        raise Refused(f"the re-pin refused: {why}")
    if roles is not None:       # the Codex roles regenerated from the patched text are the pinned ones now
        doc = json.load(open(p, encoding="utf-8"))
        doc["codex_agents"] = roles
        json.dump(doc, open(p, "w"), indent=1)
    commit_paths(audits, [p], f"pin (tool-patch {tp})")


def sync_derived(audits, files):
    """OPERATOR-AUTHORITY: a patch to the protocol text the installed copies are made from (agents/auditor.md: the
    installed reviewer agent; it and AUDIT_PROTOCOL.md's common rules: the generated Codex roles) installs them again
    before the re-pin, so integrity.py --check finds them equal to the patched source (no [agent] or [codex-roles]
    FAIL, no new stop). Returns the Codex roles' state when they were regenerated, else None."""
    import integrity
    src = os.path.join(audits, "agents", "auditor.md")
    if "agents/auditor.md" in files and os.path.isfile(src) and os.path.isfile(integrity.AGENT_FILE):
        shutil.copyfile(src, integrity.AGENT_FILE)
    cd = os.path.join(project.REPO, ".codex", "agents")
    if not ({"agents/auditor.md", "AUDIT_PROTOCOL.md"} & set(files)) or not os.path.isfile(
            os.path.join(cd, "formalize_auditor.toml")):
        return None
    import codex_agents
    m = re.search(r'^model = (".*")$', open(os.path.join(cd, "formalize_auditor.toml"), encoding="utf-8").read(), re.M)
    model = json.loads(m.group(1)) if m else codex_agents.DEFAULT_MODEL
    for name, body in codex_agents.generated(audits, model).items():
        open(os.path.join(cd, name), "w", encoding="utf-8").write(body)
    return codex_agents.state(cd, audits)


def _resume_apply(cfg, tp, rd, audits):
    """RELEASE-SWEEP I4: an apply killed between its two commits ("tool-patch TP<k> apply" committed, "pin (tool-patch
    TP<k>)" not) is completed: the approval is checked again, the apply commit's tooling diff must still be the
    approved patch.diff byte for byte, made on the pinned tooling, and nothing may have changed the tooling since;
    then the pin is written and committed. Returns the apply commit."""
    import integrity
    h = apply_commit(audits, tp)
    pin = pin_doc(rd)
    ns = attempts(rd, tp)
    if not ns:
        raise Refused(f"{tp} was applied with no prepared attempt: restore the pinned tooling (integrity.py --check)")
    n = ns[-1]
    try:
        probs = approval_problems(cfg, tp, n, rd, audits,
                                  render=lambda t, a, b: rendered_at_issue(cfg, t, a, b, rd, pin.get("audits_commit"), audits))
    finally:
        _cleanup()
    if probs:
        raise Refused(f"{tp} was applied but attempt {n} is not approved: restore the pinned tooling "
                      f"(git -C audits checkout {str(pin.get('audits_commit'))[:11]} -- <files>; commit):\n  - "
                      + "\n  - ".join(probs))
    patch = open(os.path.join(tp_dir(rd, tp), f"A{n}", "patch.diff"), encoding="utf-8").read()
    got = git(audits, "diff", "--relative", f"{h}^", h, "--", *integrity.TOOLING_PATHSPECS)
    before = git(audits, "diff", "--name-only", str(pin.get("audits_commit")), f"{h}^", "--",
                 *integrity.TOOLING_PATHSPECS, check=False)
    since = git(audits, "diff", "--name-only", h, "HEAD", "--", *integrity.TOOLING_PATHSPECS, check=False)
    if got.strip("\n") != patch.strip("\n") or before.strip() or since.strip() or integrity.tooling_dirty(audits):
        raise Refused(f"the interrupted apply of {tp} ({h[:11]}) cannot be completed: its tooling diff is not the "
                      f"approved patch.diff on the pinned tooling, or the tooling changed since; restore the pinned "
                      f"tooling (git -C audits checkout {str(pin.get('audits_commit'))[:11]} -- <files>; commit)")
    _pin_applied(cfg, tp, n, rd, audits, patch)
    return h


def withdraw(cfg, tp, reason):
    rd, audits = rounds_dir(cfg), project.AUDITS
    if tp_state(rd, tp) != "open" or not os.path.isfile(os.path.join(tp_dir(rd, tp), "BEGIN.json")):
        raise Refused(f"{tp} is not an open tool patch ({tp_state(rd, tp)})")
    r = " ".join(str(reason or "").split())
    if not r:
        raise Refused("--reason is required (e.g. the reviewers showed the check was right; a reviewer never returned)")
    p = os.path.join(tp_dir(rd, tp), "WITHDRAWN.json")
    json.dump({"tp": tp, "reason": r, "date": today()}, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    commit_paths(audits, [p], f"tool-patch {tp} withdraw")
    # TODO(B): a stop-trail/RUN_LOG event class for "patch withdrawn" if builder B wants one; the record is here
    return p


# --- the chain ---------------------------------------------------------------------------------------------------
def links(audits, rd):
    """[(pin commit, TP, previous audits_commit, audits_commit, repin entry)] of every tool-patch pin, oldest first."""
    rel = os.path.relpath(os.path.join(rd, "TOOLING_PIN.json"), audits)
    out = []
    for line in git(audits, "log", "--reverse", "--format=%H %s", "--", rel, check=False).splitlines():
        h, _, subj = line.partition(" ")
        m = PIN_SUBJ_RE.match(subj)
        if not m:
            continue
        new = json.loads(show(audits, h, rel) or "{}")
        old = json.loads(show(audits, h + "^", rel) or "{}")
        e = next((x for x in reversed(new.get("repins") or []) if x.get("tool_patch") == m.group(1)), {})
        out.append((h, m.group(1), old.get("audits_commit"), new.get("audits_commit"), e))
    return out


def verify_link(cfg, audits, rd, tp, pin_commit):
    """[problem] of one link, judged by THIS apparatus (run as the apparatus pinned before the link)."""
    import integrity
    out = []
    why = first_pin_problem(rd)
    if why:
        return [why]
    lk = next((x for x in links(audits, rd) if x[0] == pin_commit and x[1] == tp), None)
    if not lk:
        return [f"{pin_commit[:11]} is no pin of {tp}"]
    _h, _tp, prev, new, e = lk
    a = apply_commit(audits, tp)
    if not a or a != new:
        return [f"the pin's audits_commit {str(new)[:11]} is not the commit \"tool-patch {tp} apply\" ({str(a)[:11]})"]
    n = e.get("attempt")
    pp = os.path.join(tp_dir(rd, tp), f"A{n}", "patch.diff")
    patch = show(audits, a, os.path.relpath(pp, audits))
    if patch is None:
        return [f"attempt {n} of {tp} has no committed patch.diff"]
    sha = sha_bytes(patch.encode("utf-8"))
    names = git(audits, "diff", "--relative", "--name-only", f"{a}^", a).splitlines()
    rel_rd = os.path.relpath(rd, audits)
    bad = [x for x in names if not allowed(x)]
    out += guard_problems(audits, f"{a}^", patch)
    if bad:
        out.append(f"the apply commit touches {', '.join(bad[:3])}: only the allowed tooling (and never a record)")
    for base, what in ((f"{a}^", "the apply commit's"), (prev, "the diff since the previous pin's commit")):
        got = git(audits, "diff", "--relative", base, a, "--", *integrity.TOOLING_PATHSPECS, check=False)
        if got.strip("\n") != patch.strip("\n"):
            out.append(f"{what} tooling diff is not byte-identical to the approved patch.diff of attempt {n}")
    f = json.loads(show(audits, a, os.path.relpath(os.path.join(tp_dir(rd, tp), f"A{n}", "FACTS.json"), audits)) or "{}")
    if f.get("patch_sha256") != sha or not (f.get("regression") or {}).get("passes") \
            or not (f.get("selftests") or {}).get("passes"):
        out.append(f"FACTS.json of attempt {n} does not record facts (a) and (b) passing for this patch")
    if e.get("patch_sha256") != sha or e.get("stop") != (load(os.path.join(tp_dir(rd, tp), "BEGIN.json")) or {}).get("stop") \
            or e.get("previous_commit") != prev:
        out.append(f"the pin's repins entry does not record {tp} (patch_sha256, stop, previous commit)")
    oldpin = json.loads(show(audits, pin_commit + "^", os.path.relpath(os.path.join(rd, "TOOLING_PIN.json"), audits)) or "{}")
    newpin = json.loads(show(audits, pin_commit, os.path.relpath(os.path.join(rd, "TOOLING_PIN.json"), audits)) or "{}")
    oc, nc = oldpin.get("config") or {}, newpin.get("config") or {}
    if any(integrity.scope_value(oc, k) != integrity.scope_value(nc, k) for k in integrity.SCOPE_KEYS) \
            or any(x not in (nc.get(k) or []) for k in integrity.GROW_ONLY for x in (oc.get(k) or [])) \
            or oldpin.get("ownership") != newpin.get("ownership"):
        out.append("the tool-patch pin changed the pinned config (a frozen key, or a grow-only key lost an entry) or "
                   "the ownership version")
    if os.path.exists(os.path.join(tp_dir(rd, tp), "WITHDRAWN.json")):
        out.append(f"{tp} was withdrawn")
    for p in glob.glob(os.path.join(tp_dir(rd, tp), "**", "*"), recursive=True):
        if os.path.isfile(p) and "__pycache__" not in p:
            subs = git(audits, "log", "--format=%s", "--", os.path.relpath(p, audits), check=False).splitlines()
            if len(subs) != 1 or not subs[0].startswith(f"tool-patch {tp} "):
                out.append(f"{os.path.relpath(p, rd)} must be committed once, by a \"tool-patch {tp} ...\" commit "
                           f"(found {subs[:2]})")
    try:
        out += approval_problems(cfg, tp, n, rd, audits,
                                 render=lambda t, x, y: rendered_at_issue(cfg, t, x, y, rd, prev, audits))
    finally:
        _cleanup()
    return out


def _run_verifier(audits, rd, commit, args, label):
    """(problems or None when it could not run, note) running `tool_patch.py <args>` of the apparatus at `commit`."""
    tmp = tempfile.mkdtemp(prefix="tp-verify-")
    try:
        d = extract(audits, commit, os.path.join(tmp, "audits"))
        if not os.path.isfile(os.path.join(d, "tool_patch.py")):
            return None, f"the apparatus at {commit[:11]} has no tool_patch.py"
        rc, out = run_with(d, "tool_patch.py", args + ["--rounds-dir", rd, "--json"], timeout=3600)
        try:
            return json.loads(out.strip().splitlines()[-1]), None
        except (ValueError, IndexError):
            return None, f"{label} could not run (exit {rc}): {out.strip()[-200:]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def chain_problems(audits, rd, cfg=None):
    """[(severity, "[tool-patch] ...")] for integrity.py --check: each link verified by the apparatus pinned just
    before it (review §4a); a "tool-patch" commit in a dev run; an apply commit without its pin."""
    out = []
    fp = first_pin(rd)
    subs = [l.partition(" ") for l in git(audits, "log", "--format=%H %s", check=False).splitlines()]
    tpc = [(h, s) for h, _, s in subs if SUBJ_RE.match(s) or PIN_SUBJ_RE.match(s)]
    if tpc and project.mode((fp or {}).get("config") or {}) != "release":
        return [("FAIL", f"[tool-patch] commit {tpc[0][0][:11]} \"{tpc[0][1][:50]}\": a dev run never patches its tools")]
    lk = links(audits, rd)
    for h, s in tpc:
        m = re.match(r"^tool-patch (TP\d+) apply$", s)
        if m and not any(x[1] == m.group(1) for x in lk):
            out.append(("FAIL", f"[tool-patch] \"{s}\" ({h[:11]}) has no pin (tool-patch {m.group(1)}): an interrupted "
                                f"apply -- complete it with python3 audits/tool_patch.py apply --tp {m.group(1)} (it "
                                f"resumes: checks the approval and the diff again, then pins), or restore the tooling"))
    # the first pin's re-check (safety review 2026-10-25: a patch that weakened approval_problems let the next
    # link through with no review, and only the manual verify-chain --first-pin saw it): every link judged by
    # the FIRST pin's apparatus too, on every check; a link whose pinned-before apparatus IS the first pin's
    # was judged by it already
    fpc = (fp or {}).get("audits_commit")
    rech = {}
    if any(x[2] != fpc for x in lk):
        rech, rnote = first_pin_recheck(audits, rd)
        if rnote:
            out.append(("note", f"[tool-patch] the first pin's re-check (verify-chain --first-pin) could not run: {rnote}"))
    for pin_commit, tp, prev, _new, _e in lk:
        probs, note = _run_verifier(audits, rd, prev or "", ["verify-link", "--tp", tp, "--pin", pin_commit],
                                    f"the verifier pinned before {tp}")
        if probs is None:
            # review §4a: never a dead end -- the link's own apparatus verifies it, and that is said
            probs, note2 = _run_verifier(audits, rd, _new or "", ["verify-link", "--tp", tp, "--pin", pin_commit],
                                         f"{tp}'s own apparatus")
            out.append(("note", f"[tool-patch] {tp}: {note}; verified by its own apparatus instead"))
            if probs is None:
                out.append(("FAIL", f"[tool-patch] {tp} cannot be verified: {note2}"))
                continue
        first = [p for p in (rech.get(tp) or []) if prev != fpc and p not in probs]
        if (probs or first) and _restored(audits, rd, pin_commit, prev):
            out.append(("note", f"[tool-patch] {tp} does not verify ({(probs or first)[0]}); its tooling was restored by "
                                f"a later re-pin to the pin before it"))
            continue
        out += [("FAIL", f"[tool-patch] {tp}: {p}") for p in probs]
        out += [("FAIL", f"[tool-patch] {tp}: the first pin's apparatus does not verify this link (verify-chain "
                         f"--first-pin): {p}") for p in first]
    return out


_RECHECK = {}


def first_pin_recheck(audits, rd):
    """({TP: [problem]} of every tool-patch link as the FIRST pin's apparatus judges it -- `verify-chain --first-pin`
    of its scripts extracted from git, the maintainer's standalone re-check, run by every integrity check and at
    --prepare-delivery (RUN_RECORD.md lists each link's result) --, None) or ({}, why it could not run)."""
    fpc = first_pin(rd).get("audits_commit")
    lk = links(audits, rd)
    if not lk or not fpc:
        return {}, None
    key = (os.path.abspath(rd), git(audits, "rev-parse", "HEAD"),
           git(audits, "status", "--porcelain", "--", os.path.relpath(rd, audits), check=False))
    if key not in _RECHECK:
        probs, note = _run_verifier(audits, rd, fpc, ["verify-chain", "--first-pin"], "the first pin's verifier")
        if probs is None:
            _RECHECK[key] = ({}, note)
        else:
            res = {x[1]: [] for x in lk}
            for p in probs:
                tp, _, why = str(p).partition(": ")
                res.setdefault(tp, []).append(why)
            _RECHECK[key] = (res, None)
    return _RECHECK[key]


def _restored(audits, rd, pin_commit, prev):
    """True when a plain re-pin after `pin_commit` pinned tooling identical to `prev`'s (the restore cure)."""
    import integrity
    rel = os.path.relpath(os.path.join(rd, "TOOLING_PIN.json"), audits)
    seen = False
    for line in git(audits, "log", "--reverse", "--format=%H %s", "--", rel, check=False).splitlines():
        h, _, subj = line.partition(" ")
        if h == pin_commit:
            seen = True
            continue
        if seen and subj.startswith("pin (repin: "):
            b_ = json.loads(show(audits, h, rel) or "{}").get("audits_commit")
            if b_ and not git(audits, "diff", "--relative", "--name-only", str(prev), b_, "--",
                              *integrity.TOOLING_PATHSPECS, check=False).strip():
                return True
    return False


def forced_round_problems(cfg, rd=None, audits=None):
    """[why] for each applied TP whose affects-review-inputs is yes and no full round scoped after its apply commit
    has been adjudicated, judging every item of its scope (design §4; the scope.py hook and --deliver)."""
    import stops
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    out = []
    for tp in tps(rd):
        a = apply_commit(audits, tp)
        if not a:
            continue
        n = next((x[4].get("attempt") for x in links(audits, rd) if x[1] == tp), None)
        f = load(os.path.join(tp_dir(rd, tp), f"A{n}", "FACTS.json")) or {}
        if f.get("affects_review_inputs") != "yes":
            continue
        ok = False
        for p in reversed(project.rounds(cfg)):
            if project.round_kind(p) != "full" or not stops._after(audits, a, stops._scope_commit(audits, p)):
                continue
            ap = os.path.join(p, "ADOPTED.md")
            if os.path.exists(ap) and stops.committed(audits, ap) and not stops.redo_scope_problem(
                    cfg, os.path.basename(p), os.path.basename(p), rd):
                ok = True
                break
        if not ok:
            out.append(f"tool patch {tp} may have changed what an earlier review was shown or scoped "
                       f"(affects-review-inputs: yes): run a full round (prompt.py 3 --full), adjudicate it, then deliver")
    return out


def applied(cfg, rd=None, audits=None):
    """[(TP, patch_sha256, review seal commit(s) joined by ',', apply commit)] of every applied tool patch."""
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    return [(tp, e.get("patch_sha256"), ",".join(e.get("review_seals") or []), new)
            for _h, tp, _p, new, e in links(audits, rd)]


def applied_info(cfg, tp, audits=None, rd=None):
    """{tp, stop, attempt, patch_sha256, apply_commit, regression_cmd} of an applied TP; ValueError otherwise."""
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    lk = next((x for x in links(audits, rd) if x[1] == tp), None)
    if not lk:
        raise ValueError(f"{tp} has no pin (tool-patch {tp})")
    e = lk[4]
    f = load(os.path.join(tp_dir(rd, tp), f"A{e.get('attempt')}", "FACTS.json")) or {}
    reg = f.get("regression_test")
    return {"tp": tp, "stop": e.get("stop"), "attempt": e.get("attempt"), "patch_sha256": e.get("patch_sha256"),
            "apply_commit": lk[3], "regression_cmd": f"python3 audits/{reg} --apparatus audits" if reg else None}


STANDALONE = ("d=$(mktemp -d) && git -C audits archive {commit} | tar -x -C \"$d\" && python3 -I -B \"$d/tool_patch.py\" "
              "verify-chain --first-pin --audits-dir \"$PWD/audits\" --repo-dir \"$PWD\" --rounds-dir \"$PWD/{rd}\"")


def record_lines(cfg, rd=None, audits=None):
    """RUN_RECORD.md's tool-patch section (the hook builder C calls): every TP, its diagnosis and every attempt's
    diff in full, every reviewer verdict and findings, patch_sha256, the review seals and the apply commit, the
    forced round, and the command of the maintainer's standalone re-check."""
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    names = tps(rd)
    if not names:
        return []
    fp = first_pin(rd).get("audits_commit") or "<first pin commit>"
    out = ["## Tool patches", "",
           "The audit tools were patched during this run (release mode, approver 2026-10-24): each patch below was "
           "diagnosed by the operator, its mechanical facts recorded, and approved by a fresh independent reviewer "
           "before it was applied. A maintainer re-checks every link with the apparatus of the run's first pin, "
           "independently of the patched code, from the project root:", "",
           "    " + STANDALONE.format(commit=fp[:12], rd=os.path.relpath(rd, project.REPO)), ""]
    if links(audits, rd):
        rech, rnote = first_pin_recheck(audits, rd)
        out += ["That re-check was run when this record was prepared (and `integrity.py --check` runs it at every "
                "check); each link, as the first pin's apparatus judges it:", ""]
        out += ([f"- the re-check could not run: {' '.join(str(rnote).split())[:200]}"] if rnote else
                [f"- {tp}: " + ("verified" if not rech.get(tp) else "NOT VERIFIED: " + "; ".join(rech[tp]))
                 for _h, tp, _p, _n, _e in links(audits, rd)])
        out.append("")
    lk = {x[1]: x for x in links(audits, rd)}
    forced = forced_round_problems(cfg, rd, audits)
    for tp in names:
        b = load(os.path.join(tp_dir(rd, tp), "BEGIN.json")) or {}
        st = tp_state(rd, tp, audits)
        out += [f"### {tp} ({st}; stop {b.get('stop')}, begun {b.get('date')})", ""]
        sd = stop_doc(rd, b.get("stop") or "") or {}
        out.append(f"- the check: `{sd.get('command') or sd.get('check') or '(no read-only check: a pinned writer)'}`"
                   + (f"; operator's note: {sd.get('note')}" if sd.get("note") else ""))
        if st == "withdrawn":
            out.append(f"- withdrawn: {(load(os.path.join(tp_dir(rd, tp), 'WITHDRAWN.json')) or {}).get('reason')}")
        if tp in lk:
            e = lk[tp][4]
            out += [f"- {tp} applied: attempt {e.get('attempt')}, patch_sha256 `{e.get('patch_sha256')}`, review seal(s) "
                    + ", ".join(f"`{x}`" for x in e.get("review_seals") or []) + f", apply commit `{lk[tp][3]}`, pin "
                    f"commit `{lk[tp][0]}`"]
            if any(tp in x for x in forced):
                out.append("- a full round is forced (affects-review-inputs: yes) and has not run yet")
        for n in attempts(rd, tp):
            ad = os.path.join(tp_dir(rd, tp), f"A{n}")
            f = load(os.path.join(ad, "FACTS.json")) or {}
            out += ["", f"#### {tp} attempt {n} (patch_sha256 `{f.get('patch_sha256')}`; affects-review-inputs: "
                    f"{f.get('affects_review_inputs')}{' (forced by the blast radius)' if f.get('affects_forced') else ''};"
                    f" floor hits: {', '.join(h['id'] + ' ' + h['why'] for h in (f.get('floor') or {}).get('hits') or []) or 'none'};"
                    f" approvals needed: {f.get('required_approvals')})", "", "Diagnosis:", ""]
            out += ["    " + l for l in open(os.path.join(ad, "DIAGNOSIS.md"), encoding="utf-8").read().splitlines()]
            out += ["", "Diff:", "", "```diff"] + open(os.path.join(ad, "patch.diff"), encoding="utf-8").read().splitlines() + ["```"]
            for n_, m_, name in reviews(rd, tp):
                if n_ != n:
                    continue
                v = load(os.path.join(tp_dir(rd, tp), name))
                sl = seal_doc(rd, tp, name)
                out.append(f"- review {name}: " + (f"{v.get('verdict')} (agent {(sl or {}).get('agent_id')})"
                                                     if v and sl else "issued, not sealed"))
                out += [f"  - {x}" for x in (v or {}).get("findings") or []]
        out.append("")
    rr_ = raised_record_lines(cfg, rd, audits) if links(audits, rd) else []
    if rr_:
        out += ["#### Statuses raised by tool patches", "",
                "SUMMARY.md and REPORT.md say, in plain words, that each was decided by a corrected version of the "
                "checking software and quote the original version's status:", ""] + [f"- {l}" for l in rr_] + [""]
    return out


def verify_delivery(cfg, rd, audits):
    """[problem] the FIRST pin's apparatus finds at --deliver (design §2, R1 ii, approver: RUN_RECORD.md): RUN_RECORD.md
    lists every applied tool patch by id, patch_sha256 and apply commit; the floor still holds on the delivered
    tooling, or each hit is one an applied patch was approved for with two approvals; SUMMARY.md and REPORT.md carry
    every status a patch raised and the "Checks weakened" row (documents_problems, SWEEP-FIX D4)."""
    out = []
    p = os.path.join(rd, "RUN_RECORD.md")
    txt = open(p, encoding="utf-8").read() if os.path.isfile(p) else None
    ap = applied(cfg, rd, audits)
    if ap and txt is None:
        out.append("RUN_RECORD.md is missing although the tools were patched (project.py --prepare-delivery writes it)")
    for tp, sha, _seals, a in ap:
        if txt is not None and not (re.search(rf"\b{tp}\b", txt) and str(sha) in txt and str(a) in txt):
            out.append(f"RUN_RECORD.md does not list {tp} with its patch_sha256 and apply commit")
    if ap:
        head = git(audits, "rev-parse", "HEAD")
        root, d = scratch_tree(audits, head)
        try:
            fl = floor(audits, rd, d)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        ok = set()
        for tp, _sha, _s, _a in ap:
            e = next((x[4] for x in links(audits, rd) if x[1] == tp), {})
            f = load(os.path.join(tp_dir(rd, tp), f"A{e.get('attempt')}", "FACTS.json")) or {}
            if int(f.get("required_approvals") or 1) >= 2:
                ok |= {h["id"] for h in (f.get("floor") or {}).get("hits") or []}
        for h in fl["hits"]:
            if h["id"] not in ok:
                out.append(f"the floor no longer holds on the delivered tooling: {h['id']} {h['why']}, and no applied "
                           f"tool patch was approved twice for it")
        out += documents_problems(cfg, rd, audits)      # SWEEP-FIX D4: no status raised silently
    return out


# --- concern (A): a tool patch never raises a result's status silently (SWEEP-FIX D4) ---------------------------------
# result_status.py and make_report.py are patchable with one approval, and the blast radius forces a round only on
# PASS->FAIL, so a patch that turned "not established" into "faithful" would have shipped with nothing on the summary.
# The FIRST pin's result_status.py is the reference: at --prepare-delivery make_report writes, on SUMMARY page 1 and in
# REPORT, one RAISED line for every result whose status is stronger under the patched tools than under the first pin's;
# at --deliver verify_delivery (this file is core, and it runs from the FIRST pin's extraction) recomputes them and
# refuses unless both documents carry each line verbatim, and unless REPORT carries the "Checks weakened" row. The code
# only flags; the delivery status-check agent reads each line and judges whether the records support the raise.
TOOLS_PATCHED = ("the software that checks the formalization was corrected during this run (details for maintainers in "
                 "RUN_RECORD.md)")      # == make_report.TOOLS_PATCHED
WEAKENED_TITLE = "Checks weakened"
# Approver 2026-10-26 (binding): SUMMARY and REPORT speak to a paper author who knows nothing of the mechanism. They say
# only the CONSEQUENCE, in plain words (RAISED, STATUS_UNCOMPARED); the mechanism -- which tool patch, which pin -- is in
# RUN_RECORD.md (RAISED_RECORD, record_lines). An acknowledged history fault (integrity.py --ack-request) changes no
# result: it is in RUN_RECORD.md only.
RAISED = ("{label}: this status was decided by a corrected version of our checking software; the original version "
          "would have said \"{old}\". Details for maintainers: RUN_RECORD.md.")
RAISED_RECORD = "{label}: status raised by tool patch {tp}: first-pin tools say {old}"
STATUS_UNCOMPARED = ("Our checking software was corrected during this run, and the statuses could not be compared with "
                     "what the original version would have said: a status may be stronger than the original version "
                     "would have given. Details for maintainers: RUN_RECORD.md.")
MECHANISM_TERMS = ("tool patch", "tool-patch", "TP1", "first pin", "first-pin", "pinned", "acknowledg", "AK1",
                   "integrity", "reviewer", "result_status", "FAIL[", "stop S")
# The strength of one status item (result_status.py's statuses, U2 §1): what it lets a reader conclude about the result.
# 0 nothing is claimed (not established, an open decision, excluded, not formalized; "reading choice" is how a reading
#   row reads beside a "not established"); 1 something weaker than the paper's result holds (stated only, assumed,
#   a defect, differs, vacuous); 2 proved under a named hypothesis; 3 faithful under a reading; 4 faithful. Checked in
#   this order (rank 3 before 4: "faithful under reading" starts with "faithful"). An item no prefix matches is rank 0
#   with its own class, so any change to it reads as a raise (the conservative side: the agent then judges it).
STATUS_RANKS = ((0, ("not established", "not verified", "decision open", "excluded at checkpoint b", "not formalized",
                     "reading choice")),
                (1, ("stated only", "stated assuming", "assumed", "defect", "differs", "vacuous", "proved as repaired")),
                (2, ("proved assuming",)),
                (3, ("faithful under reading",)),
                (4, ("faithful",)))


def status_class(item):
    """(rank, class) of one status item (STATUS_RANKS)."""
    t = " ".join(str(item).split()).lower()
    for rank, prefixes in STATUS_RANKS:
        for p_ in prefixes:
            if t.startswith(p_):
                return rank, p_
    return 0, t.split(":")[0]


def _known_class(c):
    return any(c == p_ for _r, ps in STATUS_RANKS for p_ in ps)


def status_raised(old, new):
    """True when status list `new` claims more than `old`: its weakest item is stronger, or, as strong, it drops a
    qualifying item (rank < 4) of a class `old` has (e.g. "differs; vacuous" -> "differs")."""
    import collections
    if not old or not new:
        return False
    co, cn = [status_class(x) for x in old], [status_class(x) for x in new]
    # SWEEP-FIX review B3: a status word no rank knows ("proved", "verified", "established") that the old list lacks
    # counts as raised -- fail safe: the agent judges it, the code never lets it pass unflagged
    if any(not _known_class(c) and c not in {c0 for _r, c0 in co} for _r, c in cn):
        return True
    ro, rn = min(r for r, _c in co), min(r for r, _c in cn)
    if rn != ro:
        return rn > ro
    qo = collections.Counter(c for r, c in co if r < 4)
    qn = collections.Counter(c for r, c in cn if r < 4)
    return qn != qo and all(qn[c] <= qo[c] for c in qn)


STATUS_LAUNCH = ("import os, sys, json; sys.dont_write_bytecode = True; d, a, r, c = sys.argv[1:5]; sys.path.insert(0, d); "
                 "import project; project.AUDITS, project.REPO, project.PROJECTS = a, r, os.path.join(a, 'projects'); "
                 "cfg = json.loads(c)\ntry:\n    cfg = project.select(cfg.get('name'))[0] if cfg.get('name') else cfg\n"
                 "except Exception:\n    pass\nimport result_status\n"
                 "print('@@STATUSES@@' + json.dumps(result_status.statuses(cfg)))")


def apparatus_statuses(code_dir, cfg):
    """{label: [status]} of every result as the result_status.py of apparatus `code_dir` computes it on the live
    records (a subprocess, T34's pattern), or None when it cannot run."""
    if RUNNER:
        got = RUNNER("statuses", code_dir, cfg)
        if got is not None:
            return got
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", STATUS_LAUNCH, code_dir, project.AUDITS, project.REPO,
                            json.dumps(cfg)], cwd=project.REPO, capture_output=True, text=True, timeout=1800,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    except subprocess.TimeoutExpired:
        return None
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("@@STATUSES@@")), None)
    try:
        return {str(k): list(v) for k, v in json.loads(line[len("@@STATUSES@@"):])} if r.returncode == 0 and line else None
    except (ValueError, TypeError):
        return None


SUMMARY_LAUNCH = ("import os, sys, json; sys.dont_write_bytecode = True; d, a, r, c = sys.argv[1:5]; sys.path.insert(0, d); "
                  "os.environ['FORMALIZE_TP_NO_RAISED'] = '1'; "
                  "import project; project.AUDITS, project.REPO, project.PROJECTS = a, r, os.path.join(a, 'projects'); "
                  "cfg = json.loads(c)\ntry:\n    cfg = project.select(cfg.get('name'))[0] if cfg.get('name') else cfg\n"
                  "except Exception:\n    pass\nimport contextlib, io, make_report\n"
                  "with contextlib.redirect_stdout(io.StringIO()):\n    md = make_report.summary_md(cfg)\n"
                  "print('@@SUMMARY@@' + json.dumps(md))")


def summary_table(md):
    """{label: status cell} of a SUMMARY's results table (the "| Status | Results |" table under "## Results"; each
    row a status and its results joined by "; "). Parsed here, in the core, never by the patchable make_report."""
    out = {}
    sec_ = ("\n" + (md or "")).split("\n## Results", 1)
    if len(sec_) < 2:
        return out
    for l in sec_[1].split("\n## ", 1)[0].splitlines():
        if not l.startswith("| ") or l.startswith("| Status |") or l.startswith("|---"):
            continue
        cells = [c.strip() for c in l.strip().strip("|").split(" | ")]
        if len(cells) != 2:
            continue
        for lbl in cells[1].split("; "):
            if lbl.strip():
                out[" ".join(lbl.split())] = " ".join(cells[0].split())
    return out


def apparatus_summary(code_dir, cfg):
    """{label: status cell} of the SUMMARY results table the make_report.py of apparatus `code_dir` renders on the live
    records (a subprocess, T34's pattern; SWEEP-FIX review H1: the presentation layer), or None when it cannot run."""
    if RUNNER:
        got = RUNNER("summary", code_dir, cfg)
        if got is not None:
            return summary_table(got)
    try:
        r = subprocess.run([sys.executable, "-I", "-B", "-c", SUMMARY_LAUNCH, code_dir, project.AUDITS, project.REPO,
                            json.dumps(cfg)], cwd=project.REPO, capture_output=True, text=True, timeout=1800,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", FORMALIZE_TP_NO_RAISED="1"))
    except subprocess.TimeoutExpired:
        return None
    line = next((l for l in reversed(r.stdout.splitlines()) if l.startswith("@@SUMMARY@@")), None)
    try:
        return summary_table(json.loads(line[len("@@SUMMARY@@"):])) if r.returncode == 0 and line else None
    except (ValueError, TypeError):
        return None


NOT_LISTED = "this result was not listed"
_RAISED = {}
_FIRST_TABLE = {}


def raised_statuses(cfg, rd=None, audits=None):
    """[(label, TP, old statuses joined by "; ")] of every result whose status the current tools give stronger than the
    FIRST pin's result_status.py does (status_raised); TP is the first applied patch after which it reads stronger
    (each link's apparatus recomputed in order). [] with no applied patch; None when the first pin's (or the current)
    result_status.py cannot run on these records."""
    if os.environ.get("FORMALIZE_TP_NO_RAISED"):
        return []           # inside apparatus_summary's own rendering: never recurse
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    lk = links(audits, rd)
    if not lk:
        return []
    fp = first_pin(rd).get("audits_commit")
    key = (os.path.abspath(rd), git(audits, "rev-parse", "HEAD", check=False),
           git(audits, "status", "--porcelain", "--untracked-files=all", check=False))
    if key in _RAISED:
        return _RAISED[key]
    stats, tables, tmp = [], [], tempfile.mkdtemp(prefix="tp-status-")
    try:
        for i, c in enumerate([fp] + [x[3] for x in lk]):
            if not c:
                stats.append(None)
                tables.append(None)
                continue
            code = extract(audits, c, os.path.join(tmp, str(i), "audits"))
            stats.append(apparatus_statuses(code, cfg))
            tables.append(apparatus_summary(code, cfg))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cur, cur_t = apparatus_statuses(audits, cfg), apparatus_summary(audits, cfg)
    if stats[0] is None or cur is None or tables[0] is None or cur_t is None:
        _RAISED[key] = None     # fail closed: STATUS_UNCOMPARED is written and required
        _FIRST_TABLE.pop(os.path.abspath(rd), None)
        return None
    out, seen = [], set()
    joined = lambda xs: "; ".join(" ".join(str(x).split()) for x in xs)
    for label in list(cur) + [l for l in stats[0] if l not in cur]:
        old, new = stats[0].get(label), cur.get(label)
        # SWEEP-FIX review M6: a result the first pin lists and the current tools do not (or the reverse: relabelled)
        # is a raise candidate, never dropped silently
        if old is None or new is None:
            at = next((i for i in range(1, len(stats)) if stats[i] is not None
                       and (label in stats[i]) != (label in stats[0])), len(lk))
            out.append((label, lk[at - 1][1], NOT_LISTED if old is None else joined(old)))
            seen.add(label)
            continue
        if not status_raised(old, new):
            continue
        tp = next((lk[i - 1][1] for i in range(1, len(stats)) if stats[i] is not None
                   and status_raised(old, stats[i].get(label))), lk[-1][1])
        out.append((label, tp, joined(old)))
        seen.add(label)
    # SWEEP-FIX review H1: the presentation layer -- the SUMMARY table as the FIRST pin's make_report renders it on the
    # same records, against the current one's: any cell that differs (or a result added to or dropped from the table)
    # is flagged, whichever way it moved (fail safe: the agent judges it)
    first_t = tables[0]
    for label in list(cur_t) + [l for l in first_t if l not in cur_t]:
        if label in seen or first_t.get(label) == cur_t.get(label):
            continue
        at = next((i for i in range(1, len(tables)) if tables[i] is not None
                   and tables[i].get(label) != first_t.get(label)), len(lk))
        out.append((label, lk[at - 1][1], first_t.get(label) or NOT_LISTED))
        seen.add(label)
    _RAISED[key] = out
    _FIRST_TABLE[os.path.abspath(rd)] = first_t
    return out


def raised_lines(cfg, rd=None, audits=None):
    """The lines SUMMARY page 1 and REPORT must carry (RAISED, or STATUS_UNCOMPARED when no comparison could run)."""
    r = raised_statuses(cfg, rd, audits)
    if r is None:
        return [STATUS_UNCOMPARED]
    return [RAISED.format(label=lb, tp=tp, old=old) for lb, tp, old in r]


def raised_record_lines(cfg, rd=None, audits=None):
    """The mechanism of each raised status, for RUN_RECORD.md only (which patch, the first pin's status)."""
    r = raised_statuses(cfg, rd, audits)
    if r is None:
        return ["the statuses could not be recomputed with the first pin's result_status.py (STATUS_UNCOMPARED)"]
    return [RAISED_RECORD.format(label=lb, tp=tp, old=old) for lb, tp, old in r]


def weakened_parts(cfg, rd=None, audits=None):
    """The texts REPORT's "Checks weakened" row must carry, each a fact found from the raw records (verify_delivery
    checks them with the FIRST pin's copy of this file; make_report.weakened_row writes them). Add a part here for any
    further weakening of a check that is to be counted on that line."""
    rd, audits = rd or rounds_dir(cfg), audits or project.AUDITS
    return [TOOLS_PATCHED] if links(audits, rd) else []


def _flat(t):
    return " ".join(str(t).split())


def documents_problems(cfg, rd, audits):
    """[problem] when SUMMARY.md or REPORT.md lacks a RAISED line (or STATUS_UNCOMPARED), or REPORT.md's "Checks
    weakened" row lacks a part of weakened_parts."""
    out, docs = [], {}
    for name in ("SUMMARY.md", "REPORT.md"):
        p = os.path.join(rd, name)
        docs[name] = open(p, encoding="utf-8").read() if os.path.isfile(p) else None
    lines_ = raised_lines(cfg, rd, audits)
    # SWEEP-FIX review H1: the DELIVERED summary's table too -- a cell that is not the first pin's rendering and has no
    # line is refused (a presentation change the prepared lines did not see)
    first_t = _FIRST_TABLE.get(os.path.abspath(rd)) if lines_ != [STATUS_UNCOMPARED] else None
    if first_t is not None and docs["SUMMARY.md"] is not None:
        flagged = {lb for lb, _tp, _o in (raised_statuses(cfg, rd, audits) or [])}
        for lb, cell in summary_table(docs["SUMMARY.md"]).items():
            if lb not in flagged and lb in first_t and first_t[lb] != cell:
                out.append(f"SUMMARY.md shows {lb} as \"{cell}\", which the original checking software shows as "
                           f"\"{first_t[lb]}\", and no line says so (prepare again)")
    for line in lines_:
        for name, txt in docs.items():
            if txt is None or _flat(line) not in _flat(txt):
                out.append(f"{name} does not carry \"{line}\" (a tool patch raised a status; make_report writes the "
                           f"line at prepare: prepare again, never edit it away)")
    parts = weakened_parts(cfg, rd, audits)
    if parts:
        rows = [l for l in (docs["REPORT.md"] or "").splitlines() if re.match(rf"^\|\s*{WEAKENED_TITLE}\s*\|", l)]
        for part in parts:
            if not any(_flat(part) in _flat(r) for r in rows):
                out.append(f"REPORT.md's \"{WEAKENED_TITLE}\" row does not say \"{part}\" (prepare again)")
    return out


def delivery_problems(cfg):
    """[why --deliver refuses]: verify_delivery run by the apparatus of the run's FIRST pin (its scripts extracted
    from git, T34's pattern), the current one when that cannot run (said). Also every forced full round."""
    rd, audits = rounds_dir(cfg), project.AUDITS
    out = list(forced_round_problems(cfg, rd, audits))
    if not applied(cfg, rd, audits):
        return out
    fp = first_pin(rd).get("audits_commit")
    probs, note = _run_verifier(audits, rd, fp or "", ["verify-delivery"], "the first pin's verifier")
    if probs is None:
        out.append(f"note: {note}; the current apparatus verified the delivery instead")
        probs = verify_delivery(cfg, rd, audits)
    return out + [p for p in probs]


def chain_report(cfg, rd, audits, first=False):
    """[(TP, [problem] or None)] -- the maintainer's re-check (first=True: every link by THIS apparatus, which is
    the first pin's when run from its extraction)."""
    out = []
    for pin_commit, tp, _prev, _new, _e in links(audits, rd):
        try:
            out.append((tp, verify_link(cfg, audits, rd, tp, pin_commit)))
        except Exception as e:      # noqa: BLE001 -- reported, never a gate
            out.append((tp, [f"could not be verified: {e!r}"]))
    return out


# --- CLI ----------------------------------------------------------------------------------------------------------
def _cfg_for(rd):
    """The config a verifier uses: the first pin's frozen keys (name, rounds_dir, mode, ...)."""
    c = dict((first_pin(rd).get("config") or {}))
    c.setdefault("rounds_dir", os.path.relpath(rd, project.REPO))
    return c


def status(cfg):
    rd = rounds_dir(cfg)
    lines = []
    for tp in tps(rd):
        b = load(os.path.join(tp_dir(rd, tp), "BEGIN.json")) or {}
        lines.append(f"{tp} ({tp_state(rd, tp)}; stop {b.get('stop')}): attempts {attempts(rd, tp) or 'none'}; "
                     f"reviews " + ", ".join(f"{x}={(load(os.path.join(tp_dir(rd, tp), x)) or {}).get('verdict', 'pending')}"
                                             for _n, _m, x in reviews(rd, tp)))
    return lines or ["no tool patches"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", nargs="?", choices=["begin", "prepare", "facts", "review", "apply", "withdraw", "status",
                                                   "verify-link", "verify-chain", "verify-delivery"])
    ap.add_argument("--stop"); ap.add_argument("--tp"); ap.add_argument("--attempt", type=int)
    ap.add_argument("--reason"); ap.add_argument("--out"); ap.add_argument("--pin")
    ap.add_argument("--project"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--first-pin", action="store_true")
    ap.add_argument("--rounds-dir"); ap.add_argument("--audits-dir"); ap.add_argument("--repo-dir")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.audits_dir:
        project.AUDITS, project.PROJECTS = os.path.abspath(a.audits_dir), os.path.join(os.path.abspath(a.audits_dir), "projects")
    if a.repo_dir:
        project.REPO = os.path.abspath(a.repo_dir)
    try:
        if a.command in ("verify-link", "verify-chain", "verify-delivery"):
            rd = os.path.abspath(a.rounds_dir) if a.rounds_dir else rounds_dir(project.select(a.project)[0])
            cfg = _cfg_for(rd)
            if a.command == "verify-link":
                res = verify_link(cfg, project.AUDITS, rd, a.tp, a.pin)
            elif a.command == "verify-delivery":
                res = verify_delivery(cfg, rd, project.AUDITS)
            else:
                rep = chain_report(cfg, rd, project.AUDITS, first=a.first_pin)
                for tp, probs in rep:
                    print(f"{tp}: " + ("verified" if not probs else "NOT VERIFIED: " + "; ".join(probs)))
                res = [f"{tp}: {p}" for tp, probs in rep for p in probs]
            if a.json:
                print(json.dumps(res))
            else:
                for p in res:
                    print(f"FAIL[tool-patch] {p}")
            return 1 if res else 0
        cfg = project.select(a.project)[0]
        if a.command == "begin":
            tp, msg = begin(cfg, a.stop)
            print(msg)
        elif a.command == "prepare":
            f = prepare(cfg, a.tp)
            print(f"prepared attempt {f['attempt']} of {a.tp} (patch_sha256 {f['patch_sha256'][:12]}; approvals needed: "
                  f"{f['required_approvals']}; affects-review-inputs: {f['affects_review_inputs']}"
                  f"{' (forced: the blast radius shows PASS->FAIL)' if f['affects_forced'] else ''}). Next: "
                  f"python3 audits/tool_patch.py review --tp {a.tp}")
        elif a.command == "facts":
            txt, refuse = facts_text(cfg, a.tp, a.attempt)
            if a.out:
                open(a.out, "w", encoding="utf-8").write(txt)
            print(txt)
            for x in refuse:
                print(f"REFUSED (prepare would refuse this attempt): {x}", file=sys.stderr)
            return 1 if refuse else 0
        elif a.command == "review":
            p, line = review(cfg, a.tp)
            print(f"{os.path.relpath(p, project.REPO)}\n  spawn ONE fresh agent (general-purpose; Codex: agent_type "
                  f"{REVIEWER_ROLE}, fork_turns none; never a lane, the adjudicator or yourself) with: {line}\n"
                  f"  then seal its verdict from its own LANE_COMPLETION line: python3 audits/lane_auth.py seal "
                  f"--verdict <verdict> --sha256 <sha256> --agent-id <its id>")
        elif a.command == "apply":
            h = apply(cfg, a.tp)
            rd = rounds_dir(cfg)
            b = load(os.path.join(tp_dir(rd, a.tp), "BEGIN.json")) or {}
            print(f"applied {a.tp} in {h[:11]} and re-pinned (pin (tool-patch {a.tp})). Now: python3 audits/stops.py "
                  f"close --stop {b.get('stop')} --cured \"tool-patch {a.tp}\"")
        elif a.command == "withdraw":
            withdraw(cfg, a.tp, a.reason)
            print(f"withdrew {a.tp}: go back to the printed cure of its stop (or begin a new tool patch on it)")
        elif a.command == "status":
            print("\n".join(status(cfg)))
        else:
            ap.error("give a command")
        return 0
    except project.SelectionError as e:
        print(f"FAIL: {e}")
        return 2
    except Refused as e:
        print(f"REFUSED: {e}")
        return 1


# --- selftest --------------------------------------------------------------------------------------------------
# SWEEP-FIX D3 (RELEASE-SWEEP T2): the selftest's sample bug lives in a module the selftest writes into its own scratch
# apparatus (tp_sample.py, never shipped), not in a real non-core file: fact (b) runs this selftest on every patched
# apparatus, and pinning the exact text of e.g. result_status.py made a correct patch of that file fail for ever
TP_SAMPLE = """\"\"\"The tool-patch selftest's sample non-core module (written into its scratch apparatus only).\"\"\"


def route(cases):
    \"\"\"[(name, 'adjudicator' or 'row')] of [(name, kind, embedded)].\"\"\"
    out = []
    for name, kind, e in cases:
        emb = any((e,))
        if emb or kind.startswith("unclassified"):
            out.append((name, "adjudicator"))
        else:
            out.append((name, "row"))
    return out
"""
REGRESSION_TEST = """#!/usr/bin/env python3
\"\"\"Regression (tool patch; bench1 S2's shape): an inline binder with a valid row is not routed as 'unclassified'.\"\"\"
import argparse, sys
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser(); ap.add_argument("--apparatus", required=True); a = ap.parse_args()
sys.path.insert(0, a.apparatus)
import tp_sample
bad = [n for n, r in tp_sample.route([("P.lem:h", "inline hypothesis (its type uses no project constant)", False)])
       if r != "row"]
print("regression:", ("FAILED " + str(bad)) if bad else "ok")
sys.exit(1 if bad else 0)
"""
DIAGNOSIS_TEXT = """## The check
`python3 audits/make_report.py --check` (stop S1), via the sample module tp_sample.py.

## The failing case
RED[adj-record] Lemma 2.4: unclassified assumption `P.lem:h` although its Hypotheses row says `yes`.

## The cause
tp_sample.py `route`: `kind.startswith(("unclassified", "inline"))` routes every inline binder
to the adjudicator whatever its row says.

## The correct behaviour
An inline binder is classified by its `## Hypotheses` row, as a named hypothesis is.

## Why no faithfulness result depends on the change
Only the summary status of an inline binder with a valid row changes; the lanes' verdicts are untouched.

## Whether the old behaviour is right elsewhere
An embedded or unclassified assumption is still routed to the adjudicator.

affects-review-inputs: no
regression: tests/regressions/tp_inline_binder.py
"""
BUG = ('        if emb or kind.startswith("unclassified"):',
       '        if emb or kind.startswith(("unclassified", "inline")):')


def selftest():
    import contextlib, io, lane_auth, integrity, stops
    global RUNNER
    here = os.path.dirname(os.path.abspath(__file__))
    base = tempfile.mkdtemp(prefix="tool-patch-selftest-")
    nested = globals().get("NESTED", "FORMALIZE_TP_SELFTEST")
    keep = (project.REPO, project.AUDITS, RUNNER, stops.RUNNER, os.environ.get(nested))
    os.environ[nested] = "1"         # every process this selftest starts judges tool_patch.py's floor by pattern
    good = []

    def say(name, ok):
        good.append(bool(ok))
        print(("  ok    " if ok else "  FAIL  ") + name)

    def refused(f, *a, **k):
        try:
            f(*a, **k)
        except (Refused, stops.Refused, ValueError) as e:
            return str(e)
        return ""
    d = os.path.join(base, "run")
    rd = os.path.join(d, "P")
    G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True).stdout.strip()
    try:
        os.makedirs(rd)
        # Codex e2e TP1: the facts a reviewer re-derives must equal FACTS.json for an honest patch -- two runs with
        # their own random scratch trees (scratch_tree's mkdtemp), a test's own temporary names and object addresses
        # record the same regression tail, selftest tail and blast lines; exits and the rest of the text unchanged
        RUNNER, reps = None, []
        reg = ("import os, sys, tempfile\napp = sys.argv[2]\nif not os.path.exists(os.path.join(app, 'FIXED')):\n"
               "    raise RuntimeError(f'pinned {app} {tempfile.mkdtemp(prefix=\"reg-\")} {object()!r}')\nprint('ok')\n")
        for _ in range(2):
            pq = [os.path.join(tempfile.mkdtemp(prefix="tool-patch-", dir=base), "audits") for _ in range(2)]
            for p_ in pq:
                os.makedirs(os.path.join(p_, "tests", "regressions"))
                open(os.path.join(p_, "tests", "regressions", "r.py"), "w").write(reg)
                open(os.path.join(p_, "boom.py"), "w").write(f"raise SystemExit('FAIL[tooling] in {p_} at ' + repr(object()))\n")
            open(os.path.join(pq[1], "FIXED"), "w").close()
            reps.append((regression(pq[0], pq[1], "tests/regressions/r.py"), run_selftests(pq[1], ["boom.py"])["tails"],
                         _outcome(1, f"RED[build] {os.path.dirname(pq[0])}/proj/a.lean\n", roots=(os.path.dirname(pq[0]),))))
        say("TP1 (Codex e2e): recorded facts are reproducible -- the scratch roots, temporary names and object "
            "addresses are normalised (regression tail, selftest tails, blast lines); exits and text kept",
            reps[0] == reps[1] and reps[0][0]["passes"] and reps[0][0]["pinned"]["exit"] == 1
            and any("<scratch>/audits/tests/regressions/r.py" in l for l in reps[0][0]["pinned"]["tail"])
            and any("RuntimeError: pinned <scratch>/audits <tmp> <object object at 0x…>" == l
                    for l in reps[0][0]["pinned"]["tail"])
            and reps[0][1] == {"boom.py": ["FAIL[tooling] in <scratch>/audits at <object object at 0x…>"]}
            and reps[0][2] == {"exit": 1, "lines": ["RED[build] <scratch>/proj/a.lean"]})
        for n in os.listdir(here):
            src = os.path.join(here, n)
            if n in ("projects", "__pycache__") or not (integrity.is_tooling(n) or n == "project_template.json"):
                continue
            (shutil.copytree(src, os.path.join(d, n), ignore=shutil.ignore_patterns("__pycache__", "regressions"))
             if os.path.isdir(src) else shutil.copy(src, d))
        rs = os.path.join(d, "tp_sample.py")     # the sample non-core module (SWEEP-FIX D3), with the pinned tool's bug
        open(rs, "w").write(TP_SAMPLE.replace(BUG[0], BUG[1], 1))
        # SWEEP-FIX D3 (T2) regression: the scratch apparatus's result_status.py has the lines this selftest used to pin
        # rewritten, as a correct reviewed patch of that file would leave them (same behaviour, other text). Fact (b)
        # runs this selftest on a patched apparatus: it must pass whatever a non-core file's text is
        rsr = os.path.join(d, "result_status.py")
        _t = open(rsr).read()
        open(rsr, "w").write(_t.replace(BUG[0], '        if emb or kind[:len("unclassified")] == "unclassified":', 1)
                             .replace("        emb = any(", "        emb = any (", 1))
        rewritten = BUG[0] not in open(rsr).read() and "        emb = any(" not in open(rsr).read()
        open(os.path.join(d, ".gitignore"), "w").write("__pycache__/\n")
        open(os.path.join(rd, "RUN_LOG.md"), "w").write("# Run log\n\n## Stops\n")
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        G("add", "-A"); G("commit", "-qm", "setup")
        project.REPO = project.AUDITS = d
        agent = os.path.join(d, "agents", "auditor.md")
        cfg = {"name": "P", "rounds_dir": "P", "mode": "release", "involvement": "hands-off",
               "involvement_answer": "(c)", "namespace": "P", "lean_files": [], "build_cmds": []}
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd)
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", "pin")
        outs = {"make_report": (1, "FAIL[report] Lemma 2.4: unclassified assumption `P.lem:h`\n")}
        stops.RUNNER = lambda argv: outs.get(os.path.basename(next((x for x in argv if x.endswith(".py")), "b"))[:-3], (0, ""))
        stat = {"first": {}, "cur": {}}       # SWEEP-FIX D4: the statuses each apparatus computes (stand-in)

        def stand_in(p2f=(), floor_real=False):
            def run(kind, *a):
                if kind == "statuses":
                    return stat["first"] if a[0].endswith(os.sep + os.path.join("0", "audits")) else stat["cur"]
                if kind == "summary":       # SWEEP-FIX review H1: the SUMMARY each apparatus renders (stand-in)
                    return (stat.get("sfirst", "") if a[0].endswith(os.sep + os.path.join("0", "audits"))
                            else stat.get("scur", ""))
                if kind == "selftests":
                    return {"run": [], "failed": [], "passes": True}
                if kind == "blast":
                    return {"checks": 1, "changed": [{"check": c} for c in p2f], "pass_to_fail": list(p2f)}
                if kind == "floor" and not floor_real:
                    rd_ = lambda f: open(os.path.join(a[0], f)).read() if os.path.exists(os.path.join(a[0], f)) else None
                    return {"ids": [m[0].split()[0] for m in a[1]],
                            "hits": [{"id": i, "why": w} for i, w in floor_pattern_hits(a[1], rd_)]}
                return None
            return run
        RUNNER = stand_in()
        IC = lambda c_=cfg: [m for sv, m in integrity.check(d, c_, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
                             if sv == "FAIL"]
        s1, m1 = stops.open_stop(cfg, note="make_report --check refuses an inline binder with a valid row",
                                 cause="tool-bug", check="python3 audits/make_report.py --check")

        def write_attempt(tp, n, edits, diag=DIAGNOSIS_TEXT, reg=REGRESSION_TEST, regname="tp_inline_binder", answers=(),
                          ctx=3, newfiles=None):
            """Make the attempt's patch in the tree, diff it, restore the tree; write DIAGNOSIS.md and patch.diff.
            `answers`: the earlier rejecting reviews ("TP<k> review-<n>-<m>.json") its revision answers."""
            diag = diag.replace("tests/regressions/tp_inline_binder.py", f"tests/regressions/{regname}.py")
            if answers:
                diag += f"\n{ANSWERS_HEADING}\n" + "".join(f"- {x}: answered (the revision addresses it)\n" for x in answers)
            for f, old, new in edits:
                pf = os.path.join(d, f)
                _t = open(pf).read()
                open(pf, "w").write(_t.replace(old, new, 1))
            rt = os.path.join(d, "tests", "regressions", f"{regname}.py")
            if reg is not None:
                os.makedirs(os.path.dirname(rt), exist_ok=True)
                open(rt, "w").write(reg)
                G("add", "-N", "--", f"tests/regressions/{regname}.py")
            for rel_, text_ in (newfiles or {}).items():
                open(os.path.join(d, rel_), "w").write(text_)
                G("add", "-N", "--", rel_)
            patch = subprocess.run(["git", "-C", d, "diff", "--relative", f"-U{ctx}", "--", ".", ":!P"], capture_output=True,
                                   text=True).stdout
            G("reset", "-q", "--", "tests", *(newfiles or {})); G("checkout", "--", *[f for f, _o, _n in edits])
            for rel_ in (newfiles or {}):
                os.remove(os.path.join(d, rel_))
            if os.path.exists(rt):
                os.remove(rt)
            ad = os.path.join(tp_dir(rd, tp), f"A{n}")
            os.makedirs(ad, exist_ok=True)
            open(os.path.join(ad, "DIAGNOSIS.md"), "w").write(diag)
            open(os.path.join(ad, "patch.diff"), "w").write(patch)
            return patch

        def hand_facts(tp, n, patch):
            """An operator past a refusing prepare: FACTS.json written and committed by hand."""
            ad_ = os.path.join(tp_dir(rd, tp), f"A{n}")
            f_, _r = compute_facts(cfg, tp, n, open(os.path.join(ad_, "DIAGNOSIS.md")).read(), patch)
            json.dump(f_, open(os.path.join(ad_, "FACTS.json"), "w"), indent=1, sort_keys=True)
            commit_paths(d, [os.path.join(ad_, x) for x in ("DIAGNOSIS.md", "patch.diff", "FACTS.json")],
                         f"tool-patch {tp} diagnosis {n}")

        def hand_apply(tp, n, patch):
            """An operator past a refusing apply: the diff committed and re-pinned by hand under the TP's subjects."""
            open(os.path.join(d, "x.diff"), "w").write(patch)
            G("apply", "--index", "x.diff"); os.remove(os.path.join(d, "x.diff"))
            G("commit", "-qm", f"tool-patch {tp} apply")
            integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin=f"tool-patch {tp}",
                          tool_patch={"tool_patch": tp, "attempt": n, "patch_sha256": sha_bytes(patch.encode()),
                                      "review_seals": [], "stop": s1})
            G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", f"pin (tool-patch {tp})")

        def reviewer(line, verdict, agent_id, findings=(), sha=None, seal=True):
            tok = re.search(r"lane_token is ([0-9a-f]{64})", line).group(1)
            pp = re.search(r"Read the file (\S+) and", line).group(1)
            vp = re.search(r"Write that JSON object, and nothing else, to (\S+)", open(pp).read()).group(1)
            sha = sha or re.search(r"\"patch_sha256\": \"([0-9a-f]{64})\"", open(pp).read())
            sha = sha if isinstance(sha, str) else re.search(r"THE PATCH \(patch.diff, sha256 ([0-9a-f]{64})\)",
                                                             open(pp).read()).group(1)
            raw = json.dumps({"lane_token": tok, "verdict": verdict, "patch_sha256": sha, "facts_rederived": "same",
                              "findings": list(findings), "probes": {}}, sort_keys=True).encode()
            open(vp, "wb").write(raw)
            if seal:
                lane_auth.seal(vp, sha_bytes(raw), agent_id)
            return vp
        FIX = ("tp_sample.py", BUG[1], BUG[0])
        h_open = G("rev-parse", "HEAD")
        # ---- S-TP1: begin, prepare (fact (a) for real: the regression fails pinned, passes patched), review, apply
        tp, msg = begin(cfg, s1)
        write_attempt(tp, 1, [FIX])
        f1 = prepare(cfg, tp)
        pp1, line1 = review(cfg, tp)
        body1 = open(pp1).read()
        ftxt, frf = facts_text(cfg, tp, 1)
        say("LOW 4: `tool_patch.py facts` prints exactly what prepare wrote to FACTS.json (no extra key; refusals go to "
            "stderr and the exit code)",
            ftxt == open(os.path.join(tp_dir(rd, tp), "A1", "FACTS.json")).read() and not frf)
        pre_apply = refused(apply, cfg, tp)
        reviewer(line1, "approve", "reviewer-1")
        cfg["standing_defers"] = [{"id": "D1", "item": "x"}]     # a grow-only key grew since the pin (bench2 replay)
        h_app = apply(cfg, tp)
        subj = G("log", "-2", "--format=%s").splitlines()
        pind = json.load(open(os.path.join(rd, "TOOLING_PIN.json")))
        ic1 = IC()
        outs["make_report"] = (0, "report: OK\n")
        rec = stops.close_stop(cfg, s1, cured=f"tool-patch {tp}")
        ic2 = IC()
        say("S-TP1 (bench1 S2's result_status bug): begin, prepare (fact (a) for real: the new regression test fails on "
            "the pinned tool, passes on the patched one), a fresh reviewer's sealed approval, apply = two commits "
            "(\"tool-patch TP1 apply\" tooling only, then \"pin (tool-patch TP1)\" whose audits_commit is the apply "
            "commit, with its repins entry); integrity --check passes (the link verified by the pinned-before "
            "apparatus); S1 closes --cured \"tool-patch TP1\"; the run goes on",
            tp == "TP1" and "DIAGNOSIS.md" in msg and f1["regression"]["passes"] and f1["required_approvals"] == 1
            and f1["regression"]["pinned"]["exit"] == 1 and f1["regression"]["patched"]["exit"] == 0
            and "not approved" in pre_apply and "REFUTE" in body1 and f1["patch_sha256"] in body1
            and subj == [f"pin (tool-patch {tp})", f"tool-patch {tp} apply"] and pind["audits_commit"] == h_app
            and pind["repins"][-1]["tool_patch"] == tp and pind["repins"][-1]["stop"] == s1
            and not ic1 and not ic2 and rec["by"] == "cure" and rec.get("tool_patch") == tp
            and BUG[0] in open(rs).read())
        say("SWEEP-FIX D3 (T2): with result_status.py's lines that the core selftest used to pin rewritten (a correct "
            "patch of a non-core file), the sample bug's route still works: fact (a) for real, apply, the link verifies",
            rewritten and f1["regression"]["passes"] and not ic1 and not ic2 and BUG[0] in open(rs).read())
        say("re-check 3 (C): the reviewer prompt no longer says the floor covers the axiom checks, says what it does not "
            "cover and that the proof-validity core cannot be patched, and asks about behaviour on inputs no test "
            "exercises and about changes to which code is imported or run (shadowing, import paths, config/data files)",
            "axiom, freeze, seal, token" not in body1 and "does NOT cover" in body1 and "the axiom sweep" in body1
            and "cannot be patched" in body1 and "inputs the selftests and the regression" in body1
            and "module shadowing" in body1 and "data file a check reads" in body1)
        rl = record_lines(cfg)
        rr = os.path.join(rd, "RUN_RECORD.md")
        open(rr, "w").write("\n".join(rl) + "\n")
        rep_, sum_ = os.path.join(rd, "REPORT.md"), os.path.join(rd, "SUMMARY.md")
        wk_row = f"| {WEAKENED_TITLE} | the final delivery checks ran on the pinned audit tools | {TOOLS_PATCHED} |\n"
        open(rep_, "w").write("# Report\n\n| layer | establishes | status |\n|---|---|---|\n" + wk_row)
        open(sum_, "w").write("# Summary\n")
        vd = verify_delivery(cfg, rd, d)
        open(rr, "w").write("\n".join(l for l in rl if f1["patch_sha256"] not in l) + "\n")
        vd_bad = verify_delivery(cfg, rd, d)
        os.remove(rr)
        vd_none = verify_delivery(cfg, rd, d)
        say("RUN_RECORD.md (record_lines) lists TP1 with its diagnosis, diff, reviewer verdict, patch_sha256, review "
            "seal and apply commit, and the standalone first-pin re-check command; the delivery check passes on it, "
            "and refuses a record that omits the sha, or no record at all (M7)",
            any("TP1" in l and h_app in l and f1["patch_sha256"] in l for l in rl) and any("verify-chain --first-pin" in l for l in rl)
            and any("approve (agent reviewer-1)" in l for l in rl) and not vd and vd_bad and vd_none
            and applied(cfg) == [(tp, f1["patch_sha256"], pind["repins"][-1]["review_seals"][0], h_app)])
        # ---- SWEEP-FIX D4 (RELEASE-SWEEP Task A, HIGH 6): bench1 S2's patch turns Lemma 2.4 from "not established"
        # into "faithful"; the documents must say so, recomputed at --deliver by the FIRST pin's copy of this file
        open(rr, "w").write("\n".join(rl) + "\n")
        old_ = "not established: unclassified assumption `P.lem:h`"
        stat["first"], stat["cur"] = {"Lemma 2.4": [old_], "Lemma 1.1": ["faithful"]}, \
            {"Lemma 2.4": ["faithful"], "Lemma 1.1": ["faithful"]}
        _RAISED.clear()
        ln_ = RAISED.format(label="Lemma 2.4", tp=tp, old=old_)
        d4_missing = verify_delivery(cfg, rd, d)
        open(sum_, "w").write(f"# Summary\n\n**{ln_}**\n")
        open(rep_, "w").write("# Report\n\n| layer | establishes | status |\n|---|---|---|\n" + wk_row
                              + f"\n### Statuses raised by tool patches\n\n- {ln_}\n")
        d4_ok = verify_delivery(cfg, rd, d)
        open(rep_, "w").write(f"# Report\n\n- {ln_}\n")
        d4_nowk = verify_delivery(cfg, rd, d)
        stat["first"] = None
        _RAISED.clear()
        d4_none = verify_delivery(cfg, rd, d)
        say("SWEEP-FIX D4: a tool patch that raises a result's status (bench1 S2's: \"not established\" -> \"faithful\") "
            "is named, with the first-pin tools' status, by the line on SUMMARY page 1 and in REPORT; --deliver (the "
            "first pin's verify_delivery) refuses a document without it, a REPORT without the \"Checks weakened\" row, "
            "and, when the first pin's result_status cannot run, documents that do not say the statuses were not compared",
            raised_statuses(cfg) is None and raised_lines(cfg) == [STATUS_UNCOMPARED]
            and sum("does not carry" in x and ln_ in x for x in d4_missing) == 2 and not d4_ok
            and any("Checks weakened" in x for x in d4_nowk) and not any(ln_ in x for x in d4_nowk)
            and sum(STATUS_UNCOMPARED in x for x in d4_none) == 2)
        say("SWEEP-FIX D4: the strength order -- only a stronger status is a raise (a weaker one, a rewording of the "
            "same reason, or an unchanged list is not); a qualifying item dropped at the same strength is one",
            status_raised([old_], ["faithful"]) and status_raised(["stated only (x)"], ["proved assuming `H`"])
            and status_raised(["differs (r 1): a", "vacuous (r 2)"], ["differs (r 1): a"])
            and status_raised(["proved assuming `H`"], ["faithful under reading 1: x"])
            and not status_raised(["faithful"], [old_]) and not status_raised([old_], ["not established: other words"])
            and not status_raised(["faithful under reading 1: x"], ["faithful under reading 2: y"])
            and not status_raised(["faithful"], ["faithful"]) and not status_raised([], ["faithful"])
            and status_raised(["something new: z"], ["faithful"]))
        # ---- SWEEP-FIX review B3, M6, H1: an unknown status word is a raise; a result dropped from (or added to) the
        # statuses is a raise candidate; the presentation layer (the SUMMARY table the FIRST pin's make_report renders)
        # is compared too, and the delivered SUMMARY's table must match it or carry the line
        b3_ = (status_raised(["not established: x"], ["proved"]) and status_raised(["not established: x"], ["verified"])
               and status_raised(["stated only (y)"], ["established"]) and status_raised(["differs (row 2)"], ["proved (checked)"])
               and not status_raised(["faithful"], ["not verified: the proofs could not be checked"])
               and not status_raised(["proved"], ["proved"]))
        stat["first"], stat["cur"] = {"Lemma 2.4": ["faithful"], "Lemma 3.1": ["not established: y"]}, \
            {"Lemma 2.4": ["faithful"]}
        _RAISED.clear()
        m6_ = raised_statuses(cfg)
        stat["first"], stat["cur"] = {"Lemma 5": ["not established: z"]}, {"Lemma 5": ["not established: z"]}
        stat["sfirst"] = "# S\n\n## Results\n\n| Status | Results |\n|---|---|\n| not established | Lemma 5 |\n\n## X\n"
        stat["scur"] = stat["sfirst"].replace("| not established | Lemma 5 |", "| faithful | Lemma 5 |")
        _RAISED.clear()
        h1_ = raised_statuses(cfg)
        ln_h1 = RAISED.format(label="Lemma 5", tp=tp, old="not established")
        open(sum_, "w").write(stat["scur"] + f"\n**{ln_h1}**\n")
        open(rep_, "w").write("# Report\n\n| layer | establishes | status |\n|---|---|---|\n" + wk_row + f"\n- {ln_h1}\n")
        h1_ok = documents_problems(cfg, rd, d)
        stat["scur"] = stat["sfirst"]          # the prepared lines see no change...
        _RAISED.clear()
        open(sum_, "w").write(stat["sfirst"].replace("| not established | Lemma 5 |", "| faithful | Lemma 5 |"))
        h1_bad = documents_problems(cfg, rd, d)   # ...but the delivered SUMMARY shows a stronger cell
        stat["scur"] = None
        _RAISED.clear()
        h1_none = raised_statuses(cfg)
        stat.pop("sfirst"); stat.pop("scur")
        _RAISED.clear()
        say("SWEEP-FIX review B3/M6/H1: an unknown status word the old list lacks is a raise; a result the first pin lists "
            "and the current tools drop is flagged; a SUMMARY cell the first pin's make_report renders weaker is flagged "
            "(and the delivered SUMMARY must match it or carry the line); a summary that cannot be rendered fails closed",
            b3_ and m6_ == [("Lemma 3.1", tp, "not established: y")] and h1_ == [("Lemma 5", tp, "not established")]
            and not h1_ok and any("SUMMARY.md shows Lemma 5 as \"faithful\"" in x for x in h1_bad)
            and h1_none is None)
        fk = os.path.join(base, "fake-apparatus")
        os.makedirs(fk)
        open(os.path.join(fk, "project.py"), "w").write("AUDITS = REPO = PROJECTS = None\n"
                                                         "def select(name):\n    raise ValueError(name)\n")
        open(os.path.join(fk, "result_status.py"), "w").write(
            "import project\ndef statuses(cfg):\n    return [['Lemma 1', ['faithful', cfg['name'], project.REPO]]]\n")
        RUNNER = None
        real_ = apparatus_statuses(fk, cfg)
        RUNNER = stand_in()
        say("SWEEP-FIX D4: an apparatus's statuses are computed by its own result_status.py in a subprocess, on the live "
            "records (project.REPO set) and the run's config",
            real_ == {"Lemma 1": ["faithful", "P", d]})
        stat["first"], stat["cur"] = {}, {}
        _RAISED.clear()
        for f_ in (sum_, rep_, rr):
            os.remove(f_)
        tr = stops.trail_problems(cfg, d, rd)
        info = applied_info(cfg, tp)
        say("the stop trail accepts the tool-patch close; applied_info names the stop and the regression command; the "
            "first-pin standalone re-check verifies the link",
            not tr and info["stop"] == s1 and info["regression_cmd"].endswith("tp_inline_binder.py --apparatus audits")
            and chain_report(_cfg_for(rd), rd, d) == [(tp, [])])
        _row = lambda b, a, e0=1, e1=1: {"check": "make_report.py --check --delivery", "before": {"exit": e0, "lines": b},
                                         "after": {"exit": e1, "lines": a}}
        say("DOC-FIX replay (conf1): a generator patch whose only new failure lines are delivery preconditions "
            "(RED[deliver]: stale prepared documents, their reader gates) forces no full round; a new RED[adj-record], "
            "or a PASS->FAIL with no new line, still does",
            pass_to_fail([_row([], ["RED[deliver] SUMMARY.md is stale: x", "RED[deliver] reader gate report: y"], 0, 1)]) == []
            and pass_to_fail([_row(["RED[deliver] a"], ["RED[deliver] a", "RED[adj-record] Lemma 1: z"])]) != []
            and pass_to_fail([_row([], [], 0, 1)]) != []
            and pass_to_fail([_row(["RED[deliver] a"], ["RED[deliver] b"], 1, 1)]) == []
            and pass_to_fail([_row([], ["FAIL[ownership] x"], 0, 1)]) != [])
        # DOC-FIX replay (conf1): a stop opened with no --check (a generator fault a reader found) is closed by the
        # patch's regression command; deliver_gate re-runs it although it is no FORMS check (stops.tool_patch_checks)
        _sd = os.path.join(rd, "stops", "S99")
        os.makedirs(_sd)
        json.dump({"by": "cure", "tool_patch": tp, "check": info["regression_cmd"]}, open(os.path.join(_sd, "CLOSED.json"), "w"))
        json.dump({"stop": "S99"}, open(os.path.join(_sd, "STOP.json"), "w"))
        _tc1 = stops.tool_patch_checks(cfg)
        _dg1 = [x for x in stops.deliver_gate(cfg) if "tp_inline_binder" in x]
        json.dump({"by": "cure", "tool_patch": tp, "check": "python3 audits/tests/regressions/other.py --apparatus audits"},
                  open(os.path.join(_sd, "CLOSED.json"), "w"))
        _tc2 = stops.tool_patch_checks(cfg)
        shutil.rmtree(_sd)
        say("DOC-FIX: a stop cured by a tool patch with no --check is re-checked at delivery by the patch's own "
            "regression command (allowed although no FORMS check); any other tests/ command is not",
            _tc1 == {info["regression_cmd"]} and _tc2 == set() and _dg1 == []
            and stops.command_problem(info["regression_cmd"], cfg) is not None)
        outs["integrity"] = (1, "FAIL[tooling] x\n")
        s2_, _m = stops.open_stop(cfg, cmd="python3 audits/integrity.py --check")
        other = refused(stops.close_stop, cfg, s2_, cured=f"tool-patch {tp}")
        stops.close_stop(cfg, s2_, human="x"); outs.pop("integrity")
        say("a tool-patch close names a patch made for ITS stop (TP1 cannot close another stop)",
            f"made for stop {s1}" in other)
        h_done = G("rev-parse", "HEAD")
        # ---- M2: the applied diff is not the reviewed one (one extra line), re-pinned by hand as the TP's pin
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tp_, _m = begin(cfg, s1); write_attempt(tp_, 1, [FIX]); prepare(cfg, tp_)
        _p, ln = review(cfg, tp_); reviewer(ln, "approve", "reviewer-m2")
        h_pre = G("rev-parse", "HEAD")
        patch = open(os.path.join(tp_dir(rd, tp_), "A1", "patch.diff")).read()
        open(os.path.join(d, "x.diff"), "w").write(patch)
        G("apply", "--index", "x.diff"); os.remove(os.path.join(d, "x.diff"))
        open(rs, "a").write("# one more line\n"); G("add", "tp_sample.py")
        G("commit", "-qm", f"tool-patch {tp_} apply")
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin=f"tool-patch {tp_}",
                      tool_patch={"tool_patch": tp_, "attempt": 1, "patch_sha256": sha_bytes(patch.encode()),
                                  "review_seals": [], "stop": s1})
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", f"pin (tool-patch {tp_})")
        m2 = IC()
        say("M2: an applied diff that is not byte-identical to the reviewed patch.diff is FAIL[tool-patch]",
            any("[tool-patch]" in x and "not byte-identical" in x for x in m2))
        # ---- M3: tooling changed under a tool-patch subject with no sealed approval / with a reject seal
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tp_, _m = begin(cfg, s1); write_attempt(tp_, 1, [FIX]); prepare(cfg, tp_)
        _p, ln = review(cfg, tp_)
        r_unsealed = refused(apply, cfg, tp_)
        reviewer(ln, "reject", "reviewer-m3", findings=["the diagnosis is wrong"])
        r_reject = refused(apply, cfg, tp_)
        r_review_again = refused(review, cfg, tp_)
        patch = open(os.path.join(tp_dir(rd, tp_), "A1", "patch.diff")).read()
        open(os.path.join(d, "x.diff"), "w").write(patch)
        G("apply", "--index", "x.diff"); os.remove(os.path.join(d, "x.diff"))
        G("commit", "-qm", f"tool-patch {tp_} apply")
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin=f"tool-patch {tp_}",
                      tool_patch={"tool_patch": tp_, "attempt": 1, "patch_sha256": sha_bytes(patch.encode()),
                                  "review_seals": [], "stop": s1})
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", f"pin (tool-patch {tp_})")
        m3 = IC()
        say("M3: apply refuses an issued review that is not sealed, and a rejected attempt; the same tooling change "
            "committed and pinned by hand under the tool-patch subjects is FAIL[tool-patch] (rejected); review refuses "
            "a new reviewer for a rejected attempt (no shopping)",
            "sealed before apply" in r_unsealed and "rejected" in r_reject and "rejected" in r_review_again
            and any("[tool-patch]" in x and "rejected" in x for x in m3))
        # ---- unreviewed tooling change: still tamper (FAIL[tooling]); a plain re-pin over it is FAIL[pin] (M5);
        # a plain re-pin that changes no tooling (the gitmeta snapshot cure, R7) passes
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        _t = open(rs).read(); open(rs, "w").write(_t.replace(BUG[1], BUG[0], 1)); G("commit", "-qam", "fix result_status")
        t1 = IC()
        # RELEASE-SWEEP I1: pin() refuses it now; such a re-pin in the history (an older tool's, or written by hand)
        rp_ = integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin="a bug in result_status")
        pdoc_ = json.load(open(os.path.join(rd, "TOOLING_PIN.json")))
        json.dump(dict(pdoc_, audits_commit=G("rev-parse", "HEAD")), open(os.path.join(rd, "TOOLING_PIN.json"), "w"))
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", "pin (repin: a bug in result_status)")
        t2 = IC()
        G("reset", "-q", "--hard", h_open)
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin="gitmeta snapshot")
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", "pin (repin: gitmeta snapshot)")
        t3 = IC()
        say("an unreviewed tooling change is still FAIL[tooling]; a plain release re-pin over it is FAIL[pin] (M5); a "
            "plain re-pin that changes no tooling passes (R7: the gitmeta re-pin)",
            any(x.startswith("[tooling]") for x in t1) and any(x.startswith("[pin]") and "tool patch" in x for x in t2)
            and rp_[0] is None and "reviewed tool patch" in rp_[1]
            and not t3)
        # ---- reviewer shopping: the same diff after a reject; an unsealed reject; an approver seen elsewhere
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tp_, _m = begin(cfg, s1); write_attempt(tp_, 1, [FIX]); prepare(cfg, tp_)
        _p, ln = review(cfg, tp_); reviewer(ln, "reject", "reviewer-s1", findings=["F1: misses the embedded case"])
        write_attempt(tp_, 2, [FIX])
        same = refused(prepare, cfg, tp_)
        write_attempt(tp_, 2, [FIX, ("tp_sample.py", "        emb = any(", "        emb = True and any(")])
        unans = refused(prepare, cfg, tp_)
        write_attempt(tp_, 2, [FIX, ("tp_sample.py", "        emb = any(", "        emb = True and any(")],
                      answers=[f"{tp_} review-1-1.json"])
        prepare(cfg, tp_)
        pp2, ln2 = review(cfg, tp_)
        b2 = open(pp2).read()
        reviewer(ln2, "approve", "reviewer-s1")           # the agent that rejected attempt 1
        again = refused(apply, cfg, tp_)
        say("anti-shopping (R5): the same diff after a reject is refused at prepare; a revision that does not name and "
            "answer the reject is refused; attempt 2's prompt carries attempt 1's diff and sealed findings; an approving "
            "agent id already seen in the run does not count",
            "rejected before" in same and "F1: misses the embedded case" in b2 and "review-1-1.json: reject" in b2
            and "a reviewer must be fresh" in again and f"does not answer {tp_} review-1-1.json" in unans)
        # ---- withdraw (the check was right; or a reviewer never returned): never a dead end; M8: 3 rejects, then OK
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tp_, _m = begin(cfg, s1); write_attempt(tp_, 1, [FIX]); prepare(cfg, tp_)
        _p, ln = review(cfg, tp_)                          # the reviewer never returns
        stuck = refused(review, cfg, tp_)
        reiss = refused(lane_auth.reissue, os.path.join(tp_dir(rd, tp_), "review-1-1.json"), "lost")
        withdraw(cfg, tp_, "the reviewer never returned")
        wd = refused(apply, cfg, tp_)
        tp2, _m = begin(cfg, s1)
        n_ok = []
        for n in range(1, 5):
            write_attempt(tp2, n, [FIX, ("tp_sample.py", "        emb = any(", f"        emb = bool({n}) and any(")],
                          answers=[f"{tp_} review-1-1.json"] + [f"{tp2} review-{k}-1.json" for k in range(1, n)])
            prepare(cfg, tp2)
            pp_, ln_ = review(cfg, tp2)
            n_ok.append(open(pp_).read().count("review-") >= n)
            reviewer(ln_, "reject" if n < 4 else "approve", f"reviewer-m8-{n}", findings=[f"finding {n}"])
        bm8 = open(pp_).read()
        # RELEASE-SWEEP I4: an apply killed between its two commits ("apply" committed, its pin not): integrity's
        # FAIL[tool-patch] names `apply` again, and apply resumes (before: "TP<k> is applied", and no cure ran)
        global _pin_applied
        keep_pa = _pin_applied

        def _killed(*_a, **_k):
            raise KeyboardInterrupt
        _pin_applied = _killed
        try:
            apply(cfg, tp2)
        except KeyboardInterrupt:
            pass
        finally:
            _pin_applied = keep_pa
        np8 = [m for m in IC() if "has no pin" in m]
        h8 = apply(cfg, tp2)
        say("RELEASE-SWEEP I4: an apply interrupted after its apply commit is FAIL[tool-patch] \"has no pin\", whose "
            "printed cure (apply again) resumes it: the pin commit follows and the FAIL clears",
            np8 and f"apply --tp {tp2}" in np8[0] and h8 == apply_commit(d, tp2)
            and G("log", "-1", "--format=%s") == f"pin (tool-patch {tp2})" and not [m for m in IC() if "has no pin" in m])
        rl8 = "\n".join(record_lines(cfg))
        say("withdraw: an unsealed review blocks the next review; the TP is withdrawn (recorded) and cannot be applied; "
            "a new TP on the same stop shows the never-sealed review; M8: three rejections then an approval, each "
            "attempt reviewed by a fresh reviewer, no stop opened, every attempt in the record",
            "not sealed" in stuck and "never reissued" in reiss and "withdrawn" in wd and tp_state(rd, tp_) == "withdrawn"
            and "issued, never sealed" in bm8 and "finding 3" in bm8 and h8 and stops.open_name(cfg) == s1
            and all(f"#### {tp2} attempt {n}" in rl8 for n in range(1, 5)) and "withdrawn: the reviewer never returned" in rl8)
        # ---- safety review 2026-10-25 (HIGH 2): reviewer shopping through an unsealed reject. The reviewer rejects,
        # its verdict is never sealed and is deleted, the TP withdrawn; the identical diff in a new TP is refused at
        # prepare, and, its FACTS committed by hand past prepare, at apply; a revision that answers the never-sealed
        # review applies
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tpx, _m = begin(cfg, s1); write_attempt(tpx, 1, [FIX]); prepare(cfg, tpx)
        _p, ln = review(cfg, tpx)
        os.remove(reviewer(ln, "reject", "reviewer-x", findings=["the patch is wrong"], seal=False))   # never sealed, deleted
        withdraw(cfg, tpx, "the reviewer never returned")
        tpy, _m = begin(cfg, s1); py = write_attempt(tpy, 1, [FIX])
        shop1 = refused(prepare, cfg, tpy)
        ady = os.path.join(tp_dir(rd, tpy), "A1")
        fy, _r = compute_facts(cfg, tpy, 1, open(os.path.join(ady, "DIAGNOSIS.md")).read(), py)
        json.dump(fy, open(os.path.join(ady, "FACTS.json"), "w"), indent=1, sort_keys=True)
        commit_paths(d, [os.path.join(ady, x) for x in ("DIAGNOSIS.md", "patch.diff", "FACTS.json")],
                     f"tool-patch {tpy} diagnosis 1")
        _p, ln = review(cfg, tpy); reviewer(ln, "approve", "reviewer-y")
        shop2 = refused(apply, cfg, tpy)
        withdraw(cfg, tpy, "resubmitted the never-sealed diff")
        tpz, _m = begin(cfg, s1)
        write_attempt(tpz, 1, [FIX, ("tp_sample.py", "        emb = any(", "        emb = 1 and any(")],
                      answers=[f"{tpx} review-1-1.json"])
        prepare(cfg, tpz)
        _p, ln = review(cfg, tpz); reviewer(ln, "approve", "reviewer-z")
        hz = apply(cfg, tpz)
        icz = IC()
        say("safety review HIGH 2: a review issued and never sealed (its verdict deleted, the TP withdrawn) counts as a "
            "rejection of its diff: the identical diff in a new TP is refused at prepare and, prepared by hand, at "
            "apply; a revision naming and answering that review applies, and integrity --check passes",
            "never sealed" in shop1 and "rejected before" in shop2 and f"{tpx} review-1-1.json (never sealed)" in shop2
            and hz and not icz)
        # ---- re-check 2026-10-25 (gap 1): rejections and the reviewer's history are RUN-wide. A diff rejected
        # (sealed) on S1, its TP withdrawn and S1 closed, is refused unchanged on a LATER stop at prepare and, its
        # FACTS committed by hand, at apply; a revision there must answer the S1 rejection, and its reviewer sees it
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tpr, _m = begin(cfg, s1); write_attempt(tpr, 1, [FIX]); prepare(cfg, tpr)
        _p, ln = review(cfg, tpr); reviewer(ln, "reject", "reviewer-r1", findings=["FR: hides inline binders with a no row"])
        withdraw(cfg, tpr, "the reviewer rejected it")
        stops.close_stop(cfg, s1, human="restored the record")
        outs["make_report"] = (1, "FAIL[report] Lemma 2.5: unclassified assumption `P.lem2:h`\n")
        s3, _m = stops.open_stop(cfg, note="another make_report refusal", cause="tool-bug",
                                 check="python3 audits/make_report.py --check")
        tps_, _m = begin(cfg, s3); ps = write_attempt(tps_, 1, [FIX])
        x_prep = refused(prepare, cfg, tps_)
        ads = os.path.join(tp_dir(rd, tps_), "A1")
        if x_prep:                  # refused, as it must be: commit its FACTS by hand past prepare
            fs, _r = compute_facts(cfg, tps_, 1, open(os.path.join(ads, "DIAGNOSIS.md")).read(), ps)
            json.dump(fs, open(os.path.join(ads, "FACTS.json"), "w"), indent=1, sort_keys=True)
            commit_paths(d, [os.path.join(ads, x) for x in ("DIAGNOSIS.md", "patch.diff", "FACTS.json")],
                         f"tool-patch {tps_} diagnosis 1")
        else:
            print(f"  (gap 1: prepare ACCEPTED on {s3} the diff rejected on {s1})")
        _p, ln = review(cfg, tps_); reviewer(ln, "approve", "reviewer-r2")
        x_apply = refused(apply, cfg, tps_)
        if not x_apply:
            raise Refused(f"gap 1: apply APPLIED on {s3} the diff rejected on {s1}")
        withdraw(cfg, tps_, "resubmitted a diff rejected on another stop")
        tpt, _m = begin(cfg, s3)
        write_attempt(tpt, 1, [FIX, ("tp_sample.py", BUG[0], BUG[0] + "  # revision: routed by its row")])
        x_unans = refused(prepare, cfg, tpt)
        write_attempt(tpt, 1, [FIX, ("tp_sample.py", BUG[0], BUG[0] + "  # revision: routed by its row")],
                      answers=[f"{tpr} review-1-1.json", f"{tps_} review-1-1.json"])
        prepare(cfg, tpt)
        ppt, ln = review(cfg, tpt)
        bt = open(ppt).read()
        reviewer(ln, "approve", "reviewer-r3")
        ht = apply(cfg, tpt)
        ict = IC()
        outs["make_report"] = (0, "report: OK\n")
        say("re-check gap 1: a diff rejected (sealed) on S1 is refused unchanged on a later stop, at prepare and, "
            "prepared by hand, at apply; a revision on the later stop must answer the S1 rejection, and its reviewer's "
            "history lists the S1 attempt with its sealed findings (not \"(none)\"); it applies and integrity passes",
            "rejected before" in x_prep and f"{tpr} review-1-1.json (reject)" in x_apply
            and f"does not answer {tpr} review-1-1.json" in x_unans
            and "FR: hides inline binders with a no row" in bt and f"--- {tpr} attempt 1, stop {s1}" in bt
            and "(none)" not in bt.split("EARLIER ATTEMPTS")[-1] and ht and not ict)
        # ---- re-check 2026-10-25 (gap 3): a whitespace-only variant of a rejected diff (a blank line added to the
        # regression test, trailing blanks on the fixed line, more context lines so other line numbers) has another
        # sha256 but is the same diff: refused at prepare and, prepared by hand, at apply
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tpw, _m = begin(cfg, s1); pw0 = write_attempt(tpw, 1, [FIX]); prepare(cfg, tpw)
        _p, ln = review(cfg, tpw); reviewer(ln, "reject", "reviewer-ws1", findings=["the patch hides a defect"])
        withdraw(cfg, tpw, "the reviewer rejected it")
        tpv, _m = begin(cfg, s1)
        pv = write_attempt(tpv, 1, [("tp_sample.py", BUG[1], BUG[0] + "   ")], reg=REGRESSION_TEST + "\n\n", ctx=6,
                           answers=[f"{tpw} review-1-1.json"])
        w_prep = refused(prepare, cfg, tpv)
        adv = os.path.join(tp_dir(rd, tpv), "A1")
        if w_prep:
            fv, _r = compute_facts(cfg, tpv, 1, open(os.path.join(adv, "DIAGNOSIS.md")).read(), pv)
            json.dump(fv, open(os.path.join(adv, "FACTS.json"), "w"), indent=1, sort_keys=True)
            commit_paths(d, [os.path.join(adv, x) for x in ("DIAGNOSIS.md", "patch.diff", "FACTS.json")],
                         f"tool-patch {tpv} diagnosis 1")
        else:
            print("  (gap 3: prepare ACCEPTED a whitespace-only variant of the rejected diff)")
        _p, ln = review(cfg, tpv); reviewer(ln, "approve", "reviewer-ws2")
        w_apply = refused(apply, cfg, tpv)
        if not w_apply:
            raise Refused("gap 3: apply APPLIED a whitespace-only variant of the rejected diff")
        lean_rm = "diff --git a/x_tail.lean b/x_tail.lean\n--- a/x_tail.lean\n+++ b/x_tail.lean\n@@ -1,2 +1,1 @@\n a\n--- c\n"
        say("re-check gap 3: a whitespace-only variant of a rejected diff (another sha256: a blank line, trailing blanks, "
            "more context and so other hunk line numbers) is the same diff: refused at prepare and, prepared by hand, "
            "at apply; diff_key ignores whitespace and line numbers but not a real change (a removed Lean comment line "
            "`-- c` is a change, not a header)",
            pv != pw0 and sha_bytes(pv.encode()) != sha_bytes(pw0.encode()) and diff_key(pv) == diff_key(pw0)
            and "rejected before" in w_prep and f"{tpw} review-1-1.json (reject)" in w_apply
            and diff_key(lean_rm) != diff_key(lean_rm.replace("--- c\n", " c\n"))
            and diff_key(pw0) != diff_key(pw0.replace(BUG[0][8:], BUG[0][8:].replace("unclassified", "unclassifie"))))
        # ---- re-check 3 (2026-10-25), A: a tool patch only MODIFIES files of the first pin's apparatus. A new
        # audits/re.py (it shadowed the stdlib `re` and blinded phase0's sorry scan, one approval) is refused at prepare
        # and, prepared by hand and approved, at apply; applied by hand, integrity --check fails it (the link, the file
        # the first pin lacks, the shadowing module). A regression test named after a stdlib module is refused; a stray
        # package audits/re/ is FAIL[tooling] in any check; a plain directory with a stdlib name (a rounds dir) is not
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        RUNNER = stand_in()
        SHADOW = ("import importlib.machinery as _m, importlib.util as _u, os as _o, sys as _s\n"
                  "_spec = _m.PathFinder.find_spec('re', [p for p in _s.path if _o.path.abspath(p or '.') != "
                  "_o.path.dirname(_o.path.abspath(__file__))])\n_real = _u.module_from_spec(_spec); _s.modules['re'] = _real\n"
                  "_spec.loader.exec_module(_real)\n")
        tpn, _m = begin(cfg, s1)
        pn = write_attempt(tpn, 1, [FIX], newfiles={"re.py": SHADOW})
        n_prep = refused(prepare, cfg, tpn)
        adn = os.path.join(tp_dir(rd, tpn), "A1")
        if n_prep:
            fn_, _r = compute_facts(cfg, tpn, 1, open(os.path.join(adn, "DIAGNOSIS.md")).read(), pn)
            json.dump(fn_, open(os.path.join(adn, "FACTS.json"), "w"), indent=1, sort_keys=True)
            commit_paths(d, [os.path.join(adn, x) for x in ("DIAGNOSIS.md", "patch.diff", "FACTS.json")],
                         f"tool-patch {tpn} diagnosis 1")
        else:
            print("  (re-check 3 A: prepare ACCEPTED a new audits/re.py)")
        _p, ln = review(cfg, tpn); reviewer(ln, "approve", "reviewer-new1")
        n_apply = refused(apply, cfg, tpn)
        if not n_apply:
            raise Refused("re-check 3 A: apply APPLIED a new audits/re.py")
        open(os.path.join(d, "x.diff"), "w").write(pn)
        G("apply", "--index", "x.diff"); os.remove(os.path.join(d, "x.diff"))
        G("commit", "-qm", f"tool-patch {tpn} apply")
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin=f"tool-patch {tpn}",
                      tool_patch={"tool_patch": tpn, "attempt": 1, "patch_sha256": sha_bytes(pn.encode()),
                                  "review_seals": [], "stop": s1})
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", f"pin (tool-patch {tpn})")
        icn = IC()
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tpq, _m = begin(cfg, s1)
        write_attempt(tpq, 1, [FIX], regname="re")
        q_prep = refused(prepare, cfg, tpq)
        withdraw(cfg, tpq, "renamed")
        os.makedirs(os.path.join(d, "re")); open(os.path.join(d, "re", "__init__.py"), "w").write("")
        os.makedirs(os.path.join(d, "random")); open(os.path.join(d, "random", "notes.md"), "w").write("x\n")
        ics = IC()
        say("re-check 3 (A): a NEW audits/re.py (a stdlib shadow) is refused at prepare and, prepared by hand and "
            "approved, at apply; applied by hand, integrity --check fails the link, the file the first pin lacks and the "
            "shadowing module; a regression test named re.py is refused; a stray package audits/re/ is FAIL[tooling], "
            "a plain directory audits/random/ is not",
            "re.py shadows the Python standard-library module" in n_prep and "re.py shadows the Python" in n_apply
            and any(x.startswith(f"[tool-patch] {tpn}:") and "re.py shadows the Python" in x for x in icn)
            and any(x.startswith("[tooling] re.py is not a file of the first pin's apparatus") for x in icn)
            and any(x.startswith("[tooling] audits/re.py shadows") for x in icn)
            and "tests/regressions/re.py shadows the Python standard-library module `re`" in q_prep
            and any(x.startswith("[tooling] audits/re shadows") for x in ics)
            and not any("random" in x for x in ics)
            and patch_files("diff --git a/x.py b/x.py\nnew file mode 100755\n") == [("x.py", "new")])
        shutil.rmtree(os.path.join(d, "re")); shutil.rmtree(os.path.join(d, "random"))
        # C2-FIX review (snapshot replay): a run pinned before tool patches existed (ownership < 4) is not judged by the
        # manifest rule, as release_repin_problems does not judge it; a release run pinned under 4 still is
        keep_m = (globals()["first_pin"], globals()["pin_doc"], globals()["tooling_tree"])
        try:
            globals()["pin_doc"] = lambda rd_: {"audits_commit": "b" * 40}
            globals()["tooling_tree"] = lambda a_, c_: {"x.py"} if c_ == "a" * 40 else {"x.py", "newer.py"}
            globals()["first_pin"] = lambda rd_: {"audits_commit": "a" * 40, "ownership": 2, "config": {"mode": "release"}}
            m_old = [x for _s, x in manifest_problems(d, rd) if "newer.py" in x]
            globals()["first_pin"] = lambda rd_: {"audits_commit": "a" * 40, "ownership": 4, "config": {"mode": "release"}}
            m_new = [(s_, x) for s_, x in manifest_problems(d, rd) if "newer.py" in x]
        finally:
            globals()["first_pin"], globals()["pin_doc"], globals()["tooling_tree"] = keep_m
        say("C2-FIX review: the manifest rule (a tooling file the first pin lacks) judges runs pinned under ownership 4 "
            "or later (FAIL in release), not an older run (its re-pins follow the rules of its time)",
            m_old == [] and len(m_new) == 1 and m_new[0][0] == "FAIL")
        # ---- re-check 3 (2026-10-25), B: the PROOF-VALIDITY CORE is immutable. axiom_sweep_tail.lean edited to accept
        # extra axioms in the project namespace (no floor canary, the sweep's selftest is Lean-tier, the blast radius
        # does not run the sweep: one approval sufficed) is refused at prepare and, prepared by hand with TWO approvals,
        # at apply; applied by hand, integrity --check fails its link. The core is the FIRST pin's: a CORE emptied in
        # the running code still refuses it. Every core file is refused
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        RUNNER = stand_in()
        AX = ("axiom_sweep_tail.lean", "      let extra := ax.filter (fun a => !(ok.contains a) && a != ``sorryAx)",
              "      let extra := ax.filter (fun a => !(ok.contains a) && a != ``sorryAx && !(nsp.isPrefixOf a))")
        tpc, _m = begin(cfg, s1)
        pc = write_attempt(tpc, 1, [FIX, AX])
        c_prep = refused(prepare, cfg, tpc)
        if c_prep:
            hand_facts(tpc, 1, pc)
        else:
            print("  (re-check 3 B: prepare ACCEPTED an edit of axiom_sweep_tail.lean)")
        _p, ln = review(cfg, tpc); reviewer(ln, "approve", "reviewer-core1")
        _p, ln = review(cfg, tpc); reviewer(ln, "approve", "reviewer-core2")
        c_apply = refused(apply, cfg, tpc)
        if not c_apply:
            raise Refused("re-check 3 B: apply APPLIED an edit of axiom_sweep_tail.lean with two approvals")
        keep_core = CORE
        globals()["CORE"] = ()
        try:
            c_first = structure_problems(d, rd, [("axiom_sweep_tail.lean", "modified")], None)
        finally:
            globals()["CORE"] = keep_core
        c_all = all(structure_problems(d, rd, [(p_, "modified")], None) for p_ in CORE)
        c_other = structure_problems(d, rd, [("result_status.py", "modified"), ("lane_auth.py", "modified")], None)
        hand_apply(tpc, 1, pc)
        icc = IC()
        say("re-check 3 (B): an edit of axiom_sweep_tail.lean (the proof-validity core) is refused at prepare and, "
            "prepared by hand with two approvals, at apply; applied by hand, integrity --check fails its link; the core "
            "is read from the first pin (an emptied CORE in the running code still refuses it); every core file is "
            "refused, a file outside the core is not",
            "axiom_sweep_tail.lean is in the proof-validity core" in c_prep
            and "axiom_sweep_tail.lean is in the proof-validity core" in c_apply
            and any(x.startswith(f"[tool-patch] {tpc}:") and "axiom_sweep_tail.lean is in the proof-validity core" in x
                    for x in icc)
            and c_first and "proof-validity core" in c_first[0] and c_all and not c_other
            and set(CORE) >= {"phase0.py", "axiom_sweep.py", "axiom_sweep_tail.lean", "fingerprint.py",
                              "fingerprint_tail.lean", "tool_patch.py", "integrity.py"})
        # ---- M9: a regression test that passes on the old tool is refused (fact (a)); M10 (the revert)
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        tp_, _m = begin(cfg, s1)
        write_attempt(tp_, 1, [FIX], reg=REGRESSION_TEST.replace("sys.exit(1 if bad else 0)", "sys.exit(0)"))
        m9 = refused(prepare, cfg, tp_)
        write_attempt(tp_, 1, [FIX], reg=None)
        m9b = refused(prepare, cfg, tp_)

        def scope_refusal(path, kind="modified"):
            txt = (f"diff --git a/{path} b/{path}\n" + ("new file mode 100644\n" if kind == "new" else "")
                   + f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n")
            return " | ".join(compute_facts(cfg, tp_, 1, DIAGNOSIS_TEXT, txt)[1])
        OUT_ = "outside what a tool patch may touch"
        bad_ = {p_: scope_refusal(p_) for p_ in ("../P/Main.lean", "P/APPROVED_FINGERPRINTS.json", "P/R0/SIGNOFF.md",
                                                  "P/R0/correspondence.json", "agents/SIGNOFF.md", "REAPPROVAL.md",
                                                  ".gitattributes")}
        core_ = {p_: scope_refusal(p_) for p_ in CORE}
        ok_ = {p_: scope_refusal(p_) for p_ in ("AUDIT_PROTOCOL.md", "RUN.md", "run/stage4-rounds.md",
                                                 "agents/auditor.md", "result_status.py")}
        new_ok, new_bad = scope_refusal("run/helper_note.md", "new"), scope_refusal("json.py", "new")
        say("OPERATOR-AUTHORITY (approver 2026-10-26): a patch touching the project's Lean, a round record, a signed "
            "document or the git rules is refused, as is every proof-validity core file; the protocol text (RUN.md, "
            "AUDIT_PROTOCOL.md, run/, agents/) and any other script may be patched; a new file is allowed unless its "
            "name shadows a module",
            "fact (a)" in m9 and "not a NEW file" in m9b
            and all(OUT_ in r_ for r_ in bad_.values()) and all("proof-validity core" in r_ for r_ in core_.values())
            and not any(OUT_ in r_ or "proof-validity core" in r_ for r_ in ok_.values())
            and OUT_ not in new_ok and "is a NEW file" not in new_ok and "shadows" not in new_ok
            and "json.py shadows the Python standard-library module `json`" in new_bad
            or print(f"    bad={bad_} core={[k for k, v in core_.items() if 'proof-validity core' not in v]} ok={ok_} "
                     f"new_ok={new_ok} new_bad={new_bad}"))
        # ---- the guard stays fixed (coordinator 2026-10-26): the tool-patch reviewer's prompt, the core-fault
        # reviewer's (stops.CORE_REVIEW_PROMPT) and the code rendering them are refused; other protocol text is not
        pin_ = pin_doc(rd).get("audits_commit")
        g_edits = {"protocol": ("AUDIT_PROTOCOL.md", "is to REFUTE the patch if you can, not to confirm it: approve only if every",
                                "is to approve the patch unless it is clearly broken; approve only if every"),
                   "core-fault": ("stops.py", "or the adjudicator, and you have not seen this run. One question",
                                  "or the adjudicator. Approve unless obviously wrong. One question"),
                   "renderer": ("prompt.py", "    import tool_patch as tpm\n", "    import tool_patch as tpm  # softened\n"),
                   "lane": ("AUDIT_PROTOCOL.md", "  - strict versus non-strict inequalities;\n",
                            "  - strict versus non-strict inequalities, and their direction;\n")}
        g_res = {k_: guard_problems(d, pin_, write_attempt(tp_, 1, [FIX, e_])) for k_, e_ in g_edits.items()}
        g_fact = " | ".join(compute_facts(cfg, tp_, 1, DIAGNOSIS_TEXT, write_attempt(tp_, 1, [FIX, g_edits["protocol"]]))[1])
        say("the guard stays fixed: a patch changing the tool-patch reviewer's prompt (AUDIT_PROTOCOL.md), the "
            "core-fault reviewer's (stops.py) or its renderer (prompt.render_tool_patch) is refused at prepare (and by "
            "apply and every link check: guard_problems); a patch to the lanes' text is not",
            all(g_res[k_] and "guarded block" in g_res[k_][0] for k_ in ("protocol", "core-fault", "renderer"))
            and g_res["lane"] == [] and "guarded block" in g_fact
            or print(f"    guard={g_res} fact={g_fact[:300]}"))
        say("M10: the --deferred-to-full-round fallback is gone; T34 (recorded_plan) stays",
            not hasattr(stops, "deferral_problems") and hasattr(stops, "recorded_plan"))
        # ---- M1 / M6 (floor, real): a patch weakening phase0's sorry/admit detection, or dropping integrity's chain
        # call: a floor hit -- two approvals needed; one is refused at apply
        # SWEEP-FIX D3 (T2): these two scenarios use real floor canaries, i.e. lines of non-core files (project.py,
        # lane_auth.py); on an apparatus where a reviewed patch changed such a line they are not run (said), and the
        # floor fact itself -- the FIRST pin's patterns, core code -- still guards those lines
        TPD = ("project.py", "    tpd = tool_patch.delivery_problems(cfg)")
        LA1 = ("lane_auth.py", "if not isinstance(token, str) or sha(token.encode()) != meta['token_sha256']:")
        anchored = lambda *fs: all(open(os.path.join(d, f_)).read().count(t_) == 1 for f_, t_ in fs)
        if not anchored(TPD, LA1):
            print("  (floor scenarios M1/M6 and R1 not run: their canary lines are not in this apparatus)")
        else:
            G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
            RUNNER = stand_in(floor_real=True)
            tp_, _m = begin(cfg, s1)
            write_attempt(tp_, 1, [FIX, ("project.py", "    tpd = tool_patch.delivery_problems(cfg)", "    tpd = []"),
                                   ("lane_auth.py", "if not isinstance(token, str) or sha(token.encode()) != meta['token_sha256']:",
                                    "if False:")])
            fm = prepare(cfg, tp_)
            _p, ln = review(cfg, tp_); reviewer(ln, "approve", "reviewer-f1")
            one = refused(apply, cfg, tp_)
            _p, ln = review(cfg, tp_); reviewer(ln, "approve", "reviewer-f2")
            two = apply(cfg, tp_)
            hits = {h_["id"] for h_ in fm["floor"]["hits"]}
            say("M1/M6 (real floor run): dropping --deliver's first-pin verifier call and lane_auth's token check (outside "
                "the proof-validity core) are floor hits (TPC2, LA1), never refused before review; one approval is refused "
                "at apply, two independent approvals apply it (review §4b: no dead end, the reviewer is told)",
                {"TPC2", "LA1"} <= hits and fm["required_approvals"] == 2 and "needs 2" in one and two)
            G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
            RUNNER = lambda kind, *a: ({"ids": [], "hits": []} if kind == "floor" else stand_in()(kind, *a))
            tp_, _m = begin(cfg, s1)
            write_attempt(tp_, 1, [FIX, ("project.py", "    tpd = tool_patch.delivery_problems(cfg)", "    tpd = []")])
            fl_ = prepare(cfg, tp_)
            _p, ln = review(cfg, tp_); reviewer(ln, "approve", "reviewer-f3")
            lie = refused(apply, cfg, tp_)
            say("R1: FACTS that claim no floor hit do not lower the bar: apply recomputes the floor's pattern half (TPC2 "
                "gone) and still needs two approvals", fl_["required_approvals"] == 1 and "needs 2" in lie and "TPC2" in lie)
        # ---- safety review 2026-10-25 (HIGH 1): TPa weakens approval_problems (`if approvals and len(...) < need`);
        # it is a floor hit (TP22) and needs two approvals. TPb is then applied with NO review: its link's pinned-before
        # verifier is TPa's weakened one, so only the first pin's re-check sees it, and integrity --check runs it
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        RUNNER = stand_in()
        WEAK = ("tool_patch.py", "    if len(approvals) " + "< need:", "    if approvals and len(approvals) " + "< need:")
        tpa, _m = begin(cfg, s1); pwa = write_attempt(tpa, 1, [FIX, WEAK]); w_prep = refused(prepare, cfg, tpa)
        hand_facts(tpa, 1, pwa)
        _p, ln = review(cfg, tpa); reviewer(ln, "approve", "reviewer-w1")
        _p, ln = review(cfg, tpa); reviewer(ln, "approve", "reviewer-w2")
        w_two = refused(apply, cfg, tpa)
        hand_apply(tpa, 1, pwa)        # (re-check 3: tool_patch.py is core; the operator applies it by hand anyway)
        _st = stand_in()
        RUNNER = lambda kind, *a: ({"test": a[2], "pinned": {"exit": 1, "tail": []}, "patched": {"exit": 0, "tail": []},
                                    "passes": True} if kind == "regression" else _st(kind, *a))
        tpb, _m = begin(cfg, s1)
        write_attempt(tpb, 1, [("tp_sample.py", "        emb = any(", "        emb = any( ")], regname="tp_second")
        prepare(cfg, tpb)
        patch = open(os.path.join(tp_dir(rd, tpb), "A1", "patch.diff")).read()
        open(os.path.join(d, "x.diff"), "w").write(patch)
        G("apply", "--index", "x.diff"); os.remove(os.path.join(d, "x.diff"))
        G("commit", "-qm", f"tool-patch {tpb} apply")
        integrity.pin(d, cfg, agent_file=agent, rounds_dir=rd, repin=f"tool-patch {tpb}",
                      tool_patch={"tool_patch": tpb, "attempt": 1, "patch_sha256": sha_bytes(patch.encode()),
                                  "review_seals": [], "stop": s1})
        G("add", "--", "P/TOOLING_PIN.json"); G("commit", "-qm", f"pin (tool-patch {tpb})")
        RUNNER = stand_in()
        icw = IC()
        rlw = record_lines(cfg)
        say("safety review HIGH 1 (re-check 3: tool_patch.py is in the proof-validity core): a patch weakening "
            "approval_problems is refused at prepare and, with two approvals, at apply; applied by hand, integrity fails "
            "its link; the next patch applied with no review passes its pinned-before (weakened) verifier, but integrity "
            "--check runs the first pin's re-check and fails it, and RUN_RECORD.md lists each link's result",
            "tool_patch.py is in the proof-validity core" in w_prep and "tool_patch.py is in the proof-validity core" in w_two
            and any(x.startswith(f"[tool-patch] {tpb}: the first pin's apparatus does not verify") and "0 approval(s)" in x
                    for x in icw)
            and any(x.startswith(f"[tool-patch] {tpa}:") and "proof-validity core" in x for x in icw)
            and any(l.startswith(f"- {tpa}: NOT VERIFIED") for l in rlw) and any(l.startswith(f"- {tpb}: NOT VERIFIED") for l in rlw))
        # ---- re-check 2026-10-25 (gap 2): TP-a moves lane_auth out of project.py's pure tier (approved, applied);
        # TP-b then disables lane_auth's prompt check (LA8's line kept verbatim, so its pattern is still found once).
        # Fact (b) runs the FIRST pin's selftests, lane_auth's among them: it fails on TP-b, which is refused before
        # review; and the floor counts LA8 a hit (lane_auth's selftest fails unmutated), never a kill
        # (run when lane_auth is a pure selftest of THIS apparatus: on TP-a's own patched tree, whose selftest fact (b)
        # runs, the premise is gone; the guard is then fact (b) itself, which lists the first pin's selftests)
        la_tier = re.search(r'"lane_auth": \("([a-z+]+)", True\)', open(os.path.join(d, "project.py")).read())
        la8_ = "        if sha(Path(meta['prompt']).read_bytes()) != meta['prompt_sha256']:"
        if not (la_tier and "pure" in la_tier.group(1).split("+")) or not anchored(("lane_auth.py", la8_)):
            print("  (gap 2 scenario not run: lane_auth is not a pure selftest of this apparatus, or its LA8 line changed)")
        else:
            G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
            RUNNER = stand_in()
            tpa2, _m = begin(cfg, s1)
            write_attempt(tpa2, 1, [FIX, ("project.py", la_tier.group(0), '"lane_auth": ("lean", True)')])
            prepare(cfg, tpa2)
            _p, ln = review(cfg, tpa2); reviewer(ln, "approve", "reviewer-g2a"); apply(cfg, tpa2)
            seen, _st2 = [], stand_in()

            def g2(kind, *a):
                if kind == "selftests":     # run, for real, lane_auth's selftest if fact (b)'s list has it (only it: fast)
                    names_ = list(a[1]) if len(a) > 1 else pure_selftests(a[0])
                    seen.append(names_)
                    failed_ = [x for x in names_ if x == "lane_auth.py" and run_selftest(a[0], x)[0] != 0]
                    return {"run": names_, "failed": failed_, "passes": not failed_}
                return _st2(kind, *a)
            RUNNER = g2
            la8 = "        if sha(Path(meta['prompt']).read_bytes()) != meta['prompt_sha256']:"
            reanchor = ("lane_auth.py", la8, "        meta = dict(meta, prompt_sha256=sha(Path(meta['prompt']).read_bytes()))"
                        "  # re-anchor a moved prompt\n" + la8)
            reg_b = ("#!/usr/bin/env python3\nimport argparse, inspect, sys\nsys.dont_write_bytecode = True\n"
                     "ap = argparse.ArgumentParser(); ap.add_argument('--apparatus', required=True); a = ap.parse_args()\n"
                     "sys.path.insert(0, a.apparatus)\nimport lane_auth\n"
                     "sys.exit(0 if 're-anchor' in inspect.getsource(lane_auth.validate) else 1)\n")
            tpb2, _m = begin(cfg, s1)
            pb2 = write_attempt(tpb2, 1, [reanchor], reg=reg_b, regname="tp_reanchor")
            g2_prep = refused(prepare, cfg, tpb2)
            RUNNER = None
            keep_fm = floor_mutants
            globals()["floor_mutants"] = lambda a_, r_: [m for m in keep_fm(a_, r_) if m[0].split()[0] == "LA8"]
            root_, qd_ = scratch_tree(d, pin_doc(rd).get("audits_commit"), pb2)
            try:
                fl2 = floor(d, rd, qd_)
            finally:
                globals()["floor_mutants"] = keep_fm
                shutil.rmtree(root_, ignore_errors=True)
            RUNNER = stand_in()
            print(f"  (gap 2: fact (b) ran {[x for x in (seen or [[]])[-1] if x == 'lane_auth.py'] or 'no lane_auth.py'}; "
                  f"prepare: {' '.join(g2_prep.split())[:120] or 'ACCEPTED'}; floor LA8: {fl2['hits'] or 'killed'})")
            say("re-check gap 2: after TP-a (approved) moved lane_auth out of project.py's pure tier, TP-b, which disables "
                "lane_auth's prompt check, still has lane_auth's selftest run (the FIRST pin's list) and is refused before "
                "review (fact (b)); the floor counts LA8 a hit because lane_auth's selftest fails unmutated (never a kill)",
                "fact (b)" in g2_prep and "lane_auth.py" in g2_prep and seen and "lane_auth.py" in seen[-1]
                and [h_["id"] for h_ in fl2["hits"]] == ["LA8"] and fl2["hits"][0]["why"].startswith("baseline"))
        # ---- SWEEP-FIX D3 (RELEASE-SWEEP T3): TP-r1 (reviewed, applied) changes the reviewer-prompt renderer
        # (prompt.render_tool_patch); TP-r2's review is then issued with the renderer in force (TP-r1's). The first
        # pin's re-check of TP-r2's link compares its prompt with what the apparatus pinned at its issue renders, not
        # with the first pin's renderer: TP-r2 verifies (before the fix: "not what the apparatus in force renders")
        RND = ("prompt.py", '    out = common + "\\n\\n" + body', '    out = common + "\\n\\n" + body + "\\n\\nRENDERER NOTE (TP-r1)."')
        if not anchored(RND[:2]):
            print("  (T3 renderer scenario not run: its anchor line is not in this apparatus's prompt.py)")
        else:
            # coordinator 2026-10-26: the renderer is GUARDED now -- such a patch is refused before review (the
            # link-verification by the pin at issue, rendered_at_issue, stays for a run pinned before the guard)
            G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
            RUNNER = stand_in()
            tpr1, _m = begin(cfg, s1)
            write_attempt(tpr1, 1, [FIX, RND], regname="tp_render1")
            r_t3 = refused(prepare, cfg, tpr1)
            say("SWEEP-FIX D3 (T3), superseded by the guard: a patch to the reviewer-prompt renderer "
                "(prompt.render_tool_patch) is refused at prepare", "guarded block" in r_t3 and "render_tool_patch" in r_t3)
        # TP12: a reviewer prompt that is not the rendering (softened by hand, its hash and token consistent)
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        RUNNER = stand_in()
        tp_, _m = begin(cfg, s1); write_attempt(tp_, 1, [FIX]); prepare(cfg, tp_)
        pp_ = os.path.join(tp_dir(rd, tp_), "prompts", "review-1-1.txt")
        cp_ = os.path.join(tp_dir(rd, tp_), ".lane-auth", "review-1-1.json")
        os.makedirs(os.path.dirname(pp_)); os.makedirs(os.path.dirname(cp_))
        soft = (render_prompt(cfg, tp_, 1, 1).replace("REFUTE the patch if you can", "approve the patch"))
        open(pp_, "w").write(soft)
        tok_ = "ab" * 32
        json.dump({"verdict": "review-1-1.json", "token_sha256": lane_auth.sha(tok_.encode()), "prompt": pp_,
                   "prompt_sha256": lane_auth.sha(open(pp_, "rb").read())}, open(cp_, "w"), sort_keys=True, indent=2)
        commit_paths(d, [pp_, cp_], f"tool-patch {tp_} token review-1-1.json")
        reviewer(lane_auth.spawn_line(pp_, tok_), "approve", "reviewer-soft")
        softr = refused(apply, cfg, tp_)
        say("R3: a reviewer prompt that is not what the apparatus in force renders (softened by hand, hash and token "
            "consistent) does not count", "not what the apparatus in force renders" in softr)
        RUNNER = stand_in()
        # ---- forced round (affects-review-inputs yes, or a PASS->FAIL in the blast radius): scope.py runs it,
        # --deliver refuses until it has run
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        RUNNER = stand_in(p2f=["lanecheck.py --round R"])
        tp_, _m = begin(cfg, s1); write_attempt(tp_, 1, [FIX]); ff = prepare(cfg, tp_)
        _p, ln = review(cfg, tp_); reviewer(ln, "approve", "reviewer-fr"); apply(cfg, tp_)
        fr = forced_round_problems(cfg)
        dp = delivery_problems(cfg)
        say("R8: a PASS->FAIL in the blast radius forces affects-review-inputs yes (the diagnosis said no); until a full "
            "round scoped after the apply commit is adjudicated, scope.py never skips it and --deliver refuses",
            ff["affects_review_inputs"] == "yes" and ff["affects_forced"] and fr and any("full round" in x for x in dp))
        # ---- OPERATOR-AUTHORITY (approver 2026-10-26), end to end: a round's lane prompts are issued, a reviewed patch
        # edits AUDIT_PROTOCOL.md's lane text (protocol text, mid-run), more lane prompts are issued with the patched
        # text, both rounds are adjudicated and the delivery checks run: no new failure anywhere. The prompts issued
        # before the patch are verified against what was issued (their committed hashes), the later ones against the
        # patched text; the tool-patch link verifies with the pinned-before and the first pin's apparatus
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        RUNNER = stand_in()
        import prompt as _pr
        lcfg = dict(json.load(open(os.path.join(d, "project_template.json"))), **cfg)
        lcfg.update(title="t", source_pdf="paper.tex", source_id="x:1", source_cite="c", branch="b", base_commit="0",
                    lean_files=["Main.lean"], lanes=["correspondence"], work_dir=".w", blind_spots="none",
                    goal_results=["Theorem 1"])
        HDR_ = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"

        def issue_round(rnd, protocol):
            """Scope a round to the correspondence lane, issue its prompt (prompt.py --lanes --write's path),
            return its lane, write and seal a verdict, adjudicate it. Returns the prompt's text."""
            r_ = os.path.join(rd, rnd)
            os.makedirs(os.path.join(r_, "prompts"))
            json.dump({"correspondence": ["P.a"]}, open(os.path.join(r_, "TARGET.json"), "w"))
            commit_paths(d, [os.path.join(r_, "TARGET.json")], f"scope {rnd}")
            text_ = _pr.load(protocol)
            [(_l, body_, _n)] = _pr.render_lanes(text_, lcfg, rnd)
            [(pp_, _x)] = _pr.write_prompts({"correspondence.txt": body_ + "\n"}, os.path.join(r_, "prompts"))
            tok_ = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(pp_)).group(1)
            v_ = os.path.join(r_, "correspondence.json")
            raw_ = json.dumps({"lane_token": tok_, "probes": lane_auth.probe_manifest(v_), "checked": "x",
                               "verdicts": [{"item": "P.a", "verdict": "Pass", "next_step": ""}]}).encode()
            open(v_, "wb").write(raw_)
            lane_auth.seal(v_, sha_bytes(raw_), f"lane-{rnd}")
            open(os.path.join(r_, "ADOPTED.md"), "w").write(HDR_ + "| correspondence | P.a | Pass | ADOPT | ok |\n")
            integrity.commit_adjudication(d, rd, "P", rnd)
            return body_

        def verified(rnd, protocol):
            """[problem] of prompt.py --verify-written and lanecheck's authentication for round `rnd`, with `protocol`
            (the protocol text in force NOW)."""
            r_ = os.path.join(rd, rnd)
            files_ = _pr.lane_prompt_files(_pr.load(protocol), lcfg, rnd, None)
            return (_pr.verify_issued(files_, os.path.join(r_, "prompts"), r_, rnd)
                    + lane_auth.check_round(r_, lanecheck.lane_files(r_)))
        import lanecheck
        RA, RB = "2026-02-01-full-a1b2c3d4e5f", "2026-02-02-full-b2c3d4e5f6a"
        proto_d = os.path.join(d, "AUDIT_PROTOCOL.md")
        before_ = issue_round(RA, proto_d)
        LANE_EDIT = ("AUDIT_PROTOCOL.md", "  - strict versus non-strict inequalities;\n",
                     "  - strict versus non-strict inequalities, and which side each bound is on;\n")
        PREG = ("#!/usr/bin/env python3\nimport argparse, os, sys\nap = argparse.ArgumentParser(); "
                "ap.add_argument('--apparatus', required=True); a = ap.parse_args()\n"
                "t = open(os.path.join(a.apparatus, 'AUDIT_PROTOCOL.md'), encoding='utf-8').read()\n"
                "sys.exit(0 if 'which side each bound is on' in t else 1)\n")
        PDIAG = DIAGNOSIS_TEXT.replace("regression: tests/regressions/tp_inline_binder.py",
                                       "regression: tests/regressions/tp_lane_text.py").replace(
            "## The check\n", "## The check\nThe correspondence lane's instructions in AUDIT_PROTOCOL.md (protocol text). ")
        tpp, _m = begin(cfg, s1)
        pdiff = write_attempt(tpp, 1, [FIX, LANE_EDIT], diag=PDIAG, reg=PREG, regname="tp_lane_text")
        fp_ = prepare(cfg, tpp)
        _p, lnp = review(cfg, tpp); reviewer(lnp, "approve", "reviewer-proto")
        h_pa = apply(cfg, tpp)
        outs["make_report"] = (0, "report: OK\n")
        stops.close_stop(cfg, s1, cured=f"tool-patch {tpp}")
        patched_now = "which side each bound is on" in open(proto_d).read()
        after_ = issue_round(RB, proto_d)
        va, vb = verified(RA, proto_d), verified(RB, proto_d)
        ic_p = IC()
        open(os.path.join(rd, "RUN_RECORD.md"), "w").write("\n".join(record_lines(cfg)) + "\n")
        open(os.path.join(rd, "REPORT.md"), "w").write(
            "# Report\n\n| layer | establishes | status |\n|---|---|---|\n"
            f"| {WEAKENED_TITLE} | the final delivery checks ran on the pinned audit tools | {TOOLS_PATCHED} |\n")
        stat["first"] = stat["cur"] = {"Lemma 1.1": ["faithful"]}
        _RAISED.clear()
        # what --prepare-delivery writes: the fixture has no Lean project, so the first pin's result_status (run by
        # --deliver in a subprocess) cannot compute statuses and the documents carry the "not compared" line
        rl_ = f"\n- {STATUS_UNCOMPARED}\n"
        open(os.path.join(rd, "SUMMARY.md"), "w").write("# Summary\n" + rl_)
        open(os.path.join(rd, "REPORT.md"), "a").write(rl_)
        dp_p = delivery_problems(cfg)
        cr_p = [x for x in chain_report(cfg, rd, d, first=True) if x[1]]
        say("OPERATOR-AUTHORITY scenario: lane prompts issued, then a reviewed patch to AUDIT_PROTOCOL.md's lane text "
            "applied mid-run (one fresh approval), more lane prompts issued with the patched text, both rounds "
            "adjudicated: prompt.py --verify-written and lanecheck pass for the round issued before the patch (checked "
            "against what was issued) and the one after it, integrity --check has no FAIL (the link verified by the "
            "pinned-before and the first pin's apparatus), the delivery checks pass: no new stop",
            fp_["files"] == ["AUDIT_PROTOCOL.md", "tests/regressions/tp_lane_text.py", "tp_sample.py"]
            and bool(h_pa) and patched_now and "which side each bound is on" not in before_
            and "which side each bound is on" in after_ and va == [] and vb == [] and ic_p == [] and dp_p == []
            and cr_p == [] and len(stops.stops(cfg)) == 1 and not stop_open(rd, s1)
            or print(f"    files={fp_.get('files')} va={va} vb={vb} ic={ic_p} dp={dp_p} cr={cr_p}"))
        stat["first"] = stat["cur"] = {}
        _RAISED.clear()
        # ---- M4: dev mode refuses; a tool-patch commit in a dev run fails integrity
        G("reset", "-q", "--hard", h_open); G("clean", "-fdq")
        dev = dict(cfg, mode="dev")
        m4 = refused(begin, dev, s1)
        G("commit", "-q", "--allow-empty", "-m", "tool-patch TP1 begin")
        m4b = [m for sv, m in chain_problems(d, rd) if sv == "FAIL"]
        d2 = os.path.join(base, "dev"); shutil.copytree(d, d2, ignore=shutil.ignore_patterns("__pycache__"))
        d3 = os.path.join(base, "devrun"); r3 = os.path.join(d3, "P"); os.makedirs(r3)
        G3 = lambda *a: subprocess.run(["git", "-C", d3, *a], capture_output=True, text=True).stdout.strip()
        G3("init", "-q"); G3("config", "user.email", "t@t"); G3("config", "user.name", "t")
        json.dump({"config": {"mode": "dev"}, "ownership": 4, "audits_commit": "x"}, open(os.path.join(r3, "TOOLING_PIN.json"), "w"))
        G3("add", "-A"); G3("commit", "-qm", "pin"); G3("commit", "-q", "--allow-empty", "-m", "tool-patch TP1 begin")
        m4c = [m for sv, m in chain_problems(d3, r3) if sv == "FAIL"]
        say("M4: dev mode refuses a tool patch (begin); a run pinned in release judges a tool-patch commit, a dev pin "
            "fails it", "dev mode" in m4 and not m4b and any("dev run never patches" in x for x in m4c))
        G("reset", "-q", "--hard", h_done); G("clean", "-fdq")
        rd_old = json.load(open(os.path.join(rd, "TOOLING_PIN.json")))
        old_ok = first_pin_problem(rd) is None
        probs_ = []
        for i_, pin_ in enumerate(({"config": {"mode": "release"}, "ownership": 3},
                                   {"config": {"mode": "release"}, "ownership": 4,
                                    "codex_agents": {"model": "m", "sha256": {"formalize_auditor.toml": "x"}}},
                                   {"config": {"mode": "release"}, "ownership": 4,
                                    "codex_agents": {"model": "m", "sha256": {f"{REVIEWER_ROLE}.toml": "x"}}})):
            d4 = os.path.join(base, f"old{i_}"); r4 = os.path.join(d4, "P"); os.makedirs(r4)
            subprocess.run(["git", "init", "-q", d4]); json.dump(pin_, open(os.path.join(r4, "TOOLING_PIN.json"), "w"))
            subprocess.run(["git", "-C", d4, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"])
            subprocess.run(["git", "-C", d4, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "pin"])
            probs_.append(first_pin_problem(r4))
        say("a run pinned before ownership 4 cannot patch (refused), nor a Codex run whose first pin lacks the reviewer "
            "role (R10); a Codex run pinned with it can",
            old_ok and rd_old.get("ownership") == integrity.OWNERSHIP == OWNERSHIP_SINCE
            and "ownership 3" in (probs_[0] or "") and REVIEWER_ROLE in (probs_[1] or "") and probs_[2] is None)
    except (Refused, stops.Refused, ValueError) as e:
        say(f"no unexpected refusal ({' '.join(str(e).split())[:300]})", False)
    except Exception as e:      # noqa: BLE001 -- a crash is a failed selftest, shown
        import traceback
        traceback.print_exc()
        say(f"no unexpected crash ({e!r})", False)
    finally:
        project.REPO, project.AUDITS, RUNNER, stops.RUNNER = keep[:4]
        if keep[4] is None:
            os.environ.pop(nested, None)
        else:
            os.environ[nested] = keep[4]
        _cleanup()
        shutil.rmtree(base, ignore_errors=True)
    print("selftest:", "ok" if all(good) else "FAILED")
    return 0 if all(good) else 1


if __name__ == "__main__":
    raise SystemExit(project.run_main(main))

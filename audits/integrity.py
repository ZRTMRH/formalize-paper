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
  render <key> ...  pdf/<key>/* -- the PDF records: RENDER.json, the rendering agents' prompts, PDFs and verdicts
                 (render_record.py, prompt.py --prompt render-*)
  reader <key> <n>  readers/<key>-<n>.md (by the reader), <key>-<n>.response[-k].md and
                 KNOWN_FAULTS-<key>.md (by the operator) -- fresh readers (readers.py)
  hand-edit HE<k> <doc>  hand-edits/HE<k>.json, HE<k>.diff -- the operator's edit of a generated document after the
                 final prepare (readers.py --hand-edit; DOC-FIX), committed with the document
  adjudicate <R> also VACUOUS.md -- statements true only vacuously
  record-fix <R> PAPER_DEFECTS.md, SKIPPED.md, VACUOUS.md -- a record correction: only the names that
                 are not declared, in their cells (commit_record_fix stores the faults in the commit
                 message; --check re-verifies the content against them)
  stop S<n> ...  stops/S<n>/* -- the record of every stop (stops.py); the trail is checked by
                 stops.trail_problems
  revert <C> (stop S<n>)  release mode only: the records C changed without owning them, restored to
                 their content before C (stops.py revert, or git revert); verified by content, never by
                 subject (revert_problem: the exact inverse of C's foreign change), it excuses C
  set-aside <R> [<lane>]  <round>/ABANDONED.json, <round>/.abandoned/* -- a round (or one re-vote
                 lane) given up before adjudication (stops.py set-aside); that commit may also commit
                 the round's (lane's) remaining lane files, after which nothing may touch them
  resolve S<n> ...  resolutions/S<n>/* -- an older run's stall resolutions (pins before ownership 2,
                 whose "resolve S<n> apply abandon-round|abandon-lane <R>" commits set rounds aside)
  scope <R> (supersede ...)  <round>/.superseded/* -- an older run's sealed lane re-run by a resolution
  escalate E<n> [(answer)]  escalations/E<n>.prompt.txt, .answer.md -- an escalation check (prompt.py
                 --prompt escalate --write; its answer committed by lanecheck.py --escalation)
Author-maintained and generated files (RUN_LOG.md, AUTHOR_NOTES.md, OUTCOMES.md, DEVIATIONS.md before ownership 3,
REPORT.md, SUMMARY.md, SIGNOFF.md rendered from SIGNOFF.json, the delivered PDFs (fingerprinted in pdf/), DECISIONS.md written from
the skeleton decisions.py generates) may change at any time, in any commit.

  integrity.py --pin                 Checkpoint A: record the apparatus (<ROUNDS-DIR>/TOOLING_PIN.json)
  integrity.py --check --round R     step 4, first thing. Exit 1 on any FAIL.
  integrity.py --check-run-record [PATH]   RUN_RECORD.md lists every tool patch, operator-closed stop, set-aside
  integrity.py --selftest
"""
import argparse, fnmatch, glob, hashlib, json, os, re, subprocess, sys, tempfile, shutil, datetime
os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"    # git ignores refs/replace/* in every call (B1c review R)

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

PIN = "TOOLING_PIN.json"
TOOLING_GLOBS = ["*.py", "*.lean", "*.sh", "AUDIT_PROTOCOL.md", "RUN.md", "run", "agents", "skills",
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
              "involvement", "involvement_answer",
              # the run mode (release/dev): switching to release mid-run would turn stops into disclosures
              "mode"]


def scope_value(c, k):
    """A scope key's value for comparison. The involvement keys compare by meaning: a run pinned
    before they existed (no key) and a config that later states the default explicitly
    ("involved", answer "default") are the same run."""
    if k == "involvement":
        return project.involvement(c)
    if k == "involvement_answer":
        return c.get(k) or "default"
    if k == "mode":
        return project.mode(c)
    return c.get(k)


# Keys that may only grow (an entry removed is a fail, an entry added is a note).
GROW_ONLY = ["lean_files", "standing_defers"]

# Author-maintained files (RUN_LOG.md, AUTHOR_NOTES.md, OUTCOMES.md, DEVIATIONS.md before ownership 3, REPORT.md,
# REPORT.tex, REPORT.pdf, DECISIONS.md) match no OWNERS pattern, so they have no owner.
# Ownership rules have versions. A pin records the version it was written under (TOOLING_PIN.json
# "ownership"; a pin without the key is version 1), and a run is judged by the rules it began with,
# so an older run's history is never re-judged under rules it could not follow (RULINGS A4).
#   1  a lane's verdict, probes and re-votes were committed by the adjudication ("adjudicate R").
#   2  they are committed by the lane's seal ("seal R <lane>", lane_auth.py), the moment it is
#      sealed; the adjudicator commits ADOPTED.md and its top-level records by name; INFORMAL.json
#      and SIGNOFF.json are committed by `signoff.py save-informal|save-signoff` ("signoff R").
#   3  DEVIATIONS.md is the adjudicator's too (integration review, attack 6: a row's kind changed to
#      "reading choice" in any commit made the summary say "faithful under reading N"; nothing checked it).
#      The operator proposes route changes under "Route changes" in AUTHOR_NOTES.md; the adjudicator
#      writes the rows. Under 1 and 2 the operator still writes the rows, but never a row whose kind is a
#      status (DEVIATION_STATUS_KINDS: added, removed, or its result or kind changed): deviation_kind_problems.
#   4  a tool patch's records (tool-patches/, OPERATOR-PATCH, approver 2026-10-24) are owned by "tool-patch "
#      commits (tool_patch.py); a release re-pin either changes no tooling or is "pin (tool-patch TP<k>)",
#      verified link by link (tool_patch.chain_problems). A run pinned earlier cannot patch (tool_patch.py refuses).
OWNERSHIP = 4
# patterns owned only from an ownership version on: an older run keeps the rules it began with (RULINGS A4)
OWNED_SINCE = {"DEVIATIONS.md": 3, "tool-patches/*": 4, "acknowledgments/*": 4}
# the DEVIATIONS.md kinds that set a result's status (result_status.py): "faithful under reading N", "differs"
DEVIATION_STATUS_KINDS = ("reading choice", "differs")
OWNERS = [  # (pattern relative to the rounds dir, required prefix under version 2, also accepted under 1)
    # a lane's probe files are evidence its verdicts cite: written by the lane in the round under
    # review, committed with its seal, never changed afterwards (an "implement" commit that
    # rewrote a probe would change the evidence behind an adopted finding). Listed FIRST: fnmatch's
    # "*" crosses "/", so a probe named e.g. TARGET.json would otherwise get the scope owner.
    # a tool patch's records (tool_patch.py): its diagnosis, every attempt's diff and facts, the reviewers' prompts,
    # tokens, seals and verdicts, a withdrawal -- each committed once by a "tool-patch TP<k> ..." commit. FIRST: the
    # reviewers' .lane-auth/.lane-seals and verdicts below would otherwise match the round patterns
    ("tool-patches/*", "tool-patch ", ()),
    # a reviewed acknowledgment of a history fault (SWEEP-FIX D2; release): its request, prompt, token, the fresh
    # reviewer's verdict and seal, each committed once by an "acknowledge AK<k> ..." commit. FIRST, as tool-patches/
    ("acknowledgments/*", "acknowledge ", ()),
    ("*/.lane-auth/*", "scope ", ()),
    ("*/.lane-seals/*", "seal ", ()),
    # an older run's stall resolutions (the stall resolver, removed in 0.3.0): before "*/*.json"
    # below, which would otherwise give resolutions/S1/STALL.json to the adjudicator
    ("resolutions/*", "resolve ", ()),
    # the stop record and set-asides (stops.py); an older run's (ownership 1) abandon commits too
    ("stops/*", "stop ", ()),
    ("waivers/*", "ack ", ()),        # the human's waiver of one commit's ownership FAIL (--acknowledge)
    # an escalation check (B7, U2 §7f): its prompt, written and committed by prompt.py --prompt escalate
    # --write ("escalate E<n>", with its sha256), and its answer, committed by lanecheck.py --escalation
    ("escalations/*", "escalate ", ()),
    ("*/.abandoned/*", "set-aside ", ("resolve ",)), ("*/ABANDONED.json", "set-aside ", ("resolve ",)),
    ("*/.reissued/*", "scope ", ()),     # a reissued lane's old verdict: evidence, never used (lane_auth.py)
    ("*/.superseded/*", "scope ", ()),   # an older run's superseded lane (supersede was removed in 0.3.0)
    ("*/*.probes/*", "seal ", ("adjudicate ",)),
    # a fresh reader's report on a document a human will read (readers.py): written by the reader,
    # committed as "reader <doc> <n>", never edited (it records which version of the document passed)
    ("readers/*", "reader ", ()),
    ("KNOWN_FAULTS-*.md", "reader ", ()),     # the notice for findings marked unfixable (readers.py)
    # DOC-FIX (approver 2026-10-25): a hand edit of a generated document after the final prepare, recorded and
    # committed by readers.py --hand-edit as "hand-edit HE<k> <doc>" (the document, HE<k>.json, HE<k>.diff). No
    # earlier run has the directory, so no older history is judged anew. --deliver checks the chain itself
    ("hand-edits/*", "hand-edit ", ()),
    # the PDFs a human reads, rendered and verified by fresh agents (render_record.py, PDF-AGENTS): RENDER.json, the
    # agents' prompts, PDFs, sources and verdicts, each committed alone as "render <key> ...". Before `*/*.json`
    # (first match; fnmatch's * crosses /), or pdf/<key>/RENDER.json would read as a lane verdict
    ("pdf/*", "render ", ()),
    ("*/TARGET.json", "scope ", ()), ("*/FINGERPRINTS.json", "scope ", ()),
    ("*/STATEMENTS_BUNDLE.md", "scope ", ()),
    ("*/ADOPTED.md", ("adjudicate ", "reader-fix "), ()), ("*/revote/*", "seal ", ("adjudicate ",)),
    ("*/INFORMAL.json", "signoff ", ("adjudicate ",)), ("*/SIGNOFF.json", "signoff ", ("adjudicate ",)),
    # SIGNOFF.md is rendered from SIGNOFF.json by signoff.py: generated, not owned; the PDFs are pdf/'s (above)
    # an older run's render fix (render_fix.py, removed in PDF-AGENTS): kept read-only so its records still check:
    # its render check was a lane (token and seal matched above), its verdict committed by its seal; the rest of
    # render/ was generated, not owned
    ("render/*.check/render-check@*.json", "seal ", ()), ("render/*", None, ()),
    # the advisory citation review (Stage 5 step 5a): its drafts and the agents' scratch files are advisory,
    # never checked; before `*/*.json` so a scratch .json there is not read as a lane verdict
    ("citations/*", None, ()),
    # the advisory status check's records (status-check/: its prompts, RUNS.json, FINDINGS.md, ACTIONS.md), committed
    # by name as "status-check: findings" (run/stage5-delivery.md); a run judging hand edits is sealed by
    # run_record.py --seal-status-check (SEAL-<n>.json; readers.judgement_problems checks it). Before `*/*.json`: replay of conf1 under DOC-FIX,
    # status-check/RUNS.json read as a lane verdict and every re-run of the check failed FAIL[ownership]
    ("status-check/*", None, ()),
    # the findings a statement-round cap left open in a release run (scope.cap_record, approver 2026-10-24), written
    # and committed by scope.py as "round-cap <round>"; before `*/*.json`, or round-caps/<round>.json would read as
    # a lane verdict. No run before this row has the directory, so no older history is judged anew
    ("round-caps/*", "round-cap ", ()),
    ("*/*.json", "seal ", ("adjudicate ",)),          # lane verdicts (after the two scope-owned json above)
    # the adjudicator's records; a "record-fix R" commit may correct their faulty cells (commit_record_fix)
    ("PAPER_DEFECTS.md", ("adjudicate ", "record-fix ", "reader-fix "), ()),
    ("SKIPPED.md", ("adjudicate ", "record-fix ", "reader-fix "), ()),
    ("VACUOUS.md", ("adjudicate ", "record-fix ", "reader-fix "), ()),
    # ownership 3 (OWNED_SINCE): the route-change rows, whose `reading choice` / `differs` kinds set a result's
    # status in the summary; written by the adjudicator (and a reader fix's unprotected cells)
    ("DEVIATIONS.md", ("adjudicate ", "reader-fix "), ()),
    # B10 (ADDENDUM N4): the reader-fix round's prompt, committed by prompt.py itself; the delivery record of
    # project.py --prepare-delivery
    ("*/prompts/adjudicator-readerfix-*.txt", "reader-fix-prompt ", ()),
    ("DELIVERY.json", "prepare delivery", ()),
    ("APPROVED_FINGERPRINTS*.json", "approve", ()), (PIN, "pin", ()),
    ("REAPPROVAL*.json", "approve", ()),   # the open re-approval (signoff.py reapprove --begin; RULINGS A11)
    ("uni_math_extra.json", "glyphs ", ()),   # an older run's glyph mappings (signoff.py glyphs, removed): read-only
]


# B8 (U2 §5, §8; U §5 "Rule 4 generated from integrity.OWNERS"): RUN.md's rule 4 -- the records the
# operator never writes or edits -- is generated from OWNERS (rule4_text); tests/doclint.py checks that
# RUN.md carries it verbatim, and that every owned pattern has a label here. The reader-owned files the
# operator writes through the fresh-reader procedure (OPERATOR_WRITES) are named as such, so the rule
# no longer forbids what run/fresh-reader.md tells the operator to do.
OWNER_LABELS = {
    "tool-patches/*": "a tool patch's records (`tool-patches/`: written by `tool_patch.py` and its reviewers)",
    "acknowledgments/*": ("the reviewed acknowledgments of history faults (`acknowledgments/`: written by `integrity.py "
                          "--ack-request` and its fresh reviewer)"),
    "*/.lane-auth/*": "lane tokens", "*/.lane-seals/*": "lane seals",
    "resolutions/*": "an older run's stall resolutions (`resolutions/`)",
    "stops/*": "the stop records (`stops/`, their repair records)",
    "waivers/*": "waivers (`waivers/`)",
    "escalations/*": "escalation prompts and answers (`escalations/`)",
    "*/.abandoned/*": "set-asides (`ABANDONED.json`, `.abandoned/`)",
    "*/ABANDONED.json": "set-asides (`ABANDONED.json`, `.abandoned/`)",
    "*/.reissued/*": "reissued and superseded lane files", "*/.superseded/*": "reissued and superseded lane files",
    "*/*.probes/*": "lane probes", "readers/*": "reader records (`readers/`)",
    "KNOWN_FAULTS-*.md": "the readers' notices (`KNOWN_FAULTS-*.md`)",
    "hand-edits/*": "the hand-edit records (`hand-edits/`: written by `readers.py --hand-edit`)",
    "pdf/*": "the PDF records (`pdf/`: `RENDER.json`, the rendering agents' prompts, PDFs and verdicts)",
    "*/TARGET.json": "`TARGET.json`", "*/FINGERPRINTS.json": "`FINGERPRINTS.json`",
    "*/STATEMENTS_BUNDLE.md": "`STATEMENTS_BUNDLE.md`", "*/ADOPTED.md": "`ADOPTED.md`",
    "*/revote/*": "re-votes", "*/INFORMAL.json": "`INFORMAL.json`", "*/SIGNOFF.json": "`SIGNOFF.json`",
    "render/*.check/render-check@*.json": "render checks", "*/*.json": "lane verdicts",
    "PAPER_DEFECTS.md": "`PAPER_DEFECTS.md`", "SKIPPED.md": "`SKIPPED.md`", "VACUOUS.md": "`VACUOUS.md`",
    "DEVIATIONS.md": "`DEVIATIONS.md` (a run pinned before ownership 3: you write its rows, never a `reading "
                     "choice` or `differs` row)",
    "APPROVED_FINGERPRINTS*.json": "the approval files (`APPROVED_FINGERPRINTS*.json`)", PIN: f"`{PIN}`",
    "REAPPROVAL*.json": "`REAPPROVAL.json`", "uni_math_extra.json": "an older run's `uni_math_extra.json`",
    "*/prompts/adjudicator-readerfix-*.txt": "the reader-fix prompt (`prompts/adjudicator-readerfix-<n>.txt`)",
    "DELIVERY.json": "the delivery record (`DELIVERY.json`)",
    "round-caps/*": "the statement-round cap records (`round-caps/`)",
}
# owned files the operator itself writes, by hand, in the procedure named (and commits under the owner's
# message); everything else in OWNERS is written only by its script or subagent
OPERATOR_WRITES = {
    "readers/*": ("your response files `readers/<key>-<n>.response[-k].md` and the notice "
                  "`KNOWN_FAULTS-<key>.md` (`run/fresh-reader.md`, committed as `reader <key> <n> (response)`)"),
}


def rule4_text():
    """RUN.md's rule 4, generated from OWNERS and OWNER_LABELS (tests/doclint.py checks RUN.md carries it)."""
    groups = {}
    for pat, pre, _v1 in OWNERS:
        if pre is None:
            continue
        key = " or ".join(f"`{x.strip()}`" for x in (pre if isinstance(pre, tuple) else (pre,)))
        lab = OWNER_LABELS.get(pat, f"UNLABELLED {pat}")
        if lab not in groups.setdefault(key, []):
            groups[key].append(lab)
    lines = ["4. **You never write or edit a record by hand**, except as named below. Each record is written by",
             "   its own script or subagent and committed under its own message (`integrity.py`'s `OWNERS`,",
             "   from which this list is generated; `integrity.py` checks every commit against it):"]
    items = list(groups.items())
    for i, (key, labs) in enumerate(items):
        lines.append(f"   - {key}: " + ", ".join(labs) + ("." if i == len(items) - 1 else ";"))
    ow = "; ".join(OPERATOR_WRITES[p] for p, _pre, _v in OWNERS if p in OPERATOR_WRITES)
    lines += [f"   Of these you write by hand only {ow}.",
              "   Never edit the audit scripts, `AUDIT_PROTOCOL.md`, this file, `audits/run/`, `audits/agents/` or",
              "   `~/.claude/agents/auditor.md`. Your own files are `RUN_LOG.md`, `AUTHOR_NOTES.md` (route changes",
              "   under \"Route changes\": the adjudicator writes `DEVIATIONS.md` from them) and `OUTCOMES.md`."]
    return "\n".join(lines)


def waiting_answer(status_line, rel):
    """An escalation's answer the escalation check wrote and lanecheck.py --escalation has not committed yet
    (new, untracked): not an uncommitted-record failure (B7). A committed answer that changed still is."""
    return status_line.startswith("??") and fnmatch.fnmatch(rel, "escalations/E*.answer.md")


def owner(rel, version=OWNERSHIP):
    """The commit prefixes allowed to change a path relative to the rounds dir (a tuple), or None
    (an author file). Under version 1 a lane file may also be committed by the adjudication."""
    for pat, pre, v1 in OWNERS:
        if fnmatch.fnmatch(rel, pat):
            if pre is None or version < OWNED_SINCE.get(pat, 0):
                return None
            return (pre if isinstance(pre, tuple) else (pre,)) + (tuple(v1) if version < 2 else ())
    return None


def pinned_version(rounds_dir):
    """The ownership version the run's pin records (1 for a pin written before versions)."""
    try:
        return int(json.load(open(os.path.join(rounds_dir, PIN))).get("ownership", 1))
    except (OSError, ValueError, TypeError, AttributeError):
        return OWNERSHIP


def in_review(status_line, need, version):
    """Is an uncommitted file in the round under review one its own steps are still writing?
    Version 2: only a NEW (untracked) file that a lane's seal, the adjudication or the sign-off
    save commits; a committed record that changed is never in review (it was changed after its
    commit: restore it). Version 1: any adjudicate-owned file of the round."""
    if version < 2:
        return "adjudicate " in need
    return status_line.startswith("??") and bool(set(need) & {"seal ", "adjudicate ", "signoff "})


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


def intake_gate(rounds_dir, repin=None):
    """B6: the run's first pin requires RUN_LOG.md's ## Intake to name the printed intake message's
    hash (prompt.py --intake); a re-pin does not re-ask the intake. None, or why the pin refuses."""
    return None if repin else project.intake_logged(rounds_dir)


def pin(audits, cfg, agent_file=AGENT_FILE, rounds_dir=None, repin=None, repo=None, tool_patch=None):
    """Write the pin. A second pin (`repin`) is allowed only with a stated reason: a genuine bug
    in the apparatus found mid-run. It is committed as "pin (repin: <reason>)" and listed in the
    report's trust section, so the human sees that the apparatus changed under the run."""
    dirty = tooling_dirty(audits)
    # the run's mode is its first pin's (a config that claims another mode is refused below, as an intake term)
    fp0 = (project.first_pin(rounds_dir) if rounds_dir else None) or {}
    rel_mode = project.mode(fp0.get("config") or cfg) == "release"
    if dirty:
        if rel_mode and repin and not tool_patch:
            # RELEASE-SWEEP I1: "commit them before pinning" led to a plain re-pin over changed tooling, a FAIL[pin]
            # in the history that no restore clears. In release a tooling change is a reviewed tool patch
            return None, ("uncommitted tooling changes: in release mode the tooling changes only through a reviewed "
                          "tool patch (python3 audits/tool_patch.py begin --stop S<n>), never a commit and a re-pin; "
                          "restore it (git -C audits checkout -- <file>) and re-pin only if a re-pin is still needed:\n  "
                          + "\n  ".join(dirty))
        return None, "uncommitted tooling changes; commit them before pinning:\n  " + "\n  ".join(dirty)
    if rel_mode and repin and not tool_patch and rounds_dir and os.path.exists(os.path.join(rounds_dir, PIN)):
        # the same rule for a committed change: a plain release re-pin must not change the tooling against every
        # earlier pin (release_repin_problems would FAIL it for ever); going back to an earlier pin's tooling is fine
        rel_ = os.path.relpath(os.path.join(rounds_dir, PIN), audits)
        earlier = list(reversed(_trusted_pins(audits, rounds_dir)))    # review B1: trusted pins only, newest first
        if earlier and not any(not git(audits, "diff", "--name-only", e_, "HEAD", "--", *TOOLING_PATHSPECS)[1].strip()
                               for e_ in earlier):
            return None, ("the committed tooling differs from every earlier pin's: in release mode the tooling changes "
                          "only through a reviewed tool patch (python3 audits/tool_patch.py begin --stop S<n>), never a "
                          f"commit and a plain re-pin; restore the pinned tooling (git -C audits checkout {earlier[0][:11]} "
                          "-- <files>; commit) and re-pin then")
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
        import tree_state       # the Stage 1 snapshot of git hooks, config, remotes/user and HEADs (U2 §4 B1c)
        doc["gitmeta"] = tree_state.snapshot(repo)
    p = os.path.join(rounds_dir, PIN)
    if os.path.exists(p) and not repin:
        return None, f"{p} exists; a pin is set once per run (a re-pin needs --repin REASON)"
    if repin and not os.path.exists(p):
        return None, "nothing to re-pin: there is no pin yet"
    doc["ownership"] = OWNERSHIP
    if repin:
        old = json.load(open(p))
        # review L1: a re-pin fixes the apparatus, never the run's terms; the live config would
        # otherwise become the pinned one (release <-> dev, or another involvement level). Forgery review M2:
        # judged against the FIRST committed pin, never the working file (which can be edited first)
        first = (project.first_pin(rounds_dir) or old).get("config", {})
        moved = [f"{k} (pinned {first.get(k)!r}, now {cfg.get(k)!r})" for k in INTAKE_TERMS
                 if scope_value(first, k) != scope_value(cfg, k)]
        if moved:
            return None, ("a re-pin cannot change " + ", ".join(moved) + ": the run mode and the involvement "
                          "level are fixed for the run; restore the config")
        doc["ownership"] = (project.first_pin(rounds_dir) or old).get("ownership", 1)   # the rules the run began with
        if "gitmeta" in old:
            doc["gitmeta"] = old["gitmeta"]     # and the Stage 1 snapshot (the gitmeta cure restores to it)
        if "codex_agents" in old and repo is None:
            # CODEX-PORT test: a re-pin made without the project (tool_patch.py apply) keeps the pinned Codex
            # roles; it dropped them, and the next integrity check FAILed [codex-roles] (stop S3 of the run)
            doc["codex_agents"] = old["codex_agents"]
        if tool_patch:
            # a tool patch changes the tooling only: the pinned config stays as it was (a grow-only key that grew
            # since is still a NOTE against it; bench2 replay: standing_defers)
            doc["config"] = old.get("config", doc["config"])
        doc["repins"] = old.get("repins", []) + [dict({"date": doc["date"], "reason": repin,
                                                       "previous_commit": old["audits_commit"]}, **(tool_patch or {}))]
    os.makedirs(rounds_dir, exist_ok=True)
    json.dump(doc, open(p, "w"), indent=1)
    return p, None


# "set-aside <R>" / "set-aside <R> <revote lane>" (stops.py): the commit that made an unadjudicated
# round's (or one re-vote lane's) remaining files record. It may commit that round's (lane's) lane
# files, which only a seal or an adjudication commits otherwise -- never its decisions. An older
# run (ownership 1) did the same with "resolve S<n> apply abandon-round|abandon-lane <R>".
SET_ASIDE_RE = re.compile(r"^set-aside (\S+)(?: (\S+))?$")
ABANDON_RE = re.compile(r"^resolve S\d+ apply abandon-(round|lane) (\S+)")
NEVER_ABANDONED = ("ADOPTED.md", "INFORMAL.json", "SIGNOFF.json", "TARGET.json", "FINGERPRINTS.json")


def set_aside_of(subject, version):
    """(round, lane or None, files-match predicate) when `subject` is a set-aside commit, else None."""
    m = SET_ASIDE_RE.match(subject)
    if m:
        rnd, lane = m.group(1), m.group(2)
        if lane:
            return rnd, lane, lambda rel: rel == f"{rnd}/{lane}.json" or rel.startswith(f"{rnd}/{lane}.probes/") \
                or rel.startswith(f"{rnd}/prompts/")
        return rnd, None, lambda rel: rel.startswith(rnd + "/")
    m = ABANDON_RE.match(subject) if version < 2 else None
    if m:
        return m.group(2), (m.group(1) == "lane" or None), lambda rel: rel.startswith(m.group(2) + "/")
    return None


# A release self-cure's revert of a commit that broke record ownership (self-cure review M3; U2 §4 B1c): a commit
# whose diff is the exact inverse of an earlier commit's foreign change -- the record files that commit changed
# without owning them, each restored to its content before it, and nothing else of the record (other files it
# touches must be inverse too). It is found and judged by content, never by its commit subject: stops.py revert's
# "revert <C> (stop S<n>)" and git revert's "Revert ..." are accepted only as inverses. Both commits are then
# excused, for the files the revert restored: the records hold again what their owners committed.
REVERT_RE = re.compile(r"^revert ([0-9a-f]{40}) \(stop (S[1-9]\d*)\)$")


def _blob(audits, rev, path):
    rc, out = git(audits, "rev-parse", "--verify", "-q", f"{rev}:{path}")
    return out.strip() if rc == 0 else None


def changed_files(audits, commit):
    rc, out = git(audits, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
    return set(l for l in out.splitlines() if l.strip()) if rc == 0 else None


def misowned(audits, rounds_rel, rounds_dir, c):
    """The record files (repository paths) commit `c` changed although its subject does not own them."""
    subj = git(audits, "log", "-1", "--format=%s", c)[1].strip()
    ver = pinned_version(rounds_dir)
    out = set()
    for f in changed_files(audits, c) or ():
        if f.startswith(rounds_rel + "/"):
            need = owner(os.path.relpath(f, rounds_rel), ver)
            if need and not subj.startswith(need):
                out.add(f)
    return out


def _merge_revert(audits, c, f, base_rev):
    """The content of `f` at `base_rev` with commit `c`'s change to `f` undone (git revert's semantics: a three-way
    merge of base_rev's content, c's content as the base and c^'s content), or None when it does not apply cleanly."""
    cur, mid, old = (_blob_text(audits, base_rev, f), _blob_text(audits, c, f), _blob_text(audits, c + "^", f))
    if None in (cur, mid) or old is None:
        return None
    t = tempfile.mkdtemp(prefix="revert-merge-")
    try:
        ps = []
        for n, txt in (("cur", cur), ("mid", mid), ("old", old)):
            p = os.path.join(t, n)
            open(p, "wb").write(txt)
            ps.append(p)
        r = subprocess.run(["git", "merge-file", "-p", *ps], capture_output=True)
        return r.stdout if r.returncode == 0 else None
    finally:
        shutil.rmtree(t, ignore_errors=True)


def _blob_text(audits, rev, path):
    r = subprocess.run(["git", "-C", audits, "show", f"{rev}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _named_revert(audits, h, c):
    """Is commit `h`'s subject "revert <c> (stop S<n>)" (stops.py revert's) naming commit `c`?"""
    m = REVERT_RE.match(git(audits, "log", "-1", "--format=%s", h)[1].strip())
    return bool(m) and m.group(1) == c


def _set_aside_at(audits, rounds_rel, rel, rev):
    """Was the round of record `rel` (relative to the rounds dir) set aside at commit `rev` (its marker there)?"""
    rnd = rel.split("/", 1)[0]
    return "/" in rel and (_blob(audits, rev, f"{rounds_rel}/{rnd}/ABANDONED.json") is not None
                           or bool(git(audits, "ls-tree", "--name-only", rev, "--", f"{rounds_rel}/{rnd}/.abandoned/")[1].strip()))


def revert_files(audits, rounds_rel, rounds_dir, h, c):
    """(the record files [repo paths] a revert `h` of commit `c` may restore, owned?): c's record files it does not own
    (an operator's hand edit), or -- review R2 -- when h is stops.py's "revert <c> (stop S<n>)", every record file of
    an OWNED commit c (a record-fix commit that changed more than its cells, a commit that touched a set-aside round's
    files): never silently, an owner redo follows (revert_redo)."""
    cf = misowned(audits, rounds_rel, rounds_dir, c)
    if cf:
        return cf, False
    if _named_revert(audits, h, c):
        return {f for f in changed_files(audits, c) or () if f.startswith(rounds_rel + "/")}, True
    return set(), False


def revert_problem(audits, rounds_rel, rounds_dir, h, c):
    """Why commit `h` is no verified revert of commit `c`, or None (by content only; review R1/R2). Per record file f
    of c (revert_files; h touches exactly those, and no file c did not change):
      - nothing changed f since c: h restores f to its content before c (the exact inverse);
      - else (a later commit changed f): h is c's change undone ONTO the current content (git revert semantics: the
        three-way merge, clean) -- the later work stays -- or, when every later change of f was its owner's, f restored
        to its content before c, which undoes the owner's work too: then FAIL[owner-redo] (revert_redo) until a fresh
        round's adjudication re-decides it."""
    if git(audits, "merge-base", "--is-ancestor", c, h + "^")[0]:
        return f"{c[:11]} is not an earlier commit"
    cf, owned = revert_files(audits, rounds_rel, rounds_dir, h, c)
    hf = changed_files(audits, h) or set()
    if not cf:
        return f"{c[:11]} changed no record file it does not own"
    # the record files it touches are EXACTLY c's (review H1: a revert that also undid records c owned -- a superset
    # -- was accepted and excused its own unowned change of them); other files: exact inverses
    if {f for f in hf if f.startswith(rounds_rel + "/")} != cf:
        return f"the record files it changes must be exactly those {c[:11]} changed" + ("" if owned else " without owning them")
    if not hf <= (changed_files(audits, c) or set()):
        return f"it changes files {c[:11]} did not change"
    for f in sorted(hf):
        now, before = _blob(audits, h, f), _blob(audits, c + "^", f)
        if _blob(audits, h + "^", f) == _blob(audits, c, f):
            if now != before:
                return f"{f} is not restored to its content before {c[:11]}"
            continue
        merged = _merge_revert(audits, c, f, h + "^")
        if merged is not None and merged == (_blob_text(audits, h, f) or b""):
            continue
        if now == before and owner_only_since(audits, rounds_rel, rounds_dir, f, c, h) is True:
            continue
        return (f"{f} changed between {c[:11]} and the revert, and the revert is neither {c[:11]}'s change undone onto "
                f"the current content nor (every later change being its owner's) the content before {c[:11]}")
    return None


def revert_redo(audits, rounds_rel, rounds_dir, h, c):
    """{record file relative to the rounds dir: "round" or "full"} that verified revert `h` of `c` leaves for a fresh
    adjudication (review R1/R2): a file restored over its owner's later work (a fresh round's adjudication re-decides
    it); every file of an OWNED commit c ("full": a fresh full round's adjudication re-writes the records), except a
    set-aside round's file put back exactly as it was set aside."""
    cf, owned = revert_files(audits, rounds_rel, rounds_dir, h, c)
    out = {}
    for f in sorted(cf):
        rel = os.path.relpath(f, rounds_rel)
        exact = _blob(audits, h + "^", f) == _blob(audits, c, f)
        if owned:
            if not (exact and _set_aside_at(audits, rounds_rel, rel, c + "^")):
                out[rel] = "full"
        elif not exact:
            merged = _merge_revert(audits, c, f, h + "^")
            if merged is None or merged != (_blob_text(audits, h, f) or b""):
                out[rel] = "round"
    return out


REDO_RULED_RE = re.compile(r"^\s*(?:[-*]\s*)?REDO RULED\s+(\S+)\s*\|\s*(.+?)\s*\|\s*(keep|drop)\s*:\s*\S.*$", re.M)


def _norm_line(t):
    return " ".join(str(t or "").split())


def undone_lines(audits, rounds_rel, h, rel):
    """The lines (normalised, non-blank) the verified revert `h` removed from record `rel` (relative to the rounds
    dir): its content before the revert minus its content after, line by line (a multiset difference)."""
    import collections
    f = f"{rounds_rel}/{rel}"
    before = [_norm_line(l) for l in (_blob_text(audits, h + "^", f) or b"").decode("utf-8", "replace").splitlines()]
    after = collections.Counter(_norm_line(l) for l in (_blob_text(audits, h, f) or b"").decode("utf-8", "replace").splitlines())
    out = []
    for l in before:
        if not l:
            continue
        if after[l]:
            after[l] -= 1
        else:
            out.append(l)
    return out


def _redo_rulings(audits, rounds_rel, rev, rnd):
    """[(record, row cell, keep|drop)] of the REDO RULED lines in round `rnd`'s ADOPTED.md at commit `rev`."""
    txt = (_blob_text(audits, rev, f"{rounds_rel}/{rnd}/ADOPTED.md") or b"").decode("utf-8", "replace")
    return [(m.group(1), _norm_line(m.group(2)), m.group(3)) for m in REDO_RULED_RE.finditer(txt)]


def _rules(cell, line):
    return len(cell) >= 3 and line.startswith(cell)


def owner_redo_items(audits, rounds_rel, hist, redo):
    """[{record, revert, commit, kind, undone, why}] -- review R1/R2 (coordinator 2026-10-26): every record a verified
    revert put back over its owner's work, with the lines the restore removed (`undone`), and `why` it is still open
    (None once settled). It is settled only by the adjudication ("adjudicate R") of a FULL round R scoped after the
    revert whose ADOPTED.md rules EVERY undone line -- `REDO RULED <record> | <the line, or its first words> | keep:
    <why>` or `drop: <why>` (the adjudicator re-decides each; code checks that each has a ruling, never what it says)
    -- and every kept line stands in the record now."""
    order = {h: i for i, (_s, _f, h) in enumerate(hist)}      # newest first: a smaller index is later
    scoped = {}
    for s_, files, h_ in hist:
        for f in files:
            if f.endswith("/TARGET.json"):
                scoped[f.split("/", 1)[0]] = h_
    out = []
    for h, (c, files) in redo.items():
        later = [(s_, h_) for s_, _f, h_ in hist if order.get(h_, 1 << 30) < order.get(h, -1)]
        for rel, kind in sorted(files.items()):
            undone = undone_lines(audits, rounds_rel, h, rel)
            now = {_norm_line(l) for l in (_blob_text(audits, "HEAD", f"{rounds_rel}/{rel}") or b"").decode(
                "utf-8", "replace").splitlines()}
            why = "no adjudication of a fresh full round has ruled on it yet"
            for s_, k in reversed(later):       # oldest first
                m = re.match(r"^adjudicate (\S+)", s_)
                R = m.group(1) if m else None
                if not R or R not in scoped or order[scoped[R]] >= order[h] or "-full-" not in R:
                    continue
                rul = [x for x in _redo_rulings(audits, rounds_rel, k, R) if x[0] in (rel, f"{rounds_rel}/{rel}")]
                miss = [l for l in undone if not any(_rules(cell, l) for _r, cell, _d in rul)]
                if miss:
                    why = f"the adjudication of {R} ({k[:11]}) has no REDO RULED line for \"{miss[0][:80]}\""
                    continue
                gone = [l for l in undone if any(_rules(cell, l) and d == "keep" for _r, cell, d in rul) and l not in now]
                if gone:
                    why = f"the adjudication of {R} ({k[:11]}) keeps \"{gone[0][:80]}\", which the record does not hold"
                    continue
                why = None
                break
            out.append({"record": rel, "revert": h, "commit": c, "kind": kind, "undone": undone, "why": why})
    return out


def owner_redo_problems(audits, rounds_rel, hist, redo):
    """[FAIL text] of every owner_redo_items entry still open."""
    return [f"[owner-redo] {x['record']}: the verified revert {x['revert'][:11]} of {x['commit'][:11]} put back its "
            f"content from before {x['commit'][:11]}, which also undid what its owner decided since -- nothing is dropped "
            f"silently: a fresh FULL round must re-decide it (scope it after the revert: python3 audits/prompt.py 3 "
            f"--full; its adjudicator's prompt lists the {len(x['undone'])} undone line(s), and its ADOPTED.md rules "
            f"each one, `REDO RULED {x['record']} | <the line> | keep: <why>` or `drop: <why>`, a kept one written "
            f"back in the record); now: {x['why']}" for x in owner_redo_items(audits, rounds_rel, hist, redo) if x["why"]]


def owner_redo_pending(audits, rounds_dir, cfg=None):
    """The open owner_redo_items of the run (for the adjudicator's prompt), [] outside release."""
    rounds_rel = os.path.relpath(rounds_dir, audits)
    if (cfg or {}).get("mode") != "release" and project.mode((project.first_pin(rounds_dir) or {}).get("config") or {}) != "release":
        return []
    hist = history(audits, rounds_rel)
    fp = max((i for i, (_, files, _h) in enumerate(hist) if PIN in files), default=None)
    if fp is not None:
        hist = hist[:fp + 1]
    return [x for x in owner_redo_items(audits, rounds_rel, hist, verified_reverts(audits, rounds_rel, rounds_dir, hist)[2])
            if x["why"]]


def owner_only_since(audits, rounds_rel, rounds_dir, f, c, h="HEAD"):
    """SWEEP-FIX review H2 / RELEASE-SWEEP I3: True when every commit after `c` up to (not including) `h` that changed
    record file `f` is a commit of its owner (e.g. the next adjudication re-committed an operator's hand edit), False
    when another commit changed it, None when none did. A revert may then still restore `f` to its content before `c`
    -- undoing the owner's later change too, which the owner then makes again (the round's adjudication): a real cure,
    never a whitewash of the hand edit."""
    need = owner(os.path.relpath(f, rounds_rel), pinned_version(rounds_dir))
    rc, log = git(audits, "log", "--format=%s", f"{c}..{h}" + ("^" if h != "HEAD" else ""), "--", f)
    subs = [l for l in log.splitlines() if l.strip()]
    if not subs:
        return None
    return bool(need) and all(x.startswith(need) for x in subs)


def verified_reverts(audits, rounds_rel, rounds_dir, hist):
    """({commit: (revert commit, {files it restored, relative to the rounds dir})}, [(revert commit, why
    not verified)]). A commit that changed records it does not own is a verified revert when it is the exact
    inverse of the foreign change of an earlier such commit (revert_problem; the nearest one), whatever its subject.
    A verified revert excuses, in the reverted commit and in itself, ONLY the files it restored: every other change
    of the reverted commit is checked as any commit's (re-check R2). A commit whose subject claims a revert but is
    no inverse is listed as not verified."""
    ver = pinned_version(rounds_dir)
    mis = lambda subj, files: {f for f in files if owner(f, ver) and not subj.startswith(owner(f, ver))}
    ok, bad, old, redo = {}, [], list(reversed(hist)), {}
    for i, (subject, files, h) in enumerate(old):
        mine = mis(subject, files)
        found = None
        named = REVERT_RE.match(subject)
        for subj_c, files_c, c in (reversed(old[:i]) if mine else ()):
            if c not in ok and (mis(subj_c, files_c) or (named and named.group(1) == c)) \
                    and revert_problem(audits, rounds_rel, rounds_dir, h, c) is None:
                found = c
                break
        if found:      # it excuses only what it restored of found's change
            ok[found] = ok[h] = (h, set(mine) & {os.path.relpath(f, rounds_rel)
                                                 for f in revert_files(audits, rounds_rel, rounds_dir, h, found)[0]})
            rr_ = revert_redo(audits, rounds_rel, rounds_dir, h, found)
            if rr_:
                redo[h] = (found, rr_)
        elif REVERT_RE.match(subject) or subject.startswith("Revert "):
            bad.append((h, "its diff is not the exact inverse of an earlier commit's change to records it did not "
                           "own (a revert is judged by its content, never by its subject)"))
    return ok, bad, redo


def _deviation_rows(text):
    """{row number: (result cell, kind cell)} of DEVIATIONS.md's table rows."""
    out = {}
    for _i, cells, head in _rows(text):
        if cells and head:
            col = lambda n: next((cells[j] for j, h in enumerate(head) if h.startswith(n) and j < len(cells)), "")
            out[cells[0].strip()] = (" ".join(col("result").split()), " ".join(col("kind").strip("*` ").split()).lower())
    return out


def deviation_kind_problems(audits, rounds_rel, hist, ver):
    """[(commit, text)] (ownership 1 and 2; integration review, attack 6). The status rows of DEVIATIONS.md (kind
    `reading choice` or `differs`: they set a result's status) may change only in a commit of its owners
    (adjudicate, reader-fix). Walked from the pin: the rows as the last such commit (or the pin) left them are the
    standing ones; a later commit of anyone else that leaves them different -- a row added, removed, or its result
    or kind changed, to or from a status kind -- is a problem until a commit restores them exactly (the operator
    owns the rest of the file in these runs, so restoring it is the cure). Under ownership 3 the whole file is
    owned (owner())."""
    own = ("adjudicate ", "reader-fix ")
    status = lambda rows: {k: v for k, v in rows.items() if v[1] in DEVIATION_STATUS_KINDS}
    old = list(reversed(hist))
    if not old:
        return []
    every = _deviation_rows(_git_text(audits, old[0][2], f"{rounds_rel}/DEVIATIONS.md"))
    standing = status(every)
    first_bad = None
    for subject, files, h in old[1:]:
        if "DEVIATIONS.md" not in files:
            continue
        rows_now = _deviation_rows(_git_text(audits, h, f"{rounds_rel}/DEVIATIONS.md"))
        now = status(rows_now)
        if subject.startswith(own):
            standing, first_bad = now, None
        elif now != standing:
            first_bad = first_bad or (h, subject, now, every)
        else:
            first_bad = None
        every = rows_now
    if not first_bad:
        return []
    h, subject, now, before = first_bad
    diff = []
    for k in sorted(set(standing) | set(now)):
        a, b = standing.get(k) or before.get(k), now.get(k)
        if a != b:
            diff.append(f"row {k} of kind `{b[1]}` added" if a is None else f"row {k} of kind `{a[1]}` removed"
                        if b is None else f"row {k} changed from `{a[1]}` ({a[0][:40]}) to `{b[1]}` ({b[0][:40]})")
    return [(h, f"DEVIATIONS.md: {'; '.join(diff) or 'a status row changed'} by \"{subject[:50]}\" ({h[:11]}); a "
                f"`reading choice` or `differs` row sets a result's status, so only an adjudication (\"adjudicate R\") "
                f"writes, changes or removes one: restore the rows as the last adjudication left them (revert the "
                f"commit) and let the next adjudicator decide it")]


def deviations_ownership_problems(cfg, audits=None, rounds_dir=None):
    """[text] of the commits that changed DEVIATIONS.md against its ownership (both rules above), for
    `make_report.py --check --delivery`: the summary's statuses read it, so a delivery never rests on such a
    commit even before integrity's own check runs. Commits a verified revert restored (release) are excused."""
    audits = audits or project.AUDITS
    rounds_dir = rounds_dir or os.path.join(project.REPO, cfg["rounds_dir"])
    rounds_rel = os.path.relpath(rounds_dir, audits)
    hist = history(audits, rounds_rel)
    first_pin = max((i for i, (_, files, _h) in enumerate(hist) if PIN in files), default=None)
    if first_pin is not None:
        hist = list(hist[:first_pin + 1])     # the run begins at its first pin, as check() judges it
    ver = pinned_version(rounds_dir)
    reverted = verified_reverts(audits, rounds_rel, rounds_dir, hist)[0] if (cfg or {}).get("mode") == "release" else {}
    exc = {h for h in reverted if "DEVIATIONS.md" in reverted[h][1]}
    # SWEEP-FIX D2: a commit whose FAIL[ownership] line on DEVIATIONS.md a fresh reviewer acknowledged (release)
    acked = [l for l in (acknowledged(audits, rounds_dir) if (cfg or {}).get("mode") == "release" else {})
             if l.startswith("[ownership] ") and "DEVIATIONS.md" in l]
    exc |= {h for _s, _f, h in hist if any(h[:11] in l for l in acked)}
    if ver >= OWNED_SINCE["DEVIATIONS.md"]:
        need = owner("DEVIATIONS.md", ver)
        return [f"DEVIATIONS.md was committed by \"{s_[:50]}\" ({h[:11]}); only a \"{need[0].strip()} …\" commit may "
                f"change it (integrity.py --check: FAIL[ownership])"
                for s_, files, h in reversed(hist) if "DEVIATIONS.md" in files and not s_.startswith(need) and h not in exc]
    return [t for _h, t in deviation_kind_problems(audits, rounds_rel, hist, ver)]


def history(audits, rounds_rel):
    """[(subject, [paths relative to the rounds dir], commit)] for every commit touching the rounds dir."""
    rc, out = git(audits, "log", "--format=@@%H %s", "--name-only", "--", rounds_rel)
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            h, _, subj = line[2:].partition(" ")
            cur = (subj, [], h); commits.append(cur)
        elif line.strip() and cur is not None:
            rel = os.path.relpath(line.strip(), rounds_rel)
            if not rel.startswith(".."):
                cur[1].append(rel)
    return commits


def check(audits, cfg, round_name, agent_file=AGENT_FILE, rounds_dir=None, rounds_rel=None,
          repo=None):
    """[(severity, message)] with severity 'FAIL' or 'note'; every message starts with its cause
    code, "[<code>] " (project.CAUSES), printed as FAIL[<code>] / NOTE[<code>]."""
    out = []
    p = os.path.join(rounds_dir, PIN)
    if not os.path.exists(p):
        return [("FAIL", f"[no-pin] no {PIN}: the apparatus was never pinned (audits/run/stage1-setup.md, step 5), so "
                         f"nothing can be compared")]
    doc = json.load(open(p))
    base = doc["audits_commit"]
    # 1. tooling: committed or not, nothing differs from the pinned commit
    rc, diff = git(audits, "diff", "--name-only", base, "--", *TOOLING_PATHSPECS)
    if rc != 0:
        out.append(("FAIL", f"[no-pin] cannot diff against pinned commit {base}"))
    changed = set(diff.splitlines()) | {l[3:] for l in tooling_dirty(audits)}
    # git's own view can be told to look away (an entry in .git/info/exclude, `update-index
    # --assume-unchanged` / --skip-worktree): compare the bytes on disk with the pinned commit
    # directly, and list ignored untracked tooling files (found by the audit of batch D)
    changed |= disk_differs(audits, base)
    rc_i, ign = git(audits, "ls-files", "-o", "-i", "--exclude-standard", "--", *TOOLING_PATHSPECS)
    changed |= {f for f in ign.splitlines() if f.strip() and "__pycache__" not in f}
    for f in sorted(changed):
        if f.strip():
            out.append(("FAIL", f"[tooling] tooling changed since the pin: {f.strip()}"))
    # bytecode where it could shadow a tool (a lane's probe script leaves a __pycache__ in its probe
    # directory, which is evidence, not apparatus). RULINGS A10a: a cached __pycache__/*.pyc is
    # regenerated from its source or ignored when stale, so it is a NOTE (project.py --env-check
    # removes it); a sourceless .pyc outside __pycache__ or an unchecked-hash .pyc can run code no
    # source shows, and FAILs.
    pyc = project.apparatus_pycs(audits)
    bad = [(p, project.dangerous_pyc(p)) for p in pyc if project.dangerous_pyc(p)]
    if bad:
        out.append(("FAIL", f"[pyc] compiled bytecode that can run without its source: "
                            f"{os.path.relpath(bad[0][0], audits)}: {bad[0][1]} -- remove it (rm), after checking what wrote it "
                            f"(a program that keeps writing it is outside interference)"))
    elif pyc:
        out.append(("note", f"[pyc-cache] {len(pyc)} cached bytecode file(s) in audits/ ({os.path.relpath(pyc[0], audits)} …): "
                            f"run python3 audits/project.py --env-check, which removes them"))
    # 2. the reviewer agent: unchanged, and not overridden by a project-level copy
    repo_agent = os.path.join(audits, "agents", "auditor.md")
    if os.path.exists(repo_agent) and sha(repo_agent) != sha(agent_file):
        out.append(("FAIL", f"[agent] the installed reviewer agent {agent_file} differs from the versioned "
                            f"copy audits/agents/auditor.md; reinstall it (cp) and re-pin"))
    if sha(agent_file) != doc.get("agent_sha256"):
        out.append(("FAIL", f"[agent] reviewer agent definition changed or missing since the pin: {agent_file}"))
    if repo and os.path.exists(os.path.join(repo, ".claude", "agents", "auditor.md")):
        out.append(("FAIL", "[agent] a project-level .claude/agents/auditor.md overrides the pinned reviewer"))
    # Generated Codex roles are the actual instructions supplied to built-in children.
    if repo:
        import codex_agents
        try:
            roles = codex_agents.state(os.path.join(repo, ".codex", "agents"))
            if roles != doc.get("codex_agents"):
                out.append(("FAIL", "[codex-roles] Codex role definitions changed, added or missing since the pin"))
        except (OSError, ValueError) as e:
            out.append(("FAIL", f"[codex-roles] {e}"))
    # 3. config
    for k in SCOPE_KEYS:
        if scope_value(cfg, k) != scope_value(doc["config"], k):
            out.append(("FAIL", f"[config] config key `{k}` changed since the pin: "
                                f"{doc['config'].get(k)!r} -> {cfg.get(k)!r}"))
    out += intake_terms_problems(rounds_dir, doc, cfg)
    for k in GROW_ONLY:
        old, new = doc["config"].get(k) or [], cfg.get(k) or []
        key = (lambda x: json.dumps(x, sort_keys=True))
        gone = [x for x in old if key(x) not in {key(y) for y in new}]
        if gone:
            out.append(("FAIL", f"[config] config key `{k}` lost entries since the pin: {gone[:3]}"))
        elif len(new) != len(old):
            out.append(("note", f"[config-grew] config key `{k}` grew by {len(new) - len(old)} since the pin"))
    # 4. ownership of committed records
    pin_subjects = []
    hist = history(audits, rounds_rel)
    # the run begins at the first pin: commits before it (a project's records imported, or kept
    # under an older protocol, before this run adopted the protocol) are not this run's to judge
    first_pin = max((i for i, (_, files, _h) in enumerate(hist) if PIN in files), default=None)
    if first_pin is not None and first_pin + 1 < len(hist):
        out.append(("note", f"[before-pin] {len(hist) - first_pin - 1} commit(s) to the record before the first pin "
                            f"not checked: the run began at the pin"))
        hist = hist[:first_pin + 1]
    ver = int(doc.get("ownership", 1))
    frozen = []   # (prefix or exact path, set-aside subject), oldest first
    waived, wprobs = waivers(audits, rounds_dir, cfg)
    out += [("FAIL", f"[waiver] {w}") for w in wprobs]
    reverted, rbad, rredo = verified_reverts(audits, rounds_rel, rounds_dir, hist) if (cfg or {}).get("mode") == "release" \
        else ({}, [], {})
    # review R1/R2: a verified revert that undid an owner's decisions leaves FAIL[owner-redo] until a fresh adjudication
    out += [("FAIL", t) for t in owner_redo_problems(audits, rounds_rel, hist, rredo)]
    out += [("FAIL", f"[ownership] revert commit {h_[:11]} is not a verified revert: {w}") for h_, w in rbad]
    for subject, files, commit_h in reversed(hist):
        ab = set_aside_of(subject, ver)
        for rel in files:
            need = owner(rel, ver)
            if need == ("pin",):
                pin_subjects.append((subject, commit_h))
            excused = commit_h in reverted and rel in reverted[commit_h][1]   # a file the verified revert restored
            for fz, by in ([] if excused else frozen):
                if rel == fz or (fz.endswith("/") and rel.startswith(fz)):
                    out.append(("FAIL", f"[set-aside-changed] {rel} was touched after it was set aside (by \"{by[:50]}\"), "
                                        f"by \"{subject[:50]}\" ({commit_h[:11]}): a set-aside record is never changed"))
                    break
            abandoned_file = (ab and ab[2](rel) and need is not None
                              and set(need) & {"adjudicate ", "seal ", "signoff "}
                              and os.path.basename(rel) not in NEVER_ABANDONED)
            if need and not subject.startswith(need) and not abandoned_file and excused:
                out.append(("note", f"[reverted] {rel} was committed by \"{subject[:50]}\" ({commit_h[:11]}), not its "
                                    f"owner; a verified revert ({reverted[commit_h][0][:11]}) restored it (release self-cure)"))
            elif need and not subject.startswith(need) and not abandoned_file and commit_h in waived:
                out.append(("note", f"[acknowledged] {rel} was committed by \"{subject[:50]}\" (not its owner); the "
                                    f"human waived it ({waived[commit_h]}); the report's summary page lists it"))
            elif need and not subject.startswith(need) and not abandoned_file:
                out.append(("FAIL", f"[ownership] {rel} was committed by \"{subject[:50]}\" ({commit_h[:11]}); only a "
                                    f"\"{need[0].strip()} …\" commit may change it"))
        if ab:
            frozen += ([(ab[0] + "/", subject)] if not ab[1]
                       else [(f, subject) for f in files if f.startswith(ab[0] + "/")])
    if ver < OWNED_SINCE["DEVIATIONS.md"]:
        out += [("FAIL", f"[ownership] {t}") for _h, t in deviation_kind_problems(audits, rounds_rel, hist, ver)]
    for h_, rnd_, _d, _c, rprobs in record_fix_commits(audits, rounds_rel, cfg):
        if h_ in reverted:
            continue        # review R2: undone by a verified revert (its owner redo is FAIL[owner-redo] until done)
        out += [("FAIL", f"[record-fix-diff] \"record-fix {rnd_}\" ({h_[:11]}): {x}") for x in rprobs]
    for h_, rnd_, rprobs in reader_fix_commit_problems(audits, rounds_rel):     # B10, ADDENDUM N4
        if h_ in reverted:
            continue
        out += [("FAIL", f"[record-fix-diff] reader fix of {rnd_} ({h_[:11]}): {x}") for x in rprobs]
    # (walked oldest first above, so pin_subjects is in commit order)
    if not pin_subjects or pin_subjects[0][0] != "pin":
        out.append(("FAIL", f"[pin] {PIN}: the first pin commit must be exactly \"pin\" "
                            f"(found {[x[0] for x in pin_subjects[:1]]}{' ' + pin_subjects[0][1][:11] if pin_subjects else ''})"))
    for sj, sh in pin_subjects[1:]:
        if not re.match(r"^pin \((?:repin: .+|tool-patch TP[1-9]\d*)\)$", sj):
            out.append(("FAIL", f"[pin] {PIN} re-committed as \"{sj[:50]}\" ({sh[:11]}); a re-pin must be "
                                f"\"pin (repin: <reason>)\" via integrity.py --pin --repin, or \"pin (tool-patch TP<k>)\" "
                                f"via tool_patch.py apply"))
    out += release_repin_problems(audits, rounds_dir, rounds_rel)
    # OPERATOR-PATCH: every "pin (tool-patch TP<k>)" link verified by the apparatus pinned just before it
    import tool_patch
    out += tool_patch.chain_problems(audits, rounds_dir, cfg)
    # re-check 3 (2026-10-25): a tooling file the first pin did not have (a tool patch only modifies files; its one new
    # file is its regression test), and a module on the import path that shadows the standard library
    out += tool_patch.manifest_problems(audits, rounds_dir)
    if len(pin_subjects) > 1:
        out.append(("note", f"[repinned] the apparatus was re-pinned {len(pin_subjects) - 1} time(s) during this run"))
    # 5. uncommitted writes: author files anywhere at the top; protected records only inside
    #    the round under review (that is where lanes and the sign-off agents write)
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all", "--", rounds_rel)
    for line in st.splitlines():
        rel = os.path.relpath(line[3:].strip().strip('"'), rounds_rel)
        need = owner(rel, ver)
        if need is None:
            continue
        if round_name and rel.startswith(round_name + "/") and in_review(line, need, ver):
            continue
        if waiting_answer(line, rel):
            continue
        hint = (" -- a lane's probe evidence: never delete, move or edit it. A changed committed probe: "
                "restore it (git checkout). A new one is committed by its lane's seal; if the lane cannot be "
                "sealed and its round will never be adjudicated, set the round (or the re-vote lane) aside: "
                "stops.py set-aside" if ".probes/" in rel else "")
        out.append(("FAIL", f"[{'uncommitted-record' if line.startswith('??') else 'record-changed'}] uncommitted change to a protected record outside the round under "
                            f"review: {line.strip()}{hint}"))
    # 6. the stop record and set-asides (stops.py)
    if cfg.get("rounds_dir"):
        import stops
        try:
            for p_ in stops.trail_problems(cfg, audits=audits, rd=rounds_dir):
                out.append(("FAIL", f"[stop-trail] {p_}"))
        except (OSError, ValueError) as e:
            out.append(("FAIL", f"[stop-trail] stop trail: cannot be read: {e}"))
    # 7. every adjudicated round settles its lanes' NOTEs and re-votes, however it was committed (ROUND3 M1)
    if cfg.get("rounds_dir"):
        import lanecheck
        for p_ in lanecheck.record_problems(rounds_dir):
            out.append(("FAIL", f"[unsettled] {p_}"))
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all")
    for line in st.splitlines():
        path = line[3:].strip().strip('"')
        if not path.startswith(rounds_rel + "/") and not path.startswith("projects/"):
            if not is_tooling(path):
                out.append(("note", f"[uncommitted-file] uncommitted file in audits/: {path}"))
    # SWEEP-FIX D2: a history FAIL a fresh reviewer judged bookkeeping is acknowledged, exactly that line (release)
    return acknowledge_lines(audits, rounds_dir, out)


def release_repin_problems(audits, rounds_dir, rounds_rel):
    """OPERATOR-PATCH (review R7): in a release run pinned under ownership 4 or later, a plain re-pin ("pin (repin:
    ...)") changes no tooling -- the diff of the tooling between the previous pin's commit and the new one is empty
    (the gitmeta snapshot re-pin of RUN.md's restore cure); a tooling change mid-run is a reviewed tool patch,
    "pin (tool-patch TP<k>)". Today's unreviewed hole (a plain re-pin over a hand edit) is FAIL[pin]."""
    fp = project.first_pin(rounds_dir) or {}
    try:
        if project.mode(fp.get("config") or {}) != "release" or int(fp.get("ownership", 1)) < 4:
            return []
    except (TypeError, ValueError):
        return []
    rel = os.path.join(rounds_rel, PIN)
    out, trusted = [], []
    rc, log = git(audits, "log", "--reverse", "--format=%H %s", "--", rel)
    for i, line in enumerate(log.splitlines()):
        h, _, subj = line.partition(" ")
        try:
            b_ = json.loads(git(audits, "show", f"{h}:./{rel}")[1]).get("audits_commit")
        except (ValueError, AttributeError):
            out.append(("FAIL", f"[pin] pin commit {h[:11]}: its {PIN} cannot be read"))
            continue
        if i == 0 or re.match(r"^pin \(tool-patch TP[1-9]\d*\)$", subj):
            # the first pin, and a tool-patch link (verified link by link: tool_patch.chain_problems), set the tooling
            trusted.append(b_)
            continue
        # SWEEP-FIX review B1: EVERY other commit of the pin, whatever its subject (a mistyped "pin (repin:x)", "pin
        # again"), must leave the tooling of a trusted pin (the first, or a tool patch's): going back is fine, forward
        # to unreviewed code never
        d = ""
        for a_ in reversed(trusted):
            rc, d = git(audits, "diff", "--relative", "--name-only", str(a_), str(b_), "--", *TOOLING_PATHSPECS)
            if rc == 0 and not d.strip():
                break
        else:
            rc = 1
        if rc or d.strip():
            out.append(("FAIL", f"[pin] re-pin {h[:11]} (\"{subj[:60]}\") changed the tooling ({(d.split() or ['?'])[0]}"
                                f"{' …' if len(d.split()) > 1 else ''}): in release a tooling change is a reviewed tool "
                                f"patch (tool_patch.py), never a plain re-pin; restore the pinned tooling"))
    return out


# Forgery review M2: the terms the human chose at intake (involvement level and answer) and the run's mode and
# ownership rules are fixed by the FIRST committed pin. The config check above compares with the working pin,
# which an operator could edit together with the config (a mid-run involved -> hands-off flip that hands the
# operator the human's decisions); these compare with the first pin.
INTAKE_TERMS = ("mode", "involvement", "involvement_answer")


def intake_terms_problems(rounds_dir, doc, cfg):
    """[("FAIL", "[pin] ...")] for every intake term (INTAKE_TERMS, the ownership version) the working pin `doc` or
    the config `cfg` states differently from the run's first committed pin (project.first_pin). A record
    problem: release self-cures it by restoring the intake value (a stop of class tamper, cured and listed in
    the report); dev waits for the human. No committed pin yet: nothing to compare."""
    fp = project.first_pin(rounds_dir)
    if not fp:
        return []
    out, cfg0 = [], fp.get("config") or {}
    for k in INTAKE_TERMS:
        first = scope_value(cfg0, k)
        for what, src in (("the pin", doc.get("config") or {}), ("the config", cfg)):
            if scope_value(src, k) != first:
                out.append(("FAIL", f"[pin] `{k}` is fixed at the intake (the first committed {PIN}: {cfg0.get(k)!r}); "
                                    f"{what} now says {src.get(k)!r}. The involvement level, its intake answer and "
                                    f"the run mode never change mid-run: restore the intake value in {what} and "
                                    f"commit (release: that is the self-cure; the report lists the stop)"))
    try:
        v0, v = int(fp.get("ownership", 1)), int(doc.get("ownership", 1))
    except (TypeError, ValueError):
        v0, v = None, doc.get("ownership")
    if v0 != v:
        out.append(("FAIL", f"[pin] the ownership version is fixed at the first committed {PIN} ({fp.get('ownership', 1)!r}); "
                            f"the pin now says {doc.get('ownership', 1)!r}: restore it and commit"))
    return out


def line_of(sev, m):
    """FAIL[<code>] message / NOTE[<code>] message, from check()'s (severity, "[<code>] message")."""
    mm = re.match(r"^\[([a-z0-9-]+)\] ", m)
    kind = "FAIL" if sev == "FAIL" else "NOTE"
    return f"{kind}[{mm.group(1)}] {m[mm.end():]}" if mm else f"{kind} {m}"


WAIVERS = "waivers"


def added_only(audits, commit):
    """[path] the commit ADDED, or None when it modified, deleted or renamed anything (or is unknown)."""
    rc, out = git(audits, "show", "--name-status", "--format=", "--no-renames", commit)
    lines = [l for l in out.splitlines() if l.strip()]
    if rc != 0 or not lines or any(not l.startswith("A\t") for l in lines):
        return None
    return [l.split("\t", 1)[1] for l in lines]


# Records another check reads as control data (ROUND3 M3): adding one changes what a check sees
# (a marker hides a lane, a seal or ADOPTED.md settles one), so a commit that adds one is never
# waived. Lane evidence -- a verdict or a probe -- is waivable only when the lane's seal came after
# the commit (the seal then recorded it).
CONTROL = ["*/.abandoned/*", "*/ABANDONED.json", "*/.lane-seals/*", "*/.lane-auth/*", "*/.reissued/*",
           "*/.superseded/*", "stops/*", "waivers/*", "resolutions/*", "*/ADOPTED.md", "*/TARGET.json",
           "*/FINGERPRINTS.json", "*/INFORMAL.json", "*/SIGNOFF.json", "APPROVED_FINGERPRINTS*.json", "acknowledgments/*",
           "REAPPROVAL*.json", PIN, "readers/*", "KNOWN_FAULTS-*.md", "pdf/*"]


def unwaivable(audits, rounds_dir, commit, files):
    """[why] for each file of an add-only commit no waiver may cover (CONTROL; lane evidence the
    lane's seal did not record)."""
    import lane_auth
    out = []
    for f in files:
        rel = os.path.relpath(os.path.join(audits, f), rounds_dir)
        if rel.startswith(".."):
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in CONTROL):
            out.append(f"{rel} is a record another check reads as control data")
            continue
        m = re.match(r"^(.*?)\.probes/", rel)
        lane = (m.group(1) + ".json") if m else (rel if fnmatch.fnmatch(rel, "*/*.json") else None)
        if lane is None:
            continue
        v = os.path.join(rounds_dir, lane)
        try:
            sealed = lane_auth.committed_at(lane_auth.audit_repo(lane_auth.Path(rounds_dir)), lane_auth.locations(v)[3])
        except (lane_auth.AuthError, ValueError):
            sealed = None
        before = bool(sealed) and sealed != commit and not git(audits, "merge-base", "--is-ancestor", commit, sealed)[0]
        if not before:
            out.append(f"{rel} is lane evidence its lane's seal did not record (not sealed after this commit)")
    return out


def waiver_problem(audits, rounds_dir, commit, stop, files, others=()):
    """Why the human's stop `stop` cannot waive the ownership FAIL of `commit`, or None (ROUND3 M3): the
    stop was closed by the human; it recorded the integrity check failing with FAIL[ownership] for THIS
    commit; no other waiver uses it; the commit only ADDED files, none of them control data."""
    import stops
    sd = os.path.join(rounds_dir, stops.STOPS, str(stop))
    c = stops.load(os.path.join(sd, "CLOSED.json")) or {}
    d = stops.load(os.path.join(sd, "STOP.json")) or {}
    for f in ("STOP.json", "CLOSED.json"):
        q = os.path.relpath(os.path.join(sd, f), audits)
        if os.path.exists(os.path.join(sd, f)) and (not git(audits, "log", "-1", "--format=%H", "--", q)[1].strip()
                                                    or git(audits, "status", "--porcelain", "--", q)[1].strip()):
            # an uncommitted (or changed) stop record is no stop: its evidence was never re-run (R3c N3)
            return (f"stop {stop}'s {f} is not committed as written by stops.py: complete the stop first "
                    f"(stops.py open/close re-runs an interrupted one)")
    if c.get("by") != "human":
        return (f"stop {stop} is not closed by the human: a waiver is the human's decision at every level "
                f"(record the stop, show them the FAIL, close it with --human)")
    if stop in others:
        return f"stop {stop} already backs another waiver: one waiver per stop"
    own = [l for l in str(d.get("output") or "").splitlines() if "FAIL[ownership]" in l and commit[:11] in l]
    if "integrity.py" not in str(d.get("command") or "") or not own:
        return (f"stop {stop} is not about the ownership FAIL of {commit[:11]}: record the stop with "
                f"`stops.py open --cmd \"python3 audits/integrity.py --check\"` while it prints FAIL[ownership] "
                f"for that commit, show the human, close it with --human")
    if files is None:
        return (f"commit {commit[:11]} changed or deleted a committed file: only a commit that ADDED files "
                f"is ever waived (restore the record instead)")
    nw = unwaivable(audits, rounds_dir, commit, files)
    if nw:
        return f"commit {commit[:11]} is never waived: " + "; ".join(nw[:3])
    return None


def waivers(audits, rounds_dir, cfg):
    """({commit: why} of the valid human waivers of an ownership FAIL, [problem]) (RULINGS A5b): a
    waiver is valid only for a commit that ADDED files, never one that changed or deleted a record,
    and only on a stop the human closed."""
    import stops
    ok, probs, used = {}, [], []
    for p in sorted(glob.glob(os.path.join(rounds_dir, WAIVERS, "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            probs.append(f"{os.path.relpath(p, rounds_dir)} is not readable"); continue
        c = stops.load(os.path.join(rounds_dir, stops.STOPS, str(d.get("stop")), "CLOSED.json")) or {}
        cm = str(d.get("commit"))
        why = waiver_problem(audits, rounds_dir, cm, str(d.get("stop")), added_only(audits, cm), used)
        used.append(str(d.get("stop")))
        if why:
            probs.append(f"{os.path.relpath(p, rounds_dir)}: {why}")
        else:
            ok[cm] = f"stop {d['stop']}: \"{c.get('text', '')[:80]}\""
    return ok, probs


def acknowledge(audits, rounds_dir, cfg, commit, stop):
    """Record the human's waiver of the ownership FAIL of `commit` (integrity.py --acknowledge),
    committed as "ack <commit>". Returns the waiver's path."""
    import stops, datetime
    if project.mode(cfg) == "release":
        # RELEASE-SWEEP I9: the human's waiver is a dev route; release acknowledges a history fault after a fresh
        # reviewer's judgement (--ack-request), never by waiting for the human
        raise ValueError("--acknowledge (the human's waiver) is dev mode only; in release a history FAIL no cure clears "
                         "is acknowledged after a fresh review: python3 audits/integrity.py --ack-request --diagnosis "
                         "\"...\" (never a human stop)")
    rc, full = git(audits, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    full = full.strip()
    if rc != 0 or not full:
        raise ValueError(f"no commit {commit!r} in the audit record")
    files = added_only(audits, full)
    p = os.path.join(rounds_dir, WAIVERS, full + ".json")
    if os.path.exists(p):
        if git(audits, "log", "-1", "--format=%H", "--", os.path.relpath(p, audits))[1].strip():
            raise ValueError(f"commit {full[:11]} is already waived")
        # an --acknowledge killed between writing the waiver and committing it (ROUND3 L1): the
        # uncommitted file has no standing; it is written again below
        os.remove(p)
    others = []
    for q in glob.glob(os.path.join(rounds_dir, WAIVERS, "*.json")):
        try:
            others.append(str(json.load(open(q, encoding="utf-8")).get("stop")))
        except (OSError, ValueError):
            pass
    why = waiver_problem(audits, rounds_dir, full, str(stop), files, others)
    if why:
        raise ValueError(why)
    c = stops.load(os.path.join(rounds_dir, stops.STOPS, str(stop), "CLOSED.json")) or {}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    rc, subj = git(audits, "log", "-1", "--format=%s", full)
    json.dump({"commit": full, "subject": subj.strip(), "files": files, "stop": stop, "answer": c.get("text", ""),
               "date": datetime.date.today().isoformat()}, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
    try:
        project.commit_only([p], f"ack {full[:11]}", repo=audits)
    except ValueError:
        os.remove(p)
        raise
    return p


def waiver_rows(cfg, rounds_dir=None):
    """[(commit, its subject, files it added, stop, the human's answer)] for the report's summary page."""
    rounds_dir = rounds_dir or os.path.join(project.REPO, cfg["rounds_dir"])
    out = []
    for p in sorted(glob.glob(os.path.join(rounds_dir, WAIVERS, "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append((str(d.get("commit", ""))[:11], d.get("subject", ""), ", ".join(d.get("files") or []),
                    d.get("stop", ""), d.get("answer", "")))
    return out


# --- the reviewed acknowledgment of a history fault (release; SWEEP-FIX D2, approver 2026-10-25) ---------------------
# Some FAILs live in the committed history, and no restore clears them: a past plain re-pin that changed the tooling,
# a pin committed under a mistyped subject, an owner that later re-committed a hand-edited record (so `stops.py
# revert` refuses), a `Revert ...` that is no exact inverse, an owner-committed [set-aside-changed] or
# [record-fix-diff], a tool-patch link that cannot be verified, a damaged stop trail. In release such a line is
# never a human stop: the operator diagnoses it, a FRESH reviewer (the tool-patch reviewer rule: never the
# operator, a lane, an adjudicator, or an agent id sealed anywhere else in the run) judges that every line is
# bookkeeping and none hides a change to a statement, a proof, a verdict, an adjudication, an approval or a check,
# and only then does check() turn EXACTLY those lines into NOTE[acknowledged-fault]. Any other or new line stays
# FAIL and needs its own acknowledgment. Code records the lines and the facts of every commit they name; the agent
# judges. The validation lives here, in the proof-validity core, so no tool patch can weaken it. RUN_RECORD.md
# lists each acknowledgment (only there: approver 2026-10-26). Dev mode: refused (every stop
# waits for the human there).
ACKS = "acknowledgments"            # <rounds dir>/acknowledgments/AK<k>/: REQUEST.json, prompt.txt, review.json, seals
AK_RE = re.compile(r"^AK([1-9]\d*)$")
ACKABLE = ("pin", "ownership", "tool-patch", "set-aside-changed", "record-fix-diff", "stop-trail", "waiver")
ACK_VERDICT = "review.json"
# never acknowledged, whatever the code (coordinator 2026-10-26): a line naming a file of the proof-validity core (a
# fault there is stops.py core-fault's, or a restore), or a record of the statement freeze (the approvals, a round's
# fingerprints): those are proof/freeze faults, never bookkeeping
NEVER_ACK_RE = re.compile(r"(?:^|[\s`'\"(/])(?:phase0\.py|axiom_sweep[\w.]*|fingerprint\.py|fingerprint_tail\.lean|"
                          r"olean_parts\.lean|tool_patch\.py|integrity\.py|APPROVED_FINGERPRINTS[\w.]*|REAPPROVAL[\w.]*|"
                          r"FINGERPRINTS\.json|SIGNOFF\.json|INFORMAL\.json|STATEMENTS_BUNDLE\.md|TARGET\.json|ADOPTED\.md|"
                          r"DEVIATIONS\.md|VACUOUS\.md|PAPER_DEFECTS\.md|SKIPPED\.md)(?![\w.])")
# SWEEP-FIX review H2(a): a record that carries a judgement -- a lane's verdict or probe, a re-vote, an adjudication, an
# approval or sign-off, a scope, a reader fix or record fix, an escalation's answer -- is never acknowledged, whatever
# its file name: it keeps its real cure (revert, restore, record-fix, a new adjudication)
JUDGEMENT_OWNERS = ("adjudicate ", "seal ", "signoff ", "approve", "scope ", "reader-fix ", "record-fix ", "escalate ",
                    "round-cap ", "stop ")     # review M8: open findings at the cap; the human's answers in CLOSED.json


def _fault_paths(line):
    """The part of a FAIL line that names the faulty thing (review M4: never a quoted commit subject, never the advice):
    for [ownership] and [set-aside-changed] the record's path; otherwise the line before its first "; " with every
    quoted string removed."""
    l = ack_line(line)
    m = re.match(r"^\[(?:ownership|set-aside-changed)\] (\S+) was ", l)
    if m:
        return m.group(1)
    return re.sub(r'"[^"]*"', '""', l.split("; ", 1)[0])


def ackable(line, version=OWNERSHIP):
    """Is a check() FAIL line one a reviewed acknowledgment may cover: a history code (ACKABLE) whose faulty thing is
    no proof-validity core file, no record of the statement freeze, and no record that carries a judgement
    (JUDGEMENT_OWNERS). A past re-pin's line (`[pin] re-pin <hash> ... changed the tooling (<file>)`) may name a core
    file it changed: like every [pin] line it is acknowledged only while the tooling in force is a trusted pin's
    (tooling_trusted, checked at the request and at every check), so no unreviewed change is in force."""
    if ack_code(line) not in ACKABLE:
        return False
    rp = ack_code(line) == "pin" and ack_line(line).startswith("[pin] re-pin ") and "changed the tooling" in line
    head = _fault_paths(line)
    if not rp and NEVER_ACK_RE.search(" " + head):
        return False
    if ack_code(line) in ("ownership", "set-aside-changed"):
        need = owner(head, version) or ()
        if set(need) & set(JUDGEMENT_OWNERS) or re.search(r"(?:^|/)\d{4}-\d{2}-\d{2}-[^/]+/", head):
            return False        # a round's files (lane verdicts, probes, re-votes, its scope and adjudication)
    return True


ACK_HASH_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{11,40}(?![0-9a-f])")
ACK_PROMPT = """You are a FRESH reviewer of a release run of formalize-paper. You are not the operator, a review lane or
the adjudicator, and you have not seen this run. One question, about the run's RECORD (its git history), not about
mathematics.

The run's integrity check (audits/integrity.py --check) prints the failure lines below. Each concerns the HISTORY of
the run's records or tooling: commits already made, which no restore can undo. The operator asks to acknowledge
exactly these lines: the run then goes on and is delivered with them listed in RUN_RECORD.md (the maintainers'
record; the author's summary and report do not mention them). Decide whether EVERY line is a bookkeeping or mechanical
fault -- an interrupted or mis-ordered step; a re-pin made the wrong way or under a wrong subject ONLY when the facts
below show the tooling it pinned equals a trusted pin's (code checked that the tooling in force does); a bookkeeping
record committed by the wrong step that changes nothing the run judges -- and NONE hides a change to what the run claims:
an approved statement, a proof, a lane's verdict or probe, an adjudication (ADOPTED.md, PAPER_DEFECTS.md, SKIPPED.md,
VACUOUS.md, DEVIATIONS.md, INFORMAL.json, SIGNOFF.json), an approval, a set-aside, or an audit tool that judges them,
made by someone other than its owner or without the review it needed. A tooling change that was never reviewed and
is still in force is never bookkeeping.

Inspect the commits yourself, read-only (git show, git log, git diff in {audits}); change nothing.

The request (read it in full): {request} (sha256 {request_sha256}).

The operator's diagnosis: {diagnosis}

The lines:
{lines}

Facts recorded by code, for each commit a line names (its full diff), and for each tool patch a line names (the files
its apply commit changed):
{facts}

Earlier requests on any of these lines that were rejected or never sealed (weigh their findings):
{earlier}

Write this JSON object, and nothing else, to {verdict}:
{{"lane_token": "<your lane_token>", "verdict": "approve" or "reject", "request_sha256": "{request_sha256}",
 "reason": "<one paragraph: for each line, what its commit did and why it is (or is not) bookkeeping>"}}
Approve only if you are sure; when in doubt, reject: a rejection costs the run another request or another cure,
never a stop.
If your write of {verdict} is refused (some hosts refuse a subagent's file writes), do not look for another way to
write it: return it. Its delimiter is `RETURNED_` and the first 12 hex digits of your lane_token; check that no line of
the object equals it. Hash the object with `sha256sum <<'<delimiter>'`, the object, then a line `<delimiter>` (this
writes no file; the digest covers the object and one final newline), and end your final message with a line
`BEGIN RETURNED FILE {verdict} <delimiter>`, the same object, a line `END RETURNED FILE`, and then the LANE_COMPLETION line with
that sha256. The operator saves the object verbatim to {verdict}; it is sealed only if its sha256 is the one you
returned.
"""


def ack_line(msg):
    """The normalised "[code] text" of a check() message (whitespace collapsed): what an acknowledgment names."""
    return " ".join(str(msg or "").split())


def ack_code(msg):
    m = re.match(r"^\[([a-z0-9-]+)\] ", str(msg or ""))
    return m.group(1) if m else None


def ack_ids(rounds_dir):
    d = os.path.join(rounds_dir, ACKS)
    return sorted(int(AK_RE.match(x).group(1)) for x in (os.listdir(d) if os.path.isdir(d) else []) if AK_RE.match(x))


def _load_json(p):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _committed_once(audits, path, subject):
    """None when `path` was committed exactly once, under `subject`, and is unchanged on disk; else why not."""
    rel = os.path.relpath(path, audits)
    subj = git(audits, "log", "--format=%s", "--", rel)[1].splitlines()
    dirty = git(audits, "status", "--porcelain", "--", rel)[1].strip()
    if not os.path.isfile(path) or subj != [subject] or dirty:
        return f"{rel} is not committed once, as \"{subject}\", and unchanged (found {subj[:3]}{', changed' if dirty else ''})"
    return None


def ack_problem(audits, rounds_dir, k):
    """(why AK<k> does not acknowledge anything, or None; its request; its verdict; its seal). Valid: a release run
    (by its FIRST pin); REQUEST.json, the prompt and the token commitment committed once by "acknowledge AK<k>
    request" and unchanged; the review authenticated and sealed (lane_auth.validate); the reviewer's agent id sealed
    nothing else in the run; the verdict approves this request's sha256; every line of an acknowledgeable code."""
    import lane_auth, tool_patch
    ak = f"AK{k}"
    d = os.path.join(rounds_dir, ACKS, ak)
    req = _load_json(os.path.join(d, "REQUEST.json"))
    fp = project.first_pin(rounds_dir) or {}
    if project.mode(fp.get("config") or {}) != "release":
        return "the run is not a release run (its first pin): a history fault waits for the human in dev", req, None, None
    want = f"acknowledge {ak} request"
    for f in ("REQUEST.json", "prompt.txt", os.path.join(".lane-auth", ACK_VERDICT)):
        why = _committed_once(audits, os.path.join(d, f), want)
        if why:
            return why, req, None, None
    if not req or not isinstance(req.get("lines"), list) or not req["lines"] \
            or any(not isinstance(x, str) or not ackable(x) for x in req["lines"]):
        return "its REQUEST.json names no lines, or a line of a code that is never acknowledged", req, None, None
    v = os.path.join(d, ACK_VERDICT)
    probs = lane_auth.validate(v) if os.path.exists(v) else [f"{ak}/{ACK_VERDICT} was never returned"]
    if probs:
        return f"its review is not sealed or does not authenticate ({probs[0]})", req, None, None
    vd = _load_json(v) or {}
    sl = _load_json(os.path.join(d, ".lane-seals", ACK_VERDICT)) or {}
    if vd.get("request_sha256") != hashlib.sha256(open(os.path.join(d, "REQUEST.json"), "rb").read()).hexdigest():
        return "its review judges another request (request_sha256)", req, vd, sl
    agent = str(sl.get("agent_id") or "")
    mine = os.path.join(ACKS, ak, ".lane-seals", ACK_VERDICT)
    others = [x for x in tool_patch.all_agent_ids(rounds_dir).get(agent, []) if os.path.normpath(x) != mine]
    if not agent or others:
        return (f"its reviewer's agent id {agent or '(none)'} also sealed {others[0] if others else '?'}: the reviewer "
                f"must be fresh"), req, vd, sl
    if vd.get("verdict") != "approve":
        return f"its reviewer rejected it: {' '.join(str(vd.get('reason', '')).split())[:400]}", req, vd, sl
    return None, req, vd, sl


def acknowledgments(audits, rounds_dir):
    """[{ak, date, lines, diagnosis, verdict, reason, reviewer, valid, why}] of every acknowledgment request of the
    run, in order (RUN_RECORD.md lists them; `acknowledged` uses the valid ones)."""
    out = []
    for k in ack_ids(rounds_dir):
        try:
            why, req, vd, sl = ack_problem(audits, rounds_dir, k)
        except Exception as e:      # noqa: BLE001 -- fail closed: an unreadable acknowledgment acknowledges nothing
            why, req, vd, sl = f"it cannot be read: {e!r}", None, None, None
        out.append({"ak": f"AK{k}", "date": (req or {}).get("date"), "lines": list((req or {}).get("lines") or []),
                    "diagnosis": (req or {}).get("diagnosis", ""), "verdict": (vd or {}).get("verdict"),
                    "reason": " ".join(str((vd or {}).get("reason", "")).split()),
                    "reviewer": (sl or {}).get("agent_id"), "valid": why is None, "why": why})
    return out


def acknowledged(audits, rounds_dir):
    """{normalised line: AK<k>} of every line a valid acknowledgment names."""
    out = {}
    for a in acknowledgments(audits, rounds_dir):
        if a["valid"]:
            for l in a["lines"]:
                out.setdefault(ack_line(l), a["ak"])
    return out


def _trusted_pins(audits, rounds_dir, untrusted=()):
    """The audits commits of the run's trusted pins: its first (the oldest pin commit) and every tool-patch pin
    "pin (tool-patch TP<k>)" whose link verifies (review M1: a TP in `untrusted` -- one check() prints a FAIL[tool-patch]
    for -- is not trusted)."""
    rel = os.path.relpath(os.path.join(rounds_dir, PIN), audits)
    out = []
    for i, line in enumerate(git(audits, "log", "--reverse", "--format=%H %s", "--", rel)[1].splitlines()):
        h, _, subj = line.partition(" ")
        m = re.match(r"^pin \(tool-patch (TP[1-9]\d*)\)$", subj)
        if i == 0 or (m and m.group(1) not in untrusted):
            try:
                out.append(json.loads(git(audits, "show", f"{h}:./{rel}")[1])["audits_commit"])
            except (ValueError, KeyError, TypeError):
                continue
    return out


def _untrusted_tps(res):
    """The tool patches check()'s result `res` prints a FAIL[tool-patch] for (their link does not verify)."""
    return {m_.group(1) for s, m in res if s == "FAIL" and ack_code(m) == "tool-patch"
            for m_ in [re.search(r"\b(TP[1-9]\d*)\b", m)] if m_}


def tooling_trusted(audits, rounds_dir, res=()):
    """Is the tooling in force (committed and on disk) a trusted pin's (_trusted_pins)? Review B1: no [pin] line is
    acknowledged otherwise, at the request or at any later check."""
    if tooling_dirty(audits):
        return False
    return any(not git(audits, "diff", "--name-only", t, "--", *TOOLING_PATHSPECS)[1].strip()
               for t in _trusted_pins(audits, rounds_dir, _untrusted_tps(res)))


def _tp_files(audits, tp):
    """The files the apply commit of tool patch `tp` changed ([] when there is none)."""
    rc, h = git(audits, "log", "-1", "--format=%H", f"--grep=^tool-patch {tp} apply$")
    return sorted(changed_files(audits, h.strip()) or []) if h.strip() else []


def _core_set(audits, rounds_dir):
    try:
        import tool_patch
        return set(tool_patch.core_files(audits, rounds_dir))
    except Exception:       # noqa: BLE001 -- no first pin: this file's own list
        import tool_patch
        return set(tool_patch.CORE)


def _cure_attempted(rounds_dir, line):
    """Review H2(b): a FAIL line with a printed cure ([ownership]: stops.py revert) is acknowledged only after that cure
    was tried and failed: a failed cure attempt (stops/S<n>/CURE<k>.json) of a stop on integrity.py --check whose re-run
    still printed the line's commit. Codes with no cure in the history (a past pin, a set-aside or record-fix commit,
    an unverifiable link, the stop trail, a waiver) need none."""
    if ack_code(line) != "ownership":
        return True
    hs = [m.group(0) for m in ACK_HASH_RE.finditer(line)]
    for p in glob.glob(os.path.join(rounds_dir, "stops", "S*", "CURE*.json")):
        d = _load_json(p) or {}
        if "integrity.py" in str(d.get("check")) and any(h[:11] in str((d.get("rerun") or {}).get("output_tail")) for h in hs):
            return True
    return False


def ack_request(audits, cfg, rounds_dir, rounds_rel, diagnosis, agent_file=AGENT_FILE, repo=None):
    """`integrity.py --ack-request --diagnosis TEXT`: record the request of a reviewed acknowledgment of every
    acknowledgeable FAIL line check() prints now, with the facts of each commit a line names, and issue its fresh
    reviewer. Returns (request path, spawn line, lines). ValueError when it does not apply."""
    import lane_auth, secrets
    fp = project.first_pin(rounds_dir) or {}
    if project.mode(cfg) != "release" or project.mode(fp.get("config") or {}) != "release":
        raise ValueError("--ack-request is release mode only; in dev mode a history fault waits for the human")
    diag = " ".join(str(diagnosis or "").split())
    if not diag:
        raise ValueError("--diagnosis is required: what happened in each commit the lines name, why no restore or "
                         "revert clears it, and why no statement, proof, verdict, adjudication, approval or check "
                         "was changed by it")
    res = check(audits, cfg, None, agent_file=agent_file, rounds_dir=rounds_dir, rounds_rel=rounds_rel, repo=repo)
    lines = sorted({ack_line(m) for s, m in res if s == "FAIL" and ackable(m)})
    if not lines:
        raise ValueError("integrity.py --check prints no FAIL of a history code (" + ", ".join(ACKABLE) + ") that "
                         "names no proof-validity core file and no approval record: nothing to acknowledge; cure the "
                         "other FAILs as their codes say (a core-file fault: stops.py core-fault)")
    if any(ack_code(l) == "pin" for l in lines):
        # review B1: a fact, checked by code, for EVERY [pin] line: the tooling now in force is a trusted pin's (the
        # first, or a tool patch's whose link verifies)
        if not tooling_trusted(audits, rounds_dir, res):
            first = (_trusted_pins(audits, rounds_dir) or ["<first pin commit>"])[0]
            raise ValueError(f"a [pin] line names a pin of the history, and the tooling now is no trusted pin's (the "
                             f"first pin's, or a verified tool patch's): restore it first (git -C audits checkout {first} -- <the changed "
                             f"files>; commit; python3 audits/integrity.py --pin --repin \"restore the pinned tooling\"), "
                             f"then request the acknowledgment of the history line")
    nocure = [l for l in lines if not _cure_attempted(rounds_dir, l)]
    if nocure:
        raise ValueError(f"the printed cure was not tried for {nocure[0][:160]}: try it first (an ownership FAIL: "
                         f"python3 audits/stops.py revert --stop S<n> --commit <commit>, then close --cured, which "
                         f"records the failed attempt); only a fault no cure clears is acknowledged")
    core_, tps_ = _core_set(audits, rounds_dir), []
    for l in lines:
        m_ = re.match(r"^\[tool-patch\] (TP[1-9]\d*)\b", l)
        if m_:
            fs_ = _tp_files(audits, m_.group(1))
            hit = [f for f in fs_ if os.path.basename(f) in core_]
            if hit:
                raise ValueError(f"{m_.group(1)}'s apply commit changed {hit[0]}, a file of the proof-validity core: "
                                 f"never acknowledged (restore the tooling of the pin before it)")
            tps_.append({"tool_patch": m_.group(1), "files": fs_})
    facts = []
    for h in sorted({m.group(0) for l in lines for m in ACK_HASH_RE.finditer(l)}):
        rc, full = git(audits, "rev-parse", "--verify", "-q", f"{h}^{{commit}}")
        if rc or not full.strip():
            continue
        full = full.strip()
        subj = git(audits, "log", "-1", "--format=%s", full)[1].strip()
        diff = git(audits, "show", "--format=", "--no-color", full)[1].splitlines()
        facts.append({"commit": full, "subject": subj,
                      "stat": diff[:400] + ([f"... ({len(diff) - 400} more lines: git show {full[:11]})"]
                                            if len(diff) > 400 else [])})
    facts += tps_
    earlier = []
    for a in acknowledgments(audits, rounds_dir):
        if not a["valid"] and set(map(ack_line, a["lines"])) & set(lines):
            earlier.append({"ak": a["ak"], "verdict": a["verdict"] or "never sealed", "reason": a["reason"] or a["why"]})
    k = 1 + max(ack_ids(rounds_dir) or [0])
    ak = f"AK{k}"
    d = os.path.join(rounds_dir, ACKS, ak)
    os.makedirs(os.path.join(d, ".lane-auth"), exist_ok=True)
    req_p, pp, cp = os.path.join(d, "REQUEST.json"), os.path.join(d, "prompt.txt"), os.path.join(d, ".lane-auth", ACK_VERDICT)
    rec = {"ak": ak, "date": datetime.date.today().isoformat(), "mode": "release", "diagnosis": diag, "lines": lines,
           "facts": facts, "earlier": earlier}
    json.dump(rec, open(req_p, "w", encoding="utf-8"), indent=1, sort_keys=True, ensure_ascii=False)
    rs = hashlib.sha256(open(req_p, "rb").read()).hexdigest()
    fact_txt = "\n".join((f"- {f['commit'][:11]} \"{f['subject']}\":\n" + "\n".join(f"    {s}" for s in f["stat"]))
                         if "commit" in f else f"- tool patch {f['tool_patch']}: its apply commit changed "
                         + (", ".join(f["files"]) or "(no apply commit)") for f in facts) or "- (no commit is named)"
    open(pp, "w", encoding="utf-8").write(ACK_PROMPT.format(
        audits=os.path.abspath(audits), request=os.path.abspath(req_p), request_sha256=rs, diagnosis=diag,
        lines="\n".join(f"- {l}" for l in lines), facts=fact_txt,
        earlier="\n".join(f"- {e['ak']} ({e['verdict']}): {e['reason']}" for e in earlier) or "- none",
        verdict=os.path.abspath(os.path.join(d, ACK_VERDICT))))
    token = secrets.token_hex(32)
    json.dump({"verdict": ACK_VERDICT, "token_sha256": lane_auth.sha(token.encode()), "prompt": os.path.abspath(pp),
               "prompt_sha256": lane_auth.sha(open(pp, "rb").read())}, open(cp, "w", encoding="utf-8"),
              sort_keys=True, indent=2)
    open(cp, "a", encoding="utf-8").write("\n")
    try:
        project.commit_only([req_p, pp, cp], f"acknowledge {ak} request", repo=audits)
    except ValueError:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return req_p, lane_auth.spawn_line(os.path.abspath(pp), token), lines


def acknowledge_lines(audits, rounds_dir, out):
    """check()'s result with every FAIL line a valid acknowledgment names turned into NOTE[acknowledged-fault]."""
    try:
        acked = acknowledged(audits, rounds_dir)
    except Exception as e:      # noqa: BLE001 -- fail closed: nothing acknowledged, said
        return out + [("note", f"[acknowledged-fault] the acknowledgments could not be read ({e!r}): none applied")]
    if not acked:
        return out
    # review B1: a [pin] line stays FAIL while the tooling in force is no trusted pin's, whatever was acknowledged
    pin_ok = not any(ack_code(l) == "pin" for l in acked) or tooling_trusted(audits, rounds_dir, out)
    acked = {l: a for l, a in acked.items() if ack_code(l) != "pin" or pin_ok}
    return [("note", f"[acknowledged-fault] {ack_line(m)[len(ack_code(m)) + 3:]} (acknowledged after a fresh review: "
                     f"{acked[ack_line(m)]}; RUN_RECORD.md lists it)")
            if s == "FAIL" and ackable(m) and ack_line(m) in acked else (s, m) for s, m in out]


def adjudication_paths(audits, rounds_dir, rounds_rel, round_name, version=OWNERSHIP):
    """The files an adjudication of `round_name` commits, found from OWNERS: the round's ADOPTED.md
    and every top-level record the adjudicator owns that it changed (PAPER_DEFECTS.md, SKIPPED.md,
    VACUOUS.md); under ownership 1 also the round's lane files. Listed by name: nothing the
    adjudicator does not own is ever swept into its commit (RULINGS A5)."""
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all", "--", rounds_rel)
    out = []
    for line in st.splitlines():
        rel = os.path.relpath(line[3:].strip().strip('"'), rounds_rel)
        need = owner(rel, version)
        if need and "adjudicate " in need and (rel.startswith(round_name + "/") or "/" not in rel):
            out.append(os.path.join(rounds_dir, rel))
    return sorted(out)


def commit_adjudication(audits, rounds_dir, rounds_rel, round_name, revotes=False, cfg=None):
    """Commit the adjudication of `round_name` by name ("adjudicate R", or "adjudicate R revotes"
    for the re-vote adjudication). Returns (commit, [paths]); raises ValueError. With the project's
    `cfg` it first refuses a record that cites what does not exist (a witness cell naming `sorry` or a
    lane's scratch lemma: the release trial's S1), so the adjudicator corrects it in its own turn."""
    if not round_name or not project.ROUND_RE.match(round_name):
        raise ValueError(f"{round_name!r} is not a round name")
    adopted = os.path.join(rounds_dir, round_name, "ADOPTED.md")
    if not os.path.exists(adopted):
        raise ValueError(f"no {os.path.relpath(adopted, audits)}: write the decisions first")
    import lanecheck
    # every NOTE the lanes raised is settled in ADOPTED.md (a clearance, a re-vote, LEFT OPEN), and
    # every item a set-aside carried forward has a row (RULINGS A1 condition 1, A7 condition 4)
    unsettled = lanecheck.settle_problems(os.path.join(rounds_dir, round_name), revotes=bool(revotes)) + \
        lanecheck.carried_problems(rounds_dir, round_name, revotes=bool(revotes))
    if unsettled:
        raise ValueError("the adjudication does not settle every lane NOTE or carried item:\n  "
                         + "\n  ".join(unsettled))
    if cfg is not None:
        # every adjudicator-owned record fault (Phase 0's PENDING[adjudication] lines: a dead witness or
        # citation, a cell count, a "decided by", a prose-only defect, a carried item without its row, a
        # result left unproved without its SKIPPED.md row) is cleared by THIS adjudication, never left for
        # a check that only the next adjudication could satisfy (deadlock sweep D1-D3)
        import make_report
        found = make_report.adjudication_findings(cfg, round_name, revotes=bool(revotes))
        if found:
            raise ValueError("an adjudicator-owned record is faulty; clear every line below in this adjudication "
                             "(a witness names the declaration that states the defect, never `sorry` or a lemma "
                             "in a lane's probe file; a literal `|` in a cell is `\\|`; AUDIT_PROTOCOL.md step H), "
                             "then commit again:\n  "
                             + "\n  ".join(make_report.pending_line(f) for f in found))
    paths = adjudication_paths(audits, rounds_dir, rounds_rel, round_name, pinned_version(rounds_dir))
    if adopted not in paths:
        raise ValueError(f"{os.path.relpath(adopted, audits)} is unchanged since its last commit: nothing "
                         f"of this adjudication to commit")
    subject = f"adjudicate {round_name}" + (" revotes" if revotes else "")
    return project.commit_only(paths, subject, repo=audits), paths


# --- record correction (RUN.md failure table, record-fix; AUDIT_PROTOCOL.md "Record correction") ------
# A fault of class record-fix (dead-witness, record-cite) in an adjudicator's record is cured by a fresh
# adjudicator that edits ONLY the cells holding the faulty name, committed as "record-fix R". A cell of
# a protected column (a verdict, a decision, a severity, a defect's status or repair, who decided) never changes: a fault
# there takes a new round.
# DEVIATIONS.md too: record_faults names its faults only when it is the adjudicator's (ownership 3), and an edit
# must change a faulty name of a faulty row, so the operator's own DEVIATIONS.md is never corrected this way
FIX_RECORDS = ("PAPER_DEFECTS.md", "SKIPPED.md", "VACUOUS.md", "DEVIATIONS.md")
PROTECTED_COLS = ("#", "result", "kind", "severity", "repair", "decision", "decided by", "status", "verdict", "found", "what the paper says",
                  # which result a row is about, for which parameters, and what follows from it (re-check R1)
                  "where", "statement", "for which parameters", "consequence")
PROTECTED_EXACT = ("why", "parameters")      # VACUOUS.md's "why" (PAPER_DEFECTS' "why it is wrong" is not)


def _protected(h):
    return h in PROTECTED_EXACT or any(h == c or (c != "#" and h.startswith(c)) for c in PROTECTED_COLS)


_LOC = r"`?[\w/.-]+\.lean:\d+(?:\s*[-\u2013,]\s*:?\d+)*`?"
_NEW_NAME = r"`[A-Za-z_][A-Za-z0-9_'!?.\u2080-\u2089\u2090-\u209c]*`"
FAULT_LINE = re.compile(r"^fault: (\S+) \| (\S+) \| (.*?) \| (.*)$")
# the Lean commit whose declarations decided the faults (sweep D4): a later declaration of a cured name
# must not turn a valid correction into a tamper finding
LEAN_LINE = re.compile(r"^lean: ([0-9a-f]{7,40})$")


def _key(k):
    return " ".join(str(k).split())


def token_only(old, new, toks):
    """True iff cell `new` is cell `old` with each occurrence of a faulty token (backticked with its
    arguments; a file also bare; with a following `File.lean:N`) removed or replaced by one backticked
    identifier (with or without its `File.lean:N`), or by a `File.lean:N` alone; every other byte
    unchanged. A name is a fault only in backticks (the checks read only those), so the same word in
    plain text -- "proved sorry-free as `probe_x`" -- is not a token and stays as it is (sweep M2)."""
    units = []
    for t in toks:
        e = re.escape(t)
        units.append(r"`" + e + r"(?:[\s(][^`]*)?`")
        if t.endswith(".lean"):     # a file is cited bare too (File.lean:N names no project file)
            units.append(r"(?<![\w.`])" + e + r"(?![\w`])")
    loc = r"(?:\s*\(?" + _LOC + r"\)?)?"
    parts = re.split("(?:" + "|".join(units) + ")" + loc, old)
    if len(parts) == 1:
        return new == old
    repl = r"(?:" + _NEW_NAME + loc + r"|\(?" + _LOC + r"\)?)?"
    return re.fullmatch(repl.join(re.escape(x) for x in parts), new) is not None


def _rows(text):
    """[(line index, cells or None, header of its table)] of a record's lines."""
    out, head = [], None
    for i, line in enumerate(text.splitlines()):
        st = line.strip()
        if not st.startswith("|"):
            head = None
            out.append((i, None, None)); continue
        cells = project.split_row(st)
        if head is None:
            head = [c.strip("* ").lower() for c in cells]
            out.append((i, None, head)); continue
        out.append((i, None if all(set(c) <= set("-: ") for c in cells) else cells, head))
    return out


def record_fix_cells(old, new, faults=None):
    """([(row key, column)] the edit changed, [problem]) for an edit of a record: only cells of existing
    rows may change -- same lines, same rows, same cell counts, no protected column. With `faults`
    ([(row key, token)] of this record), also the content (re-check R1): a changed cell must be in a row
    whose key equals a fault's exactly, hold its token, and change only that token (token_only)."""
    a, b = old.splitlines(), new.splitlines()
    if len(a) != len(b):
        return [], [f"{len(b) - len(a):+d} line(s): a record correction adds or removes nothing"]
    ra, rb = _rows(old), _rows(new)
    cells, probs = [], []
    for (i, ca, ha), (_, cb, _h) in zip(ra, rb):
        if a[i] == b[i]:
            continue
        if ca is None or cb is None or len(ca) != len(cb) or ca[0] != cb[0]:
            probs.append(f"line {i + 1} is not a cell edit of an existing row: {b[i][:80]!r}")
            continue
        for j, (x, y) in enumerate(zip(ca, cb)):
            if x != y:
                col = ha[j] if ha and j < len(ha) else f"column {j + 1}"
                cells.append((ca[0], col))
                if _protected(col):
                    probs.append(f"row {ca[0]}: the {col!r} cell changed (a verdict, decision, status or what a "
                                 f"row is about never changes in a record correction: a new round)")
                elif faults is not None:
                    toks = [t for k, t in faults if _key(k) == _key(ca[0]) and t in x]
                    if not toks:
                        probs.append(f"row {ca[0]}: the {col!r} cell holds no faulty name; only a faulty cell "
                                     f"changes")
                    elif not token_only(x, y, toks):
                        probs.append(f"row {ca[0]}: the {col!r} cell changed more than its faulty name(s) "
                                     f"{', '.join('`' + t + '`' for t in toks)} (only they may be replaced by one "
                                     f"backticked name, or removed)")
    return cells, probs


def _git_text(audits, rev, path):
    rc, out = git(audits, "show", f"{rev}:{path}")
    return out if rc == 0 else ""


def commit_record_fix(audits, rounds_dir, rounds_rel, round_name, cfg):
    """Commit a record correction of round `round_name` as "record-fix R": the adjudicator's records
    changed only in cells that hold a name a record_faults() fault names, outside the protected
    columns, and no fault left afterwards. Returns (commit, [(file, row, column)]); raises ValueError."""
    import make_report
    if not round_name or not project.ROUND_RE.match(round_name):
        raise ValueError(f"{round_name!r} is not a round name")
    adopted_rel = f"{rounds_rel}/{round_name}/ADOPTED.md"
    if git(audits, "ls-files", "--error-unmatch", adopted_rel)[0]:
        raise ValueError(f"round {round_name} has no committed ADOPTED.md: a record correction follows an adjudication")
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all", "--", rounds_rel)
    changed = []
    for line in st.splitlines():
        rel = os.path.relpath(line[3:].strip().strip('"'), rounds_rel)
        if rel in FIX_RECORDS:
            changed.append(rel)
        elif owner(rel) is not None and not line.startswith("??"):
            raise ValueError(f"{rel} changed: a record correction changes only {', '.join(FIX_RECORDS)}")
    if not changed:
        raise ValueError("no record changed: nothing to correct")
    # the faults at HEAD, computed on the committed records (the same test as the failing check), against
    # the declarations of the Lean HEAD, which the commit stores (sweep D4)
    import make_report as _mr
    rc_l, lean = git(_mr.REPO, "rev-parse", "HEAD")
    lean = lean.strip() if rc_l == 0 else None
    before = _faults_at(audits, "HEAD", rounds_rel, cfg, lean)
    if not before:
        raise ValueError("the committed records have no record-fix fault: nothing a record correction may change")
    done, probs = [], []
    for f in changed:
        old = _git_text(audits, "HEAD", f"{rounds_rel}/{f}")
        new = open(os.path.join(rounds_dir, f), encoding="utf-8").read()
        cells, p_ = record_fix_cells(old, new, [(k, tok) for _c, ff, k, tok, _t in before if ff == f])
        probs += [f"{f}: {x}" for x in p_]
        done += [(f, key, col) for key, col in cells]
    after = _faults_at(audits, None, rounds_rel, cfg, lean, rounds_dir)
    probs += [f"still faulty: {t}" for _c, _f, _k, _tok, t in after]
    if probs:
        raise ValueError("not a record correction (fix the cells, or restore the records and run a new round "
                         "if more than a cell must change):\n  " + "\n  ".join(probs))
    # the faults it cures are stored with the commit: integrity --check re-verifies the edit against them
    msg = f"record-fix {round_name}\n\n" + "\n".join(sorted({f"fault: {c_} | {ff} | {_key(k)} | {tok}"
                                                             for c_, ff, k, tok, _t in before})) \
        + (f"\nlean: {lean}" if lean else "")
    h = project.commit_only([os.path.join(rounds_dir, f) for f in changed], msg, repo=audits)
    return h, done


def stored_faults(audits, h):
    """[(code, file, row key, token)] a "record-fix R" commit stores in its message (commit_record_fix)."""
    body = git(audits, "log", "-1", "--format=%b", h)[1]
    return [m.groups() for m in map(FAULT_LINE.match, body.splitlines()) if m]


def stored_lean(audits, h):
    """The Lean commit a "record-fix R" commit stores (its faults were decided at it), or None (older form)."""
    body = git(audits, "log", "-1", "--format=%b", h)[1]
    return next((m.group(1) for m in map(LEAN_LINE.match, body.splitlines()) if m), None)


def _faults_at(audits, rev, rounds_rel, cfg, lean_rev=None, rounds_dir=None):
    """make_report.record_faults on the records as committed at `rev` (None: as they are in `rounds_dir`),
    against the project's Lean files at commit `lean_rev` (sweep D4; None: as they are now). Raises
    ValueError when a Lean file of the project cannot be read at `lean_rev`."""
    import make_report
    tmp = tempfile.mkdtemp(prefix="recordfix-")
    keep = make_report.REPO
    try:
        rd = os.path.join(tmp, "records"); os.makedirs(rd)
        for f in FIX_RECORDS:
            if rev is None:
                p_ = os.path.join(rounds_dir, f)
                t = open(p_, encoding="utf-8").read() if os.path.exists(p_) else ""
            else:
                t = _git_text(audits, rev, f"{rounds_rel}/{f}")
            if t:
                open(os.path.join(rd, f), "w", encoding="utf-8").write(t)
        # the pin says whether DEVIATIONS.md is the adjudicator's (make_report.deviations_adjudicators)
        pin = (open(os.path.join(rounds_dir, PIN), encoding="utf-8").read()
               if rev is None and os.path.exists(os.path.join(rounds_dir, PIN))
               else _git_text(audits, rev or "HEAD", f"{rounds_rel}/{PIN}"))
        if pin:
            open(os.path.join(rd, PIN), "w", encoding="utf-8").write(pin)
        if lean_rev:
            ld = os.path.join(tmp, "lean")
            for rel in cfg.get("lean_files") or []:
                rc, t = git(keep, "show", f"{lean_rev}:./{rel}")
                if rc:
                    if git(keep, "cat-file", "-e", f"{lean_rev}^{{commit}}")[0]:
                        raise ValueError(f"the Lean commit {lean_rev[:11]} cannot be read")
                    continue        # a file the project did not have yet at that commit
                os.makedirs(os.path.dirname(os.path.join(ld, rel)) or ld, exist_ok=True)
                open(os.path.join(ld, rel), "w", encoding="utf-8").write(t)
            make_report.REPO = ld
        return make_report.record_faults(cfg, rd=rd)
    finally:
        make_report.REPO = keep
        shutil.rmtree(tmp, ignore_errors=True)


def record_fix_commits(audits, rounds_rel, cfg=None):
    """[(commit, round, date, [(file, row, column)], [problem])] of every "record-fix R" commit, oldest
    first: the cells it changed, and why it is not a record correction (integrity --check, the report).
    The content is re-verified (re-check R1): the commit must store the faults it cures, each a fault of
    the records at its parent (with `cfg`), and change only their tokens, in their rows (record_fix_cells)."""
    out = []
    for subject, files, h in reversed(history(audits, rounds_rel)):
        m = re.match(r"^record-fix (\S+)$", subject)
        if not subject.startswith("record-fix "):
            continue
        probs = [] if m and project.ROUND_RE.match(m.group(1)) else [f"subject {subject[:60]!r} names no round"]
        cells, faults = [], stored_faults(audits, h)
        if not faults:
            probs.append("it stores no fault it cures (a record correction is committed by integrity.py "
                         "--commit-record-fix, which stores them)")
        elif cfg is not None and cfg.get("lean_files") is not None:
            try:
                # against the declarations of the Lean commit it stores (sweep D4), never today's
                real = {(ff, _key(k), tok) for _c, ff, k, tok, _t in
                        _faults_at(audits, h + "^", rounds_rel, cfg, stored_lean(audits, h))}
            except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
                real, probs = None, probs + [f"its faults could not be recomputed: {e}"]
            if real is not None:
                probs += [f"{ff} row {k}: `{tok}` is not a fault of the records it corrected"
                          for _c, ff, k, tok in faults if (ff, _key(k), tok) not in real]
        for f in files:
            if f not in FIX_RECORDS:
                probs.append(f"{f} is not a record a correction may change")
                continue
            c_, p_ = record_fix_cells(_git_text(audits, h + "^", f"{rounds_rel}/{f}"),
                                      _git_text(audits, h, f"{rounds_rel}/{f}"),
                                      [(k, tok) for _c, ff, k, tok in faults if ff == f])
            cells += [(f, k, col) for k, col in c_]
            probs += [f"{f}: {x}" for x in p_]
        date = git(audits, "log", "-1", "--format=%cs", h)[1].strip()
        out.append((h, m.group(1) if m else "?", date, cells, probs))
    return out


# --- reader-fix round (B10; U2 §6.3, ADDENDUM N4) ---------------------------------------------------------
# A content finding of a fresh reader of the summary, the report or the decisions document is fixed in the
# adjudicator's records by an adjudicator-only FIX ROUND, never by the operator editing generated output. It is
# modelled on the record correction above, widened: the adjudicator may change any unprotected cell of an existing
# row of PAPER_DEFECTS/SKIPPED/VACUOUS/DEVIATIONS.md (never a status, decision, verdict, kind, or what a row is
# about: a new round), and the rows of the `## Hypotheses` and `## Readings` sections of the round's ADOPTED.md
# (U2 §2: the adjudicator's hypothesis and reading rows). `prompt.py 4 --round R --reader-fix` writes the prompt
# and commits it as "reader-fix-prompt R n"; `integrity.py --commit-reader-fix --round R` commits the edit as
# "reader-fix R n" with the prompt's sha256 (lanecheck --round R checks it against the committed prompt, §7f).
# At most READER_FIX_BUDGET per run; integrity --check re-verifies every one.
READER_FIX_RECORDS = ("PAPER_DEFECTS.md", "SKIPPED.md", "VACUOUS.md", "DEVIATIONS.md")
READER_FIX_SECTIONS = ("## Hypotheses", "## Readings")
READER_FIX_BUDGET = 2
READER_FIX_RE = re.compile(r"^reader-fix (\S+) ([1-9]\d*)$")
READER_FIX_PROMPT_RE = re.compile(r"^reader-fix-prompt (\S+) ([1-9]\d*)$")
PROMPT_SHA_LINE = re.compile(r"^prompt: ([0-9a-f]{64})$")


def reader_fix_prompt_rel(round_name, n):
    return f"{round_name}/prompts/adjudicator-readerfix-{n}.txt"


def _sections_only(old, new, sections=READER_FIX_SECTIONS):
    """[problem] unless `new` differs from `old` only inside the named `## ` sections (rows changed, added or
    removed there; every other line byte-identical and in place)."""
    def split(t):
        outside, cur = [], None
        for line in t.splitlines():
            if line.startswith("## "):
                cur = line.strip() if any(line.strip().startswith(s_) for s_ in sections) else None
                if cur is None:
                    outside.append(line)
                continue
            if cur is None:
                outside.append(line)
        return outside
    a, b = split(old), split(new)
    if a != b:
        diff = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        return [f"ADOPTED.md changed outside {' and '.join(sections)} (first at its line {diff + 1} outside them): "
                f"a reader fix changes only hypothesis and reading rows"]
    return []


def _deviation_cells(old, new):
    """[problem] of an edit of DEVIATIONS.md by a reader fix: only cells of existing rows, never #, result or kind."""
    a, b = old.splitlines(), new.splitlines()
    if len(a) != len(b):
        return [f"{len(b) - len(a):+d} line(s): a reader fix adds or removes no row"]
    out = []
    for (i, ca, ha), (_, cb, _h) in zip(_rows(old), _rows(new)):
        if a[i] == b[i]:
            continue
        if ca is None or cb is None or len(ca) != len(cb) or ca[0] != cb[0]:
            out.append(f"line {i + 1} is not a cell edit of an existing row")
            continue
        for j, (x, y) in enumerate(zip(ca, cb)):
            col = ha[j] if ha and j < len(ha) else f"column {j + 1}"
            if x != y and (col == "#" or col.startswith("result") or col.startswith("kind")):
                out.append(f"row {ca[0]}: the {col!r} cell changed (what the row is: a new round)")
    return out


def reader_fix_edit_problems(old, new, round_name):
    """[problem] of a reader-fix edit: {rel: text} before and after (rel relative to the rounds dir)."""
    probs = []
    for rel in sorted(set(old) | set(new)):
        a, b = old.get(rel, ""), new.get(rel, "")
        if a == b:
            continue
        if rel == "DEVIATIONS.md":
            # DEVIATIONS.md: any cell but the row's number, its result and its kind (what the row is: a reading
            # choice, a route change); same rows, same lines
            probs += [f"{rel}: {x}" for x in _deviation_cells(a, b)]
        elif rel in READER_FIX_RECORDS:
            _cells, p_ = record_fix_cells(a, b)
            probs += [f"{rel}: {x}" for x in p_]
        elif rel == f"{round_name}/ADOPTED.md":
            probs += _sections_only(a, b)
        else:
            probs.append(f"{rel} changed: a reader fix changes only {', '.join(READER_FIX_RECORDS)} and the "
                         f"{' / '.join(READER_FIX_SECTIONS)} rows of {round_name}/ADOPTED.md")
    return probs


def no_change_commits(audits, rounds_rel):
    """{commit} of the run's no-change reader fixes: an empty "reader-fix R n" commit (it touches no file, so the
    rounds dir's path-limited history misses it) whose body names this rounds dir (`rounds: <rel>`, written by
    commit_reader_fix when the adjudicator changed no record cell). Trial #9: a round that changes nothing is a
    valid outcome, counted toward the budget like any other."""
    rc, out = git(audits, "log", "--format=@@%H %s%n%b")
    found, cur = set(), None
    for line in out.splitlines() if rc == 0 else []:
        if line.startswith("@@"):
            h, _, subj = line[2:].partition(" ")
            cur = h if READER_FIX_RE.match(subj) else None
        elif cur and line.strip() == f"rounds: {rounds_rel}":
            if not git(audits, "diff-tree", "--no-commit-id", "--name-only", "-r", cur)[1].strip():
                found.add(cur)
    return found


def reader_fix_history(audits, rounds_rel):
    """([(commit, round, n, stored prompt sha)] of every "reader-fix R n" commit, oldest first (a no-change one
    included); {(round, n): commit} of every "reader-fix-prompt R n" commit)."""
    fixes, prompts = [], {}
    empty = no_change_commits(audits, rounds_rel)
    hist = history(audits, rounds_rel)
    if empty:
        rc, order = git(audits, "log", "--format=%H")
        rank = {h: i for i, h in enumerate(order.split())}
        hist = sorted(hist + [(git(audits, "log", "-1", "--format=%s", h)[1].strip(), [], h) for h in empty],
                      key=lambda c: rank.get(c[2], -1))
    for subject, _files, h in reversed(hist):
        m = READER_FIX_RE.match(subject)
        if m:
            body = git(audits, "log", "-1", "--format=%b", h)[1]
            sha_ = next((x.group(1) for x in map(PROMPT_SHA_LINE.match, body.splitlines()) if x), None)
            fixes.append((h, m.group(1), int(m.group(2)), sha_))
        m = READER_FIX_PROMPT_RE.match(subject)
        if m:
            prompts.setdefault((m.group(1), int(m.group(2))), h)
    return fixes, prompts


def reader_fix_prompt_problems(audits, rounds_rel, round_name=None):
    """[problem] of the §7f prompt hash (lanecheck --round R): every "reader-fix R n" commit (of round R, or of every
    round) stores the sha256 of the prompt its "reader-fix-prompt R n" commit committed, and that prompt is unchanged
    since; the run has at most READER_FIX_BUDGET of them, numbered 1, 2, ..."""
    fixes, prompts = reader_fix_history(audits, rounds_rel)
    out = []
    for k, (h, rnd, n, sha_) in enumerate(fixes, 1):
        if n != k:
            out.append(f"\"reader-fix {rnd} {n}\" ({h[:11]}) is the run's reader fix number {k}")
        if k > READER_FIX_BUDGET:
            out.append(f"\"reader-fix {rnd} {n}\" ({h[:11]}) is past the run's budget of {READER_FIX_BUDGET} reader fixes")
        if round_name and rnd != round_name:
            continue
        ph = prompts.get((rnd, n))
        rel = f"{rounds_rel}/{reader_fix_prompt_rel(rnd, n)}"
        if ph is None:
            out.append(f"\"reader-fix {rnd} {n}\" ({h[:11]}) has no \"reader-fix-prompt {rnd} {n}\" commit (prompt.py 4 "
                       f"--round {rnd} --reader-fix writes and commits it)")
            continue
        committed = _git_text(audits, ph, rel)
        want = hashlib.sha256(committed.encode("utf-8")).hexdigest() if committed else None
        if not want or sha_ != want:
            out.append(f"\"reader-fix {rnd} {n}\" ({h[:11]}) stores prompt sha {str(sha_)[:12]}, but the prompt committed "
                       f"by {ph[:11]} hashes to {str(want)[:12]}: the adjudicator was not given the committed prompt")
        if _git_text(audits, h, rel) != committed:
            out.append(f"the reader-fix prompt {reader_fix_prompt_rel(rnd, n)} changed after its commit {ph[:11]}")
    return out


def reader_fix_commit_problems(audits, rounds_rel):
    """[(commit, round, [problem])] of every "reader-fix R n" commit: what it changed (reader_fix_edit_problems,
    against its parent) -- integrity --check, code record-fix-diff."""
    fixes, _ = reader_fix_history(audits, rounds_rel)
    out = []
    for h, rnd, n, _sha in fixes:
        files = [f for subj, fs, hh in history(audits, rounds_rel) if hh == h for f in fs]
        old = {f: _git_text(audits, h + "^", f"{rounds_rel}/{f}") for f in files}
        new = {f: _git_text(audits, h, f"{rounds_rel}/{f}") for f in files}
        out.append((h, rnd, reader_fix_edit_problems(old, new, rnd)))
    return out


def commit_reader_fix(audits, rounds_dir, rounds_rel, round_name, cfg=None):
    """Commit a reader fix of round `round_name` as "reader-fix R n" (n = the run's next; at most
    READER_FIX_BUDGET), storing the committed prompt's sha256. Returns (commit, n, [changed files]); raises
    ValueError."""
    if not round_name or not project.ROUND_RE.match(round_name):
        raise ValueError(f"{round_name!r} is not a round name")
    fixes, prompts = reader_fix_history(audits, rounds_rel)
    n = len(fixes) + 1
    if n > READER_FIX_BUDGET:
        raise ValueError(f"the run's {READER_FIX_BUDGET} reader-fix rounds are spent: answer what remains unfixable "
                         f"(\"fix budget reached\") and quote it in the notice")
    ph = prompts.get((round_name, n))
    if ph is None:
        raise ValueError(f"no committed prompt for reader fix {n} of {round_name}: python3 audits/prompt.py 4 --round "
                         f"{round_name} --reader-fix writes and commits it, then the adjudicator runs it")
    prel = reader_fix_prompt_rel(round_name, n)
    committed = _git_text(audits, ph, f"{rounds_rel}/{prel}")
    disk = open(os.path.join(rounds_dir, prel), encoding="utf-8").read() if os.path.exists(os.path.join(rounds_dir, prel)) else None
    if not committed or disk != committed:
        raise ValueError(f"the prompt {prel} differs from the one committed by {ph[:11]}: restore it (git checkout)")
    rc, st = git(audits, "status", "--porcelain", "--untracked-files=all", "--", rounds_rel)
    changed = []
    for line in st.splitlines():
        rel = os.path.relpath(line[3:].strip().strip('"'), rounds_rel)
        if rel in READER_FIX_RECORDS or rel == f"{round_name}/ADOPTED.md":
            changed.append(rel)
        elif owner(rel) is not None and not line.startswith("??"):
            raise ValueError(f"{rel} changed: a reader fix changes only {', '.join(READER_FIX_RECORDS)} and the "
                             f"hypothesis and reading rows of {round_name}/ADOPTED.md")
    if not changed:
        # Trial #9: the adjudicator found no record cell it may change (every finding NEEDS A ROUND or NOT A
        # FAULT). That is a valid outcome: record it as an empty "reader-fix R n" commit naming this rounds dir,
        # counted toward the budget, so the findings it was given can close (unfixable past the budget, disclosed)
        msg = (f"reader-fix {round_name} {n}\n\nprompt: {hashlib.sha256(committed.encode('utf-8')).hexdigest()}\n"
               f"no change: the adjudicator changed no record cell\nrounds: {rounds_rel}\n")
        import lane_auth
        from pathlib import Path
        top = lane_auth.audit_repo(Path(rounds_dir))
        with lane_auth.repo_lock(top):
            # --only with no path: an empty commit that leaves whatever else is staged out of it
            rc, _o = git(str(top), "commit", "-q", "--allow-empty", "--only", "-m", msg)
            if rc != 0:
                raise ValueError("the no-change reader fix could not be committed (git commit failed)")
            h = git(str(top), "rev-parse", "HEAD")[1].strip()
        return h, n, []
    old = {f: _git_text(audits, "HEAD", f"{rounds_rel}/{f}") for f in changed}
    new = {f: open(os.path.join(rounds_dir, f), encoding="utf-8").read() for f in changed}
    probs = reader_fix_edit_problems(old, new, round_name)
    if probs:
        raise ValueError("not a reader fix (restore the records and run a new round if more must change):\n  "
                         + "\n  ".join(probs))
    msg = (f"reader-fix {round_name} {n}\n\nprompt: {hashlib.sha256(committed.encode('utf-8')).hexdigest()}\n"
           + "".join(f"changed: {f}\n" for f in changed))
    h = project.commit_only([os.path.join(rounds_dir, f) for f in changed], msg, repo=audits)
    return h, n, changed


# --- RUN_RECORD.md: the process record lists every applied tool patch, self-cure and set-aside (approver 2026-10-24) ---
# Provenance only: the ids and hashes the record must carry are read from the raw records (TOOLING_PIN.json's
# re-pins, the audit repository's `tool-patch TP<k> apply` commits, stops/S<n>/CLOSED.json, the set-aside markers),
# never from the generator (run_record.py) whose output is checked. Run by `project.py --deliver` on the delivered
# copy, by `stops.deliver_gate` on the prepared file, and as `integrity.py --check-run-record [PATH]` (the form the
# root of trust runs from the scripts pinned at the run's first pin, OPERATOR-PATCH §2).
RUN_RECORD_MD = "RUN_RECORD.md"
RR_PATCHES, RR_CLEARED, RR_SETASIDE = "Tool patches", "Stops cleared without you", "Set-asides and clearances"
RR_ACKS = "History faults acknowledged after review"      # run_record.ACK_TITLE (SWEEP-FIX D2)
TP_APPLY = re.compile(r"^tool-patch (TP[1-9]\d*) apply\b")


def rr_sections(text, title):
    """[body] of every `## <n>. <title>` section of a RUN_RECORD.md text (a generated one has exactly one)."""
    return re.findall(rf"(?ms)^## \d+\. {re.escape(title)}[ \t]*\n(.*?)(?=^## |\Z)", text or "")


def applied_tool_patches(audits, rounds_dir):
    """{TP<k>: {"sha": patch_sha256 or "", "seal": review seal or "", "commits": [apply commit]}} of every tool patch
    applied in this run: a re-pin entry naming it (TOOLING_PIN.json `repins[].tool_patch`) or a commit whose subject
    is `tool-patch TP<k> apply`."""
    out = {}
    try:
        pin_ = json.load(open(os.path.join(rounds_dir, PIN), encoding="utf-8"))
    except (OSError, ValueError):
        pin_ = {}
    for r in (pin_.get("repins") or []) if isinstance(pin_, dict) else []:
        tp = r.get("tool_patch") if isinstance(r, dict) else None
        if tp:
            d = out.setdefault(str(tp), {"sha": "", "seal": "", "commits": []})
            d["sha"], d["seal"] = str(r.get("patch_sha256") or d["sha"]), str(r.get("review_seal") or d["seal"])
    _rc, log = git(audits, "log", "--format=%H %s")
    for line in log.splitlines():
        h, _, s = line.partition(" ")
        m = TP_APPLY.match(s)
        if m:
            out.setdefault(m.group(1), {"sha": "", "seal": "", "commits": []})["commits"].append(h)
    return out


class run_history_hidden:
    """A selftest's fixtures read no tool patch from the run's own audit repository `audits` (DOC-FIX review #1:
    in a project with an applied tool patch, project.py's and make_report.py's selftests read its `tool-patch TP<k>
    apply` commit through project.AUDITS, failed, and so `selftest_all.py --fast` refused --deliver on the tool-patch
    route). Inside it, applied_tool_patches(audits, ...) reads an empty history in place of `audits`'s; a fixture's
    own repository and every rounds directory's TOOLING_PIN.json are read as before."""

    def __init__(self, audits):
        self.audits = os.path.realpath(audits)

    def __enter__(self):
        global applied_tool_patches
        self.keep, self.empty = applied_tool_patches, tempfile.mkdtemp(prefix="no-run-history-")
        subprocess.run(["git", "init", "-q", self.empty], capture_output=True)
        real = self.keep
        applied_tool_patches = lambda a, rd: real(self.empty if os.path.realpath(a) == self.audits else a, rd)
        return self

    def __exit__(self, *exc):
        global applied_tool_patches
        applied_tool_patches = self.keep
        shutil.rmtree(self.empty, ignore_errors=True)
        return False


def run_record_problems(audits, rounds_dir, text):
    """[problem] when the RUN_RECORD.md `text` does not list, each in its own section, every applied tool patch (its
    id, patch sha256 and apply commit), every stop the operator closed (a release self-cure, a deferral or a delegated
    close: its `| S<n> |` row) and every set-aside (its `| <round>[ <lane>] |` row). [] when it lists them all."""
    out, secs = [], {}
    for t in (RR_PATCHES, RR_CLEARED, RR_SETASIDE):
        found = rr_sections(text, t)
        if len(found) != 1:
            out.append(f"{RUN_RECORD_MD} has {len(found)} section(s) \"{t}\", not exactly one")
        secs[t] = found[0] if len(found) == 1 else ""
    for tp, d in sorted(applied_tool_patches(audits, rounds_dir).items()):
        # an id and a sha256 whole; an apply commit by its first 11 characters (a longer spelling counts)
        for v, tail in [(tp, r"(?!\w)")] + ([(d["sha"], r"(?!\w)")] if d["sha"] else []) + [(h[:11], "") for h in d["commits"]]:
            if not re.search(rf"(?<!\w){re.escape(v)}{tail}", secs[RR_PATCHES]):
                out.append(f"{RUN_RECORD_MD} does not list tool patch {tp} ({v}) under \"{RR_PATCHES}\"")
    for p in sorted(glob.glob(os.path.join(rounds_dir, "stops", "S*", "CLOSED.json"))):
        s = os.path.basename(os.path.dirname(p))
        try:
            by = (json.load(open(p, encoding="utf-8")) or {}).get("by")
        except (OSError, ValueError, AttributeError):
            by = None
        if by != "human" and not re.search(rf"(?m)^\| {re.escape(s)} \|", secs[RR_CLEARED]):
            out.append(f"{RUN_RECORD_MD} does not list stop {s}, closed by the operator, under \"{RR_CLEARED}\"")
    # DOC-FIX: every live hand edit of a generated document, its id and diff sha256, in the delivery section (a
    # delivered record only: the edits come after the final prepare, so the prepared record cannot name them)
    delivered = re.search(r"(?m)^## Delivery-phase notes[ \t]*$", text or "") is not None
    try:
        import readers as _rd
        live = _rd.live_hand_edits_at(rounds_dir)
    except Exception as e:      # noqa: BLE001 -- fail closed
        live, out = [], out + [f"the hand edits could not be read: {e!r}"]
    if live and delivered:
        hsec = re.findall(r"(?ms)^### Hand edits of generated documents[ \t]*\n(.*?)(?=^### |^## |\Z)", text or "")
        body = "\n".join(hsec)
        for r in live:
            if not re.search(rf"(?m)^#### {re.escape(r['he'])}:", body) or str(r.get("diff_sha256")) not in body:
                out.append(f"{RUN_RECORD_MD} does not list hand edit {r['he']} (its id and diff sha256) under \"Hand "
                           f"edits of generated documents\"")
    # SWEEP-FIX D2: every valid acknowledgment of a history fault, with each line it acknowledges
    acks = [a for a in acknowledgments(audits, rounds_dir) if a["valid"]]
    if acks:
        found = rr_sections(text, RR_ACKS)
        body = found[0] if len(found) == 1 else ""
        for a in acks:
            if not re.search(rf"(?m)^### {re.escape(a['ak'])} ", body) or any(l not in body for l in a["lines"]):
                out.append(f"{RUN_RECORD_MD} does not list acknowledgment {a['ak']} and every line it acknowledges "
                           f"under \"{RR_ACKS}\"")
    marks = [(os.path.basename(os.path.dirname(p)), None) for p in glob.glob(os.path.join(rounds_dir, "*", "ABANDONED.json"))]
    for p in glob.glob(os.path.join(rounds_dir, "*", ".abandoned", "*.json")):
        try:
            lane = (json.load(open(p, encoding="utf-8")) or {}).get("lane")
        except (OSError, ValueError, AttributeError):
            lane = None
        marks.append((os.path.basename(os.path.dirname(os.path.dirname(p))), lane))
    for rnd, lane in sorted(marks, key=str):
        scope = rnd + (f" {lane}" if lane else "")
        if not re.search(rf"(?m)^\| {re.escape(scope)} \|", secs[RR_SETASIDE]):
            out.append(f"{RUN_RECORD_MD} does not list the set-aside of {scope} under \"{RR_SETASIDE}\"")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--round")
    ap.add_argument("--repin", metavar="REASON", help="with --pin: re-pin, stating why")
    ap.add_argument("--commit-adjudication", action="store_true",
                    help="with --round: commit the adjudicator's records by name (ADOPTED.md and the "
                         "top-level records it owns), as \"adjudicate R\"")
    ap.add_argument("--commit-record-fix", action="store_true",
                    help="with --round: commit a record correction (only the faulty cells of PAPER_DEFECTS/SKIPPED/"
                         "VACUOUS.md) as \"record-fix R\"")
    ap.add_argument("--commit-reader-fix", action="store_true",
                    help="with --round: commit a reader-fix round (B10: unprotected cells of PAPER_DEFECTS/SKIPPED/"
                         "VACUOUS/DEVIATIONS.md, the hypothesis and reading rows of R/ADOPTED.md) as \"reader-fix R n\"")
    ap.add_argument("--revotes", action="store_true",
                    help="with --commit-adjudication: the re-vote adjudication (\"adjudicate R revotes\")")
    ap.add_argument("--acknowledge", metavar="COMMIT",
                    help="with --stop S<n>: the human waives the ownership FAIL of a commit that only ADDED files")
    ap.add_argument("--stop")
    ap.add_argument("--ack-request", action="store_true",
                    help="release: request a fresh reviewer's acknowledgment of the history FAIL lines no cure clears "
                         "(SWEEP-FIX D2), with --diagnosis TEXT")
    ap.add_argument("--diagnosis")
    ap.add_argument("--check-run-record", nargs="?", const="", metavar="PATH",
                    help="RUN_RECORD.md (default: the delivered copy, else the prepared one) lists every applied tool "
                         "patch, every stop the operator closed and every set-aside")
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
    if a.check_run_record is not None:
        p = a.check_run_record or next((x for x in (os.path.join(project.REPO, "deliverables", RUN_RECORD_MD),
                                                    os.path.join(rd, RUN_RECORD_MD)) if os.path.isfile(x)), "")
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            print(f"RED[deliver] no {RUN_RECORD_MD} to check ({p or 'neither delivered nor prepared'})")
            return 1
        probs = run_record_problems(project.AUDITS, rd, txt)
        for m in probs:
            print(f"RED[deliver] {m}")
        print(f"run record: {'OK' if not probs else f'{len(probs)} FAIL(s)'} ({os.path.relpath(p, project.REPO)})")
        return 1 if probs else 0
    if a.pin:
        why = intake_gate(rd, a.repin)
        if why:
            print(f"FAIL: {why}", file=sys.stderr); return 2
        p, err = pin(project.AUDITS, cfg, rounds_dir=rd, repin=a.repin, repo=project.REPO)
        if err:
            print(f"FAIL: {err}", file=sys.stderr); return 2
        msg = f"pin (repin: {a.repin})" if a.repin else "pin"
        print(f"pinned the audit apparatus: {os.path.relpath(p, project.REPO)}\n"
              f"now commit it, alone, with exactly this message: "
              f"git -C audits add {rel}/{PIN} && git -C audits commit -m \"{msg}\"")
        return 0
    if a.ack_request:
        try:
            p, spawn, lines = ack_request(project.AUDITS, cfg, rd, rel, a.diagnosis, repo=project.REPO)
        except ValueError as e:
            print(f"FAIL: {e}", file=sys.stderr); return 1
        ak = os.path.basename(os.path.dirname(p))
        print(f"recorded {os.path.relpath(p, project.REPO)} (\"acknowledge {ak} request\"): {len(lines)} line(s):\n"
              + "\n".join(f"  {l}" for l in lines)
              + f"\nSpawn a FRESH reviewer (general-purpose; Codex: agent_type formalize_tool_patch_reviewer, fork_turns none; never yourself, a lane or the adjudicator; a new agent) with exactly:\n{spawn}\n"
              f"then seal its verdict from its LANE_COMPLETION line: python3 audits/lane_auth.py seal --verdict "
              f"{os.path.join(os.path.dirname(p), ACK_VERDICT)} --sha256 <digest> --agent-id <its id>. Approved: "
              f"integrity.py --check prints those lines as NOTE[acknowledged-fault]; close the stop --cured "
              f"\"acknowledgment {ak}\". Rejected: revise the diagnosis (or cure otherwise) and request again; never a stop")
        return 0
    if a.acknowledge:
        try:
            p = acknowledge(project.AUDITS, rd, cfg, a.acknowledge, a.stop)
        except ValueError as e:
            print(f"FAIL: {e}", file=sys.stderr); return 1
        print(f"recorded the waiver {os.path.relpath(p, project.AUDITS)} (\"ack …\"); the report's summary page lists it")
        return 0
    if a.commit_adjudication:
        try:
            h, paths = commit_adjudication(project.AUDITS, rd, rel, a.round, a.revotes, cfg=cfg)
        except ValueError as e:
            print(f"FAIL[commit-refused] {e}", file=sys.stderr); return 1
        print(f"committed \"adjudicate {a.round}{' revotes' if a.revotes else ''}\" in {h[:11]}: "
              + ", ".join(os.path.relpath(p_, project.AUDITS) for p_ in paths))
        return 0
    if a.commit_record_fix:
        try:
            h, cells = commit_record_fix(project.AUDITS, rd, rel, a.round, cfg)
        except ValueError as e:
            print(f"FAIL[commit-refused] {e}", file=sys.stderr); return 1
        what = "; ".join(f"{f} row {k} '{c}'" for f, k, c in cells)
        project.log_append(cfg, "Mechanical failures", f"- record-fix {a.round} ({datetime.date.today().isoformat()}): "
                           f"a record correction in {h[:11]} changed {what}")
        print(f"committed \"record-fix {a.round}\" in {h[:11]}: {what}\nnow re-run the check that failed, then "
              f"stops.py close --delegated (RUN.md failure table, record-fix)")
        return 0
    if a.commit_reader_fix:
        try:
            h, n, files = commit_reader_fix(project.AUDITS, rd, rel, a.round, cfg)
        except ValueError as e:
            print(f"FAIL[commit-refused] {e}", file=sys.stderr); return 1
        if not files:
            left = READER_FIX_BUDGET - n
            print(f"no record changed: recorded \"reader-fix {a.round} {n}\" (no change) in {h[:11]}, reader fix {n} of "
                  f"the run's {READER_FIX_BUDGET}; the documents are unchanged (no new reader pass). "
                  + (f"{left} reader-fix round(s) remain for the content findings still open"
                     if left > 0 else "The budget is spent: answer each remaining content finding unfixable "
                     "(\"fix budget reached\", with the adjudicator's NEEDS A ROUND reason) and quote it in the notice"))
            return 0
        print(f"committed \"reader-fix {a.round} {n}\" in {h[:11]}: {', '.join(files)}\nnow prepare again "
              f"(python3 audits/project.py --prepare-delivery) and run the readers of the documents that changed")
        return 0
    if a.check:
        res = check(project.AUDITS, cfg, a.round, rounds_dir=rd, rounds_rel=rel, repo=project.REPO)
        for sev, m in res:
            print(line_of(sev, m))
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
        os.makedirs(os.path.join(d, "run")); open(os.path.join(d, "run", "stage4-rounds.md"), "w").write("stage\n")
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
        os.makedirs(rd, exist_ok=True)
        _no_log = intake_gate(rd)
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(f"## Intake\nintake-message sha256 {project.intake_hash()}\n")
        say("B6: the first pin needs the intake message's hash under ## Intake; a re-pin does not",
            bool(_no_log) and intake_gate(rd) is None and intake_gate(os.path.join(d, "nolog"), repin="x") is None
            and bool(intake_gate(os.path.join(d, "nolog"))))
        os.remove(os.path.join(rd, "RUN_LOG.md"))
        open(os.path.join(d, "phase0.py"), "a").write("# dirty\n")
        say("pin refuses a dirty tooling tree", pin(d, cfg, agent_file=agent, rounds_dir=rd)[0] is None)
        g("checkout", "--", "phase0.py")
        p, err = pin(d, cfg, agent_file=agent, rounds_dir=rd)
        say("pin succeeds on a clean tree", p and not err)
        commit("pin")
        say("clean state passes", fails(C()) == [])
        # forgery review M2: the involvement level (and mode, intake answer, ownership) is the FIRST pin's: a flip
        # of the working pin AND the config together (the config check alone compares the two) is FAIL[pin]
        pdoc = json.load(open(os.path.join(rd, PIN)))
        flip = dict(pdoc, config=dict(pdoc["config"], involvement="hands-off", involvement_answer="(c) hands-off"))
        json.dump(flip, open(os.path.join(rd, PIN), "w")); commit("pin (repin: config wording)")
        cfg_f = dict(cfg, involvement="hands-off", involvement_answer="(c) hands-off")
        bad_m2 = fails(C(c=cfg_f))
        refused_m2 = pin(d, cfg_f, agent_file=agent, rounds_dir=rd, repin="config wording")
        json.dump(dict(pdoc, ownership=1), open(os.path.join(rd, PIN), "w")); commit("pin (repin: older rules)")
        bad_own = fails(C())
        json.dump(pdoc, open(os.path.join(rd, PIN), "w")); commit("pin (repin: restore the intake terms)")
        say("forgery review M2: an involvement level flipped in the pin and the config together is FAIL[pin] against "
            "the first committed pin (as is an ownership downgrade); a re-pin refuses it; restoring the intake terms "
            "clears it",
            any(m.startswith("[pin] `involvement` is fixed at the intake") and "the pin now says" in m for m in bad_m2)
            and any("`involvement_answer`" in m and "the config now says" in m for m in bad_m2)
            and refused_m2[0] is None and "involvement" in refused_m2[1]
            and any("ownership version is fixed" in m for m in bad_own)
            and not [m for m in fails(C()) if not m.startswith("[pin] TOOLING_PIN.json re-committed")])
        g("reset", "-q", "--hard", "HEAD~3")
        say("record commits before the first pin are not judged, and the report says so",
            fails(C()) == [] and any("before the first pin" in m for s_, m in C() if s_ == "note"))
        open(os.path.join(d, "P", "SKIPPED.md"), "a").write("| 2 | Lemma 2 |\n"); commit("hand edit")
        say("a record edited by a non-adjudicate commit AFTER the pin still fails",
            any("SKIPPED.md was committed by" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        # integration review, attack 6: DEVIATIONS.md's reading-choice/differs rows set a result's status
        dv = os.path.join(rd, "DEVIATIONS.md")
        DV = ("| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
              "| 1 | Lemma 1 | a | b | c | same strength |\n")
        open(dv, "w").write(DV); commit("deviations")
        say("ownership 3: DEVIATIONS.md committed by the operator fails (FAIL[ownership]; the delivery check too)",
            any("DEVIATIONS.md was committed by" in m for m in fails(C()))
            and deviations_ownership_problems(cfg, d, rd) and pinned_version(rd) == OWNERSHIP >= 3)
        g("reset", "-q", "--hard", "HEAD~1")
        open(dv, "w").write(DV); commit("adjudicate R1")
        say("ownership 3: DEVIATIONS.md committed by the adjudication passes",
            fails(C()) == [] and deviations_ownership_problems(cfg, d, rd) == [])
        g("reset", "-q", "--hard", "HEAD~1")
        doc_2 = json.load(open(os.path.join(rd, PIN))); doc_2["ownership"] = 2
        json.dump(doc_2, open(os.path.join(rd, PIN), "w"))
        fails2 = lambda: [m for m in fails(C()) if PIN not in m]
        open(dv, "w").write(DV); commit("deviations")
        ok_add = fails2() == [] and deviations_ownership_problems(cfg, d, rd) == []
        open(dv, "w").write(DV.replace("| c | same strength |", "| c, reworded | same strength |")); commit("deviations wording")
        ok_edit = fails2() == []
        open(dv, "w").write(DV.replace("same strength", "reading choice")); commit("deviations wording 2")
        bad2 = fails2()
        dvp2 = deviations_ownership_problems(cfg, d, rd)
        open(dv, "w").write(DV); commit("deviations: restore")
        ok_back = fails2() == [] and deviations_ownership_problems(cfg, d, rd) == []
        open(dv, "a").write("| 2 | Lemma 2 | a | b | c | differs |\n"); commit("deviations: a differs row")
        bad3 = fails2()
        g("reset", "-q", "--hard", "HEAD~5")
        g("checkout", "--", "P/" + PIN)
        say("ownership 2 (a run pinned before 3): the operator still writes DEVIATIONS.md rows and their text, but a "
            "row's kind changed to `reading choice` (mini4 repro) or a `differs` row added is FAIL[ownership], also in "
            "the delivery check; restoring the rows clears it",
            ok_add and ok_edit and any("row 1 changed from `same strength`" in m and "reading choice" in m for m in bad2)
            and dvp2 and ok_back and any("row 2 of kind `differs` added" in m for m in bad3))
        say("second pin refuses", pin(d, cfg, agent_file=agent, rounds_dir=rd)[0] is None)
        rdg = os.path.join(tempfile.mkdtemp(), "P")
        pg, _ = pin(d, cfg, agent_file=agent, rounds_dir=rdg, repo=d)
        sg = json.load(open(pg)).get("gitmeta") or {}
        old_sg = json.dumps(sg, sort_keys=True)
        g("config", "alias.zz", "!echo later")
        pg2, _ = pin(d, cfg, agent_file=agent, rounds_dir=rdg, repin="x", repo=d)
        g("config", "--unset", "alias.zz")
        say("B1c: the pin records the Stage 1 snapshot (hooks with content, risky config, remote/credential/user, "
            "HEADs), and a re-pin keeps it",
            set(sg) == {"meta", "hooks", "ident", "heads", "hooks_dir", "hookspath", "subst"} and "project" in sg["meta"]
            and sg["heads"].get("project")
            and pg2 and json.dumps(json.load(open(pg2)).get("gitmeta"), sort_keys=True) == old_sg)
        old_pin = json.load(open(pg2)); old_pin.pop("gitmeta", None); json.dump(old_pin, open(pg2, "w"))   # an older pin
        pg3, _ = pin(d, cfg, agent_file=agent, rounds_dir=rdg, repin="add the snapshot", repo=d)
        say("B1c review L1: a re-pin of a pin without a Stage 1 snapshot adds one",
            pg3 and "meta" in (json.load(open(pg3)).get("gitmeta") or {}))
        shutil.rmtree(os.path.dirname(rdg), ignore_errors=True)
        # review R: git here ignores refs/replace/* (a replace ref would show another commit's files)
        h_now = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        real_files = changed_files(d, h_now)
        fake = subprocess.run(["git", "-C", d, "commit-tree", "4b825dc642cb6eb9a060e54bf8d69288fbee4904", "-p",
                               h_now + "~1", "-m", "x"], capture_output=True, text=True).stdout.strip()
        g("replace", h_now, fake)
        env_ = {k: v for k, v in os.environ.items() if k != "GIT_NO_REPLACE_OBJECTS"}   # a fresh process: this one's
        seen = subprocess.run([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "    # own
                               "import integrity, json; print(json.dumps(sorted(integrity.changed_files(sys.argv[2], sys.argv[3]))))",
                               os.path.dirname(os.path.abspath(__file__)), d, h_now], capture_output=True, text=True,
                              env=env_).stdout.strip()
        seen = set(json.loads(seen)) if seen.startswith("[") else None
        g("replace", "-d", h_now)
        say("B1c review R: integrity's git calls ignore replace refs", bool(real_files) and seen == real_files)

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
        say("A4: under ownership 2 a lane's files committed by the adjudication (an `add -A` sweep) fail",
            any("non-vacuity@1.probes/witness.lean" in m and "\"seal" in m for m in fails(C())))
        doc_v = json.load(open(os.path.join(rd, PIN))); doc_v.pop("ownership", None)
        json.dump(doc_v, open(os.path.join(rd, PIN), "w"))
        say("A4: a run pinned before ownership 2 keeps its rules: the adjudication's commit of lane files passes",
            [m for m in fails(C()) if PIN not in m] == [] and pinned_version(rd) == 1)
        g("checkout", "--", "P/" + PIN)
        g("reset", "-q", "--soft", "HEAD~1"); g("commit", "-qm", "seal R1 non-vacuity@1.json")
        say("the lane's seal commit of its verdict and probes passes", fails(C()) == [])
        say("COMMITTED lane probes are not tooling", fails(C()) == [])
        open(os.path.join(rd, "R1", "correspondence.json"), "w").write('{"changed": 1}')
        say("A4: a committed lane verdict changed in the round under review fails (never 'in review')",
            any("correspondence.json" in m and "protected record" in m for m in fails(C())))
        g("checkout", "--", "P/R1/correspondence.json")
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
        for f in ("phase0.py", "tail.lean", "AUDIT_PROTOCOL.md", "RUN.md", "run/stage4-rounds.md", "agents/auditor.md"):
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
        os.makedirs(os.path.join(d, "__pycache__")); open(os.path.join(d, "__pycache__", "x.cpython-312.pyc"), "wb").write(b"\0" * 16)
        say("A10a: cached bytecode in __pycache__ is a NOTE, not a FAIL",
            not any("bytecode" in m for m in fails(C())) and any("[pyc-cache]" in m for s_, m in C() if s_ == "note"))
        open(os.path.join(d, "__pycache__", "u.cpython-312.pyc"), "wb").write(b"\0" * 4 + b"\1\0\0\0" + b"\0" * 8)
        say("A10a: an unchecked-hash .pyc fails", any("unchecked-hash" in m for m in fails(C())))
        shutil.rmtree(os.path.join(d, "__pycache__"))
        os.makedirs(os.path.join(d, "tests"), exist_ok=True)
        open(os.path.join(d, "tests", "m.pyc"), "wb").write(b"\0" * 16)
        say("A10a: a sourceless .pyc next to the test scripts fails", any("outside __pycache__" in m for m in fails(C())))
        os.remove(os.path.join(d, "tests", "m.pyc"))
        shutil.rmtree(os.path.join(d, "tests"))
        pc = os.path.join(rd, "R1", "non-vacuity@1.probes", "__pycache__"); os.makedirs(pc)
        open(os.path.join(pc, "search.cpython-312.pyc"), "wb").write(b"\0" * 4 + b"\1\0\0\0" + b"\0" * 8)
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
                     ("involvement", "hands-off"), ("mode", "release")):
            say(f"scope key `{k}` change fails", any(f"`{k}`" in m for m in fails(C(dict(cfg, **{k: v})))))
        say("a pin without the involvement keys accepts the explicit default (involved, 'default')",
            not any("involvement" in m for m in fails(C(dict(cfg, involvement="involved", involvement_answer="default")))))
        say("a pin without the mode key accepts the explicit dev (the absent key is dev)",
            not any("`mode`" in m for m in fails(C(dict(cfg, mode="dev")))))
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
        open(os.path.join(rd, "REAPPROVAL.json"), "w").write('{"decls": ["x"]}'); commit("tidy")
        say("A11: a hand-written REAPPROVAL.json (not committed by the re-approval command) fails",
            any("REAPPROVAL.json" in m for m in fails(C())))
        g("reset", "-q", "--hard", "HEAD~1")
        os.makedirs(os.path.join(rd, "resolutions", "S1"))
        open(os.path.join(rd, "resolutions", "S1", "STALL.json"), "w").write("{}"); commit("adjudicate R1")
        say("an older run's stall resolution committed by anything but 'resolve' fails",
            any("STALL.json" in m and "resolve" in m for m in fails(C())))
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
        for k_, v_ in (("mode", "dev" if cfg.get("mode") == "release" else "release"), ("involvement", "hands-off-x")):
            p3, e3 = pin(d, dict(cfg, **{k_: v_}), agent_file=agent, rounds_dir=rd, repin="switch")
            say(f"a re-pin that would change the {k_} is refused (review L1)",
                p3 is None and f"cannot change {k_}" in (e3 or "")
                and json.load(open(os.path.join(rd, PIN)))["config"].get(k_) == cfg.get(k_))
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
        # forgery review M2 (mutants RM-23, I27): a run pinned with NON-default intake terms (release, hands-off)
        # whose config goes back to the defaults (dev, involved) fails, and so does a working pin edited to match:
        # the pin must record the terms, or the absent key reads as the default and the switch goes unseen
        rq = os.path.join(d, "Q"); os.makedirs(os.path.join(rq, "R1"))
        cfg_q = dict(cfg, rounds_dir="Q", mode="release", involvement="hands-off", involvement_answer="(c) hands-off")
        CQ = lambda c: [m for s_, m in check(d, c, "R1", agent_file=agent, rounds_dir=rq, rounds_rel="Q", repo=repo)
                        if s_ == "FAIL" and m.startswith(("[pin] `", "[config] config key `"))]
        pq, eq = pin(d, cfg_q, agent_file=agent, rounds_dir=rq)
        commit("pin")
        qdoc = json.load(open(os.path.join(rq, PIN)))
        kept_q = CQ(cfg_q)
        back = {"mode": "dev", "involvement": "involved"}
        bad_q = {k: CQ(dict(cfg_q, **{k: v})) for k, v in back.items()}
        json.dump(dict(qdoc, config={k: v for k, v in qdoc["config"].items() if k not in back}),
                  open(os.path.join(rq, PIN), "w"))
        commit("pin (repin: config wording)")
        bad_q2 = {k: CQ(dict(cfg_q, **{k: v})) for k, v in back.items()}
        g("reset", "-q", "--hard", "HEAD~2"); shutil.rmtree(rq, ignore_errors=True)
        say("forgery review M2: a run pinned in release / hands-off whose config (and working pin) goes back to "
            "dev / involved fails on that key; unchanged, it passes",
            pq and not eq and kept_q == []
            and all(any(f"`{k}`" in m for m in bad_q[k]) and any(f"[pin] `{k}` is fixed" in m for m in bad_q2[k])
                    for k in back))
        # S2 (live run 2026-10-19): a round superseded before adjudication. Its remaining lane files
        # are committed by its set-aside (stops.py), and then pass.
        os.makedirs(os.path.join(rd, "R0", "correspondence.probes"))
        open(os.path.join(rd, "R0", "TARGET.json"), "w").write("{}"); commit("scope R0")
        for f in ("correspondence.json", "correspondence.probes/p.lean"):
            open(os.path.join(rd, "R0", f), "w").write("{}")
        say("S2: an unadjudicated round's lane files fail while uncommitted",
            any("protected record" in m and "R0/correspondence.json" in m for m in fails(C(r="R1"))))
        json.dump({"round": "R0"}, open(os.path.join(rd, "R0", "ABANDONED.json"), "w"))
        commit("set-aside R0")
        say("S2: once committed by `set-aside <R>`, the round's lane files pass", fails(C(r="R1")) == [])
        open(os.path.join(rd, "R0", "correspondence.json"), "w").write('{"x": 1}'); commit("adjudicate R0")
        say("a set-aside round touched by any later commit fails (even an adjudication)",
            any("touched after it was set aside" in m for m in fails(C(r="R1"))))
        g("reset", "-q", "--hard", "HEAD~1")
        # X11: a set-aside re-vote lane's files are frozen too
        os.makedirs(os.path.join(rd, "R7", "revote")); open(os.path.join(rd, "R7", "revote", "s--x.json"), "w").write("{}")
        g("add", "-A", "--", "P/R7"); g("commit", "-qm", "set-aside R7 revote/s--x")
        open(os.path.join(rd, "R7", "revote", "s--x.json"), "w").write('{"y": 1}'); commit("adjudicate R7 revotes")
        say("X11: a set-aside re-vote lane's file touched by a later commit fails",
            any("R7/revote/s--x.json" in m and "touched after it was set aside" in m for m in fails(C(r="R1"))))
        g("reset", "-q", "--hard", "HEAD~2")
        os.makedirs(os.path.join(rd, "R8", "revote"))
        for f in ("s--y.json", "t--z.json"):
            open(os.path.join(rd, "R8", "revote", f), "w").write("{}")
        commit("set-aside R8 revote/s--y")
        say("a lane's set-aside commits only that lane's files",
            any("R8/revote/t--z.json" in m and "only a" in m for m in fails(C(r="R1")))
            and not any("R8/revote/s--y.json" in m for m in fails(C(r="R1"))))
        g("reset", "-q", "--hard", "HEAD~1")
        os.makedirs(os.path.join(rd, "R9")); open(os.path.join(rd, "R9", "ADOPTED.md"), "w").write("x")
        commit("set-aside R9")
        say("a set-aside commit never covers a round's decisions (ADOPTED.md)",
            any("R9/ADOPTED.md" in m for m in fails(C(r="R1"))))
        g("reset", "-q", "--hard", "HEAD~1")
        os.makedirs(os.path.join(rd, "R6")); open(os.path.join(rd, "R6", "correspondence.json"), "w").write("{}")
        commit("resolve S1 apply abandon-round R6")
        say("under ownership 2 an older run's abandon commit is not a set-aside",
            any("R6/correspondence.json" in m and "only a" in m for m in fails(C(r="R1"))))
        g("reset", "-q", "--hard", "HEAD~1")
        os.makedirs(os.path.join(rd, "R1", ".superseded")); open(os.path.join(rd, "R1", ".superseded", "c.json.1.json"), "w").write("{}")
        commit("seal R1 c.json")
        say("an older run's superseded lane evidence is committed only by its supersede (scope) commit",
            any(".superseded/c.json.1.json" in m for m in fails(C(r="R1"))))
        g("reset", "-q", "--hard", "HEAD~1")
        # A5: the adjudication commits its own records by name; nothing else is swept in
        ra = "2026-01-01-abcdef0"; os.makedirs(os.path.join(rd, ra, "revote"))
        open(os.path.join(rd, ra, "ADOPTED.md"), "w").write("| lane | item | verdict | decision | reason |\n")
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write("# Defects\n")
        open(os.path.join(rd, ra, "revote", "c--x.json"), "w").write("{}")      # an unsealed re-vote's verdict
        open(os.path.join(rd, "AUTHOR_NOTES.md"), "a").write("operator's note\n")
        os.makedirs(os.path.join(rd, "R5")); open(os.path.join(rd, "R5", "correspondence.json"), "w").write("{}")
        open(os.path.join(rd, ra, "correspondence.json"), "w").write('{"next_step": "record in ADOPTED.md"}')
        try:
            commit_adjudication(d, rd, "P", ra); unsettled_a = False
        except ValueError as e_u:
            unsettled_a = "CLEARED correspondence.json" in str(e_u)
        say("A1: the adjudication commit refuses while a lane NOTE is unsettled", unsettled_a)
        open(os.path.join(rd, ra, "ADOPTED.md"), "a").write("\n- CLEARED correspondence.json: advice text, not a read\n")
        h_a, paths_a = commit_adjudication(d, rd, "P", ra)
        names_a = set(subprocess.run(["git", "-C", d, "show", "--name-only", "--format=", h_a],
                                     capture_output=True, text=True).stdout.split())
        say("A5: the adjudication commits ADOPTED.md and its top-level records by name, nothing else",
            names_a == {f"P/{ra}/ADOPTED.md", "P/PAPER_DEFECTS.md"}
            and subprocess.run(["git", "-C", d, "log", "-1", "--format=%s"], capture_output=True,
                               text=True).stdout.strip() == f"adjudicate {ra}")
        try:
            commit_adjudication(d, rd, "P", ra); again_a = False
        except ValueError:
            again_a = True
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "a").write("a defect row\n")
        try:
            commit_adjudication(d, rd, "P", ra); only_pd = False
        except ValueError:
            only_pd = True
        g("checkout", "--", "P/PAPER_DEFECTS.md")
        say("A5: an unchanged ADOPTED.md is not committed again, even with a changed top-level record", again_a and only_pd)
        open(os.path.join(rd, ra, "ADOPTED.md"), "a").write("| c | x | Pass | **REJECT** | re-vote |\n")
        commit_adjudication(d, rd, "P", ra, revotes=True)
        say("A5: the re-vote adjudication is committed as 'adjudicate R revotes'",
            subprocess.run(["git", "-C", d, "log", "-1", "--format=%s"], capture_output=True,
                           text=True).stdout.strip() == f"adjudicate {ra} revotes")
        shutil.rmtree(os.path.join(rd, ra, "revote")); shutil.rmtree(os.path.join(rd, "R5"))
        os.remove(os.path.join(rd, ra, "correspondence.json"))
        g("reset", "-q", "--hard", "HEAD~2")
        # S1 (release trial): the adjudication commit refuses a witness that is no declaration (3); a fault
        # committed anyway is cured by a record correction of its faulty cells only (2)
        import make_report as _mr
        _mrk = _mr.REPO; _mr.REPO = d
        try:
            open(os.path.join(d, "W.lean"), "w").write("theorem real_witness : True := trivial\n"); commit("lean")
            mcfg = {"name": "t", "rounds_dir": "P", "lean_files": ["W.lean"]}
            rb = "2026-01-02-abcdef1"; os.makedirs(os.path.join(rd, rb))
            open(os.path.join(rd, rb, "ADOPTED.md"), "w").write("| lane | item | verdict | decision | reason |\n")
            _pd = ("| # | where | status | repair | what the paper says | why it is wrong | Lean witness | consequence | "
                   "decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
                   "| 2 | L3.4 | false | add hypothesis | x | y | {w} | z | {dec} | r |\n")
            _bad = "`real_witness`; its proof is `sorry`; also `probe_x` in a probe"
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(_pd.format(w=_bad, dec="keep"))
            try:
                commit_adjudication(d, rd, "P", rb, cfg=mcfg); pre = ""
            except ValueError as e_p:
                pre = str(e_p)
            say("S1: the adjudication commit refuses a witness cell naming `sorry` or a probe lemma, before committing",
                "`sorry`" in pre and "`probe_x`" in pre and "adjudicate" not in
                subprocess.run(["git", "-C", d, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout)
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(_pd.format(w="`real_witness` where |f(3)| > 2",
                                                                             dec="keep"))
            try:
                commit_adjudication(d, rd, "P", rb, cfg=mcfg); pre2 = ""
                g("reset", "-q", "HEAD~1")      # committed: undone, so the fixture goes on (the check fails)
            except ValueError as e_p:
                pre2 = str(e_p)
            say("sweep D2: the adjudication commit refuses an adjudicator-owned record fault that is no record-fix "
                "code (a bare `|` splits a cell), naming it as Phase 0 shows it (PENDING[adjudication])",
                "PENDING[adjudication] adj-record: PAPER_DEFECTS.md row 2: 12 cells under a 10-column" in pre2)
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(_pd.format(w=_bad, dec="keep"))
            if pre:
                commit_adjudication(d, rd, "P", rb)      # the incident: committed without the check
            pdp = os.path.join(rd, "PAPER_DEFECTS.md")

            def fix(w, dec="keep"):
                open(pdp, "w").write(_pd.format(w=w, dec=dec))
                try:
                    return commit_record_fix(d, rd, "P", rb, mcfg)
                except ValueError as e_f:
                    return str(e_f)
            r_dec = fix("`real_witness`", dec="changed")
            g("checkout", "--", "P/PAPER_DEFECTS.md")
            open(pdp, "w").write(_pd.format(w="`real_witness`", dec="keep").replace("| add hypothesis |", "| local |"))
            try:
                r_rep = commit_record_fix(d, rd, "P", rb, mcfg)
            except ValueError as e_f:
                r_rep = str(e_f)
            g("checkout", "--", "P/PAPER_DEFECTS.md")
            say("B3: a record correction may not change a defect's `repair` (a protected column)",
                "'repair' cell changed" in r_rep)
            r_left = fix("`real_witness`; also `probe_x`")
            g("checkout", "--", "P/PAPER_DEFECTS.md")
            _pd_c = _pd.replace("| z |", "| z2 |")
            open(pdp, "w").write(_pd_c.format(w="`real_witness`", dec="keep"))
            try:
                r_cons = commit_record_fix(d, rd, "P", rb, mcfg)
            except ValueError as e_c:
                r_cons = str(e_c)
            g("checkout", "--", "P/PAPER_DEFECTS.md")
            open(os.path.join(rd, rb, "ADOPTED.md"), "a").write("| c | x | Fail | **ADOPT** | y |\n")
            r_adopted = fix("`real_witness`")
            g("checkout", "--", "P/PAPER_DEFECTS.md", f"P/{rb}/ADOPTED.md")
            r_prose = fix("`real_witness` (states the negation; its proof is a sorry in the statement round)")
            g("checkout", "--", "P/PAPER_DEFECTS.md")
            say("re-check R1: a record correction refuses a faulty cell rewritten beyond its faulty names",
                "'lean witness' cell changed more than its faulty name" in str(r_prose))
            r_ok = fix("`real_witness`; its proof is ; also `real_witness` in a probe")
            say("S1: a record correction refuses a decision cell, a fault left, another record; it commits the "
                "witness cell alone as 'record-fix R'",
                "'decision' cell changed" in r_dec and "still faulty" in r_left
                and "'consequence' cell changed" in str(r_cons) and "ADOPTED.md changed" in r_adopted
                and isinstance(r_ok, tuple) and r_ok[1] == [("PAPER_DEFECTS.md", "2", "lean witness")]
                and subprocess.run(["git", "-C", d, "log", "-1", "--format=%s"], capture_output=True,
                                   text=True).stdout.strip() == f"record-fix {rb}")
            rfc = record_fix_commits(d, "P")
            say("S1: integrity accepts the record correction (owner, cells) and the report can list it",
                [(x[1], x[3], x[4]) for x in rfc] == [(rb, [("PAPER_DEFECTS.md", "2", "lean witness")], [])]
                and not [m for m in fails(C(r="R1")) if "PAPER_DEFECTS.md" in m or "record-fix" in m])
            say("re-check R1: the record correction stores the faults it cures in its commit",
                sorted(x[3] for x in stored_faults(d, "HEAD")) == ["probe_x", "sorry"])
            _lean_at = stored_lean(d, "HEAD")
            open(os.path.join(d, "W.lean"), "a").write("theorem probe_x : True := trivial\n")
            commit("lean: the probe's lemma promoted")
            _d4 = [x[4] for x in record_fix_commits(d, "P", mcfg)]
            g("reset", "-q", "--hard", "HEAD~1")
            say("sweep D4: a valid record correction stays valid after the name it cured is declared later (its "
                "faults are re-decided against the Lean commit it stores, not today's declarations)",
                _d4 == [[]] and bool(_lean_at))
            g("reset", "-q", "--hard", "HEAD~1")     # back to the faulty records: hand-made "record-fix" commits
            pd_head = open(pdp).read()

            def forged(text, body=""):
                open(pdp, "w").write(text)
                g("add", "-A"); g("commit", "-qm", f"record-fix {rb}" + (f"\n\n{body}" if body else ""))
                res = [m for m in fails(C(r="R1")) if m.startswith("[record-fix-diff]")]
                res += [x for c_ in record_fix_commits(d, "P", mcfg) for x in c_[4]]   # W.lean's declarations
                g("reset", "-q", "--hard", "HEAD~1")
                return res
            _fb = "fault: dead-witness | PAPER_DEFECTS.md | 2 | sorry\nfault: dead-witness | PAPER_DEFECTS.md | 2 | probe_x"
            f_dec = forged(_pd.format(w="`real_witness`", dec="reversed"), _fb)
            f_nofault = forged(pd_head.replace("| y |", "| (removed) |"))
            f_why = forged(pd_head.replace("| y |", "| (removed) |"), _fb)
            f_where = forged(pd_head.replace("| L3.4 |", "| L3.5 |"), _fb)
            f_prose = forged(_pd.format(w="`real_witness` (states the negation)", dec="keep"), _fb)
            f_false = forged(_pd.format(w="`other_witness`; its proof is ; also `real_witness` in a probe", dec="keep"),
                             _fb + "\nfault: dead-witness | PAPER_DEFECTS.md | 2 | real_witness")
            f_ok = forged(_pd.format(w="`real_witness`; its proof is ; also `real_witness` in a probe", dec="keep"), _fb)
            say("S1: a 'record-fix' commit that changes a decision fails integrity (record-fix-diff)",
                any(m.startswith("[record-fix-diff]") and "'decision' cell changed" in m for m in f_dec))
            say("re-check R1: a hand-made 'record-fix' commit fails integrity unless it stores its faults, changes only "
                "their names, in their cells, keeps 'where', and names real faults; the tool's own form passes",
                any(m.startswith("[record-fix-diff]") and "stores no fault" in m for m in f_nofault)
                and any(m.startswith("[record-fix-diff]") and "'why it is wrong' cell holds no faulty name" in m
                        for m in f_why)
                and any("'where' cell changed" in m for m in f_where)
                and any("changed more than its faulty name" in m for m in f_prose)
                and any("`real_witness` is not a fault" in m for m in f_false) and f_ok == [])
            _vh = "| # | statement | why it is wrong | decision |\n|---|---|---|---|\n"
            _v = _vh + "| 1 | L1, `a_1` | `sorry` | keep |\n| 10 | L10 | `sorry` x | keep |\n"
            _c10, _p10 = record_fix_cells(_v, _v.replace("`sorry` x", " x"), [("1", "sorry")])
            _cst, _pst = record_fix_cells(_v, _v.replace("L1, `a_1`", "L1, `a_2`"), [("1", "a_1")])
            say("sweep M2: the natural correction of the trial's cell is accepted: a faulty name counts only in "
                "backticks, so 'sorry-free' in plain text is kept, not a token to delete",
                token_only("`sorry`; proved sorry-free as `probe_x`", "`real_witness`; proved sorry-free as "
                           "`real_witness`", ["sorry", "probe_x"])
                and not token_only("`sorry`; proved sorry-free as `probe_x`", "`real_witness`; proved -free as "
                                   "`real_witness`", ["sorry", "probe_x"]))
            say("re-check R1: a fault in row 1 does not unlock row 10; a VACUOUS statement never changes",
                any("row 10" in x and "holds no faulty name" in x for x in _p10)
                and any("'statement' cell changed" in x for x in _pst))
            # L-inf run (stop S3): a dead qualified name in the adjudicator's DEVIATIONS.md (ownership 3) is a
            # record-fix fault its record correction cures, the name cell only; the operator's (no ownership 3)
            # is never corrected this way
            _h0 = git(d, "rev-parse", "HEAD")[1].strip()
            _pinp = os.path.join(rd, PIN)
            _pin0 = json.load(open(_pinp)) if os.path.exists(_pinp) else {}
            _dv = ("| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
                   "| 4 | {r} | x | via {n} W.lean:1 | y | same strength |\n")
            dvp = os.path.join(rd, "DEVIATIONS.md")
            open(pdp, "w").write(_pd.format(w="`real_witness`", dec="keep"))     # no other fault
            open(dvp, "w").write(_dv.format(r="Claim 4.14", n="`P.Gone.thm_gone`"))
            json.dump(dict(_pin0, ownership=OWNED_SINCE["DEVIATIONS.md"] - 1), open(_pinp, "w")); commit("deviation row")

            def dfix(text):
                open(dvp, "w").write(text)
                try:
                    return commit_record_fix(d, rd, "P", rb, mcfg)
                except ValueError as e_f:
                    return str(e_f)
            d_unowned = dfix(_dv.format(r="Claim 4.14", n="`real_witness`"))
            g("checkout", "--", "P/DEVIATIONS.md")
            json.dump(dict(_pin0, ownership=OWNED_SINCE["DEVIATIONS.md"]), open(_pinp, "w")); commit("pin ownership 3")
            d_result = dfix(_dv.format(r="Claim 4.15", n="`real_witness`"))
            g("checkout", "--", "P/DEVIATIONS.md")
            d_ok = dfix(_dv.format(r="Claim 4.14", n="`real_witness`"))
            g("reset", "-q", "--hard", _h0)
            say("L-inf S3: the adjudicator's DEVIATIONS.md citing a qualified name declared nowhere is cured by a record "
                "correction of that name alone; never its result; the "
                "operator's DEVIATIONS.md is not a record correction's",
                "no record-fix fault" in str(d_unowned) and "'result' cell changed" in str(d_result)
                and isinstance(d_ok, tuple) and d_ok[1] == [("DEVIATIONS.md", "4", "the lean route")])
            g("reset", "-q", "--hard", "HEAD~2")
        finally:
            _mr.REPO = _mrk
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
            g3("add", "-A"); g3("commit", "-qm", "scope R")
            pin(d3, cfg, agent_file=agent, rounds_dir=rdir, repin="tool-patch TP1",
                tool_patch={"tool_patch": "TP1", "attempt": 1})       # as tool_patch.apply calls it: no repo
            g3("add", "-A"); g3("commit", "-qm", "pin (tool-patch TP1)")
            say("a tool-patch re-pin (no project given) keeps the pinned Codex roles: the check still passes "
                "(CODEX-PORT test, stop S3)", "codex_agents" in json.load(open(os.path.join(rdir, PIN)))
                and not any("codex-roles" in m or "Codex role" in m for m in fails(C3())))
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
    for name, cond in _reader_fix_controls():
        say(name, cond)
    for name, cond in _ack_controls():
        say(name, cond)
    say("DOC-FIX review #1: inside run_history_hidden(A) a fixture reads no `tool-patch TP<k> apply` commit of A (the "
        "run's audit record); another repository, and A outside it, still are read", _run_history_hidden_control())
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def _ack_controls():
    """[(name, passed)] -- RELEASE-SWEEP BLOCKING 2-4 / SWEEP-FIX D2: the reviewed acknowledgment of a history fault.
    Scenarios of the sweep: I3 (an operator hand edit of an adjudicator record, re-committed by the next adjudication:
    `stops.py revert` cannot run, the FAIL[ownership] stays for ever), I1 (a past plain re-pin over changed tooling),
    I2 (a pin committed under a mistyped subject), I9 (--acknowledge, the human's waiver, in release)."""
    import lane_auth
    out = []
    d = tempfile.mkdtemp(prefix="ack-")
    try:
        _ack_scenarios(d, out)
    except Exception as e:      # noqa: BLE001 -- a scenario that cannot go on is a failed check, never a crash
        out.append((f"D2: the acknowledgment scenarios ran to the end ({type(e).__name__}: {str(e)[:160]})", False))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def _ack_scenarios(d, out):
    import lane_auth
    global check
    if True:
        def g(*a):
            return subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True).stdout.strip()

        def commit(msg):
            g("add", "-A"); g("commit", "-qm", msg); return g("rev-parse", "HEAD")

        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        os.makedirs(os.path.join(d, "projects")); os.makedirs(os.path.join(d, "P"))
        open(os.path.join(d, "phase0.py"), "w").write("print('gate')\n")
        os.makedirs(os.path.join(d, "agents")); open(os.path.join(d, "agents", "auditor.md"), "w").write("auditor\n")
        agent = os.path.join(d, "installed-agent.md"); open(agent, "w").write("auditor\n")
        open(os.path.join(d, ".gitignore"), "w").write("installed-agent.md\n")
        cfg = {"name": "P", "namespace": "N", "lanes": ["correspondence"], "lean_files": ["a"], "build_cmds": ["b"],
               "rounds_dir": "P", "mode": "release", "involvement": "hands-off", "involvement_answer": "(c)"}
        commit("setup")
        rd = os.path.join(d, "P")
        p_, err = pin(d, cfg, agent_file=agent, rounds_dir=rd)
        first = commit("pin")
        C = lambda c=cfg: check(d, c, None, agent_file=agent, rounds_dir=rd, rounds_rel="P")
        fails = lambda c=cfg: [m for s, m in C(c) if s == "FAIL"]
        tok = lambda sp: re.search(r"lane_token is ([0-9a-f]{64})", sp).group(1)

        def repin_as(subject, **extra):
            json.dump(dict(json.load(open(os.path.join(rd, PIN))), **extra), open(os.path.join(rd, PIN), "w"), indent=1)
            return commit(subject)

        # I3 (review H2): an operator's hand edit of an adjudicator record, re-committed by the next adjudication, is
        # never acknowledged (a judgement record); its real cure, the revert, now applies -- it undoes the owner's
        # later change too, which the owner commits again
        pd = os.path.join(rd, "PAPER_DEFECTS.md")
        R0 = "2026-01-01-full-abcdef0"
        os.makedirs(os.path.join(rd, R0)); open(os.path.join(rd, R0, "TARGET.json"), "w").write("{}")
        commit(f"scope {R0}")
        open(pd, "w").write("| # | defect |\n|---|---|\n| 1 | a |\n"); commit("adjudicate R1")
        open(pd, "a").write("| 2 | typo fixed by hand |\n"); hand = commit("implement R1")
        open(pd, "a").write("| 3 | b |\n"); commit("adjudicate R2")
        f0 = fails()
        g("checkout", hand + "^", "--", "P/PAPER_DEFECTS.md"); rv = commit(f"revert {hand} (stop S1)")
        f0r = fails()
        # review R1 (scenario s3): the restore also undid row 3, which round R2 decided: FAIL[owner-redo] until a fresh
        # round's adjudication (a round scoped AFTER the revert) re-decides it; an older round's adjudication does not
        open(pd, "a").write("| 3 | b |\n")
        open(os.path.join(rd, R0, "ADOPTED.md"), "w").write(
            "- REDO RULED PAPER_DEFECTS.md | | 2 | typo | | drop: x\n- REDO RULED PAPER_DEFECTS.md | | 3 | b | | keep: x\n")
        commit(f"adjudicate {R0}")
        f0old = fails()             # an OLDER full round's adjudication, even with every ruling, never settles it
        g("reset", "-q", "--hard", "HEAD~1")
        RF = "2026-01-09-diff-abcdef9"
        os.makedirs(os.path.join(rd, RF)); open(os.path.join(rd, RF, "TARGET.json"), "w").write("{}")
        commit(f"scope {RF}")
        open(pd, "a").write("| 9 | z |\n"); commit(f"adjudicate {RF}")
        f0diff = fails()            # scenario s4: a fresh DIFF round's adjudication never settles it
        pend0 = owner_redo_pending(d, rd, cfg)
        import prompt as _pr, integrity as _ig
        keep_pend = _ig.owner_redo_pending
        try:
            _ig.owner_redo_pending = lambda *a_, **k_: pend0
            sec0 = _pr.owner_redo_section(cfg, "2026-01-12-full-abcdefc")
            secd = _pr.owner_redo_section(cfg, RF)
        finally:
            _ig.owner_redo_pending = keep_pend
        RF1 = "2026-01-12-full-abcdefc"
        os.makedirs(os.path.join(rd, RF1)); open(os.path.join(rd, RF1, "TARGET.json"), "w").write("{}")
        commit(f"scope {RF1}")
        ap1 = os.path.join(rd, RF1, "ADOPTED.md")
        open(ap1, "w").write("| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n\n"
                             "- REDO RULED PAPER_DEFECTS.md | | 2 | typo fixed by hand | | drop: an operator's hand edit\n")
        commit(f"adjudicate {RF1}")
        f0half = fails()            # one undone line ruled, the other not
        open(ap1, "a").write("- REDO RULED PAPER_DEFECTS.md | | 3 | b | | keep: round R2's defect stands\n")
        commit(f"adjudicate {RF1}")
        f0keep = fails()            # kept, but not written back in the record
        open(pd, "a").write("| 3 | b |\n"); open(ap1, "a").write("\n"); commit(f"adjudicate {RF1}")
        f0new = fails()
        out.append(("RELEASE-SWEEP I3 / review H2, R1 (scenario s3): a hand edit of an adjudicator record the owner "
                    "re-committed is never acknowledgeable; the revert that puts back the content before it is verified "
                    "but undid round R2's row too: FAIL[owner-redo] until a fresh round's adjudication re-decides it "
                    "(an adjudication of an older round does not count)",
                    any(m.startswith("[ownership] PAPER_DEFECTS.md") and hand[:11] in m for m in f0)
                    and not any(ackable(m) for m in f0) and revert_problem(d, "P", rd, rv, hand) is None
                    and [m for m in f0r if m.startswith("[owner-redo] PAPER_DEFECTS.md")] == f0r and len(f0r) == 1
                    and f0old == f0r and len(f0diff) == 1 and f0diff[0].startswith("[owner-redo]") and f0new == []
                    and any("no REDO RULED line" in m for m in f0half)
                    and any("which the record does not hold" in m for m in f0keep)))
        out.append(("review re-check R1 (scenario s4): only a FULL round's adjudication that rules every undone line "
                    "(REDO RULED ... keep/drop) settles FAIL[owner-redo]; that round's adjudicator prompt lists the undone "
                    "lines, a diff round's prompt does not",
                    len(pend0) == 1 and pend0[0]["undone"] == ["| 2 | typo fixed by hand |", "| 3 | b |"]
                    and "REDO RULED <record>" in sec0 and "| 3 | b |" in sec0 and secd == ""))
        # review R1(a): a hand edit undone ONTO the current content (git revert semantics, clean) keeps the owner's
        # later work and needs no redo
        open(pd, "w").write("| # | defect |\n|---|---|\n| 1 | a |\n\n\n\n\n| 3 | b |\n"); commit("adjudicate R1")
        txt_ = open(pd).read()
        open(pd, "w").write(txt_.replace("| 1 | a |", "| 1 | a, typo fixed by hand |")); hand_b = commit("implement R1")
        open(pd, "a").write("| 4 | c |\n"); commit("adjudicate R2")
        txt_b = open(pd).read()
        open(pd, "w").write(txt_b.replace("| 1 | a, typo fixed by hand |", "| 1 | a |"))
        rv_b = commit(f"revert {hand_b} (stop S1)")
        f0b = fails()
        out.append(("review R1(a): a hand edit undone onto the current content (a clean three-way inverse) is a verified "
                    "revert that keeps the owner's later rows: no FAIL, no owner redo",
                    f0b == [] and "| 4 | c |" in open(pd).read() and revert_problem(d, "P", rd, rv_b, hand_b) is None))
        # review R2: an OWNED commit a check refuses (here a touch of a set-aside round) is reverted by stops.py's
        # "revert <C> (stop S<n>)": exactly back to the set-aside content -> excused, no redo; an owned adjudication
        # reverted -> FAIL[owner-redo] until a fresh FULL round's adjudication
        RS = "2026-01-03-diff-abcdef3"
        os.makedirs(os.path.join(rd, RS)); open(os.path.join(rd, RS, "TARGET.json"), "w").write("{}")
        commit(f"scope {RS}")
        open(os.path.join(rd, RS, "ABANDONED.json"), "w").write('{"round": "x"}\n')
        open(os.path.join(rd, RS, "correspondence.json"), "w").write('{"v": 1}\n'); commit(f"set-aside {RS}")
        open(os.path.join(rd, RS, "correspondence.json"), "w").write('{"v": 2}\n'); sac = commit(f"seal {RS} correspondence.json")
        f2a = fails()
        g("checkout", sac + "^", "--", f"P/{RS}/correspondence.json"); commit(f"revert {sac} (stop S2)")
        f2b = fails()
        open(pd, "a").write("| 5 | d |\n"); own_c = commit("adjudicate R3")
        g("checkout", own_c + "^", "--", "P/PAPER_DEFECTS.md"); rvo = commit(f"revert {own_c} (stop S3)")
        f2c = fails()
        RD2 = "2026-01-10-diff-abcdefa"
        os.makedirs(os.path.join(rd, RD2)); open(os.path.join(rd, RD2, "TARGET.json"), "w").write("{}")
        commit(f"scope {RD2}"); open(pd, "a").write("| 5 | d |\n"); commit(f"adjudicate {RD2}")
        f2d = fails()
        RF2 = "2026-01-11-full-abcdefb"
        os.makedirs(os.path.join(rd, RF2)); open(os.path.join(rd, RF2, "TARGET.json"), "w").write("{}")
        commit(f"scope {RF2}"); open(pd, "a").write("|  |  |\n"); commit(f"adjudicate {RF2}")
        f2e0 = fails()              # a full round's adjudication with no ruling does not settle it
        open(os.path.join(rd, RF2, "ADOPTED.md"), "w").write("- REDO RULED PAPER_DEFECTS.md | | 5 | d | | drop: no "
                                                             "lane of the fresh round finds this defect\n")
        commit(f"adjudicate {RF2}")
        f2e = fails()
        out.append(("review R2: an owner's commit that touched a set-aside round is undone by stops.py's named revert "
                    "(exactly the set-aside content: excused, no redo); a reverted owned adjudication is FAIL[owner-redo] "
                    "until a fresh FULL round's adjudication (a diff round's does not count); never a dead end",
                    any(m.startswith(f"[set-aside-changed] {RS}/correspondence.json") and sac[:11] in m for m in f2a)
                    and f2b == [] and any(m.startswith("[owner-redo] PAPER_DEFECTS.md") and "fresh full round" in m
                                          and rvo[:11] in m for m in f2c)
                    and f2d == f2c and len(f2e0) == 1 and "no REDO RULED line" in f2e0[0] and f2e == []))
        try:
            ack_request(d, dict(cfg, mode="dev"), rd, "P", "x", agent_file=agent); dev_ok = False
        except ValueError as e:
            dev_ok = "release mode only" in str(e)
        try:
            ack_request(d, cfg, rd, "P", "  ", agent_file=agent); nodiag = False
        except ValueError as e:
            nodiag = "--diagnosis is required" in str(e)
        # I2: a pin committed under a mistyped subject, the tooling unchanged (a trusted pin's)
        h1 = repin_as("pin again", note="1")
        f1 = fails()
        req, spawn, lines = ack_request(d, cfg, rd, "P", "a re-pin committed under a mistyped subject; its tooling is "
                                        "the first pin's", agent_file=agent)
        rq = json.load(open(req))
        out.append(("D2 / review B1(b), H2(c): --ack-request (release only, a diagnosis required) records exactly the "
                    "history FAIL lines -- the pin line names its commit -- and the commit's FULL diff; the line stays "
                    "FAIL until approved",
                    dev_ok and nodiag and lines == [ack_line(m) for m in f1] and len(lines) == 1 and h1[:11] in lines[0]
                    and any(f.get("commit") == h1 and any(x.startswith("+") and "note" in x for x in f["stat"])
                            for f in rq["facts"])
                    and g("log", "-1", "--format=%s") == "acknowledge AK1 request" and fails() == f1))

        def review(ak, tk, verdict, agent_id, req_sha=None):
            v = os.path.join(rd, ACKS, ak, ACK_VERDICT)
            rs = req_sha or hashlib.sha256(open(os.path.join(rd, ACKS, ak, "REQUEST.json"), "rb").read()).hexdigest()
            open(v, "w").write(json.dumps({"lane_token": tk, "verdict": verdict, "request_sha256": rs,
                                           "reason": "a subject typo; the tooling is the first pin's"}) + "\n")
            lane_auth.seal(v, hashlib.sha256(open(v, "rb").read()).hexdigest(), agent_id)

        review("AK1", tok(spawn), "approve", "agent-ack-1")
        res1 = C()
        out.append(("D2: an approved, sealed, fresh review turns exactly those lines into NOTE[acknowledged-fault]; the "
                    "seal commit is owned (\"acknowledge AK1 seal review.json\"); RUN_RECORD.md must list it",
                    [m for s, m in res1 if s == "FAIL"] == []
                    and any(s == "note" and m.startswith("[acknowledged-fault]") and "AK1" in m for s, m in res1)
                    and g("log", "-1", "--format=%s") == "acknowledge AK1 seal review.json"
                    and any("AK1" in x for x in run_record_problems(d, rd, "")) and not [x for x in run_record_problems(
                        d, rd, "## 9. History faults acknowledged after review\n\n### AK1 (x): acknowledged\n\n"
                        + "\n".join(f"  - `{l}`" for l in lines) + "\n") if "AK1" in x]))
        import tool_patch, make_report
        out.append(("approver 2026-10-26: an acknowledgment is in RUN_RECORD.md only: nothing on REPORT's \"Checks "
                    "weakened\" row", tool_patch.weakened_parts(cfg, rd, d) == []))
        h2 = repin_as("pin again", note="2")
        f2 = fails()
        out.append(("review B1(b) (scenario s1): a later pin under the SAME subject is a new line (its own commit): the "
                    "earlier acknowledgment does not cover it", len(f2) == 1 and h2[:11] in f2[0]))
        _r2, sp2, _l2 = ack_request(d, cfg, rd, "P", "a second mistyped re-pin", agent_file=agent)
        review("AK2", tok(sp2), "reject", "agent-ack-2")
        rej = fails()
        _r3, sp3, _l3 = ack_request(d, cfg, rd, "P", "a second mistyped re-pin, answered", agent_file=agent)
        p3 = open(os.path.join(rd, ACKS, "AK3", "prompt.txt")).read()
        review("AK3", tok(sp3), "approve", "agent-ack-2")
        reused = fails()
        a_ = {a["ak"]: a for a in acknowledgments(d, rd)}
        out.append(("D2: a rejection acknowledges nothing (the line stays FAIL) and the next request's prompt carries "
                    "it; a reviewer whose agent id sealed anything else in the run is not fresh: nothing acknowledged",
                    rej == f2 and "AK2 (reject)" in p3 and reused == f2 and not a_["AK3"]["valid"]
                    and "must be fresh" in a_["AK3"]["why"] and not a_["AK2"]["valid"]))
        _r3b, sp3b, _l3b = ack_request(d, cfg, rd, "P", "a second mistyped re-pin, another request", agent_file=agent)
        review("AK4", tok(sp3b), "approve", "agent-ack-3b", req_sha="0" * 64)
        other_req = fails()
        out.append(("D2: an approval of another request (its request_sha256) acknowledges nothing",
                    other_req == f2 and "another request" in str(acknowledgments(d, rd)[3]["why"])))
        _r4, sp4, _l4 = ack_request(d, cfg, rd, "P", "a second mistyped re-pin, answered again", agent_file=agent)
        review("AK5", tok(sp4), "approve", "agent-ack-4")
        ok4 = fails() == []
        rq4 = os.path.join(rd, ACKS, "AK5", "REQUEST.json")
        keep4 = open(rq4).read()
        open(rq4, "w").write(keep4.replace("again", "again!"))
        changed4 = [m for m in fails() if h2[:11] in m]
        open(rq4, "w").write(keep4)
        out.append(("D2: a request changed after its commit acknowledges nothing (and is itself an uncommitted record)",
                    ok4 and changed4 and fails() == []))
        # review B1 (scenario s2): a core change pinned under a mistyped subject is a re-pin that changed the tooling,
        # and while that tooling is in force no [pin] line -- even an acknowledged one -- is acknowledged
        open(os.path.join(d, "phase0.py"), "a").write("# accept everything\n"); commit("fix gate")
        refused_pin = pin(d, cfg, agent_file=agent, rounds_dir=rd, repin="a fix")
        h5 = repin_as("pin (repin:fix the gate)", audits_commit=g("rev-parse", "HEAD"))
        f5 = fails()
        try:
            ack_request(d, cfg, rd, "P", "a re-pin subject mistyped (missing space)", agent_file=agent); untrusted = False
        except ValueError as e:
            untrusted = "no trusted pin's" in str(e)
        out.append(("review B1 (scenario s2): a hand change of the core pinned as `pin (repin:...)` (one space missing) "
                    "is FAIL[pin] \"changed the tooling\" (every pin commit is compared with a trusted pin), the request "
                    "is refused while that tooling is in force, and the earlier acknowledged [pin] lines are FAIL again",
                    refused_pin[0] is None and "reviewed tool patch" in refused_pin[1]
                    and any(m.startswith(f"[pin] re-pin {h5[:11]}") and "changed the tooling" in m for m in f5)
                    and untrusted and any(h1[:11] in m for m in f5) and any(h2[:11] in m for m in f5)))
        g("checkout", first, "--", "phase0.py"); commit("restore the pinned gate")
        p6, e6 = pin(d, cfg, agent_file=agent, rounds_dir=rd, repin="restore the pinned tooling")
        commit("pin (repin: restore the pinned tooling)")
        f6 = fails()
        _r7, sp7, l7 = ack_request(d, cfg, rd, "P", "a hand fix re-pinned the wrong way; the tooling is the first "
                                   "pin's again", agent_file=agent)
        review("AK6", tok(sp7), "approve", "agent-ack-5")
        out.append(("RELEASE-SWEEP I1: a past re-pin over changed tooling is acknowledgeable only after the tooling is a "
                    "trusted pin's again, then cleared by a fresh review (with the earlier lines acknowledged again)",
                    p6 and not e6 and all(m.startswith("[pin]") for m in f6) and len(l7) == 2 and fails() == []))
        try:
            acknowledge(d, rd, cfg, hand, "S1"); i9 = False
        except ValueError as e:
            i9 = "dev mode only" in str(e) and "--ack-request" in str(e)
        out.append(("RELEASE-SWEEP I9: --acknowledge (the human's waiver) is refused in release", i9))
        open(os.path.join(d, "phase0.py"), "a").write("# dirty\n")
        try:
            ack_request(d, cfg, rd, "P", "x", agent_file=agent); tooling = False
        except ValueError as e:
            tooling = "no FAIL of a history code" in str(e) or "no trusted pin's" in str(e)
        out.append(("D2: a FAIL with a real cure (tooling changed now) is never acknowledged", tooling
                    and any(m.startswith("[tooling]") for m in fails())))
        g("checkout", "--", "phase0.py")
        # review H2(b), M2: crafted check() results (the fact checks themselves)
        keep_check = check
        try:
            check = lambda *a, **k: [("FAIL", f"[ownership] readers/x.md was committed by \"implement\" ({hand[:11]}); "
                                              f"only a \"reader …\" commit may change it")]
            try:
                ack_request(d, cfg, rd, "P", "x", agent_file=agent); nocure = False
            except ValueError as e:
                nocure = "cure was not tried" in str(e)
            open(os.path.join(d, "x.py"), "w").write("x\n"); open(os.path.join(d, "phase0.py"), "a").write("#\n")
            g("add", "-A"); g("commit", "-qm", "tool-patch TP9 apply"); tp9 = g("rev-parse", "HEAD")
            check = lambda *a, **k: [("FAIL", "[tool-patch] TP9 cannot be verified: the verifier timed out")]
            try:
                ack_request(d, cfg, rd, "P", "x", agent_file=agent); m2 = False
            except ValueError as e:
                m2 = "proof-validity core" in str(e) and "phase0.py" in str(e)
            g("reset", "-q", "--hard", tp9 + "^")
        finally:
            check = keep_check
        out.append(("review H2(b): an [ownership] line whose printed cure (revert) was never tried is not acknowledged",
                    nocure))
        out.append(("review M2: an unverifiable tool-patch link whose apply commit changed a core file is never "
                    "acknowledged", m2))
        out.append(("review H2(a), M4: a judgement record (adjudication, sign-off, scope, lane file) or a core/freeze "
                    "file is never acknowledgeable, whatever the subject quoted; a bookkeeping record is, even when the "
                    "commit subject names a core file",
                    not ackable("[tool-patch] TP1: the patch touches phase0.py (proof-validity core)")
                    and not ackable("[ownership] APPROVED_FINGERPRINTS.json was committed by \"x\" (abc)")
                    and not ackable("[ownership] R1/FINGERPRINTS.json was committed by \"x\" (abc)")
                    and not ackable("[ownership] PAPER_DEFECTS.md was committed by \"x\" (abc)")
                    and not ackable("[ownership] 2026-01-01-full-abcdef1/SIGNOFF.json was committed by \"x\" (abc)")
                    and not ackable("[ownership] 2026-01-01-full-abcdef1/correspondence.json was committed by \"x\" (a)")
                    and not ackable("[ownership] 2026-01-01-full-abcdef1/STATEMENTS_BUNDLE.md was committed by \"x\" (a)")
                    and ackable("[ownership] readers/x.md was committed by \"note on phase0.py output\" (abc)")
                    and not ackable("[ownership] round-caps/x.json was committed by \"x\" (abc)")
                    and not ackable("[ownership] stops/S1/CLOSED.json was committed by \"x\" (abc)")))
        hm1 = g("rev-parse", "HEAD")
        open(os.path.join(d, "phase0.py"), "a").write("# TP7\n"); g("add", "-A"); g("commit", "-qm", "tool-patch TP7 apply")
        tp7 = g("rev-parse", "HEAD")
        json.dump(dict(json.load(open(os.path.join(rd, PIN))), audits_commit=tp7), open(os.path.join(rd, PIN), "w"), indent=1)
        g("add", "-A"); g("commit", "-qm", "pin (tool-patch TP7)")
        t_all, t_bad = _trusted_pins(d, rd), _trusted_pins(d, rd, {"TP7"})
        g("reset", "-q", "--hard", hm1)
        out.append(("review M1: a tool patch whose link does not verify (a FAIL[tool-patch] names it) is no trusted pin",
                    _untrusted_tps([("FAIL", "[tool-patch] TP2: the first pin's apparatus does not verify this link")])
                    == {"TP2"} and tp7 in t_all and tp7 not in t_bad and len(t_bad) == len(t_all) - 1 >= 1))


def _run_history_hidden_control():
    a, b = tempfile.mkdtemp(prefix="run-"), tempfile.mkdtemp(prefix="fixture-")
    try:
        for r in (a, b):
            for c in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty",
                                       "-m", "tool-patch TP1 apply"]):
                subprocess.run(["git", "-C", r, *c], capture_output=True)
        with run_history_hidden(a):
            inside, other = applied_tool_patches(a, a), applied_tool_patches(b, b)
        return inside == {} and list(other) == ["TP1"] and list(applied_tool_patches(a, a)) == ["TP1"]
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def _reader_fix_controls():
    """B10 (ADDENDUM N4): the reader-fix round's edit rule, its commit, its budget and its prompt hash."""
    out = []
    R = "2026-01-01-abc1234"
    pd = ("## Defects\n| # | where | status | repair | what the paper says | why it is wrong | lean witness |\n"
          "|---|---|---|---|---|---|---|\n| 1 | Lemma 1 | false | typo | says x | why: OLD | `w` |\n")
    dv = "| # | result | the paper's route | the Lean route | why | kind |\n|---|---|---|---|---|---|\n" \
         "| 1 | Lemma 2 | a | b | OLD | reading choice |\n"
    ad = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n\n## Hypotheses\n| name | x |\n|---|---|\n"
    P = lambda old, new: reader_fix_edit_problems(old, new, R)
    out.append(("N4: a reader fix may change an unprotected cell (why, the Lean route) and the hypothesis rows of the "
                "round's ADOPTED.md",
                P({"PAPER_DEFECTS.md": pd, "DEVIATIONS.md": dv, f"{R}/ADOPTED.md": ad},
                  {"PAPER_DEFECTS.md": pd.replace("why: OLD", "why: NEW, explained"),
                   "DEVIATIONS.md": dv.replace("| OLD |", "| NEW |"),
                   f"{R}/ADOPTED.md": ad + "| `H` | matches the source |\n"}) == []))
    bad = {"status": P({"PAPER_DEFECTS.md": pd}, {"PAPER_DEFECTS.md": pd.replace("| false |", "| misprint (true as intended) |")}),
           "row": P({"PAPER_DEFECTS.md": pd}, {"PAPER_DEFECTS.md": pd + "| 2 | Lemma 3 | false | typo | y | z | `v` |\n"}),
           "kind": P({"DEVIATIONS.md": dv}, {"DEVIATIONS.md": dv.replace("reading choice", "same strength")}),
           "adopted": P({f"{R}/ADOPTED.md": ad}, {f"{R}/ADOPTED.md": ad.replace("| lane |", "| lane  |")}),
           "other": P({"SIGNOFF.md": "a"}, {"SIGNOFF.md": "b"})}
    out.append(("N4: a reader fix never changes a status cell, adds a row, changes a DEVIATIONS kind, touches ADOPTED.md "
                "outside its hypothesis and reading sections, or touches another file",
                all(bad.values())))
    d = tempfile.mkdtemp(prefix="readerfix-")
    try:
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        rd = os.path.join(d, "P")
        os.makedirs(os.path.join(rd, R, "prompts"))
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd)
        open(os.path.join(rd, R, "ADOPTED.md"), "w").write(ad)
        open(os.path.join(rd, R, "TARGET.json"), "w").write("{}")
        G("add", "-A"); G("commit", "-qm", f"adjudicate {R}")
        try:
            commit_reader_fix(d, rd, "P", R)
            no_prompt = False
        except ValueError as e:
            no_prompt = "no committed prompt" in str(e)
        pr = os.path.join(rd, reader_fix_prompt_rel(R, 1))
        open(pr, "w").write("THE PROMPT\n")
        G("add", "-A"); G("commit", "-qm", f"reader-fix-prompt {R} 1")
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd.replace("why: OLD", "why: NEW"))
        open(os.path.join(rd, R, "TARGET.json"), "w").write('{"x": 1}')
        try:
            commit_reader_fix(d, rd, "P", R)
            other = False
            G("reset", "-q", "--hard", "HEAD~1")       # a mutant committed it: undo, so the controls go on
            open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd.replace("why: OLD", "why: NEW"))
        except ValueError as e:
            other = "TARGET.json changed" in str(e)
        G("checkout", "-q", "--", f"P/{R}/TARGET.json")
        out.append(("N4: a reader fix with another owned record changed is refused", other))
        h1, n1, f1 = commit_reader_fix(d, rd, "P", R)
        subj = G("log", "-1", "--format=%s").stdout.strip()
        ok1 = (no_prompt and n1 == 1 and f1 == ["PAPER_DEFECTS.md"] and subj == f"reader-fix {R} 1"
               and reader_fix_prompt_problems(d, "P", R) == [] and all(not p_ for _h, _r, p_ in reader_fix_commit_problems(d, "P")))
        out.append(("N4: integrity.py --commit-reader-fix needs the committed prompt, commits \"reader-fix R n\" with its "
                    "sha256, and the commit passes lanecheck's hash check and integrity's edit check", ok1))
        # a hand-made reader fix with another prompt's hash, and one changing a status cell
        open(os.path.join(rd, R, "prompts", "adjudicator-readerfix-2.txt"), "w").write("PROMPT 2\n")
        G("add", "-A"); G("commit", "-qm", f"reader-fix-prompt {R} 2")
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd.replace("| false |", "| unsupported |").replace("why: OLD", "why: NEW"))
        G("add", "-A"); G("commit", "-qm", f"reader-fix {R} 2\n\nprompt: {'0' * 64}\n")
        hp = reader_fix_prompt_problems(d, "P", R)
        ep = [p_ for _h, _r, ps in reader_fix_commit_problems(d, "P") for p_ in ps]
        out.append(("N4 / U2 §7f: a reader fix with a prompt hash other than its committed prompt's fails lanecheck "
                    "(prompt-changed), and one changing a status cell fails integrity (record-fix-diff)",
                    any("hashes to" in x for x in hp) and any("'status' cell changed" in x for x in ep)))
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd.replace("why: OLD", "why: THIRD"))
        try:
            commit_reader_fix(d, rd, "P", R)
            third = False
        except ValueError as e:
            third = "spent" in str(e)
        out.append(("N4: a third reader fix in a run is refused (budget 2)", third and READER_FIX_BUDGET == 2))
        G("add", "-A"); G("commit", "-q", "-m", f"reader-fix {R} 3\n\nprompt: {'0' * 64}\n")
        out.append(("N4: a hand-made third reader fix fails lanecheck (past the budget)",
                    any("past the run's budget" in x for x in reader_fix_prompt_problems(d, "P", None))))
        out.append(("N4: ownership: the reader-fix prompt is the prompt command's, DELIVERY.json is prepare's, the records "
                    "and ADOPTED.md accept a reader fix",
                    owner(f"{R}/prompts/adjudicator-readerfix-1.txt") == ("reader-fix-prompt ",)
                    and owner("DELIVERY.json") == ("prepare delivery",)
                    and "reader-fix " in owner("PAPER_DEFECTS.md") and "reader-fix " in owner(f"{R}/ADOPTED.md")
                    and owner(f"{R}/prompts/adjudicator.txt") is None))
        out.append(("PDF-AGENTS (review 4): pdf/<key>/RENDER.json and every rendering file are the `render ` commits' "
                    "(matched before `*/*.json`, lane verdicts); the delivered PDFs are not owned",
                    owner("pdf/REPORT/RENDER.json") == ("render ",) and owner("pdf/SIGNOFF-x/v1/r2/B.md") == ("render ",)
                    and owner("pdf/SUMMARY/v1/check-1.md") == ("render ",) and owner(f"{R}/x.json") == ("seal ",)
                    and owner("REPORT.pdf") is None and owner(f"{R}/SIGNOFF.pdf") is None
                    and any(fnmatch.fnmatch("pdf/REPORT/RENDER.json", c) for c in CONTROL)))
        out.append(("DOC-FIX replay (conf1): the status check's records (status-check/RUNS.json, its prompts, FINDINGS.md) "
                    "are not lane verdicts (no owner); the hand-edit records are the `hand-edit ` commits'",
                    owner("status-check/RUNS.json") is None and owner("status-check/FINDINGS.md") is None
                    and owner("hand-edits/HE1.json") == ("hand-edit ",) and owner("hand-edits/HE1.diff") == ("hand-edit ",)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    out.append(_selftest_reader_fix_no_change(R, pd))
    return out


def _selftest_reader_fix_no_change(R, pd):
    """Trial #9: the second reader fix changed nothing; it is recorded (an empty "reader-fix R 2" naming the rounds
    dir), counted (the third is refused, readers count 2), passes the hash and edit checks, and leaves other staged
    work out of the commit; another project's no-change commit is not counted."""
    d = tempfile.mkdtemp(prefix="readerfix-nc-")
    try:
        G = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        rd = os.path.join(d, "P")
        os.makedirs(os.path.join(rd, R, "prompts"))
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd)
        G("add", "-A"); G("commit", "-qm", f"adjudicate {R}")
        for k in (1, 2):
            open(os.path.join(rd, reader_fix_prompt_rel(R, k)), "w").write(f"PROMPT {k}\n")
            G("add", "-A"); G("commit", "-qm", f"reader-fix-prompt {R} {k}")
            if k == 1:
                open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(pd.replace("why: OLD", "why: NEW"))
                commit_reader_fix(d, rd, "P", R)
        # another project's no-change reader fix in the same audit record: not this run's
        G("commit", "-q", "--allow-empty", "-m", f"reader-fix {R} 2\n\nprompt: {'0' * 64}\nrounds: Q\n")
        open(os.path.join(d, "staged.txt"), "w").write("x")
        G("add", "staged.txt")
        try:
            h, n, files = commit_reader_fix(d, rd, "P", R)
        except ValueError as e:
            return (f"Trial #9: a reader fix that changes nothing is recorded and counted (refused: {e})", False)
        body = G("log", "-1", "--format=%B").stdout
        empty = G("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.strip() == ""
        still = "A  staged.txt" in G("status", "--porcelain").stdout
        fixes, _ = reader_fix_history(d, "P")
        try:
            commit_reader_fix(d, rd, "P", R)
            third = False
        except ValueError as e:
            third = "spent" in str(e)
        ok = (n == 2 and files == [] and empty and still and f"rounds: P" in body and "no change" in body
              and [x[2] for x in fixes] == [1, 2] and fixes[-1][0] == h and third
              and reader_fix_prompt_problems(d, "P", R) == []
              and all(not p_ for _h, _r, p_ in reader_fix_commit_problems(d, "P")))
        return ("Trial #9: a reader fix that changes nothing is recorded as an empty \"reader-fix R n\" naming the "
                "rounds dir, counted toward the budget of 2 (the next is refused), passes the hash and edit checks, "
                "leaves staged work out, and another project's is not counted", ok)
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

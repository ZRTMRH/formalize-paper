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
import collections, datetime, fnmatch, functools, glob, hashlib, io, json, os, re, subprocess, time

AUDITS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(AUDITS)
PROJECTS = os.path.join(AUDITS, "projects")

REQUIRED = ["name", "source_pdf", "source_id", "source_cite", "branch", "base_commit",
            "lean_files", "build_cmds", "namespace", "sweep", "rounds_dir", "lanes",
            "calibration", "blind_spots"]
OPTIONAL = ["standing_defers", "index_file", "confidential", "goal", "goal_note", "notes",
            "lane_purpose", "title", "index_strict", "goal_results", "literature_hypotheses",
            "libraries", "work_dir", "glossary", "involvement", "involvement_answer", "mode"]
# The script registry (RULINGS D2), the one list of the apparatus's scripts, in selftest order.
# selftest_all.py runs the selftests, tests/mutants.py knows the Lean-backed ones, claude_settings.py
# allows the agent to run the agent-run ones without a prompt (RUN.md, AUDIT_PROTOCOL.md or the
# skill has the agent or a subagent run them), and codex/watchdog.py reads a failure line in any
# script's output as a checker's. {path under audits/ without .py: (selftest, agent-run)};
# selftest: "pure", "lean" (needs a built project), "pure+lean" (both: pure, then with --lean), None.
SCRIPTS = {
    "project": ("pure+lean", True), "prompt": ("pure", True), "scope": ("pure", True),
    "audit_coverage": ("pure", True), "phase0": ("pure", True), "integrity": ("pure", True),
    "signoff": ("pure+lean", True), "tree_state": ("pure", True), "make_report": ("pure", False),
    "render_record": ("pure", True), "hypotheses": ("pure", False), "result_status": ("pure", False),
    "decisions": ("pure", True), "readers": ("pure", True), "lanecheck": ("pure", True),
    "unused_args": ("pure", True), "codex_spawn": ("pure", False), "lane_auth": ("pure", True),
    "codex_agents": ("pure", False), "claude_settings": ("pure", False), "stops": ("pure", True),
    "tool_patch": ("pure", True),
    "tests/replay": ("pure", False), "tests/round3": ("pure", False), "tests/doclint": ("pure", False),
    "tests/tier": ("pure", False), "tests/snapshot_replay": ("pure", False), "tests/delivery": ("pure", False),
    "fingerprint": ("lean", False), "axiom_sweep": ("lean", True), "dependencies": ("lean", True),
    "selftest_all": (None, True),
}


def full(s):
    """`s` on one line, in full. Generated text a reader reads (a record quoted, a stop's note, a decision line)
    is never cut (a test run: readers flagged "...disclose it as true only vacuously (VACUOUS.md row 1) -- the
    adjudicator's recommendation. (decided on an earlier version of …" as clipped generator text); only a
    LABEL whose full text follows it (a heading, a table label) may be cut, with clip()."""
    return " ".join(str(s).split())


def clip(s, n):
    """`s` on one line, cut to at most `n` characters at a word boundary, " …" marking the cut: a
    cut mid-word read as a typo in the small-paper run's report ("not conf)")."""
    s = " ".join(str(s).split())
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0] if " " in s[:n] else s[:n]
    return cut.rstrip(",;:") + " …"


def scripts(selftest=None, agent_run=None):
    """Registry names (SCRIPTS order) with a selftest of this kind ("pure" or "lean"; "pure+lean"
    counts as both) and/or run by the agent."""
    return [n for n, (st, ar) in SCRIPTS.items()
            if (selftest is None or (st and selftest in st.split("+")))
            and (agent_run is None or ar == agent_run)]


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


_TERMS_CACHE = {}
_TERMS_FROM_PIN = False     # selftest only (A3): integrity.pinned_version reads the first pin in a --selftest process


def intake_terms(cfg):
    """The config the run's FIRST committed pin recorded (first_pin(...)["config"]), or {}: the intake fixes the
    involvement level and the mode (forgery review 2026-11 F4, DESIGN-E2 fix 3). Read in a real run, or in a
    --selftest process only when the cfg opts in (`_terms_from_pin`, A3); {} with no rounds dir, no committed pin or
    an unreadable one. Cached per rounds dir only once a pin was found: a process that commits the first pin and asks
    again gets it."""
    cfg = cfg or {}
    if _in_selftest() and not cfg.get("_terms_from_pin"):
        return {}
    rd = cfg.get("rounds_dir")
    if not rd:
        return {}
    try:
        key = os.path.realpath(os.path.join(REPO, str(rd)))
        if key in _TERMS_CACHE:
            return _TERMS_CACHE[key]
        if not os.path.isdir(key):
            return {}
        c = (first_pin(key) or {}).get("config")
    except Exception:       # noqa: BLE001 -- unreadable: the working config, as before
        return {}
    if not isinstance(c, dict):
        return {}
    _TERMS_CACHE[key] = c
    return c


def terms_differ(cfg):
    """[(key, working value, first pin's value)] for the intake terms the working config states differently from
    the first committed pin (the value every check uses)."""
    first = intake_terms(cfg)
    return [(k, (cfg or {}).get(k), first.get(k)) for k in ("involvement", "mode")
            if k in first and (cfg or {}).get(k) != first.get(k)]


def involvement(cfg):
    """The involvement level: the first committed pin's when it records one (intake_terms), else the configured
    one; "involved" when the key is absent. An invalid value is returned as it is (problems() reports it; callers
    refuse it rather than guess)."""
    first = intake_terms(cfg)
    v = first.get("involvement") if "involvement" in first else cfg.get("involvement")
    return "involved" if v is None else v


def delegates(cfg):
    """True when the level hands Checkpoint C (and every later stop) to the operator."""
    return involvement(cfg) in ("statements-only", "hands-off")


# Cause codes (RULINGS A9). Every FAIL/PROBLEM/WARNING/NOTE line a check prints starts with
# KIND[code]; the code, never the wording, decides what happens. {code: (class, what happens)}.
# A STOP class waits for the human at every level: `stops.py close --delegated` and a delegated
# `stops.py set-aside` refuse it. A code missing from this table (or a failure line with no code)
# is class "unknown", which is a stop: the table fails closed. The scripts keep that default; a
# failure no code covers (a traceback, an unwrapped git or Lean error) is first retried and then
# classified by the operator (RUN.md failure table), who records it under one of the three
# operator codes below: `unknown-retry`, `tool-bug` (a STOP class) or `env-unknown`.
STOP_CLASSES = ("tamper", "apparatus", "freeze", "gitmeta", "proof", "tool-bug", "unknown", "human")
CAUSES = {
    # lanecheck.py
    "independence": ("settle", "a lane names a record file: ADOPTED.md clears it in one line or re-votes the lane"),
    "quote-unmatched": ("settle", "a contradiction-step quote the text matcher did not find in the .tex: the "
                                  "adjudicator rules (QUOTE RULED ... in the paper at tex l.N / not in the paper)"),
    "independence-path": ("settle", "a lane cites another round's record or another lane's files: a whole-lane "
                                    "re-vote (no clearance)"),
    "lane-fault": ("lane-fault", "a lane's cited evidence is missing or changed before its seal: a re-vote"),
    "evidence-after-seal": ("tamper", "a lane's evidence changed after its seal commit"),
    "stray-file": ("mechanical", "a file appeared or vanished in the Lean repository during the lanes: restore "
                                 "the tree and tell the adjudicator"),
    "no-baseline": ("mechanical", "no Phase 0 tree baseline: run phase0.py before the lanes"),
    "stray-loop": ("mechanical", "a lane left a shell loop running: lanecheck --kill"),
    "no-round": ("mechanical", "no such round directory"),
    "unsettled": ("document", "ADOPTED.md does not settle every lane NOTE or carried-forward item"),
    "reissued": ("info", "a lane was reissued; its earlier verdict is kept for the adjudicator"),
    "superseded": ("info", "an old run's sealed lane re-run by a stall resolution"),
    # lane_auth.py
    "lane-output": ("mechanical", "no readable verdict: reissue the lane (lane_auth.py reissue)"),
    "unsealed": ("mechanical", "returned but not sealed: seal it from its own LANE_COMPLETION line"),
    "auth-metadata": ("tamper", "a token commitment or seal is missing, unreadable or changed"),
    "prompt-changed": ("tamper", "a lane prompt changed after its token was issued"),
    "seal-mismatch": ("tamper", "a verdict differs from its seal or token commitment"),
    "unauthenticated": ("tamper", "a round with lanes but no token commitments"),
    # stops.py
    "tool-call": ("mechanical", "a failed tool call that is not a check command (stops.py open --note)"),
    # the human stops no script detects (self-cure review H2): opened with stops.py open --note --cause
    # B13 (U2 §8): the statement-round cap reached with a faithfulness finding open (scope.py --statements)
    "round-cap": ("human", "the statement-round cap (4 before the first approval, 2 per re-approval) is reached while "
                           "the newest statement round leaves a faithfulness finding open: dev, the human decides; "
                           "release (project.round_cap_route), no stop: you judge its cause -- a genuine ambiguity of "
                           "the paper's meaning is stop 4 (`ambiguity`), a loose convention is decided as a reading "
                           "choice and disclosed, anything else goes on and every result it leaves open reads \"not "
                           "established: open faithfulness finding\" on the summary"),
    # the four release stops (approver, 2026-10-24): stop 3's outside interference and stop 4's genuine ambiguity
    "interference": ("human", "another program keeps changing the project's files during the run (a fault that recurs "
                              "however it is cured: tree-changed, head-moved, a record changed under you): stop 3, only "
                              "the user can stop it"),
    "ambiguity": ("human", "the paper's meaning is genuinely ambiguous on a point that matters and the reviewers cannot "
                           "converge on one reading (your judgement; a loose convention is a reading choice, not this): "
                           "stop 4, at every level -- show the passage, the possible readings and what each means for "
                           "the formalization, and ask the user to clarify"),
    "outward-action": ("human", "an outward action the intake did not allow (pushing, sending anything to the "
                                "authors, publishing): only the human allows it"),
    "codex-approval": ("human", "a Codex command approval prompt under a delegating level: never answered or "
                                "recorded as delegated; the person answers it"),
    "stop-trail": ("tamper", "the stop or set-aside record itself is inconsistent"),
    "resolution-trail": ("tamper", "an older run's stall-resolution record is inconsistent"),
    # operator codes for a failure with no cause code (stops.py open --note --cause <code>)
    "unknown-retry": ("mechanical", "a failure with no cause code, re-run within the retry budget: close the "
                                    "stop once its check passes, or reclassify it as tool-bug or env-unknown"),
    # L2 (U2 §8): a script's uncaught exception, printed by run_main as FAIL[uncoded] <script> (key of unknown-retry)
    "uncoded": ("mechanical", "a script crashed (an uncaught exception; its traceback is on stderr): re-run it "
                              "within the retry budget, as unknown-retry; it persists: tool-bug (the innermost "
                              "project frame is in audits/) or env-unknown"),
    "tool-bug": ("tool-bug", "a failure that persists after the retry and comes from a pinned script (a "
                             "traceback whose innermost project frame is in audits/), or a check that misjudges this "
                             "case: dev, only a maintainer fixes it; release, a tool patch reviewed by a fresh agent, "
                             "or for the proof-validity core a Lean-side workaround or stops.py core-fault, then close --core-fault "
                             "(tool_patch.py; RUN.md \"Tool patches\")"),
    "env-unknown": ("mechanical", "a failure with no cause code that persists after the retry and comes from the "
                                  "environment (git, Lean/lake, network, filesystem): fix it as an environment "
                                  "fault; a stop for the human after the retry budget"),
    # integrity.py
    "no-pin": ("apparatus", "no readable pin of the apparatus"),
    "tooling": ("apparatus", "the pinned apparatus changed"),
    "pyc": ("apparatus", "bytecode that can run without its source (sourceless, or unchecked-hash)"),
    "pyc-cache": ("info", "cached bytecode in audits/: project.py --env-check removes it"),
    "agent": ("apparatus", "the reviewer agent changed or is overridden"),
    "codex-roles": ("apparatus", "the Codex role definitions changed"),
    "config": ("apparatus", "a frozen config key changed or lost entries"),
    "config-grew": ("info", "a grow-only config key grew"),
    "before-pin": ("info", "commits before the first pin are not judged"),
    "repinned": ("info", "the apparatus was re-pinned (each re-pin states its reason)"),
    "ownership": ("tamper", "a record was committed by a commit that does not own it"),
    "acknowledged": ("info", "an ownership FAIL the human waived (a commit that only added files)"),
    "owner-redo": ("adjudication", "a verified revert put a record back over what its owner decided since: a fresh "
                                   "round's adjudication must re-decide it (review R1/R2)"),
    "acknowledged-fault": ("info", "a history FAIL no cure clears, acknowledged after a fresh reviewer judged it "
                                   "bookkeeping (integrity.py --ack-request; release; RUN_RECORD.md lists it)"),
    "reverted": ("info", "an ownership FAIL cured by a verified revert (release self-cure: stops.py revert)"),
    "waiver": ("tamper", "a waiver that is not the human's, or covers a commit that changed a record"),
    "set-aside-changed": ("tamper", "a set-aside record was changed"),
    "pin": ("tamper", "a forged or unstated pin commit, or (release) a plain re-pin that changed the tooling"),
    # OPERATOR-PATCH (tool_patch.py): a tool-patch link that does not verify, or a tool-patch commit in a dev run
    "tool-patch": ("tamper", "a tool patch whose record does not verify (tool_patch.py chain): restore the tooling of "
                             "the pin before it (git -C audits checkout <that pin's audits_commit> -- <the files>), "
                             "commit, re-pin (integrity.py --pin --repin \"restore after TP<k>\"); a fix still needed "
                             "is a new tool patch"),
    "record-changed": ("tamper", "a committed record changed and is not committed"),
    "uncommitted-record": ("mechanical", "a new lane file outside the round under review: seal its lane, or set "
                                         "the round (re-vote lane) aside with stops.py set-aside"),
    "dependencies": ("document", "DEPENDENCIES.json is missing, stale or does not match the walk, or the walk could "
                     "not run on the project: build it and rerun Phase 0"),
    "uncommitted-file": ("info", "an uncommitted author file in audits/"),
    # tree_state.py
    "gitmeta": ("gitmeta", "git hooks or config changed since the Stage 1 snapshot: release: python3 "
                           "audits/tree_state.py --restore-gitmeta restores only the snapshotted hooks and keys (a "
                           "changed remote, credential or user key, or rewritten history, also prints env-unknown: "
                           "the human); dev: only the human clears these"),
    "tree-changed": ("mechanical", "files appeared or vanished in the Lean repository since the baseline"),
    "git-error": ("mechanical", "a git command failed"),
    "head-moved": ("tamper", "HEAD moved since the baseline by a commit that changed files, a merge or another "
                             "author: a lane may have committed. Release: python3 audits/tree_state.py "
                             "--revert-foreign (git revert --no-edit over the whole foreign range, -m 1 for merges); "
                             "accepted when HEAD's tree equals the baseline's. Dev: only the human clears it"),
    "head-moved-operator": ("mechanical", "HEAD moved since the baseline only by the operator's empty commits (release: or its own "
                                          "commits up to a round's commit): "
                                          "tree_state.py --resave-operator --reason \"<which, why>\""),
    # fingerprint.py
    "not-approved": ("info", "nothing is approved: before Checkpoint B, or after an approval was moved aside by hand"),
    "drift": ("freeze", "an approved statement changed: restore the approved statement (git checkout <approval "
                        "commit> -- <its file>, or revert the edit) and commit; an intended change goes through "
                        "re-approval (reapproval.md: begin before the edit), never inside an open stop"),
    "reapproval": ("info", "a change to a declaration listed in the open re-approval (signoff.py reapprove "
                           "--begin, committed before the edit); signoff.py approve closes it"),
    "reapproval-record": ("tamper", "a REAPPROVAL.json the freeze check cannot trust: not committed as it is "
                                    "by signoff.py reapprove --begin"),
    # phase0.py (RED[<code>])
    "build": ("mechanical", "the Lean does not build: fix it and run Phase 0 again"),
    # B3: a sorry is the author's unfinished work (prove it, or follow Stage 3 for a result that
    # cannot be proved), not a stop; a token or axiom that leaves a proof unchecked is a stop
    "sorry": ("proof-wip", "a sorry, admit or sorryAx in the Lean: prove it (RUN.md failure table)"),
    "hard-token": ("proof", "a token that leaves a proof unchecked by the kernel"),
    "unproved": ("info", "a sorry inside a non-goal result left unproved by a logged [DELEGATED] decision "
                         "(stated, not proved; disclosed in SKIPPED.md, the report and DECISIONS.md)"),
    "unproved-meta": ("proof-wip", "a project elab/macro/elaborator attribute or addDecl/addAndCompile while a "
                                   "'leave <decl> unproved' line is active (it could manufacture an exempt "
                                   "auxiliary): remove it, or prove the results and drop their leave lines"),
    "unproved-goal": ("proof", "a goal result named in a 'leave <decl> unproved' [DELEGATED] line, or assumed "
                               "away (a missing-theory hypothesis that is its conclusion or restates it): a goal "
                               "result that stays unproved is a stop at every level"),
    "axiom": ("proof", "an axiom beyond the standard three"),
    # sweep M1: the same in the operator's own work (author-mode Phase 0): it rewrites the proof
    "hard-token-own": ("proof-wip", "a token that leaves a proof unchecked (native_decide, …) in your own Lean "
                                    "(author-mode Phase 0): rewrite the proof without it, commit, re-run Phase 0"),
    "axiom-own": ("proof-wip", "an axiom beyond the standard three in your own Lean (author-mode Phase 0; e.g. "
                               "Lean.ofReduceBool from native_decide, an `axiom`): rewrite the proof without it, "
                               "commit, re-run Phase 0"),
    "branch": ("mechanical", "not on the project's branch"),
    "unlisted": ("document", "a project .lean file is missing from lean_files"),
    "docstring": ("document", "a docstring placeholder or a tex line outside the source"),
    "run-log": ("document", "RUN_LOG.md does not mention every adjudicated round"),
    # approver 2026-10-27: a flag, never a stop, in every mode (disclosed)
    "escalation-cite": ("document", "a record cites an escalation never written or whose answer is not accepted "
                                    "(under involved: a re-ask of the human's question)"),
    "index": ("document", "the index check fails"),
    "unused-args": ("document", "UNUSED_ARGS.md could not be written"),
    "report": ("document", "the report check fails"),
    # B6 (U2 §7, F13): the operator's missing-theory decision line (hypotheses.missing_theory)
    "missing-theory": ("document", "a missing-theory line of RUN_LOG.md is not canonical, lacks the paper's quote or "
                                   "a configured library's search, comes from the wrong level, or names a hypothesis "
                                   "that is not in its result's assumption list: log a corrected line after it (a "
                                   "logged line is never reworded), or take the hypothesis as a binder of the result, commit, re-run "
                                   "Phase 0"),
    "baseline": ("mechanical", "the tree baseline could not be saved"),
    # an adjudicator-owned record (PAPER_DEFECTS/SKIPPED/VACUOUS.md) cites what does not exist: F, it
    # blocks, and the operator cures it at every level by a record correction (RUN.md failure table)
    "dead-witness": ("record-fix", "a PAPER_DEFECTS.md witness cell names something that is not a declaration of "
                                   "the project (`sorry`, a scratch-file lemma): record correction (prompt.py 4 "
                                   "--record-fix), or a new round if more than a cell must change"),
    "record-cite": ("record-fix", "a SKIPPED/PAPER_DEFECTS/VACUOUS.md (or the adjudicator's DEVIATIONS.md) cell "
                                  "cites a Lean name or file that does not exist: record correction (prompt.py 4 --record-fix), or a new round"),
    # deadlock sweep D1-D3: any other fault of an adjudicator-owned record (a cell count, a missing key
    # column, a prose-only defect, a missing-theory or [DELEGATED] "decided by", "formalized AND skipped",
    # a carried item without its row): only an adjudication clears it. Phase 0 prints it as
    # PENDING[adjudication]; --commit-adjudication and --deliver refuse while one remains
    "adj-record": ("adjudication", "an adjudicator-owned record (PAPER_DEFECTS/SKIPPED/VACUOUS.md, a carried item's "
                                   "row) is faulty: the next adjudication clears it (run a round: prompt.py 3 "
                                   "--full if no Lean changed); Phase 0 shows it as PENDING[adjudication]"),
    # U2 §6.4, ADDENDUM N1: the three delivery codes are never a stop (stops.py open refuses them, in both modes).
    # Approver (2026-10-28): deliver-stale is the math gate's and refuses --deliver; deliver and unverified are notes
    # project.py --deliver prints for the main agent, never a refusal
    "deliver": ("document", "project.py --deliver's own code, never a stop: RED, the math gate refused (Phase 0, the "
                            "freeze, the proof-validity core: fix what it names); as a note, a facts draft is stale or "
                            "missing, or a check of a delivered document fails: judge it (run/stage5-delivery.md)"),
    "unverified": ("document", "a note of project.py --deliver, never a stop and never a refusal: the verdicts are not "
                               "current (no full-scope round since the approval): judge it; a full round (prompt.py 3 "
                               "--full) brings them up to date"),
    "deliver-stale": ("document", "the math gate of project.py --deliver, never a stop: a .lean commit after the last "
                                  "audited round: run a diff round on it (prompt.py 3), then deliver; "
                                  "asked only until two rounds ran after the final full round (DELIVERY_ROUND_CAP): "
                                  "past that the commit ships disclosed"),
    # sweep L1: the adjudicator's and the record correction's own commit tools
    "commit-refused": ("mechanical", "integrity.py --commit-adjudication / --commit-record-fix refused: the "
                                     "adjudicator does what the message says in its turn and commits again"),
    "record-fix-diff": ("tamper", "a \"record-fix\" commit changed more than the faulty cells of an adjudicator's "
                                  "record (a verdict, a decision, a row, another file)"),
    "scope-changed": ("tamper", "a round's TARGET.json differs from its scope commit or from the scope recomputed "
                                "from its frozen inputs (scope.py --verify)"),
    "decisions": ("document", "the decisions document check fails"),
    "reader-check": ("document", "the fresh-reader record check fails (a finding the run mode does not disclose)"),
    "signoff-check": ("document", "the sign-off sheet check fails (a finding the run mode does not disclose)"),
    # release mode (RELEASE below): findings that never stop a release run; disclosed instead
    "render": ("presentation", "the report's rendering: LaTeX outside code, a line citation that names no line or "
                               "the wrong one, an undefined ID, a glyph or font warning"),
    "record-format": ("presentation", "a VACUOUS.md status in no known form (the row is kept, and treated as "
                                      "open)"),
    # legacy (PDF-AGENTS, approver 2026-10-23): no script emits it any more -- the PDFs are rendered and verified by
    # agents (render_record.py) and nothing about them is a stop or a disclosure. Kept so an older run's
    # DISCLOSED[pdf] records still parse and stay in README section D (stops.DELIVERY_PHASE_CODES)
    "pdf": ("presentation", "an older run's PDF fault (the render fix, removed): no longer emitted; the PDFs are "
                            "rendered and checked by agents (render_record.py), never a stop"),
    "reader": ("presentation", "the fresh-reader gate (findings about the generated text)"),
    "label": ("presentation", "a defect/vacuity record names a result one of whose rows is CHECK; its other "
                              "part rows are not"),
    "selftest": ("presentation", "a pre-pin self-test failure confined to checks of a non-blocking job"),
    # B9 (U2 §1 routing): a result's status that no route covers ("not established" for a reason result_status.py
    # cannot map): disclosed in release, a stop in dev
    "status-unmapped": ("presentation", "a result reads \"not established\" for a reason no route covers "
                                        "(result_status.py): never a stop, in either mode (approver 2026-10-28): a "
                                        "note of project.py --deliver; re-run Phase 0 (it rewrites DEPENDENCIES.json) "
                                        "or correct the index cell; what remains you judge from the records and the "
                                        "Lean, and SUMMARY and REPORT say the status you find"),
    "tool-fault": ("presentation", "a crash or persistent failure of a script whose job is non-blocking "
                                   "(SCRIPT_RELEASE): recorded with stops.py disclose, release mode only"),
}


def cause_class(code):
    """The class of a cause code; "unknown" (a stop) for a code not in CAUSES."""
    return CAUSES.get(code, ("unknown", ""))[0]


def is_stop_cause(code):
    return cause_class(code) in STOP_CLASSES


# Run mode (config `mode`, set at install: project_template.json carries it, `install.sh --dev`
# writes "dev"; frozen at the pin). `release` stops a run only for faithfulness (F), proof validity
# (P), integrity (I) and the human stops (H); a finding of class N (presentation, bookkeeping, a
# crash of a script that serves only them) is printed as DISCLOSED[<code>], does not fail its check,
# and is recorded with `stops.py disclose`. `dev` keeps every stop (today's behaviour). A config
# without the key is dev: the absent key fails closed. The table is CLASSIFICATION.md's (RELEASE).
MODES = ("release", "dev")


def mode(cfg):
    """The run mode: the first committed pin's when it records one (intake_terms), else the config's; dev when
    absent."""
    first = intake_terms(cfg)
    v = first.get("mode") if "mode" in first else (cfg or {}).get("mode")
    return "dev" if v is None else v


def mode_line(cfg):
    """What `prompt.py --show` (intake, Checkpoint A) says about the run mode."""
    m = mode(cfg)
    what = {"release": "only the four stops stop the run (a goal result false or unprovable, an outward action "
                       "not allowed, something only the human can fix -- another program changing the project's "
                       "files included --, a genuine ambiguity of the paper's meaning); a faithfulness, proof, "
                       "integrity or bookkeeping fault is cured by the agent with a fixed, logged step (an integrity "
                       "fault: restore the trusted version; a buggy audit tool: a patch an independent agent "
                       "reviews), a presentation fault is disclosed (stops.py disclose), and the run goes on",
            "dev": "every check stops the run, presentation and bookkeeping included"}.get(m)
    if what is None:
        return f"run mode: INVALID {m!r} (one of {', '.join(MODES)})"
    return f"run mode: {m}{'' if 'mode' in (cfg or {}) else ' (default: the config has no `mode` key)'} -- {what}"


def installed_mode():
    """The mode this installation writes into new configs (project_template.json), or None."""
    try:
        return json.load(open(os.path.join(AUDITS, "project_template.json"), encoding="utf-8")).get("mode")
    except (OSError, ValueError, AttributeError):
        return None


# The stop policy (U2 §0, §5; approver decisions 4 and 5, 2026-10-22; 2026-10-24: old stop 4, a cure that keeps
# failing, folded into stop 3 or the tool-patch route; stop 4 is now a genuine ambiguity): the four release stops, the same
# at every level, and what each level ASKS (a QUESTION, never a stop). One text, generated: the intake's
# paragraph under 5c (level None; stage0-intake.md carries the release one, tests/doclint.py checks it,
# intake_message() fills in the installation's) and the Checkpoint A line (`prompt.py --show intake`).
STOP_POLICY_STOPS = (
    "a goal result that looks false, or unprovable for a reason other than missing library theory (you "
    "will be shown why and asked how to proceed)",
    "something would be pushed, published or sent to the authors that you did not allow here",
    "something only you can fix: a login, administrator rights, more quota or payment, a change to your "
    "own files, or another program that keeps changing the project's files during the run",
    "the paper's meaning is genuinely ambiguous on a point that matters and the reviewers cannot converge on "
    "one reading (you will be shown the passage, the possible readings and what each would mean for the "
    "formalization, and asked which is meant, hands-off included; after your answer the run resumes at the "
    "level you chose)")
STOP_POLICY_ASKS = {
    "involved": "the agent asks you at Checkpoints B and C, and before any change to a statement you approved",
    "statements-only": ("the agent asks you before any change to a statement you approved, and keeps working "
                        "on everything else meanwhile: only the delivery waits for your answer"),
    "hands-off": "the agent asks you nothing; it decides, and the report discloses each decision",
}


def stop_policy_text(mode_, level=None):
    """The stop policy in words. `level` None: the intake paragraph (wrapped, indented as the intake
    block is) covering every level; a level: the one-line Checkpoint A summary of that mode and level."""
    stops_ = "; ".join(f"({i}) {t}" for i, t in enumerate(STOP_POLICY_STOPS, 1))
    if mode_ == "dev":
        rest = ("This is a development installation: the run also stops and waits for you whenever any "
                "other check fails, bookkeeping and the audit tools included (signs of tampering, tools "
                "changed from the pin); under (c) from the start, and under (b) once you have approved the "
                "statements, a stop caused by a check's bookkeeping rather than by the mathematics is cleared "
                "by the agent with a fixed, logged command, and the report lists every stop and who cleared it.")
    else:
        rest = ("Nothing else stops the run: a fault in a check's bookkeeping, in the audit records or in the "
                "tools (signs of tampering included), or a crashing check, is cured by the agent with a fixed, "
                "logged step (a bug in an audit tool: a patch an independent agent reviews first), and the run "
                "record lists it. A loosely used convention of the paper (say, whether the natural numbers start "
                "at 0 or at 1) is no stop either: the agent takes the intended reading and records the choice.")
    if level is None:
        asks = "; ".join(f"under ({k}) {STOP_POLICY_ASKS[lv]}"
                         for k, lv in zip("abc", INVOLVEMENT_LEVELS))
        import textwrap
        para = (f"Whatever you choose, the run stops and waits for you only for: {stops_}. {rest} Besides "
                f"these stops, the level decides what you are asked: {asks}. You cannot change this choice "
                f"once the run starts, short of starting a new run.")
        return textwrap.fill(para, width=96, initial_indent="    ", subsequent_indent="    ",
                             break_on_hyphens=False, break_long_words=False)
    what = STOP_POLICY_ASKS.get(level, f"INVALID level {level!r}")
    if mode_ == "dev":
        return (f"stop policy ({mode_}, {level}): every failing check stops the run, and in particular: "
                f"{stops_}; questions: {what}")
    return f"stop policy ({mode_}, {level}): the run stops for the human only for: {stops_}; questions: {what}"


# The release table (U2 §4): {cause code: (class, kind)}. The class is F, P, I, H or N; a code
# missing here is ("I", "rerun"): blocking, the unknown-retry route (fail closed). The kind says how a
# release stop of the code is cured and closed (KINDS); class H <=> kind human, class N <=> kind
# disclose (never a stop in release). The printed cure is CURES[kind] + CAUSES[code][1] (cure_text).
_F, _P, _I, _H, _N = "F", "P", "I", "H", "N"
# The four release stops (approver, 2026-10-24), the codes of kind human: (1) unproved-goal; (2) outward-action;
# (3) env-unknown, codex-approval, interference (something only the user can fix, another program that keeps
# changing the project's files included); (4) ambiguity (a genuine ambiguity of the paper's meaning: the operator's
# judgement). A cure that keeps failing (old stop 4) is classified by the operator (stops.py classify): a tool bug
# goes to the tool-patch route, outside interference is stop 3, anything else is another cure.
RELEASE_STOPS = {1: ("unproved-goal",), 2: ("outward-action",), 3: ("env-unknown", "codex-approval", "interference"),
                 4: ("ambiguity",)}
RELEASE_STOP_CODES = tuple(c for cs in RELEASE_STOPS.values() for c in cs)


# OPEN (awaiting the approver; one switch): what release does when the statement-round cap is reached with a
# faithfulness finding open. Approver 2026-10-24 (decision 3): no stop of its own -- the operator judges the cause:
# a genuine ambiguity -> stop 4 (`ambiguity`); a loose convention -> a reading-choice decision, disclosed;
# anything else -> go on, every result the finding leaves open reads "not established: open faithfulness
# finding" on the summary (result_status, scope.cap_record). Dev: unchanged, a human stop.
ROUND_CAP_ROUTE = "judge"           # "judge" (decision 3) or "stop" (round-cap a human stop in release too)


def round_cap_route(cfg):
    """How a statement-round cap reached with a faithfulness finding open is handled in this run: "stop" (dev,
    or release if ROUND_CAP_ROUTE says so: a human stop, --cause round-cap) or "judge" (release: no stop; the
    operator judges the cause, scope.cap_message names the three routes)."""
    return "stop" if mode(cfg) != "release" or ROUND_CAP_ROUTE == "stop" else "judge"


ROUND_CAP_RELEASE = (_H, "human") if ROUND_CAP_ROUTE == "stop" else (_N, "disclose")
# U2 §6.4 / ADDENDUM N1: the delivery codes. Each is a RED precondition of project.py --deliver, printed by
# make_report.py --check --delivery; none ever opens a stop, so the one-stop slot stays free for a fault
# in the rounds that clear them
DELIVERY_CODES = ("deliver", "unverified", "deliver-stale")
# approver (2026-10-23): the run never stops for a PDF. `pdf` is no longer emitted (PDF-AGENTS: agents render
# and verify, render_record.py, never a stop); it stays here for an older run's records (review 2): stops.py
# open refuses these codes in both modes, and a stop whose left_out holds one keeps its meaning
NEVER_STOP = frozenset(DELIVERY_CODES) | {"pdf"}
# approver (2026-10-28): after the mathematics is verified, the delivered documents are the main agent's, written from
# the records and judged by it on reviewers' advice: a reader finding, a document check and a status no route covers
# never open a stop either, in release or dev (run/stage5-delivery.md)
NEVER_STOP = NEVER_STOP | {"reader", "reader-check", "decisions", "status-unmapped"}
RELEASE = {
    **{c: (_I, "restore") for c in (
        "no-pin", "tooling", "pyc", "agent", "codex-roles", "config", "pin", "ownership", "waiver",
        "set-aside-changed", "record-changed", "record-fix-diff", "reapproval-record", "stop-trail",
        "resolution-trail", "uncommitted-record", "gitmeta", "tree-changed", "head-moved", "tool-patch")},
    **{c: (_I, "redo") for c in (
        "independence", "independence-path", "quote-unmatched", "evidence-after-seal", "auth-metadata", "prompt-changed",
        "unauthenticated", "seal-mismatch", "scope-changed")},
    **{c: (_F, "redo") for c in ("lane-fault", "unsettled", "owner-redo")},
    **{c: (_I, "rerun") for c in (
        "unsealed", "lane-output", "stray-file", "stray-loop", "no-round", "no-baseline", "baseline", "branch",
        "head-moved-operator", "tool-call", "git-error", "unknown-retry", "uncoded")},
    # OPERATOR-PATCH (approver, 2026-10-24): a pinned tool that misjudges or crashes is patched by the operator,
    # the patch reviewed by a fresh agent (tool_patch.py), never a stop
    "tool-bug": (_I, "patch"),
    **{c: (_F, "rerun") for c in (
        "index", "unused-args", "report", "missing-theory", "dead-witness", "record-cite", "adj-record", "commit-refused",
        "decisions", "reader-check", "signoff-check")},
    # ADDENDUM N1: preconditions of --deliver, never a stop (U2 §6.6 bounds their liveness)
    **{c: (_F, "precondition") for c in DELIVERY_CODES},
    "dependencies": (_P, "rerun"),
    **{c: (_P, "reprove") for c in (
        "build", "sorry", "hard-token", "hard-token-own", "axiom", "axiom-own", "unproved-meta", "unlisted")},
    "drift": (_F, "reprove"),
    **{c: (_H, "human") for c in RELEASE_STOP_CODES},
    "round-cap": ROUND_CAP_RELEASE,
    **{c: (_N, "disclose") for c in (
        "reissued", "superseded", "pyc-cache", "config-grew", "before-pin", "repinned", "acknowledged",
        "acknowledged-fault",
        "reverted", "uncommitted-file", "not-approved", "reapproval", "unproved", "docstring", "run-log",
        "escalation-cite",
        "render", "record-format", "pdf", "reader", "label", "selftest", "tool-fault", "status-unmapped")},
}
KINDS = ("rerun", "restore", "redo", "reprove", "patch", "human", "disclose", "precondition")
# the jobs of the scripts (a crash or self-test failure): N only where the job is presentation;
# every other script is blocking. {registry name: prefixes of its N self-test checks, or None: all}
# (review H2: the reader gate and its prompt guard the sheet's pre-approval faithfulness check, so
# readers.py and every other fresh-reader prompt check block; S1's check was the decisions reader's)
# scripts whose persistent failure in one path is a tool fault the release run discloses (stops.py disclose --note
# --cause tool-fault --script NAME) while its selftest still guards. None since PDF-AGENTS removed render_fix
TOOL_FAULT_SCRIPTS = ()
SCRIPT_RELEASE = {"tests/doclint": None,
                  "prompt": ("fresh-reader: under a delegating level the decisions reader",
                             "fresh-reader: the next report file is numbered")}


def release_class(code):
    return RELEASE.get(code, ("I", "rerun"))[0]


def release_kind(code):
    """The kind of cure of a code in a release run (KINDS); an unknown or uncoded one is rerun (the
    unknown-retry route)."""
    return RELEASE.get(code, ("I", "rerun"))[1]


# Release self-cure (approver, 2026-10-21; U2 §4; 2026-10-24). In release mode the run stops for the human only for
# the four stops of RELEASE_STOPS (codes of kind human). Every other stop is cured by the operator with the cure of
# its kind and closed `stops.py close --cured`, which re-runs the stop's read-only check (a FORMS command of
# stops.py: never a writer) and must pass; a tool that is itself wrong is patched (kind patch, tool_patch.py). When a
# cure keeps failing (a stop with CURE_BUDGET failed cures of its own, a (check script, code) with KEY_BUDGET failed
# cures in the run, or a fault opened more than OPEN_CEILING times in a round after a failed cure of it there;
# stops.tally) no further --cured is accepted until the operator classifies it (stops.py classify): a tool bug (the
# tool-patch route), outside interference (stop 3, the human's) or neither (another cure, logged). Dev mode:
# unchanged (every stop waits).
CURE_BUDGET = 2       # failed self-cures of one stop (the per-stop cap; stops.tally)
KEY_BUDGET = 3        # failed self-cures of one (script, code) in the whole run (stops.tally): a flaky check failing
                      # one cure in each of two far-apart rounds is not yet spent; a third failure is (re-check H1)
OPEN_CEILING = 3      # openings of one fault key in one round after a failed cure of it there (stops.tally)
CURES = {
    "rerun": ("fix the mechanical problem the code names, then re-run the check (close --cured re-runs it); a "
              "crash that persists: re-run the review by another route (a fresh round), never skip it"),
    "restore": ("go back to the last trusted version -- the pinned apparatus (git -C audits checkout <pin commit> "
                "-- <the files the FAIL names>), a committed record change (python3 audits/stops.py revert --stop "
                "S<n> --commit <the commit the FAIL names>: it restores the records that commit changed, committed "
                "as \"revert <commit> (stop S<n>)\", which integrity.py accepts once verified), an uncommitted one "
                "(git checkout <file>) -- then re-run the check; a FAIL in the committed history that no restore or "
                "revert clears (a past re-pin, a mistyped pin subject, a record its owner re-committed after a hand "
                "edit, an unverifiable tool-patch link, a damaged stop trail): the reviewed acknowledgment (python3 "
                "audits/integrity.py --ack-request --diagnosis \"<what happened, why nothing it judges changed>\"; a "
                "fresh reviewer judges it; then close --cured \"acknowledgment AK<k>\")"),
    "redo": ("restore the changed record if needed (git checkout <file>), set the affected round aside "
             "(stops.py set-aside <R> --reason \"release self-cure of S<n>\" --stop S<n>) and re-run its "
             "review in a fresh round (prompt.py 3; fresh lanes and adjudicator): its independence was "
             "compromised. An ADJUDICATED round is never set aside: restore what changed after its seal or commit "
             "(git checkout <the sealed or committed version> -- <file>) and re-run the check; a lane that cannot be "
             "restored is re-voted (the adjudicator's REVOTE NEEDED row, a fresh re-vote lane, \"adjudicate R "
             "revotes\"); an unsettled NOTE or carried item is settled by the round's adjudicator (its ADOPTED.md "
             "rows, integrity.py --commit-adjudication)"),
    "reprove": ("change the Lean (rewrite the proof without the token or axiom, or restore the approved "
                "statement), commit, then run Phase 0 and the build"),
    "patch": ("if a read-only check fails because of a mechanical problem, fix it and re-run the check (close "
              "--cured re-runs it); if the pinned tool itself is wrong (it crashes, or misjudges this case): "
              "diagnose it and patch it through python3 audits/tool_patch.py begin --stop S<n> (RUN.md, \"Tool "
              "patches\": a fresh reviewer approves the patch; then close --cured \"tool-patch TP<k>\"); a fault in "
              "the proof-validity core (no patch may touch it): a Lean-side workaround, else stops.py core-fault (a fresh "
              "reviewer judges it), then close --core-fault <file> (what the check guarantees reads \"not verified\", "
              "never waited on); never edit a pinned "
              "script by hand"),
    "human": ("a human stop: show the human the raw output and wait; close it with --human \"<their answer, "
              "verbatim>\""),
    "disclose": "not a stop in release mode: it is disclosed (stops.py disclose)",
    "precondition": ("not a stop, in either mode: deliver-stale refuses project.py --deliver (a diff round); the "
                     "others are notes it prints for you to judge, or document checks you fix (approver 2026-10-28)"),
}


def cure_text(code):
    """The printed cure of a code in a release run: CURES[its kind] + what the code says (CAUSES)."""
    what = CAUSES.get(code, CAUSES["unknown-retry"])[1]
    return f"{CURES[release_kind(code)]} [{code}: {what}]"


# The read-only check (a FORMS command of stops.py) that closes a release stop of each code, by the
# script that reports it; "@check" for a code with no check of its own: its stop records the read-only
# check of the step that failed at open (open --note --cause <code> --check "<it>"). A --cmd stop always
# re-runs its own --cmd. Kinds human and disclose have none.
_CLOSER_GROUPS = {
    "integrity.py --check": (
        "no-pin", "tooling", "pyc", "agent", "codex-roles", "config", "pin", "ownership", "waiver",
        "set-aside-changed", "record-changed", "record-fix-diff", "reapproval-record", "stop-trail",
        "resolution-trail", "uncommitted-record", "tool-patch", "owner-redo"),
    "tree_state.py --check": ("tree-changed", "gitmeta", "head-moved", "head-moved-operator"),
    "lanecheck.py --round {R}": (
        "independence", "independence-path", "quote-unmatched", "lane-fault", "evidence-after-seal", "auth-metadata",
        "prompt-changed", "unauthenticated", "seal-mismatch", "unsealed", "lane-output",
        "stray-file", "stray-loop", "no-round", "no-baseline"),
    # RELEASE-SWEEP G4: settledness is printed only with --settled; plain `lanecheck --round R` never checks it
    "lanecheck.py --round {R} --settled": ("unsettled",),
    "scope.py --verify --round {R}": ("scope-changed",),
    "phase0.py --readonly": (
        "baseline", "branch", "dependencies", "unused-args", "build", "sorry", "hard-token", "hard-token-own",
        "axiom", "axiom-own", "unproved-meta", "unlisted"),
    "make_report.py --check": ("index", "report", "missing-theory", "dead-witness", "record-cite", "adj-record"),
    "decisions.py --check": ("decisions",),
    "readers.py --doc report --check": ("reader-check",),
    "signoff.py check --round {R}": ("signoff-check",),
    "fingerprint.py --check": ("drift",),
    "@check": ("tool-call", "git-error", "unknown-retry", "uncoded", "tool-bug", "commit-refused"),
}
CLOSER = {c: form for form, cs in _CLOSER_GROUPS.items() for c in cs}


def closer(code, round_name="<R>"):
    """The command that closes a release stop of `code` (python3 audits/<form>, the round filled in),
    "@check" (the check recorded at open), or None (kind human or disclose: no self-cure). Total: a round of None
    reads as "<R>" (a stop opened with no --round, whose closer has no {R}, once crashed here: STATUS A1)."""
    if release_kind(code) in ("human", "disclose", "precondition"):
        return None
    form = CLOSER.get(code, "@check")
    return form if form == "@check" else "python3 audits/" + form.replace("{R}", round_name or "<R>")


def release_cure(cfg, codes):
    """[kinds] when a stop with these cause codes is the operator's to cure in this run (release mode,
    no cause of kind human, at least one that is not disclosed), else None (dev mode, or a human stop
    of release)."""
    codes = list(codes)
    if mode(cfg) != "release" or not codes or any(release_kind(c) == "human" for c in codes):
        return None
    return sorted({release_kind(c) for c in codes} - {"disclose", "precondition"}) or None


def closer_table():
    """RUN.md's release closer table (doclint checks RUN.md carries it verbatim): one row per kind."""
    rows = ["| kind | codes | cure (`project.CURES`) | closes with |", "|---|---|---|---|"]
    for k in KINDS:
        # review 2026-10-28: a code that never opens a stop (NEVER_STOP) and is not disclosed is listed as no stop
        cs = sorted(c for c in RELEASE if ("precondition" if c in NEVER_STOP and release_kind(c) != "disclose"
                                           else release_kind(c)) == k)
        how = {"human": "`close --human`", "disclose": "no stop: `stops.py disclose`",
               "patch": "`close --cured`, re-running the `--check` recorded at open (a stop with none: `close --cured "
                        "\"tool-patch TP<k>\"`, re-running the patch's regression test)",
               "precondition": "no stop: `project.py --deliver` refuses on `deliver-stale` only; the others are "
                               "notes"}.get(k)
        if how is None:
            forms = sorted({CLOSER.get(c, "@check") for c in cs})
            how = "`close --cured`, re-running " + ", ".join(
                "the `--check` recorded at open" if f == "@check" else f"`{f.replace('{R}', '<R>')}`" for f in forms)
        rows.append(f"| {k} | {', '.join(f'`{c}`' for c in cs)} | {CURES[k]} | {how} |")
    return "\n".join(rows)


def disclosed(cfg, code):
    """True when a finding of this code is disclosed instead of failing: release mode and class N; and
    escalation-cite in every mode (approver, 2026-10-27: a flag, never a stop)."""
    return code == "escalation-cite" or (mode(cfg) == "release" and release_class(code) == "N")


class Finding(str):
    """A problem string with a cause code, so a check can tell a disclosed one from a blocking one;
    still a plain string to every caller (and in dev mode it blocks exactly as before)."""
    def __new__(cls, text, code):
        f = str.__new__(cls, text)
        f.code = code
        return f


def split(cfg, problems):
    """(blocking, disclosed) of a check's problem strings: a Finding whose code is disclosed in this
    run's mode goes to the second list, everything else stays blocking."""
    block, disc = [], []
    for p in problems:
        (disc if isinstance(p, Finding) and disclosed(cfg, p.code) else block).append(p)
    return block, disc


def problem_line(p, default, kind="PROBLEM"):
    """How a blocking finding is printed: KIND[<code>] <text>, the code a Finding's own or `default`
    (stops.causes classifies a failure line by its code; an uncoded line is "unknown", a human stop)."""
    return f"{kind}[{getattr(p, 'code', None) or default}] " + " ".join(str(p).lstrip("! ").split())


def disclosed_line(p):
    """How a disclosed finding is printed: DISCLOSED[<code>] <text> (stops.py disclose records it)."""
    # never a failure line to stops.causes (whose pattern also matches "error:" anywhere)
    return f"DISCLOSED[{p.code}] " + re.sub(r"\berror:", "error -", " ".join(str(p).lstrip("! ").split()))


def selftest_release(script, output, rc):
    """None if the selftest failure of `script` (registry name) blocks, else the disclosed lines: its
    job is N (SCRIPT_RELEASE), or every FAIL line names a check of an N prefix and nothing crashed."""
    if rc == 0 or script not in SCRIPT_RELEASE:
        return None
    pre = SCRIPT_RELEASE[script]
    fails = [m.group(1).strip() for m in re.finditer(r"^\s*FAIL\s+(.*)$", output, re.M)]
    if pre is not None and (not fails or "Traceback" in output or "CRASH" in output
                            or not all(f.startswith(pre) for f in fails)):
        return None
    return [Finding(f"{script}.py selftest: {f}", "selftest") for f in fails] or \
        [Finding(f"{script}.py selftest exited {rc}", "selftest")]
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

# Words that name a paper result in PROSE and in record cells ("Lemma 2.1" in a SKIPPED row, a defect's `where`
# cell, a lane's item), matched case-insensitively. The INDEX is not read through this list: it has its own, INDEX_KINDS
# (index_table below; E2E-FIX2c). This list only helps the prose readers find a
# label; "Hypothesis", "Assumption" and "Condition" stay out of it on purpose, because records use those words for
# Lean hypotheses ("hypothesis `hW`"), which must keep being read as declaration items. Multi-word kinds come first.
RESULT_KINDS = ["Open problem", "Open question", "Definition", "Lemma", "Theorem", "Proposition", "Corollary",
                "Claim", "Remark", "Example", "Conjecture", "Fact", "Observation", "Construction", "Problem",
                "Question", "Exercise", "Algorithm", "Axiom"]
RESULT_KINDS_RE = "|".join(RESULT_KINDS)

# The index table: the line reader of 99d928e (scope.INDEX_ROW), its label words widened only by E2E finding #3
# (the e2e run's "Problem 1.1" and "Problem 6.4" rows were skipped by every reader, with no warning): a row is
# `| <kind> <rest of label> | <rest> |` at column 0, <kind> one of INDEX_KINDS, case as written. Every other `|…|…|`
# line that is not a separator or a table's header row is returned as skipped, and the index check names them in
# one NOTE (E2E-FIX2c: never dropped without a word; a formula line in a docstring, `|f x - f y| ≤ C * |x - y|`, is
# then a NOTE, never a failure).
INDEX_KINDS = ["Definition", "Lemma", "Theorem", "Proposition", "Corollary", "Claim", "Remark", "Example",
               "Conjecture", "Fact", "Observation", "Construction", "Problem", "Question"]
INDEX_ROW = re.compile(rf"^\|\s*((?:{'|'.join(INDEX_KINDS)})\s[^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
INDEX_LINE = re.compile(r"^\|\s*([^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
TABLE_SEP = re.compile(r"^\|[\s:|-]*-[\s:|-]*$")


def index_table(text):
    """([(label, rest, line)], [skipped line]) of an index file's text: every result row (INDEX_ROW), in order, and
    every other `|…|…|` line that is not a separator or a header row (the row above a separator, or one labelled
    "Paper"). For a row 99d928e read, `label` and `rest` are exactly what it read."""
    lines = (text or "").splitlines()
    rows, skipped = [], []
    for i, line in enumerate(lines):
        s = line.rstrip()
        m = INDEX_ROW.match(s)
        if m:
            rows.append((m.group(1).strip(), m.group(2), s))
            continue
        m = INDEX_LINE.match(s)
        nxt = lines[i + 1].rstrip() if i + 1 < len(lines) else ""
        if m and not TABLE_SEP.match(s) and not TABLE_SEP.match(nxt) and m.group(1).strip().lower() != "paper":
            skipped.append(s)
    return rows, skipped


def index_rows(text):
    """[(label, rest)] of the index table's result rows (index_table): THE reader of the index, for the freeze, the
    scope, the sheet, the coverage table, the statuses and the README alike."""
    return [(lab, rest) for lab, rest, _l in index_table(text)[0]]


DECISIONS = ("ADOPT", "REJECT", "DEFER", "QUESTION", "REVOTE NEEDED", "UNCOVERED")


def decision_of(cell):
    """The decision an ADOPTED.md decision cell records, or None: THE parser of that cell, for the
    carry check, the settle check, the re-vote list and the report alike (ROUND3 M2: `REJECT` in
    backticks read as "not a REJECT" to one and as REJECT to the other). Struck-through text
    (~~ADOPT~~) is dropped; bold, italics and backticks are formatting. The keyword must open the
    cell; anything else is None (the settle check refuses such a row)."""
    t = re.sub(r"~~.*?~~", " ", str(cell))
    t = re.sub(r"[*_`]+", " ", t)
    t = " ".join(t.split()).upper()
    for d in DECISIONS:
        if re.match(rf"{d}\b", t):
            return d
    return None


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


def index_file(cfg):
    """The Lean file holding the index table: config `index_file`, else the first *Main.lean of
    `lean_files`, else its first file; None without lean files."""
    lf = cfg.get("lean_files") or []
    return cfg.get("index_file") or next((x for x in lf if x.endswith("Main.lean")), lf[0] if lf else None)


def approval_order(path):
    """Sort key of an approval file, in the order the approvals were made: the moved-aside copies
    APPROVED_FINGERPRINTS.<date>[.<k>].json by date, then k numerically (unnumbered first, then .2, .3, ..., .10),
    the current APPROVED_FINGERPRINTS.json last (`signoff.py approve` names them so; B4 review fix 4)."""
    m = re.fullmatch(r"APPROVED_FINGERPRINTS\.(.+?)(?:\.(\d+))?\.json", os.path.basename(path))
    return (1, "", 0) if not m else (0, m.group(1), int(m.group(2) or 1))


def round_commit(name):
    """The commit a round directory was cut from: always the last dash-separated field."""
    return os.path.basename(name).split("-")[-1]


def is_full_round(name):
    return "-full-" in os.path.basename(name)


def git(*args):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


# Tier 1 runs the selftests once per involvement level (tests/TIERS.md): a selftest must not
# depend on the level of the project it runs in (small-paper run, stop S1: one used the run's own
# hands-off config as its baseline). Honoured only by a process run with --selftest; a real run
# never sees another level than its configuration's.
TEST_LEVEL_ENV = "FORMALIZE_TEST_INVOLVEMENT"
# Tier 1 also runs them once per run mode (MAINTAINING S3: a release-mode change never alters dev
# mode). Same rule: honoured only by a --selftest process, so a real run's mode stays the one
# frozen in its config at install (A3).
TEST_MODE_ENV = "FORMALIZE_TEST_MODE"


def _in_selftest(argv=None):
    """Is this process a selftest: its command IS `--selftest` (the first argument once `--project NAME` is set
    aside), never a real command that also carries the flag (attack review E H1: `--deliver --selftest` delivered
    under the working config's level and the test tier's variables)."""
    a = list(sys.argv if argv is None else argv)[1:]
    if "--project" in a:
        i = a.index("--project")
        a = a[:i] + a[i + 2:]
    return a[:1] == ["--selftest"]


def _test_mode(argv=None, env=None):
    """The run mode the test tier asks for, or None (not a --selftest process, or unset)."""
    m = (os.environ if env is None else env).get(TEST_MODE_ENV)
    return m if m and _in_selftest(argv) else None


def _test_level(cfg, argv=None, env=None):
    env = os.environ if env is None else env
    lvl, m = env.get(TEST_LEVEL_ENV), _test_mode(argv, env)
    if not _in_selftest(argv):
        return cfg
    if lvl:
        cfg = dict(cfg, involvement=lvl, involvement_answer=f"({lvl}, set by the test tier)")
    if m:
        cfg = dict(cfg, mode=m, _test_mode=m)    # the marker lets problems() accept it (this process only)
    return cfg


class steady_git_clock:
    """Selftests only (polish 2026-10-24, T28): a context in which every process this one starts commits with
    GIT_AUTHOR_DATE/GIT_COMMITTER_DATE read from the MONOTONIC clock (anchored at the wall clock on entry). Rounds
    are ordered by commit time where ancestry cannot decide (order_rounds), and under load this machine's wall
    clock stepped back by ~3 s twice a minute (WSL time sync), so a fixture's later commit could carry an earlier
    second and reorder its rounds: the stops.py "release-cure M4" failure. A date the caller sets is kept."""
    def __enter__(self):
        import time
        self._w, self._m, self._init = time.time(), time.monotonic(), subprocess.Popen.__init__
        clock, init = self, self._init

        def popen_init(p, *a, **k):
            env = dict(os.environ if k.get("env") is None else k["env"])
            if "GIT_COMMITTER_DATE" not in env and "GIT_AUTHOR_DATE" not in env:
                d = f"{int(clock._w + time.monotonic() - clock._m)} +0000"
                env.update(GIT_COMMITTER_DATE=d, GIT_AUTHOR_DATE=d)
            k["env"] = env
            init(p, *a, **k)
        subprocess.Popen.__init__ = popen_init
        return self

    def __exit__(self, *exc):
        subprocess.Popen.__init__ = self._init
        return False


def _steady_clock_controls():
    """steady_git_clock: commit times follow the monotonic clock even when the wall clock steps back."""
    import shutil, tempfile, time
    d = tempfile.mkdtemp(prefix="steady-clock-")
    real, mono = time.time, time.monotonic
    try:
        g = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      capture_output=True, text=True).stdout.strip()
        g("init", "-q")
        with steady_git_clock():
            g("commit", "-q", "--allow-empty", "-m", "one")
            time.time = lambda: real() - 3600        # the wall clock steps back an hour; 100 s pass
            time.monotonic = lambda: mono() + 100
            g("commit", "-q", "--allow-empty", "-m", "two")
            pinned = subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                                     "--allow-empty", "-m", "three"], capture_output=True,
                                    env=dict(os.environ, GIT_COMMITTER_DATE="1000000000 +0000",
                                             GIT_AUTHOR_DATE="1000000000 +0000")).returncode == 0
        time.time, time.monotonic = real, mono
        ts = [int(x) for x in g("log", "--format=%ct").split()]
        after = subprocess.Popen.__init__ is not None and "popen_init" not in subprocess.Popen.__init__.__name__
        return [("steady_git_clock (T28): commit times follow the monotonic clock, not a wall clock stepped back; a "
                 "date the caller sets is kept; leaving the context restores subprocess",
                 pinned and len(ts) == 3 and ts[0] == 1000000000 and 100 <= ts[1] - ts[2] < 700 and after)]
    finally:
        time.time, time.monotonic = real, mono
        shutil.rmtree(d, ignore_errors=True)


def all_projects():
    out = {}
    for path in sorted(glob.glob(os.path.join(PROJECTS, "*.json"))):
        cfg = _test_level(json.load(open(path, encoding="utf-8")))
        cfg["_path"] = path
        out[cfg.get("name", os.path.basename(path)[:-5])] = cfg
    return out


class SelectionError(Exception):
    pass


def select(name=None):
    """(config, why it was selected). Refuses a config with a hard error (a "!" line of problems();
    RULINGS A10f): every script then runs on a valid config, not only the ones that print the
    problems. A missing source_pdf is not refused for a project of another branch (the file may
    exist only on its own branch)."""
    cfg, why = _select(name)
    branch = git("branch", "--show-current")
    hard = [p[2:] for p in problems(cfg) if p.startswith("!")
            and not (p.startswith("! source_pdf does not exist") and cfg.get("branch") != branch)]
    if hard:
        raise SelectionError(f"project {cfg.get('name')!r} has hard config error(s): " + "; ".join(hard))
    return cfg, why


def _select(name=None):
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


# A round given up before adjudication (stops.py set-aside, RUN.md "Stops and set-asides"): its
# files stay in the record, committed, with this marker; no script reads it as a round (its
# unadjudicated verdicts must not count as passes, nor its commit as the previous round's).
ABANDONED = "ABANDONED.json"


def is_abandoned(round_dir):
    return os.path.exists(os.path.join(round_dir, ABANDONED))


def is_round(p):
    """A round-named directory is a round once scope.py wrote its TARGET.json (or an adjudicator its
    ADOPTED.md). A directory holding only prompts (fresh-reader prompts written with --round <new>,
    lane prompts of an empty-scope round) examined nothing: taken as the newest round it became the
    base of the next diff round and hid the commits after the real one (review of fix-mini1, M1)."""
    return (os.path.isdir(p) and ROUND_RE.match(os.path.basename(p)) is not None
            and any(os.path.exists(os.path.join(p, f)) for f in ("TARGET.json", "ADOPTED.md")))


def rounds(cfg, include_abandoned=False, repo=None):
    """Round directories of this project (is_round), oldest first (order_rounds, resolving commits
    in `repo`, default REPO). Abandoned rounds are left out unless asked for."""
    d = os.path.join(REPO, cfg["rounds_dir"])
    return order_rounds([p for p in glob.glob(os.path.join(d, "*"))
                         if is_round(p) and (include_abandoned or not is_abandoned(p))], repo or REPO)


_ANCESTOR = {}


def _resolve(repo, h):
    """(full sha, commit time) of a round's commit in `repo`, or (None, None)."""
    if not repo:
        return None, None
    r = subprocess.run(["git", "-C", repo, "show", "-s", "--format=%H %ct", f"{h}^{{commit}}", "--"],
                       capture_output=True, text=True)
    out = r.stdout.split()
    return (out[0], int(out[1])) if r.returncode == 0 and len(out) == 2 and out[1].isdigit() else (None, None)


def _is_ancestor(repo, a, b):
    if (repo, a, b) not in _ANCESTOR:
        _ANCESTOR[(repo, a, b)] = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", a, b],
                                                 capture_output=True).returncode == 0
    return _ANCESTOR[(repo, a, b)]


def _scope_time(d):
    """When a round was cut: the commit that added its directory (its scope commit, in whatever
    repository holds it), else the directory's mtime."""
    r = subprocess.run(["git", "-C", d, "log", "--diff-filter=A", "--format=%ct", "--", "."],
                       capture_output=True, text=True)
    t = r.stdout.split()
    return int(t[-1]) if r.returncode == 0 and t and t[-1].isdigit() else os.path.getmtime(d)


def order_rounds(dirs, repo):
    """Round directories oldest first: the one home of round order (RULINGS D2).

    By Lean ANCESTRY of the commit each round was cut from (`merge-base --is-ancestor`), resolved in
    `repo` (None: resolve nothing). Neither directory names nor commit times are order: two rounds of
    one date fell through to the hex hash (2026-09-29: `7759e702fdb`, 19:35, sorted after
    `60672ca5567`, 21:02, and step 4 was handed an adjudicated round), and a commit time can run
    backwards after a rebase or amend. The order sets scope.previous_commit, the diff base, so a
    wrong order silently drops changed declarations from a diff round.
      * commits on diverged lines (neither an ancestor): by commit time;
      * a hash git cannot resolve (amended, pruned): by its directory's time against the other's
        commit time;
      * the same commit (a full round cut where a diff round was), or still equal: by scope time
        (_scope_time), then by name, so the order never flaps.
    """
    info = {d: _resolve(repo, round_commit(d)) for d in dirs}
    tie = functools.lru_cache(maxsize=None)(lambda d: (_scope_time(d), os.path.basename(d)))

    def cmp(a, b):
        (ha, ta), (hb, tb) = info[a], info[b]
        if ha and hb and ha != hb:
            if _is_ancestor(repo, ha, hb):
                return -1
            if _is_ancestor(repo, hb, ha):
                return 1
        if ha != hb or not ha:
            xa = ta if ta is not None else tie(a)[0]
            xb = tb if tb is not None else tie(b)[0]
            if (ta is not None or tb is not None) and xa != xb:
                return -1 if xa < xb else 1
        ka, kb = tie(a), tie(b)
        return (ka > kb) - (ka < kb)
    return sorted(dirs, key=functools.cmp_to_key(cmp))


def log_append(cfg, section, text, replace=False):
    """Append `text` (one or more lines) under `## <section>` of the run's RUN_LOG.md, creating the
    section before `## Current stage` when it is missing; `replace` sets the section's first
    paragraph instead (for `Current stage`), keeping anything written below it. The section is
    matched by its exact name ("## Stops" never matches "## Stops resolved"), optionally followed by
    a parenthesised date; a heading line in `text` is refused (it would start a section of its own).
    The supported way to write the log from a script or a command, so that no operator improvises a
    `python3 - <<EOF` edit (which asks for permission in Claude Code's default mode). A missing rounds
    directory is created when it is the project's audits/<name> (Stage 1 step 5 is the first write
    there: STATUS A4), else ValueError and nothing is written. Returns the log's path."""
    path = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(path, encoding="utf-8").read() if os.path.exists(path) else f"# Run log — {cfg.get('name', '')}\n"
    body = "\n".join(l.rstrip() for l in str(text).strip("\n").splitlines()) + "\n"
    if not body.strip():
        raise ValueError("nothing to log")
    if re.search(r"^\s*#", body, re.M):
        raise ValueError("a log entry may not contain a heading line (# …): it would start a section")
    m = re.search(rf"^## {re.escape(section)}[ \t]*(?:\([^)\n]*\))?[ \t]*\n", log, re.M)
    if m:
        nxt = re.search(r"^## ", log[m.end():], re.M)
        end = m.end() + nxt.start() if nxt else len(log)
        old = log[m.end():end].strip("\n")
        if replace:
            # only the stage line itself: every line below it, blank-separated or not, stays
            rest = old.split("\n", 1)[1] if "\n" in old else ""
            content = body + ((rest.strip("\n") + "\n") if rest.strip() else "")
        else:
            content = ((old + "\n") if old else "") + body
        log = log[:m.end()] + content + ("\n" + log[end:] if nxt else "")
    else:
        cs = re.search(r"^## Current stage\b", log, re.M)
        block = f"## {section}\n{body}"
        if cs and section != "Current stage":
            log = log[:cs.start()] + block + "\n" + log[cs.start():]
        else:
            log = log.rstrip("\n") + "\n\n" + block
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        top = os.path.realpath(os.path.join(REPO, "audits"))
        if not os.path.realpath(folder).startswith(top + os.sep):
            raise ValueError(f"rounds_dir {cfg['rounds_dir']!r} does not exist and is not under audits/: "
                             f"not created")
        if os.path.normpath(str(cfg["rounds_dir"])) != os.path.join("audits", str(cfg.get("name", ""))):
            # compat review L5 (batch A): only the rounds directory the config template names (audits/<name>) is
            # created; a misspelt one fails as before, never a new empty log beside the run's
            raise ValueError(f"rounds_dir {cfg['rounds_dir']!r} does not exist and is not audits/{cfg.get('name')} "
                             f"(project_template.json's rounds_dir): not created")
        os.makedirs(folder, exist_ok=True)
    open(path, "w", encoding="utf-8").write(log)
    return path


# RUN.md's stage map: the file the operator reads on arriving at each stage (B1). `--stage` prints
# it, so a resumed conversation, which reads only RUN.md, is told which file holds its stage.
STAGE_FILES = {0: "run/stage0-intake.md", 1: "run/stage1-setup.md", 2: "run/stage2-statements.md",
               3: "run/stage3-proofs.md", 4: "run/stage4-rounds.md", 5: "run/stage5-delivery.md"}
# procedures read when they apply, named in RUN.md's stage map
PROCEDURE_FILES = ["run/spawn-and-seal.md", "run/fresh-reader.md", "run/render-pdf.md", "run/reapproval.md",
                   "run/stops-and-set-asides.md", "run/codex.md"]


INTAKE_HEADING = "## The intake message"


def intake_message():
    """The intake message (B6): the first fenced block under "## The intake message" in the Stage 0
    file. `prompt.py --intake` prints it and the operator sends it unchanged, so no question is
    composed, merged or lost by hand. None if the block is missing."""
    try:
        text = open(os.path.join(AUDITS, STAGE_FILES[0]), encoding="utf-8").read()
    except OSError:
        return None
    i = text.find("\n" + INTAKE_HEADING + "\n")
    m = re.search(r"^```text\n(.*?)^```", text[i:], re.S | re.M) if i >= 0 else None
    if not m:
        return None
    # the stop policy paragraph is generated (stop_policy_text): the file carries the release one,
    # a dev installation sends its own
    msg, inst = m.group(1), installed_mode()
    if inst == "dev":
        msg = msg.replace(stop_policy_text("release"), stop_policy_text("dev"))
    return msg


def intake_hash(message=None):
    """First 16 hex digits of the intake message's sha256: the line `intake-message sha256 <hex>`
    that RUN_LOG.md's "## Intake" carries (integrity.py --pin refuses without it)."""
    import hashlib
    message = intake_message() if message is None else message
    return hashlib.sha256(message.encode("utf-8")).hexdigest()[:16] if message is not None else None


def intake_logged(rounds_dir):
    """None if RUN_LOG.md's "## Intake" section names the current intake message's hash, else why not.
    It shows the operator printed the message rather than composing one; that the message was sent
    unchanged no script can see (KNOWN_LIMITATIONS)."""
    h = intake_hash()
    if h is None:
        return f"the intake message block is missing from audits/{STAGE_FILES[0]}"
    try:
        log = open(os.path.join(rounds_dir, "RUN_LOG.md"), encoding="utf-8").read()
    except OSError:
        return "no RUN_LOG.md"
    m = re.search(r"^## Intake[^\n]*\n(.*?)(?=^## |\Z)", log, re.S | re.M)
    if not m or f"intake-message sha256 {h}" not in m.group(1):
        return (f"RUN_LOG.md's \"## Intake\" lacks the line `intake-message sha256 {h}`: the intake is "
                f"the message `python3 audits/prompt.py --intake` prints, sent unchanged; log that line "
                f"(`prompt.py --intake --hash`) with the answers")
    return None


# B13 (U2 §8, restarts): the intake answer is saved before the branch and the run's log exist, so a
# conversation that ends between the intake and Stage 1 step 5 resumes without asking the intake again
INTAKE_DRAFT = "INTAKE.md"          # under .formalization-work/ (git-excluded, persistent, inside the project)


def intake_draft_path():
    return os.path.join(_fw_root(), INTAKE_DRAFT)


def intake_save(text):
    """Save the intake answer (stage0-intake.md) to .formalization-work/INTAKE.md: the `intake-message sha256`
    line of the current message and the answers, as they go under RUN_LOG.md's `## Intake`. A later save may
    only add to it (Checkpoint A's OK, a label asked again); it never replaces what was saved. Returns what it
    did; ValueError when refused."""
    body = "\n".join(l.rstrip() for l in str(text).strip("\n").splitlines()) + "\n"
    h = intake_hash()
    if h is None or f"intake-message sha256 {h}" not in body:
        raise ValueError(f"the saved intake must carry the line `intake-message sha256 {h}` (prompt.py --intake --hash) "
                         f"and the answers")
    if re.search(r"^\s*#", body, re.M):
        raise ValueError("no heading lines: the text goes under RUN_LOG.md's ## Intake as it is")
    p = intake_draft_path()
    old = open(p, encoding="utf-8").read() if os.path.exists(p) else None
    if old is not None and not body.startswith(old):
        raise ValueError(f"an intake is already saved ({os.path.relpath(p, REPO)}): this is a resumed run. Never ask "
                         f"the intake again; a later save may only add lines after what is there")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    _exclude(FW + "/")
    if old != body:
        open(p, "w", encoding="utf-8").write(body)
    return f"saved the intake in {os.path.relpath(p, REPO)}" + (" (unchanged)" if old == body else "")


def intake_resume_hint():
    """What `project.py --stage` says when no run log exists but an intake was saved (a restart before Stage 1
    step 5), or None."""
    try:
        p = intake_draft_path()
    except ValueError:
        return None
    if not os.path.exists(p):
        return None
    a_ok = re.search(r"Checkpoint A\b[^\n]*\bOK\b", open(p, encoding="utf-8").read(), re.I)
    return (f"current stage: resumed before the run log exists -- the intake is saved in {os.path.relpath(p, REPO)}. "
            f"Do NOT send the intake again. " + ("Checkpoint A was OKed: go on with Stage 1; " if a_ok else
            "Show Checkpoint A again (stage0-intake.md, \"Checkpoint A\") and wait for the OK; then Stage 1; ")
            + "in Stage 1 step 1, if the run's branch already exists, `git switch <branch>` (never a second "
            f"`git switch -c`). read now: audits/{STAGE_FILES[0] if not a_ok else STAGE_FILES[1]}")


# Integrated review fix 4: a stop before the config exists (Stage 1 steps 0-2: the environment check, the branch,
# the Mathlib cache). stops.py records into the run's rounds directory, which the config names, so it could not
# record these: they are kept beside the saved intake (git-excluded, inside the project) as P<n>, opened and closed
# with the same stops.py commands, and `--intake-move` (Stage 1 step 5) moves them under RUN_LOG.md's `## Stops`
# (refusing while one is open). Only a human stop may be opened there: nothing else can fail before the config.
PRE_CONFIG_STOPS = "PRE_CONFIG_STOPS.json"
PRE_CONFIG_CAUSES = ("env-unknown", "outward-action", "codex-approval")


def pre_config_path():
    return os.path.join(_fw_root(), PRE_CONFIG_STOPS)


def pre_config_window():
    """True between Stage 0's --intake-save and Stage 1 step 5's --intake-move: the intake is saved, so the run has
    begun, and the run log (and with it the config's rounds directory) does not hold it yet."""
    try:
        return os.path.exists(intake_draft_path())
    except ValueError:
        return False


def pre_config_stops():
    try:
        d = json.load(open(pre_config_path(), encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def pre_config_open(note, cause):
    """Record a pre-config stop; returns its id P<n>. ValueError when refused."""
    import datetime
    if not pre_config_window():
        raise ValueError("no saved intake: a pre-config stop belongs between Stage 0's --intake-save and Stage 1 "
                         "step 5; with a config, stops.py records in the run")
    if cause not in PRE_CONFIG_CAUSES:
        raise ValueError(f"before the config exists only a human stop is recorded (--cause {'|'.join(PRE_CONFIG_CAUSES)}); "
                         f"{cause!r} is not one")
    if not " ".join(str(note or "").split()):
        raise ValueError("--note \"<what failed>\" is required")
    rows = pre_config_stops()
    if any(not r.get("closed") for r in rows):
        raise ValueError(f"pre-config stop {next(r['stop'] for r in rows if not r.get('closed'))} is still open: one "
                         f"stop at a time (close it first)")
    sid = f"P{len(rows) + 1}"
    rows.append({"stop": sid, "date": datetime.date.today().isoformat(), "cause": cause,
                 "note": " ".join(str(note).split())})
    os.makedirs(os.path.dirname(pre_config_path()), exist_ok=True)
    _exclude(FW + "/")
    json.dump(rows, open(pre_config_path(), "w", encoding="utf-8"), indent=1)
    return sid


def pre_config_close(sid, human):
    import datetime
    rows = pre_config_stops()
    hit = [r for r in rows if r.get("stop") == sid]
    if not hit:
        raise ValueError(f"no pre-config stop {sid!r}")
    if hit[0].get("closed"):
        raise ValueError(f"{sid} is already closed")
    if not " ".join(str(human or "").split()):
        raise ValueError("--human \"<their answer, verbatim>\" is required: a pre-config stop is the human's")
    hit[0]["closed"] = {"by": "human", "date": datetime.date.today().isoformat(), "answer": " ".join(str(human).split())}
    json.dump(rows, open(pre_config_path(), "w", encoding="utf-8"), indent=1)
    return hit[0]


def pre_config_lines(rows=None):
    return [f"- {r['stop']} ({r['date']}, before the config existed: {r['cause']}, a human stop) {r['note']}"
            + (f" -- closed {r['closed']['date']} by the human: \"{r['closed']['answer']}\"" if r.get("closed") else
               " -- OPEN") for r in (pre_config_stops() if rows is None else rows)]


def intake_move(cfg):
    """Stage 1 step 5: put the saved intake under RUN_LOG.md's `## Intake (<date>)` and remove the draft (a later
    new run must not take it for a resume). Refuses when the log already has an `## Intake` section that lacks it."""
    import datetime
    p = intake_draft_path()
    if not os.path.exists(p):
        raise ValueError(f"no saved intake ({os.path.relpath(p, REPO)}): Stage 0 saves it with --intake-save")
    text = open(p, encoding="utf-8").read()
    pre = pre_config_stops()
    if any(not r.get("closed") for r in pre):
        raise ValueError("a pre-config stop is open (" + "; ".join(l for l in pre_config_lines(pre) if l.endswith("OPEN"))
                         + "): close it with the human's answer (stops.py close --stop P<n> --human \"...\") first")
    path = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if not re.search(r"^## Intake\b", log, re.M):
        log_append(cfg, f"Intake ({datetime.date.today().isoformat()})", text)
    elif text.strip() not in log:
        raise ValueError("RUN_LOG.md already has an ## Intake section without the saved intake: merge by hand is not "
                         "allowed; compare the two and keep the saved one")
    if pre:
        have = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        add = [l for l in pre_config_lines(pre) if l not in have]
        if add:
            log_append(cfg, "Stops", "\n".join(add))
        os.remove(pre_config_path())
    os.remove(p)
    return (f"the saved intake is under ## Intake of {os.path.relpath(path, REPO)}; {os.path.relpath(p, REPO)} removed"
            + (f"; {len(pre)} pre-config stop(s) moved under ## Stops" if pre else ""))


def committed_blob(top, commit, rel):
    """The text of `rel` (a literal path, never resolved through a symlink) at `commit` of the repository
    `top`, or None unless that git object is a regular file (mode 100644, a blob): a symlink, a
    submodule, an executable or a missing path is refused (B2 review: a RUN_LOG.md symlinked to another
    file must not be read as the intake)."""
    ls = subprocess.run(["git", "-C", top, "ls-tree", commit, "--", rel], capture_output=True, text=True)
    row = ls.stdout.split("\t", 1)[0].split() if ls.returncode == 0 else []
    if row[:2] != ["100644", "blob"] or ls.stdout.count("\n") != 1:
        return None
    r = subprocess.run(["git", "-C", top, "cat-file", "blob", row[2]], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def rounds_rel(rounds_dir, name):
    """(top, rel): the repository holding `rounds_dir` and the literal path of `<rounds_dir>/<name>` in it
    (the directory is resolved, the file name never is), or (None, None) outside a repository."""
    if not os.path.isdir(rounds_dir):
        return None, None
    r0 = subprocess.run(["git", "-C", rounds_dir, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r0.returncode:
        return None, None
    top = os.path.realpath(r0.stdout.strip())
    return top, os.path.relpath(os.path.join(os.path.realpath(rounds_dir), name), top)


def first_pin(rounds_dir):
    """The FIRST committed version of the run's TOOLING_PIN.json (the oldest commit that has the file, by its
    literal path), parsed, or None when there is none or it cannot be read. Forgery review M2/M1: the run's terms
    -- its mode, involvement level and answer, its ownership version -- are the intake's, fixed by this commit; a
    later edit of the pin or the config does not move them (integrity.py --check: FAIL[pin])."""
    top, rel = rounds_rel(rounds_dir, "TOOLING_PIN.json")
    if top is None:
        return None
    hs = subprocess.run(["git", "-C", top, "log", "--reverse", "--full-history", "--format=%H", "--", rel],
                        capture_output=True, text=True).stdout.split()
    for h in hs:
        txt = committed_blob(top, h, rel)
        if txt is None:
            continue
        try:
            d = json.loads(txt)
        except ValueError:
            return None
        return d if isinstance(d, dict) else None
    return None


# Forgery review H1: a row of SKIPPED.md, VACUOUS.md or DEVIATIONS.md is never removed. A row an adjudication
# overturns keeps its number and says so in its LAST cell, "superseded (<round>)", committed by "adjudicate
# <round>" (make_report.row_history_problems); the readers then skip it (superseded_row) and the summary lists it.
SUPERSEDED_RE = re.compile(r"^\W*superseded\s*\((\d{4}-\d\d-\d\d-[0-9A-Za-z-]+)\)", re.I)


def superseded_row(cells):
    """The round named by a row marked `superseded (<round>)` in its last cell, or None."""
    m = SUPERSEDED_RE.match(str(cells[-1])) if cells else None
    return m.group(1) if m else None


def intake_section(rounds_dir):
    """The "## Intake" section of the FIRST committed version of RUN_LOG.md that has one (a later edit of
    the log changes nothing), or None when it cannot be read. The log is read by its literal path; a
    version that is not a regular file (a symlink) is refused (B2 review)."""
    top, rel = rounds_rel(rounds_dir, "RUN_LOG.md")
    if top is None:
        return None
    hs = subprocess.run(["git", "-C", top, "log", "--reverse", "--format=%H", "--", rel], capture_output=True,
                        text=True).stdout.split()
    for h in hs:
        txt = committed_blob(top, h, rel)
        if txt is None:
            return None
        sec = re.search(r"^## Intake[^\n]*\n(.*?)(?=^## |\Z)", txt, re.S | re.M)
        if sec:
            return sec.group(1)
    return None


# The ONE form 5d is logged in (B2 review): `- 5d: agent` or `- 5d: human <name>`, printed by
# `prompt.py --intake --5d <who>` for the operator to paste; the human's own words go on the next line
FIVE_D_FORM = re.compile(r"- 5d: (agent|human \S.*)")


def five_d_line(who):
    """The RUN_LOG.md line for intake 5d: `who` is "agent" or "human <name>" (ValueError otherwise)."""
    who = " ".join(str(who or "").split())
    if not FIVE_D_FORM.fullmatch(f"- 5d: {who}"):
        raise ValueError(f"5d is logged as `agent` or `human <name>`, not {who!r}")
    return f"- 5d: {who}"


def approver_5d(rounds_dir):
    """Who the intake's 5d named to approve the statements: "agent" only when every 5d line of the first
    logged intake is exactly `- 5d: agent` (FIVE_D_FORM); "human" for anything else (`- 5d: human <name>`,
    free text, a mixture); None when no intake can be read (the caller then treats the approver as the
    human)."""
    sec = intake_section(rounds_dir)
    if sec is None:
        return None
    lines = [ln.rstrip() for ln in sec.splitlines() if re.match(r"\s*(?:[-*]\s*)?5d\b", ln)]
    return "agent" if lines and all(ln == "- 5d: agent" for ln in lines) else "human"


def agent_may_reapprove(cfg, replaced):
    """(ok, why): may `signoff.py approve --by agent` close an open re-approval (U2 §5)? Only when the
    level hands the statements to the agent (hands-off) or, under involved, the intake's 5d is logged as
    `- 5d: agent` (never under statements-only), AND the
    approval being replaced was the agent's (`replaced`: the APPROVED_FINGERPRINTS.json document). Any
    other re-approval is the human's QUESTION; an unreadable 5d means the human approves."""
    lvl = involvement(cfg)
    if lvl == "statements-only":
        # the approver's rule: under statements-only the human approves the statements; 5d never lets
        # the agent re-approve
        return False, ("under the level 'statements-only' the human approves the statements: a change to "
                       "one is always the human's question")
    who = None if lvl == "hands-off" else approver_5d(os.path.join(REPO, cfg["rounds_dir"]))
    if lvl != "hands-off" and who != "agent":
        return False, (f"under the level '{lvl}' the statements are the human's to approve (intake 5d: "
                       + ("unreadable, so the human" if who is None else "the human") + ")")
    if (replaced or {}).get("by") != "agent":
        return False, (f"the approval being replaced was made by {(replaced or {}).get('by') or 'nobody recorded'}, "
                       "not by the agent: a change to a human-approved statement is the human's")
    return True, f"under '{lvl}' the agent approved the statements it replaces"


# The day from which every apparatus copy's `signoff.py approve` records `by` (the pre-release copy had it
# by 2026-10-13; every release since 0.1.0 has it). An approval written before then has no `by` field.
BY_FIELD_SINCE = "2026-10-13"
LEGACY_BY_NOTE = "legacy: the approval was recorded before the `by` field existed; a human approved"


# Forgery review M1: the ownership version from which every apparatus copy had `by` (0.1.0 introduced ownership 2,
# after BY_FIELD_SINCE). Legacy status is judged by the run's FIRST committed pin -- its ownership version and its
# date, both written by `integrity.py --pin` at Stage 1 -- never by a date in the approval or a commit date, which
# the operator writes (GIT_COMMITTER_DATE).
BY_OWNERSHIP = 2


def run_predates_by(rounds_dir):
    """Did this run begin before the `by` field existed? Its first committed pin (first_pin) is of ownership 1 and
    dated before BY_FIELD_SINCE. False without a readable pin (fail closed: the approver is then not recorded)."""
    fp = first_pin(rounds_dir) if rounds_dir else None
    if not fp:
        return False
    try:
        ver = int(fp.get("ownership", 1))
    except (TypeError, ValueError):
        return False
    d = fp.get("date")
    return ver < BY_OWNERSHIP and isinstance(d, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)) \
        and d < BY_FIELD_SINCE


def approval_by(doc, committed=None, rounds_dir=None):
    """(by, legacy) of an APPROVED_FINGERPRINTS.json document: (its `by`, False) when it is human or agent;
    ("human", True) when the document has no `by` field and was written before the field existed: the RUN began
    before it (run_predates_by(`rounds_dir`): its first pin's ownership version and date), and the document's own
    `date` and `committed` (the date, YYYY-MM-DD, of the commit that wrote it, when it is committed) are before
    BY_FIELD_SINCE too; the apparatus then only knew human approvals. (None, False) otherwise (a newer approval
    with no `by` is a record problem; so is one in a run whose pin cannot be read, or no `rounds_dir`)."""
    if not isinstance(doc, dict):
        return None, False
    if doc.get("by") in ("human", "agent"):
        return doc["by"], False
    d = doc.get("date")
    if "by" not in doc and isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d < BY_FIELD_SINCE \
            and (committed is None or committed < BY_FIELD_SINCE) and run_predates_by(rounds_dir):
        return "human", True
    return None, False


def approval_file_by(path, doc=None):
    """approval_by for the approval file at `path` (`doc`: its parsed content, read when not given), dated by
    the last commit that wrote it (none when it is not committed), in the run of the rounds dir holding it."""
    if doc is None:
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            return None, False
    r = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(path)), "log", "-1", "--format=%cs", "--",
                        os.path.basename(path)], capture_output=True, text=True)
    return approval_by(doc, (r.stdout.strip() or None) if r.returncode == 0 else None,
                       rounds_dir=os.path.dirname(os.path.abspath(path)))


def stage_file(text):
    """The stage file for a `## Current stage` line ("Stage 4 — audit rounds" -> run/stage4-rounds.md),
    or None when the line names no stage 0-5."""
    m = re.search(r"\bStage\s+([0-5])\b", str(text or ""))
    return STAGE_FILES[int(m.group(1))] if m else None


def current_stage(cfg):
    """The first line of `## Current stage` in the run's RUN_LOG.md; None if there is no log."""
    path = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    if not os.path.exists(path):
        return None
    m = re.search(r"^## Current stage[^\n]*\n+([^\n]*)", open(path, encoding="utf-8").read(), re.M)
    return m.group(1).strip() if m else ""


def stage_hint(stage):
    """What `--stage` prints after the stage: the file to read now."""
    f = stage_file(stage)
    if f:
        return f"read now: audits/{f} (and RUN.md, if it is not in your context)"
    return "the stage names no Stage 0-5: find it in RUN.md's stage map and set it with --stage \"Stage <n> — …\""


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
            if k not in REQUIRED and k not in OPTIONAL:
                out.append(f"  unknown config key {k!r} (a typo? the keys are project.py REQUIRED and OPTIONAL)")
    if "source_pdf" in cfg and not os.path.exists(cfg["source_pdf"]):
        out.append(f"! source_pdf does not exist: {cfg['source_pdf']}")
    # Proof drafts must survive a reboot: a run once lost a dozen files of proofs kept under /tmp
    # when the machine restarted. RUN.md, Stage 1: `work_dir` is a persistent git repository.
    wd = cfg.get("work_dir")
    if wd is None:
        out.append("  no work_dir set: helpers' drafts need a persistent directory (audits/run/stage1-setup.md, step 3)")
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
    if "mode" in cfg and cfg["mode"] not in MODES:
        out.append(f"! mode is {cfg['mode']!r}; it must be one of {', '.join(MODES)}")
    elif "mode" in cfg and installed_mode() in MODES and cfg["mode"] != installed_mode() \
            and not (cfg.get("_test_mode") == cfg["mode"] == _test_mode()):   # set by _test_level, --selftest only
        out.append(f"! mode is {cfg['mode']!r}, but this installation is {installed_mode()!r} "
                   f"(project_template.json): the mode is set at install, never by the run")
    elif "mode" not in cfg:
        out.append("  no mode set: the run keeps every stop (dev); copy `mode` from project_template.json")
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


# The adjudicator's two long checks in the background (batch C, C3; fix round 1: COMPAT-C H1, ATTACK-C M1/M2,
# L2/L4/L5). Phase 0 and the coverage roll-up can each run longer than 10 minutes. The operator starts them with
# `project.py --adjudicator-checks --round <R>` before it spawns the adjudicator; the adjudicator waits with
# `project.py --wait-adjudicator-checks --round <R>`, which also verifies the log. Both are plain
# `python3 audits/project.py ...` commands, covered by the project's permission rule for project.py (a
# `bash -c '{...} > log'` and a `timeout ... until tail` loop are not). Race-free by construction:
#   - the start returns only once the detached worker owns the lock and the new log's header is in place (written
#     to a temporary file and renamed), so an adjudicator spawned after it never reads an older log;
#   - one lock for every round (.formalization-work/adjudicator-checks.lock): two Phase 0 runs of this mechanism
#     never run at once (a second start is refused while the first runs; a dead holder's lock is taken over);
#   - the adjudicator's own run (`--own`) writes its own file, adjudicator-<R>-own.log, never the operator's;
#   - the worker computes the commands itself (`--statements` from the round's TARGET.json `_meta.kind`), records
#     them, both HEADs at the start and again before END, and every exit code; the verifier accepts the log only
#     when it ends in END, both HEAD pairs equal the current HEADs, the commands and Phase 0's `mode:` line match
#     TARGET.json, Phase 0 printed its verdict line (GREEN exit 0, RED exit 1) and the coverage roll-up finished
#     (exit 0, or exit 1 after its summary line: outstanding Fails or scope drift to adjudicate; E2E fix 1).
#     Anything else is stale: the adjudicator runs the checks itself (--own).
ADJ_LOCK = "adjudicator-checks.lock"
# Test hook, honoured only by a --selftest process (like TEST_MODE_ENV): JSON {repo, audits, name, rounds_dir,
# stub, poll}; `stub` replaces both scripts by one fake script. A real verify (no --selftest) expects the real
# commands, so a stubbed log is never accepted as current.
ADJ_TEST_ENV = "FORMALIZE_ADJ_CHECKS_TEST"
# the commands the selftest's background-checks children run with a trailing --selftest (the hook only; _in_selftest
# stays false in them)
ADJ_HOOK_CMDS = ("--adjudicator-checks", "--wait-adjudicator-checks", "--adjudicator-checks-worker")
ADJ_WAIT = 540          # the default bound of one wait call, in seconds (a Bash call allows up to 600)
ADJ_POLL = 15


def _adj_ctx(name=None, argv=None, env=None):
    env = os.environ if env is None else env
    t = env.get(ADJ_TEST_ENV)
    a_ = sys.argv if argv is None else argv
    if t and (_in_selftest(a_) or (a_[1:2] and a_[1] in ADJ_HOOK_CMDS and "--selftest" in a_[2:])):
        d = json.loads(t)
        return {"repo": d["repo"], "audits": d["audits"], "name": d["name"], "rounds_dir": d["rounds_dir"],
                "stub": d.get("stub"), "poll": float(d.get("poll", ADJ_POLL)), "grace": float(d.get("grace", 5)),
                "test": True}
    cfg = select(name)[0]
    return {"repo": REPO, "audits": AUDITS, "name": cfg["name"], "rounds_dir": cfg["rounds_dir"], "stub": None,
            "poll": ADJ_POLL, "test": False}


def _adj_commands(ctx, round_name):
    """(kind, [(label, the command as the log and the prompt show it, argv)]); ValueError for a bad round."""
    import shlex
    if not (ROUND_RE.match(round_name or "") and "/" not in round_name):
        raise ValueError(f"--round {round_name!r} is not a round name (<DATE>-<HASH> or <DATE>-full-<HASH>)")
    tj = os.path.join(ctx["repo"], ctx["rounds_dir"], round_name, "TARGET.json")
    try:
        kind = json.load(open(tj, encoding="utf-8"))["_meta"]["kind"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"no readable _meta.kind in {os.path.relpath(tj, ctx['repo'])} ({type(e).__name__}): is "
                         f"{round_name} this project's round?")
    p0 = ["--readonly"] + (["--statements"] if kind == "statements" else []) + ["--project", ctx["name"]]
    out = []
    for label, script, args in (("phase0", "phase0", p0), ("coverage", "audit_coverage", [ctx["rounds_dir"]])):
        if ctx["stub"]:
            argv = [sys.executable, ctx["stub"], script, *args]
            shown = shlex.join(["python3", ctx["stub"], script, *args])
        else:
            argv = [sys.executable, "-B", os.path.join(ctx["audits"], script + ".py"), *args]
            shown = shlex.join(["python3", f"audits/{script}.py", *args])
        out.append((label, shown, argv))
    return kind, out


def _adj_mode(kind):
    return "read-only" + (", statement round" if kind == "statements" else "")


def _adj_heads(ctx):
    def h(d):
        r = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "(unreadable)"
    return h(ctx["repo"]), h(ctx["audits"])


def _adj_paths(ctx, round_name, own):
    fw = os.path.join(ctx["repo"], FW)
    if os.path.islink(fw):
        raise ValueError(f"{fw} is a symbolic link; it must be a directory inside the project")
    return (os.path.join(fw, f"adjudicator-{round_name}{'-own' if own else ''}.log"),
            os.path.join(fw, ADJ_LOCK))


def _adj_alive(pid):
    try:
        pid = int(pid)
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError, TypeError, OverflowError):
        return False
    except PermissionError:
        return True
    cmd = f"/proc/{pid}/cmdline"
    if os.path.isdir("/proc/self"):
        try:
            return b"adjudicator-checks" in open(cmd, "rb").read()    # a zombie or a reused pid is not ours
        except OSError:
            return False
    return _adj_alive_noproc(pid)


def _adj_alive_noproc(pid):
    """_adj_alive's command-line test without /proc (macOS branch): the arguments from sysctl KERN_PROCARGS2, as
    lanecheck reads them (Codex's macOS sandbox allows it for this user's processes, not ps); elsewhere from ps.
    A process whose arguments cannot be read (a zombie, exited meanwhile) is not ours, as on Linux."""
    if sys.platform == "darwin":
        import lanecheck
        try:
            argv = lanecheck._procargs(pid)[0]
        except (OSError, ValueError, AttributeError):
            return False
        return any(b"adjudicator-checks" in a for a in argv)
    r = subprocess.run(["ps", "-ww", "-o", "args=", "-p", str(pid)], capture_output=True, text=True)
    return r.returncode == 0 and "adjudicator-checks" in r.stdout


def _adj_lock(lock):
    """The lock's record, None (no lock), or {} (unreadable: being written, or garbage)."""
    try:
        return json.load(open(lock, encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


def _adj_held(lock):
    """The live holder's record, or None. An unreadable lock younger than a minute is held (a start is writing
    it); a lock whose process is gone is not."""
    d = _adj_lock(lock)
    if d is None:
        return None
    if not d.get("pid"):
        try:
            young = time.time() - os.path.getmtime(lock) < 60
        except OSError:
            return None
        return {"round": "?", "own": False, "pid": "?"} if young else None
    return d if _adj_alive(d["pid"]) else None


def _adj_write_lock(lock, rec):
    tmp = f"{lock}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, lock)


def _adj_release(lock, token):
    d = _adj_lock(lock)
    if d is not None and d.get("id") == token:
        try:
            os.remove(lock)
        except OSError:
            pass


def _adj_cmd(what, round_name, own):
    return f"python3 audits/project.py --{what} --round {round_name}{' --own' if own else ''}"


def adj_start(ctx, round_name, own=False, foreground=False):
    """Start the checks (detached; with `foreground`, in this process). 0 started (or, foreground, finished), 1
    refused (another run holds the lock), 2 bad call."""
    import secrets
    try:
        kind, cmds = _adj_commands(ctx, round_name)
        log, lock = _adj_paths(ctx, round_name, own)
    except ValueError as e:
        print(f"FAIL[tool-call] {e}")
        return 2
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    if not ctx["test"]:
        _exclude(FW + "/")
    token = secrets.token_hex(8)
    rec = {"id": token, "pid": os.getpid(), "round": round_name, "own": own,
           "log": os.path.relpath(log, ctx["repo"]), "since": time.time()}
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            held = _adj_held(lock)
            if held is not None:
                print(f"FAIL[tool-call] the adjudicator's checks are already running (round {held.get('round')}, "
                      f"{'own' if held.get('own') else 'operator'} run, pid {held.get('pid')}): two Phase 0 runs "
                      f"never run at once. Wait for them: "
                      f"`{_adj_cmd('wait-adjudicator-checks', held.get('round'), held.get('own'))}`, then start again")
                return 1
            try:
                os.remove(lock)       # its process is gone: take it over
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        break
    else:
        print("FAIL[tool-call] could not take the adjudicator-checks lock; run the same command again")
        return 1
    try:
        head, aud = _adj_heads(ctx)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        header = ([f"ADJUDICATOR CHECKS round {round_name} ({'own' if own else 'operator'} run) id {token} "
                   f"started {stamp}", f"HEAD {head}", f"AUDITS {aud}", f"KIND {kind} (TARGET.json _meta.kind)"]
                  + [f"CMD {label}: {shown}" for label, shown, _ in cmds])
        tmp = f"{log}.tmp-{token}"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(header) + "\n")
        os.replace(tmp, log)          # a reader sees the old log or this one, never a mix
        if foreground:
            return _adj_work(ctx, round_name, own, token, log, lock)
        args = [sys.executable, "-B", os.path.abspath(__file__), "--adjudicator-checks-worker", "--round", round_name,
                "--id", token, *(["--own"] if own else []), *(["--selftest"] if ctx["test"] else []),
                *([] if ctx["test"] else ["--project", ctx["name"]])]
        p = subprocess.Popen(args, cwd=ctx["repo"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.time() + 30
        while time.time() < end and (_adj_lock(lock) or {}).get("pid") != p.pid and p.poll() is None:
            time.sleep(0.05)
        if (_adj_lock(lock) or {}).get("pid") != p.pid:
            if p.poll() is None:
                p.kill()
            _adj_release(lock, token)
            print(f"FAIL[tool-call] the background checks did not start (worker exit {p.poll()}); run the same "
                  f"command again")
            return 1
    except BaseException:
        _adj_release(lock, token)
        raise
    print(f"started: Phase 0 ({_adj_mode(kind)}) and the coverage roll-up for round {round_name}, in the "
          f"background, into {os.path.relpath(log, ctx['repo'])}. Change nothing in the project or the audits "
          f"repository until they end. Wait for them with `{_adj_cmd('wait-adjudicator-checks', round_name, own)}`")
    return 0


def _adj_work(ctx, round_name, own, token, log=None, lock=None):
    """The worker: runs the two commands, appending to the log the start already wrote. Ends with both HEADs,
    every exit code and END, also when it crashes (a crash is never a bare END)."""
    if log is None:
        log, lock = _adj_paths(ctx, round_name, own)
        rec = _adj_lock(lock) or {}
        if rec.get("id") != token or rec.get("round") != round_name or bool(rec.get("own")) != own:
            print("FAIL[tool-call] --adjudicator-checks-worker runs only as started by --adjudicator-checks")
            return 2
        _adj_write_lock(lock, dict(rec, pid=os.getpid()))
    rc_all = 0
    try:
        with open(log, "a", encoding="utf-8") as f:
            try:
                kind, cmds = _adj_commands(ctx, round_name)
                for label, shown, argv in cmds:
                    f.write(f"=== {label}: {shown}\n")
                    f.flush()
                    rc = subprocess.run(argv, cwd=ctx["repo"], stdin=subprocess.DEVNULL, stdout=f,
                                        stderr=subprocess.STDOUT).returncode
                    f.write(f"\n{label} exit {rc}\n")
                    f.flush()
                    rc_all = rc_all or rc
            except Exception as e:        # noqa: BLE001 -- recorded in the log, which then never verifies
                f.write(f"\nworker crashed: {' '.join(f'{type(e).__name__}: {e}'.split())[:300]}\nworker exit 1\n")
                rc_all = 1
            head, aud = _adj_heads(ctx)
            f.write(f"HEAD {head} (end)\nAUDITS {aud} (end)\nEND\n")
    finally:
        _adj_release(lock, token)
    return 0 if rc_all == 0 else 1


def adj_verify(ctx, round_name, own, text):
    """(reasons the log is stale -- empty when it is current, phase 0's verdict line or None, what the coverage
    roll-up found or None). Each check is judged by its own documented exits (E2E fix 1): Phase 0 exits 0 after
    `PHASE 0: GREEN` and 1 after `PHASE 0: RED ...` (both current: the adjudicator reads a RED and stops on it);
    audit_coverage.py exits 0, or 1 after its summary line when the record holds an outstanding Fail or a scope
    drift (both current: the findings are what the adjudicator decides), see audit_coverage.finished. A crash
    (run_main's FAIL[uncoded] line, a traceback, no verdict or summary line), a signal, exit 2 or any code a
    check never returns is stale."""
    lines = text.splitlines()
    why = []
    first = lines[0] if lines else ""
    if not first.startswith(f"ADJUDICATOR CHECKS round {round_name} ({'own' if own else 'operator'} run) id "):
        why.append("its first line does not name this round and run")
    if lines[-1:] != ["END"]:
        why.append("it does not end in END")
    try:
        kind, cmds = _adj_commands(ctx, round_name)
    except ValueError as e:
        return [str(e)], None, None
    head, aud = _adj_heads(ctx)
    for key, now in (("HEAD", head), ("AUDITS", aud)):
        start = [l for l in lines[1:4] if l.startswith(key + " ") and not l.endswith(" (end)")]
        end = [l for l in lines if l.startswith(key + " ") and l.endswith(" (end)")]
        if start != [f"{key} {now}"]:
            why.append(f"its {key} line at the start is not the current {key} {now}")
        if end != [f"{key} {now} (end)"]:
            why.append(f"its {key} line at the end is not the current {key} {now}")
    if f"KIND {kind} (TARGET.json _meta.kind)" not in lines[:5]:
        why.append(f"its KIND line is not TARGET.json's {kind!r}")
    p0 = cov = None
    for label, shown, _ in cmds:
        if f"CMD {label}: {shown}" not in lines or lines.count(f"=== {label}: {shown}") != 1:
            why.append(f"it did not run exactly `{shown}`")
            continue
        sec = lines[lines.index(f"=== {label}: {shown}") + 1:]
        ex = [l for l in sec if re.fullmatch(rf"{label} exit -?\d+", l)]
        if not ex:
            why.append(f"no `{label} exit` line: it crashed or was killed")
            continue
        rc = int(ex[0].rsplit(" ", 1)[1])
        sec = sec[:sec.index(ex[0])]
        if label == "phase0":
            modes = [l for l in sec if l.startswith("# Phase 0 for project ")]
            want = f"; mode: {_adj_mode(kind)}"
            if len(modes) != 1 or not modes[0].endswith(want):
                why.append(f"Phase 0's mode line is not `...{want}` (TARGET.json kind {kind!r}): "
                           + (modes[0] if modes else "none"))
            res = [l for l in sec if re.fullmatch(r"PHASE 0: (GREEN|RED\b.*)", l)]
            p0 = res[-1] if res else None
            if p0 is None or (p0 == "PHASE 0: GREEN") != (rc == 0) or (p0 != "PHASE 0: GREEN" and rc != 1):
                why.append(f"Phase 0 printed no verdict matching its exit code {rc} (a crash)")
            elif any(l.startswith("FAIL[uncoded] phase0.py ") for l in sec):     # its own crash, not a child's
                why.append(f"Phase 0 crashed (FAIL[uncoded] phase0.py), exit {rc}")
        else:
            import audit_coverage
            ok_, cov = audit_coverage.finished(rc, sec)
            if not ok_:
                why.append(cov)
                cov = None
    if any(l.startswith("worker crashed:") for l in lines):
        why.append("the worker crashed")
    return why, p0, cov


def adj_wait(ctx, round_name, own=False, timeout=ADJ_WAIT):
    """Wait (at most `timeout` seconds) for the log's END, then verify it. 0 current (read the log), 1 stale (run
    the checks yourself), 3 still running (wait again), 2 bad call."""
    try:
        _adj_commands(ctx, round_name)
        log, lock = _adj_paths(ctx, round_name, own)
    except ValueError as e:
        print(f"FAIL[tool-call] {e}")
        return 2
    rel = os.path.relpath(log, ctx["repo"])
    own_cmds = (f"`{_adj_cmd('adjudicator-checks', round_name, True)}`, then "
                f"`{_adj_cmd('wait-adjudicator-checks', round_name, True)}`")
    deadline = time.monotonic() + timeout
    grace = ctx.get("grace", 5)
    while True:
        try:
            text = open(log, encoding="utf-8").read()
        except FileNotFoundError:
            text = None
        if text is not None and text.splitlines()[-1:] == ["END"]:
            break
        m = re.match(r"ADJUDICATOR CHECKS round \S+ \(\w+ run\) id (\w+) ", text or "")
        held = _adj_held(lock)
        if text is None or held is None or m is None or held.get("id") != m.group(1):
            if grace > 0:         # a start run in the background may not have written its header yet
                time.sleep(min(ctx["poll"], grace))
                grace -= ctx["poll"]
                continue
            gone = ("there is no log" if text is None else
                    "it has no END and no run is writing it (the run was killed, or the log is not this run's)")
            print(f"STALE {rel}: {gone}. Run the checks yourself: "
                  + (own_cmds if not own else f"`{_adj_cmd('adjudicator-checks', round_name, True)}` again, then the same wait"))
            return 1
        left = deadline - time.monotonic()
        if left <= 0:
            last = (text.splitlines() or ["?"])[-1][:120]
            print(f"WAIT: still running (pid {held.get('pid')}; last line: {last}). Run the same command again: "
                  f"`{_adj_cmd('wait-adjudicator-checks', round_name, own)}`")
            return 3
        time.sleep(min(ctx["poll"], left))
    why, p0, cov = adj_verify(ctx, round_name, own, text)
    if why:
        print(f"STALE {rel}: " + "; ".join(why) + ". Do not use it. Run the checks yourself: "
              + (own_cmds if not own else f"`{_adj_cmd('adjudicator-checks', round_name, True)}` again, then the same wait"))
        return 1
    print(f"current: {rel} ended; both HEADs unchanged since its start, the commands and Phase 0's mode as "
          f"TARGET.json says. Its result: {p0}; the coverage roll-up finished: {cov}. Read the log (grep, tail or "
          f"sed -n).")
    return 0


def adj_cli(argv, name):
    """--adjudicator-checks / --wait-adjudicator-checks / --adjudicator-checks-worker, after --project is taken."""
    what, rest = argv[0], argv[1:]
    own = "--own" in rest
    rest = [a for a in rest if a not in ("--own", "--selftest")]
    fg = "--foreground" in rest and what == "--adjudicator-checks"
    rest = [a for a in rest if a != "--foreground"]
    opts = {}
    while rest:
        if rest[0] in ("--round", "--timeout", "--id") and len(rest) > 1:
            opts[rest[0]] = rest[1]
            rest = rest[2:]
        else:
            print(f"FAIL[tool-call] unexpected argument {rest[0]!r}\n{USAGE}")
            return 2
    if "--round" not in opts:
        print(f"FAIL[tool-call] {what} needs --round <R>")
        return 2
    try:
        ctx = _adj_ctx(name)
    except SelectionError as e:
        print(f"FAIL: {e}")
        return 2
    if what == "--adjudicator-checks":
        return adj_start(ctx, opts["--round"], own, fg)
    if what == "--adjudicator-checks-worker":
        return _adj_work(ctx, opts["--round"], own, opts.get("--id"))
    try:
        t = float(opts.get("--timeout", ADJ_WAIT))
    except ValueError:
        t = -1
    if not 0 <= t <= 3600:
        print("FAIL[tool-call] --timeout takes seconds, 0 to 3600")
        return 2
    return adj_wait(ctx, opts["--round"], own, t)


LICENSE_TEXTS = {"apache-2.0": os.path.join("skills", "formalize-paper", "LICENSE-Apache-2.0.txt")}


def write_license(choice, root=None):
    """Stage 1 step 5, intake 6c: write <project>/LICENSE from the licence text shipped with the skill
    (apache-2.0), or from a file holding another licence's text; "none" writes nothing. Never overwrites
    an existing LICENSE (a Mathlib clone has one). Does not commit: the scaffold commit takes it.
    A script command because Claude Code's auto mode denied the `cp` it replaces. Returns (rc, line)."""
    root = root or REPO
    key = (choice or "").strip().lower()
    key = "apache-2.0" if key == "apache" else key
    dest = os.path.join(root, "LICENSE")
    if key == "none":
        return 0, "license: none asked; no LICENSE written"
    if key in LICENSE_TEXTS:
        src = os.path.join(AUDITS, LICENSE_TEXTS[key])
    elif choice and os.path.isfile(os.path.expanduser(choice)):
        src = os.path.expanduser(choice)
    else:
        return 1, (f"FAIL[tool-call] --license {choice!r}: not a known licence name or a file; give apache-2.0, "
                   f"none, or the path of a file holding the licence's standard text")
    try:
        text = open(src, "rb").read()
        if not text.strip():
            return 1, f"FAIL[tool-call] --license: {src} is empty"
        if os.path.lexists(dest):
            same = os.path.isfile(dest) and not os.path.islink(dest) and open(dest, "rb").read() == text
            return 0, ("license: LICENSE already present and identical; kept" if same else
                       "license: an existing LICENSE was kept (not replaced); record it in RUN_LOG.md and the "
                       "completion message")
        with open(dest, "xb") as f:
            f.write(text)
    except OSError as e:
        return 1, f"FAIL[tool-call] --license: could not write {dest}: {e.strerror or e}"
    return 0, f"license: wrote LICENSE ({key if key in LICENSE_TEXTS else 'text of ' + choice}); commit it with the scaffold"


def _license_controls():
    """--license (Stage 1, 6c): [(check, passed)]."""
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="license-")
    out = []
    try:
        lic = os.path.join(d, "LICENSE")
        bundled = open(os.path.join(AUDITS, LICENSE_TEXTS["apache-2.0"]), "rb").read()
        rc, line = write_license("none", d)
        out.append(("--license none writes nothing", rc == 0 and not os.path.lexists(lic) and "no LICENSE" in line))
        rc, line = write_license("Apache-2.0", d)
        out.append(("--license apache-2.0 writes the bundled text to LICENSE",
                    rc == 0 and open(lic, "rb").read() == bundled and "wrote LICENSE" in line))
        rc, line = write_license("apache-2.0", d)
        out.append(("--license apache-2.0 again: idempotent (kept, unchanged)",
                    rc == 0 and open(lic, "rb").read() == bundled and "identical; kept" in line))
        open(lic, "w").write("Mathlib's own licence\n")
        rc, line = write_license("apache-2.0", d)
        out.append(("an existing different LICENSE is kept, never overwritten",
                    rc == 0 and open(lic).read() == "Mathlib's own licence\n" and "kept (not replaced)" in line))
        os.remove(lic)
        rc, line = write_license("mit", d)
        out.append(("an unknown licence name is refused with a coded line naming the accepted values",
                    rc == 1 and line.startswith("FAIL[tool-call]") and "apache-2.0" in line
                    and not os.path.lexists(lic)))
        txt = os.path.join(d, "mit.txt")
        open(txt, "w").write("MIT License\n")
        rc, line = write_license(txt, d)
        out.append(("--license FILE writes that file's text", rc == 0 and open(lic).read() == "MIT License\n"))
        os.remove(lic)
        os.symlink(os.path.join(d, "elsewhere"), lic)
        rc, line = write_license("apache-2.0", d)
        out.append(("a LICENSE symlink is kept, never written through",
                    rc == 0 and not os.path.exists(os.path.join(d, "elsewhere"))))
        empty = os.path.join(d, "empty.txt")
        open(empty, "w").write(" \n")
        os.remove(lic)
        rc, line = write_license(empty, d)
        out.append(("an empty licence text is refused (FAIL[tool-call], nothing written)",
                    rc == 1 and line.startswith("FAIL[tool-call]") and "empty" in line and not os.path.lexists(lic)))
        rc, line = write_license("apache-2.0", os.path.join(d, "no-such-dir"))
        out.append(("a write error is a coded FAIL[tool-call] line, exit 1, not a traceback",
                    rc == 1 and line.startswith("FAIL[tool-call]") and "could not write" in line))
        import contextlib
        rcs = []
        for argv in (["--license"], ["--license", "apache-2.0", "extra"]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rcs.append((main(argv), buf.getvalue()))
        out.append(("--license with no argument or two arguments: FAIL[tool-call], exit 2",
                    all(rc == 2 and o.startswith("FAIL[tool-call] --license takes one argument") for rc, o in rcs)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


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


def commit_only(paths, subject, repo=None):
    """Commit exactly `paths` in the audit record, by name (never `git add -A`), under `subject`,
    one record commit at a time (lane_auth's repository lock), skipping paths git ignores. Every
    script that writes a record commits it this way, so no commit ever sweeps another step's files
    (RULINGS A5). Returns the commit hash; raises ValueError (nothing staged) on failure."""
    import lane_auth
    from pathlib import Path
    if not paths:
        raise ValueError("nothing to commit")
    # the repository that holds the records (never assumed: a selftest's records are in a scratch repo)
    top = lane_auth.audit_repo(Path(repo) if repo else Path(paths[0]).resolve().parent)
    with lane_auth.repo_lock(top):
        keep = [p for p in paths if os.path.exists(p)]
        gone = [Path(p).resolve() for p in paths if not os.path.exists(p)]   # a deletion, by name
        files = lane_auth.not_ignored(top, keep) + gone
        if not files:
            raise ValueError("nothing to commit")
        return lane_auth.commit_paths(top, files, subject)


def apparatus_pycs(audits=None):
    """Bytecode files where they could shadow a tool: the apparatus top level and its tests/ (a lane's
    probe script leaves a __pycache__ in its probe directory, which is evidence, not apparatus)."""
    audits = audits or AUDITS
    return sorted(p for p in glob.glob(os.path.join(audits, "**", "*.pyc"), recursive=True)
                  if not os.path.relpath(p, audits).startswith(("projects" + os.sep,))
                  and (os.path.dirname(os.path.relpath(p, audits)).split(os.sep)[0] in ("", "__pycache__", "tests",
                                                                                         "agents", "skills")))


def dangerous_pyc(path):
    """Why a .pyc could run code no source shows (RULINGS A10a), or None. Python imports a .pyc
    OUTSIDE __pycache__ when its .py is missing (sourceless), and never compares an UNCHECKED-HASH
    pyc (PEP 552: flags bit 0 set, bit 1 clear) with its source. A cached __pycache__/*.pyc is
    otherwise regenerated from its source, or ignored when stale."""
    if os.path.basename(os.path.dirname(path)) != "__pycache__":
        return "a .pyc outside __pycache__ (Python imports it when its .py is missing)"
    try:
        flags = int.from_bytes(open(path, "rb").read(8)[4:8], "little")
    except OSError:
        return "an unreadable .pyc"
    if flags & 1 and not flags & 2:
        return "an unchecked-hash .pyc (Python never compares it with its source)"
    return None


def env_check():
    """RUN.md Stage 1 step 0: every command must run with PYTHONDONTWRITEBYTECODE=1. Cached bytecode
    in the apparatus is removed (a NOTE); a sourceless or unchecked-hash .pyc is left for
    integrity.py, which fails on it (RULINGS A10a)."""
    ok = os.environ.get("PYTHONDONTWRITEBYTECODE") == "1"
    print("environment: PYTHONDONTWRITEBYTECODE=1 ok" if ok else
          "FAIL: PYTHONDONTWRITEBYTECODE is not 1 in this session's commands (audits/run/stage1-setup.md, step 0)")
    removed = []
    for p in apparatus_pycs():
        if not dangerous_pyc(p):
            os.remove(p)
            removed.append(os.path.relpath(p, AUDITS))
            try:
                os.rmdir(os.path.dirname(p))
            except OSError:
                pass
    if removed:
        print(f"NOTE[pyc-cache] removed {len(removed)} cached bytecode file(s) from audits/ ({removed[0]} …)")
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


def remove_pdf(pdf):
    """Delete a partial PDF a failed compile left (latex(): the paper's own compile at Stage 1)."""
    if os.path.exists(pdf):
        os.remove(pdf)


def keep_notices(cfg, notices, approved_round):
    """(kept, dropped) KNOWN_FAULTS-<key>.md notices: kept are those of the delivered documents (key
    report-/decisions-<newest round>, signoff-/questions-<approved round>, other-*, run); a notice of
    any other round's report, decisions or sheet is superseded."""
    rs = rounds(cfg)
    newest = os.path.basename(rs[-1]) if rs else None
    cur = {f"report-{newest}", f"decisions-{newest}", f"signoff-{approved_round}", f"questions-{approved_round}"}
    kept, dropped = [], []
    for f in notices:
        key = os.path.basename(f)[len("KNOWN_FAULTS-"):-3]
        (kept if key in cur or not re.match(r"(report|decisions|signoff|questions)-", key) else dropped).append(f)
    return kept, dropped


# --- delivery (B10; U2 §6, ADDENDUM N1, N2, N6) -------------------------------------------------------
# Two steps. `project.py --prepare-delivery` is the only generator of the delivered documents: SUMMARY and
# REPORT (make_report.py), the DECISIONS box (decisions.refresh_box: the operator's text is kept), the
# approved sheet (re-rendered when it still says "will be approved"), README sections A-C; it records each
# document's generator-content hash in DELIVERY.json and commits all of it as "prepare delivery". It writes
# even while a stop is open (H2): the summary lists it as OPEN AT PREPARATION. The readers run after it.
# `project.py --deliver` then only checks (make_report.py --check --delivery; no stop or question open;
# deliver_blocking in both modes; the render guard, render_record.check: each PDF the one recorded for its md;
# release disclosure coverage) and writes only the delivery copy: the files, README.md = README A-C + the stamp +
# section D (known faults, delivery-phase records, reader outcomes, how each PDF was made and checked; ADDENDUM
# N6: D exists only in the delivery copy). The PDFs are rendered between the two (render_record.py, PDF-AGENTS).
DELIVERY_RECORD = "DELIVERY.json"
README_AC = "README-delivery.md"
RUN_RECORD = "RUN_RECORD.md"        # the process record (run_record.py; approver 2026-10-24): markdown only
# U2 §6.6 (M2) / ADDENDUM N2: what the generator reads, and what it never reads. Paths relative to the rounds
# directory (fnmatch; "*" crosses "/"). The generator also reads the Lean at the delivered commit, Phase 0's
# outputs, git history and the config (G1, G3, G4, G7, G8). It never reads a reader's record or notice of a
# delivered document, nor anything --deliver writes; a delivery-phase D record or stop (stops.delivery_phase)
# and RUN_LOG lines of those are read but dropped (behavioural selftest: delivery_inputs_controls).
GEN_INPUTS = ("*/ADOPTED.md", "*/TARGET.json", "*/FINGERPRINTS.json", "*/SIGNOFF.json", "*/INFORMAL.json",
              "*/correspondence*.json", "*/paper-faithfulness*.json", "*/non-vacuity*.json", "*/substantiveness*.json",
              "*/prior-art*.json", "*/ABANDONED.json", "PAPER_DEFECTS.md", "SKIPPED.md", "VACUOUS.md", "DEVIATIONS.md",
              "UNUSED_ARGS.md", "DEPENDENCIES.json", "APPROVED_FINGERPRINTS*.json", "REAPPROVAL*.json", "RUN_LOG.md",
              "AUTHOR_NOTES.md", "READER_NOTES.md", "DECISIONS.md", "TOOLING_PIN.json", "CITATIONS.md",
              "readers/signoff-*", "readers/questions-*", "KNOWN_FAULTS-signoff-*", "KNOWN_FAULTS-questions-*",
              "stops/S*/STOP.json", "stops/S*/CLOSED.json", "stops/S*/CURE*.json", "stops/disclosed/D*.json",
              "stops/repairs/R*.json", "escalations/*", "waivers/*", "tool-patches/*")
READER_OUTPUTS = ("readers/summary-*", "readers/report-*", "readers/decisions-*", "readers/other-*",
                  "KNOWN_FAULTS-summary-*", "KNOWN_FAULTS-report-*", "KNOWN_FAULTS-decisions-*",
                  "KNOWN_FAULTS-other-*", "KNOWN_FAULTS-run.md", "status-check/*")
DELIVER_OUTPUTS = ("../deliverables/*", "../../deliverables/*")


def delivered_commit(cfg, short=True, repo=None):
    """The Lean commit the generated documents cite (ADDENDUM N2): the last commit of the Lean repository that
    changed a project Lean or build file, never HEAD (a commit of anything else must not change a generated
    document). HEAD when git cannot tell."""
    repo = repo or REPO
    paths = list(cfg.get("lean_files") or []) + BUILD_FILES
    r = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%H", "--", *paths], capture_output=True, text=True)
    h = r.stdout.strip() if r.returncode == 0 else ""
    if not h:
        h = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return (h[:11] if short else h) or "unknown"


def _sample(pat):
    """A path a pattern matches ("*" filled in), for the disjointness check."""
    return pat.replace("*", "x-2026-10-22-abc1234-1.md")


def gen_inputs_problems(gen=None, readers_=None, deliver_=None):
    """[pattern pairs that overlap]: GEN_INPUTS must be disjoint from READER_OUTPUTS and DELIVER_OUTPUTS (the
    path check; the behavioural one is delivery_inputs_controls)."""
    gen, readers_, deliver_ = gen or GEN_INPUTS, readers_ or READER_OUTPUTS, deliver_ or DELIVER_OUTPUTS
    out = []
    for g in gen:
        for o in tuple(readers_) + tuple(deliver_):
            if fnmatch.fnmatch(_sample(o), g) or fnmatch.fnmatch(_sample(g), o):
                out.append((g, o))
    return out


def manifest(cfg):
    """The DELIVERY.json of the last prepare, or None."""
    try:
        return json.load(open(os.path.join(REPO, cfg["rounds_dir"], DELIVERY_RECORD), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def doc_text_hash(name, text):
    """The generator-content hash of a delivered document's text: REPORT without its date line, the sheet
    without its approval stamp, the others as they are (never a PDF, never a hand-repaired .tex)."""
    if name == "REPORT.md":
        import readers
        for rx in readers.REPORT_STAMP_RES[:1]:
            text = rx.sub("", text, count=1)
    elif name.endswith("SIGNOFF.md"):
        import signoff
        text = signoff.unstamp(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(name, path):
    try:
        return doc_text_hash(name, open(path, encoding="utf-8").read())
    except OSError:
        return None


def approved_round(cfg):
    try:
        return json.load(open(os.path.join(REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json"))).get("round")
    except (OSError, ValueError, AttributeError):
        return None


def sheet_commit(rd, rnd):
    """The commit the round's SIGNOFF.md was written for (its "Commit `<hash>`." line), or None."""
    try:
        t = open(os.path.join(rd, str(rnd), "SIGNOFF.md"), encoding="utf-8").read() if rnd else ""
    except OSError:
        return None
    m = re.search(r"^Commit `([0-9a-f]{7,40})`", t, re.M)
    return m.group(1) if m else None


def readme_ac(cfg):
    """README sections A-C of the delivery copy (generated; hashed at prepare). Cites the delivered Lean commit
    (ADDENDUM N2), never HEAD; says nothing a reader or --deliver writes (that is section D)."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    appr = {}
    try:
        appr = json.load(open(os.path.join(rd, "APPROVED_FINGERPRINTS.json")))
    except (OSError, ValueError):
        pass
    by = approval_file_by(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), appr)[0] if appr else None
    lines = ["# What is delivered", "",
             f"Final state: Lean commit `{delivered_commit(cfg)}` of `{REPO}` (the last commit that changed "
             f"the Lean; the audit record is `{rd}`).", "",
             "Read the summary first (`SUMMARY.pdf`, and `SUMMARY.md`, its markdown: the audited text): one page with "
             "every result's status, every assumption, defect and reading choice, every decision taken for you, and "
             "every stop. The section just below, \"What the checking code found\", is written by the checking program "
             "when the files are delivered, not by the agent that wrote the summary: each result's status as computed "
             "from the review records, the answers recorded as yours, and what the checks noticed. The rest are its "
             "appendices. Each PDF is a rendering of the markdown delivered beside it, "
             "made and checked by independent agents; section D says how each check ended (and names a document "
             "delivered as markdown only).", "",
             "## A. The report (REPORT.pdf, REPORT.md)", "",
             "The full report at the commit above: how far to trust each layer, coverage, what is not formalized, the "
             "paper's defects, proof routes, vacuous statements, decisions, stops.", "",
             "## B. DECISIONS.md", "",
             "Every decision of the run, taken or open, with what reversing it costs.", "",
             "## C. The sign-off sheet (SIGNOFF.pdf, SIGNOFF.md)", ""]
    if appr:
        # trial #11 audit: this said "the proofs as they stood then and line numbers of that commit" (the approval
        # commit); the sheet shows no proofs, and its lines are those of the commit it was written for (its own
        # "Commit `…`." line), which may precede the approval commit. Said from what the sheet holds.
        ac = str(appr.get("commit", "?"))[:11]
        sc = sheet_commit(rd, appr.get("round"))
        at = (f"at commit `{sc}`, the commit the sheet was written for (the statements were approved at commit "
              f"`{ac}`)" if sc and sc[:11] != ac else f"at commit `{ac}`, the approval commit")
        lines.append(f"The sign-off sheet of the latest approval: round `{appr.get('round', '?')}`. It shows each "
                     f"result's paper statement and its Lean statement, not the proofs, {at}; its `File.lean:N` line "
                     f"numbers are of that commit, and a statement changed by a re-approval is marked CHANGED. The "
                     f"proofs and the line numbers at the final commit are in the report.")
        if involvement(cfg) == "hands-off" or by == "agent":
            lines.append("")
            lines.append("Not reviewed by a human: the agent approved it under the involvement level chosen at intake. "
                         "No fresh reader read the delivered sheet either (hands-off: `signoff.py check` only).")
    else:
        lines.append("No sheet: nothing was approved (no APPROVED_FINGERPRINTS.json).")
    # approver (2026-10-24): how the run went is its own file, markdown only; nothing in it is needed to judge
    # faithfulness, and the known-fault notices are folded into it (no KNOWN_FAULTS-* file is delivered)
    lines += ["", "## The run record (RUN_RECORD.md)", "",
              "How the run went, for maintainers and anyone auditing the process: tool patches, every stop and who "
              "closed it, self-cures, set-asides, re-pins, mechanical failures, faults disclosed instead of a stop, and "
              "the fresh readers' known-fault notices (presentation faults, findings answered as unfixable). Markdown "
              "only. Nothing in it is needed to judge whether the paper was formalized faithfully."]
    return "\n".join(lines) + "\n"


FACTS_DIR = "facts"           # approver (2026-10-28): the generator's draft of SUMMARY, REPORT and RUN_RECORD
AGENT_DOCS = ("SUMMARY.md", "REPORT.md", RUN_RECORD)   # written by the main agent in the rounds directory


def write_draft(rounds_dir, name, text):
    """Write the generator's draft of `name` (SUMMARY.md, REPORT.md, RUN_RECORD.md) to <rounds>/facts/ (review
    2026-10-28). The rounds-directory copy is the main agent's: it is seeded from the draft when missing, and refreshed
    only while it is still byte-identical to the previous draft (untouched by the agent); otherwise never written."""
    fd = os.path.join(rounds_dir, FACTS_DIR)
    os.makedirs(fd, exist_ok=True)
    fp_, p_ = os.path.join(fd, name), os.path.join(rounds_dir, name)
    old = open(fp_, encoding="utf-8").read() if os.path.isfile(fp_) else None
    seeded = not os.path.exists(p_) or (old is not None and open(p_, encoding="utf-8").read() == old)
    open(fp_, "w", encoding="utf-8").write(text)
    if seeded and not os.path.islink(p_):
        open(p_, "w", encoding="utf-8").write(text)
    return seeded


def _prepared_docs(cfg):
    """{name: path} of the documents prepare records (README A-C, the facts drafts of SUMMARY, REPORT and RUN_RECORD,
    DECISIONS, the sheet)."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    docs = {README_AC: os.path.join(rd, README_AC), "DECISIONS.md": os.path.join(rd, "DECISIONS.md")}
    docs.update({n: os.path.join(rd, FACTS_DIR, n) for n in AGENT_DOCS})
    ar = approved_round(cfg)
    if ar:
        docs[f"{ar}/SIGNOFF.md"] = os.path.join(rd, ar, "SIGNOFF.md")
    return docs


def _regenerate_report(cfg):
    """make_report.py on the project (its full build: REPORT.md and SUMMARY.md; the PDFs are rendered by agents)."""
    argv = [sys.executable, "-B", os.path.join(AUDITS, "make_report.py")] + (
        ["--project", cfg["name"]] if cfg.get("name") else [])
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    return r.returncode, report_tail(r.stdout + r.stderr)


def report_tail(text):
    """[make_report's last line, then its failure lines]. Integrated review item 11: the last line alone ("report
    check FAILED: 1 problem(s)") hid WHICH fault."""
    lines = str(text).strip().splitlines()
    fails = [l.strip() for l in lines if re.match(r"\s*(?:FAIL|RED)\b|\s*!", l)]
    return (lines[-1:] or [""]) + fails[:8]


def report_fault_lines(tail):
    """prepare's lines for make_report's failure lines `tail` (after its last line): each fault."""
    return [f"prepare:   {' '.join(str(l).split())[:300]}" for l in tail]


REGENERATE_REPORT = _regenerate_report      # the selftest's stand-in


def _rerender_sheet(cfg, round_name):
    """signoff.py render --round R on the project (SIGNOFF.md and its checks; its PDF is rendered by agents)."""
    argv = [sys.executable, "-B", os.path.join(AUDITS, "signoff.py"), "render", "--round", round_name] + (
        ["--project", cfg["name"]] if cfg.get("name") else [])
    r = subprocess.run(argv, cwd=REPO, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]


RERENDER_SHEET = _rerender_sheet            # the selftest's stand-in


def _run_record_text(cfg):
    import run_record
    return run_record.text(cfg)


RUN_RECORD_TEXT = _run_record_text          # the selftest's stand-in


REAPPROVAL_OPEN_WORDS = re.compile(r"re-?approval (?:is |still )?(?:open|not closed|pending)|not closed\)", re.I)


def reapproval_text_notes(rd, ar):
    """prepare's NOTE lines (E2E-FIX2 M4b; a flag, agents judge): each row of the approved sheet `ar` whose text calls
    a re-approval open while REAPPROVAL.json says it is closed. The sheet marks its row texts as of the round; the
    note lets the formalizing agent say so where the documents quote such a row."""
    try:
        ra = json.load(open(os.path.join(rd, "REAPPROVAL.json"), encoding="utf-8"))
        so = json.load(open(os.path.join(rd, str(ar), "SIGNOFF.json"), encoding="utf-8")) if ar else {}
    except (OSError, ValueError):
        return []
    if not (isinstance(ra, dict) and ra.get("closed")) or not isinstance(so, dict):
        return []
    return [f"prepare: NOTE: the approved sheet's row {r.get('result')!r} says its re-approval is open, but "
            f"REAPPROVAL.json is closed ({ra.get('closed_by', '?')}): its text is as of round {ar} (the sheet says so); "
            f"say the current state wherever a document quotes it"
            for r in so.get("rows") or [] if isinstance(r, dict)
            and REAPPROVAL_OPEN_WORDS.search(" ".join(str(v) for v in r.values()))]


def prepare_delivery(cfg, commit=True):
    """project.py --prepare-delivery (approver, 2026-10-28): the FACTS draft -- data for the main agent, never the
    deliverable. The generator's SUMMARY, REPORT and RUN_RECORD (statuses, goal results, defects, assumptions,
    decisions, trust lines) go to <rounds dir>/facts/; the main agent's own SUMMARY.md, REPORT.md and RUN_RECORD.md in
    the rounds directory are never overwritten (a missing one is seeded from the draft). Also the DECISIONS box (the
    operator's text kept), the approved sheet re-rendered when it still says "will be approved", README sections A-C,
    the drafts' hashes in DELIVERY.json, all committed as "prepare delivery". Returns (rc, [line]); never a stop: a
    draft that fails to build is named, and the agent writes from the records."""
    import decisions, stops
    rd = os.path.join(REPO, cfg["rounds_dir"])
    fd = os.path.join(rd, FACTS_DIR)
    os.makedirs(fd, exist_ok=True)
    out = []
    before = {n: (open(os.path.join(rd, n), encoding="utf-8").read() if os.path.isfile(os.path.join(rd, n)) else None)
              for n in AGENT_DOCS}
    # the approved sheet must say it was approved (mini5 audit): one rendered before the approval says it
    # "will be" (signoff.APPROVAL_STAMPS) and is rendered again
    ar = approved_round(cfg)
    smd = os.path.join(rd, ar, "SIGNOFF.md") if ar else None
    if smd and os.path.exists(smd):
        import signoff
        if any(before in open(smd, encoding="utf-8").read() for _, before in signoff.APPROVAL_STAMPS):
            rc, tail = RERENDER_SHEET(cfg, ar)
            out.append(f"prepare: the approved sheet of {ar} was rendered before its approval: rendered again "
                       f"(signoff.py render exit {rc}{': ' + tail[0] if rc and tail and tail[0] else ''})")
    out += reapproval_text_notes(rd, ar)
    added = decisions.refresh_box(cfg)
    if added:
        out.append(f"prepare: DECISIONS.md's box gained {len(added)} entr{'y' if len(added) == 1 else 'ies'} (a stop or "
                   f"disclosure recorded since it was written)")
    rc, tail = REGENERATE_REPORT(cfg)       # make_report writes its drafts to facts/ (write_draft)
    out.append(f"prepare: the facts draft of REPORT and SUMMARY written to {FACTS_DIR}/ (make_report.py exit {rc}"
               f"{': ' + tail[0] if rc and tail and tail[0] else ''})")
    if rc:
        out += report_fault_lines(tail[1:])
    open(os.path.join(rd, README_AC), "w", encoding="utf-8").write(readme_ac(cfg))
    try:
        write_draft(rd, RUN_RECORD, RUN_RECORD_TEXT(cfg))
        out.append(f"prepare: the facts draft of {RUN_RECORD} written to {FACTS_DIR}/")
    except Exception as e:      # noqa: BLE001 -- named; the agent writes the run record from the records
        p_ = os.path.join(fd, RUN_RECORD)
        if os.path.exists(p_):
            os.remove(p_)
        out.append(f"prepare: NOTE the facts draft of {RUN_RECORD} could not be generated ({type(e).__name__}: {e})")
    after = {n: (open(os.path.join(rd, n), encoding="utf-8").read() if os.path.isfile(os.path.join(rd, n)) else None)
             for n in AGENT_DOCS}
    seeded = [n for n in AGENT_DOCS if after[n] is not None and after[n] != before[n]]
    kept = [n for n in AGENT_DOCS if before[n] is not None and n not in seeded]
    if seeded:
        out.append(f"prepare: {', '.join(seeded)} (missing, or untouched since the last draft) seeded from the facts "
                   f"draft: rewrite them")
    if kept:
        out.append(f"prepare: your {', '.join(kept)} kept as they were (the facts draft never overwrites them)")
    docs = _prepared_docs(cfg)
    rec = {"lean_commit": delivered_commit(cfg, short=False),
           "involvement": involvement(cfg), "mode": mode(cfg), "approved_round": ar,
           "hashes": {n: file_hash(n, p) for n, p in docs.items()},
           "open_at_preparation": [r["stop"] for r in stops.stop_rows(cfg) if r["by"] == "nobody yet"]}
    missing = [n for n, h in rec["hashes"].items() if h is None]
    json.dump(rec, open(os.path.join(rd, DELIVERY_RECORD), "w", encoding="utf-8"), indent=1, sort_keys=True)
    if rec["open_at_preparation"]:
        out.append(f"prepare: written while stop(s) {', '.join(rec['open_at_preparation'])} are open")
    if missing:
        out.append(f"prepare: NOTE missing {', '.join(missing)} (DECISIONS.md is written by decisions.py --write and "
                   f"you; the sheet by signoff.py render)")
    if commit:
        paths = [os.path.join(rd, DELIVERY_RECORD)] + [p for p in docs.values() if os.path.exists(p)] \
            + [os.path.join(rd, n) for n in seeded]
        try:
            h = commit_only(paths, "prepare delivery", repo=AUDITS)
            out.append(f"prepare: committed \"prepare delivery\"{' ' + h[:11] if h else ''}")
        except (ValueError, OSError) as e:
            out.append(f"prepare: commit failed: {e}")
            return 1, out
    out.append(f"prepare: now write SUMMARY.md and REPORT.md yourself from the records and the Lean ({FACTS_DIR}/ is "
               f"data, not the deliverable), correct RUN_RECORD.md and DECISIONS.md where the draft is wrong, run the "
               f"four delivery reviewers, judge their findings (JUDGEMENT.md), render the PDFs "
               f"(python3 audits/render_record.py next --doc SUMMARY|REPORT" + (f"; --doc SIGNOFF --round {ar}" if ar else "")
               + "), then python3 audits/project.py --deliver (run/stage5-delivery.md)")
    return (1 if rc else 0), out        # 1: the facts draft is incomplete (named above); never a stop


def _reader_outcome(cfg, doc, round_name):
    import readers
    return readers.outcome(cfg, doc, round_name)


READER_OUTCOME = _reader_outcome        # the selftest's stand-in


def _render_check(cfg, doc, round_name):
    import render_record
    return render_record.check(cfg, doc, round_name)


RENDER_CHECK = _render_check            # the selftest's stand-in


def readme_d(cfg, files, kept, dropped, delivered=None):
    """README section D (ADDENDUM N6: only in the delivery copy): the stamp, the pointer to RUN_RECORD.md (the
    known-fault notices, the delivery-phase records and the superseded notices are folded into it: approver
    2026-10-24), who wrote and reviewed SUMMARY and REPORT (approver 2026-10-28), the sheet's reader outcome, how each
    PDF was made, and the fingerprints of the delivered PDFs and of RUN_RECORD.md. `kept` and `dropped` are unused here (run_record.delivery_section reads them)."""
    import fingerprint, stops
    try:
        lean = fingerprint.head(REPO)[:11]
    except Exception:       # noqa: BLE001 -- said, never hidden
        lean = "(unknown)"
    aud = subprocess.run(["git", "-C", AUDITS, "rev-parse", "--short=11", "HEAD"], capture_output=True, text=True).stdout.strip()
    lines = ["", "## D. Delivery notes", "",
             f"Delivered from Lean HEAD `{lean}` and audit record HEAD `{aud or '(unknown)'}`.", "",
             f"How the run went, including any fault disclosed instead of a stop and anything that arose after the "
             f"documents were written: `{RUN_RECORD}`, the run record. No separate KNOWN_FAULTS file is delivered."]
    # attack review MEDIUM-1 (batch A): a stop withdrawn as opened in error whose check still fails at delivery is
    # said in the code-written section's "Proof checks" (readme_checked; DESIGN-E fix 2 moved it there)
    # approver (2026-10-28): SUMMARY and REPORT are the main agent's; review 2026-10-28: said only from what is on record
    rd_ = os.path.join(REPO, cfg["rounds_dir"])
    same = draft_copies(cfg)
    if same:
        lines += ["", f"{' and '.join(same)} {'is' if len(same) == 1 else 'are'} the generator's draft, unchanged: the "
                  f"formalizing agent did not rewrite {'it' if len(same) == 1 else 'them'}."]
    else:
        lines += ["", "`SUMMARY` and `REPORT` were written by the formalizing agent from the run's records and the Lean, "
                  "for a mathematician who knows neither Lean nor this tool."]
    have = [p_ for p_ in REVIEW_PERSPECTIVES if os.path.isfile(os.path.join(rd_, REVIEW_DIR, p_ + ".md"))]
    gone = [p_ for p_ in REVIEW_PERSPECTIVES if p_ not in have]
    judged = os.path.isfile(os.path.join(rd_, JUDGEMENT_MD))
    if have:
        lines.append(f"Reviews by fresh agents are on record in the audit record's `{REVIEW_DIR}/` "
                     f"({', '.join(p_.lower() for p_ in have)}); the formalizing agent saved them, so the record cannot "
                     f"show who wrote them"
                     + (f"; no review is on record for {', '.join(p_.lower() for p_ in gone)}" if gone else "")
                     + (f". The formalizing agent's judgement of each finding is in `{JUDGEMENT_MD}`." if judged else
                        ". No judgement of their findings is on record."))
    else:
        lines.append("No delivery review is on record (no `delivery-review/` file)"
                     + (f"; `{JUDGEMENT_MD}` is delivered as written." if judged else "."))
    if involvement(cfg) != "hands-off":
        for f in files:
            b = os.path.basename(f)
            if b.startswith("SIGNOFF"):
                lines += ["", "Fresh-reader check of the sheet (`readers.py`):",
                          f"- `{b}`: {READER_OUTCOME(cfg, 'signoff', 'approved')}."]
                break
    # the advisory citation notes (run/stage5-delivery.md step 5a), when the review produced them: listed, never read
    if os.path.isfile(os.path.join(REPO, cfg["rounds_dir"], "CITATIONS.md")):
        lines += ["", "`CITATIONS.md`: advisory notes on the paper's citations and bibliography, for the authors to "
                  "check (written by one agent, verified and refined by a second; each item quotes its evidence). No "
                  "check of the run reads it, and it changed nothing in the formalization or the documents above."]
    # PDF-AGENTS: how each PDF was made and checked (render_record.outcome_lines), every remaining objection and
    # every checker finding quoted; the markdown is delivered beside each PDF
    import render_record
    ar = approved_round(cfg)
    lines += ["", "How each PDF was made and checked (a fresh agent rendered the markdown, another verified the PDF "
              "against it, and two independent checkers were to judge whether it says mathematically the same thing, a "
              "difference sending it back to the renderer; at most 6 rounds; `render_record.py`). Each line says what "
              "actually ran: a checker that did not run is never a pass. The markdown beside each PDF is the "
              "authoritative text:"]
    for d_, r_ in [("SUMMARY", None), ("REPORT", None)] + ([("SIGNOFF", ar)] if ar else []):
        lines += render_record.readme_lines(cfg, d_, r_)
    # review MED 3: each delivered PDF's sha256, which --check-delivered compares with the file in deliverables/
    # and with the render record (a PDF swapped after --deliver is caught)
    pdfs = [f for f in files if f.endswith(".pdf")]
    lines += ["", "Delivered PDF fingerprints (sha256 of each PDF in this directory as delivered; `python3 audits/"
              "project.py --check-delivered` compares them with the files and with each render record):"
              if pdfs else "Delivered PDF fingerprints: none (no PDF was delivered)."]
    lines += [f"- `{os.path.basename(f)}`: sha256 `{render_record.sha_file(f)}`" for f in pdfs]
    # DESIGN-E fix 2 (F11): every other delivered file but README.md (whose sha256 is in RUN_LOG.md's `## Delivery`
    # line: a file cannot hold its own hash); `delivered` None (an older caller): RUN_RECORD.md only, as before
    rr_ = os.path.join(REPO, "deliverables", RUN_RECORD)
    others = sorted({os.path.basename(f) for f in (delivered or [rr_]) if not f.endswith(".pdf")
                     and os.path.basename(f) != "README.md"
                     and os.path.isfile(os.path.join(REPO, "deliverables", os.path.basename(f)))
                     and not os.path.islink(os.path.join(REPO, "deliverables", os.path.basename(f)))})
    if others:
        lines += ["", "Delivered file fingerprints (sha256 of every other file in this directory as delivered except "
                  "this README, whose fingerprint is in the run log; `python3 audits/project.py --check-delivered` "
                  "compares them with the files):"]
        lines += [f"- `{b}`: sha256 `{render_record.sha_file(os.path.join(REPO, 'deliverables', b))}`" for b in others]
    return "\n".join(lines) + "\n"


DELIVERED_ANY = re.compile(r"^- `([^`/]+)`: sha256 `([0-9a-f]{64})`$")    # README D: every delivered file but README
# stage5's push appends this line to the delivered README after --deliver (both forms; DESIGN-E2 L4)
# exactly the generated form (attack review E M1/E4: free text after "Pushed to" passed): a remote and a branch with no
# space or comma, the two commits, and for the no-paper form the paper paths quoted in backticks, any characters but
# a backtick or a newline (re-review E L2: `Smith+Jones (2024).pdf` is an honest path); the unquoted form stage5
# printed before is still read, with its narrower characters
PUSHED_RE = re.compile(r"^Pushed to [^\s,]+, branch [^\s,]+, as commit `[0-9a-f]{7,64}`: the tree of Lean HEAD "
                       r"`[0-9a-f]{7,64}`(, without (?:`[^`\n]{1,200}`|[\w./ ,-]{1,200}))?\.\s*$")
README_LOGGED = re.compile(r"README\.md sha256 ([0-9a-f]{64}), (\d+) bytes")


def readme_log_rewrites(top, rel, now):
    """[(sha256, commit)] of every README.md sha256 a committed version of RUN_LOG.md logged, that a later commit
    removed and that the log at HEAD no longer holds (`git log -p -G`, first parent): --deliver only appends
    delivery lines, so an edited or deleted one is a record change (attack review E M1/E6, E7: a rewritten or
    removed fingerprint passed). Unreadable history: [] (the HEAD comparison still runs)."""
    r = subprocess.run(["git", "-C", top, "log", "-m", "--first-parent", "-p", "--format=@@%h %s",
                        "-G", r"README\.md sha256", "--", rel], capture_output=True, text=True)
    if r.returncode:
        return []
    out, cur = [], "?"
    for l in r.stdout.splitlines():
        if l.startswith("@@") and not l.startswith("@@ "):
            cur = l[2:].strip()
        elif l.startswith("-") and not l.startswith("---"):
            m = README_LOGGED.search(l)
            if m and m.group(1) not in now and m.group(1) not in [h for h, _ in out]:
                out.append((m.group(1), f"`{cur}`"))
    return out


def readme_problems(cfg):
    """([problem], [info]) of deliverables/README.md against the last RUN_LOG.md `## Delivery` line (committed at
    HEAD) that logs its sha256: its first <n> bytes hash to it, and what follows is only blank lines and stage5's
    `Pushed to ...` lines. A delivery logged before this check (no sha256) and a README without the code-written
    section: not checked, said in `info`."""
    readme = os.path.join(REPO, "deliverables", "README.md")
    try:
        data = open(readme, "rb").read()
    except OSError:
        return [], []
    top, rel = rounds_rel(os.path.join(REPO, cfg["rounds_dir"]), "RUN_LOG.md")
    log = (committed_blob(top, "HEAD", rel) if top else None) or ""
    sec = log.split(f"\n## {DELIVERY_LOG}\n", 1)[1].split("\n## ", 1)[0] if f"\n## {DELIVERY_LOG}\n" in log else ""
    found = [m for m in (README_LOGGED.search(l) for l in sec.splitlines()) if m]
    gone = readme_log_rewrites(top, rel, {m.group(1) for m in found}) if top else []
    if gone:
        return [f"RUN_LOG.md once logged README.md's sha256 {h_[:12]}… and no longer does (changed by commit {c_}): "
                f"a delivery line was edited or removed after delivery, so the README cannot be checked against it; "
                f"this stays in the record" for h_, c_ in gone[:3]], []
    if not found:
        if CHECKED_HEADING.encode() in data:
            return [f"deliverables/README.md has the section \"{CHECKED_HEADING[3:]}\" but no committed RUN_LOG.md "
                    f"delivery line logs its sha256: --deliver did not write it, or its log line is not committed"], []
        return [], ["deliverables/README.md not checked: its delivery predates the README fingerprint"]
    h, n = found[-1].group(1), int(found[-1].group(2))
    if len(data) < n or hashlib.sha256(data[:n]).hexdigest() != h:
        return [f"deliverables/README.md is not the README delivered (its first {n} bytes do not have the sha256 the "
                f"run log records, {h[:12]}…)"], []
    rest = [l for l in data[n:].decode("utf-8", "replace").splitlines() if l.strip()]
    bad = [l for l in rest if not PUSHED_RE.match(l)]
    if bad:
        return [f"deliverables/README.md has text after the delivered README that is not a `Pushed to` line: "
                f"{bad[0][:80]!r}"], []
    return [], []


def check_delivered(cfg, with_readme=False):
    """[problem] (review MED 3; DESIGN-E fix 2, F11): every file README D fingerprints is in deliverables/ with that
    sha256 -- each PDF also the one its render record shipped --, every PDF there is fingerprinted, and RUN_RECORD.md
    exactly once; with `with_readme`, README.md itself against the run log (readme_problems: --check-delivered; inside
    --deliver the log line does not exist yet). A hash, never a reading of a file."""
    import render_record
    out = os.path.join(REPO, "deliverables")
    readme = os.path.join(out, "README.md")
    if os.path.islink(out) or not os.path.isfile(readme) or os.path.islink(readme):
        return [f"{os.path.relpath(readme, REPO)} is missing: nothing was delivered (python3 audits/project.py --deliver)"]
    fps, rr_fp, other_fp = {}, [], {}
    for line in open(readme, encoding="utf-8").read().splitlines():
        m = DELIVERED_ANY.match(line.strip())
        if not m:
            continue
        if m.group(1).endswith(".pdf"):
            fps[m.group(1)] = m.group(2)
        elif m.group(1) == RUN_RECORD:
            rr_fp.append(m.group(2))
        else:
            other_fp[m.group(1)] = m.group(2)
    ar = approved_round(cfg)
    docs = {"SUMMARY.pdf": ("SUMMARY", None), "REPORT.pdf": ("REPORT", None)}
    if ar:
        docs["SIGNOFF.pdf"] = ("SIGNOFF", ar)
    present = sorted(f for f in os.listdir(out) if f.endswith(".pdf"))
    probs = []
    rr_p = os.path.join(out, RUN_RECORD)
    if len(rr_fp) != 1:
        probs.append(f"README D fingerprints {RUN_RECORD} {len(rr_fp)} time(s), not once: --deliver did not deliver it")
    elif os.path.islink(rr_p) or not os.path.isfile(rr_p):
        probs.append(f"deliverables/{RUN_RECORD} is missing (README D fingerprints it)")
    else:
        import render_record as _rr
        if _rr.sha_file(rr_p) != rr_fp[0]:
            probs.append(f"deliverables/{RUN_RECORD} is not the run record delivered (sha256 now "
                         f"{_rr.sha_file(rr_p)[:12]}…, README D {rr_fp[0][:12]}…)")
    for f in sorted(os.listdir(out)):
        if f.startswith("KNOWN_FAULTS-") and f.endswith(".md"):
            probs.append(f"deliverables/{f}: no KNOWN_FAULTS file is delivered any more (folded into {RUN_RECORD})")
    for f in present:
        p = os.path.join(out, f)
        if os.path.islink(p) or not os.path.isfile(p):
            probs.append(f"deliverables/{f} is not a regular file")
        elif f not in fps:
            probs.append(f"deliverables/{f} has no fingerprint in README D: --deliver did not deliver it")
        elif render_record.sha_file(p) != fps[f]:
            probs.append(f"deliverables/{f} is not the PDF delivered (sha256 now {render_record.sha_file(p)[:12]}…, "
                         f"README D {fps[f][:12]}…)")
    for f, h in sorted(other_fp.items()):
        p = os.path.join(out, f)
        if os.path.islink(p) or not os.path.isfile(p):
            probs.append(f"deliverables/{f} is missing (README D fingerprints it)")
        elif render_record.sha_file(p) != h:
            probs.append(f"deliverables/{f} is not the file delivered (sha256 now {render_record.sha_file(p)[:12]}…, "
                         f"README D {h[:12]}…)")
    if with_readme:
        probs += readme_problems(cfg)[0]
    for f, h in sorted(fps.items()):
        if f not in present:
            probs.append(f"deliverables/{f} is missing (README D fingerprints it)")
        if f not in docs:
            probs.append(f"README D fingerprints {f}, which is no delivered document's PDF")
            continue
        try:
            rec = render_record.load(cfg, render_record.resolve(cfg, *docs[f])[2]) or {}
        except render_record.Refused as e:
            rec = {"shipped_pdf_sha256": f"({e})"}
        if rec.get("shipped_pdf_sha256") != h:
            probs.append(f"README D's fingerprint of {f} ({h[:12]}…) is not the PDF its render record shipped "
                         f"({str(rec.get('shipped_pdf_sha256'))[:12]}…)")
    return probs


def check_delivered_cli(cfg):
    probs = check_delivered(cfg, with_readme=True)
    for p in probs:
        print("RED[deliver] " + " ".join(p.split()))
    info = readme_problems(cfg)[1]
    for i in info:
        print("note: " + i)
    hist = [p for p in probs if p.startswith("RUN_LOG.md once logged README.md's sha256")]
    if hist:        # re-review E L3: a new delivery line cannot bring back the one edited or removed
        print("delivered check: NOT ok: a RUN_LOG.md delivery line was edited or removed after delivery, and delivering "
              "again does not clear that: restore the line as delivered (the history of RUN_LOG.md, `git log -p`, "
              "shows it), or leave it, and this check keeps saying so" + ("; for the rest, deliver again (python3 audits/project.py "
                                                     "--deliver)" if len(hist) < len(probs) else "")
              + "; never a stop")
    elif probs:
        print("delivered check: NOT ok: deliver again (python3 audits/project.py --deliver); never a stop")
    elif info:      # attack review E M1: a README with no logged fingerprint is never reported ok
        print("delivered check: README.md not verified (no delivery line logs its fingerprint); every other "
              "delivered file is the one delivered")
    else:
        print("delivered check: ok")
    return 1 if probs else 0


DELIVERY_STARTED = None         # the running --deliver's start time (deliver), for the delivered RUN_RECORD.md
DELIVERY_LOG = "Delivery"       # RUN_LOG.md's section where --deliver logs each attempt (C1 audit)
DELIVERED_STAGE = "Stage 5 — delivered {when} (deliverables/); next: the completion message (run/stage5-delivery.md)"


class _Tee(io.TextIOBase):
    """stdout that is also kept (deliver's outcome for the run log)."""
    def __init__(self, out):
        self.out, self.buf = out, io.StringIO()

    def write(self, t):
        self.buf.write(t)
        return self.out.write(t)

    def flush(self):
        self.out.flush()


def _now():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def deliver(cfg):
    """project.py --deliver, logged (C1 audit, defect 4: a 22-minute delivery left no trace and RUN_LOG.md still read
    "Stage 5 — final round"): each attempt appends one line under `## Delivery` of RUN_LOG.md -- when it started and
    ended, and whether it delivered or which preconditions refused it (their codes only: the log is a generator input,
    and free text could read as a claim) -- and a delivery sets `## Current stage` to DELIVERED_STAGE. The log is
    written after the checks, so they never see it, and committed by name (approver 2026-10-25: the code that knows
    a mechanical fact records it). The delivered RUN_RECORD.md lists the start and the time it was written."""
    import contextlib
    global DELIVERY_STARTED
    global DELIVERY_NOTES
    t0, t = _now(), _Tee(sys.stdout)
    DELIVERY_NOTES = None
    DELIVERY_STARTED = t0           # run_record.delivery_section lists it in the delivered RUN_RECORD.md
    try:
        with contextlib.redirect_stdout(t):
            rc = _deliver(cfg)
    finally:
        DELIVERY_STARTED = None
    t1, out = _now(), t.buf.getvalue()
    if rc == 0:
        m = re.search(r"^delivered (\d+) file\(s\)", out, re.M)
        what = f"delivered {m.group(1) if m else '?'} file(s) to deliverables/"
        # DESIGN-E fix 2 (F11): README.md's own fingerprint, and the delivery notes' codes (codes only: the log is a
        # generator input); --check-delivered compares the README with it
        try:
            data = open(os.path.join(REPO, "deliverables", "README.md"), "rb").read()
            what += f" (README.md sha256 {hashlib.sha256(data).hexdigest()}, {len(data)} bytes)"
        except OSError:
            pass
        codes_ = collections.Counter(note_code(n) for n in (DELIVERY_NOTES or []))
        what += "; notes: " + (", ".join(f"{c}×{k}" for c, k in sorted(codes_.items())) or "none")
    else:
        codes = sorted(set(re.findall(r"^\s*((?:RED|PENDING|FAIL)\[[\w-]+\])", out, re.M)))
        what = "refused: " + (", ".join(codes) if codes else f"exit {rc}") + " (the command's output says why)"
    try:
        log_append(cfg, DELIVERY_LOG, f"- {t0} to {t1}: project.py --deliver {what}")
        if rc == 0:
            log_append(cfg, "Current stage", DELIVERED_STAGE.format(when=t1), replace=True)
        # approver (2026-10-25): mechanical facts are recorded by the code that knows them, committed by it too
        lp = os.path.relpath(os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md"), AUDITS)
        r = subprocess.run(["git", "-C", AUDITS, "commit", "-q", "-m", f"run log: project.py --deliver ({t1})",
                            "--", lp], capture_output=True, text=True)
        if r.returncode:
            print(f"note: RUN_LOG.md was written but not committed ({' '.join(r.stderr.split())[:200]}): commit it "
                  f"by name; until then `--check-delivered` compares the README with the last committed delivery line "
                  f"and will say NOT ok")
    except (OSError, ValueError) as e:      # the delivery stands; the missing log line is said
        print(f"note: RUN_LOG.md could not be written ({e}): this attempt is not in the run log")
    return rc


REVIEW_DIR = "delivery-review"     # each delivery reviewer's returned text, <PERSPECTIVE>.md (run/stage5-delivery.md)
REVIEW_PERSPECTIVES = ("CLAIMS", "READABILITY", "DECISIONS", "TRUST")


def draft_copies(cfg):
    """[SUMMARY.md / REPORT.md that are byte-identical to their facts draft]: not rewritten by the agent."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    out = []
    for n in ("SUMMARY.md", "REPORT.md"):
        a_, b_ = os.path.join(rd, n), os.path.join(rd, FACTS_DIR, n)
        if os.path.isfile(a_) and os.path.isfile(b_) and open(a_, "rb").read() == open(b_, "rb").read():
            out.append(n)
    return out


JUDGEMENT_MD = "JUDGEMENT.md"     # the main agent's judgement of the delivery reviewers' findings (run/stage5-delivery.md)
NOTES_HEADING = "notes for the main agent (not blocking):"


def human_stop(cfg, s):
    """Does open stop `s` wait for the human: any stop in dev; in release one with a cause of RELEASE_STOP_CODES or of
    release kind `human` (an unreadable record counts as one: fail closed)."""
    if mode(cfg) != "release":
        return True
    import stops
    try:
        doc = json.load(open(os.path.join(stops.stop_dir(cfg, s), "STOP.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return True
    codes = [str(c.get("code")) for c in doc.get("causes") or []]
    # a stop classified `interference` once its cure budget was spent is stop 3, the human's (stops.py classify)
    cls = stops.classifications(cfg, s)
    if cls and cls[-1].get("as") == "interference":
        return True
    return any(c in RELEASE_STOP_CODES or release_kind(c) == "human" for c in codes)


# --- DESIGN-E2 fix 2 (forgery review 2026-11 F1, F8, F11): the code-written section of deliverables/README.md ---------
# The agent writes SUMMARY, REPORT and RUN_RECORD; the checking program writes this one section at --deliver, from the
# records: each result's status as computed, the answers recorded as yours, and every note of the delivery checks. It
# only flags: nothing in it refuses or waits. The notes go word for word into RUN_RECORD.md ("Notes at delivery").
CHECKED_HEADING = "## What the checking code found"
STATUS_WORDING = "Status wording"       # JUDGEMENT.md's section: `- <label>: <why the summary words it differently>`
CHECKED_POINTER = "What the checking code found"    # the SUMMARY line pointing to the section (run/stage5-delivery.md)
DELIVERY_NOTES = None                   # the last _deliver's notes (deliver logs their codes in RUN_LOG.md)
CHECKED_INTRO = ("The checking program wrote this section from the run's records when the files were delivered; the "
                 "agent that wrote the summary did not. Its table is computed mechanically from the review records, so "
                 "a finding on one part of a result can mark the whole result, and the summary may word a status its "
                 "own way. Where the two differ, the agent's reason is shown. The Lean proofs themselves are checked "
                 "separately (see \"Proof checks\").")
CHECKED_FALLBACK = ("The checking program could not write this section ({e}). Until it is written, treat every result "
                    "as not established.")
# (pattern, plain phrase, counted only?), first match wins; a note no pattern matches is SHOWN as "Other" (fail toward
# the reader). Mechanical: the code does not judge which notes matter.
NOTE_KINDS = (
    (r"^\[status-wording\]", "statuses worded differently with no reason (marked † above)", True),
    (r"^\[adj-record\]", "A reviewer's finding not yet ruled on", False),
    (r"^\[unverified\]", "A review missing or out of date", False),
    (r"^\[status-unmapped\]", "A status the program could not compute", False),
    (r"^integrity|^\[ownership\]|FAIL\[(?:ownership|tooling|pin|seal|tool-patch)\]", "The run's records or checking "
                                                                                    "software", False),
    (r"^\[tool patches\]", "The corrected checking software", False),
    (r"only because of rows", "Results not established only because of a decided review finding", False),
    (r"implemented as described|was answered, and no Lean commit", "A decision that may have asked for a Lean change "
                                                                    "no later commit shows", False),
    (r"withdrawn|opened in error", "A stop closed as opened in error", False),
    (r"self-cured stop", "A fixed problem whose check fails again", False),
    (r"^stop S\d+ is open", "A stop still open", False),
    (r"coverage check", "the summary's layout (the program reads its own layout)", True),
    (r"changed since prepare|is stale|changed after prepare|was not recorded by the last prepare|Lean changed since "
     r"prepare|facts draft of \S+ is missing|no DELIVERY\.json", "documents prepared before a later change", True),
    (r"^\[pdf\]", "a PDF left out (its markdown is delivered)", True),
    (r"^\[run record\]|does not name", "the run record or a document not naming a record", True),
    (r"^\[signoff\]|reader gate", "the sign-off sheet's reader", True),
    (r"^\[hashes\]", "the documents' recorded fingerprints", True),
    (r"^DISCLOSED\[", "a fault disclosed instead of a stop (RUN_RECORD.md)", True),
    (r"^\[delivered check\]", "the delivered files' fingerprints", True),
    (r"deliverable\(s\) missing|no approval record|no JUDGEMENT|byte-identical to its facts draft|no line pointing to "
     r"README", "a missing or unwritten file or line", True),
    (r"Lean names the documents cite|Lean name", "the Lean names a document cites", True),
    (r"could not be (?:checked|computed|run)|could not run", "A check that could not run", False),
)
PLURALS = {"Lemmas": "Lemma", "Theorems": "Theorem", "Propositions": "Proposition", "Corollaries": "Corollary",
           "Definitions": "Definition", "Claims": "Claim", "Remarks": "Remark", "Examples": "Example",
           "Conjectures": "Conjecture", "Facts": "Fact", "Observations": "Observation", "Equations": "Equation"}


def _split_outside(text, sep="; "):
    """`text` split at `sep` where it lies outside parentheses and brackets."""
    out, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0 and text.startswith(sep, i):
            out.append(cur); cur, i = "", i + len(sep)
            continue
        cur += ch; i += 1
    return out + [cur]


def norm_label(s, cut=True):
    """A result label for pairing, the same on both sides: `**` removed, whitespace collapsed and, with `cut`, one
    trailing parenthetical removed when it contains a space or a code span ("Lemma 2.3 (repair: x > 0)" -> "Lemma
    2.3", "Lemma 2.4 (`H`)" -> "Lemma 2.4"; "Lemma 3.2 (c)" and "Claim (7)" are kept)."""
    s = " ".join(str(s).replace("**", "").split()).strip()
    if cut:
        m = re.search(r"\s*\(([^()]*)\)$", s)
        if m and (" " in m.group(1) or "`" in m.group(1)) and m.start() > 0:
            s = s[:m.start()].strip()
    return s


def _expand_labels(cell):
    """The labels of one summary cell: split at "; " outside parentheses, then "Lemmas 2.1, 2.2 and 3.4" expanded."""
    out = []
    for part in _split_outside(cell):
        part = " ".join(part.replace("**", "").split())
        m = re.match(r"^(%s)\s+(.+)$" % "|".join(PLURALS), part)
        if m and re.fullmatch(r"[\w.()'-]+(?:\s*(?:,|,?\s+and)\s+[\w.()'-]+)+", m.group(2)):
            out += [f"{PLURALS[m.group(1)]} {x}" for x in re.split(r"\s*(?:,|,?\s+and)\s+", m.group(2)) if x]
        elif part:
            # E2E-FIX2 M2b: "Lemma 2.2, Proposition 2.3, Example 2.4" is three results, when every part outside
            # parentheses opens with a result word ("Definition (ω₁(h), tex l.77)" stays one)
            cs = [re.sub(r"^and\s+", "", " ".join(x.split())) for x in _split_outside(part, ", ")]
            if len(cs) > 1 and all(
                    re.match(rf"(?i)(?:\*\*)?(?:{RESULT_KINDS_RE})\s+\S", x) for x in cs):
                out += cs
            else:
                out.append(part)
    return out


def _status_columns(cells):
    """(status column, labels column) of a summary table's header cells, or None: a cell beginning "Status" is the
    status column; the labels are in the cell beginning "Result" (or "Results"), or, in a two-column table whose
    status column is the first, in the second (E2E-FIX2 M2b: the run's `| Result | Status (as the Lean has it) |` was
    read status-first, and nothing paired)."""
    hd = [re.sub(r"[*_`]", "", c).strip().lower() for c in cells]
    si = next((i for i, c in enumerate(hd) if re.match(r"status\b", c)), None)
    if si is None:
        return None
    li = next((i for i, c in enumerate(hd) if i != si and re.match(r"results?\b", c)), None)
    if li is None and len(hd) == 2 and si == 0:
        li = 1
    return (si, li) if li is not None else None


def summary_result_rows(text):
    """{label: [the summary's status cells]} of the summary's results table: the rows under `## Results` (or before
    the first `## `), else the first table whose header row has a Status column and a Result column (or a Status
    first column of two). The columns are found by the header (_status_columns), by position (status, then labels)
    only when a `## Results` table's header names neither. HTML comments are dropped first, and a label listed in
    several rows keeps every row's cell (attack review E H2: a hidden or earlier decoy row cannot stand in for the
    row the reader sees)."""
    text = re.sub(r"<!--.*?(?:-->|\Z)", "", text, flags=re.S)
    sep = lambda l: bool(re.match(r"^\|[\s:|-]*-[\s:|-]*$", l.rstrip()))
    split = lambda l: [c.strip() for c in _split_outside(l.strip().strip("|"), " | ")]

    def rows(lines, need_header):
        st, on, cols, other = {}, not need_header, (0, 1), False
        for i, l in enumerate(lines):
            if on and need_header and not l.startswith("|"):
                break
            if not l.startswith("|"):
                other = False
                continue
            if not sep(l) and i + 1 < len(lines) and sep(lines[i + 1]):
                hc = _status_columns(split(l))      # a header row: never a data row
                if hc:
                    cols, on = hc, True
                else:       # a header naming no Status column: another table (stops, questions), not read
                    other = True
                continue
            if other or not on or not l.startswith("| ") or re.match(r"^\|\s*Status\b", l) or sep(l):
                continue
            cells = split(l)
            if (len(cells) != 2) if cols == (0, 1) else (len(cells) <= max(cols)):
                continue
            for lbl in _expand_labels(cells[cols[1]]):
                c_ = " ".join(cells[cols[0]].replace("**", "").split())
                if c_ not in st.setdefault(lbl, []):
                    st[lbl].append(c_)
        return st
    sec_ = text.split("\n## Results", 1)[-1].split("\n## ", 1)[0]
    return rows(sec_.splitlines(), False) or rows(text.splitlines(), True)


def status_wording_reasons(rd):
    """{label: reason} of JUDGEMENT.md's `## Status wording` section (`- <label>: <reason>`). A line is read at each
    `": "` it holds, so a label that itself contains ": " still finds its reason (COMPAT-E L4); the first split
    wins for a shorter key."""
    p = os.path.join(rd, JUDGEMENT_MD)
    try:
        jt = open(p, encoding="utf-8").read()
    except OSError:
        return {}
    m = re.search(r"^## +%s\s*$" % re.escape(STATUS_WORDING), jt, re.M)
    if not m:
        return {}
    sec = jt[m.end():].split("\n## ", 1)[0]
    out = {}
    for l in sec.splitlines():
        m2 = re.match(r"^\s*[-*] (.+)$", l)
        if not m2:
            continue
        parts = m2.group(1).split(": ")
        for i in range(1, len(parts)):
            lb, why = ": ".join(parts[:i]), " ".join(": ".join(parts[i:]).split())
            if lb.strip() and why:
                out.setdefault(norm_label(lb, cut=False), why)
    return out


def _first_part(status):
    """The part of a computed status a summary must keep: up to its first ";" or " (" (DESIGN-E2-REVIEW L1)."""
    return re.split(r";| \(", status, 1)[0].strip().lower()


STATUS_FILLER = {"a", "an", "the", "under", "of", "as", "by", "is", "it"}
STATUS_NEGATIONS = {"not", "no", "never", "nor", "without", "unproved", "unfaithful"}


def _status_words(s):
    return re.findall(r"[a-z0-9]+", re.sub(r"[*_`]", "", str(s).lower()))


def status_says(status, cell):
    """Does a summary `cell` keep the computed `status`'s first part (_first_part)? Its exact words, or (REVIEW-E2E-
    FIX2 L-5: "proved; faithful (recorded as a reading choice)" was marked against "faithful under a reading choice")
    its status words in the same order, filler words ("a", "under", "as" ...) aside, with no negation the status
    does not have ("not faithful; a reading choice" is still marked)."""
    fp = _first_part(status)
    if fp in str(cell).lower():
        return True
    want = [w for w in _status_words(fp) if w not in STATUS_FILLER]
    have = _status_words(cell)
    if not want or (STATUS_NEGATIONS & set(have)) - set(_status_words(fp)):
        return False
    it = iter(have)
    return all(w in it for w in want)


def md_quoted(s):
    """Text from the agent's files (a summary cell, a reason) made inert inside the README's quotes: whitespace
    collapsed, `<`, `>` and `&` as entities, backticks and brackets escaped (attack review E L1: no raw HTML or
    markdown from them)."""
    s = " ".join(str(s).split()).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`\[\]])", r"\\\1", s)


def _cut_any_paren(s):
    """`s` without one trailing parenthetical, whatever it holds ("Definition 2.1 (H)" -> "Definition 2.1")."""
    m = re.search(r"\s*\([^()]*\)$", s)
    return s[:m.start()].strip() if m and m.start() > 0 else s


def sheet_checks(rd):
    """{result label: CHECK reason} of the rows the latest approval's sign-off sheet flags CHECK (the round
    APPROVED_FINGERPRINTS.json names, its SIGNOFF.json); a part row ("Lemma 7.4 (c)") also under its result ("Lemma
    7.4"). {} when there is no approval or its sheet cannot be read."""
    try:
        rnd = json.load(open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), encoding="utf-8")).get("round")
        so = json.load(open(os.path.join(rd, str(rnd), "SIGNOFF.json"), encoding="utf-8")) if rnd else {}
    except (OSError, ValueError, AttributeError):
        return {}
    out = {}
    for r in (so.get("rows") or []) if isinstance(so, dict) else []:
        if isinstance(r, dict) and r.get("flag") == "CHECK":
            lab = norm_label(r.get("result", ""), cut=False)
            why = " ".join(str(r.get("check_reason") or "").split())
            out.setdefault(lab, why)
            if re.search(r"\s*\((?:[a-z]|[ivx]+)\)$", lab):
                out.setdefault(re.sub(r"\s*\((?:[a-z]|[ivx]+)\)$", "", lab), why)
    return out


def status_block(cfg, inp):
    """([md line] of the section's Results block, [note]): the computed status of each result (the facts draft's
    plain_status), grouped; a † on a result that the code does not rate exactly *faithful* and whose status some row
    of the summary words without the code status's first part, or that the summary does not list; beside it the
    summary's words and the agent's reason from JUDGEMENT.md "Status wording", or one `[status-wording]` note when no
    reason is on record. Mechanical: no strength test. A faithful result is marked only when the latest approved
    sign-off sheet flags it CHECK (E2E-FIX2 M2a: a reading choice, a generalization or a partial skip the reviews
    passed), with the sheet's reason beside it; its status is not changed."""
    import make_report
    rd = os.path.join(REPO, cfg["rounds_dir"])
    keys = make_report.disclosure_keys(cfg, inp)
    res = [(" ".join(k.ident.split()), k.short) for k in keys if k.group == "Results" and k.prefix == "result"]
    try:
        summ = open(os.path.join(rd, "SUMMARY.md"), encoding="utf-8").read()
    except OSError:
        summ = ""
    raw = summary_result_rows(summ)
    exact, normd, loose = {}, {}, {}
    for k, v in raw.items():
        for d_, k_ in ((exact, norm_label(k, cut=False)), (normd, norm_label(k)),
                       (loose, _cut_any_paren(norm_label(k, cut=False)))):
            d_.setdefault(k_, [])
            d_[k_] += [c_ for c_ in v if c_ not in d_[k_]]

    def cell_of(lbl):
        """[the summary's cells] of the result, or None: an exact label first, then one with its spaced
        parenthetical cut, then a summary label that is the result's plus a trailing parenthetical (L3)."""
        a = norm_label(lbl, cut=False)
        return exact[a] if a in exact else normd.get(norm_label(lbl)) or loose.get(a)
    why_raw = status_wording_reasons(rd)

    def why_of(lbl):
        a = norm_label(lbl, cut=False)
        if a in why_raw:
            return why_raw[a]
        return next((v for k, v in why_raw.items() if norm_label(k) == norm_label(lbl)), None)
    paired = any(cell_of(l) is not None for l, _ in res)
    groups, marked = {}, []
    for lbl, st in res:
        groups.setdefault(st, []).append(lbl)
        if st == "faithful" or not paired:
            continue
        c = cell_of(lbl)
        if c is None or any(not status_says(st, c_) for c_ in c):
            marked.append((lbl, c))
    mk = {l for l, _ in marked}
    checks_ = sheet_checks(rd)
    flagged = [(lbl, checks_[norm_label(lbl, cut=False)]) for lbl, st in res
               if st == "faithful" and norm_label(lbl, cut=False) in checks_]
    mk |= {l for l, _ in flagged}
    out = ["**Each result's status, from the review records.** " + make_report.SUMMARY_LEGEND, "",
           "| Status from the review records | Results |", "|---|---|"]
    out += [f"| {st} | {'; '.join(l + (' †' if l in mk else '') for l in ls)} |" for st, ls in groups.items()]
    out.append("")
    notes, unexplained = [], []
    if not res:
        out.append("The review records name no result.")
    elif not paired:
        out.append("The program could not pair the summary's results table with this one (it found none, or the "
                   "summary names the results its own way): compare the two.")
    elif marked:
        grouped = {}
        for lbl, c in marked:
            w = why_of(lbl)
            if w is None:
                unexplained.append(lbl)
            grouped.setdefault((tuple(c) if c is not None else None, w), []).append(lbl)
        for head, unp in (("† The summary words this status differently:", False),
                          ("† Not paired with a row of the summary's table: the program looked for these names there and found no row "
                           "it could match; a row may name them in other words (compare the two):", True)):
            its = [(c, w, lbls) for (c, w), lbls in grouped.items() if (c is None) == unp]
            if its:
                out.append(head)
            for c, w, lbls in its:
                if w:
                    s_, cut_ = make_report._short(w, 240)
                    rs = (f"The agent's reason: “{md_quoted(s_ or w[:240])}”"
                          + (f" (in full: `{JUDGEMENT_MD}`)." if cut_ else "."))
                else:
                    rs = f"No reason is on record (`{JUDGEMENT_MD}`, \"{STATUS_WORDING}\")."
                if unp:
                    out.append(f"- {', '.join(lbls)}. {rs}")
                else:
                    sw = ("the summary: " if len(c) == 1 else "the summary's rows: ") + ", ".join(
                        f"“{md_quoted(c_)}”" for c_ in c)
                    out.append(f"- {', '.join(lbls)} — {sw}. {rs}")
    else:
        out.append("For each result not rated *faithful*, the program found the first words of its status above in "
                   "every row of the summary that names it; it checks nothing more, so compare the two.")
    if flagged:
        out.append("† Faithful by the review records, but the approved sign-off sheet (appendix C) flags it CHECK, for "
                   "this reason:")
        for lbl, why in flagged:
            s_, cut_ = make_report._short(why, 240) if why else ("", False)
            out.append(f"- {lbl} — the sheet: “{md_quoted(s_ or why[:240]) if why else 'no reason given'}”"
                       + (" (in full: `SIGNOFF.md`)." if cut_ else "."))
    if unexplained:
        notes.append(f"[status-wording] the summary words the status of {len(unexplained)} result(s) differently from "
                     f"the review records with no reason in {JUDGEMENT_MD} \"{STATUS_WORDING}\": "
                     f"{'; '.join(unexplained)} (add `- <label>: <why>` lines and deliver again)")
    try:        # a tool patch that raised a status: neutral words, the labels only
        import integrity, tool_patch
        if integrity.applied_tool_patches(AUDITS, rd):
            rs_ = tool_patch.raised_statuses(cfg, rd, AUDITS)
            if rs_:
                out += ["", "With the checking software as it was when the run started, these results would read "
                            "differently: " + "; ".join(f"{lb} (then: “{old}”)" for lb, _tp, old in rs_) + "."]
    except Exception as e:      # noqa: BLE001 -- said, never hidden
        out += ["", f"Whether a correction of the checking software changed a status could not be computed: {e!r}."]
    return out, notes


def tooling_since_first_pin(audits, rounds_dir):
    """(files, commits, uncommitted) of the checking software since the run's first pin (its `audits_commit`):
    `git diff --name-only <first> HEAD`, `git log --format='%h %s' <first>..HEAD` and `git status --porcelain`, each
    on integrity.TOOLING_PATHSPECS. None when the first pin or its commit cannot be read."""
    import integrity
    base = (first_pin(rounds_dir) or {}).get("audits_commit")
    if not base:
        return None
    G = lambda *a: subprocess.run(["git", "-C", audits, *a], capture_output=True, text=True)
    d = G("diff", "--name-only", base, "HEAD", "--", *integrity.TOOLING_PATHSPECS)
    if d.returncode:
        return None
    files = [l for l in d.stdout.splitlines() if l.strip()]
    commits = [l for l in G("log", "--format=%h %s", f"{base}..HEAD", "--", *integrity.TOOLING_PATHSPECS)
               .stdout.splitlines() if l.strip()]
    unc = [l[3:] for l in G("status", "--porcelain", "--", *integrity.TOOLING_PATHSPECS).stdout.splitlines()
           if l.strip()]
    return files, commits, unc


def _software_line(cfg, rd, notes):
    import integrity
    r = tooling_since_first_pin(AUDITS, rd)
    if r is None:
        return "**The checking software.** The version fixed when the run started could not be read."
    files, commits, unc = r
    if not files and not unc and commits:     # attack review E L2: a change later reverted is still named
        return ("**The checking software.** The same now as when the run started; changed and restored during the "
                "run by: " + "; ".join(f"`{c}`" for c in commits[:8]) + (" …" if len(commits) > 8 else "") + ".")
    if not files and not unc:
        return "**The checking software.** Unchanged since the run started."
    applied = integrity.applied_tool_patches(AUDITS, rd)
    failed = {m for n in notes for m in re.findall(r"FAIL\[tool-patch\]\s*(TP\d+)", str(n))}
    tp, other = [], []
    for c in commits:
        m = re.match(r"^\S+ tool-patch (TP\d+) apply\b", c)
        (tp if m and m.group(1) in applied and m.group(1) not in failed else other).append(c)
    if not other and not unc:
        return (f"**The checking software.** Corrected {len(tp)} time(s) during the run by changes an independent agent "
                f"reviewed (`{RUN_RECORD}`, \"Tool patches\").")
    s = (f"**The checking software.** Changed during the run other than by a reviewed correction "
         f"({', '.join(files[:6])}{' …' if len(files) > 6 else ''}); the checks in this section ran on the changed "
         f"software.")
    if other:
        s += " Commits: " + "; ".join(f"`{c}`" for c in other[:8]) + (" …" if len(other) > 8 else "") + "."
    if unc:
        s += " Uncommitted changes to: " + ", ".join(unc[:6]) + (" …" if len(unc) > 6 else "") + "."
    if tp:
        s += f" Also {len(tp)} reviewed correction(s)."
    if mode(cfg) != "release":
        s += (" (In development mode a maintainer may update the checking software during a run; each commit's "
              "description says what it was.)")
    return s


LEVEL_WORDS = {"hands-off": "the agent took the decisions and approved the statements; you were asked only where a "
                            "stop needed you",
               "statements-only": "you approved the statements; the agent took the later decisions",
               "involved": "you approved the statements and answered the later questions"}
MODE_WORDS = {"release": "Release mode: the run stops only for what needs you; other faults the agent fixes with a "
                         "fixed, logged step, or discloses.",
              "dev": "Development mode: every failed check stopped the run until it was fixed."}


def note_code(n):
    """The code of a delivery note for the RUN_LOG.md line: its leading `[code]`, else `integrity` or `other`."""
    m = re.match(r"^\[([\w -]+)\]", str(n))
    if m:
        return m.group(1).replace(" ", "-")
    return "integrity" if str(n).startswith("integrity") else "other"


def note_kind(n):
    """(plain phrase, counted only?) of a delivery note (NOTE_KINDS; "Other", shown, when none matches)."""
    return next(((p, c) for r, p, c in NOTE_KINDS if re.search(r, str(n))), ("Other", False))


def readme_checked(cfg, notes, inp, status_lines):
    """The section CHECKED_HEADING of deliverables/README.md (md text), each block computed on its own: a block that
    fails says so in its place. Never refuses."""
    import make_report, stops
    rd = os.path.join(REPO, cfg["rounds_dir"])
    out = [CHECKED_HEADING, "", CHECKED_INTRO, ""]

    def block(name, f):
        try:
            out.extend(f())
        except Exception as e:      # noqa: BLE001 -- said in its place, never a refusal
            out.append(f"({name} could not be computed: {type(e).__name__}: {e})")
        out.append("")
    block("the results", lambda: list(status_lines))
    appr = inp.get("approval") or {}

    def proof():
        cf = stops.core_fault_rows(cfg)
        if cf:
            ls = ["**Proof checks at delivery.** " + " ".join(stops.core_fault_marker(c) for c in cf)]
        elif appr:
            ls = ["**Proof checks at delivery.** The Lean build, the check for unfinished proofs (`sorry`), the check "
                  "that only Lean's standard axioms are used, and the check that the approved statements are unchanged "
                  "all passed."]
        else:
            ls = ["**Proof checks at delivery.** The Lean build, the check for unfinished proofs (`sorry`) and the "
                  "check that only Lean's standard axioms are used all passed (no statements approved: the check that "
                  "they are unchanged was not run)."]
        try:        # COMPAT-E M2: a sorry let through by a logged leave line is said beside "passed"
            import decisions
            n_ = len(decisions.unproved(cfg)["decls"])
        except Exception as e:      # noqa: BLE001 -- said, never hidden
            n_, e_ = None, e
        if n_:
            ls[0] += (f" The check for unfinished proofs lets through {n_} Lean declaration(s) left unproved by a "
                      f"logged decision (“stated only” in the table above).")
        elif n_ is None:
            ls[0] += f" Whether a declaration is left unproved by a logged decision could not be read ({e_!r})."
        if mode(cfg) == "release":
            for s_, cmd_, _rc in stops.withdrawn_failing(cfg):
                ls.append(f"Stop {s_} was closed by the operator as opened in error, without a cure, and its check "
                          f"still fails at delivery (`{cmd_}`). `{RUN_RECORD}` lists the stop.")
        return ls
    block("the proof checks", proof)

    def settings():
        lv, md, fp_ = involvement(cfg), mode(cfg), first_pin(rd)
        fc_ = (fp_ or {}).get("config") if isinstance((fp_ or {}).get("config"), dict) else {}
        s = (f"**Run settings.** Involvement level *{lv}* ({LEVEL_WORDS.get(lv, 'not a known level')})"
             + (", as fixed when the run started. " if "involvement" in fc_ else ". ") + MODE_WORDS.get(md, md))
        if not fp_:
            s += " The settings fixed at the start could not be read; this is the settings file's value."
        else:       # attack review E L4: "as fixed" only for what the first pin records
            miss_ = [w_ for k_, w_ in (("involvement", "the involvement level"), ("mode", "the run mode"))
                     if k_ not in fc_]
            if miss_:
                s += (f" The settings fixed at the start do not record {' or '.join(miss_)}; this is the settings "
                      f"file's value.")
        for k, w, f_ in terms_differ(cfg):
            s += f" The run's settings file now says *{w}* for {k}; every check used *{f_}*."
        return [s]
    block("the run settings", settings)
    block("the checking software", lambda: [_software_line(cfg, rd, notes)])

    def answers():
        keys = make_report.disclosure_keys(cfg, inp)
        ans = [k for k in keys if k.group == make_report.ANSWERS_SECTION]
        by = approval_file_by(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), appr)[0] if appr else None
        if not appr:
            tail = "No approval of the statements is on record."
        elif involvement(cfg) == "hands-off" or by == "agent":
            tail = ("The statements were approved by the agent, not by you (hands-off)"
                    + ("; every other decision was the agent's (`DECISIONS.md`)." if ans else
                       ", and the agent took every decision (`DECISIONS.md`)."))
        elif any(k.prefix == "approval" for k in ans):
            tail = "The statements: approved by you (the approval above)."
        else:
            tail = (f"The statements: approved by you (the approval's Lean commit is "
                    f"`{str(appr.get('commit', '?'))[:11]}`).")
        if not ans:
            return [f"**{make_report.ANSWERS_SECTION}.** None. " + tail]
        return ([f"**{make_report.ANSWERS_SECTION}.** " + make_report.ANSWERS_INTRO]
                + [f"- {k.prefix} ({k.ident}): {k.short}" for k in ans] + [tail])
    block("the answers recorded as yours", answers)

    def reviews():
        have = [p for p in REVIEW_PERSPECTIVES if os.path.isfile(os.path.join(rd, REVIEW_DIR, p + ".md"))]
        if not have:
            return ["**Reviews of the summary and the report.** No review of the summary and the report is on record."]
        return [f"**Reviews of the summary and the report.** {len(have)} review(s) ({', '.join(p.lower() for p in have)})"
                f" are in the audit record's `{REVIEW_DIR}/` folder (not in this folder). The formalizing agent saved "
                f"them, so the record cannot show who wrote them."]
    block("the reviews", reviews)

    def noticed():
        ns = list(dict.fromkeys(" ".join(str(n).split()) for n in notes))
        if not ns:
            return ["**What the checks noticed at delivery.** Nothing."]
        ls = [f"**What the checks noticed at delivery.** {len(ns)} note(s) to the formalizing agent; a note never "
              f"stops a delivery. Each is in `{RUN_RECORD}`, \"Notes at delivery\", word for word."]
        labels = [" ".join(k.ident.split()) for k in make_report.disclosure_keys(cfg, inp)
                  if k.group == "Results" and k.prefix == "result"]
        grp, counted = {}, {}
        for n in ns:
            p, c = note_kind(n)
            if c:
                counted[p] = counted.get(p, 0) + 1
            else:
                grp.setdefault(p, []).append(n)
        for p, nn in grp.items():
            names = list(dict.fromkeys(l for n in nn for l in labels
                                       if re.search(r"(?<![\w.])" + re.escape(l) + r"(?![\w.])", n)))
            what = "; ".join(names) if names else "; ".join(
                (make_report._short(re.sub(r"^\[[\w -]+\]\s*", "", n), 160)[0] or n[:160]) for n in nn[:3])
            ls.append(f"- {p}: {what}" + (f" ({len(nn)} notes)" if len(nn) > 1 else "") + ".")
        if counted:
            ls.append("- About the documents only: " + ", ".join(f"{v} on {k}" for k, v in counted.items()) + ".")
        return ls
    block("the notes", noticed)
    out.append("**Checking this folder later.** `python3 audits/project.py --check-delivered`, run in the audit record, "
               "says whether a delivered file was changed after delivery (section D lists their fingerprints).")
    return "\n".join(out) + "\n"


def insert_checked(cover, section):
    """README A-C with `section` inserted before its first `\\n## ` line (after the title and the intro), else
    appended."""
    i = cover.find("\n## ")
    if i < 0:
        return cover.rstrip("\n") + "\n\n" + section
    return cover[:i + 1] + section + "\n" + cover[i + 1:]


def _deliver(cfg):
    """project.py --deliver (approver, 2026-10-28, binding: after the mathematics is verified, delivery never stops and
    is never refused except by the math gate). THE MATH GATE, the only refusals: Phase 0 read-only GREEN (the build, no
    `sorry` beyond a logged leave line, standard axioms only), the freeze (fingerprint.py --check; no re-approval
    open), the integrity of the proof-validity core (stops.math_gate) and no Lean commit after the last audited round
    (`deliver-stale`, within the delivery round cap). Everything else -- the prepared documents' staleness, the
    reader gates, hand-edit records, the status check, result_status disagreements, pending adjudication,
    `unverified`, ownership of document and reader files, the PDF render guard, an open stop or Checkpoint C, the
    run record's listing, the tool-patch delivery check -- is printed under NOTES_HEADING for the main agent, who
    judges it (run/stage5-delivery.md); none refuses and none is a stop. Then the delivery copy in
    <project>/deliverables/ (git-excluded): SUMMARY and REPORT (the main agent's), each with its PDF when
    render_record.py shipped one, the latest approval's sheet, DECISIONS.md, RUN_RECORD.md (as in the rounds
    directory, then its delivery-phase notes), JUDGEMENT.md and CITATIONS.md when present, and README.md (README A-C,
    then section D)."""
    import shutil
    import decisions, make_report, stops
    rd = os.path.join(REPO, cfg["rounds_dir"])
    block, notes = [], []

    def note(what, f, *a):
        try:
            r_ = f(*a)
        except Exception as e:      # noqa: BLE001 -- a note, never a refusal
            notes.append(f"{what} could not be checked ({type(e).__name__}: {e})")
            return None
        return r_
    # the freeze, first (B2: while the human's question is open nothing else is printed): an open re-approval is a
    # statement that is not approved yet; PENDING, never a failure line, so it opens no stop
    if note("the re-approval state", decisions.reapproval_question, cfg):
        print("PENDING[question] not delivered (the freeze, part of the math gate): "
              + (decisions.question_refusal(cfg) or "a re-approval is open: finish it (run/reapproval.md)"))
        return 1
    # the designed human waits (a wait, never a stop; review 2026-10-28): Checkpoint C under involved, and a stop that
    # waits for the human -- a release human stop (RELEASE_STOPS, or a cause of kind `human`), any open stop in dev.
    # Another open stop (e.g. a release tool-bug stop about a deliverable) is a note
    c_ = note("Checkpoint C", decisions.checkpoint_c_refusal, cfg)
    if c_:
        print("PENDING[question] not delivered: " + c_)
        return 1
    busy = note("the open stop", stops.open_name, cfg)
    if busy:
        if human_stop(cfg, busy):
            print(f"PENDING[stop] not delivered: stop {busy} is open and waits for the human; once it is closed, "
                  f"prepare again and deliver")
            return 1
        notes.append(f"stop {busy} is open (not a human stop)")
    # make_report.py --check --delivery: deliver-stale is the gate's; every other code a note. The summary's inputs
    # are computed once, for the checks and the README's code-written section (DESIGN-E fix 2)
    inp = note("the summary's inputs", make_report.summary_inputs, cfg)
    try:
        pre = make_report.delivery_problems(cfg, inp)
    except Exception as e:      # noqa: BLE001 -- the stale check alone, then
        notes.append(f"the delivery checks could not run ({type(e).__name__}: {e})")
        try:
            pre = [("deliver-stale", t) for t in make_report.stale_problems(cfg)]
        except Exception as e2:     # noqa: BLE001 -- fail closed: the gate cannot tell
            pre = [("deliver-stale", f"whether a Lean commit came after the last audited round could not be checked: "
                                     f"{e2!r}")]
    block += [(c, t) for c, t in pre if c == "deliver-stale"]
    notes += [f"[{c}] {' '.join(str(t).split())}" for c, t in pre if c != "deliver-stale"]
    try:
        gb, gn = stops.math_gate(cfg)
    except Exception as e:      # noqa: BLE001 -- fail closed: the gate could not run
        gb, gn = [f"the math gate could not run: {e!r}"], []
    block += [("deliver", g) for g in gb]
    notes += gn
    # OPERATOR-PATCH: the first pin's tool-patch verifier and every forced full round, as notes (approver 2026-10-28)
    import tool_patch
    try:
        tpd = tool_patch.delivery_problems(cfg)
    except Exception as e:      # noqa: BLE001 -- a note, never a refusal
        tpd = [f"the tool-patch delivery check could not run ({type(e).__name__}: {e})"]
    carry = {}
    for x in tpd:
        m = re.match(r'^((?:SUMMARY|REPORT)\.md) does not carry "(.+?): this status was decided by a corrected', str(x))
        if m:
            carry.setdefault(m.group(1), []).append(m.group(2))
        else:
            notes.append(f"[tool patches] {x}")
    for d_, names_ in carry.items():
        notes.append(f"[tool patches] {d_} does not say, for {len(names_)} result(s), that its status was decided by "
                     f"the corrected checking software (the first pin's tools would say otherwise): "
                     f"{'; '.join(names_)}. Say it in plain words where it holds; the claims reviewer checks it")

    def say_notes():
        if notes:
            print(NOTES_HEADING)
            for n_ in dict.fromkeys(notes):
                print("  note: " + " ".join(str(n_).split()))
    if block:
        for code, t in block:
            print(f"RED[{code}] not deliverable (the math gate): " + " ".join(str(t).split()))
        say_notes()
        return 1
    out = os.path.join(REPO, "deliverables")
    if os.path.islink(out):
        print(f"RED[deliver] {out} is a symbolic link: nothing is written through it"); return 1
    ar = approved_round(cfg)
    if not ar:
        notes.append("no approval record (APPROVED_FINGERPRINTS.json): no sign-off sheet delivered")
    # PDF-AGENTS: each PDF the one render_record.py shipped for its markdown as it is now -- a note when not
    import render_record
    docs_ = [("SUMMARY", None), ("REPORT", None)] + ([("SIGNOFF", ar)] if ar else [])
    for n_ in (note("the drafts", draft_copies, cfg) or []):
        notes.append(f"{n_} is byte-identical to its facts draft ({FACTS_DIR}/{n_}): write it yourself from the records "
                     f"and the Lean (run/stage5-delivery.md step 5)")
    stale_pdf = set()
    for d_, r_ in docs_:
        u_ = note(f"the {d_} PDF", RENDER_CHECK, cfg, d_, r_) or []
        if u_:      # a PDF that is not the one rendered from the md as it is now never ships beside it
            stale_pdf.add(d_)
            notes += [f"[pdf] {u} -- delivered as markdown only until rendered again" for u in u_]
    files = []
    for d_, r_ in docs_:
        oc_, pdf_ = note(f"the {d_} render record", render_record.delivered, cfg, d_, r_) or (None, None)
        pdf_ = None if d_ in stale_pdf else pdf_
        files += ([pdf_] if pdf_ else []) + [render_record.md_path(cfg, d_, r_)]   # the md beside, always (review 12)
        if d_ == "REPORT":
            files.append(os.path.join(rd, "DECISIONS.md"))
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        notes.append(f"{len(missing)} deliverable(s) missing, not delivered: "
                     + ", ".join(os.path.relpath(m, REPO) for m in missing))
    files = [f for f in files if f not in missing]
    os.makedirs(out, exist_ok=True)
    _exclude("deliverables/")
    kept, dropped = note("the known-fault notices", keep_notices, cfg,
                         sorted(glob.glob(os.path.join(rd, "KNOWN_FAULTS-*.md"))), ar) or ([], [])
    for f in ("SUMMARY.pdf", "REPORT.pdf", "SIGNOFF.pdf"):
        # a PDF of an earlier delivery never stands beside a document now delivered as markdown only (no-pdf)
        if os.path.join(out, f) not in [os.path.join(out, os.path.basename(x)) for x in files] \
                and os.path.isfile(os.path.join(out, f)) and not os.path.islink(os.path.join(out, f)):
            os.remove(os.path.join(out, f))
    for f in os.listdir(out):
        fp_ = os.path.join(out, f)
        if f.startswith("KNOWN_FAULTS-") and f.endswith(".md") and os.path.isfile(fp_) and not os.path.islink(fp_):
            os.remove(fp_)
    if not os.path.islink(os.path.join(out, "superseded")):
        shutil.rmtree(os.path.join(out, "superseded"), ignore_errors=True)
    for f in files:
        shutil.copy2(f, os.path.join(out, os.path.basename(f)))
    delivered = list(files)
    import run_record
    rr_out = os.path.join(out, RUN_RECORD)
    if os.path.islink(rr_out):
        print(f"RED[deliver] {rr_out} is a symbolic link: nothing is written through it"); return 1
    rr_in = os.path.join(rd, RUN_RECORD)
    if not os.path.isfile(rr_in):
        notes.append(f"{RUN_RECORD} is missing from the rounds directory: the delivered one has its delivery notes only")
    open(rr_out, "w", encoding="utf-8").write(
        (open(rr_in, encoding="utf-8").read() if os.path.isfile(rr_in) else "# Run record\n")
        + (note("the run record's delivery section", run_record.delivery_section, cfg, kept, dropped) or ""))
    delivered.append(rr_out)
    # approver (2026-10-24): the process record lists every applied tool patch, operator-closed stop and set-aside
    # (integrity.py, from the raw records); a note for the agent, who corrects RUN_RECORD.md (approver 2026-10-28)
    import integrity
    notes += [f"[run record] {m}" for m in (note("the run record's listing", integrity.run_record_problems, AUDITS, rd,
                                                 open(rr_out, encoding="utf-8").read()) or [])]
    # the advisory citation notes and the main agent's judgement of the delivery reviews: copied when present,
    # never checked; an earlier delivery's copy never stands beside a delivery without them
    for name_ in ("CITATIONS.md", JUDGEMENT_MD):
        src_, dst_ = os.path.join(rd, name_), os.path.join(out, name_)
        if os.path.isfile(dst_) and not os.path.islink(dst_):
            os.remove(dst_)
        if os.path.isfile(src_) and not os.path.islink(src_):
            shutil.copy2(src_, dst_)
            delivered.append(dst_)
        elif name_ == JUDGEMENT_MD:
            notes.append(f"no {JUDGEMENT_MD} in the rounds directory: the delivery reviewers' findings were not judged "
                         f"on record (run/stage5-delivery.md)")
    # DESIGN-E2 fix 2: the code-written section's results block (its `[status-wording]` note joins the notes), then
    # every note, word for word, at the end of the delivered RUN_RECORD.md (before README D fingerprints it)
    global DELIVERY_NOTES
    status_lines = []
    try:
        if inp is None:
            raise ValueError("the summary's inputs could not be computed")
        status_lines, sw_ = status_block(cfg, inp)
        notes += sw_
    except Exception as e:      # noqa: BLE001 -- said in the section and as a note, never a refusal
        status_lines = [f"(the results could not be computed: {type(e).__name__}: {e})"]
        notes.append(f"the README section's results could not be computed ({type(e).__name__}: {e})")
    notes[:] = list(dict.fromkeys(" ".join(str(n_).split()) for n_ in notes))
    nl_ = note("the run record's delivery notes", run_record.notes_lines, notes)
    if nl_:
        open(rr_out, "a", encoding="utf-8").write(nl_)
    # README.md = README A-C as prepared (generated now when there is none), the code-written section inserted before
    # its first `## ` line, then section D (N6), which fingerprints every other delivered file
    ac_ = os.path.join(rd, README_AC)
    ac_text = open(ac_, encoding="utf-8").read() if os.path.isfile(ac_) else (note("README A-C", readme_ac, cfg) or "")
    try:
        sect_ = readme_checked(cfg, notes, inp or {}, status_lines)
    except Exception as e:      # noqa: BLE001 -- the fallback text and a note, never a refusal
        notes.append(f"the README section \"{CHECKED_HEADING[3:]}\" could not be written ({type(e).__name__}: {e})")
        sect_ = CHECKED_HEADING + "\n\n" + CHECKED_FALLBACK.format(e=f"{type(e).__name__}: {e}") + "\n"
    cover = insert_checked(ac_text, sect_) \
        + (note("README section D", readme_d, cfg, files, kept, dropped, delivered)
           or "\n## D. Delivery notes\n\n(could not be written: see the notes)\n")
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(cover)
    delivered.append(os.path.join(out, "README.md"))
    notes += [f"[delivered check] {b}" for b in (note("the delivered check", check_delivered, cfg) or [])]
    DELIVERY_NOTES = list(notes)
    print(f"delivered {len(delivered)} file(s) to {out}")
    say_notes()
    return 0


# --- running Lean on the project (RULINGS D3: one runner for axiom_sweep, fingerprint,
# dependencies, unused_args and signoff) -------------------------------------------------------
def run_main(main_fn, *args):
    """Every script's entry point (L2, U2 §8): `main_fn(*args)`'s exit code; an uncaught exception prints
    its traceback (stderr) and then `FAIL[uncoded] <script>: ...` (stdout), exit 1 -- a coded line, so a
    crash is the unknown-retry route (stops.RETRY shares its key), never an uncoded failure the operator
    must spell. SystemExit and KeyboardInterrupt pass through. `tests` of project.py's selftest check
    that every script under audits/ ends in it (_run_main_sweep)."""
    script = os.path.basename(sys.argv[0] or "?")
    try:
        return main_fn(*args)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:      # noqa: BLE001 -- the crash is reported, coded
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        msg = " ".join(f"{type(e).__name__}: {e}".split())[:300]
        print(f"FAIL[uncoded] {script} crashed ({msg}): re-run it (stops.py open --note \"{script} crashed\" "
              f"--cause unknown-retry with the read-only check of this step); a crash that persists is "
              f"tool-bug or env-unknown (RUN.md failure table)", flush=True)
        return 1


def _run_main_sweep(audits=None):
    """[script] under audits/ whose `__main__` block does not end in run_main (L2): a crash there would
    print a bare traceback, an uncoded failure."""
    audits = audits or AUDITS
    out = []
    for f in sorted(glob.glob(os.path.join(audits, "*.py"))):
        src = open(f, encoding="utf-8").read()
        m = re.search(r"""^if __name__ ?== ?['"]__main__['"]:(.*)\Z""", src, re.S | re.M)
        if m and "run_main(main" not in m.group(1):
            out.append(os.path.basename(f))
    return out


def _run_main_controls():
    """L2: a script ending in run_main that crashes prints one coded line; one that does not is flagged by
    the sweep (a negative control); SystemExit passes through."""
    import tempfile, stops
    d = tempfile.mkdtemp(prefix="runmain-")
    try:
        crash = os.path.join(d, "crashy.py")
        open(crash, "w").write(f"import sys\nsys.path.insert(0, {AUDITS!r})\nimport project\n"
                               "def main():\n    raise ValueError('boom 42')\n"
                               "if __name__ == '__main__':\n    sys.exit(project.run_main(main))\n")
        r = subprocess.run([sys.executable, "-B", crash], capture_output=True, text=True, cwd=d)
        cs = stops.causes(r.stdout)
        ok = (r.returncode == 1 and r.stdout.startswith("FAIL[uncoded] crashy.py crashed (ValueError: boom 42)")
              and "Traceback" in r.stderr and "Traceback" not in r.stdout
              and [c["code"] for c in cs] == ["uncoded"] and "uncoded" in stops.RETRY
              and RELEASE.get("uncoded") == ("I", "rerun") and closer("uncoded") == "@check"
              and not is_stop_cause("uncoded"))
        open(crash, "w").write("import sys\ndef main():\n    return 3\nif __name__ == '__main__':\n    sys.exit(main())\n")
        ok = ok and _run_main_sweep(d) == ["crashy.py"]
        ok = ok and run_main(lambda: 5) == 5
        try:
            run_main(lambda: sys.exit(4)); ok = False
        except SystemExit as e:
            ok = ok and e.code == 4
        return ok
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def module_root(cfg):
    """The root module of an import-mode project ("" in append mode)."""
    sw = cfg.get("sweep", {})
    return sw.get("module", "").split(".")[0] if sw.get("mode") == "import" else ""


def lean_body(cfg):
    """Lean text that brings the project into scope (config `sweep`): `import <module>`, or the whole
    `sweep.file` in append mode (where the namespace is not a module, so `import <namespace>` fails)."""
    sw = cfg["sweep"]
    if sw["mode"] == "import":
        return f"import {sw['module']}\n"
    if sw["mode"] == "append":
        return open(os.path.join(REPO, sw["file"]), encoding="utf-8").read()
    raise SystemExit(f"FAIL: unknown sweep.mode {sw['mode']!r}")


def lean_tail(cfg, path, subs=(), root=None):
    """A *_tail.lean file with __NAMESPACE__, `__MODULE_ROOT__ (module_root(cfg) unless `root` is
    given) and the (placeholder, value) pairs of `subs` filled in."""
    root = module_root(cfg) if root is None else root
    t = (open(path, encoding="utf-8").read().replace("__NAMESPACE__", cfg["namespace"])
         .replace("`__MODULE_ROOT__", ("`" + root) if root else "Name.anonymous"))
    for k, v in subs:
        t = t.replace(k, v)
    return t


def run_lean(src, lean_path=None):
    """(exit code, stdout + stderr) of `lake env lean` on `src`, written to a temporary file and run
    from the project root. `lean_path`: a directory of extra .olean modules (`lake env` keeps a
    LEAN_PATH it is given after its own entries)."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".lean", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        env = dict(os.environ, LEAN_PATH=lean_path) if lean_path else None
        r = subprocess.run(["lake", "env", "lean", path], cwd=REPO, capture_output=True, text=True, env=env)
    finally:
        os.unlink(path)
    return r.returncode, r.stdout + r.stderr


def latex(tex, out_dir=None):
    """Compile `tex` twice with xelatex (so cross-references and longtable widths settle), shell
    escape OFF, from its own directory, output in out_dir (default: beside it). Stops at the first
    failing run. (ok, the error lines of a failure, else [])."""
    tex = os.path.abspath(tex)
    out = ["-output-directory=" + os.path.abspath(out_dir)] if out_dir else []
    # reproducible: the same .tex gives the same PDF bytes wherever it is compiled
    env = dict(os.environ, SOURCE_DATE_EPOCH="946684800", FORCE_SOURCE_DATE="1")
    for _ in range(2):
        r = subprocess.run(["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                            *out, os.path.basename(tex)], cwd=os.path.dirname(tex), capture_output=True, text=True,
                           env=env)
        if r.returncode != 0:
            # a failed run may leave a partial PDF (the pages shipped before the error): never left behind
            remove_pdf(os.path.join(os.path.abspath(out_dir) if out_dir else os.path.dirname(tex),
                                    os.path.basename(tex)[:-4] + ".pdf"))
            return False, [l for l in r.stdout.splitlines() if l.startswith("!")] or [r.stdout[-300:]]
    return True, []


def compile_source(tex, out_dir):
    """Compile a .tex source with latex() in out_dir (RUN.md, Stage 1, step 2: result numbers come
    from the .aux)."""
    tex = os.path.abspath(tex)
    os.makedirs(out_dir, exist_ok=True)
    ok, _ = latex(tex, out_dir)
    aux = os.path.join(out_dir, os.path.splitext(os.path.basename(tex))[0] + ".aux")
    print(f"compiled {tex} -> {out_dir} ({'ok' if ok else 'xelatex failed'}); numbering in {aux}"
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


def _test_mode_real_run():
    """A process without --selftest in its own argv, FORMALIZE_TEST_MODE set to the mode this
    installation is NOT: the config's mode stands and problems() still refuses the other mode.
    Positive control: the same process with --selftest takes the test mode and accepts it."""
    inst = installed_mode() if installed_mode() in MODES else "release"
    other = next(m for m in MODES if m != inst)
    code = ("import sys; sys.path.insert(0, %r); import project as p; "
            "c = p._test_level({'name': 'x', 'mode': %r}); "
            "print(c.get('mode'), p._test_mode(), any(x.startswith('! mode') for x in p.problems(c)), "
            "any(x.startswith('! mode') for x in p.problems({'name': 'x', 'mode': %r, '_test_mode': %r})))"
            % (AUDITS, inst, other, other))
    def run(*extra):
        env = dict(os.environ, **{TEST_MODE_ENV: other})
        r = subprocess.run([sys.executable, "-B", "-c", code, *extra], capture_output=True, text=True, env=env)
        return r.stdout.split()
    real, test = run("--check"), run("--selftest")
    refuses = installed_mode() in MODES
    # real: the config's own mode, no complaint; a planted marker does not excuse the other mode.
    # test: the test mode, accepted.
    return (real[:3] == [inst, "None", "False"] and test[:3] == [other, other, "False"]
            and (not refuses or real[3:] == ["True"]))


def _quiet(f):
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return f()


def _pyc_kinds():
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="pyc-")
    try:
        os.makedirs(os.path.join(d, "__pycache__"))
        def mk(rel, flags):
            open(os.path.join(d, rel), "wb").write(b"\0\0\r\n" + flags.to_bytes(4, "little") + b"\0" * 8)
            return os.path.join(d, rel)
        return (dangerous_pyc(mk("x.pyc", 0)) is not None and dangerous_pyc(mk("__pycache__/a.cpython-312.pyc", 1)) is not None
                and dangerous_pyc(mk("__pycache__/b.cpython-312.pyc", 0)) is None
                and dangerous_pyc(mk("__pycache__/c.cpython-312.pyc", 3)) is None
                and len(apparatus_pycs(d)) == 4)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _env_clean():
    import tempfile, shutil, io, contextlib
    global AUDITS
    keep, d = AUDITS, tempfile.mkdtemp(prefix="envc-")
    try:
        AUDITS = d
        os.makedirs(os.path.join(d, "__pycache__"))
        open(os.path.join(d, "__pycache__", "a.cpython-312.pyc"), "wb").write(b"\0" * 16)
        open(os.path.join(d, "__pycache__", "u.cpython-312.pyc"), "wb").write(b"\0" * 4 + b"\1\0\0\0" + b"\0" * 8)
        with contextlib.redirect_stdout(io.StringIO()):
            env_check()
        return (not os.path.exists(os.path.join(d, "__pycache__", "a.cpython-312.pyc"))
                and os.path.exists(os.path.join(d, "__pycache__", "u.cpython-312.pyc")))
    finally:
        AUDITS = keep
        shutil.rmtree(d, ignore_errors=True)


def _refuses_hard(fake):
    global all_projects
    keep = all_projects
    all_projects = lambda: {fake["name"]: fake}
    try:
        select(fake["name"])
        return False
    except SelectionError as e:
        return "hard config error" in str(e) and "missing field" in str(e)
    finally:
        all_projects = keep


def _order_controls():
    """order_rounds on a throwaway git repo whose commit times run backwards (a rebase): [(check, passed)].
    scope.py's selftest checks the diff base through previous_commit, with a set-aside round between."""
    import shutil, tempfile
    gr = tempfile.mkdtemp(prefix="ord-")

    def g(*a, when=None):
        env = dict(os.environ, **({"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}))
        return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", gr, *a],
                              capture_output=True, text=True, env=env).stdout.strip()
    try:
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        cs = []
        for i, when in enumerate(("2026-01-01T12:00:00", "2026-01-01T10:00:00", "2026-01-01T11:00:00")):
            open(os.path.join(gr, "A.lean"), "a").write(f"{i}\n")
            g("add", "A.lean"); g("commit", "-qm", f"c{i}", when=when)
            cs.append(g("rev-parse", "--short=11", "HEAD"))
        rr = os.path.join(gr, "rr")
        # names: by date the c0 round is newest; by commit time the c1 round is oldest
        d0, d1, d1f, d2 = (os.path.join(rr, n) for n in (f"2026-01-03-{cs[0]}", f"2026-01-02-{cs[1]}",
                                                          f"2026-01-02-full-{cs[1]}", f"2026-01-01-{cs[2]}"))
        for k, d in enumerate((d0, d1f, d1, d2)):   # the full round at c1 is cut BEFORE the diff round there
            os.makedirs(d); open(os.path.join(d, "TARGET.json"), "w").write("{}")   # a round (is_round)
            os.utime(d, (1_000_000 + k, 1_000_000 + k))
        open(os.path.join(d2, ABANDONED), "w").write("{}")
        os.utime(d2, (2_000_000, 2_000_000))
        u = os.path.join(rr, "2026-01-09-abcdef0123")   # a hash git cannot resolve (pruned)
        os.makedirs(u); open(os.path.join(u, "TARGET.json"), "w").write("{}"); os.utime(u, (0, 0))
        order = [os.path.basename(x) for x in order_rounds([d2, d1, d0, d1f], gr)]
        return [("round order follows Lean ancestry, not commit time or name",
                 order == [os.path.basename(x) for x in (d0, d1f, d1, d2)]),
                ("two rounds of one commit: the one cut first is first (scope time, not name)",
                 order.index(os.path.basename(d1f)) < order.index(os.path.basename(d1))),
                ("rounds(): ordered, a set-aside round left out unless asked for",
                 [os.path.basename(x) for x in rounds({"rounds_dir": rr}, repo=gr)]
                 == [os.path.basename(x) for x in (u, d0, d1f, d1)]
                 and rounds({"rounds_dir": rr}, include_abandoned=True, repo=gr)[-1] == d2),
                ("an unresolvable hash is placed by its directory's time", order_rounds([d0, u], gr)[0] == u),
                ("no repository: directory time, then name", order_rounds([d0, d2], None) == [d0, d2])]
    finally:
        shutil.rmtree(gr, ignore_errors=True)


def _changes_controls():
    """changes_after_last_audit on a throwaway git repo: [(check, passed)]. make_report's selftest
    checks the same through the report's trust row (one end-to-end path); these are the unit checks."""
    global REPO
    import shutil, tempfile
    gr = tempfile.mkdtemp(prefix="cal-")
    saved, REPO = REPO, gr

    def g(*a, when=None):
        env = dict(os.environ, **({"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {}))
        return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", gr, *a],
                              capture_output=True, text=True, env=env).stdout.strip()

    def commit(fname, txt, msg, when):
        open(os.path.join(gr, fname), "a").write(txt)
        g("add", fname)
        g("commit", "-qm", msg, when=when)
        return g("rev-parse", "--short=11", "HEAD")

    def mkround(name, kind):
        d = os.path.join(gr, "rr", name)
        os.makedirs(d, exist_ok=True)
        json.dump({"_meta": {"kind": kind}}, open(os.path.join(d, "TARGET.json"), "w"))
        return d
    cfg, checks = {"rounds_dir": "rr", "lean_files": ["A.lean"]}, []
    try:
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        c1 = commit("A.lean", "x\n", "base", "2026-01-01T10:00:00")
        r1 = mkround(f"2026-01-01-{c1}", "diff")
        c2 = commit("A.lean", "y\n", "audited fix", "2026-01-01T11:00:00")
        r2 = mkround(f"2026-01-01-{c2}", "diff")
        c3 = commit("A.lean", "z\n", "late fix", "2026-01-01T12:00:00")
        r3 = mkround(f"2026-01-01-full-{c3}", "statements")
        commit("notes.md", "n", "docs", "2026-01-01T13:00:00")
        c5 = commit("lakefile.lean", "--", "bump", "2026-01-01T14:00:00")
        r4 = os.path.join(gr, "rr", f"2026-01-01-{c5}")
        os.makedirs(os.path.join(r4, "prompts"))      # reader prompts only: no round examined c5
        c = changes_after_last_audit(cfg, [r1, r2, r3, r4]) or {}
        checks.append(("changes after the last audit: the newest proof round is the last one, a statement "
                       "round is not an audit round, nor is a directory without TARGET.json (empty scope, "
                       "reader prompts only)", c.get("round") == os.path.basename(r2) and c.get("commit") == c2))
        cm = " ".join(c.get("commits") or [])
        checks.append(("changes after the last audit: later Lean and build-file commits are listed, others not",
                       len(c.get("commits") or []) == 2 and "late fix" in cm and "bump" in cm and "docs" not in cm))
        open(os.path.join(gr, "A.lean"), "a").write("dirty\n")
        checks.append(("changes after the last audit: uncommitted Lean edits are listed",
                       (changes_after_last_audit(cfg, [r1, r2]) or {}).get("dirty") == ["A.lean"]))
        g("checkout", "-q", "--", "A.lean")
        # review of fix-mini1 (M1): a round-named directory holding only prompts, or nothing, is no
        # round for ANY consumer (rounds(): the diff base, resolve_round, the readers' newest round)
        r5 = os.path.join(gr, "rr", f"2026-01-02-{c5}"); os.makedirs(r5)   # mkdir'd for a reader
        r6 = os.path.join(gr, "rr", f"2026-01-01-full-{c2}"); os.makedirs(r6)
        open(os.path.join(r6, "ADOPTED.md"), "w").write("| lane | item | verdict | decision | reason |\n")
        checks.append(("rounds(): a directory with only prompts, or empty, is no round; one with TARGET.json "
                       "or ADOPTED.md is", [os.path.basename(x) for x in rounds(cfg)]
                       == [os.path.basename(x) for x in (r1, r2, r6, r3)]))
        r7 = os.path.join(gr, "rr2", f"2026-01-01-{c2}"); os.makedirs(r7)
        open(os.path.join(r7, "TARGET.json"), "w").write("{not json")
        open(os.path.join(r7, "ADOPTED.md"), "w").write("x")
        cu = changes_after_last_audit(cfg, [r7]) or {}
        checks.append(("changes after the last audit: an adjudicated round whose TARGET.json is unreadable is a "
                       "problem, not a missing trust row", "no proof round has a readable TARGET.json"
                       in str(cu.get("problem"))))
        g("checkout", "-q", c1)
        cb = changes_after_last_audit(cfg, [r1, r2]) or {}
        checks.append(("changes after the last audit: HEAD behind the audited commit is a problem",
                       "does not descend" in str(cb.get("problem"))))
    finally:
        REPO = saved
        shutil.rmtree(gr, ignore_errors=True)
    return checks


UNCODED_PRINT = re.compile(r"""print\(f?["'](?:PROBLEM|MISMATCH|MISSING|GITMETA|DRIFT|HARD)\s""")
SWEPT = ("make_report.py", "readers.py", "decisions.py", "signoff.py", "scope.py", "prompt.py", "dependencies.py",
         "hypotheses.py", "lanecheck.py", "integrity.py", "tree_state.py", "fingerprint.py", "phase0.py", "audit_coverage.py")


def _l1_sweep():
    """Where an uncoded failure line is printed by --deliver or the commit tools, or Phase 0's freeze step
    has no code (sweep L1: each would be "unknown", a human stop)."""
    import inspect, phase0
    out = [f"deliver: {l.strip()[:60]}" for l in inspect.getsource(deliver).splitlines()
           if re.search(r"""print\(f?["'](?:FAIL|RED|MISSING):""", l)]
    src = open(os.path.join(AUDITS, "integrity.py"), encoding="utf-8").read()
    i, j = src.find("    if a.commit_adjudication:"), src.find("    if a.check:")
    out += [f"integrity: {l.strip()[:60]}" for l in src[i:j].splitlines() if re.search(r"""["']FAIL:""", l)]
    if phase0.code_of("freeze check (approved statements unchanged)") != "drift":
        out.append("phase0: the freeze check step has no code")
    return out if i >= 0 and j > i else out + ["integrity: the commit block moved"]


def _uncoded_sweep():
    """[file:line] of every print of a failure line with no KIND[code] in the check scripts (stops.causes
    files such a line as "unknown", which only the human clears: the release trial's S1)."""
    out = []
    for f in SWEPT:
        for n, l in enumerate(open(os.path.join(AUDITS, f), encoding="utf-8"), 1):
            if UNCODED_PRINT.search(l):
                out.append(f"{f}:{n}")
    return out


def selftest():
    """The config checks, as negative controls (prompt.py's self-test runs them too)."""
    global REPO
    fake = {"name": "negctl"}
    checks = [
        ("a config missing fields is a hard error", any(p.startswith("! missing") for p in problems(fake))),
        ("A10f: select refuses a config with a hard error", _refuses_hard(fake)),
        ("S1: a blocking finding prints with its own code, a plain string with the check's",
         problem_line(Finding("! x  y", "pdf"), "report", "FAIL") == "FAIL[pdf] x y"
         and problem_line("z", "decisions") == "PROBLEM[decisions] z"),
        ("S1: the record-fix codes are agent-curable (no STOP class) and block in release (F); a bad record-fix "
         "commit is tamper", all(cause_class(c) == "record-fix" and not is_stop_cause(c) and release_class(c) == "F"
                                 for c in ("dead-witness", "record-cite"))
         and is_stop_cause("record-fix-diff") and release_class("record-fix-diff") == "I"),
        ("S2: a HEAD move by the operator's empty commits is curable by the operator; any other is a stop (I)",
         not is_stop_cause("head-moved-operator") and is_stop_cause("head-moved")
         and release_class("head-moved") == release_class("head-moved-operator") == "I"),
        ("S1: the check scripts print no failure line without a cause code (a quick source sweep)", _uncoded_sweep() == []),
        ("L2: every script under audits/ ends in run_main (a crash prints FAIL[uncoded], never a bare traceback)",
         _run_main_sweep() == []),
        ("L2: run_main turns a crash into FAIL[uncoded] <script> (exit 1, traceback kept on stderr), the unknown-retry "
         "route: release (I, rerun), its stop's own --check closes it, keyed with the retry codes", _run_main_controls()),
        ("sweep L1: --deliver, the adjudication and record-correction commit tools and Phase 0's freeze step print "
         "coded failure lines", _l1_sweep() == []),
        ("A10a: a sourceless .pyc and an unchecked-hash .pyc are dangerous; a cached one is not", _pyc_kinds()),
        ("A10a: --env-check removes cached bytecode and leaves an unchecked-hash .pyc for integrity", _env_clean()),
        ("an unknown config key is reported (a soft note); a known one is not",
         any("unknown config key 'index_strct'" in p for p in problems(dict(fake, index_strct=True)))
         and not any("unknown config key" in p for p in problems(dict(fake, index_strict=True)))),
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
        ("the test tier's involvement override applies only to a --selftest process",
         _test_level(fake, ["x.py", "--selftest"], {TEST_LEVEL_ENV: "hands-off"}).get("involvement") == "hands-off"
         and "involvement" not in _test_level(fake, ["x.py", "--check"], {TEST_LEVEL_ENV: "hands-off"})
         and "involvement" not in _test_level(fake, ["x.py", "--selftest"], {})),
        ("the test tier's mode override applies only to a --selftest process (A3)",
         all(_test_level(fake, ["x.py", "--selftest"], {TEST_MODE_ENV: m_}).get("mode") == m_ for m_ in MODES)
         and all(k not in _test_level(fake, argv_, {TEST_MODE_ENV: "release"}) for k in ("mode", "_test_mode")
                 for argv_ in (["x.py", "--check"], ["x.py", "--selftest-x"]))
         and all("mode" not in _test_level(fake, argv_, {TEST_MODE_ENV: "release", TEST_LEVEL_ENV: "hands-off"})
                 for argv_ in (["x.py", "--check"], ["x.py"], ["x.py", "--deliver"], ["x.py", "--selftests"]))
         and "mode" not in _test_level(fake, ["x.py", "--selftest"], {TEST_LEVEL_ENV: "hands-off"})
         and _test_mode(["x.py", "--check"], {TEST_MODE_ENV: "release"}) is None),
        ("attack review E H1: a real command carrying --selftest is not a selftest -- `--deliver --selftest` keeps its "
         "config and the first pin's terms; `--project P --selftest` and `--selftest --lean` are selftests",
         not _in_selftest(["project.py", "--deliver", "--selftest"])
         and not _in_selftest(["project.py", "--deliver", "--project", "P", "--selftest"])
         and _test_level(fake, ["project.py", "--deliver", "--selftest"],
                         {TEST_LEVEL_ENV: "hands-off", TEST_MODE_ENV: "release"}) == fake
         and _in_selftest(["make_report.py", "--project", "P", "--selftest"])
         and _in_selftest(["project.py", "--selftest", "--lean"]) and _in_selftest(["-c", "--selftest"])),
        ("a real run with FORMALIZE_TEST_MODE set keeps its config's mode (A3)", _test_mode_real_run()),
        ("clip cuts at a word boundary and marks the cut; a short text is unchanged",
         clip("not confidential, light budget", 18) == "not confidential …" and clip("a  b", 9) == "a b"),
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
        for f_ in ("REPORT.pdf", "SUMMARY.pdf", "REPORT.md", "SUMMARY.md", "DECISIONS.md",
                   "KNOWN_FAULTS-report-2026-01-01-abc1234.md",
                   "KNOWN_FAULTS-report-2025-12-31-full-0ld0ld0.md", "KNOWN_FAULTS-signoff-2025-12-30-0ld0ld1.md",
                   "KNOWN_FAULTS-signoff-2026-01-01-abc1234.md"):
            open(os.path.join(REPO, "audits", "x", f_), "w").write(
                f"NOTICE-{f_[len('KNOWN_FAULTS-'):-3]}-QZ\n" if f_.startswith("KNOWN_FAULTS") else "x")
        open(os.path.join(rdd, "SIGNOFF.pdf"), "w").write("x")
        open(os.path.join(rdd, "SIGNOFF.md"), "w").write("x")
        open(os.path.join(rdd, "TARGET.json"), "w").write("{}")
        # PDF-AGENTS: the render records --deliver reads (render_record.delivered): SUMMARY and REPORT shipped a PDF,
        # the sheet none (no-pdf: its md alone)
        for k_, oc_ in (("SUMMARY", "verified"), ("REPORT", "least-bad"), ("SIGNOFF-2026-01-01-abc1234", "no-pdf")):
            os.makedirs(os.path.join(REPO, "audits", "x", "pdf", k_))
            json.dump({"outcome": oc_, "shipped_pdf_sha256": None if oc_ == "no-pdf" else hashlib.sha256(b"x").hexdigest()},
                      open(os.path.join(REPO, "audits", "x", "pdf", k_, "RENDER.json"), "w"))
        json.dump({"round": "2026-01-01-abc1234"}, open(os.path.join(REPO, "audits", "x", "APPROVED_FINGERPRINTS.json"), "w"))
        open(os.path.join(REPO, "audits", "x", README_AC), "w").write("# What is delivered\n\nREADME-AC-QZ\n")
        open(os.path.join(REPO, "audits", "x", RUN_RECORD), "w").write(
            "# Run record\n\nRUNREC-QZ\n\n## 1. Tool patches\n\nNone.\n\n## 3. Stops cleared without you\n\nNone.\n\n"
            "## 4. Set-asides and clearances\n\nNone.\n")
        import decisions as _dc
        import stops as _st
        # approver (2026-10-28): the math gate is stops.math_gate (stops.py's selftest holds its content); here a
        # stand-in, so these configs never run real checks
        _gate0, _st.math_gate = _st.math_gate, lambda c_: ([], [])
        # B12: this fixture (involved by default) has Checkpoint C answered; C itself is decisions' selftest
        _ckc_d, _dc.checkpoint_c_refusal = _dc.checkpoint_c_refusal, (lambda c_: None)
        import make_report as _mrp
        # make_report.py --check --delivery is a stand-in here (its own selftest and _delivery_scenario hold it)
        _dpr0 = _mrp.delivery_problems
        _mrp.delivery_problems = lambda c_, inp=None: [("deliver-stale", "1 Lean commit(s) after the last audited round "
                                                                         "R (abc1234): STALEQZ"),
                                                        ("deliver", "SUMMARY.md is stale: its inputs changed since prepare")]
        with contextlib.redirect_stdout(io.StringIO()) as _o:
            rc_af = deliver({"rounds_dir": "audits/x"})
        _mrp.delivery_problems = lambda c_, inp=None: []
        _st.math_gate = lambda c_: (["`python3 audits/phase0.py --readonly` fails (exit 1): HARD[sorry] SORRYQZ"],
                                    ["integrity (not the proof-validity core): FAIL[ownership] readers/x.md NOTEQZ"])
        with contextlib.redirect_stdout(io.StringIO()) as _og:
            rc_mg = deliver({"rounds_dir": "audits/x"})
        _st.math_gate = lambda c_: ([], [])
        _rq0, _dc.reapproval_question = _dc.reapproval_question, (lambda c_: {"decls": ["N.x"], "date": "2026-01-01",
                                                                             "reason": "r", "why": "w"})
        try:
            with contextlib.redirect_stdout(io.StringIO()) as _oq:
                rc_q = deliver({"rounds_dir": "audits/x"})
        finally:
            _dc.reapproval_question = _rq0
        checks.append(("approver 2026-10-28, the math gate: --deliver refuses only on it -- a Lean commit after the last "
                       "audited round (RED[deliver-stale]), a failing Phase 0 / freeze / core-integrity check (RED[deliver]), "
                       "an open re-approval (PENDING[question], never a failure line) -- printing the rest as notes, and copies nothing",
                       rc_af == 1 and "RED[deliver-stale] not deliverable (the math gate): 1 Lean commit(s)" in _o.getvalue()
                       and "STALEQZ" in _o.getvalue() and NOTES_HEADING in _o.getvalue()
                       and "note: [deliver] SUMMARY.md is stale" in _o.getvalue()
                       and rc_mg == 1 and "RED[deliver] not deliverable (the math gate)" in _og.getvalue()
                       and "SORRYQZ" in _og.getvalue() and "note: integrity (not the proof-validity core)" in _og.getvalue()
                       and rc_q == 1 and _oq.getvalue().startswith("PENDING[question] not delivered (the freeze")
                       and "N.x" in _oq.getvalue() and not _st.FAIL_LINE.search(_oq.getvalue())
                       and not os.path.exists(os.path.join(REPO, "deliverables"))))
        # PDF-AGENTS / B10 / B12 / sweep D1-D3, now notes (approver 2026-10-28): an open stop, an unanswered
        # Checkpoint C, a PDF not the one shipped for its md, a pending adjudication, a stale document, `unverified`
        _rck0 = globals()["RENDER_CHECK"]
        import project as _pmd      # render_record reads the imported module's REPO (this one is __main__)
        _pmd_repo, _pmd.REPO = _pmd.REPO, REPO
        _dc.checkpoint_c_refusal = lambda c_: "item CKCQZ awaits the human"
        _keep_on = _st.open_name
        # the designed human waits stay (review 2026-10-28): Checkpoint C, a human stop (any open stop in dev)
        with contextlib.redirect_stdout(io.StringIO()) as _ow1:
            rc_w1 = deliver({"rounds_dir": "audits/x", "mode": "dev"})
        _dc.checkpoint_c_refusal = lambda c_: None
        _st.open_name = lambda c_: "S7"
        with contextlib.redirect_stdout(io.StringIO()) as _ow2:
            rc_w2 = deliver({"rounds_dir": "audits/x", "mode": "dev"})
        _s8 = os.path.join(REPO, "audits", "x", "stops", "S8")
        os.makedirs(_s8, exist_ok=True)
        json.dump({"stop": "S8", "causes": [{"code": "ambiguity"}]}, open(os.path.join(_s8, "STOP.json"), "w"))
        _st.open_name = lambda c_: "S8"
        with contextlib.redirect_stdout(io.StringIO()) as _ow3:
            rc_w3 = deliver({"rounds_dir": "audits/x", "mode": "release"})
        json.dump({"stop": "S8", "causes": [{"code": "tool-bug"}]}, open(os.path.join(_s8, "STOP.json"), "w"))
        checks.append(("review 2026-10-28: the designed human waits refuse --deliver (PENDING, never a failure line, so "
                       "never a stop): Checkpoint C under involved, any open stop in dev, a release human stop "
                       "(ambiguity); nothing is copied",
                       rc_w1 == 1 and _ow1.getvalue().startswith("PENDING[question]") and "CKCQZ" in _ow1.getvalue()
                       and rc_w2 == 1 and _ow2.getvalue().startswith("PENDING[stop]") and "S7" in _ow2.getvalue()
                       and rc_w3 == 1 and _ow3.getvalue().startswith("PENDING[stop]")
                       and not _st.FAIL_LINE.search(_ow1.getvalue() + _ow2.getvalue() + _ow3.getvalue())
                       and not os.path.exists(os.path.join(REPO, "deliverables"))))
        globals()["RENDER_CHECK"] = lambda c_, d_, r_: [f"{d_}.md changed since its PDF was rendered: render it again"]
        _mrp.delivery_problems = lambda c_, inp=None: [
            ("adj-record", "pending the next adjudication: SKIPPED.md row 3: 4 cells under a 5-column header"),
            ("deliver", "SUMMARY.md is stale: its inputs changed since prepare"),
            ("unverified", "no full-scope round since the approval"), ("ownership", "DEVIATIONS.md OWNQZ"),
            ("status-unmapped", "Lemma 1: not established UNMAPQZ")]
        os.makedirs(os.path.join(REPO, "deliverables"), exist_ok=True)
        open(os.path.join(REPO, "deliverables", "SIGNOFF.pdf"), "w").write("an earlier delivery's sheet")
        try:
            with contextlib.redirect_stdout(io.StringIO()) as _on:
                rc_d = deliver({"rounds_dir": "audits/x", "mode": "release"})
        finally:
            shutil.rmtree(os.path.join(REPO, "audits", "x", "stops"), ignore_errors=True)
            _st.open_name = _keep_on
            _dc.checkpoint_c_refusal = lambda c_: None
            globals()["RENDER_CHECK"] = lambda c_, d_, r_: []
            _mrp.delivery_problems = lambda c_, inp=None: []
        _on = _on.getvalue()
        checks.append(("approver 2026-10-28: an open release stop that is no human stop (tool-bug), a PDF not the one "
                       "shipped for its markdown, a pending adjudication, a stale document, unverified, an ownership fault and an "
                       "unmapped status are notes for the main agent after the delivery, never a refusal, never a "
                       "failure line (so never a stop)",
                       rc_d == 0 and _on.index("delivered ") < _on.index(NOTES_HEADING)
                       and all(x in _on for x in ("stop S8 is open (not a human stop)", "[pdf] SUMMARY.md changed",
                                                  "[pdf] SIGNOFF.md changed", "[adj-record] pending",
                                                  "[deliver] SUMMARY.md is stale", "[unverified]", "OWNQZ", "UNMAPQZ"))
                       and not _st.FAIL_LINE.search(_on) and not re.search(r"^\s*(?:RED|PENDING)\[", _on, re.M)
                       and "delivered as markdown only until rendered again" in _on
                       and not any(f_.endswith(".pdf") for f_ in os.listdir(os.path.join(REPO, "deliverables")))))
        os.makedirs(os.path.join(REPO, "deliverables"), exist_ok=True)
        open(os.path.join(REPO, "deliverables", "SIGNOFF.pdf"), "w").write("an earlier delivery's sheet")
        with contextlib.redirect_stdout(io.StringIO()):
            rc_d = deliver({"rounds_dir": "audits/x"})
        got = sorted(os.listdir(os.path.join(REPO, "deliverables")))
        _cover = open(os.path.join(REPO, "deliverables", "README.md")).read() if "README.md" in got else ""
        excl2 = open(os.path.join(REPO, ".git", "info", "exclude")).read().splitlines()
        _lc = {"name": "lt", "rounds_dir": "audits/lt"}
        os.makedirs(os.path.join(REPO, "audits", "lt"), exist_ok=True)
        open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md"), "w").write(
            "# Run log\n## Mechanical failures\n- old\n## Current stage\nStage 2\n")
        log_append(_lc, "Mechanical failures", "- new one")
        log_append(_lc, "Stops resolved", "- S1 line")
        log_append(_lc, "Current stage", "Stage 4", replace=True)
        _lt = open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md")).read()
        checks.append(("--log appends under its section, a new section goes before Current stage, --stage replaces",
                       _lt == "# Run log\n## Mechanical failures\n- old\n- new one\n\n## Stops resolved\n- S1 line\n\n"
                              "## Current stage\nStage 4\n"))
        try:
            log_append(_lc, "X", "  \n"); _empty = False
        except ValueError:
            _empty = True
        checks.append(("--log refuses an empty entry", _empty))
        log_append(_lc, "Stops", "- only stops")
        _lt2 = open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md")).read()
        checks.append(("--log matches a section by its exact name ('Stops' is not 'Stops resolved')",
                       "## Stops\n- only stops\n" in _lt2 and "## Stops resolved\n- S1 line\n\n## Stops" in _lt2))
        try:
            log_append(_lc, "X", "- a\n## Injected\n- b"); _inj = False
        except ValueError:
            _inj = True
        checks.append(("--log refuses an entry with a heading line in it", _inj))
        open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md"), "a").write("\nkept note written by hand\n")
        log_append(_lc, "Current stage", "Stage 5", replace=True)
        _lt3 = open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md")).read()
        checks.append(("--stage replaces the stage paragraph only, keeping lines written below it",
                       "## Current stage\nStage 5\n" in _lt3 and "kept note written by hand" in _lt3 and "Stage 4" not in _lt3))
        open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md"), "w").write("# Run log\n## Current stage\nStage 5\n- a line right under the stage, KEPTQZ\n")
        log_append(_lc, "Current stage", "Stage 6", replace=True)
        _lt4 = open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md")).read()
        checks.append(("review 2 N11: --stage keeps a line written directly under the stage line",
                       "KEPTQZ" in _lt4 and "## Current stage\nStage 6\n" in _lt4 and "Stage 5" not in _lt4))
        global select
        _sel, _stdin = select, sys.stdin
        try:
            select = lambda name=None: (_lc, "test")
            sys.stdin = io.StringIO("- via the CLI, STDINQZ\n")
            with contextlib.redirect_stdout(io.StringIO()):
                _rc = main(["--log", "Mechanical failures"])
        finally:
            select, sys.stdin = _sel, _stdin
        try:
            select = lambda name=None: (_lc, "test")
            _o = io.StringIO()
            with contextlib.redirect_stdout(_o):
                _rs = main(["--stage"])
            _o2 = io.StringIO()
            with contextlib.redirect_stdout(_o2):
                _rs2 = main(["--stage", "Stage 3 — proofs"])
            _o3 = io.StringIO()
            with contextlib.redirect_stdout(_o3):
                main(["--stage"])
        finally:
            select = _sel
        checks.append(("--stage prints the current stage and the stage file to read; --stage TEXT names the new one (B1)",
                       _rs == 0 and "current stage: Stage 6" in _o.getvalue() and "audits/run/stage" not in _o.getvalue()
                       and _rs2 == 0 and "read now: audits/run/stage3-proofs.md" in _o2.getvalue()
                       and "read now: audits/run/stage3-proofs.md" in _o3.getvalue()))
        # B13 (U2 §8, restarts): Stage 0 saves the intake before the branch and the log exist; a conversation
        # that ends before Stage 1 step 5 resumes from it, never asking the intake again
        _h13 = intake_hash()
        _ok13 = [intake_save(f"intake-message sha256 {_h13}\n- 1a: paper.tex\n").startswith("saved")]
        for _bad in (f"intake-message sha256 {_h13}\n- 1a: other.tex\n", "- 1a: paper.tex\n"):
            try:
                intake_save(_bad); _ok13.append(False)
            except ValueError:
                _ok13.append(True)
        _ok13.append("unchanged" in intake_save(f"intake-message sha256 {_h13}\n- 1a: paper.tex\n"))
        # A4 (STATUS A4): the rounds directory is NOT created first; --intake-move (log_append) creates it
        _lc13 = dict(_lc, name="lt13", rounds_dir="audits/lt13")
        _no13 = not os.path.exists(os.path.join(REPO, "audits", "lt13"))

        def _stage13(sel):
            global select
            _keep13 = select
            select = sel
            try:
                _o13 = io.StringIO()
                with contextlib.redirect_stdout(_o13):
                    main(["--stage"])
                return _o13.getvalue()
            finally:
                select = _keep13

        def _nosel(name=None):
            raise SelectionError("no config")
        _s1 = _stage13(_nosel)
        intake_save(f"intake-message sha256 {_h13}\n- 1a: paper.tex\n- Checkpoint A: OK (2026-10-23)\n")
        _s2 = _stage13(lambda name=None: (_lc13, "test"))
        try:
            _m13 = intake_move(_lc13)
            _log13 = open(os.path.join(REPO, "audits", "lt13", "RUN_LOG.md")).read()
        except OSError as e:        # A4: the missing rounds directory (FileNotFoundError before the fix)
            _m13, _log13 = f"intake_move failed: {e}", ""
        _s3 = _stage13(_nosel)
        checks.append(("B13 restart: the intake is saved before the branch (Stage 0); --stage then says resume (no new "
                       "intake; Checkpoint A again until its OK is saved; git switch to an existing branch); a different "
                       "intake or one without its hash is refused; --intake-move puts it under ## Intake and removes the "
                       "draft, after which --stage says a new run",
                       all(_ok13) and "Do NOT send the intake again" in _s1 and "Show Checkpoint A again" in _s1
                       and "stage0-intake.md" in _s1 and "Checkpoint A was OKed" in _s2 and "stage1-setup.md" in _s2
                       and "git switch <branch>" in _s2 and "removed" in _m13
                       and re.search(r"^## Intake \(\d{4}-\d{2}-\d{2}\)\n", _log13, re.M) and "- 1a: paper.tex" in _log13
                       and intake_logged(os.path.join(REPO, "audits", "lt13")) is None
                       and not os.path.exists(intake_draft_path()) and "a new run" in _s3))
        try:
            log_append(dict(_lc, rounds_dir="../lt13x"), "Notes", "x"); _out13 = False
        except ValueError as e:
            _out13 = "not under audits/" in str(e) and not os.path.exists(os.path.join(REPO, "..", "lt13x"))
        try:        # compat review L5: a misspelt rounds_dir under audits/ is not created either
            log_append(dict(_lc, name="lt13y", rounds_dir="audits/lt13z"), "Notes", "x"); _out13 = False
        except ValueError as e:
            _out13 = _out13 and "not audits/lt13y" in str(e) and not os.path.exists(os.path.join(REPO, "audits", "lt13z"))
        checks.append(("A4: --intake-move (log_append) creates a missing rounds directory audits/<name>; a missing one "
                       "outside audits/, or a misspelt one under it (compat L5), is refused and nothing is created",
                       _no13 and os.path.isfile(os.path.join(REPO, "audits", "lt13", "RUN_LOG.md")) and _out13))
        checks.append(("B3: a sorry is the author's work (proof-wip), an axiom or kernel-skipping token is a stop",
                       cause_class("sorry") == "proof-wip" and not is_stop_cause("sorry")
                       and is_stop_cause("axiom") and is_stop_cause("hard-token") and is_stop_cause("no-such-code")))
        checks.append(("stage_file maps each Stage n to its file, and every stage and procedure file exists",
                       stage_file("Stage 4 — audit rounds (round 2)") == "run/stage4-rounds.md"
                       and stage_file("Stage 0") == "run/stage0-intake.md" and stage_file("Stage 6") is None
                       and stage_file("Stages 2") is None
                       and all(os.path.isfile(os.path.join(AUDITS, f))
                               for f in list(STAGE_FILES.values()) + PROCEDURE_FILES)))
        _im = intake_message() or ""
        _labels = ["1a", "1b", "1c", "2a", "2b", "2c", "3a", "3b", "4", "5a", "5b", "5c", "5d",
                   "6a", "6b", "6c", "6d", "6e", "7"]
        _found = re.findall(r"^(\d[a-e]?)\. ", _im, re.M)
        _ild = tempfile.mkdtemp(prefix="il-", dir=os.path.join(REPO, "audits"))
        try:
            _h = intake_hash()
            _miss = intake_logged(_ild)
            open(os.path.join(_ild, "RUN_LOG.md"), "w").write(f"# Run log\n## Intake\n- 1a x\n## Rounds\nintake-message sha256 {_h}\n")
            _wrong = intake_logged(_ild)
            open(os.path.join(_ild, "RUN_LOG.md"), "w").write(f"# Run log\n## Intake (2026-01-01)\nintake-message sha256 {_h}\n## Rounds\n")
            _ok = intake_logged(_ild)
        finally:
            shutil.rmtree(_ild, ignore_errors=True)
        checks.append(("B6: the intake message carries every label, in order, the involvement question and no "
                       "operator-only text; its hash must be logged under ## Intake",
                       _found == _labels
                       and "How involved do you want to be after the intake and Checkpoint A" in _im
                       and "`" not in _im and "This fills" not in _im and "<<" not in _im
                       and len(_h or "") == 16 and _miss and _wrong and _ok is None))
        checks.append(("the --log CLI appends what it reads on stdin (X9)",
                       _rc == 0 and "- via the CLI, STDINQZ" in open(os.path.join(REPO, "audits", "lt", "RUN_LOG.md")).read()))
        for _r in ("2026-01-01-aaaaaaa", "2026-01-02-full-bbbbbbb"):
            os.makedirs(os.path.join(REPO, "audits", "lt", _r))
            open(os.path.join(REPO, "audits", "lt", _r, "TARGET.json"), "w").write("{}")
        open(os.path.join(REPO, "audits", "lt", "2026-01-02-full-bbbbbbb", ABANDONED), "w").write("{}")
        checks.append(("an abandoned round is not a round (unless asked for)",
                       [os.path.basename(x) for x in rounds(_lc)] == ["2026-01-01-aaaaaaa"]
                       and len(rounds(_lc, include_abandoned=True)) == 2))
        checks.append(("--deliver copies the summary, report, decisions, notices and the approved sheet into "
                       "deliverables/ (excluded); each PDF render_record shipped with its markdown beside it, always "
                       "(review 12); a document rendered to no PDF ships its markdown alone, and an earlier delivery's "
                       "PDF of it is removed",
                       rc_d == 0 and "DECISIONS.md" in got and "REPORT.pdf" in got and "REPORT.md" in got
                       and "SUMMARY.pdf" in got and "SUMMARY.md" in got and "SIGNOFF.md" in got
                       and "SIGNOFF.pdf" not in got and "deliverables/" in excl2))
        _dv = os.path.join(REPO, "deliverables")
        _cd0 = check_delivered({"rounds_dir": "audits/x"})
        open(os.path.join(_dv, "SUMMARY.pdf"), "a").write("swapped after --deliver")
        _cd1 = check_delivered({"rounds_dir": "audits/x"})
        open(os.path.join(_dv, "SUMMARY.pdf"), "w").write("x")
        open(os.path.join(_dv, "SIGNOFF.pdf"), "w").write("x")
        _cd2 = check_delivered({"rounds_dir": "audits/x"})
        os.remove(os.path.join(_dv, "SIGNOFF.pdf"))
        _rdj = os.path.join(REPO, "audits", "x", "pdf", "REPORT", "RENDER.json")
        _rdk = open(_rdj).read()
        json.dump({"outcome": "least-bad", "shipped_pdf_sha256": "0" * 64}, open(_rdj, "w"))
        _cd3 = check_delivered({"rounds_dir": "audits/x"})
        open(_rdj, "w").write(_rdk)
        checks.append(("review MED 3: README D fingerprints each delivered PDF (sha256); --check-delivered passes on the "
                       "delivery and catches a PDF swapped after it, a PDF added that was not delivered, and a "
                       "fingerprint that is not the render record's",
                       "- `SUMMARY.pdf`: sha256 `" + hashlib.sha256(b"x").hexdigest() + "`" in _cover
                       and "- `REPORT.pdf`: sha256 `" in _cover and "`SIGNOFF.pdf`: sha256" not in _cover
                       and _cd0 == [] and any("SUMMARY.pdf is not the PDF delivered" in x for x in _cd1)
                       and any("SIGNOFF.pdf has no fingerprint" in x for x in _cd2)
                       and any("fingerprint of REPORT.pdf" in x for x in _cd3)
                       and check_delivered({"rounds_dir": "audits/x"}) == []))
        _dmd = os.path.join(REPO, "audits", "x", "DECISIONS.md")
        _dkp = open(_dmd).read()
        os.remove(_dmd)
        with contextlib.redirect_stdout(io.StringIO()) as _om:
            _rc_m = deliver({"rounds_dir": "audits/x"})
        open(_dmd, "w").write(_dkp)
        checks.append(("approver 2026-10-28: a deliverable that is missing (here DECISIONS.md) is a note, named; the rest "
                       "is delivered",
                       _rc_m == 0 and "note: 1 deliverable(s) missing, not delivered: audits/x/DECISIONS.md" in _om.getvalue()
                       and "RED[" not in _om.getvalue()))
        _rrd = open(os.path.join(REPO, "deliverables", RUN_RECORD)).read() if RUN_RECORD in got else ""
        _rrp = os.path.join(REPO, "deliverables", RUN_RECORD)
        _rr_keep = open(_rrp).read() if os.path.exists(_rrp) else ""
        _cd0 = check_delivered({"rounds_dir": "audits/x"})
        open(_rrp, "a").write("edited after delivery\n")
        _cd1 = check_delivered({"rounds_dir": "audits/x"})
        open(_rrp, "w").write(_rr_keep)
        checks.append(("approver 2026-10-24: --check-delivered passes on the delivered RUN_RECORD.md and catches one "
                       "changed after delivery (README D's sha256)",
                       _rr_keep != "" and _cd0 == [] and any("is not the run record delivered" in p_ for p_ in _cd1)))
        # approver 2026-10-24: a stop the operator closed that RUN_RECORD.md does not list (integrity.run_record_problems,
        # from the raw CLOSED.json) -- approver 2026-10-28: a note for the main agent, who corrects RUN_RECORD.md
        _s9 = os.path.join(REPO, "audits", "x", "stops", "S9")
        os.makedirs(_s9, exist_ok=True)
        json.dump({"by": "cure"}, open(os.path.join(_s9, "CLOSED.json"), "w"))
        with contextlib.redirect_stdout(io.StringIO()) as _o9:
            _rc_9 = deliver({"rounds_dir": "audits/x"})
        shutil.rmtree(os.path.join(REPO, "audits", "x", "stops"))
        checks.append(("approver 2026-10-24/28: a RUN_RECORD.md that omits a stop the operator closed is named in a note "
                       "(from the raw stop record); the delivery proceeds",
                       _rc_9 == 0 and "note: [run record] RUN_RECORD.md does not list stop S9" in _o9.getvalue()
                       and os.path.exists(os.path.join(REPO, "deliverables", RUN_RECORD))))
        checks.append(("mini2-3 / approver 2026-10-24: --deliver ships no KNOWN_FAULTS file; the delivered RUN_RECORD.md "
                       "is the prepared one, then the notices of the delivered documents folded in (the newest report's; "
                       "the approved sheet's is the prepared part's), never a superseded report's or sheet's text",
                       not [g_ for g_ in got if g_.startswith("KNOWN_FAULTS")]
                       and _rrd.startswith("# Run record\n\nRUNREC-QZ\n")
                       and "NOTICE-report-2026-01-01-abc1234-QZ" in _rrd
                       and "NOTICE-report-2025-12-31-full-0ld0ld0-QZ" not in _rrd
                       and "NOTICE-signoff-2025-12-30-0ld0ld1-QZ" not in _rrd))
        checks.append(("ADDENDUM N6: README.md is README A-C exactly as prepared, then section D (written only into the "
                       "delivery copy), which points to RUN_RECORD.md and fingerprints it; RUN_RECORD.md names the "
                       "superseded notices left out (no superseded/ directory)",
                       _cover.startswith("# What is delivered\n\nREADME-AC-QZ\n") and "## D. Delivery notes" in _cover
                       and _cover.index("README-AC-QZ") < _cover.index("## D.") and "`RUN_RECORD.md`" in _cover
                       and "- `RUN_RECORD.md`: sha256 `" in _cover
                       and "KNOWN_FAULTS-report-2025-12-31-full-0ld0ld0.md" in _rrd
                       and not os.path.exists(os.path.join(REPO, "deliverables", "superseded"))))
        _rmd = os.path.join(REPO, "audits", "x", "REPORT.md")
        _ro0 = globals()["READER_OUTCOME"]
        globals()["READER_OUTCOME"] = lambda c_, d_, r_: ("NOT passed: it ended with 2 blocking finding(s) answered "
                                                          "unfixable (2 at the fix budget)" if d_ == "report" else
                                                          "passed (every blocking finding was fixed and re-read)")
        import project as _pm5
        _pm5_repo, _pm5.REPO = _pm5.REPO, REPO
        try:
            _cv5 = readme_d({"rounds_dir": "audits/x", "involvement": "hands-off"},
                            [os.path.join(REPO, "audits", "x", "REPORT.pdf"),
                             os.path.join(REPO, "audits", "x", "DECISIONS.md"),
                             os.path.join(REPO, "audits", "x", "2026-01-01-abc1234", "SIGNOFF.pdf")], [], [])
            _cv8 = readme_d({"rounds_dir": "audits/x", "involvement": "involved"},
                            [os.path.join(REPO, "audits", "x", "2026-01-01-abc1234", "SIGNOFF.pdf")], [], [])
            json.dump({"doc": "REPORT", "outcome": "least-bad", "shipped_round": 2, "budget": 6, "rounds": [
                           {"k": 1, "checkers": {
                               "1": {"status": "saved", "verdict": "DIFFERENT", "blocking": 1, "findings": ["p.3: CHKQZ"]},
                               "2": {"status": "failed", "why": "crashed"}}}, {"k": 2}],
                       "remaining_objections": ["[content] p.2: x2 | md: x^2"], "shipped_cover": 1,
                       "shipped_pdf_sha256": hashlib.sha256(b"x").hexdigest(),
                       "covers": [{"t": 1, "round": 2, "a": {"status": "saved"}, "check": {"status": "saved",
                                                                                         "verdict": "PASS"}}]},
                      open(os.path.join(REPO, "audits", "x", "pdf", "REPORT", "RENDER.json"), "w"))
            _cv6 = readme_d({"rounds_dir": "audits/x", "involvement": "hands-off"}, [], [], [])
            # conf1 (C1 audit): with the real gate's words, README D never says a KNOWN_FAULTS file is delivered
            import readers as _rd7
            globals()["READER_OUTCOME"] = lambda c_, d_, r_: _rd7.outcome_text(f"{d_}-r", 2, 2)[1]
            _cv7 = readme_d({"rounds_dir": "audits/x", "involvement": "hands-off"},
                            [os.path.join(REPO, "audits", "x", "REPORT.pdf"),
                             os.path.join(REPO, "audits", "x", "DECISIONS.md")], [], [])
            open(os.path.join(REPO, "audits", "x", JUDGEMENT_MD), "w").write("claims-1 · adopted.\n")
            os.makedirs(os.path.join(REPO, "audits", "x", REVIEW_DIR), exist_ok=True)
            for p_ in ("CLAIMS", "TRUST"):
                open(os.path.join(REPO, "audits", "x", REVIEW_DIR, p_ + ".md"), "w").write("1. minor: x\n")
            _cv9 = readme_d({"rounds_dir": "audits/x", "involvement": "hands-off"}, [], [], [])
            os.makedirs(os.path.join(REPO, "audits", "x", FACTS_DIR), exist_ok=True)
            shutil.copy(os.path.join(REPO, "audits", "x", "SUMMARY.md"), os.path.join(REPO, "audits", "x", FACTS_DIR))
            _cv10 = readme_d({"rounds_dir": "audits/x", "involvement": "hands-off"}, [], [], [])
            _dc10 = draft_copies({"rounds_dir": "audits/x"})
            shutil.rmtree(os.path.join(REPO, "audits", "x", FACTS_DIR))
            shutil.rmtree(os.path.join(REPO, "audits", "x", REVIEW_DIR))
            os.remove(os.path.join(REPO, "audits", "x", JUDGEMENT_MD))
        finally:
            globals()["READER_OUTCOME"] = _ro0
            _pm5.REPO = _pm5_repo
        checks.append(("approver 2026-10-28: README D says SUMMARY and REPORT were written by the agent and reviewed by "
                       "four fresh agents, names JUDGEMENT.md only when it exists, claims no reader for them, and keeps "
                       "the sheet's reader outcome (none claimed under hands-off)",
                       "written by the formalizing agent" in _cv5 and "No delivery review is on record" in _cv5
                       and "`JUDGEMENT.md`" in _cv9 and "Fresh agents reviewed them" not in _cv9
                       and "Reviews by fresh agents are on record in the audit record's `delivery-review/` (claims, trust)"
                       " ; the formalizing agent saved them, so the record cannot show who wrote them".replace(" ;", ";") in _cv9
                       and "no review is on record for readability, decisions" in _cv9
                       and _dc10 == ["SUMMARY.md"] and "SUMMARY.md is the generator's draft, unchanged" in _cv10
                       and "written by the formalizing agent" not in _cv10 and "passed (every blocking finding" not in _cv5
                       and "`SIGNOFF.pdf`: passed" not in _cv5 and "- `SIGNOFF.pdf`: passed (every blocking finding" in _cv8))
        checks.append(("conf1: README D does not contradict itself: no KNOWN_FAULTS file is delivered",
                       "No separate KNOWN_FAULTS file is delivered" in _cv7 and "delivered with the document" not in _cv7))
        checks.append(("PDF-AGENTS: README D says how each PDF was made and checked: least bad with every remaining "
                       "objection quoted and the md authoritative, a round a checker sent back and a checker that did "
                       "not run disclosed; a sheet rendered to no PDF says the md is delivered alone",
                       "- `REPORT.pdf`: NOT FULLY VERIFIED (least bad)" in _cv6 and "x2 | md: x^2" in _cv6
                       and "a fresh verifier checked that cover page" in _cv6
                       and "authoritative" in _cv6 and "round 1, checker 1: DIFFERENT (1) -- back to the renderer" in _cv6
                       and "did not run" in _cv6
                       and "- `2026-01-01-abc1234/SIGNOFF.pdf`: no PDF" in _cv6))
        import project as _pm8, signoff as _so8
        _pm8_repo, _pm8.REPO = _pm8.REPO, REPO
        _smd8 = os.path.join(REPO, "audits", "x", "2026-01-01-abc1234", "SIGNOFF.md")
        _rr8, _calls8 = globals()["RERENDER_SHEET"], []
        globals()["RERENDER_SHEET"] = lambda c_, r_: (_calls8.append(r_), (0, ["ok"]))[1]
        try:
            _rg8 = globals()["REGENERATE_REPORT"]
            globals()["REGENERATE_REPORT"] = lambda c_: (0, ["ok"])
            open(_smd8, "w").write(f"**{_so8.HANDS_OFF_PENDING}**\n")
            _out8a = prepare_delivery({"rounds_dir": "audits/x"}, commit=False)[1]
            open(_smd8, "w").write(f"**{_so8.HANDS_OFF_LINE}**\n")
            _out8b = prepare_delivery({"rounds_dir": "audits/x"}, commit=False)[1]
        finally:
            globals()["RERENDER_SHEET"], globals()["REGENERATE_REPORT"], _pm8.REPO = _rr8, _rg8, _pm8_repo
            open(_smd8, "w").write("x")
        checks.append(("mini5 audit: --prepare-delivery renders again an approved sheet rendered before its approval (it "
                       "said 'to be approved'), and leaves one that says it was approved",
                       _calls8 == ["2026-01-01-abc1234"] and any("rendered before its approval" in x for x in _out8a)
                       and not any("rendered before" in x for x in _out8b)))
        # mini4/mini5 audits: a stop closed at delivery (S1) was in no delivered file; --prepare-delivery
        # regenerates REPORT and SUMMARY (make_report, stubbed) and adds the missing box entries to DECISIONS.md
        import decisions as _dec
        _xs = os.path.join(REPO, "audits", "x", "stops", "S1")
        os.makedirs(_xs)
        json.dump({"date": "2026-01-02", "command": "python3 audits/project.py --deliver", "exit": 1,
                   "causes": [{"class": "M", "line": "FAIL[deliver] SIGNOFF.pdf is older than its markdown"}]},
                  open(os.path.join(_xs, "STOP.json"), "w"))
        json.dump({"by": "human", "text": "3. copy by hand"}, open(os.path.join(_xs, "CLOSED.json"), "w"))
        _xd = os.path.join(REPO, "audits", "x", "DECISIONS.md")
        _dkeep = open(_xd).read()
        open(_xd, "w").write("# D\n\n" + _dec.BOX_START + "\n> - defect 1: x\n\nprose\n")
        _xr = os.path.join(REPO, "audits", "x", "REPORT.md")
        open(_xr, "w").write("# R\n| S0 | x |\n")
        _regen = []
        import project as _pm      # stops and decisions read the imported module's REPO (this one is __main__)
        _pm_repo, _pm.REPO = _pm.REPO, REPO
        _rr0 = globals()["REGENERATE_REPORT"]
        globals()["REGENERATE_REPORT"] = lambda c_: (_regen.append(1), write_draft(
            os.path.dirname(_xr), "REPORT.md", "# R\n| S0 | x |\n| S1 | 2026-01-02 |\n"), (0, ["ok"]))[2]
        # B12: this fixture (involved by default) has Checkpoint C answered; C itself is decisions' selftest
        _ckc0, _dec.checkpoint_c_refusal = _dec.checkpoint_c_refusal, (lambda c_: None)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as _o:
                _prep_s1 = prepare_delivery({"rounds_dir": "audits/x"}, commit=False)
                _rc_s1 = deliver({"rounds_dir": "audits/x"})
        finally:
            globals()["REGENERATE_REPORT"], _dec.checkpoint_c_refusal = _rr0, _ckc0
        _man_s1 = json.load(open(os.path.join(REPO, "audits", "x", DELIVERY_RECORD)))
        _dx = open(_xd).read()
        _box_again = _dec.refresh_box({"rounds_dir": "audits/x"})
        _pm.REPO = _pm_repo
        _kf = os.path.join(REPO, "deliverables", RUN_RECORD)
        _fx = os.path.join(REPO, "audits", "x", FACTS_DIR)
        checks.append(("mini4/mini5 S1, approver 2026-10-28: a stop closed after REPORT and DECISIONS were written is put "
                       "by --prepare-delivery into the facts draft (facts/REPORT.md regenerated, facts/RUN_RECORD.md "
                       "written, their hashes in DELIVERY.json) and into the DECISIONS box (the writer's text kept); the "
                       "main agent's REPORT.md and RUN_RECORD.md are never overwritten, and the delivered RUN_RECORD.md "
                       "is the agent's (no KNOWN_FAULTS-run.md)",
                       _rc_s1 == 0 and _regen == [1] and "> - stop S1 (M; answered by the human)" in _dx
                       and _man_s1["hashes"]["DECISIONS.md"] == file_hash("DECISIONS.md", _xd)
                       and _man_s1["open_at_preparation"] == [] and README_AC in _man_s1["hashes"]
                       and _dx.index("> - stop S1") < _dx.index("prose") and "> - defect 1: x" in _dx
                       and "| S1 | 2026-01-02 |" in open(os.path.join(_fx, "REPORT.md")).read()
                       and open(_xr).read() == "# R\n| S0 | x |\n"
                       and "3. copy by hand" in open(os.path.join(_fx, RUN_RECORD)).read()
                       and _man_s1["hashes"][RUN_RECORD] == file_hash(RUN_RECORD, os.path.join(_fx, RUN_RECORD))
                       and os.path.exists(_kf) and open(_kf).read().startswith("# Run record\n\nRUNREC-QZ\n")
                       and not os.path.exists(os.path.join(REPO, "deliverables", "KNOWN_FAULTS-run.md"))
                       and _box_again == []))
        shutil.rmtree(os.path.join(REPO, "audits", "x", "stops"))
        open(_xd, "w").write(_dkeep)
        open(_rmd, "w").write("x")
        open(os.path.join(REPO, "audits", "x", "REPORT.pdf"), "w").write("x")
        open(os.path.join(REPO, "audits", "x", "2026-01-01-abc1234", "SIGNOFF.md"), "w").write("x")
        # the math gate itself (stops.math_gate), with its checks run by a stand-in (stops.RUNNER): a synced test copy,
        # whose apparatus differs from its pin, can test the --deliver path (re-check M4)
        _keep_r, _keep_p0, ran_ = _st.RUNNER, _st.PHASE0_LINES, []
        _st.math_gate = _gate0
        _integ = lambda txt: (lambda argv: (ran_.append(" ".join(argv)), (1, txt) if "integrity.py" in " ".join(argv)
                                            else (0, "ok\n"))[1])
        try:
            _st.PHASE0_LINES = lambda c_: []
            _st.RUNNER = lambda argv: (ran_.append(" ".join(argv)), (0, "ok\n"))[1]
            with contextlib.redirect_stdout(io.StringIO()) as _o:
                rc_r = deliver({"rounds_dir": "audits/x", "mode": "release"})
            _st.RUNNER = _integ("FAIL[ownership] readers/summary-1.md was committed by \"x\" (abc1234); only a reader\n"
                                "FAIL[tooling] tooling changed since the pin: make_report.py\n")
            with contextlib.redirect_stdout(io.StringIO()) as _od:
                rc_d = deliver({"rounds_dir": "audits/x", "mode": "dev"})
            _st.RUNNER = _integ("FAIL[tooling] tooling changed since the pin: phase0.py\n")
            with contextlib.redirect_stdout(io.StringIO()) as _oc:
                rc_c = deliver({"rounds_dir": "audits/x", "mode": "dev"})
            _st.RUNNER = _integ("FAIL[ownership] 2026-01-01-abc1234/correspondence.json was committed by \"x\" (abc1234)\n")
            with contextlib.redirect_stdout(io.StringIO()) as _ov:
                rc_v = deliver({"rounds_dir": "audits/x", "mode": "release"})
            _st.RUNNER = lambda argv: (ran_.append(" ".join(argv)), (1, "HARD[sorry] sorry: A.lean:3: sorry\nPHASE 0: RED\n")
                                       if "phase0.py" in " ".join(argv) else (0, "ok\n"))[1]
            with contextlib.redirect_stdout(io.StringIO()) as _o3:
                rc_g = deliver({"rounds_dir": "audits/x", "mode": "release"})
        finally:
            _st.RUNNER, _st.PHASE0_LINES = _keep_r, _keep_p0
        checks.append(("--deliver runs the math gate's checks (integrity, Phase 0 read-only) in both modes and "
                       "delivers when they pass; no disclosing check (make_report, readers, selftests) runs",
                       rc_r == 0 and any("integrity.py --check" in x for x in ran_)
                       and any("phase0.py --readonly" in x for x in ran_)
                       and not any("make_report.py" in x or "readers.py" in x or "selftest_all" in x for x in ran_)))
        checks.append(("approver 2026-10-28: an integrity FAIL on a reader record or a non-core tool is a note and the "
                       "delivery proceeds; one on a proof-validity core file or a round's lane file refuses (RED[deliver])",
                       rc_d == 0 and "note: integrity (not the proof-validity core): FAIL[ownership] readers/summary-1.md"
                       in _od.getvalue() and "FAIL[tooling] tooling changed since the pin: make_report.py" in _od.getvalue()
                       and rc_c == 1 and "RED[deliver] not deliverable (the math gate)" in _oc.getvalue()
                       and "phase0.py" in _oc.getvalue() and rc_v == 1 and "correspondence.json" in _ov.getvalue()))
        checks.append(("the math gate: a failing Phase 0 (an undisclosed sorry) refuses --deliver",
                       rc_g == 1 and "RED[deliver] not deliverable (the math gate)" in _o3.getvalue()
                       and "HARD[sorry]" in _o3.getvalue()))
        _st.math_gate = _gate0
        _mrp.delivery_problems = _dpr0
        globals()["RENDER_CHECK"] = _rck0
        _pmd.REPO, _dc.checkpoint_c_refusal = _pmd_repo, _ckc_d
        st = subprocess.run(["git", "-C", REPO, "status", "--porcelain"], capture_output=True, text=True).stdout
        checks.append(("the project's tree does not see work_dir", ".formalization-work" not in st))
        checks += _changes_controls()
        checks += _order_controls()
        # a failed xelatex run leaves no PDF behind (a fake xelatex that ships a page, then fails)
        fb = os.path.join(tmp, "fakebin")
        os.makedirs(fb, exist_ok=True)
        open(os.path.join(fb, "xelatex"), "w").write(
            "#!/bin/sh\nfor a; do f=$a; done\nprintf partial > \"${f%.tex}.pdf\"\necho '! Undefined control sequence.'\nexit 1\n")
        os.chmod(os.path.join(fb, "xelatex"), 0o755)
        for _sub in ("rep", "sig"):
            os.makedirs(os.path.join(tmp, _sub), exist_ok=True)
        open(os.path.join(tmp, "rep", "REPORT.tex"), "w").write("x")
        open(os.path.join(tmp, "sig", "SIGNOFF.tex"), "w").write("x")
        _path0 = os.environ.get("PATH", "")
        os.environ["PATH"] = fb + os.pathsep + _path0
        try:
            r_ok, r_err = latex(os.path.join(tmp, "rep", "REPORT.tex"))
            s_ok, _ = latex(os.path.join(tmp, "sig", "SIGNOFF.tex"))
        finally:
            os.environ["PATH"] = _path0
        checks.append(("a failed compile (the paper's, --compile-source) never leaves a partial PDF behind (xelatex "
                       "shipped a page, then failed)",
                       not r_ok and not s_ok and "! Undefined control sequence." in r_err
                       and not os.path.exists(os.path.join(tmp, "rep", "REPORT.pdf"))
                       and not os.path.exists(os.path.join(tmp, "sig", "SIGNOFF.pdf"))))
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
    checks += _release_controls(fake)
    checks += _comment_only_controls()
    checks += _parts_differ_controls()
    checks += _m7_lexer_controls()
    checks += _m7_controls()
    checks += _m7_fail_closed_controls()
    checks += _steady_clock_controls()
    checks += _license_controls()
    checks += _adj_checks_controls()
    checks += _intake_terms_controls()
    checks += _checked_controls()
    fc_ = _floor_controls()
    # REVIEW-FLOOR LOW-1: the full selftest still runs the fast floor's control (S' within S)
    checks += fc_ + [("DESIGN-FLOOR: the full selftest ran the fast floor's control (project.py --selftest --floor)",
                      len(fc_) == 1 and fc_[0][0].startswith("floor: --deliver refuses when the math gate refuses"))]
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    ok = all(c for _, c in checks)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def _floor_controls(tb=False):
    """[(name, ok)]: the math gate's floor control on --deliver (DESIGN-FLOOR, 2026-11-10; floor mutant MG2): with every
    check before the gate a stand-in that passes and stops.math_gate refusing, _deliver exits 1, prints the refusal as
    RED[deliver] and delivers nothing, in dev and release and at every involvement level (REVIEW-FLOOR LOW-6 and
    MEDIUM-1: a --deliver that dropped the gate's refusals in release only passed this control when it ran dev only).
    `project.py --selftest --floor` runs this alone (seconds); the full selftest runs it too. An exception is a failed
    control; with tb (the --floor entry) it also prints its traceback (REVIEW-FLOOR LOW-2: the floor then counts a
    mutant that raises here as crashed, a hit, never as killed; the full selftest's output is as before)."""
    import contextlib, io, shutil, tempfile, traceback
    import decisions, make_report, stops, tool_patch
    global REPO
    keep = (REPO, decisions.reapproval_question, decisions.checkpoint_c_refusal, stops.open_name,
            make_report.summary_inputs, make_report.delivery_problems, stops.math_gate, tool_patch.delivery_problems)
    bad = []
    for m_ in MODES:
        for lv in INVOLVEMENT_LEVELS:
            tmp = tempfile.mkdtemp(prefix="project-floor-")
            buf, rc = io.StringIO(), None
            try:
                REPO = tmp
                os.makedirs(os.path.join(tmp, "audits", "x"))
                decisions.reapproval_question = decisions.checkpoint_c_refusal = stops.open_name = lambda c_: None
                make_report.summary_inputs = lambda c_: None
                make_report.delivery_problems = lambda c_, inp=None: []
                stops.math_gate = lambda c_: (["`python3 audits/phase0.py --readonly` fails (exit 1): HARD[sorry] GATEQZ"], [])
                tool_patch.delivery_problems = lambda c_: []
                with contextlib.redirect_stdout(buf):
                    rc = _deliver({"rounds_dir": "audits/x", "mode": m_, "involvement": lv})
            except Exception as e:      # noqa: BLE001 -- a failed control
                buf.write(f"(_deliver raised {type(e).__name__}: {e})\n{traceback.format_exc() if tb else ''}")
            finally:
                (REPO, decisions.reapproval_question, decisions.checkpoint_c_refusal, stops.open_name,
                 make_report.summary_inputs, make_report.delivery_problems, stops.math_gate,
                 tool_patch.delivery_problems) = keep
                gone = not os.path.exists(os.path.join(tmp, "deliverables"))
                shutil.rmtree(tmp, ignore_errors=True)
            out = buf.getvalue()
            if not (rc == 1 and "RED[deliver] not deliverable (the math gate)" in out and "GATEQZ" in out and gone):
                bad.append(f"{m_}/{lv}")
                tb = "Traceback (most recent call last)" in out
                print(f"  ({m_}/{lv}) " + (out if tb else " | ".join(out.strip().splitlines()[-4:])))
    return [("floor: --deliver refuses when the math gate refuses (RED[deliver]) and delivers nothing, in dev and "
             "release, at every involvement level" + (f" (not: {', '.join(bad)})" if bad else ""), not bad)]


def _checked_controls():
    """DESIGN-E2 fix 2: the README's code-written section -- the status mark (mechanical, faithful never marked, the
    same label normalisation on both sides), the reasons, the answers at each level, the software against the first
    pin, the notes by kind, the insertion, and the README fingerprint against the run log."""
    import integrity, make_report, shutil, tempfile
    global REPO, AUDITS
    out, tmp = [], tempfile.mkdtemp(prefix="checked-")
    keep = (make_report.disclosure_keys, integrity.applied_tool_patches, REPO, AUDITS)
    K = make_report.Key
    try:
        rd = os.path.join(tmp, "R")
        os.makedirs(rd)
        cfg = {"rounds_dir": rd, "involvement": "hands-off", "mode": "dev", "name": "P"}

        def run(results, summary, judgement=None, answers=()):
            open(os.path.join(rd, "SUMMARY.md"), "w").write(summary)
            jp = os.path.join(rd, JUDGEMENT_MD)
            if judgement is None:
                if os.path.exists(jp):
                    os.remove(jp)
            else:
                open(jp, "w").write(judgement)
            make_report.disclosure_keys = lambda c_, i_=None: (
                [K("Results", "result", l, st) for l, st in results] + list(answers))
            return status_block(cfg, {})
        integrity.applied_tool_patches = lambda *a, **k: {}
        res1 = [("Theorem 1.1", "faithful"), ("Lemma 1.2", "not established: a review failed"),
                ("Lemma 2.3", "false as printed; proved as repaired"), ("Theorem 2.6", "faithful under a reading choice"),
                ("Lemma 3.2 (c)", "true only vacuously"), ("Lemma 2.4", "assumed, not proved (`H`: literature "
                                                                       "hypothesis (declared at Checkpoint A))"),
                ("Lemma 4.1", "true only vacuously"), ("Claim (7)", "true only vacuously"),
                ("Lemma 5.1 (a)", "true only vacuously")]
        summ1 = ("# Summary\n\n## Results\n\n| Status | Results |\n|---|---|\n"
                 "| false, nothing else | Theorem 1.1 |\n| faithful | Lemma 1.2 |\n"
                 "| False as printed; the Lean proves the repaired statement | Lemma 2.3 (repair: x > 0) |\n"
                 "| faithful under a reading choice | **Theorem 2.6** |\n| true only vacuously | Lemma 3.2 (c) |\n"
                 "| Assumed, not proved | Lemma 2.4 (`H`) |\n| true only vacuously | Claim (7) (the bound) |\n"
                 "| true only vacuously | Lemma 5.1 (b) |\n\n## Next\n")
        l1, n1 = run(res1, summ1)
        t1 = "\n".join(l1)
        row = lambda lbl: next((l for l in l1 if l.startswith("|") and lbl in l), "")
        out.append(("E2 fix 2: the mark is mechanical -- a faithful result is never marked (whatever the summary says); "
                    "a cell keeping the status's first part (up to ';' or ' (') is not; 'Lemma 2.3 (repair: x > 0)' and "
                    "'**Theorem 2.6**' pair; 'Lemma 3.2 (c)' pairs with an identical row (M1), 'Lemma 5.1 (a)' never with 'Lemma 5.1 (b)'; a result the summary "
                    "does not list is marked, said plainly",
                    "Theorem 1.1 †" not in t1 and "Lemma 1.2 †" in t1 and "Lemma 2.3 †" not in t1
                    and "Theorem 2.6 †" not in t1 and "Lemma 3.2 (c) †" not in t1 and "Lemma 2.4 †" not in t1
                    and "Claim (7) †" not in t1
                    and "Lemma 4.1 †" in t1 and "† Not paired with a row of the summary's table" in t1
                    and "Lemma 5.1 (a) †" in t1 and "- Lemma 4.1, Lemma 5.1 (a). No reason is on record" in t1
                    and "- Lemma 1.2 — the summary: “faithful”. No reason is on record" in t1
                    and "| Status from the review records | Results |" in t1))
        out.append(("E2 fix 2: a marked result with no reason gives one [status-wording] note naming it",
                    len(n1) == 1 and n1[0].startswith("[status-wording]") and "3 result(s)" in n1[0]
                    and "Lemma 1.2; Lemma 4.1; Lemma 5.1 (a)" in n1[0]))
        res5 = [("Lemma 2.2", "faithful under a reading choice"), ("Lemma 2.3", "faithful under a reading choice"),
                ("Lemma 2.4", "faithful under a reading choice"), ("Proposition 2.7", "vacuous as printed; x")]
        l5, _n5 = run(res5, "# Summary\n\n## Results\n\n| Status | Results |\n|---|---|\n"
                            "| proved; faithful (recorded as a reading choice) | Lemma 2.2 |\n"
                            "| proved; not faithful (a reading choice was rejected) | Lemma 2.3 |\n"
                            "| proved as printed | Lemma 2.4 |\n| proved; true only vacuously | Proposition 2.7 |\n")
        t5 = "\n".join(l5)
        out.append(("REVIEW-E2E-FIX2 L-5: a cell holding the status's words in order, filler words aside, is not "
                    "marked (b2v: 'proved; faithful (recorded as a reading choice)'); one adding a negation, or "
                    "lacking a word, still is",
                    "Lemma 2.2 †" not in t5 and "Lemma 2.3 †" in t5 and "Lemma 2.4 †" in t5
                    and "Proposition 2.7 †" in t5))
        long_ = "because " + "the record names a helper, not the theorem, " * 12
        l2, n2 = run(res1, summ1, f"# J\n\n## {STATUS_WORDING}\n\n- Lemma 1.2: REASONQZ the review was on a helper.\n"
                                  f"- Lemma 4.1: {long_}\n- Lemma 5.1 (a): (b) is another part\n\n## Other\n- Lemma 9: x\n")
        t2 = "\n".join(l2)
        out.append(("E2 fix 2: the reasons come from JUDGEMENT.md \"Status wording\", a long one cut with a pointer; "
                    "with every reason on record no note",
                    "The agent's reason: “REASONQZ the review was on a helper.”" in t2
                    and f"(in full: `{JUDGEMENT_MD}`)" in t2 and n2 == []))
        l3, n3 = run(res1, "# Summary\n\n| Result | What |\n|---|---|\n| Theorem one | proved |\n")
        out.append(("E2 fix 2: no pairing at all gives the compare sentence, no mark and no note",
                    any("could not pair the summary's results table" in l for l in l3) and "†" not in "\n".join(l3)
                    and n3 == []))
        res4 = [("Lemma 2.1", "not established: x"), ("Lemma 2.2", "not established: x"),
                ("Lemma 3.4", "not established: x"), ("Lemma 3.5", "faithful under a reading choice")]
        summ4 = ("# Summary\n\n## Status of every result\n\n| Status | Results |\n|---|---|\n"
                 "| not established: x | Lemmas 2.1, 2.2 and 3.4 |\n"
                 "| faithful under a reading choice | Lemma 3.5 (for one fixed labelling; its statement is shorter) |\n")
        l4, n4 = run(res4, summ4)
        out.append(("E2 fix 2 (M1, L3): 'Lemmas 2.1, 2.2 and 3.4' is three results; a cell is split only at '; ' "
                    "outside parentheses; a table under another heading whose header starts '| Status' is found",
                    "†" not in "\n".join(l4) and n4 == []
                    and any("it checks nothing more, so compare the two" in l for l in l4)
                    and not any("in the same words" in l for l in l4)
                    and summary_result_rows(summ4).get("Lemma 3.5 (for one fixed labelling; its statement is shorter)")))
        # attack review E H2: a decoy row hidden in an HTML comment, or a second row, never vouches for the status
        res5 = [("Lemma 1.2", "not established: a review failed"), ("Lemma 1.3", "not established: a review failed")]
        summ5 = ("# Summary\n\n## Results\n\n| Status | Results |\n|---|---|\n<!--\n"
                 "| not established: a review failed | Lemma 1.2 |\n-->\n| faithful | Lemma 1.2 |\n"
                 "| not established: a review failed | Lemma 1.3 |\n| faithful | Lemma 1.3 |\n")
        t5 = "\n".join(run(res5, summ5)[0])
        out.append(("attack review E H2: an HTML comment is not read; a label in several rows is checked in every row "
                    "and all its cells are shown",
                    "Lemma 1.2 †" in t5 and "Lemma 1.3 †" in t5 and "- Lemma 1.2 — the summary: “faithful”." in t5
                    and "- Lemma 1.3 — the summary's rows: “not established: a review failed”, “faithful”." in t5
                    and "checks nothing more" not in t5
                    and summary_result_rows(summ5) == {"Lemma 1.2": ["faithful"],
                                                       "Lemma 1.3": ["not established: a review failed", "faithful"]}))
        # L1, L3 (b3v), L4: a reason or cell is inert; "Definition 2.1 (H)" pairs; a label holding ": " has its reason
        res6 = [("Definition 2.1", "true only vacuously"), ("Lemma 2 (a: b)", "not established: x")]
        summ6 = ("# Summary\n\n## Results\n\n| Status | Results |\n|---|---|\n"
                 "| true only vacuously | Definition 2.1 (H) |\n| fine <br> `y` | Lemma 2 (a: b) |\n")
        l6, n6 = run(res6, summ6, f"# J\n\n## {STATUS_WORDING}\n\n- Lemma 2 (a: b): REASONQZ <br><br>Checked: `ok`\n")
        t6 = "\n".join(l6)
        out.append(("attack review E L1, L3, L4: the summary's cell and the agent's reason are inert (no raw HTML, no "
                    "code span); 'Definition 2.1 (H)' pairs with Definition 2.1; a label containing ': ' finds its "
                    "reason",
                    "Definition 2.1 †" not in t6 and "Lemma 2 (a: b) †" in t6 and n6 == []
                    and "“fine &lt;br&gt; \\`y\\`”" in t6 and "“REASONQZ &lt;br&gt;&lt;br&gt;Checked: \\`ok\\`”" in t6
                    and "<br>" not in t6))
        # E2E-FIX2 M2b (the e2e run: `| Result | Status (as the Lean has it) |` under "## Status of each result"
        # paired nothing): the columns are found by the header; a table with a Status column but no Result column
        # (a stops table) is not the results table
        summ7 = ("# Summary\n\n| Stop | Status |\n|---|---|\n| S1 | Lemma 1.2 |\n\n## Status of each result\n\n"
                 "| Result | Status (as the Lean has it) | Note |\n|---|---|---|\n| **Lemma 1.2** | not established: x | n |\n"
                 "| Theorem 1.1, Lemma 2.3 | Proved; faithful. | n |\n")
        l7, n7 = run([("Lemma 1.2", "not established: x"), ("Theorem 1.1", "faithful")], summ7)
        out.append(("E2E-FIX2 M2b: a summary table `| Result | Status ... |` is paired by its header, whatever its "
                    "heading and column order; a Status table with no Result column is not the results table",
                    summary_result_rows(summ7) == {"Lemma 1.2": ["not established: x"],
                                                   "Theorem 1.1": ["Proved; faithful."], "Lemma 2.3": ["Proved; faithful."]}
                    and not any("could not pair" in l for l in l7) and "†" not in "\n".join(l7) and n7 == []))
        # E2E-FIX2 M2a (the e2e run: six results the approved sheet flags CHECK for a reading choice or a partial
        # skip read as plain "faithful"): such a result is marked, the sheet's reason beside it; its status stays
        json.dump({"round": "RS"}, open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
        os.makedirs(os.path.join(rd, "RS"), exist_ok=True)
        json.dump({"rows": [{"result": "Lemma 2.1", "flag": "CHECK", "check_reason": "Generalization: confirm REASONQZ."},
                            {"result": "Remark 4.2 (b)", "flag": "CHECK", "check_reason": "Skip: the density claim."},
                            {"result": "Theorem 1.1", "flag": "OK"},
                            {"result": "Lemma 1.2", "flag": "CHECK", "check_reason": "not faithful anyway"}]},
                  open(os.path.join(rd, "RS", "SIGNOFF.json"), "w"))
        l8, n8 = run([("Theorem 1.1", "faithful"), ("Lemma 2.1", "faithful"), ("Remark 4.2", "faithful"),
                      ("Lemma 1.2", "not established: x")],
                     "# Summary\n\n## Results\n\n| Status | Results |\n|---|---|\n| faithful | Theorem 1.1, Lemma 2.1, "
                     "Remark 4.2 |\n| not established: x | Lemma 1.2 |\n")
        t8 = "\n".join(l8)
        # E2E-FIX2 M4b: a row text calling a closed re-approval open is named at prepare (a NOTE, never a refusal)
        json.dump({"rows": [{"result": "Remark 5.2", "differences": "its re-approval is open (REAPPROVAL.json, not "
                             "closed)"}, {"result": "Lemma 2.1", "differences": "fine"}]},
                  open(os.path.join(rd, "RS", "SIGNOFF.json"), "w"))
        _n_open = reapproval_text_notes(rd, "RS")
        json.dump({"closed": True, "closed_by": "approve RS"}, open(os.path.join(rd, "REAPPROVAL.json"), "w"))
        _n_closed = reapproval_text_notes(rd, "RS")
        os.remove(os.path.join(rd, "REAPPROVAL.json"))
        out.append(("E2E-FIX2 M4b: prepare names each approved-sheet row that calls a closed re-approval open, and "
                    "nothing while there is no closed re-approval",
                    _n_open == [] and len(_n_closed) == 1 and "'Remark 5.2'" in _n_closed[0]
                    and _n_closed[0].startswith("prepare: NOTE:")))
        os.remove(os.path.join(rd, "APPROVED_FINGERPRINTS.json"))
        shutil.rmtree(os.path.join(rd, "RS"))
        out.append(("E2E-FIX2 M2a: a faithful result the approved sheet flags CHECK (a part row marks its result) is "
                    "marked †, with the sheet's reason; an OK one and a not-faithful one are not marked for it",
                    "| faithful | Theorem 1.1; Lemma 2.1 †; Remark 4.2 † |" in t8
                    and "- Lemma 2.1 — the sheet: “Generalization: confirm REASONQZ.”." in t8
                    and "- Remark 4.2 — the sheet: “Skip: the density claim.”." in t8
                    and "Lemma 1.2 †" not in t8 and "not faithful anyway" not in t8 and n8 == []))
        # the whole section: answers, notes, insertion (no git: the first pin cannot be read)
        approval = {"round": "R1", "commit": "abcdef0123456789", "by": "human"}
        stop_key = K(make_report.ANSWERS_SECTION, "stop decision", "2026-10-29 stop S1", "“close it” — audit commit 0be0a91")
        appr_key = K(make_report.ANSWERS_SECTION, "approval", "Checkpoint B", "“approved” — audit commit 5dce37e")
        notes_ = ["[weird] SOMETHINGNEWQZ happened", "[status-wording] x", "[pdf] SUMMARY.pdf stale",
                  "[adj-record] Lemma 1.2 has a finding not ruled on", "[adj-record] another for Lemma 1.2"]
        make_report.disclosure_keys = lambda c_, i_=None: [K("Results", "result", "Lemma 1.2", "faithful"), stop_key]
        ho = readme_checked(dict(cfg), notes_, {"approval": dict(approval, by="agent")}, ["TABLEQZ"])
        make_report.disclosure_keys = lambda c_, i_=None: [K("Results", "result", "Lemma 1.2", "faithful")]
        none_ = readme_checked(dict(cfg), [], {"approval": dict(approval, by="agent")}, [])
        noappr = readme_checked(dict(cfg), [], {}, [])
        make_report.disclosure_keys = lambda c_, i_=None: [K("Results", "result", "Lemma 1.2", "faithful"), appr_key]
        inv = readme_checked(dict(cfg, involvement="involved"), [], {"approval": approval}, [])
        make_report.disclosure_keys = lambda c_, i_=None: [K("Results", "result", "Lemma 1.2", "faithful"), stop_key]
        inv2 = readme_checked(dict(cfg, involvement="involved"), [], {"approval": approval}, [])
        out.append(("E2 fix 2 (M1, M2): the answers recorded as yours at every level -- hands-off lists a human stop "
                    "answer and says the agent approved the statements; 'None.' only with no answer; involved points "
                    "to the approval above, never a Lean commit called an audit commit",
                    "- stop decision (2026-10-29 stop S1): “close it” — audit commit 0be0a91" in ho
                    and "approved by the agent, not by you (hands-off); every other decision" in ho
                    and "**Answers recorded as yours.** None. The statements were approved by the agent" in none_
                    and "No approval of the statements is on record." in noappr
                    and "The statements: approved by you (the approval above)." in inv
                    and "approval's Lean commit is `abcdef01234`" in inv2 and "audit commit `abcdef" not in inv2))
        out.append(("E2 fix 2: the notes -- an unknown one is shown as Other, a document-only kind is counted, a note "
                    "naming a result lists it; the proof checks say the freeze did not run without an approval; the "
                    "section starts with its heading and keeps the table",
                    ho.startswith(CHECKED_HEADING + "\n") and "TABLEQZ" in ho
                    and "- Other: SOMETHINGNEWQZ happened." in ho
                    and "- A reviewer's finding not yet ruled on: Lemma 1.2 (2 notes)." in ho
                    and "About the documents only: 1 on statuses worded differently" in ho and "1 on a PDF left out" in ho
                    and "5 note(s) to the formalizing agent" in ho and "Nothing." in none_
                    and "(no statements approved: the check that they are unchanged was not run)" in noappr
                    and "The settings fixed at the start could not be read" in ho))
        import decisions
        keep_unp = decisions.unproved
        try:
            decisions.unproved = lambda c_, *a_, **k_: {"decls": {"P.lemma_x": "[DELEGATED]"}, "lines": {}, "goal": [],
                                                       "problems": []}
            unp = readme_checked(dict(cfg), [], {"approval": dict(approval, by="agent")}, [])
        finally:
            decisions.unproved = keep_unp
        fp_k = first_pin
        try:
            globals()["first_pin"] = lambda r_: {"config": {"mode": "release"}}
            nokey = readme_checked(dict(cfg), [], {}, [])
            globals()["first_pin"] = lambda r_: {"config": {"mode": "release", "involvement": "hands-off"}}
            haskey = readme_checked(dict(cfg), [], {}, [])
        finally:
            globals()["first_pin"] = fp_k
        out.append(("COMPAT-E M2, attack review E L4: the proof checks name the declarations a logged leave line lets "
                    "through; 'as fixed when the run started' only when the first pin records the level",
                    "lets through 1 Lean declaration(s) left unproved by a logged decision" in unp
                    and "lets through" not in noappr
                    and "as fixed when the run started" not in nokey
                    and "do not record the involvement level; this is the settings file's value" in nokey
                    and "as fixed when the run started" in haskey and "do not record" not in haskey))
        c0 = "# What is delivered\n\nINTRO\n\n## A. The report\n\nA\n"
        out.append(("E2 fix 2: the section is inserted before README A-C's first `## ` line, else appended",
                    insert_checked(c0, "SECTQZ\n") == "# What is delivered\n\nINTRO\n\nSECTQZ\n\n## A. The report\n\nA\n"
                    and insert_checked("# T\n\nX\n", "SECTQZ\n") == "# T\n\nX\n\nSECTQZ\n"))
        # the software block, against the first pin's audits_commit
        aud = os.path.join(tmp, "aud")
        G = lambda *a: subprocess.run(["git", "-C", aud, *a], capture_output=True, text=True)
        os.makedirs(os.path.join(aud, "P"))
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        open(os.path.join(aud, "stops.py"), "w").write("a\n")
        G("add", "-A"); G("commit", "-qm", "setup")
        base = G("rev-parse", "HEAD").stdout.strip()
        json.dump({"audits_commit": base, "config": {}}, open(os.path.join(aud, "P", "TOOLING_PIN.json"), "w"))
        G("add", "-A"); G("commit", "-qm", "pin")
        prd = os.path.join(aud, "P")
        AUDITS = aud
        sw = lambda n_=(): _software_line({"mode": "dev"}, prd, list(n_))
        s_un = sw()
        open(os.path.join(aud, "stops.py"), "w").write("b\n"); G("commit", "-qam", "tool-patch TP1 apply")
        integrity.applied_tool_patches = lambda *a, **k: {"TP1": {}}
        s_tp, s_tpf = sw(), sw(["integrity: FAIL[tool-patch] TP1 has no patch.diff"])
        integrity.applied_tool_patches = lambda *a, **k: {}
        s_fake = sw()
        integrity.applied_tool_patches = lambda *a, **k: {"TP1": {}}
        open(os.path.join(aud, "x.py"), "w").write("x\n"); G("add", "-A"); G("commit", "-qm", "maintainer: update x.py")
        s_mt = sw()
        json.dump({"audits_commit": G("rev-parse", "HEAD").stdout.strip(), "config": {}},     # a re-pin: the working
                  open(os.path.join(aud, "P", "TOOLING_PIN.json"), "w"))                    # pin moves, not the first
        G("add", "-A"); G("commit", "-qm", "pin (re-pin)")
        s_rp = sw()
        open(os.path.join(aud, "stops.py"), "w").write("c\n")
        s_unc = sw()
        tk_ = tooling_since_first_pin
        try:
            globals()["tooling_since_first_pin"] = lambda a_, r_: ([], ["abc1234 maintainer: try x",
                                                                      "def5678 Revert \"maintainer: try x\""], [])
            s_rev = sw()
        finally:
            globals()["tooling_since_first_pin"] = tk_
        out.append(("E2 fix 2 (M2): the checking software against the first pin: unchanged; one verified TP apply is a "
                    "reviewed correction; a TP apply with a FAIL[tool-patch] note, or one not applied, is a change; a "
                    "maintainer commit is listed; an uncommitted edit is named",
                    "Unchanged since the run started." in s_un and "Corrected 1 time(s)" in s_tp
                    and "other than by a reviewed correction" in s_tpf and "other than by a reviewed correction" in s_fake
                    and "maintainer: update x.py`" in s_mt and "Also 1 reviewed correction(s)." in s_mt
                    and "In development mode" in s_mt and "maintainer: update x.py`" in s_rp
                    and "Uncommitted changes to: stops.py" in s_unc
                    and "changed and restored during the run by: `abc1234 maintainer: try x`" in s_rev
                    and "Unchanged" not in s_rev))
        # the README fingerprint against the committed run log
        REPO = os.path.join(tmp, "repo")
        GR = lambda *a: subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True)
        os.makedirs(os.path.join(REPO, "audits", "x")); os.makedirs(os.path.join(REPO, "deliverables"))
        GR("init", "-q"); GR("config", "user.email", "t@t"); GR("config", "user.name", "t")
        rme = os.path.join(REPO, "deliverables", "README.md")
        body = f"# What is delivered\n\n{CHECKED_HEADING}\n\nX\n".encode()
        open(rme, "wb").write(body)
        lg = os.path.join(REPO, "audits", "x", "RUN_LOG.md")

        def log(*lines):
            open(lg, "w").write(f"# Log\n\n## {DELIVERY_LOG}\n\n" + "".join(l + "\n" for l in lines) + "\n## Other\n")
            GR("add", "-A"); GR("commit", "-qm", "log")
        good = (f"- t0 to t1: project.py --deliver delivered 3 file(s) to deliverables/ (README.md sha256 "
                f"{hashlib.sha256(body).hexdigest()}, {len(body)} bytes); notes: none")
        cx = {"rounds_dir": "audits/x"}
        log("- t: project.py --deliver refused: RED[deliver]")
        r_none = readme_problems(cx)
        open(rme, "wb").write(b"# What is delivered\n\nold\n")
        log("- t: project.py --deliver delivered 3 file(s)")
        r_old2 = readme_problems(cx)
        open(rme, "wb").write(body)
        log(good, "- t2: project.py --deliver refused: RED[deliver] (the command's output says why)")
        r_ok = readme_problems(cx)
        open(rme, "ab").write(b"\nPushed to origin, branch main, as commit `abc1234`: the tree of Lean HEAD `def5678`.  \n"
                              b"\nPushed to o, branch b, as commit `abc1234`: the tree of Lean HEAD `def5678`, without "
                              b"paper.\n"
                              b"\nPushed to o, branch b, as commit `abc1234`: the tree of Lean HEAD `def5678`, without "
                              b"`paper/Smith+Jones (2024) ~O'Neil.pdf`.\n")
        r_push = readme_problems(cx)
        b_push = open(rme, "rb").read()
        open(rme, "ab").write(b"\nPushed to o, branch b, as commit `abc1234`: the tree of Lean HEAD `def5678`, without "
                              b"`paper` NOTE: all faithful `x`.\n")
        r_tick = readme_problems(cx)
        open(rme, "wb").write(b_push + b"I was added later\n")
        r_tail = readme_problems(cx)
        open(rme, "wb").write(body + b"\nPushed to origin. NOTE: every result is faithful, branch main, as commit "
                              b"`abc1234`: the tree of Lean HEAD `def5678`.\n")
        r_free = readme_problems(cx)
        open(rme, "wb").write(body.replace(b"X", b"Y"))
        r_edit = readme_problems(cx)
        # attack review E M1 (E6, E7): the delivery line's fingerprint rewritten to the edited README, or removed
        b2 = body.replace(b"X", b"Y")
        log(good.replace(hashlib.sha256(body).hexdigest(), hashlib.sha256(b2).hexdigest()))
        r_rw = readme_problems(cx)
        log("- t0 to t1: project.py --deliver delivered 3 file(s) to deliverables/; notes: none")
        r_rm = readme_problems(cx)
        open(rme, "wb").write(b"# What is delivered\n\nold\n")
        r_rm2 = readme_problems(cx)
        out.append(("E2 fix 2 (F11): --check-delivered compares README.md with the last committed RUN_LOG delivery line "
                    "that logs its sha256 (a later refused line does not count); stage5's `Pushed to` lines (both forms, "
                    "trailing spaces; the paper paths in backticks, any characters but a backtick: re-review E L2; the "
                    "older unquoted form) may follow, in exactly their generated form; an edit, or other text after it, "
                    "is NOT ok; a README with the section and no logged sha256 is NOT ok; an old delivery is not "
                    "checked, said; a logged fingerprint later rewritten or removed is NOT ok, with the commit (attack "
                    "review E M1)",
                    r_none[0] and "no committed RUN_LOG.md delivery line" in r_none[0][0] and r_ok == ([], [])
                    and r_push == ([], []) and "not a `Pushed to` line" in r_tail[0][0]
                    and bool(r_tick[0]) and "not a `Pushed to` line" in r_tick[0][0]
                    and bool(r_free[0]) and "not a `Pushed to` line" in r_free[0][0]
                    and "is not the README delivered" in r_edit[0][0]
                    and r_old2[0] == [] and "predates" in r_old2[1][0]
                    and all(r_[0] and "no longer does (changed by commit `" in r_[0][0] for r_ in (r_rw, r_rm, r_rm2))))
        import contextlib
        g_, keep_ = globals(), (check_delivered, readme_problems)
        try:
            g_["check_delivered"] = lambda c_, with_readme=False: []
            g_["readme_problems"] = lambda c_: ([], ["deliverables/README.md not checked: its delivery predates x"])
            o_ = io.StringIO()
            with contextlib.redirect_stdout(o_):
                rc_nv = check_delivered_cli({})
            hist_ = ("RUN_LOG.md once logged README.md's sha256 abc… and no longer does (changed by commit `x`): a "
                     "delivery line was edited or removed after delivery, so the README cannot be checked against it; "
                     "this stays in the record")
            g_["readme_problems"] = lambda c_: ([], [])
            o_h, o_m = io.StringIO(), io.StringIO()
            g_["check_delivered"] = lambda c_, with_readme=False: [hist_]
            with contextlib.redirect_stdout(o_h):
                check_delivered_cli({})
            g_["check_delivered"] = lambda c_, with_readme=False: [hist_, "deliverables/SUMMARY.pdf is missing (x)"]
            with contextlib.redirect_stdout(o_m):
                check_delivered_cli({})
        finally:
            g_["check_delivered"], g_["readme_problems"] = keep_
        out.append(("attack review E M1: a README.md no delivery line fingerprints is reported 'not verified', never ok",
                    rc_nv == 0 and "delivered check: README.md not verified" in o_.getvalue()
                    and "delivered check: ok" not in o_.getvalue()))
        out.append(("re-review E L3: a rewritten or removed delivery line is NOT ok with advice that delivering again "
                    "does not clear it (never 'deliver again' alone); with other problems too, those are sent to "
                    "--deliver",
                    "delivering again does not clear that" in o_h.getvalue() and "NOT ok: deliver again" not in
                    o_h.getvalue() and "for the rest" not in o_h.getvalue()
                    and "delivering again does not clear that" in o_m.getvalue() and "for the rest, deliver again" in
                    o_m.getvalue()))
    finally:
        make_report.disclosure_keys, integrity.applied_tool_patches, REPO, AUDITS = keep
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _intake_terms_controls():
    """DESIGN-E2 fix 3 (forgery review 2026-11 F4): the involvement level, the mode and the ownership version are the
    first committed pin's when it records them; a pin without the key, no pin, or a --selftest process without the
    opt-in read the working values as before; the cache keeps only a found pin."""
    import integrity, shutil, tempfile
    import project as _p      # the module integrity.py reads (this file may run as __main__)
    out, tmp = [], tempfile.mkdtemp(prefix="terms-")
    keep_flag = _p._TERMS_FROM_PIN
    try:
        G = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True)
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")

        def pin_(name, doc, commit=True):
            d = os.path.join(tmp, name)
            os.makedirs(d, exist_ok=True)
            json.dump(doc, open(os.path.join(d, "TOOLING_PIN.json"), "w"))
            if commit:
                G("add", "-A"); G("commit", "-qm", f"pin {name}")
            return d
        a = pin_("A", {"config": {"involvement": "involved", "mode": "release"}, "ownership": 4})
        b = pin_("B", {"config": {"mode": "release"}})
        c = os.path.join(tmp, "C"); os.makedirs(c)
        cf = lambda d, **k: dict({"rounds_dir": d, "_terms_from_pin": True, "involvement": "hands-off",
                                  "mode": "dev"}, **k)
        _TERMS_CACHE.clear()
        lv_a, md_a, df_a = involvement(cf(a)), mode(cf(a)), terms_differ(cf(a))
        lv_b, md_b = involvement(cf(b)), mode(cf(b))
        no_opt = (involvement({"rounds_dir": a, "involvement": "hands-off"}), mode({"rounds_dir": a}))
        sv_ = (integrity.scope_value(cf(a), "involvement"), integrity.scope_value(cf(a), "mode"))
        itp_ = integrity.intake_terms_problems(a, {"config": cf(a), "ownership": 4}, cf(a))
        lv_c0 = involvement(cf(c))
        pin_("C", {"config": {"involvement": "statements-only", "mode": "release"}, "ownership": 4})
        lv_c1 = involvement(cf(c))
        out.append(("E2 fix 3: a first pin saying involved/release outweighs a config saying hands-off/dev (and "
                    "terms_differ names both); a pin without the key reads the config; no opt-in in a --selftest "
                    "process reads the config",
                    (lv_a, md_a) == ("involved", "release")
                    and df_a == [("involvement", "hands-off", "involved"), ("mode", "dev", "release")]
                    and (lv_b, md_b) == ("hands-off", "release") and no_opt == ("hands-off", "dev")))
        out.append(("COMPAT-E M1: with the first pin's terms in force, the pin check still compares the raw working "
                    "values -- a config and a working pin saying hands-off/dev under a first pin of involved/release "
                    "give FAIL[pin] for both keys, from the pin and from the config",
                    sv_ == ("hands-off", "dev")
                    and sum(1 for s_, m_ in itp_ if s_ == "FAIL" and m_.startswith("[pin] `involvement`")) == 2
                    and sum(1 for s_, m_ in itp_ if s_ == "FAIL" and m_.startswith("[pin] `mode`")) == 2))
        out.append(("E2 fix 3 (L6): no committed pin reads the config and is not cached; once the pin is committed the "
                    "same process reads the pin's terms",
                    lv_c0 == "hands-off" and lv_c1 == "statements-only"))
        json.dump({"config": {}, "ownership": 2}, open(os.path.join(a, "TOOLING_PIN.json"), "w"))   # working pin lowered
        d_ = pin_("D", {"config": {}})                                                             # first pin: no key
        json.dump({"config": {}, "ownership": 4}, open(os.path.join(d_, "TOOLING_PIN.json"), "w"))
        _p._TERMS_FROM_PIN = True
        pv = (integrity.pinned_version(a), integrity.pinned_version(d_))
        _p._TERMS_FROM_PIN = False
        pv_off = integrity.pinned_version(a)
        out.append(("E2 fix 3 (M4): a first pin of 4 under a working pin of 2 gives 4; a first pin without the "
                    "`ownership` key reads the working pin (4), no crash; a --selftest process without the opt-in "
                    "reads the working pin",
                    pv == (4, 4) and pv_off == 2))
    finally:
        _p._TERMS_FROM_PIN = keep_flag
        _TERMS_CACHE.clear()
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _release_controls(fake):
    """The run-mode classifier (RELEASE, CLASSIFICATION.md): [(check, passed)]."""
    rel, dev = {"mode": "release"}, {"mode": "dev"}
    import stops as _stops
    R_ = "2026-10-19-full-1a2b3c4"

    def total_(c):      # A1: closer(c, None) == closer(c), and no exception (a TypeError before the fix)
        try:
            return closer(c, None) == closer(c)
        except TypeError:
            return False
    out = [("every cause code has a release class and kind; every class is F, P, I, H or N; class H is kind human "
            "and class N kind disclose, both ways (U2 §4: one table)",
            set(CAUSES) <= set(RELEASE) and {v[0] for v in RELEASE.values()} <= set("FPIHN")
            and {v[1] for v in RELEASE.values()} <= set(KINDS)
            and all((k == "human") == (c_ == "H") and (k == "disclose") == (c_ == "N") for c_, k in RELEASE.values())
            and set(KINDS) == set(CURES)),
           ("the printed cure of every code is CURES[its kind] + its CAUSES text; an uncoded one is the "
            "unknown-retry route",
            all(cure_text(c).startswith(CURES[release_kind(c)]) and CAUSES[c][1] in cure_text(c) for c in CAUSES)
            and CAUSES["unknown-retry"][1] in cure_text("no-such-code") and release_kind("no-such-code") == "rerun"),
           ("B2: drift's release cure is restoring the approved statement; an intended change is a re-approval, "
            "never begun inside the open stop",
            "restore the approved statement" in cure_text("drift") and "never inside an open stop" in cure_text("drift")
            and release_kind("drift") != "human"),
           ("B2 / approver 2026-10-24: the stop policy (intake paragraph and Checkpoint A line) names the four stops "
            "(goal, outward action, only you can fix incl. another program changing the files, a genuine ambiguity) "
            "in every mode x level, the questions of the level, and only the four in release; no retry-budget stop",
            all(all(w in " ".join(stop_policy_text(m_, lv_).split()) for w in (
                "goal result that looks false", "pushed, published or sent", "only you can fix",
                "another program that keeps changing the project's files", "genuinely ambiguous",
                "(4) the paper's meaning", "what each would mean for the formalization", "hands-off included",
                "resumes at the level you chose")) and "retry budget" not in stop_policy_text(m_, lv_)
                and "keeps failing" not in stop_policy_text(m_, lv_)
                for m_ in MODES for lv_ in (None,) + INVOLVEMENT_LEVELS)
            and stop_policy_text("release", "statements-only").endswith(
                "keeps working on everything else meanwhile: only the delivery waits for your answer")
            and "Checkpoints B and C" in stop_policy_text("release", "involved")
            and "asks you nothing" in stop_policy_text("release", "hands-off")
            and "only for:" in stop_policy_text("release", "involved") and "Nothing else stops the run" in
            stop_policy_text("release") and "every failing check stops the run" in stop_policy_text("dev", "hands-off")
            and all(len(l_) <= 96 for l_ in stop_policy_text("release").splitlines())),
           ("L1: every code x mode x level has a closer: release, a kind other than human/disclose closes with "
            "--cured re-running a read-only check stops.command_problem accepts in that mode (or the --check "
            "recorded at open); human: --human; disclose: no stop; dev: --human",
            all((closer(c, R_) == "@check" or _stops.command_problem(closer(c, R_), dict(fake, mode="release",
                                                                                        involvement=lv)) is None)
                if release_kind(c) not in ("human", "disclose", "precondition") else closer(c, R_) is None
                for c in list(RELEASE) + ["no-such-code"] for lv in INVOLVEMENT_LEVELS)
            and not any(release_cure(dict(fake, mode="dev", involvement=lv), [c]) for c in RELEASE
                        for lv in INVOLVEMENT_LEVELS)),
           ("A1 (STATUS A1, De Medts): closer is total: a round of None reads as the default \"<R>\", so a --note "
            "stop opened with no --round and a closer with no {R} records its code's closer instead of a TypeError",
            all(total_(c) for c in list(CLOSER) + ["no-such-code"]) and total_("drift")
            and closer("drift") == "python3 audits/fingerprint.py --check"),
           ("B1a reclassified only codes whose cure exists today: lane-output, tool-call and git-error are reruns "
            "(H before); B10 (ADDENDUM N1): deliver, unverified and deliver-stale are preconditions of --deliver, "
            "with no closer; B1c: head-moved and gitmeta are restores (tree-equality revert, Stage 1 snapshot); "
            "approver 2026-10-24: the human codes of release are exactly the four stops (RELEASE_STOPS: unproved-goal; "
            "outward-action; env-unknown, codex-approval, interference; ambiguity); round-cap follows "
            "round_cap_route (judge: no stop in release; dev: a human stop); tool-bug is the patch kind",
            all(RELEASE[c] == ("I", "rerun") for c in ("lane-output", "tool-call", "git-error"))
            and all(RELEASE[c] == ("F", "precondition") and closer(c) is None and c in CAUSES for c in DELIVERY_CODES)
            and "deliver" not in CLOSER and RELEASE["head-moved"] == RELEASE["gitmeta"] == ("I", "restore")
            and {c for c in RELEASE if release_kind(c) == "human"} == {"unproved-goal", "outward-action",
                                                                     "env-unknown", "codex-approval", "interference",
                                                                     "ambiguity"}
            and sorted(RELEASE_STOPS) == [1, 2, 3, 4] and RELEASE["tool-bug"] == ("I", "patch")
            and round_cap_route({"mode": "release"}) == "judge" and round_cap_route({"mode": "dev"}) == "stop"
            and RELEASE["round-cap"] == ("N", "disclose") and is_stop_cause("round-cap")),
           ("no code of a STOP class is non-blocking in release (tamper, apparatus, freeze, gitmeta, proof, tool-bug); "
            "the one exception is round-cap under round_cap_route 'judge' (approver 2026-10-24: the operator judges "
            "the cause, no stop of its own)",
            [c for c in CAUSES if cause_class(c) in STOP_CLASSES and release_class(c) == "N"]
            == ([] if ROUND_CAP_ROUTE == "stop" else ["round-cap"])),
           ("faithfulness, proof and integrity codes block in release: drift, index, unsettled, report, sorry, "
            "axiom, build, unlisted, ownership, tooling, tree-changed, unproved-goal",
            not any(disclosed(rel, c) for c in ("drift", "index", "unsettled", "report", "sorry", "axiom", "build",
                                               "unlisted", "ownership", "tooling", "tree-changed", "unproved-goal",
                                               "lane-fault", "unused-args", "dependencies"))),
           ("an unknown code blocks (fails closed)", release_class("no-such-code") == "I" and not disclosed(rel, "x-y")),
           ("release self-cure: every I/F/P code and an unknown one is the operator's cure in release, with the "
            "cure of its kind; an H code (unproved-goal, env-unknown, outward-action, codex-approval) never is; an N "
            "code adds no cure; dev self-cures nothing",
            all(release_cure(rel, [c]) == [release_kind(c)] and release_kind(c) in CURES
                for c in list(RELEASE) + ["no-such-code"] if release_class(c) in "FPI" and c not in DELIVERY_CODES)
            and all(release_cure(rel, [c]) is None for c in DELIVERY_CODES)
            and all(release_cure(rel, [c]) is None for c in RELEASE if release_class(c) == "N")
            and release_cure(rel, ["stray-loop", "reader"]) == ["rerun"]
            and all(release_cure(rel, [c]) is None for c in RELEASE if release_class(c) == "H")
            and release_cure(rel, ["seal-mismatch", "env-unknown"]) is None
            and all(release_class(c) == "H" and is_stop_cause(c) for c in ("outward-action", "codex-approval"))
            and not any(release_cure(dev, [c]) or release_cure({}, [c]) for c in RELEASE)
            and CURE_BUDGET == 2 and KEY_BUDGET == 3),
           ("presentation and bookkeeping codes are disclosed in release, never in dev or without a mode",
            all(disclosed(rel, c) for c in ("render", "record-format", "pdf", "reader", "label", "selftest",
                                            "tool-fault", "docstring", "run-log"))
            and not any(disclosed(m, "render") for m in (dev, {}, None))),
           ("no `mode` key means dev; the mode line says so", mode({}) == "dev" and mode(None) == "dev"
            and "default" in mode_line({}) and "INVALID" in mode_line({"mode": "x"})),
           ("the release mode line says what RELEASE does: an integrity fault is self-cured (restore), never a stop "
            "(review item a)", all(release_kind(c) == "restore" for c in ("ownership", "tooling"))
            and "integrity" in mode_line(rel) and "restore" in mode_line(rel)
            and not re.search(r"integrity[^;]*stop the run", mode_line(rel))),
           ("split: a disclosed Finding leaves the blocking list only in release; a plain string always blocks",
            split(rel, [Finding("! a", "render"), "! b"]) == (["! b"], ["! a"])
            and split(dev, [Finding("! a", "render"), "! b"]) == (["! a", "! b"], [])
            and split(rel, [Finding("! c", "drift")]) == (["! c"], [])),
           ("a disclosed line is never a failure line to stops.py (no 'error:')",
            disclosed_line(Finding("! xelatex error: x", "pdf")) == "DISCLOSED[pdf] xelatex error - x"),
           ("S1: a prompt.py selftest FAIL in a fresh-reader check is disclosed; any other prompt FAIL, a "
            "crash, or a blocking script's FAIL is not",
            [str(f) for f in selftest_release("prompt", "  ok    x\n  FAIL  fresh-reader: under a delegating level "
                                                         "the decisions reader checks x\n", 1)]
            == ["prompt.py selftest: fresh-reader: under a delegating level the decisions reader checks x"]
            and selftest_release("prompt", "  FAIL  fresh-reader: the sheet gets the former pre-approval checks\n", 1) is None
            and selftest_release("prompt", "  FAIL  fresh-reader: the next report file is numbered\n  FAIL  lane B renders\n", 1) is None
            and selftest_release("prompt", "  FAIL  fresh-reader: the next report file is numbered\nTraceback (most recent call last):\n", 1) is None
            and selftest_release("prompt", "", 1) is None
            and selftest_release("fingerprint", "  FAIL  x\n", 1) is None
            and selftest_release("signoff", "  FAIL  fresh-reader: x\n", 1) is None
            and selftest_release("readers", "  FAIL  an uncommitted reader record refuses the gate\n", 1) is None
            and selftest_release("tests/doclint", "Traceback (most recent call last):\n", 1) is not None
            and selftest_release("prompt", "  FAIL  fresh-reader: the next report file is numbered\n", 0) is None),
           ("a mode other than release/dev, or one the installation does not have, is a hard config error",
            any(p.startswith("! mode") for p in problems(dict(fake, mode="lax")))
            and (installed_mode() not in MODES or any(p.startswith("! mode") for p in problems(
                dict(fake, mode=next(m for m in MODES if m != installed_mode())))))
            and not any(p.startswith("! mode") for p in problems(dict(fake, mode=installed_mode() or "dev")))),
           ]
    return out


def round_kind(round_dir):
    """'statements', 'diff' or 'full' from the round's TARGET.json (None if unreadable)."""
    try:
        return json.load(open(os.path.join(round_dir, "TARGET.json"))).get("_meta", {}).get("kind")
    except (OSError, ValueError):
        return None


# names a proof could read a docstring through: a project using one is never "comment-only"
DOC_READERS = re.compile(r"findDocString|getDocString|docString|addDocString|doc_string|DocString")
# DESIGN-M7: Verso docstrings are elaborated, so with `doc.verso` set (in a project Lean file or in the lakefile's
# options) a docstring is not inert and only Lean's "same" counts (the source basis is off)
VERSO = re.compile(r"doc\.verso")

# --- the comment-only lexer (DESIGN-M7 §2.2). It follows Lean 4's tokenizer (v4.35.0, read from
# Lean/Parser/Basic.lean and Init/Meta/Defs.lean): `whitespace` (`--` and `/-` are comments wherever whitespace
# is consumed; `/--`, `/-!` are doc comments whose body starts after the third character), `finishCommentBlock`
# (only `/-` and `-/` count inside), `strLitFnAux`, `charLitFnAux` (a `'` at a token start opens a char literal
# unless `''` follows), `rawStrLitFnAux` and `identFnAux` (`isIdFirst`/`isIdRest`: a `'` inside an identifier is a
# prime). Where it cannot be sure, the file is ambiguous and the change is NOT comment-only (fails closed).
CO_OPEN_OK = "()[]{}⟨⟩,"     # A1: after these, `--`/`/-` is taken as a comment (off in a strict project, review L1)


def _co_letterlike(c):
    """Lean's isLetterLike (Init/Meta/Defs.lean, v4.35.0)."""
    v = ord(c)
    return ((0x3b1 <= v <= 0x3c9 and v != 0x3bb) or (0x391 <= v <= 0x3a9 and v not in (0x3a0, 0x3a3))
            or 0x3ca <= v <= 0x3fb or 0x1f00 <= v <= 0x1ffe or 0x2100 <= v <= 0x214f or 0x1d49c <= v <= 0x1d59f
            or (0xc0 <= v <= 0xff and v not in (0xd7, 0xf7)) or 0x100 <= v <= 0x17f)


def _co_id_first(c):
    """Lean's isIdFirst: an ASCII letter, `_`, or a letter-like character."""
    return ("a" <= c <= "z") or ("A" <= c <= "Z") or c == "_" or _co_letterlike(c)


def _co_id_rest(c):
    """Lean's isIdRest: isIdFirst, an ASCII digit, `'`, `!`, `?`, or a subscript letter or digit."""
    v = ord(c)
    return (_co_id_first(c) or "0" <= c <= "9" or c in "'!?" or 0x2080 <= v <= 0x209c or 0x1d62 <= v <= 0x1d6a
            or v == 0x2c7c)


def _co_block_end(t, i):
    """i at `/-`: the index after the matching `-/` (finishCommentBlock: only `/-` nests and `-/` closes), or None
    when it is never closed. The body starts after the THIRD character, whatever it is (review of the M7 build, H1):
    Lean's `whitespace` reads `/-`, then steps over the next character unread (`s.next c i`: `-` and `!` make a doc
    comment, anything else a plain one), so the `/-` of `/-/-` is never an opener and `/-/- -/` is closed."""
    n, j, d = len(t), i + 3, 1
    while j < n:
        if t.startswith("-/", j):
            d -= 1; j += 2
            if d == 0:
                return j
            continue
        if t.startswith("/-", j):
            d += 1; j += 2; continue
        j += 1
    return None


def _co_string_end(t, i):
    """i at `"`: the index after the closing quote (a `\\` escapes the next character), or None (unterminated)."""
    j, n = i + 1, len(t)
    while j < n:
        if t[j] == "\\":
            j += 2; continue
        if t[j] == '"':
            return j + 1
        j += 1
    return None


_CO_HEX = "0123456789abcdefABCDEF"


def _co_char_end(t, i):
    """i at `'`: the index after the char literal Lean's charLitFnAux reads here, or None (not a literal: Lean
    either reads a token or fails to parse, and a file that does not compile is refused by the Lean stage)."""
    n = len(t)
    if i + 1 >= n:
        return None
    j = i + 1
    if t[j] == "\\":
        q = t[j + 1] if j + 1 < n else ""
        if q and q in "\\\"'rnt":
            j += 2
        elif q == "x" and all(x in _CO_HEX for x in t[j + 2:j + 4]) and len(t[j + 2:j + 4]) == 2:
            j += 4
        elif q == "u" and all(x in _CO_HEX for x in t[j + 2:j + 6]) and len(t[j + 2:j + 6]) == 4:
            j += 6
        else:
            return None
    else:
        j += 1
    return j + 1 if j < n and t[j] == "'" else None


def _co_interp_end(t, i, depth=0):
    """i at `"`, read as an interpolated string (interpolatedStrFn: `{…}` is a term, with its own strings, chars,
    comments and braces; `\\` escapes): the index after the closing quote, or None."""
    j, n = i + 1, len(t)
    while j < n:
        c = t[j]
        if c == "\\":
            j += 2; continue
        if c == '"':
            return j + 1
        if c == "{":
            k = _co_until_brace(t, j + 1, depth + 1)
            if k is None:
                return None
            j = k; continue
        j += 1
    return None


def _co_until_brace(t, i, depth):
    """Code from i to the matching `}` (inside an interpolation): the index after it, or None."""
    n, b = len(t), 0
    if depth > 8:
        return None
    while i < n:
        if t.startswith("--", i):
            k = t.find("\n", i); i = n if k == -1 else k; continue
        if t.startswith("/-", i):
            k = _co_block_end(t, i)
            if k is None:
                return None
            i = k; continue
        c = t[i]
        if c == '"':
            k = _co_interp_end(t, i, depth)
            if k is None:
                return None
            i = k; continue
        if c == "'" and not (i and _co_id_rest(t[i - 1])) and not t.startswith("''", i):
            k = _co_char_end(t, i)
            if k:
                i = k; continue
        if c == "{":
            b += 1
        elif c == "}":
            if b == 0:
                return i + 1
            b -= 1
        i += 1
    return None


_CO_NUMBER = re.compile(r"0[xX][0-9a-fA-F_]*|0[bB][01_]*|0[oO][0-7_]*"
                        r"|[0-9][0-9_]*(?:\.(?!\.)[0-9_]*)?(?:[eE][+-]?[0-9][0-9_]*)?")
_CO_RAW = re.compile(r'r#*"')
# a literal's (string, char, «name») newline in the code view: a sentinel, escaped so no text maps onto another
# (review of the M7 build, L1: a raw NUL in a string read the same as a newline)
_CO_LIT = {0: "\x00\x00", 10: "\x00n"}
# review of the M7 build, L2: an uncertain `'` whose two readings differ locally (a char literal or `''` follows) is
# "live"; with up to this many live ones every mixed reading is compared, with more the file is ambiguous
_CO_LIVE_MAX = 4


def _co_read(text, policy="lean", open_ok=CO_OPEN_OK):
    """One reading of `text`: (code view, [(kind, start, end)] of its comments and strings, [ambiguity], the number
    of live uncertain `'`). The code view is `text` with every comment character blanked to a space (newlines kept: L7,
    and review L3, every code character keeps its column) and a newline inside a string or char literal replaced by
    a sentinel. A `'` right after a code character other than an ASCII identifier character is uncertain (a user
    token may hold it, as `⁻¹'` does; the identifier tables differ between Lean versions); `policy` says how this
    reading takes it: "lean" as Lean's tokenizer does, "code" as part of a name or token, "char" as a char literal
    when one is there; a tuple of "prime"/"char" gives the choice for each live one in turn (review of the M7
    build, L2: mixed readings), "lean" past its end. Only a live `'` (a char literal or `''` follows it) is
    counted: for any other the two choices read alike."""
    out, spans, amb = [], [], []
    n, i, unc = len(text), 0, 0
    prev = None         # the code character just before i (None after whitespace or a comment: a token starts)
    ident = False       # i continues an identifier (its last character was an isIdRest one)
    idcont = False      # a `.` at i followed by an identifier start continues the identifier (isIdCont)
    while i < n:
        c = text[i]
        if c in "\n \t\r":
            out.append(c); i += 1; prev = None; ident = idcont = False; continue
        if text.startswith("--", i) or text.startswith("/-", i):
            if prev is not None and prev not in open_ok:
                amb.append(f"`{text[i:i + 2]}` right after code at offset {i}: a notation token could contain it")
            if text.startswith("/--/", i):
                amb.append(f"`/--/` at offset {i}")
            if c == "-":
                k = text.find("\n", i)
                k = n if k == -1 else k
            else:
                k = _co_block_end(text, i)
                if k is None:
                    amb.append(f"a comment at offset {i} is never closed")
                    k = n
            spans.append(("comment", i, k))
            out.append("".join("\n" if x == "\n" else " " for x in text[i:k]))
            i = k; prev = None; ident = idcont = False; continue
        if c == '"':
            k = _co_string_end(text, i)
            if k is None:
                amb.append(f"a string at offset {i} is never closed")
                k = n
            if "{" in text[i:k] and _co_interp_end(text, i) != k:
                amb.append(f"a string at offset {i} reads differently as an interpolated string")
            spans.append(("string", i, k))
            out.append(text[i:k].translate(_CO_LIT))
            i = k; prev = '"'; ident = idcont = False; continue
        if c == "'":
            if ident and prev is not None and prev < "\x80":
                take = "prime"              # inside an ASCII identifier: certain
            elif prev is None or prev in open_ok:
                take = "char"               # a token start: certain
            else:
                lean_take = "prime" if ident else "char"
                if text.startswith("''", i) or _co_char_end(text, i) is not None:
                    take = (policy[unc] if unc < len(policy) else lean_take) if isinstance(policy, tuple) else \
                        {"code": "prime", "char": "char"}.get(policy, lean_take)
                    unc += 1
                else:
                    take = lean_take
            if take == "char":
                if text.startswith("''", i):
                    out.append("''"); i += 2; prev = "'"; ident = idcont = False; continue
                k = _co_char_end(text, i)
                if k is not None:
                    out.append(text[i:k].translate(_CO_LIT))
                    i = k; prev = "'"; ident = idcont = False; continue
            out.append(c); i += 1; prev = c; idcont = ident
            continue
        if c == "r" and _CO_RAW.match(text, i) and not (ident and prev is not None and prev < "\x80"):
            amb.append(f"a raw string at offset {i}")
        if ident and _co_id_rest(c):
            pass
        elif c == "." and idcont and i + 1 < n and (_co_id_first(text[i + 1]) or text[i + 1] == "«"):
            ident = idcont = False
        elif c == "«":
            k = text.find("»", i + 1)
            if k == -1:
                amb.append(f"a name at offset {i} is never closed")
                k = n - 1
            out.append(text[i:k + 1].translate(_CO_LIT))
            i = k + 1; prev = "»"; ident = False; idcont = True; continue
        elif not ident and "0" <= c <= "9":
            m = _CO_NUMBER.match(text, i)
            out.append(m.group(0)); i = m.end(); prev = m.group(0)[-1]; ident = idcont = False; continue
        elif _co_id_first(c):
            ident = idcont = True
        else:
            ident = idcont = False
        out.append(c); prev = c; i += 1
    return "".join(out), spans, amb, unc


def _co_lex(text, strict=False):
    """(code view with trailing blanks and blank lines dropped, [ambiguity]) of the Lean `text` (DESIGN-M7)."""
    open_ok = "" if strict else CO_OPEN_OK
    code, spans, amb, unc = _co_read(text, "lean", open_ok)
    if unc:
        # review M4: an uncertain `'` -- every reading must place the comments and strings alike; review of the M7
        # build, L2: every mixed reading too. Each reading is a choice per live `'` it meets (a choice can change
        # which later `'` are live), so the readings are enumerated as a tree, at most 2**_CO_LIVE_MAX of them
        work, done = [()], 0
        while work:
            pol = work.pop()
            r_ = _co_read(text, pol, open_ok)
            if r_[3] > len(pol):
                work += [pol + ("prime",), pol + ("char",)]
                continue
            done += 1
            if r_[1] != spans:
                amb.append("a `'` right after code reads either as a char literal or as part of a name or token, "
                           "and the readings place comments or strings differently")
                break
            if done >= 2 ** _CO_LIVE_MAX and work:
                amb.append("`'` right after code each read either as a char literal or as part of a name or token: "
                           "too many readings to compare")
                break
    for m in re.finditer(r"«[^»]*»", text):
        if any(x in m.group(0) for x in ("--", "/-", "-/", '"', "'")):
            amb.append(f"the name {m.group(0)[:30]!r}")
    lines = [l.rstrip(" \t\r") for l in code.split("\n")]
    return "\n".join(l for l in lines if l.strip(" \t\r")), amb


def code_only(text, strict=False):
    """The Lean `text` with comments and docstrings removed, as DESIGN-M7 §2.2 reads it: every comment character
    blanked to a space, so each code character keeps its column (tactic blocks are column-sensitive), then
    trailing blanks and lines left empty dropped. String and char literal CONTENT is kept (unlike
    phase0.strip_comments), a newline inside one as a sentinel, so a change inside a string is a code change.
    `strict`: the project declares a token holding a comment marker (review L1), so `(--` is ambiguous too."""
    return _co_lex(text, strict)[0]


def lexer_ambiguous(text, strict=False):
    """Why code_only's lexer may mistake code for a comment in `text`, or None (the first reason): `--` or `/-`
    right after code (a notation token may hold it: A1), `/--/` (A2), a string that reads differently as an
    interpolated string (A3), a `«…»` name holding `--`, `/-`, `-/` or a quote, a raw string (A4), an unterminated
    comment, string or name (review L2), or a `'` whose readings as a char literal or a prime disagree (review M4).
    The Lean stage compares what the .olean keeps, which is not everything (an `example`, a `#guard`), and on the
    source basis the lexer alone vouches for binder annotations and names: a change it may misread is refused."""
    amb = _co_lex(text, strict)[1]
    return amb[0] if amb else None


_CO_SYNTAX_CMD = re.compile(r"(?<![\w.'])(?:notation\d*|syntax|macro|macro_rules|elab|elab_rules|infixl?|infixr"
                            r"|prefix|postfix|declare_syntax_cat)(?![\w'!?])")


def _co_marker_token(text):
    """Review L1: does `text` declare syntax (notation, syntax, macro, infix, …) and hold, in its code, a string
    literal containing `--` or `/-`? Then a user token may start with a bracket and hold a comment marker
    (`notation "[--" x "]"`), and the bracket exemption of A1 is off for the whole project."""
    code = code_only(text)
    return bool(_CO_SYNTAX_CMD.search(code)) and bool(re.search(r'"[^"\n\x00]*(?:--|/-)', code))


def comment_only_since(cfg, base, repo=None, lean_cmd=None):
    """(True, [changed file]) when every change from commit `base` to the working tree touches only
    comments and docstrings of the project's Lean files; else (False, [reason]). The 2-tuple form of
    comment_only_detail, which decides (and says on which basis)."""
    d = comment_only_detail(cfg, base, repo, lean_cmd)
    return d["ok"], d["what"]


def comment_only_detail(cfg, base, repo=None, lean_cmd=None):
    """Are all changes from commit `base` to the working tree comments and docstrings only? A dict:
      ok      the answer
      what    [changed file] when ok, else [reason]
      basis   when ok and something changed: "compiled" (Lean found the compiled modules identical in every part
              olean_parts.lean compares) or "source" (DESIGN-M7: the code with comments removed is identical, and
              Lean found only the compiled bytes different, every declaration, type and value hash and
              extension part equal); else None
      lean    the Lean stage's reasons on the source basis (each of kind "layout"), else []
    Fails closed: a git error, a file outside `lean_files` (a build file, a new or deleted file), a file whose code
    differs with its comments removed (code_only), one the lexer cannot read for sure (lexer_ambiguous), a project
    file naming a docstring reader (DOC_READERS: a proof could depend on a docstring), or a Lean comparison that
    finds a declaration, type, value or extension part different, or cannot run (a version that does not
    compile, a failed build), or a reason without a kind, each make it False. The working tree is compared, so
    uncommitted edits count.

    Two stages. The text stage (_comment_only_text) runs first; any reason there and Lean is not run. Then the Lean
    stage, lean_identical: every changed file is compiled before and after, and the compiled modules must be
    identical in every part except docstrings and source positions -- every declaration's type and value
    (statements, proofs, definition bodies), the declarations themselves, imports, attributes, notations and
    options' effects. Lean only vetoes: when its only finding is that the compiled bytes differ (kind "layout",
    with O1's field when it names one that identical source can produce), the change is comment-only on the
    source basis, disclosed as such, unless the project elaborates docstrings (Verso). Review of fix-mini2 H1
    stands: when Lean cannot run, nothing but the lexer vouches, so it is refused. `lean_cmd`: the command that
    runs Lean (default `lake env lean`, after `lake build`; the Lean selftest passes plain `lean` on a core-only
    fixture)."""
    repo = repo or REPO
    why, changed, texts = _comment_only_text(cfg, base, repo)
    if why or not changed:
        return {"ok": not why, "what": why or changed, "basis": None, "lean": []}
    why = lean_identical(repo, texts, lean_cmd)
    if not why:
        return {"ok": True, "what": changed, "basis": "compiled", "lean": []}
    if all(reason_kind(w) == "layout" for w in why):
        v = _verso(cfg, repo)
        if v is None:
            return {"ok": True, "what": changed, "basis": "source", "lean": list(why)}
        why = list(why) + [v]
    return {"ok": False, "what": list(why), "basis": None, "lean": []}


def _verso(cfg, repo):
    """DESIGN-M7 (review L4): the reason the project elaborates docstrings (`doc.verso` in a project Lean file or
    in the lakefile, whose `leanOptions` set it for every module), or None."""
    for rel in list(cfg.get("lean_files", [])) + ["lakefile.lean", "lakefile.toml"]:
        try:
            t = open(os.path.join(repo, rel), encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        if VERSO.search(t):
            return (f"{rel}: sets `doc.verso`, so docstrings are elaborated: only identical compiled modules make a "
                    "change comment-only")
    return None


def _comment_only_text(cfg, base, repo):
    """The text stage of comment_only_detail: ([reason], [changed file], {file: (old, new)})."""
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    r = git("diff", "--name-status", "--no-renames", base, "--")
    u = git("ls-files", "--others", "--exclude-standard")
    if r.returncode != 0 or u.returncode != 0:
        return [f"git could not compare {base} with the working tree: {(r.stderr or u.stderr).strip()[:160]}"], [], {}
    lean = set(cfg.get("lean_files", []))
    why, changed, texts, edits = [], [], {}, []
    for line in r.stdout.splitlines():
        st, _, path = line.partition("\t")
        if path.startswith(".formalization-work/") or path.startswith("deliverables/"):
            continue
        if path not in lean:
            why.append(f"{path}: not a project Lean file ({st})")
            continue
        if st != "M":
            why.append(f"{path}: {st} (added or deleted), not an edit")
            continue
        old = git("show", f"{base}:{path}")
        try:
            new = open(os.path.join(repo, path), encoding="utf-8").read()
        except OSError as e:
            why.append(f"{path}: cannot read ({e})"); continue
        if old.returncode != 0:
            why.append(f"{path}: not in {base}"); continue
        edits.append((path, old.stdout, new))
    current = {}
    for rel in lean:
        try:
            current[rel] = open(os.path.join(repo, rel), encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            pass
    # review L1: a project token holding a comment marker (`notation "[--" x "]"`) turns the bracket exemption off
    strict = any(_co_marker_token(t) for t in list(current.values()) + [o for _, o, _ in edits])
    for path, old_t, new in edits:
        if code_only(old_t, strict) != code_only(new, strict):
            why.append(f"{path}: its code differs, not only its comments")
        else:
            amb = lexer_ambiguous(old_t, strict) or lexer_ambiguous(new, strict)
            if amb:
                why.append(f"{path}: {amb}: the text filter cannot tell code from comment there, and the "
                           f"compiled module does not keep everything (an `example`): not comment-only")
        changed.append(path)
        texts[path] = (old_t, new)
    for path in u.stdout.split():
        if path in lean:
            why.append(f"{path}: untracked")
    for rel in lean:
        p_ = os.path.join(repo, rel)
        if os.path.exists(p_) and DOC_READERS.search(code_only(open(p_, encoding="utf-8").read())):
            why.append(f"{rel}: its code reads docstrings, so a docstring can change what it proves")
    return why, changed, texts


OLEAN_PARTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "olean_parts.lean")
# O1: the diagnostic run only when the compiled bytes differ while every type and value hash agrees (_parts_differ).
# It compares every field of every constant and names each difference; it decides whether that reason can be a
# byte-layout one (bytes_only_kind). Review of the M7 build, H2: it fails closed -- when it fails, times out, has no
# budget left or prints nothing complete, the reason is "not-run" (a review round, never a stop)
OLEAN_DIFF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "olean_diff.lean")
# attack review L6: the diagnostic's whole budget per refusal (one lean_identical call), in seconds; past it the
# bytes-only reason is "not-run" (review of the M7 build, H2)
OLEAN_DIFF_BUDGET = 60


def _run_group(argv, cwd, timeout):
    """subprocess.run(argv, capture_output=True, text=True, timeout=timeout), but in a process group of its own:
    on a timeout (or anything else that leaves this call while it runs) the whole group is killed, not only its
    leader. `lake env lean` runs `lean` as a child, which a plain run's kill leaves running, orphaned, beside the
    next comparison (REREVIEW-M7 NEW-2: host memory). Raises what subprocess.run raises."""
    import signal
    p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(p.pid, signal.SIGKILL)     # the leader is not reaped yet, so its pid is still this group's
        except OSError:
            pass
        try:
            p.communicate(timeout=10)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        raise
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


class LeanReason(str):
    """A reason of lean_identical, with its kind (DESIGN-M7 §3.1); a plain `str` everywhere it is joined or printed:
      "semantic"  a declaration, a type or value, or an extension part differs; not a .lean file
      "layout"    only the compiled constants' bytes differ (every declaration, type and value hash and every
                  extension part equal), and O1 ran and every difference it names is one identical source can
                  produce (review M1)
      "not-run"   Lean could not compare: a failed build, a version that does not compile, olean_parts failing, or
                  (bytes only) O1 not run, failed, timed out or printed no complete answer (review of the M7 build, H2)
    A reason without a kind (a plain str) counts as "semantic" (reason_kind): fails closed."""
    def __new__(cls, text, kind):
        r = super().__new__(cls, text)
        r.kind = kind
        return r


def reason_kind(w):
    """The kind of a lean_identical reason; anything without one is "semantic" (fails closed)."""
    k = getattr(w, "kind", None)
    return k if k in ("semantic", "layout", "not-run") else "semantic"


# the bytes-only reason (_parts_differ), and O1's texts that identical source can produce (review M1): "no field
# differs ...: only the serialized form (sharing) differs" (printed only after every field of every constant compared
# equal) and "binder names (not their annotations) ...". O1 names every difference, joined by "; "; the reason is
# "layout" only when each one is of these two (review of the M7 build, H2); any other (imports, the module flag,
# declaration order, auxiliary names, their number, universe parameter names, the kind, reducibility hints, safety,
# the mutual block, inductive, constructor or recursor data, binder annotations, binder names or annotations
# undecided) makes it "semantic"; no O1 text (not run, failed, timed out) makes it "not-run"
BYTES_ONLY = "its declarations or imports differ (compiled form)"
O1_LAYOUT = ("no field differs", "binder names (not their annotations)")


def bytes_only_kind(reason):
    """"layout" when `reason` is _parts_differ's bytes-only reason and every O1 finding in it is benign, "not-run"
    when it carries no O1 text (review of the M7 build, H2: O1 failing never accepts), else "semantic" (re-derived
    from the text, so a cached reason is judged by the current rule)."""
    _, sep, rest = str(reason).partition(": " + BYTES_ONLY)
    if not sep:
        return "semantic"
    if not rest:
        return "not-run"
    if not rest.startswith(": ") or not rest[2:].strip():
        return "semantic"
    return "layout" if all(f.startswith(O1_LAYOUT) for f in rest[2:].split("; ")) else "semantic"


def lean_identical(repo, texts, lean_cmd=None):
    """[] when, for every file of `texts` ({path relative to repo: (old text, new text)}), the old
    and new texts compile to modules identical in every part olean_parts.lean compares; else the
    reasons (also when Lean cannot run: fails closed). Each version is compiled on its own, under a
    scratch root at the file's own relative path, so its module name (and private names) is the
    real one, against the project's current build of its imports. That suffices: by induction over
    the import order, if every changed file compiles identically against the same imports, the
    whole project does (an unchanged file has identical text and identical imports).
    The default `lean_cmd` (`lake env lean`) first runs `lake build` on the changed modules, so
    their imports are current.
    A result is cached in work_dir/../comment-only-cache.json by the texts' hash."""
    import tempfile, shutil, hashlib
    cmd = list(lean_cmd or ["lake", "env", "lean"])
    key = hashlib.sha256(json.dumps([cmd, sorted(texts.items()),
                                     open(OLEAN_PARTS, encoding="utf-8").read()]).encode()).hexdigest()
    cache = os.path.join(repo, FW, "comment-only-cache.json")
    # DESIGN-M7: a bytes-only result is cached too, under its own key (it also depends on olean_diff.lean), and its
    # reasons are judged again by the current rule when read
    try:
        _o1 = open(OLEAN_DIFF, encoding="utf-8").read()
    except OSError:
        _o1 = ""
    lkey = hashlib.sha256((key + _o1).encode()).hexdigest()
    try:
        c0 = json.load(open(cache))
        if c0.get(key) == "same":
            return []
        lay = (c0.get(lkey) or {}).get("layout") if isinstance(c0.get(lkey), dict) else None
        if isinstance(lay, list) and lay and all(isinstance(x, str) for x in lay):
            return [LeanReason(x, bytes_only_kind(x)) for x in lay]
        # review of the M7 build, L5: a refusal Lean gave on these texts is read back too, as a refusal (never as
        # "same" or layout), so the report's renders do not compile the same refused texts again
        ref = (c0.get(lkey) or {}).get("refused") if isinstance(c0.get(lkey), dict) else None
        # REREVIEW-M7 NEW-1: a refusal cached before only definite results were is not read back when it holds a
        # not-run reason (O1's absence): Lean compares again
        if (isinstance(ref, list) and ref and all(isinstance(x, str) for x in ref)
                and not any(bytes_only_kind(x) == "not-run" for x in ref)):
            return [LeanReason(x, "semantic") for x in ref]
    except (OSError, ValueError, AttributeError):
        pass
    mods = [t[:-len(".lean")].replace("/", ".") for t in sorted(texts) if t.endswith(".lean")]
    if lean_cmd is None:
        # the changed modules (hence their imports) as built from the working tree
        try:
            b = subprocess.run(["lake", "build", *mods], cwd=repo, capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError) as e:     # review of the M7 build, L4: no `lake` on PATH
            return [LeanReason(f"Lean comparison not run: `lake build` could not run ({e})", "not-run")]
        if b.returncode != 0:
            return [LeanReason("Lean comparison not run: `lake build` failed: " + (b.stdout + b.stderr).strip()[-300:],
                               "not-run")]
    why, env_fail = [], False      # env_fail: a compile or olean_parts failure (perhaps transient): not cached
    import time
    diag_until = time.monotonic() + OLEAN_DIFF_BUDGET
    d = tempfile.mkdtemp(prefix="comment-only-lean-")
    try:
        for path, (old, new) in sorted(texts.items()):
            mod = path[:-len(".lean")].replace("/", ".") if path.endswith(".lean") else None
            if not mod:
                why.append(LeanReason(f"{path}: not a .lean file", "semantic")); continue
            parts = []
            for tag, txt in (("old", old), ("new", new)):
                root = os.path.join(d, tag, "src")
                src = os.path.join(root, path)
                os.makedirs(os.path.dirname(src), exist_ok=True)
                open(src, "w", encoding="utf-8").write(txt)
                ol = os.path.join(d, tag, "m.olean")
                out = os.path.join(d, tag, "parts-" + mod)
                try:
                    c = _run_group(cmd + ["--root=" + root, "-o", ol, src], repo, 7200)
                    p = c.returncode == 0 and _run_group(cmd + ["--run", OLEAN_PARTS, ol, out, mod], repo, 600)
                except (OSError, subprocess.SubprocessError) as e:
                    env_fail = True
                    why.append(LeanReason(f"{path}: Lean comparison could not run ({e})", "not-run")); break
                if c.returncode != 0:
                    env_fail = True
                    why.append(LeanReason(f"{path}: the {tag} version does not compile, so it cannot be compared: "
                                          + " ".join((c.stdout + c.stderr).split())[:200], "not-run")); break
                if p.returncode != 0:
                    env_fail = True
                    why.append(LeanReason(f"{path}: olean_parts failed on the {tag} version: "
                                          + " ".join((p.stdout + p.stderr).split())[:200], "not-run")); break
                parts.append(out)
            if len(parts) < 2:
                continue
            ols = [os.path.join(d, tag, "m.olean") for tag in ("old", "new")]
            why += _parts_differ(path, *parts, diag=lambda ols=ols: _olean_diff(
                cmd, repo, *ols, timeout=diag_until - time.monotonic()))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if not why:
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            try:
                c_ = json.load(open(cache))
            except (OSError, ValueError):
                c_ = {}
            c_[key] = "same"
            json.dump(c_, open(cache, "w"))
        except OSError:
            pass
    elif all(reason_kind(w) == "layout" for w in why):
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            try:
                c_ = json.load(open(cache))
            except (OSError, ValueError):
                c_ = {}
            c_[lkey] = {"layout": [str(w) for w in why]}
            json.dump(c_, open(cache, "w"))
        except OSError:
            pass
    elif not env_fail and not any(reason_kind(w) == "not-run" for w in why):
        # review of the M7 build, L5: what _parts_differ refused (a type, value or part, or O1's answer) is cached
        # as a refusal; a compile or olean_parts failure is not (it may be the host's, not the texts'), and neither
        # is O1's absence -- a timeout, a kill, a budget run out, a failure (REREVIEW-M7 NEW-1: only a definite
        # result is cached)
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            try:
                c_ = json.load(open(cache))
            except (OSError, ValueError):
                c_ = {}
            c_[lkey] = {"refused": [str(w) for w in why]}
            json.dump(c_, open(cache, "w"))
        except OSError:
            pass
    return why


def _olean_diff(cmd, repo, old, new, timeout=OLEAN_DIFF_BUDGET):
    """O1: every difference olean_diff.lean finds between the two compiled modules, joined by "; " (the ones
    identical source cannot produce first, so a cut at 300 characters never hides one), or None when it cannot run,
    fails, times out (`timeout` seconds: what is left of the refusal's budget; none left: not run) or prints no
    complete answer (each finding on a DIFF line, then END with their number). None makes the reason "not-run"
    (review of the M7 build, H2)."""
    if not timeout or timeout < 1:
        return None
    try:
        r = _run_group(cmd + ["--run", OLEAN_DIFF, old, new], repo, min(timeout, OLEAN_DIFF_BUDGET))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if r.returncode != 0:
        return None
    lines = r.stdout.splitlines()
    found = [" ".join(l[len("DIFF\t"):].split()) for l in lines if l.startswith("DIFF\t")]
    ends = [l for l in lines if l.startswith("END\t")]
    if not found or not all(found) or not ends or ends[-1] != f"END\t{len(found)}":
        return None
    bad = [f for f in found if not f.startswith(O1_LAYOUT)]
    if bad:
        return "; ".join(bad + [f for f in found if f not in bad])[:300]
    if len(found) > 1 and any(f.startswith(O1_LAYOUT[0]) for f in found):
        return None     # "no field differs" beside a difference: not a consistent answer
    text = "; ".join(found)
    if len(text) <= 300:
        return text
    return f"{O1_LAYOUT[1]} differ, and nothing else does, in {len(found)} places"


def _parts_differ(path, a, b, diag=None):
    """The reasons the parts olean_parts.lean wrote into directories a and b differ ([] if none). `diag`: called
    only when the constants' bytes differ while every type and value hash agrees; a string it returns is added to
    that reason (O1); anything else -- None, an exception -- leaves today's text, of kind "not-run" (review of the
    M7 build, H2: O1 failing never accepts)."""
    def index(d):
        rows = [l.split("\t") for l in open(os.path.join(d, "index.tsv"), encoding="utf-8").read().splitlines()]
        return ({r[1]: r[2:] for r in rows if r[0] == "const"},
                {r[1]: r[2:] for r in rows if r[0] == "ext"}, [r[1] for r in rows if r[0] == "skip"])
    def data(d, f):
        return open(os.path.join(d, f), "rb").read()
    (ca, ea, _), (cb, eb, _) = index(a), index(b)
    why = []
    if set(ca) != set(cb):
        why.append(LeanReason(f"{path}: declarations differ: " + ", ".join(sorted(set(ca) ^ set(cb)))[:300], "semantic"))
    else:
        diff = sorted(n for n in ca if ca[n] != cb[n])
        if diff:
            why.append(LeanReason(f"{path}: the type or value of {', '.join(diff)[:300]} differs", "semantic"))
        elif data(a, "constants.olean") != data(b, "constants.olean"):
            extra = None
            if diag is not None:
                try:
                    extra = diag()
                except Exception:       # noqa: BLE001 -- fails closed: no O1 text is "not-run"
                    extra = None
            r_ = f"{path}: {BYTES_ONLY}" + (f": {extra}" if isinstance(extra, str) and extra.strip() else "")
            why.append(LeanReason(r_, bytes_only_kind(r_)))     # DESIGN-M7: the one reason that can be "layout"
    for e in sorted(set(ea) | set(eb)):
        if e not in ea or e not in eb or ea[e][0] != eb[e][0] or data(a, ea[e][1]) != data(b, eb[e][1]):
            why.append(LeanReason(f"{path}: its {e} entries differ (attributes, notation, compiled code or similar)",
                                  "semantic"))
    return why


def _parts_differ_controls():
    """O1 (Lean-free): _parts_differ on synthetic part directories. The diagnostic is asked only when the constants'
    bytes differ while every hash agrees; what it returns is appended; when it fails, raises or prints nothing the
    reason's text is exactly today's (review M7) and its kind "not-run" (review of the M7 build, H2); a real
    difference never calls it; equal parts give []. _olean_diff against a stand-in for Lean (a shell script): a
    failure, a missing or wrong END, an empty finding, a timeout give None; every finding is kept, the ones identical
    source cannot produce first (no stop at the first difference)."""
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="parts-differ-")
    out = []
    try:
        def mk(name, const_bytes, idx_extra=""):
            p = os.path.join(d, name)
            os.makedirs(p)
            open(os.path.join(p, "constants.olean"), "wb").write(const_bytes)
            open(os.path.join(p, "ext0.olean"), "wb").write(b"e")
            open(os.path.join(p, "index.tsv"), "w").write("ext\tLean.x\t1\text0.olean\nconst\tA.a\t1\t2\n" + idx_extra)
            return p
        a, b, c = mk("a", b"x"), mk("b", b"y"), mk("c", b"x")
        today = "F.lean: its declarations or imports differ (compiled form)"
        calls = []

        def ok_diag():
            calls.append(1)
            return "binder names or annotations in the value of `A.a` differ"

        def boom():
            raise OSError("lean")
        r_ok = _parts_differ("F.lean", a, b, diag=ok_diag)
        r_none = _parts_differ("F.lean", a, b, diag=lambda: None)
        r_boom = _parts_differ("F.lean", a, b, diag=boom)
        r_nodiag = _parts_differ("F.lean", a, b)
        r_same = _parts_differ("F.lean", a, c, diag=ok_diag)
        hb = mk("h", b"y", "")
        open(os.path.join(hb, "index.tsv"), "w").write("ext\tLean.x\t1\text0.olean\nconst\tA.a\t1\t3\n")
        n0 = len(calls)
        r_real = _parts_differ("F.lean", a, hb, diag=ok_diag)
        out.append(("O1: the bytes differ with every hash equal: the diagnostic's field is added to the same refusal; "
                    "it fails, raises or says nothing: exactly today's reason; equal parts: no reason, no diagnostic",
                    r_ok == [today + ": binder names or annotations in the value of `A.a` differ"]
                    and r_none == r_boom == r_nodiag == [today] and r_same == [] and len(calls) == 1))
        out.append(("O1 (review of the M7 build, H2): with no O1 text (it failed, raised, said nothing or was not "
                    "asked) the bytes-only reason is \"not-run\", never layout",
                    [reason_kind(x) for x in r_none + r_boom + r_nodiag] == ["not-run"] * 3))
        out.append(("O1: a real type or value difference never asks the diagnostic",
                    r_real == ["F.lean: the type or value of A.a differs"] and len(calls) == n0))
        out.append(("O1: _olean_diff fails soft (a missing command gives None, never an exception)",
                    _olean_diff(["/nonexistent-lean-binary"], d, "x", "y") is None))
        # attack review L6: past the budget the diagnostic is not run (a command that would hang: `sleep`)
        import time
        t0 = time.monotonic()
        r_spent = _olean_diff(["sleep", "30"], d, "x", "y", timeout=0)
        r_slow = _olean_diff(["sh", "-c", "exec sleep 5", "sh"], d, "x", "y", timeout=1.5)
        out.append(("O1 (attack review L6): no budget left: not run; a run past its budget: None (not-run), "
                    "within the time left", r_spent is None and r_slow is None and time.monotonic() - t0 < 4))
        # review of the M7 build, H2: a stand-in for `lean --run olean_diff.lean` printing what FAKE_OUT holds
        fake = os.path.join(d, "fakelean.sh")
        open(fake, "w").write('#!/bin/sh\nprintf "%b" "$FAKE_OUT"\nexit "${FAKE_RC:-0}"\n')
        os.chmod(fake, 0o755)
        nm, an = ("binder names (not their annotations) in the type of `A.a` differ",
                  "binder annotations in the value of `A.b` differ")
        sh = "no field differs (…): only the serialized form (sharing) differs"

        def fk(o, rc=0):
            os.environ["FAKE_OUT"], os.environ["FAKE_RC"] = o, str(rc)
            try:
                return _olean_diff([fake], d, "x", "y")
            finally:
                os.environ.pop("FAKE_OUT", None); os.environ.pop("FAKE_RC", None)
        f_two = fk(f"DIFF\t{nm}\nDIFF\t{an}\nEND\t2\n")
        f_one = fk(f"DIFF\t{nm}\nEND\t1\n")
        f_sh = fk(f"DIFF\t{sh}\nEND\t1\n")
        f_bad = [fk(f"DIFF\t{nm}\nEND\t1\n", rc=1), fk(f"DIFF\t{nm}\n"), fk(f"DIFF\t{nm}\nDIFF\t{an}\nEND\t1\n"),
                 fk("DIFF\t \nEND\t1\n"), fk("END\t0\n"), fk(f"DIFF\t{sh}\nDIFF\t{nm}\nEND\t2\n")]
        f_long = fk("".join(f"DIFF\t{nm.replace('A.a', 'A.a' + str(k))}\n" for k in range(20)) + "END\t20\n")
        kd = lambda x: bytes_only_kind(today + ": " + x) if x else bytes_only_kind(today)
        out.append(("O1 (review of the M7 build, H2): every finding is kept, the one identical source cannot produce "
                    "first, and it decides (a names-only finding before it masks nothing); one names-only finding or "
                    "the sharing text alone is layout; a failure, no END, a wrong count, an empty finding, no finding "
                    "or the sharing text beside a finding is None (not-run); many names-only findings stay layout",
                    f_two == f"{an}; {nm}" and kd(f_two) == "semantic" and kd(f_one) == "layout"
                    and kd(f_sh) == "layout" and f_bad == [None] * 6 and kd(None) == "not-run"
                    and kd(f_long) == "layout" and len(f_long) <= 300
                    and bytes_only_kind(today + ": " + nm + "; the kind of `A.b` differs (def, opaque)") == "semantic"
                    and bytes_only_kind(today + ": " + (nm + "; ") * 20 + "imports differ") == "semantic"))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


# DESIGN-M7: the lexer's unit cases (the design's tests_m7 and the review's adv.py), each (name, old, new, the text
# stage's verdict "same", strict). strict: the project declares a token holding a comment marker (review L1).
_M7_B = ("/-- Lemma 1. -/\ntheorem a (n : Nat) (h : 0 < n) : 0 < n := by\n  exact h\n"
         "def s : String := \"x -- y\"\ndef ab := 1\n")
_M7_CASES = [
    # accepted: comments and docstrings only
    ("docstring text and a new line comment", _M7_B, _M7_B.replace(
        "/-- Lemma 1. -/", "/-- Lemma 1. True only vacuously:\nits hypothesis never holds. -/\n-- note"), True),
    ("trailing line comment added", _M7_B, _M7_B.replace("  exact h\n", "  exact h  -- closes it\n"), True),
    ("module doc added", _M7_B, "/-! # Module\nnotes -/\n\n" + _M7_B, True),
    ("nested block comment edited", _M7_B + "/- a /- b -/ c -/\n", _M7_B + "/- a /- bbb -/ ccc\n more -/\n", True),
    ("docstring with nested comment and quotes", _M7_B, _M7_B.replace("/-- Lemma 1. -/", '/-- Lemma "1" /- x -/ `a` -/'),
     True),
    ("blank lines", _M7_B, _M7_B.replace("def ab", "\n\ndef ab"), True),
    ("comment lines between code lines in a tactic block", "theorem t : True := by\n  skip\n  trivial\n",
     "theorem t : True := by\n  skip\n  -- why\n  /- more\n  -/\n  trivial\n", True),
    ("image token '' and primes", "def f' := Set.image f '' s\n", "def f' := Set.image f '' s -- img\n", True),
    ("char literal of a quote", "def c := '\"'\n-- x\n", "def c := '\"'\n-- y\n", True),
    ("escaped char literal", "def c := '\\x41'\n-- x\n", "def c := '\\x41'\n-- yy\n", True),
    ("L7 a multi-line comment's first line edited: the code after it keeps its column",
     "  tac1\n  /- x\n  -/ tac2\n", "  tac1\n  /- xxxxxxx\n  -/ tac2\n", True),
    ("review: CRLF line ends, a comment edited", "def x := 1 -- a\r\ndef y := 2\r\n", "def x := 1 -- bb\r\ndef y := 2\r\n",
     True),
    ("review: CRLF and LF line ends (Lean normalizes them)", "def x := 1\r\n", "def x := 1\n", True),
    ("review: `---`", "def x := 1 --- a\n", "def x := 1 --- b\n", True),
    ("review: a comment inside a syntax quotation", "def q := `(1 -- a\n)\n", "def q := `(1 -- b\n)\n", True),
    ("review: a docstring becomes a plain comment", "/-- doc -/\ndef x := 1\n", "/- doc -/\ndef x := 1\n", True),
    ("review: a docstring added", "theorem a : True := trivial\n", "/-- Theorem 1.2 -/\ntheorem a : True := trivial\n",
     True),
    ("review: a comment moved to the end of the line before", "  simp\n  -- x\n  ring\n", "  simp -- x\n  ring\n", True),
    ("review: `(--` and `,--` are comments", "def x := (-- a\n  [1,-- a\n 2])\n", "def x := (-- b\n  [1,-- b\n 2])\n", True),
    ("review: a token cannot start with `--` (whitespace is consumed first)",
     "infix:50 \" --> \" => f\nexample : 1 --> 2 := rfl\n", "infix:50 \" --> \" => f\nexample : 1 --> 3 := rfl\n", True),
    ("M4: `f?'` is one identifier in Lean (isIdRest holds `?`), so what follows its string is a comment",
     "example : (f?'\"', \" -- a\").2 = \" -- a\" := rfl\n", "example : (f?'\"', \" -- b\").2 = \" -- b\" := rfl\n", True),
    ("M4: a token holding a prime (`⁻¹'`) is no char literal", "example : f ⁻¹' s = t := rfl -- a\n",
     "example : f ⁻¹' s = t := rfl -- bb\n", True),
    ("M4: a Latin-1 letter is an identifier character (`é'`)", "def é' := 1 -- a\n", "def é' := 1 -- b\n", True),
    # refused: real changes (mini2-B(c), the design's §6)
    ("proof changed", _M7_B, _M7_B.replace("exact h", "exact (h)"), False),
    ("statement changed", _M7_B, _M7_B.replace("(h : 0 < n)", "(h : 1 ≤ n)"), False),
    ("string literal content", _M7_B, _M7_B.replace('"x -- y"', '"x -- z"'), False),
    ("indentation", _M7_B, _M7_B.replace("  exact h", "    exact h"), False),
    ("a comment splitting a token", _M7_B, _M7_B.replace("def ab := 1", "def a/--/b := 1"), False),
    ("attribute added", _M7_B, _M7_B.replace("theorem a", "@[simp] theorem a"), False),
    ("set_option added", _M7_B, "set_option maxHeartbeats 400000 in\n" + _M7_B, False),
    ("notation changed", "notation:50 a \" ≺ \" b => a < b\n", "notation:60 a \" ≺ \" b => a < b\n", False),
    ("#eval changed", _M7_B + "#eval 1\n", _M7_B + "#eval 2\n", False),
    ("whitespace between tokens", _M7_B, _M7_B.replace("(n : Nat)", "(n  : Nat)"), False),
    ("a comment becomes code", _M7_B + "-- def z := 1\n", _M7_B + "def z := 1\n", False),
    ("code becomes a comment", _M7_B, _M7_B.replace("def ab := 1", "-- def ab := 1"), False),
    ("a docstring closed earlier, exposing code", _M7_B + "/-- a -/\ndef q := 1\n", _M7_B + "/-- a -/\ndef q := 1 -/\n",
     False),
    ("H1 `/--/` then a line comment hides code", "/--/ -- -/ example : 2 + 2 = 4 := rfl\n",
     "/--/ -- -/ example : 2 + 2 = 5 - 1 := rfl\n", False),
    ("H2 the column after a leading comment", "  constructor\n  /-a-/ trivial\n", "  constructor\n  /-aaaaaa-/ trivial\n",
     False),
    ("H3 the column after a multi-line comment", "  tac1\n  /- x\n  -/ tac2\n", "  tac1\n  /- x\n      -/ tac2\n", False),
    ("H4 a token containing `--`", 'notation a " <-- " b => a + b\nexample : 1 <-- 2 = 3 := rfl\n',
     'notation a " <-- " b => a + b\nexample : 1 <-- 2 = 4 := rfl\n', False),
    ("H5 an interpolation with a `'}'` char across a line", 'def s := s!"{\n\'}\' ++ "-- x"}"\n',
     'def s := s!"{\n\'}\' ++ "-- y"}"\n', False),
    ("H6 throwError braces holding a string", 'def f : MetaM Unit := throwError "a {"}"} -- b"\n',
     'def f : MetaM Unit := throwError "a {"}"} -- c"\n', False),
    ("a `«k--»` name", 'def «k--» : Nat := 1\ntheorem t : «k--» = 1 := rfl\n',
     'def «k--» : Nat := 2\ntheorem t : «k--» = 2 := rfl\n', False),
    ("a raw string", 'def r : String := r#"a"--b"#\n', 'def r : String := r#"a"--bbbb"#\n', False),
    ("an interpolated string with a quote", 'def s : String := s!"{\'"\'} -- one"\n',
     'def s : String := s!"{\'"\'} -- three"\n', False),
    ("A4 a raw string alone", 'def r : String := r#"a" -- b"#\n', 'def r : String := r#"a" -- bbbb"#\n', False),
    ("A4 a «» name alone", 'def «x -- y» : Nat := 1\n', 'def «x -- z» : Nat := 1\n', False),
    ("A1 `/-` right after code", "def x := f/-c-/ y\n", "def x := f/-cc-/ y\n", False),
    ("L3 `--` inside a block comment is no line comment", "/- a -- b -/ def x := 1\n", "/- a -- b -/ def x := 2\n",
     False),
    ("L4 an escaped quote in a string", 'def s := "a\\" -- b"\n', 'def s := "a\\" -- c"\n', False),
    ("L5 a char literal holding `-`", "def c := '-' -- x\ndef d := 1\n", "def c := '-' -- x\ndef d := 2\n", False),
    ("L2 a doc comment nests", "/-- a /- b -/ c -/ def x := 1\n", "/-- a /- b -/ c -/ def x := 2\n", False),
    ("L5 a prime is no char literal", 'def t := f x\'"\' --a"\n', 'def t := f x\'"\' --b"\n', False),
    ("review L3: a mid-line comment widened moves the code after it",
     "  all_goals /-c-/ skip\n            trivial\n", "  all_goals /-cccc-/ skip\n            trivial\n", False),
    ("review L3: a docstring before code on its line, widened", "/-- d -/ def x := 1\n", "/-- dd -/ def x := 1\n", False),
    ("M4: `!'\"'` (a standalone `!` then a char literal)",
     "example : (!'\"'.isAlpha, \" -- a\") = (true, \" -- a\") := rfl\n",
     "example : (!'\"'.isAlpha, \" -- b\") = (true, \" -- b\") := rfl\n", False),
    ("M4: `λ'\"'` (λ is not an identifier character)", "example := (λ'\"' => \" -- a\")\n",
     "example := (λ'\"' => \" -- b\")\n", False),
    ("M4: `1'\"'` (a number, then a char literal)", "example : f 1'\"' \" -- a\" = \" -- a\" := rfl\n",
     "example : f 1'\"' \" -- b\" = \" -- b\" := rfl\n", False),
    ("M4: `℘'\"'` (℘ is letter-like in Lean)", "example : ℘'\"' -- a\" = \"' -- a\" := rfl\n",
     "example : ℘'\"' -- b\" = \"' -- b\" := rfl\n", False),
    ("M4: a raw string after a digit", "example : f 1r\"\\\" \" -- a\" = 1 := rfl\n",
     "example : f 1r\"\\\" \" -- b\" = 1 := rfl\n", False),
    ("M4: a raw string after `λ`", "example := (λr#\"\\\"# => \" -- a\")\n", "example := (λr#\"\\\"# => \" -- b\")\n", False),
    ("M4: a raw string after `!`", "example := (!r\"a\" == \" -- a\")\n", "example := (!r\"a\" == \" -- b\")\n", False),
    ("review L2: an unterminated comment swallowing a code change", "def x := 1\n/- \ndef y := 2",
     "def x := 1\n/- \ndef y := 3", False),
    ("review L2: an unterminated comment at the end", "def x := 1\n/- open", "def x := 1\n/- open more", False),
    ("review L2: an unterminated string", 'def x := 1\ndef s := " -- a\n', 'def x := 1\ndef s := " -- b\n', False),
    ("review: tab indentation for spaces", "  exact h\n", "\texact h\n", False),
    ("review: a no-break space in code", "def x := 1\n", "def x :=\xa01\n", False),
    ("review: a stray `-/` in code", "def x := 1\n", "def x := 1 -/\n", False),
    ("review: `/---/`", "/---/ def x := 1\n", "/---/ def x := 2\n", False),
    ("review: `/-!` nests", "/-! a /- -/ b -/ def x := 1\n", "/-! a /- -/ b -/ def x := 2\n", False),
    ("review: a string gap", "def s := \"a\\\n  -- b\"\n", "def s := \"a\\\n  -- c\"\n", False),
    ("review: the char literal '\\''", "def c := '\\'' -- x\ndef d := 1\n", "def c := '\\'' -- x\ndef d := 2\n", False),
    ("review: a name literal `a--b", "def n := `a--b\n", "def n := `a--c\n", False),
    ("review: a comment between tokens at a line start keeps the column", "  /- -/exact h\n", "  /-    -/exact h\n", False),
    ("review: an interpolation brace across a line", "def s := s!\"{1 +\n 2} -- a\"\n", "def s := s!\"{1 +\n 2} -- b\"\n",
     False),
    ("review: a «» name holding a brace", "def «a{» := 1\n", "def «a{» := 2\n", False),
    ("review of the M7 build, H1: `/-/- -/` is one closed comment (Lean steps over the character after `/-`), so "
     "the `example` after it is code", "/-/- -/ example : 1 = 1 := rfl -- -/\n", "/-/- -/ example : 2 = 2 := rfl -- -/\n",
     False),
    ("review of the M7 build, H1: a binder annotation after `/-/- -/`",
     "/-/- -/ theorem t (n : Nat) : n = n := rfl -- -/\n", "/-/- -/ theorem t {n : Nat} : n = n := rfl -- -/\n", False),
    ("review of the M7 build, H1: `/-/- x -/` then code on the next lines",
     "/-/- x -/\nexample : 1 = 1 := rfl\n-- -/\n", "/-/- x -/\nexample : 1 = 2 := rfl\n-- -/\n", False),
    ("review of the M7 build, L1: a newline in a string and a raw NUL are different code",
     'example : True := by\n  let _s := "a\nb"\n  trivial\n', 'example : True := by\n  let _s := "a\x00b"\n  trivial\n',
     False),
    ("review of the M7 build, L2: a mixed reading of two uncertain `'` (`⁻¹'` a token, then a char literal)",
     "example : f ⁻¹''\"'\" -- a\"\n", "example : f ⁻¹''\"'\" -- b\"\n", False),
    ("M4: `⁻¹'\"'` reads as a token part (then a string) or a char literal (then a comment): the readings disagree",
     "example : f ⁻¹'\"' -- a\" = s := rfl\n", "example : f ⁻¹'\"' -- b\" = s := rfl\n", False),
]
_M7_STRICT = [     # review L1, with the project's token holding `[--`: the bracket exemption is off
    ("L1: a bracket-led user token `[--`", 'notation "[--" x "]" => x\nexample : [-- 1 ] = 1 := rfl\n',
     'notation "[--" x "]" => x\nexample : [-- 2 ] = 1 := rfl\n', False),
]
_M7_LEX = [     # (name, text, expected code view, expect an ambiguity)
    ("A1 `(--` is a comment after a bracket", "def x := (-- c\n  1)\n", "def x := (\n  1)", False),
    ("L2 `/--/` opens a doc comment whose body starts after `/--`", "/--/ a -/\ndef x := 1\n", "def x := 1", True),
    ("L2 `/-!/ a -/` is a module doc", "/-!/ a -/\ndef x := 1\n", "def x := 1", False),
    ("L6, review L3: a comment is blanked to its width", "def y := a /-c-/b\n", "def y := a      b", False),
    ("L7 code after a leading comment keeps its column", "  /-ab-/ t\n", "         t", False),
    ("a string's newline is a sentinel, escaped (review of the M7 build, L1)", 'def s := "a\nb\x00"\n',
     'def s := "a\x00nb\x00\x00"', False),
    ("review of the M7 build, H1: `/-/- -/` closes at its first `-/`", "/-/- -/ x -- -/\n", "        x", False),
    ("review of the M7 build, H1: the `/` after `/-` is skipped, so `/-/-/` is closed at once", "/-/-/ a -/ b\n",
     "      a -/ b", False),
]


def _m7_lexer_controls():
    """DESIGN-M7 §9.1 (Lean-free): every unit case of the design and of its review; each lexer-output case; the
    strict project (review L1); the base compared with itself."""
    def same(a, b, strict=False):
        return (code_only(a, strict) == code_only(b, strict)
                and not (lexer_ambiguous(a, strict) or lexer_ambiguous(b, strict)))
    bad = [n for n, a, b, want in _M7_CASES if same(a, b) != want]
    bad += [n for n, a, b, want in _M7_STRICT if same(a, b, _co_marker_token(a)) != want or not same(a, b)]
    lex = [n for n, t, code, amb in _M7_LEX if code_only(t) != code or bool(lexer_ambiguous(t)) != amb]
    return [
        ("DESIGN-M7: the lexer passes each comment-only change and refuses each code change or doubtful reading "
         f"({len(_M7_CASES) + len(_M7_STRICT)} cases" + (f"; WRONG: {bad}" if bad else "") + ")", not bad),
        ("DESIGN-M7: the lexer's code view: `/--/`, `/-!/`, a comment blanked to its width, the column after a "
         "leading comment, a string's newline" + (f"; WRONG: {lex}" if lex else ""), not lex),
        ("DESIGN-M7 (review L1): a project declaring a token that holds a comment marker is strict; one with a "
         "comment-marker string but no syntax command, or a notation without one, is not",
         _co_marker_token(_M7_STRICT[0][1]) and not _co_marker_token(_M7_B)
         and not _co_marker_token('notation:50 a " ≺ " b => a < b\n')),
        ("DESIGN-M7: an unchanged file is the same and never ambiguous", same(_M7_B, _M7_B)
         and lexer_ambiguous(_M7_B) is None),
    ]


def _m7_controls():
    """DESIGN-M7 §9.1 (Lean-free): the kinds _parts_differ gives (with O1's texts, review M1), the combination in
    comment_only_detail with lean_identical stubbed, the Verso guard (a Lean file or the lakefile), the cache of a
    bytes-only result, and changes_after_last_audit's basis keys."""
    import tempfile, shutil
    g_ = globals()
    d = tempfile.mkdtemp(prefix="m7-")
    out = []
    keep = (g_["lean_identical"], g_["comment_only_detail"], g_["REPO"])
    try:
        # --- _parts_differ's kinds
        def mk(name, const_bytes, h="2", ext=b"e"):
            p = os.path.join(d, "parts", name)
            os.makedirs(p)
            open(os.path.join(p, "constants.olean"), "wb").write(const_bytes)
            open(os.path.join(p, "ext0.olean"), "wb").write(ext)
            open(os.path.join(p, "index.tsv"), "w").write(f"ext\tLean.x\t1\text0.olean\nconst\tA.a\t1\t{h}\n")
            return p
        a, b = mk("a", b"x"), mk("b", b"y")
        hv, ex = mk("h", b"y", h="3"), mk("e", b"x", ext=b"f")
        nd = mk("n", b"x")
        open(os.path.join(nd, "index.tsv"), "w").write("ext\tLean.x\t1\text0.olean\nconst\tA.b\t1\t2\n")
        kinds = lambda rs: [reason_kind(r) for r in rs]
        o1 = {None: "not-run", "no field differs (imports, …): only the serialized form (sharing) differs":
              "layout", "binder names (not their annotations) in the type of `A.a` differ": "layout",
              "no field compared here differs (imports, …): only the serialized form (sharing) differs": "semantic",
              "binder names (not their annotations) in the type of `A.a` differ; binder annotations in the value of "
              "`A.b` differ": "semantic",
              "other fields of `A.a` differ (reducibility hints, safety, …)": "semantic",
              "the recursor rules of `A.rec` differ": "semantic", "the module-system flag differs": "semantic",
              "binder annotations in the type of `A.a` differ": "semantic",
              "binder names or annotations in the value of `A.a` differ": "semantic", "imports differ": "semantic",
              "the order of the declarations differs": "semantic", "the auxiliary constant names differ": "semantic",
              "the number of declarations differs": "semantic", "the universe parameter names of `A.a` differ":
              "semantic", "the kind of `A.a` differs": "semantic", "something new": "semantic"}
        got = {k: kinds(_parts_differ("F.lean", a, b, diag=lambda k=k: k)) for k in o1}
        out.append(("DESIGN-M7 (review M1): the bytes-only reason is \"layout\" with the sharing text or binder names "
                    "only; \"semantic\" with any field identical source cannot produce (imports, order, auxiliary "
                    "names, their number, universe names, the kind, other fields, recursor rules, the module flag, "
                    "binder annotations, undecided), also beside a benign one or in the old wording; \"not-run\" with "
                    "no O1 text (review of the M7 build, H2)",
                    all(got[k] == [v] for k, v in o1.items())))
        out.append(("DESIGN-M7: a differing declaration set, type or value, or extension part is \"semantic\"",
                    kinds(_parts_differ("F.lean", a, nd)) == ["semantic"]
                    and kinds(_parts_differ("F.lean", a, hv)) == ["semantic"]
                    and kinds(_parts_differ("F.lean", a, ex)) == ["semantic"]
                    and kinds(_parts_differ("F.lean", b, ex)) == ["not-run", "semantic"]
                    and reason_kind("a plain reason") == "semantic"
                    and reason_kind(LeanReason("x", "bogus")) == "semantic"))
        # --- comment_only_detail with lean_identical stubbed, on a git fixture
        r = os.path.join(d, "repo")
        os.makedirs(r)
        g = lambda *x: subprocess.run(["git", "-C", r, *x], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        open(os.path.join(r, "A.lean"), "w").write(_M7_B)
        open(os.path.join(r, "lakefile.toml"), "w").write("name = \"x\"\n")
        g("add", "-A"); g("commit", "-qm", "base")
        base = g("rev-parse", "HEAD").stdout.strip()
        cfg = {"lean_files": ["A.lean"]}
        doc = _M7_B.replace("/-- Lemma 1. -/", "/-- Lemma 1, longer. -/")
        lay = LeanReason("A.lean: " + BYTES_ONLY + ": " + O1_LAYOUT[0], "layout")
        calls = []

        def stub(reasons):
            def f(repo, texts, lean_cmd=None):
                calls.append(1)
                return list(reasons)
            return f

        def det(reasons, txt=doc):
            g_["lean_identical"] = stub(reasons)
            open(os.path.join(r, "A.lean"), "w").write(txt)
            try:
                return comment_only_detail(cfg, base, r)
            finally:
                open(os.path.join(r, "A.lean"), "w").write(_M7_B)
                g_["lean_identical"] = keep[0]
        d_same, d_lay = det([]), det([lay])
        d_mix = det([lay, LeanReason("A.lean: its Lean.x entries differ (…)", "semantic")])
        d_nr = det([LeanReason("A.lean: the old version does not compile, so it cannot be compared: x", "not-run")])
        d_plain = det(["A.lean: " + BYTES_ONLY])
        n0 = len(calls)
        d_code = det([lay], _M7_B.replace("exact h", "exact (h)"))
        no_call = len(calls) == n0
        out.append(("DESIGN-M7 §3.1: Lean's [] gives comment-only on the compiled basis; only bytes-only reasons give "
                    "it on the source basis, with the reasons; a semantic one among them, not-run, a plain str, or a "
                    "text difference (Lean never asked) is NOT comment-only",
                    d_same == {"ok": True, "what": ["A.lean"], "basis": "compiled", "lean": []}
                    and d_lay == {"ok": True, "what": ["A.lean"], "basis": "source", "lean": [lay]}
                    and not d_mix["ok"] and d_mix["basis"] is None and not d_nr["ok"] and not d_plain["ok"]
                    and not d_code["ok"] and no_call
                    and comment_only_since(cfg, base, r)[0] is True))
        # review L1 through the text stage: a token declared in ANOTHER project file makes `[--` ambiguous here
        open(os.path.join(r, "N.lean"), "w").write('notation "[--" x "]" => x\n')
        open(os.path.join(r, "A.lean"), "w").write(_M7_B + "example : [-- 1 ] = 1 := rfl\n")
        g("add", "-A"); g("commit", "-qm", "token")
        base = g("rev-parse", "HEAD").stdout.strip()
        open(os.path.join(r, "A.lean"), "w").write(_M7_B + "example : [-- 2 ] = 1 := rfl\n")
        st_why = _comment_only_text({"lean_files": ["A.lean", "N.lean"]}, base, r)[0]
        st_alone = _comment_only_text(cfg, base, r)[0]
        open(os.path.join(r, "A.lean"), "w").write(_M7_B)
        os.remove(os.path.join(r, "N.lean"))
        g("add", "-A"); g("commit", "-qm", "untoken")
        base = g("rev-parse", "HEAD").stdout.strip()
        out.append(("DESIGN-M7 (review L1): a project file declaring a token that holds `--` makes `[--` in another file "
                    "ambiguous (the text stage refuses); without that file it reads as a comment",
                    any("right after code" in w for w in st_why) and st_alone == []))
        # Verso (review L4: the lakefile too)
        open(os.path.join(r, "lakefile.toml"), "w").write("name = \"x\"\nleanOptions = { doc.verso = true }\n")
        g("commit", "-qam", "verso")
        base = g("rev-parse", "HEAD").stdout.strip()
        v_lake, v_lake_same = det([lay]), det([])
        open(os.path.join(r, "lakefile.toml"), "w").write("name = \"x\"\n")
        open(os.path.join(r, "A.lean"), "w").write("set_option doc.verso true\n" + _M7_B)
        g("commit", "-qam", "verso2")
        base = g("rev-parse", "HEAD").stdout.strip()
        vb = "set_option doc.verso true\n" + _M7_B
        g_["lean_identical"] = stub([lay])
        open(os.path.join(r, "A.lean"), "w").write(vb.replace("Lemma 1.", "Lemma 1, longer."))
        v_file = comment_only_detail(cfg, base, r)
        g_["lean_identical"] = keep[0]
        out.append(("DESIGN-M7 (review L4): with `doc.verso` set in a project Lean file or in the lakefile, a "
                    "bytes-only result is NOT comment-only (Lean's \"same\" still is)",
                    not v_lake["ok"] and any("doc.verso" in w for w in v_lake["what"]) and not v_file["ok"]
                    and v_lake_same["ok"] and v_lake_same["basis"] == "compiled"))
        # --- the cache of a bytes-only result: read back as layout (never as "same"), re-judged by the current rule
        import hashlib
        texts = {"A.lean": (_M7_B, doc)}
        key = hashlib.sha256(json.dumps([["false"], sorted(texts.items()),
                                         open(OLEAN_PARTS, encoding="utf-8").read()]).encode()).hexdigest()
        lkey = hashlib.sha256((key + open(OLEAN_DIFF, encoding="utf-8").read()).encode()).hexdigest()
        cpath = os.path.join(r, FW, "comment-only-cache.json")
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        json.dump({lkey: {"layout": [str(lay)]}}, open(cpath, "w"))
        c_lay = lean_identical(r, texts, ["false"])
        json.dump({lkey: {"layout": ["A.lean: " + BYTES_ONLY + ": imports differ"]}}, open(cpath, "w"))
        c_sem = lean_identical(r, texts, ["false"])
        json.dump({lkey: {"layout": []}, key: "layout"}, open(cpath, "w"))
        c_bad = lean_identical(r, texts, ["false"])
        json.dump({key: "same"}, open(cpath, "w"))
        c_same = lean_identical(r, texts, ["false"])
        os.remove(cpath)
        out.append(("DESIGN-M7 §3.4: a cached bytes-only result is read back as layout (never as \"same\"), judged "
                    "again by the current rule; an empty or old-form entry recompiles (here: not-run); \"same\" is []",
                    c_lay == [str(lay)] and kinds(c_lay) == ["layout"] and kinds(c_sem) == ["semantic"]
                    and kinds(c_bad) == ["not-run"] and c_same == []))
        # --- changes_after_last_audit carries the basis and the reasons
        rd = os.path.join(r, "R", f"2026-01-01-{base[:11]}")
        os.makedirs(rd)
        json.dump({"_meta": {"kind": "diff"}}, open(os.path.join(rd, "TARGET.json"), "w"))
        open(os.path.join(r, "A.lean"), "w").write(vb.replace("Lemma 1.", "Lemma 1, longer."))
        g("commit", "-qam", "doc")
        g_["REPO"] = r
        res = {}
        for basis, ok_ in (("source", True), ("compiled", True), (None, False)):
            g_["comment_only_detail"] = lambda c_, b_, *a_, basis=basis, ok_=ok_: {
                "ok": ok_, "what": ["A.lean"], "basis": basis, "lean": [lay] if basis == "source" else []}
            res[basis] = changes_after_last_audit(cfg, [rd])
        out.append(("DESIGN-M7: changes_after_last_audit carries the basis and, on the source basis, Lean's reasons",
                    res["source"]["comment_only"] and res["source"]["comment_only_basis"] == "source"
                    and res["source"]["comment_only_lean"] == [str(lay)]
                    and res["compiled"]["comment_only_basis"] == "compiled" and res["compiled"]["comment_only_lean"] == []
                    and not res[None]["comment_only"] and res[None]["comment_only_basis"] is None))
    finally:
        g_["lean_identical"], g_["comment_only_detail"], g_["REPO"] = keep
        shutil.rmtree(d, ignore_errors=True)
    return out


_M7_FAKE_LEAN = r'''#!/usr/bin/env python3
# A stand-in for `lean` (the review of the M7 build, fakelean.py): compiling writes the source as the "olean";
# olean_parts writes equal hashes and the source bytes, so any text change is a bytes-only difference (what
# `Expr.hash` gives for a binder change); olean_diff prints FAKE_O1 ("fail": exits 1; "hang": sleeps)
import sys, os, time
a = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    open(log, "a").write(" ".join(os.path.basename(x) for x in a[:2]) + "\n")
if a and a[0] == "--run":
    script = os.path.basename(a[1])
    if script == "olean_parts.lean":
        ol, out, mod = a[2:5]
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, "constants.olean"), "wb").write(open(ol, "rb").read())
        open(os.path.join(out, "index.tsv"), "w").write("const\tA.t\t1\t2\n")
        sys.exit(0)
    if script == "olean_diff.lean":
        mode = os.environ.get("FAKE_O1", "fail")
        if mode == "fail":
            sys.exit(1)
        if mode == "hang":
            time.sleep(30)
        if mode == "hangkid":       # a child of its own, as `lake env` starts `lean` (REREVIEW-M7 NEW-2)
            import subprocess
            k = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            open(os.environ["FAKE_KID"], "w").write(str(k.pid))
            time.sleep(30)
        print("DIFF\t" + mode.replace("|", "\nDIFF\t"))
        print("END\t%d" % (mode.count("|") + 1))
        sys.exit(0)
src = a[-1]
ol = a[a.index("-o") + 1]
open(ol, "wb").write(open(src, "rb").read())
sys.exit(0)
'''


def _m7_fail_closed_controls():
    """Review of the M7 build, H2 and L4/L5 (Lean-free, a stand-in for Lean): through comment_only_detail, a
    bytes-only difference is comment-only only when O1 ran and every finding is benign; O1 failing, hanging past
    the budget, or a benign finding before a real one is NOT comment-only. A missing `lake` is not-run, no crash.
    A refusal is cached and read back as a refusal without compiling again; a compile failure is not cached."""
    import tempfile, shutil, hashlib, time, sys as _sys
    d = tempfile.mkdtemp(prefix="m7-fc-")
    out, g_ = [], globals()
    keep_env = {k: os.environ.get(k) for k in ("FAKE_O1", "FAKE_LOG", "FAKE_KID", "PATH")}
    keep_budget = g_["OLEAN_DIFF_BUDGET"]
    try:
        fake = os.path.join(d, "fakelean.py")
        open(fake, "w").write(_M7_FAKE_LEAN)
        cmd = [_sys.executable, "-I", fake]
        r = os.path.join(d, "repo")
        os.makedirs(r)
        git = lambda *x: subprocess.run(["git", "-C", r, *x], capture_output=True, text=True)
        git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
        old = "/-- d -/\ntheorem t (n : Nat) : n = n := rfl\n"
        open(os.path.join(r, "A.lean"), "w").write(old)
        git("add", "-A"); git("commit", "-qm", "b")
        base = git("rev-parse", "HEAD").stdout.strip()
        cfg = {"lean_files": ["A.lean"]}
        open(os.path.join(r, "A.lean"), "w").write(old.replace("/-- d -/", "/-- dd -/"))
        cache = os.path.join(r, FW, "comment-only-cache.json")
        nm = "binder names (not their annotations) in the type of `A.s` differ"
        an = "binder annotations in the type of `A.t` differ"
        res = {}
        for mode in ("fail", "hang", nm, f"{nm}|{an}", an, "the kind of `A.t` differs (def, opaque)"):
            os.environ["FAKE_O1"] = mode
            g_["OLEAN_DIFF_BUDGET"] = 2
            try:
                os.remove(cache)
            except OSError:
                pass
            res[mode] = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        out.append(("review of the M7 build, H2: on the source basis O1 must have run and found only benign fields: "
                    "O1 failing or hanging past its budget, a binder annotation (also after a binder-names finding) "
                    "or the kind is NOT comment-only; binder names alone is comment-only on the source basis",
                    res[nm]["ok"] and res[nm]["basis"] == "source"
                    and not any(res[m]["ok"] for m in res if m != nm)
                    and [reason_kind(w) for w in res["fail"]["what"]] == ["not-run"]))
        # L5: a definite refusal (O1 names a binder annotation) is cached and read back without compiling again
        log = os.path.join(d, "log")
        os.environ["FAKE_LOG"] = log
        os.environ["FAKE_O1"] = an
        try:
            os.remove(cache)
        except OSError:
            pass
        r1 = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        n1 = len(open(log).read().splitlines())
        r2 = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        n2 = len(open(log).read().splitlines())
        out.append(("review of the M7 build, L5: a definite refusal (here O1 naming a binder annotation) is cached, "
                    "and read back as a refusal without running Lean again", not r1["ok"] and not r2["ok"] and n1 > 0
                    and n2 == n1 and str(r2["what"][0]) == str(r1["what"][0])))
        def _rmc():
            try:
                os.remove(cache)
            except OSError:
                pass
        # REREVIEW-M7 NEW-1: O1's absence (failing, or hanging past the budget) is not cached: once O1 answers, the
        # same texts are comment-only; a not-run refusal an older cache holds is not read back
        res1 = {}
        for mode in ("fail", "hang"):
            _rmc()
            os.environ["FAKE_O1"] = mode
            first = comment_only_detail(cfg, base, r, lean_cmd=cmd)
            n_a = len(open(log).read().splitlines())
            os.environ["FAKE_O1"] = nm
            res1[mode] = (first["ok"], comment_only_detail(cfg, base, r, lean_cmd=cmd)["ok"],
                          len(open(log).read().splitlines()) > n_a)
        os.environ["FAKE_O1"] = "fail"
        _rmc()
        old_r = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        c_old = json.load(open(cache)) if os.path.exists(cache) else {}
        texts_ = {"A.lean": (old, old.replace("/-- d -/", "/-- dd -/"))}
        k_ = hashlib.sha256(json.dumps([cmd, sorted(texts_.items()),
                                        open(OLEAN_PARTS, encoding="utf-8").read()]).encode()).hexdigest()
        lk_ = hashlib.sha256((k_ + open(OLEAN_DIFF, encoding="utf-8").read()).encode()).hexdigest()
        os.environ["FAKE_O1"] = nm
        json.dump({lk_: {"refused": [f"A.lean: {BYTES_ONLY}: {an}"]}}, open(cache, "w"))   # the key is the one used
        n_s = len(open(log).read().splitlines())
        sem = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        key_ok = not sem["ok"] and len(open(log).read().splitlines()) == n_s
        json.dump({lk_: {"refused": [str(w) for w in old_r["what"]]}}, open(cache, "w"))   # as the L5 build cached it
        n_b = len(open(log).read().splitlines())
        readback = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        out.append(("REREVIEW-M7 NEW-1: O1 failing or timing out is not cached as a refusal (the next call runs Lean "
                    "again and, O1 answering benign, accepts); an older cache's not-run refusal is not read back",
                    res1 == {"fail": (False, True, True), "hang": (False, True, True)} and c_old == {}
                    and [reason_kind(w) for w in old_r["what"]] == ["not-run"] and key_ok
                    and readback["ok"] and len(open(log).read().splitlines()) > n_b))
        # REREVIEW-M7 NEW-2: a timed-out O1 is killed with its whole process group (no `lean` left running)
        kid = os.path.join(d, "kid")
        os.environ["FAKE_KID"] = kid
        os.environ["FAKE_O1"] = "hangkid"
        _rmc()
        t0 = time.monotonic()
        hk = comment_only_detail(cfg, base, r, lean_cmd=cmd)
        took = time.monotonic() - t0
        def _dead(pid):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            if not os.path.isdir("/proc"):      # macOS branch: a zombie, or gone, has no BSD info (libproc)
                if sys.platform == "darwin":
                    import lanecheck
                    return lanecheck._bsdinfo(lanecheck._libproc(), pid) is None
                r_ = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
                return r_.returncode != 0 or r_.stdout.strip().startswith("Z")
            try:        # a zombie is dead too
                return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0] == "Z"
            except OSError:
                return True
        kpid = int(open(kid).read()) if os.path.exists(kid) else None
        gone_ = False
        for _ in range(50):
            if kpid is not None and _dead(kpid):
                gone_ = True
                break
            time.sleep(0.1)
        if kpid is not None and not gone_:
            try:
                os.kill(kpid, 9)
            except OSError:
                pass
        os.environ.pop("FAKE_KID", None)
        out.append(("REREVIEW-M7 NEW-2: O1 hanging past its budget is killed with its children (the process group), "
                    "and the call returns at the budget, not when a child ends",
                    not hk["ok"] and kpid is not None and gone_ and took < 20))
        os.environ.pop("FAKE_LOG", None)
        # a compile failure is not cached (it may be the host's)
        _rmc()
        texts = {"A.lean": (old, old.replace("/-- d -/", "/-- dd -/"))}
        lean_identical(r, texts, ["false"])
        out.append(("review of the M7 build, L5: a version that does not compile is not cached",
                    not os.path.exists(cache) or json.load(open(cache)) == {}))
        # L4: no `lake` on PATH (an empty directory as PATH: nothing can run)
        empty = os.path.join(d, "empty")
        os.makedirs(empty)
        os.environ["PATH"] = empty
        try:
            nolake = lean_identical(r, texts)
        except Exception as e:      # noqa: BLE001 -- the control reports it
            nolake = e
        os.environ["PATH"] = keep_env["PATH"] or ""
        out.append(("review of the M7 build, L4: with no `lake` on PATH the Lean stage is not-run, never a crash",
                    isinstance(nolake, list) and [reason_kind(w) for w in nolake] == ["not-run"]))
    finally:
        g_["OLEAN_DIFF_BUDGET"] = keep_budget
        for k, v in keep_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(d, ignore_errors=True)
    return out


def _comment_only_controls():
    """mini2 audit (time): a docstring-only change is recognised mechanically; any code change,
    however small, is not (comment_only_since fails closed)."""
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="comment-only-")
    out = []
    try:
        g = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        base_txt = ("/-- Lemma 1. -/\ntheorem a (n : Nat) (h : 0 < n) : 0 < n := by\n  exact h\n"
                    "def s : String := \"x -- y\"\ndef ab := 1\n")
        open(os.path.join(d, "A.lean"), "w").write(base_txt)
        open(os.path.join(d, "lakefile.toml"), "w").write("x\n")
        g("add", "-A"); g("commit", "-qm", "base")
        base = g("rev-parse", "HEAD").stdout.strip()
        cfg = {"lean_files": ["A.lean"]}

        def case(txt, extra=None):
            open(os.path.join(d, "A.lean"), "w").write(txt)
            if extra:
                extra()
            r = not _comment_only_text(cfg, base, d)[0]     # the text stage; Lean decides (--lean)
            open(os.path.join(d, "A.lean"), "w").write(base_txt)
            g("checkout", "-q", "--", "lakefile.toml")
            return r
        doc = base_txt.replace("/-- Lemma 1. -/", "/-- Lemma 1. True only vacuously:\nits hypothesis never holds. -/\n-- note")
        out.append(("mini2-B(c): a change to docstrings and comments only passes the text stage", case(doc)))
        open(os.path.join(d, "A.lean"), "w").write(doc)
        nolean = comment_only_since(cfg, base, d, lean_cmd=["false"])
        open(os.path.join(d, "A.lean"), "w").write(base_txt)
        out.append(("review of fix-mini2 H1: when Lean cannot compare the compiled modules, a change is NOT "
                    "comment-only, even one the text stage passes (the Lean stage decides; fails closed)",
                    not nolean[0] and "does not compile" in " ".join(nolean[1])))
        out.append(("mini2-B(c): a changed proof, statement, string literal, indentation, or `ab` split by a "
                    "comment into `a b` is NOT comment-only",
                    not case(base_txt.replace("exact h", "exact (h)"))
                    and not case(base_txt.replace("(h : 0 < n)", "(h : 1 ≤ n)"))
                    and not case(base_txt.replace('"x -- y"', '"x -- z"'))
                    and not case(base_txt.replace("  exact h", "    exact h"))
                    and not case(base_txt.replace("def ab := 1", "def a/--/b := 1"))))
        _hb = base_txt + 'def «x/-» : Nat := 0\nexample : 2 + 2 = 4 := rfl\n/-- d -/\ndef y := 1\n'
        open(os.path.join(d, "A.lean"), "w").write(_hb); g("commit", "-qam", "guillemet")
        _bh = g("rev-parse", "HEAD").stdout.strip()
        open(os.path.join(d, "A.lean"), "w").write(_hb.replace("2 + 2 = 4", "2 + 2 = 5 - 1"))
        hid = _comment_only_text(cfg, _bh, d)[0]
        open(os.path.join(d, "A.lean"), "w").write(_hb.replace("/-- d -/", "/-- d, longer -/"))
        hid_doc = _comment_only_text(cfg, _bh, d)[0]
        g("reset", "-q", "--hard", base)
        out.append(("re-check R3: an `example` hidden from the text filter by a `«x/-»` name, a raw string or an "
                    "interpolated string fails closed (the .olean does not keep it); a plain `«x»` does not",
                    bool(hid) and any("«x/-»" in w for w in hid_doc)     # DESIGN-M7: the name is read as code
                    and str(lexer_ambiguous('def r := r#"a"--b"#\n')).startswith("a raw string")
                    and lexer_ambiguous('def s := s!"{\'"\'} -- one"\n') is not None
                    and lexer_ambiguous(base_txt + "def «x y» := 1\n") is None))
        lake = case(doc, lambda: open(os.path.join(d, "lakefile.toml"), "w").write("y\n"))
        open(os.path.join(d, "B.lean"), "w").write("def b := 1\n")
        un = comment_only_since({"lean_files": ["A.lean", "B.lean"]}, base, d)[0]
        os.remove(os.path.join(d, "B.lean"))
        bad = comment_only_since(cfg, "0000000", d)[0]
        # a project whose code reads docstrings: even a docstring-only change is refused
        open(os.path.join(d, "A.lean"), "w").write(base_txt + "#eval Lean.findDocString? `a\n")
        g("commit", "-qam", "reader")
        base2 = g("rev-parse", "HEAD").stdout.strip()
        open(os.path.join(d, "A.lean"), "w").write(doc + "#eval Lean.findDocString? `a\n")
        rd_why = comment_only_since(cfg, base2, d)[1]
        rd = any("reads docstrings" in w for w in rd_why) is False
        out.append(("mini2-B(c): a build-file change, an untracked Lean file of the project, code that reads "
                    "docstrings, or a base git cannot read is NOT comment-only (fails closed)",
                    not lake and not un and not rd and not bad))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


# the H1 attacks (review of fix-mini2): changes the text stage reads as comments, but that are code
_CO_BASE = ("def «k--» : Nat := 1\ntheorem t : «k--» = 1 := rfl\n"
            "def «x/-» : Nat := 0\ntheorem t2 (n : Nat) (h : 0 < n) : 0 < n := h\n/-- doc -/\ndef y := 1\n"
            "def s : String := s!\"{'\"'} -- one\"\ntheorem ts : s.length = 8 := by decide\n"
            "def r : String := r#\"a\"--b\"#\n"
            "theorem c : True ∧ True := by\n  constructor\n  · /-a-/ trivial\n  · trivial\n"
            "private theorem pv : True := trivial\n")
_CO_ATTACKS = [
    ("a `«k--»` name", ("def «k--» : Nat := 1\ntheorem t : «k--» = 1", "def «k--» : Nat := 2\ntheorem t : «k--» = 2")),
    ("a hypothesis after a `«x/-»` name", ("(h : 0 < n) : 0 < n := h", "(h : 1 < n) : 0 < n := Nat.lt_of_succ_lt h")),
    ("an interpolated string", ("-- one\"\ntheorem ts : s.length = 8", "-- three\"\ntheorem ts : s.length = 10")),
    ("a raw string", ('r#"a"--b"#', 'r#"a"--bbbb"#')),
]


ADJ_STUB = r'''import json, os, sys, time
ctl = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctl.json")))
script, args = sys.argv[1], sys.argv[2:]
c = ctl.get(script, {})
print("stub", script, *args, flush=True)
time.sleep(c.get("sleep", 0))
if script == "phase0":
    mode = c.get("mode") or ("read-only" + (", statement round" if "--statements" in args else ""))
    print(f"# Phase 0 for project toy (--project toy); mode: {mode}")
    if c.get("crash"):
        print("Traceback (most recent call last):\nValueError: boom")
        sys.exit(1)
    print("PHASE 0: GREEN" if c.get("rc", 0) == 0 else "PHASE 0: RED (1 check(s))")
else:
    print(c.get("out", "REPEATED OUT-OF-LANE NOTES\n  (none)\n\nsummary: 0 outstanding fail(s), 0 never passed, "
                       "0 lane/item gap(s), 0 repeated decision(s), 0 scope drift(s), 0 unrecorded round(s), "
                       "0 NotDoneYet still unexamined"))
if c.get("rc", 0) < 0:
    sys.stdout.flush()
    os.kill(os.getpid(), -c["rc"])        # killed by that signal (a negative code, as subprocess reports it)
sys.exit(c.get("rc", 0))
'''
# E2E fix 1: the coverage section of a real run's adjudicator-checks log (a statement round whose correspondence
# lane returned one Fail; item names replaced), which the verifier called a crash: audit_coverage.py exits 1 by
# design after this report
ADJ_COV_E2E = """note: canonical lane(s) with no data in any round: substantiveness, prior-art -- expected: every round so far is a statement round, which runs only correspondence, non-vacuity, paper-faithfulness (by design; not UNCOVERED)
rolled up 3 lane-round(s) from audits/toy

========================================================================
OUTSTANDING FAILS (1) — failed, and no Pass since the last Fail
  [correspondence] Toy.T   (last seen 2026-01-01-full-abcdef0)

AMBIGUOUS (0) — a reading choice; each is a question for the human
  none

NEVER PASSED (0) — seen, but no lane round ever returned Pass
  none

NEVER EXAMINED — item is known to some lane, but this lane has never seen it
  correspondence: 0
  paper-faithfulness: 0
  non-vacuity: 0

STALE PASSES (0) — passed earlier, but changed since (vs. 2026-01-01-full-abcdef0)
  none

SCOPE DRIFT (1) — lane's declared scope vs the target step 3 sent
  2026-01-01-full-abcdef0 paper-faithfulness: -0 dropped, +0 added, 1 renamed
      renamed (cosmetic, not gated) Definition (a, tex l.7 -> Definition (b, tex l
  none

summary: 1 outstanding fail(s), 0 never passed, 0 lane/item gap(s), 0 repeated decision(s), 0 scope drift(s), 0 unrecorded round(s), 0 NotDoneYet still unexamined
"""


def _adj_checks_controls():
    """C3 fix round 1 (COMPAT-C H1, ATTACK-C M1/M2/L2/L4/L5): the background adjudicator checks, end to end on
    a toy project with both scripts stubbed (no Lean): the real CLI, the detached worker, the lock, the log."""
    import tempfile, shutil, signal
    d = tempfile.mkdtemp(prefix="adjchk-")
    out = []
    try:
        repo, aud = os.path.join(d, "repo"), os.path.join(d, "repo", "audits")
        rd = "audits/toy"
        R, R2 = "2026-01-01-full-abcdef0", "2026-01-02-abcdef1"
        os.makedirs(os.path.join(repo, rd, R))
        os.makedirs(os.path.join(repo, rd, R2))
        def tj(r, kind):
            json.dump({"_meta": {"kind": kind}}, open(os.path.join(repo, rd, r, "TARGET.json"), "w"))
        tj(R, "full")
        tj(R2, "statements")
        g = lambda where, *a: subprocess.run(["git", "-C", where, "-c", "user.name=t", "-c", "user.email=t@t",
                                              *a], capture_output=True, text=True)
        open(os.path.join(repo, "A.lean"), "w").write("x\n")
        open(os.path.join(repo, ".gitignore"), "w").write("audits/\n.formalization-work/\n")
        for w in (repo, aud):
            g(w, "init", "-q")
            g(w, "add", "-A")
            g(w, "commit", "-q", "-m", "init")
        stub = os.path.join(d, "stub.py")
        open(stub, "w").write(ADJ_STUB)
        ctlp = os.path.join(d, "ctl.json")
        def ctl(**kw):
            json.dump(kw, open(ctlp, "w"))
        ctx = {"repo": repo, "audits": aud, "name": "toy", "rounds_dir": rd, "stub": stub, "poll": 0.1, "grace": 0.3,
               "test": True}
        env = dict(os.environ, **{ADJ_TEST_ENV: json.dumps(ctx)})
        me = os.path.abspath(__file__)
        def run(*a, timeout=60):
            r = subprocess.run([sys.executable, "-B", me, *a, "--selftest"], cwd=repo, env=env, capture_output=True,
                               text=True, timeout=timeout)
            return r.returncode, r.stdout
        fw = os.path.join(repo, FW)
        log = lambda r=R, own=False: os.path.join(fw, f"adjudicator-{r}{'-own' if own else ''}.log")
        lock = os.path.join(fw, ADJ_LOCK)
        def gone(t=20):
            end = time.time() + t
            while time.time() < end and os.path.exists(lock):
                time.sleep(0.05)
            return not os.path.exists(lock)

        # 1. normal completion; the start returns at once with the header in place
        # REVIEW-FLOOR LOW-5: "at once" is the property itself, not wall time (a 1.4 s bound against a 1.5 s stub
        # flaked under load): when the start returns, the log has its header and no END line yet (Phase 0 sleeps 5 s)
        ctl(phase0={"sleep": 5})
        rc, o = run("--adjudicator-checks", "--round", R)
        hdr = open(log()).read().splitlines()
        quick = bool(hdr) and "END" not in hdr
        rc2, o2 = run("--adjudicator-checks", "--round", R2)          # 2. a second start while one runs
        rc3, o3 = run("--adjudicator-checks", "--round", R, "--own")
        rcw, ow = run("--wait-adjudicator-checks", "--round", R, "--timeout", "30")
        out.append(("C3: --adjudicator-checks starts the checks in the background and returns at once, the log's "
                    "header already written (round, run, id, both HEADs, TARGET.json's kind, the exact commands)",
                    rc == 0 and quick and "--wait-adjudicator-checks --round " + R in o
                    and hdr[0].startswith(f"ADJUDICATOR CHECKS round {R} (operator run) id ")
                    and hdr[1] == "HEAD " + _adj_heads(ctx)[0] and hdr[2] == "AUDITS " + _adj_heads(ctx)[1]
                    and hdr[3] == "KIND full (TARGET.json _meta.kind)"
                    and hdr[4] == f"CMD phase0: python3 {stub} phase0 --readonly --project toy"))
        out.append(("C3: a second start while one runs is refused, for any round and for --own (one lock: never "
                    "two Phase 0 runs of this mechanism at once), naming the wait command",
                    rc2 == 1 and rc3 == 1 and "already running" in o2 and f"--wait-adjudicator-checks --round {R}" in o3
                    and not os.path.exists(log(R2)) and not os.path.exists(log(R, True))))
        txt = open(log()).read()
        out.append(("C3: --wait-adjudicator-checks waits for END and accepts the log: both HEAD pairs current, "
                    "the commands and Phase 0's mode as TARGET.json says, Phase 0's verdict and every exit code "
                    "recorded",
                    rcw == 0 and "current:" in ow and "PHASE 0: GREEN" in ow and txt.endswith("END\n")
                    and "phase0 exit 0" in txt and "coverage exit 0" in txt and "HEAD " + _adj_heads(ctx)[0] + " (end)"
                    in txt and gone()))

        # 3. a bounded wait times out (exit 3), then the next wait succeeds; a statement round gets --statements
        ctl(phase0={"sleep": 2})
        run("--adjudicator-checks", "--round", R2)
        t0 = time.time()
        rcw1, ow1 = run("--wait-adjudicator-checks", "--round", R2, "--timeout", "0.3")
        bounded = time.time() - t0 < 1.8
        rcw2, ow2 = run("--wait-adjudicator-checks", "--round", R2, "--timeout", "30")
        out.append(("C3: a wait is bounded: at its timeout it exits 3 (still running: wait again); the next wait "
                    "ends 0; a statement round's Phase 0 runs with --statements (from TARGET.json)",
                    rcw1 == 3 and bounded and "still running" in ow1 and rcw2 == 0
                    and "--readonly --statements --project toy" in open(log(R2)).read() and gone()))

        # 4. RED is current (the adjudicator STOPs on it); a crash is stale, never a bare END
        ctl(phase0={"rc": 1})
        run("--adjudicator-checks", "--round", R, "--foreground")
        rr, orr = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        ctl(phase0={"crash": True})
        rcf, _ = run("--adjudicator-checks", "--round", R, "--foreground")
        rc4, o4 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        ctl(audit_coverage={"rc": 2})
        run("--adjudicator-checks", "--round", R, "--foreground")
        rc5, o5 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        out.append(("C3: a RED Phase 0 is a current log (its verdict reported); a Phase 0 crash (exit 1, no "
                    "verdict line) or a coverage exit other than 0 is stale: run the checks yourself (--own)",
                    rr == 0 and "PHASE 0: RED" in orr and rcf == 1 and rc4 == 1 and "STALE" in o4
                    and "no verdict" in o4 and f"--adjudicator-checks --round {R} --own" in o4
                    and rc5 == 1 and "coverage roll-up exited 2" in o5))

        # 4b. E2E fix 1: each check judged by its own documented exits. The real case: the coverage roll-up's
        # report of an outstanding Fail, exit 1 by design, is a current log (the adjudicator decides the Fail);
        # the same report with exit 0, cut before its summary line, after a crash line, or killed, is stale; so
        # is a Phase 0 that exited 2 or crashed itself (a child's crash line inside a GREEN Phase 0 is not its own)
        def cov_case(**c):
            ctl(**c)
            run("--adjudicator-checks", "--round", R, "--foreground")
            return run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        e_ok = cov_case(audit_coverage={"out": ADJ_COV_E2E, "rc": 1})
        e_rc0 = cov_case(audit_coverage={"out": ADJ_COV_E2E, "rc": 0})
        e_cut = cov_case(audit_coverage={"out": ADJ_COV_E2E.split("summary:")[0], "rc": 1})
        e_tb = cov_case(audit_coverage={"out": "Traceback (most recent call last):\nKeyError: x\n"
                                               "FAIL[uncoded] audit_coverage.py crashed (KeyError: x)", "rc": 1})
        e_sig = cov_case(audit_coverage={"out": ADJ_COV_E2E, "rc": -9})
        e_p2 = cov_case(phase0={"rc": 2})
        e_p0c = cov_case(phase0={"mode": "read-only\nFAIL[uncoded] phase0.py crashed (ValueError: x)"})
        e_kid = cov_case(phase0={"mode": "read-only\nFAIL[uncoded] dependencies.py crashed (ValueError: x)"})
        ctl()
        out.append(("E2E fix 1: a coverage roll-up that exits 1 after its summary line (the real case: one "
                    "outstanding Fail) is a current log, reported as findings to adjudicate; exit 0 with that summary, "
                    "exit 1 without it, a traceback, a signal, a Phase 0 exit 2 or a crash of Phase 0 itself are stale",
                    e_ok[0] == 0 and "current:" in e_ok[1] and "1 outstanding fail(s)" in e_ok[1]
                    and "not a crash" in e_ok[1]
                    and e_rc0[0] == 1 and "summary line says 1 outstanding" in e_rc0[1]
                    and e_cut[0] == 1 and "without its one summary line" in e_cut[1]
                    and e_tb[0] == 1 and "crashed" in e_tb[1]
                    and e_sig[0] == 1 and "signal" in e_sig[1]
                    and e_p2[0] == 1 and "no verdict matching its exit code 2" in e_p2[1]
                    and e_p0c[0] == 1 and "Phase 0 crashed" in e_p0c[1]
                    and e_kid[0] == 0 and "current:" in e_kid[1]))

        # 5. HEAD change during the run (Lean repo, then audits repo); a stale log from before a commit
        ctl(phase0={"sleep": 1.5})
        run("--adjudicator-checks", "--round", R)
        open(os.path.join(repo, "A.lean"), "a").write("y\n")
        g(repo, "commit", "-qam", "during")
        rc6, o6 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "30")
        gone()
        run("--adjudicator-checks", "--round", R)
        open(os.path.join(aud, "n.txt"), "w").write("n\n")
        g(aud, "add", "-A")
        g(aud, "commit", "-qm", "during")
        rc7, o7 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "30")
        gone()
        ctl()
        run("--adjudicator-checks", "--round", R, "--foreground")
        ok_before = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")[0]
        open(os.path.join(repo, "A.lean"), "a").write("z\n")
        g(repo, "commit", "-qam", "after")
        rc8, o8 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        out.append(("C3: a HEAD change during the run (Lean or audits repository) is stale even though the log "
                    "ends in END; so is a finished log from before a later commit",
                    rc6 == 1 and "HEAD line at the start is not the current" in o6
                    and rc7 == 1 and "AUDITS line at the start is not the current" in o7
                    and ok_before == 0 and rc8 == 1 and "STALE" in o8))

        # 6. mode mismatch vs TARGET.json: a wrong mode line; TARGET.json's kind changed after the run
        ctl(phase0={"mode": "author"})
        run("--adjudicator-checks", "--round", R, "--foreground")
        rc9, o9 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        ctl()
        run("--adjudicator-checks", "--round", R, "--foreground")
        tj(R, "statements")
        rc10, o10 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        tj(R, "full")
        out.append(("C3: a mode mismatch with TARGET.json is stale: Phase 0's mode line not `read-only` "
                    "(an author-mode output), or a kind changed since the run (KIND and command differ)",
                    rc9 == 1 and "mode line" in o9 and rc10 == 1 and "KIND line" in o10
                    and "did not run exactly" in o10))

        # 7. a killed worker (no END, no live holder) is stale at once; its dead lock is taken over
        ctl(phase0={"sleep": 30})
        run("--adjudicator-checks", "--round", R)
        pid = (_adj_lock(lock) or {}).get("pid")
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, TypeError):
            pass
        time.sleep(0.3)
        t0 = time.time()
        rc11, o11 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "30")
        fast = time.time() - t0 < 5
        ctl()
        rc12, _ = run("--adjudicator-checks", "--round", R, "--own", "--foreground")
        rc13, o13 = run("--wait-adjudicator-checks", "--round", R, "--own", "--timeout", "5")
        op_log = open(log()).read()
        out.append(("C3: a killed run (no END, its process gone) is stale at once, not waited on forever; its "
                    "lock is taken over by the next start; the adjudicator's own run (--own) writes "
                    "adjudicator-<R>-own.log and leaves the operator's log alone",
                    pid is not None and rc11 == 1 and fast and "no run is writing it" in o11 and rc12 == 0
                    and rc13 == 0 and "-own.log" in o13 and "(own run)" in open(log(R, True)).read()
                    and "(operator run)" in op_log and not op_log.endswith("END\n")))

        # 8. no log; another round's log; the worker cannot be run by hand; a stubbed log fails a real verify
        rc14, o14 = run("--wait-adjudicator-checks", "--round", R2, "--own", "--timeout", "5")
        shutil.copy(log(R2), log(R))
        rc15, o15 = run("--wait-adjudicator-checks", "--round", R, "--timeout", "5")
        rc16, o16 = run("--adjudicator-checks-worker", "--round", R, "--id", "0" * 16)
        run("--adjudicator-checks", "--round", R, "--foreground")
        real = dict(ctx, stub=None)
        good = open(log()).read()
        why, _, _ = adj_verify(real, R, False, good)
        h0 = _adj_heads(ctx)[0]
        why_end, _, _ = adj_verify(ctx, R, False, good.replace(f"HEAD {h0} (end)", "HEAD " + "0" * 40 + " (end)"))
        why_ok, _, _ = adj_verify(ctx, R, False, good)
        rc17, o17 = run("--wait-adjudicator-checks", "--round", "../x")
        out.append(("C3: no log, another round's log, a worker started by hand, a bad round name, a HEAD line "
                    "before END that differs are refused or stale; a log of stubbed commands never verifies outside the selftest (the real commands are "
                    "expected)",
                    rc14 == 1 and "no log" in o14 and rc15 == 1 and "first line" in o15 and rc16 == 2
                    and any("did not run exactly `python3 audits/phase0.py --readonly --project toy`" in w for w in why)
                    and why_ok == [] and any("HEAD line at the end" in w for w in why_end)
                    and rc17 == 2))
        # 9. the own run with --foreground started in the background (Bash run_in_background) and waited on at once
        ctl(phase0={"sleep": 1})
        os.remove(log(R, True))
        bg = subprocess.Popen([sys.executable, "-B", me, "--adjudicator-checks", "--round", R, "--own", "--foreground",
                               "--selftest"], cwd=repo, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        r18 = subprocess.run([sys.executable, "-B", me, "--wait-adjudicator-checks", "--round", R, "--own", "--timeout",
                              "30", "--selftest"], cwd=repo, capture_output=True, text=True, timeout=60,
                             env=dict(env, **{ADJ_TEST_ENV: json.dumps(dict(ctx, grace=5))}))
        rc18, o18 = r18.returncode, r18.stdout
        bg.wait(timeout=30)
        out.append(("C3: --own --foreground started in the background and waited on at once: the wait allows a "
                    "short grace for its header, then waits for END and accepts it", rc18 == 0 and "current:" in o18))
        out.append(("C3: the test hook is honoured only by a --selftest process",
                    _adj_ctx_guard(env)))
        out.append(("C3: every --adjudicator-checks / --wait-adjudicator-checks command the protocol prints is plain "
                    "and matches the project's allow rule for project.py (claude_settings.ALLOW), no deny rule",
                    _adj_allowed()))
    except Exception as e:      # noqa: BLE001 -- a failing control, not a crash
        out.append((f"C3: the background-checks controls ran ({type(e).__name__}: {e})", False))
    finally:
        try:
            pid = (_adj_lock(os.path.join(d, "repo", FW, ADJ_LOCK)) or {}).get("pid")
            if pid:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, TypeError, ValueError, NameError):
            pass
        shutil.rmtree(d, ignore_errors=True)
    return out


def _adj_ctx_guard(env):
    code = ("import sys, json; sys.path.insert(0, %r); import project as p\n"
            "try:\n    c = p._adj_ctx('no-such-project-x')\n    print(c.get('test'))\n"
            "except p.SelectionError:\n    print('refused')" % AUDITS)
    a = subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, text=True).stdout.split()
    b = subprocess.run([sys.executable, "-B", "-c", code, "--selftest"], env=env, capture_output=True,
                       text=True).stdout.split()
    return a == ["refused"] and b == ["True"]


ADJ_DOCS = ("AUDIT_PROTOCOL.md", "RUN.md", "run/stage4-rounds.md", "run/stage2-statements.md", "run/codex.md")


def _adj_allowed():
    import claude_settings as cs
    found = []
    for f in ADJ_DOCS:
        for m in re.finditer(r"`?(python3 audits/project\.py --(?:wait-)?adjudicator-checks[^`\n]*)`?",
                             open(os.path.join(AUDITS, f), encoding="utf-8").read()):
            found.append(m.group(1).strip())
    for own in (False, True):
        found += [_adj_cmd("adjudicator-checks", "2026-01-01-abcdef0", own),
                  _adj_cmd("wait-adjudicator-checks", "2026-01-01-abcdef0", own)]
    def ok(c):
        c = re.sub(r"<[^<>]+>", "R", c)
        if re.search(r"[;&|<>$`()\\\n]", c) or not c.startswith("python3 "):
            return False
        allow = [r[5:-3] for r in cs.ALLOW if r.startswith("Bash(") and r.endswith(":*)")]
        deny = [r[5:-3] for r in cs.DENY if r.startswith("Bash(") and r.endswith(":*)")]
        hit = lambda p: c == p or c.startswith(p + " ")
        return any(hit(p) for p in allow) and not any(hit(p) for p in deny)
    docs = [c for c in found if "adjudicator-checks" in c]
    return len(docs) >= 6 and all(ok(c) for c in found) and "Bash(python3 audits/project.py:*)" in cs.ALLOW


def _comment_only_lean_controls():
    """review of fix-mini2 H1, with Lean (`project.py --selftest --lean`): the Lean stage accepts a
    change to comments and docstrings, and refuses each code change the text stage misreads."""
    import tempfile, shutil
    if not shutil.which("lean"):
        return [("comment-only, Lean stage: `lean` is on PATH", False)]
    d = tempfile.mkdtemp(prefix="comment-only-lean-")
    out = []
    try:
        g = lambda *a: subprocess.run(["git", "-C", d, *a], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        f = os.path.join(d, "Foo", "A.lean")
        os.makedirs(os.path.dirname(f))
        open(f, "w").write(_CO_BASE)
        g("add", "-A"); g("commit", "-qm", "base")
        base = g("rev-parse", "HEAD").stdout.strip()
        cfg = {"lean_files": ["Foo/A.lean"]}

        def run(txt, b=_CO_BASE, bh=None):
            open(f, "w").write(txt)
            r = comment_only_since(cfg, bh or base, d, lean_cmd=["lean"])
            open(f, "w").write(b)
            return r
        # the control: a file without what the text filter refuses outright (lexer_ambiguous, re-check R3)
        plain = "\n".join(l for l in _CO_BASE.split("\n") if not lexer_ambiguous(l + "\n") and "«" not in l
                          and "s.length" not in l) + "\n"
        open(f, "w").write(plain); g("commit", "-qam", "plain")
        base_p = g("rev-parse", "HEAD").stdout.strip()
        doc = ("-- a new comment\n\n" + plain.replace("/-- doc -/", "/-- doc, now longer:\n two lines. -/")
               .replace("  · trivial\n", "  · trivial -- aaaaaaaaaaaa\n")
               .replace("private theorem", "/-- new -/\nprivate theorem"))
        ok = run(doc, plain, base_p)
        g("reset", "-q", "--hard", base)
        out.append(("review of fix-mini2 H1: Lean confirms a change to comments and docstrings only (lines "
                    "move, a docstring is added) as comment-only", ok[0]))
        for what, (a, b) in _CO_ATTACKS:
            assert a in _CO_BASE, what
            r = run(_CO_BASE.replace(a, b))
            out.append((f"review of fix-mini2 H1: a code change inside {what} is NOT comment-only (Lean "
                        "compares the compiled declarations)",
                        not r[0] and any("differs" in w or "differ:" in w or "cannot tell code from comment" in w
                                         for w in r[1])))
        # the Lean stage on its own (the text stage refuses every attack above first, so nothing else
        # reaches it with a real difference; tier 2 mutant rv-H1b survived without this control)
        lw = lean_identical(d, {"Foo/A.lean": (plain, plain.replace("def y := 1", "def y := 2"))}, lean_cmd=["lean"])
        out.append(("review of fix-mini2 H1: the Lean stage by itself reports a changed definition body",
                    any("differs" in w for w in lw)))
        # DESIGN-M7 §9.5 (UNVERIFIED-LEAN: written without a Lean run; these run in a real project's
        # `project.py --selftest --lean`). The docstring-only change above has a basis; binder names alone change only
        # the compiled bytes (O1 names them: layout); a binder annotation is O1's "binder annotations" (or a hash
        # difference): semantic either way; a `panic!` moved by a new comment line changes a value: NOT comment-only.
        g("reset", "-q", "--hard", base_p)
        open(f, "w").write(doc)
        dd = comment_only_detail(cfg, base_p, d, lean_cmd=["lean"])
        g("reset", "-q", "--hard", base)
        out.append(("DESIGN-M7 (UNVERIFIED-LEAN): a docstring-only change is comment-only on the compiled or the "
                    "source basis", dd["ok"] and dd["basis"] in ("compiled", "source")))
        m7 = ("theorem bn (n : Nat) : n = n := rfl\ntheorem ba (n : Nat) : n = n := rfl\n"
              "def pf (n : Nat) : Nat := if n = 0 then panic! \"x\" else n\n")
        names = lean_identical(d, {"Foo/A.lean": (m7, m7.replace("bn (n : Nat) : n = n", "bn (m : Nat) : m = m"))},
                               lean_cmd=["lean"])
        ann = lean_identical(d, {"Foo/A.lean": (m7, m7.replace("ba (n : Nat)", "ba {n : Nat}"))}, lean_cmd=["lean"])
        out.append(("DESIGN-M7 (UNVERIFIED-LEAN, review M1): binder names alone: one bytes-only reason, kind layout, "
                    "O1 naming binder names (not annotations); a binder annotation: semantic "
                    f"(got {[str(w)[:160] for w in names + ann]})",
                    [reason_kind(w) for w in names] == ["layout"] and "binder names (not their annotations)" in names[0]
                    and ann and all(reason_kind(w) == "semantic" for w in ann)
                    and any("binder annotations in" in w or "type or value of" in w for w in ann)))
        open(f, "w").write(m7); g("add", "-A"); g("commit", "-qm", "m7")
        base_m7 = g("rev-parse", "HEAD").stdout.strip()
        open(f, "w").write("-- a new first line\n" + m7)
        pm = comment_only_detail(cfg, base_m7, d, lean_cmd=["lean"])
        g("reset", "-q", "--hard", base)
        out.append(("DESIGN-M7 (UNVERIFIED-LEAN): a `panic!` moved down by a new comment line is NOT comment-only (its "
                    "value holds the line: the semantic veto)",
                    not pm["ok"] and any(reason_kind(w) == "semantic" and "pf" in w for w in pm["what"])))
        # review of the M7 build, H2 (UNVERIFIED-LEAN): O1 compares every field, not only types and values: `abbrev`
        # for `def` (equal type and value, other reducibility hints) names "other fields"; `def` for `theorem` names
        # the kind; never the sharing text
        hk = "abbrev hv : Nat := 1\ntheorem ka : True := trivial\n"
        hints = lean_identical(d, {"Foo/A.lean": (hk, hk.replace("abbrev hv", "def hv"))}, lean_cmd=["lean"])
        kind = lean_identical(d, {"Foo/A.lean": (hk, hk.replace("theorem ka", "def ka"))}, lean_cmd=["lean"])
        out.append(("review of the M7 build, H2 (UNVERIFIED-LEAN): O1 names other fields (`abbrev` for `def`) and the "
                    f"kind (`def` for `theorem`), both semantic (got {[str(w)[:160] for w in hints + kind]})",
                    hints and kind and all(reason_kind(w) == "semantic" for w in hints + kind)
                    and any("other fields of" in w for w in hints)
                    and any("the kind of" in w or "type or value of" in w for w in kind)
                    and not any(O1_LAYOUT[0] in w for w in hints + kind)))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


# Integrated review fix 1: the delivery phase is bounded. After the final full-scope round (the newest full proof
# round after the approved round: Stage 5 step 1's) at most DELIVERY_ROUND_CAP more proof rounds are asked for by the delivery:
# the diff round on that round's adoptions, and one diff round on every later Lean change of Stage 5 (the last round's
# adoptions, delegated decisions, Checkpoint C's answers) together. While fewer have run, a Lean commit after the last
# audited round is RED[deliver-stale] (run the diff round); once the cap is reached it is shipped, never re-audited,
# and disclosed (the report's and the summary's "Changes after the last audit round", the decisions document's item):
# each such round could adopt more fixes, so "a diff round per change" never ended. A newer full round (a
# re-approval's, RED[unverified]; one an adjudication item or an empty diff scope sends the run to) starts the count
# again: the delivery itself never asks for one on a Lean change past the cap.
DELIVERY_ROUND_CAP = 2


def delivery_rounds(cfg, rlist=None):
    """(the final full round's name or None, [names of the proof rounds after it]): the final full round is the
    newest full-scope proof round after the approved round (None: nothing approved, or no full round since)."""
    rounds_ = [os.path.basename(r) for r in (rounds(cfg) if rlist is None else rlist)]
    appr = approved_round(cfg)
    if not appr:
        return None, []
    rd = os.path.join(REPO, cfg["rounds_dir"])
    after = rounds_[rounds_.index(appr) + 1:] if appr in rounds_ else rounds_
    proof = [n for n in after if round_kind(os.path.join(rd, n)) in ("diff", "full")]
    # the NEWEST full proof round: Stage 4 opens with a full round too (scope.py refuses a first diff round), and its
    # diff rounds are not the delivery's (the mini5 honest path: counted from Stage 4's full round, the cap was
    # reached before Stage 5 began)
    last = max((i for i, n in enumerate(proof) if is_full_round(n) and round_kind(os.path.join(rd, n)) == "full"),
               default=None)
    return (None, []) if last is None else (proof[last], proof[last + 1:])


def delivery_cap(cfg, rlist=None):
    """None while the delivery may still ask for a round on a Lean change, else {"final", "after", "cap"}."""
    final, after = delivery_rounds(cfg, rlist)
    if final is None or len(after) < DELIVERY_ROUND_CAP:
        return None
    return {"final": final, "after": after, "cap": DELIVERY_ROUND_CAP}


def changes_after_last_audit(cfg, rounds):
    """What changed in the Lean since the last round that examined proofs (a diff or full round;
    a statement round examines statements only). `rounds` oldest first BY COMMIT TIME
    (order_rounds). Returns None if there is no such round, else a dict:
      round, commit            the last proof-examining round and its commit
      commits                  [oneline] after it touching lean_files or BUILD_FILES
      dirty                    [path] uncommitted changes to those files
      problem                  a sentence when the answer cannot be trusted, else None
      comment_only             every such change is comments and docstrings only (comment_only_detail)
      comment_only_basis       then "compiled" or "source" (DESIGN-M7: checked on the source), else None
      comment_only_lean        on the source basis, the Lean stage's reasons (the bytes-only ones), else []
    One implementation, used by make_report.py and decisions.py, so the two cannot disagree."""
    # a directory with no TARGET.json examined nothing: an empty-scope round (scope.py exit 3), or
    # one holding only fresh-reader prompts. Counting it hid a commit no reviewer saw (small-paper run).
    audit = [d for d in rounds if round_kind(d) not in ("statements", None)]
    if not audit:
        # an adjudicated round whose TARGET.json is missing or unreadable is no evidence that
        # nothing was examined: say so rather than drop the trust row (review of fix-mini1)
        odd = [d for d in rounds if round_kind(d) is None]
        if not odd:
            return None
        rd = odd[-1]
        return {"round": os.path.basename(rd), "commit": round_commit(os.path.basename(rd)), "commits": [],
                "dirty": [], "problem": f"no proof round has a readable TARGET.json (e.g. {os.path.basename(rd)}): "
                                        "what the audit rounds examined cannot be told; check by hand"}
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
    # mini2 audit (time): a change after the last round that is mechanically comment-only needs no round
    d = comment_only_detail(cfg, h) if (out["commits"] or out["dirty"]) else None
    out["comment_only"] = bool(d and d["ok"])
    out["comment_only_basis"] = d["basis"] if out["comment_only"] else None
    out["comment_only_lean"] = [str(w) for w in d["lean"]] if out["comment_only"] else []
    return out


USAGE = """usage:
  project.py --env-check                     PYTHONDONTWRITEBYTECODE=1 in this session? (run/stage1-setup.md)
  project.py --compile-source FILE.tex       xelatex twice, no shell escape, into .formalization-work/source-build/
  project.py --scratch NAME                  print a fresh scratch directory for one subagent
  project.py --license apache-2.0|none|FILE   Stage 1, intake 6c: write LICENSE in the project (never
                                             overwrites one; does not commit)
  project.py --prepare-delivery [--project NAME]   regenerate SUMMARY, REPORT, the DECISIONS box, the approved
                                             sheet's stamp and README A-C; record their hashes (DELIVERY.json)
  project.py --deliver [--project NAME]      check only (make_report.py --check --delivery, no stop or question
                                             open, the delivery gate, the render guard: each PDF the one
                                             render_record.py shipped for its md), then copy the deliverables
                                             (each PDF with its md beside it) into deliverables/ with README D
  project.py --check-delivered [--project NAME]   every PDF in deliverables/ is the one --deliver delivered
                                             (README D's sha256 of it, and its render record's)
  project.py --init-work-dir [--project NAME]        create the helpers' work_dir (git, excluded)
  project.py --work-commit MESSAGE [--project NAME] [PATH ...]   commit drafts in work_dir
  project.py --log SECTION [--project NAME] < TEXT   append TEXT under "## SECTION" of RUN_LOG.md
  project.py --stage TEXT [--project NAME]           set "## Current stage" of RUN_LOG.md to TEXT and print the file to read
  project.py --stage [--project NAME]                print the current stage and the file to read (resume)
  project.py --intake-save < TEXT                    Stage 0: save the intake answer before anything else (resume)
  project.py --intake-move [--project NAME]          Stage 1 step 5: move it under RUN_LOG.md's ## Intake
  project.py --adjudicator-checks --round R [--own] [--foreground] [--project NAME]
                                             start the adjudicator's Phase 0 (read-only; --statements from the
                                             round's TARGET.json) and coverage roll-up in the background, into
                                             .formalization-work/adjudicator-R[-own].log (one run at a time)
  project.py --wait-adjudicator-checks --round R [--own] [--timeout S] [--project NAME]
                                             wait at most S seconds (default 540) for that log's END, then verify
                                             it: exit 0 current, 1 stale (run them yourself, --own), 3 still running
  project.py --comment-only [BASE]                 are all Lean changes since BASE (default: the last proof round's commit)
                                                     comments and docstrings only? exit 0 yes, 1 no (fails closed)
  project.py --selftest [--floor]                 (--floor: the math gate's floor control on --deliver only)"""


def main(argv):
    if argv == ["--selftest"]:
        import integrity
        with integrity.run_history_hidden(AUDITS):     # the fixtures never see the run's applied tool patches
            return selftest()
    if argv == ["--selftest", "--floor"]:      # DESIGN-FLOOR: the math gate's floor control only (floor mutant MG2)
        checks = _floor_controls(tb=True)
        for name, ok in checks:
            print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        ok = all(c for _, c in checks)
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    if argv == ["--selftest", "--lean"]:
        checks = _comment_only_lean_controls()
        for name, ok in checks:
            print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        ok = all(c for _, c in checks)
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    if argv == ["--env-check"]:
        return env_check()
    name = None
    if "--project" in argv:
        i = argv.index("--project")
        name = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if argv[:1] in (["--adjudicator-checks"], ["--wait-adjudicator-checks"], ["--adjudicator-checks-worker"]):
        return adj_cli(argv, name)
    if argv[:1] == ["--scratch"] and len(argv) == 2:
        try:
            print(scratch(argv[1]))
            return 0
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
    if argv[:1] == ["--license"]:
        if len(argv) != 2:
            print("FAIL[tool-call] --license takes one argument: apache-2.0, none, or the path of a licence text")
            return 2
        rc, line = write_license(argv[1])
        print(line)
        return rc
    if argv[:1] == ["--comment-only"]:
        # `project.py --comment-only [BASE] [--project NAME]`: are all Lean changes since BASE (default:
        # the last proof-examining round's commit) comments and docstrings only? Exit 0 yes, 1 no
        rest = [a for a in argv[1:] if not a.startswith("--project")]
        try:
            cfg = select(next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--project=")), None))[0]
        except SelectionError as e:
            print(f"FAIL: {e}"); return 2
        base = rest[0] if rest else (changes_after_last_audit(cfg, rounds(cfg)) or {}).get("commit")
        if not base:
            print("FAIL: no proof-examining round to compare with; give a commit"); return 2
        d = comment_only_detail(cfg, base)
        ok, what = d["ok"], d["what"]
        print(("ok: comments and docstrings only since " if ok else "NO: not comment-only since ") + base
              + {"compiled": " (checked with Lean: the compiled modules are identical)",
                 "source": " (checked on the source: with comments and docstrings removed each changed file reads "
                           "exactly as before; Lean found the same declarations, types, values and attributes, but "
                           "the compiled files are not byte-for-byte identical)"}.get(d["basis"], ""))
        for w in what:
            print("  " + w)
        for w in d["lean"]:
            print("  Lean: " + w)
        return 0 if ok else 1
    if argv[:1] == ["--compile-source"] and len(argv) == 2:
        try:
            out = os.path.join(_fw_root(), "source-build")
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
        _exclude(FW + "/")
        return compile_source(argv[1], out)
    if argv == ["--stage"]:
        # resume: which stage the log says, and the file to read for it (RUN.md, "Start or resume")
        try:
            cfg = select(name)[0]
        except SelectionError as e:
            saved = intake_resume_hint()
            print(saved or f"no project selected ({e}): a new run; read now: audits/{STAGE_FILES[0]}")
            return 0
        stage = current_stage(cfg)
        if stage is None:
            saved = intake_resume_hint()
            print(saved or f"no RUN_LOG.md for project {cfg.get('name')}: a new run; read now: audits/{STAGE_FILES[0]}")
            return 0
        print(f"current stage: {stage or '(empty)'}")
        print(stage_hint(stage))
        return 0
    if argv == ["--intake-save"]:
        # B13 (U2 §8): Stage 0 saves the intake answer before anything else (before the branch exists)
        try:
            print(intake_save(sys.stdin.read()))
        except ValueError as e:
            print(f"FAIL[tool-call] {e}")
            return 1
        return 0
    if argv == ["--intake-move"]:
        try:
            print(intake_move(select(name)[0]))
        except (SelectionError, ValueError, OSError) as e:
            print(f"FAIL[tool-call] {e}")
            return 1
        return 0
    if argv[:1] in (["--log"], ["--stage"]) and len(argv) == 2:
        try:
            cfg = select(name)[0]
            if argv[0] == "--stage":
                p = log_append(cfg, "Current stage", argv[1], replace=True)
            else:
                p = log_append(cfg, argv[1], sys.stdin.read())
        except (SelectionError, ValueError, OSError) as e:
            print(f"FAIL: {e}")
            return 2
        print(f"logged in {os.path.relpath(p, REPO)} under \"## {'Current stage' if argv[0] == '--stage' else argv[1]}\"")
        if argv[0] == "--stage":
            print(stage_hint(argv[1]))
        return 0
    if argv[:1] in (["--init-work-dir"], ["--work-commit"], ["--deliver"], ["--prepare-delivery"], ["--check-delivered"]):
        try:
            cfg = select(name)[0]
        except SelectionError as e:
            print(f"FAIL: {e}")
            return 2
        if argv[0] == "--init-work-dir":
            return init_work_dir(cfg)
        if argv[0] == "--deliver":
            return deliver(cfg)
        if argv[0] == "--check-delivered":
            return check_delivered_cli(cfg)
        if argv[0] == "--prepare-delivery":
            rc, lines = prepare_delivery(cfg)
            for l in lines:
                print(l)
            return rc
        if len(argv) < 2:
            print(USAGE); return 2
        return work_commit(cfg, argv[1], argv[2:] or None)
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(run_main(main, sys.argv[1:]))

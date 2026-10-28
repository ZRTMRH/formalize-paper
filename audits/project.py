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
import datetime, fnmatch, functools, glob, hashlib, io, json, os, re, subprocess

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


def involvement(cfg):
    """The configured involvement level; "involved" when the key is absent. An invalid value is
    returned as it is (problems() reports it; callers refuse it rather than guess)."""
    v = cfg.get("involvement")
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
                                   "that is not in its result's assumption list: reword the line (or log a corrected "
                                   "one after it), or take the hypothesis as a binder of the result, commit, re-run "
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
    v = (cfg or {}).get("mode")
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
    "@check" (the check recorded at open), or None (kind human or disclose: no self-cure)."""
    if release_kind(code) in ("human", "disclose", "precondition"):
        return None
    form = CLOSER.get(code, "@check")
    return form if form == "@check" else "python3 audits/" + form.replace("{R}", round_name)


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

# The environment names a paper's numbered results may carry, as they appear in the index table.
RESULT_KINDS = ["Definition", "Lemma", "Theorem", "Proposition", "Corollary", "Claim", "Remark",
                "Example", "Conjecture", "Fact", "Observation", "Construction"]
RESULT_KINDS_RE = "|".join(RESULT_KINDS)


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
    return "--selftest" in (sys.argv if argv is None else argv)


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
    `python3 - <<EOF` edit (which asks for permission in Claude Code's default mode). Returns the
    log's path."""
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
             "every stop. The rest are its appendices. Each PDF is a rendering of the markdown delivered beside it, "
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


def readme_d(cfg, files, kept, dropped):
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
        lines.append(f"Fresh agents reviewed them ({', '.join(p_.lower() for p_ in have)}; `{REVIEW_DIR}/`)"
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
    rr_ = os.path.join(REPO, "deliverables", RUN_RECORD)
    if os.path.isfile(rr_) and not os.path.islink(rr_):
        lines += ["", "Delivered run record fingerprint (`python3 audits/project.py --check-delivered` compares it with "
                  "the file):", f"- `{RUN_RECORD}`: sha256 `{render_record.sha_file(rr_)}`"]
    return "\n".join(lines) + "\n"


DELIVERED_FP = re.compile(r"^- `([^`/]+\.pdf)`: sha256 `([0-9a-f]{64})`$")
DELIVERED_RR = re.compile(r"^- `RUN_RECORD\.md`: sha256 `([0-9a-f]{64})`$")


def check_delivered(cfg):
    """[problem] (review MED 3): every PDF in deliverables/ is the one --deliver delivered -- its sha256 is README D's
    fingerprint of it and the one its render record shipped -- and every fingerprinted PDF is there. A hash, never
    a reading of the PDF."""
    import render_record
    out = os.path.join(REPO, "deliverables")
    readme = os.path.join(out, "README.md")
    if os.path.islink(out) or not os.path.isfile(readme) or os.path.islink(readme):
        return [f"{os.path.relpath(readme, REPO)} is missing: nothing was delivered (python3 audits/project.py --deliver)"]
    fps, rr_fp = {}, []
    for line in open(readme, encoding="utf-8").read().splitlines():
        m = DELIVERED_FP.match(line.strip())
        if m:
            fps[m.group(1)] = m.group(2)
        m = DELIVERED_RR.match(line.strip())
        if m:
            rr_fp.append(m.group(1))
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
    probs = check_delivered(cfg)
    for p in probs:
        print("RED[deliver] " + " ".join(p.split()))
    print("delivered check: " + ("ok" if not probs else "NOT ok: deliver again (python3 audits/project.py --deliver); "
                                                       "never a stop"))
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
    t0, t = _now(), _Tee(sys.stdout)
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
                  f"by name")
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
    # make_report.py --check --delivery: deliver-stale is the gate's; every other code a note
    try:
        pre = make_report.delivery_problems(cfg)
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
    # README.md = README A-C as prepared (generated now when there is none), then section D (N6)
    ac_ = os.path.join(rd, README_AC)
    cover = (open(ac_, encoding="utf-8").read() if os.path.isfile(ac_) else (note("README A-C", readme_ac, cfg) or "")) \
        + (note("README section D", readme_d, cfg, files, kept, dropped) or "\n## D. Delivery notes\n\n(could not be "
                                                                            "written: see the notes)\n")
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(cover)
    delivered.append(os.path.join(out, "README.md"))
    notes += [f"[delivered check] {b}" for b in (note("the delivered check", check_delivered, cfg) or [])]
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
        _lc13 = dict(_lc, rounds_dir="audits/lt13"); os.makedirs(os.path.join(REPO, "audits", "lt13"))

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
        _m13 = intake_move(_lc13)
        _log13 = open(os.path.join(REPO, "audits", "lt13", "RUN_LOG.md")).read()
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
                       and "`JUDGEMENT.md`" in _cv9 and "reviewed them (claims, trust" in _cv9
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
    checks += _steady_clock_controls()
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    ok = all(c for _, c in checks)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def _release_controls(fake):
    """The run-mode classifier (RELEASE, CLASSIFICATION.md): [(check, passed)]."""
    rel, dev = {"mode": "release"}, {"mode": "dev"}
    import stops as _stops
    R_ = "2026-10-19-full-1a2b3c4"
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


def code_only(text):
    """The Lean `text` with every comment and docstring replaced by ONE space (it separates tokens;
    not blanked to its length, so editing a comment does not move the code after it), trailing
    blanks stripped and lines left empty dropped. String and char literal CONTENT is kept (unlike phase0.strip_comments), and a newline
    inside a string is kept as a literal sentinel, so a change inside a string is a code change.
    Leading indentation of code lines is kept (tactic blocks are indentation-sensitive)."""
    out, i, depth, n = [], 0, 0, len(text)
    while i < n:
        if depth == 0:
            if text.startswith("--", i):
                j = text.find("\n", i)
                i = n if j == -1 else j
                out.append(" ")
                continue
            if text[i] == '"':
                j = i + 1
                while j < n and text[j] != '"':
                    j += 2 if text[j] == "\\" else 1
                out.append(text[i:j + 1].replace("\n", "\x00"))
                i = j + 1
                continue
            m = re.match(r"'(\\.|[^\\'\n])'", text[i:i + 4])
            if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_'!?")):
                out.append(m.group(0)); i += len(m.group(0)); continue
        if text.startswith("/-", i):
            if depth == 0:
                out.append(" ")     # a comment separates tokens: `a/--/b` is `a b`, never `ab`
            depth += 1; i += 2; continue
        if depth and text.startswith("-/", i):
            depth -= 1; i += 2; continue
        if depth == 0:
            out.append(text[i])
        elif text[i] == "\n":
            out.append("\n")
        i += 1
    lines = [l.rstrip() for l in "".join(out).split("\n")]
    return "\n".join(l for l in lines if l.strip())


def lexer_ambiguous(text):
    """Why code_only's lexer may mistake code for a comment in `text` (re-check R3), or None: a `«…»`
    name holding `--`, `/-`, `-/` or a quote; a raw string `r"…"`/`r#"…"#` in code; an interpolated
    string with a quote inside its braces. The Lean stage compares what the .olean keeps, which is not
    everything (an `example`, a `#guard`), so a change the lexer misreads there is refused, not passed."""
    for m in re.finditer(r"«[^»]*»", text):
        if any(x in m.group(0) for x in ("--", "/-", "-/", '"', "'")):
            return f"the name {m.group(0)[:30]!r}"
    if re.search(r"(?<![\w'.!])r#*\"", code_only(text)):
        return "a raw string"
    if re.search(r'!"[^\n]*\{[^}\n]*["\']', text):
        return "an interpolated string with a quote in its braces"
    return None


def comment_only_since(cfg, base, repo=None, lean_cmd=None):
    """(True, [changed file]) when every change from commit `base` to the working tree touches only
    comments and docstrings of the project's Lean files; else (False, [reason]). Fails closed: a git
    error, a file outside `lean_files` (a build file, a new or deleted file), a file whose code
    differs with its comments removed (code_only), a project file naming a docstring reader
    (DOC_READERS: a proof could depend on a docstring), or a Lean comparison that differs or cannot
    run each make it False. The working tree is compared, so uncommitted edits count.

    Two stages. The text stage (code_only) is a quick filter only: its lexer does not model all of
    Lean (`«…»` names, raw and interpolated strings, user tokens), so it can mistake code for a
    comment (review of fix-mini2, H1); a file where it may (lexer_ambiguous) fails closed, as the Lean
    stage does not see an `example` (re-check R3). What decides is the Lean stage, lean_identical: every changed
    file is compiled before and after, and the compiled modules must be identical in every part
    except docstrings and source positions -- every declaration's type and value (statements,
    proofs, definition bodies), the declarations themselves, imports, attributes, notations and
    options' effects. `lean_cmd`: the command that runs Lean (default `lake env lean`, after
    `lake build`; the Lean selftest passes plain `lean` on a core-only fixture)."""
    repo = repo or REPO
    why, changed, texts = _comment_only_text(cfg, base, repo)
    if why or not changed:
        return (not why), (why or changed)
    why = lean_identical(repo, texts, lean_cmd)
    return (not why), (why or changed)


def _comment_only_text(cfg, base, repo):
    """The text stage of comment_only_since: ([reason], [changed file], {file: (old, new)})."""
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    r = git("diff", "--name-status", "--no-renames", base, "--")
    u = git("ls-files", "--others", "--exclude-standard")
    if r.returncode != 0 or u.returncode != 0:
        return [f"git could not compare {base} with the working tree: {(r.stderr or u.stderr).strip()[:160]}"], [], {}
    lean = set(cfg.get("lean_files", []))
    why, changed, texts = [], [], {}
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
        if code_only(old.stdout) != code_only(new):
            why.append(f"{path}: its code differs, not only its comments")
        else:
            amb = lexer_ambiguous(old.stdout) or lexer_ambiguous(new)
            if amb:
                why.append(f"{path}: {amb}: the text filter cannot tell code from comment there, and the "
                           f"compiled module does not keep everything (an `example`): not comment-only")
        changed.append(path)
        texts[path] = (old.stdout, new)
    for path in u.stdout.split():
        if path in lean:
            why.append(f"{path}: untracked")
    for rel in lean:
        p_ = os.path.join(repo, rel)
        if os.path.exists(p_) and DOC_READERS.search(code_only(open(p_, encoding="utf-8").read())):
            why.append(f"{rel}: its code reads docstrings, so a docstring can change what it proves")
    return why, changed, texts


OLEAN_PARTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "olean_parts.lean")


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
    try:
        if json.load(open(cache)).get(key) == "same":
            return []
    except (OSError, ValueError, AttributeError):
        pass
    mods = [t[:-len(".lean")].replace("/", ".") for t in sorted(texts) if t.endswith(".lean")]
    if lean_cmd is None:
        # the changed modules (hence their imports) as built from the working tree
        b = subprocess.run(["lake", "build", *mods], cwd=repo, capture_output=True, text=True)
        if b.returncode != 0:
            return ["Lean comparison not run: `lake build` failed: " + (b.stdout + b.stderr).strip()[-300:]]
    why = []
    d = tempfile.mkdtemp(prefix="comment-only-lean-")
    try:
        for path, (old, new) in sorted(texts.items()):
            mod = path[:-len(".lean")].replace("/", ".") if path.endswith(".lean") else None
            if not mod:
                why.append(f"{path}: not a .lean file"); continue
            parts = []
            for tag, txt in (("old", old), ("new", new)):
                root = os.path.join(d, tag, "src")
                src = os.path.join(root, path)
                os.makedirs(os.path.dirname(src), exist_ok=True)
                open(src, "w", encoding="utf-8").write(txt)
                ol = os.path.join(d, tag, "m.olean")
                out = os.path.join(d, tag, "parts-" + mod)
                try:
                    c = subprocess.run(cmd + ["--root=" + root, "-o", ol, src], cwd=repo,
                                       capture_output=True, text=True, timeout=7200)
                    p = c.returncode == 0 and subprocess.run(
                        cmd + ["--run", OLEAN_PARTS, ol, out, mod], cwd=repo,
                        capture_output=True, text=True, timeout=600)
                except (OSError, subprocess.TimeoutExpired) as e:
                    why.append(f"{path}: Lean comparison could not run ({e})"); break
                if c.returncode != 0:
                    why.append(f"{path}: the {tag} version does not compile, so it cannot be compared: "
                               + " ".join((c.stdout + c.stderr).split())[:200]); break
                if p.returncode != 0:
                    why.append(f"{path}: olean_parts failed on the {tag} version: "
                               + " ".join((p.stdout + p.stderr).split())[:200]); break
                parts.append(out)
            if len(parts) < 2:
                continue
            why += _parts_differ(path, *parts)
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
    return why


def _parts_differ(path, a, b):
    """The reasons the parts olean_parts.lean wrote into directories a and b differ ([] if none)."""
    def index(d):
        rows = [l.split("\t") for l in open(os.path.join(d, "index.tsv"), encoding="utf-8").read().splitlines()]
        return ({r[1]: r[2:] for r in rows if r[0] == "const"},
                {r[1]: r[2:] for r in rows if r[0] == "ext"}, [r[1] for r in rows if r[0] == "skip"])
    def data(d, f):
        return open(os.path.join(d, f), "rb").read()
    (ca, ea, _), (cb, eb, _) = index(a), index(b)
    why = []
    if set(ca) != set(cb):
        why.append(f"{path}: declarations differ: " + ", ".join(sorted(set(ca) ^ set(cb)))[:300])
    else:
        diff = sorted(n for n in ca if ca[n] != cb[n])
        if diff:
            why.append(f"{path}: the type or value of {', '.join(diff)[:300]} differs")
        elif data(a, "constants.olean") != data(b, "constants.olean"):
            why.append(f"{path}: its declarations or imports differ (compiled form)")
    for e in sorted(set(ea) | set(eb)):
        if e not in ea or e not in eb or ea[e][0] != eb[e][0] or data(a, ea[e][1]) != data(b, eb[e][1]):
            why.append(f"{path}: its {e} entries differ (attributes, notation, compiled code or similar)")
    return why


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
                    any("«x/-»" in w for w in hid) and any("«x/-»" in w for w in hid_doc)
                    and lexer_ambiguous('def r := r#"a"--b"#\n') == "a raw string"
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
               .replace("/-a-/", "/-aaaaaaaaaaaa-/").replace("private theorem", "/-- new -/\nprivate theorem"))
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
    out["comment_only"] = bool(out["commits"] or out["dirty"]) and comment_only_since(cfg, h)[0]
    return out


USAGE = """usage:
  project.py --env-check                     PYTHONDONTWRITEBYTECODE=1 in this session? (run/stage1-setup.md)
  project.py --compile-source FILE.tex       xelatex twice, no shell escape, into .formalization-work/source-build/
  project.py --scratch NAME                  print a fresh scratch directory for one subagent
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
  project.py --comment-only [BASE]                 are all Lean changes since BASE (default: the last proof round's commit)
                                                     comments and docstrings only? exit 0 yes, 1 no (fails closed)
  project.py --selftest"""


def main(argv):
    if argv == ["--selftest"]:
        import integrity
        with integrity.run_history_hidden(AUDITS):     # the fixtures never see the run's applied tool patches
            return selftest()
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
    if argv[:1] == ["--scratch"] and len(argv) == 2:
        try:
            print(scratch(argv[1]))
            return 0
        except ValueError as e:
            print(f"FAIL: {e}")
            return 1
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
        ok, what = comment_only_since(cfg, base)
        print(("ok: comments and docstrings only since " if ok else "NO: not comment-only since ") + base)
        for w in what:
            print("  " + w)
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

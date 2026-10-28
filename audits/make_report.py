#!/usr/bin/env python3
"""Assemble the handover report from the three maintained sources, verifying as it goes.

WHAT THE REPORT ANSWERS, and where each part comes from:

  1. which parts of the paper are formalized, which are skipped, and why
        -> the index table in the project's Main.lean, joined with SKIPPED.md
  2. which defects the paper has, with reasoning and a witness
        -> PAPER_DEFECTS.md
  3. what was proved differently from the paper, and why
        -> DEVIATIONS.md

WHY THIS IS GENERATED RATHER THAN WRITTEN. A hand-maintained summary of three files that change
every round is a fourth thing to keep in sync, and this project's own record on that is poor: two
copies of one instruction drifted apart inside a single day, twice. So the three sources are
authoritative and edited by the steps that know, the report is derived, and REPORT.md carries a
banner saying not to edit it.

WHAT IT VERIFIES, which is the part that makes it more than concatenation:

  - what a reader of the rendered report would trip over (rendering_problems): a LaTeX command
    outside a code span, an ID the report does not define, `File.lean:N` or `tex l.N` past the
    end of its file, a bare `l.N` that names no file.

  - every numbered result in the index is either formalized or has a SKIPPED.md row.
    A result in neither is UNACCOUNTED FOR and fails. This is the check that stops a result
    falling between "we did it" and "we decided not to".
  - every Lean name cited by any of the three sources exists in the project.
  - a SKIPPED.md row for a result the index says IS formalized is a contradiction, and fails.

Usage:
  make_report.py --project sparse-note            # write REPORT.md
  make_report.py --project sparse-note --check    # verify only, write nothing
  make_report.py --project sparse-note --selftest
Exit 1 on any verification failure; the report is still written so you can see the problem in
context, with the failures listed at the top.
"""
import argparse, json, os, re, sys, glob, datetime, subprocess
import collections, shutil
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402  (RESULT_KINDS lives there, once)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# What the report does and does not certify. One sentence (the PDF is a rendering of this markdown, made and checked
# by agents: render_record.py).
LIMITS_MD = ("**What this does not certify:** every Lean proof is checked by the Lean kernel, and "
             "the statements were reviewed by independent AI reviewers (coverage in the trust "
             "section), but nothing checks that a Lean proof follows the paper's argument. The "
             "entries below are the route changes that were recorded; a change nobody recorded is "
             "not listed.")


def decisions_tag_re():
    import decisions
    return decisions.DELEGATED_TAG_RE


def delegation(cfg):
    """(level, the human's verbatim intake answer, [each [DELEGATED] decision in RUN_LOG.md]), or
    None for the involved level when the log records no delegated decision. The intake chose who
    decides after it (RUN.md, question 5c); the report says so, and lists what the operator decided
    on the reader's behalf (AUDIT_PROTOCOL.md, "Documents a human reads", rule 4). The list is
    decisions.py's, so the report and the decisions document count the same decisions."""
    import decisions
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    dd = decisions.delegated_decisions(log)
    if not project.delegates(cfg) and not dd:
        return None
    return (project.involvement(cfg), str(cfg.get("involvement_answer") or "NOT RECORDED").strip(), dd)


def delegation_problems(cfg):
    """A level the scripts do not know, or [DELEGATED] decisions under a level that delegates
    nothing: either way the report cannot say truthfully who decided."""
    lvl = project.involvement(cfg)
    if lvl not in project.INVOLVEMENT_LEVELS:
        return [f"! project config: involvement is {lvl!r}, not one of {', '.join(project.INVOLVEMENT_LEVELS)}"]
    import decisions
    d = delegation(cfg)
    if d and not project.delegates(cfg):
        return [f"! RUN_LOG.md records {len(d[2])} [DELEGATED] decision(s), but the involvement level is "
                f"{lvl!r}, which delegates nothing: a decision taken for the human there is a [PROXY]"]
    out = []
    if project.delegates(cfg) and not str(cfg.get("involvement_answer") or "").strip():
        out.append(f"! project config: involvement is {lvl!r} but involvement_answer (the human's intake "
                   f"answer, verbatim) is not recorded, so the report cannot quote it")
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    out += ["! " + t for t in decisions.tag_problems(log, lvl if project.delegates(cfg) else None)]
    # review 1 (U2 §7f): every "escalation E<n>" the log cites exists and was accepted; under involved, a
    # re-ask of a NEEDS-HUMAN stays the human's question
    import lanecheck
    out += [project.Finding("! RUN_LOG.md " + t, "escalation-cite") for t in lanecheck.escalation_citations(cfg, log)]
    ap_ = os.path.join(REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json")
    if lvl == "statements-only" and os.path.exists(ap_):
        by_ = project.approval_file_by(ap_)[0]
        if by_ != "human":
            # statements-only keeps Checkpoint B for the human (RUN.md): an approval the human did
            # not make is outside the level, not something the intake authorized
            out.append(f"! the involvement level is statements-only, which keeps Checkpoint B for the human, "
                       f"but the statements were approved by {by_ or 'an unrecorded approver'}, not by a human")
    return out


DELEGATED_WHO = {
    "hands-off": "No human reviewed the Lean statements or any decision the protocol leaves to a person",
    "statements-only": "A person was asked only at Checkpoint B (the approval row above says who approved "
                       "the statements); no human reviewed any decision after that",
}


# Forgery review (H3, H4, LOW; the approver's threat model for the gates is a realistic operator, not a deliberate
# forger): the residual risk, disclosed where the reader decides how far to trust the run.
PROVENANCE = ("NOT CHECKED. The record proves consistency, not provenance: the checks verify that the run's records "
              "agree with each other and with the Lean, and that each was committed under its owner's commit message. "
              "They cannot tell a record written by its owner from one the operator wrote under the owner's name (a "
              "reviewer's verdict, an \"adjudicate\" commit, an answer logged as yours), they cannot detect a rewrite "
              "of the git history that is consistent throughout, and commit authors are not checked. An operator that "
              "deliberately forged could deliver a report that passes every check. What remains against it is outside "
              "the record: the independent review lanes as they ran, your sign-off, and the answers the summary lists "
              "as yours, each with the audit commit that recorded it (\"Answers recorded as yours\")")


def provenance_row(cfg):
    lvl = project.involvement(cfg)
    rm = core_fault_markers(cfg, ("record",))       # C2-FIX 5b: the provenance check itself could not run
    return ("Record provenance", "who wrote each record, and that the run's history was not rewritten",
            "".join(m + " " for m in rm) + PROVENANCE + (". Under hands-off nothing in this report rules a forgery out" if lvl == "hands-off" else "")
            + ". If the result matters, have a separate session run a fresh full audit round on the delivered commit.")


def trust_rows(cfg):
    """[(layer, what it establishes, status)] -- the report's statement of how far to trust it,
    computed from the records rather than written. EconCSLib's lesson: keep the evidence axes
    apart, and disclose a zero (no human review) rather than leave it out."""
    import audit_coverage as ac
    rd = os.path.join(REPO, cfg["rounds_dir"])
    head = delivered_commit(cfg)       # ADDENDUM N2: never HEAD
    # C2-FIX 5b (approver 2026-10-26; review 3): with any check that could not run, never "Phase 0 green": the plain
    # consequence of each Lean-side check that could not run (proofs complete, standard axioms, statements as
    # approved), then only what the other checks did establish
    kf = core_fault_markers(cfg, ("proof", "axioms", "statement"))
    if kf:
        kern = " ".join(kf)
    elif core_fault_markers(cfg):
        kern = (f"at commit {head} the Lean builds, every proof is complete and uses only Lean's standard axioms, and "
                f"the statements are the approved ones")
    else:
        kern = f"Phase 0 green at commit {head} (this report is regenerated only by a green Phase 0)"
    rows = [("Lean kernel",
             "every proof is valid; no sorry, no axiom beyond the standard three (axiom sweep)", kern)]
    import hypotheses       # B5 (U2 §2, F14): page 1 counts the hypotheses, source unavailable or not matching
    rows += hypotheses.trust_rows(cfg, rd)
    lanes, _ = ac.discover_lanes(rd)
    import io, contextlib
    with contextlib.redirect_stderr(io.StringIO()):
        state = ac.roll_up(ac.load_rounds(rd, lanes)) if lanes else {}
    if not state:
        rows.append(("AI reviewers", "each statement says what the paper says", "NO REVIEW ROUNDS RECORDED"))
    else:
        stale, _ = ac.stale_passes(rd, state)
        stale_keys = {(l, i) for l, i, _, _ in stale}
        # The latest adjudicator decision on each finding, across rounds (later rounds win).
        decided = rolled_decisions(rd)
        for lane in lanes:
            items = [(k, v) for k, v in state.items() if k[0] == lane]
            last = [v["last"] for k, v in items if k not in stale_keys]
            n = len(items)
            fails = [k for k, v in items if v["last"] == "Fail" and k not in stale_keys]
            dec = [decided.get(f"{lane} :: {ac.norm_item(i)}") for _, i in fails]
            fail_txt = fail_breakdown(dec, decision_words(rd, cfg))
            rows.append((f"AI reviewer: {lane}", ac_LANE_WHAT.get(lane, ""),
                         f"{last.count('Pass')} of {n} items passed; "
                         f"{fail_txt}; {ambiguous_words(last.count('Ambiguous'), cfg)}; "
                         f"{last.count('NotDoneYet')} not examined; "
                         f"{sum(1 for k in stale_keys if k[0] == lane)} stale"))
    # a lane no round ran is disclosed, not left out (small-paper run: nothing told the reader
    # that the paper's citations went unchecked)
    for lane in ac_LANE_WHAT:
        if lane not in lanes:
            rows.append((f"AI reviewer: {lane}", ac_LANE_WHAT[lane],
                         "NOT RUN: no round of this run had this lane, so nothing checked this"
                         + (" (the paper's citations included)" if lane == "prior-art" else "")))
    appr = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
    if os.path.exists(appr):
        a = json.load(open(appr))
        st = [r.get("status") for r in a.get("rows", {}).values()]
        how = {"individual": "result by result", "blanket": "as a blanket 'all OK'"}.get(a.get("how"), "manner not recorded")
        by, legacy_by = project.approval_file_by(appr, a)
        # Say who decided, in words a reader cannot misread (RUN.md Stage 2 step 8).
        est, who = {
            "human": ("a mathematician read the sign-off sheet and approved the statements; the "
                      "freeze check (Phase 0) proves none has changed since the approval",
                      "approved by a human"),
            "agent": ("NOT reviewed by a human: at Checkpoint B the user chose to let the agent "
                      "approve the sign-off sheet without reading it. The freeze check (Phase 0) "
                      "proves the statements have not changed since the approval",
                      "APPROVED BY THE AGENT, NOT BY A HUMAN"),
        }.get(by, ("the approver was not recorded, so treat the statements as NOT reviewed by a "
                   "human; the freeze check (Phase 0) proves none has changed since the approval",
                   "approver NOT RECORDED"))
        if by == "agent":   # nobody said "all OK" or answered per result: the agent approved all
            how = "by the agent, all at once"
            dl = delegation(cfg)
            if dl and dl[0] == "statements-only":
                # the level keeps Checkpoint B for the human: an agent approval is outside it (and a
                # report problem, delegation_problems), never "the user chose"
                est = ("NOT reviewed by a human, and NOT allowed at this level: the involvement level is "
                       "statements-only, which keeps Checkpoint B for the human, yet the agent approved "
                       "the sign-off sheet (the report check flags this). The freeze check (Phase 0) "
                       "proves the statements have not changed since the approval")
            if dl and dl[0] == "hands-off":
                # the human chose this at intake, not at Checkpoint B: say which, and quote it
                est = (f"NOT reviewed by a human: the agent approved the sign-off sheet without anyone "
                       f"reading it, under the {dl[0]} involvement level the user chose at intake "
                       f"(answer: \"{dl[1]}\"). The freeze check (Phase 0) proves the statements have "
                       f"not changed since the approval")
        note = f"; note: {a['note']}" if a.get("note") else ""
        if legacy_by:
            who, note = who + " (legacy)", note + f"; by: human ({project.LEGACY_BY_NOTE})"
        reaps = reapproval_rows(cfg)
        if reaps:
            # the freeze held only between re-approvals: never "none has changed" (ROUND3 H1)
            opened = [r for r in reaps if not r[4].startswith("closed")]
            est = re.sub(r"[Tt]he freeze check \(Phase 0\) proves (?:none has changed|the statements have "
                         r"not changed) since(?: the approval)?",
                         "the freeze check (Phase 0) proves no approved statement changed outside a "
                         f"re-approval; {len(reaps)} re-approval(s) during the run changed approved "
                         "statements (listed under \"Re-approvals during the run\")"
                         + (f", and {len(opened)} is STILL OPEN: its declarations changed with nobody "
                            "approving them" if opened else ""), est)
            note += "; re-approvals: " + "; ".join(f"{r[0]} for {r[1]} ({r[2]}), {r[4]}" for r in reaps)
        tl = statement_timeline(cfg, bool(reaps))
        if tl:
            note += f"; {tl}"
        # Earlier approvals, moved aside at a re-approval (RUN.md "Re-approval"): a human
        # re-approving only the CHANGED results after an agent approval must not make the whole
        # sheet read as human-reviewed.
        hist = []
        for f in sorted(glob.glob(os.path.join(rd, "APPROVED_FINGERPRINTS.*.json")), key=project.approval_order):
            try:
                h = json.load(open(f))
            except ValueError:
                continue
            hist.append(f"{h.get('date', '?')} by {h.get('by') or 'approver not recorded'}")
        if hist:
            note += "; earlier approvals: " + ", ".join(hist)
        rows.append(("Approval of statements", est,
                     (f"{who}: {st.count('approved')} of {len(st)} results approved {how}, "
                      f"{st.count('excluded')} excluded, on {a.get('date', '?')} at Lean commit "
                      f"{a.get('commit', '?')}{note}") if st else
                     f"{who}: {len(a.get('fingerprints', {}))} declarations approved {a.get('date', '?')} "
                     f"(older format: which results and how not recorded){note}"))
    else:
        rows.append(("Approval of statements", "a mathematician approves the statements",
                     "NONE: nobody has approved these statements"))
    dl = delegation(cfg)
    if dl:
        lvl, ans, dd = dl
        rows.append(("Decisions after the intake",
                     "who took the decisions the protocol leaves to a person (Checkpoints B and C, and "
                     "the stops between them)",
                     (f"DELEGATED, not taken by a human: at intake the user chose the {lvl} involvement "
                      f"level (answer, verbatim: \"{ans}\"). {who_decided(cfg, lvl)}. " if lvl in DELEGATED_WHO
                      else f"INCONSISTENT: the involvement level is {lvl!r}, yet ")
                     + f"The operator took {len(dd)} decision(s) on {n_matters(cfg, dd)} matter(s) on the reader's behalf, each final; "
                       f"each is listed in full in section \"{DECIDED_TITLE}\", and its reversal cost (none, "
                       f"re-prove, re-approve or new round) and how to reverse it are in "
                       f"`{os.path.join(rd, 'DECISIONS.md')}` (tagged [DELEGATED] in "
                       f"`{os.path.join(rd, 'RUN_LOG.md')}`)."))
    # approver (2026-10-24, RUN_RECORD): the apparatus, its re-pins, set-asides and self-cures are the process record
    # (RUN_RECORD.md); the report says only, in one line, when something weakened a check (weakened_row)
    wk = weakened_row(cfg)
    if wk:
        rows.append(wk)
    # a reissued lane is a process event: RUN_RECORD.md's "The audit apparatus" lists each (approver 2026-10-24)
    rows.append(PDF_ROW)
    rows.append(waiver_row(cfg))
    # B7 (U2 §7e): what the route row can and cannot say (the OUTCOMES coverage item was dropped)
    rows.append(("Proof routes", "the Lean proof follows the paper's argument",
                 "NOT CERTIFIED by anything; route changes listed are those recorded; slips are recorded when "
                 "found; proofs are not checked line by line against the paper"))
    rows.append(provenance_row(cfg))
    # Changes committed after the last audit round were never examined by a reviewer (RUN.md
    # Stage 5: the post-full diff round may itself adopt fixes). Say so, with the commits.
    row = later_row(cfg)
    if row:
        rows.append(row)
    # C2-FIX 5b (approver 2026-10-26): each row whose guarantee rests on a check that could not run says so first, in
    # plain words -- the statements' approval on the freeze and on the record's provenance, the reviewers' verdicts on
    # the record's provenance
    dep = {"Approval of statements": ("statement", "record"), "AI reviewer": ("record",), "AI reviewers": ("record",)}
    for i_, r_ in enumerate(rows):
        g_ = next((v for k_, v in dep.items() if r_[0] == k_ or r_[0].startswith(k_ + ":")), None)
        m_ = core_fault_markers(cfg, g_) if g_ else []
        if m_:
            rows[i_] = (r_[0], r_[1], " ".join(m_) + " " + r_[2])
    return rows


def mode_row(cfg, live=()):
    """The run mode: which failures stop the run. What was disclosed or self-cured instead of a stop is the process
    record (RUN_RECORD.md, approver 2026-10-24), never listed here; `live` is kept for callers and unused."""
    m = project.mode(cfg)
    if m == "release":
        st = ("RELEASE: a presentation or bookkeeping fault, or a crash of a tool that serves only those, does not "
              "stop the run; a fault of the record or the tools is cured by the agent with a fixed, logged step. Each "
              "is listed in RUN_RECORD.md (delivered with this report), not here")
    else:
        st = f"{m.upper()}: every check stops the run" + ("" if "mode" in cfg else " (no `mode` in the config)")
    return ("Run mode", "which failures stop the run: faithfulness, proof validity, integrity and the human "
            "stops always do", st)


HAND_DELIVERY = "delivered by hand: the final delivery checks did not run"
# approver 2026-10-26: plain words for the paper's author; the mechanism (which patch, its review) is RUN_RECORD.md's
TOOLS_PATCHED = ("the software that checks the formalization was corrected during this run (details for maintainers in "
                 "RUN_RECORD.md)")
RAISED_INTRO = ("Our checking software was corrected during this run. For each result below, the corrected version gives "
                "a stronger status than the original version gave on the same records; the status shown elsewhere in "
                "this report is the corrected version's, and the original one is quoted.")
RAISED_HEADING = "### Statuses decided by corrected checking software"


def hand_delivered(cfg):
    """True when a stop's answer, recorded as the human's, says the deliverables were copied by hand (not by
    project.py --deliver): the same rule as the summary's hand-delivery line."""
    import stops
    try:
        rows = stops.stop_rows(cfg, phase="run")
    except (OSError, ValueError):
        return False
    return any(is_hand_delivery(s_.get("answer") or "") for s_ in rows)


def is_hand_delivery(ans):
    """Does a human's stop answer say the deliverables were copied by hand?"""
    return bool(re.search(r"\bby hand\b", ans, re.I) and re.search(r"\b(deliver|cop(y|ied))", ans, re.I))


def tools_patched(cfg):
    """True when a tool patch was applied in this run (tool_patch.applied, or its raw provenance:
    integrity.applied_tool_patches -- a `tool-patch` re-pin or a `tool-patch TP<k> apply` commit)."""
    import integrity, run_record
    rd = os.path.join(REPO, cfg["rounds_dir"])
    try:
        return bool(run_record.applied_patches(cfg) or integrity.applied_tool_patches(project.AUDITS, rd))
    except Exception:       # noqa: BLE001 -- review R3: fail closed: the record cannot say, so the row says it may have
        return True


def weakened_row(cfg):
    """The ONE line of "How far to trust this" when something weakened a check (approver 2026-10-24), else None:
    a hand delivery (the final delivery checks did not run), and/or a patch of the audit tools. No details: those
    are in RUN_RECORD.md."""
    import tool_patch
    parts = ([HAND_DELIVERY] if hand_delivered(cfg) else []) + ([TOOLS_PATCHED] if tools_patched(cfg) else [])
    # SWEEP-FIX D4: every part the FIRST pin's tool_patch.verify_delivery requires on this row (weakened_parts)
    parts += [p_ for p_ in tool_patch.weakened_parts(cfg) if p_ not in parts]
    if not parts:
        return None
    return ("Checks weakened", "the final checks ran on the checking software as it was at the start", "; ".join(parts))


def reissue_row(cfg):
    """Every reissued lane of every round (lane_auth.py reissue: a lane whose spawn line was lost
    before it was sealed), with its reason and the earlier verdict kept as evidence. A reissue is
    the one way a lane's first answer can be set aside, so the reader is told about each."""
    import lane_auth
    items = []
    for r in project.rounds(cfg, include_abandoned=True):
        for h, lane, reason, files in lane_auth.reissues(r):
            items.append(f"{os.path.basename(r)}: {lane} (commit {h[:11]}): {reason}; earlier verdict "
                         + (", ".join(f"`{f}`" for f in files) if files else "NONE (no verdict file existed)"))
    status = ("none" if not items else f"{len(items)} lane(s) REISSUED (spawn line lost before sealing): "
              + "; ".join(items))
    return ("Lane reissues", "each lane answered once, under the token it was spawned with", status)


RESOLVED_TITLE = "Stops cleared without you"
# C2 audit (other fault 6): the intro said a self-cured stop was never of a STOP class and always a [DELEGATED]
# decision; a release self-cure may be of a STOP class (S1, freeze: restored) and is no decision (RUN.md, release)
RESOLVED_INTRO = ("A check or a tool call stopped the run, and nobody was asked: the operator closed it. In `dev` mode "
                  "that is a delegated close (never of a STOP class: tampering, the apparatus, approved statements, git "
                  "metadata, a sorry or an axiom, or anything uncoded), also a [DELEGATED] decision in `RUN_LOG.md` and "
                  "in the decisions document. In `release` mode it is a self-cure, of any class but a human stop: the "
                  "cure the cause table prints, closed by re-running the stop's recorded check, which must pass (RUN.md, "
                  "\"Stops and set-asides\"); a fault in the proof-validity core with no Lean-side workaround is "
                  "closed instead as not established, its check still failing. Its record is `<rounds dir>/stops/S<n>/`.")


def resolved_stops(cfg):
    """[(stop, date, the stop, cause classes, what was done, the check at the close)] of every stop
    the operator closed (stops.py close --delegated)."""
    import stops
    try:
        return [(r["stop"], r["date"] or "?", r["what"], ", ".join(r["classes"]), r["by"].split(": ", 1)[-1], r["done"])
                for r in stops.stop_rows(cfg, phase="run") if r["by"].startswith("the operator")]
    except (OSError, ValueError) as e:
        return [("?", "?", f"the stop record could not be read: {e}", "?", "", "")]


def record_fix_rows(cfg):
    """[[stop, date, the stop, class, who, outcome]] of every record correction ("record-fix R" commits,
    integrity.commit_record_fix): disclosed with the stops, cell by cell."""
    import integrity
    rd = os.path.join(REPO, cfg["rounds_dir"])
    try:
        fixes = integrity.record_fix_commits(project.AUDITS, os.path.relpath(rd, project.AUDITS), cfg)
    except (OSError, ValueError) as e:
        return [["record-fix ?", "?", f"the record corrections could not be read: {e}", "record-fix", "", ""]]
    return [[f"record-fix {r_}", d_, "record correction after round " + r_ + ": " + "; ".join(
        f"{f} row {k} '{c}' cell" for f, k, c in cells) + (
        f" -- NOT a record correction: {'; '.join(pr)}" if pr else
        " (a cited name was not a declaration: only that name changed; no verdict, decision or statement "
        "changed)"), "record-fix" + (", record-fix-diff" if pr else ""),
        "a fresh adjudicator (operator-run, no human)", f"committed in {h[:11]}"]
        for h, r_, d_, cells, pr in fixes]


def record_fix_problems(cfg):
    """`make_report --check`: a "record-fix R" commit that is not a record correction (its content
    re-verified, integrity.record_fix_commits) blocks, as integrity --check's record-fix-diff."""
    import integrity
    rd = os.path.join(REPO, cfg["rounds_dir"])
    try:
        fixes = integrity.record_fix_commits(project.AUDITS, os.path.relpath(rd, project.AUDITS), cfg)
    except (OSError, ValueError) as e:
        return [project.Finding(f"! the record corrections could not be read: {e}", "record-fix-diff")]
    return [project.Finding(f"! \"record-fix {r_}\" ({h[:11]}): {x}", "record-fix-diff")
            for h, r_, _d, _c, pr in fixes for x in pr]


ALL_STOPS_TITLE = "Every stop of the run"
ALL_STOPS_INTRO = ("Every stop the run recorded (`stops.py`), whoever cleared it -- the stop, the class of its "
                   "cause (a STOP class waits for the human at every level), who decided and the outcome -- then "
                   "every stop raised without a record (`RUN_LOG.md`, \"Open questions\").")


def all_stops(cfg):
    """[[stop, date, the stop, cause classes, who, outcome]] of EVERY recorded stop (human answers and
    open stops included), then every stop raised without a record (RUN_LOG.md "Open questions"
    entries: involved-level stops, the remaining stops every level keeps)."""
    import stops, decisions
    try:
        rows = [[r["stop"], r["date"] or "?", r["what"], ", ".join(r["classes"]), r["by"], r["done"]]
                for r in stops.stop_rows(cfg, phase="run") + stops.repair_rows(cfg) + stops.disclosed_rows(cfg, phase="run")]
    except (OSError, ValueError) as e:
        rows = [["?", "?", f"the stop record could not be read: {e}", "", "", ""]]
    rows += record_fix_rows(cfg)
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    for b in decisions.log_entries(decisions.section(log, "Open questions")):
        if decisions.PROXY_RE.search(b) or decisions.DELEGATED_RE.search(b):
            continue
        t = " ".join(b.lstrip("- ").split())
        rows.append(["no stop record", "", t, "", "the human" if "(answered" in t else "nobody yet",
                     "answered (see the stop)" if "(answered" in t else "OPEN"])
    return rows


SET_ASIDE_TITLE = "Set-asides and clearances"
SET_ASIDE_INTRO = ("Rounds and re-vote lanes given up before their adjudication (`stops.py set-aside`): every "
                   "file kept and committed, with the script's inventory of their lanes (sealed or not) and the "
                   "Fail or Ambiguous items it carried forward into the next adjudication, which had to give "
                   "each a row. Then every lane NOTE the adjudicator cleared in one line instead of a re-vote "
                   "(a lane that only named a record file), with the reason given.")


def set_asides(cfg):
    """[(what was set aside, date, by, inventory, reason)] (stops.py)."""
    import stops
    try:
        return [(r["scope"], r["date"] or "?", r["by"], r["summary"], r["reason"]) for r in stops.set_aside_rows(cfg)]
    except (OSError, ValueError) as e:
        return [("?", "?", "", f"the set-aside record could not be read: {e}", "")]


def all_clearances(cfg):
    """[(round, lane file, reason)] of every independence clearance in an ADOPTED.md (lanecheck)."""
    import lanecheck
    return [(os.path.basename(r), lane, why) for r in project.rounds(cfg, include_abandoned=True)
            for lane, why in lanecheck.clearances(r)]


def clearances_shown(cfg):
    """all_clearances as the report shows them: line numbers resolved from declaration names."""
    return [(r, l, refresh_lines(w, cfg)) for r, l, w in all_clearances(cfg)]


DECIDED_TITLE = "Decisions after the intake"


def delegated_items(cfg, dd):
    """The [DELEGATED] decisions, one entry per matter (decisions.delegated_by_matter): the decisions
    on one matter (a CHECK row, a QUESTION and an unused hypothesis on one lemma) are one entry, not
    separate decisions (mini2 audit: 23 entries for about 8 matters)."""
    import decisions
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    out = []
    for matter, ts in decisions.delegated_by_matter(cfg, log, dd):
        if matter and len(ts) > 1:
            out.append(f"**{matter}** ({len(ts)} decisions on this one matter): "
                       + " ".join(f"({k}) {t}" for k, t in enumerate(ts, 1)))
        else:
            out += ts
    return out


def delegated_list(cfg, dd):
    return "".join(f"- {t}\n" for t in delegated_items(cfg, dd))


ESCALATIONS_INTRO = ("Every one the run wrote, with its answer: an ANSWERABLE accepted by `lanecheck.py "
                     "--escalation` is a recommendation the operator may follow; a NEEDS-HUMAN is a question for "
                     "you, or under a delegating level a decision by the conservative rule; a later one on the "
                     "declaration of an earlier NEEDS-HUMAN or unanswered one is marked as its re-ask.")


def escalation_items(cfg):
    """[line] of every escalation check with its answer (lanecheck.escalation_line), in order: the
    DECIDED section lists them all, in the .md and the PDF (review 1: none hidden)."""
    import lanecheck
    recs = lanecheck.escalations(cfg)
    by = {e["name"]: e for e in recs}
    return [lanecheck.escalation_line(e, by) for e in recs]


def escalation_list(items):
    return ("**Escalation checks.** " + ESCALATIONS_INTRO + "\n\n"
            + ("".join(f"- {x}\n" for x in items) if items else f"- {NO_ESCALATION}\n"))


def n_matters(cfg, dd):
    """The number of matters the [DELEGATED] decisions are about (delegated_list's entries)."""
    import decisions
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    return sum(1 if m else len(ts) for m, ts in decisions.delegated_by_matter(cfg, log, dd))


def _added_in(rounds_dir, name, needle):
    """The short hash of the first audit commit whose `name` (in the rounds dir) contains `needle` (git's pickaxe),
    or "uncommitted"."""
    top, rel = project.rounds_rel(rounds_dir, name)
    if top is None:
        return "uncommitted"
    hs = subprocess.run(["git", "-C", top, "log", "--reverse", "--format=%h", "-S", needle, "--", rel],
                        capture_output=True, text=True).stdout.split()
    return hs[0] if hs else "uncommitted"


def _approval_receipt(rounds_dir, path):
    """The short hash of the audit commit that ADDED the approval file `path`'s content (the `approve <R>` commit), or
    "uncommitted". C2 audit fault (d): `git log -1` of a file moved aside at a re-approval
    (APPROVED_FINGERPRINTS.<date>.json) named the re-approval's commit (bbde24f), not the human's Checkpoint B
    approval (cfc6ff5): the content is found by its blob, wherever in the rounds dir it was first committed."""
    top, rel = project.rounds_rel(rounds_dir, os.path.basename(path))
    if top is None:
        return "uncommitted"
    blob = subprocess.run(["git", "-C", top, "hash-object", "--", path], capture_output=True, text=True).stdout.strip()
    hs = subprocess.run(["git", "-C", top, "log", "--reverse", "--format=%h", f"--find-object={blob}", "--",
                         os.path.dirname(rel) or "."], capture_output=True, text=True).stdout.split() if blob else []
    return hs[0] if hs else "uncommitted"


def reapproval_answers(cfg):
    """[(round, [declarations], words, the RUN_LOG.md line)] of the human's re-approval answers RUN_LOG.md records under
    `## Re-approvals` (or `## Answered`) as `- human answer (round <R>; <decls>): "<words>"` (fingerprint.HUMAN_ANSWER_RE,
    the form `signoff.py approve --by human` requires), in log order. C2 audit: the human's own re-approval words were
    in no delivered document."""
    import fingerprint
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    out = []
    for sec in re.findall(r"^## (?:Re-approvals|Answered)\b.*?$(.*?)(?=^## |\Z)", log, re.M | re.S):
        for ln in sec.splitlines():
            m = fingerprint.HUMAN_ANSWER_RE.match(ln)
            if m:
                out.append((m.group(1), [x.strip().strip("`") for x in m.group(2).split(",") if x.strip()],
                            m.group(3), ln.strip()))
    return out


def recorded_human_answers(cfg):
    """[(kind, label, text, words)] of every answer or approval the record attributes to the HUMAN after the intake
    (forgery review H2): the human's own answers under `## Checkpoint B` and `## Checkpoint C (<date>)` (trial #8;
    decisions.checkpoint_answers), each answer line of RUN_LOG.md `## Answered` that is the human's (decisions.human_answer:
    Checkpoint C and re-approval answers; labelled with the checkpoint whose answer it quotes), the human's re-approval
    answers under `## Re-approvals` (reapproval_answers; C2 audit: the operator's re-approval QUESTION to-do line under
    "Open questions" is not listed in their place), each stop the log records as answered by the human, each approval
    recorded `by: human` (APPROVED_FINGERPRINTS*.json: `signoff.py approve --by human`, first and re-approvals),
    each recorded stop the human closed. Each names the audit commit that recorded it (a receipt: for an approval the
    commit that added its content, _approval_receipt). The record
    cannot show who typed any of them: the summary lists them all for the human to check ("Answers recorded as
    yours"), and the report lists them as taken by the human."""
    import decisions, stops
    rd = os.path.join(REPO, cfg["rounds_dir"])
    p = os.path.join(rd, "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    out = []
    # trial #8: the human's own answers at Checkpoint B and Checkpoint C, as RUN_LOG.md logs them (`- human answer
    # (<date>): "<words>"` under `## Checkpoint B` / `## Checkpoint C (<date>)`): neither was shown back (the B
    # answer was in no delivered document; section 9 left out both)
    for cp, date, words in decisions.checkpoint_answers(log):
        line = next((l_ for l_ in log.splitlines() if decisions.CHECKPOINT_ANSWER_RE.match(l_) and words in l_), words)
        out.append(("answer", f"{date} Checkpoint {cp}",
                    f"\"{' '.join(decisions._unquote(words).split())}\" (RUN_LOG.md `## Checkpoint {cp}`; recorded in audit "
                    f"commit {_added_in(rd, 'RUN_LOG.md', line.strip())})", decisions._unquote(words)))
    for sec in re.findall(r"^## Answered\b.*?$(.*?)(?=^## |\Z)", log, re.M | re.S):
        for line in sec.splitlines():
            m = decisions.ANSWER_LINE_RE.match(line)
            if not m:
                continue
            body = line.strip()[2:].strip()
            if not decisions.human_answer(body):
                continue
            ans = decisions.ANSWER_PREFIX_RE.sub("", body, count=1).strip()
            occ = decisions.answer_occasion(log, body)
            out.append(("answer", f"{m.group(2) or 'undated'} {m.group(1)}" + (f" ({occ[0]})" if occ else ""),
                        f"\"{' '.join(decisions._unquote(ans).split())}\" (RUN_LOG.md `## Answered`"
                        + (f", round {m.group(3)}" if m.group(3) else "")
                        + f"; recorded in audit commit {_added_in(rd, 'RUN_LOG.md', line.strip())})", ans))
    # C2 audit: the human's re-approval answer, verbatim, with the commit that recorded it
    reap = reapproval_answers(cfg)
    for rnd, decls, words, line in reap:
        h = _added_in(rd, "RUN_LOG.md", line)
        d = subprocess.run(["git", "-C", rd, "show", "-s", "--format=%cs", h], capture_output=True,
                           text=True).stdout.strip() if h != "uncommitted" else ""
        out.append(("answer", f"{d or 'undated'} re-approval (round {rnd})",
                    f"\"{' '.join(decisions._unquote(words).split())}\" (RUN_LOG.md `## Re-approvals`, on "
                    f"{', '.join(decls)}; recorded in audit commit {h})", decisions._unquote(words)))
    answered_decls = [set(d) for _r, d, _w, _l in reap]
    for b in decisions.log_entries(decisions.section(log, "Open questions")):
        qm = re.match(r"\s*-?\s*re-approval QUESTION: the change to (.+?) \(", b)
        if qm and any({x.strip() for x in qm.group(1).split(",")} <= s for s in answered_decls):
            continue        # C2 audit: the operator's to-do line, not the human's answer (listed above, verbatim)
        if "(answered" in b and not decisions.PROXY_RE.search(b) and not decisions.DELEGATED_RE.search(b):
            first = b.splitlines()[0].strip() if b.strip() else b
            dm = re.search(r"\(answered (\d{4}-\d{2}-\d{2})", b)
            words = " ".join(b.lstrip("- ").split())
            out.append(("stop answer", f"{dm.group(1) if dm else 'undated'} open question",
                        f"\"{words}\" (RUN_LOG.md `## Open questions`; recorded in audit commit "
                        f"{_added_in(rd, 'RUN_LOG.md', first)})", words))
    files = sorted(glob.glob(os.path.join(rd, "APPROVED_FINGERPRINTS.*.json")), key=project.approval_order)
    files += [os.path.join(rd, "APPROVED_FINGERPRINTS.json")]
    for f in files:
        try:
            a = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if project.approval_file_by(f, a)[0] != "human":
            continue
        h = _approval_receipt(rd, f)
        out.append(("approval", f"{a.get('date', 'undated')} approval of round {a.get('round', '?')}",
                    f"statements recorded as approved by you (`signoff.py approve --by human`, "
                    f"{a.get('how') or 'manner not recorded'}) at Lean commit {str(a.get('commit', '?'))[:11]}"
                    + (f"; note: \"{' '.join(str(a['note']).split())}\"" if a.get("note") else "")
                    + f"; recorded in audit commit {h or 'uncommitted'} ({os.path.basename(f)})", a.get("note") or ""))
    try:
        for r in stops.stop_rows(cfg, phase="run"):
            if r["human"]:
                out.append(("stop", f"{r['date']} stop {r['stop']}",
                            f"{r['what']} -- decided by {r['by']}: {r['done']}",
                            f"stop {r['stop']} ({r['date']}): {r['what']} -- decided by {r['by']}: {r['done']}"))
    except (OSError, ValueError):
        pass
    return out


def human_decisions(cfg):
    """[text] of every decision a human took after the intake that the record shows: the setup
    at Checkpoint A, answers to stops (RUN_LOG.md "Open questions" entries marked answered, not
    tagged [PROXY]/[DELEGATED]), recorded stops the human closed, and (forgery review H2: they were
    missing) the human's answers under `## Answered` (Checkpoint C, re-approvals) and the approvals
    recorded `by: human`. The report must never say no human decided anything when one did (a test
    run, KNOWN_FAULTS), nor leave out an answer the record attributes to the human."""
    import decisions
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    out = []
    ca = decisions.section(log, "Checkpoint A").strip()
    if ca:
        out.append("Checkpoint A: the human approved the setup (RUN_LOG.md, \"Checkpoint A\": "
                   + project.full(ca) + ")")
    for kind, label, text, words in recorded_human_answers(cfg):
        if kind == "stop answer":
            # an answered `## Open questions` entry: a QUESTION row (a reading choice) or a stop's question
            out.append("an open question answered by the human: " + words)
        elif kind == "stop":
            out.append(words)
        elif kind == "answer":
            out.append(f"an answer recorded as the human's ({label}): {text}")
        else:
            out.append(f"{label}: {text}")
    return out


def vacuous_rows(cfg):
    """[(header, cells)] of VACUOUS.md as written (before the report sets LaTeX as code)."""
    import decisions
    p = os.path.join(REPO, cfg["rounds_dir"], "VACUOUS.md")
    text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    return [(h, c) for h, c in decisions.table_rows(text)
            if decisions._idx(h, "statement") is not None and len(c) > decisions._idx(h, "statement")]


def decided_since(cfg, header, cells, kind="vacuous"):
    """[DELEGATED] decisions in RUN_LOG.md on one VACUOUS.md row (`header`, `cells` as written); with
    kind="defect", on one PAPER_DEFECTS.md defects row (anchored lines only: `defect:<its anchor>: [DELEGATED ...]`;
    trial #11: row 2's decision cell said a companion "is left to the human" after the operator had decided it,
    and a whole round was run to have an adjudicator rewrite the cell, which it did not).
    VACUOUS.md is the adjudicator's, so a row stays "open" after the operator decided it; the report
    says so next to it instead of contradicting itself (small-paper run: "open" in the box and
    section 7, "decided" in section 9). Only a decision ON THIS ROW counts (review of fix-mini1, M2:
    any shared name, even a Mathlib lemma the row cites, used to count): a line under `## Open
    questions` or `## Checkpoint C` that starts with the canonical tag of the configured delegating
    level, and either is anchored to this row's `vacuous:` item, or is in the stage2 QUESTION form
    and names the declaration of the row's statement cell exactly (qualified, or its short name
    not preceded by another qualifier)."""
    import decisions
    lvl = project.involvement(cfg)
    if lvl not in ("hands-off", "statements-only"):
        return []
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    log = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    if kind == "defect":
        st = ""
        anchor = decisions.defect_anchor(header, cells).lower()
        legacy = decisions.defect_anchor(header, cells, legacy=True).lower()
    else:
        st = cells[decisions._idx(header, "statement")]
        anchor = decisions.vacuous_anchor(header, cells).lower()
        legacy = decisions.vacuous_anchor(header, cells, legacy=True).lower()     # trial #8: logged before the rehash
    names = set()
    for n in re.findall(r"`([A-Za-z_][\w'.]*)`", st):
        names |= {n, n.rsplit(".", 1)[-1]}
    out = []
    for sec in ("Open questions", "Checkpoint C"):
        for ln in decisions.section(log, sec).splitlines():
            m = re.match(r"(?:[-*][ \t]+)?(?:(" + kind + r":\S+?):[ \t]+)?(?=\[DELEGATED )", ln)
            t = decisions.DELEGATED_TAG_RE.match(ln, m.end()) if m else None
            if not t or t.group(2) != lvl:
                continue
            rest = ln[t.end():]
            earlier = False
            if m.group(1):
                # trial #11: the operator logs the anchor without its version (`defect:2-…-83b06f9598`, as the
                # decisions check accepts it): that names the row as it is now, not an earlier version of it
                ok = m.group(1).lower() in (anchor, legacy) or (
                    "@" not in m.group(1) and m.group(1).lower() == anchor.split("@")[0])
                # the same row (rows are numbered and never removed) at an earlier version: a round
                # refreshed its line citations or wording after the decision, which changed the anchor's
                # hash, and the row read "open" beside a decision on it (mini2 audit)
                if not ok and re.match(kind + r":(\d+)-", m.group(1)) and \
                        re.match(kind + r":(\d+)-", m.group(1)).group(1) == str(cells[0]).strip():
                    ok = earlier = True
            elif kind == "defect":
                ok = False      # a defect row is decided only by a line anchored to it
            else:
                # the QUESTION row the line answers must be this row's: its item is the declaration
                # or the statement's paper label; with no item, the decision before the form names
                # the declaration (re-check of fix-mini1: a line on another item that merely
                # mentions it later counted)
                q = decisions.QROW_RE.search(rest)
                item = (q.group("item") or "").strip().strip("`").strip() if q else ""
                if not q:
                    ok = False
                elif item:
                    ok = item in names or re.match(re.escape(item) + r"(?![\w.])", st, re.I) is not None
                else:
                    ok = any(re.search(rf"(?<![\w'.]){re.escape(n)}(?![\w'])", rest[:q.start()]) for n in names)
            txt_ = ln[t.start():].strip() + (" (decided on an earlier version of this row)" if earlier else "")
            if ok and txt_ not in out:
                out.append(txt_)
    return out


def defect_rows_raw(cfg):
    """{row number: (header, cells)} of PAPER_DEFECTS.md's defects table as written (decisions.defect_rows: the
    parse its anchors are computed from)."""
    import decisions
    return {c[0]: (h, c) for h, c in decisions.defect_rows(os.path.join(REPO, cfg["rounds_dir"]))
            if c and decisions.is_defect_header(h)}


def settle_defect_rows(cfg, header, rows):
    """In place: each PAPER_DEFECTS.md row (as the report shows it) whose row has a [DELEGATED] decision since
    (decided_since, kind "defect") gets its decision cell settled_cell'd."""
    dc_col = next((i for i, h in enumerate(header or []) if h.startswith("decision")), None)
    raw_d = defect_rows_raw(cfg)
    for row in rows:
        found = decided_since(cfg, *raw_d[row[0]], kind="defect") if row and row[0] in raw_d else []
        if found and dc_col is not None and dc_col < len(row):
            row[dc_col] = settled_cell(row[dc_col], found)
    return rows


def decided_since_defect(cfg, num):
    """decided_since for the PAPER_DEFECTS.md row numbered `num` ([] when there is none)."""
    raw = defect_rows_raw(cfg).get(str(num).strip())
    return decided_since(cfg, *raw, kind="defect") if raw else []


def decided_since_text(cfg, text):
    """decided_since for the VACUOUS.md rows whose statement cell `text` (a box line) quotes."""
    import decisions
    return [f for h, c in vacuous_rows(cfg) if c[decisions._idx(h, "statement")] in text
            for f in decided_since(cfg, h, c)]


# a decision cell that leaves the matter to a person (trial #11: "Whether to add a companion ... is left to the
# human."): once a [DELEGATED] decision on the row is logged, the report shows that sentence as the row's text when
# it was written, followed by the decision, so the generated documents never say a person will still decide it
DEFER_RE = re.compile(r"\b(?:left|deferred)\s+(?:open\s+)?(?:to|for)\s+(?:the\s+)?(?:human|person|approver|you)\b"
                      r"|\bpending\s+(?:a\s+|the\s+)?(?:human(?:'s)?\s+|person's\s+)?decision\b"
                      r"|\bfor\s+the\s+(?:human|person|approver)\s+to\s+decide\b"
                      r"|\bawait(?:s|ing)?\s+(?:the\s+)?(?:human|person|approver|a\s+decision)\b"
                      r"|\b(?:the\s+)?(?:human|person|approver)\s+(?:decides|will\s+decide|is\s+to\s+decide)\b",
                      re.I)
# a sentence ends at a full stop (or ! ?) followed by a space or the end. conf1 (C1 audit, defect 1): the old pattern
# could not cross a stop inside a word ("Results.lean", "4.1.", "VACUOUS.md"), so finditer skipped ahead and the
# cell lost everything before it ("1. Chosen by ...", "md row 1; ..."). This one consumes such a stop and never
# skips a character: the sentences always join back to the cell (settled_cell checks it)
SENTENCE_RE = re.compile(r"(?:[^.!?]|[.!?](?![\s]|$))*(?:[.!?]+(?=\s|$)|$)\s*")


def settled_cell(cell, found):
    """A record's decision cell with the [DELEGATED] decisions `found` (decided_since) on its row: each sentence that
    leaves the matter to a person (DEFER_RE) is quoted as what the row said when it was written, and the decision
    is appended (since_note). Unchanged when nothing was decided since."""
    if not found:
        return cell
    parts = []
    sents = [m.group(0) for m in SENTENCE_RE.finditer(cell) if m.group(0)]
    if "".join(sents) != cell:      # never a dropped word: the cell as one sentence
        sents = [cell]
    for sent in sents:
        if DEFER_RE.search(sent):
            sent = f"(when this row was written: \u201c{sent.strip()}\u201d) "
        parts.append(sent)
    return "".join(parts).rstrip() + " -- " + since_note(found)


def since_note(found):
    """The sentence decided_since's decisions add to a record's open status."""
    # trial #7 audit: "section 9" is the decisions section only without reader notes: it is named by title
    return ("decided since by the operator (RUN_LOG.md): " + project.full(found[-1])
            + (f" ({len(found) - 1} earlier [DELEGATED] decision(s) on it in section \"{DECIDED_TITLE}\")"
               if len(found) > 1 else ""))


def who_decided(cfg, lvl):
    """The sentence of the trust table that says who took the decisions the protocol leaves to a
    person, from the record: never "no human took any decision" when the human answered a stop."""
    n = len([h for h in human_decisions(cfg) if not h.startswith("Checkpoint A")])
    base = DELEGATED_WHO[lvl].split(" or any decision")[0] if lvl == "hands-off" else DELEGATED_WHO[lvl].split("; no human")[0]
    if n:
        return (f"{base}. The record attributes {n} answer(s), approval(s) or stop decision(s) after the intake to "
                f"the human (section \"{DECIDED_TITLE}\" lists each, with the answer; the summary asks you to check "
                f"them); every other decision the protocol leaves to a person was taken by the operator")
    return (f"{base}. Apart from the setup at Checkpoint A, no human took a decision the protocol leaves to a "
            f"person after the intake")


def setaside_row(cfg):
    """Rounds and re-vote lanes set aside (stops.py set-aside), with the items each carried forward:
    they are in the record but no script counts them as adjudicated."""
    items = [f"{r[0]} SET ASIDE ({r[1]}, {r[2]}): {r[3]}" for r in set_asides(cfg)]
    return ("Set-aside rounds and lanes", "every round's and re-vote's verdicts were adjudicated",
            "none" if not items else "; ".join(items))


def reapproval_rows(cfg):
    """[(begun, declarations, reason, level, closed by)] for every re-approval of the run (ROUND3
    H1), from fingerprint.reapprovals: the trust table and section 1 list each."""
    import fingerprint as _fp
    rows, ans = [], reapproval_answers(cfg)
    for c in _fp.reapprovals(os.path.join(REPO, cfg["rounds_dir"]), cfg):
        bs = c.get("begins") or [{}]
        # C2 audit: where the re-approval is listed, the human's own words (the answer that closing approve required)
        rnd = str(c.get("closed_by") or "").split("approve ", 1)[-1] if c.get("closed") else ""
        said = [w for r_, d_, w, _l in ans if rnd and r_ == rnd and set(c.get("decls") or []) <= set(d_)]
        rows.append(("; ".join(f"{b.get('date', '?')} at Lean {str(b.get('lean_head', '?'))[:11]}" for b in bs),
                     ", ".join(f"`{d}`" for d in (c.get("decls") or [])) or "?",
                     "; ".join(str(b.get("reason", "?")) for b in bs),
                     ", ".join(sorted({str(b.get("involvement", "?")) for b in bs})),
                     (f"closed by `{c.get('closed_by', '?')}` on {c.get('closed_date', '?')}"
                      + "".join(f"; the human's answer (RUN_LOG.md, Re-approvals): “{' '.join(w.split())}”"
                                for w in said) if c.get("closed")
                      else "OPEN: never closed by `signoff.py approve`")))
    return rows


def statement_timeline(cfg, reapproved=False):
    """Verifiable facts only (test-run audit, caveat 1): when the statements were committed (the first
    statement round's commit and its time), when and at which commit they were approved, and that
    the freeze check (fingerprints) shows them unchanged since. Never "before any proof was written",
    which nothing in the record establishes."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    first = next((r for r in project.rounds(cfg, include_abandoned=True) if project.round_kind(r) == "statements"), None)
    parts = []
    if first:
        c = project.round_commit(os.path.basename(first))
        t = subprocess.run(["git", "-C", REPO, "show", "-s", "--format=%ci", c], capture_output=True, text=True).stdout.strip()
        parts.append(f"statements committed at {c}" + (f" ({t})" if t else ""))
    ap = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
    if os.path.exists(ap):
        try:
            a = json.load(open(ap))
        except ValueError:
            a = {}
        t = subprocess.run(["git", "-C", os.path.join(REPO, "audits"), "log", "-1", "--format=%ci", "--diff-filter=A", "--",
                            os.path.relpath(ap, os.path.join(REPO, "audits"))], capture_output=True, text=True).stdout.strip()
        parts.append(f"approved for commit {a.get('commit', '?')}" + (f" (approval recorded {t})" if t else f" ({a.get('date', '?')})")
                     + ("; changed since only through the re-approvals listed, by the freeze check of their "
                        "fingerprints (Phase 0)" if reapproved else
                        "; unchanged since, by the freeze check of their fingerprints (Phase 0)"))
        if first:
            try:
                at_ = json.load(open(os.path.join(rd, str(a.get("round")), "FINGERPRINTS.json"))).get("fingerprints")
            except (OSError, ValueError, AttributeError):
                at_ = None
            ch = statement_changes(os.path.join(first, "FINGERPRINTS.json"), a.get("fingerprints") or {}, at_)
            parts.append(f"between the first statement round ({os.path.basename(first)}) and the approval, "
                         + (f"{len(ch)} statement(s) changed: " + ", ".join(ch) if ch else "no statement changed")
                         + " (fingerprints compared)")
    return "; ".join(parts)


def statement_changes(first_fp_path, approved, at_approval=None):
    """[name (changed|added|removed)] between the first statement round's fingerprints and the
    approved ones: what changed after the statements were first reviewed (review round 2, N8).
    `at_approval` is every fingerprint of the approved round: a name the approval does not list
    (a helper, a definition) is "removed" only if that round no longer has it either (the
    small-paper run reported five existing declarations as removed)."""
    try:
        first = json.load(open(first_fp_path)).get("fingerprints") or {}
    except (OSError, ValueError, AttributeError):
        return ["(the first statement round's FINGERPRINTS.json cannot be read)"]
    now = dict(at_approval or {}, **approved)
    return ([f"`{n}` changed" for n in sorted(set(first) & set(now)) if first[n] != now[n]]
            + [f"`{n}` added" for n in sorted(set(approved) - set(first))]
            + [f"`{n}` removed" for n in sorted(set(first) - set(now))])


# QUESTION: whether the human answered each one is recorded per item in the decisions document,
# not here; the report never infers "answered" or "not yet answered" (it once said "not yet
# answered" for 45 questions the human had answered)
DECISION_WORDS = {"ADOPT": "adopted", "REJECT": "rejected", "DEFER": "deferred",
                  "QUESTION": "put to the human as questions",
                  "UNCOVERED": "left uncovered, with no decision"}


def decision_words(rd, cfg=None):
    """DECISION_WORDS, pointing QUESTION to the decisions document when the record has one. Under a
    level that delegates Checkpoint C no human was asked: the QUESTION rows were decided by the
    operator (mini2 audit: "put to the human as questions" under hands-off)."""
    words = dict(DECISION_WORDS)
    dpath = os.path.join(rd, "DECISIONS.md")
    if cfg is not None and project.delegates(cfg):
        words["QUESTION"] = (f"raised as questions, decided by the operator under the "
                             f"{project.involvement(cfg)} level, not by a human (section \"{DECIDED_TITLE}\")")
        if os.path.exists(dpath):
            words["QUESTION"] += f"; `{dpath}`"
    elif os.path.exists(dpath):
        words["QUESTION"] += f" (the decisions put to the human: `{dpath}`)"
    return words


def ambiguous_words(n, cfg=None):
    """'N ambiguous', with what became of them: an Ambiguous verdict (a reading choice) is a QUESTION
    row of that round's ADOPTED.md (AUDIT_PROTOCOL.md, adjudication rule C); the report said only "7
    ambiguous" (mini2 audit)."""
    if not n:
        return "0 ambiguous"
    who = ("decided by the operator, not by a human" if cfg is not None and project.delegates(cfg)
           else "for the human to decide")
    return (f"{n} ambiguous (a reading choice the lane could not settle; each is a QUESTION row in its round's "
            f"ADOPTED.md, {who})")


def rolled_decisions(rd):
    """{"lane :: item": decision} across rounds, later rounds winning -- except that UNCOVERED, a
    coverage status rather than a decision, never replaces a decision."""
    import audit_coverage as ac
    decided = {}
    for d in project.order_rounds([x for x in glob.glob(os.path.join(rd, "*")) if os.path.isdir(x)],
                                  ac._repo_of(rd)):
        for k_, v_ in ac.read_adopted(os.path.join(d, "ADOPTED.md")).items():
            if v_ != "UNCOVERED" or k_ not in decided:
                decided[k_] = v_
    return decided


def fail_breakdown(dec, word):
    """"N Fail verdicts (a adopted, b rejected, ...)": every Fail is in exactly one part, so the
    parts add up to N (a decision kind missing from `word` would silently drop its Fails)."""
    if not dec:
        return "0 Fail verdicts"
    kinds = list(word) + sorted({d for d in dec if d is not None and d not in word})
    parts = [f"{dec.count(x)} {word.get(x, x.lower())}" for x in kinds if dec.count(x)]
    if dec.count(None):
        parts.append(f"{dec.count(None)} with no recorded decision")
    return f"{len(dec)} Fail verdicts ({', '.join(parts)})"


def later_row(cfg):
    """The trust-table row for changes after the last proof-examining round (None: no such round)."""
    c = project.changes_after_last_audit(cfg, project.rounds(cfg))
    if c is None:
        return None
    what = "every Lean change was examined by at least one audit round"
    name = "Changes after the last audit round"
    where = f"last audit round {c['round']} (commit {c['commit']})"
    if c["problem"]:
        return (name, what, f"UNKNOWN: {c['problem']}")
    parts = []
    if c["commits"] and c.get("comment_only"):
        # mini2 audit (time): verified mechanically, so no round was run for it
        parts.append(f"{len(c['commits'])} commit(s) since {where} change ONLY comments and docstrings "
                     "(verified mechanically: each changed file, compiled before and after, gives identical "
                     "declarations -- statements, proofs, definition bodies, attributes -- `project.py "
                     "--comment-only`; no statement or proof changed); the changed "
                     "docstrings themselves were not re-read by an audit lane: " + "; ".join(c["commits"]))
    elif c["commits"]:
        cap = project.delivery_cap(cfg)
        parts.append(f"{len(c['commits'])} commit(s) since {where} NOT re-audited (checked only by "
                     "Phase 0)" + (f", shipped as they are: the delivery phase's round cap is reached ({len(cap['after'])} "
                                   f"round(s) after the final full round {cap['final']}, at most {cap['cap']})"
                                   if cap else "") + ": " + "; ".join(c["commits"]))
    if c["dirty"]:
        parts.append("UNCOMMITTED changes to " + ", ".join(c["dirty"]))
    return (name, what, " ".join(parts) if parts else
            f"none: no commit since {where} touches the project's Lean or build files")


ac_LANE_WHAT = {
    "correspondence": "the Lean statement means what its English description says",
    "paper-faithfulness": "the Lean results are the paper's results, no weaker, no stronger",
    "non-vacuity": "hypotheses can be satisfied; definitions describe something",
    "substantiveness": "statements are at the right strength and not repackaged",
    "prior-art": "Mathlib does not already have it (quality, not correctness)",
}

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_'!?₀-₉ₐ-ₜ]*(?:\.[A-Za-z_][A-Za-z0-9_'!?₀-₉ₐ-ₜ]*)*$")
DECL = r"(?:theorem|lemma|def|abbrev|structure|inductive|class|instance|noncomputable def)"
# an index row: a kind and a label. C2 audit (fault (b)): a number was required, so the unnumbered row
# "Definition (notation 𝒬(n), tex l.38-39)" -- approved and frozen (signoff.index_rows, scope.INDEX_ROW read it) --
# was left out of the coverage table, the statuses and the summary (11 listed against 12 approved). One parser
# now: every row the freeze and the sheet read
RESULT = re.compile(rf"^(?:{project.RESULT_KINDS_RE})\s+\S", re.I)
NUMBERED = re.compile(rf"^(?:{project.RESULT_KINDS_RE})\s+[\d.]*\d", re.I)
NOT_FORMALIZED = re.compile(r"not formalized|no new statement|deferred|out of scope", re.I)


def declared_names(lean_files):
    """Every name declared in the project, as written and fully qualified (scope.py's parser,
    which ignores comments)."""
    import scope
    names = set()
    for rel in lean_files:
        f = os.path.join(REPO, rel)
        if os.path.exists(f):
            for q in scope.parse_decls(open(f, encoding="utf-8").read()):
                if q != "_unnamed":
                    names |= scope.short_names(q)
    return names


def table_rows(path):
    """Rows of the first markdown table in `path`, as lists of cells."""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        st = line.strip()
        if not st.startswith("|") or set(st) <= set("|-: "):
            continue
        cells = project.split_row(st)
        if cells and cells[0].lower() in ("#", "paper", "lane", "result", "item"):
            continue
        out.append(cells)
    return out


# Only a name matching the PROJECT's own convention is unambiguously ours, so only that can be
# a hard failure. Backticked text is also full of mathematical notation (`v(G) >= 2`, `t(K3,T)`)
# and of Mathlib lemma names, and the first version of this check reported all of them: six
# "undeclared" names, none of which was a defect. A checker whose first real run is all false
# positives teaches its reader to skim it.
OURS = re.compile(r"^(lemma|thm|theorem|cor|prop|def|example|claim|remark|fact|construction)_\d", re.I)


def cited_names(cells, declared):
    """Names matching the project's convention that are cited but not declared."""
    bad = []
    for c in cells:
        for t in re.findall(r"`([^`]+)`", c):
            t = t.strip()
            if IDENT.match(t) and OURS.match(t) and t not in declared:
                bad.append(t)
    return bad



# --- the index check (formerly check_index.py; AUDIT_PROTOCOL.md, "The index check") -----------
# The index table is the nearest thing to a coverage check without a .aux. This half of it is
# mechanical: every project name it cites exists, no row has silently lost all its declarations,
# every PAPER_DEFECTS witness still exists, and numbering gaps are reported as a warning (the paper
# may simply have no 4.4). It cannot say the index is COMPLETE: a green run means the index is
# internally honest, not that the paper is covered (that stays with the faithfulness lane). Phase 0
# runs it as its own gate (`--check --index-only`), which a statement round does not waive.
INDEX_ROW = re.compile(rf"^\|\s*((?:{project.RESULT_KINDS_RE})\s[^|]*?)\s*\|\s*(.*?)\s*\|\s*$")
NUM = re.compile(r"(\d+)\.(\d+)")


def index_check(cfg, declared):
    """{"rows", "dangling", "empty", "witness", "gaps", "unknown"} for the project's index, or None
    when the index file is missing or no row parses (the check refuses to pass by finding nothing).
    dangling: a project name (OURS) cited and not declared -- with config `index_strict`, ANY
    backticked span that is not a declaration (backticks are for Lean names only, math goes in $…$);
    empty: a row citing no existing declaration and not saying it is not formalized; witness: a
    PAPER_DEFECTS.md witness that is not declared."""
    path = os.path.join(REPO, project.index_file(cfg) or "")
    if not os.path.isfile(path):
        return None
    rows = [(m.group(1).strip(), m.group(2).strip())
            for m in map(INDEX_ROW.match, open(path, encoding="utf-8").read().splitlines()) if m]
    if not rows:
        return None
    out = dict(rows=rows, dangling=[], empty=[], witness=[], gaps=[], unknown=[])
    strict = bool(cfg.get("index_strict"))
    for paper, lean in rows:
        spans = re.findall(r"`([^`]+)`", lean)
        cited = [t for t in spans if IDENT.match(t)]
        if strict:
            out["dangling"] += [(paper, t) for t in spans if t not in declared]
        else:
            out["dangling"] += [(paper, t) for t in cited if t not in declared and OURS.match(t)]
            out["unknown"] += [(paper, t) for t in cited if t not in declared and not OURS.match(t)]
        if not any(t in declared for t in cited) and not NOT_FORMALIZED.search(lean):
            out["empty"].append((paper, lean[:70]))
    seen = {}
    for paper, _ in rows:
        m = NUM.search(paper)
        if m:
            seen.setdefault(int(m.group(1)), set()).add(int(m.group(2)))
    out["gaps"] = [f"{sec}.{k}" for sec in sorted(seen) for k in range(1, max(seen[sec]) + 1)
                   if k not in seen[sec]]
    out["witness"] = dead_witnesses(os.path.join(REPO, cfg.get("rounds_dir", "audits"), "PAPER_DEFECTS.md"),
                                    declared)
    return out


WITNESS_COL = 6   # the "Lean witness" cell of a PAPER_DEFECTS.md row (# | where | status | repair | says | why | witness)

# B3 (U2 §1 "Defect rows"): a defect row's `status` (what is wrong as printed) and `repair` (what it takes to
# repair), each one of these values exactly (case and `*` ignored). No S-number alias: an old `severity` table,
# an unknown value, or "S1".."S4" is PENDING[adj-record] -- the adjudicator rewrites the row.
DEFECT_KEY = "status"
DEFECT_STATUSES = ("false", "vacuous", "unsupported", "misprint (true as intended)")
DEFECT_REPAIRS = ("none (intent unknown)", "typo", "add hypothesis", "local", "substantial", "not repaired")
DEFECT_HEADER = ["#", "where", "status", "repair", "what the paper says", "why it is wrong", "lean witness",
                 "consequence", "decision", "found"]


def defect_value(cell):
    """A status/repair cell normalised for comparison (bold, backticks, case and spacing ignored)."""
    return " ".join(str(cell or "").replace("*", "").replace("`", "").split()).lower()


def defect_col(head, name):
    return next((i for i, h in enumerate(head or []) if h == name), None)


def defect_order(head, rows):
    """The defect rows, `false` first, then vacuous, unsupported, misprint (stable within each; a row whose
    status is not a known value last -- it is PENDING[adj-record] anyway)."""
    i = defect_col(head, "status")
    if i is None:
        return list(rows)
    rank = lambda r: (DEFECT_STATUSES.index(defect_value(r[i])) if i < len(r)
                      and defect_value(r[i]) in DEFECT_STATUSES else len(DEFECT_STATUSES))
    return sorted(rows, key=rank)


# F10 in code (B3 attack fixes): a `false` row states its counterexample ("counterexample: ..." in the paper's
# notation) and cites the fresh paper-faithfulness lane that confirmed it, `F10: <round>/<lane file>.json`,
# whose F10 item (an item naming F10 or the counterexample) is Pass. A lane refutation `not_<X>_as_printed`
# is a `false` row naming it, or an encoding-error line `- encoding error: ... not_<X>_as_printed ... F10:
# <round>/<lane>.json` whose F10 item is Fail (not a counterexample to the paper). A row once committed as
# `false` and now not cites an F10 lane record other than the one it cited when false.
F10_CITE = re.compile(r"\bF10:\s*`?([\w.@-]+/(?:revote/)?[\w.@-]+\.json)`?")
COUNTEREXAMPLE = re.compile(r"\bcounter-?example\b[^:|]{0,40}:", re.I)
# <X> neither starts nor ends with `_`/`.` nor ends `_as_printed` (a benchmark run: a lane's probe files
# `<decl>__as_printed.lean` read as refutations `not_cor_7_2_as_printed__as_printed`, `not_lemma_7_1__as_printed`
# of declarations that do not exist, and every full round scheduled their F10 items): the suffix is never re-applied
AS_PRINTED = re.compile(r"\bnot_(?![_.])([\w.']+)(?<![_.])(?<!_as_printed)_as_printed\b")
ENCODING_LINE = re.compile(r"^\s*[-*]\s*\**encoding error\b", re.I)


# F10 scheduling (trial #7 deadlock): scope.py puts an item named F10_ITEM into the paper-faithfulness lane's
# TARGET.json for every refutation `not_<X>_as_printed` of the round (a Lean declaration at its commit; never a name
# only lane text or a probe file carries, bench2), and records which refutation each item is about in `_meta.f10`
# ({item: name}). A refutation is due (needs its `false` row or encoding-error line) once a paper-faithfulness lane
# has DECIDED its F10 item (Pass or Fail; a name no declaration carries is never scheduled, so never due); until then
# every round schedules the item again, and the adjudicator
# may put it to a re-vote (it is an item of the round's scope).
F10_ITEM = "F10: the counterexample of {}"


def refutation_label(rows, name):
    """The index label ("Lemma 7.4") of the refutation `name` (`not_<X>_as_printed`): the first index row
    of `rows` ([(label, rest)]) naming the refutation, else the first citing a declaration whose last component
    is <X>; None when no row does."""
    s = name.split(".")[-1]
    m = AS_PRINTED.fullmatch(s)
    x = m.group(1).split(".")[-1] if m else None
    for lab, rest in rows:
        if re.search(rf"(?<![\w']){re.escape(s)}(?![\w'])", rest):
            return " ".join(lab.split())
    for lab, rest in rows:
        if x and any(t.split(".")[-1] == x for t in re.findall(r"`([^`\s]+)`", rest)):
            return " ".join(lab.split())
    return None


def refutation_items(rows, names):
    """[(F10 item, F12 item or None, refutation name)] for the refutations `names` (short names), labels read
    off the index rows `rows`: "F10: the counterexample of Lemma 7.4" (of `not_X_as_printed` when no index row
    names it) and the repair's "F12: the repair of Lemma 7.4" (only with a label)."""
    out = []
    for n in sorted(set(names)):
        lab = refutation_label(rows, n)
        out.append((F10_ITEM.format(lab or f"`{n}`"), F12_ITEM.format(lab) if lab else None, n))
    return out


def f10_decided(rounds_dir, name):
    """The lane record (<round>/<file>.json) of a paper-faithfulness lane that DECIDED (Pass or Fail) an F10 item
    some round's TARGET.json (`_meta.f10`) scheduled for the refutation `name`, or None. A set-aside round or
    lane decides nothing."""
    import lanecheck
    short = name.split(".")[-1]
    for t in sorted(glob.glob(os.path.join(rounds_dir, "*", "TARGET.json"))):
        rd = os.path.dirname(t)
        if project.is_abandoned(rd):
            continue
        try:
            f10 = (json.load(open(t, encoding="utf-8")).get("_meta") or {}).get("f10") or {}
        except (OSError, ValueError, AttributeError):
            continue
        items = {lanecheck.clean_cell(i) for i, n in f10.items() if str(n).split(".")[-1] == short} \
            if isinstance(f10, dict) else set()
        if not items:
            continue
        for p in sorted(glob.glob(os.path.join(rd, "paper-faithfulness*.json"))
                        + glob.glob(os.path.join(rd, "revote", "paper-faithfulness--*.json"))):
            if lanecheck.is_abandoned_lane(rd, os.path.relpath(p, rd)):
                continue
            try:
                got = lanecheck.judged_items(json.load(open(p, encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if any(got.get(i) in ("Pass", "Fail") for i in items):
                return os.path.relpath(p, rounds_dir)
    return None


def f10_verdict(rounds_dir, cite, label=None):
    """(verdict of the F10 item, None) of the lane record `cite` (<round>/<file>.json under `rounds_dir`), or
    (None, why not): it must be a paper-faithfulness lane's verdict with an item naming F10 or the
    counterexample. With `label` (the row's result), an F10 item naming that result wins over the others (a
    record judging two counterexamples confirms each only for its own result)."""
    p = os.path.normpath(os.path.join(rounds_dir, cite))
    if not p.startswith(os.path.normpath(rounds_dir) + os.sep) or ".abandoned" in p.split(os.sep) \
            or not os.path.isfile(p):
        return None, f"F10 cites {cite}, which is no lane record of this run"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None, f"F10 cites {cite}, which is not readable JSON"
    if not isinstance(d, dict) or not str(d.get("lane", "")).startswith("paper-faithfulness"):
        return None, f"F10 cites {cite}, which is not a paper-faithfulness lane's verdict"
    import lanecheck
    its = [x for x in lanecheck.lane_entries(d) or []
           if re.search(r"\bF10\b|counter-?example", str(x.get("item", "")), re.I)]
    if not its:
        return None, f"F10 cites {cite}, whose verdict has no item on the counterexample (F10)"
    lab = " ".join(str(label).split()) if label else None
    mine = [x for x in its if lab and re.search(rf"(?<![\w.]){re.escape(lab)}(?!\.?\d)",
                                                 " ".join(str(x.get("item", "")).replace("`", "").split()))]
    return str((mine or its)[-1].get("verdict", "")), None


# F12 in code (B4, U2 §3 "Minimal correction"): a `false` row whose repair claims to be minimal (typo, add hypothesis,
# local) cites the paper-faithfulness lane that confirmed the paper's proof proves the corrected statement,
# `F12: <round>/<lane file>.json`, whose F12 item is Pass and cites the step of the paper's proof where the added
# hypothesis is used ("step ..." or "tex l.N"); otherwise the repair is `substantial`. And a refutation a re-approval
# was begun with (`signoff.py reapprove --refuted-by`, REAPPROVAL.json `refuted`) is accounted for exactly like a
# lane's: a `false` row naming it, or an encoding-error line.
F12_CITE = re.compile(r"\bF12:\s*`?([\w.@-]+/(?:revote/)?[\w.@-]+\.json)`?")
F12_REPAIRS = ("typo", "add hypothesis", "local")
F12_STEP = re.compile(r"\bstep\b|\btex\s+l\.\s*\d+", re.I)
# B4 review fix 2: ONE rule. Every `false` row with a minimal repair, whenever the corrected statement was made
# (before the approval, or by a re-approval), has its F12 item; prompt.py lists those rows for the
# paper-faithfulness lane of every round (f12_rows), each with the item name it must use (F12_ITEM).
F12_ITEM = "F12: the repair of {}"


def defect_result(head, row):
    """The result a defect row is about: its `where` cell's label before the first comma, semicolon or " ("
    ("Lemma 7.4, tex l.182-183", "Lemma 7.4 (tex l.210-211)", "Lemma 7.4 (the key identity), tex l.186" -> "Lemma
    7.4"; "Theorem 7.5(i)" stays), when that is a numbered result (project.RESULT_KINDS); else None."""
    j = defect_col(head, "where")
    if j is None or j >= len(row):
        return None
    lab = " ".join(re.split(r"[,;]|\s\(", str(row[j]).replace("*", "").replace("`", ""), maxsplit=1)[0].split())
    return lab if re.match(rf"(?:{project.RESULT_KINDS_RE})\s", lab) else None


def f12_rows(path):
    """[(row number, result label or None)] of PAPER_DEFECTS.md's `false` rows whose repair is minimal
    (F12_REPAIRS): the repairs the paper-faithfulness lane confirms."""
    head, rows, _, old = defects_table(path)
    i, j = defect_col(head, "status"), defect_col(head, "repair")
    if old or i is None or j is None:
        return []
    return [(r[0].strip("* "), defect_result(head, r)) for r in rows
            if max(i, j) < len(r) and defect_value(r[i]) == "false" and defect_value(r[j]) in F12_REPAIRS]


def f12_verdict(rounds_dir, cite, label=None):
    """(verdict, None) of the F12 item of the lane record `cite`, or (None, why not): a paper-faithfulness lane's
    verdict with an item named exactly F12_ITEM of the row's result `label` (B4 review fix 3: an F12 item on
    another result confirms nothing about this one) whose text cites the step of the paper's proof (F12_STEP)."""
    p = os.path.normpath(os.path.join(rounds_dir, cite))
    if not p.startswith(os.path.normpath(rounds_dir) + os.sep) or ".abandoned" in p.split(os.sep) \
            or not os.path.isfile(p):
        return None, f"F12 cites {cite}, which is no lane record of this run"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None, f"F12 cites {cite}, which is not readable JSON"
    if not isinstance(d, dict) or not str(d.get("lane", "")).startswith("paper-faithfulness"):
        return None, f"F12 cites {cite}, which is not a paper-faithfulness lane's verdict"
    import lanecheck
    want = " ".join(F12_ITEM.format(label).split()) if label else None
    its = [x for x in lanecheck.lane_entries(d) or [] if re.search(r"\bF12\b", str(x.get("item", "")))
           and (want is None or " ".join(str(x.get("item", "")).replace("*", "").replace("`", "").split()) == want)]
    if not its:
        return None, (f"F12 cites {cite}, whose verdict has no item \"{want}\" (the repair of this row's result)"
                      if want else f"F12 cites {cite}, whose verdict has no F12 item (the repair)")
    it = its[-1]
    if not F12_STEP.search(" ".join(str(it.get(k, "")) for k in ("item", "comment", "checked", "evidence"))):
        return None, f"F12 cites {cite}, whose F12 item names no step of the paper's proof (\"step ...\" or \"tex l.N\")"
    return str(it.get("verdict", "")), None


def reapproval_refutations(rounds_dir):
    """{`not_<X>_as_printed` name: "REAPPROVAL.json"} for every refutation a re-approval of the run was begun with
    (any committed version of the record, and the working copy: an obligation only ever added)."""
    p = os.path.join(rounds_dir, "REAPPROVAL.json")
    texts = [open(p, encoding="utf-8").read()] if os.path.isfile(p) else []
    r = subprocess.run(["git", "-C", rounds_dir, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if not r.returncode and os.path.isdir(rounds_dir):
        top = os.path.realpath(r.stdout.strip())
        rel = os.path.relpath(os.path.realpath(p), top)
        for h in subprocess.run(["git", "-C", top, "log", "--full-history", "--format=%H", "--", rel],
                                capture_output=True, text=True).stdout.split():
            t = project.committed_blob(top, h, rel)
            if t is not None:
                texts.append(t)
    out = {}
    for t in texts:
        try:
            d = json.loads(t)
        except ValueError:
            continue
        for rec in ((d.get("refuted") or {}).values() if isinstance(d, dict) and isinstance(d.get("refuted"), dict)
                    else []):
            m = AS_PRINTED.search(str((rec or {}).get("by", ""))) if isinstance(rec, dict) else None
            if m:
                out.setdefault(m.group(0), "REAPPROVAL.json (`signoff.py reapprove --refuted-by`)")
    return out


def lane_refutations(rounds_dir):
    """{`not_<X>_as_printed` name: lane record} named by any lane verdict of the run (not set aside)."""
    import lanecheck
    out = {}
    for p in sorted(glob.glob(os.path.join(rounds_dir, "*", "*.json"))
                    + glob.glob(os.path.join(rounds_dir, "*", "revote", "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and "lane" in d and lanecheck.lane_entries(d) is not None:
            for m in AS_PRINTED.finditer(json.dumps(d, ensure_ascii=False)):
                out.setdefault(m.group(0), os.path.relpath(p, rounds_dir))
    return out


# a proved refutation of a printed statement: `theorem T : ¬ <X>_statement` / `¬ <X>_as_printed`, or one named
# `not_<X>_as_printed` (AS_PRINTED)
LEAN_REFUTATION = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+)?(?:theorem|lemma)\s+([\w.']+)"
                             r"[^:]*?:\s*¬\s*(?:\(?\s*([\w.']+))?", re.M)


# a project proposition (`def X ... : Prop`), the printed statement a refutation negates; a refutation's own name
PROP_DEF = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:noncomputable\s+)?def\s+([\w.']+)[^:=]*:\s*Prop\s*:=", re.M)
REFUTATION_NAME = re.compile(r"(?:as_printed|_false$|counterexample)")


def _lean_refutation_hits(cfg, repo=None):
    """[(short name, short target or "", "File.lean")] of every theorem lean_refutations recognises."""
    out, texts = [], {}
    for f in cfg.get("lean_files") or []:
        p_ = os.path.join(repo or REPO, f)
        try:
            t = open(p_, encoding="utf-8").read()
        except OSError:
            continue
        t = re.sub(r"/-.*?-/", lambda m: "\n" * m.group(0).count("\n"), t, flags=re.S)
        t = re.sub(r"--[^\n]*", "", t)
        texts[f] = t
    props = {m.group(1).split(".")[-1] for t in texts.values() for m in PROP_DEF.finditer(t)}
    for f, t in texts.items():
        for m in LEAN_REFUTATION.finditer(t):
            name, target = m.group(1).split(".")[-1], (m.group(2) or "").split(".")[-1]
            if (target and (target.endswith(("_statement", "_as_printed")) or target in props)) or AS_PRINTED.fullmatch(name) \
                    or REFUTATION_NAME.search(name):
                out.append((name, target, f))
    return out


def lean_refutations(cfg):
    """{name: "File.lean"} of every theorem of the project's Lean files that refutes a printed statement (forgery
    review H3(a)): its type is `¬ X` for a project proposition `def X : Prop` or an `X` named `<..>_statement` /
    `<..>_as_printed`, or `¬ ...` under a name saying so (`not_<X>_as_printed`, `..._as_printed...`, `..._false`,
    `...counterexample...`). Each
    needs a `false` row of PAPER_DEFECTS.md naming it, or an encoding-error line (f10_problems)."""
    out = {}
    for name, _t, f in _lean_refutation_hits(cfg):
        out.setdefault(name, f)
    return out


# ONE name for a refutation of a printed statement (trial #10): every consumer -- the F10/F12 checks here, scope.py's
# F10 scheduling and prompt.py's REFUTATIONS TO JUDGE, `signoff.py reapprove --refuted-by` -- reads a refutation by
# its name `not_<X>_as_printed` (AS_PRINTED), <X> the refuted declaration. A theorem lean_refutations recognises
# under any other name (trial #10: `lemma_7_4_b_as_printed_false`) is refused EARLY, by Phase 0's index check and by
# scope.py, with the exact rename: no round is spent on a refutation no lane can be scheduled to judge.
def refutation_rename(name, target=""):
    """The canonical name `not_<X>_as_printed` of the refutation `name` (short) whose type is `¬ target`: <X> from a
    target `<X>_as_printed` / `<X>_statement`, else `name` without its as_printed / false / counterexample / not
    words, else the target itself."""
    s, t = str(name).split(".")[-1], str(target or "").split(".")[-1]
    if AS_PRINTED.fullmatch(s):
        return s
    x = next((t[:-len(k)] for k in ("_as_printed", "_statement") if t.endswith(k) and len(t) > len(k)), "")
    x = x or re.sub(r"(?:^|_)(?:as_printed|is_false|false|counterexample|not)(?=_|$)", "", s).strip("_") or t or s
    return f"not_{x}_as_printed"


def refutation_name_problems(cfg, repo=None):
    """[project.Finding] (index: the operator's own Lean) for every refutation lean_refutations recognises whose
    name is not `not_<X>_as_printed`, each with its exact rename."""
    out, seen = [], set()
    for name, target, f in _lean_refutation_hits(cfg, repo):
        if AS_PRINTED.fullmatch(name) or name in seen:
            continue
        seen.add(name)
        new = refutation_rename(name, target)
        out.append(project.Finding(
            f"{f}: `{name}` refutes a printed statement but is not named `not_<decl>_as_printed`, the one name the "
            f"F10 scheduling, the defect record and `reapprove --refuted-by` read: rename it `{new}` (<decl> the "
            f"refuted declaration; its mentions in the index and docstrings too), commit, and run Phase 0 again "
            f"before scoping a round", "index"))
    return out


def _false_history(path):
    """{row number: set of F10 cites} for every row some committed version of `path` had as `false`."""
    rd = os.path.dirname(os.path.abspath(path))
    r = subprocess.run(["git", "-C", rd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode:
        return {}
    top = os.path.realpath(r.stdout.strip())
    rel = os.path.relpath(os.path.realpath(path), top)
    hs = subprocess.run(["git", "-C", top, "log", "--full-history", "--format=%H", "--", rel],
                        capture_output=True, text=True).stdout.split()
    out = {}
    import tempfile
    for h in hs:
        txt = project.committed_blob(top, h, rel)
        if txt is None:
            continue
        with tempfile.TemporaryDirectory() as td:
            q = os.path.join(td, "PAPER_DEFECTS.md")
            open(q, "w", encoding="utf-8").write(txt)
            head, rows, _, old = defects_table(q)
        i = defect_col(head, "status")
        for row in rows if not old and i is not None else []:
            if i < len(row) and defect_value(row[i]) == "false":
                out.setdefault(row[0].strip("* "), set()).update(F10_CITE.findall(" ".join(row)))
    return out


# Forgery review H1: the row-history rule of PAPER_DEFECTS.md (a `false` row is never removed) extended to the
# records whose rows set a result's status: a VACUOUS.md row (vacuous), a SKIPPED.md row (not formalized), a
# DEVIATIONS.md row (reading choice, differs). A row deleted in a commit named "adjudicate R" turned "vacuous" into
# "faithful" with every gate green. Now no row of them is ever removed: an adjudication that overturns one marks it
# `superseded (<round>)` in its last cell (project.superseded_row), the readers skip it, and the summary lists it.
HISTORY_RECORDS = (("skipped", "SKIPPED.md", "what"), ("vacuous", "VACUOUS.md", "statement"),
                   ("deviations", "DEVIATIONS.md", "kind"))


def raw_record_rows(text, keycol):
    """[cells] of every row of the first table in `text` whose header has a column starting `keycol`, superseded
    rows included (record_table skips those)."""
    header, rows, cur = None, [], None
    for line in str(text or "").splitlines():
        st = line.strip()
        if not st.startswith("|"):
            if header is not None:
                break
            cur = None
            continue
        cells = project.split_row(st)
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if cur is None:
            cur = cells
            if any(c.strip("* ").lower().startswith(keycol) for c in cells):
                header = cells
            continue
        if header is not None:
            rows.append(cells)
    return rows


def _row_key(cells):
    return cells[0].strip("*` ") if cells else ""


def _record_versions(path):
    """[(commit, subject, text)] of every committed version of `path`, oldest first (its literal path)."""
    rd = os.path.dirname(os.path.abspath(path))
    top, rel = project.rounds_rel(rd, os.path.basename(path))
    if top is None:
        return []
    out = []
    for ln in subprocess.run(["git", "-C", top, "log", "--reverse", "--full-history", "--format=%H %s", "--", rel],
                             capture_output=True, text=True).stdout.splitlines():
        h, _, subj = ln.partition(" ")
        txt = project.committed_blob(top, h, rel)
        if txt is not None:
            out.append((h, subj, txt))
    return out


def row_history_problems(rounds_dir, f, keycol):
    """["! ..."] (forgery review H1) of record `f` (HISTORY_RECORDS): a row number some committed version had and
    the file lacks now (a row is never removed); a row marked `superseded (<round>)` naming no adjudicated round of
    the run, or first committed so by anything but "adjudicate <that round>"."""
    path = os.path.join(rounds_dir, f)
    now = raw_record_rows(open(path, encoding="utf-8").read(), keycol) if os.path.exists(path) else []
    keys_now = {_row_key(r) for r in now}
    seen, sup_by = {}, {}
    for h, subj, txt in _record_versions(path):
        for r in raw_record_rows(txt, keycol):
            k = _row_key(r)
            seen.setdefault(k, h)
            rnd = project.superseded_row(r)
            if rnd and (k, rnd) not in sup_by:
                sup_by[(k, rnd)] = (h, subj)
    out = []
    gone = sorted((k for k in seen if k and k not in keys_now), key=lambda k: (len(k), k))
    if gone:
        out.append(f"! {f}: row(s) {', '.join(gone)} were committed (first in {seen[gone[0]][:11]}) and are gone: a row "
                   f"is never removed; an adjudication that overturns a row keeps it and writes `superseded "
                   f"(<round>)` in its last cell (restore the rows; AUDIT_PROTOCOL.md, step 4 G)")
    for r in now:
        rnd = project.superseded_row(r)
        if not rnd:
            continue
        if not os.path.isfile(os.path.join(rounds_dir, rnd, "ADOPTED.md")):
            out.append(f"! {f} row {_row_key(r)[:20]}: `superseded ({rnd})` names no adjudicated round of this run "
                       f"(no {rnd}/ADOPTED.md)")
            continue
        h_s = sup_by.get((_row_key(r), rnd))
        if h_s and not h_s[1].startswith(f"adjudicate {rnd}"):
            out.append(f"! {f} row {_row_key(r)[:20]}: marked `superseded ({rnd})` by \"{h_s[1][:50]}\" "
                       f"({h_s[0][:11]}); only the adjudication of that round (\"adjudicate {rnd}\") supersedes a row")
    return out


def superseded_rows(rounds_dir):
    """[(file, row number, round, row text)] of every superseded row of HISTORY_RECORDS (the summary lists each)."""
    out = []
    for _k, f, keycol in HISTORY_RECORDS:
        p_ = os.path.join(rounds_dir, f)
        if os.path.exists(p_):
            for r in raw_record_rows(open(p_, encoding="utf-8").read(), keycol):
                rnd = project.superseded_row(r)
                if rnd:
                    out.append((f, _row_key(r), rnd, " | ".join(r[1:-1])))
    return out


# Forgery review H1: a citation "<record> row N" must name a row that exists (superseded rows included): a deleted
# row leaves its citations dangling in the run log and the other records.
ROW_REF = re.compile(r"\b(VACUOUS|PAPER_DEFECTS|DEVIATIONS|SKIPPED)(?:\.md)?\s+rows?\s+(\d+(?:\s*(?:,|and|&)\s*\d+)*)")


def record_row_numbers(rounds_dir):
    """{record file: {row number}} of the four records as they stand (superseded rows included)."""
    out = {}
    for _k, f, keycol in HISTORY_RECORDS:
        p_ = os.path.join(rounds_dir, f)
        out[f] = {_row_key(r) for r in raw_record_rows(open(p_, encoding="utf-8").read(), keycol)} \
            if os.path.exists(p_) else set()
    pd = os.path.join(rounds_dir, "PAPER_DEFECTS.md")
    out["PAPER_DEFECTS.md"] = {_row_key(r) for r in defects_table(pd)[1]} if os.path.exists(pd) else set()
    return out


def row_reference_problems(rounds_dir):
    """[Finding] of every "<record> row N" citation naming a row the record does not have: in RUN_LOG.md (report:
    the operator corrects the line) and in the four records (record-cite: a record correction)."""
    have, out = record_row_numbers(rounds_dir), []
    for src, code in (("RUN_LOG.md", "report"), ("SKIPPED.md", "record-cite"), ("VACUOUS.md", "record-cite"),
                      ("DEVIATIONS.md", "record-cite"), ("PAPER_DEFECTS.md", "record-cite")):
        p_ = os.path.join(rounds_dir, src)
        if not os.path.exists(p_):
            continue
        bad = []
        for m in ROW_REF.finditer(open(p_, encoding="utf-8").read()):
            f = m.group(1) + ".md"
            for n in re.findall(r"\d+", m.group(2)):
                if n not in have.get(f, set()) and (f, n) not in bad:
                    bad.append((f, n))
        for f, n in bad:
            out.append(project.Finding(f"! {src} cites {f} row {n}, which {f} does not have (a row is never "
                                       f"removed or renumbered; correct the citation or restore the row)", code))
    return out


def _short(name):
    return str(name).strip("` ").split(".")[-1]


def row_decls(head, row, cfg=None, refuted=None):
    """{short declaration name} a defect row is about: the `<X>` of each refutation `not_<X>_as_printed` it names,
    each declaration a re-approval's `refuted` record ({decl: {by}}) lists under a refutation it names, and (with
    `cfg`) the declarations the index row of its result (defect_result, exact label) cites."""
    text = " ".join(row)
    names = {m.group(0) for m in AS_PRINTED.finditer(text)}
    out = {m.group(1).split(".")[-1] for m in AS_PRINTED.finditer(text)}
    for decl, rec in (refuted or {}).items():
        if isinstance(rec, dict) and any(re.search(rf"\b{re.escape(n)}\b", str(rec.get("by", ""))) for n in names):
            out.add(_short(decl))
    lab = defect_result(head, row)
    if cfg is not None and lab:
        p = os.path.join(project.REPO, project.index_file(cfg) or "")
        for m in map(INDEX_ROW.match, open(p, encoding="utf-8").read().splitlines() if os.path.isfile(p) else []):
            if m and " ".join(m.group(1).split()) == lab:
                out |= {_short(t) for t in re.findall(r"`([^`]+)`", m.group(2)) if IDENT.match(t)}
    return out


def reapproval_begins(rounds_dir, cfg=None):
    """(every begin of every re-approval of the run, oldest first; the union of their `refuted` records)."""
    import fingerprint
    begins, refuted = [], {}
    try:
        cycles = fingerprint.reapprovals(rounds_dir, cfg)
    except Exception:   # noqa: BLE001  (an unreadable record: no begin read, the record checks say why)
        cycles = []
    for c in cycles:
        begins += [b for b in (c.get("begins") or []) if isinstance(b, dict)]
        if isinstance(c.get("refuted"), dict):
            refuted.update(c["refuted"])
    return begins, refuted


def f12_after_begin(cite, begin):
    """None when the lane record `cite` (<round>/<file>.json) was cut from a Lean commit strictly after the
    re-approval `begin` (its `lean_head` a proper ancestor of the round's commit), else why not (B4 review fix 3:
    the repair the lane confirmed is the latest correction, never one a later failed correction replaced)."""
    rc_ = project.round_commit(cite.split("/")[0])
    c, _ = project._resolve(project.REPO, rc_)
    lh, _ = project._resolve(project.REPO, str(begin.get("lean_head") or ""))
    if c and lh and c != lh and project._is_ancestor(project.REPO, lh, c):
        return None
    return (f"F12 cites {cite}, a lane run at Lean {rc_}, not after the latest re-approval of this result (begun "
            f"at Lean {str(begin.get('lean_head') or '?')[:11]}, {begin.get('date', '?')}): a lane run after it "
            f"confirms the repair")


def f10_problems(path, head, rows, cfg=None):
    """["! ..."] (adj-record): the F10 rule in code (AUDIT_PROTOCOL.md, F10)."""
    i = defect_col(head, "status")
    if i is None:
        return []
    rd, out = os.path.dirname(os.path.abspath(path)), []
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    false_text = ""
    for r in rows:
        if i >= len(r) or defect_value(r[i]) != "false":
            continue
        false_text += " ".join(r)
        cites = F10_CITE.findall(" ".join(r))
        if not COUNTEREXAMPLE.search(" ".join(r)):
            out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: a `false` row states its counterexample in the paper's "
                       f"notation (\"counterexample: ...\") (F10)")
        vs = [f10_verdict(rd, c, defect_result(head, r)) for c in cites]
        if not any(v == "Pass" for v, _ in vs):
            out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: a `false` row cites the fresh paper-faithfulness lane that "
                       f"confirmed its counterexample, `F10: <round>/<lane>.json` with that item Pass ("
                       + ("; ".join(w or f"{c}: the F10 item is {v}" for c, (v, w) in zip(cites, vs)) or "none cited")
                       + "); otherwise it is a Lean encoding error, no row (F10)")
    j = defect_col(head, "repair")
    begins_, refuted_ = reapproval_begins(rd, cfg)
    for r in rows:
        if i >= len(r) or defect_value(r[i]) != "false" or j is None or j >= len(r) \
                or defect_value(r[j]) not in F12_REPAIRS:
            continue
        lab = defect_result(head, r)
        if not lab:
            out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: a minimal repair names its result: the `where` cell begins "
                       f"with the result's label (\"Lemma 7.4, tex l.182\"), which the F12 item names exactly (F12)")
            continue
        cites = F12_CITE.findall(" ".join(r))
        vs = [f12_verdict(rd, c, lab) for c in cites]
        mine = row_decls(head, r, cfg, refuted_)
        rby = lambda b: AS_PRINTED.search(str(b.get("refuted_by", "")))
        last = [b for b in begins_ if {_short(x) for x in b.get("decls") or []} & mine
                or (rby(b) and re.search(rf"\b{re.escape(rby(b).group(0))}\b", " ".join(r)))]
        if last:
            vs = [(v, w or (f12_after_begin(c, last[-1]) if v == "Pass" else None)) for c, (v, w) in zip(cites, vs)]
            vs = [(None if w else v, w) for v, w in vs]
        if not any(v == "Pass" for v, _ in vs):
            out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: a repair counts as `{defect_value(r[j])}` (minimal) only "
                       f"when a paper-faithfulness lane confirms the paper's proof proves the corrected statement and "
                       f"cites the step where the added hypothesis is used, `F12: <round>/<lane>.json` with that item "
                       f"Pass (" + ("; ".join(w or f"{c}: the F12 item is {v}" for c, (v, w) in zip(cites, vs))
                                     or "none cited") + "); otherwise the repair is `substantial` (F12)")
    # B4 review fix 4: a refuted and re-approved result (`--refuted-by`, REAPPROVAL `refuted`) was repaired: its
    # row's repair says how (typo | add hypothesis | local | substantial), never `not repaired`
    refuted_short = {_short(x) for x in refuted_}
    for r in rows:
        if j is not None and j < len(r) and defect_value(r[j]) == "not repaired" \
                and row_decls(head, r, cfg, refuted_) & refuted_short:
            out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: its result was refuted and re-approved (`signoff.py "
                       f"reapprove --refuted-by`): the repair is typo, add hypothesis, local or substantial, never "
                       f"`not repaired` (F12)")
    enc = [ln for ln in text.splitlines() if ENCODING_LINE.match(ln)]
    refs = dict(reapproval_refutations(rd), **lane_refutations(rd))
    lean_refs = lean_refutations(cfg) if cfg else {}
    for name, src in lean_refs.items():
        refs.setdefault(name, src)
    for name, src in sorted(refs.items()):
        if re.search(rf"\b{re.escape(name)}\b", false_text):
            continue
        # forgery review H3(a): a refutation proved in the Lean (lean_refutations) is due at once unless it is a
        # `not_<X>_as_printed` (scope.py schedules its F10 item): the Lean is fingerprinted and approved, so a
        # defect row deleted from the record (even by a history rewrite) leaves a proved refutation without its row
        if f10_decided(rd, name) is None and not (name in lean_refs and not AS_PRINTED.fullmatch(name)):
            # not yet due: no paper-faithfulness lane has decided its F10 item; scope.py schedules the item in
            # every round until one does (a round scoped before F10 scheduling never had it to judge)
            continue
        ok = False
        for ln in enc:
            if re.search(rf"\b{re.escape(name)}\b", ln) and any(f10_verdict(rd, c)[0] == "Fail"
                                                                 for c in F10_CITE.findall(ln)):
                ok = True
        if not ok:
            out.append(f"! PAPER_DEFECTS.md: the {'lane ' if src.endswith('.json') else ''}refutation `{name}` ({src}) has neither a `false` row naming it "
                       f"nor an encoding-error line (`- encoding error: ... {name} ... F10: <round>/<lane>.json`, that "
                       f"lane's F10 item Fail) (F10)"
                       + ("" if src.endswith(".json") or AS_PRINTED.fullmatch(name) else
                          f"; first the operator renames it `{refutation_rename(name)}` (refutation_name_problems): "
                          f"no lane is scheduled to judge a refutation under another name"))
    hist = _false_history(path)
    gone = sorted(set(hist) - {r[0].strip("* ") for r in rows if r})
    if gone:
        out.append(f"! PAPER_DEFECTS.md: row(s) {', '.join(gone)} were `false` and are gone: a row is never removed; "
                   f"a status change cites a fresh F10 verdict (F10)")
    for r in rows:
        n = r[0].strip("* ") if r else ""
        if n in hist and not (i < len(r) and defect_value(r[i]) == "false"):
            new = set(F10_CITE.findall(" ".join(r))) - hist[n]
            if not any(f10_verdict(rd, c)[1] is None for c in new):
                out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: was `false`; changing its status needs a fresh "
                           f"paper-faithfulness lane's F10 verdict, cited `F10: <round>/<lane>.json` (not the one "
                           f"cited while it was false) (F10)")
    return out


def defect_problems(path, head, rows, cfg=None):
    """["! ..."] (adj-record) of PAPER_DEFECTS.md's `## Defects` table: an old-format table (a `severity`
    column, no `status`), a missing `status` or `repair` column, a value not in DEFECT_STATUSES /
    DEFECT_REPAIRS (an S-number included: no alias)."""
    out = list(defects_table(path)[2])
    if not head:
        old, _ = record_table(path, "severity")
        if old:
            out.append("! PAPER_DEFECTS.md: the defects table has the old `severity` column: the adjudicator "
                       "rewrites it with a `status` (" + " | ".join(DEFECT_STATUSES) + ") and a `repair` ("
                       + " | ".join(DEFECT_REPAIRS) + ") column per row (AUDIT_PROTOCOL.md template; no "
                       "S-number alias)")
        return out
    for col in ("status", "repair"):
        if defect_col(head, col) is None:
            out.append(f"! PAPER_DEFECTS.md: the defects table has no `{col}` column (AUDIT_PROTOCOL.md template)")
    for r in rows:
        for col, vals in (("status", DEFECT_STATUSES), ("repair", DEFECT_REPAIRS)):
            i = defect_col(head, col)
            if i is not None and i < len(r) and defect_value(r[i]) not in vals:
                out.append(f"! PAPER_DEFECTS.md row {r[0][:20]}: {col} {r[i].strip()!r} is not one of "
                           + " | ".join(vals) + (" (an S-number is no status or repair: rewrite the row)"
                                                 if re.fullmatch(r"s[1-4]", defect_value(r[i])) else "")
                           + ("; a `false` row needs the F10 check first (AUDIT_PROTOCOL.md)" if col == "status" else ""))
    return out + f10_problems(path, head, rows, cfg)


def defects_intro(head, rows):
    """The defects section's first sentence: which rows carry a compiling Lean witness, and which are
    confirmed by argument only (re-check N3: a real defect without a witness stays in the record and is
    disclosed, never dropped)."""
    import decisions
    wf = [r[0] for r in rows if r and decisions.witness_free(head or [], r)]
    return ("Every row carries a compiling Lean witness"
            + (f", except defect{'s' if len(wf) > 1 else ''} {', '.join(wf)}: confirmed by argument only, no "
               f"Lean witness yet (the witness cell says where the argument is)" if wf else "") + ". ")


def dead_witnesses(defects, declared):
    """[(row number, name)] of every backticked name in a PAPER_DEFECTS.md witness cell that is not a
    declaration of the project. A defect row names a Lean witness; a witness that does not exist (a
    `sorry`, a lemma in a lane's scratch probe) is a claim about someone else's paper that nobody here
    can back up (and the kind that gets sent outside the project): `make_report.py --check` and the
    adjudication commit (integrity.py --commit-adjudication) both refuse it."""
    out, col = [], WITNESS_COL
    for line in (open(defects, encoding="utf-8") if os.path.exists(defects) else []):
        cells = project.split_row(line) if line.strip().startswith("|") else []
        if not cells:
            col = WITNESS_COL
            continue
        if cells[0].strip("* ") == "#":
            # the table's own witness column (B3: an old-format `severity` table, PENDING until the adjudicator
            # rewrites it, still has its dead witnesses found), else the template's position
            col = next((i for i, h in enumerate(cells) if h.strip("* ").lower().startswith(("lean witness", "witness"))),
                       WITNESS_COL)
            continue
        if len(cells) <= col or not cells[0].rstrip(".").isdigit():
            continue
        for t in re.findall(r"`([^`]+)`", cells[col]):
            t = t.split("(")[0].strip()
            if IDENT.match(t) and t not in declared:
                out.append((cells[0], t))
    return out


def index_only(cfg, pending=False):
    """`make_report.py --check --index-only`: the index check alone, as Phase 0's "index check" step.
    Exit 1 on a dangling name, an empty row or a dead defect witness; 2 if the index cannot be read;
    gaps and names declared elsewhere (Mathlib, notation) are warnings."""
    ix = index_check(cfg, declared_names(cfg["lean_files"]))
    if ix is None:
        print(f"FAIL[index] no index rows parsed from {project.index_file(cfg)} (missing, or the table moved or "
              f"changed shape): this check cannot pass by finding nothing", file=sys.stderr)
        return 2
    print(f"index: {project.index_file(cfg)}, {len(ix['rows'])} rows")
    for key, title in (("dangling", "DANGLING NAMES: the index cites a project declaration that does not exist"),
                       ("empty", "EMPTY ROWS: no existing declaration, and not marked unformalized"),
                       ("witness", "DEAD PAPER_DEFECTS WITNESSES: a defect's named declaration does not exist"),
                       ("unknown", "NOT DECLARED HERE (warning): expected for Mathlib names and notation")):
        print(f"{title} ({len(ix[key])})")
        for a_, b_ in ix[key]:
            print(f"  {a_}: {b_}")
    print(f"NUMBERING GAPS ({len(ix['gaps'])}, warning: the paper may simply have no such result): "
          + (", ".join(ix["gaps"]) or "none"))
    names = refutation_name_problems(cfg)
    print(f"REFUTATIONS NOT NAMED not_<decl>_as_printed ({len(names)})")
    for x in names:
        print(f"FAIL[index] {x}")
    bad = len(ix["dangling"]) + len(ix["empty"]) + len(names) + (0 if pending else len(ix["witness"]))
    # every failure line carries its cause code (stops.causes): the index is the operator's own work
    # (index); a dead witness is in the adjudicator's record (dead-witness: a record correction)
    if ix["dangling"] or ix["empty"]:
        print(f"FAIL[index] {len(ix['dangling'])} dangling name(s), {len(ix['empty'])} empty row(s) in "
              f"{project.index_file(cfg)}: fix the index (your own work)")
    for n_, t in ix["witness"]:
        w_ = (f"PAPER_DEFECTS.md row {n_}: its witness cell names `{t}`, not a declaration of this project: a "
              f"record correction (prompt.py 4 --round <R> --record-fix), or the next adjudication")
        print(pending_line(project.Finding(w_, "dead-witness")) if pending else f"FAIL[dead-witness] {w_}")
    print(f"index check: {'FAIL' if bad else 'ok'} -- {len(ix['dangling'])} dangling, {len(ix['empty'])} empty, "
          f"{len(names)} misnamed refutation(s), {len(ix['witness'])} dead defect witness(es), {len(ix['gaps'])} numbering gap(s) [warning]")
    print("NOTE: a green run means the index is internally honest, NOT that the paper is covered.")
    return 1 if bad else 0

def demote_headings(md):
    """A record's free text inside a report section: its own `#` headings become bold lines, so they
    neither break the report's numbering nor print as literal "##" (a test run)."""
    return re.sub(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", r"**\1**", md, flags=re.M)


DEFECTS_SECTION = re.compile(r"^##(?!#)\s*Defects\b", re.I)
_SECTION_END = re.compile(r"^#{1,2}(?!#)\s")
_SEP = lambda cells: all(set(c) <= set("-: ") for c in cells)


def defects_table(path):
    """(head, rows, problems, old) of PAPER_DEFECTS.md's defects table, parsed from its WHOLE `## Defects`
    section (B3 attack fixes): the table is the section's first table whose header has a `status` column
    (else, `old`, a `severity` one); rows are never dropped. A row-like line after a blank line, a text line
    or an HTML comment inside the table, or a table-like row anywhere else in the section, is kept as a row
    AND a problem; so are a second `## Defects` heading (its rows join the first's), a repeated column name
    and a repeated row number. Every problem is adj-record (defect_problems): the report, the box, REPORT.tex
    and DECISIONS.md all read these rows (decisions.defect_rows), and the adjudicator repairs the layout.
    No `## Defects` heading: the section is the file from the table's header to the next heading."""
    if not os.path.exists(path):
        return [], [], [], False
    lines = open(path, encoding="utf-8").read().splitlines()
    starts = [i for i, ln in enumerate(lines) if DEFECTS_SECTION.match(ln.strip())]
    problems = []
    if len(starts) > 1:
        problems.append(f"! PAPER_DEFECTS.md: {len(starts)} `## Defects` headings (lines "
                        f"{', '.join(str(i + 1) for i in starts)}): one section holds every defect row; merge them")
    region = []      # (line index, text) of the section(s)
    if starts:
        for s in starts:
            j = s + 1
            while j < len(lines) and not _SECTION_END.match(lines[j].strip()):
                region.append((j, lines[j])); j += 1
    else:
        hdr = next((i for i, ln in enumerate(lines) if ln.strip().startswith("|") and any(
            c.strip("* ").lower().startswith(("status", "severity")) for c in project.split_row(ln.strip()))), None)
        if hdr is None:
            return [], [], [], False
        j = hdr
        while j < len(lines) and not _SECTION_END.match(lines[j].strip()):
            region.append((j, lines[j])); j += 1
    # tables of the region: runs of consecutive `|` lines
    tables, cur = [], None
    for i, ln in region:
        if ln.strip().startswith("|"):
            if cur is None:
                cur = []; tables.append(cur)
            cur.append((i, project.split_row(ln.strip())))
        else:
            cur = None
    norm = lambda cells: [c.strip("* ").lower() for c in cells]
    pick = next((t for t in tables if any(h.startswith("status") for h in norm(t[0][1]))), None)
    old = pick is None
    if old:
        pick = next((t for t in tables if any(h.startswith("severity") for h in norm(t[0][1]))), None)
    if pick is None:
        return [], [], problems, False
    head = norm(pick[0][1])
    rows = [c for _, c in pick[1:] if not _SEP(c)]
    dup = sorted({h for h in head if h and head.count(h) > 1})
    if dup:
        problems.append(f"! PAPER_DEFECTS.md: the defects table names the column(s) {', '.join(dup)} twice: each "
                        f"column once (AUDIT_PROTOCOL.md template)")
    k = tables.index(pick)
    stray = []
    for t in tables[:k] + tables[k + 1:]:
        for i, c in t:
            if _SEP(c) or norm(c) == head:
                continue
            stray.append(i + 1)
            if tables.index(t) > k:
                rows.append(c)
    if stray:
        problems.append(f"! PAPER_DEFECTS.md: table rows outside the defects table in the `## Defects` section "
                        f"(line(s) {', '.join(map(str, stray))}: the table interrupted by a blank line, text or a "
                        f"comment, or a second table): one unbroken table; every row after the break is kept")
    nums = [r[0].strip("* ") for r in rows if r]
    dupn = sorted({n for n in nums if nums.count(n) > 1})
    if dupn:
        problems.append(f"! PAPER_DEFECTS.md: row number(s) {', '.join(dupn)} used twice: each defect row its own "
                        f"number (rows are never removed or renumbered)")
    return head, rows, problems, old


def record_table(path, keycol):
    """(header, rows) of the first table in `path` whose header has a column starting `keycol`. PAPER_DEFECTS.md's
    defects table (`status`, or `severity` for the old format) is read by defects_table: its whole section."""
    if not os.path.exists(path):
        return [], []
    if os.path.basename(path) == "PAPER_DEFECTS.md" and keycol in (DEFECT_KEY, "severity"):
        head, rows, _, old = defects_table(path)
        return (head, rows) if old == (keycol == "severity") else ([], [])
    header, rows, cur = None, [], None
    for line in open(path, encoding="utf-8"):
        st = line.strip()
        if not st.startswith("|"):
            if header is not None:
                break
            cur = None
            continue
        cells = project.split_row(st)
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if cur is None:
            cur = [c.strip("* ").lower() for c in cells]
            if any(h.startswith(keycol) for h in cur):
                header = cur
            continue
        if header is not None and not project.superseded_row(cells):
            # a row an adjudication superseded (forgery review H1) stays in the file and is read by nobody
            rows.append(cells)
    return header or [], rows


def record_after_table(path, keycol):
    """The free text a record holds after its main table (the table whose header has `keycol`):
    updates, corrections and notes written below the rows. A reader of the report must see them --
    stale table text shown without its correction misled report readers (release 0.1.0, A2)."""
    if not os.path.exists(path):
        return ""
    lines = open(path, encoding="utf-8").read().splitlines()
    in_t, seen, after = False, False, []
    for line in lines:
        st = line.strip()
        if st.startswith("|"):
            cells = project.split_row(st)
            if not in_t and not seen and any(c.strip("* ").lower().startswith(keycol) for c in cells):
                in_t = True
            continue
        if in_t:
            in_t, seen = False, True
        if seen:
            after.append(line)
    return "\n".join(after).strip()


def open_questions(cfg):
    """[(round, lane, item, reason, note)]: every QUESTION row of EVERY adjudication whose item has
    no final answer yet (decisions.open_question_rows). It used to list only the newest round's
    rows, so an unanswered question from an earlier round could silently drop out of the report."""
    import decisions
    rs = project.rounds(cfg)
    return decisions.open_question_rows(cfg, rs) if rs else []


REVOTES_INTRO = ("Re-votes left unsettled: a Fail the adjudicator would have rejected only after a second, "
                 "independent look (REVOTE NEEDED), where no later decision exists -- because the re-vote never "
                 "ran, or its lane was set aside. Each is an open item for the human, also "
                 "in `DECISIONS.md`.")
DECIDED_INTRO = ("Who took the decisions the protocol leaves to a person after the intake: those a human took "
                 "(the setup at Checkpoint A, answers to stops, recorded stops the human closed) and every "
                 "decision the operator took on the reader's behalf, each in full. How to reverse a delegated "
                 "decision, and what it costs, is in `DECISIONS.md`.")
ROUTES_TITLE = "Proof routes and results the goals do not use"
ROUTES_INTRO = ("Where a Lean proof replaces the paper's argument by another route (from `DEVIATIONS.md`; a "
                "route nobody recorded is not listed), the paper's own argument for it is NOT formalized. A "
                "formalized result the goal results do not use (a dependency walk over the kernel's terms, "
                "`dependencies.py`, run by Phase 0 after the proofs) stands alone: the goal results do not rest "
                "on it.")


def open_revotes(cfg):
    """[(round, lane, item, reason, status)] of unsettled re-votes (decisions.open_revotes)."""
    import decisions
    rs = project.rounds(cfg)
    return [(r, l, i, why, "re-vote lane SET ASIDE" if ab else "re-vote not run or not adjudicated")
            for r, l, i, why, ab in decisions.open_revotes(rs)]


def proof_routes(cfg, deviations, header):
    """{"replaced": [text], "unused": [text] or None, "why": reason when unused is None}."""
    hv = header or ["#", "result", "the paper's route", "the lean route", "why different", "kind"]
    col = lambda r, name, i: (r[hv.index(name)] if name in hv and hv.index(name) < len(r) else (r[i] if i < len(r) else ""))
    replaced = [f"{col(r, '#', 0)}: {col(r, 'result', 1)} -- kind: {next((r[i] for i, h in enumerate(hv) if h.startswith('kind') and i < len(r)), '?')}"
                for r in deviations]
    p = os.path.join(REPO, cfg["rounds_dir"], "DEPENDENCIES.json")
    if not os.path.exists(p):
        return {"replaced": replaced, "unused": None,
                "why": "no DEPENDENCIES.json (Phase 0 writes it once the proofs exist, outside a statement round)"}
    try:
        d = json.load(open(p))
    except ValueError:
        return {"replaced": replaced, "unused": None, "why": "DEPENDENCIES.json is malformed"}
    if d.get("roots") == [] and "assumes" in d:
        # B5: the walk now runs without a goal result (for the assumptions); "unused" needs one
        return {"replaced": replaced, "unused": None, "why": "no goal result of the config matches an index row"}
    head = delivered_commit(cfg)       # ADDENDUM N2: never HEAD
    same = bool(head) and (str(d.get("commit", "")).startswith(head[:7]) or head.startswith(str(d.get("commit", "?"))[:7]))
    stale = "" if same else f" (computed at commit {d.get('commit')}" + (f", not at {head})" if head else ")")
    return {"replaced": replaced,
            "unused": [f"{u.get('result')}: `{u.get('lean')}`, not used by {', '.join(d.get('goal_results') or [])}{stale}"
                       for u in d.get("unused") or []]
                      # names the walk could not find were not checked: never reported as "used"
                      + [f"NOT CHECKED: `{m}` (named in the index, not found in the Lean environment){stale}"
                         for m in d.get("missing") or []], "why": ""}


QUESTIONS_INTRO = ("Every question the adjudicator put to the human (a QUESTION row of any round's "
                   "adjudication) that has no final answer yet, oldest round first. Answered ones are "
                   "not repeated here: they are in `DECISIONS.md` and in `RUN_LOG.md` under "
                   "`## Answered` (or as [DELEGATED] decisions). Then the classes of reviewer findings "
                   "set aside by the project configuration (`standing_defers`), each with the condition "
                   "for revisiting it.")


DECL_KW = r"(?:theorem|lemma|def|abbrev|structure|inductive|class|instance|opaque|axiom)"


def _lean_lines(rel, at=None):
    """The lines of Lean file `rel`: of the working tree, or (`at`, a commit of the Lean repository) as that
    commit has it. None when the file is not there."""
    if at is None:
        fpath = os.path.join(REPO, rel)
        return open(fpath, encoding="utf-8").read().splitlines() if os.path.exists(fpath) else None
    r = subprocess.run(["git", "-C", REPO, "show", f"{at}:{rel}"], capture_output=True)
    return r.stdout.decode("utf-8", "replace").splitlines() if r.returncode == 0 else None


def locate_names(cfg, names, at=None):
    """{name: 'File.lean:N'} for each name declared in the project's Lean files (short or
    qualified name; the last component is matched against the declaration line). `at`: the lines of
    that Lean commit, not of the working tree (the sign-off sheet says its lines are of its commit; trial
    #7 audit: a sheet re-rendered after the approval printed the final commit's lines under the approval's)."""
    want = {n: n.split(".")[-1] for n in names}
    found = {}
    for rel in cfg["lean_files"]:
        lines = _lean_lines(rel, at)
        if lines is None:
            continue
        for i, line in enumerate(lines, 1):
            m = re.match(r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable|partial|unsafe)\s+)*"
                         + DECL_KW + r"\s+([^\s:({\[]+)", line)
            if not m:
                continue
            short = m.group(1).split(".")[-1]
            for n, sh in want.items():
                if sh == short and n not in found:
                    found[n] = f"{rel}:{i}"
    return found


def has_table(path):
    """Whether `path` has a markdown table row other than a header separator."""
    if not os.path.exists(path):
        return False
    return any(line.strip().startswith("|") and not all(set(c) <= set("-: ") for c in project.split_row(line.strip()))
               for line in open(path, encoding="utf-8"))


MISSING_THEORY_RE = re.compile(
    r"(Mathlib|librar(?:y|ies)|Tau ?Ceti)[^|]{0,80}?\b(has no|have no|lacks?|lacking"
    r"|(?:does|did|has|have)(?: not|n't)(?: yet)? (?:have|contain|define|formali[sz]e|got)"
    r"|is missing|are missing|absent|not (?:yet )?available|unavailable)"
    r"|\b(?:no|not)\b[^|.]{0,50}\b(?:in|from) (?:Mathlib|the librar)"
    r"|(?:\bnot|n't) (?:yet )?(?:formali[sz]ed|defined|developed) in (?:Mathlib|the librar|any librar)"
    r"|\bbeyond (?:the )?librar|\bno [^|.]{0,40}\btheory (?:exists|available)", re.I)


# Mathlib's own dependencies: a project importing one directly relies on nothing beyond Mathlib
SHIPPED_WITH_MATHLIB = {"Batteries", "Aesop", "Qq", "Plausible", "ProofWidgets", "LeanSearchClient",
                        "ImportGraph", "Cli"}


def imported_libraries(cfg):
    """Root modules the project's files import, other than the project's own (Mathlib first).
    Read from the imports, not from the config's `libraries` (the libraries SEARCHED, which by
    default include Tau Ceti whether or not anything from it is used)."""
    own = {f.split("/")[0].removesuffix(".lean") for f in cfg["lean_files"]}
    roots = set()
    for f in cfg["lean_files"]:
        p = os.path.join(REPO, f)
        if os.path.exists(p):
            roots |= {m.split(".")[0] for m in re.findall(r"(?m)^(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?(\S+)",
                                                         open(p, encoding="utf-8").read())}
    roots -= own | {"Init", "Lean", "Std"} | SHIPPED_WITH_MATHLIB
    return sorted(roots, key=lambda r: (r != "Mathlib", r))


# trial #10 audit: a misspelt Mathlib name (a `Finset.` prefix where Mathlib's lemma is under `Set.`) went from the operator's
# Checkpoint A line into the sheet writer's text and was delivered on the sign-off sheet and in the report. A
# qualified Lean name a generated document cites -- in code (`A.b`) or after "Mathlib's" -- must exist.
_LNAME = r"[A-Z][\w'!?₀-₉ₐ-ₜ]*(?:\.[^\W\d][\w'!?₀-₉ₐ-ₜ]*)+"
CITED_LEAN_RE = re.compile(rf"`({_LNAME})`|\bMathlib(?:'s| lemma| theorem)\s+`?({_LNAME})")
NOT_A_NAME_EXT = (".lean", ".md", ".pdf", ".tex", ".json", ".py", ".txt", ".log", ".olean", ".toml", ".faults",
                  ".sh", ".probes", ".html", ".png", ".aux", ".lock")


def cited_lean_names(text):
    """The qualified Lean names `text` cites: a whole code span that is a dotted name with a capitalised first
    component (`Set.Foo.card_le`, `Paper.lemma_7_2`; not `n.choose`, not a file), and a dotted
    name after "Mathlib's" / "Mathlib lemma" / "Mathlib theorem", with or without backticks."""
    out = {(a or b).rstrip(".") for a, b in CITED_LEAN_RE.findall(str(text))}
    return sorted(n for n in out if not n.lower().endswith(NOT_A_NAME_EXT))


LEAN_NAMES_SRC = """open Lean in
#eval show CoreM Unit from do
  let env ← getEnv
  let ms := env.header.moduleNames
  for s in [{names}] do
    let n := s.toName
    unless env.contains n || ms.contains n || env.isNamespace n do
      let found := env.constants.fold (init := false) fun acc c _ => acc || (c.toString.endsWith ("." ++ s))
      unless found do IO.println s!"MISSING {{s}}"
"""


def missing_lean_names(cfg, names, run=None):
    """(missing, error): the names among `names` that are no declaration, module or namespace of the built
    project and the libraries it imports (a name relative to an opened namespace counts when some declaration
    ends with it), resolved in Lean; the project's own declarations first, without Lean. `error` (the Lean run
    failed) is never a pass: the caller reports it."""
    import dependencies
    ns = cfg.get("namespace") or ""
    decls = dependencies.project_decls(cfg)
    rest = [n for n in dict.fromkeys(names) if dependencies.resolve_name(n, ns, decls) is None]
    if not rest:
        return [], None
    mods = [f.removesuffix(".lean").replace("/", ".") for f in cfg["lean_files"]]
    src = "".join(f"import {m}\n" for m in imported_libraries(cfg) + mods) + LEAN_NAMES_SRC.format(
        names=", ".join(json.dumps(n) for n in rest))
    rc, out = (run or project.run_lean)(src)
    if rc != 0:
        return None, " ".join(out.split())[-400:]
    gone = [l_[len("MISSING "):].strip() for l_ in out.splitlines() if l_.startswith("MISSING ")]
    # a project name an earlier Lean commit declared is history, cited as such (a stop quoting the refutation's
    # first name, renamed since)
    return [n for n in gone if not _declared_earlier(cfg, n)], None


def _declared_earlier(cfg, name):
    """Did some commit of the Lean repository declare `name` (its last component, in a project Lean file)?"""
    short = name.split(".")[-1]
    r = subprocess.run(["git", "-C", REPO, "log", "--all", "--format=%h", "-G", rf"\b{re.escape(short)}\b", "--",
                        *cfg["lean_files"]], capture_output=True, text=True)
    for h in r.stdout.split():
        for rel in cfg["lean_files"]:
            if any(re.match(r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable)\s+)*" + DECL_KW
                            + r"\s+(?:\S*\.)?" + re.escape(short) + r"(?![\w'])", l_) for l_ in _lean_lines(rel, h) or []):
                return True
    return False


def cited_name_problems(cfg, docs, run=None):
    """[text] for each generated document of `docs` ({name: text}) citing a Lean name that does not exist
    (cited_lean_names, missing_lean_names), or one line if the names could not be resolved."""
    cites = {d_: cited_lean_names(t_) for d_, t_ in docs.items() if t_}
    every = sorted({n for ns_ in cites.values() for n in ns_})
    if not every:
        return []
    missing, err = missing_lean_names(cfg, every, run=run)
    if err is not None:
        return [f"the Lean names the documents cite could not be resolved (the Lean run failed: {err}); build the "
                f"project and run the check again"]
    return [f"{d_} cites `{n}`, which is no declaration, module or namespace of the project or the libraries it "
            f"imports (resolved in Lean against the build): correct the text that says it -- its source record or "
            f"the operator's line -- and generate the document again"
            for d_, ns_ in cites.items() for n in ns_ if n in missing]


def libraries_phrase(cfg):
    """`with the Mathlib library`, or which other libraries the statements and proofs rely on."""
    libs = imported_libraries(cfg) or ["Mathlib"]
    if libs == ["Mathlib"]:
        return "with the Mathlib library"
    others = [l for l in libs if l != "Mathlib"]
    return ("with the Mathlib library and also " + " and ".join(others) + ", "
            + ("a smaller library" if len(others) == 1 else "smaller libraries")
            + " less widely reviewed than Mathlib, so what is taken from "
            + ("it" if len(others) == 1 else "them") + " carries less assurance")


HUMAN_ANSWER_SECTIONS = re.compile(r"^## (Answered|Checkpoint B|Checkpoint C|Stage 2|Open questions)\b(.*)$")


def run_log_text(cfg):
    p = os.path.join(REPO, cfg["rounds_dir"], "RUN_LOG.md")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def _row_names(what):
    """The forms under which a RUN_LOG.md line names a SKIPPED.md row's result: its paper names, its
    backticked declarations, the anchor form (`lemma-2-3`); else the cell's first clause."""
    names = set(_names_in(what)) | {t.strip().lower() for t in re.findall(r"`([^`]+)`", what)}
    if not names and what.strip():
        names.add(re.sub(r"\s+", " ", what.split(",")[0].strip()).lower())
    # the anchors `skip:lemma-2-3` and `question:Lemma_2.3` (decisions.py) name it too
    return (names | {re.sub(r"[^a-z0-9]+", "-", n).strip("-") for n in names}
            | {re.sub(r"\s+", "_", n) for n in names})


def _names_line(names, line):
    low = re.sub(r"\s+", " ", line).lower()
    return any(n and n in low for n in names)


def missing_theory_answers(run_log, names):
    """{"human": [(date, line)], "proxy": [line], "delegated": [line]}: the RUN_LOG.md lines that record
    a decision about the result `names` name (sweep N1: a missing-theory "decided by" is bound to one).
    A human answer is a line of `## Answered`, `## Checkpoint B`/`C` (not a delegated one), `## Stage 2`,
    or an "(answered <date>: …)" line of `## Open questions`, with no [PROXY]/[DELEGATED] tag; its date
    is the line's or its section header's."""
    out = {"human": [], "proxy": [], "delegated": []}
    sec = hdr = None
    for line in run_log.splitlines():
        if line.startswith("## "):
            m = HUMAN_ANSWER_SECTIONS.match(line)
            sec, hdr = (m.group(1), line) if m else (None, line)
            continue
        if not line.strip() or not _names_line(names, line):
            continue
        if re.search(r"\[PROXY", line):
            out["proxy"].append(line)
        elif decisions_tag_re().search(line):
            out["delegated"].append(line)
        elif sec and "delegated" not in hdr.lower() and (sec != "Open questions" or re.search(r"\banswered\b", line)):
            out["human"] += [(d, line) for d in dict.fromkeys(re.findall(r"\d{4}-\d{2}-\d{2}", line + " " + hdr))]
    return out


def _question_rows(cfg, names):
    """The ADOPTED.md QUESTION rows (any round, the one being adjudicated included) whose item or
    reason names the result."""
    out = []
    for f in sorted(glob.glob(os.path.join(REPO, cfg["rounds_dir"], "*", "ADOPTED.md"))):
        for r in table_rows(f):
            if len(r) > 3 and re.match(r"\W*QUESTION", r[3]) and _names_line(names, " ".join(r[1:])):
                out.append((os.path.basename(os.path.dirname(f)), r))
    return out


def missing_theory_problems(cfg, header, rows, run_log=None):
    """A skip blamed on a library lacking a definition or theorem is the human's decision
    (RUN.md, "Missing theory"): its row must say every configured library was searched, and its
    "decided by" must be BOUND to a recorded decision (sweep N1): "human (<date>)" to a human answer
    in RUN_LOG.md naming the result with that date, "operator [PROXY …]" to a [PROXY] line naming it,
    "operator [DELEGATED …]" (a delegating level only) to a line with that tag naming it. Without
    any such line the question is still the human's: "QUESTION (<round>)" with a QUESTION row in
    ADOPTED.md naming the result routes it to the human's question path (Checkpoint C, DECISIONS.md);
    no finding then. Every fault here is the adjudicator's to clear (adj-record), and each message
    names a cell it can write without inventing a decision. "Mathlib has no graphons" once stood as
    the whole reason, while Tau Ceti had the theorem the proof needed."""
    out = []
    libs = project.libraries(cfg)
    log = run_log_text(cfg) if run_log is None else run_log
    hi = lambda pre: next((i for i, h in enumerate(header) if h.startswith(pre)), None)
    i_how, i_dec, i_what = hi("how"), hi("decided"), hi("what")
    for row in rows:
        text = " ".join(row)
        if not MISSING_THEORY_RE.search(text):
            continue
        how = row[i_how] if i_how is not None and i_how < len(row) else ""
        norm = re.sub(r"\s+", "", how).lower()
        unsearched = [l for l in libs if re.sub(r"\s+", "", l).lower() not in norm]
        if unsearched:
            out.append(project.Finding(
                f"! SKIPPED.md row {row[0][:20]}: skipped for missing library theory, but "
                f"\"how this was checked\" does not record a search of {', '.join(unsearched)}", "adj-record"))
        dec = row[i_dec] if i_dec is not None and i_dec < len(row) else ""
        what = row[i_what] if i_what is not None and i_what < len(row) else (row[1] if len(row) > 1 else "")
        names = _row_names(what)
        ans = missing_theory_answers(log, names)
        dl = project.delegates(cfg)
        # the cells a recorded decision supports, in the form the adjudicator copies
        ok_cells = ([f"human ({d})" for d, _l in ans["human"]] + (["operator [PROXY …]"] if ans["proxy"] else [])
                    + ([f"operator {decisions_tag_re().search(l).group(0)}" for l in ans["delegated"]] if dl else []))
        m_h = re.search(r"\bhuman \((\d{4}-\d{2}-\d{2})\)", dec)
        # a [DELEGATED] cell: the dated canonical tag after "operator", on a delegating level only, and
        # the very tag of a RUN_LOG.md line naming the result
        m_d = re.search(r"operator (" + decisions_tag_re().pattern + ")", dec)
        bound = ((m_h and any(d == m_h.group(1) for d, _l in ans["human"]))
                 or (re.search(r"operator \[PROXY", dec) and ans["proxy"])
                 or (dl and m_d and any(m_d.group(1) in l for l in ans["delegated"])))
        if bound:
            continue
        if not ok_cells and re.match(r"\s*QUESTION\b", dec) and _question_rows(cfg, names):
            continue          # open: the human's question (Checkpoint C); nothing for the adjudicator
        if ok_cells:
            cure = ("write \"decided by\" as " + " or ".join(f"\"{c}\"" for c in dict.fromkeys(ok_cells))
                    + " (the RUN_LOG.md line naming it)")
        else:
            cure = ("RUN_LOG.md records no human answer, [PROXY] or [DELEGATED] decision naming it, so no one has "
                    "decided it: never type one; give it a QUESTION row in ADOPTED.md (item: its index label) and "
                    "write \"decided by\" as \"QUESTION (<round>)\" -- the question goes to the human"
                    + (" (the operator decides it under the delegating level, with a [DELEGATED] line)" if dl else
                       " at Checkpoint C"))
        out.append(project.Finding(
            f"! SKIPPED.md row {row[0][:20]}: a missing-theory skip is the human's decision; its \"decided by\" "
            f"must be bound to the recorded decision (RUN.md, \"Missing theory\"): {cure}", "adj-record"))
    return out


def prose_only_defects(path):
    """A defect stated only in prose ("Observation 1.20 is false as printed") reaches neither the
    report nor the box: every defect is a table row (rule 3). Flags a prose line saying "false as
    printed" that names a result no row of the defects table mentions."""
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    _, rows = record_table(path, DEFECT_KEY)
    in_rows = " ".join(" ".join(r) for r in rows).lower()
    out = []
    for line in text.splitlines():
        if line.strip().startswith("|") or not re.search(r"false as printed", line, re.I):
            continue
        names = re.findall(rf"\b(?:{project.RESULT_KINDS_RE})\s+\d+(?:\.\d+)+", line, re.I)
        missing = [n for n in dict.fromkeys(names) if n.lower() not in in_rows]
        if missing:
            out.append(f"! PAPER_DEFECTS.md: {', '.join(missing)} is called false as printed in prose but has "
                       f"no row in the defects table: give it a row")
    return out


# trial #7 audit: the defect rows cite F10, F12 and probes, which the report never defined
F_TERMS = ("*F10* is a fresh paper-faithfulness reviewer's check that a counterexample to a printed result is "
           "a real counterexample to the paper (not an artefact of the Lean encoding); *F12* is its check that "
           "a repair of a false result is the minimal one the paper's own proof supports. A *probe* is a small "
           "Lean check a reviewer runs (an instance evaluated, a hypothesis shown satisfiable) and records in "
           "its round directory.")
SECTION_OF = {"defect": 5, "proof slip": 5, "not formalized": 4, "proof route": 6, "vacuous": 7, "stated, not proved": 3}
# the coverage section's note on results a [DELEGATED] decision left unproved (decisions.unproved)
UNPROVED_MD = ("Each declaration below is stated in the Lean exactly as approved but has no proof (it "
               "ends in `sorry`): after a serious attempt the operator left it unproved, under the "
               "delegating involvement level chosen at intake, rather than delete or weaken it. It is not "
               "formalized in the sense of this report, and it is listed in section 4 too. Every result "
               "whose proof uses one of them is in this list as well (the axiom sweep refuses any other "
               "declaration that reaches `sorryAx`), and so is every auxiliary declaration the sweep "
               "accepts under one of their names (an equation lemma or the like, generated with no "
               "source range), with its parent; a goal result is never left unproved this way. "
               "Reversal: prove it (re-prove).")


def front_matter(cfg):
    """(box lines, background paragraphs), both markdown, shared by REPORT.md and REPORT.pdf.

    The box (AUDIT_PROTOCOL.md "Documents a human reads", rule 5) lists what a reader who stops
    after page 1 must still learn: every defect in the source, every result not formalized, every
    route change of a kind other than "same strength"/"reading choice", every statement true only
    vacuously -- the same list decisions.py puts in the decisions document's box -- plus a
    statement approval not made by a human, and Lean changes no audit round examined (rule 4).
    The background (rule 1) says what was done, where everything is, how the protocol works and
    what its terms mean, so no sentence below needs a file the reader does not have."""
    import decisions
    root = os.path.join(REPO, cfg["rounds_dir"])
    box = []
    for bl in decisions.box_lines(cfg):
        sec = next((v for k, v in SECTION_OF.items() if bl.startswith(k)), None)
        found = decided_since_text(cfg, bl) if bl.startswith("vacuous") else []
        box.append(bl + (f" (details: section {sec})" if sec else "")
                   + (f" -- open in the adjudicator's record, but {len(found)} [DELEGATED] decision(s) on it "
                      f"since (section \"{DECIDED_TITLE}\")" if found else ""))
    appr_p = os.path.join(root, "APPROVED_FINGERPRINTS.json")
    appr = json.load(open(appr_p)) if os.path.exists(appr_p) else None
    dl = delegation(cfg)
    if not appr:
        box.append("statement approval: NONE -- no one has approved the Lean statements (section 1)")
    elif project.approval_file_by(appr_p, appr)[0] != "human":
        box.append("statement approval: the Lean statements were NOT approved by a human "
                   + ((f"(the agent approved them under the {dl[0]} involvement level chosen at intake)"
                       if dl and dl[0] == "hands-off" else
                       "(the agent approved them; the statements-only level does not allow that)"
                       if dl and dl[0] == "statements-only" else "(the agent approved them, on the human's instruction)")
                      if project.approval_file_by(appr_p, appr)[0] == "agent" else "(the approver was not recorded)")
                   + " (section 1)")
    if dl:
        box.append(f"decisions taken on your behalf: {len(dl[2])} decision(s) were taken by the operator, "
                   f"not by a human, under the {dl[0]} involvement level chosen at intake (answer: "
                   f"\"{dl[1]}\"); each is final, its tag says what reversing it costs, and it is listed with how to reverse it "
                   f"in `{os.path.join(root, 'DECISIONS.md')}` and in section \"{DECIDED_TITLE}\"")
                   # (trial #7 audit: it said "section 1", the trust table; the list is in its own section,
                   # numbered 8 or 9 depending on the reader notes, so it is named by title)
    if os.path.exists(os.path.join(root, "READER_NOTES.md")):
        # records rendered in the box may predate the human's answers or later commits; the
        # formalizer's notes carry the current status, and a reader of page 1 must be told so
        box.insert(0, "current status: some lines below are copied from records written before the "
                      "human's answers or the last commits; section 1 (Notes for the reader) gives "
                      "each one's current status and corrects them")
    lr = later_row(cfg)
    if lr and not lr[2].startswith("none"):
        box.append("Lean changes after the last audit round, not examined by any reviewer (section 1)")
    head = delivered_commit(cfg)       # ADDENDUM N2: never HEAD
    audits = os.path.join(REPO, "audits")
    bg = [
        ("What this is",
         f"A formalization in Lean 4 ({libraries_phrase(cfg)}) of {cfg['source_cite']}. The source "
         f"file is `{cfg.get('source_pdf', '?')}`. The Lean code is in the repository `{REPO}`, "
         f"branch `{cfg.get('branch', '?')}`, commit `{head}`, namespace `{cfg.get('namespace', '?')}`; "
         f"its files are " + ", ".join(f"`{x}`" for x in cfg.get("lean_files", [])) + ". The "
         f"audit record is the directory `{root}`."),
        ("How it was checked",
         "The Lean statements of the paper's results were written and committed first, and reviewed "
         "and approved at a checkpoint (Checkpoint B); section 1 says who approved them, at which "
         "commit and when, and that the freeze check shows none has changed since (drafts of proofs "
         "may exist before the approval; the fingerprints, not the order of work, are what the "
         "record proves). Lean's kernel checks every proof. Then audit rounds: "
         "independent AI reviewers, each holding one criterion (the \"AI reviewer\" rows of "
         "section 1), examined the statements and proofs. An adjudicator decided each failed check: "
         "ADOPT (fix it), REJECT (the finding or proposed change was declined; see the recorded reason), DEFER (later, with a condition for "
         "revisiting it), or QUESTION (only the human can decide). A decision marked [PROXY] was "
         "taken by the operator on the human's behalf and awaits the human's confirmation."
         + (f" A decision marked [DELEGATED] was taken by the operator under the {dl[0]} involvement "
            "level the human chose at intake (the human is not asked about it); it is final, but can "
            "be reversed." if dl else "")),
        ("Terms used below",
         "The *formalizer* (the party audited) wrote the Lean; the *operator* runs the protocol; the "
         "*adjudicator* is an AI agent that decides each failed check; the *human* is the "
         "mathematician the protocol answers to. Checkpoint A fixed the setup (which literature "
         "results are assumed); Checkpoint B approved the statements; "
         + ("Checkpoint C puts the remaining "
            "decisions to the human: they are in `DECISIONS.md`, delivered with this report, until the "
            "human has answered them; the answers are recorded verbatim in `RUN_LOG.md`, under "
            "`## Answered`." if not (dl and dl[0] in DELEGATED_WHO) else
            f"at Checkpoint C, under the {dl[0]} level, the operator took the remaining decisions "
            "itself: they are in `DECISIONS.md`, delivered with this report, each with how to reverse "
            "it.")
         + " Phase 0 is the mechanical gate run before every round and before "
         "this report: the Lean builds, no `sorry`, only the standard axioms, approved statements "
         "unchanged. In section 1, an *item* is one Lean declaration or paper result a reviewer "
         "examined; *stale* means a verdict given on an earlier version of it; a *blanket* approval "
         "approved every result at once. "
         "A round is named `YYYY-MM-DD-<commit>` after the Lean commit it examined; `full-` marks a "
         "round that examined everything rather than only the changes. Each round is a directory "
         "of the audit record, holding the reviewers' verdicts and the adjudicator's decisions "
         "(`ADOPTED.md`). `AUTHOR_NOTES.md` (in the audit record) holds the formalizer's numbered "
         "notes on reading choices (not the paper author's). `tex N` or `tex l.N` is line N of the source file; `File.lean:N` is "
         "line N of that Lean file at the commit above (except where a record's line is older; "
         "those are listed under \"Stale line numbers\"). Route changes are numbered 1, 2, ... in "
         "section 6. A *standing defer* is a rule in the project configuration "
         "(`audits/projects/<project>.json`, key `standing_defers`) that sets a whole class of "
         "reviewer findings aside, with a condition for revisiting it; reviewer lanes are named "
         "`criterion@N`, part N of a round. An *out-of-lane note* is a reviewer's remark outside its "
         "own criterion; a *lead* is such a remark that the adjudicator records for a later round. "
         "UNCOVERED marks an item no reviewer returned a verdict on. *Intake* is the set-up "
         "questionnaire answered by the human before Checkpoint A; `blind_spots` is the key of the "
         "project configuration listing material declared out of scope. " + F_TERMS + " " + SEVERITY_MD),
    ]
    gl = global_differences(cfg)
    if gl:
        bg.append(("Global differences (" + ", ".join(g for g, _ in gl) + ")",
                   "The sign-off sheet states once, at its top, each way all Lean statements differ from the "
                   "paper in the same manner (a *global difference*); a result marked GLOBAL differs only "
                   "through those, and a decision may cite one by its label. "
                   + " ".join(f"{g}: {t}" for g, t in gl)))
    return box, bg


def global_differences(cfg):
    """[(label, "title -- text")] of the approved (else newest) sign-off sheet's global differences:
    their labels (G1, G2, ...) appear in decisions, so the report defines them (a test run)."""
    import decisions
    rs = project.rounds(cfg)
    appr_p = os.path.join(REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json")
    try:
        appr = json.load(open(appr_p)) if os.path.exists(appr_p) else None
        _, so = decisions.latest_signoff(rs, appr)
    except (OSError, ValueError):
        return []
    return [(str(g.get("id")), f"{g.get('title', '')} -- {' '.join(str(g.get('text', '')).split())}")
            for g in (so or {}).get("global", []) or []]


# --- the one-page summary (B10; U2 §6.1, §6.5; D3; approver: "one-page summary first") ----------------------
# SUMMARY.md / SUMMARY.pdf are ONE page, delivered first: a mathematician reads it before anything else and must
# get a true picture from it. In order: the goal result's status (one line); the results, grouped by their status
# (B9's result_status in plain words, equal statuses on one row); every defect in the source, proof slip, vacuous
# statement, assumption and the record's other disclosures, one short line each; the stops (one line each; a hand
# delivery says so); the answers recorded as yours (receipts); one line on the decisions (the number of distinct
# matters in DECISIONS.md). When the page is full, the items of a kind are counted on one line that names each by
# its number and the REPORT section holding them in full (never dropped). Generated only (never written by hand).
# summary_problems() (inside make_report.py --check --delivery) re-enumerates the record and refuses a summary on
# which an item is neither listed nor counted. Its PDF (render_record.py) is one page: the renderer fits it, the
# verifier fails a longer one (PDF-AGENTS).
SUMMARY_MD = "SUMMARY.md"
SUMMARY_POINTER = ("**0. Summary.** Read the summary first (`SUMMARY.pdf`, its markdown `SUMMARY.md` beside it; "
                   "delivered with this report): one page with the goal "
                   "result's status, every result's status, every defect in the source, proof slip, vacuous "
                   "statement, assumption and stop that waited for you (each on one line, or counted with a pointer to "
                   "the section of this report that holds it), the answers recorded as yours, and the number of "
                   "matters decided in DECISIONS.md. This report is its appendix A. How the run went (self-cured "
                   "stops, set-asides, process events) is in RUN_RECORD.md, appendix D.")
# a result's status (U2 §1) is result_status.py's (B9): "faithful" only when every review of it is Pass and current
# and nothing else applies (U2 §6.5: nothing defaulted to faithful)


def delivered_commit(cfg, short=True):
    """The Lean commit the generated documents cite (ADDENDUM N2): the last commit of the Lean repository
    that changed a project Lean or build file, never HEAD (a commit of anything else moves HEAD and must not
    change a generated document). HEAD when git cannot tell."""
    return project.delivered_commit(cfg, short, repo=REPO)


def _names_of(cell):
    return [t.split("(")[0].strip() for t in re.findall(r"`([^`]+)`", str(cell)) if IDENT.match(t.split("(")[0].strip())]


def _mentions(text, label, names):
    """Does a record's text name this result (result_status.mentions: part-aware, "Lemma 7.2 (c)" does not name
    "Lemma 7.2 (a)")?"""
    import result_status
    return result_status.mentions(text, label, names)


def _dot(t):
    """A cell joined before ". ": without its own final period (never ".."; nothing else is cut)."""
    t = str(t).rstrip()
    return t[:-1] if t.endswith(".") and not t.endswith("..") else t


def summary_inputs(cfg):
    """Everything the summary reads, once (G1-G8: records, the Lean, git; never a reader's or --deliver's
    output, never a delivery-phase record)."""
    import decisions, stops
    rd = os.path.join(REPO, cfg["rounds_dir"])
    inp = {"rd": rd}
    index = table_rows(os.path.join(REPO, project.index_file(cfg)))
    inp["index"] = [r for r in index if r and RESULT.match(r[0])]
    for k, f, keycol in (("skipped", "SKIPPED.md", "what"), ("deviations", "DEVIATIONS.md", "kind"),
                         ("vacuous", "VACUOUS.md", "statement")):
        inp[k] = record_table(os.path.join(rd, f), keycol)
    # the defects table as the report, the box and DECISIONS.md read it (an old `severity` table included: it
    # stays listed while PENDING[adj-record] waits for the adjudicator's rewrite)
    dh_, drows_, _p, _old = defects_table(os.path.join(rd, "PAPER_DEFECTS.md"))
    inp["defects"] = ([h.lower() for h in dh_], drows_)
    # as the report shows them (build): the adjudicator's LaTeX set as code, line numbers resolved from names
    for k in ("skipped", "defects", "vacuous") + (("deviations",) if deviations_adjudicators(rd) else ()):
        h_, rows_ = inp[k]
        inp[k] = (h_, [[refresh_lines(codeify_latex(c), cfg) for c in row] for row in rows_])
    try:
        inp["unproved"] = decisions.unproved(cfg)["decls"]
    except Exception:       # noqa: BLE001 -- listed as unreadable, never dropped
        inp["unproved"] = {}
    inp["questions"] = open_questions(cfg)
    ap = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
    try:
        inp["approval"] = json.load(open(ap)) if os.path.exists(ap) else None
    except ValueError:
        inp["approval"] = None
    inp["assumptions"] = assumptions(cfg)
    inp["globals"] = global_differences(cfg)
    inp["stops"] = stops.stop_rows(cfg, phase="run")
    inp["disclosed"] = stops.disclosed_rows(cfg, phase="run")
    dl = delegation(cfg)
    inp["delegation"] = dl
    inp["delegated"] = delegated_items(cfg, dl[2]) if dl and dl[2] else []
    inp["reapprovals"] = reapproval_rows(cfg)
    inp["setasides"] = set_asides(cfg)
    inp["later"] = later_row(cfg)
    inp["trust"] = trust_rows(cfg)
    inp["human_answers"] = recorded_human_answers(cfg)      # forgery review H2
    inp["superseded"] = superseded_rows(rd)                 # forgery review H1
    return _summary_extra(cfg, inp)


def _summary_extra(cfg, inp):
    """`inp` with the one-page summary's own inputs, those it lacks: idle hypotheses of approved statements
    (UNUSED_ARGS.md), PAPER_DEFECTS.md's "Not defects" entries (trial #9: an idle hypothesis was recorded only there)
    and its slips, the number of decision matters (DECISIONS.md's sections), of [PROXY] and [DELEGATED] lines."""
    import decisions
    if all(k in inp for k in ("unused", "not_defects", "slips", "matters", "proxies", "n_delegated")):
        return inp
    inp = dict(inp)
    rd = os.path.join(REPO, cfg["rounds_dir"])
    inp["unused"] = decisions.unused_hypotheses(rd)
    pdp = os.path.join(rd, "PAPER_DEFECTS.md")
    pd_text = open(pdp, encoding="utf-8").read() if os.path.exists(pdp) else ""
    inp["not_defects"] = [project.full(b[2:]) for b in decisions.log_entries(decisions.section(pd_text, "Not defects"))
                          if b.startswith("- ") and b[2:].strip(" .").lower() not in ("none", "none yet", "(none)")]
    inp["slips"] = decisions.slip_rows(rd)
    rs = project.rounds(cfg)
    try:
        dl_ = inp.get("delegation") if "delegation" in inp else delegation(cfg)
        # DECISIONS.md's sections (one per matter); before any round, the matters of the [DELEGATED] lines
        inp["matters"] = (decisions.n_sections(decisions.skeleton(cfg, rs, rs[-1])[0]) if rs else
                          n_matters(cfg, dl_[2]) if dl_ and dl_[2] else 0)
    except Exception as e:      # noqa: BLE001 -- shown, never a silent 0
        inp["matters"] = f"not counted ({type(e).__name__}: {e})"
    log = run_log_text(cfg)
    inp["proxies"] = sum(1 for b in decisions.log_entries(decisions.strip_sections(log, decisions.LOG_SKIP_SECTIONS))
                         if decisions.PROXY_RE.search(b))
    inp["n_delegated"] = len(decisions.delegated_decisions(log))
    return inp


def _col(head, row, name):
    i = next((k for k, h in enumerate(head or []) if h.lower().startswith(name)), None)
    return row[i] if i is not None and i < len(row) else ""


def result_status(cfg, row, inp):
    """[status] of one index row, every one that applies, in U2 §1's order: result_status.py (B9). "faithful"
    only when every review of the result is Pass and current and nothing else applies; never by default."""
    import result_status as _rs
    return _rs.result_status(cfg, row, inp)


def plain_status(statuses):
    """B9's statuses of one result in plain words, without row numbers, witnesses or reasons (those are on the
    lines below the table and in the report), so that equal statuses collapse into one row of the table. Never
    "faithful" unless B9 says exactly that."""
    out = []
    vac = any(s.startswith("defect ") and "vacuous as printed" in s for s in statuses)
    for s in statuses:
        s = " ".join(str(s).split())
        m = re.match(r"defect \S+: (.*)$", s)
        if m:
            body = re.sub(r" \((witness [^()]*(\([^()]*\)[^()]*)*|no Lean witness)\)$", "", m.group(1))
            if "severity" in body.split(" — ")[0] and "old-format" in body:
                p = "a defect (status not yet recorded)"
            else:
                p = body.split(" — ", 1)[1] if " — " in body else body
        elif s.startswith("vacuous (VACUOUS row"):
            p = None if vac else "true only vacuously"
        elif s.startswith("stated only ("):
            p = "stated only (a conjecture)" if "a conjecture" in s else "stated only, not proved"
        elif s.startswith("not formalized"):
            p = "not formalized"
        elif s.startswith("decision open"):
            p = "a decision is open" + (": its statement awaits re-approval" if "awaits re-approval" in s else "")
        elif s.startswith("differs"):
            p = "differs from the paper"
        elif s.startswith("faithful under reading"):
            p = "faithful under a reading choice"
        elif s.startswith("reading choice"):
            p = "a reading choice"
        elif s.startswith("not established"):
            # the kind of reason, so equal ones collapse (the reason itself: REPORT §1 and section 3)
            why = s[len("not established"):]
            p = ("not established: a review failed" if re.search(r"\b(Fail|Reject|Unclear)\b", why) else
                 "not established: a review is out of date" if "out of date" in why else
                 "not established: a review is missing" if re.search(r"\bno \S+ verdict\b", why) else
                 "not established: an assumption is not settled" if "assumption" in why or "hypothesis" in why else
                 "not established")
        elif s.startswith(("proved assuming", "stated assuming")):
            p = re.sub(r" \((?!`).*$", "", s.split(";")[0])
            p = re.sub(r"`([^`]*\.)?([^`.]+)`", r"`\2`", p)
        else:
            p = s
        if p and p.startswith("not established"):
            ne = next((i for i, x in enumerate(out) if x.startswith("not established")), None)
            why = p[len("not established: "):] if p.startswith("not established: ") else ""
            if ne is None:
                out.append(p)
            elif why and why not in out[ne]:
                out[ne] = (out[ne] + "; " + why) if ":" in out[ne] else f"not established: {why}"
            continue
        if p and p not in out:
            out.append(p)
    return "; ".join(out) or "not established"


ANSWERS_SECTION = "Answers recorded as yours"
ANSWERS_INTRO = ("Check that you gave each: the protocol cannot verify who typed them. The audit commit that recorded "
                 "each is your receipt (a later rewrite of the run's history changes it).")
ANSWER_PREFIXES = {"answer": "answer", "stop answer": "question answer", "approval": "approval", "stop": "stop decision"}
SUMMARY_LEGEND = ("*faithful*: every review of the Lean statement against the paper passed on its current version, "
                  "nothing is assumed beyond the paper, standard axioms only. *not established*: a review is missing, "
                  "out of date, failed or not settled; nothing is claimed. Any other status says what holds instead.")

# the groups of the page, in order, and the kinds of line in each (a kind not listed is not itemized: the results
# table holds `excluded`; the decisions line counts the delegated and proxy decisions)
PAGE_GROUPS = (
    ("Defects in the paper, proof slips, vacuous statements", ("defect", "proof slip", "vacuous", "not a defect")),
    ("Assumptions, and where the Lean differs", ("assumptions", "missing theory", "assumption", "unused hypothesis",
                                                 "assumption note", "stated only", "not formalized", "reading choice",
                                                 "proof route", "global difference")),
    # approver (2026-10-24): the self-cured stops, set-asides and disclosed faults are the process record
    # (RUN_RECORD.md); the page keeps the stops that waited for you (open, or answered by you) and a hand delivery
    ("Stops, hand deliveries and notices", ("stop", "hand delivery", "not run", "after the last audit round",
                                            "re-approval", "waiver", "superseded row", "standing defer",
                                            "blind spots")),
    (ANSWERS_SECTION, tuple(ANSWER_PREFIXES.values())),
    ("Decisions", ("open question",)),
)
# when the page is full, kinds are counted (not listed) in this order: the least a reader must see first
# when the page is full, items are counted (named on one line, with the place of their full text) instead of listed:
# first the kinds a reader can most easily miss without harm, one item at a time; then the answers (their receipts
# stay in REPORT); then, evenly, the kinds a reader must see (the one with the most lines listed gives one up first)
COLLAPSE_LOW = ("not a defect", "global difference", "superseded row", "standing defer", "stated only",
                "not formalized", "reading choice", "proof route", "waiver", "re-approval")
COLLAPSE_ANSWERS = ("answer", "question answer", "approval", "stop decision")
COLLAPSE_EVEN = ("assumption", "missing theory", "open question", "unused hypothesis", "stop",
                 "proof slip", "vacuous", "defect")
SINCE_SHORT = "decided by the operator on your behalf"     # a summary line's word for a [DELEGATED] decision since
SHORT_MAX = 130         # a line's free text longer than this is shortened to its first sentence, with a pointer
CPL = 100               # characters per rendered line (calibrated on the snapshots, with a margin)
PAGE_LINES = 62         # estimated lines a page holds (calibrated on 10pt pages: they overflowed at 67)


def report_sections(cfg):
    """{kind: the REPORT section that holds it in full}. Approver (2026-10-24): eleven fixed sections -- 1 trust,
    2 assumptions, 3 coverage, 4 not formalized, 5 defects, 6 differences, 7 vacuous, 8 open questions, 9 decisions,
    10 proof routes, 11 where the Lean names are (the reader notes end section 1, the notation section 11)."""
    return {"trust": 1, "assumptions": 2, "coverage": 3, "skipped": 4, "defects": 5, "deviations": 6, "vacuous": 7,
            "questions": 8, "decided": 9, "routes": 10, "names": 11, "background": None}


SECTION_KIND = {"defect": "defects", "proof slip": "defects", "not a defect": "defects", "vacuous": "vacuous",
                "assumptions": "assumptions", "missing theory": "assumptions", "assumption": "assumptions",
                "assumption note": "assumptions", "unused hypothesis": "decisions-doc", "stated only": "coverage",
                "not formalized": "skipped", "reading choice": "deviations", "proof route": "deviations",
                "global difference": "background", "stop": "decided", "hand delivery": "decided", "not run": "trust",
                "after the last audit round": "trust", "re-approval": "trust", "waiver": "trust", "superseded row": "trust",
                "standing defer": "questions", "blind spots": "trust", "answer": "decided", "question answer": "decided",
                "approval": "decided", "stop decision": "decided", "open question": "questions",
                "excluded": "coverage"}


def _where(cfg, prefix, sec=None):
    """Where a kind's full text is: "REPORT §N", the report's background, or DECISIONS.md."""
    k = SECTION_KIND.get(prefix, "trust")
    if k == "decisions-doc":
        return "DECISIONS.md"
    n = (sec or report_sections(cfg)).get(k)
    return f"REPORT §{n}" if n else "the REPORT's background"


SENTENCE_END = re.compile(r"[.;:](?=\s+[A-Z(“\"*`])")
CLAUSE_END = re.compile(r"[.;:](?=\s)")


def _short(t, limit=SHORT_MAX):
    """(text, shortened?): `t` on one line when it is short; else its first sentence, when that is short; else
    (\"\", True). Never a cut word: the caller points to the full text."""
    t = project.full(t).replace("**", "")
    if len(t) <= limit:
        return t, False
    # the first sentence (not "1." of a numbered answer), else the first clause (a slip's "Proof of Lemma 7.4(a),
    # tex l.214-218: the text says ...")
    for pat in (SENTENCE_END, CLAUSE_END):
        m = next((m for m in pat.finditer(t) if m.start() >= 20
                  and t[:m.start()].count("(") == t[:m.start()].count(")")), None)
        if m and m.start() <= limit:
            return t[:m.start()], True
    # trial #11: a first sentence longer than the limit left the line empty ("not a defect 2 — (full text in
    # REPORT §5)"): the longest leading run of whole clauses ending at a comma, parentheses balanced
    cut = [m.start() for m in re.finditer(r",(?=\s)", t[:limit + 1])
           if m.start() >= 20 and t[:m.start()].count("(") == t[:m.start()].count(")")]
    if cut:
        return t[:cut[-1]], True
    return "", True


LEAD_STOP = re.compile(r"\s\(|[,;:.](?=\s|$)|\s(?:is|are|was|were|has|have|holds?|assumes?|uses?|says?|states?|"
                       r"needs?|means?|keeps?|gives?)\s")


def _lead(t, limit=60):
    """What a "Not defects" item is about, in its own first words: the text up to its first verb, parenthesis or
    punctuation ("Claims outside numbered environments", "Theorem 7.9", "Corollary 7.6(b)"); a one-word label before
    a colon keeps what follows it ("Scope: the unnumbered Remark after Corollary 7.5"). "" when that is longer than
    `limit` or is no phrase."""
    t = " ".join(project.full(t).replace("**", "").split())
    m = LEAD_STOP.search(t)
    if m and t[m.start()] == ":" and " " not in t[:m.start()]:
        m2 = LEAD_STOP.search(t, m.end())
        lead = t[:m2.start() if m2 else len(t)]
    else:
        lead = t[:m.start()] if m else t
    lead = lead.strip()
    if not lead or len(lead) > limit or lead.count("(") != lead.count(")") or lead.count("`") % 2:
        return ""
    return lead


def _subject(cell, inp, limit):
    """(a record cell's subject in at most `limit` characters, shortened?): the cell itself when short, else the
    numbered results it names (result_status.mentions), else ("", True)."""
    s, cut = _short(cell, limit)
    if not cut:
        return s, False
    lbls = [" ".join(r[0].split()) for r in inp["index"]
            if _mentions(cell, " ".join(r[0].split()), _names_of(r[1] if len(r) > 1 else ""))]
    j = ", ".join(lbls)
    return (j, True) if j and len(j) <= limit else ("", True)


Key = collections.namedtuple("Key", "group prefix ident short")


def disclosure_keys(cfg, inp=None):
    """[Key(group, prefix, ident, short)] of everything the summary must list or count (U2 §6.4's coverage
    enumerators), in page order: `ident` names the item (its record row, stop, label), `short` is its one line of
    text, never a cut word (a long text gives its first sentence and the place of the full text). Group "Results"
    keys are shown by the results table, group "Decisions" count-only keys (delegated, proxy) by the decisions
    line."""
    inp = _summary_extra(cfg, inp or summary_inputs(cfg))
    sec = report_sections(cfg)
    keys = []
    grp = {p: g for g, ps in PAGE_GROUPS for p in ps}

    def add(prefix, ident, text, full_in=None):
        t, cut = _short(text)
        if cut:
            # conf1 (C1 audit; mini10): nothing short to say left "— (full text in REPORT §5)", a line with no text;
            # the pointer is then the line's text, and the ident (its lead, _lead) says what it is about
            t = (t + f" (full text in {full_in or _where(cfg, prefix, sec)})" if t
                 else f"full text in {full_in or _where(cfg, prefix, sec)}")
        keys.append(Key(grp.get(prefix, "Results"), prefix, " ".join(str(ident).split()), t))
    for row in inp["index"]:
        keys.append(Key("Results", "result", " ".join(row[0].split()), plain_status(result_status(cfg, row, inp))))
    appr = inp.get("approval") or {}
    for lbl, r in (appr.get("rows") or {}).items():
        if (r or {}).get("status") == "excluded":
            keys.append(Key("Results", "excluded", " ".join(str(lbl).split()), "excluded at Checkpoint B"))
    dh, drows = inp["defects"]
    for r in drows:
        st_ = "; ".join(x for x in (_col(dh, r, "status") or _col(dh, r, "severity"), _col(dh, r, "repair")) if x)
        wit = _names_of(_col(dh, r, "lean witness"))
        where, cut = _subject(_col(dh, r, "where"), inp, 70)
        # composed whole (never cut by _short: trial #11's words would push it past SHORT_MAX and lose the status)
        keys.append(Key(grp["defect"], "defect", " ".join(str(r[0]).split()),
            f"{where or 'location in ' + _where(cfg, 'defect', sec)}: {_dot(' '.join(st_.split()))}"
            + _defect_words(dh, r)
            + ("" if wit else " (no Lean witness: confirmed by argument only)")
            # trial #11: a decision taken since the row was written is said, as for a vacuous row
            # conf1 (C1 audit): "decided since (REPORT §5)" said nothing of who decided: say it
            + ("; " + SINCE_SHORT + " (" + _where(cfg, "defect", sec) + ")"
               if decided_since_defect(cfg, r[0]) else "")))
    for k, t in enumerate(inp["slips"], 1):
        s, cut = _short(t, SHORT_MAX - 30)
        lead = re.match(r"\s*\*\*(.{4,90}?)\*\*", t)
        if not s:       # its bold lead (a run: "**Proof of Theorem 7.6, tex l.248–250**, cites ..."), else its results
            s = _dot(lead.group(1)) if lead else _subject(t, inp, 90)[0]
        # C2 audit: counted, a slip read "proof slip (1): 1"; its ident names it as a "Not defects" item's does
        sj = _lead(lead.group(1) if lead else t)
        keys.append(Key(grp["proof slip"], "proof slip", f"{k} ({sj.replace('; ', ', ')})" if sj else str(k),
                        (s + " " if s else "") + "(the result still holds"
                        + (f"; full text in {_where(cfg, 'proof slip', sec)})" if cut else ")")))
    vh, vrows = inp["vacuous"]
    for r in vrows:
        s, cut = _subject(_col(vh, r, "statement"), inp, 80)
        # mini1: a row still reading "open" whose decision was taken since says so
        since = bool(decided_since_text(cfg, "vacuous: " + _col(vh, r, "statement")))
        keys.append(Key(grp["vacuous"], "vacuous", r[0], (s + " " if s else "") + "is true only vacuously"
                        + ("; " + SINCE_SHORT + " since its row was written" if since else "") + " ("
                        + ("full text and decision in " if cut else "decision in ") + _where(cfg, "vacuous", sec) + ")"))
    nd = [t for t in inp["not_defects"] if not _preamble(t, inp)]
    for k, t in enumerate(nd, 1):
        # trial #11: counted, these read "not a defect (+2): 4; 5": the ident says what the item is about. conf1 (C1
        # audit): it named every result the text mentions, even in a parenthesis ("4 (Corollary 7.6 (c))" for "Claims
        # outside numbered environments (..., the equality case of Corollary 7.6(c), ...)"): its lead now, else the
        # results its text names outside parentheses
        subj = _lead(t) or (_subject(re.sub(r"\s*\([^()]*\)", "", t), inp, 40)[0] if len(t) > 40 else "")
        add("not a defect", f"{k} ({subj.replace('; ', ', ')})" if subj else k, t)
    asm = inp["assumptions"]
    for what, how, status in assumption_trust_rows(cfg, asm):
        if what == "Missing theory":
            add("missing theory", how, status)
        else:
            parts = [p for p in str(status).split("; ") if not re.match(r"0 ", p)]
            add("assumptions", "", "; ".join(parts) if parts else "none beyond the paper's definitions")
    for name, kind, src, plain, lean in asm.get("rows") or []:
        nm = str(name).strip("` ")
        add("assumption", nm, f"{kind}; plain English: {plain}; Lean: {lean}")
    for decl, args in inp["unused"]:
        add("unused hypothesis", decl, "; ".join(f"`{a}`" for a in args) + ": no proof term uses it (keep or drop: "
            "DECISIONS.md)")
    for n in asm.get("notes") or []:
        add("assumption note", "", n)
    for d, tag in inp["unproved"].items():
        add("stated only", d, f"stated in the Lean, not proved ({tag})")
    sh, srows = inp["skipped"]
    for r in srows:
        add("not formalized", r[0], f"{_col(sh, r, 'what')}: {_col(sh, r, 'reason')}")
    deh, derows = inp["deviations"]
    for r in derows:
        k = _col(deh, r, "kind").strip("* ").lower()
        res = " ".join((_col(deh, r, "result") or r[0]).split())
        if k == "reading choice":
            add("reading choice", r[0], f"{res}: the Lean reads {_col(deh, r, 'the lean route')}")
        elif k and k != "same strength":
            # trial #11: "proof route 1 — Theorem 7.6: paper step fails" said neither where nor what: the paper's
            # place (its route cell's tex line) and the first clause of why the route differs
            tex = re.search(r"tex l\.[\d\u2013-]+", _col(deh, r, "the paper") or "")
            why = _short(_col(deh, r, "why") or "", 110)[0]
            keys.append(Key(grp["proof route"], "proof route", " ".join(str(r[0]).split()) + f" ({res.replace('; ', ', ')})",
                            (f"{tex.group(0)}: " if tex else "") + f"{k}"
                            + (f" ({_dot(why)}; {_where(cfg, 'proof route', sec)})" if why else
                               f" ({_where(cfg, 'proof route', sec)})")))
    for g, t in inp["globals"]:
        add("global difference", g, t.split(" -- ")[0])
    for s in page_stops(inp["stops"]):
        opn = s["by"] == "nobody yet"
        cmd = re.match(r"(`[^`]*` exited \S+?):", s["what"])
        who = ("OPEN: the run waits for you" if opn else "closed by your answer (below)" if s.get("human")
               else "closed by the operator (delegated)")
        hand = is_hand_delivery(s.get("answer") or "")
        keys.append(Key(grp["stop"], "stop", s["stop"],
                        f"{', '.join(s['classes']) or 'no cause class'}" + (f"; {cmd.group(1)}" if cmd and
                                                                           len(cmd.group(1)) < 90 else "")
                        + f"; {who} ({_where(cfg, 'stop', sec)})"))
        if hand:        # its own line, never counted away (approver: stops and hand deliveries, one line each)
            keys.append(Key(grp["hand delivery"], "hand delivery", s["stop"], "the deliverables were copied by hand, "
                            "not by project.py --deliver, on your answer to this stop"))
    nr = [str(layer).replace("AI reviewer: ", "") for layer, what, status in inp["trust"]
          if str(status).startswith("NOT RUN")]
    if nr:      # one line: the reviewers no round had, so nothing checked what they check
        keys.append(Key(grp["not run"], "not run", "", f"no round of this run had the {', '.join(nr)} reviewer(s): "
                        f"nothing checked what they check (REPORT §{sec['trust']})"))
    for layer, what, status in inp["trust"]:
        if layer == "Record ownership" and status != "no exception":
            add("waiver", layer, status)
    if inp["later"]:
        st_ = str(inp["later"][2])
        n_ = re.match(r"(\d+) commit\(s\)", st_)
        if st_.startswith("none"):
            add("after the last audit round", "", "no Lean change since the last audit round")
        elif not n_:
            add("after the last audit round", "", st_)
        else:
            # composed from the row's facts, short by construction (the commits themselves: the report)
            what = (f"{n_.group(1)} Lean commit(s) change only comments and docstrings (verified mechanically)"
                    if "change ONLY comments" in st_ else
                    f"{n_.group(1)} Lean commit(s) NOT re-audited (checked only by Phase 0)"
                    + ("; shipped as they are: the delivery phase's round cap is reached"
                       if "round cap is reached" in st_ else ""))
            keys.append(Key(grp["after the last audit round"], "after the last audit round", "",
                            what + ("; UNCOMMITTED changes" if "UNCOMMITTED" in st_ else "")
                            + f" (the commits: {_where(cfg, 'not run', sec)})"))
    for r in inp["reapprovals"]:
        add("re-approval", r[0], f"{r[1]}: {r[4]}")
    for f, n, rnd, text in inp.get("superseded") or []:
        add("superseded row", f"{f} row {n}", f"superseded by the adjudication of {rnd}")
    for d in cfg.get("standing_defers") or []:
        add("standing defer", d.get("id", "?"), f"{d.get('item', '')}; revisit when {d.get('revisit_when', '')}")
    if cfg.get("blind_spots"):
        keys.append(Key(grp["blind spots"], "blind spots", "", "what the mechanical checks cannot see: "
                        + _where(cfg, "blind spots", sec)))
    for kind, label, text, words in inp.get("human_answers") or []:
        keys.append(Key(grp[ANSWER_PREFIXES[kind]], ANSWER_PREFIXES[kind], label, _answer_short(cfg, kind, text, words,
                                                                                               label, sec)))
    for rnd, lane, item, why, note in inp["questions"]:
        add("open question", f"{rnd} {lane}", f"`{item}`: " + (f"({note}) " if note else "") + why)
    return keys


def page_stops(rows):
    """The stops the summary page lists (approver, 2026-10-24): every stop but a release self-cure -- open, answered
    by you, or closed by the operator on your behalf (a delegated decision). A self-cure is RUN_RECORD.md's."""
    # a stop closed as not verified (a fault of the checking tools): the page says its consequence in plain words, the
    # stop itself is RUN_RECORD.md's (approver, 2026-10-26)
    return [s for s in rows if not s.get("cured") and not s.get("deferred") and not s.get("core")]


def _preamble(t, inp):
    """True for a "Not defects" bullet that only introduces the others (trial #11: "A limitation of the
    formalization is not a paper defect, and nothing below is one." was printed as "not a defect 1"): it points
    below or above and names no paper result, tex line, Lean name or number."""
    if not re.search(r"\b(?:below|above|following)\b", t, re.I):
        return False
    if re.search(r"tex l\.|`|\d", t):
        return False
    return not any(_mentions(t, " ".join(r[0].split()), _names_of(r[1] if len(r) > 1 else "")) for r in inp["index"])


def _defect_words(dh, r):
    """What a defect line says in words beyond its status (trial #11 audit: a false row's line gave no counterexample):
    a `false` row's counterexample (its "why" cell's `counterexample:` clause), only when short enough to stay
    whole. (The repair is the results table's status; its words are in REPORT section 5: the page has no room.)"""
    out = ""
    st_ = (_col(dh, r, "status") or "").strip().lower()
    if st_.startswith("false"):
        m = re.search(r"counterexample:\s*(.+)", project.full(_col(dh, r, "why") or ""), re.I)
        if m:
            ce = m.group(1)
            ends = [x.start() for x in re.finditer(r"[;.](?=\s|$)", ce)
                    if ce[:x.start()].count("(") == ce[:x.start()].count(")")]
            ce = ce[:ends[0]] if ends else ce
            if 0 < len(ce) <= 120:
                out += f"; counterexample: {ce}"
    return out


# trial #11 audit: the page used terms it never explained (Phase 0, a round's name, a stop's class). The page's
# last line explains each one it uses, in words
CLASS_WORDS = {"document": "a fault in a document",
               "mechanical": "a tool or agent failure, retried",
               "tamper": "an integrity check failed (a record or the apparatus changed outside its owner)",
               "apparatus": "the pinned scripts or settings changed", "presentation": "how a document is worded",
               "proof": "a Lean proof does not build or uses more than it may", "freeze": "an approved statement changed",
               "human": "only the human could answer it", "lane-fault": "a reviewer did not do its task",
               "record-fix": "an adjudicator's record cites what does not exist",
               "settle": "a review finding left unsettled", "unknown": "a failure with no known cause"}
ROUND_NAME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,}\b")


def terms_line(md):
    """The page's glossary line for the terms the lines `md` use and do not explain ("" when none). Phase 0 is
    explained where the header names it."""
    text = "\n".join(md)
    out = []
    if "Phase 0" in text and "Phase 0: the Lean builds" not in text:
        out.append("*Phase 0*: the mechanical check before every round and at delivery (the Lean builds, no "
                   "`sorry`, standard axioms only, approved statements unchanged)")
    if ROUND_NAME_RE.search(text) and "*round*" not in text:
        out.append("*round*: AI reviewers' pass at a Lean commit")
    cls = [c for c in CLASS_WORDS if re.search(rf"stop S\d+ — (?:[\w-]+, )*{re.escape(c)}\b", text)]
    if cls:
        out.append("; ".join(f"*{c}* stop: {CLASS_WORDS[c]}" for c in cls))
    return ("- Terms: " + "; ".join(out) + ".") if out else ""


def _answer_short(cfg, kind, text, words, label, sec):
    """One receipt line: what is recorded as yours (in your words when short), and the audit commit."""
    commit = re.search(r"audit commit (\S+?)(?=[\s);]|$)", text)
    rc = f"audit commit {commit.group(1)}" if commit else ""
    if kind == "stop":
        m = re.search(r'answer, verbatim: "(.*)"\)', text)
        words = m.group(1) if m else words
        rc = rc or _stop_receipt(cfg, label)
    if kind == "approval":
        body = re.sub(r"; recorded in audit commit .*$", "", text)
    else:
        body = f"\u201c{words}\u201d"
    s, cut = _short(body, 320)
    if cut:
        s = (s + "\u201d " if s and kind != "approval" else s + " " if s else "") + \
            f"(full text in {_where(cfg, ANSWER_PREFIXES[kind], sec)})"
    return s + (f" — {rc}" if rc else "")


def _stop_receipt(cfg, label):
    """`audit commit <h>`: the commit that recorded the human's close of the stop in `label` (stops/S<n>/CLOSED.json)."""
    m = re.search(r"\bstop (S\d+)", label)
    if not m:
        return ""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    top, rel = project.rounds_rel(rd, os.path.join("stops", m.group(1), "CLOSED.json"))
    h = subprocess.run(["git", "-C", top, "log", "-1", "--format=%h", "--", rel], capture_output=True,
                       text=True).stdout.strip() if top else ""
    return f"audit commit {h or 'uncommitted'}"


def assumption_trust_rows(cfg, asm):
    """hypotheses.trust_rows of an already computed hypotheses.report (the report's page-1 rows; the summary reads
    the same)."""
    import hypotheses
    return hypotheses.trust_rows(cfg, r=asm)


def result_status_legend():
    import result_status as _rs
    return _rs.STATUS_LEGEND


def _goal_line(cfg, keys):
    goals = [" ".join(str(g).split()) for g in cfg.get("goal_results") or [] if str(g).strip()]
    res = {k.ident: k.short for k in keys if k.prefix == "result"}
    if not goals:
        return "**Goal result:** none named at intake."
    parts = [f"{g}: {res[g]}" if g in res else f"{g}: not in the index (no status)" for g in goals]
    return ("**Goal result" + ("s" if len(goals) > 1 else "") + ":** " + "; ".join(parts) + ".")


def summary_header(cfg, inp, keys):
    dl = inp.get("delegation")
    lvl = project.involvement(cfg)
    appr = inp.get("approval")
    if appr:
        by = project.approval_file_by(os.path.join(inp["rd"], "APPROVED_FINGERPRINTS.json"), appr)[0]
        # forgery review M1: the record shows only that the approval is recorded as the human's
        who = {"human": "you (as recorded: see \"" + ANSWERS_SECTION + "\")",
               "agent": "the agent, NOT a human"}.get(by, "an approver not recorded")
        ap = (f"Statements approved by {who} in round {appr.get('round', '?')} at Lean commit "
              f"{str(appr.get('commit', '?'))[:11]}" + (f"; {len(inp['reapprovals'])} re-approval(s) since"
                                                        if inp["reapprovals"] else "") + ".")
    else:
        ap = "Statements: NOT approved by anyone."
    axioms = [str(r[0]).strip("` ") for r in inp["assumptions"].get("rows") or [] if r[1] == "axiom"]
    cf = core_fault_markers(cfg)
    # C2-FIX 5b (approver 2026-10-26): a check that could not run is never said to have passed: its plain consequence
    # stands on page 1; the Lean-checks sentence is left out when one of those checks is the one that could not run
    rsl = raised_status_lines(cfg)      # SWEEP-FIX D4: a status a corrected tool raised stands on page 1, plainly
    p0 = ("" if core_fault_markers(cfg, ("proof", "axioms", "statement")) else
          " Phase 0: the Lean builds, with no sorry outside the results marked stated only and no axiom beyond "
          "propext, Classical.choice and Quot.sound"
          + (f" except the declared {', '.join(f'`{a}`' for a in axioms)}" if axioms else "") + ".")
    return [f"# Summary — {cfg['source_cite']}", "",
            _goal_line(cfg, keys), ""] + [f"**{m}**" for m in cf] + ([""] if cf else []) + [
            f"**{l_}**" for l_ in rsl] + ([""] if rsl else []) + [
            f"Lean: commit `{delivered_commit(cfg)}` (the last commit that changed the Lean), branch "
            f"`{cfg.get('branch', '?')}`, repository `{REPO}`. Run mode: {project.mode(cfg)}. Involvement: {lvl}"
            + (f" (intake answer: \"{dl[1]}\")" if dl and dl[1] else "") + f". {ap}{p0}"]

# Approver (2026-10-26): the plain trust lines code writes on SUMMARY page 1 and in REPORT are judged by an agent, the
# status check (run_record.status_items, readers.trust_problems). THE HOOK: TRUST_LINE_PROVIDERS, a list of functions
# provider(cfg) -> [TrustEvent]; each event names its id ("TL-<kind>-<key>", stable across prepares), what kind of
# event it is, the plain line the generator writes for it (on SUMMARY page 1 and in REPORT), and where RUN_RECORD.md
# records the event. Another kind of line (a status decided by corrected software, ...) appends its provider here
TrustEvent = collections.namedtuple("TrustEvent", "id kind line record affects")


def raised_status_lines(cfg):
    """SWEEP-FIX D4: the plain lines "<result>: this status was decided by a corrected version of our checking software; ..." (one per result
    whose status a tool patch made stronger than the FIRST pin's result_status.py gives it; tool_patch.raised_lines),
    or the one line saying the comparison could not run. SUMMARY page 1 and REPORT section 1 carry each; --deliver
    (tool_patch.verify_delivery, the first pin's copy) refuses a document without it."""
    import tool_patch
    try:
        return tool_patch.raised_lines(cfg)
    except Exception:       # noqa: BLE001 -- never silent: the comparison is said not to have run
        return [tool_patch.STATUS_UNCOMPARED]



def core_fault_events(cfg):
    """[TrustEvent] of every stop closed as not verified (stops.py close --core-fault), each with what it weakens."""
    import stops, run_record
    out = []
    for c in stops.core_fault_rows(cfg):
        g, _t, short = stops.core_guarantee(c)
        aff = (f"every result's status reads \"{short}\"; the report's Lean-kernel row says it"
               + ("; the report's Approval of statements row says it" if g == "statement" else "")
               if short else
               "no result's status changes (the proofs and statements were checked); the legend says *faithful* rests "
               "on reviewer records not verified; the report's rows Approval of statements, AI reviewer(s) and Record "
               "provenance, and the summary's section Answers recorded as yours, say it")
        out.append(TrustEvent(f"TL-not-verified-{c.get('stop')}", "a check of the proofs, the statements or the record "
                              "could not be run", stops.core_fault_marker(c),
                              f"RUN_RECORD.md: stop {c.get('stop')} (\"{run_record.STOPS_TITLE}\") and the requests to "
                              f"close a stop as not verified", aff))
    return out


STATUS_UNCOMPARED_FALLBACK = ("Our checking software was corrected during this run, and the statuses could not be "
                              "compared with what the original version would have said. Details for maintainers: "
                              "RUN_RECORD.md.")


def raised_status_events(cfg):
    """[TrustEvent] of every status a corrected version of the checking software raised (SWEEP-FIX D4: code flags it
    from the first pin's result_status.py; the status check judges the line against RUN_RECORD.md)."""
    import tool_patch
    unc = [TrustEvent("TL-raised-uncompared", "statuses not compared with the original checking software",
                      getattr(tool_patch, "STATUS_UNCOMPARED", STATUS_UNCOMPARED_FALLBACK),
                      "RUN_RECORD.md: \"Tool patches\", \"Statuses raised by tool patches\"",
                      "any result's status may be stronger than the original software would have given; the sentence "
                      "stands on the summary's first lines and in the report's section 1")]
    try:
        # SWEEP-FIX review B2: every call inside the guard; a crash fails closed (the not-compared line is then
        # required on the documents and judged by the status check), never a crash of the status check or run_record
        patched = bool(tool_patch.links(project.AUDITS, os.path.join(REPO, cfg["rounds_dir"])))
        recs = tool_patch.raised_statuses(cfg) if patched else []
    except Exception:       # noqa: BLE001 -- the comparison is said not to have run
        return unc
    if recs is None:
        return unc
    return [TrustEvent(f"TL-raised-{re.sub(r'[^A-Za-z0-9.]+', '_', lb)}", "a status decided by a corrected version of "
                       "the checking software", tool_patch.RAISED.format(label=lb, tp=tp, old=old),
                       f"RUN_RECORD.md: \"Tool patches\", \"Statuses raised by tool patches\" ({tp})",
                       f"the status of {lb} only (the shown status is the corrected software's; the original one is "
                       f"quoted); the sentence stands on the summary's first lines and in the report's section 1")
            for lb, tp, old in recs]




def weakened_events(cfg):
    """[TrustEvent] of the report's "Checks weakened" row (weakened_row): a correction of the checking software, a
    hand delivery."""
    out = []
    if tools_patched(cfg):
        out.append(TrustEvent("TL-software-corrected", "the checking software was corrected during the run",
                              TOOLS_PATCHED, "RUN_RECORD.md section 1 (tool patches)",
                              "the report's row Checks weakened says it; a corrected tool may change result statuses "
                              "-- the lines that name a status set by corrected software say which results"))
    if hand_delivered(cfg):
        out.append(TrustEvent("TL-hand-delivered", "the run was delivered by hand", HAND_DELIVERY,
                              "RUN_RECORD.md: the stop whose answer says so", "no result's status; the report's row "
                              "Checks weakened says it"))
    return out


TRUST_LINE_PROVIDERS = [core_fault_events, weakened_events, raised_status_events]   # per-result lines: SWEEP-FIX D4
# review 3 (fail-safe coverage, code flags): every plain trust sentence a generator writes is one of these kinds; each
# one SUMMARY.md or REPORT.md carries must be some event's line (readers.trust_problems), so a kind whose provider is
# missing refuses delivery. THE SECOND HOOK: a new kind of trust sentence appends its pattern here and its provider to
# TRUST_LINE_PROVIDERS
TRUST_SENTENCE_RES = [re.compile(r"Not verified: [^\n]*?\(details for maintainers in RUN_RECORD\.md\)\."),
                      re.compile(re.escape(TOOLS_PATCHED)), re.compile(re.escape(HAND_DELIVERY)),
                      # SWEEP-FIX D4: a status decided by corrected software (one per result, as SUMMARY writes it in
                      # bold and REPORT as a list item), and the line saying the statuses could not be compared
                      re.compile(r"(?m)(?:(?<=^- )|(?<=\*\*))[^\n*]+?: this status was decided by a corrected version "
                                 r"of our checking software; the original version would have said \"[^\n]*?\"\. Details "
                                 r"for maintainers: RUN_RECORD\.md\."),
                      re.compile(r"Our checking software was corrected during this run, and the statuses could not be "
                                 r"compared[^\n]*?RUN_RECORD\.md\.")]


def trust_line_events(cfg):
    """[TrustEvent] of every provider in TRUST_LINE_PROVIDERS, in order."""
    return [e for prov in TRUST_LINE_PROVIDERS for e in prov(cfg)]


def trust_sentences(text):
    """[sentence] of the plain trust kinds (TRUST_SENTENCE_RES) in a generated document's text, each once."""
    return list(dict.fromkeys(m.group(0) for rx in TRUST_SENTENCE_RES for m in rx.finditer(text or "")))


def trust_line_summary(cfg):
    """The status check's <TRUST-LINES>: each event, its kind, the line the generator wrote for it, what it weakens
    (affects: the specification the agent judges against) and where RUN_RECORD.md records it; "none"."""
    ev = trust_line_events(cfg)
    return "none" if not ev else "; ".join(f"{e.id} ({e.kind}; the line: \"{e.line}\"; what it weakens: {e.affects}; "
                                           f"recorded in {e.record})" for e in ev)


# review 3: the reviewers' verdicts are authenticated at delivery by the integrity check; when it (or the tool-patch
# check) could not run, "faithful" rests on records that were not verified then -- said once, plainly
RECORD_LEGEND = (" *faithful* here rests on the AI reviewers' records, which could not be verified automatically at "
                 "delivery (see the first lines of this page).")


def core_fault_markers(cfg, guarantees=None):
    """[plain marker] of every stop closed as not verified (stops.py close --core-fault: a check of the proofs, the
    statements or the record could not run), once each; `guarantees`: only those of these guarantees ("proof",
    "axioms", "statement", "record"; stops.CORE_GUARANTEES). C2-FIX 5b; approver 2026-10-26: plain words only."""
    import stops
    return list(dict.fromkeys(stops.core_fault_marker(c) for c in stops.core_fault_rows(cfg)
                              if guarantees is None or stops.core_guarantee(c)[0] in guarantees))


def _decisions_line(cfg, inp):
    m = inp.get("matters")
    lvl = project.involvement(cfg)
    q = len(inp["questions"])
    dl = inp.get("delegation")
    txt = (f"- Decisions: {m} matter(s), each with who decided it and what reversing it costs, in DECISIONS.md "
           f"(appendix B)" if isinstance(m, int) else f"- Decisions: the matters in DECISIONS.md (appendix B) were {m}")
    if dl and dl[2] is not None and inp.get("n_delegated"):
        txt += f"; decided on your behalf under {lvl}: {inp['n_delegated']} logged decision(s) on them"
    if inp.get("proxies"):
        txt += f"; {inp['proxies']} answered by a proxy ([PROXY])"
    return txt + (f"; {q} question(s) still open (listed above)." if q else "; no question is open.")


# The advisory citation review (run/stage5-delivery.md step 5a): two agents write CITATIONS.md in the rounds
# directory after the final audit round, before the prepare; nothing checks its content. The summary carries one
# line on it: its number of items (each a `### ` heading), or why it was not produced (the operator's RUN_LOG.md
# line `- citation notes not produced: <reason>`). Neither present (a run from before the review): no line.
CITATIONS_MD = "CITATIONS.md"
CITATIONS_NOT_PRODUCED = re.compile(r"^- citation notes not produced: (.+?)\s*$", re.M)


def citation_line(rd):
    """The summary's one line on CITATIONS.md, or None."""
    p = os.path.join(rd, CITATIONS_MD)
    if os.path.isfile(p) and not os.path.islink(p):
        n = len(re.findall(r"^### ", open(p, encoding="utf-8", errors="replace").read(), re.M))
        return f"- Citation notes: {n} item{'' if n == 1 else 's'} — see CITATIONS.md (advisory, for the authors to check)."
    log = os.path.join(rd, "RUN_LOG.md")
    why = CITATIONS_NOT_PRODUCED.findall(open(log, encoding="utf-8").read()) if os.path.isfile(log) else []
    return f"- Citation notes: not produced: {_dot(why[-1])}." if why else None


def _shown_ident(k):
    """The ident a listed line shows: a proof slip's "<n> (<lead>)" (its name when counted, C2 audit) is "<n>" when
    the line's text starts with that lead anyway (no word said twice, no room taken from other lines)."""
    m = re.fullmatch(r"(\d+) \((.+)\)", k.ident or "") if k.prefix == "proof slip" else None
    return m.group(1) if m and k.short.startswith(m.group(2)) else k.ident


def _line(k):
    i = _shown_ident(k)
    return f"- {k.prefix} {i} — {k.short}" if i else f"- {k.prefix} — {k.short}"


def _counted(cfg, prefix, ks, sec, more):
    return (f"- {prefix} ({'+' if more else ''}{len(ks)}): " + "; ".join(k.ident or "-" for k in ks)
            + f" — full text in {_where(cfg, prefix, sec)}")


COUNTED_RE = re.compile(r"^- (.+?) \(\+?(\d+)\): (.*?) — full text in ")


def _cost(line, cpl=CPL):
    """Rendered lines of one line of the page (an estimate, calibrated on the snapshots; generous)."""
    t = re.sub(r"\*\*|`|\*", "", line)
    return max(1, -(-len(t) // cpl))


def _table(rows):
    out = ["| Status | Results |", "|---|---|"]
    out += [f"| {st} | {'; '.join(lbls)} |" for st, lbls in rows]
    return out


def summary_page(cfg, inp=None):
    """[md line] of the one-page summary: the header, the results table, each group's lines (listed while the page
    has room, else counted with the place of their full text), the decisions line and the appendices."""
    inp = _summary_extra(cfg, inp or summary_inputs(cfg))
    keys = disclosure_keys(cfg, inp)
    sec = report_sections(cfg)
    head = summary_header(cfg, inp, keys)
    groups = collections.OrderedDict()
    for st, lbl in ((k.short, k.ident) for k in keys if k.prefix == "result"):
        groups.setdefault(st, []).append(lbl)
    exc = [k.ident for k in keys if k.prefix == "excluded" and not any(k.ident in v for v in groups.values())]
    if exc:
        groups.setdefault("excluded at Checkpoint B", []).extend(exc)
    # faithful first, then by first appearance
    rows = sorted(groups.items(), key=lambda kv: kv[0] != "faithful")
    table = _table(rows)
    cit = citation_line(inp["rd"])
    tail = ["", _decisions_line(cfg, inp)] + ([cit] if cit else []) + [
            "- Appendices: A the report (REPORT.pdf, REPORT.md: every check and record in full), B DECISIONS.md, C the "
            "sheet of the latest approval (SIGNOFF.pdf, SIGNOFF.md" + (f"; round {(inp.get('approval') or {}).get('round')}"
                                                                      if (inp.get("approval") or {}).get("round") else "")
            + "), D the run record (RUN_RECORD.md: how the run went -- self-cured stops, set-asides, process events, "
            "known presentation faults).", "", "- " + PDF_LINE]
    by = {g: [k for k in keys if k.group == g] for g, _ in PAGE_GROUPS}
    shown = {p: sum(1 for k in keys if k.prefix == p) for _, ps in PAGE_GROUPS for p in ps}

    def render():
        cf_ = core_fault_markers(cfg, ("proof", "axioms", "statement"))
        rec_ = core_fault_markers(cfg, ("record",))
        out = list(head) + ["", "## Results", ""] + table + ["", SUMMARY_LEGEND + (
            " *not verified: ...*: a check behind that status could not be run (the first lines of this page say which)."
            if cf_ else "") + (RECORD_LEGEND if rec_ else "")]
        for g, ps in PAGE_GROUPS:
            ls = []
            for p in ps:
                ks = [k for k in by[g] if k.prefix == p]
                ls += [_line(k) for k in ks[:shown[p]]]
                if len(ks) > shown[p]:
                    ls.append(_counted(cfg, p, ks[shown[p]:], sec, shown[p] > 0))
            if g == ANSWERS_SECTION and not ls:
                continue
            if g == "Decisions":
                out += ["", "## Decisions", ""] + ls + tail[1:]
                continue
            rm_ = core_fault_markers(cfg, ("record",)) if g == ANSWERS_SECTION else []
            out += ["", f"## {g}", ""] + ([" ".join(rm_ + [ANSWERS_INTRO]), ""] if g == ANSWERS_SECTION else []) \
                + (ls or ["- none"])
        return out

    def cost(md):
        n, in_table = 0, False
        for l in md:
            if l.startswith("|"):
                if l.startswith("|---") or l.startswith("| Status |"):
                    continue
                c = l.strip("|").split(" | ", 1)
                n += _cost(c[0] + ": " + c[-1])
            elif l.startswith("## "):
                n += 2
            elif l.startswith("# "):
                n += _cost(l, 70)
            elif l.strip():
                n += _cost(l)
        return n
    base_render = render

    def render():       # the glossary line, last, explains the terms the page uses
        out = base_render()
        tl = terms_line(out)
        return out + ([tl] if tl else [])
    md = render()
    for p in COLLAPSE_LOW + COLLAPSE_ANSWERS:
        while cost(md) > PAGE_LINES and shown.get(p, 0) > 0:
            shown[p] -= 1
            md = render()
    while cost(md) > PAGE_LINES and any(shown.get(p, 0) for p in COLLAPSE_EVEN):
        p = max(COLLAPSE_EVEN, key=lambda q: (shown.get(q, 0), -COLLAPSE_EVEN.index(q)))
        shown[p] -= 1
        md = render()
    return md


def summary_md(cfg, inp=None):
    """SUMMARY.md: the one-page summary (summary_page)."""
    return "\n".join(summary_page(cfg, inp)) + "\n"


def _table_rows_of(text):
    """{label: status} and [label] (every occurrence) of the summary's results table."""
    st, seen = {}, []
    sec_ = text.split("\n## Results", 1)[-1].split("\n## ", 1)[0]
    for l in sec_.splitlines():
        if not l.startswith("| ") or l.startswith("| Status |") or l.startswith("|---"):
            continue
        cells = [c.strip() for c in l.strip().strip("|").split(" | ")]
        if len(cells) != 2:
            continue
        for lbl in cells[1].split("; "):
            lbl = " ".join(lbl.split())
            seen.append(lbl)
            st[lbl] = cells[0]
    return st, seen


# conf1 (C1 audit, defect 1): generated lines that stopped mid-phrase ("...; decided since (REPORT §5)", a decision
# cell cut to "md row 1; ..."). A maintainers' check (selftest, snapshot regeneration), never a run's gate: a line or
# table cell ends mid-phrase when, once its trailing pointers in parentheses and a full stop are taken off, it ends in
# "since", "the", "of", "to", "and", "or", "with", "from", a dash, a colon, a semicolon or a comma ("a" is left out:
# it is a variable as often as an article)
DANGLING_RE = re.compile(r"(?:\bsince|\bthe|\bof|\bto|\band|\bor|\bwith|\bfrom|—|--|:|;|,)$", re.I)


def dangling_lines(md):
    """[line or table cell of the generated markdown `md` that ends mid-phrase] (DANGLING_RE). Exempt: headings, code
    blocks, a table's header row, a line that a non-blank line continues (a record's paragraph quoted with its line
    breaks), a line that introduces a list or a table, and a colon whose object is the parenthesis after it
    ("`P.lem`: (h : 0 < n)")."""
    out, lines, code = [], md.splitlines(), False
    for i, l in enumerate(lines):
        if l.lstrip().startswith("```"):
            code = not code
            continue
        nl = lines[i + 1] if i + 1 < len(lines) else ""
        if code or not l.strip() or l.lstrip().startswith("#") or re.match(r"\s*\|[-:| ]+\|\s*$", l) \
                or re.match(r"\s*\|[-:| ]+\|\s*$", nl):
            continue        # a table's header row is labels
        table = l.lstrip().startswith("|")
        nq = re.sub(r"^\s*(?:>\s*)+", "", nl)
        if not table and nq.strip() and not re.match(r"\s*(?:[-*+]\s|\||\d+\.\s|#|>)", nl):
            continue        # the paragraph goes on in the next line
        cells = l.strip().strip("|").split(" | ") if table else [l]
        for c in cells:
            t, cut = c.strip(), False
            while True:
                t2 = re.sub(r"\s*\([^()]*\)$", "", t).rstrip(" .")
                if t2 == t:
                    break
                t, cut = t2, True
            if not t or (cut and t.endswith(":")):
                continue
            if t.endswith(":") and not table:
                nxt = next((re.sub(r"^\s*(?:>\s*)+", "", x) for x in lines[i + 1:] if re.sub(r"^\s*(?:>\s*)+", "", x).strip()), "")
                if re.match(r"\s*(?:[-*+]\s|\||\d+\.\s|\s{2,})", nxt):
                    continue    # a list's or a table's lead-in
            if DANGLING_RE.search(t):
                out.append(c.strip())
    return out


def summary_problems(cfg, text=None, inp=None, hand_edited=False):
    """[Finding(deliver)] of the delivered SUMMARY.md against a fresh enumeration (U2 §6.4 coverage, §1
    independent check): every result in the table once, with its status as the record gives it; every other item
    of the record (defect, proof slip, vacuous statement, assumption, stop, answer, ...) either listed on its line,
    whole and as generated, or counted on its kind's line by its name (never dropped, never listed twice); the goal
    and decisions lines as the record gives them; no result a status-bearing record names reading plain
    (faithful), none with a reading-choice row reading plain faithful. `hand_edited` (DOC-FIX: the summary carries
    recorded hand edits): a result's status word and an item line's text may differ from the generator's -- the
    status check, a fresh agent, judges each edit (readers.judgement_problems) -- but every result and item must
    still be there, once."""
    import collections as _c, decisions
    p = os.path.join(REPO, cfg["rounds_dir"], SUMMARY_MD)
    if text is None:
        try:
            text = open(p, encoding="utf-8").read()
        except OSError:
            return [project.Finding(f"{SUMMARY_MD} is missing: python3 audits/project.py --prepare-delivery", "deliver")]
    inp = _summary_extra(cfg, inp or summary_inputs(cfg))
    keys = disclosure_keys(cfg, inp)
    lines = [" ".join(l.split()) for l in text.splitlines() if l.startswith("- ")]
    out = []
    st, seen = _table_rows_of(text)
    for k in keys:
        if k.prefix not in ("result", "excluded"):
            continue
        n = seen.count(k.ident)
        if n != 1:
            out.append(f"{SUMMARY_MD}'s results table has {k.prefix} {k.ident} {n} time(s), the record once")
        elif k.prefix == "result" and st[k.ident] != k.short and not hand_edited:
            out.append(f"{SUMMARY_MD}'s results table gives {k.ident} the status \"{st[k.ident]}\", the record "
                       f"\"{k.short}\"")
    for lbl in set(seen) - {k.ident for k in keys if k.prefix in ("result", "excluded")}:
        out.append(f"{SUMMARY_MD}'s results table lists {lbl}, which the index does not hold")
    counted = _c.defaultdict(list)
    for l in lines:
        m = COUNTED_RE.match(l)
        if m:
            ids = [] if not m.group(3) else m.group(3).split("; ")
            if int(m.group(2)) != len(ids):
                out.append(f"{SUMMARY_MD} counts {m.group(2)} {m.group(1)} but names {len(ids)}")
            counted[m.group(1)] += ["" if i == "-" else i for i in ids]
    itemized = [k for k in keys if k.group not in ("Results",)]
    for prefix in dict.fromkeys(k.prefix for k in itemized):
        ks = [k for k in itemized if k.prefix == prefix]
        want = _c.Counter(k.ident for k in ks)
        lst = _c.Counter()
        for k in dict.fromkeys(ks):
            lst[k.ident] += sum(1 for l in lines if l == " ".join(_line(k).split()))
        heads = _c.Counter()
        shown_ = {k.ident: _shown_ident(k) for k in ks}
        for l in lines:
            for i in want:
                h = f"- {prefix} {shown_[i]} — " if shown_[i] else f"- {prefix} — "
                if l.startswith(h):
                    heads[i] += 1
        for i in want:
            have = (max(lst[i], heads[i]) if hand_edited else lst[i]) + counted[prefix].count(i)
            if heads[i] > lst[i] and not hand_edited:
                out.append(f"{SUMMARY_MD} has the line of {prefix} {i} changed or cut short (not as the record "
                           "gives it)")
            elif have < want[i]:
                out.append(f"{SUMMARY_MD} neither lists nor counts {prefix} {i}" if i else
                           f"{SUMMARY_MD} lacks the line of {prefix}")
            elif have > want[i]:
                out.append(f"{SUMMARY_MD} has {prefix} {i} {have} time(s), the record {want[i]}")
        for i in set(counted[prefix]) - set(want):
            out.append(f"{SUMMARY_MD} counts {prefix} {i or '-'}, which the record does not hold")
    for prefix in set(counted) - {k.prefix for k in itemized}:
        out.append(f"{SUMMARY_MD} counts {prefix}, a kind the record does not hold")
    # a listed line the record does not hold (its kind: the longest prefix it starts with)
    allp = sorted({p_ for _, ps in PAGE_GROUPS for p_ in ps}, key=len, reverse=True)
    want_all = {(k.prefix, _shown_ident(k)) for k in itemized}
    for l in lines:
        if COUNTED_RE.match(l):
            continue
        p_ = next((q for q in allp if l.startswith(f"- {q} ")), None)
        if p_ is None:
            continue
        i_ = l[len(f"- {p_} "):].split(" — ", 1)[0] if not l.startswith(f"- {p_} — ") else ""
        if (p_, i_) not in want_all:
            out.append(f"{SUMMARY_MD} lists {p_} {i_}, which the record does not hold")
    # an independent count from the raw records (decisions' parsers, stops.py; not the summary's inputs): every
    # defect row, proof slip, vacuous row and stop is listed or counted
    rd_ = os.path.join(REPO, cfg["rounds_dir"])
    try:
        import stops as _stops
        vt = decisions.table_rows(decisions._read(os.path.join(rd_, "VACUOUS.md")))
        raw = {("defect",): sum(1 for h, c in decisions.defect_rows(rd_) if decisions.is_defect_header(h)),
               ("vacuous",): sum(1 for h, c in vt if decisions._idx(h, "statement") is not None),
               ("proof slip",): len(decisions.slip_rows(rd_)),
               ("stop",): len(page_stops(_stops.stop_rows(cfg, phase="run")))}
    except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
        raw = {}
        out.append(f"the record's defects, slips, vacuous rows and stops could not be counted: {e}")
    allp = {p_ for _, ps in PAGE_GROUPS for p_ in ps}
    kind = lambda l, p_: l.startswith(f"- {p_} ") and not any(l.startswith(f"- {q} ") for q in allp
                                                              if q != p_ and q.startswith(p_ + " "))
    for prefs, n in raw.items():
        on = (sum(1 for l in lines if not COUNTED_RE.match(l) and any(kind(l, p_) for p_ in prefs))
              + sum(len(counted[p_]) for p_ in prefs))
        if on != n:
            out.append(f"{SUMMARY_MD} shows {on} {prefs[0]}(s), listed or counted; the record holds {n}")
    gl = _goal_line(cfg, keys)
    if gl not in text.splitlines():
        out.append(f"{SUMMARY_MD} lacks the goal line as the record gives it ({gl})")
    dl = " ".join(_decisions_line(cfg, inp).split())
    if dl not in lines:
        out.append(f"{SUMMARY_MD} lacks the decisions line as the record gives it ({dl})")
    # the §1 independent check, from another enumerator: the subject cells of the raw records (decisions'
    # parser), never the summary's own inputs. A result one of them names must not read plain
    rd = os.path.join(REPO, cfg["rounds_dir"])
    subjects = []
    try:
        subjects += [("defect", decisions._col(h, c, "where")) for h, c in decisions.defect_rows(rd)
                     if decisions.is_defect_header(h)]
        for f, col in (("SKIPPED.md", "what"), ("VACUOUS.md", "statement")):
            subjects += [(f, c[decisions._idx(h, col)]) for h, c in decisions.table_rows(decisions._read(os.path.join(rd, f)))
                         if decisions._idx(h, col) is not None and len(c) > decisions._idx(h, col)]
        subjects += [("stated only", f"`{d}`") for d in decisions.unproved(cfg)["decls"]]
    except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
        out.append(f"the disclosures could not be enumerated: {e}")
    deh, derows = inp["deviations"]
    reading = [(_col(deh, r, "result") or r[0]) for r in derows
               if _col(deh, r, "kind").strip("* ").lower() == "reading choice"]
    for row in inp["index"]:
        lbl = " ".join(row[0].split())
        names = _names_of(row[1] if len(row) > 1 else "")
        plain = st.get(lbl) == "faithful"
        named = [f"{k}: {t}" for k, t in subjects if _mentions(t, lbl, names)]
        if plain and named:
            out.append(f"{lbl} reads plain (faithful) although a record names it: {project.clip(named[0], 120)}")
        if plain and any(_mentions(x, lbl, names) for x in reading):
            out.append(f"{lbl} reads plain faithful although a reading choice concerns it")
    return [project.Finding(x, "deliver") for x in out]


def build_summary(cfg, quiet=False):
    """Write SUMMARY.md (its PDF is made afterwards by agents: render_record.py). Returns [] (kept a list for its
    callers)."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    md = summary_md(cfg)
    if REFERENCE is not None:
        REFERENCE.append({"doc": "SUMMARY", "md": md})
        return []
    project.write_draft(rd, SUMMARY_MD, md)     # facts/; the agent's SUMMARY.md never overwritten (review 2026-10-28)
    return []


# The generator in memory (formerly render_fix.reference; PDF-AGENTS): with REFERENCE a list, build() and
# build_summary() append what they would write and write nothing; REFERENCE_STAMP keeps the date of the REPORT.md
# on disk, so a report regenerated in memory on another day hashes the same (its stamp is not hashed either).
REFERENCE = None
REFERENCE_STAMP = None


def report_md(cfg):
    """REPORT.md as the generator writes it NOW, computed in memory (nothing written), dated as the REPORT.md on
    disk; None when the generator cannot run (delivery_problems then refuses, fail closed)."""
    global REFERENCE, REFERENCE_STAMP
    import contextlib, io
    try:
        m = re.search(r"\*\*Generated (\d{4}-\d{2}-\d{2}) by",
                      open(os.path.join(REPO, cfg["rounds_dir"], project.FACTS_DIR, "REPORT.md"), encoding="utf-8").read())
    except OSError:
        m = None
    REFERENCE, REFERENCE_STAMP = [], (m.group(1) if m else None)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            build(cfg)
        return next((r["md"] for r in REFERENCE if r.get("doc") == "REPORT"), None)
    except Exception:       # noqa: BLE001 -- no reference: the caller refuses
        return None
    finally:
        REFERENCE, REFERENCE_STAMP = None, None


# --- make_report.py --check --delivery (B10; U2 §6.4 item 1) ---------------------------------------------
def unverified_problems(cfg, inp=None):
    """[text] when the verdicts are not current (code `unverified`): something is approved and no full-scope
    proof round (prompt.py 3 --full) came after the approved round; and B9's per-result rule (U2 §1 routing): a
    result whose verdict is missing or out of date (result_status.routes, route `unverified`)."""
    import result_status as _rs
    rd = os.path.join(REPO, cfg["rounds_dir"])
    per = [f"{r.result}: {r.reason}: run a full round (prompt.py 3 --full, Stage 5 step 1)"
           for r in _rs.routes(cfg, inp) if r.code == "unverified"]
    try:
        appr = json.load(open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"))).get("round")
    except (OSError, ValueError, AttributeError):
        return per
    names = [os.path.basename(r) for r in project.rounds(cfg)]
    after = names[names.index(appr) + 1:] if appr in names else names
    if not any(project.is_full_round(n) and project.round_kind(os.path.join(rd, n)) not in ("statements", None)
               for n in after):
        return [f"no full-scope round since the approved round {appr}: the verdicts are not current (run prompt.py 3 "
                f"--full, Stage 5 step 1)"] + per
    return per


def stale_problems(cfg):
    """[text] when a Lean commit came after the last audited round (code `deliver-stale`; U2 §6.4): commits that
    touch only the audit record never count; a change that is mechanically comment-only (project.py
    --comment-only) does not either (Stage 5 step 1)."""
    c = project.changes_after_last_audit(cfg, project.rounds(cfg))
    if c is None:
        return []
    if c["problem"]:
        return [c["problem"]]
    out = []
    # integrated review fix 1: once the delivery phase's round cap is reached, the commits ship unaudited and
    # disclosed (later_row, the summary, the decisions item); asking for a round per change never ended
    cap = project.delivery_cap(cfg)
    if c["commits"] and not c.get("comment_only") and not cap:
        final, after = project.delivery_rounds(cfg)
        left = (f" (round {len(after) + 1} of at most {project.DELIVERY_ROUND_CAP} after the final full round "
                f"{final}; past them a Lean change ships disclosed, never re-audited)") if final else ""
        out.append(f"{len(c['commits'])} Lean commit(s) after the last audited round {c['round']} ({c['commit']}): "
                   + "; ".join(c["commits"]) + ": run a diff round on them (prompt.py 3)" + left + "; if its scope is "
                   "empty (scope.py exits 3: the commits changed no declaration a lane reviews), a full round "
                   "(prompt.py 3 --full)")
    if c["dirty"]:
        out.append("uncommitted changes to " + ", ".join(c["dirty"]) + (
            ": commit them (the delivery-phase round cap is reached: they ship disclosed, with no round)" if cap
            else ": commit them and run a diff round"))
    return out


def delivery_problems(cfg, inp=None):
    """[(code, text)]: what --deliver reports (approver 2026-10-28: `deliver-stale` is the math gate's and refuses;
    every other code is a NOTE for the main agent, never a refusal and never a stop). The prepared documents: DELIVERY.json exists; the generator writes now exactly what
    prepare recorded and what is on disk (SUMMARY, REPORT and README A-C recomputed in memory; DECISIONS and the
    sheet by their recorded hash). The PDFs are not checked here: --deliver's render guard does (render_record.py,
    a fingerprint). Their readers: every gated
    document has a pass on its current version with every finding answered, every single-pass document exactly
    one; the hands-off sheet none. Coverage and the §1 check (summary_problems). No `unverified`, no
    `deliver-stale`, no pending adjudication item. Every code but adj-record/dead-witness/record-cite is a delivery
    code: a RED precondition, never a stop (ADDENDUM N1)."""
    import decisions, readers, stops
    rd = os.path.join(REPO, cfg["rounds_dir"])
    out = []
    man = project.manifest(cfg)
    if man is None:
        return ([("deliver", f"no {project.DELIVERY_RECORD}: run python3 audits/project.py --prepare-delivery")]
                + [("deliver-stale", t) for t in stale_problems(cfg)])
    docs = project._prepared_docs(cfg)
    rec = man.get("hashes") or {}
    now = {}
    try:
        inp = inp or summary_inputs(cfg)
        now["SUMMARY.md"] = project.doc_text_hash("SUMMARY.md", summary_md(cfg, inp))
    except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
        out.append(("deliver", f"the summary could not be generated: {e!r}"))
    rep_md = report_md(cfg)
    if rep_md is not None:
        now["REPORT.md"] = project.doc_text_hash("REPORT.md", rep_md)
    else:
        out.append(("deliver", "the report could not be generated in memory: run python3 audits/project.py "
                               "--prepare-delivery and read its output"))
    now[project.README_AC] = project.doc_text_hash(project.README_AC, project.readme_ac(cfg))
    try:        # the run record (approver 2026-10-24): recomputed as the other prepared documents are
        import run_record
        now[project.RUN_RECORD] = project.doc_text_hash(project.RUN_RECORD, run_record.text(cfg))
    except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
        out.append(("deliver", f"the run record could not be generated: {e!r}"))
    for name, path in docs.items():
        # approver (2026-10-28): SUMMARY, REPORT and RUN_RECORD are the main agent's; prepare recorded the generator's
        # facts draft of each (project.FACTS_DIR), which is what is compared here: a stale draft is a note
        disk = project.file_hash(name, path)
        draft = "the facts draft of " if name in project.AGENT_DOCS else ""
        if disk is None:
            out.append(("deliver", f"{draft}{name} is missing: run python3 audits/project.py --prepare-delivery"))
        elif name not in rec:
            out.append(("deliver", f"{draft}{name} was not recorded by the last prepare: run it again"))
        elif disk != rec[name]:
            out.append(("deliver", f"{draft}{name} changed after prepare"))
        elif name in now and now[name] != disk:
            out.append(("deliver", f"{draft}{name} is stale: its inputs changed since prepare (a record, a stop, an "
                                   f"answer or a Lean commit): prepare again"
                                   + (" and check that your document still says what the records say" if draft else "")))
    if man.get("lean_commit") and man["lean_commit"] != delivered_commit(cfg, short=False):
        out.append(("deliver", f"the Lean changed since prepare ({str(man['lean_commit'])[:11]} then, "
                               f"{delivered_commit(cfg)} now): prepare again"))
    ar = project.approved_round(cfg)
    # the readers (U2 §6.3): approver (2026-10-28), SUMMARY, REPORT and DECISIONS have the delivery reviewers instead
    # (run/stage5-delivery.md); the approved sheet keeps its reader
    gates = []
    if ar and project.involvement(cfg) != "hands-off":
        gates.append(("signoff", "approved"))
    for doc, rnd in gates:
        try:
            ps = readers.check(cfg, doc, rnd)
        except Exception as e:      # noqa: BLE001 -- fail closed
            ps = [f"the reader records could not be read: {e!r}"]
        out += [("deliver", f"reader gate {doc}: {' '.join(str(p_).split())}") for p_ in ps]
    # approver (2026-10-28): the coverage check reads the generator's layout; on the main agent's own SUMMARY it is
    # one note listing what it cannot see, for the agent to check in its own words
    sp_ = [" ".join(str(p_).split()) for p_ in summary_problems(cfg, inp=inp, hand_edited=True)]
    if sp_:
        out.append(("deliver", f"the summary coverage check (it reads the generator's layout; your wording may differ) "
                               f"cannot see {len(sp_)} item(s) in SUMMARY.md as it expects -- check that each is covered: "
                               + "; ".join(sp_)))
    # trial #10 audit: every Lean name a delivered document cites exists (a wrong Mathlib name shipped); the main
    # agent's SUMMARY and REPORT as delivered (approver 2026-10-28)
    try:
        named = {}
        for name_ in ("SUMMARY.md", "REPORT.md"):
            p_ = os.path.join(rd, name_)
            named[name_] = open(p_, encoding="utf-8").read() if os.path.isfile(p_) else None
        for name_, path_ in (("DECISIONS.md", os.path.join(rd, "DECISIONS.md")),
                             ("SIGNOFF.md", os.path.join(rd, ar, "SIGNOFF.md") if ar else "")):
            if path_ and os.path.exists(path_):
                named[name_] = open(path_, encoding="utf-8").read()
        out += [("deliver", p_) for p_ in cited_name_problems(cfg, named)]
    except Exception as e:      # noqa: BLE001 -- fail closed
        out.append(("deliver", f"the Lean names the documents cite could not be checked: {e!r}"))
    for doc, gone in stops.unnamed(cfg).items():
        out.append(("deliver", f"{doc} does not name {', '.join(sorted(gone))}: prepare again"))
    # integration review (attack 6): the summary's statuses read DEVIATIONS.md's reading-choice and differs rows;
    # one an owner did not write (integrity.py: FAIL[ownership]) never reaches a delivered summary
    import integrity
    try:
        out += [("ownership", t) for t in integrity.deviations_ownership_problems(cfg)]
    except Exception as e:      # noqa: BLE001 -- fail closed, the reason shown
        out.append(("ownership", f"the ownership of DEVIATIONS.md could not be checked: {e!r}"))
    out += [("unverified", t) for t in unverified_problems(cfg, inp)]
    # B9 (U2 §1 routing): an outstanding Fail/Ambiguous or an unrecorded assumption is the adjudicator's (pending
    # the next adjudication); a status no route covers is disclosed in release (the summary says it), RED in dev
    import result_status as _rs
    if project.mode(cfg) != "release":
        accepted = unmapped_accepted(cfg)
        for r in _rs.routes(cfg, inp):
            if r.code == _rs.UNMAPPED_CODE and unmapped_line(r) not in accepted:
                out.append((_rs.UNMAPPED_CODE, f"{r.result}: {r.reason}"))
    # approver (2026-10-28): no hand edits, status check or trust-line judgement any more -- the main agent writes the
    # documents and the delivery reviewers advise (run/stage5-delivery.md)
    out += [("deliver-stale", t) for t in stale_problems(cfg)]
    out += pending_adjudication(cfg, inp)
    return out


ROUTE_CHANGES_HEAD = re.compile(r"^##\s+Route changes\s*$", re.M)


def route_change_lines(text):
    """The non-empty lines of AUTHOR_NOTES.md's `## Route changes` section, whitespace-normalized (a table's header
    and separator rows included: they never differ from one version to the next)."""
    m = ROUTE_CHANGES_HEAD.search(text or "")
    if not m:
        return []
    body = re.split(r"^## ", text[m.end():], maxsplit=1, flags=re.M)[0]
    return [" ".join(l.split()) for l in body.splitlines() if l.strip()]


def route_changes_pending(cfg):
    """[line] of AUTHOR_NOTES.md's "Route changes" that no adjudication has seen: absent from that section as it
    stood at the last adjudication (the newest commit of an ADOPTED.md of the rounds directory). Integrated review
    fix 5: under ownership 3 the adjudicator writes DEVIATIONS.md from these rows, so a row recorded after the last
    adjudication never reached the report (stage3-proofs.md "Route changes"); --deliver refuses it (adj-record)
    until a round's adjudicator has seen it. A run pinned before ownership 3 writes DEVIATIONS.md itself: []."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    p = os.path.join(rd, "AUTHOR_NOTES.md")
    if not deviations_adjudicators(rd) or not os.path.exists(p):
        return []
    now = route_change_lines(open(p, encoding="utf-8").read())
    if not now:
        return []
    top, rel = project.rounds_rel(rd, "AUTHOR_NOTES.md")
    if top is None:
        return now
    rel_dir = os.path.dirname(rel)
    r = subprocess.run(["git", "-C", top, "log", "-1", "--format=%H", "--", f"{rel_dir}/*/ADOPTED.md"],
                       capture_output=True, text=True)
    last = r.stdout.strip() if r.returncode == 0 else ""
    if not last:
        return now
    before = set(route_change_lines(project.committed_blob(top, last, rel) or ""))
    return [l for l in now if l not in before]


def unmapped_line(r):
    """The RED line delivery_check prints for a status-unmapped route `r`, as a stop records it (stops.causes)."""
    return ("RED[status-unmapped] " + " ".join(f"{r.result}: {r.reason}".split()))[:300]


def unmapped_accepted(cfg):
    """{line} of RED[status-unmapped] that a closed stop recorded (dev mode; integrated review fix 6). A status no
    route covers had no cure in dev: the run stops on it (`stops.py open --cmd "python3 audits/make_report.py --check
    --delivery"`), the operator first tries the fixed cures (Phase 0 rewrites DEPENDENCIES.json; an index cell naming
    no declaration is corrected), and what remains is the human's answer under `involved` (close --human) or the
    operator's [DELEGATED] decision under a delegating level (close --delegated): closed, the stop accepts the
    status as shown -- disclosed, as release does (the summary prints it, the report names the stop)."""
    import result_status as _rs, stops
    out = set()
    for s_ in stops.stops(cfg):
        sd = stops.stop_dir(cfg, s_)
        if not (stops.load(os.path.join(sd, "CLOSED.json")) or {}).get("by"):
            continue
        for x in (stops.load(os.path.join(sd, "STOP.json")) or {}).get("causes") or []:
            if x.get("code") == _rs.UNMAPPED_CODE:
                out.add(" ".join(str(x.get("line", "")).split())[:300])
    return out


def pending_adjudication(cfg, inp=None):
    """[(code, text)] what only the next adjudication clears, as --deliver refuses it: B9's adj-record routes (an
    outstanding Fail/Ambiguous, an unrecorded assumption), a result left unproved no round has adjudicated since
    (decisions.pending_refusal), and every adjudicator-owned record fault (adjudication_findings; their codes:
    adj-record, or the record-fix codes). One list, read by delivery_problems and by scope.empty_scope_next: an
    empty diff scope while an adj-record item is pending goes to a full round, never to Stage 5 (integrated review
    fix 2: a `leave <decl> unproved` line logged after the final round looped between NEXT[stage5] and
    RED[adj-record])."""
    import decisions, result_status as _rs
    out = [("adj-record", f"pending the next adjudication: {r.result}: {r.reason}")
           for r in _rs.routes(cfg, inp) if r.code == "adj-record"]
    pend = decisions.pending_refusal(cfg)
    if pend:
        out.append(("adj-record", pend))
    out += [(f.code, "pending the next adjudication: " + " ".join(str(f).lstrip("! ").split()))
            for f in adjudication_findings(cfg)]
    rc = route_changes_pending(cfg)
    if rc:
        out.append(("adj-record", f"pending the next adjudication: {len(rc)} line(s) under \"Route changes\" in "
                                  f"AUTHOR_NOTES.md recorded after the last adjudication, which writes their DEVIATIONS.md "
                                  f"rows (first: {rc[0][:160]}): run a round (a diff round; when scope.py exits 3 with "
                                  f"NEXT[full-round], a full round), then prepare and the readers"))
    return out


def delivery_check(cfg):
    """make_report.py --check --delivery: print each RED precondition; exit 1 if any (a FORMS command)."""
    found = delivery_problems(cfg)
    for code, t in found:
        print(f"RED[{code}] " + " ".join(str(t).split()))
    print(f"delivery check: {'ok' if not found else 'NOT deliverable'}: {len(found)} precondition(s) open"
          + ("" if not found else " (never a stop: prepare and the readers, a full round, or a diff round)"))
    return 1 if found else 0


def assumptions(cfg):
    """hypotheses.report(cfg): {"rows": [[assumed, kind, stands for, plain English, Lean]], "notes",
    "why", "counts"} -- axioms (collectAxioms), declared literature hypotheses, and every hypothesis the
    walk lists, with its adjudicator row."""
    import hypotheses
    return hypotheses.report(cfg, os.path.join(REPO, cfg["rounds_dir"]))


ASSUME_MD = ("Read off the Lean (the assumption walk, `dependencies.py`), not written by hand: for every "
             "result, each hypothesis of its statement that uses a project notion no Definition row of the "
             "index covers -- a hypothesis binder, a condition inside a subtype, set or structure argument, an "
             "argument whose type contains anywhere (as itself, or under a function, product, subtype, `Option`, "
             "`List` or other wrapper, or inside a project definition it uses) a project structure or class "
             "with a Prop field (directly or through its fields), or one inside the statement itself -- "
             "with what it stands for and its plain-English reading (the adjudicator's), declared axioms, and "
             "the literature results the project takes as hypotheses. A result whose statement carries one is "
             "conditional on it. Hypotheses built only from the paper's definitions and Mathlib are not listed: "
             "what was checked of them is the correspondence and paper-faithfulness reviews of each statement "
             "against the paper (AI reviews, not a proof), and the walk's check that no hypothesis is the "
             "result's own conclusion or restates another result. The walk is syntactic: it reads which "
             "constants a hypothesis's type uses, so a hypothesis encoded as a Bool-valued function or as data "
             "(a number, a function or a structure standing for a condition, without a Prop field) can escape it, "
             "and the goal/restates check does not look inside a Mathlib structure, except the `P` of a "
             "`Fact P` argument.")

# One source (trial #9): a section's text is a list of blocks -- ("p", text), ("none", text), ("table", header,
# rows, widths) -- that blocks_md renders, and every empty-section text below is one constant. (The LaTeX rendering
# that once printed them too is gone: the PDF is made from this markdown by agents, render_record.py.)
REAPPROVAL_INTRO = ("Approved statements changed after the approval, each announced by `signoff.py reapprove --begin` "
                    "before the edit and closed by a new `signoff.py approve` (run/reapproval.md). An OPEN one was "
                    "never approved.")
DISCLOSED_HEAD = ("**Known faults, disclosed (release mode: presentation or bookkeeping, not the mathematics; they did "
                  "not stop the run):**")
ASSUME_NONE = ("None: no axiom, no declared literature hypothesis, and no hypothesis the walk lists (it reads the "
               "statements' types as said above).")
ASSUME_HEADER = ["assumed", "kind", "stands for (source)", "plain English", "Lean"]
ASSUME_WIDTHS = ["2.8cm", "3.0cm", "3.4cm", "2.8cm", "3.4cm"]
NONE_RECORDED = "None recorded."
NO_QUESTION = "No open QUESTION row."
NO_REVOTE = "No unsettled re-vote."
NO_DEFER = "No standing defer."
NO_DELEGATED = "None."
NO_ESCALATION = "None written."
NO_RESOLVED = "None: no stop was cleared without you."
NO_STOPS = "None: the run recorded no stop."
NO_SETASIDE = "None: nothing was set aside and no lane NOTE was cleared."
NO_UNUSED = "None: every formalized result is on the proof path of a goal result."


def assume_blocks(asm):
    """Section 2 (B5/B6) as blocks: the walk's description, NOT COMPUTED, the table or the none line, and the notes
    (hypotheses added since the approval, missing theory, instances, bare Prop definitions)."""
    b = [("p", ASSUME_MD)]
    if asm.get("why"):
        b.append(("p", "NOT COMPUTED: " + asm["why"] + "."))
    if asm.get("rows"):
        b.append(("table", ASSUME_HEADER, [list(r) for r in asm["rows"]], ASSUME_WIDTHS))
    elif not asm.get("why"):
        b.append(("none", ASSUME_NONE))
    return b + [("p", n_) for n_ in asm.get("notes") or []]


def blocks_md(blocks):
    out = ""
    for b in blocks:
        if b[0] == "p":
            out += f"\n{b[1]}\n"
        elif b[0] == "none":
            out += f"\n_{b[1]}_\n"
        elif b[0] == "table":
            hd_ = b[1]
            out += "\n| " + " | ".join(hd_) + " |\n|" + "---|" * len(hd_) + "\n" + "".join(
                "| " + " | ".join(str(c).replace("|", "\\|") for c in (list(r) + [""] * len(hd_))[:len(hd_)]) + " |\n"
                for r in b[2])
    return out


VACUOUS_MD = ("A statement is true only vacuously when, for parameter values the paper's statement "
              "covers, its hypotheses cannot all be satisfied, so it holds for no mathematical reason "
              "(for instance a lemma stated inside a proof by contradiction, whose setting cannot "
              "exist). Each entry says for which parameters, why, the decision taken and its reasoning, "
              "and whether it still holds of the Lean (status).")
SEVERITY_MD = ("Each defect has a *status*, what is wrong as printed (false, vacuous, unsupported, or misprint: "
               "true as intended), and a *repair*, what it takes to repair (none: intent unknown; typo; add "
               "hypothesis; local; substantial; not repaired). False defects come first. A false statement's "
               "counterexample is stated in the paper's notation and checked against its hypotheses as "
               "printed; a counterexample that exists only in the Lean encoding (natural-number subtraction, "
               "division by zero, indexing) is an encoding error, fixed in the Lean, not a defect. Each "
               "entry also states its consequence.")
LATEX_CMD = re.compile(r"\\[A-Za-z]+")
DOLLAR_MATH = re.compile(r"\$[^$\n]+\$")


def codeify_latex(cell):
    """LaTeX in a record the operator may not edit (ADJ_RECORDS), set as code so it does not print
    raw: `$m\\le n$` -> `` `m\\le n` ``, a stray `\\in` -> `` `\\in` ``. Existing code spans are kept.
    Only the adjudicator may rewrite these records, and only in a round that Phase 0 must first
    pass; failing the check on them deadlocked a run (small-paper run, stop S3, 2026-10-21)."""
    parts = re.split(r"(`[^`]*`)", cell)
    for i in range(0, len(parts), 2):
        t = DOLLAR_MATH.sub(lambda m: "`" + m.group(0)[1:-1].strip() + "`", parts[i])
        segs = re.split(r"(`[^`]*`)", t)
        for j in range(0, len(segs), 2):
            segs[j] = re.sub(r"\\[A-Za-z]+(?:\{[^{}`]*\})*(?:[_^](?:\{[^{}`]*\}|\w))*", lambda m: "`" + m.group(0) + "`", segs[j])
        parts[i] = "".join(segs)
    return "".join(parts)
FILE_LINE = re.compile(r"\b([A-Za-z0-9_/]+\.lean):(\d+)((?:\s*,\s*:\d+)*)")
TEX_LINE = re.compile(r"\btex (?:l\.\s*~?)?(\d+)((?:\s*(?:[–-]|,)\s*\d+)*)")
BARE_LINE = re.compile(r"(?<!tex )(?<![\w.])l\.\s*~?\d+")
BARE_ID = re.compile(r"(?<![\w.])([RGQ]\d+)(?![\w.])")
DECL_AT = r"^[ \t]*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*(?:theorem|lemma|def|abbrev|structure|inductive|class|instance|axiom|opaque)\s+(?:\S+\.)?{}(?![\w'.])"


# a declaration in comment-masked text: keyword at the start of a line (never across blank lines,
# review of fix-mini2 L1), the declared name captured
DECL_NAMED = re.compile(r"^[ \t]*(?:@\[[^\]\n]*\][ \t]*\n?[ \t]*)?(?:(?:private|protected|noncomputable)[ \t]+)*"
                        r"(theorem|lemma|def|abbrev|structure|inductive|class|instance|axiom|opaque)[ \t]+"
                        r"([^\s(:{\[]+)", re.M)
SCOPE_RE = re.compile(r"^[ \t]*(?:(namespace)[ \t]+(\S+)|(?:noncomputable[ \t]+)?(section)\b[ \t]*(\S*)|(end)\b[ \t]*(\S*))", re.M)


def declarations(txt):
    """[(full name, line)] of the declarations in Lean text `txt`, comments (and docstrings) masked
    first so a commented-out declaration is none, and each name prefixed by its enclosing
    `namespace`s (review of fix-mini2, M3)."""
    import phase0
    t = phase0.strip_comments(txt)
    events = sorted([(m.start(), "scope", m) for m in SCOPE_RE.finditer(t)]
                    + [(m.start(), "decl", m) for m in DECL_NAMED.finditer(t)], key=lambda e: e[0])
    stack, out = [], []
    for _, kind, m in events:
        if kind == "scope":
            if m.group(1):
                stack.append(("ns", m.group(2)))
            elif m.group(3):
                stack.append(("sec", m.group(4)))
            elif m.group(5) and stack:
                stack.pop()
            continue
        name = m.group(2)
        if name.startswith("_root_."):
            full = name[len("_root_."):]
        else:
            full = ".".join([n for k, n in stack if k == "ns"] + [name])
        out.append((full, t.count("\n", 0, m.start(1)) + 1))
    return out


def decl_hits(nm, txt):
    """The lines declaring the name `nm` a record cites: a qualified name must be the declaration's
    full name or a dotted tail of it (`A.helper` is not `B.helper`); a bare name matches any
    declaration with that last component."""
    hits = []
    for full, line in declarations(txt):
        if ("." in nm and (full == nm or full.endswith("." + nm))) or ("." not in nm and full.rsplit(".", 1)[-1] == nm):
            hits.append(line)
    return hits


def refresh_lines(cell, cfg, _files=None):
    """`name` at File.lean:N in a record cell, with N set to the line where `name` is declared now.
    An adjudicator's record cites lines at the commit it adjudicated; a later docstring edit moves
    them, and only an adjudicator may rewrite the record, so a run once spent a whole diff round
    only to refresh them (mini2 audit). The report resolves them from the declaration NAME instead.
    Changed only when it is unambiguous: one number (no `, :M` continuation), the nearest
    backticked name in the 90 characters before it (the name the stale-line scan checks it against),
    declared exactly once in that file (decl_hits: comments masked, the full name matched),
    more than 2 lines away. Everything else is left as written (and the stale-line scan still
    reports it). refresh_lines.count counts the citations changed."""
    files = _files if _files is not None else {
        rel: open(os.path.join(REPO, rel), encoding="utf-8").read()
        for rel in cfg.get("lean_files", []) if os.path.exists(os.path.join(REPO, rel))}

    def one(m):
        if m.group(3):
            return m.group(0)
        hits = [x for x in files if x == m.group(1) or x.endswith("/" + m.group(1))]
        if len(hits) != 1:
            return m.group(0)
        before = cell[max(0, m.start() - 90):m.start()]
        names = re.findall(r"`([A-Za-z_][\w'.]*)`", before)
        if not names:
            return m.group(0)
        decls = decl_hits(names[-1], files[hits[0]])
        n = int(m.group(2))
        if len(decls) != 1 or abs(decls[0] - n) <= 2:
            return m.group(0)
        refresh_lines.count += 1
        return f"{m.group(1)}:{decls[0]}"
    return FILE_LINE.sub(one, cell)


refresh_lines.count = 0


def plausible_declaration(nm):
    """Is a backticked name cited at `File.lean:N` plausibly a declaration, so that it must be declared? A
    qualified name (`Ns.foo`) or one of the project's naming convention (OURS: `lemma_4_14`, `claim_4_3`) is;
    a short unqualified name that no project file declares (`hR4`, `hB1`: a proof's local binder) is not, and
    passes when the cited file holds it -- only a name found nowhere is a dead citation (review M2)."""
    return "." in nm or bool(OURS.match(nm))


def names_cited_ok(nm):
    """Names that need no declaration in the project: Mathlib's (qualified with a Mathlib namespace)."""
    return {nm.rsplit(".", 1)[-1]} if re.match(r"^(?:Finset|Fin|Nat|Int|Set|List|Equiv|Matrix|Function)\.", nm) else set()


ADJ_RECORDS = ("SKIPPED.md", "PAPER_DEFECTS.md", "VACUOUS.md")


def deviations_adjudicators(rounds_dir):
    """Is DEVIATIONS.md the adjudicator's in this run (a pin of ownership 3 or later: integrity.OWNED_SINCE)? Then
    it is read like ADJ_RECORDS (its LaTeX set as code, a stale line a NOTE, a table fault pending the next
    adjudication): the operator cannot fix it. A run pinned earlier, or no pin: the operator's, as before."""
    import integrity
    try:
        v = int(json.load(open(os.path.join(rounds_dir, integrity.PIN))).get("ownership", 1))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    return v >= integrity.OWNED_SINCE["DEVIATIONS.md"]


def adj_records(rounds_dir):
    return ADJ_RECORDS + (("DEVIATIONS.md",) if deviations_adjudicators(rounds_dir) else ())


DEAD_CITATION = ("declared in no project file", "names no project file")
# a dead citation in an adjudicator's record (rendering_problems' "! <file> row <key>: ...")
ADJ_DEAD = re.compile(r"^! (SKIPPED\.md|PAPER_DEFECTS\.md|VACUOUS\.md|DEVIATIONS\.md) row (.*?): "
                      r"(?:`([^`]+)` is cited at |(\S+) names no project file|cited but not declared: `([^`]+)`)")


def dead_citation_code(p_, owned=ADJ_RECORDS):
    """record-cite for a dead citation in an adjudicator-owned record (`owned`: adj_records(), DEVIATIONS.md
    under ownership 3 included; a record correction cures it), report for one in the operator's own text."""
    m = ADJ_DEAD.match(p_)
    return "record-cite" if m and m.group(1) in owned else "report"


def record_faults(cfg, declared=None, rd=None):
    """[(code, file, row key or its prefix, token, text)] of every fault a record correction may cure:
    a dead PAPER_DEFECTS.md witness (dead-witness) and a Lean name or file cited in SKIPPED.md,
    PAPER_DEFECTS.md, VACUOUS.md or (ownership 3) DEVIATIONS.md that does not exist (record-cite) -- the
    same tests as `make_report.py --check`, on the records alone (in `rd`, default the project's rounds dir)."""
    rd = rd or os.path.join(REPO, cfg["rounds_dir"])
    declared = declared_names(cfg["lean_files"]) if declared is None else declared
    out = [("dead-witness", "PAPER_DEFECTS.md", n_, t,
            f"PAPER_DEFECTS.md row {n_}: its witness cell names `{t}`, not a declaration of this project")
           for n_, t in dead_witnesses(os.path.join(rd, "PAPER_DEFECTS.md"), declared)]
    recs = {"deviations": []}
    dev = (("deviations", "DEVIATIONS.md", "kind"),) if deviations_adjudicators(rd) else ()
    for k, f, keycol in (("skipped", "SKIPPED.md", "what"), ("defects", "PAPER_DEFECTS.md", DEFECT_KEY),
                         ("vacuous", "VACUOUS.md", "statement")) + dev:
        h_, rows_ = record_table(os.path.join(rd, f), keycol)
        if k == "defects" and not h_:
            # B3: an old-format (`severity`) table is PENDING[adj-record] until rewritten; its citations are
            # still checked meanwhile (a fault it hides would surface only after the rewrite)
            rows_ = record_table(os.path.join(rd, f), "severity")[1]
        recs[k] = [[refresh_lines(codeify_latex(c), cfg) for c in row] for row in rows_]
    texts = [f"! {f} row {r[0]}: cited but not declared: `{t}`"
             for f, k in (("SKIPPED.md", "skipped"), ("PAPER_DEFECTS.md", "defects"), ("DEVIATIONS.md", "deviations"))
             for r in recs[k] for t in cited_names(r, declared)]
    texts += [p_ for p_ in rendering_problems(dict(cfg, literature_hypotheses=[]), recs["skipped"], recs["defects"],
                                              recs["deviations"], vacuous=recs["vacuous"])
              if any(d_ in p_ for d_ in DEAD_CITATION)]
    keys = {"SKIPPED.md": "skipped", "PAPER_DEFECTS.md": "defects", "VACUOUS.md": "vacuous",
            "DEVIATIONS.md": "deviations"}
    for p_ in texts:
        m = ADJ_DEAD.match(p_)
        if m:
            # the full row key (a rendering problem cuts it to 20 characters): a record correction matches
            # rows exactly, so row 1 never unlocks rows 10-19 (re-check R1)
            tok = next(g for g in m.groups()[2:] if g)
            full = [r[0] for r in recs[keys[m.group(1)]] if r and r[0][:20] == m.group(2)] or [m.group(2)]
            out += [("record-cite", m.group(1), k_, tok, p_.lstrip("! ")) for k_ in dict.fromkeys(full)]
    return out


def rendering_problems(cfg, skipped, defects, deviations, index=(), vacuous=(), questions=(), clearances=()):
    """What a reader of the rendered report would trip over, found mechanically (AUDIT_PROTOCOL.md,
    "Documents a human reads", rules 1, 2 and 6):
      - LaTeX (any `\\command`, or `$...$`) outside a code span: it prints literally;
      - an ID like R7, G3 or Q4 the report does not define (only the route IDs are defined in it);
      - `File.lean:N` (and continuations `, :M`) naming no project file, a line past its end, or
        -- when backticked names precede it, one per number -- a line where that name is not
        declared (rule 2: the line must be the declaration's, at the report's commit);
      - `tex l.N`, `tex N–M`, `tex N, M` past the end of the source, and a bare `l.N`.
    Scanned: SKIPPED.md, PAPER_DEFECTS.md, DEVIATIONS.md, the index rows and the configured
    literature hypotheses' source text; in the open QUESTION rows (ADOPTED.md, the adjudicator's)
    only a stale `File.lean:N`, as a NOTE (a stale line in a question went unreported); likewise in
    the independence clearances (ADOPTED.md, listed in the report: a stale `Lemmas.lean:41` there sat
    beside "Stale line numbers: none", mini2 audit)."""
    out = []
    src = cfg.get("source_pdf", "")
    tex_lines = (open(src, encoding="utf-8", errors="replace").read().count("\n") + 1
                 if src.endswith(".tex") and os.path.exists(src) else None)
    route_ids = {r[0].strip() for r in deviations if r}
    files = {}
    for rel in cfg["lean_files"]:
        p_ = os.path.join(REPO, rel)
        if os.path.exists(p_):
            files[rel] = open(p_, encoding="utf-8").read()

    def resolve(f):
        hits = [x for x in files if x == f or x.endswith("/" + f)]
        return hits[0] if len(hits) == 1 else None

    sources = [("SKIPPED.md", skipped), ("PAPER_DEFECTS.md", defects), ("DEVIATIONS.md", deviations),
               ("VACUOUS.md", list(vacuous)),
               ("index", list(index)),
               ("config literature_hypotheses", [[h.get("lean", "?"), h.get("paper", "")]
                                                 for h in cfg.get("literature_hypotheses", [])]),
               ("QUESTION", [[f"Q{k}", q[3]] for k, q in enumerate(questions)]),
               ("CLEARANCE", [[f"Q{k}", c[2]] for k, c in enumerate(clearances)])]
    for src_name, rows in sources:
        if src_name == "CLEARANCE":
            for p_ in rendering_problems(dict(cfg, literature_hypotheses=[], source_pdf=""), [], [], [],
                                         vacuous=rows) if rows else []:
                m = re.match(r"NOTE VACUOUS\.md row Q(\d+):", p_)
                if m and "but declared at line" in p_:
                    c = clearances[int(m.group(1))]
                    out.append(f"NOTE clearance of {c[1]} (round {c[0]}):" + p_[m.end():])
            continue
        if src_name == "QUESTION":
            # the same scan, keeping only its stale-line NOTEs
            for p_ in rendering_problems(dict(cfg, literature_hypotheses=[], source_pdf=""), [], [], [],
                                         vacuous=rows) if rows else []:
                m = re.match(r"NOTE VACUOUS\.md row Q(\d+):", p_)
                if m and "but declared at line" in p_:
                    q = questions[int(m.group(1))]
                    out.append(f"NOTE QUESTION row on {q[2]} (round {q[0]}):" + p_[m.end():])
            continue
        for r in rows:
            where = f"{src_name} row {r[0][:20]}"
            for cell in r:
                prose = re.sub(r"`[^`]*`", "", cell)
                for rx_ in (LATEX_CMD, DOLLAR_MATH):
                    m = rx_.search(prose)
                    if m:
                        out.append(f"! {where}: LaTeX {m.group(0)[:30]} outside a code span prints literally")
                m = BARE_LINE.search(prose)
                if m:
                    out.append(f"! {where}: {m.group(0)!r} does not say which file: write 'tex l.N' for the "
                               f"source (rule 2)")
                for m in BARE_ID.finditer(prose):
                    if m.group(1) not in route_ids:
                        out.append(f"! {where}: the ID {m.group(1)} is not defined in the report "
                                   f"(say what it stands for)")
                for m in FILE_LINE.finditer(cell):
                    f = m.group(1)
                    nums = [int(m.group(2))] + [int(x) for x in re.findall(r":(\d+)", m.group(3))]
                    rel = resolve(f)
                    if not rel:
                        out.append(f"! {where}: {f} names no project file (or more than one)")
                        continue
                    txt = files[rel]
                    if max(nums) > txt.count("\n") + 1:
                        out.append(f"! {where}: {f}:{max(nums)} is past the end of the file")
                        continue
                    before = cell[max(0, m.start() - 90):m.start()]
                    names = re.findall(r"`([A-Za-z_][\w'.]*)`", before)[-len(nums):]
                    if len(names) == len(nums):
                        for nm, n in zip(names, nums):
                            short = nm.rsplit(".", 1)[-1]
                            decls = [txt.count("\n", 0, d_.start()) + 1
                                     for d_ in re.finditer(DECL_AT.format(re.escape(short)), txt, re.M)]
                            d = re.search(DECL_AT.format(re.escape(short)), txt, re.M)
                            if d and any(abs(a_ - n) <= 2 for a_ in decls):
                                continue
                            if not d:
                                elsewhere = [o for o, t_ in files.items()
                                             if re.search(DECL_AT.format(re.escape(short)), t_, re.M)]
                                if elsewhere:
                                    out.append(f"! {where}: `{nm}` is cited at {f}:{n} but declared in "
                                               f"{', '.join(elsewhere)}")
                                elif short in names_cited_ok(nm):
                                    pass
                                elif not plausible_declaration(nm) and re.search(
                                        rf"(?<![\w'.]){re.escape(nm)}(?![\w'])", txt):
                                    # a local name (a `have` or binder inside a proof: L-inf run, stop S3,
                                    # DEVIATIONS.md row 4's `hR4` at Five.lean:235) that the cited file holds:
                                    # no declaration to find, nothing dead
                                    pass
                                else:
                                    out.append(f"! {where}: `{nm}` is cited at {f}:{n} but declared in no "
                                               f"project file (renamed or deleted?)")
                            if d:
                                at = txt.count("\n", 0, d.start()) + 1
                                if abs(at - n) > 2:
                                    # A record owned by the adjudicator (SKIPPED/PAPER_DEFECTS/VACUOUS)
                                    # cites lines at the commit it adjudicated; adding proofs moves them,
                                    # and only the next round's adjudicator may rewrite the record. Failing
                                    # here would block that very round (Phase 0 must be green), so it is a
                                    # NOTE shown in the report, not a failure (2026-10-14).
                                    lead = "NOTE" if src_name in adj_records(os.path.join(REPO, cfg["rounds_dir"])) else "!"
                                    out.append(f"{lead} {where}: `{nm}` is cited at {f}:{n} but declared at "
                                               f"line {at} (cite the line at the report's commit)")
                if tex_lines:
                    for m in TEX_LINE.finditer(cell):
                        ns = [int(m.group(1))] + [int(x) for x in re.findall(r"\d+", m.group(2))]
                        if max(ns) > tex_lines:
                            out.append(f"! {where}: {m.group(0)} is past the end of the source")
    return out


def stale_sorry_notes(rounds_dir, head):
    """NOTEs for an adjudicator record whose text says the proofs are `sorry` at a commit other than
    the report's: a statement-stage sentence carried into the delivered report (small-paper run:
    "All proofs are sorry at commit 7537c3d" under "Not defects", after every proof was done). The
    report is regenerated only by a green Phase 0, so at its commit there is no sorry -- unless the check that the
    proofs are complete could not run (C2-FIX 5b review 2): then no such note is made (page 1 says it in plain words)."""
    out = []
    import stops
    if os.path.isdir(os.path.join(rounds_dir, "stops")) and any(
            (stops.load(f_) or {}).get("by") == "core-fault" and stops.core_guarantee(stops.load(f_) or {})[0] == "proof"
            for f_ in glob.glob(os.path.join(rounds_dir, "stops", "S*", "CLOSED.json"))):
        return out
    for f in ADJ_RECORDS:
        p_ = os.path.join(rounds_dir, f)
        txt = open(p_, encoding="utf-8").read() if os.path.exists(p_) else ""
        for m in re.finditer(r"\bsorry\b`?[^.\n|]{0,60}?\bat commit `?([0-9a-f]{7,40})", txt, re.I):
            if head and not (head.startswith(m.group(1)) or m.group(1).startswith(head)):
                out.append(f"NOTE {f}: says the proofs are `sorry` at commit {m.group(1)}; at this report's "
                           f"commit {head} Phase 0 found none (stale text, to be refreshed by the adjudicator)")
    return out


def count_text(index):
    """"57 index rows (55 numbered results plus 2 restatements of earlier results)": a count that
    differs from the paper's own must say why (rule 3)."""
    # C2 audit: a row without a number is counted by its kind -- a definition, notation or construction the paper
    # introduces in its text, or a result labelled otherwise ("Theorem A"); each row in exactly one count (review:
    # an unnumbered restatement was subtracted twice, and "Theorem A" was called a notation)
    kinds = {"numbered": 0, "restated": 0, "lettered": 0, "unnumbered": 0}
    for r in index:
        lab = " ".join(str(r[0]).split())
        if len(r) > 1 and re.search(r"restatement of", r[1], re.I):
            kinds["restated"] += 1
        elif NUMBERED.match(lab):
            kinds["numbered"] += 1
        elif re.match(r"(?i)(?:definition|notation|construction)\b", lab):
            kinds["unnumbered"] += 1
        else:
            kinds["lettered"] += 1
    if kinds["numbered"] == len(index):
        return f"{len(index)} numbered result{'s' if len(index) != 1 else ''}"
    pl = lambda n, w: f"{n} {w}{'s' if n != 1 else ''}"
    parts = [pl(kinds["numbered"], "numbered result")]
    if kinds["restated"]:
        parts.append(pl(kinds["restated"], "restatement") + " of earlier results")
    if kinds["lettered"]:
        parts.append(pl(kinds["lettered"], "other unnumbered row") + " (a lettered result such as \"Theorem A\", a "
                     "remark, a condition)")
    if kinds["unnumbered"]:
        parts.append(f"{kinds['unnumbered']} unnumbered definition{'s' if kinds['unnumbered'] != 1 else ''} or "
                     f"notation{'s' if kinds['unnumbered'] != 1 else ''} the paper introduces in its text")
    return f"{len(index)} index rows ({' plus '.join(parts)})"


# PDF-AGENTS (approver, 2026-10-23): the PDF is a rendering of this markdown by fresh agents (render_record.py). The
# markdown cannot report how its own rendering ended (that would change it and restart the loop), so one static
# line says where that is told: README section D of the delivery
PDF_ROW = ("Typeset PDF", "the PDF says exactly what this markdown says",
           "rendered from this markdown and checked by independent agents (a renderer, a verifier, two checkers); how "
           "that check ended is in the delivery README, section D")
PDF_LINE = ("The PDF of this document is a typeset rendering of its markdown, made and checked by independent agents; "
            "how that check ended is in the delivery README, section D.")


def waiver_row(cfg):
    """The human's waivers of an ownership FAIL (integrity.py --acknowledge; RULINGS A5b): on the
    summary page, never only in an appendix."""
    import integrity
    w = integrity.waiver_rows(cfg)
    return ("Record ownership", "every record was committed only by the step that owns it (integrity check)",
            "no exception" if not w else f"{len(w)} commit(s) WAIVED by the human: " + "; ".join(
                f"{c} \"{s_}\" added {f} (stop {st}, the human's answer: \"{a_}\")" for c, s_, f, st, a_ in w))


def cell_decls(cfg, cell, decls):
    """The full Lean names an index cell cites: each backticked name resolved the way the
    dependency walk resolves it (dependencies.resolve_all: as written, then namespace ++ name)."""
    import dependencies
    names = [t.split("(")[0].strip() for t in re.findall(r"`([^`]+)`", cell)]
    names = [n for n in names if re.fullmatch(r"[A-Za-z_][\w'.₀-₉]*", n)]
    return dependencies.resolve_all(names, cfg.get("namespace", ""), decls) if names else set()


def unproved_problems(cfg, index, skip_head, skipped, declared):
    """(problems, notes, rows, pending) for the non-goal results a logged [DELEGATED] decision left
    unproved (decisions.unproved, from the committed RUN_LOG.md). Each needs (a) a "not formalized"
    index cell wherever the index cites it -- the cell's names resolved as the dependency walk
    resolves them, so a short `lemma_2_3` cites `N.lemma_2_3` (cell_decls) -- and (b) a
    SKIPPED.md row naming it in backticks whose "decided by" column carries that very tag (the
    adjudicator's record). Until a round has been adjudicated since the log line was committed, a
    missing row is pending (a NOTE): that round's adjudicator writes it (keyed on the declaration:
    decisions.adjudicated_since); `project.py --deliver` refuses anything still pending. rows: [decl,
    paper result, decided by, the log line] for the coverage section; pending: the index labels
    whose row is explained by a pending one."""
    import decisions, dependencies
    left = decisions.unproved(cfg)
    probs, notes, rows, pending = [], [], [], set()
    i_dec = next((i for i, h in enumerate(skip_head) if h.startswith("decided")), None)
    decls = dependencies.project_decls(cfg) if left["decls"] else set()
    cited = {r[0]: cell_decls(cfg, r[1], decls) for r in index if len(r) > 1} if left["decls"] else {}
    for d, tag in left["decls"].items():
        cites = [r for r in index if d in cited.get(r[0], ())]
        for r in cites:
            if not NOT_FORMALIZED.search(r[1]):
                probs.append(f"! {r[0]}: `{d}` is left unproved by a [DELEGATED] decision, so its index cell must "
                             f"say \"stated, not proved: not formalized\"")
        rows_ = [r for r in skipped if f"`{d}`" in " ".join(r)]
        good = [r for r in rows_ if i_dec is not None and i_dec < len(r) and tag in r[i_dec]]
        if d not in declared:
            probs.append(f"! `{d}`: left unproved by a [DELEGATED] decision, but it is not declared in the Lean")
        if not good:
            what = (f"no SKIPPED.md row names `{d}` with \"decided by\" = {tag}" if not rows_ else
                    f"the SKIPPED.md row naming `{d}` does not give {tag} as \"decided by\"")
            if decisions.adjudicated_since(cfg, d):
                probs.append(project.Finding(f"! `{d}` is left unproved by a [DELEGATED] decision, and a round "
                                             f"was adjudicated since: {what} (the next adjudicator records it; "
                                             f"otherwise prove it)", "adj-record"))
            else:
                notes.append(f"`{d}`: left unproved, pending the next adjudication ({what} yet)")
                pending |= {r[0] for r in cites}
        rows.append([f"`{d}`", ", ".join(r[0] for r in cites) or "(not in the index)", tag,
                     left["lines"][d].split("]", 1)[-1].strip()])
    # re-check of Q1 (b), MED-A: every auxiliary the axiom sweep accepted under an exempt name (no
    # source range, a generated last component; DEPENDENCIES.json, written by Phase 0's walk with
    # the sweep's rule) is listed with its parent, so nothing exempted is undisclosed
    if left["decls"]:
        aux, why = dependencies.aux_record(cfg, left["decls"])
        if aux is None:
            probs.append(f"! the auxiliary declarations the axiom sweep accepts under a result left unproved are "
                         f"not recorded ({why}): run Phase 0 (it writes DEPENDENCIES.json), so the report lists each")
        for a_, par in aux or []:
            rows.append([f"`{a_}`", f"(an auxiliary of `{par}`)", left["decls"].get(par, "?"),
                         f"generated with no source range under `{par}`: the axiom sweep accepts its sorryAx "
                         f"under that result's line"])
    return probs, notes, rows, pending


# Adjudicator-owned record faults (deadlock sweep D1-D3): only an adjudication (or, for the record-fix
# codes, a record correction) can clear them. Phase 0 (`--pending`) prints them as PENDING[adjudication]
# NOTEs, so a round can start and its adjudicator is not blocked; `integrity.py --commit-adjudication`
# refuses while one remains (the adjudicator clears them in its turn), and so do `make_report.py
# --check` without `--pending` and `project.py --deliver`.
PENDING_CODES = ("adj-record", "dead-witness", "record-cite")
ADJ_TABLES = (("skipped", "SKIPPED.md", "what"), ("defects", "PAPER_DEFECTS.md", DEFECT_KEY),
              ("vacuous", "VACUOUS.md", "statement"))


def adj(problems):
    """The problems of an adjudicator-owned record, as adj-record findings."""
    return [project.Finding(p_, "adj-record") for p_ in problems]


def is_pending(p_):
    return getattr(p_, "code", None) in PENDING_CODES


def pending_line(p_):
    """How Phase 0 (`--pending`) prints an adjudicator-owned fault: a NOTE, never a failure line."""
    return f"PENDING[adjudication] {p_.code}: " + " ".join(str(p_).lstrip("! ").split())


def table_shape_problems(rounds_dir, k, f, keycol, head, rows, cfg=None):
    """A record table without its key column, or a row whose cell count is not its header's (a bare `|`
    in a cell): blocks in every mode (review H4: the checks that read the record would read shifted
    cells). adj-record in an adjudicator's record, report in DEVIATIONS.md (the operator's)."""
    code, out = ("report" if k == "deviations" and not deviations_adjudicators(rounds_dir) else "adj-record"), []
    if not head and has_table(os.path.join(rounds_dir, f)):
        # rows under a header without the key column were dropped from the report, silently
        out.append(project.Finding(f"! {f}: it has a table, but no table header has a `{keycol}` column; "
                                   f"its rows are not in the report (add the column; the record's columns are in "
                                   f"AUDIT_PROTOCOL.md)", code))
    for row in rows:
        if len(row) != len(head):
            out.append(project.Finding(f"! {f} row {row[0][:20]}: {len(row)} cells under a {len(head)}-column "
                                       f"header (a literal `|` in a cell is written `\\|`)", code))
    if k in {k_ for k_, _f, _c in HISTORY_RECORDS}:
        out += [project.Finding(x, code) for x in row_history_problems(rounds_dir, f, keycol)]
    if k == "defects":
        old_ = [x for x in defect_problems(os.path.join(rounds_dir, f), head, rows, cfg)]
        if old_ and not head:
            out = [x for x in out if "no table header has a" not in str(x)]
        out += [project.Finding(x, code) for x in old_]
    return out


def _names_in(text):
    """The result names in `text`, normalised: a SKIPPED row explains a result it names EXACTLY ("Lemma
    1.3" is not explained by a row about "Lemma 1.31": a substring match once did that)."""
    return {re.sub(r"\s+", " ", m.group(0)).lower()
            for m in re.finditer(rf"\b(?:{project.RESULT_KINDS_RE})\s+[\d.]*\d(?:\([^)]*\))?", text, re.I)}


def index_adopts(cfg):
    """{index label: round} for every ADOPTED.md ADOPT row whose item is exactly an index label (bold,
    italics, backticks and spaces ignored): the adjudicator's ruling that the INDEX is the wrong side of
    "formalized AND skipped" (re-check N2)."""
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO, cfg["rounds_dir"], "*", "ADOPTED.md"))):
        for r in table_rows(f):
            if len(r) > 3 and re.match(r"[\W_]*ADOPT\b", r[3]):
                out[r[1].strip(" *_`")] = os.path.basename(os.path.dirname(f))
    return out


def index_accounting(index, skipped, declared, pending, adopts=None):
    """(accounted, unaccounted, problems): every index row is formalized or explained by a SKIPPED.md row
    (or pending: left unproved). "Formalized AND skipped": the adjudicator decides which side is wrong
    (adj-record) -- the skip (it fixes its row) or the index (an ADOPT row naming the index label,
    `adopts`: then the operator's to fix, `report`); it is never told to delete a skip (re-check N2)."""
    # only the row's subject -- its "what" column -- names what it skips; its reasoning may
    # mention other results (a Remark 4.4 row that cites "the Theorem 4.1 value" skips 4.4 only)
    skip_names = set().union(*(_names_in(r[1] if len(r) > 1 else "") for r in skipped)) if skipped else set()
    accounted, unaccounted, probs = [], [], []
    for r in index:
        name = r[0]
        base = re.sub(r"\s+", " ", name.split("(")[0].strip()).lower()
        cited_decls = [t for t in re.findall(r"`([^`]+)`", r[1] if len(r) > 1 else "")
                       if t.split("(")[0].strip() in declared]
        # formalized = the row cites at least one declaration that exists; backticked math or a
        # misspelt name does not make a result formalized
        formalized = len(r) > 1 and not NOT_FORMALIZED.search(r[1]) and bool(cited_decls)
        explained = (base in skip_names or re.sub(r"\s+", " ", name).lower() in skip_names
                     # left unproved, its SKIPPED.md row pending the next adjudication
                     or name in pending)
        (accounted if (formalized or explained) else unaccounted).append(name)
        if not formalized and not explained:
            probs.append(f"! {name}: not formalized by the index, and no SKIPPED.md row explains it")
        if formalized and explained and not re.search(r"\(|partial|half", name + " " + r[1], re.I):
            if name in (adopts or {}):
                probs.append(project.Finding(
                    f"! {name}: the index says it is formalized AND a SKIPPED.md row skips it; the adjudication "
                    f"{adopts[name]} ADOPTed fixing the index (the skip stands): make its index cell \"not "
                    f"formalized\" (or cite the declaration that does formalize it, if the row skips only a part), "
                    f"commit, re-run Phase 0", "report"))
            else:
                probs.append(project.Finding(
                    f"! {name}: the index says it is formalized AND a SKIPPED.md row skips it: decide which side is "
                    f"wrong. The skip is wrong (the cited declaration does formalize it): fix the SKIPPED.md "
                    f"row, or mark it `superseded (<round>)` in its last cell (a row is never removed). The index is wrong (the skip is right): keep the row and write an ADOPT row with item "
                    f"`{name}` (fix its index cell); the operator then corrects the index", "adj-record"))
    return accounted, unaccounted, probs


def adjudication_findings(cfg, round_name=None, revotes=None):
    """[Finding] every adjudicator-owned record fault (PENDING_CODES) of the records as they stand on
    disk, with the same predicates as build(): a table's shape, a prose-only defect, a missing-theory
    "decided by", a result left unproved without its SKIPPED.md row (also while it is still pending:
    the adjudication about to be committed is the next one), "formalized AND skipped", a carried item
    without its row (`round_name`: that round's ADOPTED.md as it is counts), and record_faults
    (dead-witness, record-cite). `integrity.py --commit-adjudication` refuses while one remains."""
    rd = os.path.join(REPO, cfg["rounds_dir"])
    declared = declared_names(cfg["lean_files"])
    heads, recs, out = {}, {}, []
    for k, f, keycol in ADJ_TABLES + ((("deviations", "DEVIATIONS.md", "kind"),) if deviations_adjudicators(rd) else ()):
        heads[k], recs[k] = record_table(os.path.join(rd, f), keycol)
        out += table_shape_problems(rd, k, f, keycol, heads[k], recs[k], cfg)
    out += adj(prose_only_defects(os.path.join(rd, "PAPER_DEFECTS.md")))
    out += missing_theory_problems(cfg, heads["skipped"] or [], recs["skipped"])
    ixf = project.index_file(cfg)
    index = [r for r in table_rows(os.path.join(REPO, ixf)) if r and RESULT.match(r[0])] if ixf else []
    left_p, left_notes, _rows, pending = unproved_problems(cfg, index, heads["skipped"] or [], recs["skipped"],
                                                           declared)
    out += [p_ for p_ in left_p if is_pending(p_)] + adj(f"! {n_}" for n_ in left_notes)
    out += [p_ for p_ in index_accounting(index, recs["skipped"], declared, pending, index_adopts(cfg))[2]
            if is_pending(p_)]
    out += [p_ for p_ in record_problems(rd, round_name, revotes) if is_pending(p_)]
    out += [project.Finding("! " + t, c) for c, _f, _k, _tok, t in record_faults(cfg, declared)]
    out += [p_ for p_ in row_reference_problems(rd) if is_pending(p_)]     # forgery review H1
    import hypotheses       # B5 (U2 §2): an assumed name without a valid `## Hypotheses` row (adj-record)
    out += hypotheses.findings(cfg, rd)
    return out


def record_problems(rounds_dir, round_name=None, revotes=None, cfg=None):
    """["! ..."] the report check takes from the audit record itself, whoever committed it. With
    `round_name`: the adjudication of that round about to be committed counts (its ADOPTED.md as it is)."""
    # every Fail a set-aside carried forward has a row in a later adjudication (RULINGS A7.4): only the
    # next adjudication can write it, so it is adj-record (PENDING in Phase 0; deadlock sweep D1)
    import stops as _stops, lanecheck as _lc, fingerprint as _fp
    out = [project.Finding(f"! carried forward and never adjudicated: {p_}", "adj-record")
           for p_ in _stops.carried_problems(rounds_dir, round_name, revotes=revotes)]
    # every adjudicated round settles its lanes' NOTEs and re-votes (ROUND3 M1: also when committed by hand)
    out += [f"! unsettled adjudication: {p_}" for p_ in _lc.record_problems(rounds_dir)]
    # B7 (U2 §7b): a proof-by-contradiction step a lane passed needs its VACUOUS.md row (the adjudicator's)
    out += [project.Finding(f"! {p_}", "adj-record") for p_ in _lc.contradiction_problems(rounds_dir)]
    # B2 round 3: every commit that changed the approval records passed the approve gate as it applied then
    out += [f"! {p_}" for p_ in _fp.approval_problems(rounds_dir, cfg)]
    # an open re-approval: the freeze check accepts changes to its declarations, nobody approved them
    _ra = _fp.open_reapproval_problem(rounds_dir, cfg)
    if _ra and cfg is not None:
        # B2 (U2 §3 H3): a re-approval the human must answer is a QUESTION in the pending state: the run
        # goes on, and only project.py --deliver refuses it (decisions.question_refusal)
        import decisions as _dc
        q_ = _dc.reapproval_question(cfg)
        if q_:
            print(f"PENDING[question] the re-approval of {', '.join(q_['decls'])} awaits the human ({q_['why']}): "
                  "the run goes on; delivery waits")
            _ra = None
    if _ra:
        out.append(f"! {_ra}")
    return out



def build(cfg, check_only=False, pending_ok=False, adjudicating=None):
    """The report (or, `check_only`, its check). `pending_ok` (Phase 0, --pending): an adjudicator-owned record fault
    (PENDING_CODES) is printed as a PENDING[adjudication] NOTE and does not fail; without it, it fails."""
    rounds_dir = os.path.join(REPO, cfg["rounds_dir"])
    index_file = project.index_file(cfg)
    declared = declared_names(cfg["lean_files"])
    problems = []

    index = table_rows(os.path.join(REPO, index_file))
    index = [r for r in index if r and RESULT.match(r[0])]
    # each record's table is the one whose header has its key column: PAPER_DEFECTS.md opens with
    # a status and repair legend, and reading the FIRST table put every defect under the legend's headers
    heads, recs = {}, {}
    for k, f, keycol in (("skipped", "SKIPPED.md", "what"), ("defects", "PAPER_DEFECTS.md", DEFECT_KEY),
                         ("deviations", "DEVIATIONS.md", "kind"), ("vacuous", "VACUOUS.md", "statement")):
        heads[k], recs[k] = record_table(os.path.join(rounds_dir, f), keycol)
        problems += table_shape_problems(rounds_dir, k, f, keycol, heads[k], recs[k], cfg)
    problems += row_reference_problems(rounds_dir)      # forgery review H1: no citation of a missing row
    refresh_lines.count = 0
    for k in ("skipped", "defects", "vacuous") + (("deviations",) if deviations_adjudicators(rounds_dir) else ()):
        # the ADJ_RECORDS (and DEVIATIONS.md under ownership 3)
        # line numbers resolved from the declaration names (refresh_lines): a moved line is no reason
        # for another round (mini2 audit); the report says how many were resolved
        recs[k] = [[refresh_lines(codeify_latex(c), cfg) for c in row] for row in recs[k]]
    recs["defects"] = defect_order(heads["defects"], recs["defects"])     # B3: `false` first
    skipped, defects, deviations, vacuous = recs["skipped"], recs["defects"], recs["deviations"], recs["vacuous"]
    st_col = next((i for i, h in enumerate(heads["vacuous"] or []) if h.lower().startswith("status")), None)
    raw_v = {c[0]: (h, c) for h, c in vacuous_rows(cfg)}
    for row in vacuous:
        found = decided_since(cfg, *raw_v[row[0]]) if row and row[0] in raw_v else []
        if found and st_col is not None and st_col < len(row) and "open" in row[st_col].lower():
            row[st_col] += " -- " + since_note(found)
    # trial #11: a defect row's decision cell, written before the operator's [DELEGATED] decision on it, shows that
    # decision (settled_cell) instead of telling the reader a person will still decide it
    problems += adj(prose_only_defects(os.path.join(rounds_dir, "PAPER_DEFECTS.md")))
    problems += missing_theory_problems(cfg, heads["skipped"], skipped)
    problems += delegation_problems(cfg)
    import hypotheses       # B6 (U2 §7): the missing-theory decision lines (FAIL[missing-theory], the operator's)
    problems += hypotheses.missing_theory_findings(cfg, rd=rounds_dir)
    appr_p = os.path.join(rounds_dir, "APPROVED_FINGERPRINTS.json")
    if os.path.exists(appr_p) and project.approval_file_by(appr_p)[0] is None:
        problems.append("! APPROVED_FINGERPRINTS.json records no approver (`by`): re-record the approval with "
                        "`signoff.py approve --by human|agent` so the report can say who approved")
    front = front_matter(cfg)

    if not index:
        problems.append(f"! parsed 0 index rows from {index_file} — the table moved or changed shape")

    # --- the check that matters: nothing falls between formalized and deliberately skipped ---
    left_p, left_notes, left_rows, pending = unproved_problems(cfg, index, heads["skipped"], skipped, declared)
    problems += left_p
    accounted, unaccounted, acc_p = index_accounting(index, skipped, declared, pending, index_adopts(cfg))
    problems += acc_p

    dev_adj = deviations_adjudicators(rounds_dir)
    for r in index + ([] if dev_adj else deviations):
        for t in cited_names(r, declared):
            problems.append(f"! cited but not declared: `{t}` (in: {r[0][:44]})")
    for f_, rows_ in (("SKIPPED.md", skipped), ("PAPER_DEFECTS.md", defects)) \
            + ((("DEVIATIONS.md", deviations),) if dev_adj else ()):
        for r in rows_:     # an adjudicator's record: a record correction cures it (record-cite)
            problems += [project.Finding(f"! {f_} row {r[0][:20]}: cited but not declared: `{t}`", "record-cite")
                         for t in cited_names(r, declared)]
    # what only the index check sees: index_strict's every-backtick rule, dead defect witnesses
    ix = index_check(cfg, declared) or {}
    if cfg.get("index_strict"):
        problems += [f"! index_strict: `{t}` is not a declaration (in: {p_[:44]})"
                     for p_, t in ix.get("dangling", []) if not OURS.match(t)]
    problems += [project.Finding(f"! PAPER_DEFECTS.md defect {n_}: its witness `{t}` is not declared in this project",
                                 "dead-witness") for n_, t in ix.get("witness", [])]
    problems += record_problems(rounds_dir, adjudicating, cfg=cfg)
    import hypotheses       # B5 (U2 §2): an assumed name without a valid `## Hypotheses` row (adj-record)
    problems += hypotheses.findings(cfg, rounds_dir)
    problems += record_fix_problems(cfg)
    # QUESTION rows are the adjudicator's (ADOPTED.md): their LaTeX is set as code, as in ADJ_RECORDS
    questions = [(r_, l_, i_, refresh_lines(codeify_latex(w_), cfg), n_) for r_, l_, i_, w_, n_ in open_questions(cfg)]
    _rp = rendering_problems(cfg, skipped, defects, deviations, index, vacuous, questions, clearances_shown(cfg))
    record_notes = [p_ for p_ in _rp if p_.startswith("NOTE")]
    if not check_only:
        record_notes += stale_sorry_notes(rounds_dir, delivered_commit(cfg))     # ADDENDUM N2: never HEAD
    # a Lean name or file a record cites that no longer exists is a claim about nothing: F, it blocks
    # (review M2); every other rendering finding is N (render)
    owned = adj_records(rounds_dir)
    problems += [project.Finding(p_, dead_citation_code(p_, owned)) if any(d_ in p_ for d_ in DEAD_CITATION)
                 else project.Finding(p_, "render") for p_ in _rp if not p_.startswith("NOTE")]
    # release mode: a presentation or bookkeeping finding is disclosed, never a failure (project.RELEASE)
    problems, disclosed = project.split(cfg, problems)
    # Phase 0: what only the next adjudication (or a record correction) clears waits for it (sweep D1-D3)
    held = [p_ for p_ in problems if is_pending(p_)] if pending_ok else []
    problems = [p_ for p_ in problems if not (pending_ok and is_pending(p_))]
    held += adj(f"! {n_}" for n_ in left_notes) if pending_ok else []

    count_txt = count_text(index)
    # the in-memory regeneration (report_md) keeps the date the .md was generated on
    stamp = REFERENCE_STAMP or datetime.date.today().isoformat()
    _absent = lambda f: "" if os.path.exists(os.path.join(rounds_dir, f)) else " (absent in this run)"
    box, bg = front
    head = f"# Formalization report — {cfg['source_cite']}\n"
    # B10 (U2 §6.1): section 0 is a pointer to the one-page summary, which lists every disclosure the old box did
    head += "\n" + SUMMARY_POINTER + "\n"
    for title_, para in bg:
        head += f"\n**{title_}.** {para}\n"
    head += f"""
**Generated {stamp} by `audits/make_report.py`. Do not edit this file.**
Its sources are edited instead, by the protocol steps that maintain them:

| section | source | maintained by |
|---|---|---|
| coverage | the index table in `{index_file}` | steps 1 and 5, as results are formalized |
| not formalized | `{cfg['rounds_dir']}/SKIPPED.md`{_absent('SKIPPED.md')} | step 4, when a skip is decided |
| paper defects | `{cfg['rounds_dir']}/PAPER_DEFECTS.md`{_absent('PAPER_DEFECTS.md')} | step 4, when a defect is confirmed |
| proof deviations | `{cfg['rounds_dir']}/DEVIATIONS.md`{_absent('DEVIATIONS.md')} | steps 1 and 5, when a route diverges |
| vacuous statements | `{cfg['rounds_dir']}/VACUOUS.md`{_absent('VACUOUS.md')} | step 4, when a statement is found true only vacuously |
| notes for the reader | `{cfg['rounds_dir']}/READER_NOTES.md` (if present) | the formalizer, for what the human asks to have explained |

Project `{cfg['name']}`, branch `{cfg['branch']}`, namespace `{cfg['namespace']}`.
"""
    if record_notes:
        head += ("\n> **Stale line numbers in adjudicator records** (to be refreshed by the next "
                 "adjudication; the declaration's current line is given):\n>\n"
                 + "".join(f"> * {p_[5:]}\n" for p_ in record_notes))
    else:
        head += "\n**Stale line numbers in adjudicator records:** none.\n"
    lines_resolved = ((f"**Line numbers resolved from declaration names:** {refresh_lines.count} `File.lean:N` "
                       f"citation(s) in the adjudicator records named a declaration that has moved since the record "
                       f"was written; the report gives the line where it is declared at this commit.")
                      if refresh_lines.count else "")
    if lines_resolved:
        head += "\n" + lines_resolved + "\n"
    if held:
        head += ("\n> **Pending the next adjudication** (adjudicator-owned record faults; the adjudication "
                 "commit and the delivery refuse while one remains):\n>\n"
                 + "".join(f"> * {' '.join(str(p_).lstrip('! ').split())}\n" for p_ in held))
    # approver (2026-10-24): what this check discloses is recorded with stops.py disclose and listed in RUN_RECORD.md,
    # not in the report
    if problems:
        head += ("\n> **VERIFICATION FAILED — this report is not yet trustworthy.**\n>\n"
                 + "".join(f"> * {p.lstrip('! ')}\n" for p in problems))
    elif held:
        head += "\n**Not yet verified:** the faults above wait for the next adjudication.\n"
    else:
        head += (f"\n**Verified:** all {count_txt} are either formalized or "
                 f"explained in `SKIPPED.md`, and every Lean name cited below exists.\n")

    def render(title, note, rows, header):
        if not rows:
            return f"\n## {title}\n\n{note}\n\n_{NONE_RECORDED}_\n"
        w = "| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n"
        for r in rows:
            # a literal bar inside a cell must stay escaped, or GitHub splits the cell
            w += "| " + " | ".join(c.replace("|", "\\|") for c in (r + [""] * len(header))[:len(header)]) + " |\n"
        return f"\n## {title}\n\n{note}\n\n{w}"

    trust = trust_rows(cfg) + [mode_row(cfg, disclosed)]
    body = render("1. How far to trust this",
                  "Each layer establishes something different. Only the first is a proof.",
                  [list(r) for r in trust], ["layer", "establishes", "status"])
    rsl = raised_status_lines(cfg)      # SWEEP-FIX D4
    if rsl:
        body += ("\n" + RAISED_HEADING + "\n\n" + RAISED_INTRO + "\n\n"
                 + "".join(f"- {l_}\n" for l_ in rsl))
    reap_rows = reapproval_rows(cfg)
    if reap_rows:
        body += ("\n### Re-approvals during the run\n\n" + REAPPROVAL_INTRO + "\n\n"
                 "| begun | declarations | reason | involvement | closed |\n|---|---|---|---|---|\n"
                 + "".join("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |\n" for r in reap_rows))
    asm = assumptions(cfg)
    body += "\n## 2. What the formalization assumes\n" + blocks_md(assume_blocks(asm))
    body += render("3. Coverage: what is formalized",
                  f"Every numbered result of the source, every definition or notation the index lists, and the Lean that "
                  f"stands for it: "
                  f"{count_text(index)}, {len(accounted)} of {len(index)} rows accounted for.",
                  index, ["paper", "Lean"])
    if left_rows:
        body += ("\n### Stated in Lean, not proved\n\n" + UNPROVED_MD + "\n\n| declaration | paper | decided by | "
                 "the decision, as logged |\n|---|---|---|---|\n"
                 + "".join("| " + " | ".join(c.replace("|", "\\|") for c in r_) + " |\n" for r_ in left_rows)
                 + "".join(f"\n- pending: {n_}" for n_ in left_notes) + ("\n" if left_notes else ""))
    body += render("4. Not formalized, and why",
                   "Each row says what it would take to lift the skip. A skip is a decision, "
                   "not an omission.", skipped,
                   heads["skipped"] or ["#", "what", "reason", "what it would take", "verified"])
    body += render("5. Defects in the source",
                   defects_intro(heads["defects"], defects) + SEVERITY_MD,
                   # trial #11: a decision cell a [DELEGATED] decision settled since shows that decision (shown
                   # only: the record checks above read the cells as the adjudicator wrote them)
                   settle_defect_rows(cfg, heads["defects"], [list(r_) for r_ in defects]),
                   heads["defects"] or DEFECT_HEADER)
    body += render("6. Where the Lean proof differs",
                   "Where the Lean proof does not follow the paper's argument, and what kind of "
                   "change it is (same strength / paper step fails / Lean intermediate weaker / "
                   "reading choice). " + LIMITS_MD,
                   deviations, heads["deviations"] or ["#", "result", "paper's route", "Lean route", "why", "kind"])
    body += render("7. Statements true only vacuously", VACUOUS_MD, vacuous,
                   heads["vacuous"] or ["#", "statement"])
    # free text recorded below each record's table (updates, corrections): never dropped
    prose = {k: record_after_table(os.path.join(rounds_dir, f), keycol)
             for k, f, keycol in (("skipped", "SKIPPED.md", "what"), ("defects", "PAPER_DEFECTS.md", DEFECT_KEY),
                                  ("deviations", "DEVIATIONS.md", "kind"), ("vacuous", "VACUOUS.md", "statement"))}
    for k, title in (("skipped", "4. Not formalized"), ("defects", "5. Defects in the source"),
                     ("deviations", "6. Where the Lean proof differs"), ("vacuous", "7. Statements true only vacuously")):
        if prose[k]:
            # appended at the end of its section: find the next section heading after it
            i = body.index(f"\n## {title}")
            j = body.find("\n## ", i + 1)
            j = len(body) if j < 0 else j
            body = body[:j] + "\n**Also recorded with this table:**\n\n" + demote_headings(prose[k]) + "\n" + body[j:]

    # READER_NOTES.md: the formalizer's plain-language notes for the human reader (what the human
    # asked to have explained in the report at Checkpoint C); rendered verbatim at the end of section 1 (approver
    # 2026-10-24: the report's sections are eleven, fixed; the notes say how far each record line still holds)
    rn_path = os.path.join(rounds_dir, "READER_NOTES.md")
    reader_notes = ""
    if os.path.exists(rn_path):
        reader_notes = open(rn_path, encoding="utf-8").read()
        reader_notes = re.sub(r"\A\s*# [^\n]*\n", "", reader_notes).strip()
        i_ = body.find("\n## 2. What the formalization assumes")
        i_ = len(body) if i_ < 0 else i_
        body = body[:i_] + "\n### Notes for the reader\n\n" + demote_headings(reader_notes) + "\n" + body[i_:]
    nsec = 8
    defers = cfg.get("standing_defers") or []
    body += f"\n## {nsec}. Open questions and standing defers\n\n" + QUESTIONS_INTRO + "\n\n"
    if questions:
        body += "| round | lane | item | the question |\n|---|---|---|---|\n" + "".join(
            "| " + " | ".join(c.replace("|", "\\|") for c in (rnd, lane, item, (f"({note}) " if note else "") + why))
            + " |\n" for rnd, lane, item, why, note in questions)
    else:
        body += f"_{NO_QUESTION}_\n"
    revotes = open_revotes(cfg)
    body += ("\n" + REVOTES_INTRO + "\n\n")
    if revotes:
        body += "| round | lane | item | status | the adjudicator's reason |\n|---|---|---|---|---|\n" + "".join(
            "| " + " | ".join(c.replace("|", "\\|") for c in (rnd, lane, f"`{it}`", st, why)) + " |\n"
            for rnd, lane, it, why, st in revotes)
    else:
        body += f"_{NO_REVOTE}_\n"
    if defers:
        body += "\n| standing defer | covers | reason | revisit when |\n|---|---|---|---|\n" + "".join(
            "| " + " | ".join(str(d.get(k, "")).replace("|", "\\|") for k in ("id", "item", "reason", "revisit_when"))
            + " |\n" for d in defers)
    else:
        body += f"\n_{NO_DEFER}_\n"
    nsec += 1
    hd, dd = human_decisions(cfg), (delegation(cfg) or (None, None, []))[2]
    esc_items = escalation_items(cfg)
    body += (f"\n## {nsec}. {DECIDED_TITLE}\n\n" + DECIDED_INTRO + "\n\n**Taken by the human:**\n\n"
             + ("".join(f"- {h}\n" for h in hd) if hd else f"- {NONE_RECORDED}\n")
             + "\n**Taken by the operator on your behalf ([DELEGATED], under the involvement level chosen at intake):**\n\n"
             + (delegated_list(cfg, dd) if dd else f"- {NO_DELEGATED}\n")
             + "\n" + escalation_list(esc_items))
    nsec += 1
    # approver (2026-10-24): every stop, the stops cleared without you, set-asides and clearances are the process
    # record (RUN_RECORD.md, run_record.py), not the report
    routes = proof_routes(cfg, deviations, heads["deviations"])
    body += f"\n## {nsec}. {ROUTES_TITLE}\n\n" + ROUTES_INTRO + "\n\n**Results whose paper proof was replaced by a different route:**\n\n"
    body += ("".join(f"- {x}\n" for x in routes["replaced"]) if routes["replaced"] else f"- {NONE_RECORDED}\n")
    body += "\n**Formalized results the goal results do not use:**\n\n" + (
        "".join(f"- {x}\n" for x in routes["unused"]) if routes["unused"] is not None and routes["unused"]
        else f"- {NO_UNUSED}\n" if routes["unused"] is not None
        else f"- Not computed: {routes['why']}\n")
    nsec += 1
    cited = []
    # every code span above, not only the record tables' (trial #7 audit: names cited in the notes, the
    # decisions and the proof routes were missing from a section that says "every Lean name cited above")
    for c in [c for r in index + skipped + defects + deviations + vacuous for c in r] + [body]:
        cited += [t.split("(")[0].strip() for t in re.findall(r"`([^`\n]+)`", c)]
    cited = [t for t in dict.fromkeys(cited) if t in declared]
    # a name cited both bare and qualified is one row (it was listed twice)
    cited = [t for t in cited if "." in t or not any(c.endswith("." + t) for c in cited)]
    where = locate_names(cfg, cited)
    body += (f"\n## {nsec}. Where the Lean names are\n\nEvery Lean name cited above, with its file and "
             "line at this report's commit.\n\n" + ("| name | at |\n|---|---|\n"
             + "".join(f"| `{n}` | `{where[n]}` |\n" for n in sorted(where, key=str.lower)) if where
             else f"_{NONE_RECORDED}_\n"))
    glossary = cfg.get("glossary") or []
    if glossary:
        body += ("\n### Notation\n\nThe source's notation and the Lean names that bundle it.\n\n"
                 "| term | meaning | where |\n|---|---|---|\n" + "".join(
                     "| " + " | ".join(str(g.get(k, "")).replace("|", "\\|") for k in ("term", "meaning", "where"))
                     + " |\n" for g in glossary))
    out = head + body
    if not check_only:
        if REFERENCE is not None:
            # report_md: what the generator writes NOW, in memory; nothing written
            REFERENCE.append({"doc": "REPORT", "md": out})
            return 0
        project.write_draft(rounds_dir, "REPORT.md", out)    # facts/; the agent's REPORT.md never overwritten
        print(f"  REPORT.md draft written ({cfg['rounds_dir']}/{project.FACTS_DIR}/REPORT.md; the rounds directory's "
              f"copy is the main agent's, seeded from it when missing); its PDF is rendered by agents at delivery "
              f"(render_record.py)")
        # B10: the one-page summary, written with the report (Phase 0 and project.py --prepare-delivery)
        try:
            problems += [p_ if isinstance(p_, project.Finding) else "! " + str(p_) for p_ in build_summary(cfg)]
        except Exception as e:      # noqa: BLE001 -- D3: no draft; the agent's SUMMARY.md is never deleted
            sp_ = os.path.join(rounds_dir, project.FACTS_DIR, SUMMARY_MD)
            if os.path.exists(sp_):
                os.remove(sp_)
            problems.append(f"! the summary could not be generated ({type(e).__name__}: {e}): no draft "
                            f"{project.FACTS_DIR}/SUMMARY.md")
        problems, late = project.split(cfg, problems)
        disclosed += late

    print(f"index rows {len(index)}, skipped {len(skipped)}, defects {len(defects)}, "
          f"deviations {len(deviations)}")
    for p in problems:
        # every failure line carries its cause code (stops.causes; a plain string is the report's own)
        print(project.problem_line(p, "report", "FAIL"))
    for p in disclosed:
        print(project.disclosed_line(p))
    for p in held:
        print(pending_line(p))
    for p in record_notes:
        print(" ", p)
    print(f"{'report check FAILED' if problems else 'ok'}: {len(problems)} problem(s)"
          + (f", {len(held)} pending the next adjudication" if held else "")
          + (f", {len(disclosed)} disclosed (release mode: record them with python3 audits/stops.py disclose "
             f"--cmd \"python3 audits/make_report.py --check\")" if disclosed else "")
          + ("" if check_only else f"; wrote {cfg['rounds_dir']}/REPORT.md"))
    return 1 if problems else 0


def _index_controls():
    """The index check (formerly check_index.py's selftest, its mutants C1-C5 now here): [(check, passed)]."""
    import tempfile, shutil, io, contextlib
    global REPO
    keep, tmp = REPO, tempfile.mkdtemp()
    REPO = tmp
    try:
        os.makedirs(os.path.join(tmp, "P")); os.makedirs(os.path.join(tmp, "R"))
        open(os.path.join(tmp, "P", "Src.lean"), "w").write(
            "theorem lemma_1_1 : True := trivial\ndef helper : Nat := 0\n")

        def ix(rows, c=None):
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(
                "/-!\n| Paper | Lean |\n|---|---|\n" + "\n".join(rows) + "\n-/\n")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return index_only(c or cfg)
        cfg = {"lean_files": ["P/Src.lean", "P/Main.lean"], "index_file": "P/Main.lean", "rounds_dir": "R"}
        strict = dict(cfg, index_strict=True)
        checks = [("index: a good index passes", ix(["| Lemma 1.1 | `lemma_1_1` |"]) == 0),
                  ("index: a dangling project name fails, also beside a real one",
                   ix(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.2 | `lemma_1_2` |"]) == 1
                   and ix(["| Lemma 1.1 | `lemma_1_1` `lemma_9_9` |"]) == 1),
                  ("index: a row citing ONLY a non-project name is an empty row (fails)",
                   ix(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.2 | `HasPathCover` |"]) == 1),
                  ("index: legacy mode: a non-project name beside a real one only warns",
                   ix(["| Lemma 1.1 | `lemma_1_1` `HasPathCover` |"]) == 0),
                  ("index: strict mode: a misspelt name beside a real one fails",
                   ix(["| Lemma 1.1 | `lemma_1_1` `HasPathCover` |"], strict) == 1),
                  ("index: strict mode: math in $…$ beside a real name passes",
                   ix(["| Lemma 1.1 | `lemma_1_1` (needs $n \\ge 2$) |"], strict) == 0),
                  ("index: 'not formalized' is not an empty row",
                   ix(["| Lemma 1.1 | `lemma_1_1` |", "| Remark 1.2 | not formalized |"]) == 0),
                  ("index: a numbering gap warns but does not fail",
                   ix(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.3 | `helper` |"]) == 0)]
        open(os.path.join(tmp, "P", "Src.lean"), "a").write("/-\ntheorem hidden_in_comment : True := trivial\n-/\n")
        checks.append(("index: a declaration inside a comment does not count as declared",
                       ix(["| Lemma 1.1 | `lemma_1_1` |", "| Lemma 1.2 | `hidden_in_comment` |"]) == 1))
        dfx = "| # | where | status | repair | says | why | witness | consequence | found |\n|---|---|---|---|---|---|---|---|---|\n"
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(dfx + "| 1 | L1.1 | false | substantial | x | y | `gone_witness` | z | r1 |\n")
        checks.append(("index: a PAPER_DEFECTS witness that no longer exists fails",
                       ix(["| Lemma 1.1 | `lemma_1_1` |"]) == 1))
        # S1 (release trial): every failure line carries a cause code; a dead witness its own
        import stops as _st
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(
            dfx + "| 2 | L1.1 | false | add hypothesis | x | y | `lemma_1_1` is proved; its proof is `sorry` at the round; also "
                  "`probe_witness_q` in a probe | z | r1 |\n")
        open(os.path.join(tmp, "P", "Main.lean"), "w").write(
            "/-!\n| Paper | Lean |\n|---|---|\n| Lemma 1.1 | `lemma_1_1` |\n| Lemma 1.2 | `lemma_1_2` |\n-/\n")
        _b = io.StringIO()
        with contextlib.redirect_stdout(_b), contextlib.redirect_stderr(_b):
            _rc = index_only(cfg)
        _cs = _st.causes(_b.getvalue())
        checks.append(("S1: the index check's failure lines all carry codes: index for the index, dead-witness "
                       "(class record-fix) for each dead witness, sorry included",
                       _rc == 1 and {c["code"] for c in _cs} == {"index", "dead-witness"}
                       and sum(c["code"] == "dead-witness" for c in _cs) == 2
                       and all(c["class"] == "record-fix" for c in _cs if c["code"] == "dead-witness")
                       and "`sorry`" in _b.getvalue()))
        open(os.path.join(tmp, "P", "Main.lean"), "w").write(
            "/-!\n| Paper | Lean |\n|---|---|\n| Lemma 1.1 | `lemma_1_1` |\n-/\n")
        _b = io.StringIO()
        with contextlib.redirect_stdout(_b), contextlib.redirect_stderr(_b):
            index_only(cfg)
        checks.append(("S1: an index check failing only on dead witnesses names no other cause",
                       {c["code"] for c in _st.causes(_b.getvalue())} == {"dead-witness"}))
        _rf = record_faults(cfg)
        checks.append(("S1: record_faults finds both dead witness names of the row, by row and token",
                       sorted((c, f, k, t) for c, f, k, t, _ in _rf if c == "dead-witness")
                       == [("dead-witness", "PAPER_DEFECTS.md", "2", "probe_witness_q"),
                           ("dead-witness", "PAPER_DEFECTS.md", "2", "sorry")]))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| what | why | decided by |\n|---|---|---|\n| Lemma 1.2 | see `lemma_7_7` | adjudicator |\n")
        _rf = record_faults(cfg)
        os.remove(os.path.join(tmp, "R", "SKIPPED.md"))
        checks.append(("S1: record_faults finds a dead name cited in SKIPPED.md (record-cite)",
                       ("record-cite", "SKIPPED.md", "Lemma 1.2", "lemma_7_7") in [x[:4] for x in _rf]))
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(dfx + "| 1 | L1.1 | false | substantial | x | y | `lemma_1_1` | z | r1 |\n")
        checks.append(("index: an existing witness passes", ix(["| Lemma 1.1 | `lemma_1_1` |"]) == 0))
        # trial #10: the refutation `lemma_7_4_b_as_printed_false` got no F10 item (scheduled by `not_<X>_as_printed`
        # only), so the adjudicator could not record its row; Phase 0's index check now refuses it with the rename
        _srcp = os.path.join(tmp, "P", "Src.lean")
        _src = open(_srcp).read()
        _t10 = "theorem {} :\n    ¬ ∀ n : Nat, n = 0 := by\n  sorry\n"
        open(_srcp, "a").write(_t10.format("lemma_7_4_b_as_printed_false"))
        _b = io.StringIO()
        with contextlib.redirect_stdout(_b), contextlib.redirect_stderr(_b):
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(
                "/-!\n| Paper | Lean |\n|---|---|\n| Lemma 1.1 | `lemma_1_1` `lemma_7_4_b_as_printed_false` |\n-/\n")
            _rc10 = index_only(cfg, pending=True)
        _cs10 = _st.causes(_b.getvalue())
        open(_srcp, "w").write(_src + _t10.format("not_lemma_7_4_b_as_printed"))
        _ok10 = ix(["| Lemma 1.1 | `lemma_1_1` `not_lemma_7_4_b_as_printed` |"], None)
        open(_srcp, "w").write(_src)
        checks.append(("trial #10: Phase 0's index check (statement rounds too, --pending) fails on a refutation not "
                       "named `not_<decl>_as_printed`, cause index (the operator's own Lean), naming the exact rename; "
                       "renamed, it passes",
                       _rc10 == 1 and [c["code"] for c in _cs10] == ["index"]
                       and "rename it `not_lemma_7_4_b_as_printed`" in _b.getvalue() and _ok10 == 0))
        checks.append(("trial #10: the rename of each refutation form is `not_<decl>_as_printed`",
                       [refutation_rename(n, t) for n, t in
                        (("lemma_7_4_b_as_printed_false", ""), ("lemma_7_4_b_false", "lemma_7_4_b_statement"),
                         ("refute", "lemma_2_as_printed"), ("counterexample_lemma_4", ""),
                         ("not_lemma_5_as_printed", ""), ("lemma_6_is_false", "Foo"))]
                       == ["not_lemma_7_4_b_as_printed", "not_lemma_7_4_b_as_printed", "not_lemma_2_as_printed",
                           "not_lemma_4_as_printed", "not_lemma_5_as_printed", "not_lemma_6_as_printed"]))
        open(os.path.join(tmp, "P", "Main.lean"), "w").write("/-! no table here -/\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            checks.append(("index: an unparseable table refuses to pass", index_only(cfg) == 2))
        return checks
    finally:
        REPO = keep
        shutil.rmtree(tmp, ignore_errors=True)


def _unproved_controls(cfg, tmp, idx):
    """A non-goal result left unproved by a [DELEGATED] decision (decisions.unproved): the index
    says "not formalized", the adjudicator's SKIPPED.md row carries the tag, the report shows it."""
    import decisions
    checks = []
    tag = "[DELEGATED 2026-10-20, operator under hands-off (intake); reversal: re-prove]"
    src, sk = os.path.join(tmp, "P", "Src.lean"), os.path.join(tmp, "R", "SKIPPED.md")
    src_old = open(src).read()
    import dependencies
    saved = decisions.committed_log, decisions.goal_decls, decisions.adjudicated_since
    saved_aux = dependencies.aux_record
    since = [False]
    auxr = [([], None)]
    dependencies.aux_record = lambda c_, decls, rd=None: auxr[0]
    ch = dict(cfg, involvement="hands-off", involvement_answer="c")
    hdr = "| # | what | reason | what it would take | how this was checked | decided by |\n|---|---|---|---|---|---|\n"
    try:
        open(src, "a").write("theorem lemma_1_2 : True := sorry\n")
        decisions.committed_log = lambda c_: f"## Open questions\n- {tag} leave `lemma_1_2` unproved \u2014 no proof found\n"
        decisions.goal_decls = lambda c_: set()
        decisions.adjudicated_since = lambda c_, needle: since[0]
        if os.path.exists(sk):
            os.remove(sk)
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | `lemma_1_2` (all of it) |"])
        checks.append(("unproved: an index cell still citing it as formalized FAILS", build(ch, True) == 1))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | `lemma_1_2` (stated, not proved: not formalized) |"])
        checks.append(("unproved: before the next adjudication its SKIPPED.md row is pending (passes)",
                       build(ch, True) == 0))
        checks.append(("sweep D2: ... and the adjudication about to be committed must write it (adjudication_findings)",
                       any(p_.code == "adj-record" and "`lemma_1_2`: left unproved, pending" in p_
                           for p_ in adjudication_findings(ch))))
        since[0] = True
        checks.append(("unproved: once a round was adjudicated since the log line, no SKIPPED.md row FAILS",
                       build(ch, True) == 1))
        open(sk, "w").write(hdr + "| 1 | Lemma 1.2 (`lemma_1_2`) | stated in Lean, not proved | a proof | the operator's "
                            "attempt | adjudicator |\n")
        checks.append(("unproved: a SKIPPED.md row whose 'decided by' is not the [DELEGATED] tag FAILS",
                       build(ch, True) == 1))
        open(sk, "w").write(hdr + f"| 1 | Lemma 1.2 (`lemma_1_2`) | stated in Lean, not proved | a proof | the "
                            f"operator's attempt | operator {tag} |\n")
        checks.append(("unproved: index cell + SKIPPED.md row with the tag as 'decided by' passes",
                       build(ch, True) == 0))
        # re-check of Q1 (b), MED-A: the auxiliaries the sweep accepted under its name (the review's
        # metaprogram `lemma_1_2.eq_7`) are listed; not recorded for these lines, the check FAILS
        auxr[0] = (None, "no DEPENDENCIES.json")
        checks.append(("unproved: the auxiliaries the sweep accepts not recorded for the current leave lines FAILS",
                       build(ch, True) == 1))
        auxr[0] = ([("lemma_1_2.eq_7", "lemma_1_2")], None)
        build(ch)
        md = open(os.path.join(tmp, "R", "REPORT.md"), encoding="utf-8").read()
        checks.append(("B7 review 1: the report lists the escalation checks (none written here)",
                       "**Escalation checks.**" in md and "- None written." in md))
        checks.append(("PDF-AGENTS: the build writes REPORT.md only (no .tex, no PDF: agents render it)",
                       not any(os.path.exists(os.path.join(tmp, "R", f_)) for f_ in ("REPORT.tex", "REPORT.pdf",
                                                                                      "SUMMARY.tex", "SUMMARY.pdf"))))
        checks.append(("unproved: the report's coverage section says 'stated, not proved' and "
                       "the summary 'stated only', with the tag (B10: the page-1 box moved to the summary)",
                       "### Stated in Lean, not proved" in md
                       and "- stated only " in open(os.path.join(tmp, "R", SUMMARY_MD)).read()
                       and "`lemma_1_2`" in open(os.path.join(tmp, "R", SUMMARY_MD)).read()
                       and tag in open(os.path.join(tmp, "R", SUMMARY_MD)).read()))
        sec = (md.split("### Stated in Lean, not proved", 1) + [""])[1].split("## 4.")[0]
        checks.append(("unproved: every auxiliary the sweep accepted under an exempt name is listed there with "
                       "its parent and the parent's tag",
                       "| `lemma_1_2.eq_7` | (an auxiliary of `lemma_1_2`) | " + tag in sec))
        decisions.committed_log = lambda c_: f"## Open questions\n- {tag} leave `lemma_1_2` unproved \u2014 x\n"
        checks.append(("unproved: under the involved level the line exempts nothing (no rows)",
                       unproved_problems(cfg, [], [], [], {"lemma_1_2"})[2] == []
                       and unproved_problems(ch, [], [], [], {"lemma_1_2"})[2] != []))
        # the index cites it unqualified (`lemma_1_3`), the log by its full name (`P.lemma_1_3`):
        # resolved as the dependency walk resolves it (namespace ++ name), the cell rule still applies
        since[0] = False
        os.remove(sk)
        open(src, "a").write("namespace P\ntheorem lemma_1_3 : True := sorry\nend P\n")
        decisions.committed_log = lambda c_: f"## Open questions\n- {tag} leave `P.lemma_1_3` unproved \u2014 x\n"
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | `lemma_1_2` |", "| Lemma 1.3 | `lemma_1_3` |"])
        checks.append(("unproved: an index cell citing it by its short name as formalized FAILS (names resolved "
                       "as written, then namespace ++ name)", build(ch, True) == 1))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | `lemma_1_2` |",
             "| Lemma 1.3 | `lemma_1_3` (stated, not proved: not formalized) |"])
        checks.append(("unproved: ... and its short-name cell saying 'not formalized' passes (pending)",
                       build(ch, True) == 0))
    finally:
        decisions.committed_log, decisions.goal_decls, decisions.adjudicated_since = saved
        dependencies.aux_record = saved_aux
        open(src, "w").write(src_old)
        for f_ in ("SKIPPED.md", "REPORT.md"):
            if os.path.exists(os.path.join(tmp, "R", f_)):
                os.remove(os.path.join(tmp, "R", f_))
    return checks


def _section_kinds_checks():
    """trial #9: section 2 (B5/B6) and every empty-section text, from one source (assume_blocks, blocks_md), for each
    kind -- none recorded, hypotheses, added since the approval, missing theory, NOT COMPUTED."""
    kinds = {
        "none recorded": {"rows": [], "why": "", "notes": ["Hypotheses added since the approval: none."]},
        "hypotheses": {"rows": [["`HypA`", "literature hypothesis", "the paper's (2.3); matches source: yes",
                                 "every A is bounded", "`thm_a`: (h : HypA)"]], "why": "", "notes": []},
        "added since the approval": {"rows": [["`HypB`", "unclassified", "PENDING: no valid hypothesis row yet",
                                               "-", "`thm_b`: (h : HypB n)"]], "why": "",
                                     "notes": ["Hypotheses added since the approval: `thm_b`: (h : HypB n)."]},
        "missing theory": {"rows": [["`HypC`", "missing theory", "Theorem 4 of [7]; matches source: source "
                                     "unavailable", "C holds for all n", "`thm_c`: (h : HypC)"]], "why": "",
                           "notes": ["Missing theory: `HypC` is assumed for `thm_c`; the paper invokes it: \u201cby "
                                     "[7, Thm 4], C holds\u201d (searched: Mathlib).",
                                     "Hypotheses added since the approval: not computed (no approval yet, or the "
                                     "approval recorded no binders: made before approvals recorded them, or without "
                                     "a current walk)."]},
        "NOT COMPUTED": {"rows": [], "why": "no DEPENDENCIES.json (run dependencies.py --write)", "notes": []},
    }
    out = []
    for name, asm in kinds.items():
        bl = assume_blocks(asm)
        md = "# Formalization report\n\n## 2. What the formalization assumes\n" + blocks_md(bl)
        texts = [b[1] for b in bl if b[0] in ("p", "none")] + [c for b in bl if b[0] == "table" for r in b[2] for c in r]
        same = (all(t_ in md for t_ in texts) and "(none recorded)" not in md
                and (ASSUME_NONE in md) == (not asm["rows"] and not asm["why"])
                and all(n_ in md for n_ in asm["notes"]))
        out.append((f"trial #9: section 2 ({name}) prints every text of its blocks, the none line only when there is "
                    f"nothing", same))
    return out


def selftest():
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    global REPO
    keep = REPO
    try:
        REPO = tmp
        os.makedirs(os.path.join(tmp, "P")); os.makedirs(os.path.join(tmp, "R", "f10"))
        # F10: the fresh paper-faithfulness lane confirming a `false` row's counterexample (cited by the fixtures)
        json.dump({"lane": "paper-faithfulness", "verdicts": [{"item": "F10 counterexample", "verdict": "Pass"},
                                                              {"item": "F12: the repair of Lemma 2", "verdict": "Pass",
                                                               "comment": "used in step 2 of the paper's proof"}]},
                  open(os.path.join(tmp, "R", "f10", "paper-faithfulness.json"), "w"))
        open(os.path.join(tmp, "P", "Src.lean"), "w").write("theorem thm_1_1 : True := trivial\n")
        cfg = {"name": "t", "source_cite": "src", "branch": "b", "namespace": "P",
               "rounds_dir": "R", "lean_files": ["P/Src.lean", "P/Main.lean"],
               "index_file": "P/Main.lean"}

        def idx(rows):
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(
                "/-!\n| Paper | Lean |\n|---|---|\n" + "\n".join(rows) + "\n-/\n")

        checks = _index_controls()
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 7.4 | `lemma_7_4` |"])
        # mini2 audit: the delegated decisions on one matter are one entry of section 9
        _tg = "[DELEGATED 2026-10-21, operator under hands-off (intake); reversal: re-approve] "
        open(os.path.join(tmp, "R", "RUN_LOG.md"), "w").write(
            "# Run log\n## Checkpoint C\n- check:Lemma_7.4: " + _tg + "approve the restated form MQZ1\n"
            "- question:P.lemma_7_4: " + _tg + "keep hN MQZ2\n- unused:P.lemma_7_4@ab12: " + _tg + "keep hN, idle MQZ3\n"
            "- question:P.witness_x: " + _tg + "keep the witness MQZ4\n")
        import decisions as _dcm
        _dd = _dcm.delegated_decisions(open(os.path.join(tmp, "R", "RUN_LOG.md")).read())
        _pr, project.REPO = project.REPO, tmp
        try:
            _di, _nm = delegated_items(cfg, _dd), n_matters(cfg, _dd)
        finally:
            project.REPO = _pr
        checks.append(("mini2-2: the report lists the delegated decisions on one matter (CHECK row, QUESTION, unused "
                       "hypothesis of Lemma 7.4) as ONE entry, and counts matters",
                       len(_dd) == 4 and len(_di) == 2 and _di[0].startswith("**Lemma 7.4** (3 decisions")
                       and all(x in _di[0] for x in ("MQZ1", "MQZ2", "MQZ3")) and "MQZ4" in _di[1]
                       and _nm == 2))
        os.remove(os.path.join(tmp, "R", "RUN_LOG.md"))
        idx(["| Theorem 1.1 | `thm_1_1` |"])
        open(os.path.join(tmp, "P", "Src.lean"), "a").write("\n-- pad\n" * 6)
        _cl = rendering_problems(cfg, [], [], [], clearances=[("2026-01-01-abc1234", "substantiveness.json",
                                                                "cleared: `thm_1_1` at Src.lean:6 is fine")])
        _qn = rendering_problems(cfg, [], [], [], questions=[("2026-01-01-abc1234", "correspondence", "thm_1_1",
                                                              "is `thm_1_1` at Src.lean:6 meant?", 1)])
        checks.append(("a stale File.lean:N the report could not resolve in a QUESTION row is a NOTE",
                       any(p_.startswith("NOTE QUESTION row on thm_1_1") for p_ in _qn)))
        checks.append(("mini2-4: a stale File.lean:N in an independence clearance is a stale-line NOTE",
                       any(p_.startswith("NOTE clearance of substantiveness.json (round 2026-01-01-abc1234)")
                           and "declared at line 1" in p_ for p_ in _cl)))
        _rf = {"P/Src.lean": "-- a\n-- b\n-- c\n-- d\ntheorem thm_1_1 : True := trivial\n"}
        refresh_lines.count = 0
        _r1 = refresh_lines("`thm_1_1` at `Src.lean:1` is vacuous; see Src.lean:5", cfg, _rf)
        _r2 = refresh_lines("`gone` at Src.lean:1; `thm_1_1` at Src.lean:1, :3", cfg, _rf)
        checks.append(("mini2-B(d): a record's `name` at File.lean:N is rendered at the line where the name is "
                       "declared now; an unresolvable or continued citation is left as written",
                       _r1 == "`thm_1_1` at `Src.lean:5` is vacuous; see Src.lean:5" and refresh_lines.count == 1
                       and _r2 == "`gone` at Src.lean:1; `thm_1_1` at Src.lean:1, :3"))
        # review of fix-mini2 M3 (attack4): a commented-out declaration, or the same short name in
        # another namespace, is not where a cited name is declared; L1: the line is the keyword's
        _pad = "\n" * 20
        _rf3 = {"P/L.lean": "namespace A\n" + _pad + "/- removed, kept for reference:\ntheorem lemma_7_5_c (a b : Int) : "
                "True := trivial\n-/\n" + _pad + "end A\nnamespace B\n" + _pad + "theorem helper : True := trivial\n"
                "end B\nnamespace C\n\n\n\ntheorem gap : True := trivial\n\n\n\n\ntheorem two : True := trivial\nend C\n"}
        _m3 = [refresh_lines(c_, cfg, _rf3) for c_ in ("`A.lemma_7_5_c` at `L.lean:3` is vacuous",
                                                         "`A.helper` at `L.lean:5` is used", "`B.helper` at `L.lean:5` is used",
                                                         "`C.two` at `L.lean:1`")]
        _gap = [l_ for n_, l_ in declarations(_rf3["P/L.lean"]) if n_ == "C.gap"]
        checks.append(("review of fix-mini2 M3: a cited name is not re-pointed at a commented-out declaration or at "
                       "another namespace's declaration of the same short name (the stale line stays for the scan); "
                       "the full name is matched; L1: the line is the keyword's, not a blank line before it",
                       _m3[0] == "`A.lemma_7_5_c` at `L.lean:3` is vacuous" and _m3[1] == "`A.helper` at `L.lean:5` is used"
                       and _m3[2] == "`B.helper` at `L.lean:67` is used"
                       and _gap == [_rf3["P/L.lean"].splitlines().index("theorem gap : True := trivial") + 1]
                       and _m3[3] == f"`C.two` at `L.lean:{_rf3['P/L.lean'].splitlines().index('theorem two : True := trivial') + 1}`"))
        refresh_lines.count = 0
        _cal = project.changes_after_last_audit
        try:
            project.changes_after_last_audit = lambda c_, r_: {"round": "r", "commit": "c", "problem": None,
                                                               "commits": ["abc1234 docstring"], "dirty": [],
                                                               "comment_only": True}
            _lr1 = later_row(cfg)[2]
            project.changes_after_last_audit = lambda c_, r_: {"round": "r", "commit": "c", "problem": None,
                                                               "commits": ["abc1234 docstring"], "dirty": [],
                                                               "comment_only": False}
            _lr2 = later_row(cfg)[2]
        finally:
            project.changes_after_last_audit = _cal
        checks.append(("mini2-B(c): a change after the last round verified comment-only is reported as such; any "
                       "other is NOT re-audited",
                       "ONLY comments and docstrings" in _lr1 and "NOT re-audited" not in _lr1
                       and "NOT re-audited" in _lr2))
        open(os.path.join(tmp, "P", "Src.lean"), "w").write("theorem thm_1_1 : True := trivial\n")
        checks.append(("a fully covered index passes", build(cfg, True) == 0))
        _dfx = ("| # | where | status | repair | says | why | witness | consequence | found |\n"
                "|---|---|---|---|---|---|---|---|---|\n| 1 | Theorem 1.1 | false | substantial | x | y; counterexample: n = 3; F10: f10/paper-faithfulness.json | `{}` | z | r1 |\n")
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(_dfx.format("gone_witness"))
        _bd = __import__("io").StringIO()
        with __import__("contextlib").redirect_stdout(_bd):
            _dead = build(cfg, True)
        import stops as _st2
        checks.append(("S1: the report check prints each blocking problem with a cause code (dead-witness for a "
                       "dead witness), and no uncoded failure line",
                       any(c["code"] == "dead-witness" for c in _st2.causes(_bd.getvalue()))
                       and not [c for c in _st2.causes(_bd.getvalue()) if c["code"] == "unknown"]))
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(_dfx.format("thm_1_1"))
        _alive = build(cfg, True)
        os.remove(os.path.join(tmp, "R", "PAPER_DEFECTS.md"))
        checks.append(("report --check: a dead PAPER_DEFECTS witness FAILS, a live one does not",
                       (_dead, _alive) == (1, 0)))
        idx(["| Theorem 1.1 | `thm_1_1` `HasX` |"])
        checks.append(("report --check: index_strict FAILS a backticked non-declaration (legacy mode passes)",
                       build(dict(cfg, index_strict=True), True) == 1 and build(cfg, True) == 0))
        idx(["| Theorem 1.1 | `thm_1_1` |"])
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | not formalized |"])
        checks.append(("an unexplained skip FAILS", build(cfg, True) == 1))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Lemma 1.2 | needs a long construction |\n")
        checks.append(("the same skip passes once SKIPPED.md explains it", build(cfg, True) == 0))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Lemma 1.2 | needs $n\\le m$ over \\mathbb{N}_0 |\n")
        checks.append(("LaTeX in an adjudicator record is set as code, not a failure (stop S3)",
                       build(cfg, True) == 0 and codeify_latex("$n\\le m$ over \\mathbb{N}_0, `\\in` kept")
                       == "`n\\le m` over `\\mathbb{N}_0`, `\\in` kept"))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Lemma 1.2 | needs a long construction |\n")
        # release mode (project.RELEASE): LaTeX in the operator's DEVIATIONS.md is a rendering fault,
        # disclosed in release and a failure in dev; an unexplained skip fails in both (S3-like)
        import io, contextlib
        open(os.path.join(tmp, "R", "DEVIATIONS.md"), "w").write(
            "| # | result | the paper's route | the lean route | why different | kind |\n|---|---|---|---|---|---|\n"
            "| R1 | Theorem 1.1 | uses $\\alpha$ | x | y | same strength |\n")

        def B(c):
            with contextlib.redirect_stdout(io.StringIO()) as o_:
                rc_ = build(c, True)
            return rc_, o_.getvalue()
        rc_rel, out_rel = B(dict(cfg, mode="release"))
        rc_dev, out_dev = B(dict(cfg, mode="dev"))
        rc_no, _ = B(cfg)
        checks.append(("release mode: LaTeX in DEVIATIONS.md is DISCLOSED[render] and passes; dev and no mode FAIL",
                       rc_rel == 0 and "DISCLOSED[render]" in out_rel and " disclosed (release mode" in out_rel
                       and rc_dev == 1 and "DISCLOSED" not in out_dev and rc_no == 1))
        with contextlib.redirect_stdout(io.StringIO()):
            build(dict(cfg, mode="release"))
        rmd = open(os.path.join(tmp, "R", "REPORT.md"), encoding="utf-8").read()
        checks.append(("release mode (approver 2026-10-24): a disclosed presentation fault is not in the report (its D "
                       "record is in RUN_RECORD.md); the Run mode row says RELEASE and points there",
                       "Known faults, disclosed" not in rmd and "DISCLOSED[render] DEVIATIONS.md row R1" not in rmd
                       and re.search(r"\| Run mode \|[^\n]*RELEASE[^\n]*RUN_RECORD\.md", rmd) is not None
                       and "VERIFICATION FAILED" not in rmd))
        # trial #7 audit: a name cited only in prose (here the reader notes) is in "Where the Lean names are"
        _src_q = open(os.path.join(tmp, "P", "Src.lean")).read()
        open(os.path.join(tmp, "P", "Src.lean"), "a").write("\ntheorem extra_qz : True := trivial\n")
        open(os.path.join(tmp, "R", "READER_NOTES.md"), "w").write("# Notes\n\nThe example is `extra_qz`.\n")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                build(dict(cfg, mode="release"))
            rmq = open(os.path.join(tmp, "R", "REPORT.md"), encoding="utf-8").read()
        finally:
            open(os.path.join(tmp, "P", "Src.lean"), "w").write(_src_q)
            os.remove(os.path.join(tmp, "R", "READER_NOTES.md"))
        checks.append(("trial #7: 'Where the Lean names are' lists every Lean name cited above it, also one cited "
                       "only in prose",
                       "| `extra_qz` | `P/Src.lean:" in rmq.split("Where the Lean names are", 1)[-1]))
        checks.append(("approver 2026-10-24: with reader notes the report still has its eleven sections; the notes end "
                       "section 1, before section 2",
                       re.findall(r"(?m)^## (\d+)\. ", rmq) == [str(i) for i in range(1, 12)]
                       and -1 < rmq.find("### Notes for the reader") < rmq.find("## 2. What the formalization assumes")))
        with contextlib.redirect_stdout(io.StringIO()):
            build(dict(cfg, mode="release"))
        sc_ = os.path.join(tmp, "R", "stops", "S1")
        os.makedirs(sc_)
        json.dump({"stop": "S1", "date": "2026-10-21", "command": "python3 audits/integrity.py --check", "exit": 1,
                   "causes": [{"code": "seal-mismatch", "class": "tamper", "line": "FAIL[seal-mismatch] x"}]},
                  open(os.path.join(sc_, "STOP.json"), "w"))
        json.dump({"stop": "S1", "by": "cure", "mode": "release", "attempt": 2, "budget": 2, "cures": ["set-aside"],
                   "text": "set the round aside; a fresh round re-ran it", "rerun": {"exit": 0, "passes": True}},
                  open(os.path.join(sc_, "CLOSED.json"), "w"))
        saved_repo, project.REPO = project.REPO, tmp      # stops.py reads the record under project.REPO
        try:
            mr_ = mode_row(dict(cfg, mode="release"))[2]
        finally:
            project.REPO = saved_repo
            shutil.rmtree(os.path.join(tmp, "R", "stops"))
        checks.append(("approver 2026-10-24 (RUN_RECORD): the trust table's Run mode row names no self-cured stop (the "
                       "process record is RUN_RECORD.md, which it points to)",
                       "SELF-CURED" not in mr_ and "S1" not in mr_ and "fresh round re-ran it" not in mr_
                       and "RUN_RECORD.md" in mr_))
        os.makedirs(sc_)
        json.dump({"stop": "S1", "date": "2026-10-21", "command": "python3 audits/make_report.py --check", "exit": 1,
                   "causes": [{"code": "adj-record", "class": "adjudication", "line": "FAIL[adj-record] x"}]},
                  open(os.path.join(sc_, "STOP.json"), "w"))
        json.dump({"stop": "S1", "by": "cure", "mode": "release", "attempt": 1, "budget": 2, "cures": ["rerun"],
                   "text": "renamed and re-ran", "rerun": {"exit": 0, "passes": True}},
                  open(os.path.join(sc_, "CLOSED.json"), "w"))
        saved_repo, project.REPO = project.REPO, tmp
        try:
            mr2_ = mode_row(dict(cfg, mode="release"))[2]
        finally:
            project.REPO = saved_repo
            shutil.rmtree(os.path.join(tmp, "R", "stops"))
        checks.append(("trial #10 audit: a rerun self-cure's Run mode row never says independence was compromised (it "
                       "names no self-cure at all now)",
                       "renamed and re-ran" not in mr2_ and "compromised" not in mr2_))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.3 | not formalized |"])
        rc_rel, out_rel = B(dict(cfg, mode="release"))
        checks.append(("release mode: an unexplained skip (faithfulness) still FAILS, the LaTeX beside it is disclosed",
                       rc_rel == 1 and "Lemma 1.3: not formalized by the index" in out_rel
                       and "DISCLOSED[render]" in out_rel))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | not formalized |"])
        open(os.path.join(tmp, "R", "DEVIATIONS.md"), "w").write(
            "| # | result | the paper's route | the lean route | why different | kind |\n|---|---|---|---|---|---|\n"
            "| R1 | Theorem 1.1 | x | via `thm_gone` (Src.lean:1) | y | same strength |\n")
        rc_rel, out_rel = B(dict(cfg, mode="release"))
        checks.append(("review M2: a record citing a Lean name declared in no project file FAILS in release too",
                       rc_rel == 1 and "declared in no project file" in out_rel
                       and "DISCLOSED[render] DEVIATIONS.md row R1: `thm_gone`" not in out_rel))
        # L-inf run (stop S3): the adjudicator's DEVIATIONS.md row 4 cites two local binders of a proof (`hR4`,
        # `hB1`) at their lines; a short unqualified name no file declares, held by the cited file, is a local name.
        # A qualified name declared nowhere still fails: report in the operator's DEVIATIONS.md, record-cite
        # (cured by a record correction, which record_faults feeds) in the adjudicator's
        _src_l = open(os.path.join(tmp, "P", "Src.lean")).read()
        open(os.path.join(tmp, "P", "Src.lean"), "w").write(
            "theorem thm_1_1 : True := by\n  have hR4 : True := trivial\n  have hB1 : True := trivial\n  exact hR4\n")
        _dvh = ("| # | result | the paper's route | the lean route | why different | kind |\n|---|---|---|---|---|---|\n"
                "| 4 | Theorem 1.1 | x | P half `hR4` Src.lean:2; B half `hB1` Src.lean:3; `exact` at `hR4` Src.lean:4 | y "
                "| same strength |\n")
        _dvq = _dvh.replace("`hR4` Src.lean:4", "`P.Gone.thm_gone` Src.lean:4")
        _pin_l = os.path.join(tmp, "R", "TOOLING_PIN.json")
        _local = {}
        for _own in (None, 3):
            if _own:
                json.dump({"ownership": _own}, open(_pin_l, "w"))
            for _k, _d in (("local", _dvh), ("qualified", _dvq)):
                open(os.path.join(tmp, "R", "DEVIATIONS.md"), "w").write(_d)
                _rc_l, _out_l = B(dict(cfg, mode="release"))
                _local[_own, _k] = (_rc_l, _out_l, record_faults(cfg))
            if _own:
                os.remove(_pin_l)
        open(os.path.join(tmp, "P", "Src.lean"), "w").write(_src_l)
        checks.append(("L-inf S3: a record citing local binders (`hR4`, `hB1`) at their lines passes in both "
                       "ownerships (the file holds them; no record-fix fault)",
                       all(_local[o_, "local"][0] == 0 and "hR4" not in _local[o_, "local"][1]
                           and "hB1" not in _local[o_, "local"][1]
                           and not _local[o_, "local"][2] for o_ in (None, 3))))
        import stops as _st_l
        _cq = {o_: {c["code"] for c in _st_l.causes(_local[o_, "qualified"][1]) if "thm_gone" in c.get("line", "")}
               for o_ in (None, 3)}
        checks.append(("L-inf S3: a qualified name declared nowhere still FAILS: report in the operator's "
                       "DEVIATIONS.md, record-cite (class record-fix, a record correction's fault) in the adjudicator's",
                       _local[None, "qualified"][0] == 1 and _cq[None] == {"report"}
                       and not _local[None, "qualified"][2]
                       and _local[3, "qualified"][0] == 1 and _cq[3] == {"record-cite"}
                       and [x[:4] for x in _local[3, "qualified"][2]]
                       == [("record-cite", "DEVIATIONS.md", "4", "P.Gone.thm_gone")]))
        os.remove(os.path.join(tmp, "R", "DEVIATIONS.md"))
        _dfx2 = ("| # | where | status | repair | says | why | witness | consequence | found |\n"
                 "|---|---|---|---|---|---|---|---|---|\n| 1 | Theorem 1.1 | false | substantial | x has |V| = 2 | y | `gone_witness` | z | r1 |\n")
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(_dfx2)
        rc_rel, out_rel = B(dict(cfg, mode="release"))
        with contextlib.redirect_stdout(io.StringIO()) as o_:
            rc_pd = build(dict(cfg, mode="release"), True, pending_ok=True)
        _af = adjudication_findings(cfg)
        open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(_dfx2.replace("|V|", "V"))
        with contextlib.redirect_stdout(io.StringIO()) as o_ix:
            rc_ix = index_only(cfg, pending=True)
        os.remove(os.path.join(tmp, "R", "PAPER_DEFECTS.md"))
        checks.append(("sweep D2: an adjudicator-owned record fault (a stray | in a cell; a dead witness) is a "
                       "PENDING[adjudication] NOTE under --pending (Phase 0's report and index steps), never a failure "
                       "line; without it, it FAILS as adj-record; adjudication_findings (the adjudication commit) "
                       "lists it",
                       rc_pd == 0 and "PENDING[adjudication] adj-record: PAPER_DEFECTS.md row 1: 11 cells" in o_.getvalue()
                       and "FAIL[" not in o_.getvalue() and "FAIL[adj-record] PAPER_DEFECTS.md row 1" in out_rel
                       and rc_ix == 0 and "PENDING[adjudication] dead-witness: PAPER_DEFECTS.md row 1" in o_ix.getvalue()
                       and "FAIL[" not in o_ix.getvalue()
                       and any(p_.code == "adj-record" and "11 cells" in p_ for p_ in _af)))
        import stops as _sx
        _cpx = _sx.carried_problems
        try:
            _sx.carried_problems = lambda rds, rn=None, audits=None, revotes=None: [f"QZITEM (adjudicating {rn})"]
            _rpx = record_problems(os.path.join(tmp, "R"), "RX")
            _afx = adjudication_findings(cfg, "RX")
        finally:
            _sx.carried_problems = _cpx
        checks.append(("sweep D1: a carried item without its row is adj-record (PENDING in Phase 0), and the "
                       "adjudication about to be committed is checked with its own ADOPTED.md (round_name)",
                       any(getattr(p_, "code", None) == "adj-record" and "QZITEM (adjudicating RX)" in p_ for p_ in _rpx)
                       and any("QZITEM (adjudicating RX)" in p_ for p_ in _afx)))
        checks.append(("review H4: a PAPER_DEFECTS row whose cells are shifted (a stray |) FAILS in release: its dead "
                       "witness is not read", rc_rel == 1 and "cells under a 9-column header" in out_rel))
        # must match the project convention (name_<digit>) to be a hard failure; `thm_gone`
        # does not, and using it made this control stop testing anything the moment the filter
        # was tightened.
        idx(["| Theorem 1.1 | `thm_1_1`, `thm_9_9` |"])
        checks.append(("a cited name that does not exist FAILS", build(cfg, True) == 1))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.3 | not formalized |"])
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Lemma 1.31 | other |\n")
        checks.append(("a SKIPPED row for Lemma 1.31 does not explain Lemma 1.3", build(cfg, True) == 1))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | `v(G) ≥ 2` |"])
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write("| # | what | reason |\n|---|---|---|\n")
        checks.append(("backticked math is not a formalization (unexplained -> FAILS)", build(cfg, True) == 1))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | not formalized (compare `thm_1_1`) |"])
        checks.append(("'not formalized' with a real name cited is still not formalized (unexplained -> FAILS)",
                       build(cfg, True) == 1))
        idx(["| Theorem 1.1 | `thm_1_1` |"])
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Theorem 1.1 | too hard |\n")
        checks.append(("formalized AND skipped is a contradiction (FAILS)", build(cfg, True) == 1))
        # re-check N3: a defect confirmed by argument without a Lean witness is a row, passes the check and is
        # disclosed in section 5 and the box, never dropped
        pd3 = os.path.join(tmp, "R", "PAPER_DEFECTS.md"); pd3_o = open(pd3).read() if os.path.exists(pd3) else None
        sk3 = os.path.join(tmp, "R", "SKIPPED.md"); sk3_o = open(sk3).read()
        open(sk3, "w").write("| # | what | reason |\n|---|---|---|\n")
        open(pd3, "w").write("| # | where | status | repair | what the paper says | why it is wrong | Lean witness | consequence "
                             "|\n|---|---|---|---|---|---|---|---|\n| 1 | tex 9 | false | substantial | N3-PRINTED | N3-WHY; counterexample: n = 3; F10: f10/paper-faithfulness.json | none: confirmed by "
                             "argument (ADOPTED.md, round r) | survives |\n")
        saved_pr3 = project.REPO; project.REPO = tmp     # the box is decisions.box_lines' (project.REPO)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc3 = build(cfg, True)
                build(cfg, False)
        finally:
            project.REPO = saved_pr3
        md3 = open(os.path.join(tmp, "R", "REPORT.md")).read()
        open(sk3, "w").write(sk3_o)
        if pd3_o is None:
            os.remove(pd3)
        else:
            open(pd3, "w").write(pd3_o)
        sm3 = open(os.path.join(tmp, "R", SUMMARY_MD)).read() if os.path.exists(os.path.join(tmp, "R", SUMMARY_MD)) else ""
        checks.append(("N3: a defect with no Lean witness passes the check and is disclosed in section 5 and the "
                       "summary (B10: the page-1 box moved there)",
                       rc3 == 0 and "N3-PRINTED" in md3 and "except defect 1: confirmed by argument only" in md3
                       and "- defect 1 — " in sm3 and "(no Lean witness: confirmed by argument only)" in sm3))
        # B3 (U2 §1 "Defect rows"): status + repair, `false` first; an old-format table, an unknown value or an
        # S-number is PENDING[adj-record]; the witness is the 7th cell
        pd3_o = open(pd3).read() if os.path.exists(pd3) else None
        open(sk3, "w").write("| # | what | reason |\n|---|---|---|\n")
        b3h = ("## Defects\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
               "consequence |\n|---|---|---|---|---|---|---|---|\n")
        b3_none = "none: confirmed by argument (ADOPTED.md, round r)"
        b3_ok = (b3h + f"| 1 | tex 5 B3-MISPRINT | misprint (true as intended) | typo | a | b | {b3_none} | c |\n"
                 f"| 2 | tex 7 B3-UNSUP | unsupported | not repaired | a | b | {b3_none} | c |\n"
                 f"| 3 | Lemma 2, tex 9 B3-FALSE | **false** | add hypothesis | a | b; counterexample: n = 3; F10: f10/paper-faithfulness.json; F12: f10/paper-faithfulness.json | {b3_none} | c |\n")
        b3_out = {}
        saved_pr3 = project.REPO; project.REPO = tmp
        try:
            for tag_, txt_ in (("ok", b3_ok),
                               ("old", "## Defects\n| # | where | severity | what the paper says | why it is wrong | "
                                       f"Lean witness | consequence |\n|---|---|---|---|---|---|---|\n| 1 | tex 9 | S1 | a | b "
                                       f"| {b3_none} | c |\n"),
                               ("misprint", b3_ok.replace("| misprint (true as intended) | typo |", "| misprint? | typo |")),
                               ("snum", b3_ok.replace("| **false** | add hypothesis |", "| S1 | add hypothesis |")),
                               ("repair", b3_ok.replace("| unsupported | not repaired |", "| unsupported | S3 |")),
                               # B3 attack fixes: the whole `## Defects` section is parsed, nothing dropped silently
                               ("blank", b3_ok.replace("| 3 | Lemma 2, tex 9", "\n| 3 | Lemma 2, tex 9")),
                               ("comment", b3_ok.replace("| 3 | Lemma 2, tex 9", "<!-- a note -->\n| 3 | Lemma 2, tex 9")),
                               ("text", b3_ok.replace("| 3 | Lemma 2, tex 9", "A note on the next row.\n| 3 | Lemma 2, tex 9")),
                               ("twohead", b3_ok + "\n## Defects\n" + b3h.split("\n", 1)[1]
                                + f"| 4 | tex 11 B3-SECOND | unsupported | local | a | b | {b3_none} | c |\n"),
                               ("dupcol", b3_ok.replace("| Lean witness | consequence |", "| Lean witness | status |")),
                               ("dupnum", b3_ok.replace("| 2 | tex 7", "| 1 | tex 7")),
                               ("nocx", b3_ok.replace("; counterexample: n = 3", ""))):
                open(pd3, "w").write(txt_)
                o_b3 = io.StringIO()
                with contextlib.redirect_stdout(o_b3):
                    rc_b3 = build(cfg, True)
                    rcp_b3 = build(cfg, True, pending_ok=True)
                    if tag_ == "ok":
                        b3_full = io.StringIO()
                        with contextlib.redirect_stdout(b3_full):
                            b3_full_rc = build(cfg, False)
                b3_out[tag_] = (rc_b3, rcp_b3, o_b3.getvalue(), [str(p_) for p_ in adjudication_findings(cfg)
                                                                  if p_.code == "adj-record"],
                                [r_[0] for r_ in record_table(pd3, DEFECT_KEY)[1]],
                                "\n".join(map(str, __import__("decisions").box_lines(cfg))))
                if tag_ == "ok":
                    b3_md = open(os.path.join(tmp, "R", "REPORT.md")).read()
        finally:
            project.REPO = saved_pr3
        open(sk3, "w").write(sk3_o)
        if pd3_o is None:
            os.remove(pd3)
        else:
            open(pd3, "w").write(pd3_o)
        s5_ = b3_md[b3_md.find("## 5."):]
        checks.append(("B3: a status/repair defects table passes and section 5 lists `false` first, then unsupported, "
                       "then misprint, with the status/repair legend (no S1-S4)",
                       b3_out["ok"][0] == 0 and s5_.find("B3-FALSE") < s5_.find("B3-UNSUP") < s5_.find("B3-MISPRINT")
                       and s5_.find("B3-FALSE") > 0 and "Each defect has a *status*" in s5_ and "S1" not in s5_
                       and not b3_out["ok"][3]))
        checks.append(("B3: the full build of a defects row citing long record paths passes",
                       b3_full_rc == 0 and "FAIL[" not in b3_full.getvalue()))
        checks.append(("B3: an old-format (`severity`) defects table is PENDING[adj-record]: the adjudicator rewrites it",
                       b3_out["old"][0] == 1 and b3_out["old"][1] == 0
                       and "PENDING[adjudication] adj-record: PAPER_DEFECTS.md: the defects table has the old `severity`"
                       in b3_out["old"][2] and any("old `severity`" in x for x in b3_out["old"][3])))
        checks.append(("B3: an unclassifiable misprint status (`misprint?`) is PENDING[adj-record]",
                       b3_out["misprint"][0] == 1 and b3_out["misprint"][1] == 0
                       and any("status 'misprint?' is not one of" in x for x in b3_out["misprint"][3])))
        checks.append(("B3: no S-number alias: `S1` as a status, `S3` as a repair are PENDING[adj-record]",
                       any("status 'S1' is not one of" in x and "S-number" in x for x in b3_out["snum"][3])
                       and any("repair 'S3' is not one of" in x for x in b3_out["repair"][3])
                       and b3_out["snum"][0] == 1 and b3_out["repair"][0] == 1))
        _b3w = os.path.join(tmp, "b3w.md")
        open(_b3w, "w").write(b3h + "| 1 | tex 9 | false | local | a | `why_named_gone` | `gone_witness` | c |\n")
        _b3c = dead_witnesses(_b3w, set())
        open(_b3w, "w").write(b3h.replace("| Lean witness |", "| witness cell |").replace("| status | repair |", "| status | repair |")
                              + "| 1 | tex 9 | false | local | a | `why_named_gone` | `gone_witness` | c |\n")
        _b3d = dead_witnesses(_b3w, set())
        open(_b3w, "w").write("| # | where | severity | says | why | Lean witness | consequence |\n|---|---|---|---|---|---|---|\n"
                              "| 1 | tex 9 | S1 | a | `why_gone` | `old_gone` | `cons_gone` |\n")
        _b3o = dead_witnesses(_b3w, set())
        open(_b3w, "w").write("| # | where | status | repair | says | why | proof | consequence |\n|---|---|---|---|---|---|---|---|\n"
                              "| 1 | tex 9 | false | local | a | `why_gone` | `col6_gone` | c |\n")
        _b3n = dead_witnesses(_b3w, set())
        checks.append(("B3: the Lean witness is the table's witness column (a dead name there is a dead witness, one in "
                       "`why it is wrong` is not), also in an old-format table (PENDING, its dead witnesses still found); "
                       "without a witness header, the 7th cell (WITNESS_COL 6)",
                       _b3c == [("1", "gone_witness")] and _b3d == [("1", "gone_witness")]
                       and _b3o == [("1", "old_gone")] and _b3n == [("1", "col6_gone")]))
        os.remove(_b3w)
        _b3rd = os.path.join(tmp, "b3rd"); os.makedirs(_b3rd, exist_ok=True)
        open(os.path.join(_b3rd, "PAPER_DEFECTS.md"), "w").write(
            "| # | where | severity | says | why | Lean witness | consequence |\n|---|---|---|---|---|---|---|\n"
            "| 1 | tex 9 | S1 | a | see `lemma_7_8` | none: confirmed by argument (x) | c |\n")
        _b3rf = record_faults(cfg, set(), _b3rd)
        shutil.rmtree(_b3rd)
        checks.append(("B3: an old-format defects table (PENDING until rewritten) still has its citations checked "
                       "(record-cite)", any(c_ == "record-cite" and "lemma_7_8" in t_ for c_, _f, _k, _t, t_ in _b3rf)))
        # B3 attack fixes (build/B3.md "Attack fixes"): 1 a blank line, a comment or a text line before a row; 2 a
        # second `## Defects` heading; 3 a repeated column; 5 a repeated row number: each PENDING[adj-record] (the
        # check fails, Phase 0 pends), and the rows the report and the box read are the same, none dropped
        pend_ = lambda t_, msg: b3_out[t_][0] == 1 and b3_out[t_][1] == 0 and any(msg in x for x in b3_out[t_][3])
        checks.append(("B3 attack 1: a blank line, an HTML comment or a text line inside the defects table is "
                       "PENDING[adj-record] and the row after it stays in the report's and the box's rows",
                       all(pend_(t_, "outside the defects table") and b3_out[t_][4] == ["1", "2", "3"]
                           and "defect 3: Lemma 2, tex 9 B3-FALSE" in b3_out[t_][5] for t_ in ("blank", "comment", "text"))))
        checks.append(("B3 attack 2: a second `## Defects` heading is PENDING[adj-record]; its rows are read (report "
                       "and box alike)", pend_("twohead", "`## Defects` headings") and b3_out["twohead"][4] == ["1", "2", "3", "4"]
                       and "defect 4: tex 11 B3-SECOND" in b3_out["twohead"][5]))
        checks.append(("B3 attack 3: a column named twice (two `status` columns) is PENDING[adj-record]",
                       pend_("dupcol", "names the column(s) status twice")))
        checks.append(("B3 attack 5: a row number used twice is PENDING[adj-record]", pend_("dupnum", "row number(s) 1 used twice")))
        checks.append(("B3 attack 4 (F10): a `false` row without its counterexample is PENDING[adj-record]",
                       pend_("nocx", "states its counterexample")))
        # F10 in code: the confirming lane record, lane refutations, a downgrade from `false`
        f10d = os.path.join(tmp, "f10u"); os.makedirs(os.path.join(f10d, "r1"))
        gf = lambda *a_: subprocess.run(["git", "-C", f10d, *a_], capture_output=True, text=True)
        gf("init", "-q"); gf("config", "user.email", "t@t"); gf("config", "user.name", "t")
        for n_, ln_, v_ in (("pass", "paper-faithfulness", "Pass"), ("pass2", "paper-faithfulness", "Pass"),
                            ("fail", "paper-faithfulness", "Fail"), ("corr", "correspondence", "Pass")):
            json.dump({"lane": ln_, "verdicts": [{"item": "F10: the counterexample of Lemma 2", "verdict": v_}]},
                      open(os.path.join(f10d, "r1", n_ + ".json"), "w"))
        pdf_ = os.path.join(f10d, "PAPER_DEFECTS.md")

        def f10(row, extra=""):
            open(pdf_, "w").write(b3h + row + "\n" + extra)
            h_, r_ = record_table(pdf_, DEFECT_KEY)
            return " ".join(defect_problems(pdf_, h_, r_))
        fr = "| 1 | Lemma 2 | false | local | a | b; counterexample: n = 3; F10: {} | {} | c |".format
        f_ok, f_none = f10(fr("r1/pass.json", b3_none)), f10(fr("none", b3_none))
        f_fail, f_corr = f10(fr("r1/fail.json", b3_none)), f10(fr("r1/corr.json", b3_none))
        json.dump({"lane": "correspondence", "verdicts": [{"item": "Lemma 2", "verdict": "Fail",
                                                        "comment": "`not_lemma_2_as_printed` compiles"}]},
                  open(os.path.join(f10d, "r1", "corr-lane.json"), "w"))
        mr_ = "| 1 | Lemma 2 | misprint (true as intended) | typo | a | b | {} | c |".format(b3_none)
        # trial #7: a refutation is due once a paper-faithfulness lane DECIDED the F10 item scope.py scheduled for it
        f_ref_unsched = f10(mr_)
        json.dump({"paper-faithfulness": ["Lemma 2", "F10: the counterexample of Lemma 2", "F10: the counterexample "
                                          "of Lemma 3", "F10: the counterexample of Lemma 7.4"],
                   "_meta": {"kind": "full", "f10": {"F10: the counterexample of Lemma 2": "not_lemma_2_as_printed",
                                                     "F10: the counterexample of Lemma 3": "not_lemma_3_as_printed",
                                                     "F10: the counterexample of Lemma 7.4":
                                                         "not_lemma_7_4_as_printed"}}},
                  open(os.path.join(f10d, "r1", "TARGET.json"), "w"))
        _pfv = lambda v2, v3: json.dump({"lane": "paper-faithfulness", "verdicts": [
            {"item": "F10: the counterexample of Lemma 2", "verdict": v2},
            {"item": "F10: the counterexample of Lemma 3", "verdict": v3},
            {"item": "F10: the counterexample of Lemma 7.4", "verdict": v3}]},
            open(os.path.join(f10d, "r1", "paper-faithfulness.json"), "w"))
        _pfv("Ambiguous", "Ambiguous")
        f_ref_amb = f10(mr_)
        _pfv("Pass", "Pass")
        f_ref = f10(mr_)
        f_enc = f10(mr_, "## Not defects\n- encoding error: `not_lemma_2_as_printed` (ℕ subtraction); F10: r1/fail.json\n")
        f_enc_p = f10(mr_, "## Not defects\n- encoding error: `not_lemma_2_as_printed`; F10: r1/pass.json\n")
        f_row = f10(fr("r1/pass.json", "`not_lemma_2_as_printed`"))
        os.remove(os.path.join(f10d, "r1", "corr-lane.json"))
        f10(fr("r1/pass.json", b3_none)); gf("add", "-A"); gf("commit", "-qm", "adjudicate r1")
        f_down = f10(mr_.replace("| b |", "| b; F10: r1/pass.json |"))
        f_down_ok = f10(mr_.replace("| b |", "| b; F10: r1/pass2.json |"))
        f_gone = f10("| 2 | Lemma 3 | unsupported | local | a | b | {} | c |".format(b3_none))
        checks.append(("B3 attack 4 (F10): a `false` row needs a cited paper-faithfulness lane record whose F10 item "
                       "is Pass (none, a Fail, another lane: PENDING)",
                       "F10" not in f_ok and all("cites the fresh paper-faithfulness lane" in x for x in (f_none, f_fail, f_corr))
                       and "is Fail" in f_fail and "not a paper-faithfulness" in f_corr))
        checks.append(("B3 attack 4 (F10): a lane refutation `not_X_as_printed` needs a `false` row naming it or an "
                       "encoding-error line whose cited F10 verdict is Fail",
                       "lane refutation `not_lemma_2_as_printed`" in f_ref and "lane refutation" not in f_enc
                       and "lane refutation" in f_enc_p and "lane refutation" not in f_row))
        json.dump({"lane": "paper-faithfulness", "verdicts": [
            {"item": "F10: the counterexample of Lemma 2", "verdict": "Pass"},
            {"item": "F10: the counterexample of Lemma 21", "verdict": "Fail"}]},
            open(os.path.join(f10d, "r1", "two.json"), "w"))
        f_two = f10(fr("r1/two.json", b3_none))
        os.remove(os.path.join(f10d, "r1", "two.json"))
        checks.append(("trial #7: a lane record judging two counterexamples confirms each only for its own result (the "
                       "row's result is read, not the last F10 item)", "F10" not in f_two))
        checks.append(("trial #7 (F10 scheduling): a lane refutation is not yet due while no paper-faithfulness lane "
                       "has decided the F10 item scope.py scheduled for it (unscheduled, or Ambiguous); once one "
                       "decides it (Pass or Fail), it is",
                       "lane refutation" not in f_ref_unsched and "lane refutation" not in f_ref_amb
                       and "lane refutation" in f_ref))
        checks.append(("B3 attack 4 (F10): a row committed as `false` changes status only citing a fresh F10 lane "
                       "record (not the one it cited), and is never removed",
                       "was `false`" in f_down and "was `false`" not in f_down_ok and "are gone" in f_gone))
        # F10 against a real lane file's format (vendored under tests/lane_samples):
        # the fixtures above follow the same schema lanecheck checks, so they cannot drift from it again
        import lanecheck
        real_ = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "lane_samples",
                                  "pf-sample-1.json"), encoding="utf-8").read()
        fx_ok = not lanecheck.schema_faults(real_) and all(not lanecheck.schema_faults(open(os.path.join(f10d, "r1", f_)).read())
                                                          for f_ in os.listdir(os.path.join(f10d, "r1"))
                                                          if f_ != "TARGET.json")
        os.makedirs(os.path.join(f10d, "r2"))

        def real_lane(name, ent):
            d_ = json.loads(real_); d_["verdicts"].append(ent)
            json.dump(d_, open(os.path.join(f10d, "r2", name + ".json"), "w"))
        real_lane("pf-pass", {"item": "F10: the counterexample of Lemma 7.4", "verdict": "Pass", "checked": "n=3"})
        real_lane("pf-fail", {"item": "F10: the counterexample of Lemma 7.4", "verdict": "Fail", "checked": "x"})
        rr_ = "| 1 | Lemma 7.4 | false | local | a | b; counterexample: n = 3; F10: r2/{} | {} | c |".format
        g_ok, g_fail = f10(rr_("pf-pass.json", b3_none)), f10(rr_("pf-fail.json", b3_none))
        real_lane("pf-ref", {"item": "Lemma 7.4", "verdict": "Fail", "checked": "`not_lemma_7_4_as_printed` compiles"})
        g_ref = f10("| 1 | Lemma 7.4 | misprint (true as intended) | typo | a | b | {} | c |".format(b3_none))
        checks.append(("F10 on a real lane file (sample): an honest `false` row citing its Pass F10 item passes, a Fail "
                       "one is PENDING, and a refutation named only in a real lane file needs its row; the selftest "
                       "lane fixtures pass lanecheck's schema",
                       fx_ok and "F10" not in g_ok and "is Fail" in g_fail
                       and "lane refutation `not_lemma_7_4_as_printed`" in g_ref))
        # B4 (U2 §3 F12): a minimal repair cites the lane's F12 item, Pass and naming the step; a --refuted-by
        # refutation (REAPPROVAL.json `refuted`) is accounted for like a lane's
        for n_, v_, c_ in (("f12", "Pass", "the added hypothesis is used in step 3 of the paper's proof (tex l.42)"),
                           ("f12nostep", "Pass", "the paper's proof proves it"),
                           ("f12fail", "Fail", "step 3 needs only n > 1; the added n > 100 is oversized")):
            json.dump({"lane": "paper-faithfulness", "verdicts": [{"item": "F12: the repair of Lemma 2", "verdict": v_,
                                                                    "comment": c_}]},
                      open(os.path.join(f10d, "r1", n_ + ".json"), "w"))
        f12r = ("| 3 | Lemma 2 | false | {} | a | b; counterexample: n = 3; F10: r1/pass.json{} | " + b3_none + " | c |").format
        f12_ok, f12_none = f10(f12r("add hypothesis", "; F12: r1/f12.json")), f10(f12r("add hypothesis", ""))
        f12_ns, f12_fail = f10(f12r("local", "; F12: r1/f12nostep.json")), f10(f12r("typo", "; F12: r1/f12fail.json"))
        f12_sub = f10(f12r("substantial", ""))
        checks.append(("B4 F12: a `false` row whose repair is minimal (typo, add hypothesis, local) cites the "
                       "paper-faithfulness lane's F12 item, Pass and naming the step of the paper's proof; none, a "
                       "Fail (the oversized-repair benchmark) or no step: PENDING[adj-record]; `substantial` needs none",
                       "(F12)" not in f12_ok and "(F12)" in f12_none and "names no step" in f12_ns
                       and "the F12 item is Fail" in f12_fail and "(F12)" not in f12_sub))
        json.dump({"decls": ["N.lemma_3"], "refuted": {"N.lemma_3": {"by": "N.not_lemma_3_as_printed"}}},
                  open(os.path.join(f10d, "REAPPROVAL.json"), "w"))
        f12_ref = f10(mr_)
        f12_refrow = f10(f12r("substantial", "; `not_lemma_3_as_printed`"))
        f4_nr, f4_nr_other = f10(f12r("not repaired", "; `not_lemma_3_as_printed`")), f10(f12r("not repaired", ""))
        os.remove(os.path.join(f10d, "REAPPROVAL.json"))
        checks.append(("B4 review fix 4: a refuted and re-approved result's row cannot say `not repaired` "
                       "(PENDING[adj-record]); a row about another result can",
                       "never `not repaired`" in f4_nr and "never `not repaired`" not in f4_nr_other
                       and "never `not repaired`" not in f12_refrow))
        checks.append(("B4: a refutation a re-approval was begun with (`--refuted-by`) needs a `false` row naming it "
                       "or an encoding-error line, like a lane's",
                       "refutation `not_lemma_3_as_printed` (REAPPROVAL.json" in f12_ref
                       and "not_lemma_3_as_printed" not in f12_refrow))
        # B4 review fix 1: F12 against a real lane file's format (a second sample, vendored under
        # tests/lane_samples) with an F12 item added: the lane writes `verdicts`, and that is what F12 reads
        real12 = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "lane_samples",
                                   "pf-sample-2.json"), encoding="utf-8").read()
        for n_, v_ in (("pf12-pass", "Pass"), ("pf12-fail", "Fail")):
            d_ = json.loads(real12)
            d_["verdicts"].append({"item": "F12: the repair of Lemma 7.4", "verdict": v_,
                                   "checked": "the added clause n > 1 is used at tex l.192 (step 2)"})
            json.dump(d_, open(os.path.join(f10d, "r2", n_ + ".json"), "w"))
        rr12 = ("| 4 | Lemma 7.4, tex l.182-183 | false | add hypothesis | a | b; counterexample: n = 3; "
                "F10: r2/pf-pass.json; F12: r2/{} | " + b3_none + " | c |").format
        g12_ok, g12_fail = f10(rr12("pf12-pass.json")), f10(rr12("pf12-fail.json"))
        checks.append(("B4 review fix 1: F12 on a real lane file (a second sample) with an F12 item added: a Pass "
                       "item is read (the row passes), a Fail one is PENDING; the real file passes lanecheck's schema",
                       not lanecheck.schema_faults(real12) and "(F12)" not in g12_ok
                       and "the F12 item is Fail" in g12_fail))
        # B4 review fix 3: the F12 item names the row's own result exactly, and for a re-approved result comes from
        # a lane run after the latest `reapprove --begin` (a failed later correction cannot reuse an earlier Pass)
        g3 = os.path.join(tmp, "f12g"); os.makedirs(g3)
        g3g = lambda *a_: subprocess.run(["git", "-C", g3, *a_], capture_output=True, text=True).stdout.strip()
        g3g("init", "-q"); g3g("config", "user.email", "t@t"); g3g("config", "user.name", "t")
        g3c = []
        for k_ in range(3):
            open(os.path.join(g3, f"L{k_}.lean"), "w").write("-- x\n"); g3g("add", "-A"); g3g("commit", "-qm", f"c{k_}")
            g3c.append(g3g("rev-parse", "HEAD"))
        g3r = lambda k_: f"2026-10-22-full-{g3c[k_][:11]}"
        for k_ in range(3):
            os.makedirs(os.path.join(g3, g3r(k_)))
            for n_, it_ in (("pf", "F12: the repair of Lemma 2"), ("other", "F12: the repair of Lemma 22")):
                json.dump({"lane": "paper-faithfulness", "verdicts": [{"item": it_, "verdict": "Pass",
                                                                       "checked": "used in step 3 (tex l.42)"}]},
                          open(os.path.join(g3, g3r(k_), n_ + ".json"), "w"))
        open(os.path.join(g3, "Main.lean"), "w").write("| Lemma 2 | `N.lemma_2` |\n")
        g3cfg = {"index_file": "Main.lean", "lean_files": ["Main.lean"]}

        def f12g(cite, refname=True, cfg_=None, where="Lemma 2, tex l.40"):
            pp_ = os.path.join(g3, "PAPER_DEFECTS.md")
            open(pp_, "w").write(b3h + f"| 1 | {where} | false | add hypothesis | a | b; counterexample: n = 3; "
                                 + ("`not_lemma_2_as_printed`; " if refname else "") + f"F12: {cite} | {b3_none} | c |\n")
            h_, r_ = record_table(pp_, DEFECT_KEY)
            saved_ = project.REPO; project.REPO = g3
            try:
                return " ".join(x for x in f10_problems(pp_, h_, r_, cfg_) if "(F12)" in x)
            finally:
                project.REPO = saved_

        def g3begin(*bs):
            json.dump({"decls": ["N.lemma_2"], "closed": False, "refuted": {"N.lemma_2": {"by": "N.not_lemma_2_as_printed"}},
                       "begins": [dict(lean_head=g3c[k_], date="2026-10-22", decls=["N.lemma_2"], reason="r",
                                       **({"refuted_by": "N.not_lemma_2_as_printed"} if rb_ else {})) for k_, rb_ in bs]},
                      open(os.path.join(g3, "REAPPROVAL.json"), "w"))
        x_label = f12g(f"{g3r(1)}/other.json")
        x_none_ok = f12g(f"{g3r(0)}/pf.json")
        x_nolab = f12g(f"{g3r(0)}/pf.json", where="tex l.40")
        x_paren = f12g(f"{g3r(0)}/pf.json", where="Lemma 2 (the key lemma), tex l.40")
        g3begin((0, True))
        x_pre, x_post = f12g(f"{g3r(0)}/pf.json"), f12g(f"{g3r(1)}/pf.json")
        g3begin((0, True), (1, True))
        x_fail_old, x_fail_new = f12g(f"{g3r(1)}/pf.json"), f12g(f"{g3r(2)}/pf.json")
        g3begin((1, False))
        x_idx, x_noidx = f12g(f"{g3r(1)}/pf.json", False, g3cfg), f12g(f"{g3r(2)}/pf.json", False, g3cfg)
        checks.append(("B4 review fix 3: the F12 item names the row's own result exactly (an item on Lemma 22 is no "
                       "repair of Lemma 2); for a re-approved result it comes from a lane run after the latest begin: "
                       "a row naming no result is PENDING; one at or before it is PENDING, a later one passes; after a failed correction (a second "
                       "begin) the earlier Pass no longer counts; a plain re-approval is linked through the index",
                       "has no item \"F12: the repair of Lemma 2\"" in x_label and not x_none_ok
                       and "a minimal repair names its result" in x_nolab and not x_paren
                       and "not after the latest re-approval" in x_pre and not x_post
                       and "not after the latest re-approval" in x_fail_old and not x_fail_new
                       and "not after the latest re-approval" in x_idx and not x_noidx))
        shutil.rmtree(g3)
        shutil.rmtree(f10d)
        # re-check N2: the adjudicator says which side is wrong; an ADOPT row naming the index label makes
        # it the operator's (report), and the skip is never what it is told to delete
        fs_ = [p_ for p_ in index_accounting([["Theorem 1.1", "`thm_1_1`"]], [["1", "Theorem 1.1", "too hard"]],
                                             {"thm_1_1"}, [])[2]]
        fs_a = [p_ for p_ in index_accounting([["Theorem 1.1", "`thm_1_1`"]], [["1", "Theorem 1.1", "too hard"]],
                                              {"thm_1_1"}, [], {"Theorem 1.1": "2026-01-01-abc"})[2]]
        n2_rd = os.path.join(tmp, "R", "2026-10-21-n2"); os.makedirs(n2_rd, exist_ok=True)
        open(os.path.join(n2_rd, "ADOPTED.md"), "w").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            "| correspondence | **Theorem 1.1** | Fail | **ADOPT** | the index is wrong: thm_1_1 is a special case |\n")
        n2_ad = index_adopts(cfg)
        n2_af = [f_ for f_ in adjudication_findings(cfg) if "formalized AND" in f_]
        os.remove(os.path.join(n2_rd, "ADOPTED.md")); os.rmdir(n2_rd)
        checks.append(("N2: formalized AND skipped names both sides (adj-record); an ADOPT row naming the index "
                       "label makes it the operator's index fix (report)",
                       len(fs_) == 1 and fs_[0].code == "adj-record" and "The index is wrong" in fs_[0]
                       and "keep the row" in fs_[0]
                       and len(fs_a) == 1 and fs_a[0].code == "report" and "not formalized" in fs_a[0]
                       and n2_ad.get("Theorem 1.1") == "2026-10-21-n2" and n2_af == []
                       and any("formalized AND" in f_ for f_ in adjudication_findings(cfg))))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Remark 1.2 | realises the Theorem 1.1 value |\n")
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Remark 1.2 | not formalized |"])
        checks.append(("a skip row's REASON mentioning another result neither skips nor explains it",
                       build(cfg, True) == 0))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Lemma 1.2 | see `thm_9_9` |\n")
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | not formalized |"])
        checks.append(("a name cited in SKIPPED.md that does not exist FAILS", build(cfg, True) == 1))
        open(os.path.join(tmp, "P", "Src.lean"), "a").write("/-\ntheorem thm_2_1 : True := trivial\n-/\n")
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Theorem 2.1 | `thm_2_1` |"])
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write("| # | what | reason |\n|---|---|---|\n")
        checks.append(("a declaration inside a comment is not declared (FAILS)", build(cfg, True) == 1))
        a_ = assumptions(dict(cfg, literature_hypotheses=[{"lean": "ErdosHyp", "paper": "[5, Thm 2]"}]))
        checks.append(("B5: with no assumption walk, section 2 says NOT COMPUTED (never 'none'); a declared literature "
                       "hypothesis is still listed",
                       bool(a_["why"]) and [r_[0] for r_ in a_["rows"]] == ["`ErdosHyp`"]))
        tr = dict((r[0], r[2]) for r in trust_rows(cfg))
        checks.append(("trust: no approval is disclosed as NONE", "NONE" in tr["Approval of statements"]))
        tq2_ = tempfile.mkdtemp()
        try:
            open(os.path.join(tq2_, "PAPER_DEFECTS.md"), "w").write("- All proofs are `sorry` at commit abc1234. x\n")
            ss_ = stale_sorry_notes(tq2_, "def5678aaaa"), stale_sorry_notes(tq2_, "abc1234ffff")
            # C2-FIX review 2: the completeness check could not run -> no note claims "Phase 0 found none"
            os.makedirs(os.path.join(tq2_, "stops", "S1"))
            json.dump({"by": "core-fault", "core_file": "phase0.py"},
                      open(os.path.join(tq2_, "stops", "S1", "CLOSED.json"), "w"))
            ss_cf = stale_sorry_notes(tq2_, "def5678aaaa")
        finally:
            shutil.rmtree(tq2_, ignore_errors=True)
        checks.append(("mini1: 'proofs are sorry at commit X' in an adjudicator record is a stale NOTE unless X is HEAD",
                       len(ss_[0]) == 1 and "abc1234" in ss_[0][0] and ss_[1] == [] and ss_cf == []))
        checks.append(("mini1: a lane no round ran is a NOT RUN trust row (prior-art: the citations unchecked)",
                       tr.get("AI reviewer: prior-art", "").startswith("NOT RUN") and "citations" in tr["AI reviewer: prior-art"]))
        checks.append(("B7 (U2 §7e): the proof-routes row says slips are recorded when found and proofs are not checked "
                       "line by line against the paper",
                       "slips are recorded when found; proofs are not checked line by line against the paper"
                       in tr.get("Proof routes", "")))
        # changes after the last audit round: a throwaway git repo
        gr = os.path.join(tmp, "gitrepo"); os.makedirs(os.path.join(gr, "rr"))
        def g_(*x):
            return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", gr, *x],
                                  capture_output=True, text=True).stdout.strip()
        g_("init", "-q"); g_("config", "user.email", "t@t"); g_("config", "user.name", "t")
        def commit(fname, txt, msg, when):
            open(os.path.join(gr, fname), "a").write(txt); g_("add", fname)
            subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", gr, "commit", "-qm", msg],
                           env=dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when),
                           capture_output=True)
            return g_("rev-parse", "--short=11", "HEAD")
        def mkround(name, kind):
            os.makedirs(os.path.join(gr, "rr", name), exist_ok=True)
            json.dump({"_meta": {"kind": kind}}, open(os.path.join(gr, "rr", name, "TARGET.json"), "w"))
        gcfg = {"rounds_dir": "rr", "lean_files": ["A.lean"]}
        g = globals(); saved_repo = (g["REPO"], project.REPO)
        g["REPO"] = project.REPO = gr
        try:
            c1 = commit("A.lean", "x\n", "base", "2026-01-01T10:00:00")
            checks.append(("after-last-round: no round yet -> no row", later_row(gcfg) is None))
            mkround(f"2026-01-02-{c1}", "diff")   # dated LATER than the newer round below
            r = later_row(gcfg)
            checks.append(("after-last-round: HEAD is the audited commit -> 'none', naming the round",
                           r and r[2].startswith("none:") and c1 in r[2]))
            # a NEWER round whose name sorts FIRST (same date, hash order): commit time must decide
            c2 = commit("A.lean", "y\n", "audited fix", "2026-01-01T11:00:00")
            name2 = f"2026-01-01-{c2}"
            mkround(name2, "diff")
            c3 = commit("A.lean", "z\n", "late fix", "2026-01-01T12:00:00")
            r = later_row(gcfg)
            checks.append(("after-last-round: the last round is the newest BY COMMIT TIME",
                           r and c2 in r[2] and "late fix" in r[2] and "audited fix" not in r[2]))
            checks.append(("after-last-round: later commits are reported as NOT re-audited",
                           r and "NOT re-audited" in r[2] and r[2].startswith("1 commit")))
            # a newer STATEMENT round examined statements only: it is not 'the last audit round'
            mkround(f"2026-01-01-full-{c3}", "statements")
            r = later_row(gcfg)
            checks.append(("after-last-round: a statement round does not count as an audit round",
                           r and c2 in r[2] and "late fix" in r[2]))
            commit("notes.md", "n", "docs", "2026-01-01T13:00:00")
            r = later_row(gcfg)
            checks.append(("after-last-round: a commit not touching Lean/build files is not listed",
                           r and r[2].startswith("1 commit")))
            commit("lakefile.lean", "--", "bump", "2026-01-01T14:00:00")
            r = later_row(gcfg)
            checks.append(("after-last-round: a build-file change (lakefile) IS listed",
                           r and r[2].startswith("2 commit") and "bump" in r[2]))
            open(os.path.join(gr, "A.lean"), "a").write("dirty\n")
            r = later_row(gcfg)
            checks.append(("after-last-round: uncommitted Lean edits are disclosed",
                           r and "UNCOMMITTED changes to A.lean" in r[2]))
            g_("checkout", "-q", "--", "A.lean")
            g_("checkout", "-q", c1)
            r = later_row(gcfg)
            checks.append(("after-last-round: HEAD behind the audited commit is UNKNOWN, never 'none'",
                           r and r[2].startswith("UNKNOWN") and "does not descend" in r[2]))
            g_("checkout", "-q", "-")
            mkround("2026-01-02-deadbee0000", "diff")
            r = later_row(gcfg)
            checks.append(("after-last-round: an unreadable round commit is UNKNOWN, never 'none'",
                           r and r[2].startswith("UNKNOWN")))
        finally:
            g["REPO"], project.REPO = saved_repo
        def appr_doc(**kw):
            json.dump(dict({"date": "2026-01-01", "commit": "c", "how": "blanket",
                            "rows": {"Theorem 1.1": {"status": "approved"}, "Lemma 1.2": {"status": "excluded"}},
                            "fingerprints": {"P.thm_1_1": "x"}}, **kw),
                      open(os.path.join(tmp, "R", "APPROVED_FINGERPRINTS.json"), "w"))
            return dict((r[0], (r[1], r[2])) for r in trust_rows(cfg))["Approval of statements"]
        e, st_ = appr_doc(by="human")
        checks.append(("trust: approval counts results and says blanket vs individual",
                       "1 of 2 results approved as a blanket" in st_ and "1 excluded" in st_))
        checks.append(("trust: a human approval says a mathematician read the sheet",
                       "approved by a human" in st_ and "mathematician read" in e))
        e, st_ = appr_doc(by="agent", note="Thm 1.1' approved by the user")
        checks.append(("trust: an AGENT approval is never presented as a human one",
                       "NOT BY A HUMAN" in st_ and "NOT reviewed by a human" in e
                       and "mathematician read" not in e and "approved by the user" in st_))
        checks.append(("trust: an agent approval never says 'all OK' or 'result by result'",
                       "all OK" not in st_ and "result by result" not in st_))
        e, st_ = appr_doc(date="2026-10-22")
        checks.append(("trust: an approval without an approver is treated as not human-reviewed",
                       "NOT RECORDED" in st_ and "NOT reviewed by a human" in e))
        e, st_ = appr_doc()
        checks.append(("forgery review M1: a `by`-less approval dated before the field existed, in a run whose first "
                       "pin is not older than the field (here none), is NOT the human's (the date is the operator's)",
                       "NOT RECORDED" in st_ and "(legacy)" not in st_))
        _fp_keep = project.first_pin
        try:
            project.first_pin = lambda rd_: {"ownership": 1, "date": "2026-10-01"}
            e, st_ = appr_doc()
            ok_old = "approved by a human (legacy)" in st_ and project.LEGACY_BY_NOTE in st_
            project.first_pin = lambda rd_: {"ownership": 2, "date": "2026-10-01"}
            e, st_ = appr_doc()
            ok_v2 = "NOT RECORDED" in st_
        finally:
            project.first_pin = _fp_keep
        checks.append(("trust: an approval written before the `by` field existed reads as the human's, disclosed "
                       "as legacy, only in a run whose first pin is of ownership 1 and older than the field "
                       "(forgery review M1)", ok_old and ok_v2))
        e, st_ = appr_doc(by="agent", rows={})
        checks.append(("trust: the older-format branch (no rows) still names an agent approver",
                       "NOT BY A HUMAN" in st_))
        json.dump({"date": "2025-12-01", "by": "agent", "fingerprints": {}},
                  open(os.path.join(tmp, "R", "APPROVED_FINGERPRINTS.2025-12-01.json"), "w"))
        e, st_ = appr_doc(by="human")
        checks.append(("trust: an earlier (agent) approval moved aside is still disclosed",
                       "earlier approvals: 2025-12-01 by agent" in st_))
        os.remove(os.path.join(tmp, "R", "APPROVED_FINGERPRINTS.2025-12-01.json"))
        # B4 review fix 4: earlier approvals in the order made: unnumbered first, then .2, ..., .10 (numerically)
        eo_ = [("APPROVED_FINGERPRINTS.2025-12-01.json", "agent"), ("APPROVED_FINGERPRINTS.2025-12-01.2.json", "human"),
               ("APPROVED_FINGERPRINTS.2025-12-01.10.json", "operator")]
        for n_, b_ in eo_:
            json.dump({"date": "2025-12-01", "by": b_, "fingerprints": {}}, open(os.path.join(tmp, "R", n_), "w"))
        e, st_ = appr_doc(by="human")
        for n_, _ in eo_:
            os.remove(os.path.join(tmp, "R", n_))
        checks.append(("B4 review fix 4: the trust row lists earlier approvals in the order made (unnumbered, .2, .10)",
                       "earlier approvals: 2025-12-01 by agent, 2025-12-01 by human, 2025-12-01 by operator" in st_))
        # ROUND3 H1 (attack reapproval_repro.sh): a re-approval begun and never closed
        rap = os.path.join(tmp, "R", "REAPPROVAL.json")
        json.dump({"decls": ["P.thm_1_1"], "begin_fingerprints": {"P.thm_1_1": "x"}, "lean_head": "abc",
                   "begins": [{"date": "2026-01-02", "lean_head": "abc", "decls": ["P.thm_1_1"],
                               "reason": "missing theory: name a hypothesis", "involvement": "involved"}],
                   "closed": False}, open(rap, "w"))
        e, st_ = appr_doc(by="human")
        checks.append(("H1: an OPEN re-approval: the trust row never says 'none has changed', names it open",
                       "none has changed" not in e and "STILL OPEN" in e and "OPEN: never closed" in st_
                       and "P.thm_1_1" in st_))
        buf_ = __import__("io").StringIO()
        with __import__("contextlib").redirect_stdout(buf_):
            rc_ = build(cfg, True)
        checks.append(("H1: report --check FAILS while a re-approval is open, saying so",
                       rc_ == 1 and "re-approval is OPEN" in buf_.getvalue()))
        # a close counts only as `signoff.py approve` commits it (B2 review): the begin commit, then one
        # "approve R9" commit writing the closed record with the new approval (a scratch repository)
        _g = lambda *a_: subprocess.run(["git", "-C", tmp, *a_], capture_output=True, text=True)
        for c_ in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                   ["add", "R/REAPPROVAL.json"], ["commit", "-qm", "approve (reapproval begin: x)"]):
            _g(*c_)
        d_ = json.load(open(rap)); d_.update(closed=True, closed_by="approve R9", closed_date="2026-01-03")
        json.dump(d_, open(rap, "w"))
        e, st_ = appr_doc(by="human")
        # the human's close is evidenced by their answer, logged after the begin (B2 re-check (a)/(c))
        with open(os.path.join(tmp, "R", "RUN_LOG.md"), "a", encoding="utf-8") as f_:
            f_.write('\n## Re-approvals\n- human answer (round R9; P.thm_1_1): "yes, approve it"\n')
        _g("add", "R/REAPPROVAL.json", "R/APPROVED_FINGERPRINTS.json", "R/RUN_LOG.md")
        _g("commit", "-qm", "approve R9")
        e, st_ = appr_doc(by="human")      # the trust rows read once the close is committed
        buf_ = __import__("io").StringIO()
        with __import__("contextlib").redirect_stdout(buf_):
            build(cfg, False)
        shutil.rmtree(os.path.join(tmp, ".git"), ignore_errors=True)
        md_ = open(os.path.join(tmp, "R", "REPORT.md"), encoding="utf-8").read()
        checks.append(("H1: a closed re-approval is disclosed (trust row + section), the check does not fail on it",
                       "none has changed" not in e and "1 re-approval(s)" in e and "closed by `approve R9`" in st_
                       and "### Re-approvals during the run" in md_ and "missing theory: name a hypothesis" in md_
                       and "re-approval is OPEN" not in buf_.getvalue()))
        os.remove(rap)
        idx([])
        checks.append(("an unparseable index FAILS rather than reporting nothing",
                       build(cfg, True) == 1))
        # --- H3: rendering of record cells, assumptions, counts ---
        checks.append(("an escaped bar inside a cell does not split it (defect rows kept their fields)",
                       project.split_row(r"| 1 | `hd = \|i\|` | why |") == ["1", "`hd = |i|`", "why"]))
        # the Lean fixture the rendering checks below cite (fk_holds at line 4)
        open(os.path.join(tmp, "P", "Hyp.lean"), "w").write(
            "def FK : Prop := True\ndef IsTrav : Prop := True\naxiom ax1 : True\n"
            "theorem fk_holds : FK := trivial\n"
            "theorem thm_2_1 (hFK : P.FK) : True := trivial\n"
            "theorem uses_trav (P : Nat) (h : IsTrav P 3) : True := trivial\n"
            "def Anon : Prop := True\ndef Inst : Prop := True\ndef Sub : Prop := True\n"
            "-- theorem in_comment (h : Gone) : True\ndef Gone : Prop := True\n"
            "theorem a5 (_ : Anon) : True := trivial\ntheorem a6 [Fact Inst] : True := trivial\n"
            "theorem a7 (h₁ : Sub) : True := trivial\ntheorem a8 {hfk : P.FK} : True := trivial\n"
            "theorem a9 : P.FK → True := fun _ => trivial\n")
        # B5 (U2 §2): section 2 is the assumption walk's (DEPENDENCIES.json) and the adjudicator's
        # `## Hypotheses` rows; the regex path and its fixtures are gone (hypotheses.py --selftest and
        # dependencies.py --selftest hold the walk's fixtures)
        json.dump({"lean_sha256": "h", "commit": "c", "walked": ["thm"], "binders": {}, "goal": {}, "restates": {},
                   "axioms": {}, "instances": [], "bare": {},
                   "assumes": {"thm": [{"name": "InstHyp", "binder": "h", "kind": "prop", "type_pp": "InstHyp n",
                                        "embedded": False}]}},
                  open(os.path.join(tmp, "R", "DEPENDENCIES.json"), "w"))
        a5 = assumptions(cfg)
        md5 = io.StringIO()
        with contextlib.redirect_stdout(md5):
            rc5 = build(cfg, True, pending_ok=True)
        rc5b = build(cfg, True)
        af5 = [str(f_) for f_ in adjudication_findings(cfg) if getattr(f_, "code", None) == "adj-record"]
        # B6 (U2 §7): the operator's missing-theory line is checked by the report check, FAIL[missing-theory]
        lp6 = os.path.join(tmp, "R", "RUN_LOG.md")
        keep6 = open(lp6, encoding="utf-8").read() if os.path.exists(lp6) else None
        open(lp6, "w").write((keep6 or "") + "\n## Stage 2\n- missing theory (human 2026-01-02): assume `InstHyp` "
                             "for `thm` — searched: Mathlib, TauCeti; estimate: weeks\n")
        md6 = io.StringIO()
        with contextlib.redirect_stdout(md6):
            rc6 = build(dict(cfg, involvement="involved"), True, pending_ok=True)
        if keep6 is None:
            os.remove(lp6)
        else:
            open(lp6, "w").write(keep6)
        checks.append(("B6: the report check (also under --pending, Phase 0) fails a missing-theory line without the "
                       "paper's quote as FAIL[missing-theory], never PENDING (the operator's line, not the adjudicator's)",
                       rc6 == 1 and "FAIL[missing-theory]" in md6.getvalue() and "no quote" in md6.getvalue()
                       and "PENDING[adjudication] missing-theory" not in md6.getvalue()))
        os.remove(os.path.join(tmp, "R", "DEPENDENCIES.json"))
        checks.append(("B5: the hypothesis finding is an adjudicator-owned fault (adjudication_findings, so "
                       "`integrity.py --commit-adjudication` refuses while a row is missing)",
                       any("hypothesis `InstHyp`" in f_ for f_ in af5)))
        checks.append(("B5: a hypothesis the walk lists with no `## Hypotheses` row is listed as PENDING in section 2 "
                       "and is PENDING[adj-record] under --pending, a FAIL without it (never dropped)",
                       any(r_[0] == "`InstHyp`" and r_[2].startswith("PENDING") and "(h : InstHyp n)" in r_[4]
                           for r_ in a5["rows"])
                       and "PENDING[adjudication] adj-record: hypothesis `InstHyp`" in md5.getvalue()
                       and rc5b == 1))
        tq_ = tempfile.mkdtemp()
        try:
            w_no = decision_words(tq_)["QUESTION"]
            open(os.path.join(tq_, "DECISIONS.md"), "w").write("x")
            w_yes = decision_words(tq_)["QUESTION"]
        finally:
            shutil.rmtree(tq_, ignore_errors=True)
        checks.append(("QUESTION items: no claim about answers; the decisions document is named only if it exists",
                       w_no == "put to the human as questions" and tq_ in w_yes and "answer" not in w_no))
        _ho = {"involvement": "hands-off"}
        checks.append(("mini2-4: under hands-off a QUESTION row is not 'put to the human' and an ambiguous count "
                       "says what became of it",
                       "human" in decision_words(tq_, _ho)["QUESTION"]
                       and "put to the human" not in decision_words(tq_, _ho)["QUESTION"]
                       and "decided by the operator" in decision_words(tq_, _ho)["QUESTION"]
                       and "QUESTION row" in ambiguous_words(7, _ho) and "operator" in ambiguous_words(7, _ho)
                       and "for the human" in ambiguous_words(7, {"involvement": "involved"})))
        _A0 = {"rows": [], "notes": [], "why": "", "counts": {}}
        tx_c = blocks_md(assume_blocks(dict(_A0, rows=[["`P.X`", "literature hypothesis (declared at Checkpoint A)",
                                                         "[5, Thm 2]", "-", "*not used by any result's statement*"]],
                                            notes=["Hypotheses added: none."])))
        checks.append(("B5: section 2 prints the assumption rows (Lean in code, an unused hypothesis in words) and "
                       "the notes; a walk not computed says so",
                       "declared at Checkpoint A" in tx_c and "Thm 2" in tx_c and "not used by any result" in tx_c
                       and "Hypotheses added: none." in tx_c
                       and "NOT COMPUTED: no walk" in blocks_md(assume_blocks(dict(_A0, why="no walk")))))
        checks.append(("B5 review fix 3: section 2 discloses that the walk is syntactic (a Bool-valued or data encoding "
                       "of a hypothesis can escape it) and says what was checked of the hypotheses it does not list, "
                       "never calling them the paper's own",
                       "syntactic" in ASSUME_MD and "Bool-valued" in ASSUME_MD and "paper's own" not in ASSUME_MD
                       and "paper-faithfulness reviews" in ASSUME_MD and "beyond the paper's definitions" not in ASSUME_MD))
        checks.append(("B5 re-check fix: section 2 says what the walk checks of structure arguments -- a project "
                       "structure or class with a Prop field anywhere in an argument's type, under any wrapper or "
                       "project definition, not only as the argument itself -- and that a Mathlib structure other "
                       "than `Fact` is not looked inside",
                       "whose type contains anywhere" in " ".join(ASSUME_MD.split())
                       and "inside a project definition it uses" in " ".join(ASSUME_MD.split())
                       and "Mathlib structure, except the" in " ".join(ASSUME_MD.split())))
        open(os.path.join(tmp, "P", "Short.lean"), "w").write("x\n" * 10)
        src_tex = os.path.join(tmp, "paper.tex"); open(src_tex, "w").write("l\n" * 50)
        cfg_r = dict(cfg, lean_files=["P/Short.lean"], source_pdf=src_tex)
        rp = rendering_problems(cfg_r, [["1", "a \\qed b", "`\\emph{ok in code}`"]],
                                [["1", "Short.lean:99", "Short.lean:5", "tex 60", "tex l.40"]],
                                [["R1", "see R1 and G3", "Q4", "(l.1170)"]])
        checks.append(("rendering checks: literal LaTeX outside code, undefined IDs, lines past the end",
                       any("\\qed" in p for p in rp) and not any("emph" in p for p in rp)
                       and any("ID G3" in p for p in rp) and any("ID Q4" in p for p in rp)
                       and not any("ID R1" in p for p in rp)
                       and any("Short.lean:99" in p for p in rp) and not any("Short.lean:5 " in p for p in rp)
                       and any("tex 60" in p for p in rp) and not any("tex l.40" in p for p in rp)
                       and any("'l.1170'" in p for p in rp) and not any("'l.40'" in p for p in rp)))
        checks += _section_kinds_checks()
        fb = fail_breakdown(["ADOPT", "QUESTION", None, "UNCOVERED", "QUESTION"],
                            {"ADOPT": "adopted", "REJECT": "rejected", "QUESTION": "put to the human"})
        checks.append(("the Fail breakdown's parts add up to the total, whatever the decision kinds",
                       fb.startswith("5 Fail verdicts")
                       and sum(int(x) for x in re.findall(r"(\d+) [a-z]", fb.split("(", 1)[1])) == 5))
        rp2 = rendering_problems(dict(cfg_r, lean_files=["P/Short.lean", "P/Hyp.lean"],
                                      literature_hypotheses=[{"lean": "P.FK", "paper": "FK (intro, l.48)"}]),
                                 [], [["1", "`FK`, `fk_holds` (Hyp.lean:1, :9)", "Nope.lean:3", "tex 10–60",
                                       "$x$ and \\varphi", "tex l.~70"]], [],
                                 index=[["Lemma 1.1", "see Q9"]])
        open(os.path.join(tmp, "P", "Other.lean"), "w").write("theorem elsewhere : True := trivial\n")
        rp3 = rendering_problems(dict(cfg_r, lean_files=["P/Short.lean", "P/Other.lean"]), [],
                                 [["1", "`elsewhere` (Short.lean:3)"]], [])
        checks.append(("a name cited in a file it is not declared in is flagged, with where it is",
                       any("declared in P/Other.lean" in p for p in rp3)))
        open(os.path.join(tmp, "P", "Two.lean"), "w").write("namespace A\ntheorem foo : True := trivial\nend A\nnamespace B\ntheorem foo : True := trivial\nend B\naxiom ax9 : True\n")
        rp4 = rendering_problems(dict(cfg_r, lean_files=["P/Two.lean"]), [],
                                 [["1", "`B.foo` (Two.lean:5)", "`ax9` (Two.lean:7)", "`gone_name` (Two.lean:3)"]], [])
        rp5 = rendering_problems(cfg_r, [], [], [], vacuous=[["1", "Lemma 1", "a \\qed b"]])
        checks.append(("VACUOUS.md rows are checked too", any("VACUOUS.md" in p and "qed" in p for p in rp5)))
        rp6 = rendering_problems(dict(cfg_r, lean_files=["P/Short.lean", "P/Hyp.lean"]), [], [], [],
                                 vacuous=[["1", "`fk_holds` (Hyp.lean:9)"]])
        rp7 = rendering_problems(dict(cfg_r, lean_files=["P/Short.lean", "P/Hyp.lean"]), [], [],
                                 [["1", "`fk_holds` (Hyp.lean:9)"]])
        checks.append(("a stale line in an adjudicator record is a NOTE, in an author record a failure",
                       any(p.startswith("NOTE") and "fk_holds" in p for p in rp6)
                       and not any(p.startswith("!") and "fk_holds" in p for p in rp6)
                       and any(p.startswith("!") and "fk_holds" in p for p in rp7)))
        checks.append(("a name declared twice is accepted at either line; axioms count; a name declared nowhere is flagged",
                       not any("B.foo" in p for p in rp4) and not any("ax9" in p for p in rp4)
                       and any("gone_name" in p and "no project file" in p for p in rp4)))
        checks.append(("rendering checks: a name cited at the wrong line (with `, :N` continuations), a missing "
                       "file, ranges, $math$, any \\command, tex l.~N; index and config scanned",
                       any("`fk_holds` is cited at Hyp.lean:9 but declared at line 4" in p for p in rp2)
                       and not any("`FK` is cited" in p for p in rp2)
                       and any("Nope.lean names no project file" in p for p in rp2)
                       and any("tex 10–60" in p for p in rp2) and any("$x$" in p for p in rp2)
                       and any("tex l.~70" in p for p in rp2)
                       and any("index row" in p and "Q9" in p for p in rp2)
                       and any("config literature" in p and "l.48" in p for p in rp2)))
        os.makedirs(os.path.join(tmp, "R", "2026-01-01-aaaaaaa")); os.makedirs(os.path.join(tmp, "R", "2026-01-02-bbbbbbb"))
        open(os.path.join(tmp, "R", "2026-01-01-aaaaaaa", "ADOPTED.md"), "w").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n| correspondence | X.foo | Fail | **REJECT** | no |\n")
        open(os.path.join(tmp, "R", "2026-01-02-bbbbbbb", "ADOPTED.md"), "w").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n| correspondence | X.foo | STALE | **UNCOVERED** | gone |\n")
        so_ = project.order_rounds
        project.order_rounds = lambda rs, repo: sorted(rs)
        try:
            dec_ = rolled_decisions(os.path.join(tmp, "R"))
        finally:
            project.order_rounds = so_
        checks.append(("the trust section's wording claims nothing about whether QUESTION items were answered",
                       "answered" not in DECISION_WORDS["QUESTION"].replace("their answers", "")
                       and all(k in DECISION_WORDS for k in ("ADOPT", "REJECT", "DEFER", "QUESTION", "UNCOVERED"))))
        checks.append(("UNCOVERED never replaces an earlier decision in the roll-up",
                       dec_.get("correspondence :: foo") == "REJECT"))
        for d_ in ("2026-01-01-aaaaaaa", "2026-01-02-bbbbbbb"):
            shutil.rmtree(os.path.join(tmp, "R", d_))
        os.makedirs(os.path.join(tmp, "P"), exist_ok=True)
        open(os.path.join(tmp, "P", "A.lean"), "w").write("import Mathlib.Data.Nat\nimport P.B\n")
        open(os.path.join(tmp, "P", "B.lean"), "w").write("public import all TauCeti.Graphon.Basic\nimport Mathlib.Order\nimport Batteries.Data\n")
        cfg_l = {"lean_files": ["P/A.lean", "P/B.lean"]}
        checks.append(("the report names a library other than Mathlib that the project imports (and says it is "
                       "less reviewed); a Mathlib-only project gets the plain phrase",
                       imported_libraries(cfg_l) == ["Mathlib", "TauCeti"]
                       and "also TauCeti, a smaller library less widely reviewed" in libraries_phrase(cfg_l)
                       and libraries_phrase({"lean_files": ["P/A.lean"]}) == "with the Mathlib library"))
        checks.append(("a trailing escaped bar is part of the last cell",
                       project.split_row(r"| a | ends with \| |") == ["a", "ends with |"]))
        idx(["| Theorem 1.1 | `thm_1_1` (x \\| y) |", "| Lemma 3.1 | `thm_1_1` (restatement of Theorem 1.1) |"])
        open(os.path.join(tmp, "R", "DEVIATIONS.md"), "w").write(
            "| # | result | paper | lean | why | kind |\n|---|---|---|---|---|---|\n| R1 | Theorem 1.1 | stated with \\qed | x | y | same strength |\n")
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            rc_b = build(cfg, False)
        md_ = open(os.path.join(tmp, "R", "REPORT.md")).read()
        row_ = next(l for l in md_.splitlines() if l.startswith("| Theorem 1.1 |"))
        checks.append(("build runs the rendering checks (a literal \\qed fails the report)",
                       rc_b == 1 and "\\qed" in md_.split("Verification", 1)[0] + md_[:3000]))
        checks.append(("the markdown keeps an escaped bar inside its cell (the row has 2 cells)",
                       len(project.split_row(row_)) == 2 and "\\|" in row_))
        checks.append(("the markdown has the assumptions section and explains restatements, numbered like the PDF",
                       "## 2. What the formalization assumes" in md_ and "plus 1 restatement" in md_
                       and "## 6. Where the Lean proof differs" in md_))
        checks.append(("approver 2026-10-24: the report has no section on stops, self-cures or set-asides (they are "
                       "RUN_RECORD.md's)",
                       RESOLVED_TITLE not in md_ and ALL_STOPS_TITLE not in md_ and SET_ASIDE_TITLE not in md_
                       and "None: no stop was cleared without you." not in md_))
        checks.append(("approver 2026-10-24: the report has exactly the eleven sections, numbered 1 to 11 (the reader "
                       "notes end section 1, the notation section 11)",
                       re.findall(r"(?m)^## (\d+)\. ", md_) == [str(i) for i in range(1, 12)]
                       and "## 8. Open questions" in md_ and f"## 9. {DECIDED_TITLE}" in md_
                       and f"## 10. {ROUTES_TITLE}" in md_ and "## 11. Where the Lean names are" in md_))
        import stops as _st
        _keep_w = (_st.stop_rows,)
        _pin_w = os.path.join(tmp, "R", "TOOLING_PIN.json")
        _pin_keep = open(_pin_w).read() if os.path.exists(_pin_w) else None
        try:
            _st.stop_rows = lambda c_, rd=None, phase=None: [{"stop": "S1", "answer": "go on, re-run it"}]
            json.dump({"audits_commit": "a"}, open(_pin_w, "w"))
            _w0 = weakened_row(cfg)
            _st.stop_rows = lambda c_, rd=None, phase=None: [
                {"stop": "S1", "answer": "copy the deliverables by hand; the delivery check cannot pass"}]
            _w1 = weakened_row(cfg)
            _st.stop_rows = lambda c_, rd=None, phase=None: []
            json.dump({"audits_commit": "a", "repins": [{"date": "2026-10-24", "tool_patch": "TP1", "reason": "x"}]},
                      open(_pin_w, "w"))
            _w2 = weakened_row(cfg)
            _rows_w = [r_[0] for r_ in trust_rows(cfg)]
        finally:
            _st.stop_rows = _keep_w[0]
            if _pin_keep is None:
                os.remove(_pin_w)
            else:
                open(_pin_w, "w").write(_pin_keep)
        checks.append(("approver 2026-10-24: ONE trust line when a check was weakened, no details -- a hand delivery "
                       "(a human's stop answer says the deliverables were copied by hand), the audit tools patched (a "
                       "tool-patch re-pin); none otherwise; no apparatus, reissue or set-aside row",
                       _w0 is None and _w1 is not None and _w1[2] == HAND_DELIVERY
                       and _w2 is not None and _w2[2] == TOOLS_PATCHED and "Checks weakened" in _rows_w
                       and not {"Audit apparatus", "Lane reissues", "Set-aside rounds and lanes"} & set(_rows_w)))
        # SWEEP-FIX D4 (RELEASE-SWEEP Task A, HIGH 6): a status a tool patch raised stands on SUMMARY page 1 and in
        # REPORT section 1 (the line tool_patch.raised_lines computes with the first pin's result_status.py); the
        # "Checks weakened" row carries every part tool_patch.weakened_parts requires; the texts agree with tool_patch's
        import tool_patch as _tp
        _keep_tp = (_tp.raised_lines, _tp.weakened_parts)
        _ln4 = _tp.RAISED.format(label="Theorem 1.1", tp="TP1", old="not established: no correspondence verdict")
        try:
            _tp.raised_lines = lambda c_, rd=None, audits=None: [_ln4]
            _tp.weakened_parts = lambda c_, rd=None, audits=None: ["PARTQZ acknowledged"]
            with contextlib.redirect_stdout(io.StringIO()):
                build(cfg, False)
            _md4, _sm4, _w4 = open(os.path.join(tmp, "R", "REPORT.md")).read(), summary_md(cfg), weakened_row(cfg)
            _tp.raised_lines = lambda c_, rd=None, audits=None: 1 / 0
            _sm4x = summary_md(cfg)
        finally:
            _tp.raised_lines, _tp.weakened_parts = _keep_tp
        with contextlib.redirect_stdout(io.StringIO()):
            build(cfg, False)
        checks.append(("SWEEP-FIX D4: a status a tool patch raised is on SUMMARY page 1 and in REPORT section 1, "
                       "verbatim; a comparison that cannot run is said, never silent; the \"Checks weakened\" row "
                       "carries every part the first pin's verify_delivery requires (same texts as tool_patch's)",
                       f"**{_ln4}**" in _sm4 and f"- {_ln4}" in _md4.split("## 2. ", 1)[0]
                       and RAISED_HEADING in _md4 and _tp.STATUS_UNCOMPARED in _sm4x
                       and _w4 is not None and "PARTQZ acknowledged" in _w4[2] and _w4[0] == _tp.WEAKENED_TITLE
                       and TOOLS_PATCHED == _tp.TOOLS_PATCHED
                       and _ln4 not in summary_md(cfg)))
        # approver 2026-10-26: what SUMMARY and REPORT say of these routes is plain words, no mechanism term
        _plain = [_ln4, _tp.STATUS_UNCOMPARED, RAISED_INTRO, RAISED_HEADING]
        _sec4 = _md4.split(RAISED_HEADING, 1)[-1].split("\n### ", 1)[0].split("\n## ", 1)[0]
        checks.append(("approver 2026-10-26: SUMMARY/REPORT say a status decided by corrected checking software in plain "
                       "words, with no mechanism term (tool patch, pin, acknowledgment, reviewer, ...); the mechanism "
                       "is RUN_RECORD.md's",
                       not [t for t in _tp.MECHANISM_TERMS for x in _plain + [_sec4] if t.lower() in x.lower()]
                       and "corrected version of our checking software" in _ln4 and "RUN_RECORD.md" in _ln4))
        _krs, _klk = _tp.raised_statuses, _tp.links
        try:
            _tp.links = lambda *a_: [("c", "TP1", "p", "n", {})]
            _tp.raised_statuses = lambda c_, rd=None, audits=None: [("Theorem 1.1", "TP1", "not established: x")]
            _ev4 = [e for e in trust_line_events(cfg) if e.id.startswith("TL-raised-")]

            def _boom(*a_):
                raise ValueError("git log failed")
            _tp.links = _boom
            _evb = [e for e in raised_status_events(cfg) if e.id.startswith("TL-raised-")]
            _evall = [e.id for e in trust_line_events(cfg)]     # review R3: no crash; fails closed
        finally:
            _tp.raised_statuses, _tp.links = _krs, _klk
        checks.append(("SWEEP-FIX review B2: a tool_patch.links() that raises fails closed -- the trust lines carry the "
                       "not-compared event (its line then required on the documents), never a crash",
                       len(_evb) == 1 and _evb[0].id == "TL-raised-uncompared" and _evb[0].line == _tp.STATUS_UNCOMPARED
                       and "TL-software-corrected" in _evall and "TL-raised-uncompared" in _evall))
        _lnx = _tp.RAISED.format(label="Lemma 2.4 (b)", tp="TP1", old="not established: x")
        checks.append(("review 3 hook: the raised-status sentence, as SUMMARY (bold) and REPORT (a list item) write it, is "
                       "found by TRUST_SENTENCE_RES exactly as its event's line; so is the not-compared one",
                       trust_sentences(f"**{_lnx}**\n\n- {_lnx}\n") == [_lnx]
                       and trust_sentences(f"**{_tp.STATUS_UNCOMPARED}**\n") == [_tp.STATUS_UNCOMPARED]))
        checks.append(("approver 2026-10-26: a status decided by corrected checking software registers as a trust line the "
                       "status-check agent judges (TRUST_LINE_PROVIDERS), its line the plain one, its record RUN_RECORD.md",
                       len(_ev4) == 1 and _ev4[0].line == _tp.RAISED.format(label="Theorem 1.1", tp="TP1",
                                                                            old="not established: x")
                       and "RUN_RECORD.md" in _ev4[0].record and "TP1" not in _ev4[0].line))
        _keep_sr, _keep_sa, _keep_rr = _st.stop_rows, _st.set_aside_rows, _st.repair_rows
        _st.repair_rows = lambda c_, rd=None: [
            {"stop": "repair R1", "date": "2026-10-19", "classes": ["mechanical"], "by": "the operator",
             "what": "stale git lock in the audits repository removed (stops.py repair-lock): REPAIRQZ", "done": "lock removed"}]
        _keep_hd, _keep_dl, _keep_rv = globals()["human_decisions"], globals()["delegation"], globals()["open_revotes"]
        LONGQZ = ("[DELEGATED 2026-10-19, operator under hands-off (intake); reversal: none] keep the anonymous test "
                  "example in Paper/Examples.lean " + "word " * 44 + "DELEGENDQZ")   # long, but no unbreakable 220-letter word
        # mini report (final fixes 9): a long answer, repeated in the stop list, clipped in the box broke the
        # in-order render comparison; the box now shows it in full
        LONGANS = (" (the maintainer fixed the self-test: a whole-result label still covers every part) and updated "
                   "audits/signoff.py and audits/tests/mutant_list.py in this project; " + "the record says so. " * 6
                   + "ANSENDQZ")
        _st.stop_rows = lambda c_, rd=None, phase=None: [
            {"stop": "S3", "date": "2026-10-19", "round": None, "classes": ["mechanical"], "human": False,
             "what": "`python3 audits/lanecheck.py` exited 1: PROBLEM[stray-loop] x",
             "by": "the operator (delegated): QZDONE killed the loop" + LONGANS, "done": "closed; the check passes at the close"},
            {"stop": "S4", "date": "2026-10-19", "round": None, "classes": ["tamper"], "human": True,
             "what": "integrity FAIL[ownership] STOPQZ", "by": "the human (answer, verbatim: \"HUMANSTALLQZ" + LONGANS
             + "\")", "done": "closed"},
            {"stop": "S5", "date": "2026-10-19", "round": None, "classes": ["mechanical"], "human": False, "cured": True,
             "what": "`python3 audits/phase0.py` exited 1: FAIL[tree-changed] CUREDQZ",
             "by": "the operator (release self-cure, attempt 1 of 2; restore; restored): restored", "done": "closed"}]
        _st.set_aside_rows = lambda c_, rd=None: [
            {"scope": "2026-10-19-full-9c8d7e60123", "date": "2026-10-19", "reason": "SAREASONQZ", "by": "the operator (delegated)",
             "summary": "3 file(s) committed; lanes: correspondence.json unsealed; carried forward: K.carried (Fail)",
             "carried": [], "stop_causes": []}]
        globals()["human_decisions"] = lambda c_: ["a stop answered by the human: HUMANQZ (answered 2026-10-19: archive them)"]
        globals()["delegation"] = lambda c_: ("hands-off", "(c)", [LONGQZ])
        globals()["open_revotes"] = lambda c_: [("2026-10-19-full-9c8d7e60123", "substantiveness", "Paper.probDist_single",
                                                 "REVOTEREASONQZ", "re-vote lane ABANDONED")]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                build(cfg, False)
            import run_record as _rrm
            _sp_rr, project.REPO = project.REPO, tmp
            try:
                rr_txt = _rrm.text(cfg)
            finally:
                project.REPO = _sp_rr
        finally:
            _st.stop_rows, _st.set_aside_rows, _st.repair_rows = _keep_sr, _keep_sa, _keep_rr
            globals()["human_decisions"], globals()["delegation"], globals()["open_revotes"] = _keep_hd, _keep_dl, _keep_rv
        md_r = open(os.path.join(tmp, "R", "REPORT.md")).read()
        _sm_r = open(os.path.join(tmp, "R", SUMMARY_MD)).read() if os.path.exists(os.path.join(tmp, "R", SUMMARY_MD)) else ""
        checks.append(("approver 2026-10-24: a release self-cured stop is in RUN_RECORD.md (its stop list and \"Stops "
                       "cleared without you\"), never in the report or the summary; the human's and the delegated "
                       "stops stay on the summary",
                       "CUREDQZ" in rr_txt and "| S5 |" in rr_txt.split("Stops cleared without you", 1)[-1]
                       and "CUREDQZ" not in md_r and "S5" not in _sm_r and "- stop S4 —" in _sm_r
                       and "- stop S3 —" in _sm_r))
        # the same stops alone (the other stand-ins above set fixture text the comparison is not about): the long
        # answers in the box and in the stop list
        _sr_full = [dict(r_, **({"by": r_["by"]})) for r_ in [
            {"stop": "S3", "date": "2026-10-19", "round": None, "classes": ["mechanical"], "human": False,
             "what": "`python3 audits/lanecheck.py` exited 1: PROBLEM[stray-loop] x",
             "by": "the operator (delegated): QZDONE killed the loop" + LONGANS, "done": "closed"},
            {"stop": "S4", "date": "2026-10-19", "round": None, "classes": ["tamper"], "human": True,
             "what": "integrity FAIL[ownership] STOPQZ", "by": "the human (answer, verbatim: \"HUMANSTALLQZ" + LONGANS + "\")",
             "done": "closed"}]]
        _st.stop_rows = lambda c_, rd=None, phase=None: _sr_full
        try:
            with contextlib.redirect_stdout(io.StringIO()) as _o_box:
                build(cfg, False)
            import decisions as _dcb
            _sp_b, project.REPO = project.REPO, tmp
            try:
                _bl_full = _dcb.box_lines(cfg)       # DECISIONS.md's box: the stops in full too
                _fm_box = front_matter(cfg)[0]
            finally:
                project.REPO = _sp_b
        finally:
            _st.stop_rows = _keep_sr
        checks.append(("each stop cleared without the human is listed with its stop, cause class, what was done and "
                       "outcome -- in RUN_RECORD.md, never in the report (approver 2026-10-24)",
                       all(x in rr_txt for x in ("| S3 |", "QZDONE", "mechanical", "passes at the close"))
                       and "None: no stop was cleared" not in rr_txt and "| S3 |" not in md_r and "QZDONE" not in md_r))
        checks.append(("FF10b: front_matter's box (no longer printed in REPORT.md since B10, still its API) lists a "
                       "stop answered by the human and one closed as delegated",
                       any(b_.startswith("stop S4 (tamper; answered by the human)") for b_ in _fm_box)
                       and any(b_.startswith("stop S3 (mechanical; closed by the operator, delegated)") for b_ in _fm_box)))
        _box_r = open(os.path.join(tmp, "R", SUMMARY_MD)).read() if os.path.exists(os.path.join(tmp, "R", SUMMARY_MD)) else ""
        checks.append(("final fixes (B10: in the one-page summary, the page-1 box's successor): every stop answered by "
                       "the human or closed as delegated is listed on one line, who closed it, and the human's answer "
                       "under \"Answers recorded as yours\" (a long one: its first sentence and the place of the full "
                       "text, never a cut word); the DECISIONS box quotes both in full",
                       "- stop S3 — mechanical; `python3 audits/lanecheck.py` exited 1; closed by the operator "
                       "(delegated) (REPORT §9)" in _box_r
                       and "- stop S4 — tamper; closed by your answer (below) (REPORT §" in _box_r
                       and re.search(r"^- stop decision 2026-10-19 stop S4 — “HUMANSTALLQZ.*ANSENDQZ”", _box_r, re.M)
                       is not None and _box_r.count("ANSENDQZ") == 1 and not clipped_lines(_box_r)
                       and sum("ANSENDQZ" in b_ for b_ in _bl_full) == 2))
        checks.append(("every stop is listed in RUN_RECORD.md, a STOP class and a human answer included (review H3); "
                       "the human's answer is in the report too (its decisions)",
                       all(x in rr_txt for x in ("| S4 |", "STOPQZ", "HUMANSTALLQZ", "tamper"))))
        checks.append(("L4: every repair-lock is listed with the stops (RUN_RECORD.md)",
                       "| repair R1 |" in rr_txt and "REPAIRQZ" in rr_txt and "REPAIRQZ" not in md_r))
        checks.append(("every set-aside is listed with its inventory, its carried items and its reason (RUN_RECORD.md, "
                       "not the report)",
                       all(x in rr_txt for x in ("SAREASONQZ", "K.carried (Fail)", SET_ASIDE_TITLE))
                       and "SAREASONQZ" not in md_r))
        checks.append(("the human's decisions at stops and every [DELEGATED] decision are listed in full, never cut "
                       "mid-word (a test run)", "HUMANQZ" in md_r and "DELEGENDQZ" in md_r))
        # DELEGENDQZ, not ENDQZ: the box's ANSENDQZ (final fixes 9) contains ENDQZ and let a cut list pass (SR-MR4)
        checks.append(("an unsettled (here abandoned) re-vote is listed with the open questions",
                       "Paper.probDist_single" in md_r and "REVOTEREASONQZ" in md_r and "re-vote lane ABANDONED" in md_r))
        checks.append(("the proof-routes section lists replaced routes and, without DEPENDENCIES.json, says the walk "
                       "was not computed", f". {ROUTES_TITLE}" in md_r and "Not computed: no DEPENDENCIES.json" in md_r))
        checks.append(("a record's own '##' headings are demoted in the markdown (bold lines, never the report's numbering)",
                       demote_headings("## Not defects\ntext\n### Sending these") == "**Not defects**\ntext\n**Sending these**"))
        _pk = project.REPO
        try:
            project.REPO = tmp
            rab = os.path.join(tmp, "R", "2026-01-05-full-abcdef0"); os.makedirs(rab, exist_ok=True)
            json.dump({"round": "2026-01-05-full-abcdef0", "date": "2026-01-05", "reason": "x", "delegated": True,
                       "files": {"a.json": "x"}, "lanes": {"substantiveness@1.json": "unsealed"},
                       "carried": [{"lane": "substantiveness@1.json", "item": "K.hfs_comp_add", "verdict": "Fail"}]},
                      open(os.path.join(rab, project.ABANDONED), "w"))
            ar_ = setaside_row(cfg)
            open(os.path.join(rab, "ADOPTED.md"), "w").write("- CLEARED substantiveness.json: CLRQZ advice text\n")
            cl_ = all_clearances(cfg)
            open(os.path.join(tmp, "R", "RUN_LOG.md"), "w").write(
                "# Run log\n## Open questions\n- integrity failed on round x: archive? (answered 2026-10-19: STOPQZ archive them)\n"
                "- [DELEGATED 2026-10-19, operator under hands-off (intake); reversal: none] kept y — z\n")
            as_ = all_stops(cfg)
            import integrity as _ig
            _rfc = _ig.record_fix_commits
            _ig.record_fix_commits = lambda *a_: [("f" * 40, "2026-01-02-abcdef1", "2026-10-21",
                                                   [("PAPER_DEFECTS.md", "2", "lean witness")], [])]
            try:
                as_rf = all_stops(cfg)
                _ig.record_fix_commits = lambda *a_: [("e" * 40, "2026-01-02-abcdef1", "2026-10-21",
                                                       [("VACUOUS.md", "1", "why")], ["it stores no fault it cures"])]
                as_bad, rf_bad = all_stops(cfg), record_fix_problems(cfg)
            finally:
                _ig.record_fix_commits = _rfc
            checks.append(("re-check R1: a 'record-fix' commit that is not a record correction blocks the report "
                           "check (record-fix-diff) and its stop row says so",
                           [f_.code for f_ in rf_bad] == ["record-fix-diff"]
                           and any("NOT a record correction" in r_[2] and "no verdict" not in r_[2] for r_ in as_bad)))
            checks.append(("S1: every record correction is disclosed with the stops: its round, cell and commit",
                           any(r_[0] == "record-fix 2026-01-02-abcdef1" and "PAPER_DEFECTS.md row 2 'lean witness'"
                               in r_[2] and "ffffffffff" in r_[5] for r_ in as_rf)))
            os.remove(os.path.join(tmp, "R", "RUN_LOG.md"))
            json.dump({"fingerprints": {"K.a": "1", "K.b": "2", "K.c": "3"}}, open(os.path.join(tmp, "fp.json"), "w"))
            sc_ = statement_changes(os.path.join(tmp, "fp.json"), {"K.a": "1", "K.b": "9", "K.d": "4"})
            sc2_ = statement_changes(os.path.join(tmp, "fp.json"), {"K.a": "1", "K.b": "9", "K.d": "4"},
                                     {"K.c": "3", "K.helper": "5"})
            json.dump({"commit": "zzz", "goal_results": ["Theorem 1.2"], "unused": [{"result": "Lemma 4.1", "lean": "K.lemma_4_1"}],
                       "missing": ["K.gone_name"]},
                      open(os.path.join(tmp, "R", "DEPENDENCIES.json"), "w"))
            pr_ = proof_routes(cfg, [["R1", "Lemma 1.5", "rounding", "discrete", "simpler", "same strength"]],
                               ["#", "result", "the paper's route", "the lean route", "why different", "kind"])
            _hd = globals()["human_decisions"]
            globals()["human_decisions"] = lambda c_: ["Checkpoint A: x", "a stop answered by the human: y"]
            wd_ = who_decided(cfg, "hands-off")
            globals()["human_decisions"] = lambda c_: ["Checkpoint A: x"]
            wd0_ = who_decided(cfg, "hands-off")
            globals()["human_decisions"] = _hd
        finally:
            project.REPO = _pk
            shutil.rmtree(os.path.join(tmp, "R", "2026-01-05-full-abcdef0"), ignore_errors=True)
            if os.path.exists(os.path.join(tmp, "R", "DEPENDENCIES.json")):
                os.remove(os.path.join(tmp, "R", "DEPENDENCIES.json"))
        _pk2 = project.REPO
        try:
            project.REPO = tmp
            rsg = os.path.join(tmp, "R", "2026-01-06-abcdef1"); os.makedirs(rsg, exist_ok=True)
            json.dump({"_meta": {"kind": "statements"}}, open(os.path.join(rsg, "TARGET.json"), "w"))
            json.dump({"global": [{"id": "G1", "title": "tvDist for any function", "text": "GTEXTQZ"}]},
                      open(os.path.join(rsg, "SIGNOFF.json"), "w"))
            gd_ = global_differences(cfg)
        finally:
            project.REPO = _pk2
            shutil.rmtree(os.path.join(tmp, "R", "2026-01-06-abcdef1"), ignore_errors=True)
        checks.append(("global differences (G1, ...) of the sign-off sheet are defined in the report",
                       gd_ and gd_[0][0] == "G1" and "GTEXTQZ" in gd_[0][1]))
        checks.append(("the report never claims the statements were approved before any proof was written",
                       "before any proof" not in md_r and "approved at a checkpoint (Checkpoint B)" in md_r))
        checks.append(("review 2 N7: every stop raised without a stop record (RUN_LOG open questions) is listed; delegated "
                       "lines are not stops", any(r[0] == "no stop record" and "STOPQZ" in r[2] and r[4] == "the human" for r in as_)
                       and not any("kept y" in r[2] for r in as_)))
        checks.append(("review 2 N8: statement changes between the first statement round and the approval are named",
                       sc_ == ["`K.b` changed", "`K.d` added", "`K.c` removed"]))
        checks.append(("a declaration the approval does not list, still in the approved round, is not 'removed'",
                       sc2_ == ["`K.b` changed", "`K.d` added"]))
        checks.append(("a set-aside round is in the trust table, with the Fail items it carried forward, by name",
                       "SET ASIDE" in ar_[2] and "K.hfs_comp_add (Fail)" in ar_[2]))
        checks.append(("every independence clearance is listed with its reason",
                       cl_ == [("2026-01-05-full-abcdef0", "substantiveness.json", "CLRQZ advice text")]))
        checks.append(("proof routes: a replaced route and a result the goals do not use (from DEPENDENCIES.json) are "
                       "listed; a walk at another commit says so",
                       pr_["replaced"] and "Lemma 1.5" in pr_["replaced"][0] and pr_["unused"]
                       and "K.lemma_4_1" in pr_["unused"][0] and "computed at commit zzz" in pr_["unused"][0]
                       and any("NOT CHECKED" in x and "K.gone_name" in x for x in pr_["unused"])))
        checks.append(("who decided: with a human answer at a stop, the report never says no human decided",
                       "attributes 1 answer(s), approval(s) or stop decision(s)" in wd_ and "no human took" not in wd_.lower()
                       and "Apart from the setup at Checkpoint A, no human took" in wd0_))
        checks.append(("the stale-line-numbers list the background points to always exists (none when empty)",
                       "**Stale line numbers in adjudicator records:** none." in md_ or "Stale line numbers in adjudicator records" in md_))
        open(os.path.join(tmp, "R", "DEVIATIONS.md"), "w").write(
            "| # | result | paper | lean | why |\n|---|---|---|---|---|\n| R1 | Theorem 1.1 | a | b | c |\n")
        out_ = io.StringIO()
        with contextlib.redirect_stdout(out_):
            rc_k = build(cfg, False)
        checks.append(("a record table without its key column is reported, not dropped silently",
                       rc_k == 1 and "DEVIATIONS.md: it has a table, but no table header has a `kind` column"
                       in out_.getvalue()))
        os.remove(os.path.join(tmp, "R", "DEVIATIONS.md"))
        # --- H4: page-1 box, background, header-driven entries, vacuous section ---
        saved_pr = project.REPO; project.REPO = tmp
        try:
            open(os.path.join(tmp, "R", "PAPER_DEFECTS.md"), "w").write(
                "# Defects\n\n| | meaning | what the authors would do |\n|---|---|---|\n| **S1** | false as printed | correct it |\n\n"
                "Round note: Observation 9.9 is false as printed (witness `w`); Theorem 1.1 too.\n\n"
                "| # | where | status | repair | what the paper says | why it is wrong | Lean witness | consequence | decision |\n"
                "|---|---|---|---|---|---|---|---|---|\n| 1 | tex 3 (Theorem 1.1) | false | substantial | says X | WRONGSUMMARY e.g. here. More. | `thm_1_1` | survives | REPAIR-DECIDED by the human |\n")
            open(os.path.join(tmp, "R", "VACUOUS.md"), "w").write(
                "| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
                "|---|---|---|---|---|---|---|\n| 1 | Lemma 9.9 | all | setting empty | KEEP-AS-CONTRADICTION | FOUND-MARK | open |\n")
            open(os.path.join(tmp, "R", "DEVIATIONS.md"), "w").write(
                "| # | result | the paper's route | the Lean route | why different | kind | decided by |\n"
                "|---|---|---|---|---|---|---|\n| R1 | Theorem 1.1 | a | b | c | paper step fails | EXTRA-COLUMN |\n"
                # enough failing routes that the box cannot fit on one page: it must break, not clip
                + "".join(f"| R{i} | Theorem 1.1 | a | b | a long reason that takes some room on the line, number {i} | "
                          f"paper step fails | x |\n" for i in range(2, 45)))
            idx(["| Theorem 1.1 | `thm_1_1` |"])
            ap4 = os.path.join(tmp, "R", "APPROVED_FINGERPRINTS.json")
            ap4_old = open(ap4).read() if os.path.exists(ap4) else None
            if ap4_old is not None:
                os.remove(ap4)
            box_, bg_ = front_matter(cfg)
            json.dump({"by": "agent", "rows": {}}, open(ap4, "w"))
            box_ag, _ = front_matter(cfg)
            if ap4_old is not None:
                open(ap4, "w").write(ap4_old)
            else:
                os.remove(ap4)
            checks.append(("the box says when the agent, not a human, approved the statements",
                           any("NOT approved by a human (the agent approved them" in b for b in box_ag)))
            checks.append(("the box lists defects (with what is wrong), failing routes and open vacuous "
                           "statements, each with the section of its details",
                           any(b.startswith("defect 1:") and "WRONGSUMMARY e.g. here." in b and "More" not in b
                               and "section 5" in b for b in box_)
                           and any(b.startswith("proof route R1: Theorem 1.1") and "section 6" in b for b in box_)
                           and any(b.startswith("vacuous: Lemma 9.9") and "section 7" in b for b in box_)))
            checks.append(("the box says when no human approved the statements",
                           any("NONE -- no one has approved" in b for b in box_)))
            # --- involvement levels: who decided after the intake (RUN.md, question 5c) ---
            rl_ = os.path.join(tmp, "R", "RUN_LOG.md")
            tag_ = "[DELEGATED 2026-01-0{}, operator under hands-off (intake); reversal: none] "
            open(rl_, "w").write(
                "# Run log\n## Open questions\n- " + tag_.format(3) + "keep hypothesis hX as in the paper — DGAQZ\n"
                "## Checkpoint C (2026-01-04, delegated)\n- check:x: " + tag_.format(4) + "drop nothing — DGBQZ\n"
                "## Answered\n- answered check:x (2026-01-04, r): " + tag_.format(4) + "drop nothing — DGBQZ\n"
                "## Fresh readers\n- dismissed: quoting " + tag_.format(5) + "FRQZ\n")
            hcfg_ = dict(cfg, involvement="hands-off", involvement_answer="(c) hands-off ANSQZ")
            json.dump({"by": "agent", "how": "blanket", "date": "2026-01-02", "commit": "c",
                       "rows": {"Theorem 1.1": {"status": "approved"}}}, open(ap4, "w"))
            try:
                tr_h = {r[0]: (r[1], r[2]) for r in trust_rows(hcfg_)}
                box_h, bg_h = front_matter(hcfg_)
                tr_i = {r[0]: (r[1], r[2]) for r in trust_rows(cfg)}
                dp_i = delegation_problems(cfg)
                os.remove(rl_)
                box_i, bg_i = front_matter(cfg)
                tr_i2 = {r[0]: (r[1], r[2]) for r in trust_rows(cfg)}
                dp_ok = delegation_problems(cfg) + delegation_problems(hcfg_)
            finally:
                os.remove(ap4)
                if ap4_old is not None:
                    open(ap4, "w").write(ap4_old)
                if os.path.exists(rl_):
                    os.remove(rl_)
            dst_ = tr_h.get("Decisions after the intake", ("", ""))[1]
            checks.append(("hands-off: the trust section names the level, quotes the intake answer, says no human "
                           "reviewed the statements, and points to the full list of [DELEGATED] decisions",
                           "hands-off" in dst_ and "ANSQZ" in dst_ and "No human reviewed the Lean statements" in dst_
                           and "2 decision(s)" in dst_ and "listed in full in section" in dst_
                           and "reversal cost" in dst_ and "reversible" not in dst_
                           and "FRQZ" not in dst_ and "DECISIONS.md" in dst_))
            checks.append(("hands-off: the agent approval says the human chose it at intake, not at Checkpoint B",
                           "hands-off involvement level the user chose at intake" in tr_h["Approval of statements"][0]
                           and "NOT reviewed by a human" in tr_h["Approval of statements"][0]))
            checks.append(("hands-off: the box says how many decisions were taken on the reader's behalf, and where",
                           any(b.startswith("decisions taken on your behalf: 2 decision(s)")
                               and os.path.join(tmp, "R", "DECISIONS.md") in b and "ANSQZ" in b
                               and f'section "{DECIDED_TITLE}"' in b and "section 1" not in b for b in box_h)
                           and any("under the hands-off involvement level" in b for b in box_h)))
            checks.append(("hands-off: the background explains [DELEGATED] and a delegated Checkpoint C",
                           "[DELEGATED]" in " ".join(p_ for _, p_ in bg_h)
                           and "the operator took the remaining decisions" in " ".join(p_ for _, p_ in bg_h)))
            checks.append(("[DELEGATED] decisions under the involved level are a report problem, and are still disclosed",
                           dp_i != [] and "INCONSISTENT" in tr_i.get("Decisions after the intake", ("", ""))[1]))
            checks.append(("the involved level with no [DELEGATED] decision: report unchanged (no row, no box line)",
                           "Decisions after the intake" not in tr_i2 and dp_ok == []
                           and not any(b.startswith("decisions taken") for b in box_i)
                           and "[DELEGATED]" not in " ".join(p_ for _, p_ in bg_i)
                           and "on the human's instruction" in " ".join(box_i)))
            checks.append(("an invalid involvement level is a report problem",
                           delegation_problems(dict(cfg, involvement="hands-free")) != []))
            # adversarial (hands-off review, B4/B5, items 5 and 9)
            json.dump({"by": "agent", "how": "blanket", "date": "2026-01-02", "commit": "c",
                       "rows": {"Theorem 1.1": {"status": "approved"}}}, open(ap4, "w"))
            scfg_ = dict(cfg, involvement="statements-only", involvement_answer="(b)")
            try:
                tr_s = {r[0]: (r[1], r[2]) for r in trust_rows(scfg_)}
                dp_s = delegation_problems(scfg_)
                box_s, _ = front_matter(scfg_)
                ncfg_ = dict(cfg, involvement="hands-off")
                dp_n = delegation_problems(ncfg_)
                open(rl_, "w").write("# Run log\n## Open questions\n- [Delegated 2026-01-03] keep x\n")
                dp_t = delegation_problems(hcfg_)
            finally:
                os.remove(ap4)
                if ap4_old is not None:
                    open(ap4, "w").write(ap4_old)
                if os.path.exists(rl_):
                    os.remove(rl_)
            checks.append(("statements-only: an agent approval is a report problem, never worded as chosen at intake",
                           any("statements-only" in p_ and "not by a human" in p_ for p_ in dp_s)
                           and "chose at intake" not in tr_s["Approval of statements"][0]
                           and "NOT allowed at this level" in tr_s["Approval of statements"][0]
                           and any(b.startswith("statement approval:") and "does not allow" in b for b in box_s)))
            checks.append(("a delegating level with no recorded intake answer is a report problem",
                           any("involvement_answer" in p_ for p_ in dp_n)))
            checks.append(("a non-canonical [DELEGATED] tag in RUN_LOG.md is a report problem",
                           any("canonical" in p_ for p_ in dp_t)))
            checks.append(("the background gives absolute paths and explains rounds and terms",
                           any(f"repository `{tmp}`" in p_ for _, p_ in bg_) and any("YYYY-MM-DD-<commit>" in p_ for _, p_ in bg_)
                           and any("[PROXY]" in p_ for _, p_ in bg_)
                           and any("*F10*" in p_ and "*F12*" in p_ and "*probe*" in p_ for _, p_ in bg_)))
            with contextlib.redirect_stdout(io.StringIO()):
                build(cfg, False)
            md4 = open(os.path.join(tmp, "R", "REPORT.md")).read()
            checks.append(("B10 (U2 §6.1): REPORT.md opens with section 0, the pointer to the summary, before the "
                           "background and everything else; no page-1 box",
                           SUMMARY_POINTER in md4 and "**What this is.**" in md4 and "READ THIS FIRST" not in md4
                           and md4.index(SUMMARY_POINTER) < md4.index("**What this is.**") < md4.index("**Generated")))
            checks.append(("the vacuous section shows each statement with its decision",
                           "FOUND-MARK" in md4[md4.find("## 7."):]
                           and "## 7. Statements true only vacuously" in md4 and "KEEP-AS-CONTRADICTION" in md4))
            _s5 = md4[md4.find("## 5."):md4.find("## 6.")]
            _h5 = next((l_ for l_ in _s5.splitlines() if l_.startswith("| ")), "")
            checks.append(("with a legend table first, the defects table is found by its key column (details kept)",
                           "WRONGSUMMARY" in _s5 and "| what the paper says |" in _h5 and "Meaning" not in _h5))
            buf4 = io.StringIO()
            with contextlib.redirect_stdout(buf4):
                rc4 = build(cfg, True)
            checks.append(("the report check flags a defect stated only in prose",
                           "Observation 9.9 is called false as printed" in buf4.getvalue()))
            pr4 = prose_only_defects(os.path.join(tmp, "R", "PAPER_DEFECTS.md"))
            checks.append(("a defect stated only in prose is flagged; the legend is not",
                           len(pr4) == 1 and "Observation 9.9" in pr4[0]))
            sm4 = open(os.path.join(tmp, "R", SUMMARY_MD)).read()
            _k4 = [k_ for k_ in disclosure_keys(cfg) if k_.group != "Results"]
            _cnt4 = " ".join(l_ for l_ in sm4.splitlines() if COUNTED_RE.match(l_))
            checks.append(("B10: every disclosure is listed in SUMMARY.md, or counted by name with "
                           "the place of its full text, and the coverage check passes on it; the summary says how its PDF "
                           "is made and where that check's outcome is told (PDF-AGENTS)",
                           bool(_k4) and summary_problems(cfg, sm4) == [] and "- " + PDF_LINE in sm4
                           and all((_line(k_) in sm4)
                                   or (f"- {k_.prefix} (" in _cnt4 and k_.ident in _cnt4) for k_ in _k4)))
            gl = globals(); saved_lr = gl["later_row"]
            gl["later_row"] = lambda c: ("Changes after the last audit round", "x", "1 commit(s) since ... NOT re-audited")
            try:
                box_lr, _ = front_matter(cfg)
            finally:
                gl["later_row"] = saved_lr
            checks.append(("the box says when Lean changed after the last audit round",
                           any("Lean changes after the last audit round" in b for b in box_lr)))
            json.dump({"rows": {}}, open(ap4, "w"))
            buf_nb = io.StringIO()
            with contextlib.redirect_stdout(buf_nb):
                rc_nb = build(cfg, True)
            rc_nb = 1 if "records no approver" in buf_nb.getvalue() else 0
            if ap4_old is not None:
                open(ap4, "w").write(ap4_old)
            else:
                os.remove(ap4)
            checks.append(("an approval record without its approver fails the report check", rc_nb == 1))
            checks.append(("a record column the generator does not know is still shown",
                           "EXTRA-COLUMN" in md4 and "REPAIR-DECIDED" in md4))
        finally:
            project.REPO = saved_pr
            for f_ in ("PAPER_DEFECTS.md", "VACUOUS.md", "DEVIATIONS.md"):
                if os.path.exists(os.path.join(tmp, "R", f_)):
                    os.remove(os.path.join(tmp, "R", f_))
        hs_ = ["#", "what", "reason", "what it would take", "how this was checked", "decided by"]
        mt_bad = missing_theory_problems(cfg, hs_, [["1", "Thm 9.9, second half", "Mathlib has no graphons", "x",
                                                     "grep over Mathlib", "adjudicator"]])
        mt_ok = missing_theory_problems(dict(cfg, libraries=["Mathlib", "Tau Ceti"]), hs_,
                                        [["1", "Thm 9.9, second half", "Mathlib has no graphons", "x",
                                          "grep over Mathlib and TauCeti (2026-10-13)", "human (2026-10-13)"]],
                                        run_log="## Answered\n- answered skip:thm-9-9 (2026-10-13, r): Thm 9.9, second "
                                                "half: skip it\n")
        mt_other = missing_theory_problems(cfg, hs_, [["2", "Thm 1.5", "cited, unused", "x", "grep", "adjudicator"]])
        sk_p = os.path.join(tmp, "R", "SKIPPED.md"); sk_old = open(sk_p).read() if os.path.exists(sk_p) else None
        open(sk_p, "w").write("| # | what | reason | what it would take | how this was checked | decided by |\n"
                              "|---|---|---|---|---|---|\n| 1 | Lemma 1.2 | Mathlib has no graphons | x | grep | adjudicator |\n")
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | not formalized |"])
        import io, contextlib
        buf_mt = io.StringIO()
        with contextlib.redirect_stdout(buf_mt):
            build(cfg, True)
        if sk_old is None:
            os.remove(sk_p)
        else:
            open(sk_p, "w").write(sk_old)
        checks.append(("the report check runs the missing-theory rule", "missing library theory" in buf_mt.getvalue()))
        checks.append(("missing-theory phrasings are recognised; unrelated reasons are not",
                       all(MISSING_THEORY_RE.search(x) for x in (
                           "Mathlib doesn't have graphons", "not in Mathlib", "Mathlib does not yet define X",
                           "not available in Mathlib", "isn't formalized in Mathlib", "requires results beyond the library",
                           "no graph limit theory exists", "Mathlib has no graphons"))
                       and not any(MISSING_THEORY_RE.search(x) for x in (
                           "cited for context only; no proof uses it", "outside the numbered results"))))
        mt_d = [["1", "x", "Mathlib has no graphons", "x", "Mathlib TauCeti",
                 "operator [DELEGATED 2026-01-01, operator under hands-off (intake); reversal: none]"]]
        mt_dl = "## Open questions\n- x: " + mt_d[0][5][9:] + " take x as a named hypothesis\n"
        checks.append(("a missing-theory skip decided as [DELEGATED] is accepted only when the level delegates",
                       missing_theory_problems(dict(cfg, involvement="hands-off"), hs_, mt_d, run_log=mt_dl) == []
                       and missing_theory_problems(cfg, hs_, mt_d) != []
                       and missing_theory_problems(cfg, hs_, mt_d, run_log=mt_dl) != []))
        checks.append(("a missing-theory skip needs the dated, canonical [DELEGATED] tag, not a bare one",
                       missing_theory_problems(dict(cfg, involvement="hands-off"), hs_,
                                               [mt_d[0][:5] + ["operator [DELEGATED]"]]) != []
                       and missing_theory_problems(dict(cfg, involvement="hands-off"), hs_,
                                                   [mt_d[0][:5] + ["operator [DELEGATED]"]], run_log=mt_dl) != []))
        # sweep N1: "decided by" is bound to a recorded decision; the adjudicator cannot type one
        mt_r = lambda dec, log: missing_theory_problems(cfg, hs_, [["1", "Lemma 2.3", "Mathlib has no graphons", "x",
                                                                     "Mathlib TauCeti", dec]], run_log=log)
        ans_ = "## Answered\n- answered skip:lemma-2-3 (2026-10-20, r): skip Lemma 2.3\n"
        fab_ = mt_r("human (2026-10-21)", "")
        checks.append(("N1: a typed 'human (<date>)' with no RUN_LOG answer naming the result is refused, routed to a "
                       "QUESTION row (adj-record)",
                       len(fab_) == 1 and fab_[0].code == "adj-record" and "never type one" in fab_[0]
                       and "QUESTION (<round>)" in fab_[0]))
        wrong_ = mt_r("human (2026-10-21)", ans_)
        checks.append(("N1: a recorded answer binds its own date only; the refusal names the cell to copy",
                       mt_r("human (2026-10-20)", ans_) == [] and len(wrong_) == 1
                       and mt_r("human (2026-10-20)", "## Answered\n- answered question:Lemma_2.3 (2026-10-20, r): "
                                "skip\n") == []
                       and '"human (2026-10-20)"' in wrong_[0]
                       and mt_r("human (2026-10-20)", ans_.replace("Lemma 2.3", "Lemma 2.4")
                                .replace("lemma-2-3", "lemma-2-4")) != []))
        checks.append(("N1: a [PROXY] cell needs a [PROXY] line naming the result",
                       mt_r("operator [PROXY]", "") != []
                       and mt_r("operator [PROXY]", "## Open questions\n- [PROXY 2026-10-20, operator for the "
                                "human; reversible] skip Lemma 2.3\n") == []))
        q_rd = os.path.join(tmp, "R", "2026-10-20-n1q"); os.makedirs(q_rd, exist_ok=True)
        open(os.path.join(q_rd, "ADOPTED.md"), "w").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            "| paper-faithfulness | Lemma 2.3 | Fail | **QUESTION** | build graphons, hypothesise, or skip? |\n")
        q_open = mt_r("QUESTION (2026-10-20-n1q)", "")
        q_ans = mt_r("QUESTION (2026-10-20-n1q)", ans_)
        os.remove(os.path.join(q_rd, "ADOPTED.md")); os.rmdir(q_rd)
        checks.append(("N1: 'QUESTION (<round>)' with its QUESTION row is the human's open question (no finding); "
                       "without the row, or once answered, it is refused",
                       q_open == [] and mt_r("QUESTION (2026-10-20-n1q)", "") != []
                       and len(q_ans) == 1 and '"human (2026-10-20)"' in q_ans[0]))
        checks += _unproved_controls(cfg, tmp, idx)
        checks.append(("'decided by' needs a dated human answer or a [PROXY]",
                       missing_theory_problems(cfg, hs_, [["1", "x", "Mathlib has no graphons", "x", "Mathlib TauCeti", "no human asked"]]) != []))
        checks.append(("a missing-theory skip needs every library searched and the human's decision; others are untouched",
                       any("TauCeti" in p for p in mt_bad) and any("human's decision" in p for p in mt_bad)
                       and mt_ok == [] and mt_other == []))
        checks.append(("restatements are counted and explained (57 rows vs 55 results)",
                       count_text([["Theorem 1.1", "`a`"], ["Lemma 3.1", "`a` (restatement of Theorem 1.1)"]])
                       == "2 index rows (1 numbered result plus 1 restatement of earlier results)"
                       and count_text([["Theorem 1.1", "`a`"]]) == "1 numbered result"))
        # --- release 0.1.0 (A2): what the report reader needs and the generator used to omit ---
        import io as _io, contextlib as _cl
        saved_pr2 = project.REPO; project.REPO = tmp
        try:
            open(os.path.join(tmp, "P", "Src.lean"), "w").write(
                "theorem thm_1_1 : True := trivial\n\n/-- doc -/\nlemma lemma_1_2 : True := trivial\n")
            idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | `lemma_1_2` |", "| Remark 1.3 | not formalized |"])
            open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
                "| # | what | reason |\n|---|---|---|\n| 4 | Remark 1.3 | informal |\n\n"
                "**Update 2026-01-02.** Row 4's reason is stale: see `lemma_1_2`.\n")
            open(os.path.join(tmp, "R", "VACUOUS.md"), "w").write(
                "| # | statement | why |\n|---|---|---|\n| 3 | `thm_1_1` | hypothesis never holds |\n")
            rd_ = os.path.join(tmp, "R", "2026-01-01-abc1234"); os.makedirs(rd_, exist_ok=True)
            open(os.path.join(rd_, "ADOPTED.md"), "w").write(
                "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                "| correspondence | lemma_1_2 | Fail | **QUESTION** | keep the paper's hypothesis? |\n"
                "| substantiveness | thm_1_1 | Fail | **ADOPT** | drop it |\n")
            cfg_a = dict(cfg, standing_defers=[{"id": "d1", "item": "Hyp", "reason": "literature",
                                                "revisit_when": "never"}],
                         glossary=[{"term": "C(G,H)", "meaning": "the domination exponent", "where": "tex l.12"}])
            with _cl.redirect_stdout(_io.StringIO()):
                build(cfg_a, False)
            md_a = open(os.path.join(tmp, "R", "REPORT.md")).read()
            checks.append(("A2: free text below a record's table is in the markdown",
                           "reason is stale" in md_a))
            checks.append(("A2: open QUESTION rows are listed, ADOPT rows are not",
                           "keep the paper's hypothesis?" in md_a and "drop it" not in md_a))
            # cumulative questions (integration 0.2, Codex report issue 4): every unanswered
            # QUESTION of every round, not only the newest round's; final answers stay out
            rq_old = os.path.join(tmp, "R", "2025-12-30-def5678"); os.makedirs(rq_old, exist_ok=True)
            rq_mid = os.path.join(tmp, "R", "2025-12-31-fed8765"); os.makedirs(rq_mid, exist_ok=True)
            open(os.path.join(rq_old, "ADOPTED.md"), "w").write(
                "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                "| non-vacuity | old_open | Fail | **QUESTION** | OLDQ still unanswered? |\n"
                "| correspondence | old_done | Fail | **QUESTION** | OLDA answered by the human? |\n"
                "| correspondence | old_proxy | Fail | **QUESTION** | OLDP proxied only? |\n"
                "| correspondence | old_deleg | Fail | **QUESTION** | OLDD delegated? |\n"
                "| correspondence | re_q | Fail | **QUESTION** | REQ1 first asking |\n"
                "| correspondence | deleg_re | Fail | **QUESTION** | DRQ1 delegated, first asking |\n")
            open(os.path.join(rq_mid, "ADOPTED.md"), "w").write(
                "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                "| substantiveness | re_q | Fail | **QUESTION** | REQ2 asked again after the answer? |\n"
                "| substantiveness | deleg_re | Fail | **QUESTION** | DRQ2 asked again after the delegation? |\n"
                "| substantiveness | mid_q | Fail | **ADOPT** | MIDADOPT not a question |\n")
            # a [DELEGATED] decision answers a question only under a delegating level (review of
            # fix-mini1, H1): these checks run under hands-off; under involved it answers none
            cfg_q = dict(cfg_a, involvement="hands-off", involvement_answer="(c)")
            rlq = os.path.join(tmp, "R", "RUN_LOG.md")
            had_rl = open(rlq).read() if os.path.exists(rlq) else None
            open(rlq, "w").write(
                "# Run log\n## Answered\n"
                "- answered question:old_done (2025-12-30, 2025-12-30-def5678): keep it\n"
                "- answered question:re_q (2025-12-30, 2025-12-30-def5678): keep it too\n"
                "- answered question:old_proxy (2025-12-30, 2025-12-30-def5678): [PROXY 2025-12-30] keep\n"
                "- question:old_deleg: [DELEGATED 2025-12-30, operator under hands-off (intake); "
                "reversal: none] keep — reason\n"
                "- question:deleg_re: [DELEGATED 2025-12-30, operator under hands-off (intake); "
                "reversal: none] keep — reason\n")
            try:
                oq = open_questions(cfg_q)
                oq_inv = open_questions(cfg_a)
                with _cl.redirect_stdout(_io.StringIO()):
                    build(cfg_q, False)
                md_q = open(os.path.join(tmp, "R", "REPORT.md")).read()
            finally:
                if had_rl is None:
                    os.remove(rlq)
                else:
                    open(rlq, "w").write(had_rl)
                for d_ in (rq_old, rq_mid):
                    os.remove(os.path.join(d_, "ADOPTED.md")); os.rmdir(d_)
            checks.append(("questions are cumulative: an unanswered QUESTION of an earlier round is listed "
                           "next to the newest round's",
                           "OLDQ still unanswered?" in md_q and "keep the paper's hypothesis?" in md_q
                           and sorted(q[2] for q in oq) == ["deleg_re", "lemma_1_2", "old_open", "old_proxy", "re_q"]))
            checks.append(("questions: under involved a [DELEGATED] line answers no question (only the human's do)",
                           {q[2] for q in oq_inv} >= {"old_deleg", "deleg_re"} and "old_done" not in {q[2] for q in oq_inv}))
            checks.append(("questions: a question asked again after a [DELEGATED] decision is listed again, "
                           "with only the later asking",
                           "DRQ2 asked again after the delegation?" in md_q and "DRQ1" not in md_q
                           and "decided as [DELEGATED]" in md_q))
            # same-day re-ask after a delegation (verify3 MED-LOW 4): rounds of one day, in order
            rq_d1 = os.path.join(tmp, "R", "2026-02-01-aaa1111"); rq_d2 = os.path.join(tmp, "R", "2026-02-01-full-bbb2222")
            for d_, txt in ((rq_d1, "SDQ1 first asking"), (rq_d2, "SDQ2 asked again the same day")):
                os.makedirs(d_, exist_ok=True)
                open(os.path.join(d_, "ADOPTED.md"), "w").write(
                    "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                    f"| correspondence | same_day | Fail | **QUESTION** | {txt} |\n")
            had_rl2 = open(rlq).read() if os.path.exists(rlq) else None
            open(rlq, "w").write("# Run log\n## Answered\n- question:same_day: [DELEGATED 2026-02-01, operator under "
                                 "hands-off (intake); reversal: none] keep — reason\n")
            try:
                sd = [q for q in open_questions(cfg_q) if q[2] == "same_day"]
            finally:
                for d_ in (rq_d1, rq_d2):
                    os.remove(os.path.join(d_, "ADOPTED.md")); os.rmdir(d_)
                if had_rl2 is None:
                    os.remove(rlq)
                else:
                    open(rlq, "w").write(had_rl2)
            checks.append(("questions: a same-day re-ask after a [DELEGATED] decision is listed (round order)",
                           [q[3] for q in sd] == ["SDQ2 asked again the same day"]))
            # asked in X (day 1), again in Y (day 2), delegated on day 2 after Y: answered, not open
            rq_x = os.path.join(tmp, "R", "2026-03-01-ccc3333"); rq_y = os.path.join(tmp, "R", "2026-03-02-ddd4444")
            for d_, txt in ((rq_x, "XYQ1 day one"), (rq_y, "XYQ2 day two")):
                os.makedirs(d_, exist_ok=True)
                open(os.path.join(d_, "ADOPTED.md"), "w").write(
                    "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                    f"| correspondence | x_then_y | Fail | **QUESTION** | {txt} |\n")
            had_rl3 = open(rlq).read() if os.path.exists(rlq) else None
            open(rlq, "w").write("# Run log\n## Answered\n- question:x_then_y: [DELEGATED 2026-03-02, operator under "
                                 "hands-off (intake); reversal: none] keep — reason\n")
            try:
                xy = [q for q in open_questions(cfg_q) if q[2] == "x_then_y"]
            finally:
                for d_ in (rq_x, rq_y):
                    os.remove(os.path.join(d_, "ADOPTED.md")); os.rmdir(d_)
                if had_rl3 is None:
                    os.remove(rlq)
                else:
                    open(rlq, "w").write(had_rl3)
            checks.append(("questions: asked on day 1 and day 2, delegated on day 2 after both: not open", xy == []))
            checks.append(("questions: an answered question asked again lists only the later asking",
                           "REQ1 first asking" not in md_q))
            checks.append(("questions: an answered question asked again in a later round is listed again",
                           "REQ2 asked again after the answer?" in md_q and "asked again since" in md_q))
            checks.append(("questions: a final answer (human or [DELEGATED]) keeps a question out; "
                           "a [PROXY] answer does not",
                           "OLDA" not in md_q and "OLDD" not in md_q and "OLDP proxied only?" in md_q
                           and "provisional [PROXY] answer" in md_q))
            checks.append(("questions: each row names its round",
                           "| 2025-12-30-def5678 | non-vacuity | old_open |" in md_q))
            # small-paper run (mini1): a decided VACUOUS row read as open; [DELEGATED] items set in
            # the margin; raw LaTeX and a stale line in a QUESTION row
            vq_ = os.path.join(tmp, "R", "VACUOUS.md")
            had_vq = open(vq_).read()
            open(vq_, "w").write("| # | statement | why | status |\n|---|---|---|---|\n"
                                 "| 3 | `thm_1_1` | hypothesis never holds | open |\n")
            # trial #11: a defect row's decision cell "left to the human", decided since by an anchored line (logged
            # without the anchor's version, as the operator did)
            pdq_ = os.path.join(tmp, "R", "PAPER_DEFECTS.md")
            had_pdq = open(pdq_).read() if os.path.exists(pdq_) else None
            open(pdq_, "w").write(
                "## Defects\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
                "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
                "| 1 | Theorem 1.1, tex l.1 | vacuous | none (intent unknown) | If A then B. | A never holds. | none: "
                "confirmed by argument (x) | none | Kept as printed. Whether to add a companion is left to the human. "
                "Decided by the adjudicator of round 2026-01-01-abc1234. | 2026-01-01-abc1234 |\n")
            import decisions as _dq
            _dh, _dc = _dq.defect_rows(os.path.join(tmp, "R"))[0]
            _da = _dq.defect_anchor(_dh, _dc).split("@")[0]
            open(rlq, "w").write(
                "# Run log\n## Open questions\n[DELEGATED 2026-01-02, operator under hands-off (intake); "
                "reversal: re-approve] keep K.thm_1_1 as stated (QUESTION row on thm_1_1, round 2026-01-01-abc1234) — VQZ\n"
                f"- {_da}: [DELEGATED 2026-01-02, operator under hands-off (intake); reversal: new round] add no "
                "companion — DQZ\n")
            open(os.path.join(rd_, "ADOPTED.md"), "w").write(
                "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                "| correspondence | lemma_1_2 | Fail | **QUESTION** | is $n\\in\\mathbb{N}$ meant? "
                "(`lemma_1_2`, Src.lean:1) |\n"
                "| correspondence | thm_1_1 | Fail | **QUESTION** | keep it? |\n")
            try:
                with _cl.redirect_stdout(_io.StringIO()) as out_v:
                    build(dict(cfg_a, involvement="hands-off", involvement_answer="(c)"), False)
                md_v = open(os.path.join(tmp, "R", "REPORT.md")).read()
            finally:
                open(vq_, "w").write(had_vq)
                if had_pdq is None:
                    os.remove(pdq_)
                else:
                    open(pdq_, "w").write(had_pdq)
                os.remove(rlq)
                open(os.path.join(rd_, "ADOPTED.md"), "w").write(
                    "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
                    "| correspondence | lemma_1_2 | Fail | **QUESTION** | keep the paper's hypothesis? |\n"
                    "| substantiveness | thm_1_1 | Fail | **ADOPT** | drop it |\n")
            sm_v = open(os.path.join(tmp, "R", SUMMARY_MD)).read() if os.path.exists(os.path.join(tmp, "R", SUMMARY_MD)) else ""
            checks.append(("mini1: an open VACUOUS row the operator decided since says so, in section 7 and the summary",
                           "| open -- decided since by the operator (RUN_LOG.md): [DELEGATED 2026-01-02" in md_v
                           and re.search(r"^- vacuous \S+ — .*; decided by the operator on your behalf since its row was written", sm_v, re.M) is not None))
            _r5 = md_v.split("## 5.", 1)[-1].split("\n## ", 1)[0]
            checks.append(("trial #11: a defect row's decision cell \"left to the human\" that the operator decided since "
                           "shows the decision, and quotes the deferring sentence as the row's text when written "
                           "(section 5 and the summary's defect line)",
                           "(when this row was written: \u201cWhether to add a companion is left to the human.\u201d)" in _r5
                           and "-- decided since by the operator (RUN_LOG.md): [DELEGATED 2026-01-02" in _r5
                           and "add no companion — DQZ" in _r5 and "decided on an earlier version" not in _r5
                           and re.search(r"^- defect 1 — .*; decided by the operator on your behalf \(REPORT §5\)", sm_v, re.M) is not None))
            # conf1 (C1 audit): no generated line of the fixture's summary or report ends mid-phrase
            checks.append(("conf1: no line of the generated summary or report ends mid-phrase (dangling_lines)",
                           bool(sm_v) and not dangling_lines(sm_v) and not dangling_lines(md_v)))
            _sn_short = since_note(["keep it", "older"])
            checks.append(("trial #7: 'decided since' names the decisions section by title, never 'section 9' (8 or 9 "
                           "depending on the reader notes)",
                           f'on it in section "{DECIDED_TITLE}"' in _sn_short and "section 9" not in _sn_short))
            # review of fix-mini1 (M2): only a decision on THIS row says "decided since"
            ds_ = tempfile.mkdtemp(prefix="ds-"); os.makedirs(os.path.join(ds_, "R"))
            vrow_ = ("| # | statement | why | status |\n|---|---|---|---|\n"
                     "| 1 | `K.thm_1_1` | hypotheses `h : n < 0` never hold (see `Nat.succ_le_iff`) | open |\n")
            open(os.path.join(ds_, "R", "VACUOUS.md"), "w").write(vrow_)
            tg_ = "[DELEGATED 2026-04-02, operator under hands-off (intake); reversal: none]"
            def ds_found(log_, lvl_="hands-off"):
                open(os.path.join(ds_, "R", "RUN_LOG.md"), "w").write(log_)
                _sv = REPO
                globals()["REPO"] = ds_
                try:
                    h_, c_ = vacuous_rows({"rounds_dir": "R"})[0]
                    return decided_since({"rounds_dir": "R", "involvement": lvl_}, h_, c_)
                finally:
                    globals()["REPO"] = _sv
            import decisions
            h0_, c0_ = decisions.table_rows(vrow_)[0]
            va_ = decisions.vacuous_anchor(h0_, c0_)
            try:
                checks.append(("review M2: a route decision on another result citing the row's Mathlib lemma is no "
                               "decision on the VACUOUS row", ds_found(
                                   "## Open questions\n- route:K.lemma_4: " + tg_ + " record that the proof of K.lemma_4 "
                                   "uses Nat.succ_le_iff — r\n") == []))
                checks.append(("review M2: a QUESTION-form line on another declaration naming the cited lemma is none either",
                               ds_found("## Open questions\n" + tg_ + " keep K.lemma_4 via Nat.succ_le_iff (QUESTION "
                                        "row on K.lemma_4, round 2026-04-01-abc1234) — r\n") == []))
                checks.append(("review M2: a QUESTION-form line on Other.thm_1_1 is no decision on K.thm_1_1",
                               ds_found("## Open questions\n" + tg_ + " keep Other.thm_1_1 (QUESTION row, round "
                                        "2026-04-01-abc1234) — r\n") == []))
                checks.append(("review M2: a line anchored to this row's vacuous: item, or in the QUESTION form naming "
                               "K.thm_1_1, is a decision on it; under involved neither counts",
                               len(ds_found("## Checkpoint C\n- " + va_ + ": " + tg_ + " keep — r\n")) == 1
                               and len(ds_found("## Open questions\n" + tg_ + " keep K.thm_1_1 (QUESTION row, round "
                                                "2026-04-01-abc1234) — r\n")) == 1
                               and ds_found("## Checkpoint C\n- " + va_ + ": " + tg_ + " keep — r\n", "involved") == []))
                checks.append(("review M2: a line naming K.thm_1_1 outside the QUESTION form, or a tag of another level, "
                               "is none", ds_found("## Open questions\n" + tg_ + " noted the docstring of K.thm_1_1 — r\n") == []
                               and ds_found("## Checkpoint C\n- " + va_ + ": " + tg_ + " keep — r\n", "statements-only") == []))
                checks.append(("re-check M2: a QUESTION line on another item that mentions K.thm_1_1 later is none; "
                               "one whose item is K.thm_1_1 is",
                               ds_found("## Open questions\n- " + tg_ + " keep K.lemma_4 (QUESTION row on K.lemma_4, round "
                                        "2026-04-01-abc1234) — unlike K.thm_1_1\n") == []
                               and ds_found("## Open questions\n- " + tg_ + " keep it via Nat.succ_le_iff (QUESTION row, "
                                            "round 2026-04-01-abc1234) — r\n") == []
                               and ds_found("## Open questions\n- " + tg_ + " keep K.lemma_4 (QUESTION row, round "
                                            "2026-04-01-abc1234) — unlike K.thm_1_1\n") == []
                               and len(ds_found("## Open questions\n- " + tg_ + " keep (QUESTION row on K.thm_1_1, round "
                                                "2026-04-01-abc1234) — r\n")) == 1))
                checks.append(("review M2: a vacuous: anchor of another row is no decision on this one",
                               ds_found("## Checkpoint C\n- vacuous:2-x@abcdef12: " + tg_ + " keep K.thm_1_1 — r\n") == []))
                _ea = re.sub(r"@[0-9a-f]+$", "@00000000", va_)
                _eb = ds_found("## Checkpoint C\n- " + _ea + ": " + tg_ + " keep — r\n")
                checks.append(("mini2-4: a decision anchored to an earlier version of the same VACUOUS.md row (its "
                               "line citations refreshed since) still decides it, and says so",
                               _ea != va_ and len(_eb) == 1 and "earlier version of this row" in _eb[0]))
            finally:
                shutil.rmtree(ds_, ignore_errors=True)
            checks.append(("mini1: an unanchored [DELEGATED] line in the stage2 form decides the QUESTION it names; "
                           "the round's other question stays open",
                           "keep it?" not in md_v and "meant?" in md_v))
            checks.append(("mini1: LaTeX in a QUESTION row is set as code; mini2-B(d): its stale File.lean:N is shown "
                           "at the declaration's current line (no NOTE left to refresh by a round)",
                           "`n\\in\\mathbb{N}`" in md_v and "$n" not in md_v.split("## 8.")[-1]
                           and "(`lemma_1_2`, Src.lean:1)" not in md_v and "`lemma_1_2`, Src.lean:" in md_v
                           and "NOTE QUESTION row on lemma_1_2" not in out_v.getvalue()))
            import lane_auth as _la
            _saved_ri = _la.reissues
            _la.reissues = lambda r: [("abc1234def5678", "correspondence.json", "conversation lost",
                                       ["R/x/.reissued/correspondence.json.1.json"])]
            try:
                ri = reissue_row(cfg_a)
            finally:
                _la.reissues = _saved_ri
            checks.append(("the trust section lists every lane reissue with its reason and kept verdict",
                           "REISSUED" in ri[2] and "conversation lost" in ri[2] and ".reissued/" in ri[2]))
            checks.append(("no reissue: the trust row says none", reissue_row(cfg_a)[2] == "none"))
            checks.append(("approver 2026-10-24: the trust section carries no reissue row (RUN_RECORD.md lists them)",
                           not any(r[0] == "Lane reissues" for r in trust_rows(cfg_a))))
            checks.append(("A2: standing defers are listed with their revisit condition",
                           "| d1 | Hyp | literature | never |" in md_a))
            checks.append(("A2: the config's glossary is rendered", "the domination exponent" in md_a))
            checks.append(("A2: every cited Lean name is located as File.lean:N",
                           "| `lemma_1_2` | `P/Src.lean:4` |" in md_a and "| `thm_1_1` | `P/Src.lean:1` |" in md_a))
            checks.append(("A2: locate_names ignores a name that only appears in a comment",
                           locate_names(dict(cfg, lean_files=["P/Src.lean"]), ["doc"]) == {}))
            # trial #10 audit: a wrong Mathlib name shipped on the sheet and in the report
            _cn = cited_lean_names("Theorem 7.2 is Mathlib's Finset.Foo.card_le. See `Set.Foo.card_le`, "
                                   "`n.choose`, `REPORT.md`, `P/Src.lean:3`, `check:Lemma_7.4`, `Nat.add_comm`.")
            _runs = []
            _stub = lambda out_, rc_=0: (lambda src_: (_runs.append(src_), (rc_, out_))[1])
            _cfg_n = dict(cfg, lean_files=["P/Src.lean"])
            _miss = cited_name_problems(_cfg_n, {"SIGNOFF.md": "Mathlib's `Finset.Foo.card_le`",
                                                 "SUMMARY.md": "`P.doc`"}, run=_stub("MISSING Finset.Foo.card_le\n"))
            _err = cited_name_problems(_cfg_n, {"REPORT.md": "`Q.x`"}, run=_stub("unknown package", 1))
            checks.append(("trial #10 audit: the Lean names a document cites are its dotted code spans and the names after "
                           "\"Mathlib's\" (no file, field access or anchor); one that Lean does not resolve is a problem "
                           "naming the document, a failed Lean run is one too (never a pass)",
                           _cn == ["Finset.Foo.card_le", "Nat.add_comm", "Set.Foo.card_le"]
                           and len(_miss) == 1 and _miss[0].startswith("SIGNOFF.md cites `Finset.Foo.card_le`")
                           and '"Finset.Foo.card_le"' in _runs[0] and "import P.Src" in _runs[0]
                           and len(_err) == 1 and "could not be resolved" in _err[0]))
        finally:
            project.REPO = saved_pr2
            for f_ in ("SKIPPED.md", "VACUOUS.md"):
                if os.path.exists(os.path.join(tmp, "R", f_)):
                    os.remove(os.path.join(tmp, "R", f_))
        checks += _forgery_checks()
        checks += _selftest_one_page()
        # C2 audit (fault (b)): the coverage and status parsers read every index row the freeze and the sheet read
        # (scope.INDEX_ROW), the unnumbered `Definition (notation 𝒬(n), tex l.38-39)` row included, and the count says
        # what it is
        import scope as _sc
        rows_c2 = ["| Definition (notation $\\mathcal{Q}(n)$, tex l.38-39) | `P.P` |", "| Definition 2.1 | `P.M` |",
                   "| Lemma 3.1 | `P.lemma_3_1` |", "| Construction (the family S, tex l.230) | `P.S` |"]
        idx(rows_c2)
        ip_ = os.path.join(tmp, "P", "Main.lean")
        mine = [r[0] for r in table_rows(ip_) if r and RESULT.match(r[0])]
        frozen = [lab for lab, _r in _sc.index_rows(open(ip_, encoding="utf-8").read())]
        checks.append(("C2 audit: every index row the freeze and the sign-off sheet read is a row of the coverage table "
                       "and the statuses (an unnumbered Definition (notation ...) row too), counted as unnumbered",
                       mine == frozen and len(mine) == 4
                       and count_text([[m_] for m_ in mine]) == "4 index rows (2 numbered results plus 2 unnumbered "
                       "definitions or notations the paper introduces in its text)"
                       and count_text([["Lemma 3.1"]]) == "1 numbered result"
                       # the attack review: "Theorem A" is no notation; an unnumbered restatement is counted once
                       and count_text([["Theorem A", "restatement of Theorem 1.1"], ["Theorem 1.1", "z"],
                                       ["Theorem B", "`P.b`"]]) == "3 index rows (1 numbered result plus 1 restatement "
                       "of earlier results plus 1 other unnumbered row (a lettered result such as \"Theorem A\", a remark, a "
                       "condition))"))
        print()
        for n, p in checks:
            print(f"  {'ok  ' if p else 'FAIL'}  {n}")
        ok = all(p for _, p in checks)
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        REPO = keep
        shutil.rmtree(tmp, ignore_errors=True)


def _selftest_one_page():
    """[(name, ok)] of the one-page summary (approver: "one-page summary first"), on a git fixture larger than the
    largest run snapshot (at most 12 results, 2 defects, 2 slips, 7 "not defects",
    3 idle hypotheses, 3 stops with long answers): 30 results, 6 defects, 3 slips, 3 vacuous rows, 7 "not defects",
    3 idle hypotheses, 4 rows not formalized, 5 stops answered at length (one a hand delivery). The page is within
    the line budget, every item is listed or counted by name with the place of its full text, and the coverage
    check refuses a page that drops, changes, invents or miscounts one."""
    import tempfile, shutil, contextlib, io
    global REPO
    keep_r, keep_pr = REPO, project.REPO
    tmp = tempfile.mkdtemp(prefix="onepage-")
    out = []
    try:
        REPO = project.REPO = tmp
        rd = os.path.join(tmp, "R")
        os.makedirs(rd); os.makedirs(os.path.join(tmp, "P"))
        g = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        labels = [f"Lemma {s}.{k}" for s in (2, 3, 4) for k in range(1, 9)] + [f"Theorem 5.{k}" for k in range(1, 7)]
        names = {lb: "lem_" + lb.split()[1].replace(".", "_") if lb.startswith("Lemma") else
                 "thm_" + lb.split()[1].replace(".", "_") for lb in labels}
        open(os.path.join(tmp, "P", "Src.lean"), "w").write(
            "/-!\n| Paper | Lean |\n|---|---|\n" + "".join(f"| {lb} | `{names[lb]}` |\n" for lb in labels) + "-/\n"
            + "".join(f"theorem {names[lb]} : True := trivial\n" for lb in labels))
        cfg = {"name": "t", "source_cite": "A. Author, A long paper (fixture)", "branch": "b", "namespace": "P",
               "rounds_dir": "R", "lean_files": ["P/Src.lean"], "index_file": "P/Src.lean", "mode": "release",
               "involvement": "hands-off", "involvement_answer": "(c)", "goal_results": ["Theorem 5.6"],
               "blind_spots": "the checks do not read the paper"}
        long_ = " ".join(f"word{i}" for i in range(40))
        dh = ("## Defects\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
              "consequence |\n|---|---|---|---|---|---|---|---|\n")
        defs = "".join(f"| {k} | {labels[k]}, tex l.{10 * k} | false | add hypothesis | says X{k}. {long_} | {long_} | "
                       f"none: argument | {long_} |\n" for k in range(1, 7))
        slips = "".join(f"- Proof of {labels[k]}, tex l.{k}. It says x+3; it should say x+2. {long_}\n" for k in (8, 9, 10))
        notd = "".join(f"- {labels[k]} assumes n ≥ 1 although n = 0 also holds. {long_}\n" for k in range(11, 18))
        open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
            dh + defs + "\n## Slips in the proofs (no witness needed)\n" + slips
            + "\n## Not defects, recorded so they are not mistaken for some\n" + notd)
        open(os.path.join(rd, "VACUOUS.md"), "w").write(
            "| # | statement | for which parameters | why | decision | status |\n|---|---|---|---|---|---|\n"
            + "".join(f"| {k} | `{names[labels[18 + k]]}` ({labels[18 + k]}) | all n | never holds | keep | open |\n"
                      for k in (1, 2, 3)))
        open(os.path.join(rd, "SKIPPED.md"), "w").write(
            "| # | what | reason | what it would take | verified |\n|---|---|---|---|---|\n"
            + "".join(f"| {k} | the Remark after {labels[22 + k]} | prose outside a numbered environment | x | y |\n"
                      for k in (1, 2, 3, 4)))
        open(os.path.join(rd, "UNUSED_ARGS.md"), "w").write(
            "# Unused\n\n## Approved statements (3): x\n\n"
            + "".join(f"- `P.{names[labels[k]]}`: argument 2: (hn : 1 ≤ n)\n" for k in (1, 2, 3)))
        ans = ("Option {k}: re-save the baseline at abc1234 (only your own proof commit), re-run the adjudicator and "
               "carry on; disclose it in the run log and in the notice files of the delivery, with the reason. The "
               "tool bug is being fixed by a maintainer separately; keep using the cure where needed.")
        for k in range(1, 6):
            sd = os.path.join(rd, "stops", f"S{k}")
            os.makedirs(sd)
            json.dump({"stop": f"S{k}", "date": "2026-10-23", "command": None, "note": "a tool failed " + long_,
                       "causes": [{"code": "tool-bug", "class": "tool-bug", "line": "(operator's note)"}]},
                      open(os.path.join(sd, "STOP.json"), "w"))
            json.dump({"by": "human", "text": ("Option 5: deliver by hand and disclose it in the run log."
                                               if k == 5 else ans.format(k=k))},
                      open(os.path.join(sd, "CLOSED.json"), "w"))
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(
            "# Run log\n## Decisions\n" + "".join(
                f"- check:{lb.replace(' ', '_')}: [DELEGATED 2026-10-23, operator under hands-off (intake); reversal: "
                f"{cost}] keep `{names[lb]}` as printed\n" for lb in labels[:6] for cost in ("none", "re-approve")))
        g("add", "-A"); g("commit", "-qm", "fixture")
        inp = summary_inputs(cfg)
        keys = disclosure_keys(cfg, inp)
        md = summary_md(cfg, inp)
        lines = md.splitlines()
        cnt = [l for l in lines if COUNTED_RE.match(l)]
        out.append(("one page: a record larger than the largest run snapshot gives a summary within the line budget, "
                    "some kinds counted (named, with the place of their full text), and the coverage check passes",
                    summary_problems(cfg, md, inp) == [] and bool(cnt) and all("full text in " in l for l in cnt)))
        kinds = {k.prefix for k in keys}
        out.append(("one page: every defect, proof slip, vacuous row, idle hypothesis, row not formalized, \"not a "
                    "defect\" and stop of the record is a key (listed or counted)",
                    {"defect", "proof slip", "vacuous", "unused hypothesis", "not formalized", "not a defect",
                     "stop", "stop decision"} <= kinds
                    and sum(1 for k in keys if k.prefix == "defect") == 6
                    and sum(1 for k in keys if k.prefix == "stop") == 5))
        tbl = _table_rows_of(md)[1]
        out.append(("one page: the results table holds every result once, equal statuses on one row; the goal line "
                    "gives the goal's status; the decisions line counts matters, no decision listed one by one",
                    sorted(tbl) == sorted(labels) and len(_table_rows_of(md)[0]) == 30
                    and sum(1 for l in lines if l.startswith("| ") and not l.startswith("| Status")) < 30
                    and lines[2].startswith("**Goal result:** Theorem 5.6: ")
                    and any(l.startswith(f"- Decisions: {inp['matters']} matter(s)") for l in lines)
                    and isinstance(inp["matters"], int) and 0 < inp["matters"] < inp["n_delegated"]
                    and not any(l.startswith("- delegated") for l in lines)))
        hand = [l for l in lines if l.startswith("- hand delivery S5 — ")]
        s5 = [l for l in lines if "stop S5" in l and l.startswith("- stop decision")]
        out.append(("one page: a stop the human closed with a hand delivery says so on its line; the human's "
                    "answer is under \"Answers recorded as yours\" with its audit commit (or counted there)",
                    bool(hand) and "copied by hand" in hand[0] and not any(l.startswith("- hand delivery S1") for l in lines)
                    and (bool(s5) and "audit commit " in s5[0] or any("stop S5" in l for l in cnt))))
        # the coverage check refuses: a listed line dropped, changed, invented; a counted name dropped or miscounted
        if not cnt:     # the budget did not count anything: the checks below need a counted line
            raise ValueError("no counted line on the page (the line budget is off)")
        lst = next(l for l in lines if l.startswith("- defect 1 — "))
        drop = md.replace(lst + "\n", "")
        chg = md.replace(lst, lst.replace("false", "true"))
        inv = md.replace(lst, lst + "\n- defect 99 — Lemma 9.9: false")
        c0 = cnt[0]
        m0 = COUNTED_RE.match(c0)
        ids = m0.group(3).split("; ")
        lessn = md.replace(c0, c0.replace(f"({'+' if '(+' in c0 else ''}{len(ids)})",
                                          f"({'+' if '(+' in c0 else ''}{len(ids) - 1})").replace(ids[-1] + " — ", "", 1)
                           .replace("; " + ids[-1] + " — ", " — "))
        miscount = md.replace(c0, c0.replace(f"{len(ids)})", f"{len(ids) + 1})", 1))
        pr = lambda t_: [str(x) for x in summary_problems(cfg, t_, inp)]
        row0 = next(l for l in lines if l.startswith("| ") and not l.startswith("| Status") and "Lemma 2.2" in l)
        restat = md.replace(row0, row0.replace("false as printed", "a misprint"))
        decl = next(l for l in lines if l.startswith("- Decisions: "))
        redec = md.replace(decl, decl.replace(" matter(s)", "0 matter(s)", 1))
        out.append(("one page: the coverage check refuses a results row whose status is not the record's, and a "
                    "decisions line whose count of matters is not DECISIONS.md's",
                    any("gives Lemma 2.2 the status" in x for x in pr(restat))
                    and any("lacks the decisions line" in x for x in pr(redec))))
        out.append(("one page: the coverage check refuses a listed defect dropped, changed or invented, a counted item "
                    "dropped from its line, and a count that does not match its names",
                    any("neither lists nor counts defect 1" in x for x in pr(drop))
                    and any("shows 5 defect(s)" in x for x in pr(drop))
                    and any("defect 1 changed or cut short" in x for x in pr(chg))
                    and any("lists defect 99, which the record does not hold" in x for x in pr(inv))
                    and any(f"neither lists nor counts {m0.group(1)} {ids[-1]}" in x for x in pr(lessn))
                    and any("but names" in x for x in pr(miscount))))
        # several items sharing one ident (mini4: two assumption notes, ident ""; mini2: ten open questions of one
        # round and lane): every listed line counts, not only the last key's (prepare's own summary was refused)
        notes2 = ["Hypotheses added since the approval: none.",
                  "Missing theory: `HypC` is assumed for a lemma; the paper invokes it by name."]
        inp2 = dict(inp, assumptions=dict(inp["assumptions"], notes=notes2))
        md2 = summary_md(cfg, inp2)
        nl2 = [l for l in md2.splitlines() if l.startswith("- assumption note — ")]
        out.append(("one page: several items sharing one ident (two assumption notes) are each listed and the "
                    "coverage check passes the summary prepare wrote; one of them dropped is refused",
                    len(nl2) == 2 and summary_problems(cfg, md2, inp2) == []
                    and any("lacks the line of assumption note" in str(x)
                            for x in summary_problems(cfg, md2.replace(nl2[1] + "\n", ""), inp2))))
        with contextlib.redirect_stdout(io.StringIO()):
            probs = build_summary(cfg, quiet=True)
        out.append(("one page (PDF-AGENTS): build_summary writes SUMMARY.md only; its PDF is the agents' "
                    "(render_record.py: the renderer fits one page, the verifier fails a longer one)",
                    probs == [] and os.path.exists(os.path.join(rd, SUMMARY_MD))
                    and not any(os.path.exists(os.path.join(rd, "SUMMARY" + x)) for x in (".tex", ".pdf"))))
    except Exception as e:      # noqa: BLE001 -- a crash is a failed check, shown
        import traceback
        # the last frames only: the header line would make a failed check read as a crash (mutants.py)
        out.append((f"one-page checks ran ({type(e).__name__}: {e}; "
                    f"{' | '.join(traceback.format_exc().strip().splitlines()[-3:-1])})", False))
    finally:
        REPO, project.REPO = keep_r, keep_pr
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _forgery_checks():
    """[(name, ok)] of the forgery review's fixes (H1 row history, superseded rows and dangling row citations; H2
    the answers recorded as the human's; H3(a) a proved refutation needs its defect row), on a git fixture of their
    own (the history checks read committed versions)."""
    import tempfile, shutil, decisions
    global REPO
    keep_r, keep_pr = REPO, project.REPO
    tmp = tempfile.mkdtemp()
    checks = []
    try:
        REPO = project.REPO = tmp
        rd = os.path.join(tmp, "R")
        os.makedirs(os.path.join(rd, "2026-10-21-full-aaaaaaa0001")); os.makedirs(os.path.join(tmp, "P"))
        g = lambda *a: subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        cm = lambda m: (g("add", "-A"), g("commit", "-qm", m))
        cfg = {"name": "t", "source_cite": "src", "branch": "b", "namespace": "P", "rounds_dir": "R",
               "lean_files": ["P/Src.lean"], "index_file": "P/Src.lean"}
        V = ("| # | statement | for which parameters | why | decision and reasoning | found | status |\n"
             "|---|---|---|---|---|---|---|\n")
        r1 = "| 1 | `lemma_7_3` (b), Lemma 7.3 | all n | never holds | kept | 2026-10-21-full-aaaaaaa0001 | open |\n"
        r2 = "| 2 | `lemma_5_1` | all n | never holds | kept | 2026-10-21-full-aaaaaaa0001 | open |\n"
        vp = os.path.join(rd, "VACUOUS.md")
        open(os.path.join(rd, "2026-10-21-full-aaaaaaa0001", "ADOPTED.md"), "w").write("| a |\n")
        open(vp, "w").write(V + r1 + r2); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
        clean = row_history_problems(rd, "VACUOUS.md", "statement")
        open(vp, "w").write(V + r2); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
        gone = row_history_problems(rd, "VACUOUS.md", "statement")
        checks.append(("forgery review H1: a VACUOUS.md row deleted in a commit named \"adjudicate R\" is a problem "
                       "(a row is never removed); none before",
                       clean == [] and len(gone) == 1 and "row(s) 1 were committed" in gone[0]))
        sup = r1.replace("| open |", "| superseded (2026-10-21-full-aaaaaaa0001) |")
        open(vp, "w").write(V + sup + r2); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
        ok_sup = row_history_problems(rd, "VACUOUS.md", "statement") == []
        read = [r[0] for r in record_table(vp, "statement")[1]]
        dec = [c[0] for _h, c in decisions.table_rows(open(vp).read())]
        import signoff as _so
        open(vp, "w").write(V + sup + r2.replace("`lemma_5_1`", "Lemma 5.1")); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
        vres = _so.vacuous_results(rd)
        open(vp, "w").write(V + sup + r2)
        g("commit", "-qam", "adjudicate 2026-10-21-full-aaaaaaa0001")
        listed = superseded_rows(rd)
        checks.append(("forgery review H1: a row marked `superseded (2026-10-21-full-aaaaaaa0001)` by \"adjudicate 2026-10-21-full-aaaaaaa0001\" stays in the file, "
                       "passes, is read by nobody (report, decisions, sign-off), and the summary lists it",
                       ok_sup and read == ["2"] and dec == ["2"] and vres == ["Lemma 5.1"]
                       and listed and listed[0][:3] == ("VACUOUS.md", "1", "2026-10-21-full-aaaaaaa0001")))
        open(vp, "w").write(V + r1.replace("| open |", "| superseded (2026-10-29-ccccccc0009) |") + r2)
        bad_r = row_history_problems(rd, "VACUOUS.md", "statement")
        open(vp, "w").write(V + sup.replace("(2026-10-21-full-aaaaaaa0001)", "(2026-10-22-bbbbbbb0002)") + r2)
        os.makedirs(os.path.join(rd, "2026-10-22-bbbbbbb0002")); open(os.path.join(rd, "2026-10-22-bbbbbbb0002", "ADOPTED.md"), "w").write("| a |\n")
        cm("record-fix 2026-10-22-bbbbbbb0002")
        bad_s = row_history_problems(rd, "VACUOUS.md", "statement")
        checks.append(("forgery review H1: `superseded` must name an adjudicated round, and be committed by that "
                       "round's adjudication",
                       any("names no adjudicated round" in x for x in bad_r)
                       and any("only the adjudication of that round" in x for x in bad_s)))
        g("reset", "-q", "--hard", "HEAD~1")
        for f_, kc, hdr, row in (("SKIPPED.md", "what", "| # | what | reason | decided by |\n|---|---|---|---|\n",
                                  "| 1 | Lemma 2 | open problem | adjudicator |\n"),
                                 ("DEVIATIONS.md", "kind", "| # | result | the paper's route | the Lean route | why "
                                  "different | kind |\n|---|---|---|---|---|---|\n",
                                  "| 1 | Lemma 3 | a | b | c | reading choice |\n")):
            open(os.path.join(rd, f_), "w").write(hdr + row); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
            open(os.path.join(rd, f_), "w").write(hdr); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
            checks.append((f"forgery review H1: a {f_} row deleted is a problem too",
                           any("row(s) 1 were committed" in x for x in row_history_problems(rd, f_, kc))))
            open(os.path.join(rd, f_), "w").write(hdr + row); cm("adjudicate 2026-10-21-full-aaaaaaa0001")
        lp = os.path.join(rd, "RUN_LOG.md")
        open(lp, "w").write("# Run log\n- kept it (VACUOUS.md row 2; DEVIATIONS.md row 1)\n")
        ok_ref = row_reference_problems(rd) == []
        open(lp, "w").write("# Run log\n- kept it (VACUOUS.md rows 2 and 3; PAPER_DEFECTS.md row 1)\n")
        open(os.path.join(rd, "SKIPPED.md"), "a").write("| 2 | x, see DEVIATIONS.md row 4 | y | z |\n")
        refs = row_reference_problems(rd)
        checks.append(("forgery review H1: a citation of a record row that does not exist is a problem (the run log: "
                       "report; a record: record-cite); existing rows pass",
                       ok_ref and {(x.code, str(x).split(" cites ")[1].split(",")[0]) for x in refs}
                       == {("report", "VACUOUS.md row 3"), ("report", "PAPER_DEFECTS.md row 1"),
                           ("record-cite", "DEVIATIONS.md row 4")}))
        # H3(a): a proved refutation of a printed statement needs its `false` row
        open(os.path.join(tmp, "P", "Src.lean"), "w").write(
            "/-- printed (b) -/\ndef lemma_7_4_b_statement : Prop := ∀ n : ℕ, n = n + 0\n"
            "theorem lemma_7_4_b_false : ¬ lemma_7_4_b_statement := by\n  sorry\n"
            "theorem lemma_9_as_printed_false :\n    ¬ ∀ N : ℕ, N = 0 := by\n  sorry\n"
            "theorem fine (h : ¬ 1 = 2) : True := trivial\n-- theorem gone_false : ¬ x := c\n")
        lr = lean_refutations(cfg)
        pd = os.path.join(rd, "PAPER_DEFECTS.md")
        DH = ("## Defects\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
              "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n")
        open(pd, "w").write(DH + "| 1 | Lemma 9, tex l.1 | misprint (true as intended) | typo | a | b | none: by "
                            "argument (x) | c | d | 2026-10-21-full-aaaaaaa0001 |\n")
        head, rows = record_table(pd, DEFECT_KEY)
        miss = [x for x in f10_problems(pd, head, rows, cfg) if "refutation" in x]
        checks.append(("forgery review H3(a): a refutation proved in the Lean (`¬ X_statement`, a project Prop, or "
                       "named so) with no `false` row naming it is a problem at once (comments ignored)",
                       set(lr) == {"lemma_7_4_b_false", "lemma_9_as_printed_false"}
                       and sorted(re.findall(r"refutation `(\w+)`", " ".join(miss)))
                       == ["lemma_7_4_b_false", "lemma_9_as_printed_false"]
                       and "renames it `not_lemma_9_as_printed`" in " ".join(miss)))
        # H2: the answers the record attributes to the human, in the report and the summary
        open(lp, "w").write(
            "# Run log\n## Checkpoint A\nthe human approved the setup\n## Answered\n"
            "- answered question:P.lemma_7_2 (2026-10-23, 2026-10-21-full-aaaaaaa0001): keep hn as printed HUMANQZ\n"
            "- answered check:Lemma_1 (2026-10-23, 2026-10-21-full-aaaaaaa0001): [DELEGATED 2026-10-23, operator under hands-off (intake); "
            "reversal: none] keep it OPQZ\n")
        json.dump({"round": "2026-10-21-full-aaaaaaa0001", "commit": "abc", "date": "2026-10-22", "how": "blanket", "by": "human",
                   "note": "all OK APPRQZ", "rows": {}, "fingerprints": {}},
                  open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
        cm("run log: answers; approve 2026-10-21-full-aaaaaaa0001")
        h_now = g("rev-parse", "--short", "HEAD").stdout.strip()
        ans = recorded_human_answers(cfg)
        hd = human_decisions(cfg)
        checks.append(("forgery review H2: every answer recorded as the human's (an `## Answered` line without an "
                       "operator tag, an approval `by: human`) is listed with its audit commit; the operator's "
                       "[DELEGATED] answer is not; the report's \"Taken by the human\" lists them (it omitted them)",
                       [k for k, *_ in ans] == ["answer", "approval"]
                       and "HUMANQZ" in ans[0][2] and h_now in ans[0][2] and "APPRQZ" in ans[1][2] and h_now in ans[1][2]
                       and not any("OPQZ" in a[2] for a in ans)
                       and any("HUMANQZ" in x for x in hd) and any("APPRQZ" in x for x in hd)))
        inp = {"rd": rd, "index": [], "skipped": ([], []), "deviations": ([], []), "vacuous": ([], []),
               "defects": ([], []), "unproved": {}, "questions": [], "approval": None,
               "assumptions": {"rows": [], "notes": []}, "globals": [], "stops": [], "disclosed": [],
               "delegation": None, "delegated": [], "reapprovals": [], "setasides": [], "later": None, "trust": [],
               "human_answers": ans, "superseded": superseded_rows(rd)}
        _keep_atr = globals()["assumption_trust_rows"]
        globals()["assumption_trust_rows"] = lambda c_, a_: []
        try:
            md = summary_md(dict(cfg, source_cite="src"), inp)
        finally:
            globals()["assumption_trust_rows"] = _keep_atr
        sec = md.split(f"## {ANSWERS_SECTION}", 1)[-1].split("\n## ", 1)[0]
        checks.append(("forgery review H2: the summary's \"Answers recorded as yours\" asks the human to check each "
                       "answer and lists them (with date and anchor); a superseded row is listed under Process",
                       ANSWERS_INTRO in sec and "- answer 2026-10-23 question:P.lemma_7_2 — " in sec
                       and "HUMANQZ" in sec and f"audit commit {h_now}" in sec
                       and "- approval 2026-10-22 approval of round 2026-10-21-full-aaaaaaa0001 — " in sec
                       and "OPQZ" not in sec and "- superseded row VACUOUS.md row 1 — superseded by the "
                       "adjudication of 2026-10-21-full-aaaaaaa0001" in md))
        # trial #8: the human's own Checkpoint B and C answers (RUN_LOG.md `## Checkpoint B`, `## Checkpoint C (<date>)`)
        # are shown back in section 9 and the summary, each with its checkpoint; a delegated C is not the human's
        open(lp, "w").write(
            "# Run log\n## Checkpoint A\nthe human approved the setup\n## Checkpoint B\n"
            '- human answer (2026-10-22): "(a) I read SIGNOFF.pdf and approve all of it BANSQZ"\n'
            '## Checkpoint C (2026-10-24)\n- human answer (2026-10-24): "keep the hypotheses CANSQZ"\n'
            '## Checkpoint C (2026-10-25, delegated)\n- human answer (2026-10-25): "DELEGQZ"\n## Answered\n'
            '- answered unused:P.lemma_7_2@1 (2026-10-24, 2026-10-21-full-aaaaaaa0001): "keep the hypotheses CANSQZ"\n')
        cm("run log: Checkpoint B and C answers")
        ans8, hd8 = recorded_human_answers(cfg), human_decisions(cfg)
        globals()["assumption_trust_rows"] = lambda c_, a_: []
        try:
            md8 = summary_md(dict(cfg, source_cite="src"), dict(inp, human_answers=ans8))
        finally:
            globals()["assumption_trust_rows"] = _keep_atr
        sec8 = md8.split(f"## {ANSWERS_SECTION}", 1)[-1].split("\n## ", 1)[0]
        labels8 = [l_ for _, l_, _, _ in ans8]
        checks.append(("trial #8: the human's Checkpoint B and Checkpoint C answers are recorded as theirs, in section 9 and "
                       "the summary's \"" + ANSWERS_SECTION + "\", each with its checkpoint; an `## Answered` line giving the "
                       "C answer says so; a delegated Checkpoint C is not the human's",
                       "2026-10-22 Checkpoint B" in labels8 and "2026-10-24 Checkpoint C" in labels8
                       and "2026-10-24 unused:P.lemma_7_2@1 (Checkpoint C)" in labels8
                       and any("BANSQZ" in x for x in hd8) and any("CANSQZ" in x for x in hd8)
                       and not any("DELEGQZ" in a[2] for a in ans8) and "Checkpoint B" in sec8 and "BANSQZ" in sec8
                       and '""' not in " ".join(a[2] for a in ans8)))
        # trial #9: no generated line a reader reads is clipped ("… (decided on an earlier version of …")
        checks += _selftest_no_clipped_lines(cfg, rd, lp, inp)
        checks += _selftest_trial11(cfg, rd, lp, inp)
        # C2 audit, fault (d) and other fault 1: at a re-approval the first approval moves aside (same content, a new
        # name, in the re-approval's commit); its receipt stays the commit that added it. The human's re-approval
        # words are listed (section 9, and the re-approval's own row), the operator's QUESTION to-do line is not
        ap_ = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
        json.dump({"round": "2026-10-21-full-aaaaaaa0001", "commit": "abc", "date": "2026-10-22", "how": "blanket",
                   "by": "human", "rows": {}, "fingerprints": {}}, open(ap_, "w"))
        cm("approve 2026-10-21-full-aaaaaaa0001")
        h_first = g("rev-parse", "--short", "HEAD").stdout.strip()
        open(os.path.join(tmp, "P", "Src.lean"), "a").write("-- later\n"); cm("later work")
        os.rename(ap_, os.path.join(rd, "APPROVED_FINGERPRINTS.2026-10-22.json"))
        json.dump({"round": "2026-10-25-full-bbbbbbb0002", "commit": "def", "date": "2026-10-25", "how": "blanket",
                   "by": "human", "rows": {}, "fingerprints": {}}, open(ap_, "w"))
        open(lp, "a").write("\n## Re-approvals\n- change P.thm_1_1 — add a row (re-approval begun at Lean abc)\n"
                            '- human answer (round 2026-10-25-full-bbbbbbb0002; P.thm_1_1): "(a) yes, approve it REAPQZ"\n'
                            "## Open questions\n- re-approval QUESTION: the change to P.thm_1_1 (add a row) awaits the "
                            "human's approval (x); ask with `signoff.py reapprove --question` TODOQZ (answered "
                            "2026-10-25: (a))\n")
        cm("approve 2026-10-25-full-bbbbbbb0002")
        h_re = g("rev-parse", "--short", "HEAD").stdout.strip()
        import fingerprint as _fp9
        _keep_rp = _fp9.reapprovals
        _fp9.reapprovals = lambda *a_, **k_: [{"decls": ["P.thm_1_1"], "begins": [{"date": "2026-10-24"}],
                                               "closed": True, "closed_by": "approve 2026-10-25-full-bbbbbbb0002",
                                               "closed_date": "2026-10-25"}]
        try:
            ans9, rows9 = recorded_human_answers(cfg), reapproval_rows(cfg)
        finally:
            _fp9.reapprovals = _keep_rp
        appr9 = {a[1]: a[2] for a in ans9 if a[0] == "approval"}
        checks.append(("C2 audit: an approval moved aside at a re-approval keeps the receipt of the commit that added "
                       "it (not the re-approval's); the human's re-approval answer is listed verbatim with its commit, "
                       "in section 9 and on the re-approval's row; the operator's QUESTION line is not an answer",
                       f"recorded in audit commit {h_first} (APPROVED_FINGERPRINTS.2026-10-22.json)"
                       in appr9.get("2026-10-22 approval of round 2026-10-21-full-aaaaaaa0001", "")
                       and f"recorded in audit commit {h_re} (APPROVED_FINGERPRINTS.json)"
                       in appr9.get("2026-10-25 approval of round 2026-10-25-full-bbbbbbb0002", "")
                       and any(a[0] == "answer" and "REAPQZ" in a[2] and h_re in a[2]
                               and "re-approval (round 2026-10-25-full-bbbbbbb0002)" in a[1] for a in ans9)
                       and not any("TODOQZ" in a[2] for a in ans9)
                       and len(rows9) == 1 and "REAPQZ" in rows9[0][4]))
        # C2-FIX 5b (approver 2026-10-26): a check that could not run (stops.py close --core-fault) is never said to
        # have passed; the author reads only its plain consequence -- on page 1 above the results, in the report's
        # rows that rest on it -- and no word of the mechanism (the check, the file, the stop, the reviewer)
        import stops as _st9
        _keep_cf = _st9.core_fault_rows
        # the route's own mechanism words (the page's other, older texts are not this route's)
        MECH = ("axiom_sweep", "integrity.py", "tool fault", "core", "stop S3", "core-fault", "tool patch", "Phase 0",
                "fingerprint", "KeyError", "not established: the", "could not run (")
        res_cf = {}
        for cfile in ("axiom_sweep.py", "integrity.py", "fingerprint.py"):
            _st9.core_fault_rows = (lambda f_: lambda *a_, **k_: [{"stop": "S3", "check_name": "x", "core_file": f_,
                                                                   "text": "KeyError at l.88"}])(cfile)
            globals()["assumption_trust_rows"] = lambda c_, a_: []
            try:
                res_cf[cfile] = (summary_md(dict(cfg, source_cite="src"), inp), trust_rows(cfg),
                                 provenance_row(cfg))
            finally:
                _st9.core_fault_rows = _keep_cf
                globals()["assumption_trust_rows"] = _keep_atr
        # C2 audit: a counted proof slip is named ("proof slip (1): 1 (Proof of Lemma 7.4(a))"), never a bare number
        _keep_atr2 = globals()["assumption_trust_rows"]
        globals()["assumption_trust_rows"] = lambda c_, a_: []
        try:
            ks_ = disclosure_keys(dict(cfg, source_cite="src"), dict(inp, slips=[
                "Proof of Lemma 7.4(a), tex l.214-215. The text says \"substituting x = y+1\"; it should say x = y-1."],
                not_defects=[], unused=[], matters=0, proxies=0, n_delegated=0))
        finally:
            globals()["assumption_trust_rows"] = _keep_atr2
        sl_ = [k for k in ks_ if k.prefix == "proof slip"]
        checks.append(("C2 audit: a proof slip's summary ident names it (counted, the line read \"proof slip (1): 1\")",
                       len(sl_) == 1 and sl_[0].ident == "1 (Proof of Lemma 7.4(a))"))
        mk_ax = ("Not verified: the check that the proofs use only Lean's standard axioms could not be run, so that has "
                 "not been confirmed (details for maintainers in RUN_RECORD.md).")
        mk_rec = ("Not verified: the record of who reviewed and approved what could not be verified automatically "
                  "(details for maintainers in RUN_RECORD.md).")
        md_ax, tr_ax, _pv = res_cf["axiom_sweep.py"]
        md_rec, tr_rec, pv_rec = res_cf["integrity.py"]
        md_fp, tr_fp, _pv2 = res_cf["fingerprint.py"]
        mk_fp = ("Not verified: the check that the statements are exactly the ones approved could not be run, so that "
                 "has not been confirmed (details for maintainers in RUN_RECORD.md).")
        checks.append(("C2-FIX review 3: a statement check that could not run is the report's Lean-kernel status and "
                       "the approval row's (never 'Phase 0 green'), on page 1; with a provenance fault the kernel row "
                       "claims no 'Phase 0 green' either, and the legend says what *faithful* rests on",
                       mk_fp in tr_fp[0][2] and "Phase 0 green" not in tr_fp[0][2] and f"**{mk_fp}**" in md_fp
                       and dict((r_[0], r_[2]) for r_ in tr_fp)["Approval of statements"].startswith(mk_fp)
                       and "Phase 0 green" not in tr_rec[0][2] and RECORD_LEGEND.strip() in md_rec
                       and RECORD_LEGEND.strip() not in md_ax))
        rows_rec = {r_[0]: r_[2] for r_ in tr_rec}
        checks.append(("C2-FIX 5b (approver 2026-10-26): a check that could not run is said in plain words on the "
                       "summary's first lines and in the report row it affects (the Lean-kernel row: never 'green'), "
                       "the Lean-checks sentence left out; no word of the mechanism on the summary or in those rows",
                       f"**{mk_ax}**" in md_ax.split("## Results")[0] and mk_ax in tr_ax[0][2]
                       and "green" not in tr_ax[0][2] and "*not verified: ...*" in md_ax
                       and not [w for w in MECH if w in md_ax.replace(mk_ax, "") or w in tr_ax[0][2]]))
        checks.append(("C2-FIX 5b (approver 2026-10-26): a provenance check that could not run is said once on the "
                       "summary, on the rows that rest on the record (the approval, the reviewers, record provenance) and "
                       "over the answers recorded as yours; the Lean checks did run, so their sentence stays",
                       f"**{mk_rec}**" in md_rec.split("## Results")[0] and "Phase 0: the Lean builds" in md_rec
                       and all(rows_rec[k_].startswith(mk_rec) for k_ in rows_rec
                               if k_.startswith("AI reviewer") or k_ == "Approval of statements")
                       and pv_rec[2].startswith(mk_rec) and mk_rec not in tr_rec[0][2]
                       and (f"## {ANSWERS_SECTION}" not in md_rec or mk_rec in md_rec.split(f"## {ANSWERS_SECTION}")[1])))
    except Exception as e:      # noqa: BLE001 -- a crash is a failed check, shown
        import traceback
        checks.append((f"forgery review checks ran ({type(e).__name__}: {e}; {traceback.format_exc()[-300:]})", False))
    finally:
        REPO, project.REPO = keep_r, keep_pr
        shutil.rmtree(tmp, ignore_errors=True)
    return checks


def clipped_lines(text):
    """[line] of generated text that carries a cut marker ("…" ending a word-boundary cut, project.clip) where
    no label is: a content line must be whole (trial #9). Allowed: a heading, a table label cell or an
    italic item label (`*...:*`) -- each followed by its full text -- and an explicit pointer to the full text."""
    out = []
    for ln in text.splitlines():
        if "…" not in ln or ln.lstrip().startswith("#") or "full text in" in ln:
            continue
        body = re.sub(r"^\s*[-*>|]\s*(\*[^*\n]*\*)?", "", ln)
        if re.search(r"\S …(?=[\s)\]|;,.]|$)", body):
            out.append(ln)
    return out


def _selftest_no_clipped_lines(cfg, rd, lp, inp):
    """Trial #9: records with long cells, a long stop note, a long Checkpoint A, a long decision and a proof slip
    give a summary, a report box and a decisions box with no clipped line; the slip is listed in both."""
    import decisions, stops as _st
    long_ = " ".join(f"word{i}" for i in range(120)) + " ENDQZ."
    open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
        "## Defects\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
        "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
        f"| 1 | Lemma 9, tex l.1 | vacuous | none (intent unknown) | Let n be given. If A then B {long_} | {long_} | "
        f"none: by argument (x) | {long_} | {long_} | r |\n\n## Slips in the proofs (no witness needed)\n"
        "(a wrong cross-reference: location, what the text says, what it should say)\n"
        f"- Proof of Lemma 4, tex l.9. It says x+3; it should say x+2. SLIPQZ {long_}\n")
    os.makedirs(os.path.join(rd, "stops", "S1"), exist_ok=True)
    json.dump({"stop": "S1", "date": "2026-10-23", "command": None, "note": "NOTEQZ " + long_,
               "causes": [{"code": "tool-bug", "class": "tool-bug", "line": "(operator's note)"}]},
              open(os.path.join(rd, "stops", "S1", "STOP.json"), "w"))
    json.dump({"by": "human", "text": "ANSQZ " + long_}, open(os.path.join(rd, "stops", "S1", "CLOSED.json"), "w"))
    open(lp, "w").write("# Run log\n## Checkpoint A\n- approved by the human: CHKQZ " + long_ + "\n")
    out = []
    sn = since_note(["x", "[DELEGATED 2026-10-23, operator under hands-off (intake); reversal: none] keep it " + long_
                     + " (decided on an earlier version of this row)"])
    out.append(("trial #9: a decision \"decided since\" is quoted whole (it read \"(decided on an earlier version of …\")",
                "…" not in sn and sn.count("ENDQZ") == 1 and "earlier version of this row)" in sn))
    bl = decisions.box_lines(cfg)
    srows = _st.stop_rows(cfg, phase="run")
    i2 = dict(inp, defects=record_table(os.path.join(rd, "PAPER_DEFECTS.md"), DEFECT_KEY), stops=srows)
    _keep = globals()["assumption_trust_rows"]
    globals()["assumption_trust_rows"] = lambda c_, a_: []
    try:
        md = summary_md(dict(cfg, source_cite="src"), i2)
    finally:
        globals()["assumption_trust_rows"] = _keep
    hd = human_decisions(cfg)
    texts = {"summary": md, "decisions box": "\n".join(f"> - {b}" for b in bl), "human decisions": "\n".join(hd)}
    bad = {k: clipped_lines(t) for k, t in texts.items() if clipped_lines(t)}
    out.append(("trial #9: no generated line (summary, decisions box, the human's decisions) is clipped: long record "
                "cells, a stop's note and answer, Checkpoint A are given whole" + (f" (clipped: {bad})" if bad else ""),
                not bad and "NOTEQZ" in "\n".join(bl) and all(t.count("ENDQZ") for k, t in texts.items() if k != "summary")
                # the one-page summary gives a long text's first sentence and the place of the full text
                and "ANSQZ" not in md and "- stop S1 — tool-bug; closed by your answer (below)" in md
                and any(b.startswith("defect 1:") and "the paper says \"Let n be given. If A then B" in b for b in bl)
                and any("CHKQZ" in x and "ENDQZ" in x for x in hd)))
    out.append(("trial #9: a proof slip (PAPER_DEFECTS.md \"Slips in the proofs\") is in the summary's defects and the "
                "box, in full; the template's parenthetical is not an entry",
                "- proof slip 1 — Proof of Lemma 4, tex l.9 (the result still holds; full text in REPORT §5)" in md
                and [b for b in bl if b.startswith("proof slip:")] and all("ENDQZ" in b for b in bl if "SLIPQZ" in b)
                and decisions.slip_rows(rd) == [f"Proof of Lemma 4, tex l.9. It says x+3; it should say x+2. SLIPQZ {long_}"]))
    out.append(("trial #9: clipped_lines finds a cut content line and passes labels and whole lines",
                clipped_lines("- vacuous: 1 — keep it (decided on an earlier version of …") != []
                and clipped_lines("- x: a stop (note: under 'What the …) -- y") != []
                and clipped_lines("### Paper defect 1: Lemma …\n- *True only vacuously: `a` (Lemma …:* kept\n"
                                  "- whole line. … (full text in R/ADOPTED.md)\n- reads 'x…y' fine") == []))
    return out


def _selftest_trial11(cfg, rd, lp, inp):
    """Trial #11 audit: the summary's generator lines (an empty "not a defect", a counted line of bare numbers, the
    preamble printed as an item, a proof route with no place or reason, no counterexample, no glossary) and the
    defect rows a [DELEGATED] decision settled since."""
    import decisions
    out = []
    long_nd = ("Theorem 1.1 (tex l.4) assumes n ≥ 0, which its proof does not use (the two identities its proof uses, "
               "u(n+1) − u(n) = c and v(n) = 3u(n) + 1, hold for every integer n). An unnecessary hypothesis is not a defect.")
    open(os.path.join(rd, "PAPER_DEFECTS.md"), "w").write(
        "## Defects\n| # | where | status | repair | what the paper says | why it is wrong | Lean witness | "
        "consequence | decision | found |\n|---|---|---|---|---|---|---|---|---|---|\n"
        "| 1 | Theorem 1.1, tex l.1 | false | typo | For n: 3 ∣ h(n) iff n ≡ 1 (mod 3). | counterexample: n = 2: h(2) = 6, "
        "but 2 ≢ 1 (mod 3); also n = 5. | none: confirmed by argument (x) | none | Repaired to residue 2. | r |\n"
        "| 2 | Lemma 1.2, tex l.2 | vacuous | none (intent unknown) | If A then B. | A never holds. | none: confirmed "
        "by argument (x) | none | Kept as printed. Whether to add a companion is pending a decision. | r |\n\n"
        "## Not defects, recorded so they are not mistaken for some\n"
        "- A limitation of the formalization is not a paper defect, and nothing below is one.\n"
        f"- {long_nd}\n")
    open(os.path.join(rd, "DEVIATIONS.md"), "w").write(
        "| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
        "| 1 | Theorem 1.1 | via the identity h(2n) = h(n) (tex l.5-6) | via h(2n+1) = h(n) | the paper's identity "
        "h(2n) = h(n) is false (h(2) = 3); the correct one is h(2n+1) = h(n) | paper step fails |\n")
    h2, c2 = [x for x in decisions.defect_rows(rd) if x[1][0] == "2"][0]
    tag = "[DELEGATED 2026-10-24, operator under hands-off (intake); reversal: new round]"
    open(lp, "w").write("# Run log\n## Checkpoint C (2026-10-24, delegated)\n"
                        f"- {decisions.defect_anchor(h2, c2).split('@')[0]}: {tag} add no companion — CQZ\n"
                        f"- defect:9-Other_-0000000000: {tag} something else — XQZ\n"
                        f"- {tag} keep Theorem 1.1 as printed (QUESTION row on Theorem 1.1, round 2026-10-24-abc1234) — UQZ\n")
    ch = dict(cfg, involvement="hands-off")
    d2, d1, dinv = decided_since_defect(ch, "2"), decided_since_defect(ch, "1"), \
        decided_since_defect(dict(cfg, involvement="involved"), "2")
    out.append(("trial #11: a defect row is decided since only by a [DELEGATED] line anchored to it (its version may be "
                "left out; an unanchored line naming its result is none), only under a delegating level",
                len(d2) == 1 and "CQZ" in d2[0] and "earlier version" not in d2[0] and d1 == [] and dinv == []))
    sc = settled_cell(c2[h2.index("decision")], d2)
    out.append(("trial #11: settled_cell quotes a deferring sentence as the row's text when written and appends the "
                "decision; with no decision the cell is unchanged",
                sc.startswith("Kept as printed. (when this row was written: \u201cWhether to add a companion is pending a "
                              "decision.\u201d) -- decided since by the operator (RUN_LOG.md): " + tag)
                and settled_cell("Kept. Left to the human.", []) == "Kept. Left to the human."
                and settled_cell("Kept as printed.", d2).startswith("Kept as printed. -- decided since")))
    # conf1 (C1 audit, defect 1): the real decision cells of PAPER_DEFECTS.md rows 1 and 2 were cut at a full stop
    # inside a word ("Theorem 7.6.", "VACUOUS.md"): REPORT section 5 read "1. Chosen by ..." and "md row 1; ..."
    cf1 = ("The Lean states the corrected form \"case B\" as `lemma_7_4` (`Paper/Results.lean:46`), keeping "
           "the printed form and its refutation alongside; the reading is forced by the paper's own proof and by its use "
           "in Theorem 7.6. Chosen by the formalizer in the statements commit, confirmed by the adjudicator of round "
           "2026-10-25-full-be0fba8ae15 (F10 and F12 Pass); subject to the human's statement sign-off.")
    cf2 = ("The Lean keeps the printed statement as `lemma_7_5_b` (`Paper/Results.lean:95`), faithful to tex l.88, "
           "and records it in VACUOUS.md row 1; no corrected variant is added, since the intended statement is unknown. "
           "Decided by the adjudicator of round 2026-10-25-full-be0fba8ae15; the human may ask for the variant at "
           "sign-off.")
    dl1 = ["[DELEGATED 2026-10-25, operator under hands-off (intake); reversal: new round] the misprint stays recorded"]
    out.append(("conf1: a decision cell with full stops inside words (\"7.6.\", \"VACUOUS.md\", \"Results.lean\") is "
                "shown whole, the decision appended",
                settled_cell(cf1, dl1) == cf1 + " -- " + since_note(dl1)
                and settled_cell(cf2, dl1) == cf2 + " -- " + since_note(dl1)
                and settled_cell("See Theorem 7.6. Left to the human. Done.", dl1).startswith(
                    "See Theorem 7.6. (when this row was written: \u201cLeft to the human.\u201d) Done. -- ")))
    # conf2 (C2 audit, fault (a)): the real cell of PAPER_DEFECTS.md row 1 lost "The Lean states ... (Paper/Main."
    # and more at every stop inside a word; also a `tex l.N` range, a decimal and "e.g." before a word
    cf3 = ("The Lean states the corrected Lemma 7.4 as `Paper.lemma_7_4` (Paper/Main.lean:92), now proved: "
           "(a) as printed, (b) with the constant c\u22121. The printed version is kept and refuted (tex l.38-39, l.108). "
           "Reasoning: 0.5 < 1, so e.g. the bound c\u22121 is what Theorem 7.6 consumes (AUTHOR_NOTES.md). The "
           "adjudicator re-ran its probe faithfulness_checks.lean (exit 0). Left to the human.")
    s3 = settled_cell(cf3, dl1)
    out.append(("conf2: a decision cell with file names (\"Main.lean:92\", \"AUTHOR_NOTES.md\"), `tex l.38-39`, a "
                "decimal and \"e.g.\" loses no text: every character before the appended decision is the cell's, the "
                "deferring sentence quoted",
                s3.replace("(when this row was written: \u201cLeft to the human.\u201d)", "Left to the human.")
                == cf3 + " -- " + since_note(dl1)
                and "(when this row was written: \u201cLeft to the human.\u201d)" in s3
                and "".join(m.group(0) for m in SENTENCE_RE.finditer(cf3)) == cf3))
    # the generic check: conf1's delivered summary lines ended "decided since (REPORT §5)" (no object)
    cs = ("- defect 2 — Lemma 7.5(b), tex l.88: vacuous; none (intent unknown); decided since (REPORT §5)\n"
          "- vacuous 1 — `Paper.lemma_7_5_b` (Lemma 7.5(b), tex l.88) is true only vacuously; decided since "
          "its row was written (decision in REPORT §7)\n| md row 1; no corrected variant is added | x —  |\n"
          "| a | b |\n|---|---|\n| The proof says: | ok |\n- Fresh-reader checks:\n- one\n")
    out.append(("conf1: dangling_lines finds a generated line or cell that ends mid-phrase (\"decided since\", a dash, "
                "a colon), not a list's lead-in, a table's header or a whole line",
                dangling_lines(cs) == ["- defect 2 — Lemma 7.5(b), tex l.88: vacuous; none (intent unknown); decided "
                                       "since (REPORT §5)", "x —", "The proof says:"]))
    i2 = {k: v for k, v in inp.items() if k not in ("not_defects", "unused", "slips")}
    i2.update(defects=record_table(os.path.join(rd, "PAPER_DEFECTS.md"), DEFECT_KEY),
              deviations=record_table(os.path.join(rd, "DEVIATIONS.md"), "kind"))
    _keep = globals()["assumption_trust_rows"]
    globals()["assumption_trust_rows"] = lambda c_, a_: []
    try:
        keys = disclosure_keys(ch, i2)
        page = summary_page(dict(ch, source_cite="src"), i2)
        # the not-a-defect ident names the result it mentions (the fixture's index is empty: one row for it)
        nd_key = [k for k in disclosure_keys(ch, dict(_summary_extra(ch, i2), index=[["Theorem 1.1", "`P.thm_1_1`"]]))
                  if k.prefix == "not a defect"]
    finally:
        globals()["assumption_trust_rows"] = _keep
    ls = [_line(k) for k in keys if k.group != "Results"]
    get = lambda pre: [l for l in ls if l.startswith(pre)]
    out.append(("trial #11: a false defect's line gives its counterexample, a decided one says so; the line is whole",
                get("- defect 1 — ") == ["- defect 1 — Theorem 1.1, tex l.1: false; typo; counterexample: n = 2: "
                                         "h(2) = 6, but 2 ≢ 1 (mod 3) (no Lean witness: confirmed by argument only)"]
                and get("- defect 2 — ") and get("- defect 2 — ")[0].endswith("; decided by the operator on your behalf (REPORT §5)")))
    nd = get("- not a defect")
    out.append(("trial #11: the \"Not defects\" preamble is no item; a long first sentence gives its leading clauses, never "
                "an empty line; the ident names the result",
                len(nd) == 1 and nd[0].startswith("- not a defect 1 (Theorem 1.1) — Theorem 1.1 (tex l.4) assumes n ≥ 0 "
                                                  "(full text in")
                and [k.ident for k in nd_key] == ["1 (Theorem 1.1)"]
                and not any(re.search(r" — \(full text in", l) for l in ls)
                and _short("x" * 30 + ", " + "y" * 150)[0] == "x" * 30))
    # conf1 (C1 audit) and mini10: the real "Not defects" bullets. conf1's 4 read "4 (Corollary 7.6 (c))" (a result
    # its parenthesis mentions) and the status check called the line empty; mini10's 1 read "— (full text in REPORT §5)"
    nd_real = [
        "Claims outside numbered environments (the Remark after Theorem 7.4, the list of small cases, the equality case of "
        "Corollary 7.6(c), the closing remark) are outside the formalization's scope; leaving them unformalized says "
        "nothing about whether they are right. The examples of Section 2 are checked as unnamed examples in "
        "`Paper/Defs.lean`.",
        "Theorem 7.9 is a classical result cited from a textbook; the formalization states it to be proved from "
        "Mathlib rather than taking it as a hypothesis.",
        "Scope: the unnumbered Remark after Corollary 7.5 (a variance bound) and the in-text examples of Section 2 and after "
        "Theorem 7.4 are not numbered results, so they are outside the configured scope (every numbered environment). "
        "This is a limitation of the formalization's scope, not a defect of the paper. The examples are checked at "
        "small n in `Paper/Examples.lean`."]
    _keep = globals()["assumption_trust_rows"]
    globals()["assumption_trust_rows"] = lambda c_, a_: []
    try:
        nk = [k for k in disclosure_keys(ch, dict(_summary_extra(ch, i2), not_defects=nd_real, index=[
            ["Corollary 7.6 (c)", "`Paper.corollary_7_6_c`"], ["Theorem 7.9", "`Paper.theorem_7_9`"],
            ["Corollary 7.5", "`Paper.corollary_7_5`"], ["Theorem 7.4", "`Paper.theorem_7_4`"]]))
              if k.prefix == "not a defect"]
    finally:
        globals()["assumption_trust_rows"] = _keep
    out.append(("conf1, mini10: a \"Not defects\" item is named by its lead, not by a result its parenthesis mentions, "
                "and a line with nothing short to say is its pointer, never \"— (full text in ...)\"",
                [k.ident for k in nk] == ["1 (Claims outside numbered environments)", "2 (Theorem 7.9)",
                                          "3 (Scope: the unnumbered Remark after Corollary 7.5)"]
                and _line(nk[2]) == "- not a defect 3 (Scope: the unnumbered Remark after Corollary 7.5) — full text in "
                                    "REPORT §5"
                and not dangling_lines("\n".join(_line(k) for k in nk))))
    pr = get("- proof route")
    out.append(("trial #11: a proof route line names the result, its place in the paper and why it differs",
                pr == ["- proof route 1 (Theorem 1.1) — tex l.5-6: paper step fails (the paper's identity h(2n) = h(n) "
                       "is false (h(2) = 3); the correct one is h(2n+1) = h(n); REPORT §6)"]))
    tl = terms_line(["Phase 0: the Lean builds", "in round 2026-01-01-full-abc1234",
                     "- self-cured stop S1 — document; x"])
    out.append(("trial #11: the page's last line explains the terms it uses and does not explain (a round, a stop's "
                "class), never one the header explains (Phase 0)",
                tl.startswith("- Terms: *round*") and "*document* stop: a fault in a document" in tl
                and "Phase 0" not in tl and terms_line(["- nothing here"]) == ""
                and "*Phase 0*" in terms_line(["Phase 0 ran"])
                and page[-1].startswith("- Terms: *round*")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="project name (default: the one whose branch is checked out)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--index-only", action="store_true",
                    help="with --check: only the index check (Phase 0's index step)")
    ap.add_argument("--pending", action="store_true",
                    help="Phase 0: an adjudicator-owned record fault is a PENDING[adjudication] NOTE (the next "
                         "adjudication clears it; its commit and --deliver refuse while one remains), not a failure")
    ap.add_argument("--delivery", action="store_true",
                    help="with --check: the delivery preconditions of project.py --deliver (U2 §6.4): the prepared "
                         "documents current, read and covered; the verdicts current; nothing stale or pending")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        import integrity
        with integrity.run_history_hidden(project.AUDITS):     # nor the run's applied tool patches (DOC-FIX review #1)
            return selftest()     # its own fixtures: no project needed
    try:
        cfg, _ = project.select(a.project)   # validates the config (RULINGS A10f)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2
    if a.index_only:
        if not a.check:
            print("FAIL: --index-only goes with --check", file=sys.stderr)
            return 2
        return index_only(cfg, a.pending)
    if a.delivery:
        if not a.check:
            print("FAIL: --delivery goes with --check", file=sys.stderr)
            return 2
        return delivery_check(cfg)
    return build(cfg, a.check, a.pending)


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

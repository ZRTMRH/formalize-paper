#!/usr/bin/env python3
"""Regression (DESIGN-MT; live e2e 2609.08713, stop S1): a RUN_LOG.md line the missing-theory check only suspects
from its words is the adjudicator's to rule, never a FAIL with no cure.

The fixture holds the run's l.72 verbatim (a delegated Checkpoint C line keeping a global difference, whose reason
mentions "the logged Stage 2 decision to build the missing theory"; it names no Lean result, so the old cure, a later
canonical line naming its result, could never apply). Checked:
  1. it is no FAIL[missing-theory] but one adj-record finding (PENDING[adjudication]) quoting the full line and its
     MT RULED id, and the adjudication commit's list (make_report.adjudication_findings) holds it;
  2. an `MT RULED <id> | not a missing-theory decision: …` line in a committed `adjudicate R` ADOPTED.md clears it,
     and its word-for-word `## Answered` copy too; an uncommitted ruling does not count;
  3. ruled `a missing-theory decision for `N.LS``, it is the operator's hard FAIL[missing-theory] until a canonical
     line for `N.LS` is logged after it (the hard checks stay).

  python3 audits/tests/regressions/mt_live_2609.py --apparatus audits
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser()
ap.add_argument("--apparatus", required=True)
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.apparatus))
import project, hypotheses, make_report  # noqa: E402

T = "[DELEGATED 2026-11-15, operator under hands-off (intake); reversal: re-approve]"
L72 = (f"- global:G2: {T} keep the minor and star-contraction definitions built for this run, with G/A read as a "
       "quotient graph (global difference G2) — conservative rule, as in the logged Stage 2 decision to build the "
       "missing theory, and the adjudicator of round 2026-11-14-full-f97ada758fe found the quotient to be the direct "
       "reading of tex l.141-144")
A96 = L72.replace("- global:G2: ", "- answered global:G2 (2026-11-15, 2026-11-15-full-a5774234119): ")
CANON = (f"- {T.replace('re-approve', 're-prove')} missing theory: assume `N.LS` for `N.thm` — searched: Mathlib "
         "(grep -rn graphon Mathlib/); estimate: about 3000 lines; paper: \"by the theorem of Lovász and Szegedy, every "
         "graphon is a limit\"")
bad = []
tmp = tempfile.mkdtemp(prefix="mt-live-2609-")
saved = project.REPO, make_report.REPO
try:
    project.REPO = make_report.REPO = tmp
    rd = os.path.join(tmp, "R")
    R, R2 = "2026-11-16-full-0123456789a", "2026-11-17-full-0123456789b"
    for r_ in (R, R2):
        os.makedirs(os.path.join(rd, r_, "prompts"))
        json.dump({"_meta": {"kind": "full"}}, open(os.path.join(rd, r_, "TARGET.json"), "w"))
    open(os.path.join(tmp, "N.lean"), "w").write("namespace N\ntheorem thm : True := trivial\ndef LS : Prop := True\nend N\n")
    cfg = {"rounds_dir": "R", "namespace": "N", "involvement": "hands-off", "lean_files": ["N.lean"],
           "libraries": ["Mathlib"]}
    git = lambda *x: subprocess.run(["git", "-C", tmp, *x], capture_output=True, text=True)
    commit = lambda msg: (git("add", "-A"), git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg))
    log = lambda *ls: open(os.path.join(rd, "RUN_LOG.md"), "w").write(
        "# Run log\n\n## Checkpoint C (2026-11-15, delegated)\n" + "\n".join(ls) + "\n")
    adopt = lambda r_, *ls: open(os.path.join(rd, r_, "ADOPTED.md"), "w").write("# A\n\n## Notes\n" + "".join(l + "\n" for l in ls))
    # each round's adjudicator prompt, as prompt.py 4 --write renders it (it lists the pending lines)
    shown = lambda r_: open(os.path.join(rd, r_, "prompts", "adjudicator.txt"), "w").write(
        "\n".join(make_report.pending_line(f) for f in make_report.adjudication_findings(cfg, r_)))
    git("init", "-q")
    log(L72, A96)
    commit("setup")
    fs = hypotheses.missing_theory_findings(cfg, doc={})
    if not hasattr(hypotheses, "mt_line_id"):
        bad.append("1: no MT RULED route: " + "; ".join(f"{f.code}: {str(f)[:90]}" for f in fs))
    else:
        lid = hypotheses.mt_line_id(L72)
        if any(f.code == "missing-theory" for f in fs) or [f.code for f in fs] != ["adj-record", "adj-record"] \
                or not all(f"MT RULED {lid}" in f for f in fs) or L72 not in fs[0]:
            bad.append("1: " + "; ".join(f"{f.code}: {str(f)[:90]}" for f in fs))
        if not any(f"MT RULED {lid}" in f for f in make_report.adjudication_findings(cfg)):
            bad.append("1: the adjudication commit's list does not hold the line")
        shown(R)
        shown(R2)
        adopt(R, f"- MT RULED {lid} | not a missing-theory decision: it keeps the G2 reading; it only cites the canonical "
              "Stage 2 build lines")
        if not hypotheses.missing_theory_findings(cfg, doc={}):
            bad.append("2: an uncommitted ruling counted")
        commit(f"adjudicate {R}")
        if hypotheses.missing_theory_findings(cfg, doc={}):
            bad.append("2: a committed 'not' ruling did not clear the line and its Answered copy")
        adopt(R2, f"- MT RULED {lid} | a missing-theory decision for `N.LS`: it assumes the graphon theorem")
        commit(f"adjudicate {R2}")
        hard = [f for f in hypotheses.missing_theory_findings(cfg, doc={}) if f.code == "missing-theory"]
        if len(hard) != 2 or "for `N.LS`" not in hard[0]:
            bad.append("3: a 'decision' ruling is not the operator's hard FAIL: " + str([str(f)[:90] for f in hard]))
        log(L72, A96, CANON)
        commit("log")
        if any(f.code == "missing-theory" and "MT RULED" in f for f in hypotheses.missing_theory_findings(cfg, doc={})):
            bad.append("3: the canonical line logged after it does not cure it")
finally:
    project.REPO, make_report.REPO = saved
    shutil.rmtree(tmp, ignore_errors=True)
print("regression:", ("FAILED " + " | ".join(bad)) if bad else "ok")
sys.exit(1 if bad else 0)

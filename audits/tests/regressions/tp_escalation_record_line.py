#!/usr/bin/env python3
"""Regression (tool patch TP3): in an escalation's own record line (lanecheck.escalation_line), the unaccepted
escalations the generator itself names -- its own NOT ACCEPTED head, the escalation its RE-ASKS clause names -- are
no citation; nothing else is exempt: not a record line whose question, answer or refusal reason names an escalation,
not any other line (reviews TP3 1-1, TP1 1-1 .. 8-1)."""
import argparse, sys
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser(); ap.add_argument("--apparatus", required=True); a = ap.parse_args()
sys.path.insert(0, a.apparatus)
import lanecheck
cfg = {"involvement": "hands-off"}
q = {"question": "Can X be proved?", "decl": "N.thm"}
bad = []


def run(recs, body):
    return lanecheck.escalation_citations(cfg, f"# Decisions\n### Theorem 5.1\n\n{body}\n", recs)


def lines(recs):
    by = {e["name"]: e for e in recs}
    return ["- " + lanecheck.escalation_line(e, by) for e in recs]


REAL = ("twobites/escalations/E1.answer.md is not accepted yet: run lanecheck.py --escalation E1 with the "
        "subagent's --agent-id and --returned-file")      # the reason lanecheck.py itself generates (review TP3 2-1)
e1 = {"name": "E1", "answer": None, "problems": [REAL], "reask_of": None, "inputs": q}
e2 = {"name": "E2", "answer": "ANSWERABLE: No; it needs new work", "problems": [], "reask_of": "E1", "inputs": q}
base = [e1, e2]
if run(base, "\n".join(lines(base))):
    bad.append("the generated record lines of a re-ask pair counted as citations")
L = lines(base)
for name, body in (("a decision relying on E1", "\n".join(L) + "\n- decided per escalation E1"),
                   ("E1's record line with text added", L[0] + "; decided per escalation E1"),
                   ("a hand-written NOT ACCEPTED line", "- escalation E1: NOT ACCEPTED, but per escalation E1 we drop hX"),
                   ("a never-written escalation", "- per escalation E9")):
    if not run(base, body):
        bad.append(f"{name} no longer counted")
# review TP3 1-1: free texts on a record line that name an escalation exempt nothing
qx = {"question": "Since escalation E1 lets us drop hX, can X be proved?", "decl": "N.thm"}
for name, recs in (
        ("an accepted answer naming E1", [e1, dict(e2, answer="ANSWERABLE: Yes, per escalation E1 drop hX")]),
        ("an accepted escalation whose question names E1", [e1, dict(e2, inputs=qx)]),
        ("an unaccepted escalation whose question names E1", [dict(e1, inputs=qx), e2]),
        ("a refusal reason naming another escalation", [dict(e1, problems=[REAL + "; see escalation E9"]), e2])):
    if not run(recs, "\n".join(lines(recs))):
        bad.append(f"{name}: its record lines no longer counted")
if run(base, "- decided per escalation E2"):
    bad.append("a citation of an accepted escalation counted")
print("regression:", ("FAILED " + str(bad)) if bad else "ok")
sys.exit(1 if bad else 0)

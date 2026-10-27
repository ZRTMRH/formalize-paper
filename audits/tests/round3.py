#!/usr/bin/env python3
"""The round-3 adversarial attacks (RULINGS-R3, step R3a), each kept as a self-test that must now
be REFUSED or DETECTED, with a control showing the legitimate path still works.

WHY THIS EXISTS.  The round-3 adversarial check reproduced 14 attacks with the real scripts on
scratch audit records (the replay harness, tests/replay.py `Record`: a pinned record, hands-off).
Every one worked against 0.3.0-dev at the time. Each case below is that attack, asserted to fail
now; tests/mutant_list.py has a mutant per fix that this file kills.

  python3 audits/tests/round3.py --selftest
"""
import os, sys
sys.dont_write_bytecode = True
import json, shutil, tempfile

AUDITS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AUDITS)
sys.path.insert(0, os.path.join(AUDITS, "tests"))
import project, lane_auth, lanecheck, integrity, stops, decisions, audit_coverage  # noqa: E402
from replay import Record  # noqa: E402

HDR = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
R0, R1 = "2026-10-19-full-9c8d7e60000", "2026-10-20-full-4a5b6c70000"


def write(p, s, mode="w"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, mode, encoding="utf-8").write(s)


def use(rec):
    project.REPO = project.AUDITS = rec.d


def adopt(rec, rnd, body, revotes=False, append=False):
    """Write ADOPTED.md (or append rows) and commit it with the adjudication command: True if it
    was committed, else the refusal text."""
    p = os.path.join(rec.rd, rnd, "ADOPTED.md")
    write(p, body if append else HDR + body, "a" if append else "w")
    try:
        integrity.commit_adjudication(rec.d, rec.rd, "P", rnd, revotes)
        return True
    except ValueError as e:
        return str(e)


def setaside_complete_round(base):
    """A COMPLETE round (both lanes sealed) whose non-vacuity lane Fails N.b, set aside unadjudicated."""
    r = Record(base); use(r)
    r.scope(R0, ["correspondence", "non-vacuity"])
    r.lane(R0, "correspondence", [("N.a", "Pass"), ("N.b", "Pass")])
    r.lane(R0, "non-vacuity", [("N.b", "Fail")], "non-vacuity.probes/w.lean shows the hypotheses are contradictory",
           probes={"w.lean": "example : False := by sorry -- witness"})
    stops.set_aside(r.cfg, R0, "superseded by a fresh full round")
    return r


# --- H2: a REVOTE NEEDED row is not a re-vote -------------------------------------------------

def t1(base, say):
    """T1: a carried Fail rejected with REVOTE NEEDED + REJECT rows, no re-vote lane."""
    r = setaside_complete_round(base)
    r.scope(R1, ["correspondence"]); r.lane(R1, "correspondence", [("N.a", "Pass"), ("N.b", "Pass")])
    got = adopt(r, R1, "| non-vacuity | N.b | Fail | **REVOTE NEEDED** | carried |\n"
                       "| non-vacuity | N.b | Fail | **REJECT** | on reflection the witness is wrong |\n"
                       "| correspondence | N.b | Pass | **ADOPT** | ok |\n")
    say("H2/T1: a carried Fail is not rejected by REVOTE NEEDED + REJECT rows without a re-vote lane",
        got is not True and "no re-vote lane" in got)
    # control: the REVOTE NEEDED row alone is a row; the re-vote runs, is sealed, and only then the
    # REJECT, committed as "adjudicate R revotes", settles it
    got = adopt(r, R1, "| non-vacuity | N.b | Fail | **REVOTE NEEDED** | carried |\n"
                       "| correspondence | N.b | Pass | **ADOPT** | ok |\n")
    r.lane(R1, "revote/non-vacuity--N.b", [("N.b", "Pass")])
    rows = "| non-vacuity | N.b | Pass | **REJECT** | the re-vote found the witness wrong |\n"
    plain = adopt(r, R1, rows, append=True)
    ok = adopt(r, R1, "", revotes=True, append=True)
    say("H2/T1 control: after the sealed re-vote, the REJECT settles it only in an 'adjudicate R revotes' commit",
        got is True and plain is not True and "adjudicate" in plain and ok is True
        and not stops.carried_problems(r.rd) and not lanecheck.settle_problems(os.path.join(r.rd, R1)))


def t5(base, say):
    """T5: a lane fault on N.a's Fail 'settled' by a REVOTE NEEDED row for another item, N.c."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.a", "Fail"), ("N.c", "Ambiguous")],
           "correspondence.probes/never_written.lean shows N.a misstates the bound")
    r.lane(R1, "non-vacuity", [("N.a", "Pass")], "fine")
    got = adopt(r, R1, "| correspondence | N.a | Fail | **REJECT** | the cited probe does not exist |\n"
                       "| correspondence | N.c | Ambiguous | **REVOTE NEEDED** | unclear |\n"
                       "| non-vacuity | N.a | Pass | **ADOPT** | ok |\n")
    say("H2/T5: a lane fault is settled only by a re-vote of the item citing the faulty probe",
        got is not True and "N.a" in got and "faulty probe" in got)
    got = adopt(r, R1, "| correspondence | N.a | Fail | **REVOTE NEEDED** | lane fault |\n"
                       "| correspondence | N.c | Ambiguous | **REVOTE NEEDED** | unclear |\n"
                       "| non-vacuity | N.a | Pass | **ADOPT** | ok |\n")
    say("H2/T5 control: a REVOTE NEEDED row for each item citing it settles the fault", got is True)


def t12(base, say):
    """T12: delete a Fail's probe before the seal (a lane fault), then REVOTE NEEDED + REJECT."""
    r = Record(base); use(r)
    r.scope(R1, ["non-vacuity"])
    v = r.lane(R1, "non-vacuity", [("N.a", "Fail")], "non-vacuity.probes/w.lean derives False from the hypotheses",
               probes={"w.lean": "theorem w : False := by sorry"}, seal=False)
    os.remove(os.path.join(r.rd, R1, "non-vacuity.probes", "w.lean"))
    lane_auth.seal(v, lane_auth.sha(open(v, "rb").read()), "agent-nv")
    got = adopt(r, R1, "| non-vacuity | N.a | Fail | **REVOTE NEEDED** | lane fault: its probe is missing |\n"
                       "| non-vacuity | N.a | Fail | **REJECT** | no evidence for the Fail survives |\n")
    say("H2/T12: a lane-fault Fail is not rejected by REVOTE NEEDED + REJECT without the re-vote",
        got is not True and "no re-vote lane" in got)


# --- H3: a re-vote lane's own-round path ------------------------------------------------------

def t4(base, say):
    """T4: a RE-VOTE lane cites a PATH into its own round's ADOPTED.md; one CLEARED line settled it."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | would reject: hypothesis h is used |\n")
    r.lane(R1, "revote/correspondence--N.b", [("N.b", "Pass")],
           f"As audits/P/{R1}/ADOPTED.md explains, hypothesis h is used, so Pass.")
    codes = {lanecheck.flag_code(f) for f in r.flags(R1) if "revote/" in f}
    got = adopt(r, R1, "| correspondence | N.b | Pass | **ADOPT** | the re-vote passed |\n"
                       "\n- CLEARED revote/correspondence--N.b.json: names the record only as a pointer; nothing read\n",
                revotes=True, append=True)
    say("H3/T4: a re-vote lane's path into its own round's ADOPTED.md is NOTE[independence-path]",
        "independence-path" in codes)
    say("H3/T4: ... and no CLEARED line settles a re-vote lane's NOTE (its row is left open for the human)",
        got is not True and "LEFT OPEN" in got)
    r3 = Record(base); use(r3)
    r3.scope(R1, ["correspondence"])
    r3.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r3, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | unclear |\n")
    r3.lane(R1, "revote/correspondence--N.b", [("N.b", "Pass")], "the reasons in ADOPTED.md do not apply, so Pass.")
    got = adopt(r3, R1, "| correspondence | N.b | Pass | **ADOPT** | ok |\n"
                        "\n- CLEARED revote/correspondence--N.b.json: a pointer only\n", revotes=True, append=True)
    say("H3: a re-vote lane's plain mention (NOTE[independence]) is not clearable either",
        got is not True and "LEFT OPEN" in got)
    # control: a re-vote citing only its own probe directory is not flagged
    r2 = Record(base); use(r2)
    r2.scope(R1, ["correspondence"])
    r2.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r2, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | unclear |\n")
    r2.lane(R1, "revote/correspondence--N.b", [("N.b", "Pass")],
            f"audits/P/{R1}/revote/correspondence--N.b.probes/t.lean compiles", probes={"t.lean": "example : True := trivial"})
    say("H3/T4 control: a re-vote citing its own probe by a path in its round is not flagged",
        not [f for f in r2.flags(R1) if "revote/" in f])


# --- M1: the settle check also runs in integrity --check and make_report --check ---------------

def t9(base, say):
    """T9: ADOPTED.md committed by hand as "adjudicate R": an independence-path NOTE never settled."""
    import make_report
    r = Record(base); use(r)
    RX = "2026-10-19-full-1a2b3c40000"
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.b", "Pass")], f"as audits/P/{RX}/ADOPTED.md records, N.b is fine")
    write(os.path.join(r.rd, R1, "ADOPTED.md"), HDR + "| correspondence | N.b | Pass | **ADOPT** | ok |\n")
    r.g("add", "--", f"P/{R1}/ADOPTED.md"); r.g("commit", "-qm", f"adjudicate {R1}")
    fails = r.integrity(R1)
    say("M1/T9: integrity --check FAILs an adjudication committed by hand that leaves a NOTE unsettled",
        any(f.startswith("[unsettled]") and "whole-lane" in f for f in fails))
    say("M1/T9: ... and so does make_report --check",
        any(p.startswith("! unsettled adjudication") for p in make_report.record_problems(r.rd)))
    # the re-vote proof, as committed: a decision after REVOTE NEEDED in a plain "adjudicate R" commit
    r2 = Record(base); use(r2)
    r2.scope(R1, ["correspondence"])
    r2.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r2, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | unclear |\n")
    r2.lane(R1, "revote/correspondence--N.b", [("N.b", "Pass")])
    write(os.path.join(r2.rd, R1, "ADOPTED.md"), "| correspondence | N.b | Pass | **ADOPT** | re-vote passed |\n", "a")
    r2.g("add", "--", f"P/{R1}/ADOPTED.md"); r2.g("commit", "-qm", f"adjudicate {R1}")
    say("M1/H2: a re-vote decision committed by hand as 'adjudicate R' (not '... revotes') FAILs integrity",
        any(f.startswith("[unsettled]") and "revotes" in f for f in r2.integrity(R1)))
    r2.g("reset", "-q", "--soft", "HEAD~1"); r2.g("commit", "-qm", f"adjudicate {R1} revotes")
    say("M1/H2 control: the same decision in 'adjudicate R revotes' after the seal is clean",
        not r2.integrity(R1) and not make_report.record_problems(r2.rd))


# --- M2: one decision parser ------------------------------------------------------------------

def t2(base, say):
    """T2: a carried Fail rejected with the decision cell `REJECT` (backticks): the carry check read
    "not a REJECT", the report read REJECT."""
    r = setaside_complete_round(base)
    r.scope(R1, ["correspondence"]); r.lane(R1, "correspondence", [("N.a", "Pass")])
    got = adopt(r, R1, "| non-vacuity | N.b | Fail | `REJECT` | witness wrong |\n")
    say("M2/T2: a carried Fail is not rejected by spelling the decision `REJECT`", got is not True and "N.b" in got)
    ap = os.path.join(r.rd, R1, "ADOPTED.md")
    pin = os.path.join(r.rd, integrity.PIN)
    keep = open(pin).read()
    v1 = json.loads(keep); v1["ownership"] = 1
    agree = True
    for cell in ("`REJECT`", "_REJECT_", "~~ADOPT~~ REJECT", "**REJECT**", "REJECT: wrong"):
        write(ap, HDR + f"| non-vacuity | N.b | Fail | {cell} | x |\n")
        rep = audit_coverage.read_adopted(ap).get("non-vacuity :: " + audit_coverage.norm_item("N.b"))
        # an older record (ownership 1, R3f: read best-effort) reads its decision column by the same parser
        write(pin, json.dumps(v1))
        rep1 = audit_coverage.read_adopted(ap).get("non-vacuity :: " + audit_coverage.norm_item("N.b"))
        write(pin, keep)
        agree &= rep == rep1 == "REJECT" and lanecheck.decision_rows(os.path.join(r.rd, R1))[0].decision == "REJECT"
    say("M2: the report (current and older records) and the carry check read every spelling of a decision cell alike",
        agree)
    write(ap, HDR + "| non-vacuity | N.b | Fail | probably reject | x |\n")
    say("M2: a decision cell that records no decision is refused at adjudication",
        "decision cell" in "\n".join(lanecheck.settle_problems(os.path.join(r.rd, R1))))


# --- M3: a waiver is bound to the stop that showed that commit's ownership FAIL ------------------

def ownership_stop(r, c, rnd):
    """A stop recorded by `stops.py open --cmd` while integrity --check prints c's ownership FAIL, closed
    by the human (run_cmd stubbed with the real integrity output)."""
    out = "\n".join(integrity.line_of(sv, m) for sv, m in
                    integrity.check(r.d, r.cfg, rnd, agent_file=r.agent, rounds_dir=r.rd, rounds_rel="P", repo=None))
    keep = stops.run_cmd
    stops.run_cmd = lambda argv: (1, out)
    try:
        s, _ = stops.open_stop(r.cfg, cmd="python3 audits/integrity.py --check")
    finally:
        stops.run_cmd = keep
    stops.close_stop(r.cfg, s, human="waive it")
    return s, out


def t6(base, say):
    """T6: --acknowledge with an UNRELATED human-closed stop; the waived add-only commit is a
    hand-written .abandoned marker that hides a SEALED re-vote's Fail."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | would reject |\n")
    r.lane(R1, "revote/correspondence--N.b", [("N.b", "Fail")])          # the re-vote CONFIRMS the Fail
    s, _ = stops.open_stop(r.cfg, note="the Codex spawn returned 529 overloaded", cause="tool-call")
    stops.close_stop(r.cfg, s, human="retry it later")                   # an unrelated human answer
    write(os.path.join(r.rd, R1, ".abandoned", "revote__correspondence--N.b.json"),
          json.dumps({"round": R1, "lane": "revote/correspondence--N.b", "reason": "x"}))
    r.g("add", "--", f"P/{R1}/.abandoned"); r.g("commit", "-qm", "tidy record")
    c = r.g("rev-parse", "HEAD")

    def ack(stop):
        try:
            integrity.acknowledge(r.d, r.rd, r.cfg, c, stop); return ""
        except ValueError as e:
            return str(e)
    say("M3/T6: a human-closed stop about something else does not back a waiver",
        "not about the ownership FAIL" in ack(s))
    s2, out = ownership_stop(r, c, R1)
    say("M3/T6: the stop shows that commit's FAIL[ownership] (the message names the commit)",
        any("FAIL[ownership]" in l and c[:11] in l for l in out.splitlines()))
    say("M3/T6: ... yet a commit adding a set-aside marker is never waived (control data)",
        "control data" in ack(s2) and not os.path.isdir(os.path.join(r.rd, "waivers")))
    # control: a swept PAPER_DEFECTS.md (report content) is waived on its own stop, once
    r2 = Record(base); use(r2)
    r2.scope(R1, ["correspondence"])
    write(os.path.join(r2.rd, "PAPER_DEFECTS.md"), "swept\n")
    r2.g("add", "--", "P/PAPER_DEFECTS.md"); r2.g("commit", "-qm", "implement x")
    c2 = r2.g("rev-parse", "HEAD")
    s3, _ = ownership_stop(r2, c2, R1)
    try:
        integrity.acknowledge(r2.d, r2.rd, r2.cfg, c2, s3); ok = True
    except ValueError:
        ok = False
    write(os.path.join(r2.rd, "SKIPPED.md"), "swept\n")
    r2.g("add", "--", "P/SKIPPED.md"); r2.g("commit", "-qm", "implement y")
    c3 = r2.g("rev-parse", "HEAD")
    try:
        integrity.acknowledge(r2.d, r2.rd, r2.cfg, c3, s3); twice = "accepted"
    except ValueError as e:
        twice = str(e)
    say("M3 control: a swept report record is waived on the stop that showed its FAIL; that stop backs no second",
        ok and "one waiver per stop" in twice)


# --- M4: a sealed, settleable re-vote lane is not set aside ------------------------------------

def t10(base, say):
    """T10: set-aside of a SEALED re-vote lane that CONFIRMED the Fail."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | would reject |\n")
    r.lane(R1, "revote/correspondence--N.b", [("N.b", "Fail")])           # sealed, confirms
    try:
        stops.set_aside(r.cfg, R1, "re-vote will not be settled", lane="revote/correspondence--N.b"); got = "set aside"
    except stops.Refused as e:
        got = str(e)
    say("M4/T10: a sealed re-vote lane with no fault of its own is not set aside", "--revotes" in got)
    # control: an issued re-vote that never returned is set aside
    v = os.path.join(r.rd, R1, "revote", "correspondence--N.a.json")
    pf = os.path.join(r.rd, R1, "prompts", "revote-correspondence--N.a.txt")
    write(pf, f"Write that JSON object, and nothing else, to {v}\n")
    lane_auth.issue_prompt(pf)
    r.g("add", "--", f"P/{R1}"); r.g("commit", "-qm", f"scope {R1} (re-vote issued)")
    try:
        stops.set_aside(r.cfg, R1, "the re-vote never returned", lane="revote/correspondence--N.a"); ok = True
    except stops.Refused as e:
        ok = str(e)
    say("M4 control: a re-vote lane that never returned is still set aside", ok is True)


# --- M5: reissue rolls back a failed commit ----------------------------------------------------

def t7(base, say):
    """T7/T7b: `lane_auth reissue` under a stale index.lock rewrote the commitment and moved the verdict
    before the commit failed, and undid nothing: a tamper-class state no command repaired."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    v = os.path.join(r.rd, R1, "correspondence.json")
    pf = os.path.join(r.rd, R1, "prompts", "correspondence.txt")
    write(pf, f"Write that JSON object, and nothing else, to {v}\n")
    lane_auth.issue_prompt(pf)
    r.g("add", "--", f"P/{R1}"); r.g("commit", "-qm", f"scope {R1} (issue)")
    half = json.dumps({"lane_token": "0" * 64, "verdicts": []})
    write(v, half)                                                     # a half-written verdict
    lock = os.path.join(r.d, ".git", "index.lock"); open(lock, "w").close()
    try:
        lane_auth.reissue(v, "spawn line lost (usage limit)"); failed = False
    except lane_auth.AuthError:
        failed = True
    os.remove(lock)                                                    # stops.py repair-lock's job
    probs = lane_auth.validate(v, require_seal=False)
    say("M5/T7: a reissue whose commit fails leaves the lane as it was (verdict in place, commitment unchanged)",
        failed and os.path.exists(v) and open(v).read() == half and not any("auth-metadata" in p for p in probs)
        and not r.g("status", "--porcelain", "--", f"P/{R1}/.lane-auth")
        and not os.path.exists(os.path.join(r.rd, R1, ".reissued")))
    try:
        lane_auth.reissue(v, "retry after repair-lock"); again = True
    except lane_auth.AuthError as e:
        again = str(e)
    say("M5/T7b: after repair-lock the same reissue runs (no human, no git checkout)",
        again is True and r.g("log", "-1", "--format=%s").startswith(f"scope {R1} (reissue correspondence.json"))


# --- L1: interrupted record commands can be re-run ---------------------------------------------

class Killed(BaseException):
    """A kill between a command's write and its commit (not an Exception: no handler cleans up)."""


def killed_once(mod, name):
    keep = getattr(mod, name)

    def boom(*a, **k):
        setattr(mod, name, keep)
        raise Killed()
    setattr(mod, name, boom)
    return keep


def t8(base, say):
    """T8: a set-aside killed between writing its marker and committing it could not be re-run."""
    r = Record(base); use(r)
    r.scope(R0, ["correspondence"])
    r.lane(R0, "correspondence", [("N.b", "Fail")], seal=False)
    write(os.path.join(r.rd, R0, "ABANDONED.json"), "{}")                # cut short by the kill
    try:
        stops.set_aside(r.cfg, R0, "lanes crashed", unsealable=["correspondence"]); first = True
    except stops.Refused as e:
        first = str(e)
    os.remove(os.path.join(r.rd, R0, "ABANDONED.json"))                  # the printed recovery
    try:
        stops.set_aside(r.cfg, R0, "lanes crashed", unsealable=["correspondence"]); again = True
    except stops.Refused as e:
        again = str(e)
    r.scope(R1, ["correspondence"])
    say("L1/T8 (R3c N2): a cut-short marker is refused with the recovery; after it, the set-aside runs and "
        "integrity is clean", first is not True and f"Recover: rm P/{R0}/ABANDONED.json" in first
        and again is True and not r.integrity(R1))
    r2 = Record(base); use(r2)
    r2.scope(R0, ["correspondence"])
    r2.lane(R0, "correspondence", [("N.b", "Fail")], seal=False)
    keep = killed_once(stops, "commit")
    try:
        stops.set_aside(r2.cfg, R0, "lanes crashed", unsealable=["correspondence"])
    except Killed:
        pass
    finally:
        stops.commit = keep
    written = os.path.exists(os.path.join(r2.rd, R0, "ABANDONED.json"))
    try:
        doc, _ = stops.set_aside(r2.cfg, R0, "lanes crashed", unsealable=["correspondence"]); again = True
    except stops.Refused as e:
        again, doc = str(e), {}
    subj = r2.g("log", "-1", "--format=%s")
    r2.scope(R1, ["correspondence"])
    say("L1: a set-aside killed after writing its whole marker is completed by running it again",
        written and again is True and bool(doc.get("carried")) and not r2.integrity(R1) and subj == f"set-aside {R0}")


def t8b(base, say):
    """T8b: `stops.py open` killed between writing STOP.json and its commit: the trail FAILed for good."""
    r = Record(base); use(r)
    keep = killed_once(stops, "commit")
    try:
        stops.open_stop(r.cfg, note="x", cause="tool-call")
    except Killed:
        pass
    finally:
        stops.commit = keep
    try:
        stops.open_stop(r.cfg, note="next", cause="tool-call"); o = "opened"
    except stops.Refused as e:
        o = str(e)
    keep = killed_once(stops, "commit")
    try:
        stops.close_stop(r.cfg, "S1", delegated="retried")
    except Killed:
        pass
    finally:
        stops.commit = keep
    try:
        stops.close_stop(r.cfg, "S1", delegated="retried"); c = "closed"
    except stops.Refused as e:
        c = str(e)
    r.scope(R1, ["correspondence"])
    say("L1/T8b: an interrupted open is completed by the next open (which then waits for S1) ...",
        "still open" in o and "interrupted `open`, completed" in o)
    say("L1/T8b: ... and an interrupted close by the next close; the stop trail stays clean",
        "S1 is closed" in c and not [x for x in r.integrity(R1) if "stop" in x])


def t_ack(base, say):
    """L1: --acknowledge killed between writing the waiver and committing it."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    write(os.path.join(r.rd, "PAPER_DEFECTS.md"), "swept\n")
    r.g("add", "--", "P/PAPER_DEFECTS.md"); r.g("commit", "-qm", "implement x")
    c = r.g("rev-parse", "HEAD")
    s, _ = ownership_stop(r, c, R1)
    keep = killed_once(project, "commit_only")
    try:
        integrity.acknowledge(r.d, r.rd, r.cfg, c, s)
    except (Killed, ValueError):
        pass
    finally:
        project.commit_only = keep
    try:
        integrity.acknowledge(r.d, r.rd, r.cfg, c, s); ok = True
    except ValueError as e:
        ok = str(e)
    say("L1: an interrupted --acknowledge runs again", ok is True and r.g("log", "-1", "--format=%s") == f"ack {c[:11]}")


# --- CONS M1: a round named by its hash ---------------------------------------------------------

def t_hash(base, say):
    """A lane naming another round by its commit hash ("as decided in round 0b23c87") was not flagged."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.b", "Pass")], "as decided in round 0b23c87, N.b is fine")
    codes = {lanecheck.flag_code(f) for f in r.flags(R1)}
    say("CONS M1: another round named by its hash is NOTE[independence]", codes == {"independence"})
    r2 = Record(base); use(r2)
    r2.scope(R1, ["correspondence"])
    r2.lane(R1, "correspondence", [("N.b", "Pass")], "this is round 4a5b6c7; checked at Lean commit 0b23c87")
    say("CONS M1 control: its own round's hash, and a bare commit hash, are not flagged", not r2.flags(R1))


# --- M6: a carried Fail is settled only by a row about it -------------------------------------

def t3(base, say):
    """T3: a carried non-vacuity Fail settled by a fresh round's Pass rows (re-roll of a complete round)."""
    r = setaside_complete_round(base)
    r.scope(R1, ["correspondence", "non-vacuity"])
    r.lane(R1, "correspondence", [("N.b", "Pass")]); r.lane(R1, "non-vacuity", [("N.b", "Pass")])
    got = adopt(r, R1, "| correspondence | N.b | Pass | **ADOPT** | fine |\n| non-vacuity | N.b | Pass | **ADOPT** | fine |\n")
    say("M6/T3: a fresh lane's Pass rows do not settle the carried Fail", got is not True and "N.b" in got)
    got = adopt(r, R1, "| correspondence | N.b | Pass | **ADOPT** | fine |\n| non-vacuity | N.b | Pass | **ADOPT** | fine |\n"
                       "| non-vacuity | N.b | Fail | **DEFER** | the carried witness: to the human |\n")
    say("M6 control: an explicit row on the carried Fail (its lane, its verdict) settles it", got is True)
    r2 = setaside_complete_round(base)
    r2.scope(R1, ["correspondence"]); r2.lane(R1, "correspondence", [("N.b", "Pass")])
    got = adopt(r2, R1, "| correspondence | N.b | Fail | **ADOPT** | fine |\n")
    say("M6: a row of another lane does not settle the carried Fail", got is not True and "N.b" in got)


# --- R3c: the re-check attacks (round3/adversarial2/attacks2.py A1-A4) --------------------------

def revote_round(base):
    """An adjudicated round whose correspondence Fail of N.b awaits its re-vote (REVOTE NEEDED)."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r, R1, "| correspondence | N.b | Fail | **REVOTE NEEDED** | would reject: h is used |\n")
    return r


def issue_only(r, lane):
    pf = os.path.join(r.rd, R1, "prompts", lane.replace("/", "__") + ".txt")
    write(pf, f"Write that JSON object, and nothing else, to {os.path.join(r.rd, R1, lane + '.json')}\n")
    lane_auth.issue_prompt(pf)


REJECT_ROW = "| correspondence | N.b | Fail | **REJECT** | the re-vote could not be completed; h is used |\n"


def t_n1(base, say):
    """N1 (A1, A2): a set-aside re-vote lane counted as "the re-vote ran" and licensed a REJECT."""
    r = revote_round(base)
    issue_only(r, "revote/correspondence--N.b")                      # A1: never spawned, set aside
    stops.set_aside(r.cfg, R1, "the re-vote lane crashed before writing", lane="revote/correspondence--N.b")
    a1 = adopt(r, R1, REJECT_ROW, revotes=True, append=True)
    say("R3c N1/A1: a never-returned re-vote, set aside, does not license a REJECT",
        a1 is not True and "was set aside" in a1)
    r2 = revote_round(base)                                          # A2: confirmed, unsealed, --unsealable
    r2.lane(R1, "revote/correspondence--N.b", [("N.b", "Fail")], seal=False)
    stops.set_aside(r2.cfg, R1, "seal digest lost", lane="revote/correspondence--N.b",
                    unsealable=["revote/correspondence--N.b"])
    a2 = adopt(r2, R1, REJECT_ROW, revotes=True, append=True)
    say("R3c N1/A2: a re-vote that confirmed the Fail, set aside unsealed, does not license a REJECT",
        a2 is not True and "was set aside" in a2)
    write(os.path.join(r2.rd, R1, "ADOPTED.md"), r2.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    rv = decisions.open_revotes([os.path.join(r2.rd, R1)])
    say("R3c N1: ... the item stays open for the human (an open re-vote, its lane set aside); the carried "
        "Fail needs no other row", [(x[2], x[4]) for x in rv] == [("N.b", True)] and not stops.carried_problems(r2.rd))
    # control: a SEALED re-vote still settles the item in "adjudicate R revotes"
    r3 = revote_round(base)
    r3.lane(R1, "revote/correspondence--N.b", [("N.b", "Pass")])
    say("R3c N1 control: after a sealed re-vote, the REJECT is committed as 'adjudicate R revotes'",
        adopt(r3, R1, REJECT_ROW, revotes=True, append=True) is True)
    say("R3e: ... and the settled re-vote is no longer listed open", opened(r3) == [])


# --- R3d: the final-check attacks (round3/adversarial3/attacks3.py V9, V7, V6) ----------------------

WHOLE_ROW = "| correspondence | (whole lane) | - | **REVOTE NEEDED** | doubt |\n"


def t_r3d(base, say):
    """F1 (V9): a re-vote whose sealed verdict never judged the item licensed its REJECT. F2 (V7): of
    several sealed re-votes of an item, sort order picked one. F3 (V6): a later re-vote settled an item
    whose re-vote was set aside."""
    # F1: batched lane; part 2's whole-lane re-vote (--ALL.2) never judged N.b (a part-1 Fail)
    r = Record(base); use(r)
    r.scope(R1, ["correspondence@1", "correspondence@2"])
    r.lane(R1, "correspondence@1", [("N.b", "Fail")]); r.lane(R1, "correspondence@2", [("N.z", "Fail")])
    adopt(r, R1, "| correspondence@1 | N.b | Fail | **REVOTE NEEDED** | doubt |\n"
                 "| correspondence@2 | (whole lane) | - | **REVOTE NEEDED** | doubt |\n")
    r.lane(R1, "revote/correspondence--ALL.2", [("N.z", "Pass")])
    z = "| correspondence@2 | N.z | Fail | **REJECT** | re-vote passed |\n"
    got = adopt(r, R1, z + "| correspondence@1 | N.b | Fail | **REJECT** | h is used |\n", revotes=True, append=True)
    say("R3d F1/V9: a part-2 whole-lane re-vote that never judged N.b does not license REJECT of N.b",
        got is not True and "never judged the item" in got)
    write(os.path.join(r.rd, R1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    say("R3d F1 control: the same re-vote licenses the REJECT of the item it judged (N.z)",
        adopt(r, R1, z, revotes=True, append=True) is True)
    # F2: --ALL confirms the Fail, --ALL.2 votes Pass: neither settles N.b
    r2 = Record(base); use(r2)
    r2.scope(R1, ["correspondence"]); r2.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r2, R1, WHOLE_ROW)
    r2.lane(R1, "revote/correspondence--ALL", [("N.b", "Fail")])
    r2.lane(R1, "revote/correspondence--ALL.2", [("N.b", "Pass")])
    got = adopt(r2, R1, REJECT_ROW, revotes=True, append=True)
    say("R3d F2/V7: two sealed re-votes of N.b: neither licenses the REJECT (none chosen by sort order)",
        got is not True and "more than one sealed re-vote" in got)
    write(os.path.join(r2.rd, R1, "ADOPTED.md"), r2.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    say("R3d F2: ... the item stays open for the human (an open re-vote)",
        [x[2] for x in decisions.open_revotes([os.path.join(r2.rd, R1)])] == ["(whole lane)"])
    r3 = Record(base); use(r3)                                           # control: one whole-lane re-vote
    r3.scope(R1, ["correspondence"]); r3.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r3, R1, WHOLE_ROW)
    r3.lane(R1, "revote/correspondence--ALL", [("N.b", "Pass")])
    say("R3d F2 control: one sealed whole-lane re-vote that judged N.b licenses the REJECT",
        adopt(r3, R1, REJECT_ROW, revotes=True, append=True) is True)
    # F3: the item re-vote (Fail, unsealed) set aside; a later whole-lane re-vote (Pass) does not settle it
    r4 = revote_round(base)
    r4.lane(R1, "revote/correspondence--N.b", [("N.b", "Fail")], seal=False)
    stops.set_aside(r4.cfg, R1, "seal digest lost", lane="revote/correspondence--N.b",
                    unsealable=["revote/correspondence--N.b"])
    assert adopt(r4, R1, WHOLE_ROW, append=True) is True
    r4.lane(R1, "revote/correspondence--ALL", [("N.b", "Pass")])
    got = adopt(r4, R1, REJECT_ROW, revotes=True, append=True)
    say("R3d F3/V6: a whole-lane re-vote after the item's re-vote was set aside does not license the REJECT",
        got is not True and "was set aside" in got)
    write(os.path.join(r4.rd, R1, "ADOPTED.md"), r4.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    say("R3d F3: ... the item stays open for the human; the carried Fail needs no other row",
        ("N.b", True) in [(x[2], x[4]) for x in decisions.open_revotes([os.path.join(r4.rd, R1)])]
        and not stops.carried_problems(r4.rd))


# --- R3e: one strict reader of decision rows (round3/narrow/narrow.py H1, M1, M2, L1-L3) -----------

def carried_revote_round(base):
    """R0 set aside (non-vacuity Fails N.b, carried); R1 asks for its re-vote (committed)."""
    r = setaside_complete_round(base)
    r.scope(R1, ["correspondence", "non-vacuity"])
    r.lane(R1, "correspondence", [("N.b", "Pass")]); r.lane(R1, "non-vacuity", [("N.b", "Pass")])
    assert adopt(r, R1, "| non-vacuity | N.b | Fail | **REVOTE NEEDED** | carried Fail, doubt |\n") is True
    return r


def opened(r):
    return [(x[1], x[2], x[4]) for x in decisions.open_revotes([os.path.join(r.rd, R1)])]


def t_r3e(base, say):
    """H1: a row of another lane, or a lane or item cell spelled differently, was ignored by every settle
    check yet removed the open re-vote from the human's list. M1: an entry with no valid verdict counted as
    judged. M2: a decision passed over an unsealed re-vote. L1-L3: whole-lane rows, --ALL.k, abandoned."""
    # H1 (x1c): another lane's ADOPT of the carried item: committed, but the re-vote stays listed
    r = carried_revote_round(base)
    got = adopt(r, R1, "| correspondence | N.b | Pass | **ADOPT** | corresponds |\n", append=True)
    say("R3e H1/x1c: another lane's ADOPT of the item leaves the carried Fail's re-vote listed for the human",
        got is True and opened(r) == [("non-vacuity", "N.b", False)] and not stops.carried_problems(r.rd))
    # H1 (x2c, x2): a lane cell that is no lane of the round is refused, whatever the decision
    bad = {}
    for cell, dec in (("Non-vacuity", "REJECT"), ("nonvacuity", "REJECT"), ("Non-vacuity", "DEFER"),
                      ("non-vacuity.json", "REJECT"), ("non-vacuity-lane", "REJECT")):
        r = carried_revote_round(base)
        bad[cell, dec] = adopt(r, R1, f"| {cell} | N.b | Fail | **{dec}** | not vacuous |\n", append=True)
    say("R3e H1/x2c: a decision row whose lane cell is no lane of the round (case, .json, -lane) is refused",
        all(g is not True and "is not a lane of round" in g for g in bad.values()))
    say("R3e H1: ... with the round's lane names in the refusal",
        all(g is not True and "non-vacuity" in g for g in bad.values()))
    r = revote_round(base)
    g1 = adopt(r, R1, "| correspondence | n.b | Fail | **REJECT** | h is used |\n", append=True)
    say("R3e H1/x3: an item cell that is no scope item of the round (n.b) is refused",
        g1 is not True and "is not a scope item" in g1)
    for cell in ("`correspondence`", "**correspondence**"):
        write(os.path.join(r.rd, R1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
        g2 = adopt(r, R1, f"| {cell} | _N.b_ | Fail | **REJECT** | h is used |\n", append=True)
        say(f"R3e H1 control: {cell} with item _N.b_ is read as correspondence, N.b (and refused by the re-vote "
            "rule)", g2 is not True and "no re-vote lane" in g2 and "is not a lane" not in g2
            and "is not a scope item" not in g2)
    write(os.path.join(r.rd, R1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    # integrity --check and make_report --check (record_problems) refuse such a row committed by hand
    write(os.path.join(r.rd, R1, "ADOPTED.md"), "| Correspondence | N.b | Fail | **REJECT** | h |\n", "a")
    r.g("add", "--", f"P/{R1}/ADOPTED.md"); r.g("commit", "-qm", f"adjudicate {R1}")
    say("R3e H1: a misspelled lane committed by hand fails integrity --check and the report check",
        any("is not a lane of round" in m for m in r.integrity(R1))
        and any("is not a lane of round" in p_ for p_ in lanecheck.record_problems(r.rd)))
    # M1 (x4): only an entry with a verdict Pass/Fail/Ambiguous, the item's only entry, judges it
    lanes_ = {}
    for label, entries in (("no verdict", [{"item": "N.b"}]), ("verdict ''", [{"item": "N.b", "verdict": ""}]),
                           ("verdict 'Maybe'", [{"item": "N.b", "verdict": "Maybe"}]),
                           ("Pass and Fail", [{"item": "N.b", "verdict": "Pass"}, {"item": "N.b", "verdict": "Fail"}]),
                           ("two Pass", [{"item": "N.b", "verdict": "Pass"}, {"item": "N.b", "verdict": "Pass"}]),
                           ("control: `N.b` Pass", [{"item": "`N.b`", "verdict": "Pass", "next_step": ""}])):
        r = Record(base); use(r)
        r.scope(R1, ["correspondence"]); r.lane(R1, "correspondence", [("N.b", "Fail")])
        adopt(r, R1, WHOLE_ROW)
        v = r.lane(R1, "revote/correspondence--ALL", [], seal=False)
        doc = json.load(open(v)); doc["verdicts"] = entries
        data = json.dumps(doc).encode(); open(v, "wb").write(data)
        lane_auth.seal(v, lane_auth.sha(data), "agent-rv")
        lanes_[label] = adopt(r, R1, REJECT_ROW, revotes=True, append=True)
    say("R3e M1/x4: a re-vote entry with no, an empty or an unknown verdict, or two entries for the item, "
        "never judged it", all(g is not True and "no re-vote lane" in g for k, g in lanes_.items()
                               if not k.startswith("control")))
    say("R3e M1 control: one entry `N.b` Pass judges N.b", lanes_["control: `N.b` Pass"] is True)
    # M2 (x5d, x5): an unsealed re-vote covering the item blocks the decision until sealed or set aside
    r = revote_round(base)
    r.lane(R1, "revote/correspondence--N.b", [("N.b", "Fail")], seal=False)
    assert adopt(r, R1, WHOLE_ROW, append=True) is True
    r.lane(R1, "revote/correspondence--ALL", [("N.b", "Pass")])
    got = adopt(r, R1, REJECT_ROW, revotes=True, append=True)
    say("R3e M2/x5d: the item re-vote (Fail) left unsealed, a whole-lane one (Pass) sealed: REJECT refused",
        got is not True and "exists unsealed" in got and "revote/correspondence--N.b.json" in got)
    write(os.path.join(r.rd, R1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    say("R3e M2: ... both rows stay listed for the human", [x[1] for x in opened(r)] == ["N.b", "(whole lane)"])
    # L1: the (whole lane) row is settled once its whole-lane re-vote settled the lane's items
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"]); r.lane(R1, "correspondence", [("N.a", "Pass"), ("N.b", "Fail")])
    adopt(r, R1, WHOLE_ROW)
    r.lane(R1, "revote/correspondence--ALL", [("N.a", "Pass"), ("N.b", "Pass")])
    early = adopt(r, R1, "| correspondence | (whole lane) | - | **REJECT** | replaced by the re-vote's |\n",
                  revotes=True, append=True)
    write(os.path.join(r.rd, R1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    say("R3e L1: the (whole lane) row is not closed before the items its re-vote judged are decided",
        early is not True and "whole-lane re-vote has not settled it" in early and opened(r) == [
            ("correspondence", "(whole lane)", False)])
    ok1 = adopt(r, R1, REJECT_ROW, revotes=True, append=True)
    say("R3e L1: once the whole-lane re-vote settled N.b, the (whole lane) row is no longer listed",
        ok1 is True and opened(r) == [])
    say("R3e L1: ... and the protocol's closing row | (whole lane) | **REJECT** | is accepted",
        adopt(r, R1, "| correspondence | (whole lane) | - | **REJECT** | replaced by the re-vote's |\n",
              revotes=True, append=True) is True and opened(r) == [])
    # L3: a set-aside whole-lane re-vote marks its row abandoned
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"]); r.lane(R1, "correspondence", [("N.b", "Fail")])
    adopt(r, R1, WHOLE_ROW)
    issue_only(r, "revote/correspondence--ALL")
    stops.set_aside(r.cfg, R1, "the re-vote lane crashed", lane="revote/correspondence--ALL")
    say("R3e L3: a set-aside --ALL marks the (whole lane) row abandoned",
        opened(r) == [("correspondence", "(whole lane)", True)])
    # L2 (x9): part 2's set-aside --ALL.2 is not part 1's re-vote; its own carried item stays open
    r = Record(base); use(r)
    r.scope(R1, ["correspondence@1", "correspondence@2"])
    r.lane(R1, "correspondence@1", [("N.b", "Fail")]); r.lane(R1, "correspondence@2", [("N.z", "Fail")])
    adopt(r, R1, "| correspondence@1 | N.b | Fail | **REVOTE NEEDED** | doubt |\n"
                 "| correspondence@2 | (whole lane) | - | **REVOTE NEEDED** | doubt |\n")
    r.lane(R1, "revote/correspondence--ALL.2", [("N.z", "Fail")], seal=False)
    stops.set_aside(r.cfg, R1, "lost", lane="revote/correspondence--ALL.2", unsealable=["revote/correspondence--ALL.2"])
    r.lane(R1, "revote/correspondence--N.b", [("N.b", "Pass")])
    got = adopt(r, R1, "| correspondence@1 | N.b | Fail | **REJECT** | re-vote passed |\n", revotes=True, append=True)
    rd1 = os.path.join(r.rd, R1)
    say("R3e L2/x9: part 2's set-aside --ALL.2 does not block part 1's item, whose own re-vote ran",
        got is True and opened(r) == [("correspondence@2", "(whole lane)", True)] and not stops.carried_problems(r.rd))
    say("R3e L2: ... and blocks its own part's item, naming --ALL.2",
        lanecheck.set_aside_revote(rd1, "correspondence@2", "N.z") == "revote/correspondence--ALL.2.json"
        and lanecheck.set_aside_revote(rd1, "correspondence@1", "N.b") is None)


# --- R3g: lanecheck validates every lane verdict file's schema (narrow X4 "with junk entries") ------

def raw_lane(r, lane, entries):
    """Issue lane `lane` of R1 and seal a verdict whose entries are given raw (malformed ones allowed)."""
    v = r.lane(R1, lane, [], seal=False)
    doc = json.load(open(v)); doc["verdicts"] = entries
    data = json.dumps(doc).encode(); open(v, "wb").write(data)
    lane_auth.seal(v, lane_auth.sha(data), "agent-" + lane.replace("/", "-"))
    return v


def t_r3g(base, say):
    """X4: a sealed re-vote whose entries hold one valid entry for the item beside non-object entries
    licensed the REJECT. A verdict that breaks the schema is a lane fault: it judged nothing."""
    PASS = {"item": "N.b", "verdict": "Pass", "next_step": ""}
    got = {}
    for label, entries in (("junk", [PASS, "junk", None]), ("control", [PASS]),
                           ("NotDoneYet", [{"item": "N.b", "verdict": "NotDoneYet"}])):
        r = Record(base); use(r)
        r.scope(R1, ["correspondence"]); r.lane(R1, "correspondence", [("N.b", "Fail")])
        adopt(r, R1, WHOLE_ROW)
        raw_lane(r, "revote/correspondence--ALL", entries)
        fl = [f for f in r.flags(R1) if lanecheck.flag_code(f) == "lane-fault"]
        got[label] = (adopt(r, R1, REJECT_ROW, revotes=True, append=True), fl, r)
    g, fl, r = got["junk"]
    say("R3g X4: a re-vote verdict with junk entries beside a valid one is NOTE[lane-fault] (schema)",
        any(lanecheck.SCHEMA_FAULT in f and "revote/correspondence--ALL.json" in f for f in fl))
    say("R3g X4: ... and its REJECT is refused", g is not True and "no re-vote lane" in g)
    say("R3g X4: ... and the re-vote lane's own fault asks for LEFT OPEN (never a second re-vote)",
        g is not True and "LEFT OPEN revote/correspondence--ALL.json" in g)
    write(os.path.join(r.rd, R1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n" + REJECT_ROW + "\n"
          "- LEFT OPEN revote/correspondence--ALL.json: its verdict breaks the schema\n")
    g2 = adopt(r, R1, "", revotes=True, append=True)
    say("R3g X4: ... even once the re-vote lane is LEFT OPEN: the re-vote judged nothing, the row stays open",
        g2 is not True and "no re-vote lane" in g2)
    say("R3g control: a clean re-vote verdict still settles the item (no schema fault)",
        got["control"][0] is True and not got["control"][1])
    say("R3g: a NotDoneYet entry follows the schema but never judges the item",
        not got["NotDoneYet"][1] and got["NotDoneYet"][0] is not True and "no re-vote lane" in got["NotDoneYet"][0])
    # an original lane breaking the schema: every item it names is re-voted (the whole lane if one names none)
    for label, entries, want in (("bad verdict", [{"item": "N.a", "verdict": "Pass"}, {"item": "N.b", "verdict": "pass"}],
                                  "N.a, N.b"),
                                 ("no item", [{"item": "N.a", "verdict": "Pass"}, {"verdict": "Fail"}], "(whole lane)")):
        r = Record(base); use(r)
        r.scope(R1, ["correspondence"])
        raw_lane(r, "correspondence", entries)
        g = adopt(r, R1, "| correspondence | N.a | Pass | **ADOPT** | ok |\n")
        say(f"R3g: an original lane breaking the schema ({label}) needs a re-vote of {want}",
            g is not True and (f"({want})" in g if want != "(whole lane)" else "its whole lane" in g))
        rows = (WHOLE_ROW if want == "(whole lane)" else
                "| correspondence | N.a | Pass | **REVOTE NEEDED** | lane fault |\n"
                "| correspondence | N.b | - | **REVOTE NEEDED** | lane fault |\n")
        say(f"R3g control: ... and those REVOTE NEEDED rows settle it ({label})", adopt(r, R1, rows) is True)


INDEX_LEAN = """/-! Index.

| Result | Lean |
|---|---|
| Lemma 4.40 | `N.l440` |
| Theorem 1.1 | not formalized yet |
-/
namespace N
theorem l440 : True := trivial
end N
"""


def index_round(base):
    """A pinned record whose project config (audits/projects/P.json, rounds dir P) names an index file
    with rows Lemma 4.40 and Theorem 1.1 and the declaration N.l440; round R0's FINGERPRINTS.json keys
    N.old (since deleted); round R1 scopes correspondence on N.a..N.z, which judged N.a only."""
    r = Record(base); use(r)
    write(os.path.join(r.d, "audits", "projects", "P.json"),
          json.dumps({"name": "P", "rounds_dir": "P", "lean_files": ["L/Main.lean"], "index_file": "L/Main.lean"}))
    write(os.path.join(r.d, "L", "Main.lean"), INDEX_LEAN)
    r.g("add", "--", "audits/projects/P.json", "L/Main.lean"); r.g("commit", "-qm", "project")
    r.scope(R0, ["correspondence"])
    write(os.path.join(r.rd, R0, "FINGERPRINTS.json"), json.dumps({"fingerprints": {"N.old": "f0", "N.l440": "f1"}}))
    r.g("add", "--", f"P/{R0}/FINGERPRINTS.json"); r.g("commit", "-qm", f"scope {R0}")
    r.scope(R1, ["correspondence"])
    r.lane(R1, "correspondence", [("N.a", "Pass")])
    return r


def t_r3f(base, say):
    """R3f: an UNCOVERED row for a NotDoneYet index entry, or for a STALE PASS, names an item outside the
    round's TARGET.json; the strict reader refused it. It now reads every declared item of the project
    (index rows, declarations, fingerprint snapshots), still exactly. audit_coverage.read_adopted reads a
    current-format record through the same reader."""
    r = index_round(base)
    rd1 = os.path.join(r.rd, R1)
    say("R3f: the project's declared items are the index labels, declarations and snapshot names",
        {"Lemma 4.40", "Theorem 1.1", "N.l440", "N.old"} <= lanecheck.project_items(r.rd))
    got = adopt(r, R1, "| correspondence | Theorem 1.1 | NotDoneYet | **UNCOVERED** | no lane reached it |\n"
                       "| correspondence | `N.l440` | STALE PASS | **UNCOVERED** | its meaning changed |\n")
    say("R3f: an UNCOVERED row for a NotDoneYet index entry and a STALE PASS row (a declaration) are accepted",
        got is True and [(x.item, x.problem) for x in lanecheck.decision_rows(rd1)]
        == [("Theorem 1.1", None), ("N.l440", None)])
    got = adopt(r, R1, "| correspondence | N.old | STALE PASS | **UNCOVERED** | no longer exists |\n", append=True)
    say("R3f: a STALE PASS row for a declaration since deleted (in a round's FINGERPRINTS.json) is accepted",
        got is True and not lanecheck.record_problems(r.rd))
    bad = {}
    for cell in ("theorem 1.1", "Theorem  1.1", "Theorem 1.1.", "Lemma 4.4", "N.L440", "l440", "N.l440.json"):
        write(os.path.join(rd1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
        bad[cell] = adopt(r, R1, f"| correspondence | {cell} | NotDoneYet | **UNCOVERED** | x |\n", append=True)
    say("R3f: a misspelled index item (case, spacing, a prefix, a short name) is still refused",
        all(g is not True and "is not a scope item" in g for g in bad.values()))
    write(os.path.join(rd1, "ADOPTED.md"), r.g("show", f"HEAD:P/{R1}/ADOPTED.md") + "\n")
    # audit_coverage.read_adopted reads the pinned (ownership 2) record through lanecheck.decision_rows
    ap = os.path.join(rd1, "ADOPTED.md")
    write(ap, "| correspondence + non-vacuity | N.a | Pass | **ADOPT** | two lanes in one cell |\n"
              "| Correspondence | N.a | Pass | **REJECT** | misspelled lane |\n"
              "| correspondence | theorem 1.1 | NotDoneYet | **ADOPT** | misspelled item |\n", "a")
    want = {f"{x.base} :: {audit_coverage.norm_item(x.item)}": x.decision for x in lanecheck.valid_rows(rd1)}
    got = audit_coverage.read_adopted(ap)
    say("R3f: audit_coverage.read_adopted reads a current-format record through the shared reader",
        audit_coverage.strict_rows(r.rd) and got == want and got == {
            "correspondence :: theorem 1.1": "UNCOVERED", "correspondence :: l440": "UNCOVERED",
            "correspondence :: old": "UNCOVERED"})
    pin = os.path.join(r.rd, integrity.PIN)
    keep = open(pin).read()
    d = json.loads(keep); d["ownership"] = 1; write(pin, json.dumps(d))
    old, strict1 = audit_coverage.read_adopted(ap), audit_coverage.strict_rows(r.rd)
    write(pin, keep)
    say("R3f control: a record pinned under ownership 1 (before strict rows) keeps the best-effort reading",
        not strict1 and old.get("non-vacuity :: a") == "ADOPT" and "non-vacuity :: a" not in got)


def t_n2(base, say):
    """N2 (A3): a hand-written ABANDONED.json (carried: []) was committed by the 'resume' path."""
    r = Record(base); use(r)
    r.scope(R0, ["non-vacuity"])
    r.lane(R0, "non-vacuity", [("N.b", "Fail")], "non-vacuity.probes/w.lean", probes={"w.lean": "-- w"})
    rd0 = os.path.join(r.rd, R0)
    st = r.g("status", "--porcelain", "--untracked-files=all", "--", f"P/{R0}").splitlines()
    files = {os.path.relpath(os.path.join(r.d, l[3:]), rd0): stops.sha(open(os.path.join(r.d, l[3:]), "rb").read())
             for l in st}
    mk = os.path.join(rd0, "ABANDONED.json")
    forged = {"round": R0, "lane": None, "date": stops.today(), "involvement": "hands-off", "delegated": True,
              "reason": "superseded", "stop": None, "stop_causes": [], "lanes": {"non-vacuity.json": "sealed"},
              "unsealable": [], "carried": [], "files": files}
    write(mk, json.dumps(forged))
    try:
        stops.set_aside(r.cfg, R0, "superseded"); got = "committed"
    except stops.Refused as e:
        got = str(e)
    say("R3c N2/A3: a hand-written set-aside marker is never committed as found (refused, file left, recovery printed)",
        "never committed as found" in got and "(carried)" in got and os.path.exists(mk)
        and not stops._last_commit(r.d, mk))
    try:
        os.remove(mk)
        doc, _ = stops.set_aside(r.cfg, R0, "superseded")
    except (OSError, stops.Refused):
        doc = {"carried": []}
    say("R3c N2 control: after the recovery the set-aside carries the Fail", [c["item"] for c in doc["carried"]] == ["N.b"])
    # an uncommitted lane marker does not hide its lane from a whole-round set-aside
    r2 = Record(base); use(r2)
    r2.scope(R0, ["correspondence"])
    r2.lane(R0, "correspondence", [("N.b", "Fail")])
    write(os.path.join(r2.rd, R0, ".abandoned", "correspondence.json"), "{}")
    try:
        stops.set_aside(r2.cfg, R0, "superseded"); got = "committed"
    except stops.Refused as e:
        got = str(e)
    say("R3c N2: an uncommitted lane marker is refused in a whole-round set-aside", "never committed as found" in got)


def t_n3(base, say):
    """N3 (A4): an operator-written STOP.json (fabricated output) was committed as "stop S1 open"."""
    r = Record(base); use(r)
    r.scope(R1, ["correspondence"])
    sd = os.path.join(r.rd, "stops", "S1")
    forged = {"stop": "S1", "date": stops.today(), "involvement": "hands-off", "round": None,
              "command": "python3 audits/integrity.py --check", "exit": 1,
              "output": "FAIL[ownership] invented line (0123456789a)",
              "causes": [{"code": "tool-call", "class": "mechanical", "line": "FAIL[ownership] invented"}]}
    write(os.path.join(sd, "STOP.json"), json.dumps(forged))
    keep = stops.run_cmd
    stops.run_cmd = lambda argv: (1, "FAIL[ownership] the real line (fedcba98765)")
    try:
        stops.open_stop(r.cfg, note="anything", cause="tool-call"); got = "opened"
    except stops.Refused as e:
        got = str(e)
    finally:
        stops.run_cmd = keep
    say("R3c N3/A4: an operator-written STOP.json is never committed as found: refused with the recovery",
        "never committed as found" in got and "Recover: rm" in got and not r.g("log", "--format=%s", "--", "P/stops/S1"))
    # a hand-written delegated CLOSED.json of a STOP-class stop: the --delegated refusals are re-applied
    shutil.rmtree(sd)                                                # the printed recovery
    s, _ = stops.open_stop(r.cfg, note="a seal was refused", cause="seal-mismatch")
    write(os.path.join(stops.stop_dir(r.cfg, s), "CLOSED.json"),
          json.dumps({"stop": s, "date": stops.today(), "involvement": "hands-off", "by": "operator", "text": "fine"}))
    try:
        stops.open_stop(r.cfg, note="next", cause="tool-call"); got = "opened"
    except stops.Refused as e:
        got = str(e)
    say("R3c N3: a hand-written delegated close of a STOP-class stop is refused (only the human closes it)",
        "only the human" in got and not r.g("log", "--format=%s", "--", f"P/stops/{s}/CLOSED.json"))
    # ... and --acknowledge never reads an uncommitted stop record
    write(os.path.join(r.rd, "PAPER_DEFECTS.md"), "swept\n")
    r.g("add", "--", "P/PAPER_DEFECTS.md"); r.g("commit", "-qm", "implement x")
    c = r.g("rev-parse", "HEAD")
    sd2 = os.path.join(r.rd, "stops", "S9")
    write(os.path.join(sd2, "STOP.json"), json.dumps(dict(forged, stop="S9", output=f"FAIL[ownership] x ({c[:11]})")))
    write(os.path.join(sd2, "CLOSED.json"), json.dumps({"stop": "S9", "by": "human", "text": "waive"}))
    try:
        integrity.acknowledge(r.d, r.rd, r.cfg, c, "S9"); got = "waived"
    except ValueError as e:
        got = str(e)
    say("R3c N3: --acknowledge refuses a stop whose records are not committed", "not committed" in got)


def t_bundle(base, say):
    """Live L-infinity run (release 5fcd619) stop S1: `signoff.py bundle` printed a PROBLEM and left
    STATEMENTS_BUNDLE.md uncommitted; the round's set-aside swept it in, and integrity reported
    FAIL[ownership] (only a "scope" commit may change it)."""
    import io, contextlib, signoff
    r = Record(base); use(r)
    r.scope(R0, ["correspondence"])
    keep = (signoff.build_bundle, project.select)

    def stub(cfg, table=None):
        stub.missing = ["definition N.S.f: source text not found in lean_files"]
        return "# bundle with a hole\n", [], []
    signoff.build_bundle, project.select = stub, (lambda name=None: (r.cfg, "stub"))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = signoff.main(["bundle", "--round", R0])
    finally:
        signoff.build_bundle, project.select = keep
    bp = os.path.join(r.rd, R0, "STATEMENTS_BUNDLE.md")
    left = os.path.exists(bp)
    try:
        stops.set_aside(r.cfg, R0, "bundle PROBLEM: N.S.f"); aside = True
    except stops.Refused as e:
        aside = str(e)
    r.scope(R1, ["correspondence"])
    say("live S1: a bundle PROBLEM writes no STATEMENTS_BUNDLE.md, so the set-aside that follows commits none and "
        "integrity is clean", rc == 1 and "PROBLEM" in buf.getvalue() and not left and aside is True
        and not r.integrity(R1))
    # a bundle left uncommitted anyway (a kill between write and commit) is refused, never swept in
    r2 = Record(base); use(r2)
    r2.scope(R0, ["correspondence"])
    write(os.path.join(r2.rd, R0, "STATEMENTS_BUNDLE.md"), "# cut short\n")
    try:
        stops.set_aside(r2.cfg, R0, "superseded"); got = "committed"
    except stops.Refused as e:
        got = str(e)
    say("live S1: an uncommitted STATEMENTS_BUNDLE.md is refused by a set-aside, with the recovery (rm it)",
        "never a set-aside" in got and "rm it" in got)


CASES = [t1, t5, t12, t4, t9, t2, t6, t10, t7, t8, t8b, t_ack, t_hash, t3, t_n1, t_r3d, t_r3e, t_r3g, t_r3f, t_n2, t_n3,
         t_bundle]


def selftest():
    res = []

    def say(name, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    base = tempfile.mkdtemp(prefix="round3-")
    saved = (project.REPO, project.AUDITS)
    try:
        for t in CASES:
            t(base, say)
    finally:
        project.REPO, project.AUDITS = saved
        shutil.rmtree(base, ignore_errors=True)
    ok = all(res) and bool(res)
    print("selftest: " + ("ok" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__); sys.exit(2)

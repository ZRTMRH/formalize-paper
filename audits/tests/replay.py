#!/usr/bin/env python3
"""Replays of the four stops of a hands-off test run, on the current design.

WHY THIS EXISTS.  That run stopped four times for a human, each time with intact evidence and a
mechanical cure (CHANGELOG, 0.3.0-dev). The stall resolver was built to clear such stops; the
simplification (RULINGS, round 2) removes their causes instead and deletes the resolver. These
fixtures rebuild each situation in a scratch audit record and assert what the current scripts do
with it, so the cure is a property the suite keeps, not a claim:

  S1  a SEALED lane whose verdict only mentions ADOPTED.md in advice text. Asserts: lanecheck
      prints NOTE[independence] and does not block; the adjudication commit refuses until
      ADOPTED.md clears the NOTE in one line or re-votes the lane; a PATH into another round's
      record forces a re-vote that no clearance satisfies.
  S2  a round superseded before adjudication (a fresh round started instead). Asserts: its sealed
      lanes' files are already committed (commit at seal), so a later integrity check has nothing
      of that round to fail on; `stops.py set-aside` commits whatever is left (an unsealed lane's
      files) with a script-computed inventory, and carries its Fail forward until a later
      adjudication gives it a row.
  S3  a re-vote's probes live under revote/<lane>.probes/. Asserts: lanecheck finds a cited one
      there (no flag) and still flags one that is missing (a lane fault, not "evidence changed").
  S4  an unsettled re-vote. Asserts: a SEALED re-vote's files are committed at its seal (nothing
      for integrity to fail on later), the REVOTE NEEDED row stays listed for the human; an
      UNSEALED one is set aside by `stops.py set-aside R --lane revote/...`.
  SMOKE  a resolver-less hands-off round with two planted faults -- a lane that names ADOPTED.md
      and a re-vote left unsettled -- runs to a clean integrity check with zero stops recorded,
      and both are disclosed (the clearance, the set-aside).

  python3 audits/tests/replay.py --selftest
"""
import os, sys
sys.dont_write_bytecode = True
import json, re, shutil, subprocess, tempfile

AUDITS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AUDITS)
import project, lane_auth, lanecheck, integrity  # noqa: E402


class Record:
    """A scratch audit record: a git repository holding the rounds dir P/, pinned."""

    def __init__(self, base):
        self.d = tempfile.mkdtemp(prefix="replay-", dir=base)
        self.rd = os.path.join(self.d, "P")
        os.makedirs(self.rd)
        self.g("init", "-q"); self.g("config", "user.email", "t@t"); self.g("config", "user.name", "t")
        open(os.path.join(self.d, "x.py"), "w").write("# apparatus\n")
        open(os.path.join(self.d, ".gitignore"), "w").write("__pycache__/\n")
        self.agent = os.path.join(base, "agent-" + os.path.basename(self.d) + ".md")
        open(self.agent, "w").write("auditor\n")
        self.cfg = {"name": "P", "rounds_dir": "P", "lanes": ["correspondence"], "namespace": "N",
                    "involvement": "hands-off", "involvement_answer": "(c)"}
        open(os.path.join(self.rd, "RUN_LOG.md"), "w").write("# Run log\n")
        self.g("add", "--", "x.py", ".gitignore", "P/RUN_LOG.md"); self.g("commit", "-qm", "setup")
        integrity.pin(self.d, self.cfg, agent_file=self.agent, rounds_dir=self.rd)
        self.g("add", "--", "P/" + integrity.PIN); self.g("commit", "-qm", "pin")
        self.tokens = {}

    def g(self, *a):
        return subprocess.run(["git", "-C", self.d, *a], capture_output=True, text=True).stdout.strip()

    def scope(self, rnd, lanes, items=("N.a", "N.b", "N.c", "N.z")):
        r = os.path.join(self.rd, rnd)
        os.makedirs(os.path.join(r, "prompts"), exist_ok=True)
        json.dump({l.split("@")[0]: list(items) for l in lanes}, open(os.path.join(r, "TARGET.json"), "w"))
        self.g("add", "--", f"P/{rnd}/TARGET.json"); self.g("commit", "-qm", f"scope {rnd}")
        return r

    def lane(self, rnd, lane, verdicts, text="", probes=None, seal=True):
        """Issue a lane, write its verdict (and probes, listed in its own manifest), seal it."""
        r = os.path.join(self.rd, rnd)
        v = os.path.join(r, lane + ".json")
        os.makedirs(os.path.dirname(v), exist_ok=True)
        pf = os.path.join(r, "prompts", lane.replace("/", "__") + ".txt")
        open(pf, "w").write(f"Write that JSON object, and nothing else, to {v}\n")
        tok = re.search(r"lane_token is ([0-9a-f]{64})", lane_auth.issue_prompt(pf)).group(1)
        for rel, body in (probes or {}).items():
            p = os.path.join(lane_auth.probes_dir(v), rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(body)
        doc = {"lane_token": tok, "probes": lane_auth.probe_manifest(v), "checked": text,
               "verdicts": [{"item": i, "verdict": x, "next_step": text} for i, x in verdicts]}
        data = json.dumps(doc).encode()
        open(v, "wb").write(data)
        if seal:
            lane_auth.seal(v, lane_auth.sha(data), "agent-" + lane.replace("/", "-"))
        return v

    def flags(self, rnd):
        """lanecheck's flags for a round (the authentication check and each lane's own flags)."""
        r = os.path.join(self.rd, rnd)
        out = lane_auth.check_round(r, lanecheck.lane_files(r))
        for p in lanecheck.lane_files(r):
            out += lanecheck.lane_problems(r, p)
        return out

    def integrity(self, rnd):
        return [m for s, m in integrity.check(self.d, self.cfg, rnd, agent_file=self.agent, rounds_dir=self.rd,
                                              rounds_rel="P", repo=None) if s == "FAIL"]


def selftest():
    res = []

    def say(name, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    base = tempfile.mkdtemp(prefix="replay-base-")
    try:
        # ---- S1: a sealed lane that only MENTIONS ADOPTED.md ---------------------------------------
        r1 = Record(base)
        RA = "2026-10-19-full-1a2b3c40000"
        r1.scope(RA, ["substantiveness@1", "correspondence@1"])
        r1.lane(RA, "substantiveness@1", [("N.a", "Pass")], "next_step: record in ADOPTED.md that h is used")
        r1.lane(RA, "correspondence@1", [("N.a", "Pass")])
        fl = r1.flags(RA)
        say("S1: the mention is NOTE[independence] and blocks nothing (lanecheck exits 0)",
            [lanecheck.flag_code(f) for f in fl] == ["independence"] and not any(lanecheck.counts(f) for f in fl))
        HDR = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
        open(os.path.join(r1.rd, RA, "ADOPTED.md"), "w").write(HDR)
        try:
            integrity.commit_adjudication(r1.d, r1.rd, "P", RA); refused = False
        except ValueError as e:
            refused = "CLEARED substantiveness@1.json" in str(e)
        say("S1: the adjudication commit refuses until ADOPTED.md settles the NOTE", refused)
        open(os.path.join(r1.rd, RA, "ADOPTED.md"), "a").write(
            "\n- CLEARED substantiveness@1.json: advice text naming ADOPTED.md as a place to record; nothing read\n")
        h1, _ = integrity.commit_adjudication(r1.d, r1.rd, "P", RA)
        say("S1: a one-line clearance settles it; the round is adjudicated with no stop and no re-run",
            bool(h1) and not r1.integrity(RA) and lanecheck.clearances(os.path.join(r1.rd, RA))
            == [("substantiveness@1.json", "advice text naming ADOPTED.md as a place to record; nothing read")])
        RB = "2026-10-20-full-2b3c4d50000"
        r1.scope(RB, ["substantiveness@1"])
        r1.lane(RB, "substantiveness@1", [("N.a", "Pass")], f"as audits/P/{RA}/ADOPTED.md records, h is used")
        open(os.path.join(r1.rd, RB, "ADOPTED.md"), "w").write(
            HDR + f"\n- CLEARED substantiveness@1.json: harmless\n")
        say("S1, condition 3: a PATH into another round's record is not settled by a clearance",
            any("forces a whole-lane re-vote" in p for p in lanecheck.settle_problems(os.path.join(r1.rd, RB))))
        open(os.path.join(r1.rd, RB, "ADOPTED.md"), "w").write(
            HDR + "| substantiveness@1 | (whole lane) | - | **REVOTE NEEDED** | independence: it cites another round's record |\n")
        say("S1: ... a whole-lane re-vote settles it", lanecheck.settle_problems(os.path.join(r1.rd, RB)) == [])

        # ---- S2: a round superseded before its adjudication -------------------------------------
        rec = Record(base)
        R0, R1 = "2026-10-19-full-9c8d7e60000", "2026-10-19-full-4a5b6c70000"
        rec.scope(R0, ["correspondence@1", "non-vacuity@1"])
        rec.lane(R0, "correspondence@1", [("N.a", "Fail"), ("N.b", "Pass")], "probe correspondence@1.probes/w.lean",
                 probes={"w.lean": "-- witness"})
        rec.lane(R0, "non-vacuity@1", [("N.a", "Pass")])
        rec.scope(R1, ["correspondence", "substantiveness"], ("N.a", "N.b", "K.isProb", "K.other"))
        rec.lane(R1, "correspondence", [("N.a", "Pass")])
        say("S2: a superseded round's SEALED lanes leave nothing uncommitted (commit at seal): a later "
            "integrity check has nothing of that round to fail on",
            not [m for m in rec.integrity(R1) if R0 in m]
            and all(l.startswith(f"?? P/{R0}/prompts/") for l in
                    rec.g("status", "--porcelain", "--untracked-files=all", "--", f"P/{R0}").splitlines()))

        # ---- S3: a re-vote's probe under revote/ --------------------------------------------------
        rv = rec.lane(R1, "revote/substantiveness--K.isProb", [("K.isProb", "Fail")],
                      "substantiveness--K.isProb.probes/drop_h.lean compiles",
                      probes={"drop_h.lean": "-- dropped h"})
        say("S3: a re-vote's cited probe under revote/<lane>.probes/ is found: no flag",
            not [f for f in rec.flags(R1) if "substantiveness--K.isProb" in f])
        rv2 = rec.lane(R1, "revote/substantiveness--K.other", [("K.other", "Fail")],
                       "substantiveness--K.other.probes/never_written.lean compiles")
        say("S3: ... and a re-vote's probe that does not exist is a lane fault (a NOTE), not a stop",
            [lanecheck.flag_code(f) for f in rec.flags(R1) if "K.other" in f] == ["lane-fault"])
        # ---- S4: an unsettled, SEALED re-vote ----------------------------------------------------
        open(os.path.join(rec.rd, R1, "ADOPTED.md"), "w").write(
            "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            "| substantiveness | K.isProb | Fail | **REVOTE NEEDED** | would reject: h is used |\n"
            "\n- LEFT OPEN revote/substantiveness--K.other.json: its cited probe is missing\n")
        R2 = "2026-10-19-5d6e7f80000"
        rec.g("add", "--", f"P/{R1}/ADOPTED.md"); rec.g("commit", "-qm", f"adjudicate {R1}")
        rec.scope(R2, ["correspondence"])
        import decisions
        say("S4: a sealed re-vote left unsettled has nothing uncommitted for a later integrity check, and "
            "its REVOTE NEEDED row stays listed for the human",
            not [m for m in rec.integrity(R2) if R1 in m] and os.path.exists(rv)
            and [(x[1], x[2]) for x in decisions.open_revotes([os.path.join(rec.rd, R1)])]
            == [("substantiveness", "K.isProb")])

        # ---- S2 and S4 for UNSEALED lanes: stops.py set-aside -------------------------------------
        import stops
        saved = (project.REPO, project.AUDITS)
        try:
            u = Record(base)
            project.REPO = project.AUDITS = u.d
            U0, U1 = "2026-10-19-full-9c8d7e61111", "2026-10-19-full-4a5b6c71111"
            u.scope(U0, ["correspondence@1", "non-vacuity@1"])
            u.lane(U0, "correspondence@1", [("N.a", "Pass")])
            u.lane(U0, "non-vacuity@1", [("N.b", "Fail")], "non-vacuity@1.probes/w.lean", probes={"w.lean": "-- w"},
                   seal=False)
            u.scope(U1, ["correspondence"])
            u.lane(U1, "correspondence", [("N.a", "Pass"), ("N.b", "Pass")])
            say("S2, unsealed: the superseded round's returned, unsealed lane fails integrity while uncommitted",
                any(U0 in m and "non-vacuity@1" in m for m in u.integrity(U1)))
            try:
                stops.set_aside(u.cfg, U0, "superseded by a full round"); ok = False
            except stops.Refused as e:
                ok = "seal it first" in str(e)
            say("S2, unsealed: set-aside refuses while the returned lane is unsealed", ok)
            doc, _ = stops.set_aside(u.cfg, U0, "superseded; the lane's digest was lost", unsealable=["non-vacuity@1"])
            say("S2, unsealed: set-aside --unsealable commits its verdict and probes with an inventory (nothing "
                "deleted), and integrity has nothing of that round left to fail on",
                not [m for m in u.integrity(U1) if U0 in m] and os.path.exists(os.path.join(u.rd, U0, "non-vacuity@1.json"))
                and doc["lanes"]["non-vacuity@1.json"] == "unsealed" and "non-vacuity@1.probes/w.lean" in doc["files"])
            HDR = "| lane | item | verdict | decision | reason |\n|---|---|---|---|---|\n"
            open(os.path.join(u.rd, U1, "ADOPTED.md"), "w").write(HDR + "| correspondence | N.a | Pass | ADOPT | ok |\n")
            try:
                integrity.commit_adjudication(u.d, u.rd, "P", U1); ok = False
            except ValueError as e:
                ok = "N.b (Fail in non-vacuity@1.json, carried forward" in str(e)
            say("S2, unsealed: the carried Fail blocks the next adjudication until it has a row", ok)
            open(os.path.join(u.rd, U1, "ADOPTED.md"), "a").write("| non-vacuity | N.b | Fail | **REVOTE NEEDED** | carried |\n")
            say("S2, unsealed: ... a row settles it", bool(integrity.commit_adjudication(u.d, u.rd, "P", U1)[0]))
            # S4, unsealed: the adjudicated round U1's re-vote lane returned but cannot be sealed
            rv = u.lane(U1, "revote/non-vacuity--N.b", [("N.b", "Fail")], seal=False)
            try:
                stops.set_aside(u.cfg, U1, "x"); ok = False
            except stops.Refused as e:
                ok = "adjudicated" in str(e)
            say("S4, unsealed: an adjudicated round is never set aside as a whole", ok)
            stops.set_aside(u.cfg, U1, "the re-vote's seal commit was killed and its digest lost",
                            lane="revote/non-vacuity--N.b", unsealable=["revote/non-vacuity--N.b"])
            U2 = "2026-10-20-5d6e7f81111"
            u.scope(U2, ["correspondence"])
            say("S4, unsealed: set-aside --lane commits the re-vote's files; a later round's integrity is clean",
                u.integrity(U2) == [] and os.path.exists(rv)
                and f"set-aside {U1} revote/non-vacuity--N.b" in u.g("log", "--format=%s"))

            # ---- SMOKE: a resolver-less hands-off round with two planted faults ------------------
            m = Record(base)
            project.REPO = project.AUDITS = m.d
            M1, M2 = "2026-10-21-full-7a8b9c01111", "2026-10-21-8b9c0d11111"
            m.scope(M1, ["substantiveness", "correspondence"])
            m.lane(M1, "substantiveness", [("N.a", "Pass")], "next_step: record in ADOPTED.md that h is used")
            m.lane(M1, "correspondence", [("N.b", "Fail")])
            open(os.path.join(m.rd, M1, "ADOPTED.md"), "w").write(
                HDR + "| correspondence | N.b | Fail | **REVOTE NEEDED** | the lane may misread h |\n"
                "\n- CLEARED substantiveness.json: advice text naming ADOPTED.md; nothing read\n")
            integrity.commit_adjudication(m.d, m.rd, "P", M1)
            m.lane(M1, "revote/correspondence--N.b", [("N.b", "Fail")], seal=False)     # left unsettled
            stops.set_aside(m.cfg, M1, "the re-vote lane crashed before its completion line",
                            lane="revote/correspondence--N.b", unsealable=["revote/correspondence--N.b"])
            m.scope(M2, ["correspondence"])
            m.lane(M2, "correspondence", [("N.b", "Pass")])
            open(os.path.join(m.rd, M2, "ADOPTED.md"), "w").write(
                HDR + "| correspondence | N.b | Fail | DEFER | carried from the set-aside re-vote: left for the human |\n")
            integrity.commit_adjudication(m.d, m.rd, "P", M2)
            say("SMOKE: hands-off, no resolver: the planted mention and the unsettled re-vote end in a clean "
                "integrity check with zero stops recorded",
                m.integrity(M2) == [] and stops.stop_rows(m.cfg) == [] and stops.carried_problems(m.rd) == [])
            m1 = os.path.join(m.rd, M1)
            say("SMOKE: the set-aside re-vote lane is no longer expected by the round's authentication check",
                lane_auth.check_round(m1, lanecheck.lane_files(m1)) == [])
            say("SMOKE: ... and both are disclosed (the clearance, the set-aside with its inventory)",
                lanecheck.clearances(os.path.join(m.rd, M1)) != []
                and [r["carried"][0]["item"] for r in stops.set_aside_rows(m.cfg)] == ["N.b"])
        finally:
            project.REPO, project.AUDITS = saved
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)

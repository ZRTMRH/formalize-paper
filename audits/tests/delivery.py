#!/usr/bin/env python3
"""The delivery flow end to end on a fixture project (B10; U2 §6, ADDENDUM N1, N2, N6). Maintainers' test.

WHY THIS EXISTS.  The delivery used to loop: a stop closed at delivery (mini4/mini5 S1) or a reader's own
disclosure made a delivered document stale, the document was regenerated, read again, and so on (U2 §6.6,
M2). B10 splits it into `project.py --prepare-delivery` (the only generator) and a `--deliver` that only
checks. This test drives the real generator, the real reader gate and the real stop record through:

  1. SCENARIO, in every run mode x involvement level: prepare, the readers pass, then a stop opens and is
     closed AFTER the summary's pass. --deliver refuses with a delivery precondition (never a stop: stops.py
     open refuses it), one more prepare and one pass per regenerated document clear it, and --deliver
     delivers. No spent cure budget, no cure charged, exactly two prepares.
  2. N2 BEHAVIOUR: what the generator writes (SUMMARY.md, REPORT.md minus its date, README A-C) is
     byte-identical after (a) a reader record is committed, (b) an older run's delivery-code stop is opened,
     cured and closed, (c) a reader disclosure (a D record of code reader, its RUN_LOG line), (d) a commit
     of a non-Lean file moves the Lean repository's HEAD. A real input change (a closed run stop) does
     change it (control).
  3. GEN_INPUTS is disjoint from READER_OUTPUTS and DELIVER_OUTPUTS (the path check, kept as an extra).

  python3 audits/tests/delivery.py --selftest
"""
import os, sys
sys.dont_write_bytecode = True
import contextlib, io, json, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS_SRC = os.path.dirname(HERE)
sys.path.insert(0, AUDITS_SRC)
import project  # noqa: E402

LEAN = ("/-!\n| Paper | Lean |\n|---|---|\n| Theorem 1.1 | `thm_1_1` |\n| Lemma 1.2 | `lemma_1_2` |\n-/\n"
        "theorem thm_1_1 : True := trivial\ntheorem lemma_1_2 : 1 = 1 := rfl\n")


def status_of(sm, label):
    """The status the one-page summary's results table gives `label` ("" when it is not in the table)."""
    import make_report
    return make_report._table_rows_of(sm)[0].get(label, "")


def with_status(sm, label, status):
    """`sm` with `label` moved out of its row into a row of its own with `status` (a forged table)."""
    out = []
    for l in sm.splitlines():
        if l.startswith("| ") and not l.startswith("| Status |"):
            c = [x.strip() for x in l.strip().strip("|").split(" | ")]
            lbls = [x for x in c[1].split("; ") if x != label]
            if len(lbls) != len(c[1].split("; ")):
                out.append(f"| {status} | {label} |")
                if lbls:
                    out.append(f"| {c[0]} | {'; '.join(lbls)} |")
                continue
        out.append(l)
    return "\n".join(out) + "\n"


def g(repo, *a):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r.stdout.strip()


def gi(repo):
    g(repo, "init", "-q")
    g(repo, "config", "user.email", "t@t")
    g(repo, "config", "user.name", "t")


class Fixture:
    """A project: the Lean repository (project.REPO) with audits/ as the audit record's own repository
    (project.AUDITS), a statement round R0 approved, a full round R1 after it, a DECISIONS.md and the sheet."""

    def __init__(self, base, mode, level, tag="s", lean=LEAN, verdicts=True):
        import make_report, render_record, stops
        self.repo = os.path.join(base, f"{tag}-{mode}-{level}")
        self.aud = os.path.join(self.repo, "audits")
        os.makedirs(os.path.join(self.repo, "P"))
        os.makedirs(self.aud)
        gi(self.repo)
        open(os.path.join(self.repo, ".git", "info", "exclude"), "a").write("audits/\n")
        open(os.path.join(self.repo, "P", "Main.lean"), "w").write(lean)
        g(self.repo, "add", "-A"); g(self.repo, "commit", "-qm", "statements")
        h0 = g(self.repo, "rev-parse", "HEAD")
        open(os.path.join(self.repo, "P", "Main.lean"), "a").write("-- proofs\n")
        g(self.repo, "add", "-A"); g(self.repo, "commit", "-qm", "proofs")
        h1 = g(self.repo, "rev-parse", "HEAD")
        self.r0, self.r1 = f"2026-01-01-{h0[:11]}", f"2026-01-02-full-{h1[:11]}"
        self.cfg = {"name": "t", "source_cite": "A. Author, A paper (fixture)", "source_pdf": "paper.tex",
                    "branch": "b", "namespace": "P", "rounds_dir": "audits/R", "lean_files": ["P/Main.lean"],
                    "index_file": "P/Main.lean", "mode": mode, "involvement": level,
                    "involvement_answer": f"({level})" if level != "involved" else None}
        rd = self.rd = os.path.join(self.aud, "R")
        for r, kind in ((self.r0, "statements"), (self.r1, "full")):
            os.makedirs(os.path.join(rd, r))
            json.dump({"_meta": {"kind": kind}}, open(os.path.join(rd, r, "TARGET.json"), "w"))
            open(os.path.join(rd, r, "ADOPTED.md"), "w").write(
                "# Adjudication\n\nNo lane failed; nothing to adopt.\n")
        # B9 (result_status): the full round's verdicts, every one Pass, on the current fingerprints, and the
        # assumption walk (nothing assumed), so every result can read "faithful" (verdicts=False: none at all)
        import re as _re
        decls = ["P." + n for n in _re.findall(r"^theorem (\S+)", lean, _re.M)]
        labels = _re.findall(r"^\| ((?:Theorem|Lemma) [^|]*?) \|", lean, _re.M)
        fps = {d: "fp-" + d for d in decls}
        for r in (self.r0, self.r1):
            json.dump({"commit": h1, "fingerprints": fps, "deps": {d: [] for d in decls}},
                      open(os.path.join(rd, r, "FINGERPRINTS.json"), "w"))
        if verdicts:
            for lane, items in (("correspondence", decls), ("non-vacuity", decls), ("paper-faithfulness", labels)):
                json.dump({"lane": lane, "scope": items, "verdicts": [{"item": i, "verdict": "Pass", "checked": "x"}
                                                                       for i in items]},
                          open(os.path.join(rd, self.r1, lane + ".json"), "w"))
        json.dump({"commit": h1, "roots": decls, "assumes": {d: [] for d in decls}, "walked": decls,
                   "results": decls, "axioms": {}}, open(os.path.join(rd, "DEPENDENCIES.json"), "w"))
        open(os.path.join(rd, self.r0, "SIGNOFF.md"), "w").write("sheet SIGNOFF.md\n")
        json.dump({"round": self.r0, "commit": h0, "date": "2026-01-01", "how": "blanket",
                   "by": "agent" if level == "hands-off" else "human",
                   "rows": {"Theorem 1.1": {"decls": ["P.thm_1_1"], "status": "approved"},
                            "Lemma 1.2": {"decls": ["P.lemma_1_2"], "status": "approved"}},
                   "fingerprints": {}}, open(os.path.join(rd, "APPROVED_FINGERPRINTS.json"), "w"))
        log = "# Run log\n## Intake\n- 5c: " + level + "\n"
        if level != "involved":
            log += ("## Checkpoint C\n- check:x: [DELEGATED 2026-01-03, operator under " + level
                    + " (intake); reversal: none] keep it — fixture\n")
        open(os.path.join(rd, "RUN_LOG.md"), "w").write(log)
        import decisions
        open(os.path.join(rd, "DECISIONS.md"), "w").write(
            f"<!-- decisions-round: {self.r1} -->\n# Decisions\n\n{decisions.BOX_START}\n> - none yet\n\nprose\n")
        gi(self.aud)
        g(self.aud, "add", "-A", "--", ".", ":!R/APPROVED_FINGERPRINTS.json"); g(self.aud, "commit", "-qm", "records")
        g(self.aud, "add", "-A"); g(self.aud, "commit", "-qm", f"approve {self.r0}")
        # the stand-ins: the delivery gate's subprocess checks pass (stops.RUNNER), the report is built in-process;
        # the PDFs are rendered by simulated agents through the real render_record.py (render_all, at each deliver);
        # the hands-off sheet's audit gate (signoff.py check, Lean-backed) stands in as passing
        self.saved = (project.REPO, project.AUDITS, make_report.REPO, stops.RUNNER, stops.PHASE0_LINES,
                      render_record.AUDIT_GATE, project.REGENERATE_REPORT)
        project.REPO, project.AUDITS, make_report.REPO = self.repo, self.aud, self.repo
        gate0 = render_record.AUDIT_GATE
        render_record.AUDIT_GATE = lambda c_, d_, r_: ([] if d_ == "SIGNOFF" and project.involvement(c_) == "hands-off"
                                                       else gate0(c_, d_, r_))
        self.render = True
        self.runs = []
        self.failing = set()
        stops.RUNNER = lambda argv: (self.runs.append(" ".join(argv)),
                                     (1, "FAIL[tool-call] x\n") if any(f in " ".join(argv) for f in self.failing)
                                     else (0, "ok\n"))[1]
        stops.PHASE0_LINES = lambda c_: []
        self.prepares = 0

        def regen(c_):
            o = io.StringIO()
            with contextlib.redirect_stdout(o):
                rc = make_report.build(c_)
            self.last_build = o.getvalue()
            return rc, ["ok"]
        project.REGENERATE_REPORT = regen

    def close(self):
        import make_report, render_record, stops
        (project.REPO, project.AUDITS, make_report.REPO, stops.RUNNER, stops.PHASE0_LINES,
         render_record.AUDIT_GATE, project.REGENERATE_REPORT) = self.saved

    def prepare(self):
        self.prepares += 1
        with contextlib.redirect_stdout(io.StringIO()):
            return project.prepare_delivery(self.cfg)

    def render_all(self):
        """The rendering agents, simulated through the real render_record.py: for each document whose md is audited
        at its current hash (begin refuses the others), A saves a PDF, B passes it, both checkers say SAME, finish.
        Returns {key: outcome}."""
        import render_record as rr
        docs = [("SUMMARY", None), ("REPORT", None)] + (
            [("SIGNOFF", project.approved_round(self.cfg))] if project.approved_round(self.cfg) else [])
        out = {}
        wd = os.path.join(self.repo, ".formalization-work", "agents")
        os.makedirs(wd, exist_ok=True)
        for d, r in docs:
            key = rr.resolve(self.cfg, d, r)[2]
            for _ in range(12):
                rec = rr.load(self.cfg, key)
                st = rr.step(rec, rr.md_sha(self.cfg, d, r))
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        if st[0] in rr.ROLE_PROMPT:     # the operator issues the step's prompt (prompt.py --write)
                            for n in (st[1] if st[0] == "checker" else [None]):
                                rr.write_prompt(self.cfg, d, r, rr.ROLE_PROMPT[st[0]], f"simulated {st[0]} prompt", n)
                        if st[0] == "begin":
                            rr.begin(self.cfg, d, r)
                        elif st[0] == "A":
                            pdf = os.path.join(wd, f"{key}-{rec['version']}-{st[1]}.pdf")
                            open(pdf, "wb").write(b"%PDF-1.5 " + rr.md_sha(self.cfg, d, r).encode())
                            rr.save(self.cfg, d, r, "A", "RENDER_DONE " + json.dumps(
                                {"pdf": pdf, "sha256": rr.sha_file(pdf), "engine": "simulated"}))
                        elif st[0] in ("B", "checker"):
                            rec_ = rr.load(self.cfg, key)
                            last = rec_["rounds"][-1]
                            body = (f"md_sha256: {rec_['md_sha256']}\npdf_sha256: {last['a']['pdf_sha256']}\n"
                                    "pages: read 1 of 1\n")
                            if st[0] == "B":
                                rr.save(self.cfg, d, r, "B", body + "VERDICT: PASS\n")
                            else:
                                for n in st[1]:
                                    rr.save(self.cfg, d, r, "checker", body + "VERDICT: SAME\n", n)
                        elif st[0] == "finish":
                            rr.finish(self.cfg, d, r)
                        else:
                            break
                except rr.Refused:
                    break
            out[key] = (rr.load(self.cfg, key) or {}).get("outcome")
        return out

    def write_docs(self, tag="AGENTQZ"):
        """The main agent writes SUMMARY.md and REPORT.md from the facts draft and the records (approver
        2026-10-28), and JUDGEMENT.md; committed by name."""
        for n in ("SUMMARY.md", "REPORT.md"):
            src = os.path.join(self.rd, project.FACTS_DIR, n)
            body = open(src).read() if os.path.exists(src) else f"# {n}\n"
            open(os.path.join(self.rd, n), "w").write(f"<!-- written by the main agent: {tag} -->\n" + body)
        open(os.path.join(self.rd, project.JUDGEMENT_MD), "w").write("claims-1 · adopted. fixture\n")
        g(self.aud, "add", "--", "R/SUMMARY.md", "R/REPORT.md", "R/" + project.JUDGEMENT_MD)
        g(self.aud, "commit", "-qm", "deliverables: write")

    def deliver(self):
        if self.render:
            self.rendered = self.render_all()
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            rc = project.deliver(self.cfg)
        return rc, o.getvalue()

    def read(self, doc, rnd=None):
        """A fresh reader's clean pass on the current version, saved and committed as readers.py --save does."""
        import readers
        key, srcs, _ = readers.resolve(self.cfg, doc, rnd)
        text = f"sha256: {readers.content_hash(srcs, doc)}\ncoverage: all\nVERDICT: NO BLOCKING PROBLEMS\n"
        path, probs = readers.save(self.cfg, doc, rnd, text)
        if probs:
            raise RuntimeError(f"reader {doc}: {probs}")
        return path

    def read_all(self, docs=None):
        docs = docs or ["summary", "report", "decisions"] + (
            [] if self.cfg["involvement"] == "hands-off" else ["signoff"])
        for d in docs:
            self.read(d, "approved" if d == "signoff" else None)

    def outputs(self):
        """What the generator writes now, from the inputs (in memory): {name: text}."""
        import make_report
        rep = make_report.report_md(self.cfg)
        return {"SUMMARY.md": make_report.summary_md(self.cfg),
                "REPORT.md": project.doc_text_hash("REPORT.md", rep) if rep else None,
                project.README_AC: project.readme_ac(self.cfg)}


def scenario(base, mode, level):
    """(ok, why) of one run mode x level (approver 2026-10-28, binding): after the mathematics is verified, delivery
    never stops and is never refused except by the math gate. A project with a stale facts draft (a record changed
    after prepare), an open stop (dev: PENDING[stop], a wait; release, not a human stop: a note), an unanswered
    fresh-reader finding, a hand-edit record the status check judged
    MISMATCH, and a result_status disagreement (the walk missing: status-unmapped) delivers, each printed as a note
    for the main agent, and no stop opens on any of them; the agent's own SUMMARY and REPORT are delivered. A Lean
    commit after the last audited round (RED[deliver-stale]) or a `sorry` no record discloses (Phase 0 RED: a stand-in
    for phase0.py --readonly, whose own selftest holds its sorry scan) is refused, and nothing is copied."""
    import readers, stops
    f = Fixture(base, mode, level)
    try:
        rc, lines = f.prepare()
        if rc:
            return False, f"first prepare exit {rc}: {lines} {f.last_build[-900:]}"
        f.write_docs()
        if level != "hands-off":
            f.read("signoff", "approved")       # the approved sheet keeps its reader (Stage 2)
        def answer_c():     # under involved the human answers every item Checkpoint C asks (a designed wait)
            if level == "involved":
                import decisions
                for a_ in decisions.checkpoint_c_open(f.cfg):
                    project.log_append(f.cfg, "Answered", f"- answered {a_} (2026-01-03, {f.r1}): yes, keep it")
                g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "run log: Checkpoint C answered", "--allow-empty")
        answer_c()
        # the refusals first (nothing is copied): a Lean commit after the last audited round, an undisclosed sorry
        open(os.path.join(f.repo, "P", "Main.lean"), "a").write("theorem later : True := trivial\n")
        g(f.repo, "add", "-A"); g(f.repo, "commit", "-qm", "a Lean change after the last round")
        answer_c()
        rc_st, out_st = f.deliver()
        g(f.repo, "reset", "-q", "--hard", "HEAD~1")
        keep_r = stops.RUNNER
        stops.RUNNER = lambda argv: ((1, "HARD[sorry] sorry: P/Main.lean:9: sorry\nPHASE 0: RED (1 check(s))\n")
                                     if "phase0.py" in " ".join(argv) else (0, "ok\n"))
        rc_so, out_so = f.deliver()
        stops.RUNNER = keep_r
        refused_ok = (rc_st == 1 and "RED[deliver-stale] not deliverable (the math gate)" in out_st
                      and rc_so == 1 and "RED[deliver] not deliverable (the math gate)" in out_so
                      and "HARD[sorry]" in out_so and not os.path.isdir(os.path.join(f.repo, "deliverables")))
        # the non-blocking faults
        vp = os.path.join(f.rd, "VACUOUS.md")       # a record changed after prepare: the facts draft is stale
        open(vp, "w").write("| # | statement | for which parameters | why | decision | status |\n|---|---|---|---|---|---|\n"
                            "| 1 | `lemma_1_2` | all | never holds | keep | open |\n")
        f.failing = {"integrity.py"}
        s_, _m = stops.open_stop(f.cfg, note="a tool call failed after the documents", cause="tool-call",
                                 check="python3 audits/integrity.py --check")     # left open
        f.failing = set()
        key, srcs, _ = readers.resolve(f.cfg, "summary", None)  # a reader's blocking finding, never answered
        readers.save(f.cfg, "summary", None, f"sha256: {readers.content_hash(srcs, 'summary')}\ncoverage: all\n"
                     "- BLOCKING: [presentation] UNANSWEREDQZ\nVERDICT: BLOCKING PROBLEMS: 1\n")
        he = os.path.join(f.rd, "hand-edits")        # an older-style hand edit the status check judged MISMATCH
        os.makedirs(he, exist_ok=True)
        json.dump({"he": "HE1", "doc": "SUMMARY.md", "finding": "x"}, open(os.path.join(he, "HE1.json"), "w"))
        os.makedirs(os.path.join(f.rd, "status-check"), exist_ok=True)
        open(os.path.join(f.rd, "status-check", "FINDINGS.md"), "w").write("## Hand edits\n\n- HE1: MISMATCH x\n")
        dep = os.path.join(f.rd, "DEPENDENCIES.json")   # result_status cannot route the results (dev: a note)
        dep_keep = open(dep).read()
        os.remove(dep)
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "fixture: faults after the documents")
        answer_c()
        # review 2026-10-28: an open stop waits for the human in dev (PENDING[stop]); in release a stop that is no
        # human stop (here tool-call, a rerun) is a note
        rc_open, out_open = f.deliver()
        if mode == "release":
            wait_ok = rc_open == 0 and f"stop {s_} is open (not a human stop)" in out_open
            rc1, out1 = rc_open, out_open
            stops.close_stop(f.cfg, s_, cured="re-ran the tool")
        else:
            wait_ok = (rc_open == 1 and out_open.startswith("PENDING[stop]")
                       and not os.path.isdir(os.path.join(f.repo, "deliverables")))
            stops.close_stop(f.cfg, s_, human="go on")
            rc1, out1 = f.deliver()
        open(dep, "w").write(dep_keep)
        n_stops = [x for x in stops.stops(f.cfg) if x != s_]
        try:
            stops.open_stop(f.cfg, note="the delivery noted things", cause="deliver")
            stop_refused = False
        except stops.Refused as e:
            stop_refused = "never a stop" in str(e)
        dv = os.path.join(f.repo, "deliverables")
        got = sorted(os.listdir(dv)) if os.path.isdir(dv) else []
        readme = open(os.path.join(dv, "README.md")).read() if "README.md" in got else ""
        sm = open(os.path.join(dv, "SUMMARY.md")).read() if "SUMMARY.md" in got else ""
        ok = (refused_ok and rc1 == 0 and project.NOTES_HEADING in out1
              and not stops.FAIL_LINE.search(out1) and "PENDING[" not in out1
              and "SUMMARY.md is stale" in out1 and wait_ok
              and (mode == "release" or "note: [status-unmapped]" in out1)
              and not n_stops and stop_refused
              and "AGENTQZ" in sm and project.JUDGEMENT_MD in got
              and {"SUMMARY.pdf", "SUMMARY.md", "REPORT.pdf", "REPORT.md", "DECISIONS.md", "SIGNOFF.pdf",
                   "SIGNOFF.md", "README.md", "RUN_RECORD.md"} <= set(got)
              and all(v == "verified" for v in f.rendered.values()) and len(f.rendered) == 3
              and "written by the formalizing agent" in readme and "## D. Delivery notes" in readme)
        why = (f"stale={rc_st} {out_st[:200]!r}; sorry={rc_so} {out_so[:200]!r}; open={rc_open} {out_open[:200]!r}; "
               f"deliver={rc1} {out1[:900]!r}; "
               f"stops={stops.stops(f.cfg)} refused={stop_refused}; got={got}")
        return ok, why
    except Exception as e:      # noqa: BLE001 -- a crash fails the case, with its reason
        import traceback
        return False, f"crashed: {e!r} {traceback.format_exc()[-600:]}"
    finally:
        f.close()


def behaviour(base):
    """[(name, ok)] of the N2 behavioural selftest (U2 §6.6, ADDENDUM N2)."""
    import stops
    out = []
    f = Fixture(base, "release", "hands-off", tag="n2")
    try:
        f.prepare()
        h0 = f.outputs()
        # (a) a reader record committed
        f.read("summary")
        out.append(("N2 (a): a committed reader record changes nothing the generator writes", f.outputs() == h0))
        # (b) an older run's delivery-code stop (B10 refuses new ones) opened, a cure attempt, closed
        sd = os.path.join(f.rd, "stops", "S1")
        os.makedirs(sd)
        json.dump({"date": "2026-01-04", "command": None, "note": "deliver refused", "mode": "release",
                   "causes": [{"code": "deliver", "class": "document", "line": "(operator's note)"}]},
                  open(os.path.join(sd, "STOP.json"), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "stop S1 open")
        json.dump({"attempt": 1, "rerun": {"passes": False}}, open(os.path.join(sd, "CURE1.json"), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "stop S1 cure 1")
        json.dump({"by": "human", "text": "go on"}, open(os.path.join(sd, "CLOSED.json"), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "stop S1 close")
        project.log_append(f.cfg, "Stops", "- stop S1 closed by human: go on")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "run log: S1")
        out.append(("N2 (b): a delivery-phase stop (delivery codes only) opened, cured and closed changes nothing the "
                    "generator writes (README D lists it)",
                    f.outputs() == h0 and [r["stop"] for r in stops.stop_rows(f.cfg, phase="delivery")] == ["S1"]))
        # (c) a reader disclosure: a D record of code reader and its RUN_LOG line
        dd = os.path.join(f.rd, "stops", "disclosed")
        os.makedirs(dd)
        json.dump({"fault": "D1", "date": "2026-01-04", "mode": "release",
                   "command": "python3 audits/readers.py --doc report --check",
                   "faults": [{"code": "reader", "line": "the document changed after its last well-formed pass"}]},
                  open(os.path.join(dd, "D1.json"), "w"))
        project.log_append(f.cfg, "Stops", "- D1 (2026-01-04, release mode: disclosed, not a stop) reader")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "stop disclose D1")
        out.append(("N2 (c): a reader disclosure (its D record and RUN_LOG line) changes nothing the generator writes",
                    f.outputs() == h0))
        # (d) HEAD of the Lean repository moves by a commit of no Lean file
        open(os.path.join(f.repo, "NOTES.txt"), "w").write("x\n")
        g(f.repo, "add", "NOTES.txt"); g(f.repo, "commit", "-qm", "notes")
        out.append(("N2 (d): the generated documents cite the last Lean commit, never HEAD: a commit of another "
                    "file changes nothing", f.outputs() == h0))
        # control: a run stop (not a delivery code) closed is an input: the summary changes
        sd2 = os.path.join(f.rd, "stops", "S2")
        os.makedirs(sd2)
        json.dump({"date": "2026-01-05", "command": None, "note": "a tool call failed", "mode": "release",
                   "causes": [{"code": "tool-call", "class": "mechanical", "line": "(operator's note)"}]},
                  open(os.path.join(sd2, "STOP.json"), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "stop S2 open")
        out.append(("N2 control: a run stop is an input (G6): the summary lists it, so the generator's output changes",
                    f.outputs()["SUMMARY.md"] != h0["SUMMARY.md"] and "- stop S2 — " in f.outputs()["SUMMARY.md"]))
    finally:
        f.close()
    return out


def preconditions(base):
    """[(name, ok)]: each delivery precondition of make_report.py --check --delivery on the fixture."""
    import make_report
    out = []
    f = Fixture(base, "release", "involved", tag="pre")
    try:
        f.prepare()
        dp = lambda: make_report.delivery_problems(f.cfg)
        p0 = dp()
        out.append(("approver 2026-10-28: the summary, the report and the decisions document have no reader gate (the "
                    "delivery reviewers advise); the approved sheet's stays (not hands-off), a note of --deliver",
                    any("reader gate signoff" in t for c, t in p0)
                    and not any(f"reader gate {d_}" in t for c, t in p0 for d_ in ("summary", "report", "decisions"))
                    and {c for c, t in p0} == {"deliver"}))
        f.read_all()
        out.append(("the prepared, read fixture passes make_report.py --check --delivery", dp() == []))
        sp = os.path.join(f.rd, "SUMMARY.md")
        keep = open(sp).read()
        open(sp, "w").write(keep.replace("Lemma 1.2 |", "Lemma 1.2 (edited) |").replace("Lemma 1.2;", "Lemma 1.2 (edited);"))
        p1 = dp()
        open(sp, "w").write(keep)
        out.append(("approver 2026-10-28: the main agent's summary may differ from the facts draft (never 'changed after "
                    "prepare'); the coverage check, a note, still names a result it lost",
                    not any("changed after prepare" in t for c, t in p1)
                    and any("results table has result Lemma 1.2 0 time(s)" in t for c, t in p1)))
        cut = "\n".join(l.replace("Theorem 1.1; ", "").replace("; Theorem 1.1 |", " |") for l in keep.splitlines()) + "\n"
        out.append(("coverage: a summary missing one result is RED (summary_problems), with the count",
                    any("results table has result Theorem 1.1 0 time(s)" in str(x)
                        for x in make_report.summary_problems(f.cfg, cut))))
        open(os.path.join(f.repo, "P", "Main.lean"), "a").write("-- a later proof change\ntheorem extra : True := trivial\n")
        g(f.repo, "add", "-A"); g(f.repo, "commit", "-qm", "later")
        p3 = dp()
        out.append(("deliver-stale: a Lean commit after the last audited round is RED[deliver-stale] (and the prepared "
                    "documents name another Lean commit: RED[deliver])",
                    any(c == "deliver-stale" for c, t in p3) and any("the Lean changed since prepare" in t for c, t in p3)))
        import scope
        nxt = scope.empty_scope_next(f.cfg)
        g(f.repo, "reset", "-q", "--hard", "HEAD~1")
        out.append(("mini5 loop: an empty diff scope (scope.py exit 3) while a Lean commit is unaudited routes to a full "
                    "round (NEXT[full-round], prompt.py 3 --full), never to Stage 5; and the deliver-stale line names the "
                    "full round; with nothing after the last round: Stage 5",
                    nxt[0] == "full" and "prompt.py 3 --full" in nxt[1] and nxt[1].startswith("NEXT[full-round]")
                    and any(c == "deliver-stale" and "prompt.py 3 --full" in t for c, t in p3)
                    and scope.empty_scope_next(f.cfg)[0] == "stage5"))
        os.rename(os.path.join(f.rd, f.r1), os.path.join(f.rd, "aside"))
        p4 = [c for c, t in dp() if c == "unverified"]
        os.rename(os.path.join(f.rd, "aside"), os.path.join(f.rd, f.r1))
        out.append(("unverified: no full-scope round after the approved round is RED[unverified] (until B9's per-result "
                    "rule)", bool(p4) and make_report.unverified_problems(f.cfg) == []))
        import decisions, stops
        k_ = (decisions.pending_unproved, make_report.adjudication_findings)
        try:
            decisions.pending_unproved = lambda c_: ["P.lemma_1_2"]
            make_report.adjudication_findings = lambda c_, r_=None: [project.Finding(
                "! SKIPPED.md row 3: 4 cells under a 5-column header", "adj-record")]
            p5 = dp()
        finally:
            decisions.pending_unproved, make_report.adjudication_findings = k_
        out.append(("nothing pending: a result left unproved awaiting its adjudication, or an adjudicator-owned record "
                    "fault, is RED[adj-record] (pending the next adjudication)",
                    any(c == "adj-record" and "P.lemma_1_2" in t for c, t in p5)
                    and any(c == "adj-record" and "SKIPPED.md row 3" in t for c, t in p5)))
        rm = project.readme_ac(f.cfg)
        out.append(("README A-C names the summary first, then A REPORT, B DECISIONS, C the sheet of the latest approval "
                    "(its round and commit), and never HEAD or a reader's outcome",
                    rm.index("SUMMARY.pdf") < rm.index("## A. The report") < rm.index("## B. DECISIONS.md")
                    < rm.index("## C. The sign-off sheet") and f.r0 in rm and "## D." not in rm and "passed" not in rm
                    and project.delivered_commit(f.cfg) in rm))
        # trial #11 audit: README C said the sheet shows "the proofs as they stood then and line numbers of that
        # commit" (the approval's); it shows statements only, with the lines of the commit it was written for
        sp_ = os.path.join(f.rd, f.r0, "SIGNOFF.md")
        had_ = open(sp_).read() if os.path.exists(sp_) else None
        appr_c = str(json.load(open(os.path.join(f.rd, "APPROVED_FINGERPRINTS.json"))).get("commit"))[:11]
        os.makedirs(os.path.dirname(sp_), exist_ok=True)
        open(sp_, "w").write("# Statement sign-off — x\n\nCommit `fedcba98765`. 1 results\n")
        rm_s = project.readme_ac(f.cfg)
        os.remove(sp_)
        rm_n = project.readme_ac(f.cfg)
        if had_ is not None:
            open(sp_, "w").write(had_)
        out.append(("trial #11: README C says the sheet shows the statements, not the proofs, with the line numbers of "
                    "the commit the sheet names (and the approval commit beside it when they differ)",
                    "the proofs as they stood then" not in rm_s + rm_n and "not the proofs" in rm_s
                    and f"at commit `fedcba98765`, the commit the sheet was written for (the statements were approved "
                        f"at commit `{appr_c}`)" in rm_s
                    and f"at commit `{appr_c}`, the approval commit" in rm_n))
        # a closed run stop the prepared documents do not name
        sd = os.path.join(f.rd, "stops", "S1")
        os.makedirs(sd)
        json.dump({"date": "2026-01-06", "note": "x", "command": None,
                   "causes": [{"code": "tool-call", "class": "mechanical", "line": "(operator's note)"}]},
                  open(os.path.join(sd, "STOP.json"), "w"))
        json.dump({"by": "human", "text": "go on"}, open(os.path.join(sd, "CLOSED.json"), "w"))
        p6 = dp()
        shutil.rmtree(os.path.join(f.rd, "stops"))
        out.append(("a stop closed after prepare (by the human, not a self-cure) must be named by REPORT.md and "
                    "DECISIONS.md: RED[deliver] until prepare runs again",
                    any("REPORT.md does not name S1" in t for c, t in p6)
                    and any("DECISIONS.md does not name S1" in t for c, t in p6)))
        # an input changed after prepare (a record, not a stop): the generator writes something else now
        vp = os.path.join(f.rd, "VACUOUS.md")
        open(vp, "w").write("| # | statement | for which parameters | why | decision | status |\n|---|---|---|---|---|---|\n"
                            "| 1 | `lemma_1_2` | all | never holds | keep | open |\n")
        p7 = dp()
        sm7 = make_report.summary_md(f.cfg)
        os.remove(vp)
        out.append(("the summary lists a vacuous row and the result it concerns reads vacuous (a fact, not the "
                    "shared enumerator)",
                    "- vacuous 1 — `lemma_1_2` is true only vacuously" in sm7 and status_of(sm7, "Lemma 1.2") == "true only vacuously"))
        out.append(("a record changed after prepare makes the prepared summary and report stale: RED[deliver] (recomputed "
                    "in memory, U2 §6.4)",
                    any("SUMMARY.md is stale" in t for c, t in p7) and any("REPORT.md is stale" in t for c, t in p7)))
        # the §1 independent check: a result a record names never reads plain
        pd = os.path.join(f.rd, "PAPER_DEFECTS.md")
        open(pd, "w").write("## Defects\n| # | where | status | repair | what the paper says | why it is wrong | "
                            "Lean witness | consequence |\n|---|---|---|---|---|---|---|---|\n| 1 | Theorem 1.1, tex l.3 | "
                            "false | substantial | x | y | none: argument | z |\n")
        good = make_report.summary_md(f.cfg)
        bad = with_status(good, "Theorem 1.1", "faithful")
        ind = [str(x) for x in make_report.summary_problems(f.cfg, bad)]
        os.remove(pd)
        out.append(("U2 §1 independent check: a result a defect row names, shown as plain, is RED (from the raw "
                    "records, not the summary's own inputs); the generated line itself is not plain",
                    any("Theorem 1.1 reads plain" in x for x in ind) and "- defect 1 — Theorem 1.1, tex l.3: false; "
                    "substantial" in good and status_of(good, "Theorem 1.1") != "faithful"))
        h = make_report.summary_inputs(f.cfg)
        row = [r for r in h["index"] if r[0].startswith("Theorem")][0]
        out.append(("B9 plugged in: a result whose every review is Pass and current reads exactly 'faithful' "
                    "(result_status.py), and the summary says so", make_report.result_status(f.cfg, row, h) == ["faithful"]
                    and status_of(make_report.summary_md(f.cfg), "Theorem 1.1") == "faithful"))
        os.makedirs(os.path.join(f.rd, "waivers"))
        json.dump({"commit": "abc1234def0", "subject": "fix records", "files": ["SKIPPED.md"], "stop": "S1",
                   "answer": "keep it"}, open(os.path.join(f.rd, "waivers", "W1.json"), "w"))
        smw = make_report.summary_md(f.cfg)
        shutil.rmtree(os.path.join(f.rd, "waivers"))
        import fnmatch as _fn
        out.append(("the summary lists every waiver of an ownership FAIL (stops-and-set-asides.md), and GEN_INPUTS names "
                    "the waivers and escalation records the generator reads",
                    "- waiver Record ownership — 1 commit(s) WAIVED by the human: abc1234def0" in smw
                    and all(any(_fn.fnmatch(p_, g_) for g_ in project.GEN_INPUTS)
                            for p_ in ("escalations/E1.prompt.txt", "escalations/E1.answer.md", "waivers/W1.json"))))
        out.append(("the summary prints the status legend (what 'faithful' means) under its results",
                    make_report.SUMMARY_LEGEND in make_report.summary_md(f.cfg)))
    finally:
        f.close()
    return out


PARTS = LEAN.replace("| Lemma 1.2 | `lemma_1_2` |\n", "| Lemma 1.2 | `lemma_1_2` |\n| Lemma 1.3 (a) | `lemma_1_3_a` |\n"
                     "| Lemma 1.3 (c) | `lemma_1_3_c` |\n") + "theorem lemma_1_3_a : True := trivial\ntheorem lemma_1_3_c : True := trivial\n"


def b9_plug(base):
    """[(name, ok)]: B9's result_status in the summary and the delivery check (integration of B9 and B10)."""
    import make_report
    out = []
    f = Fixture(base, "release", "hands-off", tag="b9", lean=PARTS)
    try:
        open(os.path.join(f.rd, "VACUOUS.md"), "w").write(
            "| # | statement | for which parameters | why | decision | status |\n|---|---|---|---|---|---|\n"
            "| 1 | Lemma 1.3 (c) | all | never holds | keep | open |\n")
        sm = make_report.summary_md(f.cfg)
        sp = [str(x) for x in make_report.summary_problems(f.cfg, sm)]
        out.append(("sub-parts: a VACUOUS row on Lemma 1.3 (c) makes (c) vacuous and leaves (a) faithful, and the §1 "
                    "independent check does not call (a) plain-but-named (result_status.mentions, part-aware)",
                    status_of(sm, "Lemma 1.3 (c)") == "true only vacuously"
                    and status_of(sm, "Lemma 1.3 (a)") == "faithful" and not sp))
        bad = with_status(sm, "Lemma 1.3 (c)", "faithful")
        out.append(("control: the result the row does name, shown as plain, is refused by the §1 check; mentions "
                    "reads a list of parts",
                    any("Lemma 1.3 (c) reads plain" in str(x) for x in make_report.summary_problems(f.cfg, bad))
                    and make_report._mentions("Lemma 1.3 (b) and (c)", "Lemma 1.3 (c)", [])
                    and not make_report._mentions("Lemma 1.3 (c)", "Lemma 1.3 (a)", [])))
    finally:
        f.close()
    f = Fixture(base, "release", "hands-off", tag="b9dev")
    try:
        dv = ("| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
              "| 1 | Lemma 1.2 | reading A | reading B | the paper is ambiguous | reading choice |\n")
        open(os.path.join(f.rd, "DEVIATIONS.md"), "w").write(dv)
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "deviations wording")
        f.prepare()
        bad = [t for c, t in make_report.delivery_problems(f.cfg) if c == "ownership"]
        g(f.aud, "reset", "-q", "--hard", "HEAD~2")
        open(os.path.join(f.rd, "DEVIATIONS.md"), "w").write(dv)
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"adjudicate {f.r1}")
        f.prepare()
        good = [t for c, t in make_report.delivery_problems(f.cfg) if c == "ownership"]
        # ownership 3: a DEVIATIONS.md fault is the adjudicator's to clear (pending), as PAPER_DEFECTS'; before 3
        # (or no pin) the operator's (report)
        import integrity
        open(os.path.join(f.rd, "DEVIATIONS.md"), "w").write(dv + "| 2 | Lemma 1.2 | x | y | z |\n")
        pinp = os.path.join(f.rd, integrity.PIN)
        before3 = {x.code for x in make_report.table_shape_problems(f.rd, "deviations", "DEVIATIONS.md", "kind",
                                                                  *make_report.record_table(os.path.join(f.rd, "DEVIATIONS.md"), "kind"))}
        json.dump({"ownership": 3}, open(pinp, "w"))
        own3 = [x for x in make_report.adjudication_findings(f.cfg) if "DEVIATIONS.md" in str(x)]
        os.remove(pinp)
        open(os.path.join(f.rd, "DEVIATIONS.md"), "w").write(dv)
        out.append(("ownership 3: a DEVIATIONS.md table fault is pending the next adjudication (adj-record, like "
                    "PAPER_DEFECTS); a run pinned earlier keeps it the operator's (report)",
                    before3 == {"report"} and own3 and {x.code for x in own3} == {"adj-record"}))
        out.append(("attack 6: a reading-choice row DEVIATIONS.md got from a commit that does not own it is RED[ownership] "
                    "at delivery (the summary's 'faithful under reading N' rests on it); the adjudication's row is not",
                    any("DEVIATIONS.md was committed by \"deviations wording\"" in t for t in bad) and good == []
                    and status_of(make_report.summary_md(f.cfg), "Lemma 1.2") == "faithful under a reading choice"
                    and "- reading choice 1 — Lemma 1.2: the Lean reads reading B" in make_report.summary_md(f.cfg)))
    finally:
        f.close()
    f = Fixture(base, "release", "hands-off", tag="b9fail")
    try:
        cp = os.path.join(f.rd, f.r1, "correspondence.json")
        j = json.load(open(cp))
        j["verdicts"][0]["verdict"] = "Fail"
        json.dump(j, open(cp, "w"))
        f.prepare()
        dp = make_report.delivery_problems(f.cfg)
        out.append(("an outstanding correspondence Fail (no decision recorded) is RED[adj-record] at delivery (B9's "
                    "route to the adjudicator), and the result reads not established",
                    any(c == "adj-record" and "Theorem 1.1: correspondence Fail" in t for c, t in dp)
                    and status_of(make_report.summary_md(f.cfg), "Theorem 1.1") == "not established: a review failed"))
    finally:
        f.close()
    f = Fixture(base, "dev", "involved", tag="b9nov", verdicts=False)
    try:
        sm = make_report.summary_md(f.cfg)
        un = make_report.unverified_problems(f.cfg)
        out.append(("no verdict on a result: it reads 'not established: no ... verdict' (never faithful, never a "
                    "stub) and the delivery check is RED[unverified] for it (B9's per-result rule)",
                    status_of(sm, "Theorem 1.1") == "not established: a review is missing"
                    and "| faithful |" not in sm and any(x.startswith("Theorem 1.1: no correspondence verdict") for x in un)))
    finally:
        f.close()
    return out


def assumptions_part(base):
    """[(name, ok)]: the summary's assumption lines are B5's hypotheses.report (as the report reads it)."""
    import make_report
    out = []
    f = Fixture(base, "release", "hands-off", tag="asm")
    try:
        os.remove(os.path.join(f.rd, "DEPENDENCIES.json"))
        f.prepare()
        sm = make_report.summary_md(f.cfg)
        rep = make_report.report_md(f.cfg)
        sec = sm.split("## Assumptions", 1)[1].split("\n## ", 1)[0]
        h_ = make_report.summary_inputs(f.cfg)
        row_ = [r for r in h_["index"] if r[0].startswith("Theorem")][0]
        out.append(("no assumption walk: the summary says NOT COMPUTED with the reason, never 'none', as the report does; "
                    "the result is not established (B9's reason: no assumption walk)",
                    "- assumptions — NOT COMPUTED: no DEPENDENCIES.json" in sec and "- none" not in sec
                    and "NOT COMPUTED: no DEPENDENCIES.json" in rep
                    and any("not established: no assumption walk" in s_ for s_ in make_report.result_status(f.cfg, row_, h_))
                    and status_of(sm, "Theorem 1.1").startswith("not established")))
        rel = make_report.delivery_problems(f.cfg)
        f.cfg["mode"] = "dev"
        dev = make_report.delivery_problems(f.cfg)
        f.cfg["mode"] = "release"
        out.append(("a status no route covers (no walk: status-unmapped) is disclosed in release (the summary says it; "
                    "no precondition) and RED in dev",
                    not any(c == "status-unmapped" for c, t in rel)
                    and any(c == "status-unmapped" and "no assumption walk" in t for c, t in dev)))
        json.dump({"commit": "x", "roots": ["P.thm_1_1"], "walked": ["P.thm_1_1", "P.lemma_1_2"],
                   "results": ["P.thm_1_1", "P.lemma_1_2"], "axioms": {},
                   "assumes": {"P.thm_1_1": [{"name": "P.InstHyp", "binder": "h", "kind": "prop",
                                              "type_pp": "InstHyp n", "embedded": False}], "P.lemma_1_2": []}},
                  open(os.path.join(f.rd, "DEPENDENCIES.json"), "w"))
        sm = make_report.summary_md(f.cfg)
        out.append(("a hypothesis the walk lists: one assumption line with its Lean binder and type, its record state "
                    "and plain English (pending here), the B5 count line, and the result's status names it",
                    "- assumption P.InstHyp — unclassified" in sm and "Lean: `P.thm_1_1`: (h : InstHyp n)" in sm
                    and "plain English: -" in sm
                    and "- assumptions — 1 hypothesis name(s) beyond the paper's definitions" in sm
                    and status_of(sm, "Theorem 1.1") == "not established: an assumption is not settled"
                    and make_report.summary_problems(f.cfg, sm) == []))
    finally:
        f.close()
    return out


def pdf_never_stops(base):
    """[(name, ok)] (integration review, attack 8): in release a PDF fault never opens a stop, in any mix. Since
    PDF-AGENTS the `pdf` code is an older run's (no script emits it); it keeps this meaning (review 2)."""
    import stops
    out = []
    f = Fixture(base, "release", "hands-off", tag="pdf8")
    try:
        both = "FAIL[pdf] ! SUMMARY.pdf does not say what SUMMARY.md says (1 passage)\nFAIL[report] ! Theorem 1.1: x\n"
        only = "FAIL[pdf] ! SUMMARY.pdf does not say what SUMMARY.md says (1 passage)\n"
        state = {"out": both}
        stops.RUNNER = lambda argv: ((1, state["out"]) if "make_report.py" in " ".join(argv) else (0, "ok\n"))
        gate = stops.deliver_gate(f.cfg)
        state["out"] = only
        gate_only = stops.deliver_gate(f.cfg)
        try:
            stops.open_stop(f.cfg, cmd="python3 audits/make_report.py --check")
            ref_only = False
        except stops.Refused as e:
            ref_only = "never a stop" in str(e)
        state["out"] = both
        try:
            s_, msg = stops.open_stop(f.cfg, cmd="python3 audits/make_report.py --check")
            doc = json.load(open(os.path.join(f.rd, "stops", s_, "STOP.json")))
        except stops.Refused as e:
            s_, msg, doc = None, str(e), {"causes": []}
        state["out"] = only
        try:
            if s_ is None:
                raise stops.Refused("no stop")
            stops.close_stop(f.cfg, s_, cured="fixed the report text; the PDF is rendered again by its agents")
            closed = json.load(open(os.path.join(f.rd, "stops", s_, "CLOSED.json")))
        except stops.Refused:
            closed = {}
        out.append(("attack 8, approver 2026-10-28: the delivery gate (the math gate) never runs make_report.py --check, "
                    "so a (legacy) PDF fault there never refuses delivery, alone or in a mix",
                    gate == [] and gate_only == []))
        out.append(("attack 8: stops.py open refuses a PDF fault alone, and in a mix opens the stop on the other faults "
                    "only (the PDF left out, routed to the rendering agents); its cure passes once only the left-out "
                    "fault remains",
                    ref_only and [c["code"] for c in doc["causes"]] == ["report"]
                    and [c["code"] for c in doc.get("left_out") or []] == ["pdf"]
                    and "render_record.py next --doc SUMMARY" in msg
                    and closed.get("rerun", {}).get("passes") is True))
    finally:
        f.close()
    return out


def pdf_agents(base):
    """[(name, ok)] PDF-AGENTS (review 11), on a delivery fixture with the rendering agents simulated through the real
    render_record.py: the honest path delivers each PDF with its md beside it; a swapped PDF and a PDF of an older md
    are refused at --deliver (RED[deliver], never a stop) until rendered again (a new version, round 1); an older run's
    DISCLOSED[pdf] record still parses and stays in README D, out of the generated documents."""
    import stops, render_record as rr
    out = []
    f = Fixture(base, "release", "statements-only", tag="pdfag")
    try:
        f.prepare(); f.read_all()
        rc0, o0 = f.deliver()
        got = sorted(os.listdir(os.path.join(f.repo, "deliverables"))) if rc0 == 0 else []
        out.append(("PDF-AGENTS honest path: prepare, the readers, the agents (A, B, two checkers) through "
                    "render_record.py, then --deliver ships each PDF with its md beside it",
                    rc0 == 0 and f.rendered == {"SUMMARY": "verified", "REPORT": "verified",
                                                f"SIGNOFF-{f.r0}": "verified"}
                    and {"SUMMARY.pdf", "SUMMARY.md", "REPORT.pdf", "REPORT.md", "SIGNOFF.pdf", "SIGNOFF.md"} <= set(got)))
        sp = os.path.join(f.rd, "SUMMARY.pdf")
        keep = open(sp, "rb").read()
        open(sp, "ab").write(b" swapped")
        f.render = False
        rc1, o1 = f.deliver()
        open(sp, "wb").write(keep)
        out.append(("PDF-AGENTS, approver 2026-10-28: a PDF swapped after its rendering is named in a note of --deliver "
                    "(a hash, never a reading): render again; never a refusal, never a stop",
                    rc1 == 0 and "RED[" not in o1 and "note: [pdf]" in o1 and "not the PDF the render record shipped" in o1))
        # an older run's DISCLOSED[pdf] record: parsed, in README D, never in the generated documents
        dd = os.path.join(f.rd, "stops", "disclosed")
        os.makedirs(dd, exist_ok=True)
        json.dump({"fault": "D1", "date": "2026-10-21", "command": "python3 audits/signoff.py check --round R",
                   "faults": [{"code": "pdf", "line": "SIGNOFF.pdf page check: p.4: text off the right page edge: LEGACYQZ"}]},
                  open(os.path.join(dd, "D1.json"), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "stop disclose D1")
        sm0 = open(os.path.join(f.rd, "SUMMARY.md")).read()
        f.prepare()
        rc2, o2 = f.deliver()
        rd_ = open(os.path.join(f.repo, "deliverables", project.RUN_RECORD)).read() if rc2 == 0 else ""
        out.append(("review 2/11: an older run's DISCLOSED[pdf] record stays a delivery-phase record: the delivered "
                    "RUN_RECORD.md's delivery-phase notes list it (approver 2026-10-24), "
                    "the summary does not change (no re-render, no reader re-run)",
                    rc2 == 0 and "LEGACYQZ" in rd_ and open(os.path.join(f.rd, "SUMMARY.md")).read() == sm0
                    and "LEGACYQZ" not in open(os.path.join(f.rd, "REPORT.md")).read()
                    and stops.delivery_phase(["pdf"]) and "pdf" in project.NEVER_STOP))
        # the md changes (a stop closed: the summary lists it): its PDF is stale until rendered again
        f.failing = {"integrity.py"}
        s_, _m = stops.open_stop(f.cfg, note="a tool call failed", cause="tool-call",
                                 check="python3 audits/integrity.py --check")
        f.failing = set()
        # answered by the human: the summary lists it (a self-cure would be RUN_RECORD.md's only, approver 2026-10-24)
        stops.close_stop(f.cfg, s_, human="re-run it")
        f.prepare()
        f.write_docs()      # the main agent revises its summary from the new facts (the closed stop)
        rc3, o3 = f.deliver()
        f.render = True
        rc4, o4 = f.deliver()
        v_ = (rr.load(f.cfg, "SUMMARY") or {})
        out.append(("PDF-AGENTS, approver 2026-10-28: a PDF built from an older md is a note of --deliver until rendered "
                    "again; the new md gets a new version, from round 1 (the md ships beside the new PDF)",
                    rc3 == 0 and "note: [pdf]" in o3 and "changed since its PDF was rendered" in o3 and rc4 == 0
                    and v_.get("version") == 2 and len(v_.get("rounds") or []) == 1
                    and v_.get("earlier", [{}])[0].get("outcome") == "verified"))
    except Exception as e:      # noqa: BLE001
        import traceback
        out.append((f"PDF-AGENTS delivery scenarios ran ({e!r} {traceback.format_exc()[-500:]})", False))
    finally:
        f.close()
    return out


def delivery_round_cap(base):
    """[(name, ok)]: integrated review fix 1. After the final full round, a Lean commit asks for a diff round
    (RED[deliver-stale]) only while fewer than project.DELIVERY_ROUND_CAP rounds ran after it; past the cap the commit
    ships unaudited and disclosed (the report's trust row, the summary's Process line), and --deliver delivers: each
    such round could adopt more fixes, so a round per change never ended (stage5 step 1: "start no further round")."""
    import make_report
    out = []
    for mode in project.MODES:
        f = Fixture(base, mode, "hands-off", tag="cap")
        try:
            fp = open(os.path.join(f.rd, f.r1, "FINGERPRINTS.json")).read()

            def lean_commit(k):
                open(os.path.join(f.repo, "P", "Main.lean"), "a").write(f"theorem late_{k} : True := trivial\n")
                g(f.repo, "add", "-A"); g(f.repo, "commit", "-qm", f"delivery-phase fix {k}")

            def diff_round(day):
                r = os.path.join(f.rd, f"2026-01-{day:02d}-" + g(f.repo, "rev-parse", "HEAD")[:11])
                os.makedirs(r)
                json.dump({"_meta": {"kind": "diff"}}, open(os.path.join(r, "TARGET.json"), "w"))
                open(os.path.join(r, "FINGERPRINTS.json"), "w").write(fp)
                open(os.path.join(r, "ADOPTED.md"), "w").write("# Adjudication\n\nADOPT one more docstring fix.\n")
                dp_ = os.path.join(f.rd, "DECISIONS.md")
                txt_ = open(dp_).read()
                open(dp_, "w").write(txt_.replace(f.r1, os.path.basename(r)))
                f.r1 = os.path.basename(r)
                g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"adjudicate {os.path.basename(r)}")
            st = []
            for k, day in ((1, 3), (2, 4), (3, 5)):
                lean_commit(k)
                st.append(make_report.stale_problems(f.cfg))
                if k < 3:
                    diff_round(day)
            lr = make_report.later_row(f.cfg)
            rc, _l = f.prepare()
            f.read_all()
            rcd, outd = f.deliver()
            # a newer full round (Stage 5's, after Stage 4's opening one and its diff rounds) restarts the count
            r4 = os.path.join(f.rd, "2026-01-06-full-" + g(f.repo, "rev-parse", "HEAD")[:11])
            os.makedirs(r4)
            json.dump({"_meta": {"kind": "full"}}, open(os.path.join(r4, "TARGET.json"), "w"))
            open(os.path.join(r4, "FINGERPRINTS.json"), "w").write(fp)
            open(os.path.join(r4, "ADOPTED.md"), "w").write("# Adjudication\n\nNo lane failed.\n")
            g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"adjudicate {os.path.basename(r4)}")
            lean_commit(4)
            st4 = make_report.stale_problems(f.cfg)
            g(f.repo, "reset", "-q", "--hard", "HEAD~1")
            shutil.rmtree(r4)
            g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "drop the newer full round")
            sm = open(os.path.join(f.rd, "SUMMARY.md")).read()
            out.append((f"fix 1 ({mode}): after the final full round a Lean commit asks for a diff round (deliver-stale, "
                        f"round 1 then 2 of at most {project.DELIVERY_ROUND_CAP}); after the second such round the next "
                        f"commit ships: no deliver-stale, the report's row and the summary say it is not re-audited and "
                        f"the cap is reached, and --deliver delivers",
                        project.DELIVERY_ROUND_CAP == 2 and len(st[0]) == 1 and "round 1 of at most 2" in st[0][0]
                        and len(st[1]) == 1 and "round 2 of at most 2" in st[1][0] and st[2] == []
                        and "NOT re-audited" in lr[2] and "round cap is reached" in lr[2] and "late_3" not in lr[2]
                        and "delivery-phase fix 3" in lr[2]
                        and any(l.startswith("- after the last audit round — ") and "round cap is reached" in l
                                and "NOT re-audited" in l and "REPORT §1" in l for l in sm.splitlines())
                        and rc == 0 and rcd == 0 and len(st4) == 1 and "round 1 of at most 2" in st4[0]))
        except Exception as e:      # noqa: BLE001 -- a crash fails the case
            import traceback
            out.append((f"fix 1 ({mode}): crashed {e!r} {traceback.format_exc()[-500:]}", False))
        finally:
            f.close()
    return out


def route_change_after_adjudication(base):
    """[(name, ok)]: integrated review fix 5. Under ownership 3 the adjudicator writes DEVIATIONS.md from AUTHOR_NOTES.md's
    "Route changes"; a row recorded after the last adjudication never reached DEVIATIONS.md or the report. --deliver
    refuses it (RED[adj-record]) until a round's adjudicator has seen it, an empty diff scope routes to a full round,
    and that round's adjudication clears it. A run pinned before ownership 3 (the operator writes the rows) is not
    affected."""
    import integrity, make_report, scope
    out = []
    f = Fixture(base, "release", "hands-off", tag="route")
    try:
        head = "## Route changes\n\n| # | result | the paper's route | the Lean route | why different | kind |\n|---|---|---|---|---|---|\n"
        row1 = "| 1 | Theorem 1.1 | induction | `simp` | shorter | same strength |\n"
        row2 = "| 2 | Lemma 1.2 | a computation | `rfl` | shorter | same strength |\n"
        an = os.path.join(f.rd, "AUTHOR_NOTES.md")
        open(an, "w").write("# Author notes\n\n" + head + row1 + "\n## Notes for the sign-off writer\n\nnone\n")
        json.dump({"ownership": 3}, open(os.path.join(f.rd, integrity.PIN), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "author notes, pin")
        open(os.path.join(f.rd, f.r1, "ADOPTED.md"), "a").write("\nDEVIATIONS.md row 1 written.\n")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"adjudicate {f.r1}")
        p0 = make_report.route_changes_pending(f.cfg)
        open(an, "w").write("# Author notes\n\n" + head + row1 + row2 + "\n## Notes for the sign-off writer\n\nnone\n")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "author notes: route change 2")
        p1 = make_report.route_changes_pending(f.cfg)
        f.prepare(); f.read_all()
        rc1, out1 = f.deliver()
        nxt = scope.empty_scope_next(f.cfg)
        json.dump({"ownership": 2}, open(os.path.join(f.rd, integrity.PIN), "w"))
        p_old = make_report.route_changes_pending(f.cfg)
        json.dump({"ownership": 3}, open(os.path.join(f.rd, integrity.PIN), "w"))
        r2 = os.path.join(f.rd, "2026-01-09-full-" + g(f.repo, "rev-parse", "HEAD")[:11])
        os.makedirs(r2)
        json.dump({"_meta": {"kind": "full"}}, open(os.path.join(r2, "TARGET.json"), "w"))
        open(os.path.join(r2, "ADOPTED.md"), "w").write("# Adjudication\n\nDEVIATIONS.md row 2 written.\n")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "adjudicate full round")
        p2 = make_report.route_changes_pending(f.cfg)
        out.append(("fix 5: a route change recorded in AUTHOR_NOTES.md after the last adjudication is a note [adj-record] "
                    "of --deliver (pending the next adjudication; approver 2026-10-28: never a refusal), the empty diff "
                    "scope routes to a full round, whose adjudication clears it; rows the last adjudication saw are not "
                    "pending; a run pinned before ownership 3 is not affected",
                    p0 == [] and p1 == [" ".join(row2.split())] and rc1 == 0 and "note: [adj-record]" in out1
                    and "Route changes" in out1 and nxt[0] == "full" and p_old == [] and p2 == []))
    finally:
        f.close()
    return out


def operator_sourced_answers(base):
    """[(name, ok)]: integrated review fix 7. Under `involved` a `## Answered` line citing an escalation ("escalation
    E<n>"), an adjudicator's record or the conservative rule is the operator's decision: it never closes Checkpoint C
    as the human's answer; the human's own words do."""
    import decisions
    out = []
    f = Fixture(base, "release", "involved", tag="esc")
    try:
        f.prepare(); f.read_all()
        items = decisions.checkpoint_c_open(f.cfg)
        res = {}
        for tag, ans in (("esc", "keep it, as escalation E1 answered (ANSWERABLE)"),
                         ("adj", f"follow the adjudicator's row in {f.r1}/ADOPTED.md"),
                         ("cons", "keep the paper's statement (conservative rule)"),
                         ("human", "yes, keep it")):
            for a_ in items:
                project.log_append(f.cfg, "Answered", f"- answered {a_} (2026-01-03, {f.r1}): {ans}")
            g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"run log: answers ({tag})")
            res[tag] = decisions.checkpoint_c_open(f.cfg)
            if tag == "esc":
                f.prepare(); f.read_all(["decisions", "summary", "report"])
                res["deliver"] = f.deliver()
        out.append(("fix 7: under involved, a Checkpoint C answer citing an escalation (escalation E<n>), an adjudicator's "
                    "record or the conservative rule leaves C open (--deliver waits: PENDING[question], a wait, never a "
                    "stop); the human's own words close it",
                    items and res["esc"] == items and res["adj"] == items and res["cons"] == items and res["human"] == []
                    and res["deliver"][0] == 1 and res["deliver"][1].startswith("PENDING[question]")
                    and decisions.human_answer(f"answered {items[0]} (2026-01-03, {f.r1}): yes, keep it")))
    finally:
        f.close()
    return out


def open_reapproval_status(base):
    """[(name, ok)]: integrated review fix 9. While a re-approval of a statement is open (begun, the Lean not yet
    changed: every review still passes) the summary must not print "faithful" for it: it prints the open
    re-approval (status 3, decision open); the other results are unaffected."""
    import fingerprint, make_report
    out = []
    f = Fixture(base, "release", "involved", tag="reap")
    try:
        before = make_report.summary_md(f.cfg)
        json.dump({"decls": ["P.thm_1_1"], "begin_fingerprints": {"P.thm_1_1": "fp-P.thm_1_1"},
                   "lean_head": g(f.repo, "rev-parse", "HEAD"),
                   "begins": [{"date": "2026-01-05", "reason": "a stronger bound"}]},
                  open(os.path.join(f.rd, fingerprint.REAPPROVAL), "w"))
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", fingerprint.REAPPROVAL_BEGIN + ": P.thm_1_1)")
        after = make_report.summary_md(f.cfg)
        line = status_of
        out.append(("fix 9: while a re-approval of Theorem 1.1's statement is open (the Lean unchanged, every review "
                    "still Pass) the summary prints the open re-approval (decision open), never 'faithful'; Lemma 1.2 "
                    "still reads faithful",
                    line(before, "Theorem 1.1") == "faithful"
                    and "a decision is open: its statement awaits re-approval" in line(after, "Theorem 1.1")
                    and "faithful" not in line(after, "Theorem 1.1")
                    and line(after, "Lemma 1.2") == "faithful"))
    finally:
        f.close()
    return out


def unmapped_dev_cure(base):
    """[(name, ok)]: integrated review fix 6, approver 2026-10-28. In dev a result whose status no route covers
    (status-unmapped) is a note of --deliver, never a refusal and never a stop: Phase 0's walk (DEPENDENCIES.json)
    clears it; what remains the main agent judges, and the run delivers."""
    import decisions, make_report, stops
    out = []
    f = Fixture(base, "dev", "involved", tag="unm")
    try:
        dep = os.path.join(f.rd, "DEPENDENCIES.json")
        keep = open(dep).read()
        f.prepare()
        os.remove(dep)
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "no walk")
        red0 = [t for c, t in make_report.delivery_problems(f.cfg) if c == "status-unmapped"]
        open(dep, "w").write(keep)
        cured = [t for c, t in make_report.delivery_problems(f.cfg) if c == "status-unmapped"]
        os.remove(dep)
        f.prepare()
        for a_ in decisions.checkpoint_c_open(f.cfg):
            project.log_append(f.cfg, "Answered", f"- answered {a_} (2026-01-03, {f.r1}): yes, keep it")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "run log: Checkpoint C answered")
        o = io.StringIO()
        with contextlib.redirect_stdout(o):
            make_report.delivery_check(f.cfg)
        chk = o.getvalue()
        keep_r = stops.RUNNER
        stops.RUNNER = lambda argv: (1, chk)
        try:
            stops.open_stop(f.cfg, cmd="python3 audits/make_report.py --check --delivery")
            refused = False
        except stops.Refused as e:
            refused = "never a stop" in str(e)
        finally:
            stops.RUNNER = keep_r
        rc, outd = f.deliver()
        out.append(("fix 6 (dev), approver 2026-10-28: status-unmapped is a note: Phase 0's walk clears it; a stop on "
                    "the delivery check is refused (never a stop); --deliver delivers and names it",
                    red0 and cured == [] and refused and rc == 0 and "note: [status-unmapped]" in outd
                    and stops.stops(f.cfg) == []))
    finally:
        f.close()
    return out


def statement_round_restart(base):
    """[(name, ok)]: integrated review fix 3. stage2 step 2: `signoff.py bundle` reports a PROBLEM after the round was
    scoped; "fix it and start this step again" failed (the name is taken, the round counted). Now: the round is set
    aside (stops.py set-aside; no longer a round, counted by no cap); a restart at the same Lean HEAD (a config-only
    fix) is refused with the prescribed empty commit, which gives a new name that scopes."""
    import scope, stops, tree_state
    out = []
    f = Fixture(base, "release", "hands-off", tag="restart")
    try:
        def scoped(name):
            r = os.path.join(f.rd, name)
            os.makedirs(r)
            json.dump({"_meta": {"kind": "statements"}}, open(os.path.join(r, "TARGET.json"), "w"))
            json.dump({"commit": g(f.repo, "rev-parse", "HEAD"), "fingerprints": {}}, open(os.path.join(r, "FINGERPRINTS.json"), "w"))
            g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"scope {name}")
        r2 = "2026-01-05-full-" + g(f.repo, "rev-parse", "HEAD")[:11]
        scoped(r2)
        p_scoped = scope.preflight(f.cfg, f.repo, r2, "statements")
        doc, _h = stops.set_aside(f.cfg, r2, "bundle PROBLEM: an index name does not resolve")
        counted = [os.path.basename(x) for x in project.rounds(f.cfg)]
        p_aside = scope.preflight(f.cfg, f.repo, r2, "statements") or ""
        subj = f"fresh round after the set-aside of {r2}"
        g(f.repo, "commit", "-q", "--allow-empty", "-m", subj)
        r3 = "2026-01-05-full-" + g(f.repo, "rev-parse", "HEAD")[:11]
        p_nowalk = scope.preflight(f.cfg, f.repo, r3, "statements") or ""
        scope._fresh_walk(f.cfg, f.repo)        # SWEEP-FIX D1: a statement round is scoped on a fresh walk only
        p_new = scope.preflight(f.cfg, f.repo, r3, "statements")
        out.append(("fix 3: a statement round given up before its review (bundle PROBLEM) is set aside and counts as no "
                    "round; restarting under the same name is refused with the prescribed empty Lean commit (the "
                    "subject tree_state accepts), which names a new round that scopes",
                    p_scoped and "already scoped" in p_scoped and doc["round"] == r2 and r2 not in counted
                    and f'git commit --allow-empty -m "{subj}"' in p_aside
                    and any(rx.match(subj) for rx in tree_state.OPERATOR_EMPTY) and r3 != r2 and p_new is None
                    and "assumption walk" in p_nowalk))
    finally:
        f.close()
    return out


def prepare_names_faults(base):
    """[(name, ok)]: review item 11. On mini2's honest path --prepare-delivery exited 1 ("report check FAILED: 1
    problem(s)") but printed only make_report's last line, so the operator could not tell which fault. Prepare now
    names each failure line."""
    out = []
    f = Fixture(base, "release", "hands-off", tag="prep")
    keep = project.REGENERATE_REPORT
    try:
        mr = ("  wrote audits/R/REPORT.md\nFAIL[render] DEVIATIONS.md row R1: LaTeX `\\qed` outside a code span\n"
              "report check FAILED: 1 problem(s)\n")
        tail = project.report_tail(mr)
        project.REGENERATE_REPORT = lambda c_: (1, tail)
        rc, lines = f.prepare()
        txt = "\n".join(lines)
        out.append(("item 11: prepare names make_report's failure lines (not only 'report check FAILED: 1 problem(s)'), "
                    "and names the render step that follows the readers",
                    rc == 1 and tail[0] == "report check FAILED: 1 problem(s)" and "FAIL[render] DEVIATIONS.md row R1" in txt
                    and "render_record.py next --doc SUMMARY|REPORT" in txt and "--render-fix" not in txt))
    finally:
        project.REGENERATE_REPORT = keep
        f.close()
    return out


def leave_after_final(base):
    """[(name, ok)]: integrated review fix 2. A `leave <decl> unproved` line logged after the final round (delegated
    Checkpoint C) with no Lean change: the diff scope is empty, and Stage 5's --deliver refuses RED[adj-record]. The
    empty scope must route to a full round (NEXT[full-round]), whose adjudication clears the pending line."""
    import decisions, make_report, scope
    out = []
    f = Fixture(base, "release", "hands-off", tag="leave")
    try:
        before = scope.empty_scope_next(f.cfg)[0]
        open(os.path.join(f.rd, "RUN_LOG.md"), "a").write(
            "## Open questions\n- [DELEGATED 2026-01-05, operator under hands-off (intake); reversal: re-prove] leave "
            "P.lemma_1_2 unproved — no proof found\n")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "log leave")
        nxt = scope.empty_scope_next(f.cfg)
        red = decisions.pending_refusal(f.cfg)
        r2 = os.path.join(f.rd, "2026-01-09-full-" + g(f.repo, "rev-parse", "HEAD")[:11])
        os.makedirs(r2)
        json.dump({"_meta": {"kind": "full"}}, open(os.path.join(r2, "TARGET.json"), "w"))
        open(os.path.join(r2, "ADOPTED.md"), "w").write("# Adjudication\n\nNo lane failed.\n")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "adjudicate full round")
        out.append(("fix 2: a leave line logged after the final round, nothing for a diff round to scope: the empty "
                    "scope routes to a full round (NEXT[full-round], prompt.py 3 --full), never back to Stage 5 "
                    "(which refuses RED[adj-record]); the full round's adjudication clears the pending line",
                    before == "stage5" and nxt[0] == "full" and nxt[1].startswith("NEXT[full-round]")
                    and "prompt.py 3 --full" in nxt[1] and "P.lemma_1_2" in nxt[1] and red
                    and decisions.pending_unproved(f.cfg) == []))
    finally:
        f.close()
    return out


def reader_fix_no_change(base):
    """[(name, ok)]: trial #9 (S2). The second reader fix found no record cell it may change, --commit-reader-fix
    refused "no record changed", the budget read 1 of 2, and every [content] finding answered unfixable kept the
    summary's gate refused: a stop. A no-change reader fix is now recorded (an empty "reader-fix R n") and counted,
    so after two the findings close as unfixable (disclosed), with no stop."""
    import integrity, readers, stops
    out = []
    f = Fixture(base, "release", "hands-off", tag="rfnc")
    try:
        rc, lines = f.prepare()
        f.read_all()
        key, srcs, _ = readers.resolve(f.cfg, "summary", None)
        h = readers.content_hash(srcs, "summary")
        CF = "the summary clips the vacuous line (generator text)"
        path, probs = readers.save(f.cfg, "summary", None, f"sha256: {h}\ncoverage: all\n- BLOCKING: [content] {CF}\n"
                                   "VERDICT: BLOCKING PROBLEMS: 1\n")
        n = os.path.basename(path)[len(key) + 1:-3]
        open(os.path.join(f.rd, "readers", f"{key}-{n}.response.md"), "w").write(
            f"- unfixable: [content] {CF[:30]} — fix budget reached: the record keeps the row as adjudicated\n")
        open(os.path.join(f.rd, f"KNOWN_FAULTS-{key}.md"), "w").write(f"- [content] {CF}\n")
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", f"reader summary {n} response")
        budget = lambda: [p_ for p_ in readers.check(f.cfg, "summary") if "reader-fix rounds are used" in p_]
        b0 = budget()
        res = []
        for k in (1, 2):
            prel = integrity.reader_fix_prompt_rel(f.r1, k)
            os.makedirs(os.path.dirname(os.path.join(f.rd, prel)), exist_ok=True)
            open(os.path.join(f.rd, prel), "w").write(f"READER FIX {k}\n")
            g(f.aud, "add", "--", os.path.join("R", prel)); g(f.aud, "commit", "-qm", f"reader-fix-prompt {f.r1} {k}")
            res.append(integrity.commit_reader_fix(f.aud, f.rd, "R", f.r1, f.cfg))
            res.append(budget())
        try:
            integrity.commit_reader_fix(f.aud, f.rd, "R", f.r1, f.cfg)
            third = False
        except ValueError as e:
            third = "spent" in str(e)
        out.append(("trial #9 (S2): a reader fix that changes nothing is recorded and counted: after two, the [content] "
                    "finding answered unfixable passes the summary's gate (disclosed in the notice), no stop; before, "
                    "and after one, the gate sends it to a reader fix; a third is refused",
                    rc == 0 and b0 and "0 of the run's 2" in b0[0] and res[0][1:] == (1, []) and res[1]
                    and "1 of the run's 2" in res[1][0] and res[2][1:] == (2, []) and res[3] == [] and third
                    and readers.fix_rounds_used(f.cfg) == 2 and stops.stops(f.cfg) == []
                    and integrity.reader_fix_prompt_problems(f.aud, "R", f.r1) == []
                    and g(f.aud, "log", "-1", "--format=%s") == f"reader-fix {f.r1} 2"))
    except Exception as e:      # noqa: BLE001 -- a crash fails the case, with its reason
        import traceback
        out.append((f"trial #9 (S2) no-change reader fix ran ({e!r} {traceback.format_exc()[-400:]})", False))
    finally:
        f.close()
    return out


def citation_notes(base):
    """[(name, ok)] of the advisory citation notes (run/stage5-delivery.md step 5a). Without CITATIONS.md a run
    delivers exactly as before: the summary is the generator's output with the citation line switched off, and the
    delivered files and README D name no citation notes (a stale copy of an earlier delivery is removed). With it,
    --deliver copies it unchanged, the summary carries one line with its number of items and README D lists it.
    With the operator's RUN_LOG line instead, the summary says it was not produced, and why."""
    import make_report
    out = []
    plain = {"SUMMARY.pdf", "SUMMARY.md", "REPORT.pdf", "REPORT.md", "DECISIONS.md", "SIGNOFF.pdf", "SIGNOFF.md",
             "README.md", "RUN_RECORD.md"}

    def run(tag, setup=None):
        f = Fixture(base, "release", "hands-off", tag=tag)
        try:
            if setup:
                setup(f)
                g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "citations: notes")
            f.prepare()
            f.read_all()
            rc, o = f.deliver()
            dv = os.path.join(f.repo, "deliverables")
            got = set(os.listdir(dv)) if os.path.isdir(dv) else set()
            sm = open(os.path.join(f.rd, "SUMMARY.md"), encoding="utf-8").read()
            readme = open(os.path.join(dv, "README.md"), encoding="utf-8").read() if "README.md" in got else ""
            keep = make_report.citation_line
            make_report.citation_line = lambda rd: None
            try:
                old = make_report.summary_md(f.cfg)
            finally:
                make_report.citation_line = keep
            return f, rc, o, got, sm, readme, old
        except Exception:
            f.close()
            raise

    f, rc, o, got, sm, readme, old = run("cit0")
    try:
        # an earlier delivery's copy never stands beside a delivery without notes (the folder made if the delivery
        # above failed, so that failure fails this case instead of crashing the selftest: mutant b10-6)
        os.makedirs(os.path.join(f.repo, "deliverables"), exist_ok=True)
        open(os.path.join(f.repo, "deliverables", "CITATIONS.md"), "w").write("# stale\n")
        rc2, _o2 = f.deliver()
        stale_gone = not os.path.exists(os.path.join(f.repo, "deliverables", "CITATIONS.md"))
    finally:
        f.close()
    out.append(("citation notes absent: the run delivers exactly as before (the same files, the summary the generator "
                "writes with the citation line switched off, no citation line, README D silent; an earlier copy removed)"
                + ("" if rc == 0 else f" [{o[-300:]!r}]"),
                rc == 0 and rc2 == 0 and got == plain and sm == old and "itation" not in sm
                and "CITATIONS" not in readme and stale_gone))
    notes = ("# Citation notes for the authors\n\nIntro.\n\n## Cited results\n\n### C1. l.10 -- [3, Thm 2]\n- x\n\n"
             "### C2. l.20 -- [4]\n- y\n\n## Bibliography\n\n### B1. key -- year\n- z\n\n## Sources not reached\n\n"
             "- none\n")
    f, rc, o, got, sm, readme, old = run("cit1", lambda f_: open(os.path.join(f_.rd, "CITATIONS.md"), "w",
                                                                 encoding="utf-8").write(notes))
    f.close()
    copied = os.path.join(f.repo, "deliverables", "CITATIONS.md")
    out.append(("citation notes present: --deliver copies CITATIONS.md unchanged, the summary says \"Citation notes: 3 "
                "items — see CITATIONS.md\" and README D lists it" + ("" if rc == 0 else f" [{o[-300:]!r}]"),
                rc == 0 and got == plain | {"CITATIONS.md"}
                and open(copied, encoding="utf-8").read() == notes
                and "\n- Citation notes: 3 items — see CITATIONS.md" in sm and sm != old
                and "`CITATIONS.md`: advisory notes" in readme))

    def not_produced(f_):
        project.log_append(f_.cfg, "Citation notes", "- citation notes not produced: the network was unavailable")
    f, rc, o, got, sm, readme, old = run("cit2", not_produced)
    f.close()
    out.append(("citation notes not produced: the summary says so in one line, with the logged reason; nothing else "
                "changes" + ("" if rc == 0 else f" [{o[-300:]!r}]"),
                rc == 0 and got == plain
                and "\n- Citation notes: not produced: the network was unavailable.\n" in sm
                and "CITATIONS" not in readme))
    return out


def delivery_log(base):
    """[(name, ok)] C1 audit (defect 4): conf1's delivery took 22 minutes with nothing recorded, and RUN_LOG.md still
    read "Stage 5 — final round" after it. Each --deliver attempt is logged under "## Delivery" (start, end, outcome by
    code), a delivery sets the stage, and the log line is no generator input: delivering again still delivers."""
    import re as _re
    out = []
    f = Fixture(base, "release", "hands-off", tag="dlog")
    try:
        project.log_append(f.cfg, "Current stage", "Stage 5 — final round", replace=True)     # conf1's last stage line
        g(f.aud, "add", "-A"); g(f.aud, "commit", "-qm", "run log: stage")
        f.prepare()
        open(os.path.join(f.repo, "P", "Main.lean"), "a").write("theorem later : True := trivial\n")
        g(f.repo, "add", "-A"); g(f.repo, "commit", "-qm", "a Lean change after the last round")
        rc0, o0 = f.deliver()           # the math gate refuses (deliver-stale)
        g(f.repo, "reset", "-q", "--hard", "HEAD~1")
        rc1, o1 = f.deliver()
        rc2, o2 = f.deliver()
        log = open(os.path.join(f.rd, "RUN_LOG.md"), encoding="utf-8").read()
        sec = log.split("## Delivery\n", 1)[1].split("\n## ", 1)[0] if "## Delivery\n" in log else ""
        ls = [l for l in sec.splitlines() if l.startswith("- ")]
        ts = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}"
        stage = project.current_stage(f.cfg) or ""
        out.append(("C1 audit: each --deliver attempt is logged in RUN_LOG.md (start, end, refused by code or "
                    "delivered), the delivery sets the stage to delivered, and delivering again still delivers"
                    + ("" if rc1 == 0 and rc2 == 0 else f" [{o1[-300:]!r} {o2[-300:]!r}]"),
                    rc0 == 1 and rc1 == 0 and rc2 == 0 and len(ls) == 3
                    and all(_re.match(rf"- {ts} to {ts}: project\.py --deliver ", l) for l in ls)
                    and _re.search(r"--deliver refused: RED\[\w", ls[0]) is not None
                    and "delivered " in ls[1] and "file(s) to deliverables/" in ls[1] and "delivered " in ls[2]
                    and stage.startswith("Stage 5 — delivered ") and "final round" not in stage
                    and project.stage_file(stage) == project.STAGE_FILES[5]
                    # approver 2026-10-25: committed by --deliver, and the delivered run record gives the times
                    and g(f.aud, "status", "--porcelain", "--", os.path.relpath(os.path.join(f.rd, "RUN_LOG.md"), f.aud)) == ""
                    and _re.search(rf"Delivery: `project\.py --deliver` started {ts}; this run record was written {ts}",
                                   open(os.path.join(f.repo, "deliverables", project.RUN_RECORD), encoding="utf-8").read())
                    is not None))
    finally:
        f.close()
    return out


# approver (2026-10-28): the status check (status_check_rerun) and the hand edits of generated documents (doc_faults) are
# no longer part of the delivery -- the main agent writes the documents and the delivery reviewers advise
# (run/stage5-delivery.md) -- so their delivery scenarios are gone; readers.py and run_record.py keep their own
# selftests for an older run's records.


def selftest():
    res = []

    def say(name, ok):
        res.append(bool(ok))
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    base = tempfile.mkdtemp(prefix="delivery-")
    try:
        say("GEN_INPUTS is disjoint from READER_OUTPUTS and DELIVER_OUTPUTS (path check)",
            project.gen_inputs_problems() == [])
        say("control: a GEN_INPUTS pattern that also matches a reader's record is caught",
            bool(project.gen_inputs_problems(gen=project.GEN_INPUTS + ("readers/*",))))
        for name, ok in behaviour(base):
            say(name, ok)
        for name, ok in preconditions(base):
            say(name, ok)
        for name, ok in b9_plug(base):
            say(name, ok)
        for name, ok in assumptions_part(base):
            say(name, ok)
        for name, ok in pdf_never_stops(base):
            say(name, ok)
        for name, ok in pdf_agents(base):
            say(name, ok)
        for name, ok in leave_after_final(base):
            say(name, ok)
        for name, ok in delivery_round_cap(base):
            say(name, ok)
        for name, ok in route_change_after_adjudication(base):
            say(name, ok)
        for name, ok in operator_sourced_answers(base):
            say(name, ok)
        for name, ok in open_reapproval_status(base):
            say(name, ok)
        for name, ok in unmapped_dev_cure(base):
            say(name, ok)
        for name, ok in statement_round_restart(base):
            say(name, ok)
        for name, ok in prepare_names_faults(base):
            say(name, ok)
        for name, ok in reader_fix_no_change(base):
            say(name, ok)
        for name, ok in citation_notes(base):
            say(name, ok)
        for name, ok in delivery_log(base):
            say(name, ok)
        for mode in project.MODES:
            for level in project.INVOLVEMENT_LEVELS:
                ok, why = scenario(base, mode, level)
                say(f"scenario {mode} x {level} (approver 2026-10-28): a stale facts draft, an open stop, an "
                    f"unanswered reader finding, a hand-edit MISMATCH and a result_status disagreement deliver with "
                    f"notes (no stop); a Lean commit after the last audited round or an undisclosed sorry is refused"
                    + ("" if ok else f" [{why}]"), ok)
    finally:
        shutil.rmtree(base, ignore_errors=True)
    ok = all(res)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)

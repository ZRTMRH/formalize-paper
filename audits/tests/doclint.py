#!/usr/bin/env python3
"""Doc-lint: the rules the operator's instructions must keep, and the lane prompts' record rule.

WHY.  Each check below names a sentence that a review established (a stop that remains at every
level, log-before-edit, the bytecode check, ...). Whitespace is normalised, so re-wrapping a
paragraph is not a failure, but a lost or reworded rule is: change the check together with the
rule, deliberately. These checks used to sit in prompt.py's selftest, which coupled the prompt
extractor to RUN.md's prose (simplification E5).

What is linted:
  - RUN.md (the always-read core) and the stage and procedure files under audits/run/ (B1);
  - the intake message (audits/run/stage0-intake.md, as project.intake_message() reads it);
  - the lane prompts' text in AUDIT_PROTOCOL.md: no lane prompt names an audit-record file
    (lanecheck.RECORD_RE) outside lane common rule 3, whose text names them to forbid reading them.
    Reader prompts are not checked for record names: a reader's job is to read REPORT/SIGNOFF.

  python3 -B audits/tests/doclint.py [--selftest]      exit 0 all present, 1 a check failed
(--selftest is accepted so that selftest_all.py and mutants.py run it like every other selftest;
it also runs negative controls on damaged copies of the documents.)
"""
import os, re, sys
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

AUDITS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AUDITS)
import project, prompt, lanecheck, integrity  # noqa: E402

RULE3_START = "3. Do not read the audit record"
RULE3_END = "\n4. "


def load():
    """(RUN.md, {run/<file>: text}, files on disk under run/, intake message, AUDIT_PROTOCOL.md)."""
    run_md = open(os.path.join(AUDITS, "RUN.md"), encoding="utf-8").read()
    run_files = {}
    for f_ in list(project.STAGE_FILES.values()) + project.PROCEDURE_FILES:
        try:
            run_files[f_] = open(os.path.join(AUDITS, f_), encoding="utf-8").read()
        except OSError:
            run_files[f_] = ""
    rd = os.path.join(AUDITS, "run")
    on_disk = sorted("run/" + x for x in os.listdir(rd)) if os.path.isdir(rd) else []
    ap = open(prompt.DEFAULT, encoding="utf-8").read()
    return run_md, run_files, on_disk, project.intake_message() or "", ap


# operator text names only what exists: scripts, their flags, failure codes, cause codes
EXTERNAL_FLAGS = ("--dangerously-skip-permissions", "--dangerously-bypass-approvals-and-sandbox",
                  "--search")   # Codex CLI launch flags named in run/codex.md (CODEX-U2)
# scripts the operator's text may name before they land: the tool-patch route (approver 2026-10-24, builder A;
# project.CURES["patch"], stops.py imports it at close). Remove the entry once audits/tool_patch.py is in the tree
PENDING_SCRIPTS = ("tool_patch.py",)
SCRIPT_RE = re.compile(r"(?<![\w/.-])(?:audits/)?((?:tests/)?[a-z_0-9]+)\.py\b")
CODE_RE = re.compile(r"\b(FAIL|RED|PROBLEM|NOTE|PENDING|DISCLOSED|NEXT)\[([a-z0-9-]+)\]")


def code_sources():
    """{path relative to audits/: source} of every script (this file aside: its controls name what does not exist)."""
    out = {}
    for d in (AUDITS, os.path.join(AUDITS, "tests")):
        for f_ in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f_.endswith(".py") and f_ != "doclint.py":
                out[os.path.relpath(os.path.join(d, f_), AUDITS)] = open(os.path.join(d, f_), encoding="utf-8").read()
    return out


def dangling_refs(texts, src):
    """[problem]: a script, a flag of a named script, a KIND[code] or a --cause code that the operator's text
    names and no script has. texts: {document name: text}."""
    allsrc = "\n".join(src.values())
    def has(s, w, exact=False):
        if exact:
            return f'"{w}"' in s or f"'{w}'" in s
        return re.search(r"[\"'\s(]" + re.escape(w) + r"(?![\w-])", s) is not None
    out = []
    for d, t in texts.items():
        for m in SCRIPT_RE.finditer(t):
            n = m.group(1) + ".py"
            if n not in src and "tests/" + n not in src and not os.path.exists(os.path.join(AUDITS, n)) \
                    and n not in PENDING_SCRIPTS:
                out.append(f"{d}: script {n}")
        for m in CODE_RE.finditer(t):
            if not re.search(r"[\"'\[{]" + re.escape(m.group(2)) + r"[\"'\]]", allsrc):
                out.append(f"{d}: code {m.group(0)}")
        for m in re.finditer(r"--cause\s+([a-z][a-z0-9-]*)", t):
            if m.group(1) not in project.CAUSES:
                out.append(f"{d}: --cause {m.group(1)}")
        for f_ in set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", t)) - set(EXTERNAL_FLAGS):
            if not has(allsrc, f_):
                out.append(f"{d}: flag {f_}")
        fenced = re.findall(r"```.*?```", t, re.S)
        spans = re.findall(r"`([^`]+)`", re.sub(r"\s*\n\s*", " ", re.sub(r"```.*?```", " ", t, flags=re.S)))
        spans += [ln for b in fenced for ln in b.split("\n")]
        for sp in spans:
            ms = list(SCRIPT_RE.finditer(sp))
            for j, m in enumerate(ms):
                n = m.group(1) + ".py"
                s = src.get(n, src.get("tests/" + n))
                if s is None:
                    continue
                seg = sp[m.end(): ms[j + 1].start() if j + 1 < len(ms) else len(sp)]
                seg = re.split(r"[;()]|: |\. |, ", re.sub(r"\"[^\"]*\"|'[^']*'|<[^>]*>", " ", seg))[0]
                for f_ in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", seg):
                    if not has(s, f_, exact=True):
                        out.append(f"{d}: `{sp[:80]}`: {n} has no {f_}")
    return sorted(set(out))


def lane_record_names(ap):
    """{lane: [record-file names its prompt text mentions outside common rule 3]}; a lane whose
    block is missing maps to None."""
    common = prompt.blocks_after(ap, prompt.COMMON_HEADING)
    out = {}
    for lane, sub in prompt.LANES:
        b = prompt.blocks_after(ap, sub)
        if b is None or common is None or RULE3_START not in common:
            out[lane] = None
            continue
        i = common.index(RULE3_START)
        j = common.find(RULE3_END, i)
        rest = common[:i] + (common[j:] if j >= 0 else "") + "\n" + b
        out[lane] = sorted({m.group(0) for m in lanecheck.RECORD_RE.finditer(rest)})
    return out


def lint(run_md, run_files, on_disk, intake, ap):
    """[(check name, passed)]."""
    checks = []
    def rf(name):
        return " ".join(run_files.get("run/" + name, "").split())
    core = " ".join(run_md.split())
    checks.append(("RUN.md's stage map names every stage and procedure file, each exists, and audits/run/ holds no other file",
                   all(run_files[f_] and f"`{f_}`" in run_md for f_ in run_files)
                   and on_disk == sorted(run_files)))
    checks.append(("RUN.md (core) keeps the resume step, the hands-off statement-change limits with log-before-edit, "
                   "and the missing-theory level rule; it does not send the operator to read AUDIT_PROTOCOL.md",
                   "python3 audits/project.py --stage" in core and "## Start or resume" in run_md
                   and "**Statement changes after approval.**" in core and "**Log before the edit:**" in core
                   and "never strengthens or generalizes a statement" in core
                   and "signoff.py reapprove --begin" in core and "**Missing theory.**" in core
                   and "**never a stop**" in core and "**build it** (option (1))" in core
                   and "**named hypothesis** (option (2))" in core
                   and "Do not read `AUDIT_PROTOCOL.md`" in core and "Read it in full" not in core))
    ft = core.split("## When something fails", 1)[-1].split("## Logging", 1)[0] if "## When something fails" in core else ""
    classes = sorted({c for c, _ in project.CAUSES.values()} | set(project.STOP_CLASSES))
    checks.append(("RUN.md's failure table names every cause class of project.CAUSES (B3) "
                   f"{[c for c in classes if c not in ft] or ''}",
                   bool(ft) and all(c in ft for c in classes)))
    rc_ = re.search(r"<!-- release-column:begin -->\n(.*?)\n<!-- release-column:end -->", run_md, re.S)
    checks.append(("RUN.md's failure table carries the release column generated from project.RELEASE, CURES and "
                   "CLOSER (U2 §4), and says --delegated is dev mode only",
                   rc_ is not None and rc_.group(1) == project.closer_table() and rc_.start() > run_md.find("| what failed |")
                   and "`close --delegated` is dev mode only" in core))
    # B8 (U2 §5, §8): rule 4 is generated from integrity.OWNERS; every owned pattern has its label there
    r4 = re.search(r"<!-- rule4:begin -->\n(.*?)\n<!-- rule4:end -->", run_md, re.S)
    owned = [p_ for p_, pre, _v in integrity.OWNERS if pre is not None]
    checks.append(("RUN.md's rule 4 is integrity.rule4_text() (generated from OWNERS, every owned pattern labelled, "
                   "the operator's own reader responses and notices named) "
                   f"{[p_ for p_ in owned if p_ not in integrity.OWNER_LABELS] or ''}",
                   r4 is not None and r4.group(1) == integrity.rule4_text()
                   and all(p_ in integrity.OWNER_LABELS for p_ in owned) and "UNLABELLED" not in r4.group(1)
                   and "KNOWN_FAULTS-<key>.md" in r4.group(1) and ".response[-k].md" in r4.group(1)))
    checks.append(("the fresh-reader check is a prompt and a step (for the sheet too)",
                   "fresh-reader" in prompt.EXTRA_PROMPTS
                   and re.search(r"--prompt\s+fresh-reader\s+--doc\s+signoff", rf("stage2-statements.md")) is not None
                   and re.search(r"--prompt\s+fresh-reader", rf("fresh-reader.md")) is not None))
    checks.append(("the intake asks the involvement question; RUN.md lists the stops that remain at every level",
                   "How involved do you want to be after the intake and Checkpoint A" in intake
                   and "You cannot change this choice once the run starts" in " ".join(intake.split())
                   and "**Stops that remain at every level.**" in core
                   and all(f"`{lvl}`" in run_md for lvl in project.INVOLVEMENT_LEVELS)))
    # B2 (U2 §5): the intake's stop-policy paragraph is generated (project.stop_policy_text): the stage 0
    # file carries the release one verbatim, the message sent carries the installation's
    checks.append(("the intake's stop policy paragraph equals project.stop_policy_text (stage0-intake.md: "
                   "release; the message sent: the installation's mode)",
                   " ".join(project.stop_policy_text("release").split()) in rf("stage0-intake.md")
                   and project.stop_policy_text(project.installed_mode() or "release") in intake))
    checks.append(("lanes are sealed in Stage 2 step 3, Stage 4 step 3, and in spawn-and-seal.md",
                   "lane_auth.py seal" in rf("stage2-statements.md") and "lane_auth.py seal" in rf("stage4-rounds.md")
                   and "lane_auth.py seal" in rf("spawn-and-seal.md")
                   and "3. **Seal and check the lanes.**" in rf("stage4-rounds.md")
                   and "**As each lane returns, seal it**" in rf("stage2-statements.md")))
    # integration 0.2: the bytecode check, and the Codex rules that must hold at every level
    checks.append(("Stage 1 checks PYTHONDONTWRITEBYTECODE for Claude Code and Codex",
                   "0. **No bytecode.**" in rf("stage1-setup.md") and "`.claude/settings.json`" in rf("stage1-setup.md")
                   and "[shell_environment_policy.set]" in rf("stage1-setup.md")))
    checks.append(("codex.md: approval prompts are not checkpoints; delegated runs do not wait at them",
                   "**Command approval prompts are not checkpoints.**" in rf("codex.md")
                   and "A delegating level must not wait at them" in rf("codex.md")
                   and "the ONLY sanctioned sandbox change" in rf("codex.md")))
    checks.append(("spawn-and-seal.md: tokens and seals apply at every involvement level",
                   "Token commitments, seals and lanecheck apply at every involvement level" in rf("spawn-and-seal.md")))
    checks.append(("spawn-and-seal.md: the Codex parent waits with a long blocking wait, not short polls",
                   "**Waiting for children.** Wait with the blocking `wait_agent` tool" in rf("spawn-and-seal.md")
                   and "at most once every 10 minutes" in rf("spawn-and-seal.md")))
    checks.append(("spawn-and-seal.md: a mechanical retry has a time budget, not a count (C22)",
                   "**Retry budget (time, not count).**" in rf("spawn-and-seal.md")
                   and "never becomes a human stop by itself" in rf("spawn-and-seal.md")))
    # B1b review (compat MED (c)): one rule for a child's capacity error / usage limit, in all three places
    cap = "**A child's capacity error or usage limit opens no stop.**"
    checks.append(("RUN.md, stops-and-set-asides.md and spawn-and-seal.md state one rule: a child's capacity "
                   "error or usage limit, waited out within the time budget, is logged, never a stop",
                   cap in core and cap in rf("stops-and-set-asides.md") and cap in rf("spawn-and-seal.md")))
    # small-paper run: the operator read REPORT.pdf three times, ~90% of its context (rule 13)
    page_reads = [f_ for f_ in run_files if re.search(r"\bread every page\b", rf(f_[4:]), re.I)]
    checks.append(("RUN.md keeps rule 13 (the operator reads no PDF; the renderer, verifier and checkers do), "
                   f"and no stage or procedure file tells the operator to read every page {page_reads or ''}",
                   "**Never read a PDF, or a whole large file or output, yourself.**" in core
                   and "the renderer, verifier and checkers do" in core and not page_reads))
    # B6 review fix 1: the paper-faithfulness lane Fails a missing-theory hypothesis a library or the project
    # already proves, and one the listing flags as restating a result (a small-paper run: a cited result a library already has)
    f13t = re.sub(r"\s+", " ", ap[ap.find("MISSING THEORY (F13)."):][:2500]) if "MISSING THEORY (F13)." in ap else ""
    checks.append(("AUDIT_PROTOCOL.md F13: a missing-theory hypothesis a library (or the project) already proves, "
                   "or one flagged as restating a result, is a Fail",
                   "a library (or the project) already proves it" in f13t
                   and "flags as restating another result or as a conclusion is a Fail" in f13t))
    # review of fix-mini1 (L3): "Documents a human reads" rule 6 names who reads a markdown
    # deliverable in full (the fresh reader), so it does not contradict rule 13
    r6 = re.search(r"^6\. \*\*Renders correctly\*\*.*?(?=^7\. )", ap, re.M | re.S)
    checks.append(("AUDIT_PROTOCOL.md rule 6 says the fresh reader, not the operator, reads a markdown "
                   "deliverable in full (RUN.md rule 13)",
                   bool(r6) and "read in full by\n   the fresh reader" in r6.group(0)))
    # trial #11 (approver's request, replacing fix-mini2 M2's rule that an ADOPT row's docstring fix gets its diff
    # round): a comment or docstring change never needs a round at any stage; Phase 0 still checks the approved
    # statements, and the documents say no lane re-read the new text
    checks.append(("stage5: a change to comments and docstrings only, ADOPT fix or not, needs no round "
                   "(NEXT[no-round]); Phase 0 still runs and the documents say no lane re-read it",
                   all(t_ in " ".join(rf("stage5-delivery.md").split()) for t_ in (
                       "**a change to comments and docstrings only**, at any stage", "NEXT[no-round]",
                       "No lane re-reads the new text", "run Phase 0 (it still checks that the approved statements "
                       "are unchanged)"))
                   and "NEXT[no-round]" in rf("stage4-rounds.md")
                   and "the diff round above runs on it" not in " ".join(rf("stage5-delivery.md").split())))
    # PDF-AGENTS: the PDFs are rendered by agents through render_record.py, before Checkpoint B and at delivery
    checks.append(("stage2 step 7 and stage5 step 5 render the PDFs by run/render-pdf.md and render_record.py; "
                   "no operator text names the removed render fix",
                   all("render-pdf.md" in rf(f_) and "render_record.py" in rf(f_)
                       for f_ in ("stage2-statements.md", "stage5-delivery.md"))
                   and not any("--render-fix" in t or "--pdf-check" in t
                               for t in [core] + [rf(f_[4:]) for f_ in run_files])))
    # integration review (fix 4): B10 moved the report's page-1 box into SUMMARY.pdf; no operator or lane text
    # may still send a reader to "page 1 of the report"
    stale = re.compile(r"(?i)page[- ]1 (?:box|of the report)|report's first page|page 1 of the\s+report")
    where = [n for n, t in [("RUN.md", run_md), ("AUDIT_PROTOCOL.md", ap)] + sorted(run_files.items())
             if stale.search(t)]
    checks.append((f"no document says the report's page 1 or its box (B10: the summary) {where or ''}", not where))
    # trial #10 audit: a 25-minute re-vote of an idle paper hypothesis, kept anyway (stay with the paper)
    b4 = re.sub(r"\s+", " ", ap)
    checks.append(("AUDIT_PROTOCOL.md B.4: rejecting an idle paper hypothesis's removal needs no re-vote (the rule "
                   "keeps the paper's hypothesis); a docstring sentence says it is unused",
                   "Neither does a substantiveness Fail whose only finding is an IDLE PAPER HYPOTHESIS" in b4
                   and "so a second look cannot change the outcome" in b4
                   and "not yet say the hypothesis is unused, ADOPT that docstring sentence" in b4))
    # approver 2026-10-24: release has exactly FOUR human stops, at every level -- (1) a goal result false or
    # unprovable, (2) an outward action not allowed, (3) something only the user can fix (another program that keeps
    # changing the project's files included), (4) a genuine ambiguity of the paper's meaning. The old fourth stop
    # ("a cure that keeps failing") is gone from every release text, and the four appear consistently
    checks += four_stops_checks(run_md, run_files, intake, ap, release_docs())
    # approver (2026-10-28), replacing DOC-FIX: after the mathematics is verified the main agent writes SUMMARY and
    # REPORT from the records and the Lean, four fresh reviewers advise, the agent judges (JUDGEMENT.md) and must fix
    # every overstatement; --deliver refuses only on the math gate and prints the rest as notes
    fr, s5 = rf("fresh-reader.md"), " ".join(rf("stage5-delivery.md").split())
    checks.append(("approver 2026-10-28: RUN.md, stage5 and fresh-reader.md give one delivery: the agent writes the "
                   "documents from a facts draft, four reviewers (claims, readability, decisions, trust) advise, the "
                   "agent judges each finding in JUDGEMENT.md and fixes every overstatement; only the math gate refuses",
                   "**The delivered documents**" in core and "except by the math gate" in " ".join(core.split())
                   and "**Not at delivery**" in fr
                   and "**The math gate**" in s5 and "facts/" in s5 and "JUDGEMENT.md" in s5
                   and all(f"- {k}:" in s5 for k in ("CLAIMS", "READABILITY", "DECISIONS", "TRUST"))
                   and "must** fix every overstatement" in s5 and "notes for the main agent (not blocking)" in s5
                   and "## Delivery reviewer prompt" in s5 and "hand-edit --finding" not in s5
                   and "status-check --write" not in s5))
    texts = dict(run_files, **{"RUN.md": run_md, "AUDIT_PROTOCOL.md": ap})
    dang = dangling_refs(texts, code_sources())
    checks.append(("RUN.md, the stage and procedure files and AUDIT_PROTOCOL.md name only scripts, flags (of the "
                   f"script named), failure codes and cause codes the code has {dang or ''}", not dang))
    names = lane_record_names(ap)
    checks.append(("no lane prompt names an audit-record file outside common rule 3 (which names them to "
                   f"forbid reading them) {({l: n for l, n in names.items() if n}) or ''}",
                   all(n == [] for n in names.values())))
    return checks


# release text that must not keep the old fourth stop, and must name the four (README, INSTALL, MAINTAINING, the
# Codex notes: outside audits/, read only in the clone -- in an installed project those names are the user's files)
OLD_STOP4 = re.compile(r"(?i)cure\s+(?:that\s+)?keeps\s+failing|keeps\s+failing\s+past|fourth\s+release\s+stop|"
                       r"stop\s+4\W{1,3}\s*a\s+cure|stop\s+4\s+\(the\s+human|a\s+cure\s+that\s+keeps")
STOP_WORDS = {1: r"goal result", 2: r"(?:outward|push)", 3: r"only (?:you|the human|the user|a person) can (?:fix|provide)"
              r"|something only (?:you|the human|a person)|what only you can provide",
              4: r"genuine(?:ly)? ambigu"}


def in_clone(top=None):
    """True iff audits/ sits in the formalize-paper repository itself (install.sh beside it, as tier.py and
    upgrade.py detect the clone). In an installed project the files beside audits/ are the USER's: their
    README.md is their project's, not formalize-paper's (tier 1, 2026-10-25: every fresh install failed here)."""
    top = os.path.dirname(AUDITS) if top is None else top
    return os.path.isfile(os.path.join(top, "install.sh")) and os.path.isfile(os.path.join(top, "INSTALL.md"))


def release_docs(top=None):
    """{name: text} of the release documents outside audits/ (README.md, INSTALL.md, MAINTAINING.md,
    codex/README.md), those present -- read only in the formalize-paper clone, {} in an installed project."""
    top = os.path.dirname(AUDITS) if top is None else top
    out = {}
    if not in_clone(top):
        return out
    for n in ("README.md", "INSTALL.md", "MAINTAINING.md", "codex/README.md"):
        try:
            out[n] = open(os.path.join(top, n), encoding="utf-8").read()
        except OSError:
            pass
    return out


def four_stops_checks(run_md, run_files, intake, ap, docs):
    """[(name, ok)]: no release text keeps the old fourth stop; the four stops appear consistently -- the code's
    table (project.RELEASE_STOPS, the human codes of RELEASE, the stop policy text), RUN.md's release paragraph,
    the stops procedure, the statement stage's round-cap routes, the intake and the top-level docs."""
    out = []
    texts = dict(run_files, **{"RUN.md": run_md, "AUDIT_PROTOCOL.md": ap, "intake": intake}, **docs)
    texts["stop_policy_text"] = "\n".join(project.stop_policy_text(m) for m in project.MODES) + "\n".join(
        project.stop_policy_text(m, lv) for m in project.MODES for lv in project.INVOLVEMENT_LEVELS)
    texts["mode_line"] = project.mode_line({"mode": "release"})
    old = sorted(n for n, t in texts.items() if OLD_STOP4.search(" ".join(t.split())))
    out.append((f"no release text keeps the old fourth stop ('a cure that keeps failing') {old or ''}", not old))
    codes = set(getattr(project, "RELEASE_STOP_CODES", ()))
    human = {c for c, (_cl, k) in project.RELEASE.items() if k == "human"}
    out.append(("the code has exactly four release stops (project.RELEASE_STOPS 1-4; STOP_POLICY_STOPS), and the human "
                "codes of RELEASE are exactly theirs", sorted(getattr(project, "RELEASE_STOPS", {})) == [1, 2, 3, 4]
                and len(project.STOP_POLICY_STOPS) == 4 and codes == human and "ambiguity" in codes))
    core = " ".join(run_md.split())
    m = re.search(r"\*\*In `release` mode exactly four of these stop the run, at every level\*\*(.*?)Every other stop", core)
    para = m.group(1) if m else ""
    miss = sorted(c for c in codes if f"`{c}`" not in para)
    out.append((f"RUN.md's release paragraph numbers the four stops (1)-(4) and names each stop's codes {miss or ''}",
                bool(m) and not miss and all(f"**({i})**" in para for i in (1, 2, 3, 4))
                and "tool-patch route" in para and "round-cap" in para))
    sp = " ".join(run_files.get("run/stops-and-set-asides.md", "").split())
    miss = sorted(c for c in codes if f"`{c}`" not in sp)
    out.append((f"stops-and-set-asides.md names the four stops' codes and the classification of a spent budget "
                f"{miss or ''}", not miss and "stops.py classify" in sp and "(4: a genuine ambiguity" in sp))
    st2 = " ".join(run_files.get("run/stage2-statements.md", "").split())
    out.append(("stage2-statements.md routes the release round cap three ways: (a) stop 4 (--cause ambiguity, hands-off "
                "included), (b) a reading choice, (c) 'not established: open faithfulness finding'",
                "--cause ambiguity" in st2 and "(a) the paper's meaning is genuinely ambiguous" in st2
                and "`hands-off` included" in st2 and "(b) a loose or inconsistent convention" in st2
                and "(c) anything else" in st2 and "not established: open faithfulness finding" in st2))
    bad = []
    for n in ("intake", "README.md", "INSTALL.md", "MAINTAINING.md"):
        t = " ".join(texts.get(n, "").split())
        if n not in texts and n != "intake":
            continue
        if not all(re.search(w, t, re.I) for w in STOP_WORDS.values()) or not re.search(
                r"another program that keeps changing the project's files", t):
            bad.append(n)
    out.append((f"the intake, README, INSTALL and MAINTAINING each name the four stops (another program changing the "
                f"files under stop 3; a genuine ambiguity as stop 4) {bad or ''}", not bad))
    return out


def _installed_readme_ignored():
    """A scratch project holding only a user's README.md and an audits/ directory: release_docs() reads nothing,
    while the same files with install.sh and INSTALL.md beside them are read (the clone)."""
    import shutil, tempfile
    t = tempfile.mkdtemp(prefix="doclint-")
    try:
        open(os.path.join(t, "README.md"), "w").write("# my Lean project\n")
        os.makedirs(os.path.join(t, "audits"))
        installed = release_docs(t)
        for f_ in ("install.sh", "INSTALL.md"):
            open(os.path.join(t, f_), "w").write("x\n")
        clone = release_docs(t)
        return installed == {} and set(clone) == {"README.md", "INSTALL.md"}
    finally:
        shutil.rmtree(t, ignore_errors=True)


def _unlabelled_control(run_md, run_files, on_disk, intake, ap):
    """lint() with one more owned pattern in integrity.OWNERS that has no label, RUN.md's rule 4 regenerated."""
    keep = list(integrity.OWNERS)
    try:
        integrity.OWNERS.append(("newrecord/*", "newrecord ", ()))
        r4 = "<!-- rule4:begin -->\n" + integrity.rule4_text() + "\n<!-- rule4:end -->"
        md = re.sub(r"<!-- rule4:begin -->\n.*?\n<!-- rule4:end -->", lambda _m: r4, run_md, flags=re.S)
        return lint(md, run_files, on_disk, intake, ap)
    finally:
        integrity.OWNERS[:] = keep


def main(argv):
    if any(a not in ("--selftest",) for a in argv):
        print("usage: doclint.py [--selftest]")
        return 2
    docs = load()
    checks = lint(*docs)
    checks.append(("an installed project's own README.md (no install.sh beside audits/) is not read as a release "
                   "document; the clone's are", _installed_readme_ignored()))
    # negative controls: a damaged copy of each kind of document must fail
    run_md, run_files, on_disk, intake, ap = docs
    lane_b = prompt.blocks_after(ap, "### Lane B") or "\x00 no lane B block"
    controls = [
        ("control: a stage file missing from RUN.md's stage map fails",
         lint(run_md.replace("`run/stage3-proofs.md`", "`run/x.md`"), run_files, on_disk, intake, ap)),
        ("control: a record file named in a lane block fails",
         lint(run_md, run_files, on_disk, intake, ap.replace(lane_b, lane_b + "\nrecord it in ADOPTED.md", 1))),
        ("control: a stale release column (a code moved to another kind by hand) fails",
         lint(run_md.replace("| human | `codex-approval`, ", "| human | ", 1).replace("| rerun | ", "| rerun | `codex-approval`, ", 1),
              run_files, on_disk, intake, ap)),
        ("control: a rule 4 that lost an owned record (stale against OWNERS) fails",
         lint(run_md.replace("   - `pin`: `TOOLING_PIN.json`;\n", "", 1), run_files, on_disk, intake, ap)),
        ("control: a record added to integrity.OWNERS without a label fails (RUN.md regenerated to match)",
         _unlabelled_control(run_md, run_files, on_disk, intake, ap)),
        ("control: a stage 0 file whose stop policy paragraph lost a stop fails",
         lint(run_md, dict(run_files, **{"run/stage0-intake.md": run_files["run/stage0-intake.md"].replace(
             "    that you did not allow here; ", "    that ", 1)}), on_disk, intake, ap)),
        ("control: an intake message whose stop policy paragraph lost a stop fails",
         lint(run_md, run_files, on_disk, intake.replace("    that you did not allow here; ", "    that ", 1), ap)),
        ("control: a stage file that still says 'page 1 of the report' fails",
         lint(run_md, dict(run_files, **{"run/stage0-intake.md": run_files["run/stage0-intake.md"] + "\npage 1 of the report\n"}),
              on_disk, intake, ap)),
        ("control: a flag a script does not have, a failure code and a cause code no script has fail",
         [(n, ok) for n, ok in lint(run_md + "\n`python3 audits/stops.py close --stop S1 --bogus-flag` FAIL[zz-not-a-code] "
                                    "`--cause zz-not-a-cause`\n", run_files, on_disk, intake, ap) if "name only scripts" in n]),
        ("control: a release text that still says 'a cure that keeps failing' fails (approver 2026-10-24)",
         four_stops_checks(run_md, dict(run_files, **{"run/stage4-rounds.md": run_files["run/stage4-rounds.md"]
                                                      + "\nstop 4 is a cure that keeps failing\n"}), intake, ap,
                           release_docs())),
        ("control: an INSTALL.md that lost the ambiguity stop fails",
         four_stops_checks(run_md, run_files, intake, ap, dict(release_docs(), **{"INSTALL.md": re.sub(
             r"(?i)genuine(ly)? ambigu", "x", release_docs().get("INSTALL.md", "genuine ambiguity"))}))),
        ("control: a RUN.md release paragraph that lost a stop's code fails",
         four_stops_checks(run_md.replace("`interference`) -- but first", ") -- but first", 1), run_files, intake, ap,
                           release_docs())),
        ("control: an AUDIT_PROTOCOL.md without B.4's idle-paper-hypothesis exception fails",
         lint(run_md, run_files, on_disk, intake, ap.replace("IDLE PAPER HYPOTHESIS", "IDLE HYPOTHESIS", 1))),
        ("control: the same name inside common rule 3 passes",
         lint(run_md, run_files, on_disk, intake, ap.replace(RULE3_START, RULE3_START + " (ADOPTED.md)", 1))),
    ]
    for name, res in controls:
        failed = [n for n, ok in res if not ok]
        checks.append((name, failed == [] if "passes" in name else bool(failed)))
    for n, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    ok = all(c for _, c in checks)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

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
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402  (RESULT_KINDS lives there, once)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# What the report does and does not certify. One sentence, used in both renderings, so the
# Markdown and the PDF cannot disagree about it.
LIMITS_MD = ("**What this does not certify:** every Lean proof is checked by the Lean kernel, and "
             "the statements were reviewed by independent AI reviewers (coverage in the trust "
             "section), but nothing checks that a Lean proof follows the paper's argument. The "
             "entries below are the route changes that were recorded; a change nobody recorded is "
             "not listed.")
LIMITS_TEX = ("\\textbf{What this does not certify:} every Lean proof is checked by the Lean "
              "kernel, and the statements were reviewed by independent AI reviewers (coverage in "
              "the trust section), but nothing checks that a Lean proof follows the paper's "
              "argument. The entries below are the route changes that were recorded; a change "
              "nobody recorded is not listed.")


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
    ap_ = os.path.join(REPO, cfg["rounds_dir"], "APPROVED_FINGERPRINTS.json")
    if lvl == "statements-only" and os.path.exists(ap_):
        try:
            by_ = json.load(open(ap_)).get("by")
        except ValueError:
            by_ = None
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


def trust_rows(cfg):
    """[(layer, what it establishes, status)] -- the report's statement of how far to trust it,
    computed from the records rather than written. EconCSLib's lesson: keep the evidence axes
    apart, and disclose a zero (no human review) rather than leave it out."""
    import audit_coverage as ac
    rd = os.path.join(REPO, cfg["rounds_dir"])
    head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short=11", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    rows = [("Lean kernel",
             "every proof is valid; no sorry, no axiom beyond the standard three (axiom sweep)",
             f"Phase 0 green at commit {head} (this report is regenerated only by a green Phase 0)")]
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
            fail_txt = fail_breakdown(dec, decision_words(rd))
            rows.append((f"AI reviewer: {lane}", ac_LANE_WHAT.get(lane, ""),
                         f"{last.count('Pass')} of {n} items passed; "
                         f"{fail_txt}; {last.count('Ambiguous')} ambiguous; "
                         f"{last.count('NotDoneYet')} not examined; "
                         f"{sum(1 for k in stale_keys if k[0] == lane)} stale"))
    appr = os.path.join(rd, "APPROVED_FINGERPRINTS.json")
    if os.path.exists(appr):
        a = json.load(open(appr))
        st = [r.get("status") for r in a.get("rows", {}).values()]
        how = {"individual": "result by result", "blanket": "as a blanket 'all OK'"}.get(a.get("how"), "manner not recorded")
        by = a.get("by")
        # Say who decided, in words a reader cannot misread (RUN.md Stage 2 step 8).
        est, who = {
            "human": ("a mathematician read the sign-off sheet and approved the statements; the "
                      "freeze check (Phase 0) proves none has changed since",
                      "approved by a human"),
            "agent": ("NOT reviewed by a human: at Checkpoint B the user chose to let the agent "
                      "approve the sign-off sheet without reading it. The freeze check (Phase 0) "
                      "proves the statements have not changed since",
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
                       "proves the statements have not changed since")
            if dl and dl[0] == "hands-off":
                # the human chose this at intake, not at Checkpoint B: say which, and quote it
                est = (f"NOT reviewed by a human: the agent approved the sign-off sheet without anyone "
                       f"reading it, under the {dl[0]} involvement level the user chose at intake "
                       f"(answer: \"{dl[1]}\"). The freeze check (Phase 0) proves the statements have "
                       f"not changed since")
        note = f"; note: {a['note']}" if a.get("note") else ""
        # Earlier approvals, moved aside at a re-approval (RUN.md "Re-approval"): a human
        # re-approving only the CHANGED results after an agent approval must not make the whole
        # sheet read as human-reviewed.
        hist = []
        for f in sorted(glob.glob(os.path.join(rd, "APPROVED_FINGERPRINTS.*.json"))):
            try:
                h = json.load(open(f))
            except ValueError:
                continue
            hist.append(f"{h.get('date', '?')} by {h.get('by') or 'approver not recorded'}")
        if hist:
            note += "; earlier approvals: " + ", ".join(hist)
        rows.append(("Approval of statements", est,
                     (f"{who}: {st.count('approved')} of {len(st)} results approved {how}, "
                      f"{st.count('excluded')} excluded, on {a.get('date', '?')} at commit "
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
                      f"level (answer, verbatim: \"{ans}\"). {DELEGATED_WHO[lvl]}. " if lvl in DELEGATED_WHO
                      else f"INCONSISTENT: the involvement level is {lvl!r}, yet ")
                     + f"The operator took {len(dd)} decision(s) on the reader's behalf, each final; "
                       f"each one's reversal cost (none, re-prove, re-approve or new round) and how to "
                       f"reverse it are in "
                       f"`{os.path.join(rd, 'DECISIONS.md')}` and tagged [DELEGATED] in "
                       f"`{os.path.join(rd, 'RUN_LOG.md')}`"
                     + (": " + "; ".join(t[:200] for t in dd) if dd else ".")))
    pin_p = os.path.join(rd, "TOOLING_PIN.json")
    if os.path.exists(pin_p):
        reps = json.load(open(pin_p)).get("repins", [])
        rows.append(("Audit apparatus", "the scripts, prompts and reviewer definition were frozen "
                     "for the run (integrity check)",
                     "unchanged since the pin" if not reps else
                     f"RE-PINNED {len(reps)} time(s) during the run: "
                     + "; ".join(f"{r['date']}: {r['reason']}" for r in reps)))
    rows.append(reissue_row(cfg))
    rows.append(("Proof routes", "the Lean proof follows the paper's argument",
                 "NOT CERTIFIED by anything; route changes listed are those recorded"))
    # Changes committed after the last audit round were never examined by a reviewer (RUN.md
    # Stage 5: the post-full diff round may itself adopt fixes). Say so, with the commits.
    row = later_row(cfg)
    if row:
        rows.append(row)
    return rows


def reissue_row(cfg):
    """Every reissued lane of every round (lane_auth.py reissue: a lane whose spawn line was lost
    before it was sealed), with its reason and the earlier verdict kept as evidence. A reissue is
    the one way a lane's first answer can be set aside, so the reader is told about each."""
    import lane_auth
    items = []
    for r in project.rounds(cfg):
        for h, lane, reason, files in lane_auth.reissues(r):
            items.append(f"{os.path.basename(r)}: {lane} (commit {h[:11]}): {reason}; earlier verdict "
                         + (", ".join(f"`{f}`" for f in files) if files else "NONE (no verdict file existed)"))
    return ("Lane reissues", "each lane answered once, under the token it was spawned with",
            "none" if not items else f"{len(items)} lane(s) REISSUED (spawn line lost before sealing): "
            + "; ".join(items))


# QUESTION: whether the human answered each one is recorded per item in the decisions document,
# not here; the report never infers "answered" or "not yet answered" (it once said "not yet
# answered" for 45 questions the human had answered)
DECISION_WORDS = {"ADOPT": "adopted", "REJECT": "rejected", "DEFER": "deferred",
                  "QUESTION": "put to the human as questions",
                  "UNCOVERED": "left uncovered, with no decision"}


def decision_words(rd):
    """DECISION_WORDS, pointing QUESTION to the decisions document when the record has one."""
    words = dict(DECISION_WORDS)
    dpath = os.path.join(rd, "DECISIONS.md")
    if os.path.exists(dpath):
        words["QUESTION"] += f" (the decisions put to the human: `{dpath}`)"
    return words


def rolled_decisions(rd):
    """{"lane :: item": decision} across rounds, later rounds winning -- except that UNCOVERED, a
    coverage status rather than a decision, never replaces a decision."""
    import audit_coverage as ac
    decided = {}
    for d in ac.order_rounds([x for x in glob.glob(os.path.join(rd, "*")) if os.path.isdir(x)],
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
    import audit_coverage as ac
    c = project.changes_after_last_audit(cfg, ac.order_rounds(project.rounds(cfg), REPO))
    if c is None:
        return None
    what = "every Lean change was examined by at least one audit round"
    name = "Changes after the last audit round"
    where = f"last audit round {c['round']} (commit {c['commit']})"
    if c["problem"]:
        return (name, what, f"UNKNOWN: {c['problem']}")
    parts = []
    if c["commits"]:
        parts.append(f"{len(c['commits'])} commit(s) since {where} NOT re-audited (checked only by "
                     "Phase 0): " + "; ".join(c["commits"]))
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
RESULT = re.compile(rf"^({project.RESULT_KINDS_RE})\s+[\d.]+", re.I)
NOT_FORMALIZED = re.compile(r"not formalized|no new statement|deferred|out of scope", re.I)


def load_project(name):
    p = os.path.join(HERE, "projects", f"{name}.json")
    if not os.path.exists(p):
        sys.exit(f"FAIL: no project config at {p}")
    return json.load(open(p, encoding="utf-8"))


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


def table_rows(path, first_col_is=None):
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



# --------------------------------------------------------------------------------------------
# LaTeX output.
#
# WHY NOT JUST SHIP THE MARKDOWN. The sources hold cells of 400+ characters -- "what it would
# take to lift this skip" is a paragraph, not a table cell -- and a markdown table with a
# 400-character cell renders as an unreadable smear of pipes. That was shipped once and shown to
# someone before anyone looked at the rendering rather than the source.
#
# So the long-form sections are NOT tables here. Each entry becomes a titled block with labelled
# fields, which is what the content actually is. Only section 1, paper reference -> Lean name, is
# genuinely tabular, and it uses a longtable with fixed p{} widths so it wraps and breaks pages.
TEX_ESC = [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
           ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
           ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
           # a straight ' is a prime in this material (i'', L'_3): TeX would curl it and fuse ''
           # into a closing double quote, which garbled the hd/vd formula on a test run's sheet
           ("'", r"\textquotesingle{}")]

# Mathematical characters rendered as LaTeX math rather than as font glyphs. Two of these --
# U+2113 SCRIPT SMALL L and U+2AB0 SUCCEEDS-OR-EQUALS -- are simply absent from DejaVu Serif and
# came out as tofu boxes in the first PDF, in the middle of sentences like "for all even ? <= 2k".
# Mapping the whole class to math mode fixes those and typesets the rest properly besides, which
# is what a mathematical document wants anyway. Checked against the font's cmap, not guessed.
UNI_MATH = {
    "ℓ": r"\ell", "⪰": r"\succeq", "⊆": r"\subseteq", "⊂": r"\subset", "⊔": r"\sqcup",
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "→": r"\to", "⟹": r"\implies",
    "∈": r"\in", "∀": r"\forall", "∃": r"\exists", "∑": r"\sum", "∏": r"\prod",
    "×": r"\times", "·": r"\cdot", "−": "-", "²": "^2", "³": "^3",
    "₀": "_0", "₁": "_1", "₂": "_2", "₃": "_3", "₄": "_4", "₅": "_5",
    "₆": "_6", "₇": "_7", "₈": "_8", "₉": "_9", "ᶜ": r"^{c}",
    # absent from DejaVu Serif (dropped silently from a test run's sheet): set as math
    "∅": r"\emptyset", "⋃": r"\bigcup", "⋂": r"\bigcap", "𝒫": r"\mathcal{P}",
    "𝒞": r"\mathcal{C}", "𝒜": r"\mathcal{A}", "ℬ": r"\mathcal{B}", "ℱ": r"\mathcal{F}",
    # absent from DejaVu Serif (a later sign-off sheet, 2026-10-13): subscript n, midline ellipsis
    "ₙ": "_n", "⋯": r"\cdots",
}
# The Mathematical Alphanumeric Symbols block (𝒫, 𝔓, ℕ-like 𝕂, 𝐀 ...) is mostly absent from the
# font; map every letter of it to the matching LaTeX font command, by its Unicode name, rather than
# one letter at a time as each paper happens to use one (𝔓 reached a test run's sheet after 𝒫).
import unicodedata as _ud
_STYLES = [("BOLD SCRIPT", r"\mathcal"), ("SCRIPT", r"\mathcal"), ("BOLD FRAKTUR", r"\mathfrak"),
           ("FRAKTUR", r"\mathfrak"), ("DOUBLE-STRUCK", r"\mathbb"), ("BOLD", r"\mathbf")]
for _cp in list(range(0x1D400, 0x1D6A4)) + [0x210A, 0x210B, 0x2110, 0x2112, 0x211B, 0x212C,
                                            0x2130, 0x2131, 0x2133, 0x212D, 0x210C, 0x2111,
                                            0x211C, 0x2128, 0x2102, 0x210D, 0x2115, 0x2119,
                                            0x211A, 0x211D, 0x2124]:
    _nm = _ud.name(chr(_cp), "")
    _m = re.match(r"(?:MATHEMATICAL |)(.*?) ?(CAPITAL|SMALL) ([A-Z])$", _nm.replace("BLACK-LETTER", "FRAKTUR"))
    if not _m:
        continue
    _cmd = next((c for st, c in _STYLES if _m.group(1).endswith(st)), None)
    # \mathcal and \mathbb have capitals only; lowercase script/double-struck stay unmapped
    if _cmd and (_m.group(2) == "CAPITAL" or _cmd not in (r"\mathcal", r"\mathbb")):
        _letter = _m.group(3) if _m.group(2) == "CAPITAL" else _m.group(3).lower()
        UNI_MATH.setdefault(chr(_cp), _cmd + "{" + _letter + "}")
# Every other math symbol DejaVu Serif lacks, with its unicode-math command, kept only if the command
# compiles with amsmath+amssymb (generated once by tests/gen_uni_math_extra.py; ∖ was the first to
# reach a report -- mapping symbols one at a time as each paper uses one does not scale).
_extra = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uni_math_extra.json")
if os.path.exists(_extra):
    for _c, _v in json.load(open(_extra, encoding="utf-8")).items():
        UNI_MATH.setdefault(_c, _v)
# Greek letters: DejaVu has them in text, but once a math run has started (x∈σ…) they reach the
# math font, which has none -- so they are always set as math commands.
UNI_MATH.update({c: "\\" + n for c, n in zip(
    "αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ",
    "alpha beta gamma delta varepsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma "
    "tau upsilon varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega".split())})


def missing_glyphs(log_path):
    """Characters xelatex dropped because the font has no glyph for them. It does not fail on
    these: it writes a PDF with holes, which is how "the class \u2019 assumes" reached a sheet."""
    if not os.path.exists(log_path):
        return []
    text = open(log_path, encoding="utf-8", errors="replace").read()
    return sorted(set(re.findall(r"Missing character: There is no (\S+)", text)))


_TEX_ESC_MAP = dict(TEX_ESC)
_TEX_ESC_RE = re.compile("|".join(re.escape(a) for a, _ in TEX_ESC))


def tex_escape(s):
    """Escape LaTeX specials in ONE pass. Applying TEX_ESC as successive replacements escaped the
    braces of the `\\textbackslash{}` it had just inserted, so every backslash in pasted LaTeX
    printed as "\\{}" (a latent bug; a test run's fallback paper text showed it)."""
    return _TEX_ESC_RE.sub(lambda m: _TEX_ESC_MAP[m.group(0)], s)


def _mathify(part):
    """Wrap runs of mathematical characters in math mode, leaving prose alone."""
    out, i = "", 0
    while i < len(part):
        if part[i] in UNI_MATH:
            j = i
            buf = ""
            while j < len(part) and (part[j] in UNI_MATH or (buf and part[j].isalnum())):
                nxt = UNI_MATH.get(part[j], part[j])
                # a control word swallows a following letter: "k×l" must not become "\timesl"
                # (undefined; it broke a test run's sign-off PDF)
                if re.search(r"\\[A-Za-z]+$", buf) and nxt[:1].isalnum():
                    buf += " "
                buf += nxt
                j += 1
            out += "$" + buf + "$"
            i = j
        else:
            out += part[i]
            i += 1
    return out


SCRIPT_RE = re.compile(r"(?<![\w\\/])([A-Za-zℓφψσπ<])_(\{([^{}\n]*)\}|([A-Za-z0-9])(?![\w{]|\.lean))"
                       r"(\^(?:\{([^{}\n]*)\}|([A-Za-z0-9])(?![\w{]))|)")


def tex(s):
    """Escape a markdown cell for LaTeX, keeping `code`, **bold** and *emph*.

    Code spans are pulled out FIRST and replaced by placeholders, so that emphasis spanning a
    code span still converts. The earlier version split on backticks and ran the bold regex on
    each fragment separately, so `**Lemma 6.2, the inclusion `Q_U`.**` reached the PDF with its
    asterisks intact -- visible in the first render, three lines from the top of a section.
    """
    s = str(s)
    spans = []

    def stash(m):
        spans.append(m.group(1))
        return "\0%d\0" % (len(spans) - 1)

    s = re.sub(r"`([^`]*)`", stash, s)
    # Records write sub/superscripts in LaTeX style (x_{s+2}, L_{s+1}^B, t_P). Escaped, they
    # printed literally in the report; set them as real sub/superscripts. Only a single-letter base
    # not glued to a word: AUTHOR_NOTES or lemma_4_9 outside a code span stay as they are.
    subs = []

    def script(m):
        def part(braced, single):
            t = braced if braced is not None else single
            return _mathify(tex_escape(t))
        out = m.group(1) + "\\textsubscript{" + part(m.group(3), m.group(4)) + "}"
        if m.group(5):
            out += "\\textsuperscript{" + part(m.group(6), m.group(7)) + "}"
        subs.append(out)
        return "\x01%d\x01" % (len(subs) - 1)

    s = SCRIPT_RE.sub(script, s)
    # a word with a Greek subscript is notation too (height_φ, hd_φ)
    s = re.sub(r"(?<![\w\\])([A-Za-z]+)_([φψσπ])(?!\w)",
               lambda m: (subs.append(m.group(1) + "\\textsubscript{" + _mathify(m.group(2)) + "}"),
                          "\x01%d\x01" % (len(subs) - 1))[1], s)
    # straight double quotes: opening and closing (TeX would print ” for both)
    s = re.sub(r'"([^"\n]*)"', "“\\1”", s)
    s = tex_escape(s)
    s = s.replace("--", "-{}-")          # TeX would print an en dash for a command-line flag
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s, flags=re.S)
    s = re.sub(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)", r"\\emph{\1}", s, flags=re.S)
    s = _mathify(s)
    # Break points in prose too: record paths (round/lane.probes/file.lean) and File.lean:N cites
    # outside code spans could not wrap and were clipped at the right margin of the PDF.
    s = re.sub(r"[^\s{}$()]*/[^\s{}$()]*", lambda m: m.group(0) if len(m.group(0)) < 25 else
               m.group(0).replace("/", "/\\allowbreak{}").replace("\\_", "\\_\\allowbreak{}"), s)
    s = re.sub(r"(\w)\.lean:(\d)", r"\1.lean:\\allowbreak{}\2", s)
    for k, sub in enumerate(subs):
        s = s.replace("\x01%d\x01" % k, sub)
    for k, code in enumerate(spans):
        code = tex_escape(code)
        # Break points inside \texttt. Only hyphens were breakable, so a path like
        # Paper/Lemma62.lean:59 could not wrap and ran straight through the next
        # column of a table -- visible only in the PDF, which is why the PDF gets read.
        for ch in ("/", ".", "_", ":", "-"):
            code = code.replace(ch, ch + "\\allowbreak{}")
        code = mono_safe(code, _GLYPH_WARN)
        s = s.replace("\0%d\0" % k, r"\texttt{" + code + "}")
    return s


def notes_tex(md):
    """READER_NOTES.md (formalizer-owned prose: ### headings, paragraphs, "- " bullets) to LaTeX.
    The reader of the PDF must get the same notes as the reader of the markdown."""
    out, items, para = [], [], []

    def flush():
        if para:
            out.append(tex(" ".join(para)) + "\n")
            para.clear()
        if items:
            out.append("\\begin{itemize}[leftmargin=1.2em,itemsep=2pt]\n"
                       + "".join("\\item " + tex(i) + "\n" for i in items) + "\\end{itemize}\n")
            items.clear()

    for line in md.splitlines():
        st = line.strip()
        if st.startswith("#### ") or st.startswith("### "):
            flush()
            out.append("\\subsection*{" + tex(st.lstrip("#").strip()) + "}\n")
        elif st.startswith("- "):
            if para:
                flush()
            items.append(st[2:])
        elif line.startswith("  ") and items:
            items[-1] += " " + st
        elif not st:
            flush()
        else:
            if items:
                flush()
            para.append(st)
    flush()
    return "\n".join(out)


def split_title(cell):
    """A source cell often leads with a bold title then explains. Use the bold part as the
    heading and demote the rest, rather than setting a 300-character sentence in bold."""
    m = re.match(r"\s*\*\*(.+?)\*\*\s*(.*)$", str(cell), re.S)
    if m:
        # "**Title**: rest" must not leave the rest starting with a stray colon
        return m.group(1).strip().rstrip(".:"), m.group(2).strip().lstrip(":;,.— ").strip()
    return str(cell).strip(), ""



# Glyph coverage, checked against the actual font rather than assumed.
#
# The first PDF had tofu boxes mid-sentence -- "for all even <box> <= 2k" -- because DejaVu Serif
# and DejaVu Sans Mono both lack U+2113 SCRIPT SMALL L, and nothing said so. Prose characters are
# handled by UNI_MATH above; inside a code span that is not available, because \ell inside
# \texttt would print literally. So any character the mono font does not have is wrapped in a
# fallback family that does.
#
# Detected, not hardcoded: a character added to a source tomorrow gets the same treatment, and
# one that NEITHER font has is reported instead of silently rendering as a box.
# Font FILES, named exactly. A prefix match was tried first and silently picked
# DejaVuSans-Bold.ttf when asked for DejaVu Sans Mono -- and DejaVuSans-Bold HAS the two glyphs
# the mono font lacks, so the coverage check reported success while the PDF kept rendering boxes.
# A lookup that resolves to the wrong object and returns a confident answer is worse than one
# that fails, so an unfound file now raises instead of falling back to something close.
MONO_FILE = "DejaVuSansMono.ttf"
FALLBACK_FILE = "FreeMono.ttf"
_CMAP_CACHE = {}
_GLYPH_WARN = []


def _font_cmap(filename):
    if filename in _CMAP_CACHE:
        return _CMAP_CACHE[filename]
    cmap = None
    try:
        from fontTools.ttLib import TTFont
        import glob as _g
        hits = [f for f in _g.glob("/usr/share/fonts/**/*.ttf", recursive=True)
                if os.path.basename(f) == filename]
        if not hits:
            _GLYPH_WARN.append(f"! font file {filename} not found; glyph coverage unchecked")
        else:
            cmap = set()
            for t in TTFont(sorted(hits)[0], fontNumber=0)["cmap"].tables:
                cmap |= set(t.cmap.keys())
    except ImportError:
        pass                    # fontTools absent: no coverage check available
    _CMAP_CACHE[filename] = cmap
    return cmap


def mono_safe(text, warn):
    """Wrap characters the mono font lacks in the fallback family; warn if neither has them."""
    main, fb = _font_cmap(MONO_FILE), _font_cmap(FALLBACK_FILE)
    if main is None:
        return text
    out = ""
    for ch in text:
        if ord(ch) < 128 or ord(ch) in main:
            out += ch
        elif fb is not None and ord(ch) in fb:
            out += r"{\fallbackmono " + ch + "}"
        else:
            warn.append(f"! no font has U+{ord(ch):04X} ({ch!r}); it will render as a box")
            out += ch
    return out


PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.4cm]{geometry}
\usepackage{amsmath,amssymb}  % UNI_MATH maps to \implies, \succeq, \sqcup ...
\usepackage{fontspec}
\setmainfont{DejaVu Serif}[Scale=0.92]
\setsansfont{DejaVu Sans}[Scale=0.92]
\setmonofont{DejaVu Sans Mono}[Scale=0.80]
\newfontfamily\fallbackmono{FreeMono}[Scale=0.80]
\usepackage{longtable,booktabs,array,ragged2e}
\usepackage[table]{xcolor}
\usepackage{enumitem}
\usepackage[most]{tcolorbox}
\usepackage[hidelinks]{hyperref}
\usepackage{titlesec}
\titleformat{\section}{\Large\bfseries\sffamily}{\thesection.}{0.6em}{}
\titleformat{\subsection}{\normalsize\bfseries\sffamily}{}{0em}{}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.45em}
\newcolumntype{L}[1]{>{\RaggedRight\arraybackslash}p{#1}}
\renewcommand{\arraystretch}{1.25}
\begin{document}
"""


def render_entry(title, fields):
    """One long-form entry: a bold title, then labelled paragraphs. Never a table row."""
    out = "\\subsection*{" + title + "}\n\\begin{description}[leftmargin=!,labelwidth=4.6cm,style=nextline,font=\\normalfont\\itshape]\n"
    for label, value in fields:
        if value and value.strip():
            out += "\\item[" + label + "] " + value + "\n"
    return out + "\\end{description}\n"


def record_table(path, keycol):
    """(header, rows) of the first table in `path` whose header has a column starting `keycol`."""
    if not os.path.exists(path):
        return [], []
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
        if header is not None:
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
    try:
        import audit_coverage
        rs = audit_coverage.order_rounds(rs, REPO)
    except Exception:
        pass
    return decisions.open_question_rows(cfg, rs) if rs else []


QUESTIONS_INTRO = ("Every question the adjudicator put to the human (a QUESTION row of any round's "
                   "adjudication) that has no final answer yet, oldest round first. Answered ones are "
                   "not repeated here: they are in `DECISIONS.md` and in `RUN_LOG.md` under "
                   "`## Answered` (or as [DELEGATED] decisions). Then the classes of reviewer findings "
                   "set aside by the project configuration (`standing_defers`), each with the condition "
                   "for revisiting it.")


DECL_KW = r"(?:theorem|lemma|def|abbrev|structure|inductive|class|instance|opaque|axiom)"


def locate_names(cfg, names):
    """{name: 'File.lean:N'} for each name declared in the project's Lean files (short or
    qualified name; the last component is matched against the declaration line)."""
    want = {n: n.split(".")[-1] for n in names}
    found = {}
    for rel in cfg["lean_files"]:
        fpath = os.path.join(REPO, rel)
        if not os.path.exists(fpath):
            continue
        for i, line in enumerate(open(fpath, encoding="utf-8"), 1):
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


def missing_theory_problems(cfg, header, rows):
    """A skip blamed on a library lacking a definition or theorem is the human's decision
    (RUN.md, "Missing theory"): its row must say every configured library was searched, and that
    the human (or the operator as [PROXY]) decided. "Mathlib has no graphons" once stood as the
    whole reason, while Tau Ceti had the theorem the proof needed."""
    out = []
    libs = project.libraries(cfg)
    hi = lambda pre: next((i for i, h in enumerate(header) if h.startswith(pre)), None)
    i_how, i_dec = hi("how"), hi("decided")
    for row in rows:
        text = " ".join(row)
        if not MISSING_THEORY_RE.search(text):
            continue
        how = row[i_how] if i_how is not None and i_how < len(row) else ""
        norm = re.sub(r"\s+", "", how).lower()
        unsearched = [l for l in libs if re.sub(r"\s+", "", l).lower() not in norm]
        if unsearched:
            out.append(f"! SKIPPED.md row {row[0][:20]}: skipped for missing library theory, but "
                       f"\"how this was checked\" does not record a search of {', '.join(unsearched)}")
        dec = row[i_dec] if i_dec is not None and i_dec < len(row) else ""
        if not re.search(r"\bhuman \(\d{4}-\d{2}-\d{2}\)|operator \[PROXY", dec) and not (
                project.delegates(cfg) and re.search(r"operator " + decisions_tag_re().pattern, dec)):
            out.append(f"! SKIPPED.md row {row[0][:20]}: a missing-theory skip is the human's decision; "
                       f"its \"decided by\" column must record the human's answer (RUN.md, \"Missing theory\")")
    return out


def prose_only_defects(path):
    """A defect stated only in prose ("Observation 1.20 is false as printed") reaches neither the
    report nor the box: every defect is a table row (rule 3). Flags a prose line saying "false as
    printed" that names a result no row of the defects table mentions."""
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    _, rows = record_table(path, "severity")
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


def record_header(path):
    """The header cells (lower case) of the first table in a record file, or []."""
    if not os.path.exists(path):
        return []
    for line in open(path, encoding="utf-8"):
        if line.strip().startswith("|"):
            return [c.strip("* ").lower() for c in project.split_row(line)]
    return []


# Labels for record columns, by the start of the header. A column the generator does not know (a
# "decision" or "decided by" column an adjudicator added) is still shown, under its own header:
# the report must never drop what the record holds (rule 3).
LABELS = [("what the paper says", "The source says"), ("why it is wrong", "Why it is wrong"),
          ("lean witness", "Lean witness"), ("consequence", "Consequence"), ("found", "First found"),
          ("reason", "Reason"), ("what it would take", "What it would take"),
          ("how this was checked", "How this was checked"), ("the paper's route", "The paper's route"),
          ("the lean route", "The Lean route"), ("why different", "Why different"), ("kind", "Kind"),
          ("for which", "For which parameters"), ("why", "Why"), ("decision", "Decision"),
          ("status", "Status")]


def entry_fields(header, row, skip):
    """[(label, cell)] for every column of a record row except `skip` (header names)."""
    out = []
    for i, h in enumerate(header):
        if h in skip or i >= len(row):
            continue
        label = next((lab for pre, lab in LABELS if h.startswith(pre)), h[:1].upper() + h[1:])
        out.append((label, row[i]))
    return out


SECTION_OF = {"defect": 5, "not formalized": 4, "proof route": 6, "vacuous": 7}


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
        box.append(bl + (f" (details: section {sec})" if sec else ""))
    appr_p = os.path.join(root, "APPROVED_FINGERPRINTS.json")
    appr = json.load(open(appr_p)) if os.path.exists(appr_p) else None
    dl = delegation(cfg)
    if not appr:
        box.append("statement approval: NONE -- no one has approved the Lean statements (section 1)")
    elif appr.get("by") != "human":
        box.append("statement approval: the Lean statements were NOT approved by a human "
                   + ((f"(the agent approved them under the {dl[0]} involvement level chosen at intake)"
                       if dl and dl[0] == "hands-off" else
                       "(the agent approved them; the statements-only level does not allow that)"
                       if dl and dl[0] == "statements-only" else "(the agent approved them, on the human's instruction)")
                      if appr.get("by") == "agent" else "(the approver was not recorded)") + " (section 1)")
    if dl:
        box.append(f"decisions taken on your behalf: {len(dl[2])} decision(s) were taken by the operator, "
                   f"not by a human, under the {dl[0]} involvement level chosen at intake (answer: "
                   f"\"{dl[1]}\"); each is final, its tag says what reversing it costs, and it is listed with how to reverse it "
                   f"in `{os.path.join(root, 'DECISIONS.md')}` and in section 1")
    if os.path.exists(os.path.join(root, "READER_NOTES.md")):
        # records rendered in the box may predate the human's answers or later commits; the
        # formalizer's notes carry the current status, and a reader of page 1 must be told so
        box.insert(0, "current status: some lines below are copied from records written before the "
                      "human's answers or the last commits; section 8 (Notes for the reader) gives "
                      "each one's current status and corrects them")
    lr = later_row(cfg)
    if lr and not lr[2].startswith("none"):
        box.append("Lean changes after the last audit round, not examined by any reviewer (section 1)")
    head = subprocess.run(["git", "-C", REPO, "rev-parse", "--short=11", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or "unknown"
    audits = os.path.join(REPO, "audits")
    bg = [
        ("What this is",
         f"A formalization in Lean 4 ({libraries_phrase(cfg)}) of {cfg['source_cite']}. The source "
         f"file is `{cfg.get('source_pdf', '?')}`. The Lean code is in the repository `{REPO}`, "
         f"branch `{cfg.get('branch', '?')}`, commit `{head}`, namespace `{cfg.get('namespace', '?')}`; "
         f"its files are " + ", ".join(f"`{x}`" for x in cfg.get("lean_files", [])) + ". The "
         f"audit record is the directory `{root}`."),
        ("How it was checked",
         "The Lean statements of the paper's results were written first and approved at a "
         "checkpoint (Checkpoint B) before any proof was written; section 1 says who approved them. "
         "Then the proofs were written, and Lean's kernel checks every one. Then audit rounds: "
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
         "project configuration listing material declared out of scope. " + SEVERITY_MD),
    ]
    return box, bg


def build_tex(cfg, index, skipped, defects, deviations, verified, stamp, assume_rows,
              heads=None, vacuous=(), front=None, record_notes=(), reader_notes="", extras=None):
    t = PREAMBLE
    t += ("\\begin{center}\n{\\LARGE\\sffamily\\bfseries Formalization report}\\\\[0.4em]\n"
          "{\\large " + tex(cfg["source_cite"]) + "}\\\\[0.8em]\n"
          "{\\small Generated " + stamp + " from the audit records. Do not edit this file.}\n"
          "\\end{center}\n\\vspace{0.6em}\n")
    heads = heads or {}
    box, bg = front if front is not None else ([], [])
    if box:
        # breakable: a long box must continue on the next page, never be clipped (a fixed box
        # silently dropped its last three lines on the real record)
        t += ("\\begin{tcolorbox}[breakable,colback=red!4,colframe=red!60!black,title={\\textbf{READ THIS FIRST}: "
              "defects in the source, vacuous statements, results not formalized, failing routes}]\n"
              "\\begin{itemize}[leftmargin=1.2em,itemsep=2pt]\n"
              + "".join("\\item " + tex(b) + "\n" for b in box)
              + "\\end{itemize}\n\\end{tcolorbox}\n")
    for title_, para in bg:
        t += "\\paragraph{" + tex(title_) + ".} " + tex(para) + "\n\n"
    t += ("\\noindent\\textbf{Scope of this document.} It answers four questions: which parts of "
          "the source are formalized and which are not and why; which defects the source has, with "
          "a machine-checked witness for each; where the Lean proof takes a different route "
          "from the paper's; and which statements are true only vacuously. Project \\texttt{" + tex(cfg["name"]) + "}, namespace \\texttt{"
          + tex(cfg["namespace"]) + "}.\n\n")
    t += ("{\\sloppy\\noindent\\textbf{Verification.} " + tex(verified) + "\\par}\n\n")
    if record_notes:
        # the PDF must carry the same warning as the markdown: a reader of the PDF would otherwise
        # follow a stale File.lean:N without being told it is stale
        t += ("{\\sloppy\\noindent\\textbf{Stale line numbers in adjudicator records} (to be "
              "refreshed by the next adjudication; the declaration's current line is given):\n"
              "\\begin{itemize}[leftmargin=1.2em,itemsep=1pt]\n"
              + "".join("\\item " + tex(p_[5:].strip()) + "\n" for p_ in record_notes)
              + "\\end{itemize}\\par}\n\n")
    t += "\\vspace{0.4em}\\hrule\n"

    t += "\n\\section{How far to trust this}\n"
    t += ("Each layer below establishes something different. Only the first is a proof; the "
          "others are reviews, by AI reviewers or by a person, and say so.\n\n")
    for layer, what, status in trust_rows(cfg):
        t += render_entry(tex(layer), [("Establishes", tex(what)), ("Status", tex(status))])

    t += "\n\\section{What the formalization assumes}\n"
    t += ("Read off the Lean, not written by hand. Lean assumes something without proving it in "
          "these ways: a literature result the project declared it takes as a hypothesis (listed "
          "first), a declared \\texttt{axiom}, or a parameterless "
          "\\texttt{def \\dots : Prop} taken as a hypothesis, which is the idiom for "
          "\\emph{assume this whole theorem}. A \\texttt{Prop} with parameters is an ordinary "
          "predicate and is not an assumption. Every proof, conditional or not, is checked "
          "by the kernel (Phase 0's axiom sweep).\n\n")
    if not assume_rows:
        t += ("No declared literature hypotheses, no axioms, and no parameterless assumed "
              "\\texttt{Prop} found. (Detected by pattern: a hypothesis written another way is "
              "listed only if the project declares it.)\n")
    else:
        t += "\\begin{longtable}{L{3.6cm} L{5.0cm} L{6.4cm}}\n\\toprule\n"
        t += "\\textbf{Assumed} & \\textbf{Declared at, or source} & \\textbf{Used as a hypothesis by} \\\\\n"
        t += "\\midrule\n\\endhead\n"
        for kind, name, loc, users in assume_rows:
            u = ", ".join("`" + x + "`" for x in sorted(set(users))) or "*not used by any statement*"
            # wrap the path as a code span so it goes through the \texttt branch, which is
            # the only one that inserts break points. As plain text it had none -- no spaces in
            # a path -- and ran straight through the next column.
            t += (tex("`" + name + "`") + " \\newline {\\small\\itshape " + tex(kind)
                  + "} & " + tex("`" + loc + "`") + " & " + tex(u)
                  + " \\\\\n\\addlinespace[2pt]\n")
        t += "\\bottomrule\n\\end{longtable}\n"
        t += ("\\textbf{Every result whose statement carries one of these is conditional on it}, unless "
              "its row says the library proves it. Each such result says so in its own type, not in "
              "a comment. The sections \\emph{Not formalized, and why} and \\emph{Defects in the source} say which "
              "are external results and which are open problems of the source.\n")

    t += "\n\\section{Coverage: what is formalized}\n"
    t += ("Every numbered result of the source, with the Lean declarations that stand for it: "
          + tex(count_text(index)) + ".\n\n"
          "\\begin{longtable}{L{3.3cm} L{12.4cm}}\n\\toprule\n"
          "\\textbf{Paper} & \\textbf{Lean} \\\\\n\\midrule\n\\endhead\n")
    for r in index:
        t += tex(r[0]) + " & " + tex(r[1] if len(r) > 1 else "") + " \\\\\n\\addlinespace[2pt]\n"
    t += "\\bottomrule\n\\end{longtable}\n"

    t += "\n\\section{Not formalized, and why}\n"
    t += ("Each entry states what it would take to lift the skip. A skip is a decision, not an "
          "omission.\n")
    hs = heads.get("skipped") or ["#", "what", "reason", "what it would take", "how this was checked"]
    ex = extras or {}
    prose = ex.get("prose", {})
    def also(k):
        return ("\n\\paragraph{Also recorded with this table.}\n" + notes_tex(prose[k]) + "\n") if prose.get(k) else ""
    for r in skipped:
        title, rest = split_title(r[1] if len(r) > 1 else "?")
        # numbered like its row: other entries and the reader's notes cite "row N"
        num = (tex(r[0]) + ": ") if (hs and hs[0] == "#" and r and r[0].strip()) else ""
        t += render_entry(num + tex(title), [("What is not formalized", tex(rest))]
                          # the key column is the title: skip it by position, not by the name "what"
                          # (the template heads it "what is not formalized"; skipping by name printed
                          # the field twice)
                          + [(lab, tex(v)) for lab, v in entry_fields(hs, r, {"#", hs[1]})])
    t += also("skipped")

    t += "\n\\section{Defects in the source}\n"
    t += "Every entry carries a compiling Lean witness. " + tex(SEVERITY_MD) + "\n"
    hd = heads.get("defects") or ["#", "where", "severity", "what the paper says", "why it is wrong",
                                  "lean witness", "consequence", "found"]
    for r in defects:
        g = lambda i: tex(r[i]) if len(r) > i else ""
        t += render_entry("Defect " + g(0) + ": " + g(1) + "\\hfill\\normalfont\\small[" + g(2) + "]",
                          [(lab, tex(v)) for lab, v in entry_fields(hd, r, {"#", "where", "severity"})])
    if not defects:
        # the markdown says "(none recorded)"; an empty PDF section reads as lost text
        t += "\n\\emph{None recorded.}\n"
    t += also("defects")

    t += "\n\\section{Where the Lean proof differs}\n"
    t += ("Where the Lean proof of a result does not follow the paper's argument. The \\emph{kind} "
          "says what the change means: \\emph{same strength} (another route to the same step), "
          "\\emph{paper step fails} (the paper's step is wrong and was repaired; see also the "
          "defects above), \\emph{Lean intermediate weaker} (an intermediate lemma is weaker than "
          "the paper's, the result is not), \\emph{reading choice} (the paper was ambiguous).\n\n"
          + LIMITS_TEX + "\n")
    hv = heads.get("deviations") or ["#", "result", "the paper's route", "the lean route", "why different", "kind"]
    for r in deviations:
        g = lambda i: tex(r[i]) if len(r) > i else ""
        # the entry shows its ID: other entries cite it ("uniform with R2")
        t += render_entry(g(0) + ": " + g(1),
                          [(lab, tex(v)) for lab, v in entry_fields(hv, r, {"#", "result"})])
    t += also("deviations")

    t += "\n\\section{Statements true only vacuously}\n"
    t += tex(VACUOUS_MD) + "\n"
    hq = heads.get("vacuous") or []
    if not vacuous:
        t += "\n\\emph{None recorded.}\n"
    for r in vacuous:
        st = r[hq.index("statement")] if "statement" in hq and hq.index("statement") < len(r) else r[0]
        num = (tex(r[0]) + ": ") if (hq and hq[0] == "#" and r and r[0].strip()) else ""
        t += render_entry(num + tex(st), [(lab, tex(v)) for lab, v in entry_fields(hq, r, {"#", "statement"})])
    t += also("vacuous")
    if reader_notes:
        t += "\n\\section{Notes for the reader}\n" + notes_tex(reader_notes) + "\n"
    questions = ex.get("questions", [])
    t += "\n\\section{Open questions and standing defers}\n"
    t += tex(QUESTIONS_INTRO) + "\n"
    for k, (rnd, lane, item, why, note) in enumerate(questions, 1):
        t += render_entry("Question " + str(k) + ": " + tex(item),
                          [("Round", tex(rnd)), ("Raised by", tex(lane)), ("The question", tex(why))]
                          + ([("Status", tex(note))] if note else []))
    if not questions:
        t += "\n\\emph{No open QUESTION row.}\n"
    for d in ex.get("defers", []):
        t += render_entry("Standing defer " + tex(str(d.get("id", ""))),
                          [("Covers", tex(str(d.get("item", "")))), ("Reason", tex(str(d.get("reason", "")))),
                           ("Revisit when", tex(str(d.get("revisit_when", ""))))])
    if not ex.get("defers"):
        t += "\n\\emph{No standing defer.}\n"
    if ex.get("glossary"):
        t += "\n\\section{Notation}\n"
        for g in ex["glossary"]:
            t += render_entry(tex(str(g.get("term", ""))), [("Meaning", tex(str(g.get("meaning", "")))),
                                                            ("Where", tex(str(g.get("where", ""))))])
    if ex.get("where"):
        t += ("\n\\section{Where the Lean names are}\nEvery Lean name cited above, with its file and line "
              "at this report's commit.\n\n\\begin{longtable}{@{}p{0.45\\linewidth}p{0.5\\linewidth}@{}}\n")
        for n in sorted(ex["where"], key=str.lower):
            t += tex("`" + n + "`") + " & " + tex("`" + ex["where"][n] + "`") + " \\\\\n"
        t += "\\end{longtable}\n"
    return t + "\n\\end{document}\n"



# The trust boundary, read off the Lean rather than described by hand.
#
# "What does this formalization assume?" is the first question a reader asks and the report made
# them assemble it from two sections. It is also the one thing that must not be hand-maintained:
# a stale list of assumptions is a false statement about what has been proved.
#
# Two things are assumed in Lean without being proved: a declared `axiom`, and a PARAMETERLESS
# `def ... : Prop` taken as a hypothesis -- the idiom for "assume this whole theorem". A Prop
# WITH parameters is an ordinary predicate (MNonneg A, HasPathCover H) and is not an assumption.
# every way to declare a parameterless Prop: attributes, modifiers, def/abbrev/opaque, and a
# class or structure whose type is Prop (the `[X]` hypothesis idiom); `:=` may be on a later line
PROP_DECL_PREFIX = r"(?:@\[[^\]\n]*\]\s*)?(?:(?:private|protected|noncomputable)\s+)*(?:def|abbrev|opaque|class|structure)\s+"
PROP_SLOT = re.compile(r"^(?:@\[[^\]\n]*\]\s*)?(?:(?:private|protected|noncomputable)\s+)*"
                       r"(?:def|abbrev|opaque|class|structure)\s+([A-Za-z_][A-Za-z0-9_']*)\s*:\s*Prop\b", re.M)
AXIOM_RE = re.compile(r"^(?:@\[[^\]\n]*\]\s*)?(?:(?:private|protected)\s+)*axiom\s+([A-Za-z_][A-Za-z0-9_']*)", re.M)


def assumptions(cfg):
    """[(kind, name, file:line or paper, [users])] for everything assumed without proof: the
    literature results the project DECLARED it takes as hypotheses (config `literature_hypotheses`,
    fixed at Checkpoint A), declared axioms, and parameterless `def X : Prop` used as a hypothesis.

    A `def X : Prop` is left out only when EVERY use of it outside its definition applies it to an
    argument (`X P k`): then it is a predicate whose parameters come from a section `variable`
    (a test run's report listed five such predicates as "assumed" for that reason).
    Anything else is listed, with "users not detected" when no binder names it -- hiding a real
    assumption is worse than listing a harmless one. A user is any binder `(h : X)`, `{h : X}`,
    `[X]`, `[Fact X]` (binder names may be `_` or carry subscripts), or an arrow `X →`. Names are
    compared by their last component, so the declared `Ns.FKLinear` and the detected `FKLinear` are
    one row. Comments are ignored."""
    texts = {}
    for rel in cfg["lean_files"]:
        f = os.path.join(REPO, rel)
        if os.path.exists(f):
            t = open(f, encoding="utf-8").read()
            # blank out comments, keeping line numbers
            t = re.sub(r"/-.*?-/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), t, flags=re.S)
            texts[rel] = re.sub(r"--[^\n]*", "", t)
    short = lambda n: n.rsplit(".", 1)[-1]
    QUAL = r"(?:[A-Za-z_][\w.]*\.)?"

    def users(name):
        x = re.escape(short(name))
        # any binder whose TYPE mentions X unapplied: (h : X), (h : ¬ X), (h : id X), (h : X := …)
        rx = re.compile(r"[({]\s*[^\s:(){}\[\]|]+\s*:[^(){}|\n]*?(?<![\w.])" + QUAL + x + r"(?![\w'.])(?=\s*(?:[)}]|:=))"
                        r"|\[\s*(?:Fact\s+)?" + QUAL + x + r"\s*\]"
                        r"|(?<![\w.])" + QUAL + x + r"\s*→")
        out = []
        for rel, txt in texts.items():
            for m in rx.finditer(txt):
                line_start = txt.rfind("\n", 0, m.start()) + 1
                if re.match(r"\s*variable\b", txt[line_start:m.start()]):
                    out.append(f"a section `variable` ({os.path.basename(rel)}:{txt.count(chr(10), 0, m.start()) + 1})")
                    continue
                d = list(re.finditer(rf"^\s*(?:private\s+|protected\s+)?{DECL}\s+([^\s(:{{\[]+)",
                                     txt[:m.start()], re.M))
                out.append(d[-1].group(1) if d else os.path.basename(rel))
        return sorted(set(out))

    def only_applied(name):
        """Every use outside the definition applies it to an argument."""
        x = re.escape(short(name))
        uses = 0
        for txt in texts.values():
            for m in re.finditer(r"(?<![\w.])" + QUAL + x + r"(?![\w'.])", txt):
                line = txt[txt.rfind("\n", 0, m.start()) + 1:txt.find("\n", m.end())]
                if re.match(rf"\s*{PROP_DECL_PREFIX}{x}\b", line):
                    continue
                uses += 1
                nxt = txt[m.end():m.end() + 40].lstrip(" ")
                if not nxt or not re.match(r"[\w(⟨{]", nxt) or re.match(r"(?:where|with|at|in|then|else|fun)\b", nxt):
                    return False
        return uses > 0

    def where(name):
        for rel, txt in texts.items():
            m = re.search(rf"^{PROP_DECL_PREFIX}{re.escape(short(name))}\b", txt, re.M)
            if m:
                return f"{rel}:{txt.count(chr(10), 0, m.start()) + 1}"
        return None

    def proved_by(name):
        """Theorems whose whole type is the hypothesis: the library proves it outright."""
        rx = re.compile(rf"^\s*(?:theorem|lemma|instance)\s+(\S+\s*)?:\s*{QUAL}{re.escape(short(name))}\s*(?::=|where|$)", re.M)
        return sorted({(m.group(1) or "an instance").strip() for t in texts.values() for m in rx.finditer(t)})

    found = []
    declared = {short(h.get("lean", "")) for h in cfg.get("literature_hypotheses", [])}
    for h in cfg.get("literature_hypotheses", []):
        pr = proved_by(h.get("lean", "?"))
        loc = where(h.get("lean", "?"))
        found.append(["literature result taken as hypothesis (declared at Checkpoint A)"
                      + (f"; the library also PROVES it: {', '.join(pr)}, so a result stated with it "
                         f"holds unconditionally" if pr else ""),
                      h.get("lean", "?"), (f"{loc}; " if loc else "") + h.get("paper", "?"),
                      users(h.get("lean", "?"))])
    for rel, txt in texts.items():
        for rx, kind in ((AXIOM_RE, "axiom"), (PROP_SLOT, "assumed Prop")):
            for m in rx.finditer(txt):
                if m.group(1) in declared:
                    continue
                if kind == "assumed Prop" and only_applied(m.group(1)):
                    continue
                line = txt.count("\n", 0, m.start()) + 1
                pr = proved_by(m.group(1))
                found.append([kind + (f"; the library PROVES it: {', '.join(pr)}, so it assumes nothing" if pr else ""),
                              m.group(1), f"{rel}:{line}", users(m.group(1))])
    return found

VACUOUS_MD = ("A statement is true only vacuously when, for parameter values the paper's statement "
              "covers, its hypotheses cannot all be satisfied, so it holds for no mathematical reason "
              "(for instance a lemma stated inside a proof by contradiction, whose setting cannot "
              "exist). Each entry says for which parameters, why, the decision taken and its reasoning, "
              "and whether it still holds of the Lean (status).")
SEVERITY_MD = ("Severity S1–S4 measures *what it takes to repair*, not how serious the mathematics "
               "is: S1 false as printed, S2 missing hypothesis, S3 unsupported claim, S4 typo. Each "
               "entry also states its consequence.")
LATEX_CMD = re.compile(r"\\[A-Za-z]+")
DOLLAR_MATH = re.compile(r"\$[^$\n]+\$")
FILE_LINE = re.compile(r"\b([A-Za-z0-9_/]+\.lean):(\d+)((?:\s*,\s*:\d+)*)")
TEX_LINE = re.compile(r"\btex (?:l\.\s*~?)?(\d+)((?:\s*(?:[–-]|,)\s*\d+)*)")
BARE_LINE = re.compile(r"(?<!tex )(?<![\w.])l\.\s*~?\d+")
BARE_ID = re.compile(r"(?<![\w.])([RGQ]\d+)(?![\w.])")
DECL_AT = r"^\s*(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*(?:theorem|lemma|def|abbrev|structure|inductive|class|instance|axiom|opaque)\s+(?:\S+\.)?{}(?![\w'.])"


def names_cited_ok(nm):
    """Names that need no declaration in the project: Mathlib's (qualified with a Mathlib namespace)."""
    return {nm.rsplit(".", 1)[-1]} if re.match(r"^(?:Finset|Fin|Nat|Int|Set|List|Equiv|Matrix|Function)\.", nm) else set()


ADJ_RECORDS = ("SKIPPED.md", "PAPER_DEFECTS.md", "VACUOUS.md")


def rendering_problems(cfg, skipped, defects, deviations, index=(), vacuous=()):
    """What a reader of the rendered report would trip over, found mechanically (AUDIT_PROTOCOL.md,
    "Documents a human reads", rules 1, 2 and 6):
      - LaTeX (any `\\command`, or `$...$`) outside a code span: it prints literally;
      - an ID like R7, G3 or Q4 the report does not define (only the route IDs are defined in it);
      - `File.lean:N` (and continuations `, :M`) naming no project file, a line past its end, or
        -- when backticked names precede it, one per number -- a line where that name is not
        declared (rule 2: the line must be the declaration's, at the report's commit);
      - `tex l.N`, `tex N–M`, `tex N, M` past the end of the source, and a bare `l.N`.
    Scanned: SKIPPED.md, PAPER_DEFECTS.md, DEVIATIONS.md, the index rows and the configured
    literature hypotheses' source text."""
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
                                                 for h in cfg.get("literature_hypotheses", [])])]
    for src_name, rows in sources:
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
                                    lead = "NOTE" if src_name in ADJ_RECORDS else "!"
                                    out.append(f"{lead} {where}: `{nm}` is cited at {f}:{n} but declared at "
                                               f"line {at} (cite the line at the report's commit)")
                if tex_lines:
                    for m in TEX_LINE.finditer(cell):
                        ns = [int(m.group(1))] + [int(x) for x in re.findall(r"\d+", m.group(2))]
                        if max(ns) > tex_lines:
                            out.append(f"! {where}: {m.group(0)} is past the end of the source")
    return out


def count_text(index):
    """"57 index rows (55 numbered results plus 2 restatements of earlier results)": a count that
    differs from the paper's own must say why (rule 3)."""
    restated = sum(1 for r in index if len(r) > 1 and re.search(r"restatement of", r[1], re.I))
    if not restated:
        return f"{len(index)} numbered result{'s' if len(index) != 1 else ''}"
    return (f"{len(index)} index rows ({len(index) - restated} numbered result{'s' if len(index) - restated != 1 else ''} plus {restated} "
            f"restatement{'s' if restated != 1 else ''} of earlier results)")


def build(cfg, check_only=False):
    rounds_dir = os.path.join(REPO, cfg["rounds_dir"])
    index_file = cfg.get("index_file") or next(
        (f for f in cfg["lean_files"] if f.endswith("Main.lean")), cfg["lean_files"][0])
    declared = declared_names(cfg["lean_files"])
    problems = []

    index = table_rows(os.path.join(REPO, index_file))
    index = [r for r in index if r and RESULT.match(r[0])]
    # each record's table is the one whose header has its key column: PAPER_DEFECTS.md opens with
    # a severity legend, and reading the FIRST table put every defect under the legend's headers
    heads, recs = {}, {}
    for k, f, keycol in (("skipped", "SKIPPED.md", "what"), ("defects", "PAPER_DEFECTS.md", "severity"),
                         ("deviations", "DEVIATIONS.md", "kind"), ("vacuous", "VACUOUS.md", "statement")):
        heads[k], recs[k] = record_table(os.path.join(rounds_dir, f), keycol)
        if not heads[k] and has_table(os.path.join(rounds_dir, f)):
            # rows under a header without the key column were dropped from the report, silently
            problems.append(f"! {f}: it has a table, but no table header has a `{keycol}` column; "
                            f"its rows are not in the report (add the column; the record's columns are in "
                            f"AUDIT_PROTOCOL.md)")
        for row in recs[k]:
            if len(row) != len(heads[k]):
                problems.append(f"! {f} row {row[0][:20]}: {len(row)} cells under a {len(heads[k])}-column header")
    skipped, defects, deviations, vacuous = recs["skipped"], recs["defects"], recs["deviations"], recs["vacuous"]
    problems += prose_only_defects(os.path.join(rounds_dir, "PAPER_DEFECTS.md"))
    problems += missing_theory_problems(cfg, heads["skipped"], skipped)
    problems += delegation_problems(cfg)
    appr_p = os.path.join(rounds_dir, "APPROVED_FINGERPRINTS.json")
    if os.path.exists(appr_p) and json.load(open(appr_p)).get("by") not in ("human", "agent"):
        problems.append("! APPROVED_FINGERPRINTS.json records no approver (`by`): re-record the approval with "
                        "`signoff.py approve --by human|agent` so the report can say who approved")
    front = front_matter(cfg)

    if not index:
        problems.append(f"! parsed 0 index rows from {index_file} — the table moved or changed shape")

    # --- the check that matters: nothing falls between formalized and deliberately skipped ---
    # A result is explained by a SKIPPED row that names it EXACTLY: "Lemma 1.3" must not be
    # explained by a row about "Lemma 1.31" (a substring match once did that).
    def _names_in(text):
        return {re.sub(r"\s+", " ", m.group(0)).lower()
                for m in re.finditer(rf"\b(?:{project.RESULT_KINDS_RE})\s+[\d.]*\d(?:\([^)]*\))?",
                                     text, re.I)}
    # only the row's subject -- its "what" column -- names what it skips; its reasoning may
    # mention other results (a Remark 4.4 row that cites "the Theorem 4.1 value" skips 4.4 only)
    skip_names = set().union(*(_names_in(r[1] if len(r) > 1 else "") for r in skipped)) if skipped else set()
    accounted, unaccounted = [], []
    for r in index:
        name = r[0]
        base = re.sub(r"\s+", " ", name.split("(")[0].strip()).lower()
        cited_decls = [t for t in re.findall(r"`([^`]+)`", r[1] if len(r) > 1 else "")
                       if t.split("(")[0].strip() in declared]
        # formalized = the row cites at least one declaration that exists; backticked math or a
        # misspelt name does not make a result formalized
        formalized = len(r) > 1 and not NOT_FORMALIZED.search(r[1]) and bool(cited_decls)
        explained = base in skip_names or re.sub(r"\s+", " ", name).lower() in skip_names
        (accounted if (formalized or explained) else unaccounted).append(name)
        if not formalized and not explained:
            problems.append(f"! {name}: not formalized by the index, and no SKIPPED.md row explains it")
        if formalized and explained and not re.search(r"\(|partial|half", name + " " + r[1], re.I):
            problems.append(f"! {name}: the index says it is formalized AND a SKIPPED.md row skips it")

    for r in index + skipped + defects + deviations:
        for t in cited_names(r, declared):
            problems.append(f"! cited but not declared: `{t}` (in: {r[0][:44]})")
    _rp = rendering_problems(cfg, skipped, defects, deviations, index, vacuous)
    record_notes = [p_ for p_ in _rp if p_.startswith("NOTE")]
    problems += [p_ for p_ in _rp if not p_.startswith("NOTE")]

    count_txt = count_text(index)
    stamp = datetime.date.today().isoformat()
    box, bg = front
    head = f"# Formalization report — {cfg['source_cite']}\n"
    if box:
        head += ("\n> **READ THIS FIRST** -- defects in the source, vacuous statements, results not "
                 "formalized, failing routes:\n>\n" + "".join(f"> - {b}\n" for b in box))
    for title_, para in bg:
        head += f"\n**{title_}.** {para}\n"
    head += f"""
**Generated {stamp} by `audits/make_report.py`. Do not edit this file.**
Its sources are edited instead, by the protocol steps that maintain them:

| section | source | maintained by |
|---|---|---|
| coverage | the index table in `{index_file}` | steps 1 and 5, as results are formalized |
| not formalized | `{cfg['rounds_dir']}/SKIPPED.md` | step 4, when a skip is decided |
| paper defects | `{cfg['rounds_dir']}/PAPER_DEFECTS.md` | step 4, when a defect is confirmed |
| proof deviations | `{cfg['rounds_dir']}/DEVIATIONS.md` | steps 1 and 5, when a route diverges |
| vacuous statements | `{cfg['rounds_dir']}/VACUOUS.md` | step 4, when a statement is found true only vacuously |
| notes for the reader | `{cfg['rounds_dir']}/READER_NOTES.md` (if present) | the formalizer, for what the human asks to have explained |

Project `{cfg['name']}`, branch `{cfg['branch']}`, namespace `{cfg['namespace']}`.
"""
    if record_notes:
        head += ("\n> **Stale line numbers in adjudicator records** (to be refreshed by the next "
                 "adjudication; the declaration's current line is given):\n>\n"
                 + "".join(f"> * {p_[5:]}\n" for p_ in record_notes))
    if problems:
        head += ("\n> **VERIFICATION FAILED — this report is not yet trustworthy.**\n>\n"
                 + "".join(f"> * {p.lstrip('! ')}\n" for p in problems))
    else:
        head += (f"\n**Verified:** all {count_txt} are either formalized or "
                 f"explained in `SKIPPED.md`, and every Lean name cited below exists.\n")

    def render(title, note, rows, header):
        if not rows:
            return f"\n## {title}\n\n{note}\n\n_(none recorded)_\n"
        w = "| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n"
        for r in rows:
            # a literal bar inside a cell must stay escaped, or GitHub splits the cell
            w += "| " + " | ".join(c.replace("|", "\\|") for c in (r + [""] * len(header))[:len(header)]) + " |\n"
        return f"\n## {title}\n\n{note}\n\n{w}"

    trust = trust_rows(cfg)
    body = render("1. How far to trust this",
                  "Each layer establishes something different. Only the first is a proof.",
                  [list(r) for r in trust], ["layer", "establishes", "status"])
    asm = assumptions(cfg)
    body += render("2. What the formalization assumes",
                   "Read off the Lean: literature results the project takes as hypotheses (declared at "
                   "Checkpoint A), declared axioms, and parameterless `def X : Prop` taken as a "
                   "hypothesis. A result whose statement carries one of these is conditional on it, "
                   "unless the row says the library proves it.",
                   [[f"`{a[1]}`", a[0], a[2], ", ".join(f"`{u}`" for u in a[3]) or "*users not detected*"]
                    for a in asm], ["assumed", "kind", "declared at, or source", "used as a hypothesis by"])
    body += render("3. Coverage: what is formalized",
                  f"Every numbered result of the source, and the Lean that stands for it: "
                  f"{count_text(index)}, {len(accounted)} of {len(index)} rows accounted for.",
                  index, ["paper", "Lean"])
    body += render("4. Not formalized, and why",
                   "Each row says what it would take to lift the skip. A skip is a decision, "
                   "not an omission.", skipped,
                   heads["skipped"] or ["#", "what", "reason", "what it would take", "verified"])
    body += render("5. Defects in the source",
                   "Every row carries a compiling Lean witness. " + SEVERITY_MD,
                   defects, heads["defects"] or ["#", "where", "sev", "the paper says", "why wrong", "witness",
                                                 "consequence", "found"])
    body += render("6. Where the Lean proof differs",
                   "Where the Lean proof does not follow the paper's argument, and what kind of "
                   "change it is (same strength / paper step fails / Lean intermediate weaker / "
                   "reading choice). " + LIMITS_MD,
                   deviations, heads["deviations"] or ["#", "result", "paper's route", "Lean route", "why", "kind"])
    body += render("7. Statements true only vacuously", VACUOUS_MD, vacuous,
                   heads["vacuous"] or ["#", "statement"])
    # free text recorded below each record's table (updates, corrections): never dropped
    prose = {k: record_after_table(os.path.join(rounds_dir, f), keycol)
             for k, f, keycol in (("skipped", "SKIPPED.md", "what"), ("defects", "PAPER_DEFECTS.md", "severity"),
                                  ("deviations", "DEVIATIONS.md", "kind"), ("vacuous", "VACUOUS.md", "statement"))}
    for k, title in (("skipped", "4. Not formalized"), ("defects", "5. Defects in the source"),
                     ("deviations", "6. Where the Lean proof differs"), ("vacuous", "7. Statements true only vacuously")):
        if prose[k]:
            # appended at the end of its section: find the next section heading after it
            i = body.index(f"\n## {title}")
            j = body.find("\n## ", i + 1)
            j = len(body) if j < 0 else j
            body = body[:j] + "\n**Also recorded with this table:**\n\n" + prose[k] + "\n" + body[j:]

    # READER_NOTES.md: the formalizer's plain-language notes for the human reader (what the human
    # asked to have explained in the report at Checkpoint C); rendered verbatim as section 8
    rn_path = os.path.join(rounds_dir, "READER_NOTES.md")
    reader_notes = ""
    if os.path.exists(rn_path):
        reader_notes = open(rn_path, encoding="utf-8").read()
        reader_notes = re.sub(r"\A\s*# [^\n]*\n", "", reader_notes).strip()
        body += "\n## 8. Notes for the reader\n\n" + reader_notes + "\n"
    nsec = 9 if reader_notes else 8
    questions = open_questions(cfg)
    defers = cfg.get("standing_defers") or []
    body += f"\n## {nsec}. Open questions and standing defers\n\n" + QUESTIONS_INTRO + "\n\n"
    if questions:
        body += "| round | lane | item | the question |\n|---|---|---|---|\n" + "".join(
            "| " + " | ".join(c.replace("|", "\\|") for c in (rnd, lane, item, (f"({note}) " if note else "") + why))
            + " |\n" for rnd, lane, item, why, note in questions)
    else:
        body += "_(no open QUESTION row)_\n"
    if defers:
        body += "\n| standing defer | covers | reason | revisit when |\n|---|---|---|---|\n" + "".join(
            "| " + " | ".join(str(d.get(k, "")).replace("|", "\\|") for k in ("id", "item", "reason", "revisit_when"))
            + " |\n" for d in defers)
    else:
        body += "\n_(no standing defer)_\n"
    nsec += 1
    glossary = cfg.get("glossary") or []
    if glossary:
        body += (f"\n## {nsec}. Notation\n\nThe source's notation and the Lean names that bundle it.\n\n"
                 "| term | meaning | where |\n|---|---|---|\n" + "".join(
                     "| " + " | ".join(str(g.get(k, "")).replace("|", "\\|") for k in ("term", "meaning", "where"))
                     + " |\n" for g in glossary))
        nsec += 1
    cited = []
    for r in index + skipped + defects + deviations + vacuous:
        for c in r:
            cited += [t.split("(")[0].strip() for t in re.findall(r"`([^`]+)`", c)]
    cited = [t for t in dict.fromkeys(cited) if t in declared]
    where = locate_names(cfg, cited)
    if where:
        body += (f"\n## {nsec}. Where the Lean names are\n\nEvery Lean name cited above, with its file and "
                 "line at this report's commit.\n\n| name | at |\n|---|---|\n"
                 + "".join(f"| `{n}` | `{where[n]}` |\n" for n in sorted(where, key=str.lower)))
    extras = {"prose": prose, "questions": questions, "defers": defers,
              "glossary": glossary, "where": where}
    out = head + body
    if not check_only:
        open(os.path.join(rounds_dir, "REPORT.md"), "w", encoding="utf-8").write(out)
        verified_txt = (("VERIFICATION FAILED: " + "; ".join(p.lstrip("! ") for p in problems))
                        if problems else
                        ("All " + count_txt + " are either formalized or "
                         "explained below, and every Lean name cited in this document exists in "
                         "the development."))
        tx = build_tex(cfg, index, skipped, defects, deviations, verified_txt, stamp,
                       assumptions(cfg), heads, vacuous, front, record_notes, reader_notes, extras)
        texf = os.path.join(rounds_dir, "REPORT.tex")
        open(texf, "w", encoding="utf-8").write(tx)
        import subprocess
        ok = True
        for _ in range(2):   # twice, so longtable column widths settle
            r = subprocess.run(["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
                                "REPORT.tex"], cwd=rounds_dir, capture_output=True, text=True)
            ok = r.returncode == 0
            if not ok:
                tail = [l for l in r.stdout.splitlines() if l.startswith("!")][:4]
                print("  xelatex FAILED:", "; ".join(tail) or r.stdout[-300:])
                break
        gone = missing_glyphs(os.path.join(rounds_dir, "REPORT.log"))
        if ok and gone:
            print("  PDF DROPS CHARACTERS (no glyph in the font): " + " ".join(gone)
                  + " -- map them in UNI_MATH")
            ok = False
        for ext in (".aux", ".log", ".out"):
            f = os.path.join(rounds_dir, "REPORT" + ext)
            if os.path.exists(f):
                os.remove(f)
        for w in dict.fromkeys(_GLYPH_WARN):
            print(" ", w)
            problems.append(w)
        print(f"  PDF: {'written' if ok else 'NOT written'} ({cfg['rounds_dir']}/REPORT.pdf)")
        if not ok:
            problems.append("! the PDF did not compile")

    print(f"index rows {len(index)}, skipped {len(skipped)}, defects {len(defects)}, "
          f"deviations {len(deviations)}")
    for p in problems:
        print(" ", p)
    for p in record_notes:
        print(" ", p)
    print(f"{'FAIL' if problems else 'ok'}: {len(problems)} problem(s)"
          + ("" if check_only else f"; wrote {cfg['rounds_dir']}/REPORT.md"))
    return 1 if problems else 0


def selftest():
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    global REPO
    keep = REPO
    try:
        REPO = tmp
        os.makedirs(os.path.join(tmp, "P")); os.makedirs(os.path.join(tmp, "R"))
        open(os.path.join(tmp, "P", "Src.lean"), "w").write("theorem thm_1_1 : True := trivial\n")
        cfg = {"name": "t", "source_cite": "src", "branch": "b", "namespace": "P",
               "rounds_dir": "R", "lean_files": ["P/Src.lean", "P/Main.lean"],
               "index_file": "P/Main.lean"}

        def idx(rows):
            open(os.path.join(tmp, "P", "Main.lean"), "w").write(
                "/-!\n| Paper | Lean |\n|---|---|\n" + "\n".join(rows) + "\n-/\n")

        checks = []
        idx(["| Theorem 1.1 | `thm_1_1` |"])
        checks.append(("a fully covered index passes", build(cfg, True) == 0))
        idx(["| Theorem 1.1 | `thm_1_1` |", "| Lemma 1.2 | not formalized |"])
        checks.append(("an unexplained skip FAILS", build(cfg, True) == 1))
        open(os.path.join(tmp, "R", "SKIPPED.md"), "w").write(
            "| # | what | reason |\n|---|---|---|\n| 1 | Lemma 1.2 | needs a long construction |\n")
        checks.append(("the same skip passes once SKIPPED.md explains it", build(cfg, True) == 0))
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
        checks.append(("declared literature hypotheses are listed as assumptions",
                       any(x[1] == "ErdosHyp" and "declared" in x[0] for x in a_)))
        tr = dict((r[0], r[2]) for r in trust_rows(cfg))
        checks.append(("trust: no approval is disclosed as NONE", "NONE" in tr["Approval of statements"]))
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
        e, st_ = appr_doc()
        checks.append(("trust: an approval without an approver is treated as not human-reviewed",
                       "NOT RECORDED" in st_ and "NOT reviewed by a human" in e))
        e, st_ = appr_doc(by="agent", rows={})
        checks.append(("trust: the older-format branch (no rows) still names an agent approver",
                       "NOT BY A HUMAN" in st_))
        json.dump({"date": "2025-12-01", "by": "agent", "fingerprints": {}},
                  open(os.path.join(tmp, "R", "APPROVED_FINGERPRINTS.2025-12-01.json"), "w"))
        e, st_ = appr_doc(by="human")
        checks.append(("trust: an earlier (agent) approval moved aside is still disclosed",
                       "earlier approvals: 2025-12-01 by agent" in st_))
        os.remove(os.path.join(tmp, "R", "APPROVED_FINGERPRINTS.2025-12-01.json"))
        idx([])
        checks.append(("an unparseable index FAILS rather than reporting nothing",
                       build(cfg, True) == 1))
        # every mapped symbol, in prose and inside a math run, typesets with no dropped glyph
        gd = os.path.join(tmp, "glyphs"); os.makedirs(gd)
        sample = " ".join(UNI_MATH) + " ; x∈σ(i) ; class 𝒫′ ; = ∅ ; ⋃ A ; k×l ; 𝔓 𝕂 𝐀 ℙ 𝔤 ; 𝒫∖𝒫′ ⊎ A ; PRIMES i'' and L'_3"
        open(os.path.join(gd, "g.tex"), "w", encoding="utf-8").write(
            PREAMBLE + "\n" + tex(sample) + "\n\\end{document}\n")
        rg = subprocess.run(["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "g.tex"],
                            cwd=gd, capture_output=True, text=True)
        gone = missing_glyphs(os.path.join(gd, "g.log"))
        checks.append((f"every UNI_MATH symbol typesets, none dropped {gone or ''}",
                       rg.returncode == 0 and not gone))
        gtxt = subprocess.run(["pdftotext", os.path.join(gd, "g.pdf"), "-"],
                              capture_output=True, text=True).stdout
        checks.append(("escaping is one pass: a backslash does not leave a stray \\{} behind",
                       tex("a\\b {x}") == "a\\textbackslash{}b \\{x\\}"))
        checks.append(("primes stay straight (i'' is not turned into a closing quote)",
                       "PRIMES i'' and L'_3" in gtxt.replace("\n", " ")))
        open(os.path.join(gd, "h.log"), "w").write("Missing character: There is no ⋃ (U+22C3) in font\n")
        checks.append(("missing_glyphs reads xelatex's 'Missing character' lines",
                       missing_glyphs(os.path.join(gd, "h.log")) == ["⋃"]))
        words = {ch: v for ch, v in UNI_MATH.items() if re.fullmatch(r"\\[A-Za-z]+", v)}
        checks.append(("no math symbol's control word swallows a following letter or digit "
                       "(k×l, c·n, x∈S1)",
                       all(v + "b" not in _mathify("a" + ch + "b") and
                           v + "1" not in _mathify("a" + ch + "1") for ch, v in words.items())))
        # --- H3: rendering of record cells, assumptions, counts ---
        checks.append(("an escaped bar inside a cell does not split it (defect rows kept their fields)",
                       project.split_row(r"| 1 | `hd = \|i\|` | why |") == ["1", "`hd = |i|`", "why"]))
        checks.append(("'**Title**: rest' leaves no stray colon",
                       split_title("**Claims outside**: figures") == ("Claims outside", "figures")))
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
        cfg_h = dict(cfg, lean_files=["P/Hyp.lean"], literature_hypotheses=[{"lean": "P.FK", "paper": "FK 2021"}])
        A_ = assumptions(cfg_h)
        names_ = [a[1] for a in A_]
        checks.append(("a declared hypothesis and its def are one row, joined by short name",
                       names_.count("P.FK") == 1 and "FK" not in names_))
        checks.append(("a declared hypothesis lists every statement that takes it, whatever the binder",
                       A_[0][3] == ["a8", "a9", "thm_2_1"]))
        by_ = {a[1]: a[3] for a in A_}
        open(os.path.join(tmp, "P", "Forms.lean"), "w").write(
            "abbrev Ab : Prop := True\nprivate def Pv : Prop := True\n@[simp] def At : Prop := True\n"
            "class Cl : Prop where\n  x : True\nopaque Op : Prop\ndef Nl : Prop :=\n  True\nprivate axiom pax : True\n"
            "/- theorem hidden (h : Bc) : True -/\ndef Bc : Prop := True\n"
            "theorem u1 (h : ¬ Ab) : True := trivial\ntheorem u2 (h : id Pv) : True := trivial\n"
            "theorem u3 [At] : True := trivial\ntheorem u4 [Cl] : True := trivial\n"
            "theorem u5 (h : Op) : True := trivial\ntheorem u6 (h : Nl) : True := trivial\n")
        Af = {a[1]: a[3] for a in assumptions(dict(cfg, lean_files=["P/Forms.lean"]))}
        checks.append(("every declaration form of a parameterless Prop (abbrev, private, @[attr], class, opaque, "
                       ":= on the next line) and private axioms are listed",
                       all(n in Af for n in ("Ab", "Pv", "At", "Cl", "Op", "Nl", "pax"))))
        checks.append(("binders mentioning the Prop under ¬ or id count as uses",
                       Af.get("Ab") == ["u1"] and Af.get("Pv") == ["u2"]))
        checks.append(("a use inside a block comment is not a use", Af.get("Bc") == []))
        open(os.path.join(tmp, "P", "Forms2.lean"), "w").write(
            "structure SV : Prop where\n  x : True\nabbrev AV : Prop := True\nclass CV : Prop where\n  y : True\n"
            "theorem p1 (h : SV 3) (g : AV 2) [CV 1] : True := trivial\n"
            "class Prv : Prop where\n  z : True\ninstance : Prv := ⟨trivial⟩\ntheorem p2 [Prv] : True := trivial\n"
            "def Goal : Prop := True\ntheorem goal_holds : Goal := trivial\ntheorem p3 (h : Goal) : True := trivial\n"
            "def Sb : Prop := True\ntheorem p4 (s : {k : Nat | Sb}) : True := trivial\n"
            "noncomputable def Nc : Prop := True\ntheorem p5 (h : Nc := trivial) : True := trivial\n"
            "@[simp] protected axiom pax2 : True\ndef Ap : Prop := True\ntheorem p6 (h : Ap) : True := trivial\n")
        A2 = {a[1]: a for a in assumptions(dict(cfg, lean_files=["P/Forms2.lean"]))}
        checks.append(("structure/abbrev/class predicates used only applied are not listed",
                       not any(n in A2 for n in ("SV", "AV", "CV"))))
        checks.append(("a Prop the library proves (by a theorem or an instance) says it assumes nothing",
                       "PROVES it" in A2.get("Prv", ["", ""])[0] and "PROVES it: goal_holds" in A2.get("Goal", ["", ""])[0]))
        checks.append(("a set-builder is not a hypothesis; a `(h : X := v)` binder and noncomputable/attr forms are",
                       A2.get("Sb", [0, 0, 0, None])[3] == [] and A2.get("Nc", [0, 0, 0, []])[3] == ["p5"]
                       and "pax2" in A2 and A2.get("Ap", [0, 0, 0, []])[3] == ["p6"]))
        tq_ = tempfile.mkdtemp()
        try:
            w_no = decision_words(tq_)["QUESTION"]
            open(os.path.join(tq_, "DECISIONS.md"), "w").write("x")
            w_yes = decision_words(tq_)["QUESTION"]
        finally:
            shutil.rmtree(tq_, ignore_errors=True)
        checks.append(("QUESTION items: no claim about answers; the decisions document is named only if it exists",
                       w_no == "put to the human as questions" and tq_ in w_yes and "answer" not in w_no))
        tx_c = build_tex(cfg, [], [], [], [], "v", "d", [["literature result", "P.X", "src", ["t"]]])
        checks.append(("the PDF says a listed assumption is conditional unless the library proves it",
                       "unless its row says the library proves it" in tx_c))
        checks.append(("anonymous, instance and subscripted binders count as uses",
                       by_.get("Anon") == ["a5"] and by_.get("Inst") == ["a6"] and by_.get("Sub") == ["a7"]))
        checks.append(("a Prop def used only in a comment is still listed (users not detected), never hidden",
                       by_.get("Gone") == []))
        checks.append(("a hypothesis the library proves outright says so",
                       "PROVES it: fk_holds" in A_[0][0]))
        checks.append(("a Prop def never taken bare as a hypothesis is not listed as assumed",
                       "IsTrav" not in names_ and "ax1" in names_))
        tx_ = build_tex(cfg, [], [], [], [], "v", "2026-01-01", [["literature result", "P.X", "src", []]])
        checks.append(("an unused hypothesis is said in words, not as literal LaTeX",
                       "not used by any statement" in tx_ and "textbackslash{}emph" not in tx_))
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
        tv = build_tex(cfg, [], [], [], [], "VERIFICATION FAILED: PAPER_DEFECTS.md row 3: a \\qed b", "d", [])
        checks.append(("a failed verification line is escaped (it broke the PDF build)",
                       "PAPER\\_DEFECTS" in tv and "textbackslash{}qed" in tv))
        checks.append(("LaTeX-style sub/superscripts in records are set, not printed literally",
                       tex("x_{s+2} ∈ L_{s+1}^B") == "x\\textsubscript{s+2} $\\in$ L\\textsubscript{s+1}\\textsuperscript{B}"
                       and tex("t_P") == "t\\textsubscript{P}" and "\\textsubscript{$\\varphi$}" in tex("height_φ")))
        checks.append(("...but identifiers outside code spans are left alone",
                       tex("AUTHOR_NOTES") == "AUTHOR\\_NOTES" and tex("x_len") == "x\\_len"
                       and tex("rows_k here") == "rows\\_k here"
                       and tex("`a_{b}`").startswith("\\texttt{")))
        checks.append(("straight double quotes open and close", tex('say "hi"') == "say “hi”"))
        tx_r = build_tex(cfg, [], [], [], [["R7", "Lemma 2.1", "a", "b", "c", "same strength"]], "v", "d", [])
        tx_s = build_tex(cfg, [], [["1", "**Lemma 6.2.** half of it", "why", "cost"]], [], [], "v", "d", [],
                         heads={"skipped": ["#", "what is not formalized", "reason", "what it would take"]})
        checks.append(("a skip's key column is printed once, whatever its header says",
                       tx_s.count("What is not formalized") == 1 and "half of it" in tx_s))
        checks.append(("a route entry shows its ID (others cite it as R7)", "R7: Lemma 2.1" in tx_r))
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
        import audit_coverage as ac_
        so_ = ac_.order_rounds
        ac_.order_rounds = lambda rs, repo: sorted(rs)
        try:
            dec_ = rolled_decisions(os.path.join(tmp, "R"))
        finally:
            ac_.order_rounds = so_
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
        checks.append(("quotes inside code spans stay straight", "“" not in tex('`a "b"`')))
        checks.append(("a trailing escaped bar is part of the last cell",
                       project.split_row(r"| a | ends with \| |") == ["a", "ends with |"]))
        checks.append(("file names outside code are not turned into subscripts; -- is not an en dash",
                       "textsubscript" not in tex("see a_b.lean and dir/x_y.lean") and "-{}-" in tex("--write")))
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
                "| # | where | severity | what the paper says | why it is wrong | Lean witness | consequence | decision |\n"
                "|---|---|---|---|---|---|---|---|\n| 1 | tex 3 (Theorem 1.1) | S1 | says X | WRONGSUMMARY e.g. here. More. | `thm_1_1` | survives | REPAIR-DECIDED by the human |\n")
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
                           "reviewed statements or decisions, and lists each [DELEGATED] decision once",
                           "hands-off" in dst_ and "ANSQZ" in dst_ and "No human reviewed the Lean statements" in dst_
                           and "2 decision(s)" in dst_ and dst_.count("DGBQZ") == 1 and "DGAQZ" in dst_
                           and "reversal cost" in dst_ and "reversible" not in dst_
                           and "FRQZ" not in dst_ and "DECISIONS.md" in dst_))
            checks.append(("hands-off: the agent approval says the human chose it at intake, not at Checkpoint B",
                           "hands-off involvement level the user chose at intake" in tr_h["Approval of statements"][0]
                           and "NOT reviewed by a human" in tr_h["Approval of statements"][0]))
            checks.append(("hands-off: the box says how many decisions were taken on the reader's behalf, and where",
                           any(b.startswith("decisions taken on your behalf: 2 decision(s)")
                               and os.path.join(tmp, "R", "DECISIONS.md") in b and "ANSQZ" in b for b in box_h)
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
                           and any("[PROXY]" in p_ for _, p_ in bg_)))
            with contextlib.redirect_stdout(io.StringIO()):
                build(cfg, False)
            md4 = open(os.path.join(tmp, "R", "REPORT.md")).read()
            tx4 = open(os.path.join(tmp, "R", "REPORT.tex")).read()
            checks.append(("REPORT.md opens with the box, before the background and everything else",
                           "> **READ THIS FIRST**" in md4 and "**What this is.**" in md4
                           and md4.index("> **READ THIS FIRST**") < md4.index("**What this is.**") < md4.index("**Generated")))
            # the RENDERED PDF, not the source: a fixed-size box once clipped its last lines
            pdf4 = os.path.join(tmp, "R", "REPORT.pdf")
            def pdftext(first=None, last=None):
                cmd = ["pdftotext", "-layout"] + (["-f", str(first), "-l", str(last)] if first else []) + [pdf4, "-"]
                r_ = subprocess.run(cmd, capture_output=True, text=True)
                return re.sub(r"\s+", " ", r_.stdout) if r_.returncode == 0 else None
            p1, pall = pdftext(1, 1), pdftext()
            words = lambda b: " ".join(re.sub(r"[^\w ]", " ", b).split()[:3])
            checks.append(("the rendered PDF has the box on page 1 and every box line in its text (none clipped)",
                           p1 is not None and "READ THIS FIRST" in p1
                           and all(words(b) in " ".join(re.sub(r"[^\w ]", " ", pall).split()) for b in front_matter(cfg)[0])))
            checks.append(("REPORT.pdf opens with the framed box, before the scope and the sections",
                           "begin{tcolorbox}" in tx4
                           and tx4.index("begin{tcolorbox}") < tx4.index("Scope of this document") < tx4.index("section{How far")))
            checks.append(("the vacuous section shows each statement with its decision",
                           "Statements true only vacuously" in tx4 and "FOUND-MARK" in tx4
                           and "## 7. Statements true only vacuously" in md4 and "KEEP-AS-CONTRADICTION" in md4))
            checks.append(("with a legend table first, the defects table is found by its key column (details kept)",
                           "WRONGSUMMARY" in tx4 and "Why it is wrong" in tx4 and "Meaning" not in tx4
                           and "| what the paper says |" in md4))
            buf4 = io.StringIO()
            with contextlib.redirect_stdout(buf4):
                rc4 = build(cfg, True)
            checks.append(("the report check flags a defect stated only in prose",
                           "Observation 9.9 is called false as printed" in buf4.getvalue()))
            pr4 = prose_only_defects(os.path.join(tmp, "R", "PAPER_DEFECTS.md"))
            checks.append(("a defect stated only in prose is flagged; the legend is not",
                           len(pr4) == 1 and "Observation 9.9" in pr4[0]))
            checks.append(("every box line appears in both the md box and the PDF box",
                           bool(front_matter(cfg)[0])
                           and all(f"> - {b}" in md4 for b in front_matter(cfg)[0])
                           and all(tex(b) in tx4 for b in front_matter(cfg)[0])))
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
            checks.append(("a record column the generator does not know is still shown (both renderings)",
                           "EXTRA-COLUMN" in tx4 and "Decided by" in tx4 and "EXTRA-COLUMN" in md4
                           and "REPAIR-DECIDED" in tx4 and "Decision" in tx4))
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
                                          "grep over Mathlib and TauCeti (2026-10-13)", "human (2026-10-13)"]])
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
        checks.append(("a missing-theory skip decided as [DELEGATED] is accepted only when the level delegates",
                       missing_theory_problems(dict(cfg, involvement="hands-off"), hs_, mt_d) == []
                       and missing_theory_problems(cfg, hs_, mt_d) != []))
        checks.append(("a missing-theory skip needs the dated, canonical [DELEGATED] tag, not a bare one",
                       missing_theory_problems(dict(cfg, involvement="hands-off"), hs_,
                                               [mt_d[0][:5] + ["operator [DELEGATED]"]]) != []))
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
            tx_a = open(os.path.join(tmp, "R", "REPORT.tex")).read()
            checks.append(("A2: free text below a record's table is in the markdown and the PDF",
                           "reason is stale" in md_a and "reason is stale" in tx_a))
            checks.append(("A2: open QUESTION rows are listed, ADOPT rows are not",
                           "keep the paper's hypothesis?" in md_a and "hypothesis?" in tx_a
                           and "drop it" not in md_a))
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
                oq = open_questions(cfg_a)
                with _cl.redirect_stdout(_io.StringIO()):
                    build(cfg_a, False)
                md_q = open(os.path.join(tmp, "R", "REPORT.md")).read()
                tx_q = open(os.path.join(tmp, "R", "REPORT.tex")).read()
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
                           and "OLDQ still unanswered?" in tx_q
                           and sorted(q[2] for q in oq) == ["deleg_re", "lemma_1_2", "old_open", "old_proxy", "re_q"]))
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
                sd = [q for q in open_questions(cfg_a) if q[2] == "same_day"]
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
                xy = [q for q in open_questions(cfg_a) if q[2] == "x_then_y"]
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
            checks.append(("the trust section carries the reissue row",
                           any(r[0] == "Lane reissues" for r in trust_rows(cfg_a))))
            checks.append(("A2: standing defers are listed with their revisit condition",
                           "| d1 | Hyp | literature | never |" in md_a and "Standing defer d1" in tx_a))
            checks.append(("A2: the config's glossary is rendered",
                           "the domination exponent" in md_a and "the domination exponent" in tx_a))
            checks.append(("A2: every cited Lean name is located as File.lean:N",
                           "| `lemma_1_2` | `P/Src.lean:4` |" in md_a and "| `thm_1_1` | `P/Src.lean:1` |" in md_a))
            checks.append(("A2: PDF entries of sections 4 and 7 carry their row numbers",
                           "\\subsection*{4: " in tx_a and "\\subsection*{3: " in tx_a))
            checks.append(("A2: locate_names ignores a name that only appears in a comment",
                           locate_names(dict(cfg, lean_files=["P/Src.lean"]), ["doc"]) == {}))
        finally:
            project.REPO = saved_pr2
            for f_ in ("SKIPPED.md", "VACUOUS.md"):
                if os.path.exists(os.path.join(tmp, "R", f_)):
                    os.remove(os.path.join(tmp, "R", f_))
        print()
        for n, p in checks:
            print(f"  {'ok  ' if p else 'FAIL'}  {n}")
        ok = all(p for _, p in checks)
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        REPO = keep
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    cfg = load_project(a.project)
    return selftest() if a.selftest else build(cfg, a.check)


if __name__ == "__main__":
    sys.exit(main())

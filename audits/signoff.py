#!/usr/bin/env python3
"""The statement sign-off sheet: what is approved at Checkpoint B, and how it is built.

WHY THIS EXISTS.  The one judgement no agent can make for the group is "this Lean statement says
what our paper says". A mathematician who does not read Lean can only make it from a faithful
plain-English reading of the Lean. Two things go wrong with an agent-written sheet:
  * the agent writing "the Lean says X" has the paper open, and reads the paper into the Lean;
  * it is free text, so nothing checks that every result is on it, or every definition the
    statements depend on is explained.
So the sheet is assembled from parts with different authors, and checked mechanically:
  1. `bundle`: this script extracts, per paper result, the Lean statement(s) with comments and
     docstrings STRIPPED (they are the author's words, not the Lean's), plus every project
     definition those statements depend on (their closure, from the fingerprint run), bodies
     stripped likewise. -> <round>/STATEMENTS_BUNDLE.md
  2. a BLIND informalizer subagent, which is never given the paper, writes INFORMAL.json from the
     bundle alone: what each statement and definition says, in plain mathematical English.
     (Back-translation without unfolding definitions is OpenMath's failure; this bundle unfolds
     them. Stripping comments first is Theo's "Hint Cleaner".)
  3. the sign-off writer subagent compares INFORMAL.json with the paper and writes SIGNOFF.json.
  4. `check`: every result is on the sheet, every closure definition is explained, the
     plain-English column is INFORMAL.json's text verbatim (the writer may not "improve" the blind
     reading), and every flag is OK or CHECK.
  5. `render`: SIGNOFF.md and SIGNOFF.pdf, one entry per result with a box to tick.

  signoff.py bundle --round R
  signoff.py check  --round R
  signoff.py render --round R
  signoff.py --selftest [--lean]   (--lean: also the Lean-backed signature checks, ~1 min)
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

FLAGS = {"OK", "CHECK", "GLOBAL"}
# A GLOBAL row differs from the paper ONLY through global differences (a reading choice or a
# definition shared by many results), each stated once in SIGNOFF.json "global" and approved once.
# Without them a test run's sheet flagged 52 of 57 rows CHECK for five shared decisions.
GLOBAL_REF = re.compile(r"^Global: (G\d+(?:, G\d+)*)\.?$")
DEF_KINDS = {"def", "opaque", "inductive"}


def strip_comments(text):
    from phase0 import strip_comments as sc
    return sc(text)


def index_rows(cfg):
    import scope
    lf = cfg.get("lean_files") or []
    f = cfg.get("index_file") or next((x for x in lf if x.endswith("Main.lean")),
                                      lf[0] if lf else None)
    if f is None:
        return []
    p = os.path.join(project.REPO, f)
    return scope.index_rows(open(p, encoding="utf-8").read()) if os.path.exists(p) else []


def not_formalized(cfg):
    """[(label, reason)] for index rows that cite no Lean name: the results the sheet does NOT
    show. A human approving the sheet must see that they exist (found by the pre-approval audit:
    Theorem 1.5 was simply absent)."""
    return [(lab, rest.strip().strip("|").strip()) for lab, rest in index_rows(cfg)
            if "`" not in rest]


def plain(key):
    """A fingerprint key without its "(private in M)" suffix."""
    return key.split(" (private in ")[0]


def resolve(name, keys):
    """A name as cited in the index (often unqualified) -> (the fingerprint key, or None, and a
    reason). Ambiguous names resolve to nothing: guessing would put the wrong statement on a
    sheet a mathematician signs."""
    exact = [k for k in keys if plain(k) == name]
    if len(exact) == 1:
        return exact[0], None
    hits = exact or [k for k in keys if plain(k).endswith("." + name)]
    if len(hits) == 1:
        return hits[0], None
    return None, ("ambiguous: " + ", ".join(sorted(hits)[:4])) if hits else "not declared"


def is_derived_instance(key):
    """A generated instance: last name component `inst…` (Lean's naming for anonymous and derived
    instances). Only consulted when the declaration has NO source text in lean_files -- an
    instance someone wrote is found by the parser and shown like any definition."""
    return plain(key).rsplit(".", 1)[-1].startswith("inst")


def classify_sourceless(names, table, source_of):
    """(holes, derived) among definitions with no source text: a derived instance (`deriving …`)
    is shown by signature with a note; any other missing source is a hole in the bundle."""
    holes, derived = [], set()
    for d in names:
        if table[d][0] in DEF_KINDS and not source_of(d):
            if is_derived_instance(d):
                derived.add(d)
            else:
                holes.append(f"definition {d}: source text not found in lean_files")
    return holes, derived


def lean_table(cfg):
    """{name: (kind, own, deps)} from the fingerprint run (needs a built project)."""
    import fingerprint
    rc, out = fingerprint.run_lean(fingerprint.lean_source(cfg))
    if rc != 0:
        raise RuntimeError(out[-2000:])
    return fingerprint.parse(out)


def signatures(cfg, names):
    """{key: signature} as Lean prints it AFTER elaboration: every binder, including section
    `variable`s and instance arguments that the source text of a declaration does not show, with
    bound-variable types and cast targets shown (the pp options below). This, not the source
    text, is what the statement is.

    `names` are fingerprint keys; a private declaration's key ("N.aux (private in M)") is not a
    name Lean can look up, so the Lean side walks the environment and matches keys, using the
    same key function as the fingerprint run (shared text, not a copy)."""
    import fingerprint
    helpers = open(fingerprint.TAIL, encoding="utf-8").read().split("-- END HELPERS")[0]
    want = ", ".join(json.dumps(n) for n in sorted(set(names)))
    # pp.funBinderTypes: without it `∃ M', P M'` hides the type of M' (e.g. that M' is m × n),
    # and the sheet is what the human approves. Found by a test run.
    # pp.mathlib.binderPredicates false: `∃ x > 0, …` hides whether x is in ℕ or ℝ.
    # pp.coercions.types: `↑(a - b)` hides the target of the cast (truncated ℕ subtraction cast to
    # ℝ is a classic silent change of meaning). Found by an independent audit of the first fix.
    # Not set: pp.numericTypes (too noisy; binder types show what numerals range over).
    tail = (helpers + "set_option pp.funBinderTypes true in\n"
            "set_option pp.mathlib.binderPredicates false in\n"
            "set_option pp.coercions.types true in\n"
            "open Lean Elab Command in\nrun_cmd do\n"
            f"  let want : List String := [{want}]\n"
            "  for (n, _) in (← getEnv).constants.toList do\n"
            "    let k := auditFpKey n\n"
            "    if want.contains k then\n"
            "      let fmt ← liftTermElabM <| PrettyPrinter.ppSignature n\n"
            '      IO.println s!"SIG\\t{k}\\t{(toString fmt.fmt).replace "\\n" "⏎"}"\n')
    sw = cfg["sweep"]
    if sw["mode"] == "import":
        src = f"import {sw['module']}\n" + tail
    else:
        src = open(os.path.join(project.REPO, sw["file"]), encoding="utf-8").read() + "\n" + tail
    rc, out = fingerprint.run_lean(src)
    sigs = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == "SIG" and len(parts) == 3:
            sigs[parts[1]] = parts[2].replace("⏎", "\n")
    if rc != 0 or set(sigs) != set(names):
        raise RuntimeError(f"signature run failed (exit {rc}; missing "
                           f"{sorted(set(names) - set(sigs))[:5]}):\n" + out[-2000:])
    return sigs


def closure(names, table):
    seen, stack = set(), list(names)
    while stack:
        m = stack.pop()
        if m in seen or m not in table:
            continue
        seen.add(m)
        stack.extend(table[m][2])
    return seen


def build_bundle(cfg, table=None):
    """(markdown, rows, defs): rows = [(label, [qualified names])], defs = [qualified names]."""
    import fingerprint
    table = table if table is not None else lean_table(cfg)
    rows, missing = [], []
    for label, rest in index_rows(cfg):
        qs = []
        for c in re.findall(r"`([^`]+)`", rest):
            k, why = resolve(c.split()[0], table)
            if k:
                qs.append(k)
            else:
                # EVERY unresolved name is reported, not only rows where nothing resolved: a row
                # citing two names of which one is misspelt would otherwise reach the sheet with
                # half its statement missing.
                missing.append(f"{label}: `{c.split()[0]}` {why}")
        if qs:
            rows.append((label, qs))
    stmt_names = {q for _, qs in rows for q in qs}
    defs = sorted(n for n in closure(stmt_names, table) - stmt_names
                  if table[n][0] in DEF_KINDS and not fingerprint.is_autogen(n))
    sigs = signatures(cfg, sorted(stmt_names | set(defs)))
    md = ["# Statements bundle (generated by signoff.py)", "",
          "Each entry is a Lean declaration's signature as Lean prints it after elaboration: every",
          "hypothesis and binder is shown with its type (also bound variables of ∃, ∀, fun), casts",
          "are shown with their target type, proofs are omitted, and no comment or docstring is",
          "included. Definitions these statements use follow, each with its elaborated signature",
          "and its body as SOURCE TEXT (comments removed; not elaborated, so a cast or numeral",
          "there may leave its type implicit).", ""]
    holes, derived = classify_sourceless(sorted(stmt_names | set(defs)), table,
                                         lambda d: strip_comments(_raw_text(d, cfg)).strip())
    missing += holes
    for label, qs in rows:
        md.append(f"## {label}")
        for q in qs:
            if q in table and table[q][0] in DEF_KINDS:
                # a definition IS its body; the signature alone says nothing about what it means
                md += ["```lean", "-- signature (elaborated):", sigs[q].strip(),
                       "-- definition (source):", strip_comments(_raw_text(q, cfg)).strip(), "```", ""]
            else:
                md += ["```lean", sigs[q].strip(), "```", ""]
    md.append("# Definitions these statements use")
    for d in defs:
        body = strip_comments(_raw_text(d, cfg)).strip()
        if d in derived:
            body = "-- (derived instance, e.g. from `deriving DecidableEq`: no source text)"
        md += [f"## {d}", "```lean", "-- signature (elaborated):", sigs[d].strip(),
               "-- definition (source):", body, "```", ""]
    if missing:
        md.append("# Index rows whose cited names could not be resolved")
        md += [f"- {m}" for m in missing]
    build_bundle.missing = missing
    return "\n".join(md) + "\n", rows, defs


def _raw_text(qual, cfg):
    """The declaration's text as written (line breaks kept), from scope.py's parser."""
    import scope
    files = cfg["lean_files"]
    if " (private in " in qual:
        # a private key names its module: read only that file, so two files' private `aux`
        # cannot be confused
        mod = qual.split(" (private in ")[1].rstrip(")")
        files = [f for f in files if f[:-5].replace("/", ".") == mod] or files
    qual = plain(qual)
    for f in files:
        p = os.path.join(project.REPO, f)
        if not os.path.exists(p):
            continue
        ds = scope.parse_decls(open(p, encoding="utf-8").read())
        if qual in ds:
            return ds[qual][4]
    return ""


def bundle_problem(round_dir, fresh_md):
    """A problem string if the round's stored STATEMENTS_BUNDLE.md is not what a fresh build gives
    now, else None. The informalizer read the stored bundle and the sheet is built on that
    reading, so a stale bundle means the human would approve a description of OTHER Lean -- or of
    the same Lean printed with less information (found by a test run: a printing fix
    landed after the round's bundle was written, and nothing noticed)."""
    p = os.path.join(round_dir, "STATEMENTS_BUNDLE.md")
    if not os.path.exists(p):
        return "missing STATEMENTS_BUNDLE.md"
    stored = open(p, encoding="utf-8").read()
    if stored != fresh_md:
        a, b = stored.splitlines(), fresh_md.splitlines()
        i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        first = (f"line {i + 1}: stored {a[i]!r} vs now {b[i]!r}" if i < min(len(a), len(b))
                 else f"line {i + 1}: one version ends there")
        return ("STATEMENTS_BUNDLE.md is stale: a fresh build of the bundle differs (the Lean or "
                f"the printing changed since the round was scoped; first difference {first[:200]}). "
                "Start a new statement round.")
    return None


RESULT_REF = re.compile(r"\b(Theorem|Lemma|Corollary|Observation|Proposition|Claim|Fact|"
                        r"Definition|Conjecture|Remark)\s+([A-Z]?\d+(?:\.\d+)*)")


def defect_results(rounds_dir):
    """Result labels ("Corollary 1.11") named in the "where" column of PAPER_DEFECTS.md rows."""
    p = os.path.join(rounds_dir, "PAPER_DEFECTS.md")
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8").read().splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 3 and re.fullmatch(r"\d+", cells[1]):
            out += [f"{k} {n}" for k, n in RESULT_REF.findall(cells[2])]
    return sorted(set(out))


RANGE_REF = re.compile(r"\b(Theorems|Lemmas|Corollaries|Observations|Propositions)\s+"
                       r"(\d+)\.(\d+)\s*[–-]\s*(?:\2\.)?(\d+)\b")
PLURAL = {"Theorems": "Theorem", "Lemmas": "Lemma", "Corollaries": "Corollary",
          "Observations": "Observation", "Propositions": "Proposition"}


def vacuous_results(rounds_dir):
    """Result labels named in the "statement" column of OPEN VACUOUS.md rows. A row counts as
    repaired only if its status reads "repaired in <commit>"; a blank or misspelt status stays
    open, so editing the cell cannot hide a row. "Lemmas 4.10–4.12" expands to each lemma."""
    p = os.path.join(rounds_dir, "VACUOUS.md")
    if not os.path.exists(p):
        return []
    header, out = None, []
    for line in open(p, encoding="utf-8").read().splitlines():
        if not line.lstrip().startswith("|") or set(line.strip()) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if "statement" not in header or len(cells) <= header.index("statement"):
            continue
        if "status" in header and len(cells) > header.index("status") and \
                re.match(r"repaired in [0-9a-f]{7,}", cells[header.index("status")].lower()):
            continue
        st = cells[header.index("statement")]
        out += [f"{k} {n}" for k, n in RESULT_REF.findall(st)]
        for kind, sec, a, b in RANGE_REF.findall(st):
            out += [f"{PLURAL[kind]} {sec}.{i}" for i in range(int(a), int(b) + 1)]
    return sorted(set(out))


def check(cfg, round_dir, rows, defs, fresh_md=None):
    """[problem strings]; empty means the sheet is complete and consistent."""
    probs = []
    if fresh_md is not None:
        bp = bundle_problem(round_dir, fresh_md)
        if bp:
            probs.append(bp)
    inf_p, so_p = os.path.join(round_dir, "INFORMAL.json"), os.path.join(round_dir, "SIGNOFF.json")
    for p in (inf_p, so_p):
        if not os.path.exists(p):
            probs.append(f"missing {os.path.basename(p)}")
    if probs:
        return probs
    try:
        inf, so = json.load(open(inf_p, encoding="utf-8")), json.load(open(so_p, encoding="utf-8"))
    except ValueError as e:
        return [f"malformed JSON: {e}"]
    for name, lst, key in (("INFORMAL.json", inf.get("rows", []), "result"),
                           ("INFORMAL.json definitions", inf.get("definitions", []), "name"),
                           ("SIGNOFF.json", so.get("rows", []), "result")):
        seen = [x.get(key) for x in lst]
        for dup in sorted({x for x in seen if seen.count(x) > 1}, key=str):
            # a duplicate row is a second, unchecked version of the same entry; the renderer
            # would show one and the check would see the other
            probs.append(f"{name}: {dup!r} appears more than once")
    globals_ = {}
    for g in so.get("global", []) or []:
        gid = str(g.get("id", ""))
        if not re.fullmatch(r"G\d+", gid) or gid in globals_:
            probs.append(f"global difference with a missing, malformed or repeated id: {gid!r}")
            continue
        if not str(g.get("title", "")).strip() or not str(g.get("text", "")).strip():
            probs.append(f"global difference {gid}: empty title or text")
        globals_[gid] = g
    used = set()
    inf_rows = {r.get("result"): r for r in inf.get("rows", [])}
    inf_defs = {d.get("name"): d for d in inf.get("definitions", [])}
    so_rows = {r.get("result"): r for r in so.get("rows", [])}
    # a result the paper-defects record names must not reach the human as "no difference": the
    # Lean states the REPAIRED result (found by a test run's pre-approval audit: two results
    # were defects on record and "Differences: None" on the sheet)
    for label in defect_results(os.path.dirname(round_dir)):
        for res, r in so_rows.items():
            if res and re.match(re.escape(label) + r"\b(?![.\d])", res) and \
                    str(r.get("differences", "")).strip().startswith("None"):
                probs.append(f"{res}: PAPER_DEFECTS.md records a defect in this result, but the "
                             f"sheet says 'Differences: None'")
    # ...and must be CHECK, as must a result true only vacuously (AUDIT_PROTOCOL.md, "Documents a
    # human reads", rule 5): a GLOBAL or OK flag would let the reader skip it
    for src, labels in (("PAPER_DEFECTS.md records a defect in", defect_results(os.path.dirname(round_dir))),
                        ("VACUOUS.md records as true only vacuously",
                         vacuous_results(os.path.dirname(round_dir)))):
        for label in labels:
            for res, r in so_rows.items():
                if res and re.match(re.escape(label) + r"\b(?![.\d])", res) and r.get("flag") != "CHECK":
                    probs.append(f"{res}: {src} this result, so its flag must be CHECK, not "
                                 f"{r.get('flag')!r}")
    for label, _ in rows:
        if label not in inf_rows:
            probs.append(f"INFORMAL.json has no entry for {label}")
        if label not in so_rows:
            probs.append(f"SIGNOFF.json has no entry for {label}")
            continue
        r = so_rows[label]
        for fld in ("paper", "lean", "plain_english", "differences", "junk_values", "flag"):
            if not str(r.get(fld, "")).strip():
                probs.append(f"{label}: empty field `{fld}`")
        if r.get("flag") not in FLAGS:
            probs.append(f"{label}: flag must be OK, CHECK or GLOBAL, not {r.get('flag')!r}")
        if r.get("flag") == "CHECK" and not str(r.get("check_reason", "")).strip():
            probs.append(f"{label}: CHECK needs `check_reason`")
        junk = str(r.get("junk_values", "")).strip()
        if junk and not re.match(r"^(None\b|Handled:|RISK:)", junk):
            probs.append(f"{label}: junk_values must start with None, Handled: or RISK:")
        diff_ = str(r.get("differences", "")).strip()
        gm = GLOBAL_REF.match(diff_)
        if r.get("flag") == "GLOBAL":
            if not gm:
                probs.append(f"{label}: a GLOBAL row's differences must be exactly "
                             f"'Global: G1, G2.' (row-specific differences need CHECK)")
            else:
                for gid in gm.group(1).split(", "):
                    if gid not in globals_:
                        probs.append(f"{label}: refers to {gid}, which is not in `global`")
                    else:
                        used.add(gid)
            if junk.startswith("RISK:"):
                probs.append(f"{label}: a junk-value RISK is row-specific, so the flag must be CHECK")
        for gid in re.findall(r"\bG\d+\b", diff_):
            if gid in globals_:
                used.add(gid)
        if r.get("flag") != "GLOBAL" and (junk.startswith("RISK:") or (diff_ and not diff_.startswith("None"))) and r.get("flag") != "CHECK":
            # the flag is what the mathematician sees first; a difference or a junk-value risk
            # under an OK is the one inconsistency that would let it be skipped
            probs.append(f"{label}: a difference or a junk-value RISK is recorded, so the flag must be CHECK")
        if label in inf_rows and r.get("plain_english", "").strip() != \
                str(inf_rows[label].get("plain_english", "")).strip():
            probs.append(f"{label}: plain_english differs from the blind reading in INFORMAL.json "
                         f"(it must be copied verbatim)")
    for gid in sorted(set(globals_) - used):
        probs.append(f"global difference {gid} is referenced by no row")
    nf_labels = {lab for lab, _ in not_formalized(cfg)}
    for n in so.get("not_formalized", []) or []:
        if n.get("result") not in nf_labels:
            probs.append(f"not_formalized note for {n.get('result')!r}, which the index does not "
                         f"mark as not formalized")
        elif not str(n.get("note", "")).strip():
            probs.append(f"not_formalized note for {n.get('result')!r} is empty")
    for d in defs:
        # exact key: the informalizer copies the bundle's heading verbatim. A short-name match
        # once let `Other.thing` count as explaining `N.thing`.
        if d not in inf_defs:
            probs.append(f"definition {d} is used by an approved statement but not explained")
        elif not str(inf_defs[d].get("plain_english", "")).strip():
            probs.append(f"definition {d}: empty explanation")
    extra = set(so_rows) - {l for l, _ in rows}
    for e in sorted(x for x in extra if x):
        probs.append(f"SIGNOFF.json has an entry for {e!r}, which is not an index row")
    return probs


def source_macros(cfg):
    """Macro and environment definitions from a .tex source's preamble, so the paper's statements
    can be typeset on the sheet as the paper typesets them. A definition may span several lines
    (one test paper's matrix macro spans twelve); it is kept once its
    braces balance. Definitions using `@` are left out; whatever still breaks is covered by the
    fallback in render()."""
    src = cfg.get("source_pdf", "")
    if not src.endswith(".tex") or not os.path.exists(src):
        return ""
    pre = open(src, encoding="utf-8", errors="replace").read().split("\\begin{document}")[0]
    start = re.compile(r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator|"
                       r"newenvironment|renewenvironment)\*?\s*[{\\]")

    def depth(t):
        t = re.sub(r"\\[{}]", "", re.sub(r"(?<!\\)%.*", "", t))   # escaped braces, comments
        return t.count("{") - t.count("}")

    keep, cur, d = [], None, 0
    for line in pre.splitlines():
        t = line.strip()
        if cur is None:
            if not start.match(t):
                continue
            cur, d = [t], depth(t)
        else:
            cur.append(t)
            d += depth(t)
        if d <= 0:
            block = "\n".join(cur)
            if d == 0 and "@" not in block:
                if block.startswith("\\newcommand"):
                    block = block.replace("\\newcommand", "\\providecommand", 1)
                keep.append(block)
            cur = None
    return "\n".join(keep)


def paper_labels(cfg):
    """{label: (kind, number)} from the paper's compiled .aux, looked for next to the .tex and in a
    sibling `build/` directory (RUN.md has the paper compiled in scratch for its numbering). Empty
    if there is none."""
    src = cfg.get("source_pdf", "")
    if not src.endswith(".tex"):
        return {}
    stem = os.path.splitext(os.path.basename(src))[0]
    d = os.path.dirname(src)
    for aux in (os.path.join(d, stem + ".aux"), os.path.join(os.path.dirname(d), "build", stem + ".aux")):
        if os.path.exists(aux):
            text = open(aux, encoding="utf-8", errors="replace").read()
            nums = dict(re.findall(r"\\newlabel\{([^}@]+)\}\{\{([^}]*)\}", text))
            kinds = dict(re.findall(r"\\newlabel\{([^}]+)@cref\}\{\{\[([^\]]*)\]", text))
            return {l: (kinds.get(l, ""), n) for l, n in nums.items()}
    return {}


def theorem_envs(cfg):
    """Theorem-like environment names the paper declares (\\newtheorem{name}, \\declaretheorem)."""
    src = cfg.get("source_pdf", "")
    if not src.endswith(".tex") or not os.path.exists(src):
        return set()
    pre = open(src, encoding="utf-8", errors="replace").read().split("\\begin{document}")[0]
    return set(re.findall(r"\\(?:newtheorem|declaretheorem)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", pre))


def strip_theorem_envs(text, names):
    """The statement inside `\\begin{lemma}[...] ... \\end{lemma}` (and `restatable`), without the
    wrapper, `\\label` or `\\qed`: the sheet has its own heading per result, and the wrapper's
    environment is not defined there (it broke a test run's sheet)."""
    envs = set(names) | {"restatable", "theorem", "lemma", "corollary", "proposition",
                         "observation", "claim", "definition", "remark", "fact", "conjecture"}
    alt = "|".join(sorted((re.escape(e) for e in envs), key=len, reverse=True))
    text = re.sub(r"\\begin\{restatable\}(?:\[[^\]]*\])?\{[^}]*\}\{[^}]*\}", "", text)
    text = re.sub(r"\\begin\{(?:" + alt + r")\*?\}(?:\[[^\]]*\])?", "", text)
    text = re.sub(r"\\end\{(?:" + alt + r")\*?\}", "", text)
    text = re.sub(r"\\label\{[^}]*\}", "", text)
    return re.sub(r"\\qed\b", "", text).strip()


def resolve_refs(text, labels):
    """`\\cref{L}` / `\\Cref{L}` -> "Lemma 1.2", `\\ref{L}` -> "1.2", from the paper's own .aux.
    An unknown label is shown as [L] rather than breaking the sheet (the paper's statements quote
    cross-references; the sheet has no .aux of its own)."""
    def one(m):
        cmd, keys = m.group(1), m.group(2).split(",")
        out = []
        for key in keys:
            kind, num = labels.get(key.strip(), ("", None))
            if num is None:
                out.append("[" + key.strip().replace("_", "\\_") + "]")
            elif cmd in ("cref", "Cref") and kind:
                out.append(kind.capitalize() + "~" + num)
            else:
                out.append(num)
        return ", ".join(out)
    return re.sub(r"\\(cref|Cref|ref|eqref|autoref)\{([^}]*)\}", one, text)


# The first line of a sheet whose statements no person will review (RUN.md, intake question 5c,
# hands-off): the sheet is still delivered, and must not read as a human sign-off.
HANDS_OFF_LINE = ("Approved by the formalizing agent; no person reviewed these statements "
                  "(hands-off chosen at intake).")


def render(cfg, round_dir, changed=None):
    """SIGNOFF.md and SIGNOFF.pdf. The paper's statements are typeset as LaTeX (the reader is a
    mathematician); if that does not compile, the PDF is rebuilt with them shown as source text,
    and a warning says so -- the sheet must never fail to exist because of one macro."""
    ok = _render(cfg, round_dir, changed, raw_paper=True)
    render.fell_back = not ok
    if not ok:
        print("warning: the paper's statements did not typeset; they are shown as LaTeX source")
        ok = _render(cfg, round_dir, changed, raw_paper=False)
    return ok


def _render(cfg, round_dir, changed=None, raw_paper=True):
    import make_report as mr
    labels = paper_labels(cfg)
    envs = theorem_envs(cfg)
    so = json.load(open(os.path.join(round_dir, "SIGNOFF.json"), encoding="utf-8"))
    inf = json.load(open(os.path.join(round_dir, "INFORMAL.json"), encoding="utf-8"))
    rows = so.get("rows", [])
    n_check = sum(1 for r in rows if r.get("flag") == "CHECK")
    glob = so.get("global", []) or []
    uses = {g.get("id"): [r.get("result") for r in rows
                          if re.search(r"\b" + re.escape(str(g.get("id"))) + r"\b",
                                       str(r.get("differences", "")))] for g in glob}
    n_glob = sum(1 for r in rows if r.get("flag") == "GLOBAL")
    hands_off = project.involvement(cfg) == "hands-off"
    head = (f"# Statement sign-off — {cfg['source_cite']}\n\n"
            + (f"**{HANDS_OFF_LINE}**\n\n" if hands_off else "") +
            f"Commit `{so.get('commit', '?')}`. {len(rows)} results, {n_check} flagged CHECK, "
            f"{n_glob} differing only through the {len(glob)} global difference(s).\n\n"
            "**Approving this sheet means: each Lean statement says what the paper says. "
            "It says nothing about the proofs.** The plain-English reading of each Lean statement "
            "was written by a reviewer instructed not to read the paper; the comparison with the paper "
            "was written by a second reviewer. Tick a box only if you agree with the comparison.\n")
    md = [head]
    if glob:
        md.append("\n## Global differences — approve each once; leaving one unticked excludes "
                  "every result that uses it\n")
        for g in glob:
            md += [f"\n### [ ] {g.get('id')}: {g.get('title')}", f"\n{g.get('text')}",
                   "\nUsed by: " + ", ".join(uses.get(g.get("id")) or ["(none)"])]
    changed = changed or {}
    for r in rows:
        md += [f"\n## [ ] {r.get('result')}  —  {r.get('flag')}"
               + (f": {r.get('check_reason')}" if r.get("flag") == "CHECK" else "")
               + (f"  —  CHANGED since the approval of {changed[r.get('result')]}"
                  if r.get("result") in changed else ""),
               f"\n**Paper.** {r.get('paper')}",
               f"\n**Lean.** " + "; ".join(f"`{x}`" for x in _as_list(r.get("lean"))),
               f"\n**The Lean, in plain English (blind reading).** {r.get('plain_english')}",
               f"\n**Differences.** {r.get('differences')}",
               f"\n**Junk values.** {r.get('junk_values')}"]
        if str(r.get("assumed", "")).strip():
            md.append(f"\n**Literature results taken as hypotheses.** {r.get('assumed')}")
    nf = not_formalized(cfg)
    nf_note = {n.get("result"): n.get("note") for n in so.get("not_formalized", []) or []}
    if nf:
        md.append("\n## Results NOT formalized (not on this sheet)\n")
        md += [f"* [ ] **{lab}** — {why}" + (f" **Open decision:** {nf_note[lab]}" if lab in nf_note else "")
               for lab, why in nf]
    md.append("\n## Definitions the statements use (blind reading)\n")
    for d in inf.get("definitions", []):
        md.append(f"* `{d.get('name')}` — {d.get('plain_english')}")
    md_text = "\n".join(md) + "\n"
    open(os.path.join(round_dir, "SIGNOFF.md"), "w", encoding="utf-8").write(md_text)

    pre = mr.PREAMBLE
    if raw_paper:
        pre = pre.replace("\\begin{document}", "\\usepackage{amsmath,amssymb}\n"
                          + source_macros(cfg) + "\n\\begin{document}", 1)
    t = pre + (("\\noindent\\fbox{\\parbox{\\dimexpr\\linewidth-2\\fboxsep\\relax}{\\textbf{"
                + mr.tex(HANDS_OFF_LINE) + "}}}\\par\\medskip\n") if hands_off else "") + (
               "\\begin{center}\n{\\LARGE\\sffamily\\bfseries Statement sign-off}\\\\[0.4em]\n"
                       "{\\large " + mr.tex(cfg["source_cite"]) + "}\\\\[0.4em]\n{\\small commit "
                       + mr.tex(so.get("commit", "?")) + "; " + str(len(rows)) + " results, "
                       + str(n_check) + " flagged CHECK, " + str(n_glob) + " GLOBAL}\n\\end{center}\n\n")
    if glob:
        t += ("\\section*{Global differences}\n\\noindent Each is approved once, here; leaving "
              "one unticked excludes every result that uses it.\\par\\medskip\n")
        for g in glob:
            t += mr.render_entry("\\framebox[1.1em]{\\rule{0pt}{0.8em}}\\quad " + mr.tex(
                f"{g.get('id')}: {g.get('title')}"),
                [("Difference", mr.tex(g.get("text", ""))),
                 ("Used by", mr.tex(", ".join(uses.get(g.get("id")) or ["(none)"])))]) + "\\vspace{1em}\n"
        t += "\\section*{Results}\n"
    t += ("\\noindent\\textbf{Approving this sheet means: each Lean statement says what the paper "
          "says. It says nothing about the proofs.} The plain-English reading of each Lean statement "
          "was written by a reviewer instructed not to read the paper; the comparison with the "
          "paper by a second reviewer. Tick a box only if you agree with the comparison; write on "
          "the page where you do not.\n\n")
    bundle = {}
    bp = os.path.join(round_dir, "STATEMENTS_BUNDLE.md")
    if os.path.exists(bp):
        for sec in re.split(r"^## ", open(bp, encoding="utf-8").read(), flags=re.M)[1:]:
            head_, _, body_ = sec.partition("\n")
            bundle[head_.strip()] = "\n".join(re.findall(r"```lean\n(.*?)```", body_, re.S)).strip()
    for r in rows:
        flag = r.get("flag", "?")
        title = ("\\framebox[1.1em]{\\rule{0pt}{0.8em}}\\quad " + mr.tex(r.get("result", "?")) + "\\hfill\\normalfont\\small "
                 + ("\\textbf{CHANGED since " + mr.tex(changed[r.get("result")]) + "}\\quad "
                    if r.get("result") in changed else "")
                 + ("\\textbf{CHECK}" if flag == "CHECK" else
                    "GLOBAL (" + mr.tex(str(r.get("differences", "")).replace("Global: ", "").rstrip(".")) + ")"
                    if flag == "GLOBAL" else "OK"))
        paper = r.get("paper", "")
        if raw_paper:
            paper = strip_theorem_envs(resolve_refs(paper, labels), envs)
        fields = [("Paper", paper if raw_paper else mr.tex(paper)),
                  ("Lean", mr.tex("; ".join(f"`{x}`" for x in _as_list(r.get("lean"))))
                   + ("\\par{\\small " + "\\\\".join(mr.tex(f"`{ln}`") for ln in
                       bundle[r.get("result")].splitlines() if ln.strip() and not ln.startswith("--"))
                      + "}" if bundle.get(r.get("result")) else "")),
                  ("Lean, in plain English (blind)", mr.tex(r.get("plain_english", ""))),
                  ("Differences", mr.tex(r.get("differences", ""))),
                  ("Junk values", mr.tex(r.get("junk_values", "")))]
        if flag == "CHECK":
            fields.insert(0, ("Look at", "\\textbf{" + mr.tex(r.get("check_reason", "")) + "}"))
        if str(r.get("assumed", "")).strip():
            fields.append(("Literature results taken as hypotheses", mr.tex(r.get("assumed"))))
        t += mr.render_entry(title, fields) + "\\vspace{1.2em}\n"
    if nf:
        t += "\\section*{Results not formalized (not on this sheet)}\n\\begin{itemize}\n"
        t += "".join("\\item \\textbf{" + mr.tex(lab) + "} --- " + mr.tex(why)
                     + ("\\par\\textbf{Open decision:} " + mr.tex(nf_note[lab]) if lab in nf_note else "")
                     + "\n" for lab, why in nf)
        t += "\\end{itemize}\n"
    t += "\\section*{Definitions the statements use (blind reading)}\n"
    defs_ = inf.get("definitions", [])
    if not defs_:
        # an empty description list is a LaTeX error; say so in words instead
        t += "None beyond the definitions that are results of the paper themselves (above).\n"
    else:
        t += "\\begin{description}\n"
        for d in defs_:
            t += "\\item[" + mr.tex(f"`{d.get('name')}`") + "] " + mr.tex(d.get("plain_english", "")) + "\n"
        t += "\\end{description}\n"
    t += "\\end{document}\n"
    texf = os.path.join(round_dir, "SIGNOFF.tex")
    open(texf, "w", encoding="utf-8").write(t)
    ok = True
    for _ in range(2):
        r = subprocess.run(["xelatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "SIGNOFF.tex"],
                           cwd=round_dir, capture_output=True, text=True)
        ok = r.returncode == 0
        if not ok:
            print("xelatex FAILED:", "; ".join(l for l in r.stdout.splitlines() if l.startswith("!"))[:400])
            break
    _render.missing = mr.missing_glyphs(os.path.join(round_dir, "SIGNOFF.log")) if ok else []
    for ext in (".aux", ".log", ".out"):
        f = os.path.join(round_dir, "SIGNOFF" + ext)
        if os.path.exists(f):
            os.remove(f)
    return ok


def approvals(rounds_dir):
    """Earlier approval files, newest last: APPROVED_FINGERPRINTS.json and the dated copies
    re-approval moves aside."""
    fs = glob.glob(os.path.join(rounds_dir, "APPROVED_FINGERPRINTS*.json"))
    docs = []
    for f in fs:
        try:
            docs.append(json.load(open(f)))
        except ValueError:
            pass
    return sorted(docs, key=lambda d: (d.get("date", ""), d.get("commit", "")))


def approve(cfg, round_dir, rows, defs, fps, snapshot, excluded=(), how="individual", by=None, note=""):
    """(document, problems). The approval freezes the fingerprints of the declarations on the
    sheet -- each approved result's statements, and through their closure every definition they
    use -- and only if those are unchanged since the sheet was generated: the approval covers what
    the sheet showed, not whatever HEAD has become. `by` records who decided (BY below)."""
    probs = check(cfg, round_dir, rows, defs)
    labels = {l for l, _ in rows}
    unknown = sorted(set(excluded) - labels)
    if unknown:
        probs.append(f"--exclude names results not on the sheet: {unknown}")
    approved_keys = sorted({k for l, ks in rows if l not in excluded for k in ks})
    for k in approved_keys + list(defs):
        if k not in fps:
            probs.append(f"{k}: no longer exists")
        elif snapshot.get(k) != fps[k]:
            probs.append(f"{k}: changed since the sheet was generated -- regenerate the sheet")
    if by not in BY:
        probs.append(f"approver must be one of {sorted(BY)} (who decided?), got {by!r}")
    if by == "agent" and excluded:
        probs.append("--by agent approves EVERYTHING on the sheet (Checkpoint B choice (c)); "
                     "excluding results means a human chose them, i.e. --by human")
    doc = {"round": os.path.basename(round_dir), "commit": None, "date": None, "how": how,
           "by": by, "note": note,
           "rows": {l: {"decls": ks, "status": "excluded" if l in excluded else "approved"}
                    for l, ks in rows},
           "fingerprints": {k: fps[k] for k in approved_keys if k in fps}}
    return doc, probs


# Who decided at Checkpoint B (RUN.md, Stage 2, step 8). The user is asked to choose:
#   human -- the user read SIGNOFF.pdf and approved (all, or excluding some results);
#   agent -- the user chose to let the agent decide; the agent approved everything on the sheet
#            WITHOUT a human reading it. The report must say so in those words.
BY = {"human", "agent"}


def changed_since_approval(rounds_dir, rows, fps):
    """{result label: date} for results whose statements changed since the last approval, or
    that the last approval did not cover. Shown on the sheet, so a re-approval reads as a diff."""
    prev = approvals(rounds_dir)
    if not prev:
        return {}
    last = prev[-1]
    out = {}
    for label, ks in rows:
        if any(k not in last.get("fingerprints", {}) or last["fingerprints"][k] != fps.get(k) for k in ks):
            out[label] = last.get("date", "?")
    return out


def _as_list(x):
    return x if isinstance(x, list) else [x] if x else []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["bundle", "check", "render", "approve"])
    ap.add_argument("--exclude", default="", help="approve: comma-separated results NOT approved")
    ap.add_argument("--how", choices=["individual", "blanket"],
                    help="approve: did the human answer per result, or say 'all OK'?")
    ap.add_argument("--by", choices=sorted(BY),
                    help="approve: who decided -- 'human' (the user read the sheet) or 'agent' "
                         "(the user chose to let the agent approve without reading)")
    ap.add_argument("--note", default="",
                    help="approve: one sentence for the record, e.g. statements the human approved "
                         "individually inside an agent approval")
    ap.add_argument("--project")
    ap.add_argument("--round")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--lean", action="store_true",
                    help="selftest: also run the Lean-backed checks (needs a built project)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest() or (selftest_lean() if a.lean else 0)
    if not a.cmd or not a.round:
        ap.error("give a command and --round")
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    rd = os.path.join(project.REPO, cfg["rounds_dir"], a.round)
    if not os.path.isdir(rd):
        print(f"FAIL: no round directory {rd}", file=sys.stderr); return 2
    try:
        md, rows, defs = build_bundle(cfg)
    except RuntimeError as e:
        print(f"FAIL: could not read the compiled project (build it first):\n{e}", file=sys.stderr)
        return 2
    if a.cmd == "bundle":
        p = os.path.join(rd, "STATEMENTS_BUNDLE.md")
        open(p, "w", encoding="utf-8").write(md)
        print(f"wrote {os.path.relpath(p, project.REPO)}: {len(rows)} results, {len(defs)} definitions")
        for m in build_bundle.missing:
            print(f"PROBLEM  {m}")
        # An incomplete bundle produces a sheet with holes a signer cannot see. Fix the index or
        # lean_files and rebuild; do not hand this bundle to the informalizer.
        return 1 if build_bundle.missing else 0
    if a.cmd == "check":
        probs = check(cfg, rd, rows, defs, md)
        for p in probs:
            print(f"PROBLEM  {p}")
        print(f"sign-off check: {len(rows)} results, {len(defs)} definitions, {len(probs)} problem(s)")
        return 1 if probs else 0
    if a.cmd == "render":
        probs = check(cfg, rd, rows, defs, md)
        for p in probs:
            print(f"PROBLEM  {p}")
        if probs:
            print(f"FAIL: the sheet is incomplete ({len(probs)} problems); run `check` and fix first")
            return 1
        import fingerprint
        fps = fingerprint.compute(cfg)
        changed = changed_since_approval(os.path.join(project.REPO, cfg["rounds_dir"]), rows, fps)
        ok = render(cfg, rd, changed)
        if ok and getattr(render, "fell_back", False):
            print("PROBLEM  the paper's statements did not typeset and are shown as LaTeX source; the "
                  "sheet is readable but not what the approver should compare against -- fix the cause "
                  "(see the xelatex error above) and render again")
            ok = False
        gone = getattr(_render, "missing", [])
        if ok and gone:
            print("PROBLEM  the PDF drops characters (no glyph in the font): " + " ".join(gone)
                  + " -- map them in make_report.UNI_MATH; the human would read a sentence with holes")
            ok = False
        print(f"wrote SIGNOFF.md{' and SIGNOFF.pdf' if ok else ' (PDF FAILED)'}"
              + (f"; {len(changed)} result(s) marked CHANGED since the last approval" if changed else ""))
        return 0 if ok else 1
    if a.cmd == "approve":
        if not a.how:
            print("FAIL: say --how individual (the human answered per result) or --how blanket "
                  "('all OK'); the report discloses which", file=sys.stderr)
            return 2
        if not a.by:
            print("FAIL: say --by human (the user read SIGNOFF.pdf and approved) or --by agent (the "
                  "user chose to let the agent approve without reading); the report discloses which",
                  file=sys.stderr)
            return 2
        import fingerprint, datetime
        rdir = os.path.join(project.REPO, cfg["rounds_dir"])
        target = os.path.join(rdir, fingerprint.APPROVED)
        if os.path.exists(target):
            print(f"FAIL: {target} exists. For a re-approval, move it aside first "
                  f"(APPROVED_FINGERPRINTS.<date>.json) and record why in RUN_LOG.md.", file=sys.stderr)
            return 2
        snap_p = os.path.join(rd, "FINGERPRINTS.json")
        if not os.path.exists(snap_p):
            print(f"FAIL: {snap_p} missing: the sheet's round has no fingerprint snapshot", file=sys.stderr)
            return 2
        bp = bundle_problem(rd, md)
        if bp:
            print(f"PROBLEM  {bp}\napproval REFUSED")
            return 1
        fps = fingerprint.compute(cfg)
        excluded = [x.strip() for x in a.exclude.split(",") if x.strip()]
        doc, probs = approve(cfg, rd, rows, defs, fps, json.load(open(snap_p))["fingerprints"],
                             excluded, a.how, a.by, a.note)
        for p_ in probs:
            print(f"PROBLEM  {p_}")
        if probs:
            print("approval REFUSED")
            return 1
        doc["commit"] = fingerprint.head(project.REPO)
        doc["date"] = datetime.date.today().isoformat()
        json.dump(doc, open(target, "w"), indent=1, ensure_ascii=False)
        n_ok = sum(1 for r in doc["rows"].values() if r["status"] == "approved")
        print(f"wrote {os.path.relpath(target, project.REPO)}: {n_ok} result(s) approved "
              f"({a.how}, by {a.by}), {len(excluded)} excluded, {len(doc['fingerprints'])} declarations frozen\n"
              f"now commit it, alone: git -C audits add -A {os.path.relpath(rdir, project.AUDITS)} "
              f"&& git -C audits commit -m \"approve {a.round}\"")
        return 0


def selftest_lean():
    """Signatures as printed for the sheet show the information each case below used to hide.
    Exit 0 ok, 1 a check failed, 3 the Lean fixture itself did not run (not a verdict on the
    property; tests/mutants.py counts it as CRASHED, never as a kill)."""
    d = tempfile.mkdtemp(prefix="sgt-")
    f = os.path.join(d, "SgT.lean")
    open(f, "w", encoding="utf-8").write(
        "import Mathlib.Data.Real.Basic\nnamespace SgT\n"
        "theorem hid (m : Nat) : ∃ x : Fin (m + 1), x.val = 0 := ⟨0, rfl⟩\n"
        "theorem lam (m : Nat) : (fun y : Fin (m + 2) => y.val) 0 = 0 := rfl\n"
        "theorem bpr : ∃ x > (0 : ℝ), x = 1 := ⟨1, one_pos, rfl⟩\n"
        "theorem bpn : ∃ x > (0 : ℕ), x = 1 := ⟨1, Nat.one_pos, rfl⟩\n"
        "theorem cst (a b : ℕ) (h : ((a - b : ℕ) : ℝ) = 0) : True := trivial\n"
        "theorem uq : ∃! x : Fin 3, x.val = 0 := ⟨0, rfl, fun y h => Fin.ext h⟩\n"
        "end SgT\n")
    names = ["SgT.hid", "SgT.lam", "SgT.bpr", "SgT.bpn", "SgT.cst", "SgT.uq"]
    ok = True
    try:
        sigs = signatures({"sweep": {"mode": "file", "file": f}}, names)
    except RuntimeError as e:
        print(f"  CRASH  signature fixture did not run: {e}")
        return 3
    finally:
        shutil.rmtree(d, ignore_errors=True)
    for name, cond in [
            ("an ∃-bound variable's type is printed (pp.funBinderTypes)",
             "(x : Fin (m + 1))" in sigs["SgT.hid"]),
            ("a λ-bound variable's type is printed", "(y : Fin (m + 2))" in sigs["SgT.lam"]),
            ("∃ x > 0 over ℝ shows x : ℝ (pp.mathlib.binderPredicates false)",
             "(x : ℝ)" in sigs["SgT.bpr"]),
            ("∃ x > 0 over ℕ shows x : ℕ, so the two differ on the sheet",
             "(x : ℕ)" in sigs["SgT.bpn"]),
            ("a cast shows its target type (pp.coercions.types)",
             ": ℝ)" in sigs["SgT.cst"] and "a - b" in sigs["SgT.cst"]),
            ("∃! shows the bound variable's type", "x : Fin 3" in sigs["SgT.uq"])]:
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)
    if not ok:
        print("  signatures were:", sigs)
    print("selftest (lean):", "ok" if ok else "FAILED")
    return 0 if ok else 1


def selftest():
    import tempfile, shutil
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    d = tempfile.mkdtemp()
    try:
        rows = [("Theorem 1.1", ["N.main"]), ("Lemma 1.2", ["N.aux"])]
        defs = ["N.thing"]
        cfg = {"source_cite": "test"}
        good_inf = {"rows": [{"result": "Theorem 1.1", "plain_english": "For all n, f(n) > n."},
                             {"result": "Lemma 1.2", "plain_english": "Two is even."}],
                    "definitions": [{"name": "N.thing", "plain_english": "f(n) = n + 1."}]}
        row = lambda res, pe, flag="OK", **kw: dict(
            {"result": res, "paper": "p", "lean": ["N.x"], "plain_english": pe,
             "differences": "None.", "junk_values": "None.", "flag": flag}, **kw)
        good_so = {"commit": "abc", "rows": [row("Theorem 1.1", "For all n, f(n) > n."),
                                             row("Lemma 1.2", "Two is even.", "CHECK",
                                                 check_reason="parity convention")]}

        def setup(inf, so):
            for f in ("INFORMAL.json", "SIGNOFF.json"):
                p = os.path.join(d, f)
                if os.path.exists(p):
                    os.remove(p)
            if inf is not None:
                json.dump(inf, open(os.path.join(d, "INFORMAL.json"), "w"))
            if so is not None:
                json.dump(so, open(os.path.join(d, "SIGNOFF.json"), "w"))
            return check(cfg, d, rows, defs)

        say("complete, consistent sheet passes", setup(good_inf, good_so) == [])
        import make_report as mr
        say("multiplication in plain English keeps both asterisks",
            mr.tex("The product k * n and the product a * b") ==
            "The product k * n and the product a * b")
        say("Markdown emphasis still renders",
            mr.tex("An *important* product") == r"An \emph{important} product")

        # a result named in PAPER_DEFECTS.md must not be shown as "Differences: None"
        rr = os.path.join(d, "rounds-pd"); rd2 = os.path.join(rr, "R"); os.makedirs(rd2)
        json.dump(good_inf, open(os.path.join(rd2, "INFORMAL.json"), "w"))
        so2 = {"commit": "abc", "rows": [row("Theorem 1.1", "For all n, f(n) > n."),
                                        row("Lemma 1.2", "Two is even.", "CHECK",
                                            check_reason="parity convention")]}
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        open(os.path.join(rr, "PAPER_DEFECTS.md"), "w").write(
            "| # | where | severity |\n|---|---|---|\n| 1 | tex 3, Theorem 1.1 | S1 |\n"
            "| 2 | Lemma 1.20 (not on the sheet) | S4 |\n")
        pd = check(cfg, rd2, rows, defs)
        say("a result with a recorded paper defect shown as 'Differences: None' fails",
            any(p.startswith("Theorem 1.1: PAPER_DEFECTS") and "Differences: None" in p for p in pd))
        say("...and 'Lemma 1.20' in the record does not match the sheet's 'Lemma 1.2'",
            not any(p.startswith("Lemma 1.2:") for p in pd))
        so2["rows"][0] = row("Theorem 1.1", "For all n, f(n) > n.", "CHECK", check_reason="x",
                             differences="Paper defect (PAPER_DEFECTS row 1): the Lean states the repair.")
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        say("stating the difference clears it", check(cfg, rd2, rows, defs) == [])
        so2["rows"][0]["flag"] = "GLOBAL"
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        say("a result with a recorded paper defect flagged GLOBAL fails",
            any("flag must be CHECK" in p and p.startswith("Theorem 1.1") for p in check(cfg, rd2, rows, defs)))
        so2["rows"][0]["flag"] = "CHECK"
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        so2["rows"][1]["flag"] = "OK"
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n"
            "| 1 | Lemmas 1.1–1.2 | setting is empty | |\n")
        say("a result in an open VACUOUS.md range (blank status) flagged OK fails",
            any(p.startswith("Lemma 1.2:") and "vacuously" in p for p in check(cfg, rd2, rows, defs)))
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n"
            "| 1 | Lemma 1.2 | setting is empty | repaired in abc1234 |\n")
        say("a repaired VACUOUS.md row does not force CHECK", check(cfg, rd2, rows, defs) == [])
        os.remove(os.path.join(rr, "VACUOUS.md"))
        so2["rows"][1]["flag"] = "CHECK"
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        say("missing SIGNOFF.json fails", any("missing" in p for p in setup(good_inf, None)))
        so = dict(good_so, rows=good_so["rows"][:1])
        say("a result missing from the sheet fails", any("Lemma 1.2" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[row("Theorem 1.1", "For all n, f(n) >= n."), good_so["rows"][1]])
        say("plain English rewritten by the writer fails",
            any("differs from the blind reading" in p for p in setup(good_inf, so)))
        inf = dict(good_inf, definitions=[])
        say("an unexplained definition fails", any("N.thing" in p for p in setup(inf, good_so)))
        so = dict(good_so, rows=[row("Theorem 1.1", "For all n, f(n) > n.", "MAYBE"), good_so["rows"][1]])
        say("an invalid flag fails", any("flag must be" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[good_so["rows"][0], row("Lemma 1.2", "Two is even.", "CHECK")])
        say("CHECK without a reason fails", any("check_reason" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[row("Theorem 1.1", "For all n, f(n) > n.", junk_values=""),
                                 good_so["rows"][1]])
        say("an empty junk-values field fails", any("junk_values" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[dict(good_so["rows"][0], junk_values="sInf appears"), good_so["rows"][1]])
        say("junk_values in free form (not None/Handled:/RISK:) fails",
            any("must start with" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[dict(good_so["rows"][0], junk_values="RISK: sInf of empty set"), good_so["rows"][1]])
        say("a junk-value RISK under an OK flag fails", any("must be CHECK" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[dict(good_so["rows"][0], differences="Lean drops nonemptiness"), good_so["rows"][1]])
        say("a recorded difference under an OK flag fails", any("must be CHECK" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[dict(good_so["rows"][0], junk_values="Handled: S nonempty"), good_so["rows"][1]])
        say("a handled junk value under OK is fine", setup(good_inf, so) == [])
        so = dict(good_so, rows=good_so["rows"] + [row("Theorem 9.9", "x")])
        say("an entry that is not an index row fails", any("9.9" in p for p in setup(good_inf, so)))
        # rendering produces a PDF
        setup(good_inf, good_so)
        setup(dict(good_inf, definitions=[]), good_so)
        say("render compiles when there are no separate definitions",
            render(cfg, d) and os.path.exists(os.path.join(d, "SIGNOFF.pdf")))
        if os.path.exists(os.path.join(d, "SIGNOFF.pdf")):
            os.remove(os.path.join(d, "SIGNOFF.pdf"))
        setup(good_inf, good_so)
        so_m = dict(good_so, rows=[dict(good_so["rows"][0], paper="For $k\\ge 1$ the set $\\mathbb{N}$"),
                                   good_so["rows"][1]])
        setup(good_inf, so_m)
        okm = render(cfg, d)
        txt = subprocess.run(["pdftotext", os.path.join(d, "SIGNOFF.pdf"), "-"],
                             capture_output=True, text=True).stdout if okm else ""
        say("the paper's LaTeX is typeset (≥ appears, not \\ge)", okm and "≥" in txt and "\\ge" not in txt)
        so_b = dict(good_so, rows=[dict(good_so["rows"][0], paper="$\\undefinedmacroxyz{1}$"),
                                   good_so["rows"][1]])
        setup(good_inf, so_b)
        say("an uncompilable paper statement falls back to source text; the PDF still exists",
            render(cfg, d) and os.path.exists(os.path.join(d, "SIGNOFF.pdf")))
        setup(good_inf, good_so)
        say("render writes SIGNOFF.md and compiles SIGNOFF.pdf",
            render(cfg, d) and os.path.exists(os.path.join(d, "SIGNOFF.pdf"))
            and "[ ] Lemma 1.2" in open(os.path.join(d, "SIGNOFF.md")).read())
        say("an involved-level sheet does not carry the hands-off line",
            HANDS_OFF_LINE not in open(os.path.join(d, "SIGNOFF.md")).read())
        okh = render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d)
        txh = subprocess.run(["pdftotext", os.path.join(d, "SIGNOFF.pdf"), "-"],
                             capture_output=True, text=True).stdout if okh else ""
        say("under hands-off the sheet OPENS with 'Approved by the formalizing agent; no person reviewed ...'",
            okh and " ".join(txh.split()).replace("-", "").startswith(HANDS_OFF_LINE.replace("-", ""))
            and open(os.path.join(d, "SIGNOFF.md")).read().split("\n\n")[1] == f"**{HANDS_OFF_LINE}**")
        render(cfg, d)
        # global differences: stated once, approved once, used by GLOBAL rows
        g1 = {"id": "G1", "title": "witnesses are non-degenerate", "text": "paper: any size; Lean: ≥ 1 row"}
        so_g = dict(good_so, **{"global": [g1]},
                    rows=[row("Theorem 1.1", "For all n, f(n) > n.", "GLOBAL", differences="Global: G1."),
                          good_so["rows"][1]])
        say("a GLOBAL row citing a stated global difference passes", setup(good_inf, so_g) == [])
        say("render shows the global difference and its users",
            render(cfg, d) and "G1: witnesses are non-degenerate" in open(os.path.join(d, "SIGNOFF.md")).read()
            and "Used by: Theorem 1.1" in open(os.path.join(d, "SIGNOFF.md")).read())
        bad = dict(so_g, rows=[dict(so_g["rows"][0], differences="Global: G1. Also the Lean drops k = 0."),
                               so_g["rows"][1]])
        say("a GLOBAL row with a difference of its own fails (must be CHECK)",
            any("must be exactly" in p for p in setup(good_inf, bad)))
        bad = dict(so_g, rows=[dict(so_g["rows"][0], differences="Global: G7."), so_g["rows"][1]])
        say("a GLOBAL row citing an unknown global fails", any("G7" in p for p in setup(good_inf, bad)))
        bad = dict(so_g, rows=[row("Theorem 1.1", "For all n, f(n) > n."), so_g["rows"][1]])
        say("a global difference no row uses fails", any("referenced by no row" in p for p in setup(good_inf, bad)))
        bad = dict(so_g, rows=[dict(so_g["rows"][0], junk_values="RISK: sInf"), so_g["rows"][1]])
        say("a junk-value RISK cannot hide under GLOBAL", any("row-specific" in p for p in setup(good_inf, bad)))
        so = dict(good_so, rows=good_so["rows"] + [good_so["rows"][0]])
        say("a duplicated result row fails", any("more than once" in p for p in setup(good_inf, so)))
        inf = dict(good_inf, definitions=[{"name": "Other.thing", "plain_english": "x"}])
        say("a definition is explained only under its exact name", any("N.thing" in p for p in setup(inf, good_so)))
        inf = dict(good_inf, definitions=[{"name": "N.thing", "plain_english": ""}])
        say("an empty definition explanation fails", any("empty explanation" in p for p in setup(inf, good_so)))
        so = dict(good_so, rows=[dict(good_so["rows"][0], differences=""), good_so["rows"][1]])
        say("an empty `differences` fails", any("differences" in p for p in setup(good_inf, so)))
        so = dict(good_so, rows=[dict(good_so["rows"][0], plain_english=""), good_so["rows"][1]])
        inf = dict(good_inf, rows=[dict(good_inf["rows"][0], plain_english=""), good_inf["rows"][1]])
        say("an empty blind reading fails even when copied verbatim",
            any("plain_english" in p for p in setup(inf, so)))
        inf = dict(good_inf, rows=good_inf["rows"][1:])
        say("a result missing from INFORMAL.json fails", any("INFORMAL.json has no entry" in p for p in setup(inf, good_so)))
        # resolve: exact, unique suffix, ambiguity, private keys
        keys = {"N.main": 1, "N.aux (private in N.A)": 1, "M.aux": 1, "N.Sub.only": 1}
        say("resolve: exact name", resolve("N.main", keys)[0] == "N.main")
        say("resolve: unique suffix", resolve("only", keys)[0] == "N.Sub.only")
        say("resolve: an ambiguous suffix resolves to nothing", resolve("aux", keys)[0] is None
            and "ambiguous" in resolve("aux", keys)[1])
        say("resolve: a private declaration by its plain name", resolve("N.aux", keys)[0] == "N.aux (private in N.A)")
        say("resolve: an undeclared name is reported", resolve("nope", keys) == (None, "not declared"))
        tbl = {"N.instDecidableEqSide": ("def", "1", []), "N.lost": ("def", "1", []),
               "N.fine": ("def", "1", []), "N.thm": ("theorem", "1", [])}
        src = {"N.fine": "def fine := 1"}
        h_, d_ = classify_sourceless(sorted(tbl), tbl, lambda n: src.get(n, ""))
        say("a derived instance without source is not a hole; a lost definition is",
            d_ == {"N.instDecidableEqSide"} and h_ == ["definition N.lost: source text not found in lean_files"])
        say("derived instances are recognised; ordinary names are not",
            is_derived_instance("N.instDecidableEqSide") and not is_derived_instance("N.Sparse")
            and not is_derived_instance("N.installed_x"[:0] + "N.thing"))
        # approval: tied to the sheet's snapshot, exclusions recorded
        setup(good_inf, good_so)
        fps = {"N.main": "a", "N.aux": "b", "N.thing": "c"}
        rws = [("Theorem 1.1", ["N.main"]), ("Lemma 1.2", ["N.aux"])]
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps), by="human")
        say("approve: an unchanged, complete sheet is approved", pr == [] and
            set(doc["fingerprints"]) == {"N.main", "N.aux"} and doc["by"] == "human")
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps))
        say("approve: an approval that does not say who decided is refused",
            any("approver must be" in p for p in pr))
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps), by="operator")
        say("approve: an approver outside {human, agent} is refused",
            any("approver must be" in p for p in pr))
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps), by="agent", note="Thm 1.1' approved by the user")
        say("approve: an agent approval is recorded as such, with its note",
            pr == [] and doc["by"] == "agent" and "approved by the user" in doc["note"])
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps, **{"N.main": "OLD"}))
        say("approve: a statement changed since the sheet was generated is refused",
            any("changed since the sheet" in p for p in pr))
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps, **{"N.thing": "OLD"}))
        say("approve: a DEFINITION changed since the sheet is refused", any("N.thing" in p for p in pr))
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps), excluded=["Lemma 1.2"], how="blanket", by="human")
        say("approve: an excluded result is recorded and not frozen",
            pr == [] and doc["rows"]["Lemma 1.2"]["status"] == "excluded"
            and "N.aux" not in doc["fingerprints"] and doc["how"] == "blanket")
        doc, pr = approve(cfg, d, rws, defs, fps, dict(fps), excluded=["Theorem 9.9"])
        say("approve: excluding a result not on the sheet is refused", any("9.9" in p for p in pr))
        json.dump({"date": "2026-01-01", "fingerprints": {"N.main": "a"}},
                  open(os.path.join(d, "APPROVED_FINGERPRINTS.json"), "w"))
        ch = changed_since_approval(d, rws, dict(fps, **{"N.main": "z"}))
        say("changed since approval: a changed statement and a never-approved one are marked",
            set(ch) == {"Theorem 1.1", "Lemma 1.2"})
        say("changed since approval: an unchanged approved one is not marked",
            "Theorem 1.1" not in changed_since_approval(d, rws, fps))
        os.remove(os.path.join(d, "APPROVED_FINGERPRINTS.json"))
        say("strip_comments removes docstrings and line comments",
            strip_comments("/-- doc -/\ntheorem t : True -- why\n  := trivial").split() ==
            ["theorem", "t", ":", "True", ":=", "trivial"])
        bd = os.path.join(d, "bundle-round"); os.makedirs(bd)
        say("a round without a stored bundle is a problem", bundle_problem(bd, "x") is not None)
        open(os.path.join(bd, "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write("old\n")
        say("a stale stored bundle is a problem", "stale" in (bundle_problem(bd, "new\n") or ""))
        say("a stored bundle equal to a fresh build is fine", bundle_problem(bd, "old\n") is None)
        say("check() reports a stale bundle",
            any("stale" in p for p in check({}, bd, [], [], "new\n")))
        ix = os.path.join(d, "Main.lean")
        open(ix, "w", encoding="utf-8").write(
            "/-!\n| Paper | Lean |\n|---|---|\n| Theorem 1.1 | `thm_1_1` |\n"
            "| Theorem 1.5 | not formalized: cited, unused |\n-/\n")
        nf = not_formalized({"index_file": ix, "lean_files": [ix]})
        say("results the index marks as not formalized are listed for the sheet",
            nf == [("Theorem 1.5", "not formalized: cited, unused")])
        cfg_nf = dict(cfg, index_file=ix, lean_files=[ix])
        rd3 = os.path.join(d, "rounds-nf", "R"); os.makedirs(rd3)
        json.dump(good_inf, open(os.path.join(rd3, "INFORMAL.json"), "w"))
        for note, want in (({"result": "Theorem 1.5", "note": "skip pending (QUESTION)"}, True),
                           ({"result": "Theorem 1.1", "note": "x"}, False),
                           ({"result": "Theorem 1.5", "note": ""}, False)):
            json.dump(dict(good_so, not_formalized=[note]), open(os.path.join(rd3, "SIGNOFF.json"), "w"))
            pr = [p for p in check(cfg_nf, rd3, rows, defs) if "not_formalized" in p]
            say(f"a not_formalized note for {note['result']!r} (note {note['note']!r}) is "
                f"{'accepted' if want else 'refused'}", (pr == []) == want)
        tx = os.path.join(d, "paper.tex")
        open(tx, "w", encoding="utf-8").write(
            "\\documentclass{article}\n\\newcommand{\\one}{1}\n"
            "\\newenvironment{bm}{% open\n  \\renewcommand{\\o}{\\bullet}% x\n"
            "  \\left(\\begin{smallmatrix}%\n}{%\n  \\end{smallmatrix}\\right)%\n}\n"
            "\\newcommand{\\at}{\\makeatletter@}\n\\newcommand{\\lb}{\\{}\n"
            "\\begin{document}\n\\newcommand{\\late}{x}\n\\end{document}\n")
        sm = source_macros({"source_pdf": tx})
        say("source_macros keeps one-line macros (as \\providecommand)", "\\providecommand{\\one}{1}" in sm)
        say("source_macros keeps a MULTI-LINE environment whole",
            "\\newenvironment{bm}" in sm and "\\end{smallmatrix}\\right)%\n}" in sm)
        say("source_macros skips @-definitions and escaped braces do not confuse it",
            "\\at" not in sm and "\\providecommand{\\lb}{\\{}" in sm)
        say("source_macros ignores definitions after \\begin{document}", "\\late" not in sm)
        L = {"p:a": ("lemma", "1.2"), "p:t": ("theorem", "3.1")}
        say("theorem wrappers, restatable, \\label and \\qed are stripped from the paper text",
            strip_theorem_envs("\\begin{restatable}{lemma}{rX}\\label{p:x} A $P$.\\qed\\end{restatable}", set()) == "A $P$."
            and strip_theorem_envs("\\begin{theorem}[FK21] T.\\end{theorem}", set()) == "T."
            and strip_theorem_envs("\\begin{myenv} M.\\end{myenv}", {"myenv"}) == "M.")
        say("\\cref resolves to kind + number from the .aux",
            resolve_refs("by \\cref{p:a}", L) == "by Lemma~1.2")
        say("\\ref resolves to the number; several keys; unknown label shown, not broken",
            resolve_refs("\\ref{p:t}; \\cref{p:a,p:t}; \\cref{zz}", L)
            == "3.1; Lemma~1.2, Theorem~3.1; [zz]")
        say("the stale message points at the first differing line",
            "line 1: stored 'old' vs now 'new'" in (bundle_problem(bd, "new\n") or ""))
        # the commands themselves (not only check()) refuse a stale bundle: drive main() with the
        # Lean-backed parts stubbed
        import io, contextlib
        g = globals()
        saved = (g["build_bundle"], project.select)
        rr = os.path.join(d, "rounds"); os.makedirs(os.path.join(rr, "R"))
        open(os.path.join(rr, "R", "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write("old\n")
        open(os.path.join(rr, "R", "FINGERPRINTS.json"), "w").write('{"fingerprints": {}}')
        def stub_bundle(cfg, table=None):
            build_bundle.missing = []
            return "new\n", [], []
        stub_bundle.missing = []
        g["build_bundle"] = stub_bundle
        project.select = lambda name=None: ({"rounds_dir": rr, "name": "t"}, "stub")
        try:
            for argv in (["check", "--round", "R"], ["render", "--round", "R"],
                         ["approve", "--round", "R", "--how", "blanket", "--by", "agent"]):
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc = main(argv)
                except Exception as e:   # got past the guard into the Lean-backed part
                    rc, _ = 0, buf.write(f"raised {e!r}")
                say(f"`signoff.py {argv[0]}` refuses a stale bundle", rc != 0 and "stale" in buf.getvalue())
            # ... and an approval that gets past every guard WRITES the approver it was given
            import fingerprint as _fp
            saved_fp, saved_check = (_fp.compute, _fp.head), g["check"]
            open(os.path.join(rr, "R", "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write("same\n")
            open(os.path.join(rr, "R", "FINGERPRINTS.json"), "w").write('{"fingerprints": {"N.main": "a"}}')
            def stub_same(cfg, table=None):
                build_bundle.missing = []
                return "same\n", [("Theorem 1.1", ["N.main"])], []
            g["build_bundle"] = stub_same
            g["check"] = lambda *a_, **k_: []
            _fp.compute, _fp.head = (lambda cfg: {"N.main": "a"}), (lambda repo: "c0ffee")
            try:
                for by in ("agent", "human"):
                    target = os.path.join(rr, "APPROVED_FINGERPRINTS.json")
                    if os.path.exists(target):
                        os.remove(target)
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc = main(["approve", "--round", "R", "--how", "blanket", "--by", by])
                    doc = json.load(open(target)) if os.path.exists(target) else {}
                    say(f"`signoff.py approve --by {by}` writes by={by} to the approval file",
                        rc == 0 and doc.get("by") == by)
                buf = io.StringIO()
                os.remove(os.path.join(rr, "APPROVED_FINGERPRINTS.json"))
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    rc = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent",
                               "--exclude", "Theorem 1.1"])
                say("`--by agent` with `--exclude` is refused (agent approval covers everything)",
                    rc != 0 and "approves EVERYTHING" in buf.getvalue())
            finally:
                (_fp.compute, _fp.head), g["check"] = saved_fp, saved_check
        finally:
            g["build_bundle"], project.select = saved
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

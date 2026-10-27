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
  5. `render`: SIGNOFF.md, one entry per result with a box to tick (its PDF is made from it by fresh agents:
     render_record.py; `approve --by human` refuses unless that PDF is the one recorded for this markdown).

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
    f = project.index_file(cfg)
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


STRUCTURE_HEAD = re.compile(r"^(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable)\s+)*(?:structure|class)\b")


def structure_of_field(d, table, source_of):
    """The structure whose source text declares `d` as a field (or, `toX`, as a parent it extends), else
    None. Lean generates a projection per field; its text is the structure's, which the bundle shows (the
    projection's type uses the structure, so the structure is in the closure). Live L-infinity run
    (2026-10-24): fields `f`, `π` of a Type-valued structure were reported as holes and the round set aside."""
    parent, _, field = plain(d).rpartition(".")
    for k in table:
        if plain(k) == parent and table[k][0] == "inductive":
            src = source_of(k)
            if not STRUCTURE_HEAD.match(src):
                continue
            word = lambda w: re.search(r"(?<![\w'.])" + re.escape(w) + r"(?![\w'])", src)
            if word(field) or (field.startswith("to") and re.search(r"\bextends\b", src) and word(field[2:])):
                return k
    return None


def classify_sourceless(names, table, source_of):
    """(holes, notes) among definitions with no source text: a derived instance (`deriving …`) or a
    structure's field is shown by signature with a note ({name: note}); any other missing source is a
    hole in the bundle."""
    holes, notes = [], {}
    for d in names:
        if table[d][0] in DEF_KINDS and not source_of(d):
            parent = structure_of_field(d, table, source_of)
            if is_derived_instance(d):
                notes[d] = "-- (derived instance, e.g. from `deriving DecidableEq`: no source text)"
            elif parent:
                notes[d] = (f"-- (a field of the structure {plain(parent)}: declared in that structure's "
                            f"definition, shown in this bundle)")
            else:
                holes.append(f"definition {d}: source text not found in lean_files")
    return holes, notes


def lean_table(cfg):
    """{name: (kind, own, deps)} from the fingerprint run (needs a built project)."""
    import fingerprint
    rc, out = project.run_lean(fingerprint.lean_source(cfg))
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
    rc, out = project.run_lean(src)
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


def statement_source(raw):
    """A theorem's statement as written: its source text up to the proof (the first `:=` outside
    brackets), comments removed. The elaborated signature alone drops type ascriptions: the
    test run's sheet printed `Q ⊤`, where the source says
    `(⊤ : Set (Fin (n + 1)))` -- the whole content of the statement.
    "" when unsure, and the bundle shows the elaborated signature only (review of fix-mini1, L1):
    a `let`/`have`/`haveI`/`letI` at depth 0 (its own `:=` is not the proof's), a line starting
    with `|` (match alternatives), or no `:=` at all."""
    t, depth = strip_comments(raw).strip(), 0
    for i, ch in enumerate(t):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif depth == 0 and t.startswith(":=", i):
            return t[:i].rstrip()
        elif depth == 0 and (re.match(r"(?:let|have|haveI|letI)\b", t[i:]) and not re.match(r"[\w'.]", t[i - 1:i])
                             or ch == "\n" and re.match(r"\n[ \t]*\|", t[i:])):
            return ""
    return ""


# the bundle's own label lines, kept on the sheet: without them a theorem's two forms ran together
# (trial #7 audit: the sheet once reached the approver without them)
NO_DEFS = "None beyond the definitions that are results of the paper themselves (above)."
APPROVING = ("Approving this sheet means: each Lean statement says what the paper says. It says nothing about the "
             "proofs.", "The plain-English reading of each Lean statement was written by a reviewer instructed not "
             "to read the paper; the comparison with the paper was written by a second reviewer. Tick a box only "
             "if you agree with the comparison; write on the page where you do not.")
BUNDLE_LABELS = ("-- signature (elaborated):", "-- statement (source):", "-- definition (source):")


def theorem_entry(sig, raw):
    """The bundle's lines for a theorem: its elaborated signature, then its statement as written."""
    src = statement_source(raw)
    return (["```lean", "-- signature (elaborated):", sig.strip(), "-- statement (source):", src, "```", ""]
            if src else ["```lean", sig.strip(), "```", ""])


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
          "included. A theorem's statement as written in the source follows its signature (type",
          "ascriptions such as `(⊤ : Set (Fin (n + 1)))` show only there; proof omitted).",
          "Definitions these statements use follow, each with its elaborated signature",
          "and its body as SOURCE TEXT (comments removed; not elaborated, so a cast or numeral",
          "there may leave its type implicit).", ""]
    holes, notes = classify_sourceless(sorted(stmt_names | set(defs)), table,
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
                md += theorem_entry(sigs[q], _raw_text(q, cfg))
    md.append("# Definitions these statements use")
    for d in defs:
        body = strip_comments(_raw_text(d, cfg)).strip()
        if d in notes:
            body = notes[d]
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
                        r"Definition|Conjecture|Remark)\s+([A-Z]?\d+(?:\.\d+)*)"
                        r"((?:\s*(?:,|and|or|&)?\s*(?:parts?\s+)?\(\s*(?:[a-z]|[ivx]+)\s*\))*)")
PART = re.compile(r"\(\s*([a-z]|[ivx]+)\s*\)")


def ref_labels(text):
    """Result labels in `text`, one per named part: "Lemma 7.4 (c)" stays "Lemma 7.4 (c)", and "Lemma
    7.4 part (a) and part (c)" or "Lemma 7.4 (a), (c)" gives "Lemma 7.4 (a)" and "Lemma 7.4 (c)" (a
    record about some parts must not flag the others, nor be read as the whole result; small-paper
    run stop S2 and the release-mode re-check r2)."""
    out = []
    for k, n, parts in RESULT_REF.findall(text):
        ps = PART.findall(parts)
        out += [f"{k} {n} ({p_})" for p_ in ps] if ps else [f"{k} {n}"]
    return out


def label_matches(label, res):
    """True if sheet row `res` is the result `label` names: a whole result matches all its parts;
    a part matches only that part (spacing before the parenthesis ignored)."""
    m = re.match(r"(.*?)\s*\(([a-z]|[ivx]+)\)$", label)
    if m:
        return re.sub(r"\s+", "", res).startswith(re.sub(r"\s+", "", m.group(1)) + f"({m.group(2)})")
    return re.match(re.escape(label) + r"\b(?![.\d])", res) is not None


def defect_results(rounds_dir):
    """Result labels ("Corollary 1.11") named in the "where" column of PAPER_DEFECTS.md rows."""
    p = os.path.join(rounds_dir, "PAPER_DEFECTS.md")
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8").read().splitlines():
        cells = project.split_row(line) if line.lstrip().startswith("|") else []
        if len(cells) > 1 and re.fullmatch(r"\d+", cells[0]):
            out += ref_labels(cells[1])
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
        cells = project.split_row(line)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if "statement" not in header or len(cells) <= header.index("statement") or project.superseded_row(cells):
            continue
        if "status" in header and len(cells) > header.index("status") and \
                re.match(r"repaired in [0-9a-f]{7,}", cells[header.index("status")].lower()):
            continue
        st = cells[header.index("statement")]
        out += ref_labels(st)
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
            if res and label_matches(label, res) and \
                    str(r.get("differences", "")).strip().startswith("None"):
                probs.append(f"{res}: PAPER_DEFECTS.md records a defect in this result, but the "
                             f"sheet says 'Differences: None'")
    # ...and must be CHECK, as must a result true only vacuously (AUDIT_PROTOCOL.md, "Documents a
    # human reads", rule 5): a GLOBAL or OK flag would let the reader skip it
    for src, labels, fname, why in (
            ("PAPER_DEFECTS.md records a defect in", defect_results(os.path.dirname(round_dir)), "PAPER_DEFECTS.md", "defect"),
            ("VACUOUS.md records as true only vacuously", vacuous_results(os.path.dirname(round_dir)), "VACUOUS.md", "vacu")):
        rp_ = os.path.join(os.path.dirname(round_dir), fname)
        raw = open(rp_, encoding="utf-8").read() if os.path.exists(rp_) else ""
        for label in labels:
            hit = [(res, r) for res, r in so_rows.items() if res and label_matches(label, res)]
            # release mode (project.RELEASE "label"): the record names ONE part in words the label
            # parser lost ("Lemma 7.4 part (c)" read as "Lemma 7.4"; small-paper run, stop S2), and
            # that part's row is CHECK for this very record: the other part rows are disclosed. A
            # record naming the whole result anywhere, or a CHECK given for another reason, blocks
            # (review M1).
            whole = re.search(re.escape(label) + r"(?![\w.])(?!\W{0,3}(?:part\s+)?\(([a-z]|[ivx]+)\))", raw) is not None
            some = (not whole and len(hit) > 1
                    and any(r.get("flag") == "CHECK" and why in str(r.get("check_reason", "")).lower() for _, r in hit))
            for res, r in hit:
                if r.get("flag") != "CHECK":
                    p_ = f"{res}: {src} this result, so its flag must be CHECK, not {r.get('flag')!r}"
                    probs.append(project.Finding(p_ + f" (the record names {label!r}; another row of it is "
                                                      f"CHECK)", "label") if some else p_)
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
        if "cited" in r and not isinstance(r.get("cited"), str):
            probs.append(f"{label}: `cited` must be a string (the source and what the run did with it) or \"\"")
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
    for aux in (os.path.join(d, stem + ".aux"), os.path.join(os.path.dirname(d), "build", stem + ".aux"),
                os.path.join(project.REPO, ".formalization-work", "source-build", stem + ".aux")):
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


def paper_lines(cfg):
    """{result label in lower case ("lemma 2.3"): line number in the .tex}, the line of the
    environment that holds the result's \\label, from the paper's own .aux. Empty without a .tex or
    its .aux (RUN.md Stage 1 compiles it). The sheet cites `tex l.N` so a reader finds the text."""
    src = cfg.get("source_pdf", "")
    path = src if os.path.isabs(src) else os.path.join(project.REPO, src)
    if not src.endswith(".tex") or not os.path.exists(path):
        return {}
    text = open(path, encoding="utf-8", errors="replace").read()
    # comments blanked, offsets kept: a commented-out \label or \begin is no label or environment
    code = re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), text)
    # without cleveref the .aux has no kind: take the printed name of the environment that holds
    # the \label (\newtheorem{lemma}[theorem]{Lemma}). The small-paper run's sheet had no tex line.
    printed = dict(re.findall(r"\\newtheorem\*?\s*\{([^}]+)\}\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}",
                              code.split("\\begin{document}")[0]))
    best = {}
    for lab, (kind, num) in paper_labels(dict(cfg, source_pdf=path)).items():
        at = code.find("\\label{" + lab + "}")
        if at < 0:
            continue
        # the environment the \label sits in: the innermost one still open at it (review of
        # fix-mini1, M3: the nearest \begin above ANY label -- a \section's, an equation's --
        # gave that label the lemma's kind and the sheet a wrong line)
        stack = []
        for m in re.finditer(r"\\(begin|end)\s*\{([^}]+)\}", code[:at]):
            if m.group(1) == "begin":
                stack.append((m.group(2), m.start()))
            elif stack and stack[-1][0] == m.group(2):
                stack.pop()
        if not stack:
            continue
        env, start = stack[-1]
        if kind:
            # cleveref's kind must be this environment's (its name or printed name), else no line
            if kind.lower() not in (env.lower(), printed.get(env, "").lower()):
                continue
        elif env in printed:
            kind = printed[env]
        else:
            continue          # not a \newtheorem environment: the number is not a result's
        line = code.count("\n", 0, start) + 1
        dist = code.count("\n", start, at)
        key = f"{kind.lower()} {num}"
        best.setdefault(key, []).append((dist, line))
    # two labels giving one result: the one next to its \begin; a tie between lines gives none
    out = {}
    for key, cands in best.items():
        d0 = min(d for d, _ in cands)
        ls = {l for d, l in cands if d == d0}
        if len(ls) == 1:
            out[key] = ls.pop()
    return out


def paper_line(plines, result):
    """The tex line of a sheet row's result; "Lemma 7.4 (a)" falls back to Lemma 7.4's line when its
    part has no label of its own."""
    return plines.get(result.lower()) or plines.get(re.sub(r"\s*\([^)]*\)\s*$", "", result).lower())


SHEET_LEGEND = ("**How to read a result.** Its label says how the Lean statement compares with the paper. "
                "OK: no difference was found. GLOBAL (G1, …): it differs only through the global difference(s) "
                "named, each stated once at the top of the sheet (approving the result takes those with it). "
                "CHECK: it differs in a way you should look at; the reason is given. **Junk values:** Lean gives "
                "every partial operation a default value (x/0 = 0, the integral of a non-integrable function is 0, "
                "√ of a negative number is 0, the infimum of an empty set of naturals is 0); this field says whether "
                "a statement could hold only because of such a value (None, Handled: how, or RISK: what).")


# the protocol's words the sheet uses (a fresh reader of the small-paper run's sheet found them undefined)
SHEET_TERMS = ("**Terms.** `sorry` is Lean's placeholder for a proof not yet written. *Phase 0* is the "
               "mechanical gate run before every audit round: the Lean builds, no `sorry` remains (except at "
               "this statement stage), only Lean's three standard axioms are used, and approved statements are "
               "unchanged. A *round* is one pass of independent AI reviewers over the Lean at one commit, named "
               "`YYYY-MM-DD-<commit>`; the *adjudicator* is the AI agent that decides each reviewer finding, in "
               "the round's `ADOPTED.md`. The *formalizing agent* is the AI that wrote the Lean.")


def sheet_background(cfg, so, kind="statements", approved=False):
    """The sheet's own background (a test run, KNOWN_FAULTS of the sheet): what the sheet is, who
    approves it under the run's involvement level (the intake answer quoted), what a tick and an
    empty box trigger, and what the code shown was checked with. Approval is stated as done only
    when the sheet is `approved` (mini5 audit: the pre-approval sheet said it was approved)."""
    lvl, ans = project.involvement(cfg), str(cfg.get("involvement_answer") or "").strip()
    who = {
        "hands-off": (f"At intake the person chose the hands-off involvement level (answer, verbatim: \"{ans}\"): "
                      + (APPROVAL_STAMPS[1][0] if approved else APPROVAL_STAMPS[1][1]) + ". The boxes are "
                      "for a reader who checks it later: a result or global difference you disagree with is "
                      "reversed through the decisions document (DECISIONS.md, delivered with this sheet at the end of "
                      "the run), which says what a reversal costs (a re-approval, new proofs)."),
        "statements-only": (f"At intake the person chose the statements-only involvement level (answer, verbatim: "
                            f"\"{ans}\"): the approver ticks each result and each global difference they agree "
                            "with, and the agent takes every decision after that."),
    }.get(lvl, "The approver ticks each result and each global difference they agree with; under the involved "
               "level they may instead let the agent approve everything (the report then says no person "
               "reviewed the statements).")
    return (f"**What this sheet is.** For each numbered result of {cfg.get('source_cite', 'the paper')}, the "
            f"paper's statement, the Lean statement, a plain-English reading of the Lean written by a reviewer "
            f"who did not see the paper, and a second reviewer's comparison. " + who + " A result left unticked "
            "is not approved: the report lists it as excluded, and its statement can be revised and put again. "
            f"The Lean shown is in the repository `{project.REPO}`, branch `{cfg.get('branch', '?')}`, at commit "
            f"`{so.get('commit', '?')}`, where it compiles (`{'; '.join(cfg.get('build_cmds') or ['?'])}` exits 0)"
            + (" and the proof of every result is `sorry` by design (a named witness or evidence lemma may "
               "already be proved; Phase 0, run with `--statements` by the round's adjudicator; its output is in "
               "that round's ADOPTED.md). **This is the statement-stage sheet:** it shows the Lean as it was at "
               "that commit, " + (APPROVAL_STAMPS[2][0] if approved else APPROVAL_STAMPS[2][1])
               + "; proofs written later, and the line numbers at the final "
               "commit, are in the report (REPORT.pdf). " if kind == "statements" else
               " (Phase 0, run by the round's adjudicator; its output is in that round's ADOPTED.md); this sheet is "
               "for a re-approval, so the proofs may be complete at that commit. ")
            + "`tex l.N` is line N of the paper's source; `File.lean:N` is line N of that Lean "
            "file at that commit.\n\n" + SHEET_TERMS + "\n\n" + SHEET_LEGEND + "\n")


# The first line of a sheet whose statements no person will review (RUN.md, intake question 5c,
# hands-off): the sheet is still delivered, and must not read as a human sign-off.
HANDS_OFF_LINE = ("Approved by the formalizing agent; no person reviewed these statements "
                  "(hands-off chosen at intake).")
# before the approval (mini5 audit: the sheet said "approved" before the approval existed)
HANDS_OFF_PENDING = ("To be approved by the formalizing agent; no person will review these statements "
                     "(hands-off chosen at intake).")
# the wording that changes at the approval, (after, before): the reader gate hashes the sheet with the
# "after" wording read as the "before" one (readers.content_hash), so a re-render after the approval
# keeps the fresh reader's pass
# B4 (U2 §3 M5): a hands-off re-approval's sheet (some result CHANGED since the previous approval) says so on its
# first line, after the approval and before it; never "unchanged since approval" while K results changed
REAPPROVED_LINE = "Statements unchanged since the latest approval; {k} re-approved by the agent, marked CHANGED."
REAPPROVED_PENDING = "Statements changed since the previous approval; {k} awaiting re-approval by the agent, marked CHANGED."


def hands_off_line(approved, k=0):
    """The first line of a hands-off sheet; `k` results marked CHANGED (a re-approval's sheet)."""
    line = HANDS_OFF_LINE if approved else HANDS_OFF_PENDING
    if k:
        line += " " + (REAPPROVED_LINE if approved else REAPPROVED_PENDING).format(k=k)
    return line


APPROVAL_STAMPS = [(HANDS_OFF_LINE, HANDS_OFF_PENDING),
                   ("the formalizing agent approved this sheet itself, and no person reviewed it",
                    "the formalizing agent will approve this sheet itself, and no person will review it"),
                   ("when it was approved", "the commit the approval is for"),
                   ("Statements unchanged since the latest approval; ", "Statements changed since the previous approval; "),
                   (" re-approved by the agent, marked CHANGED.", " awaiting re-approval by the agent, marked CHANGED.")]


def sheet_approved(round_dir):
    """Is this round's sheet the approved one (APPROVED_FINGERPRINTS.json in the rounds directory
    names it)?"""
    try:
        return json.load(open(os.path.join(os.path.dirname(os.path.abspath(round_dir)), "APPROVED_FINGERPRINTS.json"),
                              encoding="utf-8")).get("round") == os.path.basename(os.path.abspath(round_dir))
    except (OSError, ValueError, AttributeError):
        return False


def unstamp(text):
    """`text` with the after-approval wording read as the before-approval one (readers.content_hash)."""
    for after, before in APPROVAL_STAMPS:
        text = text.replace(after, before)
    return text


def render(cfg, round_dir, changed=None):
    """SIGNOFF.md (the paper's statements as their LaTeX source, which the PDF's renderer typesets: the sheet's PDF
    is made from this markdown by fresh agents, render_record.py; PDF-AGENTS). True when written."""
    render.fell_back = False
    return _render(cfg, round_dir, changed)


def _render(cfg, round_dir, changed=None):
    import make_report as mr
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
    approved = sheet_approved(round_dir)
    # under hands-off the sheet opens with the line
    changed = changed or {}
    head = ((f"**{hands_off_line(approved, len(changed))}**\n\n" if hands_off else "")
            + f"# Statement sign-off — {cfg['source_cite']}\n\n" +
            f"Commit `{so.get('commit', '?')}`. {len(rows)} results, {n_check} flagged CHECK, "
            f"{n_glob} differing only through the {len(glob)} global difference(s).\n")
    # what the sheet is comes before what approving it means (the reading order was inverted); with
    # global differences it follows them under "Results"
    intro = ("\n" + sheet_background(cfg, so, project.round_kind(round_dir) or "statements", approved) + "\n"
            f"**{APPROVING[0]}** {APPROVING[1]}\n")
    plines = paper_lines(cfg)
    try:
        # the lines of the sheet's own commit, which its background names (trial #7 audit)
        locs = mr.locate_names(dict(cfg, lean_files=cfg.get("lean_files") or []),
                               sorted({n for r in rows for x in _as_list(r.get("lean")) for n in lean_names(x)}),
                               at=so.get("commit") or None)
    except (OSError, KeyError):
        locs = {}
    pline = lambda res: paper_line(plines, res)
    ploc = lambda r: (f"(tex l.{pline(str(r.get('result', '')))}) " if pline(str(r.get("result", ""))) else "")
    one = lambda n: (f"`{n}` ({locs[n]})" if n in locs else f"`{n}`")
    # an entry the writer wrote with code spans ("`N.x`", "`N.d` (uses `N.y`)") keeps its words, each span located
    lloc = lambda x: (re.sub(r"`([^`\n]+)`", lambda m: one(m.group(1)), str(x)) if "`" in str(x) else one(x))
    # the Lean statements the blind reader read (the round's bundle): the sheet shows them (trial #7 audit; also
    # #4, #6: a sheet once reached the approver with no Lean statement at all)
    bundle = {}
    bp = os.path.join(round_dir, "STATEMENTS_BUNDLE.md")
    if os.path.exists(bp):
        for sec in re.split(r"^## ", open(bp, encoding="utf-8").read(), flags=re.M)[1:]:
            head_, _, body_ = sec.partition("\n")
            bundle[head_.strip()] = "\n".join(re.findall(r"```lean\n(.*?)```", body_, re.S)).strip()
    lean_lines = lambda res: [ln for ln in (bundle.get(res) or "").splitlines()
                              if ln.strip() and (not ln.startswith("--") or ln in BUNDLE_LABELS)]
    md = [head]
    if not glob:
        md.append(intro)
    if glob:
        md.append("\n## Global differences — approve each once; leaving one unticked excludes "
                  "every result that uses it\n")
        for g in glob:
            md += [f"\n### [ ] {g.get('id')}: {g.get('title')}", f"\n{g.get('text')}",
                   "\nUsed by: " + ", ".join(uses.get(g.get("id")) or ["(none)"])]
        md += ["\n## Results\n", intro]
    for r in rows:
        md += [f"\n## [ ] {r.get('result')}  —  {r.get('flag')}"
               + (f": {r.get('check_reason')}" if r.get("flag") == "CHECK" else "")
               + (f"  —  CHANGED since the approval of {changed[r.get('result')]}"
                  if r.get("result") in changed else ""),
               f"\n**Paper.** {ploc(r)}{r.get('paper')}",
               f"\n**Lean.** " + "; ".join(lloc(x) for x in _as_list(r.get("lean")))
               + "".join(f"  \n`{ln}`" for ln in lean_lines(r.get("result"))),
               f"\n**The Lean, in plain English (blind reading).** {r.get('plain_english')}",
               f"\n**Differences.** {r.get('differences')}",
               f"\n**Junk values.** {r.get('junk_values')}"]
        if str(r.get("cited", "") or "").strip():
            # a cited (literature) result's status, on its row whatever its flag (mini4/mini5 audits: a GLOBAL row's
            # differences can say nothing else)
            md.append(f"\n**Cited result.** {r.get('cited')}")
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
    if not inf.get("definitions"):
        md.append(NO_DEFS)          # trial #7 audit: an empty last heading
    md_text = "\n".join(md) + "\n"
    if mr.REFERENCE is not None:
        # make_report's in-memory mode (tests): what the generator writes now, nothing written
        mr.REFERENCE.append({"doc": "SIGNOFF", "md": md_text})
        return True
    open(os.path.join(round_dir, "SIGNOFF.md"), "w", encoding="utf-8").write(md_text)
    return True


def approvals(rounds_dir):
    """Earlier approval files, newest last: APPROVED_FINGERPRINTS.json and the dated copies
    re-approval moves aside."""
    # B4 (M5): in the order they were made -- the moved-aside copies by their names (`approve` names each
    # APPROVED_FINGERPRINTS.<date>[.<k>].json, k counting up within a date), the current file last; the old
    # sort by (date, commit) put two approvals of one day in the order of their commit hashes
    docs = []
    for f in sorted(glob.glob(os.path.join(rounds_dir, "APPROVED_FINGERPRINTS*.json")), key=project.approval_order):
        try:
            d = json.load(open(f))
        except ValueError:
            continue
        if isinstance(d, dict):
            docs.append(d)
    return docs


def lean_unchanged_since(cfg, round_name):
    """True when the project's Lean files on disk equal those of the commit round `round_name` was cut from (a
    stale bundle is then the printer's change, not the statements'); False when they differ or it cannot be told."""
    if not project.ROUND_RE.match(str(round_name)) or not cfg.get("lean_files"):
        return False
    r = subprocess.run(["git", "-C", project.REPO, "diff", "--quiet", project.round_commit(round_name), "--",
                        *cfg["lean_files"]], capture_output=True)
    return r.returncode == 0


def patched_since(cfg, round_name):
    """True when a tool patch was applied after round `round_name` was scoped (its "tool-patch TP<k> apply" commit is
    a descendant of the round's scope commit): a fingerprint that changed with the Lean unchanged is then the
    patched printer's (review M5(b))."""
    import tool_patch
    rdir = os.path.join(project.REPO, cfg["rounds_dir"])
    try:
        top = subprocess.run(["git", "-C", rdir, "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True).stdout.strip()
        sc = subprocess.run(["git", "-C", top, "log", "--reverse", "--diff-filter=A", "--format=%H", "--",
                             os.path.relpath(os.path.join(rdir, round_name, "TARGET.json"), top)],
                            capture_output=True, text=True).stdout.split()
        if not sc:
            return False
        for _p, _tp, _prev, _new, _e in tool_patch.links(top, rdir):
            if subprocess.run(["git", "-C", top, "merge-base", "--is-ancestor", sc[0], _p], capture_output=True).returncode == 0:
                return True
    except Exception:       # noqa: BLE001 -- not known: no grace (the refusal's own cure stands)
        return False
    return False


def cap_grace(cfg, round_name, reason, kind):
    """SWEEP-FIX D1 (G1, G2): the text appended to an approval refused for `reason`. At a reached statement-round
    cap whose last round is `round_name`, a MECHANICAL refusal -- a statement blocker (`kind` "blocker"), or a stale
    bundle while the Lean files are unchanged since the round's commit (the bundle printer changed) -- records one
    grace round (scope.grace_record), so the round it needs never counts against the cap. A stale bundle because
    the statements changed after the round is not mechanical: its cure is printed (restore the round's Lean, or
    approve a sheet whose bundle matches). "" when no cap is reached (another statement round is allowed anyway)."""
    import scope
    c = scope.statement_cap(cfg, project.REPO)
    if not c or c["rounds"][-1] != round_name:
        return ""
    if kind == "fingerprint" and not (lean_unchanged_since(cfg, round_name) and patched_since(cfg, round_name)):
        return ""       # a statement that really changed: its own refusal says to regenerate the sheet (a new round)
    if kind == "bundle" and not lean_unchanged_since(cfg, round_name):
        files = " ".join(cfg.get("lean_files") or ["<lean files>"])
        return (f"\nThe statement-round cap is reached on this round and the statements changed after it was scoped, "
                f"so no new statement round is allowed: either restore the round's Lean (git checkout "
                f"{project.round_commit(round_name)} -- {files}; commit) and approve this sheet, or -- a rejected change "
                f"of a re-approval -- restore the approved statements and approve the sheet of the round the replaced "
                f"approval approved (run/reapproval.md, \"rejected change at the cap\")")
    try:
        p = scope.grace_record(cfg, project.REPO, round_name, reason)
    except Exception as e:      # noqa: BLE001 -- said, never silent
        return f"\nThe grace round could not be recorded ({e}): run approve again"
    if p == scope.GRACE_SPENT:
        return (f"\nThe statement-round cap is reached on this round and its {scope.GRACE_CAP} grace rounds are spent: a "
                f"sheet that keeps changing while the Lean does not is a fault of the tools that print it -- open a stop "
                f"(python3 audits/stops.py open --note \"the statement sheet keeps changing with the Lean unchanged\" "
                f"--cause tool-bug --check \"python3 audits/signoff.py check --round {round_name}\") and take the "
                f"tool-patch route; never a human stop")
    return (f"\nThe statement-round cap is reached on this round, and this refusal is mechanical ({kind}): one grace "
            f"statement round is recorded ({os.path.relpath(p, project.REPO)}, committed \"round-cap {round_name} grace\"; "
            f"disclosed in RUN_RECORD.md). Cure the cause"
            + (" (the route the FAIL[index] line names)" if kind == "blocker" else " (a fresh sheet: a new statement round)")
            + ", then scope one more statement round (prompt.py 3 --statements): it does not count against the cap") if p else ""


def approve(cfg, round_dir, rows, defs, fps, snapshot, excluded=(), how="individual", by=None, note=""):
    """(document, problems). The approval freezes the fingerprints of the declarations on the
    sheet -- each approved result's statements, and through their closure every definition they
    use -- and only if those are unchanged since the sheet was generated: the approval covers what
    the sheet showed, not whatever HEAD has become. `by` records who decided (BY below)."""
    probs = project.split(cfg, check(cfg, round_dir, rows, defs))[0]   # disclosed ones do not refuse
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


def approval_binders(cfg, rdir):
    """(binders, None): the `binders` of <ROUNDS-DIR>/DEPENDENCIES.json (every Prop and structure binder of
    each result, the assumption walk's) when the file is the walk of the Lean files at HEAD -- recorded in
    the approval, so "hypotheses added since the approval" is computed later (DEPENDENCIES.json itself is
    not committed at approval; review fix 4) -- else (None, why not)."""
    import dependencies
    p = os.path.join(rdir, dependencies.OUT)
    try:
        d = json.load(open(p, encoding="utf-8"))
    except OSError:
        return None, f"no {dependencies.OUT} (Phase 0 writes it)"
    except ValueError:
        return None, f"{dependencies.OUT} is malformed"
    if not isinstance(d, dict) or not isinstance(d.get("binders"), dict):
        return None, f"{dependencies.OUT} has no assumption walk"
    if not d.get("lean_sha256") or d.get("lean_sha256") != dependencies.lean_hash(cfg, "HEAD"):
        return None, f"{dependencies.OUT} is not the walk of the Lean files at HEAD (Phase 0 rewrites it)"
    return d["binders"], None


# Who decided at Checkpoint B (RUN.md, Stage 2, step 8). The user is asked to choose:
#   human -- the user read the sheet (its PDF, made from SIGNOFF.md: render_record.py) and approved (all, or
#            excluding some results);
#   agent -- the user chose to let the agent decide; the agent approved everything on the sheet
#            WITHOUT a human reading it. The report must say so in those words.
BY = {"human", "agent"}


def changed_since_approval(rounds_dir, rows, fps, round_name=None):
    """{result label: date} for results whose statements changed since the last approval, or
    that the last approval did not cover. Shown on the sheet, so a re-approval reads as a diff.
    B4 (M5): the sheet of `round_name` that the latest approval approved (a re-approval's sheet, rendered
    again after its approval, e.g. at delivery) is compared with the approval BEFORE it, so its CHANGED
    marks survive the approval.
    B4 review fix 4: after several re-approvals, a re-approval's sheet (the one being approved, or the latest
    approval's, which ships) marks every result changed in ANY re-approval, each with the date of the approval
    it changed since (the latest change); a later sheet with nothing changed since the latest approval marks none."""
    apps = approvals(rounds_dir)
    if not apps:
        return {}
    own = bool(round_name) and apps[-1].get("round") == round_name
    states = [a.get("fingerprints") or {} for a in (apps[:-1] if own else apps)] + [fps]
    dates = [a.get("date", "?") for a in (apps[:-1] if own else apps)]
    if len(states) < 2:
        return {}

    def moved(a, b, ks, latest):
        return any((k not in a or a[k] != b.get(k)) and (latest or k in b) for k in ks)
    if not own and not any(moved(states[-2], fps, ks, True) for _, ks in rows):
        return {}
    out = {}
    for i in range(len(states) - 1, 0, -1):
        for label, ks in rows:
            if label not in out and moved(states[i - 1], states[i], ks, i == len(states) - 1):
                out[label] = dates[i - 1]
    return out


def _as_list(x):
    return x if isinstance(x, list) else [x] if x else []


def cited_name_problems(cfg, round_dir):
    """[problem] for each Lean name the writer's and informalizer's text (SIGNOFF.json, INFORMAL.json) cites that
    does not exist (make_report.cited_name_problems, resolved in Lean). Trial #10: a Mathlib
    name with the wrong namespace reached the approved sheet."""
    import make_report as mr

    def strings(x):
        if isinstance(x, dict):
            return [t for v in x.values() for t in strings(v)]
        if isinstance(x, list):
            return [t for v in x for t in strings(v)]
        return [x] if isinstance(x, str) else []
    docs = {}
    for f in ("SIGNOFF.json", "INFORMAL.json"):
        try:
            docs[f] = "\n".join(strings(json.load(open(os.path.join(round_dir, f), encoding="utf-8"))))
        except (OSError, ValueError):
            pass
    return mr.cited_name_problems(cfg, docs)


def lean_names(x):
    """The Lean names of one `lean` entry of a sheet row: its code spans when it has any (trial #10: the writer
    wrote "`N.x`" and "`N.d` (uses `N.y`)"; the sheet showed doubled backticks and no File.lean:N at all),
    else the entry itself."""
    return re.findall(r"`([^`\n]+)`", str(x)) or [str(x).strip()]


APPROVE_WRITES = ("APPROVED_FINGERPRINTS.json", "REAPPROVAL.json")      # + an aside APPROVED_FINGERPRINTS.<date>[.k].json


def interrupted_approval_restore(rdir):
    """B13 (U2 §8): if `approve`'s own files in the rounds dir `rdir` differ from what is committed (an approve
    killed between its writes and its commit), restore the committed state -- tracked files checked out,
    untracked ones (a first approval, an aside copy) removed -- and return {"paths": [rel], "doc": the
    interrupted APPROVED_FINGERPRINTS.json or None}; None when nothing is uncommitted. Raises ValueError
    when git cannot tell or restore."""
    import subprocess
    if not os.path.isdir(rdir):
        return None
    pats = list(APPROVE_WRITES) + ["APPROVED_FINGERPRINTS.*.json"]
    r = subprocess.run(["git", "-C", rdir, "status", "--porcelain", "--untracked-files=all", "--", *pats],
                       capture_output=True, text=True)
    if r.returncode:
        raise ValueError(f"git status failed: {r.stderr.strip()[:200]}")
    rows = [(ln[:2], ln[3:].strip().strip('"')) for ln in r.stdout.splitlines() if ln.strip()]
    # only what approve writes: a file written (new or changed); a deletion only as the move of the old approval
    # aside (the aside copy is there, uncommitted) -- a file merely deleted is not approve's and is left alone
    aside = any(st == "??" and os.path.basename(rel) not in APPROVE_WRITES for st, rel in rows)
    rows = [(st, rel) for st, rel in rows if "D" not in st or aside]
    if not rows:
        return None
    top = subprocess.run(["git", "-C", rdir, "rev-parse", "--show-toplevel"], capture_output=True,
                         text=True).stdout.strip()
    doc = None
    try:
        doc = json.load(open(os.path.join(rdir, APPROVE_WRITES[0]), encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    for st, rel in rows:
        p = os.path.join(top, rel)
        if st == "??":
            os.remove(p)
        else:
            rc = subprocess.run(["git", "-C", top, "checkout", "HEAD", "--", rel], capture_output=True, text=True)
            if rc.returncode:
                raise ValueError(f"git checkout of {rel} failed: {rc.stderr.strip()[:200]}")
    return {"paths": [rel for _, rel in rows], "doc": doc if isinstance(doc, dict) else None}


def same_approval(old, new):
    """Is the interrupted approval `old` the one `new` records now? Every field but the date (any day up to
    today) and the Lean commit (the HEAD it was made at: a later HEAD whose fingerprints still equal the
    sheet's gives the same approval)."""
    import datetime
    if not isinstance(old, dict):
        return False
    d = str(old.get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d > datetime.date.today().isoformat():
        return False
    strip = lambda x: {k: v for k, v in x.items() if k not in ("date", "commit")}
    return strip(old) == strip(new)


def save_record(round_dir, name, reason=""):
    """Commit the blind informalizer's INFORMAL.json or the sign-off writer's SIGNOFF.json, by name,
    as "signoff <R>" (each is that agent's record; nobody else commits it, and the adjudication no
    longer sweeps it in). A sheet saved again after a writer rerun needs --reason; INFORMAL.json is
    saved once."""
    p = os.path.join(round_dir, name)
    r_ = os.path.basename(round_dir)
    if not os.path.exists(p):
        print(f"FAIL: no {name} in {r_}: the agent has not written it", file=sys.stderr); return 1
    try:
        json.load(open(p, encoding="utf-8"))
    except ValueError as e:
        print(f"FAIL: {name} is not valid JSON ({e}): a mechanical failure of the agent", file=sys.stderr); return 1
    st = subprocess.run(["git", "-C", os.path.dirname(p), "log", "--format=%h", "--", name],
                        capture_output=True, text=True).stdout.split()
    if st and name == "INFORMAL.json":
        print(f"FAIL: {name} is already saved; the blind reading is written once", file=sys.stderr); return 1
    why = " ".join(str(reason or "").split())
    if st and not why:
        print(f"FAIL: {name} is already saved; a writer rerun saves it again with --reason \"<why>\"",
              file=sys.stderr)
        return 1
    try:
        h = project.commit_only([p], f"signoff {r_}" + (f" (sheet re-written: {why[:120]})" if st else ""))
    except ValueError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 1
    print(f"committed {name} as \"signoff {r_}\" in {h[:11]}")
    return 0


# B4 (U2 §3, F11; ADDENDUM U2.1 N3): a re-approval that repairs a REFUTED statement names the refutation,
# `reapprove --begin --refuted-by <ns>.not_<X>_as_printed`. The refutation is `def <ns>.<X>_as_printed : Prop`
# (the statement as printed) with a proved `theorem <ns>.not_<X>_as_printed : ¬ <ns>.<X>_as_printed` whose axioms
# are standard (no sorryAx; the refuted <ns>.<X>'s own `sorry` may remain, it is false). `<X>_as_printed` must be
# the statement approved at B: defeq in Lean to <X>'s type while <X> still has its first approved fingerprint, or,
# once a correction of it was re-approved (a failed correction), the same `_as_printed` (fingerprint) the first
# repair checked -- never a refutation of a later re-approved encoding (no second weakening).
STANDARD_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
def refutation_names(thm):
    """(decl, as_printed) named by the refutation theorem `thm`; ValueError if it is not `<ns>.not_<X>_as_printed`
    (make_report.AS_PRINTED on its last component: the one refutation name every check reads, trial #10)."""
    import make_report as mr
    ns, _, short = str(thm or "").strip().rpartition(".")
    m = mr.AS_PRINTED.fullmatch(short) if re.fullmatch(r"(?:[\w']+\.)*[\w']+", str(thm or "").strip()) else None
    if not m:
        raise ValueError(f"--refuted-by {thm!r}: the refutation is a theorem `<namespace>.not_<decl>_as_printed` "
                         f"(its full Lean name), proving `¬ <namespace>.<decl>_as_printed`"
                         + (f"; rename it `{(ns + '.' if ns else '') + mr.refutation_rename(short)}`"
                            if short and re.fullmatch(r"[\w']+", short) else ""))
    d = (ns + "." if ns else "") + m.group(1)
    return d, d + "_as_printed"


def refutation_lean(thm, asp, decl):
    """The Lean command (appended to the project) printing what --refuted-by checks: REF lines, then REFDONE."""
    q = lambda s: json.dumps(s)
    return ("\nopen Lean Meta Elab Command in\nrun_cmd liftTermElabM do\n"
            "  let env ← getEnv\n"
            f"  let thm := ({q(thm)} : String).toName\n  let asp := ({q(asp)} : String).toName\n"
            f"  let decl := ({q(decl)} : String).toName\n"
            '  let say (k v : String) : MetaM Unit := IO.println s!"REF\\t{k}\\t{v}"\n'
            "  match env.find? thm with\n"
            "  | some (.thmInfo v) =>\n"
            '      say "thm" "theorem"\n'
            "      match env.find? asp with\n"
            "      | some (.defnInfo a) =>\n"
            '          say "asp" (if a.levelParams.isEmpty && a.type == .sort .zero then "def" else "notprop")\n'
            "          let ok ← try (isDefEq v.type (mkNot (mkConst asp))) catch _ => pure false\n"
            '          say "type" (if ok then "ok" else "bad")\n'
            "          match env.find? decl with\n"
            "          | some d =>\n"
            "              let ok2 ← try (isDefEq a.value d.type) catch _ => pure false\n"
            '              say "defeq" (if ok2 then "ok" else "bad")\n'
            '          | none => say "decl" "missing"\n'
            '      | some _ => say "asp" "notdef"\n'
            '      | none => say "asp" "missing"\n'
            "      let ax ← collectAxioms thm\n"
            '      say "axioms" (",".intercalate (ax.toList.map toString))\n'
            '  | some _ => say "thm" "notheorem"\n'
            '  | none => say "thm" "missing"\n'
            '  IO.println "REFDONE"\n')


def refutation_facts(cfg, thm, asp, decl):
    """{key: value} of the REF lines (thm, asp, type, defeq, decl, axioms) from a Lean run on the project;
    RuntimeError when the run did not complete (no REFDONE)."""
    rc, out = project.run_lean(project.lean_body(cfg) + "\n" + refutation_lean(thm, asp, decl))
    facts, done = {}, False
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == "REF" and len(parts) == 3:
            facts[parts[1]] = parts[2]
        done |= line.strip() == "REFDONE"
    if not done:
        raise RuntimeError(f"the refutation check did not run (lake env lean exit {rc}):\n" + out[-2000:])
    return facts


REFUTATION_FACTS = refutation_facts          # the selftest's stand-in


def refutation_problems(facts, thm, asp, decl, b_same):
    """[why --refuted-by refuses] from the Lean facts. `b_same`: <decl> still has the fingerprint it was first
    approved with (at B), so its current type is the approved one and the defeq check decides."""
    out = []
    if facts.get("thm") != "theorem":
        out.append(f"`{thm}` is " + ("not in the project (build it, commit it)" if facts.get("thm") == "missing"
                                     else "not a theorem"))
        return out
    if facts.get("asp") != "def":
        out.append(f"`{asp}` " + {"missing": "does not exist", "notdef": "is not a definition",
                                  "notprop": "is not a `def ... : Prop` without universe parameters"}
                   .get(facts.get("asp"), "could not be read") + ": the statement as printed is `def "
                   f"{asp} : Prop := <the approved statement>`")
    elif facts.get("type") != "ok":
        out.append(f"the type of `{thm}` is not `¬ {asp}`")
    ax = [a for a in (facts.get("axioms") or "").split(",") if a]
    bad = sorted(set(ax) - STANDARD_AXIOMS)
    if bad or "axioms" not in facts:
        out.append(f"`{thm}` is not proved with the standard axioms only (collectAxioms: "
                   f"{', '.join(bad) or 'not read'}): "
                   + ("it uses `sorry` (sorryAx), so nothing is refuted" if "sorryAx" in bad else "an extra axiom")
                   + " (N3: the refuted declaration's own `sorry` may remain, the refutation's may not)")
    if b_same and facts.get("asp") == "def" and facts.get("defeq") != "ok":
        out.append(f"`{asp}` is not definitionally equal to the type of `{decl}` as approved at B: the refutation "
                   f"must refute the approved statement itself (F11)")
    return out


def first_approved_fp(rdir, cfg, decl):
    """<decl>'s fingerprint in the FIRST genuine approval that froze it (Checkpoint B for it), or None."""
    import fingerprint
    for _, a in fingerprint.genuine_approvals(rdir, cfg):
        f = (a.get("fingerprints") or {}).get(decl)
        if f:
            return f
    return None


def earlier_refutations(rdir, cfg, decl):
    """[{by, as_printed, as_printed_fp, ...}] recorded for <decl> by earlier re-approvals of the run (oldest
    first; REAPPROVAL.json's `refuted` entries, every cycle)."""
    import fingerprint
    out = []
    for c in fingerprint.reapprovals(rdir, cfg):
        r = (c.get("refuted") or {}).get(decl) if isinstance(c.get("refuted"), dict) else None
        if isinstance(r, dict):
            out.append(r)
    return out


def refuted_check(cfg, rdir, thm, decls, approved, fps, goals=None):
    """({decl: record}, decls) for `--refuted-by thm`, or ValueError: the checks of U2 §3 (F11, N3). `decls`
    may be empty (then the refuted declaration); otherwise it must include it."""
    decl, asp = refutation_names(thm)
    if decls and decl not in decls:
        raise ValueError(f"--refuted-by {thm} refutes `{decl}`, which --decls does not list")
    decls = decls or [decl]
    if decl not in (approved.get("fingerprints") or {}):
        raise ValueError(f"`{decl}` is not approved: a refutation before approval changes the statement at "
                         f"Checkpoint B (a new statements round), not by re-approval")
    if goals is None:
        import decisions
        try:
            goals = decisions.goal_decls(cfg)
        except Exception as e:   # noqa: BLE001 -- fail closed: the goal list could not be read
            raise ValueError(f"could not read the goal results ({e}): a goal result found false is stop 1, so "
                             f"--refuted-by needs the goal list")
    ns = cfg.get("namespace", "")
    if {decl, f"{ns}.{decl}"} & set(goals):
        raise ValueError(f"`{decl}` is a goal result: a goal found false is stop 1, never a repair (`stops.py open "
                         f"--note \"<the refutation>\" --cause unproved-goal`)")
    b_fp = first_approved_fp(rdir, cfg, decl)
    b_same = b_fp is not None and approved["fingerprints"][decl] == b_fp
    facts = REFUTATION_FACTS(cfg, thm, asp, decl)
    probs = refutation_problems(facts, thm, asp, decl, b_same)
    asp_fp = fps.get(asp)
    if not b_same and not probs:
        prev = [r for r in earlier_refutations(rdir, cfg, decl) if r.get("as_printed") == asp]
        if not prev or not asp_fp or any(r.get("as_printed_fp") != asp_fp for r in prev):
            probs.append(f"`{decl}` was re-approved since its first approval (at B), so `{asp}` must be the statement "
                         f"as printed that its first repair refuted, unchanged (fingerprint "
                         + (f"{asp_fp}, recorded {prev[0].get('as_printed_fp')}" if prev else
                            "recorded by no earlier --refuted-by of it") + "): a refutation of a later encoding is no "
                         "refutation of the approved statement (F11)")
    if probs:
        raise ValueError("--refuted-by refused: " + "; ".join(probs))
    return ({decl: {"by": thm, "as_printed": asp, "as_printed_fp": asp_fp, "b_fingerprint": b_fp,
                    "axioms": sorted(a for a in (facts.get("axioms") or "").split(",") if a),
                    "check": "defeq at B" if b_same else "same as_printed as the first repair"}}, decls)


def reapprove_begin(cfg, decls, reason, fps=None, lean_repo=None, refuted_by=None, goals=None):
    """Open (or extend) a re-approval BEFORE the Lean edit (RULINGS A11): record the Lean HEAD and
    each listed declaration's approved fingerprint in <rounds>/REAPPROVAL.json, committed as
    "approve (reapproval begin: <reason>)". Refused unless every listed declaration is approved and
    its current fingerprint is still the approved one (so the begin provably precedes the edit),
    and while a .lean file has uncommitted changes. The freeze check then reports a change to a
    listed declaration as NOTE[reapproval]; `signoff.py approve` closes the record. Returns a
    message; raises ValueError on a refusal."""
    import fingerprint, datetime
    lean_repo = lean_repo or project.REPO
    rdir = os.path.join(project.REPO, cfg["rounds_dir"])
    why = " ".join(str(reason or "").split())
    decls = sorted({x.strip() for x in decls if x.strip()})
    if not why:
        raise ValueError("say why the statements change (--reason)")
    if not decls and not refuted_by:
        raise ValueError("list the approved declarations that will change (--decls a,b), including every "
                         "approved result stated in terms of a definition that will change")
    ap_ = os.path.join(rdir, fingerprint.APPROVED)
    if not os.path.exists(ap_):
        raise ValueError(f"no {fingerprint.APPROVED}: nothing is approved, so there is nothing to re-approve")
    top_, rel_ = project.rounds_rel(rdir, fingerprint.APPROVED)
    if top_ is None or project.committed_blob(top_, "HEAD", rel_) is None \
            or fingerprint._git(top_, "status", "--porcelain", "--", rel_)[1]:
        raise ValueError(f"{fingerprint.APPROVED} is not committed as it is (a regular file written by "
                         f"`signoff.py approve`): the re-approval replaces the committed approval")
    # B2 re-check (amend): the approval replaced is the one `signoff.py approve` last wrote (a genuine approve
    # commit, its gate holding), never a later hand edit committed over it
    gh_, approved = fingerprint.last_genuine_approval(rdir, cfg)
    if not gh_:
        raise ValueError(f"no {fingerprint.APPROVED} written by `signoff.py approve` (a genuine \"approve <R>\" "
                         f"commit) in the history: nothing is approved, so there is nothing to re-approve")
    try:
        head_doc = json.loads(project.committed_blob(top_, "HEAD", rel_))
    except ValueError:
        head_doc = None
    if head_doc != approved:
        raise ValueError(f"{fingerprint.APPROVED} differs from the approval `signoff.py approve` wrote in "
                         f"{gh_[:11]} (edited by hand since): restore it (`git checkout {gh_[:11]} -- "
                         f"{rel_}`) and commit, then begin")
    cur, prob = fingerprint.open_reapproval(rdir, lean_repo, cfg)
    if prob:
        raise ValueError(f"the existing re-approval record cannot be trusted: {prob}")
    refuted = {}
    if refuted_by:
        fps = fingerprint.compute(cfg) if fps is None else fps
        refuted, decls = refuted_check(cfg, rdir, refuted_by, decls, approved, fps, goals)
    missing = [n for n in decls if n not in approved.get("fingerprints", {})]
    if missing:
        raise ValueError(f"not approved, so not frozen: {', '.join(missing)}")
    dirty = fingerprint._git(lean_repo, "status", "--porcelain", "--untracked-files=no", "--", "*.lean")[1]
    if dirty:
        raise ValueError("a .lean file has uncommitted changes: the begin comes before the edit "
                         "(commit or revert them, rebuild, then begin)")
    fps = fingerprint.compute(cfg) if fps is None else fps
    gone = [n for n in decls if fps.get(n) != approved["fingerprints"][n]]
    if gone:
        raise ValueError(f"already changed since the approval: {', '.join(gone)}. The begin must come "
                         "before the edit; this change is a DRIFT (a freeze stop), not a re-approval")
    doc = cur or {"decls": [], "begin_fingerprints": {}, "begins": []}
    doc["decls"] = sorted(set(doc["decls"]) | set(decls))
    doc["begin_fingerprints"].update({n: approved["fingerprints"][n] for n in decls})
    head_ = fingerprint.head(lean_repo)
    doc["lean_head"] = doc.get("lean_head") or head_   # the first begin's; every later one extends it
    doc["begins"].append({"date": datetime.date.today().isoformat(), "lean_head": head_, "decls": decls,
                          "reason": why, "involvement": project.involvement(cfg)}
                         | ({"refuted_by": refuted_by} if refuted else {}))
    if refuted:
        doc["refuted"] = dict(doc.get("refuted") or {}, **refuted)
    doc["approved_commit"] = approved.get("commit")
    doc["closed"] = False
    rp = os.path.join(rdir, fingerprint.REAPPROVAL)
    json.dump(doc, open(rp, "w"), indent=1, ensure_ascii=False)
    h = project.commit_only([rp], f"{fingerprint.REAPPROVAL_BEGIN}: {why[:100]})")
    line = (f"change {', '.join(decls)} — {why} (re-approval begun at Lean {head_}, record {h[:11]}"
            + (f"; refuted by `{refuted_by}`: a repair, disclosed with its PAPER_DEFECTS.md row" if refuted else "")
            + ")")
    if project.involvement(cfg) == "hands-off":
        import stops
        line = f"{stops.tag(cfg, 're-approve')} {line}"
    project.log_append(cfg, "Re-approvals", f"- {line}")
    import decisions
    q = decisions.reapproval_question(cfg)
    if q:
        # B2 review: the question is visible in the documents -- an "## Open questions" entry, which the
        # DECISIONS.md skeleton lists (decisions.py --write) until it is marked "(answered <date>: ...)"
        project.log_append(cfg, "Open questions",
                           f"- re-approval QUESTION: the change to {', '.join(q['decls'])} ({why}) awaits the "
                           f"human's approval ({q['why']}); ask with `signoff.py reapprove --question --round <R>`, "
                           f"log their words under ## Re-approvals, then `signoff.py approve --by human` (a "
                           f"rejected change: restore the approved statement first, run/reapproval.md)")
    return (f"committed {fingerprint.REAPPROVAL} as \"{fingerprint.REAPPROVAL_BEGIN}: ...)\" in {h[:11]}; "
            f"now edit the Lean. The freeze check reports a change to {', '.join(decls)} as NOTE[reapproval] "
            f"until `signoff.py approve` closes it")


def reapproval_reader_gate(cfg, round_name):
    """[problem] of the fresh-reader gate on the re-approval sheet of `round_name` (readers.check), [] when it
    passes (B4, M5)."""
    import readers
    return readers.check(cfg, "signoff", round_name)


REAPPROVAL_READER_GATE = reapproval_reader_gate     # the selftest's stand-in


def render_guard(cfg, round_name):
    """[problem] of the sheet's PDF: render_record.check (the PDF the human reads is the one recorded, made from the
    sheet's markdown as it is now; `no-pdf` passes)."""
    import render_record
    return render_record.check(cfg, "SIGNOFF", round_name)


def render_shown(cfg, round_name):
    """({pdf_sha256, outcome, render_version, md_sha256, date} the human was shown, [problem]) (review LOW): the
    sheet's PDF recorded when the Checkpoint B question was asked (render_record.py shown), which must be the PDF
    the record ships now; the approval records it."""
    import render_record
    return render_record.shown_problem(cfg, "SIGNOFF", round_name)


RENDER_GUARD = render_guard      # the selftest's stand-ins
RENDER_SHOWN = render_shown


def human_answer_line(round_name, decls):
    return f'- human answer (round {round_name}; {", ".join(decls)}): "<their words, verbatim>"'


def human_answer_problem(rounds_dir, round_name, decls):
    """None when the COMMITTED RUN_LOG.md (HEAD, literal path, a regular file) has, under "## Re-approvals" or
    "## Answered", a line `- human answer (round <R>; <decls>): "<verbatim>"` naming this round and every
    declaration of the re-approval by its FULL name, that the begin commit's RUN_LOG.md did not have (B2
    re-check (c): answered after the question); else why not. Still trust-based -- no script sees who typed
    the words -- but the approval is evidenced by the human's recorded answer (fingerprint.answer_lines)."""
    import fingerprint
    top, rel = project.rounds_rel(rounds_dir, "RUN_LOG.md")
    want = human_answer_line(round_name, decls)
    if top is None or project.committed_blob(top, "HEAD", rel) is None:
        return f"no committed RUN_LOG.md to hold the human's answer; log `{want}` and commit it"
    begin_h = fingerprint._git(top, "log", "-1", "--format=%H", "--",
                               project.rounds_rel(rounds_dir, fingerprint.REAPPROVAL)[1])[1]
    if fingerprint.answered_after(top, "HEAD", begin_h, rel, round_name, decls):
        return None
    return (f"the human's answer is not recorded: under RUN_LOG.md's \"## Re-approvals\" log their words "
            f"verbatim as `{want}` (every declaration by its full name) and commit it AFTER the re-approval "
            f"began and BEFORE this approve (an answer you give for them is no human approval)")


def reapproval_ask(cfg, round_name):
    """The Checkpoint B question for the open re-approval (run/reapproval.md step 4): options (a) and (b)
    always; (c), "let the agent approve", only when project.agent_may_reapprove allows it (B2 review, compat
    MED-1: offering (c) where the agent may not re-approve invited an answer `approve --by agent` refuses).
    ValueError when no trusted re-approval is open."""
    import fingerprint
    rdir = os.path.join(project.REPO, cfg["rounds_dir"])
    reap, prob = fingerprint.open_reapproval(rdir, project.REPO, cfg)
    if prob or not reap:
        raise ValueError(prob or "no re-approval is open (`signoff.py reapprove --begin` first)")
    ok_, why_ = project.agent_may_reapprove(cfg, fingerprint.replaced_approval(rdir, cfg))
    decls = ", ".join(reap.get("decls") or [])
    reason = (reap.get("begins") or [{}])[-1].get("reason", "?")
    q = (f"> The statements of {decls} changed since your approval ({reason}). The new sheet is "
         f"`<rounds dir>/{round_name}/SIGNOFF.pdf` (its markdown `SIGNOFF.md` beside it; how its PDF was checked, and "
         f"any objection left, is quoted above); the changed results are marked CHANGED. Does the change "
         f"strengthen or weaken them? How do you want to approve?\n"
         f"> **(a)** I will read the sheet and approve all of it.\n"
         f"> **(b)** I will read the sheet and list the results I reject.")
    if ok_:
        q += ("\n> **(c)** Let the agent approve everything on the sheet without my reading it. The report "
              "will then say that no human reviewed the changed statements.")
    else:
        q += f"\n(no option (c): {why_})"
    return q


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["bundle", "check", "render", "approve", "save-informal",
                                               "save-signoff", "reapprove"])
    ap.add_argument("--exclude", default="", help="approve: comma-separated results NOT approved")
    ap.add_argument("--how", choices=["individual", "blanket"],
                    help="approve: did the human answer per result, or say 'all OK'?")
    ap.add_argument("--by", choices=sorted(BY),
                    help="approve: who decided -- 'human' (the user read the sheet) or 'agent' "
                         "(the user chose to let the agent approve without reading)")
    ap.add_argument("--note", default="",
                    help="approve: one sentence for the record, e.g. statements the human approved "
                         "individually inside an agent approval")
    ap.add_argument("--begin", action="store_true",
                    help="reapprove: open a re-approval, BEFORE the Lean edit")
    ap.add_argument("--question", action="store_true",
                    help="reapprove: print the question to ask about the open re-approval (option (c) only "
                         "when the agent may re-approve)")
    ap.add_argument("--refuted-by", default="",
                    help="reapprove --begin: the refutation of an approved statement, `<ns>.not_<decl>_as_printed` "
                         "(U2 §3): checked in Lean against the statement approved at B")
    ap.add_argument("--decls", default="",
                    help="reapprove: comma-separated approved declarations that will change")
    ap.add_argument("--project")
    ap.add_argument("--round")
    ap.add_argument("--reason", default="",
                    help="save-signoff: why a sheet already saved is written again (a writer rerun); "
                         "reapprove: why the statements change")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--lean", action="store_true",
                    help="selftest: also run the Lean-backed checks (needs a built project)")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest() or (selftest_lean() if a.lean else 0)
    if a.cmd == "reapprove":
        if a.question:
            try:
                cfg = project.select(a.project)[0]
                print(reapproval_ask(cfg, a.round or "<R>"))
                return 0
            except (project.SelectionError, ValueError) as e:
                print(f"FAIL: {e}", file=sys.stderr); return 1
        if not a.begin:
            ap.error("reapprove takes --begin or --question (`signoff.py approve` closes a re-approval)")
        try:
            cfg = project.select(a.project)[0]
            print(reapprove_begin(cfg, a.decls.split(","), a.reason, refuted_by=a.refuted_by or None))
            return 0
        except (project.SelectionError, ValueError) as e:
            print(f"FAIL: {e}", file=sys.stderr); return 1
        except RuntimeError as e:
            print(f"FAIL: could not read the compiled project (build it first):\n{e}", file=sys.stderr); return 2
    if not a.cmd or not a.round:
        ap.error("give a command and --round")
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    rd = os.path.join(project.REPO, cfg["rounds_dir"], a.round)
    if not os.path.isdir(rd):
        print(f"FAIL: no round directory {rd}", file=sys.stderr); return 2
    if a.cmd in ("save-informal", "save-signoff"):
        return save_record(rd, "INFORMAL.json" if a.cmd == "save-informal" else "SIGNOFF.json", a.reason)
    try:
        md, rows, defs = build_bundle(cfg)
    except RuntimeError as e:
        print(f"FAIL: could not read the compiled project (build it first):\n{e}", file=sys.stderr)
        return 2
    if a.cmd == "bundle":
        p = os.path.join(rd, "STATEMENTS_BUNDLE.md")
        # An incomplete bundle produces a sheet with holes a signer cannot see. Fix the index or
        # lean_files and rebuild. It is never written: an uncommitted bundle left here was swept into the
        # round's set-aside commit, which integrity.py refuses (only "scope" owns it; live L-infinity run S1)
        if build_bundle.missing:
            for m in build_bundle.missing:
                print(project.problem_line(m, "signoff-check"))
            print(f"not written: {os.path.relpath(p, project.REPO)} ({len(build_bundle.missing)} problem(s))")
            return 1
        before = open(p, "rb").read() if os.path.exists(p) else None
        open(p, "w", encoding="utf-8").write(md)
        print(f"wrote {os.path.relpath(p, project.REPO)}: {len(rows)} results, {len(defs)} definitions")
        try:
            h = project.commit_only([p], f"scope {a.round} (statements bundle)")
        except ValueError as e:
            if before is None:
                os.remove(p)
            else:
                open(p, "wb").write(before)
            print(f"FAIL: the bundle was not committed ({e}); the file is as it was before", file=sys.stderr); return 1
        print(f"committed it as \"scope {a.round} (statements bundle)\" in {h[:11]}")
        return 0
    if a.cmd == "check":
        probs, disc = project.split(cfg, check(cfg, rd, rows, defs, md) + cited_name_problems(cfg, rd))
        for p in probs:
            print(project.problem_line(p, "signoff-check"))
        for p in disc:
            print(project.disclosed_line(p))
        print(f"sign-off check: {len(rows)} results, {len(defs)} definitions, {len(probs)} problem(s)"
              + (f", {len(disc)} disclosed (release mode: stops.py disclose records them)" if disc else ""))
        return 1 if probs else 0
    if a.cmd == "render":
        probs, disc = project.split(cfg, check(cfg, rd, rows, defs, md))
        for p in probs:
            print(project.problem_line(p, "signoff-check"))
        for p in disc:
            print(project.disclosed_line(p))
        if probs:
            print(f"FAIL: the sheet is incomplete ({len(probs)} problems); run `check` and fix first")
            return 1
        import fingerprint
        fps = fingerprint.compute(cfg)
        changed = changed_since_approval(os.path.join(project.REPO, cfg["rounds_dir"]), rows, fps, a.round)
        ok = render(cfg, rd, changed)
        print(f"wrote SIGNOFF.md" + (f"; {len(changed)} result(s) marked CHANGED since the last approval" if changed else "")
              + f"; its PDF is rendered by agents: python3 audits/render_record.py next --doc SIGNOFF --round {a.round}")
        return 0 if ok else 1
    if a.cmd == "approve":
        # B13 (U2 §8, restarts): an approve killed between writing its files and committing them leaves them
        # uncommitted. They are never committed as found: restored to the committed state now, and the
        # approval recomputed below is committed only when it equals the interrupted one (same sheet, same
        # answer); otherwise the human is asked again (interrupted_approval_restore)
        try:
            interrupted = interrupted_approval_restore(os.path.join(project.REPO, cfg["rounds_dir"]))
        except ValueError as e:
            print(f"FAIL[uncommitted-record] an interrupted approval could not be restored: {e}", file=sys.stderr)
            return 1
        if interrupted:
            print(f"note: an interrupted `signoff.py approve` left {', '.join(interrupted['paths'])} uncommitted: "
                  f"restored to the committed state; recomputing the approval", file=sys.stderr)
        if not a.how:
            print("FAIL: say --how individual (the human answered per result) or --how blanket "
                  "('all OK'); the report discloses which", file=sys.stderr)
            return 2
        if not a.by:
            print("FAIL: say --by human (the user read the sheet and approved) or --by agent (the "
                  "user chose to let the agent approve without reading); the report discloses which",
                  file=sys.stderr)
            return 2
        import fingerprint, datetime
        rdir = os.path.join(project.REPO, cfg["rounds_dir"])
        if a.by == "human" and project.involvement(cfg) == "hands-off" \
                and (fingerprint.approval_history(rdir, cfg)[1] or {}).get("by") != "human":
            # SWEEP-FIX G6: under hands-off the person handed the statements to the agent at intake; a recorded
            # human approval would make every later re-approval the human's question (a wait hands-off never has).
            # A run that already holds a human's approval (one recorded before this rule) keeps the B2 route for it
            print("FAIL: approve --by human is refused under the hands-off level: the person chose at intake not "
                  "to approve the statements, so the agent approves (`--by agent --how blanket`, stage2 step 8, "
                  "\"Under hands-off\")", file=sys.stderr)
            return 2
        target = os.path.join(rdir, fingerprint.APPROVED)
        reap, rprob = fingerprint.open_reapproval(rdir, project.REPO, cfg)
        if rprob:
            print(f"FAIL: {rprob}", file=sys.stderr); return 2
        if os.path.exists(target) and not reap:
            print(f"FAIL: {target} exists. A re-approval begins BEFORE the Lean edit: `signoff.py "
                  f"reapprove --begin --decls <a,b> --reason \"<why>\"`; this command then closes it.",
                  file=sys.stderr)
            return 2
        if reap and a.by == "agent":
            # B2 (U2 §5): the agent closes a re-approval only when the level (hands-off) or the intake's 5d
            # chose it AND the approval being replaced was its own; otherwise the change is the human's
            # QUESTION (never a stop): the run goes on in the pending state, only --deliver waits
            # the replaced approval as committed at the begin, never the working copy (B2 review)
            ok_, why_ = project.agent_may_reapprove(cfg, fingerprint.replaced_approval(rdir, cfg))
            if not ok_:
                print(f"PENDING[question] approve --by agent refused on the open re-approval of "
                      f"{', '.join(reap.get('decls') or [])}: {why_}. It is a QUESTION for the human, not a stop: ask "
                      f"them (run/reapproval.md) and go on with the run; when they approve the changed sheet, "
                      f"`signoff.py approve --by human`. Until then only project.py --deliver refuses.",
                      file=sys.stderr)
                return 1
        if reap and a.by == "human":
            # B2 review (byhuman): a human re-approval is evidenced by their verbatim answer, committed first
            hp_ = human_answer_problem(rdir, a.round, reap.get("decls") or [])
            if hp_:
                print(f"PENDING[question] approve --by human refused on the open re-approval of "
                      f"{', '.join(reap.get('decls') or [])}: {hp_}. Until they answer, the question stays open "
                      f"and only project.py --deliver refuses.", file=sys.stderr)
                return 1
            # B4 (U2 §3 M5): the human approves a re-approval's sheet after its gated fresh-reader pass, as at
            # Checkpoint B (stage2 step 7): the sheet that ships is this one
            rg_ = REAPPROVAL_READER_GATE(cfg, a.round)
            if rg_:
                print(f"FAIL: approve --by human refused on the open re-approval: the re-approval's sheet ({a.round}) "
                      f"has no passing fresh-reader check (`readers.py --doc signoff --round {a.round} --check`: "
                      f"{rg_[0]}{'; ...' if len(rg_) > 1 else ''}); run it (run/fresh-reader.md), then approve",
                      file=sys.stderr)
                return 1
        if not reap and a.by == "agent":
            # B2 review (rmrecords): over ANY earlier approval of the run (a file now, or one in the history,
            # REAPPROVAL.json's included) --by agent is a re-approval, whatever the records now say: the same
            # level rule, against the newest committed approval
            earlier, last = fingerprint.approval_history(rdir, cfg)
            ok_, why_ = project.agent_may_reapprove(cfg, last) if earlier else (True, "")
            if not ok_:
                print(f"PENDING[question] approve --by agent refused: this run has an earlier approval (its "
                      f"records, or their history), so this approval re-approves it: {why_}. It is the human's "
                      f"QUESTION (run/reapproval.md); `signoff.py approve --by human` once they answer.",
                      file=sys.stderr)
                return 1
        snap_p = os.path.join(rd, "FINGERPRINTS.json")
        if not os.path.exists(snap_p):
            print(f"FAIL: {snap_p} missing: the sheet's round has no fingerprint snapshot", file=sys.stderr)
            return 2
        bp = bundle_problem(rd, md)
        if bp:
            print(project.problem_line(bp, "signoff-check") + "\napproval REFUSED" + cap_grace(cfg, a.round, bp, "bundle"))
            return 1
        # C2 audit: the backstop of scope.py --statements -- no approval (the human's or the agent's, first or
        # re-approval) of statements whose hypotheses the walk lists unclassified
        import hypotheses
        blk_ = hypotheses.statement_blockers(cfg, rdir)
        if blk_:
            lines_ = hypotheses.statement_blocker_lines(blk_)
            print("\n".join(lines_) + "\napproval REFUSED" + cap_grace(cfg, a.round, lines_[0], "blocker"))
            return 1
        shown = None
        if a.by == "human":
            # PDF-AGENTS (approver, 2026-10-23): the human approves on the PDF made from THIS markdown (the fingerprint
            # guard, render_record.check); an md changed after the human was shown its PDF is rendered again and the
            # human is asked again (review 7). `no-pdf`: the human read the md itself
            gp_ = RENDER_GUARD(cfg, a.round)
            if gp_:
                print("approval REFUSED: " + "; ".join(" ".join(str(x).split()) for x in gp_)
                      + f". Render the sheet (python3 audits/render_record.py next --doc SIGNOFF --round {a.round}), show "
                        f"the human the new PDF and ask again (never a stop)", file=sys.stderr)
                return 1
            shown, sp_ = RENDER_SHOWN(cfg, a.round)
            if sp_:
                print("approval REFUSED: " + "; ".join(" ".join(str(x).split()) for x in sp_)
                      + f". Show the human the sheet's PDF as it is now (python3 audits/render_record.py shown --doc "
                        f"SIGNOFF --round {a.round}, then quote its lines) and ask again (never a stop)", file=sys.stderr)
                return 1
        fps = fingerprint.compute(cfg)
        excluded = [x.strip() for x in a.exclude.split(",") if x.strip()]
        doc, probs = approve(cfg, rd, rows, defs, fps, json.load(open(snap_p))["fingerprints"],
                             excluded, a.how, a.by, a.note)
        if shown is not None and not probs:
            doc["shown"] = shown        # what the human was shown: the PDF's sha256 and the render outcome
        for p_ in probs:
            print(project.problem_line(p_, "signoff-check"))
        if probs:
            fpch_ = [p_ for p_ in probs if "changed since the sheet was generated" in p_]
            # review M5(b): a fingerprint changed by a patched printer with the Lean unchanged is mechanical too
            print("approval REFUSED" + (cap_grace(cfg, a.round, fpch_[0], "fingerprint") if fpch_ else ""))
            return 1
        doc["commit"] = fingerprint.head(project.REPO)
        doc["date"] = datetime.date.today().isoformat()
        # review fix 4: the walk's binders at the approval, for "hypotheses added since the approval"
        bnd_, bwhy_ = approval_binders(cfg, rdir)
        if bnd_ is None:
            doc["binders_not_recorded"] = bwhy_
            print(f"note: the approval records no binders ({bwhy_}): the report will say \"hypotheses added "
                  f"since the approval: not computed\"")
        else:
            doc["binders"] = bnd_
        if interrupted and not same_approval(interrupted.get("doc"), doc):
            print(f"FAIL[uncommitted-record] the interrupted approval ({(interrupted.get('doc') or {}).get('round', '?')}, "
                  f"by {(interrupted.get('doc') or {}).get('by', '?')}) is not the approval this command computes now "
                  f"(another round, answer or sheet, or it was cut short): it was discarded, never committed. "
                  + ("Approve again yourself (the agent's approval, never a human wait): run approve again"
                     if a.by == "agent" else
                     "Ask the approver again (stage2-statements.md step 8 / reapproval.md), then run approve again"),
                  file=sys.stderr)
            return 1
        paths = [target]
        if reap:
            # close the re-approval in the same "approve R" commit: the old approval moves aside
            # (the report lists every earlier approval), the record is marked closed
            old_ = json.load(open(target)) if os.path.exists(target) else {}
            stem = f"APPROVED_FINGERPRINTS.{old_.get('date') or doc['date']}"
            aside, k = os.path.join(rdir, stem + ".json"), 1
            while os.path.exists(aside):
                k += 1; aside = os.path.join(rdir, f"{stem}.{k}.json")
            if os.path.exists(target):
                os.rename(target, aside); paths.append(aside)
            reap.update(closed=True, closed_by=f"approve {a.round}", closed_date=doc["date"])
            rp = os.path.join(rdir, fingerprint.REAPPROVAL)
            json.dump(reap, open(rp, "w"), indent=1, ensure_ascii=False); paths.append(rp)
        json.dump(doc, open(target, "w"), indent=1, ensure_ascii=False)
        n_ok = sum(1 for r in doc["rows"].values() if r["status"] == "approved")
        print(f"wrote {os.path.relpath(target, project.REPO)}: {n_ok} result(s) approved "
              f"({a.how}, by {a.by}), {len(excluded)} excluded, {len(doc['fingerprints'])} declarations frozen")
        try:
            # the approval file alone, by name: never the rounds dir (`add -A` swept other steps' files)
            h = project.commit_only(paths, f"approve {a.round}")
        except ValueError as e:
            print(f"FAIL: the approval was written but not committed ({e}); commit "
                  f"{', '.join(os.path.basename(x) for x in paths)}, by name, as \"approve {a.round}\"",
                  file=sys.stderr)
            return 1
        print(f"committed it as \"approve {a.round}\" in {h[:11]}")
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
    # B4 (U2 §3 F11, ADDENDUM N3): --refuted-by's Lean facts on a real fixture. `lem` is false at n = 0 and keeps
    # its `sorry` (N3: the refuted statement's own sorry may remain); `not_lem_as_printed` is sorry-free
    d = tempfile.mkdtemp(prefix="sgt-ref-")
    f = os.path.join(d, "RefT.lean")
    open(f, "w", encoding="utf-8").write(
        "import Lean\nnamespace RefT\n"
        "theorem lem : ∀ n : Nat, n - 1 < n := sorry\n"
        "def lem_as_printed : Prop := ∀ n : Nat, n - 1 < n\n"
        "theorem not_lem_as_printed : ¬ lem_as_printed := fun h => absurd (h 0) (by decide)\n"
        "def bad_as_printed : Prop := ∀ n : Nat, n - 2 < n\n"
        "theorem not_bad_as_printed : ¬ bad_as_printed := fun h => absurd (h 0) (by decide)\n"
        "theorem bad : ∀ n : Nat, n - 1 < n := sorry\n"
        "def sor_as_printed : Prop := ∀ n : Nat, n - 1 < n\n"
        "theorem not_sor_as_printed : ¬ sor_as_printed := sorry\n"
        "theorem sor : ∀ n : Nat, n - 1 < n := sorry\n"
        "def wt_as_printed : Prop := ∀ n : Nat, n - 1 < n\n"
        "theorem not_wt_as_printed : ¬ (∀ n : Nat, n < 0) := fun h => absurd (h 0) (by decide)\n"
        "theorem wt : ∀ n : Nat, n - 1 < n := sorry\n"
        "end RefT\n")
    rcfg = {"sweep": {"mode": "append", "file": f}}
    try:
        res = {}
        for x in ("lem", "bad", "sor", "wt"):
            dcl, asp = refutation_names(f"RefT.not_{x}_as_printed")
            res[x] = refutation_problems(refutation_facts(rcfg, f"RefT.not_{x}_as_printed", asp, dcl),
                                         f"RefT.not_{x}_as_printed", asp, dcl, True)
    except RuntimeError as e:
        print(f"  CRASH  refutation fixture did not run: {e}")
        return 3
    finally:
        shutil.rmtree(d, ignore_errors=True)
    for name, cond in [
            ("B4 N3/F11: a sorry-free refutation of `¬ lem_as_printed`, defeq to `lem`'s type, is accepted though "
             "`lem` itself is sorry", res["lem"] == []),
            ("B4 F11: an `_as_printed` that is not the approved statement (n - 2) is refused (non-equal)",
             any("approved at B" in p_ for p_ in res["bad"])),
            ("B4 N3: a refutation proved by sorry is refused (sorryAx)", any("sorryAx" in p_ for p_ in res["sor"])),
            ("B4 F11: a theorem whose type is not `¬ X_as_printed` is refused", any("is not `¬" in p_ for p_ in res["wt"]))]:
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)
    if not ok:
        print("  refutation results:", res)
    print("selftest (lean):", "ok" if ok else "FAILED")
    return 0 if ok else 1


def selftest_reapproval(d, say):
    """RULINGS A11: the re-approval record is begun before the edit, owned, and closed by approve."""
    import io, contextlib, fingerprint as fp, integrity
    ra = os.path.join(d, "reapp")
    os.makedirs(os.path.join(ra, "P", "R"))
    G = lambda *a_: subprocess.run(["git", "-C", ra, *a_], capture_output=True, text=True).stdout.strip()
    G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
    open(os.path.join(ra, "X.lean"), "w").write("theorem a : True := trivial\n")
    G("add", "X.lean"); G("commit", "-qm", "lean")
    P = os.path.join(ra, "P")
    json.dump({"commit": "c0", "date": "2026-01-01", "by": "agent", "fingerprints": {"N.main": "a", "N.b": "b"}},
              open(os.path.join(P, fp.APPROVED), "w"))
    G("add", "-A"); G("commit", "-qm", "approve R0")
    cfg = {"name": "P", "rounds_dir": "P", "involvement": "hands-off", "involvement_answer": "x"}
    keep = (project.REPO, project.select, fp.compute, globals()["build_bundle"], globals()["check"])
    project.REPO = ra
    try:
        def refused(decls, fps):
            try:
                reapprove_begin(cfg, decls, "missing theory", fps=fps); return ""
            except ValueError as e:
                return str(e)
        say("A11: a begin AFTER the edit (the listed fingerprint already changed) is refused",
            "already changed" in refused(["N.main"], {"N.main": "a2", "N.b": "b"}))
        say("A11: a begin for a declaration that is not approved is refused",
            "not approved" in refused(["N.zz"], {"N.main": "a", "N.b": "b"}))
        open(os.path.join(ra, "X.lean"), "a").write("-- edit\n")
        say("A11: a begin while a .lean file has uncommitted changes is refused",
            "uncommitted" in refused(["N.main"], {"N.main": "a", "N.b": "b"}))
        G("checkout", "-q", "X.lean")
        say("A11: nothing was recorded by a refused begin", not os.path.exists(os.path.join(P, fp.REAPPROVAL)))
        reapprove_begin(cfg, ["N.main"], "missing theory", fps={"N.main": "a", "N.b": "b"})
        rec, prob = fp.open_reapproval(P, ra)
        say("A11: the begin commits REAPPROVAL.json as 'approve (reapproval begin: ...)', with the Lean HEAD",
            G("log", "-1", "--format=%s").startswith(fp.REAPPROVAL_BEGIN) and rec and not prob
            and rec["begin_fingerprints"] == {"N.main": "a"} and len(rec["lean_head"]) >= 7)
        log = open(os.path.join(P, "RUN_LOG.md"), encoding="utf-8").read()
        say("A11: under hands-off the begin logs a [DELEGATED …; reversal: re-approve] line",
            "reversal: re-approve] change N.main — missing theory" in log)
        notes, drift = fp.split_drift({"N.main": "a", "N.b": "b"}, [("N.main", "changed"), ("N.b", "changed")], rec)
        say("A11: a change to the listed declaration is announced; one to another stays a drift",
            [n for n, _ in notes] == ["N.main"] and [n for n, _ in drift] == ["N.b"])
        late = dict(rec, begin_fingerprints={"N.main": "a2"})
        say("A11: a listed change whose begin fingerprint is not the approved one stays a drift",
            fp.split_drift({"N.main": "a"}, [("N.main", "changed")], late)[0] == [])
        say("A11: REAPPROVAL.json is an owned record (integrity OWNERS: 'approve')",
            integrity.owner("REAPPROVAL.json") == ("approve",))
        rp = os.path.join(P, fp.REAPPROVAL)
        good = open(rp).read()
        forged = json.loads(good); forged["decls"].append("N.b"); forged["begin_fingerprints"]["N.b"] = "b"
        json.dump(forged, open(rp, "w"))
        say("A11: a hand-edited, uncommitted REAPPROVAL.json is not trusted", fp.open_reapproval(P, ra)[1])
        G("add", "-A"); G("commit", "-qm", "tidy")
        say("A11: a REAPPROVAL.json committed by anything but the begin is not trusted",
            "not by `signoff.py reapprove" in (fp.open_reapproval(P, ra)[1] or ""))
        G("reset", "-q", "--hard", "HEAD~1")
        forged = json.loads(good); forged["lean_head"] = "0123456789a"
        json.dump(forged, open(rp, "w")); G("add", "-A"); G("commit", "-qm", fp.REAPPROVAL_BEGIN + ": forged)")
        say("A11: a record whose Lean HEAD is not in the Lean history is not trusted",
            "history" in (fp.open_reapproval(P, ra)[1] or ""))
        G("reset", "-q", "--hard", "HEAD~1")
        # approve closes it: the old approval moves aside, the record is closed, one 'approve R' commit
        open(os.path.join(P, "R", "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write("same\n")
        json.dump({"fingerprints": {"N.main": "a2", "N.b": "b"}}, open(os.path.join(P, "R", "FINGERPRINTS.json"), "w"))
        G("add", "-A"); G("commit", "-qm", "scope R")
        g = globals()
        def stub_same(cfg_, table=None):
            build_bundle.missing = []
            return "same\n", [("Theorem 1.1", ["N.main"])], []
        g["build_bundle"], g["check"] = stub_same, (lambda *a_, **k_: [])
        g["REAPPROVAL_READER_GATE"] = lambda *a_, **k_: []    # B4: the sheet's reader gate (tested on its own)
        project.select = lambda name=None: (cfg, "stub")
        fp.compute = lambda cfg_: {"N.main": "a2", "N.b": "b"}
        # B2 (U2 §5): approve --by agent on an open re-approval -- refused (a QUESTION, the record stays open)
        # for statements-only and involved, accepted for hands-off (below)
        import decisions as dc_
        for lvl_ in ("statements-only", "involved"):
            c_l = dict(cfg, involvement=lvl_)
            project.select = lambda name=None, c_l=c_l: (c_l, "stub")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent"])
            say(f"B2: under {lvl_} approve --by agent on an open re-approval is refused as a QUESTION, not a "
                f"failure line; the re-approval stays open and is the pending state's question",
                rc == 1 and "PENDING[question]" in buf.getvalue() and "FAIL" not in buf.getvalue()
                and fp.open_reapproval(P, ra)[0] is not None
                and (dc_.reapproval_question(c_l) or {}).get("decls") == ["N.main"]
                and dc_.question_refusal(c_l) is not None)
        say("B2: under hands-off (the agent's own approval replaced) the re-approval is no question",
            dc_.reapproval_question(cfg) is None and dc_.question_refusal(cfg) is None)
        # the pending state ends only at delivery: --deliver refuses (PENDING, no failure line), and a result
        # of the question is not "left unproved" for pending_unproved
        c_s = dict(cfg, involvement="statements-only")
        k3 = (dc_.unproved, dc_.adjudicated_since, dc_.goal_decls)
        try:
            dc_.unproved = lambda c_, *a_, **k_: {"decls": {"N.main": "t", "N.x": "t"}, "lines": {}, "goal": [],
                                                  "problems": []}
            dc_.adjudicated_since = lambda c_, d_: False
            dc_.goal_decls = lambda c_: set()
            pu = dc_.pending_unproved(c_s)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_d = project.deliver(c_s)
            say("B2: statements-only question open: pending_unproved leaves its statement to the question; "
                "project.py --deliver refuses with PENDING[question] (no failure line, so no stop)",
                pu == ["N.x"] and rc_d == 1 and buf.getvalue().startswith("PENDING[question]")
                and "RED" not in buf.getvalue() and "FAIL" not in buf.getvalue())
        finally:
            dc_.unproved, dc_.adjudicated_since, dc_.goal_decls = k3
        # drift with a pending re-approval question does not hang (U2 §4/§5): a change to ANOTHER approved
        # statement is a drift whose release cure is restoring it -- never a re-approval begun inside the stop
        # (the begin refuses an already changed declaration) -- and once restored the freeze check's own
        # split passes (the question's change stays NOTE[reapproval]) with its closer a FORMS check
        import stops as st_
        rec_q = fp.open_reapproval(P, ra)[0]
        drift_now = fp.split_drift({"N.main": "a", "N.b": "b"}, [("N.main", "changed"), ("N.b", "changed")], rec_q)[1]
        notes_after, drift_after = fp.split_drift({"N.main": "a", "N.b": "b"}, [("N.main", "changed")], rec_q)
        try:
            reapprove_begin(c_s, ["N.b"], "x", fps={"N.main": "a2", "N.b": "b2"}); begin_refused = False
        except ValueError as e:
            begin_refused = "already changed" in str(e)
        cl_ = project.closer("drift")
        say("B2: a drift while a re-approval QUESTION is pending: the cure restores the approved statement "
            "(a re-approval begin inside the stop is refused), then the freeze split passes; the closer is a "
            "read-only FORMS check, not the human",
            [n_ for n_, _ in drift_now] == ["N.b"] and drift_after == [] and [n_ for n_, _ in notes_after] == ["N.main"]
            and begin_refused and "restore the approved statement" in project.cure_text("drift")
            and project.release_kind("drift") != "human"
            and st_.command_problem(cl_, dict(c_s, mode="release")) is None)
        import make_report as mr_
        has_open = lambda c_: any("re-approval is OPEN" in str(x) for x in mr_.record_problems(P, cfg=c_))
        with contextlib.redirect_stdout(io.StringIO()):
            ho_ = (has_open(c_s), has_open(cfg))
        say("B2: the report check (Phase 0's too) does not refuse the open re-approval while it is the human's "
            "QUESTION (statements-only); it still refuses the agent's own open one (hands-off)", ho_ == (False, True))
        project.select = lambda name=None: (cfg, "stub")
        # review fix 4: the walk's binders (DEPENDENCIES.json, untracked as in real runs) go into the approval
        import dependencies as dep_
        bnd = {"thm": [{"binder": "h", "type_pp": "1 ≤ n"}]}
        dp_ = os.path.join(P, dep_.OUT)
        json.dump({"lean_sha256": "0" * 64, "binders": bnd, "assumes": {}}, open(dp_, "w"))
        stale_ = approval_binders(cfg, P)
        # C2 audit: the backstop of scope.py --statements -- a hypothesis the walk of HEAD lists unclassified (a
        # definition with no index Definition row) refuses the approval, before anything is written
        json.dump({"lean_sha256": dep_.lean_hash(cfg, "HEAD"), "binders": bnd,
                   "assumes": {"thm": [{"name": "N.Dom", "binder": "hx", "kind": "prop", "type_pp": "x ∈ N.Dom n",
                                        "embedded": False}]}}, open(dp_, "w"))
        head_b, buf = G("rev-parse", "HEAD"), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc_b = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent"])
        say("C2 audit: approve is refused (FAIL[index], nothing written or committed) while the walk lists a hypothesis "
            "nothing classifies",
            rc_b == 1 and "FAIL[index] `N.Dom`" in buf.getvalue() and "approval REFUSED" in buf.getvalue()
            and G("rev-parse", "HEAD") == head_b and not G("status", "--porcelain", "--", "P/R"))
        json.dump({"lean_sha256": dep_.lean_hash(cfg, "HEAD"), "binders": bnd, "assumes": {}}, open(dp_, "w"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent"])
        os.remove(dp_)
        say("review fix 4: approve records the current walk's binders in APPROVED_FINGERPRINTS.json (its own "
            "commit; DEPENDENCIES.json stays uncommitted); a stale walk records none, and says why",
            rc == 0 and json.load(open(os.path.join(P, fp.APPROVED))).get("binders") == bnd
            and stale_[0] is None and "not the walk of the Lean files at HEAD" in stale_[1]
            and approval_binders(cfg, P)[0] is None)
        names = G("show", "--name-only", "--format=%s", "HEAD").split("\n")
        say("A11: approve closes the re-approval: old approval moved aside, record closed, in 'approve R'",
            rc == 0 and names[0] == "approve R"
            and {"P/APPROVED_FINGERPRINTS.json", "P/APPROVED_FINGERPRINTS.2026-01-01.json", "P/REAPPROVAL.json"}
            <= set(names[1:]) and json.load(open(rp))["closed"] is True
            and fp.open_reapproval(P, ra) == (None, None) and not G("status", "--porcelain", "--", "P/R"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent"])
        say("A11: with no open re-approval, approve over an approval is refused and names the begin",
            rc != 0 and "reapprove --begin" in buf.getvalue())
        # ROUND3 H1: the report lists every re-approval from the record's history
        try:
            reapprove_begin(cfg, ["N.main"], "second change", fps={"N.main": "a2", "N.b": "b"})
        except ValueError:
            pass
        cyc = fp.reapprovals(P)
        say("H1: every re-approval of the run is kept (history): the closed one and the open second one",
            len(cyc) == 2 and cyc[0].get("closed") and cyc[0]["decls"] == ["N.main"]
            and not cyc[1].get("closed") and cyc[1]["begins"][-1]["reason"] == "second change"
            and "second change" in (fp.open_reapproval_problem(P) or ""))
    finally:
        project.REPO, project.select, fp.compute, globals()["build_bundle"], globals()["check"] = keep
        globals()["REAPPROVAL_READER_GATE"] = reapproval_reader_gate


def selftest_reapprove_level(d, say):
    """B2 (U2 §5): who may close an open re-approval with --by agent: (hands-off, or the intake's 5d chose
    the agent) AND the replaced approval was the agent's; an unreadable 5d means the human approves."""
    keep = project.REPO
    n = [0]

    def ok(lvl, by, intake=None, later=None):
        n[0] += 1
        rr = os.path.join(d, f"lvl5d-{n[0]}")
        os.makedirs(os.path.join(rr, "P"))
        G = lambda *a_: subprocess.run(["git", "-C", rr, *a_], capture_output=True, text=True).stdout.strip()
        G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
        log = os.path.join(rr, "P", "RUN_LOG.md")
        for txt in (intake, later):     # a later edit of the logged intake changes nothing
            if txt is not None:
                open(log, "w").write("# Run log\n## Intake (2026-01-01)\n" + txt + "## Rounds\n")
                G("add", "-A"); G("commit", "-qm", "log")
        project.REPO = rr
        try:
            return project.agent_may_reapprove({"rounds_dir": "P", "involvement": lvl}, {"by": by})[0]
        finally:
            project.REPO = keep
    say("B2: hands-off, replaced approval the agent's -> the agent may re-approve", ok("hands-off", "agent"))
    say("B2: hands-off, replaced approval a human's -> refused (the human's)", not ok("hands-off", "human"))
    say("B2: involved with no readable 5d -> refused (the human approves)", not ok("involved", "agent"))
    say("B2: statements-only, 5d the human, replaced by the agent -> refused",
        not ok("statements-only", "agent", "- 5d: Jane Doe\n"))
    say("B2: involved, 5d chose the agent, replaced by the agent -> the agent may re-approve",
        ok("involved", "agent", "- 5d: agent\n"))
    say("B2: involved, 5d chose the agent, replaced by a human -> refused",
        not ok("involved", "human", "- 5d: agent\n"))
    say("B2: a 5d edited to 'agent' after the intake was logged changes nothing (first logged answer)",
        not ok("involved", "agent", "- 5d: human Jane Doe\n", later="- 5d: agent\n"))
    # B2 review 3: 5d is read only in its fixed form; statements-only never lets the agent re-approve
    say("B2 review 3: a 5d not in the fixed form ('the agent (let it approve)', 'operator', '5d. agent', "
        "two lines) is the human",
        not any(ok("involved", "agent", t_) for t_ in ("- 5d: the agent (let it approve)\n", "- 5d: operator\n",
                                                        "5d. agent\n", "- 5d: agent\n- 5d: human X\n")))
    say("B2 review 3: under statements-only even `- 5d: agent` and the agent's own approval -> refused",
        not ok("statements-only", "agent", "- 5d: agent\n"))
    try:
        project.five_d_line("the agent"); bad_ok = True
    except ValueError:
        bad_ok = False
    say("B2 review 3: prompt.py --intake --5d prints the fixed form and refuses any other",
        project.five_d_line("agent") == "- 5d: agent" and project.five_d_line(" human  Jane Doe") == "- 5d: human Jane Doe"
        and not bad_ok)


REF_OK = {"thm": "theorem", "asp": "def", "type": "ok", "defeq": "ok", "axioms": "propext,Classical.choice"}


def _b2_scenario(d, tag, lvl, intake, by="human", refuted_by=None):
    """A fresh repo with a human's (or agent's) approval of N.main/N.b and an open re-approval of N.main
    (begun, Lean changed, sheet R stubbed): the B2 review repros (build/B2-attack). Returns (P, cfg, G,
    approve(by) -> (rc, output)). The caller restores the stubs with _b2_restore."""
    import io, contextlib, fingerprint as fp
    t = os.path.join(d, f"b2r-{tag}")
    P = os.path.join(t, "P"); os.makedirs(os.path.join(P, "R"))
    G = lambda *a_: subprocess.run(["git", "-C", t, *a_], capture_output=True, text=True).stdout.strip()
    G("init", "-q"); G("config", "user.email", "t@t"); G("config", "user.name", "t")
    open(os.path.join(t, "X.lean"), "w").write("theorem a : True := trivial\n")
    open(os.path.join(P, "RUN_LOG.md"), "w").write("# Run log\n## Intake (2026-01-01)\n- 5c: x\n" + intake
                                                   + "## Rounds\n")
    G("add", "-A"); G("commit", "-qm", "intake")
    json.dump({"commit": "c0", "date": "2026-01-01", "by": by, "fingerprints": {"N.main": "a", "N.b": "b"}},
              open(os.path.join(P, fp.APPROVED), "w"))
    G("add", "-A"); G("commit", "-qm", "approve R0")
    cfg = {"name": "P", "rounds_dir": "P", "involvement": lvl, "involvement_answer": "x", "namespace": "N"}
    project.REPO = t
    project.select = lambda name=None: (cfg, "stub")
    g = globals()
    if refuted_by:
        # B4: the begin of a refuted statement's repair, the Lean facts stubbed (selftest_lean runs them)
        g["REFUTATION_FACTS"] = lambda *a_: dict(REF_OK)
    with contextlib.redirect_stdout(io.StringIO()):
        reapprove_begin(cfg, ["N.main"], "lemma false", fps={"N.main": "a", "N.b": "b", "N.main_as_printed": "p"},
                        refuted_by=refuted_by, goals=[])
    open(os.path.join(P, "R", "STATEMENTS_BUNDLE.md"), "w").write("same\n")
    json.dump({"fingerprints": {"N.main": "a2", "N.b": "b"}}, open(os.path.join(P, "R", "FINGERPRINTS.json"), "w"))
    G("add", "-A"); G("commit", "-qm", "scope R")

    def stub_same(cfg_, table=None):
        build_bundle.missing = []
        return "same\n", [("Theorem 1.1", ["N.main"])], []
    g["build_bundle"], g["check"] = stub_same, (lambda *a_, **k_: [])
    g["REAPPROVAL_READER_GATE"] = lambda *a_, **k_: []    # B4: the sheet's reader gate (tested on its own)
    g["RENDER_GUARD"] = lambda *a_, **k_: []      # the sheet's PDF guard (render_record.py --selftest holds it)
    g["RENDER_SHOWN"] = lambda *a_, **k_: ({"pdf_sha256": "0" * 64, "outcome": "verified"}, [])
    fp.compute = lambda cfg_: {"N.main": "a2", "N.b": "b", "N.main_as_printed": "p"}

    def approve_(by):
        o = io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(o):
            rc = main(["approve", "--round", "R", "--how", "blanket", "--by", by])
        return rc, o.getvalue()
    return P, cfg, G, approve_


def selftest_b2_review(d, say):
    """The B2 review findings (build/B2.md "Review fixes"), each a repro of build/B2-attack/attack.py."""
    import io, contextlib, fingerprint as fp, decisions as dc_
    keep = (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
            globals()["build_bundle"], globals()["check"])
    try:
        # 1. symlink5d: RUN_LOG.md replaced by a symlink to a file whose "## Intake" names the agent
        P, cfg, G, appr = _b2_scenario(d, "symlink", "involved", "- 5d: human Jane Doe\n")
        open(os.path.join(P, "notes.md"), "w").write("# notes\n## Intake\n- 5d: agent\n")
        G("add", "-A"); G("commit", "-qm", "notes")
        os.remove(os.path.join(P, "RUN_LOG.md")); os.symlink("notes.md", os.path.join(P, "RUN_LOG.md"))
        G("add", "-A"); G("commit", "-qm", "log")
        say("B2 review 1: a RUN_LOG.md symlinked to another file is not read as the intake (5d stays the human)",
            project.approver_5d(P) != "agent")
        # 1b. the replaced approval's `by` is read as committed at the begin, never from the working copy
        P, cfg, G, appr = _b2_scenario(d, "byedit", "involved", "- 5d: agent\n")
        a_ = json.load(open(os.path.join(P, fp.APPROVED))); a_["by"] = "agent"
        json.dump(a_, open(os.path.join(P, fp.APPROVED), "w"))
        rc, out = appr("agent")
        say("B2 review 1: an uncommitted edit of the replaced approval's `by` to agent does not let "
            "approve --by agent close a human's re-approval (involved, 5d agent)",
            rc == 1 and "PENDING[question]" in out and dc_.reapproval_question(cfg) is not None)
        # 2. forgeclose: REAPPROVAL.json marked closed by hand, the old approval moved aside, committed as
        # "approve R" -- not signoff's own close (that commit writes the new approval)
        import make_report as mr_, io, contextlib
        P, cfg, G, appr = _b2_scenario(d, "forge", "statements-only", "- 5d: human Jane Doe\n")
        r_ = json.load(open(os.path.join(P, fp.REAPPROVAL)))
        r_.update(closed=True, closed_by="approve R", closed_date="2026-10-22")
        json.dump(r_, open(os.path.join(P, fp.REAPPROVAL), "w"), indent=1)
        G("mv", "P/" + fp.APPROVED, "P/APPROVED_FINGERPRINTS.2026-01-01.json"); G("add", "-A")
        G("commit", "-qm", "approve R")
        rc, out = appr("agent")
        with contextlib.redirect_stdout(io.StringIO()):
            rp_ = mr_.record_problems(P, cfg=cfg)
        say("B2 review 2: a close forged by hand (\"approve R\" moving the approval aside) is no close: the "
            "record is untrusted, approve --by agent refused, the report check RED on the open re-approval",
            rc != 0 and not os.path.exists(os.path.join(P, fp.APPROVED))
            and fp.open_reapproval(P, project.REPO)[1] and any("re-approval is OPEN" in str(x) for x in rp_)
            and not fp.reapprovals(P)[-1].get("closed"))
        # 2b. closed: an uncommitted `closed: true`
        P, cfg, G, appr = _b2_scenario(d, "closed", "statements-only", "- 5d: human Jane Doe\n")
        r_ = json.load(open(os.path.join(P, fp.REAPPROVAL))); r_["closed"] = True
        json.dump(r_, open(os.path.join(P, fp.REAPPROVAL), "w"))
        say("B2 review 2: an uncommitted `closed: true` is not trusted (the re-approval stays open)",
            fp.open_reapproval(P, project.REPO)[1] is not None and fp.open_reapproval_problem(P))
        # 2c. rmrecords: REAPPROVAL.json removed and the approval moved aside, so approve looks like a first one
        P, cfg, G, appr = _b2_scenario(d, "rm", "statements-only", "- 5d: human Jane Doe\n")
        G("rm", "-q", "P/" + fp.REAPPROVAL); G("mv", "P/" + fp.APPROVED, "P/APPROVED_FINGERPRINTS.2026-01-01.json")
        G("commit", "-qm", "approve R (tidy)")
        rc, out = appr("agent")
        say("B2 review 2: with the records removed, approve --by agent over the run's earlier (human) approval "
            "is refused", rc == 1 and "PENDING[question]" in out and not os.path.exists(os.path.join(P, fp.APPROVED)))
        # 4. compat MED-1: the re-approval question offers (c) only where the agent may re-approve
        qs = {}
        for lvl_, five_ in (("statements-only", "- 5d: agent\n"), ("involved", "- 5d: human Jane Doe\n"),
                            ("hands-off", "")):
            P, cfg, G, appr = _b2_scenario(d, f"ask-{lvl_}", lvl_, five_,
                                           by="agent" if lvl_ == "hands-off" else "human")
            qs[lvl_] = reapproval_ask(cfg, "R")
        say("B2 review 4: the re-approval question offers (c) only when the agent may re-approve "
            "(statements-only and involved with a human 5d: (a)/(b) only; hands-off: (c) too)",
            all("**(a)**" in q_ and "**(b)**" in q_ for q_ in qs.values())
            and "**(c)**" not in qs["statements-only"] and "**(c)**" not in qs["involved"]
            and "**(c)**" in qs["hands-off"])
        # 5. byhuman: approve --by human needs the human's verbatim answer, committed before the approve
        P, cfg, G, appr = _b2_scenario(d, "byhuman", "statements-only", "- 5d: human Jane Doe\n")
        rc0, out0 = appr("human")
        project.log_append(cfg, "Re-approvals", '- human answer (round Q; N.main): "yes, an older sheet"')
        G("add", "P/RUN_LOG.md"); G("commit", "-qm", "log an answer to another round")
        rc0b, _ = appr("human")
        project.log_append(cfg, "Re-approvals", '- human answer (round R; N.main): "yes, approve the weakened lemma"')
        rc1, out1 = appr("human")             # logged but not committed
        G("add", "P/RUN_LOG.md"); G("commit", "-qm", "log the answer")
        rc2, out2 = appr("human")
        say("B2 review 5: approve --by human on an open re-approval is refused until the human's verbatim answer "
            "naming the declaration and the round is committed under ## Re-approvals; then it closes",
            rc0 == 1 and "PENDING[question]" in out0 and "human answer (round R; N.main)" in out0
            and rc0b == 1 and rc1 == 1 and rc2 == 0 and json.load(open(os.path.join(P, fp.REAPPROVAL)))["closed"] is True
            and fp.open_reapproval_problem(P, cfg) is None)
        # 6. the begin of a question logs it under ## Open questions (a DECISIONS.md entry); not under hands-off
        oq = lambda P_: dc_.section(open(os.path.join(P_, "RUN_LOG.md"), encoding="utf-8").read(), "Open questions")
        P, cfg, G, appr = _b2_scenario(d, "oq", "statements-only", "- 5d: human Jane Doe\n")
        P2, cfg2, G2, appr2 = _b2_scenario(d, "oq-ho", "hands-off", "", by="agent")
        say("B2 review 6: reapprove --begin of a QUESTION logs it under ## Open questions (DECISIONS.md lists it); "
            "a hands-off begin does not",
            "re-approval QUESTION: the change to N.main" in oq(P) and "re-approval QUESTION" not in oq(P2))
        # 6b. a rejected change: restore the approved statement, then approve --by human with the recorded answer
        project.REPO, project.select = os.path.dirname(P), (lambda name=None: (cfg, "stub"))
        fp.compute = lambda cfg_: {"N.main": "a", "N.b": "b"}
        json.dump({"fingerprints": {"N.main": "a", "N.b": "b"}}, open(os.path.join(P, "R", "FINGERPRINTS.json"), "w"))
        project.log_append(cfg, "Re-approvals", '- human answer (round R; N.main): "no: keep the statement I approved"')
        G("add", "-A"); G("commit", "-qm", "restore N.main; log the answer")
        rc, out = appr("human")
        new_ = json.load(open(os.path.join(P, fp.APPROVED)))
        say("B2 review 6: a rejected change has a way out: the approved statement restored, approve --by human "
            "with the recorded answer closes the re-approval on the original fingerprints",
            rc == 0 and new_["fingerprints"]["N.main"] == "a" and new_["by"] == "human"
            and fp.open_reapproval(P, project.REPO) == (None, None))
        # SWEEP-FIX D1 (G2): a rejected change at the re-approval cap (no statement round left to show the restored
        # statement; the re-approval round's bundle is stale): approve the sheet of the round the replaced approval
        # approved -- its bundle and fingerprints are the restored statements'
        P, cfg, G, appr = _b2_scenario(d, "capexit", "involved", "- 5d: human Jane Doe\n")
        os.makedirs(os.path.join(P, "R0"))
        open(os.path.join(P, "R0", "STATEMENTS_BUNDLE.md"), "w").write("same\n")
        json.dump({"fingerprints": {"N.main": "a", "N.b": "b"}}, open(os.path.join(P, "R0", "FINGERPRINTS.json"), "w"))
        open(os.path.join(P, "R", "STATEMENTS_BUNDLE.md"), "w").write("changed\n")
        G("add", "-A"); G("commit", "-qm", "scope R0 / R (fixture)")
        fp.compute = lambda cfg_: {"N.main": "a", "N.b": "b", "N.main_as_printed": "p"}
        project.log_append(cfg, "Re-approvals", '- human answer (round R0; N.main): "no: keep the statement I approved"')
        G("add", "-A"); G("commit", "-qm", "restore N.main; log the answer")
        rcR, outR = appr("human")

        def appr0(by):
            o = io.StringIO()
            with contextlib.redirect_stdout(o), contextlib.redirect_stderr(o):
                rc = main(["approve", "--round", "R0", "--how", "blanket", "--by", by])
            return rc, o.getvalue()
        rc0, out0 = appr0("human")
        new0 = json.load(open(os.path.join(P, fp.APPROVED)))
        say("SWEEP-FIX D1 (G2): a rejected change at the re-approval cap has a way out with no new statement round: "
            "the re-approval round's stale sheet is refused, the sheet of the round the replaced approval approved is "
            "approved (--round <that round>) and closes the re-approval on the original fingerprints",
            rcR == 1 and "is stale" in (bundle_problem(os.path.join(P, "R"), "same\n") or "") and rc0 == 0 and new0.get("round") == "R0"
            and new0["fingerprints"]["N.main"] == "a" and fp.open_reapproval(P, project.REPO) == (None, None))
        # SWEEP-FIX G6: under hands-off --by human is refused (the agent approves; a human approval would make every
        # later re-approval the human's question, a wait hands-off never has)
        P, cfg, G, appr = _b2_scenario(d, "g6", "hands-off", "", by="agent")
        rcH, outH = appr("human")
        rcA, _outA = appr("agent")
        say("SWEEP-FIX G6: approve --by human is refused under hands-off (the agent approves: --by agent)",
            rcH == 2 and "refused under the hands-off level" in outH and rcA == 0)
        # SWEEP-FIX D1: a stale bundle is the printer's (mechanical) only while the Lean is unchanged since the round
        t_ = os.path.join(d, "lean-unch"); os.makedirs(t_)
        g_ = lambda *a_: subprocess.run(["git", "-C", t_, *a_], capture_output=True, text=True).stdout.strip()
        g_("init", "-q"); g_("config", "user.email", "t@t"); g_("config", "user.name", "t")
        open(os.path.join(t_, "X.lean"), "w").write("theorem a : True := trivial\n")
        g_("add", "-A"); g_("commit", "-qm", "x")
        rn_ = f"2026-01-01-full-{g_('rev-parse', 'HEAD')[:11]}"
        project.REPO = t_
        u1 = lean_unchanged_since({"lean_files": ["X.lean"]}, rn_)
        open(os.path.join(t_, "X.lean"), "a").write("theorem b : True := trivial\n")
        u2 = lean_unchanged_since({"lean_files": ["X.lean"]}, rn_)
        say("SWEEP-FIX D1: the Lean is unchanged since a round's commit -> a stale bundle there is the printer's "
            "(grace); changed (even uncommitted) -> the statements' (no grace); an unreadable round name -> no grace",
            u1 is True and u2 is False and lean_unchanged_since({"lean_files": ["X.lean"]}, "R") is False)
        here = os.path.dirname(os.path.abspath(__file__))
        ra_md = open(os.path.join(here, "run", "reapproval.md"), encoding="utf-8").read()
        s5_md = open(os.path.join(here, "run", "stage5-delivery.md"), encoding="utf-8").read()
        say("B2 review 6: reapproval.md step 2 and stage5 step 5 say PENDING[question] for the human's question "
            "(not RED), stage 5 says to wait for the human, and the way out of a rejected change is documented",
            "is RED: a run is never delivered with one open" not in ra_md and "PENDING[question]" in s5_md
            and "RED: close it before delivering" not in s5_md and "wait for the human" in s5_md
            and "rejected change" in ra_md)
    finally:
        (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
         globals()["build_bundle"], globals()["check"]) = keep
        globals()["REAPPROVAL_READER_GATE"] = reapproval_reader_gate


def selftest_b4(d, say):
    """B4 (U2 §3 F11, F12 consumers, M5; ADDENDUM N3): --refuted-by, the CHANGED marks of the delivered sheet, the
    hands-off re-approval line, the reader gate of a human re-approval."""
    import io, contextlib
    import fingerprint as fp
    keep = (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
            globals()["build_bundle"], globals()["check"], globals()["REFUTATION_FACTS"])
    T, A, D = "N.not_main_as_printed", "N.main_as_printed", "N.main"

    def _raises(f):
        try:
            f()
        except ValueError:
            return True
        return False
    try:
        say("B4 F11: --refuted-by names `<ns>.not_<X>_as_printed`; the refuted declaration and its `_as_printed` follow",
            refutation_names(T) == (D, A) and refutation_names("not_lem_as_printed") == ("lem", "lem_as_printed")
            and _raises(lambda: refutation_names("N.main_false")) and _raises(lambda: refutation_names("N.not_main"))
            and _raises(lambda: refutation_names("N..not_main_as_printed")))
        try:
            refutation_names("N.main_as_printed_false")
            _msg10 = ""
        except ValueError as e:
            _msg10 = str(e)
        say("trial #10: --refuted-by reads the one refutation name (make_report.AS_PRINTED) and refuses another with "
            "its exact rename", "rename it `N.not_main_as_printed`" in _msg10)
        rp = lambda f, b=True: " ".join(refutation_problems(dict(REF_OK, **f), T, A, D, b))
        say("B4 F11/N3: a sorry-free refutation of `¬ X_as_printed`, X_as_printed defeq to the type approved at B: "
            "accepted (the refuted X's own sorry is not looked at)", rp({}) == "")
        say("B4 N3: a refutation whose axioms include sorryAx is refused; an extra axiom too; axioms not read too",
            "sorryAx" in rp({"axioms": "propext,sorryAx"}) and "my_ax" in rp({"axioms": "my_ax"})
            and "not read" in " ".join(refutation_problems({k: v for k, v in REF_OK.items() if k != "axioms"}, T, A, D, True)))
        say("B4 F11: a missing theorem, a non-theorem, a type other than `¬ X_as_printed`, a missing or non-Prop "
            "`_as_printed` are refused",
            "not in the project" in rp({"thm": "missing"}) and "not a theorem" in rp({"thm": "notheorem"})
            and "is not `¬" in rp({"type": "bad"}) and "does not exist" in rp({"asp": "missing"})
            and "not a `def ... : Prop`" in rp({"asp": "notprop"}))
        say("B4 F11: `_as_printed` not definitionally equal to the statement approved at B is refused (non-equal)",
            "approved at B" in rp({"defeq": "bad"}) and "approved at B" not in rp({"defeq": "bad"}, b=False))
        # the begin, end to end in a repo (hands-off: the agent repairs, never a stop)
        P, cfg, G, appr = _b2_scenario(d, "b4-ok", "hands-off", "", by="agent", refuted_by=T)
        rec = json.load(open(os.path.join(P, fp.REAPPROVAL)))
        log_ = open(os.path.join(P, "RUN_LOG.md")).read()
        say("B4 F11: --refuted-by (no --decls) begins the re-approval of the refuted declaration and records the "
            "refutation, its `_as_printed` fingerprint and the fingerprint approved at B; hands-off: [DELEGATED] line",
            rec["decls"] == [D] and (rec.get("refuted") or {}).get(D, {}).get("by") == T
            and rec["refuted"][D]["as_printed_fp"] == "p"
            and rec["refuted"][D]["b_fingerprint"] == "a" and rec["begins"][-1].get("refuted_by") == T
            and "[DELEGATED" in log_ and f"refuted by `{T}`" in log_)
        rc, out = appr("agent")
        say("B4 hands-off: the agent closes its repair (approve --by agent), no stop, no question", rc == 0)

        def begin_(t=T, decls=(), fps_=None, goals=(), facts=None):
            globals()["REFUTATION_FACTS"] = lambda *a_: dict(REF_OK, **(facts or {}))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    reapprove_begin(cfg, list(decls), "still false", refuted_by=t, goals=list(goals),
                                    fps=fps_ or {"N.main": "a2", "N.b": "b", "N.main_as_printed": "p"})
                return ""
            except ValueError as e:
                return str(e)
        n0 = G("rev-list", "--count", "HEAD")
        r_wrongdecl = begin_(decls=["N.b"])
        r_goal = begin_(goals=["N.main"])
        r_sorry = begin_(facts={"axioms": "sorryAx"})
        r_newasp = begin_(fps_={"N.main": "a2", "N.b": "b", "N.main_as_printed": "p2"})
        say("B4: --refuted-by refuses a refutation of a declaration --decls does not list, a goal result (stop 1), "
            "a refutation using sorry; nothing committed",
            "does not list" in r_wrongdecl and "goal result" in r_goal and "stop 1" in r_goal
            and "sorryAx" in r_sorry and G("rev-list", "--count", "HEAD") == n0)
        say("B4 F11: after a re-approved correction, a new refutation must be of the SAME `_as_printed` the first "
            "repair checked (fingerprint): a changed one is refused (no second weakening)",
            "first repair refuted" in r_newasp)
        r_fail = begin_()
        rec2 = json.load(open(os.path.join(P, fp.REAPPROVAL)))
        say("B4 F11: a failed correction (the corrected statement refuted again) begins a new re-approval against "
            "the same `_as_printed`, recorded as such",
            r_fail == "" and (rec2.get("refuted") or {}).get(D, {}).get("check") == "same as_printed as the first repair"
            and not rec2.get("closed"))
        # a re-approval that was no refutation, then a refutation of the re-approved encoding: refused
        P2, cfg2, G2, appr2 = _b2_scenario(d, "b4-enc", "hands-off", "", by="agent")
        appr2("agent")
        cfg = cfg2
        r_enc = begin_()
        say("B4 F11: a refutation of a statement re-approved since B (no earlier --refuted-by of it) is refused",
            "recorded by no earlier --refuted-by" in r_enc)
        # M5: the delivered sheet keeps its CHANGED marks after its approval; approvals in the order made
        rws = [("Theorem 1.1", ["N.main"])]
        fps_ = {"N.main": "a2", "N.b": "b"}
        say("B4 M5: the re-approval's sheet, rendered again after its approval (it is the latest approval), still "
            "marks the changed result CHANGED (compared with the approval before it); without the round it would not",
            set(changed_since_approval(P, rws, fps_, "R")) == {"Theorem 1.1"}
            and changed_since_approval(P, rws, fps_) == {})
        q = os.path.join(d, "b4-order"); os.makedirs(q)
        for name, doc in (("APPROVED_FINGERPRINTS.2026-10-22.json", {"date": "2026-10-20", "commit": "fff", "round": "R1",
                                                                      "fingerprints": {"N.main": "a"}}),
                          ("APPROVED_FINGERPRINTS.2026-10-22.2.json", {"date": "2026-10-21", "commit": "000", "round": "R2",
                                                                        "fingerprints": {"N.main": "a2"}}),
                          ("APPROVED_FINGERPRINTS.json", {"date": "2026-10-22", "commit": "111", "round": "R3",
                                                          "fingerprints": {"N.main": "a3"}})):
            json.dump(doc, open(os.path.join(q, name), "w"))
        say("B4 M5: approvals are ordered as made (moved-aside copies by name, the current one last), never by "
            "commit hash: R3's sheet is compared with R2's approval",
            [x["round"] for x in approvals(q)] == ["R1", "R2", "R3"]
            and changed_since_approval(q, [("T", ["N.main"])], {"N.main": "a3"}, "R3") == {"T": "2026-10-21"})
        # B4 review fix 4: after two re-approvals the shipped sheet (the latest approval's) marks every result changed
        # in either, and so does that sheet before its approval (the same marks: the reader's pass is kept); a later
        # sheet with nothing changed since the latest approval marks none
        q2 = os.path.join(d, "b4-union"); os.makedirs(q2)
        rw2 = [("T", ["N.main"]), ("B", ["N.b"]), ("U", ["N.u"])]
        st2 = [("APPROVED_FINGERPRINTS.2026-10-20.json", "2026-10-20", "R1", {"N.main": "a", "N.b": "b", "N.u": "u"}),
               ("APPROVED_FINGERPRINTS.2026-10-21.json", "2026-10-21", "R2", {"N.main": "a2", "N.b": "b", "N.u": "u"}),
               ("APPROVED_FINGERPRINTS.json", "2026-10-22", "R3", {"N.main": "a2", "N.b": "b3", "N.u": "u"})]
        for name, dt, rn, fpx in st2:
            json.dump({"date": dt, "round": rn, "fingerprints": fpx}, open(os.path.join(q2, name), "w"))
        fp3 = st2[2][3]
        u_ship = changed_since_approval(q2, rw2, fp3, "R3")
        u_later = changed_since_approval(q2, rw2, fp3, "R4")
        os.remove(os.path.join(q2, "APPROVED_FINGERPRINTS.json"))
        os.rename(os.path.join(q2, st2[1][0]), os.path.join(q2, "APPROVED_FINGERPRINTS.json"))
        u_pend = changed_since_approval(q2, rw2, fp3, "R3")
        say("B4 review fix 4: after several re-approvals the shipped sheet marks CHANGED every result changed in any "
            "re-approval (each since the approval it changed after); the same marks before its approval; a later "
            "sheet with nothing changed marks none",
            u_ship == {"T": "2026-10-20", "B": "2026-10-21"} and u_pend == u_ship and u_later == {})
        after, before = hands_off_line(True, 2), hands_off_line(False, 2)
        say("B4 M5: a hands-off re-approval sheet's first line says K re-approved by the agent, marked CHANGED (before: "
            "awaiting); the approval stamp maps one to the other (the reader's pass is kept); a first approval's "
            "line is unchanged",
            after.startswith(HANDS_OFF_LINE) and "Statements unchanged since the latest approval; 2 re-approved by "
            "the agent, marked CHANGED." in after and "awaiting re-approval by the agent" in before
            and unstamp(after) == before and unstamp(before) == before
            and hands_off_line(True, 0) == HANDS_OFF_LINE and hands_off_line(False) == HANDS_OFF_PENDING)
        # M5: a human re-approval (statements-only) waits for the sheet's fresh-reader pass
        P3, cfg3, G3, appr3 = _b2_scenario(d, "b4-reader", "statements-only", "- 5d: human\n", refuted_by=T)
        import decisions as dc_
        rc_ag, o_ag = appr3("agent")
        qr_ = dc_.question_refusal(cfg3)
        project.log_append(cfg3, "Re-approvals", '- human answer (round R; N.main): "approved"')
        G3("add", "-A"); G3("commit", "-qm", "log answer")
        globals()["REAPPROVAL_READER_GATE"] = lambda *a_: ["no fresh-reader pass for signoff-R"]
        rc_r, o_r = appr3("human")
        globals()["REAPPROVAL_READER_GATE"] = lambda *a_: []
        rc_ok, o_ok = appr3("human")
        open(os.path.join(P3, "R", "SIGNOFF.md"), "w").write("sheet\n")

        say("B4 M5: the reader gate of a re-approval sheet is readers.py's check of `--doc signoff --round R`: a sheet "
            "with no fresh-reader pass fails it", bool(reapproval_reader_gate(cfg3, "R")))
        P4, cfg4, G4, appr4 = _b2_scenario(d, "b4-inv", "involved", "- 5d: human\n", refuted_by=T)
        rc_ai, o_ai = appr4("agent")
        say("B4 (approved-then-refuted): under statements-only and involved the repair is the human's QUESTION, never "
            "a stop: approve --by agent is PENDING[question], and only delivery waits (question_refusal)",
            rc_ag == 1 and "PENDING[question]" in o_ag and bool(qr_) and "QUESTION" in str(qr_)
            and rc_ai == 1 and "PENDING[question]" in o_ai and bool(dc_.question_refusal(cfg4)))
        say("B4 M5: under statements-only the human's re-approval of a repaired statement is refused until the "
            "sheet's fresh-reader check passes; then it closes",
            rc_r == 1 and "fresh-reader" in o_r and rc_ok == 0 and json.load(open(os.path.join(P3, fp.REAPPROVAL)))["closed"])
    finally:
        (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
         globals()["build_bundle"], globals()["check"], globals()["REFUTATION_FACTS"]) = keep
        globals()["REAPPROVAL_READER_GATE"] = reapproval_reader_gate


def selftest_b2_recheck(d, say):
    """The B2 re-check findings (build/B2.md "Re-check fixes"): (a) closeM, (b) amend, (c) the answer."""
    import io, contextlib
    import fingerprint as fp, decisions as dc_
    keep = (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
            globals()["build_bundle"], globals()["check"])
    try:
        # (a) closeM: a close committed by hand as "approve R", writing a new approval (M, not moved aside) by
        # the agent under statements-only: the approve gate would have refused it, so it is no close
        for by_, tag_ in (("agent", "closeM"), ("human", "closeM-h")):
            P, cfg, G, appr = _b2_scenario(d, tag_, "statements-only", "- 5d: human Jane Doe\n")
            r_ = json.load(open(os.path.join(P, fp.REAPPROVAL)))
            r_.update(closed=True, closed_by="approve R", closed_date="2026-10-22")
            json.dump(r_, open(os.path.join(P, fp.REAPPROVAL), "w"), indent=1)
            json.dump({"commit": "c1", "date": "2026-10-22", "by": by_, "fingerprints": {"N.main": "a2", "N.b": "b"}},
                      open(os.path.join(P, fp.APPROVED), "w"))
            G("add", "-A"); G("commit", "-qm", "approve R")
            say(f"B2 re-check (a): a hand-made close \"approve R\" whose new approval is by the {by_} "
                + ("(statements-only: the agent may not re-approve)" if by_ == "agent"
                   else "(no human answer in that commit's RUN_LOG.md)")
                + " is no close: the record is untrusted and the re-approval OPEN",
                fp.open_reapproval(P, project.REPO, cfg)[1] and fp.open_reapproval_problem(P, cfg)
                and not fp.reapprovals(P, cfg)[-1].get("closed"))
        # (a) a close by hand that writes no new approval (the record marked closed, the answer logged) is no close
        P, cfg, G, appr = _b2_scenario(d, "closeM-noappr", "statements-only", "- 5d: human Jane Doe\n")
        r_ = json.load(open(os.path.join(P, fp.REAPPROVAL)))
        r_.update(closed=True, closed_by="approve R", closed_date="2026-10-22")
        json.dump(r_, open(os.path.join(P, fp.REAPPROVAL), "w"), indent=1)
        project.log_append(cfg, "Re-approvals", '- human answer (round R; N.main): "yes"')
        G("add", "-A"); G("commit", "-qm", "approve R")
        say("B2 re-check (a): a hand-made close \"approve R\" that writes no new approval is no close, even with "
            "the human's answer logged", fp.open_reapproval(P, project.REPO, cfg)[1]
            and not fp.reapprovals(P, cfg)[-1].get("closed"))
        # (a) the genuine close by the agent where it may (hands-off, its own approval) stays a close
        P, cfg, G, appr = _b2_scenario(d, "closeM-ok", "hands-off", "", by="agent")
        rc, out = appr("agent")
        say("B2 re-check (a): a genuine close (hands-off, the agent's own approval) is a close",
            rc == 0 and fp.open_reapproval(P, project.REPO, cfg) == (None, None)
            and fp.open_reapproval_problem(P, cfg) is None)
        # (b) amend: the approval file edited to `by: agent` by hand and committed in a begin-looking commit
        # with the record (involved, 5d agent): the replaced approval is the one signoff wrote (human), so
        # approve --by agent is refused
        P, cfg, G, appr = _b2_scenario(d, "amend", "involved", "- 5d: agent\n")
        a_ = json.load(open(os.path.join(P, fp.APPROVED))); a_["by"] = "agent"
        json.dump(a_, open(os.path.join(P, fp.APPROVED), "w"))
        r_ = json.load(open(os.path.join(P, fp.REAPPROVAL)))
        json.dump(r_, open(os.path.join(P, fp.REAPPROVAL), "w"), indent=2)
        G("add", "-A"); G("commit", "-qm", fp.REAPPROVAL_BEGIN + ": lemma false)")
        rc, out = appr("agent")
        say("B2 re-check (b): an approval edited by hand and committed (in a begin-looking commit) is not the "
            "replaced approval: approve --by agent over a human's approval refused, the question open",
            rc == 1 and "PENDING[question]" in out and fp.replaced_approval(P, cfg).get("by") == "human"
            and dc_.reapproval_question(cfg) is not None)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                reapprove_begin(cfg, ["N.b"], "more", fps={"N.main": "a2", "N.b": "b"})
            berr = ""
        except ValueError as e:
            berr = str(e)
        say("B2 re-check (b): reapprove --begin refuses an approval file edited by hand since signoff wrote it",
            "edited by hand" in berr)
        # (c) an answer logged BEFORE the begin (and a suffix name) is not the human's answer to this question
        P, cfg, G, appr = _b2_scenario(d, "early", "statements-only",
                                       '- 5d: human Jane Doe\n## Re-approvals\n- human answer (round R; N.main): "yes"\n')
        rc0, out0 = appr("human")
        project.log_append(cfg, "Re-approvals", '- human answer (round R; main): "yes, the weakened lemma"')
        G("add", "P/RUN_LOG.md"); G("commit", "-qm", "log the answer (suffix)")
        rc1, out1 = appr("human")
        project.log_append(cfg, "Re-approvals", '- human answer (round R; N.main): "yes, the weakened lemma"')
        G("add", "P/RUN_LOG.md"); G("commit", "-qm", "log the answer")
        rc2, out2 = appr("human")
        say("B2 re-check (c): approve --by human refuses an answer committed before the begin and one naming a "
            "suffix (`main`), accepts the full name logged after the begin",
            rc0 == 1 and "PENDING[question]" in out0 and rc1 == 1 and rc2 == 0
            and fp.open_reapproval_problem(P, cfg) is None)
    finally:
        (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
         globals()["build_bundle"], globals()["check"]) = keep
        globals()["REAPPROVAL_READER_GATE"] = reapproval_reader_gate



def selftest_b13_interrupted(d, say):
    """B13 (U2 §8, restarts): an `approve` killed between writing its files and committing them. Resumed with
    the same answer it commits the approval it recomputes; with another answer (or a file cut short) the
    interrupted files are discarded, never committed, and the next approve (after the human is asked again)
    goes through. Nothing loops: each re-run either commits or leaves the committed state clean."""
    import fingerprint as fp
    keep = (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
            globals()["build_bundle"], globals()["check"], project.commit_only)
    real_commit = project.commit_only

    def killed(*a_, **k_):
        raise KeyboardInterrupt("killed before the commit")
    try:
        for tag, how2, cut in (("same", "blanket", False), ("other", "individual", False), ("cut", "blanket", True)):
            P, cfg, G, appr = _b2_scenario(d, "kill-" + tag, "hands-off", "", by="agent")
            head0 = G("rev-parse", "HEAD")
            project.commit_only = killed
            try:
                appr("agent"); died = False
            except KeyboardInterrupt:
                died = True
            finally:
                project.commit_only = real_commit
            dirty = G("status", "--porcelain")
            if cut:
                open(os.path.join(P, fp.APPROVED), "w").write('{"round": "R", "by": "ag')
            import io, contextlib
            o = io.StringIO()
            with contextlib.redirect_stdout(o), contextlib.redirect_stderr(o):
                rc = main(["approve", "--round", "R", "--how", how2, "--by", "agent"])
            out = o.getvalue()
            subj = G("log", "-1", "--format=%s")
            if tag == "same":
                say("B13 kill point (approve): resumed with the same answer, the interrupted approval equals the "
                    "recomputed one and is committed as `approve R` (re-approval closed, tree clean)",
                    died and "APPROVED_FINGERPRINTS.json" in dirty and rc == 0 and subj == "approve R"
                    and G("status", "--porcelain") == "" and json.load(open(os.path.join(P, fp.REAPPROVAL))).get("closed")
                    and "restored to the committed state" in out)
            else:
                still = G("rev-parse", "HEAD") == head0 and G("status", "--porcelain") == ""
                again, out2 = appr("agent")
                say(f"B13 kill point (approve, {'another answer' if tag == 'other' else 'file cut short'}): the "
                    "interrupted files are discarded, never committed (FAIL[uncommitted-record], committed state "
                    "restored); approved once the human is asked again",
                    died and rc == 1 and "FAIL[uncommitted-record]" in out and "discarded" in out
                    and subj != "approve R" and still and again == 0
                    and G("log", "-1", "--format=%s") == "approve R" and G("status", "--porcelain") == "")
    finally:
        (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
         globals()["build_bundle"], globals()["check"], project.commit_only) = keep
        globals()["REAPPROVAL_READER_GATE"] = reapproval_reader_gate


def selftest_b2_round3(d, say):
    """B2 round 3 (build/B2.md "Round 3"): ONE invariant -- every commit of the full history that changes
    APPROVED_FINGERPRINTS.json passes the approve gate as it applied at that commit, or it is a record problem;
    a merge bringing the records from another branch is a record problem (build/rc-att/a.py)."""
    import io, contextlib
    import fingerprint as fp, make_report as mr_
    keep = (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
            globals()["build_bundle"], globals()["check"])

    def rp(P, cfg):
        with contextlib.redirect_stdout(io.StringIO()):
            return [str(x) for x in mr_.record_problems(P, cfg=cfg)]
    try:
        # merge: involved, 5d agent, the human approved R0; a side branch's forged agent approval merged in
        P, cfg, G, appr = _b2_scenario(d, "r3-merge", "involved", "- 5d: agent\n", by="human")
        G("reset", "-q", "--hard", "HEAD~2")
        main_ = G("rev-parse", "--abbrev-ref", "HEAD")
        G("checkout", "-q", "-b", "side", "HEAD~1")
        json.dump({"commit": "c0", "date": "2026-01-01", "by": "agent", "fingerprints": {"N.main": "a", "N.b": "b"}},
                  open(os.path.join(P, fp.APPROVED), "w"))
        G("add", "-A"); G("commit", "-qm", "approve R0")
        G("checkout", "-q", main_)
        G("merge", "-q", "--no-ff", "-X", "theirs", "side", "-m", "approve R0 (merge)")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                reapprove_begin(cfg, ["N.main"], "lemma false", fps={"N.main": "a", "N.b": "b"})
            berr = ""
        except ValueError as e:
            berr = str(e)
        say("B2 round 3: a merge bringing a forged agent approval from a side branch is a record problem, the "
            "approval counted is the human's on the run's own line, and reapprove --begin refuses the merged file",
            any("merge commit" in x for x in rp(P, cfg)) and [a_.get("by") for _, a_ in fp.genuine_approvals(P, cfg)]
            == ["human"] and "edited by hand" in berr)
        # stealth: no re-approval at all, a hand-made "approve R" over the existing approval (by the human, or
        # by the agent over its own approval where it may re-approve): undisclosed re-approvals
        for lvl_, five_, by0, by1 in (("statements-only", "- 5d: human Jane Doe\n", "human", "human"),
                                      ("involved", "- 5d: agent\n", "agent", "agent"),
                                      ("involved", "- 5d: human Jane Doe\n", "human", "agent")):
            P, cfg, G, appr = _b2_scenario(d, f"r3-st-{lvl_}-{by0}{by1}", lvl_, five_, by=by0)
            G("reset", "-q", "--hard", "HEAD~2")
            json.dump({"commit": "c1", "date": "2026-10-22", "by": by1, "round": "R",
                       "fingerprints": {"N.main": "a2", "N.b": "b"}}, open(os.path.join(P, fp.APPROVED), "w"))
            G("add", "-A"); G("commit", "-qm", "approve R")
            say(f"B2 round 3: a hand-made \"approve R\" by the {by1} over the {by0}'s approval with no re-approval "
                f"open ({lvl_}) is a record problem and not an approval",
                any("without passing the approve gate" in x and "N.main" in x for x in rp(P, cfg))
                and len(fp.genuine_approvals(P, cfg)) == 1)
        # an agent approval adding only NEW declarations but over a human's approval: the gate's agent rule
        P, cfg, G, appr = _b2_scenario(d, "r3-st-new", "involved", "- 5d: agent\n", by="human")
        G("reset", "-q", "--hard", "HEAD~2")
        json.dump({"commit": "c1", "date": "2026-10-22", "by": "agent", "round": "R",
                   "fingerprints": {"N.main": "a", "N.b": "b", "N.c": "c"}}, open(os.path.join(P, fp.APPROVED), "w"))
        G("add", "-A"); G("commit", "-qm", "approve R")
        say("B2 round 3: a hand-made agent approval over a human's (only a new declaration added) is a record problem",
            any("without passing the approve gate" in x for x in rp(P, cfg)))
        # rmrecords: the approval moved aside by a commit of its own is a record problem
        P, cfg, G, appr = _b2_scenario(d, "r3-rm", "statements-only", "- 5d: human Jane Doe\n")
        G("rm", "-q", "P/" + fp.REAPPROVAL); G("mv", "P/" + fp.APPROVED, "P/APPROVED_FINGERPRINTS.2026-01-01.json")
        G("commit", "-qm", "approve R (tidy)")
        say("B2 round 3: a commit moving the approval aside is a record problem",
            any("deletes or moves" in x for x in rp(P, cfg)))
        # an approval without `by`: legacy (by: human) only when written and committed before the field existed
        leg = []
        # forgery review M1: and only in a run whose FIRST committed pin is of ownership 1 and older than the field
        # ("forged": an old-dated approval, its commit backdated, in a run pinned under ownership 2 on 2026-10-21)
        for tag_, date_, cdate_, pin_ in (("old", "2026-10-12", "2026-10-12T12:00:00", {"date": "2026-10-10"}),
                                          ("new", "2026-10-22", "2026-10-22T12:00:00", {"date": "2026-10-10"}),
                                          ("oldcopied", "2026-10-12", "2026-10-22T12:00:00", {"date": "2026-10-10"}),
                                          ("forged", "2026-10-12", "2026-10-12T12:00:00",
                                           {"date": "2026-10-21", "ownership": 2}),
                                          ("newdoc", "2026-10-22", "2026-10-12T12:00:00", {"date": "2026-10-10"})):
            P, cfg, G, appr = _b2_scenario(d, f"r3-legacy-{tag_}", "statements-only", "- 5d: human Jane Doe\n")
            G("reset", "-q", "--hard", "HEAD~3")
            json.dump(dict(pin_, audits_commit="x", config={}), open(os.path.join(P, "TOOLING_PIN.json"), "w"))
            G("add", "-A"); G("commit", "-qm", "pin")
            json.dump({"round": "R0", "commit": "c0", "date": date_, "how": "blanket",
                       "fingerprints": {"N.main": "a", "N.b": "b"}}, open(os.path.join(P, fp.APPROVED), "w"))
            G("add", "-A")
            subprocess.run(["git", "-C", os.path.dirname(P), "commit", "-qm", "approve R0"], capture_output=True,
                           env=dict(os.environ, GIT_COMMITTER_DATE=cdate_, GIT_AUTHOR_DATE=cdate_))
            leg.append((not any("is not an approval" in x for x in rp(P, cfg)),
                        project.approval_file_by(os.path.join(P, fp.APPROVED))))
        say("B3 re-check: an approval with no `by` committed before the field existed is legacy (by: human, "
            "disclosed); a newer one (or an old one committed later) stays a record problem",
            leg == [(True, ("human", True))] + [(False, (None, False))] * 4
            and project.approval_by({"date": "2026-10-12", "by": None}) == (None, False)
            and project.approval_by({"date": "2026-10-22"}) == (None, False)
            # no run to judge it by: never legacy (forgery review M1)
            and project.approval_by({"date": "2026-10-12"}) == (None, False))
        # legit flows: human under statements-only, agent under involved with 5d agent, hands-off (agent and
        # human): no record problem, the re-approval closed and disclosed
        res = []
        for lvl_, five_, by0 in (("statements-only", "- 5d: human Jane Doe\n", "human"),
                                 ("involved", "- 5d: agent\n", "agent"), ("hands-off", "", "agent"),
                                 ("hands-off", "", "human")):
            P, cfg, G, appr = _b2_scenario(d, f"r3-ok-{lvl_}-{by0}", lvl_, five_, by=by0)
            if by0 == "human":
                project.log_append(cfg, "Re-approvals", '- human answer (round R; N.main): "yes"')
                G("add", "P/RUN_LOG.md"); G("commit", "-qm", "log the answer")
            rc, out = appr(by0)
            cyc = fp.reapprovals(P, cfg)
            res.append(rc == 0 and rp(P, cfg) == [] and len(fp.genuine_approvals(P, cfg)) == 2
                       and [c_.get("closed") for c_ in cyc] == [True] and cyc[0].get("decls") == ["N.main"])
        say("B2 round 3: the legit re-approvals (statements-only human, involved 5d agent, hands-off agent and human) "
            "pass with no record problem, each closed and listed by reapprovals()", all(res) and len(res) == 4)
    finally:
        (project.REPO, project.select, fp.compute, globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"],
         globals()["build_bundle"], globals()["check"]) = keep
        globals()["REAPPROVAL_READER_GATE"] = reapproval_reader_gate


def selftest():
    import tempfile, shutil
    import make_report as mr
    ok = True

    def say(name, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
        ok &= bool(cond)

    # the round dir gets its own parent: SIGNOFF's render files go to <parent>/render/, which must
    # not be a shared /tmp/render (another user's run there made the install check fail)
    d = os.path.join(tempfile.mkdtemp(prefix="sgt-"), "round")
    os.makedirs(d)
    # approve's PDF guard (render_record.check) is stubbed to pass except where a check below exercises it:
    # render_record.py --selftest holds the fingerprint itself
    _guard0 = (RENDER_GUARD, RENDER_SHOWN)
    globals()["RENDER_GUARD"] = lambda c_, r_: []
    globals()["RENDER_SHOWN"] = lambda c_, r_: ({"pdf_sha256": "0" * 64, "outcome": "verified"}, [])
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
        te_ = theorem_entry("K.cor (n : ℕ) : K.Q ⊤",
                            "/-- doc -/\ntheorem cor (n : ℕ) (h : P := by simp) :\n    Q (⊤ : Set (Fin (n + 1))) := by\n  simp")
        say("mini1: a theorem's bundle entry gives its statement as written (the ascription the elaborated "
            "signature drops), up to the proof, a binder's `:=` kept",
            "-- statement (source):" in te_ and any("(⊤ : Set (Fin (n + 1)))" in l and l.rstrip().endswith("(n + 1)))")
                                                   for l in te_) and any("(h : P := by simp)" in l for l in te_)
            and not any("doc" in l or l.strip() == "simp" for l in te_))
        # review of fix-mini1 (L1): a `let`/`haveI` in the statement or match alternatives: unsure,
        # so the elaborated signature only (a source "statement" cut at the let's `:=` misled)
        uns_ = {k: statement_source(v) for k, v in (
            ("let", "theorem t : let n := 5; n = 5 := rfl"),
            ("haveI", "theorem t : haveI := Classical.dec; True := trivial"),
            ("match", "theorem t : ∀ n : ℕ, n + 0 = n\n  | 0 => rfl\n  | n + 1 => rfl"))}
        say(f"review L1: a let/haveI statement or match alternatives give no source statement ({uns_})",
            all(v == "" for v in uns_.values()) and "-- statement (source):" not in theorem_entry(
                "t : True", "theorem t : haveI := Classical.dec; True := trivial")
            and statement_source("theorem t (x : ℕ) (hx : complete x) : outlet x := rfl") ==
            "theorem t (x : ℕ) (hx : complete x) : outlet x")
        # a result named in PAPER_DEFECTS.md must not be shown as "Differences: None"
        rr = os.path.join(d, "rounds-pd"); rd2 = os.path.join(rr, "R"); os.makedirs(rd2)
        json.dump(good_inf, open(os.path.join(rd2, "INFORMAL.json"), "w"))
        so2 = {"commit": "abc", "rows": [row("Theorem 1.1", "For all n, f(n) > n."),
                                        row("Lemma 1.2", "Two is even.", "CHECK",
                                            check_reason="parity convention")]}
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        open(os.path.join(rr, "PAPER_DEFECTS.md"), "w").write(
            "| # | where | status | repair |\n|---|---|---|---|\n| 1 | tex 3, Theorem 1.1 | false | substantial |\n"
            "| 2 | Lemma 1.20 (not on the sheet) | misprint (true as intended) | typo |\n")
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
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n"
            "| 1 | Lemma 7.4 (c) | the hypothesis is never met | |\n")
        say("a VACUOUS.md row naming one part keeps the part (a multi-part lemma's (a)-(c))",
            vacuous_results(rr) == ["Lemma 7.4 (c)"])
        say("a record naming several parts in words gives one label per part, never the whole result "
            "(release-mode re-check r2)",
            ref_labels("Lemma 7.4 part (a) and part (c)") == ["Lemma 7.4 (a)", "Lemma 7.4 (c)"]
            and ref_labels("Lemma 7.4 (a), (c)") == ["Lemma 7.4 (a)", "Lemma 7.4 (c)"]
            and ref_labels("Theorem 6.1 and Lemma 7.4(b)") == ["Theorem 6.1", "Lemma 7.4 (b)"]
            and ref_labels("Lemma 7.4 (a corollary)") == ["Lemma 7.4"])
        say("a part label matches only that part; a whole label matches every part",
            label_matches("Lemma 7.4 (c)", "Lemma 7.4(c)") and label_matches("Lemma 7.4 (c)", "Lemma 7.4 (c)")
            and not label_matches("Lemma 7.4 (c)", "Lemma 7.4 (a)") and label_matches("Lemma 7.4", "Lemma 7.4 (b)")
            and not label_matches("Lemma 7.4", "Lemma 7.41") and not label_matches("Lemma 7.4", "Lemma 7.4.1"))
        # release mode (S2-like): a record whose label lost its part ("Lemma 7.4 part (c)" reads as
        # "Lemma 7.4") demands CHECK on every part; with (c) CHECK, the others are disclosed (label)
        # in release and block in dev; with no CHECK row at all they block in both
        so3 = json.loads(json.dumps(so2))
        so3["rows"] += [row("Lemma 7.4 (a)", "x", "OK"), row("Lemma 7.4 (c)", "y", "CHECK", check_reason="vacuous")]
        # review M1 (a2's case): the whole result recorded as vacuous; one part CHECK for another reason
        so4 = json.loads(json.dumps(so3)); so4["rows"][-1]["check_reason"] = "S4 defect in the bound"
        json.dump(so4, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n| 1 | Lemma 7.4 | never met | |\n")
        m1 = [p for p in check(cfg, rd2, rows, defs) if "vacuously" in p]
        say("review M1: a wholly vacuous result is not covered by one part's CHECK, nor by a CHECK for another reason",
            len(m1) == 1 and project.split(dict(cfg, mode="release"), m1)[1] == [])
        json.dump(so3, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        m1 = [p for p in check(cfg, rd2, rows, defs) if "vacuously" in p]
        say("review M1: a wholly vacuous result: one part CHECK for the vacuity does not cover the other parts",
            len(m1) == 1 and project.split(dict(cfg, mode="release"), m1)[1] == [])
        json.dump(so4, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n| 1 | Lemma 7.4 part (c) | never met | |\n")
        m1 = [p for p in check(cfg, rd2, rows, defs) if "vacuously" in p]
        say("a part named in words (\"Lemma 7.4 part (c)\") concerns that part only: (a) is not required to be "
            "CHECK (re-check r2: the parser keeps parts named in words)",
            m1 == [])
        json.dump(so3, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n| 1 | Lemma 7.4 part (c) | never met | |\n")
        vc = lambda: [p for p in check(cfg, rd2, rows, defs) if "vacuously" in p]
        rel, dev = dict(cfg, mode="release"), dict(cfg, mode="dev")
        say("a record about part (c) in words, with (c) CHECK: no other part is flagged, in either mode",
            vc() == [])
        so3["rows"][-1]["flag"] = "OK"
        json.dump(so3, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        say("release: the vacuous part named in words, flagged OK, blocks in both modes (faithfulness)",
            len(vc()) == 1 and "Lemma 7.4 (c)" in vc()[0] and project.split(rel, vc())[1] == []
            and project.split(dev, vc())[1] == [])
        # a part the parser still loses ("Lemma 7.4 – (c)": a dash, not a list separator): release's
        # label rule discloses the other parts only when (c)'s CHECK is for this very record
        so3["rows"][-1]["flag"] = "CHECK"
        open(os.path.join(rr, "VACUOUS.md"), "w").write(
            "| # | statement | why | status |\n|---|---|---|---|\n| 1 | Lemma 7.4 – (c) | never met | |\n")
        json.dump(so3, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        say("release: a part lost by the parser, its CHECK row on the sheet: the other part is disclosed "
            "(label); dev: it blocks",
            len(vc()) == 1 and project.split(rel, vc()) == ([], vc()) and project.split(dev, vc())[0] == vc()
            and vc()[0].code == "label")
        json.dump(so4, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
        say("review M1: ...a CHECK given for another reason does not cover a part lost by the parser",
            len(vc()) == 1 and project.split(rel, vc())[1] == [])
        json.dump(so2, open(os.path.join(rd2, "SIGNOFF.json"), "w"))
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
        # PDF-AGENTS: render writes SIGNOFF.md only (its PDF is made by agents, render_record.py)
        made = lambda: os.path.exists(os.path.join(d, "SIGNOFF.md"))
        setup(good_inf, good_so)
        setup(dict(good_inf, definitions=[]), good_so)
        say("render writes the sheet when there are no separate definitions", render(cfg, d) and made())
        # trial #7 audit (also #4, #6): the .md carries the Lean statements
        open(os.path.join(d, "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write(
            "# Statements bundle\n\n## Theorem 1.1\n```lean\n-- signature (elaborated):\nN.thm_q (n : ℕ) : f n > n\n"
            "-- statement (source):\ntheorem thm_q (n : ℕ) : f n > n\n```\n")
        try:
            okq = render(cfg, d)
            mdq = open(os.path.join(d, "SIGNOFF.md"), encoding="utf-8").read()
        finally:
            os.remove(os.path.join(d, "STATEMENTS_BUNDLE.md"))
        say("trial #7: SIGNOFF.md shows each result's Lean statement (signature and source) from the bundle, and "
            "says there are no separate definitions",
            okq and "`N.thm_q (n : ℕ) : f n > n`" in mdq and "`theorem thm_q (n : ℕ) : f n > n`" in mdq
            and NO_DEFS in mdq and APPROVING[1] in mdq)
        so_m = dict(good_so, rows=[dict(good_so["rows"][0], paper="For $k\\ge 1$ the set $\\mathbb{N}$"),
                                   good_so["rows"][1]])
        setup(good_inf, so_m)
        okm = render(cfg, d)
        say("PDF-AGENTS: the paper's statement reaches SIGNOFF.md as its LaTeX source, verbatim (the renderer typesets "
            "it), and no .tex or PDF is written",
            okm and "**Paper.** For $k\\ge 1$ the set $\\mathbb{N}$" in open(os.path.join(d, "SIGNOFF.md")).read()
            and not any(os.path.exists(os.path.join(d, "SIGNOFF" + x)) for x in (".tex", ".pdf")))
        setup(good_inf, good_so)
        say("render writes SIGNOFF.md", render(cfg, d) and made()
            and "[ ] Lemma 1.2" in open(os.path.join(d, "SIGNOFF.md")).read())
        say("an involved-level sheet does not carry the hands-off line",
            HANDS_OFF_LINE not in open(os.path.join(d, "SIGNOFF.md")).read())
        okh = render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d)
        say("under hands-off SIGNOFF.md OPENS with 'To be approved by the formalizing agent; no person will review ...' "
            "before the approval (mini5 audit: it said 'Approved' before the approval existed)",
            okh and open(os.path.join(d, "SIGNOFF.md")).read().split("\n\n")[0] == f"**{HANDS_OFF_PENDING}**")
        mdh = open(os.path.join(d, "SIGNOFF.md")).read()
        import readers as _rd
        _hsrc = [os.path.join(d, "SIGNOFF.md")]
        _h_pre = _rd.content_hash(_hsrc, "signoff")
        _apf = os.path.join(os.path.dirname(os.path.abspath(d)), "APPROVED_FINGERPRINTS.json")
        _had_ap = open(_apf).read() if os.path.exists(_apf) else None
        json.dump({"round": os.path.basename(os.path.abspath(d))}, open(_apf, "w"))
        try:
            render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d)
            mda = open(os.path.join(d, "SIGNOFF.md")).read()
            _h_post = _rd.content_hash(_hsrc, "signoff")
        finally:
            if _had_ap is None:
                os.remove(_apf)
            else:
                open(_apf, "w").write(_had_ap)
            render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d)
        # B4 (M5): a hands-off re-approval's sheet (a result CHANGED) says K re-approved, before and after the
        # approval, and the reader's hash is the same for the two
        _ch = {"Theorem 1.1": "2026-01-01"}
        render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d, _ch)
        _mdc_pre, _hc_pre = open(os.path.join(d, "SIGNOFF.md")).read(), _rd.content_hash(_hsrc, "signoff")
        json.dump({"round": os.path.basename(os.path.abspath(d))}, open(_apf, "w"))
        try:
            render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d, _ch)
            _mdc = open(os.path.join(d, "SIGNOFF.md")).read()
            _hc_post = _rd.content_hash(_hsrc, "signoff")
        finally:
            if _had_ap is None:
                os.remove(_apf)
            else:
                open(_apf, "w").write(_had_ap)
            render(dict(cfg, involvement="hands-off", involvement_answer="(c)"), d)
        say("B4 M5: a hands-off re-approval sheet opens with 'Statements unchanged since the latest approval; 1 "
            "re-approved by the agent, marked CHANGED.' after its approval ('awaiting' before); the "
            "reader's hash is the same before and after",
            _mdc.split("\n\n")[0] == f"**{hands_off_line(True, 1)}**"
            and _mdc_pre.split("\n\n")[0] == f"**{hands_off_line(False, 1)}**" and _hc_pre == _hc_post)
        say("mini5 audit: approval wording only after the approval: the approved sheet opens with 'Approved by the "
            "formalizing agent', its background says the agent approved it; before, neither (and the reader gate's "
            "hash of the sheet is the same, so a re-render after the approval keeps the reader's pass)",
            mda.split("\n\n")[0] == f"**{HANDS_OFF_LINE}**" and APPROVAL_STAMPS[1][0] in mda
            and HANDS_OFF_LINE not in mdh and APPROVAL_STAMPS[1][0] not in mdh
            and "approved this sheet" not in mdh and "when it was approved" not in mdh
            and APPROVAL_STAMPS[1][1] in mdh and _h_pre == _h_post)
        say("review 2 N8: at a re-approval (not a statement round) the background does not claim every proof is sorry",
            "sorry` by design" in sheet_background(cfg, {"commit": "x"}, "statements")
            and "statement-stage sheet" in sheet_background(cfg, {"commit": "x"}, "statements")
            and "sorry` by design" not in sheet_background(cfg, {"commit": "x"}, "full")
            and "re-approval" in sheet_background(cfg, {"commit": "x"}, "full"))
        say("the sheet has its own background: what it is, who approves under the level (intake answer quoted), "
            "what an unticked box triggers, and a legend of OK/GLOBAL/CHECK and junk values",
            "**What this sheet is.**" in mdh and "answer, verbatim: \"(c)\"" in mdh and "unticked" in mdh
            and "**How to read a result.**" in mdh and "**Junk values:**" in mdh and "CHECK:" in mdh)
        bgh_ = sheet_background(dict(cfg, involvement="hands-off", involvement_answer="(c)", branch="BRQZ",
                                     build_cmds=["lake build QZ"]), {"commit": "x"})
        say("mini1: the sheet gives the repository, branch and build command, defines its terms, says "
            "DECISIONS.md is delivered with it, and says what it is before what approving it means",
            f"repository `{project.REPO}`, branch `BRQZ`" in bgh_ and "`lake build QZ` exits 0" in bgh_
            and "**Terms.**" in bgh_ and "*Phase 0*" in bgh_ and "delivered with this sheet" in bgh_
            and 0 <= mdh.find("**What this sheet is.**") < mdh.find("**Approving this sheet means"))
        # paper line numbers from the .tex and its .aux; Lean locations from the project's files
        tex_ = os.path.join(d, "paper.tex")
        open(tex_, "w").write("\\documentclass{article}\n\\begin{document}\nx\n\\begin{theorem}\\label{thm:main}\n"
                              "For all n.\n\\end{theorem}\n\\begin{lemma}\nTwo is even.\\label{lem:two}\n\\end{lemma}\n\\end{document}\n")
        open(os.path.join(d, "paper.aux"), "w").write("\\newlabel{thm:main}{{1.1}{1}}\n\\newlabel{thm:main@cref}{{[theorem][1][1]1.1}{[1][1][1]1}}\n"
                                                      "\\newlabel{lem:two}{{1.2}{1}}\n\\newlabel{lem:two@cref}{{[lemma][2][1]1.2}{[1][1][1]1}}\n")
        os.makedirs(os.path.join(d, "L")); open(os.path.join(d, "L", "A.lean"), "w").write("namespace N\n\ntheorem x : True := trivial\n")
        # trial #7 audit: the Lean lines are those of the sheet's commit, not of the working tree
        _gq = lambda *a_: subprocess.run(["git", "-C", d, *a_], capture_output=True, text=True).stdout.strip()
        _gq("init", "-q"); _gq("add", "L/A.lean")
        _gq("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "lean")
        _so_l = json.load(open(os.path.join(d, "SIGNOFF.json")))
        # trial #10: the writer's entry in code spans, a second name in words around it
        _rows_bt = [dict(r_, lean="`N.x` (uses `N.x`)") if r_.get("lean") in (["N.x"], "N.x") and not k_ else r_
                    for k_, r_ in enumerate(_so_l.get("rows", []))]
        json.dump(dict(_so_l, commit=_gq("rev-parse", "--short=11", "HEAD"), rows=_rows_bt),
                  open(os.path.join(d, "SIGNOFF.json"), "w"))
        open(os.path.join(d, "L", "A.lean"), "w").write("namespace N\n\n-- later\n-- edits\ntheorem x : True := trivial\n")
        _kr = project.REPO
        try:
            project.REPO = d
            mr.REPO, _krm = d, mr.REPO
            render(dict(cfg, source_pdf=tex_, lean_files=["L/A.lean"]), d)
            mr.REPO = _krm
        finally:
            project.REPO = _kr
        mdl = open(os.path.join(d, "SIGNOFF.md")).read()
        json.dump(_so_l, open(os.path.join(d, "SIGNOFF.json"), "w"))
        shutil.rmtree(os.path.join(d, ".git"))
        say("each result cites its paper line (tex l.N, from the .aux) and each Lean name its File.lean:N, the line "
            "of the sheet's commit (a later edit in the working tree moves nothing; trial #7 audit)",
            "**Paper.** (tex l.4) " in mdl and "**Paper.** (tex l.7) " in mdl and "`N.x` (L/A.lean:3)" in mdl
            and "A.lean:5" not in mdl)
        say("trial #10: a Lean entry written in code spans is located name by name, its words kept, no doubled "
            "backticks", "**Lean.** `N.x` (L/A.lean:3) (uses `N.x` (L/A.lean:3))" in mdl and "``" not in mdl)
        # mini1: no cleveref -- the kind comes from the \newtheorem the \label sits in
        d2 = os.path.join(d, "nocref"); os.makedirs(d2)
        open(os.path.join(d2, "p.tex"), "w").write(
            "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}[section]\n\\newtheorem{lem}[theorem]{Lemma}\n"
            "\\begin{document}\n\\begin{lem}\\label{lem:a}\nx\n\\begin{enumerate}\n\\item y\\label{it:b}\n"
            "\\end{enumerate}\n\\end{lem}\n\\end{document}\n")
        open(os.path.join(d2, "p.aux"), "w").write("\\newlabel{lem:a}{{7.4}{1}}\n\\newlabel{it:b}{{(b)}{1}}\n")
        pl_ = paper_lines({"source_pdf": os.path.join(d2, "p.tex")})
        say("mini1: without cleveref a result's paper line comes from its \\newtheorem environment (an "
            "enumerate label gives none)", pl_ == {"lemma 7.4": 5})
        say("a test run: a part ('Lemma 7.4 (b)') without a label of its own cites its result's line",
            paper_line(pl_, "Lemma 7.4 (b)") == 5 and paper_line(pl_, "Lemma 7.5") is None)
        # review of fix-mini1 (M3): a \label outside the theorem environment (a section's, an
        # equation's) never lends its number to the environment above it; a kind mismatch gives no line
        d3 = os.path.join(d, "nocref2"); os.makedirs(d3)
        open(os.path.join(d3, "p.tex"), "w").write(
            "\\documentclass{article}\n\\newtheorem{lemma}{Lemma}\n\\begin{document}\n"     # 1-3
            "\\section{One}\n"                                                                  # 4
            "\\begin{lemma}\\label{lem:a}\nFirst \\begin{equation}x\\label{eq:3}\\end{equation}\n\\end{lemma}\n"  # 5-7
            "\\section{Two}\\label{sec:two}\n"                                                  # 8
            "Text.\n"                                                                           # 9
            "\\begin{lemma}\\label{lem:b}\nSecond.\nlemma.\n"                                    # 10-12
            "\\end{lemma}\n\\section{Three}\\label{sec:three}\n"                                 # 13-14
            "% \\begin{lemma}\\label{lem:old}\n\\end{document}\n")                                 # 15-16
        open(os.path.join(d3, "p.aux"), "w").write(
            "\\newlabel{lem:a}{{1}{1}}\n\\newlabel{sec:two}{{2}{1}}\n\\newlabel{lem:b}{{2}{1}}\n"
            "\\newlabel{eq:3}{{3}{1}}\n\\newlabel{lem:old}{{3}{1}}\n\\newlabel{sec:three}{{4}{1}}\n")
        pl3_ = paper_lines({"source_pdf": os.path.join(d3, "p.tex")})
        say("review M3: a section's or an equation's \\label after a lemma gives no wrong lemma line "
            f"({pl3_})", pl3_ == {"lemma 1": 5, "lemma 2": 10})
        open(os.path.join(d3, "p.aux"), "w").write(
            "\\newlabel{lem:a}{{1}{1}}\n\\newlabel{lem:a@cref}{{[theorem][1][]1}{[1][1][]1}}\n"
            "\\newlabel{lem:b}{{2}{1}}\n\\newlabel{lem:b@cref}{{[lemma][2][]2}{[1][1][]1}}\n")
        pl4_ = paper_lines({"source_pdf": os.path.join(d3, "p.tex")})
        say("review M3: a cleveref kind that is not the environment's own gives no line", pl4_ == {"lemma 2": 10})
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
        so_c = dict(so_g, rows=[dict(so_g["rows"][0], cited="cited from [GKP, (6.108)]; proved here"),
                                so_g["rows"][1]])
        ok_c = setup(good_inf, so_c) == [] and render(cfg, d)
        md_c = open(os.path.join(d, "SIGNOFF.md")).read()
        bad_c = setup(good_inf, dict(so_c, rows=[dict(so_c["rows"][0], cited=["GKP"]), so_c["rows"][1]]))
        setup(good_inf, so_g)
        say("mini4/mini5 audits: a cited result's status is shown on its row even when the row is GLOBAL; a "
            "non-string `cited` fails",
            ok_c and "**Cited result.** cited from [GKP, (6.108)]; proved here" in md_c
            and md_c.index("**Cited result.**") > md_c.index("Theorem 1.1  —  GLOBAL")
            and any("`cited` must be a string" in p for p in bad_c))
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
            set(d_) == {"N.instDecidableEqSide"} and h_ == ["definition N.lost: source text not found in lean_files"])
        # a structure's fields have no text of their own (live L-infinity run: a set-aside round)
        tbl = {"N.S": ("inductive", "1", []), "N.S.f": ("def", "1", ["N.S"]), "N.S.π": ("def", "1", ["N.S"]),
               "N.S.toB": ("def", "1", ["N.S"]), "N.S.gone": ("def", "1", ["N.S"]),
               "N.T": ("inductive", "1", []), "N.T.f": ("def", "1", ["N.T"])}
        src = {"N.S": "@[ext] structure S (n : ℕ) extends B n where\n  f : Fin 3 → Fin n\n  π : Equiv.Perm (Fin n)",
               "N.T": "inductive T | f"}
        h_, d_ = classify_sourceless(sorted(tbl), tbl, lambda n: src.get(n, ""))
        say("a structure's fields (and its `toB`) are noted, not holes; a name it does not declare, or an "
            "inductive's, is a hole", set(d_) == {"N.S.f", "N.S.π", "N.S.toB"} and "structure N.S" in d_["N.S.f"]
            and h_ == ["definition N.S.gone: source text not found in lean_files",
                       "definition N.T.f: source text not found in lean_files"])
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
        for c_ in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", rr, *c_], capture_output=True)
        open(os.path.join(rr, "R", "STATEMENTS_BUNDLE.md"), "w", encoding="utf-8").write("old\n")
        open(os.path.join(rr, "R", "FINGERPRINTS.json"), "w").write('{"fingerprints": {}}')
        def stub_bundle(cfg, table=None):
            build_bundle.missing = []
            return "new\n", [], []
        stub_bundle.missing = []
        g["build_bundle"] = stub_bundle
        _cfg3 = {"rounds_dir": rr, "name": "t", "involvement": "hands-off"}
        project.select = lambda name=None: (_cfg3, "stub")
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
                for by in ("human", "agent"):
                    # SWEEP-FIX G6: a human approves under involved (hands-off refuses --by human)
                    _cfg3["involvement"] = "involved" if by == "human" else "hands-off"
                    target = os.path.join(rr, "APPROVED_FINGERPRINTS.json")
                    if os.path.exists(target):
                        os.remove(target)
                    if by == "agent":
                        # a run with no earlier approval (B2 review: --by agent over one is a re-approval);
                        # the agent's is the last, so the later --by agent approvals re-approve its own (hands-off)
                        shutil.rmtree(os.path.join(rr, ".git"))
                        for c_ in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                                   ["add", "-A"], ["commit", "-qm", "fixture"]):
                            subprocess.run(["git", "-C", rr, *c_], capture_output=True)
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc = main(["approve", "--round", "R", "--how", "blanket", "--by", by])
                    doc = json.load(open(target)) if os.path.exists(target) else {}
                    say(f"`signoff.py approve --by {by}` writes by={by} to the approval file",
                        rc == 0 and doc.get("by") == by)
                    names = subprocess.run(["git", "-C", rr, "show", "--name-only", "--format=%s", "HEAD"],
                                           capture_output=True, text=True).stdout.split("\n")
                    say(f"A5: `approve --by {by}` commits the approval file alone, by name, as 'approve R'",
                        names[0] == "approve R" and [n for n in names[1:] if n.strip()] == ["APPROVED_FINGERPRINTS.json"])
                buf = io.StringIO()
                os.remove(os.path.join(rr, "APPROVED_FINGERPRINTS.json"))
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    rc = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent",
                               "--exclude", "Theorem 1.1"])
                say("`--by agent` with `--exclude` is refused (agent approval covers everything)",
                    rc != 0 and "approves EVERYTHING" in buf.getvalue())
                # A5: the informalizer's and the writer's files are committed by name, as "signoff R"
                rR = os.path.join(rr, "R")
                head_s = lambda: subprocess.run(["git", "-C", rr, "show", "--name-only", "--format=%s", "HEAD"],
                                                capture_output=True, text=True).stdout.split()
                open(os.path.join(rR, "INFORMAL.json"), "w").write('{"rows": []}')
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    r1 = save_record(rR, "INFORMAL.json"); h1 = head_s()
                    open(os.path.join(rR, "INFORMAL.json"), "w").write('{"rows": [2]}')
                    r2 = save_record(rR, "INFORMAL.json", "a second blind reading")
                    open(os.path.join(rR, "SIGNOFF.json"), "w").write('{"rows": []}')
                    r3 = save_record(rR, "SIGNOFF.json")
                    open(os.path.join(rR, "SIGNOFF.json"), "w").write('{"rows": [1]}')
                    r4 = save_record(rR, "SIGNOFF.json")
                    r5 = save_record(rR, "SIGNOFF.json", "writer rerun: a flag was missing"); h5 = head_s()
                say("A5: save-informal commits INFORMAL.json alone as 'signoff R', once",
                    r1 == 0 and h1[:2] == ["signoff", "R"] and h1[2:] == ["R/INFORMAL.json"] and r2 != 0)
                say("A5: save-signoff commits SIGNOFF.json; saving it again needs a reason, recorded in the subject",
                    r3 == 0 and r4 != 0 and r5 == 0 and "re-written:" in " ".join(h5))
                # PDF-AGENTS (review 7): `approve --by human` refuses unless the sheet's PDF is the one recorded for its
                # markdown as it is now (render_record.check); the shown PDF's sha and outcome go into the approval
                def fresh_():
                    if os.path.exists(os.path.join(rr, "APPROVED_FINGERPRINTS.json")):
                        os.remove(os.path.join(rr, "APPROVED_FINGERPRINTS.json"))
                    shutil.rmtree(os.path.join(rr, ".git"))
                    for c_ in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                               ["add", "-A"], ["commit", "-qm", "fixture"]):
                        subprocess.run(["git", "-C", rr, *c_], capture_output=True)
                project.select = lambda name=None: ({"rounds_dir": rr, "name": "t", "involvement": "involved"}, "stub")
                saved_guard = (g["RENDER_GUARD"], g["RENDER_SHOWN"])
                try:
                    fresh_()
                    g["RENDER_GUARD"] = lambda c_, r_: ["R/SIGNOFF.md changed since its PDF was rendered: render it"]
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc_g = main(["approve", "--round", "R", "--how", "blanket", "--by", "human"])
                    refused_ = rc_g == 1 and "approval REFUSED" in buf.getvalue() and "ask again" in buf.getvalue() \
                        and not os.path.exists(os.path.join(rr, "APPROVED_FINGERPRINTS.json"))
                    fresh_()
                    project.select = lambda name=None: ({"rounds_dir": rr, "name": "t", "involvement": "hands-off"}, "stub")
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc_ag = main(["approve", "--round", "R", "--how", "blanket", "--by", "agent"])
                    fresh_()
                    project.select = lambda name=None: ({"rounds_dir": rr, "name": "t", "involvement": "involved"}, "stub")
                    g["RENDER_GUARD"] = lambda c_, r_: []
                    g["RENDER_SHOWN"] = lambda c_, r_: (None, ["the sheet's PDF now (cd…) is not the one shown to the "
                                                               "human (ab…)"])
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc_sh = main(["approve", "--round", "R", "--how", "blanket", "--by", "human"])
                    refused_sh = rc_sh == 1 and "not the one shown" in buf.getvalue() and "ask again" in buf.getvalue() \
                        and not os.path.exists(os.path.join(rr, "APPROVED_FINGERPRINTS.json"))
                    fresh_()
                    g["RENDER_SHOWN"] = lambda c_, r_: ({"pdf_sha256": "ab" * 32, "outcome": "least-bad",
                                                         "render_version": 2}, [])
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        rc_h = main(["approve", "--round", "R", "--how", "blanket", "--by", "human"])
                    doc_h = json.load(open(os.path.join(rr, "APPROVED_FINGERPRINTS.json")))
                    say("PDF-AGENTS: `approve --by human` refuses while the sheet's PDF is not the one recorded for its "
                        "markdown now (render again, ask the human again; never a stop); `--by agent` needs no PDF; a "
                        "human approval records the PDF's sha256 and the render outcome the human was shown",
                        refused_ and rc_ag == 0 and rc_h == 0
                        and doc_h.get("shown") == {"pdf_sha256": "ab" * 32, "outcome": "least-bad", "render_version": 2})
                    say("review LOW: `approve --by human` refuses unless the PDF recorded as shown when the human was "
                        "asked is the one the record ships now (show it and ask again)", refused_sh)
                    say("PDF-AGENTS: the guard approve uses is render_record's fingerprint check of the sheet; what was "
                        "shown is render_record's record of it (render_record.py shown)",
                        {"render_record", "check"} <= set(render_guard.__code__.co_names)
                        and "shown_problem" in render_shown.__code__.co_names)
                finally:
                    g["RENDER_GUARD"], g["RENDER_SHOWN"] = saved_guard
            finally:
                (_fp.compute, _fp.head), g["check"] = saved_fp, saved_check
        finally:
            g["build_bundle"], project.select = saved
        selftest_reapproval(d, say)
        selftest_reapprove_level(d, say)
        selftest_b2_review(d, say)
        selftest_b2_recheck(d, say)
        selftest_b2_round3(d, say)
        selftest_b4(d, say)
        selftest_b13_interrupted(d, say)
    finally:
        globals()["RENDER_GUARD"], globals()["RENDER_SHOWN"] = _guard0
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

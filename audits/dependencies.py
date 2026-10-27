#!/usr/bin/env python3
"""Which formalized results do the goal results not use, and what does each result assume? Two walks
over the kernel's terms, in one Lean run.

WHY THIS EXISTS.  The independent audit of a test run found that one lemma was
formalized and proved but is not on the proof path of the main theorem: an intermediate result was
proved by a different route (disclosed as a route change, "same strength"). Nothing in the report
said plainly that a reader may not assume the goal rests on that lemma. This script computes it: from the
declarations of the goal results (config `goal_results`, matched to index rows), it walks every
constant their types and proofs use, through the project's own declarations, and lists every
other index result the walk never reaches. The report prints the list (section "Proof routes").

THE ASSUMPTION WALK (U2 §2).  A pattern over the source text decided what the formalization assumes
and missed every hypothesis not written as a parameterless `def X : Prop` taken bare. Now Lean
decides, per index result (dependencies_tail.lean): the head of its type is unfolded while it is a
non-Definition project definition, then for each binder of the telescope
  - a Prop binder counts if it uses a non-Definition project constant (`¬ H`, `H ∧ True`,
    `∀ k, H k`, `[Fact (H n)]`, membership of a project set);
  - a data binder counts if a Subtype, set-builder, membership or `↥S` part of its type does (F2:
    `{y // H y}`, `Finset {y // H y}`, `ℕ → {y // H y}`), or a Prop field of its structure or class
    does (flattened through `extends`; recursion stops at a Definition row);
  - a binder of any sort whose type is a project structure or class (no Definition row) with a Prop
    field, recursively, counts under the structure's name (kind `struct`) whatever its fields use: a
    `class LemmaB : Type where eq : ∀ m, …` instance argument packages a hypothesis like a Prop binder
    does (review fix 1). The conjunction of such a binder's Prop fields (and each field, when several),
    and the `P` of a `[Fact P]`, get the goal/restates checks below;
  - re-check fix: so does a binder whose type CONTAINS such a structure anywhere, not as its head
    (`∀ m, ParamSetup m`, `ParamSetup n × ℕ`, `Unit → ParamSetup n`, a subtype, Option/List/Sigma
    wrappers, the value of a non-Definition project definition it uses, a field of type `List (MSet k)`):
    listed under the structure's name (a Prop binder is already listed, kind prop), and the structure's
    Prop fields on a generic value, closed over its parameters (`∀ n, h1 n ∧ h2 n`), get the goal/restates
    checks (binder `<binder>.<structure>[.<field>]`);
  - a non-Definition project Prop constant left in the body is an embedded assumption (F3:
    `P ∧ (H → Q)`, `∃ x, H x → …`, `H ↔ P`).
A Definition row covers its constant and everything under it (projections, equation lemmas);
theorems, instances, generated companions and `<decl>_as_printed` never count. Section variables
taken with `include` are binders like any other (F6). It writes `assumes`: {result: [{name, binder,
kind, type_pp, embedded}]} (one entry per counting constant: `name` is the hypothesis's Lean name,
the key of its `## Hypotheses` row), `binders` (every Prop binder and `struct` binder, for "added since
approval"), `goal`/`restates` (a Prop binder, or such a field conjunction, definitionally the conclusion
or another result's statement or conclusion instance), `axioms`
(collectAxioms), `instances` (project data instances in the closure with no index row, F5),
`bare` (every project Prop constant taken bare as a hypothesis anywhere, F17) and `walked`.
type_pp is printed under pinned pp options. The old regex path (make_report PROP_SLOT,
only_applied) is gone.

  dependencies.py [--project NAME] [--write]   writes <ROUNDS-DIR>/DEPENDENCIES.json with --write
  dependencies.py [--project NAME] --compare   exit 1 if DEPENDENCIES.json differs from the walk now,
                                               or is missing (Phase 0 --readonly, run by the adjudicator)
  dependencies.py --selftest                   needs a built project (it compiles a fixture)

Phase 0 runs it in every round (statement rounds too: the assumption walk reads types only).
Failures are coded: a walk that crashes inside the walk's own code is RED[tool-bug] (L3: a pinned
script's bug, the tool-bug key); one that fails before it (the project does not build, an import is
missing) and a missing or stale file are RED[dependencies] (rerun Phase 0).
"""
import sys
sys.dont_write_bytecode = True
import argparse, json, os, re, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

TAIL = os.path.join(project.AUDITS, "dependencies_tail.lean")
OUT = "DEPENDENCIES.json"


def index_decls(cfg):
    """[(paper label, [Lean names cited in its row])] from the index (backticked names)."""
    import signoff
    out = []
    for label, rest in signoff.index_rows(cfg):
        names = [t.split("(")[0].strip() for t in re.findall(r"`([^`]+)`", rest)]
        names = [n for n in names if re.fullmatch(r"[A-Za-z_][\w'.₀-₉]*", n)]
        if names:
            out.append((label, names))
    return out


def norm(label):
    return re.sub(r"\s+", " ", label).strip().lower()


def goal_roots(cfg):
    """The Lean names the index cites (as written) for the configured goal results."""
    goals = {norm(g) for g in cfg.get("goal_results") or []}
    return sorted({n for lab, ns in index_decls(cfg) if norm(lab) in goals for n in ns})


def project_decls(cfg):
    """Every declaration of the project's lean_files, fully qualified (scope.py's parser)."""
    import scope
    out = set()
    for rel in cfg.get("lean_files") or []:
        p = os.path.join(project.REPO, rel)
        if os.path.exists(p):
            out |= {q for q in scope.parse_decls(open(p, encoding="utf-8").read()) if q != "_unnamed"}
    return out


def resolve_name(name, ns, declared):
    """A name as the index cites it (often unqualified) -> the full declaration name, the way the
    dependency walk resolves it (dependencies_tail.lean, `resolve`): as written if declared, else
    namespace ++ name if declared, else None. The one Python implementation of that rule (the goal
    check and the index-cell rule of a result left unproved use it; the axiom sweep's tail applies
    the same rule in Lean)."""
    if name in declared:
        return name
    q = f"{ns}.{name}" if ns else name
    return q if q in declared else None


def resolve_all(names, ns, declared):
    """{full names} for `names`; an unresolved one gives both forms it could stand for (as written
    and namespace ++ name), so a check keyed on it fails closed."""
    out = set()
    for n in names:
        r = resolve_name(n, ns, declared)
        out |= {r} if r else {n, f"{ns}.{n}" if ns else n}
    return out


def build_source(cfg, roots, cands, body=None, unproved=(), asm=None):
    """The Lean text: the project (or `body`), then the walks. `asm`: (results, Definition-row names,
    every indexed name) for the assumption walk (default: none walked)."""
    import axiom_sweep
    lit = lambda xs: "[" + ", ".join(json.dumps(x) for x in xs) + "]"
    a_roots, a_defs, a_ix = asm or ([], [], [])
    tail = project.lean_tail(cfg, TAIL, [("__ROOTS__", lit(roots)), ("__CANDS__", lit(cands)),
                                         ("__UNPROVED__", lit(sorted(unproved))),
                                         ("__GENERATED__", axiom_sweep.GENERATED_LEAN),
                                         ("__ASMROOTS__", lit(a_roots)), ("__DEFS__", lit(a_defs)),
                                         ("__INDEXED__", lit(a_ix))])
    return (project.lean_body(cfg) if body is None else body) + "\n" + tail


LAST = {}      # the raw output and source of the last run (failure_code reads them)


def run(cfg, roots, cands, body=None, unproved=(), asm=None):
    """(exit code, unused candidates, missing names, raw output, [(auxiliary, its exempt parent)]:
    the compiler-generated auxiliaries the axiom sweep accepts under a result left unproved).
    parse_asm(raw output) reads the assumption walk."""
    src = build_source(cfg, roots, cands, body, unproved, asm)
    rc, out = project.run_lean(src)
    LAST.update(src=src, out=out, body_lines=((project.lean_body(cfg) if body is None else body) + "\n").count("\n"))
    unused = re.findall(r"DEPS-UNUSED (\S+)", out)
    missing = re.findall(r"DEPS-MISSING (\S+)", out)
    aux = sorted(set(re.findall(r"DEPS-AUX (\S+) (\S+)", out)))
    ok = rc == 0 and "DEPS-DONE" in out and (asm is None or "DEPS-ASM-DONE" in out)
    return (0 if ok else 1), unused, missing, out, aux


def parse_asm(out):
    """The assumption walk's lines (dependencies_tail.lean) as the DEPENDENCIES.json fields."""
    one = lambda s: " ".join(s.split())
    doc = {"assumes": {}, "binders": {}, "goal": {}, "restates": {}, "axioms": {}, "instances": [],
           "bare": {}, "walked": []}
    for line in out.splitlines():
        kind, _, rest = line.partition(" ")
        f = rest.split("\t")
        if kind == "DEPS-ASM" and len(f) >= 5:
            r, k, b, names, ty = f[0], f[1], f[2], f[3], "\t".join(f[4:])
            for n in [x for x in names.split(",") if x]:
                doc["assumes"].setdefault(r, []).append({"name": n, "binder": b, "kind": k, "type_pp": one(ty),
                                                        "embedded": k == "embedded"})
        elif kind == "DEPS-BINDER" and len(f) >= 3:
            doc["binders"].setdefault(f[0], []).append({"binder": f[1], "type_pp": one("\t".join(f[2:]))})
        elif kind == "DEPS-GOAL" and len(f) >= 2:
            doc["goal"].setdefault(f[0], []).append(f[1])
        elif kind == "DEPS-RESTATES" and len(f) >= 3:
            doc["restates"].setdefault(f[0], []).append({"binder": f[1], "result": f[2]})
        elif kind == "DEPS-AX" and len(f) >= 2:
            doc["axioms"].setdefault(f[0], []).append(f[1])
        elif kind == "DEPS-INST" and f and f[0]:
            doc["instances"].append(f[0].strip())
        elif kind == "DEPS-BARE" and len(f) >= 2:
            doc["bare"].setdefault(f[0], []).append(f[1])
        elif kind == "DEPS-ROOT" and f and f[0]:
            doc["walked"].append(f[0].strip())
    for k in ("bare",):
        doc[k] = {n: sorted(set(u)) for n, u in doc[k].items()}
    # a binder checked both as itself and as its fields' conjunction (a Prop structure) is flagged once
    doc["goal"] = {r: list(dict.fromkeys(bs)) for r, bs in doc["goal"].items()}
    doc["restates"] = {r: [json.loads(x) for x in dict.fromkeys(json.dumps(y, sort_keys=True) for y in v)]
                       for r, v in doc["restates"].items()}
    doc["instances"] = sorted(set(doc["instances"]))
    return doc


def failure_code(out=None, body_lines=None):
    """`tool-bug` when the Lean run failed inside the walks' own code (an error at a line of the
    appended tail: a pinned script's bug, L3), else `dependencies` (the project or an import failed
    before the walk ran: build it and rerun). No error line at all (a crash, a timeout) is tool-bug."""
    out = LAST.get("out", "") if out is None else out
    body_lines = LAST.get("body_lines", 0) if body_lines is None else body_lines
    lines = [int(m.group(1)) for m in re.finditer(r"^\S*\.lean:(\d+):\d+: error", out, re.M)]
    if lines and all(n <= body_lines for n in lines):
        return "dependencies"
    if re.search(r"unknown (?:module prefix|package)|object file .* does not exist", out):
        return "dependencies"
    return "tool-bug"


def lean_hash(cfg, commit):
    """sha256 over the project's Lean files at `commit` (path and content, in order), or None if one
    cannot be read: what DEPENDENCIES.json was computed from. integrity.py recomputes it."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(cfg.get("lean_files") or []):
        r = subprocess.run(["git", "-C", project.REPO, "show", f"{commit}:{f}"], capture_output=True)
        if r.returncode:
            return None
        h.update(f.encode() + b"\0" + r.stdout + b"\0")
    return h.hexdigest()


WALK_SLACK_S = 45     # seconds the walk may add to a bare import (selftest timing guard): ~1 s now, ~165 s before B5r

ASM_KEYS = ("assumes", "binders", "goal", "restates", "axioms", "instances", "bare", "walked")


def problems(cfg, rd=None):
    """[problem] with <ROUNDS-DIR>/DEPENDENCIES.json: it must exist (U2 §2: a missing file is code
    `dependencies`, cured by rerunning Phase 0), carry the assumption walk (a file written before it
    has no `assumes`), and be what dependencies.py wrote for the Lean files at its recorded commit
    (Phase 0 checks this, RED[dependencies], also read-only for the adjudicator; it rewrites the file
    before every report it regenerates)."""
    p = os.path.join(rd or os.path.join(project.REPO, cfg["rounds_dir"]), OUT)
    if not os.path.exists(p):
        return [f"no {OUT}: rerun Phase 0 (phase0.py, not --readonly), which writes it, and commit it"]
    try:
        d = json.load(open(p, encoding="utf-8"))
    except ValueError:
        return [f"{OUT} is malformed"]
    if not isinstance(d, dict):
        return [f"{OUT} is malformed"]
    if not d.get("lean_sha256") or lean_hash(cfg, str(d.get("commit"))) != d.get("lean_sha256"):
        return [f"{OUT} does not match the Lean files at its commit {d.get('commit')}: regenerate it with Phase 0 "
                f"(never edit it)"]
    if not isinstance(d.get("assumes"), dict) or not isinstance(d.get("walked"), list):
        return [f"{OUT} has no assumption walk (written before it existed): rerun Phase 0, which rewrites it"]
    now = lean_hash(cfg, "HEAD")
    if now and now != d.get("lean_sha256"):
        return [f"{OUT} was computed at commit {d.get('commit')}, and the Lean files changed since: rerun Phase 0"]
    # a goal result the assumption walk did not reach fails closed (U2 §2): its assumptions are unknown
    out = [f"{OUT}: the goal result's `{g}` has no assumption-walk entry (not found or not walked): fix the index "
           f"cell or rerun Phase 0" for g in goal_roots(cfg) if g not in set(d.get("walked") or [])]
    return out


def compare(cfg, doc, rd=None):
    """[difference] between <ROUNDS-DIR>/DEPENDENCIES.json and the walk just computed (`doc`), when
    the file is for the same Lean files: a written-by-hand result fails here (review round 3, D1). A
    missing file is a difference (U2 §2)."""
    p = os.path.join(rd or os.path.join(project.REPO, cfg["rounds_dir"]), OUT)
    if not os.path.exists(p):
        return [f"no {OUT}: rerun Phase 0 (it writes the file)"]
    try:
        old = json.load(open(p, encoding="utf-8"))
    except ValueError:
        return [f"{OUT} is malformed"]
    if old.get("lean_sha256") != doc.get("lean_sha256"):
        return []           # for other Lean files: integrity.py checks it against its own commit
    out = []
    for k in ("unused", "missing", "roots", "unproved", "aux"):
        a = sorted(json.dumps(x, sort_keys=True) for x in old.get(k) or [])
        b = sorted(json.dumps(x, sort_keys=True) for x in doc.get(k) or [])
        if a != b:
            out.append(f"{OUT}: `{k}` is {a}, the walk gives {b}")
    for k in ASM_KEYS:
        if json.dumps(old.get(k), sort_keys=True) != json.dumps(doc.get(k), sort_keys=True):
            out.append(f"{OUT}: `{k}` differs from the assumption walk now")
    return out


def aux_record(cfg, decls, rd=None):
    """([(auxiliary, exempt parent)], None) from <ROUNDS-DIR>/DEPENDENCIES.json: every
    compiler-generated auxiliary the axiom sweep accepts under a result left unproved (`decls`, the
    current decisions.unproved), for the report; or (None, why) when the file does not record them
    for exactly these results (absent, older, or written for other leave lines)."""
    p = os.path.join(rd or os.path.join(project.REPO, cfg["rounds_dir"]), OUT)
    if not os.path.exists(p):
        return None, f"no {OUT}"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except ValueError:
        return None, f"{OUT} is malformed"
    if "aux" not in d or sorted(d.get("unproved") or []) != sorted(decls):
        return None, f"{OUT} was not written for the current 'leave <decl> unproved' lines"
    return [(a.get("lean", "?"), a.get("parent", "?")) for a in d["aux"]], None


def index_parts(cfg):
    """(results, Definition-row names, every indexed name): the Lean names the index cites for its
    result rows, for its Definition/Notation/Construction rows, and all of them."""
    rows = index_decls(cfg)
    is_def = lambda lab: re.match(r"(?i)(definition|notation|construction)\b", lab)
    return (sorted({n for lab, ns in rows if not is_def(lab) for n in ns}),
            sorted({n for lab, ns in rows if is_def(lab) for n in ns}),
            sorted({n for _lab, ns in rows for n in ns}))


def compute(cfg):
    """(doc, None) or (None, why); after a failed Lean run, failure_code() says whose fault it was."""
    rows = index_decls(cfg)
    roots = goal_roots(cfg)
    results, defs, indexed = index_parts(cfg)
    # results only: a definition is not a result a proof can leave unused
    cands = sorted(set(results) - set(roots))
    if not results:
        LAST.update(out="", body_lines=0)
        return None, "the index cites no Lean name for any result"
    import decisions
    unproved = sorted(decisions.unproved(cfg)["decls"])
    rc, unused, missing, out, aux = run(cfg, roots, cands if roots else [], unproved=unproved,
                                        asm=(results, defs, indexed))
    if rc:
        last = (out.strip().splitlines() or ["?"])[-1][:200]
        return None, "the dependency walk did not run: " + re.sub(r"\berror:", "error -", last)
    by_name = {n: lab for lab, ns in rows for n in ns}
    head = subprocess.run(["git", "-C", project.REPO, "rev-parse", "--short=11", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    doc = {"commit": head, "lean_sha256": lean_hash(cfg, head), "goal_results": sorted(cfg.get("goal_results") or []),
           "roots": roots,
           # no goal result matched: nothing to measure "unused" against (the report says not computed)
           "unused": [{"result": by_name.get(n, "?"), "lean": n} for n in unused] if roots else [],
           "missing": missing, "unproved": unproved,
           "aux": [{"lean": a, "parent": p} for a, p in aux], "results": results, "definitions": defs}
    doc.update(parse_asm(out))
    return doc, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.project)
    try:
        cfg, why = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    try:
        doc, err = compute(cfg)
    except Exception as e:      # noqa: BLE001 -- a crash of this script is a pinned script's bug (L3)
        print(f"RED[tool-bug] dependencies.py crashed: {type(e).__name__}: {str(e)[:200]}")
        return 1
    if err:
        code = failure_code() if LAST.get("out") else "dependencies"
        print(f"RED[{code}] dependencies: not computed: {err}"
              + (" (the walk's own code failed: a pinned script's bug)" if code == "tool-bug"
                 else " (build the project, then rerun Phase 0)"))
        return 1
    if a.compare:
        diff = compare(cfg, doc)
        for d_ in diff:
            print(f"MISMATCH[dependencies] {d_}")
        print(f"dependencies: {OUT} {'differs from the walk now' if diff else 'matches the walk now (or is for other Lean)'}")
        return 1 if diff else 0
    for u in doc["unused"]:
        print(f"UNUSED  {u['result']}: {u['lean']} is not used by the goal results ({', '.join(doc['goal_results'])})")
    for m in doc["missing"]:
        print(f"MISSING[dependencies] {m}: cited in the index, not found in the environment")
    nasm = sorted({e["name"] for es in doc["assumes"].values() for e in es})
    print(f"dependencies at {doc['commit']}: {len(doc['unused'])} formalized result(s) not used by the goal results; "
          f"{len(nasm)} hypothesis name(s) assumed by {len(doc['assumes'])} result(s)")
    if a.write:
        p = os.path.join(project.REPO, cfg["rounds_dir"], OUT)
        json.dump(doc, open(p, "w", encoding="utf-8"), indent=1, sort_keys=True)
        print(f"wrote {os.path.relpath(p, project.REPO)}")
    return 0


def selftest(proj=None):
    """A fixture appended to the built project: a root using a helper that uses a candidate; an
    unrelated candidate; a private helper on the path. Exit 3 if the fixture cannot run."""
    res = []
    def say(n, ok):
        res.append(bool(ok)); print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    try:
        cfg, _ = project.select(proj)
    except project.SelectionError as e:
        print(f"selftest: needs a project ({e})"); return 3
    ns = cfg["namespace"]
    sw = cfg["sweep"]
    base = (f"import {sw['module']}\n" if sw["mode"] == "import"
            else open(os.path.join(project.REPO, sw["file"]), encoding="utf-8").read())
    body = base + (f"\nnamespace {ns}\n"
                   "theorem depctl_used : 1 + 1 = 2 := rfl\n"
                   "private theorem depctl_helper : 2 = 1 + 1 := depctl_used.symm\n"
                   "theorem depctl_root : 2 = 1 + 1 := depctl_helper\n"
                   "theorem depctl_unused : 3 = 3 := rfl\n"
                   "theorem depctl_type_only (h : depctl_unused = depctl_unused) : True := trivial\n"
                   # re-check of Q1 (b), MED-A: auxiliaries the axiom sweep accepts under a result
                   # left unproved -- a generated equation lemma, and the review's metaprogram that
                   # manufactures a rangeless `X.eq_7` -- are recorded for the report; one written
                   # by hand (a source range) is not an auxiliary
                   "def depctl_f (n : Nat) : Nat := match n with | 0 => sorry | k+1 => k\n"
                   "theorem depctl_t : depctl_f 0 = depctl_f 0 := by rw [depctl_f.eq_1]\n"
                   "theorem depctl_s : 1 = 2 := sorry\n"
                   "open Lean Elab Command in\nelab \"depctl_gen\" : command => liftCoreM do\n"
                   f"  let c ← getConstInfo `{ns}.depctl_s\n"
                   f"  addDecl (.thmDecl {{ name := `{ns}.depctl_s.eq_7, levelParams := [], type := c.type, "
                   f"value := .const `{ns}.depctl_s [] }})\n"
                   "depctl_gen\n"
                   "theorem depctl_s.eq_3 : 1 = 2 := depctl_s\n"
                   f"end {ns}\n")
    import time
    t0 = time.monotonic()
    project.run_lean(base)
    t_base = time.monotonic() - t0
    t0 = time.monotonic()
    rc, unused, missing, out, aux = run(cfg, ["depctl_root"], ["depctl_used", "depctl_unused", f"{ns}.depctl_used",
                                                              "depctl_nonexistent"], body,
                                        unproved=[f"{ns}.depctl_f", f"{ns}.depctl_s"])
    if rc and "DEPS-DONE" not in out:
        print(out[-800:]); print("selftest: the fixture did not run (is the project built?)"); return 3
    t_walk = time.monotonic() - t0
    say(f"timing guard: the walk (with a result left unproved, so both project-constant loops run) adds "
        f"{t_walk - t_base:.1f} s to importing the project ({t_base:.1f} s); at most {WALK_SLACK_S} s (it took ~3 min "
        f"when it listed every constant with Mathlib imported)", t_walk - t_base <= WALK_SLACK_S)
    tail_src = open(TAIL, encoding="utf-8").read()
    say("timing guard: the tail never lists every constant (`env.constants.toList`/`fold`/`forM` outside comments)",
        not re.search(r"env\.constants\.(toList|fold|forM|foldM)",
                      re.sub(r"--[^\n]*", "", re.sub(r"/-.*?-/", "", tail_src, flags=re.S))))
    say("a candidate the root's proof reaches through a private helper is used; an unrelated one is not",
        "depctl_used" not in unused and f"{ns}.depctl_used" not in unused and "depctl_unused" in unused)
    say("a name not in the environment is reported missing, never as used", "depctl_nonexistent" in missing)
    rc2, unused2, _, _, aux2 = run(cfg, ["depctl_type_only"], ["depctl_unused"], body)
    say("MED-A: every rangeless generated auxiliary of a result left unproved that reaches sorryAx is recorded "
        "with its parent (an equation lemma; a metaprogram's `X.eq_7`); one written by hand is not; with no "
        "leave line, none",
        {(f"{ns}.depctl_f.eq_1", f"{ns}.depctl_f"), (f"{ns}.depctl_s.eq_7", f"{ns}.depctl_s")} <= set(aux)
        and all(p_ in (f"{ns}.depctl_f", f"{ns}.depctl_s") and a_.startswith(p_ + ".eq_") for a_, p_ in aux)
        and f"{ns}.depctl_s.eq_3" not in {a_ for a_, _p in aux} and aux2 == [])
    say("a candidate used only in a root's statement (its type) counts as used", "depctl_unused" not in unused2)
    rc3, unused3, _, out3, _ = run(cfg, ["depctl_unused"], ["depctl_root", "depctl_used"], body)
    say("the walk does not go backwards (a used lemma does not reach what uses it)",
        set(unused3) == {"depctl_root", "depctl_used"})
    td = tempfile.mkdtemp()
    try:
        head = subprocess.run(["git", "-C", project.REPO, "rev-parse", "--short=11", "HEAD"], capture_output=True, text=True).stdout.strip()
        none_ = problems(cfg, td)
        walked_ = sorted(goal_roots(cfg))
        full = {"commit": head, "lean_sha256": lean_hash(cfg, head), "unused": [], "assumes": {}, "walked": walked_}
        json.dump(full, open(os.path.join(td, OUT), "w"))
        good = problems(cfg, td) == []
        json.dump(dict(full, walked=[]), open(os.path.join(td, OUT), "w"))
        unwalked = problems(cfg, td)
        json.dump({k: v for k, v in full.items() if k != "assumes"}, open(os.path.join(td, OUT), "w"))
        noasm = problems(cfg, td)
        json.dump({"commit": head, "lean_sha256": "0" * 64, "unused": []}, open(os.path.join(td, OUT), "w"))
        bad = problems(cfg, td)
        json.dump({"commit": head, "unused": []}, open(os.path.join(td, OUT), "w"))
        nohash = problems(cfg, td)
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    say("review 2 N4: DEPENDENCIES.json is checked against the Lean files at its commit (a written-by-hand file fails)",
        good and bad and nohash)
    say("U2 §2: no DEPENDENCIES.json is a problem; one without the assumption walk is; a goal result's root "
        "not in `walked` is (fails closed)",
        len(none_) == 1 and none_[0].startswith(f"no {OUT}") and noasm and "no assumption walk" in noasm[0]
        and bool(walked_) and len(unwalked) == len(walked_) and all("has no assumption-walk entry" in x for x in unwalked))
    td2 = tempfile.mkdtemp()
    try:
        walk = {"lean_sha256": "h", "roots": ["a"], "unused": [{"result": "Lemma 1", "lean": "N.l1"}], "missing": []}
        json.dump(dict(walk, unused=[]), open(os.path.join(td2, OUT), "w"))
        doctored = compare(cfg, walk, td2)
        json.dump(walk, open(os.path.join(td2, OUT), "w"))
        same = compare(cfg, walk, td2)
    finally:
        import shutil
        shutil.rmtree(td2, ignore_errors=True)
    say("review 3 D1: a DEPENDENCIES.json whose result differs from the walk (e.g. 'unused' emptied) is a mismatch",
        doctored and same == [])
    td3 = tempfile.mkdtemp()
    try:
        rec = {"lean_sha256": "h", "unproved": ["N.a"], "aux": [{"lean": "N.a.eq_7", "parent": "N.a"}]}
        none_ = aux_record(cfg, ["N.a"], td3)
        json.dump(rec, open(os.path.join(td3, OUT), "w"))
        got, stale, old_ = aux_record(cfg, ["N.a"], td3), aux_record(cfg, ["N.a", "N.b"], td3), None
        doctored_aux = compare(cfg, dict(rec, aux=[]), td3)
        json.dump({"lean_sha256": "h", "unused": []}, open(os.path.join(td3, OUT), "w"))
        old_ = aux_record(cfg, ["N.a"], td3)
    finally:
        import shutil
        shutil.rmtree(td3, ignore_errors=True)
    say("MED-A: the report reads the recorded auxiliaries only for the current leave lines (absent, older or "
        "for other lines: not recorded); an emptied list is a mismatch with the walk",
        got == ([("N.a.eq_7", "N.a")], None) and none_[0] is None and stale[0] is None and old_[0] is None
        and doctored_aux)
    # --- B5 (U2 §2): the assumption walk's fixtures; each must or must not be listed --------------------
    fx = (f"\nnamespace {ns}.AsmFix\n"
          "def H (n : ℕ) : Prop := n ≠ 7\ndef H0 : Prop := True\ndef DefP (n : ℕ) : Prop := n ≤ 5\n"
          "def GoodSet : Set ℕ := {n | n ≠ 7}\n"
          "structure Bundle where\n  n : ℕ\n  hn : H n\nstructure Ext extends Bundle where\n  m : ℕ\n"
          "structure DefS where\n  n : ℕ\n  extra : H n\n"
          "def MainStmt : Prop := ∀ n, H n → n = n\n"
          "axiom asm_ax : (2 : ℕ) = 2\n"
          "theorem r_prop (n : ℕ) (h : H n) : True := trivial\n"
          "theorem r_not (h : ¬ H 0) : True := trivial\ntheorem r_and (h : H 0 ∧ True) : True := trivial\n"
          "theorem r_forall (h : ∀ k, H k) : True := trivial\ntheorem r_fact [Fact (H 0)] : True := trivial\n"
          "theorem r_sub (x : {y // H y}) : True := trivial\ntheorem r_finsub (s : Finset {y // H y}) : True := trivial\n"
          "theorem r_fnsub (f : ℕ → {y // H y}) : True := trivial\ntheorem r_elem (x : ↥GoodSet) : True := trivial\n"
          "theorem r_mem (n : ℕ) (h : n ∈ GoodSet) : True := trivial\n"
          "theorem r_setb (x : {k : ℕ | H k}) : True := trivial\n"
          "theorem r_struct (b : Bundle) : True := trivial\ntheorem r_ext (b : Ext) : True := trivial\n"
          "theorem r_defs (d : DefS) : True := trivial\n"
          "theorem r_emb : True ∧ (H 0 → True) := ⟨trivial, fun _ => trivial⟩\n"
          "theorem r_exists : ∃ x, H x → True := ⟨0, fun _ => trivial⟩\ntheorem r_iff : H 0 ↔ H 0 := Iff.rfl\n"
          "theorem r_unf : MainStmt := fun _ _ => rfl\n"
          "theorem r_clean (n : ℕ) (h : 1 ≤ n) (h2 : DefP n) : n = n := rfl\n"
          "theorem r_bare (h : H0) : True := trivial\n"
          "def x_as_printed : Prop := ∀ n : ℕ, n = 0\n"
          "theorem not_x_as_printed : ¬ x_as_printed := fun h => absurd (h 1) (by decide)\n"
          "section\nvariable (hv : H 1)\ninclude hv\ntheorem r_include : True := trivial\nend\n"
          "instance instBundle : Inhabited Bundle := ⟨⟨0, by unfold H; decide⟩⟩\n"
          "theorem r_inst : (default : Bundle).n = 0 := rfl\n"
          "theorem r_goal (n : ℕ) (h : H n) : H n := h\ntheorem lem (n : ℕ) : n + 0 = n := rfl\n"
          "theorem r_restate (h : ∀ n : ℕ, n + 0 = n) : True := trivial\n"
          "theorem r_axiom : (2 : ℕ) = 2 := asm_ax\n"
          # real records (two test runs): the printed statement as a Prop definition cited on its result's
          # index row, and its refutation `¬ P`; a theorem conditional on that statement takes it as a binder
          "def PStmt : Prop := ∀ n : ℕ, n = 0\n"
          "theorem r_refute : ¬ PStmt := fun h => absurd (h 1) (by decide)\n"
          "theorem r_cond (h : PStmt) : True := trivial\n"
          # an instance of another result's conclusion (U §13 plant: (h : InstHyp n) restating a lemma
          # at n); a binder merely of the same shape as a lemma's hypothesis is not one
          "theorem lem2 (n : ℕ) (hn : 1 ≤ n) : n * 1 = n := Nat.mul_one n\n"
          "def InstHyp (n : ℕ) : Prop := n * 1 = n\n"
          "theorem r_inst_of (n : ℕ) (h : InstHyp n) : True := trivial\n"
          "theorem r_shape (n : ℕ) (hn : 1 ≤ n) : True := trivial\n"
          # review fix 1: a project class/structure of ANY sort whose Prop fields use only Mathlib hides a
          # hypothesis (a repro: `class LemmaB : Type` restating a corrected lemma as an instance
          # argument; `structure ParamSetup (n) : Type` with a result's conclusion as two fields)
          "theorem lem3 (n : ℕ) : n * 1 = n ∧ n + 0 = n := ⟨Nat.mul_one n, rfl⟩\n"
          "class LemB : Type where\n  eq : ∀ n : ℕ, n + 0 = n\n"
          "theorem r_cls [LemB] : True := trivial\n"
          "structure MSet (n : ℕ) : Type where\n  h1 : n * 1 = n\n  h2 : n + 0 = n\n"
          "theorem r_mset (n : ℕ) (S : MSet n) : True := trivial\n"
          "class LemBP : Prop where\n  eq : ∀ n : ℕ, n + 0 = n\n"
          "theorem r_clsP [LemBP] : True := trivial\n"
          "structure MSetP (n : ℕ) : Prop where\n  h1 : n * 1 = n\n  h2 : n + 0 = n\n"
          "theorem r_msetP (n : ℕ) (S : MSetP n) : True := trivial\n"
          "structure Wrap : Type where\n  k : ℕ\n  s : MSet k\n"
          "theorem r_wrap (w : Wrap) : True := trivial\n"
          "structure DataS : Type where\n  n : ℕ\n"
          "theorem r_data (d : DataS) : True := trivial\n"
          "theorem r_factr [Fact (∀ n : ℕ, n + 0 = n)] : True := trivial\n"
          "theorem r_factc (n : ℕ) [Fact (1 ≤ n)] : True := trivial\n"
          "theorem r_two [LemB] [LemB] : True := trivial\n"
          # re-check fix: a project structure with a Prop field CONTAINED in a binder's type, not its head
          # (a result (S : ∀ m, ParamSetup m), `× ℕ`, `Unit →`, Option/List/subtype/Sigma wrappers)
          "theorem r_cfa (S : ∀ m, MSet m) : True := trivial\n"
          "theorem r_cprod (n : ℕ) (S : MSet n × ℕ) : True := trivial\n"
          "theorem r_cfun (n : ℕ) (S : Unit → MSet n) : True := trivial\n"
          "theorem r_copt (n : ℕ) (S : Option (MSet n)) : True := trivial\n"
          "theorem r_clist (S : List LemB) : True := trivial\n"
          "theorem r_csub (n : ℕ) (S : {s : MSet n // True}) : True := trivial\n"
          "theorem r_csig (S : Σ m, MSet m) : True := trivial\n"
          "theorem r_cpropfa (h : ∀ m, MSetP m) : True := trivial\n"
          "structure WrapL : Type where\n  l : List (MSet 3)\n"
          "theorem r_cwrapl (w : WrapL) : True := trivial\n"
          "theorem r_cdata (S : DataS × ℕ) : True := trivial\n"
          "def Setups : Type := ∀ m, MSet m\n"
          "theorem r_cdef (S : Setups) : True := trivial\n"
          f"end {ns}.AsmFix\n")
    names = ("r_prop r_not r_and r_forall r_fact r_sub r_finsub r_fnsub r_elem r_mem r_setb r_struct r_ext r_defs "
             "r_emb r_exists r_iff r_unf r_clean r_bare not_x_as_printed r_include r_inst r_goal lem r_restate "
             "r_axiom PStmt r_refute r_cond lem2 r_inst_of r_shape lem3 r_cls r_mset r_clsP r_msetP r_wrap r_data r_factr "
             "r_factc r_two r_cfa r_cprod r_cfun r_copt r_clist r_csub r_csig r_cpropfa r_cwrapl r_cdata r_cdef").split()
    A = lambda n: f"AsmFix.{n}"
    rcA, _u, _m, outA, _a = run(cfg, [], [], body + "set_option linter.unusedVariables false\n" + fx,
                                asm=([A(n) for n in names], [f"{ns}.AsmFix.DefS", f"{ns}.AsmFix.DefP"], [A(n) for n in names]))
    if rcA:
        print(outA[-1500:])
    W = parse_asm(outA)
    H, G = f"{ns}.AsmFix.H", f"{ns}.AsmFix.GoodSet"
    got = lambda r, k=None: {e["name"] for e in W["assumes"].get(A(r), []) if k is None or e["kind"] == k}
    say("U2 §2 the walk runs on the fixture and reaches every result", rcA == 0 and set(W["walked"]) == {A(n) for n in names})
    say("Prop binders using a non-Definition project constant are listed: (h : H n), ¬ H, H ∧ True, ∀ k, H k, "
        "[Fact (H 0)], membership of a project set, a parameterless H0",
        all(got(r, "prop") == {H} for r in ("r_prop", "r_not", "r_and", "r_forall", "r_fact"))
        and got("r_mem", "prop") == {G} and got("r_bare") == {f"{ns}.AsmFix.H0"})
    say("F2: a subtype, Finset of a subtype, a function into a subtype, a set-builder and ↥S binder are listed",
        all(got(r, "data") == {H} for r in ("r_sub", "r_finsub", "r_fnsub", "r_setb")) and got("r_elem", "data") == {G})
    say("structures: a Prop field of a structure binder is listed, flattened through extends",
        got("r_struct", "field") == {H} and got("r_ext", "field") == {H})
    say("recursion stops at a Definition row: an extra Prop field on a Definition-row structure is not listed (the "
        "correspondence lane lists its fields, F1); a Definition-row or Mathlib-only binder is not listed",
        got("r_defs") == set() and got("r_clean") == set())
    say("F3: a project Prop constant left in the body is an embedded assumption (P ∧ (H → Q), ∃ x, H x → …, H ↔ P)",
        all(got(r, "embedded") == {H} and all(e["embedded"] for e in W["assumes"][A(r)])
            for r in ("r_emb", "r_exists", "r_iff")))
    say("step 1: the root's type is unfolded first (theorem : MainStmt lists H as a binder, not MainStmt)",
        got("r_unf", "prop") == {H} and f"{ns}.AsmFix.MainStmt" not in got("r_unf"))
    say("F6: a section variable taken with `include` is a binder like any other", got("r_include", "prop") == {H})
    say("<decl>_as_printed is never a binder (its refutation lists nothing)", got("not_x_as_printed") == set())
    say("an index result's own Prop statement left in a body (`¬ P`, its refutation) is not embedded; taken as "
        "a binder it is a hypothesis (as in two test runs' refutations)",
        got("r_refute") == set() and got("r_cond", "prop") == {f"{ns}.AsmFix.PStmt"})
    say("benchmarks: a binder that IS the conclusion (H = goal), a binder restating another result",
        W["goal"].get(A("r_goal")) == ["h"] and {"binder": "h", "result": A("lem")} in W["restates"].get(A("r_restate"), []))
    say("benchmark: a binder that is an instance of another result's conclusion ((h : InstHyp n), InstHyp n "
        "unfolding to lem2's conclusion at n) restates it; a binder like a result's hypothesis (1 ≤ n) does not; "
        "a refutation's `¬ P` is not taken apart",
        {"binder": "h", "result": A("lem2")} in W["restates"].get(A("r_inst_of"), [])
        and got("r_inst_of", "prop") == {f"{ns}.AsmFix.InstHyp"} and A("r_shape") not in W["restates"]
        and all(x["result"] != A("r_refute") for v in W["restates"].values() for x in v))
    rs = lambda r: {(x["binder"], x["result"]) for x in W["restates"].get(A(r), [])}
    F = lambda n: f"{ns}.AsmFix.{n}"
    say("review fix 1: a binder whose type is a project class/structure of sort Type with a Prop field (its fields "
        "Mathlib-only) is listed under the structure's name (kind struct, recorded as a binder) and its fields' "
        "conjunction gets the restates check: `[LemB]` restates lem, `(S : MSet n)` restates lem3 (h1 alone lem2)",
        got("r_cls", "struct") == {F("LemB")} and ("inst", A("lem")) in rs("r_cls")
        and got("r_mset", "struct") == {F("MSet")} and ("S", A("lem3")) in rs("r_mset")
        and ("S.h1", A("lem2")) in rs("r_mset")
        and [b["binder"] for b in W["binders"].get(A("r_mset"), [])] == ["S"])
    say("review fix 1: the Prop-sorted versions are listed (prop) and flagged as restating; a structure field of "
        "structure type is followed (Wrap.s : MSet k); a data-only structure, a Mathlib-only `Fact` are not "
        "listed; a `Fact P` with P restating a result is flagged (an inline hypothesis); two anonymous instance "
        "binders get distinct names",
        got("r_clsP", "prop") == {F("LemBP")} and ("inst", A("lem")) in rs("r_clsP")
        and got("r_msetP", "prop") == {F("MSetP")} and ("S", A("lem3")) in rs("r_msetP")
        and got("r_wrap", "struct") == {F("Wrap")} and ("w.s.h1", A("lem2")) in rs("r_wrap") and got("r_data") == set() and A("r_data") not in W["restates"]
        and got("r_factr") == set() and ("inst", A("lem")) in rs("r_factr")
        and got("r_factc") == set() and A("r_factc") not in W["restates"] and A("r_factc") not in W["goal"]
        and sorted(e["binder"] for e in W["assumes"].get(A("r_two"), [])) == ["inst", "inst#1"])
    say("re-check fix: a project structure/class with a Prop field anywhere in a binder's type (∀ m, MSet m; "
        "MSet n × ℕ; Unit → MSet n; Option; List LemB; a subtype; a Sigma; a structure field `List (MSet 3)`; a project def `Setups := ∀ m, MSet m`) "
        "is listed under the structure's name (kind struct) and its fields closed over the parameters get the "
        "restates check (`∀ m, MSet m` is lem3's statement; the others instances of it, or lem); a Prop binder "
        "`∀ m, MSetP m` is flagged too; a data-only structure inside a product is not listed",
        all(got(r, "struct") == {F("MSet")} and (("S." + F("MSet"), A("lem3")) in rs(r))
            for r in ("r_cfa", "r_cprod", "r_cfun", "r_copt", "r_csub", "r_csig", "r_cdef"))
        and ("S." + F("MSet") + ".h1", A("lem2")) in rs("r_cprod")
        and got("r_clist", "struct") == {F("LemB")} and ("S." + F("LemB"), A("lem")) in rs("r_clist")
        and got("r_cpropfa", "prop") == {F("MSetP")} and ("h." + F("MSetP"), A("lem3")) in rs("r_cpropfa")
        and got("r_cwrapl", "struct") == {F("WrapL")} and any(b.startswith("w") and r == A("lem3") for b, r in rs("r_cwrapl"))
        and got("r_cdata") == set() and A("r_cdata") not in W["restates"]
        and [b["binder"] for b in W["binders"].get(A("r_cfa"), [])] == ["S"])
    say("F5 a project data instance in the closure, F17 every project Prop constant taken bare, axioms from collectAxioms",
        f"{ns}.AsmFix.instBundle" in W["instances"] and f"{ns}.AsmFix.r_bare" in W["bare"].get(f"{ns}.AsmFix.H0", [])
        and W["axioms"].get(A("r_axiom")) == [f"{ns}.AsmFix.asm_ax"])
    say("type_pp is one line under pinned options; every Prop binder is recorded (for 'added since approval')",
        all("\n" not in e["type_pp"] for es in W["assumes"].values() for e in es)
        and [b["binder"] for b in W["binders"].get(A("r_clean"), [])] == ["h", "h2"])
    rcB, _u, _m, outB, _a = run(cfg, [], [], body + "theorem broken : (1 : ℕ) = 2 := rfl\n", asm=([A("r_prop")], [], []))
    say("L3: a project error before the walk is `dependencies` (rerun); an error inside the walk's code is `tool-bug`",
        rcB == 1 and failure_code(outB, LAST["body_lines"]) == "dependencies"
        and failure_code("x.lean:9999:0: error: unknown constant", 10) == "tool-bug"
        and failure_code("", 10) == "tool-bug")
    src = build_source(cfg, ["a"], ["b"], body="")
    say("the tail is filled: namespace, roots and candidates as Lean string lists",
        "__" not in src.replace("__init", "") and '["a"]' in src and '["b"]' in src)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


if __name__ == "__main__":
    import project
    sys.exit(project.run_main(main))

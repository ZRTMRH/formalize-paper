#!/usr/bin/env python3
"""Print the paste block for one step of an audit round, read from AUDIT_PROTOCOL.md.

WHY THIS EXISTS.  The obvious way to make the prompts easy to find is to collect them in an
appendix.  That would create a second copy of every prompt, and two copies of an instruction drift
-- which is not a hypothetical here: on 2026-09-29 a review pass found that Phase 2 had restated
the post-round commands that "After the lanes return" also gave, and the two had already begun to
disagree, and separately that Phase 3's checklist contradicted its own paste blocks.  The
duplicate is always the copy nobody updates.

So the protocol keeps exactly one copy of each prompt, next to the rationale that explains it, and
this script extracts it.  What you paste is then what the file says, by construction, rather than
by your having remembered to sync an appendix.

  prompt.py --list        the sequence: which step, where to open it, what it does
  prompt.py 3             print step 3's block (pipe to clip.exe / pbcopy to paste)
  prompt.py --lanes       print every enabled lane prompt, filled for this project
  prompt.py --show        print the project's config and anything unfilled in it
  prompt.py --selftest    negative control: every step resolves to exactly one block
  --project NAME          choose the paper; default: the project whose branch is checked out

Steps whose work is commands rather than a prompt (2 and 4) print the commands.

PROJECTS.  One AUDIT_PROTOCOL.md serves every paper formalized in this clone (it is git-excluded,
so it is the same file on every branch). Paper-specific values -- source PDF, arXiv id, Lean
files, namespace, build commands, rounds directory, per-lane calibration -- are placeholders in
the protocol (<SOURCE-PDF>, <NAMESPACE>, ...) filled from audits/projects/<name>.json. See
audits/project.py.
"""
import re, sys, os, glob, argparse, subprocess, datetime, json
sys.dont_write_bytecode = True   # stale bytecode would run code no file shows

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project  # noqa: E402

BLANK_RE = re.compile(r"<<[^\n]*?>>")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The protocol is versioned in this audits/ repo; ../AUDIT_PROTOCOL.md is a symlink to it.
DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AUDIT_PROTOCOL.md")

# lane name -> heading substring that precedes its prompt block
LANES = [
    ("substantiveness", "### Lane A"),
    ("correspondence", "### Lane B"),
    ("paper-faithfulness", "### Lane C"),
    ("non-vacuity", "### Lane D"),
    ("prior-art", "### Lane E"),
]

# step -> (where to open it, one-line description, heading substring that precedes its block)
STEPS = [
    (1, "Working conversation",
        "Formalize, commit, then stop.",
        "Open a conversation in"),
    (2, "Terminal (or an agent)",
        "Phase 0 mechanical gate. Delegatable, if it pastes raw output.",
        "If you delegate this to an agent"),
    (3, "A NEW conversation",
        "Spawn the audit lanes; they write their JSON.",
        "Open a new conversation in"),
    (4, "A NEW conversation",
        "Confirm no lane wrote, roll up coverage, then adjudicate.",
        "Step 4 — adjudicate"),
    (5, "Working conversation",
        "Implement the adopted rows. Re-run Phase 0. Commit.",
        "Step 5 — implement"),
]


def blocks_after(text, heading_sub):
    """The first fenced block following the heading containing `heading_sub`."""
    i = text.find(heading_sub)
    if i < 0:
        return None
    m = re.search(r"^```[a-z]*\n(.*?)^```", text[i:], re.S | re.M)
    return m.group(1).rstrip("\n") if m else None


def fill_project(body, cfg, lane=None):
    """Fill the per-paper placeholders from the project config. Returns (body, notes)."""
    notes = []
    subs = {
        "<PROJECT>": cfg["name"],
        "<REPO>": project.REPO,
        "<BRANCH>": cfg["branch"],
        "<BASE>": cfg["base_commit"],
        "<SOURCE-PDF>": cfg["source_pdf"],
        "<SOURCE-ID>": cfg["source_id"],
        "<SOURCE-CITE>": cfg["source_cite"],
        "<LEAN-FILES>": " ".join(cfg["lean_files"]),
        "<NAMESPACE>": cfg["namespace"],
        "<ROUNDS-DIR>": cfg["rounds_dir"],
        "<INDEX-FILE>": cfg.get("index_file") or next(
            (x for x in cfg["lean_files"] if x.endswith("Main.lean")),
            (cfg["lean_files"] or ["<the project's index file>"])[0]),
        "<NETWORK-RULE>": (
            "The source is UNPUBLISHED. Do not use WebFetch, web search, Loogle, or any other "
            "network access, and do not send any text from the source or the repository "
            "anywhere. Work only from the files on disk."
            if cfg.get("confidential") else
            "You may consult public references (Mathlib documentation, Loogle) but never send "
            "text from the source or the repository to any service."),
        "<LIBRARIES>": ", ".join(project.libraries(cfg)),
        "<GOAL-RESULTS>": (", ".join(cfg.get("goal_results") or [])
                           or "none recorded -- treat every result of the source as a goal"),
        "<ROUNDS-DIR-IN-AUDITS>": os.path.relpath(os.path.join(project.REPO, cfg["rounds_dir"]),
                                                  project.AUDITS),
        "<STANDING-DEFERS>": (
            "\n".join(
                f"  [{x['id']}] {x['item']}\n"
                f"      decided: {x.get('decided','?')}\n"
                f"      because: {x.get('reason','?')}\n"
                f"      revisit when: {x.get('revisit_when','NOT STATED — ask for one')}"
                for x in cfg.get("standing_defers", []))
            or "  (none recorded)"),
        "<BUILD-CMDS>": "\n".join(f"{c}; echo $?     # CHECK THE EXIT CODE. Never pipe it."
                                  for c in cfg["build_cmds"]),
    }
    if lane is not None:
        subs["<CALIBRATION>"] = cfg["calibration"].get(lane, "none recorded yet")
    for k, v in subs.items():
        if k in body:
            body = body.replace(k, v)
    # a config blank is `<<…>>` on one line; a shell heredoc in a prompt (`<<'REPORT'`) is not one
    if BLANK_RE.search(body):
        notes.append("! the filled prompt still contains a <<blank>> from "
                     f"{os.path.relpath(cfg['_path'], project.REPO)} — fill it there")
    return body, notes



def order_rounds(rounds, repo):
    """Round directories oldest-first, by the COMMIT TIME of the hash in their name.

    They used to be sorted by directory name, which is wrong whenever two rounds share a date:
    the ordering then falls through to the commit hash, which is a hex string with no relation to
    time. On 2026-09-29 that picked `2026-09-29-7759e702fdb` (committed 19:35) as newer than
    `2026-09-29-60672ca5567` (committed 21:02), because "7" > "6". The step-4 session was handed
    an already-adjudicated round and would have overwritten its ADOPTED.md; it noticed and
    stopped, which is the only reason this was caught rather than shipped.

    A hash that git cannot resolve (an amended or pruned commit) falls back to the directory's
    mtime, and is reported rather than silently reordered.
    """
    import subprocess
    def key(d):
        h = os.path.basename(d).split("-")[-1]
        r = subprocess.run(["git", "-C", repo, "show", "-s", "--format=%ct", h],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            # Same commit -> the directory created later is the later round (a full round cut
            # from the commit a diff round already audited).
            return (int(r.stdout.strip()), os.path.getmtime(d))
        return (int(os.path.getmtime(d)), os.path.getmtime(d))
    return sorted(rounds, key=key)


def pick_round(rounds, step, repo):
    """The round a given step means, plus a note explaining the choice.

    Step 4 adjudicates a round and writes its ADOPTED.md, so it wants the newest round that does
    NOT have one. Step 5 implements an ADOPTED.md, so it wants the newest that DOES. Defaulting
    both to "newest" is what let an already-adjudicated round be handed to step 4.
    """
    if not rounds:
        return None, "! no round directory found"
    ordered = order_rounds(rounds, repo)
    def has_adopted(d):
        return os.path.exists(os.path.join(d, "ADOPTED.md"))
    if step == 4:
        cand = [d for d in ordered if not has_adopted(d)]
        if cand:
            n = "  (newest round with no ADOPTED.md)" if len(ordered) > 1 else ""
            return os.path.basename(cand[-1]), n
        return os.path.basename(ordered[-1]), "! every round already has an ADOPTED.md — this one would be OVERWRITTEN. Pass --round, or check whether step 3 has run."
    if step == 5:
        cand = [d for d in ordered if has_adopted(d)]
        if cand:
            n = "  (newest round with an ADOPTED.md)" if len(ordered) > 1 else ""
            return os.path.basename(cand[-1]), n
        return os.path.basename(ordered[-1]), "! no round has an ADOPTED.md — step 4 has not run yet."
    n = f"  (newest of {len(ordered)} rounds, by commit time; --round NAME to pick another)" if len(ordered) > 1 else ""
    return os.path.basename(ordered[-1]), n


def resolve(body, repo, step, want_round=None, cfg=None, full=False):
    """Fill <DATE>-<HASH>, <HASH> and <PREV> from the repo. Returns (body, notes).

    A fresh conversation cannot know which round you mean, so leaving these as literal
    placeholders means either you substitute them by hand every time or the session guesses.
    Both are avoidable: the round directories are named <YYYY-MM-DD>-<commit> precisely so that
    the newest one is discoverable, and HEAD is a question git answers.

    Rounds are looked up in THIS PROJECT's rounds directory only. They used to be globbed from
    audits/ as a whole, which with two papers would hand one paper's round to the other's
    adjudicator.

    Whatever is substituted is announced on stderr. Nothing is filled silently -- a prompt that
    quietly points at the wrong round is worse than one that still says <HASH>.
    """
    notes = []
    if cfg is not None:
        body, n = fill_project(body, cfg)
        notes += n
        rounds = project.rounds(cfg)
        where = cfg["rounds_dir"]
    else:
        rounds, where = [], "audits"
    rnd = None
    if want_round:
        hit = [d for d in rounds if os.path.basename(d) == want_round]
        if not hit:
            notes.append(f"! no round directory named {want_round!r} in {where}")
        else:
            rnd = os.path.basename(hit[0])
    elif rounds:
        rnd, note = pick_round(rounds, step, repo)
        if note:
            notes.append(note)

    def git(*a):
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    if "<DATE>-<HASH>" in body:
        if step == 3:
            # Step 3 OPENS a round, so its directory is today + HEAD. An earlier version filled
            # the newest EXISTING round here, which from the second round on would have told the
            # lanes to overwrite the previous round's JSON.
            head = git("rev-parse", "--short=11", "HEAD")
            new = f"{datetime.date.today().isoformat()}-{'full-' if full else ''}{head}"
            body = body.replace("<DATE>-<HASH>", new)
            notes.append(f"  round  = {new}  (new round: today + {'full- + ' if full else ''}HEAD)")
            if cfg is not None and os.path.isdir(os.path.join(project.REPO, cfg["rounds_dir"], new)):
                notes.append(f"! round directory {new} ALREADY EXISTS. Starting step 3 again "
                             "would overwrite its record. Commit new work first, or (full "
                             "round) check whether it already ran.")
        elif rnd:
            body = body.replace("<DATE>-<HASH>", rnd); notes.append(f"  round  = {rnd}")
        else:
            notes.append("! no round directory found — <DATE>-<HASH> left as-is")

    if "<PREV>" in body:
        prev = os.path.basename(order_rounds(rounds, repo)[-1]).split("-")[-1] if rounds else None
        if prev:
            body = body.replace("<PREV>", prev)
            notes.append(f"  <PREV> = {prev}  (the last audited commit)")
        elif cfg is not None:
            body = body.replace("<PREV>", cfg["base_commit"])
            notes.append(f"  <PREV> = {cfg['base_commit']}  (no round yet: the branch base "
                         f"recorded in the project config)")
        else:
            notes.append("! no previous round — <PREV> left as-is; use the base of this branch")

    if "<HASH>" in body:
        # Decide by STEP, not by sniffing the text: step 3 opens a round on HEAD, while steps 5
        # and 6 act on the round already stored. An earlier version inferred this from whether
        # "<DATE>" was still present -- which it never was, having just been substituted above --
        # so step 3 silently resolved to the OLD round's commit and produced an empty diff. It
        # looked right only because HEAD happened to equal it.
        if step == 3:
            h = git("rev-parse", "--short=11", "HEAD")
            label = "HEAD, the commit to audit"
        else:
            h = rnd.split("-")[-1] if rnd else None
            label = "the commit this round was cut from"
        if h:
            body = body.replace("<HASH>", h)
            notes.append(f"  <HASH> = {h}  ({label})")
        else:
            notes.append("! could not resolve <HASH>")

    if "<PHASE-ZERO-FLAGS>" in body:
        # A statement round's implementer runs `phase0.py --statements` (sorry scan and axiom sweep
        # waived): the plain form is RED by construction there, and an implementer told to stop on
        # RED would be stuck (found by a test run).
        kind = None
        if rnd and cfg is not None:
            try:
                kind = json.load(open(os.path.join(project.REPO, cfg["rounds_dir"], rnd,
                                                   "TARGET.json"))).get("_meta", {}).get("kind")
            except (OSError, ValueError):
                kind = None
        if kind is None:
            notes.append("! could not read the round's kind from TARGET.json — "
                         "<PHASE-ZERO-FLAGS> left as-is")
        else:
            flags = " --statements" if kind == "statements" else ""
            body = body.replace("<PHASE-ZERO-FLAGS>", flags)
            notes.append(f"  phase0 flags = '{flags.strip()}'  (round kind: {kind})")

    if step == 3 and rounds and not full:
        prev = os.path.basename(order_rounds(rounds, repo)[-1]).split("-")[-1]
        head = git("rev-parse", "--short=11", "HEAD")
        if prev and head and prev == head:
            notes.append("! HEAD is the commit the last round already audited, so this would")
            notes.append("!   diff a commit against itself. Commit new work first, or pass")
            notes.append("!   --raw and set <PREV> to the range you actually mean.")

    left = re.findall(r"<[A-Z][A-Z -]*>", body)
    if left:
        notes.append(f"! still unfilled, you must supply: {', '.join(sorted(set(left)))}")
    return body, notes


def load(path):
    if not os.path.exists(path):
        print(f"FAIL: no protocol at {path}", file=sys.stderr)
        sys.exit(2)
    return open(path, encoding="utf-8").read()


def do_list(text):
    print("An audit round, in order. `prompt.py N` prints the block for step N.\n")
    w = max(len(s[1]) for s in STEPS)
    for n, where, what, sub in STEPS:
        ok = "  " if blocks_after(text, sub) else " !"
        print(f"{ok}{n}  {where:<{w}}  {what}")
    print("")
    print("  Steps 3 and 4 must be conversations that did NOT write the code:")
    print("  at 3 the author would choose the scope, at 4 the author would judge the findings.")
    print("  Step 4 opens by running tree_state.py --check: that is the gate that catches a")
    print("  lane that wrote into the repo, and it must pass before any finding is read.")


LEFTOVER = re.compile(r"<[A-Z][A-Z -]*>")
# Prepended to every lane prompt, so the rules every lane shares exist in one place.
COMMON_HEADING = "### Common rules for every lane"
# Prepended to the adjudicator's prompt and to the other subagent prompts below.
SUBAGENT_COMMON_HEADING = "### Common rules for every other subagent"
EXTRA_PROMPTS = {
    "informalizer": "### Informalizer prompt (blind)",
    "signoff-writer": "### Sign-off writer prompt",
    "escalate": "### Escalation check prompt",
    "fresh-reader": "### Fresh-reader prompt",
}



def probe_dir(verdict_file):
    """Where a lane keeps the probes its verdicts cite: next to its verdict file, in the round
    directory, so the adjudicator can re-run them and the adjudication commit keeps them."""
    return verdict_file[:-len(".json")] + ".probes"

def format_target(items):
    """{{TARGET}} as an explicit enumeration -- never a phrase (see "What {{TARGET}} is")."""
    return (f"the following {len(items)} item(s). Every one of them needs a verdict; an item you "
            f"omit is read as NotDoneYet.\n" + "\n".join(f"  - {i}" for i in items))


def render_extra(text, cfg, name, round_name=None):
    """(body, notes) for one of EXTRA_PROMPTS, with the subagent common rules on top."""
    common = blocks_after(text, SUBAGENT_COMMON_HEADING)
    body = blocks_after(text, EXTRA_PROMPTS[name])
    if common is None or body is None:
        return None, [f"! block not found for {name!r}"]
    body, notes = fill_project(common + "\n\n" + body, cfg)
    if "<ROUND-DIR>" in body:
        if not round_name:
            return None, [f"! {name} needs --round"]
        body = body.replace("<ROUND-DIR>", f"{cfg['rounds_dir']}/{round_name}")
    left = set(LEFTOVER.findall(body))
    if left:
        notes.append(f"! still unfilled: {', '.join(sorted(left))}")
    return body, notes


# What each checked document is, for whom, and which file the reader hashes (RUN.md "Fresh-reader
# check"). Fixed here so no operator wording reaches the reader.
FRESH_PURPOSE = {
    "signoff": ("the mathematician who must approve each Lean statement as a faithful rendering of "
                "the paper (or choose to let the agent approve), reading only this sheet"),
    "report": ("a mathematician who was not inside the run and must learn from it what is proved, "
               "under which assumptions, what is not formalized, and what is wrong in the paper"),
    "decisions": "the human who must answer every decision in it, without other context",
    "questions": ("the approver at Checkpoint B, who must answer each open question listed here "
                  "without other context"),
    "other": "the human it is addressed to, who must understand and act on it without other context",
}
# under a delegating involvement level (RUN.md, question 5c) nobody answers the decisions document:
# its reader checks what was decided on their behalf, and may reverse it
FRESH_PURPOSE_DELEGATED = ("the human on whose behalf every decision in it was taken (the involvement "
                           "level chosen at intake delegated them), who must be able to check each "
                           "decision and reverse it, without other context")


def render_fresh_reader(text, cfg, round_name, doc):
    """(body, notes, file name) for the fresh-reader prompt, or an error string. The document is
    resolved by readers.py, so the reader hashes exactly what the gate will hash."""
    import readers
    rd = os.path.normpath(os.path.join(project.REPO, cfg["rounds_dir"], round_name))
    rounds_abs = os.path.normpath(os.path.join(project.REPO, cfg["rounds_dir"]))
    if not os.path.isdir(rd):
        return f"no round directory {rd}"
    kind = "other" if doc.startswith("other:") else doc
    if kind not in FRESH_PURPOSE:
        return f"--doc must be one of signoff, questions, report, decisions, other:PATH (got {doc!r})"
    per_round = kind in ("signoff", "questions")
    try:
        key, srcs, shown = readers.resolve(cfg, doc, round_name if per_round else None)
    except readers.DocError as e:
        return str(e)
    if "fresh-reader" not in EXTRA_PROMPTS:
        return "the fresh-reader prompt is not registered"
    common = blocks_after(text, SUBAGENT_COMMON_HEADING)
    body = blocks_after(text, EXTRA_PROMPTS["fresh-reader"])
    extra = blocks_after(text, "Extras for `--doc signoff`") if kind == "signoff" else ""
    if common is None or body is None or extra is None:
        return "fresh-reader prompt blocks not found in AUDIT_PROTOCOL.md"
    rdir = readers.readers_dir(cfg)
    if not per_round:
        newest = readers.newest_round(cfg)
        if newest and round_name != newest:
            return f"--doc {kind} belongs to the newest round ({newest}), not {round_name}"
    n = readers.next_number(cfg, key)
    # the commit the document describes: the sheet says it; the report and decisions describe HEAD
    commit = None
    if kind == "signoff":
        try:
            commit = json.load(open(os.path.join(rd, "SIGNOFF.json"))).get("commit")
        except (OSError, ValueError):
            commit = None
    commit = commit or subprocess.run(["git", "-C", project.REPO, "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout.strip()
    if not commit:
        return "cannot tell which commit the document describes (no SIGNOFF.json commit, no HEAD)"
    import shlex
    # relative to the project root, the reader's working directory: the project's permission rule
    # `Bash(python3 audits/readers.py:*)` matches this form and no absolute path
    hash_cmd = (f"python3 audits/readers.py --project {shlex.quote(cfg['name'])} "
                f"--hash --doc {shlex.quote(doc)}" + (f" --round {shlex.quote(round_name)}" if per_round else ""))
    rfile = os.path.join(rdir, f"{key}-{n}.md")
    # the reader saves its record through readers.py --save (stdin): no file-writing tool needed,
    # and the script checks the format and the sha before it writes and commits the one file
    save_cmd = (f"python3 audits/readers.py --project {shlex.quote(cfg['name'])} "
                f"--save --doc {shlex.quote(doc)}" + (f" --round {shlex.quote(round_name)}" if per_round else ""))
    pdf = shown if shown.endswith(".pdf") else "none"
    md = srcs[0] if srcs[0].endswith(".md") else shown
    os.makedirs(rdir, exist_ok=True)
    body = body.replace("<DOC-EXTRA>", extra or "")
    for ph, v in (("<DOC-PATH>", md), ("<DOC-PDF>", pdf), ("<HASH-CMD>", hash_cmd),
                  ("<DOC-PURPOSE>", FRESH_PURPOSE_DELEGATED if kind == "decisions" and project.delegates(cfg)
                   else FRESH_PURPOSE[kind]), ("<COMMIT>", commit),
                  ("<AUDITS-DIR>", project.AUDITS), ("<SAVE-CMD>", save_cmd),
                  ("<READER-FILE>", rfile)):
        body = body.replace(ph, v)
    # absolute paths: the reader has no other context to resolve a relative one
    body = body.replace("<ROUND-DIR>", rd).replace("<ROUNDS-DIR>", rounds_abs)
    body, notes = fill_project(common + "\n\n" + body, cfg)
    left = set(LEFTOVER.findall(body))
    if left:
        notes.append(f"! still unfilled: {', '.join(sorted(left))}")
    return body, notes, f"fresh_reader_{key}_{n}.txt"


SPAWN_LINE = ("Read the file {path} and carry out the task it describes, exactly. That file is your "
              "complete instructions; this message adds nothing to it.")


def prompt_filename(label):
    """File name for a rendered prompt: `correspondence.txt`, `correspondence@2.txt`, …"""
    m = re.match(r"^(\S+) \(part (\d+) of \d+\)$", label)
    return f"{m.group(1)}@{m.group(2)}.txt" if m else f"{label}.txt"


def recorded_batch(pdir):
    """The --batch a round's lane prompts were written with (prompts/BATCH), or None."""
    p = os.path.join(pdir, "BATCH") if pdir else None
    try:
        return int(open(p).read().strip()) if p and os.path.exists(p) else None
    except ValueError:
        return None


def effective_batch(given, pdir):
    """--batch as given, else as recorded when the prompts were written."""
    return given if given is not None else recorded_batch(pdir)


def lane_prompt_files(text, cfg, round_name, batch=None):
    """{file name: prompt text} for every lane prompt of a round (batched as given)."""
    out = {}
    for lane, body, _ in render_lanes(text, cfg, round_name, None, batch, False):
        if body is not None:
            out[prompt_filename(lane)] = body + "\n"
    return out


def write_prompts(files, outdir):
    """Write rendered prompts to files; return [(path, spawn line)]. Prompts that reach a subagent
    are then reproducible files, and the spawn message is one fixed sentence -- nothing the
    launcher types can reach the subagent."""
    os.makedirs(outdir, exist_ok=True)
    res = []
    for name, body in sorted(files.items()):
        p = os.path.join(outdir, name)
        if name.startswith("fresh_reader_") and os.path.exists(p):
            # two --write calls before the first reader commits would give two readers one record
            # number; spawn the prompt already written (or delete it if it was never spawned)
            raise SystemExit(f"FAIL: {p} exists: a reader for that pass number was already prepared. "
                             f"Spawn it; if HEAD moved since it was written, delete it and write it again")
        open(p, "w", encoding="utf-8").write(body)
        res.append((p, SPAWN_LINE.format(path=p)))
    return res


def verify_prompts(files, outdir):
    """[problem] comparing written prompt files with a fresh rendering."""
    probs = []
    for name, body in sorted(files.items()):
        p = os.path.join(outdir, name)
        cur = open(p, encoding="utf-8").read() if os.path.exists(p) else None
        if cur is None:
            probs.append(f"missing prompt file {name}")
        elif cur != body:
            probs.append(f"prompt file {name} differs from what prompt.py renders now")
    return probs


def render_lanes(text, cfg, round_name=None, revote=None, batch=None, missing_only=False):
    """[(lane, body, notes)], placeholders filled.

    Without a round: every lane the project enables, with {{TARGET}} and <VERDICT-FILE> left for
    display. With a round: exactly the lanes in that round's TARGET.json (written by scope.py), with
    {{TARGET}} filled from it and <VERDICT-FILE> pointing at <round>/<lane>.json -- so the prompt
    that reaches a lane is reproducible from the files, and nobody fills anything in by hand.
    """
    out = []
    target = None
    if round_name is not None:
        rd = os.path.join(project.REPO, cfg["rounds_dir"], round_name)
        tp = os.path.join(rd, "TARGET.json")
        if not os.path.exists(tp):
            return [("-", None, [f"! no {os.path.relpath(tp, project.REPO)}: run "
                                 f"`python3 audits/scope.py --round {round_name}` first"])]
        # `_meta` records how the scope was made (scope.py); it is not a lane
        target = {k: v for k, v in json.load(open(tp, encoding="utf-8")).items()
                  if not k.startswith("_")}
        if revote is not None:
            # A re-vote: ONE fresh lane, ONE item, written under revote/ so it never mixes with
            # the round's own verdicts. Used when an adjudicator would REJECT a correctness Fail:
            # the rejection stands only if an independent second lane also fails to find it.
            rlane, ritem = revote
            if ritem not in target.get(rlane, []):
                return [("-", None, [f"! {ritem!r} was not in lane {rlane}'s scope this round"])]
            target = {rlane: [ritem]}
        unknown = set(target) - {l for l, _ in LANES}
        if unknown:
            return [("-", None, [f"! TARGET.json names unknown lanes: {sorted(unknown)}"])]
    for lane, sub in LANES:
        if target is not None:
            if lane not in target:
                continue
        elif lane not in cfg["lanes"]:
            continue
        body = blocks_after(text, sub)
        if body is None:
            out.append((lane, None, [f"! lane block not found under {sub!r}"]))
            continue
        common = blocks_after(text, COMMON_HEADING)
        if common is None:
            out.append((lane, None, [f"! common lane rules not found under {COMMON_HEADING!r}"]))
            continue
        body, notes = fill_project(common + "\n\n" + body, cfg, lane)
        allowed_left = {"<VERDICT-FILE>", "<PROBE-DIR>"}
        if target is not None:
            if not target[lane]:
                out.append((lane, None, [f"! TARGET.json gives lane {lane} an empty scope"]))
                continue
            items = target[lane]
            if batch and len(items) > batch and revote is None:
                # One subagent cannot examine hundreds of items carefully; it returns NotDoneYet for
                # most, honestly, and the round covers little. Split the scope into parts, each its
                # own subagent and its own verdict file <lane>@<k>.json; audit_coverage merges them.
                parts = [items[k:k + batch] for k in range(0, len(items), batch)]
                for k, part in enumerate(parts, 1):
                    if missing_only and os.path.exists(os.path.join(
                            project.REPO, cfg["rounds_dir"], round_name, f"{lane}@{k}.json")):
                        continue
                    b = body.replace("{{TARGET}}", format_target(part) + (
                        f"\n(This is part {k} of {len(parts)} of this lane's scope; other agents "
                        f"have the rest. Examine only these.)"))
                    vfk = os.path.join(project.REPO, cfg["rounds_dir"], round_name,
                                       f"{lane}@{k}.json")
                    b = b.replace("<VERDICT-FILE>", vfk).replace("<PROBE-DIR>", probe_dir(vfk))
                    left = set(LEFTOVER.findall(b))
                    out.append((f"{lane} (part {k} of {len(parts)})", b,
                                notes + ([f"! still unfilled: {', '.join(sorted(left))}"] if left else [])))
                continue
            if missing_only and revote is None and os.path.exists(os.path.join(
                    project.REPO, cfg["rounds_dir"], round_name, f"{lane}.json")):
                continue
            body = body.replace("{{TARGET}}", format_target(items))
            vf = os.path.join(project.REPO, cfg["rounds_dir"], round_name, f"{lane}.json")
            if revote is not None:
                slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", revote[1])[:80]
                vf = os.path.join(project.REPO, cfg["rounds_dir"], round_name, "revote",
                                  f"{lane}--{slug}.json")
            body = body.replace("<VERDICT-FILE>", vf).replace("<PROBE-DIR>", probe_dir(vf))
            allowed_left = set()
        left = set(LEFTOVER.findall(body)) - allowed_left
        if left:
            notes.append(f"! still unfilled: {', '.join(sorted(left))}")
        out.append((lane, body, notes))
    return out



def _round_selection_controls():
    """Regression controls for round selection. Returns [(name, passed)].

    Both guard the same incident: on 2026-09-29 two rounds shared a date, directory-name order
    fell through to the commit hash, and step 4 was handed the round that had already been
    adjudicated. Sorting by commit time fixed the cause; picking by ADOPTED.md presence makes the
    choice right even when the ordering is somehow wrong again.
    """
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    out = []
    try:
        # names chosen so that lexicographic order is the OPPOSITE of the intended order
        older, newer = os.path.join(tmp, "2026-01-01-ffff"), os.path.join(tmp, "2026-01-01-aaaa")
        os.makedirs(older); os.makedirs(newer)
        open(os.path.join(older, "ADOPTED.md"), "w").write("adjudicated already")
        rounds = [older, newer]   # neither hash resolves; falls back to mtime
        r4, _ = pick_round(rounds, 4, tmp)
        out.append(("step 4 skips a round that already has ADOPTED.md", r4 == "2026-01-01-aaaa"))
        r5, _ = pick_round(rounds, 5, tmp)
        out.append(("step 5 picks the round that has ADOPTED.md", r5 == "2026-01-01-ffff"))
        _, n4 = pick_round([older], 4, tmp)
        out.append(("step 4 warns when every round is adjudicated", "OVERWRITTEN" in (n4 or "")))
        _, n5 = pick_round([newer], 5, tmp)
        out.append(("step 5 warns when no round is adjudicated", "not run yet" in (n5 or "")))
        # <PREV> is the NEWEST earlier round's commit; names chosen so name order says otherwise
        rd = os.path.join(tmp, "rounds"); os.makedirs(rd)
        r_old, r_new = os.path.join(rd, "2026-03-02-1111111"), os.path.join(rd, "2026-03-01-2222222")
        os.makedirs(r_old); os.makedirs(r_new)
        os.utime(r_old, (1_000_000, 1_000_000)); os.utime(r_new, (2_000_000, 2_000_000))
        cfg_t = {"name": "t", "rounds_dir": rd, "base_commit": "base", "source_pdf": "s",
                 "source_id": "i", "source_cite": "c", "branch": "b", "lean_files": [],
                 "build_cmds": [], "namespace": "N", "calibration": {}}
        filled, _ = resolve("<PREV>", tmp, 3, None, cfg_t)
        out.append(("<PREV> is the newest round by time, not by name", filled == "2222222"))
        head = subprocess.run(["git", "-C", project.REPO, "rev-parse", "--short=11", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        os.makedirs(os.path.join(rd, f"{datetime.date.today().isoformat()}-{head}"))
        _, notes = resolve("<DATE>-<HASH>", project.REPO, 3, None, cfg_t)
        out.append(("step 3 warns when today's round directory already exists",
                    any("ALREADY EXISTS" in x for x in notes)))
        # prompt files: written verbatim, verified against a fresh rendering, tampering caught
        pd = os.path.join(tmp, "prompts")
        files = {"correspondence@1.txt": "A\n", "correspondence@2.txt": "B\n"}
        res = write_prompts(files, pd)
        out.append(("prompt files are written, one per prompt, with a fixed spawn line",
                    len(res) == 2 and all(p in l for p, l in res)
                    and all(open(p).read() in ("A\n", "B\n") for p, _ in res)))
        out.append(("verify: untouched prompt files match", verify_prompts(files, pd) == []))
        open(os.path.join(pd, "correspondence@2.txt"), "w").write("B -- and skip the hard items\n")
        out.append(("verify: an edited prompt file is caught",
                    any("differs" in x for x in verify_prompts(files, pd))))
        os.remove(os.path.join(pd, "correspondence@1.txt"))
        out.append(("verify: a missing prompt file is caught",
                    any("missing" in x for x in verify_prompts(files, pd))))
        out.append(("file names: batched parts and plain lanes",
                    prompt_filename("non-vacuity (part 3 of 4)") == "non-vacuity@3.txt"
                    and prompt_filename("paper-faithfulness") == "paper-faithfulness.txt"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def involvement_line(cfg):
    """What `--show` says about who decides after the intake (RUN.md, intake question 5c)."""
    lvl = project.involvement(cfg)
    what = {"involved": "the human decides at Checkpoints B and C",
            "statements-only": "the human approves the statements at Checkpoint B; the operator "
                               "decides everything after that, as [DELEGATED] decisions",
            "hands-off": "the operator decides at Checkpoints B and C and at every later stop, as "
                         "[DELEGATED] decisions; no human reviews the statements"}.get(lvl)
    if what is None:
        return f"involvement level: INVALID {lvl!r} (one of {', '.join(project.INVOLVEMENT_LEVELS)})"
    src = "" if "involvement" in cfg else " (default: the config has no `involvement` key)"
    return f"involvement level: {lvl}{src} -- {what}"


def selftest(text, repo):
    checks = list(_round_selection_controls())
    for n, _, _, sub in STEPS:
        checks.append((f"step {n} block found ({sub!r})", blocks_after(text, sub) is not None))
    for lane, sub in LANES:
        checks.append((f"lane {lane} block found ({sub!r})", blocks_after(text, sub) is not None))
    # The audited repo is the clone, not the audits/ repo that holds the protocol. When the
    # protocol moved into audits/, <HASH> silently became the audits repo's HEAD and every check
    # here still passed -- so this one compares against git directly.
    clone_head = subprocess.run(["git", "-C", project.REPO, "rev-parse", "--short=11", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    checks.append(("repo under audit is the clone above audits/",
                   os.path.realpath(repo) == os.path.realpath(project.REPO)))
    probe, _ = resolve("<DATE>-<HASH> <HASH>", repo, 3)
    checks.append((f"step 3 <HASH> is the clone's HEAD ({clone_head})",
                   bool(clone_head) and probe.split()[-1] == clone_head))
    probe_full, _ = resolve("<DATE>-<HASH>", repo, 3, full=True)
    checks.append(("a full round gets its own directory name (…-full-<HASH>)",
                   probe_full.endswith(f"-full-{clone_head}") and project.ROUND_RE.match(probe_full)
                   and project.round_commit(probe_full) == clone_head))
    checks.append(("a diff round's name is not mistaken for a full round",
                   not project.is_full_round(probe.split()[0])))
    # negative control: a heading that is not in the file must resolve to nothing
    checks.append(("absent heading resolves to nothing",
                   blocks_after(text, "### A heading that does not exist") is None))
    # every project renders every step and lane with no UNKNOWN placeholder left. <<blanks>> are
    # reported, not failed: an unfilled calibration line is a fact about setup, not a broken script.
    projects = project.all_projects()
    # a fresh install has no project until the first intake (RUN.md, Stage 1, step 3); that is not
    # a broken script. A projects/ directory with files that are not configs still fails below.
    if not projects:
        print("  note  no project config yet (expected before the first intake)")
    checks.append(("at least one project config, or none at all (fresh install)",
                   bool(projects) or not glob.glob(os.path.join(project.PROJECTS, "*"))))
    # an earlier run's source file lives on the machine that ran it; only the project on the
    # checked-out branch (the run in progress) must have its source here
    branch = project.git("branch", "--show-current")
    for name, cfg in projects.items():
        # a `~/…` work_dir is judged against $HOME, which is the test machine's, not the config's:
        # with HOME under /tmp (a scratch install) the config itself is still fine
        # likewise a relative work_dir (the default, inside the project) is judged against where the
        # project is: a scratch checkout under /tmp says nothing about the config
        home_tmp = project.is_temporary(os.path.expanduser("~"))
        repo_tmp = project.is_temporary(project.REPO)
        wd_ = str(cfg.get("work_dir", ""))
        env_tmp = (home_tmp and wd_.startswith("~")) or (repo_tmp and not wd_.startswith(("~", "/")))
        hard = [p for p in project.problems(cfg) if p.startswith("!")
                and not (p.startswith("! source_pdf does not exist") and cfg.get("branch") != branch)
                and not (env_tmp and p.startswith("! work_dir is under a temporary directory"))]
        checks.append((f"project {name}: no hard config errors {hard or ''}", not hard))
        for n, _, _, sub in STEPS:
            body = blocks_after(text, sub)
            if body is None:
                continue
            filled, _ = resolve(body, repo, n, None, cfg)
            # <PHASE-ZERO-FLAGS> needs a round's TARGET.json; none exists here (see the controls)
            left = set(LEFTOVER.findall(filled)) - {"<HASH>", "<PREV>", "<DATE>",
                                                    "<PHASE-ZERO-FLAGS>"}
            checks.append((f"project {name}: step {n} leaves no unknown placeholder {left or ''}",
                           not left))
        for lane, body, notes in render_lanes(text, cfg):
            checks.append((f"project {name}: lane {lane} renders",
                           body is not None and not any(n.startswith("! still") for n in notes)))
        checks.append((f"project {name}: the network rule is filled in every lane prompt",
                       all(b is not None and "<NETWORK-RULE>" not in b and ("never send" in b or "UNPUBLISHED" in b)
                           for _, b, _ in render_lanes(text, cfg))))
        checks.append((f"project {name}: every lane prompt carries the common rules",
                       all(b is not None and "COMMON RULES FOR EVERY AUDIT LANE" in b
                           for _, b, _ in render_lanes(text, cfg))))
        for nm in EXTRA_PROMPTS:
            if nm == "fresh-reader":   # needs --doc; tested on its own below
                continue
            b, nt = render_extra(text, cfg, nm, "2026-01-01-abcdef1")
            checks.append((f"project {name}: subagent prompt {nm} renders with the common rules, nothing unfilled",
                           b is not None and "COMMON RULES FOR EVERY SUBAGENT" in b
                           and not any(x.startswith("! still") for x in nt)
                           and "<NETWORK-RULE>" not in b and ("never send" in b or "UNPUBLISHED" in b)))
        b, nt = render_extra(text, cfg, "informalizer", None)
        checks.append((f"project {name}: the informalizer refuses to render without a round", b is None))
        b4, _ = resolve(blocks_after(text, "Step 4 — adjudicate"), repo, 4, None, cfg)
        checks.append((f"project {name}: step 4 names the goal results", "<GOAL-RESULTS>" not in b4))
        checks.append((f"project {name}: step 4 tells the adjudicator to re-run cited probes",
                       "re-run that probe" in b4 and "voids" in b4))
        checks.append((f"project {name}: step 4 says statement-round lane gaps are not UNCOVERED",
                       "is NOT an UNCOVERED row" in b4))
        b3 = blocks_after(text, "Open a new conversation in")
        checks.append((f"project {name}: step 3 has exactly one scope.py command for --full to rewrite",
                       b3 is not None and b3.count("python3 audits/scope.py --round <DATE>-<HASH>") == 1))
        # every lane prompt names its own probe directory, inside the round, next to its verdict
        # file, and allows reading its own prompt file (the rule text and the paths agree)
        rl = render_lanes(text, cfg)
        checks.append((f"project {name}: lane prompts without a round keep <PROBE-DIR> for the round",
                       all(b is None or "<VERDICT-FILE>" not in b or "<PROBE-DIR>" in b
                           for _, b, _ in rl)))
        checks.append((f"project {name}: every lane prompt allows its own prompt file and probe dir",
                       all(b is not None and "the\n   prompt file you were told to read" in b
                           and "your own probe\n   directory" in b for _, b, _ in rl)))
        # with a round: <PROBE-DIR> is filled, inside the round, next to the verdict file (also
        # for batched parts), and step 5 picks phase0's flags from the round's kind
        import tempfile, shutil
        tmpr = tempfile.mkdtemp()
        try:
            cfg_r = dict(cfg, rounds_dir=tmpr)
            rn = "2026-01-01-full-abcdef1"
            os.makedirs(os.path.join(tmpr, rn))
            lanes_r = [l for l, _, _ in rl]
            json.dump(dict({l: [f"I{j}" for j in range(3)] for l in lanes_r},
                           _meta={"kind": "statements"}),
                      open(os.path.join(tmpr, rn, "TARGET.json"), "w"))
            _bd = tempfile.mkdtemp()
            open(os.path.join(_bd, "BATCH"), "w").write("2\n")
            checks.append(("a batched round's --batch is read back for --verify-written (F-I14)",
                           recorded_batch(_bd) == 2 and recorded_batch(tempfile.mkdtemp()) is None
                           and effective_batch(None, _bd) == 2 and effective_batch(5, _bd) == 5))
            got = render_lanes(text, cfg_r, rn, batch=2)
            vre = re.compile(re.escape(os.path.join(tmpr, rn)) + r"/[^\s/]+\.json")
            pre = re.compile(re.escape(os.path.join(tmpr, rn)) + r"/[^\s/]+\.probes")
            pairs = []
            for _, b, _ in got:
                vfs = set(vre.findall(b or "")) - {os.path.join(tmpr, rn, "TARGET.json")}
                pds = set(pre.findall(b or ""))
                pairs.append((vfs, pds))
            checks.append((f"project {name}: with a round, each prompt's probe dir is ITS OWN "
                           f"verdict file with .probes for .json, inside the round",
                           bool(got) and all(len(v) == 1 and pds == {next(iter(v))[:-5] + ".probes"}
                                             for v, pds in pairs)))
            checks.append((f"project {name}: no two prompts (batched parts included) share a probe dir",
                           len({next(iter(p)) for _, p in pairs if p}) == len(pairs)))
            s5 = blocks_after(text, STEPS[[s[0] for s in STEPS].index(5)][3])
            f5, _ = resolve(s5, repo, 5, rn, cfg_r)
            checks.append((f"project {name}: step 5 in a statement round runs phase0 --statements",
                           "phase0.py --statements" in f5 and "<PHASE-ZERO-FLAGS>" not in f5))
            json.dump({"_meta": {"kind": "diff"}}, open(os.path.join(tmpr, rn, "TARGET.json"), "w"))
            f5d, _ = resolve(s5, repo, 5, rn, cfg_r)
            checks.append((f"project {name}: step 5 in a proof round runs plain phase0",
                           "phase0.py   --" in f5d and "--statements" not in f5d))
        finally:
            shutil.rmtree(tmpr, ignore_errors=True)
        # the source path must actually appear in lane C: the point of the whole change
        c = [b for l, b, _ in render_lanes(text, cfg) if l == "paper-faithfulness"]
        checks.append((f"project {name}: lane C names its own PDF",
                       bool(c) and c[0] is not None and cfg["source_pdf"] in c[0]))
        checks.append((f"project {name}: lane C compares every definition with the source word by word",
                       bool(c) and c[0] is not None and "DEFINITIONS PASS" in c[0]
                       and "WORD BY WORD" in c[0]))
    # the pre-approval check exists and RUN.md tells the operator to run it before Checkpoint B
    run_md = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "RUN.md"),
                  encoding="utf-8").read()
    checks.append(("the fresh-reader check is a prompt and a RUN.md step (for the sheet too)",
                   "fresh-reader" in EXTRA_PROMPTS
                   and re.search(r"--prompt\s+fresh-reader\s+--doc\s+signoff", run_md) is not None
                   and re.search(r"--prompt\s+fresh-reader", run_md.split("### Fresh-reader check")[-1]) is not None))
    checks.append(("RUN.md asks the involvement question at intake and lists the stops that remain at every level",
                   "How involved do you want to be after the intake and Checkpoint A" in run_md
                   and "You cannot change\n     > this choice once the run starts" in run_md
                   and "**Stops that remain at every level.**" in run_md
                   and all(f"`{lvl}`" in run_md for lvl in project.INVOLVEMENT_LEVELS)))
    # pre-merge review P1/P2: every lane spawn is sealed from the child's own result, and
    # adjudicators never spawn lanes (an unauthenticated re-vote bypassed attribution)
    b3 = blocks_after(text, "Open a new conversation in") or ""
    b4 = text.split("REJECTING a Fail from correspondence", 1)[-1][:1500]
    checks.append(("step 3 block seals each lane from its own LANE_COMPLETION, then runs lanecheck",
                   "lane_auth.py seal --verdict" in b3 and "LANE_COMPLETION" in b3
                   and "--agent-id" in b3 and "lanecheck.py --round" in b3
                   and "SAME printed line" in b3))
    checks.append(("RUN.md seals lanes in Stage 2 step 3 and Stage 4 step 3 and step 5",
                   run_md.count("lane_auth.py seal") >= 3 and "**Seal and check the lanes.**" in run_md
                   and "**As each lane returns,\n   seal it**" in run_md))
    checks.append(("the adjudicator never spawns a re-vote lane; it records REVOTE NEEDED",
                   "you never spawn a lane yourself" in b4 and "--revote" not in b4
                   and '"REVOTE NEEDED"' in b4))
    # integration 0.2: the bytecode check, and the Codex rules that must hold at every level
    checks.append(("RUN.md: Stage 1 checks PYTHONDONTWRITEBYTECODE for Claude Code and Codex",
                   "0. **No bytecode.**" in run_md and "`.claude/settings.json`" in run_md
                   and "[shell_environment_policy.set]" in run_md))
    checks.append(("RUN.md: Codex approval prompts are not checkpoints; delegated runs do not wait at them",
                   "**Command approval prompts are not checkpoints.**" in run_md
                   and "A delegating level\n  must not wait at them" in run_md
                   and "the ONLY sanctioned sandbox change" in run_md))
    checks.append(("RUN.md: tokens and seals apply at every involvement level",
                   "Token commitments, seals and lanecheck apply at every involvement level" in run_md))
    checks.append(("RUN.md: Codex parent waits with a long blocking wait, not short polls",
                   "**Waiting for children.** Wait with the blocking `wait_agent` tool" in run_md
                   and "at most once every 10\n  minutes" in run_md))
    # the fresh-reader prompt is fully filled, names its report file, hashes the right document,
    # and carries the sheet extras only for the sheet
    import tempfile, shutil
    if projects:
        name0, cfg0 = sorted(projects.items())[0]
        tmpf = tempfile.mkdtemp(prefix="fr-")
        try:
            cfg_f = dict(cfg0, rounds_dir=os.path.relpath(tmpf, project.REPO))
            R = "2026-01-01-abc1234"
            os.makedirs(os.path.join(tmpf, R)); os.makedirs(os.path.join(tmpf, "readers"))
            open(os.path.join(tmpf, "readers", "decisions-1.md"), "w").write("x")
            json.dump({"commit": "sheetcommit123"}, open(os.path.join(tmpf, R, "SIGNOFF.json"), "w"))
            for f in ("SIGNOFF.md", "SIGNOFF.tex"):
                open(os.path.join(tmpf, R, f), "w").write("x")
            open(os.path.join(tmpf, f"QUESTIONS-B-{R}.md"), "w").write("q")
            open(os.path.join(tmpf, "DECISIONS.md"), "w").write(f"<!-- decisions-round: {R} -->\nx")
            open(os.path.join(tmpf, "readers", f"decisions-{R}-1.md"), "w").write("x")
            res = {d: render_fresh_reader(text, cfg_f, R, d) for d in ("signoff", "decisions", "questions")}
            ok_all = all(not isinstance(v, str) and not any(n.startswith("!") for n in v[1])
                         for v in res.values())
            checks.append(("fresh-reader: renders with nothing left unfilled", ok_all))
            if ok_all:
                bs, bd = res["signoff"][0], res["decisions"][0]
                checks.append(("fresh-reader: the next report file is numbered after the existing ones (one history per project)",
                               res["decisions"][2] == f"fresh_reader_decisions-{R}_2.txt"
                               and os.path.join(tmpf, "readers", f"decisions-{R}-2.md") in bd))
                checks.append(("fresh-reader: the reader saves its own record through readers.py --save",
                               "--save --doc decisions" in bd and f"--save --doc questions --round {R}" in res["questions"][0]
                               and "<SAVE-CMD>" not in bd))
                import shlex as _sh
                checks.append(("fresh-reader: every path and argument in the reader's commands is shell-quoted",
                               f"python3 audits/readers.py --project {_sh.quote(cfg_f['name'])} --save" in bd
                               and f"python3 audits/readers.py --project {_sh.quote(cfg_f['name'])}" in bd
                               and "python3 /" not in bd))
                checks.append(("fresh-reader: the sheet gets the former pre-approval checks, others do not",
                               "Nothing known is hidden" in bs and "Nothing known is hidden" not in bd))
                checks.append(("fresh-reader: the reader runs the gate's own hash command",
                               "readers.py" in bs and "--project" in bs and f"--hash --doc signoff --round {R}" in bs
                               and "--hash --doc decisions" in bd))
                checks.append(("fresh-reader: the reader is told not to open earlier readers' records",
                               "Do NOT open" in bd and "/readers/" in bd))
                checks.append(("fresh-reader: the sheet is checked at the commit the sheet states",
                               "at commit sheetcommit123" in bs))
                rh = render_fresh_reader(text, dict(cfg_f, involvement="hands-off", involvement_answer="c"), R, "decisions")
                checks.append(("fresh-reader: under a delegating level the decisions reader checks decisions taken on their behalf",
                               not isinstance(rh, str) and FRESH_PURPOSE_DELEGATED in rh[0]
                               and FRESH_PURPOSE_DELEGATED not in bd and FRESH_PURPOSE["decisions"] in bd))
                checks.append(("fresh-reader: findings use the fixed markers the gate counts",
                               "`- BLOCKING:`" in bd and "`- NOT BLOCKING:`" in bd))
                checks.append(("fresh-reader: the common rules come first (memory is not evidence)",
                               bd.index("Background in your context") > 0 and blocks_after(text, SUBAGENT_COMMON_HEADING)[:60] in bd))
            if ok_all:
                outd = os.path.join(tmpf, "pr"); write_prompts({res["decisions"][2]: "x"}, outd)
                try:
                    write_prompts({res["decisions"][2]: "y"}, outd); refused = False
                except SystemExit:
                    refused = True
                checks.append(("fresh-reader: a prompt already prepared for that pass number is not overwritten", refused))
            checks.append(("fresh-reader: an unknown --doc is refused",
                           isinstance(render_fresh_reader(text, cfg_f, R, "notes"), str)))
            checks.append(("fresh-reader: a missing round or document is refused",
                           isinstance(render_fresh_reader(text, cfg_f, "NOPE", "decisions"), str)
                           and isinstance(render_fresh_reader(text, cfg_f, R, "report"), str)))
        finally:
            shutil.rmtree(tmpf, ignore_errors=True)
    checks.append(("an unfilled <<blank>> is caught; a shell heredoc (<<'REPORT') is not a blank",
                   BLANK_RE.search("path: <<path to the paper, e.g. ~/x/<name>.tex>>") is not None
                   and BLANK_RE.search("cmd <<'REPORT'\n  report\n  REPORT") is None))
    if projects:
        _c = dict(sorted(projects.items())[0][1], source_pdf="<<path to the paper>>")
        _b, _n = fill_project("Source: <SOURCE-PDF>. Save with: cmd <<'REPORT'", _c)
        checks.append(("a prompt filled from a config with an unfilled blank is flagged; the heredoc alone is not",
                       any("<<blank>>" in n for n in _n)
                       and not any("<<blank>>" in n for n in fill_project("cmd <<'REPORT'", sorted(projects.items())[0][1])[1])))
    # negative control: a config missing a field must be reported as a hard error
    fake = {"name": "negctl"}
    checks.append(("config missing fields is a hard error",
                   any(p.startswith("! missing") for p in project.problems(fake))))
    checks.append(("a work_dir under /tmp is a hard config error (drafts there were lost once)",
                   any(p.startswith("! work_dir") for p in project.problems(dict(fake, work_dir="/tmp/w")))
                   and (project.is_temporary(project.REPO) or not any(p.startswith("! work_dir") for p in
                        project.problems(dict(fake, work_dir=".formalization-work/x"))))))
    checks.append(("an invalid involvement value is a hard config error; the three levels are not",
                   any(p.startswith("! involvement") for p in project.problems(dict(fake, involvement="hands-free", involvement_answer="x")))
                   and not any(p.startswith("! involvement") for lvl in project.INVOLVEMENT_LEVELS
                               for p in project.problems(dict(fake, involvement=lvl, involvement_answer="(c)")))))
    checks.append(("a delegating level without its verbatim intake answer is a hard config error",
                   any(p.startswith("! involvement") for p in project.problems(dict(fake, involvement="hands-off")))
                   and not any(p.startswith("! involvement") for p in project.problems(fake))))
    checks.append(("--show names the involvement level, the default when the key is absent, and an invalid one",
                   "involved (default" in involvement_line(fake)
                   and "hands-off --" in involvement_line(dict(fake, involvement="hands-off"))
                   and "INVALID" in involvement_line(dict(fake, involvement="x"))))
    # negative control: another paper's PDF must not leak into this paper's lanes
    if len(projects) >= 2:
        (n1, c1), (n2, c2) = list(projects.items())[:2]
        leak = any(b and c2["source_pdf"] in b for _, b, _ in render_lanes(text, c1))
        checks.append((f"project {n1}'s lanes do not name {n2}'s PDF", not leak))
    ok = True
    for name, passed in checks:
        print(f"  {'ok  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print("selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", nargs="?", type=int, choices=[s[0] for s in STEPS])
    ap.add_argument("--file", default=DEFAULT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--lanes", action="store_true", help="print every enabled lane prompt")
    ap.add_argument("--show", action="store_true", help="print the project config")
    ap.add_argument("--project", help="project name (audits/projects/NAME.json)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--round", help="round directory name; default is the newest")
    ap.add_argument("--raw", action="store_true", help="do not fill placeholders")
    ap.add_argument("--write", action="store_true",
                    help="with --round: write the prompts to <round>/prompts/ and print spawn lines")
    ap.add_argument("--verify-written", action="store_true",
                    help="with --lanes --round: check <round>/prompts/ against a fresh rendering")
    ap.add_argument("--missing", action="store_true",
                    help="with --lanes --round: only the prompts whose verdict file is missing")
    ap.add_argument("--prompt", choices=sorted(EXTRA_PROMPTS),
                    help="print one of the non-lane subagent prompts, filled")
    ap.add_argument("--doc", metavar="signoff|questions|report|decisions|other:PATH",
                    help="with --prompt fresh-reader: the document to check")
    ap.add_argument("--batch", type=int, metavar="N",
                    help="with --lanes --round: split any lane with more than N items into parts")
    ap.add_argument("--revote", metavar="LANE:ITEM",
                    help="with --lanes --round: one fresh lane prompt for one item (re-vote)")
    ap.add_argument("--full", action="store_true",
                    help="step 3: scope the whole namespace instead of the diff")
    a = ap.parse_args()
    text = load(a.file)
    # The repository being AUDITED: the clone above audits/. It used to be "the directory holding
    # AUDIT_PROTOCOL.md", which was the same place until the protocol moved into the audits/ repo
    # -- after which every <HASH> silently resolved to the audits repo's HEAD. selftest now checks.
    repo = project.REPO

    if a.selftest:
        return selftest(text, repo)

    if a.list or (a.step is None and not a.lanes and not a.show and not a.prompt):
        do_list(text)
        return 0

    cfg = None
    if not a.raw:
        try:
            cfg, why = project.select(a.project)
        except project.SelectionError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 2
        print(f"# project {cfg['name']} — {cfg.get('title', '')}  (selected by {why})",
              file=sys.stderr)
        for p in project.problems(cfg):
            print(f"# {p}", file=sys.stderr)

    if a.show:
        for k, v in cfg.items():
            if not k.startswith("_"):
                print(f"{k}: {v}")
        print(involvement_line(cfg))
        return 0

    pdir = (os.path.join(project.REPO, cfg["rounds_dir"], a.round, "prompts")
            if (cfg is not None and a.round) else None)
    if (a.write or a.verify_written) and pdir is None:
        print("FAIL: --write / --verify-written need --round", file=sys.stderr)
        return 2

    if a.prompt == "fresh-reader":
        if not (a.round and a.doc):
            print("FAIL: --prompt fresh-reader needs --round and --doc", file=sys.stderr)
            return 2
        res = render_fresh_reader(text, cfg, a.round, a.doc)
        if isinstance(res, str):
            print(f"FAIL: {res}", file=sys.stderr)
            return 2
        body, notes, fname = res
        for note in notes:
            print(f"# {note}", file=sys.stderr)
        if any(n.startswith("!") for n in notes):
            return 2
        if a.write:
            for p, line in write_prompts({fname: body + "\n"}, pdir):
                print(f"{p}\n  spawn with: {line}")
            return 0
        print(body)
        return 0

    if a.prompt:
        body, notes = render_extra(text, cfg, a.prompt, a.round)
        for note in notes:
            print(f"# {note}", file=sys.stderr)
        if body is None:
            return 2
        if a.write:
            for p, line in write_prompts({f"{a.prompt}.txt": body + "\n"}, pdir):
                print(f"{p}\n  spawn with: {line}")
            return 0
        print(body)
        return 0

    if a.lanes and a.verify_written:
        # a batched round recorded its --batch when the prompts were written: verifying without
        # it compared against unbatched prompts and reported a false MISMATCH (a test run, F-I14)
        batch = effective_batch(a.batch, pdir)
        probs = verify_prompts(lane_prompt_files(text, cfg, a.round, batch), pdir)
        for p in probs:
            print(f"MISMATCH  {p}")
        print(f"prompt files: {'OK' if not probs else 'MISMATCH'}")
        return 1 if probs else 0

    if a.lanes:
        rc = 0
        rv = None
        if a.revote:
            if not a.round or ":" not in a.revote:
                print("FAIL: --revote LANE:ITEM needs --round", file=sys.stderr); return 2
            rv = tuple(a.revote.split(":", 1))
        written = {}
        for lane, body, notes in render_lanes(text, cfg, a.round, rv, a.batch, a.missing):
            for note in notes:
                print(f"# [{lane}] {note}", file=sys.stderr)
            if body is None:
                rc = 2
                continue
            if a.write:
                name = prompt_filename(lane) if rv is None else f"revote-{prompt_filename(lane)}"
                written[name] = body + "\n"
                continue
            print(f"===== lane: {lane} =====")
            print(body)
            print()
        if a.write:
            if a.batch is not None and rv is None:
                os.makedirs(pdir, exist_ok=True)
                open(os.path.join(pdir, "BATCH"), "w").write(f"{a.batch}\n")
            import lane_auth
            for p, line in write_prompts(written, pdir):
                try:
                    line = lane_auth.issue_prompt(p)
                except (OSError, ValueError) as e:
                    print(f"STOP: {e}", file=sys.stderr)
                    return 2
                print(f"{p}\n  spawn (subagent_type auditor; Codex: agent_type formalize_auditor, fork_turns none) with: {line}")
        return rc

    n, where, what, sub = next(s for s in STEPS if s[0] == a.step)
    body = blocks_after(text, sub)
    if body is None:
        print(f"FAIL: step {n}'s block not found — the heading {sub!r} has moved or changed. "
              f"Fix STEPS in this script, or the heading.", file=sys.stderr)
        return 2
    if a.full and n != 3:
        print("--full applies to step 3 only (it changes what gets audited, not how)",
              file=sys.stderr)
        return 2
    if a.full:
        # A full-scope round is step 3 with a different scope: scope.py --full lists every
        # declaration and every index row. Diff-scoped rounds never reach code that has stopped
        # changing, so the backlog only shrinks when a round is pointed at it deliberately.
        before = body
        body = body.replace("python3 audits/scope.py --round <DATE>-<HASH>",
                            "python3 audits/scope.py --full --round <DATE>-<HASH>")
        if body == before or "scope.py --full" not in body:
            print("FAIL: --full could not rewrite step 3's scope command; the block changed. "
                  "Fix the replacement in prompt.py.", file=sys.stderr)
            return 2
    if n == 4 and a.write and not a.raw:
        common = blocks_after(text, SUBAGENT_COMMON_HEADING)
        body4, notes4 = resolve(common + "\n\n" + body, repo, 4, a.round, cfg)
        for note in notes4:
            print(f"# {note}", file=sys.stderr)
        for p, line in write_prompts({"adjudicator.txt": body4 + "\n"}, pdir):
            print(f"{p}\n  spawn (general-purpose) with: {line}")
        return 0
    if n == 4:
        common = blocks_after(text, SUBAGENT_COMMON_HEADING)
        if common is None:
            print(f"FAIL: {SUBAGENT_COMMON_HEADING!r} not found", file=sys.stderr)
            return 2
        body = common + "\n\n" + body
    notes = []
    if not a.raw:
        body, notes = resolve(body, repo, n, a.round, cfg, full=a.full)
    print(f"# step {n} — open: {where}\n# {what}", file=sys.stderr)
    for note in notes:
        print(f"# {note}", file=sys.stderr)
    print("", file=sys.stderr)
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())

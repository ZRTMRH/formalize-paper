#!/usr/bin/env python3
"""Check a round's lanes after they return and before adjudication (RUN.md Stage 4, step 3).

WHY THIS EXISTS.  In a test run, rules written into the lane prompts were broken anyway:
lanes read earlier rounds' records four times (one aborted itself on noticing), left `until !
pgrep -f ...` loops running five times (the pattern matches its own command line, so the loop
never exits), wrote files into the repository root, and cited probe files that were never
written. A rule in a prompt is advice; this script makes each of those a mechanical failure the
operator must clear (re-run the lane, remove the stray files, kill the loop) before the
adjudicator reads the verdicts.

  python3 audits/lanecheck.py --round R [--project NAME] [--kill]
  python3 audits/lanecheck.py --selftest

Checks, per lane verdict file `<round>/<lane>.json` (and `<lane>@<n>.json`):
  1. independence: the file cites another round (a `YYYY-MM-DD-<hash>` name other than this
     round's) or a record file lanes may not read (ADOPTED.md, RUN_LOG.md, TARGET.json,
     SIGNOFF.*, REPORT.*, SKIPPED.md, DEVIATIONS.md, PAPER_DEFECTS.md, VACUOUS.md, readers/);
  2. evidence: every `<lane>.probes/...` path the file cites exists;
and for the round as a whole:
  3. stray files: untracked files in the Lean repository outside the audits directory;
  4. stray processes: this user's processes running a polling loop (`until`/`while` with `sleep`
     or `pgrep`); `--kill` ends them.
Exit 1 if anything is found.
"""
import sys
sys.dont_write_bytecode = True
import argparse, glob, json, os, re, shutil, subprocess, tempfile, time

import project

ROUND_NAME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40}\b")
RECORD_RE = re.compile(r"\b(ADOPTED\.md|RUN_LOG\.md|TARGET\.json|SIGNOFF\.(?:md|json|pdf|tex)|REPORT\.(?:md|pdf|tex)"
                       r"|SKIPPED\.md|DEVIATIONS\.md|PAPER_DEFECTS\.md|VACUOUS\.md|AUTHOR_NOTES\.md|OUTCOMES\.md"
                       r"|readers/)", re.I)
# a probe path ends at its file extension (lanes sometimes run paths together without a space)
PROBE_RE = re.compile(r"([A-Za-z0-9_@.-]+\.probes/[^\s\"'`,;()]+?\.(?:lean|py|txt|out|log|json|sh|md)(?:\.(?:txt|log|out))?)(?!\w)(?!\.\w)")
# a shell running a polling loop -- the command line of `bash -c 'until ! pgrep -f X; do sleep 5; done'`
LOOP_RE = re.compile(r"^(?:\S*/)?(?:ba|z|da)?sh\b.*\b(?:until|while)\b.*\b(?:sleep|pgrep)\b")


def lane_files(round_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(round_dir, "*.json")) + glob.glob(os.path.join(round_dir, "revote", "*.json"))):
        b = os.path.basename(p)
        if b in ("TARGET.json", "FINGERPRINTS.json", "SIGNOFF.json", "INFORMAL.json") or b.startswith("APPROVED"):
            continue
        out.append(p)
    return out


def check_lane(path, round_dir):
    """[problem] for one lane verdict file."""
    probs, name = [], os.path.basename(path)
    text = open(path, encoding="utf-8", errors="replace").read()
    this = os.path.basename(round_dir)
    others = {r for r in ROUND_NAME_RE.findall(text) if r != this}
    # other rounds named by their commit hash alone (round 0b23c87), from the rounds next to this one
    for sib in os.listdir(os.path.dirname(round_dir)):
        h = sib.rsplit("-", 1)[-1]
        if sib != this and project.ROUND_RE.match(sib) and re.search(rf"\b{re.escape(h[:7])}[0-9a-f]*\b", text) \
                and h[:7] != this.rsplit("-", 1)[-1][:7]:
            others.add(sib)
    others = sorted(others)
    if others:
        probs.append(f"{name}: cites other rounds ({', '.join(others[:3])}): the lane read the audit record; "
                     f"re-run it")
    rec = sorted(set(RECORD_RE.findall(text)))
    if rec:
        probs.append(f"{name}: mentions record files lanes may not read ({', '.join(rec[:4])}): read the "
                     f"context; if the lane read them, re-run it, and log either way")
    for m in sorted(set(PROBE_RE.findall(text))):
        rel = m.rstrip(".:")        # PROBE_RE stops at the extension, so `file.lean:90-95` is just the file
        # a pattern (del_*.lean, del_<decl>.lean, a|b.lean) must match at least one file
        alts = []
        if "|" in rel:
            head, _, tail = rel.rpartition("/")
            stem = tail.split("|")
            ext = os.path.splitext(stem[-1])[1]
            prefix = stem[0].rsplit("_", 1)[0] + "_" if "_" in stem[0] else ""
            alts = [os.path.join(head, (x if i == 0 else (x if x.startswith(prefix) else prefix + x)).replace(ext, "") + ext)
                    for i, x in enumerate(stem)]
        pats = [re.sub(r"<[^>]*>", "*", x) for x in (alts or [rel])]
        if all(glob.glob(os.path.join(round_dir, x)) for x in pats):
            continue
        if True:
            probs.append(f"{name}: cites probe {rel}, which does not exist in the round; re-run the lane "
                         f"or drop the verdicts that rely on it")
    return probs


def stray_files(repo, audits_dir):
    """Files that appeared or changed in the Lean repository since Phase 0's baseline
    (tree_state.py): the user's own pre-existing untracked files are not lane writes."""
    r = subprocess.run([sys.executable, "-B", os.path.join(audits_dir, "tree_state.py"), "--check"],
                       cwd=repo, capture_output=True, text=True)
    out = [f"since Phase 0: {l.strip()}" for l in r.stdout.splitlines() if l.startswith(("APPEARED", "VANISHED"))]
    if r.returncode == 2:
        out.append("no Phase 0 tree baseline, so lane writes cannot be told from earlier files: run phase0.py "
                   "before the lanes")
    return out


def _ancestors():
    pids, pid = set(), os.getpid()
    while pid > 1:
        pids.add(pid)
        try:
            pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return pids


OPERATOR_TAG = b"FORMALIZE_PAPER_OPERATOR=1"


def _environ_has(pid, tag):
    try:
        return tag in open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    except OSError:
        return False


def _parent(pid):
    try:
        return int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def _lane_pids(prompt_dir):
    """Processes running a lane of this round as a process of their own (the codex_spawn.py
    fallback runs `codex exec … <round>/prompts/<lane>.txt`); built-in subagents (Claude Code,
    Codex) are not processes of their own and cannot be traced this way."""
    if not prompt_dir:
        return set()
    out = set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                cmd = open(f"/proc/{d}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError:
                continue
            if prompt_dir in cmd:
                out.add(int(d))
    return out


def stray_loops(kill=False, since=None, repo=None, prompt_dir=None):
    """This user's shells running a polling loop, started after `since` (epoch seconds; the
    round's scope time), never this process or its ancestors, and never a process started with
    FORMALIZE_PAPER_OPERATOR=1 in its environment (a monitor the operator started on purpose,
    RUN.md rule 12). A loop counts when its cwd is inside the repository, or when its parent chain
    reaches a lane process of this round (whatever its cwd). Listed always; ended only with --kill."""
    r = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid=,etimes=,args="], capture_output=True, text=True)
    mine, now, out = _ancestors(), time.time(), []
    lanes = _lane_pids(prompt_dir)
    for l in r.stdout.splitlines():
        parts = l.strip().split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        pid, age, args = int(parts[0]), int(parts[1]), parts[2]
        if pid in mine or not LOOP_RE.search(args):
            continue
        if since is not None and now - age < since - 60:
            continue                      # older than the round: not a lane's
        if _environ_has(pid, OPERATOR_TAG):
            continue                      # the operator's own monitor, tagged as RUN.md says
        chain, q = set(), _parent(pid)
        while q > 1 and q not in chain:
            chain.add(q); q = _parent(q)
        from_lane = bool(chain & lanes)
        if repo is not None and not from_lane:
            # A same-user process in another project is not this round's to inspect or kill.
            # cwd gives actual process ownership evidence; a word in a shell wrapper does not.
            try:
                cwd = os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
                root = os.path.realpath(repo)
                if os.path.commonpath([cwd, root]) != root:
                    continue
            except (OSError, ValueError):
                continue
        if kill:
            subprocess.run(["kill", str(pid)], capture_output=True)
        out.append(f"stray polling loop (pid {pid}{', killed' if kill else ''}): {args[:100]}")
    return out


def check_round(cfg, round_name, kill=False, processes=True):
    rd = os.path.join(project.REPO, cfg["rounds_dir"], round_name)
    if not os.path.isdir(rd):
        return [f"no round directory {rd}"]
    import lane_auth
    probs = lane_auth.check_round(rd, lane_files(rd))
    for p in lane_files(rd):
        probs += check_lane(p, rd)
    probs += stray_files(project.REPO, project.AUDITS)
    if processes:
        tgt = os.path.join(rd, "TARGET.json")
        probs += stray_loops(kill, since=os.path.getmtime(tgt) if os.path.exists(tgt) else None, repo=project.REPO,
                             prompt_dir=os.path.join(rd, "prompts") + os.sep)
    return probs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--round")
    ap.add_argument("--project")
    ap.add_argument("--kill", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.round:
        ap.error("give --round")
    try:
        cfg, _ = project.select(a.project)
    except project.SelectionError as e:
        print(f"FAIL: {e}", file=sys.stderr); return 2
    probs = check_round(cfg, a.round, a.kill)
    import lane_auth
    for h, lane, reason, files in lane_auth.reissues(os.path.join(project.REPO, cfg["rounds_dir"], a.round)):
        print(f"NOTE     reissued lane {lane} in commit {h[:11]}: {reason}; earlier verdict kept as "
              f"{', '.join(files) or 'NONE (no verdict file existed at the reissue)'} -- the adjudicator reads it")
    for p in probs:
        print(f"PROBLEM  {p}")
    print(f"lane check {a.round}: {'OK' if not probs else f'{len(probs)} problem(s)'}")
    return 1 if probs else 0


def selftest():
    res = []
    def say(n, ok):
        res.append(ok); print(f"  {'ok  ' if ok else 'FAIL'}  {n}")
    d = tempfile.mkdtemp(prefix="lanecheck-")
    try:
        rd = os.path.join(d, "2026-01-02-bbbbbbb"); os.makedirs(os.path.join(rd, "correspondence.probes"))
        open(os.path.join(rd, "correspondence.probes", "ok.lean"), "w").write("x")
        def lane(name, text):
            p = os.path.join(rd, name); open(p, "w").write(text); return check_lane(p, rd)
        say("a clean lane passes", lane("correspondence.json",
            '{"checked": "probe correspondence.probes/ok.lean compiles; this round 2026-01-02-bbbbbbb"}') == [])
        say("a lane citing another round is flagged",
            any("other rounds" in p for p in lane("substantiveness.json", '{"checked": "as in 2026-01-01-aaaaaaa"}')))
        open(os.path.join(rd, "correspondence.probes", "run.out.txt"), "w").write("x")
        say("a double extension (run.out.txt) is one probe path",
            lane("correspondence.json", '{"checked": "correspondence.probes/run.out.txt"}') == [])
        say("a lane citing ADOPTED.md is flagged",
            any("record files" in p for p in lane("non-vacuity.json", '{"checked": "per ADOPTED.md row 3"}')))
        say("a lane citing a probe that was never written is flagged",
            any("missing.lean" in p for p in lane("paper-faithfulness.json",
                                                  '{"checked": "see paper-faithfulness.probes/missing.lean."}')))
        open(os.path.join(rd, "correspondence.probes", "del_a__h.lean"), "w").write("x")
        say("line suffixes, wildcards, <placeholders> and a|b alternatives resolve against real files",
            lane("correspondence.json", '{"checked": "correspondence.probes/ok.lean:90-95, correspondence.probes/del_*.lean, '
                 'correspondence.probes/del_<decl>__<hyp>.lean, correspondence.probes/del_a__h|h.lean, '
                 'correspondence.probes/ok.lean/audits/x/correspondence.probes/del_a__h.lean"}') == []
            and any("nope" in p for p in lane("correspondence.json", '{"checked": "correspondence.probes/nope_*.lean"}')))
        say("record files are not lane files", "TARGET.json" not in [os.path.basename(p) for p in
                                                                     (open(os.path.join(rd, "TARGET.json"), "w").write("{}") and lane_files(rd))])
        say("another round named by its hash alone is flagged; record names in any case too",
            (os.makedirs(os.path.join(d, "2026-01-01-aaaaaaa")) or True)
            and any("other rounds" in p for p in lane("x1.json", '{"checked": "as in round aaaaaaa"}'))
            and any("record files" in p for p in lane("x2.json", '{"checked": "per adopted.md and AUTHOR_NOTES.md"}')))
        os.makedirs(os.path.join(rd, "revote"))
        open(os.path.join(rd, "revote", "nv.json"), "w").write("{}")
        tr = os.path.join(d, "repo"); os.makedirs(os.path.join(tr, "audits"))
        shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tree_state.py"), os.path.join(tr, "audits"))
        gt = lambda *x: subprocess.run(["git", "-C", tr, *x], capture_output=True, text=True)
        gt("init", "-q"); gt("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i")
        open(os.path.join(tr, "users_own.md"), "w").write("x")
        say("no Phase 0 baseline is reported, never passed", any("no Phase 0 tree baseline" in p
                                                                for p in stray_files(tr, os.path.join(tr, "audits"))))
        subprocess.run([sys.executable, "-B", os.path.join(tr, "audits", "tree_state.py"), "--save"], cwd=tr, capture_output=True)
        open(os.path.join(tr, "lane_wrote.lean"), "w").write("x")
        sf = stray_files(tr, os.path.join(tr, "audits"))
        say("a file written after Phase 0 is flagged; the user's earlier untracked file is not",
            any("lane_wrote.lean" in p for p in sf) and not any("users_own" in p for p in sf))
        say("re-vote lane files are checked too", any(p.endswith("revote/nv.json") for p in lane_files(rd)))
        old_repo, old_audits = project.REPO, project.AUDITS
        try:
            project.REPO, project.AUDITS = tr, os.path.join(tr, "audits")
            os.makedirs(os.path.join(tr, "audits", "P", "R"))
            auth_problems = check_round({"rounds_dir": "audits/P"}, "R", processes=False)
            say("round check rejects missing lane token commitments",
                any("no lane token commitments" in p for p in auth_problems))
        finally:
            project.REPO, project.AUDITS = old_repo, old_audits

        say("a shell polling loop is recognised; a grep mentioning the words is not",
            LOOP_RE.search("bash -c until ! pgrep -f lake; do sleep 5; done") is not None
            and LOOP_RE.search("lake build Foo") is None
            and LOOP_RE.search("grep -E until|while .* sleep") is None)
        loop = subprocess.Popen(["bash", "-c", "until false; do sleep 1; done"], cwd=d)
        unrelated_dir = tempfile.mkdtemp(prefix="unrelated-project-")
        unrelated = subprocess.Popen(["bash", "-c", "until false; do sleep 1; done"], cwd=unrelated_dir)
        # the operator's own monitor, tagged; and a fallback lane process whose child loops elsewhere
        operator = subprocess.Popen(["bash", "-c", "until false; do sleep 1; done"], cwd=d,
                                    env=dict(os.environ, FORMALIZE_PAPER_OPERATOR="1"))
        lane_prompts = os.path.join(d, "audits", "P", "R", "prompts") + os.sep
        lane_proc = subprocess.Popen(["bash", "-c", f"until false; do sleep 1; done & wait # {lane_prompts}correspondence.txt"],
                                     cwd=unrelated_dir)
        time.sleep(0.3)
        lane_child = [int(c) for c in open(f"/proc/{lane_proc.pid}/task/{lane_proc.pid}/children").read().split()]
        real_run = subprocess.run
        def fixture_processes(cmd, *args, **kwargs):
            result = real_run(cmd, *args, **kwargs)
            if isinstance(cmd, list) and cmd[:2] == ["ps", "-u"]:
                allowed = {str(loop.pid), str(unrelated.pid), str(operator.pid)} | {str(c) for c in lane_child}
                result.stdout = "\n".join(line for line in result.stdout.splitlines()
                                          if line.strip().split(None, 1)[0] in allowed)
            return result
        # Even a mutant removing process ownership must never kill other real projects.
        # Keep real processes/cwds/kill calls, but expose only this selftest's two fixtures.
        subprocess.run = fixture_processes
        try:
            say("a loop older than the round is not touched",
                not any(str(loop.pid) in p for p in stray_loops(kill=False, since=time.time() + 3600, repo=d)))
            found = stray_loops(kill=True, repo=d, prompt_dir=lane_prompts)
            try:
                ended = loop.wait(timeout=5) is not None
            except subprocess.TimeoutExpired:
                ended = False
            say("a running polling loop is found and killed", any(str(loop.pid) in p for p in found) and ended)
            say("another project's loop is neither flagged nor killed",
                unrelated.poll() is None and not any(str(unrelated.pid) in p for p in found))
            say("the operator's tagged monitor (FORMALIZE_PAPER_OPERATOR=1) is neither flagged nor killed",
                operator.poll() is None and not any(str(operator.pid) in p for p in found))
            say("a loop started by a lane process is flagged and killed, even with its cwd elsewhere",
                bool(lane_child) and any(str(c) in p for c in lane_child for p in found))
        finally:
            subprocess.run = real_run
            if loop.poll() is None:
                loop.kill()
            unrelated.terminate(); unrelated.wait(timeout=5)
            operator.terminate(); operator.wait(timeout=5)
            for c in lane_child:
                try:
                    os.kill(c, 9)
                except OSError:
                    pass
            lane_proc.kill(); lane_proc.wait(timeout=5)
            shutil.rmtree(unrelated_dir, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())

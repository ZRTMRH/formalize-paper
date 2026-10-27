#!/usr/bin/env python3
"""install.sh --upgrade, end to end in a scratch Lean project (smoke test, 2026-10-24: INSTALL.md said "move
audits/ aside and run install.sh again", which failed on the existing AUDIT_PROTOCOL.md link and lost the record's
history).

It installs this clone into a fresh project (HOME and `lake` stood in, so the user's ~/.claude is untouched), makes
that install look like an older version with a finished project's records, upgrades it, and checks: the records
and the run mode are kept, an apparatus file this version no longer has is gone, every apparatus file is this
version's, the upgrade is one commit `upgrade formalize-paper <version>`, a second upgrade changes nothing, a
plain install refuses an existing audits/ and names --upgrade, and an audit record with uncommitted changes is
refused. It needs the clone (install.sh beside audits/); from an installed project it reports itself not run.

  python3 audits/tests/upgrade.py --selftest
"""
import sys
sys.dont_write_bytecode = True
import filecmp, json, os, shutil, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUDITS = os.path.dirname(HERE)
CLONE = os.path.dirname(AUDITS)
INSTALL = os.path.join(CLONE, "install.sh")


def run(cmd, env, cwd=None):
    r = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def selftest():
    if not os.path.isfile(INSTALL):
        print("  note  install.sh is not beside audits/ (an installed project): not run")
        print("selftest: ok (not run)")
        return 0
    res = []

    def say(name, ok):
        res.append(bool(ok))
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")

    t = tempfile.mkdtemp(prefix="upgrade-")
    try:
        home, bin_, proj = (os.path.join(t, x) for x in ("home", "bin", "proj"))
        for d in (home, bin_, proj):
            os.makedirs(d)
        open(os.path.join(bin_, "lake"), "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(bin_, "lake"), 0o755)
        env = dict(os.environ, HOME=home, PATH=bin_ + os.pathsep + os.environ.get("PATH", ""),
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        G = lambda *a: run(["git", "-C", os.path.join(proj, "audits"), *a], env)
        open(os.path.join(proj, "lakefile.toml"), "w").write('name = "p"\n')
        for c in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "p"]):
            run(["git", "-C", proj, *c], env)
        rc, out = run(["bash", INSTALL, proj], env)
        say("a fresh install works", rc == 0 and "installed in" in out)
        a = os.path.join(proj, "audits")
        # an older version: an apparatus file since removed, another one different, the dev mode, and a finished
        # project's records (its config and rounds directory, pinned)
        open(os.path.join(a, "render_fix.py"), "w").write("# removed in this version\n")
        open(os.path.join(a, "render_record.py"), "a").write("# an older version\n")
        tp = os.path.join(a, "project_template.json")
        d_ = json.load(open(tp)); d_["mode"] = "dev"; open(tp, "w").write(json.dumps(d_, indent=1) + "\n")
        os.makedirs(os.path.join(a, "old", "2026-01-01-abc1234"))
        json.dump({"name": "old", "rounds_dir": "audits/old"}, open(os.path.join(a, "projects", "old.json"), "w"))
        open(os.path.join(a, "old", "RUN_LOG.md"), "w").write("# the old run\n")
        open(os.path.join(a, "old", "2026-01-01-abc1234", "SIGNOFF.md"), "w").write("# sheet\n")
        open(os.path.join(a, "old", "TOOLING_PIN.json"), "w").write("{}\n")
        G("add", "-A"); G("commit", "-qm", "the old version and its run")
        before = G("rev-list", "--count", "HEAD")[1].strip()
        rc, out = run(["bash", INSTALL, proj], env)
        say("a plain install refuses an existing audits/ and names --upgrade", rc != 0 and "--upgrade" in out)
        open(os.path.join(a, "old", "RUN_LOG.md"), "a").write("uncommitted\n")
        rc_d, out_d = run(["bash", INSTALL, "--upgrade", proj], env)
        G("checkout", "-q", "--", "old/RUN_LOG.md")
        open(os.path.join(a, "stray.py"), "w").write("# not committed\n")
        rc_s, out_s = run(["bash", INSTALL, "--upgrade", proj], env)
        os.remove(os.path.join(a, "stray.py"))
        say("--upgrade refuses an audit record with an uncommitted record change, or an untracked file among the "
            "apparatus, changing nothing",
            rc_d != 0 and "uncommitted" in out_d and "old/RUN_LOG.md" in out_d and rc_s != 0 and "stray.py" in out_s
            and G("rev-list", "--count", "HEAD")[1].strip() == before and os.path.exists(os.path.join(a, "render_fix.py")))
        # an untracked file inside a rounds directory (a round's prompts/, as real runs leave them) is left alone
        os.makedirs(os.path.join(a, "old", "2026-01-01-abc1234", "prompts"))
        open(os.path.join(a, "old", "2026-01-01-abc1234", "prompts", "lane.txt"), "w").write("a prompt\n")
        rc, out = run(["bash", INSTALL, "--upgrade", proj], env)
        ver = open(os.path.join(CLONE, "VERSION")).read().strip()
        src_files = sorted(os.path.relpath(os.path.join(dp, f), AUDITS) for dp, dn, fs in os.walk(AUDITS)
                           for f in fs if "__pycache__" not in dp)
        same = all(filecmp.cmp(os.path.join(AUDITS, f), os.path.join(a, f), shallow=False) for f in src_files
                   if f != "project_template.json")
        tracked = set(G("ls-files")[1].split())
        apparatus = {f for f in tracked if f.split("/")[0] not in ("projects", "old")}
        say("--upgrade replaces the apparatus with this version's (a removed file gone, a changed one this version's)",
            rc == 0 and "upgraded in" in out and not os.path.exists(os.path.join(a, "render_fix.py")) and same
            and apparatus == set(src_files))
        say("--upgrade keeps the records (the projects' configs and rounds directories) and the run mode",
            open(os.path.join(a, "old", "RUN_LOG.md")).read() == "# the old run\n"
            and os.path.exists(os.path.join(a, "old", "2026-01-01-abc1234", "SIGNOFF.md"))
            and json.load(open(os.path.join(a, "projects", "old.json")))["rounds_dir"] == "audits/old"
            and json.load(open(tp))["mode"] == "dev" and "run mode: dev" in out
            and open(os.path.join(a, "old", "2026-01-01-abc1234", "prompts", "lane.txt")).read() == "a prompt\n"
            and "old/2026-01-01-abc1234/prompts/lane.txt" not in tracked)
        say("--upgrade is one commit in the audit record, `upgrade formalize-paper <version>`, the history kept, the "
            "tree clean; a pinned project is named",
            G("log", "-1", "--format=%s")[1].strip() == f"upgrade formalize-paper {ver}"
            and int(G("rev-list", "--count", "HEAD")[1]) == int(before) + 1
            and G("status", "--porcelain")[1].split() == ["??", "old/2026-01-01-abc1234/prompts/"]
            and "old was pinned" in out)
        say("the project link, the agent and the skill are in place after it",
            os.path.islink(os.path.join(proj, "AUDIT_PROTOCOL.md"))
            and filecmp.cmp(os.path.join(home, ".claude", "agents", "auditor.md"),
                            os.path.join(AUDITS, "agents", "auditor.md"), shallow=False))
        rc2, out2 = run(["bash", INSTALL, "--upgrade", proj], env)
        say("a second --upgrade changes nothing (no new commit)",
            rc2 == 0 and int(G("rev-list", "--count", "HEAD")[1]) == int(before) + 1)
    finally:
        shutil.rmtree(t, ignore_errors=True)
    print("selftest:", "ok" if all(res) else "FAILED")
    return 0 if all(res) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)

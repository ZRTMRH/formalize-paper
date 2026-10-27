#!/usr/bin/env bash
# Install formalize-paper into a Lean project.
#
#   ./install.sh <lean-project-dir>            Claude Code
#   ./install.sh --codex <lean-project-dir>    also the Codex CLI files (experimental, see codex/README.md)
#   ./install.sh --dev <lean-project-dir>      run mode "dev": every check stops the run (maintainers);
#                                              the default, "release", stops only for the four human
#                                              stops (RUN.md, "Stops that remain at every level")
#   ./install.sh --upgrade <lean-project-dir>  between runs: replace the apparatus in an existing audits/
#                                              with this version, keeping the records (audits/projects/ and
#                                              each project's rounds directory) and the run mode; committed in
#                                              the audit record as "upgrade formalize-paper <version>"
#
# What it does, and nothing else:
#   1. copies the apparatus (audits/ of this repository) into <lean-project-dir>/audits/ and makes
#      it a git repository of its own: the audit record. Its first commit is the installed version.
#   2. links <lean-project-dir>/AUDIT_PROTOCOL.md -> audits/AUDIT_PROTOCOL.md and adds both to the
#      project's .git/info/exclude, so the record never enters the project's own history.
#   3. installs the reviewer agent and the skill for your user: ~/.claude/agents/auditor.md and
#      ~/.claude/skills/formalize-paper/ (an existing different copy is backed up first).
#   4. sets "env": {"PYTHONDONTWRITEBYTECODE": "1"} and the protocol's permission rules (allow and
#      deny; INSTALL.md, "Permissions") in the PROJECT's .claude/settings.json (created, or merged
#      keeping every other key; an unparsable file is refused before step 1), and excludes the
#      run's .formalization-work/ and deliverables/ from the project's git history.
# With --codex it also installs generated project roles and the required bytecode-prevention
# shell environment setting in the user and project Codex configs (see codex/README.md).
# It never pushes anything and never touches the network.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX=0
MODE=release
MODE_GIVEN=0
UPGRADE=0
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --codex) CODEX=1 ;;
    --dev) MODE=dev; MODE_GIVEN=1 ;;
    --upgrade) UPGRADE=1 ;;
    *) echo "usage: $0 [--codex] [--dev] [--upgrade] <lean-project-dir>" >&2; exit 2 ;;
  esac
  shift
done
if [[ $# -ne 1 ]]; then
  echo "usage: $0 [--codex] [--dev] [--upgrade] <lean-project-dir>" >&2; exit 2
fi
TARGET="$(cd "$1" && pwd)"
VERSION="$(cat "$HERE/VERSION" 2>/dev/null || echo unknown)"

fail() { echo "install.sh: $*" >&2; exit 1; }

# --- checks -------------------------------------------------------------------------------------
for tool in git python3 lake; do
  command -v "$tool" >/dev/null || fail "'$tool' not found on PATH (see INSTALL.md, Requirements)"
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 3.10 or newer is required"
[[ -f "$TARGET/lakefile.lean" || -f "$TARGET/lakefile.toml" ]] \
  || fail "$TARGET has no lakefile.lean or lakefile.toml: not a Lean (Lake) project"
git -C "$TARGET" rev-parse --show-toplevel >/dev/null 2>&1 \
  || fail "$TARGET is not a git repository (run 'git init' and commit once first)"
[[ "$(git -C "$TARGET" rev-parse --show-toplevel)" == "$TARGET" ]] \
  || fail "$TARGET is inside a git repository but not its root; install at the root"
# --upgrade's bookkeeping: the records are audits/projects/ and each project's rounds directory (a top-level
# directory of audits/); everything else tracked is the apparatus. check: no tracked change anywhere and no
# untracked file outside the records (untracked files inside a rounds directory are left alone); apply: remove
# the old apparatus; add: stage the new apparatus only (never a record).
upgrade_py() {
  python3 -B - "$1" "$TARGET/audits" "$HERE/audits" <<'PY'
import glob, json, os, subprocess, sys
op, a, src = sys.argv[1:4]
keep = {"projects"}
for p in sorted(glob.glob(os.path.join(a, "projects", "*.json"))):
    try:
        rd = json.load(open(p, encoding="utf-8")).get("rounds_dir", "")
    except (OSError, ValueError):
        sys.exit(f"install.sh: --upgrade: {p} is not JSON")
    parts = os.path.normpath(rd).split(os.sep)
    if len(parts) >= 2 and parts[0] == "audits":
        if os.path.exists(os.path.join(src, parts[1])):
            sys.exit(f"install.sh: --upgrade: {p}'s rounds directory {rd} has the name of an apparatus path")
        keep.add(parts[1])
        if op == "check" and os.path.exists(os.path.join(a, parts[1], *parts[2:], "TOOLING_PIN.json")):
            print(f"  note: {os.path.basename(p)[:-5]} was pinned to the old tooling: its record stays, but a run "
                  f"continued on it would fail integrity's tooling check (upgrade between runs only)")
G = lambda *x: subprocess.run(["git", "-C", a, *x], capture_output=True, text=True, check=True).stdout
if op == "check":
    bad = []
    for e in [x for x in G("status", "--porcelain", "-z", "--untracked-files=all").split("\0") if x]:
        st, path = e[:2], e[3:]
        if st == "??" and path.split("/")[0] in keep:
            continue
        bad.append(f"{st.strip()} {path}")
    if bad:
        sys.exit(f"install.sh: --upgrade: {a} has uncommitted changes ({', '.join(bad[:5])}"
                 f"{', ...' if len(bad) > 5 else ''}): commit them first (a run in progress is never upgraded)")
elif op == "apply":
    for f in [x for x in G("ls-files", "-z").split("\0") if x]:
        if f.split("/")[0] not in keep:
            os.remove(os.path.join(a, f))
    for d, _subs, _fs in sorted(os.walk(a, topdown=False)):
        rel = os.path.relpath(d, a)
        if rel != "." and rel.split(os.sep)[0] not in keep | {".git"} and not os.listdir(d):
            os.rmdir(d)
else:
    G("add", "-A", "--", ".", *[f":(exclude){k}" for k in sorted(keep)])
PY
}
if [[ $UPGRADE -eq 1 ]]; then
  [[ -d "$TARGET/audits/.git" && ! -L "$TARGET/audits" ]] \
    || fail "--upgrade: $TARGET/audits is not an installed audit record (no audits/.git); install without --upgrade"
  upgrade_py check || fail "--upgrade: nothing was changed"
  [[ $MODE_GIVEN -eq 1 ]] || MODE="$(python3 -B -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mode","release"))' \
    "$TARGET/audits/project_template.json" 2>/dev/null || echo release)"
else
  [[ -e "$TARGET/audits" ]] \
    && fail "$TARGET/audits already exists. To upgrade it between runs: $0 --upgrade $TARGET (INSTALL.md, 'Upgrading')."
fi
[[ -e "$TARGET/.claude/agents/auditor.md" ]] \
  && fail "$TARGET/.claude/agents/auditor.md exists; it would override the pinned reviewer. Remove it first."
# (A project .claude/settings.json is fine and is kept: step 4 only adds an env variable and
# permission rules to it.)
SETTINGS="$TARGET/.claude/settings.json"
python3 -B "$HERE/audits/claude_settings.py" --dry-run "$SETTINGS" \
  || fail "fix $SETTINGS first (see the message above); nothing was installed"
# everything this script writes must be writable BEFORE it writes anything (no partial install)
writable() {  # path: the path itself if it exists, else its nearest existing ancestor
  local p="$1"; while [[ ! -e "$p" ]]; do p="$(dirname "$p")"; done
  [[ -w "$p" && -x "$p" ]] || [[ -f "$p" && -w "$p" ]]
}
EXCL_PRE="$(git -C "$TARGET" rev-parse --git-path info/exclude)"; [[ "$EXCL_PRE" = /* ]] || EXCL_PRE="$TARGET/$EXCL_PRE"
for p in "$TARGET" "$EXCL_PRE" "$HOME/.claude/agents/auditor.md" "$HOME/.claude/skills/formalize-paper/SKILL.md"; do
  writable "$p" || fail "$p (or the directory that would hold it) is not writable; nothing was installed"
done
# an existing, different copy is backed up next to itself: its directory must be writable too
for pair in "$HERE/audits/agents/auditor.md:$HOME/.claude/agents/auditor.md" \
            "$HERE/audits/skills/formalize-paper/SKILL.md:$HOME/.claude/skills/formalize-paper/SKILL.md"; do
  src="${pair%%:*}"; dst="${pair#*:}"
  if [[ -e "$dst" ]] && ! cmp -s "$src" "$dst"; then
    [[ -w "$(dirname "$dst")" ]] || fail "$(dirname "$dst") is not writable, so $dst cannot be backed up; nothing was installed"
  fi
done
if [[ $CODEX -eq 1 && -x "$HERE/codex/install-codex.sh" ]]; then
  for c in "${CODEX_HOME:-$HOME/.codex}/config.toml" "$TARGET/.codex/config.toml"; do
    python3 -B "$HERE/codex/configure-environment.py" --dry-run "$c" \
      || fail "Codex configuration $c cannot be updated (see the message above); nothing was installed"
  done
  for p in "$HOME/.agents/skills/formalize-paper/SKILL.md" "$TARGET/.codex/agents"; do
    writable "$p" || fail "$p (or the directory that would hold it) is not writable; nothing was installed"
  done
fi

# --- 1. the apparatus, as a git repository of its own -------------------------------------------
if [[ $UPGRADE -eq 1 ]]; then
  # every tracked file outside the records goes (an apparatus file this version no longer has must not
  # linger); the records -- audits/projects/ and each project's rounds directory -- are kept as they are
  upgrade_py apply || fail "--upgrade: could not remove the old apparatus"
else
  mkdir "$TARGET/audits"
fi
( cd "$HERE/audits" && tar cf - --exclude='__pycache__' . ) | ( cd "$TARGET/audits" && tar xf - )
mkdir -p "$TARGET/audits/projects"
# the run mode every config of this installation copies (project.mode; the config check refuses another)
python3 -B - "$TARGET/audits/project_template.json" "$MODE" <<'PY' || fail "could not set the run mode"
import json, sys
p, m = sys.argv[1], sys.argv[2]
d = json.load(open(p, encoding="utf-8")); d["mode"] = m
open(p, "w", encoding="utf-8").write(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
PY
if [[ $UPGRADE -eq 1 ]]; then
  upgrade_py add || fail "--upgrade: could not stage the new apparatus"
else
  git -C "$TARGET/audits" init -q
  git -C "$TARGET/audits" add -A
fi
if [[ $UPGRADE -eq 0 ]] || ! git -C "$TARGET/audits" diff --cached --quiet; then
  git -C "$TARGET/audits" -c user.name="${GIT_AUTHOR_NAME:-$(git config user.name || echo formalize-paper)}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo formalize-paper@localhost)}" \
    commit -q -m "$([[ $UPGRADE -eq 1 ]] && echo upgrade || echo install) formalize-paper $VERSION"
fi

# --- 2. protocol link and excludes ---------------------------------------------------------------
[[ $UPGRADE -eq 1 && -L "$TARGET/AUDIT_PROTOCOL.md" ]] || ln -s audits/AUDIT_PROTOCOL.md "$TARGET/AUDIT_PROTOCOL.md"
EXCL="$(git -C "$TARGET" rev-parse --git-path info/exclude)"
[[ "$EXCL" = /* ]] || EXCL="$TARGET/$EXCL"
mkdir -p "$(dirname "$EXCL")"
for line in "audits/" "AUDIT_PROTOCOL.md" ".formalization-work/" "deliverables/"; do
  grep -qxF "$line" "$EXCL" 2>/dev/null || echo "$line" >> "$EXCL"
done

# --- 3. agent and skill, for the user ------------------------------------------------------------
install_file() {  # src dst
  if [[ -e "$2" ]] && ! cmp -s "$1" "$2"; then
    cp "$2" "$2.bak.$(date +%Y%m%d%H%M%S)"
    echo "  backed up the existing $2"
  fi
  mkdir -p "$(dirname "$2")"
  cp "$1" "$2"
}
install_file "$HERE/audits/agents/auditor.md" "$HOME/.claude/agents/auditor.md"
install_file "$HERE/audits/skills/formalize-paper/SKILL.md" "$HOME/.claude/skills/formalize-paper/SKILL.md"

# --- 4. project settings: no Python bytecode from any command Claude Code runs here ---------------
SETTINGS_NEW=0; [[ -e "$SETTINGS" ]] || SETTINGS_NEW=1
python3 -B "$HERE/audits/claude_settings.py" "$SETTINGS" || fail "could not update $SETTINGS"
if [[ $SETTINGS_NEW -eq 1 ]]; then
  # created by us: keep it out of the project's history, like audits/ (Phase 0 needs a clean tree)
  grep -qxF ".claude/settings.json" "$EXCL" 2>/dev/null || echo ".claude/settings.json" >> "$EXCL"
elif git -C "$TARGET" ls-files --error-unmatch .claude/settings.json >/dev/null 2>&1 \
     && ! git -C "$TARGET" diff --quiet -- .claude/settings.json; then
  echo "  note: .claude/settings.json is tracked in the project and changed; commit it before the run"
fi

if [[ $CODEX -eq 1 ]]; then
  if [[ -x "$HERE/codex/install-codex.sh" ]]; then
    "$HERE/codex/install-codex.sh" "$TARGET"
  else
    echo "  --codex: codex/install-codex.sh is not present in this version; see KNOWN_LIMITATIONS.md" >&2
  fi
fi

echo "formalize-paper $VERSION $([[ $UPGRADE -eq 1 ]] && echo "upgraded" || echo "installed") in $TARGET (run mode: $MODE)"
echo "Next: cd $TARGET && python3 -B audits/selftest_all.py --fast   (last line: ALL SELFTESTS: ok)"
if [[ $CODEX -eq 1 ]]; then
  echo "Then start Codex there with the command printed above and type \$formalize-paper."
else
  echo "Then open Claude Code there and type /formalize-paper."
fi

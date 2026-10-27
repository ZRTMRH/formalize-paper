#!/usr/bin/env bash
# Install formalize-paper into a Lean project.
#
#   ./install.sh <lean-project-dir>            Claude Code
#   ./install.sh --codex <lean-project-dir>    also the Codex CLI files (experimental, see codex/README.md)
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
if [[ "${1:-}" == "--codex" ]]; then CODEX=1; shift; fi
if [[ $# -ne 1 ]]; then
  echo "usage: $0 [--codex] <lean-project-dir>" >&2; exit 2
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
[[ -e "$TARGET/audits" ]] \
  && fail "$TARGET/audits already exists. To upgrade, see INSTALL.md, 'Upgrading' (a run in progress is pinned to its tooling)."
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
mkdir "$TARGET/audits"
( cd "$HERE/audits" && tar cf - --exclude='__pycache__' . ) | ( cd "$TARGET/audits" && tar xf - )
mkdir -p "$TARGET/audits/projects"
git -C "$TARGET/audits" init -q
git -C "$TARGET/audits" add -A
git -C "$TARGET/audits" -c user.name="${GIT_AUTHOR_NAME:-$(git config user.name || echo formalize-paper)}" \
  -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo formalize-paper@localhost)}" \
  commit -q -m "install formalize-paper $VERSION"

# --- 2. protocol link and excludes ---------------------------------------------------------------
ln -s audits/AUDIT_PROTOCOL.md "$TARGET/AUDIT_PROTOCOL.md"
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

echo "formalize-paper $VERSION installed in $TARGET"
echo "Next: cd $TARGET && python3 -B audits/selftest_all.py --fast   (last line: ALL SELFTESTS: ok)"
echo "Then open Claude Code there and type /formalize-paper."

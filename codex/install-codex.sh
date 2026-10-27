#!/usr/bin/env bash
# Codex CLI part of install.sh --codex (experimental; see codex/README.md).
# Installs the formalize-paper skill where Codex reads user skills: ~/.agents/skills/formalize-paper/.
# The reviewer definition stays at ~/.claude/agents/auditor.md (installed by install.sh): it is the
# same canonical body used to generate the built-in Codex auditor; integrity.py pins both.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v codex >/dev/null || echo "  note: the Codex CLI (codex) is not on PATH; install it before a run" >&2
python3 -B "$HERE/codex/configure-environment.py" "${CODEX_HOME:-$HOME/.codex}/config.toml"
mkdir -p "$HOME/.agents/skills/formalize-paper"
cp "$HERE/audits/skills/formalize-paper/SKILL.md" "$HOME/.agents/skills/formalize-paper/SKILL.md"
echo "  Codex: skill installed in ~/.agents/skills/formalize-paper/ (start a run with \$formalize-paper)"

if [[ $# -ge 1 ]]; then
  python3 -B "$HERE/codex/configure-environment.py" "$1/.codex/config.toml"
  python3 -B "$1/audits/codex_agents.py" --install "$1/.codex/agents"
  # keep the generated roles and the project Codex config out of the project's history
  EXCL="$(git -C "$1" rev-parse --git-path info/exclude)"; [[ "$EXCL" = /* ]] || EXCL="$1/$EXCL"
  grep -qxF ".codex/" "$EXCL" 2>/dev/null || echo ".codex/" >> "$EXCL"
  # the count is read from what was installed, never typed here (safety review LOW 5: it said "eight" of nine)
  echo "  Codex: $(ls "$1/.codex/agents"/formalize_*.toml | wc -l | tr -d ' ') generated project roles installed; integrity.py pins their actual bytes."
  # Git without approval prompts (F9): workspace-write keeps the project's .git read-only, so every
  # branch/stage/commit of the author waits for a person's approval -- and a hands-off run stalls.
  # Tested on Codex 0.163.0: --add-dir <git dir> (same as sandbox_workspace_write.writable_roots)
  # makes it writable for that session only. Printed, not written to any config: a project config
  # is ignored until the project is trusted, and a user-config entry would outlive the run.
  GD="$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  GW="$(git -C "$1" rev-parse --path-format=absolute --git-dir 2>/dev/null || true)"
  if [[ -n "$GD" ]]; then
    ADD="--add-dir $(printf %q "$GD")"
    [[ -n "$GW" && "$GW" != "$GD" ]] && ADD="$ADD --add-dir $(printf %q "$GW")"
    echo "  Codex: start the run with the project's git metadata writable (no approval prompt per commit):"
    echo "         cd $(printf %q "$1") && codex --sandbox workspace-write $ADD"
    echo "         (see codex/README.md, 'Git commits without approval prompts', for what this allows)"
    echo "         (public paper only, optional: add --search so the citation agents can search; audits/run/codex.md)"
  fi
else
  echo "  Run install.sh --codex <project> to install the built-in roles before starting Codex."
fi

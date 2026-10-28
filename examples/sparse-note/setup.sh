#!/usr/bin/env bash
# Make a ready-to-run copy of the sparse-note example: a Lean project on branch `sparse-note`,
# with formalize-paper installed and the example's project config in place.
#
#   examples/sparse-note/setup.sh [--codex] [--dev] <new-directory>
#
# --codex and --dev are passed to install.sh (INSTALL.md, "Codex CLI" and "Run mode").
#
# Afterwards: cd <new-directory> && lake exe cache get && lake build SparseNote
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
FLAGS=()
while [[ $# -gt 0 && "$1" == --* ]]; do
  case "$1" in
    --codex|--dev) FLAGS+=("$1"); shift ;;
    *) echo "usage: $0 [--codex] [--dev] <new-directory>" >&2; exit 2 ;;
  esac
done
[[ $# -eq 1 ]] || { echo "usage: $0 [--codex] [--dev] <new-directory>" >&2; exit 2; }
[[ -e "$1" ]] && { echo "setup.sh: $1 already exists" >&2; exit 1; }
mkdir -p "$1"; DST="$(cd "$1" && pwd)"
( cd "$HERE" && tar cf - --exclude=setup.sh --exclude=sparse-note.json --exclude=README.md . ) | ( cd "$DST" && tar xf - )
printf '.lake/\n' > "$DST/.gitignore"
G=(-c user.name="${GIT_AUTHOR_NAME:-$(git config user.name || echo formalize-paper)}"
   -c user.email="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo formalize-paper@localhost)}")
git -C "$DST" init -q -b sparse-note
git -C "$DST" add -A
git -C "$DST" "${G[@]}" commit -q -m "sparse-note example: statements (sorry)"
"$REPO/install.sh" ${FLAGS[@]+"${FLAGS[@]}"} "$DST"
BASE="$(git -C "$DST" rev-parse --short=11 HEAD)"
sed "s/<<set by setup.sh>>/$BASE/" "$HERE/sparse-note.json" > "$DST/audits/projects/sparse-note.json"
# the run mode of this installation (install.sh writes it into the template; a config without it would run as dev)
python3 -B -c 'import json,sys; t=json.load(open(sys.argv[1]))["mode"]; p=sys.argv[2]; d=json.load(open(p)); d["mode"]=t; open(p,"w").write(json.dumps(d,indent=1,ensure_ascii=False)+"\n")' \
  "$DST/audits/project_template.json" "$DST/audits/projects/sparse-note.json"
git -C "$DST/audits" add projects/sparse-note.json
git -C "$DST/audits" "${G[@]}" commit -q -m "setup sparse-note (example)"
echo "sparse-note example ready in $DST"
echo "Next: cd $DST && lake exe cache get && lake build SparseNote"

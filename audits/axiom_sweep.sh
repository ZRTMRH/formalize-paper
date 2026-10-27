#!/usr/bin/env bash
# Kept so that older notes calling `audits/axiom_sweep.sh` still work. The sweep is now
# project-driven: see audits/axiom_sweep.py (project chosen by branch, or --project NAME).
exec python3 "$(dirname "$0")/axiom_sweep.py" "$@"

# Contributing

Bug reports and suggestions are welcome as GitHub issues. Useful reports say which version
(`VERSION`), whether the installation is `release` or `dev` (`install.sh --dev`), Claude Code or
Codex, and which step failed, with the failing line of the script's output. Please do not attach
an unpublished paper, its Lean code or a run's audit record unless you are free to share them.

Before changing the apparatus (the scripts under `audits/`, `audits/RUN.md`, the stage files in
`audits/run/`, `audits/AUDIT_PROTOCOL.md`), read [`MAINTAINING.md`](MAINTAINING.md): it lists the
protocol's invariants and the fix process. The test tiers are in
[`audits/tests/TIERS.md`](audits/tests/TIERS.md); at least tier 0
(`python3 -B audits/tests/tier.py 0`, from a clone, a few minutes) must pass for every change.

Licensing of contributions: unless you say otherwise, a contribution is under Apache-2.0. A change
to the parts adapted from Trellis (Lanes A–C of `audits/AUDIT_PROTOCOL.md` and the prompts cut
from them; see [`NOTICE`](NOTICE)) stays under the PolyForm Noncommercial License 1.0.0 of those
parts.

# Known limitations

What you should know before relying on a run. The full, detailed list (mostly for maintainers) is in
[`docs/maintainer-notes.md`](docs/maintainer-notes.md).

- **The reviewers are AI judgements, not proofs.** Lean's kernel checks every proof. Whether each Lean
  statement says what the paper says is judged by independent AI reviewers and, if you choose, by you on the
  sign-off sheet; that judgement is not a mechanical guarantee. Their detection rate has been measured on one
  benchmark of ten short papers with planted errors (`benchmark/`), not in general.
- **Cited results are assumed, not proved, by default.** A result the paper only cites becomes an explicit,
  named hypothesis in the Lean, and the report lists it. The citation check compares a cited result with its
  source only when the source is openly available (for example on arXiv), and it does not yet run under Codex.
- **Slips in the paper's proofs are reported when noticed,** not searched for line by line: the absence of a
  listed slip says little.
- **Built against careless agents, not deliberate forgery.** The checks catch an agent that skips or misreports
  a step; someone deliberately rewriting the run's records could evade them. Run it in an account that holds
  nothing you would mind an agent seeing.
- **The PDFs are produced and checked by agents.** The markdown delivered beside each PDF is the
  authoritative text.
- **Platforms.** Most tested on Linux with Claude Code. macOS (this branch) is less tested: runs on one Intel Mac under Claude Code and Codex. On macOS two rare cases in the reviewer-process check are skipped rather than refused (a process of yours that cannot be read at that moment, and a process whose parent cannot be read); the worst outcome is a leftover agent loop that goes unreported, and proofs are unaffected. The Codex CLI is experimental; a "model at capacity" error can pause a Codex run until you type `resume`.
- **Time and usage.** A run takes hours even for a short paper (a 30-page paper took about 16 hours of active
  run time on an earlier version), and it uses a large share of a subscription's usage limits.

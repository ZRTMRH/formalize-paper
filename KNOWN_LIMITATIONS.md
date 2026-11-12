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
- **The checks catch an agent's mistakes, not an agent that sets out to deceive.** The summary and the report
  are written by the agent that did the formalization, and the reviews of them and the checks of the PDFs are
  saved by that agent. The README's section "What the checking code found" is written by the checking program
  when the files are delivered: each result's status as computed from the review records, the answers recorded
  as yours, and anything the checks noticed, so what the summary claims can be compared with it there. When the
  summary names a result exactly as the record does somewhere (even in a collapsed block), only those rows are
  compared, so a visible row with extra words in its label, such as "Lemma 1.2 (main)", can differ unmarked;
  the computed status is still shown in the section. But the
  agent runs that program, and could change it or the other checking scripts during the run, or rewrite the
  run's history consistently; nothing in the delivery then rules a deception out. What you can check yourself:
  rebuild the Lean and print its axioms; read the Lean statements of the main results (the sign-off sheet); run
  `python3 audits/project.py --check-delivered` in the audit record to see whether a delivered file was changed
  after delivery. If the result matters, have a separate session re-check the delivered commit. Run the tool in
  an account that holds nothing you would mind an agent seeing.
- **A change to comments and docstrings only is not re-reviewed.** It is checked mechanically
  (`project.py --comment-only`) and disclosed, and no review lane reads the new docstrings, so a later edit
  could drop a caveat a docstring carried. When Lean finds the compiled files not byte-for-byte identical
  while every declaration, type, value and attribute agrees, the verdict rests on the source text with
  comments removed (the report says "checked on the source"); a reader of docstrings inside an imported
  tactic, or a token from an imported file holding a comment marker (or one declared through a parser
  combinator such as `leading_parser "[--"` rather than a `notation`/`syntax` command), is not seen there.
  Phase 0's simpler comment reader (`phase0.strip_comments`) can still take code for a comment after a
  raw string (`r#"--"#`), a `«--»` name, a char literal right after another, or inside `s!"{…}"`; it only
  feeds the text `sorry` scan, which Lean's axiom sweep backs, and the diff-round skip, which leads to a full
  round. It is not the comment-only decision, and it is left as is because Phase 0 is in the core.
- **The PDFs are produced and checked by agents.** The markdown delivered beside each PDF is the
  authoritative text.
- **Platforms.** Most tested on Linux (Debian or Ubuntu, or Ubuntu under WSL2) with Claude Code. macOS (this branch) has had fewer runs, all on one 8 GB Intel Mac, but has delivered real papers: Ramanujan's proof of Bertrand's postulate under Claude Code and a 5-page paper under Codex. On macOS two rare cases in the reviewer-process check are skipped rather than refused (a process of yours that cannot be read at that moment, and a process whose parent cannot be read); the worst outcome is a leftover agent loop that goes unreported, and proofs are unaffected. The Codex CLI has had fewer runs than Claude Code; a "model at capacity" error can pause a Codex run until you type `resume`.
- **Time and usage.** A run takes hours even for a short paper (a 35-page paper took about 16 hours of active
  run time on an earlier version), and it uses a large share of a subscription's usage limits.

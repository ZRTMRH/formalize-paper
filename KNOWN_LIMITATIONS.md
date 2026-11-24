# Known limitations

What you should know before relying on a run. The full, detailed list (mostly for maintainers) is in
[`docs/maintainer-notes.md`](docs/maintainer-notes.md).

- **The reviewers are AI judgements, not proofs.** Lean's kernel checks every proof. Whether each Lean
  statement says what the paper says is judged by independent AI reviewers and, if you choose, by you on the
  sign-off sheet; that judgement is not a mechanical guarantee. Their detection rate has been measured on one
  benchmark of ten short papers with planted errors (`benchmark/`), not in general.
- **Cited results are assumed, not proved, by default.** A result the paper only cites becomes an explicit,
  named hypothesis in the Lean, and the report lists it. The citation check compares a cited result with its
  source only when the source is openly available (for example on arXiv); under Codex only with `--search` (public
  papers), where publisher pages often refuse access and a 4-reference paper cost about 1.4 M tokens (mostly cached).
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
- **Proofs inside definitions are not part of what you approve.** The freeze on approved statements ignores every
  proof inside a definition (so filling a `sorry` there is not a change), and a definition used only inside such a
  proof is not listed on the sign-off sheet: by proof irrelevance it cannot change what a statement means. A proof
  written inside a statement itself still counts, and `opaque` definitions are compared in full. A change
  confined to the proof inside a `Decidable` value is not a change; a different decision procedure is. If the
  sign-off sheet shows that definition's source text, filling a proof there still changes the approved statement
  text, which is reported as drift: under `hands-off` the agent re-approves it; under `involved` or
  `statements-only` it is a question for you.
- In `append` sweep mode (the fallback when the namespace is not a module), a project declaration named under the
  fingerprint program's own helper prefixes (`auditFpStripMData`, `auditFpKey`, `auditFpEraseProofs`) is not
  fingerprinted, so changing it would not show as drift. Such a name is visible in the source; `import` mode, the
  default, fingerprints it (REVIEW-FIX-FP-R1).
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
- **Do not upgrade the tool in the middle of a run.** A run resumed on another version fails the tooling check
  and may show a false change of an approved statement (DRIFT); start the next run on the new version.
- **A line such as `open Finset` right after a definition** is read as part of that definition: it shows in the
  sign-off sheet's text of the definition and can give a false DRIFT. The run is told to keep such lines before
  the first declaration or inside a `section`.
- **The K certificate is the formalizing agent's judgement.** Since 2026-11-16 the code writes no K content (no
  count, table or item list: its count understated, since it could not tell which results an item on a helper
  lemma affects); the run's agent writes REPORT's section 12 and SUMMARY's K line, checked by the CLAIMS delivery
  reviewer, with no code check. Whether a change of representation is trivial, whether a
  bridge theorem is adequate, and whether the conditions list is complete are judged by reviewers and the
  adjudicator, not by code; the list is written by the operator and only checked against the human's recorded
  words (a row the operator deletes before any adjudicator ruled it vanishes, unless the adjudicator's check of
  the human's words catches it). An item the code cannot match, read or confirm is counted open. When one reading
  implies the other, the stronger is taken with no K item, so that judgement rests on the adjudicator. Under
  hands-off a statement changed in the K stage is approved by the agent on the human's recorded answer.
- **The intake's list of stops is worded more narrowly** than stop 1 now is: a goal result true only vacuously
  also stops (the intake text is unchanged so that runs in flight keep their intake check).
- **With no goal result named, a false result never stops the run**: stop 1 covers goal results only, so a result
  that looks false is disclosed in the documents, never asked. The goal list (`goal_results`) is written by the operator
  and is not checked against the human's answer to intake question 2b.
- **The probe wrapper is allowed like every agent-run script,** so `lean_slot.py run --no-slot -- <command>` runs
  without a permission prompt (a run is not a sandbox; INSTALL.md).
- **An approved statement found unfaithful after the sign-off ships unchanged** under the delegating levels, marked
  "not established" with an open K item; a refuted non-goal statement ships "stated, not proved".
- **The Lean probe limit is followed by instruction**, not enforced: reviewers and helpers are told to compile
  through `lean_slot.py`; the run's own checks (Phase 0, the sign-off checks) are not slotted; after a 300 s wait a
  probe runs without a slot; under WSL the free-memory floor reads the Linux VM's memory, not Windows'.
- **The memory guard also pauses on memory pressure, which can slow a run.** Besides low free memory, it pauses the probes of every formalize-paper project of the account (a second run, or the user's own `lake env lean` in such a project, included; editor processes never) when the kernel reports sustained memory pressure (Linux), and it briefly treats each new probe as needing up to 3.2 GB (2 GB on an 8 GB machine); on a busy or small machine probes therefore wait more and the run takes longer, and every probe waits while one of the run's own checks runs (after 15 minutes paused in all, one probe runs beside it). The time a probe is paused is added to its 240 s limit (up to about 540 s with its slot wait), so a paused probe keeps its memory and its slot longer; a probe cut with 180 s or less of running says so and is re-run, not called too large. In a 16 GB test with 12 simultaneous probes, real memory peaked at 7.6 GB with the machine responsive, against 14.6 GB and seven probes killed without the guard (V2 round 4, after fix round RAMK).
- **The memory guard pauses, it does not kill.** When free memory runs low it pauses the Lean probes of all formalize-paper projects of the account (at most
  10 minutes per pause) and never touches the run's own checks, so one probe, or the run's own checks alone, larger
  than the memory left can still exhaust it; the kernel's out-of-memory killer then takes a probe first (Linux). A
  probe compiled without the wrapper prints no note when it was paused, so a pause can make a tool call reach its
  600 s limit with no explanation in its output; the guard's log
  (`/tmp/formalize-paper-lean-slots/guard-<uid>.log`) has it. Under Codex the guard starts with Stage 1's
  `lean_slot.py --show` or the first lane prompt at the latest. On macOS a probe killed while paused is resumed only
  by the 10-minute cap, and the free-memory figure is an estimate; a process the guard cannot read (`ps` output it
  cannot parse) is never paused. A paused probe whose shell was killed is resumed by the orphan test only when it
  is reparented to pid 1; under a subreaper (WSL's init, `systemd --user`) the 10-minute cap and the probe's own
  time limit bound it instead. Under WSL the guard decides on the Linux VM's
  memory; Windows' free memory is only reported. Up to a second passes between its checks. A paper on a heavy
  library may not fit on an 8 GB computer without swap: it is then slow, with a note at Checkpoint A.
- **A missing-theory decision line in the log's own words is judged by the next review round, not at once.** When a
  logged decision mentions missing theory but is not in the required form, the next adjudicator rules whether it is
  one. A line logged after the last round (a delegated Checkpoint C decision) costs one more full round; delivered
  without that round, the summary, the report and the README say it was "not judged by an independent agent". If
  an adjudicator wrongly rules a line a missing-theory decision, the agent may dissent once and a second reviewer
  rules again; that second ruling is final. A disputed line delivered before the second ruling is shown as "ruled a
  missing-theory decision by an independent reviewer; disputed by the operator; not re-ruled".
- **Which lines an adjudicator was shown is read from its prompt file, which the record does not commit.** A ruling
  counts only from a round's first adjudication commit (or a re-vote adjudication that holds re-vote reviews), and
  only for a line the round's adjudicator prompt listed; that prompt file is not part of the committed record, so
  this second condition adds little beyond the first.
- **A redo can close on items its fresh round did not examine.** A stop whose round was set aside closes on the
  fresh round that redoes it; an item a lane there left NotDoneYet (a vacuous lemma, say) counts once that round's
  adjudicator recorded it UNCOVERED. Such an item is still reported as not examined, with no verdict, and a carried
  Fail still needs its own decision row; nothing reads it as passed.
- **A human's quoted answer containing a dated decision tag** (`[DELEGATED 2026-…]`) is still checked as a tag, and
  so is an `answered` line whose answer opens with a tag. An answer that points to an option the agent offered (an
  escalation's answer, an adjudicator's record, the conservative rule) counts as the human's answer; the summary
  says it adopts that source (approver, 2026-11-15).
- **Notes at delivery are judged once.** One fresh reviewer judges the checking program's delivery notes after the
  first delivery; a note first raised at a later delivery, or whose text changed since (a count, a hash), is listed
  in the README as not judged. The README names every note that, by the record, no independent reviewer judged.
  The formalizing agent saves the reviewer's `delivery-review/NOTES.md`, so the record cannot show who wrote it; its
  verdicts count as the reviewer's only when it was committed under the subject "delivery review", and the README
  and RUN_RECORD.md say so beside them.
- **The Checkpoint A resume hint reads a free-text line.** On resume, an intake that merely mentions "Checkpoint A:
  OK" may skip showing Checkpoint A again (deferred: a stricter match could add a wait for the human).
- **A cited Lean name whose first part is no Lean name is judged only at delivery** (DESIGN-SW2B X1, X2). The
  checking program cannot tell Lean dot notation on a variable (`G.Adj` for `SimpleGraph.Adj G`) from a wrong name
  whose first part also resolves to nothing (`Turan.bound_le`, a misspelt `Finest.card_le`), so both are notes, not
  failures, in the sign-off check and in the records' line citations. Only the delivered sheet and report are
  re-checked at delivery and judged by the notes reviewer: a note on a round that was set aside or replaced, or on a
  name the sheet does not render (an undocumented key of the writer's JSON), reaches no judge; under `involved` the
  human may approve a sheet before that judgement. A Mathlib
  declaration or namespace named like a variable (`X`) would keep the old failure (a probe of A-Z found none).
- **A "what" cell of SKIPPED.md explains a lettered, appendix, primed or part label only as its first label** (the
  one the result's status reads: "Corollary 5, a case of Theorem A" explains Corollary 5, not Theorem A), its letter
  case-sensitive; a numbered label a later part of the cell names still counts, as before.
- **"PAPER_DEFECTS row 2, 3 lanes agree" is still read as citing row 3** (a date or a year after a comma no longer
  is); the operator rewords the line.
- **A stray script in audits/ is listed, not judged.**
- **The PDFs are produced and checked by agents.** The markdown delivered beside each PDF is the
  authoritative text.
- **At the `involved` level, two delivered documents can show answered questions as still open.** REPORT's
  section 8 and RUN_RECORD's question rows may be written before your Checkpoint C answers; they can then list
  as open questions you answered at Checkpoint B, at a re-approval or at Checkpoint C. `DECISIONS.md` and the
  run log record every answer correctly: trust them over those two tables. To be fixed in the next version.
- **A note about running the tool can be recorded as a condition on the paper.** If your intake answer to the
  last question (memory, a test run, a shared machine) is recorded in `CONDITIONS.md` as a condition on all
  results, the summary's K line can read "K reached for 0 of N" even though the report finds no mathematical
  gap (seen once, under Codex). Read the report and `CONDITIONS.md` before the K line. To be fixed in the next
  version.
- **Platforms.** Most tested on Linux (Debian or Ubuntu, or Ubuntu under WSL2) with Claude Code. macOS (the separate `macos` branch) and the Codex CLI have had fewer runs, but both have delivered real papers: under Codex, a 5-page paper on Linux and on an 8 GB Mac; on the Mac under Claude Code, Ramanujan's proof of Bertrand's postulate; a "model at capacity" error can pause a Codex run until you type `resume`.
- **Time and usage.** A run takes hours even for a short paper (a 35-page paper took about 16 hours of active
  run time on an earlier version), and it uses a large share of a subscription's usage limits.

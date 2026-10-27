# Re-approval

Read this when an approved statement, or a definition one uses, must change, or the freeze check
reports DRIFT. Who may decide is RUN.md, "Statement changes after approval" (always read first:
under `hands-off` its limits apply, and the begin command comes before the edit).

A statement must change, or the freeze check reports DRIFT (a freeze stop).

**A DRIFT** (a change made without a begin) is a stop. In `release` its cure is always to restore the
approved statement (`git checkout <approval commit> -- <its file>`, or revert the edit), commit, and
close it `--cured`; never begin a re-approval inside the open stop (the begin refuses a declaration
that has already changed). If the change is wanted, begin a re-approval afterwards, as below.

**An intended change** (for example an approved lemma found false) follows the steps below. Who
decides depends on the level (U2 §0, §5), the same in `release` and `dev`:
- `hands-off`: you decide (step 4), tagged [DELEGATED …; reversal: re-approve].
- `statements-only` and `involved`: a **QUESTION** for the human, never a stop. Begin (step 1),
  ask, and keep working on everything else. Until they answer the **pending state** holds: rounds,
  Phase 0 (`--readonly` too), `pending_unproved` and the axiom sweep accept `sorry` in the changing
  statement's proof and sorryAx reaching other results only through it; only `project.py --deliver`
  refuses (`PENDING[question]`, not a failure: open no stop on it).
- A goal result found false stays stop 1 (`--cause unproved-goal`).

**A refuted statement** (U2 §3; the same rule before and after approval): a statement is refuted
when a refutation compiles -- `def <ns>.<X>_as_printed : Prop :=` the approved statement, and a
proved `theorem <ns>.not_<X>_as_printed : ¬ <ns>.<X>_as_printed`. Begin its repair with
`python3 audits/signoff.py reapprove --begin --refuted-by <ns>.not_<X>_as_printed --reason "<why>"`
(`--decls` may be left out; if given it must list `<ns>.<X>`). It refuses unless, checked in Lean:
the theorem's type is `¬ <X>_as_printed`; its axioms are standard (collectAxioms: no `sorryAx`; the
refuted `<X>`'s own `sorry` may stay, it is false); and `<X>_as_printed` is definitionally equal to
the statement approved at B -- or, once a correction of `<X>` was re-approved and turned out false
too (a failed correction), it is the same `_as_printed`, unchanged, that the first repair checked
(never a refutation of a later encoding). A goal result is refused: a goal found false is stop 1.
The record (`REAPPROVAL.json` `refuted`) obliges a PAPER_DEFECTS.md `false` row naming the
refutation, or an encoding-error line (F10), and a minimal repair (typo, add hypothesis, local)
cites the paper-faithfulness lane's F12 verdict (the step of the paper's proof using the added
hypothesis; AUDIT_PROTOCOL.md, "A REPAIR"); otherwise the row's repair is `substantial`. The same rule
holds for a `false` row whose corrected statement was stated before the approval: every round, the
paper-faithfulness lane's prompt lists each `false` row with a minimal repair, with the item name
"F12: the repair of <result>" (the label the row's `where` cell begins with). Only that item counts;
for a re-approved result, only from a lane run after the latest `--begin` (a failed correction is
confirmed afresh). Under
`hands-off` you repair it and disclose it (never a stop); under `statements-only` and `involved` it
is the human's QUESTION (the pending state holds; only delivery waits). Then steps 2-4 below.

**Which sheet ships (M5).** The sheet of the latest approval, with each changed result marked
**CHANGED since the approval of <date>** (the marks are kept when it is rendered again after its
approval). After several re-approvals it marks every result changed in any of them, each since the
approval it last changed after. Under `involved` and `statements-only` the human approves it with `approve --by human`,
which refuses until the sheet's fresh-reader check passes (`readers.py --doc signoff --round <R>
--check`) and unless the PDF the human reads is the one rendered from the sheet as it is now
(`render_record.py check`; render it before asking, `render-pdf.md`). Under `hands-off` its first line says "Statements unchanged since the latest approval; K
re-approved by the agent, marked CHANGED."

1. Before the edit, begin the re-approval: `python3 audits/signoff.py reapprove --begin --decls
   <a,b> --reason "<why>"`. It refuses a declaration that has already changed: after a DRIFT, the
   human decides; to re-approve that change, revert it, begin, and make it again.
2. Make the change and commit it. The approval stays in place; `signoff.py approve` (step 4) moves
   it aside to `APPROVED_FINGERPRINTS.<date>.json` and closes `REAPPROVAL.json` in its `approve <R>`
   commit. Never move it by hand: a `closed: true` committed any other way (not by that `approve <R>`
   commit, which also writes the new approval) is no close, and the re-approval stays open; and
   `approve --by agent` over ANY earlier approval of the run (its files or their history) is a
   re-approval under the same rule as step 4, whatever the records now say. The report check walks
   the whole history (merges included): every commit that changes `APPROVED_FINGERPRINTS.json` must
   pass the approve gate as it stood at that commit -- with no re-approval open only first approvals
   of new declarations; with one open, the agent only where it may re-approve and the human only with
   their committed answer -- and a merge bringing the records from another branch fails it. Until that approve, the re-approval is open: when it is the
   human's question, the report check (`make_report.py --check`, in Phase 0) prints
   `PENDING[question]` and the run goes on (only `project.py --deliver` refuses); one the agent may
   close itself keeps the report check RED. Either way a run is never delivered with one open.
3. Run Stage 2 steps 2–7 (`stage2-statements.md`) on the new commit, at most 2 statement rounds
   for this re-approval (the cap of step 5 there), its rendering included (under `involved` and
   `statements-only`: render the sheet's PDF, `render-pdf.md`, before asking). The sheet marks every
   result **CHANGED since the approval of <date>**.
   The begin of a question also logs it under `RUN_LOG.md`'s `## Open questions`, so DECISIONS.md
   lists it; mark it `(answered <date>: ...)` when the human answers.
4. Ask the approver the question `python3 audits/signoff.py reapprove --question --round <R>`
   prints, with the sheet's render outcome lines above it (run `python3 audits/render_record.py shown
   --doc SIGNOFF --round <R>` right before asking: it records the PDF you show, which `approve --by
   human` requires, and prints those lines), pointing them at those results in particular: does the change strengthen or weaken the
   statement? A change that is partly both, or unclear, counts as a weakening. It offers (a) and
   (b); it offers (c), letting the agent approve, only when the agent may re-approve (the rule
   below); never offer (c) otherwise. If they choose (c), that judgment is yours and is logged as
   a [PROXY] decision; the report lists every earlier approval and who made it.
   Under `statements-only` the approver types the answer (never a [PROXY]); if they are away, the
   question stays open and the run goes on in the pending state; only delivery waits. When they
   answer, log their words verbatim under `RUN_LOG.md`'s `## Re-approvals` as
   `- human answer (round <R>; <declarations>): "<their words>"` (`project.py --log`), commit it,
   then run `signoff.py approve --by human`, which refuses until that line, committed after the
   begin, names the round and every declaration of the re-approval by its full name (`N.main`, not
   `main`). A close is checked again later: one whose commit lacks that line (by the human) or that
   the agent may not make is no close, and the re-approval stays open. This is still trust-based (no script sees who typed the
   words), but the human approval is evidenced by the recorded answer. `approve --by agent` refuses (`PENDING[question]`) unless
   the level is `hands-off`, or `involved` with the intake's 5d logged as `- 5d: agent` (never
   `statements-only`), and the approval it replaces was the agent's. Under `hands-off`, do not ask:
   approve the new sheet as in Stage 2 step 8 (`--by agent`, with a `--note` saying the
   re-approval was delegated at intake). The change must be one RUN.md "Statement changes after
   approval" allows (never a strengthening or generalization; a weakening only to turn missing theory into a
   named hypothesis, or to repair a refuted statement with `--refuted-by`), logged as [DELEGATED] with
   `reversal: re-approve` in a commit made before the Lean edit.

**A rejected change.** If the human rejects the change (answer (b) naming it), the way out is to
restore the approved statement (`git checkout <approval commit> -- <its file>`, or revert the edit;
the proof may stay `sorry` meanwhile in the pending state), commit, rerun Stage 2 steps 2–7 so the
sheet shows the restored statement, log their answer verbatim as above (`- human answer (round <R>;
<declarations>): "<their words>"`), commit, and run `signoff.py approve --by human`: it closes the
re-approval on the original fingerprints. Then find another route to the proof, or a correction
they approve (a new re-approval).
**A rejected change at the cap** (the re-approval's 2 statement rounds are spent, so `scope.py
--statements` refuses the round that would show the restored statement; never a stop): restore the
approved statement as above, commit, log the answer naming the round the REPLACED approval approved
(its `round` in `APPROVED_FINGERPRINTS.json`: `- human answer (round <that round>; <declarations>):
"<their words>"`), and run `signoff.py approve --round <that round> --by human`: that sheet's bundle and
fingerprints are those of the restored statements, so it closes the re-approval on the original
fingerprints. The same holds for the first-approval cap: a sheet whose bundle is fresh can always be
approved; a mechanical refusal of the last round's records a grace round (stage2 step 7).

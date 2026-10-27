# Fresh-reader check

Read this before the first fresh-reader check of the run (Stage 2 step 7). It is one procedure for
every document a human reads.

Run this before any of these documents reaches the human:
- the sign-off sheet (Stage 2 step 7; not under `hands-off`), and the list of QUESTION rows for
  Checkpoint B (step 8);
- at Stage 5, after `project.py --prepare-delivery`: `SUMMARY.md`, `REPORT.md` and `DECISIONS.md`;
- any other summary you write for them, with `--doc other:<absolute path>`.

The reader reads the markdown, the audited content. The PDFs are made afterwards from exactly that
markdown by their own agents (`render-pdf.md`), which start only once the gate below passes.

**Modes** (fixed per document by `readers.py`, never chosen by you):
- **gated** (the summary at every level, the sheet, the QUESTION list, `other:`): the newest pass
  reads the current version and every blocking finding is answered; fix and re-read as below.
- **single** (the report, the decisions document): exactly one pass per version; a second pass on
  the same version is refused. A regenerated version gets one new pass.
- The sheet's approval-time pass stays valid while its hash is unchanged; under `hands-off` the
  delivered sheet has no reader (`signoff.py check` is kept; the README says so).

**Labels.** Each finding is `[content]` (the audit record gives something wrongly or not at all) or
`[presentation]` (how a right thing is said). On the summary, the report and the decisions document a
content finding goes to the adjudicator's **reader-fix round** (`prompt.py 4 --round <newest round>
--reader-fix --write`, at most two per run; `run/stage5-delivery.md` step 5), never to your own edit;
it may be answered `unfixable` only once both rounds are spent. A fault in a **generated** document
(`SUMMARY.md`, `REPORT.md`: a presentation finding, or a content finding the generator, not the record,
gets wrong) is never `unfixable`; you answer it one of three ways (step 3, "A fault in a generated
document"): reject it with a reason, fix the generator, or hand-edit the document. In dev a blocking
finding left unfixable past the budget is a stop.

The Checkpoint C message only points to checked documents. It needs no pass, but it must be true
(AUDIT_PROTOCOL.md, "Documents a human reads", rule 4).

**What the gate enforces.** `readers.py` checks two things:
- the newest well-formed pass read exactly the version you deliver;
- **every** `- BLOCKING:` finding that any reader ever raised about this document is answered.

So re-running a reader gains nothing: the findings it would wash away must still be answered.

1. **Mechanical check first.** Fix what it finds before any reader sees the document:
   - sheet: `signoff.py check --round <R>`, then `signoff.py render --round <R>` (it writes
     `SIGNOFF.md`);
   - report: commit, then `phase0.py` (it regenerates `REPORT.md` and `SUMMARY.md`);
   - decisions document: `decisions.py --check`.
2. **Spawn a reader.**
   ```
   python3 audits/prompt.py --prompt fresh-reader --doc signoff|questions|summary|report|decisions|other:<path> --round <R> --write
   ```
   `<R>` is the sheet's round for `signoff` and `questions`, and the newest round otherwise (a
   directory with a TARGET.json; never create a round directory for a reader: it is refused). An
   `other:` document must lie inside the rounds directory. Spawn **one new**
   general-purpose agent with the printed sentence and nothing else. The script fills everything;
   you add no words.

   The reader saves its record itself by piping it into `readers.py --save` (the prompt gives
   the command), which checks it, writes `<rounds dir>/readers/<key>-<n>.md` and commits it
   alone as `reader <key> <n>`, so no record can vanish before it is on record. If the reader
   could not run commands and returned the report as text, pipe that text into the same command
   yourself, unedited: never retype or summarize it. The key names the document and its cycle: `signoff-<R>`, `questions-<R>`, `summary-<newest round>`, `report-<newest round>`,
   `decisions-<newest round>`, or `other-<name>-<id>` (an `other:` document's history is tied to its
   path: never copy it to a new name to check it again). If the reader returned without committing,
   commit the file exactly as it is. Never edit, rename or delete a record: the gate reads every
   record as it was first committed, so an edit changes nothing except that the checkpoint message
   must report it (`readers.py --check` prints it as a NOTE). Never rewrite the history of the
   audits repository (`reset`, `--amend`, `rebase`): that is the one way to remove a record, and it
   is forbidden. If `--write` refuses because the prompt for that pass number exists, spawn that
   prompt; if it was never spawned, or HEAD moved since it was written, delete it and write it
   again.
3. **Answer every blocking finding.** For pass n, write `readers/<key>-<n>.response.md` with one line
   per `- BLOCKING:` finding. Each line copies the **start** of the finding (at least 15
   characters, or all of a shorter finding; enough that it matches no other finding of that pass,
   or the whole finding when it is the start of another), then a spaced em dash ` — ` and the
   answer. The quote may itself contain ` — `. There are three answers:
   - `- fixed: <quote> — <what you changed>`. Fix the sheet and the report through their sources or
     the generator, or (the summary and the report, after the final prepare) by a recorded hand edit,
     never by an unrecorded edit of the output (AUDIT_PROTOCOL.md, "Fixing a generated
     document"; "A fault in a generated document" below). Then rerun step 1 and spawn a new reader. The gate accepts `fixed` only once a
     later pass has read a changed version of the document.
   - `- dismissed: <quote> — <evidence that the finding is wrong, or why it is trivial>`, with file:line and what it
     says. The next reader is not told. If it raises the point again, answer it again; the human
     sees every dismissal (Checkpoint B and C messages).
   - `- unfixable: <quote> — <why nothing can fix it, and what will>`, for a correct finding that
     nothing can fix: a finding about the paper itself, a record whose owner step is closed, a content
     finding past the reader-fix budget. Never a fault of a generated document's own text ("generator
     fault"): `readers.py --check` refuses that (below). Quote the
     finding also in the notice `<rounds dir>/KNOWN_FAULTS-<key>.md` (delivered folded into
     `RUN_RECORD.md`, never as a file of its own).

   **A fault in a generated document** (`SUMMARY.md`, `REPORT.md`; approver 2026-10-25): when a fresh
   reader, the status check or a PDF agent finds one, choose one of three, each recorded:
   1. **Reject** it: `- dismissed: <quote> — <reason>`: not a real problem (with evidence), or
      `trivial:` it affects neither faithfulness nor readability (say why).
   2. **Fix the generator** (release): `stops.py open --note "<the finding>" --cause tool-bug`, then the
      tool-patch route (RUN.md "Tool patches": a fresh reviewer approves the patch), `close --cured
      "tool-patch TP<k>"`, prepare again and give the regenerated document its new pass. Answer
      `- fixed: <quote> — tool patch TP<k>`. In dev a generator bug is the maintainer's (a stop).
   3. **Hand-edit the document**, when a generator patch would be dangerous (it touches logic many
      documents share, or the core). Only after the **final** prepare (a later prepare regenerates the
      document and erases the edit: prepare names it, and the answer below then refuses the gate).
      Edit the markdown in place, then
      `python3 audits/readers.py --doc summary|report --hand-edit --finding "<record>: <quote>"`
      (`<record>`: the agent's committed file under the rounds directory, e.g.
      `readers/<key>-<n>.md` or `status-check/FINDINGS.md`). It records `hand-edits/HE<k>.json` and
      `HE<k>.diff` and commits them with the document, alone, as `hand-edit HE<k> <doc>`. Answer
      `- fixed: <quote> — hand edit HE<k>`. Then a fresh reader reads the edited version (step 2), the
      status check runs again and judges every hand edit (`run/stage5-delivery.md`), and the PDF is
      rendered from the edited markdown. An edit may not change a result's status, a statement, a defect
      row's verdict or a human answer unless the status check confirms it matches the records:
      `--deliver` refuses an edit the check did not judge `OK`. Never edit a generated document any
      other way: `--deliver` refuses a change no recorded hand edit explains.
   The sheet (`SIGNOFF.md`) and the README are never hand-edited: (1) or (2) only.

   Commit the response file, and the notice if any, as `reader <key> <n> (response)`. Response
   files are records too: to correct a committed one, add `readers/<key>-<n>.response-2.md` (then
   `-3`, …); the gate reads them all, and the last answer to a finding counts. The gate names any
   response line it could not parse.
4. **A malformed report is a mechanical failure.** That means:
   - a missing or malformed first line, coverage line or verdict line;
   - a verdict whose count differs from its `- BLOCKING:` lines;
   - COULD NOT CHECK entries caused by a wrong path in the prompt.

   Commit it anyway and answer its `- BLOCKING:` lines like any others. Then spawn a new reader on the
   same document, and log the failure under "Mechanical failures".
5. **When to stop fixing.** After 3 passes that still report blocking problems, stop fixing: mark
   what remains `unfixable` with the reason "fix budget reached" (this counts as nothing open in
   this run), and deliver with the notice. A fault in a generated document is not "nothing open":
   answer it as step 3 says (reject, generator, hand edit). The
   notice is never written into the document itself, since that would change what the reader
   read. It is delivered next to the document and quoted verbatim at the top of the checkpoint
   message.
   The checkpoint message says the fix budget was reached. Expect this for a long hand-written
   document; it is not a failure of the run.
6. **The gate.** Run it for each document before Checkpoint B (the sheet and the QUESTION list) and
   before delivering at Stage 5:
   ```
   python3 audits/readers.py --doc signoff|questions --round <R> --check   # Stage 5: --doc signoff --round approved
   python3 audits/readers.py --doc summary|report|decisions|other:<path> --check
   ```
   It refuses, naming the case, unless the newest well-formed pass read exactly the version you
   deliver, every blocking finding of every pass (malformed ones included) has exactly one matching
   answer, every `fixed` was re-read by a later pass, every `unfixable` is quoted in the notice,
   `DECISIONS.md` is tagged for the newest round, and every record and notice is committed; git
   errors fail closed. Records edited or deleted after their commit do not refuse the gate (it reads
   them as first committed); it prints them as NOTE lines, and the checkpoint message repeats them.
7. **Log** each pass in `RUN_LOG.md` under `## Fresh readers`: document key · sha256 · commit ·
   pass n · verdict line · reader file. Never write that a gate "passed" when it ended with blocking findings
   answered `unfixable` (at the fix budget or not): say what happened, as the gate's summary line does
   ("NOT passed: … answered unfixable"). `readers.py --check` refuses a run-log line that says such a
   gate passed, and the delivery README states each document's outcome from the record.

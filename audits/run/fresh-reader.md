# Fresh-reader check

Read this before the first fresh-reader check of the run (Stage 2 step 7). It is one procedure for
the documents a human reads before the mathematics is verified.

**Not at delivery**: `SUMMARY.md`, `REPORT.md` and `DECISIONS.md` have no fresh
reader. You write them, four delivery reviewers advise and you judge (`run/stage5-delivery.md` step 5):
no reader pass is run for them, and nothing about them is a stop. An older run's summary, report and decisions
reader records are still checked by `readers.py --check`.

Run this before any of these documents reaches the human:
- the sign-off sheet (Stage 2 step 7; not under `hands-off`), and the list of QUESTION rows for
  Checkpoint B (step 8);
- any other summary you write for them, with `--doc other:<absolute path>`.

The reader reads the markdown, the audited content. The PDFs are made afterwards from exactly that
markdown by their own agents (`render-pdf.md`), which start only once the gate below passes.

The Checkpoint C message only points to checked documents. It needs no pass, but it must be true
(AUDIT_PROTOCOL.md, "Documents a human reads", rule 4).

**What the gate enforces.** `readers.py` checks two things:
- the newest well-formed pass read exactly the version you deliver;
- **every** `- BLOCKING:` finding that any reader ever raised about this document is answered.

So re-running a reader gains nothing: the findings it would wash away must still be answered.

1. **Mechanical check first.** Fix what it finds before any reader sees the document:
   - sheet: `signoff.py check --round <R>`, then `signoff.py render --round <R>` (it writes
     `SIGNOFF.md`);
2. **Spawn a reader.**
   ```
   python3 audits/prompt.py --prompt fresh-reader --doc signoff|questions|other:<path> --round <R> --write
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
   yourself, unedited: never retype or summarize it. The key names the document and its cycle: `signoff-<R>`, `questions-<R>`, or `other-<name>-<id>` (an `other:` document's history is tied to its
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
   - `- fixed: <quote> — <what you changed>`. Fix the sheet through its sources or the generator,
     never by an edit of the output (AUDIT_PROTOCOL.md, "Fixing a generated
     document"; "A fault in a generated document" below). Then rerun step 1 and spawn a new reader. The gate accepts `fixed` only once a
     later pass has read a changed version of the document.
   - `- dismissed: <quote> — <evidence that the finding is wrong, or why it is trivial>`, with file:line and what it
     says. The next reader is not told. If it raises the point again, answer it again; the human
     sees every dismissal (Checkpoint B and C messages).
   - `- unfixable: <quote> — <why nothing can fix it, and what will>`, for a correct finding that
     nothing can fix: a finding about the paper itself, a record whose owner step is closed. Never a
     fault of a generated document's own text ("generator fault"): answer that as below. Quote the
     finding also in the notice `<rounds dir>/KNOWN_FAULTS-<key>.md` (delivered folded into
     `RUN_RECORD.md`, never as a file of its own), and commit the notice with your response under
     exactly the subject `reader <key> <n> (response)` (another subject is a `NOTE[notice-subject]`).

   **A fault in a generated document** (the sheet): when a fresh
   reader or a PDF agent finds one, choose one of two, each recorded:
   1. **Reject** it: `- dismissed: <quote> — <reason>`: not a real problem (with evidence), or
      `trivial:` it affects neither faithfulness nor readability (say why).
   2. **Fix the generator** (release): `stops.py open --note "<the finding>" --cause tool-bug`, then the
      tool-patch route (`run/stops-and-set-asides.md` "Tool patches": a fresh reviewer approves the patch), `close --cured
      "tool-patch TP<k>"`, prepare again and give the regenerated document its new pass. Answer
      `- fixed: <quote> — tool patch TP<k>`. In dev a generator bug is the maintainer's (a stop).

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
   answer it as step 3 says (reject, or fix the generator). The
   notice is never written into the document itself, since that would change what the reader
   read. It is delivered next to the document and quoted verbatim at the top of the checkpoint
   message.
   The checkpoint message says the fix budget was reached. Expect this for a long hand-written
   document; it is not a failure of the run.
6. **The gate.** Run it for each document before Checkpoint B (the sheet and the QUESTION list) and
   before delivering at Stage 5:
   ```
   python3 audits/readers.py --doc signoff|questions --round <R> --check   # Stage 5: --doc signoff --round approved
   python3 audits/readers.py --doc other:<path> --check
   ```
   It refuses, naming the case, unless the newest well-formed pass read exactly the version you
   deliver, every blocking finding of every pass (malformed ones included) has exactly one matching
   answer, every `fixed` was re-read by a later pass, every `unfixable` is quoted in the notice,
   and every record and notice is committed; git
   errors fail closed. Records edited or deleted after their commit do not refuse the gate (it reads
   them as first committed); it prints them as NOTE lines, and the checkpoint message repeats them.
7. **Log** each pass in `RUN_LOG.md` under `## Fresh readers`: document key · sha256 · commit ·
   pass n · verdict line · reader file. Never write that a gate "passed" when it ended with blocking findings
   answered `unfixable` (at the fix budget or not): say what happened, as the gate's summary line does
   ("NOT passed: … answered unfixable"). `readers.py --check` refuses a run-log line that says such a
   gate passed, and the delivery README states each document's outcome from the record.

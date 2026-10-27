# Rendering a PDF (renderer, verifier, checkers)

Read this before the first PDF of the run (Stage 2 step 7, or Stage 5 step 5 under `hands-off`).
It is one procedure for every PDF a human reads: `SUMMARY.pdf`, `REPORT.pdf` and `SIGNOFF.pdf`. `RUN_RECORD.md`, the run record, is never rendered: it is delivered as markdown only.

The generators write markdown only. A document's markdown is audited first (its code checks and
its fresh-reader gate, `fresh-reader.md`); only then is it rendered, by fresh agents, never by you
and never by a script. You never read a PDF, never write a verdict and never compose a prompt
(RUN.md, rule 13). Nothing here is ever a stop, in any mode, and nobody is asked anything.

**The loop** (`render_record.py next` names each step; follow it, never your own judgement):
1. **A, the renderer**, makes a PDF of the md with any engine, layout or method: faithful to the md
   and readable (it may rephrase or re-lay out for readability, never change the mathematics; Lean
   code character for character).
2. **B, the verifier**, reads the whole md and every page and says `PASS` or `FAIL (<n>)`. On `FAIL`,
   a fresh A gets the next round with its previous source and B's findings.
3. On `PASS`, two fresh **checkers**, in parallel, judge only whether the PDF says mathematically the
   same thing as the md. If either says `DIFFERENT`, its findings go back to a fresh A as the next
   round, then B, then a fresh pair of checkers.
4. All of it inside one budget of 6 renderer rounds per version of the md. Once it is spent, the
   least bad round ships: a fresh A adds a cover page listing every remaining objection (B's and the
   checkers') verbatim, a fresh cover verifier checks it (those objections exactly, the round's pages
   unchanged behind it), and the md is delivered beside the PDF as the authoritative text. A cover
   its verifier does not pass never ships: a second attempt gets the rejection; after two attempts
   without a pass the round ships without a cover, disclosed.
5. `finish` ships the chosen PDF to the document's usual path. If no round produced a PDF, the md
   ships alone (`no-pdf`), disclosed. The run always finishes.

**Commands.** `D` is `SUMMARY`, `REPORT` or `SIGNOFF` (with `--round <R>`, or `--round approved` at
Stage 5):

```
python3 audits/render_record.py next --doc D [--round R]        # the one next step: run what it prints
python3 audits/render_record.py begin --doc D [--round R]       # refuses an md not audited at its hash
python3 audits/prompt.py --prompt render-a|render-b|render-cover|render-cover-check|render-check --doc D [--round R] [--n 1|2] --write
python3 audits/render_record.py fail --doc D [--round R] --role A|B|cover|cover-check|checker [--n 1|2] --why "<what happened>"
python3 audits/render_record.py finish --doc D [--round R]
python3 audits/render_record.py check --doc D [--round R]       # the guard: the PDF is the recorded one, of this md
```

**Spawning.** `prompt.py … --write` fills the prompt for the step `next` names, commits it with its
hash, and prints the spawn line. Spawn ONE new `general-purpose` agent with exactly that line and
nothing else (Codex: `agent_type` `formalize_renderer`, fresh context, `spawn-and-seal.md`). Each
agent saves its own output (`render_record.py save`, which checks the format and the hashes and
commits it alone as `render <key> …`). `save` and `fail` refuse a step whose prompt was not issued
(written and committed by `--write`): every recorded output answers the prompt on record. If an agent returns its output as text without saving, pipe
that text into the save command its prompt names, unedited. B and the checkers are blind: they get
the md and the PDF, never A's notes, an earlier verdict or each other's output.

**Parallel.** At Stage 5 render SUMMARY and REPORT (and the sheet, when it needs it) at the same
time: each document's loop is independent, and their saves take a lock and retry a busy index.
Spawn both checkers of a round at once.

**A usage limit or a capacity error is not a failed round.** Wait it out as `spawn-and-seal.md`
("Retry budget") says -- until its reset time, or with its backoff -- and then spawn the agent again
with the same line (the same `--write` prints it again; nothing new is committed). Such a wait never
counts as the respawn below, never as a `fail`, and never opens a stop.

**An agent that fails** otherwise (a crash, a refusal, no save) is a mechanical failure, but for
rendering agents the 2-hour retry budget of `spawn-and-seal.md` does NOT apply: respawn it at most
once with the same line, then record it with `render_record.py fail`, and go on. A failed A round counts toward the 6; a
round with no B verdict is unverified (it ranks below every verified round for least bad); a
checker that did not run is never looped on and never a pass: the outcome is then
`checkers-did-not-run` (never `verified`, which needs both checkers' recorded SAME), and its lines
say plainly that the checkers did not run; a cover that failed, or that no
verifier passed, never ships (after two attempts the least bad PDF ships without a cover).
Never open a stop for any of these, and never wait for a person.

**Restarts.** All state is in `<rounds dir>/pdf/<key>/RENDER.json` and the committed files beside
it (every round's PDF, source and verdict). After a restart, run `next`: it restores what an
interrupted command left uncommitted, then names the step. An agent you spawned before the restart
is lost: record its step `fail` (or respawn it once, as above).

**The md changes** (a new prepare, a reader fix, the approval stamp on the sheet): every output on
the old md is refused, `next` says `begin`, and the loop starts again at round 1 with a new budget.
Only a document whose md changed is rendered again.

**The guard.** `project.py --deliver` and `signoff.py approve --by human` refuse unless the PDF at
the document's usual path is the one `RENDER.json` shipped and was made from the md as it is now
(`render_record.py check`; `no-pdf` passes, the md ships). On a refusal, render again: never a
stop.

**What the human is told.** `render_record.py next` prints `DONE[render]` with the outcome lines:
the outcome, the rounds, every remaining objection, each checker's verdict and findings, and A's
notes (NOTE lines: a suspected md error A saw, which nobody acts on). Quote them in the Checkpoint B
and C messages and the completion message; `--deliver` writes them into README section D.

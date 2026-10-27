# Stops and set-asides

Read this when a check stops the round (RUN.md, failure table) or a round must be set aside. What
happens to each cause is decided by its code (`project.CAUSES`, shown as `KIND[code]` on the failure
line), never by its wording. Every stop is recorded, whoever clears it (the run record
`RUN_RECORD.md`, "Every stop of the run").

1. **Record the stop** with the failing check in its exact read-only form, for example
   `python3 audits/stops.py open --cmd "python3 audits/integrity.py --check --round <R>" --round <R>`.
   (A lanecheck run with `--kill` is recorded without it: `--kill` is an action, not a check.)
   It runs the check itself, refuses one that passes or only reports a normal state (the freeze
   check's `NOTE[not-approved]` or `NOTE[reapproval]`), and records the raw output with the class
   of each failure line. A failed tool call that is not a check: `open --note "<what failed>"
   --cause tool-call` (in `release` mode with `--check "<the read-only check of the step that
   failed>"`, below). One stop is open at a time (the script refuses a second).
   **A failure with no cause code** (a check script crashing with a Python traceback, an error
   message no code covers, git or Lean/lake failing unwrapped) is first recorded with `open --note
   "<what failed>" --cause unknown-retry` and re-run within the retry budget (`spawn-and-seal.md`);
   if it passes, close it. If it persists, close it naming the next stop and classify it: a traceback
   whose innermost frame in the project is in `audits/` is a bug in a pinned script, `--cause
   tool-bug`, a STOP class (you never edit a pinned script by hand: in `dev` a maintainer fixes it; in
   `release` it is the tool-patch route below, and a fault in the proof-validity core, which no patch
   may touch, is a Lean-side workaround or `stops.py core-fault` and `close --core-fault` after a
   fresh reviewer's approval, RUN.md "Tool patches"); anything
   else (git, Lean/lake, network, filesystem) is `--cause env-unknown`, which you fix as an
   environment fault (RUN.md, "Stops that remain at every level") and close with `--delegated`,
   asking the human only after the retry budget. The scripts themselves still class a code nobody
   recorded as unknown, a stop: this retry and classification is your step.
   **In `release` mode** the retry itself is the stop: `open --note "<what failed>" --cause
   unknown-retry --check "<the read-only check of the failed step, failing now>"` (a FORMS command),
   then cure and `close --cured`; `--delegated` is dev mode only. **A child's capacity error or usage limit opens no stop.** A child agent's
   capacity error or usage limit is waited out within the 2-hour time budget (`spawn-and-seal.md`)
   and logged under "Mechanical failures" only, in both modes; it is a stop only once that budget
   is spent with the failure unchanged. Open `--cause env-unknown` (stop 3, a human
   stop) only after the retry budget is spent, and in `release` only after you tried to remove the
   cause yourself -- a plain retry, or a tool patch (protocol text included: a subagent whose file write
   Claude Code refuses is told to return its text) -- and only for a login, a quota or usage limit,
   payment, OS or administrator rights, or another program changing the project's files; a pinned script that keeps crashing is `--cause
   tool-bug`: with the failing read-only check as `--check` a self-cure, and with no check failing
   (a pinned writer such as `prompt.py` or `signoff.py approve` crashing while every read-only check
   passes) `--cause tool-bug` without `--check`, which in `release` is the tool-patch route
   (`close --cured "tool-patch TP<k>"`), never a human stop.
2. **A STOP class** -- tamper, apparatus, freeze, gitmeta, proof, tool-bug, and any failure line whose code
   is unknown or missing -- waits for the human at every level. Show the raw output and record the
   answer: `python3 audits/stops.py close --stop S<n> --human "<their answer, verbatim>"`. Under the
   involved level every stop is the human's.
   **Release mode** (RUN.md, "Stops that remain at every level", and the release column under its
   failure table): a stop with no cause of kind human is a **self-cure** at every level instead.
   `open` prints the cure of each code's kind (`project.CURES`) and the code's own text; apply it,
   then `python3 audits/stops.py close --stop S<n> --cured "<what was done>"`. The cure re-runs
   exactly the read-only check the stop recorded at open, never a substitute and never a writer: a
   `--cmd` stop's check, or for a `--note` stop the read-only check of the step that failed, given at
   open as `--check "<it>"` (required in `release` except for a human code; it must fail then; the
   failed tool command itself is never the check; an uncoded failure is `--cause unknown-retry`). A
   code with a closer of its own (`project.CLOSER`) records exactly that closer, on the stop's
   `--round` (leave `--check` out and `open` records it).
   `--delegated` is dev mode only. It must pass; each failing attempt is committed as
   `S<n>/CURE<k>.json` ("stop S<n> cure <k>"). The failure tally counts, from git history and
   across stops, failed attempts per fault key (check script, cause code; a `--note` stop: the codes
   its check printed, `unknown` when uncoded) over the whole run, and openings per key and round (a
   `--note` stop's code, round and check script too, the retry codes and `commit-refused` sharing one); passes are
   not counted. The cure budget is spent (under any new stop or code) by 2 failed cures of one stop,
   3 of one fault in the run, or a 4th opening of a fault in a round after a failed cure of it there;
   then classify it (`stops.py classify --stop S<n> --as tool-bug|interference|other --evidence
   "<why>"`): a tool bug is the tool-patch route, outside interference (another program that keeps
   changing the project's files) is stop 3, the human's, anything else one more cure. A made-up
   or mistyped `--round` is refused at `open` (nothing recorded): give the round of this run. A history
   fault no cure clears (RUN.md, "History faults no cure clears") is acknowledged after a fresh review
   (`integrity.py --ack-request`), never a human stop. The four release stops (RUN.md, "Stops that remain at every level") are
   the codes of kind human: `unproved-goal` (1), `outward-action` (2), `env-unknown`,
   `codex-approval`, `interference` (3; a denied command is a stop 3 only after its plain retry --
   exactly `python3 audits/<script>.py <args>`, no env prefix, pipe or chaining, RUN.md rule 12 -- is
   denied too) and `ambiguity` (4: a genuine ambiguity of the paper,
   asked under every level, `hands-off` included; after `close --human` the run resumes at its
   own level). A
   tampered round's set-aside names the stop (`set-aside <R> --stop S<n>`, accepted while that stop
   is open or self-cured; it carries forward the Fails of each lane's SEALED verdict, read from git,
   even if the file was changed after its seal, and is refused when the sealed verdict cannot be
   found); its `close --cured` then re-runs the check on the fresh round that redoes it (a round scoped
   after the set-aside while the stop is open, so its TARGET.json names the set-aside round as
   `redo_of`, its sealed verdicts judging every item of the set-aside scope -- use `--full` to redo
   a full or statements round; recorded as `redo_round`; refused, no attempt spent, until there is
   one; a check naming no round also runs `lanecheck.py --round <fresh round>`; a failure with other
   codes there is charged to those codes), since the set-aside round keeps its faulty files; an ownership FAIL is reverted, never waived: `stops.py revert --stop S<n> --commit <the
   commit the FAIL names>` restores the records it changed without owning them, and integrity.py accepts
   the revert once verified by content, never by its subject (the exact inverse of that commit's
   change to records it did not own; `git revert` of it qualifies too). It
   excuses only the files it restored: every other change of that commit (a set-aside lane, say)
   is still checked and stays a FAIL. RUN_LOG names what it restored and what it did not. A commit
   that changed nothing it does not own (a reviewer's) cannot be reverted. `head-moved` (release):
   `tree_state.py --revert-foreign` reverts the whole foreign range (`git revert`, `-m 1` for a
   merge, no hook run; refused while `gitmeta` fails); the check accepts it only when HEAD's tree
   equals the tree hash the baseline recorded. `gitmeta` (release): `tree_state.py --restore-gitmeta` restores only the hooks and config keys of the
   Stage 1 snapshot the pin recorded; a changed identity, destination or hooks-directory setting, a
   history substitution, or pinned history no longer an ancestor of HEAD, also prints `env-unknown`
   (RUN.md lists them): stop 3, the human's.
3. **Any other class**, under a delegating level in `dev` mode (in `release` mode it is a self-cure,
   above): cure it as the failure table says (mechanical:
   "A child that failed mechanically" in `spawn-and-seal.md`, or the code's own cure; document:
   RUN.md's narrow exception; lane-fault and settle: the adjudicator), then `python3 audits/stops.py
   close --stop S<n> --delegated "<what was done>"`. It re-runs the check, refuses while it still
   fails or for a STOP class, and logs the [DELEGATED] line.
   **Class record-fix** (`dead-witness`, `record-cite`: an adjudicator's record cites what does not
   exist) is yours at every level, the involved level included: cure it by a record correction
   (RUN.md failure table; AUDIT_PROTOCOL.md "Record correction"), then `close --delegated` (`release`:
   `close --cured`). A stop
   mixing it with another class follows that other class. **Class adjudication** (`adj-record`:
   any other fault of an adjudicator's record, or a carried item without its row) is likewise
   yours: Phase 0 shows it as `PENDING[adjudication]` and the next round's adjudicator clears it;
   before delivery, run that round (`prompt.py 3 --full` if nothing else changed).
4. **Set a round aside** that will never be adjudicated (its lanes crashed past `reissue`, it was
   cut from the wrong commit, a full round replaced it), or one re-vote lane that will never be
   settled: `python3 audits/stops.py set-aside <R> --reason "<why>" [--lane revote/<lane>--<item>]`.
   It commits every remaining file of the round (lane) by name with a script-computed inventory
   (its lanes, sealed or not, and their Fail and Ambiguous items); nothing is deleted. It refuses an
   adjudicated round (set aside its re-vote lanes instead), and refuses while a returned lane is
   unsealed: seal it first; `--lane` also refuses a sealed re-vote lane that can still be settled
   (one with no NOTE of its own: the adjudicator decides it); a lane that cannot be sealed (its digest is lost, its seal was refused)
   is named in `--unsealable <lane>[,<lane>…]`. A lane that differs from its seal whose sealed bytes are
   nowhere in git (release self-cure) has every item its round scoped for it carried forward as Ambiguous
   (the marker's `sealed_lost`), so the next adjudication decides each. An adjudicated round is never set
   aside: restore what changed after its seal (git checkout), or re-vote the lane. In `release`, a round
   with a STOP-class cause is set aside on its open self-cure stop (`--stop S<n>`). In dev, under a
   delegating level a round with a STOP-class cause is set aside only on the human's answer: record the cause (a refused seal: `open --note
   "<the refusal>" --cause seal-mismatch --round <R>`), ask, close it with `--human`, and pass
   `--stop S<n>`. A re-vote lane set aside never counts as the re-vote having run: its item's
   REVOTE NEEDED row stays undecided (no ADOPT, REJECT or DEFER after it), and the item is listed for
   the human as an open re-vote (DECISIONS.md, the report). Every carried item needs a row in the next adjudication: its commit,
   `lanecheck.py --round <R> --settled` and `make_report.py --check` refuse until it has one.
   Start the next round as usual (`prompt.py 3`); if its name is taken, make an empty Lean commit
   first (`git commit --allow-empty -m "fresh round after the set-aside of <R>"`, exactly that subject)
   and list it in the run log, its full hash and that subject on one line (`echo "- <full hash>
   fresh round after the set-aside of <R>" | python3 audits/project.py --log "Mechanical failures"`;
   this works while a stop is open, `stops.py open --note` does not): `tree_state.py
   --resave-operator` re-saves only such commits.
5. **An ownership FAIL caused by a commit that only ADDED files** (for example a careless sweep
   of a new file into the wrong commit) can be waived by the human, never by you (dev mode; in `release`
   it is `stops.py revert`, and only for a bookkeeping record whose revert failed the reviewed acknowledgment,
   `integrity.py --ack-request`). Record the stop
   with the integrity check while it shows the FAIL, `python3 audits/stops.py open --cmd "python3
   audits/integrity.py --check"` (the FAIL[ownership] line names the commit), show them the FAIL,
   close it with `--human`, then `python3 audits/integrity.py --acknowledge <commit> --stop S<n>`:
   one waiver per stop. It refuses a commit that changed or deleted a record (restore that
   instead), and one that added control data another check reads (seals, tokens, set-aside
   markers, `ADOPTED.md`, `TARGET.json`, the stop, waiver, approval and reader records, and lane
   evidence its seal did not record): only report records such as `PAPER_DEFECTS.md`,
   `SKIPPED.md`, `VACUOUS.md`, `STATEMENTS_BUNDLE.md` or an older run's `uni_math_extra.json` can be
   waived. The summary (`SUMMARY.md` and its PDF) and the report's trust section list every waiver.
6. **A stale git lock** (`index.lock` left by a killed git command): `python3 audits/stops.py
   repair-lock audits|project --reason "<why>"`. It refuses while a git process runs in that
   repository or the lock is under a minute old, and records the removal in the stop record
   (`stops/repairs/R<n>.json`, committed as `stop repair R<n>`; `RUN_RECORD.md` lists it with the stops).
7. **An interrupted command** (`stops.py open`, `close`, `set-aside`, `integrity.py --acknowledge`
   stopped between writing its record and committing it) is run again with the same arguments. It
   never commits a file as found: it recomputes the record now (a set-aside: every refusal and the
   whole inventory; a `--cmd` stop: the check re-run, its output and causes; a close: the re-run and
   the `--delegated` refusals) and commits the file only when it equals what it computed; otherwise
   it refuses and prints the exact recovery (remove the uncommitted file, run the command again).
   A `--note` stop's text and cause code are yours, as when it was first written.

8. **A `DISCLOSED[…]` line (release mode only)** is not a stop: `python3 audits/stops.py disclose
   --cmd "<the check that printed it>"` (RUN.md, "Run mode"). It re-runs the check, refuses while
   the check fails, and records the lines in `stops/disclosed/D<n>.json` ("stop disclose D<n>").

`integrity.py` checks this record (numbering, ownership, no delegated close of a STOP class, nothing
of a set-aside touched afterwards); `python3 audits/stops.py list` shows every stop and set-aside.
The watchdog (`codex/watchdog.py`, in the clone) only notifies. `--human` cannot tell the human's words from
yours (as with `signoff.py approve --by human`; KNOWN_LIMITATIONS.md): never record an answer the
human did not give.

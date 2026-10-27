# Stage 4 — audit rounds

Read this when Stage 3 ends (Phase 0 GREEN, nothing in scope `sorry`). It ends when a round's exit
check says "go to Stage 5"; then run `python3 audits/project.py --stage "Stage 5 — final round"`
and read `stage5-delivery.md`. Spawning, sealing, mechanical retries and a half-finished round:
`spawn-and-seal.md`.

Each round, in order:

1. **Phase 0.** Commit, then run `python3 audits/phase0.py`. It must be GREEN; it also saves the
   tree baseline. A `PENDING[adjudication]` line (a fault of an adjudicator-owned record) does not
   make it RED: this round's adjudicator clears it (its prompt lists it), and its commit and
   `project.py --deliver` refuse until it is cleared.
2. **Scope and lanes.** Run `python3 audits/prompt.py 3` and do exactly what its block says: scope,
   commit `scope <R>`, spawn the lanes it prints.
   - If `scope.py` exits 3 with `NEXT[stage5]` -- nothing changed, or only comments and docstrings
     changed since the last audited round (Stage 5's full round re-reads them on this same commit with
     every lane, so a diff round now only repeats part of it) -- go to Stage 5.
   - If `scope.py` exits 3 (nothing changed), go to Stage 5 -- unless it prints `NEXT[full-round]`: a
     Lean commit came after the last audited round that changed no declaration a lane reviews (a
     theorem turned into an `example`), which `--deliver` would refuse (`deliver-stale`), or an item
     awaits the next adjudication (`adj-record`: a result left unproved since the last round, a route
     change recorded since, an unsettled Fail). Then run `python3 audits/prompt.py 3 --full` instead:
     the full round audits that commit, and its adjudicator settles the item.
   - **The first round after Stage 3 is the full-scope round**: `scope.py` refuses a diff round
     while no earlier round examined proofs. Run `python3 audits/prompt.py 3 --full` instead (it
     examines more than a diff round, never less). If its exit check finds no ADOPT, no REVOTE
     NEEDED and no unexpected UNCOVERED row, it is Stage 5's full round: go to `stage5-delivery.md`
     step 2. The same holds when its only ADOPT rows are fixed in comments and docstrings (and every
     REVOTE NEEDED row is decided): implement them, commit, run Phase 0, go to Stage 5, and its
     `scope.py --full` prints `NEXT[no-round]` (this round is its full-scope round). Otherwise
     implement and go on with diff rounds as below; Stage 5 still opens with its own full round.
3. **Seal and check the lanes.** As each lane returns, seal it from that child's own result
   (`lane_auth.py seal --verdict … --sha256 … --agent-id …`, `spawn-and-seal.md`). When every lane
   has returned and is sealed, run `python3 audits/lanecheck.py --round <R> --kill` and handle its
   lines as RUN.md's failure table says: PROBLEM lines of a STOP class are stops; an unsealed lane
   is sealed (or reissued); NOTE lines (NOTE[independence], NOTE[independence-path],
   NOTE[lane-fault]) are the adjudicator's to settle, by a one-line clearance in ADOPTED.md or a
   re-vote, and its commit refuses until every NOTE is settled.
4. **Adjudicate.** `python3 audits/prompt.py 4 --round <R> --write`, then spawn one new
   general-purpose subagent with the printed sentence. Wait for it. It commits `adjudicate <R>`.
   A later `FAIL[dead-witness]` or `FAIL[record-cite]` in its records: a record correction
   (RUN.md failure table, record-fix), not a new round; any other fault of its records
   (`adj-record`) waits for the next round's adjudicator. That includes a hypothesis the
   assumption walk lists with no valid `## Hypotheses` row in an ADOPTED.md: every adjudicator,
   in a diff round too, writes the missing rows.
5. **Re-votes.** If `ADOPTED.md` has **REVOTE NEEDED** rows (adjudicators never spawn lanes; the
   re-votes are yours):
   - For each row with an item, spawn the lane printed by
     `python3 audits/prompt.py --lanes --round <R> --revote LANE:ITEM --write`; for each
     `(whole lane)` row, the lane printed by `python3 audits/prompt.py --lanes --round <R>
     --revote-lane <lane file without .json> --write` (one fresh lane re-judging every item of
     that lane). Spawn each with its whole printed line (token included), and seal it from its own
     result exactly as in step 3 (the seal commits it); then run `python3 audits/lanecheck.py
     --round <R> --kill`.
   - Then, once every re-vote lane is sealed or set aside, write the re-vote adjudicator's
     prompt, `python3 audits/prompt.py 4 --round <R> --revotes --write` (it carries the re-vote
     rules; append nothing), and spawn a fresh general-purpose subagent with the printed line. It
     commits `adjudicate <R> revotes`. A REVOTE NEEDED row settles its item (a carried Fail, a
     lane fault) only through a decision in that commit, made after the re-vote lane's seal; the
     settle check refuses anything else (a re-vote counts only if its sealed verdict judged the item;
     a re-vote lane set aside never ran, and an item with one set aside, or with more than one sealed
     re-vote, keeps its REVOTE NEEDED row undecided and stays open for the human), in the adjudication commit, `integrity.py --check`
     (`FAIL[unsettled]`) and `make_report.py --check` alike, so no hand-made commit gets past it.
   - Decision rows name exact names: the lane cell one lane of the round (`correspondence@2`,
     `revote/<lane>--<item>` included) and the item cell one item of its TARGET.json (or a carried
     item, `(whole lane)`, or an index label or declaration name of the project, for an UNCOVERED
     row), ignoring only surrounding spaces, emphasis and backticks; the scripts
     refuse any other row, and only a row of the same lane and item settles a REVOTE NEEDED row. A
     re-vote lane that exists unsealed blocks the item's decision until it is sealed or set aside.
   - A re-vote is never re-voted: a re-vote lane with its own NOTE leaves its row open for the
     human (the adjudicator writes `LEFT OPEN`, never `CLEARED`; the decisions document lists it). A re-vote lane
     that was sealed is committed; its row, if left unsettled, stays listed for the human. A
     re-vote lane that returned but cannot be sealed leaves its files uncommitted, and the next
     integrity check fails on them. Never delete or move them: `stops.py set-aside <R> --lane
     revote/<lane>--<item> --unsealable revote/<lane>--<item>` commits them as record, carries
     their Fails forward and leaves the row undecided (the decisions document lists it).
6. **Implement.** Run `python3 audits/prompt.py 5 --round <R>` and do exactly what it says. A
   declaration a new `VACUOUS.md` row names gets a docstring sentence saying it is true only
   vacuously (Phase 0 checks the word "vacuous").
7. **Exit check.** Read `ADOPTED.md`.
   - **Go to Stage 5** if it has no **ADOPT**, no **REVOTE NEEDED**, and no **UNCOVERED** row
     except those marked "(expected: …)".
   - **At the round cap** (the budget's, `stage0-intake.md`; under a delegating level `thorough` is
     capped at 6 diff rounds) start no further diff round: implement the round's ADOPT rows, log
     "round cap reached; no further diff round" -- as [DELEGATED] under a delegating level, as a
     [PROXY] decision under `involved` (it goes to the human at Checkpoint C) -- and go to Stage 5
     (its full-scope round runs whatever the budget; what it does not re-check is disclosed there).
     The cap is never a stop in `release` mode (U2 §8); in `dev` mode, under `involved`, stop and ask
     instead.
   - **Go to Stage 5 without a diff round** also when the round's fixes change no Lean but comments and
     docstrings (records aside), once every REVOTE NEEDED row is decided by its re-vote adjudication:
     implement them, commit, run Phase 0, then step 2 -- `scope.py` prints `NEXT[stage5]` (it compares
     the Lean with comments removed) and you go to Stage 5. Its full-scope round re-reads every
     docstring on the same commit, so a diff round first only repeats it (trial #7: a 20-minute diff
     round, trial #10 a 16-minute one, then the full round on the same commit). When this round was
     itself a full-scope round, Stage 5 runs no full round either (`NEXT[no-round]`, stage5 step 1;
     trial #11: 53 minutes for a full round on a docstring-only commit).
   - **Otherwise** go to the next round.
   - **QUESTION** rows wait for Checkpoint C.
   - **In Stage 5** at most two rounds follow the full round (step 1's cap): follow
     `stage5-delivery.md` step 1 instead of this exit check.


A round you give up before its adjudication is set aside (`stops-and-set-asides.md`) and a fresh
round started; a half-finished round is resumed as `spawn-and-seal.md` says.

Log each round in `RUN_LOG.md`: commit; lanes; P/F/A/N counts;
ADOPT/REJECT/DEFER/QUESTION/UNCOVERED; wall-clock time.

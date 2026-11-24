# Stops and set-asides

Read only the section a pointer names, never the whole file: `sed -n '/^#.*<section>/,/^#/p'
audits/run/stops-and-set-asides.md` (the failure table; "Tool patches"; "History faults no cure clears";
"Recording and closing a stop").

Read this when a check stops the round (the failure table, below) or a round must be set aside. What
happens to each cause is decided by its code (`project.CAUSES`, shown as `KIND[code]` on the failure
line), never by its wording. Every stop is recorded, whoever clears it (the run record
`RUN_RECORD.md`, "Every stop of the run"). A human stop's printed `close --human` may be refused by the
auto-mode classifier; then show the human the command (the stop is theirs already). Any other refused
command: RUN.md rule 12 (one plain retry; denied again, stop 3 with `stops.py open`). Never an unrecorded question.

## When something fails: the failure table

Each failure line carries a cause code, `KIND[code]` (`project.CAUSES` gives each code a class);
the class, never the wording, decides. A "stop" is recorded and handled as
below ("Recording and closing a stop"). Every cure is logged under "Mechanical failures".

The two right-hand columns are `dev` mode's. In `release` mode a stop closes only as the release
column below the table says: `close --cured` (re-running its read-only check) or, a human stop,
`close --human`; `close --delegated` is dev mode only.

| what failed | class (codes) | `involved` | `statements-only` (after B), `hands-off` |
|---|---|---|---|
| a `DISCLOSED[…]` line (`release` mode only) | presentation (`render`, `record-format`, `pdf`, `reader`, `label`, `selftest`, `tool-fault`); `docstring`, `run-log` | not a stop: fix your own text, or `stops.py disclose` (RUN.md, "Run mode") | same |
| a PDF: `signoff.py approve --by human` refuses, or `project.py --deliver` notes, that a PDF is missing, swapped, or was made from an older markdown (`render_record.py check`); a rendering agent crashed or never saved; an older run's `[pdf]` line | presentation (`pdf`, legacy) | never a stop, in either mode (`stops.py open` refuses `pdf`): render again (`render_record.py next --doc D`, `run/render-pdf.md`); a failed agent is recorded with `render_record.py fail` and the loop goes on; under approve, show the human the new PDF and ask again | same |
| a citation-review agent (Stage 5 step 5a: the advisory `CITATIONS.md`): crash, no file, the network unavailable | none: advisory, no check reads it | never a stop, never a retry beyond waiting out a usage limit or capacity error (`spawn-and-seal.md`): log `- citation notes not produced: <reason>` and go on; the run ships without it and the summary says so in one line | same |
| `RED[deliver-stale]` (`project.py --deliver`, the math gate): a Lean commit after the last audited round; a note `[deliver]` or `[unverified]` (`project.py --deliver`, after delivering): a facts draft stale or missing, a check of a delivered document, no full-scope round since the approval, or a result whose verdict is missing or out of date (`result_status.py`) | precondition (`deliver`, `unverified`, `deliver-stale`) | never a stop, in either mode (`stops.py open` refuses them): for `deliver-stale` a diff round (a full round when `scope.py` exits 3 with `NEXT[full-round]`: the commit changed no reviewed declaration; `run/stage5-delivery.md`), asked only until two rounds ran after the final full round (`project.DELIVERY_ROUND_CAP`, stage 5 step 1): past that the commit ships, disclosed as not re-audited, and no round is run for it; `deliver` and `unverified` never refuse: judge each note | same |
| a note `[status-unmapped]` (`project.py --deliver`): a result reads "not established" for a reason no route of `result_status.py` covers (no assumption walk, the walk did not reach it, an index cell naming no declaration with a fingerprint, a record it cannot read) | presentation (`status-unmapped`) | never a stop: re-run Phase 0 (not `--readonly`: it rewrites `DEPENDENCIES.json`, the walk) or correct an index cell that names no declaration, commit; what remains you judge from the records and the Lean, and SUMMARY and REPORT state the status you find | same |
| a `NOTE[…]` line | info, settle (`independence`, `independence-path`), lane-fault | nothing to do, never act on it; the adjudicator settles each lane NOTE by a clearance or a re-vote | same |
| a child: crash, service or capacity error, usage limit, no verdict file, no `LANE_COMPLETION`; a failed tool call or download | mechanical (`lane-output`, `tool-call`) | retry within the time budget (`spawn-and-seal.md`; a capacity error or usage limit waited out there is logged under "Mechanical failures", no stop); then an environment fault (a stop) | same |
| your own work: Phase 0 (author mode) `RED[build]`, `RED[branch]`, `RED[baseline]`, `RED[sorry]`, `RED[unproved-meta]`, `RED[hard-token-own]`, `RED[axiom-own]` (a `native_decide` or other kernel-skipping token, an extra axiom: rewrite that proof without it); `RED[index]`, `RED[unlisted]`, `RED[docstring]`, `RED[run-log]`, `RED[unused-args]`, `RED[dependencies]` | mechanical, proof-wip, document | fix it in a new commit and re-run Phase 0; a `sorry` you cannot prove follows Stage 3 (a goal result: a stop; otherwise ask: removing, narrowing or hypothesising away a result is the human's decision) | fix it in a new commit and re-run Phase 0; a `sorry` you cannot prove: a goal result is a stop; missing theory becomes a named hypothesis (RUN.md, "Missing theory"; an approved statement also follows RUN.md, "Statement changes after approval"); any other result that stays unproved after a serious attempt is left unproved, never deleted or weakened: keep its statement byte-identical, log `[DELEGATED <date>, operator under <level> (intake); reversal: re-prove] leave <decl> unproved — <reason>` as a line of its own under `## Open questions` (`project.py --log "Open questions"`; full Lean name; every result whose proof uses it needs its own line: the axiom sweep is RED until it has one), propose it in `AUTHOR_NOTES.md` under results not to formalize, make its index cell "`<decl>` (stated, not proved: not formalized)", commit, re-run Phase 0 (its `sorry` is then `NOTE[unproved]`); the next round's adjudicator records it in `SKIPPED.md`, and the report and `DECISIONS.md` disclose it as "stated, not proved" |
| a `project.py --deliver` note `[adj-record]`: a result left unproved that no round has adjudicated since (its line logged after the final diff round) | document | (cannot occur: no line exempts under `involved`) | run one more round, so its adjudicator checks it and records it in `SKIPPED.md` (a diff round; `scope.py` exits 3 with `NEXT[full-round]` when it has nothing to scope: a full round); then Phase 0, prepare, and deliver |
| Phase 0 `RED[dependencies]` from the walk: `DEPENDENCIES.json` missing, without the assumption walk, stale (the Lean changed), or a goal result with no walk entry; or the walk did not run because the project does not build | document | re-run Phase 0 (not `--readonly`): it rewrites the file; a goal result with no entry: fix its index cell. `RED[tool-bug]` from the walk (an error inside the walk's own code): a pinned script's bug, the `tool-bug` key | same |
| `FAIL[missing-theory]` (`make_report.py --check`, also inside Phase 0): your missing-theory line in `RUN_LOG.md` tries the canonical form (`missing theory: …`, naming its result) and misses it (RUN.md, "Missing theory"), lacks the paper's quote or a configured library's search, comes from the wrong level (a [DELEGATED] line under `involved`, a human one under `hands-off`), is a human line without the human's committed answer naming the result, takes option (3) as [DELEGATED], names a hypothesis that is not in its result's assumption list or that the walk flags as restating a result (or as a result's conclusion), or says `build` while the replaced hypothesis is still a binder, or is a line an adjudicator ruled a missing-theory decision (`MT RULED`) with no canonical line after it (log it, or, if you judge the ruling wrong, `- MT DISSENT <id>: <why>` once: the line goes back to the next adjudicator; a line only suspected from its words: the `PENDING[adjudication]` row below). (`FAIL[unproved-goal]` from the same check: `H` is a goal result's conclusion: stop 1, below. `H` restates a goal result: this row's curable `FAIL[missing-theory]`, never stop 1: use that result instead of assuming it.) | document | the human's choice is recorded in the wrong form: log their answer and log the corrected line after the old one (a logged line is never reworded), commit, re-run the check; ask if the Lean must change | log the corrected line after the old one (a logged line is never reworded), take `H` as a binder of the result's statement, or prove a restated result instead of assuming it (RUN.md, "Missing theory"; an approved statement follows RUN.md, "Statement changes after approval"), commit, re-run Phase 0 (`release`: a self-cure, closed by `make_report.py --check`) |
| lanecheck `PROBLEM[unsealed]`, `[stray-loop]`, `[stray-file]`, `[no-baseline]` | mechanical | seal (or reissue) the lane; `--kill`; restore the tree and tell the adjudicator; run Phase 0 | same |
| a record of the adjudicator's (PAPER_DEFECTS, SKIPPED, VACUOUS.md) cites what does not exist: `FAIL[dead-witness]` (a witness cell naming `sorry` or a probe's lemma), `FAIL[record-cite]` | record-fix | `stops.py open`; record correction: `prompt.py 4 --round <R> --record-fix --write` (R the last adjudicated round), spawn a fresh adjudicator with the printed line; it edits only the faulty cells and commits `record-fix <R>` (`integrity.py --commit-record-fix`, which refuses anything more); re-run the check, `close --delegated` (`release`: `close --cured`). It needs no GREEN Phase 0, no Lean commit and no new round (Phase 0 is RED on the very fault). It returns NEEDS A ROUND, or the fault is in a verdict, decision or status cell: a new round (Phase 0 shows the fault as `PENDING[adjudication]`, so the round runs; its adjudicator clears it). Disclosed in the report's stop list | same (never the human; `release`: `close --cured`, never `--delegated`) |
| a `PENDING[adjudication]` line (Phase 0), or `FAIL[adj-record]` / `RED[adj-record]` (`make_report.py --check`; a note of `project.py --deliver`): any other fault of an adjudicator's record (a cell count: a literal `\|` in a cell; a missing-theory "decided by" cell not bound to a RUN_LOG.md decision naming the result -- with none recorded, the adjudicator writes a QUESTION row and "QUESTION (<round>)", and the question reaches the human at Checkpoint C (under a delegating level, you decide it with a [DELEGATED] line); a defect only in prose; "formalized AND skipped" -- once an adjudication ADOPTs fixing the index for it, it is your `report` fault: make the index cell "not formalized"; a result left unproved without its SKIPPED.md row; a carried item without its ADOPTED.md row; a RUN_LOG.md line the missing-theory check suspects (`MT RULED`)) | adjudication (`adj-record`) | not RED in Phase 0: run the round (a decided row -- ADOPT, DEFER, an answered QUESTION -- is never listed: no round can clear it); its adjudicator's prompt lists the faults and `--commit-adjudication` refuses until it clears them. Before delivery: one more round (`prompt.py 3 --full` if no Lean changed); a stop on it is closed `--delegated` (`release`: `--cured`) | same (never the human; `release`: `close --cured`) |
| tree_state `FAIL[head-moved-operator]`: HEAD moved since the baseline only by your own prescribed empty commits (each empty, the baseline's author, subject `fresh round after the set-aside of <R>`, or `fresh full round on <R>` from the route `scope.py` prints when a full round already on HEAD was adjudicated and is not settled, listed in RUN_LOG.md or a stop record: its full hash, or 12+ characters, on one line with that subject) | mechanical | list it when you make it: `echo "- <full hash> fresh round after the set-aside of <R>" \| python3 audits/project.py --log "Mechanical failures"` (works while another stop is open; `stops.py open` does not); `python3 audits/tree_state.py --resave-operator --reason "<which commit, why>"` (logged, recorded in the baseline; no GREEN Phase 0 needed); a stop opened on it: `close --delegated` (`release`: `close --cured`). `release` also: HEAD moved only by your own commits up to exactly the commit a round was cut from (its directory committed; Phase 0 did not save the baseline after them) is the same row, the same cure (`--resave-operator` logs it). Any other commit (another subject, unlisted, a change and its revert, a commit past the round's) is `FAIL[head-moved]` (next row) | same |
| tree_state `FAIL[head-moved]`: a commit since the baseline changed files, is a merge, or has another author | tamper | a stop for the human at every level (a lane may have committed); `release`: a self-cure (restore): `tree_state.py --revert-foreign` reverts the whole foreign range, accepted only when HEAD's tree equals the baseline's, then `close --cured` | same |
| a document check (`report`) RED from text you wrote in `AUTHOR_NOTES.md`, `READER_NOTES.md` | document | a stop: ask | the narrow exception (RUN.md, after "Stops that remain at every level"), then `stops.py close --delegated` |
| any other failure line of a check (integrity, tree_state, lanecheck, lane_auth, stops), class mechanical or document: e.g. `uncommitted-record`, `tree-changed`, `git-error`, `unsettled` | mechanical, document | a stop: `stops.py open`, ask, `close --human` | `stops.py open`, cure as the code says, `close --delegated` |
| a failure with no cause code: a script crashing (`FAIL[uncoded] <script> crashed (...)`, printed by `project.run_main` after the traceback, which goes to stderr), an error message no code covers, git or Lean/lake failing unwrapped | mechanical (`unknown-retry`, `uncoded`, `env-unknown`), tool-bug (`tool-bug`) | `stops.py open --note "<what failed>" --cause unknown-retry`, re-run the command within the retry budget (`spawn-and-seal.md`), ask, `close --human` | same open and re-run; it passes: `close --delegated`; it persists: close it naming the next stop and classify it ("Recording and closing a stop", item 1, below): a traceback whose innermost project frame is in `audits/` is `--cause tool-bug`, a stop (you never edit a pinned script); otherwise `--cause env-unknown`, fixed as an environment fault (the last bullet of RUN.md, "Stops that remain at every level"), then `close --delegated`, a stop only after the retry budget. `release` mode, both columns: `open --note "<what failed>" --cause unknown-retry --check "<the read-only check of the failed step>"` (a FORMS check, failing now), cure, `close --cured`; after the retry budget `--cause env-unknown` (stop 3, a human stop) or, a pinned script, `--cause tool-bug` (the tool-patch route, never a human stop); never `--delegated` |
| a STOP class | tamper, apparatus, freeze (`drift`), gitmeta, proof (`axiom`, `hard-token`: read-only Phase 0 or another check; `unproved-goal`), tool-bug (`tool-bug`), unknown (a failure line with no code) | a stop: `stops.py open`, ask, `close --human`. `release` mode: a self-cure, except `unproved-goal` (RUN.md, "Stops that remain at every level": `open`, apply the printed cure, `close --cured`; past the budget, `stops.py classify`: stop 3 only for outside interference, a tool bug the tool-patch route) | same |
| the four release stops: (1) a goal result looks false, true only vacuously, unprovable for a reason other than missing library theory, or stays unproved; (2) an outward action the intake did not allow; (3) something only the human can fix (an environment fault, a Codex approval prompt under a delegating level, another program that keeps changing the project's files); (4) a genuine ambiguity of the paper's meaning the reviewers cannot settle | `unproved-goal` (Phase 0 prints it for one left unproved, the report check for a goal assumed as "missing theory"; one that looks false: `open --note ... --cause unproved-goal`), `outward-action`, `env-unknown` (after the retry budget), `codex-approval`, `interference` (after `stops.py classify --as interference`), `ambiguity`: human (H) | a stop: `stops.py open --note "<what>" --cause <that code>`, ask, `close --human` | same, in `release` mode too (never a self-cure; `release` refuses a `--note` cause that is not a cause code) |
| an approved statement must change | (decision) | a QUESTION (`reapproval.md`; the pending state holds, only `--deliver` waits) | `statements-only`: missing theory turned into a named hypothesis, a QUESTION as under `involved`; any other change (a faithfulness finding after the sign-off, a refuted non-goal statement): the approved statement is kept, a [DELEGATED keep] line and a `CONDITIONS.md` `finding` item (an open K item, offered in the K stage). `hands-off`: delegated (`reapproval.md`; RUN.md, "Statement changes after approval"), except a faithfulness finding after the sign-off or a refuted non-goal statement: the approved statement is kept, a [DELEGATED keep] line and a `CONDITIONS.md` `finding` item |
| missing theory; a QUESTION row; the round cap | (decision) | ask at the checkpoint; the round cap: the conservative default as a [PROXY] decision (`release`; `dev`: ask) | decide as in RUN.md, "How you decide" and "Missing theory" |
| the statement-round cap (`scope.py --statements`: 4 before the first approval, 2 per re-approval) | `NOTE[round-cap]`; with a faithfulness finding open: `dev`, `PROBLEM[round-cap]` (`round-cap`, a stop); `release`, `NOTE[round-cap]` naming the three routes, the open findings recorded in `round-caps/<round>.json` (`round-cap`, disclosed) | no finding open: no stop, the last round's sheet, its statement-changing ADOPT rows recorded as decisions ([PROXY]). A finding open: `dev`, a stop, `stops.py open --note "<what>" --cause round-cap`, ask, `close --human`; `release`, judge its cause: (a) a genuine ambiguity, stop 4 (`--cause ambiguity`, ask, `close --human`); (b) a loose convention, a reading-choice decision ([PROXY]), go on; (c) anything else: a Checkpoint B question (the human decides at B), each result it concerns reads "not established: open faithfulness finding" on the summary's first page | same ([DELEGATED] decisions; (a) is asked under `hands-off` too, and the run resumes hands-off; (c) under `statements-only` is asked at B, under `hands-off` "keep the last round's statement, disclosed" plus a `CONDITIONS.md` `finding` item) |

**Release column** (generated from `project.RELEASE`, `project.CURES` and `project.CLOSER`; `tests/doclint.py` checks it is current). Each cause code has a kind; `open` prints the kind's cure followed by the code's own text:

<!-- release-column:begin -->
| kind | codes | cure (`project.CURES`) | closes with |
|---|---|---|---|
| rerun | `adj-record`, `baseline`, `branch`, `commit-refused`, `dead-witness`, `dependencies`, `git-error`, `head-moved-operator`, `index`, `lane-output`, `missing-theory`, `no-baseline`, `no-round`, `record-cite`, `report`, `signoff-check`, `stray-file`, `stray-loop`, `tool-call`, `uncoded`, `unknown-retry`, `unsealed`, `unused-args` | fix the mechanical problem the code names, then re-run the check (close --cured re-runs it); a crash that persists: re-run the review by another route (a fresh round), never skip it | `close --cured`, re-running the `--check` recorded at open, `lanecheck.py --round <R>`, `make_report.py --check`, `phase0.py --readonly`, `signoff.py check --round <R>`, `tree_state.py --check` |
| restore | `agent`, `codex-roles`, `config`, `gitmeta`, `head-moved`, `no-pin`, `ownership`, `pin`, `pyc`, `reapproval-record`, `record-changed`, `record-fix-diff`, `set-aside-changed`, `stop-trail`, `tool-patch`, `tooling`, `tree-changed`, `uncommitted-record`, `waiver` | go back to the last trusted version -- the pinned apparatus (git -C audits checkout <pin commit> -- <the files the FAIL names>), a committed record change (python3 audits/stops.py revert --stop S<n> --commit <the commit the FAIL names>: it restores the records that commit changed, committed as "revert <commit> (stop S<n>)", which integrity.py accepts once verified), an uncommitted one (git checkout <file>) -- then re-run the check; a FAIL in the committed history that no restore or revert clears (a past re-pin, a mistyped pin subject, a record its owner re-committed after a hand edit, an unverifiable tool-patch link, a damaged stop trail): the reviewed acknowledgment (python3 audits/integrity.py --ack-request --diagnosis "<what happened, why nothing it judges changed>"; a fresh reviewer judges it; then close --cured "acknowledgment AK<k>") | `close --cured`, re-running `integrity.py --check`, `tree_state.py --check` |
| redo | `auth-metadata`, `evidence-after-seal`, `independence`, `independence-path`, `lane-fault`, `owner-redo`, `prompt-changed`, `quote-unmatched`, `scope-changed`, `seal-mismatch`, `unauthenticated`, `unsettled` | restore the changed record if needed (git checkout <file>), set the affected round aside (stops.py set-aside <R> --reason "release self-cure of S<n>" --stop S<n>) and re-run its review in a fresh round (prompt.py 3; fresh lanes and adjudicator): its independence was compromised. An ADJUDICATED round is never set aside: restore what changed after its seal or commit (git checkout <the sealed or committed version> -- <file>) and re-run the check; a lane that cannot be restored is re-voted (the adjudicator's REVOTE NEEDED row, a fresh re-vote lane, "adjudicate R revotes"); an unsettled NOTE or carried item is settled by the round's adjudicator (its ADOPTED.md rows, integrity.py --commit-adjudication) | `close --cured`, re-running `integrity.py --check`, `lanecheck.py --round <R>`, `lanecheck.py --round <R> --settled`, `scope.py --verify --round <R>` |
| reprove | `axiom`, `axiom-own`, `build`, `drift`, `hard-token`, `hard-token-own`, `sorry`, `unlisted`, `unproved-meta` | change the Lean (rewrite the proof without the token or axiom, or restore the approved statement), commit, then run Phase 0 and the build | `close --cured`, re-running `fingerprint.py --check`, `phase0.py --readonly` |
| patch | `tool-bug` | if a read-only check fails because of a mechanical problem, fix it and re-run the check (close --cured re-runs it); if the pinned tool itself is wrong (it crashes, or misjudges this case): diagnose it and patch it through python3 audits/tool_patch.py begin --stop S<n> (run/stops-and-set-asides.md, "Tool patches": a fresh reviewer approves the patch; then close --cured "tool-patch TP<k>"); a fault in the proof-validity core (no patch may touch it): a Lean-side workaround, else stops.py core-fault (a fresh reviewer judges it), then close --core-fault <file> (what the check guarantees reads "not verified", never waited on); never edit a pinned script by hand | `close --cured`, re-running the `--check` recorded at open (a stop with none: `close --cured "tool-patch TP<k>"`, re-running the patch's regression test) |
| human | `ambiguity`, `codex-approval`, `env-unknown`, `interference`, `outward-action`, `unproved-goal` | a human stop: show the human the raw output and wait; close it with --human "<their answer, verbatim>" | `close --human` |
| disclose | `acknowledged`, `acknowledged-fault`, `before-pin`, `config-grew`, `docstring`, `escalation-cite`, `label`, `lean-slot`, `not-approved`, `notice-subject`, `pdf`, `pyc-cache`, `reader`, `reapproval`, `record-format`, `reissued`, `render`, `repinned`, `reverted`, `round-cap`, `run-log`, `selftest`, `status-unmapped`, `superseded`, `tool-fault`, `uncommitted-file`, `unpinned-py`, `unproved` | not a stop in release mode: it is disclosed (stops.py disclose) | no stop: `stops.py disclose` |
| precondition | `decisions`, `deliver`, `deliver-stale`, `reader-check`, `unverified` | not a stop, in either mode: deliver-stale refuses project.py --deliver (a diff round); the others are notes it prints for you to judge, or document checks you fix (approver 2026-10-28) | no stop: `project.py --deliver` refuses on `deliver-stale` only; the others are notes |
<!-- release-column:end -->

### Tool patches (`release` mode only)

When a pinned check is itself wrong -- it crashes, or it misjudges this case (bench1: `result_status.py`
routed a correctly recorded inline hypothesis to the adjudicator; bench2: a diff round's scope check
read the round's own sealed verdict) -- you act as the maintainer. Decide first: **is the check
right?** If it is, apply the printed cure; real tamper, ownership, freeze, gitmeta and proof faults are
never patched. If it misjudged, go straight to a tool patch (never burn a cure that cannot work). A
human stop (the codes of kind `human`) is never a tool patch's subject. `dev` mode refuses all of this:
a tool fault stops the run and a maintainer fixes the tool.

1. `python3 audits/tool_patch.py begin --stop S<n>` (the stop stays open throughout, so nothing runs on
   the buggy tool). Diagnose it from the code and write `<rounds dir>/tool-patches/TP<k>/A1/DIAGNOSIS.md`
   (sections: the check; the failing case; the cause, `file:line`; the correct behaviour; why no
   faithfulness result depends on the change; whether the old behaviour is right elsewhere; then the
   lines `affects-review-inputs: yes|no` and `regression: tests/regressions/<name>.py`) and
   `A1/patch.diff`: `git -C audits diff --relative` of a minimal fix made in a scratch worktree, never in
   `audits/`. It may touch any file of the apparatus -- scripts, tests, Lean tails, and the protocol
   text (`AUDIT_PROTOCOL.md`, `RUN.md`, `run/`, `agents/`, `skills/`): a wrong instruction is patched
   like a wrong script. It never touches the proof-validity core (below), the
   reviewer prompts that judge patches, core faults and acknowledgments or the code rendering them
   (`tool_patch.GUARDED`; this includes the common rules for subagents, which the reviewer receives),
   the git rules, anything outside `audits/` (the project's Lean), a round record, or what the author
   signed (`SIGNOFF*`, `APPROVED_FINGERPRINTS*`, `REAPPROVAL*` as `.json`/`.md`/`.pdf`/`.tex`; `signoff.py` and
   `run/reapproval.md` are tooling). It adds the NEW regression test,
   which takes `--apparatus DIR` and fails with the pinned apparatus, passes with the patched one (for
   a text patch: it reads the patched text). It may add other new files, under no Python module's
   name; it deletes and renames none. Prompts issued before the patch stay verified against what was
   issued (their committed hashes; a tool-patch review against the apparatus pinned at its issue);
   prompts after it are rendered from the patched text. A patch to `agents/auditor.md` or the common
   rules reinstalls the reviewer agent and the Codex roles at apply.
2. `python3 audits/tool_patch.py prepare --tp TP<k>` records the mechanical facts (`FACTS.json`): the
   regression test, every pure selftest of the first pin (and any the patch adds) on the patched tools,
   the blast radius (every read-only check of every round, pinned vs patched; a PASS->FAIL forces
   `affects-review-inputs: yes`), and the floor (the canaries of the first pin's `FLOOR`, each killed
   only by a selftest that passes on the patched tools unmutated: a hit needs two approvals). It refuses before review a
   failing fact (a) or (b), a file it may not touch (above), a new file with a module's name, a change to a
   guarded block, and a diff already rejected. It flags (never refuses) a patch touching code the core
   relies on (`core_reachable`), for the reviewer.
3. `python3 audits/tool_patch.py review --tp TP<k>` prints the spawn line of a FRESH reviewer (a
   general-purpose agent; Codex: `agent_type` `formalize_tool_patch_reviewer`, `fork_turns` "none"):
   never yourself, a lane or an adjudicator of the run. Seal its verdict exactly like a lane's
   (`lane_auth.py seal --verdict ... --sha256 ... --agent-id ...`). It approves or rejects.
4. **Rejected:** revise with its findings, write `A<n+1>/` (its `DIAGNOSIS.md` adds a section `## Earlier
   findings answered` naming each rejecting review of the run, on any stop, `TP<k> review-<n>-<m>.json`, with
   your answer; a review issued and never sealed counts as a rejection, and a diff once rejected anywhere in the
   run is never resubmitted, even with only whitespace or line numbers changed),
   prepare and review again (a new fresh reviewer sees every earlier attempt and finding). There is no cap
   and no stop. **The check was right
   after all, or a reviewer never returned:** `python3 audits/tool_patch.py withdraw --tp TP<k> --reason
   "<why>"`, then the printed cure (or a new tool patch). **Approved:** `python3 audits/tool_patch.py
   apply --tp TP<k>` commits the diff (`tool-patch TP<k> apply`) and re-pins (`pin (tool-patch TP<k>)`);
   then `python3 audits/stops.py close --stop S<n> --cured "tool-patch TP<k>"`, which re-runs the
   stop's check on the patched tools (a stop with no check: the regression test). If that still fails,
   the diagnosis was wrong: re-diagnose (a new tool patch, or the printed cure); never a stop.

`integrity.py --check` verifies every tool-patch link with the scripts pinned just before it, and again with
the first pin's scripts. A patch may never touch the proof-validity core -- `phase0.py` (the build and the
sorry scan), the axiom sweep (`axiom_sweep.*`, `axiom_sweep_tail.lean`), the freeze (`fingerprint.py`,
`fingerprint_tail.lean`, `olean_parts.lean`), `tool_patch.py` and `integrity.py`: refused at prepare and
apply whatever the reviewers say. A fault there is never patched, and in `release` never waited on: in `dev` it is
a maintainer's; in `release` withdraw the patch, then first try a Lean-side workaround (a pure refactor of the Lean
that the freeze check confirms, closed `--cured`); if none exists, the stop is closed as not established, in
two steps. (1) `python3 audits/stops.py core-fault --stop S<n> --core-fault <core file> --diagnosis "<the fault,
file:line; why no Lean-side workaround works>"`: the stop must be a tool bug whose check is the one that runs that
file (`phase0.py --readonly` for phase0.py and the sweep, `fingerprint.py --check` for the freeze, `integrity.py
--check` for integrity.py and tool_patch.py) and fails now, and every failure of the blocking checks must be that
file's own (a sorry beside a crashed sweep, a drift, an ownership FAIL keep their own cures); it records the
failure lines and prints the spawn line of a FRESH reviewer (as a tool patch's: never yourself, a lane or the
adjudicator), whose verdict you seal like a lane's. (2) After an approval, `python3 audits/stops.py close --stop
S<n> --core-fault <core file>`: it needs the sealed approval and the same failure lines. A rejection: revise and
request again, or take the ordinary cure; no cap, never a stop. A rejection means the reviewer saw a real problem
(a real sorry, axiom, changed statement or tampering) or a workaround: repeated rejections mean fix that problem,
whose own cure applies; `RUN_RECORD.md` lists every request with its verdict. A run whose reviewers never approve
does not deliver by this route (KNOWN_LIMITATIONS.md). After the close the run delivers with the consequence in
plain words on SUMMARY page 1 and in the REPORT ("Not verified: the check that every proof is complete could not
be run ...", per guarantee), each affected result marked "not verified: ...", and the check, the file, the
diagnosis, the failure lines and the verdict in `RUN_RECORD.md` only; it never claims that check passed, and
`--deliver` accepts no failure line but those the reviewer judged. Any other
tooling change is `FAIL[tooling]`, and a plain `pin (repin: ...)` in `release` may not change the tooling
(`FAIL[pin]`; the gitmeta re-pin changes none). If a patch may have changed what an earlier review was
shown (`affects-review-inputs: yes`), `scope.py` runs a full round scoped after it, and `--deliver` names it in
a note until one has been adjudicated. Tool patches are recorded only in `RUN_RECORD.md` (diagnosis, diffs, every reviewer
verdict, seals, commits, and the command a maintainer runs to re-check every link with the first
pin's scripts); the report names them only by its one "Checks weakened" line (details in
`RUN_RECORD.md`), and the summary, the sheet and `DECISIONS.md` not at all -- except that a result whose
status a patch made stronger than the run's first-pin tools make it is marked on SUMMARY page 1 and in REPORT
in plain words, for a reader who knows nothing of the mechanism ("<result>: this status was decided by a corrected
version of our checking software; the original version would have said <old>. ..."; which patch and the first
pin's status are in `RUN_RECORD.md`): `--deliver` recomputes it with the
first pin's `tool_patch.py` and `result_status.py` and names in a note a document without the line (or a REPORT
without the "Checks weakened" row): you write the line in plain words and the claims reviewer checks it.

An apply killed between its two commits leaves `FAIL[tool-patch] ... has no pin`: run `tool_patch.py apply --tp
TP<k>` again; it resumes (the approval and the byte-identical diff checked again, then the pin).

### History faults no cure clears (`release` mode only)

Some integrity FAILs live in the committed history, and no restore or revert can clear them: a past plain
re-pin that changed the tooling (once the tooling in force is a trusted pin's again), a pin committed under a
mistyped subject, an unverified `Revert ...`, a tool-patch link no verifier can run (never one that touched the
proof-validity core), a damaged stop trail, a bookkeeping record (a stop, reader, PDF or tool-patch record) committed
by the wrong step whose revert was tried and failed. They are never a human stop. A record that carries a judgement
(a lane's verdict or probe, `ADOPTED.md`, `PAPER_DEFECTS.md`, `SKIPPED.md`, `VACUOUS.md`, `DEVIATIONS.md`,
`INFORMAL.json`, `INFORMAL-2.json`, `SIGNOFF.json`, `TARGET.json`, `STATEMENTS_BUNDLE.md`, an approval, an answer) is never acknowledged:
it keeps its real cure, `stops.py revert --stop S<n> --commit <C>` (also for an owner's own commit that a
check refuses: a record fix beyond its faulty cells, a touch of a set-aside round). It undoes C's change onto the
current content when that applies cleanly (later work stays); otherwise, when every later change was the owner's, it
puts back the content before C, and `integrity.py --check` then prints `FAIL[owner-redo]` for that record until a
fresh FULL round scoped after the revert is adjudicated and its `ADOPTED.md` rules every line the restore removed
(its adjudicator's prompt lists them): `REDO RULED <record> | <the line> | keep: <why>` or `drop: <why>`, each kept
line written back in the record. Code checks only that every line has a ruling and every kept one stands. Nothing is dropped silently, and none of it is a human stop. Open the stop on `integrity.py --check` as usual, then:
(1) `python3 audits/integrity.py --ack-request --diagnosis "<what each commit did, why no cure clears it, why no
statement, proof, verdict, adjudication, approval or check changed>"` records every current FAIL line it may cover,
each naming its commit, with the full diff of each named commit and the files of each named tool patch
(`acknowledgments/AK<k>/`), and prints a FRESH reviewer's spawn line (as a tool patch's: never yourself, a lane or the
adjudicator; Codex `agent_type` `formalize_tool_patch_reviewer`); seal its verdict like a lane's. Any `[pin]` line is
accepted, and stays acknowledged, only while the tooling in force is a trusted pin's (the first pin's, or a verified
tool patch's): restore it and re-pin first (`integrity.py --pin --repin` in release refuses a re-pin over changed
tooling). (2) Approved: `integrity.py --check` prints exactly those lines as `NOTE[acknowledged-fault]` (any other or
later line stays FAIL and needs its own request); close the stop `--cured "acknowledgment AK<k>"`. Rejected: revise
and request again (the next reviewer sees the rejection), or take another cure; no cap, never a stop.
`RUN_RECORD.md` lists each acknowledgment, and only it: none changes what the summary and the report say about the
results. `integrity.py --acknowledge` (the human's waiver) is dev mode only.

`head-moved` and `gitmeta` are restores
(B1c): `tree_state.py --revert-foreign` reverts the whole foreign range and the check accepts it only
when HEAD's tree equals the baseline's (never by a commit subject); `tree_state.py --restore-gitmeta`
restores only the hooks and config keys of the Stage 1 snapshot in the pin, and writes only in
`<gitdir>/hooks`; `--revert-foreign` is refused while `gitmeta` fails and runs no hook. In release,
`env-unknown` (stop 3) is: a `user.*` or `credential.*` setting changed in the repository's own
(local or worktree) config -- the human's `~/.gitconfig` is not checked for these; in any scope
(local, worktree, global, system), a changed resolved hooks directory or `core.hooksPath`, or a
destination setting (a remote's url or pushurl, `url.*.insteadOf`/`pushInsteadOf`,
`http.*.extraHeader`, `branch.*.remote`/`pushRemote`, `remote.pushDefault`, `core.sshCommand`); a
`refs/replace/*` ref or `info/grafts` not in the snapshot; pinned history no longer an ancestor of
HEAD; a pin with no snapshot when the cure needs one (a re-pin adds it). In dev none of this is
checked against the snapshot: every git meta change is `FAIL[gitmeta]`, the human's.

## Recording and closing a stop

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
   fresh reviewer's approval, "Tool patches" above); anything
   else (git, Lean/lake, network, filesystem) is `--cause env-unknown`, which you fix as an
   environment fault (RUN.md, "Stops that remain at every level") and close with `--delegated`,
   asking the human only after the retry budget. The scripts themselves still class a code nobody
   recorded as unknown, a stop: this retry and classification is your step. Fixes to try first for an environment fault: retry failed downloads (`lake exe cache get` again; it can partly fail), re-run the build, check that the Mathlib and toolchain pins match, clear and rebuild the project's own build outputs (never the user's files), wait out a usage limit and resume, and free space only in the run's own scratch and build directories.
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
   **Release mode** (RUN.md, "Stops that remain at every level", and the failure table's release
   column above): a stop with no cause of kind human is a **self-cure** at every level instead.
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
   changing the project's files) is stop 3, the human's, anything else one more cure. A stop you
   opened in error (the fault's route is not a stop, or the wrong check or round): `close --withdrawn
   "<why, and the route instead>"` (a stop whose fault you cured is closed `--cured`, also when the check still prints
   only `adj-record` faults the cure created: those count as passing; a withdrawal of such a stop goes through with a
   NOTE that `--cured` was the right close); release only, never for a human stop, refused while its check
   passes, while it still shows a redo or tamper fault on the current round, even one that appeared
   after it was opened (set the round aside and redo it, or restore, as its cure says), or, the budget spent, until you classify it `other`; it counts as a failed
   cure, and RUN_RECORD lists it. A made-up
   or mistyped `--round` is refused at `open` (nothing recorded): give the round of this run. A history
   fault no cure clears ("History faults no cure clears" above) is acknowledged after a fresh review
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
   `redo_of`, its sealed verdicts judging every item of the set-aside scope, an item a lane left
   NotDoneYet counting once that round's adjudicator recorded it UNCOVERED for that lane (AUDIT_PROTOCOL
   step E; read from ADOPTED.md as first committed by `adjudicate <fresh round>`) -- scope it with the
   set-aside round's kind (`--statements` for a statement round, `--full` for a full round; a diff
   round cannot redo either); recorded as `redo_round`; refused, no attempt spent, until there is
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
   **The release cure in full** (moved from RUN.md). `close --cured` re-runs exactly the read-only check the stop recorded at open, which must pass; a failing attempt
   is recorded (`S<n>/CURE<k>.json`). That check is always one of the protocol's read-only check
   commands, never a writer and never the failed tool command itself: a `--cmd` stop's check, or for a
   `--note` stop the read-only check of the step that failed, given at open (`open --note ... --cause
   <code> --check "<it>"`: `integrity.py --check` for setup, `lanecheck.py --round <R>` for a round,
   `phase0.py --readonly` for the build); it must fail then. A code with a closer of its own (the
   release column's "closes with") records exactly that closer, on the stop's `--round` for a
   round-bound one (leave `--check` out and `open` records it), never another check that happens to
   fail now; `--deliver` re-runs those closers too. A failure no code covers is `--cause
   unknown-retry` with such a `--check`. `close --delegated` is dev mode only; a code that is
   disclosed in release never opens a stop. The failure tally, counted from git history over the whole run and never
   reset, under any stop id: a fault is keyed by (check script, cause code) -- a `--cmd` stop by its
   command's codes, a `--note` stop by the codes its `--check` printed at open (an uncoded failure:
   `unknown`), whatever code you gave it. A `--note` stop also has the key (its code, the round: the
   newest round with a verdict file or adjudicated when it opened, its check script), `unknown-retry`, `tool-call`,
   `git-error`, `tool-bug`, `commit-refused` and uncoded sharing one; it counts openings only. The
   cure budget is spent by a stop with `project.CURE_BUDGET` (2) failed `--cured` re-runs of its own,
   whatever codes they showed; a (script, code) with `project.KEY_BUDGET` (3) failed re-runs anywhere in
   the run (a flaky check failing one cure in each of two far-apart rounds does not spend it); or a key
   opened more than `project.OPEN_CEILING` (3) times in one round after a failed cure of it there. A
   passing cure is not counted, so a fault that recurs but is cured at the first try never spends it.
   A spent budget is no stop of its own: no further `--cured` is accepted until you classify the fault
   (your judgement, recorded): `python3 audits/stops.py classify --stop S<n> --as
   tool-bug|interference|other --evidence "<why>"` -- `tool-bug`: the check or tool is wrong, the
   tool-patch route; `interference`: another program keeps changing the project's files, stop 3 (show
   the human the recurring events, `close --human`); `other`: neither, name the different cure you
   will try and `close --cured` once more. A stop you opened in error (the fault's route is not a
   stop, or the wrong check or round): `close --withdrawn "<why, and the route instead>"`. A stop whose
   fault you cured is not one: close it `--cured`, also when the check still prints only `adj-record`
   faults the cure itself created (the next adjudication's: they count as passing; a withdrawal of such
   a stop goes through with a NOTE, recorded in its close, that `--cured` was the right close). It is
   release only, never for a human stop, and is refused while its check passes, while it still shows a
   redo or tamper fault on the current round, even one that appeared after it was opened (set the
   round aside and redo it, or restore, as its cure says), or, the
   budget spent, until you classify it `other`. It counts as a failed cure, and RUN_RECORD lists it. A stop
   round that is not a real round of the run is the
   human's. The run record `RUN_RECORD.md` names every self-cure ("Stops cleared without you", with
   what was redone and where the independence of a review was compromised; the report and the summary
   do not; `project.py --deliver` names an omission in a note, and you correct RUN_RECORD.md). In both modes
   `--deliver` re-runs on the state delivered the math gate -- Phase 0 read-only (build, sorry scan, axiom sweep,
   freeze), `fingerprint.py --check` (once something is approved) and `integrity.py --check` (refusing only on a fault
   of the proof-validity core, a freeze record or a judgement record; any other integrity FAIL is a note) -- and
   refuses on its failure; every self-cured stop's own check is re-run too, a failure printed as a note for you to
   judge. A refusal is cleared only by fixing what the check reports (and re-running
   `--deliver`); closing a stop does not clear it, since the check itself is re-run. A
   self-cure whose check names a round since set aside or superseded is not
   re-run (it held for that round only): its committed passing record is verified instead. A redo
   stop whose round its own self-cure set aside (`set-aside <R> --stop S<n>`) is closed on the fresh
   round that redoes it: the set-aside round keeps its faulty files as record, so its check would fail
   for ever; `close --cured` re-runs the recorded check with `--round` the fresh round: scoped after the
   set-aside while the stop is open (`scope.py` records `redo_of` in its TARGET.json), covering the
   set-aside round's scope with sealed verdicts on every item of it (a diff round cannot cover a
   full or statements round: scope it with that round's kind, `--statements` or `--full`), recorded as `redo_round`; it refuses, spending no
   attempt, until that round exists, and refuses for the human when the lineage cannot be read. When
   the recorded check names no round (`tree_state.py --check`, say), the cure also runs `lanecheck.py
   --round <the fresh round>` (and `--deliver` re-runs it). A fresh round that fails with other codes
   only charges the failed cure to those codes.
3. **Any other class**, under a delegating level in `dev` mode (in `release` mode it is a self-cure,
   above): cure it as the failure table says (mechanical:
   "A child that failed mechanically" in `spawn-and-seal.md`, or the code's own cure; document:
   RUN.md's narrow exception; lane-fault and settle: the adjudicator), then `python3 audits/stops.py
   close --stop S<n> --delegated "<what was done>"`. It re-runs the check, refuses while it still
   fails or for a STOP class, and logs the [DELEGATED] line.
   **Class record-fix** (`dead-witness`, `record-cite`: an adjudicator's record cites what does not
   exist) is yours at every level, the involved level included: cure it by a record correction
   (the failure table above; AUDIT_PROTOCOL.md "Record correction"), then `close --delegated` (`release`:
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

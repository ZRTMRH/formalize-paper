# Changelog

## Unreleased

### 0.3.2 release notes (2026-11-24)

- **KNOWN_LIMITATIONS:** two entries added from the final end-to-end tests, both deferred to the next version:
  answered questions shown as open in REPORT section 8 and RUN_RECORD at the `involved` level, and an intake
  note about running the tool recorded as a condition (a "K reached for 0 of N" line). Documentation only.

### 0.3.2 W-R8 (2026-11-22; REVIEW-WHOLE-032-FINAL L1-L7, L11, L13)

- **`project.py --log`** matches a `[DELEGATED …; reversal: X]` tag's cost ignoring case and whitespace and logs
  its canonical form (`New  Round` is logged as `new round`); any other X is still refused, nothing logged (exit 2).
  The W-R3 header's "No new stop or question" missed this refusal: it was one new curable refusal. Selftest
  (W-R8 L7) added; mutants WR8-L7a, WR8-L7b added.
- **Text:** stage 5's "No third delivery" exceptions add a `[status-wording]` note, a later reversal and the K
  stage; non-vacuity 4b splits its probe file only when a cut's NOTE says it is too large (an inconclusive cut is
  re-run, rule 9); rule 9: after a second inconclusive cut the item is marked NotDoneYet with the comment
  `memory`; stage 3's machine note: 16 GB is the minimum for a long paper, 8 GB runs a short one on the 8 GB
  route; release stop 1 has one wording in RUN.md (twice) and the stops file ("looks false, true only vacuously,
  unprovable …, or stays unproved"); stop 3's "only for" lists include a change to the user's own files;
  `codex.md`: a confidential paper gets no citation notes under Codex (no `--search`), and the completion message
  says so (the intake text, and its hash, unchanged).
- **KNOWN_LIMITATIONS:** the stale intake question 7 entry is removed (q7 names the memory routes); the no-goal
  limitation added (no stop for a false result; the goal list not checked against the 2b answer).
- **Moved from 0.3.1** (a 0.3.2 change): the licence file is now written by a setup command
  (`project.py --license`), so Claude Code's auto mode no longer blocks it (it often denied the file copy used
  before).

No new stop or question; one refusal narrowed.

### 0.3.2 W-R7 (2026-11-22; REVIEW-W032-R6-COMBINED-CODE H1, L1-L6, REVIEW-COMPAT-W032-R6-COMBINED L1-L4)

- **Pause deadline:** a re-pause of a probe the guard had already paused and resumed is now counted (a resume line
  drops a pause record only if it ended that record's pause), so such a probe is extended and, if cut, called
  inconclusive rather than too large (its NOTE's pause seconds come from the same read); `pause_secs`, the
  summed variant, is fixed the same way. A pause record older
  than the wrapper's start is ignored. Selftest (z0n) added; (z0b)'s fixture starts its window before its records;
  (z0i), (z0c2), (z0d), (z0j) given wider timing margins for a loaded machine. Mutants PD11, PD12 added.
- **`project.py --log`** no longer refuses an entry with control characters (see W-R6 below); WR6-g re-pointed,
  WR7-L1 added.
- **Wording:** the wait plus a probe take "about 540 s" (the SIGTERM/SIGKILL waits can add a few seconds); rule 9
  says a cut whose NOTE says too large is split; the second 2b ask's answer is final; with no goal, REPORT section
  10's walk is headed "Unused formalized results" (mutant WR7-L5); the cure section of the stops file is read before
  the first `stops.py open` or `close` in a conversation. No new stop or refusal.

### 0.3.2 pause deadline (2026-11-21; approver, DESIGN-PAUSE-DEADLINE with REVIEW-PAUSE-DEADLINE's changes)

- **A probe's time limit no longer counts the time the memory guard paused it.** `lean_slot.py run` cuts a probe
  once it has run 240 s unpaused, and at the latest when the slot wait plus the probe reach 540 s (today's worst
  case, under a 600 s tool call). The pause time is the union of the guard's pauses of the probe's processes, read
  only when a deadline is reached; if it cannot be read the probe is cut at 240 s as before. A cut probe that ran
  180 s or less unpaused is inconclusive ("re-run, this is not a too-large probe"); a cut at the cap says
  `cut after W s at the C s cap`. At the cut the wrapper sends SIGCONT right after SIGTERM, so a stopped probe dies
  at once. The call's budget counts from the start of `main`. Selftests (z0b) refitted, (z0c2)-(z0m) added
  (including a real SIGSTOP/SIGCONT); mutants PD1-PD10 added, LS-3 and LG-23-25 re-pointed. No new stop or refusal;
  the guard and its decisions are unchanged. A paused probe now keeps its memory and slot up to 540 s, not 240 s.

### 0.3.2 W-R6 (2026-11-21; approver items 3-5 and N1, AUDIT-E2E-032-T009-NOGOALS N2-N5, AUDIT-E2E-032-8G-MAC-R3 b c g i j)

- **No goal named at intake** (approver N1): an empty `goal_results` means no result is a goal (stop 1 does not
  apply). When 2b names no goal, the intake asks 2b again in the approver's words; "every result is a goal" lists
  every numbered result in `goal_results` at Stage 1 (before the pin); insisting on none keeps it empty, logs the
  reply verbatim, and Checkpoint A states the consequence. The lanes' `<GOAL-RESULTS>` fill for an empty list no
  longer says "treat every result of the source as a goal". With no goal, REPORT section 0 promises no goal
  status, section 10 is titled "Proof routes", its walk says "no goal result was named at intake", and SUMMARY
  says "No goal result was named at intake." A delegated Checkpoint C line names an earlier missing-theory
  decision's result by its Lean name. An existing config with an empty `goal_results` now means no goal; before
  upgrading a run mid-way, list its goals in the config.
- **Approver wordings:** the K reminder's human-condition line reads "You chose this restriction during the run (at
  the start, or when approving the statements)."; the Stage 2 PDF-only bullet is the approver's wording again
  (trimmed), not the compaction's pointer.
- **Mac R3 audit:** non-vacuity 4b puts all of a lane's triviality probes in one file (one `example` each, its own
  heartbeat limit; split only at the 240 s cut); the 8 GB route spawns the non-vacuity lanes first; `project.py
  --log` turns CRLF into LF, strips other non-printing control characters (newline and tab kept), logs the entry
  and prints a note naming what it removed; SUMMARY never asks whether a result
  the paper attributes to others is the paper's own; the K closing line names the results behind each gap kind.
- **Code removed:** `integrity.py --commit-reader-fix` (unreachable since `prompt.py --reader-fix` went in 0.3.2);
  the verifier of older runs' reader-fix commits stays. Mutants b10-29, t9d-1, t9d-4 retired; WR6-N2, WR6-N3a-c,
  WR6-g added; M62 re-pointed. No new stop or refusal.

### 0.3.2 compaction (2026-11-21; DESIGN-W032-COMPACT rev 2, reviewed)

- Text only, no behaviour change, no new stop, refusal or mechanism. Lane prompts: the common rules 7, 9 and 10
  tightened (rule 10 now covers every Lean file a lane compiles, scratch or probe), the seal rationale and review
  ids dropped, the read-only line moved into the common head. RUN.md: the release-cure mechanics ("close --cured",
  failure tally, cure budget, classify, withdrawal, redo stop's fresh round, what `--deliver` re-runs) move verbatim
  to `run/stops-and-set-asides.md` item 2, read by section before the first `stops.py open`; "Statement changes
  after approval", the round-cap routes and the tool-bug bullet point to the files that hold the detail; the
  "Fixes to try first" list moves to the stops file item 1. Review ids and approver dates removed from agent-read
  text (not from the generated release column or the intake message). Adjudicator: small trims (T10 b, d-g).
- Code: unused `lanecheck.revote_lane`, `decisions.RESULT_RE`/`result_of` (mutant rv-H2a now inlines the regex),
  `hypotheses.mt_rulings`, `stops.SET_ASIDE_RE`, `prompt.HERE`, doclint's `PENDING_SCRIPTS`, the uncalled
  `readers.py --next` and `result_status.py --live` flags, and a never-reached selftest stub removed.

### 0.3.2 W-R5 AP2: rolling lane spawns at the same cap (2026-11-21; REVIEW-MEMORY-AP2 conditions)

- Lanes are spawned rolling: the first up to the memory route's cap in one message, then the next lane once a
  returned one's seal command has finished (Codex: its child closed); the cap counts agents running now (8 GB: 2 of
  any kind). `lanecheck --kill` runs only when every lane of the round has returned. `lean_slot.py --show` prints
  "at most W lanes at once". Guard and slot code unchanged.

### 0.3.2 W-R5: approver decisions AP3 AP5b AP6 AP7 AP9 AP11 AP13 (2026-11-21)

- Text: two equivalent phrasings of a definition are a K representation change (bridge tip at Stage 2); a PDF-only
  paper's related pages are read as page images (RUN.md rule 13); `reversal: re-approve` for "missing theory: build"
  and for a reading that would change an approved statement; F12 minimality by the counterexample alone when the proof
  never argues the failing clause ("no printed step"); the adjudicator may mark a helper-only UNCOVERED row expected,
  with a reason; the SUMMARY K reminder's other gap kinds in the approver's words, and the CLAIMS/READABILITY check
  against suggesting carelessness; a goal false only by an evident misprint is release stop 1. Code: `scope.py` reads
  the `(expected` mark in an UNCOVERED row's decision cell too. No new stop kind or refusal; AP13 adds a case to
  release stop 1.

### 0.3.2 fix round W-R4 (2026-11-21; AUDIT-E2E-032-INVOLVED, -KWALK, -FALSEGOAL, -T008-PDF, -CODEX, approver)

No new stop or refusal; one question inside the existing Checkpoint A wait (intake 5c (b) with 5d the agent).
- **A goal result refuted as printed** (a witness in the paper's notation, rule G's F10 test; not a Lean encoding
  artefact, not a stated convention) is release stop 1 at once (`GOAL LOOKS FALSE` in the QUESTION row), never a
  delegated reading; restricting it away is a repair. Genuine two-reading cases and non-goal results are unchanged.
- **Probe slots.** `lean_slot.py` opens an existing slot file without `O_CREAT` (another account's file is usable);
  an unusable slot file is skipped and the probe waits for another, running unslotted only when every slot is
  unusable. `--show` counts the memory guard's pauses since this run's pin (this account's guard log, named).
- **Diff base.** A statement round is no diff base (`_meta.base_rule: 2`); a TARGET.json without it verifies under
  the old rule. K-stage re-approvals: a statement round, then one diff round.
- **Empty-commit route** `fresh full round on <R>` when a full round on HEAD was adjudicated and is not settled
  (`scope.py` prints it; `tree_state` accepts that subject only).
- **Checks.** `lanecheck` skips a loop wrapper whose direct child carries `FORMALIZE_PAPER_OPERATOR=1`; REPORT.md
  names a stop case-insensitively; `decisions.py --check` does not count the header comment's `<<FILL`; release
  `--note` stops read "release stop <k> (<label>)" in the documents.
- **Documents.** README under `involved` no longer says "hands-off" and drops the reader sentence when a fresh
  reader read the sheet; the sign-off sheet quotes the `involved` intake answer; a PDF-only source gets PDF
  locations in the glossary and a disclosure. SUMMARY carries a K reminder (whose side each gap is on); the
  completion message ends with a verbatim block; K questions offer "Something else", skip and stop.
- **Text.** K3 bridges only by a project declaration; PDF sources read as page images; intake 5c (b) with 5d agent
  asked again at Checkpoint A; non-vacuity 4b on index rows only; citation notes start at the beginning of
  Stage 5; `literature_hypotheses` frozen at the pin; `decisions.py --check` after each prepare; condition ids
  `C<n>`; declarations on their own lines; build after a merge; operator scratch never `/tmp`; Codex reads
  stage files in ranged parts. Common-rule changes (PDF reading, never `/tmp`) alter the generated Codex roles:
  `install.sh --upgrade --codex` regenerates them.

### macOS branch: the 0.3.2 port (2026-11-18; BUILD-MACOS-032)

- **The guard self-test's macOS stand-in is named `lean-fp-test`** (0.3.2 A1): on macOS it is a copy of the
  interpreter's binary (a symlink keeps the target's name there), now under that name, so a live guard on the Mac
  never pauses it; the outer-guard test (z8) also runs on macOS, where both guards read processes through libproc.
- **INSTALL's 8 GB line follows the 0.3.2 route**: say the RAM at intake question 7 (1 Lean probe, at most 2 agents
  at a time), in place of asking for one agent at a time.
- **Merge of 0.3.2 W-R4 to W-R7 (2026-11-22):** the stray-loop check's wrapper rule (W-R4 B4) works without /proc:
  `_children` reads libproc's table on macOS (`ps` elsewhere) and `_cmdline` reads KERN_PROCARGS2 (`ps` elsewhere);
  its self-test narrows the macOS table to its own wrappers and says it is skipped when a SIP-protected `bash` hides
  the tag. INSTALL: poppler is needed for a paper given only as a PDF (RUN.md rule 13).

### 0.3.2 fix round W-R3 (2026-11-19; AUDIT-E2E-032-32G-T005, -8G-MAC, -MATIJASEVICK, approver)

No new stop or question.
- **Background moves.** A lane, the formalizer or the adjudicator whose command the harness moves to the background
  does not stop it or start a second copy: it waits for the completion notification, reads the output file, and
  never hands back its result while the command runs.
- **No `pgrep -f`/`pkill -f`** of a pattern (RUN.md rule 9, spawn-and-seal, lane rule 9, and new rule 5 of the common
  rules for every other subagent): wait on the notification or the `[exited with code` line; stop with TaskStop or a
  recorded PID. The common-rules change alters the generated Codex roles: `install.sh --upgrade --codex` regenerates them.
- **Checks.** `prompt.py --show` prints the render check's findings on the config (`# config: …`, e.g. a bare `l.N`
  in `literature_hypotheses`) before the pin; `project.py --log` refuses a `[DELEGATED …]` tag whose reversal is not
  one of the four costs (nothing written, exit 2). Stage 1: run `prompt.py --show` after every config edit.
- **Text.** Unused arguments dropped once per merge in one change, a cascade left to the adjudicator; index labels in
  Unicode (stage1's "`$…$`" instruction corrected) and missing-theory lines logged before the first Phase 0; Stage 4
  goes to Stage 5 without a diff round when the adopted fixes change no approved statement and leave no proof work;
  no bare stdin readers; a SUMMARY/REPORT drafting helper returns text; citation notes start with Stage 5's full
  round; no new `CONDITIONS.md` item at the NOTES step; K only through the result's own approved statement; the
  adjudicator defers clean-up findings under `goal: faithfulness`; unnumbered running-text claims settled at Stage 2;
  F12 and the formalizer's "A result false as printed" bullet: restrict only the failing clauses, or say the true
  clauses lose the case; a case nonempty only if an open conjecture of the paper fails is no vacuity question.

### 0.3.2 fix round W-R2 (2026-11-18; AUDIT-E2E-032-16G, approver)

No new stop, check or question.
- **Text.** Stages 2 and 3: never put `omit … in` / `include … in` directly after an approved definition (the
  freeze reads it as part of that definition: a DRIFT stop); Stage 2 step 1: name every `instance` before the first
  scope. Non-vacuity rule 4b: a closure only through a verbatim project twin of the audited statement is no
  closure; the twin is probed instead.
- **Report.** A statement round set aside before any lane was issued is not "the first statement round" (no false
  "N statement(s) changed" line); the Verified line names `SKIPPED.md` only when it exists and excepts the
  declarations section 1 lists as removed.

### 0.3.2 fix round W-R1 (2026-11-18; REVIEW-WHOLE-032, REVIEW-COMPAT-D032-1)

No new stop, refusal or question. `VERSION` is `0.3.2-rc1` for the end-to-end runs.
- **`install.sh --upgrade --codex`** replaces the project's generated roles (`.codex/agents/formalize_*.toml`, a
  role this version no longer generates included) instead of refusing an older version's; `tests/upgrade.py` covers it.
- **A reused tool-patch floor is said** at `--deliver`: one note `floor reused: tooling digest <12 hex> matched`.
- **Text.** Stage 5's "no third delivery" names the steps that deliver again; Stage 3's NEEDS-HUMAN answer is
  decided, not asked, under a delegating level; the blind informalizers stay within the 8 GB route's 2 agents;
  pointers moved with the failure table name `run/stops-and-set-asides.md` or `RUN.md`; pointers into that file
  name their section, and its first lines say to read only that section. RUN.md's rule 4 no longer lists the owners
  no current step commits under (`reader-fix`, `reader-fix-prompt`, `hand-edit`; `integrity.py` still checks them).
  Codex launch commands are shown as two lines, public paper with `--search`, confidential without.
- **Probe slots on about 17.7-21.9 GB** are 2, not 3 (approver 2026-11-18, "Keep 2": 16 GB = 2 probes, waves of
  6): the derived S is 1, 2 or 4; a hand-set `lean_slots` 3 is kept.

### 0.3.2 Phase A: two blind readers; a wrong name in the blind reading is a flag; small fixes (2026-11-17; DESIGN-A032, approver)

No new stop or refusal.
- **A wrong name in the blind reading is a flag (D3).** A Lean name that does not exist, cited by the write-once blind
  reading (INFORMAL.json), is now `NOTE[signoff-check]` and no longer a `signoff.py check` problem. The same holds for
  a SIGNOFF.json `plain_english` that is equal to the blind reading's text for that row. Every field the sign-off
  writer authors (a different `plain_english`, `differences`, `paper`, the definitions) stays a problem. This
  replaces the set-aside cure for such a name given in the X1 entry below. TRADEOFFS T69.
- **Two blind readers (A7).** Stage 2 spawns two independent informalizers. The second writes `INFORMAL-2.json`
  (`signoff.py save-informal --second`, write-once, owned like INFORMAL.json). The sign-off writer compares the two
  readings and marks a substantive difference CHECK. No code compares them (TRADEOFFS T70). Fix round A-R1: `check`
  prints a NOTE when the second reading was asked for (`prompts/informalizer-2.txt`) but not saved, or when it is
  byte-identical to INFORMAL.json. Fix round AB-R2: delivery repeats the approved round's notes, so the NOTES
  reviewer judges them under hands-off too.
- **Smaller fixes.** The memory guard's self-test stand-ins are named `lean-fp-test`, so a live guard no longer
  pauses them (A1). The leak control pairs only projects with different sources (A2). A bare reliance check skips a
  line that is exactly a generated escalation record line (A3a, the TP3 port). A refutation proved at universe 0 is
  accepted for a universe-polymorphic statement (A3b). `adj_verify` returns four values on a bad round,
  `readers` decodes KNOWN_FAULTS with `errors="replace"`, and summary note ids no longer depend on the hash seed
  (A4a-c). `tool_patch.py withdraw` commits the TP's drafts too (A4d). A declined no-round prints its reason (A4e).
  The text says that `close --cured` is the release form of a record fix (A5).

### 0.3.2 Phase B: compaction (2026-11-18; DESIGN-B032-r2, approver)

Removals only; no new stop or refusal, and no cure changed.
- Dead code and older-run text removed (pure cuts; `stops.deliver_gate` callers now call `math_gate`). The
  resolver-era compatibility rows (`resolutions/*`, `*/.superseded/*`, ownership 1) are gone from integrity.py and
  lanecheck. Read-only Phase 0 no longer runs `unused_args.py`, so the adjudicator's Phase 0 log carries no fresh
  unused-argument list: a stale `UNUSED_ARGS.md` (its header not naming the adjudicated commit) is its only signal. `codex_spawn.py` is removed.
- The summary-coverage delivery note is cut (D2 b), and with it the summary's "reads plain although a record names
  it" check, whose only live caller it was.
- The status-check prompt, the reader-fix route and the hand-edit listing are removed, with the code that produced
  their records (D1). Older runs' records are still read. On such records there is no reader-fix routing and no dev
  past-budget stop, and a "hand edit HEk" answer is not cross-checked. There are ten Codex roles.
- One `rounds_dir`, one `_col`, one escalation-citation pattern. RUN.md's failure table moves unchanged to
  `run/stops-and-set-asides.md`, and RUN.md keeps a pointer.

### 0.3.2 Phase C: speed and memory routes (2026-11-18; DESIGN-C032-r2, approver C-D1..C-D3)

No new stop or refusal.
- **Faster freeze and sweep checks (C-D2, F-1).** The fingerprint and axiom-sweep tails take their candidates from
  the module tables (each constant once) instead of every constant of the environment; the same declarations are
  decided by the unchanged rules (nie-wei: 299 s to 0.4 s and 233 s to 10 s). The fingerprint tail stops with an
  error on a candidate it cannot resolve (fix round C-R1).
- **Memory routes (C-D3).** P = 3.2 GB per probe and 4 GB of shared .olean pages counted once give 1, 2 or 4 probe
  slots: the 8 GB route (at most 2 agents at once), 16 GB (waves of 6) and 32+ GB (waves of 8);
  `lean_slot.py --show` prints the route, from a lower hand-set `lean_slots` when there is one (C-R1). Slot waits
  are logged.
- **Faster self-test.** `selftest_all.py --jobs N` runs the scripts in a pool and ends with the tooling id;
  Stage 1 starts `--fast` at step 1 in the background (it needs no project, also when another paper's config
  exists: C-R1) and checks the id before the pin. tool_patch's selftest fixture carries a FLOOR of 3.
- **Tool-patch floor reused at delivery (C-D1).** `--deliver` reuses the floor FACTS judged at prepare when the
  tooling digest matches byte for byte (every extracted file, `__pycache__` included: C-R1); otherwise the full
  floor runs. TRADEOFFS T71. The apparatus is extracted with one `git cat-file --batch`: the committed bytes,
  whatever attributes or `core.autocrlf` say (C-R1).
- Sign-off render/approve reuse one fingerprint run; Stage 5 orders delivery so fixes fold into one `--deliver`.

### 0.3.2 D8: the 0.2 decision-row reader is removed (2026-11-18; approver D8)

No new stop or refusal. `audit_coverage.read_adopted` reads every ADOPTED.md through the strict reader
(`lanecheck.valid_rows`); the best-effort reading kept for records with no pin or a pin of ownership 1 is gone, with
`strict_rows`. A 0.2 run keeps its pinned tools. Read by these tools, such a record's rows that name no lane or item of
their round decide nothing. Self-test fixtures write their rows with `lanecheck.fixture_rows`.

### 0.3.2 Phase D: the citation check under Codex (2026-11-18; DESIGN-D032, CANARY-D032, approver D7, O1, O2)

No new stop, refusal or code switch; the citation step stays advisory.
- **Public paper: start Codex with `--search` (D7).** Every child inherits live web search (canary-verified);
  `install.sh --codex` prints a public and a confidential launch line. A confidential paper keeps Codex's default
  cached search and the prompts' title-and-authors rule (O1). The shell network stays off.
- **The citation role says that web search is not a sandbox command** (`codex_agents.CITATION_SEARCH`): in the
  canary its child read the sandbox rule's "(no network" as no search and reached nothing; with the sentence it
  read all four sources. Only that role's bytes change (`install.sh --codex` regenerates). TRADEOFFS T72.

### Filling a proof inside an approved definition is no drift; hands-off re-approves (2026-11-16; DESIGN-FP, approver)

- **Proof-erased definition fingerprints (decision 1).** In a definition's value every proof subterm (an
  expression whose type is a proposition, decided by Lean's `Meta.isProof` on the elaborated term, never on the
  source text) is replaced by one fixed marker before hashing (`fingerprint_tail.lean`, `auditFpEraseProofs`).
  Filling a `sorry` in a proof field of an approved instance or structure value, or rewriting such a proof, no
  longer drifts the approval (De Medts e2e, stop S1: 14 of 33 approved declarations drifted because Lean names the
  aux proofs of an instance's proof fields and reuses them across a module). Everything else is hashed as before:
  a theorem's statement, a definition's type, its data (also data built by a tactic), a structure field's type,
  a `Decidable`/`DecidableEq` value. A definition with no proof subterm keeps its old hash exactly.
- **Disclosed consequences.** (a) A definition used only inside a proof is no longer a dependency, so the sign-off
  sheet's "Definitions these statements use" may list fewer definitions (only those reached through data or
  types; approver: "Accept, disclose it"); by proof irrelevance such a definition cannot change what a statement
  means. (b) `opaque` values are not erased (they still drift on any change). (c) A change confined to the proof
  inside a `Decidable` value (`isTrue rfl` to `isTrue (by decide)`) does not drift; a change of the decision
  procedure does. (d) A proof written inside a statement (`(⟨2, by decide⟩ : Fin 3)`) is part of the type and still
  drifts. (e) The approved statement text (STATEMENTS_BUNDLE.md) still shows a named definition's source, so filling
  a proof field written there still changes that text (a freeze self-cure, then a re-approval).
- **Upgrading.** Hashes change for definitions with a proof subterm, so an approval made with the old code does not
  match the new one: a run in progress keeps its pinned code; a project upgraded between runs starts a fresh run
  and re-approves (INSTALL.md, "Upgrading"; it never checks an old `APPROVED_FINGERPRINTS.json` with the new tail).
  Runs are not upgraded mid-run: a maintainer `--repin` of a running run onto this version (dev only) makes every
  approved result over a definition containing a proof show DRIFT (it fails safe).
- **Helper names (REVIEW-SAFETY-FP F1).** The fingerprint program's own helpers (`auditFpStripMData`, `auditFpKey`,
  `auditFpEraseProofs`) are excluded only as declarations of the appended file; in `import` sweep mode (the
  default) a project module's declaration under those names (`auditFpEraseProofs.evil`) is now fingerprinted. In
  `append` sweep mode the project's text is part of the appended file, so such a name is still excluded there
  (as before this version; KNOWN_LIMITATIONS).
- **Hands-off re-approval (decision 2).** The 2026-11-14 restriction that a `hands-off` run re-approves only missing
  theory turned into a named hypothesis is removed: under `hands-off` the agent decides any intended change of an
  approved statement by re-approval, except the D2 cases (a faithfulness finding after the sign-off, a refuted
  non-goal statement: keep the approved statement, [DELEGATED keep], a `CONDITIONS.md` `finding` item; the
  adjudicator never ADOPTs such a change, it writes a QUESTION row). `involved` and `statements-only` unchanged.
  Text only (`RUN.md`, `run/reapproval.md`, `run/stage3-proofs.md`); no new stop or refusal.

### The code writes no K content; the run's agent judges K (2026-11-16; K-REMOVE, approver's decision, option A)

- Approver: "remove the code output. Just let agent judge." All code-generated K content is removed from the
  deliverables: the SUMMARY's "K reached for X of N results" line, REPORT's K count, per-result K1-K4 table and
  open-items list, the README's K line, and the delivery notes that compared the SUMMARY's count with the code's or
  reported a missing K line. `result_status.k_status` and `make_report.k_facts` are gone. The code's K was wrong on
  the last run (AUDIT-P7 §8): an open item on a helper lemma counted against every result.
- REPORT keeps section 12 "K certificate": the facts draft holds the definition and a place for the formalizing
  agent's judgement, which run/stage5-delivery.md tells the agent to write (per result K1-K4 with reasons and
  file:line evidence, the count, the open K gaps with the results each affects) together with SUMMARY's K line.
  The CLAIMS delivery reviewer checks it. The conditions-checklist notes (inferred items included) stay, as flags
  for the agent. Only removals and wording: no new check, stop or refusal.

### macOS branch: two process-table races under load (2026-11-16; found live on the Mac end-to-end run)

Both were applied in that run as an operator-authorized tool patch (lin-2026 TP1) and are ported here; neither adds
a stop or refusal, and both keep the fail-closed rule (a live process that cannot be read is never read as none).
- **`stops.py repair-lock` skips a git process that has exited.** On macOS a short-lived git process listed by
  libproc but gone before `lsof` reads its working directory made repair-lock refuse ("cannot read the working
  directory of git process N"), so stops.py's selftest, and a tool patch's facts step, failed on a busy Mac. Such a
  process (`os.kill(pid, 0)` gives ProcessLookupError) is now skipped, as the ps and /proc branches already did; a
  live one still refuses.
- **The libproc process table reads a pid's arguments again on EIO.** `sysctl KERN_PROCARGS2` returns EIO for a
  process exiting or exec'ing; one such read made the whole table raise `NoProcessFacts` (lanecheck.py's selftest
  crashed in 20 of 51 runs beside a facts step). An EIO is now read again (5 reads, 50 ms apart); a process that
  exited meanwhile is skipped; an EIO that persists for a live process, or any other error, still raises.
- Selftest cases on a faked table (run on every platform); mutants MAC-TP1a/b (the unsafe directions) in the
  tool-patch floor.

### A redo's fresh round cures a set-aside stop (2026-11-15; STOPFIX and DESIGN-ND)

- **A self-cure bound to a set-aside round re-runs on the redo (STOPFIX).** A self-cure stop whose check names its
  round (`--round R`), when R was set aside naming that stop, now re-runs its check on the fresh round that redoes R
  (`TARGET.json` `redo_of` R), as a redo-kind stop already did. Before, the check kept running on the set-aside
  round, whose write-once records kept it failing for ever. A check that names no round is unchanged.
- **A NotDoneYet in the fresh round counts once the adjudicator ruled it (DESIGN-ND).** An item a sealed lane of the
  fresh round left NotDoneYet counts as covered for the redo when ADOPTED.md, as first committed by
  `adjudicate <fresh round>`, has an UNCOVERED row for that lane and item (the existing step E ruling; no new form).
  The item is still reported as not examined, with no verdict; nothing reads it as passed.

### Undecidable name and label extractions no longer stop a run (2026-11-16; DESIGN-SW2B and its review)

Each change only removes a hard stop or failure; no new refusal or stop.
- **Dot notation on a variable (X1).** A dotted name the sign-off sheet's texts cite whose first component is no Lean
  name (`G.Adj`, `G.chromaticNumber`) is printed as `NOTE[signoff-check]` and no longer fails `signoff.py check`; it
  comes back at delivery as a note for the NOTES reviewer. A wrong global name (`Finset.Foo.card_le`) still fails. Stage 2 step 7 named the cure for a wrong name in the blind reading: set the round
  aside on its stop (`--stop S<n>`), redo it with a round of the same kind, close the stop `--cured`. Superseded in
  0.3.2 (Phase A, D3): such a name is a `NOTE[signoff-check]`, with no stop and no set-aside.
- **Record citations of library names (X2).** A dotted non-project name cited at `File.lean:N` is resolved in Lean:
  a wrong global name is still a dead citation; a variable's field at the line that shows it passes; elsewhere it is
  a note in the report ("Citations the check could not decide") and a delivery note. No answer from Lean: as before.
- **Lettered, appendix, primed and part labels (X3).** A SKIPPED.md "what" cell naming `Theorem A`, `Lemma A.2`,
  `Theorem 1.1'` or `Lemma 2.3(b)` exactly explains the index row.
- **Dates in row citations (X4).** "VACUOUS row 4, 2026-11-15" cites row 4 only.
- TRADEOFFS T65-T67; KNOWN_LIMITATIONS updated.
- Fix round (REVIEW-SAFETY-SW2B, REVIEW-COMPAT-SW2B): a name whose first part does not look like a variable
  (`Reals.sqrt_le`, "Mathlib's `Turan.bound_le`") is noted "likely a wrong name"; a name only in a Lean comment at the
  cited line is a note, not a pass; a SKIPPED.md cell explains a lettered label only as its first label, the letter
  case-sensitive; four more unsafe-direction mutants in the tool-patch floor; step 7 says what `dev` does.

### Hard prose checks become curable; flags reach a judge (2026-11-15; DESIGN-SW2 and its review)

Each change only removes a hard stop, refusal or wait; no new refusal or stop.
- **An old round is judged on its own Lean (C2).** The settle check that `integrity.py --check` and the report check
  re-run on committed adjudications reads the names declared at the Lean commit the round audited, or now: a later
  rename no longer makes an old adjudication `FAIL[unsettled]`; a fault present at both commits still is.
- **A human answer counts by provenance (C3, approver Q5).** Under `involved`, a Checkpoint C answer that points to an
  option the operator offered (an escalation's answer, an adjudicator's record, the conservative rule) is the human's
  answer; the summary shows "your answer adopts … as your own". A [PROXY]/[DELEGATED] tag still answers nothing.
- **The human's verbatim words (C4, C6).** A tag-like phrase or a "VACUOUS row N" citation inside the human's
  `- answered …` words (and the other human-quote forms) is no longer a report failure.
- **Missing-theory head (C7, C8).** A `missing theory:` line whose body is no decision goes to the adjudicator
  (`MT RULED`) instead of a FAIL with no honest cure; a hypothesis that restates a goal result is the operator's
  curable FAIL ("use that result"), no longer stop 1.
- **A stale leave line (C10).** A `leave <goal> unproved` line no longer opens stop 1 once the goal has no `sorry`;
  Phase 0 prints it as stale.
- **The paper's own negative result (C5).** A `¬ X` declaration (X a project Prop) that its own index row cites is not
  read as refuting a printed statement; the correspondence lane of that row is told so (NEGATIONS TO JUDGE).
  `_statement`/`_as_printed` targets and refutation-like names stay hard.
- **Adjudication commit (C19, C24, C15, C32, C9).** The commit no longer refuses a missing-theory suspect its prompt
  did not list (the next round's prompt lists it); a cure that leaves only a dead-witness or record-cite residue
  closes `--cured`; a re-vote lane whose only NOTE mentions a record file other than ADOPTED.md may be CLEARED; a
  Fail on another item that only mentions a hypothesis no longer forces `matches source: no`; the adjudicator's
  STOP text goes on past non-core integrity codes and record-only Phase 0 REDs (doclint pins the code list).
- **Delivery notes are judged (1.14).** Every disclosure reaches the delivery notes in both modes, with its D record;
  every note has an id and a `judged:` field in RUN_RECORD.md; one fresh NOTES reviewer judges them after the first
  delivery; README names every note no independent reviewer judged, every note nobody judged, every note the
  reviewer called a real problem and every note it could not judge ("cannot tell"). A verdict in
  `delivery-review/NOTES.md` counts as the reviewer's only when the file was committed under the subject
  "delivery review" (otherwise it reads as the operator's); README and RUN_RECORD.md say that the formalizing agent
  saves the file, so the record cannot show who wrote it. Nothing refuses.
- Deferred: the Checkpoint A resume hint (TRADEOFFS T64). TRADEOFFS T58-T64; KNOWN_LIMITATIONS updated.

### Missing-theory suspects ruled by the adjudicator (2026-11-15; DESIGN-MT and its review)

- **A missing-theory line only suspected from its words is no longer a failure.** A RUN_LOG.md decision line whose
  words mention missing theory, that is not in the canonical form and that no later canonical line naming its
  result cures, is now `PENDING[adjudication]` (code `adj-record`) instead of `FAIL[missing-theory]`: Phase 0 stays
  GREEN, the adjudicator's prompt lists the line with its id, and `integrity.py --commit-adjudication` refuses
  until the adjudicator rules it once in ADOPTED.md (`- MT RULED <id> | not a missing-theory decision: …` or `| a
  missing-theory decision for `<Lean name>`: …`). Ruled a decision, the operator logs its canonical line
  (`FAIL[missing-theory]` until then). The id binds the line's anchor and its text from the `[DELEGATED` tag on, so
  a Checkpoint C line and its `## Answered` copy share one ruling. Every other missing-theory check is unchanged.
  `--deliver` notes an unruled line as "not judged by an independent agent"; stage5-delivery.md runs one full
  round first. A line naming no Lean result had no cure before (live e2e 2609.08713, stop S1).
- **The human's verbatim words are not tag-linted (D2).** A tag-like phrase (`[delegated to you]`) inside a stop's
  verbatim human answer or a `- human answer (…): "…"` line no longer fails the report check; a dated tag there
  still does.
- **Fix round (REVIEW-SAFETY-MT, REVIEW-COMPAT-MT).** A ruling counts only from a round's ADOPTED.md as of its
  first `adjudicate R` (or `revotes`) commit and only for an id that round's adjudicator prompt lists, so a later
  re-commit of an old round cannot rule a line. A line that tries the canonical form (`missing theory: …`) and names
  its result keeps the hard FAIL. After a decision ruling for a hypothesis the Lean assumes, only its `assume` line
  cures it; a `build` line for a result cures it only once no unclassified hypothesis of it is left. The operator
  may dissent once (`- MT DISSENT <id>: <why>`): the line goes back to the next adjudicator, and a second decision
  ruling is final. The summary, report and README name an unruled line by its anchor, "not judged by an
  independent agent". The ruling id normalizes only a line that opens with its tag; the human-quote mask ends at the
  quote's own closing quote.
- **Fix round 2 (REVIEW-FIXMT).** A re-vote adjudication commit rules only when it holds the round's re-vote
  reviews. A disputed line not yet re-ruled is shown as "ruled a missing-theory decision by an independent reviewer;
  disputed by the operator; not re-ruled", never as "not judged". TRADEOFFS T57: the prompt check reads an
  uncommitted file.
- Docs: `decisions.py --check` is described as advisory (it never blocks `--deliver`). KNOWN_LIMITATIONS and
  TRADEOFFS T53-T56.

### Next batch (2026-11-14; DESIGN-NB: approver decisions D1-D5, fixes B1-B28)

- **The K standard in every level (D1).** A result reaches K when its Lean statement says exactly what the paper
  says, its proof is kernel-checked, every nontrivial change of representation is proved in Lean (a bridge
  theorem), and nothing is assumed. The operator keeps `CONDITIONS.md`, a checklist of the human's own conditions
  (verbatim), scope limits, known issues and open K items; no reviewer reads it. Each adjudicator rules it every
  round (`## Conditions` rows; a condition missing from the list is a `C?-<n>` row, closed once the operator adds
  it). The correspondence reviewer names every change of representation; nontrivial ones become bridge items the
  run proves as pure additions. Ambiguous readings: under `involved` the human is asked when the question appears;
  under the delegating levels the stronger reading, both readings, or the adjudicator's choice, with an open K item.
  REPORT gains a section "K certificate" (K1-K4 per result, the open items numbered), SUMMARY a line "K reached for
  X of N results", the README the same line and, above the approved sheet's CHECK lines, a note that the sheet is
  the statement-stage record. After delivery the human may reply **K** to go through the open items one at a time
  (`project.py --k-stage`; the K stage gets its own two diff rounds). Never a stop or a refusal: notes only.
- **Strict before the sign-off (D2).** Every statement-faithfulness finding is resolved before Checkpoint B (one
  open at the statement-round cap is a Checkpoint B question; under hands-off the last statement is kept and
  disclosed). A notion the paper takes from a citation follows the source and says "taken from <source>, not
  printed in the paper". After the sign-off the adjudicator never changes an approved statement: a finding becomes
  a question (involved) or a kept statement with an open K item (delegating levels); a refuted non-goal statement
  is left unproved, not repaired. **A goal result true only vacuously now stops for the human** (stop 1, the existing
  `unproved-goal` code: the batch's one stop-list change, the approver's wording).
- **A stray script is listed (D3).** `NOTE[unpinned-py]`: every `*.py` in audits/ that no pin's tree holds and no
  tool patch brought, shown by `integrity.py --check`, in the README and in the run record. Never a stop.
- **README:12 L∞ line kept** (D4, approver 2026-11-11).
- **A machine-wide limit on Lean probes (D5, NW-9).** `audits/lean_slot.py run --timeout 240 -- lake env lean
  <file>`: reviewers and helpers compile probes through it; it waits at most 300 s for one of the config's
  `lean_slots` (and `lean_free_mb` of free memory), then runs anyway and says so; a probe is cut at 240 s. It only
  delays, never refuses; tool-internal Lean calls are not slotted. The adjudicator's background checks now run
  `scope.py --verify` too (B13/B11), so it starts no Lean command of its own in Step A.
- **A run cannot starve the computer's memory (DESIGN-RAM).** A memory guard (`lean_slot.py guard`), one per
  account, started by code: a Claude Code `SessionStart` hook that install.sh adds to the project's
  `.claude/settings.json` (it only starts the guard, is silenced and always exits 0), and the pinned scripts
  (`prompt.py`, `lanecheck.py`, `lean_slot.py run` and `--show`; under Codex these are the only starters). Every
  second, when free memory falls below a reserve (max(4 GB, a quarter of the memory)), it pauses this run's Lean
  probes however they were started (all but the oldest at once, or all while a tool check runs) and resumes them
  one at a time when memory recovers. Tool checks, editor `lean --server` processes and Lean outside a run are
  never paused. A pause lasts at most 10 minutes; each pause is recorded before the stop, and a dead guard's
  pauses are resumed by the next start. It never kills, refuses or stops anything. The probe wrapper's settings
  are now derived from the memory when absent (1 slot on 8 and 16 GB, 3 on 32 GB; a floor that can be met on
  8 GB) instead of "no limit", and it says when a probe was paused. Checkpoint A shows the guard's line; a heavy
  Lean file is a note. New optional config keys `lean_ram_mb`, `lean_reserve_mb`.
- **The memory guard also reads memory pressure and new probes' needs (DESIGN-RAM V2).** Besides low free memory,
  it pauses probes when the kernel reports memory pressure (Linux PSI: 5 % or more of the last 2 s spent waiting
  for memory; a resume needs under 1 % over 5 s), and it presumes each probe in its first minute (or first minute
  after a resume) still needs up to 5 GB, so a burst of new probes is paused before it allocates. In a 16 GB test
  with 12 probes started together the machine stayed responsive (memory peak 7.6 GB, no memory stall); without the
  guard seven probes were killed.
- **Fix round P6 (AUDIT-P6): the K certificate no longer counts false sources against every result.** The final
  e2e run (arXiv:2609.08713 at b91644b) reported "K reached for 0 of 25"; the run's own records support 15. The rule
  that an open item naming no result counts against every result is kept; what changed is what makes such items.
  A delegated reading whose RUN_LOG line names the open `reading` item that carries it ("open item C3") gives no
  inferred R? item (a reference to a closed or missing item keeps it, counted open). The adjudicator's B'' gains a
  machine-readable ruling: when no REPRESENTATION note of the round needs a bridge, it writes `| K3-0 | not
  applicable | - | <reason> |`, and no K3? item is inferred from that round's notes; the ruling, and any `K3-<n>`
  row, now applies to its own round only (before, one `K3-` row in any round hid every round's notes). An inferred
  item naming a project declaration that is no longer in the Lean is listed "stale, not counted" (never met), with a
  note and its own list in REPORT's K certificate; with no readable declaration set it stays open. A results cell
  may list labels in plural form ("Theorems 1.3, 2.1, 2.2, 3.1", "Lemmas 2.4 and 2.6", "Lemmas 2.4–2.6"). A result
  with several `proved assuming …` statuses (Theorem 1.4 there) has K1 yes (K4 still fails it). The adjudicator's
  `--wait-adjudicator-checks` returns after at most 150 s (was 540), before Claude Code moves a foreground call to the
  background at 180 s (the two adjudicator respawns of that run); exit 3 still means "wait again". RUN.md asks the
  delegated reading line to end with `open item C<n>`. Replay test on the run's records
  (tests/lane_samples/k-p6-records.json: 0 as recorded, 15 with the `K3-0` rows), mutants P6-1..16.
- **Fix round RAMK (REVIEW-RAMK-NB).** A probe cut at 240 s after a guard pause now says "paused M s by the memory
  guard; the time limit includes the pause -- re-run, this is not a too-large probe", and the reviewer rules call
  such a cut inconclusive, never a reason to mark an item NotDoneYet for its size. The presumed need is sized to
  the machine (2 GB on 8 GB, 5 GB from 16 GB), a resume needs 1 GB above the reserve, and a probe so resumed is not
  paused again by the presumption alone, so a second probe can run on an 8 GB machine or on 16 GB with 8 GB
  available; while the run's own checks run, a probe paused 15 minutes in all runs beside them. A check started as
  `cd audits && python3 phase0.py`, `python3 ./audits//phase0.py` or `python3 -m audits.phase0` is recognised as
  the run's own check and never paused. The guard acts on every formalize-paper project of the account (the docs
  said "this run's"). On macOS `lsof` is cached per tick and `ps` runs in the C locale. A closed `reading` item that
  names only a result's row no longer hides another delegated reading on that row (it counts open).
- **macOS branch: the memory guard reads processes through libproc.** On macOS the guard's process table, command
  lines, working directories and memory come from libproc and sysctl (the calls Codex's macOS sandbox allows, which
  refuses `ps`), with `ps`/`lsof` as the fallback; a framework Python (process name `Python`) running a check is
  recognised as the run's own check; the real-process selftests also run on macOS, and on `ps`/`lsof` with
  `FORMALIZE_PAPER_GUARD_SELFTEST_PROCS=ps`.
- **Fix round K (AUDIT-P5): the K certificate counts more strictly.** A result fails K4 when its proof uses a declared
  literature or missing-theory hypothesis directly (an unreadable record gives "unknown", never "reached"); a
  checklist item applies to a result whose Lean name its text names exactly; "proved assuming …" counts as K1 yes
  (the statement is the paper's); an item whose id is not of the form `C<n>` or `K3-<n>` is kept under that id and
  counted open, with a note (the report's wording changes from "not counted" to "counted open"); a delegated
  reading gives one inferred open item per decision, not one per log line.
- Fixes: the F12 re-approval matcher compares short names again (B1); an ADOPTed docstring fix on an index row is
  re-read by the next diff round (B2); the delivery's coverage note reads the summary as the README does, and
  labels with nested parentheses pair (B3/B16); README footnotes get blank lines and ‡ for the sheet's CHECK (B5); a
  VACUOUS or SKIPPED row's context mention no longer gives another result its status (B6); `open`-style lines after
  a definition: text and a known limitation (B7, code deferred); one rule on mid-run upgrades (B8); a literature
  hypothesis without a valid row gets its own paper-faithfulness item, ending the commit dead end (B17); waves of
  at most 20 subagents, spawn lines read whole (B18/B19); an open question answered under `## Answered` or at
  Checkpoint B reads answered (B20); known issues and no-network runs are said plainly (B23/B24); a KNOWN_FAULTS
  notice under the wrong commit subject is a NOTE, not a tamper stop, and human-stop messages mention auto mode
  (B26); index rows added after the approval begin a re-approval first, pure additions never enter the index (B28);
  `selftest_all.py --only` (B10); lane briefs name the paper and forbid file-system searches (B12); the 4b battery
  ignores closures through the audited declaration (B4).

### In short

- **Index rows labelled Problem or Question are results** (E2E fix 2, M1 of the audit of a real hands-off run;
  narrowed in E2E fix 2c). The index was read through a closed, case-sensitive list of twelve words (Lemma,
  Theorem, ...). The run's "Problem 1.1" and "Problem 6.4" rows were dropped without a warning: they were not
  frozen, not on the sign-off sheet, not reviewed and had no status. The same line reader now also reads Problem
  and Question rows. `project.index_table` is the one reader of the index, for the freeze, the scope, the sheet,
  the index check, the coverage table, the statuses and the README. Every other `|…|…|` line that is not a
  separator or a header is named in one NOTE of the index check, never dropped without a word and never a
  failure. This covers an empty label, a lower-case label, a glossary table and a docstring formula such as
  `|f x - f y| ≤ C * |x - y|`. On 51 past runs' index files and 27 git versions of them (read-only), every row
  the old reader read reads the same. Only the e2e run gains rows (its two Problem rows), and only demedts-codex
  gets the NOTE (Equation 2.1, 4.3). "Problem 6.4" is counted as a numbered result. The prose word list gains
  Problem, Question, Open problem, Open question, Exercise, Algorithm and Axiom; it is used for finding labels
  in records, not for the index. It leaves out Hypothesis, Assumption and Condition on purpose, because records
  use those words for Lean hypotheses. decisions uses it instead of its own drifted copy; signoff's label words
  for defect and vacuous cells are 99d928e's plus Problem and Question (E2E fix 2d). The report's coverage table
  and statuses read the index as 99d928e did (indented rows, any case), plus Problem and Question. In the
  statements bundle, an unresolved name in a Problem or Question row is a NOTE, not a problem.
- **Do not upgrade in the middle of a run** (E2E fix 2c; the skip-and-compare NOTE of fix 2b was removed). A run
  resumed on another version fails the tooling check (integrity) and may show a freeze-check DRIFT, for example
  for an index row the old reader skipped (a Problem or Question row); start the next run on the new version.
- **README "What the checking code found": no plain "faithful" for a result the sheet flags CHECK, and the
  summary's table is paired by its header** (E2E fix 2, M2).
  - A result rated *faithful* by the review records that the approved sign-off sheet flags CHECK (a reading
    choice, a generalization, a partial skip) now carries † and the sheet's reason. Its computed status is not
    changed.
  - The summary's status table is found by its header: a "Status" column and a "Result" column, in any order,
    under any heading. A table with a Status column but no Result column (a stops table) is not taken for it.
    "Lemma 2.2, Proposition 2.3" in a cell is two results.
- **The sign-off sheet no longer says what the state no longer is** (E2E fix 2, M4).
  - Its sentence about the proofs is read from the Lean at the sheet's commit. "`sorry` by design" appears
    only when a `sorry` is there; otherwise the sheet says no proof uses `sorry`.
  - Every sheet says that the texts under each result were written when the round's sheet was made: a word
    such as "open" or "not yet audited" says how things stood then.
  - A re-approval's sheet says, from its approval, whether the re-approval is closed. This is an
    approval-stamp pair, so the reader's hash does not change at the approval.
  - `--prepare-delivery` prints a NOTE for each approved-sheet row that calls a closed re-approval open.
- **A cured stop closes `--cured`, also when the cure leaves an adjudication fault behind; a withdrawal is only
  for a stop opened in error** (E2E fix 2, L1).
  - A self-cure's re-run that prints only `adj-record` faults the stop was not opened for now passes. The next
    adjudication clears those faults, and Phase 0, `--commit-adjudication` and `--deliver` still hold them.
  - A withdrawal of such a stop goes through with a NOTE that `--cured` was the right close (E2E fix 2b).
  - `close --withdrawn` prints a NOTE when the stop's own codes no longer print.
  - RUN.md and stops-and-set-asides.md say so.
- **A logged decision is never reworded** (E2E fix 2, L2). RUN.md's missing-theory text, its failure table, the
  check's message and the cure text invited rewording a logged line in place, which stage5 forbids. All of them
  now say: log the corrected line after it. The check is unchanged (a reworded line is still read).
- **Three surviving mutants killed** (DF14, DF30, DF31). Their delivery scenarios were removed with the
  hand-edit route (approver 2026-10-28), so `tests/delivery.py` no longer reached them. They now run
  `run_record.py`'s selftest (a new check: the run record lists live hand edits and the dismissed reader
  findings) and `readers.py`'s selftest (its existing MISMATCH-refusal check).
- **Fixes after the review of E2E fix 2** (REVIEW-E2E-FIX2; E2E fix 2b).
  - A re-approval's sign-off sheet at a commit with some `sorry` says "some or all of the proofs there are
    `sorry`". It no longer says that every proof is `sorry` by design (L-2).
  - A redo cure whose check passes except for an `adj-record` residue still runs the fresh round's lanecheck. A
    failing lanecheck fails the cure (L-3).
  - The README marks fewer statuses as worded differently (L-5). A summary cell is not marked when it keeps the
    status's words in order, leaves out only filler words ("a", "under", "as") and adds no negation. Example:
    "proved; faithful (recorded as a reading choice)" against "faithful under a reading choice". A `| Paper |
    Status |` summary table is still not paired; that is a missed pairing, never a false mark.
  - E2E fix 2 adds no refusal and no stop (the owner's rule: flags, not hard checks).
    - `close --withdrawn` of a stop whose check passes except for an `adj-record` residue is no longer refused.
      The stop is withdrawn, with a NOTE that `--cured` was the right close. The NOTE is printed, kept in the
      close record and shown in the run record's stop table. The older withdrawal refusals are unchanged: a
      check that passes, a redo or tamper code on the current round, a human stop.
    - A Problem or Question index row (a label word the old reader skipped) gets a NOTE, not a failure, when it
      has a dangling name, cites no declaration, lacks a SKIPPED.md row or cites an undeclared name. Rows of the
      old label words are checked as before.
  - The README no longer says a result is "Not found in the summary's table" when only the label matching failed
    (AUDIT-P3 D1: a label with nested parentheses, "b(G,H) ≥ 51 > 50 = Q(78)", was not matched once the header
    pairing read three-column tables). Such a result is now "Not paired with a row of the summary's table … a row
    may name them in other words" (E2E fix 2e).
  - The fresh-round lanecheck of L-3 also runs when a redo cure's check fails only on left-out (NEVER_STOP)
    faults, as for a residue (E2E fix 2c, a note of REVIEW-E2E-FIX2b).

- **A tool patch's facts no longer wait half an hour for the math gate's floor** (E2E finding #2, a real release
  run: 39 minutes for one patch; design DESIGN-FLOOR). The floor mutants on the math gate (MG2-MG4, MG6-MG8) ran
  the whole `stops.py` and `project.py` selftests (minutes each), and `tool_patch.py`'s own selftest, which a
  real floor runs once per tool-patch mutant, ran them all again inside. Now `stops.py --selftest --floor` and
  `project.py --selftest --floor` run only the gate's controls (`integrity_blocks`, `math_gate` with stand-in
  checks, `--deliver` refusing on the gate; well under a second each; the full selftests run the same
  controls), and `tests/mutant_list.py` judges those six mutants by them (MG3 by `stops.py --floor`, no longer
  `project.py`'s whole selftest). `tool_patch.py`'s M1/M6 scenario runs the real floor on the two mutants it
  checks (TPC2, LA1) only. Same rule as before: a mutant whose pattern is gone, whose floor selftest fails on
  the patched tools unmutated, or which survives, is a hit and needs two approvals; no new stop or refusal; the
  full selftests still run in fact (b). New runs only (the floor is read from the first pin). A new
  `tool_patch.py` selftest scenario checks, with real runs, that a patch weakening the gate (patterns kept) or
  the fast controls makes every MG mutant a hit. The floor is not skipped for patches that touch no floor file:
  the floor's selftests reach nearly the whole apparatus, so that is not provably safe.
- **The math gate's fast floor now tests every involvement level and both modes** (review REVIEW-FLOOR, its
  MEDIUM-1 and LOWs). The reviewer found a patch that made the gate refuse nothing at involvement `involved` and
  passed the fast floor and both full selftests (the gate was tested hands-off only; not new with the fast floor).
  `stops.py --selftest --floor` now runs the gate's controls in dev and release at each of `involved`,
  `statements-only` and `hands-off`, and checks that a failing freeze (`fingerprint.py --check`) refuses;
  `project.py --selftest --floor` checks `--deliver`'s refusal in both modes at every level (a drop in release
  only also passed before). New floor mutant MG9 (that `involved` patch) is in `FLOOR` (new runs). With `--floor`,
  an exception inside the controls prints its traceback, so the floor counts that mutant as crashed (a hit), not
  killed. The full selftests check that they ran the fast controls. A baseline floor hit now names the selftest as
  it ran (e.g. `` `stops.py --selftest --floor` ``). `tool_patch.py`'s fast-floor scenario runs the reviewer's two
  attacks as real floor judgements, and fails, instead of skipping silently, when its anchors drift (it still
  skips, saying so, on a patched apparatus that changed an MG line itself: that is a floor hit already). The C3
  check that `--adjudicator-checks` returns at once now tests that the log has no END line when the start
  returns, not a 1.4 s wall-time bound (a flake under load). Not changed: the delivery-time re-check of the
  tooling (`verify_delivery`, notes only) runs the same floor, so it now re-runs the fast controls, not the whole
  `stops.py`/`project.py` selftests: every applied patch passed the full selftests at prepare (fact (b)).
- **A reviewer's Fail no longer stops the adjudicator at its first step** (E2E fix 1, a real release run). The
  background check of the adjudicator's two read-only checks (`project.py --wait-adjudicator-checks`, batch C3)
  called every coverage roll-up exit other than 0 a crash. But `audit_coverage.py` exits 1 by design after its
  full report when a Fail is outstanding (or a scope drifted), which is exactly what the adjudicator is there to
  decide; the run had to open a tool-bug stop and patch the tool. Each check is now judged by its own documented
  exits (`audit_coverage.finished`, beside the code that prints them): coverage exit 0, or 1 after its summary
  line with findings, is a finished roll-up, and the wait reports what it found; a traceback, a missing summary
  line, a signal, exit 2, any other code, or a summary that disagrees with the exit code is still a crash.
  Phase 0 keeps its rule (GREEN 0, RED 1, a verdict line required); its own crash line is now read too.
  `AUDIT_PROTOCOL.md` step A says so.
- **A timed-out Lean comparison no longer leaves Lean running, and is no longer remembered as a refusal**
  (REREVIEW-M7 NEW-1, NEW-2). The comment-only check's Lean calls (compile, `olean_parts`, the O1 diagnostic)
  run in a process group of their own, and a timeout kills the whole group: `lake env` starts `lean` as a
  child, which before kept running beside the next comparison (memory on a small host). O1 failing, timing out
  or running out of budget is no longer cached as a refusal (only definite results are), so a docstring change
  refused once on a busy host is compared again next time; a refusal of that kind an older cache holds is not
  read back. `phase0.strip_comments`'s remaining divergences on literals are listed in KNOWN_LIMITATIONS (Phase 0
  is in the core: not changed).
- **A change to comments and docstrings only no longer costs a review round when Lean finds only a byte-layout
  difference** (M7, post-paper; design DESIGN-M7 and its review). Before, a commit after the last round whose
  code was unchanged was still refused as comment-only when Lean compiled both versions, found every
  declaration, type, value and attribute the same, but the compiled bytes differed (a long confidential run spent a
  4-lane round on this). Now the source is compared with a stricter lexer that follows Lean's tokenizer; when it
  says the code with comments removed is identical and Lean's only finding is the byte difference, the change is
  comment-only, and the report, the summary's facts, the decisions document, the `NEXT[no-round]` line and
  `RUN_RECORD.md` say "checked on the source" (with Lean's comparison), never "verified mechanically". Lean
  still vetoes: any difference in a declaration, a type or value, an attribute or other extension, a field
  O1 names that identical source cannot produce (imports, universe names, the kind, reducibility hints,
  safety, binder annotations, and the rest), O1 not running, failing or timing out, a version that does not
  compile, a failed build, and Verso docstrings all refuse as before. No new stop.
- **A hole in the comment check, older than M7, is closed** (review of the M7 build, H1). Lean reads the
  character right after an opening `/-` without looking at it, so `/-/- -/` is one closed comment and what
  follows it is code. The tool's comment readers (the comment-only lexer, and `phase0.strip_comments`, which
  the Stage 4 diff-round skip and the `sorry` scan use) read `/-/-` as two nested openers and took the code
  after it, up to a later `-/`, for a comment. A change there could pass as comment-only (on the compiled basis
  when it was in an `example`, before M7 too), and a `sorry` there could go unseen by Phase 0's text scan. No Mathlib file and none of the 36 local run histories contains
  `/-/-`. Both readers now follow Lean.
- **A stop opened in error can be withdrawn** (release mode): `stops.py close --stop S<n> --withdrawn
  "<why, and the route instead>"`. Before, a stop whose check could never pass (for example one bound to a
  set-aside round) blocked every later stop, because only one stop is open at a time (Pisani run, S1). It is
  never allowed for one of the four human stops, it is refused while the stop's check passes or still shows a
  tampered or changed round, it counts as a failed cure, and `RUN_RECORD.md` lists it (and README's delivery
  notes, when its check still fails at delivery).
- **Fixes:** a `--note` stop opened without `--round` or `--check` no longer crashes; the setup step that
  writes the run log creates the rounds directory if it is missing; the sign-off check accepts blind-reading
  keys written as `## <heading>`; an encoding-error line in `PAPER_DEFECTS.md` is judged by the F10 item of the
  refutation it names; the sign-off sheet and its messages count numbered results, other rows and definitions
  apart instead of calling every row a "result".
- **A paper that may not be redistributed is left out of the push** (batch C): Stage 5 prints a second
  one-command push that builds the tree without the paper's files, refuses a mistyped path or an unchanged
  tree, and pushes a commit with no parent to a new branch. Both push commands add a line to
  `deliverables/README.md` that maps the Lean commit the documents cite to the pushed commit. Fix round 1:
  a later push whose parent's history holds the paper, or a tree missing a Lean or build file, is refused;
  the commands work from any directory, add the line once, and keep their index in `.git`; a push the
  permission layer denies is handed to the person, never a stop.
- **Long checks run in the background** (Phase 0, the selftests, the approval, a tool patch's facts), so
  a slow machine no longer cuts them after about 20 minutes. Before an adjudicator starts, the operator runs
  its Phase 0 and coverage checks in the background and the adjudicator reads their log. No new stop. Fix
  round 1: two plain commands, `project.py --adjudicator-checks --round <R>` and
  `project.py --wait-adjudicator-checks --round <R>`, which the permission rules already allow; the wait
  accepts the log only if both HEADs are unchanged from start to end, the mode matches TARGET.json and no
  check crashed; two Phase 0 runs never run at once.
- **Wording:** copy hashes, tokens and agent ids from the output, never retype them; the blind reader knows
  that an index row titled "Definition ..." is a row; a stronger reading that the paper's own proof proves
  may be recommended; each reading choice nobody answered becomes a question to the authors in SUMMARY;
  INSTALL warns about a stray `ANTHROPIC_API_KEY`.
- **Tool patches touching code the core relies on are flagged** for the reviewer (FACTS `core_reachable`),
  never refused.
- **A row the adjudicator already decided never starts another review round** (batch B): it still reads "not
  established", a delivery note names it, and a declined ADOPT is a decisions item; the reading a QUESTION's
  answer takes is read from a `[Lean: (a); recommended: (b)]` token or the older wordings, and a negated
  answer names no reading; the comment-only refusal names the first differing field.
- **The delivered README has a section the checking program writes** (batch E, forgery review 2026-11):
  "What the checking code found", before section A, gives each result's status as computed from the review
  records (a † where the summary words it differently, with the agent's reason from `JUDGEMENT.md`'s new
  `## Status wording`), the proof checks, the run settings fixed at the start, whether the checking software
  changed since the run started, the answers recorded as yours at every level, the reviews on record, and what
  the checks noticed, counted by kind. Every note is also in the delivered `RUN_RECORD.md`, word for word, and
  `--check-delivered` now checks every delivered file, README.md included. Nothing new refuses or waits.
- **The math gate never skips a real `sorry` or a non-standard axiom** through a core-fault close; **the
  involvement level, mode and ownership version are the first pin's** even after a config or pin edit; **a merge
  commit's changes to records are judged** like any other commit's.

### Details (batch C, post-paper; design DESIGN-C and its review)

- **C1** `run/stage0-intake.md`: an answer (1b, 1c or 7) that the paper's text may not be redistributed is
  logged as an intake constraint and named at Checkpoint A. `run/stage5-delivery.md`: the push comes after
  the last `--deliver`, from the project root, and both commands are printed in full (review C1-2). Without
  the paper: a temporary index in the operator's scratch directory, `git rm -r --cached` **without**
  `--ignore-unmatch`, so a mistyped path fails (review C1-1), and `test "$T" != HEAD^{tree}`. The first such
  push always has no parent and goes to a new branch (review C1-3; on an existing branch it is refused as
  not a fast-forward, never forced). A full-history request for such a paper pushes the clean commit, said
  in the completion message. The Lean docstrings and the audit record (6d) still quote the paper; the
  completion message says so (review C1-5). A parent git no longer has: `git fetch` restores it (C1-6).
  `run/codex.md`: the push before the copy, an absolute scratch path, run from the project root (C1-4).
  Tested in a toy repository with a local bare remote (right path, mistyped, empty and untracked paths,
  a base that holds the paper, a parentless push onto an existing branch, a later push with a parent, an
  unknown parent, a full-history push, the redistributable command): 23 checks.
- **C2** The push command appends `Pushed to <remote>, branch <b>, as commit <C>: the tree of Lean HEAD <H>`
  to `deliverables/README.md` (via `tee`, which also prints it; the operator copies it into `RUN_LOG.md`). `--check-delivered` reads
  only the fingerprint lines, so nothing it checks changes. After a later `--deliver`, the line is copied
  back from `RUN_LOG.md` (review C2-2). SUMMARY and REPORT cite the last commit that changed Lean files;
  the text says the pushed tree holds those files (C2-1). The copy to another destination follows the push.
- **C3** `RUN.md` rule 9 is now "Long commands in the background; tag every monitor you start": a command
  that can run past 10 minutes runs plainly with `run_in_background` (Codex: one long call); nothing in
  either repository changes until it finishes (review C3-2; the harness gives each run a fresh output file).
  The adjudicator's checks (review C3-1, no new stop): the operator starts `phase0.py --readonly` and
  `audit_coverage.py` in the background into `.formalization-work/adjudicator-<R>.log`, which starts with
  the Lean and audits HEADs and ends with `END` (Stage 2 step 4, Stage 4 steps 4 and 5). The adjudicator
  checks both HEADs, waits for `END` with a tagged wait, and never ends its turn before then (C3-3). With no
  log, a stale one, or under Codex it runs the same command itself, or the two plain commands if a
  permission prompt refuses it. Lane rule 9 keeps the ban on background processes: a probe still cut at
  the longest timeout is NotDoneYet. The guarded tool-patch reviewer prompt gets the same background
  sentence (a maintainer change; a tool patch still cannot touch it). `lanecheck.stray_loops` docstring only.
  Not run: the design's 15-minute subagent wait test (the operator-log design does not depend on it).
- **C4** `RUN.md` rule 11 and `run/spawn-and-seal.md`: copy every hash, token, digest and agent id from the
  output that printed it.
- **C5** Informalizer prompt: the sections above `# Definitions these statements use` are `rows`, even one
  whose heading begins "Definition"; those below are `definitions`.
- **C7** Adjudicator rule C: the weaker reading, unless the paper's own proof proves the stronger or a later
  proof needs it; cite the proof's lines; for an approved statement, recommending the stronger reading is a
  statement change. Lane rule 6: a `question` says which reading the paper's proof proves; lane C's
  `too-strong` pattern sends such a reading to Ambiguous. The design's change to RUN.md's conservative
  rule is **not** made (review C7-1): the operator alone never takes the stronger reading.
- **C8** A reading choice whose QUESTION no person answered (DECISIONS.md says who decided; review C8-1)
  is asked of the authors: its one SUMMARY line is phrased as a short question (review C8-2: no second
  line). The DECISIONS delivery reviewer checks it.
- **C9** `INSTALL.md`: `ANTHROPIC_API_KEY` in the shell bills the API account; how to check with `/status`.
- **D2** `tool_patch.core_reachable` (FACTS key `core_reachable`, always present): the patch's hunks mapped
  to top-level Python spans (decorators included) of the code the core relies on. That code is
  `core_reachable_map`, derived one hop from the first pin's core files (every `module.name` a core file
  reads, and the whole of every script a core file runs as `{PY} audits/<x>.py`: make_report, unused_args,
  dependencies, tree_state), plus `CORE_REACHABLE` by hand (stops.py and lane_auth.py whole; named functions
  and assignments of project, decisions, signoff and dependencies, including `project.RELEASE` and `CAUSES`)
  (review D2-1). Each entry says why it is listed; "<module level>" and "<unparsed>" cover the rest. The
  output is sorted, and any exception gives "<unparsed>" (D2-2). It never refuses and never changes
  `required_approvals`. Reviewer question 12; the RUN_RECORD and `prepare` lines show it.
- Tests: `tool_patch.py --selftest` (four D2 cases), mutants `ppC-D2a`-`ppC-D2c`.

### Details (batch C, fix round 1; ATTACK-C, COMPAT-C)

- **C3** (COMPAT-C H1, ATTACK-C M1, M2, L2, L4, L5) `project.py --adjudicator-checks --round <R> [--own]
  [--foreground]` starts Phase 0 read-only (`--statements` taken from the round's TARGET.json `_meta.kind`,
  not typed) and `audit_coverage.py <rounds_dir>` in a detached worker, and returns once the worker holds
  the lock `.formalization-work/adjudicator-checks.lock` and the new log's header is in place (written
  to a temporary file and renamed, so an adjudicator never reads an older log). The log records the round,
  the run (operator or own), both HEADs, the kind, the exact commands, each exit code, both HEADs again,
  then `END`; a worker crash is recorded with its own exit line. A second start while a run holds the lock
  is refused (any round): two Phase 0 runs of this mechanism never run at once. `--wait-adjudicator-checks
  --round <R> [--own] [--timeout S]` (default 540 s) waits for `END`, then verifies: exit 0 current, 1 stale
  (no log; another round's log; no `END` and no live writer; a HEAD or AUDITS line, at the start or the
  end, that is not current; a KIND, command or Phase 0 `mode:` line that differs from TARGET.json; no
  `PHASE 0: GREEN|RED` verdict that matches the exit code; a coverage exit other than 0), 3 still running.
  The adjudicator's own run (`--own`) writes `adjudicator-<R>-own.log`. Both commands are plain `python3
  audits/project.py ...` forms: no `bash -c`, no `until tail` loop, no `git -C audits rev-parse`.
  `AUDIT_PROTOCOL.md` step 4, `run/stage4-rounds.md` steps 4 and 5, `run/stage2-statements.md` step 4, RUN.md
  rule 9. The adjudicator reads no finding until it has the result (COMPAT-C M2: "read the verdicts
  meanwhile" is dropped); a second crash of its own run is a STOP. Under Codex the adjudicator runs `--own
  --foreground` in one long call. A test hook (`FORMALIZE_ADJ_CHECKS_TEST`) is honoured only by a
  `--selftest` process, and a real verify expects the real commands.
- **C1** (ATTACK-C M3, L1, L2, L3; COMPAT-C M1, L1, L3) The no-paper push takes `P=` (empty for the first
  push) and refuses unless `git rev-list -1 "$P" -- <paper paths>` is empty, so a wrong parent cannot carry
  the paper through history; it also refuses a tree without a Lean or build file HEAD has (`.` or the Lean
  directory given as the paper's path). Both commands `cd` to the repository's top level first, append
  the `Pushed to` line only if it is not there yet, and the no-paper one keeps its temporary index in
  `.git/formalize-push.index` (it still works when the person runs it later under Codex). A push the
  permission prompt or classifier denies is put in the completion message for the person, never a stop.
  The check after a push compares with the Lean HEAD named in the line, not the current HEAD.
- **C8** (COMPAT-C L4) On a full SUMMARY page reading choices are reduced to a count only with the most
  important kinds (`make_report.COLLAPSE_EVEN`), not among the first.
- **D2** (ATTACK-C L10) A data file that a whole-file entry names (`dependencies_tail.lean`, read by
  `dependencies.py`) is listed whole. The code comment names what the flag still misses: helpers, a module
  two hops away, an import-time patch from a module outside the map.
- Tests: `project.py --selftest` (12 C3 cases, scripts stubbed, no Lean, including the allow-rule check of
  every documented command); `tool_patch.py --selftest` (the data-file hop); mutants `ppC1-C3a`-`ppC1-C3g`,
  `ppC1-D2d`; the push commands, extracted verbatim, in toy repositories with local bare remotes (20 checks).

### Details (batch A, post-paper; design DESIGN-A and its review)

- **A1** `project.closer(code, None)` raised a TypeError, so `stops.py open --note --cause <code>` with no
  `--check` and no `--round`, for a code whose own closer has no `{R}` (`drift`, `tree-changed`, ...),
  crashed (Codex De Medts run). `closer` now reads a None round as `"<R>"`; no output changes.
- **A2** `stops.py close --withdrawn` (release only; `_withdrawn_doc`). Refused (a refusal of the command,
  never a stop, each naming the route) in dev mode, for a human stop of release, for a stop classified
  `interference`, while a set-aside names the stop, while a tool patch for it is open (or applied, when the
  stop has no check), while a core-fault request exists for it, past the cure budget unless classified
  `other` after those failures, while its check passes, and without text. The tally counts a withdrawal like
  a failed cure (on the stop and its keys), so withdraw/re-open never resets a budget; `trail_problems`
  checks the record and the budget rule. It is process record: `RUN_RECORD.md` lists it under "Stops
  cleared without you"; the summary page (`make_report.page_stops`) and DECISIONS.md's box leave it out (it
  is no delegated decision). The math gate notes a withdrawn stop's check that fails at delivery (a note,
  never a refusal). Refused before the config exists. Not done: a refusal tied to an integrity
  acknowledgment request (review LOW), because those records do not name a stop.
- **A3a** `signoff.informal_key`: INFORMAL.json keys written `## <heading>` (b1v and b2v runs, each a
  stop and a tool patch) are read as the heading. The regex needs whitespace after the `#`s (`##Lemma 1.2`
  stays "no entry"); the duplicate check runs on the normalized keys; SIGNOFF.json keys are not normalized
  (that record is not write-once). The informalizer prompt is unchanged here.
- **A3b** `make_report.f10_verdict_for`: an encoding-error line is judged by the F10 item the cited round
  scheduled for the refutation it names, not by the record's last F10 item (b2v run, round e5f2d954d5f).
  **Difference from the run's reviewed patch (b2v TP1 A2), disclosed:** b2v fell back to the record's last
  F10 item whenever the cited round scheduled no item for the name. Here that fallback is kept only for a
  round with no `_meta.f10` key at all (from before F10 scheduling); a round with a schedule, even an empty
  one (`f10: {}`), but no item for the name, or an unreadable TARGET.json, gives "not judged", i.e.
  PENDING[adj-record] for the next adjudicator, never a stop. A correct line cites the round that scheduled
  and decided the item, so this rejects only citations of the wrong record.
- **A4** `project.log_append` creates a missing rounds directory when it lies under the project's
  `audits/` (Stage 1 step 5, `--intake-move`, failed in four runs); a missing one outside `audits/` is
  refused and nothing is written.
- **C6** `signoff.row_count` reuses `make_report.count_text`: the sheet header and `signoff.py
  bundle`/`check` say "161 index rows (67 numbered results plus ...)" and "N Lean definitions in the
  bundle"; `approve` says "N sheet row(s) approved"; the facts draft's trust row says "N of M statements on
  the sign-off sheet approved". An old sheet re-rendered takes its restatement split from today's index.
- **A6** (tool patches of PORTING.md and project_template.json): no change.
- Tests: selftest cases in `project.py`, `stops.py`, `signoff.py`, `make_report.py` and
  `tests/delivery.py`; mutants `ppA-*`; the stale mutants rsc-1i, FF3a and RUNREC6 (their text no longer
  occurred) brought up to date.

### Details (batch A, fix round 1: attack review ATTACK-A, compatibility review COMPAT-A)

- **A2, tampered rounds (attack HIGH-1).** `close --withdrawn` is refused while the re-run check still
  prints one of the stop's own codes of release kind `redo` or of class `tamper` (`seal-mismatch`,
  `evidence-after-seal`, `scope-changed`, `head-moved`, ...) on the current state; the refusal names the route
  (set the round aside, `set-aside R --stop S<n>`, redo it, `close --cured` on the fresh round; or the restore
  cure). A check bound to a round that is no longer current (set aside or superseded) does not block, so the
  Pisani case is unchanged. `trail_problems` flags a withdrawal whose recorded re-run shows such a code.
  `stops.withdraw_blockers`.
- **A2, human codes (attack LOW-1).** A withdrawal is refused while the re-run check prints any code of the
  four human stops, whatever cause the stop was opened under; the human closes it. RUN.md says a withdrawal
  never re-labels a fault.
- **A2, still failing at delivery (attack MEDIUM-1).** When a withdrawn stop's check (not bound to an old round)
  still fails at delivery, README's delivery notes (section D) say so in plain words. A note, never a refusal.
- **A2, smaller fixes (compat L1, L2, L4).** RUN_RECORD's "Stops cleared without you" intro adds one sentence on
  withdrawals, only when the table has one; the "what was done" cell of a withdrawn row no longer starts inside
  the parenthesis; the close tests STOP.json's mode as the trail does. RUN.md and
  `run/stops-and-set-asides.md` now say that a withdrawal past the budget needs `classify --as other` first.
- **A3a (attack LOW-4, compat L6).** `signoff.check` looks index labels and definition names up through
  `informal_key` as well, so both sides are read the same way. The sign-off writer's prompt
  (AUDIT_PROTOCOL.md) asks for the heading's text without its `## `. SIGNOFF.json keys are still not
  normalized.
- **A4 (compat L5).** `log_append` creates a missing rounds directory only when it is `audits/<name>`, the
  form `project_template.json` gives. A misspelt `rounds_dir` under `audits/` is refused as before, and no new
  empty log is written.
- Tests: `stops.py`, `signoff.py`, `project.py` and `tests/delivery.py` selftest cases; mutants `ppA-F1a`-`j`;
  the mutants R3c-3b, b1b-2a and c2-39 (dead since batch A) and G4, G6, G7 (moved by the LOW-4 change)
  retargeted.

### Details (batch A, fix round 2: re-review REREVIEW-A)

- **A2, codes that appear later (R-M1).** The withdrawal refusal no longer looks only at the stop's own codes:
  any code of release kind `redo` or class `tamper` that the re-run prints on a round that is still current
  blocks it, including one first printed after the stop was opened (a stop opened on `unsealed`, whose check
  now prints `seal-mismatch`). The trail check follows. The Pisani case is unchanged (its check is bound to an
  old round).
- **A2, the route named (R-L2).** The refusal names `set-aside R --stop S<n>` only when STOP.json names that
  round (otherwise `set-aside R` without `--stop`, which `set_aside` accepts); for an adjudicated round or a
  check bound to no round it names the cure the check's cause table prints, never a set-aside.
- **Docs (R-L3).** RUN.md and `run/stops-and-set-asides.md` name restoring as well as the redo.
- Tests: a `stops.py` selftest case; mutants `ppA-F2a`-`c`; `ppA-F1a` retargeted.
- Residual (R-L1, accepted): the old-round exemption is read when the withdrawal runs, so a round superseded
  by a newer one (not set aside) exempts its check; if the newer round is later set aside, the trail flags the
  withdrawal (fail-closed). Not changed.

### Details (batch B, post-paper; design DESIGN-B and its review): no review round for rows already decided

- **A decided row never scopes a round** (MAINTAINING L5). A Fail or Ambiguous whose round's adjudicator
  already decided it (ADOPT, DEFER, a QUESTION since answered; every item of the verdict, no re-vote open; a
  `## Hypotheses` row saying `no`) is routed `decided`: its result still reads "not established: ... decision:
  X", but `make_report.pending_adjudication` no longer lists it, so `scope.py` prints `NEXT[no-round]` (or
  `NEXT[stage5]` after an empty diff scope) instead of starting a 60-80-agent round that could only re-raise
  it. A Definition row the result uses follows the same rule (an unanswered QUESTION there is the human's).
  A verdict with no decision row, an adjudicator-record fault, a `leave ... unproved` line or route change
  after the last adjudication, and any Lean change that is not comment-only still scope a round.
- **What the extra round used to carry is kept**: an ADOPT the author did not carry out (OUTCOMES.md "not
  implemented — disagree" / "could not be implemented") is a `declined:` item of `decisions.py --write` (a
  Checkpoint C item under `involved`); delivery notes name the results not established by decided rows, an
  ADOPT with no OUTCOMES row or "implemented" with no Lean commit behind it, and an answer that took another
  reading than the Lean's. Notes never refuse.
- **The reading decision is read reliably.** The adjudicator ends a QUESTION row with
  `[Lean: (a); recommended: (b)]`; an answer names `take reading (x)`. Older records are read from both cells
  of the row, with the wordings real runs used ("The Lean (`x`, File.lean:3) takes reading A"); a bare label
  must end its clause, so "takes A arbitrary" is no label. An answered QUESTION that kept the Lean's reading
  reads "faithful under reading (x)", also for the results using a Definition settled that way (A5b).
- **Comment-only check: a sharper refusal.** When the compiled bytes differ while every declaration's hash
  agrees, the refusal names the first differing field (`olean_diff.lean`, a diagnostic; it never changes the
  outcome, and when it cannot run the message is as before). The diagnostic is **untested on Lean**: no Lean
  control has run it yet (one is pending), so it may never fire; it has 60 seconds per refusal in all.

### Details (M7, post-paper; design DESIGN-M7 and its review DESIGN-M7-REVIEW)

- **The lexer** (`project.py` `code_only`, `lexer_ambiguous`, same names): `/--` and `/-!` bodies start after
  the third character, so `/--/` no longer closes at once; every comment is blanked to its width, so each code
  character keeps its column (a widened mid-line comment before code is now a code change: review L3); Lean's
  identifier tables (`isIdFirst`/`isIdRest`, v4.35.0) decide whether a `'` is a prime, and a `'` after a symbol
  or a non-ASCII character is read three ways, which must agree (review M4). Ambiguous, so NOT comment-only:
  `--`/`/-` right after code, `/--/`, a string that reads differently as an interpolated one (now across
  lines), a raw string anywhere in code (also after `!`, `λ` or a digit), a `«…»` name holding a marker, an
  unterminated comment, string or name (review L2); a project declaring a token that holds `--` or `/-` turns
  the bracket exemption off (review L1). Replayed on the 551 edits of project Lean files in 34 local runs: the
  verdicts are unchanged.
- **Kinds** (`LeanReason`): each Lean reason is `semantic`, `layout` (only the constants' bytes differ, with no
  O1 field or a benign one: sharing, binder names) or `not-run`; a reason without a kind is `semantic`.
  `comment_only_detail` gives the basis (`compiled` or `source`); `comment_only_since` keeps its 2-tuple.
  `doc.verso` in a project Lean file or the lakefile turns the source basis off (review L4). O1 now decides in
  one direction: a field identical source cannot produce makes the reason `semantic` (review M1); this replaces
  "it never changes the outcome" of batch B. `olean_diff.lean` tells binder names from binder annotations
  (UNVERIFIED-LEAN: no Lean has run it; the `--selftest --lean` controls do).
- **Fix round 1 (review of the M7 build).** H1 above (`_co_block_end`, `phase0.strip_comments`). H2: O1 fails
  closed: with no O1 answer (it failed, timed out, had no budget left, or printed no complete answer, now
  `DIFF` lines followed by `END <count>`) the bytes-only reason is `not-run`, a review round, never a stop.
  `olean_diff.lean` compares every constant (no stop at the first difference), reports binder names and
  annotations of a type and of a value independently, compares the kind, the module flag, imports with their
  flags, recursor rules and every other field (`ConstantInfo`'s `==`: hints, safety, the mutual block,
  inductive, constructor and recursor data), and prints the sharing text only when nothing differs; the reason
  is `layout` only when every finding is benign (UNVERIFIED-LEAN, still). M1: every lexer helper,
  `OLEAN_DIFF*`, `OLEAN_PARTS` and `olean_diff.lean` are in CORE_REACHABLE (flagged only). L1: a string's
  newline sentinel is escaped, so a raw NUL no longer reads as a newline. L2: two or more uncertain `'` are
  read in every mixed combination (at most 16 readings; past that, ambiguous). L4: no `lake` on PATH is
  `not-run`, not a crash. L5: a refusal from the comparison of the compiled parts is cached (read back as a
  refusal); a compile or build failure is not.
- A bytes-only result is cached (`comment-only-cache.json`, its own key, which includes `olean_diff.lean`), and
  its reasons are judged again when read. The deciding names are in `tool_patch.CORE_REACHABLE`: a tool patch
  touching them is flagged to its reviewer, never refused; project.py stays out of CORE.

### Details (batch B, fix round 1: attack review ATTACK-B, compatibility review COMPAT-B)

- **A negated or questioning answer keeps nothing.** "do not keep the Lean's reading", "Keep the Lean's
  reading? No: ...", "not reading (a)" and a row saying "Neither the paper nor the Lean takes (a)" name no
  reading, so the result reads "not established" (before, the first two read "faithful under reading").
- **Which label the Lean takes is read more strictly.** A bare label after "takes" ("takes A") counts only when
  the row names it as a reading ("Reading A: ..."); "takes 1, i.e.", "takes C," are objects. A row whose
  `[Lean: ...]` token names one reading while its text says the Lean takes another settles nothing, and a
  delivery note names the row.
- **Every outstanding verdict of the round must be decided.** A decided Fail on one part of a result no
  longer hides an undecided Ambiguous on another part of it (or another item of the same round): the result
  then still scopes a round. A row on part (a) no longer decides part (b).
- **Declined ADOPTs in any wording reach the human.** Every OUTCOMES.md outcome that does not start with
  "implemented" ("declined — disagree", "deferred (disagree)", "done"), and an ADOPT with no OUTCOMES.md row,
  is a `declined:` decisions item. An item a later round passed is not listed; its anchor no longer moves when
  the note is reworded.
- **Notes.** An answered QUESTION with no Lean commit after its round is a delivery note (did the answer ask
  for a change?). `make_report.py --check --delivery` prints the decided rows' notes as `NOTE[deliver]` and
  no longer says "NOT deliverable" because of them.
- `olean_diff.lean` compares imports by module name (`.module`).
- TRADEOFFS.md T37: what no longer re-checks an "implemented" claim or a DEFER.

### Details (batch E, post-paper; design DESIGN-E2 and its review DESIGN-E2-REVIEW)

- **Fix 2 (F1, F8, F11): the code-written README section.** `project.readme_checked` and `status_block`. The
  mark is mechanical: a result the code rates exactly *faithful* is never marked; another is marked when the
  summary's cell does not contain the code status's first part (up to its first `;` or ` (`, review L1), or the
  summary does not list it. Labels are normalised the same way on both sides (`**` removed; a trailing
  parenthetical removed only when it contains a space, so "Lemma 3.2 (c)" and "Claim (7)" stay; exact match
  first), a cell is split only at `; ` outside parentheses, and "Lemmas 2.1, 2.2 and 3.4" is three results
  (review M1); the summary's table is the one under `## Results`, else the first whose header starts
  `| Status` (L3). A missing reason is one `[status-wording]` note. The software block diffs the tooling
  against the first pin's `audits_commit`; only a `tool-patch TP<k> apply` commit of an applied patch with no
  `FAIL[tool-patch] TP<k>` note counts as reviewed. The approval line under involved and statements-only points
  to the approval in the list (review M2: it named the Lean commit as an audit commit). The withdrawn-stop line
  moved from README D to "Proof checks"; README D's review sentence now says the agent saved the reviews.
  README D fingerprints every delivered file but README.md, whose sha256 and length go in the RUN_LOG
  `## Delivery` line with the note codes; `--check-delivered` reads the last such committed line, and only
  stage5's `Pushed to` lines may follow the delivered README. SUMMARY's facts draft carries a pointer line to
  the section (a SUMMARY without it is a note); stage5 asks for the `## Status wording` lines.
- **Fix 3 (F4).** `project.intake_terms` (the first committed pin's config, cached once found), used by
  `involvement`, `mode` and `terms_differ`; `integrity.pinned_version` takes the first pin's `ownership` when the
  key is present (else the working pin, as before; `KeyError` caught); the three `(cfg or {}).get("mode")`
  bypasses in integrity.py go through `project.mode`. A --selftest process keeps reading the working values
  unless it opts in (`_terms_from_pin`, `project._TERMS_FROM_PIN`).
- **Fix 4 (F3).** `stops.work_lines`: a kernel "N declarations reach sorryAx" while no leave line or
  re-approval is active, a "X carries [" line, and a token-scan `sorry` unless the same output's axiom sweep is
  clean are never a core fault's: `core_attribution` makes every line foreign and `core_covered` returns False.
  "swept only", a goal in a leave line, drift, crashes and Lean API errors stay coverable.
- **Fix 5 (F5).** `integrity.history` walks `git log -m --first-parent`; `changed_files` diffs a merge against its
  first parent.
- **Fix 6.** maintainer-notes, AUDIT_PROTOCOL's limitations text, MAINTAINING (F2, R0, S3, D1, the withdrawal
  refusal), KNOWN_LIMITATIONS and the tool_patch.py comment on RAISED lines say what is now true; maintainer-notes
  lists what remains open (F2/fix 1, F6, F7, F9, F10, fix 4's residuals, merges, fix 7).
- **Floor mutants** (forgery review rec. 6): the math gate's MG2-MG4 (10-28) and the new MG6-MG8 are in `FLOOR`,
  so a tool patch hitting one needs two approvals. Each runs its selftest at every tool patch's FACTS: 8 more
  selftest runs per FACTS run (a `project.py` baseline with MG2 and MG3, a `stops.py` baseline with MG4 and
  MG6-MG8), each FACTS run at prepare and again in each reviewer.
- **INT-REVIEW leftovers.** The tool-patch reviewer's FACTS command is `python3 audits/tool_patch.py facts ...`,
  which the project allow rules cover (LOW-4; `claude_settings.py --selftest` now checks every documented
  `python3 audits/<x>.py` command and that one); a declined-ADOPT decisions item no longer claims its result reads
  "not established" (LOW-1); the stale "land C7 with B1" build note is gone (LOW-2).
- Tests: unit controls in `stops.py` (including direct `integrity_blocks` controls), `integrity.py` and
  `project.py --selftest`; `tests/delivery.py` `checked_section` (F1 variants 1 and 1b, involved receipts, an honest
  reason, edits after delivery) and `forgery_gate` (F3, F4, F5 regressions); mutants `E2-*`, `E3-*`, `E4-*`,
  `E5-1`, `E5-3`, `E-L4`, `MG6`-`MG8` (no "drop -m" mutant: on git >= 2.31 it is equivalent); mutants `scr-5c` and
  `pa-32` retargeted. `tests/mutants.py` copies `skills/` into its scratch copies: without the bundled licence
  texts `project.py`'s selftest baseline failed and no `project.py` mutant was judged.
- **Fix round E1** (attack review ATTACK-E, compatibility review COMPAT-E). Nothing new refuses, stops or waits.
  - A command is a selftest only when it IS `--selftest`: `project.py --deliver --selftest` no longer reads the
    working config's level and mode or the test tier's variables (H1).
  - The README section's status comparison drops SUMMARY.md's HTML comments, compares every row that names a
    result, and no longer says "in the same words": it says the first words were found and asks the reader to
    compare (H2). The summary's cell and the agent's reason are made inert (no raw HTML or code spans). A summary
    label with an extra trailing parenthetical ("Definition 2.1 (H)") pairs; results not found in the summary's
    table have their own heading; a Status wording label containing ": " finds its reason.
  - `--check-delivered` flags a README fingerprint that a later RUN_LOG.md commit rewrote or removed, says "not
    verified" (never ok) for a README no delivery line fingerprints, and accepts a `Pushed to` line only in its
    generated form (M1).
  - The pin check compares the raw working level and mode again, so FAIL[pin], FAIL[config], the re-pin refusal
    and the tool-patch link check fire in real runs as before batch E (COMPAT M1).
  - "Proof checks" names the declarations a logged leave line lets through the `sorry` check (COMPAT M2);
    "as fixed when the run started" only when the first pin records the level; tooling changed and reverted is
    named, not "Unchanged"; the tool-patch reviewer runs the FACTS command from the project's top-level
    directory; one note kind reworded; `project.SUMMARY_POINTER` renamed `CHECKED_POINTER`.
  - Mutants `E1-*` and `I28`, `TM3` retargeted.
- **Polish round** (re-review REREVIEW-E, all LOW). Nothing new refuses, stops or waits.
  - The no-paper push command writes the paper paths in backticks, and `--check-delivered` accepts any path
    there except one with a backtick or a newline (`Smith+Jones (2024).pdf` is fine); the older unquoted form
    is still accepted (L2).
  - For a RUN_LOG.md delivery line edited or removed after delivery, `--check-delivered` no longer says only
    "deliver again", which cannot clear it: it says to restore the line or leave it (L3).
  - The summary coverage check ignores results rows inside HTML comments, as the README section does;
    `tests/TIERS.md` states the `--selftest` rule as MAINTAINING A3 does (L4). KNOWN_LIMITATIONS says when a
    summary row with extra words in its label is not compared (L1).
  - Surviving mutants killed: `A5-1` (a `result_status.py` case where the label is named as a reading but
    does not end its clause) and `DF13` (now run by `integrity.py`'s selftest, since `tests/delivery.py` no
    longer builds hand edits). New mutants `PL-L2`, `PL-L3`, `PL-L4`.

## 0.3.1

### In short

- **Delivery redesign.** Once the mathematics is verified, delivery is never refused except by the
  math gate (Phase 0, the frozen statements, the integrity of the proof-validity core, and no Lean
  change after the last audited round). The agent writes `SUMMARY.md` and `REPORT.md` from the run's
  records and the Lean; four fresh reviewers advise, the agent judges each finding in
  `JUDGEMENT.md`, then renders the PDFs. Problems that used to block delivery are now notes.
- **Memory setting at intake (question 7).** Say how much RAM the computer has: on 16 GB the run
  keeps at most 3 agents at a time, each compiling one Lean file at a time; on 8 GB you can ask for
  one agent at a time.
- **Licence at setup.** The intake asks which licence to use when the formalization is pushed
  (default Apache-2.0), and the setup adds it.
- **Clean push.** A push of the Lean branch can be made as one clean commit, with a guarded
  one-command push.
- **Fixes:** the sign-off guard no longer refuses legitimate records.
- **Documentation:** "Who it is for"; installation by asking Claude Code or Codex to follow
  `INSTALL.md`, with a quick check (seconds) instead of the full self-tests, which every run
  performs itself; Codex status (two runs on Linux, including a real paper; one on macOS);
  macOS support on the separate `macos` branch (less tested).

## 0.3.0 (release date: the date of the v0.3.0 tag)

### In short

- **Release and dev installations.** By default (release), a run stops for you only for four
  reasons: a goal result that looks false or unprovable, an outward action you did not allow, something
  only you can fix, and a genuine ambiguity in the paper's meaning. Faults in the run's own
  bookkeeping are fixed by the agent and disclosed in `RUN_RECORD.md`. `install.sh --dev` keeps
  every stop, for people changing the scripts.
- **A one-page `SUMMARY.pdf`**, delivered first, with the status of every numbered result. The other
  documents are its appendices.
- **The PDFs are rendered and checked by AI agents** from the audited markdown, which is always
  delivered beside them and is the authoritative text.
- **`RUN_RECORD.md`**: how the run went (stops, fixes, disclosed tool problems), apart from the
  report.
- **`DECISIONS.md` has one section per matter**, and an answered matter is not asked again.
- **Advisory notes**: a review of the paper's citations (`CITATIONS.md`) and a check of the
  summary's statuses by a fresh agent. Neither ever stops a run.
- **Reviewed tool patches (release mode).** When one of the run's own checks crashes or misjudges a
  case, the agent may patch it, with a regression test and an independent agent's review, and the
  patch is disclosed.
- **Codex (experimental):** generated roles for the tool-patch reviewer and the summary check. Not
  tested end to end on this version.

The entries below are the maintainers' detailed build log. They refer to internal test runs
("trial #n", "mini", "bench", "conf") and design notes ("U2", "B1"…"B13", "G", "F") that are not
published.

0.3.0 was tested end to end on the exact release code (Claude Code): a hands-off run on a short
synthetic test paper with planted errors delivered in about 4 h 15 min with no human input after
setup (2026-10-26), and a second hands-off run on a benchmark paper delivered with no stops
(2026-10-27). The changes below follow a live hands-off run of a 0.3.0-dev build (2026-10-19), the
independent audit of that run and a whole-repository simplification audit. The
principle is to remove the causes of stops instead of adding machinery to cure them. Every
decision, clearance, set-aside and waiver is still disclosed in the report. A stall-resolver agent
was added during 0.3.0-dev and removed again before release (see "Removed").

### Delivery: only the math gate refuses; the agent writes the documents (approver, 2026-10-28)
- After the mathematics is verified, delivery never stops and is never refused except by the math gate: Phase 0
  read-only GREEN, the freeze (`fingerprint.py --check`; an open re-approval waits as `PENDING[question]`), an
  `integrity.py --check` FAIL on the proof-validity core, a freeze record or a judgement record, and a Lean commit
  after the last audited round (`deliver-stale`). Everything else `--deliver` used to refuse on (stale documents,
  reader gates, hand edits, the status check, result_status disagreements, pending adjudication, `unverified`,
  ownership of document and reader files, the PDF render guard, an open stop that waits for no human, the run
  record's listing) is printed as "notes for the main agent (not blocking)"; a PDF not rendered from the markdown as it is now
  is not shipped (the markdown is). No stop opens on a delivered document in either mode (`reader`, `reader-check`,
  `decisions`, `status-unmapped` join `NEVER_STOP`). The designed human waits stay: `PENDING[question]` for
  Checkpoint C under `involved`, `PENDING[stop]` for a stop that waits for the human (any open stop in dev).
  The generator writes its drafts to `<ROUNDS-DIR>/facts/` (Phase 0 included) and never overwrites or deletes
  the agent's SUMMARY.md and REPORT.md; README D states only the reviews on record.
- `--prepare-delivery` writes a facts draft (`facts/SUMMARY.md`, `REPORT.md`, `RUN_RECORD.md`) and never overwrites
  the main agent's documents. Stage 5 step 5: the agent writes SUMMARY and REPORT from the records and the Lean,
  four fresh reviewers (claims, readability, decisions, trust) advise with returned text, the agent judges each
  finding in `JUDGEMENT.md` (every overstatement fixed), renders the PDFs and delivers. The fresh readers, hand
  edits and status check are no longer part of delivery. Validated by a simulation on two real runs and by replaying
  `--deliver` on copies of both (the stuck example run now delivers). Mutants MG1-MG5; 23 mutants of removed
  delivery refusals dropped.

### Codex end-to-end fixes: stated-only conjectures, reproducible tool-patch facts (2026-10-26)
- Lane D (non-vacuity) rule 5b: on a stated-only conjecture (a `def : Prop` no theorem asserts) Pass means the
  sets/predicates it quantifies over are witnessed and the 4b probes close neither it nor its negation; never
  NotDoneYet for want of a proof of it. A Codex lane had returned NotDoneYet every full round, and delivery's
  RED[unverified] asked for a round that could not answer it. Statuses and delivery checks are unchanged.
- `tool_patch.py`: the facts a reviewer re-derives (regression and selftest tails, blast-radius lines) record the
  random scratch directories as `<scratch>`, other temporary names as `<tmp>` and object addresses as `0x…`, so an
  honest patch's FACTS.json re-derives identically.

### Codex port brought up to the redesign (codex-u2 2026-10-24, ported onto combined-fixes 2026-10-25 as codex-port; experimental; one hands-off end-to-end run on a synthetic paper, before the release rebase)
- Every subagent the Claude Code path spawns has a generated Codex role: new `formalize_citations` (citation agents
  1 and 2, step 5a; it replaces "a default agent") and `formalize_helper` (author-side helpers), eleven roles in all with the
  tool-patch reviewer and the status check.
  No role sets the network, the sandbox or tools; each child inherits the parent's sandbox (network off) and gets
  its network rule from its generated task (intake 1c). Every printed spawn line names its Codex role
  (`prompt.spawn_kind`). `run/codex.md` maps each Claude spawn to its role and lists every other difference: no
  network (prior-art and citation notes degrade, `--search` optional for a public paper only), steps that would
  leave the sandbox (fetch, push, copying deliverables elsewhere) handed to the person as commands, never an
  approval; seeing PDFs; waits and long commands. Claude Code behaviour unchanged (only the text before "with:"
  of a spawn line: the status check's and a reissued lane's now name their roles; the core-fault reviewer
  is `formalize_tool_patch_reviewer`). `codex_agents.py --selftest`
  checks the whole map from the sources: every spawn line a script prints names a generated role (or prints one
  through `spawn_kind`), every `formalize_*` role an instruction file names is generated, and every generated role
  is spawned somewhere; the history-fault acknowledgment reviewer (`integrity.py --ack-request`) is
  `formalize_tool_patch_reviewer` too. Mutants cu-1..13.
- `tests/snapshot_replay.py` selftest: its scratch directories fall back to the system temporary directory when
  `~/.cache/formalize-paper` cannot be written. Inside Codex's workspace-write sandbox ~/.cache is read-only, and
  `selftest_all.py --fast` FAILED there ("Read-only file system"), which made the Codex test run ask to re-run it
  outside the sandbox (CODEX-PORT test). Checked inside `codex sandbox`.
- integrity.py `pin`: a re-pin made without the project (`tool_patch.py apply`) keeps the first pin's Codex roles
  (`codex_agents`). It dropped them, so under Codex every applied tool patch was followed by `FAIL[codex-roles]`
  (stop S3 of the CODEX-PORT test run, self-cured there by a plain re-pin). Mutant cu-11.
- Codex roles: every generated role ends with a Codex-only sandbox rule (`codex_agents.SANDBOX_RULE`): a command the
  sandbox blocks is a failure the child records ("not reachable" for a source), never an approval it asks for. In
  the CODEX-PORT test run the citation child asked the person to approve downloading two cited PDFs. Mutant cu-12.

### Reviewed in-run tool patches; the deferral fallback reverted (post-release, approver 2026-10-24)
- Release mode: when a pinned check crashes or misjudges a case (bench1 S2, bench2 S1, bench1 S1 each ended at
  the person although the operator had diagnosed it exactly), the operator acts as maintainer:
  `tool_patch.py begin --stop S<n>`, a diagnosis and a minimal diff with a NEW regression test, `prepare`
  (mechanical facts: the regression test fails on the pinned and passes on the patched tools, every selftest
  passes, the blast radius over every round's read-only checks, the first pin's FLOOR of canary mutants),
  `review` (a fresh independent agent, prompt rendered from AUDIT_PROTOCOL.md, verdict sealed like a lane's;
  every earlier attempt and finding shown), `apply` (two commits: `tool-patch TP<k> apply` and `pin (tool-patch
  TP<k>)`), then `stops.py close --cured "tool-patch TP<k>"`. A reject is revised until approved (no cap, no
  stop); `withdraw` returns to the printed cure. A floor hit needs two approvals. Dev mode refuses all of it.
- integrity.py (ownership 4): every tool-patch link is verified by the apparatus pinned just before it; any
  other tooling change is `FAIL[tooling]`; a plain release re-pin may not change the tooling (`FAIL[pin]`;
  the gitmeta re-pin still passes); new code `tool-patch` (restore). `--deliver`: the first pin's apparatus
  checks that RUN_RECORD.md lists every applied patch and re-runs the floor; a patch that may have changed an
  earlier review's inputs forces a full round. Codex: the role `formalize_tool_patch_reviewer` (nine roles).
- Reverted: 378cf65's `stops.py close --deferred-to-full-round` and everything around it (its scope.py and
  `--deliver` hooks now serve the forced full round of a tool patch); kept: its T34 fix (`stops.recorded_plan`).
- Rejections are run-wide (re-check 2026-10-25): a diff rejected, or reviewed and never sealed, anywhere in the
  run is refused at prepare and apply on every later stop, a revision answers every earlier rejection of the run,
  and the reviewer's history lists the attempts of every stop (a diff rejected on S2 was accepted on S3, its
  reviewer shown "(none)").
- The "never resubmitted" rule compares diffs up to whitespace and line numbers (`tool_patch.diff_key`; re-check
  2026-10-25: a rejected diff with one blank line added had another sha256 and was accepted).
- A patch's selftests are the FIRST pin's (its project.py, plus any the patch adds), never the patched project.py's
  list, and a floor mutant counts as killed only when its selftest passes on the patched tools unmutated (re-check
  2026-10-25: TP-a moved lane_auth out of the pure tier, TP-b then disabled its prompt check, LA8 "killed" by a
  selftest that already failed).
- A tool patch only MODIFIES files of the first pin's apparatus: its one new file is its regression test, under no
  stdlib or apparatus module name; integrity.py FAILs a tooling file the first pin lacks and any stdlib-shadowing
  module in audits/, tests/ or tests/regressions/ (re-check 3, 2026-10-25: a new audits/re.py shadowed `re` and
  blinded phase0's sorry scan, with one approval).
- The proof-validity core is immutable to tool patches (`tool_patch.CORE`, read from the first pin): phase0.py, the
  axiom sweep (axiom_sweep.py/.sh, axiom_sweep_tail.lean), the freeze (fingerprint.py, fingerprint_tail.lean,
  olean_parts.lean), tool_patch.py and integrity.py; refused at prepare, apply and every link check (re-check 3: an
  edit of axiom_sweep_tail.lean accepting project-namespace axioms needed one approval and no guard fired).

### Release has exactly four human stops (post-release, approver 2026-10-24)
- At every involvement level a release run stops for the person only for: (1) a goal result that looks false
  or unprovable for a reason other than missing library theory; (2) an outward action the intake did not
  allow; (3) something only the user can fix -- a login, administrator rights, quota or payment, a change to
  their own files, or another program that keeps changing the project's files (`interference`); (4) NEW: the
  paper's meaning is genuinely ambiguous on a point that matters and the reviewers cannot converge on one
  reading (`--cause ambiguity`): the operator shows the passage, the readings and what each would mean for the
  formalization and asks; this holds under hands-off too, the answer is recorded verbatim and the run resumes
  at its own level. The old fourth stop, "a cure that keeps failing", is gone: a spent cure budget is
  classified (`stops.py classify`: a tool bug goes to the tool-patch route, outside interference is stop 3).
  A loose convention (ℕ from 0 or 1) is a reading-choice decision, never a stop. The statement-round cap with
  a faithfulness finding open is no stop in release: the operator judges it -- ambiguity (stop 4), convention
  (a reading choice) or anything else (the result reads "not established: open faithfulness finding";
  `round-caps/<round>.json`, owned by `round-cap <round>` commits). Dev mode keeps all its stops.
- RUN.md, the stage files, the intake paragraph, MAINTAINING S1, README, INSTALL and the Codex notes say the
  same; `tests/doclint.py` refuses the old fourth-stop wording in release text and checks the four stops
  appear consistently. Scenario selftests: the ambiguity stop at every level (hands-off resumes), the
  classification of a spent budget (a tool bug never reaches a human stop), and the three round-cap outcomes.

### RUN_RECORD.md: the process record, apart from the report (post-release, approver 2026-10-24)
- A separate deliverable `RUN_RECORD.md` (markdown only: never rendered, no reader; `audits/run_record.py`, written
  by `project.py --prepare-delivery` and hashed with the other prepared documents) holds how the run went: tool
  patches, every stop and who closed it, self-cures, set-asides and lane clearances, re-pins and reissues, faults
  disclosed instead of a stop, RUN_LOG's mechanical failures, and the fresh readers' known-fault notices (folded
  in at `--deliver`; no `KNOWN_FAULTS-*` file is delivered any more, and no `superseded/` directory).
- REPORT.md keeps eleven fixed sections (trust, assumptions, coverage, not formalized, defects, differences,
  vacuous, open questions, decisions, proof routes, Lean names; the reader notes end section 1, the notation
  section 11). Removed: "Stops cleared without you", "Every stop of the run", "Set-asides and clearances", the
  apparatus, reissue and set-aside trust rows and the disclosed/self-cured lists of the Run mode row. One trust
  line, "Checks weakened", says only "delivered by hand: the final delivery checks did not run" and/or "the audit
  tools were patched during this run; see RUN_RECORD.md". SUMMARY.md and the DECISIONS box drop self-cured stops
  and disclosed faults; the human's answers and the delegated closes stay.
- `integrity.py --check-run-record` (run by `--deliver` on the delivered copy and by the delivery gate on the
  prepared one): RUN_RECORD.md lists every applied tool patch (from TOOLING_PIN.json's re-pins and the
  `tool-patch TP<k> apply` commits), every stop the operator closed and every set-aside -- provenance only.
  README D points to RUN_RECORD.md and fingerprints it; `--check-delivered` compares it.
- Status check (advisory, approver 2026-10-24: "let agents guard code, not just code guard agents"): after the
  first prepare, a fresh agent (`prompt.py --prompt status-check --write`; Codex role `formalize_status_check`)
  reads SUMMARY.md beside REPORT.md and the records and lists each result whose summary status the records do
  not support (`status-check/FINDINGS.md`). The operator corrects each through the route that owns the status
  and writes `status-check/ACTIONS.md`; both are quoted in the delivered RUN_RECORD.md. Never blocks, never a
  stop; no script checks their content.

### F10/F12 items only for declared refutations (post-release, 2026-10-24)
- Benchmark run bench2: a reviewer's probe file `not_<X>_as_printed` (with no such declaration in
  the project) gave every round an F10 item no reviewer could judge (UNCOVERED,
  QUESTIONs, a standing defer, then an alias theorem that tripped RED[drift]). `scope.py` now schedules F10/F12
  items only for refutations `not_<X>_as_printed` that are declarations of the project at the round's commit;
  a name only lane text or a file name carries schedules nothing, and `scope.py` prints a note naming it
  (`lane_only_refutations`). The F10 rule is unchanged. Scheduling on the mini2/5/6/10/11 and bench1 snapshots is
  unchanged. A scenario selftest replays bench2's second fault (set-aside, empty commit, fresh diff round whose own
  lane decides the item, then `--verify`); it passes since 4dd9a08 (verify against frozen inputs).

### Deferral fallback: an impossible cure is not a human stop (post-release, 2026-10-24)
- Release mode: an integrity fault of an adjudicated round's review (a class-I `redo` code such as `prompt-changed`,
  or `tool-bug`) has no cure (`set-aside` refuses an adjudicated round), and the benchmark run bench1 (S1) went to
  the human for it. `stops.py close --stop S<n> --deferred-to-full-round "<text>"` now closes it: the round's
  verdicts are superseded (result_status drops them, so a tampered verdict never becomes a status), `scope.py`
  never skips the full round while a deferral is uncovered, and `--deliver` refuses until a later full round
  (scoped after the deferral, adjudicated, judging every item of its scope) has run. A fault in the final full
  round gets one more full round; a second is stop 4. Refused in dev mode, for faithfulness, proof, restore-kind
  or unknown codes, a statement round, and a round not adjudicated. The trail checks every deferral record.
  Review fixes: a deferred round's `## Hypotheses` rows and any cite of its verdicts support nothing; only a check of
  the round's own review (lanecheck, prompt, scope --verify, on that round) is deferred; the report names records the
  superseded adjudication wrote elsewhere; the trail re-checks a Stage-5 deferral as late from the committed log.
- TRADEOFFS T34: the stop trail judges an earlier self-cure by the apparatus pinned at its close (its scripts at that
  pin, in a subprocess), not by today's tables: a re-pin no longer turns a correct cure into "a human stop"; a forged
  cure is still caught.

### Live L-infinity run: bundle step (post-release, 2026-10-24)
- `signoff.py bundle` with a PROBLEM writes no `STATEMENTS_BUNDLE.md` (a failed commit restores the file as it was).
  The live run's bundle was left uncommitted, the round's set-aside committed it, and integrity stopped the next
  adjudicator on `FAIL[ownership]` (only a `scope` commit owns it; stop S1). `stops.py set-aside` now refuses an
  uncommitted bundle with the recovery (rm it), as it does the other files another step owns. The PROBLEM itself was
  a tool bug: a field of a Type-valued structure (a projection, no source text of its own) was reported as a
  definition whose source is missing; it is now shown by signature with a note naming its structure, whose
  definition the bundle shows. Scenario `tests/round3.py` t_bundle; mutants lsw-S1a..c.

### Advisory citation notes (citations, 2026-10-24)
- Stage 5 step 5a: after the final audit round, a fresh agent reviews every cited result the paper uses (as stated,
  a stronger form, not reachable) and its bibliography, and a second fresh agent verifies each item's evidence and
  writes `CITATIONS.md`: reminders for the authors to check, each with quotes and links. Prompts
  `prompt.py --prompt citations-draft|citations-review --write` (AUDIT_PROTOCOL.md); a confidential paper's agents
  only search for the cited works by title and authors. No check reads it; it never stops, blocks or changes the
  run. The summary gets one line ("Citation notes: N items — see CITATIONS.md", or "not produced: <reason>" from a
  RUN_LOG line); `--deliver` copies it and README D lists it. A run without it delivers exactly as before.

### Trial #11 audit fixes (protocol-u2-pdf, 2026-10-24)
- A decided defect row no longer reads "left to the human". Trial #11's PAPER_DEFECTS row 2 kept its statement-round
  decision cell ("whether to add a companion ... is left to the human") after the operator's [DELEGATED] decision
  under hands-off; the reader-fix may not touch a decision cell, so the operator ran a whole full round (50 min) for an
  adjudicator to rewrite it, which it did not. The generator now shows the decision instead, as it already did for an
  "open" VACUOUS row: a `defect:<anchor>: [DELEGATED …]` line (the anchor's version may be left out, as the decisions
  check accepts it) makes REPORT section 5 quote each sentence of the cell that leaves the matter to a person as what
  the row said when written, followed by the decision, and the summary's defect line say "decided since"
  (`make_report.decided_since(kind="defect")`, `settled_cell`; shown only, the record checks read the cells as
  written). stage5 step 1 lists it among the things that are never a reason for another round. Mutants t11b-1..6.
- A change to comments and docstrings only never needs a review round, at any stage. Trial #11 ran a Stage 5 full
  round (R3, 53 min) on R2's docstring-only fix (Stage 4's first full round had ADOPT rows, so Stage 5 "opened with its
  own full round") and then a diff round (R4, 31 min) on R3's docstring-only fixes ("a docstring fix of an ADOPT row
  is a fix like any other"; 347977f skipped such a diff round only in Stage 4). In Stage 5, `scope.py` now exits 3
  with `NEXT[no-round]` (`scope.no_round_line`) when the Lean is unchanged since the last proof-examining round, or
  changed only in comments and docstrings as `--deliver` decides it (the Lean comparison of
  `project.changes_after_last_audit`, so the delivery never asks for the round skipped), committed, with no item
  pending the next adjudication, no `deliver-stale` or `unverified` precondition and no set-aside redo due: a diff
  round then has nothing to audit, and a full round is already done when that last round is a full-scope proof
  round, adjudicated, every REVOTE NEEDED row decided and no unexpected UNCOVERED row (Stage 4's first full round is
  then Stage 5's full-scope round). Phase 0 still runs on the commit (the freeze check: approved statements
  unchanged); the report and the decisions document list the commits as comment-only, not re-read by a lane. This
  reverses fix-mini2 M2's rule that an ADOPT row's docstring fix is re-read by a lane (doclint and mutant rv-M2
  replaced; t11b-22). stage4 step 2/7 and stage5 step 1/7. Mutants t11b-15..22.
- The one-page summary's generator lines say something, and README C says what the sheet shows. Trial #11's
  SUMMARY printed "not a defect 2 — (full text in REPORT §5)" (a first sentence over the length limit left nothing:
  `_short` now falls back to its leading clauses ending at a comma), "not a defect (+2): 4; 5" (a counted item's ident
  now names the result it mentions; a proof route's names its result), the "Not defects" preamble as an item (a bullet
  that only points below or above and names no result, tex line, Lean name or number is not an item), and "proof
  route 1 — Theorem 2.1: paper step fails" (now the paper's tex line and the first clause of why the route differs).
  A `false` defect's line gives its counterexample when short, and the page ends with a "Terms" line for the terms it
  uses and does not explain (a round, a stop's class). README C said the sheet shows "the proofs as they stood then
  and line numbers of that commit" (the approval commit); it now says the sheet shows the statements, not the proofs,
  with the line numbers of the commit its own "Commit" line names, and the approval commit beside it when they
  differ (`project.sheet_commit`). Mutants t11b-7..14; mini2-3b and os-15 re-pointed.

### Trial #11 fix: a mentioned tag is no decision (protocol-u2-pdf, 2026-10-24)
- Live trial #11 (release, hands-off) looped on self-cures: a run-log line "QUESTION 1 decided [DELEGATED]" failed
  the report check's tag lint (S1); the cure text quoting the bare tag was copied by `stops.py` into `## Stops` and
  failed it again (S2). The lint (`decisions.tag_problems`, review B2: a decision in a variant spelling must not slip
  past the canonical pattern unseen) now reads a BARE `[DELEGATED]` as a decision only where one stands (opening an
  entry, or after its anchor or label); mid-sentence, in a code span or in a `stops.py` `## Stops` line it is a
  mention (`decisions.mentions_masked`, also used for the [PROXY]-under-a-delegating-level check, for code spans and
  stop lines only). A tag with anything inside it is linted wherever it stands (a dated one is counted as a
  decision). `stops.py close --cured/--delegated` refuses, before writing anything, a text the lint would refuse.
  Mutants t11-1..7.

### PDFs rendered and verified by agents (protocol-u2-pdf, PDF-AGENTS, 2026-10-23)
- Approver: the PDFs a human reads are made and checked by fresh agents, never by a script. The generators write
  markdown only (REPORT.md, SUMMARY.md, SIGNOFF.md, the sheet's paper statements as LaTeX source). Once a markdown is
  audited at its current hash (its fresh-reader gate; the hands-off sheet: `signoff.py check`),
  `render_record.py` runs the loop: a renderer (A, faithful and readable: it may rephrase or re-lay out for
  readability, never change the mathematics; Lean code character for character), a verifier (B), and on B's PASS
  two fresh checkers that judge only mathematical faithfulness; a checker's DIFFERENT goes back to A as a normal
  round, then B, then a fresh pair, within 6 renderer rounds. Spent: the least bad round ships with every
  remaining objection on a cover page. The markdown is always delivered beside its PDF. No round produced a PDF:
  the markdown ships alone (`no-pdf`), disclosed. Nothing in the loop is a stop; a crashed agent is `fail`ed and
  counts; a restart resumes from `pdf/<key>/RENDER.json` (every round's PDF and source committed).
- The one code guard is a fingerprint (`render_record.py check`): `project.py --deliver` and `signoff.py approve
  --by human` refuse unless the PDF is the one recorded for the markdown as it is now (`RED[deliver]`, render
  again). A human approval records the PDF's sha256 and the render outcome it was shown.
- Prompts: renderer, verifier, cover and checker blocks in AUDIT_PROTOCOL.md (`prompt.py --prompt
  render-a|render-b|render-cover|render-check`); the Codex role `formalize_renderer`; TeX engines allowed only with
  `-no-shell-escape` (LuaTeX `--safer`), pandoc only `--sandbox`, filters and `-shell-escape` denied.
- Removed: `render_fix.py` (the pdftotext comparison, the .tex edit allowlist, `--render-fix`, the render-check
  lane, the plain renderer), the LaTeX output of make_report and signoff, `project.py --pdf-check`, the PDF FAULT
  notes, `signoff.py glyphs` and `uni_math_extra.json`, the no-PDF test mode, the `pdf` mutant kind and its
  mutants, Phase 0's release PDF-only baseline exception. `pdf` stays a legacy cause code (never emitted; an older
  run's DISCLOSED[pdf] records still parse and stay in README D). `integrity.py`: `pdf/*` owned by `render `
  commits; the old `render/*` and `uni_math_extra.json` owners kept read-only.
- Migration: the reader hash is md-only; a pass recorded on md + .tex stands while the md is unchanged (a
  one-version shim in `readers.py`, to be dropped). An approval made on an old PDF stands; the approved sheet is
  rendered at delivery. Run `install.sh --upgrade <project>` (or `claude_settings.py`) for the new permissions.

### PDF-AGENTS review fixes (2026-10-24)
- `save` and `fail` refuse a step whose prompt was not issued (`prompt.py --write`), as lanes and readers do.
- The cover of a least bad PDF is checked by a fresh cover verifier (`--prompt render-cover-check`, `--role
  cover-check`), whose verdict is recorded: it compares the cover's objections with the record's, verbatim, and
  the pages behind it with the round's. A cover it does not pass never ships; after two attempts the round ships
  without a cover, disclosed. `finish` refuses a cover whose objection list is not the record's.
- `verified` needs both checkers' recorded SAME verdicts. A checker that did not run is never a pass: the
  outcome `verified-checkers-disclosed` is now `checkers-did-not-run`, and README D's line opens "NOT
  INDEPENDENTLY CHECKED" and says the checkers did not run.
- README D lists each delivered PDF's sha256; `project.py --check-delivered` (also run at the end of
  `--deliver`) refuses a PDF in `deliverables/` swapped after delivery, added without a fingerprint, or whose
  fingerprint is not its render record's.
- `render_record.py shown --doc SIGNOFF --round R`, run right before the human is asked, records the PDF shown;
  `approve --by human` refuses unless that is the PDF the record ships now, and stores it (not the PDF current at
  approval) in the approval.
- `install.sh --upgrade <project>` updates an existing project's `audits/` between runs (records, history and run
  mode kept; one `upgrade formalize-paper <version>` commit). INSTALL.md's old path ("move audits/ aside and run
  install.sh again") failed on the existing `AUDIT_PROTOCOL.md` link. Tested by `tests/upgrade.py` (tier 0).
- The subagent common rule 4 defers to the working directory a task names (the render prompts' `<DIR>`); `begin`'s
  refusal names the reader pass to run.

### Trial #8 (involved) fixes: the human is not asked twice (protocol-u2-int, 2026-10-24)
- Under `involved`, Checkpoint C no longer asks what the human decided at Checkpoint B: the approval, the approved
  sheet's global differences, CHECK rows and results not formalized, and the defect and vacuity rows the record held
  at the approval on a CHECK result. DECISIONS.md lists them once, under "Already decided by you at Checkpoint B
  (<date>)", with the B answer verbatim; delivery does not wait on them. One comes back only when its substance
  changes, saying it was decided at B. Trial #8's C asked 12 items, 9 of them B's; the same state now asks 3.
- A defect or vacuity item is keyed on its substance (location, printed statement, status, repair), never its prose:
  a reader-fix glossary sentence re-asked trial #8's two answered defects (C'). Answers logged under the old
  prose-hashing anchors still count (read from the record's history).
- Every answer in DECISIONS.md "Previously answered" names its checkpoint (trial #8 showed the C answer as the B
  approval's); a stop's answer is listed as the stop's, not as a stray anchor.
- REPORT section 9 and SUMMARY "Answers recorded as yours" show the human's own Checkpoint B and C answers, each
  with its checkpoint and audit commit; an answered open question (a reading choice) is no longer called a stop.

### Trial #10 audit fixes (protocol-u2-int, 2026-10-24)
- The sign-off sheet locates each Lean name of a row written in code spans (`` `N.x` ``, `` `N.d` (uses `N.y`) ``):
  trial #10's sheet showed doubled backticks and no `File.lean:N` at all.
- The report's trust table no longer says, for every self-cure, that a review's independence was compromised; each
  cured stop's line says what was done (52a863e).
- Stage 4: a diff round whose Lean differs from the last audited round only in comments and docstrings is skipped:
  `scope.py` exits 3 with `NEXT[stage5]`, and Stage 5's full round audits that commit with every lane (trial #10:
  a 16-minute diff round, then the full round on the same commit). Stage 5 keeps its diff rounds.
- AUDIT_PROTOCOL B.4: rejecting the removal of an idle hypothesis the paper states needs no re-vote (the rule keeps
  the paper's hypothesis; trial #10 spent about 25 minutes re-voting an idle hypothesis and kept it).
- One count of decision matters: the report groups the [DELEGATED] lines by DECISIONS.md's sections, as the summary
  counts them (trial #10: 23 decisions on 10 matters in the report, 7 sections elsewhere).
- Every qualified Lean name SUMMARY, REPORT, DECISIONS.md and the sheet cite must exist, resolved in Lean against the
  build (`signoff.py check`, `make_report.py --check --delivery`): trial #10 delivered a Mathlib
  name with the wrong namespace, written by the operator at Checkpoint A and copied by the sheet writer.

### SUMMARY is one page (protocol-u2-int, 2026-10-23)
- Approver: "one-page summary first". Trial #9's SUMMARY.pdf was 6 pages, left out items of three kinds
  (among them stop S2), and listed 20 decision lines for 6 matters. SUMMARY.md is now one page: the goal result's
  status; the results grouped by B9's status in plain words (equal statuses on one row); one short line per defect,
  proof slip, vacuous row, "not a defect" entry, assumption, idle hypothesis (UNUSED_ARGS.md), stop, hand delivery
  and other disclosure; the answers recorded as yours with their audit commit; one line with the number of matters
  in DECISIONS.md. When the page is full, a kind's items are counted by name with the REPORT section holding them
  (never dropped); a long text gives its first sentence and the place of the full text.
- `build_summary` and `make_report.py --check --delivery` refuse a SUMMARY.pdf of more than one page (code `pdf`:
  the render fix, never a stop); the plain renderer typesets SUMMARY compact so it fits too. The coverage check
  re-enumerates every item (listed whole or counted by name; nothing dropped, changed, invented or miscounted) and
  counts defects, slips, vacuous rows and stops from the raw records.

### Trial #10 fix: one refutation name (protocol-u2-int, 2026-10-23)
- A refutation of a printed statement has ONE name, `not_<decl>_as_printed` (`make_report.AS_PRINTED`), read by the
  F10/F12 checks, scope.py's F10 scheduling, prompt.py and `signoff.py reapprove --refuted-by` (its own regex
  removed). A theorem `make_report.lean_refutations` recognises under another name (trial #10:
  a theorem named `<decl>_as_printed_false`, which got no F10 item, so the adjudicator could not record its row and a statement
  round was lost) is refused before any round: Phase 0's index check (`FAIL[index]`, statement rounds too) and
  `scope.py` print the exact rename (`make_report.refutation_rename`); the F10 problem and `--refuted-by` name it too.
- The rule reaches whoever writes the Lean: stage2's "A result false as printed" bullet, and a new
  `prompt.py --prompt formalizer` brief for author-side helpers (stage2/stage3 spawn them with it); the
  paper-faithfulness lane names the missing `not_<decl>_as_printed` in its next_step (in trial #9 a result false as
  printed shipped with no refutation scheduled).

### Trial #7 and #9 audit fixes (protocol-u2-int, 2026-10-23)
- The freeze check (`fingerprint.py --check`, every Phase 0) also compares the approval round's statements bundle
  with a fresh build: a layout-only change to an approved statement (a space lost in a docstring edit) is
  RED[drift] in the round that made it, not first at delivery (trial #7: found 5 h later).
- A self-cure is described by what its cure did (`stops.cure_done`); only a redo says a review's independence
  was compromised.
- SIGNOFF.md carries the Lean statements of the round's bundle, the no-definitions sentence and the approving
  paragraph exactly as the .tex prints them, so the plain-renderer fallback keeps the Lean (trials #4, #6, #7, #9);
  its `File.lean:N` are the lines of the sheet's own commit (`make_report.locate_names(at=)`), as it claims.
- The DECISIONS box quotes the printed statement, then '; ' and the counterexample (`decisions.why_summary`), never
  the 'why' cell's first sentence (trial #9: a sentence restating a definition).
- A QUESTION on a declaration no index row names and the delegated lines answering it each round are one
  DECISIONS.md section (trial #7: 13 of 29 decisions re-asked on four worked examples).
- REPORT: "Where the Lean names are" lists every name cited above it; the terms define F10, F12 and probe; the
  decisions section is named by title. Stage 4 goes to Stage 5 without a diff round when the only ADOPT rows are
  comment or docstring fixes.

### Trial #9 delivery fixes (protocol-u2-int, 2026-10-23)
- A reader-fix round that changes no record cell is a valid outcome: `integrity.py --commit-reader-fix` records it
  as an empty `reader-fix R n` commit (body `no change`, `rounds: <dir>`), counted toward the budget of two, so the
  remaining `[content]` findings close as unfixable (disclosed) instead of a stop (trial #9, S2).
- Generated text a reader reads is never clipped (`project.full`): the "decided since" decision on a VACUOUS row, a
  stop's note and answer, Checkpoint A, the records quoted in DECISIONS.md, the escalation question, a long first
  sentence; the box quotes the printed statement in full (it read "the paper says Let …" and stopped). Only labels whose
  full text follows may be cut; `make_report.clipped_lines` tests it.
- The proof slips of PAPER_DEFECTS.md reach the summary ("proof slip") and both boxes. The summary's appendix map
  gives SIGNOFF.pdf's path and says README.md is written at delivery; the approval names its commit as the Lean's.

### Integrated review fixes (protocol-u2-int, 2026-10-23)
- The delivery phase is bounded (`project.DELIVERY_ROUND_CAP` = 2): after the newest full round a Lean commit asks
  for a diff round (`RED[deliver-stale]`) only while fewer than two ran; past that it ships, disclosed as not
  re-audited with the cap named (report, summary, decisions item). Stage 5 said "start no further round" while
  `--deliver` asked for one per change, and each round could adopt more.
- An empty diff scope while an item awaits the next adjudication (a `leave <decl> unproved` line logged after the
  final round, a route change recorded since the last adjudication, an unsettled Fail) routes to a full round
  (`NEXT[full-round]`), never back to Stage 5 (`make_report.pending_adjudication`).
- A route change recorded in AUTHOR_NOTES.md after the last adjudication is `RED[adj-record]` at delivery until a
  round's adjudicator has seen it (ownership 3).
- A statement round given up at `signoff.py bundle` is set aside (counted by no cap); a restart at the same Lean HEAD
  is refused with the prescribed empty commit, which `tree_state` now accepts for full/statement round names.
- `stops.py open/close/list` work before the config exists (Stage 1 steps 0-1): a human stop P<n> kept beside the
  saved intake, moved under `## Stops` by `--intake-move` (which refuses while one is open).
- Dev: `RED[status-unmapped]` has a cure (a stop; Phase 0 or the index cell; what remains is accepted as shown when
  the stop closes). A Checkpoint C answer citing an escalation, an adjudicator's record or the conservative rule is
  never the human's. At the statement-round cap a QUESTION the agent decides is not an open finding. An open
  re-approval prints as "decision open", never "faithful". B9's per-result verdicts are in `LANE_ITEM_PATHS`.
  `--prepare-delivery` names make_report's failure lines and routes a PDF fault to the render fix.

### Integration of B9 and B10 (protocol-u2-int, 2026-10-23)
- The summary's result statuses are `result_status.py`'s (the B10 stub "no finding recorded" is gone); matching a
  record to a result is part-aware (`Lemma 2.4 (c)` no longer names `(a)`); `--check --delivery` adds B9's routes
  (a missing or stale verdict: `unverified`; an outstanding Fail/Ambiguous or unrecorded assumption: `adj-record`;
  `status-unmapped`: disclosed in release, refused in dev); the summary prints the status legend.
- The summary's assumption part is B5's `hypotheses.report` (it crashed on B5's dict): the count line, or NOT
  COMPUTED with its reason (as the report says, never "none"), B6's missing-theory rows, each hypothesis with its
  Lean binder/type, record state and plain English. The summary lists the human's waivers.
- An empty diff scope while a Lean commit is unaudited (mini5: a theorem turned into an `example`) prints
  `NEXT[full-round]`: run a full round, not Stage 5 (the loop between Stage 5's deliver-stale and an empty diff round).
- DEVIATIONS.md is the adjudicator's from ownership 3 (`integrity.OWNED_SINCE`): the operator proposes route changes
  under "Route changes" in AUTHOR_NOTES.md. In a run pinned before 3 its `reading choice`/`differs` rows change only
  in an adjudication (FAIL[ownership]; `--check --delivery` RED[ownership]). An operator commit making a row a
  reading choice made the summary say "faithful under reading N", unchecked.
- The plain renderer's text check reads pdftotext's `-raw` text too (its default reading drops the hyphen of a line
  ending in "-": mini4's report failed the check at every level and was called an environment fault); a plain
  renderer failure while xelatex works is `FAIL[tool-fault]` (disclosable: `TOOL_FAULT_SCRIPTS`), never the
  environment's.
- A PDF fault never opens a stop, in any mix: `stops.py open` records the other faults only (`left_out`), the
  delivery gate routes a PDF-only failure to `--render-fix`.
- Compatibility: rule 4 labels B10's owned files; GEN_INPUTS names `escalations/*` and `waivers/*`; no text sends
  the reader to "page 1 of the report"; `result_status.py` enters through `run_main` (L2).

### B9: one status per result (U2 §1: F1, F7-F9)
- `result_status.py` combines what the records say about each numbered result into the statuses of U2 §1, every
  one that applies, in order: excluded at Checkpoint B, not formalized, decision open, stated only (a conjecture:
  "stated as a proposition, asserted nowhere"), defect (B3's status and repair in plain words: "false as printed;
  proved as repaired", "vacuous as printed; intent unknown"), differs, vacuous, not established: <reason>, proved
  assuming `H` ("(source not checked)", "also proved unconditionally"), faithful under reading X, faithful.
- "faithful" (F1) only when the latest correspondence, paper-faithfulness and non-vacuity verdicts on the result,
  and correspondence and paper-faithfulness on every Definition row of its fingerprint closure, are Pass and no
  older than the result's (or the definition's) last fingerprint change; a non-Pass verdict counts as settled only
  when the adjudicator REJECTed it, or decided it and an adjudicator-owned record names the result (an operator's
  DEVIATIONS row never clears a verdict); no drift from the approved statement; every assumption classified and
  recorded (F7, F9). A NotDoneYet is no verdict.
- Routing of "not established": a missing or stale verdict -> `unverified`; an outstanding Fail/Ambiguous or an
  unclassified/unrecorded assumption -> `adj-record` (the adjudicator); drift -> `drift`; anything else -> the new
  code `status-unmapped` (disclosed in release, a stop in dev). An open question is "decision open".
- `scope.py` records each declaration's project-local deps in the round's FINGERPRINTS.json (`deps`): the closure is
  read from the record. A round without it requires every Definition row (conservative).
- DEVIATIONS.md gains the kind `differs` (U2 §3, F10).
- The interface B10's summary calls: `result_status.result_status(cfg, row, inp)`; `result_status.py [--json]
  [--check] [--live]` prints every result's status and route.

### Fix: no pinned path gave a lane the F10 item, so a false lemma deadlocked the run (2026-10-23)
- Trial #7 (release, hands-off) stopped: the adjudicator could not commit, because the
  lane refutation `not_<X>_as_printed` needed a `false` row citing a Pass F10 item that no script
  ever put into a lane's scope (and `--revote` refuses items outside it).
- `scope.py` now gives the paper-faithfulness lane "F10: the counterexample of <result>" and "F12: the
  repair of <result>" for every refutation `not_<X>_as_printed` (a declaration at the round's commit, or
  one an earlier round's lane named; a diff round only while no lane has decided it, or when it is in
  scope), and in a full round an F10 item for every `false` row, refutation-less ones included
  (`_meta.f10` records each item's source; `--verify` accepts rounds scoped before this). `prompt.py`
  lists them under REFUTATIONS TO JUDGE, naming the Lean refutation or quoting the row's counterexample;
  `--revote` takes them as items of the scope.
- `make_report`: a lane refutation is due once a paper-faithfulness lane has decided (Pass or Fail) its
  scheduled F10 item (before that the next round schedules it again), so the stuck round commits and the
  next round records the row. An F10 citation reads the item naming the row's result when the record
  judges several.
- `prompt.py --selftest` checks the invariant: every `<NAME>_ITEM` constant of a gate, and the F15 and
  B7 lane requirements, have a pinned path into a lane prompt (LANE_ITEM_PATHS), each exercised by
  rendering a fixture's prompt and passing the check with a Pass for the rendered item.

### B11: the decisions document, one decision per matter (2026-10-23)
- `decisions.py --write` gives one section per matter (U2 §6.1, D3 §4; the mini2 audit counted 23 items
  for about 8 matters): a QUESTION row on a paper result ("Lemma 1.2") and a delegated line answering
  it (`QUESTION row on <item>, round R`, or logged as `- <anchor>: [DELEGATED …]`) join that result's
  section; items on no paper result are grouped by kind (global differences, standing rules,
  delegated lines, …). Under `involved` each question, [PROXY], open question and re-vote stays its
  own section. Fix: the writer's field prompt "re-approval?" made any delegated line naming the
  approved round part of the statement approval (mini6).
- Under a delegating level an item the operator decided and logged under `## Answered` with that
  level's `[DELEGATED]` tag keeps its section, its Decision taken filled from the log, instead of
  moving to "Previously answered" (mini2, mini4 and mini6 rewrote those decisions by hand in an
  appendix of about 3,000 words). Answered items are listed once per matter. Dev too.
- The "At a glance" table has one row per section (a matter's row lists its items' sources and
  costs, `;`-separated); each item keeps its own tagged Decision taken line. The fields' writing
  prompts are HTML comments, so the delivered document shows only the field names.
- Review fixes (mini6 hands-off review): `--check` requires each decision logged in `RUN_LOG.md` to stand
  word for word in its item's Decision taken (M2: a prefilled line was rewritten as "dropped …"), and
  exactly one tagged line per item, each naming one item (M3: one line named all five anchors).
- `--check` (delegating levels) also refuses a [DELEGATED] decision that a committed `RUN_LOG.md`
  recorded and the log no longer holds (M4: a delegated record was removed and its decision rewritten).
  A decision is changed by logging a new line beside it; a line the tag check refuses may be corrected.
- Readability (the reader is a mathematician): a decided delegated line is shown once, in its Decision
  taken (it was also the item's heading and a run-log quote); a merged section's decision lines open with
  the item's plain label ("CHECK row: Lemma 1.2"), the anchor id small at the end; section headings read
  "Lemma 1.2 (5 items: …)".
- A standing rule is one matter: a QUESTION row or a delegated line naming a configured or proposed
  standing rule is decided in that rule's section, and the paper result it sits on points there ("See
  also"); the report groups the same way (mini6: the standing-defer decision stood in two sections).

### B12, B13: Checkpoint C before delivery; restarts, caps, run_main (2026-10-23)
- `involved`: Checkpoint C is asked on the checked documents BEFORE delivery; `project.py --deliver` waits
  (`PENDING[question]`, never a stop) while an item of the decisions document has no answer of the human's
  (`decisions.checkpoint_c_open`; a [PROXY] or [DELEGATED] answer counts for nothing). Stage 5 step 7, at
  every level after C's answers or a reversal: carry out; Lean changed -> Phase 0 and a diff round;
  statement changed -> re-approval; DECISIONS.md written again; documents, readers, deliver. Dev too.
- Restarts: Stage 0 saves the intake before anything else (`project.py --intake-save`; Stage 1 moves it
  into RUN_LOG.md, `--intake-move`); `project.py --stage` then says "resume, no new intake", and Stage 1
  uses `git switch` on an existing branch. `signoff.py approve` killed before its commit: run again, it
  commits the approval only when equal to the one it recomputes, else discards it
  (`FAIL[uncommitted-record]`) and the approver is asked again. `lane_auth.py reissue` finishes an issue
  or reissue killed before its commit (an issue never committed is issued afresh). Dev too.
- Caps: 4 statement rounds before the first approval, 2 per re-approval (`scope.py --statements`):
  `NOTE[round-cap]` with no faithfulness finding open (no stop: the last round's sheet, its
  statement-changing ADOPT rows recorded as decisions), `PROBLEM[round-cap]` with one (stop 4,
  `--cause round-cap`, class H). The diff-round cap is never a stop in release (a [PROXY] default under
  `involved`, put to the human at C); `thorough` is capped at 6 diff rounds under a delegating level.
- L2: every script's entry is `project.run_main`: a crash prints `FAIL[uncoded] <script>` (code
  `uncoded`, class I, kind rerun, the unknown-retry key); the project selftest checks every script uses it.
- Codex: a missing spawn tool or role, or the operator's own usage limit past the time budget, is
  `env-unknown` (a human stop). RUN.md's "Stops that remain" says which stops are `dev` only.

### Fix: the report's PDF check failed in an installed, PDF-on selftest (2026-10-23)
- The report is set ragged right (`make_report.PREAMBLE`). Justified, a line holding a long record path
  (a defect row's `F10:`/`F12:` lane paths) stretched its spaces so far that pdftotext read it as
  separate columns; the render check then failed the PDF ("does not say what REPORT.md says"), and in
  `make_report.py --selftest` that fault failed eight later B3 and SKIPPED checks. Only the PDF-on
  selftest (the operator's `selftest_all.py --fast`) showed it; every builder's tier 0 ran without PDF.
  A new check fails on the PDF fault itself; mutant pdf-on-1 removes the fix.
- Tier 0 also runs `make_report.py --selftest` and `signoff.py --selftest` with the PDF compiled
  (`tier.py --selftest` checks the plan); TIERS.md says to run it from an installed project.

### B6: missing theory (2026-10-23)
- Under a delegating level, a result needing theory no configured library has is never a stop (a goal
  result included; RUN.md's goal stop now reads "false, or unprovable for a reason other than missing
  library theory"): the operator searches every configured library, estimates, builds the theory if
  only definitions and easy lemmas are missing, else assumes the missing result as a named hypothesis
  `H` (a project Prop definition taken as a binder of the result). Never "do not formalize".
- The decision is one canonical `RUN_LOG.md` line (`[DELEGATED …] missing theory: assume `<H>` for
  `<R>` — searched: …; estimate: …; paper: "<the passage>"`, or `… build <what> for `<R>` …`; under
  `involved` the human form `- missing theory (human <date>): …`). The report check refuses, as
  `FAIL[missing-theory]` (new code: document; release F/rerun, closed by `make_report.py --check`), a
  bare or non-canonical line, one without the quote or a configured library's search, the wrong
  level's form, and an `H` that is not in its result's assumption list; a corrected line clears it.
- F13: the paper-faithfulness lane, not the operator's line, judges `H` (quote not the paper's, the
  paper derives the result, `H` stronger than the invocation: Fail); non-vacuity flags `H` that is the
  goal's main step. Section 2 classifies `H` as missing theory with its result and quote; page 1 says
  "<result> proved assuming <H>" (and every goal result whose statement takes `H` too) and how far it
  was checked.
- Review fixes: an `H` the walk flags as restating a result the project states (mini5: a
  hypothesis restating a proposition the project itself proves) is `FAIL[missing-theory]`
  ("prove it instead"), its row may only say `no`, and the F13 lane Fails a hypothesis a library or the
  project already proves; an `H` that is a goal's conclusion or restates a goal is `FAIL[unproved-goal]`
  (stop 1); a human line needs the human's committed answer naming the result on its date; option (3)
  has the human form `- missing theory (human <date>): do not formalize `<R>` — …` (refused as
  [DELEGATED]); a `build` line is refused while the hypothesis it replaces is still a binder.
- F13 item (with trial #7's LANE_ITEM_PATHS): each missing-theory hypothesis of `RUN_LOG.md` gets the
  item "F13: the missing theory <H>" (`hypotheses.F13_ITEM`) in every round's paper-faithfulness
  scope (`scope.py`, `_meta.f13`, kept as recorded by `--verify`), listed under MISSING THEORY TO
  JUDGE (`prompt.py`, `--revote` takes it); its `yes` or `source unavailable` row needs a Pass on
  that item. Mutants f13s-1..5.

### B10: delivery, landed together (2026-10-23)
- `project.py --prepare-delivery` is the only generator of what is delivered: SUMMARY and REPORT
  (make_report.py), the DECISIONS box, the approved sheet's stamp, README sections A-C; it records each
  document's generator-content hash and the Lean commit in `DELIVERY.json` and commits all of it ("prepare
  delivery"). It runs while a stop is open (listed OPEN AT PREPARATION).
- `project.py --deliver` only checks, in both modes: `make_report.py --check --delivery` (each prepared
  document recomputed in memory and equal to its record and its file; each reader gate; the summary's
  coverage and result-status check; `unverified`, `deliver-stale`, pending items), no stop or QUESTION
  open, `deliver_blocking`, the render recompute of SUMMARY.pdf, REPORT.pdf and SIGNOFF.pdf; then the copy,
  with README = A-C as prepared + section D (known faults, delivery-phase records, reader outcomes), D
  only in the copy (ADDENDUM N6).
- One-page summary (`SUMMARY.md`/`.pdf`, delivered first; REPORT's section 0 points to it): every result
  with every status that applies, every defect, reading choice, assumption, decision taken on the
  reader's behalf, stop, self-cure and disclosed fault, one generated line each, never clipped. Until B9
  a result with no recorded finding reads "no finding recorded", never "faithful".
- Delivery codes `deliver`, `unverified`, `deliver-stale` are preconditions of `--deliver`, never a stop
  (ADDENDUM N1); `pdf` is never a stop either (approver: once the documents exist the run does not stop;
  the render fix ends at worst in the plain renderer). `stops.py open` refuses them in both modes.
- Readers: `--doc summary` (gated at every level); REPORT and DECISIONS get exactly one pass per version
  once the delivery flow runs; findings are labelled `[content]` or `[presentation]`; a content finding
  goes to the adjudicator's reader-fix round (`prompt.py 4 --reader-fix`, `integrity.py
  --commit-reader-fix`, at most 2 per run, its prompt hash checked by lanecheck; ADDENDUM N4). The
  hands-off sheet has no reader (`signoff.py check` kept; disclosed in the README); `deliver_checks` no
  longer gates it (with stage2-statements.md, L4). Dev: a missing pass, or a blocking finding left
  unfixable past the budget, is a stop.
- Generated documents cite the last Lean commit, never HEAD (ADDENDUM N2); a delivery-phase record (a
  reader's, the PDF's or the rendering's disclosure) is listed in README D, never in the documents.
- Dev-reaching (U2 §10): the reader modes and fix route, the summary, prepare/deliver.

### B4: refuted-statement repair (2026-10-22)
- `signoff.py reapprove --begin --refuted-by <ns>.not_<X>_as_printed` (U2 §3, F11, ADDENDUM N3): checked
  in Lean -- the theorem's type is `¬ <X>_as_printed`, its axioms are standard (no `sorryAx`; the
  refuted statement's own `sorry` may stay), `<X>_as_printed` is defeq to the statement approved at B,
  or after a failed correction the same `_as_printed` the first repair checked. A goal result is
  refused (stop 1). The begin records the refutation (`REAPPROVAL.json` `refuted`). Dev too.
- F12: a `false` defect row with a minimal repair (typo, add hypothesis, local) cites the
  paper-faithfulness lane's F12 item (Pass, naming the step of the paper's proof that uses the added
  hypothesis), else `PENDING[adj-record]` (the repair is `substantial`); a `--refuted-by` refutation
  needs its `false` row or encoding-error line, like a lane's. Lane C and the adjudicator prompt say so.
- M5: the delivered sheet (the latest approval's) keeps its CHANGED marks when rendered again after
  its approval (compared with the approval before it; approvals ordered as made, not by commit hash);
  a hands-off re-approval sheet says "Statements unchanged since the latest approval; K re-approved by
  the agent, marked CHANGED."; `approve --by human` on a re-approval refuses until the sheet's
  fresh-reader check passes.

### B2: questions, the pending state, the stop policy (2026-10-22)
- Level-reserved decisions are QUESTIONs, never stops: under `involved` and `statements-only` a change
  to a statement the human approved is a question (`reapproval.md`); the run goes on and only
  `project.py --deliver` waits (`PENDING[question]`, no failure line). Under `statements-only` a
  QUESTION row on that statement is the human's (`decisions.needs_human`).
- `signoff.py approve --by agent` closes an open re-approval only under `hands-off`, or when the
  intake's 5d chose the agent (the first logged answer), and only when the approval it replaces
  was the agent's; otherwise it refuses with `PENDING[question]`. An unreadable 5d means the human.
- Pending state (H3): while that question is open, Phase 0 (author and read-only) prints the
  statement's `sorry` as `NOTE[reapproval]`, the report check prints `PENDING[question]` instead of
  refusing the open re-approval, `decisions.pending_unproved` leaves the statement to the question,
  and the axiom sweep accepts sorryAx reaching a result only through it (a walk that stops at the
  pending declarations; a goal result is never pending).
- `drift`: the release cure is always restoring the approved statement; an intended change is a
  re-approval begun before the edit, never inside the open stop.
- `project.stop_policy_text(mode, level)` generates the intake paragraph (the four stops; the
  questions each level asks; a dev installation sends its own) and the Checkpoint A line
  (`prompt.py --show intake`; without a config, the installation's mode). `tests/doclint.py`
  checks `stage0-intake.md` carries it. The intake no longer says tampering stops a release run.

### B7, B8: smaller items, rule 4 (2026-10-22)
- A literature hypothesis later proved is never retired and never re-pinned: its proof lands as a pure
  addition `<decl>_unconditional`, audited by the next round like any new declaration (U2 §7a).
- Non-vacuity lane: a step of the paper's proof by contradiction needs the paper's quoted passage and
  the negating lemma (`CONTRADICTION STEP: negated by ...; paper (tex l.N): "..."`); a docstring alone
  is Ambiguous, and a Pass claiming the step without that form is a lane fault (re-voted). A passed
  step needs its VACUOUS.md row (`PENDING[adj-record]` until the adjudicator writes it) (§7b).
- Non-vacuity lane: each goal and main theorem is tried with `first | decide | simp | omega | aesop |
  exact?` under short heartbeats, with and without its hypotheses; a closure is Ambiguous (a QUESTION
  row, the sheet's CHECK), never a Pass (§7c; a lane judgement, not enforced by a script).
- Reading choices: never formalize both readings; the adjudicator's QUESTION row recommends the weaker
  one, or, when neither implies the other, the one the paper's proof proves; RUN.md "How you decide"
  takes it under a delegating level (§7d).
- The report's "Proof routes" row adds "slips are recorded when found; proofs are not checked line by
  line against the paper" (§7e).
- Escalation check (§7f): `prompt.py --prompt escalate --question ... [--decl] [--passage "tex l.N-M"]
  --write` builds the prompt (question, declaration with `File.lean:N`, paper passage quoted from the
  source), writes it once and commits it as `escalate E<n>` with its sha256 and inputs;
  `lanecheck.py --escalation E<n>` refuses an answer whose prompt changed, was committed otherwise, or
  is not what prompt.py renders for the recorded inputs, and commits the answer. A new owned record
  (`escalations/`, `escalate`). Dev too.
- RUN.md rule 4 is generated from `integrity.OWNERS` (`integrity.rule4_text`; doclint checks it), and
  names the reader responses and notices the operator writes (it used to forbid them) (U2 §5, §8).
  `reapproval.md`: a delegated re-approval may also repair a refuted statement.

### B7 re-check fixes (2026-10-23)
- `lanecheck.py --escalation E<n> --returned-file <file>`: the subagent's final message, saved verbatim
  with a quoted heredoc (`cat > <file> <<'RETURNED'`), so the backticks and `$` the escalation prompt
  invites survive (a `--returned "..."` call lost them and the honest answer was refused). The answer
  file must still be the message's last line. The protocol text and prompt.py's printed line show it.
- A contradiction step's quote is compared with the .tex with all whitespace, `$`, ties, spacing
  macros and simple formatting wrappers (`\emph`, `\textit`, `\textbf`, `\text`, `\mathrm`, ...: their
  argument kept) dropped, and `{x}` read as `x`: `$x_{n + 1}$`, `\pmod{m}` or a dropped `\emph` no
  longer make an honest quote a lane fault.
- An escalation names its declaration (`prompt.py --prompt escalate ... --decl`, now required), and the
  matter it is about is keyed on the declarations it names (`--decl` and declared Lean names in the
  question), never on its wording: a later escalation on a declaration whose earlier escalation was
  answered NEEDS-HUMAN or has no accepted answer is its re-ask (under `involved` citing it is
  refused). A rephrase ("Is ℤ the intended domain ...") used to pass.

### B7 review fixes (2026-10-23)
- Escalations: an answer counts only when `lanecheck.py --escalation E<n> --agent-id <id> --returned
  "<final message>"` commits it from the subagent's own returned line (id and sha256 in the commit).
  The report's "Decisions after the intake" lists every escalation with its answer (both renderings);
  a later one on the same matter as an earlier NEEDS-HUMAN is marked as its re-ask. A cited
  "escalation E<n>" must exist and be accepted (report check, `decisions.py --check`); under `involved`
  citing a re-ask is refused (the human's question). A DECISIONS.md section citing one shows its answer
  and a re-ask's earlier NEEDS-HUMAN; an accepted ANSWERABLE counts as a Recommendation's source.
- Contradiction steps: the quote must occur in the paper's .tex (whitespace aside) and the negating
  lemma must be declared, else a lane fault; the VACUOUS.md row must name the step or lemma exactly in
  its statement cell, status open or repaired. A Pass the adjudication overturned (REVOTE NEEDED,
  QUESTION, a Fail/Ambiguous verdict cell) demands no row (it was PENDING forever). The marker is read in
  any case as a label.

### B1c review fixes (2026-10-22)
- `--restore-gitmeta` writes and deletes only in `<gitdir>/hooks`, and only when that is also the
  snapshot's resolved hooks directory. The snapshot records the resolved hooks directory and
  `core.hooksPath` in every scope; either one changed is `FAIL[env-unknown]` (stop 3), nothing
  restored (attack H: a global `core.hooksPath` made the cure delete another directory's files).
- The revert test compares HEAD's tree with the tree hash `--save` recorded (a baseline without
  one accepts nothing), never asks git for the baseline commit's tree again; `tree_state` and
  `integrity` run git with `GIT_NO_REPLACE_OBJECTS=1`. A `refs/replace/*` ref or `info/grafts` is
  `FAIL[gitmeta]` (and `--save` refuses); one not in the Stage 1 snapshot is `FAIL[env-unknown]`
  (attack R: a replace ref made a tampered tree pass as "reverted to the baseline").
- `--revert-foreign` refuses (`FAIL[gitmeta]`) while the git hooks or config differ from the
  baseline or the Stage 1 snapshot, and commits each revert with `-c core.hooksPath=/dev/null`,
  `--no-verify`, `--no-gpg-sign`: no hook runs (attack K: a planted post-commit hook ran).
- Destination settings are stop 3 like a remote's url, in every scope: `url.*.insteadOf` /
  `pushInsteadOf`, `http.*.extraHeader`, `branch.*.pushRemote` / `branch.*.remote`,
  `remote.pushDefault`, `core.sshCommand` (attack U: they were restored, or not seen, as gitmeta).
- `integrity.revert_problem`: the record files a revert changes must be exactly the foreign
  commit's misowned ones (a superset, undoing records that commit owned, is no verified revert);
  its other files must be exact inverses; a verified revert excuses only its misowned files that
  are the foreign commit's. Content only, no stop binding. Mutant b1c-r5a ("accept a superset")
  replaces the retired scr-5b (compat H1).
- The Stage 1 snapshot comparison and the stop-3 identity, destination and history checks of
  `tree_state --check` apply in release only; dev is as before B1c (every gitmeta change, rewritten
  history included, is `FAIL[gitmeta]`, the human's) (compat M1).
- A pin without a Stage 1 snapshot: `--restore-gitmeta` is `FAIL[env-unknown]` (stop 3); a re-pin
  adds the snapshot when the pin has none (compat L1). `user.*` / `credential.*` count for stop 3
  only in the repository's own (local, worktree) config; a remote's url, the destination keys and
  `core.hooksPath` in every scope (compat L2; the rule is stated in RUN.md).

### Reverts by tree equality, gitmeta snapshot (U2 B1c, 2026-10-22)
- `head-moved` is a restore in release: `tree_state.py --revert-foreign` runs `git revert --no-edit`
  over the whole foreign range (`-m 1` for a merge); `tree_state --check` accepts a range that changed
  files only when HEAD's tree equals the baseline's (NOTE[reverted]; dev unchanged). A commit titled
  as a revert is never accepted by its subject.
- `integrity.verified_reverts` pairs a revert with the earlier commit whose foreign record change it
  exactly inverts, by content; `stops.py revert`'s and `git revert`'s commits both qualify, and the
  stop-record binding is dropped.
- The pin records a Stage 1 snapshot (`tree_state.snapshot`: hooks with content, risky config,
  remote url/credential/user, HEADs); `tree_state --check` compares against it; `--restore-gitmeta`
  restores only its hooks and keys. A changed remote, credential or user setting, or pinned history
  no longer an ancestor, prints `FAIL[env-unknown]` too: stop 3. No author or identity test.

### Failure tally and redo lineage (U2 B1b, 2026-10-22)
- Release self-cures are bounded by one failure tally (`stops.fault_keys`, `tally_events`, `tally`):
  fault key (check script, cause code); a `--note` stop keyed by (its code, round), the retry codes
  (`unknown-retry`, `tool-call`, `git-error`, `tool-bug`, uncoded) sharing one key, plus the coded
  faults its check printed. Failed cures counted over the whole run (`CURE_BUDGET` 2), openings per
  key and round (`OPEN_CEILING` 3, new); passes are no longer counted. Replaces `cure_key`,
  `cure_history`, `same_cure`.
- Review fixes: per-stop cap (a stop with 2 failed cures of its own is stop 4, whatever codes); the
  failed-cure budget is whole-run per (check script, code), `(script, unknown)` included, and
  `commit-refused` joins the retry codes (a `--note` key now counts openings only); openings count
  only after a failed cure of that key in the round, bucketed by the newest round with a verdict
  file or adjudicated; a child's capacity error or usage limit waited out is logged, no stop; a
  redo's fresh round must have sealed verdicts on every item of the set-aside scope, and a redo
  whose check names no round also runs `lanecheck --round <fresh round>`.
- Re-check H3: a `--note` stop's openings key carries its check script, ("--note", code, round,
  script): tool failures on different checks after one failed cure are different faults.
- Re-check H1: the run-wide budget per (check script, code) is its own constant, `KEY_BUDGET` 3
  (the per-stop cap stays `CURE_BUDGET` 2): a flaky check failing one cure in each of two far-apart
  rounds is not stop 4, a third failure is. A cure attempt is numbered per stop.
- Redo lineage: `scope.py` records `_meta.redo_of` (the open stop's set-aside round) in TARGET.json;
  `--verify` ignores it; a redo closes only on such a round, covering the set-aside scope with its
  lanes run; another code Y on the fresh round charges Y; unreadable lineage is the human's.
- STOP.json records `mode`; an operator close of a stop opened in release is a trail fault.
  A closer's `--project` is dropped only when it names this project.

### One cure table and real closers (U2 B1a, 2026-10-22)
- **Release:** `project.RELEASE` is one table `{code: (class, kind)}`; the kinds are rerun, restore,
  redo, reprove, human and disclose, and `open` prints `CURES[kind]` plus the code's own text
  (`_CURE_OF` and the special cases of `cure_plan` and `close --cured` are gone). RUN.md's failure
  table has a generated release column, checked by `tests/doclint.py`.
- **Release:** a stop's check is a read-only FORMS command (a build command is refused; Phase 0
  read-only checks the build); `open --note` needs `--check <the read-only check of the step that
  failed>` except for a human code; a `--note` cause that is no cause code is refused (an uncoded
  failure is `--cause unknown-retry`, now self-cured with its `--check`); `close --delegated` is
  dev-only. `tool-call`, `git-error` and `lane-output` are self-cured reruns instead of human stops.
  The cure kinds were renamed in new CLOSED.json records (`set-aside` -> `redo`, `restore-pin` and
  `revert` -> `restore`; `revert` now needs a stop of kind restore).
- **Both modes (dev-reaching):** `project.py --deliver` re-runs `deliver_blocking` in dev too
  (integrity, fingerprint once something is approved, Phase 0 read-only, each self-cured stop's
  check) and refuses on any failure. Dev is otherwise unchanged: no self-cure, `--delegated` kept,
  every class waits.
- Tests: an L1 selftest closes a stop of every code x mode x level (real integrity check with the
  stop open), and the snapshot replay re-runs each passing closer gate with a stop open.

### B1a review fixes (2026-10-22)

- Release: a `--note` stop of a code with a closer of its own records exactly that closer (H-1);
  `--deliver` also re-runs those closers. A redo stop whose round its self-cure set aside closes on
  the fresh round (`redo_round`; addendum N5). `--delegated` records the mode; a release-mode
  operator close is a trail fault. `--cause tool-bug` without `--check` is a human stop (a pinned
  writer that keeps crashing). `lanecheck --kill` is no longer a check form. Docs: release retry
  route mode-qualified; interim closer rows marked; MAINTAINING S3/S4.

### Test harness for the U2 build (B0, 2026-10-22)
- Tier 1 runs the fast selftests under both run modes x the three levels; the new test switch
  `FORMALIZE_TEST_MODE` is honoured only by `--selftest` processes (a real run keeps its
  config's mode). Tier 2 adds `tests/snapshot_replay.py`, which replays the mini1–5 run snapshots
  through the read-only gates in every mode x level against `tests/replay_baseline/`. No change to
  what a run does.
- The snapshot replay prefers the full snapshots (both git repositories): the runs' real history is
  replayed, and the recorded project path (under the test machine's home directory) resolves to the copy through
  a private mount namespace (no byte of the record rewritten; any other path still fails). The
  baselines were re-recorded (all rows: the lanecheck `PROBLEM[auth-metadata]` and
  `RED[dependencies]` artefacts of the synthetic history are gone).

### Run mode: release and dev (2026-10-21)
- **One codebase, two modes (`mode` in the config, set at install).** `release` is the default. It
  stops a run only for faithfulness, proof validity, integrity and the human stops. A finding of
  presentation or bookkeeping prints `DISCLOSED[<code>]` and does not fail its check. That covers
  report rendering, PDF, line citations, reader-gate findings, record formats, part labels,
  docstrings and the log's round list. It also covers a self-test failure or crash of a script
  that serves only those. `stops.py disclose` records it. The report's "Run mode" row and stop
  list, DECISIONS.md's box and `deliverables/KNOWN_FAULTS-run.md` list every one.
  `install.sh --dev` keeps every stop.
- The classifier is `project.RELEASE`. CLASSIFICATION.md gives a class to every place that can
  stop a run. The three stops of the first small-paper run (S1-S3) would have been disclosed
  under `release`. Mutants RM-1..RM-25 check that no F/P/I/H check becomes non-blocking.

### Guarantee changes approved by the approver (2026-10-20)
- **A lane's mention of a record file is a note, not a stop (A1).** lanecheck prints
  `NOTE[independence]`, and the adjudication commit refuses until each note is settled in
  ADOPTED.md. A mention is settled by a `CLEARED <lane file>: <reason>` line or by a whole-lane
  re-vote. A path into another round, or into another lane's verdict or probes, needs a whole-lane
  re-vote and cannot be cleared. Such a path is now caught; a lane citing a sibling's probe
  directory used to pass. Clearances have their own report section.
- **Lane mistakes are re-voted, not stops (A2/A3).** These cases are sealed, recorded in the seal
  and reported as `NOTE[lane-fault]`, and the adjudicator orders a re-vote: a cited probe that does
  not exist, a probe directory that differs from the lane's manifest, or no manifest. Only a change
  after the seal commit counts as tampering (`PROBLEM[evidence-after-seal]`). If a re-vote lane
  itself makes a mistake, its row is left open for the person.
- **A human waiver for an ownership failure (A5b).** `integrity.py --acknowledge <commit> --stop
  S<n>` is allowed only for a commit that added files, and only on a stop the person closed. The
  report's first page lists every waiver.
- **A failure with no cause code is retried, then classified (approved 2026-10-20).** It is no
  longer a stop as such. The operator records it (`--cause unknown-retry`) and re-runs it within the
  retry budget. If it persists, a traceback from a pinned script in `audits/` is `tool-bug`, a STOP
  class; anything else is `env-unknown`, fixed as an environment fault and closable with
  `--delegated`. The scripts still treat an unrecorded code as a stop.
- **The stall resolver is replaced by recorded stops and one `set-aside` command (A7).** See
  "Stops and set-asides" below.
- **Cached bytecode in `audits/` is a note (A10a).** It used to be an integrity failure; now
  `project.py --env-check` removes it. A sourceless or unchecked-hash `.pyc` still fails.

- **A non-goal result the operator cannot prove is left unproved and disclosed, not a stop (Q1 (b),
  2026-10-20).** Under a delegating level the operator keeps the statement byte-identical and
  unproved and logs `[DELEGATED <date>, operator under <level> (intake); reversal: re-prove] leave
  <decl> unproved — <reason>`. Phase 0 reads that line from the committed `RUN_LOG.md`: a `sorry`
  inside a declaration it names is `NOTE[unproved]`, any other stays `RED[sorry]`, and a goal
  result named there is refused (`RED[unproved-goal]`, a stop). The axiom sweep allows `sorryAx`
  for exactly those declarations, so every result whose proof uses one needs its own line. The
  adjudicator records each in `SKIPPED.md` ("Hard" stays no reason otherwise); `make_report.py
  --check` requires a "not formalized" index cell and that row, with the tag as "decided by",
  once a round has been adjudicated since the line. The report (coverage section and page-1 box)
  and `DECISIONS.md` disclose it as "stated, not proved". A goal result that stays unproved is
  still a stop; under `involved` nothing changes.
  After review: index names are resolved as the dependency walk resolves them (as written, then
  namespace ++ name), so a goal the index cites unqualified is still refused, and the sweep itself
  refuses a goal named in a leave line; the sweep's allowance under an exempt `X` covers only
  compiler-generated names (`eq_<n>`, `eq_def`, `eq_unfold`, `proof_<n>`, `induct`,
  `mutual_induct`) with no source range; "pending" is keyed on the declaration, and
  `project.py --deliver` refuses a result still pending (a line logged after the final diff round
  needs one more diff round); only a top-level line of `## Open questions`, `## Checkpoint C` or
  `## Answered` that begins with the tag counts; Phase 0 reads `set_option … in` / `open … in`
  declaration lines.
  After re-check: `decisions.py --check` (run before the completion message) refuses a result still
  pending, as `--deliver` does; the report lists every auxiliary the sweep accepted under an exempt
  name, with its parent (recorded in `DEPENDENCIES.json` by the walk, same rule); while a leave line
  is active a project `elab`/`macro`/elaborator attribute or `addDecl`/`addAndCompile` is
  `RED[unproved-meta]`; a leave line's anchor must be a real decisions anchor (`considered:` is not).

### Stops and set-asides
- `stops.py` records every stop with the raw output of the failing check and a cause code per
  failure line. `close --delegated` is refused under the involved level, for a STOP-class cause,
  and while the check still fails. The report lists every stop and who closed it.
- `stops.py set-aside` replaces abandoning a round or a re-vote lane. It commits every remaining
  file of the round or lane, by name, with an inventory computed by the script; nothing is deleted.
  Every Fail or Ambiguous item of the set-aside lanes is carried forward, and the next adjudication
  and the final report refuse until each has a row. Under a delegating level it refuses a round
  with a STOP-class cause unless the person closed that stop.
- **Structured cause codes (A9).** Every failure line starts with `KIND[code]`, and `project.CAUSES`
  gives each code its class. An unknown code, or a failure line without a code, counts as a stop
  (it fails closed). Normal states, such as nothing approved during a re-approval, are not stops.
- Smaller causes removed (A10). The tree_state git-config allow list takes exact keys and values
  only (submodule and git-lfs defaults). A project's extra glyph mappings are its own disclosed
  record (`signoff.py glyphs --add`), not an apparatus edit. The round name must match the full
  HEAD hash. `project.select` refuses a config with a hard error.
- `audits/tests/replay.py` replays the four live stops on the current design.

### Records
- **Commit at seal (A4).** `lane_auth.py seal` commits the lane's verdict and its probe files in
  one commit, by name. Sealing again is safe: it completes an interrupted seal, and a lane already
  sealed gets its existing seal commit back. A lane has one seal, ever.
- **Every record is committed by name (A5); no instruction uses `git add -A`.** The adjudicator
  commits with `integrity.py --commit-adjudication`. The commands of `signoff.py` and `scope.py`
  commit what they write. Ownership rules carry a version: a run pinned earlier keeps the rules it
  started with.
- **Re-approval begins before the edit (A11).** `signoff.py reapprove --begin` records the Lean
  HEAD and the approved fingerprints before any statement is edited. The freeze check then reports
  a change to a listed declaration as `NOTE[reapproval]`, and any other change as a drift.

### Round-3 audit fixes (scripts)
- **An open re-approval fails the report check.** `make_report.py --check`, and so Phase 0's
  report step, fails while `REAPPROVAL.json` is open. The report lists every re-approval of the run
  (begun, declarations, reason, which `approve` closed it) in the trust table and under
  "Re-approvals during the run", and the trust row no longer says that no statement changed.
- **A REVOTE NEEDED row is not a re-vote.** A decision (ADOPT, REJECT, DEFER) that follows a
  REVOTE NEEDED row counts only once the re-vote lane for that item (or the whole lane) is sealed
  or set aside, and only in an "adjudicate R revotes" commit after that seal. A carried Fail whose
  last row is a REJECT needs the same. A lane fault is settled by a REVOTE NEEDED row for each item
  whose verdict cites the faulty probe, not by a row for another item of the lane.
  `tests/round3.py` keeps the round-3 attacks as self-tests.
- **A re-vote lane is held to more than a first-pass lane.** It runs while its round's ADOPTED.md
  holds the adjudicator's reasons, so a path into its own round (other than its own files) is
  `NOTE[independence-path]`, and none of its notes can be cleared: its row is left open for the
  person.
- **The settle check runs on the committed record too.** `integrity.py --check`
  (`FAIL[unsettled]`) and `make_report.py --check` check every adjudicated round's NOTEs, lane
  faults and re-vote decisions, so an ADOPTED.md committed by hand as "adjudicate R" does not
  bypass the check of `--commit-adjudication`.
- **One parser for decision cells** (`project.decision_of`). The carry check, the settle check, the
  re-vote list and the report read a decision cell alike: backticks, italics and bold are
  formatting, struck-through text is dropped, and a cell that does not open with a decision is
  refused at adjudication.
- **A waiver is bound to its stop.** `integrity.py --acknowledge C --stop S` needs a stop recorded
  with `--cmd` on the integrity check while it printed `FAIL[ownership]` for commit C (the message
  now names the commit), closed by the person; one waiver per stop. A commit that adds a record
  another check reads (a set-aside marker, a seal, ADOPTED.md, a stop or waiver, an approval, a
  reader's report, ...), or lane evidence its lane's seal did not record, is never waived.
- **`set-aside --lane` refuses a sealed re-vote lane with no fault of its own**: it is settled by
  "adjudicate R revotes", not set aside.
- **`lane_auth.py reissue` rolls back a failed commit** (a stale `index.lock`): the verdict, its
  probes and the token commitment are restored, so the reissue runs again after `stops.py
  repair-lock` instead of leaving a tamper-class state.
- **Interrupted record commands can be re-run.** `stops.py open` and `close` first commit a stop
  file left uncommitted by a kill; `set-aside` completes a marker whose inventory still matches,
  or starts again when the marker was cut short; `integrity.py --acknowledge` writes an
  uncommitted waiver again.
- A lane naming another round by its commit hash ("round 0b23c87") is `NOTE[independence]` again
  (the simplification had dropped it).
- **A carried Fail is settled only by a row about it**: a row of the carried lane whose verdict
  cell is the carried verdict (ADOPT, DEFER, QUESTION), a REVOTE NEEDED row, or a decision after
  the re-vote ran. A fresh lane's Pass, or another lane's row, does not settle it.
- `stops.py repair-lock` is recorded in the stop record (`stops/repairs/R<n>.json`, committed as
  "stop repair R<n>"), and the report lists it with the stops.

### Round-3 audit fixes (instructions, docs, axiom sweep)
- The instructions describe the round-3 rules where the operator meets them: an open re-approval
  must be closed before delivery (RUN.md, `reapproval.md`, Stage 5); a REVOTE NEEDED row settles
  its item only through the re-vote adjudication after the re-vote lane's seal, and the settle
  check also runs in `integrity.py --check` and `make_report.py --check` (Stage 4, adjudicator
  prompt); a re-vote lane's NOTE is LEFT OPEN, never CLEARED; decision cells open with the bold
  decision; a waiver needs a stop recorded with `--cmd` on the integrity check, one per stop,
  report records only; `set-aside --lane` refuses a re-vote that can still be settled; a reissue
  runs again after `repair-lock`; interrupted stop, set-aside and waiver commands are re-run.
- A result you cannot prove is never removed or weakened under a delegating level, except missing
  theory as a named hypothesis (failure table, Stage 3). A statement change at Stage 5 under
  `statements-only` is a stop. RUN.md rule 2 names the escalation prompt as its one exception;
  rules 4 and 5 list every owned record and commit prefix. The document-check exception is
  recorded as a stop and closed delegated. Smaller wording fixes (`approve` commits itself,
  Checkpoint A under `hands-off`, the Checkpoint B question verbatim under Codex, literature
  hypotheses under `statements-only`, committing by name at delivery, INSTALL's denied edits).
- Test-run mentions are generic everywhere (code comments, fixtures, mutant names). `NOTICE`
  lists every adapted source `AUDIT_PROTOCOL.md` names.
- `axiom_sweep.py --selftest` matches the sweep's messages as whole lines (a miscount such as
  "11" for "1" is caught), exercises the module rule on an imported temp module with a root-level
  `sorry` (mutants X14, X15), and labels the fallback check by what failed.

### Round-3 re-check fixes (R3c)
- **A re-vote lane that was set aside never counts as the re-vote having run** (never spawned,
  crashed, unsealed or `--unsealable`): no ADOPT, REJECT or DEFER of its item after the REVOTE
  NEEDED row is accepted; the item stays open for the human (an unsettled re-vote in DECISIONS.md
  and the report), and the Fails the set-aside lane carried are settled by that open row.
- **An interrupted set-aside is never committed as found**: running `set-aside` again recomputes the
  marker after every refusal (an adjudicated round, an unsealed lane, a STOP-class cause under a
  delegating level, ...) and commits the uncommitted marker only when it equals the recomputed one;
  otherwise it refuses, leaves the file, and prints the recovery (remove it, run again). A
  whole-round set-aside refuses an uncommitted re-vote lane marker in the round.
- **An interrupted stop is never committed as found**: `open` and `close` recompute an uncommitted
  STOP.json (a `--cmd` stop: the check re-run, its exit, output and causes; refused if it passes
  now) or CLOSED.json (the re-run and every `--delegated` refusal) and commit it only when equal;
  a `--note` stop keeps the operator's note and cause code. `integrity.py --acknowledge` refuses a
  stop whose STOP.json or CLOSED.json is not committed.
- RUN.md lists "a result that stays unproved and is not missing theory" among the stops that
  remain at every level (the current behaviour).
- Self-tests from the re-check attacks (tests/round3.py, N1-N3) and mutants R3c-1a..3c.
- **R3d (final check F1-F3): a re-vote settles an item only when it is THE re-vote of that item**:
  its sealed verdict has an entry for the item (a whole-lane `--ALL.k` of another batch part never
  judged it); when more than one sealed re-vote judged the item, none is chosen (no sort order) and
  the item stays open for the human; an item whose re-vote was set aside stays open for the human
  even after a later item or whole-lane re-vote. Self-tests t_r3d (attacks3 V9, V7, V6, with
  controls) and mutants R3d-1..3.
- **R3e (narrow review H1, M1, M2, L1-L3): one strict reader of ADOPTED.md decision rows**
  (`lanecheck.decision_rows`), used by the settle check, the re-vote rules, the carried-item check,
  and the open re-vote, question and UNCOVERED lists: the lane cell must be exactly one lane name of
  the round and the item cell exactly one scope item (only surrounding spaces, emphasis and
  backticks ignored); any other row is refused by the adjudication commit, `integrity.py --check`
  and `make_report.py --check`. Open re-votes are keyed by (lane, item) and settled only by a row the
  re-vote rules accept; a re-vote entry counts only with a Pass/Fail/Ambiguous verdict and one entry
  for the item; an unsealed re-vote covering the item blocks its decision; a `(whole lane)` row is
  settled once its whole-lane re-vote settled the lane's items; `--ALL.k` covers only its part's
  items; a set-aside `--ALL*` marks its row abandoned. Self-tests t_r3e, mutants R3e-1a..7.
- **R3f: an UNCOVERED row may name any declared item of the project.** The strict reader's item
  names are the round's TARGET.json items, carried items, `(whole lane)` and every declared item of
  the project (`lanecheck.project_items`: the index file's row labels, the declarations' full names,
  and every name a round's FINGERPRINTS.json keys), so an UNCOVERED row for a NotDoneYet index
  entry or a STALE PASS is accepted; matching stays exact. `audit_coverage.read_adopted` reads a
  record pinned under ownership 2 or later through `lanecheck.decision_rows`, and keeps its
  best-effort reading only for older records (no pin, or ownership 1). Self-test t_r3f, mutants
  R3f-1a..2b.
- **R3g (narrow X4, junk entries): lanecheck validates every lane verdict file's schema.** The file
  must be one JSON object, its `verdicts` a list, and every entry an object with a non-empty
  `item` and a `verdict` of Pass, Fail, Ambiguous or NotDoneYet. A violation is
  `NOTE[lane-fault]` for that lane and covers all its items: an original lane needs a REVOTE
  NEEDED row for every item it names (a whole-lane row when an entry names none). A re-vote lane's
  violation means it validly judged nothing: its row stays open for the human (LEFT OPEN), and no
  decision can follow it. Before this change, a sealed re-vote with one valid entry beside
  non-object entries licensed the REJECT. Self-test t_r3g, mutants R3g-1..3.

### Deferred (round-2 proposal, group G)
- G1 (planted-fault benchmark for the faithfulness lanes) and G2 (hands-off smoke test without a
  resolver) are later test material: they run on the planned small test paper, after this release.
- G4 (a reader's re-found `unfixable` finding counts as answered): deferred; it changes what blocks
  a document and needs its own review that it cannot hide a new finding.
- G5 (one standing question per hypothesis and declaration): deferred; it needs a stable key (the
  declaration fingerprint) in the adjudicator's template and in `audit_coverage.py`.
- G6 (statements-only fixtures, a stop before and after Checkpoint B): deferred; the level has not
  run yet, and the small-paper test is the first source for realistic fixtures.
- G7 (records cite Lean names, generators render the lines): deferred; it changes the format of
  every adjudicator-owned record and of the generators.
- G9 (`git push --dry-run` at intake): deferred; a blocked push is already a remaining stop.
- G8 (a lighter round for docstring-only diffs after Checkpoint C): not now; it reduces audit
  coverage, an approver decision.

### Instructions
- **RUN.md is an always-read core of about 2.8k words** (it was 14.8k). The rest moved to one file
  per stage, plus procedure files, under `audits/run/`. `project.py --stage` names the file to
  read, and also does so on resume. The operator no longer reads AUDIT_PROTOCOL.md, and neither do
  lanes or readers: the verdict schema is inline in their prompts.
- **One failure table**, keyed by cause class. A `sorry` is the author's work in progress, not a
  stop. A mechanical retry gets a time budget (up to 2 hours) instead of "once more". Usage limits
  and capacity errors are waited out.
- **A script prints the intake** (`prompt.py --intake`). The operator sends it unchanged, as one
  message, and the first pin checks its hash.
- The adjudicator's prompt is self-contained, and re-votes have their own prompt. Under Codex the
  escalation check runs as the role `formalize_escalation`, the sixth role. The by-hand mode is
  dropped.

### Report, sign-off sheet and decisions (from a test run's audit)
- The report states verifiable facts about the order of work: when the statements were committed,
  when they were approved, and that they are unchanged since. It never claims that the statements
  came "before any proof was written". Proofs may be drafted aside once the statements are
  committed.
- New report sections: the decisions taken after the intake, every `[DELEGATED]` decision in full,
  every stop of the run, set-asides and clearances, and the proof routes. The proof-routes section
  includes the results the goals do not use, from a new dependency walk (`dependencies.py`, checked
  in Phase 0). Global differences are defined in the report, and unsettled re-votes are listed with
  the open questions.
- The sign-off sheet has a background section, a legend, the paper's `tex l.N` for each result and
  `File.lean:N` for each Lean name.

### Scripts and tests
- Rounds are ordered by Lean ancestry, in one place (`project.order_rounds`). Shared helpers have
  one home (`project.py`): the Lean runner, LaTeX, the index file and the table-row splitter. One
  script registry (`project.SCRIPTS`) feeds selftest_all, the allow list, the mutants and the
  watchdog.
- `check_index.py` is merged into `make_report.py --check --index-only`. The DEPENDENCIES.json check
  moved to Phase 0. The watchdog moved to `codex/`. Dead options were removed.
- Three test tiers (`audits/tests/tier.py 0|1|2`; see `audits/tests/TIERS.md`). Self-tests have a
  no-PDF mode, which a real run refuses. Mutants have a kind (plain, pdf, lean, codex). The doc-lint
  has its own script (`audits/tests/doclint.py`).
- `axiom_sweep.py --selftest` asks each negative control and main() for the sweep's own error message, not just a non-zero exit; its synthetic target lives in the system temp dir; the fallback shows the project's own sweep errors (mutants X7-X13).

### Documentation and release
- README, INSTALL and the other docs name the version only through `VERSION`. README says what to
  read: README, then INSTALL, then a run. It credits Trellis and states the licence of the parts
  adapted from it (new `NOTICE`; `CITATION.cff` lists both licences). The track record is updated.
- The deliverables of the test run on a public paper were removed from `examples/`. The raw Codex
  test evidence, the live Codex test harnesses and the Codex test report (`codex/SUBAGENTS_REPORT.md`)
  left the tree; they are kept privately. `codex/README.md` (History) summarizes the reference run.
- KNOWN_LIMITATIONS loses the items fixed since 0.2.0.
- The agent spawns lanes in waves of at most 8, fewer on less memory or on request, and waits
  for `signoff.py approve`, which can take many minutes.

### Removed
- The stall resolver (`resolve.py`, its prompt, the Codex role `formalize_resolver`,
  `codex_spawn.py --kind resolver`), lane supersede and seal generations, and the resolver caps.
  It was added and removed within 0.3.0-dev and never released.
- `check_index.py`, `prompt.py --missing`, `fingerprint.py --snapshot` and `--approve`.

## 0.2.0 (release date: the date of the v0.2.0 tag)

Two features, the fixes found by testing them, and the fixes from three independent pre-merge
reviews (protocol, code with adversarial tests, newcomer documentation).

- **Involvement levels.** An intake question (5c) chooses `involved` (the default), `statements-only`
  or `hands-off`. Delegated decisions are final and tagged `[DELEGATED …; reversal: …]` in
  `RUN_LOG.md`. They follow the adjudicator's recommendation, or else the most conservative choice
  that stays with the paper. The decisions document ("Decisions taken on your behalf"), the report
  and the sign-off sheet disclose the level, quote the intake answer and list every delegated
  decision. Some stops remain at every level.
- **Codex built-in reviewer subagents** (experimental). Reviewers run as fresh built-in Codex agents
  from roles that `audits/codex_agents.py` generates from the same reviewer body Claude uses.
  `codex_spawn.py` stays as a fallback that fails closed.
- **Lane attribution, Claude and Codex.** Each lane gets a spawn-only token, and the owning reviewer
  returns the digest of its verdict, which `lane_auth.py seal` commits. lanecheck and the
  adjudicator check tokens and seals.
- **Unattended runs in Claude Code.** The installer adds exact allow rules, edit rules for what the
  run writes, deny rules for the pinned apparatus, and `PYTHONDONTWRITEBYTECODE=1`. The protocol's
  own steps then ask for no permission. Helper drafts, scratch directories, the source compile and
  the delivery copy go through `project.py`, inside the project.
- `tree_state.py` records git hooks and command-running git config and flags any change. The
  installer refuses before writing anything. The optional Codex watchdog only notifies.
- Fixes: a docstring belongs to the declaration below it (a docstring-only change used to scope a
  neighbour). The report's open questions are cumulative across rounds. A question asked again
  after a delegated decision returns. Every xelatex call runs with `-no-shell-escape`.

## 0.1.0 (2026-10-18)

First public release. The protocol and scripts had been used on five papers before this release
(see README, "Track record").

- `install.sh` installs into any Lean project that requires Mathlib, or into a clone of Mathlib.
  `examples/sparse-note/` is a ready-to-build fixture.
- `readers.py --save` saves a fresh reader's record through the script, which checks and commits it.
- The project setting `work_dir` gives the proof helpers a persistent directory (never `/tmp`).
- The report gained sections for open questions and standing defers, an optional notation
  glossary, and the location of every cited Lean name.
- `selftest_all.py` works before the first project exists. `tests/mutants.py` checks that each
  self-test passes on the unmutated code before it judges the mutants. The axiom sweep's self-test
  runs a positive control first.
- Experimental Codex CLI support (`install.sh --codex`, `codex exec` per subagent).

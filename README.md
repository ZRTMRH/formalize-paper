# formalize-paper

**Formalize a math paper in Lean 4 with an audit trail from separate-context AI reviewers:
single-criterion reviewers, a defect record, and a statement sign-off sheet.**

Version 0.2.0 (see [`CHANGELOG.md`](CHANGELOG.md)).

**This is version 0.2.0, kept for reference**: it is the version cited by Le, Shi and Wei,
arXiv:2610.28271. The current version is 0.3.0 (tag `v0.3.0`). For the public release this tree
was cleaned: raw test-run logs, the deliverables of a test run and an internal investigation log
were removed; the code is otherwise as released.

**Credit.** The one-criterion-per-reviewer design and the wording of three reviewer rubrics are
adapted from Wes Pegden's [Trellis](https://github.com/wpegden/trellis) (arXiv:2606.09674). Those
parts are under the PolyForm Noncommercial License 1.0.0, the rest under Apache-2.0: see
"License" below and [`NOTICE`](NOTICE).

formalize-paper is a [Claude Code](https://claude.com/claude-code) skill plus an *audit
apparatus*: a written protocol and about twenty Python scripts. In one conversation, an AI agent
formalizes a mathematics paper in Lean 4 and Mathlib, and separate AI reviewer agents, which did
not write the code, audit the formalization. A person approves the setup, signs off the
statements (or chooses at intake to let the agent do it), and receives the results.

It is tuned for Claude Code. Support for the OpenAI Codex CLI is experimental
(see [`codex/README.md`](codex/README.md)).

## What you get

- **The Lean formalization**, on a git branch of your Lean project: every in-scope definition and
  numbered result of the paper. A literature result the paper only cites is taken as an explicit,
  named hypothesis, never as an axiom.
- **`REPORT.pdf`**, the audit report. Page 1 has a "read this first" box listing defects in the
  paper, statements that are true only vacuously (because their hypotheses can never hold), results not formalized, and failing proof routes.
  The rest says how far to trust each layer of checking, what the formalization assumes, which
  results are covered, where the Lean proof differs from the paper's, the open questions, and where
  every cited Lean name is.
- **`SIGNOFF.pdf`**, a statement-by-statement sign-off sheet. For each result it shows the paper's
  statement, a plain-English reading of the Lean statement, and every known difference between the
  two, so that the approver can check the statements before any proof is written.
- **`DECISIONS.md`**: every decision only a person can make, each with its context, the options and
  a recommendation. The approver's answers are recorded verbatim in the run log (`RUN_LOG.md`,
  under `## Answered`); a later `DECISIONS.md` lists them as previously answered instead of asking
  again.
- **Defect records** in the audit record: suspected errors in the paper, each with a Lean witness
  where one could be built (the Lean kernel checks the witness; whether it captures the paper's
  error is a reviewer's judgment); the results not formalized and why; and the places where the
  proof route differs from the paper's.
- **The audit record itself**: a separate git repository holding every reviewer's raw verdicts, and
  the adjudicator's decision on each, round by round.

## What is distinctive

- **One criterion per reviewer.** Each reviewer holds exactly one criterion (substantiveness,
  correspondence to the docstring, faithfulness to the paper, non-vacuity, prior art). It starts
  without the conversation's context, with only its prompt and the files on disk (plus whatever
  background Claude Code gives every subagent, such as the user's memory index, which the prompt
  tells it to disregard), and is instructed not to read the other reviewers' work or earlier
  rounds. That is an instruction, not an access control: scripts
  (`lanecheck.py`, `tree_state.py`) check afterwards that no reviewer cited the record or wrote
  into the project.
- **Probes are re-run.** An adjudicator (another AI agent, which did not write the code) decides
  each failed check. It
  re-runs every Lean probe a reviewer cites before accepting the finding.
- **Statements first, then frozen.** The statements are written with `sorry` proofs and signed off
  before any proof is written. Content fingerprints then freeze them: a change to an approved
  statement is detected by the Phase 0 check.
- **Fresh readers gate the documents.** The report and the decisions document reach the approver
  only after a fresh reader (another AI agent, with no context of the run) has read that exact
  version. Every blocking finding any reader
  raised must be answered: fixed, dismissed with evidence, or declared unfixable in a notice shown
  to the approver.
- **Mechanical checks back the judgments.** A Phase 0 gate runs before every round and before the
  report. It checks that the Lean builds; that, once the proofs are written, there is no `sorry`
  and only the standard axioms are used; that approved statements are unchanged; and that the
  index of results is internally consistent.
  Every checking script has a self-test, and a mutation suite checks that the self-tests notice the faults
  they claim to catch.

## Requirements

- Debian or Ubuntu, or Ubuntu under WSL2, with `sudo` for the packages (other Linux distributions
  and macOS are untested).
- About 8 GB of disk per Lean project plus about 3 GB for TeX; 16 GB of RAM at least (with smaller
  reviewer waves), 32 GB recommended.
- `git`, Python 3.10 or newer, and Lean 4 through [`elan`](https://github.com/leanprover/elan).
- A Lean project that requires Mathlib (a standalone Lake project, or a clone of Mathlib itself).
- For the PDFs: XeLaTeX with `texlive-latex-extra`, the DejaVu and FreeFont fonts, and `pdftotext`
  (`poppler-utils`).
- Claude Code, logged in. A run spawns many subagents; a Max subscription is the practical minimum.
  For scale, one measured Claude Code run (the L∞ permutation-removal paper in "Track record",
  67 numbered results, 30 pages, Claude Opus 5.5, a 24 GB RAM machine): about 16 h of model activity over
  2 days of wall-clock time, most of the rest waiting for the approver, with one session usage limit
  reached and waited out. A short paper needs much less; this is not an estimate for yours. The
  Codex test run on the one-page example took 9 h 34 min including stalls. The Codex CLI is
  optional and experimental.

## Install and first run

Follow [`INSTALL.md`](INSTALL.md): it covers the requirements above and how to create a Lean
project if you do not have one. Once those are in place, the install is:

```bash
git clone https://github.com/ZRTMRH/formalize-paper ~/formalize-paper
~/formalize-paper/install.sh ~/my-formalization        # your Lean project's root
cd ~/my-formalization && python3 -B audits/selftest_all.py --fast
claude        # then type /formalize-paper
```

[`examples/`](examples/) has an example project to try (a synthetic one-page note, ready to
build) and the report and sign-off sheet of a real run.

## How a run goes

The run is one conversation. It stops and waits for the person at three checkpoints, and
otherwise only when it needs a decision only a person can make:

- **Checkpoint A**, after the intake questions: the setup on one screen. This includes the scope,
  which literature results are taken as hypotheses, and the budget.
- **Checkpoint B**, when the statements are written: `SIGNOFF.pdf`, to approve, to reject in part,
  or to let the agent approve. If the agent approves, the report says so.
- **Checkpoint C**, at the end: `REPORT.pdf` and `DECISIONS.md`. Under the two delegating levels
  below, the run delivers both at the end and does not wait.

An intake question sets how involved the person stays. *Involved* (the default) is the above.
*Statements only*: the person approves the statements at Checkpoint B, and the agent takes every
later decision. *Hands-off*: the agent also decides at Checkpoint B, and the run finishes without
asking anything after Checkpoint A. The agent then follows the adjudicator's recommendation (a
reviewing agent's, never its own), or else the most conservative choice that stays with the
paper. Each such decision is tagged `[DELEGATED]` in the run log with what reversing it would
cost, and the report and the decisions document list it and say that no person reviewed it.
Pushing or contacting the authors unless authorized at intake, integrity failures, a goal result
that looks false or unprovable, and a machine problem only the person can fix (a login, more
quota) still stop the run at every level. Hands-off removes the checkpoints, not the need for
someone to restart the session after a usage limit. In Claude Code, the protocol's own steps ask
for no permission (INSTALL.md, "Permissions"); copying the deliverables outside the project,
deleting a stray file, and a command the agent improvises outside the list still ask. Without a person at Checkpoint B, every judgement that a Lean statement says what
the paper says rests on the AI reviewers.

Between checkpoints the agent writes Lean and runs *audit rounds*. In each round, the reviewers
examine the Lean, and an *adjudicator* (a separate agent that did not write the code) decides
every failed check: adopt it (fix), reject it, defer it, or put it to the person as a question.
The agent then implements what was adopted, and logs every step. A session that ends early resumes where it stopped. The full
procedure is [`audits/RUN.md`](audits/RUN.md); the reviewers' criteria and the record formats are
in [`audits/AUDIT_PROTOCOL.md`](audits/AUDIT_PROTOCOL.md).

## Track record

The protocol and scripts were used by one team on five papers before the 0.1.0 release, with these
results:

- **Le, Shi and Wei, "A Complete Dichotomy for L∞ Permutation Removal"** (arXiv:2610.28271; the
  formalized version had 67 numbered results and 30 pages): run to completion and delivered,
  before the paper was public. The Lean formalization is public at
  [github.com/ZRTMRH/le-shi-wei-linf-lean](https://github.com/ZRTMRH/le-shi-wei-linf-lean) (v1.0).
- **A public arXiv paper, chosen at random as a test**: run through Checkpoint C.
- **Two further public arXiv papers**: one formalized before the protocol existed, then audited
  under it (its statements have not been signed off); one with its main theorem formalized and
  early audit rounds.
- **A synthetic test note**: used to calibrate the statement phase; it is now the example project
  (`examples/sparse-note`) and the test fixture. The Codex test runs of 0.2.0 were on this note.

Whether a person signed off the statements of a run is stated in that run's report (page 1 box
and trust section). The reviewers'
verdicts are AI judgments throughout; no result above is claimed to have been checked line by line
by a person.

## Limitations

Only the Lean kernel and the mechanical checks give proofs. The reviewers' verdicts and the
adjudicator's decisions are judgments by AI models. The protocol states what it does not check
([`audits/AUDIT_PROTOCOL.md`](audits/AUDIT_PROTOCOL.md), "What this protocol does not cover"),
and the known problems of this version are in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).
What the installer changes on your machine, and how to undo it, is in INSTALL.md, "Uninstall".

## Citing

See [`CITATION.cff`](CITATION.cff); GitHub shows it as "Cite this repository".

## License

Apache-2.0, the license of Lean and Mathlib (see [`LICENSE`](LICENSE)), **except** the parts
adapted from Trellis: the substantiveness, correspondence and paper-faithfulness rubrics (Lanes
A–C of `audits/AUDIT_PROTOCOL.md`) and the reviewer prompts cut from them. Those parts are under
the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0),
with this notice:

Required Notice: Copyright (c) 2026 Wesley Pegden.

Commercial use of those parts needs Wes Pegden's permission. [`NOTICE`](NOTICE) lists the files
and sections concerned.

# formalize-paper

**Formalize a math paper in Lean 4 with AI agents. Separate AI reviewers then check that the Lean
says what the paper says. You get a statement sign-off sheet and a record of every defect the run
found.**

The version is in [`VERSION`](VERSION); what changed is in [`CHANGELOG.md`](CHANGELOG.md).
0.3.0 is the current version. The L∞ permutation-removal paper (Le, Shi and Wei, arXiv:2610.28271)
cites version 0.2.0, which is kept as tag `v0.2.0`.

**Credit.** The one-criterion-per-reviewer design and the wording of three reviewer rubrics are
adapted from Wes Pegden's [Trellis](https://github.com/wpegden/trellis) (arXiv:2606.09674). Those
parts are under the PolyForm Noncommercial License 1.0.0; the rest is under Apache-2.0. See
"License" below and [`NOTICE`](NOTICE).

formalize-paper is a [Claude Code](https://claude.com/claude-code) skill plus a written protocol
and about twenty-five Python scripts. Everything happens in one Claude Code conversation:

- An AI agent formalizes a mathematics paper in Lean 4 and Mathlib.
- Separate AI reviewer agents, which did not write the code, audit the formalization.
- You approve the setup and sign off the statements, or choose at the start to let the agent sign
  them off. Then you receive the results.

How often the run waits for you depends on the involvement level you choose (see "How a run goes").

**Linux only**: Debian or Ubuntu, or Ubuntu under WSL2 on Windows. macOS is not supported yet (the
tool reads Linux's `/proc`, and its install steps use `apt`). On a Mac, use an Ubuntu virtual
machine (e.g. UTM or Parallels) or a Linux server over SSH.

It requires Claude Code. Support for the OpenAI Codex CLI is included but **experimental**: one hands-off
run on a small synthetic paper completed end to end under Codex CLI 0.163.0, on a pre-release of this
version (about 12.5 h on a shared machine), and a person had to step in six times (four "Selected model
is at capacity" stalls on the provider's side, two sandbox approval requests). The fixes from that run
are included here, but Codex has not been re-run end to end on this exact version (see
[`codex/README.md`](codex/README.md)). For a real paper, use Claude Code.

**What to read.** This README, then [`INSTALL.md`](INSTALL.md), then start a run. You do not need
to read `audits/RUN.md` or `audits/AUDIT_PROTOCOL.md`: they are written for the agent. The known
problems are in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## What you get

Everything is delivered to `<project>/deliverables/`:

- `README.md`: start here. It lists the other files and, in its section D, the known faults of the
  delivered documents and the checksum of each PDF.
- `SUMMARY.pdf`, `REPORT.pdf` and `SIGNOFF.pdf`. Each comes with its markdown, and the markdown is
  the authoritative text.
- `DECISIONS.md`.
- `RUN_RECORD.md`: how the run went. It lists every stop, every fix the agent made to keep the run
  going, and every disclosed tool problem. It is written mainly for maintainers.
- `CITATIONS.md`, if it was produced: advisory notes on the paper's citations.

In more detail:

- **The Lean formalization**, on a git branch of your Lean project. Every in-scope definition and
  numbered result of the paper is stated in Lean. Each is proved, proved from a named hypothesis,
  or listed with the reason it is not. A result left unproved is always disclosed, and a goal
  result is never left unproved. A literature result the paper only cites is taken as an explicit,
  named hypothesis, never as an axiom.
- **`SUMMARY.pdf`**, one page; read it first. It gives the goal result's status and the status of
  every numbered result. The statuses are: judged faithful by the AI reviewers, a defect in the
  paper, true only vacuously, not formalized, stated only, proved assuming a named hypothesis, a
  reading choice, and not established.
  - "Faithful" is the reviewers' judgement, not a proof. How often they miss a mismatch has not
    been measured ([`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md), T4).
  - It also lists the defects, proof slips and vacuous statements the run **found**. The run does
    not read the paper's proofs line by line, and it checks the paper's citations only when you ask
    for a library contribution. So a missing entry is not evidence that there is nothing to find.
  - It lists the assumptions and the stops, and the answers recorded as yours, each with the audit
    commit that recorded it. The answers themselves are in REPORT §9 and `DECISIONS.md`.
  - The other documents are its appendices.
- **`REPORT.pdf`**, the audit report (appendix A). It covers:
  - how far to trust each layer of checking;
  - what the formalization assumes, and which results are covered;
  - where the Lean proof differs from the paper's;
  - the open questions;
  - where every cited Lean name is.
- **`SIGNOFF.pdf`**, a statement-by-statement sign-off sheet. For each result it shows the paper's
  statement, a plain-English reading of the Lean statement, and every difference the run found
  between the two. You check the statements on it before any proof is merged.
- **`DECISIONS.md`**: every decision only a person can make, each with its context, the options and
  a recommendation. Your answers are recorded verbatim in the run log. A later `DECISIONS.md` lists
  them as previously answered instead of asking again.
- **Defect records** in the audit record:
  - suspected errors in the paper, each with a Lean witness where one could be built (the Lean
    kernel checks the witness; whether it captures the paper's error is a reviewer's judgement);
  - the results not formalized, and why;
  - the places where the proof route differs from the paper's.
- **The audit record itself**: a separate git repository holding every reviewer's raw verdicts and
  the adjudicator's decision on each, round by round.

## How far to trust a result

- **Checked by machine.** The Lean kernel checks the proofs. Scripts check the axioms used, and that
  the approved statements did not change afterwards. If one of these checks could not be run (a fault in the
  checking software itself, confirmed by a separate reviewer agent), the summary says so on its first
  page ("Not verified: …") and marks each affected result; it never claims the check passed.
- **AI judgement.** Whether each Lean statement says what the paper says, whether a reported defect
  is real, and whether a result is vacuous are all judged by AI reviewers. How often they miss
  something has not been measured.
- **Your part.** If you approved the statements yourself at Checkpoint B, faithfulness rests on
  your reading. Otherwise it rests on the AI reviewers. Have a mathematician read at least the
  riskiest entries on `SIGNOFF.pdf`.
- **Not checked:**
  - the paper's proofs, line by line;
  - its citations (usually);
  - deliberate tampering by the agent. The record shows that the files agree with each other, not
    who wrote what.

## What is distinctive

The one-criterion-per-reviewer design and the rubric wording come from Trellis (credit above). What
differs from Trellis is listed at the top of `audits/AUDIT_PROTOCOL.md`.

- **One criterion per reviewer.** Each reviewer checks exactly one criterion:
  - substantiveness;
  - correspondence to the docstring;
  - faithfulness to the paper;
  - non-vacuity;
  - prior art.

  A reviewer starts without the conversation's context. It has only its prompt and the files on
  disk, plus whatever background Claude Code gives every subagent, such as your memory index, which
  the prompt tells it to disregard. It is told not to read the other reviewers' work or earlier
  rounds. That is an instruction, not an access control. Afterwards, scripts look for reviewers
  that cited the record or wrote into the project. This detects such a breach; it does not prevent
  it, and it can miss a write that was undone before the check ([`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md)).
- **Probes are re-run.** An adjudicator decides each failed check. It re-runs every Lean probe a
  reviewer cites before accepting the finding.
- **Statements first, then frozen.** The statements are written with `sorry` proofs and signed off
  before any proof is merged. From then on, a change to an approved statement is detected by the
  mechanical check run before every round.
- **Fresh readers check the documents.** The sign-off sheet, the Checkpoint B questions, the report
  and the decisions document reach you only after a fresh AI reader, with no context of the run,
  has read that exact version. Every blocking finding must be answered: fixed, dismissed with
  evidence, or declared unfixable in a notice shown to you.
- **Mechanical checks back the judgements.** Before every round and before the report, a check
  confirms:
  - that the Lean builds;
  - that, once the proofs are written, there is no `sorry` (except in a non-goal result left
    unproved by a recorded, disclosed decision);
  - that only the standard axioms are used;
  - that the approved statements are unchanged;
  - that the index of results is consistent.

  Every checking script has a self-test. A mutation suite checks that the self-tests catch the
  faults they claim to catch (see [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md), T27, for mutants
  not re-run in this release).

## Requirements

- **System.** Linux only: Debian or Ubuntu, or Ubuntu under WSL2 on Windows, with `sudo` for the
  packages. Other Linux distributions are untested. macOS is not supported yet (the tool reads
  Linux's `/proc`, and its install steps use `apt`). On a Mac, use an Ubuntu virtual machine (e.g.
  UTM or Parallels) or a Linux server over SSH.
- **Disk and memory.** About 7 GB of disk per Lean project plus about 3 GB for TeX. 16 GB of RAM at
  least (with smaller reviewer waves); 32 GB recommended.
- **Software.** `git`, and Lean 4 through [`elan`](https://github.com/leanprover/elan). Python 3.10
  or newer; 3.11 or newer (or 3.10 with `tomli`) if you use `--codex`.
- **A Lean project that requires Mathlib**: a standalone Lake project, or a clone of Mathlib itself.
- **For the PDFs**, which agents render from the audited markdown: a TeX engine (for example
  XeLaTeX with `texlive-latex-extra`) or pandoc, and `poppler-utils` so the agents can look at the
  pages. The markdown is always delivered beside each PDF.
- **Claude Code on a Max plan**, logged in.
  - A run spawns dozens of reviewer agents and uses a large share of a usage window. A 30-page paper
    used about 16 hours of model activity and reached one session limit.
  - Several papers can run at once on one Max (20x) subscription, but they share its usage limits:
    with many runs in parallel, expect to hit the 5-hour session limit more often, and check that
    enough of the weekly limit is left before starting a long run.
  - A usage limit pauses a run; it does not break it (see "If Claude stops" below).
- **Time.** Plan on about 4–5 hours for a short paper (a few pages, about ten results). Plan on 1–2
  days for a paper like the 30-page L∞ paper (67 results). Add the time you take at the checkpoints.
  You do not need to watch the run between checkpoints.

## Quick install

The full steps, with explanations, are in [`INSTALL.md`](INSTALL.md).

```bash
# once: a Lean project that requires Mathlib (skip if you have one; INSTALL.md section 2)
cd ~ && lake +leanprover/lean4:v4.35.0 new my-formalization math
cd ~/my-formalization && lake exe cache get        # prebuilt Mathlib: minutes, not hours
git add -A && git commit -m "new project"

# install and check (about 5 minutes)
git clone https://github.com/ZRTMRH/formalize-paper ~/formalize-paper
~/formalize-paper/install.sh ~/my-formalization
python3 -B audits/selftest_all.py --fast           # last line: ALL SELFTESTS: ok
claude                                             # accept the trust dialog, then type /formalize-paper
```

[`examples/`](examples/) has an example project to try (a synthetic one-page note, ready to
build).

## How a run goes

The run is one conversation. It waits for you at up to three checkpoints:

- **Checkpoint A**, after the intake questions. You see the setup on one screen: the scope, which
  literature results are taken as hypotheses, and the budget.
- **Checkpoint B**, when the statements are written. You get `SIGNOFF.pdf`, and you can approve it,
  reject part of it, or let the agent approve. If the agent approves, the report says so.
- **Checkpoint C**, at the end. You get `SUMMARY.pdf`, `REPORT.pdf` and `DECISIONS.md`, and you
  answer the open decisions.

**Involvement levels.** You choose one at intake (question 5c), once, for the whole run:

| Level | Setup (A) | Statements (B) | Results (C) | Who decides everything else |
|---|---|---|---|---|
| involved (default) | you approve | you approve | you answer; the run waits | you |
| statements only | you approve | you approve | delivered; the run does not wait | the agent |
| hands-off | you approve | the agent approves | delivered; the run does not wait | the agent |

How the agent decides:
- A decision taken by the agent follows the adjudicator's recommendation, never the agent's own;
  failing that, it takes the most conservative choice that stays with the paper.
- Each such decision is final and tagged `[DELEGATED]`.
- Each is listed in the report and in `DECISIONS.md` as not reviewed by a person.

**Only an answer you type yourself in the Claude Code session counts as yours.** Some answers are
recorded as the agent's approval, and the summary and report then say that no person reviewed the
statements. These include:
- an answer relayed by another AI agent (a second Claude session, a script, an assistant acting for
  you);
- an instruction such as "approve whatever the reviewers accept".

**When the run stops for you.** In the default (release) installation, the run stops at every level
only for these four reasons:

1. **A goal result looks false or unprovable** as stated.
2. **An outward action you did not allow at intake**: pushing, publishing, or contacting the
   authors.
3. **Something only you can fix**:
   - a login, quota or payment;
   - administrator rights;
   - a change to your own files;
   - another program that keeps changing the project's files.
4. **A genuine ambiguity in the paper's meaning** that the reviewers cannot settle. You are shown
   the passage and the possible readings, and the run continues at your level once you answer.

**If Claude stops.** If Claude reaches a usage limit, or an API error ends its turn ("overloaded",
a network error), the run is paused, not stopped:
- Leave the session open.
- Type `continue` once the limit resets (the message says when), or after a minute for an API error.

If the session itself has ended, see INSTALL.md, "If the session ends".

**Release and dev installations.** `install.sh` installs in *release* mode unless you pass `--dev`.
- In release mode, the run stops only for the four reasons above. A fault in the run's own checks or
  bookkeeping is fixed by the agent with a fixed, logged step, or disclosed in `RUN_RECORD.md`.
- A *dev* installation stops for every such fault. It is meant for people changing the scripts and
  the protocol.
- The mode is fixed per installation.

Between checkpoints the agent writes Lean and runs *audit rounds*. In each round:
- the reviewers examine the Lean;
- the adjudicator decides every failed check: adopt it (fix), reject it, defer it, or put it to you
  as a question;
- the agent implements what was adopted and logs every step.

A session that ends early resumes where it stopped.

**Words used in these documents.**
- *Main agent* (the *operator* in the maintainers' files): the Claude session that writes the Lean
  and runs the protocol.
- *Reviewer* (*lane*): a separate AI agent that checks one criterion.
- *Adjudicator*: a separate AI agent, which did not write the code, that decides each failed check.
- *Round*: one pass of the reviewers plus adjudication. A *diff round* re-checks only what changed.
- *Phase 0*: the mechanical check run before every round and before the report.
- *Approver*: the person who signs off the statements (intake question 5d).
- *Pinned*: the run's scripts and settings, frozen for the rest of the run.

## Track record

The protocol and scripts were used by one team on five papers before the 0.1.0 release:

- **Le, Shi and Wei, "A Complete Dichotomy for L∞ Permutation Removal"** (arXiv:2610.28271). The
  formalized version had 67 numbered results and 30 pages. It was run to completion and delivered
  before the paper was public. The Lean formalization is public at
  [github.com/ZRTMRH/le-shi-wei-linf-lean](https://github.com/ZRTMRH/le-shi-wei-linf-lean) (v1.0).
- **A public arXiv paper, chosen at random as a test**: run through Checkpoint C.
- **Two further public arXiv papers**: one formalized before the protocol existed, then audited
  under it (its statements have not been signed off); one with its main theorem formalized and
  early audit rounds.
- **A synthetic test note**, used to calibrate the statement phase. It is now the example project
  (`examples/sparse-note`) and the test fixture. The Codex test runs (0.1.0 and 0.2.0) were on
  this note.

**A hands-off test on a pre-release build of 0.3.0.** Claude Code ran a short paper on a light
budget. It finished in about 4 hours. After Checkpoint A, a person was needed only at four stops,
about 19 minutes in all. All four came from the protocol's own bookkeeping, not from a problem in
the formalization. Version 0.3.0 addresses these causes.

**A hands-off run on 0.3.0 itself.** Claude Code ran the same kind of short synthetic paper (seven
numbered results, with planted problems) on the exact code of this release, in release mode at the
hands-off level. It delivered end to end in about 4 h 15 min, with no stop and no human input after
Checkpoint A. It reported the planted false lemma (with a Lean counterexample and the repaired form
proved), the vacuous statement, the slip in a proof and the stated-only conjecture, and proved the
goal theorem. This is one run on one small paper; time and behaviour on a long real paper will differ.

Each run's summary (`SUMMARY.pdf`) and its report's trust section say whether a person signed off
the statements. The reviewers' verdicts are AI judgements throughout. No result above is claimed to
have been checked line by line by a person.

## Limitations

Only the Lean kernel and the mechanical checks give proofs. The reviewers' verdicts and the
adjudicator's decisions are judgements by AI models. What the protocol does not check is in
[`audits/AUDIT_PROTOCOL.md`](audits/AUDIT_PROTOCOL.md), "What this protocol does not cover". The
known problems of this version are in [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md). In
particular:

- No end-to-end run has been made on 0.3.0 itself. The hands-off test ran on a pre-release build
  of it, and the long real paper ran on an earlier version.
- Without a person at Checkpoint B, whether each Lean statement says what the paper says rests on
  the AI reviewers alone.
- The permission list saves prompts; it is not a sandbox. Run formalizations in a dedicated
  account or on a dedicated machine (INSTALL.md, "Permissions").
- Codex support is experimental (above).

What the installer changes on your machine, and how to undo it, is in INSTALL.md, "Uninstall".

## Developing

Changing the scripts or the protocol (`audits/`)? Read [MAINTAINING.md](MAINTAINING.md) first. It
covers the protocol's invariants, the fix process and the review prompts. The test tiers are in
`audits/tests/TIERS.md`, and contributions are described in [`CONTRIBUTING.md`](CONTRIBUTING.md).

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

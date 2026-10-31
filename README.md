# formalize-paper

**Formalize a mathematics paper in Lean 4 with AI agents, and audit it with independent AI
reviewers. You get the Lean formalization, a statement sign-off sheet, and a report of every
defect the run found in the paper.**

formalize-paper is a [Claude Code](https://claude.com/claude-code) skill plus a written protocol and
a set of Python checks. A whole run happens in one Claude Code conversation. Version 0.3.1 is
current ([`CHANGELOG.md`](CHANGELOG.md)); the L∞ permutation-removal paper (Le, Shi and Wei,
arXiv:2610.28271) cites version 0.2.0, kept as tag `v0.2.0`; its formalization's
[`CERTIFICATE.md`](https://github.com/ZRTMRH/le-shi-wei-linf-lean/blob/v1.0/CERTIFICATE.md) shows
what a delivered run certifies.

It runs on Claude Code under Linux (Debian or Ubuntu, or Ubuntu under WSL2 on Windows). Support for the OpenAI Codex CLI is experimental: under Codex CLI 0.163.0
two hands-off runs have delivered on the current version, on Linux: the example note and a real 5-page
paper (about 4 h, the same outcome as under Claude Code). The citation check does not yet run under
Codex (planned). See [`codex/README.md`](codex/README.md).

**Credit.** The one-criterion-per-reviewer design and the wording of three reviewer rubrics are
adapted from Wes Pegden's [Trellis](https://github.com/wpegden/trellis) (arXiv:2606.09674); see
"License" below.

## Who it is for

A mathematician with one AI subscription (Claude Code; Codex CLI supported, less tested) and an ordinary
computer: 16 GB of RAM is enough; 8 GB also works, more slowly, if you ask at intake question 7 for one agent at a time: a real paper delivered
on a 2019 MacBook Air (dual-core 1.6 GHz Intel Core i5, 8 GB).
macOS needs the separate `macos` branch.
It checks whether a paper's statements are faithfully formalized and correct, with no need to read Lean, and
produces a report for the paper's authors:
- a sign-off sheet pairing each statement of the paper with a plain-English reading of its Lean, written by a
  reviewer who sees only the Lean, with every difference spelled out;
- defects proved in Lean and classified by kind (typo, missing hypothesis, false as printed), and proof gaps it
  notices;
- a citation check (with Claude Code; Codex support is planned soon), where the cited work is openly available (e.g. on
  arXiv): whether it states the cited result in the form used, and whether bibliography entries are correct and up
  to date (e.g. preprints since published). With Claude Code it reached 74% of cited results across seven real papers.

Not aimed at: textbook-scale formalization; proving every cited result in Lean (by default a result the paper only
cites becomes an explicit, named hypothesis); other agents; hosted or collaborative use.

## Highlights

- **Finds errors in the paper, not only proofs of it.** A false statement is reported with a Lean
  counterexample and its repaired form proved; vacuous statements are reported too, in a defect
  report written for the authors. The run can also report slips in proofs it notices.
- **A sign-off sheet for the authors.** Before any proof is written, each statement of the paper is
  shown next to a plain-English reading of its Lean, with every difference spelled out. Once signed,
  the statements are frozen, and any later change is caught mechanically.
- **Choose how involved you are.** Approve every step, sign off only the statements, or let the run
  go hands-off; every decision taken for you is recorded, with what it would cost to reverse it.
- **Finishes on its own.** The run stops only for a mathematical question, a permission, or
  something only you can fix; faults in its own tooling are repaired inside the run through
  reviewed patches.
- **Nothing to deploy.** Everything runs in one Claude Code conversation on your machine: no
  server, no sandbox to set up. A 30-page, 67-result paper took about 16 hours of active run time
  (48.5 hours of wall-clock in all, on an earlier version) on one subscription.
- **Readable results.** A one-page summary, a full report and a decisions document, each read by a
  fresh AI reader before you see it, with mechanism details kept out of your way.

## How it works

- **Statements first, then frozen.** The agent first writes every statement with `sorry` proofs.
  You (or, if you choose, the agent) sign them off on `SIGNOFF.pdf` at Checkpoint B. From then on
  the approved statements are fingerprinted, and any change to them is caught mechanically.
- **Independent reviewers.** Each audit round sends the Lean to separate reviewer agents, each
  checking one criterion: faithfulness to the paper, correspondence between statement and
  docstring, non-vacuity, and substantiveness. Each starts fresh, with only its prompt and the files.
- **An adjudicator decides every finding.** It re-runs the Lean probes a reviewer cites, then
  adopts, rejects, defers, or puts the question to you. Adopted fixes are implemented and re-audited.
- **Machine checks back the judgements.** Before every round: the Lean builds, no `sorry` remains,
  only the standard axioms are used, the approved statements are unchanged, and the index of
  results is consistent. Proofs are checked by the Lean kernel. You can independently re-check the
  proofs with Lean's `leanchecker` ([`INSTALL.md`](INSTALL.md)); a built-in check is planned.
- **Fresh readers check the documents** before they reach you, and every line that tells you how
  far to trust a result is checked by an agent against the run's record.
- **The run repairs itself.** In release mode (the default), a fault in the run's own tooling is
  fixed by the agent through a reviewed patch and recorded for maintainers, instead of stopping.
  The proof checks and what you signed can never be changed by such a patch.

## What you get

Delivered to `<project>/deliverables/`:

- **The Lean formalization**, on a git branch of your Lean project. A result the paper only cites
  is taken as an explicit, named hypothesis, never as an axiom.
- **`SUMMARY.pdf`** (one page, read first): the status of every numbered result, and the defects,
  proof slips and vacuous statements found.
- **`REPORT.pdf`**: the full audit report.
- **`SIGNOFF.pdf`**: the statement-by-statement sign-off sheet.
- **`DECISIONS.md`**: every decision taken, by whom, and what reversing it would cost.
- **`CITATIONS.md`**: advisory notes on the paper's citations.
- **`RUN_RECORD.md`**: how the run went (stops, fixes, tool problems), for maintainers.
- **`README.md`**: an index of the deliverables.
- **The audit record**: a separate git repository with every reviewer verdict and every decision.

## Quick install

**Easiest: let Claude Code (or Codex) do it.** Clone the repository, open Claude Code in it, and ask:

```bash
git clone https://github.com/ZRTMRH/formalize-paper ~/formalize-paper
cd ~/formalize-paper && claude
```

then type: "Set up formalize-paper for me: follow INSTALL.md. Create a Lean project ~/my-formalization if I don't have one, run the quick check it describes, and ask me for anything that needs my password, a click, or my name and email for git."

It follows [`INSTALL.md`](INSTALL.md) and asks before each command; when it trusts the folder, choose
"Yes, I trust this folder". If a system package is missing it gives you one command to run yourself (it cannot
type your password). Tested on Linux and on a new macOS account: the setup itself took under 30 minutes. On a Mac, clone the `macos` branch instead (`git clone -b macos …`).

**By hand (Linux):**

```bash
# once: a Lean project that requires Mathlib (skip if you have one)
cd ~ && lake +leanprover/lean4:v4.35.0 new my-formalization math
cd ~/my-formalization && lake exe cache get        # prebuilt Mathlib: minutes, not hours
git add -A && git commit -m "new project"

# install and a quick check (seconds)
git clone https://github.com/ZRTMRH/formalize-paper ~/formalize-paper
~/formalize-paper/install.sh ~/my-formalization            # Codex: add --codex before the path
python3 -B audits/project.py --selftest && python3 -B audits/lanecheck.py --selftest   # each ends: selftest: ok

# start a run
claude                                                     # then type /formalize-paper
# or, with Codex:
codex --sandbox workspace-write --add-dir ~/my-formalization/.git   # then type $formalize-paper
```

**By hand (macOS):** the same, cloning the `macos` branch, after three one-time extras listed in the macOS
section of `INSTALL.md` on that branch (Python 3.10 or newer, bash 5, and one line in `~/.zshrc`).

[`examples/`](examples/) has a one-page example project to try.

## How a run goes

A run asks a few setup questions, then works in one conversation. It can wait for you at three
checkpoints: **A** (confirm the setup), **B** (sign off the statements) and **C** (answer open
decisions). You choose how involved you want to be:

| Level | Setup (A) | Statements (B) | Results (C) |
|---|---|---|---|
| involved (default) | you approve | you approve | you answer |
| statements only | you approve | you approve | delivered |
| hands-off | you approve | the agent approves | delivered |

Decisions the agent takes for you follow the adjudicator's recommendation, and each is listed in
the report for you to reverse. Otherwise the run stops for you only when:

1. a goal result looks false or unprovable as stated;
2. it would push, publish or contact someone you did not allow at setup;
3. something only you can fix (a login, a usage limit, permissions, or another program that keeps changing the project's files);
4. the paper's meaning is genuinely ambiguous on a point that matters.

If Claude pauses on a usage limit or an API error, leave the session open and type `continue` once
it clears. A run on a short paper takes a few hours; a 30-page paper takes one to two days. A Claude
Max plan is recommended. 16 GB of RAM is enough (say so at intake question 7); 8 GB works, more
slowly, with one agent at a time. More detail: [`INSTALL.md`](INSTALL.md).

## Track record

- **Le, Shi and Wei, "A Complete Dichotomy for L∞ Permutation Removal"** (arXiv:2610.28271): 30
  pages, 67 numbered results, formalized in full. The Lean is public at
  [github.com/ZRTMRH/le-shi-wei-linf-lean](https://github.com/ZRTMRH/le-shi-wei-linf-lean) (v1.0).
- **Version 0.3.0 end to end:** a hands-off run on a synthetic test paper with planted errors
  delivered in about 4 h 15 min with no human input after setup. It found the planted false lemma
  (with a Lean counterexample, and the repaired form proved), the vacuous statement, the slip in a
  proof, and proved the goal theorem.

## Documentation

- [`INSTALL.md`](INSTALL.md): installation, permissions, upgrading and uninstalling.
- [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md): known limitations of this version.
- [`MAINTAINING.md`](MAINTAINING.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md): for changing the
  scripts or the protocol.
- `audits/RUN.md` and `audits/AUDIT_PROTOCOL.md` are written for the agent; you do not need to read them.

## Citing

See [`CITATION.cff`](CITATION.cff); GitHub shows it as "Cite this repository".

## License

Apache-2.0 (see [`LICENSE`](LICENSE)), **except** the parts adapted from Trellis: the
substantiveness, correspondence and paper-faithfulness rubrics (Lanes A–C of
`audits/AUDIT_PROTOCOL.md`) and the reviewer prompts cut from them. Those parts are under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0),
with this notice:

Required Notice: Copyright (c) 2026 Wesley Pegden.

Commercial use of those parts needs Wes Pegden's permission. [`NOTICE`](NOTICE) lists the files
and sections concerned.

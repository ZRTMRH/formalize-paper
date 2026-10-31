# Stage 0 — intake and Checkpoint A

Read this at the start of a new run (RUN.md, "Start or resume"). It ends when the human OKs
Checkpoint A; then read `stage1-setup.md` (the stage is first recorded with `project.py --stage`
in Stage 1 step 5, once the config and the log exist).

**Send the intake.** Run `python3 audits/prompt.py --intake` and send what it prints on stdout to
the human **unchanged, as ONE plain-text message**, then wait for the one answer. Never use the
question tool (Claude Code's `AskUserQuestion`, or any form) for it: a form takes at most four
questions, and a run once split the intake that way and lost questions. The script also prints a
line `intake-message sha256 <hex>` (on stderr, or alone with `--hash`): it goes into `RUN_LOG.md`
under "## Intake" in Stage 1, and `integrity.py --pin` refuses without it. If the answer leaves a
label out, ask that label alone and record that in the log.

**Save the answer at once,** before Checkpoint A and before any branch exists (a conversation can
end at any point; the run's log is only created in Stage 1 step 5): `python3 audits/project.py
--intake-save` with, on its standard input, the `intake-message sha256` line and one line per label
as they go under `## Intake` (no heading lines). When the human OKs Checkpoint A, save the same text
again with the line `- Checkpoint A: OK (<date>)` added at the end (a save may only add lines). A
resumed conversation finds it (`project.py --stage` says so) and never sends the intake again.

**What each answer fills** (derive everything else yourself):
- 1a `source_pdf` (it must be inside the project; the config check refuses a path outside it); 1b, 1c
  `confidential` (true: no subagent uses the network; push only to private remotes, and only as
  6c/6d allow).
- 2a the range; 2b `goal_results`; 2c the indexed environments.
- 3a `literature_hypotheses`; 3b `libraries` (a library other than Mathlib is less vetted: its
  definitions are checked before use, "Missing theory" in `stage2-statements.md`).
- 4: faithfulness only is `goal: faithfulness`, prior-art lane off; the other answer is
  `goal: library-contribution`, prior-art lane on.
- 5a the budget (table below); 5b the subscription; 5c `involvement` (`involved`,
  `statements-only` or `hands-off`) and `involvement_answer` (the answer, verbatim): what each
  level hands to you is in RUN.md, "Involvement levels and delegated decisions"; 5d the approver
  (none under `hands-off`; under `involved` they may still let the agent approve at Checkpoint B,
  which the report discloses), logged in ONE fixed form that `python3 audits/prompt.py --intake
  --5d "human <name>"` (or `--5d agent`, only when the answer is the agent under `involved`) prints:
  `- 5d: human <name>` or `- 5d: agent`, the human's words on the next line (`  answer: "..."`).
  Only the exact line `- 5d: agent` lets the agent re-approve its own approval (under `involved`;
  never under `statements-only`); any other 5d line means the human.
- 6a the report's reader; 6b the copy destination; 6c, 6d, 6e what may be pushed or sent.
- 7 anything else, logged.

## The intake message

`prompt.py --intake` prints this block; it is not typed by hand.

```text
Before I start, please answer these questions in one reply, by label (for example
"1a: paper/note.tex"). Where a default is given, "default" keeps it.

Source
1a. Where is the paper? A .tex file is preferred. It must be inside this project (for example
    paper/): a file outside it makes every reviewer's read ask for permission.
1b. Is it the authors' own text, and which version?
1c. Is it unpublished or confidential? If so, no reviewer uses the network, and nothing is
    pushed except to private remotes, and only if 6c and 6d allow it. (The advisory citation
    notes at the end then only search for the cited works by title and authors.)

Range
2a. The whole paper, or which results?
2b. Which result(s) are the goal?
2c. Which environments count as results: Theorems, Lemmas, Propositions, Corollaries,
    Definitions, and also Claims inside proofs, Facts, Constructions, Remarks?
    Default: every numbered environment.

Literature and libraries
3a. Results the paper cites from the literature: formalize each, or take it as an explicit
    named hypothesis? Default: a named hypothesis, unless a library below has it.
3b. Which Lean libraries besides Mathlib may the formalization use? Default: Tau Ceti
    (TauCetiProject/TauCeti; it has, for example, graphons and dense graph limits). Every
    listed library is searched before a result is skipped for missing theory; one is added to
    the project only if something from it is used, and its definitions are checked first.

Library work
4.  Faithfulness only (default), or also check Mathlib for duplicates and list candidates for
    Mathlib pull requests (this adds a prior-art reviewer)?

Budget and involvement
5a. Budget: light, standard (default) or thorough.
      light     3 reviewers (correspondence, paper-faithfulness, non-vacuity);
                at most 2 rounds that re-examine what changed
      standard  4 reviewers (+ substantiveness); at most 4 such rounds
      thorough  4 reviewers; rounds until one finds nothing to fix
    The statement round and the final full round run whatever the budget.
5b. Which subscription pays? (Runs on one subscription share its usage limit: several papers at
    once draw on it together and hit the 5-hour limit sooner. If the agent stops because
    the limit or a service error ended its turn, type "continue" once the limit resets.)
5c. How involved do you want to be after the intake and Checkpoint A (where you confirm the
    setup, right after this message)? After Checkpoint A the run normally waits for you twice
    more:
    - Checkpoint B (after the Lean statements are written and committed, before any proof is
      merged): approve that each Lean statement says what the paper says, and answer open
      questions (for example: Mathlib lacks a theory the paper uses -- build it, assume it as
      a named hypothesis, or skip that result?).
    - Checkpoint C (at the end): decisions such as keeping or dropping hypotheses the proofs
      do not need, claims that hold only vacuously (true only because nothing satisfies their
      hypotheses), results not formalized, and limits of the review (what the reviewers could
      not check).

    Where the agent decides for you, it follows the recommendation of the adjudicator (a
    separate agent that did not write the code) if there is one. Otherwise it keeps the paper's
    statements and hypotheses, never generalizes a statement, and handles missing theory (a
    result needing mathematics no library has) by building it when only definitions and easy
    lemmas are missing, otherwise by assuming it as a named hypothesis, disclosed in the summary
    delivered with the report: it never builds a large library or skips a result on its own, and never stops for it.

    (a) Involved (default): you decide at B and C. You keep every decision; the run waits for
        you twice.
    (b) Statements only: you approve the statements at B; the agent decides everything after
        that. If a statement you approved must change later, the agent asks you and keeps
        working; only the delivery waits for your answer. You keep the statement sign-off; you
        give up the end-of-run decisions.
    (c) Hands-off: the agent decides at B, at C and on every later matter, and finishes the run
        without asking you. When it has no written recommendation it keeps the paper's
        statements and hypotheses and handles missing theory as above. The report
        states that no human checked that the Lean statements say what the paper says, nor any
        later decision. Each decision is explained, and can be reversed later, but a reversal
        may need new proofs and new audit rounds. You keep the setup (Checkpoint A); you give
        up the statement sign-off and every later decision.

    Whatever you choose, the run stops and waits for you only for: (1) a goal result that looks
    false, or unprovable for a reason other than missing library theory (you will be shown why
    and asked how to proceed); (2) something would be pushed, published or sent to the authors
    that you did not allow here; (3) something only you can fix: a login, administrator rights,
    more quota or payment, a change to your own files, or another program that keeps changing
    the project's files during the run; (4) the paper's meaning is genuinely ambiguous on a
    point that matters and the reviewers cannot converge on one reading (you will be shown the
    passage, the possible readings and what each would mean for the formalization, and asked
    which is meant, hands-off included; after your answer the run resumes at the level you
    chose). Nothing else stops the run: a fault in a check's bookkeeping, in the audit records
    or in the tools (signs of tampering included), or a crashing check, is cured by the agent
    with a fixed, logged step (a bug in an audit tool: a patch an independent agent reviews
    first), and the run record lists it. A loosely used convention of the paper (say, whether
    the natural numbers start at 0 or at 1) is no stop either: the agent takes the intended
    reading and records the choice. Besides these stops, the level decides what you are asked:
    under (a) the agent asks you at Checkpoints B and C, and before any change to a statement
    you approved; under (b) the agent asks you before any change to a statement you approved,
    and keeps working on everything else meanwhile: only the delivery waits for your answer;
    under (c) the agent asks you nothing; it decides, and the report discloses each decision.
    You cannot change this choice once the run starts, short of starting a new run.
5d. Answer only if you chose (a) or (b) in 5c: who approves the statements at Checkpoint B?
    It should be someone who knows the mathematics. (Under (a) they may still choose at
    Checkpoint B to let the agent approve; the report then says the statements were not
    reviewed by a human. Under (b) the approver approves the statements themselves, and every
    later change to one is their question.) Answer with a name, or, under (a) only, "the
    agent": then the agent may re-approve, later, a statement it approved; a statement a person
    approved is changed only with that person's approval. Only an answer the approver types
    here personally counts as theirs; an answer relayed through another AI agent counts as the
    agent's approval.

Deliverables
6a. Who reads the report?
6b. Where should the report PDF and the sign-off PDF be copied? Default: deliverables/ in the
    project (not committed); a copy anywhere else asks for permission, or you make it.
6c. May the Lean branch be pushed, and to which remote (for a confidential paper, a private one
    only)? Under which license may others reuse the Lean code? Default: Apache-2.0, Mathlib's ("none"
    adds no license file). Push it as one clean commit (default) or with the run's full history?
6d. May the audit record (audits/, its own git repository) be pushed, and where?
6e. Will defects be sent to the authors?

Anything else
7.  Anything else I should know? For example: known errors or doubts, conventions, deadlines.
    If this computer has 16 GB of RAM or less, please say so here: the run then keeps at most
    3 agents at a time, and each compiles its Lean files one at a time.
```

## Checkpoint A

Show the derived setup on one screen:

- title, authors and version, from the source;
- the project name and branch;
- the namespace and `lean_lib` name;
- the goal results;
- the indexed environments;
- the literature hypotheses;
- the libraries besides Mathlib (`libraries`), and any result already known to need theory none
  of them has, asked as in "Missing theory" (`stage2-statements.md`, step 6; under `hands-off`
  report it: the agent builds it if only definitions and easy lemmas are missing, else takes
  option (2), the named hypothesis, RUN.md "Missing theory");
- `confidential`;
- the lanes, budget and round cap;
- the approver (none under `hands-off`);
- the involvement level, with the human's answer to 5c verbatim, and in one line what it means
  (who decides at B, at C and in between);
- the stop policy, as `prompt.py --show intake` prints it (`project.stop_policy_text`: the four
  stops of the run mode, and the questions the level asks);
- the run mode, as `prompt.py --show` prints it (set at install; RUN.md, "Run mode");
- the report destination;
- push yes or no, as one clean commit or with the full history, and the license;
- any other library in the lakefile that the run leaves alone (for example the template library of
  `lake new … math`).

Proceed only on the human's OK.

| budget | lanes in diff rounds (`lanes` in the config) | diff-round cap |
|---|---|---|
| light | correspondence, paper-faithfulness, non-vacuity | 2 |
| standard | + substantiveness | 4 |
| thorough | + substantiveness | until a round adopts nothing (6 under a delegating level) |

Prior-art is added only if question 4 said so. The statement round and the final full round run
fixed lane sets whatever the budget (`scope.py` decides). When the cap is reached and ADOPT rows
are still coming, the conservative default holds (`stage4-rounds.md`, exit check; RUN.md "How you
decide"); only a `dev` run under `involved` stops and asks. Statement rounds have caps of their
own: 4 before the first approval, 2 for each re-approval (`scope.py --statements` refuses one more).

# Writing one planted-defect benchmark paper (bench6–10, agent-made, disclosed as such)

*Published copy of the brief given to each writer agent. Local file paths and internal folder names were replaced by plain descriptions; the instructions are otherwise unchanged.*

You are an isolated writer. Do NOT read anything about the formalization tool under test: no files of the tool itself, its audit directories, its run folders, its test notes or its configuration, and NOT the existing benchmark keys or bench1–5 papers. You may use pdflatex and python3 (stdlib) for checks.

Write a short, realistic research-style mathematics note (2–3 pages of LaTeX, amsart, a fictional author and affiliation), on the TOPIC given to you, in the style of a careful but imperfect paper:
- Section 1 introduction; Section 2 definitions, lemmas, propositions and ONE goal theorem (say which in the key) with proofs; optionally a short Section 3 with an application/corollary and a cited classical result.
- 9–12 numbered items (shared counter), every result with a proof except cited ones.
- The GOAL THEOREM must be TRUE as stated, and its proof must go through from the corrected lemmas.
- Keep everything formalizable in Lean 4 + Mathlib with modest effort (elementary objects only).

Plant exactly 6 defects plus 1 decoy, spread over these types (pick 6 different types where possible):
1. numbered lemma false as printed (intended version recoverable);
2. missing hypothesis at an edge case (n=0/1, empty set, x<0, zero divisor…);
3. vacuous statement (hypotheses unsatisfiable together);
4. unused / unneeded hypothesis;
5. cited classical result stated stronger than its source (real source, real theorem, misquoted);
6. typo in a statement (bound, index, modulus, inequality direction);
7. slip inside a proof only (statement correct);
8. definition clashing with its later use;
9. ℕ starting at 0 vs 1 / off-by-one in a range.
No defect may make the goal theorem false. The decoy is something that looks suspicious but is correct. Every defect must be subtle enough to look natural, but definitely wrong, with a concrete witness. Verify every defect and the goal with python where possible (exhaustive small cases), and verify the decoy is correct.

Outputs (write files; if a write is refused, return the full text between `=== FILE <path> ===` and `=== END ===`):
- `benchN/paper.tex` in the benchmark folder (and `paper.pdf` via pdflatex if available).
- the KEY, which must never be placed in the paper folder: `keys/benchN-key.md` in the benchmark folder, in this format: title line; goal theorem (number, tex line, statement, TRUE and why); numbering list; for each defect `### BN-k — <type> (<item>, l.<line>)` with What / Witness / Intended / Goal (affected or not, and why); the decoy with why it is correct; "not a defect" notes; your verification method.
Final message: one paragraph summary (topic, goal, the 6 defect types, the decoy) and confirmation of what you verified computationally.

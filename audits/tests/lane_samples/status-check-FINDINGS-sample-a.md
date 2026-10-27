# Status check

(A public fixture in the format of a status-check agent's FINDINGS.md. The structure follows a
real run's file; the paper-specific content has been replaced.)

I compared the summary's status for each result in its results table and for each defect in
PAPER_DEFECTS.md against REPORT.md and the records.

## Mismatches

### M1. Lemma 1.2 -- the summary says "not established"
- **The summary:** "| not established | Lemma 1.2 |"
- **The records:** "| non-vacuity | Example.lemma_1_2 | Ambiguous | **QUESTION** | ... Recommended: (a)." (ADOPTED.md of the latest round); "- [DELEGATED, operator under hands-off (intake); reversal: re-approve] keep lemma_1_2 as stated (reading (a))" (RUN_LOG.md, "Open questions")
- **It should read:** faithful (decided under hands-off). The only unsettled-looking item is the non-vacuity Ambiguous verdict, and its QUESTION was answered reading (a) in RUN_LOG.md.
- **The status comes from:** the summary's own computation (a script), which does not count the operator's delegated answers as settling a QUESTION.

### M2. Corollary 1.3 -- the summary says "not established"
- **The summary:** "| not established | Corollary 1.3 |"
- **The records:** "| non-vacuity | Example.corollary_1_3 | Ambiguous | **QUESTION** | ... Recommended: (a), for the same reason as Lemma 1.2." (ADOPTED.md of the latest round)
- **It should read:** faithful (decided under hands-off), for the same reason as M1.
- **The status comes from:** the summary's own computation (a script).

### M3. Theorem 3.1 -- the summary says "false as printed; proved as repaired"
- **The summary:** "| false as printed; proved as repaired | Theorem 3.1 |"
- **The records:** "Theorem 3.1 is not proved in the formalization: as in the paper, it is a cited literature result, taken as the named hypothesis `Example.CitedResult`, which no result of the formalization uses." (PAPER_DEFECTS.md, "Not defects"; also REPORT.md §5)
- **It should read:** "false as printed (refuted); repaired statement taken as a literature hypothesis, not proved". The repaired form exists only as the unproved named hypothesis, so "proved as repaired" claims a proof that does not exist.
- **The status comes from:** the summary's own computation (a script), which reads the defect row's `false` status with a repair as "proved as repaired" without checking that the repaired statement is a proved theorem rather than the literature hypothesis.

## Checked and consistent

- Definition 1.1: faithful
- Theorem 2.1: faithful (goal result)

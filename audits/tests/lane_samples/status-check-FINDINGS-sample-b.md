# Status check

(A public fixture in the format of a status-check agent's FINDINGS.md. The structure follows a
real run's file; the paper-specific content has been replaced.)

I compared the summary's status for each of its 12 results and for both defects in PAPER_DEFECTS.md (rows 1-2), plus the proof slip and VACUOUS.md row 1, against REPORT.md, the records and the rounds' ADOPTED.md.

## Mismatches

- none

## Checked and consistent

- Definition 1.1: faithful (correspondence and paper-faithfulness Pass in the latest round; no assumption, REPORT §2 empty)
- Lemma 1.2: faithful (every lane Pass in the latest round)
- Lemma 2.3: false as printed; proved as repaired (PAPER_DEFECTS row 1; the paper-faithfulness Fail of the latest round was ADOPTed as that source defect, with F10 and F12 Pass)
- Proposition 2.4 (b): vacuous as printed; intent unknown, not repaired (PAPER_DEFECTS row 2; VACUOUS.md row 1)
- Theorem 3.1: faithful (statement Pass in every review; only its paper proof has a slip, shown on the summary as proof slip 1)
- Defect 1 (Lemma 2.3): shown on the summary as "defect 1"
- Defect 2 (Proposition 2.4(b)): shown on the summary as "defect 2"
- Proof slip (Theorem 3.1): shown on the summary as "proof slip 1"
- VACUOUS.md row 1: shown on the summary as "vacuous 1"; SKIPPED.md is absent and REPORT §4 records no skip

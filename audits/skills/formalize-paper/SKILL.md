---
name: formalize-paper
description: Formalize a mathematics paper in Lean and audit it with independent reviewer subagents, in one conversation, producing a PDF report and a statement sign-off sheet. Use when the user asks to formalize a paper, audit a formalization, or resume a formalization run.
---

Read `audits/RUN.md` in the root of the current Lean project and follow it exactly, starting at
Stage 0. It begins by checking whether a run is already in progress on this branch; if not, it asks
the intake questions.

If `audits/RUN.md` does not exist in the current repository, stop and say so: the audit apparatus
is not installed here. It is installed with `install.sh` from the formalize-paper repository
(see its `INSTALL.md`).

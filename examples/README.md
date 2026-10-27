# Examples

## `sparse-note/`: a project to install into and try

A synthetic one-page note, "A short note on sparse sets of integers" by "A. Author" (12 numbered
results), set up as a standalone Lake project:
- `paper/note.tex`, the note;
- `SparseNote/Basic.lean`, its definitions and statements (proofs are `sorry`);
- `SparseNote/Main.lean`, the index from paper results to Lean names;
- `sparse-note.json`, the project configuration the run uses.

It is the fixture for the self-tests and the install test. Set it up with

```bash
examples/sparse-note/setup.sh ~/sparse-note-try
cd ~/sparse-note-try && lake exe cache get && lake build SparseNote
python3 -B audits/selftest_all.py
```

`setup.sh` copies the project, makes it a git repository on branch `sparse-note`, runs
`install.sh`, and writes the project configuration into `audits/projects/`. See `INSTALL.md` for
a first run.

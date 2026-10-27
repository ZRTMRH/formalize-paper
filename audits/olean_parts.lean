import Lean
open Lean

/-!
`audits/project.py` (`comment_only_since`) runs this with `lake env lean --run`: it splits a
compiled module (`.olean`) into the parts that carry meaning -- its imports and constants (every
declaration's type and value: statements, proofs, definition bodies, auxiliary declarations), and
each environment extension's entries (attributes such as `simp` and `instance`, reducibility,
notations, compiled code, ...) -- and saves each part alone. Two builds of one module, before and
after an edit, are then compared part by part, byte for byte. Left out are only the extensions
that record docstrings and source positions (`SKIP`), which a comment edit changes by design.
-/

/-- The extensions that hold docstrings, declaration source ranges or linter messages (with their
positions), and nothing a proof or a later module can use. Matched by user-facing name, so a
`private` extension (`_private.….0.Lean.moduleDocExt`) is matched too. -/
def SKIP : List Name :=
  [`Lean.docStringExt, `Lean.declRangeExt, `Lean.moduleDocExt, `Lean.versoDocStringExt,
   `Lean.versoModuleDocExt, `Lean.inheritDocStringExt, `Lean.Linter.lintLogExt]

def main (args : List String) : IO UInt32 := do
  let [src, out, mod] := args | IO.eprintln "usage: olean_parts OLEAN OUTDIR MODULE"; return 2
  let out : System.FilePath := out
  IO.FS.createDirAll out
  let (md, _) ← readModuleData src
  let mod := mod.toName
  let mut idx := ""
  let mut i := 0
  for (en, es) in md.entries do
    if es.isEmpty then continue
    if SKIP.contains ((privateToUserName? en).getD en) then
      idx := idx ++ s!"skip\t{en}\n"
      continue
    saveModuleData (out / s!"ext{i}.olean") mod
      { md with constNames := #[], constants := #[], extraConstNames := #[], entries := #[(en, es)] }
    idx := idx ++ s!"ext\t{en}\t{es.size}\text{i}.olean\n"
    i := i + 1
  saveModuleData (out / "constants.olean") mod { md with entries := #[] }
  -- one line per declaration: which ones differ, for the message (the bytes above decide)
  for c in md.constants do
    let v := match c.value? (allowOpaque := true) with | some v => toString v.hash | none => "-"
    idx := idx ++ s!"const\t{c.name}\t{c.type.hash}\t{v}\n"
  IO.FS.writeFile (out / "index.tsv") idx
  return 0

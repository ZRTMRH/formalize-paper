-- Content fingerprints, appended (or imported) by audits/fingerprint.py.
-- __NAMESPACE__ and __MODULE_ROOT__ are substituted from the project config.
--
-- Which constants are the PROJECT's: those under the namespace, AND those defined in a module
-- under the project's root module (a root-level helper outside the namespace is still ours --
-- treating it as trusted Mathlib let a changed `def` slip past every fingerprint), AND, in append
-- mode, those defined in this very file.
--
-- For each, one line
--   FP <TAB> key <TAB> kind <TAB> origin <TAB> own-hash <TAB> deps (keys, comma-separated)
-- key    : the user-facing name; for a `private` declaration "<name> (private in <Module>)",
--          because two files may each have a private `aux` and a name-keyed table collided.
-- origin : "user" if the declaration has a source position (someone wrote it), "auto" otherwise
--          (equation lemmas, recursors, noConfusion, congr lemmas, matchers). Lean decides this;
--          the earlier name-pattern guess excluded a real theorem called `eq_zero_of_G`.
-- own    : the MEANING only -- a theorem's type (never its proof); a def's type and value; an
--          inductive's type and constructor types. Metadata is erased, universe parameters are
--          renamed positionally (renaming `u` to `w` is not a change), and binder names are not
--          part of Lean's expression hash.
open Lean in
partial def auditFpStripMData : Expr → Expr
  | .mdata _ e => auditFpStripMData e
  | .app f a => .app (auditFpStripMData f) (auditFpStripMData a)
  | .lam n t b bi => .lam n (auditFpStripMData t) (auditFpStripMData b) bi
  | .forallE n t b bi => .forallE n (auditFpStripMData t) (auditFpStripMData b) bi
  | .letE n t v b nd => .letE n (auditFpStripMData t) (auditFpStripMData v) (auditFpStripMData b) nd
  | .proj s i e => .proj s i (auditFpStripMData e)
  | e => e

open Lean in
def auditFpKey (n : Name) : String :=
  match privateToUserName? n, privatePrefix? n with
  | some u, some p =>
      -- p = `_private.<Module>.0`; show the module
      let mod := (p.components.drop 1).dropLast
      s!"{u} (private in {".".intercalate (mod.map toString)})"
  | _, _ => toString n

-- END HELPERS (signoff.py reuses everything above this line)
open Lean in
run_cmd do
  let env ← getEnv
  let ns : Name := `__NAMESPACE__
  let root : Name := `__MODULE_ROOT__
  let isOurs (n : Name) : Bool :=
    let u := (privateToUserName? n).getD n
    if u.isInternal || (`auditFpStripMData).isPrefixOf u || (`auditFpKey).isPrefixOf u then false
    else if ns.isPrefixOf u then true
    else match env.getModuleIdxFor? n with
      | some i => root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i.toNat]!
      | none => true   -- defined in this file (append mode); the two helpers above are excluded
  let mut count : Nat := 0
  for (n, ci) in env.constants.toList do
    if isOurs n then
      let (kind, es) : String × Array Expr := match ci with
        | .thmInfo v => ("theorem", #[v.type])
        | .defnInfo v => ("def", #[v.type, v.value])
        | .opaqueInfo v => ("opaque", #[v.type, v.value])
        | .inductInfo v =>
            ("inductive", #[v.type] ++ v.ctors.toArray.filterMap (fun c => (env.find? c).map (·.type)))
        | .ctorInfo v => ("ctor", #[v.type])
        | .recInfo v => ("rec", #[v.type])
        | .axiomInfo v => ("axiom", #[v.type])
        | .quotInfo v => ("quot", #[v.type])
      let lps := ci.levelParams
      let canon := (List.range lps.length).map (fun i => Level.param (Name.mkSimple s!"u{i}"))
      let es := es.map (fun e => auditFpStripMData (e.instantiateLevelParams lps canon))
      let h : UInt64 := es.foldl (fun acc e => mixHash acc e.hash) (hash kind)
      let deps := (es.foldl (fun acc e => acc ++ e.getUsedConstants) #[]).filter
        (fun d => isOurs d && d != n)
      let deps := (deps.toList.map auditFpKey).eraseDups.toArray.qsort (· < ·)
      -- recursors, casesOn/recOn, noConfusion and constructors inherit the inductive's source
      -- position, but nobody approves them separately: the inductive's own hash covers them
      let generated := isAuxRecursor env n || isNoConfusion env n || kind == "rec" || kind == "ctor"
      let origin := if (← findDeclarationRanges? n).isSome && !generated then "user" else "auto"
      IO.println s!"FP\t{auditFpKey n}\t{kind}\t{origin}\t{h}\t{",".intercalate deps.toList}"
      count := count + 1
  IO.println s!"FPCOUNT\t{count}"

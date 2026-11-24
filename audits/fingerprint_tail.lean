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
-- Proof erasure (approver, 2026-11-16): in a definition's VALUE, every subterm that is a proof -- its type
-- is a proposition (Meta.isProof: inferType, then isProp; Lean's proof irrelevance) -- becomes one fixed
-- marker. Decided on the elaborated Expr, never on source syntax: data built by a tactic (`by exact 5`, the
-- first component of `⟨x, by …⟩`, a Decidable instance) is not a proof and is hashed as before. Types are
-- never erased; `opaque` values are not erased. If Lean cannot type a subterm, it is kept (fails toward
-- DRIFT, never hides a change). Filling a `sorry` in a proof field of an approved instance no longer
-- drifts (De Medts e2e, stop S1: Lean names the aux proofs `<decl>._proof_<k>` it reuses across a module).
open Lean Meta in
def auditFpEraseProofs (e : Expr) : MetaM Expr :=
  Meta.transform e (pre := fun s => do
    if (← try Meta.isProof s catch _ => pure false) then
      return .done (.lit (.strVal "auditFpProof"))
    return .continue)

-- the whole command types the subterms of every project definition's value: no heartbeat limit, and a
-- recursion limit above any project term (`Meta.transform` counts depth; a deeper term threw past `try`)
set_option maxHeartbeats 0 in
set_option maxRecDepth 1000000 in
open Lean in
run_cmd do
  let env ← getEnv
  let ns : Name := `__NAMESPACE__
  let root : Name := `__MODULE_ROOT__
  let isOurs (n : Name) : Bool :=
    let u := (privateToUserName? n).getD n
    -- the three helpers above are excluded only as declarations of THIS file (REVIEW-SAFETY-FP F1): a project
    -- module's `auditFpEraseProofs.evil` or `auditFpKey.evil` is fingerprinted like any other
    if u.isInternal || ((env.getModuleIdxFor? n).isNone && ((`auditFpStripMData).isPrefixOf u
        || (`auditFpKey).isPrefixOf u || (`auditFpEraseProofs).isPrefixOf u)) then false
    else if ns.isPrefixOf u then true
    else match env.getModuleIdxFor? n with
      | some i => root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i.toNat]!
      | none => true   -- defined in this file (append mode); the three helpers above are excluded
  let mut count : Nat := 0
  -- the candidates from the module tables (as dependencies_tail's auditProjectNames); `isOurs` decides
  let mut cands : Array Name := #[]
  for i in [0:env.header.moduleNames.size] do
    let names := env.header.moduleData[i]!.constNames
    if root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i]! then cands := cands ++ names
    else for c in names do
      if ns.isPrefixOf ((privateToUserName? c).getD c) then cands := cands.push c
  for (c, _) in env.constants.map₂.toList do cands := cands.push c
  -- a realized constant (an equation lemma made on first use) can be in two modules' tables: once each
  let mut once : NameSet := {}
  for n in cands do
    if once.contains n then continue
    once := once.insert n
    let some ci := env.constants.find?' n | throwError m!"fingerprint: candidate {n} is not in the environment"
    if isOurs n then
      -- a def's value is proof-erased BEFORE universes are renamed and mdata stripped; `deps` below are read
      -- from the same erased Exprs as the hash (a proof field citing a new lemma adds no dependency)
      let (kind, es) : String × Array Expr ← match ci with
        | .thmInfo v => pure ("theorem", #[v.type])
        | .defnInfo v => do pure ("def", #[v.type, ← Elab.Command.liftTermElabM (auditFpEraseProofs v.value)])
        | .opaqueInfo v => pure ("opaque", #[v.type, v.value])
        | .inductInfo v =>
            pure ("inductive", #[v.type] ++ v.ctors.toArray.filterMap (fun c => (env.find? c).map (·.type)))
        | .ctorInfo v => pure ("ctor", #[v.type])
        | .recInfo v => pure ("rec", #[v.type])
        | .axiomInfo v => pure ("axiom", #[v.type])
        | .quotInfo v => pure ("quot", #[v.type])
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

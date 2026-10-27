-- Dependency walk, appended by audits/dependencies.py. __NAMESPACE__, __ROOTS__ and __CANDS__ are
-- substituted from the project config and its index; __UNPROVED__ and __GENERATED__ as in the
-- axiom sweep; __ASMROOTS__, __DEFS__ and __INDEXED__ for the assumption walk at the end (U2 §2).
-- The dependency walk follows the constants each root's type and proof use, transitively, through
-- the project's own declarations only (no Mathlib declaration uses a project one), and prints every candidate the walk never reaches.
open Lean in
partial def auditDepWalk (env : Environment) (ours : Name → Bool) : List Name → NameSet → NameSet
  | [], seen => seen
  | n :: rest, seen =>
    if seen.contains n then auditDepWalk env ours rest seen else
    let seen := seen.insert n
    match env.find? n with
    | none => auditDepWalk env ours rest seen
    | some ci =>
      let cs := ci.type.getUsedConstants ++ ((ci.value? (allowOpaque := true)).map (·.getUsedConstants)).getD #[]
      auditDepWalk env ours (cs.toList.filter ours ++ rest) seen

open Lean in
/-- Exactly the constants `ours` accepts (namespace `ns`, a module under `root`, or this file), listed
without `env.constants.toList`: with Mathlib imported, filtering every constant through `ours` in a
`run_cmd` took ~3 min per run (B5 handoff); this reads the module tables (~1 s). -/
def auditProjectNames (env : Environment) (ns root : Name) : Array Name := Id.run do
  let mut out : Array Name := #[]
  for i in [0:env.header.moduleNames.size] do
    let names := env.header.moduleData[i]!.constNames
    if root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i]! then
      out := out ++ names
    else
      for n in names do
        if ns.isPrefixOf ((privateToUserName? n).getD n) then out := out.push n
  for (n, _) in env.constants.map₂.toList do
    out := out.push n
  return out

open Lean in
run_cmd do
  let env ← getEnv
  let ns : Name := `__NAMESPACE__
  let root : Name := `__MODULE_ROOT__
  let ours : Name → Bool := fun n =>
    let u := (privateToUserName? n).getD n
    ns.isPrefixOf u || match env.getModuleIdxFor? n with
      | some i => root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i.toNat]!
      | none => true
  let resolve : String → Option Name := fun s =>
    let n := s.toName
    if env.contains n then some n else if env.contains (ns ++ n) then some (ns ++ n) else none
  let roots : List String := __ROOTS__
  let cands : List String := __CANDS__
  let mut start : List Name := []
  for r in roots do
    match resolve r with
    | some n => start := n :: start
    | none => logInfo m!"DEPS-MISSING {r}"
  let seen := auditDepWalk env ours start {}
  for c in cands do
    match resolve c with
    | some n => if !(seen.contains n) then logInfo m!"DEPS-UNUSED {c}"
    | none => logInfo m!"DEPS-MISSING {c}"
  -- every compiler-generated auxiliary (no source range, a generated last component) of a result
  -- left unproved by a logged decision that reaches sorryAx: the axiom sweep accepts it under its
  -- parent's line (axiom_sweep_tail.lean, same rule), so the report must list it
  let unproved : List String := __UNPROVED__
  let generated : String → Bool := __GENERATED__
  if !unproved.isEmpty then
    for n in auditProjectNames env ns root do
      let u := (privateToUserName? n).getD n
      if !u.isInternal then
        match u with
        | .str p s =>
          if generated s && unproved.contains p.toString then
            if (← findDeclarationRanges? n).isNone then
              let ax ← Elab.Command.liftCoreM (collectAxioms n)
              if ax.contains ``sorryAx then logInfo m!"DEPS-AUX {u} {p}"
        | _ => pure ()
  logInfo m!"DEPS-DONE {seen.size}"

-- ASSUMPTION WALK (U2 §2; appended after the dependency walk). __ASMROOTS__: every index result's
-- Lean name; __DEFS__: the Lean names of the index's Definition/Notation/Construction rows; __INDEXED__:
-- every Lean name the index cites. Lines:
--   DEPS-ASM <root> TAB <kind> TAB <binder> TAB <names, comma-separated> TAB <type, one line>
--     kind: prop (a Prop binder), data (a Subtype/set-builder/membership part of a data binder's
--     type, F2), field (a Prop field of a structure or class binder, flattened through extends),
--     embedded (a project Prop constant left in the body after the binders, F3), struct (a binder of
--     any sort whose type is, or contains anywhere (re-check fix), a project structure or class with a
--     Prop field, recursively: the structure's name first, review fix 1). <names>: the non-Definition
--     project constants that make it count
--   DEPS-BINDER <root> TAB <binder> TAB <type>     every Prop binder of the root's telescope, and every
--                                                  `struct` binder
--   DEPS-GOAL <root> TAB <binder>                  a Prop binder definitionally the conclusion ("H = goal");
--                                                  for a `struct` or `Fact P` binder, the conjunction of its
--                                                  Prop fields (`<binder>`) or one of several (`<binder>.<field>`);
--                                                  for a contained structure, `<binder>.<structure>[.<field>]`
--   DEPS-RESTATES <root> TAB <binder> TAB <result> a Prop binder (or such a field conjunction or field)
--                                                  definitionally another index result's statement, or an
--                                                  instance of its conclusion ("H restates a paper result")
--   DEPS-AX <root> TAB <axiom>                     a non-standard axiom (collectAxioms)
--   DEPS-INST <instance>                           a project data instance in the closure, no index row
--   DEPS-BARE <constant> TAB <user>                a project Prop constant taken bare as a hypothesis
--   DEPS-ROOT <root>                               the walk finished this root
open Lean Meta in
partial def auditAsmSpine {α} (unf : Name → Bool) (e : Expr) (acc : Array Expr)
    (k : Array Expr → Expr → MetaM α) : MetaM α := do
  let e := (← instantiateMVars e).consumeMData.headBeta
  match e with
  | .forallE n t b bi =>
    withLocalDecl n bi t fun x => auditAsmSpine unf (b.instantiate1 x) (acc.push x) k
  | _ =>
    match e.getAppFn with
    | .const c _ =>
      if unf c then
        match ← delta? e (· == c) with
        | some e' => auditAsmSpine unf e' acc k
        | none => k acc e
      else k acc e
    | _ => k acc e

open Lean in
partial def auditAsmParts (e : Expr) (acc : Array Expr) : Array Expr :=
  let acc := match e.getAppFn with
    | .const c _ => if c == ``Subtype || c == ``setOf || c == ``Membership.mem || c == ``Set.Elem
                      then acc.push e else acc
    | _ => acc
  match e with
  | .app f a => auditAsmParts a (auditAsmParts f acc)
  | .lam _ t b _ => auditAsmParts b (auditAsmParts t acc)
  | .forallE _ t b _ => auditAsmParts b (auditAsmParts t acc)
  | .letE _ t v b _ => auditAsmParts b (auditAsmParts v (auditAsmParts t acc))
  | .mdata _ b => auditAsmParts b acc
  | .proj _ _ b => auditAsmParts b acc
  | _ => acc

open Lean Meta in
/-- `a` and `b` are definitionally equal (default transparency); a timeout (its own heartbeat budget,
a runtime exception caught too) or an error is "no" -/
def auditAsmDefEq (a b : Expr) : MetaM Bool := do
  tryCatchRuntimeEx (withCurrHeartbeats (withTransparency .default (withNewMCtxDepth (isDefEq a b))))
    fun _ => return false

open Lean Meta in
/-- binder type `t` is (definitionally) the statement of result type `ot` or an instance of its
conclusion (`ot`'s explicit foralls -- not `¬`, not a definition's -- become metavariables): the
hypothesis restates a result the paper proves. A conclusion that is a bare metavariable (`P → P`) never
counts; a timeout or error is "no" -/
def auditAsmRestates (t ot : Expr) : MetaM Bool := do
  if !t.hasFVar then
    if ← auditAsmDefEq t ot then return true
  tryCatchRuntimeEx (withCurrHeartbeats (withTransparency .default (withNewMCtxDepth do
      let (_, _, b) ← forallMetaTelescope ot
      if b.getAppFn.isMVar then return false
      isDefEq t b)))
    fun _ => return false

open Lean Meta in
/-- `e` printed on one line under pinned options (the project's own `set_option`s do not change it) -/
def auditAsmOneLine (e : Expr) : MetaM String := do
  let f ← withOptions (fun _ => ({} : Options) |>.setBool `pp.fullNames false |>.setBool `pp.universes false
      |>.setBool `pp.proofs false |>.setBool `pp.notation true |>.setBool `pp.funBinderTypes false
      |>.setBool `pp.explicit false |>.setBool `pp.mvars false |>.setBool `pp.unicode.fun true
      |>.insert `format.width (.ofNat 100000)) (ppExpr e)
  return (toString f).map fun c => if c == '\n' || c == '\t' then ' ' else c

open Lean Meta in
/-- the "bad" constants of the Prop fields of structure value `x` (flattened through extends),
recursing into fields whose type is a structure `recurse` accepts; [(field, names, field type)] -/
partial def auditAsmFields (bad : Name → Bool) (recurse : Name → Bool) (x : Expr) (seen : List Name) :
    MetaM (Array (String × Array Name × Expr)) := do
  let env ← getEnv
  let ty ← whnfR (← inferType x)
  let .const s _ := ty.getAppFn | return #[]
  if !isStructure env s || seen.contains s then return #[]
  let mut out := #[]
  for f in getStructureFieldsFlattened env s (includeSubobjectFields := false) do
    let p ← try mkProjection x f catch _ => continue
    let ft ← inferType p
    if ← isProp ft then
      let ns := ft.getUsedConstants.filter bad
      if !ns.isEmpty then out := out.push (toString f, ns, ft)
    else
      match (← whnfR ft).getAppFn with
      | .const s' _ => if recurse s' then out := out ++ (← auditAsmFields bad recurse p (s :: seen))
      | _ => pure ()
  return out

open Lean Meta in
mutual
/-- EVERY Prop field of structure value `x` (flattened through extends; [(field path, field type)]),
recursing into fields whose type is a structure `hyp` accepts -- whatever constants the field uses:
a project structure or class (of any sort, `Type` included) with a Prop field packages a hypothesis,
like a `Fact P` (review fix 1: `class LemmaB : Type where eq : ∀ m, …` hid a corrected lemma). A data
field whose type CONTAINS such a structure elsewhere than its head (`List (MSet k)`) contributes that
structure's Prop fields, closed over its parameters (auditAsmContained; path `<field>.<structure>.<f>`) -/
partial def auditAsmPropFields (hyp : Name → Bool) (x : Expr) (pre : String) (seen : List Name) :
    MetaM (Array (String × Expr)) := do
  let env ← getEnv
  let ty ← whnfR (← inferType x)
  let .const s _ := ty.getAppFn | return #[]
  if !isStructure env s || seen.contains s then return #[]
  let mut out := #[]
  for f in getStructureFieldsFlattened env s (includeSubobjectFields := false) do
    let p ← try mkProjection x f catch _ => continue
    let ft ← inferType p
    let path := if pre.isEmpty then toString f else s!"{pre}.{f}"
    if ← isProp ft then
      out := out.push (path, ft)
    else
      match (← whnfR ft).getAppFn with
      | .const s' _ =>
        if hyp s' then out := out ++ (← auditAsmPropFields hyp p path (s :: seen))
        else
          for (s'', conj, _) in ← auditAsmContained hyp ft (s :: seen) do
            out := out.push (s!"{path}.{s''}", conj)
      | _ =>
        for (s'', conj, _) in ← auditAsmContained hyp ft (s :: seen) do
          out := out.push (s!"{path}.{s''}", conj)
  return out

/-- re-check fix: the project structures and classes (`hyp`, not `Fact`) occurring ANYWHERE in type
`t`, its `whnfR`, or the value of a `hyp` type-forming definition occurring there (recursively) -- not
only as its head: `∀ m, ParamSetup m`, `ParamSetup n × ℕ`, `Unit → ParamSetup n`, `{s : ParamSetup n // True}`, `Option`/`List`/`Sigma` wrappers -- that have a
Prop field (recursively, auditAsmPropFields). For each: the conjunction of its Prop fields on a
generic value, and each field, closed over the structure's parameters (and the value, when a field
uses it): `ParamSetup` gives `∀ n, h1 n ∧ h2 n`. [(structure, closed conjunction, [(field, closed)])] -/
partial def auditAsmContained (hyp : Name → Bool) (t : Expr) (seen : List Name) :
    MetaM (Array (Name × Expr × Array (String × Expr))) := do
  let env ← getEnv
  let t ← instantiateMVars t
  -- the constants of `t`, of its whnfR, and of the value of every `hyp` type-forming definition (not
  -- an instance) among them, recursively: `def Setups : Type := ∀ m, ParamSetup m` taken as `(S : Setups)`
  let mut todo := t.getUsedConstants ++ (← whnfR t).getUsedConstants
  let mut cs : Array Name := #[]
  while !todo.isEmpty do
    let c := todo.back!
    todo := todo.pop
    if cs.contains c then continue
    cs := cs.push c
    if hyp c && c != ``Fact && !(isInstanceCore env c) then
      if let some (.defnInfo v) := env.find? c then
        if ← forallTelescopeReducing v.type fun _ b => return (← whnfR b).isSort then
          todo := todo ++ v.value.getUsedConstants
  let mut out := #[]
  for s in cs do
    if s == ``Fact || !hyp s || !isStructure env s || seen.contains s || out.any (·.1 == s) then continue
    let some ci := env.find? s | continue
    let r ← forallTelescopeReducing ci.type fun ps _ => do
      let us ← ci.levelParams.mapM fun _ => mkFreshLevelMVar
      withLocalDeclD `x (mkAppN (.const s us) ps) fun x => do
        let pfs ← auditAsmPropFields hyp x "" seen
        if pfs.isEmpty then return none
        let close := fun (e : Expr) => do mkForallFVars (ps.push x) (← instantiateMVars e) (usedOnly := true)
        let conj := pfs.pop.foldr (fun (_, a) acc => mkAnd a acc) pfs.back!.2
        return some (← close conj, ← pfs.mapM fun (f, ft) => return (f, ← close ft))
    if let some (conj, fs) := r then out := out.push (s, conj, fs)
  return out
end

open Lean Meta Elab Command in
run_cmd do
  let env ← getEnv
  let ns : Name := `__NAMESPACE__
  let root : Name := `__MODULE_ROOT__
  let ours : Name → Bool := fun n =>
    let u := (privateToUserName? n).getD n
    ns.isPrefixOf u || match env.getModuleIdxFor? n with
      | some i => root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i.toNat]!
      | none => true
  let resolve : String → Option Name := fun s =>
    let n := s.toName
    if env.contains n then some n else if env.contains (ns ++ n) then some (ns ++ n) else none
  let defs : List Name := (__DEFS__ : List String).filterMap resolve
  let indexed : List Name := (__INDEXED__ : List String).filterMap resolve
  -- the index results' own constants: a result stated as a Prop definition (`def lemma_2_4 : Prop`,
  -- the printed statement a refutation negates) is what a result is ABOUT when it is left in a body
  -- (`¬ lemma_2_4`), not an embedded assumption; taken as a binder it still counts
  let resultNs : List Name := (__ASMROOTS__ : List String).filterMap resolve
  -- a constant a Definition row covers: the row's own, or one under it (projections, equation lemmas)
  let covered : Name → Bool := fun c => defs.any (·.isPrefixOf ((privateToUserName? c).getD c))
  let asPrinted : Name → Bool := fun c => match (privateToUserName? c).getD c with
    | .str _ s => s.endsWith "_as_printed" | _ => false
  let isThm : Name → Bool := fun c => match env.find? c with | some (.thmInfo _) => true | _ => false
  -- generated companions of a declaration (projections, constructors, recursors, matchers) are not
  -- hypotheses; the structure itself is walked through its fields (step 4)
  let aux : Name → Bool := fun c =>
    env.isProjectionFn c || env.isConstructor c || isAuxRecursor env c || isRecCore env c
      || isNoConfusion env c || Meta.isMatcherCore env c || ((privateToUserName? c).getD c).isInternal
  let bad : Name → Bool := fun c =>
    ours c && !covered c && !asPrinted c && !isThm c && !(Meta.isInstanceCore env c) && !aux c
  let propConst : Name → MetaM Bool := fun c => do
    match env.find? c with
    | some ci => forallTelescopeReducing ci.type fun _ b => return b.isProp
    | none => return false
  let unf : Name → Bool := fun c => bad c && match env.find? c with
    | some (.defnInfo _) => true | _ => false
  let std : List Name := [``propext, ``Classical.choice, ``Quot.sound, ``sorryAx]
  let rootTypes : List (String × Expr) := (__ASMROOTS__ : List String).filterMap fun r =>
    match resolve r with
    | some n => match env.find? n with
      | some (.thmInfo v) => some (r, v.type) | _ => none
    | none => none
  for r in (__ASMROOTS__ : List String) do
    let some rn := resolve r | continue
    let some ci := env.find? rn | continue
    let lines ← liftTermElabM do
      let mut lines : Array String := #[]
      -- step 1: unfold the head while it is a non-Definition project definition (the root's type is a
      -- Prop, so every head on its spine is a Prop definition)
      lines ← auditAsmSpine (fun c => unf c) ci.type #[] fun xs body => do
        let mut ls : Array String := #[]
        let mut used : Array String := #[]
        for x in xs do
          let d ← x.fvarId!.getDecl
          -- an anonymous instance binder is `inst`; a second one with that name gets `#<position>`
          let bn0 := toString d.userName.eraseMacroScopes
          let bn := if used.contains bn0 then s!"{bn0}#{used.size}" else bn0
          used := used.push bn
          let t := d.type
          -- review fix 1: a binder whose type is a project structure or class (any sort) with a Prop field
          -- (recursively), or `Fact P`, is a hypothesis: the conjunction of its Prop fields (and each field
          -- of several) gets the goal/restates checks; a project one is listed under the structure's name
          let hyp : Name → Bool := fun s => s == ``Fact || (ours s && !covered s)
          let pfs ← match (← whnfR t).getAppFn with
            | .const s _ => if hyp s then auditAsmPropFields hyp x "" [] else pure #[]
            | _ => pure #[]
          if !pfs.isEmpty then
            let conj := pfs.pop.foldr (fun (_, a) acc => mkAnd a acc) pfs.back!.2
            let targets := (if pfs.size > 1 then pfs.map (fun (f, ft) => (s!"{bn}.{f}", ft)) else #[]).push (bn, conj)
            for (b, ft) in targets do
              if ← auditAsmDefEq ft body then ls := ls.push s!"DEPS-GOAL {r}\t{b}"
              for (o, ot) in rootTypes do
                if o != r then
                  if ← auditAsmRestates ft ot then ls := ls.push s!"DEPS-RESTATES {r}\t{b}\t{o}"
            match (← whnfR t).getAppFn with
            | .const s _ =>
              if s != ``Fact && !(← isProp t) then
                let mut cs : Array Name := #[s]
                for (_, ft) in pfs do
                  for c in ft.getUsedConstants.filter bad do
                    if !cs.contains c then cs := cs.push c
                ls := ls.push s!"DEPS-BINDER {r}\t{bn}\t{← auditAsmOneLine t}"
                ls := ls.push s!"DEPS-ASM {r}\tstruct\t{bn}\t{",".intercalate (cs.toList.map toString)}\t{← auditAsmOneLine t}"
            | _ => pure ()
          -- re-check fix: a project structure or class with a Prop field (recursively) occurring
          -- ANYWHERE in the type, not as its head (`∀ m, ParamSetup m`, `ParamSetup n × ℕ`,
          -- `Unit → ParamSetup n`, a subtype or Option/List wrapper): its Prop fields, closed over its
          -- parameters, get the goal/restates checks (also on the open conjunction, an instance); a
          -- non-Prop binder is listed under the structure's name (a Prop one already is, kind prop)
          let inner ← if pfs.isEmpty then auditAsmContained hyp t [] else pure #[]
          if !inner.isEmpty then
            let mut cs : Array Name := #[]
            for (s, conj, fs) in inner do
              if !cs.contains s then cs := cs.push s
              let ctargets := (if fs.size > 1 then fs.map (fun (f, ft) => (s!"{bn}.{s}.{f}", ft)) else #[]).push (s!"{bn}.{s}", conj)
              for (cb, cft) in ctargets do
                let isGoal ← forallTelescope cft fun _ e => do
                  return (← auditAsmDefEq cft body) || (← auditAsmDefEq e body)
                if isGoal then ls := ls.push s!"DEPS-GOAL {r}\t{cb}"
                for (o, ot) in rootTypes do
                  if o != r then
                    let rs ← forallTelescope cft fun _ e => do
                      return (← auditAsmRestates cft ot) || (← auditAsmRestates e ot)
                    if rs then ls := ls.push s!"DEPS-RESTATES {r}\t{cb}\t{o}"
              for (_, ft) in fs do
                for c in ft.getUsedConstants.filter bad do
                  if !cs.contains c then cs := cs.push c
            if !(← isProp t) then
              ls := ls.push s!"DEPS-BINDER {r}\t{bn}\t{← auditAsmOneLine t}"
              ls := ls.push s!"DEPS-ASM {r}\tstruct\t{bn}\t{",".intercalate (cs.toList.map toString)}\t{← auditAsmOneLine t}"
          if ← isProp t then
            ls := ls.push s!"DEPS-BINDER {r}\t{bn}\t{← auditAsmOneLine t}"
            -- the benchmarks "H = goal" and "H restates a paper result": a Prop binder definitionally
            -- the conclusion, or another index result's statement or an instance of its conclusion
            if ← auditAsmDefEq t body then
              ls := ls.push s!"DEPS-GOAL {r}\t{bn}"
            for (o, ot) in rootTypes do
              if o != r then
                if ← auditAsmRestates t ot then ls := ls.push s!"DEPS-RESTATES {r}\t{bn}\t{o}"
            let cs := t.getUsedConstants.filter bad
            if !cs.isEmpty then
              ls := ls.push s!"DEPS-ASM {r}\tprop\t{bn}\t{",".intercalate (cs.toList.map toString)}\t{← auditAsmOneLine t}"
          else
            -- step 3 (F2): the Prop parts of a data binder's type
            let mut cs : Array Name := #[]
            for p in auditAsmParts t #[] do
              for c in p.getUsedConstants.filter bad do
                if !cs.contains c then cs := cs.push c
            if !cs.isEmpty then
              ls := ls.push s!"DEPS-ASM {r}\tdata\t{bn}\t{",".intercalate (cs.toList.map toString)}\t{← auditAsmOneLine t}"
            -- step 4: a structure or class binder's Prop fields, flattened, recursion stopping at
            -- Definition rows (and at constants not the project's)
            match (← whnfR t).getAppFn with
            | .const s _ =>
              if ours s && !covered s then
                for (f, fcs, ft) in ← auditAsmFields bad (fun s' => ours s' && !covered s') x [] do
                  ls := ls.push s!"DEPS-ASM {r}\tfield\t{bn}.{f}\t{",".intercalate (fcs.toList.map toString)}\t{← auditAsmOneLine ft}"
            | _ => pure ()
        -- step 5 (F3): a non-Definition project Prop constant left in the body (not an index result's own)
        let mut emb : Array Name := #[]
        for c in body.getUsedConstants do
          if bad c && !emb.contains c && !resultNs.contains c then
            if ← propConst c then emb := emb.push c
        if !emb.isEmpty then
          ls := ls.push s!"DEPS-ASM {r}\tembedded\t\t{",".intercalate (emb.toList.map toString)}\t{← auditAsmOneLine body}"
        return ls
      return lines
    for l in lines do logInfo l
    let ax ← liftCoreM (collectAxioms rn)
    for a in ax do
      if !std.contains a then logInfo m!"DEPS-AX {r}\t{a}"
    logInfo m!"DEPS-ROOT {r}"
  -- F5: project data instances in the closure of the walked roots that have no index row
  let starts : List Name := (__ASMROOTS__ : List String).filterMap resolve
  let seen := auditDepWalk env ours starts {}
  for n in seen.toList do
    if Meta.isInstanceCore env n && !indexed.contains n then
      match env.find? n with
      | some ci =>
        let isP ← liftTermElabM (forallTelescopeReducing ci.type fun _ b => do return (← inferType b).isProp)
        if !isP then logInfo m!"DEPS-INST {n}"
      | none => pure ()
  -- F17: every project Prop constant taken BARE (the binder's head) as a hypothesis by any declaration
  for n in auditProjectNames env ns root do
    let some ci := env.find? n | continue
    let userDecl := match ci with
      | .thmInfo _ | .defnInfo _ | .opaqueInfo _ => true | _ => false
    if ours n && userDecl && !aux n then
      if (← findDeclarationRanges? n).isSome then
        let hs ← liftTermElabM (forallTelescope ci.type fun xs _ => do
          let mut hs : Array Name := #[]
          for x in xs do
            let t ← inferType x
            if ← isProp t then
              match t.consumeMData.getAppFn with
              | .const c _ => if ours c && !asPrinted c && !hs.contains c then
                                if ← propConst c then hs := hs.push c
              | _ => pure ()
          return hs)
        for h in hs do logInfo m!"DEPS-BARE {h}\t{n}"
  logInfo m!"DEPS-ASM-DONE"

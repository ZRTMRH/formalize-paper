
-- Axiom sweep, appended (or imported) by audits/axiom_sweep.py.
-- __NAMESPACE__ and __MIN_DECLS__ are substituted from the project config; __UNPROVED__ lists the
-- declarations a logged [DELEGATED] decision left unproved (decisions.unproved): their sorryAx
-- (and that of their compiler-generated equation lemmas and auxiliary proofs -- `eq_<n>`,
-- `eq_def`, `eq_unfold`, `proof_<n>`, `induct`, `mutual_induct`, with no source range, so not
-- written by anyone) is not a hole; any OTHER declaration reaching sorryAx -- a result whose
-- proof uses one -- still is. __GOALS__ lists the goal results' names (decisions.goal_decls),
-- resolved here as the dependency walk resolves them (as written, then namespace ++ name): a
-- goal result is never exempt, and naming one in __UNPROVED__ is an error. __PENDING__ lists the
-- declarations of a re-approval QUESTION the human has not answered (decisions.pending_reapproval,
-- U2 §3 H3): a declaration that reaches sorryAx only THROUGH them (a walk of the constants it uses
-- that stops at each one, and at their compiler-generated auxiliaries) is pending, not a hole.
open Lean in
run_cmd do
  let env ← getEnv
  let ok : List Name := [``propext, ``Classical.choice, ``Quot.sound]
  let unproved : List String := __UNPROVED__
  let nsp : Name := `__NAMESPACE__
  let resolve : String → Name := fun s =>
    let n := s.toName
    if env.contains n then n else if env.contains (nsp ++ n) then nsp ++ n else n
  let goals : List Name := (__GOALS__ : List String).map resolve
  let pending : List Name := (__PENDING__ : List String).map resolve
  for g in goals do
    if unproved.contains g.toString then
      logError m!"goal result {g} is named in a 'leave <decl> unproved' line: refused (a goal result left unproved is a stop)"
  -- a compiler-generated auxiliary's last component (axiom_sweep.GENERATED_LEAN; the dependency
  -- walk records, for the report, every auxiliary this sweep accepts, by the same rule)
  let generated : String → Bool := __GENERATED__
  let isPending : Name → Elab.Command.CommandElabM Bool := fun c => do
    let u := (privateToUserName? c).getD c
    if pending.contains u then return true
    match u with
    | .str p s =>
      if generated s && pending.contains p then return (← findDeclarationRanges? c).isNone
      else return false
    | _ => return false
  let mut total : Nat := 0; let mut holes : Nat := 0; let mut left : Nat := 0; let mut waiting : Nat := 0
  let mut bad : Array (Name × Array Name) := #[]
  for (n, _) in env.constants.toList do
    -- private declarations are mapped to their user name, not skipped as internal; and a
    -- declaration in one of the project's own modules is the project's even outside its
    -- namespace (a root-level `sorry` helper used to pass), as is one in this very file
    let u := (privateToUserName? n).getD n
    let root : Name := `__MODULE_ROOT__
    let ours := (`__NAMESPACE__).isPrefixOf u || match env.getModuleIdxFor? n with
      | some i => root != Name.anonymous && root.isPrefixOf env.header.moduleNames[i.toNat]!
      | none => true
    if ours && !u.isInternal then
      total := total + 1
      let ax ← Elab.Command.liftCoreM (collectAxioms n)
      if ax.contains ``sorryAx then
        let aux : Bool ← match u with
          | .str _ s => do
            if !(generated s) then pure false
            else pure (← findDeclarationRanges? n).isNone
          | _ => pure false
        let isGoal := goals.contains u
        if !isGoal && (unproved.contains u.toString
            || (aux && unproved.contains u.getPrefix.toString && !goals.contains u.getPrefix)) then
          left := left + 1
          logInfo m!"left unproved by a logged decision: {u}"
        else
          let mut hit := pending.isEmpty
          if !hit then
            let mut seen : NameSet := {}
            let mut stack : Array Name := #[n]
            while !stack.isEmpty && !hit do
              let c := stack.back!
              stack := stack.pop
              if !seen.contains c then
                seen := seen.insert c
                if !(← isPending c) then
                  if c == ``sorryAx then
                    hit := true
                  else
                    match env.find? c with
                    | some ci =>
                      -- as collectAxioms walks: the type, a definition's or theorem's value, an inductive's constructors
                      stack := stack ++ ci.type.getUsedConstants
                      match ci with
                      | .defnInfo v => stack := stack ++ v.value.getUsedConstants
                      | .thmInfo v => stack := stack ++ v.value.getUsedConstants
                      | .opaqueInfo v => stack := stack ++ v.value.getUsedConstants
                      | .inductInfo v => stack := stack ++ v.ctors.toArray
                      | _ => pure ()
                    | none => pure ()
          if !hit then
            waiting := waiting + 1
            logInfo m!"reaches sorryAx only through a pending re-approval question: {u}"
          else
            holes := holes + 1
            if isGoal && unproved.contains u.toString then
              logInfo m!"reaches sorryAx, a goal result (never left unproved): {u}"
            else if !unproved.isEmpty then logInfo m!"reaches sorryAx, not left unproved by a logged decision: {u}"
      let extra := ax.filter (fun a => !(ok.contains a) && a != ``sorryAx)
      if !extra.isEmpty then bad := bad.push (n, extra)
  if total < __MIN_DECLS__ then
    logError m!"swept only {total} declarations — namespace filter is wrong"
  for (n, ax) in bad do logError m!"{n} carries {ax}"
  if holes > 0 then logError m!"{holes} declarations reach sorryAx"
  logInfo m!"axiom sweep: {total} declarations, {holes} reach sorryAx, {left} left unproved by a logged decision, {waiting} pending a re-approval question, {bad.size} carry extra axioms"

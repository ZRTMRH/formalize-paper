
-- Axiom sweep, appended (or imported) by audits/axiom_sweep.py.
-- __NAMESPACE__ and __MIN_DECLS__ are substituted from the project config.
open Lean in
run_cmd do
  let env ← getEnv
  let ok : List Name := [``propext, ``Classical.choice, ``Quot.sound]
  let mut total : Nat := 0; let mut holes : Nat := 0
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
      if ax.contains ``sorryAx then holes := holes + 1
      let extra := ax.filter (fun a => !(ok.contains a) && a != ``sorryAx)
      if !extra.isEmpty then bad := bad.push (n, extra)
  if total < __MIN_DECLS__ then
    logError m!"swept only {total} declarations — namespace filter is wrong"
  for (n, ax) in bad do logError m!"{n} carries {ax}"
  if holes > 0 then logError m!"{holes} declarations reach sorryAx"
  logInfo m!"axiom sweep: {total} declarations, {holes} reach sorryAx, {bad.size} carry extra axioms"

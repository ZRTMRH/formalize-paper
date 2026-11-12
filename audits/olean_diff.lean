import Lean
open Lean

/-!
`audits/project.py` (`lean_identical`, through `_parts_differ`) runs this with `lake env lean --run` only
when `olean_parts.lean` found two builds of one module whose `constants.olean` bytes differ while every
declaration's type and value hash agrees (the refusal "its declarations or imports differ (compiled
form)"). It names EVERY field that differs, each on its own `DIFF` line, then `END` with their number. DESIGN-M7
(review M1): the fields decide whether that reason can count as a byte-layout difference (comment-only on the
source basis): only "binder names (not their annotations)" and, when nothing differs at all, "the serialized form
(sharing)" can; any other field it names is one that identical source cannot produce, and the change is refused.
Review of the M7 build, H2: it compares every constant (no stop at the first difference), and binder names and
annotations of a type and of a value are reported independently; when it cannot run, fails or prints no `END`,
the change is refused (fails closed).

The comparison is structural (`Expr.equal`: binder names and binder annotations included, unlike the hash
`olean_parts.lean` prints), field by field: the module flag, imports (with their flags), the order of the
declarations, the auxiliary constant names, and per declaration its kind, universe parameters, type, value,
recursor rules' right-hand sides, and every other field (`ConstantInfo`'s derived `==`, whose `Expr` comparison
ignores binder names and annotations, which `Expr.equal` checks above: reducibility hints, safety (`unsafe`), the
mutual block `all`, and the inductive, constructor and recursor data).

For a type or value that differs only in binder information, `namesOnly` tells binder names from binder
annotations (UNVERIFIED-LEAN: written without a Lean run; `project.py --selftest --lean` exercises it): it walks
both expressions together, at most `fuel` nodes, and gives up (the undecided message) on anything else.
-/

/-- Do `a` and `b` differ only in binder names, for every pair of `work`? `some true`: the same structure and
binder annotations; `some false`: a binder annotation differs; `none`: undecided (another difference, metadata,
or more than `fuel` nodes). -/
partial def namesOnly (work : List (Expr × Expr)) (fuel : Nat) : Option Bool :=
  match work with
  | [] => some true
  | (a, b) :: rest =>
    if a.equal b then namesOnly rest fuel
    else if fuel == 0 then none
    else match a, b with
      | .forallE _ t₁ e₁ i₁, .forallE _ t₂ e₂ i₂ =>
        if i₁ != i₂ then some false else namesOnly ((t₁, t₂) :: (e₁, e₂) :: rest) (fuel - 1)
      | .lam _ t₁ e₁ i₁, .lam _ t₂ e₂ i₂ =>
        if i₁ != i₂ then some false else namesOnly ((t₁, t₂) :: (e₁, e₂) :: rest) (fuel - 1)
      | .letE _ t₁ v₁ e₁ d₁, .letE _ t₂ v₂ e₂ d₂ =>
        if d₁ != d₂ then none else namesOnly ((t₁, t₂) :: (v₁, v₂) :: (e₁, e₂) :: rest) (fuel - 1)
      | .app f₁ x₁, .app f₂ x₂ => namesOnly ((f₁, f₂) :: (x₁, x₂) :: rest) (fuel - 1)
      | .proj s₁ j₁ x₁, .proj s₂ j₂ x₂ =>
        if s₁ == s₂ && j₁ == j₂ then namesOnly ((x₁, x₂) :: rest) (fuel - 1) else none
      | _, _ => none

/-- Which binder information differs between `a` and `b` (not `Expr.equal`), for the message. -/
def binderDiff (a b : Expr) : String :=
  match namesOnly [(a, b)] 1000000 with
  | some true => "binder names (not their annotations)"
  | some false => "binder annotations"
  | none => "binder names or annotations"

/-- The kind of a constant, for the message. -/
def kindName : ConstantInfo → String
  | .axiomInfo _ => "axiom"
  | .defnInfo _ => "def"
  | .thmInfo _ => "theorem"
  | .opaqueInfo _ => "opaque"
  | .quotInfo _ => "quot"
  | .inductInfo _ => "inductive"
  | .ctorInfo _ => "constructor"
  | .recInfo _ => "recursor"

/-- The right-hand sides of a recursor's rules (`==` compares them up to binder information only). -/
def ruleRhs : ConstantInfo → List Expr
  | .recInfo v => v.rules.map (·.rhs)
  | _ => []

/-- Every difference between two constants of one name, each a message. -/
def constDiffs (ca cb : ConstantInfo) : Array String := Id.run do
  let n := ca.name
  if kindName ca != kindName cb then
    return #[s!"the kind of `{n}` differs ({kindName ca}, {kindName cb})"]
  let mut out : Array String := #[]
  if ca.levelParams != cb.levelParams then
    out := out.push s!"the universe parameter names of `{n}` differ"
  if !(ca.type.equal cb.type) then
    out := out.push s!"{binderDiff ca.type cb.type} in the type of `{n}` differ"
  match ca.value? (allowOpaque := true), cb.value? (allowOpaque := true) with
  | some va, some vb =>
    if !(va.equal vb) then
      out := out.push s!"{binderDiff va vb} in the value of `{n}` differ"
  | none, none => pure ()
  | _, _ => out := out.push s!"the kind of `{n}` differs"
  let ra := ruleRhs ca
  let rb := ruleRhs cb
  if ra.length != rb.length || (ra.zip rb).any (fun (x, y) => !(x.equal y)) then
    out := out.push s!"the recursor rules of `{n}` differ"
  if ca.levelParams == cb.levelParams && !(ca == cb) then
    out := out.push s!"other fields of `{n}` differ (reducibility hints, safety, the mutual block, or inductive, constructor or recursor data)"
  return out

def allDiffs (a b : ModuleData) : Array String := Id.run do
  let mut out : Array String := #[]
  if a.isModule != b.isModule then
    out := out.push "the module-system flag differs"
  if a.imports != b.imports then
    out := out.push "imports differ"
  if a.constNames != b.constNames then
    out := out.push "the order of the declarations differs"
  if a.extraConstNames != b.extraConstNames then
    out := out.push "the auxiliary constant names differ"
  if a.constants.size != b.constants.size then
    out := out.push "the number of declarations differs"
  else
    for (ca, cb) in a.constants.zip b.constants do
      if ca.name != cb.name then
        out := out.push s!"the order of the declarations differs (`{ca.name}`, `{cb.name}`)"
      else
        out := out ++ constDiffs ca cb
  return out

def main (args : List String) : IO UInt32 := do
  let [a, b] := args | IO.eprintln "usage: olean_diff OLD.olean NEW.olean"; return 2
  let (ma, _) ← readModuleData a
  let (mb, _) ← readModuleData b
  let ds := allDiffs ma mb
  let ds := if ds.isEmpty then #["no field differs (the module flag, imports, declaration order, auxiliary names, and every declaration's kind, universe parameters, type, value, recursor rules and other fields, binder information included): only the serialized form (sharing) differs"] else ds
  for d in ds do
    IO.println s!"DIFF\t{d}"
  IO.println s!"END\t{ds.size}"
  return 0

import Mathlib.Order.Lattice.Nat
import Mathlib.Algebra.Group.Even
import Mathlib.Data.Nat.GCD.Basic
import Mathlib.Data.Finset.Card
import Mathlib.Data.Int.Basic

namespace SparseNote

/-- A set `S ⊆ ℕ` is `k`-sparse if distinct elements are at distance at least `k`. -/
def Sparse (k : ℕ) (S : Set ℕ) : Prop :=
  ∀ a ∈ S, ∀ b ∈ S, a ≠ b → k ≤ Int.natAbs ((a : ℤ) - b)

/-- The multiples of `k` form a `k`-sparse set (Theorem 2.2). -/
theorem thm_2_2 (k : ℕ) (hk : 1 ≤ k) : Sparse k {m | ∃ n, m = k * n} := by
  sorry

/-- A set of naturals all of whose elements are at least 3 has minimum at least 3 (Lemma 2.3). -/
theorem lemma_2_3 (S : Set ℕ) (hne : S.Nonempty) (h : ∀ x ∈ S, 3 ≤ x) : 3 ≤ sInf S := by
  sorry

/-- In a `k`-sparse set with `k ≥ 2`, distinct elements are more than 1 apart (Lemma 2.4). -/
theorem lemma_2_4 (k : ℕ) (hk : 2 ≤ k) (S : Set ℕ) (hS : Sparse k S) :
    ∀ a ∈ S, ∀ b ∈ S, a ≠ b → 1 < Int.natAbs ((a : ℤ) - b) := by
  sorry

/-- Existence of large sparse sets (Proposition 2.5). -/
theorem prop_2_5 : ∀ k : ℕ, 1 ≤ k → ∀ N : ℕ, ∃ S : Finset ℕ,
    Sparse k ↑S ∧ S ⊆ Finset.range (N + 1) ∧ N ≤ k * S.card := by
  sorry

/-- A finite nonempty sparse set has a largest element (Lemma 2.6). -/
theorem lemma_2_6 (k : ℕ) (hk : 1 ≤ k) (S : Finset ℕ) (hne : S.Nonempty)
    (hS : Sparse k ↑S) : ∃ m ∈ S, ∀ x ∈ S, x ≤ m := by
  sorry

/-- Among any `n + 1` distinct elements of `{1, …, 2n}` two are coprime (Theorem 2.7). -/
theorem thm_2_7 (n : ℕ) (hn : 1 ≤ n) (A : Finset ℕ) (hA : A ⊆ Finset.Icc 1 (2 * n))
    (hcard : A.card = n + 1) : ∃ a ∈ A, ∃ b ∈ A, a ≠ b ∧ Nat.Coprime a b := by
  sorry

/-- For every `n ≥ 2`, `{1, …, 2n}` contains two distinct coprime elements (Corollary 2.8). -/
theorem cor_2_8 (n : ℕ) (hn : 2 ≤ n) :
    ∃ a b : ℕ, 1 ≤ a ∧ a ≤ 2 * n ∧ 1 ≤ b ∧ b ≤ 2 * n ∧ a ≠ b ∧ Nat.Coprime a b := by
  sorry

/-- A finite set is balanced if it has as many even as odd elements. -/
def Balanced (S : Finset ℕ) : Prop := (S.filter (fun n => n % 2 = 0)).card = (S.filter (fun n => n % 2 = 1)).card

/-- Every finite balanced set has even cardinality (Theorem 2.10). -/
theorem thm_2_10 (S : Finset ℕ) (hS : Balanced S) : Even S.card := by
  sorry

/-- Subtracting and re-adding (Lemma 2.11). -/
theorem lemma_2_11 (a b : ℕ) (h : b ≤ a) : a - b + b = a := by
  sorry

/-- In a `k`-sparse set with `k ≥ 1`, distinct elements are at distance at least 1 (Theorem 2.12). -/
theorem thm_2_12 (k : ℕ) (hk : 1 ≤ k) (S : Set ℕ) (hS : Sparse k S) :
    ∀ a ∈ S, ∀ b ∈ S, a ≠ b → 1 ≤ Int.natAbs ((a : ℤ) - b) := by
  sorry

end SparseNote

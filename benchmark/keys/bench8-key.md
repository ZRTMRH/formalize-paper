# bench8 key — "A note on the nested radical iteration x_{n+1} = sqrt(2 + x_n)" (M. K. Oduya, fictional; agent-made)

## Goal theorem
Theorem 2.8 (`thm:main`), tex l.128–133: for every a ≥ −2 the sequence x_n(a) (x_0 = a, x_{n+1} = sqrt(2 + x_n)) converges and lim x_n(a) = 2.
TRUE: for a ≤ 2 the sequence is nondecreasing and ≤ 2, for a ≥ 2 nonincreasing and ≥ 2 (Lemma 2.4/Cor 2.5, both true); the monotone limit L ≥ −2 satisfies f(L) = L, so L = 2 by Lemma 2.2 (true). Independently, Lemma 2.6 (true) gives |x_n − 2| ≤ 2^{-n}|a − 2| from the intended Lemma 2.3 (factor 1/2).

## Numbering
- 2.1 Definition (f, x_n(a)), l.44
- 2.2 Lemma fixed point, l.53 — DECOY
- 2.3 Lemma contraction, l.63 — BN-1
- 2.4 Lemma monotonicity, l.78 (proof l.82–90) — BN-2
- 2.5 Corollary monotone bounded, l.92
- 2.6 Lemma rate, l.107
- 2.7 Lemma limit candidate, l.117 — BN-3
- 2.8 Theorem (GOAL), l.128
- 3.1 Definition Cesàro mean, l.149 — BN-4
- 3.2 Theorem (Cauchy, cited), l.160 — BN-5
- 3.3 Corollary, l.165 — BN-6

### BN-1 — typo in a statement (bound) (Lemma 2.3, l.66)
What: printed |f(x) − 2| ≤ (1/4)|x − 2| for all x ≥ −2.
Witness: x = −1: |f(−1) − 2| = 1 > 3/4. (Fails for every x ∈ [−2, 2).)
Intended: |f(x) − 2| ≤ (1/2)|x − 2| (proof: denominator sqrt(2+x)+2 ≥ 2; Lemma 2.6's proof uses the factor 1/2).
Goal: not affected; the intended 1/2 version is true and suffices for Lemma 2.6, and the main proof goes via Cor 2.5 + Lemma 2.2 anyway.

### BN-2 — slip inside a proof only (Lemma 2.4 proof, l.83–85)
What: "Since both sides are non-negative, x ≤ sqrt(2+x) iff x² ≤ 2 + x, i.e. (x−2)(x+1) ≤ 0, which holds for −2 ≤ x ≤ 2." For x < 0 the left side is negative, and (x−2)(x+1) ≤ 0 fails on [−2, −1).
Witness: x = −3/2: x ≤ f(x) holds (−1.5 ≤ 0.707) but (x−2)(x+1) = 1.75 > 0, i.e. x² > 2 + x.
Intended: for x < 0, x < 0 ≤ f(x) trivially; for 0 ≤ x ≤ 2 square (both sides nonnegative) and use (x−2)(x+1) ≤ 0. Statement of Lemma 2.4 is correct.
Goal: not affected (statement true).

### BN-3 — vacuous statement (Lemma 2.7, l.117–120)
What: hypotheses a ≥ −2, x_n(a) → L, L ≠ 2 are jointly unsatisfiable (every such sequence tends to 2, Theorem 2.8; also any limit is ≥ 0 and a fixed point of f, hence 2 by Lemma 2.2). The conclusion L = −1 is itself impossible (sqrt(2 + (−1)) = 1 ≠ −1). The proof is formally valid (squaring gives a necessary condition, and L ∈ {2, −1}, L ≠ 2 ⇒ L = −1); the only issue is that the hypotheses are unsatisfiable. A Lean formalization is provable only vacuously.
Witness: no (a, L) satisfies the hypotheses; e.g. a = 0 gives L = 2.
Intended: "any limit L satisfies L = 2" (or: L ∈ {2, −1} before using L ≥ 0).
Goal: not affected; used only in a parenthetical "alternatively" argument in the goal proof, which is itself a contradiction step.

### BN-4 — off-by-one in a range (Definition 3.1, l.153)
What: σ_N(y) = (1/N) Σ_{n=0}^{N} y_n sums N+1 terms, but is described as "the arithmetic mean of its first N terms".
Witness: y ≡ 1, N = 1: printed σ_1 = 2, mean of first term = 1.
Intended: σ_N(y) = (1/N) Σ_{n=0}^{N−1} y_n.
Goal: not affected (goal is in Section 2). Note: Cor 3.3 and the forward direction of Thm 3.2 remain true even with the printed definition (σ_N = ((N+1)/N)·mean_{N+1} → L).

### BN-5 — cited classical result stated stronger than its source (Theorem 3.2, l.160–163)
What: Cauchy's first limit theorem (regularity of Cesàro (C,1) summation; Cauchy, Cours d'analyse 1821; Hardy, Divergent Series) is "y_n → L ⟹ σ_N(y) → L". The paper states "if and only if".
Witness: y_n = (−1)^n: σ_N(y) → 0 (|σ_N| ≤ 1/N) but y_n diverges. (Also holds with the printed Def 3.1.)
Intended: forward implication only.
Goal: not affected; Cor 3.3 uses only the forward direction.

### BN-6 — unused / unneeded hypothesis (Corollary 3.3, l.166)
What: hypothesis 0 ≤ a ≤ 2; the proof uses only Theorem 2.8, valid for all a ≥ −2. The conclusion σ_N(x(a)) → 2 holds for every a ≥ −2 (e.g. a = −2, a = 100).
Witness: a = −2 (outside the hypothesis) still gives σ_N → 2; numerically σ_20000 ≈ 1.99966.
Intended: "Let a ≥ −2".
Goal: not affected.

## Decoy — Lemma 2.2 (l.53–54): "for x ≥ −2, f(x) = x iff x = 2"
Looks suspicious because x² = x + 2 has the root −1, but f(−1) = 1 ≠ −1; f(x) = x forces x = f(x) ≥ 0, and then x = 2. Correct.

## Not defects
- Def 2.1: f maps [−2,∞) into [0,∞) ⊂ [−2,∞), so x_n is well defined for every a ≥ −2; x_n ≥ 0 for n ≥ 1 (true).
- Lemma 2.6 at n = 0 is the trivial equality-case bound; ℕ includes 0 consistently.
- Cor 2.5 at a = 2 both parts apply (constant sequence) — consistent.
- Goal proof's "continuity of f at L" needs L ≥ −2, which is noted.
- Lemma 2.6's proof cites Lemma 2.3 with factor 1/2 (mismatch with the printed 1/4 is a symptom of BN-1, not a separate defect).
- Bibliography: Cauchy's Cours d'analyse (1821) and Hardy's Divergent Series (1949) are real; Chapter V of Hardy treats Cesàro means.

## Verification
python3 (stdlib), grid x ∈ [−2, 18] step 0.001: Lemma 2.3 with 1/4 fails at 4000 grid points (all x < 2), holds with 1/2; Lemma 2.2 only fixed point 2 (f(−1) = 1); Lemma 2.4 holds on the grid; proof-slip witness x = −1.5 checked; Cor 2.5 and Lemma 2.6 checked for 401 starting values a ∈ [−2, 18] over 80/60 iterations; Theorem 2.8: |x_80 − 2| = 0 (float) for all; Def 3.1 witness σ_1(1) = 2; Theorem 3.2 witness σ_N((−1)^n) ≈ 1e−5 → 0; Cor 3.3 for a ∈ {−2, −1.5, 10, 100}: σ_20000 ≈ 2 under both definitions. pdflatex compiles (3 pages).

# bench7 key — "A short note on nilpotent and idempotent real matrices" (H. M. Vortkamp, fictional; agent-made)

## Goal theorem
Theorem 2.5 (`thm:main`, paper.tex l.99–101): Let A ∈ M_n(ℝ) (n ≥ 1) be nilpotent. Then ν(A) ≤ n. In particular A^n = 0.
TRUE: classical. Proof in the paper goes through from the corrected lemmas: Lemma 2.4 is only used for k = 0,…,ν−1 (the corrected range), giving 0 = d_0 < d_1 < … < d_ν ≤ n, so ν ≤ n; then A^n = A^{n−ν}A^ν = 0. Lemma 2.3's statement is true (only its proof has a slip), and Lemma 2.2 is correct.

## Numbering (one shared counter, per section)
- 2.1 Definition (nilpotent, index ν(A) = least k ≥ 1 with A^k = 0, idempotent, d_k = dim ker A^k)
- 2.2 Lemma (kernel chain ker A^k ⊆ ker A^{k+1}; 0 = d_0 ≤ d_1 ≤ … ≤ n)
- 2.3 Lemma (stabilisation of the kernel chain)
- 2.4 Lemma (strict increase of d_k)
- 2.5 Theorem — GOAL
- 2.6 Proposition (cyclic vectors x, Nx, …, N^{ν−1}x)
- 2.7 Lemma (sum of commuting nilpotents)
- 2.8 Proposition (idempotent symmetric ⇒ tr = rank)
- 2.9 Lemma (resolvent of an idempotent)
- 3.1 Theorem (Jacobson, cited)
- 3.2 Corollary (commutator commuting with A+B)
- 3.3 Remark (symmetry of Corollary 3.2)

### B7-1 — slip inside a proof only (Lemma 2.3, l.80–83)
What: the proof deduces from A^k(Ax) = 0 that "Hence A^k x = 0". From A^k(Ax) = 0 one gets A^{k+1}x = 0, not A^k x = 0. (The intended conclusion x ∈ ker A^{k+1} is exactly A^{k+1}x = 0, so the proof is repaired by writing "A^{k+1}x = 0, so x ∈ ker A^{k+1}".)
Witness for the invalid step: A = [[0,1],[0,0]], k = 1, x = e_2: A^1(Ax) = A e_1 = 0 but A x = e_1 ≠ 0.
Intended: statement unchanged (it is true; verified exhaustively on 3×3 {−1,0,1} matrices).
Goal: not affected — the lemma's statement is true and that is all the goal uses.

### B7-2 — off-by-one in a range (Lemma 2.4, l.87)
What: "d_k < d_{k+1} for every 0 ≤ k ≤ ν(A)". At k = ν, A^ν = A^{ν+1} = 0 so d_ν = d_{ν+1} = n. The proof's final "contradicts the minimality of ν" does not apply at k = ν.
Witness: A = 0 ∈ M_1(ℝ): ν = 1, d_1 = d_2 = 1. (Fails for every nilpotent matrix; checked on all 491 nilpotent n×n {−1,0,1} matrices, n ≤ 3.)
Intended: 0 ≤ k < ν(A) (equivalently k ≤ ν(A) − 1).
Goal: not affected — Theorem 2.5's proof explicitly applies the lemma only for k = 0,…,ν−1.

### B7-3 — vacuous statement (Proposition 2.6, l.110–114)
What: hypothesis "N^ν x ≠ 0" with ν = ν(N) is unsatisfiable, since N^ν = 0 by definition of the index. The proposition is vacuously true (the proof even derives N^{ν−1}x ≠ 0 from it and is formally valid).
Witness: for every nilpotent N and every x, N^{ν(N)} x = 0; so no (N, x) satisfies the hypotheses.
Intended: N^{ν−1} x ≠ 0 (then x, …, N^{ν−1}x are independent and span an N-invariant subspace of dimension ν).
Goal: not affected — not used.

### B7-4 — numbered lemma false as printed (Lemma 2.7, l.126–129)
What: ν(A+B) ≤ max{ν(A), ν(B)} is false; the proof's claim "either i ≥ ν(A) or m−i ≥ ν(B)" fails for 0 < i < m when m is only the max.
Witness: A = J⊗I_2, B = I_2⊗J in M_4(ℝ), J = [[0,1],[0,0]]. AB = BA, ν(A) = ν(B) = 2, but (A+B)^2 = 2AB ≠ 0, so ν(A+B) = 3.
Intended: ν(A+B) ≤ ν(A) + ν(B) − 1 (take m = ν(A)+ν(B)−1 in the binomial argument). Verified on all 5281 commuting pairs of nilpotent 3×3 {−1,0,1} matrices. The first claim "A+B is nilpotent" is true.
Goal: not affected — not used.

### B7-5 — unused / unneeded hypothesis (Proposition 2.8, l.139)
What: "and symmetric, P^T = P" is never used in the proof; tr P = rank P holds for every idempotent.
Witness: P = [[1,1],[0,0]] is idempotent, not symmetric, and tr P = rank P = 1. (tr = rank checked on all 414 idempotent n×n matrices with entries in {−1,0,1,2}, n ≤ 3.)
Intended: drop the symmetry hypothesis.
Goal: not affected.

### B7-6 — cited classical result stated stronger than its source (Theorem 3.1, l.174–177)
What: Jacobson's lemma (N. Jacobson, Ann. of Math. 36 (1935); finite-dimensional, characteristic 0: if [A,[A,B]] = 0 then [A,B] is nilpotent) gives only nilpotency. The added "in fact C^2 = 0" is not in the source and is false.
Witness: n = 3, A = J_3 (E12 + E23), B = diag(0,1,2). C = [A,B] = J_3 commutes with A, but C^2 = E13 ≠ 0 (C^3 = 0).
Intended: "then C is nilpotent" (and hence C^n = 0 by Theorem 2.5).
Goal: not affected — the goal is in Section 2 and does not use Section 3.

## Decoy — Corollary 3.2 (l.179–189)
Looks suspicious (hypothesis "[A,B] commutes with A+B" rather than with A, and the proof invokes the misquoted Theorem 3.1). It is CORRECT: with X = A+B, [X,B] = [A,B] + [B,B] = [A,B], so [X,[X,B]] = 0 and the TRUE part of Jacobson's lemma (nilpotency) applies to the pair (X,B); then Theorem 2.5 gives [A,B]^n = 0. The corollary uses only nilpotency, not the false "C^2 = 0". Verified: identity [A+B,B] = [A,B] on 1000 random 3×3 integer pairs; conclusion on all 7417 pairs (2×2 {−1,0,1} and 3×3 {0,1}) satisfying the hypothesis.

## Not defects
- Lemma 2.9 (resolvent (I+tP)^{-1} = I − t/(1+t)·P for t ≠ −1) is correct (checked exactly with Fractions on all small idempotents, several t, both orders).
- Remark 3.3 is correct (trivial).
- n ≥ 1 is assumed globally (Introduction), so the k = 0 case in Lemma 2.4's proof ("I = 0 impossible") is legitimate, and ν(A) ≥ 1 by definition.
- Lemma 2.2 and Lemma 2.3's statement are correct.
- Theorem 2.5's proof uses A^{n−ν}, fine since ν ≤ n has been shown first.
- Jacobson citation is a real paper; the matrix-form lemma is the standard finite-dimensional reading (operator versions are Kleinecke 1957 / Shirokov 1956). Do not count the attribution format as a defect.

## Verification method
python3 (stdlib, exact Fraction arithmetic): `keys/bench7-verify.py`. Exhaustive: goal (ν ≤ n, A^n = 0) and corrected/printed Lemma 2.4 on all nilpotent n×n matrices with entries in {−1,0,1}, n ≤ 3; Lemma 2.3 statement on all 3×3 {−1,0,1}; intended Lemma 2.7 bound on all commuting nilpotent 3×3 {−1,0,1} pairs; tr = rank and Lemma 2.9 on all idempotents with entries {−1,0,1,2}, n ≤ 3; decoy on exhaustive small pairs. Random: goal on 300 4×4 nilpotents S·U·adj(S). Explicit witnesses for B7-1, B7-4, B7-5, B7-6 computed. paper.pdf built with pdflatex (3 pages, no errors).

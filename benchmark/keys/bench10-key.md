# bench10 key — "Divisibility and rational roots of integer polynomials" (M. K. Olsberg, fictional; agent-made)

## Goal theorem
Theorem 2.9 (tex l.140–143): Let P ∈ ℤ[x] be monic of degree n ≥ 1 and r ∈ ℚ a root of P. Then r ∈ ℤ and r ∣ P(0).
TRUE: classical. Write r = p/q in lowest terms (q ≥ 1, as in Def 2.1); the rational root theorem (2.8, correct) gives q ∣ 1, so q = 1, and p ∣ a_0. The proof uses only Def 2.1 and Theorem 2.8, both correct; 2.8's proof is direct (does not use Lemma 2.2).

## Numbering (shared counter)
- 2.1 Definition (notation; lowest terms with q ≥ 1) — l.52
- 2.2 Lemma: a−b ∣ P(a)−P(b) — l.62
- 2.3 Corollary: congruence mod m for monic P — l.75
- 2.4 Lemma: no integer root criterion — l.85
- 2.5 Lemma: |P(a)−P(b)| = 1 ⇒ |a−b| = 1 — l.96
- 2.6 Lemma: integer roots divide a_0, |r| ≤ |a_0| — l.106
- 2.7 Proposition: 3-cycles have equal gaps — l.116
- 2.8 Theorem: rational root theorem — l.127
- 2.9 Theorem (GOAL) — l.140
- 3.1 Theorem: Eisenstein's criterion (cited, Lang) — l.155
- 3.2 Corollary: x^n − p has no rational root (n ≥ 2) — l.166
- 3.3 Corollary: monic, P(0), P(1) odd ⇒ no rational root — l.176

### B10-1 — slip inside a proof only (Lemma 2.2 proof, l.69)
What: the factorisation is printed as a^k − b^k = (a−b) Σ_{j=0}^{k−1} a^j b^{k−j}; the exponents sum to k instead of k−1.
Witness: k=1, a=3, b=2: LHS = 1, RHS = (1)·(a^0 b^1) = 2.
Intended: Σ_{j=0}^{k−1} a^j b^{k−1−j}. Statement of 2.2 is true (also for constant P).
Goal: not affected (2.9 uses only 2.8, whose proof does not use 2.2).

### B10-2 — unused / unneeded hypothesis (Corollary 2.3, l.76)
What: "P monic" is never used; the proof is m ∣ a−b ∣ P(a)−P(b), valid for all P ∈ ℤ[x].
Witness: P = 2x+1, m = 2, a = 0, b = 2: P(0)−P(2) = −4 ≡ 0 mod 2, conclusion holds for non-monic P.
Intended: drop "monic". Goal: not affected (2.3 is not used anywhere later).

### B10-3 — off-by-one in a range (Lemma 2.4, l.87; also proof l.91)
What: hypothesis checks only k ∈ {1,…,m−1}, omitting residue 0; the proof wrongly takes the residue of r in {1,…,m−1}.
Witness: P = x, m = 2: P(1) = 1 is not divisible by 2, yet 0 is an integer root.
Intended: k ∈ {0,1,…,m−1} (residue in {0,…,m−1}); then true (verified).
Goal: not affected. Corollary 3.3 cites 2.4 with m = 2; its statement (P(0), P(1) both odd) matches the corrected 2.4, so 3.3 is true.

### B10-4 — missing hypothesis at an edge case (Lemma 2.6, l.108)
What: "in particular |r| ≤ |a_0|" fails when a_0 = 0 (divisibility r ∣ 0 gives no bound). The first claim r ∣ a_0 is true.
Witness: P = x^2 − 2x (nonzero, so allowed by Def 2.1), r = 2, a_0 = 0: |2| ≤ 0 false.
Intended: add a_0 ≠ 0 (or P(0) ≠ 0) for the bound. Goal: not affected (2.6 not used by 2.9; 3.2 does not use it).

### B10-5 — vacuous statement (Proposition 2.7, l.116–118)
What: no P ∈ ℤ[x] has a 3-cycle a→b→c→a with a,b,c pairwise distinct. The proof correctly gives |a−b| = |b−c| = |c−a| = d > 0, but then (a−b)+(b−c)+(c−a) = 0 is a sum of three terms ±d, i.e. an odd multiple of d, contradiction. So the hypotheses are unsatisfiable and the proposition is vacuously true.
Witness: no satisfying (P,a,b,c) exists (proof above; search over all distinct triples in [−12,12] via integrality of Newton divided differences found 0).
Intended: the real classical statement is "an integer polynomial has no periodic points of exact period 3" (indeed none of period > 2). Goal: not affected (not used).

### B10-6 — cited classical result stated stronger than source (Theorem 3.1, l.155–161)
What: Eisenstein's criterion is cited as concluding irreducibility in ℤ[x]; Lang, Algebra (rev. 3rd ed., GTM 211), Ch. IV, Thm 3.1 concludes irreducibility in K[X] (here ℚ[x]) only. Over ℤ[x] one needs P primitive.
Witness: P = 3x + 6, p = 2: 2 ∤ 3, 2 ∣ 6, 4 ∤ 6, but 3x+6 = 3·(x+2) is reducible in ℤ[x] (3 is not a unit).
Intended: "irreducible in ℚ[x]" (or add: P primitive). Goal: not affected (3.1 not used by 2.9; the remark "x^n − p is irreducible" is true since x^n − p is monic, and 3.2 is proved from 2.9).

## Decoy
Lemma 2.5 (l.96–97): "If |P(a)−P(b)| = 1 then |a−b| = 1", with no hypothesis a ≠ b. Looks like a missing edge-case hypothesis, but it is correct: a = b forces P(a)−P(b) = 0 ≠ ±1, and otherwise a−b ∣ ±1 gives |a−b| = 1. Verified exhaustively.

## Not defects
- Def 2.1 requires q ≥ 1, matching its use in 2.9 (q ∣ 1 ⇒ q = 1). Uniqueness claim of the lowest-terms representation is true.
- Theorem 2.8 (rational root theorem) and its proof are correct, including p = 0 (then a_0 = 0, 0 ∣ 0).
- Corollary 3.3: true as stated (any integer root is even or odd, so P(r) ≡ P(0) or P(1) mod 2). Under the printed 2.4 the hypothesis "P(0) odd" is not used in the proof; this is a consequence of B10-3, not a separate defect.
- "x^n − p irreducible for every n ≥ 1" (remark after 3.1, unnumbered): true.
- Lemma 2.6 proof says "a nonzero divisor ..." — the r = 0 case is fine (then a_0 = 0); the defect is only the a_0 = 0, r ≠ 0 case (B10-4).
- Corollary 2.3 allows m = 1: fine.

## Verification method
python3 (stdlib, Fractions), script exhaustive over all polynomials of degree 1–3 with coefficients in [−3,3] plus 3000 random monic polynomials of degree ≤ 5 with coefficients in [−20,20]: Lemma 2.2 (all a,b ∈ [−5,5], including constants and non-monic, confirming 2.3's monic is unneeded), corrected 2.4 (m = 2..5), decoy 2.5, 2.6 with a_0 ≠ 0, RRT 2.8 and goal 2.9 (rational roots p/q with |p| ≤ 40, q ≤ 12), 3.2 (p ∈ {2,3,5,7}, n ∈ {2,3,4}), 3.3. Witnesses for B10-1, -2, -3, -4, -6 checked numerically; B10-5 by proof plus Newton divided-difference search over [−12,12] (0 integer 3-cycles). pdflatex compiles (3 pages).

# bench6 key — "A short self-contained route to the first supplementary law" (agent-made, quadratic residues mod an odd prime)

## Goal theorem
Theorem 2.8 (`thm:main`), tex l.148–150: "Let p be an odd prime. Then −1 is a quadratic residue modulo p if and only if p ≡ 1 (mod 4)."
TRUE: classical first supplementary law. Its proof uses Euler's criterion (Thm 2.7), which uses Prop 2.3 (only the count (p−1)/2 / distinctness for x ≤ (p−1)/2, true in the intended version), Lemma 2.5 (Lagrange, correct) and Lemma 2.6 (intended exponent (p−1)/2), and Lemma 2.2 (correct, with superfluous hypothesis). With the corrected lemmas the chain goes through. Checked for all odd primes < 400.

## Numbering (shared counter per section)
- 2.1 Definition (QR for p∤a; Legendre symbol with value 0 when p | a)
- 2.2 Lemma (x² ≡ y² iff y ≡ ±x) — BN-1
- 2.3 Proposition (squares 1²,…,((p+1)/2)² distinct; count (p−1)/2) — BN-2
- 2.4 Corollary (sum of QRs in 1..p−1 divisible by p) — BN-3
- 2.5 Lemma (Lagrange: nonzero poly of degree d over F_p has ≤ d roots) — correct
- 2.6 Lemma (a^{(p+1)/2} ≡ ±1) — BN-4
- 2.7 Theorem (Euler's criterion, every integer a) — DECOY
- 2.8 Theorem (GOAL)
- 3.1 Theorem (Wilson, cited HW Thm 80) — correct
- 3.2 Proposition (p ≡ 1 mod 4 ⇒ ((p−1)/2)!² ≡ −1) — BN-5 (proof)
- 3.3 Theorem (Fermat–Euler two squares, cited HW Ch. XX) — BN-6
- 3.4 Corollary (p ≡ 3 mod 4, p | x²+y² ⇒ p | x, p | y) — correct

### BN-1 — unused / unneeded hypothesis (Lemma 2.2, l.63)
What: "Let x, y be integers with p ∤ x." The hypothesis p ∤ x is never used in the proof (p | (x−y)(x+y) ⇒ p | x−y or p | x+y) and the equivalence holds for all integers x, y.
Witness: x = y = 0 (or x = p, y = 0): p | x, yet x² ≡ y² and y ≡ ±x both hold; exhaustive check over all x, y mod p for p < 400 confirms the equivalence without the hypothesis.
Intended: "Let x, y be integers. Then x² ≡ y² iff y ≡ ±x."
Goal: not affected (all uses — Prop 2.3 with 1 ≤ x, Lemma 2.6 with x = 1 — satisfy the hypothesis anyway).

### BN-2 — off-by-one in a range (Proposition 2.3, l.74)
What: the list of squares is printed as 1², …, ((p+1)/2)²; claimed pairwise incongruent. False: ((p+1)/2) ≡ −((p−1)/2), so the last two squares coincide.
Witness: p = 3: 1² ≡ 2² ≡ 1 (mod 3). Fails for every odd prime p (verified p < 400).
Intended: 1², …, ((p−1)/2)² (the proof itself works with 1 ≤ x < y ≤ (p−1)/2). The "in particular" count (p−1)/2 is true.
Goal: not affected — Euler's criterion only uses that there are (p−1)/2 distinct QR classes, true in the intended version.

### BN-3 — missing hypothesis at an edge case (Corollary 2.4, l.91–93)
What: "The sum of the QRs in {1,…,p−1} is divisible by p" for every odd prime p. Fails for p = 3. The proof's slip "one of p−1, p, p+1 is divisible by 3, and it is not p" is exactly the p = 3 case.
Witness: p = 3: QRs in {1,2} are {1}, sum 1, not divisible by 3. For all primes 5 ≤ p < 400 it holds.
Intended: add p > 3 (p ≥ 5).
Goal: not affected (Cor 2.4 is not used anywhere).

### BN-4 — typo in a statement (exponent) (Lemma 2.6, l.122)
What: printed "a^{(p+1)/2} ≡ 1 or a^{(p+1)/2} ≡ −1" for p ∤ a. False; the proof sets y = a^{(p−1)/2}.
Witness: p = 5, a = 2: 2³ = 8 ≡ 3 (mod 5), not ±1. (Fails for every p ≥ 5; true trivially for p = 3.)
Intended: a^{(p−1)/2} ≡ ±1.
Goal: affected only through the citation in Euler's criterion's proof; with the intended exponent the proof goes through. Goal statement remains true.

### BN-5 — slip inside a proof only (Proposition 3.2 proof, l.176–180)
What: the display writes ∏_{k=1}^{(p−1)/2}(−k²) = (−1)^{(p+1)/2} x² (correct sign is (−1)^{(p−1)/2}), and then asserts "since p ≡ 1 (mod 4), the exponent (p+1)/2 is even" (false: it is odd). The two errors cancel, so the conclusion x² ≡ −1 is correct.
Witness: p = 5, x = 2! = 2: ∏(−k²) = (−1)(−4) = 4 = +x², whereas (−1)^{3}x² = −4; and (p+1)/2 = 3 is odd.
Intended: "= (−1)^{(p−1)/2} x², and (p−1)/2 is even since p ≡ 1 (mod 4)."
Goal: not affected (Section 3; statement of Prop 3.2 true, verified for all p ≡ 1 mod 4, p < 400).

### BN-6 — cited classical result stated stronger than its source (Theorem 3.3, l.187–190)
What: Fermat–Euler two-squares theorem (Hardy–Wright Ch. XX) gives uniqueness of a² + b² = p (up to order/sign) for primes p ≡ 1 mod 4; the paper asserts uniqueness (0 < a < b) for every n > 1 all of whose prime factors are ≡ 1 mod 4. Existence holds for such n, uniqueness does not.
Witness: n = 65 = 5·13 = 1² + 8² = 4² + 7². (Other counterexamples < 200: 85, 125, 145, 185.)
Intended: "Let p ≡ 1 (mod 4) be prime. Then there is exactly one pair (a,b) with 0 < a < b and p = a² + b²." (verified for primes < 400).
Goal: not affected (only used in an unnumbered remark, which needs existence for primes).

## Decoy — Theorem 2.7 (Euler's criterion), l.130–134
Looks suspicious: stated "for every integer a", including p | a, while QR is only defined for p ∤ a. Correct: Definition 2.1 sets (a/p) = 0 when p | a, and then a^{(p−1)/2} ≡ 0 because (p−1)/2 ≥ 1 (p odd, so p ≥ 3). Verified for all a ∈ [−2p, 2p], p < 400.

## Not defects
- Lemma 2.5 (Lagrange) and its proof are correct (d = 0 case: nonzero constant has no roots).
- Wilson's theorem (3.1) is quoted correctly; HW Thm 80 is Wilson's theorem.
- Goal proof: "1 ≢ −1 because p > 2" is correct.
- Cor 3.4 is correct (p ≡ 3 mod 4 and p | x²+y² ⇒ p | x, y), verified exhaustively for p < 60, x, y < 2p.
- Unnumbered remark after Thm 3.3 ((ab⁻¹)² ≡ −1 for p = a²+b²) is correct.
- Def 2.1 restricts QR to p ∤ a; the goal's "−1 is a QR" is consistent with this.

## Verification method
Python 3 (stdlib) script, exhaustive for all odd primes p < 400: goal; count of QRs; intended Prop 2.3 and failure of printed range for every p; Cor 2.4 holds iff p > 3; Lemma 2.2 for all x, y mod p without p ∤ x; intended Lemma 2.6 and failure of printed exponent for p ≥ 5; Euler's criterion for all a ∈ [−2p, 2p] including multiples of p; Wilson; Prop 3.2 and the sign/parity slip; uniqueness of two-square representation for primes ≡ 1 mod 4 and counterexamples (65, 85, 125, 145, 185) for products; Cor 3.4 for p < 60. paper.tex compiles with pdflatex (3 pages).

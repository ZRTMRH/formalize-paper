# bench9 key — "Involutions in groups of even order: a counting note" (M. K. Oyelaran, fictional; agent-made)

Paper: `papers/bench9/paper.tex` (+ `paper.pdf`, 3 pages).

## Goal theorem
**Theorem 2.8** (tex l.122–125): *Let G be a finite group of even order. Then the number of elements of order 2 in G is odd. In particular, G contains an element of order 2.*

TRUE. Inversion σ(g)=g⁻¹ is an involution of G whose fixed-point set is F={g : g²=e} (Lemma 2.4). By Lemma 2.6 (statement correct), |F| ≡ |G| ≡ 0 (mod 2). e ∈ F, and for g ≠ e, g²=e ⇔ ord(g)=2 (corrected Lemma 2.5), so the order-2 elements are F∖{e}, of odd size |F|−1 ≥ 1. The printed proof uses only the true first clause of Cor 2.7 and Lemma 2.5 only for g ≠ e, so it goes through from the corrected lemmas. (Mathlib: `exists_prime_orderOf_dvd_card` gives existence; the odd-count part needs the pairing argument.)

## Numbering (shared counter; Remark in §3 is unnumbered)
- 2.1 Definition (order of an element), l.52
- 2.2 Lemma (g^m=e ⇔ divisibility), l.58 — **BN-1**
- 2.3 Lemma (ord(g⁻¹)=ord(g), abelian), l.68 — **BN-2**
- 2.4 Lemma (g=g⁻¹ ⇔ g²=e), l.77
- 2.5 Lemma (g²=e ⇔ ord(g)=2), l.86 — **BN-3**
- 2.6 Lemma (|X| ≡ |Fix σ| mod 2), l.99 — **BN-4** (proof only)
- 2.7 Corollary (even |X| ⇒ |Fix σ| even, ≥2 fixed points), l.112 — **BN-5**
- 2.8 Theorem — GOAL, l.122
- 3.1 Theorem (Cauchy, cited, stated correctly), l.141
- 3.2 Proposition (exponent 2 ⇒ abelian, |G| = 2^k), l.145 — **DECOY**
- 3.3 Theorem (Frobenius, cited), l.157 — **BN-6**
- 3.4 Corollary (#elements of order p ≡ −1 mod p), l.162

### BN-1 — typo in a statement (Lemma 2.2, l.59)
- What: printed "g^m = e iff **m divides ord(g)**"; divisibility is reversed. The proof (l.63–65) proves ord(g) | m.
- Witness: G = {e}, g = e, m = 2: g² = e but 2 ∤ 1 = ord(e). Also G = ℤ/2, g = 1, m = 4; and the reverse direction fails for ord(g)=2, m=1 (1 | 2 but g ≠ e).
- Intended: g^m = e ⇔ ord(g) | m (Mathlib `orderOf_dvd_iff_pow_eq_one`).
- Goal: not affected; used (in corrected form) in Lemma 2.5, Prop 3.2, Cor 3.4.

### BN-2 — unused / unneeded hypothesis (Lemma 2.3, l.69)
- What: "Let G be a finite **abelian** group". The proof uses only (g⁻¹)^k = (g^k)⁻¹, valid in every group; commutativity is never used.
- Witness (that it is unneeded): conclusion holds in every nonabelian group checked (S3, S4, A4, A5, D3–D7, Q8, ℤ2×S3, ℤ2×Q8); Mathlib `orderOf_inv` has no commutativity hypothesis.
- Intended: any finite group (or any group).
- Goal: not affected (lemma is not used in the goal proof).

### BN-3 — missing hypothesis at an edge case (Lemma 2.5, l.87)
- What: "g² = e iff ord(g) = 2" fails at g = e. The proof (l.91–92) silently skips the case ord(g)=1.
- Witness: any G, g = e: e² = e but ord(e) = 1. (Exhaustively, g = e is the only failure in every group checked.)
- Intended: for g ≠ e, g² = e ⇔ ord(g) = 2.
- Goal: not affected; the goal proof invokes it only for g ∈ F with g ≠ e (l.131–132) and handles e separately.

### BN-4 — slip inside a proof only (proof of Lemma 2.6, l.108–109)
- What: after partitioning X∖Fix σ into m two-element sets, the proof writes |X| = |Fix σ| + m; it should be |Fix σ| + 2m. As written, the conclusion "|X| ≡ |Fix σ| (mod 2)" does not follow.
- Witness: X = {1,2}, σ = swap: Fix σ = ∅, m = 1, |X| = 2 ≠ 0 + 1.
- Intended: |X| = |Fix σ| + 2m. Statement of Lemma 2.6 is correct (checked exhaustively for all involutions of sets of size ≤ 7).
- Goal: not affected (statement true; correct proof is one character away).

### BN-5 — lemma false as printed (Corollary 2.7, l.114)
- What: "|Fix σ| is even; **in particular, σ has at least two fixed points**." The second clause is false (and the proof's "an even number of fixed points is at least two" ignores 0).
- Witness: X = {1,2}, σ = swap (0 fixed points); also X = ∅.
- Intended: |Fix σ| is even; in particular, if σ has a fixed point then it has at least two.
- Goal: not affected; the goal proof uses only the first clause "|F| is even" and then e ∈ F.

### BN-6 — cited classical result stated stronger than its source (Theorem 3.3, l.158–159)
- What: Frobenius (1895) proves: if n **divides |G|**, the number of solutions of xⁿ = e in G is a multiple of n. The paper drops "n divides |G|".
- Witness: G = {e}, n = 2: one solution, not a multiple of 2. Also G = ℤ/3, n = 2: one solution.
- Intended: add the hypothesis n | |G|.
- Goal: not affected. Theorem 3.3 is used only in Cor 3.4, which applies it with n = p where p | |G| — within the source's hypothesis, so Cor 3.4 is true as stated.

## Decoy — Proposition 3.2 (l.145–155)
"If g² = e for all g, then G is abelian and |G| is a power of 2." Looks too strong (and the inverse-chain might look like the classic (ab)⁻¹ = a⁻¹b⁻¹ slip), but it is correct: the chain is ab = (ab)⁻¹ = b⁻¹a⁻¹ = ba, with the inverses in the correct order; the 2-power claim follows from the correctly stated Cauchy theorem (an element of odd prime order p would satisfy ord | 2 by corrected Lemma 2.2). The trivial group gives 2⁰. Verified on all exponent-2 groups in the test set (ℤ1, ℤ2, ℤ2², ℤ2³, ℤ2⁴); no group of exponent 2 in the set fails.

## Not a defect
- Definition 2.1 uses "least positive integer" (no ℕ-from-0 issue); existence remark is fine.
- Lemma 2.2's proof itself is correct (for the intended statement); only the statement is reversed (BN-1).
- Lemma 2.4 and its one-line proof are correct.
- Theorem 3.1 (Cauchy) is stated correctly; Cauchy's 1844 memoir in *Exercices d'analyse et de physique mathématique* 3 is the real source.
- Corollary 3.4 is true as stated (it is Frobenius's theorem for n = p | |G|; it also matches the classical "≡ −1 mod p" count); its proof uses Lemma 2.2 in corrected form.
- The unnumbered Remark (p = 2 case of Cor 3.4 recovers Thm 2.8) is correct.
- Statements are for finite G throughout (fixed in the intro), so the Prop 3.2 / Cor 3.4 statements "about G" are about finite groups.

## Verification method
Python 3 (stdlib) script `b9check.py` (writer's scratchpad): built 29 finite groups as permutation groups (ℤ1–ℤ12, D3–D7, S3, S4, A4, A5, Q8, ℤ2², ℤ2³, ℤ2⁴, ℤ3², ℤ2×S3, ℤ2×Q8, ℤ4×ℤ2) and checked, all passing:
corrected Lemma 2.2 for all g and 0 ≤ m ≤ 3|G| (and collected printed-version witnesses); Lemma 2.3 in all groups incl. 12 nonabelian ones; Lemma 2.4; Lemma 2.5 fails exactly at g = e and holds for g ≠ e; the goal (odd number of order-2 elements) for every even-order group; the decoy for every exponent-2 group; Frobenius for every n | |G| (and the misquote witnesses for n ∤ |G|); Cor 3.4 for p ∈ {2,3,5,7,11} dividing |G|. Lemma 2.6 checked exhaustively over all 352 involutions of sets of size 0–7; Cor 2.7 and the proof-slip witnesses printed (n=2 swap, n=0). pdflatex compiles cleanly (3 pages).

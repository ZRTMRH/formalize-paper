# bench4 answer key — "Greatest common divisors of the numbers 2^n − 1"

Goal theorem: **Theorem 2.6** (tex l.82): for all m, n in N (including 0, with gcd(m,0) = m), gcd(2^m − 1, 2^n − 1) = 2^gcd(m,n) − 1. TRUE (checked for 0 <= m, n < 40).

Numbering: Def 2.1, Lem 2.2, Lem 2.3, Lem 2.4, Lem 2.5, Thm 2.6, Cor 2.7, Prop 2.8, Prop 3.1, Prop 3.2, Remark (Zsigmondy), Conj 3.3.

## Planted defects (6)

### B4-1 — N starting at 0 vs 1 (Lemma 2.3, l.55)
- What: "for every n in N, a_n is odd". The paper's own convention includes 0 (Def 2.1 lists a_0 = 0), and a_0 = 0 is even. The proof's "2^n is even" also fails at n = 0. The lemma is true only for n >= 1.
- Witness: n = 0: a_0 = 2^0 - 1 = 0.
- Intended: n >= 1.
- Goal: the proof of Lemma 2.5 invokes Lemma 2.3 for arbitrary n >= 0. Lemma 2.5 is still true at n = 0 (both sides equal a_m), and the main proof handles n = 0 separately, so the goal theorem is unaffected. A literal formalization of 2.3 is unprovable.

### B4-2 — unneeded hypothesis (Lemma 2.4, l.63)
- What: the hypothesis "m <= n" is redundant: for n >= 1, m | n already implies m <= n. In N it is not needed at all: n = 0 gives a_0 = 0, which every a_m divides. The hypothesis "m >= 1" is also unnecessary, since 0 | n forces n = 0 and a_0 | a_0.
- Witness: the conclusion holds for every pair with m | n (e.g. m = 3, n = 0: 7 | 0), with or without m <= n.
- Intended: "If m | n then a_m | a_n" for all m, n in N.
- Goal: not affected.

### B4-3 — proof slip (proof of Lemma 2.5, l.77–79)
- What: Lemma 2.2 applied to (m-n, n) gives a_m = 2^n a_{m-n} + a_n. The proof writes 2^m instead of 2^n, and carries 2^m through the coprimality step. The argument still works with either power of 2.
- Witness: m = 3, n = 1: 2^n a_2 + a_1 = 2*3 + 1 = 7 = a_3, while 2^m a_2 + a_1 = 8*3 + 1 = 25 != 7.
- Intended: a_m = 2^n a_{m-n} + a_n, and then gcd(2^n, a_n) = 1.
- Statement correct. Goal: the statement is unaffected; only the proof of a lemma on the goal's path is wrong.

### B4-4 — vacuous statement (Proposition 2.8, l.110)
- What: the hypotheses "m, n >= 1, m does not divide n, a_m | a_n" are never satisfiable. By Thm 2.6, a_m | a_n gives a_m = gcd(a_m, a_n) = a_{gcd(m,n)}, so gcd(m,n) = m and m | n. The proposition and its proof are vacuously correct but say nothing.
- Witness: an exhaustive check over 1 <= m, n < 40 finds no such pair.
- Intended: probably the converse of Lemma 2.4, "a_m | a_n implies m | n", which is what the hypotheses rule out.
- Goal: not affected.

### B4-5 — typo in a modulus (Proposition 3.2, l.132)
- What: the conclusion "q ≡ 1 (mod 4p)" should be "(mod 2p)". The proof proves 2p | q - 1.
- Witness: p = 11: a_11 = 2047 = 23 * 89, and 23 ≡ 23 (mod 44). (89 ≡ 1 mod 44 happens to hold.) The mod-2p version was checked for all prime divisors of a_p with odd primes p < 62.
- Intended: q ≡ 1 (mod 2p).
- Goal: not affected.

### B4-6 — cited result stated stronger than the source (Remark citing Zsigmondy, l.143)
- What: Zsigmondy's theorem for 2^n - 1 has the exception n = 6 (and n = 1). The Remark claims a primitive prime divisor for every n >= 2.
- Witness: a_6 = 63 = 3^2 * 7, with 3 | a_2 = 3 and 7 | a_3 = 7. A search over 2 <= n < 40 finds n = 6 as the only failure.
- Intended: "for every n >= 2 with n != 6".
- Goal: not affected. The Remark's second sentence is fine, since it is conditional on such a prime existing.

## Decoy (not a defect)
- **Corollary 2.7 at m = n = 0** (l.100): gcd(a_0, a_0) = gcd(0,0) = 0, which is not 1, and gcd(0,0) = 0, which is not 1, so both sides of the "iff" are false and the corollary holds. In general a_g = 1 iff g = 1, including g = 0 (a_0 = 0). Likewise the case n = 0 of Theorem 2.6 relies on the stated convention gcd(m,0) = m, which is correct.

## Other notes
- Prop 3.1 (a_n prime implies n prime) is correct, as is its proof, which uses Lemma 2.4 with 1 < r < n.
- Conjecture 3.3 is the open Mersenne-prime conjecture; it is not a defect.

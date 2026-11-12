# bench1 answer key — "Polite numbers and odd divisors"

Goal theorem: **Theorem 2.6** (tex l.106): for every integer n >= 1, n is polite iff n is not a power of 2. TRUE (checked for n < 300).

Numbering: Def 2.1, Lem 2.2, Lem 2.3, Lem 2.4, Prop 2.5, Thm 2.6, Prop 3.1, Cor 3.2, Cor 3.3, Lem 3.4, Prop 3.5, Cor 4.1, Conj 4.2.

## Planted defects (6)

### B1-1 — proof slip (Lemma 2.3, l.75)
- What: proof says k + (2a+k-1) = 2a+2k+1; the correct sum is 2a+2k-1. Both are odd, so the conclusion survives.
- Witness: a=k=1: k+(2a+k-1) = 1+2 = 3 = 2a+2k-1, while 2a+2k+1 = 5.
- Intended: "The sum k+(2a+k-1) = 2a+2k-1 is odd".
- Statement of Lemma 2.3 is correct. Goal: not affected (Lemma 2.3 remains true; its proof is repairable).

### B1-2 — typo in bound (Proposition 2.5, l.93)
- What: "odd divisor d >= 1" should be "d > 1". As printed the proposition is false, since every n has the odd divisor 1.
- Witness: n = 1 or n = 2 (or any 2^j): d = 1 is an odd divisor, but 2 has only the trivial representation (2,1), so 2 is not polite.
- Intended: d > 1 (the proof itself uses "d >= 3").
- Goal: the proof of Thm 2.6 applies Prop 2.5 only with d = m > 1, so the goal is unaffected once 2.5 is corrected. A formalization of 2.5 as printed cannot be proved.

### B1-3 — false lemma (Corollary 3.2, l.133)
- What: claims R*(n) = d_odd(n), but removing the trivial representation gives R*(n) = d_odd(n) - 1. The proof even says "every representation other than the trivial one…", which gives the -1.
- Witness: n = 3: representations (3,1), (1,2), so R*(3) = 1, while d_odd(3) = 2 (divisors 1, 3). Also n = 1: R* = 0, d_odd = 1.
- Intended: R*(n) = d_odd(n) - 1 (checked for n < 300).
- Goal: not affected (not used).

### B1-4 — missing hypothesis at an edge case (Lemma 3.4, l.151)
- What: "for every k >= 1, T_k is polite" fails at k = 1, since T_1 = 1 and the representation (1,1) has length 1.
- Witness: k = 1: R*(1) = 0; 1 = 2^0 is not polite (consistent with Thm 2.6).
- Intended: k >= 2.
- Goal: not affected.

### B1-5 — unneeded hypothesis (Proposition 3.5, l.161)
- What: "p prime with p >= 5" is stronger than needed. The statement and proof hold for every odd prime, including p = 3: R(3) = 2 with representations (3,1) and (1,2). The proof uses only that p is odd.
- Witness: p = 3 satisfies the conclusion; R(p) = 2 checked for all odd primes < 300.
- Intended: "p an odd prime" (or p >= 3).
- Goal: not affected.

### B1-6 — cited result stated stronger than the source (Section 4, l.174)
- What: Bertrand's postulate / Chebyshev's theorem is quoted as "for every integer n >= 1 there is a prime p with n < p < 2n". It fails for n = 1. The source result is for n > 1 (equivalently, n < p <= 2n for n >= 1).
- Witness: n = 1: there is no integer strictly between 1 and 2.
- Intended: "for every integer n >= 2" (which is all that Cor 4.1 uses, since Cor 4.1 assumes n >= 2).
- Goal: not affected. Cor 4.1 itself is true.

## Decoy (not a defect)
- **Corollary 3.3** (l.142), R(2^j) = 1 for all j >= 0, including j = 0 (n = 1). This is correct: 1 has exactly one odd divisor and exactly one representation (1,1). Also, Thm 2.6 includes n = 1 = 2^0, which is correctly impolite.

## Other notes
- Mason (1912) is cited only as background for Prop 3.1; this is not a planted defect.
- Conjecture 4.2 is an open-style statement, not a defect.

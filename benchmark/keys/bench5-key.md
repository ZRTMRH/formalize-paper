# bench5 answer key — "Divisibility and coprimality in large subsets of {1,…,2n}"

Goal theorem: **Theorem 2.5** (tex l.79): for n >= 1, every A ⊆ [2n] with |A| >= n+1 contains distinct a, b with a | b. TRUE (checked exhaustively for n <= 7).

Numbering: Def 2.1, Lem 2.2, Prop 2.3, Lem 2.4, Thm 2.5, Prop 3.1, Prop 3.2, Lem 3.3, Remark (Erdős–Szekeres).

## Planted defects (6)

### B5-1 — unneeded hypothesis (Lemma 2.2, l.50)
- What: "k >= 1" is unnecessary. gcd(k, k+1) = 1 holds for every integer k, including k = 0 (gcd(0,1) = 1) and negative k.
- Witness: k = 0 or k = -5 (gcd(-5,-4) = 1). The proof never uses k >= 1.
- Intended: for every integer (or natural number) k.
- Goal: not affected.

### B5-2 — typo in a bound (Proposition 2.3, l.58)
- What: the hypothesis "|A| >= n" should be "|A| >= n+1". As printed the proposition is false, and Proposition 3.2 is itself a counterexample. The proof uses "the n+1 (or more) elements of A".
- Witness: n = 2, A = {2,4}: |A| = 2 >= n, and gcd(2,4) = 2. Also n = 1, A = {1}: there are no two distinct elements.
- Intended: |A| >= n+1.
- Goal: not affected. Lemma 3.3 cites it as a contrapositive, which works with the corrected version.

### B5-3 — proof slip (proof of Theorem 2.5, l.88)
- What: with a = 2^i q, b = 2^j q and i < j, the correct conclusion is a | b (b = 2^{j-i} a). The proof says "b | a, since a = 2^{i-j} b", but 2^{i-j} is not an integer.
- Witness: q = 3, i = 0, j = 1: a = 3, b = 6, and 6 does not divide 3.
- Intended: "Then a | b, since b = 2^{j-i} a."
- Statement correct. Goal: the statement is unaffected (an existential with a, b swapped); only the goal's proof text is wrong.

### B5-4 — definition clashes with later use (Def 2.1 "divisibility antichain", l.44, vs Proposition 3.1, l.94)
- What: Def 2.1 says there are "no a, b in A with a | b" without requiring a != b. Since a | a, the only antichain under this literal reading is the empty set. Prop 3.1 (and the Remark) use the intended meaning, with distinct a, b; the proof of 3.1 explicitly takes a != b. Read literally, Prop 3.1 is false.
- Witness: n = 1: {2} is not an antichain under Def 2.1, because 2 | 2.
- Intended: "no distinct a, b in A with a | b".
- Goal: not affected (Thm 2.5 is stated without the term).

### B5-5 — false lemma (Lemma 3.3, l.114)
- What: the second claim, "every element of A is even", is false. The proof appeals to an unstated "maximality" of A.
- Witness: n = 1, A = {1}: no two distinct elements, yet 1 is odd. Also n = 3, A = {3, 6}: gcd = 3, and 3 is odd.
- Intended: only |A| <= n (or: if A is a maximum-size set with no coprime pair, then for n >= 2 it consists of even numbers; for n = 1, {1} is also maximum).
- Goal: not affected.

### B5-6 — cited result stated stronger than the source (Remark, Erdős–Szekeres, l.129)
- What: Erdős–Szekeres requires n^2 + 1 distinct reals for a monotone subsequence of length n + 1. With n^2 terms it is false.
- Witness: n = 2: (2,1,4,3) has length 4 = n^2, and its longest monotone subsequence has length 2. In general, n decreasing blocks of length n (e.g. 3,2,1,6,5,4,9,8,7 for n = 3, longest monotone subsequence 3).
- Intended: "every sequence of n^2 + 1 distinct real numbers".
- Goal: not affected.

## Decoy (not a defect)
- **Proposition 3.2 at n = 1** (l.105): {2} has one element, so "no two of which are coprime" holds vacuously. This is correct, and it is exactly sharp for Prop 2.3 (corrected), since n+1 = 2 elements are needed.

## Other notes
- Lemma 2.4 correctly requires m >= 1 (m = 0 has no such representation).
- Theorem 2.5's hypothesis n >= 1 is harmless (for n = 0 the hypothesis |A| >= 1 cannot hold); it is not counted.
- The attribution to Erdős via Aigner–Ziegler is standard and not a planted defect.

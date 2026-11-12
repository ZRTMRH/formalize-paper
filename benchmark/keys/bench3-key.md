# bench3 answer key — "A sum–reciprocal inequality and two applications"

Goal theorem: **Theorem 2.6** (tex l.93): for n >= 1 and positive reals x_1..x_n, (sum x_i)(sum 1/x_i) >= n^2. TRUE (Cauchy–Schwarz).

Numbering: Def 2.1, Lem 2.2, Lem 2.3, Lem 2.4 (Cauchy–Schwarz), Lem 2.5, Thm 2.6, Cor 2.7, Cor 2.8, Prop 2.9 (Nesbitt), Prop 3.1.

## Planted defects (7)

### B3-1 — missing hypothesis / sign (Lemma 2.3, l.63)
- What: "for every real x != 0, x + 1/x >= 2" is false for x < 0. The proof multiplies by x, which preserves the inequality only when x > 0.
- Witness: x = -1: x + 1/x = -2 < 2.
- Intended: x > 0.
- Goal: not affected. Lemma 2.3 is used only in the final Remark, with a positive argument.

### B3-2 — unneeded hypothesis (Lemma 2.5, l.84)
- What: the hypothesis x_i >= 0 is unnecessary. (sum x_i)^2 <= n * sum x_i^2 holds for all real tuples.
- Witness: x = (1, -1): 0 <= 4. The proof via Cauchy–Schwarz (with b_i = 1) never uses the sign.
- Intended: drop "x_i >= 0".
- Goal: not affected (Lemma 2.5 is not used).

### B3-3 — proof slip (proof of Lemma 2.5, l.89)
- What: the proof applies Cauchy–Schwarz with a_i = x_i and b_i = x_i. That yields the trivial inequality (sum x_i^2)^2 <= (sum x_i^2)^2, not the claim. The text then "uses sum 1^2 = n", which only makes sense for b_i = 1.
- Witness: for x = (1,2), the choice b = x gives 25 <= 25, which does not imply 9 <= 2*5 = 10.
- Intended: b_i = 1 for all i.
- Statement correct. Goal: not affected.

### B3-4 — definition clashes with later use (Def 2.1, l.50, vs Corollary 2.7, l.106)
- What: Def 2.1 calls H(x) = (1/n) sum 1/x_i the "harmonic mean". That is the mean of the reciprocals; the harmonic mean is n / sum 1/x_i. Cor 2.7 (AM–HM) and its proof use the genuine harmonic mean. Read literally with Def 2.1, Cor 2.7 is false.
- Witness: n = 1, x = (1/2): A = 1/2, while the Def 2.1 H = 2, so A >= H fails. The genuine harmonic mean is 1/2 and gives equality.
- Intended: H(x) = n / sum(1/x_i).
- Goal: not affected (Cor 2.7 is downstream of the goal).

### B3-5 — vacuous statement (Corollary 2.8, l.115)
- What: the hypotheses sum x_i = 1 and sum 1/x_i < n^2 (with x_i > 0) contradict Theorem 2.6, so they can never hold together. The corollary is vacuously true.
- Witness: by Thm 2.6, sum 1/x_i = (sum x_i)(sum 1/x_i) >= n^2 whenever sum x_i = 1.
- Intended: probably "sum 1/x_i > n^2 implies the x_i are not all equal", or the equality case "sum 1/x_i = n^2 iff all x_i = 1/n".
- Goal: not affected.

### B3-6 — cited result stated stronger than the source (Bernoulli's inequality, Section 3, l.141–145)
- What: quoted as holding "for every real x and every n in N". The standard statement (e.g. Hardy–Littlewood–Pólya) requires x >= -1 (or x > -1). For odd n >= 3 and x < -1 it can fail.
- Witness: n = 3, x = -4: (1+x)^3 = -27 < 1 + 3(-4) = -11.
- Intended: real x >= -1 and n in N (n >= 0).
- Goal: not affected. Prop 3.1 uses x = 1/n > 0, which is covered by the correct version.

### B3-7 — N starting at 0 vs 1 (Proposition 3.1, l.150)
- What: "for every n in N, (1+1/n)^n >= 2". The paper never fixes its convention for N, and the Bernoulli paragraph just above uses n = 0 ("for n = 0 both sides equal 1"), so N contains 0 there. At n = 0, 1/n is undefined. Under Lean's 1/0 = 0 the left side is (1+0)^0 = 1 < 2. The claim needs n >= 1.
- Witness: n = 0 (left side 1, or undefined).
- Intended: n >= 1.
- Goal: not affected.

## Decoy (not a defect)
- **The proof of Nesbitt's inequality (Prop 2.9, l.124)** rewrites a/(b+c) = s/(b+c) - 1 with s = a+b+c. This looks like a slip but is correct, since s - (b+c) = a. The final bound s * (9/(2s)) - 3 = 3/2 is also correct.

## Other notes
- The Remark after Prop 3.1 is logically fine (Lemma 2.3 is applied to a positive number).
- Theorem 2.6's hypothesis n >= 1 is harmless (for n = 0 both sides are 0); it is not counted as a defect.

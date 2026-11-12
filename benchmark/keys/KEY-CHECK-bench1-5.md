# Independent check of the benchmark answer keys

Checked 2026-10-24 by an independent agent. I read all five papers in full (tex, and I spot-checked that the PDFs carry the same planted text) and all five keys. I verified every key entry by hand and with Python (stdlib only). The scripts were `b1.py`, `b2.py` and `b345.py` in the session scratchpad. They were:
- an exhaustive search over n < 400 (bench1);
- all labelled graphs with n ≤ 6, plus all degree sequences with n ≤ 6 against both the printed and the true Erdős–Gallai condition (bench2);
- 10^5 random tuples (bench3);
- 0 ≤ m, n < 60, with factorisations of 2^p − 1 for p ≤ 43 and Zsigmondy for n ≤ 40 (bench4);
- all subsets of [2n] for n ≤ 7, and Erdős–Szekeres witnesses (bench5).

I did not read any tool, protocol or audit files.

**Summary:** 31/31 planted defects confirmed. 0 wrong, 0 type mislabelled, 0 unclear. 5/5 decoys are genuinely not defects. All five goal theorems are true as stated. No substantive unplanted defects were found; only minor remarks follow (none is a mathematical error the key misses).

Theorem numbering (shared counter per section) and tex line references in the keys match the papers (to within one line).

---

## bench1 — Polite numbers

Goal: Thm 2.6 (n ≥ 1 polite ⇔ n not a power of 2). **TRUE.** The paper's proof is correct: Lemma 2.4, plus Prop 2.5 applied with d = odd part m > 1. I checked it exhaustively for n < 400, and checked that Prop 2.5's construction gives a valid (a, k) with k ≥ 2 for every odd d ≥ 3 dividing n < 200.

| Id | Verdict | Notes |
|---|---|---|
| B1-1 proof slip, Lem 2.3 | confirmed | k + (2a+k−1) = 2a+2k−1, not 2a+2k+1. Both are odd, so the lemma and its use survive. |
| B1-2 typo d ≥ 1, Prop 2.5 | confirmed | n = 2: d = 1 is an odd divisor but R*(2) = 0. The proof uses d ≥ 3. Thm 2.6 uses d = m > 1, so the goal is unaffected. |
| B1-3 false Cor 3.2 | confirmed | R*(n) = d_odd(n) − 1 holds for all n < 300. The printed version fails for every n (e.g. n = 3: R* = 1, d_odd = 2). |
| B1-4 edge case, Lem 3.4 | confirmed | T_1 = 1 has only (1,1). The intended k ≥ 2 is right. |
| B1-5 unneeded p ≥ 5, Prop 3.5 | confirmed | p = 3: (3,1), (1,2). R(p) = 2 for all odd primes < 300. (p = 2 fails, so "odd prime" is the right fix.) |
| B1-6 Bertrand misquoted (n ≥ 1) | confirmed | n = 1: no integer lies in (1,2). Cor 4.1 (n ≥ 2) is true: I checked n < 2000, and it is Bertrand's postulate for n ≥ 2. |
| Decoy Cor 3.3 (j = 0) | not a defect (confirmed) | R(2^j) = 1 for j = 0..7. |

Unplanted: none. Cosmetic only: the final Remark cites Cor 3.3 needlessly. Its claim (R(n) = 2 iff the odd part of n is prime) is true (checked n < 400). Conjecture 4.2 is a conjecture and makes no false claim.

## bench2 — Repeated degrees

Goal: Thm 2.6. **TRUE.** The degrees lie in {0..n−1} and 0 and n−1 cannot both occur (n ≥ 2), so at most n−1 values are taken by n vertices. Checked on all labelled graphs with n ≤ 6.

| Id | Verdict | Notes |
|---|---|---|
| B2-1 edge case n = 1, Lem 2.5 | confirmed | K_1: its vertex has degree 0 = n−1. The exhaustive search finds n = 1 as the only failure. |
| B2-2 proof slip "n−2 values" | confirmed | It should be n−1 values. The pigeonhole step still works. |
| B2-3 vacuous Prop 2.7 | confirmed | Its hypothesis contradicts Thm 2.6. No graph with 2 ≤ n ≤ 6 has distinct degrees. |
| B2-4 typo (n−2)/2, Prop 3.1 | confirmed | Counterexamples: n = 2 edgeless; 2K_2. The (n−1)/2 version has no counterexample for n ≤ 6. |
| B2-5 false Prop 3.2 (≥ C(n−1,2)) | confirmed | Counterexample: K_{n−1} plus an isolated vertex. The strict version (>) has no counterexample for n ≤ 6. The proof only derives ≤. |
| B2-6 Erdős–Gallai without min | confirmed | (4,2,2,2,0) passes the printed condition but is not graphic. The search also finds (5,2,2,2,1,0), (5,3,2,2,2,0), etc. The true EG condition (with min) agrees with graphicity for all n ≤ 6. Only the "if" direction breaks. |
| Decoy n ≥ 2 in Thm 2.6 | not a defect (confirmed) | — |

Unplanted: none. The Remark's arithmetic (5 > 2+1 at k = 2) is right under both versions.

## bench3 — Sum–reciprocal inequality

Goal: Thm 2.6 ((Σx)(Σ1/x) ≥ n²). **TRUE.** The Cauchy–Schwarz proof with a_i = √x_i, b_i = 1/√x_i is correct, and the discriminant proof of Cauchy–Schwarz is correct. No violation in 10^5 random tests.

| Id | Verdict | Notes |
|---|---|---|
| B3-1 x + 1/x ≥ 2 for x ≠ 0, Lem 2.3 | confirmed | x = −1 gives −2. The intended x > 0 is right. |
| B3-2 unneeded x_i ≥ 0, Lem 2.5 | confirmed | It holds for all reals (random tests; e.g. (1,−1)). |
| B3-3 proof slip b_i = x_i, Lem 2.5 | confirmed | b = x gives a tautology. b_i = 1 is needed (consistent with "Σ1² = n"). |
| B3-4 Def 2.1 "harmonic mean" | confirmed | With n = 1, x = 1/2: A = 1/2 < H_def = 2, so Cor 2.7 read literally is false. The proof of Cor 2.7 uses n/Σ(1/x_i). |
| B3-5 vacuous Cor 2.8 | confirmed | Σx = 1 forces Σ1/x ≥ n² by Thm 2.6. |
| B3-6 Bernoulli for all real x | confirmed | n = 3, x = −4: −27 < −11. There are no failures for x ≥ −1 (n < 20, grid). The "by induction" justification also needs 1+x ≥ 0. |
| B3-7 ℕ ∋ 0, Prop 3.1 | confirmed | The paper uses n = 0 in the Bernoulli paragraph. At n = 0, 1/n is undefined, or under the 1/0 = 0 convention the left side is 1 < 2. |
| Decoy Nesbitt proof | not a defect (confirmed) | a/(b+c) = s/(b+c) − 1. The numerical minimum is 1.5. |

Unplanted: none. The final Remark is logically fine. Citation details (Cauchy 1821, HLP 1934, Nesbitt Educational Times 1903) look standard. I could not verify the Nesbitt volume and page numbers offline.

## bench4 — gcd of 2ⁿ − 1

Goal: Thm 2.6. **TRUE** for all m, n ∈ ℕ including 0. I checked 0 ≤ m, n < 60. The proof is Euclid's algorithm on the exponents and is valid once B4-3 is fixed. The main proof only invokes Lem 2.5 with n ≥ 1, and handles n = 0 directly.

| Id | Verdict | Notes |
|---|---|---|
| B4-1 a_n odd for n ∈ ℕ, Lem 2.3 | confirmed | a_0 = 0. Lem 2.5 is still true at n = 0 (both sides are a_m; checked). |
| B4-2 redundant m ≤ n (and m ≥ 1), Lem 2.4 | confirmed | m ∣ n with n ≥ 1 already gives m ≤ n. The cases m ∣ 0 and 0 ∣ 0 hold trivially. |
| B4-3 proof slip 2^m vs 2^n, Lem 2.5 | confirmed | m = 3, n = 1: 2^m·a_2 + a_1 = 25 ≠ 7. The coprimality argument works with 2^n. |
| B4-4 vacuous Prop 2.8 | confirmed | No pair 1 ≤ m, n < 60 has m ∤ n and a_m ∣ a_n. The theorem implies this in general. |
| B4-5 mod 4p typo, Prop 3.2 | confirmed | The key's witness (p = 11, q = 23) is valid. There is an even simpler one: p = 3, q = 7 ≢ 1 (mod 12). In fact any Mersenne prime 2^p − 1 is ≡ 3 (mod 4), so it is never ≡ 1 (mod 4p). Every p ≤ 43 tested has a failing q. The mod 2p version holds for all tested p. |
| B4-6 Zsigmondy without n = 6 exception | confirmed | 63 = 3²·7. For 2 ≤ n ≤ 40, n = 6 is the only failure. The Remark's second sentence is correct (k = 0 is a multiple of n). |
| Decoy Cor 2.7 at m = n = 0 | not a defect (confirmed) | Cor 2.7 was checked for 0 ≤ m, n < 40. |

Unplanted: none. Prop 3.1 and its proof are correct (also checked n < 32). Lucas 1878 and Zsigmondy 1892 citations are correct.

## bench5 — Divisibility in subsets of [2n]

Goal: Thm 2.5. **TRUE** by the odd-part pigeonhole argument, once B5-3 is fixed. Checked exhaustively for n ≤ 7.

| Id | Verdict | Notes |
|---|---|---|
| B5-1 unneeded k ≥ 1, Lem 2.2 | confirmed | gcd(0,1) = 1 and gcd(−5,−4) = 1. The proof does not use k ≥ 1. |
| B5-2 typo \|A\| ≥ n, Prop 2.3 | confirmed | n = 2, A = {2,4}. Also n = 1, A = {1} or {2}. |
| B5-3 proof slip "b ∣ a" | confirmed | It should be a ∣ b with b = 2^{j−i}a. |
| B5-4 antichain definition without a ≠ b | confirmed | Read literally, only ∅ is an antichain, so Prop 3.1 is false (n = 1, {2}). Prop 3.1's proof uses a ≠ b. |
| B5-5 false Lem 3.3 ("all even") | confirmed | {1} for n = 1; {3} for n = 2; {3,6} for n = 3. The proof appeals to "maximality", which is never stated. The key's corrected variant holds: for n ≥ 2, every maximum-size coprime-free set is all even (checked n ≤ 7, where it is uniquely {2,4,…,2n}). |
| B5-6 Erdős–Szekeres with n² | confirmed | (2,1,4,3) has longest monotone subsequence 2, and the n = 3 block example gives 3. Every permutation of 5 elements has one of length ≥ 3, as n² + 1 predicts. |
| Decoy Prop 3.2 at n = 1 | not a defect (confirmed) | — |

Unplanted: none. Lemma 3.3's first claim relies on the contrapositive of Prop 2.3. With Prop 2.3 as printed, that contrapositive would give \|A\| ≤ n−1, which is false (Prop 3.2), so the dependency only works with B5-2 corrected. This is a consequence of B5-2, not a separate defect.

---

## Overall
- Key entries: 31 confirmed, 0 wrong, 0 type mislabelled, 0 unclear. Every intended correction is right, and every goal-impact claim is right: no defect makes a goal false, and every on-path defect is repairable.
- Decoys: 5/5 confirmed as non-defects.
- Unplanted defects: none of substance. Minor remarks:
  - bench4 has a simpler witness for B4-5;
  - bench1's Remark cites Cor 3.3 needlessly;
  - the "unneeded hypothesis" items (B1-5, B3-2, B4-2, B5-1) make statements that are true but weaker than possible. They are not errors, so a tool that does not flag them is not missing anything false.
- Goal theorems: all five are true as stated and have valid proofs once the on-path slips are fixed.

## Independent check of the planted-defect benchmark, bench6–10

All 30 planted defects are confirmed, all 5 decoys are correct, and all 5 goal theorems are true. I found no unplanted defects, and no paper needs changing. There is one optional wording fix to the bench8 key.

**How I checked.** For each paper I read the tex in full and formed my own view of every numbered item before opening its key. I then checked the keys with my own stdlib Python script (exact Fractions where it matters), kept in the checker's session scratchpad and not published. I did not run or read the writers' scripts.

- **PDFs:** I extracted the text of all five with pdftotext. Item numbering matches the keys exactly, and every defect I spot-checked appears in the PDF as in the tex. Each PDF was built from the current tex (timestamps within one second).
- **Line numbers:** every location in the keys is within ±2 tex lines.

### bench6 (quadratic residues; goal Thm 2.8, −1 is a QR iff p ≡ 1 mod 4)
| Entry | Verdict | Notes |
|---|---|---|
| BN-1, unused hypothesis (L2.2, l.63) | confirmed | The hypothesis p∤x is never used; the equivalence holds for all x, y (checked for p<300). |
| BN-2, off-by-one (P2.3, l.74) | confirmed | Fails for every odd prime p<300; the version with (p−1)/2 holds. |
| BN-3, missing edge case (C2.4) | confirmed | Fails only at p=3 (sum of QRs is 1); holds for 5≤p<300. |
| BN-4, exponent typo (L2.6, l.122) | confirmed | Fails for p≥5 (p=5, a=2 gives 3); the (p−1)/2 version holds. |
| BN-5, proof slip (P3.2, l.176–180) | confirmed | Checked that ∏(−k²) = (−1)^{(p−1)/2}x²; the statement holds. |
| BN-6, citation stated too strongly (T3.3) | confirmed | 65 = 1²+8² = 4²+7² and 125 = 2²+11² = 5²+10²; uniqueness holds for primes ≡ 1 mod 4. |
| Decoy, Euler's criterion (T2.7) | confirmed correct | Checked for all a in [−2p, 2p]. |
| Goal | true | The proof works once 2.3 and 2.6 are corrected. Cor 3.4 and Wilson also check out. |

### bench7 (nilpotent matrices; goal Thm 2.5, ν(A) ≤ n)
| Entry | Verdict | Notes |
|---|---|---|
| B7-1, proof slip (L2.3, l.82) | confirmed | "A^k x = 0" should read A^{k+1}x = 0. |
| B7-2, off-by-one (L2.4, l.87) | confirmed | At k=ν, d_ν = d_{ν+1}; the goal's proof only uses k<ν. |
| B7-3, vacuous (P2.6) | confirmed | N^ν x ≠ 0 can never hold; the proof is formally valid. |
| B7-4, false lemma (L2.7) | confirmed | For J⊗I and I⊗J, (A+B)² = 2AB ≠ 0. The intended bound ν(A)+ν(B)−1 is right. |
| B7-5, unused hypothesis (P2.8) | confirmed | Symmetry is never used. |
| B7-6, citation stated too strongly (Jacobson, T3.1) | confirmed | With A=J₃, B=diag(0,1,2): C=J₃, AC=CA, C² = E13 ≠ 0. |
| Decoy (C3.2) | confirmed correct | [A+B, B] = [A, B]; only the nilpotency part of Jacobson is needed. |
| Goal | true | — |

I also checked the inverse formula in L2.9 exactly: its coefficient t − t/(1+t) − t²/(1+t) is 0.

### bench8 (√(2+x) iteration; goal Thm 2.8, x_n → 2)
| Entry | Verdict | Notes |
|---|---|---|
| BN-1, bound typo (L2.3) | confirmed | At x=−1: 1 > 0.75. The 1/2 version holds on a grid over [−2, 18]. |
| BN-2, proof slip (L2.4, l.83–85) | confirmed | (x−2)(x+1) ≤ 0 fails on [−2, −1); the statement holds. |
| BN-3, vacuous (L2.7) | confirmed | The hypotheses are unsatisfiable. See the key-wording fix below. |
| BN-4, off-by-one (D3.1, l.153) | confirmed | The sum has N+1 terms but is called "the mean of the first N". |
| BN-5, citation stated too strongly (Cauchy "iff") | confirmed | y_n = (−1)^n. |
| BN-6, unused hypothesis (C3.3) | confirmed | Starting at a = −2, −1.5, 5 or 100 the means still tend to 2 numerically. |
| Decoy (L2.2) | confirmed correct | f(−1) = 1. |
| Goal | true | — |

### bench9 (involutions; goal Thm 2.8, the number of elements of order 2 is odd)
| Entry | Verdict | Notes |
|---|---|---|
| BN-1, divisibility reversed (L2.2) | confirmed | — |
| BN-2, unused "abelian" (L2.3) | confirmed | — |
| BN-3, missing edge case (L2.5) | confirmed | Fails at g = e. |
| BN-4, proof slip (L2.6, l.109) | confirmed | Should be +2m. |
| BN-5, false (C2.7) | confirmed | A swap of two points has 0 fixed points. |
| BN-6, Frobenius missing "n divides \|G\|" | confirmed | Fails for Z3 with n=2. |
| Decoy (P3.2) | confirmed correct | — |
| Goal | true | — |

I checked the goal, Frobenius for n dividing |G|, and Cor 3.4 (the count ≡ −1 mod p) on S3, S4, S5, A4, D4, D6, Z6 and Z2×S3.

### bench10 (integer polynomials; goal Thm 2.9, a rational root of a monic integer polynomial is an integer dividing P(0))
| Entry | Verdict | Notes |
|---|---|---|
| B10-1, exponent slip in a proof (l.69) | confirmed | k=1, a=3, b=2 gives RHS 2 ≠ 1. |
| B10-2, unused "monic" (C2.3) | confirmed | — |
| B10-3, off-by-one (L2.4) | confirmed | P = x, m = 2. |
| B10-4, missing a₀ ≠ 0 (L2.6) | confirmed | — |
| B10-5, vacuous (P2.7) | confirmed | No triple in [−15,15]³ satisfies even the necessary divisibility conditions. |
| B10-6, Eisenstein "irreducible in Z[x]" | confirmed | Lang IV.3.1 concludes irreducibility in K[X]; 3x+6 with p=2 is a counterexample. |
| Decoy (L2.5) | confirmed correct | — |
| Goal | true | The proof uses only Def 2.1 and Thm 2.8, both correct. |

### Totals
- **Defects confirmed:** 30/30 (6 per paper). None wrong, mislabelled or unclear.
- **Decoys confirmed correct:** 5/5.
- **Goals true as stated:** 5/5. Each printed proof works once the planted defects are corrected, and no planted defect makes a goal false.
- **Unplanted defects:** none. I also checked the citations I know:
  - HW Thm 80 is Wilson's theorem.
  - IR Ch. 5 covers quadratic reciprocity.
  - The Jacobson 1935, Cauchy 1844 and Frobenius 1895 references are real.
  - Lang IV Thm 3.1 is Eisenstein's criterion.
  - Hardy, *Divergent Series* Ch. V (arithmetic means) is right as far as I recall; I could not look it up.

### Required fixes
No fixes to the papers. One optional fix to a key:

**bench8 key, BN-3.** The sentence "The proof's squaring step ignores the sign." could lead a scorer to count a "proof slip" report on Lemma 2.7 as a match. The proof is in fact logically valid: squaring only gives a necessary condition, and from L≠2 it validly concludes L=−1. Replace it with:

"The proof is formally valid (squaring gives a necessary condition, and L ∈ {2, −1}, L ≠ 2 ⇒ L = −1); the only issue is that the hypotheses are unsatisfiable."

I also recommend one scoring note. Three items are labelled "vacuous statement" (B7-3, bench8 BN-3, B10-5), and all three are true statements with valid proofs. Score a report as a hit only if it names unsatisfiable or impossible hypotheses, not if it claims the item is false.
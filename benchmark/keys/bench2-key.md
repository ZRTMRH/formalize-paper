# bench2 answer key — "Repeated degrees in finite simple graphs"

Goal theorem: **Theorem 2.6** (tex l.88): every simple graph with n >= 2 vertices has two distinct vertices of equal degree. TRUE (checked on all labelled graphs with n <= 6).

Numbering: Def 2.1, Lem 2.2, Cor 2.3, Lem 2.4, Lem 2.5, Thm 2.6, Prop 2.7, Prop 3.1, Prop 3.2, Thm 4.1 (Erdős–Gallai).

## Planted defects (6)

### B2-1 — missing hypothesis at an edge case (Lemma 2.5, l.78)
- What: "No graph has both an isolated vertex and a dominating vertex" is false for n = 1. The proof's step "u != w because their degrees n-1 and 0 differ" needs n >= 2.
- Witness: the one-vertex graph: its vertex has degree 0 = n - 1, so it is both isolated and dominating.
- Intended: graphs with n >= 2 vertices (alternatively, distinct vertices u != w).
- Goal: Thm 2.6 assumes n >= 2, so it is unaffected once 2.5 is corrected. A literal formalization of 2.5 is unprovable.

### B2-2 — proof slip (proof of Theorem 2.6, l.96)
- What: "the degrees take at most n-2 distinct values". Excluding one of {0, n-1} from an n-element set leaves n-1 values, not n-2. The pigeonhole step still works, since n-1 < n.
- Witness: n = 3, path P_3: degrees 1, 2, 1 take 2 = n-1 values (> n-2 = 1).
- Intended: "at most n-1 distinct values".
- Statement correct. Goal: the statement is unaffected; only the proof text is wrong.

### B2-3 — vacuous statement (Proposition 2.7, l.101)
- What: the hypothesis "n >= 2 and all degrees pairwise distinct" is never satisfiable, by Theorem 2.6. The proposition is therefore vacuously true and says nothing.
- Witness: an exhaustive check of all graphs with 2 <= n <= 6 finds no graph with pairwise-distinct degrees.
- Intended: none (it should be deleted, or rephrased as a step inside a proof by contradiction).
- Goal: not affected.

### B2-4 — typo in a bound (Proposition 3.1, l.116)
- What: the minimum-degree threshold (n-2)/2 should be (n-1)/2. As printed the statement is false. The proof itself uses (n-1)/2.
- Witness: n = 2 with no edges: min degree 0 >= 0 = (2-2)/2, and the graph is disconnected. Also n = 4, two disjoint edges (2K_2): min degree 1 >= 1, disconnected.
- Intended: degree >= (n-1)/2 (checked for all graphs with n <= 6).
- Goal: not affected.

### B2-5 — false lemma (Proposition 3.2, l.128)
- What: |E| >= C(n-1, 2) does not force connectivity. The sharp threshold is strict: |E| > C(n-1, 2). The proof only derives |E| <= C(n-1, 2) for disconnected G, which does not contradict the hypothesis.
- Witness: n = 2 with no edges (|E| = 0 = C(1,2)); n = 3 with one edge (|E| = 1 = C(2,2)); in general, K_{n-1} plus an isolated vertex.
- Intended: |E| > C(n-1, 2) (checked for all graphs with n <= 6).
- Goal: not affected.

### B2-6 — cited result misstated / stronger than source (Theorem 4.1, Erdős–Gallai, l.144)
- What: the right-hand side should be k(k-1) + sum_{i>k} min(d_i, k). Without the min, the condition is weaker, so the "if" direction becomes false.
- Witness: (4,2,2,2,0): the sum 10 is even and the printed inequality holds for every k (k=1: 4 <= 6; k=2: 6 <= 2+4; k=3: 8 <= 6+2; k=4: 10 <= 12; k=5: 10 <= 20). The sequence is not graphic: a degree-4 vertex on 5 vertices must be adjacent to the degree-0 vertex. Found by exhaustive search; others include (5,2,2,2,1,0) and (5,3,2,2,2,0).
- Intended: the genuine Erdős–Gallai condition with min(d_i, k).
- Goal: not affected. The Remark's example (3,2,1,0) fails both the printed and the correct condition at k = 2, so the Remark is fine.

## Decoy (not a defect)
- **The hypothesis n >= 2 in Theorem 2.6** looks like the same n = 1 problem as Lemma 2.5, but here it is necessary and correct. For n = 1 there are no two distinct vertices. For n = 2 the claim holds (degrees are 0,0 or 1,1).
- Also fine: Corollary 2.3 for edgeless graphs (0 odd-degree vertices), and Proposition 3.1 with n = 1.

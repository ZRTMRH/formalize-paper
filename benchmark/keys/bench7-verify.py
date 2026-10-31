from fractions import Fraction as F
from itertools import product
import random
def mul(A,B):
    n=len(A); return [[sum(A[i][k]*B[k][j] for k in range(n)) for j in range(n)] for i in range(n)]
def add(A,B): return [[a+b for a,b in zip(r,s)] for r,s in zip(A,B)]
def sub(A,B): return [[a-b for a,b in zip(r,s)] for r,s in zip(A,B)]
def sc(c,A): return [[c*a for a in r] for r in A]
def I(n): return [[int(i==j) for j in range(n)] for i in range(n)]
def Z(A): return all(a==0 for r in A for a in r)
def pw(A,k):
    R=I(len(A))
    for _ in range(k): R=mul(R,A)
    return R
def rank(A):
    M=[[F(x) for x in r] for r in A]; n=len(M); m=len(M[0]); r=0
    for c in range(m):
        p=next((i for i in range(r,n) if M[i][c]!=0),None)
        if p is None: continue
        M[r],M[p]=M[p],M[r]
        for i in range(n):
            if i!=r and M[i][c]!=0:
                f=M[i][c]/M[r][c]; M[i]=[a-f*b for a,b in zip(M[i],M[r])]
        r+=1
    return r
def tr(A): return sum(A[i][i] for i in range(len(A)))
def d(A,k): return len(A)-rank(pw(A,k))
def nu(A,maxk=20):
    for k in range(1,maxk):
        if Z(pw(A,k)): return k
    return None
def mats(n,vals): 
    for e in product(vals,repeat=n*n): yield [list(e[i*n:(i+1)*n]) for i in range(n)]
# Goal + Lemma 2.4 corrected / printed
cnt=0; viol24=0
for n in (1,2,3):
    for A in mats(n,(-1,0,1)):
        v=nu(A)
        if v is None: continue
        cnt+=1
        assert v<=n and Z(pw(A,n))
        assert all(d(A,k)<d(A,k+1) for k in range(v))      # corrected 2.4
        if not d(A,v)<d(A,v+1): viol24+=1                    # printed fails at k=nu
print("nilpotent matrices checked:",cnt,"; printed L2.4 fails at k=nu for",viol24)
assert viol24==cnt
# goal on 4x4 {0,1} upper-ish random nilpotents via similarity
random.seed(1)
for _ in range(300):
    n=4; U=[[random.randint(-2,2) if j>i else 0 for j in range(n)] for i in range(n)]
    S=[[random.randint(-2,2) for j in range(n)] for i in range(n)]
    if rank(S)<n: continue
    # A = S U adj(S) (scaled inverse) -> nilpotent integer matrix
    from itertools import permutations
    def det(M):
        if len(M)==1: return M[0][0]
        return sum((-1)**j*M[0][j]*det([r[:j]+r[j+1:] for r in M[1:]]) for j in range(len(M)))
    adj=[[(-1)**(i+j)*det([r[:i]+r[i+1:] for k,r in enumerate(S) if k!=j]) for j in range(n)] for i in range(n)]
    A=mul(mul(S,U),adj); assert Z(pw(A,n)) and nu(A)<=n
print("goal: 4x4 random similar-to-strict-upper nilpotents ok")
# L2.3 slip witness: A=J2,k=1,x=e2: A^k(Ax)=0 but A^k x !=0
J2=[[0,1],[0,0]]; x=[0,1]
Ax=[sum(J2[i][j]*x[j] for j in range(2)) for i in range(2)]
AAx=[sum(J2[i][j]*Ax[j] for j in range(2)) for i in range(2)]
print("L2.3 slip: A(Ax)=",AAx," Ax=",Ax)
# L2.3 statement true: exhaustive 3x3 {-1,0,1}
for A in mats(3,(-1,0,1)):
    for k in range(3):
        if d(A,k)==d(A,k+1): assert all(d(A,k+j)==d(A,k) for j in range(4))
print("L2.3 statement verified 3x3 {-1,0,1}")
# Prop 2.6 vacuous: N^nu x != 0 impossible since N^nu=0 (definition). intended: N^{nu-1}x!=0
# Lemma 2.7 counterexample
def kron(A,B):
    a=len(A);b=len(B); return [[A[i//b][j//b]*B[i%b][j%b] for j in range(a*b)] for i in range(a*b)]
A=kron(J2,I(2)); B=kron(I(2),J2)
assert mul(A,B)==mul(B,A)
print("L2.7: nu(A),nu(B),nu(A+B)=",nu(A),nu(B),nu(add(A,B)))
# intended bound nu(A)+nu(B)-1 exhaustive commuting pairs 3x3 {0,1}? check 2x2/3x3 {-1,0,1} pairs commuting nilpotent (sample)
nil3=[A_ for A_ in mats(3,(-1,0,1)) if nu(A_)]
c=0
for X in nil3:
    for Y in nil3:
        if mul(X,Y)==mul(Y,X):
            c+=1; assert nu(add(X,Y)) is not None and nu(add(X,Y))<=nu(X)+nu(Y)-1
print("intended L2.7 verified on",c,"commuting nilpotent 3x3 pairs")
# Prop 2.8 symmetric unused; trace=rank for all idempotents
c=0
for n in (1,2,3):
    for P in mats(n,(-1,0,1,2)):
        if mul(P,P)==P: c+=1; assert tr(P)==rank(P)
P=[[1,1],[0,0]]; assert mul(P,P)==P and P!=[list(r) for r in zip(*P)] and tr(P)==rank(P)==1
print("tr=rank on",c,"idempotents; nonsymmetric witness [[1,1],[0,0]]")
# Lemma 2.9 resolvent (correct)
for n in (1,2,3):
    for P in mats(n,(-1,0,1,2)):
        if mul(P,P)!=P: continue
        for t in [F(-3),F(-1,2),F(0),F(1),F(2),F(5,3)]:
            Q=add(I(n),sc(t,P)); R=sub(I(n),sc(t/(1+t),P))
            assert mul(Q,R)==I(n) and mul(R,Q)==I(n)
print("L2.9 resolvent verified")
# Thm 3.1 misquote witness
J3=[[0,1,0],[0,0,1],[0,0,0]]; D=[[0,0,0],[0,1,0],[0,0,2]]
C=sub(mul(J3,D),mul(D,J3)); print("Jacobson witness C=",C,"AC==CA",mul(J3,C)==mul(C,J3),"C^2=",mul(C,C),"C^3=",pw(C,3))
# Decoy Cor 3.2: identity [A+B,B]=[A,B] and search examples
def br(X,Y): return sub(mul(X,Y),mul(Y,X))
random.seed(2)
for _ in range(1000):
    X=[[random.randint(-3,3) for _ in range(3)] for _ in range(3)]; Y=[[random.randint(-3,3) for _ in range(3)] for _ in range(3)]
    assert br(add(X,Y),Y)==br(X,Y)
# exhaustive 2x2 {-1,0,1} pairs with [A,B] commuting with A+B -> [A,B] nilpotent ; plus 3x3 {0,1}
c=0
for n,vals in ((2,(-1,0,1)),(3,(0,1))):
    L=list(mats(n,vals))
    for X in L:
        for Y in L:
            Cm=br(X,Y)
            if mul(Cm,add(X,Y))==mul(add(X,Y),Cm):
                c+=1; assert Z(pw(Cm,n))
print("decoy Cor 3.2 verified on",c,"pairs")

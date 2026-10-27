#!/usr/bin/env python3
"""Regenerate audits/uni_math_extra.json: math symbols absent from DejaVu Serif, mapped to their
unicode-math command, kept only if the command compiles with amsmath+amssymb (bisection over
pdflatex runs). Needs fontTools and TeX Live's unicode-math-table.tex."""
import re, sys, json, subprocess, os, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); AUD = os.path.dirname(HERE)
sys.path.insert(0, AUD)
import make_report as mr
from fontTools.ttLib import TTFont
cmap = set(TTFont(subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Serif"], capture_output=True,
                                  text=True).stdout).getBestCmap())
tab = open(subprocess.run(["kpsewhich", "unicode-math-table.tex"], capture_output=True,
                          text=True).stdout.strip()).read()
SKIP = {r"\mathaccent", r"\mathbotaccent", r"\mathover", r"\mathunder", r"\mathaccentwide",
        r"\mathaccentoverlay", r"\mathalpha"}
cand = {chr(int(cp, 16)): cmd for cp, cmd, cls in
        re.findall(r'\\UnicodeMathSymbol\{"([0-9A-F]+)\}\{(\\[A-Za-z]+)\s*\}\{(\\math\w+)\}', tab)
        if int(cp, 16) not in cmap and cls not in SKIP}
existing = json.load(open(os.path.join(AUD, "uni_math_extra.json"))) if os.path.exists(os.path.join(AUD, "uni_math_extra.json")) else {}
cand = {c: v for c, v in cand.items() if c not in mr.UNI_MATH or c in existing}
D = tempfile.mkdtemp()
def ok(items):
    open(os.path.join(D, "t.tex"), "w").write("\\documentclass{article}\\usepackage{amsmath,amssymb}"
        "\\begin{document}\n" + "\n".join(f"$a {c}$ $x{c}$" for _, c in items) + "\n\\end{document}\n")
    return subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "t.tex"],
                          cwd=D, capture_output=True).returncode == 0
good = []
def test(items):
    if not items: return
    if ok(items): good.extend(items); return
    if len(items) > 1: h = len(items) // 2; test(items[:h]); test(items[h:])
test(sorted(cand.items()))
json.dump(dict(sorted(good)), open(os.path.join(AUD, "uni_math_extra.json"), "w"), ensure_ascii=False, indent=0)
print(len(cand), "candidates,", len(good), "kept")
